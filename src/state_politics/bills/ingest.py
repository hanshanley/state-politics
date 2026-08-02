"""Build the state bills table: every bill, with the party of its sponsors.

This is stream B of the project -- what state legislators actually *file*, as against what
their party's platform *says*. It reads the Open States public dump via
:mod:`state_politics.bills.openstates_dump` and produces two tables:

* ``bills.parquet`` -- one row per bill, with state/session/title/subjects, sponsor party,
  originating chamber, and recorded action/vote outcome fields.
* ``bill_sponsorships.parquet`` -- one row per sponsorship, with the sponsor's party.
* ``bill_actions.parquet`` and vote artifacts -- source action and roll-call records used for
  outcome analysis rather than inferred from titles.

Party attribution
-----------------
A bill is attributed to a party when its **primary** sponsors are all of that party; a bill with
primary sponsors from both major parties is marked ``bipartisan``, and one whose sponsors cannot
be resolved to a party is ``unknown``. Lead sponsorship is the right signal -- cosponsor lists
are often long, cross-party and procedural, so counting them equally would blur exactly the
distinction this table exists to draw.

Party comes from the dump's own membership records (a legislator's membership in a party
organization), not from the current-legislators CSV, because a bill filed in 2019 may have been
sponsored by someone no longer serving.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from .openstates_dump import state_of, stream_table

# Party normalization lives in `people`, and is imported rather than restated here: the two
# modules read the same party strings from the same source, and a second copy of the mapping
# silently drifted out of sync once already.
from .people import normalize_party

__all__ = ["attribute_party", "build_bills", "party_by_person"]



#: How far a bill's first action may precede the year its session convened before the date is
#: treated as bad source data. New Hampshire genuinely files legislative service requests the
#: year before a session opens, so a small lead is normal; a first action years earlier is not.
MAX_FILING_LEAD = 2


def _filing_year(session_year: int | None, first_action_year: int | None) -> int | None:
    """Pick the filing year, refusing first-action dates the session contradicts.

    A handful of source rows carry impossible first-action dates -- a Montana bill dated year
    ``202``, a 2019 Michigan resolution dated 1959, a 2023 West Virginia bill dated 2003. They
    are rare enough not to move any share, but ``year`` is what dates a diffusion cluster, and
    a single 1959 row would report a 2019 model bill as first appearing sixty years early. When
    the first action precedes its own session by more than `MAX_FILING_LEAD` years the date is
    not believed and the session year is used instead.
    """
    if first_action_year is None:
        return session_year
    if session_year is None:
        return first_action_year
    if first_action_year < session_year - MAX_FILING_LEAD:
        return session_year
    return first_action_year


def party_by_person(dump_path: Path | str) -> dict[str, str]:
    """Map ``person_id`` -> party code, from party-organization memberships.

    Where a legislator has belonged to more than one party organization the most recent
    membership wins, so a party switch is reflected rather than resolved arbitrarily.
    """
    party_orgs: dict[str, str] = {}
    for row in stream_table(dump_path, "opencivicdata_organization"):
        if (row.get("classification") or "") == "party":
            party_orgs[row["id"]] = normalize_party(row.get("name"))

    best: dict[str, tuple[str, str]] = {}
    for row in stream_table(dump_path, "opencivicdata_membership"):
        person_id = row.get("person_id")
        party = party_orgs.get(row.get("organization_id") or "")
        if not person_id or party is None:
            continue
        start = row.get("start_date") or ""
        previous = best.get(person_id)
        if previous is None or start >= previous[0]:
            best[person_id] = (start, party)
    return {person_id: party for person_id, (_, party) in best.items()}


def attribute_party(primary_parties: list[str], all_parties: list[str]) -> str:
    """Reduce a bill's sponsor parties to one attribution.

    Primary sponsors decide it. Cosponsor lists are frequently long, cross-party and
    procedural, so letting them vote would blur the distinction this whole table exists to
    draw; they are only consulted when no primary sponsor could be resolved.
    """
    considered = [p for p in primary_parties if p in ("D", "R")]
    if not considered:
        considered = [p for p in all_parties if p in ("D", "R")]
    if not considered:
        return "unknown"
    distinct = set(considered)
    if distinct == {"D"}:
        return "D"
    if distinct == {"R"}:
        return "R"
    return "bipartisan"


def build_bills(dump_path: Path | str, *, min_year: int = 2018):
    """Build the bills and sponsorships tables. Returns ``(bills, sponsorships)`` frames."""
    import pandas as pd

    jurisdiction_state = {
        row["id"]: state_of(row["id"])
        for row in stream_table(dump_path, "opencivicdata_jurisdiction")
    }
    sessions = {}
    for row in stream_table(dump_path, "opencivicdata_legislativesession"):
        state = jurisdiction_state.get(row.get("jurisdiction_id") or "")
        if state is None:
            continue
        sessions[row["id"]] = {
            "state": state,
            "session_identifier": row.get("identifier"),
            "session_name": row.get("name"),
            "session_start": row.get("start_date"),
        }

    person_party = party_by_person(dump_path)

    bills: dict[str, dict] = {}
    for row in stream_table(dump_path, "opencivicdata_bill"):
        session = sessions.get(row.get("legislative_session_id") or "")
        if session is None:
            continue
        # Two dates, and they mean different things. `session_year` is the year the session
        # convened and is available for every bill; `first_action_year` is when this bill was
        # actually filed but is often missing. A session is admitted when *either* overlaps the
        # window, because filtering on session start alone excluded the whole 2017-2018
        # biennium and left 20 states -- New York, Texas, Massachusetts, Illinois, Ohio and
        # others -- with no 2018 bills at all while stamping California's 2018-convened session
        # onto 5,423 bills filed in 2019-2020.
        session_year = _year_of(session["session_start"])
        first_action_year = _year_of(row.get("first_action_date"))
        if session_year is None and first_action_year is None:
            continue
        latest = max(y for y in (session_year, first_action_year) if y is not None)
        if latest < min_year:
            continue
        bills[row["id"]] = {
            "bill_id": row["id"],
            "state": session["state"],
            "session_identifier": session["session_identifier"],
            "session_name": session["session_name"],
            "session_year": session_year,
            "first_action_year": first_action_year,
            # The best available filing year: the bill's own first action when recorded and
            # credible, otherwise the year its session convened. See `_filing_year`.
            "year": _filing_year(session_year, first_action_year),
            "identifier": row.get("identifier"),
            "title": row.get("title") or "",
            "from_organization_id": row.get("from_organization_id"),
            "classification": _pg_array(row.get("classification")),
            "subject": _pg_array(row.get("subject")),
            "latest_action_date": row.get("latest_action_date"),
            "latest_action_description": row.get("latest_action_description") or "",
            "latest_passage_date": row.get("latest_passage_date"),
        }

    sponsor_rows = []
    primary_by_bill: dict[str, list[str]] = defaultdict(list)
    all_by_bill: dict[str, list[str]] = defaultdict(list)
    for row in stream_table(dump_path, "opencivicdata_billsponsorship"):
        bill_id = row.get("bill_id")
        if bill_id not in bills:
            continue
        person_id = row.get("person_id")
        party = person_party.get(person_id or "", "unknown")
        is_primary = (row.get("primary") or "").lower() in ("t", "true")
        sponsor_rows.append({
            "bill_id": bill_id,
            "state": bills[bill_id]["state"],
            "person_id": person_id,
            "sponsor_name": row.get("name"),
            "entity_type": row.get("entity_type"),
            "primary": is_primary,
            "classification": row.get("classification"),
            "party": party,
        })
        (primary_by_bill if is_primary else all_by_bill)[bill_id].append(party)
        if is_primary:
            all_by_bill[bill_id].append(party)

    for bill_id, record in bills.items():
        record["sponsor_party"] = attribute_party(
            primary_by_bill.get(bill_id, []), all_by_bill.get(bill_id, [])
        )
        record["n_sponsors"] = len(all_by_bill.get(bill_id, []))

    return pd.DataFrame(list(bills.values())), pd.DataFrame(sponsor_rows)


def _year_of(value: str | None) -> int | None:
    if value and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def _pg_array(value: str | None) -> str:
    """Flatten a PostgreSQL array literal such as ``{bill,resolution}`` to ``bill|resolution``.

    Quoted elements are respected. PostgreSQL quotes any element containing a comma, and a
    naive split shredded them: the single subject "Appointments - Individuals - Pardons and
    Paroles, Board of" became three fragments, and the debris ("Department of", "PUBLIC")
    reached the top-25 most frequent "subjects" in the built table.
    """
    if not value:
        return ""
    inner = value.strip()
    if inner.startswith("{") and inner.endswith("}"):
        inner = inner[1:-1]

    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    index = 0
    while index < len(inner):
        char = inner[index]
        if in_quotes:
            if char == "\\" and index + 1 < len(inner):
                current.append(inner[index + 1])
                index += 2
                continue
            if char == '"':
                in_quotes = False
            else:
                current.append(char)
        elif char == '"':
            in_quotes = True
        elif char == ",":
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current).strip())
    return "|".join(part for part in parts if part)


def main(argv: list[str] | None = None) -> int:
    from .outcomes import extract_outcomes

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dump", default="data/raw/openstates/2026-07-public.pgdump")
    parser.add_argument("--out-dir", default="data/processed")
    parser.add_argument("--min-year", type=int, default=2018)
    args = parser.parse_args(argv)

    dump = Path(args.dump)
    if not dump.exists():
        parser.error(f"{dump} not found - download it first (see README)")

    bills, sponsorships = build_bills(dump, min_year=args.min_year)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bills = extract_outcomes(dump, bills, out_dir)
    bills.to_parquet(out_dir / "bills.parquet", index=False)
    sponsorships.to_parquet(out_dir / "bill_sponsorships.parquet", index=False)

    print(f"bills:          {len(bills):,} (from {args.min_year})")
    print(f"states:         {bills['state'].nunique()}/50")
    print(f"sponsorships:   {len(sponsorships):,}")
    print(f"by attribution: {bills['sponsor_party'].value_counts().to_dict()}")
    print(f"recorded outcomes: {bills['recorded_outcome'].value_counts().to_dict()}")
    print(f"wrote {out_dir / 'bills.parquet'}")
    print(f"wrote {out_dir / 'bill_sponsorships.parquet'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

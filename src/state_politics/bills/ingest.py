"""Build the state bills table: every bill, with the party of its sponsors.

This is stream B of the project -- what state legislators actually *file*, as against what
their party's platform *says*. It reads the Open States public dump via
:mod:`state_politics.bills.openstates_dump` and produces two tables:

* ``bills.parquet`` -- one row per bill, with its state, session, title, subjects, and a
  party attribution derived from who sponsored it.
* ``bill_sponsorships.parquet`` -- one row per sponsorship, with the sponsor's party.

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

__all__ = ["attribute_party", "build_bills", "party_by_person"]

#: Party organization names in the dump, mapped to the project's canonical codes. Anything
#: else stays "other": several states seat genuine third parties and Nebraska's legislature is
#: formally nonpartisan, and folding those into D or R would misattribute their bills.
_PARTY_MAP = {
    "democratic": "D",
    "democrat": "D",
    "democratic-farmer-labor": "D",
    "democratic-npl": "D",
    "republican": "R",
}


def normalize_party(name: str | None) -> str:
    return _PARTY_MAP.get((name or "").strip().lower(), "other")


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
        # Session start is the reliable date: many bills have no first_action_date, and
        # session identifiers are not consistently year-prefixed across states.
        year = _year_of(session["session_start"]) or _year_of(row.get("first_action_date"))
        if year is None or year < min_year:
            continue
        bills[row["id"]] = {
            "bill_id": row["id"],
            "state": session["state"],
            "session_identifier": session["session_identifier"],
            "session_name": session["session_name"],
            "year": year,
            "identifier": row.get("identifier"),
            "title": row.get("title") or "",
            "classification": _pg_array(row.get("classification")),
            "subject": _pg_array(row.get("subject")),
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
    """Flatten a PostgreSQL array literal such as ``{bill,resolution}`` to ``bill|resolution``."""
    if not value:
        return ""
    inner = value.strip()
    if inner.startswith("{") and inner.endswith("}"):
        inner = inner[1:-1]
    parts = [p.strip().strip('"') for p in inner.split(",") if p.strip()]
    return "|".join(parts)


def main(argv: list[str] | None = None) -> int:
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
    bills.to_parquet(out_dir / "bills.parquet", index=False)
    sponsorships.to_parquet(out_dir / "bill_sponsorships.parquet", index=False)

    print(f"bills:          {len(bills):,} (from {args.min_year})")
    print(f"states:         {bills['state'].nunique()}/50")
    print(f"sponsorships:   {len(sponsorships):,}")
    print(f"by attribution: {bills['sponsor_party'].value_counts().to_dict()}")
    print(f"wrote {out_dir / 'bills.parquet'}")
    print(f"wrote {out_dir / 'bill_sponsorships.parquet'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Build the state bills table: every bill, with the party of its sponsors.

This is stream B of the project -- what state legislators actually *file*, as against what
their party's platform *says*. It reads the Open States public dump via
:mod:`state_politics.bills.openstates_dump` and produces source-bound evidence tables:

* ``bills.parquet`` -- one row per bill, with state/session/title/subjects, sponsor party,
  originating chamber, and recorded action/vote outcome fields.
* ``bill_sponsorships.parquet`` -- one row per sponsorship, with the sponsor's party.
* ``bill_actions.parquet`` and vote artifacts -- source action and roll-call records used for
  outcome analysis rather than inferred from titles.
* Abstracts, sources, versions, version links and per-bill evidence coverage -- retained
  separately, without treating snapshot text as filing-time evidence.

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
import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from ..provenance import ProvenanceLog, sha256_file, utc_now_iso
from .openstates_dump import find_pg_restore, state_of, stream_table
from .outcomes import _event_calendar_date, party_membership_intervals, resolve_party_on_date

# Party normalization lives in `people`, and is imported rather than restated here: the two
# modules read the same party strings from the same source, and a second copy of the mapping
# silently drifted out of sync once already.
from .people import normalize_party

__all__ = ["attribute_party", "build_bills", "extract_bill_evidence", "resolve_sponsor_party"]



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


def attribute_party(primary_parties: list[str], all_parties: list[str]) -> str:
    """Reduce a bill's sponsor parties to one attribution.

    An unresolved primary sponsor blocks attribution. All sponsors are used only when
    the source records no primary sponsors, and that fallback is recorded by the caller.
    """
    considered = primary_parties or all_parties
    if not considered or "unknown" in considered:
        return "unknown"
    distinct = set(considered)
    if distinct == {"D"}:
        return "D"
    if distinct == {"R"}:
        return "R"
    if distinct == {"D", "R"}:
        return "bipartisan"
    return "other"


def sponsorship_date(first_action: str | None, session_start: str | None) -> tuple[str, str]:
    """Use a credible exact first-action date; session dates do not date sponsorships."""
    if not first_action:
        return "", "missing_first_action"
    try:
        parsed = _event_calendar_date(first_action)
    except ValueError:
        return "", "invalid_first_action"
    session_year = _year_of(session_start)
    if session_year and parsed.year < session_year - MAX_FILING_LEAD:
        return "", "contradictory_first_action"
    return parsed.isoformat(), "first_action_proxy"


def resolve_sponsor_party(
    memberships: dict[str, list[tuple[str, str, str]]],
    person_id: str | None,
    state: str,
    attribution_date: str | None,
) -> tuple[str, str]:
    """Keep missing sponsor identities distinct from undated or conflicting affiliations."""
    if state == "NE":
        return "nonpartisan", "nonpartisan_legislature"
    if not person_id:
        return "unknown", "missing_person_id"
    return resolve_party_on_date(memberships.get(person_id), attribution_date)


def build_bills(dump_path: Path | str, *, min_year: int = 2018, progress=None):
    """Build the bills and sponsorships tables. Returns ``(bills, sponsorships)`` frames."""
    import pandas as pd

    source_counts = Counter()
    admission_counts = Counter()

    def source_rows(table):
        if progress:
            progress(f"Reading {table}", flush=True)
        for row in stream_table(dump_path, table):
            source_counts[table] += 1
            yield row

    jurisdiction_state = {
        row["id"]: state_of(row["id"])
        for row in source_rows("opencivicdata_jurisdiction")
    }
    sessions = {}
    for row in source_rows("opencivicdata_legislativesession"):
        state = jurisdiction_state.get(row.get("jurisdiction_id") or "")
        if state is None:
            continue
        sessions[row["id"]] = {
            "state": state,
            "session_identifier": row.get("identifier"),
            "session_name": row.get("name"),
            "session_start": row.get("start_date"),
            "session_end": row.get("end_date"),
        }

    party_orgs = {
        row["id"]: normalize_party(row.get("name"))
        for row in source_rows("opencivicdata_organization")
        if row.get("classification") == "party"
    }
    memberships = party_membership_intervals(dump_path, party_orgs)

    bills: dict[str, dict] = {}
    for row in source_rows("opencivicdata_bill"):
        session = sessions.get(row.get("legislative_session_id") or "")
        if session is None:
            admission_counts["nonstate_or_unresolved_session"] += 1
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
            admission_counts["missing_session_and_first_action_year"] += 1
            continue
        latest = max(y for y in (session_year, first_action_year) if y is not None)
        if latest < min_year:
            admission_counts["before_context_window"] += 1
            continue
        if row["id"] in bills:
            raise ValueError(f"duplicate source bill ID: {row['id']}")
        admission_counts["retained_source_context"] += 1
        party_date, party_date_basis = sponsorship_date(
            row.get("first_action_date"), session["session_start"]
        )
        bills[row["id"]] = {
            "bill_id": row["id"],
            "state": session["state"],
            "session_identifier": session["session_identifier"],
            "session_name": session["session_name"],
            "legislative_session_id": row.get("legislative_session_id"),
            "session_start_date": session["session_start"],
            "session_end_date": session["session_end"],
            "session_year": session_year,
            "first_action_year": first_action_year,
            "first_action_date": row.get("first_action_date"),
            "party_attribution_date": party_date,
            "party_attribution_date_basis": party_date_basis,
            # The best available filing year: the bill's own first action when recorded and
            # credible, otherwise the year its session convened. See `_filing_year`.
            "year": _filing_year(session_year, first_action_year),
            "identifier": row.get("identifier"),
            "title": row.get("title") or "",
            "from_organization_id": row.get("from_organization_id"),
            "classification": _pg_array(row.get("classification")),
            "classification_raw": row.get("classification"),
            "subject": _pg_array(row.get("subject")),
            "subject_raw": row.get("subject"),
            "latest_action_date": row.get("latest_action_date"),
            "latest_action_description": row.get("latest_action_description") or "",
            "latest_passage_date": row.get("latest_passage_date"),
        }

    sponsor_rows = []
    primary_by_bill: dict[str, list[str]] = defaultdict(list)
    all_by_bill: dict[str, list[str]] = defaultdict(list)
    for row in source_rows("opencivicdata_billsponsorship"):
        bill_id = row.get("bill_id")
        if bill_id not in bills:
            continue
        person_id = row.get("person_id")
        party, party_reason = resolve_sponsor_party(
            memberships, person_id, bills[bill_id]["state"],
            bills[bill_id]["party_attribution_date"],
        )
        is_primary = (row.get("primary") or "").lower() in ("t", "true")
        sponsor_rows.append({
            "sponsorship_id": row.get("id"),
            "bill_id": bill_id,
            "state": bills[bill_id]["state"],
            "person_id": person_id,
            "sponsor_name": row.get("name"),
            "entity_type": row.get("entity_type"),
            "organization_id": row.get("organization_id"),
            "primary": is_primary,
            "classification": row.get("classification"),
            "party": party,
            "party_attribution_date": bills[bill_id]["party_attribution_date"],
            "party_attribution_date_basis": bills[bill_id]["party_attribution_date_basis"],
            "party_resolution": (
                "active_membership" if party in ("D", "R", "other")
                else "nonpartisan_legislature" if party == "nonpartisan"
                else "unresolved"
            ),
            "party_resolution_reason": party_reason,
        })
        (primary_by_bill if is_primary else all_by_bill)[bill_id].append(party)
        if is_primary:
            all_by_bill[bill_id].append(party)

    for bill_id, record in bills.items():
        record["sponsor_party"] = attribute_party(
            primary_by_bill.get(bill_id, []), all_by_bill.get(bill_id, [])
        )
        record["n_sponsors"] = len(all_by_bill.get(bill_id, []))
        primary = primary_by_bill.get(bill_id, [])
        record["sponsor_attribution_basis"] = "primary" if primary else "all_sponsors_fallback"
        record["n_primary_sponsors"] = len(primary)
        record["n_unresolved_primary_sponsors"] = primary.count("unknown")
        if record["state"] == "NE":
            record["sponsor_party"] = "nonpartisan"

    frame = pd.DataFrame(list(bills.values()))
    frame.attrs["source_row_counts"] = dict(source_counts)
    frame.attrs["bill_admission_counts"] = dict(admission_counts)
    return frame, pd.DataFrame(sponsor_rows)


def extract_bill_evidence(dump_path, bills, out_dir: Path, *, progress=None) -> dict:
    """Retain source text/references without assuming their versions describe filing time."""
    import pyarrow as pa

    from .outcomes import _ParquetSink

    out_dir = Path(out_dir)
    bill_ids = set(bills["bill_id"])
    versions = {}
    counts = {name: Counter() for name in (
        "n_abstracts", "n_sources", "n_versions", "n_version_links", "n_nonempty_abstracts",
        "n_nonempty_source_urls", "n_nonempty_version_urls",
    )}
    tables = (
        ("billabstract", "bill_abstracts", ("id", "abstract", "note", "bill_id"), "n_abstracts"),
        ("billsource", "bill_sources", ("id", "note", "url", "bill_id"), "n_sources"),
        ("billversion", "bill_versions",
         ("id", "note", "date", "bill_id", "extras", "classification"), "n_versions"),
        ("billversionlink", "bill_version_links",
         ("id", "media_type", "url", "version_id"), "n_version_links"),
    )
    report = {
        "source_rows": {}, "retained_rows": {},
        "text_version_timing_review": "not_performed",
        "version_text_retrieval": "references_only_not_downloaded",
        "rich_text_automatically_used_for_filing_classification": False,
    }
    for table, filename, columns, count_key in tables:
        if progress:
            progress(f"Reading opencivicdata_{table}", flush=True)
        linked = table == "billversionlink"
        fields = (*columns, "bill_id") if linked else columns
        sink = _ParquetSink(
            out_dir / f"{filename}.parquet",
            pa.schema([(field, pa.string()) for field in fields]),
        )
        seen_ids = set()
        total = retained = 0
        try:
            for row in stream_table(dump_path, f"opencivicdata_{table}"):
                total += 1
                if set(row) != set(columns):
                    raise ValueError(f"unexpected source columns in opencivicdata_{table}")
                bill_id = versions.get(row["version_id"]) if linked else row["bill_id"]
                if bill_id not in bill_ids:
                    continue
                if not row["id"] or row["id"] in seen_ids:
                    raise ValueError(f"missing/duplicate evidence ID in opencivicdata_{table}")
                seen_ids.add(row["id"])
                if table == "billversion":
                    versions[row["id"]] = bill_id
                if linked:
                    row = {**row, "bill_id": bill_id}
                if table == "billabstract" and (row["abstract"] or "").strip():
                    counts["n_nonempty_abstracts"][bill_id] += 1
                if (row.get("url") or "").strip():
                    if table == "billsource":
                        counts["n_nonempty_source_urls"][bill_id] += 1
                    elif linked:
                        counts["n_nonempty_version_urls"][bill_id] += 1
                sink.add(row)
                counts[count_key][bill_id] += 1
                retained += 1
        finally:
            sink.close()
        report["source_rows"][table] = total
        report["retained_rows"][table] = retained
    coverage = bills[["bill_id", "state"]].copy()
    for name, counter in counts.items():
        coverage[name] = coverage["bill_id"].map(lambda key, c=counter: c.get(key, 0))
    coverage.to_parquet(out_dir / "bill_evidence_coverage.parquet", index=False)
    report["bills_with_nonempty_abstracts"] = int((coverage["n_nonempty_abstracts"] > 0).sum())
    report["bills_with_source_urls"] = int((coverage["n_nonempty_source_urls"] > 0).sum())
    report["bills_with_version_references"] = int((coverage["n_nonempty_version_urls"] > 0).sum())
    return report


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
    parser.add_argument("--dump", required=True, help="explicit, provenance-logged source snapshot")
    parser.add_argument("--out-dir", default="data/processed")
    parser.add_argument("--min-year", type=int, default=2018)
    parser.add_argument("--provenance", type=Path, default=Path("data/provenance.jsonl"))
    args = parser.parse_args(argv)

    dump = Path(args.dump)
    if not dump.exists():
        parser.error(f"{dump} not found - download it first (see README)")

    pg_restore = find_pg_restore()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "bills.parquet", "bill_sponsorships.parquet", "bill_actions.parquet",
        "vote_events.parquet", "vote_counts.parquet", "vote_party_counts.parquet",
        "bill_abstracts.parquet", "bill_sources.parquet", "bill_versions.parquet",
        "bill_version_links.parquet", "bill_evidence_coverage.parquet",
    }
    manifest_path = out_dir / "bill_extraction_manifest.json"
    occupied = [name for name in sorted(outputs) if (out_dir / name).exists()]
    if occupied or manifest_path.exists():
        raise FileExistsError(
            f"{out_dir}: existing extraction artifacts; select a new --out-dir, never overwrite"
        )
    source_hash = sha256_file(dump)
    fetches = [
        record.to_dict() for record in ProvenanceLog(args.provenance)
        if record.ok and record.content_sha256 == source_hash and record.stored_path
        and Path(record.stored_path).resolve() == dump.resolve()
    ]
    with manifest_path.open("x", encoding="utf-8") as handle:
        staging = Path(tempfile.mkdtemp(prefix=".bill-extraction-", dir=out_dir))
        manifest = {
            "schema_version": 1, "status": "incomplete", "started_at": utc_now_iso(),
            "source_path": str(dump.resolve()), "source_sha256": source_hash,
            "source_bytes": dump.stat().st_size, "source_fetch": fetches[-1] if fetches else None,
            "pg_restore": pg_restore, "min_context_year": args.min_year,
            "staging_directory": str(staging), "scientific_certification": "not_performed",
            "analysis_cutoff": None,
        }
        handle.write(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    bills, sponsorships = build_bills(dump, min_year=args.min_year, progress=print)
    if bills.empty or bills["bill_id"].isna().any() or bills["bill_id"].duplicated().any():
        raise ValueError("extraction requires a nonempty corpus with unique source bill IDs")
    manifest["source_row_counts"] = bills.attrs["source_row_counts"]
    manifest["bill_admission_counts"] = bills.attrs["bill_admission_counts"]
    manifest["evidence"] = extract_bill_evidence(dump, bills, staging, progress=print)
    print("Reading recorded actions and votes", flush=True)
    bills = extract_outcomes(dump, bills, staging)
    bills.to_parquet(staging / "bills.parquet", index=False)
    sponsorships.to_parquet(staging / "bill_sponsorships.parquet", index=False)
    import pyarrow.parquet as pq

    actual = {path.name for path in staging.iterdir()}
    if actual != outputs:
        raise ValueError(f"extraction artifact mismatch: {sorted(actual ^ outputs)}")
    manifest["artifacts"] = {
        name: {
            "sha256": sha256_file(staging / name),
            "rows": pq.ParquetFile(staging / name).metadata.num_rows,
        } for name in sorted(outputs)
    }
    manifest["state_session_year_counts"] = (
        bills.groupby(["state", "session_identifier", "year"], dropna=False)
        .size().rename("n_source_context_bills").reset_index().to_dict("records")
    )
    manifest["sponsor_party_counts"] = bills["sponsor_party"].value_counts().to_dict()
    for name in sorted(outputs):
        (staging / name).replace(out_dir / name)
    staging.rmdir()
    manifest["status"] = "complete_extraction_not_source_certification"
    manifest["completed_at"] = utc_now_iso()
    partial = manifest_path.with_suffix(".json.part")
    partial.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    partial.replace(manifest_path)
    print(f"bills:          {len(bills):,} (source context overlapping {args.min_year}+)")
    print(f"states:         {bills['state'].nunique()}/50")
    print(f"sponsorships:   {len(sponsorships):,}")
    print(f"by attribution: {bills['sponsor_party'].value_counts().to_dict()}")
    print(f"recorded outcomes: {bills['recorded_outcome'].value_counts().to_dict()}")
    print(f"wrote {out_dir / 'bills.parquet'}")
    print(f"wrote {out_dir / 'bill_sponsorships.parquet'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

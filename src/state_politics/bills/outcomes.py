"""Extract bill actions, chamber metadata, and roll-call summaries from Open States.

The title pipeline measures filing agendas. This module adds the source fields needed to ask
different questions without pretending that filing implies passage: recorded bill actions,
originating/action/vote chambers, vote results, official vote counts, and date-aware voter-party
counts. Large related tables are streamed into Parquet instead of materialized in memory.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from datetime import date as calendar_date
from pathlib import Path

from ..provenance import sha256_file, utc_now_iso

__all__ = [
    "extract_outcomes",
    "organization_chamber",
    "party_membership_intervals",
    "party_on_date",
    "recorded_outcome",
]

_CHAMBER_CLASSES = {"upper", "lower", "legislature"}
_PASSAGE_CLASSES = {"passage", "informal-passage"}
_COMMITTEE_PASSAGE_CLASSES = {
    "committee-passage",
    "committee-passage-favorable",
}


def organization_chamber(
    organization_id: str | None,
    organizations: dict[str, dict],
) -> str:
    """Resolve an organization or committee to upper/lower/legislature/unknown."""
    seen: set[str] = set()
    current = organization_id
    while current and current not in seen:
        seen.add(current)
        organization = organizations.get(current)
        if organization is None:
            break
        classification = (organization.get("classification") or "").lower()
        if classification in _CHAMBER_CLASSES:
            return classification
        current = organization.get("parent_id")
    return "unknown"


def party_membership_intervals(
    dump_path,
    party_orgs: dict[str, str],
) -> dict[str, list[tuple[str, str, str]]]:
    """Person -> dated party memberships, for resolving party at roll-call time."""
    from .openstates_dump import stream_table

    memberships: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for row in stream_table(dump_path, "opencivicdata_membership"):
        person_id = row.get("person_id")
        party = party_orgs.get(row.get("organization_id") or "")
        if not person_id or party not in ("D", "R", "other"):
            continue
        memberships[person_id].append(
            (row.get("start_date") or "", row.get("end_date") or "", party)
        )
    for rows in memberships.values():
        rows.sort(key=lambda item: item[0])
    return memberships


def party_on_date(
    intervals: list[tuple[str, str, str]] | None,
    date: str | None,
) -> str:
    """Resolve only memberships covering a known event date; never extrapolate affiliation."""
    if not intervals or not date:
        return "unknown"
    date = date[:10]
    try:
        calendar_date.fromisoformat(date)
    except ValueError:
        return "unknown"
    active = []
    for row in intervals:
        if not row[0] and not row[1]:
            return "unknown"
        for bound in row[:2]:
            if not bound:
                continue
            try:
                if calendar_date.fromisoformat(bound).isoformat() != bound:
                    return "unknown"
            except ValueError:
                return "unknown"
        if row[0] and row[1] and row[0] > row[1]:
            return "unknown"
        if (not row[0] or row[0] <= date) and (not row[1] or row[1] >= date):
            active.append(row)
    parties = {row[2] for row in active}
    return parties.pop() if len(parties) == 1 else "unknown"


def recorded_outcome(
    classes: set[str],
    passage_chambers: set[str],
    *,
    n_actions: int,
) -> str:
    """Highest classified stage, distinguishing absent from unclassified actions."""
    if n_actions < 0 or (n_actions == 0 and (classes or passage_chambers)):
        raise ValueError("action classifications contradict the recorded action count")
    if "became-law" in classes:
        return "became_law"
    if "executive-signature" in classes:
        return "signed"
    if "executive-veto" in classes or "executive-veto-line-item" in classes:
        return "vetoed"
    if "executive-receipt" in classes:
        return "sent_to_executive"
    if {"upper", "lower"} <= passage_chambers or "legislature" in passage_chambers:
        return "passed_legislature"
    if passage_chambers:
        return "passed_one_chamber"
    if classes & {"failure", "withdrawal", "committee-failure"}:
        return "recorded_failure_or_withdrawal"
    if classes:
        return "introduced_or_pending"
    return "action_stage_unclassified" if n_actions else "no_action_data"


def repair_action_missingness(bills):
    """Repair the legacy absent-action label without guessing an unclassified stage."""
    import pandas as pd

    if (
        bills["bill_id"].isna().any() or bills["bill_id"].duplicated().any()
        or bills["n_actions"].isna().any()
        or not pd.api.types.is_integer_dtype(bills["n_actions"])
        or bills["n_actions"].lt(0).any()
    ):
        raise ValueError("outcome repair requires unique bill IDs and nonnegative action counts")
    repaired = bills.copy()
    mask = repaired["recorded_outcome"].eq("no_action_data") & repaired["n_actions"].gt(0)
    repaired.loc[mask, "recorded_outcome"] = recorded_outcome(set(), set(), n_actions=1)
    return repaired


class _ParquetSink:
    """Small buffered streaming Parquet writer with an explicit stable schema."""

    def __init__(self, path: Path, schema, *, chunk_size: int = 100_000):
        self.path = path
        self.schema = schema
        self.chunk_size = chunk_size
        self.rows: list[dict] = []
        self.writer = None

    def add(self, row: dict) -> None:
        self.rows.append(row)
        if len(self.rows) >= self.chunk_size:
            self.flush()

    def flush(self) -> None:
        if not self.rows:
            return
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pylist(self.rows, schema=self.schema)
        if self.writer is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.writer = pq.ParquetWriter(
                self.path,
                self.schema,
                compression="zstd",
            )
        self.writer.write_table(table)
        self.rows.clear()

    def close(self) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        self.flush()
        if self.writer is not None:
            self.writer.close()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pylist([], schema=self.schema), self.path)


def extract_outcomes(dump_path, bills, out_dir: Path):
    """Write outcome/vote artifacts and return the bill frame with recorded-stage columns."""
    import pandas as pd
    import pyarrow as pa

    from .ingest import _pg_array
    from .openstates_dump import stream_table
    from .people import normalize_party

    out_dir = Path(out_dir)
    bill_ids = set(bills["bill_id"])
    bill_lookup = bills.set_index("bill_id")[["state", "sponsor_party"]].to_dict("index")

    organizations: dict[str, dict] = {}
    party_orgs: dict[str, str] = {}
    for row in stream_table(dump_path, "opencivicdata_organization"):
        organization_id = row["id"]
        organizations[organization_id] = {
            "name": row.get("name") or "",
            "classification": row.get("classification") or "",
            "parent_id": row.get("parent_id"),
        }
        if (row.get("classification") or "") == "party":
            party_orgs[organization_id] = normalize_party(row.get("name"))

    bills = bills.copy()
    bills["originating_chamber"] = bills["from_organization_id"].map(
        lambda organization_id: organization_chamber(organization_id, organizations)
    )

    action_schema = pa.schema(
        [
            ("action_id", pa.string()),
            ("bill_id", pa.string()),
            ("state", pa.string()),
            ("date", pa.string()),
            ("description", pa.string()),
            ("classification", pa.string()),
            ("organization_id", pa.string()),
            ("chamber", pa.string()),
            ("order", pa.int32()),
        ]
    )
    action_sink = _ParquetSink(out_dir / "bill_actions.parquet", action_schema)
    action_metrics: dict[str, dict] = defaultdict(
        lambda: {
            "n_actions": 0,
            "classes": set(),
            "passage_chambers": set(),
            "committee_passage": False,
        }
    )
    for row in stream_table(dump_path, "opencivicdata_billaction"):
        bill_id = row.get("bill_id")
        if bill_id not in bill_ids:
            continue
        classification = _pg_array(row.get("classification"))
        classes = set(classification.split("|")) if classification else set()
        chamber = organization_chamber(row.get("organization_id"), organizations)
        metrics = action_metrics[bill_id]
        metrics["n_actions"] += 1
        metrics["classes"].update(classes)
        if classes & _PASSAGE_CLASSES:
            metrics["passage_chambers"].add(chamber)
        if classes & _COMMITTEE_PASSAGE_CLASSES:
            metrics["committee_passage"] = True
        action_sink.add(
            {
                "action_id": row.get("id"),
                "bill_id": bill_id,
                "state": bill_lookup[bill_id]["state"],
                "date": row.get("date"),
                "description": row.get("description") or "",
                "classification": classification,
                "organization_id": row.get("organization_id"),
                "chamber": chamber,
                "order": int(row.get("order") or 0),
            }
        )
    action_sink.close()

    vote_schema = pa.schema(
        [
            ("vote_id", pa.string()),
            ("bill_id", pa.string()),
            ("state", pa.string()),
            ("start_date", pa.string()),
            ("identifier", pa.string()),
            ("motion_text", pa.string()),
            ("motion_classification", pa.string()),
            ("result", pa.string()),
            ("organization_id", pa.string()),
            ("chamber", pa.string()),
            ("bill_action_id", pa.string()),
            ("order", pa.int32()),
        ]
    )
    vote_sink = _ParquetSink(out_dir / "vote_events.parquet", vote_schema)
    vote_meta: dict[str, dict] = {}
    vote_metrics: dict[str, Counter] = defaultdict(Counter)
    for row in stream_table(dump_path, "opencivicdata_voteevent"):
        bill_id = row.get("bill_id")
        if bill_id not in bill_ids:
            continue
        vote_id = row["id"]
        chamber = organization_chamber(row.get("organization_id"), organizations)
        motion_classification = _pg_array(row.get("motion_classification"))
        result = row.get("result") or ""
        vote_meta[vote_id] = {
            "bill_id": bill_id,
            "state": bill_lookup[bill_id]["state"],
            "sponsor_party": bill_lookup[bill_id]["sponsor_party"],
            "start_date": row.get("start_date") or "",
        }
        vote_metrics[bill_id]["n_vote_events"] += 1
        vote_metrics[bill_id][f"vote_result_{result}"] += 1
        if "passage" in motion_classification.split("|"):
            vote_metrics[bill_id]["n_passage_votes"] += 1
        vote_sink.add(
            {
                "vote_id": vote_id,
                "bill_id": bill_id,
                "state": bill_lookup[bill_id]["state"],
                "start_date": row.get("start_date"),
                "identifier": row.get("identifier") or "",
                "motion_text": row.get("motion_text") or "",
                "motion_classification": motion_classification,
                "result": result,
                "organization_id": row.get("organization_id"),
                "chamber": chamber,
                "bill_action_id": row.get("bill_action_id"),
                "order": int(row.get("order") or 0),
            }
        )
    vote_sink.close()

    vote_count_schema = pa.schema(
        [
            ("vote_event_id", pa.string()),
            ("bill_id", pa.string()),
            ("state", pa.string()),
            ("option", pa.string()),
            ("value", pa.int32()),
        ]
    )
    vote_count_sink = _ParquetSink(out_dir / "vote_counts.parquet", vote_count_schema)
    for row in stream_table(dump_path, "opencivicdata_votecount"):
        vote_id = row.get("vote_event_id")
        metadata = vote_meta.get(vote_id or "")
        if metadata is None:
            continue
        vote_count_sink.add(
            {
                "vote_event_id": vote_id,
                "bill_id": metadata["bill_id"],
                "state": metadata["state"],
                "option": row.get("option") or "",
                "value": int(row.get("value") or 0),
            }
        )
    vote_count_sink.close()

    memberships = party_membership_intervals(dump_path, party_orgs)
    party_counts: Counter = Counter()
    for row in stream_table(dump_path, "opencivicdata_personvote"):
        vote_id = row.get("vote_event_id")
        metadata = vote_meta.get(vote_id or "")
        if metadata is None:
            continue
        party = party_on_date(
            memberships.get(row.get("voter_id") or ""),
            metadata["start_date"],
        )
        party_counts[
            (
                vote_id,
                metadata["bill_id"],
                metadata["state"],
                metadata["sponsor_party"],
                party,
                row.get("option") or "",
            )
        ] += 1
    party_rows = [
        {
            "vote_event_id": key[0],
            "bill_id": key[1],
            "state": key[2],
            "sponsor_party": key[3],
            "voter_party": key[4],
            "option": key[5],
            "n_votes": value,
        }
        for key, value in party_counts.items()
    ]
    pd.DataFrame(
        party_rows,
        columns=[
            "vote_event_id",
            "bill_id",
            "state",
            "sponsor_party",
            "voter_party",
            "option",
            "n_votes",
        ],
    ).to_parquet(out_dir / "vote_party_counts.parquet", index=False)

    bills["n_actions"] = bills["bill_id"].map(
        lambda bill_id: action_metrics[bill_id]["n_actions"]
    )
    bills["action_classifications"] = bills["bill_id"].map(
        lambda bill_id: "|".join(sorted(action_metrics[bill_id]["classes"]))
    )
    bills["passage_chambers"] = bills["bill_id"].map(
        lambda bill_id: "|".join(sorted(action_metrics[bill_id]["passage_chambers"]))
    )
    bills["committee_passage"] = bills["bill_id"].map(
        lambda bill_id: action_metrics[bill_id]["committee_passage"]
    )
    bills["recorded_outcome"] = bills["bill_id"].map(
        lambda bill_id: recorded_outcome(
            action_metrics[bill_id]["classes"],
            action_metrics[bill_id]["passage_chambers"],
            n_actions=action_metrics[bill_id]["n_actions"],
        )
    )
    bills["recorded_enacted"] = bills["bill_id"].map(
        lambda bill_id: bool(
            action_metrics[bill_id]["classes"]
            & {"became-law", "executive-signature", "veto-override-passage"}
        )
    )
    bills["n_vote_events"] = bills["bill_id"].map(
        lambda bill_id: vote_metrics[bill_id]["n_vote_events"]
    )
    bills["n_passage_votes"] = bills["bill_id"].map(
        lambda bill_id: vote_metrics[bill_id]["n_passage_votes"]
    )
    bills["n_passed_votes"] = bills["bill_id"].map(
        lambda bill_id: vote_metrics[bill_id]["vote_result_pass"]
    )
    bills["n_failed_votes"] = bills["bill_id"].map(
        lambda bill_id: vote_metrics[bill_id]["vote_result_fail"]
    )
    return bills


def main(argv: list[str] | None = None) -> int:
    """Write a separate, source-bound correction bundle; never rewrite an extraction."""
    import pandas as pd
    import pyarrow.parquet as pq

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out_dir.exists():
        raise FileExistsError(f"{args.out_dir}: select a new correction directory")
    source_manifest = args.source_dir / "bill_extraction_manifest.json"
    extraction = json.loads(source_manifest.read_text())
    if extraction.get("status") != "complete_extraction_not_source_certification":
        raise ValueError("outcome repair requires a completed source extraction")
    source_artifacts = {}
    for name in ("bills.parquet", "bill_actions.parquet"):
        digest = sha256_file(args.source_dir / name)
        if digest != extraction["artifacts"][name]["sha256"]:
            raise ValueError(f"{name}: extraction checksum mismatch")
        source_artifacts[name] = {"sha256": digest, "path": str((args.source_dir / name).resolve())}
    bills = pd.read_parquet(args.source_dir / "bills.parquet")
    repaired = repair_action_missingness(bills)
    action_counts = Counter()
    for batch in pq.ParquetFile(args.source_dir / "bill_actions.parquet").iter_batches(
        columns=["bill_id"],
    ):
        action_counts.update(batch.column(0).to_pylist())
    if set(action_counts) - set(bills["bill_id"]):
        raise ValueError("action records contain bills outside the extraction")
    observed = bills["bill_id"].map(action_counts).fillna(0).astype("int64")
    if not observed.eq(bills["n_actions"]).all():
        raise ValueError("bill action counts disagree with retained action records")
    changed = bills["recorded_outcome"].ne(repaired["recorded_outcome"])
    changes = bills.loc[changed, ["bill_id", "state", "n_actions", "recorded_outcome"]].rename(
        columns={"recorded_outcome": "previous_recorded_outcome"},
    )
    changes["recorded_outcome"] = repaired.loc[changed, "recorded_outcome"]
    manifest = {
        "schema_version": 1, "status": "complete_correction_not_outcome_certification",
        "created_at": utc_now_iso(),
        "source_extraction_manifest": str(source_manifest.resolve()),
        "source_extraction_manifest_sha256": sha256_file(source_manifest),
        "source_artifacts": source_artifacts,
        "code_sha256": sha256_file(__file__),
        "n_bills": len(bills), "n_action_records_checked": sum(action_counts.values()),
        "n_outcomes_changed": int(changed.sum()),
        "before": bills["recorded_outcome"].value_counts().to_dict(),
        "after": repaired["recorded_outcome"].value_counts().to_dict(),
        "limitations": [
            "Only absent-versus-unclassified action semantics are repaired.",
            "Chronology, veto overrides, final disposition and completeness remain unaudited.",
            "Historical sponsor attribution is unchanged and remains unresolved.",
            "Use this bills.parquet explicitly; the original extraction is preserved.",
        ],
    }
    args.out_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".outcome-repair-", dir=args.out_dir.parent) as temp:
        staging = Path(temp)
        repaired.to_parquet(staging / "bills.parquet", index=False)
        changes.to_parquet(staging / "bill_outcome_changes.parquet", index=False)
        manifest["artifacts"] = {
            name: {"sha256": sha256_file(staging / name), "rows": len(frame)}
            for name, frame in (
                ("bills.parquet", repaired), ("bill_outcome_changes.parquet", changes),
            )
        }
        (staging / "outcome_correction_manifest.json").write_text(
            json.dumps(manifest, indent=2, allow_nan=False) + "\n",
        )
        staging.rename(args.out_dir)
    print(f"wrote {args.out_dir}: {int(changed.sum()):,} corrected outcome labels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

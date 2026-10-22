"""Recover exact retained search-index bodies, without certifying their version or timing.

The public dump's omitted ``searchablebill.raw_text`` is a body, unlike a source URL or
abstract. Its explicit version-link foreign key is retained separately from any interpretation
of the version note. This module never downloads, attributes parties, or admits model inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ..provenance import sha256_file
from .openstates_dump import stream_table
from .outcomes import _ParquetSink

SOURCE_COLUMNS = (
    "id", "search_vector", "all_titles", "raw_text", "is_error", "created_at",
    "bill_id", "version_link_id",
)


def _update_digest(digest, row):
    digest.update(json.dumps(
        row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8") + b"\n")


def _retain_references(path, requested, output):
    source = pq.ParquetFile(path)
    schema = source.schema_arrow.append(pa.field("retained_table_row_ordinal", pa.int64()))
    sink = _ParquetSink(output, schema, chunk_size=8192)
    lookup = defaultdict(list)
    ordinal = 0
    try:
        for batch in source.iter_batches(batch_size=8192):
            for row in batch.to_pylist():
                ordinal += 1
                if row["id"] in requested:
                    sink.add({**row, "retained_table_row_ordinal": ordinal})
                    lookup[row["id"]].append(row)
    finally:
        sink.close()
    return lookup


def recover_retained_text(
    records: Iterable[dict],
    context_states: Mapping[str, str],
    version_links: Path,
    versions: Path,
    out_dir: Path,
) -> dict:
    """Preserve complete target records and their exact already-retained foreign-key rows.

    ``records`` contains ``source_record`` and the original one-based dump
    ``source_row_ordinal``. Duplicate ids/bodies are not deduplicated. All eight original
    strings/nulls survive; a streamed round trip checks their ordered canonical digest.
    Source hashes and the calendar-cohort binding belong in the caller's packet manifest.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    schema = pa.schema(
        [("source_row_ordinal", pa.int64())]
        + [(name, pa.string()) for name in SOURCE_COLUMNS]
    )
    sink = _ParquetSink(out_dir / "searchablebill.parquet", schema, chunk_size=128)
    counts, states, ids, bills = Counter(), Counter(), Counter(), Counter()
    relationships = []
    source_digest = hashlib.sha256()
    previous_ordinal = 0
    try:
        for record in records:
            ordinal, row = record["source_row_ordinal"], record["source_record"]
            if type(ordinal) is not int or ordinal <= previous_ordinal:
                raise ValueError("source ordinals must be positive and strictly increasing")
            previous_ordinal = ordinal
            if set(row) != set(SOURCE_COLUMNS):
                raise ValueError("unexpected searchablebill source columns")
            if any(value is not None and not isinstance(value, str) for value in row.values()):
                raise ValueError("source values must remain original strings or nulls")
            if row["bill_id"] not in context_states:
                raise ValueError("search-index record is outside the bound calendar cohort")
            retained = {"source_row_ordinal": ordinal, **row}
            sink.add(retained)
            _update_digest(source_digest, retained)
            counts["rows"] += 1
            ids[row["id"]] += 1
            bills[row["bill_id"]] += 1
            nonempty = bool((row["raw_text"] or "").strip())
            if nonempty:
                counts["nonempty_raw_text_rows"] += 1
                counts["raw_text_characters"] += len(row["raw_text"])
                states[context_states[row["bill_id"]]] += 1
                if row["is_error"] == "t":
                    counts["nonempty_error_flagged_rows"] += 1
            counts["error_flagged_rows"] += int(row["is_error"] == "t")
            relationships.append((row["bill_id"], row["version_link_id"], nonempty))
    finally:
        sink.close()

    links = _retain_references(
        version_links, {link for _, link, _ in relationships if link},
        out_dir / "version_links.parquet",
    )
    metadata = _retain_references(
        versions, {row["version_id"] for rows in links.values() for row in rows},
        out_dir / "versions.parquet",
    )
    relationship_counts = Counter()
    notes = Counter()
    for bill_id, link_id, nonempty in relationships:
        prefix = "nonempty_text_" if nonempty else "empty_text_"
        candidates = links.get(link_id, [])
        if not candidates:
            relationship_counts[prefix + "missing_version_link"] += 1
            continue
        if len(candidates) != 1:
            relationship_counts[prefix + "multiple_version_links"] += 1
            continue
        link = candidates[0]
        if link["bill_id"] != bill_id:
            relationship_counts[prefix + "cross_bill_version_link"] += 1
            continue
        candidates = metadata.get(link["version_id"], [])
        if not candidates:
            relationship_counts[prefix + "missing_version_metadata"] += 1
        elif len(candidates) != 1:
            relationship_counts[prefix + "multiple_version_metadata"] += 1
        elif candidates[0]["bill_id"] != bill_id:
            relationship_counts[prefix + "cross_bill_version_metadata"] += 1
        else:
            relationship_counts[prefix + "exact_version_foreign_keys"] += 1
            if nonempty:
                notes[candidates[0]["note"]] += 1

    roundtrip_digest = hashlib.sha256()
    roundtrip_rows = 0
    for batch in pq.ParquetFile(out_dir / "searchablebill.parquet").iter_batches(batch_size=128):
        for row in batch.to_pylist():
            _update_digest(roundtrip_digest, row)
            roundtrip_rows += 1
    if source_digest.digest() != roundtrip_digest.digest() or roundtrip_rows != counts["rows"]:
        raise ValueError("retained source record round trip changed full strings or multiplicity")
    report = {
        "status": "recovered_retained_snapshot_text_not_introduced_version_certification",
        "source_table": "opencivicdata_searchablebill",
        "source_columns": list(SOURCE_COLUMNS),
        "counts": dict(counts),
        "unique_source_ids": len(ids),
        "repeated_source_id_rows": sum(n - 1 for n in ids.values()),
        "unique_bill_ids": len(bills),
        "repeated_bill_id_rows": sum(n - 1 for n in bills.values()),
        "nonempty_text_rows_by_state": dict(sorted(states.items())),
        "relationship_counts": dict(relationship_counts),
        "version_note_counts_for_exact_nonempty_relationships": dict(notes),
        "retained_version_link_rows": sum(map(len, links.values())),
        "retained_version_metadata_rows": sum(map(len, metadata.values())),
        "full_source_record_roundtrip_verified": True,
        "ordered_source_record_sha256": source_digest.hexdigest(),
        "approvals": {name: False for name in (
            "scientific_approval", "model_input_approved", "training_approved",
            "publication_approved", "party_attribution_approved",
            "filing_time_text_certified", "analytical_admission",
        )},
        "limitations": [
            "Snapshot search-index text, not independently verified native publisher bytes.",
            "Foreign-key/version-note identity is not introduced-version certification.",
            "created_at is an index timestamp, not an introduction or affiliation date.",
            "Error-flagged, empty, repeated and conflicting records remain distinct.",
            "No party, date, cohort, label, weight, training or publication changes.",
        ],
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )
    return report


def extract_retained_search_index(
    dump_path: Path, candidate_cohort: Path, out_dir: Path,
) -> dict:
    """Stream exact candidate bill IDs from one retained dump into a fresh JSONL packet.

    The candidate source is an explicit Parquet file with a nonempty string ``bill_id``
    column. Repeated candidate IDs do not multiply source records. The JSONL wrappers are
    directly compatible with ``recover_retained_text``; no version or error filtering occurs.
    """
    dump_path, candidate_cohort, out_dir = map(Path, (dump_path, candidate_cohort, out_dir))
    if out_dir.exists():
        raise FileExistsError(out_dir)
    if not dump_path.is_file():
        raise FileNotFoundError(dump_path)
    cohort = pq.ParquetFile(candidate_cohort)
    if "bill_id" not in cohort.schema_arrow.names:
        raise ValueError("candidate cohort must have a bill_id column")
    candidate_ids = set()
    candidate_rows = 0
    for batch in cohort.iter_batches(batch_size=8192, columns=["bill_id"]):
        for bill_id in batch.column(0).to_pylist():
            if not isinstance(bill_id, str) or not bill_id.strip():
                raise ValueError("candidate bill IDs must be nonempty source strings")
            candidate_ids.add(bill_id)
            candidate_rows += 1
    if not candidate_ids:
        raise ValueError("candidate cohort must not be empty")
    inputs = {
        name: {
            "path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for name, path in (("dump", dump_path), ("candidate_cohort", candidate_cohort))
    }
    out_dir.mkdir(parents=True, exist_ok=False)
    records_path = out_dir / "target_searchablebill_records.jsonl"
    counts = Counter(dict.fromkeys((
        "source_rows_scanned", "retained_rows", "nonempty_raw_text_rows", "error_flagged_rows",
    ), 0))
    matched_ids = set()
    with records_path.open("x", encoding="utf-8") as handle:
        for ordinal, row in enumerate(
            stream_table(dump_path, "opencivicdata_searchablebill"), 1,
        ):
            if set(row) != set(SOURCE_COLUMNS):
                raise ValueError("unexpected searchablebill source columns")
            if any(value is not None and not isinstance(value, str) for value in row.values()):
                raise ValueError("source values must remain original strings or nulls")
            counts["source_rows_scanned"] += 1
            if row["bill_id"] not in candidate_ids:
                continue
            handle.write(json.dumps(
                {"source_row_ordinal": ordinal, "source_record": row},
                ensure_ascii=False, allow_nan=False,
            ) + "\n")
            matched_ids.add(row["bill_id"])
            counts["retained_rows"] += 1
            counts["nonempty_raw_text_rows"] += int(bool((row["raw_text"] or "").strip()))
            counts["error_flagged_rows"] += int(row["is_error"] == "t")
    report = {
        "status": "complete_offline_source_record_extraction_not_scientific_certification",
        "source_table": "opencivicdata_searchablebill",
        "source_columns": list(SOURCE_COLUMNS),
        "inputs": inputs,
        "candidate_rows": candidate_rows,
        "unique_candidate_bill_ids": len(candidate_ids),
        "matched_candidate_bill_ids": len(matched_ids),
        "unmatched_candidate_bill_ids": sorted(candidate_ids - matched_ids),
        "counts": dict(counts),
        "records": {
            "path": str(records_path.resolve()), "bytes": records_path.stat().st_size,
            "sha256": sha256_file(records_path),
        },
        "approvals": {name: False for name in (
            "scientific_approval", "model_input_approved", "training_approved",
            "publication_approved", "party_attribution_approved",
            "filing_time_text_certified", "analytical_admission",
        )},
    }
    with (out_dir / "extraction_report.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dump", type=Path, required=True, help="explicit retained local PG dump")
    parser.add_argument(
        "--candidate-cohort", type=Path, required=True,
        help="explicit candidate-cohort Parquet containing exact bill_id strings",
    )
    parser.add_argument("--out-dir", type=Path, required=True, help="new output directory only")
    args = parser.parse_args(argv)
    report = extract_retained_search_index(args.dump, args.candidate_cohort, args.out_dir)
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

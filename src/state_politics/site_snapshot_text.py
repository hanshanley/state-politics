"""Stream complete retained searchable-bill records without treating them as introduced text."""

from __future__ import annotations

import gzip
import hashlib
import json
from contextlib import ExitStack
from pathlib import Path

import pyarrow.csv as csv
import pyarrow.parquet as pq

from state_politics.provenance import sha256_file

STATUS = "complete_bounded_retained_dump_gap_recovery_not_scientific_certification"
FLAGS = (
    "scientific_approval", "model_input_approved", "training_approved",
    "publication_approved", "party_attribution_approved", "filing_time_text_certified",
    "analytical_admission",
)


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible snapshot text: {message}")


def bind_snapshot(directory: Path, metadata):
    directory = directory.absolute()
    manifest_path = directory / "sealed_manifest.json"
    require(directory.resolve() == directory and not directory.is_symlink(), "linked source")
    require(manifest_path.is_file() and manifest_path.resolve() == manifest_path,
            "missing or linked sealed manifest")
    manifest = json.loads(manifest_path.read_bytes())
    require(manifest.get("schema_version") == 1 and manifest.get("status") == STATUS,
            "sealed recovery schema/status")
    require(all(manifest["approvals"].get(flag) is False for flag in FLAGS),
            "all source approvals must remain false")
    require(manifest["validation"]["all_context_to_source_record_bindings_verified"] is True,
            "exact source/context validation required")
    artifacts = manifest["packet_artifacts"]
    require({
        "context_inventory.parquet", "searchablebill.parquet", "version_links.parquet",
        "versions.parquet", "state_text_coverage.csv", "interface.json", "report.json",
    } <= artifacts.keys(), "missing complete source tables")
    pins = {"sealed_manifest.json": sha256_file(manifest_path)}
    for name, binding in artifacts.items():
        relative = Path(name)
        path = directory / relative
        require(
            not relative.is_absolute() and ".." not in relative.parts
            and path.is_file() and path.resolve() == path,
            "unsafe or missing source artifact",
        )
        require(
            path.stat().st_size == binding["bytes"] and sha256_file(path) == binding["sha256"],
            f"source checksum mismatch: {name}",
        )
        pins[name] = binding["sha256"]
    contexts = pq.read_table(directory / "context_inventory.parquet").to_pylist()
    by_bill = {row["bill_id"]: row for row in contexts}
    require(len(by_bill) == len(contexts), "duplicate source context")
    require(
        set(by_bill) == {row["bill_id"] for row in metadata}
        and all(
            all(by_bill[row["bill_id"]][field] == row[field]
                for field in ("state", "identifier", "session_identifier"))
            for row in metadata
        ),
        "snapshot scope must exactly match the unchanged candidate cohort",
    )
    require(all(all(row[flag] is False for flag in FLAGS) for row in contexts),
            "source context approvals")
    links = pq.read_table(directory / "version_links.parquet").to_pylist()
    versions = pq.read_table(directory / "versions.parquet").to_pylist()
    link_map = {row["id"]: row for row in links}
    version_map = {row["id"]: row for row in versions}
    require(len(link_map) == len(links) and len(version_map) == len(versions),
            "duplicate original version/link identity")
    coverage = csv.read_csv(directory / "state_text_coverage.csv").to_pylist()
    return manifest, pins, by_bill, link_map, version_map, coverage


def export_snapshot(directory, out, metadata, states):
    manifest, pins, contexts, links, versions, coverage = bind_snapshot(directory, metadata)
    require(len(coverage) == len(states) and {r["state"] for r in coverage} == set(states),
            "all state coverage rows required")
    metadata = {row["bill_id"]: row for row in metadata}
    seen, nonempty, characters, nonempty_characters = set(), 0, 0, 0
    per_state = {state: {"records": 0, "nonempty": 0} for state in states}
    with ExitStack() as stack:
        handles = {}
        for state in sorted(states):
            plain = stack.enter_context(
                (out / "evidence" / f"snapshot-{state}.jsonl").open("wb"),
            )
            compressed = stack.enter_context(
                (out / "downloads" / f"snapshot-{state}.jsonl.gz").open("wb"),
            )
            zipped = stack.enter_context(gzip.GzipFile(
                filename="", fileobj=compressed, mode="wb", mtime=0,
            ))
            handles[state] = (plain, zipped)
        for batch in pq.ParquetFile(directory / "searchablebill.parquet").iter_batches(
            batch_size=32,
        ):
            for record in batch.to_pylist():
                bill_id = record["bill_id"]
                require(bill_id in contexts and bill_id not in seen, "source bill identity")
                seen.add(bill_id)
                context = contexts[bill_id]
                require(record["id"] == context["searchablebill_id"]
                        and record["version_link_id"] == context["version_link_id"],
                        "source search/version identity mismatch")
                text = record["raw_text"]
                require(text is None or isinstance(text, str), "raw_text must remain a string/null")
                digest = hashlib.sha256((text or "").encode()).hexdigest()
                require(digest == context["raw_text_sha256"]
                        and len(text or "") == context["raw_text_n_characters"],
                        "complete retained source text mismatch")
                link = links.get(record["version_link_id"])
                version = versions.get(link["version_id"]) if link is not None else None
                if context["exact_version_foreign_keys"]:
                    require(
                        link is not None and version is not None
                        and link["bill_id"] == version["bill_id"] == bill_id
                        and link["version_id"] == context["version_id"],
                        "version link belongs to a different bill",
                    )
                require(context["has_raw_text"] == bool(text and text.strip()),
                        "retained text availability mismatch")
                state = context["state"]
                row = {
                    "view_id": f"searchablebill:{record['id']}", "source_type": "snapshot_text",
                    "bill_id": bill_id, "state": state, "identifier": context["identifier"],
                    "session_identifier": context["session_identifier"],
                    "title": metadata[bill_id]["title"],
                    "source_row_ordinal": record["source_row_ordinal"],
                    "source_record": {key: value for key, value in record.items()
                                      if key != "source_row_ordinal"},
                    "source_version": {"link": link, "version": version},
                    "source_context": context,
                    "snapshot": {
                        "has_nonempty_raw_text": context["has_raw_text"],
                        "version_binding_status": context["source_reference_status"],
                        "source_url": context["source_url"],
                        "provider_flags": {"is_error": record["is_error"]},
                        "source_manifest_sha256": pins["sealed_manifest.json"],
                    },
                    **dict.fromkeys(FLAGS, False), "training_admission": False,
                    "source_date_or_party_inferred": False,
                }
                encoded = (json.dumps(
                    row, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
                ) + "\n").encode()
                for handle in handles[state]:
                    handle.write(encoded)
                per_state[state]["records"] += 1
                per_state[state]["nonempty"] += int(context["has_raw_text"])
                nonempty += int(context["has_raw_text"])
                characters += len(text or "")
                if context["has_raw_text"]:
                    nonempty_characters += len(text)
    require(seen == set(contexts), "missing complete source records")
    for row in coverage:
        require(
            per_state[row["state"]] == {
                "records": row["context_rows"], "nonempty": row["nonempty_retained_rows"],
            }, "state source counts do not reconcile",
        )
    for name, digest in pins.items():
        require(sha256_file(directory / name) == digest, "source changed during export")
    return {
        "n_records": len(seen), "n_nonempty_retained_texts": nonempty,
        "raw_text_characters": characters, "nonempty_raw_text_characters": nonempty_characters,
        "states_with_nonempty_text": sum(
            row["nonempty"] > 0 for row in per_state.values()
        ), "filing_time_text_certified": False,
    }, coverage, pins, manifest

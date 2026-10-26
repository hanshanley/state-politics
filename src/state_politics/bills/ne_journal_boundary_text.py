"""Qualify complete ordinary journal resolutions at literal publication boundaries."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from state_politics.bills import ne_journal_collection as collection
from state_politics.bills import ne_journal_day_text as day
from state_politics.bills.ne_journal_text import load_ne_journal

ROOT = collection.ROOT
SCHEMA = "state-politics.nebraska-journal-boundary-text.v1"
PARENT_SHA = "ac27e166a4d5a0481106391e4b70b38ba9d131ab511f18c02a8f1ca88616bb9a"
QUEUE_SHA = "c4a575d77835b50f6c389efba5b174ac86e27e58da55efe4cdccdb4f94b7f0a0"
BOOKS = {
    name: {
        **book,
        "pdf": "parent/" + book["pdf"],
        "readers": "parent/" + book["readers"],
    }
    for name, book in day.BOOKS.items()
}
PRODUCERS = (
    "ne_journal_boundary_text.py",
    "ne_journal_day_text.py",
    "ne_journal_collection.py",
    "ne_journal_text.py",
)


def qualify(pages, originals, *, books=BOOKS):
    return collection.qualify(
        pages,
        originals,
        books=books,
        header_profile=collection.EXPLICIT_DAY_HEADERS,
        boundary_profile=collection.LITERAL_BOUNDARIES,
    )


def previous_admissions(parent, pages):
    views, contexts = [], []
    for directory, loader in (
        (parent, day.load_ne_journal_day),
        (parent / "parent", collection.load_ne_journal_collection),
        (parent / "sealed", load_ne_journal),
    ):
        saved, original, _, _ = loader(directory)
        views.extend(saved)
        contexts.extend(original)
    original_text = {
        (view["bill_id"], view["source_record"]["reader"]): view["text"] for view in views
    }
    collection.require(
        len(contexts) == len({row["bill_id"] for row in contexts}) == 461
        and len(original_text) == 922,
        "all complete prior journal admissions",
    )
    observed, dispositions, _ = qualify(pages, contexts)
    collection.require(
        len(observed) == 922
        and {view["bill_id"] for view in observed} == {row["bill_id"] for row in contexts}
        and all(
            view["text"] == original_text[view["bill_id"], view["source_record"]["reader"]]
            for view in observed
        ),
        "all prior dates and policy strings remain qualified and byte-identical",
    )
    return {row["bill_id"] for row in contexts}, {
        "existing_contexts_retained": len(contexts),
        "existing_policy_strings_byte_identical": len(observed),
        "all_previous_context_dispositions": dispositions,
    }


def replay(directory):
    parent = directory / "parent"
    day.packet_members(parent, PARENT_SHA)
    collection.require(
        collection.binding(directory / "input_gap_queue.parquet")["sha256"] == QUEUE_SHA,
        "externally pinned current complete gap queue",
    )
    pages = day.source_pages(parent)
    previous, prior_report = previous_admissions(parent, pages)
    originals = pq.read_table(directory / "input_gap_queue.parquet").to_pylist()
    views, dispositions, candidates = qualify(pages, originals)
    collection.require(
        not previous & {row["bill_id"] for row in originals}
        and len({view["view_id"] for view in views}) == len(views),
        "new gap-only contexts with non-colliding namespaced views",
    )
    report = {
        **collection.report_for(originals, views, dispositions, candidates),
        **prior_report,
        "page_header_profile": collection.EXPLICIT_DAY_HEADERS,
        "literal_boundary_profile": collection.LITERAL_BOUNDARIES,
        "old_source_packets_or_default_profiles_modified": False,
        "original_introduction_dates_repaired_or_relaxed": False,
        "raw_policy_whitespace_trimmed_or_normalized": False,
    }
    return originals, views, dispositions, candidates, report


def build(parent, queue, output):
    parent, queue, output = (Path(path).absolute() for path in (parent, queue, output))
    collection.require(
        not output.exists()
        and output.resolve() == output
        and output != ROOT / "data/processed"
        and output.is_relative_to(ROOT / "data/processed"),
        "fresh unlinked output under project data/processed",
    )
    collection.require(
        queue.resolve() == queue and collection.binding(queue)["sha256"] == QUEUE_SHA,
        "externally pinned unlinked original gap queue",
    )
    files = day.packet_members(parent, PARENT_SHA)
    output.mkdir(parents=True)
    for name, source in files.items():
        target = output / "parent" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(queue, output / "input_gap_queue.parquet")
    (output / "producer").mkdir()
    for name in PRODUCERS:
        shutil.copy2(Path(__file__).with_name(name), output / "producer" / name)
    originals, views, dispositions, candidates, report = replay(output)
    collection.require(views, "nonempty complete new original contexts")
    accepted = {view["bill_id"] for view in views}
    table = pq.read_table(output / "input_gap_queue.parquet")
    pq.write_table(
        table.filter(pa.array([row["bill_id"] in accepted for row in originals])),
        output / "context_inventory.parquet",
    )
    for name, rows in (
        ("views.jsonl", views),
        ("candidate_dispositions.jsonl", dispositions),
        ("source_resolution_candidates.jsonl", candidates),
    ):
        collection.write_rows(output / name, rows)
    collection.write_json(output / "report.json", report)
    manifest = {
        "schema": SCHEMA,
        "source_profiles": BOOKS,
        "parent_packet_sha256": PARENT_SHA,
        "original_gap_queue_sha256": QUEUE_SHA,
        "page_header_profile": collection.EXPLICIT_DAY_HEADERS,
        "literal_boundary_profile": collection.LITERAL_BOUNDARIES,
        "report": report,
        "approvals": dict.fromkeys(collection.FLAGS, False),
        "packet_artifacts": {
            path.relative_to(output).as_posix(): collection.binding(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    collection.write_json(output / "manifest.json", manifest)
    for name, source in files.items():
        collection.require(
            collection.binding(source) == collection.binding(output / "parent" / name),
            "immutable original source packet changed during qualification",
        )
    collection.require(
        collection.binding(queue)["sha256"] == QUEUE_SHA,
        "immutable original gap queue changed during qualification",
    )
    return manifest


def load_ne_journal_boundary(directory, metadata=None):
    directory = Path(directory).absolute()
    collection.require(
        directory.is_dir() and directory.resolve() == directory, "unlinked packet root"
    )
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    collection.require(
        manifest["schema"] == SCHEMA
        and manifest["source_profiles"] == BOOKS
        and manifest["parent_packet_sha256"] == PARENT_SHA
        and manifest["original_gap_queue_sha256"] == QUEUE_SHA
        and manifest["page_header_profile"] == collection.EXPLICIT_DAY_HEADERS
        and manifest["literal_boundary_profile"] == collection.LITERAL_BOUNDARIES
        and all(manifest["approvals"].get(flag) is False for flag in collection.FLAGS),
        "fixed unapproved literal-boundary source profile",
    )
    required = {
        "input_gap_queue.parquet",
        "context_inventory.parquet",
        "views.jsonl",
        "candidate_dispositions.jsonl",
        "source_resolution_candidates.jsonl",
        "report.json",
        *(f"producer/{name}" for name in PRODUCERS),
    }
    collection.require(
        required <= manifest["packet_artifacts"].keys(), "complete boundary-source packet"
    )
    files = day.packet_members(directory, collection.binding(manifest_path)["sha256"])
    pins = {name: collection.binding(path)["sha256"] for name, path in files.items()}
    originals, views, dispositions, candidates, report = replay(directory)
    collection.require(
        list(collection.records(directory / "views.jsonl")) == views
        and list(collection.records(directory / "candidate_dispositions.jsonl")) == dispositions
        and list(collection.records(directory / "source_resolution_candidates.jsonl")) == candidates
        and json.loads((directory / "report.json").read_bytes()) == manifest["report"] == report,
        "all positive and negative source records and exact accounting replay",
    )
    accepted = {view["bill_id"] for view in views}
    contexts = pq.read_table(directory / "context_inventory.parquet").to_pylist()
    collection.require(
        contexts == [row for row in originals if row["bill_id"] in accepted],
        "all original context fields and unknowns preserved",
    )
    if metadata is not None:
        current = {row["bill_id"]: row for row in metadata}
        collection.require(
            all(
                row["bill_id"] in current
                and all(
                    row[key] == current[row["bill_id"]][key]
                    for key in ("state", "session_identifier", "identifier")
                )
                for row in contexts
            ),
            "current original candidate identity conflict",
        )
    return views, contexts, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent-packet", "gap-queue", "out-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(args.parent_packet, args.gap_queue, args.out_dir)
    load_ne_journal_boundary(args.out_dir)
    print(json.dumps(manifest["report"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

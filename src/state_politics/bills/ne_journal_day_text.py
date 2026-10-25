"""Qualify fixed journal bodies against explicit printed legislative-day dates."""

from __future__ import annotations

import argparse
import json
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import pyarrow as pa
import pyarrow.parquet as pq

from state_politics.bills import ne_journal_collection as collection
from state_politics.bills.ne_journal_text import load_ne_journal

ROOT = collection.ROOT
SCHEMA = "state-politics.nebraska-journal-day-text.v1"
QUEUE_SHA = "444f8f879cc8130cc1a9affe07ccf0e467a052e086ad1e3963e676c8ec353876"
PACKETS = {
    "parent": "3948e5160a060654ee1c65b1c334e3366dee9fb168b68f3a046ed43f5f877123",
    "sealed": "d4496cc9af71061371c8575acaae3257e074488d06e59d8c7deaf1114bcbef61",
}
BUNDLES = {
    "late/source": "55806d20d72ff0a6300b2831e9c29055001f19d14ebd0491ed6665b033a82c74",
    "late/readers": "c52a4057f0f4d1a03d32be0a95b20f5308dcd72f4d05e9120f2da3d79a1bfafd",
}
CATALOGUE_URL = "https://govdocs.nebraska.gov/epubs/L3300/T001.html"
LATE_BOOK = {
    "year": 2024,
    "session": "SECOND",
    "volume": 2,
    "pages": 1613,
    "pdf": "late/source/journal-2024-v2.body",
    "readers": "late/readers/pages-{reader}.jsonl",
    "sha256": "2cf21b90fb163a1f1e20220996e6af5b490221095c3cb4b446b1f9b4d99e8355",
    "url": "https://govdocs.nebraska.gov/epubs/L3300/T001-2024v2.pdf",
}
BOOKS = {
    **{
        name: {
            **book,
            "pdf": "parent/" + book["pdf"],
            "readers": "parent/" + book["readers"],
        }
        for name, book in collection.BOOKS.items()
    },
    "journal-2024-v2": LATE_BOOK,
}


class CatalogueLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = {"href": dict(attrs).get("href"), "text": ""}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append(self.current)
            self.current = None


def packet_members(directory, pin):
    directory = Path(directory)
    collection.require(
        directory.resolve() == directory and directory.is_dir(), "unlinked original packet"
    )
    manifest_path = directory / "manifest.json"
    collection.require(
        collection.binding(manifest_path)["sha256"] == pin, "pinned original packet manifest"
    )
    manifest = json.loads(manifest_path.read_bytes())
    files = {"manifest.json": manifest_path}
    for name, expected in manifest["packet_artifacts"].items():
        path = directory / name
        collection.require(
            collection.safe_member(name)
            and name != "manifest.json"
            and path.is_file()
            and path.resolve() == path
            and collection.binding(path) == expected,
            "complete unlinked original packet member",
        )
        files[name] = path
    return files


def source_pages(directory):
    packet_members(directory / "parent", PACKETS["parent"])
    packet_members(directory / "sealed", PACKETS["sealed"])
    for prefix, pin in BUNDLES.items():
        collection.input_bundle(directory / prefix, pin)
    pages = collection.source_pages(directory / "parent")
    capture = json.loads((directory / "late/source/manifest.json").read_bytes())
    collection.require(
        capture["complete_response_collection"] is True
        and capture["controlled_GET_attempts_total"] == 2
        and capture["catalogue_url"] == CATALOGUE_URL
        and capture["catalogue_link"]["absolute_URL"] == LATE_BOOK["url"],
        "complete explicitly catalogued later volume",
    )
    parser = CatalogueLinks()
    parser.feed((directory / "late/source/catalogue.body").read_text(encoding="utf-8"))
    links = [
        link
        for link in parser.links
        if link["href"]
        and urljoin(CATALOGUE_URL, link["href"]) == LATE_BOOK["url"]
        and "".join(link["text"].split()) == "2024Journal(v.2)"
    ]
    collection.require(len(links) == 1, "literal own official catalogue link")
    collection.require(
        collection.binding(directory / LATE_BOOK["pdf"])["sha256"] == LATE_BOOK["sha256"],
        "pinned complete later PDF",
    )
    readers = {}
    for reader in collection.READERS:
        saved = list(collection.records(directory / LATE_BOOK["readers"].format(reader=reader)))
        collection.require(
            len(saved) == LATE_BOOK["pages"]
            and all(row["reader"] == reader and row["page"] == i for i, row in enumerate(saved, 1)),
            "both complete later-volume reader streams",
        )
        cover = collection.compact(saved[0]["text"])
        collection.require(
            "Volume2" in cover and "ONEHUNDREDEIGHTHLEGISLATURESECONDSESSION2024" in cover,
            "own later-volume cover/session/year",
        )
        readers[reader] = saved
    pages["journal-2024-v2"] = readers
    return pages


def qualify(pages, originals, *, books=BOOKS):
    return collection.qualify(
        pages, originals, books=books, header_profile=collection.EXPLICIT_DAY_HEADERS
    )


def previous_admissions(directory, pages):
    old_views, old_contexts, _, _ = collection.load_ne_journal_collection(directory / "parent")
    sealed_views, sealed_contexts, _, _ = load_ne_journal(directory / "sealed")
    contexts = old_contexts + sealed_contexts
    originals = {(v["bill_id"], v["source_record"]["reader"]): v for v in old_views + sealed_views}
    collection.require(
        len(contexts) == len({row["bill_id"] for row in contexts}) == 357 and len(originals) == 714,
        "all complete prior journal admissions",
    )
    observed, dispositions, _ = qualify(pages, contexts)
    collection.require(
        len(observed) == 714
        and {v["bill_id"] for v in observed} == {r["bill_id"] for r in contexts}
        and all(
            v["text"] == originals[v["bill_id"], v["source_record"]["reader"]]["text"]
            for v in observed
        ),
        "every prior context date and policy string remains qualified and unchanged",
    )
    return {r["bill_id"] for r in contexts}, {
        "existing_contexts_retained": len(contexts),
        "existing_policy_strings_byte_identical": len(observed),
        "all_previous_context_dispositions": dispositions,
    }


def replay(directory):
    collection.require(
        collection.binding(directory / "input_gap_queue.parquet")["sha256"] == QUEUE_SHA,
        "externally pinned current complete gap queue",
    )
    pages = source_pages(directory)
    previous, prior_report = previous_admissions(directory, pages)
    originals = pq.read_table(directory / "input_gap_queue.parquet").to_pylist()
    views, dispositions, candidates = qualify(pages, originals)
    collection.require(
        not previous & {r["bill_id"] for r in originals}
        and len({v["view_id"] for v in views}) == len(views),
        "new gap-only contexts and non-colliding namespaced views",
    )
    report = {
        **collection.report_for(originals, views, dispositions, candidates),
        **prior_report,
        "explicit_printed_day_header_profile": collection.EXPLICIT_DAY_HEADERS,
        "old_source_packet_or_default_profile_modified": False,
        "original_introduction_dates_repaired_or_relaxed": False,
    }
    return originals, views, dispositions, candidates, report


def build(parent, sealed, late_source, late_readers, queue, output):
    parent, sealed, late_source, late_readers, queue, output = (
        Path(path).absolute() for path in (parent, sealed, late_source, late_readers, queue, output)
    )
    collection.require(
        not output.exists()
        and output.resolve() == output
        and output.is_relative_to(ROOT / "data/processed")
        and output != ROOT / "data/processed",
        "fresh unlinked output under project data/processed",
    )
    collection.require(
        queue.resolve() == queue and collection.binding(queue)["sha256"] == QUEUE_SHA,
        "pinned unlinked original gap queue",
    )
    inputs = {
        "parent": packet_members(parent, PACKETS["parent"]),
        "sealed": packet_members(sealed, PACKETS["sealed"]),
        "late/source": collection.input_bundle(late_source, BUNDLES["late/source"]),
        "late/readers": collection.input_bundle(late_readers, BUNDLES["late/readers"]),
    }
    output.mkdir(parents=True)
    for prefix, files in inputs.items():
        for name, source in files.items():
            target = output / prefix / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    shutil.copy2(queue, output / "input_gap_queue.parquet")
    (output / "producer").mkdir()
    for name in ("ne_journal_day_text.py", "ne_journal_collection.py", "ne_journal_text.py"):
        shutil.copy2(Path(__file__).with_name(name), output / "producer" / name)
    originals, views, dispositions, candidates, report = replay(output)
    collection.require(views, "nonempty complete new original contexts")
    accepted = {v["bill_id"] for v in views}
    table = pq.read_table(output / "input_gap_queue.parquet")
    pq.write_table(
        table.filter(pa.array([r["bill_id"] in accepted for r in originals])),
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
        "fixed_packet_manifests": PACKETS,
        "fixed_input_manifests": BUNDLES,
        "original_gap_queue_sha256": QUEUE_SHA,
        "page_header_profile": collection.EXPLICIT_DAY_HEADERS,
        "report": report,
        "approvals": dict.fromkeys(collection.FLAGS, False),
        "packet_artifacts": {
            path.relative_to(output).as_posix(): collection.binding(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    collection.write_json(output / "manifest.json", manifest)
    for prefix, files in inputs.items():
        for name, source in files.items():
            collection.require(
                collection.binding(source) == collection.binding(output / prefix / name),
                "original immutable input changed during qualification",
            )
    return manifest


def load_ne_journal_day(directory, metadata=None):
    directory = Path(directory).absolute()
    collection.require(
        directory.is_dir() and directory.resolve() == directory, "unlinked packet root"
    )
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    collection.require(
        manifest["schema"] == SCHEMA
        and manifest["source_profiles"] == BOOKS
        and manifest["fixed_packet_manifests"] == PACKETS
        and manifest["fixed_input_manifests"] == BUNDLES
        and manifest["original_gap_queue_sha256"] == QUEUE_SHA
        and manifest["page_header_profile"] == collection.EXPLICIT_DAY_HEADERS
        and all(manifest["approvals"].get(flag) is False for flag in collection.FLAGS),
        "fixed unapproved explicit-day source profile",
    )
    required = {
        "input_gap_queue.parquet",
        "context_inventory.parquet",
        "views.jsonl",
        "candidate_dispositions.jsonl",
        "source_resolution_candidates.jsonl",
        "report.json",
        "producer/ne_journal_day_text.py",
        "producer/ne_journal_collection.py",
        "producer/ne_journal_text.py",
    }
    collection.require(
        required <= manifest["packet_artifacts"].keys(), "complete day-source packet"
    )
    pins = {"manifest.json": collection.binding(manifest_path)["sha256"]}
    for name, expected in manifest["packet_artifacts"].items():
        path = directory / name
        collection.require(
            collection.safe_member(name)
            and name != "manifest.json"
            and path.is_file()
            and path.resolve() == path
            and collection.binding(path) == expected,
            "every complete day-source artifact",
        )
        pins[name] = expected["sha256"]
    originals, views, dispositions, candidates, report = replay(directory)
    collection.require(
        list(collection.records(directory / "views.jsonl")) == views
        and list(collection.records(directory / "candidate_dispositions.jsonl")) == dispositions
        and list(collection.records(directory / "source_resolution_candidates.jsonl")) == candidates
        and json.loads((directory / "report.json").read_bytes()) == manifest["report"] == report,
        "every accepted and rejected record and exact source accounting replay",
    )
    accepted = {v["bill_id"] for v in views}
    contexts = pq.read_table(directory / "context_inventory.parquet").to_pylist()
    collection.require(
        contexts == [r for r in originals if r["bill_id"] in accepted],
        "all original context fields and unknowns preserved",
    )
    if metadata is not None:
        current = {r["bill_id"]: r for r in metadata}
        collection.require(
            all(
                r["bill_id"] in current
                and all(
                    r[k] == current[r["bill_id"]][k]
                    for k in ("state", "session_identifier", "identifier")
                )
                for r in contexts
            ),
            "current original candidate identity conflict",
        )
    return views, contexts, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "parent-collection",
        "sealed-packet",
        "late-source",
        "late-readers",
        "gap-queue",
        "out-dir",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(
        args.parent_collection,
        args.sealed_packet,
        args.late_source,
        args.late_readers,
        args.gap_queue,
        args.out_dir,
    )
    load_ne_journal_day(args.out_dir)
    print(json.dumps(manifest["report"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

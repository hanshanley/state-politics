"""Qualify only exact source-proven hyphen positions without changing raw text."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from state_politics.bills import ne_enacted_law_text as laws
from state_politics.bills import ne_journal_collection as common
from state_politics.bills.ne_journal_day_text import packet_members

ROOT = common.ROOT
SCHEMA = "state-politics.nebraska-enacted-hyphen-text.v1"
PROFILE = "literal_winansi_ad_hyphen_at_verified_source_positions_v1"
PARENT_SHA = "56732a9b8f5dc0881d877556c2b6883e7cfd7a8ee009606988fa0e8a7b1a9e31"
QUEUE_SHA = "819618e953b550d66e2bc38c56b2f6d6a1984c88af83f4628d83543b351759a6"
GLYPHS_SHA = "4de7c1bdbd748ca7e4d304c7bf5e0d6aba8b476fdee91ed4b26d37cef5aa571d"
WITNESS_SHA = "f523ba371bf03739ec49b618693eace20be49932917f4f7581baefbbe2162edc"
PRODUCERS = ("ne_enacted_hyphen_text.py", *laws.PRODUCERS)


def valid_glyph(row, books):
    operator = row["source_text_operator"]
    native = row["native_glyph_trace"]
    reference = row["same_font_ASCII_reference"]
    return (
        row["document"] in books
        and row["PDF_sha256"] == books[row["document"]]["sha256"]
        and operator["byte"] == 173
        and operator["source_code_unit_bytes"] == 1
        and operator["font_encoding"] == "/WinAnsiEncoding"
        and operator["font_subtype"] == "/Type1"
        and operator["ToUnicode_present"] is False
        and operator["operator"] == "Tj"
        and type(operator["byte_offset"]) is int
        and 0 <= operator["byte_offset"] < len(bytes.fromhex(operator["string_bytes_hex"]))
        and bytes.fromhex(operator["string_bytes_hex"])[operator["byte_offset"]] == 173
        and native["unicode"] == reference["native_glyph_trace"]["unicode"] == 45
        and native["glyph_id"] == reference["native_glyph_trace"]["glyph_id"]
        and native["font"] == reference["native_glyph_trace"]["font"]
        and native["font"] == operator["font_base"].lstrip("/")
        and operator["font_xref"] == reference["source_text_operator"]["font_xref"]
        and reference["source_text_operator"]["byte"] == 45
        and row["raw_reader_characters"] == {"pymupdf": "-", "pypdf": "\u00ad"}
        and row["native_source_bytes_and_font_glyph_equivalence_verified"] is True
        and type(row["compact_page_character_index"]) is int
        and row["compact_page_character_index"] >= 0
    )


def exact_position_agreement(selected, pages, glyphs):
    mu, py = selected["pymupdf"], selected["pypdf"]
    if mu["document"] != py["document"]:
        return False
    name = mu["document"]
    if [part["page"] for part in mu["fragments"]] != [part["page"] for part in py["fragments"]]:
        return False
    allowed = {
        (row["document"], row["page"], row["compact_page_character_index"]) for row in glyphs
    }
    if len(allowed) != len(glyphs) or not allowed:
        return False
    observed = set()
    for part in mu["fragments"]:
        number = part["page"]
        left = common.compact(pages[name]["pymupdf"][number - 1]["text"])
        right = common.compact(pages[name]["pypdf"][number - 1]["text"])
        if len(left) != len(right):
            return False
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            key = (name, number, index)
            if key in allowed:
                if (a, b) != ("-", "\u00ad"):
                    return False
                observed.add(key)
            elif a != b:
                return False
    return observed == allowed


def qualify(pages, originals, glyphs, *, books=laws.BOOKS):
    common.require(set(pages) == set(books), "all fixed original law books")
    common.require(
        len({row["bill_id"] for row in originals}) == len(originals),
        "duplicate original context identity",
    )
    common.require(
        glyphs and all(valid_glyph(row, books) for row in glyphs),
        "literal source-byte/font/glyph evidence",
    )
    by_identifier = defaultdict(list)
    for row in glyphs:
        by_identifier[row["identifier"]].append(row)
    identities = Counter(
        (row["state"], row["session_identifier"], row["identifier"]) for row in originals
    )
    indexed, inventory = defaultdict(list), []
    for name, book in books.items():
        common.require(set(pages[name]) == set(common.READERS), "both complete law-book readers")
        for reader in common.READERS:
            for candidate in laws.candidates(pages[name][reader], book):
                value = {"document": name, "reader": reader, **candidate}
                indexed[reader, value["identifier"]].append(value)
                inventory.append(value)
    views, dispositions = [], []
    for original in originals:
        if original["state"] != "NE":
            continue
        identifier = original["identifier"]
        date = original["source_introduction_date"]
        reason, selected = None, {}
        if identifier not in by_identifier:
            reason = "outside_exact_source_proven_hyphen_cohort"
        elif original["session_identifier"] != "108" or not re.fullmatch(r"LB \d+A?", identifier):
            reason = "outside_108th_legislative_bill_profile"
        elif identities["NE", "108", identifier] != 1:
            reason = "ambiguous_original_context_identity"
        elif not isinstance(date, str) or not re.fullmatch(r"202[34]-\d{2}-\d{2}", date):
            reason = "unresolved_original_introduction_date"
        if reason is None:
            for reader in common.READERS:
                matches = [
                    row
                    for row in indexed[reader, identifier]
                    if row["reason"] is None and row["approval_date"] >= date
                ]
                if len(matches) != 1:
                    reason = reason or "no_unique_complete_enacted_version"
                else:
                    selected[reader] = matches[0]
            if len(selected) == 2:
                if len({row["approval_date"] for row in selected.values()}) != 1:
                    reason = reason or "reader_approval_date_disagreement"
                if not exact_position_agreement(selected, pages, by_identifier[identifier]):
                    reason = reason or "unproved_or_additional_reader_character_disagreement"
        dispositions.append(
            {
                **{
                    key: original[key]
                    for key in ("bill_id", "state", "identifier", "session_identifier")
                },
                "disposition": reason or "complete_two_reader_source_proven_hyphen_match",
            }
        )
        if reason:
            continue
        for reader, candidate in selected.items():
            name = candidate["document"]
            book = books[name]
            text = candidate["text"]
            views.append(
                {
                    "view_id": (
                        f"ne-enacted-hyphen-v1:{name}:{book['sha256']}:{reader}:{candidate['ordinal']}"
                    ),
                    "source_type": "archive_text",
                    "bill_id": original["bill_id"],
                    "state": "NE",
                    "identifier": identifier,
                    "session_identifier": "108",
                    "title": original["title"],
                    "text": text,
                    "raw_text_characters": len(text),
                    "raw_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "source_record": {
                        "provider": "Nebraska Library Commission, official Laws Passed",
                        "url": book["url"],
                        "reader": reader,
                        "document": name,
                        "source_PDF_sha256": book["sha256"],
                        "law_book_year": book["year"],
                        "law_book_session": book["session"],
                        "law_book_volume": book["volume"],
                        "version_scope": "enacted_law_not_introduced",
                        "approval_date": candidate["approval_date"],
                        "literal_approval": candidate["literal_approval"],
                        "original_introduction_date": date,
                        "page_fragments": candidate["fragments"],
                        "fragment_joiner": "\n",
                        "page_text_trimmed_or_normalized": False,
                        "bill_page_folios": candidate["bill_page_folios"],
                        "following_law_heading": candidate["following_law_heading"],
                        "following_law_physical_page": candidate["following_law_physical_page"],
                        "ends_at_physical_book_end": candidate["ends_at_physical_book_end"],
                        "profile": PROFILE,
                        "literal_hyphen_source_evidence": by_identifier[identifier],
                    },
                    "source_identity": {
                        "state": "NE",
                        "session_identifier": "108",
                        "identifier": identifier,
                        "profile": PROFILE,
                    },
                    "source_version": {
                        "note": "Enacted law, not introduced text",
                        "date": candidate["approval_date"],
                    },
                    **dict.fromkeys(common.FLAGS, False),
                }
            )
    return views, dispositions, inventory


def replay(directory):
    parent = directory / "parent"
    packet_members(parent, PARENT_SHA)
    previous, prior_contexts, _, _ = laws.load_ne_enacted_law(parent)
    common.require(len(previous) == 102 and len(prior_contexts) == 51, "all prior law views")
    common.require(
        common.binding(directory / "input_gap_queue.parquet")["sha256"] == QUEUE_SHA,
        "externally pinned complete current gap queue",
    )
    common.require(
        common.binding(directory / "glyphs/report.json")["sha256"] == GLYPHS_SHA
        and common.binding(directory / "independent/witness.json")["sha256"] == WITNESS_SHA,
        "externally pinned literal glyph and independent source witnesses",
    )
    report = json.loads((directory / "glyphs/report.json").read_bytes())
    witness = json.loads((directory / "independent/witness.json").read_bytes())
    common.require(
        witness["source_glyph_report"] == common.binding(directory / "glyphs/report.json")
        and witness["fresh_original_reader_page_strings_verified"] == 44
        and len(witness["all_nine_original_stream_font_glyph_crop_witnesses"]) == 9
        and common.binding(directory / "independent/observer.py") == witness["observer"]
        and common.binding(directory / "first-failed-observer/observer.py")
        == {key: report["first_failed_observer_preserved"][key] for key in ("sha256", "bytes")},
        "complete independent direct-original glyph witness",
    )
    for name, expected in report["artifacts"].items():
        common.require(common.safe_member(name), "safe literal glyph member")
        common.require(
            common.binding(directory / "glyphs" / name) == expected, "exact glyph artifact"
        )
    glyphs = report["all_nine_exact_source_glyph_witnesses"]
    common.require(
        len(glyphs) == 9 and len({row["identifier"] for row in glyphs}) == 7,
        "complete fixed source-proven glyph cohort",
    )
    originals = pq.read_table(directory / "input_gap_queue.parquet").to_pylist()
    common.require(
        not {row["bill_id"] for row in prior_contexts} & {row["bill_id"] for row in originals},
        "new gap-only cohort excludes all prior law contexts",
    )
    views, dispositions, inventory = qualify(laws.source_pages(parent), originals, glyphs)
    summary = {
        "status": "qualified_exact_source_proven_hyphen_laws_not_scientific_certification",
        "original_gap_contexts": len(originals),
        "original_NE_gap_contexts": sum(row["state"] == "NE" for row in originals),
        "recovered_original_contexts": len({row["bill_id"] for row in views}),
        "complete_reader_views": len(views),
        "complete_policy_characters": sum(len(row["text"]) for row in views),
        "candidate_dispositions": dict(Counter(row["disposition"] for row in dispositions)),
        "source_candidates_preserved": len(inventory),
        "prior_law_contexts_preserved": len(prior_contexts),
        "prior_law_strings_preserved": len(previous),
        "literal_source_glyph_positions": 9,
        "original_policy_text_or_dates_modified": False,
        "old_whitespace_only_profile_modified": False,
        "source_version": "enacted_not_introduced",
        "model_execution": False,
        "publication": False,
    }
    return originals, views, dispositions, inventory, summary


def build(parent, glyphs, independent, queue, output):
    parent, glyphs, independent, queue, output = (
        Path(path).absolute() for path in (parent, glyphs, independent, queue, output)
    )
    common.require(
        not output.exists()
        and output.resolve() == output
        and output != ROOT / "data/processed"
        and output.is_relative_to(ROOT / "data/processed"),
        "fresh unlinked output under project data/processed",
    )
    files = packet_members(parent, PARENT_SHA)
    common.require(
        glyphs.resolve() == glyphs
        and common.binding(glyphs / "report.json")["sha256"] == GLYPHS_SHA
        and independent.resolve() == independent
        and common.binding(independent)["sha256"] == WITNESS_SHA
        and queue.resolve() == queue
        and common.binding(queue)["sha256"] == QUEUE_SHA,
        "fixed unlinked source-glyph witnesses and current gap queue",
    )
    glyph_report = json.loads((glyphs / "report.json").read_bytes())
    independent_report = json.loads(independent.read_bytes())
    witness_code = ROOT / "data/independently_verify_ne_enacted_hyphens_20261026_v1.py"
    first_failure = ROOT / "data/ne-enacted-law-hyphen-glyphs-20261026-v1"
    failure_log = ROOT / "data/ne-enacted-law-hyphen-glyphs-20261026-v1.log"
    common.require(
        witness_code.resolve() == witness_code
        and common.binding(witness_code) == independent_report["observer"]
        and common.binding(first_failure / "observer.py")
        == {
            key: glyph_report["first_failed_observer_preserved"][key] for key in ("sha256", "bytes")
        },
        "complete independent and preserved failed observer provenance",
    )
    glyph_members = {
        "report.json": common.binding(glyphs / "report.json"),
        **glyph_report["artifacts"],
    }
    common.require(
        all(
            common.safe_member(name)
            and (glyphs / name).resolve() == glyphs / name
            and common.binding(glyphs / name) == expected
            for name, expected in glyph_members.items()
        ),
        "complete literal glyph evidence bundle",
    )
    output.mkdir(parents=True)
    for name, source in files.items():
        target = output / "parent" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (output / "glyphs").mkdir()
    for name in glyph_members:
        shutil.copy2(glyphs / name, output / "glyphs" / name)
    (output / "independent").mkdir()
    shutil.copy2(independent, output / "independent/witness.json")
    shutil.copy2(witness_code, output / "independent/observer.py")
    (output / "first-failed-observer").mkdir()
    for source in (
        first_failure / "observer.py",
        first_failure / "glyph-01-laws-2024-v2-p446.png",
        failure_log,
    ):
        common.require(source.resolve() == source and source.is_file(), "unlinked failed evidence")
        shutil.copy2(source, output / "first-failed-observer" / source.name)
    shutil.copy2(queue, output / "input_gap_queue.parquet")
    (output / "producer").mkdir()
    for name in PRODUCERS:
        shutil.copy2(Path(__file__).with_name(name), output / "producer" / name)
    originals, views, dispositions, inventory, summary = replay(output)
    common.require(views, "nonempty exact-position qualified source cohort")
    accepted = {view["bill_id"] for view in views}
    table = pq.read_table(output / "input_gap_queue.parquet")
    pq.write_table(
        table.filter(pa.array([row["bill_id"] in accepted for row in originals])),
        output / "context_inventory.parquet",
    )
    for name, rows in (
        ("views.jsonl", views),
        ("candidate_dispositions.jsonl", dispositions),
        ("source_law_candidates.jsonl", inventory),
    ):
        common.write_rows(output / name, rows)
    common.write_json(output / "report.json", summary)
    manifest = {
        "schema": SCHEMA,
        "profile": PROFILE,
        "parent_packet_sha256": PARENT_SHA,
        "original_gap_queue_sha256": QUEUE_SHA,
        "glyph_report_sha256": GLYPHS_SHA,
        "independent_witness_sha256": WITNESS_SHA,
        "report": summary,
        "approvals": dict.fromkeys(common.FLAGS, False),
        "packet_artifacts": {
            path.relative_to(output).as_posix(): common.binding(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    common.write_json(output / "manifest.json", manifest)
    common.require(
        all(
            common.binding(path) == common.binding(output / "parent" / name)
            for name, path in files.items()
        )
        and all(
            common.binding(glyphs / name) == common.binding(output / "glyphs" / name)
            for name in glyph_members
        )
        and common.binding(independent) == common.binding(output / "independent/witness.json")
        and common.binding(queue)["sha256"] == QUEUE_SHA,
        "all original inputs unchanged during qualification",
    )
    return manifest


def load_ne_enacted_hyphen(directory, metadata=None):
    directory = Path(directory).absolute()
    common.require(directory.is_dir() and directory.resolve() == directory, "unlinked packet root")
    path = directory / "manifest.json"
    manifest = json.loads(path.read_bytes())
    common.require(
        manifest["schema"] == SCHEMA
        and manifest["profile"] == PROFILE
        and manifest["parent_packet_sha256"] == PARENT_SHA
        and manifest["original_gap_queue_sha256"] == QUEUE_SHA
        and manifest["glyph_report_sha256"] == GLYPHS_SHA
        and manifest["independent_witness_sha256"] == WITNESS_SHA
        and all(manifest["approvals"].get(flag) is False for flag in common.FLAGS),
        "fixed unapproved exact-source-position profile",
    )
    required = {
        "input_gap_queue.parquet",
        "context_inventory.parquet",
        "views.jsonl",
        "candidate_dispositions.jsonl",
        "source_law_candidates.jsonl",
        "report.json",
        "glyphs/report.json",
        "independent/witness.json",
        "independent/observer.py",
        "first-failed-observer/observer.py",
        "first-failed-observer/ne-enacted-law-hyphen-glyphs-20261026-v1.log",
        *(f"producer/{name}" for name in PRODUCERS),
    }
    common.require(required <= manifest["packet_artifacts"].keys(), "complete exact-glyph packet")
    files = packet_members(directory, common.binding(path)["sha256"])
    originals, views, dispositions, inventory, report = replay(directory)
    common.require(
        list(common.records(directory / "views.jsonl")) == views
        and list(common.records(directory / "candidate_dispositions.jsonl")) == dispositions
        and list(common.records(directory / "source_law_candidates.jsonl")) == inventory
        and json.loads((directory / "report.json").read_bytes()) == manifest["report"] == report,
        "all exact raw bodies, negatives and source accounting replay",
    )
    accepted = {view["bill_id"] for view in views}
    contexts = pq.read_table(directory / "context_inventory.parquet").to_pylist()
    common.require(
        contexts == [row for row in originals if row["bill_id"] in accepted],
        "all original context fields and unknowns preserved",
    )
    if metadata is not None:
        current = {row["bill_id"]: row for row in metadata}
        common.require(
            all(
                row["bill_id"] in current
                and all(
                    row[key] == current[row["bill_id"]][key]
                    for key in (
                        "state",
                        "session_identifier",
                        "identifier",
                        "source_introduction_date",
                    )
                )
                for row in contexts
            ),
            "current original identity or introduction-date conflict",
        )
    return (
        views,
        contexts,
        {name: common.binding(path)["sha256"] for name, path in files.items()},
        manifest,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent-packet", "glyph-evidence", "independent-witness", "gap-queue", "out-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(
        args.parent_packet,
        args.glyph_evidence,
        args.independent_witness,
        args.gap_queue,
        args.out_dir,
    )
    load_ne_enacted_hyphen(args.out_dir)
    print(json.dumps(manifest["report"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

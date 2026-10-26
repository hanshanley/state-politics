"""Qualify complete introduced constitutional proposals from fixed journal sources."""

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

from state_politics.bills import ne_journal_boundary_text as boundary
from state_politics.bills import ne_journal_collection as collection
from state_politics.bills import ne_journal_day_text as day
from state_politics.bills.ne_journal_text import load_ne_journal

ROOT = collection.ROOT
SCHEMA = "state-politics.nebraska-journal-constitutional-text.v1"
PROFILE = "whole_constitutional_proposal_and_literal_publication_boundaries_v1"
PARENT_SHA = "2c3b261f145325d5f38b185105efb1f21ff659e294dcd6ccd94fd0b85810b03b"
QUEUE_SHA = "f1631e502f6913dce8d7cd3a79ff63d6a5cef01fb71a29e24c6b073a6f6f86e7"
BOOKS = {
    name: {
        **book,
        "pdf": "parent/" + book["pdf"],
        "readers": "parent/" + book["readers"],
    }
    for name, book in boundary.BOOKS.items()
}
PRODUCERS = (
    "ne_journal_constitutional_text.py",
    "ne_journal_boundary_text.py",
    "ne_journal_day_text.py",
    "ne_journal_collection.py",
    "ne_journal_text.py",
)
VENUE = "THEMEMBERSOFTHEONEHUNDREDEIGHTHLEGISLATUREOFNEBRASKA,{session}SESSION,RESOLVETHAT:"
PROCEEDINGS = (
    "MOTIONS - Print in Journal",
    "UNANIMOUS CONSENT - Add Cointroducers",
    "UNANIMOUS CONSENT - Add Cointroducer(s)",
    "NOTICE OF COMMITTEE HEARINGS",
    "NOTICE OF COMMITTEE HEARING(S)",
    "ANNOUNCEMENT",
    "ANNOUNCEMENT(S)",
    "VISITOR(S)",
    "AMENDMENT(S) - Print in Journal",
)
PUBLICATION = re.compile(
    collection.OTHER.pattern
    + "|"
    + "|".join(
        "^" + r"\s*".join(re.escape(char) for char in "".join(heading.split())) + r"[ \t\xa0]*$"
        for heading in PROCEEDINGS
    ),
    re.M,
)


def raw_parts(spans, start, end):
    fragments, dates, pieces = [], set(), []
    for span in spans:
        left, right = max(start, span["start"]), min(end, span["end"])
        if left >= right:
            continue
        a = span["raw_start"] + left - span["start"]
        b = span["raw_start"] + right - span["start"]
        raw = span["row"]["text"][a:b]
        dates.add(span["date"])
        pieces.append(raw)
        fragments.append(
            {
                "page": span["page"],
                "start": a,
                "end": b,
                "sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "excluded_page_prefix": span["excluded_page_prefix"],
            }
        )
    return fragments, dates, "\n".join(pieces)


def candidates(pages, book):
    stream, spans = collection.collection_stream(pages, collection.EXPLICIT_DAY_HEADERS)
    result = []
    for ordinal, own in enumerate(collection.INTRO.finditer(stream)):
        if own["suffix"] != "CA":
            continue
        endings = [
            value
            for value in (
                PUBLICATION.search(stream, own.end()),
                collection.END.search(stream, own.end()),
            )
            if value is not None
        ]
        ending = min(endings, key=lambda value: value.start()) if endings else None
        start, end = own.start(), ending.start() if ending else len(stream)
        text = stream[start:end]
        fragments, dates, rebuilt = raw_parts(spans, start, end)
        excluded_join = None
        if ending and fragments and rebuilt + "\n" == text:
            following = [span for span in spans if span["start"] == end]
            if (
                len(following) == 1
                and fragments[-1]["page"] + 1 == following[0]["page"]
                and fragments[-1]["end"] == len(spans[fragments[-1]["page"] - 1]["row"]["text"])
            ):
                excluded_join = {
                    "start": end - 1,
                    "end": end,
                    "text": "\n",
                    "preceding_page": fragments[-1]["page"],
                    "following_page": following[0]["page"],
                }
                text = rebuilt
        terminators, _, literal_end = (
            raw_parts(spans, ending.start(), ending.end()) if ending else ([], set(), "")
        )
        normalized = collection.compact(text)
        venue = VENUE.format(session=book["session"])
        sections = re.findall(r"(?m)(?:^|(?<=\.))\s*Sec\.\s*(\d+)\s*\.", text)
        failures = []
        if not ending:
            failures.append("no_literal_publication_boundary")
        elif literal_end != ending[0]:
            failures.append("unreconstructable_literal_publication_boundary")
        if rebuilt != text:
            failures.append("unreconstructable_raw_page_boundary")
        observed = next(iter(dates)) if len(dates) == 1 else None
        if len(dates) != 1 or None in dates:
            failures.append("unresolved_or_multiple_printed_body_dates")
        elif not observed.startswith(f"{book['year']}-"):
            failures.append("outside_own_journal_year")
        if normalized.count(venue) != 1:
            failures.append("missing_unique_own_108th_constitutional_resolving_clause")
        if not normalized.partition(venue)[2].startswith("Section1."):
            failures.append("missing_own_first_proposal_section")
        if not sections or sections != [str(i) for i in range(2, len(sections) + 2)]:
            failures.append("missing_or_nonconsecutive_outer_proposal_sections")
        if "followingballotlanguage:" not in normalized:
            failures.append("missing_literal_ballot_language_introduction")
        if "ConstitutionofNebraska,ArticleXVI,section1" not in normalized:
            failures.append("missing_constitutional_submission_clause")
        if not normalized.endswith("ForAgainst."):
            failures.append("missing_complete_terminal_ballot_options")
        result.append(
            {
                "ordinal": ordinal,
                "identifier": "LR " + str(int(own["number"])) + "CA",
                "journal_date": observed,
                "reason": failures[0] if failures else None,
                "all_failed_checks": failures,
                "text": text,
                "fragments": fragments,
                "outer_sections_after_first": sections,
                "terminator": ending[0] if ending else None,
                "terminator_fragments": terminators,
                "excluded_synthetic_page_join": excluded_join,
            }
        )
    return result


def qualify(pages, originals, *, books=BOOKS):
    collection.require(set(pages) == set(books), "all fixed original source books required")
    collection.require(
        len({row["bill_id"] for row in originals}) == len(originals),
        "duplicate original context identity",
    )
    counts = Counter(
        (row["state"], row["session_identifier"], row["identifier"]) for row in originals
    )
    indexed, inventory = defaultdict(list), []
    for name, book in books.items():
        collection.require(set(pages[name]) == set(collection.READERS), "both complete readers")
        for reader in collection.READERS:
            for candidate in candidates(pages[name][reader], book):
                value = {"document": name, "reader": reader, **candidate}
                indexed[reader, value["identifier"]].append(value)
                inventory.append(value)
    views, dispositions = [], []
    for original in originals:
        if original["state"] != "NE":
            continue
        reason, selected = None, {}
        if original["session_identifier"] != "108" or not re.fullmatch(
            r"LR \d+CA", original["identifier"]
        ):
            reason = "outside_108th_constitutional_resolution_profile"
        elif counts["NE", "108", original["identifier"]] != 1:
            reason = "ambiguous_original_context_identity"
        for reader in collection.READERS:
            found = [
                value
                for value in indexed[reader, original["identifier"]]
                if value["reason"] is None
                and value["journal_date"] == original["source_introduction_date"]
            ]
            if len(found) != 1:
                reason = reason or "no_unique_complete_exact_original_date_proposal"
            else:
                selected[reader] = found[0]
        if len(selected) == 2:
            if len({value["document"] for value in selected.values()}) != 1:
                reason = reason or "readers_select_different_source_documents"
            if len({collection.compact(value["text"]) for value in selected.values()}) != 1:
                reason = reason or "whole_constitutional_proposal_reader_disagreement"
        dispositions.append(
            {
                **{
                    key: original[key]
                    for key in ("bill_id", "state", "identifier", "session_identifier")
                },
                "disposition": reason or "complete_two_reader_original_context_match",
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
                        f"ne-journal-ca-v1:{name}:{book['sha256']}:{reader}:{candidate['ordinal']}"
                    ),
                    "source_type": "archive_text",
                    "bill_id": original["bill_id"],
                    "state": "NE",
                    "identifier": original["identifier"],
                    "session_identifier": "108",
                    "title": original["title"],
                    "text": text,
                    "raw_text_characters": len(text),
                    "raw_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "source_record": {
                        "provider": "Nebraska State Library, official Legislative Journal",
                        "url": book["url"],
                        "reader": reader,
                        "document": name,
                        "source_PDF_sha256": book["sha256"],
                        "journal_year": book["year"],
                        "journal_session": book["session"],
                        "journal_volume": book["volume"],
                        "journal_date": candidate["journal_date"],
                        "resolution_ordinal": candidate["ordinal"],
                        "page_fragments": candidate["fragments"],
                        "fragment_joiner": "\n",
                        "page_header_profile": collection.EXPLICIT_DAY_HEADERS,
                        "boundary_profile": PROFILE,
                        "terminator_not_policy_text": candidate["terminator"],
                        "terminator_fragments": candidate["terminator_fragments"],
                        "excluded_synthetic_page_join": candidate["excluded_synthetic_page_join"],
                        "outer_sections_after_first": candidate["outer_sections_after_first"],
                        "constitutional_proposal": True,
                    },
                    "source_identity": {
                        "state": "NE",
                        "session_identifier": "108",
                        "identifier": original["identifier"],
                        "profile": PROFILE,
                    },
                    **dict.fromkeys(collection.FLAGS, False),
                }
            )
    return views, dispositions, inventory


def previous_admissions(parent, pages):
    views, contexts = [], []
    for directory, loader in (
        (parent, boundary.load_ne_journal_boundary),
        (parent / "parent", day.load_ne_journal_day),
        (parent / "parent/parent", collection.load_ne_journal_collection),
        (parent / "parent/sealed", load_ne_journal),
    ):
        saved, original, _, _ = loader(directory)
        views.extend(saved)
        contexts.extend(original)
    original_text = {
        (view["bill_id"], view["source_record"]["reader"]): view["text"] for view in views
    }
    collection.require(
        len(contexts) == len({row["bill_id"] for row in contexts}) == 464
        and len(original_text) == 928,
        "all prior journal contexts and exact strings",
    )
    observed, dispositions, _ = boundary.qualify(pages, contexts)
    collection.require(
        len(observed) == 928
        and {view["bill_id"] for view in observed} == {row["bill_id"] for row in contexts}
        and all(
            view["text"] == original_text[view["bill_id"], view["source_record"]["reader"]]
            for view in observed
        ),
        "all previous dates and policy strings remain qualified and byte-identical",
    )
    return {row["bill_id"] for row in contexts}, {
        "existing_contexts_retained": 464,
        "existing_policy_strings_byte_identical": 928,
        "all_previous_context_dispositions": dispositions,
    }


def replay(directory):
    parent = directory / "parent"
    day.packet_members(parent, PARENT_SHA)
    collection.require(
        collection.binding(directory / "input_gap_queue.parquet")["sha256"] == QUEUE_SHA,
        "externally pinned current complete gap queue",
    )
    pages = day.source_pages(parent / "parent")
    previous, prior_report = previous_admissions(parent, pages)
    originals = pq.read_table(directory / "input_gap_queue.parquet").to_pylist()
    views, dispositions, inventory = qualify(pages, originals)
    collection.require(
        not previous & {row["bill_id"] for row in originals}
        and len({view["view_id"] for view in views}) == len(views),
        "gap-only new contexts with non-colliding typed CA view identities",
    )
    report = {
        **collection.report_for(originals, views, dispositions, inventory),
        **prior_report,
        "page_header_profile": collection.EXPLICIT_DAY_HEADERS,
        "constitutional_proposal_profile": PROFILE,
        "old_source_packets_or_profiles_modified": False,
        "original_dates_or_policy_text_repaired_or_normalized": False,
    }
    return originals, views, dispositions, inventory, report


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
        "externally pinned unlinked complete original gap queue",
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
    originals, views, dispositions, inventory, report = replay(output)
    collection.require(views, "nonempty complete new constitutional proposals")
    accepted = {view["bill_id"] for view in views}
    table = pq.read_table(output / "input_gap_queue.parquet")
    pq.write_table(
        table.filter(pa.array([row["bill_id"] in accepted for row in originals])),
        output / "context_inventory.parquet",
    )
    for name, values in (
        ("views.jsonl", views),
        ("candidate_dispositions.jsonl", dispositions),
        ("source_resolution_candidates.jsonl", inventory),
    ):
        collection.write_rows(output / name, values)
    collection.write_json(output / "report.json", report)
    manifest = {
        "schema": SCHEMA,
        "source_profiles": BOOKS,
        "parent_packet_sha256": PARENT_SHA,
        "original_gap_queue_sha256": QUEUE_SHA,
        "page_header_profile": collection.EXPLICIT_DAY_HEADERS,
        "constitutional_proposal_profile": PROFILE,
        "report": report,
        "approvals": dict.fromkeys(collection.FLAGS, False),
        "packet_artifacts": {
            path.relative_to(output).as_posix(): collection.binding(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    collection.write_json(output / "manifest.json", manifest)
    collection.require(
        all(
            collection.binding(source) == collection.binding(output / "parent" / name)
            for name, source in files.items()
        )
        and collection.binding(queue)["sha256"] == QUEUE_SHA,
        "all original inputs unchanged during qualification",
    )
    return manifest


def load_ne_journal_constitutional(directory, metadata=None):
    directory = Path(directory).absolute()
    collection.require(
        directory.is_dir() and directory.resolve() == directory,
        "unlinked packet root",
    )
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    collection.require(
        manifest["schema"] == SCHEMA
        and manifest["source_profiles"] == BOOKS
        and manifest["parent_packet_sha256"] == PARENT_SHA
        and manifest["original_gap_queue_sha256"] == QUEUE_SHA
        and manifest["page_header_profile"] == collection.EXPLICIT_DAY_HEADERS
        and manifest["constitutional_proposal_profile"] == PROFILE
        and all(manifest["approvals"].get(flag) is False for flag in collection.FLAGS),
        "fixed unapproved whole constitutional-proposal source profile",
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
    collection.require(required <= manifest["packet_artifacts"].keys(), "complete CA source packet")
    files = day.packet_members(directory, collection.binding(manifest_path)["sha256"])
    originals, views, dispositions, inventory, report = replay(directory)
    collection.require(
        list(collection.records(directory / "views.jsonl")) == views
        and list(collection.records(directory / "candidate_dispositions.jsonl")) == dispositions
        and list(collection.records(directory / "source_resolution_candidates.jsonl")) == inventory
        and json.loads((directory / "report.json").read_bytes()) == manifest["report"] == report,
        "every accepted and rejected record and exact complete-source accounting replay",
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
                    for key in (
                        "state",
                        "session_identifier",
                        "identifier",
                        "source_introduction_date",
                    )
                )
                for row in contexts
            ),
            "current original context identity or introduction-date conflict",
        )
    return (
        views,
        contexts,
        {name: collection.binding(path)["sha256"] for name, path in files.items()},
        manifest,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent-packet", "gap-queue", "out-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(args.parent_packet, args.gap_queue, args.out_dir)
    load_ne_journal_constitutional(args.out_dir)
    print(json.dumps(manifest["report"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Qualify whole enacted Nebraska laws without calling them introduced versions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from contextlib import suppress
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from state_politics.bills import ne_journal_collection as common
from state_politics.bills.ne_journal_day_text import packet_members

SCHEMA = "state-politics.nebraska-enacted-law-text.v1"
PROFILE = "whole_enacted_law_consecutive_literal_pages_v1"
ROOT = common.ROOT
QUEUE_SHA = "712543ae5b85ed784ad6e968d24a0b33b55b032f2fa2e454753baac60e03a43b"
BUNDLES = {
    "source": "a1331dc8bc45ff6a6c0f57857a53fba23d6118d3f41a009213db73ccb06780e0",
    "readers": "51da1e432ff2bfd1d59c49843dafd0e90befca112de737433b9eea81c9d50a36",
}
BOOKS = {
    "laws-2023": {
        "year": 2023,
        "session": "FIRST",
        "volume": 1,
        "pages": 833,
        "sha256": "28111493682810466ac479d0aa0404e9fb97c84049a6329761e69d27acf36951",
        "url": "https://govdocs.nebraska.gov/epubs/L3300/Q002-2023.pdf",
    },
    "laws-2024-v1": {
        "year": 2024,
        "session": "SECOND",
        "volume": 1,
        "pages": 666,
        "sha256": "05cb64cf5d212fee21498ac28f61e05ef628197e73e76f60002ac3bf8dcf56fb",
        "url": "https://govdocs.nebraska.gov/epubs/L3300/Q002-2024v1.pdf",
    },
    "laws-2024-v2": {
        "year": 2024,
        "session": "SECOND",
        "volume": 2,
        "pages": 666,
        "sha256": "ef9da2358e0fc48b2531c7164de864f1421d6f408643a09c38e442b9ec052dbc",
        "url": "https://govdocs.nebraska.gov/epubs/L3300/Q002-2024v2.pdf",
    },
}
PRODUCERS = (
    "ne_enacted_law_text.py",
    "ne_journal_day_text.py",
    "ne_journal_collection.py",
    "ne_journal_text.py",
)
OWN = re.compile(r"\bLEGISLATIVE\s*BILL\s*(\d+)\s*(A?)\b")
APPROVAL = re.compile(
    r"Approved\s*by\s*the\s*Governor\s*"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s*\d{1,2}\s*,\s*20\d{2})"
)
CAPTION = re.compile(r"A\s*BILL\s*FOR\s*AN\s*ACT\b")
ENACT = re.compile(r"Be\s*it\s*enacted\s*by\s*the\s*people\s*of\s*the\s*State\s*of\s*Nebraska\s*,")
FIRST = re.compile(r"\bSection\s*1\s*\.")
FOLIO = re.compile(r"\s*-\s*(\d+)\s*-\s*(?:\d+\s*)?\Z")


def candidates(pages, book):
    starts = [
        (index, match)
        for index, row in enumerate(pages)
        if (match := OWN.search(row["text"][:600])) is not None
    ]
    result = []
    for ordinal, (start, own) in enumerate(starts):
        stop = starts[ordinal + 1][0] if ordinal + 1 < len(starts) else len(pages)
        selected = pages[start:stop]
        number = f"{int(own[1])}{own[2]}"
        header = re.compile(r"\A\s*LB\s*" + re.escape(number) + r"\s*" + str(book["year"]) + r"\b")
        approval = APPROVAL.search(selected[0]["text"][:800])
        date = None
        if approval:
            with suppress(ValueError):
                date = datetime.strptime(common.compact(approval[1]), "%B%d,%Y").date().isoformat()
        failed = []
        if not all(header.match(row["text"]) for row in selected):
            failed.append("one_or_more_pages_lack_their_exact_own_running_header")
        if date is None:
            failed.append("no_literal_governor_approval_date")
        elif not date.startswith(str(book["year"]) + "-"):
            failed.append("approval_year_conflicts_with_book")
        for pattern, reason in (
            (CAPTION, "no_literal_full_bill_caption"),
            (ENACT, "no_literal_enacting_clause"),
            (FIRST, "no_literal_first_section"),
        ):
            if not pattern.search(selected[0]["text"]):
                failed.append(reason)
        folios = [FOLIO.search(row["text"]) for row in selected]
        if not all(folios) or [int(match[1]) for match in folios] != list(
            range(1, len(selected) + 1)
        ):
            failed.append("no_complete_consecutive_literal_bill_page_folios")
        terminal = selected[-1]["text"][: folios[-1].start()] if folios[-1] else ""
        if not terminal.rstrip().endswith("."):
            failed.append("no_complete_literal_terminal_full_stop")
        result.append(
            {
                "ordinal": ordinal,
                "identifier": "LB " + number,
                "approval_date": date,
                "literal_approval": approval[0] if approval else None,
                "reason": failed[0] if failed else None,
                "all_failed_checks": failed,
                "text": "\n".join(row["text"] for row in selected),
                "fragments": [
                    {
                        "page": row["page"],
                        "start": 0,
                        "end": len(row["text"]),
                        "sha256": hashlib.sha256(row["text"].encode()).hexdigest(),
                    }
                    for row in selected
                ],
                "bill_page_folios": [match[0] if match else None for match in folios],
                "following_law_heading": starts[ordinal + 1][1][0]
                if ordinal + 1 < len(starts)
                else None,
                "following_law_physical_page": pages[stop]["page"] if stop < len(pages) else None,
                "ends_at_physical_book_end": stop == len(pages),
            }
        )
    return result


def qualify(pages, originals, *, books=BOOKS):
    common.require(set(pages) == set(books), "all fixed enacted-law books required")
    common.require(
        len({row["bill_id"] for row in originals}) == len(originals),
        "duplicate original context identity",
    )
    identities = Counter(
        (row["state"], row["session_identifier"], row["identifier"]) for row in originals
    )
    indexed, inventory = defaultdict(list), []
    for name, book in books.items():
        common.require(set(pages[name]) == set(common.READERS), "both complete law-book readers")
        for reader in common.READERS:
            for candidate in candidates(pages[name][reader], book):
                value = {"document": name, "reader": reader, **candidate}
                inventory.append(value)
                indexed[reader, value["identifier"]].append(value)
    views, dispositions = [], []
    for original in originals:
        if original["state"] != "NE":
            continue
        reason, selected = None, {}
        date = original["source_introduction_date"]
        if original["session_identifier"] != "108" or not re.fullmatch(
            r"LB \d+A?", original["identifier"]
        ):
            reason = "outside_108th_legislative_bill_profile"
        elif identities["NE", "108", original["identifier"]] != 1:
            reason = "ambiguous_original_context_identity"
        elif not isinstance(date, str) or not re.fullmatch(r"202[34]-\d{2}-\d{2}", date):
            reason = "unresolved_original_introduction_date"
        for reader in common.READERS:
            found = [
                value
                for value in indexed[reader, original["identifier"]]
                if value["reason"] is None
                and isinstance(date, str)
                and value["approval_date"] >= date
            ]
            if len(found) != 1:
                reason = reason or "no_unique_complete_enacted_law_after_original_introduction"
            else:
                selected[reader] = found[0]
        if len(selected) == 2:
            if len({value["document"] for value in selected.values()}) != 1:
                reason = reason or "readers_select_different_law_books"
            if len({value["approval_date"] for value in selected.values()}) != 1:
                reason = reason or "reader_approval_date_disagreement"
            if len({common.compact(value["text"]) for value in selected.values()}) != 1:
                reason = reason or "whole_enacted_law_reader_disagreement"
        dispositions.append(
            {
                **{
                    key: original[key]
                    for key in ("bill_id", "state", "identifier", "session_identifier")
                },
                "disposition": reason or "complete_two_reader_enacted_version_match",
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
                        f"ne-enacted-law-v1:{name}:{book['sha256']}:{reader}:{candidate['ordinal']}"
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
                    },
                    "source_identity": {
                        "state": "NE",
                        "session_identifier": "108",
                        "identifier": original["identifier"],
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


def source_pages(directory):
    for name, pin in BUNDLES.items():
        common.input_bundle(directory / name, pin)
    capture = json.loads((directory / "source/manifest.json").read_bytes())
    common.require(
        capture["complete_response_collection"] is True
        and capture["controlled_GET_attempts_total"] == 4
        and capture["version_scope"] == "enacted_laws_not_introduced_versions",
        "complete fixed bounded enacted-law capture",
    )
    pages = {name: {} for name in BOOKS}
    for reader in common.READERS:
        rows = list(common.records(directory / f"readers/pages-{reader}.jsonl"))
        common.require(len(rows) == 2165, "all literal physical reader pages")
        for name, book in BOOKS.items():
            common.require(
                common.binding(directory / f"source/{name}.body")["sha256"] == book["sha256"],
                "fixed whole law-book PDF",
            )
            selected = [row for row in rows if row["document"] == name]
            common.require(
                [row["page"] for row in selected] == list(range(1, book["pages"] + 1))
                and all(
                    row["reader"] == reader
                    and row["source_PDF_sha256"] == book["sha256"]
                    and len(row["text"]) == row["characters"]
                    and hashlib.sha256(row["text"].encode()).hexdigest() == row["sha256"]
                    for row in selected
                ),
                "complete exact reader page ledger",
            )
            title = common.compact(selected[0]["text"])
            common.require(
                all(
                    value in title
                    for value in (
                        "LEGISLATUREOFTHESTATEOFNEBRASKA",
                        "ONEHUNDREDEIGHTHLEGISLATURE",
                        book["session"] + "SESSION",
                        str(book["year"]),
                    )
                ),
                "literal own state, legislature and law-book session",
            )
            pages[name][reader] = selected
    return pages


def replay(directory):
    common.require(
        common.binding(directory / "input_gap_queue.parquet")["sha256"] == QUEUE_SHA,
        "externally pinned complete original gap queue",
    )
    originals = pq.read_table(directory / "input_gap_queue.parquet").to_pylist()
    views, dispositions, inventory = qualify(source_pages(directory), originals)
    report = {
        "status": "qualified_complete_enacted_laws_not_introduced_or_scientifically_certified",
        "original_gap_contexts": len(originals),
        "original_NE_gap_contexts": sum(row["state"] == "NE" for row in originals),
        "recovered_original_contexts": len({row["bill_id"] for row in views}),
        "complete_reader_views": len(views),
        "complete_policy_characters": sum(len(row["text"]) for row in views),
        "candidate_dispositions": dict(Counter(row["disposition"] for row in dispositions)),
        "source_candidate_dispositions": dict(
            Counter(row["reason"] or "complete_own_enacted_law_profile" for row in inventory)
        ),
        "source_version": "enacted_not_introduced",
        "all_raw_pages_retained": 4330,
        "original_context_fields_modified": False,
        "source_collection_during_qualification": False,
        "model_execution": False,
        "publication": False,
    }
    return originals, views, dispositions, inventory, report


def build(capture, readers, queue, output):
    capture, readers, queue, output = (
        Path(path).absolute() for path in (capture, readers, queue, output)
    )
    common.require(
        not output.exists()
        and output.resolve() == output
        and output != ROOT / "data/processed"
        and output.is_relative_to(ROOT / "data/processed"),
        "fresh unlinked output under project data/processed",
    )
    common.require(
        queue.resolve() == queue and common.binding(queue)["sha256"] == QUEUE_SHA,
        "pinned unlinked gap queue",
    )
    inputs = {
        name: common.input_bundle(directory, BUNDLES[name])
        for name, directory in (("source", capture), ("readers", readers))
    }
    output.mkdir(parents=True)
    for prefix, files in inputs.items():
        for name, path in files.items():
            target = output / prefix / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    shutil.copy2(queue, output / "input_gap_queue.parquet")
    (output / "producer").mkdir()
    for name in PRODUCERS:
        shutil.copy2(Path(__file__).with_name(name), output / "producer" / name)
    originals, views, dispositions, inventory, report = replay(output)
    common.require(views, "nonempty complete enacted laws")
    accepted = {view["bill_id"] for view in views}
    table = pq.read_table(output / "input_gap_queue.parquet")
    pq.write_table(
        table.filter(pa.array([row["bill_id"] in accepted for row in originals])),
        output / "context_inventory.parquet",
    )
    for name, values in (
        ("views.jsonl", views),
        ("candidate_dispositions.jsonl", dispositions),
        ("source_law_candidates.jsonl", inventory),
    ):
        common.write_rows(output / name, values)
    common.write_json(output / "report.json", report)
    manifest = {
        "schema": SCHEMA,
        "source_profiles": BOOKS,
        "input_bundles": BUNDLES,
        "original_gap_queue_sha256": QUEUE_SHA,
        "source_profile": PROFILE,
        "report": report,
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
            common.binding(path) == common.binding(output / prefix / name)
            for prefix, files in inputs.items()
            for name, path in files.items()
        )
        and common.binding(queue)["sha256"] == QUEUE_SHA,
        "all original sources unchanged during qualification",
    )
    return manifest


def load_ne_enacted_law(directory, metadata=None):
    directory = Path(directory).absolute()
    common.require(directory.is_dir() and directory.resolve() == directory, "unlinked packet root")
    path = directory / "manifest.json"
    manifest = json.loads(path.read_bytes())
    common.require(
        manifest["schema"] == SCHEMA
        and manifest["source_profiles"] == BOOKS
        and manifest["input_bundles"] == BUNDLES
        and manifest["original_gap_queue_sha256"] == QUEUE_SHA
        and manifest["source_profile"] == PROFILE
        and all(manifest["approvals"].get(flag) is False for flag in common.FLAGS),
        "fixed unapproved whole enacted-law source profile",
    )
    required = {
        "input_gap_queue.parquet",
        "context_inventory.parquet",
        "views.jsonl",
        "candidate_dispositions.jsonl",
        "source_law_candidates.jsonl",
        "report.json",
        *(f"producer/{name}" for name in PRODUCERS),
    }
    common.require(required <= manifest["packet_artifacts"].keys(), "complete enacted-law packet")
    files = packet_members(directory, common.binding(path)["sha256"])
    originals, views, dispositions, inventory, report = replay(directory)
    common.require(
        list(common.records(directory / "views.jsonl")) == views
        and list(common.records(directory / "candidate_dispositions.jsonl")) == dispositions
        and list(common.records(directory / "source_law_candidates.jsonl")) == inventory
        and json.loads((directory / "report.json").read_bytes()) == manifest["report"] == report,
        "all admitted bodies, negatives, dates and source-version accounting replay",
    )
    accepted = {view["bill_id"] for view in views}
    contexts = pq.read_table(directory / "context_inventory.parquet").to_pylist()
    common.require(
        contexts == [row for row in originals if row["bill_id"] in accepted],
        "all original fields and unknowns",
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
    for name in ("source-capture", "source-readers", "gap-queue", "out-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(args.source_capture, args.source_readers, args.gap_queue, args.out_dir)
    load_ne_enacted_law(args.out_dir)
    print(json.dumps(manifest["report"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Qualify fixed 2023/2024 official journal profiles without changing sealed v1."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from state_politics.bills.ne_journal_text import (
    DAILY,
    END,
    FLAGS,
    MONTHS,
    OTHER,
    READERS,
    binding,
    compact,
    journal_stream,
    records,
    require,
    write_json,
    write_rows,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "state-politics.nebraska-journal-collection-text.v2"
LEGACY_SCHEMA = "state-politics.nebraska-journal-collection-text.v1"
LEGACY_HEADERS = "sealed_running_headers_v1"
LITERAL_HEADERS = "literal_letterspaced_running_headers_v2"
EXPLICIT_DAY_HEADERS = "literal_number_first_day_headers_v1"
QUEUE_SHA = "77400a15a69ed74cfcc57b706cf7e72668afa7f8eca80a199bd5cd266a25b813"
INPUTS = {
    "first/source": "ba6b0f5db28d9a6797a3f13e1f211ae91fcfa309aadfcac2bbcc6f768fefa5fa",
    "first/readers": "2c192731d6f077cbfe8b22495cb581ce546c9abe4391fc4127b4c778bfe4c6f8",
    "second/source": "b85ab00a65d310efbe5c914fc66979f30c34ec002d7ceb73cabb4acee71cc25c",
    "second/readers": "709bb1eefa406d5cf340a5fe0a9d6bf12cfe167b698011fdf7655e08cd873db9",
}
BOOKS = {
    "journal-2023-v1": {
        "year": 2023,
        "session": "FIRST",
        "volume": 1,
        "pages": 1320,
        "pdf": "first/source/journal-2023-v1.body",
        "readers": "first/readers/journal-2023-v1-pages-{reader}.jsonl",
        "sha256": "65d07ba4bc796ff7fa375ebc58de3a73cb06251c8c43ea69f5497fab21668e2f",
        "url": "https://govdocs.nebraska.gov/epubs/L3300/T001-2023v1.pdf",
    },
    "journal-2023-v2": {
        "year": 2023,
        "session": "FIRST",
        "volume": 2,
        "pages": 1345,
        "pdf": "first/source/journal-2023-v2.body",
        "readers": "first/readers/journal-2023-v2-pages-{reader}.jsonl",
        "sha256": "f2b2a1ace7beaf1c55b4505065a3adf61bed23867c8361a7f3675477e34c6acd",
        "url": "https://govdocs.nebraska.gov/epubs/L3300/T001-2023v2.pdf",
    },
    "journal-2024-v1": {
        "year": 2024,
        "session": "SECOND",
        "volume": 1,
        "pages": 1370,
        "pdf": "second/source/journal-response.body",
        "readers": "second/readers/pages-{reader}.jsonl",
        "sha256": "f2ce1960af68ece140f3af2d27d25daf1ee1df061e969019ebbfb644d2869a2f",
        "url": "https://govdocs.nebraska.gov/epubs/L3300/T001-2024v1.pdf",
    },
}
INTRO = re.compile(
    r"(?m)^LEGISLATIVE\s*RESOLUTION\s*(?P<number>\d+)(?P<suffix>CA)?\."
    r"\s*Introduced\s*by[^\n]*\n"
)
VENUE = (
    "NOW,THEREFORE,BEITRESOLVEDBYTHEMEMBERSOFTHE"
    "ONEHUNDREDEIGHTHLEGISLATUREOFNEBRASKA,{session}SESSION:"
)
RUNNING_LITERAL = re.compile(
    r"\A" + r"\s*".join("LEGISLATIVEJOURNAL") + r"\s*(?P<printed>\d{1,4})[ \t\xa0]*\n"
)
NUMBER_FIRST_DAY = re.compile(
    r"\A(?P<printed>\d{1,4})\s+[A-Z \-]+DAY\s*[-–—]\s*(?P<month>"
    + "|".join(MONTHS)
    + r")\s*(?P<day>\d{1,2}),\s*(?P<year>20\d{2})[ \t\xa0]*\n"
)


def collection_stream(pages, header_profile):
    if header_profile == LEGACY_HEADERS:
        return journal_stream(pages)
    require(
        header_profile in (LITERAL_HEADERS, EXPLICIT_DAY_HEADERS),
        "known literal page-header profile",
    )
    chunks, spans, position, current_date = [], [], 0, None
    for expected, row in enumerate(pages, 1):
        text = row["text"]
        require(
            row["page"] == expected
            and row["characters"] == len(text)
            and row["sha256"] == hashlib.sha256(text.encode()).hexdigest(),
            "page identity/text/hash",
        )
        header = DAILY.match(text)
        kind = "printed_daily_header"
        if not header and header_profile == EXPLICIT_DAY_HEADERS:
            header = NUMBER_FIRST_DAY.match(text)
            kind = "printed_day_opening_header_number_first"
        if header:
            current_date = date(
                int(header["year"]), MONTHS[header["month"]], int(header["day"])
            ).isoformat()
        else:
            header = RUNNING_LITERAL.match(text)
            kind = "printed_running_header_whitespace_only"
        cut = header.end() if header else 0
        clean = text[cut:]
        chunks.append(clean)
        removed = (
            {
                "start": 0,
                "end": cut,
                "kind": kind,
                "text": text[:cut],
                "sha256": hashlib.sha256(text[:cut].encode()).hexdigest(),
            }
            if header
            else None
        )
        spans.append(
            {
                "page": expected,
                "start": position,
                "end": position + len(clean),
                "raw_start": cut,
                "date": current_date,
                "row": row,
                "excluded_page_prefix": removed,
            }
        )
        position += len(clean) + 1
    return "\n".join(chunks), spans


def candidates(pages, book, *, header_profile=LITERAL_HEADERS):
    stream, spans = collection_stream(pages, header_profile)
    by_page = {row["page"]: row["text"] for row in pages}
    venue = VENUE.format(session=book["session"])
    result = []
    for ordinal, header in enumerate(INTRO.finditer(stream)):
        start = header.start()
        following = OTHER.search(stream, header.end())
        ending = END.search(stream, header.end())
        end = ending.start() if ending else len(stream)
        reason = None
        if not ending or end - start > 60000:
            reason = "no_bounded_complete_resolution_end"
        elif following and following.start() < end:
            reason = "another_legislative_item_before_end"
        elif header["suffix"]:
            reason = "constitutional_amendment_outside_profile"
        text, fragments, dates = stream[start:end], [], set()
        for span in spans:
            left, right = max(start, span["start"]), min(end, span["end"])
            if left >= right:
                continue
            a = span["raw_start"] + left - span["start"]
            b = span["raw_start"] + right - span["start"]
            raw = by_page[span["page"]][a:b]
            dates.add(span["date"])
            fragment = {
                "page": span["page"],
                "start": a,
                "end": b,
                "sha256": hashlib.sha256(raw.encode()).hexdigest(),
            }
            if header_profile != LEGACY_HEADERS:
                fragment["excluded_page_prefix"] = span["excluded_page_prefix"]
            fragments.append(fragment)
        if len(dates) != 1 or None in dates:
            reason = reason or "unresolved_or_multiple_journal_dates"
        observed = next(iter(dates)) if len(dates) == 1 else None
        if observed and not observed.startswith(f"{book['year']}-"):
            reason = reason or "outside_own_journal_year"
        rebuilt = "\n".join(by_page[s["page"]][s["start"] : s["end"]] for s in fragments)
        if rebuilt != text:
            reason = reason or "unreconstructable_page_boundary"
        normalized = compact(text)
        if venue not in normalized:
            reason = reason or "missing_own_108th_session_resolving_clause"
        after = normalized.partition(venue)[2]
        has_recital = re.search(r"\bWHEREAS,|\bPURPOSE:", text) is not None
        numbered_operative_only = after.startswith("1.That") and len(after) >= 40
        if not (has_recital or numbered_operative_only) or len(after) < 20:
            reason = reason or "missing_substantive_resolution_body"
        if not normalized.endswith("."):
            reason = reason or "missing_complete_body_ending"
        result.append(
            {
                "ordinal": ordinal,
                "identifier": "LR " + str(int(header["number"])),
                "journal_date": observed,
                "reason": reason,
                "text": text,
                "fragments": fragments,
                "terminator": ending[0] if ending else None,
            }
        )
    return result


def qualify(pages_by_book, originals, *, books=BOOKS, header_profile=LITERAL_HEADERS):
    require(set(pages_by_book) == set(books), "all fixed source books required")
    require(len({r["bill_id"] for r in originals}) == len(originals), "duplicate original context")
    identity_counts = Counter(
        (r["state"], r["session_identifier"], r["identifier"]) for r in originals
    )
    indexed, all_candidates = defaultdict(list), []
    for name, book in books.items():
        require(set(pages_by_book[name]) == set(READERS), "both complete readers required")
        for reader in READERS:
            for candidate in candidates(
                pages_by_book[name][reader], book, header_profile=header_profile
            ):
                value = {"document": name, "reader": reader, **candidate}
                indexed[reader, candidate["identifier"]].append(value)
                all_candidates.append(value)
    views, dispositions = [], []
    for row in originals:
        if row["state"] != "NE":
            continue
        reason, selected = None, {}
        if row["session_identifier"] != "108" or not re.fullmatch(r"LR \d+", row["identifier"]):
            reason = "outside_ordinary_108th_resolution_profile"
        elif identity_counts["NE", "108", row["identifier"]] != 1:
            reason = "ambiguous_original_context_identity"
        for reader in READERS:
            found = indexed[reader, row["identifier"]]
            matching = [
                c
                for c in found
                if c["reason"] is None and c["journal_date"] == row["source_introduction_date"]
            ]
            if len(matching) != 1:
                reason = reason or (
                    "no_unique_complete_same_date_journal_body"
                    if found
                    else "no_introduced_resolution_in_supplied_books"
                )
            else:
                selected[reader] = matching[0]
        if len(selected) == 2:
            if len({c["document"] for c in selected.values()}) != 1:
                reason = reason or "readers_select_different_source_documents"
            if len({compact(c["text"]) for c in selected.values()}) != 1:
                reason = reason or "PDF_readers_disagree_on_complete_body"
        dispositions.append(
            {
                **{k: row[k] for k in ("bill_id", "state", "identifier", "session_identifier")},
                "disposition": reason or "complete_two_reader_original_context_match",
            }
        )
        if reason:
            continue
        for reader, candidate in selected.items():
            name = candidate["document"]
            book = books[name]
            text = candidate["text"]
            namespace = (
                "ne-journal-day-v1"
                if header_profile == EXPLICIT_DAY_HEADERS
                else f"ne-journal-collection-v{2 if header_profile == LITERAL_HEADERS else 1}"
            )
            views.append(
                {
                    "view_id": (
                        f"{namespace}:{name}:{book['sha256']}:{reader}:{candidate['ordinal']}"
                    ),
                    "source_type": "archive_text",
                    "bill_id": row["bill_id"],
                    "state": "NE",
                    "identifier": row["identifier"],
                    "session_identifier": "108",
                    "title": row["title"],
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
                        "terminator_not_policy_text": candidate["terminator"],
                        "page_fragments": candidate["fragments"],
                        "page_header_removal_only": True,
                        "fragment_joiner": "\n",
                        **(
                            {"page_header_profile": header_profile}
                            if header_profile != LEGACY_HEADERS
                            else {}
                        ),
                    },
                    "source_identity": {
                        "state": "NE",
                        "session_identifier": "108",
                        "identifier": row["identifier"],
                        "profile": (
                            "own_wrapped_introduced_header_session_clause_exact_original_date"
                        ),
                    },
                    **dict.fromkeys(FLAGS, False),
                }
            )
    return views, dispositions, all_candidates


def safe_member(name):
    return (
        isinstance(name, str)
        and bool(name)
        and "\\" not in name
        and not Path(name).is_absolute()
        and ".." not in Path(name).parts
        and Path(name).as_posix() == name
    )


def input_bundle(directory, pin):
    require(directory.resolve() == directory and directory.is_dir(), "unlinked source directory")
    manifest_path = directory / "manifest.json"
    require(binding(manifest_path)["sha256"] == pin, "externally pinned input manifest")
    manifest = json.loads(manifest_path.read_bytes())
    require(
        isinstance(manifest["artifacts"], dict) and manifest["artifacts"], "complete source files"
    )
    files = {"manifest.json": manifest_path}
    for name, expected in manifest["artifacts"].items():
        require(safe_member(name) and name != "manifest.json", "safe source member")
        source = directory / name
        require(source.is_file() and source.resolve() == source, "unlinked source artifact")
        require(
            binding(source) == {k: expected[k] for k in ("sha256", "bytes")},
            "complete source artifact binding",
        )
        files[name] = source
    return files


def source_pages(directory):
    for prefix, pin in INPUTS.items():
        input_bundle(directory / prefix, pin)
    first = json.loads((directory / "first/source/manifest.json").read_bytes())
    second = json.loads((directory / "second/source/manifest.json").read_bytes())
    require(
        first["complete_response_collection"] is True
        and first["controlled_GET_attempts_total"] == 3
        and second["complete_response"] is True,
        "complete bounded original captures",
    )
    require(
        binding(directory / "input_gap_queue.parquet")["sha256"] == QUEUE_SHA,
        "fixed original missing-context queue",
    )
    pages_by_book = {}
    for name, book in BOOKS.items():
        require(
            binding(directory / book["pdf"])["sha256"] == book["sha256"],
            "fixed complete original source PDF",
        )
        readers = {}
        for reader in READERS:
            pages = list(records(directory / book["readers"].format(reader=reader)))
            require(
                len(pages) == book["pages"]
                and all(
                    row["reader"] == reader
                    and row["page"] == i
                    and row["characters"] == len(row["text"])
                    and row["sha256"] == hashlib.sha256(row["text"].encode()).hexdigest()
                    for i, row in enumerate(pages, 1)
                ),
                "complete original reader page strings",
            )
            cover = compact(pages[0]["text"])
            require(
                f"Volume{book['volume']}" in cover
                and f"ONEHUNDREDEIGHTHLEGISLATURE{book['session']}SESSION{book['year']}" in cover,
                "own printed journal cover/session/year/volume",
            )
            readers[reader] = pages
        pages_by_book[name] = readers
    for reader in READERS:
        catalogue = list(records(directory / f"first/readers/catalogue-2023-pages-{reader}.jsonl"))
        require(
            len(catalogue) == 102
            and all(
                row["reader"] == reader
                and row["page"] == i
                and row["characters"] == len(row["text"])
                and row["sha256"] == hashlib.sha256(row["text"].encode()).hexdigest()
                for i, row in enumerate(catalogue, 1)
            ),
            "complete authoritative catalogue pages",
        )
        witness = compact(catalogue[40]["text"])
        require(
            all(BOOKS[key]["url"] in witness for key in ("journal-2023-v1", "journal-2023-v2")),
            "catalogue identifies both exact first-session source URLs",
        )
    return pages_by_book


def report_for(originals, views, dispositions, all_candidates):
    accepted = {row["bill_id"] for row in views}
    return {
        "status": "qualified_complete_journal_collection_not_scientific_certification",
        "original_gap_contexts": len(originals),
        "original_NE_gap_contexts": sum(row["state"] == "NE" for row in originals),
        "recovered_original_contexts": len(accepted),
        "complete_reader_views": len(views),
        "complete_policy_characters": sum(len(row["text"]) for row in views),
        "contexts_by_journal": dict(
            Counter(
                next(v["source_record"]["document"] for v in views if v["bill_id"] == key)
                for key in sorted(accepted)
            )
        ),
        "candidate_dispositions": dict(Counter(row["disposition"] for row in dispositions)),
        "source_candidate_dispositions": dict(
            Counter(row["reason"] or "complete_own_resolution_profile" for row in all_candidates)
        ),
        "source_collection_during_qualification": False,
        "original_context_fields_modified": False,
        "model_execution": False,
        "publication": False,
        "scientific_certification": "not_performed",
    }


def build(first_source, first_readers, second_source, second_readers, queue, output):
    paths = tuple(
        Path(p).absolute()
        for p in (first_source, first_readers, second_source, second_readers, queue, output)
    )
    first_source, first_readers, second_source, second_readers, queue, output = paths
    require(
        not output.exists()
        and output.resolve() == output
        and output != ROOT / "data/processed"
        and output.is_relative_to(ROOT / "data/processed"),
        "fresh unlinked output under project data/processed",
    )
    require(
        binding(queue)["sha256"] == QUEUE_SHA and queue.resolve() == queue,
        "externally pinned original missing-context queue",
    )
    bundles = dict(
        zip(INPUTS, (first_source, first_readers, second_source, second_readers), strict=True)
    )
    checked = {
        prefix: input_bundle(directory, INPUTS[prefix]) for prefix, directory in bundles.items()
    }
    output.mkdir(parents=True)
    for prefix, files in checked.items():
        for name, source in files.items():
            target = output / prefix / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    shutil.copy2(queue, output / "input_gap_queue.parquet")
    (output / "producer").mkdir()
    for name in ("ne_journal_collection.py", "ne_journal_text.py"):
        shutil.copy2(Path(__file__).with_name(name), output / "producer" / name)
    originals_table = pq.read_table(output / "input_gap_queue.parquet")
    originals = originals_table.to_pylist()
    pages = source_pages(output)
    views, dispositions, all_candidates = qualify(pages, originals)
    require(
        views and len({row["view_id"] for row in views}) == len(views),
        "nonempty uniquely namespaced complete reader views",
    )
    accepted = {row["bill_id"] for row in views}
    mask = [row["bill_id"] in accepted for row in originals]
    import pyarrow as pa

    pq.write_table(originals_table.filter(pa.array(mask)), output / "context_inventory.parquet")
    for name, values in (
        ("views.jsonl", views),
        ("candidate_dispositions.jsonl", dispositions),
        ("source_resolution_candidates.jsonl", all_candidates),
    ):
        write_rows(output / name, values)
    report = report_for(originals, views, dispositions, all_candidates)
    write_json(output / "report.json", report)
    manifest = {
        "schema": SCHEMA,
        "page_header_profile": LITERAL_HEADERS,
        "source_profiles": BOOKS,
        "fixed_input_manifests": INPUTS,
        "original_gap_queue_sha256": QUEUE_SHA,
        "views": "views.jsonl",
        "contexts": "context_inventory.parquet",
        "report": report,
        "approvals": dict.fromkeys(FLAGS, False),
        "legacy_v1_parser_and_packet_modified": False,
        "packet_artifacts": {
            p.relative_to(output).as_posix(): binding(p)
            for p in sorted(output.rglob("*"))
            if p.is_file()
        },
    }
    write_json(output / "manifest.json", manifest)
    for prefix, files in checked.items():
        for name, source in files.items():
            require(binding(source) == binding(output / prefix / name), "original input changed")
    require(binding(queue)["sha256"] == QUEUE_SHA, "original queue changed")
    return manifest


def load_ne_journal_collection(directory, metadata=None):
    directory = Path(directory).absolute()
    require(directory.resolve() == directory and directory.is_dir(), "unlinked packet root")
    path = directory / "manifest.json"
    manifest = json.loads(path.read_bytes())
    require(
        manifest["schema"] in (SCHEMA, LEGACY_SCHEMA)
        and manifest["source_profiles"] == BOOKS
        and manifest["fixed_input_manifests"] == INPUTS
        and manifest["original_gap_queue_sha256"] == QUEUE_SHA
        and all(manifest["approvals"].get(flag) is False for flag in FLAGS),
        "fixed unapproved source profile",
    )
    header_profile = LITERAL_HEADERS if manifest["schema"] == SCHEMA else LEGACY_HEADERS
    require(
        manifest.get("page_header_profile", LEGACY_HEADERS) == header_profile,
        "source schema and page-header profile agree",
    )
    required = {
        "views.jsonl",
        "context_inventory.parquet",
        "input_gap_queue.parquet",
        "candidate_dispositions.jsonl",
        "source_resolution_candidates.jsonl",
        "report.json",
        "producer/ne_journal_collection.py",
        "producer/ne_journal_text.py",
    }
    require(required <= manifest["packet_artifacts"].keys(), "complete source packet")
    pins = {"manifest.json": binding(path)["sha256"]}
    for name, expected in manifest["packet_artifacts"].items():
        target = directory / name
        require(
            safe_member(name)
            and name != "manifest.json"
            and target.is_file()
            and target.resolve() == target
            and binding(target) == expected,
            "complete unlinked packet artifact",
        )
        pins[name] = expected["sha256"]
    originals = pq.read_table(directory / "input_gap_queue.parquet").to_pylist()
    views, dispositions, all_candidates = qualify(
        source_pages(directory), originals, header_profile=header_profile
    )
    require(
        list(records(directory / "views.jsonl")) == views
        and list(records(directory / "candidate_dispositions.jsonl")) == dispositions
        and list(records(directory / "source_resolution_candidates.jsonl")) == all_candidates,
        "all accepted and rejected source evidence replay",
    )
    report = report_for(originals, views, dispositions, all_candidates)
    require(
        manifest["report"] == report
        and json.loads((directory / "report.json").read_bytes()) == report,
        "exact source accounting",
    )
    accepted = {row["bill_id"] for row in views}
    contexts = pq.read_table(directory / "context_inventory.parquet").to_pylist()
    require(
        contexts == [row for row in originals if row["bill_id"] in accepted],
        "every original context field preserved",
    )
    if metadata is not None:
        current = {row["bill_id"]: row for row in metadata}
        require(
            all(
                row["bill_id"] in current
                and all(
                    row[key] == current[row["bill_id"]][key]
                    for key in ("state", "session_identifier", "identifier")
                )
                for row in contexts
            ),
            "original current candidate identity conflict",
        )
    return views, contexts, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "first-source",
        "first-readers",
        "second-source",
        "second-readers",
        "gap-queue",
        "out-dir",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(
        args.first_source,
        args.first_readers,
        args.second_source,
        args.second_readers,
        args.gap_queue,
        args.out_dir,
    )
    load_ne_journal_collection(args.out_dir)
    print(json.dumps(manifest["report"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

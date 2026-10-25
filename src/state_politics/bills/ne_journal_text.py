"""Qualify complete introduced resolutions in a pinned official Nebraska journal."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA = "state-politics.nebraska-journal-text.v1"
PROVIDER = "Nebraska State Library, official Legislative Journal"
ROOT = Path(__file__).resolve().parents[3]
URL = "https://govdocs.nebraska.gov/epubs/L3300/T001-2024v1.pdf"
PDF_SHA = "f2ce1960af68ece140f3af2d27d25daf1ee1df061e969019ebbfb644d2869a2f"
QUEUE_SHA = "2a3dc1f20aa70912b3f44a616640bb5b75559aa86f5b4f221e6b412ea24f1258"
CAPTURE_SHA = "b85ab00a65d310efbe5c914fc66979f30c34ec002d7ceb73cabb4acee71cc25c"
READERS_SHA = "709bb1eefa406d5cf340a5fe0a9d6bf12cfe167b698011fdf7655e08cd873db9"
READERS = ("pymupdf", "pypdf")
FLAGS = (
    "scientific_approval",
    "model_input_approved",
    "training_admission",
    "training_approved",
    "analytical_admission",
    "publication_approved",
    "party_attribution_approved",
    "filing_time_text_certified",
    "publisher_original_verified",
    "introduced_version_certified",
    "source_rights_approved",
)
MONTHS = {
    name: i
    for i, name in enumerate(
        (
            "JANUARY",
            "FEBRUARY",
            "MARCH",
            "APRIL",
            "MAY",
            "JUNE",
            "JULY",
            "AUGUST",
            "SEPTEMBER",
            "OCTOBER",
            "NOVEMBER",
            "DECEMBER",
        ),
        1,
    )
}
DAILY = re.compile(
    r"\A[A-Z \-]+DAY\s*[-–—]\s*(?P<month>"
    + "|".join(MONTHS)
    + r")\s*(?P<day>\d{1,2}),\s*(?P<year>20\d{2})\s*(?:\n\s*)?\d{1,4}[ \t]*\n"
)
RUNNING = re.compile(r"\ALEGISLATIVE\s*JOURNAL\s*(?:\n\s*)?\d{1,4}[ \t]*\n")
INTRO = re.compile(
    r"(?m)^LEGISLATIVE\s*RESOLUTION\s*(?P<number>\d+)(?P<suffix>CA)?\."
    r"[ \t]*Introduced\s*by[^\n]*\n"
)
END = re.compile(r"(?m)^[ \t]*(?:Laid\s*over\.|Referred\s*to\s*the\s*Executive\s*Board\.)[ \t]*$")
OTHER = re.compile(
    r"(?m)^(?:LEGISLATIVE\s*(?:RESOLUTION|BILL)\s*\d+[A-Z]*\."
    r"|GENERAL FILE[ \t]*$|SELECT FILE[ \t]*$|COMMITTEE REPORTS[ \t]*$)"
)
VENUE = (
    "NOW,THEREFORE,BEITRESOLVEDBYTHEMEMBERSOFTHE"
    "ONEHUNDREDEIGHTHLEGISLATUREOFNEBRASKA,SECONDSESSION:"
)


def require(condition, message):
    if not condition:
        raise ValueError("incompatible Nebraska journal: " + message)


def binding(path):
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"sha256": digest, "bytes": path.stat().st_size}


def compact(text):
    """Whitespace-only comparison key; never used as replacement source text."""
    return re.sub(r"\s+", "", text)


def records(path):
    with path.open() as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def journal_stream(pages):
    chunks, spans, position, current_date = [], [], 0, None
    for expected, page in enumerate(pages, 1):
        text = page["text"]
        require(
            page["page"] == expected
            and page["characters"] == len(text)
            and page["sha256"] == hashlib.sha256(text.encode()).hexdigest(),
            "page identity/text/hash",
        )
        header = DAILY.match(text)
        if header:
            current_date = date(
                int(header["year"]),
                MONTHS[header["month"]],
                int(header["day"]),
            ).isoformat()
        header = header or RUNNING.match(text)
        cut = header.end() if header else 0
        clean = text[cut:]
        chunks.append(clean)
        spans.append(
            {
                "page": expected,
                "start": position,
                "end": position + len(clean),
                "raw_start": cut,
                "date": current_date,
                "row": page,
            }
        )
        position += len(clean) + 1
    return "\n".join(chunks), spans


def resolution_candidates(pages):
    stream, spans = journal_stream(pages)
    candidates = []
    for ordinal, header in enumerate(INTRO.finditer(stream)):
        start = header.start()
        following = OTHER.search(stream, header.end())
        stop = END.search(stream, header.end())
        end = stop.start() if stop else len(stream)
        reason = None
        if not stop or end - start > 60000:
            reason = "no_bounded_complete_resolution_end"
        elif following and following.start() < end:
            reason = "another_legislative_item_before_end"
        elif header["suffix"]:
            reason = "constitutional_amendment_outside_profile"
        text = stream[start:end]
        fragments = []
        dates = set()
        for page in spans:
            left, right = max(start, page["start"]), min(end, page["end"])
            if left >= right:
                continue
            raw_left = page["raw_start"] + left - page["start"]
            raw_right = page["raw_start"] + right - page["start"]
            original = page["row"]["text"][raw_left:raw_right]
            dates.add(page["date"])
            fragments.append(
                {
                    "page": page["page"],
                    "start": raw_left,
                    "end": raw_right,
                    "sha256": hashlib.sha256(original.encode()).hexdigest(),
                }
            )
        if len(dates) != 1 or None in dates:
            reason = reason or "unresolved_or_multiple_journal_dates"
        observed_date = next(iter(dates)) if len(dates) == 1 else None
        if observed_date and not observed_date.startswith("2024-"):
            reason = reason or "outside_2024_journal_date"
        by_page = {page["page"]: page["text"] for page in pages}
        reconstructed = "\n".join(
            by_page[span["page"]][span["start"] : span["end"]] for span in fragments
        )
        if reconstructed != text:
            reason = reason or "unreconstructable_page_boundary"
        normalized = compact(text)
        if VENUE not in normalized:
            reason = reason or "missing_own_108th_second_session_resolving_clause"
        after = normalized.partition(VENUE)[2]
        if (
            not re.search(r"\bWHEREAS,|\bPURPOSE:", text)
            or len(after) < 20
            or not normalized.endswith(".")
        ):
            reason = reason or "missing_substantive_complete_resolution_body"
        candidates.append(
            {
                "ordinal": ordinal,
                "identifier": "LR " + str(int(header["number"])),
                "journal_date": observed_date,
                "reason": reason,
                "text": text,
                "fragments": fragments,
                "terminator": stop[0] if stop else None,
            }
        )
    return candidates


def qualify(pages_by_reader, originals):
    require(set(pages_by_reader) == set(READERS), "both complete PDF readers required")
    indexed = {}
    all_candidates = []
    for reader in READERS:
        candidates = resolution_candidates(pages_by_reader[reader])
        index = defaultdict(list)
        for candidate in candidates:
            index[candidate["identifier"]].append(candidate)
            all_candidates.append({"reader": reader, **candidate})
        indexed[reader] = index
    require(
        len({row["bill_id"] for row in originals}) == len(originals), "duplicate original contexts"
    )
    identities = Counter(
        (row["state"], row["session_identifier"], row["identifier"]) for row in originals
    )
    views, dispositions = [], []
    for row in originals:
        if row["state"] != "NE":
            continue
        reason = None
        if row["session_identifier"] != "108" or not re.fullmatch(r"LR \d+", row["identifier"]):
            reason = "outside_ordinary_108th_resolution_profile"
        elif identities["NE", "108", row["identifier"]] != 1:
            reason = "ambiguous_original_context_identity"
        chosen = {}
        for reader in READERS:
            found = indexed[reader].get(row["identifier"], [])
            matching = [
                c
                for c in found
                if c["reason"] is None and c["journal_date"] == row["source_introduction_date"]
            ]
            if len(matching) != 1:
                reason = reason or (
                    "no_unique_complete_same_date_journal_body"
                    if found
                    else "no_introduced_resolution_in_volume"
                )
            else:
                chosen[reader] = matching[0]
        if len(chosen) == 2 and len({compact(c["text"]) for c in chosen.values()}) != 1:
            reason = reason or "PDF_readers_disagree_on_complete_body"
        dispositions.append(
            {
                "bill_id": row["bill_id"],
                "state": "NE",
                "identifier": row["identifier"],
                "session_identifier": row["session_identifier"],
                "disposition": reason or "complete_two_reader_original_context_match",
            }
        )
        if reason:
            continue
        for reader, candidate in chosen.items():
            text = candidate["text"]
            views.append(
                {
                    "view_id": f"ne-journal:{PDF_SHA}:{reader}:{candidate['ordinal']}",
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
                        "provider": PROVIDER,
                        "url": URL,
                        "reader": reader,
                        "source_PDF_sha256": PDF_SHA,
                        "journal_date": candidate["journal_date"],
                        "resolution_ordinal": candidate["ordinal"],
                        "terminator_not_policy_text": candidate["terminator"],
                        "page_fragments": candidate["fragments"],
                        "page_header_removal_only": True,
                        "fragment_joiner": "\n",
                    },
                    "source_identity": {
                        "state": "NE",
                        "session_identifier": "108",
                        "identifier": row["identifier"],
                        "profile": "own_introduced_header_resolving_clause_exact_original_date",
                    },
                    **dict.fromkeys(FLAGS, False),
                }
            )
    return views, dispositions, all_candidates


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def write_rows(path, rows):
    with path.open("x") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def build(source, readers, queue, output):
    source, readers, queue, output = map(
        lambda p: Path(p).absolute(),
        (source, readers, queue, output),
    )
    require(
        not output.exists()
        and output.resolve() == output
        and output != ROOT / "data/processed"
        and output.is_relative_to(ROOT / "data/processed"),
        "fresh non-symlink output under project data/processed required",
    )
    require(
        binding(source / "manifest.json")["sha256"] == CAPTURE_SHA,
        "externally pinned capture inventory",
    )
    require(
        binding(readers / "manifest.json")["sha256"] == READERS_SHA,
        "externally pinned complete reader inventory",
    )
    source_manifest = json.loads((source / "manifest.json").read_bytes())
    require(
        source_manifest["complete_response"] is True
        and source_manifest["requested_url"] == URL
        and binding(source / "journal-response.body")["sha256"] == PDF_SHA,
        "exact complete original PDF capture",
    )
    require(binding(queue)["sha256"] == QUEUE_SHA, "exact v30 missing-text queue")
    reader_manifest = json.loads((readers / "manifest.json").read_bytes())
    require(
        reader_manifest["source"] == binding(source / "journal-response.body"), "reader/PDF binding"
    )
    pages = {}
    for reader in READERS:
        path = readers / f"pages-{reader}.jsonl"
        expected = reader_manifest["artifacts"][path.name]
        require(
            binding(path) == {key: expected[key] for key in ("sha256", "bytes")},
            "complete reader file binding",
        )
        pages[reader] = list(records(path))
        require(
            len(pages[reader]) == expected["pages"] == 1370, "all original source pages required"
        )
    original_table = pq.read_table(queue)
    originals = original_table.to_pylist()
    require(
        len(originals) == 18281
        and all(row["neither_source_observed"] is True for row in originals),
        "complete unchanged original gap cohort",
    )
    views, dispositions, candidates = qualify(pages, originals)
    require(bool(views), "no complete compatible source bodies")
    output.mkdir(parents=True)
    (output / "source").mkdir()
    (output / "readers").mkdir()
    (output / "producer").mkdir()
    for name in ("manifest.json", "journal-response.body", "capture_producer.py"):
        shutil.copyfile(source / name, output / "source" / name)
    for name in ("manifest.json", *(f"pages-{r}.jsonl" for r in READERS)):
        shutil.copyfile(readers / name, output / "readers" / name)
    shutil.copyfile(queue, output / "input_gap_queue.parquet")
    shutil.copyfile(__file__, output / "producer/ne_journal_text.py")
    write_rows(output / "views.jsonl", views)
    write_rows(output / "source_resolution_candidates.jsonl", candidates)
    write_rows(output / "candidate_dispositions.jsonl", dispositions)
    accepted = {row["bill_id"] for row in views}
    pq.write_table(
        original_table.filter(
            pa.array(
                [row["bill_id"] in accepted for row in originals],
            )
        ),
        output / "context_inventory.parquet",
    )
    report = {
        "original_missing_contexts": len(originals),
        "NE_original_missing_contexts": len(dispositions),
        "recovered_original_contexts": len(accepted),
        "complete_reader_views": len(views),
        "complete_policy_characters": sum(len(row["text"]) for row in views),
        "candidate_dispositions": dict(Counter(row["disposition"] for row in dispositions)),
        "source_candidate_dispositions": dict(
            Counter(row["reason"] or "complete_own_resolution_profile" for row in candidates)
        ),
        "originals_and_source_dates_unchanged": True,
        "full_bills_and_amendment_fragments_not_inferred_from_journal_mentions": True,
        "whole_journal_raw_PDF_and_both_complete_page_readers_retained": True,
        "model_execution": False,
        "publication": False,
    }
    write_json(output / "report.json", report)
    manifest = {
        "schema": SCHEMA,
        "provider": PROVIDER,
        "status": "complete_offline_journal_resolution_evidence_not_scientific_certification",
        "approvals": dict.fromkeys(FLAGS, False),
        "report": report,
        "reader_versions": reader_manifest["versions"],
        "packet_artifacts": {
            path.relative_to(output).as_posix(): binding(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def load_ne_journal(directory, metadata=None):
    directory = Path(directory).absolute()
    require(directory.resolve() == directory and not directory.is_symlink(), "unsafe packet root")
    path = directory / "manifest.json"
    manifest = json.loads(path.read_bytes())
    require(
        manifest["schema"] == SCHEMA and manifest["provider"] == PROVIDER, "journal schema/provider"
    )
    require(
        all(manifest["approvals"].get(flag) is False for flag in FLAGS), "no approval inference"
    )
    artifacts = manifest["packet_artifacts"]
    mandatory = {
        "source/journal-response.body",
        "source/manifest.json",
        "source/capture_producer.py",
        "readers/manifest.json",
        *(f"readers/pages-{reader}.jsonl" for reader in READERS),
        "input_gap_queue.parquet",
        "context_inventory.parquet",
        "views.jsonl",
        "source_resolution_candidates.jsonl",
        "candidate_dispositions.jsonl",
        "report.json",
        "producer/ne_journal_text.py",
    }
    require(mandatory <= artifacts.keys(), "incomplete source packet")
    pins = {"manifest.json": binding(path)["sha256"]}
    for name, expected in artifacts.items():
        target = directory / name
        require(
            not Path(name).is_absolute()
            and ".." not in Path(name).parts
            and "\\" not in name
            and target.is_file()
            and target.resolve() == target,
            "unsafe or missing artifact",
        )
        require(binding(target) == expected, "artifact binding mismatch: " + name)
        pins[name] = expected["sha256"]
    require(
        binding(directory / "source/journal-response.body")["sha256"] == PDF_SHA
        and binding(directory / "source/manifest.json")["sha256"] == CAPTURE_SHA
        and binding(directory / "readers/manifest.json")["sha256"] == READERS_SHA
        and binding(directory / "input_gap_queue.parquet")["sha256"] == QUEUE_SHA,
        "original source/cohort changed",
    )
    reader_manifest = json.loads((directory / "readers/manifest.json").read_bytes())
    for reader in READERS:
        expected = reader_manifest["artifacts"][f"pages-{reader}.jsonl"]
        require(
            binding(directory / f"readers/pages-{reader}.jsonl")
            == {key: expected[key] for key in ("sha256", "bytes")},
            "pinned original reader bytes",
        )
    originals = pq.read_table(directory / "input_gap_queue.parquet").to_pylist()
    pages = {
        reader: list(records(directory / f"readers/pages-{reader}.jsonl")) for reader in READERS
    }
    require(all(len(rows) == 1370 for rows in pages.values()), "missing source pages")
    rows, dispositions, candidates = qualify(pages, originals)
    require(
        list(records(directory / "views.jsonl")) == rows
        and list(records(directory / "candidate_dispositions.jsonl")) == dispositions
        and list(records(directory / "source_resolution_candidates.jsonl")) == candidates,
        "complete deterministic source replay",
    )
    accepted = {row["bill_id"] for row in rows}
    report = json.loads((directory / "report.json").read_bytes())
    require(
        report == manifest["report"]
        and report["recovered_original_contexts"] == len(accepted)
        and report["complete_reader_views"] == len(rows)
        and report["complete_policy_characters"] == sum(len(row["text"]) for row in rows)
        and report["candidate_dispositions"]
        == dict(Counter(row["disposition"] for row in dispositions))
        and report["source_candidate_dispositions"]
        == dict(Counter(row["reason"] or "complete_own_resolution_profile" for row in candidates))
        and report["model_execution"] is False
        and report["publication"] is False,
        "report/replayed source counts changed",
    )
    contexts = pq.read_table(directory / "context_inventory.parquet").to_pylist()
    require(
        contexts == [row for row in originals if row["bill_id"] in accepted],
        "original context fields changed",
    )
    if metadata is not None:
        current = {row["bill_id"]: row for row in metadata}
        require(
            all(
                row["bill_id"] in current
                and all(
                    row[key] == current[row["bill_id"]][key]
                    for key in ("state", "identifier", "session_identifier")
                )
                for row in contexts
            ),
            "current candidate identity conflict",
        )
    return rows, contexts, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--readers", type=Path, required=True)
    parser.add_argument("--gap-queue", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(args.source, args.readers, args.gap_queue, args.out_dir)
    load_ne_journal(args.out_dir)
    print(json.dumps(manifest["report"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

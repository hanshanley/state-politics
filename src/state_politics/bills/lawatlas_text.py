"""Build and verify the bounded LawAtlas PDF archive evidence, entirely offline."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import shutil
import stat
from collections import Counter
from pathlib import Path, PurePosixPath

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pypdf

SCHEMA = "state-politics.lawatlas-archive-text.v1"
PROVIDER = "LawAtlas/MonQcle"
STATUS = "independent_pdf_archive_not_publisher_certified"
FLAGS = (
    "scientific_approval", "model_input_approved", "training_approved",
    "publication_approved", "party_attribution_approved", "filing_time_text_certified",
    "analytical_admission", "publisher_original_verified",
)
SOURCE_MANIFEST_SHA256 = "70b84d17ab46ee2bedf053492d9357cab1b4fdd9f0fc6ec406faca003596bdc9"
GAP_SHA256 = "32a6f62e57cdf1d936cc7e90e70bcbf6d26c81e9669a11d6b6cae3f0e2189ab1"
# The installed project extractor must reproduce the original 6.16.0 output byte for byte.
PINNED_PYPDF = "6.14.2"
SELECTION = (
    ("nj_s3841", "649603499cd360c7678b4572"),
    ("nj_a5445", "649608679cd36048688b45e0"),
    ("ne_lb202", "649b00a59cd360166a8b4571"),
    ("ok_hb2170", "64ac29d09cd36030178b461c"),
    ("ok_hb3249", "67c091f09cd360d5558b4567"),
    ("nj_a1899", "678089319cd3604c778b4591"),
)


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible LawAtlas archive: {message}")


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _binding(path):
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return {"sha256": hasher.hexdigest(), "bytes": path.stat().st_size}


def _regular(path):
    require(not path.is_symlink(), f"linked source/manifest: {path.name}")
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError(f"incompatible LawAtlas archive: missing artifact: {path}") from exc
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and path.resolve() == path, f"unsafe or linked artifact: {path.name}")
    return path


def _root(directory):
    directory = Path(directory).absolute()
    require(not directory.is_symlink() and directory.resolve() == directory
            and directory.is_dir(), "unsafe or linked packet directory")
    return directory


def _relative(name):
    require(isinstance(name, str) and bool(name) and "\\" not in name
            and ":" not in name and "\0" not in name, "unsafe artifact path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts
            and path.as_posix() == name and name != ".", "unsafe artifact path")
    return name


def _json(path):
    def distinct(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON object key")
            result[key] = value
        return result

    return json.loads(path.read_bytes(), object_pairs_hook=distinct)


def _jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def _write_rows(path, rows):
    path.write_text("".join(json.dumps(
        row, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    ) + "\n" for row in rows))


def _source_inventory(source):
    source = _root(source)
    manifest = _regular(source / "sha256_manifest.jsonl")
    require(_binding(manifest)["sha256"] == SOURCE_MANIFEST_SHA256,
            "immutable original source manifest mismatch")
    inventory = {}
    for row in _jsonl(manifest):
        name = _relative(row["path"])
        require(name not in inventory, "duplicate original source artifact")
        binding = {key: row[key] for key in ("sha256", "bytes")}
        require(_binding(_regular(source / name)) == binding,
                f"immutable original source artifact mismatch: {name}")
        inventory[name] = binding
    require(len(inventory) == 99, "incomplete original source inventory")
    inventory["sha256_manifest.jsonl"] = _binding(manifest)
    return inventory


def _one(pattern, text, field):
    matches = list(re.finditer(pattern, text, re.I | re.M))
    require(len(matches) == 1, f"ambiguous or absent printed {field}")
    match = matches[0]
    return match, {"field": field, "start": match.start(), "end": match.end(),
                   "literal": match[0]}


def _bill(identifier):
    match = re.fullmatch(r"([A-Z]+)\s*([0-9]+)([A-Z]*)", identifier.strip(), re.I)
    require(match is not None, "nonliteral bill identifier")
    return f"{match[1].upper()} {int(match[2])}{match[3].upper()}"


def _key(row):
    return row["state"].upper(), str(row["session_identifier"]), _bill(row["identifier"])


def printed_identity(first_page):
    """Parse only the own printed first-page state, session and bill headers."""
    states = [(state, pattern) for state, pattern in (
        ("NJ", r"^\s*STATE\s+OF\s+NEW\s+JERSEY"),
        ("NE", r"^\s*LEGISLATURE\s+OF\s+NEBRASKA"),
        ("OK", r"^\s*STATE\s+OF\s+OKLAHOMA\b"),
    ) if re.search(pattern, first_page, re.I | re.M)]
    require(len(states) == 1, "ambiguous or absent printed state")
    state, pattern = states[0]
    _, venue = _one(pattern, first_page, "state")
    if state == "NJ":
        session, assembly = _one(
            r"(?<![0-9])(220|221)(?:st|nd|rd|th)\s+LEGISLATURE\b", first_page, "session",
        )
        bill, measure = _one(
            r"^\s*(SENATE|ASSEMBLY),\s*No\.\s*([0-9]+)\b", first_page, "bill",
        )
        session_id = session[1]
        identifier = ("S" if bill[1].upper() == "SENATE" else "A") + " " + bill[2]
    elif state == "NE":
        _, assembly = _one(
            r"\bONE\s+HUNDRED\s+EIGHTH\s+LEGISLATURE\b", first_page, "session",
        )
        bill, measure = _one(r"^\s*LEGISLATIVE\s+BILL\s+([0-9]+)\b", first_page, "bill")
        session_id, identifier = "108", "LB " + bill[1]
    else:
        session, assembly = _one(
            r"\b(1st|2nd)\s+Session\s+of\s+the\s+59th\s+Legislature\s*\((2023|2024)\)",
            first_page, "session",
        )
        require((session[1].lower(), session[2]) in {("1st", "2023"), ("2nd", "2024")},
                "contradictory printed Oklahoma session")
        bill, measure = _one(r"^\s*(HOUSE|SENATE)\s+BILL\s+([0-9]+)\b", first_page, "bill")
        session_id = session[2]
        identifier = ("HB" if bill[1].upper() == "HOUSE" else "SB") + " " + bill[2]
    return {"state": state, "session_identifier": session_id, "identifier": _bill(identifier),
            "spans": [venue, assembly, measure]}


class _Warnings(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def emit(self, record):
        self.rows.append({"level": record.levelname, "logger": record.name,
                          "message": record.getMessage()})


def _extract(path):
    require(pypdf.__version__ == PINNED_PYPDF, "pinned installed PDF extractor required")
    handler = _Warnings()
    logger = logging.getLogger("pypdf")
    logger.addHandler(handler)
    try:
        reader = pypdf.PdfReader(io.BytesIO(path.read_bytes()))
        pages = [page.extract_text() or "" for page in reader.pages]
    finally:
        logger.removeHandler(handler)
    require(bool(pages) and all(page.strip() for page in pages), "incomplete PDF extraction")
    return pages, handler.rows


def _replay(source, gap_table):
    require(_binding(source.parent / "input_gap_queue.parquet")["sha256"] == GAP_SHA256,
            "original complete gap queue hash")
    gaps = gap_table.to_pylist()
    by_id = {row["bill_id"]: row for row in gaps}
    require(len(by_id) == len(gaps) and all(
        row["neither_source_observed"] is True for row in gaps
    ), "original gap context universe")
    owned = gap_table.filter(pc.is_in(
        gap_table["state"], value_set=pa.array(["NJ", "OK", "NE"]),
    ))
    require(owned.equals(pq.read_table(source / "recovery-v2/exact_candidates.parquet"),
                         check_metadata=True), "original owned gap contexts changed")
    by_identity = {}
    for row in owned.to_pylist():
        key = _key(row)
        require(key not in by_identity, "ambiguous original context identity")
        by_identity[key] = row
    ledger = _jsonl(source / "http_exchanges.jsonl")

    def response(label):
        matches = [row for row in ledger if row["label"] == label
                   and row.get("status") == 200 and row.get("raw_path")]
        require(len(matches) == 1, "complete original response required")
        row = matches[0]
        path = _regular(source / _relative(row["raw_path"]))
        require(_binding(path) == {key: row[key] for key in ("sha256", "bytes")},
                "raw HTTP response binding mismatch")
        return row, path

    landing, path = response("lawatlas_complete_landing")
    html = path.read_text()
    match = re.search(r"var full_preview\s*=\s*", html)
    require(match is not None, "public preloaded snapshot missing")
    preview, _ = json.JSONDecoder().raw_decode(html[match.end():])
    snapshot = preview["snapshot"]["mappable_data"]
    require(preview["is_published"] is True and len(snapshot) == 675,
            "original public snapshot")
    require(_jsonl(source / "recovery-v2/all_source_records.jsonl") == [
        {"source_row_ordinal": index, "source_record": record}
        for index, record in enumerate(snapshot, 1)
    ], "complete original source records changed")
    original_views = pq.read_table(source / "recovery-v2/fullbody_views.parquet").to_pylist()
    originals = {row["source_law_id"]: row for row in original_views}
    matched = {row["law_record"]["id"]: row for row in
               _jsonl(source / "recovery-v2/matched_records.jsonl")}
    all_laws, pages_inventory, warning_inventory, rows = [], [], [], []
    selected = {}
    source_flags = (
        *FLAGS[:-1], "publisher_original_certified", "human_gold", "introduced_version_certified",
    )
    for label, law_id in SELECTION:
        metadata_response, metadata_path = response(label + "_law_metadata")
        pdf_response, pdf_path = response(label + "_attached_pdf")
        law = _json(metadata_path)
        all_laws.append({"source_record_ordinal": len(all_laws) + 1, "label": label,
                         "law_record": law, "source_raw_path": metadata_response["raw_path"]})
        require(law["id"] == law_id and pdf_response["url"] ==
                f"https://monqcle.com/upload/{law['attachment']}/download",
                "actual law/attachment foreign key changed")
        ordinals = [i for i, record in enumerate(snapshot, 1) if law_id in record.get("laws", [])]
        require(bool(ordinals), "law without original snapshot references")
        pages, warnings = _extract(pdf_path)
        warning_inventory.extend({"label": label, **warning} for warning in warnings)
        text = "\n".join(pages)
        text_path = source / f"recovery-v2/{label}_complete_pdf_text.txt"
        require(text_path.read_text() == text, "proven complete PDF extraction changed")
        pages_inventory.extend({
            "label": label, "page_ordinal": index, "text": page,
            "text_sha256": _sha(page.encode()), "n_characters": len(page),
        } for index, page in enumerate(pages, 1))
        identity = printed_identity(pages[0])
        context = by_identity.get(_key(identity))
        if context is None:
            require(law_id not in originals and law_id not in matched,
                    "rejected identity promoted")
            selected[law_id] = {
                "disposition": "rejected_exact_identity",
                "error": "Exact candidate key must select precisely one retained context",
            }
            continue
        require(law_id in originals and law_id in matched, "unproven new context admission")
        original, record = originals[law_id], matched[law_id]
        require(record["candidate"] == context and record["law_record"] == law
                and record["identity"] == identity and record["source_row_ordinals"] == ordinals,
                "complete original record/context/identity binding changed")
        require(original["text"] == text and original["text_sha256"] == _sha(text.encode())
                and original["n_characters"] == len(text) and original["n_pages"] == len(pages)
                and json.loads(original["source_identity_spans_json"]) == identity["spans"]
                and original["bill_id"] == context["bill_id"]
                and _key(original) == _key(identity)
                and original["source_record_ordinals"] == ordinals
                and all(original[flag] is False for flag in source_flags),
                "original PDF text/identity/context or approval changed")
        require(all(snapshot[i - 1]["state_code"] == identity["state"] for i in ordinals),
                "snapshot state/identity binding")

        def member(relative):
            return {"path": f"source-evidence/{relative}", **_binding(source / relative)}

        source_record = {
            "law_metadata": law, "original_recovery_record": record,
            "snapshot_records": [{"source_row_ordinal": i, "record": snapshot[i - 1]}
                                 for i in ordinals],
        }
        view = {
            "view_id": original["view_id"], "source_type": "archive_text",
            "bill_id": context["bill_id"], "state": context["state"],
            "identifier": context["identifier"],
            "session_identifier": context["session_identifier"], "title": context["title"],
            "text": text, "raw_text_characters": len(text),
            "raw_text_sha256": _sha(text.encode()), "source_record": source_record,
            "source_identity": {
                key: identity[key] for key in ("state", "session_identifier", "identifier")
            } | {"printed_evidence": [
                {"start": span["start"], "end": span["end"], "text": span["literal"]}
                for span in identity["spans"]
            ]},
            "source_version": {"law_metadata": law, "original_recovery_view": original,
                               "attachment_id": law["attachment"],
                               "attachment_name": law["attachment_name"],
                               "attachment_url": pdf_response["url"],
                               "introduced_version_certified": False},
            "source_members": {
                "pdf": member(pdf_response["raw_path"]),
                "metadata": member(metadata_response["raw_path"]),
                "extraction": member(text_path.relative_to(source).as_posix()),
                "snapshot": member(landing["raw_path"]),
                "matched_records": member("recovery-v2/matched_records.jsonl"),
                "dispositions": member("recovery-v2/all_source_row_dispositions.jsonl"),
                "http_ledger": member("http_exchanges.jsonl"),
            },
            "source_row_ordinals": ordinals, "archive_provider": PROVIDER,
            "archive_generated_prologue_preserved": False, "source_status": STATUS,
            "source_date_or_party_inferred": False, "training_admission": False,
            **dict.fromkeys(FLAGS, False),
        }
        rows.append(view)
        selected[law_id] = {
            "disposition": "exact_existing_candidate_attachment_recovered",
            "bill_id": context["bill_id"], "view_id": view["view_id"],
        }
    require(all_laws == _jsonl(source / "recovery-v2/all_downloaded_law_records.jsonl")
            and pages_inventory == _jsonl(source / "recovery-v2/pdf_pages.jsonl")
            and warning_inventory == _jsonl(source / "recovery-v2/pdf_extraction_warnings.jsonl"),
            "complete law records/PDF pages or extraction warnings changed")
    dispositions = []
    for index, record in enumerate(snapshot, 1):
        item = {"source_row_ordinal": index, "source_record_id": record.get("id"),
                "state_code": record.get("state_code"), "law_ids": record.get("laws", [])}
        if record.get("state_code") not in {"NJ", "OK", "NE"}:
            item["disposition"] = "outside_owned_target_states"
        elif not record.get("laws"):
            item["disposition"] = "no_attached_law_foreign_key"
        else:
            linked = [selected[law] for law in record["laws"] if law in selected]
            item["disposition"] = ("linked_selected_law_record" if linked
                                   else "not_requested_bounded_selection")
            item["selected_law_dispositions"] = linked
        dispositions.append(item)
    require(dispositions == _jsonl(source / "recovery-v2/all_source_row_dispositions.jsonl"),
            "all 675 original row dispositions changed")
    require(len(rows) == len(originals) == len(matched) == 4
            and len({row["bill_id"] for row in rows}) == 4, "four original contexts required")
    accepted = {row["bill_id"] for row in rows}
    contexts = gap_table.filter(pa.array([row["bill_id"] in accepted for row in gaps]))
    counts = {
        "text_views": len(rows), "newly_covered_contexts": len(accepted),
        "original_gap_contexts": len(gaps), "original_owned_gap_contexts": owned.num_rows,
        "source_snapshot_records": len(snapshot), "downloaded_pdf_attachments": len(SELECTION),
        "rejected_pdf_attachments": len(SELECTION) - len(rows),
        "all_pdf_pages": len(pages_inventory),
        "text_views_by_state": dict(Counter(row["state"] for row in rows)),
    }
    report = {
        "counts": counts, "approvals": dict.fromkeys(FLAGS, False),
        "tools": {"pypdf": PINNED_PYPDF, "original_pypdf": "6.16.0",
                  "complete_original_extraction_replay_equal": True},
        "source_license_and_integrity_findings": _json(source / "source_findings.json"),
        "initial_partial_size_abort_caveat":
            _json(source / "recovery-v2/verification.json")["initial_lawatlas_error"],
        "source_http_exchanges": len(ledger), "source_campaign_remains_closed": True,
        "count_scope": "original supplied v9 gap queue; overlapping archive views not deduplicated",
        "source_row_dispositions": dict(Counter(row["disposition"] for row in dispositions)),
    }
    return rows, contexts, report


def build_lawatlas(source_directory: Path, gap_queue: Path, out_directory: Path):
    """Copy the complete immutable source and build four lossless normalized PDF views."""
    source = _root(source_directory)
    gap_queue = _regular(Path(gap_queue).absolute())
    out = Path(out_directory).absolute()
    require(not out.exists() and not out.is_symlink() and out.resolve() == out,
            "new unlinked output directory required")
    before = _source_inventory(source)
    require(_binding(gap_queue)["sha256"] == GAP_SHA256, "original complete gap queue required")
    out.mkdir(parents=True)
    evidence = out / "source-evidence"
    evidence.mkdir()
    for name in before:
        target = evidence / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    shutil.copy2(gap_queue, out / "input_gap_queue.parquet")
    require(_source_inventory(evidence) == before, "source copy was not lossless")
    rows, contexts, report = _replay(evidence, pq.read_table(out / "input_gap_queue.parquet"))
    _write_rows(out / "views.jsonl", rows)
    pq.write_table(contexts, out / "context_inventory.parquet")
    _write(out / "report.json", report)
    (out / "producer").mkdir()
    shutil.copy2(Path(__file__), out / "producer/lawatlas_text.py")
    artifact_names = (
        [f"source-evidence/{name}" for name in before]
        + ["input_gap_queue.parquet", "views.jsonl", "context_inventory.parquet",
           "report.json", "producer/lawatlas_text.py"]
    )
    manifest = {
        "schema": SCHEMA, "provider": PROVIDER, "status": STATUS,
        "approvals": dict.fromkeys(FLAGS, False), "counts": report["counts"],
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "source_original_artifacts": 99, "source_files_copied_including_manifest": len(before),
        "gap_queue_sha256": GAP_SHA256, "tools": report["tools"],
        "packet_artifacts": {name: _binding(out / name) for name in sorted(artifact_names)},
    }
    _write(out / "manifest.json", manifest)
    require(_source_inventory(source) == before, "immutable original source changed")
    load_lawatlas(out)
    return manifest


def load_lawatlas(directory: Path, metadata=None):
    """Verify every retained source, replay every PDF, and return rows, contexts, pins, manifest."""
    directory = _root(directory)
    manifest_path = _regular(directory / "manifest.json")
    manifest = _json(manifest_path)
    require(manifest.get("schema") == SCHEMA and manifest.get("provider") == PROVIDER
            and manifest.get("status") == STATUS, "schema/provider/status mismatch")
    require(set(manifest.get("approvals", {})) == set(FLAGS)
            and all(manifest["approvals"][flag] is False for flag in FLAGS),
            "source approval promotion")
    require(manifest.get("source_manifest_sha256") == SOURCE_MANIFEST_SHA256
            and manifest.get("gap_queue_sha256") == GAP_SHA256,
            "original input trust anchors")
    artifacts = manifest["packet_artifacts"]
    for name in artifacts:
        _relative(name)
    pins = {"manifest.json": _binding(manifest_path)["sha256"]}
    for name, binding in artifacts.items():
        require(_binding(_regular(directory / name)) == binding,
                f"packet artifact binding mismatch: {name}")
        pins[name] = binding["sha256"]
    source = directory / "source-evidence"
    original = _source_inventory(source)
    expected = {f"source-evidence/{name}" for name in original} | {
        "input_gap_queue.parquet", "views.jsonl", "context_inventory.parquet",
        "report.json", "producer/lawatlas_text.py",
    }
    require(set(artifacts) == expected, "incomplete or unexpected packet artifacts")
    require(_binding(directory / "producer/lawatlas_text.py") == _binding(Path(__file__)),
            "producer module mismatch")
    gap = pq.read_table(directory / "input_gap_queue.parquet")
    replay, expected_contexts, report = _replay(source, gap)
    rows = _jsonl(directory / "views.jsonl")
    require(rows == replay, "complete record/text/identity/approval replay mismatch")
    contexts = pq.read_table(directory / "context_inventory.parquet")
    require(contexts.equals(expected_contexts, check_metadata=True),
            "unchanged original context inventory mismatch")
    require(_json(directory / "report.json") == report
            and manifest["counts"] == report["counts"] and manifest["tools"] == report["tools"]
            and manifest["source_original_artifacts"] == 99
            and manifest["source_files_copied_including_manifest"] == 100,
            "complete report/counts/tools mismatch")
    context_rows = contexts.to_pylist()
    if metadata is not None:
        current = list(metadata)
        for context in context_rows:
            matches = [row for row in current if row["bill_id"] == context["bill_id"]]
            require(len(matches) == 1 and all(
                matches[0][key] == context[key]
                for key in ("state", "identifier", "session_identifier")
            ), "current candidate identity mismatch or duplicate")
    return rows, context_rows, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--source-dir", type=Path, required=True)
    build.add_argument("--gap-queue", type=Path, required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_lawatlas(args.source_dir, args.gap_queue, args.out_dir)
    else:
        _, _, _, manifest = load_lawatlas(args.directory)
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

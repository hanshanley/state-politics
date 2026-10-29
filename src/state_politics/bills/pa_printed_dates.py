"""Replay labelled Pennsylvania introduction-date observations without cohort admission."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import re
import warnings
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pymupdf
import pypdf
import yaml

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "state-politics.pa-printed-introduction-observations.v1"
STATUS = "complete_source_date_observations_not_cohort_or_filing_time_certification"
QUALIFIED = "concordant_source_reported_introduction_date"
FLAGS = (
    "date_admission", "cohort_change", "filing_time_text_certified", "analytical_admission",
    "model_input_approved", "training_admission", "publication", "scientific_approval",
    "native_identity_certified", "independent_human_validation", "human_gold_approved",
    "model_execution", "model_promotion", "rights_approved", "party_attribution_approved",
)
TOOLS = {"pymupdf": "1.28.0", "pypdf": "6.14.2"}
MONTHS = dict(zip(
    ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
     "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"],
    range(1, 13), strict=True,
))
DATE = re.compile(r"\b(" + "|".join(MONTHS) + r") ([0-9]{1,2}), ([0-9]{4})\b")
EVENT = re.compile(
    r"\b(?:INTRODUCED BY\b|INTRODUCED AND ADOPTED\s*,|INTRODUCED\s*,|"
    r"REFERRED TO\b|REPORTED FROM\b|AS AMENDED\b|ADOPTED\s*,)"
)
BODY = re.compile(r"\b(?:AN ACT|A JOINT RESOLUTION|A CONCURRENT RESOLUTION|A RESOLUTION)\b")
PREFIX = {
    ("HOUSE", "BILL"): "HB", ("SENATE", "BILL"): "SB",
    ("HOUSE", "RESOLUTION"): "HR", ("SENATE", "RESOLUTION"): "SR",
}


def _require(condition, message):
    if not condition:
        raise ValueError(f"incompatible PA printed-date evidence: {message}")


def observe_header(text, identifier, session_identifier="2023-2024"):
    """Keep exact raw spans; introduction confirmations must agree, never supply a fallback."""
    _require(type(text) is str and bool(text), "nonempty first-page text required")
    _require(type(identifier) is str, "typed identifier string required")
    expected = re.fullmatch(r"(HB|SB|HR|SR) ?([1-9][0-9]*)", identifier)
    _require(expected is not None and session_identifier == "2023-2024",
             "explicit typed identity and supported canonical session required")
    words = list(re.finditer(r"\S+", text))
    normalized = " ".join(word.group() for word in words)
    positions = []
    for word in words:
        if positions:
            positions.append(None)
        positions.extend(range(word.start(), word.end()))

    def span(start, end):
        bounds = [positions[start], positions[end - 1] + 1]
        return {"span": bounds, "text": text[bounds[0]:bounds[1]]}

    own = list(re.finditer(
        r"THE GENERAL ASSEMBLY OF PENNSYLVANIA\s+(HOUSE|SENATE)\s+"
        r"(BILL|RESOLUTION)\s+No\.\s*([0-9]+)\s+Session of\s+(20[0-9]{2})\b",
        normalized,
    ))
    _require(len(own) == 1, "unique own printed state/type/number/session required")
    own = own[0]
    typed = PREFIX[own.group(1, 2)] + str(int(own.group(3)))
    _require(typed == expected.group(1) + expected.group(2)
             and own.group(4) in {"2023", "2024"}, "printed identity/session mismatch")
    body = BODY.search(normalized, own.end())
    _require(body is not None, "bounded printed header/body boundary required")
    events = list(EVENT.finditer(normalized, own.end(), body.start()))
    primary = [event for event in events if event.group() == "INTRODUCED BY"]
    _require(len(primary) == 1, "unique introduced-by field required")
    witnesses = []
    for index, event in enumerate(events):
        label = event.group()
        if not label.startswith("INTRODUCED"):
            continue
        end = events[index + 1].start() if index + 1 < len(events) else body.start()
        matches = list(DATE.finditer(normalized, event.end(), end))
        _require(len(matches) == 1, "one explicit date per labelled introduction field required")
        match = matches[0]
        try:
            observed = date(int(match[3]), MONTHS[match[1]], int(match[2])).isoformat()
        except ValueError as exc:
            raise ValueError("incompatible PA printed-date evidence: invalid printed date") from exc
        witnesses.append({
            "event": label, "date": observed,
            "event_label": span(event.start(), event.end()),
            "date_literal": span(match.start(), match.end()),
        })
    _require(witnesses and len({row["date"] for row in witnesses}) == 1,
             "conflicting printed introduction dates")
    version_notes = [
        span(match.start(), match.end())
        for match in re.finditer(r"\b(?:AS AMENDED|CORRECTED COPY|REPRINT(?:ED)?)\b", normalized)
        if match.start() < body.start()
    ]
    return {
        "printed_identifier": typed, "printed_session_year": own.group(4),
        "identity_literal": span(own.start(), own.end()),
        "date": witnesses[0]["date"], "labelled_date_witnesses": witnesses,
        "version_notes": version_notes, **dict.fromkeys(FLAGS, False),
    }


def binding(path):
    def fingerprint():
        value = path.stat()
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                value.st_ctime_ns, value.st_mode, value.st_nlink)
    before = fingerprint()
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    _require(fingerprint() == before, f"source changed while hashing: {path}")
    return {"sha256": digest, "bytes": before[2]}


def _file(path, root):
    path = Path(path).absolute()
    _require(path.resolve() == path and path.is_file()
             and path.is_relative_to(root / "data"),
             "unlinked input file under project data required")
    return path


def _pages(data):
    _require({"pymupdf": pymupdf.__version__, "pypdf": pypdf.__version__} == TOOLS,
             "locked PDF-reader versions required")
    pymupdf.TOOLS.mupdf_warnings(reset=True)
    with warnings.catch_warnings(record=True) as fitz_warnings:
        warnings.simplefilter("always")
        with pymupdf.open(stream=data, filetype="pdf") as document:
            _require(len(document) > 0, "source PDF has no pages")
            fitz_text = document[0].get_text("text", sort=False)
    fitz_log = pymupdf.TOOLS.mupdf_warnings(reset=True)
    messages = io.StringIO()
    handler = logging.StreamHandler(messages)
    logger = logging.getLogger("pypdf")
    logger.addHandler(handler)
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            reader = pypdf.PdfReader(io.BytesIO(data), strict=True)
            plain = reader.pages[0].extract_text(extraction_mode="plain")
    finally:
        logger.removeHandler(handler)
    return {
        "pymupdf": {"text": fitz_text, "warnings": [str(row.message) for row in fitz_warnings],
                    "log": fitz_log},
        "pypdf": {"text": plain, "warnings": [str(row.message) for row in captured],
                  "log": messages.getvalue()},
    }


def _replay(assessment, assessment_sha256, root):
    inputs = {}

    def checked(path, expected=None):
        path = _file(path, root)
        actual = binding(path)
        if expected is not None:
            _require(actual == expected, f"source binding changed: {path}")
        name = str(path.relative_to(root))
        _require(inputs.get(name, actual) == actual, "input changed between source views")
        inputs[name] = actual
        return path

    assessment = checked(assessment)
    _require(binding(assessment)["sha256"] == assessment_sha256, "assessment manifest hash changed")
    manifest = json.loads(assessment.read_bytes())
    _require(manifest["status"] == (
        "complete_bounded_source_date_assessment_not_qualified_cohort_extension"
    )
             and all(manifest[key] is False for key in ("date_admission", "cohort_change",
                                                       "model_execution", "publication")),
             "unadmitted assessment required")
    _require({"probe.json", "join-incidence-v2.json"} <= set(manifest["artifacts"]),
             "assessment source-index and canonical-join bindings required")
    for name, expected in manifest["artifacts"].items():
        _require(Path(name).name == name, "assessment artifact must be a direct child")
        checked(assessment.parent / name, expected)
    probe = json.loads((assessment.parent / "probe.json").read_bytes())
    previous_join = json.loads((assessment.parent / "join-incidence-v2.json").read_bytes())
    view_path = checked(root / probe["source"])
    _require(binding(view_path)["sha256"] == probe["sha256"], "retained view index changed")
    join_path = checked(root / previous_join["shared_join"], previous_join["binding"])
    views = pq.read_table(view_path, columns=[
        "view_id", "context_id", "state", "identifier", "reader", "input_sha256",
        "original_source_path", "original_source_sha256", "negative_flags_json",
    ]).to_pylist()
    _require(len({row["view_id"] for row in views}) == len(views), "duplicate source view identity")
    joined = defaultdict(list)
    for row in pq.read_table(join_path, columns=[
        "context_id", "bill_id", "identifier", "session_identifier",
        "state", "state_native", "source_introduction_date", "canonical_join_basis",
    ]).to_pylist():
        if row["state"] == "PA" or row["state_native"] == "PA":
            joined[row["context_id"]].append(row)
    pdfs, witnesses, dispositions, groups = {}, [], [], defaultdict(list)
    for view in views:
        disposition = {
            "view_id": view["view_id"], "context_id": view["context_id"],
            "reader": view["reader"], "original_input_sha256": view["input_sha256"],
            "original_negative_flags_json": view["negative_flags_json"],
            **dict.fromkeys(FLAGS, False),
        }
        if view["reader"] not in {"pdf_stored_reader", "parent_pdf_stored_reader"}:
            dispositions.append(disposition | {"status": "not_a_selected_pdf_date_source"})
            continue
        _require(view["state"] == "PA", "foreign state in PA source index")
        candidates = joined[view["context_id"]]
        _require(len(candidates) == 1 and candidates[0]["bill_id"] is not None,
                 "unique existing canonical context join required")
        canonical = candidates[0]
        _require(canonical["canonical_join_basis"] == "unique_declared_session_typed_identity"
                 and canonical["identifier"] == view["identifier"]
                 and canonical["session_identifier"] == "2023-2024",
                 "original session/typed-identity join changed")
        path = checked(view["original_source_path"])
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        _require(digest == view["original_source_sha256"], "raw PDF source hash mismatch")
        if digest not in pdfs:
            pdfs[digest] = _pages(data)
            witnesses.append({"pdf_sha256": digest, "complete_first_pages": pdfs[digest]})
        observed = {}
        for reader, page in pdfs[digest].items():
            try:
                observed[reader] = observe_header(page["text"], view["identifier"])
            except ValueError as exc:
                observed[reader] = {"unresolved": str(exc)}
        dates = [row.get("date") for row in observed.values()]
        valid = all(dates) and len(set(dates)) == 1
        result = disposition | {
            "status": QUALIFIED if valid else "unresolved_reader_or_header_observation",
            "source": str(path.relative_to(root)), "pdf_sha256": digest,
            "reader_observations": observed, "observed_date": dates[0] if valid else None,
        }
        dispositions.append(result)
        groups[view["context_id"]].append((result, canonical))
    _require(bool(groups), "no selected PDF date sources")
    observations = []
    for context_id, group in sorted(groups.items()):
        dates = {row["observed_date"] for row, _ in group}
        valid = None not in dates and len(dates) == 1
        canonical = group[0][1]
        _require(len({row["bill_id"] for _, row in group}) == 1, "canonical bill conflict")
        observations.append({
            "observation_id": f"pa-printed-introduction:{context_id}",
            "context_id": context_id, "source_context_id": context_id,
            "state": "PA", "bill_id": canonical["bill_id"],
            "identifier": canonical["identifier"], "session_identifier": "2023-2024",
            "source_introduction_date_unchanged": canonical["source_introduction_date"],
            "printed_introduction_date": next(iter(dates)) if valid else None,
            "observation_status": QUALIFIED if valid else "unresolved_source_date_observation",
            "source_view_ids_json": json.dumps([row["view_id"] for row, _ in group]),
            "source_pdf_hashes_json": json.dumps(sorted({row["pdf_sha256"] for row, _ in group})),
            "negative_flags_json": json.dumps([
                json.loads(row["original_negative_flags_json"]) for row, _ in group
            ]),
            **dict.fromkeys(FLAGS, False),
        })
    for name, expected in inputs.items():
        _require(binding(root / name) == expected, f"input changed during replay: {name}")
    report = {
        "source_views": len(views), "pdf_source_views": sum(len(g) for g in groups.values()),
        "unique_pdfs": len(pdfs), "canonical_contexts": len(observations),
        "qualified_contexts": sum(row["observation_status"] == QUALIFIED for row in observations),
        "view_dispositions": dict(Counter(row["status"] for row in dispositions)),
        **dict.fromkeys(FLAGS, False),
    }
    return observations, witnesses, dispositions, report, inputs


def _json(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def _csv(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def build(assessment, assessment_sha256, out, *, root=ROOT):
    root, out = Path(root).resolve(), Path(out).absolute()
    _require(out.resolve() == out and out.parent in {root / "data", root / "data/processed"},
             "new direct child of project data or data/processed required")
    _require(not out.exists(), "refusing existing output")
    rows, witnesses, dispositions, report, inputs = _replay(
        assessment, assessment_sha256, root,
    )
    out.mkdir(parents=True, exist_ok=False)
    pq.write_table(pa.Table.from_pylist(rows), out / "observations.parquet")
    with (out / "observations.csv").open("x", newline="", encoding="utf-8") as handle:
        handle.write(_csv(rows))
    for name, values in (("reader_witnesses.jsonl", witnesses),
                         ("source_dispositions.jsonl", dispositions)):
        with (out / name).open("x", encoding="utf-8") as handle:
            for value in values:
                handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    _json(out / "report.json", report)
    (out / "producer.py").write_bytes(Path(__file__).read_bytes())
    manifest = {
        "schema": SCHEMA, "status": STATUS, "readers": TOOLS,
        "assessment": {"path": str(Path(assessment).absolute().relative_to(root)),
                       "sha256": assessment_sha256},
        "inputs": inputs, "files": {
            path.name: binding(path) for path in sorted(out.iterdir())
        },
        "producer": binding(Path(__file__)), "counts": report,
        **dict.fromkeys(FLAGS, False),
    }
    _json(out / "manifest.json", manifest)
    return manifest


def verify(directory, manifest_sha256, *, root=ROOT):
    root = Path(root).resolve()
    directory = Path(directory).absolute()
    manifest_path = _file(directory / "manifest.json", root)
    _require(binding(manifest_path)["sha256"] == manifest_sha256, "packet manifest hash changed")
    manifest = json.loads(manifest_path.read_bytes())
    _require(manifest["schema"] == SCHEMA and manifest["status"] == STATUS
             and manifest["readers"] == TOOLS
             and all(manifest[flag] is False for flag in FLAGS), "packet status/approval changed")
    _require(manifest["producer"] == binding(Path(__file__)), "installed producer changed")
    for name, expected in manifest["files"].items():
        _require(Path(name).name == name, "packet artifact must be a direct child")
        _require(binding(_file(directory / name, root)) == expected, "packet artifact changed")
    _require(binding(directory / "producer.py") == manifest["producer"],
             "archived producer binding mismatch")
    rows, witnesses, dispositions, report, inputs = _replay(
        root / manifest["assessment"]["path"], manifest["assessment"]["sha256"], root,
    )
    _require(pq.read_table(directory / "observations.parquet").to_pylist() == rows,
             "date observation replay mismatch")
    _require((directory / "observations.csv").read_bytes() == _csv(rows).encode("utf-8"),
             "complete CSV replay mismatch")
    for name, expected in (("reader_witnesses.jsonl", witnesses),
                           ("source_dispositions.jsonl", dispositions)):
        actual = [json.loads(line) for line in (directory / name).read_bytes().split(b"\n")
                  if line.strip()]
        _require(actual == expected, "complete source/reader witness replay mismatch")
    _require(json.loads((directory / "report.json").read_bytes()) == report == manifest["counts"]
             and inputs == manifest["inputs"], "source counts/input replay mismatch")
    return manifest


def registry_entry(directory, manifest_sha256, *, root=ROOT):
    manifest = verify(directory, manifest_sha256, root=root)
    return {
        "state": "PA", "packet_id": "PA_printed_introduction_dates",
        "root": str(Path(directory).absolute().relative_to(Path(root).resolve())),
        "manifest_sha256": manifest_sha256, "profile": "observations",
        "context_granularity": "source_reference", "contexts": "observations.parquet",
        "context_id": "observation_id", "identifier": "identifier", "bill_id": "bill_id",
        "session_identifier": "session_identifier", "status": "observation_status",
        "native_introduction_field": "printed_introduction_date",
        "native_introduction_when": [{"selector": "observation_status", "values": [QUALIFIED]}],
        "preserve_context_fields": [
            "source_introduction_date_unchanged", "source_view_ids_json",
            "source_pdf_hashes_json", "negative_flags_json", "source_context_id",
        ],
        "expected_contexts": manifest["counts"]["canonical_contexts"], "expected_views": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("build")
    create.add_argument("--assessment", type=Path, required=True)
    create.add_argument("--assessment-sha256", required=True)
    create.add_argument("--out-dir", type=Path, required=True)
    for name in ("verify", "registry"):
        command = commands.add_parser(name)
        command.add_argument("--directory", type=Path, required=True)
        command.add_argument("--manifest-sha256", required=True)
        if name == "registry":
            command.add_argument("--base", type=Path, required=True)
            command.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        result = build(args.assessment, args.assessment_sha256, args.out_dir)
    elif args.command == "verify":
        result = verify(args.directory, args.manifest_sha256)
    else:
        target = args.out.absolute()
        _require(target.resolve() == target and target.parent == ROOT / "data",
                 "new proposed registry must be a direct child of project data")
        _require(not args.out.exists() and not args.out.is_symlink(),
                 "refusing existing proposed registry")
        base = yaml.safe_load(args.base.read_bytes())
        entry = registry_entry(args.directory, args.manifest_sha256)
        _require(all(row.get("packet_id", row["state"]) != entry["packet_id"]
                     for row in base["packets"]), "duplicate registry packet")
        proposed = base | {"packets": [*base["packets"], entry]}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x") as handle:
            yaml.safe_dump(proposed, handle, sort_keys=False)
        result = {"status": "new_proposed_registry_not_current_cohort_change",
                  "path": str(args.out), "new_entry": entry}
    print(json.dumps(result.get("counts", result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

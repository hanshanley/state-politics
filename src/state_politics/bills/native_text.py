"""Capture explicit retained publisher PDF links and preserve complete reader alternatives."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import yaml

from ..provenance import sha256_file, utc_now_iso
from .native_inventory import FLAGS, Capture, Refusal, _append, write_json
from .study_matrix import read_tracker

ROOT = Path(__file__).resolve().parents[3]
TYPE_NAMES = {
    "HB": "HOUSE BILL", "SB": "SENATE BILL",
    "HR": "HOUSE RESOLUTION", "SR": "SENATE RESOLUTION",
    "HMR": "HOUSE MEMORIAL RESOLUTION", "SMR": "SENATE MEMORIAL RESOLUTION",
    "HCR": "HOUSE CONCURRENT RESOLUTION", "SCR": "SENATE CONCURRENT RESOLUTION",
    "HJR": "HOUSE JOINT RESOLUTION", "SJR": "SENATE JOINT RESOLUTION",
    "HCMR": "HOUSE CONCURRENT MEMORIAL RESOLUTION",
    "SCMR": "SENATE CONCURRENT MEMORIAL RESOLUTION",
}


def json_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_bytes().split(b"\n") if line.strip()]


def terminal_result(receipt: dict, results: dict) -> dict | None:
    if "terminal_exchange" in receipt:
        result = results[receipt["terminal_exchange"]]
        if receipt["terminal_exchange"] not in receipt["exchanges"]:
            raise ValueError("terminal result is outside the declared document exchanges")
        return result
    prototype_fields = {"native_id", "source_plan_ordinal", "exchanges", "status", "source_url"}
    if set(receipt) == prototype_fields and len(receipt["exchanges"]) == 1:
        result = results[receipt["exchanges"][0]]
        if (
            receipt["status"] == result["status"] == 200
            and receipt["source_url"] == result["url"]
        ):
            return result
    return None


def _output(path: Path) -> Path:
    path = path.absolute()
    if (
        path.exists() or path.resolve() != path or path == ROOT / "data"
        or not path.is_relative_to(ROOT / "data")
    ):
        raise ValueError("use a new non-symlink output directory under project data/")
    return path


def collect(raw: Path) -> dict:
    """Use the unchanged physical-exchange collector; never restart a closed allowance."""
    authorization = json.loads((raw / "authorization.json").read_bytes())
    capture = Capture(raw, authorization)
    plan = json_rows(raw / "source_plan.jsonl")
    receipts_path = raw / "document_receipts.jsonl"
    receipts = json_rows(receipts_path) if receipts_path.exists() else []
    done = [row["native_id"] for row in receipts]
    if len(set(done)) != len(done):
        raise ValueError("duplicate native document receipt")
    if any(event["event"] in {"closure", "stop"} for event in capture.events):
        raise Refusal("closed/stopped native-text allowance; no continuation")
    states = {row["record"]["state"] for row in plan}
    if len(states) != 1:
        raise ValueError("one independently bounded source state per text allowance")
    state = states.pop()
    reason = "declared_source_plan_completed"
    try:
        for ordinal, item in enumerate(plan):
            native_id = item["record"]["native_id"]
            if native_id in done:
                continue
            if capture.used(state) >= capture._new_exchange_limit(
                authorization["states"][state],
            ):
                reason = "named_physical_exchange_allowance_exhausted"
                break
            url = item["publisher_pdf_link"]["absolute_url"]
            start = len(capture.events)
            receipt = {
                "native_id": native_id, "source_plan_ordinal": ordinal,
                "source_url": url, "exchanges": [], "status": None,
                "original_version_certified": False,
            }
            try:
                seen = set()
                for _ in range(6):
                    if url in seen:
                        raise Refusal("repeated redirect URL; no further retrieval")
                    seen.add(url)
                    result = capture.get(
                        state, url, purpose=f"native_id={native_id};publisher Bill PDF;"
                        " original version remains unverified",
                    )
                    receipt["status"] = result["status"]
                    if not 300 <= result["status"] < 400:
                        receipt["terminal_exchange"] = result["id"]
                        break
                    location = next(
                        (value for key, value in result["headers"]
                         if key.lower() == "location"), None,
                    )
                    if location is None:
                        raise Refusal("redirect without Location")
                    url = urljoin(url, location)
                else:
                    raise Refusal("manual redirect limit reached")
            except Refusal as exc:
                receipt["explicit_stop"] = str(exc)
                reason = str(exc)
            receipt["exchanges"] = [
                event["id"] for event in capture.events[start:] if event["event"] == "result"
            ]
            _append(receipts_path, receipt)
            if "explicit_stop" in receipt:
                break
    finally:
        capture._record({
            "event": "closure", "state": state, "at": utc_now_iso(), "reason": reason,
        })
        manifest = capture.seal()
    return manifest


def observe_header(text: str, record: dict, state_name: str) -> dict:
    """Observe exact printed header spans; never derive a date from the request URL."""
    header = text[:6000]
    end = re.search(r"\bBy\s*:|\bFor\s+An\s+Act\b|\bBE\s+IT\b", header, re.I)
    if end:
        header = header[:end.start()]
    kind = TYPE_NAMES.get(record["measure_type"])
    number = record["identifier"].split()[-1]
    identity = None
    if kind is not None:
        long_name = r"\s+".join(map(re.escape, kind.split()))
        pattern = r"\b(?:" + long_name + "|" + re.escape(record["measure_type"]) + ")"
        pattern += r"\s+(?:NO[.]?\s*)?" + re.escape(number) + r"\b"
        identity = re.search(pattern, header, re.I)
    session_parts = record["session_kind"].replace(",", " ").split()
    session = re.search(
        r"\b" + r"[,\s]+".join(map(re.escape, session_parts)) + r"\b", header, re.I,
    )
    state = re.search(r"\bState\s+of\s+" + re.escape(state_name) + r"\b", header, re.I)

    def span(match):
        if match is None:
            return None
        return {"start": match.start(), "end": match.end(), "text": match.group()}

    return {
        "printed_identifier": span(identity), "printed_session": span(session),
        "printed_state": span(state),
        "all_expected_header_observations_present": all(
            match is not None for match in (identity, session, state)
        ),
        "as_engrossed_literal_present": bool(re.search(r"\bAs\s+Engrossed\b", header, re.I)),
        "filing_date_inferred": False, "original_version_certified": False,
    }


def extract_pdf(path: Path, record: dict, state_name: str) -> tuple[list[dict], list[dict]]:
    """Retain every page from both readers; retain MuPDF word/block layout separately."""
    import fitz
    from pypdf import PdfReader

    pages = []
    with fitz.open(path) as document:
        mupdf_pages = len(document)
        for index, page in enumerate(document):
            pages.append({
                "reader": "pymupdf", "page": index + 1, "text": page.get_text(),
                "words": page.get_text("words"), "blocks": page.get_text("blocks"),
            })
    reader = PdfReader(path)
    if len(reader.pages) != mupdf_pages or mupdf_pages == 0:
        raise ValueError("PDF readers disagree on the complete page population")
    for index, page in enumerate(reader.pages):
        pages.append({"reader": "pypdf", "page": index + 1, "text": page.extract_text() or ""})
    views = []
    for name in ("pymupdf", "pypdf"):
        selected = [row for row in pages if row["reader"] == name]
        text = "\f".join(row["text"] for row in selected)
        if not text.strip():
            continue
        views.append({
            "context_id": record["native_id"], "view_id": f"{record['native_id']}:{name}",
            "reader": name, "text": text, "n_input_characters": len(text),
            "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "n_pages": len(selected), "declared_page_joiner": "\\f",
            "header_observations": observe_header(selected[0]["text"], record, state_name),
            "source_pdf_sha256": sha256_file(path), **FLAGS,
        })
    return pages, views


def project(raw: Path, source: Path, metadata: Path, out: Path) -> dict:
    """Project a closed capture into a separately bound, unapproved native-input packet."""
    out = _output(out)
    manifest = json.loads((raw / "manifest.json").read_bytes())
    if not all(value["closed_for_this_run"] for value in manifest["states"].values()):
        raise ValueError("close collection before projecting immutable native text")
    for name, expected in manifest["files"].items():
        if sha256_file(raw / name) != expected:
            raise ValueError(f"raw native-text capture hash mismatch: {name}")
    authorization = json.loads((raw / "authorization.json").read_bytes())
    for name, expected in authorization["inputs"].items():
        if sha256_file(Path(name)) != expected:
            raise ValueError(f"inherited native source changed: {name}")
    inputs = [
        raw / "manifest.json", source / "manifest.json",
        source / "canonical_identity_candidates.jsonl",
        metadata / "manifest.json", metadata / "bill_evidence.parquet",
        ROOT / "conf/native_inventory_ar_complete.yml", ROOT / "docs/STATE_PROGRESS.md",
        Path(__file__),
    ]
    before = {str(path): sha256_file(path) for path in inputs}
    tracker = read_tracker(ROOT / "docs/STATE_PROGRESS.md").set_index("state")
    candidate_rows = json_rows(source / "canonical_identity_candidates.jsonl")
    candidates = {row["native_id"]: row["candidate_canonical_bill_ids"] for row in candidate_rows}
    aliases = yaml.safe_load(
        (ROOT / "conf/native_inventory_ar_complete.yml").read_text()
    )["canonical_session_candidate_aliases"]
    calendar = pd.read_parquet(metadata / "bill_evidence.parquet", columns=["bill_id"])
    calendar_ids = set(calendar["bill_id"])
    plan = json_rows(raw / "source_plan.jsonl")
    originals = {
        row["native_id"]: row for row in json_rows(source / "native_source_records.jsonl")
    }
    original_links = json_rows(source / "source_original_and_version_urls.jsonl")
    for item in plan:
        if (
            item["record"] != originals.get(item["record"]["native_id"])
            or item["publisher_pdf_link"] not in original_links
        ):
            raise ValueError("native text plan differs from the complete retained source records")
    receipts = {row["native_id"]: row for row in json_rows(raw / "document_receipts.jsonl")}
    if len({row["record"]["native_id"] for row in plan}) != len(plan):
        raise ValueError("duplicate source native context")
    results = {
        event["id"]: event for event in json_rows(raw / "exchanges.jsonl")
        if event["event"] == "result"
    }
    out.mkdir(parents=True)
    shutil.copytree(raw, out / "raw")
    for name in ("native_source_records.jsonl", "canonical_identity_candidates.jsonl",
                 "source_original_and_version_urls.jsonl"):
        shutil.copy2(source / name, out / name)
    shutil.copy2(Path(__file__), out / "producer.py")
    shutil.copy2(ROOT / "docs/STATE_PROGRESS.md", out / "input_state_tracker.txt")
    shutil.copy2(
        ROOT / "conf/native_inventory_ar_complete.yml", out / "input_session_crosswalk.yml",
    )
    contexts, views, errors = [], [], []
    pages_path = out / "complete_pdf_pages.jsonl"
    for item in plan:
        record = item["record"]
        native_id, state = record["native_id"], record["state"]
        receipt = receipts.get(native_id)
        context = {
            "context_id": native_id, "state": state, "identifier": record["identifier"],
            "native_session_identifier": record["session_identifier"],
            "session_identifier": aliases[state][record["session_identifier"]],
            "status": "native_metadata_only_not_collected_in_this_allowance",
            "source_identity_disposition": "metadata_context_no_document_observation",
            "source_record_json": json.dumps(record, ensure_ascii=False),
            "publisher_pdf_link_json": json.dumps(item["publisher_pdf_link"], ensure_ascii=False),
            "candidate_canonical_bill_ids_json": json.dumps(candidates[native_id]),
            "canonical_bill_id": None, "in_primary_calendar_candidates": False,
            "original_version_certified": False, "filing_date_inferred": False, **FLAGS,
        }
        if receipt:
            context["capture_receipt_json"] = json.dumps(receipt)
            context["status"] = "retained_response_not_complete_pdf"
            terminal = terminal_result(receipt, results)
            if (
                terminal and terminal["status"] == 200 and terminal["complete_body"]
                and (raw / terminal["body"]).read_bytes().startswith(b"%PDF-")
            ):
                try:
                    page_rows, reader_views = extract_pdf(
                        raw / terminal["body"], record, tracker.loc[state, "state_name"],
                    )
                except ValueError as exc:
                    errors.append({"native_id": native_id, "error": str(exc)})
                    context["status"] = "explicit_pdf_projection_failure"
                else:
                    for row in page_rows:
                        _append(pages_path, {"context_id": native_id, **row})
                    matched = len(reader_views) == 2 and all(
                        row["header_observations"]["all_expected_header_observations_present"]
                        for row in reader_views
                    )
                    context["status"] = "complete_reader_views" if reader_views else (
                        "complete_pdf_without_extractable_text"
                    )
                    context["source_identity_disposition"] = (
                        "two_reader_printed_identity_and_scope_observed" if matched
                        else "printed_identity_or_scope_unresolved"
                    )
                    if matched and len(candidates[native_id]) == 1:
                        context["canonical_bill_id"] = candidates[native_id][0]
                        context["in_primary_calendar_candidates"] = (
                            candidates[native_id][0] in calendar_ids
                        )
                    for row in reader_views:
                        row["header_observations_json"] = json.dumps(
                            row.pop("header_observations"), ensure_ascii=False,
                        )
                        row["source_url"] = receipt["source_url"]
                        row["source_pdf_path"] = f"raw/{terminal['body']}"
                        views.append(row)
        contexts.append(context)
    pd.DataFrame(contexts).to_parquet(out / "context_inventory.parquet", index=False)
    view_columns = [
        "context_id", "view_id", "reader", "text", "n_input_characters", "input_sha256",
        "n_pages", "declared_page_joiner", "header_observations_json", "source_pdf_sha256",
        "source_url", "source_pdf_path", *FLAGS,
    ]
    pd.DataFrame(views, columns=view_columns).to_parquet(
        out / "source_view_inputs.parquet", index=False,
    )
    (out / "source_view_inputs.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in views), encoding="utf-8",
    )
    write_json(out / "extraction_errors.json", errors)
    after = {str(path): sha256_file(path) for path in inputs}
    if before != after:
        raise ValueError("native-text projection inputs changed")
    report = {
        "schema_version": 1,
        "status": "complete_native_text_observation_packet_not_original_version_certification",
        "native_source_contexts": len(contexts), "captured_document_responses": len(receipts),
        "complete_reader_views": len(views),
        "contexts_with_views": len({row["context_id"] for row in views}),
        "printed_identity_scope_observed_contexts": sum(
            row["source_identity_disposition"] == "two_reader_printed_identity_and_scope_observed"
            for row in contexts
        ),
        "primary_calendar_contexts_with_new_text": sum(
            row["in_primary_calendar_candidates"] for row in contexts
        ),
        "context_statuses": dict(Counter(row["status"] for row in contexts)),
        "pdf_projection_errors": len(errors), "inputs_before": before, "inputs_after": after,
        "unverified_current_or_engrossed_versions_not_filing_time_originals": True,
        "model_input_approved": False, "training_admission": False,
        "filing_time_text_certified": False,
        "sourceclosure_certification": False, "publication": False, **FLAGS,
    }
    write_json(out / "report.json", report)
    report["files"] = {
        path.relative_to(out).as_posix(): {
            "sha256": sha256_file(path), "bytes": path.stat().st_size,
        } for path in sorted(out.rglob("*")) if path.is_file()
    }
    write_json(out / "manifest.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["collect", "project"])
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.command == "collect":
        report = collect(args.raw)
    else:
        if any(value is None for value in (args.source, args.metadata, args.out)):
            parser.error("project requires --source, --metadata and --out")
        report = project(args.raw, args.source, args.metadata, args.out)
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {"artifacts", "inputs_before", "inputs_after", "files"}},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

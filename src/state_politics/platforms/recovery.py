"""Validate bounded source recovery without certifying operative policy or model inputs."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from state_politics.bills.openstates_dump import STATE_CODES
from state_politics.provenance import sha256_file, utc_now_iso

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = {
    "bounded_recovery_inventory_v1", "bounded_recovery_inventory_v2",
    "bounded_recovery_inventory_v3",
}
ALTERNATE_KINDS = {"ocr", "docx_main_document", "pdf_native_blocks"}
DOCX_METHOD = "stdlib_zipfile_elementtree_word_document_xml_paragraphs"
NATIVE_BLOCK_METHOD = "pymupdf_native_blocks_content_order_sort_false"
NATIVE_METHODS = {"docx_main_document": DOCX_METHOD, "pdf_native_blocks": NATIVE_BLOCK_METHOD}


def load_json(path: Path):
    def reject_constant(value):
        raise ValueError(f"nonstandard recovery JSON constant: {value}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def load_jsonl(path: Path) -> list[dict]:
    def reject_constant(value):
        raise ValueError(f"nonstandard recovery JSON constant: {value}")

    with path.open(encoding="utf-8") as handle:
        return [
            json.loads(line, parse_constant=reject_constant) for line in handle if line.strip()
        ]


def verify_manifest(root: Path, required: set[str]) -> dict:
    root = root.resolve()
    manifest = load_json(root / "manifest.json")
    if not required.issubset(manifest["files"]):
        raise ValueError("incomplete recovery inventory manifest")
    for name, digest in manifest["files"].items():
        source = (root / name).resolve()
        if not source.is_relative_to(root):
            raise ValueError("recovery manifest path escapes its packet")
        if sha256_file(source) != digest:
            raise ValueError(f"recovery manifest hash mismatch: {name}")
    return manifest


def validate_capture(row: dict, expected: set, *, typed: bool) -> None:
    key = row["state"], row["party"]
    if key not in expected:
        raise ValueError(f"unexpected recovery organization: {key}")
    url = urlsplit(row["url"])
    if url.scheme not in {"http", "https"} or not url.netloc:
        raise ValueError("recovery source URL must be HTTP(S)")
    if (row["operative_platform_status"] != "unresolved"
            or row["training_admission"] is not False
            or row["analytical_admission"] is not False):
        raise ValueError("recovery captures cannot imply analytical admission")
    retained = row["retrieval_status"] == "response_retained"
    if retained:
        text = row["extracted_text"]
        if not row["stored_path"] or not row["source_sha256"]:
            raise ValueError("retained recovery response lacks body identity")
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != row[
            "text_sha256"
        ]:
            raise ValueError("recovery text hash mismatch")
    elif row["retrieval_status"] == "retrieval_failed":
        if row["stored_path"] or row["source_sha256"] or row["extracted_text"]:
            raise ValueError("failed recovery cannot contain a retained response")
    else:
        raise ValueError("unknown recovery retrieval status")
    if typed:
        if "analysis_cutoff" not in row or row["analysis_cutoff"] is not None:
            raise ValueError("recovery capture cannot establish an analytical cutoff")
        if retained:
            source = Path(row["stored_path"])
            if not source.is_absolute():
                source = ROOT / source
            if not source.is_file() or sha256_file(source) != row["source_sha256"]:
                raise ValueError("recovery source body hash mismatch or missing body")
            if (type(row["source_bytes"]) is not int
                    or source.stat().st_size != row["source_bytes"]):
                raise ValueError("recovery source body byte count mismatch")
        elif row["source_bytes"] is not None:
            raise ValueError("failed recovery cannot contain a retained byte count")
        alternatives = row.get("alternate_extractions")
        if not isinstance(alternatives, list):
            raise ValueError("typed recovery requires an alternate-extractions list")
        identities = set()
        for alternate in alternatives:
            if alternate.get("kind") not in ALTERNATE_KINDS:
                raise ValueError("unknown recovery alternate extraction kind")
            method = alternate.get("extraction_method")
            kind = alternate["kind"]
            if ((kind in NATIVE_METHODS and method != NATIVE_METHODS[kind])
                    or (kind == "ocr" and method in NATIVE_METHODS.values())):
                raise ValueError("recovery alternate kind/method mismatch: native text is not OCR")
            if kind == "pdf_native_blocks":
                provenance = alternate.get("input_disposition", {})
                if not isinstance(provenance, dict):
                    raise ValueError("native-block alternative requires explicit review provenance")
                count = provenance.get("page_count")
                reviewed = provenance.get("visually_checked_pages")
                if (type(count) is not int or count < 1
                        or not isinstance(reviewed, list)
                        or any(type(page) is not int or not 1 <= page <= count
                               for page in reviewed)
                        or len(set(reviewed)) != len(reviewed)
                        or provenance.get("reading_order_certified") is not False):
                    raise ValueError(
                        "native-block alternative requires explicit uncertified review scope"
                    )
            identity = alternate.get("extraction_id")
            if not isinstance(identity, str) or not identity or identity in identities:
                raise ValueError("missing or duplicate recovery alternate extraction identity")
            identities.add(identity)
            if (alternate.get("training_admission") is not False
                    or alternate.get("analytical_admission") is not False):
                raise ValueError("recovery alternate cannot imply analytical admission")
            if (not retained
                    or (alternate["state"], alternate["party"]) != key
                    or alternate["source_sha256"] != row["source_sha256"]
                    or not isinstance(alternate["extracted_text"], str)
                    or hashlib.sha256(alternate["extracted_text"].encode()).hexdigest()
                    != alternate["text_sha256"]):
                raise ValueError("recovery alternate source/text hash mismatch")
    else:
        ocr = row["alternate_ocr"]
        if ocr is not None and (
            not retained
            or (ocr["state"], ocr["party"]) != key
            or ocr["source_sha256"] != row["source_sha256"]
            or not isinstance(ocr["extracted_text"], str)
            or hashlib.sha256(ocr["extracted_text"].encode()).hexdigest() != ocr["text_sha256"]
        ):
            raise ValueError("recovery OCR source/text hash mismatch")


def alternate_body_counts(captures: list[dict], *, include_native_blocks: bool = True) -> dict:
    kinds = [("ocr", "alternate_ocr"), ("docx_main_document", "docx_main_document")]
    if include_native_blocks:
        kinds.append(("pdf_native_blocks", "pdf_native_blocks"))
    return {
        f"n_distinct_bodies_with_{label}": len({
            row["source_sha256"] for row in captures
            if any(alt["kind"] == kind for alt in row["alternate_extractions"])
        })
        for kind, label in kinds
    }


def load_recovery(path: Path, expected: set) -> tuple[dict, list]:
    root = path.parent.resolve()
    if path.name != "inventory.json":
        raise ValueError("incomplete recovery inventory manifest")
    verify_manifest(root, {"inventory.json", "captures.jsonl", "organizations.csv"})
    inventory = load_json(path)
    if inventory.get("schema") not in SCHEMAS:
        raise ValueError("incompatible bounded recovery inventory")
    typed = inventory["schema"] != "bounded_recovery_inventory_v1"
    native_blocks = inventory["schema"] == "bounded_recovery_inventory_v3"
    captures = load_jsonl(root / "captures.jsonl")
    if len({row["capture_id"] for row in captures}) != len(captures):
        raise ValueError("duplicate recovery capture identity")
    groups = defaultdict(list)
    bodies = defaultdict(list)
    for row in captures:
        validate_capture(row, expected, typed=typed)
        if typed and not native_blocks and any(
            alt["kind"] == "pdf_native_blocks" for alt in row["alternate_extractions"]
        ):
            raise ValueError("native-block alternatives require recovery inventory v3")
        groups[row["state"], row["party"]].append(row)
        if row["retrieval_status"] == "response_retained":
            bodies[row["source_sha256"]].append(row)
    rows = inventory["rows"]
    if len(rows) != 100 or {(r["state"], r["party"]) for r in rows} != expected:
        raise ValueError("recovery requires all 100 expected organizations")
    with (root / "organizations.csv").open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    if csv_rows != [{k: str(v) for k, v in row.items()} for row in rows]:
        raise ValueError("recovery CSV does not reconcile with inventory")
    for row in rows:
        org = groups[row["state"], row["party"]]
        retained = [r for r in org if r["retrieval_status"] == "response_retained"]
        counts = {
            "n_selected_capture_attempts": len(org),
            "n_retained_response_captures": len(retained),
            "n_failed_retrieval_attempts": len(org) - len(retained),
            "n_distinct_response_body_hashes": len({r["source_sha256"] for r in retained}),
        }
        if typed:
            counts.update(alternate_body_counts(org, include_native_blocks=native_blocks))
        if any(row[key] != value for key, value in counts.items()):
            raise ValueError("recovery organization counts do not reconcile")
        if (row["operative_platform_status"] != "unresolved"
                or row["training_admission"] is not False
                or row["analytical_admission"] is not False):
            raise ValueError("recovery organization operative status must remain unresolved")
    totals = {
        "expected_organizations": 100, "n_selected_capture_attempts": len(captures),
        "n_retained_response_captures": sum(map(len, bodies.values())),
        "n_failed_retrieval_attempts": sum(
            row["retrieval_status"] == "retrieval_failed" for row in captures
        ),
        "n_distinct_response_body_hashes": len(bodies),
        "n_repeated_body_hash_groups": sum(len(group) > 1 for group in bodies.values()),
        "n_organizations_with_retained_responses": len({
            (row["state"], row["party"]) for group in bodies.values() for row in group
        }),
    }
    if typed:
        totals.update(alternate_body_counts(captures, include_native_blocks=native_blocks))
    if any(inventory[key] != value for key, value in totals.items()):
        raise ValueError("recovery inventory totals do not reconcile")
    if inventory["analysis_cutoff"] is not None:
        raise ValueError("bounded recovery does not establish an analytical cutoff")
    return inventory, captures


def build_inventory(
    baseline: Path, capture_paths: list[Path], alternates: list[tuple[str, Path]],
    out: Path, *, registry: Path = ROOT / "conf/party_registry.yml",
) -> dict:
    if out.exists():
        raise FileExistsError("refusing to overwrite recovery inventory")
    organizations = yaml.safe_load(registry.read_text())["organizations"]
    expected = {(state.upper(), party) for state in STATE_CODES for party in ("D", "R")}
    registered = {(org["state"], org["party"]) for org in organizations}
    if len(organizations) != 100 or registered != expected:
        raise ValueError("registry must contain exactly 100 unique organizations")
    inherited, original = load_recovery(baseline, expected)
    captures = [
        {**row, "alternate_extractions": list(row.get("alternate_extractions", []))}
        for row in original
    ]
    inputs = [{
        "packet": str(baseline.parent), "input": baseline.name,
        "manifest_sha256": sha256_file(baseline.parent / "manifest.json"),
        "input_sha256": sha256_file(baseline), "role": "preserved_baseline_inventory",
    }]
    frozen_inputs = [baseline, baseline.parent / "manifest.json",
                     baseline.parent / "captures.jsonl", baseline.parent / "organizations.csv"]
    normalizations = []
    normalization_path = baseline.parent / "normalizations.json"
    if normalization_path.exists():
        verify_manifest(baseline.parent, {"normalizations.json"})
        normalizations = load_json(normalization_path)
        frozen_inputs.append(normalization_path)
    for path in capture_paths:
        verify_manifest(path.parent, {path.name})
        inputs.append({
            "packet": str(path.parent), "input": path.name,
            "manifest_sha256": sha256_file(path.parent / "manifest.json"),
            "input_sha256": sha256_file(path), "role": "additional_capture_packet",
        })
        frozen_inputs.extend([path, path.parent / "manifest.json"])
        for index, source in enumerate(load_jsonl(path)):
            if source["capture_id"] != f"{path.parent.name}:{index}":
                raise ValueError("capture identity does not match its frozen packet position")
            if source["ok"] != bool(source["stored_path"]):
                raise ValueError("fetch success and raw retention do not reconcile")
            if source.get("analysis_cutoff") is not None:
                raise ValueError("recovery capture cannot establish an analytical cutoff")
            if ("source_sha256" in source
                    and source["source_sha256"] != source["content_sha256"]):
                raise ValueError("inconsistent source body hash aliases")
            captures.append({
                "capture_id": source["capture_id"], "packet": path.parent.name,
                "input_record_index": index, "state": source["state"], "party": source["party"],
                "url": source["url"], "stored_path": source["stored_path"],
                "source_sha256": source["content_sha256"],
                "source_bytes": source["content_bytes"],
                "retrieval_status": (
                    "response_retained" if source["stored_path"] else "retrieval_failed"
                ),
                "extraction_method": source.get(
                    "extraction_method", "captured_response_standard_extraction"
                ),
                "extracted_text": source["extracted_text"], "text_sha256": source["text_sha256"],
                "passed_automated_content_filter": None, "input_disposition": source,
                "operative_platform_status": source["operative_platform_status"],
                "training_admission": source["training_admission"],
                "analytical_admission": source["analytical_admission"],
            })
    if len({row["capture_id"] for row in captures}) != len(captures):
        raise ValueError("duplicate recovery capture identity")
    for row in captures:
        row["analysis_cutoff"] = None
        row.setdefault("alternate_extractions", [])
        legacy_ocr = row.pop("alternate_ocr", None)
        if legacy_ocr:
            if (legacy_ocr.get("training_admission", False) is not False
                    or legacy_ocr.get("analytical_admission", False) is not False):
                raise ValueError("recovery alternate cannot imply analytical admission")
            row["alternate_extractions"].append({
                **legacy_ocr,
                "extraction_id": (
                    f"legacy-ocr:{row['state']}:{row['party']}:{row['source_sha256']}"
                ),
                "kind": "ocr",
                "training_admission": False, "analytical_admission": False,
            })
        if row["stored_path"]:
            stored = Path(row["stored_path"])
            if not stored.is_absolute():
                stored = ROOT / stored
            size = stored.stat().st_size
            if "source_bytes" in row and row["source_bytes"] != size:
                raise ValueError("recovery source body byte count mismatch")
            row["source_bytes"] = size
        else:
            if row.get("source_bytes") is not None or row["extracted_text"]:
                raise ValueError("failed recovery cannot contain retained bytes or text")
            row["source_bytes"] = None
    by_identity = {row["capture_id"]: row for row in captures}
    by_body = defaultdict(list)
    for row in captures:
        if row["stored_path"]:
            by_body[row["state"], row["party"], row["source_sha256"]].append(row)
    for kind, path in alternates:
        if kind not in ALTERNATE_KINDS:
            raise ValueError("unknown recovery alternate extraction kind")
        verify_manifest(path.parent, {path.name})
        inputs.append({
            "packet": str(path.parent), "input": path.name,
            "manifest_sha256": sha256_file(path.parent / "manifest.json"),
            "input_sha256": sha256_file(path),
            "role": "alternate_extraction_not_an_additional_source_capture", "kind": kind,
        })
        frozen_inputs.extend([path, path.parent / "manifest.json"])
        for index, source in enumerate(load_jsonl(path)):
            parent_id = source.get("parent_capture_id", source.get("capture_id"))
            if parent_id not in by_identity:
                raise ValueError("recovery alternate has no matching source capture")
            parent = by_identity[parent_id]
            key = source["state"], source["party"], source["source_sha256"]
            if key != (parent["state"], parent["party"], parent["source_sha256"]):
                raise ValueError("recovery alternate source binding mismatch")
            if key not in by_body:
                raise ValueError("recovery alternate has no retained source body")
            alternate = {
                "extraction_id": f"{path.parent.name}:{index}", "kind": kind,
                "state": source["state"], "party": source["party"],
                "source_sha256": source["source_sha256"],
                "extracted_text": source["extracted_text"], "text_sha256": source["text_sha256"],
                "extraction_method": source["extraction_method"],
                "input_disposition": source,
                "derivative_manifest_sha256": sha256_file(path.parent / "manifest.json"),
                "training_admission": source["training_admission"],
                "analytical_admission": source["analytical_admission"],
            }
            for row in by_body[key]:
                row["alternate_extractions"].append(alternate)
    for related in by_body.values():
        alternatives = {}
        for row in related:
            for alternate in row["alternate_extractions"]:
                identity = alternate["extraction_id"]
                if identity in alternatives and alternatives[identity] != alternate:
                    raise ValueError("inconsistent recovery alternate extraction identity")
                alternatives[identity] = alternate
        for row in related:
            existing = {alt["extraction_id"] for alt in row["alternate_extractions"]}
            row["alternate_extractions"].extend(
                alt for identity, alt in alternatives.items() if identity not in existing
            )
    groups = defaultdict(list)
    bodies = defaultdict(list)
    for row in captures:
        validate_capture(row, expected, typed=True)
        groups[row["state"], row["party"]].append(row)
        if row["stored_path"]:
            bodies[row["source_sha256"]].append(row["capture_id"])
    for prior, current in zip(original, captures[:len(original)], strict=True):
        if any(
            current[key] != value for key, value in prior.items()
            if key not in {"alternate_ocr", "alternate_extractions"}
        ):
            raise ValueError("successor changed a baseline source identity or native field")
    rows = []
    for org in sorted(organizations, key=lambda row: (row["state"], row["party"])):
        selected = groups[org["state"], org["party"]]
        retained = [row for row in selected if row["stored_path"]]
        rows.append({
            "state": org["state"], "party": org["party"], "name": org["name"],
            "n_selected_capture_attempts": len(selected),
            "n_retained_response_captures": len(retained),
            "n_failed_retrieval_attempts": len(selected) - len(retained),
            "n_distinct_requested_urls": len({row["url"] for row in selected}),
            "n_distinct_response_body_hashes": len({row["source_sha256"] for row in retained}),
            "n_nonempty_standard_or_viewer_text_captures": sum(
                bool(row["extracted_text"].strip()) for row in retained
            ),
            **alternate_body_counts(selected),
            "operative_platform_status": "unresolved",
            "training_admission": False, "analytical_admission": False,
        })
    summary = {
        "generated_at": utc_now_iso(), "schema": "bounded_recovery_inventory_v3",
        "analysis_cutoff": None, "expected_organizations": 100,
        "n_selected_capture_attempts": len(captures),
        "n_retained_response_captures": sum(map(len, bodies.values())),
        "n_failed_retrieval_attempts": sum(not row["stored_path"] for row in captures),
        "n_distinct_response_body_hashes": len(bodies),
        "n_repeated_body_hash_groups": sum(len(group) > 1 for group in bodies.values()),
        "n_organizations_with_retained_responses": sum(
            row["n_retained_response_captures"] > 0 for row in rows
        ),
        "n_organizations_without_retained_responses_in_this_inventory": sum(
            row["n_retained_response_captures"] == 0 for row in rows
        ),
        **alternate_body_counts(captures),
        "n_inherited_normalizations": len(normalizations),
        "operative_status_counts": {"unresolved": 100}, "rows": rows, "inputs": inputs,
        "inherited_inputs": inherited.get("inputs", []),
        "selected_capture_packets": sorted({
            row["capture_id"].rsplit(":", 1)[0] for row in captures
        }),
        "limitations": [
            "Selected packets only, not all recovery evidence or an exhaustive crawl.",
            "Capture records count logical retrievals, not individual HTTP retry attempts.",
            "Retained responses and nonempty text do not establish operative adopted policy.",
            "Identical body hashes are not independent semantic documents or commitments.",
            "OCR, DOCX and PDF native-block text are alternatives, "
            "never additional source captures.",
            "DOCX alternatives exclude layout, other XML parts and images; they are not OCR.",
            "PDF native-block alternatives are not OCR; "
            "full-document reading order is uncertified.",
            "No adoption dates, analytical cutoff, classifications or analytical claims certified.",
            "Original captures, native text and historical evidence remain unchanged.",
            "Ignored local evidence bytes are not backed up by a Git push.",
        ],
    }
    encoded = "".join(
        json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in captures
    )
    out.mkdir(parents=True)
    (out / "captures.jsonl").write_text(encoded, encoding="utf-8")
    for name, value in (
        ("inventory.json", summary), ("normalizations.json", normalizations),
        ("body_hash_groups.json", bodies),
    ):
        (out / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    with (out / "organizations.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    inputs_dir = out / "inputs"
    inputs_dir.mkdir()
    for source in frozen_inputs:
        dest = inputs_dir / source.parent.name / source.name
        dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, dest)
    shutil.copyfile(registry, inputs_dir / "party_registry.yml")
    shutil.copyfile(__file__, inputs_dir / "recovery.py")
    shutil.copyfile(ROOT / "scripts/build_recovery_inventory.py",
                    inputs_dir / "build_recovery_inventory.py")
    manifest = {
        "completed_at": utc_now_iso(),
        "files": {
            str(path.relative_to(out)): sha256_file(path)
            for path in sorted(out.rglob("*")) if path.is_file()
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return summary

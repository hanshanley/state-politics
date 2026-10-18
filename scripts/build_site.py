#!/usr/bin/env python3
"""Build an explicitly unpublished evidence preview from saved sources, never model inference."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import json
import shutil
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from state_politics.bills.openstates_dump import STATE_CODES
from state_politics.provenance import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def load_recovery(path: Path, expected: set) -> tuple[dict, list]:
    def reject_constant(value):
        raise ValueError(f"nonstandard recovery JSON constant: {value}")

    def load(file):
        return json.loads(file.read_text(), parse_constant=reject_constant)

    root = path.parent.resolve()
    manifest = load(root / "manifest.json")
    required = {"inventory.json", "captures.jsonl", "organizations.csv"}
    if path.name != "inventory.json" or not required.issubset(manifest["files"]):
        raise ValueError("incomplete recovery inventory manifest")
    for name, digest in manifest["files"].items():
        source = (root / name).resolve()
        if not source.is_relative_to(root):
            raise ValueError("recovery manifest path escapes its packet")
        if sha256_file(source) != digest:
            raise ValueError(f"recovery manifest hash mismatch: {name}")
    inventory = load(path)
    if inventory.get("schema") != "bounded_recovery_inventory_v1":
        raise ValueError("incompatible bounded recovery inventory")
    captures = [
        json.loads(line, parse_constant=reject_constant)
        for line in (root / "captures.jsonl").read_text().split("\n") if line.strip()
    ]
    if len({row["capture_id"] for row in captures}) != len(captures):
        raise ValueError("duplicate recovery capture identity")
    groups = defaultdict(list)
    bodies = defaultdict(list)
    for row in captures:
        key = row["state"], row["party"]
        if key not in expected:
            raise ValueError(f"unexpected recovery organization: {key}")
        url = urlsplit(row["url"])
        if url.scheme not in {"http", "https"} or not url.netloc:
            raise ValueError("recovery source URL must be HTTP(S)")
        if (row["operative_platform_status"] != "unresolved"
                or row["training_admission"] or row["analytical_admission"]):
            raise ValueError("recovery captures cannot imply analytical admission")
        groups[key].append(row)
        if row["retrieval_status"] == "response_retained":
            text = row["extracted_text"]
            if not row["stored_path"] or not row["source_sha256"]:
                raise ValueError("retained recovery response lacks body identity")
            if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != row[
                "text_sha256"
            ]:
                raise ValueError("recovery text hash mismatch")
            bodies[row["source_sha256"]].append(row)
        elif row["retrieval_status"] == "retrieval_failed":
            if row["stored_path"] or row["source_sha256"] or row["extracted_text"]:
                raise ValueError("failed recovery cannot contain a retained response")
        else:
            raise ValueError("unknown recovery retrieval status")
        ocr = row["alternate_ocr"]
        if ocr is not None and (
            row["retrieval_status"] != "response_retained"
            or (ocr["state"], ocr["party"]) != key
            or ocr["source_sha256"] != row["source_sha256"]
            or not isinstance(ocr["extracted_text"], str)
            or hashlib.sha256(ocr["extracted_text"].encode()).hexdigest() != ocr["text_sha256"]
        ):
            raise ValueError("recovery OCR source/text hash mismatch")
    rows = inventory["rows"]
    if len(rows) != 100 or {(r["state"], r["party"]) for r in rows} != expected:
        raise ValueError("recovery requires all 100 expected organizations")
    with (root / "organizations.csv").open(newline="") as handle:
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
        if any(row[key] != value for key, value in counts.items()):
            raise ValueError("recovery organization counts do not reconcile")
        if (row["operative_platform_status"] != "unresolved"
                or row["training_admission"] or row["analytical_admission"]):
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
    if any(inventory[key] != value for key, value in totals.items()):
        raise ValueError("recovery inventory totals do not reconcile")
    if inventory["analysis_cutoff"] is not None:
        raise ValueError("bounded recovery does not establish an analytical cutoff")
    return inventory, captures


def build_preview(
    ledger_path: Path, historical_path: Path, out: Path, *, recovery_path: Path | None = None,
) -> dict:
    ledger = json.loads(ledger_path.read_text())
    if ledger.get("schema_version") != 1 or ledger.get("expected_organizations") != 100:
        raise ValueError("incompatible source coverage contract")
    rows = ledger["rows"]
    keys = {(row["state"], row["party"]) for row in rows}
    expected = {(state.upper(), party) for state in STATE_CODES for party in ("D", "R")}
    if len(rows) != 100 or keys != expected:
        raise ValueError("preview requires all 100 unique expected organization rows")
    recovery, captures = load_recovery(recovery_path, expected) if recovery_path else (None, [])
    recovery_rows = (
        {(row["state"], row["party"]): row for row in recovery["rows"]} if recovery else {}
    )
    recovered = defaultdict(list)
    for row in captures:
        recovered[row["state"], row["party"]].append(row)
    archive = [
        json.loads(line) for line in historical_path.read_text().split("\n") if line.strip()
    ]
    partitions = defaultdict(list)
    for row in archive:
        if (row["state"], row["party"]) in keys:
            partitions[row["state"], row["party"]].append(row)
    table = []
    def escape(value):
        return html.escape(str(value), quote=True)

    for row in rows:
        key = (row["state"], row["party"])
        if row["historical_document_count"] != len(partitions[key]):
            raise ValueError(f"coverage does not reconcile with source rows: {key}")
        cells = [
            f"{row['state']} / {row['party']}", row["historical_document_count"],
            row["historical_latest_year"] if row["historical_latest_year"] is not None else "—",
            row["operative_platform_status"],
            (
                f"{recovery_rows[key]['n_retained_response_captures']} retained / "
                f"{recovery_rows[key]['n_selected_capture_attempts']} attempts"
                if recovery else "Not included in this build"
            ),
            "Not applicable: nonpartisan" if row["state"] == "NE" else "Not rebuilt",
        ]
        table.append(
            f'<tr data-state="{escape(key[0])}" data-party="{escape(key[1])}">'
            + "".join(f"<td>{escape(value)}</td>" for value in cells) + "</tr>"
        )
    options = "".join(
        f'<option value="{escape(state)}">{escape(state)}</option>'
        for state in sorted({row["state"] for row in rows})
    )
    document = (ROOT / "web/preview.html").read_text()
    for marker, value in {
        "@@ARCHIVE_COUNT@@": f"{len(archive):,}",
        "@@STATE_OPTIONS@@": options, "@@COVERAGE_ROWS@@": "\n".join(table),
        "@@RECOVERY_OPTION@@": (
            '<option value="recovery">Bounded recovery captures</option>' if recovery else ""
        ),
        "@@RECOVERY_NOTE@@": (
            f"<p class=\"note\">Selected recovery packets: {len(captures)} attempts, "
            f"{recovery['n_retained_response_captures']} retained responses and "
            f"{recovery['n_distinct_response_body_hashes']} distinct body hashes. "
            "These include shells, drafts and repeated captures, not verified platforms. "
            "This bounded inventory excludes other campaign packets; zero here is not "
            "publication absence.</p>" if recovery else ""
        ),
        "@@RECOVERY_DOWNLOADS@@": (
            '<p><a href="downloads/recovery_captures.jsonl.gz" download>'
            'Complete selected recovery captures (JSONL, gzip; full text and alternate OCR)</a>'
            ' · <a href="downloads/recovery_inventory.json" download>'
            'Recovery inventory and all 100 organization rows</a>'
            ' · <a href="downloads/recovery_inventory_manifest.json" download>'
            'Original recovery packet hashes</a></p>' if recovery else ""
        ),
    }.items():
        document = document.replace(marker, value)
    if "@@" in document:
        raise ValueError("unresolved template fields")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(document)
    for name in ("preview.css", "preview.js"):
        shutil.copyfile(ROOT / "web" / name, out / name)
    evidence = out / "evidence"
    evidence.mkdir(exist_ok=True)
    for state, party in keys:
        (evidence / f"{state}-{party}.json").write_text(
            json.dumps(partitions[state, party], ensure_ascii=True)
        )
        if recovery:
            (evidence / f"recovery-{state}-{party}.json").write_text(
                json.dumps(recovered[state, party], ensure_ascii=True, allow_nan=False)
            )
        else:
            (evidence / f"recovery-{state}-{party}.json").unlink(missing_ok=True)
    downloads = out / "downloads"
    downloads.mkdir(exist_ok=True)
    shutil.copyfile(ledger_path, downloads / "source_coverage.json")
    with (
        gzip.open(downloads / "historical_documents.jsonl.gz", "wb") as handle,
        historical_path.open("rb") as source,
    ):
        shutil.copyfileobj(source, handle)
    if recovery_path:
        shutil.copyfile(recovery_path, downloads / "recovery_inventory.json")
        shutil.copyfile(
            recovery_path.parent / "manifest.json", downloads / "recovery_inventory_manifest.json"
        )
        with (
            gzip.open(downloads / "recovery_captures.jsonl.gz", "wb") as handle,
            (recovery_path.parent / "captures.jsonl").open("rb") as source,
        ):
            shutil.copyfileobj(source, handle)
    else:
        for name in (
            "recovery_inventory.json", "recovery_inventory_manifest.json",
            "recovery_captures.jsonl.gz",
        ):
            (downloads / name).unlink(missing_ok=True)
    manifest = {
        "schema_version": 1, "publication_status": "local_only_unpublished",
        "scientific_certification": "not_performed", "archive_documents": len(archive),
        "state_major_party_documents": sum(map(len, partitions.values())),
        "analysis_cutoff": ledger["analysis_cutoff"],
        "recovery_capture_attempts": len(captures) if recovery else None,
        "recovery_retained_responses": (
            recovery["n_retained_response_captures"] if recovery else None
        ),
        "recovery_inventory_scope": "selected_packets_not_full_campaign" if recovery else None,
        "inputs": {
            "source_coverage_sha256": sha256_file(ledger_path),
            "historical_documents_sha256": sha256_file(historical_path),
        },
        "assets": {
            path.name: sha256_file(path) for path in (ROOT / "web").iterdir() if path.is_file()
        },
    }
    if recovery_path:
        manifest["inputs"]["recovery_manifest_sha256"] = sha256_file(
            recovery_path.parent / "manifest.json"
        )
    (downloads / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coverage", type=Path, default=ROOT / "data/processed/source_coverage.json"
    )
    parser.add_argument(
        "--historical", type=Path, default=ROOT / "data/processed/platforms_historical.jsonl"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "data/preview")
    parser.add_argument(
        "--recovery", type=Path,
        help="Optional verified bounded-recovery inventory.json; not analytical admission",
    )
    args = parser.parse_args(argv)
    if not args.out.resolve().is_relative_to((ROOT / "data").resolve()):
        parser.error("preview output must remain under this project's ignored data/ directory")
    result = build_preview(
        args.coverage, args.historical, args.out, recovery_path=args.recovery,
    )
    print(f"wrote local-only preview: {args.out / 'index.html'}")
    print(f"archive documents: {result['archive_documents']}; no analytical findings published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

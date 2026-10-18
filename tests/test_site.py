"""Local preview uses complete source evidence and never manufactures analytical findings."""

import csv
import gzip
import hashlib
import json
import runpy
from pathlib import Path

import pytest
import yaml

from state_politics.analysis.coverage import build_source_ledger
from state_politics.analysis.coverage import main as coverage_main
from state_politics.provenance import sha256_file

ROOT = Path(__file__).resolve().parents[1]
build_preview = runpy.run_path(str(ROOT / "scripts/build_site.py"))["build_preview"]


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085"])
def test_preview_downloads_full_text_and_reconciles_all_organization_rows(tmp_path, separator):
    organizations = yaml.safe_load((ROOT / "conf/party_registry.yml").read_text())[
        "organizations"
    ]
    documents = [
        {"state": "TX", "party": "D", "year": 2010, "filename": "TX-2010-D.txt",
         "text": f"Complete historical policy text{separator}not metadata only."},
        {"state": "US", "party": "R", "year": 2008, "filename": "US-2008-R.txt",
         "text": "National evidence remains in the full archive download."},
    ]
    ledger = build_source_ledger(organizations, documents)
    coverage = tmp_path / "source_coverage.json"
    coverage.write_text(json.dumps(ledger))
    history = tmp_path / "platforms_historical.jsonl"
    history.write_text("".join(
        json.dumps(row, ensure_ascii=False) + "\n" for row in documents
    ))
    assert coverage_main([
        "--sources-only", "--data-dir", str(tmp_path),
        "--registry", str(ROOT / "conf/party_registry.yml"), "--out", str(coverage),
    ]) == 0
    generated = json.loads(coverage.read_text())
    assert generated["rows"] == ledger["rows"]
    out = tmp_path / "preview"
    result = build_preview(coverage, history, out)
    assert result["archive_documents"] == 2
    assert result["state_major_party_documents"] == 1
    assert result["publication_status"] == "local_only_unpublished"
    assert len(list((out / "evidence").glob("*.json"))) == 100
    assert json.loads((out / "evidence/TX-D.json").read_text()) == documents[:1]
    assert json.loads((out / "evidence/NE-R.json").read_text()) == []
    with gzip.open(out / "downloads/historical_documents.jsonl.gz", "rt") as handle:
        assert [json.loads(line) for line in handle] == documents
    html = (out / "index.html").read_text()
    assert html.count('<tr data-state="') == 100
    assert "@@" not in html and "Not publication-ready" in html
    assert all(row["modern_evidence_status"] == "unresolved" for row in ledger["rows"])
    ledger["rows"][0]["historical_document_count"] += 1
    coverage.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match="reconcile"):
        build_preview(coverage, history, out)


def test_source_ledger_does_not_call_a_failed_search_platform_absence():
    organizations = yaml.safe_load((ROOT / "conf/party_registry.yml").read_text())[
        "organizations"
    ]
    ledger = build_source_ledger(organizations, [], [
        {"state": "TX", "party": "D", "searched": "False", "wayback_error": "timeout"}
    ])
    texas = next(row for row in ledger["rows"] if row["state"] == "TX" and row["party"] == "D")
    assert texas["discovery_status"] == "retrieval_failed"
    assert texas["modern_evidence_status"] == "unresolved"
    assert ledger["analysis_cutoff"] is None
    with pytest.raises(ValueError, match="100 expected"):
        build_source_ledger(organizations[:-1], [])


def recovery_fixture(tmp_path, separator="\u2028"):
    organizations = yaml.safe_load((ROOT / "conf/party_registry.yml").read_text())[
        "organizations"
    ]
    ledger = build_source_ledger(organizations, [])
    coverage = tmp_path / "coverage.json"
    coverage.write_text(json.dumps(ledger))
    history = tmp_path / "history.jsonl"
    history.write_text("")
    packet = tmp_path / "recovery"
    packet.mkdir()
    text = f"Complete recovered text{separator}<script>literal source evidence</script>"
    digest = hashlib.sha256(text.encode()).hexdigest()
    ocr_text = f"Complete alternate OCR{separator}uncertified transcription"
    retained = {
        "capture_id": "packet:0", "state": "TX", "party": "D",
        "url": "https://example.org/platform", "stored_path": "raw/source.bin",
        "source_sha256": digest, "text_sha256": digest, "extracted_text": text,
        "retrieval_status": "response_retained",
        "extraction_method": "captured_response_standard_extraction",
        "operative_platform_status": "unresolved",
        "training_admission": False, "analytical_admission": False,
        "alternate_ocr": {
            "state": "TX", "party": "D", "source_sha256": digest,
            "extracted_text": ocr_text,
            "text_sha256": hashlib.sha256(ocr_text.encode()).hexdigest(),
        },
    }
    captures = [
        retained,
        {**retained, "capture_id": "packet:1", "url": "https://example.org/duplicate"},
        {**retained, "capture_id": "packet:2", "url": "https://example.org/failed",
         "stored_path": None, "source_sha256": None, "extracted_text": None,
         "text_sha256": hashlib.sha256(b"").hexdigest(), "alternate_ocr": None,
         "retrieval_status": "retrieval_failed"},
    ]
    (packet / "captures.jsonl").write_text("".join(
        json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in captures
    ))
    rows = []
    for org in ledger["rows"]:
        selected = org["state"] == "TX" and org["party"] == "D"
        rows.append({
            "state": org["state"], "party": org["party"],
            "n_selected_capture_attempts": 3 if selected else 0,
            "n_retained_response_captures": 2 if selected else 0,
            "n_failed_retrieval_attempts": 1 if selected else 0,
            "n_distinct_response_body_hashes": 1 if selected else 0,
            "operative_platform_status": "unresolved",
            "training_admission": False, "analytical_admission": False,
        })
    inventory = {
        "schema": "bounded_recovery_inventory_v1", "expected_organizations": 100,
        "analysis_cutoff": None, "n_selected_capture_attempts": 3,
        "n_retained_response_captures": 2, "n_failed_retrieval_attempts": 1,
        "n_distinct_response_body_hashes": 1, "n_repeated_body_hash_groups": 1,
        "n_organizations_with_retained_responses": 1, "rows": rows,
    }
    (packet / "inventory.json").write_text(json.dumps(inventory))
    with (packet / "organizations.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    refresh_recovery_manifest(packet)
    return coverage, history, packet, captures


def refresh_recovery_manifest(packet):
    (packet / "manifest.json").write_text(json.dumps({"files": {
        name: sha256_file(packet / name)
        for name in ("inventory.json", "captures.jsonl", "organizations.csv")
    }}))


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085"])
def test_preview_preserves_recovery_failures_duplicates_and_complete_ocr(tmp_path, separator):
    coverage, history, packet, captures = recovery_fixture(tmp_path, separator)
    out = tmp_path / "preview"
    result = build_preview(coverage, history, out, recovery_path=packet / "inventory.json")
    assert result["recovery_capture_attempts"] == 3
    assert result["recovery_retained_responses"] == 2
    assert json.loads((out / "evidence/recovery-TX-D.json").read_text()) == captures
    assert json.loads((out / "evidence/recovery-NE-R.json").read_text()) == []
    with gzip.open(out / "downloads/recovery_captures.jsonl.gz", "rb") as handle:
        assert handle.read() == (packet / "captures.jsonl").read_bytes()
    document = (out / "index.html").read_text()
    assert "2 retained responses and 1 distinct body hashes" in document
    assert "not verified platforms" in document
    assert 'value="recovery"' in document and "@@" not in document
    build_preview(coverage, history, out)
    assert not list((out / "evidence").glob("recovery-*.json"))
    assert not list((out / "downloads").glob("recovery_*"))


@pytest.mark.parametrize("defect,match", [
    ("file_hash", "manifest hash"),
    ("text_hash", "text hash"),
    ("unsafe_url", "HTTP"),
    ("duplicate_identity", "duplicate"),
    ("ocr_binding", "OCR source"),
    ("analytical_admission", "analytical admission"),
    ("nonstandard_json", "nonstandard recovery JSON"),
    ("inventory_total", "totals"),
])
def test_preview_rejects_inconsistent_or_unsafe_recovery_inputs(tmp_path, defect, match):
    coverage, history, packet, captures = recovery_fixture(tmp_path)
    if defect == "unsafe_url":
        captures[0]["url"] = "javascript:alert(1)"
    elif defect == "duplicate_identity":
        captures[1]["capture_id"] = captures[0]["capture_id"]
    elif defect == "ocr_binding":
        captures[0]["alternate_ocr"]["source_sha256"] = "b" * 64
    elif defect == "analytical_admission":
        captures[0]["analytical_admission"] = True
    elif defect == "nonstandard_json":
        captures[0]["diagnostic"] = float("nan")
    elif defect == "inventory_total":
        inventory = json.loads((packet / "inventory.json").read_text())
        inventory["n_retained_response_captures"] += 1
        (packet / "inventory.json").write_text(json.dumps(inventory))
    else:
        captures[0]["extracted_text"] += " changed"
    (packet / "captures.jsonl").write_text("".join(
        json.dumps(row, ensure_ascii=False) + "\n" for row in captures
    ))
    if defect != "file_hash":
        refresh_recovery_manifest(packet)
    out = tmp_path / "preview"
    with pytest.raises(ValueError, match=match):
        build_preview(coverage, history, out, recovery_path=packet / "inventory.json")
    assert not out.exists()


def test_preview_rejects_recovery_manifest_paths_outside_packet(tmp_path):
    coverage, history, packet, _ = recovery_fixture(tmp_path)
    manifest_path = packet / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["../coverage.json"] = sha256_file(coverage)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="escapes its packet"):
        build_preview(coverage, history, tmp_path / "preview",
                      recovery_path=packet / "inventory.json")

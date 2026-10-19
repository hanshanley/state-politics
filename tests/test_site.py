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
from state_politics.platforms.recovery import NATIVE_BLOCK_METHOD, build_inventory
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


def recovery_fixture(tmp_path, separator="\u2028", *, failed_text=None):
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
    (packet / "source.bin").write_text(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    ocr_text = f"Complete alternate OCR{separator}uncertified transcription"
    retained = {
        "capture_id": "packet:0", "state": "TX", "party": "D",
        "url": "https://example.org/platform", "stored_path": str(packet / "source.bin"),
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
         "stored_path": None, "source_sha256": None, "extracted_text": failed_text,
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


def write_source_packet(packet, rows, filename):
    packet.mkdir(exist_ok=True)
    (packet / filename).write_text("".join(
        json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows
    ))
    (packet / "manifest.json").write_text(json.dumps({"files": {
        filename: sha256_file(packet / filename),
    }}))


def successor_fixture(
    tmp_path, separator="\u2028", *, failed_text=None, kind="docx_main_document",
):
    coverage, history, baseline, original = recovery_fixture(
        tmp_path, separator, failed_text=failed_text
    )
    source_packet = tmp_path / "additional"
    source_packet.mkdir()
    extension = "pdf" if kind == "pdf_native_blocks" else "docx"
    body = source_packet / f"source.{extension}"
    body.write_bytes(b"Retained source bytes for source-binding fixture")
    source = {
        "capture_id": "additional:0", "state": "TX", "party": "D",
        "url": f"https://example.org/template.{extension}", "ok": True,
        "stored_path": str(body), "content_sha256": sha256_file(body),
        "content_bytes": body.stat().st_size, "extracted_text": "",
        "text_sha256": hashlib.sha256(b"").hexdigest(),
        "operative_platform_status": "unresolved",
        "training_admission": False, "analytical_admission": False,
    }
    write_source_packet(source_packet, [source], "captures.jsonl")
    text = f"Native paragraphs\u202d{separator}<script>literal template, not executed</script>"
    alternate = {
        "capture_id": source["capture_id"], "state": "TX", "party": "D",
        "source_sha256": source["content_sha256"],
        "extraction_method": "stdlib_zipfile_elementtree_word_document_xml_paragraphs",
        "extracted_text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "training_admission": False, "analytical_admission": False,
    }
    if kind == "pdf_native_blocks":
        alternate.update({
            "extraction_method": NATIVE_BLOCK_METHOD, "page_count": 37,
            "visually_checked_pages": [3], "reading_order_certified": False,
        })
    derivative = tmp_path / "docx-alternative"
    write_source_packet(derivative, [alternate], "extractions.jsonl")
    return coverage, history, baseline, original, source_packet, derivative, source, alternate


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085"])
@pytest.mark.parametrize("failed_text", [None, ""])
@pytest.mark.parametrize("kind", ["docx_main_document", "pdf_native_blocks"])
def test_successor_preserves_sources_failures_and_typed_derivatives(
    tmp_path, separator, failed_text, kind,
):
    coverage, history, baseline, original, sources, derivative, source, alt = successor_fixture(
        tmp_path, separator, failed_text=failed_text, kind=kind,
    )
    old_bytes = {name: (baseline / name).read_bytes() for name in (
        "inventory.json", "manifest.json", "captures.jsonl", "organizations.csv",
    )}
    packet = tmp_path / "successor"
    result = build_inventory(
        baseline / "inventory.json", [sources / "captures.jsonl"],
        [(kind, derivative / "extractions.jsonl")], packet,
    )
    assert result["n_selected_capture_attempts"] == 4
    assert result["n_retained_response_captures"] == 3
    assert result["n_failed_retrieval_attempts"] == 1
    assert result["n_distinct_response_body_hashes"] == 2
    assert result["n_distinct_bodies_with_alternate_ocr"] == 1
    assert result["n_distinct_bodies_with_docx_main_document"] == (kind == "docx_main_document")
    assert result["n_distinct_bodies_with_pdf_native_blocks"] == (kind == "pdf_native_blocks")
    assert result["analysis_cutoff"] is None
    assert len(result["rows"]) == 100
    out = tmp_path / "preview"
    build_preview(coverage, history, out, recovery_path=packet / "inventory.json")
    captures = json.loads((out / "evidence/recovery-TX-D.json").read_text())
    assert len(captures) == 4
    for row, prior in zip(captures[:3], original, strict=True):
        for key, value in prior.items():
            if key != "alternate_ocr":
                assert row[key] == value
    assert captures[0]["alternate_extractions"][0]["kind"] == "ocr"
    assert captures[-1]["extracted_text"] == ""
    assert captures[-1]["alternate_extractions"][0]["kind"] == kind
    assert captures[-1]["alternate_extractions"][0]["extracted_text"] == alt["extracted_text"]
    assert captures[-1]["input_disposition"] == source
    assert captures[-1]["alternate_extractions"][0]["input_disposition"] == alt
    with gzip.open(out / "downloads/recovery_captures.jsonl.gz", "rb") as handle:
        assert handle.read() == (packet / "captures.jsonl").read_bytes()
    assert all((baseline / name).read_bytes() == value for name, value in old_bytes.items())
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        build_inventory(baseline / "inventory.json", [], [], packet)


@pytest.mark.parametrize("field,value", [
    ("page_count", 0),
    ("visually_checked_pages", [38]),
    ("visually_checked_pages", [3, 3]),
    ("visually_checked_pages", [True]),
    ("reading_order_certified", True),
])
def test_native_blocks_reject_invalid_review_scope_before_output(tmp_path, field, value):
    _, _, baseline, _, sources, derivative, _, alt = successor_fixture(
        tmp_path, kind="pdf_native_blocks",
    )
    alt[field] = value
    write_source_packet(derivative, [alt], "extractions.jsonl")
    out = tmp_path / "successor"
    with pytest.raises(ValueError, match="uncertified review scope"):
        build_inventory(
            baseline / "inventory.json", [sources / "captures.jsonl"],
            [("pdf_native_blocks", derivative / "extractions.jsonl")], out,
        )
    assert not out.exists()


@pytest.mark.parametrize("kind", ["ocr", "docx_main_document"])
def test_native_block_method_cannot_be_mislabeled(tmp_path, kind):
    _, _, baseline, _, sources, derivative, _, _ = successor_fixture(
        tmp_path, kind="pdf_native_blocks",
    )
    out = tmp_path / "successor"
    with pytest.raises(ValueError, match="kind/method mismatch"):
        build_inventory(
            baseline / "inventory.json", [sources / "captures.jsonl"],
            [(kind, derivative / "extractions.jsonl")], out,
        )
    assert not out.exists()


def test_preview_revalidates_native_review_scope(tmp_path):
    coverage, history, baseline, _, sources, derivative, _, _ = successor_fixture(
        tmp_path, kind="pdf_native_blocks",
    )
    packet = tmp_path / "successor"
    build_inventory(
        baseline / "inventory.json", [sources / "captures.jsonl"],
        [("pdf_native_blocks", derivative / "extractions.jsonl")], packet,
    )
    with (packet / "captures.jsonl").open() as handle:
        captures = [json.loads(line) for line in handle]
    captures[-1]["alternate_extractions"][0]["input_disposition"]["visually_checked_pages"] = [38]
    write_source_packet(packet, captures, "captures.jsonl")
    refresh_recovery_manifest(packet)
    out = tmp_path / "preview"
    with pytest.raises(ValueError, match="uncertified review scope"):
        build_preview(coverage, history, out, recovery_path=packet / "inventory.json")
    assert not out.exists()


def test_preview_retains_legacy_v2_inventory_support(tmp_path):
    coverage, history, baseline, _, sources, derivative, _, _ = successor_fixture(tmp_path)
    packet = tmp_path / "successor"
    inventory = build_inventory(
        baseline / "inventory.json", [sources / "captures.jsonl"],
        [("docx_main_document", derivative / "extractions.jsonl")], packet,
    )
    inventory["schema"] = "bounded_recovery_inventory_v2"
    del inventory["n_distinct_bodies_with_pdf_native_blocks"]
    for row in inventory["rows"]:
        del row["n_distinct_bodies_with_pdf_native_blocks"]
    (packet / "inventory.json").write_text(json.dumps(inventory))
    with (packet / "organizations.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(inventory["rows"][0]))
        writer.writeheader()
        writer.writerows(inventory["rows"])
    refresh_recovery_manifest(packet)
    result = build_preview(
        coverage, history, tmp_path / "preview", recovery_path=packet / "inventory.json",
    )
    assert result["recovery_capture_attempts"] == 4


@pytest.mark.parametrize("defect,match", [
    ("source_body", "body hash"),
    ("source_bytes", "byte count"),
    ("source_cutoff", "analytical cutoff"),
    ("parent", "matching source capture"),
    ("binding", "source binding"),
    ("text", "source/text hash"),
    ("admission", "analytical admission"),
    ("unknown_kind", "unknown recovery alternate"),
    ("kind_mismatch", "kind/method mismatch"),
    ("duplicate_input", "duplicate recovery capture"),
])
def test_successor_rejects_bad_source_or_alternate_before_writing(tmp_path, defect, match):
    _, _, baseline, _, sources, derivative, source, alt = successor_fixture(tmp_path)
    kind = "docx_main_document"
    paths = [sources / "captures.jsonl"]
    if defect == "source_body":
        Path(source["stored_path"]).write_bytes(b"Changed raw source")
        source["content_bytes"] = Path(source["stored_path"]).stat().st_size
    elif defect == "source_bytes":
        source["content_bytes"] += 1
    elif defect == "source_cutoff":
        source["analysis_cutoff"] = "2026-10-18"
    elif defect == "parent":
        alt["capture_id"] = "missing:0"
    elif defect == "binding":
        alt["source_sha256"] = "b" * 64
    elif defect == "text":
        alt["extracted_text"] += " changed"
    elif defect == "admission":
        alt["analytical_admission"] = True
    elif defect == "unknown_kind":
        kind = "topic_predictions"
    elif defect == "kind_mismatch":
        kind = "ocr"
    elif defect == "duplicate_input":
        paths *= 2
    write_source_packet(sources, [source], "captures.jsonl")
    write_source_packet(derivative, [alt], "extractions.jsonl")
    out = tmp_path / "successor"
    with pytest.raises(ValueError, match=match):
        build_inventory(
            baseline / "inventory.json", paths,
            [(kind, derivative / "extractions.jsonl")], out,
        )
    assert not out.exists()


@pytest.mark.parametrize("defect,match", [
    ("body", "body hash"),
    ("bytes", "byte count"),
    ("alternate_kind", "unknown recovery alternate"),
    ("alternate_method", "kind/method mismatch"),
    ("alternate_binding", "source/text hash"),
    ("alternate_text", "source/text hash"),
    ("alternate_admission", "analytical admission"),
    ("alternate_identity", "duplicate recovery alternate"),
    ("alternate_on_failure", "source/text hash"),
    ("cutoff", "analytical cutoff"),
])
def test_preview_revalidates_typed_inventory_before_output(tmp_path, defect, match):
    coverage, history, baseline, _, sources, derivative, _, _ = successor_fixture(tmp_path)
    packet = tmp_path / "successor"
    build_inventory(
        baseline / "inventory.json", [sources / "captures.jsonl"],
        [("docx_main_document", derivative / "extractions.jsonl")], packet,
    )
    with (packet / "captures.jsonl").open() as handle:
        captures = [json.loads(line) for line in handle]
    row = captures[-1]
    alt = row["alternate_extractions"][0]
    if defect == "body":
        Path(row["stored_path"]).write_bytes(b"Changed raw source")
    elif defect == "bytes":
        row["source_bytes"] += 1
    elif defect == "alternate_kind":
        alt["kind"] = "topic_predictions"
    elif defect == "alternate_method":
        alt["kind"] = "ocr"
    elif defect == "alternate_binding":
        alt["source_sha256"] = "b" * 64
    elif defect == "alternate_text":
        alt["extracted_text"] += " changed"
    elif defect == "alternate_admission":
        alt["training_admission"] = True
    elif defect == "alternate_identity":
        row["alternate_extractions"].append(alt)
    elif defect == "alternate_on_failure":
        captures[2]["alternate_extractions"] = [alt]
    elif defect == "cutoff":
        row["analysis_cutoff"] = "2026-10-18"
    (packet / "captures.jsonl").write_text("".join(
        json.dumps(row, ensure_ascii=False) + "\n" for row in captures
    ))
    refresh_recovery_manifest(packet)
    out = tmp_path / "preview"
    with pytest.raises(ValueError, match=match):
        build_preview(coverage, history, out, recovery_path=packet / "inventory.json")
    assert not out.exists()


def test_successor_requires_the_actual_fifty_state_major_party_pairs(tmp_path):
    _, _, baseline, _ = recovery_fixture(tmp_path)
    registry = yaml.safe_load((ROOT / "conf/party_registry.yml").read_text())
    registry["organizations"][0]["state"] = "ZZ"
    path = tmp_path / "registry.yml"
    path.write_text(yaml.safe_dump(registry))
    with pytest.raises(ValueError, match="100 unique organizations"):
        build_inventory(
            baseline / "inventory.json", [], [], tmp_path / "successor", registry=path,
        )
    assert not (tmp_path / "successor").exists()


@pytest.mark.parametrize("difference", ["party", "body"])
def test_successor_reuses_inherited_alternatives_only_for_same_organization_and_body(
    tmp_path, difference,
):
    _, _, baseline, _, sources, derivative, source, _ = successor_fixture(tmp_path)
    first = tmp_path / "first-successor"
    build_inventory(
        baseline / "inventory.json", [sources / "captures.jsonl"],
        [("docx_main_document", derivative / "extractions.jsonl")], first,
    )
    repeat = tmp_path / "repeat"
    different = {**source, "capture_id": "repeat:1", "party": "R"}
    if difference == "body":
        other = tmp_path / "other.docx"
        other.write_bytes(b"Different retained source")
        different.update({
            "party": "D", "stored_path": str(other),
            "content_sha256": sha256_file(other), "content_bytes": other.stat().st_size,
        })
    write_source_packet(repeat, [
        {**source, "capture_id": "repeat:0"},
        different,
    ], "captures.jsonl")
    second = tmp_path / "second-successor"
    build_inventory(first / "inventory.json", [repeat / "captures.jsonl"], [], second)
    with (second / "captures.jsonl").open() as handle:
        rows = [json.loads(line) for line in handle]
    assert rows[-2]["alternate_extractions"] == rows[-3]["alternate_extractions"]
    assert rows[-2]["alternate_extractions"][0]["kind"] == "docx_main_document"
    assert rows[-1]["alternate_extractions"] == []
    assert rows[-2]["extracted_text"] == ""
    assert rows[-2]["input_disposition"]["capture_id"] == "repeat:0"


def test_successor_rejects_conflicting_inherited_alternative_identities(tmp_path):
    _, _, baseline, _, sources, derivative, source, _ = successor_fixture(tmp_path)
    write_source_packet(sources, [
        source, {**source, "capture_id": "additional:1"},
    ], "captures.jsonl")
    first = tmp_path / "first-successor"
    build_inventory(
        baseline / "inventory.json", [sources / "captures.jsonl"],
        [("docx_main_document", derivative / "extractions.jsonl")], first,
    )
    capture_path = first / "captures.jsonl"
    rows = [json.loads(line) for line in capture_path.open()]
    rows[-1]["alternate_extractions"][0] = {
        **rows[-1]["alternate_extractions"][0], "extracted_text": "Conflicting transcription",
        "text_sha256": hashlib.sha256(b"Conflicting transcription").hexdigest(),
    }
    capture_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest = json.loads((first / "manifest.json").read_text())
    manifest["files"]["captures.jsonl"] = sha256_file(capture_path)
    (first / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="inconsistent recovery alternate extraction identity"):
        build_inventory(first / "inventory.json", [], [], tmp_path / "second-successor")
    assert not (tmp_path / "second-successor").exists()

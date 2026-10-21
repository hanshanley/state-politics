"""Focused offline inventory, provenance and non-admission regressions."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from state_politics.platforms import study_evidence as evidence
from state_politics.provenance import sha256_file


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n")


def seal(root):
    write_json(root / "manifest.json", {
        "files": {p.name: sha256_file(p) for p in root.iterdir()
                  if p.is_file() and p.name != "manifest.json"},
    })


@pytest.fixture
def packet(request):
    work = Path(request.config.rootpath) / "data/processed/platform-evidence-test-work"
    root = work / uuid4().hex
    root.mkdir(parents=True)
    source = root / "source"
    source.mkdir()
    text = "Amended March 9, 2024\nUnchanged text\u2028with a native separator."
    raw = source / "body.bin"
    raw.write_bytes(b"frozen source")
    digest = sha256_file(raw)
    captures = [{
        "capture_id": "fixture:0", "state": "AK", "party": "D",
        "url": "https://example.invalid/2026/not-a-date",
        "stored_path": str(raw), "source_sha256": digest,
        "source_bytes": raw.stat().st_size, "retrieval_status": "response_retained",
        "extraction_method": "fixture", "extracted_text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "input_disposition": {"state": "AK", "party": "D"},
        "operative_platform_status": "unresolved", "analysis_cutoff": None,
        "training_admission": False, "analytical_admission": False,
        "alternate_extractions": [],
    }, {
        "capture_id": "fixture:1", "state": "AL", "party": "R",
        "url": "https://example.invalid/2024/failed",
        "stored_path": None, "source_sha256": None, "source_bytes": None,
        "retrieval_status": "retrieval_failed", "extraction_method": "fixture",
        "extracted_text": None, "text_sha256": None, "input_disposition": {},
        "operative_platform_status": "unresolved", "analysis_cutoff": None,
        "training_admission": False, "analytical_admission": False,
        "alternate_extractions": [],
    }]
    (source / "captures.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in captures))
    zero_alternatives = {
        "n_distinct_bodies_with_alternate_ocr": 0,
        "n_distinct_bodies_with_docx_main_document": 0,
        "n_distinct_bodies_with_pdf_native_blocks": 0,
    }
    rows = []
    for state, party in sorted(evidence.EXPECTED):
        retained = int((state, party) == ("AK", "D"))
        failed = int((state, party) == ("AL", "R"))
        rows.append({
            "state": state, "party": party, "n_selected_capture_attempts": retained + failed,
            "n_retained_response_captures": retained, "n_failed_retrieval_attempts": failed,
            "n_distinct_response_body_hashes": retained, **zero_alternatives,
            "operative_platform_status": "unresolved",
            "training_admission": False, "analytical_admission": False,
        })
    with (source / "organizations.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(source / "inventory.json", {
        "schema": "bounded_recovery_inventory_v3", "analysis_cutoff": None,
        "expected_organizations": 100, "n_selected_capture_attempts": 2,
        "n_retained_response_captures": 1, "n_failed_retrieval_attempts": 1,
        "n_distinct_response_body_hashes": 1, "n_repeated_body_hash_groups": 0,
        "n_organizations_with_retained_responses": 1, **zero_alternatives, "rows": rows,
    })
    registry = root / "registry.yml"
    registry.write_text(yaml.safe_dump({"organizations": [
        {"state": state, "party": party, "name": f"{state}-{party}"}
        for state, party in sorted(evidence.EXPECTED)
    ]}))
    caucus = root / "caucus.yml"
    caucus.write_text(yaml.safe_dump({"sources": [{
        "state": "KY", "party": "R", "year": 2024,
        "institution": "Fixture legislative caucus", "document_type": "caucus_agenda",
        "urls": ["https://example.invalid/caucus"],
    }]}))
    modern = source / "modern.parquet"
    pq.write_table(pa.Table.from_pylist([{
        "state": "AK", "party": "D", "url": captures[0]["url"],
        "sha256": digest, "text": text, "year": 2026, "stored_path": str(raw),
    }]), modern)
    seal(source)
    review_root = root / "reviews"
    review_root.mkdir()
    review = review_root / "reviews.jsonl"
    write_json(review, {
        "capture_id": "fixture:0", "source_sha256": digest,
        "text_sha256": captures[0]["text_sha256"], "complete_source_text": text,
        "reviewer": "assistant", "source_reported_date": "2024-03-09",
        "evidence_span": {"start": 0, "end": len("Amended March 9, 2024\n"),
                          "exact_text": "Amended March 9, 2024\n"},
    })
    seal(review_root)
    historical = root / "historical.parquet"
    pq.write_table(pa.Table.from_pylist([{
        "state": "AK", "party": "D", "party_raw": "D", "year": 1968,
        "member": "AK/1968.txt", "sha256": digest, "text": "Historical retained text",
    }]), historical)
    options = {
        "baseline": source / "inventory.json", "recovery": source / "inventory.json",
        "registry": registry, "caucus_registry": caucus,
        "modern_tables": [modern], "historical": historical, "review_paths": [review],
        "caucus_table": root / "missing-caucus.parquet",
    }
    yield root, options
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    root.rmdir()


def test_actual_inventory_accounting_text_and_non_admission(packet):
    root, options = packet
    result = evidence.build(root / "out", **options)
    records = evidence._jsonl(root / "out/records.jsonl")
    organizations = evidence._jsonl(root / "out/organizations.jsonl")
    assert len(organizations) == 100
    assert sum(row["n_evidence_records"] == 0 for row in organizations) == 97
    assert len(records) == result["n_evidence_records"] == 5
    assert sum(row["n_evidence_records"] for row in organizations) == 5
    capture = next(r for r in records if r["record_id"] == "capture:fixture:0")
    assert "\u2028" in capture["extracted_text"]
    assert capture["cycle_date_dispositions"] == ["source_observed_2023_2024_candidate"]
    table = next(r for r in records if r["record_kind"] == "frozen_modern_table_view")
    assert table["metadata_year_disposition"] == "later_metadata_hint_not_a_substitute"
    assert table["cycle_date_dispositions"] == ["source_observed_2023_2024_candidate"]
    failed = next(r for r in records if r["record_id"] == "capture:fixture:1")
    assert failed["extracted_text"] is None
    assert failed["cycle_date_dispositions"] == ["undated_candidate"]
    caucus = next(r for r in records if r["record_kind"] == "supplementary_caucus")
    assert caucus["institution_type"] == "legislative_caucus"
    assert caucus["extracted_text"] is None
    assert caucus["availability"] == "registry_only_text_unavailable"
    assert result["unavailable_inputs"] == [str(options["caucus_table"])]
    assert all(r["analytical_admission"] is False for r in records)
    assert all(r["cycle_applicability"] == "unresolved" for r in records)
    assert result["files"]["records.jsonl"] == sha256_file(root / "out/records.jsonl")
    with pytest.raises(FileExistsError):
        evidence.build(root / "out", **options)


@pytest.mark.parametrize(("value", "band"), [
    ("2022-12-31", "older_applicability_unresolved"),
    ("2023", "source_observed_2023_2024_candidate"),
    ("2024-12", "source_observed_2023_2024_candidate"),
    ("2025-01-01", "later_candidate_not_a_cycle_substitute"),
])
def test_structured_source_date_bands(value, band):
    assert evidence.date_band(value) == band


@pytest.mark.parametrize("value", ["2024-02-30", "2024junk", "24", "2024-1", True])
def test_malformed_source_dates_fail(value):
    with pytest.raises(ValueError):
        evidence.date_band(value)


def test_retained_browser_year_strings_remain_metadata_only():
    record = evidence._base("browser", {"state": "WA", "party": "D"}, "recovery_capture", {})
    evidence._year(record, "2024")
    assert record["metadata_year_disposition"] == "2023_2024_metadata_hint_not_date_evidence"
    assert record["source_observed_dates"] == []
    assert record["cycle_date_dispositions"] == ["undated_candidate"]


def test_filtered_empty_table_view_does_not_replace_full_capture_text(packet):
    root, options = packet
    modern = options["modern_tables"][0]
    rows = pq.read_table(modern).to_pylist()
    rows[0].update(text="", confirmed=False, reason="retained automated filter rejection")
    pq.write_table(pa.Table.from_pylist(rows), modern)
    seal(modern.parent)
    evidence.build(root / "out", **options)
    records = evidence._jsonl(root / "out/records.jsonl")
    table = next(r for r in records if r["record_kind"] == "frozen_modern_table_view")
    capture = next(r for r in records if r["record_id"] == "capture:fixture:0")
    assert table["extracted_text"] == ""
    assert table["text_join_disposition"] == (
        "empty_filtered_table_view_full_capture_text_retained")
    assert "Unchanged text" in capture["extracted_text"]


def test_failed_table_attempt_keeps_null_body_and_distinct_empty_text(packet):
    root, options = packet
    modern = options["modern_tables"][0]
    rows = pq.read_table(modern).to_pylist()
    rows.append({
        "state": "AL", "party": "R", "url": "https://example.invalid/2024/failed",
        "sha256": None, "text": "", "year": None, "stored_path": None,
        "confirmed": False, "reason": "fetch failed",
    })
    # Explicit schema is needed because the first row has no filter disposition.
    rows[0].update(confirmed=True, reason="fixture retained text")
    pq.write_table(pa.Table.from_pylist(rows), modern)
    seal(modern.parent)
    evidence.build(root / "out", **options)
    table = next(r for r in evidence._jsonl(root / "out/records.jsonl")
                 if r["record_kind"] == "frozen_modern_table_view" and r["party"] == "R")
    assert table["text_join_disposition"] == "failed_capture_no_retained_body"
    assert table["source_sha256"] is None
    assert table["parent_capture_ids"] == ["fixture:1"]


@pytest.mark.parametrize("failure", ["identity", "join", "duplicate", "span", "manifest"])
def test_substantive_failures_keep_incomplete_manifest(packet, failure):
    root, options = packet
    modern = options["modern_tables"][0]
    if failure in {"identity", "join", "duplicate"}:
        rows = pq.read_table(modern).to_pylist()
        if failure == "identity":
            rows[0]["party"] = "X"
        elif failure == "join":
            rows[0]["text"] = "Changed source text"
        else:
            rows.append(rows[0])
        pq.write_table(pa.Table.from_pylist(rows), modern)
        seal(modern.parent)
    elif failure == "span":
        path = options["review_paths"][0]
        row = evidence._json(path)
        row["evidence_span"]["start"] = 1
        write_json(path, row)
        seal(path.parent)
    else:
        modern.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        evidence.build(root / "failed", **options)
    manifest = evidence._json(root / "failed/manifest.json")
    assert manifest["status"] == "incomplete"
    assert manifest["error_type"] == "ValueError"
    assert manifest["inputs"]


def test_input_change_before_completion_fails(packet, monkeypatch):
    root, options = packet
    original = evidence.Inputs.stable

    def mutate_then_check(inputs):
        with options["registry"].open("a") as handle:
            handle.write("\n# changed after consumption\n")
        original(inputs)

    monkeypatch.setattr(evidence.Inputs, "stable", mutate_then_check)
    with pytest.raises(ValueError, match="input changed"):
        evidence.build(root / "changed", **options)
    assert evidence._json(root / "changed/manifest.json")["status"] == "incomplete"


def record_review_packet(root, options):
    modern = options["modern_tables"][0]
    rows = pq.read_table(modern).to_pylist()
    rows[0]["year"] = 2024
    pq.write_table(pa.Table.from_pylist(rows), modern)
    seal(modern.parent)
    base = root / "base"
    evidence.build(base, **options)
    selected = [r for r in evidence._jsonl(base / "records.jsonl")
                if r["metadata_year_disposition"] == "2023_2024_metadata_hint_not_date_evidence"]
    path = root / "record-reviews"
    path.mkdir()
    reviews = []
    for index, row in enumerate(selected):
        text = row["extracted_text"]
        full = f"{index}.txt" if text is not None else None
        if full is not None:
            (path / full).write_bytes(text.encode())
        reviews.append({
            "review_id": f"fixture-review:{index}", "record_id": row["record_id"],
            "state": row["state"], "party": row["party"],
            "source_sha256": row["source_sha256"], "original_text_sha256": row["text_sha256"],
            "reviewed_text_record_id": row["record_id"],
            "reviewed_text_sha256": row["text_sha256"], "full_text_path": full,
            "source_inventory_records_sha256": sha256_file(base / "records.jsonl"),
            "source_inventory_manifest_sha256": sha256_file(base / "manifest.json"),
            "operative_platform_status": "unresolved", "cycle_applicability": "unresolved",
            "reviewer_type": "assistant", "independent_certification": False, "human_gold": False,
            "training_admission": False, "analytical_admission": False,
            "source_date_claims": [{
                "kind": "source_stated_amendment", "value": "2024-03-09",
                "scope": "fixture_amendment", "use_for_cycle_date_band": True,
                "evidence_span": {"start": 0, "end": len("Amended March 9, 2024"),
                                  "exact_text": "Amended March 9, 2024"},
            }] if text is not None else [],
        })
    for name, values in (("reviews.jsonl", reviews), ("selected_records.jsonl", selected)):
        (path / name).write_text("".join(json.dumps(row) + "\n" for row in values))
    seal(path)
    manifest = evidence._json(path / "manifest.json")
    manifest.update(
        schema="platform_cycle_date_advisory_v1", status="complete_advisory_not_certification",
        input_records=str(base / "records.jsonl"),
        input_records_sha256=sha256_file(base / "records.jsonl"),
        input_inventory_manifest_sha256=sha256_file(base / "manifest.json"),
        expected_selected_records=len(selected),
    )
    write_json(path / "manifest.json", manifest)
    return path / "reviews.jsonl"


def reseal_review(path):
    manifest = evidence._json(path.parent / "manifest.json")
    seal(path.parent)
    manifest["files"] = evidence._json(path.parent / "manifest.json")["files"]
    write_json(path.parent / "manifest.json", manifest)


def test_record_level_reviews_preserve_existing_reviews_and_unavailable_text(packet):
    root, options = packet
    path = record_review_packet(root, options)
    result = evidence.build(root / "successor", record_reviews=path, **options)
    records = evidence._jsonl(root / "successor/records.jsonl")
    original = {r["record_id"]: r for r in evidence._jsonl(root / "base/records.jsonl")}
    assert result["record_review_input"]["n_record_level_advisory_reviews"] == 2
    for row in records:
        assert row["advisory_reviews"] == original[row["record_id"]]["advisory_reviews"]
        assert row["extracted_text"] == original[row["record_id"]]["extracted_text"]
        if row.get("record_level_advisory_reviews"):
            assert row["cycle_applicability"] == "unresolved"
            assert row["analytical_admission"] is False
    caucus = next(r for r in records if r["record_kind"] == "supplementary_caucus")
    assert caucus["source_observed_dates"] == []
    assert caucus["extracted_text"] is None


@pytest.mark.parametrize("failure", [
    "span", "cover", "join", "omitted", "duplicate", "certification",
])
def test_record_review_corruptions_cannot_be_admitted(packet, failure):
    root, options = packet
    path = record_review_packet(root, options)
    rows = evidence._jsonl(path)
    row = next(r for r in rows if r["source_date_claims"])
    if failure == "span":
        row["source_date_claims"][0]["evidence_span"]["start"] += 1
    elif failure == "cover":
        row["source_date_claims"][0]["kind"] = "cover_year_not_adoption"
    elif failure == "join":
        row["reviewed_text_sha256"] = "0" * 64
    elif failure == "omitted":
        rows.remove(row)
    elif failure == "duplicate":
        rows.append(row)
    else:
        row["analytical_admission"] = True
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    reseal_review(path)
    with pytest.raises(ValueError):
        evidence.build(root / "rejected", record_reviews=path, **options)
    assert evidence._json(root / "rejected/manifest.json")["status"] == "incomplete"

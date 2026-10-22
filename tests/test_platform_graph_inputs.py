"""Offline recovery tests use exclusive fixture directories under ignored data/."""

from __future__ import annotations

import gzip
import json
import shutil
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from state_politics.platforms import graph_inputs as recovery
from state_politics.platforms.collect import CollectedDocument
from state_politics.provenance import sha256_file


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def jsonl(path, values):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in values),
                    encoding="utf-8")


@pytest.fixture
def packet(request):
    project = Path(request.config.rootpath)
    root = project / "data/processed/recovered-platform-graph-inputs-20261022-v1-work" / uuid4().hex
    source = root / "retained"
    downloads = root / "preview/downloads"
    source.mkdir(parents=True)
    downloads.mkdir(parents=True)
    text = "Full original platform text\u2028with separators and no source date."
    raw = source / "body.bin"
    raw.write_bytes(b"original source bytes")
    digest = sha256_file(raw)
    captures = []
    records = []

    def view(kind, identity, raw_row, origin, **extra):
        value = raw_row.get("text", raw_row.get("extracted_text"))
        row = {
            "source_type": "platform", "record_id": identity, "record_kind": kind,
            "state": raw_row["state"], "party": raw_row["party"], "origin": origin,
            "operative_platform_status": "unresolved", "cycle_applicability": "unresolved",
            "analysis_cutoff": None, "training_admission": False,
            "analytical_admission": False, "adoption_certified": False, "human_gold": False,
            "extracted_text": value, "text_sha256": recovery._digest_text(value),
            "source_sha256": raw_row.get("sha256", raw_row.get("source_sha256")),
            "retained_record": raw_row, "metadata_year_disposition": "unavailable",
            "cycle_date_dispositions": ["undated_candidate"], **extra,
        }
        records.append(row)
        return row

    for index, (state, party, status) in enumerate([
        ("AK", "D", True), ("AL", "R", False), ("AZ", "D", None)
    ]):
        retained = status is not None
        capture = {
            "capture_id": f"source:{index}", "state": state, "party": party,
            "url": f"https://example.invalid/{state}/2024",
            "packet": "source", "input_record_index": index,
            "stored_path": str(raw) if retained else None,
            "source_sha256": digest if retained else None,
            "source_bytes": raw.stat().st_size if retained else None,
            "retrieval_status": "response_retained" if retained else "retrieval_failed",
            "extraction_method": "retained_fixture",
            "extracted_text": text if retained else None,
            "text_sha256": recovery._digest_text(text) if retained else None,
            "passed_automated_content_filter": status,
            "input_disposition": {}, "alternate_extractions": [],
            "operative_platform_status": "unresolved", "analysis_cutoff": None,
            "training_admission": False, "analytical_admission": False,
        }
        captures.append(capture)
    alternate = {
        "extraction_id": "alternate:0", "kind": "docx_main_document",
        "extraction_method": "stdlib_zipfile_elementtree_word_document_xml_paragraphs",
        "state": "AK", "party": "D", "source_sha256": digest,
        "extracted_text": "Alternate extraction must not replace the original.",
        "text_sha256": recovery._digest_text("Alternate extraction must not replace the original."),
        "training_admission": False, "analytical_admission": False,
    }
    captures[0]["alternate_extractions"] = [alternate]
    capture_path = source / "captures.jsonl"
    jsonl(capture_path, captures)
    for i, row in enumerate(captures):
        view("recovery_capture", f"capture:{row['capture_id']}", row, {
            "path": str(capture_path), "sha256": sha256_file(capture_path), "record_index": i,
        }, capture_id=row["capture_id"], retrieval_status=row["retrieval_status"], url=row["url"])
    view("alternative_extraction", "extraction:alternate:0", alternate, records[0]["origin"],
         parent_capture_ids=["source:0"])
    original_rows = [
        asdict(CollectedDocument(
            state=c["state"], party=c["party"], url=c["url"], fetched_url=c["url"],
            source="live", doc_type="platform" if i == 0 else None,
            year=None if i == 0 else 2026, confirmed=i == 0,
            reason="accepted" if i == 0 else "rejected" if i == 1 else "fetch failed: offline",
            sha256=c["source_sha256"], text=text if i == 0 else "",
            stored_path=c["stored_path"], n_chars=len(text) if i < 2 else 0,
        )) for i, c in enumerate(captures)
    ]
    original = source / "platforms_2018_present.parquet"
    pq.write_table(pa.Table.from_pylist(original_rows), original)
    for i, row in enumerate(original_rows):
        view("frozen_modern_table_view", f"table:source:{i}", row, {
            "path": str(original), "sha256": sha256_file(original), "record_index": i,
        }, parent_capture_ids=[f"source:{i}"])
    # A second table is a repeated view of AK-D, not an independent platform.
    second = root / "second"
    second.mkdir()
    duplicate = second / "platforms_2018_present.parquet"
    pq.write_table(pa.Table.from_pylist(original_rows[:1]), duplicate)
    view("frozen_modern_table_view", "table:second:0", original_rows[0], {
        "path": str(duplicate), "sha256": sha256_file(duplicate), "record_index": 0,
    }, parent_capture_ids=["source:0"])
    historical = source / "historical.parquet"
    historical_rows = []
    for index, (state, party, name) in enumerate([
        ("AK", "D", "inside"), ("US", "other", "outside")
    ]):
        raw_row = {
            "state": state, "party": party, "text": "Historical unmodified text.", "year": 1968,
        }
        historical_rows.append(raw_row)
        view("historical_archive_view", f"historical:{name}", {
            **raw_row,
        }, {"path": str(historical), "sha256": None, "record_index": index},
             organization_scope="expected" if state == "AK" else "excluded_national_or_other_party")
    pq.write_table(pa.Table.from_pylist(historical_rows), historical)
    for row in records:
        if row["record_kind"] == "historical_archive_view":
            row["origin"]["sha256"] = sha256_file(historical)
    caucus_registry = source / "caucus.yml"
    caucus_raw = {
        "state": "KY", "party": "R", "institution": "Caucus, not committee",
        "document_type": "priority_agenda", "year": 2024,
        "urls": ["https://example.invalid/caucus"],
    }
    caucus_registry.write_text(yaml.safe_dump({"sources": [caucus_raw]}))
    view("supplementary_caucus", "caucus:KY:R", caucus_raw, {
        "path": str(caucus_registry), "sha256": sha256_file(caucus_registry), "record_index": 0,
    },
         availability="registry_only_text_unavailable", institution_type="legislative_caucus")
    exported = {}

    def seal_exports():
        for state, party in [*sorted(recovery.EXPECTED), ("outside", None)]:
            name = f"platform-{state}" + (f"-{party}" if party else "") + ".jsonl.gz"
            values = [r for r in records if (r["state"], r["party"]) == (state, party)]
            if party is None:
                values = [r for r in records
                          if (r["state"], r["party"]) not in recovery.EXPECTED]
            with gzip.open(downloads / name, "wt", encoding="utf-8") as handle:
                for row in values:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            exported[f"downloads/{name}"] = {
                "sha256": sha256_file(downloads / name), "bytes": (downloads / name).stat().st_size,
            }
        inputs = [{
            "path": str(p), "sha256": sha256_file(p), "bytes": p.stat().st_size,
            "role": "retained_fixture",
        } for p in (raw, capture_path, original, duplicate, historical, caucus_registry)
            if p.exists()]
        # Missing originals retain their original source pin in the real manifest.
        if not original.exists():
            inputs.append(original_pin)
        manifest = {
            "schema": "platform_study_evidence_v1",
            "status": "complete_evidence_inventory_not_scientific_admission",
            "files": {"records.jsonl": "frozen_original_inventory_hash"},
            "inputs": inputs, "n_evidence_records": len(records),
            "n_historical_outside_organization_scope": 1,
            "record_kind_counts": dict(Counter(r["record_kind"] for r in records)),
            "n_recovery_captures": 3, "n_retained_response_captures": 2,
            "n_failed_retrieval_attempts": 1,
        }
        dump(downloads / "platform_source_manifest.json", manifest)
        dump(downloads / "build_manifest.json", {
            "outputs": exported,
            "inputs": {"platform": {
                "manifest.json": sha256_file(downloads / "platform_source_manifest.json"),
                "records.jsonl": manifest["files"]["records.jsonl"],
            }},
            "counts": {"platform_evidence_views": len(records),
                       "platform_outside_organization_views": 1},
        })

    original_pin = {"path": str(original), "sha256": sha256_file(original),
                    "bytes": original.stat().st_size, "role": "retained_fixture"}
    seal_exports()
    yield {
        "root": root, "project": project, "records": records, "raw": raw,
        "original": original, "original_rows": original_rows,
        "preview": downloads.parent, "reseal": seal_exports,
    }
    shutil.rmtree(root)


def build(packet, **kwargs):
    return recovery.build(packet["root"] / "out", preview=packet["preview"],
                          root=packet["project"], plots=False, **kwargs)


def test_recovers_original_fields_without_conflating_views_or_caucus(packet):
    result = build(packet)
    out = packet["root"] / "out"
    assert result["counts"]["n_original_modern_rows"] == 4
    assert result["counts"]["n_original_modern_filter_accepted_rows"] == 2
    assert result["counts"]["n_capture_attempts"] == 3
    assert result["counts"]["n_distinct_retained_capture_body_hashes"] == 1
    assert result["counts"]["n_outside_organization_views"] == 1
    assert result["n_caucus_original_rows"] == 0
    assert result["n_caucus_registry_only_entries"] == 1
    assert not list(out.rglob("caucus_priorities.parquet"))
    recovered = out / "original_tables/retained/platforms_2018_present.parquet"
    assert recovered.read_bytes() == packet["original"].read_bytes()
    rows = pq.read_table(recovered).to_pylist()
    assert rows == packet["original_rows"]
    assert rows[0]["year"] is None and "\u2028" in rows[0]["text"]
    assert rows[1]["text"] == "" and rows[1]["n_chars"] > 0
    assert all(result[key] is False for key in recovery.APPROVALS)
    assert recovery.verify_packet(out)["n_original_rows_round_tripped"] == 4
    import csv

    with (out / "collection_status.csv").open(newline="") as handle:
        orgs = {(r["state"], r["party"]): r for r in csv.DictReader(handle)}
    assert len(orgs) == 100
    assert orgs["AK", "D"]["n_original_modern_table_rows"] == "2"
    assert orgs["AK", "D"]["n_distinct_response_body_hashes"] == "1"
    assert orgs["AZ", "D"]["modern_collection_status"] == "fetch_failed"
    assert orgs["AL", "R"]["modern_collection_status"] == "candidates_rejected"
    assert orgs["KY", "R"]["modern_collection_status"] == "not_in_retained_modern_tables"
    with pytest.raises(FileExistsError):
        build(packet)


def test_recovers_missing_parquet_from_complete_original_export_rows(packet):
    packet["original"].unlink()
    packet["reseal"]()
    result = build(packet)
    tables = {r["original_path"]: r for r in result["recovered_original_tables"]}
    assert tables[str(packet["original"])]["fidelity"].startswith("field_exact_reconstruction")
    assert pq.read_table(packet["root"] / "out" / tables[
        str(packet["original"])
    ]["output"]).to_pylist() == packet["original_rows"]


@pytest.mark.parametrize("fault", ["export", "body", "text_join", "approved", "row_index"])
def test_rejects_tampering_and_incomplete_original_tables(packet, fault):
    if fault == "export":
        path = packet["preview"] / "downloads/platform-AK-D.jsonl.gz"
        path.write_bytes(path.read_bytes() + b"tampering")
    elif fault == "body":
        packet["raw"].write_bytes(b"changed source")
    else:
        row = next(r for r in packet["records"]
                   if r["record_kind"] == "frozen_modern_table_view")
        if fault == "text_join":
            row["retained_record"]["text"] = "Substituted alternative"
            row["extracted_text"] = "Substituted alternative"
            row["text_sha256"] = recovery._digest_text(row["extracted_text"])
        elif fault == "approved":
            row["analytical_admission"] = True
        else:
            row["origin"]["record_index"] = 8
        packet["reseal"]()
    with pytest.raises(ValueError):
        build(packet)
    assert json.loads((packet["root"] / "out/manifest.json").read_text())["status"] == "incomplete"


def test_output_verification_detects_modified_chart_data(packet):
    build(packet)
    out = packet["root"] / "out"
    with (out / "collection_status.csv").open("a") as handle:
        handle.write("fabricated row\n")
    with pytest.raises(ValueError, match="hash/count"):
        recovery.verify_packet(out)


def test_produces_source_bound_plot_bundle(packet):
    result = recovery.build(packet["root"] / "out", preview=packet["preview"],
                            root=packet["project"], plots=True)
    files = result["files"]
    assert len([name for name in files if name.endswith(".png")]) == 3
    assert len([name for name in files if name.endswith(".svg")]) == 3
    assert not (packet["root"] / "out/.plot-cache").exists()
    assert recovery.verify_packet(packet["root"] / "out")["status"] == "verified"


def test_gap_status_precedence_does_not_invent_candidate_absence():
    def row(confirmed=False, reason="filter rejected"):
        return {"confirmed": confirmed, "reason": reason}

    assert recovery._collection_status([row(), row(reason="fetch failed: timeout")]) == (
        "candidates_partially_unresolved")
    assert recovery._collection_status([row(True), row(reason="fetch failed")]) == (
        "automated_filter_accepted")
    assert recovery._collection_status([]) == "not_in_retained_modern_tables"

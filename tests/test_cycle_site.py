"""Evidence-only mode retains original source strings and never promotes candidate admission."""

import gzip
import hashlib
import json
import os
import runpy
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as csv
import pyarrow.parquet as pq
import pytest

from state_politics.provenance import sha256_file
from state_politics.site_evidence import COHORTS, ORGANIZATIONS, ROOT, STATES, build_cycle_preview

SOURCE_TEXT = (
    'literal <script>window.EVIDENCE_INJECTED=true</script>'
    ' <img src=x onerror="window.EVIDENCE_INJECTED=true"> "quoted phrase"'
    "\u2028\u2029\nFull source ending; never truncated."
)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def write_jsonl(path, rows):
    path.write_text("".join(
        json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows
    ), encoding="utf-8")


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def repin(bundle, *, platform=False):
    manifest = json.loads((bundle / "manifest.json").read_text())
    if platform:
        manifest["files"] = {
            name: sha256_file(bundle / name) for name in ("records.jsonl", "organizations.jsonl")
        }
    else:
        manifest["artifacts"] = {
            name: {"sha256": sha256_file(bundle / name), "bytes": (bundle / name).stat().st_size}
            for name in (
                "report.json", "state_matrix.csv", "bill_evidence.parquet",
                "abstract_evidence.parquet", "candidate_metadata_views.parquet",
            )
        }
    write_json(bundle / "manifest.json", manifest)


@pytest.fixture
def cycle_bundle(tmp_path):
    metadata, platform = tmp_path / "metadata", tmp_path / "platform"
    metadata.mkdir()
    platform.mkdir()
    contexts, abstracts, views = [], [], []
    for index in range(14):
        state = "TX" if index < 12 else "CA" if index == 12 else "MA"
        context = {
            "bill_id": f"bill:{index}", "state": state, "identifier": f"HB {index}",
            "session_identifier": "2023", "title": f"{SOURCE_TEXT} title {index}",
            "cohort_scope": COHORTS[0 if index < 12 else index - 11],
            "n_indexed_native_views": None if state == "MA" else int(state == "CA"),
            "n_nonempty_abstract_records": 2 if index == 0 else 0,
            "n_distinct_abstract_texts": 2 if index == 0 else 0,
            "source_introduction_date": "", "source_filing_date": "2023-02-01",
            "native_introduction_date": None,
            "model_input_approved": False, "filing_time_text_certified": False,
            "analytical_admission": False,
        }
        contexts.append(context)
        for variant in range(2 if index == 0 else 1):
            abstract = None
            if index == 0:
                text = f"{SOURCE_TEXT} variant {variant}"
                abstract = {
                    "id": f"abstract:{variant}", "bill_id": context["bill_id"], "state": state,
                    "abstract": text, "note": f"{SOURCE_TEXT} note {variant}",
                    "abstract_sha256": digest(text),
                }
                abstracts.append(abstract)
            text = context["title"] + ("\n\n" + abstract["abstract"] if abstract else "")
            views.append({
                **{key: context[key] for key in (
                    "state", "identifier", "bill_id", "title", "session_identifier", "cohort_scope",
                )},
                "view_id": f"view:{index}:{variant}",
                "abstract_id": abstract["id"] if abstract else None,
                "abstract": abstract["abstract"] if abstract else None,
                "abstract_note": abstract["note"] if abstract else None, "text": text,
                "input_sha256": digest(text), "n_input_characters": len(text),
                "metadata_tier": "retained_abstract_unaligned" if abstract else "title_only",
                "multiple_abstract_variants": index == 0, "n_input_tokens": None,
                "n_discarded_tokens": None, "chunking_status": "not_tokenized",
                "model_input_approved": False, "filing_time_text_certified": False,
                "training_admission": False, "analytical_admission": False,
            })
    for name, rows in (
        ("bill_evidence", contexts), ("abstract_evidence", abstracts),
        ("candidate_metadata_views", views),
    ):
        pq.write_table(pa.Table.from_pylist(rows), metadata / f"{name}.parquet")
    matrix = []
    for state in sorted(STATES):
        rows = [row for row in contexts if row["state"] == state]
        counts = Counter(row["cohort_scope"] for row in rows)
        matrix.append({
            "state": state, "state_name": f"{state} {SOURCE_TEXT}" if state == "TX" else state,
            "n_retained_contexts_wider_history": 9877 if state == "ME" else len(rows),
            "n_cycle_evidence_candidate_contexts": len(rows),
            "n_filing_or_introduction_in_window": counts[COHORTS[0]],
            "n_native_only_scope_candidates": counts[COHORTS[1]],
            "n_description_only_scope_candidates": counts[COHORTS[2]],
            "n_cycle_metadata_candidate_views": sum(row["state"] == state for row in views),
            "n_cycle_contexts_with_nonempty_abstract": int(state == "TX"),
            "n_cycle_contexts_with_multiple_abstract_variants": int(state == "TX"),
            "n_cycle_contexts_with_indexed_native_text": int(state == "CA")
            if state in ("TX", "CA") else None,
        })
    csv.write_csv(pa.Table.from_pylist(matrix), metadata / "state_matrix.csv")
    write_json(metadata / "report.json", {
        "status": "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted",
        "n_cycle_contexts": 14, "n_cycle_abstract_records": 2,
        "n_metadata_candidate_views_not_bills": 15,
        "n_cycle_contexts_with_nonempty_abstract": 1,
        "n_cycle_contexts_with_multiple_abstract_variants": 1,
        "cohort_scope_counts": dict(Counter(row["cohort_scope"] for row in contexts)),
        "model_input_approved": False, "analytical_admission": False,
    })
    write_json(metadata / "manifest.json", {
        "schema_version": 1,
        "status": "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted",
        "inputs_unchanged": True, "model_input_approved": False, "analytical_admission": False,
    })
    repin(metadata)
    records = []
    for index in range(13):
        text = None if index == 11 else f"{SOURCE_TEXT} platform {index}"
        records.append({
            "record_id": f"record:{index}", "state": "TX" if index < 12 else "US",
            "party": "D", "record_kind": "recovery_capture",
            "extracted_text": text, "text_sha256": digest(text) if text else None,
            "source_sha256": None, "url": "javascript:window.EVIDENCE_INJECTED=true",
            "origin": {"path": "/unserved/original.jsonl", "sha256": "b" * 64},
            "retained_record": {"text": text, "unverified_claim": SOURCE_TEXT},
            "source_path": "/unserved/source.pdf", "advisory_reviews": [],
            "source_observed_dates": [], "retained_metadata_year": None,
            "metadata_year_disposition": "unavailable", "cycle_applicability": "unresolved",
            "operative_platform_status": "unresolved", "analysis_cutoff": None,
            "training_admission": False, "analytical_admission": False,
            "adoption_certified": False, "human_gold": False,
            "cycle_date_dispositions": [
                "source_observed_2023_2024_candidate" if index == 0 else "undated_candidate",
            ],
            **({"organization_scope": "excluded_national_or_other_party"} if index == 12 else {}),
        })
    orgs = []
    for state, party in sorted(ORGANIZATIONS):
        rows = [row for row in records if (row["state"], row["party"]) == (state, party)]
        orgs.append({
            "state": state, "party": party, "name": f"{state} / {party} {SOURCE_TEXT}",
            "n_evidence_records": len(rows),
            "n_retained_nonempty_text_views": sum(bool(row["extracted_text"]) for row in rows),
            "record_kind_counts": dict(Counter(row["record_kind"] for row in rows)),
            "cycle_date_counts": dict(Counter(
                date for row in rows for date in row["cycle_date_dispositions"]
            )),
            "cycle_applicability": "unresolved", "operative_platform_status": "unresolved",
            "training_admission": False, "analytical_admission": False,
        })
    write_jsonl(platform / "records.jsonl", records)
    write_jsonl(platform / "organizations.jsonl", orgs)
    write_json(platform / "manifest.json", {
        "schema": "platform_study_evidence_v1",
        "status": "complete_evidence_inventory_not_scientific_admission",
        "scientific_certification": "not_performed", "analysis_cutoff": None,
        "study_start": "2023-01-01", "study_end": "2024-12-31",
        "n_evidence_records": 13, "n_organization_rows": 100, "expected_organizations": 100,
        "n_historical_outside_organization_scope": 1,
        "record_kind_counts": {"recovery_capture": 13},
        "cycle_date_counts": {"source_observed_2023_2024_candidate": 1, "undated_candidate": 12},
    })
    repin(platform, platform=True)
    return metadata, platform, contexts, abstracts, views, records


def test_cycle_export_reconciles_and_downloads_full_sources_and_unknowns(cycle_bundle, tmp_path):
    metadata, platform, contexts, abstracts, views, records = cycle_bundle
    source_pins = {
        str(path): sha256_file(path) for directory in (metadata, platform)
        for path in directory.iterdir()
    }
    out = tmp_path / "preview"
    manifest = build_cycle_preview(metadata, platform, out)
    assert manifest["publication_status"] == "local_only_unpublished"
    assert manifest["counts"]["states"] == 50
    assert manifest["counts"]["organizations"] == 100
    assert manifest["counts"]["n_cycle_contexts"] == 14
    assert manifest["counts"]["n_metadata_candidate_views_not_bills"] == 15
    assert manifest["counts"]["cohort_scope_counts"] == dict(Counter(
        row["cohort_scope"] for row in contexts
    ))
    assert len(list((out / "evidence").glob("bills-*.jsonl"))) == 50
    assert len(list((out / "evidence").glob("platform-*.jsonl"))) == 101
    exported = []
    for path in sorted((out / "downloads").glob("bills-*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            exported.extend(json.loads(line) for line in handle)
    assert len(exported) == len(views)
    original = {row["view_id"]: row for row in views}
    for row in exported:
        assert {key: row[key] for key in original[row["view_id"]]} == original[row["view_id"]]
        assert row["source_bundle_manifest_sha256"] == sha256_file(metadata / "manifest.json")
        assert row["model_input_approved"] is row["training_admission"] is False
        assert row["n_input_tokens"] is None
    assert {row["source_abstract"]["id"]: row["source_abstract"] for row in exported
            if row["source_abstract"]} == {row["id"]: row for row in abstracts}
    assert next(row for row in exported if row["state"] == "MA")[
        "bill_context"
    ]["n_indexed_native_views"] is None
    assert next(row for row in exported if row["state"] == "TX")[
        "bill_context"
    ]["n_indexed_native_views"] == 0
    platform_export = []
    for path in sorted((out / "downloads").glob("platform-*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            platform_export.extend(json.loads(line) for line in handle)
    assert {row["record_id"]: {k: v for k, v in row.items() if k != "source_type"}
            for row in platform_export} == {row["record_id"]: row for row in records}
    assert all(row["human_gold"] is row["analytical_admission"] is False for row in platform_export)
    assert json.loads((out / "downloads/metadata_source_manifest.json").read_text()) == json.loads(
        (metadata / "manifest.json").read_text()
    )
    document = (out / "index.html").read_text()
    assert document.count('<tr data-state="') == 150
    assert "<script>window.EVIDENCE_INJECTED" not in document
    assert "&lt;script&gt;window.EVIDENCE_INJECTED" in document
    assert "@@" not in document
    assert "Unknown (not registered)" in document
    assert "relative to 2 registered state packets" in document
    assert len(list(out.rglob("*.pdf"))) == 0
    for relative, pin in manifest["outputs"].items():
        assert sha256_file(out / relative) == pin["sha256"]
    assert all(sha256_file(Path(path)) == digest for path, digest in source_pins.items())


@pytest.mark.parametrize("defect", [
    "hash", "missing", "admission", "unknown_as_zero", "matrix_count", "duplicate_view",
    "missing_abstract", "platform_count", "platform_admission", "platform_text", "platform_dates",
])
def test_cycle_preview_rejects_bad_bundles_before_output(cycle_bundle, tmp_path, defect):
    metadata, platform, *_ = cycle_bundle
    if defect == "hash":
        (metadata / "report.json").write_text("{}")
    elif defect == "missing":
        (metadata / "abstract_evidence.parquet").unlink()
    elif defect in ("admission", "duplicate_view", "missing_abstract"):
        path = metadata / "candidate_metadata_views.parquet"
        rows = pq.read_table(path).to_pylist()
        if defect == "admission":
            rows[0]["model_input_approved"] = True
        elif defect == "duplicate_view":
            rows[1]["view_id"] = rows[0]["view_id"]
        else:
            rows[0]["abstract_id"] = "missing"
        pq.write_table(pa.Table.from_pylist(rows), path)
        repin(metadata)
    elif defect == "unknown_as_zero":
        path = metadata / "bill_evidence.parquet"
        rows = pq.read_table(path).to_pylist()
        rows[-1]["n_indexed_native_views"] = 0
        pq.write_table(pa.Table.from_pylist(rows), path)
        repin(metadata)
    elif defect == "matrix_count":
        path = metadata / "state_matrix.csv"
        rows = csv.read_csv(path).to_pylist()
        rows[0]["n_cycle_evidence_candidate_contexts"] += 1
        csv.write_csv(pa.Table.from_pylist(rows), path)
        repin(metadata)
    elif defect == "platform_dates":
        path = platform / "manifest.json"
        value = json.loads(path.read_text())
        value["study_end"] = "2026-12-31"
        write_json(path, value)
    else:
        path = platform / ("organizations.jsonl" if defect == "platform_count" else "records.jsonl")
        rows = [json.loads(line) for line in path.read_text().split("\n") if line]
        if defect == "platform_count":
            rows[0]["n_evidence_records"] += 1
        elif defect == "platform_admission":
            rows[0]["human_gold"] = True
        else:
            rows[0]["extracted_text"] += "changed"
        write_jsonl(path, rows)
        repin(platform, platform=True)
    out = tmp_path / "preview"
    with pytest.raises((ValueError, FileNotFoundError)):
        build_cycle_preview(metadata, platform, out)
    assert not out.exists()


def test_cycle_refuses_overlapping_or_nonempty_output(cycle_bundle, tmp_path):
    metadata, platform, *_ = cycle_bundle
    for out in (metadata, tmp_path, ROOT / "web" / "forbidden-preview"):
        with pytest.raises(ValueError, match="output"):
            build_cycle_preview(metadata, platform, out)


def test_query_download_uses_all_matches_and_safe_literal_text(cycle_bundle, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable; no browser validation implied")
    metadata, platform, *_ = cycle_bundle
    out = tmp_path / "preview"
    build_cycle_preview(metadata, platform, out)
    check = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { filterEvidence, fullQueryJSONL, safeSourceURL } = require(process.argv[1]);
const rows = fs.readFileSync(process.argv[2], "utf8").trimEnd().split("\n").map(JSON.parse);
const matches = filterEvidence(rows, '"quoted phrase"');
assert.equal(matches.length, 13);
assert.ok(matches.length > 10);
const downloaded = fullQueryJSONL(matches).trimEnd().split("\n").map(JSON.parse);
assert.deepEqual(downloaded, matches);
assert.ok(downloaded[12].text.includes("<script>window.EVIDENCE_INJECTED=true</script>"));
assert.equal(downloaded[0].training_admission, false);
assert.equal(downloaded[0].n_input_tokens, null);
assert.equal(filterEvidence(rows, "no-such-text").length, 0);
assert.equal(fullQueryJSONL([]), "");
assert.equal(filterEvidence(rows, "HB 11").length, 1);
assert.equal(safeSourceURL("javascript:alert(1)"), null);
assert.equal(safeSourceURL("file:///unserved/source.pdf"), null);
assert.equal(safeSourceURL("/unserved/source.pdf"), null);
assert.equal(safeSourceURL("https://example.org/platform"), "https://example.org/platform");
"""
    subprocess.run(
        [node, "-e", check, str(out / "cycle-evidence.js"), str(out / "evidence/bills-TX.jsonl")],
        check=True, capture_output=True, text=True,
    )


def test_cycle_cli_mode_builds_separate_unpublished_preview(
    cycle_bundle, tmp_path, capsys, monkeypatch,
):
    metadata, platform, *_ = cycle_bundle
    main = runpy.run_path(str(ROOT / "scripts/build_site.py"))["main"]
    out = tmp_path / "preview"
    assert main([
        "--cycle-evidence", "--bill-evidence", str(metadata), "--platform-evidence", str(platform),
        "--out", str(out),
    ]) == 0
    assert "build manifest sha256:" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--cycle-evidence", "--recovery", str(platform)])
    captured = []

    def capture_defaults(metadata_dir, platform_dir, output):
        captured.append((metadata_dir, platform_dir, output))
        return {"counts": {}}

    monkeypatch.setattr("state_politics.site_evidence.build_cycle_preview", capture_defaults)
    monkeypatch.setitem(main.__globals__, "sha256_file", lambda _: "test-default-paths")
    assert main(["--cycle-evidence"]) == 0
    assert captured == [(
        ROOT / "data/processed/study-abstract-evidence-2023-2024-v2",
        ROOT / "data/processed/platform-study-evidence-2023-2024-v5",
        ROOT / "data/preview-cycle-evidence-v2",
    )]


@pytest.mark.skipif(not os.environ.get("CYCLE_BROWSER_CHROME"), reason="No real browser configured")
def test_cycle_real_browser_controls_downloads_markup_nojs_and_mobile(cycle_bundle, tmp_path):
    metadata, platform, *_ = cycle_bundle
    out = tmp_path / "preview"
    build_cycle_preview(metadata, platform, out)
    result = subprocess.run([
        shutil.which("node"), str(ROOT / "tests/browser_cycle_site.cjs"), str(out),
        str(tmp_path / "browser-check"), os.environ["CYCLE_BROWSER_CHROME"], "fixture",
    ], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr

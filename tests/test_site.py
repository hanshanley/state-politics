"""Local preview uses complete source evidence and never manufactures analytical findings."""

import gzip
import json
import runpy
from pathlib import Path

import pytest
import yaml

from state_politics.analysis.coverage import build_source_ledger
from state_politics.analysis.coverage import main as coverage_main

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

"""Repository-wide traceability and reproducibility checks."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml

from state_politics.platforms.official_documents import load_registry, merge_documents

ROOT = Path(__file__).resolve().parents[1]


def test_manual_input_hashes_match_manifest():
    manifest = yaml.safe_load((ROOT / "conf/reproducibility.yml").read_text())
    for entry in manifest["manual_inputs"]:
        path = ROOT / entry["path"]
        assert path.exists(), entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["path"]


def test_official_ocr_registry_is_primary_and_hashed():
    sources = load_registry()
    assert len(sources) == 5
    assert all(source["primary_source"] is True for source in sources)
    pdfs = [source for source in sources if source["extraction"] == "scanned_pdf"]
    assert len(pdfs) == 4
    assert all(len(source["expected_document_sha256"]) == 64 for source in pdfs)


def test_merge_official_documents_replaces_by_stable_id_and_url():
    corpus = pd.DataFrame(
        [
            {
                "official_source_id": None,
                "state": "NY",
                "party": "D",
                "url": "https://issuu.com/nydems/docs/resolutions",
                "text": "old manual OCR",
            },
            {
                "official_source_id": None,
                "state": "TX",
                "party": "R",
                "url": "https://example.test/platform",
                "text": "keep",
            },
        ]
    )
    incoming = [
        {
            "official_source_id": "ny-dem-state-committee-resolutions-2019-2024",
            "state": "NY",
            "party": "D",
            "url": "https://issuu.com/nydems/docs/resolutions",
            "text": "reproducible OCR",
        }
    ]
    merged = merge_documents(corpus, incoming)

    assert len(merged) == 2
    assert "old manual OCR" not in set(merged["text"])
    assert "reproducible OCR" in set(merged["text"])
    assert "keep" in set(merged["text"])


def test_reproducibility_audit_passes_current_artifacts():
    result = subprocess.run(
        [sys.executable, "scripts/audit_reproducibility.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

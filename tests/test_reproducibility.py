"""Repository-wide traceability and reproducibility checks."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pandas.testing as pdt
import pytest
import yaml

from state_politics.analysis.gold_sample import sample_frame
from state_politics.platforms import official_documents as official_module
from state_politics.platforms.official_documents import load_registry, merge_documents

ROOT = Path(__file__).resolve().parents[1]


def test_manual_input_hashes_match_manifest():
    manifest = yaml.safe_load((ROOT / "conf/reproducibility.yml").read_text())
    for entry in manifest["manual_inputs"]:
        path = ROOT / entry["path"]
        assert path.exists(), entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["path"]


def test_manifested_hosts_are_reputable_explicit_allowlists():
    manifest = yaml.safe_load((ROOT / "conf/reproducibility.yml").read_text())
    hosts = manifest["trusted_source_hosts"]

    assert "issuu.com" in hosts["official_document_pages"]
    assert "static.wixstatic.com" in hosts["official_document_content"]
    assert "apps.legislature.ky.gov" in hosts["caucus_sources"]
    assert all(not host.endswith(".example") for values in hosts.values() for host in values)


def test_official_ocr_registry_is_primary_and_hashed():
    sources = load_registry()
    assert len(sources) == 5
    assert all(source["primary_source"] is True for source in sources)
    pdfs = [source for source in sources if source["extraction"] == "scanned_pdf"]
    assert len(pdfs) == 4
    assert all(len(source["expected_document_sha256"]) == 64 for source in pdfs)


def test_official_document_hash_drift_is_rejected(monkeypatch):
    source = next(
        source for source in load_registry() if source["extraction"] == "scanned_pdf"
    )

    class Record:
        ok = True
        error = None

    monkeypatch.setattr(
        official_module,
        "fetch",
        lambda *args, **kwargs: (b"tampered source", Record()),
    )
    with pytest.raises(ValueError, match="source hash changed"):
        official_module._verified_fetch(
            source["document_url"],
            expected_sha256=source["expected_document_sha256"],
            source_org=source["institution"],
            note="test",
            log=object(),
        )


def test_merge_official_documents_replaces_by_stable_id_and_url():
    corpus = pd.DataFrame(
        [
            {
                "official_source_id": None,
                "state": "NY",
                "party": "D",
                "url": "https://issuu.com/nydems/docs/resolutions",
                "fetched_url": "https://issuu.com/nydems/docs/resolutions",
                "text": "old manual OCR",
            },
            {
                "official_source_id": None,
                "state": "TX",
                "party": "R",
                "url": "https://example.test/platform",
                "fetched_url": "https://example.test/platform.pdf",
                "text": "keep",
            },
            {
                "official_source_id": None,
                "state": "LA",
                "party": "R",
                "url": "https://www.lagop.com/2025-rscc-resolutions#q1",
                "fetched_url": "https://static.wixstatic.com/ugd/q1.pdf",
                "text": "old fragment URL OCR",
            },
        ]
    )
    incoming = [
        {
            "official_source_id": "ny-dem-state-committee-resolutions-2019-2024",
            "state": "NY",
            "party": "D",
            "url": "https://issuu.com/nydems/docs/resolutions",
            "fetched_url": "https://issuu.com/nydems/docs/resolutions",
            "text": "reproducible OCR",
        },
        {
            "official_source_id": "la-q1",
            "state": "LA",
            "party": "R",
            "url": "https://www.lagop.com/2025-rscc-resolutions",
            "fetched_url": "https://static.wixstatic.com/ugd/q1.pdf",
            "text": "reproducible Louisiana OCR",
        },
    ]
    merged = merge_documents(corpus, incoming)

    assert len(merged) == 3
    assert "old manual OCR" not in set(merged["text"])
    assert "old fragment URL OCR" not in set(merged["text"])
    assert "reproducible OCR" in set(merged["text"])
    assert "reproducible Louisiana OCR" in set(merged["text"])
    assert "keep" in set(merged["text"])


def test_reproducibility_audit_passes_current_artifacts():
    result = subprocess.run(
        [sys.executable, "scripts/audit_reproducibility.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_gold_template_sampling_is_deterministic_and_seeded():
    frame = pd.DataFrame(
        {
            "state": ["AK"] * 20,
            "party": ["D"] * 20,
            "year": [2024] * 20,
            "source_document_sha256": [f"{index:064x}" for index in range(20)],
            "plank_index": list(range(20)),
            "text": [f"plank {index}" for index in range(20)],
        }
    )
    first = sample_frame(frame, seed=20260729, size=8)
    second = sample_frame(frame, seed=20260729, size=8)
    other = sample_frame(frame, seed=7, size=8)

    pdt.assert_frame_equal(first, second)
    assert first["text"].tolist() != other["text"].tolist()
    assert first["gold_topic"].eq("").all()

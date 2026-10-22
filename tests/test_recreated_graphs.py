"""Complete research downloads and source-preserving graph input accounting."""

import hashlib
import json
import runpy
import zipfile
from pathlib import Path

import pandas as pd
import pytest

GRAPH = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/recreate_graphs.py"))


def packet(tmp_path):
    directory = tmp_path / "source"
    directory.mkdir()
    body = '{"text":"complete\u2028native\u2029source","all_rows":[1,2,3]}\n'.encode()
    (directory / "full_records.jsonl").write_bytes(body)
    manifest = {
        "analytical_admission": False, "scientific_approval": False,
        "files": {"full_records.jsonl": {
            "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
        }},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return directory, manifest, body


def test_research_archive_preserves_complete_records_and_original_manifest(tmp_path):
    directory, _, body = packet(tmp_path)
    inputs = {}
    files = GRAPH["recovery_packet"](tmp_path, "source", inputs)
    output = tmp_path / "complete.zip"
    result = GRAPH["archive_packet"](files, output)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"manifest.json", "full_records.jsonl"}
        assert archive.read("full_records.jsonl") == body
        assert archive.read("manifest.json") == (directory / "manifest.json").read_bytes()
    assert result["files"] == 2
    assert result["uncompressed_bytes"] == sum(path.stat().st_size for path in files.values())
    assert inputs["source/full_records.jsonl"]["sha256"] == hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize("defect", ["approved", "modified", "escape"])
def test_recovery_input_rejects_approval_corruption_and_path_escape(tmp_path, defect):
    directory, manifest, _ = packet(tmp_path)
    if defect == "approved":
        manifest["analytical_admission"] = True
    elif defect == "modified":
        (directory / "full_records.jsonl").write_bytes(b"metadata-only replacement")
    else:
        manifest["files"]["../outside.jsonl"] = manifest["files"].pop("full_records.jsonl")
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        GRAPH["recovery_packet"](tmp_path, "source", {})


def native_files(tmp_path, missing_reader=False):
    contexts = pd.DataFrame({
        "context_id": ["a", "b", "c"],
        "native_session_identifier": ["2023R", "2024F", "2024F"],
    })
    views = pd.DataFrame({
        "context_id": ["b", "b", "c", "c"],
        "reader": ["pymupdf", "pypdf", "pymupdf", "pypdf"],
    })
    if missing_reader:
        views = views.iloc[:-1]
    files = {
        "context_inventory.parquet": tmp_path / "contexts.parquet",
        "source_view_inputs.parquet": tmp_path / "views.parquet",
    }
    contexts.to_parquet(files["context_inventory.parquet"])
    views.to_parquet(files["source_view_inputs.parquet"])
    return files


def test_native_graph_counts_contexts_separately_from_reader_alternatives(tmp_path):
    result = GRAPH["arkansas_rows"](native_files(tmp_path)).set_index("native_session_identifier")
    assert result["native_metadata_contexts"].to_dict() == {"2023R": 1, "2024F": 2}
    assert result["complete_pdf_contexts"].to_dict() == {"2023R": 0, "2024F": 2}
    assert result["complete_reader_views"].to_dict() == {"2023R": 0, "2024F": 4}
    assert result["metadata_only_contexts"].to_dict() == {"2023R": 1, "2024F": 0}


def test_native_graph_cannot_claim_two_readers_when_one_is_missing(tmp_path):
    with pytest.raises(ValueError, match="two complete reader"):
        GRAPH["arkansas_rows"](native_files(tmp_path, missing_reader=True))


def test_snapshot_native_union_counts_exact_bills_once_and_keeps_unknown_native_counts(
    tmp_path, monkeypatch,
):
    metadata = tmp_path / GRAPH["SOURCES"]["metadata"]
    metadata.mkdir(parents=True)
    bills = pd.DataFrame({
        "bill_id": ["a", "b", "c", "d"], "state": ["CA", "AK", "CA", "AK"],
        "n_indexed_native_views": [2, None, 2, None],
    })
    source = metadata / "bill_evidence.parquet"
    bills.to_parquet(source)
    (metadata / "manifest.json").write_text(json.dumps({
        "artifacts": {"bill_evidence.parquet": {
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "bytes": source.stat().st_size,
        }},
    }))
    inventory = tmp_path / "snapshot.parquet"
    pd.DataFrame({
        "bill_id": bills["bill_id"], "state": bills["state"],
        "nonempty_bound_noerror": [True, True, False, False],
    }).to_parquet(inventory)
    monkeypatch.setitem(GRAPH["snapshot_coverage"].__globals__, "read_tracker",
                        lambda _: pd.DataFrame({"state": ["AK", "CA"]}))
    coverage, missing = GRAPH["snapshot_coverage"](
        tmp_path, {"context_inventory.parquet": inventory}, {},
    )
    counts = coverage.set_index("state")
    assert counts.loc["CA", ["candidate_contexts", "both_sources", "native_only"]].tolist() == [
        2, 1, 1,
    ]
    assert counts.loc["AK", ["candidate_contexts", "snapshot_only",
                              "neither_source_observed"]].tolist() == [2, 1, 1]
    assert missing["bill_id"].tolist() == ["d"]
    assert pd.isna(missing.iloc[0]["n_indexed_native_views"])

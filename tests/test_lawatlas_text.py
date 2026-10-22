import copy
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from state_politics.bills import lawatlas_text as lawatlas

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "data/processed/new-public-corpora-nj-ok-ne-20261022-v1"
GAP = REPO / "outputs/recreated-2023-2024-v9/chart-data/missing_retained_text.parquet"


@pytest.fixture(scope="module")
def packet():
    if not SOURCE.exists():
        pytest.skip("immutable local LawAtlas evidence is not present")
    workspace = REPO / "data/processed" / f"lawatlas-adapter-test-{uuid.uuid4().hex}"
    workspace.mkdir()
    before = lawatlas._source_inventory(SOURCE)
    times = {name: (SOURCE / name).stat().st_mtime_ns for name in before}
    out = workspace / "packet"
    try:
        lawatlas.build_lawatlas(SOURCE, GAP, out)
        yield out
    finally:
        assert lawatlas._source_inventory(SOURCE) == before
        assert {name: (SOURCE / name).stat().st_mtime_ns for name in before} == times
        shutil.rmtree(workspace)


def repin(packet, relative):
    path = packet / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["packet_artifacts"][relative] = lawatlas._binding(packet / relative)
    path.write_text(json.dumps(manifest))


def test_lossless_actual_pdf_replay_preserves_overlap_and_all_duplicate_references(packet):
    rows, contexts, pins, manifest = lawatlas.load_lawatlas(packet)
    originals = pq.read_table(SOURCE / "recovery-v2/fullbody_views.parquet").to_pylist()
    by_view = {row["view_id"]: row for row in originals}
    assert len(rows) == len(contexts) == 4
    assert manifest["counts"]["newly_covered_contexts"] == 4
    assert {row["view_id"] for row in rows} == set(by_view)
    for row in rows:
        original = by_view[row["view_id"]]
        assert row["text"] == original["text"]
        assert row["raw_text_sha256"] == hashlib.sha256(row["text"].encode()).hexdigest()
        references = row["source_record"]["snapshot_records"]
        assert [item["source_row_ordinal"] for item in references] == (
            original["source_record_ordinals"]
        )
        assert row["source_record"]["original_recovery_record"]["law_record"] == (
            row["source_record"]["law_metadata"]
        )
        assert all(row[flag] is False for flag in lawatlas.FLAGS)
    assert any(row["identifier"] == "A 1899" and row["session_identifier"] == "221"
               for row in rows)
    assert any(row["state"] == "NE" for row in rows)
    assert len(pins) == 106
    lawatlas.load_lawatlas(packet, contexts)
    assert all((packet / "source-evidence" / name).read_bytes() == (SOURCE / name).read_bytes()
               for name in lawatlas._source_inventory(SOURCE))


@pytest.mark.parametrize("defect", [
    "text", "duplicate_reference", "printed_identity", "context", "approval", "raw_pdf",
])
def test_rejects_rebound_altered_body_record_identity_context_promotion_or_source(packet, defect):
    relative = {
        "context": "context_inventory.parquet",
        "raw_pdf": "source-evidence/raw/21_nj_s3841_attached_pdf_hop0.body",
    }.get(defect, "views.jsonl")
    path = packet / relative
    original, manifest = path.read_bytes(), (packet / "manifest.json").read_bytes()
    try:
        if defect == "context":
            table = pq.read_table(path)
            records = table.to_pylist()
            records[0]["title"] += " changed"
            pq.write_table(pa.Table.from_pylist(records, schema=table.schema), path)
        elif defect == "raw_pdf":
            path.write_bytes(original + b"\nchanged PDF")
        else:
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            if defect == "text":
                rows[0]["text"] = rows[0]["text"][:-1]
                rows[0]["raw_text_sha256"] = hashlib.sha256(rows[0]["text"].encode()).hexdigest()
                rows[0]["raw_text_characters"] -= 1
            elif defect == "duplicate_reference":
                rows[0]["source_record"]["snapshot_records"].pop()
            elif defect == "printed_identity":
                rows[0]["source_identity"]["session_identifier"] = "221"
            else:
                rows[0]["training_approved"] = True
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        repin(packet, relative)
        with pytest.raises(ValueError, match="incompatible LawAtlas archive"):
            lawatlas.load_lawatlas(packet)
    finally:
        path.write_bytes(original)
        (packet / "manifest.json").write_bytes(manifest)


def test_linked_manifest_is_rejected_before_any_json_read(packet, monkeypatch):
    manifest = packet / "manifest.json"
    original = manifest.read_bytes()
    target = packet.parent / "manifest-link-target.json"
    target.write_bytes(original)
    manifest.unlink()
    manifest.symlink_to(target)
    try:
        monkeypatch.setattr(lawatlas, "_json", lambda _: pytest.fail("read linked manifest"))
        with pytest.raises(ValueError, match="linked source/manifest"):
            lawatlas.load_lawatlas(packet)
    finally:
        manifest.unlink()
        manifest.write_bytes(original)
        target.unlink()


@pytest.mark.parametrize("defect", ["unsafe", "symlink", "hardlink", "hash"])
def test_rejects_unsafe_linked_or_unbound_artifacts(packet, defect):
    manifest = packet / "manifest.json"
    saved_manifest = manifest.read_bytes()
    relative = "source-evidence/raw/21_nj_s3841_attached_pdf_hop0.body"
    source = packet / relative
    original = source.read_bytes()
    target = packet.parent / "artifact-link-target"
    try:
        if defect == "unsafe":
            value = json.loads(saved_manifest)
            value["packet_artifacts"]["source-evidence/../outside"] = {"bytes": 0, "sha256": "0"}
            manifest.write_text(json.dumps(value))
        elif defect == "hash":
            source.write_bytes(original + b"unbound")
        else:
            target.write_bytes(original)
            source.unlink()
            if defect == "symlink":
                source.symlink_to(target)
            else:
                os.link(target, source)
        with pytest.raises(ValueError, match="unsafe|linked|binding mismatch"):
            lawatlas.load_lawatlas(packet)
    finally:
        if source.is_symlink() or source.stat().st_nlink != 1:
            source.unlink()
        source.write_bytes(original)
        manifest.write_bytes(saved_manifest)
        if target.exists():
            target.unlink()


def test_current_metadata_cannot_reassign_or_duplicate_original_contexts(packet):
    _, contexts, _, _ = lawatlas.load_lawatlas(packet)
    wrong = copy.deepcopy(contexts)
    wrong[0]["session_identifier"] = "unrelated"
    for metadata in (wrong, contexts + [contexts[0]]):
        with pytest.raises(ValueError, match="current candidate identity"):
            lawatlas.load_lawatlas(packet, metadata)


@pytest.mark.parametrize("promotion", [
    {"training_approved": True}, {"publisher_original_certified": True},
])
def test_manifest_cannot_promote_either_required_or_extra_approvals(packet, promotion):
    path = packet / "manifest.json"
    original = path.read_bytes()
    try:
        manifest = json.loads(original)
        manifest["approvals"].update(promotion)
        path.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="source approval promotion"):
            lawatlas.load_lawatlas(packet)
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize("text", [
    "STATE OF NEW JERSEY\nASSEMBLY, No. 1899\nEffective January 1, 2024",
    "STATE OF OKLAHOMA\n1st Session of the 59th Legislature (2024)\nHOUSE BILL 2170",
    "LEGISLATURE OF NEBRASKA\nONE HUNDRED NINTH LEGISLATURE\nLEGISLATIVE BILL 202",
])
def test_dates_citations_or_different_assembly_cannot_substitute_for_own_session(text):
    with pytest.raises(ValueError, match="printed|Oklahoma"):
        lawatlas.printed_identity(text)

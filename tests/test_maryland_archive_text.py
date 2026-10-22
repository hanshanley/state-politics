import copy
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from state_politics.bills import maryland_archive_text as maryland

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "data/processed/remaining-predecessor-session-recovery-20261022-v1"
GAP = REPO / "outputs/recreated-2023-2024-v10/chart-data/missing_retained_text.parquet"


@pytest.fixture(scope="module")
def packet():
    if not SOURCE.exists():
        pytest.skip("sealed local Maryland archive is not present")
    workspace = REPO / "data/processed" / f"maryland-adapter-test-{uuid.uuid4().hex}"
    workspace.mkdir()
    before = maryland._source_inventory(SOURCE)
    attributes = {
        name: ((SOURCE / name).stat().st_mtime_ns, stat.S_IMODE((SOURCE / name).stat().st_mode))
        for name in before
    }
    try:
        out = workspace / "packet"
        maryland.build_maryland(SOURCE, GAP, out)
        yield out
    finally:
        assert maryland._source_inventory(SOURCE) == before
        assert {
            name: ((SOURCE / name).stat().st_mtime_ns,
                   stat.S_IMODE((SOURCE / name).stat().st_mode)) for name in before
        } == attributes
        shutil.rmtree(workspace)


def repin(packet, name):
    path = packet / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["packet_artifacts"][name] = maryland._binding(packet / name)
    path.write_text(json.dumps(manifest))


def test_actual_complete_tar_replay_preserves_records_sections_and_current_identity(packet):
    rows, contexts, pins, manifest = maryland.load_maryland(packet)
    originals = maryland._jsonl(SOURCE / "views.jsonl")
    assert len(rows) == len(originals) == 1070
    assert len(contexts) == 563
    assert len(pins) == len(manifest["packet_artifacts"]) + 1 == 1766
    assert manifest["counts"]["rejected_source_views"] == 57
    assert manifest["counts"]["bounded_negative_contexts"] == 6672
    assert len({row["view_id"] for row in rows}) == 1070
    for row, original in zip(rows, originals, strict=True):
        assert row["source_record"] == original
        assert row["text"] == original["source_text"]
        assert row["raw_text_characters"] == len(row["text"])
        assert row["raw_text_sha256"] == hashlib.sha256(row["text"].encode()).hexdigest()
        assert all(row[flag] is False for flag in (*maryland.FLAGS, *maryland.EXTRA_FLAGS))
        identity = row["source_identity"]
        assert identity["policy_section_start"] == re.search(
            r"(?m)^Section 1:[ \t]*\r?\n", row["text"],
        ).end()
        assert row["text"][:identity["policy_section_start"]].startswith("Title: ")
        assert row["archive_generated_prologue_preserved"] is True
        for span in identity["printed_evidence"]:
            assert row["text"][span["start"]:span["end"]] == span["text"]
        assert row["source_version"]["version"] in original["original_metadata"]["versions"]
        assert row["source_version"]["link"] in row["source_version"]["version"]["links"]
        for name in ("text", "metadata", "pdf"):
            member = row["source_members"][name]
            assert type(member["archive_ordinal"]) is int
            assert member["archive_member"].startswith("md-data-pipeline-" + maryland.COMMIT)
    original_gap = pq.read_table(GAP)
    ids = {row["bill_id"] for row in contexts}
    assert pq.read_table(packet / "context_inventory.parquet").equals(
        original_gap.filter([row["bill_id"] in ids for row in original_gap.to_pylist()]),
        check_metadata=True,
    )
    current = pq.read_table(
        REPO / "data/processed/bills.parquet",
        columns=["bill_id", "state", "identifier", "session_identifier"],
        filters=[("bill_id", "in", sorted(ids))],
    )
    maryland.load_maryland(packet, current)
    assert maryland.main([
        "replay", "--directory", str(packet),
        "--metadata", str(REPO / "data/processed/bills.parquet"),
    ]) == 0


@pytest.mark.parametrize("defect", [
    "text", "typed_identity", "promotion", "original_record", "prologue",
    "source_member", "counts", "manifest_promotion",
])
def test_rehashed_exports_cannot_rebind_source_text_identity_approvals_or_counts(packet, defect):
    path = packet / "views.jsonl"
    saved, manifest_saved = path.read_bytes(), (packet / "manifest.json").read_bytes()
    try:
        if defect in {"counts", "manifest_promotion"}:
            manifest = json.loads(manifest_saved)
            if defect == "counts":
                manifest["counts"]["text_views"] -= 1
            else:
                manifest["approvals"]["scientific_approval"] = True
            (packet / "manifest.json").write_text(json.dumps(manifest))
        else:
            rows = maryland._jsonl(path)
            if defect == "text":
                rows[0]["text"] = rows[0]["text"][:-1]
                rows[0]["raw_text_characters"] -= 1
                rows[0]["raw_text_sha256"] = hashlib.sha256(rows[0]["text"].encode()).hexdigest()
            elif defect == "typed_identity":
                rows[0]["source_identity"]["session_identifier"] = 2025
            elif defect == "promotion":
                rows[0]["training_admission"] = 0
            elif defect == "original_record":
                rows[0]["source_record"]["original_metadata"]["versions"].pop()
            elif defect == "prologue":
                rows[0]["source_identity"]["policy_section_start"] -= 1
            else:
                other = next(row for row in rows if row["bill_id"] != rows[0]["bill_id"])
                rows[0]["source_members"]["pdf"] = other["source_members"]["pdf"]
            maryland._write_rows(path, rows)
            repin(packet, "views.jsonl")
        with pytest.raises(ValueError, match="incompatible Maryland archive"):
            maryland.load_maryland(packet)
    finally:
        path.write_bytes(saved)
        (packet / "manifest.json").write_bytes(manifest_saved)


def test_linked_manifest_is_rejected_before_any_json_read(packet, monkeypatch):
    path = packet / "manifest.json"
    original = path.read_bytes()
    target = packet.parent / "linked-manifest.json"
    target.write_bytes(original)
    path.unlink()
    path.symlink_to(target)
    try:
        monkeypatch.setattr(maryland, "_json", lambda _: pytest.fail("read linked manifest"))
        with pytest.raises(ValueError, match="linked source/manifest"):
            maryland.load_maryland(packet)
    finally:
        path.unlink()
        path.write_bytes(original)
        target.unlink()


@pytest.mark.parametrize("defect", ["traversal", "hardlink", "source"])
def test_unsafe_paths_links_and_rehashed_corrupt_original_sources_are_rejected(packet, defect):
    manifest = packet / "manifest.json"
    saved_manifest = manifest.read_bytes()
    relative = "source-evidence/downloads/md-0e17cc31.tar.gz"
    source = packet / relative
    original = source.read_bytes()
    attributes = source.stat()
    target = packet.parent / "linked-source"
    try:
        if defect == "traversal":
            value = json.loads(saved_manifest)
            value["packet_artifacts"]["source-evidence/../outside"] = {
                "bytes": 0, "sha256": "0" * 64,
            }
            manifest.write_text(json.dumps(value))
        elif defect == "hardlink":
            source.unlink()
            target.write_bytes(original)
            os.link(target, source)
        else:
            source.chmod(0o644)
            source.write_bytes(original + b"corrupt source")
            repin(packet, relative)
        with pytest.raises(ValueError, match="unsafe|linked|source binding mismatch"):
            maryland.load_maryland(packet)
    finally:
        if source.stat().st_nlink != 1:
            source.unlink()
        if source.exists():
            source.chmod(0o644)
        source.write_bytes(original)
        source.chmod(stat.S_IMODE(attributes.st_mode))
        os.utime(source, ns=(attributes.st_atime_ns, attributes.st_mtime_ns))
        manifest.write_bytes(saved_manifest)
        if target.exists():
            target.unlink()


def test_current_metadata_cannot_reassign_duplicate_or_type_coerce_identity(packet):
    contexts = pq.read_table(packet / "context_inventory.parquet").to_pylist()
    rebound = copy.deepcopy(contexts)
    rebound[0]["session_identifier"] = 2025
    for current in (rebound, contexts + [contexts[0]]):
        with pytest.raises(ValueError, match="current candidate identity"):
            maryland.load_maryland(packet, current)


def test_printed_evidence_ignores_machine_titles_crossfiles_and_effective_dates():
    body = (
        "HOUSE JOINT RESOLUTION 3\nCF SJ 1\nRequested: September 12, 2024\n"
        "Introduced and read first time: January 8, 2025\n"
        "HOUSE JOINT RESOLUTION\n1 A House Joint Resolution concerning\n"
        "RESOLVED BY THE GENERAL ASSEMBLY OF MARYLAND\n"
        "This resolution takes effect in 2026.\n"
    )
    identity = maryland.printed_identity(body, "HJ 3", "2025")
    assert identity["archive_extractor_prologue_preserved"] is False
    assert identity["policy_section_start"] == 0
    with pytest.raises(ValueError, match="printed_session"):
        maryland.printed_identity(body, "HJ 3", "2024")
    with pytest.raises(ValueError, match="missing_explicit_printed_session"):
        maryland.printed_identity(
            body.replace("Introduced and read first time: January 8, 2025\n", ""), "HJ 3", "2025",
        )
    prologue = "Title: HOUSE JOINT RESOLUTION 3\nSection 1:\nplaceholder\n\nRaw Text:\n"
    with pytest.raises(ValueError, match="missing_printed_own"):
        maryland.printed_identity(prologue + body.replace("HOUSE JOINT RESOLUTION 3", "CF HJ 3"),
                                  "HJ 3", "2025")

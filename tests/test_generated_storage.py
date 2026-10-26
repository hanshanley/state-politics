"""Reclamation preserves immutable bytes and refuses unsafe or changing targets."""

import errno
import hashlib
import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest

MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/reclaim_generated_storage.py")
)


def pair(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"complete immutable evidence\n")
    shutil.copy2(source, target)
    expected = {
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "bytes": source.stat().st_size,
    }
    return source, target, expected


def test_clone_preserves_content_metadata_and_independence(tmp_path, monkeypatch):
    source, target, expected = pair(tmp_path)
    original_time = target.stat().st_mtime_ns
    original_source = MODULE["identity"](source)

    def clone(source, target):
        shutil.copyfile(source, target)

    monkeypatch.setitem(MODULE["clone_duplicate"].__globals__, "native_clone", clone)
    MODULE["clone_duplicate"](source, target, expected)
    assert source.read_bytes() == target.read_bytes()
    assert target.stat().st_mtime_ns == original_time
    assert MODULE["identity"](source) == original_source
    target.write_bytes(b"independent later output")
    assert source.read_bytes() == b"complete immutable evidence\n"


@pytest.mark.skipif(sys.platform != "darwin", reason="requires native APFS clone support")
def test_native_clone_keeps_later_writes_independent(tmp_path):
    source, target, expected = pair(tmp_path)
    MODULE["clone_duplicate"](source, target, expected)
    assert target.stat().st_ino != source.stat().st_ino
    assert target.read_bytes() == source.read_bytes()
    target.write_bytes(b"later independently changed output")
    assert source.read_bytes() == b"complete immutable evidence\n"


@pytest.mark.skipif(sys.platform != "darwin", reason="requires native clonefile support")
def test_native_clone_refuses_existing_destination_without_overwrite(tmp_path):
    source, target, _ = pair(tmp_path)
    target.write_bytes(b"existing distinct evidence")
    with pytest.raises(OSError) as caught:
        MODULE["native_clone"](source, target)
    assert caught.value.errno == errno.EEXIST
    assert target.read_bytes() == b"existing distinct evidence"


@pytest.mark.parametrize("defect", ["source", "target", "linked_target", "linked_source"])
def test_clone_refuses_unverified_or_linked_content(tmp_path, monkeypatch, defect):
    source, target, expected = pair(tmp_path)
    if defect.startswith("linked_"):
        linked = tmp_path / "linked"
        linked.symlink_to(source if defect == "linked_source" else target)
        if defect == "linked_source":
            source = linked
        else:
            target = linked
    else:
        (source if defect == "source" else target).write_bytes(b"different")
    before = target.read_bytes()
    monkeypatch.setitem(
        MODULE["clone_duplicate"].__globals__,
        "native_clone",
        lambda *a: pytest.fail("must not copy"),
    )
    with pytest.raises(ValueError):
        MODULE["clone_duplicate"](source, target, expected)
    assert target.read_bytes() == before


def test_clone_failure_never_falls_back_or_replaces_target(tmp_path, monkeypatch):
    source, target, expected = pair(tmp_path)
    before = MODULE["identity"](target)

    def fail(source, target):
        target.write_bytes(b"partial clone")
        raise OSError("clone unsupported")

    monkeypatch.setitem(MODULE["clone_duplicate"].__globals__, "native_clone", fail)
    with pytest.raises(OSError, match="unsupported"):
        MODULE["clone_duplicate"](source, target, expected)
    assert MODULE["identity"](target) == before
    assert target.read_bytes() == source.read_bytes()
    assert not list(tmp_path.glob(".*.cow-*"))


def test_clone_refuses_target_changed_during_copy(tmp_path, monkeypatch):
    source, target, expected = pair(tmp_path)

    def racing_clone(source, temporary):
        shutil.copyfile(source, temporary)
        target.write_bytes(b"another writer's output")

    monkeypatch.setitem(MODULE["clone_duplicate"].__globals__, "native_clone", racing_clone)
    with pytest.raises(ValueError, match="changed during"):
        MODULE["clone_duplicate"](source, target, expected)
    assert target.read_bytes() == b"another writer's output"
    assert not list(tmp_path.glob(".*.cow-*"))


def test_clone_collision_does_not_remove_another_writers_file(tmp_path, monkeypatch):
    source, target, expected = pair(tmp_path)

    def collide(source, temporary):
        temporary.write_bytes(b"another writer created this path")
        raise FileExistsError(errno.EEXIST, "already exists")

    monkeypatch.setitem(MODULE["clone_duplicate"].__globals__, "native_clone", collide)
    with pytest.raises(FileExistsError):
        MODULE["clone_duplicate"](source, target, expected)
    remaining = list(tmp_path.glob(".*.cow-*"))
    assert len(remaining) == 1
    assert remaining[0].read_bytes() == b"another writer created this path"
    assert source.read_bytes() == target.read_bytes()


def test_inventory_ignores_unfinished_jobs_and_failed_bundles(tmp_path, monkeypatch):
    monkeypatch.setitem(MODULE["inventory"].__globals__, "MIN_BYTES", 1)
    outputs = tmp_path / "outputs"
    for name in (
        "classification-inspector-2023-2024-v1",
        "classification-inspector-2023-2024-v2-FAILED",
    ):
        directory = outputs / name
        (directory / "evidence").mkdir(parents=True)
        payload = directory / "evidence/complete.jsonl"
        payload.write_bytes(b"same complete bytes\n")
        (directory / "manifest.json").write_text(
            json.dumps({"artifacts": {"evidence/complete.jsonl": MODULE["binding"](payload)}})
        )
    job = tmp_path / "data/processed/cycle-topic-inference-retained-text-20261026-v2"
    job.mkdir(parents=True)
    (job / "inference_plan.json").write_text("{}")
    (job / "progress-retained_text.json").write_text('{"status":"running"}')
    manifests, duplicates = MODULE["inventory"](tmp_path)
    assert len(manifests) == 1
    assert not duplicates


@pytest.mark.parametrize("name", ["../outside", "/outside", "evidence//x", "evidence/./x"])
def test_bound_path_cannot_escape_or_change_spelling(tmp_path, name):
    with pytest.raises(ValueError):
        MODULE["safe_path"](tmp_path, tmp_path, name)


def test_inventory_refuses_linked_bundle_before_reading_it(tmp_path):
    outside = tmp_path / "unbound"
    outside.mkdir()
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "classification-inspector-2023-2024-v1").symlink_to(
        outside, target_is_directory=True
    )
    with pytest.raises(ValueError, match="linked generated bundle"):
        MODULE["inventory"](tmp_path)

"""Reclamation preserves immutable bytes and refuses unsafe or changing targets."""

import errno
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from state_politics import storage

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


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_evidence_copy_uses_fresh_independent_full_files(tmp_path, monkeypatch, platform):
    source = tmp_path / "source"
    source.write_bytes(b"complete evidence\x00\nwith a final clause\n")
    target = tmp_path / "new-evidence"
    before = MODULE["identity"](source)
    clones = []

    def clone(source, target):
        clones.append((source, target))
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)

    monkeypatch.setattr(storage.sys, "platform", platform)
    monkeypatch.setattr(storage, "native_clone", clone)
    assert storage.copy_evidence(source, target) == target
    assert clones == ([(source, target)] if platform == "darwin" else [])
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_ino != source.stat().st_ino
    assert MODULE["identity"](source) == before
    target.write_bytes(b"independent later write")
    assert source.read_bytes() == b"complete evidence\x00\nwith a final clause\n"


@pytest.mark.parametrize(
    "platform",
    [
        pytest.param(
            "darwin",
            marks=pytest.mark.skipif(
                sys.platform != "darwin", reason="requires native clonefile support"
            ),
        ),
        "linux",
    ],
)
@pytest.mark.parametrize("linked", [False, True])
def test_evidence_copy_never_overwrites_an_existing_file(
    tmp_path,
    monkeypatch,
    platform,
    linked,
):
    source, target, _ = pair(tmp_path)
    target.write_bytes(b"another writer's complete evidence")
    destination = tmp_path / "linked" if linked else target
    if linked:
        destination.symlink_to(target)
    monkeypatch.setattr(storage.sys, "platform", platform)
    with pytest.raises(FileExistsError):
        storage.copy_evidence(source, destination)
    assert target.read_bytes() == b"another writer's complete evidence"
    assert not linked or destination.is_symlink()


def test_evidence_copy_never_falls_back_after_native_failure(tmp_path, monkeypatch):
    source, _, _ = pair(tmp_path)
    target = tmp_path / "new-evidence"
    monkeypatch.setattr(storage.sys, "platform", "darwin")

    def unsupported(*args):
        raise OSError(errno.ENOTSUP, "native cloning unsupported")

    monkeypatch.setattr(storage, "native_clone", unsupported)
    monkeypatch.setattr(
        storage.shutil, "copyfileobj", lambda *args: pytest.fail("must not fall back")
    )
    with pytest.raises(OSError) as caught:
        storage.copy_evidence(source, target)
    assert caught.value.errno == errno.ENOTSUP
    assert not target.exists()
    assert source.read_bytes() == b"complete immutable evidence\n"


def test_evidence_copy_refuses_linked_sources_before_creating_output(tmp_path):
    source, _, _ = pair(tmp_path)
    linked = tmp_path / "linked"
    linked.symlink_to(source)
    target = tmp_path / "new-evidence"
    with pytest.raises(ValueError, match="unlinked"):
        storage.copy_evidence(linked, target)
    assert not target.exists()


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


def preview(root, version, body):
    directory = root / "data" / f"preview-cycle-evidence-v{version}"
    (directory / "downloads").mkdir(parents=True)
    (directory / "evidence").mkdir()
    artifact = directory / "evidence/source.jsonl"
    artifact.write_bytes(body)
    (directory / "downloads/build_manifest.json").write_text(
        json.dumps(
            {
                "schema": "local_cycle_evidence_preview_v1",
                "outputs": {"evidence/source.jsonl": MODULE["binding"](artifact)},
            }
        )
    )
    return directory


def test_preview_scope_matches_content_not_names_and_excludes_bundles(tmp_path, monkeypatch):
    monkeypatch.setitem(MODULE["register_candidate"].__globals__, "MIN_BYTES", 1)
    first = preview(tmp_path, 1, b"same full evidence\n")
    preview(tmp_path, 2, b"different evidence\n")
    third = preview(tmp_path, 3, b"same full evidence\n")
    unrelated = tmp_path / "outputs/classification-inspector-2023-2024-v1"
    unrelated.mkdir(parents=True)
    (unrelated / "manifest.json").write_text("not a preview manifest")
    manifests, entries = MODULE["inventory"](tmp_path, "previews")
    assert len(manifests) == 3 and len(entries) == 1
    assert tmp_path / entries[0]["source"] == first / "evidence/source.jsonl"
    assert tmp_path / entries[0]["target"] == third / "evidence/source.jsonl"
    assert all(path.startswith("data/preview-cycle-evidence-") for path in manifests)


def test_preview_scope_ignores_incomplete_and_failed_snapshots(tmp_path):
    (tmp_path / "data/preview-cycle-evidence-v1").mkdir(parents=True)
    failed = tmp_path / "data/preview-cycle-evidence-v2-FAILED/downloads"
    failed.mkdir(parents=True)
    (failed / "build_manifest.json").write_text("not a completed snapshot")
    assert MODULE["inventory"](tmp_path, "previews") == ({}, [])


@pytest.mark.parametrize("defect", ["directory", "manifest"])
def test_preview_scope_refuses_links_before_reading(tmp_path, defect):
    directory = preview(tmp_path, 1, b"complete source")
    if defect == "directory":
        linked = directory.with_name("preview-cycle-evidence-v2")
        linked.symlink_to(directory, target_is_directory=True)
    else:
        manifest = directory / "downloads/build_manifest.json"
        original = manifest.with_name("original.json")
        manifest.rename(original)
        manifest.symlink_to(original)
    with pytest.raises(ValueError, match="linked preview"):
        MODULE["inventory"](tmp_path, "previews")


def test_preview_scope_refuses_unknown_schema(tmp_path):
    directory = preview(tmp_path, 1, b"complete source")
    (directory / "downloads/build_manifest.json").write_text('{"schema":"unknown"}')
    with pytest.raises(ValueError, match="schema"):
        MODULE["inventory"](tmp_path, "previews")


def test_inventory_does_not_silently_expand_unknown_scope(tmp_path):
    with pytest.raises(ValueError, match="scope"):
        MODULE["inventory"](tmp_path, "everything")


@pytest.mark.parametrize("script", ["serve_research.py", "build_site.py"])
def test_refuses_active_servers_and_preview_builders(monkeypatch, script):
    monkeypatch.setattr(
        MODULE["subprocess"],
        "check_output",
        lambda *a, **k: f"python -I -B scripts/{script} --port 8765\n",
    )
    with pytest.raises(ValueError, match="active research servers/builders"):
        MODULE["require_quiet"]()


def test_legacy_clean_refuses_to_delete_retained_tables_or_figures(tmp_path):
    data, output = tmp_path / "data/processed", tmp_path / "outputs"
    data.mkdir(parents=True)
    output.mkdir()
    originals = {
        data / "retained_source.parquet": b"retained normalized source",
        data / "retained_source.csv": b"complete source ledger",
        output / "legacy_figure.png": b"preserved historical figure",
    }
    for path, body in originals.items():
        path.write_bytes(body)
    makefile = Path(__file__).resolve().parents[1] / "Makefile"
    result = subprocess.run(
        ["make", "-f", str(makefile), "clean-derived", f"DATA={data}", f"OUT={output}"],
        cwd=tmp_path,
        env=dict(os.environ, MAKEFLAGS="", MAKEOVERRIDES="", MAKEFILES=""),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "No files were deleted." in result.stdout
    assert "reclaim_generated_storage.py" in result.stdout
    assert all(path.read_bytes() == body for path, body in originals.items())

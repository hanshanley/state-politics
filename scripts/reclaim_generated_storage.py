#!/usr/bin/env python3
"""Reclaim generated duplicates with verified APFS clones; default to a dry run."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from state_politics.storage import native_clone  # noqa: E402

MIN_BYTES = 10_000_000


def read(path):
    return json.loads(path.read_bytes())


def binding(path):
    with path.open("rb") as handle:
        sha = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"sha256": sha, "bytes": path.stat().st_size}


def identity(path):
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def safe_path(root, directory, name):
    relative = PurePosixPath(name)
    if (
        not name
        or relative.is_absolute()
        or relative.as_posix() != name
        or "\\" in name
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError(f"unsafe artifact path: {name}")
    path = directory / name
    if not path.is_relative_to(root) or path.resolve() != path or not path.is_file():
        raise ValueError(f"missing or linked generated artifact: {path}")
    return path


def register_candidate(root, candidates, directory, name, expected):
    if expected.get("bytes", 0) < MIN_BYTES:
        return
    if not re.fullmatch(r"[0-9a-f]{64}", expected.get("sha256", "")):
        raise ValueError("invalid generated artifact binding")
    path = safe_path(root, directory, name)
    if path.stat().st_size != expected["bytes"]:
        raise ValueError(f"generated artifact size changed: {path}")
    entry = {"sha256": expected["sha256"], "bytes": expected["bytes"]}
    if path in candidates and candidates[path] != entry:
        raise ValueError(f"conflicting artifact bindings: {path}")
    candidates[path] = entry


def duplicate_entries(root, candidates):
    canonical, duplicates = {}, []
    for path, expected in candidates.items():
        key = expected["sha256"], expected["bytes"]
        if key not in canonical:
            canonical[key] = path
            continue
        source = canonical[key]
        source_stat, target_stat = source.stat(), path.stat()
        if (source_stat.st_dev, source_stat.st_ino) == (target_stat.st_dev, target_stat.st_ino):
            continue
        duplicates.append(
            {
                "source": str(source.relative_to(root)),
                "target": str(path.relative_to(root)),
                **expected,
            }
        )
    return duplicates


def preview_inventory(root):
    manifests, candidates = {}, {}
    for directory in sorted((root / "data").glob("preview-cycle-evidence-v*")):
        if not re.fullmatch(r"preview-cycle-evidence-v\d+", directory.name):
            continue
        if directory.resolve() != directory:
            raise ValueError("linked preview directory")
        path = directory / "downloads/build_manifest.json"
        if not path.is_file():
            continue
        if path.resolve() != path:
            raise ValueError("linked preview manifest")
        manifest = read(path)
        if manifest.get("schema") != "local_cycle_evidence_preview_v1":
            raise ValueError("unknown preview manifest schema")
        manifests[str(path.relative_to(root))] = binding(path)
        for name, expected in manifest["outputs"].items():
            if name.startswith(("evidence/", "downloads/")):
                register_candidate(root, candidates, directory, name, expected)
    return manifests, duplicate_entries(root, candidates)


def inventory(root, scope="bundles"):
    if scope == "previews":
        return preview_inventory(root)
    if scope != "bundles":
        raise ValueError("unknown reclamation scope")
    manifests, candidates = {}, {}

    def register(directory, name, expected):
        register_candidate(root, candidates, directory, name, expected)

    processed = root / "data/processed"
    for directory in sorted(processed.glob("cycle-topic-inference-retained-text-*-v*")):
        if not re.fullmatch(r"cycle-topic-inference-retained-text-\d{8}-v\d+", directory.name):
            continue
        if directory.resolve() != directory:
            raise ValueError("linked generated job directory")
        plan_path = directory / "inference_plan.json"
        progress_path = directory / "progress-retained_text.json"
        if not plan_path.is_file() or not progress_path.is_file():
            continue
        if read(progress_path).get("status") != (
            "complete_provisional_inference_not_scientific_validation"
        ):
            continue
        plan = read(plan_path)
        manifests[str(plan_path.relative_to(root))] = binding(plan_path)
        manifests[str(progress_path.relative_to(root))] = binding(progress_path)
        register(directory, "contexts.jsonl", plan["contexts"])
        for name, expected in plan["inputs"].items():
            if name.startswith("inputs/"):
                register(directory, name, expected)

    profiles = (
        ("topic-majority-2023-2024", ("decisions/", "research-data/")),
        ("recreated-2023-2024", ("research-data/",)),
        ("classification-inspector-2023-2024", ("evidence/", "research-data/")),
    )
    for prefix, allowed in profiles:
        for directory in sorted((root / "outputs").glob(prefix + "-v*")):
            if not re.fullmatch(re.escape(prefix) + r"-v\d+", directory.name):
                continue
            if directory.resolve() != directory:
                raise ValueError("linked generated bundle directory")
            manifest_path = directory / "manifest.json"
            if not manifest_path.is_file():
                continue
            manifest = read(manifest_path)
            manifests[str(manifest_path.relative_to(root))] = binding(manifest_path)
            for name, expected in manifest.get("artifacts", {}).items():
                if name.startswith(allowed):
                    register(directory, name, expected)
            for expected in manifest.get("complete_research_packets", {}).values():
                if expected["path"].startswith("research-data/"):
                    register(directory, expected["path"], expected)

    return manifests, duplicate_entries(root, candidates)


def clone_duplicate(source, target, expected):
    if source.resolve() != source or target.resolve() != target or source == target:
        raise ValueError("unlinked distinct source and target required")
    before_source, before_target = identity(source), identity(target)
    if before_source[0] != before_target[0]:
        raise ValueError("source and target must be on the same filesystem")
    if binding(source) != expected or binding(target) != expected:
        raise ValueError("duplicate content changed; original target retained")
    temporary = target.with_name(f".{target.name}.cow-{uuid.uuid4().hex}")
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("fresh clone temporary path required")
    cleanup_temporary = True
    try:
        native_clone(source, temporary)
        if temporary.stat().st_ino == source.stat().st_ino or binding(temporary) != expected:
            raise ValueError("independent byte-identical clone required")
        if identity(source) != before_source or identity(target) != before_target:
            raise ValueError("source or target changed during reclamation")
        shutil.copystat(target, temporary, follow_symlinks=False)
        os.replace(temporary, target)
        if binding(target) != expected or identity(source) != before_source:
            raise ValueError("post-replacement content or source identity changed")
    except OSError as caught:
        if caught.errno == errno.EEXIST:
            cleanup_temporary = False
        raise
    finally:
        if cleanup_temporary and temporary.exists():
            temporary.unlink()


def require_quiet():
    processes = subprocess.check_output(["ps", "-axo", "command="], text=True)
    blocked = {
        "serve_research.py",
        "build_site.py",
        "build_classification_inspector.py",
        "recreate_graphs.py",
        "recreate_topic_graphs.py",
        "reaggregate_cycle_topics.py",
    }
    for line in processes.splitlines():
        try:
            args = shlex.split(line)
        except ValueError:
            continue
        if any(Path(arg).name in blocked for arg in args):
            raise ValueError("stop active research servers/builders before reclaiming their files")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--scope", choices=("bundles", "previews"), default="bundles")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = args.report.absolute()
    if report.parent != ROOT / "data" or report.exists() or report.resolve() != report:
        raise ValueError("fresh unlinked report in project data/ required")
    if args.apply and sys.platform != "darwin":
        raise ValueError("APFS reclamation requires macOS; no full-copy fallback")
    if args.apply:
        require_quiet()
    manifests, duplicates = inventory(ROOT, args.scope)
    before = shutil.disk_usage(ROOT).free
    completed, error = [], None
    journal = report.with_suffix(".journal.jsonl")
    if journal.exists():
        raise ValueError("fresh reclamation journal required")
    try:
        if args.apply:
            with journal.open("x") as handle:
                for entry in duplicates:
                    expected = {key: entry[key] for key in ("sha256", "bytes")}
                    clone_duplicate(ROOT / entry["source"], ROOT / entry["target"], expected)
                    completed.append(entry)
                    handle.write(json.dumps(entry) + "\n")
                    handle.flush()
            for name, expected in manifests.items():
                if binding(ROOT / name) != expected:
                    raise ValueError(f"generated manifest changed: {name}")
    except Exception as caught:
        error = str(caught)
    after = shutil.disk_usage(ROOT).free
    result = {
        "status": "failed" if error else "verified_COW_reclamation" if args.apply else "dry_run",
        "scope": args.scope,
        "duplicate_files": len(duplicates),
        "logical_duplicate_bytes_upper_bound_not_promised_recovery": sum(
            entry["bytes"] for entry in duplicates
        ),
        "completed_files": len(completed),
        "free_bytes_before": before,
        "free_bytes_after": after,
        "observed_free_bytes_recovered": after - before,
        "all_original_paths_and_content_preserved": error is None,
        "no_hardlinks_or_full_copy_fallback": True,
        "manifests": manifests,
        "duplicates": duplicates,
        "error": error,
        "producer": binding(Path(__file__)),
    }
    with report.open("x") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key not in {"manifests", "duplicates"}},
            indent=2,
        )
    )
    if error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verify pinned current research bytes without rebuilding or certifying the study."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
GRAPH = "outputs/current-graphs-manifest.json"
GRAPH_PIN = "5be564561d6693f7cc08a3951b1fbd0ea68010bf800052c753c2ef338119c014"
INSPECTOR = "outputs/classification-inspector-2023-2024-v9/manifest.json"
INSPECTOR_PIN = "10e0a930c0d6f8f91e153612f0701d88c94b735baff502650d85e7668316d2e5"
FALSE_FLAGS = (
    "publication",
    "model_execution",
    "model_promotion",
    "scientific_approval",
    "model_input_approved",
    "training_admission",
    "analytical_admission",
    "filing_time_text_certified",
    "publication_approved",
    "party_attribution_approved",
    "independent_human_validation",
)


def safe_path(root, directory, name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or PurePosixPath(name).is_absolute()
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError(f"unsafe research path: {name}")
    path = directory / name
    if not path.is_relative_to(root) or path.resolve() != path or not path.is_file():
        raise ValueError(f"missing or linked research file: {path}")
    return path


def fingerprint(path):
    value = path.stat()
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        value.st_nlink,
    )


def binding(path):
    before = fingerprint(path)
    if not stat.S_ISREG(before[5]):
        raise ValueError(f"regular research file required: {path}")
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if fingerprint(path) != before:
        raise ValueError(f"research file changed during hashing: {path}")
    return {"sha256": digest, "bytes": before[2]}


def valid_binding(value):
    return (
        isinstance(value, dict)
        and isinstance(value.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None
        and type(value.get("bytes")) is int
        and value["bytes"] >= 0
    )


def audit(root, graph=GRAPH, graph_pin=GRAPH_PIN, inspector=INSPECTOR, inspector_pin=INSPECTOR_PIN):
    root = Path(root).resolve()
    snapshots, manifests = {}, {}

    def verify(path, expected):
        if not valid_binding(expected):
            raise ValueError(f"invalid research binding: {path}")
        before = fingerprint(path)
        if binding(path) != {key: expected[key] for key in ("sha256", "bytes")}:
            raise ValueError(f"research bytes changed: {path}")
        if fingerprint(path) != before:
            raise ValueError(f"research file changed during verification: {path}")
        snapshots.setdefault(path, before)

    def manifest(name, pin, expected=None):
        if not isinstance(pin, str) or re.fullmatch(r"[0-9a-f]{64}", pin) is None:
            raise ValueError(f"external manifest SHA-256 required: {name}")
        path = safe_path(root, root, name)
        if path in manifests:
            raise ValueError(f"repeated research manifest: {name}")
        before = fingerprint(path)
        actual = binding(path)
        if actual["sha256"] != pin:
            raise ValueError(f"manifest pin changed: {name}")
        if expected is not None:
            verify(path, expected)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin or fingerprint(path) != before:
            raise ValueError(f"manifest changed while reading: {name}")
        snapshots.setdefault(path, before)
        value = json.loads(raw)
        if not isinstance(value, dict) or not isinstance(value.get("artifacts"), dict):
            raise ValueError(f"artifact manifest required: {name}")
        if not value["artifacts"]:
            raise ValueError(f"empty artifact manifest: {name}")
        if any(value[key] is not False for key in FALSE_FLAGS if key in value):
            raise ValueError(f"unapproved research flags required: {name}")
        if value.get("scientific_certification", "not_performed") != "not_performed":
            raise ValueError(f"scientific certification is outside this audit: {name}")
        total = 0
        for relative, expected_artifact in value["artifacts"].items():
            artifact = safe_path(root, path.parent, relative)
            verify(artifact, expected_artifact)
            total += expected_artifact["bytes"]
        manifests[path] = {
            "path": name,
            "manifest": actual,
            "artifacts_verified": len(value["artifacts"]),
            "logical_artifact_bytes": total,
        }
        return value

    graphs = manifest(graph, graph_pin)
    manifest(inspector, inspector_pin)
    inputs = graphs.get("inputs")
    sources = graphs.get("source_manifests")
    if not isinstance(inputs, dict) or not isinstance(sources, dict) or not sources:
        raise ValueError("complete graph input/source-manifest bindings required")
    source_bindings = []
    for name, expected in inputs.items():
        path = safe_path(root, root, name)
        verify(path, expected)
        if path.name == "manifest.json":
            manifest(name, expected["sha256"], expected)
            source_bindings.append(expected)
    if not all(valid_binding(value) for value in sources.values()) or sorted(
        (v["sha256"], v["bytes"]) for v in sources.values()
    ) != sorted((v["sha256"], v["bytes"]) for v in source_bindings):
        raise ValueError("graph source manifests do not match complete graph inputs")
    for path, before in snapshots.items():
        if path.resolve() != path or fingerprint(path) != before:
            raise ValueError(f"research file changed during audit: {path}")
    return {
        "status": "pinned_current_research_integrity_passed",
        "scope": "declared saved artifacts and direct graph inputs; not a study release gate",
        "manifests": list(manifests.values()),
        "artifacts_verified": sum(v["artifacts_verified"] for v in manifests.values()),
        "logical_artifact_bytes": sum(v["logical_artifact_bytes"] for v in manifests.values()),
        "graph_inputs_verified": len(inputs),
        "scientific_certification": "not_performed",
        "publication_approved": False,
        "project_complete": False,
        "source_collection_or_model_execution": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--graphs", default=GRAPH)
    parser.add_argument("--graphs-sha256", default=GRAPH_PIN)
    parser.add_argument("--inspector", default=INSPECTOR)
    parser.add_argument("--inspector-sha256", default=INSPECTOR_PIN)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = args.report.absolute() if args.report else None
    try:
        if report and (
            not report.is_relative_to(root / "data")
            or report.resolve() != report
            or report.exists()
        ):
            raise ValueError("report must be a new unlinked path under project data/")
        result = audit(root, args.graphs, args.graphs_sha256, args.inspector, args.inspector_sha256)
        if report:
            with report.open("x") as handle:
                json.dump(result, handle, indent=2)
                handle.write("\n")
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

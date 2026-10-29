"""Current saved-byte integrity is explicit and never scientific certification."""

import json
import runpy
from pathlib import Path

import pytest

MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/audit_current_research.py")
)


def fixture(root):
    def bundle(folder, content):
        directory = root / folder
        directory.mkdir(parents=True)
        data = directory / "records.jsonl"
        data.write_bytes(content)
        value = {
            "publication": False,
            "model_promotion": False,
            "artifacts": {"records.jsonl": MODULE["binding"](data)},
        }
        path = directory / "manifest.json"
        path.write_text(json.dumps(value))
        return path, value

    source, _ = bundle("outputs/source", b'{"full_text":"complete source"}\n')
    inspector, inspector_value = bundle("outputs/inspector", b'{"scores":[1,2],"topic":null}\n')
    graph, graph_value = bundle("outputs/graphs", b"actual saved chart bytes")
    source_binding = MODULE["binding"](source)
    graph_value.update(
        inputs={str(source.relative_to(root)): source_binding},
        source_manifests={"source": source_binding},
    )
    graph.write_text(json.dumps(graph_value))
    args = (
        root,
        str(graph.relative_to(root)),
        MODULE["binding"](graph)["sha256"],
        str(inspector.relative_to(root)),
        MODULE["binding"](inspector)["sha256"],
    )
    return args, source, inspector, inspector_value, graph, graph_value


def current_fixture(root):
    args, _, _, _, _, value = fixture(root)
    graph = root / MODULE["GRAPH"]
    value["artifacts"] = {"graphs/" + name: item for name, item in value["artifacts"].items()}
    graph.write_text(json.dumps(value))
    args = list(args)
    args[1:3] = [MODULE["GRAPH"], MODULE["binding"](graph)["sha256"]]
    original_inspector = root / args[3]
    inspector = root / MODULE["INSPECTOR"]
    inspector.parent.mkdir(parents=True)
    inspector.write_bytes(original_inspector.read_bytes())
    (inspector.parent / "records.jsonl").write_bytes(
        (original_inspector.parent / "records.jsonl").read_bytes()
    )
    args[3:5] = [MODULE["INSPECTOR"], MODULE["binding"](inspector)["sha256"]]
    payload = sum(item["bytes"] for item in value["artifacts"].values())
    docs = root / "docs"
    docs.mkdir()
    website = docs / "WEBSITE.md"
    website.write_text(
        f"| `outputs/current-graphs-manifest.json` | Manifest SHA-256: `{args[2]}`. |\n"
        f"| `{inspector.parent.relative_to(root)}/` | Manifest SHA-256: `{args[4]}`. |\n"
        f"The manifest-declared chart payload is **{payload:,} bytes**.\n"
    )
    tracker = docs / "STATE_PROGRESS.md"
    tracker.write_text(
        "## Current presentation: fixture\n\n"
        f"Current graph manifest:\n`{args[2]}`.\n"
        f"Its 1 declared artifacts total {payload:,} bytes, excluding the manifest.\n\n"
        "## Preserved checkpoint\n\n"
        f"Current graph manifest:\n`{'f' * 64}`.\n"
        "Its 999 declared artifacts total 999 bytes.\n"
    )
    return args, website, tracker


def test_complete_saved_payloads_verify_without_certifying_or_modifying_them(tmp_path):
    args, *_ = fixture(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = MODULE["audit"](*args)
    assert result["artifacts_verified"] == 3
    assert result["graph_inputs_verified"] == 1
    assert len(result["manifests"]) == 3
    assert result["scientific_certification"] == "not_performed"
    assert result["publication_approved"] is result["project_complete"] is False
    assert result["current_handoff"]["status"] == "not_applicable_noncurrent_graph_path"
    assert all(p.read_bytes() == value for p, value in before.items())


@pytest.mark.parametrize("defect", ["same-size", "missing", "pin", "source-map", "approved"])
def test_changed_or_incomplete_current_research_is_not_accepted(tmp_path, defect):
    args, source, inspector, inspector_value, graph, graph_value = fixture(tmp_path)
    args = list(args)
    if defect == "same-size":
        path = source.parent / "records.jsonl"
        path.write_bytes(path.read_bytes().replace(b"complete", b"tampered"))
    elif defect == "missing":
        (inspector.parent / "records.jsonl").unlink()
    elif defect == "pin":
        graph.write_bytes(graph.read_bytes() + b"\n")
    elif defect == "source-map":
        graph_value["inputs"] = {}
        graph.write_text(json.dumps(graph_value))
        args[2] = MODULE["binding"](graph)["sha256"]
    else:
        inspector_value["publication"] = True
        inspector.write_text(json.dumps(inspector_value))
        args[4] = MODULE["binding"](inspector)["sha256"]
    with pytest.raises(ValueError, match="changed|missing|match|unapproved"):
        MODULE["audit"](*args)


@pytest.mark.parametrize("name", ["../outside", "/absolute", "sub/../records.jsonl"])
def test_manifest_cannot_redirect_artifact_reads_outside_its_bundle(tmp_path, name):
    args, _, inspector, value, *_ = fixture(tmp_path)
    value["artifacts"] = {name: next(iter(value["artifacts"].values()))}
    inspector.write_text(json.dumps(value))
    args = list(args)
    args[4] = MODULE["binding"](inspector)["sha256"]
    with pytest.raises(ValueError, match="unsafe"):
        MODULE["audit"](*args)


def test_symlink_and_boolean_byte_count_are_not_valid_evidence_bindings(tmp_path):
    args, source, *_ = fixture(tmp_path)
    data = source.parent / "records.jsonl"
    moved = source.parent / "actual.jsonl"
    data.rename(moved)
    data.symlink_to(moved)
    with pytest.raises(ValueError, match="linked"):
        MODULE["audit"](*args)
    data.unlink()
    moved.rename(data)
    value = json.loads(source.read_text())
    value["artifacts"]["records.jsonl"]["bytes"] = True
    source.write_text(json.dumps(value))
    graph = tmp_path / args[1]
    value = json.loads(graph.read_text())
    source_binding = MODULE["binding"](source)
    value["inputs"][str(source.relative_to(tmp_path))] = source_binding
    value["source_manifests"]["source"] = source_binding
    graph.write_text(json.dumps(value))
    args = list(args)
    args[2] = MODULE["binding"](graph)["sha256"]
    with pytest.raises(ValueError, match="invalid"):
        MODULE["audit"](*args)


def test_cli_writes_only_a_fresh_report_and_preserves_existing_reports(tmp_path, capsys):
    args, *_ = fixture(tmp_path)
    report = tmp_path / "data/audit.json"
    report.parent.mkdir()
    cli = [
        "--root",
        str(tmp_path),
        "--graphs",
        args[1],
        "--graphs-sha256",
        args[2],
        "--inspector",
        args[3],
        "--inspector-sha256",
        args[4],
        "--report",
        str(report),
    ]
    assert MODULE["main"](cli) == 0
    assert json.loads(capsys.readouterr().out)["project_complete"] is False
    before = report.read_bytes()
    assert MODULE["main"](cli) == 1
    assert "new unlinked path" in capsys.readouterr().out
    assert report.read_bytes() == before


def test_manifest_changed_after_hashing_cannot_reuse_the_earlier_pin(tmp_path, monkeypatch):
    args, _, _, _, graph, _ = fixture(tmp_path)
    namespace = MODULE["audit"].__globals__
    original = namespace["binding"]

    def changed_after_hash(path):
        result = original(path)
        if path == graph:
            path.write_bytes(path.read_bytes() + b"\n")
        return result

    monkeypatch.setitem(namespace, "binding", changed_after_hash)
    with pytest.raises(ValueError, match="manifest changed while reading"):
        MODULE["audit"](*args)


@pytest.mark.parametrize("fragment", [
    '"publication":true,"publication":false',
    '"metadata":{"source":"first","source":"second"}',
    '"metadata":NaN',
    '"metadata":Infinity',
    '"metadata":-Infinity',
    '"metadata":1e400',
])
def test_ambiguous_manifest_metadata_is_rejected_even_with_a_rebound_pin(tmp_path, fragment):
    args, _, inspector, *_ = fixture(tmp_path)
    inspector.write_text(inspector.read_text()[:-1] + "," + fragment + "}")
    args = list(args)
    args[4] = MODULE["binding"](inspector)["sha256"]
    with pytest.raises(ValueError, match="duplicate JSON key|non-finite JSON"):
        MODULE["audit"](*args)


def test_current_handoff_matches_actual_snapshot_without_rewriting_history(tmp_path):
    args, website, tracker = current_fixture(tmp_path)
    before = website.read_bytes(), tracker.read_bytes()
    result = MODULE["audit"](*args)
    assert result["current_handoff"]["status"] == "verified"
    assert result["current_handoff"]["documents_verified"] == 2
    assert result["current_handoff"]["inspector_reference"] == "verified"
    assert result["current_handoff"]["documents"] == {
        str(path.relative_to(tmp_path)): MODULE["binding"](path)
        for path in (website, tracker)
    }
    assert (website.read_bytes(), tracker.read_bytes()) == before
    assert result["publication_approved"] is result["project_complete"] is False


@pytest.mark.parametrize("defect", [
    "website-pin", "website-payload", "tracker-pin", "tracker-count", "tracker-payload",
    "duplicate-website", "duplicate-tracker", "missing-website", "missing-tracker",
    "same-row-website", "partial-tracker", "partial-website-payload",
    "inspector-pin", "inspector-path", "duplicate-inspector",
    "same-row-inspector", "missing-inspector",
])
def test_stale_current_handoff_cannot_pass_a_byte_integrity_audit(tmp_path, defect):
    args, website, tracker = current_fixture(tmp_path)
    if defect == "website-pin":
        website.write_text(website.read_text().replace(args[2], "0" * 64))
    elif defect == "website-payload":
        website.write_text(website.read_text().replace(" bytes**", "0 bytes**"))
    elif defect == "tracker-pin":
        tracker.write_text(tracker.read_text().replace(args[2], "0" * 64))
    elif defect == "tracker-count":
        tracker.write_text(tracker.read_text().replace("Its 1 declared", "Its 2 declared"))
    elif defect == "tracker-payload":
        tracker.write_text(tracker.read_text().replace(" bytes,", "0 bytes,"))
    elif defect == "duplicate-website":
        website.write_text(website.read_text() + website.read_text())
    elif defect == "duplicate-tracker":
        text = tracker.read_text()
        current = text.split("## Current presentation: fixture\n\n")[1].split("\n## ")[0]
        tracker.write_text(
            text.replace("## Preserved checkpoint", current + "## Preserved checkpoint")
        )
    elif defect == "same-row-website":
        website.write_text(website.read_text().replace(
            "Manifest SHA-256:", f"Manifest SHA-256: `{'0' * 64}`; Manifest SHA-256:",
        ))
    elif defect == "partial-tracker":
        tracker.write_text(tracker.read_text().replace(
            "Current graph manifest:",
            f"Current graph manifest:\n`{'0' * 64}`.\nCurrent graph manifest:", 1,
        ))
    elif defect == "partial-website-payload":
        website.write_text(
            website.read_text() + "\nThe manifest-declared chart payload is **unavailable**.\n"
        )
    elif defect == "inspector-pin":
        website.write_text(website.read_text().replace(args[4], "0" * 64))
    elif defect == "inspector-path":
        name = str(Path(args[3]).parent)
        website.write_text(website.read_text().replace(name, "outputs/stale-inspector"))
    elif defect in {"duplicate-inspector", "same-row-inspector", "missing-inspector"}:
        text = website.read_text()
        line = next(row for row in text.splitlines() if str(Path(args[3]).parent) in row)
        if defect == "duplicate-inspector":
            website.write_text(text + line + "\n")
        elif defect == "same-row-inspector":
            replacement = line.replace(
                "Manifest SHA-256:", f"Manifest SHA-256: `{'0' * 64}`; Manifest SHA-256:",
            )
            website.write_text(text.replace(line, replacement))
        else:
            website.write_text(text.replace(line + "\n", ""))
    elif defect == "missing-website":
        website.unlink()
    else:
        tracker.unlink()
    with pytest.raises(ValueError, match="handoff|missing|linked"):
        MODULE["audit"](*args)


def test_current_handoff_change_after_reading_is_not_accepted(tmp_path, monkeypatch):
    args, website, _ = current_fixture(tmp_path)
    namespace = MODULE["audit"].__globals__
    original = namespace["binding"]

    def change_handoff(path):
        result = original(path)
        if path == tmp_path / args[3]:
            website.write_bytes(website.read_bytes() + b"\n")
        return result

    monkeypatch.setitem(namespace, "binding", change_handoff)
    with pytest.raises(ValueError, match="changed during audit"):
        MODULE["audit"](*args)


def test_staged_inspector_audit_does_not_require_promoting_the_current_handoff(tmp_path):
    args, *_ = current_fixture(tmp_path)
    args[3] = "outputs/inspector/manifest.json"
    args[4] = MODULE["binding"](tmp_path / args[3])["sha256"]
    result = MODULE["audit"](*args)
    assert result["current_handoff"]["status"] == "verified"
    assert result["current_handoff"]["inspector_reference"] == (
        "not_applicable_noncurrent_inspector_path"
    )
    assert result["publication_approved"] is result["project_complete"] is False


def test_stale_handoff_cli_failure_does_not_create_a_success_report(tmp_path, capsys):
    args, website, _ = current_fixture(tmp_path)
    website.write_text(website.read_text().replace(args[2], "0" * 64))
    report = tmp_path / "data/audit.json"
    report.parent.mkdir()
    assert MODULE["main"]([
        "--root", str(tmp_path), "--graphs", args[1], "--graphs-sha256", args[2],
        "--inspector", args[3], "--inspector-sha256", args[4], "--report", str(report),
    ]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed" and "handoff" in result["error"]
    assert not report.exists()

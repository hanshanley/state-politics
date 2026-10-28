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


def test_complete_saved_payloads_verify_without_certifying_or_modifying_them(tmp_path):
    args, *_ = fixture(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = MODULE["audit"](*args)
    assert result["artifacts_verified"] == 3
    assert result["graph_inputs_verified"] == 1
    assert len(result["manifests"]) == 3
    assert result["scientific_certification"] == "not_performed"
    assert result["publication_approved"] is result["project_complete"] is False
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

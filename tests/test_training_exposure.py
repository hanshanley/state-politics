"""Training exposure is a source-bound census, not an independence or accuracy claim."""

import csv
import hashlib
import json
import runpy
from pathlib import Path

import pytest

MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/audit_training_exposure.py")
)


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def fixture(root):
    job, model, labels_dir = root / "job", root / "model", root / "labels"
    for path in (job / "inputs", model, labels_dir):
        path.mkdir(parents=True)
    contexts = [
        {"bill_id": "ocd-bill/a", "state": "CA"},
        {"bill_id": "ocd-bill/b", "state": "CA"},
        {"bill_id": "ocd-bill/c", "state": "WY"},
        {"bill_id": "ocd-bill/d", "state": "ME"},
    ]
    write_rows(job / "contexts.jsonl", contexts)
    labels = labels_dir / "labels.jsonl"
    refs = [
        {"record_id": "T1", "group_id": "ocd-bill/a", "split": "train",
         "domain": "bill", "text": "Alpha\u2028 policy."},
        {"record_id": "T2", "group_id": "ocd-bill/d", "split": "train",
         "domain": "bill", "text": "A metadata-only title"},
        {"record_id": "D1", "group_id": "ocd-bill/not-in-cohort", "split": "dev",
         "domain": "bill", "text": "Beta policy."},
        {"record_id": "P1", "group_id": "platform:one", "split": "train",
         "domain": "plank", "text": "Beta policy."},
    ]
    write_rows(labels, refs)
    training = {
        "labels_sha256": MODULE["binding"](labels)["sha256"],
        "split_counts": {"train": 3, "dev": 1},
    }
    (model / "training_manifest.json").write_text(json.dumps(training))
    for state in MODULE["STATES"]:
        write_rows(job / f"inputs/retained_text-{state}.jsonl", [])
    for state, values in {
        "CA": [
            ("a1", "ocd-bill/a", "Alpha\u2028 policy.", None),
            ("a2", "ocd-bill/a", "ALPHA policy!", None),
            ("b1", "ocd-bill/b", "Alpha\u2028 policy.", "source_test_record"),
        ],
        "WY": [("c1", "ocd-bill/c", "Beta policy.", None)],
    }.items():
        rows = []
        for view, bill, text, exclusion in values:
            sha = hashlib.sha256(text.encode()).hexdigest()
            rows.append({
                "input_id": "retained_text:" + view, "view_id": view,
                "bill_id": bill, "state": state, "tier": "retained_text",
                "domain": "bill", "input_sha256": sha,
                "raw_source_text_sha256": sha, "source_text_span": [0, len(text)],
                "original_source_view": {"source_type": "native_text", "text": text},
                "pre_inference_exclusion": exclusion, **MODULE["FLAGS"],
            })
        write_rows(job / f"inputs/retained_text-{state}.jsonl", rows)
    producer = Path(MODULE["input_text"].__code__.co_filename)
    topics = root / "topics.yml"
    topics.write_text("unchanged fixture taxonomy\n")
    plan = {
        "schema": "state-politics.provisional-cycle-topics.v1",
        "producer": MODULE["binding"](producer),
        "frozen_inference_runtime": MODULE["binding"](producer.with_name("modernbert.py")),
        "checkpoint": str(model), "training_manifest": MODULE["binding"](
            model / "training_manifest.json"
        ),
        "contexts": MODULE["binding"](job / "contexts.jsonl"),
        "n_contexts": 4, "tiers": ["retained_text"], "n_views_by_tier": {"retained_text": 4},
        "topics_path": str(topics), "taxonomy_sha256": MODULE["binding"](topics)["sha256"],
        "inputs": {}, **MODULE["FLAGS"],
    }
    rebind(job, labels, plan)
    return job, labels, root / "report", plan


def rebind(job, labels, plan):
    model = Path(plan["checkpoint"]) / "training_manifest.json"
    training = json.loads(model.read_bytes())
    training["labels_sha256"] = MODULE["binding"](labels)["sha256"]
    model.write_text(json.dumps(training))
    plan["training_manifest"] = MODULE["binding"](model)
    plan["model_run"] = plan["training_manifest"]["sha256"]
    plan["contexts"] = MODULE["binding"](job / "contexts.jsonl")
    for state in MODULE["STATES"]:
        name = f"inputs/retained_text-{state}.jsonl"
        plan["inputs"][name] = {
            **MODULE["binding"](job / name), "state": state, "tier": "retained_text",
            "views": len((job / name).read_bytes().split(b"\n")) - 1,
        }
    (job / "inference_plan.json").write_text(json.dumps(plan))


def run(job, labels, out):
    return MODULE["audit"](
        job, labels, out, MODULE["binding"](job / "inference_plan.json")["sha256"],
    )


def test_full_census_separates_text_identity_domain_split_and_missing_bodies(tmp_path):
    job, labels, out, _ = fixture(tmp_path)
    originals = {
        path: path.read_bytes()
        for path in tmp_path.rglob("*") if path.is_file()
    }
    result = run(job, labels, out)
    count = result["counts"]
    assert result["states_accounted_for"] == 50
    assert (count["n_contexts"], count["n_contexts_with_body"], count["n_body_gaps"]) == (4, 3, 1)
    assert (count["n_views"], count["n_pre_excluded_views"]) == (4, 1)
    assert count["train_exact_text_views"] == 2
    assert count["train_normalized_text_views"] == 3
    assert count["train_bill_identity_views"] == 2
    assert count["train_any_match_contexts"] == 3
    assert count["train_bill_identity_contexts"] == 2
    assert count["dev_exact_text_views"] == count["dev_any_match_contexts"] == 1
    views = [json.loads(line) for line in (out / "matched_views.jsonl").open()]
    assert len(views) == 4
    assert views[-1]["matches"] == {
        "dev": {"exact_text": ["D1"], "normalized_text": ["D1"]},
    }
    assert any(row["pre_inference_exclusion"] == "source_test_record" for row in views)
    contexts = [json.loads(line) for line in (out / "matched_contexts.jsonl").open()]
    assert next(row for row in contexts if row["bill_id"] == "ocd-bill/d") == {
        "bill_id": "ocd-bill/d", "state": "ME", "body_available": False,
        "matches": {"train:bill_identity": ["T2"]},
    }
    with (out / "state_counts.csv").open() as handle:
        states = list(csv.DictReader(handle))
    assert len(states) == 50
    empty = next(row for row in states if row["state"] == "AK")
    assert empty["n_contexts"] == empty["n_views"] == "0"
    assert "NOT independently held out" in result["definitions"]["no_match"]
    assert all(result[key] is False for key in (*MODULE["FLAGS"], "model_execution"))
    assert all(path.read_bytes() == raw for path, raw in originals.items())


@pytest.mark.parametrize("defect", [
    "input-bytes", "duplicate-view", "duplicate-context", "context-count",
    "partition-count", "missing-partition", "label-text-hash", "label-count",
    "promoted-view", "empty-body",
])
def test_incomplete_or_rebound_inconsistent_evidence_cannot_get_a_complete_report(tmp_path, defect):
    job, labels, out, plan = fixture(tmp_path)
    path = job / "inputs/retained_text-CA.jsonl"
    rows = [json.loads(line) for line in path.open()]
    if defect == "duplicate-view":
        rows[1] = rows[0]
    elif defect == "promoted-view":
        rows[0]["analytical_admission"] = True
    elif defect == "empty-body":
        rows[0]["original_source_view"]["text"] = ""
        rows[0]["source_text_span"] = [0, 0]
        empty_sha = hashlib.sha256(b"").hexdigest()
        rows[0]["input_sha256"] = rows[0]["raw_source_text_sha256"] = empty_sha
    write_rows(path, rows)
    if defect == "duplicate-context":
        rows = [json.loads(line) for line in (job / "contexts.jsonl").open()]
        rows[-1] = rows[0]
        write_rows(job / "contexts.jsonl", rows)
    if defect == "label-text-hash":
        rows = [json.loads(line) for line in labels.open()]
        rows[0]["text_sha256"] = "0" * 64
        write_rows(labels, rows)
    rebind(job, labels, plan)
    if defect == "input-bytes":
        path.write_bytes(path.read_bytes() + b"\n")
    elif defect == "context-count":
        plan["n_contexts"] += 1
    elif defect == "partition-count":
        plan["inputs"]["inputs/retained_text-CA.jsonl"]["views"] += 1
    elif defect == "missing-partition":
        del plan["inputs"]["inputs/retained_text-ME.jsonl"]
    elif defect == "label-count":
        model = Path(plan["checkpoint"]) / "training_manifest.json"
        training = json.loads(model.read_bytes())
        training["split_counts"]["train"] += 1
        model.write_text(json.dumps(training))
        plan["training_manifest"] = MODULE["binding"](model)
        plan["model_run"] = plan["training_manifest"]["sha256"]
    (job / "inference_plan.json").write_text(json.dumps(plan))
    with pytest.raises(ValueError):
        run(job, labels, out)
    assert not (out / "manifest.json").exists()


def test_pin_and_existing_report_fail_without_overwrite(tmp_path):
    job, labels, out, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="pin mismatch"):
        MODULE["audit"](job, labels, out, "0" * 64)
    assert not out.exists()
    run(job, labels, out)
    before = {path: path.read_bytes() for path in out.iterdir()}
    with pytest.raises(ValueError, match="fresh"):
        run(job, labels, out)
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_source_changed_after_streaming_cannot_get_a_manifest(tmp_path, monkeypatch):
    job, labels, out, _ = fixture(tmp_path)
    namespace = MODULE["audit"].__globals__
    original = namespace["input_text"]

    def raced(row):
        result = original(row)
        labels.write_bytes(labels.read_bytes() + b"\n")
        return result

    monkeypatch.setitem(namespace, "input_text", raced)
    with pytest.raises(ValueError, match="input raced"):
        run(job, labels, out)
    assert not (out / "manifest.json").exists()


def test_report_budget_failure_cannot_create_a_complete_manifest(tmp_path, monkeypatch):
    job, labels, out, _ = fixture(tmp_path)
    monkeypatch.setitem(MODULE["audit"].__globals__, "LIMIT", 256)
    with pytest.raises(ValueError, match="budget"):
        run(job, labels, out)
    assert not (out / "manifest.json").exists()


def test_cli_pin_failure_reports_error_without_creating_output(tmp_path, capsys):
    job, labels, out, _ = fixture(tmp_path)
    assert MODULE["main"]([
        "--job", str(job), "--labels", str(labels), "--out", str(out),
        "--plan-sha256", "0" * 64,
    ]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed" and "pin mismatch" in result["error"]
    assert not out.exists()

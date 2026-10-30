"""Observed exposure removal changes descriptive counts, never truth or canonical membership."""

import copy
import csv
import json
import runpy
from pathlib import Path
from xml.etree import ElementTree as ET

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from PIL import Image

MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/analyze_exposure_sensitivity.py")
)


def examples():
    rows = []
    for identity, state, topic, status, candidate_topic, candidate_status, views in [
        ("a", "CA", 1, "classified", 1, "classified", 2),
        ("b", "CA", None, "abstained", 2, "classified", 1),
        ("c", "AK", None, "unavailable", None, "unavailable", 0),
        ("d", "AK", None, "abstained", None, "excluded", 1),
    ]:
        rows.append({
            "bill_id": identity, "state": state, "topic": topic, "inference_status": status,
            "n_source_views": views, **dict.fromkeys(MODULE["FLAGS"], False),
            "abstention_reason": None if status == "classified" else "unresolved",
            "majority_candidate": {
                "status": candidate_status, "topic": candidate_topic,
                **dict.fromkeys(MODULE["FLAGS"], False),
            },
            "preserved_extra": {"unicode": "a\u2028b", "large_integer": 9007199254740993},
        })
    matches = {
        "a": {"state": "CA", "body_available": True, "matches": {"train:exact_text": ["T"]}},
        "c": {"state": "AK", "body_available": False, "matches": {"dev:bill_identity": ["D"]}},
    }
    return rows, matches


def test_missing_bodies_and_abstentions_stay_in_denominators_and_sources_are_preserved():
    rows, matches = examples()
    before = copy.deepcopy(rows)
    totals, topics, statuses, states, removed = MODULE["calculate"](iter(rows), matches, [1, 2, 3])
    assert totals == {"full": 4, "remaining": 2, "removed": 2}
    topic = next(row for row in topics if (row["rule"], row["topic"]) == ("majority", 2))
    assert topic["full_share"] == 0.25 and topic["remaining_share"] == 0.5
    assert topic["change_percentage_points"] == 25
    zero = next(row for row in topics if row["topic"] == 3)
    assert zero["change_percentage_points"] == 0
    unavailable = next(row for row in statuses if (
        row["rule"], row["subset"], row["status"]
    ) == ("majority", "removed", "unavailable"))
    assert unavailable["contexts"] == 1 and unavailable["share"] == 0.5
    assert len(states) == 50 and next(r for r in states if r["state"] == "ME")["full_contexts"] == 0
    assert [row["bill_id"] for row in removed] == ["a", "c"]
    assert rows == before and removed[0] == before[0]


def test_all_removed_is_undefined_not_zero_and_empty_removed_subset_is_readable():
    rows, _ = examples()
    matches = {
        row["bill_id"]: {"state": row["state"], "body_available": row["n_source_views"] > 0}
        for row in rows
    }
    totals, topics, statuses, _, _ = MODULE["calculate"](rows, matches, [1, 2])
    assert totals["remaining"] == 0
    assert all(row["remaining_share"] is row["change_percentage_points"] is None for row in topics)
    assert all(row["share"] is None for row in statuses if row["subset"] == "remaining")
    result = MODULE["calculate"](rows, {}, [1, 2])
    assert result[0]["removed"] == 0 and result[4] == []
    assert all(row["change_percentage_points"] == 0 for row in result[1])


@pytest.mark.parametrize("defect", [
    "duplicate", "foreign-exposure", "wrong-state", "body-mismatch",
    "body-not-boolean", "boolean-topic", "changed-baseline", "missing-status", "promoted",
])
def test_inconsistent_saved_decisions_or_exposure_fail_closed(defect):
    rows, matches = examples()
    if defect == "duplicate":
        rows.append(rows[0])
    elif defect == "foreign-exposure":
        matches["outside"] = {"state": "CA", "body_available": True}
    elif defect == "wrong-state":
        matches["a"]["state"] = "NY"
    elif defect == "body-mismatch":
        matches["c"]["body_available"] = True
    elif defect == "body-not-boolean":
        matches["a"]["body_available"] = 1
    elif defect == "boolean-topic":
        rows[0]["topic"] = True
    elif defect == "changed-baseline":
        rows[0]["majority_candidate"]["topic"] = 2
    elif defect == "missing-status":
        rows[2]["majority_candidate"]["status"] = "uncertain"
    else:
        rows[0]["majority_candidate"]["analytical_admission"] = True
    with pytest.raises(ValueError):
        MODULE["calculate"](rows, matches, [1, 2])


def test_actual_dual_plots_preserve_negative_zero_and_exposure_caveats(tmp_path):
    rows, matches = examples()
    totals, topics, *_ = MODULE["calculate"](rows, matches, [1, 2, 3])
    source = {
        code: {"candidate_contexts": 3 - code, "label": "Topic " + str(code)}
        for code in [1, 2, 3]
    }
    for row in topics:
        row["label"] = source[row["topic"]]["label"]
    figure = MODULE["plot"](topics, source, totals, tmp_path)
    texts, dimensions = [], []
    for background, color in [("substack", "F7F5F0"), ("themarginoferror", "F5F5F5")]:
        directory = tmp_path / background / "sensitivity"
        with Image.open(directory / "topic_share_change.png") as image:
            assert image.convert("RGB").getpixel((0, 0)) == tuple(bytes.fromhex(color))
            dimensions.append(image.size)
        svg = ET.parse(directory / "topic_share_change.svg").getroot()
        text = [node.text for node in svg.iter() if node.tag.endswith("}text") and node.text]
        assert "-25" in text and "+25" in text and "0" in text
        assert "Not accuracy or a held-out test." in " ".join(text)
        texts.append(text)
    assert texts[0] == texts[1] and dimensions[0] == dimensions[1]
    assert len(figure["files"]) == 4


def test_nonzero_plot_changes_never_round_to_observed_zero(tmp_path):
    rows = [
        {"rule": rule, "topic": 1, "label": "Small change",
         "change_percentage_points": value}
        for rule, value in [("unanimity", -0.000034), ("majority", 0.00000001)]
    ]
    MODULE["plot"](
        rows, {1: {"candidate_contexts": 1}},
        {"full": 100000, "remaining": 99999}, tmp_path,
    )
    svg = ET.parse(tmp_path / "substack/sensitivity/topic_share_change.svg").getroot()
    text = [node.text for node in svg.iter() if node.tag.endswith("}text") and node.text]
    assert "-3.4e-05" in text and "+1e-08" in text
    assert "-0.0000" not in text and "+0.0000" not in text


def snapshot(root):
    rows, matches = examples()
    majority, exposure, job = root / "majority", root / "exposure", root / "job"
    for folder in (majority / "decisions", majority / "chart-data", exposure, job):
        folder.mkdir(parents=True)
    flags = dict.fromkeys(MODULE["FLAGS"], False)
    bind = MODULE["binding"]
    for row in rows:
        row["model_run"] = None if row["inference_status"] == "unavailable" else "model"
        row["majority_candidate"]["policy_run"] = "policy"
    contexts = job / "contexts.jsonl"
    contexts.write_text("".join(
        json.dumps({"bill_id": row["bill_id"], "state": row["state"]}) + "\n" for row in rows
    ))
    inputs = {
        f"inputs/retained_text-{state}.jsonl": {"sha256": "0" * 64, "bytes": 0}
        for state in MODULE["STATES"]
    }
    plan = job / "inference_plan.json"
    plan.write_text(json.dumps({"model_run": "model", "inputs": inputs}))
    policy = majority / "policy_plan.json"
    policy.write_text(json.dumps({"baseline_model_run": "model"}))
    decisions = majority / "decisions/context_assignments.jsonl"
    decisions.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    baseline = job / "bill_assignments-retained_text.parquet"
    pq.write_table(pa.Table.from_pylist([
        {key: value for key, value in row.items() if key != "majority_candidate"} for row in rows
    ]), baseline)
    table = majority / "chart-data/topic_comparison.csv"
    with table.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "topic", "label", "baseline_contexts", "candidate_contexts",
        ])
        writer.writeheader()
        for code in (1, 2, 3):
            writer.writerow({
                "topic": code, "label": "Topic " + str(code),
                "baseline_contexts": int(code == 1), "candidate_contexts": int(code != 3),
            })
    manifest = {
        **flags, "original_contexts": 4, "output_codes": [1, 2, 3, None],
        "policy_run": "policy", "source_inference_inputs": {
            **inputs, "inference_plan.json": bind(plan), "contexts.jsonl": bind(contexts),
            baseline.name: bind(baseline),
            "predictions/retained_text-AK.jsonl": {"sha256": "1" * 64, "bytes": 2},
        },
        "candidate_status_counts": {
            "classified": 2, "model_rejected": 0, "uncertain": 0,
            "excluded": 1, "unavailable": 1,
        },
        "artifacts": {
            str(path.relative_to(majority)): bind(path) for path in (policy, decisions, table)
        },
    }
    (majority / "manifest.json").write_text(json.dumps(manifest))
    matched = exposure / "matched_contexts.jsonl"
    matched.write_text("".join(
        json.dumps({"bill_id": identity, **value}) + "\n"
        for identity, value in matches.items()
    ))
    census = {
        **flags, "counts": {"n_contexts": 4}, "training_split_counts": {"train": 1, "dev": 1},
        "inputs": {str(job / name): value for name, value in inputs.items()}
        | {str(plan): bind(plan), str(contexts): bind(contexts)},
        "artifacts": {"matched_contexts.jsonl": bind(matched)},
    }
    (exposure / "manifest.json").write_text(json.dumps(census))
    return majority, exposure, job, decisions, manifest


@pytest.mark.parametrize("defect", [
    None, "pin", "bytes", "outside-context", "render-race", "baseline-topic", "missing-input",
    "available-null-model",
])
def test_bound_snapshot_refuses_incomplete_or_changed_inputs(tmp_path, monkeypatch, defect):
    majority, exposure, job, decisions, manifest = snapshot(tmp_path)
    output = tmp_path / "report"
    if defect == "bytes":
        decisions.write_bytes(decisions.read_bytes() + b"\n")
    elif defect == "outside-context":
        rows = [json.loads(raw) for raw in decisions.open()]
        rows[-1]["bill_id"] = "outside"
        decisions.write_text("".join(json.dumps(row) + "\n" for row in rows))
        manifest["artifacts"]["decisions/context_assignments.jsonl"] = MODULE["binding"](decisions)
        (majority / "manifest.json").write_text(json.dumps(manifest))
    elif defect == "baseline-topic":
        path = job / "bill_assignments-retained_text.parquet"
        rows = pq.read_table(path).to_pylist()
        rows[0]["topic"] = 2
        pq.write_table(pa.Table.from_pylist(rows), path)
        manifest["source_inference_inputs"][path.name] = MODULE["binding"](path)
        (majority / "manifest.json").write_text(json.dumps(manifest))
    elif defect == "available-null-model":
        rows = [json.loads(raw) for raw in decisions.open()]
        rows[0]["model_run"] = None
        decisions.write_text("".join(json.dumps(row) + "\n" for row in rows))
        path = job / "bill_assignments-retained_text.parquet"
        base = pq.read_table(path).to_pylist()
        base[0]["model_run"] = None
        pq.write_table(pa.Table.from_pylist(base), path)
        manifest["source_inference_inputs"][path.name] = MODULE["binding"](path)
        manifest["artifacts"]["decisions/context_assignments.jsonl"] = MODULE["binding"](decisions)
        (majority / "manifest.json").write_text(json.dumps(manifest))
    elif defect == "missing-input":
        del manifest["source_inference_inputs"]["inputs/retained_text-AK.jsonl"]
        (majority / "manifest.json").write_text(json.dumps(manifest))
    elif defect == "render-race":
        original = MODULE["build"].__globals__["plot"]

        def race(*args):
            figure = original(*args)
            path = job / "contexts.jsonl"
            path.write_bytes(path.read_bytes() + b"\n")
            return figure

        monkeypatch.setitem(MODULE["build"].__globals__, "plot", race)
    args = (
        majority, "0" * 64 if defect == "pin" else MODULE["binding"](
            majority / "manifest.json"
        )["sha256"],
        exposure, MODULE["binding"](exposure / "manifest.json")["sha256"], output,
    )
    if defect:
        with pytest.raises(ValueError):
            MODULE["build"](*args)
        assert not (output / "manifest.json").exists()
    else:
        result = MODULE["build"](*args)
        assert result["totals"] == {"full": 4, "remaining": 2, "removed": 2}
        assert len(result["artifacts"]) == 8
        assert result["model_execution"] is result["canonical_cohort_changed"] is False
        assert json.loads((output / "removed_contexts.jsonl").read_text().split("\n")[0])[
            "preserved_extra"
        ] == {"unicode": "a\u2028b", "large_integer": 9007199254740993}
        with pytest.raises(ValueError, match="fresh"):
            MODULE["build"](*args)

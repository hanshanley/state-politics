"""Consumed diagnostic identities are separate exposure, never independent truth."""

import copy
import hashlib
import json
import runpy
from pathlib import Path
from xml.etree import ElementTree as ET

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from PIL import Image

MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/audit_diagnostic_exposure.py")
)
SHARED = MODULE["shared"]
SETS = MODULE["SETS"]


def examples(model="model"):
    population = [
        {
            "bill_id": "ocd-bill/" + identity,
            "state": state,
            "n_source_views": views,
            "inference_status": "abstained" if views else "unavailable",
            "model_run": model if views else None,
            **dict.fromkeys(SHARED.FLAGS, False),
        }
        for identity, state, views in [("a", "CA", 1), ("b", "CA", 0), ("c", "AK", 1)]
    ]
    known = {
        "ocd-bill/a": {
            "bill_id": "ocd-bill/a",
            "state": "CA",
            "body_available": True,
            "matches": {"train:bill_identity": ["T"]},
            "retained_extra": 9007199254740993,
        }
    }
    references = []
    for dataset, identity, state in (
        (SETS[0], "a", "CA"),
        (SETS[0], "b", "CA"),
        (SETS[1], "a", "CA"),
        (SETS[1], "outside", "AZ"),
    ):
        references.append(
            {
                "dataset": dataset,
                "reference": {
                    "record_id": dataset + ":" + identity,
                    "group_id": "ocd-bill/" + identity,
                    "state": state,
                    "domain": "bill",
                    "topic": None,
                    "extra": {"unicode": "a\u2028b", "integer": 9007199254740993},
                },
            }
        )
    return population, known, references


def test_union_is_deduplicated_and_keeps_body_gaps_ambiguity_and_complete_references():
    population, known, references = examples()
    before = copy.deepcopy((population, known, references))
    totals, states, contexts, sets = MODULE["calculate"](population, known, references, "model")
    assert totals == {
        "contexts": 3,
        "body_available": 2,
        "body_gaps": 1,
        "known_train_dev_matches": 1,
        "diagnostic_seen": 2,
        "diagnostic_overlap_known": 1,
        "additional_diagnostic_seen": 1,
        "known_seen_union": 2,
        "known_seen_body_gaps": 1,
    }
    assert len(states) == 50 and len(contexts) == 2 and len(sets) == 2
    assert next(row for row in states if row["state"] == "CA")["known_seen_share"] == 1
    assert next(row for row in states if row["state"] == "AK")["known_seen_share"] == 0
    assert next(row for row in states if row["state"] == "ME")["known_seen_share"] is None
    assert contexts[0]["matches"] == known["ocd-bill/a"]["matches"]
    assert contexts[0]["retained_extra"] == 9007199254740993
    assert len(contexts[0]["diagnostic_references"]) == 2
    assert sets[1]["outside_primary_bill_identities"] == 1
    assert population == before[0] and known == before[1]
    assert [row["reference"] for row in references] == [row["reference"] for row in before[2]]
    assert references[-1]["in_primary"] is False and references[-1]["body_available"] is None


def test_empty_cohort_and_no_diagnostics_keep_full_output_shapes_and_unknown_rates():
    totals, states, contexts, sets = MODULE["calculate"]([], {}, [], "model")
    assert totals["contexts"] == 0 and len(states) == 50 and len(sets) == 2 and not contexts
    assert all(row["known_seen_share"] is None for row in states)


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate-context",
        "duplicate-reference",
        "known-state",
        "known-body",
        "reference-state",
        "body-model",
        "promoted",
    ],
)
def test_identity_body_and_promotion_guards(defect):
    rows, known, refs = examples()
    if defect == "duplicate-context":
        rows.append(rows[0])
    elif defect == "duplicate-reference":
        refs.append(refs[0])
    elif defect == "known-state":
        known["ocd-bill/a"]["state"] = "NY"
    elif defect == "known-body":
        known["ocd-bill/a"]["body_available"] = 1
    elif defect == "reference-state":
        refs[0]["reference"]["state"] = "NY"
    elif defect == "body-model":
        rows[1]["model_run"] = "model"
    else:
        rows[0]["analytical_admission"] = True
    with pytest.raises(ValueError):
        MODULE["calculate"](rows, known, refs, "model")


def snapshot(root):
    national, evaluation, job, refs_dir = (
        root / name for name in ("national", "evaluation", "job", "references")
    )
    for path in (national, evaluation, job, refs_dir, job / "model"):
        path.mkdir(parents=True, exist_ok=True)
    bind = SHARED.binding
    model_path = job / "model/training_manifest.json"
    model_path.write_text(json.dumps({"labels_sha256": "a" * 64}))
    model = bind(model_path)["sha256"]
    rows, known, audits = examples(model)
    baseline = job / "bill_assignments-retained_text.parquet"
    pq.write_table(pa.Table.from_pylist(rows), baseline)
    plan = job / "inference_plan.json"
    plan.write_text(
        json.dumps(
            {
                "checkpoint": str(model_path.parent),
                "model_run": model,
                "training_manifest": bind(model_path),
            }
        )
    )
    matches = root / "matched_contexts.jsonl"
    matches.write_text("".join(json.dumps(row) + "\n" for row in known.values()))
    (national / "manifest.json").write_text(
        json.dumps(
            {
                **dict.fromkeys(SHARED.FLAGS, False),
                "totals": {"full": 3, "removed": 1},
                "inputs": {str(path): bind(path) for path in (plan, baseline, matches)},
            }
        )
    )
    policy = {"temperature": 1.0, "min_confidence": 0.8, "min_margin": 0.2}
    (evaluation / "fixed_policy.json").write_text(json.dumps(policy))
    reference_specs = {}
    for name in SETS:
        folder = evaluation / name
        folder.mkdir()
        references, predictions = [], []
        for audit in audits:
            if audit["dataset"] != name:
                continue
            row = audit["reference"]
            text = row["record_id"] + "\u2028complete"
            sha = hashlib.sha256(text.encode()).hexdigest()
            row.update(
                {
                    "text": text,
                    "input_sha256": sha,
                    "text_sha256": sha,
                    **dict.fromkeys(MODULE["REFERENCE_FLAGS"], False),
                }
            )
            references.append(row)
            predictions.append(
                {
                    "record_id": row["record_id"],
                    "input_sha256": sha,
                    "input_domain": "bill",
                    "model_run": model,
                    "base_model_run": model,
                    "calibration_sha256": None,
                    "retained_extra": [9007199254740993, "\u2029"],
                }
            )
        path = refs_dir / (name + ".jsonl")
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in references))
        prediction_path = folder / "predictions.jsonl"
        prediction_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in predictions)
        )
        reference_specs[name] = {
            "path": str(path),
            "sha256": bind(path)["sha256"],
            "size": path.stat().st_size,
        }
        (folder / "report.json").write_text(
            json.dumps(
                {
                    "status": "evaluated_provisional",
                    "scientific_certification": "not_performed",
                    "model_run": model,
                    "training_manifest_sha256": model,
                    "training_labels_sha256": "a" * 64,
                    "labels_sha256": bind(path)["sha256"],
                    "predictions_sha256": bind(prediction_path)["sha256"],
                    "policy_sha256": bind(evaluation / "fixed_policy.json")["sha256"],
                }
            )
        )
    (evaluation / "evaluation_plan.json").write_text(
        json.dumps(
            {
                "checkpoint": str(model_path.parent),
                "labels": {"sha256": "a" * 64},
                "fixed_decision": policy,
                "references": reference_specs,
                **dict.fromkeys(
                    ("model_promotion", "reference_edits", "threshold_tuning", "publication"), False
                ),
            }
        )
    )
    repin(evaluation)
    return national, evaluation, baseline


def repin(evaluation):
    (evaluation / "manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    str(path.relative_to(evaluation)): SHARED.binding(path)["sha256"]
                    for path in evaluation.rglob("*")
                    if path.is_file() and path.name != "manifest.json"
                },
            }
        )
    )


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "pin",
        "reference-bytes",
        "model-report",
        "unbound-plan",
        "missing-prediction",
        "input-hash",
        "promoted-reference",
        "render-race",
    ],
)
def test_bound_actual_build_and_source_failures(tmp_path, monkeypatch, defect):
    national, evaluation, baseline = snapshot(tmp_path)
    output = tmp_path / "report"
    if defect == "reference-bytes":
        path = tmp_path / "references" / (SETS[0] + ".jsonl")
        path.write_bytes(path.read_bytes() + b" ")
    elif defect == "model-report":
        path = evaluation / SETS[0] / "report.json"
        row = json.loads(path.read_bytes())
        row["model_run"] = "another"
        path.write_text(json.dumps(row))
        repin(evaluation)
    elif defect == "unbound-plan":
        path = evaluation / "manifest.json"
        row = json.loads(path.read_bytes())
        del row["files"]["evaluation_plan.json"]
        path.write_text(json.dumps(row))
    elif defect == "missing-prediction":
        path = evaluation / SETS[0] / "predictions.jsonl"
        path.write_bytes(b"\n".join(path.read_bytes().split(b"\n")[1:]))
        report_path = evaluation / SETS[0] / "report.json"
        row = json.loads(report_path.read_bytes())
        row["predictions_sha256"] = SHARED.binding(path)["sha256"]
        report_path.write_text(json.dumps(row))
        repin(evaluation)
    elif defect in ("input-hash", "promoted-reference"):
        path = tmp_path / "references" / (SETS[0] + ".jsonl")
        rows = [json.loads(raw) for raw in path.read_bytes().split(b"\n") if raw]
        rows[0]["input_sha256" if defect == "input-hash" else "human_gold"] = (
            "b" * 64 if defect == "input-hash" else True
        )
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        plan_path = evaluation / "evaluation_plan.json"
        plan = json.loads(plan_path.read_bytes())
        plan["references"][SETS[0]].update(
            {
                "sha256": SHARED.binding(path)["sha256"],
                "size": path.stat().st_size,
            }
        )
        plan_path.write_text(json.dumps(plan))
        report_path = evaluation / SETS[0] / "report.json"
        report = json.loads(report_path.read_bytes())
        report["labels_sha256"] = SHARED.binding(path)["sha256"]
        report_path.write_text(json.dumps(report))
        repin(evaluation)
    elif defect == "render-race":

        def changed_plot(*args):
            baseline.write_bytes(baseline.read_bytes() + b" ")
            return {}

        monkeypatch.setitem(MODULE["build"].__globals__, "plot", changed_plot)
    pin = SHARED.binding(evaluation / "manifest.json")["sha256"]
    if defect == "pin":
        pin = "0" * 64
    if defect:
        message = {
            "pin": "source binding changed",
            "reference-bytes": "source binding changed",
            "model-report": "report identity mismatch",
            "unbound-plan": "unbound evaluation plan",
            "missing-prediction": "missing/duplicate reference prediction",
            "input-hash": "reference/prediction input/model/provenance mismatch",
            "promoted-reference": "reference/prediction input/model/provenance mismatch",
            "render-race": "source changed during rendering",
        }[defect]
        with pytest.raises(ValueError, match=message):
            MODULE["build"](
                national,
                SHARED.binding(national / "manifest.json")["sha256"],
                evaluation,
                pin,
                output,
            )
        assert not (output / "manifest.json").exists()
        return
    result = MODULE["build"](
        national, SHARED.binding(national / "manifest.json")["sha256"], evaluation, pin, output
    )
    assert result["totals"]["known_seen_union"] == 2 and len(result["artifacts"]) == 8
    audits = [
        json.loads(raw)
        for raw in (output / "diagnostic_reference_audit.jsonl").read_bytes().split(b"\n")
        if raw
    ]
    assert len(audits) == 4 and audits[0]["reference"]["extra"]["integer"] == 9007199254740993
    assert audits[0]["prediction"]["retained_extra"] == [9007199254740993, "\u2029"]
    texts, shapes = [], []
    for destination, color in (("substack", "F7F5F0"), ("themarginoferror", "F5F5F5")):
        path = output / destination / "exposure/known_bill_identity_exposure"
        with Image.open(path.with_suffix(".png")) as image:
            assert image.size == (4200, 3900)
            assert image.convert("RGB").getpixel((0, 0)) == tuple(bytes.fromhex(color))
        svg = ET.parse(path.with_suffix(".svg")).getroot()
        text = [node.text for node in svg.iter() if node.tag.endswith("}text") and node.text]
        assert "no cohort" in text and "0%" in text and "100%" in text and "CA (n=2)" in text
        assert "not exact-text leakage or accuracy" in " ".join(text)
        texts.append(text)
        shapes.append(
            [
                (node.tag, node.get("d"), node.get("transform"))
                for node in svg.iter()
                if node.tag.endswith(("}path", "}text"))
            ]
        )
    assert texts[0] == texts[1] and shapes[0] == shapes[1]
    with pytest.raises(ValueError, match="fresh"):
        MODULE["build"](
            national, SHARED.binding(national / "manifest.json")["sha256"], evaluation, pin, output
        )

"""State-local rates must not be confused with volume-pooled sensitivity."""

import copy
import csv
import json
import runpy
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/analyze_state_exposure_sensitivity.py")
)
NATIONAL = MODULE["national"]


def examples():
    rows = []
    for identity, state, topic, status, candidate_topic, candidate_status, views in [
        ("a", "PA", 1, "classified", 1, "classified", 1),
        ("b", "PA", None, "abstained", 2, "classified", 1),
        ("c", "PA", None, "unavailable", None, "unavailable", 0),
        ("d", "CA", 2, "classified", 2, "classified", 1),
    ]:
        rows.append(
            {
                "bill_id": identity,
                "state": state,
                "topic": topic,
                "inference_status": status,
                "n_source_views": views,
                **dict.fromkeys(NATIONAL.FLAGS, False),
                "majority_candidate": {
                    "status": candidate_status,
                    "topic": candidate_topic,
                    **dict.fromkeys(NATIONAL.FLAGS, False),
                },
                "extra": {"unicode": "a\u2028b", "integer": 9007199254740993},
            }
        )
    return rows, {"a": {"state": "PA", "body_available": True}}


def test_state_denominators_include_missing_and_abstained_inputs_not_the_national_population():
    rows, matches = examples()
    before = copy.deepcopy(rows)
    original, topics, statuses, peaks = MODULE["calculate"](iter(rows), matches, [1, 2, 3])
    assert len(topics) == 300 and len(statuses) == 1200 and len(peaks) == 100
    selected = next(
        row for row in topics if (row["state"], row["rule"], row["topic"]) == ("PA", "majority", 2)
    )
    assert selected["full_share"] == 1 / 3 and selected["remaining_share"] == 1 / 2
    assert selected["change_percentage_points"] == pytest.approx(100 / 6)
    national = next(row for row in original[1] if (row["rule"], row["topic"]) == ("majority", 2))
    assert national["change_percentage_points"] != selected["change_percentage_points"]
    gaps = next(
        row
        for row in statuses
        if (row["state"], row["rule"], row["subset"], row["status"])
        == ("PA", "majority", "remaining", "unavailable")
    )
    assert gaps["contexts"] == 1 and gaps["denominator"] == 2 and gaps["share"] == 0.5
    peak = next(row for row in peaks if (row["state"], row["rule"]) == ("PA", "majority"))
    assert peak["peak_topic"] == 1
    assert peak["peak_signed_change_percentage_points"] == pytest.approx(-100 / 3)
    assert rows == before


def test_empty_original_all_removed_and_observed_zero_are_distinct():
    rows, _ = examples()
    matches = {"d": {"state": "CA", "body_available": True}}
    _, topics, statuses, peaks = MODULE["calculate"](rows, matches, [1, 2, 3])
    me = next(row for row in peaks if row["state"] == "ME")
    ca = next(row for row in peaks if row["state"] == "CA")
    pa = next(row for row in peaks if row["state"] == "PA")
    assert me["comparison_status"] == "no_full_contexts"
    assert ca["comparison_status"] == "no_remaining_contexts"
    assert me["max_absolute_change_percentage_points"] is None
    assert ca["max_absolute_change_percentage_points"] is None
    assert pa["max_absolute_change_percentage_points"] == 0 and pa["peak_topic"] is None
    assert all(row["change_percentage_points"] is None for row in topics if row["state"] == "ME")
    assert all(row["share"] is None for row in statuses if row["state"] == "ME")


def test_empty_population_and_no_matches_preserve_complete_output_shapes():
    _, topics, statuses, peaks = MODULE["calculate"]([], {}, [1, 2])
    assert len(topics) == 200 and len(statuses) == 1200 and len(peaks) == 100
    assert all(row["change_percentage_points"] is None for row in topics)
    rows, _ = examples()
    assert all(
        row["change_percentage_points"] in (None, 0)
        for row in MODULE["calculate"](rows, {}, [1, 2])[1]
    )


@pytest.mark.parametrize("defect", ["duplicate", "foreign", "body", "promoted", "topic"])
def test_original_saved_decision_guards_remain_effective(defect):
    rows, matches = examples()
    if defect == "duplicate":
        rows.append(rows[0])
    elif defect == "foreign":
        matches["outside"] = {"state": "CA", "body_available": True}
    elif defect == "body":
        matches["a"]["body_available"] = False
    elif defect == "promoted":
        rows[0]["analytical_admission"] = True
    else:
        rows[0]["topic"] = True
    with pytest.raises(ValueError):
        MODULE["calculate"](rows, matches, [1, 2])


def snapshot(root):
    source = root / "national"
    source.mkdir()
    rows, matches = examples()
    decisions = root / "context_assignments.jsonl"
    decisions.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    result = NATIONAL.calculate(rows, matches, [1, 2, 3])
    for row in result[1]:
        row["label"] = "Topic " + str(row["topic"])
    for name, values in zip(
        ("topic_sensitivity.csv", "status_sensitivity.csv", "state_sensitivity.csv"),
        result[1:4],
        strict=True,
    ):
        with (source / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)
    (source / "removed_contexts.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in result[4])
    )
    manifest = {
        "status": "complete_descriptive_exposure_sensitivity_not_independent_validation",
        "totals": result[0],
        "inputs": {str(decisions): NATIONAL.binding(decisions)},
        "artifacts": {path.name: NATIONAL.binding(path) for path in source.iterdir()},
        **dict.fromkeys(
            (*NATIONAL.FLAGS, "model_execution", "model_promotion", "canonical_cohort_changed"),
            False,
        ),
        "producer": NATIONAL.binding(Path(NATIONAL.__file__)),
        "renderer": NATIONAL.binding(MODULE["ROOT"] / "scripts/render_current_graphs.py"),
        "theme": NATIONAL.binding(Path(NATIONAL.theme.__file__)),
    }
    (source / "manifest.json").write_text(json.dumps(manifest))
    return source, manifest, decisions


@pytest.mark.parametrize("defect", [None, "pin", "bytes", "national-drift", "render-race"])
def test_bound_build_actual_exports_and_source_failures(tmp_path, monkeypatch, defect):
    source, manifest, decisions = snapshot(tmp_path)
    output = tmp_path / "new"
    if defect == "bytes":
        decisions.write_bytes(decisions.read_bytes() + b"\n")
    elif defect == "national-drift":
        path = source / "state_sensitivity.csv"
        path.write_text(path.read_text().replace("PA,3,", "PA,4,"))
        manifest["artifacts"][path.name] = NATIONAL.binding(path)
        (source / "manifest.json").write_text(json.dumps(manifest))
    elif defect == "render-race":

        def changed_plot(*args):
            decisions.write_bytes(decisions.read_bytes() + b" ")
            return {}

        monkeypatch.setitem(MODULE["build"].__globals__, "plot", changed_plot)
    pin = NATIONAL.binding(source / "manifest.json")["sha256"]
    if defect == "pin":
        pin = "0" * 64
    if defect:
        message = {
            "pin": "source binding changed",
            "bytes": "source binding changed",
            "national-drift": "national reconstruction failed",
            "render-race": "source changed during rendering",
        }[defect]
        with pytest.raises(ValueError, match=message):
            MODULE["build"](source, pin, output)
        assert not (output / "manifest.json").exists()
        return
    result = MODULE["build"](source, pin, output)
    assert len(result["artifacts"]) == 7
    assert result["totals"] == manifest["totals"]
    texts, geometries = [], []
    for destination, color in (("substack", "F7F5F0"), ("themarginoferror", "F5F5F5")):
        path = output / destination / "sensitivity/state_topic_share_change"
        with Image.open(path.with_suffix(".png")) as image:
            assert image.size == (4050, 3900)
            assert image.convert("RGB").getpixel((0, 0)) == tuple(bytes.fromhex(color))
        svg = ET.parse(path.with_suffix(".svg")).getroot()
        text = [node.text for node in svg.iter() if node.tag.endswith("}text") and node.text]
        assert "no cohort" in text and "0" in text and "33.33" in text
        assert "PA (3 / 2)" in text and "ME (0 / 0)" in text
        assert "Not accuracy or a held-out test." in " ".join(text)
        texts.append(text)
        geometries.append(
            [
                (node.tag, node.get("d"), node.get("transform"))
                for node in svg.iter()
                if node.tag.endswith(("}path", "}text"))
            ]
        )
    assert texts[0] == texts[1] and geometries[0] == geometries[1]
    with pytest.raises(ValueError, match="fresh"):
        MODULE["build"](source, pin, output)


def test_actual_plot_distinguishes_all_removed_tiny_change_and_empty_cohort(tmp_path):
    rows, _ = examples()
    _, _, _, peaks = MODULE["calculate"](
        rows, {"d": {"state": "CA", "body_available": True}}, [1, 2, 3]
    )
    for row in peaks:
        if row["state"] == "PA":
            row["max_absolute_change_percentage_points"] = 0.000034
    MODULE["plot"](peaks, tmp_path)
    svg = ET.parse(tmp_path / "substack/sensitivity/state_topic_share_change.svg").getroot()
    text = [node.text for node in svg.iter() if node.tag.endswith("}text") and node.text]
    assert "no remaining" in text and "no cohort" in text and "3.4e-05" in text
    assert "0.0000" not in text


def test_output_cannot_be_nested_in_an_upstream_immutable_job(tmp_path):
    source, manifest, _ = snapshot(tmp_path)
    job = tmp_path / "immutable"
    job.mkdir()
    plan = job / "inference_plan.json"
    plan.write_text("{}")
    manifest["inputs"][str(plan)] = NATIONAL.binding(plan)
    (source / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="immutable source directory"):
        MODULE["build"](source, NATIONAL.binding(source / "manifest.json")["sha256"], job / "new")
    assert not (job / "new").exists()

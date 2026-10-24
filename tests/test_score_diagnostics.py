import copy
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest

from state_politics.analysis.cycle_topics import FLAGS, binding
from state_politics.analysis.modernbert import decide

SPEC = importlib.util.spec_from_file_location(
    "complete_score_diagnostics",
    Path(__file__).resolve().parents[1] / "scripts/recreate_score_diagnostics.py",
)
diagnostics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostics)
CODES = [1, 2, None]
DECISION = {"temperature": 1.0, "min_confidence": 0.8, "min_margin": 0.2}


def view(logits, *, sha="a", suffix="first", exclusion=None):
    result = asdict(decide(logits, CODES, **DECISION))
    row = {
        **result, **dict.fromkeys(FLAGS, False),
        "input_id": "input-" + suffix, "bill_id": "original-bill",
        "input_sha256": sha * 64, "output_codes": json.dumps(CODES),
        "logits": json.dumps(logits), "scores": json.dumps(result["scores"]),
        "n_input_tokens": 42, "score_type": "uncalibrated_softmax", "calibration_sha256": None,
    }
    if exclusion:
        row.update(abstention_reason=exclusion, n_input_tokens=None)
    row["score_diagnostics"] = {
        "output_scores": diagnostics.prediction_scores(row, CODES, DECISION)}
    return row


def context(views, status="abstained", reason="all_source_views_abstained", topic=None):
    reasons = {}
    for row in views:
        if row["abstention_reason"] is not None:
            key = row["abstention_reason"]
            reasons[key] = reasons.get(key, 0) + 1
    return {
        "bill_id": "original-bill", "state": "HI", "session_identifier": "original-session",
        "source_filing_date": None, "n_source_views": len(views),
        "inference_status": status, "abstention_reason": reason,
        "view_abstention_reasons": json.dumps(reasons), "topic": topic,
    }


def test_supervised_rejection_is_not_removed_or_renormalized_into_a_topic():
    rows = [view([[-5, -4, 7]])]
    result = diagnostics.context_diagnostics(context(rows), rows, CODES)
    assert result["decision_category"] == "supervised_rejection"
    assert result["mean_rejection_score"] > 0.99
    assert sum(result["mean_output_scores"][:2]) < 0.01
    assert sum(result["mean_output_scores"]) == pytest.approx(1)
    assert result["n_scored_views"] == 1


def test_exact_duplicate_sources_do_not_overweight_context_or_hide_disagreement():
    rows = [
        view([[7, 0, -2]]),
        view([[7, 0, -2]], suffix="duplicate"),
        view([[0, 7, -2]], sha="b", suffix="other-source"),
    ]
    original = context(rows, reason="source_alternative_disagreement")
    before = copy.deepcopy(original)
    result = diagnostics.context_diagnostics(original, rows, CODES)
    expected = (
        np.array(rows[0]["score_diagnostics"]["output_scores"])
        + np.array(rows[2]["score_diagnostics"]["output_scores"])
    ) / 2
    np.testing.assert_allclose(result["mean_output_scores"], expected)
    assert result["source_argmax_disagrees"]
    assert result["n_scored_views"] == 3 and result["n_distinct_scored_inputs"] == 2
    assert result["minimum_source_output_scores"][0] < result["mean_output_scores"][0]
    assert result["maximum_source_output_scores"][0] > result["mean_output_scores"][0]
    assert original == before and original["topic"] is None
    rows[-1]["input_sha256"] = rows[0]["input_sha256"]
    with pytest.raises(ValueError, match="same input has different frozen scores"):
        diagnostics.context_diagnostics(original, rows, CODES)


def test_missing_text_and_explicit_exclusion_have_no_fabricated_scores():
    missing = diagnostics.context_diagnostics(
        context([], status="unavailable", reason="no_supplied_retained_text"), [], CODES)
    excluded_views = [view([], exclusion="source_test_record")]
    excluded = diagnostics.context_diagnostics(context(excluded_views), excluded_views, CODES)
    assert missing["decision_category"] == "unavailable"
    assert excluded["decision_category"] == "source_test_record"
    assert missing["mean_output_scores"] is excluded["mean_output_scores"] is None
    assert missing["mean_rejection_score"] is excluded["mean_rejection_score"] is None
    assert missing["n_source_views"] == 0 and excluded["n_excluded_views"] == 1


def test_window_conflict_is_not_reclassified_as_just_low_confidence():
    rows = [view([[7, 0, -2], [0, 7, -2]])]
    result = diagnostics.context_diagnostics(context(rows), rows, CODES)
    assert result["decision_category"] == "mixed_chunk_topics"
    assert result["source_argmax_disagrees"] is False
    assert result["mean_output_scores"][0] == pytest.approx(result["mean_output_scores"][1])
    assert result["mean_score_entropy_bits"] > 1


@pytest.mark.parametrize("defect", ["saved_score", "nonfinite_logit", "code_order"])
def test_changed_scores_or_output_maps_fail_instead_of_emitting_plausible_diagnostics(defect):
    row = view([[7, 0, -2]])
    if defect == "saved_score":
        scores = json.loads(row["scores"])
        scores[0] = 0.1
        row["scores"] = json.dumps(scores)
    elif defect == "nonfinite_logit":
        row["logits"] = "[[NaN,0,-2]]"
    else:
        row["output_codes"] = "[2,1,null]"
    with pytest.raises(ValueError):
        diagnostics.prediction_scores(row, CODES, DECISION)


def test_complete_diagnostic_download_keeps_original_full_text_and_original_zip(tmp_path):
    text = tmp_path / "complete-text.jsonl"
    text.write_text(json.dumps({"text": "Complete policy text.\u2028No metadata substitute."}))
    prediction = tmp_path / "prediction.jsonl"
    prediction.write_text('{"scores":[0.1,0.2,0.7]}\n')
    source, target = tmp_path / "original.zip", tmp_path / "complete-diagnostics.zip"
    original = {"inputs/full.jsonl": text, "predictions/full.jsonl": prediction}
    with ZipFile(source, "x") as archive:
        for name, path in original.items():
            archive.write(path, name)
    before = binding(source)
    extra = tmp_path / "context_scores.jsonl"
    extra.write_text('{"mean_output_scores":[0.1,0.2,0.7]}\n')
    members = diagnostics.complete_zip(
        source, target, {name: binding(path) for name, path in original.items()},
        {"score-diagnostics/context_scores.jsonl": extra},
    )
    assert binding(source) == before
    with ZipFile(target) as archive:
        assert set(archive.namelist()) == set(members)
        assert archive.read("inputs/full.jsonl") == text.read_bytes()
        assert archive.read("predictions/full.jsonl") == prediction.read_bytes()

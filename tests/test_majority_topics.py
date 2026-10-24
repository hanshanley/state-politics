import math
from dataclasses import replace

import pytest

from state_politics.analysis.majority_topics import source_majority, window_majority
from state_politics.analysis.modernbert import decide

CODES = [1, 2, None]
GATES = {"temperature": 1.0, "min_confidence": 0.8, "min_margin": 0.2}
SOURCE_GATES = {"min_confidence": 0.8, "min_margin": 0.2}
A, B, REJECT = [8, -8, -8], [-8, 8, -8], [-8, -8, 8]


def result(windows):
    return window_majority(windows, CODES, **GATES)


def test_two_of_three_windows_assign_instead_of_unanimity_veto_without_renormalization():
    old = decide([A, A, B], CODES, **GATES)
    new = result([A, A, B])
    assert old.topic is None and old.abstention_reason == "mixed_chunk_topics"
    assert new.status == "classified" and new.topic == 1
    assert new.electorate == 3 and new.support == 2 and new.vote_counts == (2, 1, 0)
    assert new.disagreement_present and new.supporting_score > 0.99
    assert new.mean_output_scores[0] == pytest.approx(2 / 3, abs=1e-6)
    assert sum(new.mean_output_scores) == pytest.approx(1)
    assert sum(new.supporting_output_scores) == pytest.approx(1)
    assert new.mean_output_scores[-1] > 0


@pytest.mark.parametrize("windows", [[A, B], [A, B, REJECT], [A, A, B, REJECT]])
def test_ties_and_pluralities_are_not_strict_majorities(windows):
    new = result(windows)
    assert new.status == "uncertain" and new.topic is None
    assert new.reason == "no_strict_window_majority"
    assert new.supporting_output_scores is None


def test_majority_of_weak_windows_does_not_bypass_the_supporting_score_gate():
    weak = [math.log(p) for p in [0.7, 0.2, 0.1]]
    new = result([weak, weak, B])
    assert new.support == 2 and new.electorate == 3
    assert new.status == "uncertain"
    assert new.reason == "supporting_score_below_threshold"


def test_source_majority_retains_dissent_and_deduplicates_exact_input_copies():
    a, b = result([A]), result([B])
    sources = [("a" * 64, a), ("b" * 64, a), ("c" * 64, b)]
    new = source_majority(sources, CODES, **SOURCE_GATES)
    assert new.status == "classified" and new.topic == 1
    assert new.vote_counts == (2, 1, 0) and new.disagreement_present
    duplicate = source_majority(
        [("a" * 64, a)] * 8 + [("b" * 64, b)], CODES, **SOURCE_GATES)
    assert duplicate.status == "uncertain" and duplicate.electorate == 2
    assert duplicate.reason == "no_strict_source_majority"
    with pytest.raises(ValueError, match="identical source input"):
        source_majority([("a" * 64, a), ("a" * 64, b)], CODES, **SOURCE_GATES)


def test_uncertain_sources_remain_in_denominator_and_rejection_is_a_separate_vote():
    uncertain = result([A, B])
    a = result([A])
    mixed = source_majority([("a" * 64, a), ("b" * 64, uncertain)], CODES, **SOURCE_GATES)
    assert mixed.status == "uncertain" and mixed.abstaining_votes == 1
    rejected = source_majority(
        [("a" * 64, result([REJECT, REJECT, A]))], CODES, **SOURCE_GATES)
    assert rejected.status == "model_rejected" and rejected.topic is None
    assert rejected.vote_counts[-1] == rejected.support == 1
    assert rejected.mean_output_scores[-1] == pytest.approx(2 / 3, abs=1e-6)
    assert rejected.supporting_output_scores[-1] > 0.99


def test_unanimous_frozen_acceptance_is_preserved_and_empty_inputs_remain_scoreless():
    windows = [[math.log(p) for p in [0.79, 0.11, 0.1]], A]
    old, new = decide(windows, CODES, **GATES), result(windows)
    assert old.topic == new.topic == 1
    assert new.mean_output_scores == pytest.approx(old.scores)
    missing = source_majority([], CODES, **SOURCE_GATES)
    assert missing.status == "unscored" and missing.mean_output_scores is None
    assert missing.supporting_output_scores is None
    with pytest.raises(ValueError, match="fabricated window votes"):
        result([])


def test_inconsistent_accepted_source_decision_cannot_be_counted_as_a_valid_vote():
    malformed = replace(result([A]), topic=2)
    with pytest.raises(ValueError, match="inconsistent accepted source"):
        source_majority([("a" * 64, malformed)], CODES, **SOURCE_GATES)


@pytest.mark.parametrize("windows", [[[float("nan"), 0, 0]], [[1, 2]], [[float("inf"), 0, 0]]])
def test_malformed_or_nonfinite_window_evidence_is_rejected(windows):
    with pytest.raises(ValueError):
        result(windows)

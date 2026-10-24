"""Explicitly provisional strict-majority aggregation of frozen full-document outputs."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from state_politics.analysis.modernbert import decide

POLICY = "strict_window_majority_then_distinct_input_majority_supporting_scores.v1"


@dataclass(frozen=True)
class Majority:
    status: str
    topic: int | None
    reason: str | None
    winner_output_index: int | None
    electorate: int
    support: int
    vote_counts: tuple[int, ...]
    abstaining_votes: int
    mean_output_scores: tuple[float, ...] | None
    supporting_output_scores: tuple[float, ...] | None
    supporting_score: float | None
    supporting_margin: float | None
    disagreement_present: bool


def _validate(codes, min_confidence, min_margin):
    if (len(codes) < 2 or codes[-1] is not None
            or any(type(code) is not int for code in codes[:-1])
            or len(set(codes)) != len(codes)
            or not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1
            or not math.isfinite(min_margin) or not 0 <= min_margin <= 1):
        raise ValueError("invalid majority output map or score gates")


def _mean(profiles, width):
    if not profiles:
        return None
    for row in profiles:
        if (len(row) != width or any(not math.isfinite(x) or not 0 <= x <= 1 for x in row)
                or not math.isclose(math.fsum(row), 1, rel_tol=0, abs_tol=1e-12)):
            raise ValueError("invalid complete majority score vector")
    return tuple(math.fsum(row[i] for row in profiles) / len(profiles) for i in range(width))


def _aggregate(codes, votes, profiles, full_profiles, *, level, min_confidence, min_margin):
    _validate(codes, min_confidence, min_margin)
    if len(votes) != len(profiles) or len(votes) != len(full_profiles):
        raise ValueError("majority electorate/profile mismatch")
    counts = [0] * len(codes)
    for vote in votes:
        if vote is not None:
            if type(vote) is not int or not 0 <= vote < len(codes):
                raise ValueError("invalid majority vote index")
            counts[vote] += 1
    means = _mean(full_profiles, len(codes))
    winner = next((i for i, count in enumerate(counts) if count * 2 > len(votes)), None)
    supporting = _mean(
        [profile for vote, profile in zip(votes, profiles, strict=True) if vote == winner],
        len(codes),
    ) if winner is not None else None
    score = supporting[winner] if supporting is not None else None
    margin = (score - max(value for i, value in enumerate(supporting) if i != winner)
              if supporting is not None else None)
    reason = (
        "no_scored_inputs" if not votes
        else f"no_strict_{level}_majority" if winner is None
        else "supporting_score_below_threshold" if score < min_confidence
        else "supporting_margin_below_threshold" if margin < min_margin
        else None
    )
    status = (
        "unscored" if not votes else "uncertain" if reason
        else "model_rejected" if codes[winner] is None else "classified"
    )
    return Majority(
        status=status, topic=codes[winner] if status == "classified" else None,
        reason=reason, winner_output_index=winner, electorate=len(votes),
        support=counts[winner] if winner is not None else max(counts, default=0),
        vote_counts=tuple(counts), abstaining_votes=len(votes) - sum(counts),
        mean_output_scores=means, supporting_output_scores=supporting,
        supporting_score=score, supporting_margin=margin,
        disagreement_present=sum(count > 0 for count in counts) > 1,
    )


def window_majority(
    logits: Sequence[Sequence[float]], codes: Sequence[int | None], *,
    temperature: float, min_confidence: float, min_margin: float,
) -> Majority:
    """Count all windows; gate the winning coalition, not its diluted whole-bill mean."""
    _validate(codes, min_confidence, min_margin)
    if not logits:
        raise ValueError("excluded/missing inputs must not receive fabricated window votes")
    profiles = [
        decide([list(window)], list(codes), temperature=temperature,
               min_confidence=min_confidence, min_margin=min_margin).scores
        for window in logits
    ]
    votes = [max(range(len(codes)), key=lambda i: row[i]) for row in profiles]
    return _aggregate(codes, votes, profiles, profiles, level="window",
                      min_confidence=min_confidence, min_margin=min_margin)


def source_majority(
    sources: Sequence[tuple[str, Majority]], codes: Sequence[int | None], *,
    min_confidence: float, min_margin: float,
) -> Majority:
    """One vote per exact input string; uncertain sources remain in the denominator."""
    _validate(codes, min_confidence, min_margin)
    unique = {}
    for identity, result in sources:
        if (type(identity) is not str or re.fullmatch(r"[a-f0-9]{64}", identity) is None
                or result.status not in {"classified", "model_rejected", "uncertain"}
                or result.mean_output_scores is None):
            raise ValueError("invalid scored source majority evidence")
        if result.status in {"classified", "model_rejected"}:
            winner = result.winner_output_index
            if (type(winner) is not int or not 0 <= winner < len(codes)
                    or result.supporting_output_scores is None
                    or result.topic != codes[winner]
                    or (result.status == "model_rejected") != (codes[winner] is None)):
                raise ValueError("inconsistent accepted source majority evidence")
        if identity in unique and unique[identity] != result:
            raise ValueError("identical source input has conflicting majority evidence")
        unique[identity] = result
    selected = list(unique.values())
    votes = [
        result.winner_output_index if result.status in {"classified", "model_rejected"} else None
        for result in selected
    ]
    return _aggregate(
        codes, votes, [result.supporting_output_scores for result in selected],
        [result.mean_output_scores for result in selected], level="source",
        min_confidence=min_confidence, min_margin=min_margin,
    )

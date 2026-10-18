"""Evaluate saved logits against versioned labels without promoting a model to certified."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from ..provenance import sha256_file
from .modernbert import decide
from .taxonomy import DEFAULT_TOPICS_PATH, load_topics
from .train_topics import load_examples


def wilson(successes: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.959963984540054
    proportion = successes / total
    center = (proportion + z * z / (2 * total)) / (1 + z * z / total)
    radius = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / (1 + z * z / total)
    return [max(0, center - radius), min(1, center + radius)]


def join_predictions(labels: list[dict], predictions: list[dict]) -> list[dict]:
    indexed = {}
    for prediction in predictions:
        key = prediction["record_id"]
        if key in indexed:
            raise ValueError(f"duplicate prediction: {key}")
        indexed[key] = prediction
    if set(indexed) != {row["record_id"] for row in labels}:
        raise ValueError("prediction IDs must match the selected evaluation split exactly")
    joined = []
    for row in labels:
        prediction = indexed[row["record_id"]]
        if (
            prediction.get("input_sha256") != row["text_sha256"]
            or prediction.get("input_domain") != row["domain"]
        ):
            raise ValueError(f"prediction evidence mismatch: {row['record_id']}")
        logits = prediction["logits"]
        joined.append({
            **row, "logits": json.loads(logits) if isinstance(logits, str) else logits,
        })
    return joined


def metrics(rows: list[dict], codes: list[int], policy: dict) -> dict:
    decisions = [decide(row["logits"], codes, **policy) for row in rows]
    classified = sum(decision.topic is not None for decision in decisions)
    correct = sum(
        decision.topic is not None and decision.topic == row.get("topic")
        for row, decision in zip(rows, decisions, strict=True)
    )
    null_gold = sum(row.get("topic") is None for row in rows)
    correctly_abstained = sum(
        row.get("topic") is None and decision.topic is None
        for row, decision in zip(rows, decisions, strict=True)
    )
    per_topic = []
    for code in codes:
        support = sum(row.get("topic") == code for row in rows)
        predicted = sum(decision.topic == code for decision in decisions)
        true_positive = sum(
            row.get("topic") == code and decision.topic == code
            for row, decision in zip(rows, decisions, strict=True)
        )
        precision = true_positive / predicted if predicted else None
        recall = true_positive / support if support else None
        f1 = 2 * true_positive / (support + predicted) if support + predicted else None
        per_topic.append(dict(
            topic=code, support=support, predicted=predicted, true_positive=true_positive,
            precision=precision, recall=recall, f1=f1,
        ))
    confusion = Counter(
        (row.get("topic"), decision.topic)
        for row, decision in zip(rows, decisions, strict=True)
    )
    supported = [row["f1"] for row in per_topic if row["support"]]
    reference_scores = [
        (codes.index(row["topic"]), decision.scores)
        for row, decision in zip(rows, decisions, strict=True)
        if row.get("topic") in codes and decision.scores
    ]
    nll = (
        -sum(math.log(max(scores[target], 1e-300)) for target, scores in reference_scores)
        / len(reference_scores) if reference_scores else None
    )
    brier = (
        sum(sum((score - (i == target)) ** 2 for i, score in enumerate(scores))
            for target, scores in reference_scores) / len(reference_scores)
        if reference_scores else None
    )
    return {
        "n_eligible": len(rows), "n_classified": classified,
        "n_abstained": len(rows) - classified, "n_correct_topic": correct,
        "coverage": classified / len(rows) if rows else None,
        "classified_precision": correct / classified if classified else None,
        "classified_precision_wilson95": wilson(correct, classified),
        "all_eligible_topic_accuracy": correct / len(rows) if rows else None,
        "decision_accuracy": (
            (correct + correctly_abstained) / len(rows) if rows else None
        ),
        "gold_abstention_count": null_gold,
        "correct_abstention_count": correctly_abstained,
        "macro_f1_supported_topics": sum(supported) / len(supported) if supported else None,
        "probability_metrics": {
            "scope": "single_topic_references_with_nonempty_logits",
            "n": len(reference_scores), "multiclass_log_loss": nll,
            "multiclass_brier_score": brier,
        },
        "unsupported_topics": [row["topic"] for row in per_topic if not row["support"]],
        "per_topic": per_topic,
        "confusion": [
            {"reference": reference, "prediction": prediction, "n": count}
            for (reference, prediction), count in confusion.items()
        ],
        "abstention_reasons": dict(Counter(
            decision.abstention_reason for decision in decisions if decision.topic is None
        )),
    }


def calibrate(rows, codes, *, min_precision, min_coverage, min_support):
    """Select only on development data, against explicitly supplied acceptance constraints."""
    if not rows or {row["split"] for row in rows} != {"dev"}:
        raise ValueError("calibration may use only the development split")
    if (
        not 0 < min_precision <= 1 or not 0 <= min_coverage <= 1 or min_support < 1
    ):
        raise ValueError("invalid predeclared calibration constraints")
    candidates = []
    temperatures = []
    for temperature in (0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
        result = metrics(rows, codes, dict(
            temperature=temperature, min_confidence=0, min_margin=0,
        ))
        loss = result["probability_metrics"]["multiclass_log_loss"]
        if loss is not None:
            temperatures.append((loss, temperature))
    if not temperatures:
        raise ValueError("development temperature fitting requires single-topic references")
    _, temperature = min(temperatures)
    for confidence in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99):
        for margin in (0.0, 0.1, 0.2, 0.3):
            policy = dict(
                temperature=temperature, min_confidence=confidence, min_margin=margin
            )
            result = metrics(rows, codes, policy)
            interval = result["classified_precision_wilson95"]
            if (
                result["n_classified"] >= min_support
                and result["coverage"] >= min_coverage
                and interval is not None and interval[0] >= min_precision
            ):
                candidates.append((policy, result))
    if not candidates:
        raise ValueError("no development policy meets the predeclared constraints")
    return max(candidates, key=lambda pair: (
        pair[1]["n_classified"], pair[1]["classified_precision"],
        -abs(pair[0]["temperature"] - 1),
    ))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument(
        "--predictions", type=Path, required=True, help="JSONL with source-bound logits"
    )
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--split", choices=("dev", "test", "challenge"), required=True)
    parser.add_argument("--policy", type=Path, help="frozen JSON decision policy for evaluation")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--min-precision", type=float)
    parser.add_argument("--min-coverage", type=float)
    parser.add_argument("--min-support", type=int)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.calibrate and (
        args.split != "dev" or args.policy is not None
        or any(value is None for value in (
            args.min_precision, args.min_coverage, args.min_support
        ))
    ):
        parser.error("calibration requires dev-only data and all three predeclared constraints")
    if not args.calibrate and args.policy is None:
        parser.error("evaluation requires a previously frozen --policy")
    codes = [topic.code for topic in load_topics(args.topics)]
    labels = [row for row in load_examples(args.labels, codes) if row["split"] == args.split]
    if not labels:
        parser.error("selected evaluation split has no labels")
    predictions = [json.loads(line) for line in args.predictions.read_text().splitlines() if line]
    runs = {row.get("model_run") for row in predictions}
    if len(runs) != 1 or not all(isinstance(run, str) and run for run in runs):
        parser.error("predictions must identify exactly one nonempty model run")
    taxonomy_hash = sha256_file(args.topics)
    if {row.get("taxonomy_sha256") for row in predictions} != {taxonomy_hash}:
        parser.error("predictions must identify the requested taxonomy exactly")
    rows = join_predictions(labels, predictions)
    if args.calibrate:
        policy, result = calibrate(
            rows, codes, min_precision=args.min_precision,
            min_coverage=args.min_coverage, min_support=args.min_support,
        )
    else:
        policy = json.loads(args.policy.read_text())
        if "decision" in policy:
            base_runs = {row.get("base_model_run", row["model_run"]) for row in predictions}
            if (
                policy.get("status") != "development_calibrated"
                or policy.get("split") != "dev"
                or policy.get("taxonomy_sha256") != taxonomy_hash
                or base_runs != {policy.get("model_run")}
            ):
                parser.error("frozen calibration differs from the prediction model/taxonomy")
            policy = policy["decision"]
        result = metrics(rows, codes, policy)
    slices = {}
    for field in ("domain", "evidence_tier", "state", "party"):
        groups = sorted({str(row.get(field, "not_recorded")) for row in rows})
        slices[field] = {
            group: metrics(
                [row for row in rows if str(row.get(field, "not_recorded")) == group],
                codes, policy,
            ) for group in groups
        }
    report = {
        "status": "development_calibrated" if args.calibrate else "evaluated_provisional",
        "scientific_certification": "not_performed", "split": args.split,
        "model_run": next(iter(runs)), "decision": policy, "metrics": result, "slices": slices,
        "taxonomy_sha256": taxonomy_hash,
        "labels_sha256": sha256_file(args.labels),
        "predictions_sha256": sha256_file(args.predictions),
        "policy_sha256": sha256_file(args.policy) if args.policy is not None else None,
        "reviewer_types": dict(Counter(row["reviewer_type"] for row in labels)),
        "limitations": [
            "review provenance and representative sampling require separate audit",
            "Wilson intervals treat rows as independent; clustered uncertainty remains required",
            "development selection is not held-out certification",
        ],
    }
    if args.calibrate:
        report["predeclared_constraints"] = {
            "min_precision_wilson_lower95": args.min_precision,
            "min_coverage": args.min_coverage, "min_classified": args.min_support,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

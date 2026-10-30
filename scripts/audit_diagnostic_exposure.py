#!/usr/bin/env python3
"""Account named consumed bill diagnostics separately from saved training/dev matches."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

import pyarrow.parquet as pq  # noqa: E402

from scripts import analyze_exposure_sensitivity as shared  # noqa: E402
from scripts.audit_current_research import safe_path  # noqa: E402

SETS = ("cycle_metadata_190", "cycle_native_39")
REFERENCE_FLAGS = (
    "human_gold",
    "independent_gold",
    "training_admission",
    "analytical_admission",
    "model_input_approved",
    "filing_time_text_certified",
)


def calculate(rows, known, references, model):
    require = shared.require
    population, diagnostic = {}, defaultdict(lambda: defaultdict(list))
    for row in rows:
        identity, state = row["bill_id"], row["state"]
        require(
            isinstance(identity, str)
            and identity.startswith("ocd-bill/")
            and identity not in population
            and state in shared.STATES,
            "duplicate/foreign primary context",
        )
        views = row["n_source_views"]
        require(
            type(views) is int
            and views >= 0
            and row["inference_status"] in shared.BASE
            and (row["inference_status"] == "unavailable") == (views == 0)
            and row["model_run"] == (model if views else None)
            and all(row.get(flag) is False for flag in shared.FLAGS),
            "primary body/model/status/approval mismatch",
        )
        population[identity] = row
    for identity, match in known.items():
        require(
            identity in population
            and match["state"] == population[identity]["state"]
            and type(match["body_available"]) is bool
            and match["body_available"] == (population[identity]["n_source_views"] > 0),
            "known exposure state/body/population mismatch",
        )
    seen = set()
    for audit in references:
        row, dataset = audit["reference"], audit["dataset"]
        key = dataset, row["record_id"]
        require(
            dataset in SETS
            and key not in seen
            and row["state"] in shared.STATES
            and row["domain"] == "bill"
            and row["group_id"].startswith("ocd-bill/"),
            "duplicate/invalid diagnostic reference",
        )
        seen.add(key)
        identity = row["group_id"]
        inside = identity in population
        require(
            not inside or population[identity]["state"] == row["state"], "diagnostic state mismatch"
        )
        audit["in_primary"] = inside
        audit["body_available"] = population[identity]["n_source_views"] > 0 if inside else None
        if inside:
            diagnostic[identity][dataset].append(row["record_id"])
    states = []
    for state in shared.STATES:
        ids = {identity for identity, row in population.items() if row["state"] == state}
        first, second = ids & set(known), ids & set(diagnostic)
        union, additional = first | second, second - first
        states.append(
            {
                "state": state,
                "contexts": len(ids),
                "body_available": sum(
                    population[identity]["n_source_views"] > 0 for identity in ids
                ),
                "body_gaps": sum(population[identity]["n_source_views"] == 0 for identity in ids),
                "known_train_dev_matches": len(first),
                "diagnostic_seen": len(second),
                "diagnostic_overlap_known": len(first & second),
                "additional_diagnostic_seen": len(additional),
                "known_seen_union": len(union),
                "known_seen_body_gaps": sum(
                    population[identity]["n_source_views"] == 0 for identity in union
                ),
                "known_seen_share": len(union) / len(ids) if ids else None,
                **{
                    name + "_contexts": sum(
                        name in diagnostic.get(identity, {}) for identity in ids
                    )
                    for name in SETS
                },
            }
        )
    contexts = []
    for identity in sorted(set(known) | set(diagnostic)):
        row = population[identity]
        contexts.append(
            {
                **known.get(
                    identity,
                    {
                        "bill_id": identity,
                        "state": row["state"],
                        "body_available": row["n_source_views"] > 0,
                        "matches": {},
                    },
                ),
                "known_train_dev_match": identity in known,
                "diagnostic_references": {
                    name: sorted(ids) for name, ids in sorted(diagnostic.get(identity, {}).items())
                },
            }
        )
    sets = []
    for name in SETS:
        selected = [audit for audit in references if audit["dataset"] == name]
        ids = {audit["reference"]["group_id"] for audit in selected}
        inside = ids & set(population)
        sets.append(
            {
                "dataset": name,
                "reference_rows": len(selected),
                "unique_bill_identities": len(ids),
                "primary_bill_identities": len(inside),
                "outside_primary_bill_identities": len(ids - set(population)),
                "overlap_known_train_dev": len(inside & set(known)),
                "additional_to_known_train_dev": len(inside - set(known)),
            }
        )
    totals = {
        key: sum(row[key] for row in states)
        for key in (
            "contexts",
            "body_available",
            "body_gaps",
            "known_train_dev_matches",
            "diagnostic_seen",
            "diagnostic_overlap_known",
            "additional_diagnostic_seen",
            "known_seen_union",
            "known_seen_body_gaps",
        )
    }
    return totals, states, contexts, sets


def plot(states, output):
    theme, plt = shared.theme, shared.plt
    ordered = sorted(
        states,
        key=lambda row: (
            -(row["known_seen_share"] if row["known_seen_share"] is not None else -1),
            row["state"],
        ),
    )
    with plt.rc_context(
        theme.RC_PARAMS
        | {
            "svg.fonttype": "none",
            "svg.hashsalt": "consumed-diagnostic-exposure",
        }
    ):
        fig, axs = shared.axes(50, panels=2, width=14, height=13)
        for ax, percent, title in zip(
            axs,
            (False, True),
            ("Observed bill identities", "Share within each state"),
            strict=True,
        ):
            left = [0.0] * 50
            for key, label, color in (
                ("known_train_dev_matches", "Training/dev bill matches", theme.MUTED),
                ("additional_diagnostic_seen", "Additional diagnostic bill matches", theme.BLUE),
            ):
                values = [
                    100 * row[key] / row["contexts"]
                    if percent and row["contexts"]
                    else 0
                    if percent
                    else row[key]
                    for row in ordered
                ]
                ax.barh(range(50), values, left=left, height=0.64, label=label, color=color)
                left = [a + b for a, b in zip(left, values, strict=True)]
            ax.set_yticks(
                range(50),
                [f"{row['state']} (n={row['contexts']:,})" for row in ordered]
                if ax is axs[0]
                else [""] * 50,
            )
            ax.tick_params(axis="y", labelsize=8)
            ax.set_ylim(49.6, -0.6)
            ax.set_title(title, fontsize=11, loc="left")
            ax.set_xlim(0, 100 if percent else max(1, max(left)) * 1.35)
            if percent:
                ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
            ax.set_xlabel(
                "Share of candidate contexts" if percent else "Known-seen bill identities"
            )
            for position, row, value in zip(range(50), ordered, left, strict=True):
                label = (
                    "no cohort"
                    if not row["contexts"]
                    else f"{100 * row['known_seen_share']:.3g}%"
                    if percent
                    else f"{row['known_seen_union']:,}"
                )
                inside = percent and value > 90
                offset = 1.5 if percent else ax.get_xlim()[1] * 0.02
                ax.text(
                    value - offset if inside else value + offset,
                    position,
                    label,
                    ha="right" if inside else "left",
                    va="center",
                    fontsize=8,
                    color="white" if inside else theme.TEXT,
                )
        return shared.save_figure(
            {
                "group": "exposure",
                "name": "known_bill_identity_exposure",
                "fig": fig,
                "title": "Known development exposure, state by state",
                "subtitle": "Training/dev bill matches plus two consumed bill-diagnostic sets; "
                "same frozen candidate cohort",
                "note": "Bill identities can match across versions or input tiers; this is not "
                "exact-text leakage or accuracy. Denominator: all contexts, including missing "
                "text. No match is not independence. Only the named diagnostic sets are covered.",
                "tables": ["state_exposure.csv", "diagnostic_sets.csv"],
            },
            output,
        )


def build(source, source_pin, evaluation, evaluation_pin, output):
    source, evaluation, output = (Path(path).absolute() for path in (source, evaluation, output))
    require, binding, fingerprint = shared.require, shared.binding, shared.fingerprint
    require(
        output.resolve() == output
        and output.parent.is_dir()
        and not output.exists()
        and not output.is_relative_to(source)
        and not output.is_relative_to(evaluation),
        "fresh unlinked output outside sources required",
    )
    snapshots, inputs = {}, {}

    def checked(path, expected):
        require(path.resolve() == path and path.is_file(), f"missing/linked source: {path}")
        before = fingerprint(path)
        require(
            shared.valid_binding(expected)
            and binding(path) == expected
            and fingerprint(path) == before,
            f"source binding changed: {path}",
        )
        snapshots[path], inputs[str(path)] = before, expected

    def manifest(directory, pin):
        path = directory / "manifest.json"
        checked(path, {"sha256": pin, "bytes": path.stat().st_size})
        return shared.strict_json(path.read_bytes())

    for path in (
        Path(__file__),
        Path(shared.__file__),
        ROOT / "scripts/render_current_graphs.py",
        Path(shared.theme.__file__),
    ):
        checked(path, binding(path))
    national, evaluated = manifest(source, source_pin), manifest(evaluation, evaluation_pin)
    require(
        all(national.get(flag) is False for flag in shared.FLAGS),
        "unapproved national source required",
    )
    roles = {}
    for name in (
        "inference_plan.json",
        "bill_assignments-retained_text.parquet",
        "matched_contexts.jsonl",
    ):
        paths = [Path(path) for path in national["inputs"] if Path(path).name == name]
        require(len(paths) == 1, f"unique source role required: {name}")
        roles[name] = paths[0]
        checked(paths[0], national["inputs"][str(paths[0])])
    job = roles["inference_plan.json"].parent
    require(not output.is_relative_to(job), "output cannot mutate frozen inference")
    plan = shared.strict_json(roles["inference_plan.json"].read_bytes())
    model_path = Path(plan["checkpoint"]) / "training_manifest.json"
    require(not output.is_relative_to(model_path.parent), "output cannot mutate model")
    checked(model_path, plan["training_manifest"])
    training = shared.strict_json(model_path.read_bytes())
    require(plan["model_run"] == plan["training_manifest"]["sha256"], "model identity mismatch")
    for name, sha in evaluated["files"].items():
        path = safe_path(evaluation, evaluation, name)
        checked(path, {"sha256": sha, "bytes": path.stat().st_size})
    require(str(evaluation / "evaluation_plan.json") in inputs, "unbound evaluation plan")
    evaluation_plan = shared.strict_json((evaluation / "evaluation_plan.json").read_bytes())
    checkpoint = Path(evaluation_plan["checkpoint"])
    checkpoint = checkpoint if checkpoint.is_absolute() else ROOT / checkpoint
    require(
        checkpoint.resolve() == model_path.parent
        and all(
            evaluation_plan.get(flag) is False
            for flag in ("model_promotion", "reference_edits", "threshold_tuning", "publication")
        ),
        "evaluation checkpoint/approval mismatch",
    )
    require(
        evaluation_plan["labels"]["sha256"] == training["labels_sha256"],
        "evaluation training-label identity mismatch",
    )
    policy_path = evaluation / "fixed_policy.json"
    require(str(policy_path) in inputs, "unbound evaluation policy")
    policy = shared.strict_json(policy_path.read_bytes())
    require(policy == evaluation_plan["fixed_decision"], "evaluation policy changed")

    def records(path):
        with path.open("rb") as handle:
            return [(ordinal, shared.strict_json(raw)) for ordinal, raw in enumerate(handle, 1)]

    known_rows = [row for _, row in records(roles["matched_contexts.jsonl"])]
    known = {row["bill_id"]: row for row in known_rows}
    require(
        len(known) == len(known_rows) == national["totals"]["removed"],
        "duplicate/incomplete known matches",
    )
    audits = []
    for name in SETS:
        ref = evaluation_plan["references"][name]
        path = Path(ref["path"])
        checked(path, {"sha256": ref["sha256"], "bytes": ref["size"]})
        require(not output.is_relative_to(path.parent), "output cannot mutate references")
        predictions_path = evaluation / name / "predictions.jsonl"
        report_path = evaluation / name / "report.json"
        require(
            str(predictions_path) in inputs
            and str(report_path) in inputs
            and str(policy_path) in inputs,
            "unbound evaluation output",
        )
        report = shared.strict_json(report_path.read_bytes())
        require(
            report["status"] == "evaluated_provisional"
            and report["scientific_certification"] == "not_performed"
            and report["model_run"] == report["training_manifest_sha256"] == plan["model_run"]
            and report["training_labels_sha256"] == training["labels_sha256"]
            and report["labels_sha256"] == ref["sha256"]
            and report["predictions_sha256"] == inputs[str(predictions_path)]["sha256"]
            and report["policy_sha256"] == inputs[str(policy_path)]["sha256"],
            "consumed evaluation report identity mismatch",
        )
        predictions = {}
        for ordinal, row in records(predictions_path):
            require(row["record_id"] not in predictions, "duplicate saved prediction")
            predictions[row["record_id"]] = (ordinal, row)
        seen = set()
        for ordinal, row in records(path):
            identity = row["record_id"]
            require(
                identity not in seen and identity in predictions,
                "missing/duplicate reference prediction",
            )
            seen.add(identity)
            prediction_ordinal, prediction = predictions[identity]
            sha = hashlib.sha256(row["text"].encode()).hexdigest()
            require(
                all(row.get(flag) is False for flag in REFERENCE_FLAGS)
                and row["text_sha256"] == row["input_sha256"] == sha
                and prediction["input_sha256"] == sha
                and prediction["input_domain"] == row["domain"] == "bill"
                and prediction["base_model_run"] == prediction["model_run"] == plan["model_run"]
                and prediction["calibration_sha256"] is None,
                "reference/prediction input/model/provenance mismatch",
            )
            require(
                row.get("bill_id", row["group_id"]) == row["group_id"],
                "conflicting reference bill identity",
            )
            audits.append(
                {
                    "dataset": name,
                    "reference_file": str(path),
                    "physical_reference_record": ordinal,
                    "prediction_file": str(predictions_path),
                    "physical_prediction_record": prediction_ordinal,
                    "reference": row,
                    "prediction": prediction,
                }
            )
        require(seen == set(predictions), "extra saved prediction")
    columns = ["bill_id", "state", "n_source_views", "inference_status", "model_run", *shared.FLAGS]
    population = pq.read_table(roles["bill_assignments-retained_text.parquet"], columns=columns)
    totals, states, contexts, sets = calculate(
        population.to_pylist(), known, audits, plan["model_run"]
    )
    require(totals["contexts"] == national["totals"]["full"], "incomplete primary population")
    for path, before in snapshots.items():
        require(fingerprint(path) == before, f"source changed during analysis: {path}")
    output.mkdir()
    for name, rows in (("state_exposure.csv", states), ("diagnostic_sets.csv", sets)):
        with (output / name).open("x", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    for name, rows in (
        ("matched_contexts.jsonl", contexts),
        ("diagnostic_reference_audit.jsonl", audits),
    ):
        with (output / name).open("x") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    figure = plot(states, output)
    artifacts = {
        str(path.relative_to(output)): binding(path) for path in output.rglob("*") if path.is_file()
    }
    result = {
        "status": "complete_named_consumed_diagnostic_identity_audit_not_validation",
        "totals": totals,
        "inputs": inputs,
        "artifacts": artifacts,
        "figure": figure,
        "definitions": {
            "diagnostics": (
                "Only the named actually evaluated bill sets; not every consumed diagnostic."
            ),
            "identity": (
                "Stable bill-ID overlap, not exact full-population input/version equivalence."
            ),
            "union": "De-duplicated known train/dev matches plus diagnostic bill identities.",
            "references": (
                "Complete original reference and saved prediction records, including ambiguity."
            ),
            "denominator": "All candidate contexts; empty cohort shares are undefined.",
            "limitation": "No match is not independence; no accuracy, causal effect or human gold.",
        },
        "producer": binding(Path(__file__)),
        **dict.fromkeys(shared.FLAGS, False),
        "model_execution": False,
        "source_collection": False,
        "model_promotion": False,
        "canonical_cohort_changed": False,
    }
    raw = json.dumps(result, indent=2, allow_nan=False) + "\n"
    require(
        sum(value["bytes"] for value in artifacts.values()) + len(raw.encode()) < 10 * 1024 * 1024,
        "report budget exceeded",
    )
    for path, before in snapshots.items():
        require(fingerprint(path) == before, f"source changed during rendering: {path}")
    with (output / "manifest.json").open("x") as handle:
        handle.write(raw)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("national", "evaluation", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--national-sha256", required=True)
    parser.add_argument("--evaluation-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = build(
            args.national, args.national_sha256, args.evaluation, args.evaluation_sha256, args.out
        )
        print(json.dumps({"status": result["status"], "totals": result["totals"]}, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

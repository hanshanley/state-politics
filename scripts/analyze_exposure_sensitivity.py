#!/usr/bin/env python3
"""Describe saved-prediction sensitivity without creating an independent test."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

import matplotlib.pyplot as plt  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from scripts.audit_current_research import (  # noqa: E402
    binding,
    fingerprint,
    strict_json,
    valid_binding,
)
from scripts.render_current_graphs import axes, save_figure  # noqa: E402
from state_politics.bills.openstates_dump import STATE_CODES  # noqa: E402
from state_politics.plotting import theme  # noqa: E402

STATES = sorted(state.upper() for state in STATE_CODES)
FLAGS = (
    "scientific_approval", "model_input_approved", "training_admission",
    "analytical_admission", "filing_time_text_certified", "publication_approved",
    "party_attribution_approved",
)
BASE = ("classified", "abstained", "unavailable")
CANDIDATE = ("classified", "model_rejected", "uncertain", "excluded", "unavailable")


def require(value, message):
    if not value:
        raise ValueError(message)


def calculate(rows, matches, codes):
    """Keep complete populations, including missing bodies, in share denominators."""
    seen, removed = set(), []
    counts = Counter()
    topics = Counter()
    states = {state: Counter() for state in STATES}
    for row in rows:
        identity, state = row["bill_id"], row["state"]
        require(identity not in seen and state in states, "duplicate/foreign context")
        seen.add(identity)
        candidate = row["majority_candidate"]
        require(
            all(row.get(flag) is False and candidate.get(flag) is False for flag in FLAGS),
            "promoted or incomplete source flags",
        )
        base_status = row["inference_status"]
        require(base_status in BASE and candidate["status"] in CANDIDATE, "invalid status")
        for status, topic in (
            (base_status, row["topic"]), (candidate["status"], candidate["topic"]),
        ):
            require(
                (status == "classified" and type(topic) is int and topic in codes)
                or (status != "classified" and topic is None),
                "status/topic inconsistency",
            )
        require(
            type(row["n_source_views"]) is int and row["n_source_views"] >= 0
            and (base_status == "unavailable") == (row["n_source_views"] == 0)
            and (candidate["status"] == "unavailable") == (base_status == "unavailable"),
            "missing-body status inconsistency",
        )
        require(
            base_status != "classified"
            or (candidate["status"] == "classified" and candidate["topic"] == row["topic"]),
            "candidate changed an accepted baseline topic",
        )
        matched = identity in matches
        if matched:
            match = matches[identity]
            require(
                type(match["body_available"]) is bool and match["state"] == state
                and match["body_available"] == (row["n_source_views"] > 0),
                "exposure state/body mismatch",
            )
            removed.append(row)
        for subset in ("full", "removed" if matched else "remaining"):
            states[state][subset + "_contexts"] += 1
            states[state][subset + "_body_gaps"] += base_status == "unavailable"
            for rule, status, topic in (
                ("unanimity", base_status, row["topic"]),
                ("majority", candidate["status"], candidate["topic"]),
            ):
                counts[rule, subset, status] += 1
                states[state][subset + "_" + rule + "_assigned"] += status == "classified"
                if topic is not None:
                    topics[rule, subset, topic] += 1
    require(set(matches) <= seen, "exposure contains contexts outside the decision population")
    totals = {
        subset: sum(states[state][subset + "_contexts"] for state in STATES)
        for subset in ("full", "remaining", "removed")
    }
    topic_rows, status_rows = [], []
    for rule, statuses in (("unanimity", BASE), ("majority", CANDIDATE)):
        for code in codes:
            full = topics[rule, "full", code]
            remaining = topics[rule, "remaining", code]
            before = full / totals["full"] if totals["full"] else None
            after = remaining / totals["remaining"] if totals["remaining"] else None
            topic_rows.append({
                "rule": rule, "topic": code,
                "full_assigned": full, "remaining_assigned": remaining,
                "removed_assigned": full - remaining,
                "full_contexts": totals["full"], "remaining_contexts": totals["remaining"],
                "full_share": before, "remaining_share": after,
                "change_percentage_points": (
                    100 * (after - before) if before is not None and after is not None else None
                ),
            })
        for subset in ("full", "remaining", "removed"):
            for status in statuses:
                status_rows.append({
                    "rule": rule, "subset": subset, "status": status,
                    "contexts": counts[rule, subset, status], "denominator": totals[subset],
                    "share": (
                        counts[rule, subset, status] / totals[subset] if totals[subset] else None
                    ),
                })
    state_rows = [
        {"state": state, **{
            subset + "_" + metric: states[state][subset + "_" + metric]
            for subset in ("full", "remaining", "removed")
            for metric in ("contexts", "body_gaps", "unanimity_assigned", "majority_assigned")
        }} for state in STATES
    ]
    return totals, topic_rows, status_rows, state_rows, removed


def plot(topics, source_topics, totals, output):
    with plt.rc_context(
        theme.RC_PARAMS | {"svg.fonttype": "none", "svg.hashsalt": "exposure-sensitivity"}
    ):
        fig, axs = axes(len(source_topics), panels=2, width=12.4, height=9)
        limit = max([abs(row["change_percentage_points"]) for row in topics
                     if row["change_percentage_points"] is not None] or [0.01])
        limit = max(limit, 0.0001) * 1.5
        for ax, rule, title, color in zip(
            axs, ("unanimity", "majority"), ("Unanimity", "Majority candidate"),
            (theme.MUTED, theme.BLUE), strict=True,
        ):
            selected = [row for row in topics if row["rule"] == rule]
            selected.sort(key=lambda row: -int(source_topics[row["topic"]]["candidate_contexts"]))
            values = [row["change_percentage_points"] for row in selected]
            ax.barh(range(len(values)), [v if v is not None else 0 for v in values], color=color)
            ax.set_yticks(range(len(values)), [row["label"] for row in selected])
            if ax is axs[1]:
                ax.set_yticklabels([])
            ax.invert_yaxis()
            ax.set_xlim(-limit, limit)
            ax.axvline(0, color=theme.TEXT, linewidth=0.6)
            ax.set_title(title, fontsize=11, loc="left")
            ax.set_xlabel("Change in share (percentage points)")
            ax.xaxis.set_major_formatter(FuncFormatter(
                lambda value, _: "0" if value == 0 else f"{value:+.3g}"
            ))
            for position, value in enumerate(values):
                label = "unavailable" if value is None else "0" if value == 0 else f"{value:+.4g}"
                x = value if value is not None else 0
                ax.text(x + (limit * 0.025 if x >= 0 else -limit * 0.025), position, label,
                        va="center", ha="left" if x >= 0 else "right", fontsize=8)
        return save_figure({
            "group": "sensitivity", "name": "topic_share_change", "fig": fig,
            "title": "Topic-count sensitivity to known saved-label matches",
            "subtitle": f"Full {totals['full']:,} versus {totals['remaining']:,} diagnostic "
                        "contexts; canonical cohort unchanged",
            "note": "Same saved decisions; observed train/dev matches removed only. Shares use "
                    "all candidate contexts, including missing text. No-match is not independence. "
                    "Not accuracy or a held-out test.",
            "tables": ["topic_sensitivity.csv"],
        }, output)


def build(majority, majority_pin, exposure, exposure_pin, output):
    majority, exposure, output = (Path(path).absolute() for path in (majority, exposure, output))
    require(
        output.resolve() == output and output.parent.is_dir() and not output.exists()
        and not output.is_relative_to(majority) and not output.is_relative_to(exposure),
        "fresh unlinked output outside the immutable sources required",
    )
    snapshots, inputs = {}, {}

    def checked(path, expected):
        require(path.resolve() == path and path.is_file(), f"missing/linked source: {path}")
        before = fingerprint(path)
        actual = binding(path)
        require(
            actual == expected and fingerprint(path) == before,
            f"source binding changed: {path}",
        )
        snapshots[path], inputs[str(path)] = before, actual

    def manifest(directory, pin):
        path = directory / "manifest.json"
        checked(path, {"sha256": pin, "bytes": path.stat().st_size})
        value = strict_json(path.read_bytes())
        require(all(value.get(flag) is False for flag in FLAGS), "unapproved source required")
        return value

    original = manifest(majority, majority_pin)
    census = manifest(exposure, exposure_pin)
    require(
        original["original_contexts"] == census["counts"]["n_contexts"]
        and set(census["training_split_counts"]) == {"train", "dev"},
        "population/saved-label scope mismatch",
    )
    for name in ("policy_plan.json", "chart-data/topic_comparison.csv"):
        checked(majority / name, original["artifacts"][name])
    policy = strict_json((majority / "policy_plan.json").read_bytes())
    plans = [Path(name) for name in census["inputs"] if Path(name).name == "inference_plan.json"]
    require(len(plans) == 1, "unique original inference plan required")
    require(not output.is_relative_to(plans[0].parent), "output cannot mutate the frozen job")
    checked(plans[0], census["inputs"][str(plans[0])])
    plan = strict_json(plans[0].read_bytes())
    required_inputs = (*plan["inputs"], "inference_plan.json", "contexts.jsonl")
    require(
        policy["baseline_model_run"] == plan["model_run"]
        and all(
            original["source_inference_inputs"].get(name)
            == census["inputs"].get(str(plans[0].parent / name))
            and name in original["source_inference_inputs"]
            and valid_binding(census["inputs"].get(str(plans[0].parent / name)))
            for name in required_inputs
        ),
        "model/input populations differ",
    )
    context_path = plans[0].parent / "contexts.jsonl"
    checked(context_path, census["inputs"][str(context_path)])
    population = {}
    with context_path.open("rb") as handle:
        for raw in handle:
            row = strict_json(raw)
            require(row["bill_id"] not in population and row["state"] in STATES,
                    "duplicate/foreign canonical context")
            population[row["bill_id"]] = row["state"]
    require(len(population) == original["original_contexts"], "canonical population mismatch")
    baseline_path = plans[0].parent / "bill_assignments-retained_text.parquet"
    checked(baseline_path, original["source_inference_inputs"][baseline_path.name])
    baseline_columns = (
        "state", "topic", "inference_status", "abstention_reason",
        "n_source_views", "model_run", *FLAGS,
    )
    baseline_table = pq.read_table(baseline_path, columns=["bill_id", *baseline_columns])
    baseline = {row["bill_id"]: row for row in baseline_table.to_pylist()}
    require(
        baseline_table.num_rows == len(baseline) == len(population)
        and set(baseline) == set(population),
        "baseline/canonical context populations differ",
    )
    checked(exposure / "matched_contexts.jsonl", census["artifacts"]["matched_contexts.jsonl"])
    matches = {}
    with (exposure / "matched_contexts.jsonl").open("rb") as handle:
        for raw in handle:
            row = strict_json(raw)
            require(
                row["bill_id"] not in matches and isinstance(row["matches"], dict)
                and row["matches"] and all(
                    key in {f"{split}:{kind}" for split in ("train", "dev")
                            for kind in ("exact_text", "normalized_text", "bill_identity")}
                    and isinstance(ids, list) and ids and all(isinstance(v, str) for v in ids)
                    for key, ids in row["matches"].items()
                ),
                "duplicate/unsupported exposure match",
            )
            matches[row["bill_id"]] = row
    codes = original["output_codes"][:-1]
    require(
        original["output_codes"][-1] is None
        and all(type(code) is int for code in codes) and len(set(codes)) == len(codes),
        "invalid output map",
    )
    decisions = majority / "decisions/context_assignments.jsonl"
    checked(decisions, original["artifacts"]["decisions/context_assignments.jsonl"])

    def records():
        with decisions.open("rb") as handle:
            for raw in handle:
                row = strict_json(raw)
                require(
                    row["model_run"] == (
                        None if row["inference_status"] == "unavailable" else plan["model_run"]
                    )
                    and row["majority_candidate"]["policy_run"] == original["policy_run"]
                    and population.get(row["bill_id"]) == row["state"]
                    and all(row.get(key) == baseline[row["bill_id"]][key]
                            for key in baseline_columns),
                    "saved prediction identity changed",
                )
                yield row

    totals, topics, statuses, states, removed = calculate(records(), matches, codes)
    require(totals["full"] == original["original_contexts"], "incomplete decision population")
    with (majority / "chart-data/topic_comparison.csv").open() as handle:
        source_topics = {int(row["topic"]): row for row in csv.DictReader(handle)}
    require(set(source_topics) == set(codes), "incomplete source topic map")
    for row in topics:
        column = "baseline_contexts" if row["rule"] == "unanimity" else "candidate_contexts"
        require(row["full_assigned"] == int(source_topics[row["topic"]][column]),
                "full-population topic reconstruction failed")
        row["label"] = source_topics[row["topic"]]["label"]
    for row in statuses:
        if row["subset"] == "full" and row["rule"] == "majority":
            require(row["contexts"] == original["candidate_status_counts"][row["status"]],
                    "full-population status reconstruction failed")
    for path, before in snapshots.items():
        require(fingerprint(path) == before, f"source changed during analysis: {path}")
    output.mkdir()

    def table(name, rows):
        with (output / name).open("x", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    table("topic_sensitivity.csv", topics)
    table("status_sensitivity.csv", statuses)
    table("state_sensitivity.csv", states)
    with (output / "removed_contexts.jsonl").open("x") as handle:
        for row in removed:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    figure = plot(topics, source_topics, totals, output)
    artifacts = {
        str(path.relative_to(output)): binding(path)
        for path in output.rglob("*") if path.is_file()
    }
    result = {
        "status": "complete_descriptive_exposure_sensitivity_not_independent_validation",
        "totals": totals, "inputs": inputs, "artifacts": artifacts, "figure": figure,
        "definitions": {
            "remaining": "Only observed saved-label train/dev matches removed; not held out.",
            "denominator": "All candidate contexts in each subset, including missing bodies.",
            "scope": "Saved-label matches only, not all consumed diagnostics or related families.",
            "removed_records": (
                "Complete saved context decision records, not full-text query exports."
            ),
        },
        "producer": binding(Path(__file__)), **dict.fromkeys(FLAGS, False),
        "renderer": binding(ROOT / "scripts/render_current_graphs.py"),
        "theme": binding(Path(theme.__file__)),
        "model_execution": False, "model_promotion": False, "canonical_cohort_changed": False,
    }
    raw = json.dumps(result, indent=2, allow_nan=False) + "\n"
    require(sum(v["bytes"] for v in artifacts.values()) + len(raw.encode()) < 10 * 1024 * 1024,
            "report budget exceeded")
    for path, before in snapshots.items():
        require(fingerprint(path) == before, f"source changed during rendering: {path}")
    with (output / "manifest.json").open("x") as handle:
        handle.write(raw)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("majority", "exposure", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--majority-sha256", required=True)
    parser.add_argument("--exposure-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = build(args.majority, args.majority_sha256, args.exposure,
                       args.exposure_sha256, args.out)
        print(json.dumps({"status": result["status"], "totals": result["totals"]}, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

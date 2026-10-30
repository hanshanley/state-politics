#!/usr/bin/env python3
"""Measure state-local descriptive sensitivity using unchanged saved decisions."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from matplotlib.ticker import FuncFormatter  # noqa: E402

from scripts import analyze_exposure_sensitivity as national  # noqa: E402


def calculate(rows, matches, codes):
    counts, statuses = Counter(), Counter()

    def observe():
        for row in rows:
            for subset in ("full", "removed" if row["bill_id"] in matches else "remaining"):
                for rule, status, topic in (
                    ("unanimity", row["inference_status"], row["topic"]),
                    (
                        "majority",
                        row["majority_candidate"]["status"],
                        row["majority_candidate"]["topic"],
                    ),
                ):
                    statuses[row["state"], rule, subset, status] += 1
                    if topic is not None:
                        counts[row["state"], rule, subset, topic] += 1
            yield row

    original = national.calculate(observe(), matches, codes)
    topic_rows, status_rows, peaks = [], [], []
    for state_row in original[3]:
        state = state_row["state"]
        full_n, left_n = state_row["full_contexts"], state_row["remaining_contexts"]
        for rule, possible in (("unanimity", national.BASE), ("majority", national.CANDIDATE)):
            selected = []
            for code in codes:
                full = counts[state, rule, "full", code]
                remaining = counts[state, rule, "remaining", code]
                before, after = (
                    full / full_n if full_n else None,
                    remaining / left_n if left_n else None,
                )
                row = {
                    "state": state,
                    "rule": rule,
                    "topic": code,
                    "full_assigned": full,
                    "remaining_assigned": remaining,
                    "removed_assigned": full - remaining,
                    "full_contexts": full_n,
                    "remaining_contexts": left_n,
                    "full_share": before,
                    "remaining_share": after,
                    "change_percentage_points": (
                        100 * (after - before) if before is not None and after is not None else None
                    ),
                }
                topic_rows.append(row)
                selected.append(row)
            for subset in ("full", "remaining", "removed"):
                denominator = state_row[subset + "_contexts"]
                for status in possible:
                    value = statuses[state, rule, subset, status]
                    status_rows.append(
                        {
                            "state": state,
                            "rule": rule,
                            "subset": subset,
                            "status": status,
                            "contexts": value,
                            "denominator": denominator,
                            "share": value / denominator if denominator else None,
                        }
                    )
            defined = [row for row in selected if row["change_percentage_points"] is not None]
            peak = (
                max(defined, key=lambda row: (abs(row["change_percentage_points"]), -row["topic"]))
                if defined
                else None
            )
            change = peak["change_percentage_points"] if peak else None
            peaks.append(
                {
                    "state": state,
                    "rule": rule,
                    "full_contexts": full_n,
                    "remaining_contexts": left_n,
                    "removed_contexts": state_row["removed_contexts"],
                    "full_body_gaps": state_row["full_body_gaps"],
                    "remaining_body_gaps": state_row["remaining_body_gaps"],
                    "comparison_status": (
                        "no_full_contexts"
                        if not full_n
                        else "no_remaining_contexts"
                        if not left_n
                        else "defined"
                    ),
                    "max_absolute_change_percentage_points": abs(change)
                    if change is not None
                    else None,
                    "peak_topic": peak["topic"] if change else None,
                    "peak_signed_change_percentage_points": change,
                }
            )
    return original, topic_rows, status_rows, peaks


def plot(peaks, output):
    theme, plt = national.theme, national.plt
    keyed = {(row["state"], row["rule"]): row for row in peaks}
    order = sorted(
        national.STATES,
        key=lambda state: (
            -max(
                (
                    keyed[state, rule]["max_absolute_change_percentage_points"]
                    for rule in ("unanimity", "majority")
                    if keyed[state, rule]["max_absolute_change_percentage_points"] is not None
                ),
                default=-1,
            ),
            state,
        ),
    )
    limit = max(
        (
            row["max_absolute_change_percentage_points"]
            for row in peaks
            if row["max_absolute_change_percentage_points"] is not None
        ),
        default=0,
    )
    limit = max(limit, 0.0001) * 1.35
    with plt.rc_context(
        theme.RC_PARAMS
        | {
            "svg.fonttype": "none",
            "svg.hashsalt": "state-exposure-sensitivity",
        }
    ):
        fig, axs = national.axes(50, panels=2, width=13.5, height=13)
        labels = [
            f"{state} ({keyed[state, 'unanimity']['full_contexts']:,} / "
            f"{keyed[state, 'unanimity']['remaining_contexts']:,})"
            for state in order
        ]
        for ax, rule, title, color in zip(
            axs,
            ("unanimity", "majority"),
            ("Unanimity", "Majority candidate"),
            (theme.MUTED, theme.BLUE),
            strict=True,
        ):
            selected = [keyed[state, rule] for state in order]
            values = [row["max_absolute_change_percentage_points"] for row in selected]
            ax.barh(
                range(50),
                [value if value is not None else 0 for value in values],
                height=0.64,
                color=color,
            )
            ax.set_yticks(range(50), labels if ax is axs[0] else [""] * 50)
            ax.tick_params(axis="y", labelsize=8)
            ax.set_ylim(49.6, -0.6)
            ax.set_xlim(0, limit)
            ax.set_title(title, fontsize=11, loc="left")
            ax.set_xlabel("Largest absolute share change (percentage points)", fontsize=9)
            ax.xaxis.set_major_formatter(
                FuncFormatter(lambda value, _: "0" if value == 0 else f"{value:.3g}")
            )
            for position, row, value in zip(range(50), selected, values, strict=True):
                label = (
                    "no cohort"
                    if row["comparison_status"] == "no_full_contexts"
                    else "no remaining"
                    if value is None
                    else "0"
                    if value == 0
                    else f"{value:.4g}"
                )
                ax.text(
                    (value or 0) + limit * 0.02, position, label, fontsize=8, ha="left", va="center"
                )
        return national.save_figure(
            {
                "group": "sensitivity",
                "name": "state_topic_share_change",
                "fig": fig,
                "title": "Known-match sensitivity varies by state",
                "subtitle": "Largest absolute change among topic shares; state labels show "
                "full / remaining context counts",
                "note": "Same saved decisions; known train/dev matches removed only. "
                "Shares use all contexts within each state, including missing text. "
                "No cohort / no remaining "
                "means unavailable. Not accuracy or a held-out test.",
                "tables": [
                    "state_topic_sensitivity.csv",
                    "state_peak_changes.csv",
                    "state_status_sensitivity.csv",
                ],
            },
            output,
        )


def build(source, pin, output):
    source, output = (Path(path).absolute() for path in (source, output))
    require, binding, fingerprint = national.require, national.binding, national.fingerprint
    require(
        output.resolve() == output
        and output.parent.is_dir()
        and not output.exists()
        and not output.is_relative_to(source),
        "fresh unlinked output required",
    )
    snapshots, inputs = {}, {}

    def checked(path, expected):
        require(
            path.resolve() == path and path.is_file() and not path.is_relative_to(output),
            "missing/linked/overlapping source",
        )
        before = fingerprint(path)
        require(
            national.valid_binding(expected)
            and binding(path) == expected
            and fingerprint(path) == before,
            f"source binding changed: {path}",
        )
        snapshots[path], inputs[str(path)] = before, expected

    manifest_path = source / "manifest.json"
    checked(manifest_path, {"sha256": pin, "bytes": manifest_path.stat().st_size})
    accepted = national.strict_json(manifest_path.read_bytes())
    require(
        accepted["status"] == "complete_descriptive_exposure_sensitivity_not_independent_validation"
        and all(
            accepted.get(flag) is False
            for flag in (
                *national.FLAGS,
                "model_execution",
                "model_promotion",
                "canonical_cohort_changed",
            )
        ),
        "unapproved saved sensitivity source required",
    )
    protected = {
        Path(name).parent
        for name in accepted["inputs"]
        if Path(name).name in ("manifest.json", "inference_plan.json")
    }
    require(
        not any(output.is_relative_to(path) for path in protected),
        "output cannot mutate an immutable source directory",
    )
    for name, expected in accepted["inputs"].items():
        checked(Path(name), expected)
    for name, expected in accepted["artifacts"].items():
        checked(source / name, expected)
    for path, expected in (
        (Path(national.__file__), accepted["producer"]),
        (ROOT / "scripts/render_current_graphs.py", accepted["renderer"]),
        (Path(national.theme.__file__), accepted["theme"]),
        (Path(__file__), binding(Path(__file__))),
    ):
        checked(path, expected)
    decision_paths = [
        Path(name) for name in accepted["inputs"] if Path(name).name == "context_assignments.jsonl"
    ]
    require(len(decision_paths) == 1, "unique original decision source required")

    def records(path):
        with path.open("rb") as handle:
            for raw in handle:
                yield national.strict_json(raw)

    removed = list(records(source / "removed_contexts.jsonl"))
    matches = {
        row["bill_id"]: {"state": row["state"], "body_available": row["n_source_views"] > 0}
        for row in removed
    }
    require(len(matches) == len(removed), "duplicate removed context")
    with (source / "topic_sensitivity.csv").open() as handle:
        old_topics = list(csv.DictReader(handle))
    labels = {}
    for row in old_topics:
        code = int(row["topic"])
        require(code not in labels or labels[code] == row["label"], "topic label conflict")
        labels[code] = row["label"]
    require(labels, "nonempty topic map required")
    original, topics, statuses, peaks = calculate(records(decision_paths[0]), matches, list(labels))
    require(
        original[0] == accepted["totals"] and original[4] == removed,
        "source population/removed record reconstruction failed",
    )
    for row in original[1]:
        row["label"] = labels[row["topic"]]
    for name, rows in zip(
        ("topic_sensitivity.csv", "status_sensitivity.csv", "state_sensitivity.csv"),
        original[1:4],
        strict=True,
    ):
        with (source / name).open() as handle:
            expected = list(csv.DictReader(handle))
        require(
            expected
            == [
                {key: "" if value is None else str(value) for key, value in row.items()}
                for row in rows
            ],
            f"national reconstruction failed: {name}",
        )
    for row in topics:
        row["label"] = labels[row["topic"]]
    for row in peaks:
        row["peak_label"] = labels.get(row["peak_topic"])
    for path, before in snapshots.items():
        require(fingerprint(path) == before, f"source changed during analysis: {path}")
    output.mkdir()
    for name, rows in (
        ("state_topic_sensitivity.csv", topics),
        ("state_status_sensitivity.csv", statuses),
        ("state_peak_changes.csv", peaks),
    ):
        with (output / name).open("x", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    figure = plot(peaks, output)
    artifacts = {
        str(path.relative_to(output)): binding(path) for path in output.rglob("*") if path.is_file()
    }
    result = {
        "status": "complete_state_local_descriptive_sensitivity_not_independent_validation",
        "totals": original[0],
        "inputs": inputs,
        "artifacts": artifacts,
        "figure": figure,
        "definitions": {
            "denominator": "All candidate contexts within each state and subset, including gaps.",
            "remaining": "Only known train/dev matches removed; not held out.",
            "peak": "Largest absolute topic-share change; signed change and topic retained in CSV.",
            "ties": "Lowest numeric topic code; no peak topic for an observed all-zero change.",
            "unavailable": "No full or no remaining contexts; never a false observed zero.",
            "removed_records": str(source / "removed_contexts.jsonl"),
            "scope": "Saved-label matches only; not all consumed diagnostics or related families.",
        },
        "producer": binding(Path(__file__)),
        **dict.fromkeys(national.FLAGS, False),
        "model_execution": False,
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
    parser.add_argument("--sensitivity", type=Path, required=True)
    parser.add_argument("--sensitivity-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build(args.sensitivity, args.sensitivity_sha256, args.out)
        print(json.dumps({"status": result["status"], "totals": result["totals"]}, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

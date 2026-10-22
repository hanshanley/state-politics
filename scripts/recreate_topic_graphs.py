#!/usr/bin/env python3
"""Render provisional topic graphs from complete, frozen record-level inference only."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.analysis.cycle_topics import (  # noqa: E402
    FLAGS,
    binding,
    checked,
    checked_job,
    read,
    records,
    require,
)
from state_politics.analysis.taxonomy import load_topics  # noqa: E402
from state_politics.bills.openstates_dump import STATE_CODES  # noqa: E402
from state_politics.plotting import theme  # noqa: E402

NOTICE = (
    "Provisional model assignments, not independently validated policy findings. "
    "Retained versions and filing-time alignment remain uncertified. One candidate "
    "bill counts once; conflicting source alternatives abstain. Unknown party "
    "affiliations are not inferred. No party or operative-platform comparison."
)


def topic_tables(frame, topics):
    require(not frame["bill_id"].duplicated().any(), "duplicate bill-level assignments")
    require(
        set(frame["inference_status"]) <= {"classified", "abstained", "unavailable"},
        "unknown inference disposition",
    )
    codes = {topic.code for topic in topics}
    require(set(frame["topic"].dropna()) <= codes, "unknown model topic")
    require(
        frame["topic"].notna().equals(frame["inference_status"].eq("classified")),
        "topic and inference disposition disagree",
    )
    for flag in FLAGS:
        require(frame[flag].eq(False).all(), f"inference approval changed: {flag}")
    states = sorted(code.upper() for code in STATE_CODES)
    require(set(frame["state"]) <= set(states), "unexpected state in model assignments")
    status = (
        pd.crosstab(frame["state"], frame["inference_status"])
        .reindex(
            index=states,
            columns=["classified", "abstained", "unavailable"],
            fill_value=0,
        )
        .reset_index(names="state")
    )
    status["candidate_contexts"] = status[["classified", "abstained", "unavailable"]].sum(axis=1)
    status["observed_input_contexts"] = status["classified"] + status["abstained"]
    rows = []
    for state in states:
        group = frame[frame["state"] == state]
        observed = group["inference_status"].ne("unavailable").sum()
        for topic in topics:
            count = int(group["topic"].eq(topic.code).sum())
            rows.append(
                {
                    "state": state,
                    "topic": topic.code,
                    "topic_name": topic.name,
                    "model_assigned_contexts": count,
                    "candidate_contexts": len(group),
                    "observed_input_contexts": int(observed),
                    "share_of_all_candidates": count / len(group)
                    if len(group) and observed
                    else None,
                }
            )
    national = pd.DataFrame(
        [
            {
                "topic": topic.code,
                "topic_name": topic.name,
                "model_assigned_contexts": int(frame["topic"].eq(topic.code).sum()),
                "candidate_contexts": len(frame),
                "share_of_all_candidates": float(frame["topic"].eq(topic.code).sum()) / len(frame)
                if len(frame)
                else None,
            }
            for topic in topics
        ]
    )
    return national, status, pd.DataFrame(rows)


def save(fig, output, name, title):
    fig.suptitle(title, x=0.03, ha="left", fontsize=17, fontweight="bold")
    theme.source_note(fig, NOTICE)
    for suffix in ("png", "svg"):
        fig.savefig(output / f"{name}.{suffix}", dpi=160, facecolor=theme.BG)
    plt.close(fig)


def render(output, tier, national, states, shares):
    label = "Title / abstract" if tier == "metadata" else "Retained full text"
    ordered = national.sort_values("model_assigned_contexts")
    fig, ax = plt.subplots(figsize=(11, 8))
    ax.barh(ordered["topic_name"], ordered["model_assigned_contexts"], color=theme.BLUE)
    ax.set_xlabel("Candidate bills receiving a model topic")
    ax.tick_params(axis="y", labelsize=10)
    fig.subplots_adjust(left=0.29, right=0.97, bottom=0.18, top=0.88)
    save(fig, output, f"{tier}_topic_counts", f"{label}: provisional bill topics")

    fig, ax = plt.subplots(figsize=(12, 16))
    denominator = states["candidate_contexts"].replace(0, np.nan)
    left = np.zeros(len(states))
    for column, name, color in (
        ("classified", "Assigned one topic", theme.BLUE),
        ("abstained", "Abstained / source conflict", theme.MUTED),
        ("unavailable", "No supplied text for this tier", theme.GRID),
    ):
        values = (states[column] / denominator * 100).fillna(0)
        ax.barh(states["state"], values, left=left, height=0.65, color=color, label=name)
        left += values.to_numpy()
    for i, row in states.iterrows():
        ax.text(101.5, i, f"n={int(row['candidate_contexts']):,}", va="center", fontsize=8)
    ax.set_xlim(0, 121)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.invert_yaxis()
    ax.set_xlabel("Share of all existing calendar candidates; no-candidate states are unknown")
    ax.legend(loc="lower right", fontsize=8)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.91, bottom=0.12)
    save(fig, output, f"{tier}_classification_coverage", f"{label}: assignments and abstentions")

    matrix = shares.pivot(index="state", columns="topic_name", values="share_of_all_candidates")
    matrix = matrix.reindex(index=states["state"], columns=national["topic_name"])
    fig, ax = plt.subplots(figsize=(15, 16))
    cmap = LinearSegmentedColormap.from_list(
        "provisional_attention", [theme.BG, theme.BLUE]
    ).with_extremes(bad=theme.GRID)
    values = np.ma.masked_invalid(matrix.to_numpy(dtype=float) * 100)
    image = ax.imshow(values, aspect="auto", cmap=cmap, vmin=0)
    ax.set_yticks(range(len(matrix)), matrix.index, fontsize=9)
    ax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=65, ha="right", fontsize=9)
    fig.colorbar(image, ax=ax, shrink=0.5, label="Assigned topic / all candidate bills (%)")
    fig.subplots_adjust(left=0.06, right=0.94, top=0.92, bottom=0.22)
    save(fig, output, f"{tier}_state_topics", f"{label}: model-assigned topics by state")
    return [
        f"{tier}_topic_counts",
        f"{tier}_classification_coverage",
        f"{tier}_state_topics",
    ]


def recreate(directory, output, *, tiers):
    directory, output = directory.absolute(), output.absolute()
    plan = checked_job(directory)
    require(
        not output.exists()
        and output.resolve() == output
        and output.is_relative_to(ROOT / "outputs"),
        "new project output required",
    )
    require(bool(tiers) and len(set(tiers)) == len(tiers), "unique completed tiers required")
    inputs, frames, tables = {}, {}, {}
    topics = load_topics(plan["topics_path"])
    expected_states = {s.upper() for s in STATE_CODES}
    context_ids = {row["bill_id"] for _, row in records(directory / "contexts.jsonl")}
    for tier in tiers:
        require(tier in plan["tiers"], "tier absent from frozen inference")
        summary_path = directory / f"summary-{tier}.json"
        summary = read(summary_path)
        progress = read(directory / f"progress-{tier}.json")
        require(
            progress["status"] == "complete_provisional_inference_not_scientific_validation"
            and set(progress["states"]) == expected_states,
            "population inference incomplete",
        )
        source = directory / f"bill_assignments-{tier}.parquet"
        checked(source, summary["assignments"])
        frame = pd.read_parquet(source)
        require(
            set(frame["bill_id"]) == context_ids and len(frame) == plan["n_contexts"],
            "complete exact candidate denominator required",
        )
        require(set(frame["model_run"].dropna()) <= {plan["model_run"]}, "mixed model assignments")
        for name, entry in plan["inputs"].items():
            if entry["tier"] == tier:
                checked(directory / name, {key: entry[key] for key in ("sha256", "bytes")})
                inputs[name] = directory / name
        for state, entry in progress["states"].items():
            name = f"predictions/{tier}-{state}.jsonl"
            checked(directory / name, entry["artifact"])
            inputs[name] = directory / name
        for name in (
            f"summary-{tier}.json",
            f"progress-{tier}.json",
            f"bill_assignments-{tier}.parquet",
        ):
            inputs[name] = directory / name
        frames[tier] = frame
        tables[tier] = topic_tables(frame, topics)
    for folder in ("graphs", "chart-data", "research-data", "producers"):
        (output / folder).mkdir(parents=True)
    theme.apply()
    graph_names = []
    for tier, (national, states, shares) in tables.items():
        for name, table in (
            ("topic_counts", national),
            ("classification_coverage", states),
            ("state_topics", shares),
        ):
            table.to_csv(output / f"chart-data/{tier}_{name}.csv", index=False)
        frames[tier].to_csv(output / f"chart-data/{tier}_bill_assignments.csv", index=False)
        graph_names.extend(render(output / "graphs", tier, national, states, shares))
    for name in (
        "inference_plan.json",
        "contexts.jsonl",
        "producer/cycle_topics.py",
        "producer/modernbert.py",
        "producer/topics.yml",
    ):
        inputs[name] = directory / name
    archive_path = output / "research-data/complete_inference_inputs_and_predictions.zip"
    with zipfile.ZipFile(
        archive_path,
        "x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=1,
        allowZip64=True,
    ) as archive:
        for name, source in sorted(inputs.items()):
            archive.write(source, name)
    shutil.copy2(Path(__file__), output / "producers/recreate_topic_graphs.py")
    producer_pins = {name: binding(source) for name, source in inputs.items()}
    cards = "".join(
        f"<section><h2>{html.escape(name.replace('_', ' '))}</h2>"
        f'<a href="graphs/{name}.png"><img src="graphs/{name}.png" '
        f'alt="{html.escape(name.replace("_", " "))}"></a>'
        f'<p><a href="graphs/{name}.svg">SVG</a> · '
        f'<a download href="chart-data/{name}.csv">Complete chart data</a></p></section>'
        for name in graph_names
    )
    counts_by_tier = {
        tier: {
            "candidate_contexts": len(frame),
            **{
                key: int(frame["inference_status"].eq(key).sum())
                for key in ("classified", "abstained", "unavailable")
            },
        }
        for tier, frame in frames.items()
    }
    population = "".join(
        f"<p><strong>{html.escape(tier)}: {counts['candidate_contexts']:,} candidates</strong> · "
        f"{counts['classified']:,} assigned one topic · {counts['abstained']:,} abstained · "
        f"{counts['unavailable']:,} unavailable. Assignment rate is not accuracy.</p>"
        for tier, counts in counts_by_tier.items()
    )
    (output / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Provisional state bill topics</title><style>"
        f"body{{max-width:1100px;margin:40px auto;padding:0 24px;background:{theme.BG};"
        f"color:{theme.TEXT};font:16px/1.6 Georgia,serif}}a{{color:{theme.BLUE};"
        "overflow-wrap:anywhere}img{max-width:100%;height:auto}"
        "section{margin:40px 0;border-top:1px solid #D6D3CC}h1,h2{font-weight:normal}"
        "</style><main><p>LOCAL / UNPUBLISHED / PROVISIONAL</p>"
        "<h1>What the saved classifier assigns</h1>"
        f"<p>{html.escape(NOTICE)}</p><p>Evidence tiers: {html.escape(', '.join(tiers))}. "
        "Abstentions stay in every candidate denominator; unavailable inputs are not policy zeros. "
        "Topic attention does not establish agreement, ideology or party positions. "
        "These graphs do not estimate accuracy.</p>"
        f'{population}'
        '<p><a download href="research-data/complete_inference_inputs_and_predictions.zip">'
        "Complete inference texts, original source-view fields, per-view predictions, "
        "bill-level assignments and frozen plan (ZIP)</a></p>"
        "<p>This download contains every selected-tier input and prediction, not just chart "
        "metadata. Other incomplete tiers are not represented as completed inference.</p>"
        f"{cards}</main></html>"
    )
    for name, source in inputs.items():
        require(
            binding(source) == producer_pins[name], "inference inputs changed during graph build"
        )
    result = {
        "status": "complete_provisional_topic_graphs_not_scientific_validation",
        "notice": NOTICE,
        "inference_directory": str(directory),
        "tiers": list(tiers),
        "candidate_contexts": plan["n_contexts"],
        "assignment_counts_by_tier": counts_by_tier,
        "model_run": plan["model_run"],
        "scientific_certification": "not_performed",
        "model_promotion": False,
        "publication": False,
        "inference_was_executed": True,
        "model_execution_during_graph_build": False,
        "inference_inputs": producer_pins,
        "graphs": graph_names,
        "artifacts": {
            path.relative_to(output).as_posix(): binding(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
        **FLAGS,
    }
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--tiers", nargs="+", choices=("metadata", "retained_text"), default=["metadata"]
    )
    args = parser.parse_args(argv)
    result = recreate(args.directory, args.out_dir, tiers=args.tiers)
    print(json.dumps({key: result[key] for key in ("status", "tiers", "graphs")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Plot recorded bill outcomes and passage-vote support by sponsor and voter party."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.colors as mcolors  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.plotting import charts, theme  # noqa: E402


def build_outcome_figure(
    outcomes: pd.DataFrame,
    comparison: dict,
    out_path: Path,
):
    """Render two explicit recorded bill stages for the same 41 states."""
    fig, ax = charts.new_figure(figsize=(10.8, 5.8))
    outcome_labels = [
        "Passed ≥1 chamber\nor reached executive action",
        "Recorded as enacted",
    ]
    y = np.arange(len(outcome_labels))
    height = 0.32
    for offset, party in ((height / 2, "D"), (-height / 2, "R")):
        row = outcomes.set_index("party").loc[party]
        values = [
            row["mean_advancement_rate"] * 100,
            row["mean_enactment_rate"] * 100,
        ]
        bars = ax.barh(
            y + offset,
            values,
            height=height,
            color=theme.PARTY_COLORS[party],
        )
        for bar, value in zip(bars, values, strict=True):
            ax.text(
                value - 0.5,
                bar.get_y() + bar.get_height() / 2,
                f"{'Democratic' if party == 'D' else 'Republican'}  {value:.1f}%",
                ha="right",
                va="center",
                fontsize=10,
                fontweight="bold",
                color="white",
            )
    ax.set_yticks(y)
    ax.set_yticklabels(outcome_labels, fontsize=11)
    ax.invert_yaxis()
    ax.set_xlim(0, 35)
    ax.set_xlabel("Equal-state mean share of law-eligible bills (%)")
    ax.grid(axis="x", linestyle="-", linewidth=0.5)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)
    charts.style_axes(
        ax,
        "How often filed bills reach recorded legislative stages",
        "Equal-state mean share of law-eligible bills (%)",
        "",
        subtitle=(
            "Same 41 states for both parties; "
            f"D−R enactment gap {comparison['mean_d_minus_r_enactment_rate']:+.1%}, "
            f"paired p = {comparison['sign_flip_p_value']:.3f}"
        ),
    )
    source = (
        "Source: Open States / Plural Policy, 2026-07 public PostgreSQL dump. Ordinary bills "
        "sponsored by D/R legislators; each party has at least 500 filings and 80% action "
        "coverage in every included state. The first stage means passage in at least one chamber "
        "or a later executive action, including a veto. 'Recorded as enacted' requires "
        "became-law, executive-signature, or veto-override-passage. These are descriptive "
        "associations, not causal party-performance estimates."
    )
    return charts.finish(fig, ax, out_path, source=source, legend=False)


def build_rollcall_figure(rollcalls: pd.DataFrame, out_path: Path):
    """Render a 2×2 sponsor-party by voter-party yes-share matrix."""
    indexed = rollcalls.set_index(["sponsor_party", "voter_party"])
    values = np.array(
        [
            [
                indexed.loc[("D", "D"), "mean_yes_share"] * 100,
                indexed.loc[("D", "R"), "mean_yes_share"] * 100,
            ],
            [
                indexed.loc[("R", "D"), "mean_yes_share"] * 100,
                indexed.loc[("R", "R"), "mean_yes_share"] * 100,
            ],
        ]
    )
    theme.apply()
    fig, ax = charts.new_figure(figsize=(8.8, 5.8))
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rollcall-support",
        [theme.BG, theme.tint(theme.GREEN, 0.55), theme.GREEN, theme.shade(theme.GREEN, 0.35)],
    )
    image = ax.imshow(values, cmap=cmap, vmin=60, vmax=100, aspect="auto")
    for row in range(2):
        for column in range(2):
            value = values[row, column]
            ax.text(
                column,
                row,
                f"{value:.1f}%",
                ha="center",
                va="center",
                fontsize=18,
                fontweight="bold",
                color="white" if value >= 88 else theme.TEXT,
            )
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Democratic legislators", "Republican legislators"], fontsize=11)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Democratic-sponsored bills", "Republican-sponsored bills"], fontsize=11)
    ax.set_xlabel("Party of legislators casting votes")
    ax.set_ylabel("Party of the bill's sponsors")
    ax.tick_params(length=0)
    fig.suptitle(
        "Who votes yes on whose bills?",
        fontweight="bold",
        fontsize=18,
        y=0.985,
    )
    fig.text(
        0.5,
        0.925,
        "Mean yes share on recorded passage roll calls in the same 40 states",
        ha="center",
        va="top",
        fontsize=11,
        color=theme.MUTED,
    )
    colorbar = fig.colorbar(image, ax=ax, fraction=0.04, pad=0.04)
    colorbar.set_label("Mean yes share (%)")
    colorbar.outline.set_visible(False)
    source = (
        "Source: Open States / Plural Policy, 2026-07 public PostgreSQL dump. Each cell averages "
        "recorded passage-vote events rather than states. Voter party is resolved on the vote "
        "date; each party-vote cell requires at least 10 resolved Democratic/Republican voters. "
        "The matrix describes motions that received roll calls, not all bills or causal party "
        "effects."
    )
    note = theme.source_note(fig, source)
    theme.layout_with_note(fig, note, top=0.88)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--outcomes",
        default=ROOT / "data/processed/bill_outcomes_by_party.csv",
    )
    parser.add_argument(
        "--rollcalls",
        default=ROOT / "data/processed/rollcall_party_support.csv",
    )
    parser.add_argument(
        "--comparison",
        default=ROOT / "data/processed/bill_outcome_comparison.json",
    )
    parser.add_argument(
        "--stages-out",
        default=ROOT / "outputs/bill_recorded_stages.png",
    )
    parser.add_argument(
        "--votes-out",
        default=ROOT / "outputs/passage_vote_support_matrix.png",
    )
    args = parser.parse_args(argv)

    stages_out = build_outcome_figure(
        pd.read_csv(args.outcomes),
        json.loads(Path(args.comparison).read_text(encoding="utf-8")),
        Path(args.stages_out),
    )
    votes_out = build_rollcall_figure(
        pd.read_csv(args.rollcalls),
        Path(args.votes_out),
    )
    print(f"wrote {stages_out}")
    print(f"wrote {votes_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

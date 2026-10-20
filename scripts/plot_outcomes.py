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
    """Render recorded stages with the supplied paired-state coverage."""
    n_paired = comparison["n_paired_states"]
    expected_parties = {"D", "R"} if n_paired else set()
    if (
        n_paired < 0
        or len(outcomes) != len(expected_parties)
        or set(outcomes["party"]) != expected_parties
        or not outcomes["n_states"].eq(n_paired).all()
    ):
        raise ValueError("Outcome rows do not match the paired-state count and D/R coverage")
    fig, ax = charts.new_figure(figsize=(10.8, 5.8))
    outcome_labels = [
        "Passed ≥1 chamber\nor reached executive action",
        "Recorded as enacted",
    ]
    y = np.arange(len(outcome_labels))
    height = 0.32
    for offset, party in ((height / 2, "D"), (-height / 2, "R")):
        if outcomes.empty:
            break
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
            inside = value >= 30
            ax.text(
                value - 1 if inside else value + 1,
                bar.get_y() + bar.get_height() / 2,
                f"{'Democratic' if party == 'D' else 'Republican'}  {value:.1f}%",
                ha="right" if inside else "left",
                va="center",
                fontsize=10,
                fontweight="bold",
                color="white" if inside else theme.TEXT,
            )
    ax.set_yticks(y)
    ax.set_yticklabels(outcome_labels, fontsize=11)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Equal-state mean share of law-eligible bills (%)")
    ax.grid(axis="x", linestyle="-", linewidth=0.5)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)
    if n_paired:
        subtitle = (
            f"Paired states: {n_paired}; "
            f"D−R enactment gap {comparison['mean_d_minus_r_enactment_rate']:+.1%}, "
            f"paired p = {comparison['sign_flip_p_value']:.3f}"
        )
    else:
        subtitle = "Comparison unavailable: no paired states meet the coverage floors"
        ax.text(
            0.5, 0.5, "Recorded outcome comparison unavailable",
            transform=ax.transAxes, ha="center", va="center", color=theme.MUTED,
        )
    charts.style_axes(
        ax,
        "How often filed bills reach recorded legislative stages",
        "Equal-state mean share of law-eligible bills (%)",
        "",
        subtitle=subtitle,
    )
    source = (
        "Source: supplied Open States / Plural Policy outcome exports; this figure does not "
        "establish their snapshot identity or revalidate the findings. Ordinary D/R-sponsored "
        "bills, with paired-state coverage floors recorded in the comparison metadata. "
        "The first stage means passage in at least one chamber "
        "or a later executive action, including a veto. 'Recorded as enacted' requires "
        "became-law, executive-signature, or veto-override-passage. These are descriptive "
        "associations, not causal party-performance estimates."
    )
    return charts.finish(fig, ax, out_path, source=source, legend=False)


def build_rollcall_figure(rollcalls: pd.DataFrame, out_path: Path):
    """Render a 2×2 sponsor-party by voter-party yes-share matrix."""
    pairs = pd.MultiIndex.from_product(
        [("D", "R"), ("D", "R")], names=["sponsor_party", "voter_party"],
    )
    indexed = rollcalls.set_index(["sponsor_party", "voter_party"]).reindex(pairs)
    values = indexed["mean_yes_share"].to_numpy(dtype=float).reshape(2, 2) * 100
    theme.apply()
    fig, ax = charts.new_figure(figsize=(8.8, 5.8))
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rollcall-support",
        [theme.BG, theme.tint(theme.GREEN, 0.55), theme.GREEN, theme.shade(theme.GREEN, 0.35)],
    )
    image = ax.imshow(np.ma.masked_invalid(values), cmap=cmap, vmin=0, vmax=100, aspect="auto")
    for row in range(2):
        for column in range(2):
            value = values[row, column]
            if np.isnan(value):
                ax.text(
                    column, row, "Unavailable", ha="center", va="center",
                    fontsize=13, color=theme.MUTED,
                )
                continue
            color = "white" if value >= 88 else theme.TEXT
            ax.text(
                column,
                row - 0.08,
                f"{value:.1f}%",
                ha="center",
                va="center",
                fontsize=18,
                fontweight="bold",
                color=color,
            )
            cell = indexed.iloc[row * 2 + column]
            n_states = cell.get("n_states")
            state_label = (
                f"{int(n_states)} state{'s' if n_states != 1 else ''}"
                if pd.notna(n_states) else "state count unavailable"
            )
            n_events = int(cell["n_vote_events"])
            ax.text(
                column, row + 0.2,
                f"{state_label}; {n_events:,} roll call{'s' if n_events != 1 else ''}",
                ha="center", va="center", fontsize=9, color=color,
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
        "Event-weighted passage-vote means; coverage shown separately for each cell",
        ha="center",
        va="top",
        fontsize=11,
        color=theme.MUTED,
    )
    colorbar = fig.colorbar(image, ax=ax, fraction=0.04, pad=0.04)
    colorbar.set_label("Mean yes share (%)")
    colorbar.outline.set_visible(False)
    source = (
        "Source: supplied Open States / Plural Policy roll-call exports; this figure does not "
        "establish their snapshot identity or revalidate attribution. Each cell averages "
        "recorded passage-vote events rather than states; counts describe that cell's supplied "
        "coverage, not necessarily a common state sample. Missing cells are unavailable, not "
        "zero. These are motions that received roll calls, not all bills or causal party effects."
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

#!/usr/bin/env python3
"""Plot recorded bill outcomes and passage-vote support by sponsor and voter party."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.plotting import charts, theme  # noqa: E402


def build_figure(
    outcomes: pd.DataFrame,
    rollcalls: pd.DataFrame,
    comparison: dict,
    out_path: Path,
):
    """Render equal-state recorded outcomes and roll-call coalition support."""
    fig, _ = charts.new_figure(figsize=(13.5, 7.6))
    fig.clf()
    left, right = fig.subplots(1, 2)

    outcome_labels = ["Advanced", "Recorded enacted"]
    x = [0, 1]
    width = 0.34
    for offset, party in ((-width / 2, "D"), (width / 2, "R")):
        row = outcomes.set_index("party").loc[party]
        values = [
            row["mean_advancement_rate"] * 100,
            row["mean_enactment_rate"] * 100,
        ]
        bars = left.bar(
            [position + offset for position in x],
            values,
            width=width,
            color=theme.PARTY_COLORS[party],
            label=theme.PARTY_LABELS[party],
        )
        for bar, value in zip(bars, values, strict=True):
            left.text(
                bar.get_x() + bar.get_width() / 2,
                value + 0.7,
                f"{value:.1f}%",
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
            )
    left.set_xticks(x)
    left.set_xticklabels(outcome_labels)
    left.set_ylabel("Equal-state mean share of law-eligible filings")
    left.set_ylim(0, max(40, left.get_ylim()[1] * 1.08))
    left.grid(axis="y", linestyle="-", linewidth=0.5)
    left.grid(axis="x", visible=False)
    left.set_axisbelow(True)
    left.set_title("Recorded advancement and enactment", fontweight="bold", fontsize=14)
    left.text(
        0.5,
        0.96,
        (
            f"D−R enactment gap: "
            f"{comparison['mean_d_minus_r_enactment_rate']:+.1%}; "
            f"paired sign-flip p = {comparison['sign_flip_p_value']:.3f}"
        ),
        transform=left.transAxes,
        ha="center",
        va="top",
        fontsize=9.5,
        color=theme.MUTED,
    )
    left.legend(frameon=False, loc="lower right")

    vote_labels = []
    vote_values = []
    vote_colors = []
    indexed = rollcalls.set_index(["sponsor_party", "voter_party"])
    for sponsor, voter in (("D", "D"), ("D", "R"), ("R", "R"), ("R", "D")):
        row = indexed.loc[(sponsor, voter)]
        vote_labels.append(f"{sponsor}-sponsored\n{voter} voters")
        vote_values.append(row["mean_yes_share"] * 100)
        vote_colors.append(theme.PARTY_COLORS[voter])
    bars = right.bar(range(4), vote_values, color=vote_colors, width=0.62)
    for bar, value in zip(bars, vote_values, strict=True):
        right.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.8,
            f"{value:.1f}%",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )
    right.set_xticks(range(4))
    right.set_xticklabels(vote_labels)
    right.set_ylabel("Mean yes share on recorded passage votes")
    right.set_ylim(0, 105)
    right.grid(axis="y", linestyle="-", linewidth=0.5)
    right.grid(axis="x", visible=False)
    right.set_axisbelow(True)
    right.set_title("Roll-call support crosses party lines", fontweight="bold", fontsize=14)

    fig.suptitle(
        "What happens after state bills are filed?",
        fontweight="bold",
        fontsize=18,
        y=0.985,
    )
    fig.text(
        0.5,
        0.94,
        "Explicit Open States actions and votes—not outcomes inferred from bill titles",
        ha="center",
        va="top",
        fontsize=11,
        color=theme.MUTED,
    )
    source = (
        "Source: Open States / Plural Policy, 2026-07 public PostgreSQL dump. Outcomes cover "
        "ordinary bills sponsored by D/R legislators in the 41 states where both parties have "
        "at least 500 filings and 80% action coverage; party bars are equal-state means. "
        "'Recorded enacted' requires "
        "became-law, executive-signature, or veto-override-passage action classifications. "
        "Roll-call bars average passage-vote yes shares after resolving voter party on the vote "
        "date; each party-vote cell requires at least 10 resolved D/R voters. These are "
        "descriptive associations, not causal party-performance estimates."
    )
    note = theme.source_note(fig, source)
    theme.layout_with_note(fig, note, top=0.91)
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
    parser.add_argument("--out", default=ROOT / "outputs/bill_outcomes.png")
    args = parser.parse_args(argv)

    out = build_figure(
        pd.read_csv(args.outcomes),
        pd.read_csv(args.rollcalls),
        json.loads(Path(args.comparison).read_text(encoding="utf-8")),
        Path(args.out),
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

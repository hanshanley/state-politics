#!/usr/bin/env python3
"""Plot separate 50-state Democratic and Republican bill-topic focus heatmaps."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.analysis.state_focus import STATE_CODES  # noqa: E402
from state_politics.plotting import theme  # noqa: E402

TOPIC_LABELS = {
    "Macroeconomics": "Economy\n& tax",
    "Civil rights and liberties": "Civil rights\n& liberties",
    "Health": "Health",
    "Agriculture": "Agriculture",
    "Labor and employment": "Labor",
    "Education": "Education",
    "Environment": "Environment",
    "Energy": "Energy",
    "Immigration": "Immigration",
    "Transportation": "Transport",
    "Law, crime and justice": "Law &\ncrime",
    "Social welfare": "Social\nwelfare",
    "Housing and community development": "Housing",
    "Business, commerce and consumers": "Business &\nconsumers",
    "Defense and veterans": "Defense &\nveterans",
    "Science, technology and communications": "Science &\ntech",
    "Foreign trade": "Foreign\ntrade",
    "International affairs": "International",
    "Government operations": "Government\noperations",
    "Public lands and water": "Public lands\n& water",
    "Culture, family and social issues": "Culture &\nfamily",
}


def focus_matrix(emphasis: pd.DataFrame, party: str):
    """Return the fixed 50-state matrix and common topic order used by both figures."""
    party_frame = emphasis[emphasis["party"] == party].copy()
    topic_order = (
        emphasis.groupby("topic_name")["share"]
        .mean()
        .sort_values(ascending=False)
        .index.tolist()
    )
    matrix = (
        party_frame.pivot_table(
            index="state",
            columns="topic_name",
            values="share",
            fill_value=0.0,
        )
        .reindex(columns=topic_order, fill_value=0.0)
        .reindex(index=STATE_CODES)
    )
    return matrix, topic_order


def build_figure(
    emphasis: pd.DataFrame,
    coverage: pd.DataFrame,
    party: str,
    out_path: Path,
):
    """Render a 4-column card atlas listing each state's top three bill topics."""
    matrix, _topic_order = focus_matrix(emphasis, party)
    party_color = theme.PARTY_COLORS[party]
    theme.apply()
    rows, columns = 13, 4
    fig, axes = plt.subplots(rows, columns, figsize=(16, 20))
    coverage_index = coverage[coverage["party"] == party].set_index("state")
    bar_colors = [
        party_color,
        theme.tint(party_color, 0.35),
        theme.tint(party_color, 0.62),
    ]
    for index, state in enumerate(STATE_CODES):
        ax = axes[index // columns, index % columns]
        ax.set_facecolor(theme.CARD)
        n_classified = (
            coverage_index.loc[state, "n_classified_total"]
            if state in coverage_index.index
            else 0
        )
        state_label = f"{state}†" if 0 < n_classified < 500 else state
        ax.set_title(
            state_label,
            loc="left",
            fontsize=12,
            fontweight="bold",
            color=party_color,
            pad=4,
        )
        state_row = matrix.loc[state]
        if state_row.isna().all():
            ax.axis("off")
            ax.text(
                0.5,
                0.5,
                "NE\nFormally nonpartisan\nlegislature",
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=11,
                color=theme.MUTED,
                fontstyle="italic",
            )
            continue
        top = state_row.nlargest(3)
        labels = [
            TOPIC_LABELS.get(topic, topic).replace("\n", " ")
            for topic in top.index
        ]
        values = top.to_numpy(dtype=float) * 100
        y = np.arange(3)[::-1]
        ax.barh(y, values, color=bar_colors, height=0.54)
        ax.set_xlim(0, 33)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=8.4)
        ax.set_xticks([10, 20, 30])
        ax.set_xticklabels([])
        ax.grid(axis="x", linestyle="-", linewidth=0.45)
        ax.grid(axis="y", visible=False)
        ax.set_axisbelow(True)
        ax.tick_params(axis="both", length=0)
        for position, value in zip(y, values, strict=True):
            ax.text(
                value + 0.5,
                position,
                f"{value:.0f}%",
                ha="left",
                va="center",
                fontsize=8.4,
                fontweight="bold",
                color=theme.TEXT,
            )
        for spine in ax.spines.values():
            spine.set_color(theme.GRID)
            spine.set_linewidth(0.7)

    for index in range(len(STATE_CODES), rows * columns):
        axes[index // columns, index % columns].axis("off")

    label = "Democratic" if party == "D" else "Republican"
    fig.suptitle(
        f"Top three bill topics in every {label} state caucus",
        fontsize=20,
        fontweight="bold",
        y=0.985,
    )
    fig.text(
        0.5,
        0.955,
        "Bars show each topic's share of that state caucus's classified bills",
        ha="center",
        va="top",
        fontsize=11,
        color=theme.MUTED,
    )
    source = (
        "Source: Open States / Plural Policy, 2026-07 public PostgreSQL dump. Cards cover every "
        "state; Nebraska is explicitly unavailable because its legislature is formally "
        "nonpartisan. Shares use bill titles classified into the Comparative Agendas Project "
        "major-topic scheme after excluding Illinois -TECH placeholders and New Mexico's "
        "emergency-clause shell. † = fewer than 500 classified bills, so the card is descriptive "
        "rather than a reliable outlier comparison. Topic attention does not establish support "
        "or opposition."
    )
    note = theme.source_note(fig, source)
    theme.layout_with_note(fig, note, top=0.94, max_fraction=0.14)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--emphasis",
        default=ROOT / "data/processed/bill_emphasis_by_state.csv",
    )
    parser.add_argument(
        "--coverage",
        default=ROOT / "data/processed/bill_classification_coverage.csv",
    )
    parser.add_argument("--out-dir", default=ROOT / "outputs")
    parser.add_argument("--party", choices=["D", "R"])
    args = parser.parse_args(argv)

    emphasis = pd.read_csv(args.emphasis)
    coverage = pd.read_csv(args.coverage)
    parties = (args.party,) if args.party else ("D", "R")
    names = {"D": "democratic", "R": "republican"}
    for party in parties:
        out = Path(args.out_dir) / f"{names[party]}_50_state_focus_cards.png"
        build_figure(emphasis, coverage, party, out)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

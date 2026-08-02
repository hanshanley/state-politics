#!/usr/bin/env python3
"""Plot separate 50-state Democratic and Republican bill-topic focus heatmaps."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.colors as mcolors  # noqa: E402
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
    """Render one party's 50-state topic-share matrix with top-three cells labelled."""
    matrix, topic_order = focus_matrix(emphasis, party)
    values = matrix.to_numpy(dtype=float) * 100
    party_color = theme.PARTY_COLORS[party]
    cmap = mcolors.LinearSegmentedColormap.from_list(
        f"{party}-focus",
        [theme.BG, theme.tint(party_color, 0.65), party_color, theme.shade(party_color, 0.35)],
    )
    cmap.set_bad(theme.CARD)
    vmax = max(30.0, float(np.nanmax(values)))

    fig, ax = plt.subplots(figsize=(17, 17.5))
    theme.apply()
    image = ax.imshow(values, aspect="auto", cmap=cmap, vmin=0, vmax=vmax)
    ax.set_xticks(range(len(topic_order)))
    ax.set_xticklabels(
        [TOPIC_LABELS.get(topic, topic) for topic in topic_order],
        rotation=42,
        ha="right",
        fontsize=9,
    )
    coverage_index = coverage[coverage["party"] == party].set_index("state")
    state_labels = []
    for state in STATE_CODES:
        n_classified = (
            coverage_index.loc[state, "n_classified_total"]
            if state in coverage_index.index
            else 0
        )
        state_labels.append(f"{state}†" if 0 < n_classified < 500 else state)
    ax.set_yticks(range(len(STATE_CODES)))
    ax.set_yticklabels(state_labels, fontsize=9.5, fontweight="bold")
    ax.set_xticks(np.arange(-0.5, len(topic_order), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(STATE_CODES), 1), minor=True)
    ax.grid(which="minor", color=theme.BG, linewidth=1.1)
    ax.tick_params(which="minor", bottom=False, left=False)
    ax.tick_params(axis="both", length=0)

    for row_index, _state in enumerate(STATE_CODES):
        row = values[row_index]
        if np.isnan(row).all():
            ax.text(
                len(topic_order) / 2,
                row_index,
                "Formally nonpartisan legislature — no D/R bill caucus",
                ha="center",
                va="center",
                fontsize=8.5,
                color=theme.MUTED,
                fontstyle="italic",
            )
            continue
        top_positions = np.argsort(np.nan_to_num(row, nan=-1))[-3:]
        for column_index in top_positions:
            value = row[column_index]
            ax.text(
                column_index,
                row_index,
                f"{value:.0f}%",
                ha="center",
                va="center",
                fontsize=7.5,
                fontweight="bold",
                color="white" if value >= vmax * 0.35 else theme.TEXT,
            )

    label = "Democratic" if party == "D" else "Republican"
    fig.suptitle(
        f"What {label} state legislators focus on, state by state",
        fontsize=20,
        fontweight="bold",
        y=0.985,
    )
    ax.set_title(
        "Share of each state party caucus's classified bills; "
        "each state's top three cells are labelled",
        fontsize=11,
        color=theme.MUTED,
        pad=18,
    )
    colorbar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.015)
    colorbar.set_label("Share of classified bills (%)", fontsize=10)
    colorbar.outline.set_visible(False)
    source = (
        "Source: Open States / Plural Policy, 2026-07 public PostgreSQL dump. Rows cover every "
        "state; Nebraska is explicitly unavailable because its legislature is formally "
        "nonpartisan. Shares use bill titles classified into the Comparative Agendas Project "
        "major-topic scheme after excluding Illinois -TECH placeholders and New Mexico's "
        "emergency-clause shell. † = fewer than 500 classified bills, so the row is descriptive "
        "rather than a reliable outlier comparison. Color encodes attention, not support or "
        "opposition within a topic."
    )
    note = theme.source_note(fig, source)
    theme.layout_with_note(fig, note, top=0.94, max_fraction=0.20)
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
        out = Path(args.out_dir) / f"{names[party]}_all_state_focus.png"
        build_figure(emphasis, coverage, party, out)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

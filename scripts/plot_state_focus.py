#!/usr/bin/env python3
"""Plot the state legislative agendas most unlike their same-party peers.

The full 100-row atlas is written by ``analysis.state_focus``. This figure highlights the most
distinctive *filed* agendas among the 43 Democratic and 44 Republican state-party samples that
clear the 500-bill floor; Nebraska is unavailable because its legislature is formally
nonpartisan.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.plotting import charts, theme  # noqa: E402

TOPIC_LABELS = {
    "Civil rights and liberties": "Civil rights & liberties",
    "Public lands and water": "Public lands & water",
    "Law, crime and justice": "Law, crime & justice",
    "Science, technology and communications": "Science & technology",
    "Business, commerce and consumers": "Business & consumers",
    "Housing and community development": "Housing & community development",
}

SOURCE_NOTE = (
    "Source: Open States / Plural Policy, 2026-07 public PostgreSQL dump. Each row is one "
    "state party's classified bill-title distribution. The comparison is leave-one-state-out: "
    "each state is measured against same-party peers that do not include itself. Bars show the "
    "percentage-point excess in the labelled topic. Rankings require 500 classified bills. "
    "Illinois -TECH placeholders and New Mexico emergency-clause shells are excluded. Nebraska "
    "is absent because its legislature is formally nonpartisan. Bill titles are a noisy agenda "
    "signal; this measures filing priorities, not enactment or ideology."
)


def build_figure(atlas: pd.DataFrame, out_path: Path, *, top_n: int = 10) -> Path:
    """Render the most distinctive state bill agendas for each major party."""
    fig, axes = charts.new_figure(figsize=(13, 8.5))
    fig.clf()
    axes = fig.subplots(1, 2, sharex=True)
    plotted_max = 0.0

    for ax, party in zip(axes, ("D", "R"), strict=True):
        subset = atlas[
            (atlas["party"] == party)
            & atlas["bill_focus_reliable"].fillna(False)
        ].nlargest(top_n, "bill_cosine_distance").copy()
        subset = subset.sort_values("bill_focus_share")
        labels = subset["state"].tolist()
        peers = (subset["bill_peer_share"] * 100).tolist()
        states = (subset["bill_focus_share"] * 100).tolist()
        plotted_max = max(plotted_max, max(states))
        color = theme.PARTY_COLORS[party]
        charts.dumbbell(
            ax,
            labels,
            peers,
            states,
            left_color=theme.MUTED,
            right_color=color,
            left_label="Same-party peers",
            right_label="State share",
            left_marker="o",
            right_marker="s",
            left_filled=False,
            right_filled=True,
            markersize=7.5,
        )
        for position, row in enumerate(subset.itertuples()):
            topic_label = TOPIC_LABELS.get(row.bill_focus_topic, row.bill_focus_topic)
            ax.annotate(
                topic_label,
                xy=(row.bill_focus_share * 100, position),
                xytext=(7, 0),
                textcoords="offset points",
                va="center",
                fontsize=8.4,
                color=theme.TEXT,
            )
        ax.set_title(theme.PARTY_LABELS[party], fontweight="bold", fontsize=14, pad=10)
        ax.set_xlabel("Share of classified bills (%)")
        ax.grid(axis="x", linestyle="-", linewidth=0.5)
        ax.grid(axis="y", visible=False)
        ax.set_axisbelow(True)

    axes[0].set_xlim(0, plotted_max * 1.60)
    axes[0].legend(loc="lower right", frameon=False, fontsize=9.5)
    fig.suptitle(
        "Where a state's filing agenda differs most from its own party",
        fontweight="bold",
        fontsize=18,
        y=0.985,
    )
    fig.text(
        0.5,
        0.945,
        "Open circle = same-party peer share; solid square = state share "
        "in its largest positive gap",
        ha="center",
        va="top",
        fontsize=11,
        color=theme.MUTED,
    )
    note = theme.source_note(fig, SOURCE_NOTE)
    theme.layout_with_note(fig, note, top=0.925)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--atlas", default=ROOT / "data/processed/state_party_focus.csv")
    parser.add_argument("--out", default=ROOT / "outputs/state_party_focus.png")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)

    atlas = pd.read_csv(args.atlas)
    out = build_figure(atlas, Path(args.out), top_n=args.top)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Plot FDR-significant supplied bill-topic changes with source-tag direction concordance."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.plotting import charts, theme  # noqa: E402


def build_figure(trends: pd.DataFrame, out_path: Path):
    """Render available, direction-concordant changes without certifying supplied labels."""
    subset = trends[
        trends["q_value_model"].lt(0.05)
        & trends["direction_replicates_with_tags"].fillna(False)
    ].copy()
    subset = subset.sort_values("change_model")
    fig, ax = charts.new_figure(figsize=(12.8, max(6.8, 3 + 0.55 * len(subset))))
    y_positions = range(len(subset))

    for y, row in zip(y_positions, subset.itertuples(), strict=True):
        color = theme.PARTY_COLORS[row.party]
        early, late = row.early_share_model * 100, row.late_share_model * 100
        ax.plot([early, late], [y, y], color=color, linewidth=2.2, zorder=1)
        ax.scatter(
            [early],
            [y],
            facecolors=theme.BG,
            edgecolors=color,
            linewidths=1.8,
            s=64,
            zorder=2,
        )
        ax.scatter([late], [y], color=color, s=64, zorder=3)
        ax.annotate(
            f"{row.change_model * 100:+.1f} percentage points",
            xy=(max(early, late), y),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=color,
        )

    labels = [
        f"{'Democratic' if row.party == 'D' else 'Republican'} · {row.topic_name}\n"
        f"model n={row.paired_state_count_model:.0f}; tags n={row.paired_state_count_tags:.0f}"
        for row in subset.itertuples()
    ]
    if subset.empty:
        ax.text(
            0.5, 0.5, "No comparable direction-concordant changes available",
            ha="center", va="center", transform=ax.transAxes, color=theme.MUTED,
        )
    ax.set_yticks(list(y_positions))
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlabel("Equal-state share of classified bills (%)")
    ax.grid(axis="x", linestyle="-", linewidth=0.5)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)
    ax.legend(
        handles=[
            Line2D(
                [0], [0], marker="o", color="none", markerfacecolor=theme.BG,
                markeredgecolor=theme.TEXT, label="2018–2019",
            ),
            Line2D(
                [0], [0], marker="o", color="none", markerfacecolor=theme.TEXT,
                markeredgecolor=theme.TEXT, label="2024–2025",
            ),
        ],
        loc="lower right",
        frameon=False,
    )
    fig.suptitle(
        "Changes in supplied state-party topic shares",
        fontweight="bold",
        fontsize=18,
        y=0.985,
    )
    fig.text(
        0.5,
        0.94,
        "Equal-state bill shares, 2018–2019 versus 2024–2025",
        ha="center",
        va="top",
        fontsize=11,
        color=theme.MUTED,
    )
    source = (
        "Source: supplied Open States / Plural Policy exports. Source snapshot, topic labels "
        "and subject tags have not been revalidated. Shares are "
        "equal-state means over states with at least 100 classified bills in both periods. "
        "Only changes passing model-based FDR correction and moving in the same direction under "
        "unambiguously mapped source tags are shown; this is not independent accuracy validation. "
        "Model and tag samples may differ; paired-state counts are shown per row. "
        "The analysis window is 2018–2025, not a claim of complete source coverage."
    )
    note = theme.source_note(fig, source)
    theme.layout_with_note(fig, note, top=0.92)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--trends",
        default=ROOT / "data/processed/bill_topic_trend_replication.csv",
    )
    parser.add_argument("--out", default=ROOT / "outputs/robust_bill_topic_trends.png")
    args = parser.parse_args(argv)

    trends = pd.read_csv(args.trends)
    out = build_figure(trends, Path(args.out))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

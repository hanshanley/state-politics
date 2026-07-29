#!/usr/bin/env python3
"""Plot what state parties say against what their legislators file.

The project's central comparison. Platform emphasis is what a state party organization declares
matters; bill emphasis is what its legislators actually spend the session filing. The two come
from different sources with different authors and incentives, and are made comparable only by
being classified into the same taxonomy -- so the distance between them is the finding.

Reads ``data/processed/stated_vs_revealed.csv`` from
``python -m state_politics.analysis.revealed``.

Usage::

    python scripts/plot_stated_vs_revealed.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: no display required

import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.plotting import charts, theme  # noqa: E402

SOURCE_NOTE = (
    "Sources: platform planks from Hopkins, Coffey, Galvin, Gamm, Henderson, Paddock & Schickler "
    "(2022), 'Select American State Party Platforms, 1846-2017', V3.0, Harvard Dataverse, "
    "doi:10.7910/DVN/KNOSHL, CC0 1.0 (1990-2017), plus 2018-present platforms published by the "
    "individual state party committees and collected for this project; bills from Open States / "
    "Plural Policy, '2026-07 public PostgreSQL dump', public domain. Accessed 2026-07-29. "
    "43,104 planks from 872 documents; 516,155 bills filed 2018-2026 in all 50 states and "
    "attributed to a party by their primary sponsors. Topics follow the Comparative Agendas "
    "Project major-topic scheme, assigned by a local sentence-transformer scoring 62% top-1 and "
    "78% top-2 on a hand-labelled plank sample. Bills are classified from titles, which are "
    "shorter and noisier than planks. Filing a bill is not passing one: this measures agenda, "
    "not achievement."
)


def build_figure(table: pd.DataFrame, out_path: Path) -> Path:
    fig, axes = charts.new_figure(figsize=(13, 9))
    fig.clf()
    axes = fig.subplots(1, 2, sharex=True)

    for ax, party in zip(axes, ("D", "R"), strict=True):
        subset = table[table["party"] == party].copy()
        subset = subset.sort_values("stated_minus_revealed")
        labels = subset["topic_name"].tolist()
        stated = (subset["stated_share"] * 100).tolist()
        revealed = (subset["revealed_share"] * 100).tolist()

        color = theme.PARTY_COLORS[party]
        charts.dumbbell(
            ax, labels, stated, revealed,
            left_color=color, right_color=theme.shade(color, 0.55),
            left_label="Said (platform planks)", right_label="Filed (bills)",
            markersize=7.0,
        )
        ax.invert_yaxis()
        ax.set_title(theme.PARTY_LABELS[party], fontweight="bold", fontsize=14, pad=12)
        ax.set_xlabel("Share of that party's planks / bills (%)", labelpad=2)
        ax.grid(axis="x", linestyle="-", linewidth=0.5)
        ax.set_axisbelow(True)

    axes[1].tick_params(labelleft=False)
    axes[0].legend(loc="lower right", frameon=False, labelcolor=theme.TEXT, fontsize=10)

    fig.suptitle("What state parties say, and what they actually file",
                 fontweight="bold", fontsize=18, y=0.985)
    fig.text(0.5, 0.945,
             "Filled = share of platform planks; darker = share of bills sponsored. "
             "The gap is the distance between agenda and action.",
             ha="center", va="top", fontsize=11, color=theme.MUTED)

    lines = theme.source_note(fig, SOURCE_NOTE)
    fig.tight_layout(rect=(0, min(0.16, 0.03 + 0.022 * lines), 1, 0.935))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", default=ROOT / "data/processed/stated_vs_revealed.csv")
    parser.add_argument("--out", default=ROOT / "outputs/stated_vs_revealed.png")
    args = parser.parse_args(argv)

    table_path = Path(args.table)
    if not table_path.exists():
        parser.error(
            f"{table_path} not found - run 'python -m state_politics.analysis.revealed' first"
        )

    out = build_figure(pd.read_csv(table_path), Path(args.out))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

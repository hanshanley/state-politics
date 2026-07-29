#!/usr/bin/env python3
"""Plot the recency of the historical state party platform corpus.

This is the figure that motivates the whole project: the most recent platform the Harvard
Dataverse corpus holds for each state party. Everything stops at 2017, and for many states
far earlier, which is why the 2018-present corpus has to be collected from scratch.

Reads the coverage matrix produced by ``python -m state_politics.platforms.dataverse``.

Usage::

    python scripts/plot_platform_coverage.py
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
    "Source: Hopkins, Coffey, Galvin, Gamm, Henderson, Paddock & Schickler (2022), "
    "'Select American State Party Platforms, 1846-2017', V3.0 (2025-04-23), Harvard Dataverse, "
    "doi:10.7910/DVN/KNOSHL, CC0 1.0; accessed 2026-07-28. Authoritative archive "
    "(platform-update-04212025.zip) only; the superseded archive is excluded. Each point is the "
    "most recent platform the corpus holds for that state party. A state with no document for a "
    "party has no point for it; Maryland is absent from the corpus entirely."
)


def build_figure(coverage: pd.DataFrame, out_path: Path) -> Path:
    states = coverage[coverage["state"] != "US"].copy()
    # Matplotlib places index 0 at the bottom, so the axis is inverted below and index 0
    # renders at the TOP. Sorting oldest-first therefore puts the most severe gaps at the top.
    states["sort_key"] = states["latest_any"].fillna(0)
    states = states.sort_values(["sort_key", "state"], ascending=[True, True])

    labels = states["state"].tolist()
    positions = range(len(labels))

    fig, ax = charts.new_figure(figsize=(10, 13))

    for pos, (_, row) in zip(positions, states.iterrows(), strict=True):
        d, r = row["latest_D"], row["latest_R"]
        if pd.notna(d) and pd.notna(r):
            ax.plot([d, r], [pos, pos], color=theme.GRID, linewidth=1.8, zorder=1,
                    solid_capstyle="round")
        # Where the two parties' most recent platforms fall in the same year the markers
        # coincide exactly -- true for 20 of the rows. Drawing them at equal size hid the
        # Democratic dot completely, so a present observation looked identical to an absent
        # one. The Democratic marker is therefore drawn larger and above.
        if pd.notna(d):
            ax.scatter([d], [pos], color=theme.PARTY_COLORS["D"], s=86, zorder=3,
                       edgecolor=theme.BG, linewidth=0.8)
        if pd.notna(r):
            ax.scatter([r], [pos], color=theme.PARTY_COLORS["R"], s=40, zorder=4,
                       edgecolor=theme.BG, linewidth=0.8)
        if pd.isna(d) and pd.isna(r):
            ax.text(1948, pos, "no platform of either party in the corpus", va="center",
                    ha="left", fontsize=8.5, color=theme.MUTED, style="italic")

    ax.set_yticks(list(positions))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_ylim(-1, len(labels) + 1)
    ax.invert_yaxis()
    ax.grid(axis="x", linestyle="-", linewidth=0.5)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)

    charts.marker_line(ax, 2017)
    header_y = -0.9  # just above the first row, since the y-axis is inverted
    ax.text(2015, header_y, "corpus ends 2017  ", ha="right", va="center", fontsize=9,
            style="italic", color=theme.MUTED, path_effects=theme.white_stroke())

    charts.style_axes(
        ax,
        "The state party platform record runs out long before the present",
        "Year of the most recent platform held in the corpus",
        "",
        subtitle="Most recent Democratic and Republican state platform, by state",
    )

    # Direct labels instead of a legend box, per the house style.
    ax.scatter([1946], [header_y], color=theme.PARTY_COLORS["D"], s=86, edgecolor=theme.BG,
               linewidth=0.8, clip_on=False)
    ax.text(1949, header_y, "Democratic", color=theme.PARTY_COLORS["D"], fontweight="bold",
            fontsize=10, va="center")
    ax.scatter([1978], [header_y], color=theme.PARTY_COLORS["R"], s=40, edgecolor=theme.BG,
               linewidth=0.8, clip_on=False)
    ax.text(1981, header_y, "Republican", color=theme.PARTY_COLORS["R"], fontweight="bold",
            fontsize=10, va="center")

    return charts.finish(fig, ax, out_path, source=SOURCE_NOTE, legend=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coverage",
                        default=ROOT / "data/processed/platforms_historical_coverage.csv")
    parser.add_argument("--out", default=ROOT / "outputs/platform_corpus_recency.png")
    args = parser.parse_args(argv)

    coverage_path = Path(args.coverage)
    if not coverage_path.exists():
        parser.error(
            f"{coverage_path} not found - run 'python -m state_politics.platforms.dataverse' first"
        )

    coverage = pd.read_csv(coverage_path)
    out = build_figure(coverage, Path(args.out))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

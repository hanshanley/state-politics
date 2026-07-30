#!/usr/bin/env python3
"""Plot how far state parties sit from their *own* party, against the other party.

The project's other figures treat each party as one actor. This one tests that assumption: if
two co-partisan state organizations are nearly as far apart as two opposed ones, then "the
Republican agenda" is an average over genuinely different actors rather than a single object.

Reads the artifacts written by ``python -m state_politics.analysis.intraparty``.

Usage::

    python scripts/plot_intraparty.py
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
    "Sources: platform planks from Hopkins, Coffey, Galvin, Gamm, Henderson, Paddock & "
    "Schickler (2022), 'Select American State Party Platforms, 1846-2017', V3.0, Harvard "
    "Dataverse, doi:10.7910/DVN/KNOSHL, CC0 1.0, plus 2018-present platforms collected for "
    "this project; bills from Open States / Plural Policy, '2026-07 public PostgreSQL dump', "
    "public domain. {sample} Each bar is a mean cosine distance between topic-share vectors, "
    "over the states where both parties clear the 30-observation floor. Distance measures "
    "*agenda overlap, not agreement*: two organizations devoting equal attention to a topic "
    "are close here even when they advocate opposite policies."
)


def load(root: Path, name: str) -> pd.DataFrame | None:
    path = root / "data" / "processed" / name
    return pd.read_csv(path) if path.exists() else None


def build_figure(rows: list[dict], out_path: Path, *, sample: str = "") -> Path:
    # Two rows only: a tall canvas would leave a large empty band between them and push
    # the tick labels onto the axis.
    fig, ax = charts.new_figure(figsize=(11, 3.9))

    labels = [row["label"] for row in rows]
    positions = list(range(len(rows)))
    for position, row in zip(positions, rows, strict=True):
        ax.plot([row["within"], row["between"]], [position, position],
                color=theme.GRID, linewidth=2.0, zorder=1, solid_capstyle="round")
    ax.scatter([r["within"] for r in rows], positions, s=90, zorder=2,
               color=theme.MUTED, edgecolor=theme.BG, linewidth=0.8,
               label="Between two state parties of the SAME party")
    ax.scatter([r["between"] for r in rows], positions, s=90, zorder=2,
               color=theme.ACCENT, edgecolor=theme.BG, linewidth=0.8,
               label="Between opposing state parties")

    for position, row in zip(positions, rows, strict=True):
        ax.annotate(f"{row['ratio']:.0%} as far apart",
                    xy=(max(row["within"], row["between"]), position),
                    xytext=(10, 0), textcoords="offset points",
                    va="center", fontsize=10, color=theme.TEXT, fontweight="bold")

    ax.set_yticks(positions)
    ax.set_yticklabels(labels, fontsize=11)
    ax.set_ylim(len(rows) - 0.45, -0.55)  # padding, so rows never sit on the frame
    ax.set_xlim(0, max(r["between"] for r in rows) * 1.42)
    ax.grid(axis="x", linestyle="-", linewidth=0.5)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)

    charts.style_axes(
        ax,
        "State parties barely cluster by party",
        "Mean cosine distance between topic-share vectors",
        "",
        subtitle="Two co-partisan state organizations are almost as far apart as two opposed ones",
    )
    ax.legend(loc="center right", frameon=False, labelcolor=theme.TEXT, fontsize=9.5)

    return charts.finish(fig, ax, out_path, source=SOURCE_NOTE.format(sample=sample),
                         legend=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=ROOT / "outputs/intraparty_coherence.png")
    args = parser.parse_args(argv)

    rows = []
    for stream, label in (("platform", "What they say"),
                          ("bill", "What they file")):
        frame = load(ROOT, f"intraparty_{stream}_coherence.csv")
        if frame is None or frame.empty:
            continue
        record = frame.iloc[0]
        rows.append({
            "label": f"{label}  ({int(record['n_states'])} states)",
            "within": float(record["mean_within"]),
            "between": float(record["between"]),
            "ratio": float(record["within_over_between"]),
        })
    if not rows:
        parser.error("no intraparty coherence artifacts found - run "
                     "'python -m state_politics.analysis.intraparty' first")

    sample = "Restricted to the 2018-present platform era."
    out = build_figure(rows, Path(args.out), sample=sample)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

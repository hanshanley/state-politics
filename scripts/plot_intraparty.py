#!/usr/bin/env python3
"""Plot average topic similarity within and across parties.

The analysis artifact stores cosine distance. This figure converts it to similarity because a
direct comparison such as "73% versus 68% similar" is easier to interpret than a ratio of two
abstract distances.

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
from matplotlib.ticker import PercentFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.plotting import charts, theme  # noqa: E402

SOURCE_NOTE = (
    "Sources: platform planks from Hopkins, Coffey, Galvin, Gamm, Henderson, Paddock & "
    "Schickler (2022), 'Select American State Party Platforms, 1846-2017', V3.0, Harvard "
    "Dataverse, doi:10.7910/DVN/KNOSHL, CC0 1.0, plus 2018-present platforms collected for "
    "this project; bills from Open States / Plural Policy, '2026-07 public PostgreSQL dump', "
    "public domain. {sample} Platforms require at least 30 classified current planks per "
    "organization. Nebraska is excluded from bills because its legislature is formally "
    "nonpartisan. "
    "Similarity measures *topic mix, not policy agreement*: organizations can discuss the same "
    "topic while taking opposing positions."
)


def load(root: Path, name: str) -> pd.DataFrame | None:
    path = root / "data" / "processed" / name
    return pd.read_csv(path) if path.exists() else None


def build_figure(rows: list[dict], out_path: Path, *, sample: str = "") -> Path:
    fig, ax = charts.new_figure(figsize=(11, 4.6))

    labels = [row["label"] for row in rows]
    positions = list(range(len(rows)))
    bar_height = 0.28
    same = [row["same_similarity"] for row in rows]
    opposite = [row["opposite_similarity"] for row in rows]
    ax.barh(
        [position - bar_height / 2 for position in positions],
        same,
        height=bar_height,
        color=theme.BLUE,
    )
    ax.barh(
        [position + bar_height / 2 for position in positions],
        opposite,
        height=bar_height,
        color=theme.ACCENT,
    )

    for position, row in zip(positions, rows, strict=True):
        advantage = row["same_similarity"] - row["opposite_similarity"]
        ax.text(
            row["same_similarity"] - 0.012,
            position - bar_height / 2,
            f"Same-party  {row['same_similarity']:.1%}",
            ha="right",
            va="center",
            fontsize=9,
            color="white",
            fontweight="bold",
        )
        ax.text(
            row["opposite_similarity"] - 0.012,
            position + bar_height / 2,
            f"Opposite-party  {row['opposite_similarity']:.1%}",
            ha="right",
            va="center",
            fontsize=9,
            color="white",
            fontweight="bold",
        )
        ax.annotate(
            f"same-party advantage: {advantage:.1%}",
            xy=(max(row["same_similarity"], row["opposite_similarity"]), position),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9.5,
            color=theme.TEXT,
            fontweight="bold",
        )

    ax.set_yticks(positions)
    ax.set_yticklabels(labels, fontsize=11)
    ax.set_ylim(len(rows) - 0.6, -0.6)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1))
    ax.grid(axis="x", linestyle="-", linewidth=0.5)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)

    charts.style_axes(
        ax,
        "Party label only modestly predicts topic emphasis",
        "Average topic-profile similarity",
        "",
        subtitle=(
            "Higher values mean two state organizations devote similar shares "
            "to the same topics"
        ),
    )
    return charts.finish(fig, ax, out_path, source=SOURCE_NOTE.format(sample=sample),
                         legend=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=ROOT / "outputs/intraparty_coherence.png")
    args = parser.parse_args(argv)

    rows = []
    state_counts = {}
    for stream, label in (("platform", "Platforms"),
                          ("bill", "Bills")):
        frame = load(ROOT, f"intraparty_{stream}_coherence.csv")
        if frame is None or frame.empty:
            continue
        record = frame.iloc[0]
        state_counts[stream] = int(record["n_states"])
        rows.append({
            "label": f"{label}  ({int(record['n_states'])} states)",
            "same_similarity": 1 - float(record["mean_within"]),
            "opposite_similarity": 1 - float(record["between"]),
        })
    if not rows:
        parser.error("no intraparty coherence artifacts found - run "
                     "'python -m state_politics.analysis.intraparty' first")

    sample = (
        "Restricted to the 2018-present platform era. "
        f"Matched samples: {state_counts.get('platform', 0)} platform states and "
        f"{state_counts.get('bill', 0)} bill states."
    )
    out = build_figure(rows, Path(args.out), sample=sample)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

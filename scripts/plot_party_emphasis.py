#!/usr/bin/env python3
"""Plot what Democratic and Republican state parties emphasize.

The project's headline comparison: for each issue topic, the share of platform planks devoted
to it by Democratic state parties against Republican ones. A dumbbell is the right form because
the gap between the two dots *is* the finding.

Reads ``data/processed/emphasis_by_party.csv`` from
``python -m state_politics.analysis.emphasis``.

Usage::

    python scripts/plot_party_emphasis.py
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
    "Sources: state party platforms 1990-2017 from Hopkins, Coffey, Galvin, Gamm, Henderson, "
    "Paddock & Schickler (2022), 'Select American State Party Platforms, 1846-2017', V3.0, "
    "Harvard Dataverse, doi:10.7910/DVN/KNOSHL, CC0 1.0; and 2018-present platforms published by "
    "the individual state party committees, collected for this project via the Internet Archive "
    "Wayback Machine and the parties' own sites. Accessed 2026-07-29. Each point is the "
    "equal-weight mean of state-party topic shares over states represented for both parties "
    "({sample}); pooled-plank sensitivity results are retained separately. Topics "
    "follow the Comparative Agendas Project major-topic scheme. Planks are classified by a local "
    "sentence-transformer scoring 62% top-1 and 78% top-2 against a 50-plank hand-labelled "
    "sample, so these shares describe broad aggregate emphasis, not individual planks."
)


def sample_description(planks_path: Path) -> str:
    """Describe the sample from the data itself, so the caption cannot go stale."""
    if not planks_path.exists():
        return "see data/processed/planks_classified.parquet"
    planks = pd.read_parquet(planks_path, columns=["document_index", "topic"])
    classified = int(planks["topic"].notna().sum())
    return (f"{classified:,} classified planks of {len(planks):,}, "
            f"{planks['document_index'].nunique():,} documents")


def build_figure(table: pd.DataFrame, out_path: Path, *, sample: str = "") -> Path:
    table = table.sort_values("gap").reset_index(drop=True)
    labels = table["topic_name"].tolist()
    dem = (table["D"] * 100).tolist()
    rep = (table["R"] * 100).tolist()

    fig, ax = charts.new_figure(figsize=(11, 10))
    charts.dumbbell(
        ax, labels, dem, rep,
        left_color=theme.PARTY_COLORS["D"], right_color=theme.PARTY_COLORS["R"],
        left_label="Democratic state parties", right_label="Republican state parties",
        markersize=8.0,
    )
    ax.invert_yaxis()  # largest Democratic lead at the top

    charts.style_axes(
        ax,
        "What Democratic and Republican state parties talk about",
        "Share of platform planks (%)",
        "",
        subtitle="Topics ordered by how much more one party emphasizes them",
    )
    ax.legend(loc="lower right", frameon=False, labelcolor=theme.TEXT, fontsize=10.5)
    return charts.finish(fig, ax, out_path, source=SOURCE_NOTE.format(sample=sample),
                         legend=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", default=ROOT / "data/processed/emphasis_by_party.csv")
    parser.add_argument("--out", default=ROOT / "outputs/party_emphasis.png")
    args = parser.parse_args(argv)

    table_path = Path(args.table)
    if not table_path.exists():
        parser.error(
            f"{table_path} not found - run 'python -m state_politics.analysis.emphasis' first"
        )

    sample = sample_description(ROOT / "data/processed/planks_classified.parquet")
    out = build_figure(pd.read_csv(table_path), Path(args.out), sample=sample)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

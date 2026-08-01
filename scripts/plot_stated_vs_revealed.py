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
    "{sample}. Both sides use equal-state means over the same matched state set and are "
    "restricted to the same 2018-present window. Bills are attributed "
    "to a party by their primary sponsors, falling back to cosponsors only when no primary "
    "sponsor resolves. Topics follow the Comparative Agendas "
    "Project major-topic scheme, assigned by a local sentence-transformer scoring 62% top-1 and "
    "78% top-2 on a hand-labelled plank sample. Bills are classified from titles, which are "
    "shorter and noisier than planks. Filing a bill is not passing one: this measures agenda, "
    "not achievement. Rows marked † are contradicted when bill topics are "
    "re-derived from Open States subject tags assigned by legislative staff rather than by "
    "this model, and should not be read as findings; the classifier tends to file a tax bill "
    "under the thing being taxed, which inflates housing in particular."
)


def sample_description(root: Path) -> str:
    """Describe both samples from the data itself, so the caption cannot go stale."""
    parts = []
    planks = root / "data/processed/planks_classified.parquet"
    if planks.exists():
        frame = pd.read_parquet(planks, columns=["document_index", "topic", "era"])
        modern = frame[frame["era"] == "2018-present"]
        parts.append(f"{int(modern['topic'].notna().sum()):,} classified planks from "
                     f"{modern['document_index'].nunique():,} 2018-present documents")
    bills = root / "data/processed/bill_emphasis_by_party.csv"
    if bills.exists():
        bill_frame = pd.read_csv(bills)
        parts.append(
            f"{int(bill_frame['n_bills'].sum()):,} classified bills "
            f"from {int(bill_frame['n_states'].max())} matched states"
        )
    return "; ".join(parts)


def unreliable_topics(root: Path, table: pd.DataFrame) -> set[tuple[int, str]]:
    """(topic, party) pairs an independent labelling contradicts.

    Bill topics are re-derived from Open States `subject` tags, which are assigned by
    legislative staff and owe nothing to this project's classifier. A row is flagged when the
    two labellings put the filed share on *opposite* sides of the stated share -- that is, when
    they disagree about the direction of the gap, which is the only thing the figure claims.
    """
    replication = root / "data/processed/headline_tag_replication.csv"
    if not replication.exists():
        return set()
    comparison = pd.read_csv(replication)
    return {
        (int(row.topic), row.party)
        for row in comparison[~comparison["holds"].fillna(False)].itertuples()
    }


def build_figure(table: pd.DataFrame, out_path: Path, *, sample: str = "",
                 flagged: set[tuple[int, str]] | None = None) -> Path:
    fig, axes = charts.new_figure(figsize=(13, 9))
    fig.clf()
    axes = fig.subplots(1, 2, sharex=True)

    # One row order for both panels. The right panel's tick labels are hidden so the two share
    # the left panel's, which means sorting each party independently silently plots R's values
    # against D's labels -- it mislabelled 15 of 21 rows, reading R's government-operations gap
    # as "Agriculture". Order by the two parties' mean gap so the shared axis stays honest and
    # the figure still reads sorted.
    order = (table.groupby("topic_name")["stated_minus_revealed"].mean()
             .sort_values().index.tolist())

    for ax, party in zip(axes, ("D", "R"), strict=True):
        subset = table[table["party"] == party].copy()
        # Reindexed on the *full* shared order, not the intersection: the panels share one set
        # of tick labels, so unequal row counts would give them different y-limits and slide
        # the right panel's dots off the labels they are read against.
        subset = subset.set_index("topic_name").reindex(order).reset_index()
        labels = subset["topic_name"].tolist()
        stated = (subset["stated_share"] * 100).tolist()
        revealed = (subset["revealed_share"] * 100).tolist()

        codes = subset["topic"].fillna(-1).astype(int).tolist()
        # The dagger goes on the shared label, so it has to mean "flagged for either party" --
        # marking only this panel would leave the other panel's contradiction unexplained.
        labels = [f"{label} †" if any((code, side) in (flagged or set()) for side in ("D", "R"))
                  else label
                  for label, code in zip(labels, codes, strict=True)]

        color = theme.PARTY_COLORS[party]
        charts.dumbbell(
            ax, labels, stated, revealed,
            left_color=color, right_color=color,
            left_label="Platform share", right_label="Bill share",
            left_marker="o", right_marker="s",
            left_filled=False, right_filled=True,
            markersize=7.5,
        )
        # Pinned rather than autoscaled. A topic missing for one party leaves that row empty,
        # and matplotlib would then give the two panels different limits -- sliding one panel's
        # dots off the shared tick labels the other panel supplies.
        ax.set_ylim(len(order) - 0.5, -0.5)
        ax.set_title(theme.PARTY_LABELS[party], fontweight="bold", fontsize=14, pad=12)
        ax.set_xlabel("Share of that party's planks / bills (%)", labelpad=2)
        ax.grid(axis="x", linestyle="-", linewidth=0.5)
        ax.set_axisbelow(True)

    axes[1].tick_params(labelleft=False)
    # Centre-right of the left panel is the only reliably empty region: the rows sitting there
    # (environment, social welfare, agriculture, energy) are all low-single-digit shares, while
    # the corners are occupied by the large civil-rights and law-and-crime gaps.
    axes[0].legend(loc="center right", frameon=False, labelcolor=theme.TEXT, fontsize=10)

    fig.suptitle("What state parties say, and what they actually file",
                 fontweight="bold", fontsize=18, y=0.985)
    fig.text(0.5, 0.945,
             "Open circle = platform share; solid square = bill share; "
             "the line joins the same topic. "
             "\u2020 = either party's direction fails to replicate under legislative subject tags.",
             ha="center", va="top", fontsize=11, color=theme.MUTED)

    note = theme.source_note(fig, SOURCE_NOTE.format(sample=sample))
    theme.layout_with_note(fig, note, top=0.935)
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

    table = pd.read_csv(table_path)
    out = build_figure(table, Path(args.out), sample=sample_description(ROOT),
                       flagged=unreliable_topics(ROOT, table))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

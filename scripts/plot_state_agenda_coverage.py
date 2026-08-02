#!/usr/bin/env python3
"""Plot all-state stated-agenda coverage without conflating institutions.

Party-committee platforms/resolutions are the primary corpus. Four states have no such
document from either party, so official legislative caucus priority agendas supply a separate,
explicitly labelled supplement. This figure makes the coverage complete *and* the distinction
visible, instead of quietly colouring a caucus agenda as if it were a party platform.
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

STATE_CODES = (
    "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "IA", "ID",
    "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO", "MS", "MT",
    "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY",
)

SOURCE_NOTE = (
    "Sources: party-committee platforms and state-committee resolutions collected from official "
    "party sites, official third-party document hosts, and the Internet Archive; four "
    "supplemental legislative-caucus priority sources from the Kentucky Senate Republican Caucus "
    "(2024), Maryland Senate Democrats (published 2025 for the 2026 session), "
    "New Jersey Assembly Republicans (2025), and "
    "Pennsylvania Senate Democrats (2025). The green marker is deliberately a different "
    "institution: caucus evidence completes state-level agenda coverage but is never merged "
    "with party platforms or used in the platform-vs-bill comparison."
)


def build_figure(platforms: pd.DataFrame, caucuses: pd.DataFrame, out_path: Path) -> Path:
    """Render a compact 5-column grid of all 50 states by evidence source."""
    committee_states = set(platforms.loc[platforms["confirmed"], "state"])
    caucus_states = set(caucuses["state"])
    unresolved = set(STATE_CODES) - committee_states - caucus_states
    if unresolved:
        raise ValueError(f"states have no stated-agenda evidence: {sorted(unresolved)}")
    overlap = committee_states & caucus_states
    if overlap:
        raise ValueError(
            "supplement should contain only states absent from the party committee corpus: "
            f"{sorted(overlap)}"
        )

    fig, ax = charts.new_figure(figsize=(10.5, 8.0))
    for index, state in enumerate(STATE_CODES):
        column = index // 10
        row = 9 - index % 10
        color = theme.BLUE if state in committee_states else theme.GREEN
        ax.scatter(
            column,
            row,
            color=color,
            s=125,
            edgecolor=theme.BG,
            linewidth=0.9,
            zorder=3,
        )
        ax.text(
            column + 0.12,
            row,
            state,
            ha="left",
            va="center",
            fontsize=11,
            fontweight="bold",
            color=theme.TEXT,
        )
    ax.set_xlim(-0.35, 4.75)
    ax.set_ylim(-0.75, 9.75)
    ax.axis("off")

    charts.style_axes(
        ax,
        "Every state has a stated state-level agenda source",
        "",
        "",
        subtitle=(
            "46 states have party-committee evidence; the 4 states without it are covered "
            "only by separately labelled legislative-caucus priorities"
        ),
    )
    ax.legend(
        handles=[
            matplotlib.patches.Patch(facecolor=theme.BLUE, edgecolor=theme.BG,
                                     label=("Party committee platform or "
                                            "state-committee resolution")),
            matplotlib.patches.Patch(facecolor=theme.GREEN, edgecolor=theme.BG,
                                     label=("Legislative caucus priority source "
                                            "(separate corpus)")),
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=2,
        frameon=False,
        fontsize=10,
    )
    return charts.finish(fig, ax, out_path, source=SOURCE_NOTE, legend=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--platforms", default=ROOT / "data/processed/platforms_2018_present.parquet"
    )
    parser.add_argument(
        "--caucuses", default=ROOT / "data/processed/caucus_priorities.parquet"
    )
    parser.add_argument("--out", default=ROOT / "outputs/state_agenda_coverage.png")
    args = parser.parse_args(argv)

    platforms = pd.read_parquet(args.platforms)
    caucuses = pd.read_parquet(args.caucuses)
    out = build_figure(platforms, caucuses, Path(args.out))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    "(2024), Maryland Senate Democrats (2026), New Jersey Assembly Republicans (2025), and "
    "Pennsylvania Senate Democrats (2025). The green marker is deliberately a different "
    "institution: caucus evidence completes state-level agenda coverage but is never merged "
    "with party platforms or used in the platform-vs-bill comparison."
)


def build_figure(platforms: pd.DataFrame, caucuses: pd.DataFrame, out_path: Path) -> Path:
    """Render one row per state and two mutually exclusive evidence columns."""
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

    fig, ax = charts.new_figure(figsize=(10.5, 12.5))
    positions = {state: index for index, state in enumerate(STATE_CODES)}
    for state, position in positions.items():
        if state in committee_states:
            ax.scatter(0, position, color=theme.BLUE, s=85, edgecolor=theme.BG, linewidth=0.8,
                       zorder=3)
        else:
            ax.scatter(1, position, color=theme.GREEN, s=85, edgecolor=theme.BG, linewidth=0.8,
                       zorder=3)

    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Party committee\nplatform or resolution",
                        "Legislative caucus\npriority supplement"],
                       fontsize=11, fontweight="bold")
    # The column labels are already repeated below the plot. Showing them above as well puts
    # them directly through the explanatory subtitle on a 50-row figure.
    ax.tick_params(axis="x", labeltop=False, labelbottom=True)
    ax.set_yticks(list(positions.values()))
    ax.set_yticklabels(STATE_CODES, fontsize=9)
    ax.set_ylim(-1.5, len(STATE_CODES))
    ax.invert_yaxis()
    ax.set_xlim(-0.55, 1.55)
    ax.grid(axis="y", linestyle="-", linewidth=0.5)
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)

    charts.style_axes(
        ax,
        "Every state has a stated state-level agenda source",
        "",
        "",
        subtitle=("46 states have party-committee evidence; 4 are separately supplemented "
                  "by official legislative caucus priorities"),
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
        loc="upper center",
        bbox_to_anchor=(0.5, -0.035),
        ncol=1,
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

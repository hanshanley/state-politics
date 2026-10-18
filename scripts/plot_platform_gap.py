#!/usr/bin/env python3
"""Plot current-collection coverage for all 100 state party organizations.

This is the counterpart to ``plot_platform_coverage.py``. That figure shows where the
historical corpus runs out; this one shows what the project's own collection recovered for
the modern period, and -- just as importantly -- *why* each remaining gap is a gap.

Reads the gap report produced by ``python -m state_politics.platforms.collect``.

Usage::

    python scripts/plot_platform_gap.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: no display required

import matplotlib.patches as mpatches  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.plotting import charts, theme  # noqa: E402

SOURCE_NOTE = (
    "Source: platform documents published by the individual state party committees, located via "
    "the Internet Archive Wayback Machine CDX Server API (https://web.archive.org/cdx/search/cdx) "
    "and the parties' own websites. Collection dates belong to the saved retrieval provenance. "
    "Filled markers indicate documents passing the automated content filter, not verified "
    "adoption or operative status. Retrieval failures, unattempted candidates and filter "
    "rejections remain distinct; zero candidates does not establish publication absence. A "
    "qualifying document is a platform, a set of convention resolutions, a legislative-priorities "
    "agenda or a statement of principles; {non_platform_count} organizations are covered only "
    "by a non-platform document type. A pre-2018 year is an older fallback source still found "
    "by the current collection, not a newly published document."
)

# Statuses in the order they should read: success first, then progressively weaker evidence.
STATUS_STYLE = {
    "found": ("Document passed content filter", None, "o"),
    "fetch_failed": ("Candidate retrieval failed", theme.TEXT, "X"),
    "candidates_partially_unresolved": (
        "Filter rejections and retrieval failures", theme.GOLD, "D",
    ),
    "candidates_rejected": ("Retrieved candidates failed content filter", theme.GOLD, "o"),
    "candidates_unfetched": ("Strong candidates not yet fetched", theme.MUTED, "s"),
    "no_strong_candidates": ("Only weak candidates found", theme.MUTED, "^"),
    "no_candidates": ("No candidate recorded; absence unverified", theme.TEXT, "v"),
}


def build_figure(report: pd.DataFrame, out_path: Path) -> Path:
    unknown = set(report["status"]) - STATUS_STYLE.keys()
    if unknown:
        raise ValueError(f"unsupported collection statuses: {sorted(unknown)}")
    states = sorted(report["state"].unique())
    positions = {state: index for index, state in enumerate(states)}

    fig, ax = charts.new_figure(figsize=(11, 13))

    for _, row in report.iterrows():
        y = positions[row["state"]]
        # Democrats left of centre, Republicans right, so party is readable as position.
        x = -1 if row["party"] == "D" else 1
        status = row["status"]
        if status == "found":
            color = theme.PARTY_COLORS[row["party"]]
            ax.scatter([x], [y], s=150, color=color, edgecolor=theme.BG, linewidth=1.0, zorder=3)
            year = row["latest_year"]
            if pd.notna(year):
                ax.text(x + (0.28 if x > 0 else -0.28), y, str(int(year)),
                        ha="left" if x > 0 else "right", va="center", fontsize=8.5,
                        color=theme.TEXT)
        else:
            color = STATUS_STYLE[status][1] or theme.GRID
            ax.scatter([x], [y], s=110, facecolor=theme.BG, edgecolor=color, linewidth=1.8,
                       zorder=3, marker=STATUS_STYLE[status][2])

    ax.set_yticks(list(positions.values()))
    ax.set_yticklabels(list(positions.keys()), fontsize=9)
    ax.set_ylim(-1.5, len(states))
    ax.invert_yaxis()
    ax.set_xlim(-2.6, 2.6)
    ax.set_xticks([-1, 1])
    ax.set_xticklabels(["Democratic", "Republican"], fontsize=11, fontweight="bold")
    ax.tick_params(axis="x", labeltop=True, labelbottom=True)
    ax.grid(axis="y", linestyle="-", linewidth=0.5)
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)

    charts.style_axes(
        ax,
        "What the current party-document collection recovered",
        "",
        "",
        subtitle="One marker per state party; filled = document passed content filter, "
                 "with its most recent year",
    )

    handles = [
        mpatches.Patch(
            facecolor=theme.BLUE,
            edgecolor=theme.BG,
            label="Democratic qualifying source found",
        ),
        mpatches.Patch(facecolor=theme.ACCENT, edgecolor=theme.BG,
                       label="Republican qualifying source found"),
    ]
    for status, (label, color, marker) in STATUS_STYLE.items():
        if status == "found" or status not in set(report["status"]):
            continue
        handles.append(Line2D(
            [], [], linestyle="none", marker=marker, markerfacecolor=theme.BG,
            markeredgecolor=color, markeredgewidth=1.8, markersize=8, label=label,
        ))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.035),
              ncol=2, frameon=False, fontsize=10)

    found = report[report["status"] == "found"]
    non_platform_count = int(
        found["doc_types"].fillna("").str.split(",").map(
            lambda values: "platform" not in values
        ).sum()
    )
    return charts.finish(
        fig,
        ax,
        out_path,
        source=SOURCE_NOTE.format(non_platform_count=non_platform_count),
        legend=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", default=ROOT / "data/processed/platform_gap_report.csv")
    parser.add_argument("--out", default=ROOT / "outputs/platform_coverage_2018_present.png")
    args = parser.parse_args(argv)

    report_path = Path(args.report)
    if not report_path.exists():
        parser.error(
            f"{report_path} not found - run 'python -m state_politics.platforms.collect' first"
        )

    report = pd.read_csv(report_path)
    out = build_figure(report, Path(args.out))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

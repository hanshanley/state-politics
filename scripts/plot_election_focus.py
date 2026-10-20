#!/usr/bin/env python3
"""Plot state party caucuses that devote unusual attention to election legislation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.analysis.elections import format_title_validation  # noqa: E402
from state_politics.plotting import charts, theme  # noqa: E402

SUBTYPE_LABELS = {
    "voting_and_administration": "Voting & administration",
    "campaign_finance": "Campaign finance",
    "redistricting": "Redistricting",
    "election_security": "Election security",
    "candidates_and_parties": "Candidates & parties",
    "other_election": "Other election policy",
}


def build_figure(focus: pd.DataFrame, validation: dict, out_path: Path, *, top_n: int = 10):
    """Render top election-bill shares relative to same-party peers."""
    fig, axes = charts.new_figure(figsize=(13, 8.2))
    fig.clf()
    axes = fig.subplots(1, 2, sharex=True)
    plotted_min = 0.0
    plotted_max = 0.0
    for ax, party in zip(axes, ("D", "R"), strict=True):
        subset = focus[
            (focus["party"] == party) & focus["focus_reliable"].fillna(False).astype(bool)
            & focus["peer_share"].notna() & focus["overemphasis"].notna()
        ]
        if not subset.empty:
            subset = subset.nlargest(top_n, "overemphasis").sort_values("overemphasis")
        if subset.empty:
            ax.text(
                0.5, 0.5, "Peer comparison unavailable",
                ha="center", va="center", transform=ax.transAxes, color=theme.MUTED,
            )
        else:
            plotted_min = min(plotted_min, float(subset["overemphasis"].min()))
            plotted_max = max(plotted_max, float(subset["overemphasis"].max()))
        y = range(len(subset))
        values = subset["overemphasis"] * 100
        ax.barh(y, values, color=theme.PARTY_COLORS[party], alpha=0.88, height=0.56)
        ax.set_yticks(list(y))
        ax.set_yticklabels(subset["state"], fontsize=10, fontweight="bold")
        for position, row in enumerate(subset.itertuples()):
            subtype = SUBTYPE_LABELS.get(row.top_subtype, row.top_subtype or "Election policy")
            ax.annotate(
                f"{subtype}\n{row.election_share:.1%} vs {row.peer_share:.1%}",
                xy=(row.overemphasis * 100, position),
                xytext=(-5 if row.overemphasis < 0 else 5, 0),
                textcoords="offset points",
                ha="right" if row.overemphasis < 0 else "left",
                va="center",
                fontsize=8.5,
            )
        ax.set_title(theme.PARTY_LABELS[party], fontweight="bold", fontsize=14, pad=10)
        ax.set_xlabel("Election-bill excess over same-party peers (percentage points)")
        ax.grid(axis="x", linestyle="-", linewidth=0.5)
        ax.grid(axis="y", visible=False)
        ax.set_axisbelow(True)

    axes[0].set_xlim(
        (plotted_min * 100 * 1.75, plotted_max * 100 * 1.75)
        if plotted_min != plotted_max else (-1, 1)
    )
    fig.suptitle(
        "Election-title matches relative to same-party peers",
        fontweight="bold",
        fontsize=18,
        y=0.985,
    )
    fig.text(
        0.5,
        0.945,
        "Title-rule matches as a share of supplied D/R-attributed substantive measures",
        ha="center",
        va="top",
        fontsize=11,
        color=theme.MUTED,
    )
    source = (
        "Source: supplied Open States / Plural Policy artifacts; snapshot and findings "
        "not revalidated. Title-rule matches are not verified policy labels. Supplied "
        f"subject-tag agreement: {format_title_validation(validation)}. Tag authorship "
        "and independence are unverified; these metrics are not audited accuracy. Peer "
        "values are leave-one-state-out same-party means. Rankings require at least "
        "500 substantive bills and an observed same-party peer state. Supplied D/R "
        "attribution is not verified filing-time affiliation."
    )
    note = theme.source_note(fig, source)
    theme.layout_with_note(fig, note, top=0.925)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--focus", default=ROOT / "data/processed/election_focus_by_state_party.csv"
    )
    parser.add_argument(
        "--validation", default=ROOT / "data/processed/election_title_validation.json"
    )
    parser.add_argument(
        "--out",
        default=ROOT / "outputs/election_focus_by_state_party.png",
    )
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)

    focus = pd.read_csv(args.focus)
    validation = json.loads(Path(args.validation).read_text(encoding="utf-8"))
    out = build_figure(focus, validation, Path(args.out), top_n=args.top)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

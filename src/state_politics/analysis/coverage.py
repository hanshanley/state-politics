"""Machine-readable assessment of what the current data can and cannot answer.

Deep analysis also means refusing unsupported questions. This module derives coverage and
capability statements from artifact schemas and sample sizes instead of relying on prose.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

__all__ = ["build_capability_report"]


def build_capability_report(data_dir: Path):
    """Return one row per analytical question with support level and evidence."""
    import pandas as pd
    import pyarrow.parquet as pq

    bill_path = data_dir / "bills.parquet"
    bill_columns = set(pq.read_schema(bill_path).names)
    optional_bill_columns = [
        column
        for column in ("recorded_outcome", "recorded_enacted", "originating_chamber")
        if column in bill_columns
    ]
    bills = pd.read_parquet(
        bill_path,
        columns=["state", "sponsor_party", "subject", *optional_bill_columns],
    )
    platforms = pd.read_parquet(
        data_dir / "platforms_2018_present.parquet",
        columns=["state", "party", "confirmed", "year"],
    )
    caucuses = pd.read_parquet(
        data_dir / "caucus_priorities.parquet",
        columns=["state", "party"],
    )
    atlas = pd.read_csv(data_dir / "state_party_focus.csv")
    elections = pd.read_csv(data_dir / "election_focus_by_state_party.csv")
    bill_coverage = pd.read_csv(data_dir / "bill_classification_coverage.csv")
    tagged = bills["subject"].fillna("").str.len() > 0
    confirmed = platforms[platforms["confirmed"]]
    years = pd.to_numeric(confirmed["year"], errors="coerce")
    current = confirmed[years.isna() | (years >= 2018)]
    stated_states = set(current["state"]) | set(caucuses["state"])
    current_orgs = current.groupby(["state", "party"]).ngroups
    all_date_orgs = confirmed.groupby(["state", "party"]).ngroups
    outcomes_path = data_dir / "bill_outcomes_by_state_party.csv"
    outcomes = pd.read_csv(outcomes_path) if outcomes_path.exists() else pd.DataFrame()
    votes_path = data_dir / "vote_events.parquet"
    vote_parties_path = data_dir / "vote_party_counts.parquet"
    has_outcomes = "recorded_outcome" in bills
    has_chambers = "originating_chamber" in bills
    has_votes = votes_path.exists() and vote_parties_path.exists()
    rows = [
        {
            "question": "Current stated state-level agenda",
            "support": "supported",
            "coverage": f"{len(stated_states)}/50 states",
            "evidence": (
                f"{len(current)} current party-committee documents plus "
                f"{len(caucuses)} separately labelled caucus sources"
            ),
        },
        {
            "question": "Reliable within-party stated comparison",
            "support": "partial",
            "coverage": f"{int(atlas['stated_focus_reliable'].sum())}/100 state-party rows",
            "evidence": "Requires at least 30 classified units; smaller sources remain descriptive",
        },
        {
            "question": "Introduced-bill agenda by party and state",
            "support": "supported",
            "coverage": f"{bill_coverage['state'].nunique()}/50 states",
            "evidence": (
                f"{int(bill_coverage['n_attributed'].sum()):,} D/R-attributed bills; "
                f"{int(bill_coverage['n_procedural_excluded'].sum()):,} procedural shells "
                "excluded; Nebraska is formally nonpartisan"
            ),
        },
        {
            "question": "Election and voting bill focus",
            "support": "supported",
            "coverage": f"{elections['state'].nunique()}/50 states",
            "evidence": f"{int(elections['n_election_bills'].sum()):,} detected substantive bills",
        },
        {
            "question": "Legislative-staff tag validation",
            "support": "partial",
            "coverage": f"{bills.loc[tagged, 'state'].nunique()}/50 states",
            "evidence": f"{int(tagged.sum()):,} bills carry source subject tags",
        },
        {
            "question": "Party-topic bill trends over time",
            "support": (
                "supported"
                if (data_dir / "bill_topic_trends_by_party.csv").exists()
                else "not_yet_generated"
            ),
            "coverage": "2018-2025",
            "evidence": (
                "Equal-state 2018-2019 vs 2024-2025 change with paired "
                "sign-flip tests and BH q-values"
            ),
        },
        {
            "question": "Bill enactment/pass rates",
            "support": "supported" if has_outcomes else "unsupported",
            "coverage": (
                f"{outcomes.loc[outcomes['reliable'], 'state'].nunique()}/50 states"
                if has_outcomes and not outcomes.empty
                else "0 states in processed artifact"
            ),
            "evidence": (
                f"{pq.ParquetFile(data_dir / 'bill_actions.parquet').metadata.num_rows:,} "
                "explicit actions; state-party estimates require 500 bills and 80% coverage"
                if has_outcomes
                else "bills.parquet has no actions, status, result or enacted fields"
            ),
        },
        {
            "question": "Roll-call voting behavior",
            "support": "partial" if has_votes else "unsupported",
            "coverage": (
                f"{pd.read_parquet(vote_parties_path, columns=['state'])['state'].nunique()}"
                "/50 states"
                if has_votes
                else "0 states in processed artifact"
            ),
            "evidence": (
                f"{pq.ParquetFile(votes_path).metadata.num_rows:,} vote events; "
                "Missouri has no resolved person-vote rows"
                if has_votes
                else "No votes table is retained by the current ingest"
            ),
        },
        {
            "question": "Chamber-specific historical agenda",
            "support": "supported" if has_chambers else "unsupported",
            "coverage": (
                f"{bills.loc[bills['originating_chamber'] != 'unknown', 'state'].nunique()}"
                "/50 states"
                if has_chambers
                else "0 states in processed bill artifact"
            ),
            "evidence": (
                "Originating chamber is resolved through historical Open States organizations"
                if has_chambers
                else "Bills are not linked to a historical chamber field"
            ),
        },
        {
            "question": "Policy stance or ideological direction",
            "support": "limited",
            "coverage": "attention plus recorded yes/no votes",
            "evidence": (
                "Votes measure support for specific motions, not a one-dimensional ideology "
                "score or the policy direction encoded by every bill"
            ),
        },
        {
            "question": "Current party-committee platform coverage",
            "support": "partial",
            "coverage": f"{current['state'].nunique()}/50 states; "
                        f"{current_orgs}/100 organizations",
            "evidence": (
                f"{100 - current_orgs} lack a current source: "
                f"{100 - all_date_orgs} have no confirmed source at any date and "
                f"{all_date_orgs - current_orgs} are legacy-only"
            ),
        },
    ]
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default=root / "data/processed")
    parser.add_argument("--out", default=root / "data/processed/analysis_capabilities.json")
    args = parser.parse_args(argv)

    report = build_capability_report(Path(args.data_dir))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report.to_dict(orient="records"), indent=2), encoding="utf-8"
    )
    report.to_csv(out.with_suffix(".csv"), index=False)
    print(report.to_string(index=False))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

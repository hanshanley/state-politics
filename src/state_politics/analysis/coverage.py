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

    bills = pd.read_parquet(data_dir / "bills.parquet")
    platforms = pd.read_parquet(data_dir / "platforms_2018_present.parquet")
    caucuses = pd.read_parquet(data_dir / "caucus_priorities.parquet")
    atlas = pd.read_csv(data_dir / "state_party_focus.csv")
    elections = pd.read_csv(data_dir / "election_focus_by_state_party.csv")
    bill_coverage = pd.read_csv(data_dir / "bill_classification_coverage.csv")
    tagged = bills["subject"].fillna("").str.len() > 0
    confirmed = platforms[platforms["confirmed"]]
    years = pd.to_numeric(confirmed["year"], errors="coerce")
    current = confirmed[years >= 2018]
    stated_states = set(current["state"]) | set(caucuses["state"])
    current_orgs = current.groupby(["state", "party"]).ngroups
    all_date_orgs = confirmed.groupby(["state", "party"]).ngroups
    rows = [
        {
            "question": "Current stated state-level agenda",
            "support": "supported",
            "coverage": f"{len(stated_states)}/50 states",
            "evidence": (
                f"{len(current)} party-committee documents dated 2018+ plus "
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
            "support": "unsupported",
            "coverage": "0 states in processed artifact",
            "evidence": "bills.parquet has no actions, status, result or enacted fields",
        },
        {
            "question": "Roll-call voting behavior",
            "support": "unsupported",
            "coverage": "0 states in processed artifact",
            "evidence": "No votes table is retained by the current ingest",
        },
        {
            "question": "Chamber-specific historical agenda",
            "support": "unsupported",
            "coverage": "0 states in processed bill artifact",
            "evidence": "Bills are not linked to a historical chamber field",
        },
        {
            "question": "Policy stance or ideological direction",
            "support": "limited",
            "coverage": "topic attention only",
            "evidence": "Topic shares measure attention, not support/opposition within a topic",
        },
        {
            "question": "Current party-committee platform coverage",
            "support": "partial",
            "coverage": f"{current['state'].nunique()}/50 states; "
                        f"{current_orgs}/100 organizations",
            "evidence": (
                f"{100 - current_orgs} lack a 2018+ source: "
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

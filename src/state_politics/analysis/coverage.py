"""Machine-readable assessment of what the current data can and cannot answer.

Deep analysis also means refusing unsupported questions. This module derives coverage and
capability statements from artifact schemas and sample sizes instead of relying on prose.
Availability and sample size do not establish scientific validation or operative platforms.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

__all__ = ["build_capability_report", "build_source_ledger"]


def build_source_ledger(organizations, historical, discovery=()):
    """Account for every expected organization without treating discovery as collection."""
    from ..bills.openstates_dump import STATE_CODES
    from ..provenance import utc_now_iso

    expected = {(state.upper(), party) for state in STATE_CODES for party in ("D", "R")}
    registered = {(row["state"], row["party"]) for row in organizations}
    if registered != expected or len(organizations) != len(expected):
        raise ValueError(
            "registry must identify exactly the 100 expected state-party organizations"
        )
    searches = {(row["state"], row["party"]): row for row in discovery}
    documents = defaultdict(list)
    for row in historical:
        if (row["state"], row["party"]) in expected:
            documents[row["state"], row["party"]].append(row)
    rows = []
    for org in sorted(organizations, key=lambda row: (row["state"], row["party"])):
        key = (org["state"], org["party"])
        archive = documents[key]
        search = searches.get(key)
        searched = search and str(search.get("searched", "")).lower() == "true"
        rows.append({
            "state": key[0], "party": key[1], "institution": "party_committee",
            "name": org["name"], "website": org.get("website"),
            "registry_verified_on": org.get("verified_on"),
            "registry_needs_review": org.get("needs_review"),
            "historical_document_count": len(archive),
            "historical_latest_year": max((row["year"] for row in archive), default=None),
            "discovery_status": (
                "searched" if searched else "retrieval_failed" if search else "not_completed"
            ),
            "modern_evidence_status": "unresolved",
            "operative_platform_status": "unresolved",
            "bill_party_comparison": (
                "not_applicable_nonpartisan" if key[0] == "NE" else "not_rebuilt"
            ),
            "discovery_evidence": search,
            "gap_disposition": (
                "Source discovery is not collection or a reviewed absence determination."
            ),
        })
    return {
        "schema_version": 1, "generated_at": utc_now_iso(), "analysis_cutoff": None,
        "status": "incomplete_source_audit", "expected_organizations": 100,
        "rows": rows,
        "limitations": [
            "Historical evidence is not evidence of a currently operative platform.",
            "No organization is marked absent merely because a search failed or found no URLs.",
            "A verified analytical cutoff requires recovered and reconciled source coverage.",
        ],
    }


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
    dated_from_2018 = confirmed[years >= 2018]
    undated = confirmed[years.isna()]
    dated_orgs = dated_from_2018.groupby(["state", "party"]).ngroups
    undated_orgs = undated.groupby(["state", "party"]).ngroups
    available_orgs = confirmed.groupby(["state", "party"]).ngroups
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
            "support": "unsupported",
            "coverage": "operative coverage unresolved",
            "evidence": (
                f"{len(dated_from_2018)} heuristic-confirmed dated 2018+ source records; "
                f"{len(undated)} undated source records; "
                f"{len(caucuses)} separately labelled caucus sources. "
                "Content confirmation verifies neither adoption, operative version, "
                "analytical cutoff nor topic accuracy"
            ),
        },
        {
            "question": "Reliable within-party stated comparison",
            "support": "unsupported",
            "coverage": "comparison validity unresolved",
            "evidence": (
                f"{int(atlas['stated_focus_reliable'].sum())}/100 state-party rows pass "
                "the legacy 30-unit heuristic. Sample size alone does not validate "
                "classification, source versions or within-party comparability"
            ),
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
            "support": "unsupported",
            "coverage": "operative coverage unresolved",
            "evidence": (
                f"{dated_orgs}/100 organizations have heuristic-confirmed dated 2018+ "
                f"source records; {undated_orgs}/100 have undated source records; "
                f"{available_orgs}/100 have source records at any date or undated. "
                "These overlapping availability counts establish neither operative "
                "coverage nor publication absence"
            ),
        },
    ]
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default=root / "data/processed")
    parser.add_argument("--out", default=root / "data/processed/analysis_capabilities.json")
    parser.add_argument("--sources-only", action="store_true")
    parser.add_argument("--registry", type=Path, default=root / "conf/party_registry.yml")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.sources_only:
        import yaml

        data = Path(args.data_dir)
        historical_path = data / "platforms_historical.jsonl"
        historical = [
            json.loads(line) for line in historical_path.read_text().split("\n") if line
        ]
        discovery_path = data / "platform_discovery_status.csv"
        discovery = []
        if discovery_path.exists():
            with discovery_path.open(newline="") as handle:
                discovery = list(csv.DictReader(handle))
        report = build_source_ledger(
            yaml.safe_load(args.registry.read_text())["organizations"], historical, discovery
        )
        out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote {out}; unresolved modern evidence is not zero coverage")
        return 0
    report = build_capability_report(Path(args.data_dir))
    out.write_text(
        json.dumps(report.to_dict(orient="records"), indent=2), encoding="utf-8"
    )
    report.to_csv(out.with_suffix(".csv"), index=False)
    print(report.to_string(index=False))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

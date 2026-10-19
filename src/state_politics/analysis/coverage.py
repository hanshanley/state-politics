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
    """Inventory retained artifacts without equating availability with scientific support."""
    import pandas as pd
    import pyarrow.parquet as pq

    def read_optional(name, *, columns=None):
        path = data_dir / name
        if not path.exists():
            return None
        if path.suffix == ".parquet":
            return pd.read_parquet(path, columns=columns)
        return pd.read_csv(path)

    def state_coverage(frame):
        return (
            f"{frame['state'].nunique()}/50 states represented in retained artifact"
            if frame is not None else "not measured: source artifact missing"
        )

    bill_path = data_dir / "bills.parquet"
    bill_columns = set(pq.read_schema(bill_path).names) if bill_path.exists() else set()
    optional_bill_columns = [
        column
        for column in ("recorded_outcome", "recorded_enacted", "originating_chamber")
        if column in bill_columns
    ]
    bills = read_optional(
        "bills.parquet",
        columns=["state", "sponsor_party", "subject", *optional_bill_columns],
    )
    platforms = read_optional(
        "platforms_2018_present.parquet",
        columns=["state", "party", "confirmed", "year"],
    )
    caucuses = read_optional(
        "caucus_priorities.parquet",
        columns=["state", "party"],
    )
    atlas = read_optional("state_party_focus.csv")
    elections = read_optional("election_focus_by_state_party.csv")
    bill_coverage = read_optional("bill_classification_coverage.csv")
    trends = read_optional("bill_topic_trends_by_party.csv")
    outcomes = read_optional("bill_outcomes_by_state_party.csv")
    source_evidence = "Contemporary analytical source corpus not retained."
    organization_evidence = "Contemporary organization availability not measured."
    if platforms is not None:
        confirmed = platforms[platforms["confirmed"]]
        years = pd.to_numeric(confirmed["year"], errors="coerce")
        dated_from_2018 = confirmed[years >= 2018]
        undated = confirmed[years.isna()]
        dated_orgs = dated_from_2018.groupby(["state", "party"]).ngroups
        undated_orgs = undated.groupby(["state", "party"]).ngroups
        available_orgs = confirmed.groupby(["state", "party"]).ngroups
        source_evidence = (
            f"{len(dated_from_2018)} heuristic-confirmed dated 2018+ source records; "
            f"{len(undated)} undated source records."
        )
        organization_evidence = (
            f"{dated_orgs}/100 organizations have heuristic-confirmed dated 2018+ "
            f"source records; {undated_orgs}/100 have undated source records; "
            f"{available_orgs}/100 have source records at any date or undated."
        )
    if caucuses is not None:
        source_evidence += f" {len(caucuses)} separately labelled caucus sources."
    bill_evidence = "Source bill availability not measured."
    tag_evidence = "Source subject-tag availability not measured."
    tag_coverage = state_coverage(None)
    chamber_coverage = state_coverage(None)
    if bills is not None:
        chamber_coverage = "not measured: originating-chamber field missing"
        bill_evidence = (
            f"{len(bills):,} retained source-context bills; "
            f"{int(bills['sponsor_party'].isin(['D', 'R']).sum()):,} carry D/R attribution. "
            "Historical attribution, filing-time eligibility and topic accuracy remain unverified."
        )
        tagged = bills["subject"].fillna("").str.strip().ne("")
        tag_evidence = f"{int(tagged.sum()):,} bills carry nonempty source subject tags."
        tag_coverage = state_coverage(bills.loc[tagged])
        if "originating_chamber" in bills:
            chamber_coverage = state_coverage(bills.loc[
                bills["originating_chamber"].isin(["upper", "lower", "legislature"])
            ])
    if bill_coverage is not None:
        test_exclusions = (
            f" and {int(bill_coverage['n_source_test_excluded'].sum()):,} source-test exclusions"
            if "n_source_test_excluded" in bill_coverage.columns else ""
        )
        draft_exclusions = (
            f" and {int(bill_coverage['n_source_draft_excluded'].sum()):,} source-draft exclusions"
            if "n_source_draft_excluded" in bill_coverage.columns else ""
        )
        bill_evidence += (
            f" Legacy classifier coverage reports {int(bill_coverage['n_attributed'].sum()):,} "
            f"attributed rows and {int(bill_coverage['n_procedural_excluded'].sum()):,} "
            f"procedural exclusions{test_exclusions}{draft_exclusions}; "
            "these are not reconciled or certified denominators."
        )
    actions_path = data_dir / "bill_actions.parquet"
    votes_path = data_dir / "vote_events.parquet"
    vote_parties_path = data_dir / "vote_party_counts.parquet"
    action_evidence = (
        f"{pq.ParquetFile(actions_path).metadata.num_rows:,} retained source action rows."
        if actions_path.exists() else "Source action artifact not retained."
    )
    if outcomes is not None:
        action_evidence += (
            f" {len(outcomes):,} legacy state-party outcome rows; the 500-bill/80%-coverage "
            "heuristic does not certify outcome semantics, party timing or comparability."
        )
    vote_evidence = (
        f"{pq.ParquetFile(votes_path).metadata.num_rows:,} retained source vote events."
        if votes_path.exists() else "Source vote-event artifact not retained."
    )
    if vote_parties_path.exists():
        vote_evidence += (
            f" {pq.ParquetFile(vote_parties_path).metadata.num_rows:,} retained party-count "
            "rows, including unresolved parties; not a count of resolved person-votes."
        )
    rows = [
        {
            "question": "Current stated state-level agenda",
            "artifacts": ("platforms_2018_present.parquet", "caucus_priorities.parquet"),
            "coverage": "operative coverage unresolved",
            "evidence": (
                f"{source_evidence} "
                "Content confirmation verifies neither adoption, operative version, "
                "analytical cutoff nor topic accuracy"
            ),
        },
        {
            "question": "Reliable within-party stated comparison",
            "artifacts": ("state_party_focus.csv", "platforms_2018_present.parquet"),
            "coverage": "comparison validity unresolved",
            "evidence": (
                (
                    f"{int(atlas['stated_focus_reliable'].sum())}/100 state-party rows pass "
                    "the legacy 30-unit heuristic."
                    if atlas is not None else "Legacy state-party atlas not retained."
                ) + " Sample size alone does not validate "
                "classification, source versions or within-party comparability"
            ),
        },
        {
            "question": "Introduced-bill agenda by party and state",
            "artifacts": ("bills.parquet", "bill_classification_coverage.csv"),
            "coverage": state_coverage(bills),
            "evidence": bill_evidence + " Nebraska is formally nonpartisan.",
        },
        {
            "question": "Election and voting bill focus",
            "artifacts": ("election_focus_by_state_party.csv", "bills.parquet"),
            "coverage": state_coverage(elections),
            "evidence": (
                (
                    f"{int(elections['n_election_bills'].sum()):,} legacy detector candidates."
                    if elections is not None else "Election-detector output not retained."
                ) + " Detections are not verified substantive election measures; eligibility "
                "and historical party comparisons remain unresolved."
            ),
        },
        {
            "question": "Legislative-staff tag validation",
            "artifacts": ("bills.parquet",),
            "coverage": tag_coverage,
            "evidence": tag_evidence + " Source tags are not independently verified staff "
            "gold, classifier accuracy or a representative validation sample.",
        },
        {
            "question": "Party-topic bill trends over time",
            "artifacts": ("bill_topic_trends_by_party.csv", "bills.parquet"),
            "coverage": "legacy configured 2018-2025 window; analytical cutoff unresolved",
            "evidence": (
                (
                    f"{len(trends):,} retained legacy trend rows."
                    if trends is not None else "Legacy topic-trend output not retained."
                ) + " Equal-state changes, sign-flip tests and BH q-values do not validate "
                "source coverage, historical party timing, topics or changing missingness."
            ),
        },
        {
            "question": "Bill enactment/pass rates",
            "artifacts": (
                "bills.parquet", "bill_actions.parquet", "bill_outcomes_by_state_party.csv",
            ),
            "coverage": state_coverage(outcomes),
            "evidence": action_evidence + " Recorded stages are not certified enactment "
            "rates or evidence that missing actions mean legislative failure.",
        },
        {
            "question": "Roll-call voting behavior",
            "artifacts": ("vote_events.parquet", "vote_party_counts.parquet"),
            "coverage": "party-at-vote and motion comparability unresolved",
            "evidence": vote_evidence + " Presence does not establish dated voter-party "
            "resolution, motion equivalence or a complete roll-call universe.",
        },
        {
            "question": "Chamber-specific historical agenda",
            "artifacts": ("bills.parquet", "bill_classification_coverage.csv"),
            "coverage": chamber_coverage,
            "evidence": (
                "Recognized originating-chamber values describe organizational availability, "
                "not historically attributed, filing-time-eligible or validated topic agendas."
            ),
        },
        {
            "question": "Policy stance or ideological direction",
            "artifacts": ("bills.parquet", "vote_events.parquet", "vote_party_counts.parquet"),
            "coverage": "stance/ideology validation not performed",
            "evidence": (
                "Topic attention does not encode stance. Recorded yes/no votes concern "
                "specific motions, not a validated ideology score or every bill's direction."
            ),
        },
        {
            "question": "Current party-committee platform coverage",
            "artifacts": ("platforms_2018_present.parquet",),
            "coverage": "operative coverage unresolved",
            "evidence": (
                f"{organization_evidence} "
                "These overlapping availability counts establish neither operative "
                "coverage nor publication absence"
            ),
        },
    ]
    for row in rows:
        artifacts = row.pop("artifacts")
        missing = [name for name in artifacts if not (data_dir / name).exists()]
        row.update({
            "support": "unsupported",
            "artifact_status": (
                "missing" if len(missing) == len(artifacts)
                else "partial" if missing else "available"
            ),
            "missing_artifacts": "; ".join(missing),
            "scientific_certification": "not_performed",
            "analysis_cutoff": None,
        })
        if missing:
            row["evidence"] += " Missing retained inputs: " + "; ".join(missing) + "."
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
        json.dumps(report.to_dict(orient="records"), indent=2, allow_nan=False), encoding="utf-8"
    )
    report.to_csv(out.with_suffix(".csv"), index=False)
    print(report.to_string(index=False))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

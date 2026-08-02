#!/usr/bin/env python3
"""Print the canonical figures for this project, computed from the committed artifacts.

Every number quoted in the README or in a figure caption should be reproducible from here.
The counts in this project have drifted more than once as the pipeline was corrected, so this
exists to make "check the docs against the data" a single command rather than an archaeology
exercise.

Usage::

    python scripts/report_figures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"


def _load(name: str):
    path = DATA / name
    if not path.exists():
        return None
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)


def _parquet_rows(name: str) -> int | None:
    import pyarrow.parquet as pq

    path = DATA / name
    return pq.ParquetFile(path).metadata.num_rows if path.exists() else None


def main() -> int:
    print("=" * 72)
    print("CANONICAL FIGURES  (recompute before quoting any number in the docs)")
    print("=" * 72)

    historical = _load("platforms_historical.parquet")
    if historical is not None:
        major = historical[historical["is_major_party"]]
        print("\nHistorical platform corpus (Dataverse)")
        print(f"  documents            {len(historical):,}")
        span = f"{int(historical['year'].min())}-{int(historical['year'].max())}"
        states = historical.loc[historical["state"] != "US", "state"].nunique()
        print(f"  years                {span}")
        print(f"  states (excl. US)    {states}")
        print(f"  D / R                {int((major['party_raw'] == 'D').sum()):,} / "
              f"{int((major['party_raw'] == 'R').sum()):,}")

    modern = _load("platforms_2018_present.parquet")
    if modern is not None:
        ok = modern[modern["confirmed"]]
        print("\nModern platform corpus (collected by this project)")
        print(f"  documents            {len(ok):,}")
        print(f"  organizations        {ok.groupby(['state', 'party']).ngroups}/100")
        print(f"  states               {ok['state'].nunique()}")
        dem, rep = int((ok["party"] == "D").sum()), int((ok["party"] == "R").sum())
        print(f"  D / R                {dem} / {rep}")
        print(f"  words                {int(ok['n_words'].sum()):,}")
        print(f"  dated 2018+          {int((ok['year'] >= 2018).sum())} of {len(ok)}")

    gaps = _load("platform_gap_report.csv")
    if gaps is not None:
        print("\nGap report")
        for status, count in gaps["status"].value_counts().items():
            print(f"  {status:<22} {count}")
        missing = gaps[gaps["n_confirmed"] == 0]
        explained = int((missing.get("gap_finding", pd.Series(dtype=str)).fillna("") != "").sum())
        print(f"  gaps with a finding    {explained}/{len(missing)}")
        if "gap_cause" in missing:
            for cause, count in missing["gap_cause"].value_counts().items():
                print(f"    {cause:<20} {count}")

    caucus = _load("caucus_priorities.parquet")
    if caucus is not None and not caucus.empty:
        platform_states = set(ok["state"]) if modern is not None else set()
        caucus_states = set(caucus["state"])
        print("\nSupplemental caucus priority sources")
        print(f"  sources              {len(caucus)}")
        print(f"  states               {', '.join(sorted(caucus_states))}")
        print(f"  words                {int(caucus['n_words'].sum()):,}")
        print(f"  stated agenda coverage {len(platform_states | caucus_states)}/50 states")
        print("  note                 caucus sources are separate from party platforms")

    planks = _load("planks_classified.parquet")
    if planks is not None:
        classified = int(planks["topic"].notna().sum())
        print("\nPlank classification")
        print(f"  planks               {len(planks):,}")
        below = len(planks) - classified
        print(f"  classified           {classified:,} ({below:,} below threshold)")
        print(f"  documents            {planks['document_index'].nunique():,}")
        if "era" in planks:
            for era, count in planks["era"].value_counts().items():
                print(f"    {era:<18} {count:,}")

    scores = _load("plank_classifier_scores.csv")
    if scores is not None and "embedding_topic" in scores:
        n = len(scores)
        top1 = int((scores["embedding_topic"] == scores["gold_topic"]).sum())
        top2 = (
            int(scores["embedding_top2_correct"].sum())
            if "embedding_top2_correct" in scores
            else None
        )
        key = int((scores["keyword_topic"] == scores["gold_topic"]).sum())
        print("\nClassifier validation (hand-labelled gold set)")
        print(f"  gold planks          {n}")
        print(f"  embedding top-1      {top1}/{n} ({top1 / n:.0%})")
        if top2 is not None:
            print(f"  embedding top-2      {top2}/{n} ({top2 / n:.0%})")
        print(f"  keyword top-1        {key}/{n} ({key / n:.0%})")

    legislators = _load("legislators_current.parquet")
    if legislators is not None:
        print("\nLegislators")
        print(f"  legislators          {len(legislators):,}")
        print(f"  states               {legislators['state'].nunique()}/50")
        print(f"  by party             {legislators['party'].value_counts().to_dict()}")

    bills = _load("bills.parquet")
    if bills is not None:
        print("\nBills")
        print(f"  bills                {len(bills):,}")
        print(f"  states               {bills['state'].nunique()}/50")
        print(f"  years                {int(bills['year'].min())}-{int(bills['year'].max())}")
        print(f"  attribution          {bills['sponsor_party'].value_counts().to_dict()}")

    bill_coverage = _load("bill_classification_coverage.csv")
    if bill_coverage is not None:
        print(
            f"  classified into topics "
            f"{int(bill_coverage['n_classified_total'].sum()):,}"
        )

    outcomes = _load("bill_outcomes_by_party.csv")
    comparison_path = DATA / "bill_outcome_comparison.json"
    rollcalls = _load("rollcall_party_support.csv")
    if outcomes is not None and comparison_path.exists():
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        print("\nRecorded bill outcomes")
        print(f"  explicit actions     {_parquet_rows('bill_actions.parquet'):,}")
        print(f"  vote events          {_parquet_rows('vote_events.parquet'):,}")
        for row in outcomes.itertuples():
            print(
                f"  {row.party} equal-state      advanced {row.mean_advancement_rate:.1%}; "
                f"enacted {row.mean_enactment_rate:.1%} "
                f"({int(row.n_states)} reliable states)"
            )
        print(
            f"  D-R enactment gap    "
            f"{comparison['mean_d_minus_r_enactment_rate']:+.1%}, "
            f"p={comparison['sign_flip_p_value']:.3f} "
            f"({comparison['n_paired_states']} paired states)"
        )
        if rollcalls is not None:
            for row in rollcalls.itertuples():
                print(
                    f"  {row.sponsor_party}-sponsored / {row.voter_party} voters "
                    f"yes {row.mean_yes_share:.1%} "
                    f"({int(row.n_vote_events):,} votes)"
                )

    divergence = _load("stated_vs_revealed.csv")
    if divergence is not None:
        print("\nStated vs revealed (headline)")
        for topic in ("Civil rights and liberties", "Immigration", "Law, crime and justice",
                      "Housing and community development"):
            for party in ("D", "R"):
                row = divergence[(divergence["topic_name"] == topic)
                                 & (divergence["party"] == party)]
                if len(row) == 1:
                    row = row.iloc[0]
                    print(f"  {party} {topic:<34} said {row['stated_share'] * 100:5.1f}%  "
                          f"filed {row['revealed_share'] * 100:5.1f}%")

    reuse = _load("text_reuse_near_duplicates.csv")
    if reuse is not None and not reuse.empty:
        print("\nText reuse (model legislation)")
        print(f"  clusters             {len(reuse):,}")
        print(f"  bills in clusters    {int(reuse['n_bills'].sum()):,}")
        print(f"  widest cluster       {int(reuse['n_states'].max())} states")
        if "min_similarity" in reuse:
            loose = int((reuse["min_similarity"] < 0.8).sum())
            print(f"  cohesion             {reuse['min_similarity'].min():.2f}-"
                  f"{reuse['min_similarity'].max():.2f} "
                  f"(median {reuse['min_similarity'].median():.2f})")
            print(f"  below threshold      {loose} of {len(reuse)} clusters "
                  f"contain a sub-threshold pair")
        if "ceremonial" in reuse:
            print(f"  ceremonial           {int(reuse['ceremonial'].sum())} "
                  f"({int((~reuse['ceremonial']).sum())} substantive)")

    tags = _load("bill_tag_agreement.csv")
    if tags is not None and not tags.empty:
        total, agreed = int(tags["n"].sum()), int(tags["agreed"].sum())
        print("\nBill classifier vs statehouse subject tags")
        print(f"  scored               {total:,}")
        print(f"  overall agreement    {100 * agreed / total:.1f}%")
        worst = tags.nsmallest(3, "precision")
        for _, row in worst.iterrows():
            print(f"  lowest precision     {row['topic_name']:<38} "
                  f"{row['precision'] * 100:.1f}%")

    replication = _load("headline_tag_replication.csv")
    if replication is not None:
        holds = replication["holds"].fillna(False).astype(bool)
        print(f"  headline rows replicated {int(holds.sum())}/{len(replication)} "
              "using tag labels instead of the model")
        for _, row in replication[~holds].iterrows():
            print(f"    does not hold      {row['topic_name']} ({row['party']}): "
                  f"said {row['stated_share'] * 100:.1f}%, "
                  f"model {row['model_share'] * 100:.1f}%, "
                  f"tags {row['tag_share'] * 100:.1f}%")

    print("\nIntra-party comparison (within vs between party)")
    for stream in ("platform", "bill"):
        blocs = _load(f"intraparty_{stream}_coherence.csv")
        if blocs is None or blocs.empty:
            continue
        row = blocs.iloc[0]
        print(f"  {stream:<9} within {row['mean_within']:.3f}  between {row['between']:.3f}  "
              f"ratio {row['within_over_between']:.2f}  ({int(row['n_states'])} states)")
    tests = _load("intraparty_dispersion_tests.csv")
    if tests is not None and not tests.empty:
        for _, row in tests.iterrows():
            verdict = "significant" if row["p_value"] < 0.05 else "not distinguishable from chance"
            print(f"  {row['stream']:<9} D-R dispersion gap {row['observed_gap']:+.3f}, "
                  f"p={row['p_value']:.3f} ({verdict})")

    focus = _load("state_party_focus.csv")
    if focus is not None and not focus.empty:
        print("\nWithin-party state focus atlas")
        print(f"  profiles             {len(focus)}/100")
        print(f"  stated evidence      {int((focus['stated_source'] != 'none').sum())}/100")
        print(f"  stated comparisons   {int(focus['stated_focus_reliable'].sum())}/100")
        print(f"  bill evidence        {int(focus['bill_n_items'].notna().sum())}/100")
        for party in ("D", "R"):
            top = focus[
                (focus["party"] == party) & focus["bill_focus_reliable"].fillna(False)
            ].nlargest(3, "bill_cosine_distance")
            for row in top.itertuples():
                print(f"    {party} {row.state}: {row.bill_focus_topic} "
                      f"{row.bill_focus_share:.1%} vs {row.bill_peer_share:.1%} peers")

    elections = _load("election_focus_by_state_party.csv")
    validation_path = DATA / "election_title_validation.json"
    if elections is not None and validation_path.exists():
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        print("\nElection and voting bills")
        print(f"  election bills       {int(elections['n_election_bills'].sum()):,}")
        print(f"  detector validation  {validation['precision']:.1%} precision, "
              f"{validation['recall']:.1%} recall")
        for party in ("D", "R"):
            block = elections[elections["party"] == party]
            share = block["n_election_bills"].sum() / block["n_bills"].sum()
            top = block[block["focus_reliable"]].nlargest(1, "overemphasis").iloc[0]
            print(f"  {party} pooled share       {share:.2%}; highest {top['state']} "
                  f"{top['election_share']:.1%} vs {top['peer_share']:.1%} peers")

    terms = _load("state_party_terms.csv")
    if terms is not None:
        print("\nTF-IDF and log2 concentration")
        print(f"  reported term rows   {len(terms):,}")
        print("  interpretation       +1 log2 = 2x peer concentration; +2 = 4x")

    registry_path = ROOT / "conf" / "party_registry.yml"
    if registry_path.exists():
        orgs = yaml.safe_load(registry_path.read_text(encoding="utf-8"))["organizations"]
        print("\nParty registry")
        print(f"  organizations        {len(orgs)}")
        print(f"  websites resolved    {sum(1 for o in orgs if o['website'])}/{len(orgs)}")
        print(f"  machine-verified     {sum(1 for o in orgs if not o['needs_review'])}/{len(orgs)}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

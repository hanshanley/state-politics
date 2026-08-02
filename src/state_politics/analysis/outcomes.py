"""Recorded advancement, enactment, chamber, and roll-call analysis.

This module answers questions the filing-only pipeline deliberately could not. It uses explicit
Open States action classifications and vote records; missing actions remain missing and are
reported through state coverage floors rather than interpreted as failure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MIN_OUTCOME_BILLS = 500
MIN_ACTION_COVERAGE = 0.80
MIN_ROLLCALL_VOTERS = 10
OUTCOME_PERMUTATIONS = 10_000
OUTCOME_RANDOM_SEED = 20_260_801

__all__ = [
    "build_outcome_tables",
    "is_law_eligible",
    "party_rollcall_support",
]


def is_law_eligible(classification: str | None) -> bool:
    """True for ordinary bills, excluding resolutions and constitutional amendments."""
    values = {
        value.strip().lower()
        for value in str(classification or "").split("|")
        if value.strip()
    }
    return "bill" in values and not any(
        "resolution" in value or "constitutional" in value for value in values
    )


def _sign_flip_p_value(differences) -> float:
    import numpy as np

    values = np.asarray(differences, dtype=float)
    if len(values) < 2:
        return 1.0
    rng = np.random.default_rng(OUTCOME_RANDOM_SEED)
    signs = rng.choice((-1, 1), size=(OUTCOME_PERMUTATIONS, len(values)))
    observed = abs(float(values.mean()))
    permuted = abs((signs * values).mean(axis=1))
    return float(
        (1 + np.count_nonzero(permuted >= observed)) / (OUTCOME_PERMUTATIONS + 1)
    )


def build_outcome_tables(bills):
    """State and party summaries for explicitly recorded bill outcomes."""
    frame = bills[
        bills["sponsor_party"].isin(("D", "R"))
        & bills["year"].ge(2018)
        & bills["classification"].map(is_law_eligible)
    ].copy()
    frame["has_action_data"] = frame["n_actions"].fillna(0).gt(0)
    frame["advanced"] = frame["recorded_outcome"].isin(
        {
            "passed_one_chamber",
            "passed_legislature",
            "sent_to_executive",
            "signed",
            "vetoed",
            "became_law",
        }
    )
    if "recorded_enacted" in frame:
        frame["enacted"] = frame["recorded_enacted"].fillna(False)
    else:
        frame["enacted"] = frame["recorded_outcome"].isin({"signed", "became_law"})
    state = (
        frame.groupby(["state", "sponsor_party"])
        .agg(
            n_bills=("bill_id", "size"),
            n_with_actions=("has_action_data", "sum"),
            n_advanced=("advanced", "sum"),
            n_enacted=("enacted", "sum"),
            n_with_votes=("n_vote_events", lambda values: values.fillna(0).gt(0).sum()),
        )
        .reset_index()
        .rename(columns={"sponsor_party": "party"})
    )
    state["action_coverage"] = state["n_with_actions"] / state["n_bills"]
    state["advancement_rate"] = state["n_advanced"] / state["n_bills"]
    state["enactment_rate"] = state["n_enacted"] / state["n_bills"]
    state["vote_coverage"] = state["n_with_votes"] / state["n_bills"]
    state["reliable"] = (
        state["n_bills"].ge(MIN_OUTCOME_BILLS)
        & state["action_coverage"].ge(MIN_ACTION_COVERAGE)
    )

    reliable = state[state["reliable"]]
    reliable_state_sets = {
        party_code: set(reliable.loc[reliable["party"] == party_code, "state"])
        for party_code in ("D", "R")
    }
    paired_states = reliable_state_sets["D"] & reliable_state_sets["R"]
    matched = reliable[reliable["state"].isin(paired_states)]
    party = (
        matched.groupby("party")
        .agg(
            n_states=("state", "nunique"),
            mean_action_coverage=("action_coverage", "mean"),
            mean_advancement_rate=("advancement_rate", "mean"),
            mean_enactment_rate=("enactment_rate", "mean"),
            mean_vote_coverage=("vote_coverage", "mean"),
        )
        .reset_index()
    )
    paired = matched.pivot(
        index="state",
        columns="party",
        values="enactment_rate",
    ).dropna()
    differences = paired["D"] - paired["R"] if {"D", "R"} <= set(paired.columns) else []
    comparison = {
        "n_paired_states": len(paired),
        "mean_d_minus_r_enactment_rate": (
            float(differences.mean()) if len(paired) else None
        ),
        "sign_flip_p_value": _sign_flip_p_value(differences),
        "minimum_bills": MIN_OUTCOME_BILLS,
        "minimum_action_coverage": MIN_ACTION_COVERAGE,
    }

    chamber = (
        frame.groupby(["originating_chamber", "sponsor_party"])
        .agg(
            n_bills=("bill_id", "size"),
            action_coverage=("has_action_data", "mean"),
            advancement_rate=("advanced", "mean"),
            enactment_rate=("enacted", "mean"),
        )
        .reset_index()
        .rename(columns={"sponsor_party": "party"})
    )
    return state, party, chamber, comparison


def party_rollcall_support(vote_events, party_counts):
    """Same/opposite-party yes shares on recorded passage roll calls."""
    import pandas as pd

    passage = vote_events[
        vote_events["motion_classification"].fillna("").str.split("|").map(
            lambda values: "passage" in values
        )
    ][["vote_id", "bill_id", "state", "result", "chamber"]]
    votes = party_counts[
        party_counts["sponsor_party"].isin(("D", "R"))
        & party_counts["voter_party"].isin(("D", "R"))
        & party_counts["option"].isin(("yes", "no"))
    ].merge(
        passage,
        left_on=["vote_event_id", "bill_id", "state"],
        right_on=["vote_id", "bill_id", "state"],
        how="inner",
        validate="many_to_one",
    )
    if votes.empty:
        return pd.DataFrame(
            columns=[
                "sponsor_party",
                "voter_party",
                "n_vote_events",
                "n_person_votes",
                "mean_yes_share",
            ]
        )
    per_vote = (
        votes.groupby(
            [
                "vote_event_id",
                "sponsor_party",
                "voter_party",
                "state",
                "chamber",
                "result",
            ]
        )
        .apply(
            lambda group: pd.Series(
                {
                    "n_person_votes": int(group["n_votes"].sum()),
                    "yes_share": (
                        group.loc[group["option"] == "yes", "n_votes"].sum()
                        / group["n_votes"].sum()
                    ),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    per_vote = per_vote[per_vote["n_person_votes"] >= MIN_ROLLCALL_VOTERS]
    expected_pairs = {("D", "D"), ("D", "R"), ("R", "D"), ("R", "R")}
    observed_pairs = set(
        map(
            tuple,
            per_vote[["sponsor_party", "voter_party"]].drop_duplicates().values,
        )
    )
    if expected_pairs <= observed_pairs:
        state_sets = [
            set(
                per_vote.loc[
                    per_vote["sponsor_party"].eq(sponsor)
                    & per_vote["voter_party"].eq(voter),
                    "state",
                ]
            )
            for sponsor, voter in sorted(expected_pairs)
        ]
        common_states = set.intersection(*state_sets)
        per_vote = per_vote[per_vote["state"].isin(common_states)]
    return (
        per_vote.groupby(["sponsor_party", "voter_party"])
        .agg(
            n_vote_events=("vote_event_id", "nunique"),
            n_states=("state", "nunique"),
            n_person_votes=("n_person_votes", "sum"),
            mean_yes_share=("yes_share", "mean"),
        )
        .reset_index()
    )


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bills", default=root / "data/processed/bills.parquet")
    parser.add_argument(
        "--vote-events",
        default=root / "data/processed/vote_events.parquet",
    )
    parser.add_argument(
        "--vote-party-counts",
        default=root / "data/processed/vote_party_counts.parquet",
    )
    parser.add_argument("--out-dir", default=root / "data/processed")
    args = parser.parse_args(argv)

    bills = pd.read_parquet(args.bills)
    state, party, chamber, comparison = build_outcome_tables(bills)
    votes = party_rollcall_support(
        pd.read_parquet(args.vote_events),
        pd.read_parquet(args.vote_party_counts),
    )
    out = Path(args.out_dir)
    state.to_csv(out / "bill_outcomes_by_state_party.csv", index=False)
    party.to_csv(out / "bill_outcomes_by_party.csv", index=False)
    chamber.to_csv(out / "bill_outcomes_by_chamber_party.csv", index=False)
    votes.to_csv(out / "rollcall_party_support.csv", index=False)
    (out / "bill_outcome_comparison.json").write_text(
        json.dumps(comparison, indent=2),
        encoding="utf-8",
    )

    print("recorded law-eligible bill outcomes (equal-state means):")
    print(party.to_string(index=False))
    print(f"\npaired-state comparison: {comparison}")
    print("\nrecorded passage roll-call support:")
    print(votes.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

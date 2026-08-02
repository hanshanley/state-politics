"""Tests for action/chamber/roll-call outcome extraction."""

from __future__ import annotations

import pandas as pd

from state_politics.analysis.outcomes import (
    build_outcome_tables,
    is_law_eligible,
    party_rollcall_support,
)
from state_politics.bills.outcomes import (
    organization_chamber,
    party_on_date,
    recorded_outcome,
)


def test_committee_resolves_to_parent_chamber():
    organizations = {
        "senate": {
            "classification": "upper",
            "parent_id": "legislature",
        },
        "committee": {
            "classification": "committee",
            "parent_id": "senate",
        },
    }

    assert organization_chamber("committee", organizations) == "upper"
    assert organization_chamber("missing", organizations) == "unknown"


def test_party_membership_resolves_at_vote_date():
    intervals = [
        ("2018-01-01", "2022-12-31", "D"),
        ("2023-01-01", "", "R"),
    ]

    assert party_on_date(intervals, "2020-05-01") == "D"
    assert party_on_date(intervals, "2025-05-01") == "R"
    assert party_on_date(None, "2025-05-01") == "unknown"


def test_recorded_outcome_uses_highest_explicit_action_stage():
    assert recorded_outcome({"introduction"}, set()) == "introduced_or_pending"
    assert recorded_outcome({"passage"}, {"upper"}) == "passed_one_chamber"
    assert recorded_outcome({"passage"}, {"upper", "lower"}) == "passed_legislature"
    assert recorded_outcome({"executive-veto"}, {"upper", "lower"}) == "vetoed"
    assert recorded_outcome({"became-law"}, {"upper", "lower"}) == "became_law"


def test_law_eligible_excludes_resolutions():
    assert is_law_eligible("bill")
    assert not is_law_eligible("resolution")
    assert not is_law_eligible("bill|joint resolution")


def test_outcome_tables_use_recorded_actions_and_reliability_floor():
    rows = []
    for state in ("TX", "VT"):
        for party in ("D", "R"):
            for index in range(500):
                became_law = index < (100 if party == "D" else 50)
                rows.append(
                    {
                        "bill_id": f"{state}-{party}-{index}",
                        "state": state,
                        "sponsor_party": party,
                        "year": 2024,
                        "classification": "bill",
                        "n_actions": 1,
                        "recorded_outcome": (
                            "became_law" if became_law else "introduced_or_pending"
                        ),
                        "recorded_enacted": became_law,
                        "n_vote_events": 0,
                        "originating_chamber": "lower",
                    }
                )

    state, party, chamber, comparison = build_outcome_tables(pd.DataFrame(rows))

    assert state["reliable"].all()
    assert party.set_index("party").loc["D", "mean_enactment_rate"] == 0.2
    assert party.set_index("party").loc["R", "mean_enactment_rate"] == 0.1
    assert comparison["n_paired_states"] == 2
    assert set(chamber["originating_chamber"]) == {"lower"}


def test_rollcall_support_separates_sponsor_and_voter_party():
    events = pd.DataFrame(
        [
            {
                "vote_id": "v1",
                "bill_id": "b1",
                "state": "TX",
                "result": "pass",
                "chamber": "lower",
                "motion_classification": "passage",
            }
        ]
    )
    counts = pd.DataFrame(
        [
            {
                "vote_event_id": "v1", "bill_id": "b1", "state": "TX",
                "sponsor_party": "D", "voter_party": "D", "option": "yes",
                "n_votes": 20,
            },
            {
                "vote_event_id": "v1", "bill_id": "b1", "state": "TX",
                "sponsor_party": "D", "voter_party": "R", "option": "yes",
                "n_votes": 5,
            },
            {
                "vote_event_id": "v1", "bill_id": "b1", "state": "TX",
                "sponsor_party": "D", "voter_party": "R", "option": "no",
                "n_votes": 15,
            },
        ]
    )

    result = party_rollcall_support(events, counts).set_index(
        ["sponsor_party", "voter_party"]
    )

    assert result.loc[("D", "D"), "mean_yes_share"] == 1.0
    assert result.loc[("D", "R"), "mean_yes_share"] == 0.25

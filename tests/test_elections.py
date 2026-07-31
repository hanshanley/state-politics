"""Tests for the dedicated election- and voting-bill lens."""

from __future__ import annotations

import pandas as pd

from state_politics.analysis.elections import (
    election_focus,
    election_subtype,
    validate_title_rule,
)


def test_election_subtypes_are_specific():
    assert election_subtype("An act concerning voter registration and absentee voting") == (
        "voting_and_administration"
    )
    assert election_subtype("Campaign finance disclosure requirements") == "campaign_finance"
    assert election_subtype("Legislative redistricting plan") == "redistricting"
    assert election_subtype("Election fraud penalties") == "election_security"
    assert election_subtype("Primary election candidate filing") == "candidates_and_parties"


def test_election_rule_does_not_match_electrical_or_elected_officials():
    assert election_subtype("Electrical contractor licensing") is None
    assert election_subtype("Compensation of elected officials") is None


def test_focus_uses_leave_one_state_out_party_baseline():
    frame = pd.DataFrame(
        [
            {
                "state": "TX", "sponsor_party": "D",
                "title": "Election administration", "subject": "",
            },
            {"state": "TX", "sponsor_party": "D", "title": "Voter registration", "subject": ""},
            {"state": "OH", "sponsor_party": "D", "title": "School funding", "subject": ""},
            {"state": "OH", "sponsor_party": "D", "title": "Health care", "subject": ""},
            {"state": "VT", "sponsor_party": "D", "title": "Ballot access", "subject": ""},
            {"state": "VT", "sponsor_party": "D", "title": "Housing", "subject": ""},
        ]
    )
    focus, _, _ = election_focus(frame)
    texas = focus.set_index("state").loc["TX"]

    assert texas["election_share"] == 1.0
    assert texas["peer_share"] == 0.25
    assert texas["overemphasis"] == 0.75


def test_subject_validation_is_independent_of_cross_state_share():
    frame = pd.DataFrame(
        [
            {
                "title": "Voter registration", "subject": "Elections",
                "election_subtype": "voting_and_administration",
            },
            {
                "title": "Ballot access", "subject": "Education",
                "election_subtype": "voting_and_administration",
            },
            {
                "title": "Election law", "subject": "Elections",
                "election_subtype": None,
            },
        ]
    )
    scores = validate_title_rule(frame)

    assert scores["precision"] == 0.5
    assert scores["recall"] == 0.5

"""Tests for the dedicated election- and voting-bill lens."""

from __future__ import annotations

import pandas as pd
import pytest

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


def test_draft_requests_do_not_change_election_shares_or_tag_validation():
    source = pd.DataFrame({
        "state": ["MT", "MT", "MT", "OH"],
        "identifier": ["LC 442", "SB 6", "HB 117", "HB 1"],
        "title": [
            "Election administration", "School funding", "Election administration", "Housing",
        ],
        "subject": ["Elections", "", "Elections", ""],
        "classification": ["bill"] * 4, "sponsor_party": ["R"] * 4,
    })
    focus, _, validation = election_focus(source)
    montana = focus.set_index("state").loc["MT"]
    assert montana["n_bills"] == 2 and montana["n_election_bills"] == 1
    assert montana["election_share"] == 0.5
    assert validation["n_tagged_bills"] == 1


@pytest.mark.parametrize(
    ("subject", "subtype", "precision", "recall"),
    [
        ("", "voting_and_administration", None, None),
        ("Education", "voting_and_administration", 0.0, None),
        ("Elections", None, None, 0.0),
    ],
)
def test_tag_comparison_distinguishes_undefined_metrics_from_observed_zero(
    subject, subtype, precision, recall,
):
    scores = validate_title_rule(pd.DataFrame({
        "subject": [subject], "election_subtype": [subtype],
    }))

    assert scores["precision"] == precision
    assert scores["recall"] == recall


def test_single_state_cannot_have_a_reliable_peer_comparison():
    frame = pd.DataFrame({
        "state": ["TX"] * 500, "sponsor_party": ["D"] * 500,
        "title": ["Election administration"] * 500, "subject": ["Elections"] * 500,
    })
    focus, _, _ = election_focus(frame)
    row = focus.iloc[0]

    assert row["n_bills"] == 500
    assert row["election_share"] == 1.0
    assert pd.isna(row["peer_share"]) and pd.isna(row["overemphasis"])
    assert not row["focus_reliable"]


@pytest.mark.parametrize("population", ["empty", "no_major_party", "resolutions_only"])
def test_election_cli_exports_empty_coverage(tmp_path, capsys, population):
    import json

    from state_politics.analysis.elections import main

    frame = pd.DataFrame({
        "state": ["TX"], "identifier": ["HB 1"], "sponsor_party": ["D"],
        "title": ["Election administration"], "subject": ["Elections"],
        "classification": ["bill"],
    })
    if population == "empty":
        frame = frame.iloc[:0]
    elif population == "no_major_party":
        frame["sponsor_party"] = None
    else:
        frame["classification"] = "resolution"
    source = tmp_path / "bills.parquet"
    frame.to_parquet(source, index=False)
    out = tmp_path / "exports"

    assert main(["--bills", str(source), "--out-dir", str(out)]) == 0
    focus = pd.read_csv(out / "election_focus_by_state_party.csv")
    subtypes = pd.read_csv(out / "election_focus_subtypes.csv")
    validation = json.loads((out / "election_title_validation.json").read_text())
    assert focus.empty and subtypes.empty
    assert {"state", "party", "n_bills", "n_election_bills", "focus_reliable"} <= set(focus)
    assert validation["n_tagged_bills"] == 0
    assert validation["precision"] is None and validation["recall"] is None
    assert "unavailable" in capsys.readouterr().out.lower()

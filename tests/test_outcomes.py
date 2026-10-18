"""Tests for action/chamber/roll-call outcome extraction."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from state_politics.analysis.outcomes import (
    build_outcome_tables,
    is_law_eligible,
    party_rollcall_support,
)
from state_politics.bills.outcomes import (
    main as repair_outcomes,
)
from state_politics.bills.outcomes import (
    organization_chamber,
    party_on_date,
    recorded_outcome,
)
from state_politics.provenance import sha256_file


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


def test_party_membership_never_uses_expired_future_or_conflicting_affiliations():
    intervals = [("2020-01-01", "2020-12-31", "D"), ("2022-01-01", "", "R")]
    assert party_on_date(intervals, "2019-01-01") == "unknown"
    assert party_on_date(intervals, "2021-06-01") == "unknown"
    assert party_on_date(intervals, None) == "unknown"
    assert party_on_date(intervals, "2020") == "unknown"
    assert party_on_date([("", "", "D"), ("", "", "R")], "2024-01-01") == "unknown"


@pytest.mark.parametrize("interval", [
    ("2020", "", "D"), ("2020-01", "", "D"), ("", "", "D"),
    ("2020-13-01", "", "D"), ("2024-01-01", "2023-01-01", "D"),
])
def test_party_membership_does_not_guess_missing_partial_or_malformed_bounds(interval):
    assert party_on_date([interval], "2024-06-01") == "unknown"


def test_recorded_outcome_uses_highest_explicit_action_stage():
    assert recorded_outcome({"introduction"}, set(), n_actions=1) == "introduced_or_pending"
    assert recorded_outcome({"passage"}, {"upper"}, n_actions=1) == "passed_one_chamber"
    assert recorded_outcome({"passage"}, {"upper", "lower"}, n_actions=2) == "passed_legislature"
    assert recorded_outcome({"executive-veto"}, {"upper", "lower"}, n_actions=3) == "vetoed"
    assert recorded_outcome({"became-law"}, {"upper", "lower"}, n_actions=3) == "became_law"


def test_unclassified_actions_are_not_missing_or_assumed_pending():
    assert recorded_outcome(set(), set(), n_actions=0) == "no_action_data"
    assert recorded_outcome(set(), set(), n_actions=2) == "action_stage_unclassified"
    with pytest.raises(ValueError, match="contradict"):
        recorded_outcome({"introduction"}, set(), n_actions=0)


def _outcome_source(tmp_path, *, wrong_count=False):
    source = tmp_path / "source"
    source.mkdir()
    bills = pd.DataFrame({
        "bill_id": ["unclassified", "missing", "introduced"],
        "state": ["TX", "VT", "TX"],
        "title": ["Original title", "No actions", "Introduced title"],
        "n_actions": [2 if wrong_count else 1, 0, 1],
        "recorded_outcome": ["no_action_data", "no_action_data", "introduced_or_pending"],
    })
    bills.to_parquet(source / "bills.parquet", index=False)
    pd.DataFrame({
        "bill_id": ["unclassified", "introduced"], "classification": ["", "introduction"],
    }).to_parquet(source / "bill_actions.parquet", index=False)
    (source / "bill_extraction_manifest.json").write_text(json.dumps({
        "status": "complete_extraction_not_source_certification",
        "artifacts": {
            name: {"sha256": sha256_file(source / name)}
            for name in ("bills.parquet", "bill_actions.parquet")
        },
    }))
    return source, bills


def test_outcome_correction_preserves_extraction_and_unrelated_values(tmp_path):
    source, original = _outcome_source(tmp_path)
    original_hash = sha256_file(source / "bills.parquet")
    out = tmp_path / "correction"
    assert repair_outcomes(["--source-dir", str(source), "--out-dir", str(out)]) == 0
    actual = pd.read_parquet(out / "bills.parquet")
    expected = original.copy()
    expected.loc[0, "recorded_outcome"] = "action_stage_unclassified"
    pd.testing.assert_frame_equal(actual, expected)
    assert sha256_file(source / "bills.parquet") == original_hash
    manifest = json.loads((out / "outcome_correction_manifest.json").read_text())
    assert manifest["n_action_records_checked"] == 2
    assert manifest["n_outcomes_changed"] == 1
    assert manifest["artifacts"]["bills.parquet"]["sha256"] == sha256_file(out / "bills.parquet")
    assert pd.read_parquet(out / "bill_outcome_changes.parquet")["bill_id"].tolist() == [
        "unclassified",
    ]
    with pytest.raises(FileExistsError, match="new correction"):
        repair_outcomes(["--source-dir", str(source), "--out-dir", str(out)])


@pytest.mark.parametrize("damage", ["checksum", "counts"])
def test_outcome_correction_refuses_corrupt_or_inconsistent_source(tmp_path, damage):
    source, _ = _outcome_source(tmp_path, wrong_count=damage == "counts")
    if damage == "checksum":
        (source / "bill_actions.parquet").write_bytes(b"corrupt source")
    out = tmp_path / "refused"
    with pytest.raises(ValueError, match="checksum mismatch|disagree"):
        repair_outcomes(["--source-dir", str(source), "--out-dir", str(out)])
    assert not out.exists()


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

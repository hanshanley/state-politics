"""Tests for all-state within-party focus profiles."""

from __future__ import annotations

import pandas as pd

from state_politics.analysis.state_focus import (
    _kentucky_priority_units,
    _maryland_agenda_units,
    build_state_focus_atlas,
    combine_stated_emphasis,
    focus_metrics,
)
from state_politics.analysis.taxonomy import load_topics


def test_kentucky_parser_keeps_priority_bills_and_drops_session_index():
    text = """
    Priority Legislation SB 1 SB 2 SB 50.
    24RS SB 1 Legislation Title AN ACT relating to education. Bill Documents
    Summary of Original Version Create a research fund for public universities.
    Index Headings
    24RS SB 2 Legislation Title AN ACT relating to student safety. Bill Documents
    Summary of Enacted Version Improve school safety and student mental health.
    Legislative History
    24RS SB 50 Legislation Title AN ACT relating to roads. Bill Documents
    Summary of Original Version Build roads. Index Headings
    """
    units = _kentucky_priority_units(text)

    assert len(units) == 2
    assert "Senate Bill 1" in units[0] and "public universities" in units[0]
    assert "Senate Bill 2" in units[1] and "student mental health" in units[1]
    assert all("Bill 50" not in unit for unit in units)


def test_maryland_parser_uses_the_agenda_sentence_not_assignments():
    text = (
        "Senator X will chair a committee. The Senate Democratic Caucus agenda will focus on "
        "growth, affordability, and protecting against attacks from the federal Administration "
        "in the 2026 Legislative Session. Committee assignments follow."
    )
    units = _maryland_agenda_units(text)

    assert units == [
        "Senate Democratic Caucus agenda will focus on growth, affordability, and protecting "
        "against attacks from the federal Administration in the 2026 Legislative Session."
    ]


def test_caucus_supplement_never_overrides_party_committee_evidence():
    committee = pd.DataFrame(
        [
            {
                "state": "PA", "party": "D", "era": "2018-present", "topic": 6,
                "topic_name": "Education", "n_planks": 9, "share": 1.0,
            }
        ]
    )
    caucus = pd.DataFrame(
        [
            {
                "state": "PA", "party": "D", "topic": 3, "topic_name": "Health",
                "n_items": 4, "share": 1.0, "evidence_type": "legislative_caucus",
            },
            {
                "state": "MD", "party": "D", "topic": 20,
                "topic_name": "Government operations", "n_items": 1, "share": 1.0,
                "evidence_type": "legislative_caucus",
            },
        ]
    )
    combined = combine_stated_emphasis(committee, caucus)

    assert set(map(tuple, combined[["state", "party"]].drop_duplicates().values)) == {
        ("PA", "D"), ("MD", "D")
    }
    assert combined[combined["state"] == "PA"]["evidence_type"].unique().tolist() == [
        "party_committee"
    ]


def test_focus_metrics_uses_a_leave_one_state_out_baseline():
    vectors = pd.DataFrame(
        [[0.8, 0.2], [0.2, 0.8], [0.2, 0.8]],
        index=pd.MultiIndex.from_tuples(
            [("TX", "D"), ("OH", "D"), ("VT", "D")], names=["state", "party"]
        ),
        columns=[3, 6],
    )
    counts = pd.DataFrame(
        [
            {"state": state, "party": "D", "topic": topic, "n_items": 10}
            for state in ("TX", "OH", "VT") for topic in (3, 6)
        ]
    )
    metrics = focus_metrics(vectors, counts, {3: "Health", 6: "Education"})
    texas = metrics.set_index("state").loc["TX"]

    assert texas["focus_topic"] == "Health"
    assert texas["focus_share"] == 0.8
    assert texas["peer_share"] == 0.2
    assert texas["overemphasis"] == 0.6


def test_atlas_contains_all_100_state_party_rows_and_marks_nebraska():
    topics = load_topics()
    stated = pd.DataFrame(
        [
            {
                "state": "NE", "party": party, "topic": 6, "topic_name": "Education",
                "n_items": 10, "share": 1.0, "evidence_type": "party_committee",
            }
            for party in ("D", "R")
        ]
    )
    bills = pd.DataFrame(
        columns=["state", "party", "topic", "topic_name", "n_bills", "share"]
    )
    atlas = build_state_focus_atlas(stated, bills, topics)

    assert len(atlas) == 100
    nebraska = atlas[atlas["state"] == "NE"]
    assert set(nebraska["stated_source"]) == {"party_committee"}
    assert set(nebraska["bill_status"]) == {"formally_nonpartisan_legislature"}

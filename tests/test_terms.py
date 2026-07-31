"""Tests for TF-IDF and within-party log2 term concentration."""

from __future__ import annotations

import pandas as pd

from state_politics.analysis.terms import (
    build_bill_documents,
    build_stated_documents,
    distinctive_terms,
)


def test_bill_documents_group_titles_by_state_party():
    bills = pd.DataFrame(
        [
            {"state": "TX", "sponsor_party": "D", "title": "Voting rights"},
            {"state": "TX", "sponsor_party": "D", "title": "Ballot access"},
            {"state": "TX", "sponsor_party": "unknown", "title": "Ignored"},
            {"state": "OH", "sponsor_party": "R", "title": "Property tax"},
        ]
    )
    documents = build_bill_documents(bills).set_index(["state", "party"])

    assert documents.loc[("TX", "D"), "n_source_items"] == 2
    assert "Voting rights" in documents.loc[("TX", "D"), "text"]
    assert ("TX", "unknown") not in documents.index


def test_stated_documents_prefer_committee_over_caucus_supplement():
    platforms = pd.DataFrame(
        [
            {
                "state": "PA", "party": "D", "year": 2024, "confirmed": True,
                "text": "Committee platform",
            }
        ]
    )
    caucuses = pd.DataFrame(
        [
            {
                "state": "PA", "party": "D", "year": 2025,
                "institution": "Pennsylvania Senate Democratic Caucus",
                "text": "Caucus agenda", "n_pages": 1,
            },
            {
                "state": "MD",
                "party": "D",
                "year": 2026,
                "institution": "Maryland Senate Democratic Caucus",
                "text": (
                    "The Senate Democratic Caucus agenda will focus on growth, affordability, "
                    "and protecting against attacks from the federal Administration in the "
                    "2026 Legislative Session."
                ),
                "n_pages": 1,
            },
        ]
    )
    documents = build_stated_documents(platforms, caucuses).set_index(["state", "party"])

    assert documents.loc[("PA", "D"), "evidence_type"] == "party_committee"
    assert documents.loc[("PA", "D"), "text"] == "Committee platform"
    assert documents.loc[("MD", "D"), "evidence_type"] == "legislative_caucus"


def test_log2_concentration_is_against_same_party_peers():
    documents = pd.DataFrame(
        [
            {
                "state": "TX", "party": "D", "stream": "bills",
                "text": "solar solar solar solar schools common common",
            },
            {
                "state": "OH", "party": "D", "stream": "bills",
                "text": "schools schools common common common",
            },
            {
                "state": "TX", "party": "R", "stream": "bills",
                "text": "solar common common common",
            },
            {
                "state": "OH", "party": "R", "stream": "bills",
                "text": "solar common common common",
            },
        ]
    )
    terms = distinctive_terms(
        documents, min_count=2, max_features=100, top_n=5
    )
    solar = terms[
        (terms["state"] == "TX")
        & (terms["party"] == "D")
        & (terms["term"] == "solar")
    ].iloc[0]

    assert solar["log2_concentration"] > 1
    assert solar["count"] == 4
    # Republican usage is irrelevant to a Democratic same-party baseline.
    assert solar["peer_count"] == 0

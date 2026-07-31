"""Tests for TF-IDF and within-party log2 term concentration."""

from __future__ import annotations

import pandas as pd
import pytest

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
    assert documents.loc[("TX", "D"), "evidence_type"] == "legislative_bills"
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

    assert solar["peer_absent"]
    assert pd.isna(solar["log2_concentration"])
    assert solar["count"] == 4
    # Republican usage is irrelevant to a Democratic same-party baseline.
    assert solar["peer_count"] == 0


def test_numeric_log2_ratio_has_literal_rate_interpretation():
    documents = pd.DataFrame(
        [
            {"state": "TX", "party": "D", "stream": "bills", "text": "solar " * 8 + "school " * 2},
            {"state": "OH", "party": "D", "stream": "bills", "text": "solar " * 2 + "school " * 8},
            {"state": "TX", "party": "R", "stream": "bills", "text": "wind school " * 5},
            {"state": "OH", "party": "R", "stream": "bills", "text": "wind school " * 5},
        ]
    )
    terms = distinctive_terms(documents, min_count=2, max_features=100, top_n=5)
    solar = terms[
        (terms["state"] == "TX")
        & (terms["party"] == "D")
        & (terms["term"] == "solar")
    ].iloc[0]

    expected = (
        solar["count"] / solar["feature_total"]
    ) / (
        solar["peer_count"] / solar["peer_feature_total"]
    )
    assert not solar["peer_absent"]
    assert 2 ** solar["log2_concentration"] == pytest.approx(expected, rel=1e-4)


def test_stated_term_peers_use_the_same_evidence_genre():
    documents = pd.DataFrame(
        [
            {
                "state": "KY", "party": "R", "stream": "stated",
                "evidence_type": "legislative_caucus",
                "text": "solar " * 8 + "school " * 2,
            },
            {
                "state": "NJ", "party": "R", "stream": "stated",
                "evidence_type": "legislative_caucus",
                "text": "solar " * 2 + "school " * 8,
            },
            {
                "state": "TX", "party": "R", "stream": "stated",
                "evidence_type": "party_committee",
                "text": "solar " * 100 + "school " * 100,
            },
            {
                "state": "CA", "party": "R", "stream": "stated",
                "evidence_type": "party_committee",
                "text": "budget " * 100 + "school " * 100,
            },
        ]
    )

    terms = distinctive_terms(documents, min_count=2, max_features=100, top_n=5)
    solar = terms[
        (terms["state"] == "KY")
        & (terms["term"] == "solar solar")
    ].iloc[0]

    assert solar["evidence_type"] == "legislative_caucus"
    assert solar["peer_feature_total"] == 4

"""Tests for TF-IDF and within-party log2 term concentration."""

from __future__ import annotations

import pandas as pd
import pytest

from state_politics.analysis.terms import (
    build_bill_documents,
    build_stated_documents,
    distinctive_terms,
    main,
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


def test_bill_term_evidence_excludes_requests_without_merging_formal_records():
    source = pd.DataFrame({
        "state": ["MT"] * 3, "sponsor_party": ["R"] * 3,
        "identifier": ["LC 239", "SB 6", "HB 117"],
        "title": ["Request-only language", "Senate policy text", "House policy text"],
    })
    [document] = list(build_bill_documents(source).itertuples())
    assert document.n_source_items == 2
    assert document.text == "Senate policy text. House policy text"


def test_stated_documents_prefer_committee_over_caucus_supplement():
    platforms = pd.DataFrame(
        [
            {
                "state": "PA", "party": "D", "year": 2024, "confirmed": True,
                "text": "Committee platform",
            },
            {
                "state": "DE", "party": "D", "year": None, "confirmed": True,
                "text": "Currently published undated committee platform",
            },
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
    assert documents.loc[("DE", "D"), "evidence_type"] == "party_committee"
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


@pytest.mark.parametrize("has_committee", [False, True])
@pytest.mark.parametrize("empty_caucuses", [False, True])
def test_stated_documents_allow_no_extracted_caucus_units(has_committee, empty_caucuses):
    platforms = pd.DataFrame(
        [{
            "state": "PA", "party": "D", "year": 2024, "confirmed": has_committee,
            "text": "Committee evidence",
        }]
    )
    caucuses = pd.DataFrame(
        [] if empty_caucuses else [{
            "state": "KY", "party": "R", "year": 2024, "institution": "Caucus",
            "text": "No extractable priority entries.", "n_pages": 1,
        }],
        columns=["state", "party", "year", "institution", "text", "n_pages"],
    )

    documents = build_stated_documents(platforms, caucuses)

    assert list(documents.columns) == [
        "state", "party", "text", "n_source_items", "evidence_type", "stream",
    ]
    assert len(documents) == int(has_committee)
    if has_committee:
        [document] = list(documents.itertuples())
        assert document.text == "Committee evidence"
        assert document.evidence_type == "party_committee"
        assert document.n_source_items == 1


@pytest.mark.parametrize(
    "texts",
    [
        [],
        ["solar housing"],
        ["solar housing", "solar housing"],
        ["the and public"] * 3,
        ["solar"] * 3,
        ["solar", "housing", "migration"],
        ["solar school", "solar school", "wind school", "wind school"],
    ],
    ids=["empty", "one", "two", "stopwords", "all-common", "disjoint", "below-count"],
)
def test_unavailable_term_comparisons_retain_export_schema(texts):
    documents = pd.DataFrame({
        "state": ["TX", "OH", "CA", "NY"][:len(texts)],
        "party": ["D"] * len(texts),
        "stream": ["bills"] * len(texts),
        "text": texts,
    })

    if len(texts) < 4:
        with pytest.warns(UserWarning, match="Term comparison unavailable"):
            terms = distinctive_terms(documents, min_count=100, max_features=100)
    else:
        terms = distinctive_terms(documents, min_count=100, max_features=100)

    assert terms.empty
    assert list(terms.columns) == [
        "state", "party", "stream", "evidence_type", "term", "count", "peer_count",
        "feature_total", "peer_feature_total", "tfidf", "log2_concentration",
        "peer_absent", "tfidf_rank", "concentration_rank",
    ]


def test_term_vocabulary_unavailability_does_not_hide_invalid_configuration():
    documents = pd.DataFrame({
        "state": ["TX", "OH", "CA", "NY"], "party": ["D"] * 4,
        "stream": ["bills"] * 4, "text": ["solar school"] * 4,
    })

    with pytest.raises(ValueError, match="max_features"):
        distinctive_terms(documents, min_count=1, max_features=0)


def test_terms_cli_exports_readable_empty_results_and_explicit_unavailability(tmp_path, capsys):
    frames = {
        "bills": pd.DataFrame(
            columns=["state", "identifier", "title", "sponsor_party"],
        ),
        "platforms": pd.DataFrame(
            columns=["state", "party", "year", "confirmed", "text"],
        ),
        "caucuses": pd.DataFrame(
            columns=["state", "party", "year", "institution", "text", "n_pages"],
        ),
    }
    argv = []
    for name, frame in frames.items():
        path = tmp_path / f"{name}.parquet"
        frame.to_parquet(path)
        argv.extend((f"--{name}", str(path)))
    out = tmp_path / "output"

    with pytest.warns(UserWarning, match="Term comparison unavailable: no supplied documents"):
        assert main([*argv, "--out-dir", str(out)]) == 0

    terms = pd.read_csv(out / "state_party_terms.csv")
    highlights = pd.read_csv(out / "state_party_term_highlights.csv")
    assert terms.empty and {"term", "log2_concentration", "peer_absent"} <= set(terms)
    assert highlights.empty and list(highlights) == [
        "state", "party", "stream", "distinctive_terms",
    ]
    assert "unavailable: no eligible same-party term comparisons" in capsys.readouterr().out

"""Tests for cross-state text-reuse detection.

The risk in this analysis is the opposite of the rest of the project: not missing evidence, but
manufacturing it. Two states can name a bill "An Act relating to the state budget" without ever
having seen each other's text, so the tests below are mostly about *not* calling coincidence
diffusion.
"""

from __future__ import annotations

import pandas as pd
import pytest

from state_politics.analysis.diffusion import (
    find_near_duplicates,
    find_reuse_clusters,
    is_ceremonial,
    normalize_title,
    significant_tokens,
)


def _bills(rows):
    return pd.DataFrame(rows, columns=["state", "year", "title", "sponsor_party"])


def test_normalize_title_strips_the_parts_that_differ_between_states():
    """Bill numbers, years and ordinals are exactly what two states running one template differ
    on, so they must not block a match."""
    assert normalize_title("HB 1234 - An Act relating to the 2024 Uniform Commercial Code") == \
        normalize_title("SB 99: An Act relating to the 2019 Uniform Commercial Code")


def test_normalize_title_is_case_and_punctuation_insensitive():
    assert (normalize_title("AN ACT, RELATING TO HEALTH!")
            == normalize_title("an act relating to health"))


def test_significant_tokens_drops_boilerplate():
    tokens = significant_tokens(normalize_title("An Act relating to the state of health insurance"))
    assert "insurance" in tokens
    assert "health" in tokens
    for boilerplate in ("act", "relating", "the", "state"):
        assert boilerplate not in tokens


def test_find_reuse_clusters_requires_several_states():
    """One state filing the same bill twice is a re-introduction, not diffusion."""
    rows = [("TX", 2020, "Enacting the widget licensure interstate compact provisions", "R")] * 4
    assert find_reuse_clusters(_bills(rows), min_states=3).empty


def test_find_reuse_clusters_finds_a_genuine_template():
    title = "Enacting the audiology and speech-language pathology interstate compact"
    rows = [(state, 2021, title, "R") for state in ("TX", "OH", "GA", "IA")]
    clusters = find_reuse_clusters(_bills(rows), min_states=3)
    assert len(clusters) == 1
    assert clusters.iloc[0]["n_states"] == 4


def test_generic_administrative_titles_are_excluded():
    """Every state files a budget bill; that is not evidence of copying."""
    rows = [(state, 2021, "An Act making appropriations for the general state budget", "D")
            for state in ("TX", "OH", "GA", "IA")]
    assert find_reuse_clusters(_bills(rows), min_states=3).empty


def test_short_titles_are_excluded():
    rows = [(state, 2021, "Relating to taxes", "R") for state in ("TX", "OH", "GA")]
    assert find_reuse_clusters(_bills(rows), min_states=3).empty


def test_near_duplicates_tolerate_rewording():
    """Real model legislation is edited in transit; exact matching would miss it."""
    rows = [
        ("TX", 2021, "An Act enacting the advanced practice registered nurse licensure "
                     "compact", "R"),
        ("OH", 2021, "A Bill enacting the advanced practice registered nurse compact "
                     "licensure", "R"),
        ("GA", 2022, "Advanced practice registered nurse licensure compact; enact "
                     "provisions", "R"),
    ]
    clusters = find_near_duplicates(_bills(rows), min_states=3, threshold=0.7)
    assert len(clusters) == 1
    assert clusters.iloc[0]["n_states"] == 3


def test_near_duplicates_do_not_merge_unrelated_bills():
    rows = [
        ("TX", 2021, "An Act concerning the licensure of advanced practice registered nurses", "R"),
        ("OH", 2021, "An Act concerning the regulation of commercial fishing vessel permits", "D"),
        ("GA", 2021, "An Act concerning municipal broadband infrastructure grant funding", "D"),
    ]
    assert find_near_duplicates(_bills(rows), min_states=3).empty


def test_near_duplicates_report_party_and_year_span():
    title = "Agreement among the states to elect the president by national popular vote"
    rows = [("TX", 2019, title, "D"), ("OH", 2021, title, "D"), ("GA", 2023, title, "D")]
    clusters = find_near_duplicates(_bills(rows), min_states=3)
    assert clusters.iloc[0]["first_year"] == 2019
    assert clusters.iloc[0]["last_year"] == 2023
    assert set(clusters.iloc[0]["states"].split(",")) == {"TX", "OH", "GA"}


@pytest.mark.parametrize(
    "title",
    [
        'RECOGNIZING THE MONTH OF APRIL 2021 AS "NATIONAL DONATE LIFE MONTH"',
        "A Resolution designating the week of May 2 through 8 as Awareness Week",
        "Commemorating the 50th Anniversary of the State Government Affairs Council",
        "Honoring the life and achievements of a distinguished citizen",
    ],
)
def test_ceremonial_resolutions_are_flagged(title):
    """Commemorative templates circulate as widely as policy but say nothing about an agenda."""
    assert is_ceremonial(title)


@pytest.mark.parametrize(
    "title",
    [
        "Enacting the audiology and speech-language pathology interstate compact",
        "An Act increasing the property tax exemption for disabled veterans",
        "Provide a sales and use tax exemption for feminine hygiene products",
    ],
)
def test_substantive_bills_are_not_flagged_as_ceremonial(title):
    assert not is_ceremonial(title)


def test_empty_input_returns_empty_frames():
    empty = _bills([])
    assert find_reuse_clusters(empty).empty
    assert find_near_duplicates(empty).empty


def test_cohesion_exposes_transitive_chaining():
    """A chain A~B~C clusters all three even when A and C are dissimilar.

    The reported ``min_similarity`` has to reveal that, otherwise ``n_states`` reads as
    "this many states filed near-identical text" when it does not mean that.
    """
    rows = [
        ("TX", 2021, "alpha beta gamma delta epsilon zeta", "R"),
        ("OH", 2021, "beta gamma delta epsilon zeta eta", "R"),
        ("GA", 2021, "gamma delta epsilon zeta eta theta", "R"),
    ]
    frame = pd.DataFrame(rows, columns=["state", "year", "title", "sponsor_party"])
    clusters = find_near_duplicates(frame, min_states=3, threshold=0.6)

    assert len(clusters) == 1
    # The end links pair at 0.6+, but the ends of the chain do not.
    assert clusters["min_similarity"].iloc[0] < 0.6


def test_cohesion_is_one_for_an_exact_repeat():
    """Identical text across states has nothing to disclose."""
    rows = [
        (state, 2021, "enacting the interstate medical licensure compact act", "R")
        for state in ("TX", "OH", "GA")
    ]
    frame = pd.DataFrame(rows, columns=["state", "year", "title", "sponsor_party"])
    clusters = find_near_duplicates(frame, min_states=3, threshold=0.8)

    assert clusters["min_similarity"].iloc[0] == 1.0

"""Tests for longitudinal party-topic change analysis."""

from __future__ import annotations

import pandas as pd
import pytest

from state_politics.analysis.trends import (
    benjamini_hochberg,
    party_topic_trends,
    state_topic_trends,
)


def _rows():
    rows = []
    for year in range(2018, 2027):
        early = year <= 2020
        late = year >= 2024
        for party in ("D", "R"):
            for state in ("AK", "AZ", "CA", "CO", "FL", "IL", "NY", "TX"):
                # Topic 1 rises from 20% to 40%; topic 2 falls correspondingly.
                topic_one = 20 if early else 40 if late else 30
                rows.extend(
                    [
                        {
                            "state": state, "party": party, "year": year, "topic": 1,
                            "n_bills": topic_one,
                        },
                        {
                            "state": state, "party": party, "year": year, "topic": 2,
                            "n_bills": 100 - topic_one,
                        },
                    ]
                )
    return pd.DataFrame(rows)


def test_benjamini_hochberg_is_monotone_in_ranked_order():
    p = [0.01, 0.04, 0.03, 0.20]
    q = benjamini_hochberg(p)
    ranked = sorted(zip(p, q, strict=True))
    assert [value for _, value in ranked] == sorted(value for _, value in ranked)
    assert all(0 <= value <= 1 for value in q)


def test_party_trends_reproduce_early_late_change_and_significance():
    trends = party_topic_trends(_rows())
    row = trends[(trends["party"] == "D") & (trends["topic"] == 1)].iloc[0]

    assert row["early_share"] == pytest.approx(0.20)
    assert row["late_share"] == pytest.approx(0.40)
    assert row["change"] == pytest.approx(0.20)
    assert row["slope_per_year"] > 0
    assert row["q_value"] < 0.05


def test_state_trends_require_enough_years_and_bills():
    frame = _rows()
    trends = state_topic_trends(frame)
    assert len(trends) == 32
    assert trends["n_years"].eq(8).all()

    sparse = frame.copy()
    sparse["n_bills"] = 1
    assert state_topic_trends(sparse).empty


def test_state_trends_include_observed_years_with_zero_topic_bills():
    frame = _rows()
    frame = frame[
        ~(
            frame["state"].eq("AK")
            & frame["party"].eq("D")
            & frame["year"].eq(2018)
            & frame["topic"].eq(1)
        )
    ].copy()
    frame.loc[
        frame["state"].eq("AK")
        & frame["party"].eq("D")
        & frame["year"].eq(2018)
        & frame["topic"].eq(2),
        "n_bills",
    ] = 100

    row = state_topic_trends(frame).query(
        "state == 'AK' and party == 'D' and topic == 1"
    ).iloc[0]

    assert row["n_years"] == 8
    assert row["first_year"] == 2018
    assert row["first_share"] == 0


def test_state_trends_exclude_pre_window_years():
    frame = pd.concat(
        [
            _rows(),
            pd.DataFrame(
                [
                    {
                        "state": "AK", "party": "D", "year": 2017,
                        "topic": 1, "n_bills": 100,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    row = state_topic_trends(frame).query(
        "state == 'AK' and party == 'D' and topic == 1"
    ).iloc[0]
    assert row["first_year"] == 2018

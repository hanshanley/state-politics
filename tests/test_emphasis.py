"""Tests for classifier validation and emphasis measurement.

The point of the emphasis tests is that share, not count, is the unit: platforms differ by an
order of magnitude in length, so counting planks would measure verbosity rather than priority.
"""

from __future__ import annotations

import pandas as pd

from state_politics.analysis.emphasis import emphasis_by_party, emphasis_table
from state_politics.analysis.taxonomy import Topic
from state_politics.analysis.validate import DEFAULT_GOLD_PATH, Scores, load_gold

TOPICS = [
    Topic(code=1, name="Macroeconomics", description="d", seeds=("tax",)),
    Topic(code=5, name="Labor", description="d", seeds=("union",)),
    Topic(code=6, name="Education", description="d", seeds=("school",)),
]


def _planks(rows):
    return pd.DataFrame(
        rows, columns=["state", "party", "era", "topic"]
    ).assign(similarity=0.5)


def test_gold_set_exists_and_is_labelled():
    gold = load_gold()
    assert len(gold) >= 50
    assert all(p.gold_topic > 0 for p in gold)
    assert all(p.text.strip() for p in gold)
    assert DEFAULT_GOLD_PATH.exists()


def test_gold_set_covers_a_range_of_topics():
    """A gold set concentrated on one topic would not test the classifier at all."""
    gold = load_gold()
    assert len({p.gold_topic for p in gold}) >= 10


def test_scores_report_both_accuracies():
    score = Scores(name="x", n=50, correct=31, unclassified=0, top2_correct=39)
    assert score.accuracy == 31 / 50
    assert score.top2_accuracy == 39 / 50
    assert "top-1 31/50 (62%)" in score.summary()


def test_scores_handle_an_empty_gold_set():
    assert Scores(name="x", n=0, correct=0, unclassified=0).accuracy == 0.0


def test_emphasis_uses_share_not_raw_count():
    """A 10-plank platform and a 1,000-plank one must weigh the same per party."""
    planks = _planks(
        [("TX", "R", "2018-present", 1)] * 90
        + [("TX", "R", "2018-present", 6)] * 10
        + [("VT", "R", "2018-present", 1)] * 1
        + [("VT", "R", "2018-present", 6)] * 9
    )
    table = emphasis_table(planks, TOPICS, by=("state", "party"))
    tx = table[(table.state == "TX") & (table.topic == 1)].iloc[0]
    vt = table[(table.state == "VT") & (table.topic == 6)].iloc[0]
    assert tx["share"] == 0.9
    assert vt["share"] == 0.9
    # Shares sum to 1 within each group.
    assert table.groupby(["state", "party"])["share"].sum().round(6).eq(1.0).all()


def test_unclassified_planks_are_excluded_from_the_denominator():
    """Counting them would dilute every share by an amount that varies with document quality."""
    planks = _planks(
        [("TX", "R", "e", 1)] * 5 + [("TX", "R", "e", 6)] * 5 + [("TX", "R", "e", None)] * 90
    )
    table = emphasis_table(planks, TOPICS, by=("state", "party"))
    assert set(table["share"].round(6)) == {0.5}


def test_emphasis_by_party_reports_the_gap_between_the_two():
    planks = _planks(
        [("TX", "D", "e", 5)] * 60 + [("TX", "D", "e", 1)] * 40
        + [("TX", "R", "e", 5)] * 10 + [("TX", "R", "e", 1)] * 90
    )
    table = emphasis_by_party(planks, TOPICS)
    labour = table[table.topic == 5].iloc[0]
    assert round(labour["D"], 3) == 0.6
    assert round(labour["R"], 3) == 0.1
    assert round(labour["gap"], 3) == 0.5
    assert labour["n_D"] == 60 and labour["n_R"] == 10
    # Ordered by gap, so the most Democratic-leaning topic comes first.
    assert table.iloc[0]["topic"] == 5


def test_emphasis_by_party_ignores_third_parties():
    planks = _planks([("TX", "D", "e", 5)] * 10 + [("TX", "other", "e", 5)] * 100)
    table = emphasis_by_party(planks, TOPICS)
    assert table[table.topic == 5].iloc[0]["n_D"] == 10
    assert "other" not in table.columns


def test_emphasis_table_on_empty_input_returns_empty_frame():
    empty = pd.DataFrame(columns=["state", "party", "era", "topic", "similarity"])
    assert emphasis_table(empty, TOPICS).empty

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


def test_divergence_table_reports_the_gap_between_saying_and_filing():
    from state_politics.analysis.revealed import divergence_table

    platform = pd.DataFrame({
        "topic": [5, 12], "topic_name": ["Labor", "Law"],
        "D": [0.06, 0.07], "R": [0.01, 0.09],
    })
    bills = pd.DataFrame({
        "topic": [5, 12, 5, 12], "party": ["D", "D", "R", "R"],
        "share": [0.05, 0.14, 0.01, 0.16], "n_bills": [10, 20, 5, 30],
    })
    table = divergence_table(platform, bills)
    dem_law = table[(table.party == "D") & (table.topic == 12)].iloc[0]
    assert round(dem_law["stated_minus_revealed"], 3) == round(0.07 - 0.14, 3)
    # Negative means filed more than talked about.
    assert dem_law["stated_minus_revealed"] < 0
    assert len(table) == 4


def test_divergence_table_treats_a_missing_side_as_zero_not_as_missing():
    """A topic a party never legislates is a real zero, not an absent observation."""
    from state_politics.analysis.revealed import divergence_table

    platform = pd.DataFrame({"topic": [19], "topic_name": ["International"],
                             "D": [0.03], "R": [0.02]})
    bills = pd.DataFrame({"topic": [19], "party": ["D"], "share": [0.001], "n_bills": [2]})
    table = divergence_table(platform, bills)
    rep = table[table.party == "R"].iloc[0]
    assert rep["revealed_share"] == 0.0
    assert rep["stated_minus_revealed"] == 0.02


def test_classify_bills_leaves_very_short_titles_unclassified():
    """A four-word procedural title carries too little signal to place."""
    from state_politics.analysis.revealed import classify_bills

    class StubClassifier:
        def predict_many(self, texts, batch_size=512, min_similarity=0.20):
            return [(1, 0.9, 0.3) for _ in texts]

    frame = pd.DataFrame({"title": ["Relating to tax.", "An Act relating to the funding of "
                                    "public schools and teacher salaries statewide"]})
    out = classify_bills(frame, StubClassifier())
    assert pd.isna(out.iloc[0]["topic"])
    assert out.iloc[1]["topic"] == 1


def test_topic_vectors_recomputes_shares_instead_of_summing_eras():
    """The platform table is split by era and each era's shares sum to 1.

    Summing them gave a state 200% and produced "distinctive" topics with shares above 100%.
    """
    from state_politics.analysis.profiles import topic_vectors

    table = pd.DataFrame({
        "state": ["TN"] * 4, "party": ["D"] * 4,
        "era": ["1990-2017", "1990-2017", "2018-present", "2018-present"],
        "topic": [5, 12, 5, 12],
        "n_planks": [30, 10, 5, 55],
        "share": [0.75, 0.25, 0.083, 0.917],   # each era sums to 1
    })
    vectors = topic_vectors(table, count_column="n_planks")
    assert round(float(vectors.loc[("TN", "D")].sum()), 6) == 1.0
    assert (vectors.values <= 1.0).all()
    # Pooled counts: 35 of 100 planks on topic 5.
    assert round(float(vectors.loc[("TN", "D"), 5]), 3) == 0.35


def test_topic_vectors_drops_groups_with_too_few_observations():
    """One plank moves a share by tens of points; such a group is noise, not an outlier."""
    from state_politics.analysis.profiles import topic_vectors

    table = pd.DataFrame({
        "state": ["TX", "VT"], "party": ["D", "D"], "era": ["e", "e"],
        "topic": [5, 5], "n_planks": [500, 2], "share": [1.0, 1.0],
    })
    vectors = topic_vectors(table, count_column="n_planks", min_observations=30)
    assert list(vectors.index) == [("TX", "D")]


def test_cross_state_outliers_compares_within_party():
    """'Unusual for a Democrat', not the trivial finding that Democrats differ from Republicans."""
    from state_politics.analysis.profiles import cross_state_outliers
    from state_politics.analysis.taxonomy import Topic

    topics = [Topic(code=5, name="Labor", description="d", seeds=("union",)),
              Topic(code=21, name="Public lands", description="d", seeds=("land",))]
    vectors = pd.DataFrame(
        [[0.9, 0.1], [0.9, 0.1], [0.1, 0.9], [0.9, 0.1], [0.9, 0.1]],
        index=pd.MultiIndex.from_tuples(
            [("CA", "D"), ("NY", "D"), ("MT", "D"), ("TX", "R"), ("FL", "R")],
            names=["state", "party"],
        ),
        columns=[5, 21],
    )
    table = cross_state_outliers(vectors, topics)
    democrats = table[table.party == "D"]
    assert democrats.iloc[0]["state"] == "MT"
    assert democrats.iloc[0]["most_distinctive_topic"] == "Public lands"
    assert set(table["party"]) == {"D", "R"}


def test_cross_state_outliers_on_empty_input():
    from state_politics.analysis.profiles import cross_state_outliers

    assert cross_state_outliers(pd.DataFrame(), []).empty

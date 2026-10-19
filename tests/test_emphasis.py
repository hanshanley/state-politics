"""Tests for classifier validation and emphasis measurement.

The point of the emphasis tests is that share, not count, is the unit: platforms differ by an
order of magnitude in length, so counting planks would measure verbosity rather than priority.
"""

from __future__ import annotations

import pandas as pd

from state_politics.analysis.emphasis import (
    _drop_duplicate_documents,
    emphasis_by_party,
    emphasis_table,
)
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
    planks = _planks(
        [("TX", "D", "e", 5)] * 10
        + [("TX", "R", "e", 1)] * 10
        + [("TX", "other", "e", 5)] * 100
    )
    table = emphasis_by_party(planks, TOPICS)
    assert table[table.topic == 5].iloc[0]["n_D"] == 10
    assert "other" not in table.columns


def test_party_emphasis_weights_matched_states_equally():
    planks = _planks(
        [("TX", "D", "e", 5)] * 100
        + [("TX", "R", "e", 1)] * 100
        + [("VT", "D", "e", 1)]
        + [("VT", "R", "e", 1)]
    )

    matched = emphasis_by_party(planks, TOPICS)
    pooled = emphasis_by_party(planks, TOPICS, matched_states=False)

    matched_labor = matched[matched["topic"] == 5].iloc[0]
    pooled_labor = pooled[pooled["topic"] == 5].iloc[0]
    assert matched_labor["D"] == 0.5
    assert pooled_labor["D"] == 100 / 101
    assert matched_labor["n_states"] == 2


def test_collected_near_duplicate_documents_are_clustered_across_adjacent_years():
    corpus = pd.DataFrame(
        [
            {
                "state": "CO", "party": "D", "year": 2020,
                "source_corpus": "collected",
                "text": "education healthcare environment workers rights " * 20,
            },
            {
                "state": "CO", "party": "D", "year": 2021,
                "source_corpus": "collected",
                "text": "education healthcare environment workers rights " * 21,
            },
            {
                "state": "CO", "party": "D", "year": 2024,
                "source_corpus": "collected",
                "text": "education healthcare environment workers rights " * 20,
            },
        ]
    )

    deduplicated = _drop_duplicate_documents(corpus)

    assert len(deduplicated) == 2
    assert 2024 in set(deduplicated["year"])


def test_platform_section_is_dropped_when_full_same_year_platform_exists():
    corpus = pd.DataFrame(
        [
            {
                "state": "CA", "party": "D", "year": 2020,
                "source_corpus": "collected",
                "text": (
                    "education healthcare environment labor housing immigration "
                    "transportation voting agriculture"
                ),
            },
            {
                "state": "CA", "party": "D", "year": 2020,
                "source_corpus": "collected",
                "text": "education healthcare environment",
            },
        ]
    )

    deduplicated = _drop_duplicate_documents(corpus)

    assert len(deduplicated) == 1
    assert "immigration" in deduplicated.iloc[0]["text"]


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


def test_bill_party_emphasis_weights_states_equally():
    from state_politics.analysis.revealed import party_emphasis_from_states

    state_counts = pd.DataFrame(
        [
            {
                "state": "TX", "party": "D", "topic": 5,
                "topic_name": "Labor", "n_bills": 100, "share": 1.0,
            },
            {
                "state": "VT", "party": "D", "topic": 1,
                "topic_name": "Macroeconomics", "n_bills": 1, "share": 1.0,
            },
        ]
    )

    equal = party_emphasis_from_states(state_counts)
    pooled = party_emphasis_from_states(state_counts, equal_state=False)

    assert equal.loc[equal["topic"] == 5, "share"].iloc[0] == 0.5
    assert pooled.loc[pooled["topic"] == 5, "share"].iloc[0] == 100 / 101


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


def test_introduced_input_excludes_unaligned_metadata_and_preserves_source_fields():
    import hashlib
    import json

    from state_politics.analysis.revealed import BILL_INPUT_CONSTRUCTION, classify_bills

    introduced = (
        "\nAn Act to fund public school classrooms.\n\nSection 1. Teachers receive grants.\n"
    )

    class StubClassifier:
        def predict_many(self, texts, **kwargs):
            assert texts == [introduced]
            return [(6, 0.9, 0.3)]

    bills = pd.DataFrame([{
        "bill_id": "changed-version", "state": "SD",
        "title": "Revise alcohol advertising agreements.",
        "summary": "The amended measure regulates alcoholic beverage advertising.",
        "introduced_text": introduced,
        "filing_time_text_certified": False,
    }])
    result = classify_bills(bills, StubClassifier())
    row = result.iloc[0]
    assert row["classification_text"] == introduced
    assert row["input_sha256"] == hashlib.sha256(introduced.encode()).hexdigest()
    assert json.loads(row["input_fields"]) == ["introduced_text"]
    assert row["bill_input_construction"] == BILL_INPUT_CONSTRUCTION
    assert row["input_tier"] == "introduced_text"
    pd.testing.assert_frame_equal(result[bills.columns], bills)


def test_insufficient_introduced_text_does_not_fall_back_to_unaligned_metadata():
    import json

    from state_politics.analysis.revealed import classify_bills

    class UncalledClassifier:
        def predict_many(self, *args, **kwargs):
            raise AssertionError("later metadata must not mask insufficient introduced evidence")

    bills = pd.DataFrame([{
        "title": "Provide comprehensive funding for public education statewide.",
        "summary": "The amended version supports teacher recruitment and classroom grants.",
        "introduced_text": "Tax.",
    }])
    row = classify_bills(bills, UncalledClassifier()).iloc[0]
    assert row["classification_text"] == "Tax."
    assert row["classification_status"] == "abstained"
    assert row["abstention_reason"] == "insufficient_evidence"
    assert row["input_tier"] == "introduced_text"
    assert json.loads(row["input_fields"]) == ["introduced_text"]


def test_bill_input_retains_title_summary_fallback_and_exact_source_whitespace():
    from state_politics.analysis.revealed import build_bill_input

    assert build_bill_input(" Title \n", "\n Summary ", " \n") == (
        " Title \n\n\n\n Summary ", ["title", "summary"],
    )
    assert build_bill_input("", "\n Summary ") == ("\n Summary ", ["summary"])
    assert build_bill_input(" ", "\n") == ("", [])


def test_bill_prediction_export_retains_learned_rejection_and_output_map(tmp_path):
    import json

    from state_politics.analysis.revealed import count_topics_by_state

    class RejectionClassifier:
        run_id = "rejection-research"
        manifest = {"status": "provisional"}

        def predict_records(self, texts, **kwargs):
            assert texts == ["Funding public schools and regulating alcohol advertising."]
            return [{
                "topic": None, "candidate_topic": 6, "runner_up": 1,
                "score": 0.9, "margin": 0.82, "abstention_reason": "learned_rejection",
                "output_codes": "[1, 6, null]", "rejection_score": 0.9,
                "scores": "[0.02, 0.08, 0.9]", "logits": "[[-2.0, -0.7, 1.7]]",
                "n_chunks": 1,
            }]

    path = tmp_path / "bills.parquet"
    pd.DataFrame([{
        "bill_id": "mixed-policy", "state": "SD", "year": 2024, "sponsor_party": "D",
        "title": "Funding public schools and regulating alcohol advertising.",
    }]).to_parquet(path, index=False)
    counts, totals, coverage = count_topics_by_state(
        path, RejectionClassifier(), predictions_dir=tmp_path / "predictions", progress=None,
    )
    assert counts.empty
    assert totals == {"n_bills": 1, "n_attributed": 1, "n_classified": 0}
    assert coverage.iloc[0]["n_abstained"] == 1
    row = pd.read_parquet(tmp_path / "predictions" / "SD.parquet").iloc[0]
    assert json.loads(row["output_codes"]) == [1, 6, None]
    assert row["rejection_score"] == 0.9
    assert json.loads(row["scores"]) == [0.02, 0.08, 0.9]
    assert json.loads(row["logits"]) == [[-2.0, -0.7, 1.7]]
    assert row["classification_status"] == "abstained"
    assert row["abstention_reason"] == "learned_rejection"


def test_unscored_and_empty_bills_keep_traceable_prediction_schema():
    import hashlib

    from state_politics.analysis.revealed import classify_bills

    class UncalledClassifier:
        run_id = "research-run"
        base_model_run = "base-run"
        manifest = {"status": "provisional", "taxonomy_sha256": "taxonomy"}

        def predict_records(self, *args, **kwargs):
            raise AssertionError("excluded/insufficient evidence must not call the model")

    bills = pd.DataFrame([
        {"bill_id": "shell", "state": "IL", "title": "EDUCATION-TECH"},
        {"bill_id": "short", "state": "TX", "title": "Tax."},
    ])
    result = classify_bills(bills, UncalledClassifier())
    assert result["record_id"].tolist() == ["shell", "short"]
    assert result["model_run"].tolist() == ["research-run", "research-run"]
    assert result["abstention_reason"].tolist() == ["procedural_shell", "insufficient_evidence"]
    assert result["classification_status"].tolist() == ["excluded", "abstained"]
    assert result.iloc[1]["input_sha256"] == hashlib.sha256(b"Tax.").hexdigest()
    assert result["score_type"].eq("not_scored").all()
    assert result["output_codes"].isna().all()
    assert result["rejection_score"].isna().all()
    empty = classify_bills(bills.iloc[:0], UncalledClassifier())
    assert empty.empty and set(empty.columns) == set(result.columns)


def test_reviewed_washington_system_tests_are_excluded_even_with_policy_text():
    from state_politics.analysis.revealed import classify_bills

    class UncalledClassifier:
        def predict_many(self, *args, **kwargs):
            raise AssertionError("publisher test records must never reach the model")

    bills = pd.DataFrame({
        "bill_id": [f"test-{index}" for index in range(6)],
        "state": "WA",
        "title": [
            "Bill 4 for System Testing",
            "Bill 2 for System Testing",
            " TEST   BILL FOR PRODUCTION TESTING ",
            "TEST BILL for Production System Testing",
            "TESTING BILL for Session 2025 Testing and Training",
            "TRAINING BILL FOR SESSION '25",
        ],
        "summary": "Funding public schools and teacher salaries statewide.",
        "introduced_text": "The state shall appropriate funding for classroom instruction.",
    })
    result = classify_bills(bills, UncalledClassifier())

    assert result["record_id"].tolist() == bills["bill_id"].tolist()
    assert result["source_test_record"].all()
    assert result["classification_status"].eq("excluded").all()
    assert result["abstention_reason"].eq("source_test_record").all()
    assert result["topic"].isna().all()
    assert result["score_type"].eq("not_scored").all()
    assert result["classification_text"].str.contains("classroom instruction", regex=False).all()
    pd.testing.assert_frame_equal(result[bills.columns], bills)


def test_source_test_guard_keeps_real_testing_policy_and_evidenced_shells():
    from state_politics.analysis.revealed import classify_bills

    class StubClassifier:
        def predict_many(self, texts, **kwargs):
            assert len(texts) == 4
            return [(6, 0.9, 0.3) for _ in texts]

    bills = pd.DataFrame([
        {"state": "WA", "title": "Testing requirements for safe public drinking water."},
        {"state": "WA", "title": "Establishing a system testing program for water supplies."},
        {"state": "TX", "title": "TEST BILL FOR PRODUCTION TESTING"},
        {"state": "IL", "title": "EDUCATION-TECH",
         "introduced_text": "Funding public schools and teacher salaries statewide."},
    ])
    result = classify_bills(bills, StubClassifier())
    assert result["topic"].eq(6).all()
    assert not result["source_test_record"].any()
    assert not result["procedural_shell"].any()


def test_source_test_exclusions_leave_coverage_denominators_but_remain_exported(tmp_path):
    from state_politics.analysis.revealed import count_topics_by_state

    class StubClassifier:
        def predict_many(self, texts, **kwargs):
            assert texts == ["Testing requirements for safe public drinking water."]
            return [(21, 0.9, 0.3)]

    bills = pd.DataFrame([
        {"bill_id": "test", "title": "TEST BILL FOR PRODUCTION TESTING"},
        {"bill_id": "sample", "title": "Bill 4 for System Testing",
         "introduced_text": "Funding public schools and teacher salaries statewide."},
        {"bill_id": "policy", "title": "Testing requirements for safe public drinking water."},
    ]).assign(state="WA", sponsor_party="D", year=2024)
    path = tmp_path / "bills.parquet"
    bills.to_parquet(path, index=False)
    counts, totals, coverage = count_topics_by_state(
        path, StubClassifier(), progress=None, predictions_dir=tmp_path / "predictions",
    )
    assert totals == {"n_bills": 3, "n_attributed": 3, "n_classified": 1}
    assert counts["n_bills"].tolist() == [1]
    row = coverage.iloc[0]
    assert row["n_source_test_excluded"] == 2
    assert row["n_procedural_excluded"] == 0
    assert row["n_substantive_attributed"] == 1
    assert row["n_abstained"] == 0
    assert row["classification_rate"] == 1.0
    exported = pd.read_parquet(tmp_path / "predictions" / "WA.parquet")
    assert exported["bill_id"].tolist() == bills["bill_id"].tolist()
    assert exported["classification_status"].tolist() == ["excluded", "excluded", "classified"]


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


def test_cross_state_outliers_report_sample_noise_threshold():
    from state_politics.analysis.profiles import cross_state_outliers
    from state_politics.analysis.taxonomy import Topic

    topics = [
        Topic(code=5, name="Labor", description="d", seeds=("union",)),
        Topic(code=21, name="Public lands", description="d", seeds=("land",)),
    ]
    vectors = pd.DataFrame(
        [[0.99, 0.01], [0.5, 0.5], [0.5, 0.5]],
        index=pd.MultiIndex.from_tuples(
            [("TX", "D"), ("OH", "D"), ("VT", "D")],
            names=["state", "party"],
        ),
        columns=[5, 21],
    )
    sizes = pd.Series(
        [1_000, 1_000, 1_000],
        index=vectors.index,
    )

    outliers = cross_state_outliers(
        vectors, topics, sample_sizes=sizes, null_draws=200
    )

    texas = outliers[outliers["state"] == "TX"].iloc[0]
    assert texas["cosine_distance"] > texas["null_distance_p95"]
    assert texas["n_observations"] == 1_000

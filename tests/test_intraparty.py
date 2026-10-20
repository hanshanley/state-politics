"""Tests for the intra-party comparison.

The claim this module makes -- that two state parties of the same party are nearly as far
apart as two of opposite parties -- is only meaningful if the distance measure behaves, if the
two parties are compared over the same states, and if a difference that could be chance is
reported as chance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from state_politics.analysis.intraparty import (
    coherence,
    common_states,
    cosine_distance,
    dispersion,
    dispersion_gap_pvalue,
    distance_to_centroid,
    divisive_topics,
    main,
)

TOPIC_NAMES = {1: "Macroeconomics", 3: "Health", 6: "Education"}


def _vectors(rows):
    frame = pd.DataFrame(
        [values for _, _, values in rows],
        index=pd.MultiIndex.from_tuples([(s, p) for s, p, _ in rows], names=["state", "party"]),
        columns=[1, 3, 6],
    )
    return frame


def test_cosine_distance_is_zero_for_identical_shapes():
    """Cosine compares shape, so doubling every share must not register as distance."""
    assert cosine_distance([0.2, 0.3, 0.5], [0.2, 0.3, 0.5]) == 0.0
    assert cosine_distance([0.2, 0.3, 0.5], [0.4, 0.6, 1.0]) < 1e-9


def test_cosine_distance_is_nan_for_an_empty_vector():
    """An all-zero vector has no direction; returning 0.0 would read as 'identical'."""
    assert np.isnan(cosine_distance([0.0, 0.0, 0.0], [0.2, 0.3, 0.5]))


def test_common_states_restricts_to_states_present_for_both_parties():
    """Dispersion is only comparable across parties on a shared set of states."""
    vectors = _vectors([
        ("TX", "D", [0.5, 0.3, 0.2]), ("TX", "R", [0.2, 0.3, 0.5]),
        ("OH", "D", [0.4, 0.4, 0.2]), ("OH", "R", [0.3, 0.3, 0.4]),
        ("VT", "D", [0.1, 0.1, 0.8]),
    ])
    assert common_states(vectors) == ["OH", "TX"]


def test_dispersion_uses_only_the_states_it_is_given():
    vectors = _vectors([
        ("TX", "D", [0.5, 0.3, 0.2]), ("OH", "D", [0.4, 0.4, 0.2]),
        ("VT", "D", [0.0, 0.0, 1.0]),
    ])
    everything = dispersion(vectors).iloc[0]
    restricted = dispersion(vectors, states=["TX", "OH"]).iloc[0]

    assert everything["n_states"] == 3 and everything["n_pairs"] == 3
    assert restricted["n_states"] == 2 and restricted["n_pairs"] == 1
    assert restricted["mean_distance"] < everything["mean_distance"]


def test_coherence_ratio_is_near_zero_for_cleanly_separated_parties():
    """Tight, well-separated blocs must not look like overlapping ones."""
    vectors = _vectors([
        ("TX", "D", [0.90, 0.05, 0.05]), ("OH", "D", [0.89, 0.06, 0.05]),
        ("TX", "R", [0.05, 0.05, 0.90]), ("OH", "R", [0.05, 0.06, 0.89]),
    ])
    ratio = coherence(vectors).iloc[0]["within_over_between"]
    assert ratio < 0.1


def test_coherence_ratio_approaches_one_when_the_party_label_is_uninformative():
    """If party membership says nothing about agenda, within and between must coincide."""
    rng = np.random.default_rng(11)
    rows = []
    for index in range(24):
        rows.append((f"S{index}", "D" if index % 2 else "R", list(rng.random(3))))
    ratio = coherence(_vectors(rows)).iloc[0]["within_over_between"]
    assert 0.8 < ratio < 1.25


def test_dispersion_gap_reports_chance_as_chance():
    """Same distribution for both parties must not yield a significant gap."""
    rng = np.random.default_rng(5)
    rows = [(f"S{i}", "D" if i % 2 else "R", list(rng.random(3))) for i in range(30)]
    result = dispersion_gap_pvalue(_vectors(rows), n_permutations=400)
    assert result["p_value"] > 0.05


def test_dispersion_gap_detects_a_real_difference():
    """One genuinely tight party against one genuinely scattered one must register."""
    rng = np.random.default_rng(7)
    rows = []
    for index in range(15):
        rows.append((f"T{index}", "D", list(np.array([0.5, 0.3, 0.2]) + rng.random(3) * 0.005))) 
        rows.append((f"T{index}", "R", list(rng.random(3))))
    result = dispersion_gap_pvalue(_vectors(rows), n_permutations=400)
    assert result["p_value"] < 0.05


def test_divisive_topics_reports_spread_alongside_the_mean():
    """A high spread on a small mean is a different finding from one on a large mean."""
    vectors = _vectors([
        ("TX", "D", [0.8, 0.1, 0.1]), ("OH", "D", [0.0, 0.5, 0.5]),
        ("VT", "D", [0.4, 0.3, 0.3]),
    ])
    frame = divisive_topics(vectors, TOPIC_NAMES).set_index("topic")
    assert frame.loc[1, "sd_share"] > frame.loc[3, "sd_share"]
    assert {"mean_share", "max_state", "min_share"} <= set(frame.columns)


def test_distance_to_centroid_names_the_topic_driving_the_difference():
    vectors = _vectors([
        ("TX", "D", [0.9, 0.05, 0.05]), ("OH", "D", [0.1, 0.45, 0.45]),
        ("VT", "D", [0.1, 0.45, 0.45]),
    ])
    frame = distance_to_centroid(vectors).set_index("state")
    assert frame.loc["TX", "most_distinctive_topic"] == 1
    assert frame.loc["TX", "distance_to_centroid"] > frame.loc["OH", "distance_to_centroid"]


def test_coherence_excludes_same_state_pairs_from_between():
    """A state's own D-R pair is not comparable to cross-state within-party pairs.

    Same-state opposite-party pairs are systematically closer than cross-state ones, so
    including them deflates the between-party distance and inflates the within/between ratio --
    in the direction of the finding this module reports.
    """
    vectors = _vectors([
        ("TX", "D", [0.50, 0.30, 0.20]), ("OH", "D", [0.45, 0.35, 0.20]),
        # TX Republicans are deliberately near TX Democrats; OH Republicans are far from both.
        ("TX", "R", [0.50, 0.30, 0.20]), ("OH", "R", [0.05, 0.05, 0.90]),
    ])
    between = coherence(vectors).iloc[0]["between"]

    cross_only = (cosine_distance(vectors.loc[("TX", "D")], vectors.loc[("OH", "R")])
                  + cosine_distance(vectors.loc[("OH", "D")], vectors.loc[("TX", "R")])) / 2
    assert abs(between - cross_only) < 1e-3  # coherence() rounds to 4 dp


@pytest.mark.parametrize(
    ("function", "columns"),
    [
        (dispersion, {"party", "n_states", "n_pairs", "mean_distance"}),
        (coherence, {"mean_within", "between", "within_over_between", "n_states"}),
        (distance_to_centroid, {"state", "party", "distance_to_centroid"}),
        (
            lambda vectors: divisive_topics(vectors, TOPIC_NAMES),
            {"party", "topic", "n_states", "mean_share", "sd_share"},
        ),
    ],
)
def test_empty_intraparty_results_keep_readable_schemas(function, columns):
    result = function(pd.DataFrame())
    assert result.empty
    assert columns <= set(result.columns)


@pytest.mark.parametrize("case", ["empty", "one_party", "one_shared_state", "zero_between"])
def test_intraparty_cli_exports_unavailable_comparisons(tmp_path, capsys, case):
    organizations = {
        "empty": [],
        "one_party": [("TX", "D"), ("OH", "D")],
        "one_shared_state": [("TX", "D"), ("TX", "R")],
        "zero_between": [("TX", "D"), ("TX", "R"), ("OH", "D"), ("OH", "R")],
    }[case]
    platform = pd.DataFrame(
        [
            {
                "state": state, "party": party, "era": "2018-present",
                "topic": topic, "n_planks": 40 if topic == 1 else 0,
            }
            for state, party in organizations for topic in TOPIC_NAMES
        ],
        columns=["state", "party", "era", "topic", "n_planks"],
    )
    platform.to_csv(tmp_path / "platform.csv", index=False)
    platform.rename(columns={"n_planks": "n_bills"}).to_csv(tmp_path / "bills.csv", index=False)
    output = tmp_path / "output"
    output.mkdir()
    for stream in ("platform", "bill"):
        for suffix in ("coherence", "topic_spread", "distance"):
            (output / f"intraparty_{stream}_{suffix}.csv").write_text("stale\n1\n")
    for filename in ("intraparty_dispersion.csv", "intraparty_dispersion_tests.csv"):
        (output / filename).write_text("stale\n1\n")
    assert main([
        "--platform-emphasis", str(tmp_path / "platform.csv"),
        "--bill-emphasis", str(tmp_path / "bills.csv"), "--out-dir", str(output),
        "--permutations", "4",
    ]) == 0
    for stream in ("platform", "bill"):
        for suffix in ("coherence", "topic_spread", "distance"):
            frame = pd.read_csv(output / f"intraparty_{stream}_{suffix}.csv")
            if case != "zero_between":
                assert frame.empty
            elif suffix == "coherence":
                assert frame.iloc[0]["between"] == 0
                assert pd.isna(frame.iloc[0]["within_over_between"])
    for filename in ("intraparty_dispersion.csv", "intraparty_dispersion_tests.csv"):
        frame = pd.read_csv(output / filename)
        assert frame.empty == (case != "zero_between")
    text = capsys.readouterr().out
    assert "unavailable" in text.lower()
    assert "nan" not in text.lower()


@pytest.mark.parametrize("all_zero", [False, True])
def test_dispersion_gap_does_not_turn_undefined_distances_into_significance(all_zero):
    vectors = _vectors([
        (state, party, [0, 0, 0] if all_zero or state == "TX" else [1, 0, 0])
        for state in ("TX", "OH", "VT") for party in ("D", "R")
    ])
    assert dispersion_gap_pvalue(vectors, n_permutations=4) == {}


def test_dispersion_gap_rejects_an_empty_permutation_run():
    vectors = _vectors([
        (state, party, [1, 0, 0]) for state in ("TX", "OH") for party in ("D", "R")
    ])
    with pytest.raises(ValueError, match="permutations"):
        dispersion_gap_pvalue(vectors, n_permutations=0)

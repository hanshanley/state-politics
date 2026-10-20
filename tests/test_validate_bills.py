"""Tests for the bill-title classifier check against statehouse subject tags.

The rule this module protects is that the tag-derived label must never be *guessed*: a tag that
does not determine a topic, or a set of tags that disagree, has to produce no label at all
rather than a plausible one. A silently wrong reference label would make the classifier look
accurate against nothing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from state_politics.analysis.validate_bills import (
    agreement_report,
    headline_replication_table,
    load_subject_map,
    normalize_tag,
    tag_replication,
    tag_replication_by_state,
    tag_topic,
)

TOPIC_NAMES = {1: "Macroeconomics", 6: "Education", 12: "Law, crime and justice"}
SUBJECT_MAP = {"education": 6, "schools": 6, "taxation": 1, "courts": 12}


def test_headline_replication_keeps_each_missing_source_verdict_unavailable():
    for missing_source in ("stated", "model", "tags"):
        platform = pd.DataFrame({
            "topic": [1, 6], "topic_name": ["Macroeconomics", "Education"],
            "D": [0.6, 0.4], "R": [0.7, 0.3],
        })
        model = pd.DataFrame({
            "topic": [1, 6, 1, 6], "party": ["D", "D", "R", "R"],
            "share": [0.8, 0.2, 0.9, 0.1], "n_bills": [8, 2, 9, 1],
        })
        tags = model.copy()
        if missing_source == "stated":
            platform.loc[platform["topic"] == 1, "R"] = float("nan")
        else:
            source = model if missing_source == "model" else tags
            source.loc[(source["party"] == "R") & (source["topic"] == 1), "share"] = (
                float("nan")
            )
        table = headline_replication_table(platform, model, tags).set_index(["party", "topic"])
        assert pd.isna(table.loc[("R", 1), "holds"])
        assert table.loc[("R", 6), "holds"]
        assert table.loc[("D", 1), "holds"]


def test_headline_replication_separates_absent_parties_from_absent_topics():
    platform = pd.DataFrame({
        "topic": [1], "topic_name": ["Macroeconomics"], "D": [1.0], "R": [1.0],
    })
    model = pd.DataFrame({
        "topic": [1], "party": ["D"], "share": [1.0], "n_bills": [2],
    })
    tags = pd.DataFrame({
        "topic": [6, 6], "topic_name": ["Education", "Education"],
        "party": ["D", "R"], "share": [1.0, 1.0], "n_bills": [3, 4],
    })
    table = headline_replication_table(platform, model, tags).set_index(["party", "topic"])
    assert len(table) == 4
    assert table.loc[("D", 6), "stated_share"] == 0.0
    assert table.loc[("D", 6), "model_share"] == 0.0
    assert table.loc[("D", 6), "tag_share"] == 1.0
    assert table.loc[("D", 6), "topic_name"] == "Education"
    assert table.loc["R", "model_share"].isna().all()
    assert table.loc["R", "holds"].isna().all()


def test_headline_replication_rejects_inconsistent_topic_names():
    for platform in (
        pd.DataFrame(columns=["topic", "topic_name", "D", "R"]),
        pd.DataFrame({
            "topic": [6], "topic_name": ["Education"], "D": [1.0], "R": [1.0],
        }),
    ):
        model = pd.DataFrame({
            "topic": [6], "topic_name": ["Schools"], "party": ["D"],
            "share": [1.0], "n_bills": [2],
        })
        tags = model.assign(topic_name="Education")
        with pytest.raises(ValueError, match="topic names disagree"):
            headline_replication_table(platform, model, tags)


@pytest.mark.parametrize("have_model_r", [True, False])
@pytest.mark.parametrize("prediction_only", [False, True])
def test_tag_replication_cli_matches_model_states_too(
    tmp_path, monkeypatch, capsys, have_model_r, prediction_only,
):
    from state_politics.analysis import revealed, validate_bills

    bills = pd.DataFrame({
        "state": ["TX", "TX", "VT", "VT"], "sponsor_party": ["D", "R", "D", "R"],
        "identifier": ["HB 1", "HB 2", "HB 3", "HB 4"], "year": [2024] * 4,
        "subject": ["Education"] * 4,
    })
    bills_path = tmp_path / "bills.parquet"
    bills.to_parquet(bills_path, index=False)
    platform = pd.DataFrame({
        "state": ["TX", "TX", "VT", "VT"], "party": ["D", "R", "D", "R"],
        "topic": [6] * 4, "share": [1.0] * 4, "era": ["2018-present"] * 4,
    })
    platform_path = tmp_path / "platform.csv"
    platform.to_csv(platform_path, index=False)
    model = pd.DataFrame({
        "state": ["TX", "TX", "VT"], "party": ["D", "R", "D"],
        "topic": [6] * 3, "topic_name": ["Education"] * 3,
        "share": [1.0] * 3, "n_bills": [1] * 3,
    })
    if not have_model_r:
        model = model.loc[model["party"] != "R"]
    model_path = tmp_path / "model.csv"
    model.to_csv(model_path, index=False)
    monkeypatch.setattr(validate_bills, "load_classifier", lambda *args: None)
    monkeypatch.setattr(validate_bills, "load_subject_map", lambda *args: SUBJECT_MAP)
    monkeypatch.setattr(
        revealed, "classify_bills",
        lambda frame, classifier: frame.assign(topic=12 if prediction_only else 6),
    )
    assert validate_bills.main([
        "--bills", str(bills_path), "--platform-by-org", str(platform_path),
        "--bill-by-state", str(model_path), "--out", str(tmp_path / "agreement.csv"),
    ]) == 0
    comparison = pd.read_csv(tmp_path / "headline_tag_replication.csv")
    replication = pd.read_csv(tmp_path / "bill_emphasis_by_tag.csv")
    agreement = pd.read_csv(tmp_path / "agreement.csv").set_index("topic")
    assert "nan%" not in capsys.readouterr().out
    if prediction_only:
        assert agreement.loc[12, "n_predicted"] == 4
        assert agreement.loc[12, "precision"] == 0.0
        assert pd.isna(agreement.loc[12, "agreement"])
    if have_model_r:
        assert set(comparison["n_states"]) == {1}
        assert set(replication["n_states"]) == {1}
        assert replication["n_bills"].sum() == 2
    else:
        assert comparison.empty
        assert replication.empty


def test_subject_agreement_and_replication_exclude_requests_but_keep_formal_abstentions():
    frame = pd.DataFrame({
        "state": ["MT"] * 3, "identifier": ["LC 239", "SB 6", "HB 117"],
        "subject": ["Taxation", "Education", "Education"],
        "topic": [None, 6, None], "sponsor_party": ["R"] * 3,
    })
    report = agreement_report(frame, SUBJECT_MAP, TOPIC_NAMES)
    assert report.topic.tolist() == [6]
    assert report.n.tolist() == [2] and report.n_abstained.tolist() == [1]
    for replicate, share_column in (
        (tag_replication, "tag_share"), (tag_replication_by_state, "share"),
    ):
        table = replicate(frame, SUBJECT_MAP, TOPIC_NAMES)
        assert table.topic.tolist() == [6]
        assert table.n_bills.tolist() == [2]
        assert table[share_column].tolist() == [1.0]


def test_normalize_tag_strips_state_reference_codes():
    """Tags carry state-specific trailing codes that would fragment the vocabulary."""
    assert normalize_tag("Resolutions--Congratulatory & Honorary (I0705)") == (
        "resolutions--congratulatory & honorary"
    )
    assert normalize_tag("  EDUCATION  ") == "education"
    assert normalize_tag("Health   and\tHealth Department") == "health and health department"


def test_tag_topic_resolves_a_single_agreed_topic():
    assert tag_topic("Education|Schools", SUBJECT_MAP) == 6
    assert tag_topic("EDUCATION", SUBJECT_MAP) == 6


def test_tag_topic_refuses_to_guess_when_tags_disagree():
    """A bill tagged both education and taxation has no single right answer."""
    assert tag_topic("Education|Taxation", SUBJECT_MAP) is None


def test_tag_topic_ignores_unmapped_tags_but_still_resolves():
    """An unmappable tag alongside a mappable one must not block the mappable one."""
    assert tag_topic("Memorials|Education", SUBJECT_MAP) == 6


def test_tag_topic_returns_none_for_absent_or_unmapped_tags():
    assert tag_topic("", SUBJECT_MAP) is None
    assert tag_topic(None, SUBJECT_MAP) is None
    assert tag_topic("Memorials|Rules", SUBJECT_MAP) is None


def test_agreement_report_separates_precision_from_recall():
    """Precision is what governs a share, so it must be reported independently.

    Here every education bill is found (recall 1.0) but a tax bill is also pulled in, so
    precision is lower -- exactly the asymmetry that inflated the housing share.
    """
    frame = pd.DataFrame([
        {"subject": "Education", "topic": 6},
        {"subject": "Schools", "topic": 6},
        {"subject": "Taxation", "topic": 6},
        {"subject": "Taxation", "topic": 1},
    ])
    report = agreement_report(frame, SUBJECT_MAP, TOPIC_NAMES).set_index("topic")

    assert report.loc[6, "agreement"] == 1.0
    assert report.loc[6, "n_predicted"] == 3
    assert round(report.loc[6, "precision"], 3) == round(2 / 3, 3)
    assert report.loc[6, "top_contaminant"].startswith("Macroeconomics")
    assert report.loc[1, "agreement"] == 0.5


@pytest.mark.parametrize("nullable", [False, True])
def test_agreement_retains_prediction_only_topics_without_inventing_reference_support(nullable):
    frame = pd.DataFrame({
        "state": ["TX", "TX", "TX", "TX", "MT"],
        "identifier": ["HB 1", "HB 2", "HB 3", "HB 4", "LC 123"],
        "subject": ["Education", "Education", "Taxation", "Unmapped", "Education"],
        "topic": [12, 12, None, 1, 1],
    })
    if nullable:
        frame["topic"] = frame["topic"].astype("Int64")

    report = agreement_report(frame, SUBJECT_MAP, TOPIC_NAMES).set_index("topic")

    assert set(report.index) == {1, 6, 12}
    assert report["n"].sum() == 3
    assert report["n_predicted"].sum() == 2
    assert report["agreed"].sum() == 0
    assert report.loc[12, "n"] == 0
    assert report.loc[12, "n_classified"] == report.loc[12, "n_abstained"] == 0
    assert report.loc[12, "n_predicted"] == 2
    assert report.loc[12, "precision"] == 0.0
    assert report.loc[12, "top_contaminant"] == "Education (2)"
    assert report.loc[12, ["agreement", "coverage", "agreement_when_classified"]].isna().all()
    assert report.loc[6, "agreement"] == 0.0
    assert report.loc[6, "coverage"] == 1.0
    assert pd.isna(report.loc[6, "precision"])
    assert report.loc[1, "n_abstained"] == 1
    assert report.loc[1, "coverage"] == 0.0
    assert pd.isna(report.loc[1, "agreement_when_classified"])


def test_tag_replication_uses_tags_not_the_model():
    """The replication must ignore any model column and label purely from tags."""
    frame = pd.DataFrame([
        {"subject": "Education", "sponsor_party": "D", "topic": 12},
        {"subject": "Education", "sponsor_party": "D", "topic": 12},
        {"subject": "Taxation", "sponsor_party": "D", "topic": 12},
        {"subject": "Courts", "sponsor_party": "R", "topic": 6},
    ])
    table = tag_replication(frame, SUBJECT_MAP, TOPIC_NAMES)
    democratic = table[table["party"] == "D"].set_index("topic")

    assert round(democratic.loc[6, "tag_share"], 3) == round(2 / 3, 3)
    assert table[table["party"] == "R"]["topic"].tolist() == [12]


def test_agreement_accounts_for_abstentions_in_the_reference_denominator():
    frame = pd.DataFrame([
        {"subject": "Education", "topic": 6},
        {"subject": "Education", "topic": None},
        {"subject": "Taxation", "topic": None},
        {"subject": "Unmapped", "topic": 6},
    ])
    report = agreement_report(frame, SUBJECT_MAP, TOPIC_NAMES).set_index("topic")
    assert report.loc[6, "n"] == 2
    assert report.loc[6, "agreement"] == 0.5
    assert report.loc[6, "agreement_when_classified"] == 1.0
    assert report.loc[6, "coverage"] == 0.5
    assert report.loc[1, "n_abstained"] == 1


def test_tag_replication_excludes_third_party_sponsors():
    """Shares are per major party; 'other' and unknown must not dilute a denominator."""
    frame = pd.DataFrame([
        {"subject": "Education", "sponsor_party": "D"},
        {"subject": "Education", "sponsor_party": "unknown"},
        {"subject": "Courts", "sponsor_party": "bipartisan"},
    ])
    table = tag_replication(frame, SUBJECT_MAP, TOPIC_NAMES)

    assert set(table["party"]) == {"D"}
    assert table["tag_share"].iloc[0] == 1.0


def test_tag_replication_by_state_preserves_equal_state_inputs():
    frame = pd.DataFrame(
        [
            {"state": "TX", "subject": "Education", "sponsor_party": "D"},
            {"state": "TX", "subject": "Education", "sponsor_party": "D"},
            {"state": "VT", "subject": "Taxation", "sponsor_party": "D"},
        ]
    )

    table = tag_replication_by_state(frame, SUBJECT_MAP, TOPIC_NAMES)

    assert table.groupby(["state", "party"])["share"].sum().eq(1.0).all()
    assert set(table["state"]) == {"TX", "VT"}


def test_shipped_map_only_uses_codes_from_the_taxonomy():
    """A typo'd topic code would silently score every bill in that topic as wrong."""
    from state_politics.analysis.taxonomy import load_topics

    valid = {topic.code for topic in load_topics()}
    unknown = {code for code in load_subject_map().values() if code not in valid}
    assert not unknown, f"subject map uses codes absent from conf/topics.yml: {sorted(unknown)}"


def test_shipped_map_tags_are_already_normalized():
    """An un-normalised key can never match, so it would silently do nothing."""
    bad = [tag for tag in load_subject_map() if normalize_tag(tag) != tag]
    assert not bad, f"tags in conf/subject_topic_map.yml need normalising: {bad}"

"""Tests for the bill-title classifier check against statehouse subject tags.

The rule this module protects is that the tag-derived label must never be *guessed*: a tag that
does not determine a topic, or a set of tags that disagree, has to produce no label at all
rather than a plausible one. A silently wrong reference label would make the classifier look
accurate against nothing.
"""

from __future__ import annotations

import pandas as pd

from state_politics.analysis.validate_bills import (
    agreement_report,
    load_subject_map,
    normalize_tag,
    tag_replication,
    tag_topic,
)

TOPIC_NAMES = {1: "Macroeconomics", 6: "Education", 12: "Law, crime and justice"}
SUBJECT_MAP = {"education": 6, "schools": 6, "taxation": 1, "courts": 12}


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

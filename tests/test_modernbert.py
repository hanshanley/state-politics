"""Decision, source-span, checkpoint and supervised-label safeguards without model downloads."""

import csv
import hashlib
import json
import re

import pytest

from state_politics.analysis import modernbert as modernbert_module
from state_politics.analysis.evaluate_topics import calibrate, join_predictions, metrics
from state_politics.analysis.evaluate_topics import main as evaluate_main
from state_politics.analysis.modernbert import (
    INPUT_CONSTRUCTION,
    MODEL_ID,
    MODEL_REVISION,
    WINDOWING,
    ModernBertClassifier,
    decide,
    model_input_ids,
    policy_tokens,
    policy_units,
    section_windows,
    token_windows,
)
from state_politics.analysis.prepare_topics import compatibility_flags, prepare
from state_politics.analysis.state_references import (
    ReferenceIndex,
    bind_florida,
    read_source_csv,
    source_profile,
)
from state_politics.analysis.taxonomy import DEFAULT_TOPICS_PATH, load_topics
from state_politics.analysis.train_topics import (
    label_support,
    load_examples,
    validate_source_reservation,
)
from state_politics.provenance import sha256_file


def test_external_state_csv_preserves_logical_records_and_rejects_malformed_sources(tmp_path):
    path = tmp_path / "state.csv"
    path.write_text('id,year,majortopic,Bill_Title\nHB 1,2019,3,"A title\ncontinued"\n')
    rows = read_source_csv(path, {"id", "year", "majortopic", "Bill_Title"})
    assert rows == [{"id": "HB 1", "year": "2019", "majortopic": "3",
                     "Bill_Title": "A title\ncontinued"}]
    assert source_profile(rows)["year_counts"] == {"2019": 1}
    path.write_text("id,year,majortopic,Bill_Title\nHB 1,2019,3\n")
    with pytest.raises(ValueError, match="logical CSV record 2"):
        read_source_csv(path, {"id"})
    path.write_text("id,id\none,two\n")
    with pytest.raises(ValueError, match="duplicate source columns"):
        read_source_csv(path, {"id"})


def test_external_state_binding_never_repairs_ids_or_certifies_matching_numeric_codes():
    rows = [
        {"id": key, "year": year, "majortopic": topic, "Bill_Title": ""}
        for key, year, topic in [
            ("HB 001", "2019", "3"), ("B 1", "2019", "3"),
            ("HB 1", "2020", "24"), ("HB 1", "2017", "3"),
        ]
    ]
    bills = [
        {"bill_id": "fl-regular", "state": "FL", "session_identifier": "2019",
         "identifier": "HB 1", "title": "Later source title", "year": 2020},
        {"bill_id": "fl-special", "state": "FL", "session_identifier": "2020A",
         "identifier": "HB 1", "title": "Special-session title", "year": 2020},
        {"bill_id": "other-state", "state": "GA", "session_identifier": "2020",
         "identifier": "HB 1", "title": "Other state title", "year": 2020},
    ]
    before = json.dumps([rows, bills], sort_keys=True)
    bound = bind_florida(rows, bills, {3})
    assert [row["link_status"] for row in bound] == [
        "unique_source_context", "unparsed_external_identifier",
        "missing_source_context", "outside_year_window",
    ]
    assert bound[0]["matched_bill_id"] == "fl-regular"
    assert bound[0]["source_title"] == ""
    assert bound[0]["candidate_title"] == "Later source title"
    assert bound[0]["candidate_title_sha256"] == hashlib.sha256(
        b"Later source title"
    ).hexdigest()
    assert {"external_title_missing", "external_subtopic_unavailable",
            "rubric_mapping_unreviewed", "annotation_provenance_unresolved",
            "candidate_title_version_unverified"} <= set(bound[0]["review_flags"])
    assert "unsupported_external_major" in bound[2]["review_flags"]
    for row in bound:
        assert not any(row[key] for key in (
            "training_admission", "evaluation_admission", "analytical_admission",
            "independent_gold",
        ))
        assert "topic" not in row
    assert json.dumps([rows, bills], sort_keys=True) == before


def test_external_state_binding_retains_both_sides_of_duplicate_contexts():
    rows = [{"id": "SB 792", "year": "2020", "majortopic": str(code), "Bill_Title": ""}
            for code in (3, 12)]
    bills = [{"state": "FL", "session_identifier": "2020", "identifier": "SB 792",
              "bill_id": key, "title": "Unresolved source context"} for key in ("b", "a")]
    bound = bind_florida(rows, bills, {3, 12})
    assert len(bound) == 2
    assert [row["source_major"] for row in bound] == ["3", "12"]
    assert [row["source_csv_record_number"] for row in bound] == [2, 3]
    for row in bound:
        assert row["link_status"] == "ambiguous_source_context"
        assert row["source_context_bill_ids"] == ["a", "b"]
        assert row["matched_bill_id"] is None and row["candidate_title"] is None
        assert "duplicate_external_context" in row["review_flags"]
    with pytest.raises(ValueError, match="duplicate Florida source bill ID"):
        bind_florida(rows, [bills[0], bills[0]], {3})


def test_external_state_overlap_keeps_all_witnesses_and_short_exact_copies():
    phrase = " ".join(f"word{number}" for number in range(35))
    variant = phrase + " more"
    unrelated = "distinct subject matter with entirely different evidence"
    index = ReferenceIndex([
        {"record_id": "short-a", "text": "HEALTH"},
        {"record_id": "short-b", "text": "Health!"},
        {"record_id": "prior-a", "text": phrase},
        {"record_id": "prior-b", "text": phrase},
        {"record_id": "different", "text": unrelated},
    ])
    assert index.overlaps("health") == {
        "exact_text_reference_ids": ["short-a", "short-b"], "near_text_reference_ids": [],
    }
    assert index.overlaps(variant) == {
        "exact_text_reference_ids": [], "near_text_reference_ids": ["prior-a", "prior-b"],
    }
    assert index.overlaps("a new topic") == {
        "exact_text_reference_ids": [], "near_text_reference_ids": [],
    }
    with pytest.raises(ValueError, match="reference text"):
        ReferenceIndex([{"record_id": "invalid", "text": ""}])


def test_windows_cover_every_token_without_silent_truncation():
    windows = token_windows(2351, 1000, 128)
    assert windows == [(0, 1000), (872, 1872), (1744, 2351)]
    assert set().union(*(set(range(start, end)) for start, end in windows)) == set(range(2351))
    assert token_windows(0, 1000, 128) == []
    with pytest.raises(ValueError):
        token_windows(100, 128, 128)


def test_decision_returns_one_topic_or_accounted_for_abstention():
    policy = dict(temperature=1, min_confidence=0.8, min_margin=0.2)
    assert decide([[8, 0], [7, 0]], [1, 2], **policy).topic == 1
    mixed = decide([[8, 0], [0, 8]], [1, 2], **policy)
    assert mixed.topic is None and mixed.abstention_reason == "mixed_chunk_topics"
    uncertain = decide([[0.1, 0]], [1, 2], **policy)
    assert uncertain.topic is None and uncertain.abstention_reason == "low_confidence"
    assert decide([], [1, 2], **policy).abstention_reason == "insufficient_evidence"
    with pytest.raises(ValueError, match="non-finite"):
        decide([[float("nan"), 0]], [1, 2], **policy)


@pytest.mark.parametrize(
    ("logits", "codes", "temperature", "scores", "topic", "reason"),
    [
        ([[10.0, 9.0]], [1, 2], 5e-324, [1.0, 0.0], 1, None),
        ([[1e308, 1e308]], [1, 2], 0.5, [0.5, 0.5], None, "low_confidence"),
        ([[-1e308, -1e308]], [1, 2], 0.5, [0.5, 0.5], None, "low_confidence"),
        (
            [[10.0, 0.0], [0.0, 10.0]], [1, 2], 5e-324,
            [0.5, 0.5], None, "mixed_chunk_topics",
        ),
        (
            [[0.0, 0.0, 10.0]], [1, 2, None], 5e-324,
            [0.0, 0.0, 1.0], None, "supervised_rejection",
        ),
    ],
)
def test_decision_keeps_finite_scores_when_temperature_scaling_overflows(
    logits, codes, temperature, scores, topic, reason,
):
    result = decide(
        logits, codes, temperature=temperature, min_confidence=0.8, min_margin=0.2,
    )
    assert result.scores == pytest.approx(scores)
    assert result.score == pytest.approx(max(scores))
    assert sum(result.scores) == pytest.approx(1.0)
    assert result.topic == topic
    assert result.abstention_reason == reason
    json.dumps(result.__dict__, allow_nan=False)


def test_supervised_rejection_is_not_counted_as_an_additional_topic():
    policy = dict(temperature=1, min_confidence=0.8, min_margin=0.2)
    rejected = decide([[0, 0, 12]], [1, 2, None], **policy)
    assert rejected.topic is None and rejected.candidate_topic is None
    assert rejected.abstention_reason == "supervised_rejection"
    assert rejected.scores[-1] > 0.99
    accepted = decide([[12, 0, 1]], [1, 2, None], **policy)
    assert accepted.topic == 1 and accepted.runner_up is None
    mixed = decide([[0, 0, 12], [12, 0, 0]], [1, 2, None], **policy)
    assert mixed.topic is None and mixed.abstention_reason == "mixed_chunk_topics"
    with pytest.raises(ValueError, match="label map"):
        decide([[0, 12, 0]], [1, None, 2], **policy)


def test_policy_units_retain_short_headings_and_all_substantive_text():
    text = "Health\n\n" + "Expand access to public health services. " * 8 + "\n\nEducation\n\n" + (
        "Improve public schools and support teachers. " * 8
    ) + "\n\nEnd note."
    units = policy_units(text)
    assert len(units) == 2
    assert units[0][2].startswith("Health")
    assert units[1][2].startswith("Education")
    assert units[1][2].endswith("End note.")
    covered = set()
    for start, end, unit in units:
        assert text[start:end] == unit
        covered.update(range(start, end))
    assert all(index in covered for index, char in enumerate(text) if not char.isspace())


def test_numbered_platform_planks_are_not_collapsed_into_page_sized_units():
    prefix = "Committee and contents\n\n1. First principle\n2. Second principle\n\n"
    policies = "".join(
        f"{number}. Policy {number}: " + "A complete policy commitment. " * 7 + "\n"
        for number in range(1, 25)
    )
    suffix = "\n1. Appendix resolution one.\n2. Appendix resolution two.\n"
    text = prefix + policies + suffix
    units = policy_units(text)
    numbered = [unit for _, _, unit in units if re.match(r"\d+\. Policy ", unit)]
    assert len(numbered) == 24
    assert numbered[0].startswith("1. Policy 1:")
    assert numbered[-1].startswith("24. Policy 24:")
    covered = set()
    for start, end, unit in units:
        assert text[start:end] == unit
        covered.update(range(start, end))
    assert all(i in covered for i, character in enumerate(text) if not character.isspace())


def test_short_or_nonconsecutive_numbering_does_not_imply_independent_planks():
    text = "1. A short condition.\n2. Another condition.\n\n" + "Explanation. " * 20
    assert len(policy_units(text)) == 1


def test_all_long_numbered_sections_are_split_not_only_the_longest():
    first = "".join(
        f"{number}. First-section policy: " + "A complete commitment. " * 7 + "\n"
        for number in range(1, 25)
    )
    interlude = "\n1. An appendix condition.\n2. Another condition.\n\n"
    second = "".join(
        f"{number}. Second-section policy: " + "Another complete commitment. " * 7 + "\n"
        for number in range(1, 27)
    )
    text = "Opening context.\n\n" + first + interlude + second + "\nClosing context."
    units = policy_units(text)
    first_units = [unit for _, _, unit in units if re.match(r"\d+\. First-section ", unit)]
    second_units = [unit for _, _, unit in units if re.match(r"\d+\. Second-section ", unit)]
    assert len(first_units) == 24
    assert len(second_units) == 26
    assert any("1. An appendix condition.\n2. Another condition." in unit
               for _, _, unit in units)
    covered = set()
    previous_end = 0
    for start, end, unit in units:
        assert previous_end <= start < end
        assert text[start:end] == unit
        covered.update(range(start, end))
        previous_end = end
    assert all(i in covered for i, character in enumerate(text) if not character.isspace())


def _cap_row(**updates):
    return {
        "id": "one", "bill_id": "115-HR-1", "year": "2016",
        "majortopic": "6", "subtopic": "600", "pap_majortopic": "6",
        "pap_subtopic": "600",
        "description": "We support expanding public school access with sustained funding "
        "for teachers and students.",
        **updates,
    }


def test_external_initialization_quarantines_incompatible_codes_and_preserves_migration():
    codes = {2, 3, 6, 23}
    assert compatibility_flags(_cap_row(), codes, 2000) == []
    assert "rights_reproductive_health_boundary" in compatibility_flags(
        _cap_row(majortopic="2", subtopic="202", pap_majortopic="2", pap_subtopic="202"),
        codes, 2000,
    )
    assert "major_subtopic_disagreement" in compatibility_flags(
        _cap_row(subtopic="300"), codes, 2000,
    )
    assert "source_code_versions_disagree" in compatibility_flags(
        _cap_row(pap_majortopic="3", pap_subtopic="300"), codes, 2000,
    )
    assert compatibility_flags(
        _cap_row(majortopic="23", subtopic="2300", pap_subtopic="609"), codes, 2000,
    ) == []


@pytest.mark.parametrize(("major", "subtopic", "flag"), [
    ("12", "1208", "adapted_family_boundary"),
    ("13", "1308", "adapted_child_care_leave_boundary"),
    ("14", "1405", "adapted_rural_development_boundary"),
    ("15", "1526", "adapted_sports_boundary"),
    ("20", "2030", "adapted_holiday_boundary"),
    ("21", "2101", "adapted_historic_site_boundary"),
])
def test_external_subtopics_with_adapted_scope_need_review(major, subtopic, flag):
    row = _cap_row(
        majortopic=major, subtopic=subtopic,
        pap_majortopic=major, pap_subtopic=subtopic,
    )
    assert compatibility_flags(row, {int(major)}, 2000) == [flag]


def test_external_family_boundary_is_quarantined_before_sampling(tmp_path):
    path = tmp_path / "source.csv"
    rows = [
        _cap_row(
            id="family", majortopic="12", subtopic="1208",
            pap_majortopic="12", pap_subtopic="1208",
            description="A bill to change family law and provide new procedures "
            "for divorce and child custody.",
        ),
        _cap_row(),
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    source = (path.name, "bill", "https://example.test/frozen.csv", sha256_file(path))
    prepared, report = prepare(
        tmp_path, [6, 12, 23], per_source_topic=1, min_year=2000, seed=1,
        reviewed=[], sources=[source],
    )
    assert [row["source_record_id"] for row in prepared] == ["one"]
    summary = report["sources"][0]
    assert summary["dispositions"]["quarantined"] == 1
    assert summary["quarantine_flags_overlapping"] == {"adapted_family_boundary": 1}


def test_external_corpus_is_checksum_bound_and_reserves_target_text_families(tmp_path):
    path = tmp_path / "source.csv"
    rows = [
        _cap_row(), _cap_row(id="duplicate"),
        _cap_row(id="bad", subtopic="300"),
        _cap_row(id="culture", majortopic="23", subtopic="2300", pap_subtopic="609",
                 description="We support funding public museums and local artistic "
                 "programs so communities can preserve cultural heritage."),
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    source = (path.name, "bill", "https://example.test/frozen.csv", sha256_file(path))
    target = _label("reviewed", rows[0]["description"] + " Today.", "dev")
    prepared, report = prepare(
        tmp_path, [3, 6, 23], per_source_topic=1, min_year=2000, seed=1,
        reviewed=[target], sources=[source],
    )
    assert [row["topic"] for row in prepared if row["split"] == "train"] == [23]
    assert prepared[0]["source_major"] == "23"
    assert prepared[0]["label_origin"] == "external_coded"
    assert prepared[-1]["reviewer_type"] == "assistant"
    summary = report["sources"][0]
    assert summary["n_raw"] == sum(summary["dispositions"].values()) == 4
    assert summary["dispositions"]["quarantined"] == 1
    assert summary["dispositions"]["exact_duplicate_or_target_overlap"] == 1
    assert summary["target_near_copy_candidates_rejected"] == 1
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        prepare(
            tmp_path, [3, 6, 23], per_source_topic=1, min_year=2000, seed=1,
            reviewed=[], sources=[source],
        )


def test_preparation_keeps_reviewed_rejection_separate_from_policy_topic_counts(tmp_path):
    target = _label(
        "honor", "Honoring a community volunteer.", topic=None,
        label_origin="reviewed_target", abstention_reason="non_policy",
    )
    rows, report = prepare(
        tmp_path, [1, 6], per_source_topic=1, min_year=2000, seed=1,
        reviewed=[target], sources=[],
    )
    assert rows == [target]
    assert report["training_topic_counts"] == {}
    assert report["training_abstention_count"] == 1


def test_missing_or_empty_checkpoint_never_falls_back_to_embeddings(tmp_path):
    topics = load_topics()
    with pytest.raises(FileNotFoundError, match="not an automatic fallback"):
        ModernBertClassifier(topics, tmp_path)
    manifest = {
        "schema_version": 1, "model_id": MODEL_ID, "base_revision": MODEL_REVISION,
        "taxonomy_sha256": sha256_file(DEFAULT_TOPICS_PATH),
        "topic_codes": [topic.code for topic in topics],
        "status": "provisional", "checkpoint_files": {},
    }
    (tmp_path / "training_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="provisional"):
        ModernBertClassifier(topics, tmp_path)
    with pytest.raises(ValueError, match="required model/tokenizer"):
        ModernBertClassifier(topics, tmp_path, allow_provisional=True)


@pytest.mark.parametrize("changes", [
    {"schema_version": 1},
    {"training_abstention_count": 0},
    {"training_abstention_count": True},
    {"output_codes": None},
])
def test_checkpoint_refuses_inconsistent_rejection_contract_before_weights(tmp_path, changes):
    topics = load_topics()
    codes = [topic.code for topic in topics]
    manifest = {
        "schema_version": 2, "model_id": MODEL_ID, "base_revision": MODEL_REVISION,
        "taxonomy_sha256": sha256_file(DEFAULT_TOPICS_PATH), "topic_codes": codes,
        "output_codes": [*codes, None], "training_abstention_count": 10,
        "status": "provisional", **changes,
    }
    (tmp_path / "training_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="output codes|rejection output"):
        ModernBertClassifier(topics, tmp_path, allow_provisional=True)


def _label(record_id, text, split="train", **updates):
    return {
        "record_id": record_id, "group_id": record_id, "split": split,
        "domain": "bill", "text": text, "source_url": "https://example.test/evidence",
        "label_origin": "external_coded" if split == "train" else "reviewed_target",
        "label_version": "test", "evidence_tier": "official_summary", "topic": 6,
        "reviewer_id": "synthetic-test-fixture", "reviewer_type": "assistant",
        "reviewed_on": "2026-10-18", "rationale": "Synthetic fixture, not evaluation gold.",
        **updates,
    }


def test_label_manifest_rejects_group_and_normalized_text_leakage(tmp_path):
    path = tmp_path / "labels.jsonl"
    for held_out in (
        _label("test", "Different school funding evidence", "test", group_id="train"),
        _label("test", "PUBLIC school funding!!!", "test"),
    ):
        rows = [_label("train", "Public school funding"), held_out]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with pytest.raises(ValueError, match="leakage"):
            load_examples(path, [1, 6])


def test_label_manifest_does_not_promote_predictions_to_independent_labels(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text(json.dumps(_label("one", "School funding", label_origin="model")) + "\n")
    with pytest.raises(ValueError, match="model guesses"):
        load_examples(path, [1, 6])


@pytest.mark.parametrize("split", ["train", "dev", "test", "challenge"])
@pytest.mark.parametrize("topic", [True, 1.0, 6.0])
def test_label_manifest_rejects_noninteger_topic_aliases(tmp_path, split, topic):
    path = tmp_path / "labels.jsonl"
    path.write_text(json.dumps(_label("one", "School funding", split, topic=topic)) + "\n")
    with pytest.raises(ValueError, match="row 1: invalid topic"):
        load_examples(path, [1, 6])


@pytest.mark.parametrize("split", ["train", "dev", "test", "challenge"])
@pytest.mark.parametrize("topic", [1, 6, None])
def test_label_manifest_preserves_integer_topics_and_explicit_rejections(tmp_path, split, topic):
    path = tmp_path / "labels.jsonl"
    path.write_text(json.dumps(_label(
        "one", "School funding", split, topic=topic,
        label_origin="reviewed_target", abstention_reason="non_policy",
    )) + "\n")
    row = load_examples(path, [1, 6])[0]
    assert row["topic"] == topic
    assert type(row["topic"]) is type(topic)


def _source_reservation(tmp_path):
    path = tmp_path / "reservation.json"
    path.write_text(json.dumps({"sources": [{
        "organization": "WA-R", "state": "WA", "party": "R",
        "source_sha256": "a" * 64, "document_text_sha256": "b" * 64,
    }]}))
    (tmp_path / "manifest.json").write_text(json.dumps({
        "files": {path.name: sha256_file(path)},
    }))
    return path


@pytest.mark.parametrize("identity", [
    {"state": "WA", "party": "R"},
    {"group_id": "platform-organization:WA-R"},
    {"organization": "WA-R"},
    {"source_sha256": "a" * 64},
    {"document_text_sha256": "b" * 64},
])
def test_reservation_excludes_alternate_versions_and_reidentified_sources(tmp_path, identity):
    row = _label(
        "alternate-edition", "A different edition with a different body.",
        domain="plank", label_origin="reviewed_target", state="KS", party="R",
        source_sha256="c" * 64, document_text_sha256="d" * 64,
    )
    if "group_id" in identity or "organization" in identity:
        row.pop("state")
        row.pop("party")
    row.update(identity)
    with pytest.raises(ValueError, match="reserved platform source"):
        validate_source_reservation([row], _source_reservation(tmp_path))


def test_reservation_does_not_exclude_bills_or_evaluation_or_external_national_groups(tmp_path):
    path = _source_reservation(tmp_path)
    rows = [
        _label("bill", "A bill from a shared snapshot.", source_sha256="a" * 64),
        _label("challenge", "Reserved evaluation policy.", "challenge", domain="plank",
               state="WA", party="R", source_sha256="a" * 64),
        _label("external", "Historical national platform policy.", domain="plank"),
        _label("target", "An unrelated state's policy.", domain="plank",
               label_origin="reviewed_target", state="KS", party="R",
               source_sha256="c" * 64, document_text_sha256="d" * 64),
    ]
    result = validate_source_reservation(rows, path)
    assert result["reserved_organizations"] == ["WA-R"]
    assert result["sha256"] == sha256_file(path)
    assert result["manifest_sha256"] == sha256_file(tmp_path / "manifest.json")


@pytest.mark.parametrize("identity", [
    {},
    {"state": "KS"},
    {"state": "KS", "party": "R", "group_id": "platform-organization:HI-R"},
])
def test_reservation_requires_consistent_reviewed_platform_identity(tmp_path, identity):
    row = _label("target", "Reviewed state policy.", domain="plank",
                 label_origin="reviewed_target", **identity)
    with pytest.raises(ValueError, match="organization|state/party"):
        validate_source_reservation([row], _source_reservation(tmp_path))


def test_training_rejects_reserved_or_corrupt_reservation_before_model_import(
    tmp_path, monkeypatch,
):
    import builtins
    from types import SimpleNamespace

    from state_politics.analysis.train_topics import train

    path = _source_reservation(tmp_path)
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps(_label(
        "reserved", "Alternate-version policy.", domain="plank",
        label_origin="reviewed_target", state="WA", party="R", source_sha256="c" * 64,
    )) + "\n")
    args = SimpleNamespace(
        labels=labels, topics=DEFAULT_TOPICS_PATH, source_reservation=path,
        out=tmp_path / "model",
    )
    original_import = builtins.__import__

    def no_model_import(name, *args, **kwargs):
        assert name not in ("torch", "transformers"), "model imported before reservation check"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_model_import)
    with pytest.raises(ValueError, match="reserved platform source"):
        train(args)
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        train(args)
    assert not args.out.exists()


@pytest.mark.parametrize("split", ["dev", "test", "challenge"])
def test_platform_source_cannot_cross_splits_under_different_urls_or_groups(tmp_path, split):
    rows = [
        _label(
            "train-span", "Expand public schools with stable funding.", domain="plank",
            label_origin="reviewed_target", source_sha256="a" * 64,
        ),
        _label(
            "held-out-span", "Protect clean drinking water for every community.", split,
            domain="plank", source_url="https://other.test/platform-copy.pdf",
            source_sha256="a" * 64, topic=1,
        ),
    ]
    path = tmp_path / "labels.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="platform source leakage"):
        load_examples(path, [1, 6])


@pytest.mark.parametrize("split", ["dev", "test", "challenge"])
def test_identical_platform_document_text_cannot_cross_distinct_body_splits(tmp_path, split):
    rows = [
        _label(
            "train-span", "Expand public schools with stable funding.", domain="plank",
            label_origin="reviewed_target", source_sha256="a" * 64,
            document_text_sha256="d" * 64,
        ),
        _label(
            "held-out-span", "Protect clean drinking water.", split,
            domain="plank", source_sha256="b" * 64, topic=1,
            document_text_sha256="d" * 64,
        ),
    ]
    path = tmp_path / "labels.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="platform document text leakage"):
        load_examples(path, [1, 6])


def test_platform_source_grouping_does_not_merge_shared_bill_snapshots(tmp_path):
    rows = [
        _label("train-span", "Expand public schools with stable funding.",
               domain="plank", label_origin="reviewed_target", source_sha256="a" * 64,
               document_text_sha256="d" * 64),
        _label("same-document", "Invest in teacher training programs.",
               domain="plank", label_origin="reviewed_target", source_sha256="a" * 64,
               document_text_sha256="d" * 64),
        _label("held-out", "Protect clean drinking water.", "dev",
               domain="plank", source_sha256="b" * 64, topic=1,
               document_text_sha256="e" * 64),
        _label("bill-train", "An act providing public school funding.",
               label_origin="reviewed_target", source_sha256="c" * 64,
               document_text_sha256="f" * 64),
        _label("bill-test", "An act to protect drinking water.", "test",
               source_sha256="c" * 64, topic=1, document_text_sha256="f" * 64),
    ]
    path = tmp_path / "labels.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert len(load_examples(path, [1, 6])) == 5


@pytest.mark.parametrize("source_hash", [None, "", "not-a-source-hash", 42])
def test_reviewed_platform_labels_require_a_source_body_hash(tmp_path, source_hash):
    row = _label("one", "Invest in public schools.", "dev",
                 domain="plank", source_sha256=source_hash)
    path = tmp_path / "labels.jsonl"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="platform source body hash"):
        load_examples(path, [1, 6])


@pytest.mark.parametrize("document_hash", ["", "not-a-document-hash", 42])
def test_optional_platform_document_text_hash_must_be_valid(tmp_path, document_hash):
    row = _label(
        "one", "Invest in public schools.", "dev", domain="plank",
        source_sha256="a" * 64, document_text_sha256=document_hash,
    )
    path = tmp_path / "labels.jsonl"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="platform document-text hash"):
        load_examples(path, [1, 6])


def test_training_rejection_requires_reviewed_evidence_and_an_admissible_reason(tmp_path):
    path = tmp_path / "labels.jsonl"
    valid = _label(
        "one", "Honoring a retiring volunteer.", topic=None,
        label_origin="reviewed_target", abstention_reason="non_policy",
    )
    path.write_text(json.dumps(valid) + "\n")
    assert load_examples(path, [1, 6])[0]["topic"] is None
    for update in (
        {"label_origin": "external_coded"},
        {"abstention_reason": "taxonomy_adjudication_pending"},
        {"reviewer_id": ""},
        {"text_sha256": "changed"},
    ):
        path.write_text(json.dumps({**valid, **update}) + "\n")
        with pytest.raises(ValueError):
            load_examples(path, [1, 6])


def test_support_audit_does_not_confuse_external_labels_rejections_or_sources_with_target_support():
    rows = [
        _label("external", "External bill policy."),
        _label("target", "State platform policy.", domain="plank",
               label_origin="reviewed_target", source_sha256="a" * 64, state="CA", party="D",
               document_text_sha256="d" * 64),
        _label("reject", "Committee roster.", domain="plank", label_origin="reviewed_target",
               source_sha256="a" * 64, state="CA", party="D",
               topic=None, abstention_reason="non_policy"),
        _label("heldout", "Other state platform policy.", "dev",
               domain="plank", source_sha256="b" * 64, state="TX"),
    ]
    report = {(row["split"], row["domain"]): row for row in label_support(rows, [1, 6])}
    external = report["train", "bill"]
    assert external["topics_without_reviewed_target_positives"] == [1, 6]
    assert external["topic_support"][1] == {
        "topic": 6, "external_coded": 1, "reviewed_target": 0,
    }
    platform = report["train", "plank"]
    assert platform["n_rows"] == 2
    assert platform["topic_support"][1]["reviewed_target"] == 1
    assert platform["reviewed_target_abstentions"] == {"non_policy": 1}
    assert len(platform["reviewed_platform_sources"]) == 1
    assert platform["reviewed_platform_sources"][0]["rows_missing_state_or_party"] == 0
    assert platform["reviewed_platform_sources"][0]["rows_missing_document_text_sha256"] == 1
    heldout = report["dev", "plank"]["reviewed_platform_sources"][0]
    assert heldout["parties_recorded"] == [None]
    assert heldout["rows_missing_state_or_party"] == 1
    assert heldout["rows_missing_document_text_sha256"] == 1
    assert report["dev", "bill"]["n_rows"] == 0
    assert report["test", "plank"]["n_rows"] == 0
    assert report["test", "plank"]["topics_without_reviewed_target_positives"] == [1, 6]


def test_rejection_outputs_survive_evidence_join_and_probability_evaluation():
    policy = dict(temperature=1, min_confidence=0.8, min_margin=0.2)
    labels = [
        {"record_id": "policy", "text_sha256": "one", "domain": "bill", "topic": 1},
        {"record_id": "honor", "text_sha256": "two", "domain": "bill", "topic": None},
    ]
    predictions = [
        {"record_id": row["record_id"], "input_sha256": row["text_sha256"],
         "input_domain": "bill", "output_codes": json.dumps([1, 2, None]),
         "logits": json.dumps([logits])}
        for row, logits in zip(labels, ([12, 0, 0], [0, 0, 12]), strict=True)
    ]
    joined = join_predictions(labels, predictions)
    report = metrics(joined, [1, 2], policy)
    assert report["decision_accuracy"] == 1
    assert report["n_classified"] == 1 and report["correct_abstention_count"] == 1
    assert report["abstention_reasons"] == {"supervised_rejection": 1}
    assert report["probability_metrics"]["n"] == 2
    assert report["probability_metrics"]["multiclass_log_loss"] < 0.001
    assert len(report["per_topic"]) == 2
    for mapping in ([1, 2], [1, None, 2], [1, 2, 3]):
        changed = [{**row} for row in joined]
        changed[1]["output_codes"] = mapping
        with pytest.raises(ValueError):
            metrics(changed, [1, 2], policy)


def test_evaluation_counts_abstentions_and_never_calibrates_on_test():
    rows = [
        {"split": "dev", "topic": 1, "logits": [[8, 0]]},
        {"split": "dev", "topic": 2, "logits": [[0.1, 0]]},
        {"split": "dev", "topic": None, "logits": [[8, 0], [0, 8]]},
    ]
    policy = dict(temperature=1, min_confidence=0.8, min_margin=0.2)
    report = metrics(rows, [1, 2], policy)
    assert report["n_eligible"] == 3 and report["n_abstained"] == 2
    assert report["all_eligible_topic_accuracy"] == 1 / 3
    assert report["classified_precision"] == 1
    assert report["decision_accuracy"] == 2 / 3
    assert report["per_topic"][1]["recall"] == 0
    with pytest.raises(ValueError, match="development"):
        calibrate(
            [{**rows[0], "split": "test"}], [1, 2],
            min_precision=0.9, min_coverage=0.1, min_support=1,
        )
    with pytest.raises(ValueError, match="predeclared constraints"):
        calibrate(rows, [1, 2], min_precision=0.99, min_coverage=1, min_support=3)


@pytest.mark.parametrize("logits", [None, {}, "", False, [None]])
def test_evaluation_rejects_malformed_logits_instead_of_scoring_an_abstention(logits):
    policy = dict(temperature=1, min_confidence=0.8, min_margin=0.2)
    with pytest.raises(ValueError, match="logits"):
        metrics([{"topic": None, "logits": logits}], [1, 2], policy)


def test_evaluation_retains_empty_logits_in_all_eligible_denominators():
    policy = dict(temperature=1, min_confidence=0.8, min_margin=0.2)
    report = metrics([
        {"topic": 1, "logits": [[8, 0]]},
        {"topic": 2, "logits": []},
        {"topic": None, "logits": []},
    ], [1, 2], policy)
    assert report["n_eligible"] == 3 and report["n_classified"] == 1
    assert report["all_eligible_topic_accuracy"] == 1 / 3
    assert report["classified_precision"] == 1
    assert report["decision_accuracy"] == 2 / 3
    assert report["abstention_reasons"] == {"insufficient_evidence": 2}
    assert report["probability_metrics"]["n"] == 1


def test_evaluation_refuses_predictions_for_changed_or_missing_evidence():
    labels = [{"record_id": "one", "text_sha256": "original", "domain": "bill"}]
    with pytest.raises(ValueError, match="IDs"):
        join_predictions(labels, [])
    with pytest.raises(ValueError, match="evidence mismatch"):
        join_predictions(labels, [{
            "record_id": "one", "input_sha256": "changed", "input_domain": "bill",
        }])


@pytest.mark.parametrize(("case", "expected_error"), [
    ("record", "record leakage"),
    ("group", "group leakage"),
    ("text", "text leakage"),
    ("platform", "platform source leakage"),
    ("calibration_platform", "platform source leakage"),
    ("reserved_development", "platform source leakage"),
    ("platform_document_text", "platform document text leakage"),
    ("calibration_document_text", "platform document text leakage"),
    ("reserved_development_document_text", "platform document text leakage"),
    ("shared_bill_snapshot", None),
    ("changed_training_labels", "binding"),
    ("different_model", "binding"),
    ("training_taxonomy", "binding"),
    ("missing_rejection_output", "binding"),
    ("extra_rejection_output", "binding"),
    ("matched_rejection_output", None),
])
def test_separate_evaluation_is_bound_to_original_training_evidence(
    tmp_path, case, expected_error,
):
    codes = [topic.code for topic in load_topics()]
    taxonomy_hash = sha256_file(DEFAULT_TOPICS_PATH)
    prior = _label("reserved", "Original school funding commitment.",
                   label_origin="reviewed_target", source_sha256="a" * 64)
    held_out = _label("heldout", "Distinct drinking water commitment.", "test",
                      source_sha256="b" * 64)
    if case == "record":
        held_out["record_id"] = prior["record_id"]
        held_out["group_id"] = "changed-group"
    elif case == "group":
        held_out["group_id"] = prior["group_id"]
    elif case == "text":
        held_out["text"] = "ORIGINAL school funding commitment!!!"
    elif case in ("platform", "calibration_platform", "reserved_development"):
        prior["domain"] = held_out["domain"] = "plank"
        held_out["source_sha256"] = prior["source_sha256"]
        held_out["source_url"] = "https://other.test/copied-platform.pdf"
        if case == "reserved_development":
            prior["split"] = "dev"
        elif case == "calibration_platform":
            held_out["split"] = "dev"
    elif case == "shared_bill_snapshot":
        held_out["source_sha256"] = prior["source_sha256"]
    elif case in (
        "platform_document_text", "calibration_document_text",
        "reserved_development_document_text",
    ):
        prior["domain"] = held_out["domain"] = "plank"
        prior["document_text_sha256"] = held_out["document_text_sha256"] = "d" * 64
        if case == "reserved_development_document_text":
            prior["split"] = "dev"
        elif case == "calibration_document_text":
            held_out["split"] = "dev"
    training_labels = tmp_path / "original-labels.jsonl"
    training_labels.write_text("".join(json.dumps(row) + "\n" for row in [
        _label("training", "Separate training evidence."), prior,
    ]))
    labels = tmp_path / "evaluation-labels.jsonl"
    labels.write_text(json.dumps(held_out) + "\n")
    training_manifest = tmp_path / "training_manifest.json"
    training_manifest.write_text(json.dumps({
        "topic_codes": codes, "labels_sha256": sha256_file(training_labels),
        "taxonomy_sha256": "wrong" if case == "training_taxonomy" else taxonomy_hash,
        **({"output_codes": [*codes, None]} if case in (
            "missing_rejection_output", "matched_rejection_output",
        ) else {}),
    }))
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "record_id": held_out["record_id"], "input_domain": held_out["domain"],
        "input_sha256": hashlib.sha256(held_out["text"].encode()).hexdigest(),
        "model_run": "wrong" if case == "different_model" else sha256_file(training_manifest),
        "taxonomy_sha256": taxonomy_hash,
        "logits": [[12 if code == 6 else 0 for code in codes]],
        **({
            "output_codes": [*codes, None],
            "logits": [[12 if code == 6 else 0 for code in [*codes, None]]],
        } if case in ("extra_rejection_output", "matched_rejection_output") else {}),
    }) + "\n")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(dict(temperature=1, min_confidence=0.8, min_margin=0.2)))
    if case == "changed_training_labels":
        training_labels.write_text(training_labels.read_text() + "\n")
    report = tmp_path / "evaluation.json"
    arguments = [
        "--labels", str(labels), "--predictions", str(predictions),
        "--training-manifest", str(training_manifest),
        "--training-labels", str(training_labels), "--split", held_out["split"],
        "--out", str(report),
    ]
    if case in ("calibration_platform", "calibration_document_text"):
        arguments += [
            "--calibrate", "--min-precision", "0.01", "--min-coverage", "0",
            "--min-support", "1",
        ]
    else:
        arguments += ["--policy", str(policy)]
    if expected_error == "binding":
        with pytest.raises(SystemExit):
            evaluate_main(arguments)
    elif expected_error:
        with pytest.raises(ValueError, match=expected_error):
            evaluate_main(arguments)
    else:
        assert evaluate_main(arguments) == 0
        assert json.loads(report.read_text())["metrics"]["n_correct_topic"] == 1
    if expected_error:
        assert not report.exists()


def test_section_windows_prefer_boundaries_without_losing_long_paragraph_tokens():
    text = "a" * 7 + "\n\n" + "b" * 30 + "\n\n" + "c" * 5
    offsets = [(i, i + 1) for i in range(len(text))]
    windows = section_windows(text, offsets, 12, 2)
    assert windows[0] == (0, 9)
    assert all(0 < end - start <= 12 for start, end in windows)
    assert set().union(*(set(range(start, end)) for start, end in windows)) == set(
        range(len(text))
    )
    assert section_windows("", [], 12, 2) == []
    with pytest.raises(ValueError):
        section_windows(text, offsets, 12, 12)


def test_training_and_inference_use_separately_tokenized_source_marker():
    class Tokenizer:
        def encode(self, text, *, add_special_tokens):
            assert not add_special_tokens
            return list(text.encode())

    prefix, text = policy_tokens(Tokenizer(), "School funding", "bill")
    assert bytes(prefix).decode() == "Bill policy:\n"
    assert bytes(text).decode() == "School funding"
    with pytest.raises(ValueError, match="domain"):
        policy_tokens(Tokenizer(), "School funding", "unknown")


def test_reviewed_labels_require_explicit_reviewer_provenance(tmp_path):
    row = _label("reviewed", "School funding", "dev")
    del row["reviewer_type"]
    path = tmp_path / "labels.jsonl"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="review provenance"):
        load_examples(path, [1, 6])


@pytest.mark.parametrize("input_changes", [
    {"construction": "unknown"}, {"windowing": "unknown"},
    {"max_tokens": 9000}, {"overlap": 1024},
])
def test_checkpoint_rejects_incompatible_input_contract_before_loading_weights(
    tmp_path, input_changes,
):
    topics = load_topics()
    codes = [topic.code for topic in topics]
    config = {
        "model_type": "modernbert", "architectures": ["ModernBertForSequenceClassification"],
        "id2label": {str(i): str(code) for i, code in enumerate(codes)},
    }
    files = {
        "config.json": json.dumps(config), "model.safetensors": "not real weights",
        "tokenizer.json": "{}", "tokenizer_config.json": "{}",
    }
    for name, value in files.items():
        (tmp_path / name).write_text(value)
    manifest = {
        "schema_version": 1, "model_id": MODEL_ID, "base_revision": MODEL_REVISION,
        "taxonomy_sha256": sha256_file(DEFAULT_TOPICS_PATH),
        "topic_codes": codes, "status": "provisional",
        "checkpoint_files": {name: sha256_file(tmp_path / name) for name in files},
        "input": {
            "construction": INPUT_CONSTRUCTION, "windowing": WINDOWING,
            "max_tokens": 1024, "overlap": 128, **input_changes,
        },
    }
    (tmp_path / "training_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="input construction/windowing"):
        ModernBertClassifier(topics, tmp_path, allow_provisional=True)


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085"])
def test_split_export_calibration_and_frozen_evaluation_handoff(tmp_path, monkeypatch, separator):
    codes = [topic.code for topic in load_topics()]
    taxonomy_hash = sha256_file(DEFAULT_TOPICS_PATH)
    evidence = [
        _label("training", "Distinct original training evidence."),
    ] + [
        _label(f"dev-{i}", f"Synthetic development evidence{separator}number {i}", "dev")
        for i in range(40)
    ] + [
        _label(f"test-{i}", f"Synthetic heldout evidence{separator}number {i}", "test")
        for i in range(4)
    ]
    labels = tmp_path / "labels.jsonl"
    labels.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in evidence))
    training_manifest = tmp_path / "training_manifest.json"
    training_manifest.write_text(json.dumps({
        "taxonomy_sha256": taxonomy_hash, "topic_codes": codes,
        "labels_sha256": sha256_file(labels),
    }))
    model_run = sha256_file(training_manifest)
    training_arguments = [
        "--training-manifest", str(training_manifest), "--training-labels", str(labels),
    ]
    called = []

    def retain_literal_unicode(path):
        predictions = [json.loads(line) for line in path.read_text().split("\n") if line]
        path.write_text("".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in predictions
        ))

    class SyntheticModel:
        def predict_records(self, texts, *, domain):
            called.extend(texts)
            return [{
                "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "input_domain": domain, "taxonomy_sha256": taxonomy_hash,
                "model_run": model_run, "base_model_run": model_run,
                "logits": [[12 if code == 6 else 0 for code in codes]],
            } for text in texts]

    monkeypatch.setattr(modernbert_module, "load_classifier", lambda *a: SyntheticModel())
    dev_predictions = tmp_path / "dev.jsonl"
    assert modernbert_module.main([
        "--inputs", str(labels), "--split", "dev", "--out", str(dev_predictions),
    ]) == 0
    assert called == [row["text"] for row in evidence if row["split"] == "dev"]
    assert not dev_predictions.with_suffix(".jsonl.part").exists()
    retain_literal_unicode(dev_predictions)
    calibration = tmp_path / "calibration.json"
    assert evaluate_main([
        "--labels", str(labels), "--predictions", str(dev_predictions), "--split", "dev",
        "--calibrate", "--min-precision", "0.8", "--min-coverage", "0.5",
        "--min-support", "20", "--out", str(calibration),
        *training_arguments,
    ]) == 0
    test_predictions = tmp_path / "test.jsonl"
    assert modernbert_module.main([
        "--inputs", str(labels), "--split", "test", "--out", str(test_predictions),
    ]) == 0
    retain_literal_unicode(test_predictions)
    report = tmp_path / "evaluation.json"
    arguments = [
        "--labels", str(labels), "--predictions", str(test_predictions), "--split", "test",
        "--policy", str(calibration), "--out", str(report),
        *training_arguments,
    ]
    assert evaluate_main(arguments) == 0
    result = json.loads(report.read_text())
    assert result["metrics"]["n_eligible"] == 4
    assert result["reviewer_types"] == {"assistant": 4}
    assert result["scientific_certification"] == "not_performed"
    assert result["training_manifest_sha256"] == model_run
    assert result["training_labels_sha256"] == sha256_file(labels)
    assert result["split_isolation"]["status"] == "passed"
    original = test_predictions.read_text()
    for field in ("taxonomy_sha256", "base_model_run"):
        predictions = [json.loads(line) for line in original.split("\n") if line]
        predictions[0][field] = "different"
        test_predictions.write_text("".join(json.dumps(row) + "\n" for row in predictions))
        with pytest.raises(SystemExit):
            evaluate_main(arguments)


@pytest.mark.parametrize("with_rejection", [False, True])
def test_real_local_checkpoint_loads_and_processes_all_chunks_without_legacy_apis(
    tmp_path, with_rejection,
):
    transformers = pytest.importorskip("transformers")
    tokenizers = pytest.importorskip("tokenizers")
    backend = tokenizers.Tokenizer(tokenizers.models.WordLevel({
        "[UNK]": 0, "[PAD]": 1, "[CLS]": 2, "[SEP]": 3, "school": 4, "funding": 5,
    }, unk_token="[UNK]"))
    backend.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    backend.post_processor = tokenizers.processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 2), ("[SEP]", 3)],
    )
    tokenizer = transformers.PreTrainedTokenizerFast(
        tokenizer_object=backend, unk_token="[UNK]", pad_token="[PAD]",
        cls_token="[CLS]", sep_token="[SEP]",
    )
    assert model_input_ids(
        tokenizer, tokenizer.encode("school funding", add_special_tokens=False),
    ) == tokenizer.encode("school funding", add_special_tokens=True)
    topics = load_topics()
    codes = [topic.code for topic in topics]
    outputs = [*codes, None] if with_rejection else codes
    names = [str(code) if code is not None else "ABSTAIN" for code in outputs]
    config = transformers.ModernBertConfig(
        vocab_size=6, hidden_size=16, intermediate_size=32,
        num_hidden_layers=2, num_attention_heads=2, max_position_embeddings=128,
        pad_token_id=1, bos_token_id=2, eos_token_id=3,
        id2label=dict(enumerate(names)),
        label2id={name: i for i, name in enumerate(names)},
    )
    if hasattr(config, "reference_compile"):
        config.reference_compile = False
    model = transformers.ModernBertForSequenceClassification(config)
    model.save_pretrained(tmp_path, safe_serialization=True)
    tokenizer.save_pretrained(tmp_path)
    manifest = {
        "schema_version": 2 if with_rejection else 1,
        "model_id": MODEL_ID, "base_revision": MODEL_REVISION,
        "taxonomy_sha256": sha256_file(DEFAULT_TOPICS_PATH),
        "topic_codes": codes, "status": "provisional",
        "output_codes": outputs, "training_abstention_count": 10 if with_rejection else 0,
        "checkpoint_files": {
            path.name: sha256_file(path) for path in tmp_path.iterdir() if path.is_file()
        },
        "input": {
            "construction": INPUT_CONSTRUCTION, "windowing": WINDOWING,
            "max_tokens": 64, "overlap": 8,
        },
        "decision": {"temperature": 1, "min_confidence": 1, "min_margin": 0},
        "decision_status": "uncalibrated_research_defaults",
    }
    (tmp_path / "training_manifest.json").write_text(json.dumps(manifest))
    classifier = ModernBertClassifier(topics, tmp_path, allow_provisional=True, device="cpu")
    records = classifier.predict_records(
        [("school funding " * 70).strip(), ""], domain="bill", batch_size=2,
    )
    assert records[0]["n_input_tokens"] == 140
    assert records[0]["n_discarded_tokens"] == 0
    assert len(json.loads(records[0]["logits"])) >= 2
    assert len(json.loads(records[0]["logits"])[0]) == len(outputs)
    assert json.loads(records[0]["output_codes"]) == outputs
    assert (records[0]["rejection_score"] is not None) == with_rejection
    assert records[0]["topic"] is None
    assert records[1]["abstention_reason"] == "insufficient_evidence"

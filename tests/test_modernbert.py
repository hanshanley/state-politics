"""Decision, source-span, checkpoint and supervised-label safeguards without model downloads."""

import csv
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
from state_politics.analysis.taxonomy import DEFAULT_TOPICS_PATH, load_topics
from state_politics.analysis.train_topics import load_examples
from state_politics.provenance import sha256_file


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


def test_evaluation_refuses_predictions_for_changed_or_missing_evidence():
    labels = [{"record_id": "one", "text_sha256": "original", "domain": "bill"}]
    with pytest.raises(ValueError, match="IDs"):
        join_predictions(labels, [])
    with pytest.raises(ValueError, match="evidence mismatch"):
        join_predictions(labels, [{
            "record_id": "one", "input_sha256": "changed", "input_domain": "bill",
        }])


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


def test_split_export_calibration_and_frozen_evaluation_handoff(tmp_path, monkeypatch):
    import hashlib

    codes = [topic.code for topic in load_topics()]
    taxonomy_hash = sha256_file(DEFAULT_TOPICS_PATH)
    evidence = [
        _label(f"dev-{i}", f"Synthetic development evidence number {i}", "dev")
        for i in range(40)
    ] + [
        _label(f"test-{i}", f"Synthetic heldout evidence number {i}", "test")
        for i in range(4)
    ]
    labels = tmp_path / "labels.jsonl"
    labels.write_text("".join(json.dumps(row) + "\n" for row in evidence))
    called = []

    class SyntheticModel:
        def predict_records(self, texts, *, domain):
            called.extend(texts)
            return [{
                "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "input_domain": domain, "taxonomy_sha256": taxonomy_hash,
                "model_run": "synthetic-run", "base_model_run": "synthetic-run",
                "logits": [[12 if code == 6 else 0 for code in codes]],
            } for text in texts]

    monkeypatch.setattr(modernbert_module, "load_classifier", lambda *a: SyntheticModel())
    dev_predictions = tmp_path / "dev.jsonl"
    assert modernbert_module.main([
        "--inputs", str(labels), "--split", "dev", "--out", str(dev_predictions),
    ]) == 0
    assert called == [row["text"] for row in evidence if row["split"] == "dev"]
    assert not dev_predictions.with_suffix(".jsonl.part").exists()
    calibration = tmp_path / "calibration.json"
    assert evaluate_main([
        "--labels", str(labels), "--predictions", str(dev_predictions), "--split", "dev",
        "--calibrate", "--min-precision", "0.8", "--min-coverage", "0.5",
        "--min-support", "20", "--out", str(calibration),
    ]) == 0
    test_predictions = tmp_path / "test.jsonl"
    assert modernbert_module.main([
        "--inputs", str(labels), "--split", "test", "--out", str(test_predictions),
    ]) == 0
    report = tmp_path / "evaluation.json"
    arguments = [
        "--labels", str(labels), "--predictions", str(test_predictions), "--split", "test",
        "--policy", str(calibration), "--out", str(report),
    ]
    assert evaluate_main(arguments) == 0
    result = json.loads(report.read_text())
    assert result["metrics"]["n_eligible"] == 4
    assert result["reviewer_types"] == {"assistant": 4}
    assert result["scientific_certification"] == "not_performed"
    original = test_predictions.read_text()
    for field in ("taxonomy_sha256", "base_model_run"):
        predictions = [json.loads(line) for line in original.splitlines()]
        predictions[0][field] = "different"
        test_predictions.write_text("".join(json.dumps(row) + "\n" for row in predictions))
        with pytest.raises(SystemExit):
            evaluate_main(arguments)


def test_real_local_checkpoint_loads_and_processes_all_chunks_without_legacy_apis(tmp_path):
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
    config = transformers.ModernBertConfig(
        vocab_size=6, hidden_size=16, intermediate_size=32,
        num_hidden_layers=2, num_attention_heads=2, max_position_embeddings=128,
        pad_token_id=1, bos_token_id=2, eos_token_id=3,
        id2label={i: str(code) for i, code in enumerate(codes)},
        label2id={str(code): i for i, code in enumerate(codes)},
    )
    if hasattr(config, "reference_compile"):
        config.reference_compile = False
    model = transformers.ModernBertForSequenceClassification(config)
    model.save_pretrained(tmp_path, safe_serialization=True)
    tokenizer.save_pretrained(tmp_path)
    manifest = {
        "schema_version": 1, "model_id": MODEL_ID, "base_revision": MODEL_REVISION,
        "taxonomy_sha256": sha256_file(DEFAULT_TOPICS_PATH),
        "topic_codes": codes, "status": "provisional",
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
    assert records[0]["topic"] is None
    assert records[1]["abstention_reason"] == "insufficient_evidence"

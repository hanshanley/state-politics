"""Inference accounting safeguards using tokenizer and model-output stubs only."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from state_politics.analysis.modernbert import ModernBertClassifier


class _Batch(dict):
    def to(self, device):
        return self


class _Tokenizer:
    cls_token_id = 101
    sep_token_id = 102

    def encode(self, text, *, add_special_tokens):
        return [101, 102] if add_special_tokens else [100] if text else []

    def num_special_tokens_to_add(self):
        return 2

    def __call__(self, text, **kwargs):
        offsets = [(i, i + 1) for i, char in enumerate(text) if not char.isspace()]
        return {"input_ids": [i + 1 for i, _ in offsets], "offset_mapping": offsets}

    def pad(self, examples, **kwargs):
        return _Batch(input_ids=[example["input_ids"] for example in examples])


class _Logits:
    def __init__(self, rows):
        self.rows = rows

    def float(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.rows


def _classifier(row_delta=0, *, mixed=False):
    classifier = object.__new__(ModernBertClassifier)
    classifier.tokenizer = _Tokenizer()
    classifier.device = "cpu"
    classifier.run_id = classifier.base_model_run = "stub-run"
    classifier.calibration_sha256 = None
    classifier.output_codes = [1, 2]
    classifier.manifest = {
        "input": {"max_tokens": 7, "overlap": 1},
        "decision": {"temperature": 1, "min_confidence": 0.8, "min_margin": 0.2},
        "status": "provisional",
        "decision_status": "uncalibrated_research_defaults",
        "taxonomy_sha256": "stub-taxonomy",
    }
    classifier.submitted = []

    def output(*, input_ids):
        classifier.submitted.extend(input_ids)
        rows = [[9.0, 0.0] for _ in range(max(0, len(input_ids) + row_delta))]
        if mixed and rows:
            rows[-1] = [0.0, 9.0]
        return SimpleNamespace(logits=_Logits(rows))

    classifier.model = output
    return classifier


@pytest.mark.parametrize("row_delta", [-1, 1])
def test_inference_rejects_missing_or_extra_window_outputs(row_delta):
    classifier = _classifier(row_delta)
    with pytest.raises(ValueError, match="one logit row per input window"):
        classifier.predict_records(["abcdefghi"], domain="bill", batch_size=2)


def test_inference_preserves_window_coverage_source_offsets_and_record_identity():
    classifier = _classifier()
    text = "  abcd\n\nefghi  "
    records = classifier.predict_records([text, "", " \n "], domain="bill", batch_size=2)
    record = records[0]
    spans = json.loads(record["chunk_spans"])
    assert spans == [[2, 6], [5, 11], [10, 13]]
    assert [
        token for window in classifier.submitted for token in window[2:-1]
    ] == [3, 4, 5, 6, 6, 9, 10, 11, 11, 12, 13]
    assert record["n_chunks"] == len(spans) == len(json.loads(record["logits"])) == 3
    assert record["n_input_tokens"] == 9 and record["n_discarded_tokens"] == 0
    assert record["input_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert record["topic"] == 1 and record["abstention_reason"] is None
    for source, empty in zip(["", " \n "], records[1:], strict=True):
        assert empty["input_sha256"] == hashlib.sha256(source.encode()).hexdigest()
        assert empty["topic"] is None and empty["abstention_reason"] == "insufficient_evidence"
        assert empty["n_input_tokens"] == empty["n_discarded_tokens"] == empty["n_chunks"] == 0
        assert json.loads(empty["chunk_spans"]) == json.loads(empty["logits"]) == []
    assert classifier.predict_records([], domain="bill") == []


def test_inference_retains_all_windows_when_topics_disagree():
    record = _classifier(mixed=True).predict_records(
        ["abcdefghi"], domain="bill", batch_size=2,
    )[0]
    assert record["topic"] is None and record["abstention_reason"] == "mixed_chunk_topics"
    assert record["n_chunks"] == len(json.loads(record["chunk_spans"])) == 3

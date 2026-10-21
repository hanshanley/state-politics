"""Metadata windows must cover the full source without loading encoder weights."""

import hashlib
import json
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from state_politics.analysis import study_token_plan as module
from state_politics.analysis.study_token_plan import build_plan, plan_view
from state_politics.provenance import sha256_file


class TinyTokenizer:
    cls_token_id = 1
    sep_token_id = 2

    def encode(self, text, *, add_special_tokens):
        if add_special_tokens:
            assert text == ""
            return [1, 2]
        return [7, 8] if text == "Bill policy:\n" else [ord(c) for c in text]

    def __call__(self, text, *, add_special_tokens, return_offsets_mapping, truncation):
        assert not add_special_tokens and return_offsets_mapping and not truncation
        return {
            "input_ids": [ord(c) for c in text],
            "offset_mapping": [(i, i + 1) for i in range(len(text))],
        }


def view(text):
    return {
        "view_id": "v1",
        "bill_id": "b1",
        "text": text,
        "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def test_long_unicode_source_is_fully_covered_in_bounded_windows():
    text = "A long source.\n\nAnother paragraph.\u2028Literal separator."
    result = plan_view(TinyTokenizer(), view(text), budget=10, overlap=2)
    assert result["token_ids"] == [ord(c) for c in text]
    assert result["n_input_tokens"] == result["n_unique_covered_tokens"] == len(text)
    assert result["n_discarded_tokens"] == 0
    assert result["n_windows"] > 1
    assert max(result["window_model_input_lengths"]) <= 10
    assert result["window_token_starts"][0] == 0
    assert result["window_token_ends"][-1] == len(text)
    assert not result["model_input_approved"]


def test_empty_view_is_explicitly_tokenized_without_inventing_a_window():
    result = plan_view(TinyTokenizer(), view(""), budget=10, overlap=2)
    assert result["n_input_tokens"] == result["n_windows"] == 0
    assert result["token_ids"] == result["window_model_input_lengths"] == []


@pytest.mark.parametrize("defect", ["hash", "budget", "offset", "token"])
def test_corrupt_source_or_unsafe_window_plan_fails(defect):
    tokenizer = TinyTokenizer()
    source = view("some text")
    if defect == "hash":
        source["input_sha256"] = "bad"
    elif defect in {"offset", "token"}:

        class BadTokenizer(TinyTokenizer):
            def __call__(self, text, **kwargs):
                result = super().__call__(text, **kwargs)
                if defect == "offset":
                    result["offset_mapping"][0] = (-1, 1)
                else:
                    result["input_ids"][0] = 1.0
                return result

        tokenizer = BadTokenizer()
    with pytest.raises(ValueError):
        plan_view(tokenizer, source, budget=4 if defect == "budget" else 10, overlap=2)


def fixture(tmp_path, monkeypatch):
    evidence, policy = tmp_path / "evidence", tmp_path / "policy"
    evidence.mkdir()
    policy.mkdir()
    pd.DataFrame(
        [
            view("all source tokens.\u2028Keep the full string."),
            {
                **view(""),
                "view_id": "v2",
                "bill_id": "b2",
            },
        ]
    ).to_parquet(evidence / "candidate_metadata_views.parquet", index=False)
    (evidence / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted",
                "artifacts": {
                    "candidate_metadata_views.parquet": {
                        "sha256": sha256_file(evidence / "candidate_metadata_views.parquet"),
                    }
                },
            }
        )
    )
    for name in ("tokenizer.json", "tokenizer_config.json", "config.json"):
        (policy / name).write_text("{}")
    (policy / "report.json").write_text(
        json.dumps(
            {
                "tokenizer_model_id": "answerdotai/ModernBERT-base",
                "tokenizer_base_revision": "8949b909ec900327062f0ebf497f51aef5e6f0c8",
                "model_token_budget": 10,
                "source_token_budget": 6,
                "overlap_tokens": 2,
            }
        )
    )
    (policy / "manifest.json").write_text(
        json.dumps(
            {
                "files": {p.name: sha256_file(p) for p in policy.iterdir()},
            }
        )
    )
    monkeypatch.setattr(module, "POLICY_MANIFEST_SHA256", sha256_file(policy / "manifest.json"))

    def load(path, **kwargs):
        assert path == policy
        assert kwargs == {"local_files_only": True, "trust_remote_code": False, "use_fast": True}
        return TinyTokenizer()

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoTokenizer=SimpleNamespace(from_pretrained=load),
        ),
    )
    return evidence, policy


def test_persistent_full_token_plan_is_bound_and_overwrite_rejected(tmp_path, monkeypatch):
    evidence, policy = fixture(tmp_path, monkeypatch)
    out = tmp_path / "out"
    report = build_plan(evidence, policy, out)
    assert report["n_views"] == 2
    assert report["n_multichunk_views"] == 1
    assert report["n_discarded_tokens"] == report["model_forward_passes"] == 0
    rows = pd.read_parquet(out / "token_window_plan.parquet")
    assert len(rows) == 2
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["inputs_unchanged"]
    for name, binding in manifest["artifacts"].items():
        assert sha256_file(out / name) == binding["sha256"]
    with pytest.raises(FileExistsError):
        build_plan(evidence, policy, out)


def test_modified_tokenizer_file_rejects_before_output(tmp_path, monkeypatch):
    evidence, policy = fixture(tmp_path, monkeypatch)
    (policy / "tokenizer.json").write_text('{"changed": true}')
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="policy checksum"):
        build_plan(evidence, policy, out)
    assert not out.exists()

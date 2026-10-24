import copy
from types import SimpleNamespace

import pytest
import torch

from state_politics.analysis.context_profiles import (
    encode_window_batches,
    encoder_window_key,
    profile_windows,
)


class Batch(dict):
    def to(self, device):
        return Batch({key: value.to(device) for key, value in self.items()})


class Tokenizer:
    cls_token_id, sep_token_id = 101, 102

    def encode(self, text, add_special_tokens=False):
        tokens = [ord(character) % 11 + 10 for character in text]
        return [101, *tokens, 102] if add_special_tokens else tokens

    def num_special_tokens_to_add(self):
        return 2

    def pad(self, rows, **kwargs):
        width = max(len(row["input_ids"]) for row in rows)
        return Batch(
            {
                "input_ids": torch.tensor(
                    [row["input_ids"] + [0] * (width - len(row["input_ids"])) for row in rows]
                ),
                "attention_mask": torch.tensor(
                    [
                        [1] * len(row["input_ids"]) + [0] * (width - len(row["input_ids"]))
                        for row in rows
                    ]
                ),
            }
        )


def document(text, size, overlap):
    tokenizer = Tokenizer()
    return profile_windows(
        tokenizer,
        text,
        tokenizer.encode(text),
        [(i, i + 1) for i in range(len(text))],
        max_tokens=size,
        overlap=overlap,
    )


def test_longer_profile_preserves_every_token_wrapper_and_original_unicode_characters():
    text = ("Complete\u2028source\u2029text.\n\n" * 15) + "final clause"
    short, long = document(text, 32, 3), document(text, 128, 16)
    assert len(long["encoder_inputs"]) < len(short["encoder_inputs"])
    for result in (short, long):
        assert result["n_input_tokens"] == len(text) and result["n_discarded_tokens"] == 0
        covered = {i for left, right in result["token_spans"] for i in range(left, right)}
        assert covered == set(range(len(text)))
        assert result["chunk_spans"][-1][-1] == len(text)
        assert all(
            ids[0] == 101 and ids[-1] == 102 and len(ids) <= result["max_tokens"]
            for ids in result["encoder_inputs"]
        )


def test_exact_window_cache_does_not_reuse_short_document_logits_for_different_long_windows():
    text = "complete source " * 20
    short, long = document(text, 32, 3), document(text, 128, 16)
    model, source = "a" * 64, "b" * 64
    old = encoder_window_key(model, source, short["token_spans"][0], short["encoder_inputs"][0])
    new = encoder_window_key(model, source, long["token_spans"][0], long["encoder_inputs"][0])
    assert old != new
    one, two = document("short", 32, 3), document("short", 128, 16)
    assert encoder_window_key(model, source, one["token_spans"][0], one["encoder_inputs"][0]) == (
        encoder_window_key(model, source, two["token_spans"][0], two["encoder_inputs"][0])
    )
    assert encoder_window_key(
        "c" * 64, source, one["token_spans"][0], one["encoder_inputs"][0]
    ) != (encoder_window_key(model, source, one["token_spans"][0], one["encoder_inputs"][0]))


def test_bounded_batches_preserve_original_indices_and_do_not_mutate_training_manifest():
    class Model:
        def __call__(self, input_ids, attention_mask):
            values = (input_ids * attention_mask).sum(dim=1).float()
            return SimpleNamespace(logits=torch.stack([values, -values, values * 0], dim=1))

    classifier = SimpleNamespace(
        tokenizer=Tokenizer(),
        model=Model(),
        output_codes=[1, 2, None],
        device="cpu",
        manifest={"input": {"max_tokens": 32, "overlap": 3}},
    )
    before = copy.deepcopy(classifier.manifest)
    windows = [[101, 10, 102], [101, 10, 11, 12, 102], [101, 10, 11, 102]]
    batches = list(encode_window_batches(classifier, windows, batch_size=2, padded_token_budget=8))
    actual = {
        index: logits
        for batch in batches
        for index, logits in zip(batch["indices"], batch["logits"], strict=True)
    }
    assert set(actual) == {0, 1, 2}
    assert all(batch["padded_tokens"] <= 8 for batch in batches)
    assert [actual[i][0] for i in range(3)] == [sum(row) for row in windows]
    assert classifier.manifest == before


@pytest.mark.parametrize("size,overlap", [(31, 0), (8193, 0), (32, 30), (32, -1)])
def test_invalid_context_limits_fail_explicitly(size, overlap):
    with pytest.raises(ValueError):
        document("complete source", size, overlap)

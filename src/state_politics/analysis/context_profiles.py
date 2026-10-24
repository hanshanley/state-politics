"""Explicit inference-window experiments without changing the trained checkpoint."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time

from state_politics.analysis.modernbert import (
    model_input_ids,
    policy_tokens,
    section_windows,
)


def profile_windows(tokenizer, text, ids, offsets, *, max_tokens, overlap):
    """Use the frozen tokenizer/wrappers and prove complete token coverage."""
    if (
        type(max_tokens) is not int
        or not 32 <= max_tokens <= 8192
        or type(overlap) is not int
        or not isinstance(text, str)
        or not ids
        or len(ids) != len(offsets)
        or any(type(token) is not int or token < 0 for token in ids)
        or any(len(pair) != 2 or not 0 <= pair[0] <= pair[1] <= len(text) for pair in offsets)
    ):
        raise ValueError("invalid complete context-profile input")
    prefix, _ = policy_tokens(tokenizer, "", "bill")
    budget = max_tokens - len(prefix) - tokenizer.num_special_tokens_to_add()
    spans = section_windows(text, offsets, budget, overlap)
    covered = 0
    windows, characters = [], []
    for left, right in spans:
        if not 0 <= left <= covered < right <= len(ids):
            raise ValueError("context profile loses or repeats a complete token interval")
        covered = right
        values = model_input_ids(tokenizer, prefix + ids[left:right])
        if len(values) > max_tokens:
            raise ValueError("context profile exceeds its declared encoder limit")
        windows.append(values)
        characters.append([offsets[left][0], offsets[right - 1][1]])
    if covered != len(ids):
        raise ValueError("context profile discards source tokens")
    return {
        "max_tokens": max_tokens,
        "overlap": overlap,
        "n_input_tokens": len(ids),
        "n_discarded_tokens": 0,
        "token_spans": [list(span) for span in spans],
        "chunk_spans": characters,
        "encoder_inputs": windows,
    }


def encoder_window_key(model_run, input_sha256, span, token_ids):
    """Reuse only the exact bound document interval and complete encoder input."""
    if (
        not all(
            type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value)
            for value in (model_run, input_sha256)
        )
        or len(span) != 2
        or any(type(value) is not int for value in span)
        or not 0 <= span[0] < span[1]
        or not token_ids
        or any(type(value) is not int or value < 0 for value in token_ids)
    ):
        raise ValueError("invalid encoder-window cache identity")
    value = json.dumps(
        [model_run, input_sha256, list(span), list(token_ids)], separators=(",", ":")
    ).encode()
    return hashlib.sha256(value).hexdigest()


def encode_window_batches(classifier, windows, *, batch_size, padded_token_budget):
    """Yield durable-cache-ready batches; longest first exposes resource limits early."""
    import torch

    if (
        type(batch_size) is not int
        or batch_size < 1
        or type(padded_token_budget) is not int
        or padded_token_budget < 1
        or any(not row or len(row) > padded_token_budget for row in windows)
    ):
        raise ValueError("invalid bounded context-profile batch")
    ordered = sorted(enumerate(windows), key=lambda item: len(item[1]), reverse=True)
    cursor = 0
    while cursor < len(ordered):
        stop = cursor + 1
        width = len(ordered[cursor][1])
        while (
            stop < len(ordered)
            and stop - cursor < batch_size
            and (stop - cursor + 1) * width <= padded_token_budget
        ):
            stop += 1
        batch = ordered[cursor:stop]
        encoded = classifier.tokenizer.pad(
            [{"input_ids": values} for _, values in batch],
            padding=True,
            return_attention_mask=True,
            return_tensors="pt",
        ).to(classifier.device)
        if tuple(encoded["input_ids"].shape) != (len(batch), width) or tuple(
            encoded["attention_mask"].shape
        ) != (len(batch), width):
            raise ValueError("context-profile padding changed the declared batch")
        started = time.perf_counter()
        with torch.inference_mode():
            logits = classifier.model(**encoded).logits.float().cpu().tolist()
        seconds = time.perf_counter() - started
        if len(logits) != len(batch) or any(
            len(row) != len(classifier.output_codes)
            or not all(math.isfinite(value) for value in row)
            for row in logits
        ):
            raise ValueError("context encoder returned invalid complete logit rows")
        yield {
            "indices": [index for index, _ in batch],
            "logits": logits,
            "input_lengths": [len(values) for _, values in batch],
            "padded_length": width,
            "padded_tokens": width * len(batch),
            "encoder_seconds": seconds,
        }
        cursor = stop

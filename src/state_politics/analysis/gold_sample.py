"""Deterministic sampling frame for manually labelled platform planks."""

from __future__ import annotations

import numpy as np

from .taxonomy import segment_planks

DEFAULT_SAMPLE_SEED = 20260729
DEFAULT_SAMPLE_SIZE = 50

__all__ = [
    "DEFAULT_SAMPLE_SEED",
    "DEFAULT_SAMPLE_SIZE",
    "build_sampling_frame",
    "sample_frame",
]


def build_sampling_frame(platforms):
    """All segmented planks from confirmed documents dated 2018 onward."""
    import pandas as pd

    rows = []
    confirmed = platforms[
        platforms["confirmed"]
        & (pd.to_numeric(platforms["year"], errors="coerce") >= 2018)
    ].reset_index(drop=True)
    for document_index, document in confirmed.iterrows():
        for plank in segment_planks(document["text"] or "", document_index):
            rows.append(
                {
                    "source_document_index": document_index,
                    "source_document_sha256": document["sha256"],
                    "source_url": document["url"],
                    "state": document["state"],
                    "party": document["party"],
                    "year": document["year"],
                    "plank_index": plank.plank_index,
                    "n_words": plank.n_words,
                    "text": plank.text,
                }
            )
    return pd.DataFrame(rows)


def sample_frame(frame, *, seed: int, size: int):
    """Sample stable row positions from a deterministically sorted frame."""
    if size > len(frame):
        raise ValueError(f"requested {size} planks from a frame of {len(frame)}")
    ordered = frame.sort_values(
        ["state", "party", "year", "source_document_sha256", "plank_index", "text"],
        kind="stable",
    ).reset_index(drop=True)
    positions = np.random.default_rng(seed).choice(len(ordered), size=size, replace=False)
    sample = ordered.iloc[np.sort(positions)].copy().reset_index(drop=True)
    sample.insert(0, "sample_index", range(len(sample)))
    sample["gold_topic"] = ""
    return sample

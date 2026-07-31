#!/usr/bin/env python3
"""Generate a deterministic, unlabeled plank-labeling template.

This never overwrites the existing hand-labelled gold snapshot. It records enough source
metadata to trace every candidate row to a fetched platform document.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from state_politics.analysis.taxonomy import segment_planks

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEED = 20260729
DEFAULT_SIZE = 50


def build_sampling_frame(platforms: pd.DataFrame) -> pd.DataFrame:
    """All segmented planks from confirmed documents dated 2018 onward."""
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


def sample_frame(frame: pd.DataFrame, *, seed: int, size: int) -> pd.DataFrame:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--platforms", default=ROOT / "data/processed/platforms_2018_present.parquet"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    parser.add_argument(
        "--out", default=ROOT / "data/processed/plank_topics_labeling_template.csv"
    )
    args = parser.parse_args(argv)

    frame = build_sampling_frame(pd.read_parquet(args.platforms))
    sample = sample_frame(frame, seed=args.seed, size=args.size)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(out, index=False)
    print(f"sampling frame: {len(frame):,} planks")
    print(f"sample:         {len(sample)} planks (seed {args.seed})")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

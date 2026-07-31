#!/usr/bin/env python3
"""Generate a deterministic, unlabeled plank-labeling template.

This never overwrites the existing hand-labelled gold snapshot. It records enough source
metadata to trace every candidate row to a fetched platform document.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from state_politics.analysis.gold_sample import (
    DEFAULT_SAMPLE_SEED,
    DEFAULT_SAMPLE_SIZE,
    build_sampling_frame,
    sample_frame,
)

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--platforms", default=ROOT / "data/processed/platforms_2018_present.parquet"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SAMPLE_SEED)
    parser.add_argument("--size", type=int, default=DEFAULT_SAMPLE_SIZE)
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

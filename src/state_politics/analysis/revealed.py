"""Compare what state parties *say* with what their legislators *file*.

This is the comparison the whole project was built for. Platform emphasis is what a state party
organization declares matters; bill emphasis is what its legislators actually spend the session
filing. The two are produced independently -- different sources, different authors, different
incentives -- and are made comparable only by being classified into the same taxonomy.

Both are measured as **share**: share of platform planks, and share of sponsored bills. Share
rather than count, because states differ enormously in both platform length and legislative
volume (New York files over 100,000 bills in this window and Wyoming a small fraction of
that), so
raw counts would measure institutional throughput rather than priority.

Caveats that belong next to any number produced here
----------------------------------------------------
* Both sides are restricted to the same window. The platform side uses 2018-present planks
  only; pooling the full 1990-2026 corpus against a 2018-2026 bill window would compare
  different eras, and most of the plank corpus predates 2018.
* Bills are classified from their **titles**, which are short and often procedural. That is a
  noisier signal than a platform plank, and the validation figures reported by
  :mod:`state_politics.analysis.validate` are measured on planks, not titles.
* A bill is attributed to a party by its primary sponsors; roughly a fifth cannot be resolved
  to a party at all and are excluded rather than guessed at.
* Filing a bill is not passing one. This measures agenda, not achievement.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .taxonomy import DEFAULT_TOPICS_PATH, EmbeddingClassifier, load_topics

__all__ = ["classify_bills", "divergence_table"]

#: Bill titles handed to the classifier per pass. Bounds peak memory on a machine whose RAM is
#: mostly spoken for; the classifier itself slices again internally.
_BILL_SLICE = 100_000


def classify_bills(bills, classifier: EmbeddingClassifier, *, batch_size: int = 512,
                   min_similarity: float = 0.20, min_title_chars: int = 20):
    """Classify bills by title. Returns the frame with ``topic`` and ``similarity`` columns.

    Very short titles ("Relating to taxation.") carry too little signal to place, and are left
    unclassified rather than assigned on the strength of one word.
    """
    import numpy as np

    # Written to keep peak memory low rather than to read prettily: this runs over ~880k bill
    # titles, and the obvious version (copy the frame, materialise every title, keep a Python
    # list of result tuples) was repeatedly OOM-killed. Nothing here holds more than one slice
    # of embeddings plus two flat arrays.
    frame = bills
    titles = frame["title"].fillna("").astype(str).to_numpy()
    long_enough = np.fromiter((len(t) >= min_title_chars for t in titles),
                              dtype=bool, count=len(titles))
    usable = np.flatnonzero(long_enough)

    codes = np.full(len(titles), np.nan, dtype=float)
    scores = np.zeros(len(titles), dtype=float)
    for start in range(0, len(usable), _BILL_SLICE):
        index = usable[start:start + _BILL_SLICE]
        predictions = classifier.predict_many(
            [titles[i] for i in index], batch_size=batch_size, min_similarity=min_similarity,
        )
        for position, (code, similarity, _) in zip(index, predictions, strict=True):
            if code is not None:
                codes[position] = code
            scores[position] = similarity
        del predictions

    return frame.assign(topic=codes, similarity=np.round(scores, 4))


def divergence_table(platform_emphasis, bill_emphasis):
    """Join stated and revealed emphasis and report the gap between them, per party per topic.

    ``stated_minus_revealed`` is positive where a party's platforms give a topic more room than
    its legislators' bills do.
    """
    import pandas as pd

    stated = platform_emphasis.melt(
        id_vars=["topic", "topic_name"], value_vars=["D", "R"],
        var_name="party", value_name="stated_share",
    )
    merged = stated.merge(
        bill_emphasis.rename(columns={"share": "revealed_share"})[
            ["topic", "party", "revealed_share", "n_bills"]
        ],
        on=["topic", "party"], how="outer",
    )
    merged["stated_share"] = merged["stated_share"].fillna(0.0)
    merged["revealed_share"] = merged["revealed_share"].fillna(0.0)
    merged["stated_minus_revealed"] = merged["stated_share"] - merged["revealed_share"]
    names = (
        pd.concat([platform_emphasis[["topic", "topic_name"]]])
        .drop_duplicates().set_index("topic")["topic_name"]
    )
    merged["topic_name"] = merged["topic"].map(names)
    return merged.sort_values(["party", "stated_minus_revealed"], ascending=[True, False])


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bills", default="data/processed/bills.parquet")
    # Default to the era-restricted table: comparing 2018-2026 bills against a platform
    # average that is mostly pre-2018 would not be a like-for-like comparison.
    parser.add_argument("--platform-emphasis",
                        default="data/processed/emphasis_by_party_2018_present.csv")
    parser.add_argument("--topics", default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--out-dir", default="data/processed")
    args = parser.parse_args(argv)

    topics = load_topics(args.topics)
    classifier = EmbeddingClassifier(topics)
    print(f"model {classifier.model_name} on device {classifier.device}")

    bills = pd.read_parquet(args.bills, columns=["state", "year", "title", "sponsor_party"])
    total = len(bills)
    major = bills[bills["sponsor_party"].isin(["D", "R"])].rename(
        columns={"sponsor_party": "party"}
    ).reset_index(drop=True)
    del bills  # the unattributed two-thirds are never used again
    print(f"bills with a party attribution: {len(major):,} of {total:,}")

    classified = classify_bills(major, classifier)
    unclassified = int(classified["topic"].isna().sum())
    print(f"classified: {len(classified) - unclassified:,} "
          f"({unclassified:,} unclassified or title too short)")

    named = {topic.code: topic.name for topic in topics}
    usable = classified[classified["topic"].notna()]
    counts = usable.groupby(["party", "topic"]).size().rename("n_bills").reset_index()
    counts["share"] = counts["n_bills"] / counts.groupby("party")["n_bills"].transform("sum")
    counts["topic_name"] = counts["topic"].map(named)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    counts.to_csv(out_dir / "bill_emphasis_by_party.csv", index=False)

    by_state = usable.groupby(["state", "party", "topic"]).size().rename("n_bills").reset_index()
    by_state["share"] = by_state["n_bills"] / by_state.groupby(["state", "party"])[
        "n_bills"].transform("sum")
    by_state["topic_name"] = by_state["topic"].map(named)
    by_state.to_csv(out_dir / "bill_emphasis_by_state.csv", index=False)

    platform = pd.read_csv(args.platform_emphasis)
    divergence = divergence_table(platform, counts)
    divergence.to_csv(out_dir / "stated_vs_revealed.csv", index=False)

    print("\nlargest gaps between what a party says and what it files:")
    display = divergence.copy()
    for column in ("stated_share", "revealed_share", "stated_minus_revealed"):
        display[column] = (display[column] * 100).round(1)
    for party in ("D", "R"):
        subset = display[display["party"] == party]
        print(f"\n  {party}: talked about far more than filed")
        print(subset.head(3)[["topic_name", "stated_share", "revealed_share"]]
              .to_string(index=False))
        print(f"  {party}: filed far more than talked about")
        print(subset.tail(3)[["topic_name", "stated_share", "revealed_share"]]
              .to_string(index=False))

    print(f"\nwrote {out_dir / 'bill_emphasis_by_party.csv'}")
    print(f"wrote {out_dir / 'bill_emphasis_by_state.csv'}")
    print(f"wrote {out_dir / 'stated_vs_revealed.csv'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

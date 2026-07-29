"""Compare what state parties *say* with what their legislators *file*.

This is the comparison the whole project was built for. Platform emphasis is what a state party
organization declares matters; bill emphasis is what its legislators actually spend the session
filing. The two are produced independently -- different sources, different authors, different
incentives -- and are made comparable only by being classified into the same taxonomy.

Both are measured as **share**: share of platform planks, and share of sponsored bills. Share
rather than count, because states differ enormously in both platform length and legislative
volume (New York files 97,000 bills in this window and Wyoming a small fraction of that), so
raw counts would measure institutional throughput rather than priority.

Caveats that belong next to any number produced here
----------------------------------------------------
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


def classify_bills(bills, classifier: EmbeddingClassifier, *, batch_size: int = 512,
                   min_similarity: float = 0.20, min_title_chars: int = 20):
    """Classify bills by title. Returns the frame with ``topic`` and ``similarity`` columns.

    Very short titles ("Relating to taxation.") carry too little signal to place, and are left
    unclassified rather than assigned on the strength of one word.
    """
    frame = bills.copy()
    titles = frame["title"].fillna("").astype(str).tolist()
    usable = [index for index, title in enumerate(titles) if len(title) >= min_title_chars]

    topics = [None] * len(titles)
    similarities = [0.0] * len(titles)
    if usable:
        predictions = classifier.predict_many(
            [titles[index] for index in usable],
            batch_size=batch_size, min_similarity=min_similarity,
        )
        for index, (code, similarity, _) in zip(usable, predictions, strict=True):
            topics[index] = code
            similarities[index] = round(similarity, 4)

    frame["topic"] = topics
    frame["similarity"] = similarities
    return frame


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
    parser.add_argument("--platform-emphasis", default="data/processed/emphasis_by_party.csv")
    parser.add_argument("--topics", default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--out-dir", default="data/processed")
    args = parser.parse_args(argv)

    topics = load_topics(args.topics)
    classifier = EmbeddingClassifier(topics)
    print(f"model {classifier.model_name} on device {classifier.device}")

    bills = pd.read_parquet(args.bills, columns=["state", "year", "title", "sponsor_party"])
    major = bills[bills["sponsor_party"].isin(["D", "R"])].rename(
        columns={"sponsor_party": "party"}
    )
    print(f"bills with a party attribution: {len(major):,} of {len(bills):,}")

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

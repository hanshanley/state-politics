"""Measure what each state party emphasizes, and compare parties and eras.

Emphasis is measured as **share of planks**: of everything a state party said in a document,
what fraction was about each topic. Share is the right unit because platforms differ enormously
in length -- the Texas GOP's 2024 platform runs to 22,000 words and Vermont's to a few thousand
-- so raw counts would measure verbosity rather than priority.

Two comparisons the resulting table supports:

* **Between parties.** For each topic, the Democratic and Republican share of planks, which is
  the headline "what does each side talk about" result.
* **Across eras.** The same measure computed on the 1990-2017 slice of the Dataverse corpus
  (see ``--historical-from``) and on the
  2018-present corpus this project collected, showing how emphasis has moved.

Everything here is descriptive. Classification accuracy is 62% top-1 / 78% top-2 on a
hand-labelled sample (see :mod:`state_politics.analysis.validate`), which supports statements
about broad aggregate emphasis and not about any individual plank.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from .taxonomy import (
    DEFAULT_TOPICS_PATH,
    MIN_TOPIC_SIMILARITY,
    EmbeddingClassifier,
    load_topics,
    segment_planks,
)

__all__ = ["classify_corpus", "emphasis_by_party", "emphasis_table"]

#: Earliest year counted as "modern". A document the collector found on a party's site today
#: but which the party dated earlier belongs to the earlier era.
MODERN_FROM = 2018


def classify_corpus(frame, classifier: EmbeddingClassifier, *, text_column: str = "text",
                    batch_size: int = 256,
                    min_similarity: float = MIN_TOPIC_SIMILARITY):
    """Segment every document into planks and classify them. Returns a plank-level frame."""
    import pandas as pd

    records = []
    for row_index, row in enumerate(frame.itertuples(index=False)):
        text = getattr(row, text_column, "") or ""
        for plank in segment_planks(text, row_index):
            records.append({
                "document_index": row_index,
                "state": row.state,
                "party": row.party,
                "year": getattr(row, "year", None),
                "era": getattr(row, "era", None),
                "plank_index": plank.plank_index,
                "n_words": plank.n_words,
                "text": plank.text,
            })
    if not records:
        return pd.DataFrame(columns=["state", "party", "year", "topic", "similarity"])

    planks = pd.DataFrame(records)
    predictions = classifier.predict_many(
        planks["text"].tolist(), batch_size=batch_size, min_similarity=min_similarity
    )
    planks["topic"] = [code for code, _, _ in predictions]
    planks["similarity"] = [round(sim, 4) for _, sim, _ in predictions]
    planks["margin"] = [round(margin, 4) for _, _, margin in predictions]
    return planks


def emphasis_table(planks, topics, *, by: tuple[str, ...] = ("state", "party")):
    """Share of classified planks per topic within each group.

    Unclassified planks are excluded from the denominator rather than spread across topics:
    they carry no topic information, and counting them would dilute every share by an amount
    that varies with document quality.
    """
    import pandas as pd

    named = {topic.code: topic.name for topic in topics}
    classified = planks[planks["topic"].notna()].copy()
    if classified.empty:
        return pd.DataFrame(columns=[*by, "topic", "topic_name", "n_planks", "share"])

    counts = (
        classified.groupby([*by, "topic"], dropna=False).size().rename("n_planks").reset_index()
    )
    totals = counts.groupby(list(by))["n_planks"].transform("sum")
    counts["share"] = counts["n_planks"] / totals
    counts["topic_name"] = counts["topic"].map(named)
    return counts.sort_values([*by, "share"], ascending=[*[True] * len(by), False])


def emphasis_by_party(planks, topics):
    """Topic shares for each major party, side by side, with the gap between them."""

    major = planks[planks["party"].isin(["D", "R"])]
    table = emphasis_table(major, topics, by=("party",))
    wide = table.pivot(index=["topic", "topic_name"], columns="party", values="share")
    wide = wide.reindex(columns=["D", "R"]).fillna(0.0).reset_index()
    wide["gap"] = wide["D"] - wide["R"]
    counts = (
        major[major["topic"].notna()]
        .groupby(["topic", "party"]).size().unstack(fill_value=0).reindex(columns=["D", "R"])
        .fillna(0).astype(int)
        .rename(columns={"D": "n_D", "R": "n_R"}).reset_index()
    )
    return wide.merge(counts, on="topic", how="left").sort_values("gap", ascending=False)


def _content_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", (text or "").lower()))


def _drop_cross_corpus_duplicates(corpus, *, min_jaccard: float = 0.85):
    """Drop documents present in both the Dataverse corpus and this project's collection.

    The two corpora overlap: eleven (state, party, year) documents appear in both, ten of them
    with content-word Jaccard between 0.90 and 1.00 and two identical. Counting those planks
    twice does not move a national share much but badly distorts the organizations concerned --
    28.3% of Indiana Republicans' planks were a second copy of one document.

    Two things this deliberately does *not* do:

    * It does not key off the era label. An earlier version did, and became a silent no-op the
      moment pre-2018 collected documents started being filed under the historical era: both
      copies then sat on the same side and nothing ever matched.
    * It does not treat key equality as proof. Wisconsin Republicans have a 2014 document in
      each corpus whose content-word Jaccard is 0.31 -- different documents that happen to
      share a year -- so the texts must actually agree before one is discarded.

    The copy carrying a fetched URL and hash (the collected one) is the one kept.
    """

    frame = corpus.reset_index(drop=True)
    dated = frame[frame["year"].notna()]
    keys = list(zip(dated["state"], dated["party"],
                    dated["year"].astype("Int64"), strict=True))
    by_key: dict[tuple, list[int]] = {}
    for position, key in zip(dated.index, keys, strict=True):
        by_key.setdefault(key, []).append(position)

    collected = set(frame.index[frame["source_corpus"] == "collected"])
    drop: list[int] = []
    for positions in by_key.values():
        if len(positions) < 2:
            continue
        keep = next((i for i in positions if i in collected), positions[0])
        keep_tokens = _content_tokens(frame.at[keep, "text"])
        for other in positions:
            if other == keep:
                continue
            tokens = _content_tokens(frame.at[other, "text"])
            union = keep_tokens | tokens
            if union and len(keep_tokens & tokens) / len(union) >= min_jaccard:
                drop.append(other)
    if drop:
        print(f"dropped {len(drop)} documents duplicated across the two corpora")
    return frame.drop(index=drop)


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--modern", default="data/processed/platforms_2018_present.parquet")
    parser.add_argument("--historical", default="data/processed/platforms_historical.parquet")
    parser.add_argument("--topics", default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--out-dir", default="data/processed")
    parser.add_argument("--historical-from", type=int, default=1990,
                        help="earliest historical year to classify; the full corpus reaches "
                             "back to 1840 and is far larger than the modern one")
    args = parser.parse_args(argv)

    topics = load_topics(args.topics)
    classifier = EmbeddingClassifier(topics)
    print(f"model {classifier.model_name} on device {classifier.device}")

    frames = []
    modern = pd.read_parquet(args.modern)
    modern = modern[modern["confirmed"]]
    # The collector finds whatever a party currently publishes, and some parties still publish
    # a platform from before the window -- 16 of these documents are dated 2006-2017. Labelling
    # them "2018-present" because that is when they were *collected* would put pre-2018 planks
    # on the modern side of a comparison whose entire point is that both sides cover the same
    # years, so they are assigned by their own date instead.
    modern_year = pd.to_numeric(modern["year"], errors="coerce")
    in_window = modern_year.isna() | (modern_year >= MODERN_FROM)
    frames.append(modern[in_window].assign(era="2018-present", source_corpus="collected")[
        ["state", "party", "year", "era", "text", "source_corpus"]])
    print(f"modern documents:     {int(in_window.sum())} "
          f"({int((~in_window).sum())} dated before {MODERN_FROM}, moved to the earlier era)")

    historical_path = Path(args.historical)
    if historical_path.exists():
        historical = pd.read_parquet(historical_path)
        historical = historical[
            historical["is_major_party"]
            & (historical["year"] >= args.historical_from)
            & (historical["state"] != "US")
        ].assign(era=f"{args.historical_from}-2017", source_corpus="dataverse")
        frames.append(historical[["state", "party", "year", "era", "text", "source_corpus"]])
        print(f"historical documents: {len(historical)} (from {args.historical_from})")

    # Pre-window modern documents belong with the historical era, not with the years they were
    # collected in.
    early = modern[~in_window]
    if not early.empty:
        frames.append(early.assign(era=f"{args.historical_from}-2017",
                                   source_corpus="collected")[
            ["state", "party", "year", "era", "text", "source_corpus"]])

    corpus = _drop_cross_corpus_duplicates(pd.concat(frames, ignore_index=True))
    planks = classify_corpus(corpus, classifier)
    print(f"planks classified:    {len(planks)} "
          f"({int(planks['topic'].isna().sum())} below the similarity threshold)")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    planks.drop(columns=["text"]).to_parquet(out_dir / "planks_classified.parquet", index=False)

    by_org = emphasis_table(planks, topics, by=("state", "party", "era"))
    by_org.to_csv(out_dir / "emphasis_by_org.csv", index=False)

    by_party = emphasis_by_party(planks, topics)
    by_party.to_csv(out_dir / "emphasis_by_party.csv", index=False)

    # An era-restricted table as well. The stated-vs-revealed comparison must not measure a
    # 1990-2026 platform average against a 2018-2026 bill window: most planks predate 2018,
    # and pooling them understates exactly the topics that have risen since (Republican
    # immigration 4.1% pooled vs 5.9% on 2018-present planks alone).
    modern = planks[planks["era"] == "2018-present"]
    if not modern.empty:
        emphasis_by_party(modern, topics).to_csv(
            out_dir / "emphasis_by_party_2018_present.csv", index=False
        )

    print("\ntopics where the parties differ most (share of planks):")
    display = by_party[["topic_name", "D", "R", "gap"]].copy()
    for column in ("D", "R", "gap"):
        display[column] = (display[column] * 100).round(1)
    print(display.head(6).to_string(index=False))
    print("...")
    print(display.tail(6).to_string(index=False))
    print(f"\nwrote {out_dir / 'planks_classified.parquet'}")
    print(f"wrote {out_dir / 'emphasis_by_org.csv'}")
    print(f"wrote {out_dir / 'emphasis_by_party.csv'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

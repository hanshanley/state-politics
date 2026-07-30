"""Score the plank classifiers against a hand-labelled gold set.

The project's rule is that no unvalidated classifier output ships. This module measures both
classifiers on the same held-out planks and reports per-topic accuracy, so the emphasis
figures downstream can be read with a known error rate attached rather than taken on trust.

About the gold set
------------------
``data/gold/plank_topics_gold.csv`` holds 50 planks drawn at random (seed 20260729) from the
2018-present corpus and labelled by hand by this project's author against
``conf/topics.yml``. It is small and single-annotator, so it supports statements like "the
embedding classifier is roughly right about two-thirds of planks" and not fine-grained
per-topic claims. It is committed to the repository because it is authored input, not a
reproducible artifact: a future change to the taxonomy or the model can be re-scored against
exactly the same labels.

Some planks are genuinely ambiguous between two defensible topics -- a plank on the cost of
educating immigrant children is both Immigration and Education -- so a ceiling well below
100% is expected, and top-2 accuracy is reported alongside top-1 for that reason.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from .taxonomy import DEFAULT_TOPICS_PATH, EmbeddingClassifier, KeywordClassifier, load_topics

__all__ = ["DEFAULT_GOLD_PATH", "GoldPlank", "Scores", "evaluate", "load_gold"]

DEFAULT_GOLD_PATH = Path(__file__).resolve().parents[3] / "data" / "gold" / "plank_topics_gold.csv"


@dataclass(frozen=True, slots=True)
class GoldPlank:
    index: int
    state: str
    party: str
    gold_topic: int
    text: str


@dataclass(frozen=True, slots=True)
class Scores:
    """Accuracy of one classifier on the gold set."""

    name: str
    n: int
    correct: int
    unclassified: int
    top2_correct: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0

    @property
    def top2_accuracy(self) -> float:
        return self.top2_correct / self.n if self.n else 0.0

    def summary(self) -> str:
        return (
            f"{self.name:<22} top-1 {self.correct}/{self.n} ({self.accuracy:.0%})"
            f"  top-2 {self.top2_correct}/{self.n} ({self.top2_accuracy:.0%})"
            f"  unclassified {self.unclassified}"
        )


def load_gold(path: Path | str = DEFAULT_GOLD_PATH) -> list[GoldPlank]:
    with open(path, encoding="utf-8") as handle:
        return [
            GoldPlank(
                index=int(row["index"]),
                state=row["state"],
                party=row["party"],
                gold_topic=int(row["gold_topic"]),
                text=row["text"],
            )
            for row in csv.DictReader(handle)
        ]


def evaluate(
    gold: list[GoldPlank],
    topics_path: Path | str = DEFAULT_TOPICS_PATH,
    *,
    include_embedding: bool = True,
) -> tuple[list[Scores], list[dict]]:
    """Score both classifiers. Returns ``(scores, per_plank_rows)``."""
    import numpy as np

    topics = load_topics(topics_path)
    texts = [plank.text for plank in gold]
    rows: list[dict] = [
        {"index": plank.index, "state": plank.state, "party": plank.party,
         "gold_topic": plank.gold_topic}
        for plank in gold
    ]

    keyword = KeywordClassifier(topics)
    keyword_predictions = [code for code, _ in keyword.predict_many(texts)]
    for row, prediction in zip(rows, keyword_predictions, strict=True):
        row["keyword_topic"] = prediction
    scores = [Scores(
        name="keyword baseline",
        n=len(gold),
        correct=sum(p == g.gold_topic for p, g in zip(keyword_predictions, gold, strict=True)),
        unclassified=sum(p is None for p in keyword_predictions),
        top2_correct=sum(p == g.gold_topic for p, g in zip(keyword_predictions, gold, strict=True)),
    )]

    if include_embedding:
        classifier = EmbeddingClassifier(topics)
        # Score the configuration that actually ships, threshold included. Scoring a bare
        # argsort would report "unclassified 0" for a classifier that leaves 8% of this sample
        # unclassified in production.
        predictions = classifier.predict_many(texts)
        vectors = classifier.model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
        similarities = vectors @ classifier.topic_vectors.T
        ranking = np.argsort(-similarities, axis=1)
        codes = [topic.code for topic in topics]
        top1 = [code for code, _, _ in predictions]
        top2 = [{codes[int(r[0])], codes[int(r[1])]} for r in ranking]
        for row, (code, similarity, _) in zip(rows, predictions, strict=True):
            row["embedding_topic"] = code
            row["embedding_similarity"] = round(similarity, 3)
        scores.append(Scores(
            name=f"embedding ({classifier.device})",
            n=len(gold),
            correct=sum(p == g.gold_topic for p, g in zip(top1, gold, strict=True)),
            unclassified=sum(code is None for code in top1),
            top2_correct=sum(g.gold_topic in pair for pair, g in zip(top2, gold, strict=True)),
        ))
    return scores, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", default=DEFAULT_GOLD_PATH)
    parser.add_argument("--topics", default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--out", default="data/processed/plank_classifier_scores.csv")
    parser.add_argument("--no-embedding", action="store_true")
    args = parser.parse_args(argv)

    gold = load_gold(args.gold)
    scores, rows = evaluate(gold, args.topics, include_embedding=not args.no_embedding)
    print(f"gold planks: {len(gold)} (hand-labelled, single annotator)")
    for score in scores:
        print("  " + score.summary())

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

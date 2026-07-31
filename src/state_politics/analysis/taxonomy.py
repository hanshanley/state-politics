"""Shared issue taxonomy and plank-level classification.

One taxonomy is applied to *both* evidence streams so platform emphasis and bill sponsorship
are directly comparable; it is anchored to the Comparative Agendas Project major topics rather
than invented here (see ``conf/topics.yml``).

Classification runs **entirely locally** on this machine's Apple Silicon GPU, per the project's
no-hosted-API rule. Two classifiers are provided on purpose:

* :class:`EmbeddingClassifier` -- a local sentence-transformer embeds each plank and each topic
  description and assigns the nearest topic. This is the one whose output is used.
* :class:`KeywordClassifier` -- a transparent seed-term baseline. It exists so the embedding
  model can be checked against something a human can read and argue with, and so agreement
  between the two is measurable rather than assumed.

Neither is trusted on its own: :mod:`state_politics.analysis.validate` scores both against a
hand-labelled gold set and the accuracy is reported with the results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DEFAULT_TOPICS_PATH",
    "EmbeddingClassifier",
    "KeywordClassifier",
    "Plank",
    "Topic",
    "load_topics",
    "segment_planks",
]

DEFAULT_TOPICS_PATH = Path(__file__).resolve().parents[3] / "conf" / "topics.yml"

#: Sentence-transformer used for plank classification. Small enough to run comfortably in the
#: machine's 16 GB of unified memory, and pinned so results are reproducible.
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MIN_TOPIC_SIMILARITY = 0.20

#: A plank shorter than this is a heading or fragment, not a position statement.
MIN_PLANK_CHARS = 120
#: Longer blocks are split further; a 5,000-character block is several distinct positions.
MAX_PLANK_CHARS = 1500


@dataclass(frozen=True, slots=True)
class Topic:
    """One issue topic."""

    code: int
    name: str
    description: str
    seeds: tuple[str, ...]

    @property
    def embedding_text(self) -> str:
        """What the embedding model sees: the topic stated as prose, plus its vocabulary."""
        return f"{self.name}. {self.description} Examples: {', '.join(self.seeds)}."


@dataclass(frozen=True, slots=True)
class Plank:
    """One position statement extracted from a platform document."""

    document_index: int
    plank_index: int
    text: str

    @property
    def n_words(self) -> int:
        return len(self.text.split())


def load_topics(path: Path | str = DEFAULT_TOPICS_PATH) -> list[Topic]:
    """Load the topic scheme from YAML."""
    import yaml

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    topics = [
        Topic(
            code=int(entry["code"]),
            name=entry["name"],
            description=" ".join(entry["description"].split()),
            seeds=tuple(str(s).lower() for s in entry.get("seeds", [])),
        )
        for entry in payload["topics"]
    ]
    codes = [t.code for t in topics]
    if len(set(codes)) != len(codes):
        raise ValueError("duplicate topic codes in the taxonomy")
    return topics


_BOILERPLATE_RE = re.compile(
    r"^\s*(?:table of contents|contents|index|preamble|adopted|approved|page \d+|"
    r"copyright|all rights reserved|paid for by)\b",
    re.I,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
#: Runs of single capitals separated by spaces -- "A ND D EMOCRACY" -- are a PDF extraction
#: artefact, not prose.
_SPACED_CAPS_RE = re.compile(r"(?:\b[A-Z]\s+[A-Z]{2,}\b\s*){2,}")


def _looks_like_prose(block: str) -> bool:
    """Reject table-of-contents rows and extraction artefacts.

    A contents page is mostly headings and page numbers, and each of its rows survives every
    length test while carrying no position at all. Left in, they became "planks" that the
    classifier dutifully assigned topics to at similarities of 0.10-0.19.
    """
    words = block.split()
    if len(words) < 12:
        return False
    digits = sum(character.isdigit() for character in block)
    if digits / len(block) > 0.08:          # page numbers dominate a contents row
        return False
    if _SPACED_CAPS_RE.search(block):
        return False
    lowercase_words = sum(1 for word in words if word[:1].islower())
    return lowercase_words / len(words) >= 0.4   # prose, not a run of headings


def segment_planks(text: str, document_index: int = 0) -> list[Plank]:
    """Split a platform document into plank-sized position statements.

    Platforms are written as discrete planks, so paragraph breaks are the natural unit. Very
    long paragraphs are split on sentence boundaries -- a 5,000-character block is several
    distinct positions and classifying it as one would smear its topics together. Short
    fragments, contents rows and PDF extraction artefacts are dropped.
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]
    planks = _planks_from_blocks(blocks, document_index)

    # Hard-wrapped documents defeat both splitters: one long run of single newlines yields
    # line-level fragments, and a blank line after every wrapped line yields thousands of tiny
    # "paragraphs". Either way the length floor deletes almost everything, and real platforms
    # of 5,000-11,000 words segmented to *zero* planks. So the fallback triggers on the yield
    # rather than on the block count: if a substantial document produced implausibly few
    # planks, re-join its short lines into paragraphs and try again.
    words = len(text.split())
    if words > 500 and len(planks) < words / 500:
        rejoined = _planks_from_blocks(_rejoin_wrapped_lines(text), document_index)
        if len(rejoined) > len(planks):
            return rejoined
    return planks


def _planks_from_blocks(blocks: list[str], document_index: int) -> list[Plank]:
    planks: list[Plank] = []
    for block in blocks:
        block = _strip_boilerplate_prefix(re.sub(r"\s+", " ", block).strip())
        if len(block) < MIN_PLANK_CHARS:
            continue
        for piece in _split_long(block):
            if _looks_like_prose(piece):
                planks.append(Plank(document_index, len(planks), piece))
    return planks


def _rejoin_wrapped_lines(text: str, *, target: int = 400) -> list[str]:
    """Reassemble hard-wrapped lines into paragraph-sized blocks."""
    blocks: list[str] = []
    current: list[str] = []
    for line in (raw.strip() for raw in text.split("\n")):
        if not line:
            # A blank line only ends a paragraph once enough text has accumulated. Several
            # platform PDFs extract with blank lines between every short line, and treating
            # each as a boundary left every block below the length floor -- deleting the whole
            # document.
            if current and len(" ".join(current)) >= MIN_PLANK_CHARS:
                blocks.append(" ".join(current))
                current = []
            continue
        current.append(line)
        length = len(" ".join(current))
        # Prefer to break at sentence punctuation, but break on length regardless: several
        # platform PDFs are laid out as short unpunctuated lines ("WHEREAS", "One"), and
        # waiting for a full stop swallowed the entire document into a single block.
        ends_sentence = line.endswith((".", "!", "?", ":", ";"))
        if (length >= target and ends_sentence) or length >= target * 3:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    return blocks


def _strip_boilerplate_prefix(block: str) -> str:
    """Remove a leading boilerplate phrase instead of discarding the block that carries it.

    :data:`_BOILERPLATE_RE` is a *prefix* test, but it was used to drop the whole block. A
    single 47,345-word platform beginning "PAID FOR BY THE DEMOCRATIC PARTY OF VIRGINIA" was
    therefore deleted in its entirety, and the loss was party-asymmetric -- 5.9% of Democratic
    words against 3.4% of Republican -- biasing the very comparison this project publishes.
    """
    match = _BOILERPLATE_RE.match(block)
    if not match:
        return block
    remainder = block[match.end():].lstrip(" :.-\u2014")
    return remainder if len(remainder) >= MIN_PLANK_CHARS else ""


def _split_long(block: str) -> list[str]:
    if len(block) <= MAX_PLANK_CHARS:
        return [block]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT_RE.split(block):
        if current and len(current) + len(sentence) + 1 > MAX_PLANK_CHARS:
            pieces.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current.strip():
        pieces.append(current.strip())
    return [p for p in pieces if len(p) >= MIN_PLANK_CHARS]


class KeywordClassifier:
    """Transparent seed-term baseline.

    Scores each topic by how many of its seed terms appear, normalized by the number of seeds
    so topics with long seed lists are not systematically favoured. Returns ``None`` when no
    seed matches, rather than guessing -- an unclassifiable plank is a fact worth keeping.
    """

    def __init__(self, topics: list[Topic]):
        self.topics = topics
        self._patterns = {
            topic.code: [re.compile(rf"\b{re.escape(seed)}\b", re.I) for seed in topic.seeds]
            for topic in topics
        }

    def predict(self, text: str) -> tuple[int | None, float]:
        best_code, best_score = None, 0.0
        for topic in self.topics:
            patterns = self._patterns[topic.code]
            hits = sum(1 for pattern in patterns if pattern.search(text))
            if not hits:
                continue
            score = hits / len(patterns) ** 0.5
            if score > best_score:
                best_code, best_score = topic.code, score
        return best_code, best_score

    def predict_many(self, texts: list[str]) -> list[tuple[int | None, float]]:
        return [self.predict(text) for text in texts]


#: Texts embedded per slice. Bounds peak memory independently of corpus size.
CHUNK_SIZE = 50_000


class EmbeddingClassifier:
    """Nearest-topic classifier using a local sentence-transformer.

    Runs on Apple Silicon via MPS (see :mod:`state_politics.compute`). No hosted API is used
    or permitted.
    """

    def __init__(self, topics: list[Topic], model_name: str = DEFAULT_MODEL,
                 device: str | None = None):
        from sentence_transformers import SentenceTransformer

        from ..compute import select_device

        self.topics = topics
        self.model_name = model_name
        self.device = device or select_device()
        self.model = SentenceTransformer(model_name, device=self.device)
        self.topic_vectors = self.model.encode(
            [topic.embedding_text for topic in topics],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    def predict_many(
        self,
        texts: list[str],
        batch_size: int = 64,
        min_similarity: float = MIN_TOPIC_SIMILARITY,
    ) -> list[tuple[int | None, float, float]]:
        """Return ``(topic_code, similarity, margin)`` per text.

        ``topic_code`` is ``None`` when the nearest topic is below ``min_similarity``: a plank
        that resembles no topic should be recorded as unclassified rather than pushed into
        whichever topic happened to be least far away.

        ``margin`` is the gap to the runner-up. A small margin means the plank sat between two
        topics, which a reader should be able to filter on rather than have silently resolved.
        """
        import numpy as np

        if not texts:
            return []
        results: list[tuple[int | None, float, float]] = []
        # Encode in slices. Embedding the whole corpus at once materialises one array of
        # len(texts) x 384 float32 -- 1.6 GB for the 1.1M bill titles -- alongside the
        # similarity matrix and its argsort, which was enough to get this step OOM-killed on a
        # 16 GB machine. Only one slice is ever resident now, so the classifier scales with the
        # corpus instead of with available RAM.
        for start in range(0, len(texts), CHUNK_SIZE):
            chunk = texts[start:start + CHUNK_SIZE]
            vectors = self.model.encode(
                chunk, batch_size=batch_size, normalize_embeddings=True,
                convert_to_numpy=True, show_progress_bar=False,
            )
            similarities = vectors @ self.topic_vectors.T
            # Only the best and runner-up are needed, so partition rather than fully sorting
            # every row across all topics.
            top2 = np.argpartition(-similarities, kth=1, axis=1)[:, :2]
            for row, pair in zip(similarities, top2, strict=True):
                first, second = (pair if row[pair[0]] >= row[pair[1]] else pair[::-1])
                score = float(row[first])
                results.append((
                    self.topics[int(first)].code if score >= min_similarity else None,
                    score,
                    score - float(row[second]),
                ))
            del vectors, similarities, top2
        return results

    def predict(
        self, text: str, min_similarity: float = MIN_TOPIC_SIMILARITY
    ) -> tuple[int | None, float, float]:
        return self.predict_many([text], min_similarity=min_similarity)[0]

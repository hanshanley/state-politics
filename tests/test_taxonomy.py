"""Tests for the shared issue taxonomy, plank segmentation and classification.

Two of these encode bugs that produced confidently wrong output: a PDF table of contents being
segmented into "planks" that the classifier then dutifully assigned topics to, and a plank
resembling no topic being pushed into whichever one was least far away.
"""

from __future__ import annotations

import pytest

from state_politics.analysis.taxonomy import (
    DEFAULT_TOPICS_PATH,
    MIN_PLANK_CHARS,
    KeywordClassifier,
    Topic,
    load_topics,
    segment_planks,
)

PLANK = (
    "We support a living wage for every worker in this state, and we believe collective "
    "bargaining rights must be protected for public and private sector employees alike."
)


def test_taxonomy_loads_and_is_well_formed():
    topics = load_topics()
    assert len(topics) >= 20
    assert all(t.description and t.seeds for t in topics)
    assert len({t.code for t in topics}) == len(topics)
    assert len({t.name for t in topics}) == len(topics)


def test_taxonomy_keeps_the_rare_national_topics():
    """Dropping Defense/Foreign trade/International affairs would push genuine foreign-policy
    planks into whichever domestic topic was nearest."""
    codes = {t.code for t in load_topics()}
    assert {16, 18, 19} <= codes


def test_topics_file_is_where_the_code_expects():
    assert DEFAULT_TOPICS_PATH.exists()


def test_duplicate_codes_are_rejected(tmp_path):
    bad = tmp_path / "topics.yml"
    bad.write_text(
        "topics:\n"
        "  - {code: 1, name: A, description: x, seeds: [a]}\n"
        "  - {code: 1, name: B, description: y, seeds: [b]}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate topic codes"):
        load_topics(bad)


def test_segment_planks_splits_on_paragraphs_and_drops_fragments():
    text = f"{PLANK}\n\nHEADING\n\n{PLANK}"
    planks = segment_planks(text)
    assert len(planks) == 2
    assert all(len(p.text) >= MIN_PLANK_CHARS for p in planks)


def test_segment_planks_drops_table_of_contents_rows():
    """A contents row survives every length test while carrying no position at all.

    Left in, these became planks the classifier assigned topics to at similarities of 0.10.
    """
    toc = (
        "Part One - Economy 13 Protecting Workers 14 Raising Wages 15 Health Care 26 "
        "Education 31 Housing 34 Environment 38 Energy 42 Immigration 47 Justice 51"
    )
    assert segment_planks(toc) == []


def test_segment_planks_drops_pdf_spaced_capital_artefacts():
    artefact = (
        "AND D EMOCRACY ` 6 A CCESS TO THE B ALLOT C OUNTING E VERY L AWFUL V OTE "
        "P ROTECTING THE R IGHT AND I NTEGRITY 6 R EDISTRICTING 7 C AMPAIGN F INANCE"
    )
    assert segment_planks(artefact) == []


def test_segment_planks_splits_overlong_blocks():
    long_block = " ".join([PLANK] * 12)
    planks = segment_planks(long_block)
    assert len(planks) > 1
    assert all(len(p.text) <= 1600 for p in planks)


def test_segment_planks_handles_pdf_single_newline_text():
    """Hard-wrapped text must survive; how it is grouped matters less than that none is lost."""
    text = "\n".join([PLANK, PLANK, PLANK])
    planks = segment_planks(text)
    assert planks
    combined = " ".join(p.text for p in planks)
    assert combined.count("living wage") == 3


def test_segment_planks_does_not_discard_a_block_for_its_first_words():
    """_BOILERPLATE_RE is a prefix test; using it to drop whole blocks deleted a 47,345-word
    platform because of the four words it opened with."""
    body = " ".join([PLANK] * 4)
    planks = segment_planks(f"PAID FOR BY THE DEMOCRATIC PARTY OF SOMEWHERE {body}")
    assert planks
    assert "living wage" in " ".join(p.text for p in planks)


def test_segment_planks_recovers_a_hard_wrapped_document():
    """Real platform PDFs extract as short lines with blank lines between them; treating each
    blank line as a paragraph break left every block under the length floor and lost the lot."""
    lines = []
    for _ in range(40):
        lines.extend(["We support fair wages for every worker in this state,",
                      "and we believe collective bargaining must be protected.", ""])
    planks = segment_planks("\n".join(lines))
    assert len(planks) >= 5


def test_segment_planks_never_silently_loses_a_substantial_document():
    document = " ".join([PLANK] * 30)
    assert segment_planks(document), "a 30-plank document must not segment to nothing"


def test_keyword_classifier_returns_none_rather_than_guessing():
    topics = load_topics()
    classifier = KeywordClassifier(topics)
    code, score = classifier.predict("The quick brown fox jumped over the lazy dog entirely.")
    assert code is None
    assert score == 0.0


def test_keyword_classifier_finds_the_obvious_topic():
    topics = load_topics()
    classifier = KeywordClassifier(topics)
    code, score = classifier.predict(PLANK)
    labour = next(t.code for t in topics if t.name.startswith("Labor"))
    assert code == labour
    assert score > 0


def test_keyword_scoring_does_not_favour_long_seed_lists():
    """Normalizing by seed count stops a topic winning purely by having more seeds."""
    topics = [
        Topic(code=1, name="Few", description="d", seeds=("alpha",)),
        Topic(code=2, name="Many", description="d", seeds=tuple(f"w{i}" for i in range(40))),
    ]
    classifier = KeywordClassifier(topics)
    code, _ = classifier.predict("alpha")
    assert code == 1


def test_topic_embedding_text_includes_name_description_and_seeds():
    topic = Topic(code=1, name="Energy", description="About energy.", seeds=("solar", "wind"))
    text = topic.embedding_text
    assert "Energy" in text and "About energy." in text and "solar" in text


def test_predict_many_is_unchanged_by_chunking():
    """Chunking bounds memory; it must not change a single prediction.

    Encoding the whole corpus at once materialised a 1.6 GB embedding array for the 1.1M bill
    titles and got the step OOM-killed, so predictions are now made in slices.
    """
    import numpy as np

    from state_politics.analysis import taxonomy as module
    from state_politics.analysis.taxonomy import EmbeddingClassifier

    topics = load_topics()
    classifier = EmbeddingClassifier(topics)
    texts = [f"An act relating to {word} policy in the state" for word in
             ("education", "transportation", "health", "taxation", "housing",
              "agriculture", "energy", "elections", "labor", "veterans")] * 3

    original = module.CHUNK_SIZE
    try:
        module.CHUNK_SIZE = 4          # forces several slices
        chunked = classifier.predict_many(texts, batch_size=8)
        module.CHUNK_SIZE = 10_000     # single slice
        single = classifier.predict_many(texts, batch_size=8)
    finally:
        module.CHUNK_SIZE = original

    assert len(chunked) == len(texts)
    for left, right in zip(chunked, single, strict=True):
        assert left[0] == right[0]
        assert np.isclose(left[1], right[1])
        assert np.isclose(left[2], right[2])


def test_predict_many_handles_an_empty_corpus():
    from state_politics.analysis.taxonomy import EmbeddingClassifier

    classifier = EmbeddingClassifier(load_topics())
    assert classifier.predict_many([]) == []

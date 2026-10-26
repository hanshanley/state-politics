"""Whole constitutional proposals remain distinct from ordinary resolution profiles."""

import hashlib
import json

import pytest

from state_politics.bills import ne_journal_constitutional_text as ca
from state_politics.bills.ne_journal_text import FLAGS, compact


def page(number, text):
    return {
        "page": number,
        "text": text,
        "characters": len(text),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def original(**changes):
    return {
        "bill_id": "original-proposal",
        "state": "NE",
        "identifier": "LR 5CA",
        "session_identifier": "108",
        "source_introduction_date": "2023-01-05",
        "title": "Propose a complete constitutional amendment",
        "unknown_party": None,
        **changes,
    }


def book():
    return {
        "year": 2023,
        "session": "FIRST",
        "volume": 1,
        "pages": 2,
        "sha256": "a" * 64,
        "url": "https://example.org/complete-journal.pdf",
    }


def source(heading="Laid over.\n"):
    return [
        page(
            1,
            "1\nSECOND DAY - JANUARY 5, 2023\n"
            "LEGISLATIVE RESOLUTION 5CA. Introduced by Author, 1;\n"
            "THE MEMBERS OF THE ONE HUNDRED EIGHTH LEGISLATURE\n"
            "OF NEBRASKA, FIRST SESSION, RESOLVE THAT:\n"
            "Section 1. At the general election the proposed amendment shall be submitted.\n"
            "I-1 The full proposed constitutional provision is retained here.\n",
        ),
        page(
            2,
            "LEGISLATIVE JOURNAL\n2\n"
            "Sec. 2. The proposed amendment shall be submitted to the electors in the\n"
            "manner prescribed by the Constitution of Nebraska, Article XVI, section 1,\n"
            "with the following ballot language:\n"
            "A constitutional amendment providing the complete stated change.\n"
            "For\nAgainst.\n" + heading + "Unrelated proceedings must not become policy text.\n",
        ),
    ]


def readers(raw):
    return {
        "pymupdf": raw,
        "pypdf": [page(row["page"], row["text"].replace(" ", "")) for row in raw],
    }


def qualify(raw, originals=None):
    return ca.qualify(
        {"book": readers(raw)},
        [original()] if originals is None else originals,
        books={"book": book()},
    )


@pytest.mark.parametrize(
    "heading",
    [
        "Laid over.\n",
        "LEGISLATIVE BILL 99. Introduced by Another Author, 2;\n",
        "ANNOUNCEMENT(S)\n",
        "UNANIMOUS CONSENT - Add Cointroducer(s)\n",
        "NOTICE OF COMMITTEE HEARING(S)\n",
        "AMENDMENT(S) - Print in Journal\n",
    ],
)
def test_complete_proposal_exact_identity_and_literal_proceedings_boundary(heading):
    raw = source(heading)
    context = original()
    before = context.copy()
    views, dispositions, candidates = qualify(raw, [context])
    assert len(views) == 2 and context == before
    assert dispositions[0]["disposition"] == "complete_two_reader_original_context_match"
    assert all(value["reason"] is None for value in candidates)
    assert views[0]["text"] != views[1]["text"]
    assert compact(views[0]["text"]) == compact(views[1]["text"])
    for view in views:
        assert view["identifier"] == "LR 5CA"
        assert view["view_id"].startswith("ne-journal-ca-v1:")
        assert all(view[flag] is False for flag in FLAGS)
        record = view["source_record"]
        saved = readers(raw)[record["reader"]]
        assert (
            "\n".join(
                saved[part["page"] - 1]["text"][part["start"] : part["end"]]
                for part in record["page_fragments"]
            )
            == view["text"]
        )
        assert (
            "\n".join(
                saved[part["page"] - 1]["text"][part["start"] : part["end"]]
                for part in record["terminator_fragments"]
            )
            == record["terminator_not_policy_text"]
        )
        assert "Unrelated" not in view["text"]
        assert compact(view["text"]).endswith("ForAgainst.")
        assert record["journal_date"] == "2023-01-05"


def test_inline_outer_sections_and_all_ballot_questions_are_preserved():
    raw = source()
    raw[1] = page(
        2,
        raw[1]["text"]
        .replace("Sec. 2.", "Complete final text from the first section.   Sec.\n2.", 1)
        .replace(
            "For\nAgainst.\nLaid over.",
            "For\nAgainst.\nA second complete ballot question.\nFor\nAgainst.\nLaid over.",
        ),
    )
    views, _, _ = qualify(raw)
    assert len(views) == 2
    for view in views:
        assert compact(view["text"]).count("ForAgainst.") == 2
        assert "secondcompleteballotquestion" in compact(view["text"])
        assert view["source_record"]["outer_sections_after_first"] == ["2"]


def test_next_page_heading_excludes_only_synthetic_separator():
    raw = source()
    body, _ = raw[1]["text"].split("Laid over.", 1)
    raw[1] = page(2, body + "\n\n")
    raw.append(page(3, "LEGISLATIVE JOURNAL\n3\nANNOUNCEMENT\nUnrelated proceedings.\n"))
    views, _, _ = qualify(raw)
    assert len(views) == 2
    assert all(view["text"].endswith("\n\n\n") for view in views)
    for view in views:
        join = view["source_record"]["excluded_synthetic_page_join"]
        assert join["text"] == "\n" and join["following_page"] == 3
        assert join["preceding_page"] == 2


def test_typed_ca_identity_never_aliases_same_numbered_ordinary_resolution():
    raw = source()
    views, dispositions, _ = qualify(
        raw, [original(), original(bill_id="ordinary", identifier="LR 5")]
    )
    assert len(views) == 2 and {view["bill_id"] for view in views} == {"original-proposal"}
    assert dispositions[1]["disposition"] == "outside_108th_constitutional_resolution_profile"


@pytest.mark.parametrize(
    "defect",
    [
        "ordinary_header",
        "wrong_original_date",
        "wrong_session",
        "missing_first_section",
        "missing_outer_section",
        "missing_ballot_introduction",
        "missing_against",
        "intervening_legislation",
        "reader_disagreement",
        "wrong_printed_day",
    ],
)
def test_incomplete_or_conflicting_proposals_are_not_admitted(defect):
    raw = source()
    context = original()
    if defect == "ordinary_header":
        raw[0] = page(1, raw[0]["text"].replace("5CA.", "5.", 1))
    elif defect == "wrong_original_date":
        context["source_introduction_date"] = "2023-01-06"
    elif defect == "wrong_session":
        raw[0] = page(1, raw[0]["text"].replace("FIRST SESSION", "SECOND SESSION"))
    elif defect == "missing_first_section":
        raw[0] = page(1, raw[0]["text"].replace("Section 1.", "Article 1."))
    elif defect == "missing_outer_section":
        raw[1] = page(2, raw[1]["text"].replace("Sec. 2.", "Sec. 3."))
    elif defect == "missing_ballot_introduction":
        raw[1] = page(2, raw[1]["text"].replace("following ballot language", "other text"))
    elif defect == "missing_against":
        raw[1] = page(2, raw[1]["text"].replace("Against.", ""))
    elif defect == "intervening_legislation":
        raw[1] = page(
            2,
            raw[1]["text"].replace(
                "Sec. 2.", "LEGISLATIVE BILL 99. Introduced by Other, 2;\nSec. 2.", 1
            ),
        )
    elif defect == "wrong_printed_day":
        raw[0] = page(1, raw[0]["text"].replace("JANUARY 5,", "JANUARY 6,"))
    supplied = readers(raw)
    if defect == "reader_disagreement":
        supplied["pypdf"][1] = page(
            2, supplied["pypdf"][1]["text"].replace("statedchange", "differentpolicy")
        )
    before = context.copy()
    views, dispositions, _ = ca.qualify({"book": supplied}, [context], books={"book": book()})
    assert not views and context == before
    assert dispositions[0]["disposition"] != "complete_two_reader_original_context_match"


def test_ca_archive_dispatch_preserves_current_metadata(tmp_path, monkeypatch):
    from state_politics.bills import archive_text

    (tmp_path / "manifest.json").write_text(json.dumps({"schema": ca.SCHEMA}))
    metadata, sentinel = [original()], object()

    def loader(directory, current):
        assert directory == tmp_path and current is metadata
        return sentinel

    monkeypatch.setattr(ca, "load_ne_journal_constitutional", loader)
    assert archive_text.load_archive(tmp_path, metadata) is sentinel


def test_ca_packet_cannot_be_built_under_public_output(tmp_path):
    with pytest.raises(ValueError, match="under project data/processed"):
        ca.build(*(tmp_path / name for name in ("parent", "queue", "public")))
    assert not (tmp_path / "public").exists()

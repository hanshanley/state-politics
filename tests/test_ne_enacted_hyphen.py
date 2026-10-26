"""Only independently witnessed PDF glyph positions may explain reader differences."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from state_politics.bills import ne_enacted_hyphen_text as hyphens
from state_politics.bills import ne_enacted_law_text as laws
from state_politics.bills.ne_journal_text import FLAGS, compact


def page(number, text):
    return {
        "page": number,
        "text": text,
        "characters": len(text),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def fixture():
    raw = [
        page(
            1,
            "LB1143\n2024\nLEGISLATIVE BILL 1143\n"
            "Approved by the Governor April 2, 2024\nIntroduced by Author, 1.\n"
            "A BILL FOR AN ACT relating to public health.\n"
            "Be it enacted by the people of the State of Nebraska,\n"
            "Section 1. The source-proven provision continues\n-1-\n695\n",
        ),
        page(
            2,
            "LB1143\n2024\nwith all its complete language.\n"
            "Sec. 2. The complete final provision is retained.\n-2-\n696\n",
        ),
        page(
            3,
            "LB1144\n2024\nLEGISLATIVE BILL 1144\n"
            "Approved by the Governor April 3, 2024\nIntroduced by Another, 2.\n"
            "A BILL FOR AN ACT relating to other matters.\n"
            "Be it enacted by the people of the State of Nebraska,\n"
            "Section 1. This next law must stay outside the body.\n-1-\n697\n",
        ),
    ]
    other = [
        page(row["page"], row["text"].replace("source-proven", "source\u00adproven")) for row in raw
    ]
    book = {
        "year": 2024,
        "session": "SECOND",
        "volume": 2,
        "pages": 3,
        "sha256": "a" * 64,
        "url": "https://example.org/enacted-laws.pdf",
    }
    context = {
        "bill_id": "original-bill",
        "state": "NE",
        "identifier": "LB 1143",
        "session_identifier": "108",
        "source_introduction_date": "2023-01-11",
        "title": "Original title stays unchanged",
        "unknown_party": None,
    }
    glyph = {
        "identifier": "LB 1143",
        "document": "book",
        "page": 1,
        "PDF_sha256": book["sha256"],
        "compact_page_character_index": compact(raw[0]["text"]).index("source-proven") + 6,
        "source_text_operator": {
            "byte": 173,
            "source_code_unit_bytes": 1,
            "font_encoding": "/WinAnsiEncoding",
            "font_subtype": "/Type1",
            "ToUnicode_present": False,
            "operator": "Tj",
            "string_bytes_hex": b"source\xad".hex(),
            "byte_offset": 6,
            "font_xref": 5,
            "font_base": "/Times-Roman",
        },
        "native_glyph_trace": {"unicode": 45, "glyph_id": 14, "font": "Times-Roman"},
        "same_font_ASCII_reference": {
            "native_glyph_trace": {"unicode": 45, "glyph_id": 14, "font": "Times-Roman"},
            "source_text_operator": {"byte": 45, "font_xref": 5},
        },
        "raw_reader_characters": {"pymupdf": "-", "pypdf": "\u00ad"},
        "native_source_bytes_and_font_glyph_equivalence_verified": True,
    }
    return {"book": {"pymupdf": raw, "pypdf": other}}, [context], [glyph], {"book": book}


def test_exact_source_positions_preserve_both_raw_strings_and_original_dates():
    pages, originals, glyphs, books = fixture()
    before = copy.deepcopy((pages, originals, glyphs))
    views, dispositions, _ = hyphens.qualify(pages, originals, glyphs, books=books)
    assert (pages, originals, glyphs) == before and len(views) == 2
    assert dispositions[0]["disposition"] == "complete_two_reader_source_proven_hyphen_match"
    assert views[0]["text"] != views[1]["text"]
    assert "source-proven" in views[0]["text"] and "source\u00adproven" in views[1]["text"]
    for view in views:
        record = view["source_record"]
        assert record["original_introduction_date"] == "2023-01-11"
        assert record["approval_date"] == "2024-04-02"
        assert record["version_scope"] == "enacted_law_not_introduced"
        assert not record["page_text_trimmed_or_normalized"]
        assert all(view[key] is False for key in FLAGS)
        assert (
            "\n".join(
                pages["book"][record["reader"]][part["page"] - 1]["text"][
                    part["start"] : part["end"]
                ]
                for part in record["page_fragments"]
            )
            == view["text"]
        )
        assert "next law" not in view["text"]


def test_sealed_whitespace_only_law_profile_still_rejects_the_same_pair():
    pages, originals, _, books = fixture()
    views, dispositions, _ = laws.qualify(pages, originals, books=books)
    assert not views and dispositions[0]["disposition"] == "whole_enacted_law_reader_disagreement"


@pytest.mark.parametrize(
    "defect",
    [
        "encoding",
        "subtype",
        "to_unicode",
        "raw_byte",
        "negative_offset",
        "font",
        "glyph",
        "book_sha",
        "unverified",
        "wrong_reference",
    ],
)
def test_unverified_or_different_source_glyph_metadata_fails_closed(defect):
    pages, originals, glyphs, books = fixture()
    glyph = glyphs[0]
    if defect == "encoding":
        glyph["source_text_operator"]["font_encoding"] = "/Identity-H"
    elif defect == "subtype":
        glyph["source_text_operator"]["font_subtype"] = "/Type0"
    elif defect == "to_unicode":
        glyph["source_text_operator"]["ToUnicode_present"] = True
    elif defect == "raw_byte":
        glyph["source_text_operator"]["string_bytes_hex"] = b"source-".hex()
    elif defect == "negative_offset":
        glyph["source_text_operator"]["byte_offset"] = -1
    elif defect == "font":
        glyph["native_glyph_trace"]["font"] = "Different"
    elif defect == "glyph":
        glyph["native_glyph_trace"]["glyph_id"] = 99
    elif defect == "book_sha":
        glyph["PDF_sha256"] = "b" * 64
    elif defect == "unverified":
        glyph["native_source_bytes_and_font_glyph_equivalence_verified"] = False
    elif defect == "wrong_reference":
        glyph["same_font_ASCII_reference"]["source_text_operator"]["font_xref"] = 6
    with pytest.raises(ValueError, match="literal source-byte/font/glyph evidence"):
        hyphens.qualify(pages, originals, glyphs, books=books)


@pytest.mark.parametrize(
    "defect",
    [
        "wrong_position",
        "wrong_page",
        "missing_difference",
        "extra_difference",
        "different_letter",
        "future_introduction",
        "duplicate_identity",
        "wrong_session",
        "missing_footer",
        "missing_enacting_clause",
    ],
)
def test_only_the_exact_witnessed_complete_body_can_qualify(defect):
    pages, originals, glyphs, books = fixture()
    if defect == "wrong_position":
        glyphs[0]["compact_page_character_index"] += 1
    elif defect == "wrong_page":
        glyphs[0]["page"] = 2
    elif defect == "missing_difference":
        pages["book"]["pypdf"][0] = pages["book"]["pymupdf"][0].copy()
    elif defect in {"extra_difference", "different_letter"}:
        old = pages["book"]["pypdf"][1]
        replacement = "com\u00adplete" if defect == "extra_difference" else "different"
        pages["book"]["pypdf"][1] = page(2, old["text"].replace("complete", replacement, 1))
    elif defect == "future_introduction":
        originals[0]["source_introduction_date"] = "2024-04-03"
    elif defect == "duplicate_identity":
        originals.append({**originals[0], "bill_id": "another-original"})
    elif defect == "wrong_session":
        originals[0]["session_identifier"] = "107"
    elif defect in {"missing_footer", "missing_enacting_clause"}:
        for reader in ("pymupdf", "pypdf"):
            index = 1 if defect == "missing_footer" else 0
            old = pages["book"][reader][index]
            a, b = ("-2-", "") if defect == "missing_footer" else ("Be it enacted", "Described")
            pages["book"][reader][index] = page(index + 1, old["text"].replace(a, b, 1))
    views, dispositions, _ = hyphens.qualify(pages, originals, glyphs, books=books)
    assert not views and all(
        row["disposition"] != "complete_two_reader_source_proven_hyphen_match"
        for row in dispositions
    )


def test_generic_dispatch_routes_only_the_separately_typed_schema(tmp_path, monkeypatch):
    from state_politics.bills import archive_text

    (tmp_path / "manifest.json").write_text(json.dumps({"schema": hyphens.SCHEMA}))
    sentinel = object()
    monkeypatch.setattr(hyphens, "load_ne_enacted_hyphen", lambda directory, metadata: sentinel)
    assert archive_text.load_archive(tmp_path, [{"bill_id": "original"}]) is sentinel


def test_builder_refuses_public_output_before_copying_any_source():
    with pytest.raises(ValueError, match="fresh unlinked output"):
        hyphens.build(*(Path("/unused"),) * 4, hyphens.ROOT / "outputs")

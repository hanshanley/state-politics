"""Native print observations preserve full evidence and do not certify model inputs."""

import pytest
from pypdf.errors import PdfReadError

from state_politics.bills.florida import extract_filed_document, parse_print_context

HOUSE = "HB 77 2019\nCODING: legislative markup\nhb0077-00\nPage 1 of 1\n"
SENATE = "Florida Senate - 2019 SB 72\nBy Senator A\n3-00123-19 201972__\n"


@pytest.mark.parametrize(
    "text,identifier,session,original",
    [
        (HOUSE, "HB 77", "2019", True),
        (SENATE, "SB 72", "2019", True),
        ("\uf020 \n" + HOUSE, "HB 77", "2019", True),
        (SENATE.replace("SB 72", "(NP) SB 72"), "SB 72", "2019", True),
        (HOUSE.replace("hb0077", "hb0078"), "HB 77", "2019", False),
        (HOUSE.replace("hb0077-00", "hb0077-01-c1"), "HB 77", "2019", False),
        (HOUSE.replace("HB 77", "CS/HB 77"), "HB 77", "2019", False),
        (HOUSE.replace("HB 77", "ENROLLED HB 77"), "HB 77", "2019", False),
        (SENATE.replace("SB 72", "CS for SB 72"), "SB 72", "2019", False),
        (SENATE.replace("201972__", "201972c1"), "SB 72", "2019", False),
        (HOUSE + "hb0077-00\n", "HB 77", "2019", False),
    ],
)
def test_native_header_requires_matching_original_print_code(text, identifier, session, original):
    result = parse_print_context(text)
    header = result["header"]
    assert header["identifier"] == identifier
    assert header["session_identifier"] == session
    assert header["source_text"] == text[header["source_start"] : header["source_end"]]
    assert result["original_print_observed"] is original
    for code in result["print_codes"]:
        assert code["source_text"] == text[code["source_start"] : code["source_end"]]


def test_body_citations_do_not_become_native_headers():
    assert parse_print_context("An act citing\n" + HOUSE)["header"] is None
    assert parse_print_context(SENATE.replace("SB 72", "SB 72, Engrossed 1"))["header"] is None
    assert parse_print_context(HOUSE.replace("HB 77 2019", "HB 77 2019 ENROLLED"))["header"] is None
    assert parse_print_context("\uf021" + HOUSE)["header"] is None
    assert parse_print_context(SENATE.replace("SB 72", "(Unknown) SB 72"))["header"] is None


def test_corrected_copy_retains_identity_without_becoming_uncorrected_original():
    text = SENATE.replace("SB 72", "(Corrected Copy) SB 72")
    result = extract_filed_document(
        ("<pre>" + text + "</pre>").encode(),
        state="FL", identifier="SB 72", session_identifier="2019",
    )
    observation = result["text_units"][0]["native_print_observation"]
    assert observation["header"]["identifier"] == "SB 72"
    assert observation["header"]["copy_note"] == "(Corrected Copy)"
    assert observation["print_codes"][0]["suffix"] == "__"
    assert observation["original_print_observed"] is False
    assert result["text_units"][0]["text"] == text
    assert result["issues"] == [
        "corrected_copy_not_uncorrected_original", "original_print_not_established",
    ]
    assert result["status"] == "requires_source_review"
    assert result["filing_time_text_certified"] is False
    assert result["training_admission"] is False
    header = observation["header"]
    assert text[header["source_start"]:header["source_end"]] == header["source_text"]


def test_nested_pre_markup_does_not_drop_trailing_source_text():
    body = ("<pre>" + SENATE + "First<pre>Second</pre>Third</pre>").encode()
    result = extract_filed_document(body, state="FL", identifier="SB 72", session_identifier="2019")
    assert "nested_pre_blocks" in result["issues"]
    assert result["text_units"][0]["text"] == SENATE + "FirstSecondThird"


def test_html_preserves_deleted_added_nested_and_non_ascii_source_text():
    body = (
        "<html><style>.Remove{color:red}</style><pre>"
        + SENATE
        + 'A bill to be entitled\nOld <s class="Remove">deleted <span>law</span></s>'
        + ' and <span class="Insert">new &amp; added</span>.<br>Last\u2028line'
        + "</pre><div>Publisher navigation</div></html>"
    ).encode()
    result = extract_filed_document(
        body, state="FL", identifier="SB 0072", session_identifier="2019"
    )
    assert result["status"] == "native_original_print_matches_context"
    unit = result["text_units"][0]
    assert (
        unit["text"]
        == SENATE + "A bill to be entitled\nOld deleted law and new & added.\nLast\u2028line"
    )
    spans = unit["markup_spans"]
    assert (
        "".join(unit["text"][r["start"] : r["end"]] for r in spans if r["kind"] == "deleted")
        == "deleted law"
    )
    assert (
        "".join(unit["text"][r["start"] : r["end"]] for r in spans if r["kind"] == "added")
        == "new & added"
    )
    assert not any(
        result[key]
        for key in (
            "version_identity_certified",
            "filing_time_text_certified",
            "training_admission",
            "evaluation_admission",
            "analytical_admission",
        )
    )


@pytest.mark.parametrize(
    "body,issue",
    [
        (b"<html>Application shell only</html>", "no_native_text_units"),
        (("<pre>" + SENATE).encode(), "unclosed_pre_block"),
        (
            ("<pre>" + SENATE + "</pre><pre>Second block</pre>").encode(),
            "missing_or_multiple_bill_pre_blocks",
        ),
        (
            ("<pre>" + SENATE + "<script>alert(1)</script></pre>").encode(),
            "active_content_inside_bill_pre",
        ),
        (("<pre>" + SENATE + "<span>unclosed</pre>").encode(), "unbalanced_pre_markup"),
        (b"<pre>\xff\xfe", "source_parse_or_extraction_error"),
        (b"Unrecognized source body", "unsupported_body_format"),
        (b"%PDF-1.4\nnot a complete PDF", "source_parse_or_extraction_error"),
    ],
)
def test_unusable_or_ambiguous_source_bytes_are_explicit(body, issue):
    result = extract_filed_document(body, state="FL", identifier="SB 72", session_identifier="2019")
    assert result["status"] == "requires_source_review"
    assert issue in result["issues"]


def test_complete_pdf_pages_survive_context_conflicts_and_page_extraction_errors(monkeypatch):
    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            if self.text is None:
                raise PdfReadError("unreadable page content")
            return self.text

    class Reader:
        def __init__(self, stream):
            self.pages = [Page(HOUSE), Page(HOUSE.replace("2019", "2020")), Page(None)]

    monkeypatch.setattr("state_politics.bills.florida.PdfReader", Reader)
    result = extract_filed_document(
        b"%PDF-retained", state="FL", identifier="HB 77", session_identifier="2019"
    )
    assert [unit["unit_number"] for unit in result["text_units"]] == [1, 2, 3]
    assert result["text_units"][0]["text"] == HOUSE
    assert result["text_units"][1]["text"] == HOUSE.replace("2019", "2020")
    assert result["text_units"][2]["text"] is None
    assert result["extraction_errors"][0]["unit_number"] == 3
    assert "native_context_conflict" in result["issues"]
    assert "source_parse_or_extraction_error" in result["issues"]
    assert result["status"] == "requires_source_review"


@pytest.mark.parametrize(
    "state,identifier,session",
    [("WA", "HB 77", "2019"), ("FL", "HJR 77", "2019"), ("FL", "SB 72", "2019E")],
)
def test_unsupported_source_context_is_not_silently_coerced(state, identifier, session):
    with pytest.raises(ValueError, match="explicit regular-session"):
        extract_filed_document(
            b"source bytes", state=state, identifier=identifier, session_identifier=session
        )

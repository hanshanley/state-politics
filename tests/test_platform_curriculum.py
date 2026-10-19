import pytest

from state_politics.analysis.prepare_platform_curriculum import (
    numbered_span,
    paragraph_span,
    section_span,
)


def test_numbered_unit_keeps_scope_and_excludes_a_trailing_pdf_page_number():
    text = "Title\n\nFirst\n1. First policy.\n 13\n2. Second policy.\n\nNext\n1. Other.\n"
    bounds = section_span(text, "\nFirst\n", "\nNext\n")
    start, end = numbered_span(text, 1, bounds)
    assert text[start:end] == "1. First policy."
    with pytest.raises(ValueError, match="ambiguous"):
        numbered_span(text, 1)


def test_numbered_unit_does_not_truncate_a_policy_at_an_internal_page_break():
    text = "1. Require restoration to the\n 3\n\n original condition.\n2. Another policy.\n"
    start, end = numbered_span(text, 1)
    assert text[start:end] == "1. Require restoration to the\n 3\n\n original condition."


def test_paragraph_selection_preserves_heading_and_preceding_policy_sentences():
    text = "Previous.\n\nHealth\nFirst commitment.\nSecond commitment.\n\nNext."
    start, end = paragraph_span(text, "Second commitment")
    assert text[start:end] == "Health\nFirst commitment.\nSecond commitment."


def test_ambiguous_or_absent_source_selectors_fail_explicitly():
    with pytest.raises(ValueError, match="ambiguous"):
        paragraph_span("Repeated.\n\nRepeated.", "Repeated")
    with pytest.raises(ValueError, match="absent"):
        section_span("No such heading.", "\nMissing\n")
    with pytest.raises(ValueError, match="absent"):
        numbered_span("1. Only policy.", 2)

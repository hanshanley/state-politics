import pytest

from state_politics.analysis.prepare_platform_challenge import bounded_span


def test_bounded_native_unit_preserves_wrapping_numbers_and_internal_page_break():
    text = (
        "Chapter\n\n1588 • Require a complete\n 43\n\n native policy unit.\n"
        "1590 • Another policy.\n"
    )
    start, end = bounded_span(text, "Require a complete", "Another policy")
    assert text[start:end] == "1588 • Require a complete\n 43\n\n native policy unit."


def test_bounded_html_unit_does_not_merge_space_only_blank_lines_or_decode_entities():
    text = (
        "Heading\n \n Support Vermont&rsquo;s public housing.\n \n \n"
        " Increase the minimum wage.\n \n Next.\n"
    )
    start, end = bounded_span(text, "Support Vermont", "Increase the minimum wage")
    assert text[start:end] == " Support Vermont&rsquo;s public housing."


@pytest.mark.parametrize(
    "text,anchor,stop",
    [
        ("One.\nOther.\nOne.\n", "One.", "Other."),
        ("One.\nOther.\nOther.\n", "One.", "Other."),
        ("One.\nOther.\n", "Missing.", "Other."),
        ("One.\nOther.\n", "One.", "Missing."),
        ("One. Other.\n", "One.", "Other."),
    ],
)
def test_bounded_units_fail_on_ambiguous_missing_or_same_line_endpoints(text, anchor, stop):
    with pytest.raises(ValueError, match="absent|ambiguous|complete native unit"):
        bounded_span(text, anchor, stop)

from hashlib import sha256

import pytest

from state_politics.bills.illinois_html import (
    parse_printed_header,
    project_illinois_html,
)


def test_word_body_without_closed_rows_is_not_an_unavailable_shell():
    source = (
        '<html><head><title>$HB0013 103RD GENERAL ASSEMBLY</title>'
        '<style>.WordSection1 { color: black }</style></head>\r\n<body>'
        '<p>103RD GENERAL ASSEMBLY</p>\r\n<p>State of Illinois</p>\r\n'
        '<p>2023 and 2024</p>\r\n<p><span>HB0013</span></p>\r\n'
        '<table><tr><td>Retained header</table>'
        '<p>Complete policy text &amp; <u>new</u> <strike>old</strike> text.</p>'
        '</body></html>'
    )
    projection = project_illinois_html(source)
    assert projection.text == (
        "103RD GENERAL ASSEMBLY\r\nState of Illinois\r\n"
        "2023 and 2024\r\nHB0013\r\n"
        "Retained headerComplete policy text & new old text."
    )
    assert "$HB0013" not in projection.text
    assert "color:" not in projection.text
    header = parse_printed_header(projection.text)
    assert header is not None
    assert (header.measure_type, header.measure_number) == ("HB", 13)
    assert header.printed_identifier == "HB0013"
    assert header.printed_assembly == "103RD"
    assert header.printed_years == "2023 and 2024"
    assert projection.text[header.identifier_start:header.identifier_end] == "HB0013"
    assert [s.tag for s in projection.spans if s.kind == "start_tag"][-4:] == [
        "td", "p", "u", "strike",
    ]


def test_native_xsl_unmatched_child_tags_and_zero_padded_identity():
    source = (
        "<html><head><style>font-size: 15pt</style></head><body>"
        "<table><pre><tr><td></td></tr></td></tr>"
        "103RD GENERAL ASSEMBLY\nState of Illinois\n2023 and 2024<br>HB0015"
        "<br/><code>Only one numbered line: 1</code></pre></table>"
        "</body></html>"
    )
    projection = project_illinois_html(source)
    assert projection.text.endswith("HB0015\nOnly one numbered line: 1")
    header = parse_printed_header(projection.text)
    assert header is not None
    assert (header.measure_type, header.measure_number) == ("HB", 15)
    assert "font-size" not in projection.text


def test_exact_source_and_output_spans_preserve_crlf_entities_and_literal_markup():
    source = (
        "<html><head><!-- note > retained --></head>\r\n"
        "<body>\r\n<u>A&#160;&amp B</u><br><s>old</s>"
        "<span style='display:none'>hidden</span><!-- comment > x -->\r\n"
        "</body></html>"
    )
    projection = project_illinois_html(source)
    assert projection.text == "\r\nA\xa0& B\noldhidden\r\n"
    cursor = 0
    for span in projection.spans:
        raw = source[span.source_start:span.source_end]
        assert sha256(raw.encode()).hexdigest() == span.source_sha256
        if span.character_start is not None:
            assert span.character_start == cursor
            assert projection.text[span.character_start:span.character_end] == span.text
            cursor = span.character_end
    assert cursor == len(projection.text)
    comments = [source[s.source_start:s.source_end] for s in projection.spans
                if s.kind == "comment"]
    assert comments == ["<!-- note > retained -->", "<!-- comment > x -->"]


@pytest.mark.parametrize("source", [
    "", None, "<p>missing body</p>", "<body>unclosed",
    "<body>one</body><body>two</body>", "<body/>",
    "<head>unclosed<body>text</body>", "<body> </body>",
    "<body>text</body>orphaned policy text",
    "<body>text<script>code</script></body>",
    "<body>text<img src='bill.png'></body>",
    "<body>text<!--[if IE]>alternate policy<![endif]--></body>",
    "<body>text<!DOCTYPE html></body>",
])
def test_incomplete_or_unsupported_body_fails_explicitly(source):
    with pytest.raises(ValueError):
        project_illinois_html(source)


@pytest.mark.parametrize("identifier,kind,number", [
    ("HB0015", "HB", 15), ("SB0015", "SB", 15),
    ("HJRCA0001", "HJRCA", 1), ("AM1020178", "AM", 1020178),
])
def test_printed_identity_keeps_type_and_padding(identifier, kind, number):
    text = f"103RD GENERAL ASSEMBLY\nState of Illinois\n2023 and 2024\n{identifier}"
    header = parse_printed_header(text)
    assert header is not None
    assert (header.printed_identifier, header.measure_type, header.measure_number) == (
        identifier, kind, number,
    )


@pytest.mark.parametrize("text", [
    "Other document mentions HB0015 and 103RD GENERAL ASSEMBLY",
    "103RD GENERAL ASSEMBLY\nState of Illinois\n2023 and 2024\nHB0015A",
    "103RD GENERAL ASSEMBLY\nState of Illinois\n2023 and 2024\nHB0015-1",
    "103RD GENERAL ASSEMBLY\nState of Illinois\nHB0015",
])
def test_unsupported_or_body_reference_header_is_not_accepted(text):
    assert parse_printed_header(text) is None

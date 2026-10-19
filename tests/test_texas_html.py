"""Exact source and body-text provenance for native Texas HTML."""

from hashlib import sha256

import pytest

from state_politics.bills.texas_html import project_texas_html


def test_body_excludes_head_and_preserves_literal_formatting_and_entities():
    source = (
        '<html><head><title>HB 2</title><style>td { color: red; }</style></head>'
        '<body>\n<table><tr><td><META name="PGLN" contents="1-1">'
        'A<u title="quoted > boundary">new &amp; &#xE9;</u>'
        '<s>old</s><br>tail&nbsp;</td></tr></table>\n</body></html>'
    )
    result = project_texas_html(source)
    assert result.text == "\nAnew & \u00e9old\ntail\u00a0\n"
    assert "color" not in result.text and "HB 2" not in result.text
    for element in result.elements:
        raw = source[element.source_start:element.source_end]
        assert element.source_sha256 == sha256(raw.encode()).hexdigest()
        assert raw.startswith("<")
        if element.character_start is not None:
            assert element.in_body
            assert element.character_end > element.character_start
    underline = next(element for element in result.elements if element.tag == "u")
    assert underline.attributes == (("title", "quoted > boundary"),)
    assert result.text[underline.character_start:underline.character_end] == "new & \u00e9"
    strike = next(element for element in result.elements if element.tag == "s")
    assert result.text[strike.character_start:strike.character_end] == "old"
    line_break = next(span for span in result.text_spans if span.kind == "line_break")
    assert source[line_break.source_start:line_break.source_end] == "<br>"
    assert line_break.text == "\n"
    for span in result.text_spans:
        raw = source[span.source_start:span.source_end]
        assert span.source_sha256 == sha256(raw.encode()).hexdigest()
        if span.in_body:
            assert result.text[span.character_start:span.character_end] == span.text
        else:
            assert span.character_start is span.character_end is None


def test_repeated_text_multibyte_prefix_and_crlf_keep_distinct_exact_offsets():
    source = '<html><head><title>\u00e9</title></head>\r\n<body><u>x</u><u>x</u></body></html>'
    result = project_texas_html(source)
    assert result.text == "xx"
    first, second = [element for element in result.elements if element.tag == "u"]
    assert first.source_start == source.index("<u>")
    assert second.source_start == source.rindex("<u>")
    assert (first.character_start, first.character_end) == (0, 1)
    assert (second.character_start, second.character_end) == (1, 2)


def test_comments_are_not_text_and_unknown_entities_remain_literal():
    result = project_texas_html(
        '<body>A<!-- hidden -->B<?note ignored?><u/>&unknown; &#65 &#x42;</body>'
    )
    assert result.text == "AB&unknown; A B"
    empty = next(element for element in result.elements if element.tag == "u")
    assert empty.character_start is empty.character_end is None


@pytest.mark.parametrize("source", [
    "",
    "<html>missing body</html>",
    "<body>one</body><body>two</body>",
    "<body>unclosed",
    "<body><u>wrong nesting</body></u>",
    "<body>text</br></body>",
    "<body>   </body>",
    "<body><script>policy-looking code</script></body>",
    "<body><style>policy-looking CSS</style></body>",
    "<body><template>hidden policy</template></body>",
    "<body><noscript>conditional policy</noscript></body>",
    '<body>text<img src="chart.png"></body>',
    "<body><svg>diagram</svg></body>",
])
def test_unsupported_or_ambiguous_document_fails_instead_of_silent_partial_input(source):
    with pytest.raises(ValueError):
        project_texas_html(source)

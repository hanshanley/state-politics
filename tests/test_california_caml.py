"""Native CAML byte offsets, nested markup and flattened-projection provenance."""

from __future__ import annotations

from hashlib import sha256
from xml.etree import ElementTree as ET

import pytest

from state_politics.bills.california_caml import project_caml_source

_NS = "http://lc.ca.gov/legalservices/schemas/caml.1#"
_XHTML = "http://www.w3.org/1999/xhtml"


def document(body: str, *, encoding: str = "UTF-8", body_name: str = "Bill") -> str:
    return (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        f'<MeasureDoc xmlns="{_NS}" xmlns:h="{_XHTML}">'
        '<Description>H &#xE9;</Description>'
        f'<{body_name}>{body}</{body_name}><Metadata>excluded</Metadata></MeasureDoc>'
    )


@pytest.mark.parametrize("body_name", ["Bill", "Resolution"])
def test_nested_markup_maps_exact_native_bytes_and_normalized_text(body_name):
    body = (
        'before<h:span class="add" title="a > b">new'
        '<h:s>old &amp; stale</h:s>tail</h:span>after<h:br/>done'
    )
    raw = document(body, body_name=body_name).encode()
    result = project_caml_source(raw)
    assert result.text == "H \u00e9\n\nbefore new old & stale tail after done"
    nodes = list(ET.fromstring(raw).iter())
    assert len(result.elements) == len(nodes)
    for node, span in zip(nodes, result.elements, strict=True):
        assert span.tag == node.tag
        assert span.attributes == node.attrib
        assert span.source_sha256 == sha256(
            raw[span.source_byte_start:span.source_byte_end]
        ).hexdigest()
        if span.projection_scope != "outside_input":
            expected = " ".join(" ".join(node.itertext()).split())
            if expected:
                assert result.text[span.character_start:span.character_end] == expected
            else:
                assert span.character_start is None and span.character_end is None
    strike = next(span for span in result.elements if span.tag == f"{{{_XHTML}}}s")
    assert raw[strike.source_byte_start:strike.source_byte_end] == b"<h:s>old &amp; stale</h:s>"
    metadata = result.elements[-1]
    assert metadata.projection_scope == "outside_input"
    assert metadata.character_start is None and metadata.character_end is None


def test_entity_cdata_comments_and_processing_instructions_do_not_invent_fragments():
    raw = document("A<!-- ignored -->B<?note ok?><![CDATA[C&D]]><h:i>E</h:i>F").encode()
    result = project_caml_source(raw)
    assert result.body_text == "ABC&D E F"
    italic = next(span for span in result.elements if span.tag == f"{{{_XHTML}}}i")
    assert result.text[italic.character_start:italic.character_end] == "E"
    assert raw[italic.source_byte_start:italic.source_byte_end] == b"<h:i>E</h:i>"


@pytest.mark.parametrize("encoding,bom", [
    ("utf-8", b""),
    ("utf-8", b"\xef\xbb\xbf"),
    ("utf-16le", b"\xff\xfe"),
    ("utf-16be", b"\xfe\xff"),
    ("utf-16le", b""),
    ("utf-16be", b""),
    ("iso-8859-1", b""),
])
def test_declared_encoding_and_multibyte_prefix_do_not_shift_byte_spans(encoding, bom):
    raw = bom + document(
        'pr\u00e9<h:s title="quoted > boundary">same</h:s>post<h:br/>end',
        encoding=encoding,
    ).encode(encoding)
    result = project_caml_source(raw)
    strike = next(span for span in result.elements if span.tag == f"{{{_XHTML}}}s")
    opening = '<h:s title="quoted > boundary">'.encode(encoding)
    closing = "</h:s>".encode(encoding)
    assert strike.source_byte_start == raw.index(opening)
    assert strike.source_byte_end == raw.index(closing) + len(closing)
    assert result.body_text == "pr\u00e9 same post end"
    assert result.text[strike.character_start:strike.character_end] == "same"
    line_break = next(span for span in result.elements if span.tag == f"{{{_XHTML}}}br")
    assert raw[line_break.source_byte_start:line_break.source_byte_end] == "<h:br/>".encode(
        encoding
    )
    assert line_break.character_start is None and line_break.character_end is None


def test_repeated_elements_keep_distinct_source_and_character_locations():
    raw = document("<h:i>same</h:i><h:i>same</h:i>").encode()
    result = project_caml_source(raw)
    first, second = [span for span in result.elements if span.tag == f"{{{_XHTML}}}i"]
    assert first.source_byte_end == second.source_byte_start
    assert first.character_end < second.character_start
    assert result.text[first.character_start:first.character_end] == "same"
    assert result.text[second.character_start:second.character_end] == "same"


@pytest.mark.parametrize("raw,match", [
    (b"", "nonempty original"),
    (b"<broken", "Invalid CAML"),
    (b"<MeasureDoc/>", "native MeasureDoc"),
    (
        f'<MeasureDoc xmlns="{_NS}"><Description>H</Description>'
        "<Bill>B</Bill><Resolution>R</Resolution></MeasureDoc>".encode(),
        "exactly one",
    ),
    (document("   ").encode(), "non-whitespace"),
    (
        b'<!DOCTYPE MeasureDoc [<!ENTITY x "hidden">]><MeasureDoc/>',
        "DTD or entity",
    ),
])
def test_invalid_ambiguous_and_entity_declared_sources_fail_explicitly(raw, match):
    with pytest.raises(ValueError, match=match):
        project_caml_source(raw)

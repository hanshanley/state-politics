"""Project a native Texas HTML body without interpreting legislative formatting."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from typing import Literal

_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


@dataclass(frozen=True)
class HtmlElementSpan:
    element_index: int
    parent_index: int | None
    tag: str
    attributes: tuple[tuple[str, str | None], ...]
    source_start: int
    source_end: int
    source_sha256: str
    in_body: bool
    character_start: int | None
    character_end: int | None


@dataclass(frozen=True)
class HtmlTextSpan:
    parent_index: int | None
    source_start: int
    source_end: int
    source_sha256: str
    kind: Literal["text", "entity", "line_break"]
    text: str
    in_body: bool
    character_start: int | None
    character_end: int | None


@dataclass(frozen=True)
class TexasHtmlProjection:
    text: str
    elements: tuple[HtmlElementSpan, ...]
    text_spans: tuple[HtmlTextSpan, ...]


@dataclass
class _Element:
    parent_index: int | None
    tag: str
    attributes: tuple[tuple[str, str | None], ...]
    start: int
    end: int
    in_body: bool
    text_start: int
    text_end: int


class _BodyProjection(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_starts = [0] + [
            index + 1 for index, character in enumerate(source) if character == "\n"
        ]
        self.elements: list[_Element] = []
        self.stack: list[int] = []
        self.spans: list[HtmlTextSpan] = []
        self.fragments: list[str] = []
        self.cursor = 0
        self.body_count = 0
        self.body_active = False

    def position(self) -> int:
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raw = self.get_starttag_text()
        if raw is None:
            raise ValueError("Texas HTML opening tag has no source span")
        start = self.position()
        if tag == "body":
            self.body_count += 1
            if self.body_count != 1:
                raise ValueError("Texas HTML requires exactly one body")
            self.body_active = True
        if self.body_active and tag in {"script", "style", "template", "noscript"}:
            raise ValueError(f"Unsupported active or conditional content in Texas body: {tag}")
        if self.body_active and tag in {
            "img", "object", "iframe", "embed", "svg", "math", "canvas",
        }:
            raise ValueError(f"Texas body contains non-text content requiring review: {tag}")
        index = len(self.elements)
        self.elements.append(_Element(
            parent_index=self.stack[-1] if self.stack else None,
            tag=tag,
            attributes=tuple(attrs),
            start=start,
            end=start + len(raw) if tag in _VOID_TAGS else 0,
            in_body=self.body_active,
            text_start=self.cursor,
            text_end=self.cursor,
        ))
        if tag not in _VOID_TAGS:
            self.stack.append(index)
        elif tag == "br" and self.body_active:
            self.append_text(raw, "\n", kind="line_break")
            self.elements[index].text_end = self.cursor

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            element = self.elements[self.stack.pop()]
            element.end = element.start + len(self.get_starttag_text() or "")
            if tag == "body":
                self.body_active = False

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS or not self.stack or self.elements[self.stack[-1]].tag != tag:
            raise ValueError(f"Unbalanced Texas HTML closing tag: {tag}")
        start = self.position()
        end = self.source.find(">", start)
        if end < 0:
            raise ValueError("Unterminated Texas HTML closing tag")
        element = self.elements[self.stack.pop()]
        element.end = end + 1
        element.text_end = self.cursor
        if tag == "body":
            self.body_active = False

    def append_text(
        self,
        raw: str,
        rendered: str,
        *,
        kind: Literal["text", "entity", "line_break"] = "text",
    ) -> None:
        start = self.position()
        if self.source[start:start + len(raw)] != raw:
            raise ValueError("Texas HTML text does not match its source span")
        left = self.cursor if self.body_active else None
        if self.body_active:
            self.fragments.append(rendered)
            self.cursor += len(rendered)
        self.spans.append(HtmlTextSpan(
            parent_index=self.stack[-1] if self.stack else None,
            source_start=start,
            source_end=start + len(raw),
            source_sha256=sha256(raw.encode("utf-8")).hexdigest(),
            kind=kind,
            text=rendered,
            in_body=self.body_active,
            character_start=left,
            character_end=self.cursor if self.body_active else None,
        ))

    def handle_data(self, data: str) -> None:
        self.append_text(data, data)

    def entity(self, prefix: str, name: str) -> None:
        start = self.position()
        raw = prefix + name
        if self.source[start + len(raw):start + len(raw) + 1] == ";":
            raw += ";"
        self.append_text(raw, unescape(raw), kind="entity")

    def handle_entityref(self, name: str) -> None:
        self.entity("&", name)

    def handle_charref(self, name: str) -> None:
        self.entity("&#", name)

    def unknown_decl(self, data: str) -> None:
        raise ValueError(f"Unsupported Texas HTML declaration: {data}")


def project_texas_html(source: str) -> TexasHtmlProjection:
    """Retain body text/entities and literal formatting with Unicode source offsets.

    No whitespace is collapsed; explicit br tags contribute mapped newlines.
    No deleted/underlined text is removed. Offsets
    address the supplied decoded source, not raw response bytes or browser layout.
    Malformed/unsupported bodies fail explicitly instead of producing partial input.
    """
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Texas HTML projection requires nonempty decoded source")
    parser = _BodyProjection(source)
    parser.feed(source)
    parser.close()
    if parser.body_count != 1 or parser.body_active or parser.stack:
        raise ValueError("Texas HTML requires one complete, balanced body/document")
    text = "".join(parser.fragments)
    if not text.strip():
        raise ValueError("Texas HTML body has no non-whitespace text")
    elements = []
    for index, element in enumerate(parser.elements):
        left, right = element.text_start, element.text_end
        nonempty = element.in_body and right > left
        elements.append(HtmlElementSpan(
            element_index=index,
            parent_index=element.parent_index,
            tag=element.tag,
            attributes=element.attributes,
            source_start=element.start,
            source_end=element.end,
            source_sha256=sha256(
                source[element.start:element.end].encode("utf-8")
            ).hexdigest(),
            in_body=element.in_body,
            character_start=left if nonempty else None,
            character_end=right if nonempty else None,
        ))
    return TexasHtmlProjection(text, tuple(elements), tuple(parser.spans))

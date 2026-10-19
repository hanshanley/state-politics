"""Observe native Illinois HTML without assuming a balanced table-based DOM."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from typing import Literal

_SpanKind = Literal["start_tag", "end_tag", "text", "entity", "comment", "declaration"]

_UNSUPPORTED = frozenset({
    "script", "style", "template", "noscript", "img", "object", "iframe",
    "embed", "svg", "math", "canvas",
})
_HEADER = re.compile(
    r"\A\s*(?P<assembly>\d+(?:ST|ND|RD|TH))\s+GENERAL\s+ASSEMBLY"
    r"\s+State\s+of\s+Illinois"
    r"\s+(?P<years>\d{4}\s+and\s+\d{4})"
    r"\s+(?P<identifier>(?:HJRCA|SJRCA|HJR|SJR|JSR|HB|SB|HR|SR|AM|EO)"
    r"(?P<number>\d+))(?![\w-])"
)


@dataclass(frozen=True)
class IllinoisHtmlSpan:
    kind: _SpanKind
    source_start: int
    source_end: int
    source_sha256: str
    tag: str | None
    attributes: tuple[tuple[str, str | None], ...]
    text: str | None
    character_start: int | None
    character_end: int | None


@dataclass(frozen=True)
class IllinoisHtmlProjection:
    text: str
    spans: tuple[IllinoisHtmlSpan, ...]


@dataclass(frozen=True)
class IllinoisPrintedHeader:
    printed_assembly: str
    printed_years: str
    printed_identifier: str
    measure_type: str
    measure_number: int
    identifier_start: int
    identifier_end: int


class _Projection(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0] + [i + 1 for i, c in enumerate(source) if c == "\n"]
        self.in_body = False
        self.in_head = False
        self.body_count = 0
        self.cursor = 0
        self.fragments: list[str] = []
        self.spans: list[IllinoisHtmlSpan] = []

    def position(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def emit(
        self, kind: _SpanKind, raw: str, text: str | None = None, *,
        tag: str | None = None,
        attributes: tuple[tuple[str, str | None], ...] = (),
    ) -> None:
        start = self.position()
        if self.source[start:start + len(raw)] != raw:
            raise ValueError("Illinois HTML token does not match its source span")
        left = self.cursor if text is not None and self.in_body else None
        if text is not None and self.in_body:
            self.fragments.append(text)
            self.cursor += len(text)
        self.spans.append(IllinoisHtmlSpan(
            kind, start, start + len(raw), sha256(raw.encode()).hexdigest(),
            tag, attributes, text, left, self.cursor if left is not None else None,
        ))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raw = self.get_starttag_text()
        if raw is None:
            raise ValueError("Illinois HTML opening tag has no source span")
        if tag == "head":
            if self.in_head or self.in_body or self.body_count:
                raise ValueError("Unexpected Illinois HTML head")
            self.in_head = True
        if tag == "body":
            self.body_count += 1
            if self.body_count != 1 or self.in_head:
                raise ValueError("Illinois HTML requires one body outside its head")
            self.in_body = True
        if self.in_body and tag in _UNSUPPORTED:
            raise ValueError(f"Illinois body requires review of unsupported content: {tag}")
        self.emit("start_tag", raw, "\n" if tag == "br" and self.in_body else None,
                  tag=tag, attributes=tuple(attrs))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"head", "body"}:
            raise ValueError(f"Self-closing Illinois HTML {tag} is unsupported")
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "body" and not self.in_body:
            raise ValueError("Illinois HTML body closes without an opening body")
        if tag == "head" and not self.in_head:
            raise ValueError("Illinois HTML head closes without an opening head")
        start = self.position()
        end = self.source.find(">", start)
        if end < 0:
            raise ValueError("Unterminated Illinois HTML closing tag")
        self.emit("end_tag", self.source[start:end + 1], tag=tag)
        if tag == "head":
            self.in_head = False
        elif tag == "body":
            self.in_body = False

    def handle_data(self, data: str) -> None:
        if data.strip() and not self.in_body and not self.in_head:
            raise ValueError("Illinois HTML contains text outside its head/body")
        self.emit("text", data, data)

    def entity(self, prefix: str, name: str) -> None:
        raw = prefix + name
        start = self.position()
        if self.source[start + len(raw):start + len(raw) + 1] == ";":
            raw += ";"
        if not self.in_body and not self.in_head:
            raise ValueError("Illinois HTML contains an entity outside its head/body")
        self.emit("entity", raw, unescape(raw))

    def handle_entityref(self, name: str) -> None:
        self.entity("&", name)

    def handle_charref(self, name: str) -> None:
        self.entity("&#", name)

    def handle_comment(self, data: str) -> None:
        if self.in_body and re.search(r"\[\s*if\b", data, re.I):
            raise ValueError("Illinois body contains a conditional comment requiring review")
        start = self.position()
        ending = re.search(r"--\s*>", self.source[start + 4:])
        if ending is None:
            raise ValueError("Unterminated Illinois HTML comment")
        self.emit("comment", self.source[start:start + 4 + ending.end()])

    def raw_markup(self) -> str:
        start = self.position()
        end = self.source.find(">", start)
        if end < 0:
            raise ValueError("Unterminated Illinois HTML markup")
        return self.source[start:end + 1]

    def handle_decl(self, decl: str) -> None:
        if self.in_body:
            raise ValueError("Illinois HTML contains a declaration inside its body")
        self.emit("declaration", self.raw_markup())

    def handle_pi(self, data: str) -> None:
        raise ValueError("Illinois HTML processing instructions require review")

    def unknown_decl(self, data: str) -> None:
        raise ValueError(f"Illinois HTML declaration requires review: {data}")


def project_illinois_html(source: str) -> IllinoisHtmlProjection:
    """Preserve body characters, entities and br newlines with decoded-source offsets.

    Tokens are lexical observations, not inferred DOM ancestry. Native XSL can have
    unmatched child tags; Word bills need not have table rows. No CSS visibility,
    legal insert/delete semantics or source character encoding is certified here.
    """
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Illinois HTML requires nonempty decoded source")
    parser = _Projection(source)
    parser.feed(source)
    parser.close()
    if parser.body_count != 1 or parser.in_body or parser.in_head:
        raise ValueError("Illinois HTML requires one complete body and a closed head")
    end = 0
    for span in parser.spans:
        if span.source_start != end:
            raise ValueError("Illinois HTML contains unaccounted source characters")
        end = span.source_end
    if end != len(source):
        raise ValueError("Illinois HTML contains an unaccounted source tail")
    text = "".join(parser.fragments)
    if not text.strip():
        raise ValueError("Illinois HTML body has no non-whitespace text")
    return IllinoisHtmlProjection(text, tuple(parser.spans))


def parse_printed_header(text: str) -> IllinoisPrintedHeader | None:
    """Observe the literal leading GA/year/typed-number header, not legal identity."""
    if not isinstance(text, str):
        raise ValueError("Illinois printed header requires text")
    match = _HEADER.match(text)
    if match is None:
        return None
    identifier = match["identifier"]
    return IllinoisPrintedHeader(
        match["assembly"], match["years"], identifier,
        identifier[:-len(match["number"])], int(match["number"]),
        match.start("identifier"), match.end("identifier"),
    )

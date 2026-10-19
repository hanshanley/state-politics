"""Map native CAML elements to raw bytes and the existing flattened text projection.

Element names and attributes are observations, not certified legislative semantics.
No inserted/deleted text is removed, and no filing-time or analytical admission is made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal
from xml.parsers import expat

_CAML = "{http://lc.ca.gov/legalservices/schemas/caml.1#}"
ProjectionScope = Literal["header", "body", "outside_input"]


@dataclass(frozen=True)
class CamlElementSpan:
    element_index: int
    parent_index: int | None
    tag: str
    attributes: dict[str, str]
    source_byte_start: int
    source_byte_end: int
    source_sha256: str
    projection_scope: ProjectionScope
    character_start: int | None
    character_end: int | None


@dataclass(frozen=True)
class CamlProjection:
    header_name: str
    body_name: str
    header_text: str
    body_text: str
    text: str
    elements: tuple[CamlElementSpan, ...]


@dataclass
class _Element:
    parent_index: int | None
    tag: str
    attributes: dict[str, str]
    start: int
    opening_end: int
    empty: bool
    end: int = 0
    pieces: list[list[str] | int] = field(default_factory=list)


def _expanded_name(name: str) -> str:
    return "{" + name if "}" in name else name


def _syntax_encoding(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"<\x00?\x00", b"<\x00")):
        return "utf-16-le"
    if raw.startswith((b"\xfe\xff", b"\x00<\x00?", b"\x00<")):
        return "utf-16-be"
    return "ascii"


def _tag_end(raw: bytes, start: int, encoding: str) -> int:
    width = len(">".encode(encoding))
    quotes = {'"'.encode(encoding), "'".encode(encoding)}
    quote: bytes | None = None
    position = start + width
    while position < len(raw):
        token = raw[position:position + width]
        if quote is not None:
            if token == quote:
                quote = None
        elif token in quotes:
            quote = token
        elif token == ">".encode(encoding):
            return position + width
        position += width
    raise ValueError(f"Unterminated CAML element at byte {start}")


def project_caml_source(raw_xml: bytes) -> CamlProjection:
    """Retain every native element and map both selected subtrees without text loss."""
    if not isinstance(raw_xml, bytes) or not raw_xml:
        raise ValueError("CAML mapping requires nonempty original XML bytes")

    encoding = _syntax_encoding(raw_xml)
    empty_suffix = "/>".encode(encoding)
    elements: list[_Element] = []
    stack: list[int] = []
    parser = expat.ParserCreate(namespace_separator="}")

    def start_element(name: str, attributes: dict[str, str]) -> None:
        start = parser.CurrentByteIndex
        opening_end = _tag_end(raw_xml, start, encoding)
        index = len(elements)
        parent = stack[-1] if stack else None
        if parent is not None:
            elements[parent].pieces.append(index)
        elements.append(_Element(
            parent_index=parent,
            tag=_expanded_name(name),
            attributes={_expanded_name(key): value for key, value in attributes.items()},
            start=start,
            opening_end=opening_end,
            empty=raw_xml[start:opening_end].endswith(empty_suffix),
        ))
        stack.append(index)

    def end_element(_name: str) -> None:
        element = elements[stack.pop()]
        element.end = (
            element.opening_end if element.empty
            else _tag_end(raw_xml, parser.CurrentByteIndex, encoding)
        )

    def character_data(text: str) -> None:
        if not stack:
            return
        pieces = elements[stack[-1]].pieces
        if pieces and isinstance(pieces[-1], list):
            pieces[-1].append(text)
        else:
            pieces.append([text])

    def reject_declaration(*_args: object) -> None:
        raise ValueError("CAML source mapping does not support DTD or entity declarations")

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = character_data
    parser.StartDoctypeDeclHandler = reject_declaration
    parser.EntityDeclHandler = reject_declaration
    parser.ExternalEntityRefHandler = reject_declaration
    try:
        parser.Parse(raw_xml, True)
    except expat.ExpatError as exc:
        raise ValueError(f"Invalid CAML XML: {exc}") from exc

    if not elements or elements[0].tag != _CAML + "MeasureDoc":
        raise ValueError("CAML source requires a native MeasureDoc root")
    headers = [
        index for index, element in enumerate(elements)
        if element.parent_index == 0 and element.tag == _CAML + "Description"
    ]
    bodies = [
        index for index, element in enumerate(elements)
        if element.parent_index == 0
        and element.tag in {_CAML + "Bill", _CAML + "Resolution", _CAML + "GRP"}
    ]
    if len(headers) != 1 or len(bodies) != 1:
        raise ValueError(
            "CAML source requires exactly one Description and one Bill, Resolution or GRP"
        )

    positions: dict[int, tuple[ProjectionScope, int | None, int | None]] = {}

    def project(root_index: int, scope: ProjectionScope, offset: int) -> str:
        fragments: list[str] = []
        cursor = offset

        def visit(index: int) -> None:
            nonlocal cursor
            before = cursor
            separator = int(bool(fragments))
            for piece in elements[index].pieces:
                if isinstance(piece, int):
                    visit(piece)
                else:
                    text = " ".join("".join(piece).split())
                    if text:
                        cursor += int(bool(fragments)) + len(text)
                        fragments.append(text)
            positions[index] = (
                scope, before + separator if cursor > before else None,
                cursor if cursor > before else None,
            )

        visit(root_index)
        return " ".join(fragments)

    header_text = project(headers[0], "header", 0)
    body_text = project(bodies[0], "body", len(header_text) + 2)
    if not header_text or not body_text:
        raise ValueError("CAML Description and body must contain non-whitespace text")
    spans = tuple(
        CamlElementSpan(
            element_index=index,
            parent_index=element.parent_index,
            tag=element.tag,
            attributes=element.attributes,
            source_byte_start=element.start,
            source_byte_end=element.end,
            source_sha256=sha256(raw_xml[element.start:element.end]).hexdigest(),
            projection_scope=positions.get(index, ("outside_input", None, None))[0],
            character_start=positions.get(index, ("outside_input", None, None))[1],
            character_end=positions.get(index, ("outside_input", None, None))[2],
        )
        for index, element in enumerate(elements)
    )
    return CamlProjection(
        header_name="Description",
        body_name=elements[bodies[0]].tag.removeprefix(_CAML),
        header_text=header_text,
        body_text=body_text,
        text=header_text + "\n\n" + body_text,
        elements=spans,
    )

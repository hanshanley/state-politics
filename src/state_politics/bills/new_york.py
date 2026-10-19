"""Observe paired New York print headers without certifying legal identity."""

from __future__ import annotations

import re
from dataclasses import dataclass

_JOINT_HEADER = re.compile(
    r"\A[ \t\r\n]*STATE[ \t]+OF[ \t]+NEW[ \t]+YORK[ \t]*\r?\n"
    r"[ \t]*_+[ \t]*\r?\n"
    r"[ \t]*(?P<senate>S\.[ \t]+(?P<senate_number>[1-9][0-9]*))[ \t]+"
    r"(?P<assembly>A\.[ \t]+(?P<assembly_number>[1-9][0-9]*))[ \t]*\r?\n"
    r"(?:[ \t]*(?P<session>[0-9]{4}-[0-9]{4}[ \t]+Regular[ \t]+Sessions)"
    r"[ \t]*\r?\n)?"
    r"[ \t]*SENATE[ \t]+-[ \t]+ASSEMBLY[ \t]*\r?\n"
    r"[ \t]*(?P<date>(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)[ \t]+[0-9]{1,2},[ \t]+[0-9]{4})"
    r"[ \t]*\r?\n"
    r"[ \t]*_+[ \t]*\r?\n"
    r"[ \t]*IN[ \t]+SENATE[ \t]+--"
)


@dataclass(frozen=True)
class JointPrintHeader:
    senate_identifier: str
    assembly_identifier: str
    senate_source_start: int
    senate_source_end: int
    assembly_source_start: int
    assembly_source_end: int
    printed_session: str | None
    session_source_start: int | None
    session_source_end: int | None
    printed_date: str
    date_source_start: int
    date_source_end: int
    source_start: int
    source_end: int


def parse_joint_print_header(first_page: str) -> JointPrintHeader | None:
    """Match the observed base-print preamble, not numbers elsewhere in a bill.

    Both chamber identities remain distinct. An absent session stays absent;
    the literal printed date is not interpreted as a filing or version date.
    Offsets address the exact supplied reader text, without whitespace rewriting.
    Nonmatching, including amended-print, formats remain unsupported observations.
    """
    if not isinstance(first_page, str):
        raise ValueError("New York joint-header parsing requires first-page text")
    match = _JOINT_HEADER.match(first_page)
    if match is None:
        return None
    session_present = match["session"] is not None
    return JointPrintHeader(
        senate_identifier=f"S {match['senate_number']}",
        assembly_identifier=f"A {match['assembly_number']}",
        senate_source_start=match.start("senate"),
        senate_source_end=match.end("senate"),
        assembly_source_start=match.start("assembly"),
        assembly_source_end=match.end("assembly"),
        printed_session=match["session"],
        session_source_start=match.start("session") if session_present else None,
        session_source_end=match.end("session") if session_present else None,
        printed_date=match["date"],
        date_source_start=match.start("date"),
        date_source_end=match.end("date"),
        source_start=match.start(),
        source_end=match.end(),
    )

"""Observe the reviewed withdrawal-only Missouri Senate cover, not policy text."""

from __future__ import annotations

import re

_WITHDRAWAL_NOTICE = re.compile(
    r"\A\s*(?P<session_heading>SECOND\s+REGULAR\s+SESSION)\s+"
    r"\[WITHDRAWN\]\s+SENATE\s+BILL\s+NO\.\s+(?P<number>[1-9][0-9]*)\s+"
    r"(?P<assembly>102ND\s+GENERAL\s+ASSEMBLY)\s+"
    r"INTRODUCED\s+BY\s+SENATOR\s+(?P<sponsor>[A-Z][A-Z .'-]*?)\.\s+"
    r"(?P<print_code>[0-9]+S\.[0-9]{2}W)\s+"
    r"KRISTINA\s+MARTIN,\s+Secretary\s+WITHDRAWN\s*(?:\uf0fc\s*)?\Z"
)


def parse_withdrawal_notice(text: str) -> dict | None:
    """Require the complete observed cover grammar; never match a body keyword."""
    if not isinstance(text, str):
        raise ValueError("Missouri withdrawal notice parsing requires text")
    match = _WITHDRAWAL_NOTICE.fullmatch(text)
    if match is None:
        return None
    return {
        "identifier": f"SB {match['number']}",
        "session_heading": match["session_heading"],
        "assembly": match["assembly"],
        "sponsor": match["sponsor"],
        "print_code": match["print_code"],
        "source_start": match.start(),
        "source_end": match.end(),
        "source_text": match[0],
        "print_code_source_start": match.start("print_code"),
        "print_code_source_end": match.end("print_code"),
    }

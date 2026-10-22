"""Own-document Texas identities in research text, not dates inferred from citations."""

import re

GAP = r"\s+(?:\d{1,3}\s+)?"
ABBR = r"[HS]\.?\s*(?:[CJ]\.?\s*)?[BR]\.?"
VALID_TYPES = {"HB", "SB", "HR", "SR", "HCR", "SCR", "HJR", "SJR"}
BROWSER = re.compile(
    r"^\s*(?P<leg>\d{2,3})\s*\(\s*(?P<kind>R|[1-9])\s*\)\s*"
    r"(?P<type>" + ABBR + r")\s*(?P<number>\d+)\s*-\s*"
    r"(?:Introduced|Engrossed|Enrolled|Comm(?:ittee)?\.?\s*Sub(?:stitute)?\.?)"
    r"\s+version\s*-\s*Bill\s+Text", re.I,
)
DRAFT = re.compile(r"\b(?P<leg>\d{2,3})\s*R(?=\d+\b)", re.I)
NUMBER = re.compile(
    r"(?P<type>" + ABBR + r")\s*(?:\d{1,3}\s+)?(?:No\.?|Number)\s*(?P<number>\d+)", re.I,
)
CERTIFICATION = re.compile(
    r"\bI\s+(?:hereby\s+)?certify\s+that\s+(?P<type>" + ABBR
    + r")\s*(?:No\.?|Number)\s*(?P<number>\d+)\s+was\s+(?:unanimously\s+)?"
    r"(?:adopted|passed)\b", re.I,
)
OPERATIVE = re.compile(
    r"\bBE" + GAP + r"IT" + GAP + r"(?:ENACTED|RESOLVED)\b|\bRESOLVED\s*,", re.I,
)
STATE = re.compile(r"\bSTATE" + GAP + r"OF" + GAP + r"(?P<state>[A-Z]+)\b", re.I)
RESOLVING_SESSION = re.compile(
    r"\bRESOLVED\s*,\s*That\s+the\s+"
    r"(?:(?:House\s+of\s+Representatives|Senate)\s+of\s+the\s+)?"
    r"(?P<leg>\d{2,3})(?:st|nd|rd|th)\s+"
    r"(?:Texas\s+Legislature|Legislature\s+of\s+the\s+State\s+of\s+Texas)"
    r"\s*,?\s*(?P<kind>Regular\s+Session|(?P<called>[1-9])(?:st|nd|rd|th)"
    r"\s+Called\s+Session)\b", re.I,
)
CONTENT = re.compile(
    r"\b(?:AN\s+ACT|A\s+JOINT\s+RESOLUTION|SENATE\s+(?:JOINT\s+)?RESOLUTION|WHEREAS)\b",
    re.I,
)


def _view(text):
    def replace(match):
        end = match.start()
        while end and text[end - 1].isspace():
            end -= 1
        if re.search(r"(?:No\.?|Number)$", text[max(0, end - 7):end], re.I):
            return match[0]
        return " " * len(match[0])
    return re.sub(r"(?m)^[ \t]*\d{1,3}[ \t]*(?=\r?$)", replace, text)


def _identifier(match):
    kind = re.sub(r"[^A-Z]", "", match["type"].upper())
    return f"{kind} {int(match['number'])}" if kind in VALID_TYPES else None


def parse_texas_identity(text):
    def failure(reason):
        return {"valid": False, "reason": reason}

    if not isinstance(text, str) or not text.strip():
        return failure("missing_source_text")
    view = _view(text)
    operative = OPERATIVE.search(view)
    if not operative:
        return failure("no_operative_enacting_or_resolving_clause")
    venue = next((m for m in STATE.finditer(view) if m["state"].upper() == "TEXAS"), None)
    if venue is None:
        return failure("no_explicit_own_state")
    enacting = re.search(
        r"\bBE" + GAP + r"IT" + GAP + r"(?:ENACTED|RESOLVED)" + GAP
        + r"BY" + GAP + r"(?:THE" + GAP + r")?"
        r"(?:LEGISLATURE|SENATE|HOUSE" + GAP + r"OF" + GAP + r"REPRESENTATIVES)"
        + GAP + r"OF" + GAP + r"(?:THE" + GAP + r")?STATE" + GAP
        + r"OF" + GAP + r"(?P<state>[A-Z]+)", view, re.I,
    )
    if enacting and enacting["state"].upper() != "TEXAS":
        return failure("conflicting_own_enacting_state")
    tail = view[operative.end():]
    if len(tail) < 80 or len(re.findall(r"\b[A-Za-z]{2,}\b", tail)) < 12:
        return failure("insufficient_substantive_operative_text")
    beginning = CONTENT.search(view)
    header = view[:beginning.start() if beginning else operative.start()]
    browser, draft = BROWSER.search(header), DRAFT.search(header)
    resolving = RESOLVING_SESSION.search(view)
    numbers = list(NUMBER.finditer(header))
    evidence = [operative, venue]
    if browser:
        identifier = _identifier(browser)
        if identifier is None or {_identifier(m) for m in numbers} != {identifier}:
            return failure("missing_or_conflicting_printed_own_identifier")
        session = {
            "kind": "regular" if browser["kind"].upper() == "R" else "called",
            "legislature": browser["leg"],
        }
        if session["kind"] == "called":
            session["called_session_number"] = int(browser["kind"])
        if draft and (draft["leg"] != session["legislature"] or session["kind"] != "regular"):
            return failure("conflicting_own_drafting_session")
        evidence.append(browser)
    elif draft:
        identifiers = {_identifier(m) for m in numbers}
        if len(identifiers) != 1 or None in identifiers:
            return failure("missing_or_ambiguous_own_texas_bill_header")
        identifier = identifiers.pop()
        session = {"kind": "regular", "legislature": draft["leg"]}
        evidence.append(draft)
    elif resolving:
        numbers = list(CERTIFICATION.finditer(view))
        identifiers = {_identifier(m) for m in numbers}
        if len(identifiers) != 1 or None in identifiers:
            return failure("missing_or_ambiguous_own_texas_certification")
        identifier = identifiers.pop()
        session = {
            "kind": "called" if resolving["called"] else "regular",
            "legislature": resolving["leg"],
        }
        if resolving["called"]:
            session["called_session_number"] = int(resolving["called"])
        evidence.append(resolving)
    else:
        return failure("no_own_texas_session_header_or_explicit_resolving_session")
    return {
        "valid": True, "state": "TX", "identifier": identifier, "session": session,
        "printed_evidence": [
            {"start": match.start(), "end": match.end(), "text": text[match.start():match.end()]}
            for match in [*evidence, *numbers]
        ],
    }


def matches_texas_session(identity, candidate):
    if identity["state"] != candidate["state"] or identity["identifier"] != candidate["identifier"]:
        return False
    session = identity["session"]
    name = candidate.get("session_name") or ""
    if session["kind"] == "regular":
        return (session["legislature"] == "88" and candidate["session_identifier"] == "88"
                and name == "88th Legislature (2023)")
    match = re.fullmatch(
        r"(?P<leg>\d+)(?:st|nd|rd|th) Legislature, "
        r"(?P<called>\d+)(?:st|nd|rd|th) Called Session \(2023\)", name,
    )
    return bool(match and match["leg"] == session["legislature"]
                and int(match["called"]) == session["called_session_number"])

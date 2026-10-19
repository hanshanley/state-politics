"""Extract complete Florida bill text with explicit native-print/context observations."""

from __future__ import annotations

import hashlib
import io
import re
from html.parser import HTMLParser

from pypdf import PdfReader
from pypdf.errors import PyPdfError

_HOUSE = re.compile(
    r"[\s\uf020]*(?P<enrolled>ENROLLED\s+)?(?P<substitutes>(?:CS/)*)HB\s+"
    r"(?P<number>\d+)(?:,\s*Engrossed\s+(?P<engrossed>\d+))?\s+"
    r"(?P<year>20\d{2})[ \t]*(?=\r?\n|\Z)"
)
_SENATE = re.compile(
    r"\s*Florida\s+Senate\s*-\s*(?P<year>20\d{2})\s+"
    r"(?:\(NP\)\s+|(?P<copy_note>\(Corrected Copy\))\s+)?"
    r"(?P<substitutes>(?:(?:CS/)*CS\s+for\s+)?)SB\s+(?P<number>\d+)[ \t]*(?=\r?\n|\Z)"
)
_HOUSE_CODE = re.compile(
    r"(?m)^[ \t]*hb(?P<number>\d+)[ \t]*-[ \t]*(?P<version>\d{2})"
    r"(?:-(?P<suffix>[a-z]\d+|er))?[ \t]*$",
    re.I,
)
_SENATE_CODE = re.compile(
    r"(?<!\w)(?P<year>20\d{2})(?P<number>\d+)(?P<suffix>__|c\d+|e\d+|er)(?!\w)"
)
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def parse_print_context(text: str) -> dict:
    """Observe an anchored publisher header and print code, never a body citation."""
    if not isinstance(text, str):
        raise ValueError("native Florida print parsing requires text")
    house = _HOUSE.match(text)
    header = house or _SENATE.match(text)
    if header is None:
        return {"header": None, "print_codes": [], "original_print_observed": False}
    chamber = "HB" if house else "SB"
    policy_start = re.search(r"A\s+bill\s+to\s+be\s+entitled", text, re.I)
    end = policy_start.start() if policy_start else header.end() + 2000
    codes = []
    for match in (_HOUSE_CODE if house else _SENATE_CODE).finditer(text[:end]):
        codes.append(
            {
                **match.groupdict(),
                "source_start": match.start(),
                "source_end": match.end(),
                "source_text": match[0],
            }
        )
    original = False
    if len(codes) == 1:
        code = codes[0]
        original = (
            int(code["number"]) == int(header["number"])
            and not header["substitutes"]
            and not header.groupdict().get("copy_note")
            and (
                (
                    code["version"] == "00"
                    and code["suffix"] is None
                    and header["enrolled"] is None
                    and header["engrossed"] is None
                )
                if house
                else (code["suffix"] == "__" and code["year"] == header["year"])
            )
        )
    return {
        "header": {
            "identifier": f"{chamber} {int(header['number'])}",
            "session_identifier": header["year"],
            "copy_note": header.groupdict().get("copy_note"),
            "source_start": header.start(),
            "source_end": header.end(),
            "source_text": header[0],
        },
        "print_codes": codes,
        "original_print_observed": original,
    }


class _BillPre(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.units = []
        self.active = False
        self.pre_depth = 0
        self.stack = []
        self.issues = set()

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            if self.active:
                self.issues.add("nested_pre_blocks")
                self.pre_depth += 1
                return
            self.active = True
            self.pre_depth = 1
            self.stack = []
            self.units.append({"text": "", "markup_spans": []})
        elif self.active:
            if tag in {"script", "style"}:
                self.issues.add("active_content_inside_bill_pre")
            classes = (dict(attrs).get("class") or "").casefold().split()
            kinds = set()
            if tag in {"s", "strike", "del"} or "remove" in classes:
                kinds.add("deleted")
            if tag == "ins" or "insert" in classes:
                kinds.add("added")
            if tag == "br":
                self.handle_data("\n")
            elif tag not in _VOID_TAGS:
                self.stack.append((tag, kinds))

    def handle_endtag(self, tag):
        if tag == "pre":
            if self.pre_depth > 1:
                self.pre_depth -= 1
                return
            if not self.active or self.stack:
                self.issues.add("unbalanced_pre_markup")
            self.active = False
            self.pre_depth = 0
            self.stack = []
        elif self.active and tag not in _VOID_TAGS:
            if not self.stack or self.stack[-1][0] != tag:
                self.issues.add("unbalanced_pre_markup")
            else:
                self.stack.pop()

    def handle_data(self, data):
        if self.active:
            unit = self.units[-1]
            start = len(unit["text"])
            unit["text"] += data
            for kind in sorted({kind for _, kinds in self.stack for kind in kinds}):
                unit["markup_spans"].append(
                    {"start": start, "end": len(unit["text"]), "kind": kind}
                )


def extract_filed_document(
    body: bytes,
    *,
    state: str,
    identifier: str,
    session_identifier: str,
) -> dict:
    """Retain every page/pre block; failures and nonmatching native prints stay explicit."""
    bill = re.fullmatch(r"(HB|SB)\s*(\d+)", identifier) if isinstance(identifier, str) else None
    if (
        state != "FL"
        or bill is None
        or not isinstance(session_identifier, str)
        or not re.fullmatch(r"20\d{2}", session_identifier)
    ):
        raise ValueError("Florida extraction requires an explicit regular-session HB/SB context")
    if not isinstance(body, bytes) or not body:
        raise ValueError("Florida extraction requires nonempty retained response bytes")
    expected = f"{bill[1]} {int(bill[2])}"
    units, errors, issues = [], [], set()
    prefix = body.removeprefix(b"\xef\xbb\xbf").lstrip()
    media_type = (
        "application/pdf"
        if body.startswith(b"%PDF")
        else "text/html"
        if prefix.startswith(b"<")
        else "unrecognized"
    )
    if media_type == "application/pdf":
        try:
            pdf = PdfReader(io.BytesIO(body))
            for number, page in enumerate(pdf.pages, 1):
                try:
                    text = page.extract_text() or ""
                except (PyPdfError, ValueError) as exc:
                    text = None
                    errors.append(
                        {
                            "unit_number": number,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        }
                    )
                units.append(
                    {
                        "unit_number": number,
                        "unit_kind": "pdf_page",
                        "text": text,
                        "markup_spans": [],
                    }
                )
        except (PyPdfError, ValueError) as exc:
            errors.append(
                {"unit_number": None, "error_type": type(exc).__name__, "error_message": str(exc)}
            )
    elif media_type == "text/html":
        try:
            html = body.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            errors.append(
                {"unit_number": None, "error_type": type(exc).__name__, "error_message": str(exc)}
            )
        else:
            parser = _BillPre()
            parser.feed(html)
            parser.close()
            issues.update(parser.issues)
            if parser.active:
                issues.add("unclosed_pre_block")
            if len(parser.units) != 1:
                issues.add("missing_or_multiple_bill_pre_blocks")
            units = [
                {"unit_number": number, "unit_kind": "html_pre", **unit}
                for number, unit in enumerate(parser.units, 1)
            ]
    else:
        issues.add("unsupported_body_format")
    if errors:
        issues.add("source_parse_or_extraction_error")
    if not units:
        issues.add("no_native_text_units")
    for unit in units:
        text = unit["text"]
        observation = (
            parse_print_context(text)
            if text
            else {
                "header": None,
                "print_codes": [],
                "original_print_observed": False,
            }
        )
        unit["native_print_observation"] = observation
        if not text or not text.strip():
            issues.add("empty_or_unreadable_native_text_unit")
        header = observation["header"]
        if header is None:
            issues.add("unrecognized_native_header")
        elif header["identifier"] != expected or header["session_identifier"] != session_identifier:
            issues.add("native_context_conflict")
        if header is not None and header["copy_note"] is not None:
            issues.add("corrected_copy_not_uncorrected_original")
        if not observation["original_print_observed"]:
            issues.add("original_print_not_established")
    return {
        "source_sha256": hashlib.sha256(body).hexdigest(),
        "observed_media_type": media_type,
        "state": state,
        "identifier": identifier,
        "session_identifier": session_identifier,
        "status": "native_original_print_matches_context"
        if not issues
        else "requires_source_review",
        "issues": sorted(issues),
        "extraction_errors": errors,
        "text_units": units,
        "version_identity_certified": False,
        "filing_time_text_certified": False,
        "training_admission": False,
        "evaluation_admission": False,
        "analytical_admission": False,
    }

"""Build/replay bounded NJ State Library evidence without network access.

Both installed PDF readers are retained independently, including every ancillary
page. An enacted version without a legislature line uses a separately identified
same-bill cover as an explicit session witness, never as appended policy text.

Offline usage::

    python -m state_politics.bills.nj_library_text build \
      --source-dir data/processed/remaining-hi-nj-independent-corpus-20261022-v1 \
      --gap-queue outputs/recreated-2023-2024-v11/chart-data/missing_retained_text.parquet \
      --out-dir data/processed/nj-library-text-20261022-v1
    python -m state_politics.bills.nj_library_text verify --directory PACKET

An optional --batch-list (same format as source-batch-first4.json) and its
--batch-sha256 add explicitly pinned PDFs. The original four-file batch and queue
remain mandatory; neither the growing parent directory nor its ledger is sealed.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import shutil
import stat
import warnings
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq
import pymupdf
import pypdf

SCHEMA = "state-politics.nj-library-text.v1"
PROVIDER = "New Jersey State Library legislative histories"
STATUS = "independent_first_party_archive_not_filing_time_certified"
BATCH_NAME = "source-batch-first4.json"
QUEUE_NAME = "outputs/recreated-2023-2024-v11/chart-data/missing_retained_text.parquet"
BATCH_SHA256 = "83ad9cfc02469648e9e19890fb6e051c938a2b9fe2ac27b5587919eb584d81ae"
GAP_SHA256 = "0ad1a0fdb9cbc627283d7ad28510584ad265501ee825c295b17265ab57ad0167"
FIRST4_MANIFEST_SHA256 = "4bb1f7fbb4aedb1b8bab9a59511413ad0339dabc31481b13c9b7a442709a02ef"
FIRST4_PRODUCER = {
    "sha256": "5089089aa6e2fa23620ab6088e8ff152c0603d21ffbd0714616144847ae1fd74",
    "bytes": 51557,
}
LEGACY_PRODUCERS = {
    FIRST4_MANIFEST_SHA256: FIRST4_PRODUCER,
    "43dd2b81cc743101a147f4fc81391c5be78a7320df38ac19e33f5fbf92d329d7": {
        "sha256": "30d7b5cc7ba3ad8c864f92ea7d6d3ee6d19364aad9bf08f51874801faf591952",
        "bytes": 54426,
    },
}
STRICT_2023_PRODUCER = {
    "sha256": "072353f61a0c9cd74a5cd8fc74b9b5caea70945c0a21b3d6d8120788914bef70",
    "bytes": 54845,
}
COMPATIBLE_PRODUCERS = {
    "a27a57b4f72d43f0fc4235713e23b994bebc1a39f49f2284c2a990c1aa70df30":
        STRICT_2023_PRODUCER,
}
TOOLS = {"pymupdf": "1.28.0", "pypdf": "6.14.2"}
FLAGS = (
    "scientific_approval", "model_input_approved", "training_admission",
    "analytical_admission", "filing_time_text_certified", "publication_approved",
    "party_attribution_approved", "training_approved", "publisher_original_verified",
    "source_rights_approved", "source_date_or_party_inferred", "introduced_version_certified",
)
PINNED_PDFS = {
    "raw/0003-nj-2023-chapter183.body": (
        "5d284354be6e8daaeb9817c8736ac93b0f68495821f8e51101385be859484c74", 643995, 10,
        ("S 3782", "A 5398"),
    ),
    "raw/0007-nj-2023-chapter13-pdf.body": (
        "f189792a3edd4d1a42c0d77c2d9006f6fb9ff56f8f48c442a9cc5a722c23e8df", 1280666, 18,
        ("A 5086", "S 3491"),
    ),
    "raw/0008-nj-2023-chapter144-pdf.body": (
        "9b7fd09c573356e0775008d1ba82172387d32d8a284b883d2fc1c65bae85fba7", 1171630, 31,
        ("A 5329", "S 3734"),
    ),
    "raw/0009-nj-2023-chapter116-pdf.body": (
        "8c514241ff9b64a1a3a0c650daf68a6fd6f954c4cc0434018e00dbd3850a3f0c", 865362, 21,
        ("S 3444", "A 5211"),
    ),
}
PRODUCTS = {
    "input_gap_queue.parquet", "context_inventory.parquet", "original_queue_rows.jsonl",
    "pages.jsonl", "documents.jsonl", "versions.jsonl", "views.jsonl",
    "page_dispositions.jsonl", "report.json", "producer/nj_library_text.py",
    "source_inventory.json", "consumed_input_hashes.json",
}
LIMITS = {
    "no_network_performed": True,
    "neither_reader_is_ground_truth": True,
    "canonical_cohort_unchanged": True,
    "no_new_labels_or_predictions": True,
    "no_filing_date_inference": True,
    "no_source_rights_approval": True,
    "reader_views_are_not_distinct_legislative_versions": True,
    "enacted_session_witness": (
        "Where an enacted page lacks a legislature label, its own typed bill header "
        "is linked to a separate same-bill cover in the same PDF and reader. Exact "
        "cover state/session/bill spans are external witnesses, not policy content."
    ),
    "inherited_exchange_limit": {
        "source": "inherited research report; not independently reconstructed",
        "method": "GET", "url": "https://api.github.com/user", "status": 200,
        "raw_response_retained": False, "response_body_sha256": None,
        "complete_transport_history_available": False,
    },
    "transport_scope": (
        "Complete retained files for explicitly selected captures only. The parent "
        "ledger and scope are copied snapshots, not immutable parent-root inventories "
        "or evidence of complete transport for other exchanges."
    ),
}


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible NJ library archive: {message}")


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _binding(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def _regular(path):
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"incompatible NJ library archive: missing artifact: {path}") from exc
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink() and path.resolve() == path,
            f"unsafe or linked artifact: {path}")
    return path


def _root(path):
    path = Path(path).absolute()
    require(path.is_dir() and not path.is_symlink() and path.resolve() == path,
            "unsafe or linked packet directory")
    return path


def _relative(name):
    require(type(name) is str and bool(name) and "\\" not in name
            and ":" not in name and "\0" not in name, "unsafe artifact path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts
            and path.as_posix() == name and name != ".", "unsafe artifact path")
    return name


def _decode(content):
    def distinct(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON object key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"incompatible NJ library archive: nonfinite JSON: {value}")

    return json.loads(content, object_pairs_hook=distinct, parse_constant=invalid)


def _json(path):
    return _decode(path.read_bytes())


def _jsonl(path):
    return [_decode(line) for line in path.read_bytes().splitlines() if line]


def _equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
                    encoding="utf-8")


def _write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False,
                                    separators=(",", ":")) + "\n")


def _inventory(bindings):
    require(type(bindings) is dict, "typed artifact inventory required")
    for name, binding in bindings.items():
        _relative(name)
        require(type(binding) is dict and set(binding) == {"sha256", "bytes"}
                and type(binding["bytes"]) is int and binding["bytes"] >= 0
                and type(binding["sha256"]) is str
                and re.fullmatch(r"[0-9a-f]{64}", binding["sha256"]),
                "invalid artifact binding")


def _text_binding(text):
    content = text.encode("utf-8")
    return {"characters": len(text), "utf8_bytes": len(content),
            "sha256": _sha(content), "encoding": "UTF-8", "normalization": "none"}


def _span(text, start, end, kind, page):
    literal = text[start:end]
    return {
        "kind": kind, "page_ordinal": page, "start": start, "end": end,
        "text": literal, "character_start": start, "character_end": end,
        "utf8_byte_start": len(text[:start].encode("utf-8")),
        "utf8_byte_end": len(text[:end].encode("utf-8")), "end_exclusive": True,
        "literal_sha256": _sha(literal.encode("utf-8")),
    }


def _match_span(text, match, kind, page, group=0):
    return _span(text, match.start(group), match.end(group), kind, page)


def _one(pattern, text, name, flags=0):
    matches = list(re.finditer(pattern, text, flags))
    require(len(matches) == 1, f"ambiguous or absent printed {name}")
    return matches[0]


def _identifier(kind, number):
    return ("A" if kind.upper() == "ASSEMBLY" else "S") + " " + str(int(number))


_COVER_PREFIX = (
    r"\A[ \t\r\n]*(?:\(Sponsorship Updated As Of:[^\r\n]+\)[ \t\r\n]*)?"
)
_COVER_IDENTITY = (
    r"(?P<bill>(?P<kind>ASSEMBLY|SENATE),[ \t]+No\.[ \t]*(?P<number>[1-9][0-9]*))"
    r"[ \t]*\r?\n[ \t\r\n]*(?P<state>STATE OF NEW JERSEY)"
    r"[ \t]*\r?\n[ \t\r\n]*(?P<session>[0-9]+(?:st|nd|rd|th)[ \t]+LEGISLATURE)"
)
_COVER = re.compile(_COVER_PREFIX + _COVER_IDENTITY)
_REPRINT_COVER = re.compile(
    _COVER_PREFIX
    + r"(?:(?P<cover_reprint>\[(?P<reprint>First|Second|Third|Fourth|Fifth) Reprint\])"
      r"[ \t\r\n]*)?"
    + _COVER_IDENTITY
)
_REPRINT_NUMBERS = {"First": "1", "Second": "2", "Third": "3", "Fourth": "4", "Fifth": "5"}


def printed_identity(text, page_ordinal=1, *, context_qualified_introductions=None,
                     qualify_supported_years=False, allow_printed_variants=False):
    """Require an own bill cover, not a fiscal/committee/checklist or cited header."""
    require(type(text) is str, "literal complete cover string required")
    require(context_qualified_introductions is None
            or type(context_qualified_introductions) is dict,
            "explicit context-qualified introduction map required")
    require(type(qualify_supported_years) is bool
            and (not qualify_supported_years or context_qualified_introductions is not None),
            "extended original-date profile requires explicit context evidence")
    require(type(allow_printed_variants) is bool
            and (not allow_printed_variants or qualify_supported_years),
            "printed variants require the explicit extended profile")
    own = (_REPRINT_COVER if allow_printed_variants else _COVER).match(text)
    require(own is not None, "not an own typed bill cover")
    require(own["session"] == "220th LEGISLATURE", "wrong printed session")
    prefile = None
    if allow_printed_variants and not re.search(r"(?m)^[ \t]*INTRODUCED\b", text):
        prefile = _one(
            r"(?m)^[ \t]*PRE-FILED FOR INTRODUCTION IN THE (20[0-9]{2}) SESSION[ \t]*$",
            text, "literal prefiling session year",
        )
        require(prefile[1] in {"2022", "2023", "2024"}, "unsupported printed prefiling year")
    intro = prefile if prefile is not None else _one(
        r"(?m)^[ \t]*INTRODUCED[ \t]+[A-Z]+[ \t]+[0-9]{1,2},[ \t]+(20[0-9]{2})[ \t]*$",
        text, "introduced year",
    )
    context_proof = None
    identifier = _identifier(own["kind"], own["number"])
    if prefile is None and (intro[1] not in {"2022", "2023"} or (
        qualify_supported_years and identifier in context_qualified_introductions
    )):
        qualified = (context_qualified_introductions or {}).get(identifier)
        allowed = {"2022", "2023", "2024"} if qualify_supported_years else {"2024"}
        require(intro[1] in allowed and type(qualified) is dict
                and set(qualified) == {"original_context", "origin_introduction_actions"},
                "wrong printed cover year for session 220")
        context, actions = qualified["original_context"], qualified["origin_introduction_actions"]
        require(type(context) is dict and type(actions) is list and bool(actions),
                "original context and actual original introduction actions required")
        try:
            printed_date = datetime.strptime(
                intro[0].strip().removeprefix("INTRODUCED").strip(), "%B %d, %Y",
            ).date().isoformat()
        except ValueError as exc:
            raise ValueError("incompatible NJ library archive: invalid printed introduction date") from exc
        ids = context.get("origin_introduction_action_ids")
        require(type(ids) is str, "explicit original origin-introduction IDs required")
        ids = _decode(ids)
        require(all(type(row) is dict and all(type(row.get(key)) is str for key in (
            "action_id", "bill_id", "state", "date", "organization_id",
            "description", "classification", "chamber",
        )) for row in actions), "typed complete original introduction actions required")
        action_dates = []
        for row in actions:
            try:
                calendar_date = datetime.fromisoformat(row["date"]).date().isoformat()
            except ValueError as exc:
                raise ValueError("incompatible NJ library archive: invalid original action date") from exc
            require(row["date"].split("T")[0] == calendar_date,
                    "literal ISO calendar date required, without timezone conversion")
            action_dates.append(calendar_date)
        require(
            context.get("state") == "NJ" and context.get("session_identifier") == "220"
            and context.get("identifier") == identifier
            and type(context.get("bill_id")) is str
            and context["bill_id"].startswith("ocd-bill/")
            and type(context.get("from_organization_id")) is str
            and context["from_organization_id"].startswith("ocd-organization/")
            and context.get("originating_chamber")
            == {"ASSEMBLY": "lower", "SENATE": "upper"}[own["kind"]]
            and context.get("source_introduction_date") == printed_date
            and type(ids) is list and bool(ids)
            and all(type(value) is str and bool(value) for value in ids)
            and len(set(ids)) == len(ids)
            and (
                type(context.get("n_origin_introduction_actions")) is int
                and context["n_origin_introduction_actions"] == len(ids)
                or type(context.get("n_origin_introduction_actions")) is str
                and context["n_origin_introduction_actions"] == str(len(ids))
            )
            and {row["action_id"] for row in actions} == set(ids)
            and all(value == printed_date for value in action_dates)
            and all(row["bill_id"] == context["bill_id"] and row["state"] == "NJ"
                    and row["organization_id"] == context["from_organization_id"]
                    and row["chamber"] == context["originating_chamber"]
                    and "introduction" in row["classification"].split("|")
                    for row in actions),
            "printed introduction does not match the exact original context",
        )
        context_proof = {
            "relation": "own_printed_220_session_and_exact_original_introduction_date",
            "printed_introduction_date": printed_date,
            "printed_date_span": _match_span(
                text, intro, "printed_full_introduction_date", page_ordinal,
            ),
            "original_context": context,
            "original_origin_introduction_actions": actions,
            "original_context_sha256": _sha(
                json.dumps(context, sort_keys=True, ensure_ascii=False, allow_nan=False).encode(),
            ),
            "original_context_fields_and_session_end_preserved": True,
            "action_date_comparison": "literal_ISO_calendar_date_without_timezone_conversion",
            "source_date_or_session_end_inferred": False,
        }
    version = _one(
        r"(?m)^[ \t]*CURRENT VERSION OF TEXT[ \t]*\r?\n(?P<version>[\s\S]+)\Z",
        text, "version",
    )
    version_start, version_end = version.span("version")
    while version_start < version_end and text[version_start].isspace():
        version_start += 1
    while version_end > version_start and text[version_end - 1].isspace():
        version_end -= 1
    require(version_start < version_end and "Sponsored by:" in text and "SYNOPSIS" in text,
            "incomplete own cover/version")
    result = {
        "state": "NJ", "identifier": _identifier(own["kind"], own["number"]),
        "session_identifier": "220",
        "printed_cover_year": None if prefile is not None else intro[1],
        "identity_spans": [
            _match_span(text, own, "printed_own_bill_header", page_ordinal, "bill"),
            _match_span(text, own, "printed_state", page_ordinal, "state"),
            _match_span(text, own, "printed_session", page_ordinal, "session"),
        ],
        "printed_year_span": _match_span(
            text, intro, "printed_prefiling_session_year" if prefile is not None
            else "printed_cover_year", page_ordinal, 1,
        ),
        "version_span": _span(text, version_start, version_end,
                              "printed_version_text", page_ordinal),
    }
    if context_proof is not None:
        result["original_context_introduction_proof"] = context_proof
    if prefile is not None:
        result["printed_prefiling_session_year"] = prefile[1]
        result["unproven_original_introduction_date"] = True
    if allow_printed_variants and own["reprint"] is not None:
        result["printed_cover_reprint"] = own["reprint"]
        result["printed_cover_reprint_span"] = _match_span(
            text, own, "printed_own_cover_reprint", page_ordinal, "cover_reprint",
        )
    return result


def _continuation(text, page):
    match = re.match(
        r"\A[ \t\r\n]*(?P<bill>[AS][1-9][0-9]*)(?P<label>[^\r\n]*)\r?\n"
        r"[ \t]*(?P<folio>[1-9][0-9]*)[ \t]*(?:\r?\n|\Z)", text,
    )
    if match is None:
        return None
    require(re.fullmatch(r"[ A-Z0-9,\[\].'’\-]*", match["label"]) is not None
            and not re.search(r"\b[AS][0-9]+\b", match["label"]),
            "ambiguous printed continuation label")
    return {
        "identifier": match["bill"][0] + " " + match["bill"][1:],
        "folio": int(match["folio"]), "printed_label": match["label"],
        "spans": [
            _match_span(text, match, "printed_continuation_bill", page, "bill"),
            _match_span(text, match, "printed_folio", page, "folio"),
            _match_span(text, match, "printed_continuation_label", page, "label"),
        ],
    }


def _enacted(text, page, *, extended_identity_profile=False, allow_printed_variants=False,
             prologue_witness=None):
    number_prefix = r"No[.,]" if allow_printed_variants else r"No\."
    ordinals = "First|Second|Third|Fourth|Fifth" if allow_printed_variants else "First|Second|Third|Fourth"
    law = re.search(
        r"(?m)^P\.L\.[ \t]+(?P<year>20[0-9]{2}),[ \t]+CHAPTER[ \t]+[0-9]+,"
        r"[ \t]+approved[^\r\n]+\r?\n"
        rf"(?P<bill>(?P<kind>Assembly|Senate),[ \t]+{number_prefix}[ \t]+(?P<number>[1-9][0-9]*))"
        rf"(?P<version>[ \t]*\((?P<reprint>{ordinals}) Reprint\))?"
        r"[ \t]*(?:\r?\n|\Z)", text,
    )
    if law is None or law["reprint"] == "Fourth" and not extended_identity_profile:
        return None
    witnessed_prologue = None
    if prologue_witness is not None:
        require(allow_printed_variants and type(prologue_witness) is dict
                and set(prologue_witness) == {
                    "source_pdf_sha256", "page_text_sha256", "prefix_sha256", "role",
                }
                and all(type(value) is str for value in prologue_witness.values())
                and re.fullmatch(r"[0-9a-f]{64}", prologue_witness["source_pdf_sha256"])
                and prologue_witness["role"] in {
                    "printed_initial_folio", "printed_statutory_codification",
                }
                and _sha(text.encode()) == prologue_witness["page_text_sha256"]
                and _sha(text[:law.start()].encode()) == prologue_witness["prefix_sha256"],
                "pinned enacted prologue bytes or source witness changed")
        witnessed_prologue = {
            **prologue_witness,
            "literal_prefix_span": _span(text, 0, law.start(), "source_enacted_prologue", page),
            "no_source_text_inserted_cropped_or_rewritten": True,
        }
    require((text.lstrip().startswith("EXPLANATION") or witnessed_prologue is not None)
            and "STATEMENT TO" not in text[:law.end()]
            and "LEGISLATIVE HISTORY CHECKLIST" not in text[:law.end()],
            "ambiguous enacted-version prologue")
    require(law["year"] in {"2022", "2023"}, "wrong printed enacted year for session 220")
    require("AN ACT" in text[law.end():] and "BE IT ENACTED" in text[law.end():],
            "incomplete own enacted first page")
    # Chapter 187's pypdf string has "of New Jer sey:"; preserve that exact span.
    state = _one(r"of New Jer ?sey:", text, "enacted state")
    version = _match_span(text, law, "printed_enacted_version_header", page)
    result = {
        "identifier": _identifier(law["kind"], law["number"]),
        "state_span": _match_span(text, state, "printed_enacting_state", page),
        "bill_span": _match_span(text, law, "printed_own_bill_header", page, "bill"),
        "version_span": version, "printed_law_year": law["year"],
        "reprint": f"{law['reprint']} Reprint" if law["version"] else None,
    }
    if witnessed_prologue is not None:
        result["source_scoped_enacted_prologue"] = witnessed_prologue
    return result


def _ancillary(text):
    if "LEGISLATIVE HISTORY CHECKLIST" in text[:500]:
        return "library_checklist"
    if text.lstrip().startswith(("Office of Legislative Services", "FE to ")):
        return "fiscal_estimate"
    if "STATEMENT TO" in text[:500] or re.search(
        r"COMMITTEE[ \t]*\r?\n", text[:500],
    ):
        return "committee_or_floor_statement"
    if re.search(r"Governor Murphy|www\.nj\.gov/governor", text):
        return "governor_press_document"
    return "unselected_ancillary_or_unresolved_page"


def _checklist_only(page_texts):
    if len(page_texts) != 2:
        return False
    first, last = page_texts
    header = re.match(
        r"\A[ \t]*[0-9][^\r\n]{0,119}\r?\n[ \t]*LEGISLATIVE HISTORY CHECKLIST[ \t]*\r?\n"
        r"[ \t]*Compiled by the NJ State Law Library[ \t]*\r?\n", first,
    )
    law = re.search(r"\bLAWS OF:\s*(20[0-9]{2})\s+CHAPTER:\s*[1-9][0-9]*\b", first)
    forbidden = (
        r"(?im)^[ \t]*(?:ASSEMBLY|SENATE)[ \t]*,?[ \t]*No\b"
        r"|\bAN\s+ACT\b|\bBE\s+IT\s+ENACTED\b"
        r"|\bSTATE\s+OF\s+[A-Z]|\b[0-9]+(?:st|nd|rd|th)\s+LEGISLATURE\b"
    )
    return bool(
        header and law and law[1] in {"2022", "2023"}
        and all(first.count(label) == 1 for label in ("LAWS OF:", "CHAPTER:", "BILL NO:"))
        and re.search(r"\bNJSA:\s*\S", first)
        and re.search(r"\bBILL NO:\s*[AS][1-9][0-9]*\b", first)
        and "DATE INTRODUCED:" in first
        and "FOLLOWING ARE ATTACHED IF AVAILABLE:" in first
        and re.match(r"\A\s*VETO MESSAGE:", last)
        and "FOLLOWING WERE PRINTED:" in last
        and "contact New Jersey State Government" in last
        and all(label in last for label in ("REPORTS:", "HEARINGS:", "NEWSPAPER ARTICLES:"))
        and re.search(r"\bCL/JA\s*\Z", last)
        and not any(re.search(forbidden, text) or _continuation(text, i + 1)
                    for i, text in enumerate(page_texts))
    )


def separate_versions(page_texts, *, context_qualified_introductions=None,
                      qualify_supported_years=False, unlabelled_page_bridges=None,
                      allow_single_page_versions=False, allow_printed_variants=False,
                      enacted_prologue_witnesses=None, whitespace_page_witnesses=None):
    """Return complete contiguous own versions and all-page dispositions.

    Unknown boundaries, orphan typed continuations, or contradictory folios are
    errors, not a reason to return a plausible shortened bill.
    The explicit extended profile can quarantine a fully bounded but unproven
    version separately. Its entire pages remain present, and accepted versions
    of the same bill carry the corresponding source-completeness warning.
    """
    require(type(page_texts) is list and bool(page_texts)
            and all(type(text) is str for text in page_texts),
            "complete nonempty reader pages required")
    require(unlabelled_page_bridges is None
            or qualify_supported_years and type(unlabelled_page_bridges) is dict,
            "explicit extended-profile page bridge required")
    require(type(allow_single_page_versions) is bool
            and (not allow_single_page_versions or qualify_supported_years),
            "single-page versions require the explicit extended profile")
    require(type(allow_printed_variants) is bool
            and (not allow_printed_variants or qualify_supported_years),
            "printed variants require the explicit extended profile")
    require(enacted_prologue_witnesses is None or (
        allow_printed_variants and type(enacted_prologue_witnesses) is dict
    ), "enacted prologue witnesses require the explicit printed-variant profile")
    require(whitespace_page_witnesses is None or (
        allow_printed_variants and type(whitespace_page_witnesses) is dict
    ), "whitespace-page witnesses require the explicit printed-variant profile")
    whitespace = whitespace_page_witnesses or {}
    for ordinal, witness in whitespace.items():
        require(type(ordinal) is int and 1 <= ordinal <= len(page_texts)
                and type(witness) is dict and set(witness) == {
                    "source_pdf_sha256", "page_ordinal", "page_text_sha256",
                    "content_stream_sha256", "only_whitespace_text_operations",
                }
                and witness["page_ordinal"] == ordinal
                and witness["only_whitespace_text_operations"] is True
                and all(type(witness[key]) is str
                        and re.fullmatch(r"[0-9a-f]{64}", witness[key]) for key in (
                            "source_pdf_sha256", "page_text_sha256", "content_stream_sha256",
                        ))
                and not page_texts[ordinal - 1].strip()
                and _sha(page_texts[ordinal - 1].encode()) == witness["page_text_sha256"],
                "pinned whitespace-page bytes or physical-content witness changed")
    require(all(text.strip() or i + 1 in whitespace for i, text in enumerate(page_texts)),
            "complete nonempty reader pages required")
    cover_pattern = _REPRINT_COVER if allow_printed_variants else _COVER
    covers = {
        i: printed_identity(
            text, i + 1, context_qualified_introductions=context_qualified_introductions,
            qualify_supported_years=qualify_supported_years,
            allow_printed_variants=allow_printed_variants,
        )
        for i, text in enumerate(page_texts) if cover_pattern.match(text)
    }
    enacted = {
        i: value for i, text in enumerate(page_texts)
        if (value := _enacted(
            text, i + 1, extended_identity_profile=qualify_supported_years,
            allow_printed_variants=allow_printed_variants,
            prologue_witness=(enacted_prologue_witnesses or {}).get(i + 1),
        )) is not None
    }
    if not covers and not enacted and _checklist_only(page_texts):
        return [], [{
            "page_ordinal": i + 1, "disposition": "library_checklist_only_no_bill_text",
            "version_ordinal": None, "text_preserved_in_full": True,
        } for i in range(len(page_texts))]
    require(bool(covers), "no independently printed session bill covers")
    own_by_id = defaultdict(list)
    for index, cover in covers.items():
        own_by_id[cover["identifier"]].append((index, cover))
    versions, selected, quarantined, unproven_versions = [], {}, {}, []
    for index in sorted(covers.keys() | enacted.keys()):
        require(index not in selected and index not in quarantined, "overlapping own versions")
        unproven_session = False
        kind = "bill_cover" if index in covers else "enacted_version"
        if kind == "bill_cover":
            identity = covers[index]
            identifier = identity["identifier"]
            witnesses = identity["identity_spans"]
            version = identity["version_span"]
            external = []
            printed_year = identity["printed_cover_year"]
        else:
            first = enacted[index]
            identifier = first["identifier"]
            candidates = own_by_id[identifier]
            if allow_printed_variants:
                introduced = [(i, witness) for i, witness in candidates
                              if "printed_cover_reprint" not in witness]
                candidates = introduced or candidates
            require(len(candidates) == 1 or allow_printed_variants,
                    "ambiguous or missing same-bill session cover witness")
            if len(candidates) == 1:
                _, cover = candidates[0]
            else:
                cover = None
                unproven_session = True
            witnesses = [first["bill_span"], first["state_span"]]
            external = cover["identity_spans"] if cover is not None else []
            version = first["version_span"]
            printed_year = first["printed_law_year"]
        context_witness = identity if kind == "bill_cover" else cover
        context_proof = context_witness.get(
            "original_context_introduction_proof",
        ) if context_witness is not None else None
        unproven_introduction = context_witness.get(
            "unproven_original_introduction_date", False,
        ) if context_witness is not None else False
        ordinals = [index + 1]
        continuations = []
        page_bridges = []
        cursor, folio = index + 1, 2
        while cursor < len(page_texts):
            continuation = _continuation(page_texts[cursor], cursor + 1)
            if continuation is None:
                bridge = (unlabelled_page_bridges or {}).get(cursor + 1)
                if bridge is not None:
                    require(0 < cursor < len(page_texts) - 1
                            and kind == "enacted_version"
                            and identifier == bridge["identifier"]
                            and _sha(page_texts[cursor - 1].encode()) == bridge["before_text_sha256"]
                            and _sha(page_texts[cursor].encode()) == bridge["page_text_sha256"]
                            and _sha(page_texts[cursor + 1].encode()) == bridge["after_text_sha256"],
                            "pinned unlabelled-page bytes or own version changed")
                    before = _continuation(page_texts[cursor - 1], cursor)
                    after = _continuation(page_texts[cursor + 1], cursor + 2)
                    require(before is not None and after is not None
                            and before["identifier"] == after["identifier"] == identifier
                            and before["folio"] == bridge["preceding_folio"] == folio - 1
                            and after["folio"] == bridge["following_folio"] == folio + 1
                            and before["printed_label"].strip()
                            == after["printed_label"].strip() == bridge["printed_reprint_label"]
                            and cursor not in selected and cursor not in quarantined,
                            "unlabelled-page two-sided printed witnesses changed")
                    page_bridges.append({
                        "page_ordinal": cursor + 1,
                        "extracted_bill_header": None, "extracted_folio": None,
                        "source_pdf_sha256": bridge["source_pdf_sha256"],
                        "page_text_binding": _text_binding(page_texts[cursor]),
                        "preceding_printed_witness": before, "following_printed_witness": after,
                        "binding_basis": "exact_pinned_PDF_and_two_sided_same_bill_reprint_folios",
                        "no_header_folio_or_text_inserted": True,
                    })
                    ordinals.append(cursor + 1)
                    cursor += 1
                    folio += 1
                    continue
                require(not re.match(r"\s*[AS][0-9]+\b", page_texts[cursor]),
                        "unresolved continuation header at boundary")
                break
            require(continuation["identifier"] == identifier and continuation["folio"] == folio,
                    "wrong continuation identifier or noncontiguous printed folio")
            if kind == "enacted_version":
                reprints = re.findall(r"\[([0-9]+)R\]", continuation["printed_label"])
                # Chapters 186/187 pair Second/Third Reprint with every [2R]/[3R] folio.
                expected = {
                    None: [], "First Reprint": ["1"],
                    "Second Reprint": ["2"], "Third Reprint": ["3"],
                    "Fourth Reprint": ["4"],
                    "Fifth Reprint": ["5"],
                }[enacted[index]["reprint"]]
                require(reprints == expected, "enacted printed reprint mismatch")
            else:
                expected = ([_REPRINT_NUMBERS[identity["printed_cover_reprint"]]]
                            if identity.get("printed_cover_reprint") else [])
                require(re.findall(r"\[([0-9]+)R\]", continuation["printed_label"]) == expected,
                        "introduced cover/continuation version mismatch")
            require(cursor not in selected and cursor not in quarantined,
                    "overlapping continuation pages")
            ordinals.append(cursor + 1)
            continuations.append(continuation)
            cursor += 1
            folio += 1
        require(len(ordinals) >= 2 or allow_single_page_versions,
                "missing complete bill continuation")
        body = "\n".join(page_texts[p - 1] for p in ordinals)
        section_effective = re.search(
            r"(?m)^[ \t]*[1-9][0-9]*\.[ \t]+[Ss]ections?[ \t]+[0-9]+"
            r"(?:(?:[ \t]+(?:and|through)|,)[ \t]+[0-9]+)*[ \t]+of[ \t]+this[ \t]+act"
            r"[ \t]+shall[ \t]+take[ \t]+e[ \t]*ffect\b",
            body,
        ) if context_proof is not None or qualify_supported_years else None
        literal_effective = re.search(
            r"(?m)^[ \t]*[1-9][0-9]*\.[ \t]+This[ \t]+ac[ \t]*t[ \t]+shall"
            r"[ \t]+ta[ \t]*ke[ \t]+e[ \t]*ffect\b", body,
        ) if qualify_supported_years else None
        body_complete = bool(
            "AN ACT" in body and "BE IT ENACTED" in body
            and (re.search(r"This\s+act\s+shall\s+take\s+effect", body)
                 or section_effective is not None or literal_effective is not None)
        )
        require(qualify_supported_years or body_complete,
                "missing complete own legislative body/effective section")
        statements = []
        for ordinal in ordinals:
            text = page_texts[ordinal - 1]
            for match in re.finditer(r"(?m)^[ \t]*STATEMENT[ \t]*(?:[0-9]+[ \t]*)?$", text):
                statements.append(_match_span(text, match, "own_bill_statement", ordinal))
        statement_complete = (kind != "bill_cover"
                              or bool(identity.get("printed_cover_reprint"))
                              or bool(statements))
        require(qualify_supported_years or statement_complete,
                "introduced bill missing its complete statement")
        if cursor == len(page_texts):
            boundary = {"reason": "end_of_complete_pdf", "next_page_ordinal": None}
        elif cursor in covers or cursor in enacted:
            boundary = {"reason": "next_distinct_own_version", "next_page_ordinal": cursor + 1}
        else:
            reason = _ancillary(page_texts[cursor])
            require(reason != "unselected_ancillary_or_unresolved_page",
                    "ambiguous bill/ancillary boundary")
            boundary = {"reason": reason, "next_page_ordinal": cursor + 1}
        if not body_complete or not statement_complete or unproven_introduction or unproven_session:
            unproven = {
                "identifier": identifier, "kind": kind, "page_ordinals": ordinals,
                "printed_version": version, "boundary": boundary,
                "reason": ("unproven_same_bill_session_witness" if unproven_session else
                           "unproven_original_introduction_date"
                           if unproven_introduction else
                           "unproven_complete_policy_body_or_effective_clause"
                           if not body_complete else "unproven_complete_introduced_statement"),
                "entire_extracted_page_strings_and_original_pdf_retained": True,
                "policy_input_admitted": False,
            }
            if unproven_session:
                unproven["unproven_session_evidence"] = {
                    "identity_spans": witnesses,
                    "candidate_own_cover_spans": [
                        witness["identity_spans"] for _, witness in candidates
                    ],
                    "session_identifier": None, "no_session_inferred": True,
                }
            if unproven_introduction:
                witness = identity if kind == "bill_cover" else cover
                unproven["printed_prefiling_evidence"] = {
                    "printed_prefiling_session_year": witness["printed_prefiling_session_year"],
                    "literal_span": witness["printed_year_span"],
                    "original_introduction_date": None,
                    "no_introduction_date_inferred": True,
                }
            unproven_versions.append(unproven)
            for ordinal in ordinals:
                require(ordinal - 1 not in selected and ordinal - 1 not in quarantined,
                        "overlapping quarantined version pages")
                quarantined[ordinal - 1] = unproven
            continue
        item = {
            "identifier": identifier, "state": "NJ", "session_identifier": "220",
            "kind": kind, "page_ordinals": ordinals, "continuations": continuations,
            "printed_version": version, "printed_year": printed_year,
            "identity_spans": witnesses, "external_same_bill_cover_spans": external,
            "statement_spans": statements, "boundary": boundary,
            "complete_contiguous_pages": True, "no_policy_page_cropping": True,
        }
        if context_proof is not None:
            item["original_context_introduction_proof"] = context_proof
        if kind == "bill_cover" and identity.get("printed_cover_reprint"):
            item["printed_cover_reprint"] = identity["printed_cover_reprint"]
            item["printed_cover_reprint_span"] = identity["printed_cover_reprint_span"]
        if section_effective is not None:
            item["section_specific_effective_clause_evidence"] = {
                "scope": "complete_contiguous_version_text",
                "start": section_effective.start(), "end": section_effective.end(),
                "text": section_effective[0],
            }
        if literal_effective is not None:
            item["literal_effective_clause_evidence"] = {
                "scope": "complete_contiguous_version_text",
                "start": literal_effective.start(), "end": literal_effective.end(),
                "text": literal_effective[0], "source_word_spacing_not_rewritten": True,
            }
        if page_bridges:
            item["unlabelled_page_bridges"] = page_bridges
        if kind == "enacted_version" and enacted[index].get("source_scoped_enacted_prologue"):
            item["source_scoped_enacted_prologue"] = enacted[index]["source_scoped_enacted_prologue"]
        if whitespace:
            item["retained_source_scoped_whitespace_pages"] = list(whitespace.values())
        if len(ordinals) == 1:
            item["complete_single_page_policy_version"] = True
        versions.append(item)
        for ordinal in ordinals:
            require(ordinal - 1 not in selected, "overlapping complete bill versions")
            selected[ordinal - 1] = len(versions) - 1
    dispositions = []
    for version in versions:
        related = [row for row in unproven_versions if row["identifier"] == version["identifier"]]
        if related:
            version["quarantined_same_bill_source_versions"] = related
    for index, text in enumerate(page_texts):
        if index + 1 in whitespace:
            require(index not in selected and index not in quarantined,
                    "verified whitespace page overlaps a policy version")
            dispositions.append({
                "page_ordinal": index + 1, "disposition": "retained_verified_whitespace_page",
                "version_ordinal": None, "text_preserved_in_full": True,
                "policy_input_admitted": False, "source_witness": whitespace[index + 1],
            })
            continue
        require(index in selected or index in quarantined or _continuation(text, index + 1) is None,
                "orphan printed bill continuation; no guessing")
        if index in quarantined:
            dispositions.append({
                "page_ordinal": index + 1, "disposition": "quarantined_unproven_version",
                "version_ordinal": None, "text_preserved_in_full": True,
                "unproven_version": quarantined[index],
            })
            continue
        dispositions.append({
            "page_ordinal": index + 1,
            "disposition": "selected_complete_version" if index in selected else _ancillary(text),
            "version_ordinal": selected[index] + 1 if index in selected else None,
            "text_preserved_in_full": True,
        })
    return versions, dispositions


class _Warnings(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def emit(self, record):
        self.rows.append({"logger": record.name, "level": record.levelname,
                          "message": record.getMessage()})


def _extract(path, source_id):
    require({"pymupdf": pymupdf.__version__, "pypdf": pypdf.__version__} == TOOLS,
            "installed dual-reader tool versions changed")
    data = path.read_bytes()
    require(data.startswith(b"%PDF-"), "source is not a PDF")
    pages, documents = [], []
    handler = _Warnings()
    logger = logging.getLogger("pypdf")
    logger.addHandler(handler)
    try:
        with warnings.catch_warnings(record=True) as python_warnings:
            warnings.simplefilter("always")
            reader = pypdf.PdfReader(io.BytesIO(data), strict=True)
            documents.append({
                "source_id": source_id, "reader": "pypdf", "n_pages": len(reader.pages),
                "metadata": dict(reader.metadata) if reader.metadata is not None else None,
                "warnings": list(handler.rows),
                "python_warnings": [str(w.message) for w in python_warnings],
                "errors": [], "extraction_options": {"extraction_mode": "plain"},
            })
        for ordinal, page in enumerate(reader.pages, 1):
            handler.rows.clear()
            errors, text, layout = [], None, None
            with warnings.catch_warnings(record=True) as python_warnings:
                warnings.simplefilter("always")
                try:
                    text = page.extract_text(extraction_mode="plain")
                    layout = page.extract_text(extraction_mode="layout")
                except (pypdf.errors.PdfReadError, ValueError, RuntimeError) as exc:
                    errors.append({"type": type(exc).__name__, "message": str(exc)})
            pages.append({
                "source_id": source_id, "reader": "pypdf", "page_ordinal": ordinal,
                "text": text, "text_binding": _text_binding(text) if text is not None else None,
                "layout_text": layout,
                "layout_text_binding": _text_binding(layout) if layout is not None else None,
                "geometry": {"mediabox": [float(v) for v in page.mediabox],
                             "rotation": page.rotation},
                "warnings": list(handler.rows),
                "python_warnings": [str(w.message) for w in python_warnings], "errors": errors,
            })
    finally:
        logger.removeHandler(handler)
    pymupdf.TOOLS.mupdf_warnings(reset=True)
    with pymupdf.open(stream=data, filetype="pdf") as reader:
        documents.append({
            "source_id": source_id, "reader": "pymupdf", "n_pages": len(reader),
            "metadata": reader.metadata, "warnings": pymupdf.TOOLS.mupdf_warnings(reset=True),
            "errors": [], "extraction_options": {"sort": False, "format": "text"},
        })
        for ordinal, page in enumerate(reader, 1):
            errors, text, layout = [], None, None
            with warnings.catch_warnings(record=True) as python_warnings:
                warnings.simplefilter("always")
                try:
                    text = page.get_text("text", sort=False)
                    layout = page.get_text(
                        "dict", sort=False,
                        flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES,
                    )
                except (ValueError, RuntimeError) as exc:
                    errors.append({"type": type(exc).__name__, "message": str(exc)})
            pages.append({
                "source_id": source_id, "reader": "pymupdf", "page_ordinal": ordinal,
                "text": text, "text_binding": _text_binding(text) if text is not None else None,
                "text_layout": layout,
                "geometry": {"mediabox": list(page.mediabox), "rotation": page.rotation},
                "warnings": pymupdf.TOOLS.mupdf_warnings(reset=True),
                "python_warnings": [str(w.message) for w in python_warnings], "errors": errors,
            })
    return (
        _decode(json.dumps(pages, ensure_ascii=False, allow_nan=False)),
        _decode(json.dumps(documents, ensure_ascii=False, allow_nan=False)),
    )


def _capture_files(capture):
    require(type(capture) is dict and type(capture["ordinal"]) is int
            and type(capture["status"]) is int and capture["status"] in {200, 302}
            and capture["curl_returncode"] == 0 and capture["access_stop"] is False
            and capture["automatic_retries"] is False
            and capture["automatic_redirects"] is False, "unsuccessful capture or hidden retries")
    parsed = urlsplit(capture["url"])
    require(parsed.scheme == "https" and parsed.hostname == "repo.njstatelib.org"
            and not parsed.username and not parsed.password and not parsed.fragment
            and capture["host"] == parsed.hostname, "wrong source host or unsafe URL")
    names = [_relative(capture[key]) for key in ("body", "headers", "transport", "stderr")]
    require(len(set(names)) == 4 and all(name.startswith("raw/") for name in names),
            "invalid raw capture file paths")
    return names


def _verify_capture(source, capture):
    names = _capture_files(capture)
    for name in names:
        _regular(source / name)
    require(_binding(source / capture["body"]) == {
        "sha256": capture["body_sha256"], "bytes": capture["body_bytes"],
    }, "original capture body hash/size mismatch")
    headers = (source / capture["headers"]).read_bytes().decode("iso-8859-1")
    statuses = re.findall(r"(?m)^HTTP/[0-9.]+[ \t]+([0-9]{3})[^\r\n]*", headers)
    require(statuses == [str(capture["status"])] and headers.endswith(("\n\n", "\r\n\r\n")),
            "missing/ambiguous original response headers")
    transport = _json(source / capture["transport"])
    require(transport["url"] == capture["url"]
            and transport["url_effective"] == capture["url"]
            and transport["http_code"] == capture["status"]
            and transport["response_code"] == capture["status"]
            and transport["exitcode"] == 0 and transport["num_redirects"] == 0
            and transport["method"] == "GET"
            and transport["size_download"] == capture["body_bytes"],
            "original URL/status/transport/body mismatch")
    if capture["status"] == 302:
        locations = re.findall(r"(?im)^location:[ \t]*([^\r\n]+)", headers)
        require(len(locations) == 1 and locations[0] == transport["redirect_url"],
                "unretained or conflicting redirect Location")
        return locations[0]
    return None


def _batches(source, extension_sha256):
    base = _regular(source / BATCH_NAME)
    require(_binding(base)["sha256"] == BATCH_SHA256, "immutable first-four batch mismatch")
    batches = [_json(base)]
    if extension_sha256 is not None:
        require(type(extension_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", extension_sha256),
                "explicit extension batch SHA256 required")
        extra = _regular(source / "additional-source-batch.json")
        require(_binding(extra)["sha256"] == extension_sha256, "additional batch mismatch")
        batches.append(_json(extra))
    entries = []
    for batch in batches:
        require(type(batch) is dict and type(batch["pdfs"]) is list and bool(batch["pdfs"])
                and batch["queue"] == QUEUE_NAME
                and batch["all_source_approvals"] is False
                and batch["source_urls_directly_discovered_or_retained_302_location"] is True,
                "invalid batch schema/approval")
        entries.extend(batch["pdfs"])
    paths = []
    for entry in entries:
        require(type(entry) is dict and type(entry["n_pages"]) is int
                and entry["n_pages"] > 0, "typed PDF batch entry required")
        capture = entry["capture"]
        _capture_files(capture)
        require(capture["status"] == 200 and capture["is_robots"] is False
                and entry["pdf_sha256"] == capture["body_sha256"]
                and PurePosixPath(entry["pdf"]).parts[-2:] ==
                PurePosixPath(capture["body"]).parts, "batch PDF/capture foreign key mismatch")
        paths.append(capture["body"])
    require(len(set(paths)) == len(paths) and set(paths[:len(PINNED_PDFS)]) == set(PINNED_PDFS),
            "duplicate PDFs or incomplete original batch")
    for entry in batches[0]["pdfs"]:
        capture = entry["capture"]
        expected = PINNED_PDFS[capture["body"]]
        require((entry["pdf_sha256"], capture["body_bytes"], entry["n_pages"]) == expected[:3],
                "pinned original PDF changed")
    require(len(batches[0]["pdfs"]) == len(PINNED_PDFS), "unexpected first-four batch entries")
    return entries


def _related_captures(entries, ledger):
    earliest = min(entry["capture"]["ordinal"] for entry in entries)
    robots = [r for r in ledger if r["is_robots"] is True
              and r["url"] == "https://repo.njstatelib.org/robots.txt" and r["ordinal"] < earliest]
    require(len(robots) == 1, "unique retained prior robots policy required")
    captures = [robots[0]]
    for entry in entries:
        capture = entry["capture"]
        matches = [r for r in ledger if r["ordinal"] == capture["ordinal"]]
        require(len(matches) == 1 and _equal(matches[0], capture),
                "complete batch capture metadata/ledger mismatch")
        bitstream = re.fullmatch(
            r"/server/api/core/bitstreams/([a-zA-Z0-9-]+)/content", urlsplit(capture["url"]).path,
        )
        require(bitstream is not None, "explicit library PDF bitstream URL required")
        redirect_url = f"https://repo.njstatelib.org/bitstreams/{bitstream[1]}/download"
        redirects = [row for row in ledger if row["status"] == 302
                     and row["ordinal"] < capture["ordinal"] and row["url"] == redirect_url]
        require(len(redirects) <= 1, "ambiguous retained redirect history")
        if capture["body"] in PINNED_PDFS and capture["ordinal"] != 3:
            require(len(redirects) == 1, "missing explicitly retained first-four 302 hop")
        captures.extend(redirects)
        captures.append(capture)
    selected = {}
    for capture in captures:
        require(capture["ordinal"] not in selected, "duplicate selected capture ordinal")
        selected[capture["ordinal"]] = capture
    return sorted(selected.values(), key=lambda r: r["ordinal"])


def _source_selection(source, extension_sha256):
    entries = _batches(source, extension_sha256)
    ledger = _jsonl(_regular(source / "request-ledger.snapshot.jsonl"))
    scope = _json(_regular(source / "scope.snapshot.json"))
    inherited = scope["inherited_exchange"]
    require(inherited["raw_response_retained"] is False
            and inherited["response_body_sha256"] is None
            and inherited["url"] == LIMITS["inherited_exchange_limit"]["url"],
            "inherited unretained exchange cannot become recovered evidence")
    selected = _related_captures(entries, ledger)
    names = {BATCH_NAME, "request-ledger.snapshot.jsonl", "scope.snapshot.json"}
    if extension_sha256 is not None:
        names.add("additional-source-batch.json")
    for capture in selected:
        names.update(_capture_files(capture))
        location = _verify_capture(source, capture)
        if location:
            require(location in {entry["capture"]["url"] for entry in entries},
                    "redirect without an explicitly retained final PDF")
    return entries, selected, names


def _key(row):
    require(type(row) is dict and type(row.get("state")) is str
            and type(row.get("session_identifier")) is str
            and type(row.get("identifier")) is str
            and re.fullmatch(r"[AS] [1-9][0-9]*", row["identifier"]),
            "typed literal NJ bill/session/state required")
    return row["state"], row["session_identifier"], row["identifier"]


def _current_metadata(contexts, metadata):
    current = metadata.to_pylist() if isinstance(metadata, pa.Table) else list(metadata)
    by_id = defaultdict(list)
    for row in current:
        require(type(row) is dict and type(row.get("bill_id")) is str,
                "typed current metadata bill_id required")
        by_id[row["bill_id"]].append(row)
    for context in contexts:
        matches = by_id[context["bill_id"]]
        require(len(matches) == 1 and _key(matches[0]) == _key(context),
                "current candidate identity mismatch or duplicate")
        require(all(_equal(value, context[key]) for key, value in matches[0].items()
                    if key in context), "current metadata changed an original queue/context field")


def _view(page_rows, version, context, entry, reader, ordinal):
    selected = [page_rows[p - 1] for p in version["page_ordinals"]]
    text, ranges = "", []
    for page in selected:
        if ranges:
            text += "\n"
        start = len(text)
        text += page["text"]
        ranges.append({
            "page_ordinal": page["page_ordinal"], "page_text_binding": page["text_binding"],
            "page_character_start": 0, "page_character_end": len(page["text"]),
            "view_character_start": start, "view_character_end": len(text),
            "view_utf8_byte_start": len(text[:start].encode("utf-8")),
            "view_utf8_byte_end": len(text.encode("utf-8")),
        })
    offsets = {r["page_ordinal"]: r["view_character_start"] for r in ranges}
    spans = []
    for span in version["identity_spans"] + version["external_same_bill_cover_spans"]:
        item = {**span, "reader": reader, "source_id": entry["capture"]["label"],
                "in_policy_text": span["page_ordinal"] in offsets}
        if item["in_policy_text"]:
            item["view_character_start"] = offsets[span["page_ordinal"]] + span["start"]
            item["view_character_end"] = offsets[span["page_ordinal"]] + span["end"]
            item["view_utf8_byte_start"] = len(
                text[:item["view_character_start"]].encode("utf-8"),
            )
            item["view_utf8_byte_end"] = len(text[:item["view_character_end"]].encode("utf-8"))
        spans.append(item)
    return {
        "view_id": (
            f"nj-library:{entry['capture']['label']}:{entry['pdf_sha256']}:{ordinal}:{reader}"
        ),
        "source_type": "archive_text", "bill_id": context["bill_id"], "state": "NJ",
        "session_identifier": "220", "identifier": context["identifier"],
        "title": context["title"],
        "text": text, "raw_text_characters": len(text),
        "raw_text_sha256": _sha(text.encode("utf-8")),
        "text_binding": _text_binding(text), "reader": reader, "reader_version": TOOLS[reader],
        "source_record": {"batch_entry": entry, "original_queue_row": context},
        "source_identity": {
            "state": "NJ", "identifier": context["identifier"], "session_identifier": "220",
            "printed_evidence": spans,
            "session_witness_scope": (
                "external_same_bill_cover_in_same_pdf_and_reader"
                if version["external_same_bill_cover_spans"] else "own_selected_bill_cover"
            ),
        },
        "source_version": version,
        "source_members": {
            "pdf": {"path": "source-evidence/" + entry["capture"]["body"],
                    "sha256": entry["pdf_sha256"], "bytes": entry["capture"]["body_bytes"]},
            "pages": "pages.jsonl", "original_queue": "input_gap_queue.parquet",
            "capture_records": "source-evidence/request-ledger.snapshot.jsonl",
        },
        "selected_page_ranges": ranges, "page_separator": "\n",
        "archive_provider": PROVIDER, "source_status": STATUS,
        "archive_generated_prologue_preserved": False, **dict.fromkeys(FLAGS, False),
    }


def _replay(source, queue_path, extension_sha256):
    require(_binding(_regular(queue_path))["sha256"] == GAP_SHA256,
            "original complete gap queue mismatch")
    gap = pq.read_table(queue_path)
    require(gap.num_rows == 21576, "original gap count changed")
    originals = gap.to_pylist()
    by_key = defaultdict(list)
    for row in originals:
        if (row["state"] == "NJ" and row["session_identifier"] == "220"
                and re.fullmatch(r"[AS] [1-9][0-9]*", row["identifier"])):
            require(row["neither_source_observed"] is True, "not an original unresolved NJ gap")
            by_key[_key(row)].append(row)
    entries, captures, names = _source_selection(source, extension_sha256)
    pages, documents, versions, views, dispositions, comparisons = [], [], [], [], [], []
    negatives = []
    accepted = set()
    for entry in entries:
        label = entry["capture"]["label"]
        extracted, docs = _extract(_regular(source / entry["capture"]["body"]), label)
        require(all(doc["n_pages"] == entry["n_pages"] for doc in docs),
                "source page-count mismatch")
        pages.extend(extracted)
        documents.extend(docs)
        per_reader = {}
        for reader in ("pypdf", "pymupdf"):
            page_rows = [p for p in extracted if p["reader"] == reader]
            require(len(page_rows) == entry["n_pages"]
                    and all(not p["errors"] and type(p["text"]) is str and p["text"].strip()
                            for p in page_rows),
                    "unresolved extraction errors/empty page; no reader substitution")
            source_versions, source_dispositions = separate_versions([p["text"] for p in page_rows])
            per_reader[reader] = source_versions
            dispositions.extend({"source_id": label, "reader": reader, **r}
                                for r in source_dispositions)
            if entry["capture"]["body"] in PINNED_PDFS:
                expected = PINNED_PDFS[entry["capture"]["body"]][3]
                require(tuple(v["identifier"] for v in source_versions if v["kind"] == "bill_cover")
                        == expected, "first-four own bill covers changed")
            for ordinal, version in enumerate(source_versions, 1):
                matches = by_key[_key(version)]
                require(len(matches) == 1, "absent or ambiguous exact original gap join")
                context = matches[0]
                require(all(context[flag] is False for flag in (
                    "model_input_approved", "filing_time_text_certified", "analytical_admission",
                )), "original gap approvals changed")
                require(context["session_start_date"][:4] <= version["printed_year"]
                        <= context["session_end_date"][:4], "printed/queue session year mismatch")
                accepted.add(context["bill_id"])
                versions.append({"source_id": label, "reader": reader,
                                 "version_ordinal": ordinal, **version})
                views.append(_view(page_rows, version, context, entry, reader, ordinal))
        def structural(rows):
            return [(r["identifier"], r["kind"], r["page_ordinals"], r["boundary"]) for r in rows]

        require(_equal(structural(per_reader["pypdf"]), structural(per_reader["pymupdf"])),
                "ambiguous dual-reader bill boundaries/identities; no reader chosen")
        if not per_reader["pypdf"]:
            negatives.append({
                "source_id": label, "disposition": "library_checklist_only_no_bill_text",
                "recovered_text_views": 0, "page_ordinals": list(range(1, entry["n_pages"] + 1)),
                "readers": ["pypdf", "pymupdf"],
            })
        for ordinal in range(1, entry["n_pages"] + 1):
            pair = [p for p in extracted if p["page_ordinal"] == ordinal]
            comparisons.append({
                "source_id": label, "page_ordinal": ordinal,
                "reader_texts_exactly_equal": pair[0]["text"] == pair[1]["text"],
                "reader_text_bindings": {p["reader"]: p["text_binding"] for p in pair},
                "ground_truth_reader": None,
            })
    contexts = gap.filter(pa.array([r["bill_id"] in accepted for r in originals]))
    require(contexts.num_rows == len(accepted), "duplicate original bill_id queue context")
    counts = {
        "source_pdfs": len(entries), "retained_http_captures": len(captures),
        "original_gap_contexts": gap.num_rows, "original_calendar_candidates_declared": 157598,
        "newly_covered_contexts": len(accepted), "text_views": len(views),
        "source_versions": len(views) // 2,
        "all_source_pdf_pages": sum(entry["n_pages"] for entry in entries),
        "all_reader_pages": len(pages),
        "selected_reader_pages": sum(len(v["page_ordinals"]) for v in versions),
        "unselected_reader_pages": sum(
            r["disposition"] != "selected_complete_version" for r in dispositions
        ),
        "reader_pages_with_warnings": sum(
            bool(p["warnings"] or p["python_warnings"]) for p in pages
        ),
        "reader_pages_with_errors": sum(bool(p["errors"]) for p in pages),
        "reader_page_strings_differ": sum(not p["reader_texts_exactly_equal"] for p in comparisons),
    }
    counts["versions_by_kind"] = dict(Counter(
        v["kind"] for v in versions if v["reader"] == "pypdf"
    ))
    report = {
        "schema": SCHEMA, "counts": counts, "tools": TOOLS, "limits": LIMITS,
        "approvals": dict.fromkeys(FLAGS, False), "selected_capture_records": captures,
        "reader_comparisons": comparisons,
        "original_queue_columns": gap.column_names,
        "full_original_queue_schema": str(gap.schema),
        "complete_reader_text_and_layout_retained": True,
        "raw_original_scope_record": _json(source / "scope.snapshot.json"),
        "source_parent_is_mutable": True,
    }
    if negatives:
        report["source_negative_dispositions"] = negatives
    return views, contexts, pages, documents, versions, dispositions, report, names


def _copy(source, target):
    _regular(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    require(_binding(_regular(target)) == _binding(source), "copy2 source binding mismatch")


def build_nj_library(source_directory, gap_queue, out_directory, *,
                     batch_list=None, batch_sha256=None):
    """Copy finite retained inputs, normalize with both readers, then load/replay."""
    source = _root(source_directory)
    queue = _regular(Path(gap_queue).absolute())
    out = Path(out_directory).absolute()
    require(not out.exists() and not out.is_symlink() and out.resolve() == out,
            "new unlinked output directory required")
    require((batch_list is None) == (batch_sha256 is None),
            "additional batch requires both path and explicit SHA256")
    require(_binding(queue)["sha256"] == GAP_SHA256, "original complete gap queue mismatch")
    require(_binding(_regular(source / BATCH_NAME))["sha256"] == BATCH_SHA256,
            "immutable first-four batch mismatch")
    out.mkdir(parents=True)
    evidence = out / "source-evidence"
    evidence.mkdir()
    _copy(source / BATCH_NAME, evidence / BATCH_NAME)
    _copy(source / "request-ledger.jsonl", evidence / "request-ledger.snapshot.jsonl")
    _copy(source / "scope.json", evidence / "scope.snapshot.json")
    if batch_list is not None:
        extra = _regular(Path(batch_list).absolute())
        require(_binding(extra)["sha256"] == batch_sha256, "additional batch hash mismatch")
        _copy(extra, evidence / "additional-source-batch.json")
    entries = _batches(evidence, batch_sha256)
    # Read only explicitly listed captures, plus retained robots and 302 records.
    ledger = _jsonl(evidence / "request-ledger.snapshot.jsonl")
    possible = _related_captures(entries, ledger)
    before = {}
    for capture in possible:
        for name in _capture_files(capture):
            before[name] = _binding(_regular(source / name))
            _copy(source / name, evidence / name)
    _, _, names = _source_selection(evidence, batch_sha256)
    copied_raw = {name for name in before if name.startswith("raw/")}
    require(copied_raw == {name for name in names if name.startswith("raw/")},
            "unselected capture file would enter the finite packet; supply a narrower batch")
    before[BATCH_NAME] = _binding(source / BATCH_NAME)
    before["input_gap_queue.parquet"] = _binding(queue)
    if batch_list is not None:
        before["additional-source-batch.json"] = _binding(extra)
    _copy(queue, out / "input_gap_queue.parquet")
    result = _replay(evidence, out / "input_gap_queue.parquet", batch_sha256)
    views, contexts, pages, documents, versions, dispositions, report, replay_names = result
    require(replay_names == names, "finite source selection changed")
    _write_rows(out / "views.jsonl", views)
    _write_rows(out / "pages.jsonl", pages)
    _write_rows(out / "documents.jsonl", documents)
    _write_rows(out / "versions.jsonl", versions)
    _write_rows(out / "page_dispositions.jsonl", dispositions)
    _write_rows(out / "original_queue_rows.jsonl", contexts.to_pylist())
    pq.write_table(contexts, out / "context_inventory.parquet")
    _write(out / "report.json", report)
    source_inventory = {name: _binding(evidence / name) for name in sorted(names)}
    _write(out / "source_inventory.json", source_inventory)
    original_paths = {name: source / name for name in before}
    original_paths["input_gap_queue.parquet"] = queue
    if batch_list is not None:
        original_paths["additional-source-batch.json"] = extra
    after = {name: _binding(original_paths[name]) for name in before}
    require(_equal(before, after), "consumed finite original inputs changed during normalization")
    _write(out / "consumed_input_hashes.json", {
        "before": before, "after": after, "all_immutable_consumed_files_unchanged": True,
        "mutable_metadata_snapshot_bindings": {
            name: source_inventory[name]
            for name in ("request-ledger.snapshot.jsonl", "scope.snapshot.json")
        },
        "parent_directory_and_ledger_not_immutable_roots": True,
    })
    _copy(Path(__file__).absolute(), out / "producer/nj_library_text.py")
    artifacts = PRODUCTS | {f"source-evidence/{name}" for name in names}
    manifest = {
        "schema": SCHEMA, "provider": PROVIDER, "status": STATUS,
        "source_batch_sha256": BATCH_SHA256, "additional_batch_sha256": batch_sha256,
        "gap_queue_sha256": GAP_SHA256, "tools": TOOLS,
        "approvals": dict.fromkeys(FLAGS, False), "counts": report["counts"],
        "packet_artifacts": {name: _binding(out / name) for name in sorted(artifacts)},
    }
    _write(out / "manifest.json", manifest)
    load_nj_library(out)
    return manifest


def load_nj_library(root, metadata=None):
    """Verify source/queue/producer, replay all strings/spans, return archive protocol."""
    directory = _root(root)
    path = _regular(directory / "manifest.json")
    manifest = _json(path)
    require(type(manifest) is dict and set(manifest) == {
        "schema", "provider", "status", "source_batch_sha256", "additional_batch_sha256",
        "gap_queue_sha256", "tools", "approvals", "counts", "packet_artifacts",
    }, "invalid manifest fields")
    require(manifest["schema"] == SCHEMA and manifest["provider"] == PROVIDER
            and manifest["status"] == STATUS, "schema/provider/status mismatch")
    require(_equal(manifest["approvals"], dict.fromkeys(FLAGS, False)),
            "source approval promotion or mistyped false flag")
    require(manifest["source_batch_sha256"] == BATCH_SHA256
            and manifest["gap_queue_sha256"] == GAP_SHA256 and _equal(manifest["tools"], TOOLS),
            "source/queue/tool trust anchors changed")
    artifacts = manifest["packet_artifacts"]
    _inventory(artifacts)
    pins = {"manifest.json": _binding(path)["sha256"]}
    for name, binding in artifacts.items():
        require(_binding(_regular(directory / name)) == binding,
                f"packet artifact binding mismatch: {name}")
        pins[name] = binding["sha256"]
    source = _root(directory / "source-evidence")
    source_inventory = _json(directory / "source_inventory.json")
    _inventory(source_inventory)
    entries, _, names = _source_selection(source, manifest["additional_batch_sha256"])
    require(set(source_inventory) == names
            and set(artifacts) == PRODUCTS | {f"source-evidence/{name}" for name in names},
            "incomplete or unexpected finite packet inventory")
    require(all(_equal(binding, artifacts[f"source-evidence/{name}"])
                for name, binding in source_inventory.items()), "source inventory mismatch")
    producer = _binding(directory / "producer/nj_library_text.py")
    legacy_producer = LEGACY_PRODUCERS.get(pins["manifest.json"])
    compatible_producer = COMPATIBLE_PRODUCERS.get(pins["manifest.json"])
    require(producer == _binding(_regular(Path(__file__).absolute()))
            or producer == legacy_producer or producer == compatible_producer,
            "producer module mismatch")
    result = _replay(source, directory / "input_gap_queue.parquet",
                     manifest["additional_batch_sha256"])
    expected_views, expected_contexts, pages, docs, versions, dispositions, report, _ = result
    if legacy_producer is not None:
        # Preserve the two exact sealed packets, including their incorrect prologue flag.
        for row in expected_views:
            row["archive_generated_prologue_preserved"] = True
    rows = _jsonl(directory / "views.jsonl")
    require(_equal(rows, expected_views),
            "complete bill text/identity/span/queue/false-flag replay mismatch")
    for name, expected in (
        ("pages.jsonl", pages), ("documents.jsonl", docs), ("versions.jsonl", versions),
        ("page_dispositions.jsonl", dispositions),
        ("original_queue_rows.jsonl", expected_contexts.to_pylist()),
    ):
        require(_equal(_jsonl(directory / name), expected), f"complete {name} replay mismatch")
    contexts = pq.read_table(directory / "context_inventory.parquet")
    require(contexts.equals(expected_contexts, check_metadata=True),
            "full original queue/context fields or schema mismatch")
    require(_equal(_json(directory / "report.json"), report)
            and _equal(manifest["counts"], report["counts"]), "full report/count replay mismatch")
    hashes = _json(directory / "consumed_input_hashes.json")
    expected_hashes = {
        name: source_inventory[name] for name in names
        if name not in {"request-ledger.snapshot.jsonl", "scope.snapshot.json"}
    } | {"input_gap_queue.parquet": artifacts["input_gap_queue.parquet"]}
    require(_equal(hashes, {
        "before": expected_hashes, "after": expected_hashes,
        "all_immutable_consumed_files_unchanged": True,
        "mutable_metadata_snapshot_bindings": {
            name: source_inventory[name]
            for name in ("request-ledger.snapshot.jsonl", "scope.snapshot.json")
        },
        "parent_directory_and_ledger_not_immutable_roots": True,
    }), "original finite consumed-file before/after receipt mismatch")
    require(len(entries) == manifest["counts"]["source_pdfs"], "source count mismatch")
    context_rows = contexts.to_pylist()
    if metadata is not None:
        _current_metadata(context_rows, metadata)
    return rows, context_rows, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="copy finite inputs and normalize entirely offline")
    build.add_argument("--source-dir", type=Path, required=True)
    build.add_argument("--gap-queue", type=Path, required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    build.add_argument("--batch-list", type=Path)
    build.add_argument("--batch-sha256")
    verify = commands.add_parser(
        "verify", aliases=["replay"], help="strict complete offline replay",
    )
    verify.add_argument("--directory", type=Path, required=True)
    verify.add_argument("--metadata", type=Path, help="optional current candidate parquet join")
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_nj_library(
            args.source_dir, args.gap_queue, args.out_dir,
            batch_list=args.batch_list, batch_sha256=args.batch_sha256,
        )
    else:
        rows, contexts, _, manifest = load_nj_library(args.directory)
        if args.metadata is not None:
            current = pq.read_table(_regular(args.metadata.absolute()),
                                    filters=[("bill_id", "in", [r["bill_id"] for r in contexts])])
            _current_metadata(contexts, current)
        require(bool(rows), "no complete views recovered")
    print(json.dumps({"schema": SCHEMA, "counts": manifest["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

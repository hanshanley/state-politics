"""Reconcile Montana draft-request and formal identities without discarding either."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

import pandas as pd

_IDENTIFIER = re.compile(r"(LC|HB|HJ|HR|SB|SJ|SR)\s*(\d+)")


def _key(identifier):
    if not isinstance(identifier, str) or not (match := _IDENTIFIER.fullmatch(identifier)):
        return None
    return match[1], int(match[2])


def parse_native_pages(sessions: list[dict], responses: dict[int, list[dict]]) -> pd.DataFrame:
    """Validate complete page-index enumeration and preserve each original native object."""
    rows = []
    session_ids = set()
    session_keys = set()
    for session in sessions:
        sid = session["native_session_id"]
        year = session["session_identifier"]
        family = session["source_family"]
        if (
            type(sid) is not int or sid <= 0 or sid in session_ids
            or not isinstance(year, str) or not re.fullmatch(r"20\d{2}", year)
            or year in session_keys or family not in {"archive", "current"}
        ):
            raise ValueError("Invalid or duplicate Montana native session")
        session_ids.add(sid)
        session_keys.add(year)
        pages = responses.get(sid)
        if not isinstance(pages, list) or not pages:
            raise ValueError(f"Missing native pages: {year}")
        first = pages[0]["bills"] if family == "archive" else pages[0]
        total = first["totalElements"]
        size = first["size"]
        count = first["totalPages"]
        if (
            type(total) is not int or total < 0 or type(size) is not int or size <= 0
            or type(count) is not int or count != (total + size - 1) // size
            or len(pages) != max(1, count)
        ):
            raise ValueError(f"Incomplete or invalid native page population: {year}")
        seen = set()
        for number, response in enumerate(pages):
            page = response["bills"] if family == "archive" else response
            content = page["content"]
            if (
                not isinstance(content, list)
                or page["number"] != number
                or page["pageable"]["pageNumber"] != number
                or page["pageable"]["offset"] != number * size
                or page["pageable"]["pageSize"] != size
                or page["size"] != size
                or page["totalElements"] != total or page["totalPages"] != count
                or page["numberOfElements"] != len(content)
                or len(content) != min(size, total - number * size)
                or page["first"] != (number == 0)
                or page["last"] != (number == max(0, count - 1))
            ):
                raise ValueError(f"Native pagination does not replay: {year}/{number}")
            for position, raw in enumerate(content):
                if family == "archive":
                    raw_sid = raw["id"]["sessionId"]
                    draft = raw["id"]["billDraftNumber"]
                    title = raw["shortTitle"]
                    kind = raw["billType"]
                    bill_id = None
                else:
                    raw_sid = raw["sessionId"]
                    draft = raw["draft"]["draftNumber"]
                    title = raw["draft"]["shortTitle"]
                    kind = raw["billType"]["code"] if raw["billType"] is not None else None
                    bill_id = raw["id"]
                    if type(bill_id) is not int or bill_id <= 0:
                        raise ValueError("Invalid native current bill ID")
                number_value = raw["billNumber"]
                draft_key = _key(draft)
                if (
                    raw_sid != sid or draft_key is None or draft_key[0] != "LC"
                    or draft_key in seen or not isinstance(title, str)
                ):
                    raise ValueError(f"Invalid or duplicate native draft identity: {year}/{draft}")
                seen.add(draft_key)
                if kind is None and number_value is None:
                    formal = None
                elif (
                    kind in {"HB", "HJ", "HR", "SB", "SJ", "SR"}
                    and type(number_value) is int and number_value > 0
                ):
                    formal = f"{kind} {number_value}"
                else:
                    raise ValueError(f"Inconsistent native formal identity: {year}/{draft}")
                rows.append({
                    "native_record_index": len(rows),
                    "native_session_id": sid,
                    "native_session_identifier": year,
                    "native_source_family": family,
                    "native_page_number": number,
                    "native_page_row_index": position,
                    "native_draft_identifier": draft,
                    "native_formal_identifier": formal,
                    "native_has_formal_identity": formal is not None,
                    "native_bill_id": bill_id,
                    "native_title": title,
                    "native_source_json": json.dumps(raw, ensure_ascii=False),
                })
        if len(seen) != total:
            raise ValueError(f"Native unique population does not equal declared total: {year}")
    if set(responses) != session_ids:
        raise ValueError("Native responses differ from the selected session scope")
    fields = [
        "native_record_index", "native_session_id", "native_session_identifier",
        "native_source_family", "native_page_number", "native_page_row_index",
        "native_draft_identifier", "native_formal_identifier", "native_has_formal_identity",
        "native_bill_id", "native_title", "native_source_json",
    ]
    return pd.DataFrame(rows, columns=fields).astype({"native_bill_id": "Int64"})


def reconcile(
    baseline: pd.DataFrame, sessions: list[dict], responses: dict[int, list[dict]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Preserve all rows; link LC/formal identities without treating aliases as new filings."""
    required = {"bill_id", "state", "session_identifier", "identifier", "title"}
    if not required.issubset(baseline.columns) or baseline.columns.duplicated().any():
        raise ValueError("Missing or duplicate Montana baseline fields")
    if not baseline["state"].eq("MT").all() or baseline["bill_id"].duplicated().any():
        raise ValueError("Expected Montana source rows with unique source IDs")
    for field in ("bill_id", "session_identifier", "identifier"):
        if not baseline[field].map(lambda v: isinstance(v, str) and bool(v)).all():
            raise ValueError(f"Invalid baseline identity: {field}")
    native = parse_native_pages(sessions, responses)
    by_key = defaultdict(list)
    for row in native.to_dict("records"):
        for identifier in (row["native_draft_identifier"], row["native_formal_identifier"]):
            if identifier is not None:
                by_key[row["native_session_identifier"], _key(identifier)].append(row)
    keys = [(row.session_identifier, _key(row.identifier)) for row in baseline.itertuples()]
    counts = Counter(keys)
    native_sessions = {s["session_identifier"] for s in sessions}
    decisions = []
    for bill, key in zip(baseline.to_dict("records"), keys, strict=True):
        found = by_key[key] if key[1] is not None else []
        if key[0] not in native_sessions:
            status = "no_native_session_in_selected_scope"
        elif not found:
            status = "no_native_identity_match"
        elif counts[key] != 1:
            status = "ambiguous_baseline_identity"
        elif len(found) != 1:
            status = "ambiguous_native_identity"
        else:
            status = "unique_native_match"
        match = found[0] if status == "unique_native_match" else None
        formal_key = (
            (key[0], _key(match["native_formal_identifier"])) if match is not None else None
        )
        draft_key = (
            (key[0], _key(match["native_draft_identifier"])) if match is not None else None
        )
        decisions.append({
            "source_identity_kind": (
                "draft_request" if key[1] and key[1][0] == "LC"
                else "formal_measure" if key[1] else "unrecognized"
            ),
            "native_match_status": status,
            "n_native_identity_matches": len(found),
            "native_record_indices": json.dumps([r["native_record_index"] for r in found]),
            "matched_native_record_index": match["native_record_index"] if match else None,
            "matched_native_draft_identifier": (
                match["native_draft_identifier"] if match else None
            ),
            "matched_native_formal_identifier": (
                match["native_formal_identifier"] if match else None
            ),
            "matched_native_has_formal_identity": (
                match["native_has_formal_identity"] if match else None
            ),
            "matched_native_title_matches": (
                bill["title"] == match["native_title"] if match else None
            ),
            "n_baseline_formal_aliases": counts[formal_key] if formal_key and formal_key[1] else 0,
            "n_baseline_draft_aliases": counts[draft_key] if draft_key else 0,
            "native_version_identity_certified": False,
            "native_filing_time_party_certified": False,
            "native_training_admission": False,
            "native_analytical_admission": False,
        })
    if decisions and set(decisions[0]) & set(baseline.columns):
        raise ValueError("Conflicting Montana enrichment fields")
    decision_frame = pd.DataFrame(decisions, columns=[
        "source_identity_kind", "native_match_status", "n_native_identity_matches",
        "native_record_indices", "matched_native_record_index", "matched_native_draft_identifier",
        "matched_native_formal_identifier", "matched_native_has_formal_identity",
        "matched_native_title_matches", "n_baseline_formal_aliases", "n_baseline_draft_aliases",
        "native_version_identity_certified", "native_filing_time_party_certified",
        "native_training_admission", "native_analytical_admission",
    ]).astype({"matched_native_record_index": "Int64"})
    coverage = baseline.reset_index(drop=True).join(decision_frame)
    native["n_baseline_formal_aliases"] = [
        counts[row.native_session_identifier, _key(row.native_formal_identifier)]
        if row.native_formal_identifier else 0
        for row in native.itertuples()
    ]
    native["n_baseline_draft_aliases"] = [
        counts[row.native_session_identifier, _key(row.native_draft_identifier)]
        for row in native.itertuples()
    ]
    return coverage, native

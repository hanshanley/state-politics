"""Reconcile native SD session lists without inferring original text or affiliations."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

import pandas as pd


def parse_native_sessions(
    sessions: list[dict],
    responses: dict[int, list[dict]],
) -> list[dict]:
    """Preserve raw source rows and use explicit session identity, not introduction year."""
    if not isinstance(sessions, list) or not isinstance(responses, dict):
        raise ValueError("native session and bill responses require arrays and an ID mapping")
    session_ids = set()
    session_keys = set()
    rows = []
    for session_index, session in enumerate(sessions):
        if not isinstance(session, dict):
            raise ValueError("native session row must be an object")
        session_id = session.get("SessionId")
        key = session.get("Year")
        special = session.get("SpecialSession")
        if (
            type(session_id) is not int
            or session_id <= 0
            or session_id in session_ids
            or not isinstance(key, str)
            or not re.fullmatch(r"\d{4}[a-z]*", key)
            or key in session_keys
            or type(special) is not bool
            or (key[4:] != "") != special
        ):
            raise ValueError(f"invalid or duplicate native session identity: {session!r}")
        session_ids.add(session_id)
        session_keys.add(key)
        if session_id not in responses or not isinstance(responses[session_id], list):
            raise ValueError(f"missing or non-array native bill response: {session_id}")
        for row_index, bill in enumerate(responses[session_id]):
            if not isinstance(bill, dict):
                raise ValueError("native bill row must be an object")
            bill_id = bill.get("BillId")
            kind = bill.get("BillType")
            number = bill.get("BillNumberOnly")
            if (
                type(bill_id) is not int
                or bill_id <= 0
                or not isinstance(kind, str)
                or not re.fullmatch(r"[A-Z]+", kind)
                or type(number) is not int
                or number <= 0
                or bill.get("Year") != key
                or not isinstance(bill.get("BillNumber"), str)
                or bill.get("BillNumber") not in {str(number), f"{kind}{number}"}
                or not isinstance(bill.get("Title"), str)
            ):
                raise ValueError(f"invalid native bill identity in {key}, row {row_index}")
            rows.append(
                {
                    "native_record_index": len(rows),
                    "native_session_row_index": session_index,
                    "native_response_row_index": row_index,
                    "native_session_id": session_id,
                    "native_session_identifier": key,
                    "native_special_session": special,
                    "native_bill_id": bill_id,
                    "native_identifier": f"{kind} {number}",
                    "native_title": bill["Title"],
                    "native_introduced_observation": bill.get("Introduced"),
                    "native_listed_document_id": bill.get("DocumentId"),
                    "native_source_json": json.dumps(bill, ensure_ascii=False),
                }
            )
    if set(responses) != session_ids:
        raise ValueError("bill-response scope does not equal the explicit session scope")
    return rows


def reconcile(
    baseline: pd.DataFrame,
    sessions: list[dict],
    responses: dict[int, list[dict]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Keep every baseline/native row and distinguish exact, missing and ambiguous keys."""
    fields = {"bill_id", "state", "session_identifier", "identifier", "title"}
    if not fields.issubset(baseline.columns) or baseline.columns.duplicated().any():
        raise ValueError("baseline bill schema is missing or duplicates required fields")
    if not baseline["state"].eq("SD").all():
        raise ValueError("baseline must contain only South Dakota source rows")
    for field in fields - {"state", "title"}:
        if not baseline[field].map(lambda value: isinstance(value, str) and bool(value)).all():
            raise ValueError(f"baseline identity must be a nonempty string: {field}")
    if baseline["bill_id"].duplicated().any():
        raise ValueError("baseline contains duplicate source bill IDs")
    native = parse_native_sessions(sessions, responses)
    by_key = defaultdict(list)
    native_ids = Counter(row["native_bill_id"] for row in native)
    baseline_keys = Counter(
        zip(
            baseline["session_identifier"],
            baseline["identifier"],
            strict=True,
        )
    )
    native_sessions = {session["Year"] for session in sessions}
    for row in native:
        by_key[row["native_session_identifier"], row["native_identifier"]].append(row)
    decisions = []
    for bill in baseline.to_dict("records"):
        key = bill["session_identifier"], bill["identifier"]
        found = by_key[key]
        if key[0] not in native_sessions:
            status = "no_native_session_in_selected_scope"
        elif not found:
            status = "no_native_bill_match"
        elif baseline_keys[key] != 1:
            status = "ambiguous_baseline_key"
        elif len(found) != 1 or native_ids[found[0]["native_bill_id"]] != 1:
            status = "ambiguous_native_match"
        else:
            status = "unique_native_match"
        match = found[0] if status == "unique_native_match" else None
        decisions.append(
            {
                "native_match_status": status,
                "n_native_key_matches": len(found),
                "native_record_indices": json.dumps([row["native_record_index"] for row in found]),
                "matched_native_bill_id": match["native_bill_id"] if match else None,
                "matched_native_session_id": match["native_session_id"] if match else None,
                "matched_native_title": match["native_title"] if match else None,
                "native_title_matches_baseline": (
                    bill["title"] == match["native_title"] if match else None
                ),
                "native_version_identity_certified": False,
                "native_filing_time_text_certified": False,
                "native_filing_time_party_certified": False,
                "native_training_admission": False,
                "native_analytical_admission": False,
            }
        )
    decision_fields = [
        "native_match_status",
        "n_native_key_matches",
        "native_record_indices",
        "matched_native_bill_id",
        "matched_native_session_id",
        "matched_native_title",
        "native_title_matches_baseline",
        "native_version_identity_certified",
        "native_filing_time_text_certified",
        "native_filing_time_party_certified",
        "native_training_admission",
        "native_analytical_admission",
    ]
    if set(decision_fields) & set(baseline.columns):
        raise ValueError("baseline has conflicting native-enrichment columns")
    decision_frame = pd.DataFrame(decisions, columns=decision_fields).astype(
        {
            "matched_native_bill_id": "Int64",
            "matched_native_session_id": "Int64",
        }
    )
    coverage = baseline.reset_index(drop=True).join(decision_frame)
    native_fields = [
        "native_record_index",
        "native_session_row_index",
        "native_response_row_index",
        "native_session_id",
        "native_session_identifier",
        "native_special_session",
        "native_bill_id",
        "native_identifier",
        "native_title",
        "native_introduced_observation",
        "native_listed_document_id",
        "native_source_json",
    ]
    native_frame = pd.DataFrame(native, columns=native_fields)
    source_only = native_frame.loc[
        [
            (row["native_session_identifier"], row["native_identifier"]) not in baseline_keys
            for row in native
        ]
    ].copy()
    return coverage, native_frame, source_only


def plan_introduced_documents(native: pd.DataFrame, versions: pd.DataFrame) -> pd.DataFrame:
    """Keep every native bill and select only a unique, explicitly introduced candidate."""
    identity = [
        "native_record_index",
        "native_bill_id",
        "native_session_identifier",
        "native_identifier",
    ]
    version_fields = {
        *identity,
        "native_version_row_index",
        "native_document_id",
        "native_version_note",
    }
    if not set(identity).issubset(native.columns) or not version_fields.issubset(versions.columns):
        raise ValueError("native bill/version planning schema is incomplete")
    if native.columns.duplicated().any() or versions.columns.duplicated().any():
        raise ValueError("native bill/version planning columns must be unique")
    sources = native.to_dict("records")
    for field in ["native_bill_id", "native_record_index"]:
        if native[field].duplicated().any():
            raise ValueError(f"ambiguous native planning identity: {field}")
    by_id = {}
    for source in sources:
        if type(source["native_bill_id"]) is not int or source["native_bill_id"] <= 0:
            raise ValueError("native planning bill IDs must be positive integers")
        by_id[source["native_bill_id"]] = source
    groups = defaultdict(list)
    for row in versions.to_dict("records"):
        bill_id = row["native_bill_id"]
        if type(bill_id) is not int or bill_id not in by_id:
            raise ValueError("native version belongs to an unknown bill")
        if any(row[field] != by_id[bill_id][field] for field in identity):
            raise ValueError("native version and bill context conflict")
        if (
            type(row["native_document_id"]) is not int
            or row["native_document_id"] <= 0
            or type(row["native_version_row_index"]) is not int
            or row["native_version_row_index"] < 0
            or not isinstance(row["native_version_note"], str)
        ):
            raise ValueError("native version document/row/note fields are invalid")
        if row["native_version_note"] == "Introduced":
            groups[bill_id].append(row)
    extra_fields = [
        "native_introduced_candidate_status",
        "n_native_introduced_candidates",
        "native_introduced_version_row_indices",
        "native_introduced_document_ids",
        "native_introduced_document_id",
        "native_introduced_request_url",
        "version_identity_certified",
        "filing_time_text_certified",
        "training_admission",
        "analytical_admission",
    ]
    if set(extra_fields) & set(native.columns):
        raise ValueError("native input already contains document-planning decisions")
    planned = []
    for source in sources:
        found = groups[source["native_bill_id"]]
        unique = len(found) == 1
        document_id = found[0]["native_document_id"] if unique else None
        status = (
            "unique_native_introduced_candidate"
            if unique
            else "ambiguous_native_introduced_candidates"
            if found
            else "no_native_introduced_note"
        )
        planned.append(
            {
                **source,
                "native_introduced_candidate_status": status,
                "n_native_introduced_candidates": len(found),
                "native_introduced_version_row_indices": json.dumps(
                    [row["native_version_row_index"] for row in found]
                ),
                "native_introduced_document_ids": json.dumps(
                    [row["native_document_id"] for row in found]
                ),
                "native_introduced_document_id": document_id,
                "native_introduced_request_url": (
                    f"https://mylrc.sdlegislature.gov/api/Documents/{document_id}.pdf"
                    if unique
                    else None
                ),
                "version_identity_certified": False,
                "filing_time_text_certified": False,
                "training_admission": False,
                "analytical_admission": False,
            }
        )
    return pd.DataFrame(planned, columns=[*native.columns, *extra_fields]).astype(
        {
            "native_introduced_document_id": "Int64",
        }
    )

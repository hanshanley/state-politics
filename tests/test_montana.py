"""Native Montana identity and complete-pagination regressions."""

import copy
import json

import pandas as pd
import pytest

from state_politics.bills.montana import (
    parse_document_headers,
    reconcile,
    source_draft_request_mask,
)


def test_source_draft_scope_is_state_specific_and_preserves_conflicting_formal_identities():
    source = pd.DataFrame({
        "state": ["MT", "MT", "MT", "MT", "TX"],
        "identifier": ["LC 0239", "LC0442", "SB 6", "HB 117", "LC 239"],
    }, index=[2, 7, 2, 8, 9])
    original = source.copy()
    assert source_draft_request_mask(source).tolist() == [True, True, False, False, False]
    pd.testing.assert_frame_equal(source, original)


@pytest.mark.parametrize("identifiers", [None, [None], [""]])
def test_montana_scope_refuses_missing_source_identity(identifiers):
    source = pd.DataFrame({"state": ["MT"]})
    if identifiers is not None:
        source["identifier"] = identifiers
    with pytest.raises(ValueError, match="source identifiers"):
        source_draft_request_mask(source)


@pytest.mark.parametrize(
    ("text", "identifier", "kind", "version"),
    [
        ("****\n69th Legislature 2025 SB 6.1\nSENATE BILL NO. 6", "SB 6", "formal_measure", 1),
        ("69th Legislature 2025\nLC 0239\n___ BILL NO. ___", "LC 239", "draft_request", None),
    ],
)
def test_document_headers_preserve_printed_identity_and_exact_source_spans(
    text, identifier, kind, version,
):
    [header] = parse_document_headers(text)
    assert header["identifier_observation"] == identifier
    assert header["identity_kind_observation"] == kind
    assert header["printed_version_observation"] == version
    assert header["session_year_observation"] == "2025"
    assert text[header["source_start"]:header["source_end"]] == header["source_text"]
    assert parse_document_headers("The committee discussed SB 6 in 2025.") == []


def _sources():
    sessions = [
        {"native_session_id": 20231, "session_identifier": "2023", "source_family": "archive"},
        {"native_session_id": 2, "session_identifier": "2025", "source_family": "current"},
    ]
    records = [
        [
            {"id": {"sessionId": 20231, "billDraftNumber": "LC0001"},
             "billType": "HB", "billNumber": 1, "shortTitle": "Education"},
            {"id": {"sessionId": 20231, "billDraftNumber": "LC0002"},
             "billType": None, "billNumber": None, "shortTitle": "Election draft"},
        ],
        [
            {"id": 10, "sessionId": 2, "draft": {"draftNumber": "LC0010", "shortTitle": "Health"},
             "billType": {"code": "SB"}, "billNumber": 4},
        ],
    ]
    pages = {}
    for session, rows in zip(sessions, records, strict=True):
        result = []
        for number, row in enumerate(rows):
            page = {
                "number": number, "size": 1, "numberOfElements": 1,
                "totalElements": len(rows), "totalPages": len(rows),
                "first": number == 0, "last": number == len(rows) - 1,
                "pageable": {"pageNumber": number, "pageSize": 1, "offset": number},
                "content": [row],
            }
            result.append({"bills": page} if session["source_family"] == "archive" else page)
        pages[session["native_session_id"]] = result
    baseline = pd.DataFrame([
        {"bill_id": "formal", "state": "MT", "session_identifier": "2023",
         "identifier": "HB 1", "title": "Education", "classification": "bill"},
        {"bill_id": "alias", "state": "MT", "session_identifier": "2023",
         "identifier": "LC1", "title": "Education", "classification": "proposed bill"},
        {"bill_id": "draft", "state": "MT", "session_identifier": "2023",
         "identifier": "LC2", "title": "Election draft", "classification": "bill"},
        {"bill_id": "current", "state": "MT", "session_identifier": "2025",
         "identifier": "SB 4", "title": "Health", "classification": "bill"},
        {"bill_id": "missing", "state": "MT", "session_identifier": "2023",
         "identifier": "HB 99", "title": "Missing", "classification": "bill"},
    ])
    return baseline, sessions, pages


def test_native_reconciliation_preserves_aliases_drafts_raw_objects_and_source_columns():
    baseline, sessions, pages = _sources()
    original = baseline.copy(deep=True)
    coverage, native = reconcile(baseline, sessions, pages)
    pd.testing.assert_frame_equal(coverage[baseline.columns], original)
    pd.testing.assert_frame_equal(baseline, original)
    found = coverage.set_index("bill_id")
    assert found.loc["formal", "matched_native_record_index"] == (
        found.loc["alias", "matched_native_record_index"]
    )
    assert found.loc["alias", "n_baseline_formal_aliases"] == 1
    assert found.loc["formal", "n_baseline_draft_aliases"] == 1
    assert found.loc["alias", "matched_native_has_formal_identity"]
    assert not found.loc["draft", "matched_native_has_formal_identity"]
    assert found.loc["draft", "classification"] == "bill"
    assert found.loc["missing", "native_match_status"] == "no_native_identity_match"
    assert len(native) == 3
    assert json.loads(native.iloc[-1]["native_source_json"]) == pages[2][0]["content"][0]
    assert not coverage[["native_training_admission", "native_analytical_admission"]].any().any()


def test_duplicate_normalized_source_identity_is_not_arbitrarily_matched():
    baseline, sessions, pages = _sources()
    duplicate = baseline.iloc[[1]].assign(bill_id="duplicate", identifier="LC0001")
    coverage, _ = reconcile(pd.concat([baseline, duplicate], ignore_index=True), sessions, pages)
    found = coverage.set_index("bill_id")
    for bill_id in ("alias", "duplicate"):
        assert found.loc[bill_id, "native_match_status"] == "ambiguous_baseline_identity"
        assert pd.isna(found.loc[bill_id, "matched_native_record_index"])
    assert found.loc["formal", "n_baseline_draft_aliases"] == 2


def test_duplicate_native_formal_identity_stays_ambiguous_without_dropping_drafts():
    baseline, sessions, pages = _sources()
    record = pages[20231][1]["bills"]["content"][0]
    record.update(billType="HB", billNumber=1)
    coverage, native = reconcile(baseline, sessions, pages)
    formal = coverage.set_index("bill_id").loc["formal"]
    assert formal["native_match_status"] == "ambiguous_native_identity"
    assert formal["n_native_identity_matches"] == 2
    assert json.loads(formal["native_record_indices"]) == [0, 1]
    assert len(native) == 3


@pytest.mark.parametrize(
    "damage", ["missing_page", "wrong_offset", "duplicate_draft", "half_formal"],
)
def test_incomplete_or_inconsistent_native_sources_are_rejected(damage):
    baseline, sessions, original = _sources()
    pages = copy.deepcopy(original)
    if damage == "missing_page":
        pages[20231].pop()
    elif damage == "wrong_offset":
        pages[20231][1]["bills"]["number"] = 100
    elif damage == "duplicate_draft":
        pages[20231][1]["bills"]["content"][0]["id"]["billDraftNumber"] = "LC0001"
    else:
        pages[20231][1]["bills"]["content"][0]["billNumber"] = 5
    with pytest.raises(ValueError, match="Incomplete|pagination|duplicate|Inconsistent"):
        reconcile(baseline, sessions, pages)

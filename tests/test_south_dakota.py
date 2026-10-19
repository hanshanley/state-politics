"""Native lists are version-uncertified evidence, not replacement analytical bills."""

import json

import pandas as pd
import pytest

from state_politics.bills.south_dakota import (
    parse_native_sessions,
    plan_introduced_documents,
    reconcile,
)


def _sources():
    baseline = pd.DataFrame(
        [
            {
                "bill_id": "special",
                "state": "SD",
                "session_identifier": "2021i",
                "identifier": "HR 7001",
                "title": "Baseline title.",
                "sponsor_party": "unknown",
            },
            {
                "bill_id": "regular",
                "state": "SD",
                "session_identifier": "2022",
                "identifier": "HR 7001",
                "title": "Regular subject.",
                "sponsor_party": "unknown",
            },
            {
                "bill_id": "missing",
                "state": "SD",
                "session_identifier": "2022",
                "identifier": "HJR 1",
                "title": "Retain unmatched.",
                "sponsor_party": "unknown",
            },
        ]
    )
    sessions = [
        {"SessionId": 66, "Year": "2021i", "SpecialSession": True},
        {"SessionId": 64, "Year": "2022", "SpecialSession": False},
    ]
    responses = {
        66: [
            {
                "BillId": 100,
                "BillType": "HR",
                "BillNumber": "HR7001",
                "BillNumberOnly": 7001,
                "Year": "2021i",
                "Title": "Later special title.",
                "Introduced": "2022-04-11",
                "DocumentId": 20,
                "PrimeSponsors": [4, 9],
            },
            {
                "BillId": 101,
                "BillType": "SR",
                "BillNumber": "701",
                "BillNumberOnly": 701,
                "Year": "2021i",
                "Title": "Source-only native.",
            },
        ],
        64: [
            {
                "BillId": 102,
                "BillType": "HR",
                "BillNumber": "7001",
                "BillNumberOnly": 7001,
                "Year": "2022",
                "Title": "Regular subject.",
            },
        ],
    }
    return baseline, sessions, responses


def test_cross_year_special_session_and_full_source_preservation():
    baseline, sessions, responses = _sources()
    coverage, native, source_only = reconcile(baseline, sessions, responses)
    pd.testing.assert_frame_equal(coverage[baseline.columns], baseline)
    assert coverage["native_match_status"].tolist() == [
        "unique_native_match",
        "unique_native_match",
        "no_native_bill_match",
    ]
    assert coverage["matched_native_bill_id"].iloc[:2].tolist() == [100, 102]
    assert coverage["native_title_matches_baseline"].tolist() == [False, True, None]
    assert coverage.iloc[0]["matched_native_title"] == "Later special title."
    assert source_only["native_identifier"].tolist() == ["SR 701"]
    assert json.loads(native.iloc[0]["native_source_json"]) == responses[66][0]
    assert native.iloc[0]["native_introduced_observation"] == "2022-04-11"
    flags = [
        "native_version_identity_certified",
        "native_filing_time_text_certified",
        "native_filing_time_party_certified",
        "native_training_admission",
        "native_analytical_admission",
    ]
    assert not coverage[flags].any().any()


@pytest.mark.parametrize("defect", ["duplicate_key", "reused_id", "duplicate_baseline"])
def test_ambiguous_identities_are_retained_not_resolved_by_first_row(defect):
    baseline, sessions, responses = _sources()
    if defect == "duplicate_key":
        responses[66].append({**responses[66][0], "BillId": 103})
    elif defect == "reused_id":
        responses[64][0]["BillId"] = responses[66][0]["BillId"]
    else:
        baseline = pd.concat(
            [baseline, baseline.iloc[:1].assign(bill_id="second")], ignore_index=True
        )
    coverage, native, _ = reconcile(baseline, sessions, responses)
    assert coverage.iloc[0]["native_match_status"] == (
        "ambiguous_baseline_key" if defect == "duplicate_baseline" else "ambiguous_native_match"
    )
    assert pd.isna(coverage.iloc[0]["matched_native_bill_id"])
    assert len(native) == sum(map(len, responses.values()))
    assert len(coverage) == len(baseline)


@pytest.mark.parametrize(
    "defect",
    [
        "missing_response",
        "extra_response",
        "wrong_year",
        "inconsistent_number",
        "boolean_bill_id",
        "special_flag",
        "duplicate_session",
    ],
)
def test_incomplete_or_conflicting_native_scope_fails_explicitly(defect):
    baseline, sessions, responses = _sources()
    if defect == "missing_response":
        del responses[64]
    elif defect == "extra_response":
        responses[99] = []
    elif defect == "wrong_year":
        responses[66][0]["Year"] = "2022"
    elif defect == "inconsistent_number":
        responses[66][0]["BillNumber"] = "SR7001"
    elif defect == "boolean_bill_id":
        responses[66][0]["BillId"] = True
    elif defect == "special_flag":
        sessions[0]["SpecialSession"] = False
    else:
        sessions.append(sessions[0].copy())
    with pytest.raises(ValueError):
        reconcile(baseline, sessions, responses)


def test_empty_native_array_does_not_drop_baseline_or_certify_absence():
    baseline, sessions, _ = _sources()
    coverage, native, source_only = reconcile(baseline, sessions, {66: [], 64: []})
    assert coverage["native_match_status"].eq("no_native_bill_match").all()
    assert native.empty and source_only.empty
    assert list(coverage["bill_id"]) == list(baseline["bill_id"])
    assert parse_native_sessions([], {}) == []


def test_missing_selected_session_is_distinct_from_missing_bill():
    baseline, sessions, responses = _sources()
    coverage, _, _ = reconcile(baseline, sessions[:1], {66: responses[66]})
    assert coverage.iloc[0]["native_match_status"] == "unique_native_match"
    assert coverage.iloc[1]["native_match_status"] == "no_native_session_in_selected_scope"


def _version_sources():
    baseline, sessions, responses = _sources()
    _, native, _ = reconcile(baseline, sessions, responses)
    rows = []
    for index, note in enumerate(["Enrolled", "Introduced"]):
        rows.append(
            {
                **native.iloc[0][
                    [
                        "native_record_index",
                        "native_bill_id",
                        "native_session_identifier",
                        "native_identifier",
                    ]
                ].to_dict(),
                "native_version_row_index": index,
                "native_document_id": 30 + index,
                "native_version_note": note,
            }
        )
    return native, pd.DataFrame(rows)


def test_introduced_plan_does_not_select_first_latest_or_missing_version():
    native, versions = _version_sources()
    plan = plan_introduced_documents(native, versions)
    pd.testing.assert_frame_equal(plan[native.columns], native)
    assert plan["native_introduced_candidate_status"].tolist() == [
        "unique_native_introduced_candidate",
        "no_native_introduced_note",
        "no_native_introduced_note",
    ]
    assert plan.iloc[0]["native_introduced_document_id"] == 31
    assert plan.iloc[0]["native_introduced_request_url"].endswith("/31.pdf")
    assert pd.isna(plan.iloc[1]["native_introduced_request_url"])
    assert (
        not plan[
            [
                "version_identity_certified",
                "filing_time_text_certified",
                "training_admission",
                "analytical_admission",
            ]
        ]
        .any()
        .any()
    )


def test_repeated_introduced_rows_remain_ambiguous_even_with_the_same_document_id():
    native, versions = _version_sources()
    versions = pd.concat([versions, versions.iloc[1:]], ignore_index=True)
    plan = plan_introduced_documents(native, versions)
    assert plan.iloc[0]["native_introduced_candidate_status"] == (
        "ambiguous_native_introduced_candidates"
    )
    assert json.loads(plan.iloc[0]["native_introduced_document_ids"]) == [31, 31]
    assert pd.isna(plan.iloc[0]["native_introduced_request_url"])


@pytest.mark.parametrize("defect", ["context", "unknown_bill", "ambiguous_bill", "document_id"])
def test_introduced_plan_rejects_untraceable_native_versions(defect):
    native, versions = _version_sources()
    if defect == "context":
        versions.loc[0, "native_session_identifier"] = "2022"
    elif defect == "unknown_bill":
        versions.loc[0, "native_bill_id"] = 999
    elif defect == "ambiguous_bill":
        native = pd.concat([native, native.iloc[:1]], ignore_index=True)
    else:
        versions.loc[0, "native_document_id"] = 0
    with pytest.raises(ValueError):
        plan_introduced_documents(native, versions)

"""Accepted input indexes are reusable evidence, not reader-duplicated bill counts."""

import json

import pandas as pd
import pytest
import yaml

from state_politics.bills import study_native_overlap
from state_politics.bills.study_native_overlap import (
    aggregate_bill_contexts,
    build_overlap,
    join_contexts,
    native_introduction_observation,
    normalize_packet,
)
from state_politics.bills.study_window import _STATES
from state_politics.provenance import sha256_file


def inputs(profile="single"):
    spec = {
        "state": "CA",
        "root": "packet",
        "profile": profile,
        "context_id": "record_id",
        "identifier": "identifier",
        "bill_id": "bill_id",
        "canonical_session": "20232024",
    }
    raw = pd.DataFrame(
        {
            "record_id": ["one", "old", "native-only"],
            "identifier": ["HB 1", "HB 2", "HB 3"],
            "bill_id": ["b1", "b2", None],
            "input_sha256": ["a" * 64, "b" * 64, "c" * 64],
            "n_input_characters": [11, 22, 33],
        }
    )
    views = None
    if profile == "views":
        views = pd.DataFrame(
            {
                "view_id": ["one:pypdf", "one:pymupdf"],
                "context_id": ["one", "one"],
                "reader": ["pypdf", "pymupdf"],
                "input_sha256": ["a" * 64, "b" * 64],
                "n_input_characters": [11, 12],
            }
        )
    elif profile == "reader_rows":
        spec.pop("bill_id")
        spec["context_id"] = "native_id"
        raw = pd.concat([raw.iloc[:1], raw.iloc[:1]], ignore_index=True)
        raw["native_id"] = ["native-one", "native-one"]
        raw["record_id"] = ["native-one:pypdf", "native-one:pymupdf"]
        raw["reader"] = ["pypdf", "pymupdf"]
    return spec, raw, views


def ledger():
    return pd.DataFrame(
        {
            "state": ["CA"] * 3,
            "bill_id": ["b1", "b2", "b3"],
            "identifier": ["HB 1", "HB 2", "HB 3"],
            "session_identifier": ["20232024"] * 3,
            "window_disposition": [
                "source_introduction_in_window",
                "source_introduction_before_window",
                "no_source_introduction_action",
            ],
            "source_introduction_date": ["2023-02-01", "2019-02-01", ""],
        }
    )


@pytest.mark.parametrize("profile", ["single", "reader_rows", "views"])
def test_alternative_views_never_become_extra_bills(profile):
    spec, raw, source_views = inputs(profile)
    contexts, views = normalize_packet(spec, raw, source_views)
    result = join_contexts(contexts, ledger())
    assert contexts["n_retained_views"].sum() == len(views)
    assert result["source_in_window"].sum() == 1
    assert not result["analytical_admission"].any()
    assert not result["native_identity_certified"].any()
    if profile == "reader_rows":
        assert len(contexts) == 1 and len(views) == 2
        assert result["canonical_join_basis"].iloc[0] == "unique_declared_session_typed_identity"
    else:
        source_only = result.loc[result["context_id"].eq("native-only")].iloc[0]
        assert pd.isna(source_only["bill_id"])
        assert source_only["canonical_join_basis"] == "source_only_no_declared_bill_id"
        assert not source_only["source_in_window"]


def test_empty_untyped_view_table_preserves_explicit_missing_originals():
    spec, raw, views = inputs("views")
    empty = views.iloc[:0].astype(object)
    contexts, retained = normalize_packet(spec, raw, empty)
    assert len(contexts) == len(raw)
    assert retained.empty
    assert pd.api.types.is_integer_dtype(retained["n_input_characters"].dtype)
    assert contexts["n_retained_views"].eq(0).all()
    assert not contexts["native_identity_certified"].any()


@pytest.mark.parametrize("defect", ["session", "identifier", "duplicate-canonical"])
def test_identity_or_cross_session_conflicts_fail(defect):
    spec, raw, views = inputs()
    contexts, _ = normalize_packet(spec, raw, views)
    canonical = ledger()
    if defect == "session":
        canonical.loc[0, "session_identifier"] = "20192020"
    elif defect == "identifier":
        canonical.loc[0, "identifier"] = "HB 999"
    else:
        canonical = pd.concat([canonical, canonical.iloc[:1]])
    with pytest.raises(ValueError):
        join_contexts(contexts, canonical)


def reference_pair(dates=(None, None), granularity="source_reference"):
    spec, raw, _ = inputs()
    raw = raw.iloc[:1].copy()
    spec["native_introduction_field"] = "introduced"
    raw["introduced"] = dates[0]
    first, first_views = normalize_packet(spec, raw, None)
    spec.update(root="references", context_granularity=granularity)
    raw["record_id"] = "reference-one"
    raw["introduced"] = dates[1]
    second, second_views = normalize_packet(spec, raw, None)
    return (
        pd.concat([first, second], ignore_index=True),
        pd.concat([first_views, second_views], ignore_index=True),
    )


def test_explicit_reference_contexts_preserve_physical_ids_but_aggregate_one_bill():
    contexts, views = reference_pair()
    joined = join_contexts(contexts, ledger())
    bills = aggregate_bill_contexts(joined)
    assert len(joined) == 2 and len(views) == 2 and len(bills) == 1
    assert joined["context_id"].tolist() == ["one", "reference-one"]
    assert joined["packet_root"].tolist() == ["packet", "references"]
    bill = bills.iloc[0]
    assert bill["bill_id"] == "b1"
    assert bill["n_native_contexts"] == 2
    assert bill["n_retained_views"] == 2
    references = json.loads(bill["source_contexts_json"])
    assert [reference["context_id"] for reference in references] == ["one", "reference-one"]
    assert [reference["packet_root"] for reference in references] == ["packet", "references"]
    assert not bill["native_identity_certified"] and not bill["analytical_admission"]
    contexts["context_granularity"] = "source_reference"
    assert len(aggregate_bill_contexts(join_contexts(contexts, ledger()))) == 1


def test_default_measure_duplicates_still_fail_even_with_reference_contexts():
    contexts, _ = reference_pair(granularity="measure")
    with pytest.raises(ValueError, match="double-count a canonical bill"):
        join_contexts(contexts, ledger())
    reference = contexts.iloc[[1]].copy()
    reference["context_id"] = "third-reference"
    reference["context_granularity"] = "source_reference"
    with pytest.raises(ValueError, match="double-count a canonical bill"):
        join_contexts(pd.concat([contexts, reference], ignore_index=True), ledger())
    contexts, _ = reference_pair()
    joined = join_contexts(contexts, ledger())
    joined["context_granularity"] = "measure"
    with pytest.raises(ValueError, match="double-count a canonical bill"):
        aggregate_bill_contexts(joined)


@pytest.mark.parametrize(
    "field,value",
    [
        ("native_identifier", "HB 999"),
        ("session_identifier", "other-session"),
        ("native_identifier", None),
        ("session_identifier", None),
    ],
)
def test_reference_opt_in_never_weakens_typed_session_or_missing_identity_checks(field, value):
    contexts, _ = reference_pair()
    contexts.loc[1, field] = value
    with pytest.raises(ValueError):
        join_contexts(contexts, ledger())


@pytest.mark.parametrize(
    "dates,expected",
    [
        ((None, "2023-02-01"), "2023-02-01"),
        (("2023-02-01T10:00:00", "2023-02-01"), "2023-02-01"),
        (("2023-02-01", "2023-02-02"), None),
    ],
)
def test_bill_aggregation_resolves_only_one_unique_native_date_and_preserves_observations(
    dates, expected
):
    contexts, _ = reference_pair(dates)
    joined = join_contexts(contexts, ledger())
    bill = aggregate_bill_contexts(joined).iloc[0]
    assert json.loads(bill["native_introduction_raw"]) == list(dates)
    references = json.loads(bill["source_contexts_json"])
    assert [reference["native_introduction_raw"] for reference in references] == list(dates)
    if expected is None:
        assert pd.isna(bill["native_introduction_date"])
        assert not bill["native_in_window"]
        assert bill["date_evidence_status"] == "conflicting_native_introduction_observations"
        assert joined["native_in_window"].all()
    else:
        assert bill["native_introduction_date"] == expected
        assert bill["native_in_window"]
        assert bill["date_evidence_status"] == "native_source_dates_agree"


@pytest.mark.parametrize(
    "field",
    ["state", "identifier", "session_identifier", "source_introduction_date", "window_disposition"],
)
def test_bill_aggregation_requires_consistent_canonical_identity_and_source_dates(field):
    contexts, _ = reference_pair()
    joined = join_contexts(contexts, ledger())
    joined.loc[1, field] = "inconsistent"
    with pytest.raises(ValueError, match="canonical bill identity/source-date fields disagree"):
        aggregate_bill_contexts(joined)


@pytest.mark.parametrize("defect", ["orphan", "duplicate-reader", "empty", "bad-hash"])
def test_invalid_view_indexes_fail(defect):
    spec, raw, views = inputs("views")
    if defect == "orphan":
        views.loc[0, "context_id"] = "foreign"
    elif defect == "duplicate-reader":
        views.loc[0, "reader"] = "pymupdf"
    elif defect == "empty":
        views.loc[0, "n_input_characters"] = 0
    else:
        views.loc[0, "input_sha256"] = "missing"
    with pytest.raises(ValueError, match="invalid or orphaned"):
        normalize_packet(spec, raw, views)


def test_reader_context_disagreement_is_not_silently_deduplicated():
    spec, raw, views = inputs("reader_rows")
    raw.loc[1, "identifier"] = "HB 2"
    with pytest.raises(ValueError, match="reader variants disagree"):
        normalize_packet(spec, raw, views)


def test_null_id_packet_never_falls_back_to_guessing_aliases():
    spec, raw, views = inputs()
    raw["bill_id"] = None
    contexts, _ = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, ledger())
    assert result["bill_id"].isna().all()
    assert not result["source_in_window"].any()


@pytest.mark.parametrize("field", ["identifier", "source_session"])
@pytest.mark.parametrize("missing", [None, ""])
def test_missing_identity_requires_opt_in_and_never_joins_declared_ids(field, missing):
    spec, raw, views = inputs()
    spec["session_identifier"] = "source_session"
    raw["source_session"] = "20232024"
    raw.loc[0, field] = missing
    with pytest.raises(ValueError, match="native context identity"):
        normalize_packet(spec, raw, views)
    spec["allow_missing_identity"] = True
    contexts, retained = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, ledger()).set_index("context_id")
    assert len(result) == len(raw) and len(retained) == len(raw)
    assert result.loc["one", "declared_bill_id"] == "b1"
    assert pd.isna(result.loc["one", "bill_id"])
    assert result.loc["one", "canonical_join_basis"] == "source_only_unresolved_identity"
    assert not result.loc["one", "source_in_window"]
    assert not result["analytical_admission"].any()
    assert not result["native_identity_certified"].any()


def test_all_missing_identities_cannot_match_canonical_null_keys():
    spec, raw, views = inputs()
    spec.pop("bill_id")
    spec.update(allow_missing_identity=True, session_identifier="source_session")
    raw["identifier"] = float("nan")
    raw["source_session"] = None
    canonical = ledger()
    canonical["identifier"] = None
    canonical["session_identifier"] = None
    contexts, retained = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, canonical)
    assert len(result) == len(raw) and len(retained) == len(raw)
    assert result["bill_id"].isna().all()
    assert result["source_introduction_date"].isna().all()
    assert not result["source_in_window"].any()


def test_source_only_cannot_inherit_preserved_canonical_named_source_fields():
    spec, raw, views = inputs()
    spec.update(
        allow_missing_identity=True,
        preserve_context_fields=["bill_id", "source_introduction_date", "window_disposition"],
    )
    raw.loc[0, "identifier"] = None
    raw["source_introduction_date"] = "2023-02-01"
    raw["window_disposition"] = "source_introduction_in_window"
    contexts, _ = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, ledger()).set_index("context_id")
    assert pd.isna(result.loc["one", "bill_id"])
    assert pd.isna(result.loc["one", "source_introduction_date"])
    assert result.loc["one", "bill_id_native"] == "b1"
    assert result.loc["one", "source_introduction_date_native"] == "2023-02-01"
    assert not result.loc["one", "source_in_window"]


@pytest.mark.parametrize("field", ["record_id", "state"])
def test_missing_identity_opt_in_does_not_allow_missing_context_or_state(field):
    spec, raw, views = inputs()
    spec["allow_missing_identity"] = True
    if field == "state":
        spec["state"] = None
    else:
        raw.loc[0, field] = None
    with pytest.raises(ValueError, match="native context"):
        normalize_packet(spec, raw, views)


def test_source_only_selector_blocks_typed_and_declared_matches_without_discarding_evidence():
    spec, raw, views = inputs()
    spec.update(
        source_only={
            "selector": "original_source_record_json.population_kind",
            "values": ["native_untyped", "canonical_only"],
        },
        preserve_context_fields=["original_source_record_json", "negative_flags_json"],
        native_introduction_field="introduced",
        native_introduction_guard="is_introduced",
    )
    raw["original_source_record_json"] = [
        '{"population_kind": "canonical_only"}',
        '{"population_kind": "native_typed"}',
        '{"population_kind": "native_untyped"}',
    ]
    raw["negative_flags_json"] = '{"identity_approved": false, "analytical_approved": false}'
    raw["introduced"] = "2023-02-01"
    raw["is_introduced"] = [False, True, False]
    contexts, retained = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, ledger()).set_index("context_id")
    assert len(result) == len(raw) and len(retained) == len(raw)
    assert result.loc["old", "bill_id"] == "b2"
    for context_id in ("one", "native-only"):
        assert pd.isna(result.loc[context_id, "bill_id"])
        assert pd.isna(result.loc[context_id, "native_introduction_date"])
        assert pd.isna(result.loc[context_id, "source_introduction_date"])
        assert result.loc[context_id, "native_introduction_raw"] == "2023-02-01"
        assert not result.loc[context_id, "native_in_window"]
        assert not result.loc[context_id, "source_in_window"]
    assert result.loc["one", "declared_bill_id"] == "b1"
    assert (
        result.loc["one", "original_source_record_json"]
        == raw.loc[0, "original_source_record_json"]
    )
    assert result["negative_flags_json"].eq(raw.loc[0, "negative_flags_json"]).all()
    assert not result["analytical_admission"].any()
    assert not result["native_identity_certified"].any()
    raw["introduced"] = pd.Series([["header-only", "2024"], "2023-02-01", None], dtype=object)
    contexts, _ = normalize_packet(spec, raw, views)
    assert contexts.loc[0, "native_introduction_raw"] == ["header-only", "2024"]
    assert pd.isna(contexts.loc[0, "native_introduction_date"])


@pytest.mark.parametrize("source_only", [False, True])
@pytest.mark.parametrize("identifier", ["not a typed identity", 123])
def test_opt_in_does_not_accept_malformed_nonmissing_identifiers(source_only, identifier):
    spec, raw, views = inputs()
    spec.update(allow_missing_identity=True, session_identifier="source_session")
    raw["source_session"] = "20232024"
    raw.loc[0, "source_session"] = None
    raw["identifier"] = raw["identifier"].astype(object)
    raw.loc[0, "identifier"] = identifier
    if source_only:
        spec["source_only"] = {"selector": "bill_id", "values": ["b1"]}
    contexts, _ = normalize_packet(spec, raw, views)
    with pytest.raises(ValueError, match="unsupported typed identifier"):
        join_contexts(contexts, ledger())


@pytest.mark.parametrize("declared_bill_id", [False, True])
def test_explicit_negative_flag_array_blocks_all_identity_join_modes(declared_bill_id):
    spec, raw, views = inputs()
    if not declared_bill_id:
        spec.pop("bill_id")
    flag = "quarantined_wrong_session_document_never_exact_native_match"
    spec.update(
        source_only={
            "selector": "negative_flags_json",
            "match": "json_array_any",
            "values": [flag],
        },
        preserve_context_fields=["negative_flags_json"],
    )
    raw["negative_flags_json"] = [json.dumps([flag]), "[]", json.dumps([f"{flag}_other"])]
    contexts, retained = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, ledger()).set_index("context_id")
    assert pd.isna(result.loc["one", "bill_id"])
    assert not result.loc["one", "source_in_window"]
    assert result.loc["old", "bill_id"] == "b2"
    if not declared_bill_id:
        assert result.loc["native-only", "bill_id"] == "b3"
    assert contexts["negative_flags_json"].tolist() == raw["negative_flags_json"].tolist()
    assert len(retained) == len(raw)


@pytest.mark.parametrize("flags", ['{"flag": true}', "[1]", "invalid-json"])
def test_negative_flag_selector_requires_a_json_string_array(flags):
    spec, raw, views = inputs()
    spec["source_only"] = {
        "selector": "negative_flags_json",
        "match": "json_array_any",
        "values": ["quarantined"],
    }
    raw["negative_flags_json"] = flags
    with pytest.raises(ValueError, match="JSON string array"):
        normalize_packet(spec, raw, views)


def test_reader_allowlist_is_opt_in_and_only_supported_for_views_profile():
    spec, raw, source_views = inputs("views")
    _, original = normalize_packet(spec, raw, source_views)
    spec["view_reader_allowlist"] = ["pypdf"]
    contexts, filtered = normalize_packet(spec, raw, source_views)
    assert len(original) == 2 and len(filtered) == 1
    assert filtered["reader"].tolist() == ["pypdf"]
    assert contexts["n_excluded_views"].tolist() == [1, 0, 0]
    assert contexts["n_retained_views"].tolist() == [1, 0, 0]
    assert len(source_views) == 2
    spec, raw, source_views = inputs()
    spec["view_reader_allowlist"] = ["native_caml"]
    with pytest.raises(ValueError, match="views profile"):
        normalize_packet(spec, raw, source_views)


def test_native_regular_session_crosswalk_is_explicit_and_preserves_original_key():
    spec, raw, views = inputs()
    spec.pop("canonical_session")
    spec.update(session_identifier="source_session", session_map={"88R": "88"})
    raw["source_session"] = "88R"
    canonical = ledger()
    canonical["session_identifier"] = "88"
    contexts, _ = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, canonical)
    assert result.loc[result.bill_id.notna(), "session_identifier"].eq("88").all()
    assert result["native_session_identifier"].eq("88R").all()
    raw.loc[0, "source_session"] = "88S"
    with pytest.raises(ValueError, match="explicit canonical crosswalk"):
        normalize_packet(spec, raw, views)


def test_explicit_unavailable_html_shell_is_retained_but_never_counted_as_input():
    spec, raw, views = inputs()
    spec.update(
        view_available="input_available",
        view_character_count="body_characters",
        source_kind="native_html_body",
    )
    raw["body_characters"] = raw.pop("n_input_characters")
    raw["input_available"] = [False, True, True]
    raw.loc[0, "input_sha256"] = None
    contexts, indexed = normalize_packet(spec, raw, views)
    assert len(contexts) == 3
    assert len(indexed) == 2
    assert indexed["reader"].eq("native_html_body").all()
    assert contexts.set_index("context_id").loc["one", "n_retained_views"] == 0
    raw["input_available"] = ["False", "True", "True"]
    with pytest.raises(ValueError, match="explicit boolean"):
        normalize_packet(spec, raw, views)


@pytest.mark.parametrize(
    "raw,expected,date",
    [
        ("2022-12-31T23:30:00-06:00", "native_introduction_before_window", "2022-12-31"),
        ("2023-01-01 00:00:00", "native_introduction_in_window", "2023-01-01"),
        ("2024-12-31", "native_introduction_in_window", "2024-12-31"),
        ("2025-01-01", "native_introduction_after_window", "2025-01-01"),
        (None, "missing_native_introduction_observation", None),
        ("2023-01-01not-a-date", "invalid_native_introduction_observation", None),
    ],
)
def test_native_reported_date_requires_complete_value_and_keeps_local_day(raw, expected, date):
    assert native_introduction_observation(raw) == (date, expected)


def test_native_date_adds_evidence_without_replacing_unknown_or_conflicting_source_dates():
    spec, raw, views = inputs()
    spec.update(native_introduction_field="introduced", native_introduction_guard="is_introduced")
    raw["introduced"] = ["2023-02-01", "2023-02-02", None]
    raw["is_introduced"] = True
    contexts, _ = normalize_packet(spec, raw, views)
    canonical = ledger()
    canonical.loc[canonical.bill_id.eq("b2"), "source_introduction_date"] = ""
    canonical.loc[canonical.bill_id.eq("b2"), "window_disposition"] = (
        "no_source_introduction_action"
    )
    result = join_contexts(contexts, canonical).set_index("context_id")
    assert result.loc["old", "native_in_window"]
    assert not result.loc["old", "source_in_window"]
    assert result.loc["old", "window_disposition"] == "no_source_introduction_action"
    assert result.loc["old", "date_evidence_status"] == "native_date_only_source_unresolved"
    raw.loc[0, "is_introduced"] = False
    with pytest.raises(ValueError, match="explicit introduced records"):
        normalize_packet(spec, raw, views)


def test_comparable_native_and_source_dates_keep_disagreement_visible():
    spec, raw, views = inputs()
    spec["native_introduction_field"] = "introduced"
    raw["introduced"] = ["2023-02-01", "2023-02-02", None]
    contexts, _ = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, ledger()).set_index("context_id")
    assert result.loc["one", "date_evidence_status"] == "native_source_dates_agree"
    assert result.loc["old", "date_evidence_status"] == "native_source_dates_differ"
    assert result.loc["old", "source_introduction_date"] == "2019-02-01"


def test_conditional_native_dates_keep_formal_events_separate_from_drafts_and_ancillary():
    spec, raw, source_views = inputs("views")
    raw = pd.concat([raw, raw.iloc[[-1]]], ignore_index=True)
    raw.loc[3, "record_id"] = "missing-guard"
    raw.loc[3, "identifier"] = "HB 4"
    date_key = "intro_bound_native_origin_date_observation"
    context_key = "intro_source_context_status"
    event_key = "intro_bound_native_event_status"
    formal_status = "exact_formal_identity_native_event_observation"
    unique_event = "unique_origin_introduction_event"
    source_records = [
        {
            context_key: formal_status,
            event_key: unique_event,
            date_key: "2024-12-31T23:30:00-06:00",
        },
        {context_key: "lc_draft_request", date_key: "2023-01-01"},
        {context_key: formal_status, event_key: "ancillary_history"},
        {date_key: "2023-01-01"},
    ]
    raw["original_source_record_json"] = [json.dumps(record) for record in source_records]
    spec.update(
        view_reader_allowlist=[],
        preserve_context_fields=["original_source_record_json"],
        native_introduction_field=f"original_source_record_json.{date_key}",
        native_introduction_when=[
            {
                "selector": f"original_source_record_json.{context_key}",
                "values": [formal_status],
            },
            {
                "selector": f"original_source_record_json.{event_key}",
                "values": [unique_event],
            },
        ],
    )
    contexts, retained = normalize_packet(spec, raw, source_views)
    assert retained.empty and len(contexts) == 4
    assert contexts["n_retained_views"].eq(0).all()
    assert contexts["n_excluded_views"].sum() == len(source_views)
    assert contexts["native_introduction_date"].tolist() == ["2024-12-31", None, None, None]
    assert contexts.loc[1:, "native_introduction_raw"].isna().all()
    assert (
        contexts.loc[1:, "native_window_disposition"].eq("not_supplied_by_registered_packet").all()
    )
    assert (
        contexts["original_source_record_json"].tolist()
        == raw["original_source_record_json"].tolist()
    )
    assert not contexts["native_identity_certified"].any()
    assert not contexts["analytical_admission"].any()
    for missing in ({}, {date_key: None}):
        raw.loc[0, "original_source_record_json"] = json.dumps(
            {context_key: formal_status, event_key: unique_event, **missing}
        )
        with pytest.raises(ValueError, match="matching native introduction condition lacks a date"):
            normalize_packet(spec, raw, source_views)
    raw.loc[0, "original_source_record_json"] = json.dumps({context_key: "lc_draft_request"})
    without_formal_events, _ = normalize_packet(spec, raw, source_views)
    assert without_formal_events["native_introduction_date"].isna().all()
    raw.loc[0, "original_source_record_json"] = json.dumps(source_records[0])
    spec["native_introduction_guard"] = "is_introduced"
    raw["is_introduced"] = [True, False, True, True]
    with pytest.raises(ValueError, match="explicit introduced records"):
        normalize_packet(spec, raw, source_views)


def test_explicit_native_special_session_crosswalk_links_only_mapped_contexts():
    spec, raw, views = inputs()
    spec.update(
        source_only_session_fields=["native_session_num"],
        source_only_session_map={"1": "20232024 Special Session 1"},
    )
    raw["native_session_num"] = ["0", "0", "1"]
    contexts, _ = normalize_packet(spec, raw, views)
    canonical = ledger()
    canonical.loc[canonical.bill_id.eq("b3"), "session_identifier"] = "20232024 Special Session 1"
    result = join_contexts(contexts, canonical).set_index("context_id")
    assert result.loc["native-only", "bill_id"] == "b3"
    assert result.loc["native-only", "session_binding"] == "explicit_native_session_code_crosswalk"
    assert not result.loc["native-only", "source_in_window"]
    raw.loc[2, "native_session_num"] = "99"
    contexts, _ = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, canonical).set_index("context_id")
    assert pd.isna(result.loc["native-only", "bill_id"])


def test_colorado_hyphenated_identifier_is_preserved_not_rewritten():
    spec, raw, views = inputs()
    spec.update(state="CO", canonical_session="2023A")
    raw = raw.iloc[:1].copy()
    raw["identifier"] = "HB 23-1001"
    canonical = ledger().iloc[:1].copy()
    canonical["state"] = "CO"
    canonical["identifier"] = "HB 23-1001"
    canonical["session_identifier"] = "2023A"
    contexts, _ = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, canonical)
    assert result["bill_id"].tolist() == ["b1"]
    assert result["native_identifier"].tolist() == ["HB 23-1001"]


def test_unselected_sessions_do_not_expand_adapter_scope():
    spec, raw, views = inputs()
    contexts, _ = normalize_packet(spec, raw, views)
    canonical = ledger()
    canonical.loc[len(canonical)] = [
        "CA",
        "unselected",
        "UNREVIEWED-SPECIAL-FORMAT",
        "other-special-session",
        "source_introduction_in_window",
        "2023-03-05",
    ]
    result = join_contexts(contexts, canonical)
    assert result["bill_id"].dropna().tolist() == ["b1", "b2"]


@pytest.mark.parametrize("state", ["MI", "WA"])
def test_michigan_exact_letter_joint_resolutions_do_not_become_generic_aliases(state):
    spec, raw, views = inputs()
    spec.update(state=state, canonical_session="2023-2024")
    raw.loc[0, "identifier"] = "HJR A"
    canonical = ledger()
    canonical["state"] = state
    canonical["session_identifier"] = "2023-2024"
    canonical.loc[0, "identifier"] = "HJR A"
    contexts, _ = normalize_packet(spec, raw, views)
    if state == "MI":
        result = join_contexts(contexts, canonical)
        assert result.loc[result.context_id.eq("one"), "bill_id"].tolist() == ["b1"]
    else:
        with pytest.raises(ValueError, match="unsupported typed"):
            join_contexts(contexts, canonical)


def test_retained_negative_flags_and_raw_dates_are_not_silently_admitted():
    spec, raw, views = inputs()
    spec["preserve_context_fields"] = ["negative_flags_json", "native_date_observations_json"]
    raw["negative_flags_json"] = '{"identity_unresolved": true}'
    raw["native_date_observations_json"] = '[{"event_kind": "reading", "raw_value": "2023"}]'
    contexts, _ = normalize_packet(spec, raw, views)
    assert contexts["negative_flags_json"].tolist() == raw["negative_flags_json"].tolist()
    assert (
        contexts["native_date_observations_json"].tolist()
        == raw["native_date_observations_json"].tolist()
    )
    assert contexts["native_introduction_date"].isna().all()
    assert not contexts["analytical_admission"].any()
    spec["preserve_context_fields"] = ["state"]
    with pytest.raises(ValueError, match="cannot override"):
        normalize_packet(spec, raw, views)


def packet(tmp_path):
    spec, raw, _ = inputs()
    root = tmp_path / "native"
    root.mkdir()
    raw.to_parquet(root / "candidate_inputs.parquet", index=False)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    "candidate_inputs.parquet": sha256_file(root / "candidate_inputs.parquet")
                },
            }
        )
    )
    spec.update(
        {
            "root": str(root),
            "contexts": "candidate_inputs.parquet",
            "manifest_sha256": sha256_file(root / "manifest.json"),
            "expected_contexts": 3,
            "expected_views": 3,
        }
    )
    registry = tmp_path / "registry.yml"
    registry.write_text(yaml.safe_dump({"schema_version": 1, "packets": [spec]}))
    matrix_dir = tmp_path / "matrix"
    matrix_dir.mkdir()
    ledger_path = tmp_path / "ledger.csv"
    original = ledger()
    original.loc[len(original)] = [
        "CA",
        "b4",
        "HB 4",
        "20232024",
        "source_introduction_in_window",
        "2023-03-05",
    ]
    original.to_csv(ledger_path, index=False)
    pd.DataFrame(
        {
            "state": sorted(_STATES),
            "native_cycle_denominator": None,
            "recovered_cycle_text_count": None,
            "n_source_in_window": [2 if state == "CA" else 0 for state in sorted(_STATES)],
        }
    ).to_csv(matrix_dir / "state_matrix.csv", index=False)
    (matrix_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete_all_state_triage_not_native_coverage_or_analytical_admission",
                "inputs": {
                    "ledger": {
                        "path": str(ledger_path),
                        "sha256": sha256_file(ledger_path),
                    }
                },
                "artifacts": {
                    "state_matrix.csv": {
                        "sha256": sha256_file(matrix_dir / "state_matrix.csv"),
                    }
                },
            }
        )
    )
    return matrix_dir, registry, root


def test_persistent_overlap_keeps_unregistered_unknown_and_exports_exact_missing_ids(tmp_path):
    matrix, registry, _ = packet(tmp_path)
    out = tmp_path / "out"
    report = build_overlap(matrix, registry, out)
    assert report["n_native_contexts"] == 3
    assert report["n_reader_or_source_views_not_bills"] == 3
    assert report["n_source_only_contexts"] == 1
    assert report["n_source_in_window_without_supplied_native_text"] == 1
    missing = pd.read_parquet(out / "missing_supplied_native_text.parquet")
    assert missing["bill_id"].tolist() == ["b4"]
    result = pd.read_csv(out / "state_matrix.csv").set_index("state")
    assert result.loc["CA", "n_source_in_window_with_supplied_native_text"] == 1
    assert pd.isna(result.loc["AL", "n_source_in_window_with_supplied_native_text"])
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["inputs_unchanged"]
    for name, binding in manifest["artifacts"].items():
        assert sha256_file(out / name) == binding["sha256"]
    with pytest.raises(FileExistsError):
        build_overlap(matrix, registry, out)


@pytest.mark.parametrize("conflicting_date", [False, True])
def test_reference_packets_use_unique_bill_counts_but_keep_all_contexts_and_views(
    tmp_path, conflicting_date
):
    matrix, registry, root = packet(tmp_path)
    config = yaml.safe_load(registry.read_text())
    spec = config["packets"][0]
    spec["native_introduction_field"] = "introduced"
    raw = pd.read_parquet(root / "candidate_inputs.parquet")
    raw["introduced"] = ["2023-02-01", "2023-02-02", None]

    def save_inputs(packet_root, frame):
        name = "candidate_inputs.parquet"
        frame.to_parquet(packet_root / name, index=False)
        manifest = packet_root / "manifest.json"
        manifest.write_text(json.dumps({"files": {name: sha256_file(packet_root / name)}}))
        return sha256_file(manifest)

    spec["manifest_sha256"] = save_inputs(root, raw)
    reference_root = tmp_path / "references"
    reference_root.mkdir()
    reference_raw = raw.iloc[:1].copy()
    reference_raw["record_id"] = "reference-one"
    reference_raw["introduced"] = "2023-02-02" if conflicting_date else "2023-02-01"
    reference_spec = dict(spec)
    reference_spec.update(
        packet_id="CA_references",
        root=str(reference_root),
        context_granularity="source_reference",
        expected_contexts=1,
        expected_views=1,
        manifest_sha256=save_inputs(reference_root, reference_raw),
    )
    config["packets"].append(reference_spec)
    registry.write_text(yaml.safe_dump(config))
    out = tmp_path / "out"
    report = build_overlap(matrix, registry, out)
    assert report["n_native_contexts"] == 4
    assert report["n_reader_or_source_views_not_bills"] == 4
    assert report["n_canonical_bills_with_native_contexts"] == 2
    contexts = pd.read_parquet(out / "native_context_overlap.parquet")
    assert len(contexts) == 4
    assert len(pd.read_parquet(out / "native_view_index.parquet")) == 4
    bills = pd.read_parquet(out / "native_bill_overlap.parquet").set_index("bill_id")
    assert len(bills) == 2 and bills.loc["b1", "n_retained_views"] == 2
    assert bills.loc["b1", "n_native_contexts"] == 2
    saved = pd.read_csv(out / "state_matrix.csv").set_index("state")
    assert saved.loc["CA", "n_supplied_native_contexts"] == 4
    assert saved.loc["CA", "n_supplied_native_views"] == 4
    assert saved.loc["CA", "n_source_in_window_with_supplied_native_text"] == 1
    assert saved.loc["CA", "n_source_in_window_without_supplied_native_text"] == 1
    assert saved.loc["CA", "n_native_in_window_with_join_and_text"] == (
        1 if conflicting_date else 2
    )
    assert saved.loc["CA", "n_native_in_window_text_with_outside_source_date"] == 1
    assert saved.loc["CA", "n_native_source_date_disagreements_cycle_relevant"] == 1
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["artifacts"]["native_bill_overlap.parquet"]["sha256"] == sha256_file(
        out / "native_bill_overlap.parquet"
    )
    assert manifest["inputs_unchanged"]


def test_entirely_source_only_packet_keeps_raw_evidence_and_empty_bill_artifact(tmp_path):
    matrix, registry, _ = packet(tmp_path)
    config = yaml.safe_load(registry.read_text())
    config["packets"][0]["source_only"] = {
        "selector": "identifier",
        "values": ["HB 1", "HB 2", "HB 3"],
    }
    registry.write_text(yaml.safe_dump(config))
    out = tmp_path / "out"
    report = build_overlap(matrix, registry, out)
    assert report["n_native_contexts"] == 3
    assert report["n_reader_or_source_views_not_bills"] == 3
    assert report["n_canonical_bills_with_native_contexts"] == 0
    bills = pd.read_parquet(out / "native_bill_overlap.parquet")
    assert bills.empty
    assert {"bill_id", "source_contexts_json", "native_in_window"}.issubset(bills.columns)
    assert pd.api.types.is_integer_dtype(bills["n_retained_views"].dtype)
    assert len(pd.read_parquet(out / "native_context_overlap.parquet")) == 3


def test_modified_native_packet_is_not_accepted_by_stale_manifest(tmp_path):
    matrix, registry, root = packet(tmp_path)
    raw = pd.read_parquet(root / "candidate_inputs.parquet")
    raw.loc[0, "input_sha256"] = "d" * 64
    raw.to_parquet(root / "candidate_inputs.parquet", index=False)
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="checksum mismatch"):
        build_overlap(matrix, registry, out)
    assert not out.exists()


def test_registered_source_only_selector_is_loaded_and_never_counts_as_joined_text(tmp_path):
    matrix, registry, root = packet(tmp_path)
    config = yaml.safe_load(registry.read_text())
    spec = config["packets"][0]
    spec.update(
        allow_missing_identity=True,
        source_only={
            "selector": "original_source_record_json.population_kind",
            "values": ["canonical_only"],
        },
        preserve_context_fields=["original_source_record_json"],
    )
    raw = pd.read_parquet(root / "candidate_inputs.parquet")
    raw["original_source_record_json"] = [
        '{"population_kind": "canonical_only"}',
        '{"population_kind": "native_typed"}',
        '{"population_kind": "native_untyped"}',
    ]
    raw.loc[2, "identifier"] = None
    raw.to_parquet(root / "candidate_inputs.parquet", index=False)
    (root / "manifest.json").write_text(
        json.dumps(
            {"files": {"candidate_inputs.parquet": sha256_file(root / "candidate_inputs.parquet")}}
        )
    )
    spec["manifest_sha256"] = sha256_file(root / "manifest.json")
    registry.write_text(yaml.safe_dump(config))
    out = tmp_path / "out"
    report = build_overlap(matrix, registry, out)
    assert report["n_native_contexts"] == 3
    assert report["n_reader_or_source_views_not_bills"] == 3
    assert report["n_source_only_contexts"] == 2
    assert report["n_source_in_window_without_supplied_native_text"] == 2
    saved = pd.read_csv(out / "state_matrix.csv").set_index("state")
    assert saved.loc["CA", "n_source_in_window_with_supplied_native_text"] == 0
    assert pd.isna(saved.loc["CA", "n_native_in_window_with_join_and_text"])


def test_observations_profile_binds_flat_dates_without_views_or_text_columns(tmp_path):
    matrix, registry, root = packet(tmp_path)
    config = yaml.safe_load(registry.read_text())
    spec = config["packets"][0]
    context_key = "intro_source_context_status"
    event_key = "intro_bound_native_event_status"
    date_key = "intro_bound_native_origin_date_observation"
    formal_status = "exact_formal_identity_native_event_observation"
    unique_event = "unique_origin_introduction_event"
    raw = pd.DataFrame(
        {
            "bill_id": ["b1", "b2", "b3"],
            "state": ["CA"] * 3,
            "identifier": ["HB 1", "LC 2", "HB 3"],
            "session_identifier": ["2025", "2023", "2023"],
            "source_identity_kind": ["formal_measure", "draft_request", "formal_measure"],
            context_key: [formal_status, "draft_request_not_formal_event", formal_status],
            event_key: [unique_event, None, unique_event],
            date_key: ["2024-12-31", None, "2023-02-01"],
        }
    )
    name = "source_introduction_observations.parquet"
    raw.to_parquet(root / name, index=False)
    (root / "manifest.json").write_text(json.dumps({"files": {name: sha256_file(root / name)}}))
    spec.update(
        profile="observations",
        context_id="bill_id",
        contexts=name,
        session_identifier="session_identifier",
        expected_views=0,
        manifest_sha256=sha256_file(root / "manifest.json"),
        preserve_context_fields=["source_identity_kind", context_key, event_key, date_key],
        native_introduction_field=date_key,
        native_introduction_when=[
            {"selector": context_key, "values": [formal_status]},
            {"selector": event_key, "values": [unique_event]},
        ],
    )
    registry.write_text(yaml.safe_dump(config))
    ledger_path = tmp_path / "ledger.csv"
    canonical = pd.read_csv(ledger_path, dtype=str, keep_default_na=False)
    canonical.loc[canonical.bill_id.eq("b1"), "session_identifier"] = "2025"
    canonical.loc[canonical.bill_id.isin(["b2", "b3"]), "session_identifier"] = "2023"
    canonical.loc[canonical.bill_id.eq("b2"), "identifier"] = "LC 2"
    canonical.to_csv(ledger_path, index=False)
    matrix_manifest = json.loads((matrix / "manifest.json").read_text())
    matrix_manifest["inputs"]["ledger"]["sha256"] = sha256_file(ledger_path)
    (matrix / "manifest.json").write_text(json.dumps(matrix_manifest))
    out = tmp_path / "out"
    report = build_overlap(matrix, registry, out)
    assert report["n_native_contexts"] == 3
    assert report["n_reader_or_source_views_not_bills"] == 0
    assert report["n_source_in_window_without_supplied_native_text"] == 2
    contexts = pd.read_parquet(out / "native_context_overlap.parquet").set_index("context_id")
    assert contexts["n_retained_views"].eq(0).all()
    assert contexts.loc["b1", "native_introduction_date"] == "2024-12-31"
    assert contexts.loc["b1", "session_identifier"] == "2025"
    assert contexts.loc["b1", "native_in_window"]
    assert pd.isna(contexts.loc["b2", "native_introduction_date"])
    assert not contexts.loc["b2", "native_in_window"]
    assert contexts.loc["b2", "source_identity_kind"] == "draft_request"
    assert pd.read_parquet(out / "native_view_index.parquet").empty
    saved = pd.read_csv(out / "state_matrix.csv").set_index("state")
    assert saved.loc["CA", "n_source_in_window_with_supplied_native_text"] == 0
    assert saved.loc["CA", "n_native_in_window_with_join_and_text"] == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert "CA_views" not in manifest["inputs"]
    assert manifest["inputs"]["CA_contexts"]["sha256"] == sha256_file(root / name)
    assert manifest["inputs_unchanged"]
    raw.loc[0, "identifier"] = None
    with pytest.raises(ValueError, match="missing native context identity"):
        normalize_packet(spec, raw, None)


@pytest.mark.parametrize("allowed_readers", [["stored_native_body"], []])
def test_reader_allowlist_reports_excluded_views_and_keeps_full_source_binding(
    tmp_path, allowed_readers
):
    matrix, registry, root = packet(tmp_path)
    config = yaml.safe_load(registry.read_text())
    spec = config["packets"][0]
    source_views = pd.DataFrame(
        {
            "view_id": ["one:markup", "old:body", "native-only:markup"],
            "context_id": ["one", "old", "native-only"],
            "reader": ["html_source_decoded", "stored_native_body", "original_html_markup"],
            "input_sha256": ["a" * 64, "b" * 64, "c" * 64],
            "n_input_characters": [11, 22, 33],
        }
    )
    source_views.to_parquet(root / "views.parquet", index=False)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    name: sha256_file(root / name)
                    for name in ("candidate_inputs.parquet", "views.parquet")
                }
            }
        )
    )
    expected_retained = len(allowed_readers)
    spec.update(
        profile="views",
        views="views.parquet",
        view_reader_allowlist=allowed_readers,
        expected_views=expected_retained,
        manifest_sha256=sha256_file(root / "manifest.json"),
    )
    registry.write_text(yaml.safe_dump(config))
    out = tmp_path / "out"
    report = build_overlap(matrix, registry, out)
    assert report["n_native_contexts"] == 3
    assert report["n_reader_or_source_views_not_bills"] == expected_retained
    assert report["n_reader_views_excluded_by_allowlist"] == 3 - expected_retained
    assert report["reader_allowlist_counts"]["CA"] == {
        "state": "CA",
        "allowed_readers": allowed_readers,
        "n_source_views": 3,
        "n_retained_views": expected_retained,
        "n_excluded_views": 3 - expected_retained,
    }
    contexts = pd.read_parquet(out / "native_context_overlap.parquet")
    assert contexts["n_excluded_views"].sum() == 3 - expected_retained
    filtered = pd.read_parquet(out / "native_view_index.parquet")
    assert filtered["reader"].isin(allowed_readers).all()
    assert report["n_source_in_window_without_supplied_native_text"] == 2
    saved = pd.read_csv(out / "state_matrix.csv").set_index("state")
    assert saved.loc["CA", "n_source_in_window_with_supplied_native_text"] == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["inputs"]["CA_views"]["sha256"] == sha256_file(root / "views.parquet")
    assert manifest["inputs_unchanged"]
    pd.testing.assert_frame_equal(pd.read_parquet(root / "views.parquet"), source_views)


def register_binding_proof(registry, proof, selector, expected):
    config = yaml.safe_load(registry.read_text())
    config["packets"][0]["binding_evidence"] = [
        {
            "path": str(proof),
            "sha256": sha256_file(proof),
            "selector": selector,
            "expected": expected,
        }
    ]
    registry.write_text(yaml.safe_dump(config))


def test_binding_proof_validates_explicit_scope_and_is_snapshotted_without_dates(tmp_path):
    matrix, registry, _ = packet(tmp_path)
    proof = tmp_path / "contract.json"
    proof.write_text(json.dumps({"contract": {"scope": {"session": "2023-2024", "regular": True}}}))
    register_binding_proof(
        registry, proof, "contract.scope", {"regular": True, "session": "2023-2024"}
    )
    out = tmp_path / "out"
    build_overlap(matrix, registry, out)
    manifest = json.loads((out / "manifest.json").read_text())
    binding = manifest["inputs"]["CA_binding_evidence_0"]
    assert binding["path"] == str(proof.resolve())
    assert binding["sha256"] == sha256_file(proof)
    assert manifest["inputs_unchanged"]
    contexts = pd.read_parquet(out / "native_context_overlap.parquet")
    assert contexts["native_introduction_date"].isna().all()


@pytest.mark.parametrize(
    "actual,expected",
    [
        ("2021-2022", "2023-2024"),
        (103, "103"),
        (True, 1),
        (103.0, 103),
        ({"session": True}, {"session": 1}),
    ],
)
def test_binding_proof_wrong_value_or_json_type_fails_before_outputs(
    tmp_path, monkeypatch, actual, expected
):
    matrix, registry, _ = packet(tmp_path)
    proof = tmp_path / "contract.json"
    proof.write_text(json.dumps({"contract": {"scope": actual}}))
    register_binding_proof(registry, proof, "contract.scope", expected)
    monkeypatch.setattr(
        study_native_overlap,
        "_read",
        lambda *args: pytest.fail("native tables read before binding validation"),
    )
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="binding evidence JSON value mismatch"):
        build_overlap(matrix, registry, out)
    assert not out.exists()


@pytest.mark.parametrize("change_during_build", [False, True])
def test_changed_binding_proof_fails_without_fallback(tmp_path, monkeypatch, change_during_build):
    matrix, registry, _ = packet(tmp_path)
    proof = tmp_path / "contract.json"
    proof.write_text('{"contract": {"scope": "2023-2024"}}')
    register_binding_proof(registry, proof, "contract.scope", "2023-2024")
    if change_during_build:
        original_read = study_native_overlap._read

        def read_and_change_proof(*args):
            proof.write_text('{"contract": {"scope": "2021-2022"}}')
            return original_read(*args)

        monkeypatch.setattr(study_native_overlap, "_read", read_and_change_proof)
        expected_error = "inputs changed"
    else:
        proof.write_text('{"contract": {"scope": "2021-2022"}}')
        expected_error = "binding evidence checksum mismatch"
    out = tmp_path / "out"
    with pytest.raises(ValueError, match=expected_error):
        build_overlap(matrix, registry, out)
    if change_during_build:
        assert json.loads((out / "manifest.json").read_text())["status"] == "incomplete"
    else:
        assert not out.exists()


def test_second_accepted_packet_fills_a_gap_without_recollecting_or_session_year_filter(tmp_path):
    matrix, registry, _ = packet(tmp_path)
    original = yaml.safe_load(registry.read_text())
    second = dict(original["packets"][0])
    second.update(
        packet_id="CA_second",
        root=str(tmp_path / "second"),
        expected_contexts=1,
        expected_views=1,
        canonical_session="20252026",
    )
    root = tmp_path / "second"
    root.mkdir()
    _, raw, _ = inputs()
    raw = raw.iloc[:1].copy()
    raw["record_id"] = "prefiled"
    raw["bill_id"] = "b4"
    raw["identifier"] = "HB 4"
    raw.to_parquet(root / "candidate_inputs.parquet", index=False)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    "candidate_inputs.parquet": sha256_file(root / "candidate_inputs.parquet")
                },
            }
        )
    )
    second["manifest_sha256"] = sha256_file(root / "manifest.json")
    original["packets"].append(second)
    registry.write_text(yaml.safe_dump(original))
    source = json.loads((matrix / "manifest.json").read_text())
    ledger_path = tmp_path / "ledger.csv"
    source_ledger = pd.read_csv(ledger_path, dtype=str, keep_default_na=False)
    source_ledger.loc[source_ledger.bill_id.eq("b4"), "session_identifier"] = "20252026"
    source_ledger.to_csv(ledger_path, index=False)
    source["inputs"]["ledger"]["sha256"] = sha256_file(ledger_path)
    (matrix / "manifest.json").write_text(json.dumps(source))
    out = tmp_path / "out"
    report = build_overlap(matrix, registry, out)
    assert report["registered_states"] == ["CA"]
    assert report["n_native_contexts"] == 4
    assert report["n_source_in_window_without_supplied_native_text"] == 0
    saved = pd.read_parquet(out / "native_context_overlap.parquet").set_index("context_id")
    assert saved.loc["prefiled", "source_in_window"]
    assert saved.loc["prefiled", "session_identifier"] == "20252026"

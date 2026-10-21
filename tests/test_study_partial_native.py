"""Retained initial-source selectors preserve whole, separate unapproved inputs."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from state_politics.bills.study_partial_native import (
    FrozenPacket,
    _digest,
    _reader_inputs,
    _records,
    build_state,
    complete_view,
    native_date_observations,
    reconcile_tables,
)


class MemoryPacket:
    root = Path("data/processed/unit-initial-source").resolve()

    def __init__(self, files):
        self.files = files

    def read(self, name):
        return self.files[name]

    def pin(self, name):
        return {"sha256": _digest(name)}


def source(reader="pypdf", segments=None):
    return {
        "reader": reader,
        "source_reader": reader,
        "segments": segments if segments is not None else ["first\u2028page", "\f第二頁\n"],
        "extraction_path": "stored.json",
        "extraction_selector": f"{reader}/*/text",
        "source_path": "original.pdf",
        "source_url": "https://publisher.invalid/original",
        "source_sha256": None,
        "n_pages": 2,
        "kind": "original_pdf",
    }


def context(available=True):
    return {"context_id": "literal-source-context", "source_record": {}, "available": available}


def test_complete_reader_alternatives_keep_every_character_and_remain_one_context():
    packet = MemoryPacket({})
    record = context()
    views = pd.DataFrame([
        complete_view(packet, record, source()),
        complete_view(packet, record, source("pymupdf", ["different\n", "whole text"])),
    ])
    contexts = pd.DataFrame([{"context_id": record["context_id"], "n_retained_views": 2}])
    result = reconcile_tables(contexts, views)
    assert result["n_contexts"] == 1
    assert result["n_source_views"] == 2
    assert views.iloc[0]["text"] == "first\u2028page\f第二頁\n"
    assert json.loads(views.iloc[0]["segment_character_counts_json"]) == [10, 5]
    assert views.iloc[0]["input_sha256"] == _digest(views.iloc[0]["text"])
    assert not views[["approved", "policy_eligible", "analytical_admission"]].any().any()


@pytest.mark.parametrize("defect", ["empty", "missing-segment", "wrong-original"])
def test_incomplete_or_changed_originals_fail_closed(defect):
    item = source()
    if defect == "empty":
        item["segments"] = [" \n", ""]
    elif defect == "missing-segment":
        item["segments"] = ["first", None]
    else:
        item["source_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        complete_view(MemoryPacket({}), context(), item)


@pytest.mark.parametrize("defect", ["truncated", "orphan", "duplicate-reader", "admitted"])
def test_whole_text_and_context_reconciliation_rejects_false_counts(defect):
    packet = MemoryPacket({})
    views = pd.DataFrame([complete_view(packet, context(), source())])
    contexts = pd.DataFrame([{"context_id": "literal-source-context", "n_retained_views": 1}])
    if defect == "truncated":
        views.loc[0, "text"] = views.loc[0, "text"][:-1]
    elif defect == "orphan":
        views.loc[0, "context_id"] = "not-accepted"
    elif defect == "duplicate-reader":
        duplicate = views.iloc[0].copy()
        duplicate["view_id"] = "another-id-same-reader"
        views = pd.concat([views, duplicate.to_frame().T], ignore_index=True)
    else:
        views.loc[0, "policy_eligible"] = True
    with pytest.raises(ValueError):
        reconcile_tables(contexts, views)


def test_maryland_calendar_and_detail_html_never_become_bill_text():
    view = {
        "purpose": "selected_first_text_pdf",
        "source_url": "literal-original-url",
        "page_count": 2,
        "pymupdf_pages": ["all-one", "all-two"],
        "pypdf_pages": ["other-one", "other-two"],
    }
    packet = MemoryPacket({
        "source_views.json": {
            "pdf_views": {"x0016": view, "calendar": {"purpose": "calendar"}},
            "html_views": {"detail": {"all_text_nodes": ["not full bill text"]}},
        },
    })
    record = context() | {
        "source_record": {"pdf_exchange": "x0016", "first_text_url": "literal-original-url"},
    }
    inputs = list(_reader_inputs(packet, "MD", {"contexts": "source_views.json"}, record))
    assert [item["reader"] for item in inputs] == ["pymupdf", "pypdf"]
    assert inputs[0]["segments"] == ["all-one", "all-two"]
    view["purpose"] = "publisher_calendar"
    with pytest.raises(ValueError, match="calendar or non-original"):
        list(_reader_inputs(packet, "MD", {"contexts": "source_views.json"}, record))


def test_minnesota_uses_final_exchanges_all_html_spans_and_two_pdf_readers():
    packet = MemoryPacket({
        "projections/109.html.json": {
            "full_source_markup": "<html>front matter<div>entire original</div></html>",
            "document_markup": "<div>entire original</div>",
            "text_spans": [{"decoded": "front matter\n"}, {"decoded": "entire original"}],
        },
        "transport/109/writeout.json": {"http_code": 200, "url_effective": "actual-html"},
        "projections/110.pdf.json": {
            "page_count": 2,
            "fitz": [{"page": 1, "text": "fitz1"}, {"page": 2, "text": "fitz2"}],
            "pypdf": [{"page": 1, "text": "pypdf1"}, {"page": 2, "text": "pypdf2"}],
        },
        "transport/110/writeout.json": {"http_code": 200, "url_effective": "actual-pdf"},
    })
    record = context() | {
        "source_record": {"html_exchange": 109, "pdf_exchange": 110, "page_count": 2},
    }
    inputs = list(_reader_inputs(packet, "MN", {}, record))
    assert [item["reader"] for item in inputs] == ["html_full_projection", "pymupdf", "pypdf"]
    assert inputs[0]["segments"] == ["front matter\n", "entire original"]
    assert inputs[1]["segments"] == ["fitz1", "fitz2"]
    assert inputs[2]["source_reader"] == "pypdf"
    assert inputs[2]["source_url"] == "actual-pdf"


@pytest.mark.parametrize("state", ["MI", "MD", "MN", "KY", "AZ", "KS", "OR", "VA"])
def test_selected_unavailable_contexts_cannot_emit_placeholder_or_notice_text(state):
    assert list(_reader_inputs(MemoryPacket({}), state, {}, context(False))) == []


def test_kentucky_keeps_text_not_layout_and_never_interprets_br_as_identity():
    packet = MemoryPacket({
        "derived/source_views.json": {
            "x0013": {"kind": "PDF", "view": {
                "pymupdf": [{"physical_page": 1, "text": "23 RS BR 225\nwhole bill"}],
                "pypdf": [{
                    "physical_page": 1, "text": "23 RS BR 225 whole bill",
                    "layout_text": "must not substitute this alternative extraction",
                }],
            }},
        },
    })
    record = context() | {
        "source_record": {
            "original_exchange": "x0013", "original_stage": {"url": "literal-original"},
        },
    }
    inputs = list(_reader_inputs(packet, "KY", {}, record))
    assert inputs[1]["segments"] == ["23 RS BR 225 whole bill"]
    assert len(inputs) == 2


def test_explicit_native_crosswalk_does_not_guess_aliases_or_sessions():
    bill = {
        "bill_id": "explicit-ocd-id", "identifier": "HJ 1", "session_identifier": "2023",
        "state": "MD",
    }
    native = {
        "typed_key": ["2023RS", "lower", "HJ", 1],
        "literal_identifier": "HJ0001", "literal_session_key": "2023RS",
        "url": "literal-native-detail",
    }
    packet = MemoryPacket({
        "views.json": {"contexts": [{
            "canonical_bill_ids": ["explicit-ocd-id"], "typed_key": native["typed_key"],
        }]},
        "derived/selected.json": [native],
    })
    with patch(
        "state_politics.bills.study_partial_native._canonical_rows", return_value=[bill]
    ):
        record = _records(packet, "MD", {"contexts": "views.json", "canonical": "bills"})[0]
    assert record["identifier"] == "HJ 1"
    assert record["native_identifier"] == "HJ0001"
    assert record["session_identifier"] == "2023"
    assert record["native_session_identifier"] == "2023RS"
    assert record["canonical_bill_id"] == "explicit-ocd-id"


def test_manifest_binding_and_physical_jsonl_preserve_unicode_separators():
    manifest = {"files": {"pages.jsonl": {"sha256": "bound-hash", "bytes": 10}}}
    spec = {"manifest_sha256": "accepted-manifest", "manifest_members": "files"}

    def snapshot(path):
        return {
            "sha256": "accepted-manifest" if path.name == "manifest.json" else "bound-hash",
            "size": 10,
        }

    def contents(path, **kwargs):
        if path.name == "manifest.json":
            return json.dumps(manifest)
        return '{"text":"literal\u2028separator"}\n'

    with (
        patch("state_politics.bills.study_partial_native._snapshot", side_effect=snapshot),
        patch.object(Path, "read_text", contents),
    ):
        packet = FrozenPacket(Path("data/processed/unit-no-files-created"), spec)
        assert packet.read("pages.jsonl") == [{"text": "literal\u2028separator"}]
        assert packet.stable()["all_consumed_files_unchanged"]
        with pytest.raises(ValueError, match="unbound source member"):
            packet.pin("not-in-accepted-manifest.json")
        with pytest.raises(ValueError, match="ordinary packet member"):
            packet.pin("../outside.json")

    with patch("state_politics.bills.study_partial_native._snapshot", return_value={
        "sha256": "changed", "size": 10,
    }), pytest.raises(ValueError, match="unaccepted"):
        FrozenPacket(Path("data/processed/unit-no-files-created"), spec)


def test_native_date_observations_remain_raw_and_do_not_use_years_or_canonical_dates():
    row = {
        "introduction_events": [{"date": "2024-01-03", "source_span": {"exact_utf8": "action"}}],
        "native_introduction_action_rows": [{"printed_date": "02/12/2024"}],
        "printed_observations": {
            reader: {"introduced": {"literal": "Introduced and read first time: January 11, 2023"}}
            for reader in ("pymupdf", "pypdf")
        },
        "first_action_date": "unrelated canonical date",
        "printed_session_year": "2024",
        "pdf_url": "https://publisher.invalid/2023/document.pdf",
    }
    assert native_date_observations("MI", row) == []
    assert native_date_observations("KY", row)[0]["raw_value"] == "2024-01-03"
    assert native_date_observations("MN", row)[0]["raw_value"] == "02/12/2024"
    maryland = native_date_observations("MD", row)
    assert len(maryland) == 2
    assert maryland[0]["source_field"] == "printed_observations/pymupdf/introduced/literal"
    assert maryland[0]["raw_value"] == "Introduced and read first time: January 11, 2023"
    assert native_date_observations("KY", {"introduction_events": []}) == []


def test_state_output_retains_raw_date_columns_on_contexts_not_only_views():
    packet = MemoryPacket({})
    packet.stable = lambda: {"all_consumed_files_unchanged": True}
    record = context() | {
        "identifier": "HJR J", "native_identifier": "HJR J",
        "session_identifier": "2023-2024", "native_session_identifier": "2023-2024",
        "canonical_bill_id": "explicit-ocd-id",
        "source_record_locator": "0", "negative_flags": [],
    }
    spec = {
        "root": "accepted", "contexts": "records", "canonical": "canonical",
        "manifest_sha256": "frozen", "expected_contexts": 1, "expected_views": 1,
        "accepted_listed_identities": 20, "limitations": ["bounded selection"],
    }
    stored = {}

    def persist(frame, path, **kwargs):
        stored[str(path)] = frame.copy(deep=True)

    with (
        patch("state_politics.bills.study_partial_native.FrozenPacket", return_value=packet),
        patch("state_politics.bills.study_partial_native._records", return_value=[record]),
        patch("state_politics.bills.study_partial_native._reader_inputs", return_value=[source()]),
        patch("state_politics.bills.study_partial_native.sha256_file", return_value="table-hash"),
        patch.object(pd.DataFrame, "to_parquet", persist),
        patch.object(pd, "read_parquet", side_effect=lambda path: stored[str(path)]),
        patch.object(Path, "mkdir"),
        patch.object(Path, "stat", return_value=SimpleNamespace(st_size=10)),
        patch.object(Path, "write_text"),
    ):
        manifest = build_state(Path("data/processed"), Path("unit-output"), "MI", spec)
    contexts = stored["unit-output/context_inventory.parquet"]
    assert contexts.iloc[0]["identifier"] == "HJR J"
    assert contexts.iloc[0]["native_date_observations_json"] == "[]"
    assert contexts.iloc[0]["native_date_observation_status"] == (
        "no_unambiguous_stored_date_field_selected"
    )
    assert manifest["native_date_observations"]["n_contexts_with_observations"] == 0


def test_flat_kansas_manifest_is_checksum_bound_without_a_wrapper():
    member = {"derived/selected.json": {"sha256": "member", "size": 12}}
    spec = {"manifest_sha256": "manifest", "manifest_members": None}
    with (
        patch("state_politics.bills.study_partial_native._snapshot", side_effect=lambda path: {
            "sha256": "manifest" if path.name == "manifest.json" else "member", "size": 12,
        }),
        patch.object(Path, "read_text", return_value=json.dumps(member)),
    ):
        packet = FrozenPacket(Path("data/processed/unit-flat-manifest"), spec)
        assert packet.pin("derived/selected.json")["sha256"] == "member"
        assert packet.stable()["all_consumed_files_unchanged"]


def test_arizona_canonical_link_context_does_not_invent_a_native_listing_identity():
    bill = {
        "bill_id": "literal-bill-id", "state": "AZ", "identifier": "HB 2001",
        "session_identifier": "56th-1st-regular",
    }
    row = {
        "typed_key": ["HB", 2001, "lower", "56th-1st-regular"],
        "canonical_version": {"bill_id": bill["bill_id"]},
        "canonical_links": [{
            "bill_id": bill["bill_id"], "media_type": "application/pdf", "url": "literal-pdf",
        }],
        "substantive_original_retained": True,
    }
    packet = MemoryPacket({
        "recovery.json": [row], "canonical.json": {"bills": [bill]},
        "derived/selection.json": {"selected": [{
            "typed_key": row["typed_key"], "canonical_bill": bill, "native": None,
        }]},
    })
    record = _records(packet, "AZ", {
        "contexts": "recovery.json", "canonical": "canonical.json",
    })[0]
    assert record["canonical_bill_id"] == bill["bill_id"]
    assert record["context_id"] == "literal-pdf"
    assert record["native_identifier"] is None
    assert record["native_session_identifier"] is None
    assert "publisher_html_original_link_not_proven" in record["negative_flags"]
    assert native_date_observations("AZ", row) == []


def test_kansas_selected_absence_keeps_exact_gap_metadata_and_never_uses_canonical_dates():
    selected = [
        {"identifier": "SB 1", "formal_identifier_literal": "SB 1",
         "detail_path": "/literal/one/", "session_label": "2023-2024 Regular Sessions"},
        {"identifier": "SCR 1601", "formal_identifier_literal": "SCR 1601",
         "detail_path": "/literal/two/", "session_label": "2023-2024 Regular Sessions"},
    ]
    gap = {"identifier": "SCR 1601", "reason": "no PDF link; later texts not substituted"}
    packet = MemoryPacket({
        "selected.json": selected,
        "derived/introduced_contexts.json": [{"identifier": "SB 1"}],
        "derived/original_context_gaps.json": [gap],
        "derived/html_original_contexts.json": [],
        "canonical.jsonl": [
            {"bill_id": f"id-{i}", "identifier": row["identifier"], "state": "KS",
             "session_identifier": "2023-2024", "first_action_date": "2023-01-09"}
            for i, row in enumerate(selected)
        ],
    })
    records = _records(packet, "KS", {
        "contexts": "selected.json", "canonical": "canonical.jsonl",
    })
    assert records[1]["available"] is False
    assert json.loads(records[1]["source_linkage_metadata_json"])["gap"] == gap
    assert records[1]["native_session_identifier"] == "2023-2024 Regular Sessions"
    assert list(_reader_inputs(packet, "KS", {}, records[1])) == []
    assert native_date_observations("KS", records[0]["source_record"]) == []


def test_kansas_uses_whole_plain_reader_strings_and_complete_html_segments_not_journals():
    packet = MemoryPacket({
        "derived/pdf/087.json": {
            "fitz": {"pages": [{
                "number": 1, "text": "Be it enacted:\nwhole\u2028bill",
                "layout": "not the selected reader string",
            }]},
            "pypdf": {"pages": [{"number": 1, "text": "Be it enacted:\nother whole bill"}]},
        },
        "raw/087/result.json": {"body_sha256": None},
        "derived/document_html/110.json": {
            "segments": [{"text": "front matter\n"}, {"text": "Be it enacted:\nwhole bill"}],
            "text": "front matter\nBe it enacted:\nwhole bill",
        },
        "raw/110/result.json": {"body_sha256": None},
    })
    record = context() | {
        "negative_flags": [],
        "source_linkage_metadata_json": json.dumps({
            "original": {"original_exchange": 87, "original_url": "literal-original-pdf"},
            "html_originals": [{"exchange": 110, "url": "literal-original-html"}],
        }),
    }
    inputs = list(_reader_inputs(packet, "KS", {}, record))
    assert [item["reader"] for item in inputs] == ["pymupdf", "pypdf", "html_full_projection"]
    assert inputs[0]["source_reader"] == "fitz"
    assert inputs[0]["segments"] == ["Be it enacted:\nwhole\u2028bill"]
    assert inputs[2]["segments"] == ["front matter\n", "Be it enacted:\nwhole bill"]
    assert inputs[1]["extraction_selector"] == "pypdf/pages/*/text"


@pytest.mark.parametrize("defect", ["header-only", "missing-page", "explicit-truncation"])
def test_oregon_incomplete_view_is_an_explicit_negative_not_a_full_text_or_lost_context(defect):
    pages = [{"page": 1, "text": "Be it enacted:\nSECTION 1. Whole bill.\n"}]
    bad = [dict(pages[0])]
    if defect == "header-only":
        bad[0]["text"] = "82nd OREGON LEGISLATIVE ASSEMBLY--2023\nHouse Bill 2001\n"
    elif defect == "missing-page":
        bad = []
    else:
        bad[0]["truncated"] = True
    identity = {"session": "literal-session", "measure_type": "HB", "measure_number": 2001}
    packet = MemoryPacket({"derived/pdfs.json": [{
        "exchange": 63, "identity": identity, "version": "Introduced",
        "url": "literal-original", "body_sha256": None, "page_count": 1,
        "pages": {"pymupdf": bad, "pypdf": pages},
    }]})
    record = context() | {
        "negative_flags": [],
        "source_record": {
            "identity": identity,
            "proof": [{"pdf_exchange": 63, "link": {"url": "literal-original"}}],
        },
    }
    inputs = list(_reader_inputs(packet, "OR", {}, record))
    assert [item["reader"] for item in inputs] == ["pypdf"]
    assert record["available"] is True
    excluded = record["excluded_source_views"]
    assert len(excluded) == 1 and excluded[0]["reader"] == "pymupdf"
    assert excluded[0]["reason"] in record["negative_flags"]
    assert excluded[0]["extraction_path"] == "derived/pdfs.json"


def test_virginia_raw_offered_and_prefiled_dates_do_not_collapse_into_a_session_date():
    row = {"printed_observations": {
        "offered": {"raw": "Offered January 11, 2023", "groups": ["January 11, 2023"]},
        "prefiled": {"raw": "Prefiled July 18, 2022", "groups": ["July 18, 2022"]},
        "session": {"raw": "2023 SESSION"},
    }}
    observations = native_date_observations("VA", row)
    assert [item["raw_value"] for item in observations] == [
        "Offered January 11, 2023", "Prefiled July 18, 2022",
    ]
    assert [item["event_kind"] for item in observations] == ["offered", "prefiled"]


def test_zero_complete_stored_projections_remains_an_explicit_zero_view_state():
    packet = MemoryPacket({})
    packet.stable = lambda: {"all_consumed_files_unchanged": True}
    record = context(False) | {
        "identifier": "HB 1", "native_identifier": "HB1",
        "session_identifier": "literal-session", "native_session_identifier": "literal-native",
        "canonical_bill_id": "literal-ocd-id", "source_record_locator": "0",
        "negative_flags": ["stored_projection_header_only"],
    }
    spec = {
        "root": "accepted", "contexts": "records", "canonical": "canonical",
        "manifest_sha256": "frozen", "expected_contexts": 1, "expected_views": 0,
        "accepted_listed_identities": None, "limitations": ["bounded selection"],
    }
    stored = {}
    with (
        patch("state_politics.bills.study_partial_native.FrozenPacket", return_value=packet),
        patch("state_politics.bills.study_partial_native._records", return_value=[record]),
        patch("state_politics.bills.study_partial_native.sha256_file", return_value="table-hash"),
        patch.object(pd.DataFrame, "to_parquet",
                     lambda frame, path, **kwargs: stored.update({str(path): frame.copy()})),
        patch.object(pd, "read_parquet", side_effect=lambda path: stored[str(path)]),
        patch.object(Path, "mkdir"),
        patch.object(Path, "stat", return_value=SimpleNamespace(st_size=10)),
        patch.object(Path, "write_text"),
    ):
        manifest = build_state(Path("data/processed"), Path("unit-zero-output"), "AZ", spec)
    assert manifest["counts"]["n_contexts"] == 1
    assert manifest["counts"]["n_source_views"] == 0
    assert manifest["counts"]["n_contexts_with_views"] == 0
    contexts = stored["unit-zero-output/context_inventory.parquet"]
    assert not bool(contexts.iloc[0]["full_source_text_available"])
    assert contexts.iloc[0]["status"] == "selected_original_unavailable_retained_gap"

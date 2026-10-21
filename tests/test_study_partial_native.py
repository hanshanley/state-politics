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


@pytest.mark.parametrize("state", ["MI", "MD", "MN", "KY"])
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

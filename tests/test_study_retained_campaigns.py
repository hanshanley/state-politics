"""Stored campaigns retain complete strings and honest unavailability without extraction."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from state_politics.bills.study_retained_campaigns import (
    FALSE_FLAGS,
    VIEW_COLUMNS,
    StoredSources,
    _context,
    _digest,
    _mo_records,
    _mt_records,
    _native_records,
    _nm_records,
    _pa_records,
    _partial_reference_records,
    _tx_records,
    _ut_records,
    _wa_records,
    build_indexes,
    build_state,
    complete_projection,
    date_observations,
    explicit_source_statements,
    reconcile_tables,
    retain_source_date_observations,
)


def put(root: Path, name: str, value) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value if isinstance(value, bytes) else (
        json.dumps(value, ensure_ascii=False).encode("utf-8")
        if isinstance(value, (dict, list)) else value.encode("utf-8")
    )
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def jsonl(root, name, rows):
    return put(root, name, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def context(state="NY"):
    return _context(state, {"identifier": "A 255", "session_identifier": "literal-session"},
                    "literal-context", "records.jsonl")


def projection(sources, record, paths, digest, reader="pypdf", bindings=None):
    return complete_projection(
        sources, record, reader=reader, paths=paths, original="original.pdf",
        original_sha256=digest, source_url="literal-source-pointer", n_pages=2,
        source_kind="original_pdf", segment_bindings=bindings,
    )


def test_complete_file_and_separate_readers_preserve_utf8_bytes_crlf_and_every_page(tmp_path):
    digest = put(tmp_path, "original.pdf", b"opaque saved original; no PDF parser")
    texts = ["first\r\n\u2028second\f第三頁\n", "different\r\nentire alternative\fend\n"]
    for i, text in enumerate(texts):
        put(tmp_path, f"reader-{i}.txt", text)
    sources, record = StoredSources(tmp_path), context()
    views = pd.DataFrame([
        projection(sources, record, [f"reader-{i}.txt"], digest, reader)
        for i, reader in enumerate(("pymupdf", "pypdf"))
    ])
    contexts = pd.DataFrame([record | {
        "n_retained_views": 2, "status": "stored_complete_projection_unapproved",
    }])
    summary = reconcile_tables(contexts, views)
    assert summary["n_contexts_with_views"] == 1
    assert summary["n_source_views"] == 2
    for text, row in zip(texts, views.to_dict("records"), strict=True):
        assert row["text"].encode("utf-8") == text.encode("utf-8")
        assert row["input_sha256"] == _digest(text)
        assert row["n_input_utf8_bytes"] == len(text.encode("utf-8"))
    receipt = sources.finish(tmp_path / "fingerprints.parquet")
    assert receipt["all_consumed_source_sha256_and_stat_before_after_equal"]


@pytest.mark.parametrize("defect", ["missing-page", "wrong-page-hash", "wrong-original"])
def test_incomplete_page_stream_or_unbound_original_cannot_be_promoted(tmp_path, defect):
    digest = put(tmp_path, "original.pdf", b"saved PDF")
    put(tmp_path, "one.txt", "full first page\n")
    binding = {"page": 1, "characters": 16, "sha256": _digest("full first page\n")}
    binding["characters"] = len("full first page\n")
    bindings = [binding]
    if defect == "missing-page":
        bindings.append({"page": 2, "characters": 10, "sha256": _digest("other page")})
    elif defect == "wrong-page-hash":
        binding["sha256"] = "0" * 64
    else:
        digest = "0" * 64
    with pytest.raises(ValueError):
        projection(StoredSources(tmp_path), context(), ["one.txt"], digest, bindings=bindings)


def test_header_prefix_is_never_fabricated_into_a_missouri_full_view(tmp_path):
    jsonl(tmp_path, "prefix/unused.jsonl", [])
    put(tmp_path, "prefix/candidates/00001.json", {
        "identifier": "HB 1", "raw_context_id": "literal-mo-context",
        "route": {"url": "literal-original"}, "status": "success_collected",
        "document": {"printed_identity_observed": False, "first_page_text_prefix": "HEADER ONLY"},
    })
    [(record, views, header_only)] = list(_mo_records(StoredSources(tmp_path), "prefix"))
    assert views == []
    assert header_only
    assert record["native_identity_certified"] is False
    assert "original_printed_identity_flag_false" in json.loads(record["negative_flags_json"])


def test_illinois_complete_unverified_rendering_keeps_serialization_newline_not_shell(tmp_path):
    source_sha = put(tmp_path, "doc/raw.html", b"stored original source")
    text = "first block\nwhole bill [[INSERT:collector marker]]\nlast block"
    put(tmp_path, "doc/full_text.txt", text + "\n")
    put(tmp_path, "doc/document.json", {
        "identifier": "SB 1", "policy_text_available": True, "html_unavailable_shell": False,
        "identity_observation_pass": False, "raw_html_sha256": source_sha,
        "full_text_characters": len(text), "full_text_sha256": _digest(text),
    })
    put(tmp_path, "shell/document.json", {
        "identifier": "SB 2", "policy_text_available": False, "html_unavailable_shell": True,
    })
    put(tmp_path, "shell/full_text.txt", "publisher navigation header, NOT A BILL")
    jsonl(tmp_path, "mutable/population_dispositions.jsonl", [
        {"identifier": "SB 1", "population_index": 1, "state": "identity_unverified",
         "general_assembly": 103, "document_path": "doc"},
        {"identifier": "SB 2", "population_index": 2, "state": "html_unavailable_shell",
         "general_assembly": 103, "document_path": "shell"},
    ])
    sources = StoredSources(tmp_path)
    [(record, views, _), (_, shell_views, shell_only)] = list(_native_records(sources, "IL"))
    assert views[0]["text"] == text + "\n"
    assert record["original_identity_observation"] is False
    assert record["session_identifier"] is None
    assert record["native_session_identifier"] == "103"
    assert shell_views == []
    assert shell_only
    assert "shell/full_text.txt" not in sources.before


def test_new_york_keeps_complete_disagreeing_readers_and_anomaly_unapproved(tmp_path):
    original_sha = put(tmp_path, "doc/raw.pdf", b"opaque stored PDF")
    texts = {"pymupdf": "all page one\f全 second page\n", "pypdf": "different full pages\fend"}
    metadata = {"identifier": "A 255", "identity_header_pass": False,
                "raw_pdf_sha256": original_sha}
    for reader, text in texts.items():
        put(tmp_path, f"doc/full_text_{reader}.txt", text)
        metadata[f"{reader}_page_count"] = 2
        metadata[f"{reader}_character_count"] = len(text)
    put(tmp_path, "doc/document.json", metadata)
    jsonl(tmp_path, "mutable/population_dispositions.jsonl", [
        {"identifier": "A 255", "population_index": 1, "state": "unverified_header",
         "document_path": "doc"},
    ])
    proof = {"doc": {
        "completed": True, "identifier": "A 255", "raw_sha256": original_sha,
        "readers": {reader: {"saved_full_text_sha256": _digest(text)}
                    for reader, text in texts.items()},
    }}
    [(record, views, _)] = list(_native_records(StoredSources(tmp_path), "NY", proof))
    assert [view["text"] for view in views] == list(texts.values())
    assert record["original_identity_observation"] is False
    assert "A255_cancelled_then_started_lifecycle_anomaly" in record["negative_flags_json"]
    assert not any(views[0][name] for name in FALSE_FLAGS)
    proof["doc"]["readers"]["pypdf"]["saved_full_text_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="accepted complete-reader proof"):
        list(_native_records(StoredSources(tmp_path), "NY", proof))


def test_pa_incomplete_pair_still_preserves_every_complete_stored_format_and_markup(tmp_path):
    base = "prefix/documents/hb1"
    original_sha = put(tmp_path, f"{base}/raw/one.html", b"<html>whole stored source</html>")
    texts = ["first\r\n\u2028page\n", "最後 entire page\f\n"]
    pages = []
    for number, text in enumerate(texts, 1):
        path = f"reader_html/page-{number:04}.txt"
        pages.append({"page": number, "path": path, "characters": len(text),
                      "sha256": put(tmp_path, f"{base}/{path}", text)})
        put(tmp_path, f"{base}/parent_extracted_text/html-page-{number:04}.txt",
            text + " independent stored alternative")
    decoded = "<html>whole stored source</html>"
    put(tmp_path, f"{base}/reader_html/source-decoded.html", decoded)
    put(tmp_path, f"{base}/html_metadata.json", {
        "identifier": "HB 1", "source_sha256": original_sha, "stored_path": "raw/one.html",
        "pages": pages, "receipt": {"http_status": 200, "body_complete": True},
        "decoding": {"lossless_roundtrip_verified": True,
                     "decoded_source_path": "reader_html/source-decoded.html",
                     "decoded_utf8_sha256": _digest(decoded)},
    })
    jsonl(tmp_path, "prefix/source_plan.jsonl", [{
        "identifier": "HB 1", "native_id": "literal_native_id", "slug": "hb1",
        "action_history_json": '[{"date":"03/01/23","verb":"Referred to"}]',
    }])
    jsonl(tmp_path, "prefix/candidate_status.jsonl", [{"slug": "hb1", "state": "incomplete"}])
    [(record, views, _)] = list(_pa_records(StoredSources(tmp_path), "prefix"))
    assert record["source_status"] == "incomplete"
    assert [view["reader"] for view in views] == [
        "html_full_projection", "parent_html_stored_reader", "html_source_decoded",
    ]
    assert views[0]["text"] == "".join(texts)
    assert views[1]["text"] == "".join(text + " independent stored alternative" for text in texts)
    assert views[2]["text"] == decoded
    assert json.loads(views[0]["segment_character_counts_json"]) == list(map(len, texts))
    assert record["session_identifier"] is None
    assert "03/01/23" in record["native_date_observations_json"]


def test_date_fields_do_not_mistake_candidate_ordinals_or_url_years_for_dates():
    observed = date_observations({
        "candidate_ordinal": 4, "updated_at": "2026-10-21", "session_identifier": "2023",
        "url": "/2023/A255", "introduction_date": "literal 03/01/23",
        "action_history_json": '[{"date":""}]',
    })
    assert [row["source_field"] for row in observed] == [
        "introduction_date", "action_history_json",
    ]
    assert all(row["normalized"] is False for row in observed)


def test_literal_source_date_spans_never_borrow_a_generic_header_or_prior_line_date():
    text = (
        "STATE OF NEW YORK\nJanuary 4, 2023\nIntroduced by Senator Example\r\n"
        "The introduced version was discussed elsewhere.\n"
        "Introduced 10/26/2023, by Sen. Example\n"
        "Filed on March 3, 2024, by Example\n"
    )
    view = {
        "text": text, "view_id": "literal-view", "input_sha256": _digest(text),
        "source_kind": "original_pdf",
    }
    observations = explicit_source_statements(view)
    assert len(observations) == 3
    assert observations[0]["raw_dates_on_same_event_line"] == []
    assert [
        date["raw_value"] for row in observations for date in row["raw_dates_on_same_event_line"]
    ] == ["10/26/2023", "March 3, 2024"]
    for row in observations:
        assert text[row["span_start"]:row["span_end"]] == row["raw_value"]
        assert text.encode("utf-8")[row["utf8_byte_start"]:row["utf8_byte_end"]].decode() == (
            row["raw_value"]
        )
        assert row["used_as_window_evidence"] is False
    assert explicit_source_statements(view | {"source_kind": "original_html_markup"}) == []
    record = context()
    summary = retain_source_date_observations(record, [view])
    assert summary["literal_statement_spans_with_same_line_dates"] == 2
    assert json.loads(view["native_date_observations_json"]) == observations
    assert view["text"] == text
    assert "January 4, 2023" not in record["native_date_observations_json"]


def test_fingerprints_detect_source_mutation_and_reject_symlink_ancestors(tmp_path):
    put(tmp_path, "source.txt", "original")
    sources = StoredSources(tmp_path)
    sources.read("source.txt")
    put(tmp_path, "source.txt", "modified")
    with pytest.raises(ValueError, match="consumed source changed"):
        sources.finish(tmp_path / "fingerprints.parquet")
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        sources.path("alias/source.txt")
    with pytest.raises(ValueError, match="relative packet"):
        sources.path("../source.txt")


def test_frozen_manifest_binding_prevents_changed_projection_exports(tmp_path):
    original_sha = put(tmp_path, "source.txt", "original")
    manifest_sha = put(tmp_path, "manifest.json", {
        "files": {"source.txt": {"sha256": original_sha, "bytes": 8}},
    })
    sources = StoredSources(tmp_path)
    sources.manifest(manifest_sha)
    put(tmp_path, "source.txt", "modified")
    with pytest.raises(ValueError, match="unbound or changed"):
        sources.read("source.txt")


def test_all_unavailable_packet_is_persisted_honestly_and_existing_outputs_refused(tmp_path):
    data, proof = tmp_path / "data", tmp_path / "proof"
    root = data / "campaign"
    jsonl(root, "mutable/population_dispositions.jsonl", [
        {"identifier": "A 1", "population_index": 1, "state": "pending"},
        {"identifier": None, "population_index": 2, "state": "failure"},
    ])
    digest = put(proof, "accepted.json", {"status": "bounded reconstruction only"})
    spec = {"root": "campaign", "receipt": "accepted.json", "receipt_sha256": digest,
            "limitations": ["No complete stored projections available."]}
    output = tmp_path / "output"
    manifest = build_state(data, output, proof, "NY", spec)
    assert manifest["counts"]["n_unavailable_contexts"] == 2
    assert manifest["counts"]["n_source_views"] == 0
    assert list(pd.read_parquet(output / "source_view_inputs.parquet")) == VIEW_COLUMNS
    with pytest.raises(FileExistsError):
        build_indexes(data, output, proof)


@pytest.mark.parametrize("defect", ["truncation", "duplicate", "approval", "wrong-byte-count"])
def test_reconciliation_rejects_truncation_duplicates_or_silent_admission(tmp_path, defect):
    digest = put(tmp_path, "original.pdf", b"saved original")
    put(tmp_path, "text.txt", "complete first\fsecond頁\n")
    record = context()
    row = projection(StoredSources(tmp_path), record, ["text.txt"], digest)
    views = pd.DataFrame([row])
    contexts = pd.DataFrame([record | {
        "n_retained_views": 1, "status": "stored_complete_projection_unapproved",
    }])
    if defect == "truncation":
        views.loc[0, "text"] = views.loc[0, "text"][:-2]
    elif defect == "duplicate":
        views = pd.DataFrame([row, row | {"view_id": "different-id-same-reader"}])
    elif defect == "approval":
        contexts.loc[0, "model_admission"] = True
    else:
        views.loc[0, "n_input_utf8_bytes"] = row["n_input_characters"]
    with pytest.raises(ValueError):
        reconcile_tables(contexts, views)


def parquet(root, name, rows, columns=None):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_parquet(path, index=False)


def test_inline_complete_page_arrays_require_consumed_sources_and_keep_exact_segments(tmp_path):
    digest = put(tmp_path, "original.pdf", b"opaque original")
    segments = ["page one\r\n\u2028", "第二頁\fend\n"]
    put(tmp_path, "reader.json", {"pages": segments})
    sources = StoredSources(tmp_path)
    with pytest.raises(ValueError, match="consumed stored records"):
        complete_projection(
            sources, context(), reader="stored", paths=["reader.json"] * 2,
            stored_segments=segments, extraction_selector="pages JSON array",
            original="original.pdf", original_sha256=digest, source_url="literal",
            n_pages=2, source_kind="original_pdf",
        )
    sources.json("reader.json")
    view = complete_projection(
        sources, context(), reader="stored", paths=["reader.json"] * 2,
        stored_segments=segments, extraction_selector="pages JSON array",
        original="original.pdf", original_sha256=digest, source_url="literal",
        n_pages=2, source_kind="original_pdf",
    )
    assert view["text"] == "".join(segments)
    assert json.loads(view["segment_character_counts_json"]) == list(map(len, segments))
    assert view["extraction_selector"] == "pages JSON array"
    assert len(sources.before) == 2


def test_explicit_selection_does_not_build_or_read_any_legacy_packet(tmp_path, monkeypatch):
    from state_politics.bills import study_retained_campaigns as module

    called = []

    def build(data, out, proof, state, spec):
        called.append(state)
        out.mkdir()
        put(out, "manifest.json", {"state": state})
        return {"counts": {"n_source_views": 0}}

    monkeypatch.setattr(module, "build_state", build)
    result = build_indexes(tmp_path / "absent-data", tmp_path / "output",
                           tmp_path / "absent-proof", ["OK", "WV"])
    assert called == ["OK", "WV"]
    assert list(result["states"]) == called
    for selected in ([], ["TX", "TX"], ["unknown"]):
        with pytest.raises(ValueError, match="unique supported states"):
            build_indexes(tmp_path, tmp_path / "never-created", tmp_path, selected)


def test_washington_keeps_failures_missing_notes_and_cross_packet_version_alternatives(tmp_path):
    root, alternate, originals = [tmp_path / name for name in ("text", "alt", "originals")]
    original = put(root, "source_packet/source/one.pdf", b"saved PDF")
    text = "First reading January 4, 2023\nIntroduced by A\nall pages\fend"
    text_sha = put(root, "text/one.txt", text)
    base = {
        "bill_id": "literal-bill", "request_index": 1, "source_file": "source/one.pdf",
        "source_url": "literal-url", "source_version": {"date": "", "note": "Bill"},
        "reviewed_source_test_record": False, "retrieval_ok": True,
        "source_sha256": original, "document_scope_status": "unverified_document_scope",
        "text_file": "text/one.txt", "text_characters": len(text), "text_sha256": text_sha,
        "page_count": 2, "expected_identifier": "SR 8601", "expected_session": "2023-2024",
    }
    jsonl(root, "documents.jsonl", [
        base, base | {"request_index": 1, "retrieval_ok": False,
                      "reviewed_source_test_record": True, "text_file": None},
    ])
    put(root, "source_packet/plan.json", {
        "baseline_references": [{"bill_id": "missing", "identifier": "test record"}],
        "targets_without_original_links": ["missing"],
        "all_retained_version_rows": [{"bill_id": "missing", "date": "", "note": "later"}],
    })
    alt_sha = put(originals, "source/alternative.html", b"saved alternative HTML")
    alt_text = "complete plain-heading version\nfull policy"
    alt_text_sha = put(alternate, "0000.txt", alt_text)
    put(alternate, "review.json", {"version_review": [{
        "bill_id": "literal-alt", "source_url": "literal-alt-url",
        "source_file": "source/alternative.html", "source_sha256": alt_sha,
        "full_text_file": "0000.txt", "full_text_sha256": alt_text_sha,
        "source_note_review": "plain_heading_conflicts_with_substitute_note",
    }]})
    records = list(_wa_records({
        "text": StoredSources(root), "alternate": StoredSources(alternate),
        "originals": StoredSources(originals),
    }))
    assert [len(views) for _, views, _ in records] == [1, 0, 0, 1]
    assert len({record["context_id"] for record, _, _ in records}) == len(records)
    assert records[-1][1][0]["original_source_path"] == str(
        originals.resolve() / "source/alternative.html"
    )
    assert records[-1][1][0]["text"] == alt_text
    assert "version_conflict" in records[0][0]["negative_flags_json"]
    assert "First reading" not in records[0][0]["native_date_observations_json"]
    assert not any(records[-1][1][0][flag] for flag in FALSE_FLAGS)


def test_new_mexico_wrong_document_and_header_only_substitute_never_become_introduced(tmp_path):
    root, ocr = tmp_path / "review", tmp_path / "ocr"
    wrong_sha = put(root, "source_packet/capture/wrong.bin", b"wrong-session PDF")
    text_sha = put(root, "texts/wrong.txt", "whole wrong-session document")
    header_sha = put(root, "texts/header.txt", "heading only\f")
    source_sha = put(ocr, "source.pdf", b"committee substitute image PDF")
    rows = [{
        "identifier": "SB 6", "bill_id": "special-session-6", "link_id": "wrong",
        "session_identifier": "2024S1", "version_note_hint": "unclassified_note",
        "source_file": "capture/wrong.bin", "source_sha256": wrong_sha,
        "source_url": "literal-wrong-url", "text_file": "texts/wrong.txt",
        "text_sha256": text_sha, "text_method": "pdf_embedded",
        "pdf_pages": 1, "pdf_page_embedded_text_lengths": [27],
        "source_scope": "quarantined_byte_identical_regular_session_final",
    }, {
        "identifier": "HB 99", "bill_id": "substitute-99", "link_id": "substitute",
        "session_identifier": "2026", "version_note_hint": "unclassified_note",
        "source_file": "capture/header.bin", "source_sha256": source_sha,
        "source_url": "literal-substitute-url", "text_file": "texts/header.txt",
        "text_sha256": header_sha, "text_method": "pdf_embedded",
        "pdf_pages": 2, "pdf_page_embedded_text_lengths": [12, 0],
        "source_scope": "nonoriginal_note_requires_separate_native_context_review",
    }]
    parquet(root, "document_texts.parquet", rows)
    put(root, "cross_session_conflicts.json", [{
        "link_id": "wrong", "identical_pdf_sha256": wrong_sha,
        "baseline_session": "2024S1",
    }])
    segments = ["first whole page\r\n", "entire second page\n"]
    for number, segment in enumerate(segments, 1):
        put(ocr, f"pages/{number:03}.txt", segment)
    serialized = "PAGE 1\n" + segments[0] + "\fPAGE 2\n" + segments[1]
    put(ocr, "full_ocr_text.txt", serialized)
    put(ocr, "report.json", {
        "source_reference": {"link_id": "substitute"}, "n_pdf_pages": 2,
        "ocr_page_text_lengths": list(map(len, segments)),
    })
    records = list(_nm_records({"text": StoredSources(root), "ocr": StoredSources(ocr)}))
    assert records[0][1][0]["source_kind"] == "quarantined_cross_session_pdf"
    assert "never_exact_native_match" in records[0][0]["negative_flags_json"]
    assert [view["text"] for view in records[1][1]] == [serialized, "".join(segments)]
    assert "heading only" not in "".join(view["text"] for view in records[1][1])
    assert "heading only" in records[1][0]["partial_stored_projection_json"]
    assert all("not_introduced" in view["source_kind"] for view in records[1][1])


def test_montana_lc_aliases_and_native_nonmatches_stay_separate_and_unavailable(tmp_path):
    native, conflicts, history = [tmp_path / name for name in ("native", "conflicts", "history")]
    parquet(native, "native_bill_records.parquet", [
        {"native_record_index": 7, "native_source_json": '{"billNumber":1}'},
    ])
    parquet(native, "bill_reconciliation.parquet", [
        {"bill_id": "formal", "identifier": "HB 1", "source_identity_kind": "formal_measure",
         "matched_native_record_index": 7, "native_match_status": "unique_native_match"},
        {"bill_id": "draft", "identifier": "LC 1", "source_identity_kind": "draft_request",
         "matched_native_record_index": 7, "native_match_status": "unique_native_match"},
        {"bill_id": "unmatched", "identifier": "SR 55", "source_identity_kind": "formal_measure",
         "matched_native_record_index": None, "native_match_status": "no_native_match"},
    ])
    parquet(conflicts, "reader_physical_pages.parquet", [])
    parquet(conflicts, "document_observations.parquet", [])
    parquet(history, "reader_physical_pages.parquet", [])
    put(history, "volume_captures.json", [])
    records = list(_mt_records({
        "native": StoredSources(native), "conflicts": StoredSources(conflicts),
        "history": StoredSources(history),
    }))
    assert [record["identifier"] for record, _, _ in records] == ["HB 1", "LC 1", "SR 55"]
    assert len({record["context_id"] for record, _, _ in records}) == 3
    assert [record["identity_kind"] for record, _, _ in records][:2] == [
        "formal_measure", "draft_request",
    ]
    assert all(views == [] for _, views, _ in records)
    assert records[-1][0]["source_status"] == "no_native_match"


def test_utah_reconstructed_reader_alternatives_do_not_accept_collection(tmp_path):
    row = {
        "context_exchange": 1, "document_exchange": 2, "document_html_exchange": 3,
        "requested_identity": [2023, "HB", 1],
        "selected_original_link": {"url": "literal.pdf"},
        "introduced_group": {"html_link": {"url": "literal.htm"}},
    }
    put(tmp_path, "derived/recovered_contexts.json", [row])
    put(tmp_path, "derived/source_joins.json", [{
        "context_exchange": 1, "canonical_bill_ids": ["retained-canonical"],
    }])
    put(tmp_path, "derived/pdf_x0002.json", {
        "pymupdf_pages": ["first page\r\n", "second page"],
        "pypdf_pages": ["different first page", "different second page\n"],
    })
    put(tmp_path, "derived/html_x0003.json", {
        "full_text": "complete stored HTML body", "source": "<html>entire HTML source</html>",
    })
    pdf_sha = put(tmp_path, "transport/x0002.body", b"saved PDF")
    html_sha = put(tmp_path, "transport/x0003.body", b"saved HTML")
    sources = StoredSources(tmp_path)
    members = [
        {
            "path": path.relative_to(tmp_path).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in tmp_path.rglob("*") if path.is_file()
    ]
    manifest_sha = put(tmp_path, "manifest.json", {"members": members})
    sources.manifest(manifest_sha)
    [(record, views, _)] = list(_ut_records({"originals": sources}))
    assert len(views) == 4
    assert [view["text"] for view in views][:2] == [
        "first page\r\nsecond page", "different first pagedifferent second page\n",
    ]
    assert [view["original_source_sha256"] for view in views] == [
        pdf_sha, pdf_sha, html_sha, html_sha,
    ]
    assert record["canonical_bill_id"] == "retained-canonical"
    assert "collection_policy_acceptance_withheld" in record["negative_flags_json"]
    assert all(view["collection_policy_accepted"] is False for view in views)


@pytest.mark.parametrize("state", ["OK", "WV"])
def test_partial_reference_keeps_every_character_and_literal_date_but_exports_zero_views(
    tmp_path, state,
):
    partial = "[Introduced August 6, 2023]\ncomplete main document; remaining DOCX parts unknown"
    text_sha = put(tmp_path, "partial.txt", partial)
    source_sha = put(tmp_path, "source_packet/source/original.bin", b"saved original")
    put(tmp_path, "review.json", {"source_scope_review": [{
        "state": state, "bill_id": "retained-id", "link_id": "retained-link",
        "text_file": "partial.txt", "text_sha256": text_sha,
        "text_method": "docx_main_document_only" if state == "WV" else "pdf_all_pages",
        "original_source_receipt": {
            "source_file": "source/original.bin", "content_sha256": source_sha,
        },
    }]})
    [(record, views, partial_only)] = list(_partial_reference_records(
        {"review": StoredSources(tmp_path)}, state,
    ))
    retain_source_date_observations(record, views)
    assert views == []
    assert partial_only
    assert json.loads(record["partial_stored_projection_json"])["text"] == partial
    observation = json.loads(record["native_date_observations_json"])[0]
    assert observation["raw_dates_on_same_event_line"][0]["raw_value"] == "August 6, 2023"
    assert observation["source_field"] == "partial_stored_projection_json.text"
    assert observation["source_view_id"] is None
    assert observation["used_as_window_evidence"] is False


def test_texas_shell_and_pending_sources_are_not_promoted_by_file_presence(tmp_path, monkeypatch):
    from state_politics.bills import study_retained_campaigns as module

    campaign, body, initial = [tmp_path / name for name in ("campaign", "body", "initial")]
    pins = {
        "mutable/population_dispositions.jsonl": jsonl(
            campaign, "mutable/population_dispositions.jsonl", [
                {"identifier": "HB 1", "state": "unverified_header",
                 "document_path": "mutable/documents/HB1"},
                {"identifier": "HB 2", "state": "pending", "document_path": None},
            ],
        ),
        "mutable/progress.json": put(
            campaign, "mutable/progress.json", {"official_filed_population": 2},
        ),
        "contract/complete_accounted_population.jsonl": jsonl(
            campaign, "contract/complete_accounted_population.jsonl", [{
                "identifier": "SB 15247", "bill_id": None,
            }],
        ),
    }
    monkeypatch.setattr(module, "TX_SOURCE_PINS", pins)
    put(campaign, "mutable/documents/HB1/document.json", {"identifier": "HB 1"})
    put(campaign, "mutable/documents/HB1/full_source_text.txt", "unavailable shell not policy")
    jsonl(body, "candidate_inputs.jsonl", [{
        "identifier": "HB 1", "classifier_input_available": False, "body_text": "shell body",
        "body_text_sha256": _digest("shell body"),
    }])
    parquet(initial, "document_recovery.parquet", [])
    parquet(initial, "document_pages.parquet", [])
    stored = StoredSources(campaign)
    records = list(_tx_records({
        "campaign": stored, "body": StoredSources(body), "initial": StoredSources(initial),
    }))
    assert [len(views) for _, views, _ in records] == [0, 0, 0]
    assert records[0][2] is True
    assert "HB1_HTML_shell_PDF_unfetched" in records[0][0]["negative_flags_json"]
    assert "full_source_text.txt" not in "".join(stored.before)
    assert "shell body" in records[0][0]["partial_stored_projection_json"]
    assert "canonical_only_unmatched" in records[-1][0]["negative_flags_json"]


@pytest.mark.parametrize("tamper", [False, True])
def test_partial_build_reuses_only_hash_checked_outputs_without_source_reads(
    tmp_path, monkeypatch, tamper,
):
    from state_politics.bills import study_retained_campaigns as module

    data, output = tmp_path / "absent-data", tmp_path / "partial-output"
    state_output = output / "TX"
    digest = put(state_output, "opaque.parquet", b"retained output bytes, not loaded as rows")
    manifest = {
        "state": "TX", "profile": "views", "full_campaign_closure": False, **FALSE_FLAGS,
        "source_packet_root": str((data / module.PROFILES["TX"]["root"]).resolve()),
        "counts": {"n_source_views": 5},
        "files": {"opaque.parquet": {
            "sha256": digest, "bytes": (state_output / "opaque.parquet").stat().st_size,
        }},
    }
    put(state_output, "manifest.json", manifest)
    monkeypatch.setattr(module, "build_state", lambda *args: pytest.fail("source reread"))
    if tamper:
        put(state_output, "opaque.parquet", b"changed retained output")
        with pytest.raises(ValueError, match="reused output member changed"):
            build_indexes(data, output, tmp_path / "absent-proof", ["TX"], ["TX"])
        assert not (output / "manifest.json").exists()
    else:
        result = build_indexes(data, output, tmp_path / "absent-proof", ["TX"], ["TX"])
        assert result["reused_existing_states_without_source_renormalization"] == ["TX"]
        assert result["states"]["TX"] == manifest["counts"]
        with pytest.raises(FileExistsError, match="completed output"):
            build_indexes(data, output, tmp_path / "absent-proof", ["TX"], ["TX"])

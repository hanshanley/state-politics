"""Sealed collection membership, full reader alternatives, negatives and replay."""

from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pymupdf
import pytest

from state_politics.bills import nj_library_collection as nj

old = nj.legacy


@pytest.fixture
def work():
    directory = Path.cwd() / ".pytest_cache" / "nj-library-collection" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def _cover(kind="ASSEMBLY", number=100):
    return (
        f"{kind}, No. {number}\nSTATE OF NEW JERSEY\n220th LEGISLATURE\n"
        "INTRODUCED MAY 8, 2023\nSponsored by:\nMember é\nSYNOPSIS\nPolicy.\n"
        "CURRENT VERSION OF TEXT\nAs introduced.\n"
    )


def _pages():
    return [
        "An unresolved original attachment, not an own bill identity.\n",
        "LEGISLATIVE HISTORY CHECKLIST\nA100 and S200 are referenced here.\n",
        "EXPLANATION - Matter underlined is new matter.\n"
        "P.L. 2023, CHAPTER 1, approved May 9, 2023\nAssembly, No. 100 (First Reprint)\n"
        "AN ACT concerning testing.\nBE IT ENACTED by the State\nof New Jersey:\nPolicy é.\n",
        "A100 [1R]\n2\n2. This act shall take effect immediately.\nEnacted ending é.\n",
        _cover(),
        "A100 MEMBER\n2\nAN ACT concerning testing.\n"
        "BE IT ENACTED by the State of New Jersey:\n"
        "2. This act shall take effect immediately.\nSTATEMENT\nStatement begins\n",
        "A100 MEMBER\n3\nFinal complete statement paragraph é.\n",
        "Office of Legislative Services\nFISCAL ESTIMATE\nAncillary, not policy.\n",
        _cover("SENATE", 200),
        "S200 OTHER\n2\nAN ACT concerning an unmatched bill.\n"
        "BE IT ENACTED by the State of New Jersey:\n"
        "2. This act shall take effect immediately.\nSTATEMENT\nFull unmatched bill.\n",
        "COMMITTEE\nSTATEMENT TO\nASSEMBLY, No. 100\nAncillary not policy.\n",
    ]


def _pdf(texts):
    with pymupdf.open() as pdf:
        for text in texts:
            page = pdf.new_page()
            if text:
                page.insert_text((40, 40), text, fontsize=10)
        return pdf.tobytes()


def _capture(source, number, label, url, content, *, robots=False):
    stem = f"raw/{number:04d}-{label}"
    (source / "raw").mkdir(exist_ok=True)
    (source / (stem + ".body")).write_bytes(content)
    (source / (stem + ".headers")).write_bytes(b"HTTP/2 200\r\ncontent-type: test\r\n\r\n")
    old._write(source / (stem + ".transport.json"), {
        "url": url, "url_effective": url, "http_code": 200, "response_code": 200,
        "exitcode": 0, "num_redirects": 0, "method": "GET", "size_download": len(content),
    })
    (source / (stem + ".stderr")).write_bytes(b"")
    return {
        "ordinal": number, "label": label, "url": url, "host": "repo.njstatelib.org",
        "body": stem + ".body", "headers": stem + ".headers",
        "transport": stem + ".transport.json", "stderr": stem + ".stderr",
        "body_sha256": old._sha(content), "body_bytes": len(content), "status": 200,
        "curl_returncode": 0, "access_stop": False, "automatic_retries": False,
        "automatic_redirects": False, "is_robots": robots,
        "original_capture_metadata": {"nullable": None, "literal": "é"},
    }


def _seal(source, status="immutable_first16_subset"):
    manifest = {
        "status": status,
        "artifacts": {
            p.relative_to(source).as_posix(): old._binding(p)
            for p in sorted(source.rglob("*")) if p.is_file() and p != source / "manifest.json"
        },
    }
    if status == "closed_complete_collection_capture":
        manifest.update(network_closed=True, model_input_approved=False,
                        scientific_approval=False, publication=False)
    old._write(source / "manifest.json", manifest)
    return old._binding(source / "manifest.json")["sha256"]


def _source(work, *, texts=None, status="immutable_first16_subset", duplicate_bytes=False):
    source = work / "source"
    source.mkdir()
    queue = work / "queue.parquet"
    original = {
        "bill_id": "ocd-bill/100", "state": "NJ", "session_identifier": "220",
        "identifier": "A 100", "title": "Original é",
        "source_introduction_date": None, "source_filing_date": "",
        "session_start_date": None, "session_end_date": None,
        "origin_filing_action_ids": ["literal-original-ID"],
        "original_nested": {"values": ["é", None]},
        "model_input_approved": False, "filing_time_text_certified": False,
        "analytical_admission": False, "neither_source_observed": True,
    }
    originals = [
        original,
        {**original, "bill_id": "ocd-bill/221", "session_identifier": "221"},
        {**original, "bill_id": "ocd-bill/unknown", "identifier": "AR 10"},
        {**original, "bill_id": "ocd-bill/outside", "state": "HI"},
        {**original, "bill_id": "ocd-bill/absent", "identifier": "S 999"},
    ]
    pq.write_table(pa.Table.from_pylist(originals), queue)
    shutil.copy2(queue, source / "input-gap-queue.parquet")
    robots = _capture(source, 1, "robots", "https://repo.njstatelib.org/robots.txt",
                      b"User-agent: *\nDisallow: /admin\n", robots=True)
    entries, items, captures = [], [], [robots]
    examples = [texts or _pages(), ["Unknown original page.\n", "Full ending.\n"]]
    previous_content = None
    for index, page_texts in enumerate(examples):
        item_id, stream_id = f"item-{index}", f"stream-{index}"
        item = {
            "id": item_id, "uuid": item_id, "type": "item",
            "inArchive": True, "discoverable": True, "withdrawn": False,
            "metadata": {
                "dc.description.abstract": [{"value": f"Year: 2023, Chapter: {index + 1}"}],
            },
        }
        if duplicate_bytes and index:
            content = previous_content
            page_texts = examples[0]
        else:
            content = _pdf(page_texts)
        previous_content = content
        pdf_url = f"https://repo.njstatelib.org/server/api/core/bitstreams/{stream_id}/content"
        bitstream = {
            "id": stream_id, "uuid": stream_id, "type": "bitstream", "bundleName": "ORIGINAL",
            "sizeBytes": len(content), "_links": {"content": {"href": pdf_url}},
        }
        angular = {
            "id": item_id, "uuid": item_id, "type": "item", "metadata": item["metadata"],
            "isArchived": True, "isDiscoverable": True, "isWithdrawn": False,
        }
        state = json.dumps({"cache": [angular, bitstream]}, ensure_ascii=False)
        for token, literal in (("a", "&"), ("q", '"'), ("s", "'"), ("l", "<"), ("g", ">")):
            state = state.replace(literal, f"&{token};")
        html = '<script id="dspace-angular-state" type="application/json">' + state + "</script>"
        item_capture = _capture(source, 3 + index * 2, f"item-{index}",
                                "https://repo.njstatelib.org/items/" + item_id, html.encode())
        pdf_capture = _capture(source, 4 + index * 2, f"pdf-{index}", pdf_url, content)
        captures.extend([item_capture, pdf_capture])
        items.append(item)
        entries.append({
            "catalog_item": item, "item_capture": item_capture, "capture": pdf_capture,
            "pdf": pdf_capture["body"], "pdf_sha256": pdf_capture["body_sha256"],
            "n_pages": len(page_texts), "bitstream_record": bitstream,
        })
    url = "https://repo.njstatelib.org/server/api/discover/search/objects?dsoType=ITEM&scope=collection"
    catalogue = _capture(source, 2, "catalogue", url, json.dumps({
        "scope": "collection", "_embedded": {"searchResult": {
            "page": {"number": 0, "size": 20, "totalPages": 1, "totalElements": len(items)},
            "_links": {}, "_embedded": {
                "objects": [{"_embedded": {"indexableObject": i}} for i in items],
            },
        }},
    }).encode())
    captures.insert(1, catalogue)
    old._write(source / "request-ledger.snapshot.json", captures)
    old._write(source / "source-batch.json", {
        "status": nj.SOURCE_STATUSES[status], "collection": "collection",
        "catalog_items": items, "catalog_captures": [catalogue], "new_pdfs": entries,
        "reused_pdfs": [], "all_source_approvals": False, "publication": False,
        "network_closed": True,
    })
    old._write(source / "scope.json", {
        "all_state_publishers_remain_closed": True, "old_packets_immutable": True,
        "scientific_approval": False, "model_input_approved": False, "publication": False,
        "original_queue": {"path": str(queue), **old._binding(queue)},
        "inherited_exchange": {"raw_response_retained": False, "response_body_sha256": None},
    })
    return source, queue, _seal(source, status), originals


@pytest.mark.parametrize("context_schema", [
    nj.CONTEXT_SCHEMA, nj.CONTEXT_ALL_DATES_SCHEMA, nj.CONTEXT_SINGLE_PAGE_SCHEMA,
    nj.CONTEXT_PRINTED_VARIANTS_SCHEMA,
])
def test_context_evidence_recovers_tail_and_preserves_exact_original_subset(
    work, monkeypatch, context_schema,
):
    texts = [
        text.replace("MAY 8, 2023", "JANUARY 4, 2024").replace(
            "approved May 9, 2023", "approved January 16, 2024",
        ) for text in _pages()
    ]
    if context_schema in {nj.CONTEXT_SINGLE_PAGE_SCHEMA, nj.CONTEXT_PRINTED_VARIANTS_SCHEMA}:
        texts[2] += "2. This act shall take effect immediately.\nComplete final policy.\n"
        del texts[3]
    if context_schema == nj.CONTEXT_PRINTED_VARIANTS_SCHEMA:
        texts[2] = texts[2].replace("No. 100 (First", "No, 100 (Fifth")
        texts[3] = "[First Reprint]\n" + texts[3].replace(
            "As introduced.", "As reported with amendments.",
        )
        texts[4] = texts[4].replace("A100 MEMBER", "A100 [1R]")
        texts[5] = texts[5].replace("A100 MEMBER", "A100 [1R]")
    source, queue, _, originals = _source(work, texts=texts)
    original = {
        **originals[0], "session_end_date": "2023-12-31",
        "source_introduction_date": "2024-01-04",
        "from_organization_id": "ocd-organization/lower", "originating_chamber": "lower",
        "n_origin_introduction_actions": "1", "origin_introduction_action_ids": '["actual-A"]',
    }
    originals[0] = original
    table = pa.Table.from_pylist(originals)
    pq.write_table(table, queue)
    shutil.copyfile(queue, source / "input-gap-queue.parquet")
    scope = old._json(source / "scope.json")
    scope["original_queue"] = {"path": str(queue), **old._binding(queue)}
    old._write(source / "scope.json", scope)
    source_sha = _seal(source)
    subset = work / "current-original-subset.parquet"
    pq.write_table(table.slice(0, 1), subset)
    evidence = work / "context-inputs"
    evidence.mkdir()
    upper = {
        **original, "bill_id": "ocd-bill/200", "identifier": "S 200",
        "from_organization_id": "ocd-organization/upper", "originating_chamber": "upper",
        "origin_introduction_action_ids": '["actual-S"]',
    }
    old._write_rows(evidence / "contexts.jsonl", [original, upper])
    actions = [{
        "action_id": action_id, "bill_id": row["bill_id"], "state": "NJ",
        "date": "2024-01-04T05:00:00+00:00", "description": "Introduced",
        "classification": "introduction|referral-committee",
        "organization_id": row["from_organization_id"], "chamber": row["originating_chamber"],
    } for row, action_id in [(original, "actual-A"), (upper, "actual-S")]]
    pq.write_table(pa.Table.from_pylist(actions), evidence / "bill_actions.parquet")
    old._write(evidence / "bill_extraction_manifest.json", {
        "status": "complete_extraction_not_source_certification",
        "scientific_certification": "not_performed", "artifacts": {
            "bill_actions.parquet": {
                **old._binding(evidence / "bill_actions.parquet"), "rows": 2,
            },
        },
    })
    monkeypatch.setattr(nj, "ORIGINAL_CONTEXTS_SHA256",
                        old._binding(evidence / "contexts.jsonl")["sha256"])
    monkeypatch.setattr(nj, "ORIGINAL_EXTRACTION_SHA256",
                        old._binding(evidence / "bill_extraction_manifest.json")["sha256"])
    old._write(evidence / "manifest.json", {
        "schema": context_schema, "artifacts": {
            name: old._binding(evidence / name) for name in (
                "contexts.jsonl", "bill_actions.parquet", "bill_extraction_manifest.json",
            )
        },
    })
    evidence_sha = old._binding(evidence / "manifest.json")["sha256"]
    out = work / "tail-packet"
    nj.build_nj_collection(
        source, subset, out, source_manifest_sha256=source_sha,
        gap_queue_sha256=old._binding(subset)["sha256"],
        context_evidence=evidence, context_evidence_sha256=evidence_sha,
    )
    views, contexts, _, manifest = nj.load_nj_collection(
        out, context_evidence_sha256=evidence_sha,
    )
    assert contexts == [original]
    count_name = ("context_qualified_tail_views" if context_schema == nj.CONTEXT_SCHEMA
                  else "context_qualified_original_date_views")
    assert len(views) == manifest["counts"][count_name] == 4
    if context_schema in {nj.CONTEXT_SINGLE_PAGE_SCHEMA, nj.CONTEXT_PRINTED_VARIANTS_SCHEMA}:
        assert manifest["counts"]["accepted_complete_single_page_views"] == 2
        assert sum(view["source_version"].get("complete_single_page_policy_version", False)
                   for view in views) == 2
    if context_schema == nj.CONTEXT_PRINTED_VARIANTS_SCHEMA:
        assert sum(view["source_version"].get("printed_cover_reprint") == "First"
                   for view in views) == 2
    assert all(view["source_version"]["original_context_introduction_proof"]
               ["original_context"]["session_end_date"] == "2023-12-31" for view in views)
    assert all(view["source_version"]["original_context_introduction_proof"]
               ["original_origin_introduction_actions"][0]["date"]
               == "2024-01-04T05:00:00+00:00" for view in views)
    assert pq.read_metadata(out / "context-evidence/bill_actions.parquet").num_rows == 2
    with pytest.raises(ValueError, match="external context"):
        nj.load_nj_collection(out, context_evidence_sha256="0" * 64)
    changed = work / "changed-subset.parquet"
    pq.write_table(pa.Table.from_pylist([{**original, "session_end_date": "2024-01-08"}]), changed)
    with pytest.raises(ValueError, match="whole-row subset"):
        nj.build_nj_collection(
            source, changed, work / "rejected", source_manifest_sha256=source_sha,
            gap_queue_sha256=old._binding(changed)["sha256"],
            context_evidence=evidence, context_evidence_sha256=evidence_sha,
        )
    assert not (work / "rejected").exists()


def _full_source(work):
    source, queue, _, originals = _source(work)
    batch = old._json(source / "source-batch.json")
    ledger = old._json(source / "request-ledger.snapshot.json")
    by_ordinal = {c["ordinal"]: c for c in ledger}
    old_pdf = by_ordinal[6]
    current = [c for c in ledger if c["ordinal"] != 6]
    for index, capture in enumerate(current):
        capture["start_monotonic"] = 10 + index * 2.3
        transport = old._json(source / capture["transport"])
        transport["ssl_verify_result"] = 0
        old._write(source / capture["transport"], transport)
    for entry in batch["new_pdfs"]:
        for field in ("capture", "item_capture"):
            entry[field] = by_ordinal[entry[field]["ordinal"]]
    batch["catalog_captures"] = [by_ordinal[c["ordinal"]] for c in batch["catalog_captures"]]
    nested = source / "sealed-first16"
    nested.mkdir()
    subset = {**batch, "new_pdfs": batch["new_pdfs"][:1]}
    selected = [c for c in current if c["ordinal"] != 5]
    for name in ("scope.json", "input-gap-queue.parquet"):
        shutil.copy2(source / name, nested / name)
    for capture in selected:
        for name in old._capture_files(capture):
            old._copy(source / name, nested / name)
    old._write(nested / "source-batch.json", subset)
    old._write(nested / "request-ledger.snapshot.json", selected)
    _seal(nested)
    reused = batch["new_pdfs"].pop()
    original = {k: reused[k] for k in ("capture", "pdf", "pdf_sha256", "n_pages")}
    batch["reused_pdfs"] = [{
        "catalog_item": reused["catalog_item"], "item_capture": reused["item_capture"],
        "bitstream_record": reused["bitstream_record"], "original_entry": original,
    }]
    prefix = [old_pdf]
    old._write(source / "seed-source-batch-all8.json", {"pdfs": [original]})
    old._write_rows(source / "seed-request-ledger.jsonl", prefix)
    old._write_rows(source / "request-ledger.jsonl", prefix + current)
    (source / "request-ledger.snapshot.json").unlink()
    scope = old._json(source / "scope.json")
    scope.update(known_inherited_physical_exchanges=2, maximum_new_physical_requests=500,
                 minimum_start_spacing_seconds=2.2)
    old._write(source / "scope.json", scope)
    batch.update(status="closed_complete_collection_capture",
                 new_physical_requests=len(current),
                 known_aggregate_physical_exchanges=len(current) + 2)
    old._write(source / "source-batch.json", batch)
    producer = source / "producer"
    producer.mkdir()
    failed = producer / "capture_nj_library_collection_20261023_failed_v1.py"
    corrected = producer / "capture_nj_library_collection_20261023_v1.py"
    failed.write_text("retained historical collector\n")
    corrected.write_text("retained guard-only collector\n")
    old._write(source / "failure.json", {
        "status": "stopped_incomplete_collection", "error": "'isArchived'",
        "new_physical_requests": 2, "network_closed": True,
    })
    old._write(source / "schema-v2-continuation.json", {
        "previous_failure_preserved": True, "access_stops_retried_or_bypassed": False,
        "original_new_request_ceiling": 500, "retained_responses_reused_without_refetch": 2,
        "new_requests_already_consumed": 2, "remaining_new_request_allowance": 498,
        "previous_source": old._binding(failed), "corrected_source": old._binding(corrected),
    })
    old._write(source / "capture-completion-report.json", {
        "catalog_items": 2, "catalog_pages": 1, "new_pdfs": 1,
        "exact_original_URL_reused_pdfs": 1,
        "all_current_published_ORIGINAL_bitstream_sizes_verified": 2,
        "new_physical_pdf_pages": len(_pages()),
        "new_complete_pdf_bytes": batch["new_pdfs"][0]["capture"]["body_bytes"],
        "new_physical_requests": len(current), "original_new_request_ceiling": 500,
        "known_aggregate_physical_exchanges": len(current) + 2,
        "encoder_or_training_calls": 0, "model_input_approved": False,
        "scientific_approval": False, "publication": False,
    })
    return source, queue, _seal(source, "closed_complete_collection_capture"), originals


def _build(source, queue, out, source_sha):
    return nj.build_nj_collection(
        source, queue, out, source_manifest_sha256=source_sha,
        gap_queue_sha256=old._binding(queue)["sha256"],
    )


@pytest.fixture
def packet(work):
    source, queue, source_sha, originals = _source(work)
    out = work / "normalized"
    _build(source, queue, out, source_sha)
    return out, source, queue, source_sha, originals


def _rebind(out, name):
    manifest = old._json(out / "manifest.json")
    manifest["packet_artifacts"][name] = old._binding(out / name)
    old._write(out / "manifest.json", manifest)


@pytest.mark.parametrize("name", [
    "producer/nj_library_collection.py", "producer/nj_library_text.py",
])
def test_exact_format_compatible_dependency_never_waives_payload_replay(packet, monkeypatch, name):
    out = packet[0]
    path = out / name
    path.write_bytes(path.read_bytes() + b"\n# prior synthetic formatting-only producer\n")
    aliases = dict(getattr(nj, "FORMATTING_COMPATIBLE_PRODUCERS", {}))
    aliases[name] = (old._binding(path),)
    monkeypatch.setattr(nj, "FORMATTING_COMPATIBLE_PRODUCERS", aliases, raising=False)
    _rebind(out, name)
    rows, _, _, _ = nj.load_nj_collection(out)
    assert rows
    rows[0]["text"] = rows[0]["text"][:-1]
    old._write_rows(out / "views.jsonl", rows)
    _rebind(out, "views.jsonl")
    with pytest.raises(ValueError, match="replay"):
        nj.load_nj_collection(out)


def test_full_reader_alternatives_ancillaries_unknowns_original_fields_and_queue_accounting(packet):
    out, source, queue, source_sha, originals = packet
    views, contexts, pins, manifest = nj.load_nj_collection(
        out, originals, source_manifest_sha256=source_sha,
        gap_queue_sha256=old._binding(queue)["sha256"],
    )
    assert len(views) == 4 and contexts == originals[:1]
    assert len({v["view_id"] for v in views}) == len(views)
    assert all(v["view_id"].startswith("nj-library-collection:") for v in views)
    assert manifest["counts"]["newly_covered_contexts"] == 1
    assert manifest["counts"]["original_gap_contexts"] == len(originals)
    assert manifest["counts"]["versions_without_queue_candidate"] == 2
    assert len(pins) == len(manifest["packet_artifacts"]) + 1
    pages = old._jsonl(out / "pages.jsonl")
    assert len(pages) == (len(_pages()) + 2) * 2
    assert all(p.get("layout_text") is not None for p in pages if p["reader"] == "pypdf")
    assert all(p.get("text_layout") for p in pages if p["reader"] == "pymupdf")
    for view in views:
        selected = [p for p in pages if p["reader"] == view["reader"]
                    and p["source_id"] == "pdf-0"
                    and p["page_ordinal"] in view["source_version"]["page_ordinals"]]
        assert view["text"] == "\n".join(p["text"] for p in selected)
        assert view["text_binding"] == old._text_binding(view["text"])
        assert "Ancillary" not in view["text"] and "unresolved" not in view["text"]
        assert all(view[flag] is False for flag in nj.FLAGS)
        assert view["source_record"]["original_queue_row"] == originals[0]
        if view["source_version"]["kind"] == "bill_cover":
            assert "Final complete statement paragraph" in view["text"]
        else:
            witnesses = [s for s in view["source_identity"]["printed_evidence"]
                         if not s["in_policy_text"]]
            assert len(witnesses) == 3 and all(s["page_ordinal"] == 5 for s in witnesses)
            assert "CURRENT VERSION OF TEXT" not in view["text"]
    dispositions = old._jsonl(out / "page_dispositions.jsonl")
    assert len(dispositions) == len(pages)
    assert any(d["disposition"] == "quarantined_unresolved_page" for d in dispositions)
    assert any(d["disposition"] == "fiscal_estimate" for d in dispositions)
    assert all(d["text_preserved_in_full"] for d in dispositions)
    queue_rows = old._jsonl(out / "queue_dispositions.jsonl")
    assert [r["original_queue_row"] for r in queue_rows] == originals
    assert sum(r["newly_covered"] for r in queue_rows) == 1
    assert [r["original_row_ordinal"] for r in queue_rows] == list(range(len(originals)))
    assert any(r["disposition"] == "no_accepted_candidate_in_selected_source_packet"
               for r in queue_rows)
    receipt = old._json(out / "consumed_input_hashes.json")
    assert receipt["before"] == receipt["after"]
    assert all(
        old._binding(source / name) == binding for name, binding in receipt["before"].items()
    )


def test_no_generated_prologue_inference_entry(packet):
    from state_politics.analysis.cycle_topics import input_text, make_input

    views, _, _, _ = nj.load_nj_collection(packet[0])
    for ordinal, view in enumerate(views, 1):
        unit = make_input(view, "retained_text", "evidence/archive-NJ.jsonl", ordinal)
        assert view["archive_generated_prologue_preserved"] is False
        assert unit["source_text_span"] == [0, len(view["text"])]
        assert input_text(unit) == view["text"]
        assert unit["input_sha256"] == view["raw_text_sha256"]


@pytest.mark.parametrize("change", [
    "text", "identity", "report", "false_flag", "prologue", "layout", "page_disposition",
    "queue_disposition", "producer", "context",
])
def test_repinned_normalized_tampering_still_fails_independent_replay(packet, change):
    out = packet[0]
    if change == "report":
        name = "report.json"
        data = old._json(out / name)
        data["limits"]["no_filing_date_or_alias_inference"] = False
        old._write(out / name, data)
    elif change == "producer":
        name = "producer/nj_library_text.py"
        (out / name).write_bytes((out / name).read_bytes() + b"\n# changed\n")
    elif change == "context":
        name = "context_inventory.parquet"
        table = pq.read_table(out / name)
        rows = table.to_pylist()
        rows[0]["source_filing_date"] = "invented"
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), out / name)
    else:
        name = {
            "layout": "pages.jsonl", "page_disposition": "page_dispositions.jsonl",
            "queue_disposition": "queue_dispositions.jsonl",
        }.get(change, "views.jsonl")
        rows = old._jsonl(out / name)
        if change == "text":
            rows[0]["text"] = rows[0]["text"][:-15]
            rows[0]["raw_text_sha256"] = old._sha(rows[0]["text"].encode())
        elif change == "identity":
            rows[0]["source_identity"]["printed_evidence"][0]["start"] += 1
        elif change == "false_flag":
            rows[0]["scientific_approval"] = 0
        elif change == "prologue":
            rows[0]["archive_generated_prologue_preserved"] = True
        elif change == "layout":
            rows[0]["layout_text"] = "invented"
        elif change == "page_disposition":
            rows[0]["disposition"] = "selected_complete_version"
        else:
            rows[0]["original_queue_row"]["source_filing_date"] = "invented"
        old._write_rows(out / name, rows)
    _rebind(out, name)
    with pytest.raises(ValueError, match="replay|dependency"):
        nj.load_nj_collection(out)


@pytest.mark.parametrize("change", [
    "identity", "state", "typed_session", "null_date", "id", "duplicate",
])
def test_current_metadata_exact_original_identity_and_null_id_fields(packet, change):
    metadata = copy.deepcopy(packet[4])
    if change == "duplicate":
        metadata.append(copy.deepcopy(metadata[0]))
    else:
        key, value = {
            "identity": ("identifier", "S 100"), "state": ("state", "NY"),
            "typed_session": ("session_identifier", 220),
            "null_date": ("source_introduction_date", "2023-05-08"),
            "id": ("origin_filing_action_ids", ["invented"]),
        }[change]
        metadata[0][key] = value
    with pytest.raises(ValueError, match="candidate|metadata|typed literal"):
        nj.load_nj_collection(packet[0], metadata)


@pytest.mark.parametrize("change", [
    "omitted_pdf", "catalogue", "item", "bitstream", "transport", "raw_omission", "closure",
    "page_count", "approval",
])
def test_resealed_source_membership_and_transport_errors_fail_explicitly(work, change):
    source, queue, _, _ = _source(work)
    batch = old._json(source / "source-batch.json")
    if change == "omitted_pdf":
        batch["new_pdfs"].pop()
    elif change == "catalogue":
        batch["catalog_items"].pop()
    elif change == "item":
        batch["new_pdfs"][0]["catalog_item"]["uuid"] = "different-item"
    elif change == "bitstream":
        batch["new_pdfs"][0]["bitstream_record"]["_links"]["content"]["href"] += "-invented"
    elif change == "transport":
        path = source / batch["new_pdfs"][0]["capture"]["transport"]
        transport = old._json(path)
        transport["num_redirects"] = 1
        old._write(path, transport)
    elif change == "raw_omission":
        (source / batch["new_pdfs"][0]["capture"]["stderr"]).unlink()
    elif change == "page_count":
        batch["new_pdfs"][0]["n_pages"] += 1
    elif change == "approval":
        batch["training_approved"] = True
    else:
        batch["network_closed"] = False
    old._write(source / "source-batch.json", batch)
    source_sha = _seal(source)
    with pytest.raises(
        ValueError,
        match="membership|catalogue|bitstream|transport|missing|closure|page-count|approval",
    ):
        _build(source, queue, work / "invalid", source_sha)


@pytest.mark.parametrize("change", [
    "symlink", "hardlink", "outside_inventory", "missing_member", "repin_source",
])
def test_packet_safety_original_source_anchors_and_source_omissions(packet, change):
    out = packet[0]
    name = "source-evidence/raw/0004-pdf-0.body"
    target = out / name
    if change in {"symlink", "hardlink"}:
        external = out.parent / "linked-original"
        target.rename(external)
        if change == "symlink":
            target.symlink_to(external)
        else:
            target.hardlink_to(external)
    elif change == "outside_inventory":
        manifest = old._json(out / "manifest.json")
        manifest["packet_artifacts"]["../unsafe"] = old._binding(target)
        old._write(out / "manifest.json", manifest)
    elif change == "missing_member":
        target.unlink()
        manifest = old._json(out / "manifest.json")
        del manifest["packet_artifacts"][name]
        old._write(out / "manifest.json", manifest)
    else:
        target.write_bytes(target.read_bytes() + b"\nrepinned")
        _rebind(out, name)
    with pytest.raises(ValueError, match="linked|unsafe|omission|hash|mismatch|missing|incomplete"):
        nj.load_nj_collection(out)


@pytest.mark.parametrize("change", [
    "wrong_session", "wrong_typed_bill", "wrong_state", "unknown", "scanned", "boundary",
])
def test_unsupported_identity_scanned_pages_and_boundaries_are_full_negatives(work, change):
    texts = _pages()
    if change == "wrong_session":
        texts = [t.replace("220th", "221st") for t in texts]
    elif change == "wrong_typed_bill":
        texts = [t.replace("ASSEMBLY, No. 100", "ASSEMBLY RESOLUTION, No. 100")
                 .replace("SENATE, No. 200", "SENATE RESOLUTION, No. 200") for t in texts]
    elif change == "wrong_state":
        texts = [t.replace("STATE OF NEW JERSEY", "STATE OF NEW YORK")
                 .replace("of New Jersey:", "of New York:") for t in texts]
    elif change == "unknown":
        texts = ["All original unknown text.\n", "Full unknown ending.\n"]
    elif change == "scanned":
        texts = [""]
    else:
        texts[6] = texts[6].replace("\n3\n", "\n4\n")
    source, queue, source_sha, _ = _source(work, texts=texts)
    out = work / "negative"
    _build(source, queue, out, source_sha)
    views, contexts, _, manifest = nj.load_nj_collection(out)
    assert views == contexts == []
    assert manifest["counts"]["all_reader_pages"] == 2 * (len(texts) + 2)
    assert manifest["counts"]["quarantined_reader_pages"] == manifest["counts"]["all_reader_pages"]
    pages = old._jsonl(out / "pages.jsonl")
    assert len(pages) == manifest["counts"]["all_reader_pages"]
    assert all(d["disposition"] == "quarantined_reader" and d["reason"]
               for d in old._jsonl(out / "page_dispositions.jsonl"))


def test_full_closed_collection_and_reused_sources_never_duplicate_views(work):
    source, queue, _, _ = _source(work, status="closed_complete_collection_capture")
    batch = old._json(source / "source-batch.json")
    batch["reused_pdfs"] = [batch["new_pdfs"].pop()]
    old._write(source / "source-batch.json", batch)
    source_sha = _seal(source, "closed_complete_collection_capture")
    out = work / "full"
    _build(source, queue, out, source_sha)
    views, contexts, _, manifest = nj.load_nj_collection(out)
    assert len(views) == 4 and len(contexts) == 1
    assert manifest["counts"]["source_pdfs"] == 1
    assert manifest["counts"]["reused_pdfs_not_normalized"] == 1
    assert {p["source_id"] for p in old._jsonl(out / "pages.jsonl")} == {"pdf-0"}
    report = old._json(out / "report.json")
    assert report["complete_collection_capture"] is True
    assert report["unprocessed_catalogue_item_ids"] == []
    assert report["reused_source_dispositions"][0]["new_views"] == 0


def test_full_ledger_retains_prefix_guard_history_and_first16_without_reusing_old_text(work):
    source, queue, source_sha, originals = _full_source(work)
    out = work / "full-ledger"
    _build(source, queue, out, source_sha)
    views, contexts, _, manifest = nj.load_nj_collection(out, originals)
    assert len(views) == 4 and len(contexts) == 1
    assert manifest["counts"]["retained_inherited_prefix_records"] == 1
    assert manifest["counts"]["current_collection_http_captures"] == 5
    assert manifest["counts"]["known_aggregate_physical_exchanges"] == 7
    assert manifest["counts"]["unretained_inherited_identity_exchanges"] == 1
    assert all(v["source_members"]["capture_records"].endswith("request-ledger.jsonl")
               for v in views)
    assert all(v["source_identity"]["printed_evidence"][0]["source_id"].startswith(
        "nj-library-collection-source:",
    ) for v in views)
    report = old._json(out / "report.json")
    assert report["forensic_history_not_current_capture_failure"]["error"] == "'isArchived'"
    assert report["immutable_first16_source_manifest"]["sha256"] == old._binding(
        source / "sealed-first16/manifest.json",
    )["sha256"]


@pytest.mark.parametrize("change", [
    "prefix", "spacing", "tls", "budget_reset", "nested_capture", "reused_url",
])
def test_full_source_consistency_is_reconstructed_not_trusted_receipts(work, change):
    source, queue, _, _ = _full_source(work)
    if change in {"prefix", "spacing"}:
        path = source / "request-ledger.jsonl"
        ledger = old._jsonl(path)
        if change == "prefix":
            ledger = ledger[1:]
        else:
            ledger[2]["start_monotonic"] = ledger[1]["start_monotonic"]
        old._write_rows(path, ledger)
    elif change == "tls":
        batch = old._json(source / "source-batch.json")
        path = source / batch["new_pdfs"][0]["capture"]["transport"]
        transport = old._json(path)
        transport["ssl_verify_result"] = 1
        old._write(path, transport)
    elif change == "budget_reset":
        path = source / "schema-v2-continuation.json"
        continuation = old._json(path)
        continuation["original_new_request_ceiling"] = 501
        old._write(path, continuation)
    elif change == "nested_capture":
        path = source / "sealed-first16/source-batch.json"
        batch = old._json(path)
        batch["new_pdfs"][0]["capture"]["body_sha256"] = "0" * 64
        old._write(path, batch)
        _seal(source / "sealed-first16")
    else:
        path = source / "source-batch.json"
        batch = old._json(path)
        batch["reused_pdfs"][0]["original_entry"]["capture"]["url"] += "-invented"
        old._write(path, batch)
    source_sha = _seal(source, "closed_complete_collection_capture")
    with pytest.raises(
        ValueError, match="prefix|membership|spacing|TLS|allowance|mismatch|capture|seed",
    ):
        _build(source, queue, work / "invalid-full", source_sha)


def test_duplicate_capture_labels_are_storage_metadata_not_shared_identity(work):
    source, queue, _, _ = _source(work)
    batch = old._json(source / "source-batch.json")
    ledger = old._json(source / "request-ledger.snapshot.json")
    for entry in batch["new_pdfs"]:
        entry["capture"]["label"] = "same-chapter-label"
    for capture in ledger:
        if capture["ordinal"] in {4, 6}:
            capture["label"] = "same-chapter-label"
    old._write(source / "source-batch.json", batch)
    old._write(source / "request-ledger.snapshot.json", ledger)
    out = work / "duplicate-label"
    _build(source, queue, out, _seal(source))
    views, _, _, manifest = nj.load_nj_collection(out)
    assert len(views) == 4 and manifest["counts"]["source_pdfs"] == 2
    assert len({p["source_id"] for p in old._jsonl(out / "pages.jsonl")}) == 2
    assert all(v["source_identity"]["printed_evidence"][0]["source_id"].startswith(
        "nj-library-collection-source:",
    ) for v in views)


def test_new_url_with_prior_archive_identical_bytes_is_preserved_but_not_a_new_fill(work):
    source, queue, _, _ = _source(work, duplicate_bytes=True)
    batch = old._json(source / "source-batch.json")
    batch["reused_pdfs"] = [batch["new_pdfs"].pop(0)]
    old._write(source / "source-batch.json", batch)
    out = work / "new-url-old-bytes"
    _build(source, queue, out, _seal(source))
    views, contexts, _, manifest = nj.load_nj_collection(out)
    assert views == contexts == []
    assert manifest["counts"]["source_pdfs"] == 1
    assert manifest["counts"]["reused_pdfs_not_normalized"] == 1
    assert manifest["counts"]["all_reader_pages"] == 2 * len(_pages())
    assert all(d["disposition"] == "quarantined_reused_content"
               for d in old._jsonl(out / "page_dispositions.jsonl"))


def test_one_reader_unsupported_is_an_alternative_not_truth_or_a_duplicate(work, monkeypatch):
    source, queue, source_sha, _ = _source(work)
    extract = nj._extract

    def reader_difference(path, source_id):
        pages, documents = extract(path, source_id)
        for page in pages:
            if source_id == "pdf-0" and page["reader"] == "pypdf" and page["page_ordinal"] == 5:
                page["text"] = page["text"].replace("220th", "221st")
                page["text_binding"] = old._text_binding(page["text"])
        return pages, documents

    monkeypatch.setattr(nj, "_extract", reader_difference)
    out = work / "reader-alternative"
    _build(source, queue, out, source_sha)
    views, contexts, _, manifest = nj.load_nj_collection(out)
    assert len(views) == 2 and len(contexts) == 1
    assert {v["reader"] for v in views} == {"pymupdf"}
    assert manifest["counts"]["newly_covered_contexts"] == 1
    report = old._json(out / "report.json")
    assert all(c["ground_truth_reader"] is None for c in report["reader_comparisons"])
    assert any(not c["reader_version_structures_equal"] for c in report["reader_comparisons"])
    assert any(d["reader"] == "pypdf" and d["disposition"] == "quarantined_reader"
               for d in old._jsonl(out / "page_dispositions.jsonl"))


def test_explicit_trust_anchors_input_overlap_and_immutable_output(packet, work):
    out, source, queue, source_sha, _ = packet
    for kwargs in ({"source_manifest_sha256": "0" * 64}, {"gap_queue_sha256": "0" * 64}):
        with pytest.raises(ValueError, match="trust anchor"):
            nj.load_nj_collection(out, **kwargs)
    for output in (out, source / "overlap"):
        with pytest.raises(ValueError, match="new unlinked|overlap"):
            _build(source, queue, output, source_sha)
    with pytest.raises(ValueError, match="manifest hash"):
        _build(source, queue, work / "wrong-anchor", "0" * 64)

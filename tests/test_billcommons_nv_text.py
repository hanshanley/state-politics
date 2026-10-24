"""Finite offline Nevada original-reference replay and fail-closed export guards."""

import copy
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlencode

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from state_politics.bills import billcommons_nv_text as archive
from state_politics.bills.archive_text import load_archive

TITLE = "Revises provisions relating to governmental administration. (BDR\u00a045-300)"


def write_json(path, value):
    path.write_bytes(archive._json_bytes(value))


def context(identifier="AB 59"):
    return {
        "bill_id": "ocd-bill/original-" + identifier.replace(" ", "-"),
        "state": "NV", "identifier": identifier, "session_identifier": "83",
        "session_name": "2025 Regular Session", "source_introduction_date": "2024-11-20",
        "session_start_date": "2025-02-01", "session_end_date": "2025-06-01",
        "title": TITLE, "unknown_native_count": None, "source_unknown_flag": None,
        "source_event_in_window": True, "neither_source_observed": True,
        "model_input_approved": False, "snapshot_exact_version_foreign_keys": False,
    }


def body(identifier="AB 59", *, introduced=True, enrolled=False):
    kind, number = identifier.split()
    chamber = "ASSEMBLY" if kind == "AB" else "SENATE"
    prologue = (
        "- 83rd Session (2025)\n" if enrolled else
        f"  {kind[0]}.B. {number}\n\n- *{kind}{number}*\n"
    )
    title = (
        "SUMMARY—Revises provisions relating to governmental\n"
        "administration. (BDR 45-300)\n"
    )
    prefile = "PREFILED NOVEMBER 20, 2024\n" if introduced else ""
    return (
        prologue + f"{chamber} BILL NO. {number}–COMMITTEE ON NATURAL RESOURCES\n"
        + prefile + title
        + "FISCAL NOTE: Effect on Local Government: No.\n Effect on the State: Yes.\n~\n"
        "AN ACT relating to governmental administration; providing other matters\n"
        "properly relating thereto.\nLegislative Counsel’s Digest:\n"
        "This bill contains a complete unchanged policy; this digest is not the body.\n"
        "THE PEOPLE OF THE STATE OF NEVADA, REPRESENTED IN\n"
        "SENATE AND ASSEMBLY, DO ENACT AS FOLLOWS:\n"
        " Section 1. The agency shall preserve the complete original policy. 1\n"
        " (a) Preserve the source\u00a0spacing and case.\r\n"
        " Literal separators: \u2028 and \u2029 remain inside the JSONL string. 2\n"
        " – 2 –\n"
        + ("- 83rd Session (2025)\n" if enrolled else f"- *{kind}{number}*\n")
        + " Sec. 2. This act becomes effective upon passage and approval. 3\n"
        + ("\n20 ~~~~~ 25" if enrolled else "\nH")
    )


def exchange(directory, ordinal, url, value, status=200):
    prefix = directory / f"exchange-{ordinal:03d}"
    raw = archive._json_bytes(value) if isinstance(value, (dict, list)) else value
    prefix.with_suffix(".body").write_bytes(raw)
    prefix.with_suffix(".headers").write_bytes(f"HTTP/2 {status}\r\n\r\n".encode())
    prefix.with_suffix(".stderr.log").write_bytes(b"")
    write_json(prefix.with_suffix(".curl.json"), {
        "url": url, "url_effective": url, "method": "GET", "http_code": status,
        "response_code": status, "num_redirects": 0, "exitcode": 0, "size_download": len(raw),
    })


def reseal(source):
    def scope(directory):
        path = directory / "manifest.json"
        previous = archive._json(path) if path.exists() else {}
        if (directory / "previous").exists():
            scope(directory / "previous")
            previous["previous_scope_manifest"] = archive._binding(
                directory / "previous/manifest.json",
            )
        current = list(directory.glob("exchange-*.body"))
        write_json(path, {
            **previous, "actual_GETs": len(current),
            "scientific_approval": False, "publication": False,
            "artifacts": {p.name: archive._binding(p) for p in sorted(directory.iterdir())
                          if p.is_file() and p.name != "manifest.json"},
        })

    scopes, total = {}, 0
    for name in sorted(archive.SCOPES):
        directory = source / name
        scope(directory)
        count = len(list(directory.glob("exchange-*.body")))
        total += len(list(directory.rglob("exchange-*.body")))
        scopes[name] = {
            "directory": name, "actual_GETs": count,
            "manifest": archive._binding(directory / "manifest.json"),
        }
    old = archive._json(source / "manifest.json") if (source / "manifest.json").exists() else {}
    write_json(source / "manifest.json", {
        **old, "schema": archive.SOURCE_SCHEMA, "scopes": scopes, "actual_GETs": total,
        "input_gap_queue": archive._binding(source / "input_gap_queue.parquet"),
        "source_admission": False, "scientific_approval": False, "publication": False,
        "artifacts": {
            p.relative_to(source).as_posix(): archive._binding(p)
            for p in sorted(source.rglob("*")) if p.is_file() and p != source / "manifest.json"
        },
    })


def api_document():
    string = {"type": "string"}
    schemas = {
        "sessions": {"type": "object"}, "batch": {"type": "object"},
        "full": {"type": "object"},
        "text": {
            "type": "object", "required": [
                "document_id", "bill_id", "version_id", "extracted_text", "char_count",
                "fulltext_status",
            ],
            "properties": {
                **dict.fromkeys(("document_id", "bill_id", "version_id", "extracted_text"), string),
                "char_count": {"type": "integer"}, "fulltext_status": string,
            },
        },
    }
    paths = {}
    for route, name, params in [
        ("/api/v1/sessions", "sessions", []), ("/api/v1/bills/batch", "batch", ["keys"]),
        (archive.FULL_ROUTE, "full", ["bill_id"]),
        (archive.TEXT_ROUTE, "text", ["bill_id", "document_id"]),
    ]:
        paths[route] = {"get": {
            "parameters": [{"name": key} for key in params],
            "responses": {"200": {"content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/" + name},
            }}}},
        }}
    return {"openapi": "3.1.0", "paths": paths, "components": {"schemas": schemas}}


@pytest.fixture
def packet_source(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("strict offline adapter attempted a source request")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    source = tmp_path / "source"
    source.mkdir()
    for name in archive.SCOPES | {"originals"}:
        (source / name).mkdir()
    (source / "metadata/previous").mkdir()
    (source / "retained-diagnostic.log").write_bytes(b"All source diagnostics are preserved.\n")
    contexts = [context(), context("SB 72")]
    all_contexts = [*reversed(contexts), {**context("AB 90"), "state": "MA"}]
    table = pa.Table.from_pylist(all_contexts)
    pq.write_table(table, source / "input_gap_queue.parquet")
    session = {
        "id": archive.SESSION_ID, "identifier": archive.SESSION_IDENTIFIER,
        "jurisdiction_id": "nv-provider-jurisdiction", "jurisdiction_abbreviation": "NV",
        "start_date": "2025-02-03", "end_date": "2025-06-03", "canonical_session_id": None,
    }
    write_json(source / "metadata/provider_session_preserved.json", session)
    write_json(source / "metadata/exact_original_candidates.json", all_contexts[:2])
    exchange(source / "discovery", 1, archive.API + "/robots.txt", b"Not Found", 404)
    exchange(source / "discovery", 2, "https://billcommons.org/robots.txt",
             b"User-agent: *\nAllow: /\nDisallow: /search\nDisallow: /bills/*/compare\n")
    exchange(source / "discovery", 3, "https://billcommons.org/docs/api", b"Public API docs")
    exchange(source / "discovery", 4, archive.API + "/api/v1/sessions", {
        "data": [session], "pagination": {"page": 1, "total_pages": 1, "total": 1},
    })
    write_json(source / "discovery/complete_session_metadata.json", [session])
    exchange(source / "openapi", 1, archive.API + "/docs", b"/openapi.json")
    exchange(source / "openapi", 2, archive.API + "/openapi.json", api_document())
    exchange(source / "probe", 1, archive.API + "/api/v1/bills/batch?keys=NV%3AAB59", {
        "data": [], "ambiguous": {}, "not_found": ["NV:AB59"],
    })
    frontier, original_versions, original_links = [], [], []
    summaries = []
    for i, original in enumerate(contexts):
        bill_id = "provider:" + original["identifier"]
        provider_bill = {
            "id": bill_id, "identifier": original["identifier"], "title": original["title"],
            "jurisdiction_id": session["jurisdiction_id"], "jurisdiction_abbreviation": "NV",
            "session_id": session["id"], "session_identifier": session["identifier"],
            "introduced_date": original["source_introduction_date"], "short_title": None,
        }
        summaries.append(copy.deepcopy(provider_bill))
        versions, documents = [], []
        notes = ["As Introduced", "Reprint 1", "As Enrolled"] if i == 0 else ["As Introduced"]
        for j, note in enumerate(notes):
            version = {"id": f"provider-version:{i}:{j}", "bill_id": bill_id, "note": note,
                       "date": "2025-04-12" if j == 1 else None}
            original_version = {
                "id": f"original-version:{i}:{j}", "bill_id": original["bill_id"], "note": note,
                "date": "" if j != 1 else "2025-04-11", "extras": "{}", "classification": "",
            }
            original_versions.append(original_version)
            url = f"https://www.leg.state.nv.us/exact/{i}/{j}.pdf"
            attachment = {
                "id": f"document:{i}:{j}", "bill_version_id": version["id"],
                "media_type": "application/pdf", "url": url,
                "has_extracted_text": True, "text_is_partial": False,
            }
            original_links.append({
                "id": f"original-link:{i}:{j}", "media_type": "application/pdf",
                "url": url, "version_id": original_version["id"], "bill_id": original["bill_id"],
            })
            versions.append(version)
            documents.append(attachment)
        documents.append({
            "id": f"ancillary:{i}", "bill_version_id": versions[0]["id"],
            "media_type": "application/pdf",
            "url": f"https://www.leg.state.nv.us/exhibits/{i}.pdf",
            "has_extracted_text": True, "text_is_partial": False,
        })
        full = {
            "bill": provider_bill, "versions": versions, "documents": documents,
            "sponsors": [{"name": "Unchanged source name", "party": None}],
            "actions": [{"description": "Unchanged complete metadata, not policy"}],
        }
        directory = source / ("metadata/previous" if i == 0 else "metadata")
        ordinal = 2 if i == 0 else 1
        exchange(directory, ordinal, archive.API + f"/api/v1/bills/{bill_id}/full", full)
        frontier.append({
            "original_context": original, "provider_bill": provider_bill,
            "versions": versions, "documents": documents,
            "complete_metadata_file": (
                "previous/exchange-002.body" if i == 0 else "exchange-001.body"
            ),
            "capture_provenance": {
                "captured_in": "preserved_prefix" if i == 0 else "new_suffix",
                "original_exchange": ordinal,
            },
        })
    keys = ",".join(f"NV:{r['identifier'].replace(' ', '')}:{session['identifier']}"
                    for r in contexts)
    exchange(source / "metadata/previous", 1, archive.API + "/api/v1/bills/batch?"
             + urlencode({"keys": keys}), {"data": summaries, "not_found": [], "ambiguous": {}})
    write_json(source / "metadata/complete_document_frontier.json", frontier)
    unrelated = {
        "id": "not-a-target", "bill_id": all_contexts[-1]["bill_id"], "note": "As Introduced",
        "date": "", "extras": "{}", "classification": "",
    }
    for name, rows in [
        ("bill_versions.parquet", original_versions),
        ("bill_version_links.parquet", original_links),
    ]:
        extra = (unrelated if name == "bill_versions.parquet" else {
            "id": "unrelated-link", "bill_id": unrelated["bill_id"],
            "version_id": unrelated["id"], "url": "https://example.invalid/unrelated",
            "media_type": "application/pdf",
        })
        pq.write_table(pa.Table.from_pylist([*rows, extra]), source / "originals" / name)
        pq.write_table(pa.Table.from_pylist(rows), source / "texts" / name)
    authority = {
        name: {**archive._binding(source / "originals" / name),
               "rows": pq.ParquetFile(source / "originals" / name).metadata.num_rows}
        for name in archive.ORIGINAL_TABLES
    }
    extraction = {"artifacts": {
        name: {"sha256": spec["sha256"], "rows": spec["rows"]}
        for name, spec in authority.items()
    }}
    for directory in ("originals", "texts"):
        write_json(source / directory / "bill_extraction_manifest.json", extraction)
    monkeypatch.setattr(archive, "ORIGINAL_TABLES", authority)
    monkeypatch.setattr(archive, "EXTRACTION_SHA256", archive._binding(
        source / "originals/bill_extraction_manifest.json",
    )["sha256"])
    write_json(source / "texts/original_reference_bindings.json", {
        name: {
            "original_complete_table": {
                "path": "data/processed/" + name,
                **archive._binding(source / "originals" / name),
            },
            "original_table_rows": spec["rows"],
            "complete_target_subset": {
                "path": name, **archive._binding(source / "texts" / name),
            },
            "target_subset_rows": pq.ParquetFile(source / "texts" / name).metadata.num_rows,
        } for name, spec in authority.items()
    })
    plan, dispositions = archive._plan(
        frontier, {row["id"]: row for row in original_versions}, original_links,
    )
    write_json(source / "texts/exact_original_document_plan.json", plan)
    write_json(source / "texts/complete_document_dispositions.json", dispositions)
    inventory, new_number = [], 0
    for i, row in enumerate(plan):
        original = row["original_context"]
        note = row["original_version"]["note"]
        text = body(original["identifier"], introduced=note == "As Introduced",
                    enrolled=note == "As Enrolled")
        if note == "Reprint 1":
            text = text.replace("SUMMARY—Revises provisions", "SUMMARY—Amended provisions")
        attachment = row["provider_document"]
        response = {
            "document_id": attachment["id"], "bill_id": row["provider_bill_id"],
            "version_id": row["provider_version"]["id"], "extracted_text": text,
            "char_count": len(text), "fulltext_status": "ok",
        }
        url = archive.API + (
            f"/api/v1/bills/{row['provider_bill_id']}/documents/{attachment['id']}/text"
        )
        if i == 0:
            exchange(source / "pilot", 1, url, response)
            response_file = "reused-pilot-exchange-001.body"
            (source / "texts" / response_file).write_bytes(
                (source / "pilot/exchange-001.body").read_bytes(),
            )
            provenance = {
                "kind": "original_pilot_reuse_no_request", "response_file": response_file,
            }
        else:
            new_number += 1
            exchange(source / "texts", new_number, url, response)
            provenance = {
                "kind": "new_exact_document_GET", "ordinal": new_number,
                "response_file": f"exchange-{new_number:03d}.body",
            }
        path = f"complete-source-text-{i + 1:03d}.txt"
        (source / "texts" / path).write_bytes(text.encode("utf-8"))
        inventory.append({
            **row, "capture_provenance": provenance,
            "response_fields_preserved": {
                k: v for k, v in response.items() if k != "extracted_text"
            },
            "complete_text": {"path": path, **archive._binding(source / "texts" / path)},
            "full_characters": len(text),
        })
    reseal(source)
    for scope, key, value in [
        ("probe", "preceding_complete_publication_capture_GETs", 34),
        ("pilot", "preceding_publication_GETs", 35),
        ("texts", "preceding_publication_GETs", 39),
        ("texts", "expected_cumulative_publication_GETs", 42),
    ]:
        path = source / scope / "manifest.json"
        manifest = archive._json(path)
        manifest[key] = value
        write_json(path, manifest)
    reseal(source)
    inventory[0]["capture_provenance"]["source_manifest"] = archive._binding(
        source / "pilot/manifest.json",
    )
    write_json(source / "texts/complete_text_inventory.json", inventory)
    reseal(source)
    return source, table, tmp_path / "normalized"


def build(source, out):
    return archive.build_billcommons_nv(
        source, source / "input_gap_queue.parquet", out,
        source_manifest_sha256=archive._binding(source / "manifest.json")["sha256"],
        gap_queue_sha256=archive._binding(source / "input_gap_queue.parquet")["sha256"],
    )


def repin(out, name):
    manifest = archive._json(out / "manifest.json")
    manifest["packet_artifacts"][name] = archive._binding(out / name)
    write_json(out / "manifest.json", manifest)


def test_build_route_whole_strings_original_rows_and_all_dispositions(packet_source):
    source, table, out = packet_source
    result = build(source, out)
    views, contexts, pins, manifest = load_archive(out, table)
    assert manifest == result
    assert contexts == table.to_pylist()[:2]
    assert contexts[0]["identifier"] == "SB 72" and views[0]["identifier"] == "AB 59"
    assert len(views) == 4
    assert result["counts"]["newly_covered_contexts"] == 2
    assert result["counts"]["source_document_dispositions"] == 6
    assert result["counts"]["received_text_dispositions"] == 4
    assert result["counts"]["actual_pilot_text_reuses_not_recounted"] == 1
    assert result["counts"]["actual_GETs_previously_captured"] == 14
    assert pins.keys() >= {"producer/billcommons_nv_text.py", "producer/billcommons_text.py"}
    inventory = archive._json(source / "texts/complete_text_inventory.json")
    for view, capture in zip(views, inventory, strict=True):
        text = (source / "texts" / capture["complete_text"]["path"]).read_bytes().decode("utf-8")
        assert view["text"] == text
        assert "FISCAL NOTE:" in text
        assert "\r\n" in text and "\u2028" in text and "\u2029" in text
        assert view["inference_text_start"] == 0 and view["inference_text_end"] == len(text)
        assert view["archive_generated_prologue_preserved"] is False
        assert all(view[key] is False for key in archive.FLAGS)
        assert view["source_identity"]["original_link"] == capture["original_reference_matches"][0]
        for span in view["source_identity"]["printed_evidence"]:
            assert text[span["start"]:span["end"]] == span["text"]
    assert views[1]["source_version"]["version"]["date"] == "2025-04-12"
    assert views[1]["source_version"]["original_version"]["date"] == "2025-04-11"
    assert views[1]["original_target_context"]["source_introduction_date"] == "2024-11-20"
    assert views[1]["source_identity"]["printed_prefile_dates"] == []
    assert views[0]["source_version"]["printed_year"] is None
    assert views[2]["source_version"]["printed_year"] == 2025
    assert views[0]["source_session"]["start_date"] == "2025-02-03"
    assert views[0]["original_target_context"]["session_start_date"] == "2025-02-01"


def test_original_pilot_metadata_reuse_is_not_a_missing_batch_key_or_new_get(packet_source):
    source, _, out = packet_source
    path = source / "metadata/previous/exchange-002.body"
    full = archive._json(path)
    curl = archive._json(path.with_suffix(".curl.json"))
    exchange(source / "pilot", 2, curl["url"], full)
    (source / "metadata/previous/reused-pilot-NV-full.body").write_bytes(path.read_bytes())
    for suffix in (".body", ".curl.json", ".headers", ".stderr.log"):
        path.with_suffix(suffix).unlink()
    frontier_path = source / "metadata/complete_document_frontier.json"
    frontier = archive._json(frontier_path)
    frontier[0]["complete_metadata_file"] = "previous/reused-pilot-NV-full.body"
    frontier[0]["capture_provenance"] = {
        "captured_in": "original_pilot_reuse_not_new_request",
    }
    write_json(frontier_path, frontier)
    batch_path = source / "metadata/previous/exchange-001.body"
    batch = archive._json(batch_path)
    batch["data"] = [bill for bill in batch["data"] if bill["identifier"] == "SB 72"]
    exchange(source / "metadata/previous", 1, archive.API + "/api/v1/bills/batch?" + urlencode({
        "keys": "NV:SB72:" + archive.SESSION_IDENTIFIER,
    }), batch)
    reseal(source)
    inventory = archive._json(source / "texts/complete_text_inventory.json")
    inventory[0]["capture_provenance"]["source_manifest"] = archive._binding(
        source / "pilot/manifest.json",
    )
    write_json(source / "texts/complete_text_inventory.json", inventory)
    reseal(source)
    result = build(source, out)
    views, contexts, _, _ = archive.load_billcommons_nv(out)
    assert len(views) == 4 and len(contexts) == 2
    assert result["counts"]["actual_GETs_previously_captured"] == 14


@pytest.mark.parametrize(("change", "reason"), [
    (lambda t: t.replace("BILL NO. 59", "BILL NO. 99"), "contradictory_own_formal"),
    (lambda t: "A.B. 99\n" + t, "contradictory_own_short"),
    (lambda t: t.replace("SUMMARY", "A.B. 99\nSUMMARY"), "contradictory_own_short"),
    (lambda t: t.replace("STATE OF NEVADA", "STATE OF UTAH"), "contradictory_own_nevada"),
    (lambda t: "STATE OF UTAH\n" + t, "contradictory_own_state"),
    (lambda t: "- 82nd Session (2023)\n" + t, "contradictory_own_session"),
    (lambda t: "2026 Session (83rd)\n" + t, "contradictory_own_session"),
    (lambda t: t.replace(" Section 1.", " Article 1."), "missing_complete_caption"),
    (lambda t: t.replace("AN ACT", "SUMMARY ONLY"), "missing_complete_caption"),
    (lambda t: t[:-2], "missing_observed_original_body"),
    (lambda t: t.replace(" – 2 –", " – 3 –"), "discontinuous_observed"),
    (lambda t: t.replace("NOVEMBER 20", "NOVEMBER 21"), "prefile_original_date"),
    (lambda t: t.replace("PREFILED NOVEMBER 20, 2024", ""), "prefile_original_date"),
    (lambda t: t.replace("BDR 45-300", "BDR 45-999"), "summary_bdr"),
    (lambda t: "Sign in\nCreate an account\n" + t, "access_or_ancillary"),
    (lambda t: "TESTIMONY IN OPPOSITION\n" + t, "access_or_ancillary"),
    (lambda t: "Amendment No. 7\n" + t, "amendment_document"),
])
def test_own_identity_body_and_completeness_negatives(change, reason):
    identity, disposition = archive._observe(
        change(body()), context(), "application/pdf", {"note": "As Introduced"},
    )
    assert identity is None and reason in disposition


def test_cited_number_fiscal_attachment_and_copied_access_page_are_not_bills():
    for text in [
        "FISCAL NOTE\nBill: ASSEMBLY BILL NO. 59\nEstimated fiscal effect: none.\n",
        "Sign in\nAccess to Nevada exhibits requires an account.\n",
        "Testimony relating to ASSEMBLY BILL NO. 59\nTHE PEOPLE OF THE STATE OF NEVADA\n",
    ]:
        assert archive.printed_identity(
            text, context(), "application/pdf", {"note": "As Introduced"},
        ) is None


def test_actual_nevada_recital_line_numbers_changed_summary_and_no_effective_clause():
    text = body().replace("REPRESENTED IN\n", "REPRESENTED IN 24\n").replace(
        "FOLLOWS:\n", "FOLLOWS: 25\n",
    )
    identity = archive.printed_identity(
        text, context(), "application/pdf", {"note": "As Introduced"},
    )
    assert identity is not None
    assert any("REPRESENTED IN 24\n" in span["text"] for span in identity["printed_evidence"])
    changed_title = {**context(), "title": "Different latest summary. (BDR\u00a045-300)"}
    identity = archive.printed_identity(
        text, changed_title, "application/pdf", {"note": "As Introduced"},
    )
    assert identity is not None
    assert identity["printed_summary_matches_original_title"] is False
    assert identity["printed_bdr_matches_original_title"] is True
    no_effective = body().replace(
        " Sec. 2. This act becomes effective upon passage and approval. 3",
        " Sec. 2. The agency shall preserve every completed record. 3",
    )
    identity = archive.printed_identity(
        no_effective, context(), "application/pdf", {"note": "As Introduced"},
    )
    assert identity is not None and identity["printed_effective_clause_evidence"] is None
    special_bdr = body().replace("45-300", "S-137").replace(
        " Sec. 2. This act becomes effective upon passage and approval. 3",
        " Sec. 2. (Deleted by amendment.) 3",
    )
    identity = archive.printed_identity(
        special_bdr, {**context(), "title": TITLE.replace("45-300", "S-137")},
        "application/pdf", {"note": "As Introduced"},
    )
    assert identity is not None and identity["printed_bdr_matches_original_title"] is True


@pytest.mark.parametrize("change", [
    lambda t: t.replace(" – 2 –\n", ""),
    lambda t: t.replace("- *AB59*\n Sec. 2.", "- *AB99*\n Sec. 2."),
])
def test_deleted_folio_and_contradictory_page_signature_not_accepted(change):
    assert archive.printed_identity(
        change(body()), context(), "application/pdf", {"note": "As Introduced"},
    ) is None


@pytest.mark.parametrize("defect", [
    "original_null", "original_type", "query_field", "query_schema", "national_table",
    "forged_version", "forged_provider", "url_case", "url_alias", "missing_received",
    "extra_exchange", "prefix_extra", "prefix_missing", "partial_text_bytes",
    "response_id", "char_count", "promoted", "reuse_bytes", "source_counter",
])
def test_rebound_source_cannot_replace_original_chain(packet_source, defect):
    source, _, out = packet_source
    texts = source / "texts"
    if defect.startswith("original"):
        path = source / "metadata/exact_original_candidates.json"
        rows = archive._json(path)
        key = "source_unknown_flag" if defect == "original_null" else "source_event_in_window"
        rows[0][key] = "" if defect == "original_null" else 1
        write_json(path, rows)
    elif defect.startswith("query"):
        path = texts / "bill_versions.parquet"
        table = pq.read_table(path)
        if defect == "query_field":
            rows = table.to_pylist()
            rows[0]["date"] = "2025-12-31"
            table = pa.Table.from_pylist(rows)
        else:
            table = table.replace_schema_metadata({"changed": "schema"})
        pq.write_table(table, path)
        bindings = archive._json(texts / "original_reference_bindings.json")
        bindings[path.name]["complete_target_subset"].update(archive._binding(path))
        write_json(texts / "original_reference_bindings.json", bindings)
    elif defect == "national_table":
        path = source / "originals/bill_versions.parquet"
        rows = pq.read_table(path).to_pylist()
        rows[-1]["date"] = "2025-01-01"
        pq.write_table(pa.Table.from_pylist(rows), path)
    elif defect in ("forged_version", "forged_provider", "url_case", "url_alias"):
        path = texts / "exact_original_document_plan.json"
        rows = archive._json(path)
        if defect == "forged_version":
            rows[0]["original_version"]["bill_id"] = "ocd-bill/same-number-different-context"
        elif defect == "forged_provider":
            rows[0]["provider_version"]["bill_id"] = "provider:wrong-bill"
        else:
            rows[0]["provider_document"]["url"] = rows[0]["provider_document"]["url"].replace(
                "exact", "EXACT" if defect == "url_case" else "alias",
            )
        write_json(path, rows)
    elif defect == "missing_received":
        path = texts / "complete_text_inventory.json"
        rows = archive._json(path)
        rows.pop()
        write_json(path, rows)
    elif defect == "extra_exchange":
        exchange(texts, 4, archive.API + "/unrequested", b"{}")
    elif defect == "prefix_extra":
        (source / "metadata/previous/extra").mkdir()
        (source / "metadata/previous/extra/unlisted.txt").write_bytes(b"must not be ignored")
    elif defect == "prefix_missing":
        (source / "metadata/previous/exchange-002.headers").unlink()
    elif defect == "partial_text_bytes":
        path = texts / "complete-source-text-001.txt"
        path.write_bytes(path.read_bytes()[:-1])
        rows = archive._json(texts / "complete_text_inventory.json")
        rows[0]["complete_text"].update(archive._binding(path))
        write_json(texts / "complete_text_inventory.json", rows)
    elif defect in ("response_id", "char_count"):
        path = texts / "exchange-001.body"
        value = archive._json(path)
        value["bill_id" if defect == "response_id" else "char_count"] = (
            "wrong" if defect == "response_id" else 1
        )
        update_response(path, value)
        rows = archive._json(texts / "complete_text_inventory.json")
        rows[1]["response_fields_preserved"] = {
            k: v for k, v in value.items() if k != "extracted_text"
        }
        write_json(texts / "complete_text_inventory.json", rows)
    elif defect == "promoted":
        path = source / "metadata/manifest.json"
        value = archive._json(path)
        value["source_rights_approved"] = True
        write_json(path, value)
    elif defect == "reuse_bytes":
        path = texts / "reused-pilot-exchange-001.body"
        path.write_bytes(path.read_bytes() + b" ")
    elif defect == "source_counter":
        path = source / "manifest.json"
        value = archive._json(path)
        value["new_NV_metadata_text_GETs"] = 999
        write_json(path, value)
    reseal(source)
    with pytest.raises(ValueError):
        build(source, out)
    assert not out.exists()


def update_response(path, response):
    write_json(path, response)
    curl = archive._json(path.with_suffix(".curl.json"))
    curl["size_download"] = path.stat().st_size
    write_json(path.with_suffix(".curl.json"), curl)


@pytest.mark.parametrize("defect", ["partial", "status", "wrong_body", "deleted_folio"])
def test_received_unknown_or_partial_body_remains_explicit_negative(packet_source, defect):
    source, _, out = packet_source
    texts = source / "texts"
    inventory = archive._json(texts / "complete_text_inventory.json")
    capture = inventory[1]
    if defect == "partial":
        path = source / "metadata/previous/exchange-002.body"
        full = archive._json(path)
        full["documents"][1]["text_is_partial"] = True
        update_response(path, full)
        frontier_path = source / "metadata/complete_document_frontier.json"
        frontier = archive._json(frontier_path)
        frontier[0]["documents"] = full["documents"]
        write_json(frontier_path, frontier)
        # A partial offered document must not be requested or silently substituted.
        reseal(source)
        with pytest.raises(ValueError, match="plan"):
            build(source, out)
        return
    path = texts / capture["capture_provenance"]["response_file"]
    response = archive._json(path)
    if defect == "status":
        response["fulltext_status"] = "partial"
    else:
        response["extracted_text"] = (
            "A stored HTTP200 login page, not a bill." if defect == "wrong_body" else
            response["extracted_text"].replace(" – 2 –", " – 4 –")
        )
        response["char_count"] = len(response["extracted_text"])
    update_response(path, response)
    text_path = texts / capture["complete_text"]["path"]
    text_path.write_bytes(response["extracted_text"].encode("utf-8"))
    capture["complete_text"].update(archive._binding(text_path))
    capture["full_characters"] = len(response["extracted_text"])
    capture["response_fields_preserved"] = {
        k: v for k, v in response.items() if k != "extracted_text"
    }
    write_json(texts / "complete_text_inventory.json", inventory)
    reseal(source)
    build(source, out)
    views, _, _, _ = archive.load_billcommons_nv(out)
    assert len(views) == 3
    dispositions = list(archive._rows(out / "received_text_dispositions.jsonl"))
    assert len(dispositions) == 4
    assert dispositions[1]["disposition"] != dispositions[0]["disposition"]


@pytest.mark.parametrize("name", [
    "views.jsonl", "context_inventory.parquet", "candidate_dispositions.parquet",
    "received_text_dispositions.jsonl", "source_document_dispositions.jsonl",
    "report.json", "producer/billcommons_nv_text.py", "producer/billcommons_text.py",
])
def test_rebound_exports_and_producers_are_recomputed(packet_source, name):
    source, _, out = packet_source
    build(source, out)
    path = out / name
    if name.endswith(".jsonl"):
        rows = list(archive._rows(path))
        if name == "views.jsonl":
            rows[0]["text"] += "\nRebound fabricated source header."
        else:
            rows.pop()
        path.write_bytes(archive._row_bytes(rows))
    elif name.endswith(".parquet"):
        table = pq.read_table(path)
        rows = table.to_pylist()
        if name == "context_inventory.parquet":
            rows[0]["source_unknown_flag"] = ""
        else:
            rows[0]["n_retained_source_views"] = 999
        pq.write_table(pa.Table.from_pylist(rows), path)
    elif name.startswith("producer/"):
        path.write_bytes(path.read_bytes() + b"\n# Rebound producer.\n")
    else:
        value = archive._json(path)
        value["counts"]["text_views"] = 999
        write_json(path, value)
    repin(out, name)
    with pytest.raises(ValueError, match="replay mismatch|producer mismatch"):
        archive.load_billcommons_nv(out)


def test_promotions_external_pins_current_metadata_and_overwrite(packet_source):
    source, table, out = packet_source
    build(source, out)
    with pytest.raises(ValueError, match="new nonoverlapping"):
        build(source, out)
    with pytest.raises(ValueError, match="anchor"):
        archive.load_billcommons_nv(out, source_manifest_sha256="f" * 64)
    changed = table.to_pylist()
    changed[0]["unknown_native_count"] = 0
    with pytest.raises(ValueError, match="missingness/type"):
        load_archive(out, changed)
    with pytest.raises(ValueError, match="missing or duplicated"):
        load_archive(out, [*table.to_pylist(), table.to_pylist()[0]])
    value = archive._json(out / "manifest.json")
    value["approvals"]["publication_approved"] = True
    write_json(out / "manifest.json", value)
    with pytest.raises(ValueError, match="approval"):
        archive.load_billcommons_nv(out)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "traversal"])
def test_unsafe_source_members_refused_before_output(packet_source, kind):
    source, _, out = packet_source
    member = source / "retained-diagnostic.log"
    if kind == "traversal":
        manifest = archive._json(source / "manifest.json")
        manifest["artifacts"]["../outside"] = archive._binding(member)
        write_json(source / "manifest.json", manifest)
    else:
        target = source.parent / "outside.txt"
        target.write_bytes(member.read_bytes())
        member.unlink()
        if kind == "symlink":
            member.symlink_to(target)
        else:
            os.link(target, member)
    with pytest.raises(ValueError):
        build(source, out)
    assert not out.exists()


@pytest.mark.parametrize("raw", [
    b'{"same":null,"same":null}', b'{"value":NaN}', b'{"value":1e999}',
    '{"value":null}'.encode("utf-16"),
])
def test_strict_json_duplicates_nonfinite_and_encoding(raw):
    with pytest.raises((ValueError, UnicodeError)):
        archive._decode(raw)


def test_cli_build_and_replay(packet_source, capsys):
    source, _, out = packet_source
    source_sha = archive._binding(source / "manifest.json")["sha256"]
    queue_sha = archive._binding(source / "input_gap_queue.parquet")["sha256"]
    archive.main([
        "build", "--source-dir", str(source), "--source-manifest-sha256", source_sha,
        "--gap-queue", str(source / "input_gap_queue.parquet"), "--gap-queue-sha256", queue_sha,
        "--out-dir", str(out),
    ])
    counts = json.loads(capsys.readouterr().out)
    archive.main([
        "replay", "--directory", str(out), "--source-manifest-sha256", source_sha,
        "--gap-queue-sha256", queue_sha,
    ])
    assert json.loads(capsys.readouterr().out) == counts


def test_archive_preview_freezes_nevada_adapter_without_new_renderer(tmp_path, monkeypatch):
    import test_cycle_site

    bundle = test_cycle_site.cycle_bundle.__wrapped__(tmp_path)
    test_cycle_site.test_independent_archive_exports_preserve_provider_alternatives_and_full_text(
        bundle, tmp_path, monkeypatch, False,
    )
    path = tmp_path / "archive-preview/downloads/producers/billcommons_nv_text.py"
    assert path.read_bytes() == Path(archive.__file__).read_bytes()

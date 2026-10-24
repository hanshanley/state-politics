"""Offline stored-extraction identities, complete evidence and exact replay guards."""

import copy
import hashlib
import json
import os
import socket
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from state_politics.bills import billcommons_text as archive
from state_politics.bills.archive_text import load_archive

HB_TITLE = "AN ACT TO AMEND TITLE 14 OF THE DELAWARE CODE RELATING TO SCHOOL OFFICER FUNDING."
SR_TITLE = "RELATING TO THE ELECTION OF THE PRESIDENT PRO TEMPORE."


def write_json(path, value):
    path.write_bytes(archive._json_bytes(value))


def context(identifier="HB 32"):
    return {
        "bill_id": "original:" + identifier, "state": "DE", "identifier": identifier,
        "session_identifier": "153", "session_name": "153rd General Assembly (2025-2026)",
        "title": SR_TITLE if identifier.startswith("SR") else HB_TITLE,
        "source_introduction_date": "2024-12-16" if identifier.startswith("SR") else "2024-12-19",
        "unknown_native_count": None, "source_unknown_flag": None,
        "source_event_in_window": True, "neither_source_observed": True,
        "model_input_approved": False,
    }


def body(identifier="HB 32", *, pdf=True, recitals=False):
    kind, number = identifier.split()
    venue = "HOUSE OF REPRESENTATIVES" if kind == "HB" else "DELAWARE STATE SENATE"
    formal = "HOUSE BILL" if kind == "HB" else "SENATE RESOLUTION"
    title = context(identifier)["title"]
    if pdf:
        prefix = "DLS : TEST : CM\n3021530034\nPage 1 of 2 Released: 12/19/2024  10:14 AM\n"
        title = title.replace("SCHOOL OFFICER", "SCHOOL\nOFFICER")
    else:
        prefix = "                "
        title = title.replace("SCHOOL OFFICER", "SCHOOL\u00a0OFFICER")
    header = (
        f"{prefix}SPONSOR: Representative Source\n{venue}\n153rd GENERAL ASSEMBLY\n"
        f"{formal} NO. {number}\n{title}\n"
    )
    line = "1 " if pdf else "        "
    if kind == "HB":
        policy = (
            (line + "WHEREAS, these are the actual recitals; and\n" if recitals else "")
            + line + "BE IT ENACTED BY THE GENERAL ASSEMBLY OF THE STATE OF DELAWARE:\n"
            + line + "Section 1. Complete unchanged policy. \u2028Inside one JSONL string.\n"
        )
    else:
        policy = (
            line + "BE IT RESOLVED by the Senate of the 153\n\n rd\n\n General Assembly "
            "of the State of Delaware that David P. Sokola is elected President Pro Tempore.\n"
        )
    ending = "Page 2 of 2 Released: 12/19/2024  10:14 AM\n" if pdf else ""
    return (
        header + policy + ending + "SYNOPSIS\nThis is the complete synopsis.\r\nExact ending.\u2029"
    )


def fiscal_note():
    return (
        "3471530001 Page 1 of 1 Date: January 03, 2025\n153rd GENERAL ASSEMBLY\n"
        "FISCAL NOTE\nBILL: HOUSE BILL NO. 32\nDESCRIPTION: " + HB_TITLE + "\n"
        "Assumptions: Fiscal analysis, not a bill.\n"
    )


def seal_source(source):
    scopes = {}
    for name in ("discovery", "openapi", "metadata", "texts"):
        directory = source / name
        ledger_path = directory / "request_ledger.jsonl"
        if ledger_path.exists():
            ledger = list(archive._rows(ledger_path))
            for row in ledger:
                row["artifacts"] = {
                    member: archive._binding(directory / member) for member in row["artifacts"]
                }
            ledger_path.write_bytes(archive._row_bytes(ledger))
        old = archive._json(directory / "manifest.json") if (
            directory / "manifest.json"
        ).exists() else {}
        count = len(list(directory.glob("exchange-*.body")))
        write_json(directory / "manifest.json", {
            **old, "actual_GETs": count, "scientific_approval": False, "publication": False,
            "artifacts": {
                path.name: archive._binding(path) for path in sorted(directory.iterdir())
                if path.name != "manifest.json"
            },
        })
        scopes[name] = {
            "directory": name, "manifest": archive._binding(directory / "manifest.json"),
            "actual_GETs": count,
        }
    write_json(source / "manifest.json", {
        "schema": archive.SOURCE_SCHEMA, "scopes": scopes,
        "actual_GETs": sum(row["actual_GETs"] for row in scopes.values()),
        "input_gap_queue": archive._binding(source / "input_gap_queue.parquet"),
        "source_admission": False, "scientific_approval": False, "publication": False,
        "artifacts": {
            path.relative_to(source).as_posix(): archive._binding(path)
            for path in sorted(source.rglob("*")) if path.is_file()
            and path != source / "manifest.json"
        },
    })


def exchange(source, scope, ordinal, url, value, status=200):
    prefix = source / scope / f"exchange-{ordinal:03d}"
    raw = archive._json_bytes(value) if isinstance(value, (dict, list)) else value
    prefix.with_suffix(".body").write_bytes(raw)
    prefix.with_suffix(".headers").write_bytes(f"HTTP/2 {status}\r\n\r\n".encode())
    prefix.with_suffix(".stderr.log").write_bytes(b"")
    write_json(prefix.with_suffix(".curl.json"), {
        "url": url, "url_effective": url, "method": "GET", "http_code": status,
        "response_code": status, "num_redirects": 0, "exitcode": 0, "size_download": len(raw),
    })
    ledger_path = source / scope / "request_ledger.jsonl"
    rows = list(archive._rows(ledger_path)) if ledger_path.exists() else []
    rows.append({
        "ordinal": ordinal, "url": url, "method": "GET", "returncode": 0, "status": status,
        "no_cookies_authorization_retries_or_automatic_redirects": True,
        "artifacts": {
            path.name: archive._binding(path) for path in [
                prefix.with_suffix(suffix)
                for suffix in (".body", ".curl.json", ".headers", ".stderr.log")
            ]
        },
    })
    ledger_path.write_bytes(archive._row_bytes(sorted(rows, key=lambda row: row["ordinal"])))


def api_document():
    def obj(fields, required=None):
        return {"type": "object", "properties": fields,
                "required": list(fields) if required is None else required}

    string = {"type": "string"}
    integer = {"type": "integer"}
    nullable = {"anyOf": [string, {"type": "null"}]}
    schemas = {
        "Sessions": obj({"data": {"type": "array", "items": {"type": "object"}},
                         "pagination": obj(dict.fromkeys(
                             ("page", "per_page", "total", "total_pages"), integer,
                         ))}),
        "Batch": obj({"data": {"type": "array", "items": {"type": "object"}},
                      "not_found": {"type": "array"}, "ambiguous": {"type": "object"}}),
        "Full": obj({"bill": {"type": "object"}, "versions": {"type": "array"},
                     "documents": {"type": "array"}, "sponsors": {"type": "array"},
                     "actions": {"type": "array"}}),
        "Text": obj({"document_id": string, "bill_id": string, "version_id": string,
                     "extracted_text": string, "char_count": integer, "fulltext_status": nullable}),
    }
    paths = {}
    for route, schema, params in [
        ("/api/v1/sessions", "Sessions", []), ("/api/v1/bills/batch", "Batch", ["keys"]),
        (archive.FULL_ROUTE, "Full", ["bill_id"]),
        (archive.TEXT_ROUTE, "Text", ["bill_id", "document_id"]),
    ]:
        paths[route] = {"get": {
            "parameters": [{"name": key} for key in params],
            "responses": {"200": {"content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/" + schema},
            }}}},
        }}
    return {"openapi": "3.1.0", "paths": paths, "components": {"schemas": schemas}}


@pytest.fixture
def packet_source(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("offline adapter attempted network")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    source = tmp_path / "source"
    source.mkdir()
    (source / "executed_consolidation.py").write_bytes(b"# Retained provenance, never executed.\n")
    for name in ("discovery", "openapi", "metadata", "texts"):
        (source / name).mkdir()
    contexts = [context(), context("SR 3"), context("HB 22")]
    table = pa.Table.from_pylist([*contexts, {**context("HB 99"), "state": "MA"}])
    pq.write_table(table, source / "input_gap_queue.parquet")
    session = {
        "id": archive.SESSION_ID, "identifier": archive.SESSION_IDENTIFIER,
        "jurisdiction_id": "de-provider-jurisdiction", "jurisdiction_abbreviation": "DE",
        "start_date": "2026-01-13", "end_date": "2026-06-30", "notice": None,
    }
    write_json(source / "metadata/provider_session_preserved.json", session)
    exchange(source, "discovery", 1, archive.API + "/robots.txt", b'{"detail":"Not Found"}', 404)
    exchange(source, "discovery", 2, "https://billcommons.org/robots.txt",
             b"User-agent: *\nAllow: /\nDisallow: /search\nDisallow: /bills/*/compare\n")
    exchange(source, "discovery", 3, "https://billcommons.org/docs/api",
             b"Complete public API docs")
    exchange(source, "discovery", 4, archive.API + "/api/v1/sessions", {
        "data": [session],
        "pagination": {"page": 1, "per_page": 25, "total": 1, "total_pages": 1},
    })
    write_json(source / "discovery/complete_session_metadata.json", [session])
    exchange(source, "openapi", 1, archive.API + "/docs", b'<script url="/openapi.json"></script>')
    exchange(source, "openapi", 2, archive.API + "/openapi.json", api_document())
    frontier, summaries, inventory = [], [], []
    text_number = 0
    ordered_numbers = sorted(row["identifier"].replace(" ", "") for row in contexts)
    for original in contexts:
        number = ordered_numbers.index(original["identifier"].replace(" ", "")) + 2
        provider_id = "provider:" + original["identifier"]
        version = {"id": "version:" + provider_id, "bill_id": provider_id,
                   "note": "Bill Text", "date": None}
        bill = {
            "id": provider_id, "identifier": original["identifier"], "title": original["title"],
            "jurisdiction_id": session["jurisdiction_id"], "jurisdiction_abbreviation": "DE",
            "session_id": session["id"], "session_identifier": session["identifier"],
            "introduced_date": original["source_introduction_date"], "short_title": None,
        }
        documents = []
        styles = [True, False, "fiscal"] if original["identifier"] == "HB 32" else (
            [False] if original["identifier"] == "SR 3" else []
        )
        for style in styles:
            text_number += 1
            text = fiscal_note() if style == "fiscal" else body(
                original["identifier"], pdf=style, recitals=True,
            )
            attachment = {
                "id": f"document:{text_number}", "bill_version_id": version["id"],
                "media_type": "application/pdf" if style else "text/html",
                "url": f"https://legis.delaware.gov/original/{text_number}",
                "has_extracted_text": True, "text_is_partial": False,
            }
            documents.append(attachment)
            response = {
                "document_id": attachment["id"], "bill_id": bill["id"],
                "version_id": version["id"], "extracted_text": text,
                "char_count": len(text), "fulltext_status": "ok",
            }
            url = archive.API + f"/api/v1/bills/{bill['id']}/documents/{attachment['id']}/text"
            exchange(source, "texts", text_number, url, response)
            path = f"complete-source-text-{text_number:02d}.txt"
            (source / "texts" / path).write_bytes(text.encode("utf-8"))
            inventory.append({
                "original_bill_id": original["bill_id"],
                "original_identifier": original["identifier"],
                "provider_bill_id": bill["id"], "provider_document": attachment,
                "provider_version": version, "source_exchange": text_number,
                "response_fields_preserved": {
                    key: value for key, value in response.items() if key != "extracted_text"
                },
                "complete_text": {"path": path, **archive._binding(source / "texts" / path)},
                "full_policy_characters": len(text),
            })
        full = {"bill": bill, "versions": [version], "documents": documents,
                "sponsors": [{"party": None, "name": "Preserved source sponsor, not policy"}],
                "actions": [{"description": "Unchanged provider action"}], "subjects": ["not gold"]}
        exchange(source, "metadata", number,
                 archive.API + f"/api/v1/bills/{bill['id']}/full", full)
        frontier.append({
            "original_bill_id": original["bill_id"], "original_identifier": original["identifier"],
            "original_title": original["title"], "provider_bill": bill,
            "provider_full_exchange": number, "versions": [version], "documents": documents,
            "complete_metadata_file": f"exchange-{number:03d}.body",
        })
        summaries.append({key: bill[key] for key in ("id", "identifier", "title", "session_id")})
    keys = ",".join(
        f"DE:{number}:{session['identifier']}" for number in ordered_numbers
    )
    batch = {
        "data": sorted(summaries, key=lambda row: row["identifier"].replace(" ", "")),
        "not_found": [], "ambiguous": {},
    }
    exchange(source, "metadata", 1,
             archive.API + "/api/v1/bills/batch?" + urlencode({"keys": keys}), batch)
    write_json(source / "metadata/batch_dispositions.json", batch)
    write_json(source / "metadata/exact_original_candidates.json", contexts)
    write_json(source / "metadata/candidate_document_frontier.json",
               sorted(frontier, key=lambda row: row["provider_full_exchange"]))
    write_json(source / "texts/complete_text_inventory.json", inventory)
    seal_source(source)
    return source, table, tmp_path / "normalized"


def build(source, out):
    return archive.build_billcommons(
        source, source / "input_gap_queue.parquet", out,
        source_manifest_sha256=archive._binding(source / "manifest.json")["sha256"],
        gap_queue_sha256=archive._binding(source / "input_gap_queue.parquet")["sha256"],
    )


def repin(out, name):
    manifest = archive._json(out / "manifest.json")
    manifest["packet_artifacts"][name] = archive._binding(out / name)
    write_json(out / "manifest.json", manifest)


@pytest.mark.parametrize(("identifier", "pdf", "recitals"), [
    ("HB 32", True, False), ("HB 32", False, True), ("SR 3", True, False),
    ("SR 3", False, False),
])
def test_literal_identity_caption_wrapping_recitals_short_resolution(identifier, pdf, recitals):
    text = body(identifier, pdf=pdf, recitals=recitals)
    identity = archive.printed_identity(
        text, context(identifier), "application/pdf" if pdf else "text/html",
    )
    assert identity is not None and identity["printed_year"] is None
    assert identity["inference_text_start"] == 0 and identity["inference_text_end"] == len(text)
    assert identity["kind"] == ("bill" if identifier.startswith("HB") else "resolution")
    for span in identity["printed_evidence"] + identity["printed_page_evidence"]:
        assert text[span["start"]:span["end"]] == span["text"]
    assert identity["printed_page_sequence_complete"] is (True if pdf else None)


@pytest.mark.parametrize("defect", [
    "fiscal", "typed_number", "assembly", "caption", "cited_number", "no_synopsis",
    "empty_synopsis", "no_clause", "omitted_page", "duplicate_page", "wrong_page_total",
    "quoted_own_block",
])
def test_identity_and_completeness_fail_closed(defect):
    text = body()
    if defect == "fiscal":
        text = fiscal_note()
    elif defect == "typed_number":
        text = text.replace("HOUSE BILL NO. 32", "SENATE BILL NO. 32")
    elif defect == "assembly":
        text = text.replace("153rd GENERAL ASSEMBLY", "152nd GENERAL ASSEMBLY")
    elif defect == "caption":
        text = text.replace("SCHOOL\nOFFICER", "SCHOOL\nLIBRARY")
    elif defect == "cited_number":
        text = text.replace("HOUSE BILL NO. 32", "HOUSE BILL NO. 99")
        text += "\nReferences HOUSE BILL NO. 32\n"
    elif defect == "no_synopsis":
        text = text.replace("SYNOPSIS", "DESCRIPTION")
    elif defect == "empty_synopsis":
        text = text[:text.index("SYNOPSIS")] + "SYNOPSIS\n  "
    elif defect == "no_clause":
        text = text.replace("BE IT ENACTED BY", "COMMENTARY ABOUT")
    elif defect == "omitted_page":
        text = text.replace("Page 2 of 2", "Source page omitted")
    elif defect == "duplicate_page":
        text = text.replace("Page 2 of 2", "Page 1 of 2")
    elif defect == "quoted_own_block":
        text = body().replace("HOUSE BILL NO. 32", "HOUSE BILL NO. 99") + "\n" + text
    else:
        text = text.replace("Page 2 of 2", "Page 2 of 3")
    assert archive.printed_identity(text, context(), "application/pdf") is None


def test_build_load_archive_routing_and_complete_original_records(packet_source):
    source, originals, out = packet_source
    before = {p.relative_to(source).as_posix(): archive._binding(p)
              for p in source.rglob("*") if p.is_file()}
    manifest = build(source, out)
    views, contexts, artifacts, loaded = load_archive(out, originals)
    assert loaded == manifest
    assert manifest["counts"]["newly_covered_contexts"] == 2
    assert manifest["counts"]["text_views"] == 3
    assert pq.read_table(out / "context_inventory.parquet").equals(originals.slice(0, 2))
    assert len(contexts) == 2 and len(list(archive._rows(
        out / "source_document_dispositions.jsonl",
    ))) == 4
    candidates = pq.read_table(out / "candidate_dispositions.parquet").to_pylist()
    assert [r["original_target_context"] for r in candidates] == originals.slice(0, 3).to_pylist()
    assert candidates[-1]["n_retained_source_views"] == 0
    assert any(r["disposition"] == "ancillary_fiscal_note_not_bill_body" for r in archive._rows(
        out / "source_document_dispositions.jsonl",
    ))
    for view in views:
        path = view["source_members"]["text"]
        assert view["text"].encode("utf-8") == (out / path).read_bytes()
        assert view["raw_text_sha256"] == hashlib.sha256(view["text"].encode("utf-8")).hexdigest()
        assert view["raw_text_characters"] == len(view["text"])
        assert view["source_session"]["start_date"] == "2026-01-13"
        assert view["original_target_context"]["source_introduction_date"].startswith("2024-12")
        assert view["original_target_context"]["unknown_native_count"] is None
        assert view["source_version"]["version"]["date"] is None
        assert view["source_version"]["printed_year"] is None
        assert all(view[flag] is False for flag in archive.FLAGS)
        assert view["source_record"]["sponsors"][0]["party"] is None
        assert "Preserved source sponsor, not policy" not in view["text"]
    assert before == {p.relative_to(source).as_posix(): archive._binding(p)
                      for p in source.rglob("*") if p.is_file()}
    for name, binding in before.items():
        assert archive._binding(out / "source-evidence" / name) == binding
        assert artifacts["source-evidence/" + name] == binding["sha256"]
    with pytest.raises(ValueError, match="new nonoverlapping"):
        build(source, out)


def test_compact_sorted_capture_keys_preserve_unsorted_whole_original_contexts(packet_source):
    source, originals, out = packet_source
    ledger = list(archive._rows(source / "metadata/request_ledger.jsonl"))
    original_rows = originals.slice(0, 3).to_pylist()
    assert [row["identifier"] for row in original_rows] == ["HB 32", "SR 3", "HB 22"]
    compact_numbers = ["HB22", "HB32", "SR3"]
    assert parse_qs(urlsplit(ledger[0]["url"]).query) == {
        "keys": [",".join(
            f"DE:{number}:{archive.SESSION_IDENTIFIER}" for number in compact_numbers
        )],
    }
    build(source, out)
    _, contexts, _, _ = archive.load_billcommons(out)
    assert [row["bill_id"] for row in contexts] == [row["bill_id"] for row in original_rows[:2]]
    candidates = pq.read_table(out / "candidate_dispositions.parquet").to_pylist()
    assert [row["original_target_context"] for row in candidates] == original_rows
    assert [row["provider_bill_id"] for row in candidates] == [
        "provider:HB 32", "provider:SR 3", "provider:HB 22",
    ]
    assert [row["provider_document_count"] for row in candidates] == [3, 1, 0]


@pytest.mark.parametrize("defect", ["unsorted", "typed_number", "session", "ledger_url"])
def test_sorted_capture_query_remains_exactly_original_and_session_bound(packet_source, defect):
    source, _, out = packet_source
    path = source / "metadata/exchange-001.curl.json"
    curl = archive._json(path)
    keys = parse_qs(urlsplit(curl["url"]).query)["keys"][0].split(",")
    if defect == "unsorted":
        keys.reverse()
    elif defect == "typed_number":
        keys[0] = keys[0].replace("HB22:", "HB23:")
    elif defect == "session":
        keys[0] = keys[0].replace(archive.SESSION_IDENTIFIER, "2026")
    else:
        ledger_path = source / "metadata/request_ledger.jsonl"
        rows = list(archive._rows(ledger_path))
        rows[0]["url"] += "&changed=1"
        ledger_path.write_bytes(archive._row_bytes(rows))
    if defect != "ledger_url":
        url = archive.API + "/api/v1/bills/batch?" + urlencode({"keys": ",".join(keys)})
        curl["url"] = curl["url_effective"] = url
        write_json(path, curl)
        ledger_path = source / "metadata/request_ledger.jsonl"
        rows = list(archive._rows(ledger_path))
        rows[0]["url"] = url
        ledger_path.write_bytes(archive._row_bytes(rows))
    seal_source(source)
    message = ("request ledger/exchange binding" if defect == "ledger_url"
               else "batch original/session key")
    with pytest.raises(ValueError, match=message):
        build(source, out)
    assert not out.exists()


@pytest.mark.parametrize("defect", [
    "text", "original_date", "null", "approval", "version", "report", "disposition",
    "context", "producer", "jsonl_crlf", "jsonl_no_final_newline", "manifest_approval",
    "manifest_counts", "manifest_extra",
])
def test_rebound_exports_producer_and_manifest_rejected(packet_source, defect):
    source, _, out = packet_source
    build(source, out)
    name = "views.jsonl"
    rows = list(archive._rows(out / name))
    if defect == "text":
        rows[0]["text"] = rows[0]["text"][:-1]
    elif defect == "original_date":
        rows[0]["original_target_context"]["source_introduction_date"] = "2026-01-13"
    elif defect == "null":
        rows[0]["original_target_context"]["unknown_native_count"] = 0
    elif defect == "approval":
        rows[0]["source_rights_approved"] = True
    elif defect == "version":
        rows[0]["source_version"]["version"]["date"] = ""
    elif defect == "report":
        name = "report.json"
        value = archive._json(out / name)
        value["network_calls"] = 1
        write_json(out / name, value)
    elif defect == "disposition":
        name = "source_document_dispositions.jsonl"
        value = list(archive._rows(out / name))
        value[-2]["disposition"] = "accepted_fiscal_note"
        (out / name).write_bytes(archive._row_bytes(value))
    elif defect == "context":
        name = "context_inventory.parquet"
        value = pq.read_table(out / name).to_pylist()
        value[0]["source_introduction_date"] = "2026-01-13"
        pq.write_table(pa.Table.from_pylist(value), out / name)
    elif defect == "producer":
        name = "producer/billcommons_text.py"
        (out / name).write_bytes((out / name).read_bytes() + b"\n# rebound producer\n")
    elif defect == "jsonl_crlf":
        (out / name).write_bytes((out / name).read_bytes().replace(b"\n", b"\r\n"))
    elif defect == "jsonl_no_final_newline":
        (out / name).write_bytes((out / name).read_bytes()[:-1])
    elif defect.startswith("manifest"):
        value = archive._json(out / "manifest.json")
        if defect == "manifest_approval":
            value["approvals"]["scientific_approval"] = 1
        elif defect == "manifest_counts":
            value["counts"]["text_views"] = 999
        else:
            value["source_rights_approved"] = True
        write_json(out / "manifest.json", value)
    if defect in ("text", "original_date", "null", "approval", "version"):
        (out / name).write_bytes(archive._row_bytes(rows))
    if not defect.startswith("manifest"):
        repin(out, name)
    with pytest.raises(ValueError):
        archive.load_billcommons(out)


@pytest.mark.parametrize("defect", [
    "source_response", "source_manifest", "source_extra", "source_missing", "source_symlink",
    "source_hardlink", "output_hardlink", "output_extra", "queue", "source_anchor", "queue_anchor",
])
def test_sources_external_anchors_paths_and_original_queue_rejected(packet_source, defect):
    source, _, out = packet_source
    build(source, out)
    arguments = {}
    if defect == "source_response":
        name = "source-evidence/texts/exchange-001.body"
        (out / name).write_bytes(b"{}")
        repin(out, name)
    elif defect == "source_manifest":
        name = "source-evidence/manifest.json"
        value = archive._json(out / name)
        value["actual_GETs"] += 1
        write_json(out / name, value)
        repin(out, name)
    elif defect == "source_extra":
        (out / "source-evidence/texts/extra").write_bytes(b"unbound")
    elif defect == "source_missing":
        (out / "source-evidence/texts/exchange-001.stderr.log").unlink()
    elif defect in ("source_symlink", "source_hardlink", "output_hardlink"):
        path = out / ("views.jsonl" if defect == "output_hardlink"
                      else "source-evidence/texts/exchange-001.body")
        retained = out.parent / "retained"
        path.rename(retained)
        if defect == "source_symlink":
            path.symlink_to(retained)
        else:
            os.link(retained, path)
    elif defect == "output_extra":
        (out / "unbound").write_bytes(b"unbound")
    elif defect == "queue":
        name = "input_gap_queue.parquet"
        rows = pq.read_table(out / name).to_pylist()
        rows[0]["unknown_native_count"] = 0
        pq.write_table(pa.Table.from_pylist(rows), out / name)
        repin(out, name)
    else:
        arguments["source_manifest_sha256" if defect == "source_anchor" else "gap_queue_sha256"] = (
            "0" * 64
        )
    with pytest.raises(ValueError):
        archive.load_billcommons(out, **arguments)


@pytest.mark.parametrize("defect", [
    "foreignkey", "response_foreignkey", "char_count", "inventory_text", "context_null",
    "context_bool_type", "missing_download", "scope_approval", "root_approval",
    "batch", "extra_exchange", "dangling_exchange", "native_promotion", "partial",
    "fulltext_status",
])
def test_source_normalization_derives_from_actual_captured_records(packet_source, defect):
    source, _, out = packet_source
    if defect in ("partial", "foreignkey"):
        path = source / "metadata/exchange-003.body"
        full = archive._json(path)
        full["documents"][0]["text_is_partial" if defect == "partial" else "bill_version_id"] = (
            True if defect == "partial" else "foreign-version"
        )
        write_json(path, full)
        curl = archive._json(path.with_suffix(".curl.json"))
        curl["size_download"] = path.stat().st_size
        write_json(path.with_suffix(".curl.json"), curl)
        frontier = archive._json(source / "metadata/candidate_document_frontier.json")
        frontier[1]["documents"] = full["documents"]
        write_json(source / "metadata/candidate_document_frontier.json", frontier)
        if defect == "partial":
            inventory = archive._json(source / "texts/complete_text_inventory.json")
            inventory[0]["provider_document"] = full["documents"][0]
            write_json(source / "texts/complete_text_inventory.json", inventory)
    elif defect in ("response_foreignkey", "char_count", "fulltext_status"):
        path = source / "texts/exchange-001.body"
        response = archive._json(path)
        key, value = {
            "response_foreignkey": ("version_id", "foreign-version"),
            "char_count": ("char_count", 1), "fulltext_status": ("fulltext_status", "partial"),
        }[defect]
        response[key] = value
        write_json(path, response)
        curl = archive._json(path.with_suffix(".curl.json"))
        curl["size_download"] = path.stat().st_size
        write_json(path.with_suffix(".curl.json"), curl)
        inventory = archive._json(source / "texts/complete_text_inventory.json")
        inventory[0]["response_fields_preserved"][key] = value
        write_json(source / "texts/complete_text_inventory.json", inventory)
    elif defect == "inventory_text":
        path = source / "texts/complete-source-text-01.txt"
        path.write_bytes(path.read_bytes()[:-1])
        inventory = archive._json(source / "texts/complete_text_inventory.json")
        inventory[0]["complete_text"].update(archive._binding(path))
        write_json(source / "texts/complete_text_inventory.json", inventory)
    elif defect.startswith("context"):
        path = source / "metadata/exact_original_candidates.json"
        rows = archive._json(path)
        key = "unknown_native_count" if defect == "context_null" else "source_event_in_window"
        rows[0][key] = 0 if defect == "context_null" else 1
        write_json(path, rows)
    elif defect == "missing_download":
        path = source / "texts/complete_text_inventory.json"
        rows = archive._json(path)
        rows.pop()
        write_json(path, rows)
    elif defect == "batch":
        path = source / "metadata/batch_dispositions.json"
        value = archive._json(path)
        value["data"].pop()
        write_json(path, value)
    elif defect == "extra_exchange":
        exchange(source, "texts", 5, archive.API + "/unadvertised", b"{}")
    elif defect == "dangling_exchange":
        write_json(source / "texts/exchange-005.curl.json", {"method": "GET"})
    seal_source(source)
    if defect in ("scope_approval", "root_approval", "native_promotion"):
        path = source / (
            "metadata/manifest.json" if defect == "scope_approval" else "manifest.json"
        )
        value = archive._json(path)
        value["raw_publisher_PDF_or_HTML_bytes_supplied" if defect == "native_promotion"
              else "source_rights_approved"] = True
        write_json(path, value)
        if defect == "scope_approval":
            seal_source(source)
    if defect in ("partial", "fulltext_status"):
        build(source, out)
        views, _, _, _ = archive.load_billcommons(out)
        assert len(views) == 2
        assert not any(v["source_version"]["document"]["id"] == "document:1" for v in views)
    else:
        with pytest.raises(ValueError):
            build(source, out)
        assert not out.exists()


@pytest.mark.parametrize("shape", ["arrow", "rows", "indexed"])
def test_current_metadata_full_fields_and_missingness_types(packet_source, shape):
    source, originals, out = packet_source
    build(source, out)
    rows = originals.to_pylist()
    metadata = (originals if shape == "arrow" else rows if shape == "rows"
                else {r["bill_id"]: r for r in rows})
    assert len(archive.load_billcommons(out, metadata)[0]) == 3
    altered = copy.deepcopy(rows)
    altered[0]["source_unknown_flag"] = ""
    with pytest.raises(ValueError, match="missingness/type changed"):
        archive.load_billcommons(out, altered)
    with pytest.raises(ValueError, match="missing or duplicated"):
        archive.load_billcommons(out, [*rows, rows[0]])


@pytest.mark.parametrize("raw", [
    b'{"same":null,"same":null}', b'{"value":NaN}', b'{"value":Infinity}', b'{"value":1e999}',
    '{"value":null}'.encode("utf-16"),
])
def test_strict_unique_finite_utf8_json(raw):
    with pytest.raises((ValueError, UnicodeError)):
        archive._decode(raw)


def test_literal_jsonl_unicode_separators_and_crlf_source_preserved(tmp_path):
    path = tmp_path / "records.jsonl"
    value = {"text": "line\r\nU+2028:\u2028U+2029:\u2029final"}
    path.write_bytes(archive._row_bytes([value, value]))
    assert list(archive._rows(path)) == [value, value]
    path.write_bytes(b'{"value":1}\r\n')
    with pytest.raises(ValueError, match="literal-newline"):
        list(archive._rows(path))


def test_cli_finite_build_and_replay(packet_source, capsys):
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
    assert counts["newly_covered_contexts"] == 2 and counts["text_views"] == 3


def test_generic_archive_download_freezes_new_dependency(tmp_path, monkeypatch):
    import test_cycle_site

    bundle = test_cycle_site.cycle_bundle.__wrapped__(tmp_path)
    test_cycle_site.test_independent_archive_exports_preserve_provider_alternatives_and_full_text(
        bundle, tmp_path, monkeypatch, False,
    )
    assert (tmp_path / "archive-preview/downloads/producers/billcommons_text.py").read_bytes() == (
        Path(archive.__file__).read_bytes()
    )

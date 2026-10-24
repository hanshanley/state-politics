"""Bounded, strictly offline Nevada original-reference Bill Commons replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.robotparser import RobotFileParser

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from state_politics.bills import billcommons_text as frozen

SCHEMA = "state-politics.billcommons-nevada-archive-text.v1"
SOURCE_SCHEMA = "state-politics.billcommons-nevada-captures.v1"
PROFILE = "nv83_exact_original_document_reference"
SESSION_ID = "0d6be290-517b-4ae8-a46c-035cd8dc43c2"
SESSION_IDENTIFIER = "2025 Regular Session (83rd Session)"
DEPENDENCY_SHA256 = "42ad8a2ab6a1a866610c127b367e9077209c600dc1337eb8382364cfdeb78e5c"
EXTRACTION_SHA256 = "9a3555e5194ac3d45ab30c4107df4f720ad40f3ce85e040fa5336138d8ee8a29"
ORIGINAL_TABLES = {
    "bill_versions.parquet": {
        "sha256": "c3cbfdc7042756da9751f5d1201078701effb6d0a292e103394b1c869167ed31",
        "bytes": 68064911, "rows": 1899909,
    },
    "bill_version_links.parquet": {
        "sha256": "f1b66ed75244eaed64cc878f6074a33ce1b4e731cd8291489a6b77eca3b4f76f",
        "bytes": 133922540, "rows": 2617690,
    },
}

# Only these low-level helpers are reused; the frozen Delaware profile is never called.
require = frozen.require
_equal = frozen._equal
_decode = frozen._decode
_hash = frozen._hash
_relative = frozen._relative
_root = frozen._root
_regular = frozen._regular
_binding = frozen._binding
_tree = frozen._tree
_json = frozen._json
_json_bytes = frozen._json_bytes
_row_bytes = frozen._row_bytes
_rows = frozen._rows
_parquet_bytes = frozen._parquet_bytes
_unapproved = frozen._unapproved
_api_schema = frozen._api_schema
_span = frozen._span
FLAGS = frozen.FLAGS
TOOLS = frozen.TOOLS
API = frozen.API
TEXT_ROUTE = frozen.TEXT_ROUTE
FULL_ROUTE = frozen.FULL_ROUTE
PROVIDER = frozen.PROVIDER
STATUS = frozen.STATUS
PRODUCERS = {
    "billcommons_nv_text.py": Path(__file__).absolute(),
    "billcommons_text.py": Path(frozen.__file__).absolute(),
}
PRODUCTS = {
    "views.jsonl", "context_inventory.parquet", "candidate_dispositions.parquet",
    "source_document_dispositions.jsonl", "received_text_dispositions.jsonl",
    "input_gap_queue.parquet", "report.json", "source_inventory.json",
    "source_immutability.json", *("producer/" + name for name in PRODUCERS),
}
SCOPES = {"discovery", "openapi", "probe", "pilot", "metadata", "texts"}
EXACT = "exact_original_version_URL_complete_stored_text"


def _dependency():
    require(_binding(PRODUCERS["billcommons_text.py"])["sha256"] == DEPENDENCY_SHA256,
            "frozen generic dependency changed")


def _scope(source, relative, binding, depth=0):
    """Validate every prefix byte, including a stopped prefix's terminal response."""
    require(depth <= 4, "previous manifest chain ceiling")
    directory = _root(source / _relative(relative))
    require(_equal(_binding(directory / "manifest.json"), binding),
            "scope manifest binding changed")
    manifest = _json(directory / "manifest.json")
    _unapproved(manifest)
    artifacts = manifest["artifacts"]
    require(type(artifacts) is dict, "scope artifacts must be a mapping")
    names = {"manifest.json"}
    for name, expected in artifacts.items():
        _relative(name)
        require("/" not in name, "scope inventory must enumerate its own top-level files")
        require(_equal(_binding(directory / name), expected), "scope artifact changed")
        names.add(name)
    ledger = []
    if "previous_scope_manifest" in manifest:
        previous, prior_files, _ = _scope(
            source, relative + "/previous", manifest["previous_scope_manifest"], depth + 1,
        )
        names |= {"previous/" + name for name in prior_files}
        ledger.extend(previous)
    require(_tree(directory) == names, "scope inventory omissions or unexpected nested members")
    count = manifest["actual_GETs"]
    require(type(count) is int and 0 <= count <= 160, "scope physical GET ceiling")
    current = []
    for ordinal in range(1, count + 1):
        exchange = frozen._exchange(directory, ordinal)
        current.append({**exchange, "path": relative + "/" + exchange["path"],
                        "ordinal": ordinal})
    members = {
        Path(row["path"]).name.removesuffix(".body") + suffix
        for row in current for suffix in (".body", ".curl.json", ".headers", ".stderr.log")
    }
    require({name for name in artifacts if name.startswith("exchange-")} == members,
            "unaccounted or unpaired scope exchange")
    if "request_ledger.jsonl" in artifacts:
        requests = list(_rows(directory / "request_ledger.jsonl"))
        require(len(requests) == count, "request ledger physical count mismatch")
        for request, exchange in zip(requests, current, strict=True):
            prefix = Path(exchange["path"]).name.removesuffix(".body")
            expected = {
                prefix + suffix: _binding(directory / (prefix + suffix))
                for suffix in (".body", ".curl.json", ".headers", ".stderr.log")
            }
            require(_equal(request["ordinal"], exchange["ordinal"])
                    and request["url"] == exchange["url"] and request["method"] == "GET"
                    and _equal(request["returncode"], 0)
                    and _equal(request["status"], exchange["http_status"])
                    and _equal(request["artifacts"], expected),
                    "request ledger/raw physical exchange mismatch")
    ledger.extend(current)
    return ledger, names, manifest


def _source(source, expected_sha):
    _dependency()
    require(_binding(source / "manifest.json")["sha256"] == _hash(expected_sha),
            "caller-pinned source manifest changed")
    manifest = _json(source / "manifest.json")
    require(manifest["schema"] == SOURCE_SCHEMA
            and all(manifest.get(key) is False for key in (
                "source_admission", "scientific_approval", "publication",
            )), "closed unapproved Nevada source required")
    require(manifest.get("raw_publisher_PDF_or_HTML_bytes_supplied", False) is False,
            "stored extraction cannot be promoted to native publisher bytes")
    _unapproved(manifest)
    frozen._inventory(source, manifest["artifacts"])
    require(set(manifest["scopes"]) == SCOPES, "all six finite source scopes required")
    ledgers, directories, packets, total, scoped = {}, {}, {}, 0, set()
    for name in sorted(SCOPES):
        spec = manifest["scopes"][name]
        directory = _relative(spec["directory"])
        require("/" not in directory and directory not in directories.values(),
                "distinct top-level source scope directory required")
        ledger, members, packet = _scope(source, directory, spec["manifest"])
        require(_equal(spec["actual_GETs"], packet["actual_GETs"]),
                "scope suffix count changed")
        ledgers[name], directories[name] = ledger, directory
        packets[name] = packet
        scoped |= {directory + "/" + member for member in members}
        total += len(ledger)
    require(total <= 203 and _equal(manifest["actual_GETs"], total),
            "unique physical source dependency GET accounting mismatch")
    # Original tables and retained diagnostics may be top-level or under originals only.
    remaining = set(manifest["artifacts"]) - scoped
    require({"input_gap_queue.parquet", "originals/bill_extraction_manifest.json",
             *("originals/" + name for name in ORIGINAL_TABLES)} <= remaining
            and all("/" not in name or name.startswith("originals/") for name in remaining),
            "unscoped or missing original source evidence")
    before_probe = packets["probe"]["preceding_complete_publication_capture_GETs"]
    other_dependencies = before_probe - len(ledgers["discovery"]) - len(ledgers["openapi"])
    require(type(before_probe) is int and other_dependencies == 28
            and _equal(packets["pilot"]["preceding_publication_GETs"],
                       before_probe + len(ledgers["probe"]))
            and _equal(packets["texts"]["preceding_publication_GETs"],
                       before_probe + len(ledgers["probe"]) + len(ledgers["pilot"])
                       + len(ledgers["metadata"]))
            and _equal(packets["texts"]["expected_cumulative_publication_GETs"],
                       total + other_dependencies),
            "complete publication prefix/suffix accounting changed")
    accounting = {
        "unique_source_dependencies_GETs": total,
        "new_NV_metadata_text_GETs": len(ledgers["metadata"]) + len(ledgers["texts"]),
        "whole_publication_GETs": total + other_dependencies,
    }
    source_counters = {
        **accounting,
        "nested_preserved_metadata_prefix_GETs": (
            len(ledgers["metadata"]) - packets["metadata"]["actual_GETs"]
        ),
        "new_NV_metadata_and_text_GETs": accounting["new_NV_metadata_text_GETs"],
        "known_controlled_publication_GETs_including_separate_DE_scopes": (
            accounting["whole_publication_GETs"]
        ),
    }
    for key, value in source_counters.items():
        if key in manifest:
            require(_equal(manifest[key], value), "source accounting counter changed: " + key)
    if "original_complete_reference_tables" in manifest:
        require(_equal(manifest["original_complete_reference_tables"], {
            name: _binding(source / "originals" / name)
            for name in ("bill_extraction_manifest.json", *ORIGINAL_TABLES)
        }), "root original reference authority inventory changed")
    return manifest, ledgers, directories, accounting


def _response(source, exchange, url, route, document):
    require(exchange["url"] == url and exchange["http_status"] == 200,
            "raw API route/status foreign key mismatch")
    value = _json(source / _relative(exchange["path"]))
    schema = document["paths"][route]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    _api_schema(value, schema, document)
    _unapproved(value)
    return value


def _publication(source, ledgers, directories):
    discovery, api = ledgers["discovery"], ledgers["openapi"]
    require(4 <= len(discovery) <= 7 and len(api) == 2
            and discovery[0]["url"] == API + "/robots.txt"
            and discovery[0]["http_status"] == 404
            and discovery[1]["url"] == "https://billcommons.org/robots.txt"
            and discovery[1]["http_status"] == 200
            and discovery[2]["url"] == "https://billcommons.org/docs/api"
            and discovery[2]["http_status"] == 200
            and api[0]["url"] == API + "/docs" and api[0]["http_status"] == 200
            and api[1]["url"] == API + "/openapi.json" and api[1]["http_status"] == 200,
            "retained public API/robots publication evidence missing")
    robots = RobotFileParser()
    robots.parse((source / discovery[1]["path"]).read_bytes().decode("utf-8").split("\n"))
    require(all(robots.can_fetch(agent, url) for agent in (
        "GitHubCopilot-StatePoliticsResearch/1.0", "GPTBot",
    ) for url in ("https://billcommons.org/docs/api", "https://billcommons.org/robots.txt")),
        "retained robots policy disallows documentation")
    require("/openapi.json" in (source / api[0]["path"]).read_bytes().decode("utf-8"),
            "retained docs do not advertise OpenAPI")
    document = _json(source / api[1]["path"])
    for route, params in (
        ("/api/v1/sessions", set()), ("/api/v1/bills/batch", {"keys"}),
        (FULL_ROUTE, {"bill_id"}), (TEXT_ROUTE, {"bill_id", "document_id"}),
    ):
        method = document["paths"][route]["get"]
        require(params <= {p["name"] for p in method.get("parameters", [])}
                and "200" in method["responses"], "unadvertised public API method")
    sessions = []
    for page, exchange in enumerate(discovery[3:], 1):
        url = API + "/api/v1/sessions" + (f"?page={page}" if page != 1 else "")
        value = _response(source, exchange, url, "/api/v1/sessions", document)
        pagination = value["pagination"]
        require(_equal(pagination["page"], page)
                and _equal(pagination["total_pages"], len(discovery) - 3),
                "incomplete published session pagination")
        sessions.extend(value["data"])
    require(_equal(pagination["total"], len(sessions))
            and len({row["id"] for row in sessions}) == len(sessions)
            and _equal(sessions, _json(
                source / directories["discovery"] / "complete_session_metadata.json",
            )), "complete session inventory replay mismatch")
    session = _json(source / directories["metadata"] / "provider_session_preserved.json")
    require(_equal([r for r in sessions if r["id"] == SESSION_ID], [session])
            and session["identifier"] == SESSION_IDENTIFIER
            and session["jurisdiction_abbreviation"] == "NV",
            "explicit provider 83rd session changed")
    return document, session


def _originals(source, candidates, text_directory):
    original_dir = source / "originals"
    extraction = original_dir / "bill_extraction_manifest.json"
    require(_binding(extraction)["sha256"] == EXTRACTION_SHA256,
            "complete frozen extraction manifest changed")
    authority = _json(extraction)
    require(_equal(_binding(extraction), _binding(
        text_directory / "bill_extraction_manifest.json",
    )), "text scope extraction authority changed")
    bindings = _json(text_directory / "original_reference_bindings.json")
    require(set(bindings) == set(ORIGINAL_TABLES), "original reference bindings incomplete")
    ids = [row["bill_id"] for row in candidates]
    tables = {}
    for name, expected in ORIGINAL_TABLES.items():
        full_path = original_dir / name
        require(_equal(_binding(full_path), {k: expected[k] for k in ("sha256", "bytes")})
                and _equal(authority["artifacts"][name]["sha256"], expected["sha256"])
                and _equal(authority["artifacts"][name]["rows"], expected["rows"])
                and pq.ParquetFile(full_path).metadata.num_rows == expected["rows"],
                "complete national original reference authority changed")
        spec = bindings[name]
        require(_equal(spec["original_complete_table"], {
            "path": "data/processed/" + name,
            **{k: expected[k] for k in ("sha256", "bytes")},
        }) and _equal(spec["original_table_rows"], expected["rows"])
            and spec["complete_target_subset"]["path"] == name
            and _equal(_binding(text_directory / name), {
                k: spec["complete_target_subset"][k] for k in ("sha256", "bytes")
            }), "source query authority/subset binding mismatch")
        subset = pq.read_table(full_path, filters=[("bill_id", "in", ids)])
        supplied = pq.read_table(text_directory / name)
        require(subset.schema.equals(supplied.schema, check_metadata=True)
                and _equal(subset.to_pylist(), supplied.to_pylist())
                and _equal(spec["target_subset_rows"], subset.num_rows),
                "complete original query subset fields/order/schema mismatch")
        tables[name] = subset.to_pylist()
    versions = tables["bill_versions.parquet"]
    links = tables["bill_version_links.parquet"]
    by_version = {row["id"]: row for row in versions}
    require(len(by_version) == len(versions) and len({r["id"] for r in links}) == len(links)
            and len(versions) <= 143 and len(links) <= 143,
            "duplicate or unbounded original reference rows")
    require(all(row["version_id"] in by_version
                and by_version[row["version_id"]]["bill_id"] == row["bill_id"]
                and row["bill_id"] in ids for row in links),
            "original link/version/context foreign key mismatch")
    return by_version, links


def _metadata(source, ledgers, directories, candidates, session, document):
    metadata_dir = directories["metadata"]
    frontier = _json(source / metadata_dir / "complete_document_frontier.json")
    by_id = {row["bill_id"]: row for row in candidates}
    require(len(frontier) == len(candidates)
            and {r["original_context"]["bill_id"] for r in frontier} == by_id.keys()
            and all(_equal(r["original_context"], by_id[r["original_context"]["bill_id"]])
                    for r in frontier), "whole original frontier fields/nulls changed")
    originals = {frozen._typed_number(row["identifier"]): row for row in candidates}
    require(len(originals) == len(candidates), "duplicate typed original bill number")
    summaries, keys_seen, used = {}, [], set()
    for exchange in ledgers["metadata"]:
        if urlsplit(exchange["url"]).path != "/api/v1/bills/batch":
            continue
        query = parse_qs(urlsplit(exchange["url"]).query)
        require(set(query) == {"keys"} and len(query["keys"]) == 1,
                "original exact-session batch key query changed")
        keys = query["keys"][0].split(",")
        keys_seen.extend(keys)
        batch = _response(source, exchange, exchange["url"], "/api/v1/bills/batch", document)
        used.add(exchange["path"])
        require(_equal(batch["not_found"], []) and _equal(batch["ambiguous"], {})
                and len(batch["data"]) == len(keys)
                and sorted(keys) == sorted(
                    f"NV:{frozen._typed_number(bill['identifier'])}:{session['identifier']}"
                    for bill in batch["data"]
                ), "unresolved or foreign batch metadata dispositions")
        for bill in batch["data"]:
            number = frozen._typed_number(bill["identifier"])
            require(number in originals and number not in summaries,
                    "batch foreign or duplicate original typed number")
            summaries[number] = bill
    require(sorted(keys_seen) == sorted(
        f"NV:{number}:{session['identifier']}" for number in summaries
    ), "batch exact original/session coverage mismatch")
    available = {row["path"]: row for row in ledgers["metadata"]}
    pilot = ledgers["pilot"]
    records, offered, metadata_paths, reused_numbers = {}, {}, {}, set()
    for lead in frontier:
        context, bill = lead["original_context"], lead["provider_bill"]
        raw_path = metadata_dir + "/" + _relative(lead["complete_metadata_file"])
        url = API + f"/api/v1/bills/{bill['id']}/full"
        provenance = lead["capture_provenance"]
        if raw_path in available:
            exchange = available[raw_path]
            used.add(raw_path)
            expected_kind = ("preserved_prefix" if "/previous/" in raw_path else "new_suffix")
            require(_equal(provenance, {
                "captured_in": expected_kind, "original_exchange": exchange["ordinal"],
            }), "metadata prefix/suffix provenance changed")
        else:
            matches = [row for row in pilot if row["url"] == url
                       and _equal(row["binding"], _binding(source / raw_path))]
            require(len(matches) == 1 and _equal(provenance, {
                "captured_in": "original_pilot_reuse_not_new_request",
            }), "metadata reuse not byte-identical original pilot")
            exchange = matches[0]
            reused_numbers.add(frozen._typed_number(context["identifier"]))
        full = _response(source, exchange, url, FULL_ROUTE, document)
        require(_equal(bill, full["bill"]) and _equal(lead["versions"], full["versions"])
                and _equal(lead["documents"], full["documents"])
                and bill["id"] not in records and bill["session_id"] == session["id"]
                and bill["jurisdiction_id"] == session["jurisdiction_id"]
                and bill["jurisdiction_abbreviation"] == "NV"
                and bill["session_identifier"] == session["identifier"]
                and bill["identifier"] == context["identifier"],
                "provider full metadata/original/session identity mismatch")
        number = frozen._typed_number(context["identifier"])
        if number in summaries:
            summary = summaries[number]
            require(all(key in bill and _equal(bill[key], value)
                        for key, value in summary.items()), "batch/full provider metadata changed")
        else:
            require(number in reused_numbers, "original missing from batch and actual pilot reuse")
        versions = {row["id"]: row for row in full["versions"]}
        require(len(versions) == len(full["versions"])
                and all(row["bill_id"] == bill["id"] for row in versions.values()),
                "provider version foreign key mismatch")
        records[context["bill_id"]], metadata_paths[bill["id"]] = full, raw_path
        for attachment in full["documents"]:
            require(attachment["id"] not in offered
                    and attachment["bill_version_id"] in versions,
                    "provider document/version foreign key mismatch")
            offered[attachment["id"]] = (
                context, full, versions[attachment["bill_version_id"]], attachment,
            )
    require(len(offered) <= 350 and used == set(available)
            and summaries.keys() | reused_numbers == originals.keys(),
            "finite offered document ceiling or unaccounted metadata GET")
    return frontier, records, offered, metadata_paths


def _plan(frontier, versions, links):
    plan, dispositions = [], []
    for lead in frontier:
        context, bill = lead["original_context"], lead["provider_bill"]
        provider_versions = {row["id"]: row for row in lead["versions"]}
        for attachment in lead["documents"]:
            matches = [row for row in links if row["bill_id"] == context["bill_id"]
                       and row["url"] == attachment["url"]
                       and row["media_type"] == attachment["media_type"]]
            reason = (
                "not_an_exact_original_version_document_pointer" if not matches else
                "ambiguous_original_document_pointer" if len(matches) != 1 else
                "publisher_no_complete_stored_text" if not attachment["has_extracted_text"] else
                "publisher_partial_extraction_not_policy" if attachment["text_is_partial"] else
                EXACT
            )
            disposition = {
                "original_bill_id": context["bill_id"], "provider_bill_id": bill["id"],
                "provider_document": attachment, "disposition": reason,
                "original_reference_matches": matches,
            }
            dispositions.append(disposition)
            if reason == EXACT:
                plan.append({
                    **disposition, "original_context": context, "provider_bill": bill,
                    "provider_version": provider_versions[attachment["bill_version_id"]],
                    "original_version": versions[matches[0]["version_id"]],
                })
    require(len(plan) <= 143, "finite original document plan ceiling")
    return plan, dispositions


def _observe(text, context, media_type, version):
    if (type(text) is not str or context.get("state") != "NV"
            or context.get("session_identifier") != "83"
            or media_type not in ("application/pdf", "text/html")):
        return None, "unsupported_original_context_or_media"
    typed = re.fullmatch(r"(AB|SB) ([1-9]\d*)", context["identifier"])
    if not typed:
        return None, "unsupported_original_typed_number"
    if re.search(r"(?im)^[ \t]*(?:Amendment\s+No\.|(?:Senate|Assembly)\s+Amendment\s+to)",
                 text[:4000]) or re.match(r"Amendment\b", version["note"] or "", re.I):
        return None, "amendment_document_not_a_complete_formal_bill"
    if re.search(r"(?im)^[ \t]*(?:access denied|sign in|log in|create an account|"
                 r"testimony\b|testimony\s+(?:in|on)|submitted testimony)", text[:2500]):
        return None, "access_or_ancillary_page_not_a_bill"
    kind, number = typed.groups()
    formal = list(re.finditer(
        r"(?im)^[ \t]*(ASSEMBLY|SENATE)\s+BILL\s+NO\.?[ \t]*(\d+)\b", text,
    ))
    if not formal or formal[0].start() > 4000:
        return None, "missing_own_anchored_formal_bill_number"
    if any(("AB" if m[1].upper() == "ASSEMBLY" else "SB", m[2]) != (kind, number)
           for m in formal):
        return None, "contradictory_own_formal_bill_number"
    clauses = list(re.finditer(
        r"(?im)^[ \t]*THE PEOPLE OF THE STATE OF ([A-Z ]+?),[ \t]*REPRESENTED IN"
        r"(?:[ \t]+\d+)?\s+"
        r"SENATE AND ASSEMBLY,[ \t]*DO ENACT AS FOLLOWS:", text,
    ))
    if len(clauses) != 1 or clauses[0][1].upper() != "NEVADA":
        return None, "missing_or_contradictory_own_nevada_enacting_clause"
    clause = clauses[0]
    title_page = text[:clause.start()]
    short = list(re.finditer(
        r"(?im)^[ \t]*(?:(?:FIRST|SECOND|THIRD|FOURTH)\s+REPRINT[ \t]+)?"
        r"([AS])\.\s*B\.\s*(?:No\.\s*)?(\d+)\b", title_page,
    ))
    if any((m[1].upper() + "B", m[2]) != (kind, number) for m in short):
        return None, "contradictory_own_short_bill_number"
    states = re.findall(r"(?im)^[ \t]*(?:STATE|COMMONWEALTH) OF ([A-Z][A-Z ]+)[ \t]*$",
                        title_page)
    if any(state.strip().upper() != "NEVADA" for state in states):
        return None, "contradictory_own_state_header"
    sessions = list(re.finditer(
        r"(?im)^[ \t]*(?:-[ \t]*)?(\d+)(?:st|nd|rd|th)\s+Session\s*\((\d{4})\)",
        text,
    ))
    if any(m[1] != "83" or m[2] != "2025" for m in sessions):
        return None, "contradictory_own_session_header"
    reverse_sessions = list(re.finditer(
        r"(?im)^[ \t]*(\d{4})\s+Session\s*\((\d+)(?:st|nd|rd|th)\)", title_page,
    ))
    if any(m[1] != "2025" or m[2] != "83" for m in reverse_sessions):
        return None, "contradictory_own_session_header"
    caption = re.search(r"(?im)^[ \t]*AN ACT\b", title_page)
    section = re.search(r"(?im)^[ \t]*Section\s+1\.", text[clause.end():])
    if caption is None or caption.start() <= formal[0].end() or section is None:
        return None, "missing_complete_caption_or_operative_body"
    # Numeric suffixes are masked only for observations, never for the policy string.
    masked = re.sub(r"(?m)[ \t]+\d+[ \t]*(?=\r?$)",
                    lambda m: " " * len(m[0]), text)
    effective = re.search(
        r"\b(?:This\s+act|(?:Sections?[\s\S]{0,240}?)of\s+this\s+act)\s+"
        r"(?:becomes?|become)\s+effective\b", masked[clause.end():], re.I,
    )
    ending = re.search(r"(?m)^[ \t]*(?:H|20[ \t]+~+[ \t]+25)[ \t]*\s*\Z", text)
    if ending is None:
        return None, "missing_observed_original_body_ending"
    last_policy = masked[clause.end():ending.start()].rstrip()
    if not re.search(r"[.;:\])]$", last_policy):
        return None, "unterminated_observed_original_body"
    folios = list(re.finditer(r"(?m)^[ \t]*[–—-][ \t]+(\d+)[ \t]+[–—-][ \t]*\r?$",
                             text))
    if folios and [int(m[1]) for m in folios] != list(range(2, len(folios) + 2)):
        return None, "discontinuous_observed_printed_folios"
    signatures = list(re.finditer(
        r"(?m)^[ \t]*-[ \t]+\*((?:AB|SB))(\d+)(?:_R\d+)?\*[ \t]*\r?$", text,
    ))
    if any((m[1], m[2]) != (kind, number) for m in signatures):
        return None, "contradictory_own_printed_page_signature"
    if ((signatures and len(signatures) != len(folios) + 1)
            or (sessions and len(sessions) != len(folios) + 1)):
        return None, "discontinuous_observed_printed_folios_and_page_signatures"
    introduced = version["note"] == "As Introduced"
    prefiles = list(re.finditer(
        r"(?im)^[ \t]*PREFILED[ \t]+([A-Z]+)[ \t]+(\d{1,2}),[ \t]*(\d{4})",
        title_page,
    ))
    months = dict(zip((
        "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
        "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
    ), range(1, 13), strict=True))
    dates = []
    try:
        dates = [date(int(m[3]), months[m[1].upper()], int(m[2])).isoformat() for m in prefiles]
    except (KeyError, ValueError):
        return None, "invalid_own_printed_prefile_date"
    if (introduced and (len(prefiles) != 1 or dates[0] != context["source_introduction_date"])):
        return None, "introduced_printed_prefile_original_date_mismatch"
    summary = re.search(
        r"(?im)^[ \t]*SUMMARY[—–-](?P<summary>[\s\S]+?)(?=\n[ \t]*FISCAL NOTE:)", title_page,
    )
    bdr_pattern = r"\(\s*BDR\s+((?:\d+|S)-\d+)\s*\)"
    original_bdr = re.findall(bdr_pattern, context["title"])
    body_bdr = re.findall(bdr_pattern, summary["summary"]) if summary is not None else []
    if ((introduced and summary is None)
            or (summary is not None and (
                len(original_bdr) != 1 or body_bdr != original_bdr
            ))):
        return None, "printed_summary_bdr_original_reference_mismatch"
    evidence = [_span(text, formal[0]), _span(text, caption), _span(text, clause),
                *[_span(text, m) for m in prefiles]]
    if summary is not None:
        evidence.append(_span(text, summary))
    for match in sessions:
        evidence.append(_span(text, match))
    for match in reverse_sessions:
        evidence.append(_span(text, match))
    evidence.append(_span(text, ending))
    effective_evidence = None
    if effective is not None:
        start, end = effective.start() + clause.end(), effective.end() + clause.end()
        effective_evidence = {"start": start, "end": end, "text": text[start:end]}
    return {
        "state": "NV", "session_identifier": "83", "identifier": context["identifier"],
        "profile": PROFILE, "kind": "bill",
        "original_session_relation": "exact_original_bill_version_link_foreign_keys",
        "provider_session_identifier": SESSION_IDENTIFIER,
        "printed_year": (int(sessions[0][2]) if sessions else
                         int(reverse_sessions[0][1]) if reverse_sessions else None),
        "printed_prefile_dates": dates, "printed_evidence": evidence,
        "printed_summary_matches_original_title": (
            " ".join(summary["summary"].split()) == " ".join(context["title"].split())
            if summary is not None else None
        ),
        "printed_bdr_matches_original_title": True if summary is not None else None,
        "printed_effective_clause_evidence": effective_evidence,
        "printed_page_evidence": [_span(text, m) for m in folios],
        "observed_printed_folio_sequence_contiguous": True if folios else None,
        "raw_publisher_pages_or_originality_verified": False,
        "inference_text_start": 0, "inference_text_end": len(text),
    }, "complete_stored_extraction_exact_original_document_reference"


def printed_identity(text, context, media_type, original_version):
    """Return literal identity witnesses, not native/filing-time certification."""
    return _observe(text, context, media_type, original_version)[0]


def _replay(source, queue_path, source_sha, queue_sha):
    manifest, ledgers, directories, accounting = _source(source, source_sha)
    require(_binding(queue_path)["sha256"] == _hash(queue_sha)
            and _equal(_binding(queue_path), manifest["input_gap_queue"])
            and _equal(_binding(queue_path), _binding(source / "input_gap_queue.parquet")),
            "complete original gap queue changed")
    queue = pq.read_table(queue_path)
    originals = queue.to_pylist()
    require(len(originals) <= 18332 and all(type(r["bill_id"]) is str for r in originals)
            and len({r["bill_id"] for r in originals}) == len(originals),
            "duplicate/untyped or unbounded original contexts")
    candidates = [r for r in originals if r["state"] == "NV" and r["session_identifier"] == "83"]
    require(0 < len(candidates) <= 40
            and all(r["bill_id"].startswith("ocd-bill/") for r in candidates)
            and _equal(candidates, _json(
                source / directories["metadata"] / "exact_original_candidates.json",
            )), "whole original candidate fields/nulls/types changed")
    _unapproved(candidates)
    document, session = _publication(source, ledgers, directories)
    texts = source / directories["texts"]
    versions, links = _originals(source, candidates, texts)
    frontier, records, offered, metadata_paths = _metadata(
        source, ledgers, directories, candidates, session, document,
    )
    plan, offered_dispositions = _plan(frontier, versions, links)
    require(_equal(plan, _json(texts / "exact_original_document_plan.json"))
            and _equal(offered_dispositions, _json(texts / "complete_document_dispositions.json")),
            "exact original URL plan or all-offered dispositions changed")
    inventory = _json(texts / "complete_text_inventory.json")
    require(len(inventory) == len(plan), "actual received text inventory incomplete")
    new_exchanges = {row["ordinal"]: row for row in ledgers["texts"]}
    seen_gets, seen_reuses, views, dispositions, counts = set(), set(), [], [], {}
    for capture, expected in zip(inventory, plan, strict=True):
        require(_equal({key: capture[key] for key in expected}, expected),
                "captured original/provider/version/link fields changed")
        context = expected["original_context"]
        attachment = expected["provider_document"]
        provider_version = expected["provider_version"]
        original_version = expected["original_version"]
        full = records[context["bill_id"]]
        provenance = capture["capture_provenance"]
        response_path = directories["texts"] + "/" + _relative(provenance["response_file"])
        url = API + f"/api/v1/bills/{full['bill']['id']}/documents/{attachment['id']}/text"
        if provenance["kind"] == "new_exact_document_GET":
            ordinal = provenance["ordinal"]
            require(type(ordinal) is int and ordinal in new_exchanges and ordinal not in seen_gets,
                    "unknown/duplicate actual text GET")
            exchange = new_exchanges[ordinal]
            require(response_path == exchange["path"], "text response ordinal/path mismatch")
            seen_gets.add(ordinal)
        else:
            require(provenance["kind"] == "original_pilot_reuse_no_request"
                    and _equal(provenance["source_manifest"], _binding(
                        source / directories["pilot"] / "manifest.json",
                    )), "unknown or rebound text reuse")
            matches = [row for row in ledgers["pilot"] if row["url"] == url
                       and _equal(row["binding"], _binding(source / response_path))]
            require(len(matches) == 1 and matches[0]["path"] not in seen_reuses,
                    "text reuse not unique byte-identical pilot response")
            exchange = matches[0]
            seen_reuses.add(exchange["path"])
        response = _response(source, exchange, url, TEXT_ROUTE, document)
        text = response["extracted_text"]
        fields = {key: value for key, value in response.items() if key != "extracted_text"}
        complete = capture["complete_text"]
        text_path = _relative(complete["path"])
        require(type(text) is str and _equal(fields, capture["response_fields_preserved"])
                and response["document_id"] == attachment["id"]
                and response["bill_id"] == full["bill"]["id"]
                and response["version_id"] == provider_version["id"]
                and type(response["char_count"]) is int
                and response["char_count"] == len(text)
                and _equal(capture["full_characters"], len(text))
                and _equal(_binding(texts / text_path), {
                    key: complete[key] for key in ("sha256", "bytes")
                }) and (texts / text_path).read_bytes() == text.encode("utf-8"),
                "whole actual UTF8 text/response/foreign key mismatch")
        identity = None
        if (attachment["has_extracted_text"] is not True
                or attachment["text_is_partial"] is not False):
            reason = "provider_partial_or_unavailable_extraction_not_a_fill"
        elif response.get("fulltext_status") != "ok":
            reason = "provider_fulltext_status_not_complete_not_a_fill"
        else:
            identity, reason = _observe(text, context, attachment["media_type"], original_version)
        disposition = {**capture, "disposition": reason}
        if identity is not None:
            view_id = f"billcommons-nv:{attachment['id']}:context:{context['bill_id']}"
            original_link = expected["original_reference_matches"][0]
            counts[context["bill_id"]] = counts.get(context["bill_id"], 0) + 1
            identity["original_version"] = original_version
            identity["original_link"] = original_link
            views.append({
                "view_id": view_id, "source_type": "archive_text",
                **{key: context[key] for key in (
                    "bill_id", "state", "identifier", "session_identifier", "title",
                )},
                "text": text, "raw_text_characters": len(text),
                "raw_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "source_record": full, "source_identity": identity,
                "source_version": {
                    "version": provider_version, "document": attachment,
                    "link": original_link, "original_version": original_version,
                    "printed_year": identity["printed_year"], "kind": "bill",
                },
                "source_session": session, "original_target_context": context,
                "source_members": {
                    "metadata": "source-evidence/" + metadata_paths[full["bill"]["id"]],
                    "response": "source-evidence/" + response_path,
                    "text": "source-evidence/" + directories["texts"] + "/" + text_path,
                    "original_queue": "input_gap_queue.parquet",
                    "original_versions": "source-evidence/originals/bill_versions.parquet",
                    "original_links": "source-evidence/originals/bill_version_links.parquet",
                },
                "archive_provider": PROVIDER, "source_status": STATUS,
                "source_profile": PROFILE, "archive_generated_prologue_preserved": False,
                "inference_text_start": 0, "inference_text_end": len(text),
                "raw_publisher_PDF_or_HTML_bytes_supplied": False,
                "independent_reader_truth_or_reextraction_asserted": False,
                "provider_dates_preserved_not_original_context_overrides": True,
                **dict.fromkeys(FLAGS, False),
            })
            disposition.update(view_id=view_id, source_identity=identity)
        dispositions.append(disposition)
    require(seen_gets == set(new_exchanges), "unaccounted actual text GET")
    candidate_rows = [
        {"original_target_context": row,
         "provider_bill_id": records[row["bill_id"]]["bill"]["id"],
         "provider_document_count": len(records[row["bill_id"]]["documents"]),
         "n_retained_source_views": counts.get(row["bill_id"], 0),
         "disposition": ("retained_independent_stored_extraction" if row["bill_id"] in counts
                         else "no_accepted_complete_body_original_context_preserved")}
        for row in candidates
    ]
    contexts = queue.filter(pc.is_in(
        queue["bill_id"], value_set=pa.array(list(counts), type=pa.string()),
    ))
    report = {
        "status": STATUS, "provider": PROVIDER, "profile": PROFILE,
        "source_manifest_sha256": source_sha, "original_gap_queue_sha256": queue_sha,
        "counts": {
            "original_gap_contexts": len(originals), "source_candidate_contexts": len(candidates),
            "newly_covered_contexts": len(counts), "text_views": len(views),
            "source_document_dispositions": len(offered_dispositions),
            "received_text_dispositions": len(dispositions),
            "full_received_text_characters": sum(row["full_characters"] for row in inventory),
            "unrequested_offered_documents": len(offered_dispositions) - len(plan),
            "rejected_received_texts": len(dispositions) - len(views),
            "introduced_text_views": sum(
                v["source_version"]["original_version"]["note"] == "As Introduced" for v in views
            ),
            "contexts_with_introduced_text": len({
                v["bill_id"] for v in views
                if v["source_version"]["original_version"]["note"] == "As Introduced"
            }),
            "original_version_rows": len(versions), "original_link_rows": len(links),
            "full_retained_text_characters": sum(len(v["text"]) for v in views),
            "remaining_unavailable_from_this_source": len(originals) - len(counts),
            "actual_GETs_previously_captured": manifest["actual_GETs"],
            "actual_pilot_text_reuses_not_recounted": len(seen_reuses),
            **accounting,
        },
        "provider_session": session, "all_original_fields_nulls_types_and_dates_preserved": True,
        "received_text_disposition_counts": dict(Counter(
            row["disposition"] for row in dispositions
        )),
        "raw_publisher_PDF_or_HTML_bytes_supplied": False,
        "observed_folios_not_unavailable_raw_pdf_page_truth": True,
        "provider_session_dates_not_original_context_overrides": True,
        "network_calls": 0, "encoder_calls": 0, "approvals": dict.fromkeys(FLAGS, False),
    }
    return {
        "views.jsonl": views, "source_document_dispositions.jsonl": offered_dispositions,
        "received_text_dispositions.jsonl": dispositions,
    }, (contexts, pa.Table.from_pylist(candidate_rows)), report


def _exports(products, tables, report):
    contexts, candidates = tables
    return {
        **{name: _row_bytes(rows) for name, rows in products.items()},
        "context_inventory.parquet": _parquet_bytes(contexts),
        "candidate_dispositions.parquet": _parquet_bytes(candidates),
        "report.json": _json_bytes(report),
    }


def build_billcommons_nv(source_directory, gap_queue, out_directory, *,
                        source_manifest_sha256, gap_queue_sha256):
    source, queue = _root(source_directory), _regular(Path(gap_queue).absolute())
    out = Path(out_directory).absolute()
    require(not out.exists() and out.resolve() == out and not out.is_symlink()
            and not out.is_relative_to(source) and not source.is_relative_to(out)
            and not queue.is_relative_to(out), "new nonoverlapping output directory required")
    source_sha, queue_sha = _hash(source_manifest_sha256), _hash(gap_queue_sha256)
    source_manifest, _, _, _ = _source(source, source_sha)
    names = set(source_manifest["artifacts"]) | {"manifest.json"}
    before = {name: _binding(source / name) for name in sorted(names)}
    queue_before = _binding(queue)
    producers = {name: _binding(path) for name, path in PRODUCERS.items()}
    products, tables, report = _replay(source, queue, source_sha, queue_sha)
    out.mkdir(parents=True)
    for name in sorted(names):
        target = out / "source-evidence" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    shutil.copyfile(queue, out / "input_gap_queue.parquet")
    for name, raw in _exports(products, tables, report).items():
        (out / name).write_bytes(raw)
    after = {name: _binding(source / name) for name in sorted(names)}
    require(_tree(source) == names and _equal(before, after)
            and _equal(queue_before, _binding(queue))
            and _equal(producers, {name: _binding(path) for name, path in PRODUCERS.items()}),
            "source/queue/producer changed during normalization")
    (out / "source_inventory.json").write_bytes(_json_bytes(before))
    (out / "source_immutability.json").write_bytes(_json_bytes({
        "before": before, "after": after, "original_queue_before": queue_before,
        "original_queue_after": queue_before, "all_original_inputs_unchanged": True,
    }))
    (out / "producer").mkdir()
    for name, path in PRODUCERS.items():
        shutil.copyfile(path, out / "producer" / name)
    result = {
        "schema": SCHEMA, "provider": PROVIDER, "status": STATUS, "profile": PROFILE,
        "tools": TOOLS, "source_manifest_sha256": source_sha, "gap_queue_sha256": queue_sha,
        "approvals": dict.fromkeys(FLAGS, False), "counts": report["counts"],
        "packet_artifacts": {name: _binding(out / name) for name in sorted(
            PRODUCTS | {"source-evidence/" + name for name in names}
        )},
    }
    (out / "manifest.json").write_bytes(_json_bytes(result))
    load_billcommons_nv(out, source_manifest_sha256=source_sha, gap_queue_sha256=queue_sha)
    return result


def load_billcommons_nv(directory, metadata=None, *,
                       source_manifest_sha256=None, gap_queue_sha256=None):
    _dependency()
    root = _root(directory)
    manifest = _json(root / "manifest.json")
    require(set(manifest) == {
        "schema", "provider", "status", "profile", "tools", "source_manifest_sha256",
        "gap_queue_sha256", "approvals", "counts", "packet_artifacts",
    } and manifest["schema"] == SCHEMA and manifest["profile"] == PROFILE
        and manifest["provider"] == PROVIDER and manifest["status"] == STATUS
        and _equal(manifest["tools"], TOOLS)
        and _equal(manifest["approvals"], dict.fromkeys(FLAGS, False)),
        "normalized Nevada schema/profile/tools/approval mismatch")
    for key, external in (("source_manifest_sha256", source_manifest_sha256),
                          ("gap_queue_sha256", gap_queue_sha256)):
        _hash(manifest[key])
        if external is not None:
            require(manifest[key] == _hash(external), "external source or queue anchor changed")
    artifacts = manifest["packet_artifacts"]
    require(type(artifacts) is dict and _tree(root) == set(artifacts) | {"manifest.json"}
            and artifacts.keys() >= PRODUCTS, "normalized inventory omissions or extra members")
    pins = {"manifest.json": _binding(root / "manifest.json")["sha256"]}
    for name, value in artifacts.items():
        _relative(name)
        require(_equal(_binding(root / name), value), "normalized artifact changed: " + name)
        pins[name] = value["sha256"]
    require(all(_equal(artifacts["producer/" + name], _binding(path))
                for name, path in PRODUCERS.items()), "installed/archived producer mismatch")
    source = _root(root / "source-evidence")
    source_manifest, _, _, _ = _source(source, manifest["source_manifest_sha256"])
    names = set(source_manifest["artifacts"]) | {"manifest.json"}
    require(set(artifacts) == PRODUCTS | {"source-evidence/" + name for name in names},
            "unexpected normalized/source inventory")
    inventory = {name: _binding(source / name) for name in sorted(names)}
    queue_binding = _binding(root / "input_gap_queue.parquet")
    receipts = {
        "source_inventory.json": inventory,
        "source_immutability.json": {
            "before": inventory, "after": inventory, "original_queue_before": queue_binding,
            "original_queue_after": queue_binding, "all_original_inputs_unchanged": True,
        },
    }
    products, tables, report = _replay(
        source, root / "input_gap_queue.parquet",
        manifest["source_manifest_sha256"], manifest["gap_queue_sha256"],
    )
    for name, raw in {
        **_exports(products, tables, report),
        **{name: _json_bytes(value) for name, value in receipts.items()},
    }.items():
        require((root / name).read_bytes() == raw, "full " + name + " replay mismatch")
    require(_equal(manifest["counts"], report["counts"]), "manifest counts replay mismatch")
    contexts = tables[0].to_pylist()
    if metadata is not None:
        if isinstance(metadata, dict):
            require(all(type(row) is dict and row.get("bill_id") == key
                        for key, row in metadata.items()), "current metadata index/ID mismatch")
            current = list(metadata.values())
        else:
            current = metadata.to_pylist() if isinstance(metadata, pa.Table) else list(metadata)
        by_id = {}
        for row in current:
            require(type(row) is dict and type(row.get("bill_id")) is str,
                    "typed current metadata row/bill_id required")
            by_id.setdefault(row["bill_id"], []).append(row)
        for row in contexts:
            matches = by_id.get(row["bill_id"], [])
            require(len(matches) == 1, "matched original context missing or duplicated")
            require(all(key in matches[0] for key in (
                "bill_id", "state", "identifier", "session_identifier",
            )) and all(_equal(row[key], value)
                       for key, value in matches[0].items() if key in row),
                "original metadata field or missingness/type changed")
    return products["views.jsonl"], contexts, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--source-dir", type=Path, required=True)
    build.add_argument("--source-manifest-sha256", required=True)
    build.add_argument("--gap-queue", type=Path, required=True)
    build.add_argument("--gap-queue-sha256", required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    verify = commands.add_parser("verify", aliases=["replay"])
    verify.add_argument("--directory", type=Path, required=True)
    verify.add_argument("--metadata", type=Path)
    verify.add_argument("--source-manifest-sha256")
    verify.add_argument("--gap-queue-sha256")
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_billcommons_nv(
            args.source_dir, args.gap_queue, args.out_dir,
            source_manifest_sha256=args.source_manifest_sha256,
            gap_queue_sha256=args.gap_queue_sha256,
        )
    else:
        metadata = pq.read_table(args.metadata) if args.metadata else None
        _, _, _, manifest = load_billcommons_nv(
            args.directory, metadata, source_manifest_sha256=args.source_manifest_sha256,
            gap_queue_sha256=args.gap_queue_sha256,
        )
    print(json.dumps(manifest["counts"], indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

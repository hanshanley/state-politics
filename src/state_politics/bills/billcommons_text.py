"""Strict offline replay of independently stored Bill Commons Delaware extractions."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import shutil
import stat
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit
from urllib.robotparser import RobotFileParser

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

SCHEMA = "state-politics.billcommons-archive-text.v1"
SOURCE_SCHEMA = "state-politics.billcommons-captures.v1"
PROVIDER = "Bill Commons"
STATUS = "independent_stored_extraction_not_native_original_or_filing_certified"
SESSION_ID = "d7f8e36c-b8dd-4b8a-a38b-42501413c11f"
SESSION_IDENTIFIER = "2025-2026 Regular Session (153rd General Assembly)"
FLAGS = (
    "scientific_approval", "model_input_approved", "training_approved",
    "training_admission", "publication_approved", "party_attribution_approved",
    "filing_time_text_certified", "analytical_admission", "publisher_original_verified",
    "native_original_verified", "native_identity_certified", "source_rights_approved",
    "rights_approved", "canonical_population_admission", "source_date_or_party_inferred",
    "source_admission", "publication",
)
TOOLS = {"python": platform.python_version(), "pyarrow": pa.__version__}
PRODUCTS = {
    "views.jsonl", "context_inventory.parquet", "candidate_dispositions.parquet",
    "source_document_dispositions.jsonl", "input_gap_queue.parquet", "report.json",
    "source_inventory.json", "source_immutability.json", "producer/billcommons_text.py",
}
API = "https://api.billcommons.org"
TEXT_ROUTE = "/api/v1/bills/{bill_id}/documents/{document_id}/text"
FULL_ROUTE = "/api/v1/bills/{bill_id}/full"


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible Bill Commons archive: {message}")


def _equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"incompatible Bill Commons archive: nonfinite JSON {value}")

    # Decode explicitly: json.loads(bytes) otherwise accepts UTF-16/UTF-32.
    result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)

    def finite(value):
        if isinstance(value, float):
            require(math.isfinite(value), "nonfinite JSON number")
        elif isinstance(value, dict):
            for item in value.values():
                finite(item)
        elif isinstance(value, list):
            for item in value:
                finite(item)

    finite(result)
    return result


def _hash(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "invalid SHA256")
    return value


def _relative(name):
    require(type(name) is str and name and "\\" not in name and "\0" not in name,
            "invalid artifact path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts and path.as_posix() == name
            and name != "." and ":" not in path.parts[0], "unsafe artifact path")
    return name


def _root(value):
    path = Path(value).absolute()
    require(path.is_dir() and not path.is_symlink() and path.resolve() == path,
            "unlinked existing packet root required")
    return path


def _regular(path):
    require(path.resolve() == path and not path.is_symlink(), "linked artifact")
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError(f"incompatible Bill Commons archive: missing artifact: {path}") from exc
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "nonregular artifact")
    return path


def _binding(path):
    _regular(path)
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": sha, "bytes": path.stat().st_size}


def _tree(root):
    files, pending = set(), [root]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            require(not path.is_symlink() and path.resolve() == path, "linked packet member")
            if path.is_dir():
                require(len(path.relative_to(root).parts) <= 12, "packet depth ceiling")
                pending.append(path)
            else:
                _regular(path)
                files.add(path.relative_to(root).as_posix())
                require(len(files) <= 10000, "packet inventory ceiling")
    return files


def _json(path):
    return _decode(_regular(path).read_bytes())


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def _row_bytes(rows):
    return b"".join(
        (json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        for row in rows
    )


def _rows(path):
    raw = _regular(path).read_bytes()
    require(not raw or raw.endswith(b"\n"), "JSONL record missing literal newline")
    for line in raw.split(b"\n")[:-1]:
        require(line and not line.endswith(b"\r"), "blank or nonliteral-newline JSONL record")
        yield _decode(line)


def _parquet_bytes(table):
    output = pa.BufferOutputStream()
    pq.write_table(table, output)
    return output.getvalue().to_pybytes()


def _unapproved(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FLAGS or any(key == "snapshot_" + flag for flag in FLAGS):
                require(item is False, f"approval promotion: {key}")
            _unapproved(item)
    elif isinstance(value, list):
        for item in value:
            _unapproved(item)


def _inventory(root, artifacts):
    require(type(artifacts) is dict and _tree(root) == set(artifacts) | {"manifest.json"},
            "source inventory omissions or extra members")
    for name, binding in artifacts.items():
        _relative(name)
        require(_equal(_binding(root / name), binding), f"source artifact changed: {name}")


def _exchange(scope, ordinal):
    matches = [
        path for path in scope.glob("exchange-*.body")
        if re.fullmatch(r"exchange-0*" + str(ordinal) + r"\.body", path.name)
    ]
    require(type(ordinal) is int and ordinal > 0 and len(matches) == 1,
            "missing/ambiguous captured exchange")
    body = _regular(matches[0])
    stem = body.with_suffix("")
    curl = _json(stem.with_suffix(".curl.json"))
    headers = _regular(stem.with_suffix(".headers")).read_bytes()
    _regular(stem.with_suffix(".stderr.log"))
    url = curl["url_effective"]
    parts = urlsplit(url)
    require(parts.scheme == "https" and parts.netloc in (
        "api.billcommons.org", "billcommons.org",
    ) and not parts.username and not parts.password and not parts.fragment
        and curl["url"] == url and curl["method"] == "GET"
        and type(curl["num_redirects"]) is int and curl["num_redirects"] == 0
        and type(curl["exitcode"]) is int and curl["exitcode"] == 0
        and type(curl["http_code"]) is int
        and _equal(curl["http_code"], curl["response_code"])
        and type(curl["size_download"]) is int
        and curl["size_download"] == body.stat().st_size,
        "incomplete/redirected/nonpublic captured GET")
    statuses = re.findall(rb"(?m)^HTTP/\S+\s+(\d{3})", headers)
    require(statuses and int(statuses[-1]) == curl["http_code"],
            "HTTP response headers/status mismatch")
    return {"path": body.name, "url": url, "http_status": curl["http_code"],
            "binding": _binding(body)}


def _source(source, expected_sha):
    require(_binding(source / "manifest.json")["sha256"] == _hash(expected_sha),
            "caller-pinned source manifest changed")
    manifest = _json(source / "manifest.json")
    require(manifest["schema"] == SOURCE_SCHEMA and manifest["source_admission"] is False
            and manifest["scientific_approval"] is False and manifest["publication"] is False,
            "closed unapproved source packet required")
    require(manifest.get("raw_publisher_PDF_or_HTML_bytes_supplied", False) is False,
            "stored extractions cannot become native publisher originals")
    _unapproved(manifest)
    _inventory(source, manifest["artifacts"])
    require(set(manifest["scopes"]) == {"discovery", "openapi", "metadata", "texts"},
            "all four complete source scopes required")
    total, names, exchanges = 0, {"input_gap_queue.parquet"}, {}
    for name, spec in manifest["scopes"].items():
        require(spec["directory"] == name, "source scope directory changed")
        scope = _root(source / name)
        require(_equal(_binding(scope / "manifest.json"), spec["manifest"]),
                "source scope manifest changed")
        packet = _json(scope / "manifest.json")
        _unapproved(packet)
        _inventory(scope, packet["artifacts"])
        count = spec["actual_GETs"]
        require(type(count) is int and count > 0 and _equal(count, packet["actual_GETs"]),
                "scope GET accounting mismatch")
        ledger = [_exchange(scope, i) for i in range(1, count + 1)]
        require({row["path"] for row in ledger}
                == {p.name for p in scope.glob("exchange-*.body")},
                "unaccounted captured response")
        exchange_members = {
            row["path"].removesuffix(".body") + suffix
            for row in ledger for suffix in (".body", ".curl.json", ".headers", ".stderr.log")
        }
        require({member for member in packet["artifacts"] if member.startswith("exchange-")}
                == exchange_members, "unpaired captured exchange artifacts")
        if "request_ledger.jsonl" in packet["artifacts"]:
            requests = list(_rows(scope / "request_ledger.jsonl"))
            require(len(requests) == count, "retained request ledger count mismatch")
            for ordinal, (request, exchange) in enumerate(zip(requests, ledger, strict=True), 1):
                prefix = exchange["path"].removesuffix(".body")
                bindings = {
                    prefix + suffix: _binding(scope / (prefix + suffix))
                    for suffix in (".body", ".curl.json", ".headers", ".stderr.log")
                }
                require(_equal(request["ordinal"], ordinal)
                        and request["url"] == exchange["url"] and request["method"] == "GET"
                        and _equal(request["returncode"], 0)
                        and _equal(request["status"], exchange["http_status"])
                        and _equal(request["artifacts"], bindings),
                        "retained request ledger/exchange binding mismatch")
        require(len({row["url"] for row in ledger}) == count, "duplicate source GET")
        exchanges[name] = ledger
        total += count
        names |= {f"{name}/{member}" for member in set(packet["artifacts"]) | {"manifest.json"}}
    members = set(manifest["artifacts"])
    require(type(manifest["actual_GETs"]) is int and manifest["actual_GETs"] == total
            and names <= members
            and all(len(PurePosixPath(name).parts) == 1 for name in members - names),
            "aggregate source inventory/GET mismatch")
    return manifest, exchanges


def _api_schema(value, schema, document):
    if "$ref" in schema:
        ref = schema["$ref"]
        require(ref.startswith("#/components/schemas/"), "nonlocal API schema reference")
        return _api_schema(value, document["components"]["schemas"][ref.rsplit("/", 1)[1]],
                           document)
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                _api_schema(value, option, document)
                return
            except ValueError:
                pass
        require(False, "captured API response violates anyOf schema")
    for option in schema.get("allOf", []):
        _api_schema(value, option, document)
    kinds = {"object": dict, "array": list, "string": str, "integer": int,
             "boolean": bool, "null": type(None)}
    kind = schema.get("type")
    if kind == "number":
        require(type(value) in (int, float), "captured API numeric type mismatch")
    elif kind:
        require(kind in kinds and type(value) is kinds[kind], "captured API typed schema mismatch")
    if "enum" in schema:
        require(any(_equal(value, item) for item in schema["enum"]), "API enum mismatch")
    if isinstance(value, dict):
        require(set(schema.get("required", [])) <= value.keys(), "API required fields missing")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _api_schema(item, properties[key], document)
            elif schema.get("additionalProperties") is False:
                require(False, "API unexpected field")
            elif isinstance(schema.get("additionalProperties"), dict):
                _api_schema(item, schema["additionalProperties"], document)
    if isinstance(value, list):
        for item in value:
            _api_schema(item, schema.get("items", {}), document)


def _api_response(source, scope, exchange, url, route, document):
    require(exchange["url"] == url and exchange["http_status"] == 200,
            "captured response URL/status foreign key mismatch")
    value = _json(source / scope / exchange["path"])
    method = document["paths"][route]["get"]
    schema = method["responses"]["200"]["content"]["application/json"]["schema"]
    _api_schema(value, schema, document)
    return value


def _publication_evidence(source, exchanges):
    discovery, api = exchanges["discovery"], exchanges["openapi"]
    require(len(discovery) >= 4 and len(api) == 2
            and discovery[0]["url"] == API + "/robots.txt"
            and discovery[0]["http_status"] == 404
            and discovery[1]["url"] == "https://billcommons.org/robots.txt"
            and discovery[1]["http_status"] == 200
            and discovery[2]["url"] == "https://billcommons.org/docs/api"
            and discovery[2]["http_status"] == 200
            and api[0]["url"] == API + "/docs" and api[0]["http_status"] == 200
            and api[1]["url"] == API + "/openapi.json" and api[1]["http_status"] == 200,
            "missing retained public documentation or robots responses")
    robots = RobotFileParser()
    robots.parse((source / "discovery" / discovery[1]["path"]).read_bytes().decode("utf-8")
                 .split("\n"))
    require(all(robots.can_fetch(agent, url) for agent in (
        "GitHubCopilot-StatePoliticsResearch/1.0", "GPTBot",
    ) for url in ("https://billcommons.org/docs/api", "https://billcommons.org/robots.txt")),
        "retained main robots policy disallows documentation")
    swagger = (source / "openapi" / api[0]["path"]).read_bytes().decode("utf-8")
    require("/openapi.json" in swagger, "OpenAPI not advertised by retained docs")
    document = _json(source / "openapi" / api[1]["path"])
    for route, parameters in (
        ("/api/v1/sessions", set()), ("/api/v1/bills/batch", {"keys"}),
        (FULL_ROUTE, {"bill_id"}), (TEXT_ROUTE, {"bill_id", "document_id"}),
    ):
        method = document["paths"][route]["get"]
        require(parameters <= {item["name"] for item in method.get("parameters", [])}
                and "200" in method["responses"], "unadvertised public API method/parameters")
    sessions = []
    for page, exchange in enumerate(discovery[3:], 1):
        url = API + "/api/v1/sessions" + (f"?page={page}" if page != 1 else "")
        value = _api_response(source, "discovery", exchange, url, "/api/v1/sessions", document)
        pagination = value["pagination"]
        require(type(pagination["page"]) is int and pagination["page"] == page
                and pagination["total_pages"] == len(discovery) - 3,
                "incomplete/nonconsecutive published session pages")
        sessions.extend(value["data"])
        require(pagination["total"] >= len(sessions), "session page total conflict")
    require(pagination["total"] == len(sessions)
            and _equal(sessions, _json(source / "discovery/complete_session_metadata.json"))
            and len({row["id"] for row in sessions}) == len(sessions),
            "complete published session inventory replay mismatch")
    session = _json(source / "metadata/provider_session_preserved.json")
    require([row for row in sessions if row["id"] == SESSION_ID] == [session]
            and session["identifier"] == SESSION_IDENTIFIER
            and session["jurisdiction_abbreviation"] == "DE"
            and session["start_date"] == "2026-01-13" and session["end_date"] == "2026-06-30",
            "provider session chain/date conflict was altered")
    return document, session


def _span(text, match):
    return {"start": match.start(), "end": match.end(), "text": text[match.start():match.end()]}


def _typed_number(identifier):
    require(type(identifier) is str, "untyped original/provider bill number")
    match = re.fullmatch(r"([A-Z]+)\s*(\d+)", identifier)
    require(match is not None, "invalid original/provider typed bill number")
    return match[1] + str(int(match[2]))


def printed_identity(text, context, media_type):
    """Observe own headers and complete-body witnesses at unchanged source coordinates."""
    if (type(text) is not str or context["state"] != "DE"
            or context["session_identifier"] != "153"
            or context.get("session_name") != "153rd General Assembly (2025-2026)"
            or type(context.get("title")) is not str or not context["title"].strip()
            or media_type not in ("application/pdf", "text/html")):
        return None
    identifier = re.fullmatch(r"(HB|SR) ([1-9]\d*)", context["identifier"])
    if not identifier or re.search(r"(?im)^[^\S\n]*FISCAL\s+NOTE\b", text[:2000]):
        return None
    kind, number = identifier.groups()
    venue = "HOUSE OF REPRESENTATIVES" if kind == "HB" else "DELAWARE STATE SENATE"
    formal = "HOUSE BILL" if kind == "HB" else "SENATE RESOLUTION"
    header = re.search(
        r"(?m)^[^\S\n]*(?P<venue>" + r"\s+".join(venue.split()) + r")\s+"
        r"(?P<assembly>153rd\s+GENERAL\s+ASSEMBLY)\s+"
        r"(?P<bill>" + r"\s+".join(formal.split()) + r"\s+NO\.\s*" + number + r")"
        r"[^\S\n]*\n", text[:5000],
    )
    if header is None:
        return None
    prefix = text[:header.start()]
    if re.search(
        r"(?im)^[^\S\n]*(?:HOUSE\s+OF\s+REPRESENTATIVES|DELAWARE\s+STATE\s+SENATE|"
        r"(?:HOUSE|SENATE)\s+(?:BILL|RESOLUTION)\s+NO\.|"
        r"(?:\d+[^\S\n]+)?(?:BE\s+IT\s+(?:ENACTED|RESOLVED)|WHEREAS,|Section\s+1\.))",
        prefix,
    ):
        return None
    # Caption whitespace is compared, not rewritten; all evidence points into the original.
    caption = re.match(
        r"\s*(?P<caption>" + r"\s+".join(map(re.escape, context["title"].split())) + r")"
        r"(?=\s|$)", text[header.end():],
    )
    if caption is None:
        return None
    caption_start = header.end() + caption.start("caption")
    caption_end = header.end() + caption.end("caption")
    # Mask only printed numeric line prefixes, preserving every character coordinate.
    masked = re.sub(r"(?m)^([^\S\n]*)(\d+)(?=[^\d\n])",
                    lambda m: " " * len(m[0]), text)
    clause_pattern = (
        r"BE\s+IT\s+ENACTED\s+BY\s+THE\s+GENERAL\s+ASSEMBLY\s+OF\s+THE\s+STATE\s+OF\s+DELAWARE:"
        if kind == "HB" else
        r"BE\s+IT\s+RESOLVED\s+by\s+the\s+Senate\s+of\s+the\s+153\s*rd\s+"
        r"General\s+Assembly\s+of\s+the\s+State\s+of\s+Delaware"
    )
    clauses = list(re.finditer(r"(?m)^[^\S\n]*" + clause_pattern, masked, re.I))
    synopsis = re.search(r"(?m)^[^\S\n]*SYNOPSIS[^\S\n]*(?:\n|$)", text)
    if (not clauses or synopsis is None or not caption_end <= clauses[0].start() < synopsis.start()
            or not text[clauses[0].end():synopsis.start()].strip()
            or not text[synopsis.end():].strip()):
        return None
    if kind == "HB":
        recitals = masked[caption_end:clauses[0].start()].strip()
        if recitals and not recitals.startswith("WHEREAS,"):
            return None
        if re.search(r"(?im)^[^\S\n]*Section\s+1\.", masked[
            clauses[0].end():synopsis.start()
        ]) is None:
            return None
    elif masked[caption_end:clauses[0].start()].strip():
        return None
    pages = list(re.finditer(r"\bPage\s+(\d+)\s+of\s+(\d+)\b", text))
    if pages:
        total = int(pages[0][2])
        if not 1 <= total <= 1000 or [(int(m[1]), int(m[2])) for m in pages] != [
            (page, total) for page in range(1, total + 1)
        ]:
            return None
    if media_type == "application/pdf" and re.search(r"\bPage\s+\d", text) and not pages:
        return None
    evidence = [
        {"start": header.start(name), "end": header.end(name),
         "text": text[header.start(name):header.end(name)]}
        for name in ("venue", "assembly", "bill")
    ]
    evidence.append({"start": caption_start, "end": caption_end,
                     "text": text[caption_start:caption_end]})
    evidence.extend((_span(text, clauses[0]), _span(text, synopsis)))
    return {
        "state": "DE", "session_identifier": "153", "identifier": context["identifier"],
        "printed_assembly": "153rd GENERAL ASSEMBLY",
        "original_printed_assembly_relation": "original_153_session_and_own_printed_153rd_assembly",
        "printed_year": None, "kind": "bill" if kind == "HB" else "resolution",
        "printed_evidence": evidence, "printed_page_evidence": [_span(text, m) for m in pages],
        "printed_page_sequence_complete": True if pages else None,
        "raw_publisher_pages_or_originality_verified": False,
        "inference_text_start": 0, "inference_text_end": len(text),
    }


def _replay(source, queue_path, source_sha, queue_sha):
    manifest, exchanges = _source(source, source_sha)
    require(_binding(queue_path)["sha256"] == _hash(queue_sha)
            and _equal(_binding(queue_path), manifest["input_gap_queue"])
            and _equal(_binding(queue_path), _binding(source / "input_gap_queue.parquet")),
            "original complete gap queue changed")
    queue = pq.read_table(queue_path)
    originals = queue.to_pylist()
    require(all(type(row["bill_id"]) is str for row in originals)
            and len({row["bill_id"] for row in originals}) == len(originals),
            "duplicate/untyped original gap context")
    document, session = _publication_evidence(source, exchanges)
    candidates = _json(source / "metadata/exact_original_candidates.json")
    targets = [row for row in originals if row["state"] == "DE"
               and row["session_identifier"] == "153"]
    require(_equal(candidates, targets), "whole original candidate fields/nulls/types changed")
    _unapproved(candidates)
    frontier = _json(source / "metadata/candidate_document_frontier.json")
    require(len(frontier) == len(candidates) and len(exchanges["metadata"]) == len(frontier) + 1,
            "incomplete candidate metadata frontier")
    batch_exchange = exchanges["metadata"][0]
    require(urlsplit(batch_exchange["url"]).path == "/api/v1/bills/batch"
            and urlsplit(batch_exchange["url"]).netloc == "api.billcommons.org",
            "batch response is not the advertised API")
    keys = parse_qs(urlsplit(batch_exchange["url"]).query)
    original_by_number = {_typed_number(row["identifier"]): row for row in candidates}
    require(len(original_by_number) == len(candidates), "duplicate original typed bill number")
    ordered_numbers = sorted(original_by_number)
    expected_keys = [
        f"DE:{number}:{session['identifier']}" for number in ordered_numbers
    ]
    require(keys == {"keys": [",".join(expected_keys)]}, "batch original/session key mismatch")
    batch = _api_response(source, "metadata", batch_exchange, batch_exchange["url"],
                          "/api/v1/bills/batch", document)
    require(_equal(batch, _json(source / "metadata/batch_dispositions.json"))
            and _equal(batch["not_found"], []) and _equal(batch["ambiguous"], {})
            and len(batch["data"]) == len(candidates), "batch dispositions replay mismatch")
    summaries = {}
    for summary in batch["data"]:
        number = _typed_number(summary["identifier"])
        require(number in original_by_number and number not in summaries,
                "batch original typed bill number missing/duplicated")
        summaries[number] = summary
    require(summaries.keys() == original_by_number.keys(), "batch original coverage mismatch")
    records, offered, metadata_paths = {}, {}, {}
    leads_by_context = {}
    for ordinal, (number, lead) in enumerate(zip(ordered_numbers, frontier, strict=True), 2):
        context, summary = original_by_number[number], summaries[number]
        require(lead["provider_full_exchange"] == ordinal
                and lead["original_bill_id"] == context["bill_id"]
                and lead["original_identifier"] == context["identifier"]
                and lead["original_title"] == context["title"],
                "frontier original identity mismatch")
        exchange = exchanges["metadata"][ordinal - 1]
        full = _api_response(source, "metadata", exchange,
                             API + f"/api/v1/bills/{summary['id']}/full", FULL_ROUTE, document)
        bill = full["bill"]
        require(_equal(lead["provider_bill"], bill)
                and _equal(lead["versions"], full["versions"])
                and _equal(lead["documents"], full["documents"])
                and lead["complete_metadata_file"] == exchange["path"]
                and all(key in bill and _equal(bill[key], value)
                        for key, value in summary.items())
                and bill["id"] not in records and bill["session_id"] == session["id"]
                and bill["jurisdiction_id"] == session["jurisdiction_id"]
                and bill["jurisdiction_abbreviation"] == "DE"
                and bill["session_identifier"] == session["identifier"]
                and bill["identifier"] == context["identifier"]
                and bill["title"] == context["title"],
                "provider session/bill/full metadata projection mismatch")
        versions = {row["id"]: row for row in full["versions"]}
        require(len(versions) == len(full["versions"])
                and all(row["bill_id"] == bill["id"] for row in versions.values()),
                "provider version foreign key mismatch")
        records[bill["id"]] = (context, full)
        leads_by_context[context["bill_id"]] = lead
        metadata_paths[bill["id"]] = exchange["path"]
        for attachment in full["documents"]:
            require(attachment["id"] not in offered
                    and attachment["bill_version_id"] in versions,
                    "provider document/version foreign key mismatch")
            offered[attachment["id"]] = (
                context, full, versions[attachment["bill_version_id"]], attachment,
            )
    inventory = _json(source / "texts/complete_text_inventory.json")
    require(len(inventory) == len(exchanges["texts"]), "incomplete captured text inventory")
    seen, views, dispositions, counts = set(), [], [], {}
    for ordinal, capture in enumerate(inventory, 1):
        require(type(capture["source_exchange"]) is int and capture["source_exchange"] == ordinal,
                "text exchange ordinal changed")
        attachment = capture["provider_document"]
        require(attachment["id"] in offered and attachment["id"] not in seen,
                "unknown/duplicate captured source document")
        seen.add(attachment["id"])
        context, full, version, actual_attachment = offered[attachment["id"]]
        require(_equal(attachment, actual_attachment)
                and _equal(capture["provider_version"], version)
                and capture["original_bill_id"] == context["bill_id"]
                and capture["original_identifier"] == context["identifier"]
                and capture["provider_bill_id"] == full["bill"]["id"],
                "text inventory provider/original foreign key mismatch")
        exchange = exchanges["texts"][ordinal - 1]
        url = API + f"/api/v1/bills/{full['bill']['id']}/documents/{attachment['id']}/text"
        response = _api_response(source, "texts", exchange, url, TEXT_ROUTE, document)
        fields = {key: value for key, value in response.items() if key != "extracted_text"}
        text = response["extracted_text"]
        complete = capture["complete_text"]
        path = _relative(complete["path"])
        require(_equal(fields, capture["response_fields_preserved"])
                and response["document_id"] == attachment["id"]
                and response["version_id"] == version["id"]
                and response["bill_id"] == full["bill"]["id"]
                and type(response["char_count"]) is int
                and response["char_count"] == len(text) == capture["full_policy_characters"]
                and _equal(_binding(source / "texts" / path),
                           {key: complete[key] for key in ("sha256", "bytes")})
                and (source / "texts" / path).read_bytes() == text.encode("utf-8"),
                "complete text/raw response binding or foreign key mismatch")
        disposition = {
            "original_bill_id": context["bill_id"], "original_identifier": context["identifier"],
            "provider_bill_id": full["bill"]["id"], "provider_document": attachment,
            "provider_version": version, "response_fields_preserved": fields,
            "source_exchange": ordinal, "complete_text": complete,
            "full_policy_characters": len(text),
        }
        if (attachment["has_extracted_text"] is not True
                or attachment["text_is_partial"] is not False):
            reason = "provider_partial_or_unavailable_extraction_not_a_fill"
        elif response.get("fulltext_status") != "ok":
            reason = "provider_fulltext_status_not_complete_not_a_fill"
        elif re.search(r"(?im)^[^\S\n]*FISCAL\s+NOTE\b", text[:2000]):
            reason = "ancillary_fiscal_note_not_bill_body"
        else:
            identity = printed_identity(text, context, attachment["media_type"])
            reason = ("complete_stored_extraction_original_context" if identity is not None
                      else "unresolved_own_identity_caption_clause_or_completeness_not_a_fill")
            if identity is not None:
                view_id = f"billcommons:{attachment['id']}:context:{context['bill_id']}"
                counts[context["bill_id"]] = counts.get(context["bill_id"], 0) + 1
                views.append({
                    "view_id": view_id, "source_type": "archive_text",
                    **{key: context[key] for key in (
                        "bill_id", "state", "identifier", "session_identifier", "title",
                    )},
                    "text": text, "raw_text_characters": len(text),
                    "raw_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "source_record": full, "source_identity": identity,
                    "source_version": {
                        "version": version, "document": attachment,
                        "link": {"url": attachment["url"], "media_type": attachment["media_type"]},
                        "printed_year": None, "kind": identity["kind"],
                    },
                    "source_session": session, "original_target_context": context,
                    "source_members": {
                        "metadata": (
                            "source-evidence/metadata/" + metadata_paths[full["bill"]["id"]]
                        ),
                        "response": "source-evidence/texts/" + exchange["path"],
                        "text": "source-evidence/texts/" + path,
                        "original_queue": "input_gap_queue.parquet",
                    },
                    "archive_provider": PROVIDER, "source_status": STATUS,
                    "archive_generated_prologue_preserved": False,
                    "inference_text_start": 0, "inference_text_end": len(text),
                    "raw_publisher_PDF_or_HTML_bytes_supplied": False,
                    "independent_reader_truth_or_reextraction_asserted": False,
                    "provider_dates_preserved_not_original_context_overrides": True,
                    **dict.fromkeys(FLAGS, False),
                })
                disposition.update(view_id=view_id, source_identity=identity)
        disposition["disposition"] = reason
        dispositions.append(disposition)
    require(seen == {key for key, (_, _, _, attachment) in offered.items()
                     if attachment["has_extracted_text"] is True},
            "offered complete downloads omitted from captured inventory")
    candidate_rows = [
        {"original_target_context": row,
         "provider_bill_id": leads_by_context[row["bill_id"]]["provider_bill"]["id"],
         "provider_document_count": len(leads_by_context[row["bill_id"]]["documents"]),
         "n_retained_source_views": counts.get(row["bill_id"], 0),
         "disposition": "retained_independent_stored_extraction" if row["bill_id"] in counts
         else "no_accepted_complete_body_original_context_preserved"}
        for row in candidates
    ]
    contexts = queue.filter(pc.is_in(
        queue["bill_id"], value_set=pa.array(list(counts), type=pa.string()),
    ))
    report = {
        "status": STATUS, "provider": PROVIDER, "source_manifest_sha256": source_sha,
        "original_gap_queue_sha256": queue_sha,
        "counts": {
            "original_gap_contexts": len(originals), "source_candidate_contexts": len(candidates),
            "newly_covered_contexts": len(counts), "text_views": len(views),
            "source_document_dispositions": len(dispositions),
            "remaining_unavailable_from_this_source": len(originals) - len(counts),
            "full_retained_text_characters": sum(len(view["text"]) for view in views),
            "actual_GETs_previously_captured": manifest["actual_GETs"],
        },
        "provider_session": session, "all_original_fields_nulls_types_and_dates_preserved": True,
        "raw_publisher_PDF_or_HTML_bytes_supplied": False,
        "stored_provider_extraction_not_reextraction_or_independent_reader_truth": True,
        "provider_session_dates_not_original_context_overrides": True,
        "printed_year_not_inferred_from_assembly_original_session_or_release_stamp": True,
        "network_calls": 0, "encoder_calls": 0, "approvals": dict.fromkeys(FLAGS, False),
    }
    return {"views.jsonl": views, "source_document_dispositions.jsonl": dispositions}, (
        contexts, pa.Table.from_pylist(candidate_rows)
    ), report


def _exports(products, tables, report):
    contexts, candidates = tables
    return {
        **{name: _row_bytes(rows) for name, rows in products.items()},
        "context_inventory.parquet": _parquet_bytes(contexts),
        "candidate_dispositions.parquet": _parquet_bytes(candidates),
        "report.json": _json_bytes(report),
    }


def build_billcommons(source_directory, gap_queue, out_directory, *,
                     source_manifest_sha256, gap_queue_sha256):
    source, queue = _root(source_directory), _regular(Path(gap_queue).absolute())
    out = Path(out_directory).absolute()
    require(not out.exists() and out.resolve() == out and not out.is_symlink()
            and not out.is_relative_to(source) and not source.is_relative_to(out)
            and not queue.is_relative_to(out), "new nonoverlapping output directory required")
    source_sha, queue_sha = _hash(source_manifest_sha256), _hash(gap_queue_sha256)
    manifest, _ = _source(source, source_sha)
    names = set(manifest["artifacts"]) | {"manifest.json"}
    before = {name: _binding(source / name) for name in sorted(names)}
    queue_before, producer = _binding(queue), _binding(Path(__file__).absolute())
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
            and _equal(producer, _binding(Path(__file__).absolute())),
            "source/queue/producer changed during normalization")
    (out / "source_inventory.json").write_bytes(_json_bytes(before))
    (out / "source_immutability.json").write_bytes(_json_bytes({
        "before": before, "after": after, "original_queue_before": queue_before,
        "original_queue_after": queue_before, "all_original_inputs_unchanged": True,
    }))
    (out / "producer").mkdir()
    shutil.copyfile(Path(__file__).absolute(), out / "producer/billcommons_text.py")
    result = {
        "schema": SCHEMA, "provider": PROVIDER, "status": STATUS, "tools": TOOLS,
        "source_manifest_sha256": source_sha, "gap_queue_sha256": queue_sha,
        "approvals": dict.fromkeys(FLAGS, False), "counts": report["counts"],
        "packet_artifacts": {
            name: _binding(out / name) for name in sorted(
                PRODUCTS | {"source-evidence/" + name for name in names}
            )
        },
    }
    (out / "manifest.json").write_bytes(_json_bytes(result))
    load_billcommons(out, source_manifest_sha256=source_sha, gap_queue_sha256=queue_sha)
    return result


def load_billcommons(directory, metadata=None, *,
                     source_manifest_sha256=None, gap_queue_sha256=None):
    root = _root(directory)
    manifest = _json(root / "manifest.json")
    require(set(manifest) == {
        "schema", "provider", "status", "tools", "source_manifest_sha256", "gap_queue_sha256",
        "approvals", "counts", "packet_artifacts",
    }, "unexpected normalized manifest fields")
    require(manifest["schema"] == SCHEMA and manifest["provider"] == PROVIDER
            and manifest["status"] == STATUS and _equal(manifest["tools"], TOOLS)
            and _equal(manifest["approvals"], dict.fromkeys(FLAGS, False)),
            "normalized schema/provider/runtime/approval mismatch")
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
        require(_equal(_binding(root / name), value), f"normalized artifact changed: {name}")
        pins[name] = value["sha256"]
    require(_equal(artifacts["producer/billcommons_text.py"], _binding(Path(__file__).absolute())),
            "installed/archived producer mismatch")
    source = _root(root / "source-evidence")
    source_manifest, _ = _source(source, manifest["source_manifest_sha256"])
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
        require((root / name).read_bytes() == raw, f"full {name} replay mismatch")
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
        manifest = build_billcommons(
            args.source_dir, args.gap_queue, args.out_dir,
            source_manifest_sha256=args.source_manifest_sha256,
            gap_queue_sha256=args.gap_queue_sha256,
        )
    else:
        metadata = pq.read_table(args.metadata) if args.metadata else None
        _, _, _, manifest = load_billcommons(
            args.directory, metadata, source_manifest_sha256=args.source_manifest_sha256,
            gap_queue_sha256=args.gap_queue_sha256,
        )
    print(json.dumps(manifest["counts"], indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

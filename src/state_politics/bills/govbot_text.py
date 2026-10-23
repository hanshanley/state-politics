"""Offline replay of selected, independently archived Govbot document objects.

Only the reviewed Montana 2025 formal-resolution profile is admitted. A Git
membership proof, published extraction witness and both complete PDF readers
must agree; none of these observations certifies an original filing or rights.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import platform
import re
import shutil
import stat
import warnings
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

import fitz
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pypdf

from . import native_text

SCHEMA = "state-politics.govbot-archived-documents.v1"
SOURCE_SCHEMA = "state-politics.govbot-exact-original-leads.v1"
PROVIDER = "govbot-data"
STATUS = "independent_provider_full_PDF_not_native_original_or_filing_certified"
FLAGS = (
    "scientific_approval", "model_input_approved", "training_approved",
    "training_admission", "publication_approved", "party_attribution_approved",
    "filing_time_text_certified", "analytical_admission", "publisher_original_verified",
    "native_original_verified", "native_identity_certified", "source_rights_approved",
    "rights_approved", "canonical_population_admission", "source_date_or_party_inferred",
    "bill_specific_carryover_status_inferred", "native_URL_alias_inferred",
    "introduced_version_certified", "original_version_certified", "source_admission",
    "human_review_approved", "human_validation_approved",
)
TOOLS = {
    "python": platform.python_version(), "pyarrow": pa.__version__,
    "PyMuPDF": fitz.VersionBind, "pypdf": pypdf.__version__,
}
DEPENDENCIES = {"govbot_text.py": Path(__file__).absolute(),
                "native_text.py": Path(native_text.__file__).absolute()}
PRODUCTS = {
    "views.jsonl", "source_dispositions.jsonl", "version_dispositions.jsonl",
    "document_dispositions.jsonl", "candidate_dispositions.jsonl", "reader_pages.jsonl",
    "source_context_dispositions.jsonl",
    "context_inventory.parquet", "input_gap_queue.parquet", "report.json",
    "source_inventory.json", "source_immutability.json",
    *(f"producer/{name}" for name in DEPENDENCIES),
}
PROFILE = {"SR 1": "SENATE RESOLUTION", "SJ 1": "SENATE JOINT RESOLUTION",
           "SJ 2": "SENATE JOINT RESOLUTION"}


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible Govbot archive: {message}")


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"incompatible Govbot archive: nonfinite JSON {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def _equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _hash(value, length=64):
    require(type(value) is str and re.fullmatch(rf"[0-9a-f]{{{length}}}", value),
            "invalid object digest")
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
        raise ValueError(f"incompatible Govbot archive: missing artifact: {path}") from exc
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "nonregular artifact")
    return path


def _binding(path):
    _regular(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": digest, "bytes": path.stat().st_size}


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


def _rows(path):
    with _regular(path).open("rb") as stream:
        for line in stream:
            require(bool(line.strip()), "blank source JSONL record")
            yield _decode(line)


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def _write_rows(path, rows):
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def _git_hash(kind, raw):
    return hashlib.sha1(kind.encode() + b" " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def _typed_identifier(value):
    match = re.fullmatch(r"([A-Z]+) ?([1-9]\d*)", value) if type(value) is str else None
    require(match is not None, "malformed provider/original typed number")
    return match.groups()


def _git_tree(data, recursive):
    """Rebuild every available complete tree without extracting Git symlinks."""
    require(type(data["truncated"]) is bool and len(data["tree"]) <= 250000,
            "invalid or oversized Git tree")
    _hash(data["sha"], 40)
    nodes, directories = {}, {"": {}}
    for node in data["tree"]:
        name = _relative(node["path"])
        require(name not in nodes, "duplicate Git tree member")
        _hash(node["sha"], 40)
        require((node["mode"], node["type"]) in {
            ("040000", "tree"), ("100644", "blob"), ("100755", "blob"),
            ("120000", "blob"), ("160000", "commit"),
        }, "unsupported Git tree mode/type")
        parent, leaf = PurePosixPath(name).parent.as_posix(), PurePosixPath(name).name
        parent = "" if parent == "." else parent
        require(recursive or not parent, "nested member in direct Git tree")
        nodes[name] = node
        directories.setdefault(parent, {})[leaf] = node
        if recursive and node["type"] == "tree":
            directories.setdefault(name, {})
    if data["truncated"]:
        return nodes
    require(all(not name or name in nodes and nodes[name]["type"] == "tree"
                for name in directories), "missing recursive parent tree")
    for directory, entries in directories.items():
        names = sorted(entries, key=lambda name: name.encode() + (
            b"/" if entries[name]["type"] == "tree" else b""
        ))
        raw = b"".join(
            entries[name]["mode"].lstrip("0").encode() + b" " + name.encode()
            + b"\0" + bytes.fromhex(entries[name]["sha"]) for name in names
        )
        expected = nodes[directory]["sha"] if directory else data["sha"]
        require(_git_hash("tree", raw) == expected, "Git tree reconstruction mismatch")
    return nodes


def _source(source, expected_sha):
    require(_binding(source / "manifest.json")["sha256"] == _hash(expected_sha),
            "caller-pinned source manifest changed")
    manifest = _json(source / "manifest.json")
    require(manifest["schema"] == SOURCE_SCHEMA and manifest["network_closed"] is True
            and manifest["source_admission"] is False and manifest["publication"] is False,
            "closed unapproved source packet required")
    artifacts = manifest["artifacts"]
    require(type(artifacts) is dict and _tree(source) == set(artifacts) | {"manifest.json"},
            "source inventory omissions or extra members")
    require(all(type(value) is dict and type(value.get("bytes")) is int
                and 0 <= value["bytes"] <= 100000000 for value in artifacts.values())
            and sum(value["bytes"] for value in artifacts.values()) <= 3000000000,
            "source artifact/aggregate byte ceiling")
    for name, value in artifacts.items():
        _relative(name)
        require(_equal(_binding(source / name), value), f"source artifact changed: {name}")
    scope, report = _json(source / "scope.json"), _json(source / "report.json")
    ledger = list(_rows(source / "invocation-ledger.jsonl"))
    require(report["network_closed"] is True and report["source_admissions"] == 0
            and report["model_calls"] == 0 and report["publication"] is False
            and report["native_publisher_requests"] == 0
            and len(ledger) == report["new_gh_CLI_invocations"]
            <= scope["maximum_new_gh_CLI_invocations"] == 250
            and report["original_250_allowance_not_reset"] is True
            and report["new_invocations_in_this_continuation"]
            + report["closed_preceding_capture_invocations"] == len(ledger)
            and report["closed_prior_discovery_invocations"]
            == scope["closed_previous_discovery_invocations"],
            "source logical invocation accounting or analytical gates changed")
    responses, trees, blob_data = {}, {}, {}
    tree_report = []
    for ordinal, row in enumerate(ledger, 1):
        require(row["ordinal"] == ordinal and row["gh_returncode"] == 0
                and row["http_status"] == 200, "nonconsecutive or unsuccessful source ledger")
        endpoint = row["endpoint"]
        match = re.fullmatch(
            r"repos/govbot-data/([a-z]{2})-legislation/git/(trees|blobs)/"
            r"([0-9a-f]{40})(\?recursive=1)?", endpoint,
        )
        require(match is not None and endpoint not in responses,
                "unreviewed or duplicate source endpoint")
        name = _relative(row["response"])
        require(_equal(_binding(source / name), row["response_binding"]),
                "raw source response binding mismatch")
        raw = (source / name).read_bytes()
        header, separator, body = raw.partition(b"\r\n\r\n")
        require(separator and re.match(rb"HTTP/[0-9.]+ 200(?: |\r?\n)", header)
                and len(raw) <= 100000000, "malformed archived HTTP response")
        data = _decode(body)
        require(_equal(data, _json((source / name).with_suffix(".json")))
                and data["sha"] == match[3], "raw response/parsed JSON/object digest mismatch")
        responses[endpoint] = (row, data)
        if match[2] == "trees":
            recursive = bool(match[4])
            nodes = _git_tree(data, recursive)
            trees[endpoint] = (data, nodes)
            tree_report.append({
                "endpoint": endpoint, "git_tree_sha1": data["sha"],
                "recursive": recursive, "truncated": data["truncated"],
                "n_structural_entries": len(nodes),
                "complete_structure_reconstructed": not data["truncated"],
                "nonselected_blobs_downloaded": False,
            })
        else:
            require(not match[4] and data["encoding"] == "base64", "unsupported Git blob encoding")
            decoded = base64.b64decode(re.sub(r"\s+", "", data["content"]), validate=True)
            require(len(decoded) == data["size"] <= scope["maximum_individual_blob_bytes"]
                    and _git_hash("blob", decoded) == data["sha"],
                    "Git blob SHA1/size mismatch")
            blob_data[endpoint] = decoded
    object_paths = {f"objects/{data['sha']}" for _, data in responses.values()
                    if "content" in data}
    require({name for name in artifacts if name.startswith("objects/")} == object_paths,
            "selected object inventory mismatch")
    require(len(object_paths) == report["selected_complete_blob_objects"]
            and sum(artifacts[name]["bytes"] for name in object_paths)
            == report["selected_blob_bytes"] <= scope["maximum_selected_original_blob_bytes"],
            "selected unique object/byte accounting mismatch")
    proofs = _json(source / "session-tree-proofs.json")
    leads = scope["session_leads"]
    require(len({(lead["state"], lead["session_identifier"]) for lead in leads}) == len(leads)
            == len(proofs), "duplicate or omitted source session proof")
    proof_index = {(row["state"], row["session_identifier"]): row for row in proofs}

    def response(ref):
        require(ref["endpoint"] in responses and _equal(responses[ref["endpoint"]][0], ref),
                "unbound tree/blob response reference")
        return responses[ref["endpoint"]][1]

    memberships = {}
    for lead in leads:
        state, session = lead["state"], lead["session_identifier"]
        proof = proof_index.get((state, session))
        require(proof is not None and proof["tree_sha1"] == lead["published_session_tree"]["sha"]
                and proof["all_selected_branch_membership_verified"] is True
                and proof["all_nonselected_blobs_downloaded"] is False,
                "unbound selected source session")
        root = response(proof["response"])
        require(root["sha"] == proof["tree_sha1"]
                and proof["structural_tree_reconstructed"] is (not root["truncated"]),
                "source session tree identity/completeness conflict")
        nodes = trees[proof["response"]["endpoint"]][1]
        if not root["truncated"]:
            memberships[(state, session)] = nodes
        else:
            selected = {}
            for branch in proof["targeted_branch_proofs"]:
                direct = response(branch["direct_session_response"])
                bills = response(branch["direct_bill_directories_response"])
                complete = response(branch["selected_bill_tree_response"])
                published = branch["published_bill_directory"]
                require(direct["sha"] == root["sha"] and direct["truncated"] is False
                        and bills["truncated"] is False and complete["truncated"] is False
                        and branch["complete_selected_branch_reconstructed"] is True,
                        "incomplete selected branch proof")
                direct_nodes = trees[branch["direct_session_response"]["endpoint"]][1]
                bill_nodes = trees[branch["direct_bill_directories_response"]["endpoint"]][1]
                require(direct_nodes["bills"]["sha"] == bills["sha"]
                        and _equal(bill_nodes[published["path"]], published)
                        and published["type"] == "tree" and published["sha"] == complete["sha"],
                        "selected branch not a member of the exact source session")
                prefix = f"bills/{_relative(published['path'])}"
                require(prefix not in selected, "duplicate selected bill branch")
                selected[prefix] = published
                branch_nodes = trees[branch["selected_bill_tree_response"]["endpoint"]][1]
                for name, node in branch_nodes.items():
                    selected[f"{prefix}/{name}"] = {**node, "path": f"{prefix}/{name}"}
            memberships[(state, session)] = selected

    records = list(_rows(source / "retained-original-bill-records.jsonl"))
    require(len(records) == report["retained_bill_records"]
            and len({r["original_target_context"]["bill_id"] for r in records}) == len(records),
            "duplicate or omitted original provider context")
    expected_ids = [bill_id for lead in leads for bill_id in lead["original_bill_ids"]]
    require(len(set(expected_ids)) == len(expected_ids)
            and set(expected_ids) == {r["original_target_context"]["bill_id"] for r in records},
            "selected original leads not completely disposed")
    used_objects = set()

    def blob(node, obj, state):
        require(node["type"] == "blob" and node["mode"] in ("100644", "100755"),
                "selected symlink/nonregular Git object")
        name = _relative(obj["path"])
        require(name == f"objects/{_hash(node['sha'], 40)}"
                and obj["git_blob_sha1"] == node["sha"]
                and _equal(_binding(source / name), {
                    "sha256": obj["sha256"], "bytes": obj["bytes"],
                }) and obj["bytes"] == node["size"], "selected blob binding mismatch")
        expected = f"repos/govbot-data/{state.lower()}-legislation/git/blobs/{node['sha']}"
        require(obj["response"]["endpoint"] == expected, "wrong repository blob response")
        response(obj["response"])
        raw = (source / name).read_bytes()
        require(raw == blob_data[expected] and _git_hash("blob", raw) == node["sha"],
                "selected blob is not the published raw Git blob")
        used_objects.add(name)
        return raw

    for record in records:
        context, provider = record["original_target_context"], record["provider_record"]
        state, session = context["state"], context["session_identifier"]
        nodes = memberships[(state, session)]
        proof = proof_index[(state, session)]
        require(record["source_session_tree"] == proof["tree_sha1"]
                and record["source_admission"] is False
                and provider["legislative_session"] == session
                and _typed_identifier(provider["identifier"])
                == _typed_identifier(context["identifier"])
                and provider["title"] == context["title"]
                and provider["jurisdiction"]["id"]
                == f"ocd-jurisdiction/country:us/state:{state.lower()}/government",
                "provider state/session/typed number/title conflict")
        require("id" not in provider and record["provider_bill_ID_equals_original"] is False,
                "provider OCD identity absent; no alias or conflicting ID admitted")
        metadata_node = record["metadata_node"]
        require(_equal(nodes.get(metadata_node["path"]), metadata_node),
                "metadata missing from selected Git branch")
        raw = blob(metadata_node, record["metadata_object"], state)
        require(_equal(_decode(raw), provider), "provider record differs from published metadata")
        base = PurePosixPath(metadata_node["path"]).parent
        require(base.parent.as_posix() == "bills"
                and base.name == context["identifier"].replace(" ", "")
                and metadata_node["path"] == f"{base}/metadata.json",
                "metadata not in its exact typed-number directory")
        files = record["complete_published_bill_files"]
        file_index = {f["published_git_path"]: f for f in files}
        expected_files = {name for name, node in nodes.items()
                          if name.startswith(f"{base}/files/") and node["type"] != "tree"}
        require(len(file_index) == len(files) and set(file_index) == expected_files,
                "complete selected published file inventory mismatch")
        for name, item in file_index.items():
            require(_equal(nodes[name], item["node"]) and item["node"]["path"] == name,
                    "document not in selected published branch")
            blob(item["node"], item["captured_object"], state)
    require(used_objects == object_paths, "unaccounted selected source objects")
    return manifest, records, tree_report


def _span(match):
    return {"start": match.start(), "end": match.end(), "text": match[0]}


def _venue(text):
    return re.match(r"\A\s*69th[ \t]+Legislature[ \t]+(?:-[ \t]+)?2025\b", text)


def _page_header(text):
    venue = _venue(text)
    compact = None
    if venue:
        compact = re.match(
            r"\s*(SR|SJ|LC)[ \t]*(\d+)(?:\.(\d+))?\b", text[venue.end():],
        )
    abbreviated = None
    if compact:
        abbreviated = {
            "start": venue.end() + compact.start(), "end": venue.end() + compact.end(),
            "text": compact[0],
        }
    return {
        "printed_venue": _span(venue) if venue else None,
        "printed_abbreviated_header": abbreviated,
        "internal_header_token_not_formal_alias": list(compact.groups()) if compact else None,
        "nonempty": bool(text.strip()),
    }


def printed_identity(text, context):
    """Observe a formal *own* heading, never a citation or an LC-number alias."""
    if (context["state"] != "MT" or context["session_identifier"] != "2025"
            or context["identifier"] not in PROFILE):
        return None
    header = text[:3500]
    venue = _venue(header)
    introduced = re.search(r"\bINTRODUCED[ \t]+BY\b", header)
    if not venue or not introduced:
        return None
    preamble = header[:introduced.start()]
    kind, number = context["identifier"].split()
    own = re.search(
        r"(?m)^[ \t]*(?:\d{1,2}[ \t]+)?"
        + PROFILE[context["identifier"]] + r"[ \t]+NO\.[ \t]+" + number
        + r"(?=(?:[ \t]+1)?[ \t]*\r?$)", preamble,
    )
    state = re.search(
        r"\bSTATE\s+OF(?:[ \t]+\d{1,2}(?=[ \t]*\r?\n)"
        r"|[ \t]*\r?\n[ \t]*\d{1,2})?\s+MONTANA\b", header,
    )
    resolved = re.search(r"\bBE[ \t]+IT[ \t]+RESOLVED\b", header)
    if not own or not state or not resolved or own.start() >= resolved.start():
        return None
    if re.search(r"\b(?:AMENDMENT|CONDENSED|FISCAL|INSTRUCTIONS)\b", preamble, re.I):
        return None
    return {
        "state": "MT", "identifier": f"{kind} {number}", "session_identifier": "2025",
        "printed_legislature": "69th", "printed_year": "2025",
        "source_relation": "exact_provider_context_and_printed_own_formal_resolution",
        "original_native_URL_equality_or_alias_not_asserted": True,
        "printed_evidence": [_span(m) for m in (venue, own, state, resolved)],
    }


def _witness(text, versions):
    prologue, separator, _ = text.partition("\n" + "=" * 80 + "\n")
    notes = re.findall(r"(?m)^Source: versions - ([^\r\n]+)\r?$", prologue)
    media = re.findall(r"(?m)^Media Type: ([^\r\n]+)\r?$", prologue)
    if not separator or len(notes) != 1 or media != ["application/pdf"]:
        return None, "missing_or_malformed_published_PDF_witness"
    matched = [v for v in versions if v["note"] == notes[0]]
    if len(matched) != 1:
        return None, "nonunique_exact_published_version_note"
    links = [link for link in matched[0]["links"] if link["media_type"] == "application/pdf"]
    if len(links) != 1 or type(links[0]["url"]) is not str or not links[0]["url"]:
        return None, "nonunique_published_PDF_version_link"
    return {"version": matched[0], "link": links[0],
            "witness_prologue": prologue,
            "visual_markup_warning_preserved": "Visual Markup Detected: true" in prologue}, None


class _Warnings(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append({"channel": record.name, "level": record.levelname,
                              "message": record.getMessage()})


def _extract(path, context):
    record = {
        "native_id": f"provider-source-extraction:{context['bill_id']}",
        "measure_type": context["identifier"].split()[0],
        "identifier": context["identifier"], "session_kind": "2025",
    }
    handler, logger = _Warnings(), logging.getLogger("pypdf")
    logger.addHandler(handler)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            pages, views = native_text.extract_pdf(path, record, "Montana")
    finally:
        logger.removeHandler(handler)
    diagnostics = handler.messages + [
        {"channel": "python", "level": warning.category.__name__, "message": str(warning.message)}
        for warning in caught
    ]
    # The helper's generic header observations are retained only as diagnostics.
    # Authority here comes solely from our reviewed own-formal-header profile.
    return _decode(json.dumps(pages)), views, diagnostics


def _replay(source, queue_path, source_sha, queue_sha):
    manifest, records, tree_report = _source(source, source_sha)
    capture_report = _json(source / "report.json")
    queue_binding = _binding(queue_path)
    require(queue_binding["sha256"] == _hash(queue_sha)
            and _equal(queue_binding, manifest["input_gap_queue"])
            and _equal(queue_binding, _binding(source / "input_gap_queue.parquet")),
            "original complete gap queue changed")
    queue = pq.read_table(queue_path)
    originals = queue.to_pylist()
    original_index = {row["bill_id"]: row for row in originals}
    require(len(original_index) == len(originals), "duplicate original gap context")
    views, pages_out, documents, files_out, versions_out, source_contexts = (
        [] for _ in range(6)
    )
    counts = Counter()
    for record in records:
        context, provider = record["original_target_context"], record["provider_record"]
        require(_equal(original_index.get(context["bill_id"]), context)
                and context["neither_source_observed"] is True,
                "retained context changed original fields/nulls/types")
        files = {item["published_git_path"]: item
                 for item in record["complete_published_bill_files"]}
        linked_versions, bindings = defaultdict(list), {}
        for name in files:
            if not name.endswith(".pdf"):
                continue
            witness = files.get(name[:-4] + "_extracted.txt")
            binding = (None, "same_stem_published_extraction_witness_missing")
            if witness is not None:
                binding = _witness(
                    (source / witness["captured_object"]["path"]).read_text(encoding="utf-8"),
                    provider["versions"],
                )
            bindings[name] = binding
            if binding[0]:
                linked_versions[binding[0]["version"]["note"]].append(name)
        for name, item in files.items():
            if not name.endswith(".pdf"):
                files_out.append({
                    "bill_id": context["bill_id"], **item,
                    "disposition": "published_extraction_witness_not_policy_input"
                    if name.endswith("_extracted.txt")
                    else "unreviewed_non_PDF_preserved_not_admitted",
                })
                continue
            witness = files.get(name[:-4] + "_extracted.txt")
            version, reason = bindings[name]
            if version and len(linked_versions[version["version"]["note"]]) != 1:
                reason = "nonunique_published_witness_to_PDF_pairing"
            pages, extracted, diagnostics = _extract(
                source / item["captured_object"]["path"], context,
            )
            for page in pages:
                pages_out.append({
                    "bill_id": context["bill_id"], "published_git_path": name,
                    "source_pdf_sha256": item["captured_object"]["sha256"], **page,
                })
            identities, page_headers = {}, []
            for view in extracted:
                selected = [page for page in pages if page["reader"] == view["reader"]]
                identities[view["reader"]] = printed_identity(selected[0]["text"], context)
                first = _page_header(selected[0]["text"])["internal_header_token_not_formal_alias"]
                for page in selected:
                    header = _page_header(page["text"])
                    page_headers.append({
                        "reader": page["reader"], "page": page["page"], **header,
                        "same_literal_header_identity_as_first_reader_page": first is not None
                        and header["internal_header_token_not_formal_alias"] == first,
                    })
            if context["state"] != "MT" or context["session_identifier"] != "2025":
                reason = "outside_reviewed_MT_2025_profile"
            elif version and re.search(
                r"amend|condens|context|fiscal|instruction|ancillary",
                version["version"]["note"], re.I,
            ):
                reason = "ancillary_or_amendment_context_not_full_formal_resolution"
            elif reason is None:
                if (set(identities) != {"pymupdf", "pypdf"}
                        or any(identity is None for identity in identities.values())):
                    reason = "printed_own_formal_identity_or_year_unresolved"
                elif not all(
                    row["nonempty"] and row["printed_venue"]
                    and row["same_literal_header_identity_as_first_reader_page"]
                    for row in page_headers
                ):
                    reason = "blank_or_conflicting_complete_reader_page"
                elif any(view["n_pages"] * 2 != len(pages) for view in extracted):
                    reason = "reader_population_disagreement"
            disposition = reason or "complete_PDF_exact_original_context_and_formal_header"
            document = {
                "bill_id": context["bill_id"], **item, "witness": witness,
                "source_version": version, "disposition": disposition,
                "reader_identities": identities, "reader_page_headers": page_headers,
                "reader_warnings": diagnostics,
                "warning_disposition": "preserved_not_original_or_markup_certification",
                "n_reader_page_records": len(pages), "n_reader_views": len(extracted),
            }
            documents.append(document)
            files_out.append({"bill_id": context["bill_id"], **item, "disposition": disposition})
            if reason is not None:
                continue
            for extracted_view in extracted:
                text = extracted_view["text"]
                view_id = f"govbot:{context['bill_id']}:{name}:{extracted_view['reader']}"
                views.append({
                    "view_id": view_id, "source_type": "archive_text",
                    **{key: context[key] for key in (
                        "bill_id", "state", "identifier", "session_identifier", "title",
                    )},
                    "reader": extracted_view["reader"], "text": text,
                    "raw_text_characters": len(text),
                    "raw_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "n_pages": extracted_view["n_pages"], "declared_page_joiner": "\\f",
                    "source_record": provider,
                    "source_identity": identities[extracted_view["reader"]],
                    "source_version": version, "original_target_context": context,
                    "source_members": {
                        "metadata": record["metadata_object"], "pdf": item,
                        "published_extraction_witness": witness,
                        "source_evidence_root": "source-evidence",
                        "original_queue": "input_gap_queue.parquet",
                    },
                    "helper_header_observations_not_authority":
                        extracted_view["header_observations"],
                    "archive_provider": PROVIDER, "source_status": STATUS,
                    "archive_generated_prologue_preserved": False,
                    **dict.fromkeys(FLAGS, False),
                })
                counts[context["bill_id"]] += 1
        for ordinal, version in enumerate(provider["versions"]):
            matched = linked_versions.get(version["note"], [])
            versions_out.append({
                "bill_id": context["bill_id"], "version_ordinal": ordinal,
                "provider_version": version, "published_PDF_files": matched,
                "document_dispositions": [
                    {"published_git_path": doc["published_git_path"],
                     "disposition": doc["disposition"]}
                    for doc in documents if doc["bill_id"] == context["bill_id"]
                    and doc["published_git_path"] in matched
                ],
                "disposition": "published_PDF_disposed" if matched
                else "no_uniquely_bound_published_PDF_not_admitted",
            })
        source_contexts.append({
            "original_target_context": context, "metadata_node": record["metadata_node"],
            "metadata_object": record["metadata_object"],
            "provider_bill_ID_absent_not_an_alias": True,
            "n_published_files": len(files), "n_provider_versions": len(provider["versions"]),
            "n_retained_views": counts[context["bill_id"]],
            "disposition": "reviewed_full_PDF_attempt_completed"
            if context["state"] == "MT" and context["session_identifier"] == "2025"
            else "no_published_body_files" if not files
            else "outside_reviewed_MT_2025_profile_no_annual_alias",
            **dict.fromkeys(FLAGS, False),
        })
    require(len({view["view_id"] for view in views}) == len(views), "duplicate retained view")
    contexts = queue.filter(pc.is_in(
        queue["bill_id"], value_set=pa.array(list(counts), type=queue["bill_id"].type),
    ))
    candidates = [
        {"bill_id": row["bill_id"], "state": row["state"],
         "identifier": row["identifier"], "session_identifier": row["session_identifier"],
         "n_retained_source_views": counts[row["bill_id"]],
         "disposition": "retained_provider_full_PDF" if counts[row["bill_id"]]
         else "still_unavailable_from_this_finite_source_scope"}
        for row in originals
    ]
    report = {
        "provider": PROVIDER, "status": STATUS, "source_manifest_sha256": source_sha,
        "original_gap_queue_sha256": queue_sha,
        "all_original_fields_nulls_types_order_and_queue_schema_preserved": True,
        "source_tree_replay": tree_report,
        "source_capture_invocation_accounting": {
            "selected_capture_total_logical_gh_invocations":
                capture_report["new_gh_CLI_invocations"],
            "preceding_capture_prefix_already_included_not_added":
                capture_report["closed_preceding_capture_invocations"],
            "prior_closed_discovery_logical_gh_invocations":
                capture_report["closed_prior_discovery_invocations"],
            "native_publisher_requests": 0,
            "raw_failed_prefixes_preserved_with_entire_source_inventory": True,
            "physical_HTTP_redirect_retry_counts_not_asserted": True,
        },
        "counts": {
            "original_gap_contexts": len(originals), "n_attempted_source_contexts": len(records),
            "n_attempted_MT_contexts": sum(r["original_target_context"]["state"] == "MT"
                                           for r in records),
            "n_recovered_contexts": len(counts), "n_retained_views": len(views),
            "full_retained_text_characters": sum(len(view["text"]) for view in views),
            "n_source_file_dispositions": len(files_out),
            "n_source_context_dispositions": len(source_contexts),
            "n_source_version_dispositions": len(versions_out),
            "n_raw_PDF_documents": len(documents),
            "n_raw_PDF_pages": len(pages_out) // 2,
            "n_reader_page_records": len(pages_out),
            "n_retained_view_pages": sum(v["n_pages"] for v in views),
            "n_rejected_PDF_documents": sum(
                doc["disposition"] != "complete_PDF_exact_original_context_and_formal_header"
                for doc in documents
            ),
            "remaining_unavailable_from_this_source": len(originals) - len(counts),
        },
        "PDF_document_dispositions": dict(Counter(doc["disposition"] for doc in documents)),
        "non_PDF_sources_preserved_not_admitted": True,
        "provider_ID_absence_is_not_an_alias_or_conflicting_actual_ID": True,
        "no_original_native_URL_requested_or_URL_alias_or_date_inferred": True,
        "reader_errors_never_swallowed_and_all_reader_pages_preserved": True,
        "abbreviated_headers_only_internal_consistency_not_LC_to_formal_alias": True,
        "published_extraction_prologue_never_policy_input": True,
        "native_completeness_originality_markup_or_rights_not_certified": True,
        "approval_flags": dict.fromkeys(FLAGS, False), "encoder_calls": 0,
        "native_publisher_requests": 0, "network_calls": 0, "publication": False,
    }
    return {
        "views.jsonl": views, "source_dispositions.jsonl": files_out,
        "version_dispositions.jsonl": versions_out, "document_dispositions.jsonl": documents,
        "candidate_dispositions.jsonl": candidates, "reader_pages.jsonl": pages_out,
        "source_context_dispositions.jsonl": source_contexts,
    }, contexts, report


def build_govbot(source_directory, gap_queue, out_directory, *,
                 source_manifest_sha256, gap_queue_sha256):
    source, queue = _root(source_directory), _regular(Path(gap_queue).absolute())
    out = Path(out_directory).absolute()
    require(not out.exists() and out.resolve() == out and not out.is_symlink()
            and not out.is_relative_to(source) and not source.is_relative_to(out)
            and not queue.is_relative_to(out), "new nonoverlapping output directory required")
    source_sha, queue_sha = _hash(source_manifest_sha256), _hash(gap_queue_sha256)
    source_manifest, _, _ = _source(source, source_sha)
    names = set(source_manifest["artifacts"]) | {"manifest.json"}
    before = {name: _binding(source / name) for name in sorted(names)}
    queue_before = _binding(queue)
    producers = {name: _binding(path) for name, path in DEPENDENCIES.items()}
    require(TOOLS["PyMuPDF"] == "1.28.0" and TOOLS["pypdf"] == "6.14.2",
            "reviewed exact PDF reader versions required")
    out.mkdir(parents=True)
    for name in sorted(names):
        target = out / "source-evidence" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    shutil.copyfile(queue, out / "input_gap_queue.parquet")
    products, contexts, report = _replay(
        out / "source-evidence", out / "input_gap_queue.parquet", source_sha, queue_sha,
    )
    for name, rows in products.items():
        _write_rows(out / name, rows)
    pq.write_table(contexts, out / "context_inventory.parquet")
    _write(out / "report.json", report)
    after = {name: _binding(source / name) for name in sorted(names)}
    require(_tree(source) == names and _equal(before, after)
            and _equal(queue_before, _binding(queue))
            and _equal(producers, {name: _binding(path) for name, path in DEPENDENCIES.items()}),
            "source, original queue or producer changed during normalization")
    _write(out / "source_inventory.json", before)
    _write(out / "source_immutability.json", {
        "before": before, "after": after,
        "original_queue_before": queue_before, "original_queue_after": queue_before,
        "all_original_inputs_unchanged": True,
    })
    (out / "producer").mkdir()
    for name, path in DEPENDENCIES.items():
        shutil.copyfile(path, out / "producer" / name)
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
    _write(out / "manifest.json", result)
    load_govbot(out, source_manifest_sha256=source_sha, gap_queue_sha256=queue_sha)
    return result


def load_govbot(directory, metadata=None, *, source_manifest_sha256=None, gap_queue_sha256=None):
    root = _root(directory)
    manifest = _json(root / "manifest.json")
    require(set(manifest) == {
        "schema", "provider", "status", "tools", "source_manifest_sha256", "gap_queue_sha256",
        "approvals", "counts", "packet_artifacts",
    }, "unexpected normalized manifest fields")
    require(manifest["schema"] == SCHEMA and manifest["provider"] == PROVIDER
            and manifest["status"] == STATUS and _equal(manifest["tools"], TOOLS)
            and TOOLS["PyMuPDF"] == "1.28.0" and TOOLS["pypdf"] == "6.14.2"
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
    for name, path in DEPENDENCIES.items():
        require(_equal(artifacts[f"producer/{name}"], _binding(path)),
                "installed/archived producer or extraction dependency mismatch")
    source = _root(root / "source-evidence")
    source_manifest = _json(source / "manifest.json")
    names = set(source_manifest["artifacts"]) | {"manifest.json"}
    require(set(artifacts) == PRODUCTS | {"source-evidence/" + name for name in names},
            "unexpected normalized/source inventory")
    inventory = {name: _binding(source / _relative(name)) for name in sorted(names)}
    require(_equal(_json(root / "source_inventory.json"), inventory),
            "source inventory replay mismatch")
    products, expected_contexts, report = _replay(
        source, root / "input_gap_queue.parquet",
        manifest["source_manifest_sha256"], manifest["gap_queue_sha256"],
    )
    for name, rows in products.items():
        require(_equal(list(_rows(root / name)), rows), f"full {name} replay mismatch")
    contexts = pq.read_table(root / "context_inventory.parquet")
    require(contexts.equals(expected_contexts, check_metadata=True)
            and _equal(_json(root / "report.json"), report)
            and _equal(manifest["counts"], report["counts"]),
            "original context/report replay mismatch")
    queue_binding = artifacts["input_gap_queue.parquet"]
    require(_equal(_json(root / "source_immutability.json"), {
        "before": inventory, "after": inventory,
        "original_queue_before": queue_binding, "original_queue_after": queue_binding,
        "all_original_inputs_unchanged": True,
    }), "input immutability receipt mismatch")
    context_rows = contexts.to_pylist()
    if metadata is not None:
        if isinstance(metadata, dict):
            current = list(metadata.values())
            require(all(type(row) is dict and row.get("bill_id") == key
                        for key, row in metadata.items()), "current metadata index/ID mismatch")
        else:
            current = metadata.to_pylist() if isinstance(metadata, pa.Table) else list(metadata)
        by_id = defaultdict(list)
        for row in current:
            require(type(row) is dict and type(row.get("bill_id")) is str,
                    "typed current metadata row/bill_id required")
            by_id[row["bill_id"]].append(row)
        for row in context_rows:
            matched = by_id[row["bill_id"]]
            require(len(matched) == 1, "matched original context missing or duplicated")
            original = matched[0]
            require(all(key in original for key in (
                "bill_id", "state", "identifier", "session_identifier",
            )) and all(_equal(row[key], value) for key, value in original.items() if key in row),
                "original metadata field or missingness/type changed")
    return products["views.jsonl"], context_rows, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--source-dir", type=Path, required=True)
    build.add_argument("--source-manifest-sha256", required=True)
    build.add_argument("--gap-queue", type=Path, required=True)
    build.add_argument("--gap-queue-sha256", required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--directory", type=Path, required=True)
    verify.add_argument("--source-manifest-sha256", required=True)
    verify.add_argument("--gap-queue-sha256", required=True)
    args = parser.parse_args(argv)
    anchors = {"source_manifest_sha256": args.source_manifest_sha256,
               "gap_queue_sha256": args.gap_queue_sha256}
    if args.command == "build":
        manifest = build_govbot(args.source_dir, args.gap_queue, args.out_dir, **anchors)
    else:
        manifest = load_govbot(args.directory, **anchors)[3]
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

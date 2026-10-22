"""Normalize and replay the sealed Maryland predecessor archive entirely offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import tarfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

import pyarrow as pa
import pyarrow.parquet as pq

try:
    from state_politics import provenance
except ModuleNotFoundError:  # The copied standalone producer ships this helper beside it.
    import provenance

SCHEMA = "state-politics.maryland-archive-text.v1"
PROVIDER = "windy-civi-pipelines/md-data-pipeline"
STATUS = "independent_mirror_and_extraction_not_publisher_certified"
COMMIT = "0e17cc31f8830462eed3caaf578a9f0a370ec79d"
GIT_TREE = "0a68f74d4cbeb9902d308245851d7e702dea97ba"
SOURCE_MANIFEST_SHA256 = "c047e3db19f9a79837d6e02ac92cf1ddbda22032449e65881d510155604d6337"
GAP_SHA256 = "baa3cc3cfb494f1de1096b4ae8f524c424ada73f00f79592144c2209b4578bdd"
ARCHIVE_SHA256 = "d47c374e8f5da1455b9bc1a74bdc1c61d34bafc24e1293890b3c9148ab43f9f4"
ARCHIVE_FILE = "downloads/md-0e17cc31.tar.gz"
FLAGS = (
    "scientific_approval", "model_input_approved", "training_approved",
    "publication_approved", "party_attribution_approved", "filing_time_text_certified",
    "analytical_admission", "publisher_original_verified",
)
EXTRA_FLAGS = ("training_admission", "source_date_or_party_inferred")
SOURCE_FILES = 1754
HISTORY_LIMIT = (
    "Only pinned current and initial earliest reachable commit trees were inspected; "
    "intervening/deleted/unreachable historical snapshots are not censused."
)


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible Maryland archive: {message}")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _binding(path):
    return {"sha256": provenance.sha256_file(path), "bytes": path.stat().st_size}


def _regular(path, *, allow_hardlinks=False):
    require(not path.is_symlink(), f"linked source/manifest: {path.name}")
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError(f"incompatible Maryland archive: missing artifact: {path}") from exc
    require(stat.S_ISREG(info.st_mode) and (allow_hardlinks or info.st_nlink == 1)
            and path.resolve() == path,
            f"unsafe or linked artifact: {path.name}")
    return path


def _root(directory):
    path = Path(directory).absolute()
    require(not path.is_symlink() and path.resolve() == path and path.is_dir(),
            "unsafe or linked packet directory")
    return path


def _relative(name):
    require(type(name) is str and bool(name) and "\\" not in name and "\0" not in name
            and not re.match(r"^[A-Za-z]:", name), "unsafe artifact path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts
            and path.as_posix() == name and name != ".", "unsafe artifact path")
    return name


def _decode(data):
    def distinct(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON object key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"incompatible Maryland archive: nonfinite JSON value: {value}")

    return json.loads(data, object_pairs_hook=distinct, parse_constant=invalid)


def _json(path):
    return _decode(path.read_bytes())


def _jsonl(path):
    return [_decode(line) for line in path.read_bytes().splitlines() if line]


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


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def _write_rows(path, rows):
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(
                row, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ) + "\n")


def _artifact_bindings(inventory):
    require(type(inventory) is dict, "artifact inventory must be an object")
    for name, binding in inventory.items():
        _relative(name)
        require(type(binding) is dict and set(binding) == {"sha256", "bytes"}
                and type(binding["bytes"]) is int and binding["bytes"] >= 0
                and type(binding["sha256"]) is str
                and re.fullmatch(r"[0-9a-f]{64}", binding["sha256"]),
                "invalid typed artifact binding")


def _source_inventory(source):
    source = _root(source)
    manifest_path = _regular(source / "manifest.json")
    require(_binding(manifest_path)["sha256"] == SOURCE_MANIFEST_SHA256,
            "immutable original source manifest mismatch")
    manifest = _json(manifest_path)
    inventory = manifest["packet_artifacts"]
    _artifact_bindings(inventory)
    require(len(inventory) == SOURCE_FILES, "incomplete original sealed evidence")
    for name, binding in inventory.items():
        require(_binding(_regular(source / name)) == binding,
                f"immutable original source binding mismatch: {name}")
    return {**inventory, "manifest.json": _binding(manifest_path)}


def _http(source, label):
    data = (source / "raw" / f"{label}.http").read_bytes()
    boundary = re.search(rb"\r?\n\r?\n", data)
    require(boundary is not None, "incomplete raw HTTP headers")
    header = data[:boundary.start()].decode("ascii")
    require(re.match(r"HTTP/[0-9.]+ 200\b", header), "unsuccessful retained HTTP response")
    return data[boundary.end():]


def _api(source, label):
    return _decode(_http(source, label))


def _identifier(value):
    if type(value) is not str:
        return None
    match = re.fullmatch(r"(HB|SB|HJ|SJ)\s*0*([0-9]+)", value)
    return f"{match[1]} {int(match[2])}" if match else None


def _literal_span(text, start, end, kind):
    return {
        "kind": kind, "text": text[start:end], "character_start": start,
        "character_end": end, "utf8_byte_start": len(text[:start].encode()),
        "utf8_byte_end": len(text[:end].encode()), "end_exclusive": True,
    }


def _printed(text, identifier, session, *, prologue=True):
    marker = "\nRaw Text:\n"
    if prologue:
        if text.count(marker) != 1:
            return {"disposition": "missing_or_ambiguous_complete_raw_text_section"}
        offset = text.index(marker) + len(marker)
    else:
        offset = 0
    body = text[offset:]
    patterns = (
        (r"(?im)^(?:\d+[ \t]+)?(HOUSE|SENATE)[ \t]+BILL[ \t]+([0-9]+)\b", "B"),
        (r"(?im)^\((House|Senate)[ \t]+Bill[ \t]+([0-9]+)\)", "B"),
        (r"(?im)^(?:\d+[ \t]+)?(HOUSE|SENATE)[ \t]+JOINT[ \t]+RESOLUTION"
         r"[ \t]+([0-9]+)\b", "J"),
        (r"(?im)^\((House|Senate)[ \t]+Joint[ \t]+Resolution[ \t]+([0-9]+)\)", "J"),
    )
    own = []
    for pattern, family in patterns:
        for match in re.finditer(pattern, body[:1200]):
            value = ("H" if match[1].upper() == "HOUSE" else "S") + family
            own.append((f"{value} {int(match[2])}", match))
    if not own:
        return {"disposition": "missing_printed_own_number"}
    alternatives = sorted({value for value, _ in own})
    if alternatives != [identifier]:
        return {"disposition": "printed_own_number_conflict",
                "printed_identifier_alternatives": alternatives}
    state = re.search(r"GENERAL ASSEMBLY OF MARYLAND", body)
    if not state:
        return {"disposition": "missing_explicit_printed_state"}
    years = []
    for pattern, kind in (
        (r"(?im)^Introduced and read first time:[^\n]{0,150}?\b(20[0-9]{2})\b",
         "printed_introduced_and_read_first_time_year"),
        (r"\b(20[0-9]{2})\s+LAWS OF MARYLAND\b", "printed_laws_of_maryland_year"),
        (r"(?im)\b(20[0-9]{2})\s+(?:REGULAR\s+)?SESSION\b", "printed_session_label"),
    ):
        for match in re.finditer(pattern, body):
            years.append((match[1], match, kind))
    alternatives = sorted({year for year, _, _ in years})
    if not years:
        return {"disposition": "missing_explicit_printed_session_evidence"}
    if alternatives != [session]:
        return {"disposition": "printed_session_conflict",
                "printed_session_alternatives": alternatives}
    own_match = own[0][1]
    year, year_match, kind = years[0]
    return {
        "disposition": "exact_existing_gap_identity", "printed_identifier": identifier,
        "printed_session": year, "printed_state": "MD", "raw_body_character_start": offset,
        "identity_spans": [
            _literal_span(text, offset + own_match.start(), offset + own_match.end(),
                          "printed_own_bill_header"),
            _literal_span(text, offset + state.start(), offset + state.end(),
                          "printed_state_enacting_clause"),
            _literal_span(text, offset + year_match.start(), offset + year_match.end(), kind),
        ],
        "session_evidence_limit": (
            "Literal bill-facing year plus original session metadata; no date, filing-time, "
            "or introduced-version certification."
        ),
    }


def printed_identity(text, identifier, session_identifier):
    """Return literal printed evidence and the exact policy-section boundary, without slicing."""
    require(type(text) is str and type(identifier) is str
            and type(session_identifier) is str, "typed printed identity required")
    prologue = text.startswith("Title: ")
    result = _printed(text, identifier, session_identifier, prologue=prologue)
    require(result["disposition"] == "exact_existing_gap_identity",
            f"unresolved printed identity: {result['disposition']}")
    section_start = 0
    if prologue:
        sections = list(re.finditer(r"(?m)^Section 1:[ \t]*\r?\n", text))
        require(len(sections) == 1 and sections[0].end() < result["raw_body_character_start"],
                "missing or ambiguous extractor policy section")
        section_start = sections[0].end()
    return {
        "state": "MD", "session_identifier": session_identifier, "identifier": identifier,
        "printed_evidence": [
            {"start": span["character_start"], "end": span["character_end"],
             "text": span["text"]} for span in result["identity_spans"]
        ],
        "policy_section_start": section_start,
        "archive_extractor_prologue_preserved": prologue,
        "session_evidence_limit": result["session_evidence_limit"],
    }


def _censuses(source):
    results = {}
    for state in ("OK", "NE", "CT", "MD"):
        prefix = state.lower()
        current = _api(source, f"{prefix}-current-commit")[0]
        earliest = _api(source, f"{prefix}-earliest-commit")[0]
        tree = _api(source, f"{prefix}-current-tree")
        old = _api(source, f"{prefix}-earliest-tree")
        path = f"country:us/state:{prefix}/sessions/"
        require(current["commit"]["tree"]["sha"] == tree["sha"]
                and earliest["commit"]["tree"]["sha"] == old["sha"]
                and old["truncated"] is False, "source commit/tree binding")
        if tree["truncated"] is True:
            full = _api(source, f"{prefix}-current-sessions")
            session_tree = next(entry for entry in tree["tree"]
                                if entry["path"] == path.rstrip("/"))
            require(full["sha"] == session_tree["sha"] and full["truncated"] is False,
                    "truncated source is not a complete session census")
            sessions = [entry["path"] for entry in full["tree"] if entry["type"] == "tree"]
            response = f"raw/{prefix}-current-sessions.http"
        else:
            require(tree["truncated"] is False, "typed truncation flag")
            sessions = [
                entry["path"][len(path):] for entry in tree["tree"]
                if entry["type"] == "tree" and entry["path"].startswith(path)
                and "/" not in entry["path"][len(path):]
            ]
            response = f"raw/{prefix}-current-tree.http"
        results[state] = {
            "state": state, "repository": f"windy-civi-pipelines/{prefix}-data-pipeline",
            "current_commit": current["sha"], "current_root_tree": tree["sha"],
            "current_recursive_tree_truncated": tree["truncated"],
            "current_session_census_complete": True, "current_sessions": sorted(sessions),
            "current_session_census_response": response, "earliest_commit": earliest["sha"],
            "earliest_commit_author_date": earliest["commit"]["author"]["date"],
            "earliest_commit_message": earliest["commit"]["message"],
            "earliest_tree": old["sha"], "earliest_tree_complete": True,
            "earliest_tree_entries": len(old["tree"]),
            "earliest_sessions": [
                entry["path"][len(path):] for entry in old["tree"]
                if entry["type"] == "tree" and entry["path"].startswith(path)
                and "/" not in entry["path"][len(path):]
            ], "scope_limit": HISTORY_LIMIT,
        }
    require(_equal(results, _json(source / "source-metadata.json")),
            "original complete source census replay mismatch")
    require(results["MD"]["current_commit"] == COMMIT
            and results["MD"]["current_root_tree"] == GIT_TREE, "wrong predecessor source")
    return results


def _git(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).digest()


def _scan(source, targets):
    tree = _api(source, "md-current-tree")
    require(tree["sha"] == GIT_TREE and tree["truncated"] is False,
            "complete pinned Git tree required")
    entries = {entry["path"]: entry for entry in tree["tree"]}
    require(len(entries) == len(tree["tree"]), "duplicate Git tree path")
    archive_path = source / ARCHIVE_FILE
    require(_binding(archive_path) == {"bytes": 33170244, "sha256": ARCHIVE_SHA256},
            "pinned full archive mismatch")
    require(_http(source, "md-source-archive") == archive_path.read_bytes(),
            "original complete HTTP archive body mismatch")
    metadata, texts, inventory, nodes = {}, [], [], defaultdict(dict)
    seen = set()
    bindings = {}
    total_bytes = 0
    with tarfile.open(archive_path, "r|gz") as archive:
        for ordinal, member in enumerate(archive):
            require(ordinal < 50000 and (member.isfile() or member.isdir()),
                    "linked, special or excessive archive member")
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and ".." not in path.parts
                    and path.as_posix() == member.name.rstrip("/")
                    and path.parts[0] == f"md-data-pipeline-{COMMIT}", "unsafe archive member")
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            if relative == ".":
                require(ordinal == 0 and member.isdir(), "duplicate or non-directory archive root")
                continue
            _relative(relative)
            require(relative not in seen and relative in entries,
                    "extra or duplicate archive member")
            seen.add(relative)
            entry = entries[relative]
            record = {
                "archive_member": member.name, "path": relative, "bytes": member.size,
                "kind": "file" if member.isfile() else "directory",
            }
            if member.isdir():
                require(entry["type"] == "tree" and entry["mode"] == "040000",
                        "archive directory/Git tree mismatch")
                nodes[relative]
            else:
                require(0 <= member.size <= 100000000, "oversized archive member")
                total_bytes += member.size
                require(total_bytes <= 500000000, "uncompressed archive byte ceiling")
                data = archive.extractfile(member).read()
                blob = _git("blob", data)
                mode = b"100755" if member.mode & 0o111 else b"100644"
                require(len(data) == member.size and entry["type"] == "blob"
                        and entry["size"] == len(data) and entry["sha"] == blob.hex()
                        and entry["mode"].encode() == mode, "archive/Git blob binding mismatch")
                parent = PurePosixPath(relative).parent.as_posix()
                parent = "" if parent == "." else parent
                nodes[parent][path.name] = (mode, blob)
                record.update(sha256=_sha(data), git_blob_sha=blob.hex(), git_blob_verified=True)
                parts = PurePosixPath(relative).parts
                if len(parts) >= 7 and parts[:5] == (
                    "country:us", "state:md", "sessions", "2025", "bills",
                ):
                    identifier = _identifier(parts[5])
                    if identifier in targets and (
                        len(parts) == 7 and parts[-1] == "metadata.json"
                        or len(parts) == 8 and parts[6] == "files"
                        and parts[-1].endswith("_extracted.txt")
                    ):
                        local = f"sources/{relative}"
                        require((source / local).read_bytes() == data,
                                "original complete raw byte file differs from archive")
                        record["complete_local_byte_file"] = local
                        if parts[-1] == "metadata.json":
                            require(identifier not in metadata, "duplicate original bill metadata")
                            metadata[identifier] = (_decode(data), record, data)
                        else:
                            texts.append((identifier, data, record))
                bindings[relative] = {
                    "archive_file": f"source-evidence/{ARCHIVE_FILE}",
                    "archive_member": member.name, "archive_ordinal": ordinal,
                    "archive_relative_path": relative, "bytes": len(data),
                    "sha256": _sha(data), "git_blob_sha1": blob.hex(),
                }
            inventory.append(record)
    require(seen == set(entries), "incomplete full archive/file tree")
    for directory in sorted(nodes, key=lambda value: (value.count("/"), len(value)), reverse=True):
        children = nodes[directory]
        names = sorted(children, key=lambda name: name.encode() + (
            b"/" if children[name][0] == b"40000" else b""
        ))
        body = b"".join(mode + b" " + name.encode() + b"\0" + digest
                        for name in names for mode, digest in [children[name]])
        digest = _git("tree", body)
        require(digest.hex() == (GIT_TREE if directory == "" else entries[directory]["sha"]),
                "full reconstructed Git tree mismatch")
        if directory:
            parent = PurePosixPath(directory).parent.as_posix()
            parent = "" if parent == "." else parent
            nodes[parent][PurePosixPath(directory).name] = (b"40000", digest)
    require(_equal(inventory, _jsonl(source / "archive-inventory.jsonl")),
            "complete original archive inventory replay mismatch")
    return metadata, texts, bindings, inventory, total_bytes, entries


def _replay(source, gap):
    original_rows = gap.to_pylist()
    original = {row["bill_id"]: row for row in original_rows}
    require(len(original) == len(original_rows) == 22139
            and all(row["neither_source_observed"] is True for row in original_rows),
            "complete original v10 gap universe required")
    require(_binding(source / "inputs/input_gap_queue.parquet")["sha256"] == GAP_SHA256
            and gap.equals(pq.read_table(source / "inputs/input_gap_queue.parquet"),
                           check_metadata=True), "original v10 queue changed")
    owned = [row for row in original_rows if row["state"] in {"OK", "NE", "CT", "MD"}]
    require(Counter(row["state"] for row in owned) == {
        "OK": 3336, "NE": 1812, "CT": 1097, "MD": 990,
    }, "original owned contexts changed")
    targets = {
        row["identifier"]: row for row in owned
        if row["state"] == "MD" and row["session_identifier"] == "2025"
    }
    require(len(targets) == 563 and all(
        _identifier(identifier) == identifier for identifier in targets
    ), "ambiguous or typed original target identity")
    censuses = _censuses(source)
    ledger = _jsonl(source / "request-ledger.jsonl")
    require(len(ledger) == 18 and sum(row["physical_exchanges"] for row in ledger) == 18
            and all(row["returncode"] == 0 and not row["stop_reason"]
                    and set(row["statuses"]) == {200} for row in ledger),
            "original bounded request ledger mismatch")
    for row in ledger:
        require(_binding(source / _relative(row["response_file"])) == {
            "bytes": row["response_bytes"], "sha256": row["response_sha256"],
        }, "original raw request binding mismatch")
    metadata, texts, bindings, inventory, total_bytes, entries = _scan(source, targets)
    country_tree = entries["country:us"]["sha"]
    retained_members = {
        kind: {"path": f"source-evidence/{name}", **_binding(source / name)}
        for kind, name in (
            ("git_tree", "raw/md-current-tree.http"),
            ("http_archive", "raw/md-source-archive.http"),
            ("http_ledger", "request-ledger.jsonl"),
        )
    }
    old_dispositions = _jsonl(source / "source-view-dispositions.jsonl")
    old_views = _jsonl(source / "views.jsonl")
    require(len(old_dispositions) == len(texts) == 1127 and len(old_views) == 1070,
            "original source view counts mismatch")
    source_flags = _json(source / "manifest.json")["approvals"]
    dispositions, rows, accepted_old, original_ordinals = [], [], [], []
    for identifier, data, record in texts:
        require(identifier in metadata, "missing original archived bill metadata")
        meta, meta_record, meta_bytes = metadata[identifier]
        require(type(meta["legislative_session"]) is str
                and meta["legislative_session"] == "2025"
                and _identifier(meta["identifier"]) == identifier
                and meta["jurisdiction"]["id"]
                == "ocd-jurisdiction/country:us/state:md/government",
                "original metadata state/session/own number conflict")
        text = data.decode("utf-8", errors="strict")
        identity = _printed(text, identifier, "2025")
        note = re.search(r"(?m)^Source: versions - ([^\n]*)$", text)
        versions = [version for version in meta.get("versions", [])
                    if note and version.get("note") == note[1]]
        source_record = {
            "identifier": identifier, "session_identifier": "2025", "state": "MD", **record,
            "original_metadata_file": meta_record["complete_local_byte_file"],
            "original_metadata_sha256": _sha(meta_bytes), **identity,
            "original_version_alternatives": versions,
            "extraction_source_note": note[1] if note else None,
        }
        if identity["disposition"] == "exact_existing_gap_identity" and not versions:
            source_record["disposition"] = "unbound_original_version_note"
        pdf_path = record["path"].removesuffix("_extracted.txt") + ".pdf"
        pdf = bindings.get(pdf_path)
        source_record["paired_archived_pdf"] = entries.get(pdf_path)
        dispositions.append(source_record)
        if source_record["disposition"] != "exact_existing_gap_identity":
            continue
        context = targets[identifier]
        view_id = _sha((context["bill_id"] + "\0" + record["path"] + "\0"
                        + record["sha256"]).encode())
        original_view = {
            **source_record, "view_id": view_id, "bill_id": context["bill_id"],
            "provider": PROVIDER, "source_commit": COMMIT,
            "source_kind": "independent_archived_government_records", "source_text": text,
            "text_utf8_bytes": len(data), "original_metadata": meta,
            "original_queue_record": context, "approvals": source_flags,
            "complete_byte_file": record["complete_local_byte_file"],
            "limitations": [
                "Complete existing machine extraction retained unchanged, including prologue, "
                "section/raw duplication, and possible annotation artifacts.",
                "No markup, introduced-version, filing-time, scientific, publisher, "
                "redistribution, date, party, or model approval.",
                "Later-labelled 2025 prefilings are matched only to existing queue identities; "
                "the January 2023–December 2024 existing-date cohort is unchanged.",
            ],
        }
        accepted_old.append(original_view)
        require(_equal(original_view, old_views[len(accepted_old) - 1]),
                "complete original metadata/header/body/context/source-view replay mismatch")
        require(pdf is not None, "complete paired original PDF required")
        alternatives = [
            {"version": version, "link": link}
            for version in versions for link in version.get("links", [])
        ]
        require(bool(alternatives), "original exact metadata version/link required")
        members = {}
        for kind, relative, local in (
            ("text", record["path"], record["complete_local_byte_file"]),
            ("metadata", meta_record["path"], meta_record["complete_local_byte_file"]),
            ("pdf", pdf_path, None),
        ):
            members[kind] = {**bindings[relative]}
            if local:
                members[kind]["path"] = f"source-evidence/{local}"
        members["original_view"] = {
            "path": "source-evidence/views.jsonl", "source_row_ordinal": len(accepted_old),
        }
        members.update(retained_members)
        printed = printed_identity(text, identifier, "2025")
        rows.append({
            "source_type": "archive_text", "view_id": f"archive:md:{view_id}",
            "bill_id": context["bill_id"], "state": "MD", "identifier": identifier,
            "session_identifier": "2025", "title": context["title"], "text": text,
            "raw_text_characters": len(text), "raw_text_sha256": _sha(data),
            "source_record": original_view, "source_identity": printed,
            "source_version": {**alternatives[0], "alternatives": alternatives},
            "source_members": members, "archive_provider": PROVIDER, "archive_commit": COMMIT,
            "archive_git_tree": GIT_TREE, "archive_country_git_tree": country_tree,
            "archive_generated_prologue_preserved":
                printed["archive_extractor_prologue_preserved"],
            "source_status": STATUS, **dict.fromkeys((*FLAGS, *EXTRA_FLAGS), False),
        })
        original_ordinals.append(context)
    require(_equal(dispositions, old_dispositions),
            "all original negative/source dispositions changed")
    require(_equal(original_ordinals, pq.read_table(
        source / "matched-context-view-original-rows.parquet",
    ).to_pylist()), "original per-view full queue rows changed")
    coverage = Counter(row["bill_id"] for row in rows)
    candidates = []
    for context in owned:
        present = context["session_identifier"] in censuses[context["state"]]["current_sessions"]
        reason = (
            "new_exact_existing_context_views" if context["bill_id"] in coverage
            else "target_session_not_in_complete_current_census_and_initial_tree_empty"
            if not present else (
                "original_bill_metadata_present_but_no_admissible_printed_identity_view"
            )
        )
        candidates.append({
            **context, "predecessor_disposition": reason,
            "new_context_views": coverage[context["bill_id"]],
            "predecessor_current_commit": censuses[context["state"]]["current_commit"],
            "bounded_history_limit": HISTORY_LIMIT,
        })
    require(_equal(candidates, pq.read_table(
        source / "candidate-dispositions.parquet",
    ).to_pylist()), "all original missing candidate dispositions changed")
    contexts = gap.filter(pa.array([row["bill_id"] in coverage for row in original_rows]))
    source_counts = dict(Counter(row["disposition"] for row in dispositions))
    require(len(rows) == 1070 and len(coverage) == 563 and source_counts == {
        "exact_existing_gap_identity": 1070,
        "missing_explicit_printed_session_evidence": 51, "missing_printed_own_number": 6,
    }, "replayed wrong source-view/context/rejection counts")
    counts = {
        "text_views": len(rows), "newly_covered_contexts": len(coverage),
        "original_gap_contexts": len(original_rows), "original_owned_gap_contexts": len(owned),
        "original_target_metadata_records": len(metadata), "source_text_candidates": len(texts),
        "rejected_source_views": len(texts) - len(rows), "identity_conflicts": 0,
        "bounded_negative_contexts": len(owned) - len(coverage),
        "source_dispositions": source_counts, "text_views_by_state": {"MD": len(rows)},
        "contexts_by_state_session": {"MD:2025": len(coverage)},
        "archive_members": len(inventory) + 1,
        "archive_git_blobs": len(bindings), "uncompressed_file_bytes": total_bytes,
    }
    original_report = _json(source / "report.json")
    report = {
        "counts": counts, "approvals": dict.fromkeys(FLAGS, False),
        "source_status": STATUS, "complete_git_root_tree_reconstructed": GIT_TREE,
        "source_license_observations": original_report["license_observations"],
        "negative_scope": original_report["negative_scope"], "source_censuses": censuses,
        "source_physical_http_exchanges": 18, "new_physical_http_exchanges": 0,
        "source_campaign_remains_closed": True,
        "source_record_preservation": "Every original full record, null, version/link alternative, "
                                      "negative disposition, helper, tar, and manifest is copied.",
        "cohort": "Only existing original v10 gap identities; January 2023–December 2024 "
                  "existing-date cohort unchanged. Maryland 2025 labels are existing prefilings.",
        "prologue": "Complete original text retained; policy_section_start is the exact character "
                    "following the Section 1 heading newline. No body or raw duplication removed.",
    }
    return rows, contexts, candidates, dispositions, inventory, report


def _helpers():
    return {
        "producer/maryland_archive_text.py": Path(__file__).absolute(),
        "producer/provenance.py": Path(provenance.__file__).absolute(),
    }


def _handoff(report):
    return {
        "schema": SCHEMA, "provider": PROVIDER, "status": STATUS,
        "api": "state_politics.bills.maryland_archive_text.load_maryland"
               "(directory, metadata=None) -> (rows, contexts, pins, manifest)",
        "builder": "state_politics.bills.maryland_archive_text.build_maryland"
                   "(source_directory, gap_queue, out_directory)",
        "standalone": "producer/maryland_archive_text.py build --source-dir SOURCE "
                      "--gap-queue V10_GAP --out-dir NEW_DIRECTORY; "
                      "producer/maryland_archive_text.py replay --directory PACKET "
                      "[--metadata CURRENT_BILLS_PARQUET]",
        "counts": report["counts"], "pins": "manifest.json :: packet_artifacts; "
                                           "load_maryland additionally pins manifest.json",
        "source_provenance": {
            "repository": PROVIDER, "commit": COMMIT, "complete_root_git_tree": GIT_TREE,
            "complete_tar_sha256": ARCHIVE_SHA256,
            "original_sealed_manifest_sha256": SOURCE_MANIFEST_SHA256,
            "original_v10_full_gap_sha256": GAP_SHA256,
            "complete_original_artifacts_copied_including_manifest": SOURCE_FILES + 1,
            "original_physical_http_exchanges": 18, "new_physical_http_exchanges": 0,
            "source_evidence": "source-evidence/",
        },
        "license_observations": report["source_license_observations"],
        "approvals": dict.fromkeys((*FLAGS, *EXTRA_FLAGS), False),
        "cohort": report["cohort"], "negative_scope": report["negative_scope"],
        "prologue": report["prologue"],
        "validation": "Every successful load independently replays the complete pinned Git tree, "
                      "all original archive records/body/header/metadata/queue bindings, all "
                      "negative dispositions, and all normalized typed fields and approvals.",
        "test_suite": "tests/test_maryland_archive_text.py",
        "shared_integration_or_model_execution_performed": False,
    }


def build_maryland(source_directory: Path, gap_queue: Path, out_directory: Path):
    """Copy sealed evidence with copy2 and normalize exactly 563 unchanged original contexts."""
    source = _root(source_directory)
    gap_queue = _regular(Path(gap_queue).absolute())
    out = Path(out_directory).absolute()
    require(not out.exists() and not out.is_symlink() and out.resolve() == out,
            "new unlinked output directory required")
    require(not out.is_relative_to(source), "output cannot mutate original source evidence")
    before = _source_inventory(source)
    times = {name: (source / name).stat().st_mtime_ns for name in before}
    require(_binding(gap_queue)["sha256"] == GAP_SHA256, "original complete v10 gap queue required")
    out.mkdir(parents=True)
    evidence = out / "source-evidence"
    evidence.mkdir()
    for name in before:
        target = evidence / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    shutil.copy2(gap_queue, out / "input_gap_queue.parquet")
    require(_source_inventory(evidence) == before, "source copy was not lossless")
    rows, contexts, candidates, dispositions, inventory, report = _replay(
        evidence, pq.read_table(out / "input_gap_queue.parquet"),
    )
    _write_rows(out / "views.jsonl", rows)
    pq.write_table(contexts, out / "context_inventory.parquet")
    pq.write_table(pa.Table.from_pylist(candidates), out / "candidate_dispositions.parquet")
    _write_rows(out / "source_view_dispositions.jsonl", dispositions)
    _write_rows(out / "archive_inventory.jsonl", inventory)
    _write(out / "report.json", report)
    _write(out / "handoff.json", _handoff(report))
    (out / "producer").mkdir()
    for name, path in _helpers().items():
        shutil.copy2(path, out / name)
    names = {
        *(f"source-evidence/{name}" for name in before), *_helpers(),
        "input_gap_queue.parquet", "views.jsonl", "context_inventory.parquet",
        "candidate_dispositions.parquet", "source_view_dispositions.jsonl",
        "archive_inventory.jsonl", "report.json", "handoff.json",
    }
    manifest = {
        "schema": SCHEMA, "provider": PROVIDER, "status": STATUS,
        "approvals": dict.fromkeys(FLAGS, False), "counts": report["counts"],
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256, "gap_queue_sha256": GAP_SHA256,
        "source_commit": COMMIT, "source_git_tree": GIT_TREE,
        "source_original_artifacts": SOURCE_FILES,
        "source_files_copied_including_manifest": len(before),
        "packet_artifacts": {name: _binding(out / name) for name in sorted(names)},
    }
    _write(out / "manifest.json", manifest)
    require(_source_inventory(source) == before
            and {name: (source / name).stat().st_mtime_ns for name in before} == times,
            "immutable original source changed")
    load_maryland(out)
    return manifest


def load_maryland(directory: Path, metadata=None):
    """Strictly replay all source bindings; return rows, unchanged contexts, pins, manifest."""
    directory = _root(directory)
    manifest_path = _regular(directory / "manifest.json")
    manifest = _json(manifest_path)
    require(type(manifest) is dict and manifest.get("schema") == SCHEMA
            and manifest.get("provider") == PROVIDER and manifest.get("status") == STATUS,
            "schema/provider/status mismatch")
    require(set(manifest) == {
        "schema", "provider", "status", "approvals", "counts", "source_manifest_sha256",
        "gap_queue_sha256", "source_commit", "source_git_tree", "source_original_artifacts",
        "source_files_copied_including_manifest", "packet_artifacts",
    }, "incomplete or unexpected manifest fields")
    require(type(manifest.get("approvals")) is dict
            and set(manifest["approvals"]) == set(FLAGS)
            and all(manifest["approvals"][flag] is False for flag in FLAGS),
            "source approval promotion")
    require(manifest.get("source_manifest_sha256") == SOURCE_MANIFEST_SHA256
            and manifest.get("gap_queue_sha256") == GAP_SHA256
            and manifest.get("source_commit") == COMMIT
            and manifest.get("source_git_tree") == GIT_TREE, "original input trust anchors")
    artifacts = manifest.get("packet_artifacts")
    _artifact_bindings(artifacts)
    pins = {"manifest.json": _binding(manifest_path)["sha256"]}
    for name, binding in artifacts.items():
        require(_binding(_regular(directory / name)) == binding,
                f"packet artifact binding mismatch: {name}")
        pins[name] = binding["sha256"]
    source = directory / "source-evidence"
    original = _source_inventory(source)
    expected = {
        *(f"source-evidence/{name}" for name in original), *_helpers(),
        "input_gap_queue.parquet", "views.jsonl", "context_inventory.parquet",
        "candidate_dispositions.parquet", "source_view_dispositions.jsonl",
        "archive_inventory.jsonl", "report.json", "handoff.json",
    }
    require(set(artifacts) == expected, "incomplete or unexpected packet artifacts")
    require(all(_binding(directory / name) == _binding(path)
                for name, path in _helpers().items()), "producer/helper module mismatch")
    require(_binding(directory / "input_gap_queue.parquet")["sha256"] == GAP_SHA256,
            "original complete v10 gap queue mismatch")
    replay, contexts, candidates, dispositions, inventory, report = _replay(
        source, pq.read_table(directory / "input_gap_queue.parquet"),
    )
    rows = _jsonl(directory / "views.jsonl")
    require(_equal(rows, replay), "complete record/text/typed identity/approval replay mismatch")
    context_table = pq.read_table(directory / "context_inventory.parquet")
    require(context_table.equals(contexts, check_metadata=True),
            "unchanged original context inventory mismatch")
    require(_equal(pq.read_table(directory / "candidate_dispositions.parquet").to_pylist(),
                   candidates)
            and _equal(_jsonl(directory / "source_view_dispositions.jsonl"), dispositions)
            and _equal(_jsonl(directory / "archive_inventory.jsonl"), inventory),
            "complete negative/source/inventory disposition replay mismatch")
    require(_equal(_json(directory / "report.json"), report)
            and _equal(_json(directory / "handoff.json"), _handoff(report))
            and _equal(manifest["counts"], report["counts"])
            and type(manifest["source_original_artifacts"]) is int
            and manifest["source_original_artifacts"] == SOURCE_FILES
            and type(manifest["source_files_copied_including_manifest"]) is int
            and manifest["source_files_copied_including_manifest"] == SOURCE_FILES + 1,
            "complete report/source/view counts mismatch")
    context_rows = contexts.to_pylist()
    if metadata is not None:
        _current_metadata(context_rows, metadata)
    return rows, context_rows, pins, manifest


def _current_metadata(contexts, metadata):
    current = metadata.to_pylist() if isinstance(metadata, pa.Table) else list(metadata)
    current_by_id = defaultdict(list)
    for row in current:
        require(isinstance(row, dict) and type(row.get("bill_id")) is str,
                "typed current candidate identity required")
        current_by_id[row["bill_id"]].append(row)
    for context in contexts:
        matches = current_by_id[context["bill_id"]]
        require(len(matches) == 1 and all(
            type(matches[0].get(key)) is str and matches[0][key] == context[key]
            for key in ("state", "identifier", "session_identifier")
        ), "current candidate identity mismatch or duplicate")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--source-dir", type=Path, required=True)
    build.add_argument("--gap-queue", type=Path, required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("--directory", type=Path, required=True)
    replay.add_argument("--metadata", type=Path)
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_maryland(args.source_dir, args.gap_queue, args.out_dir)
    else:
        _, contexts, _, manifest = load_maryland(args.directory)
        if args.metadata is not None:
            metadata = pq.read_table(
                _regular(args.metadata.absolute(), allow_hardlinks=True),
                columns=["bill_id", "state", "identifier", "session_identifier"],
                filters=[("bill_id", "in", [row["bill_id"] for row in contexts])],
            )
            _current_metadata(contexts, metadata)
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

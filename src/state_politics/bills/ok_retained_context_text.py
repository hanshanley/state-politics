"""Offline, replayable exact-document relations across distinct Oklahoma annual contexts.

House publications establish legislature context, not bill-specific carryover or filing
status. The bodies remain third-party OpenStates snapshot extractions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA = "state-politics.ok-retained-context-text.v1"
STATUS = "third_party_snapshot_extraction_same_legislature_exact_document_not_filing_certified"
RELATION = "distinct_annual_contexts_of_same_legislature_with_exact_existing_document_pointers"
RELATION_KIND = "same_legislature_exact_existing_document_pointer"
CONDITIONAL_SHA256 = "0bf6d7f7ccf15575cb716af9fff07833fd2a9578b2e9a103aeb5e015d7b7a480"
HOUSE_SHA256 = "a59fea589165294a5a1eadaeea5530eeca4e63f67f937a93056cd72d47f8827d"
REVIEW_SHA256 = "a4faa683616789d8dfbace0f25249b4d6a2178dd3325e8598c7e66870e4bdc24"
QUEUE_SHA256 = "839b4874c7c8343caf3ecb831f1179f70691c27e92cf10af9372cf2acba5eb69"
FLAGS = (
    "scientific_approval", "model_input_approved", "training_approved", "training_admission",
    "native_identity_certified", "native_original_verified", "publisher_original_verified",
    "native_approved", "publisher_approved",
    "source_rights_approved", "rights_approved", "filing_time_text_certified",
    "party_attribution_approved", "publication_approved", "analytical_admission",
    "canonical_population_admission", "bill_specific_carryover_status_inferred",
    "source_date_or_party_inferred",
)
TYPES = {
    ("HOUSE", "BILL"): "HB", ("SENATE", "BILL"): "SB",
    ("HOUSE", "JOINT RESOLUTION"): "HJR", ("SENATE", "JOINT RESOLUTION"): "SJR",
    ("HOUSE", "CONCURRENT RESOLUTION"): "HCR", ("SENATE", "CONCURRENT RESOLUTION"): "SCR",
    ("HOUSE", "RESOLUTION"): "HR", ("SENATE", "RESOLUTION"): "SR",
}
ALLOWED = {"HB", "SB", "HJR", "SJR"}
GENERATED = {
    "views.jsonl", "context_inventory.parquet", "candidate_dispositions.parquet",
    "source_dispositions.jsonl", "report.json", "reviewed_house_replay.json",
    "input_gap_queue.parquet", "source_immutability.json",
    "producer/ok_retained_context_text.py",
}


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible OK retained context: {message}")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _regular(path):
    require(path.resolve() == path and not path.is_symlink(), f"linked artifact: {path}")
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError(f"incompatible OK retained context: missing artifact: {path}") from exc
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, f"unsafe artifact: {path}")
    return path


def _root(path):
    path = Path(path).absolute()
    require(path.is_dir() and path.resolve() == path and not path.is_symlink(),
            "unlinked packet root required")
    return path


def _relative(name):
    require(type(name) is str and name and "\\" not in name and "\0" not in name,
            "unsafe relative artifact path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts
            and path.as_posix() == name and name != "." and ":" not in path.parts[0],
            "unsafe relative artifact path")
    return name


def _binding(path):
    _regular(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def _decode(value):
    def unique(pairs):
        result = {}
        for key, item in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = item
        return result

    def invalid(value):
        raise ValueError(f"incompatible OK retained context: nonfinite JSON {value}")

    return json.loads(value, object_pairs_hook=unique, parse_constant=invalid)


def _json(path):
    return _decode(_regular(path).read_bytes())


def _rows(path):
    with _regular(path).open("rb") as stream:
        for ordinal, line in enumerate(stream, 1):
            require(bool(line.strip()), "blank source record")
            yield ordinal, _decode(line), _sha(line)


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def _write_rows(path, rows):
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(
                row, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ) + "\n")


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


def _walk(root):
    files = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            require(not path.is_symlink() and path.resolve() == path, "linked packet member")
            if path.is_dir():
                require(len(path.relative_to(root).parts) <= 10, "packet directory depth")
                pending.append(path)
            else:
                _regular(path)
                files.add(path.relative_to(root).as_posix())
                require(len(files) <= 1000, "bounded packet inventory exceeded")
    return files


def _inventory(directory, expected_sha, *, house=False):
    root = _root(directory)
    manifest_name = "manifest.json" if house else "packet_manifest.json"
    require(_binding(root / manifest_name)["sha256"] == expected_sha,
            "immutable original source manifest mismatch")
    manifest = _json(root / manifest_name)
    artifacts = manifest["artifacts" if house else "outputs"]
    result = {}
    for name, binding in artifacts.items():
        _relative(name)
        expected = {key: binding[key] for key in ("sha256", "bytes")}
        require(type(expected["bytes"]) is int and expected["bytes"] >= 0
                and type(expected["sha256"]) is str
                and re.fullmatch("[0-9a-f]{64}", expected["sha256"]),
                "invalid typed source binding")
        require(_binding(root / name) == expected, f"immutable source binding mismatch: {name}")
        result[name] = expected
    result[manifest_name] = _binding(root / manifest_name)
    if not house:
        result["handoff.json"] = _binding(root / "handoff.json")
        require(_json(root / "handoff.json")["packet_manifest"]["sha256"] == expected_sha,
                "original conditional handoff binding")
    require(_walk(root) == set(result), "incomplete or unexpected source inventory")
    return result


class _Nodes(HTMLParser):
    """Visible source nodes, with original character offsets; never execute HTML."""

    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self.starts = [0] + [match.end() for match in re.finditer("\n", raw)]
        self.stack, self.nodes = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in {
            "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr",
        }:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]

    def handle_data(self, text):
        line, column = self.getpos()
        start = self.starts[line - 1] + column
        end = self.raw.find("<", start)
        self.nodes.append({
            "text": text, "tag_path": list(self.stack),
            "raw_source_start": start, "raw_source_end": len(self.raw) if end < 0 else end,
            "visible_text_not_script_style_noscript": not any(
                tag in self.stack for tag in ("script", "style", "noscript")
            ),
        })


def _house_witnesses(root):
    """Independently derive both annual witnesses from full original HTTP HTML."""
    reviewed = _json(root / "reviewed-session-context.json")
    require(_binding(root / "reviewed-session-context.json")["sha256"] == REVIEW_SHA256,
            "reviewed primary context binding")
    ledger = [row for _, row, _ in _rows(root / "request-ledger.jsonl")]
    require([row["status"] for row in ledger] == [404, 200, 200, 200]
            and [row["ordinal"] for row in ledger] == [1, 2, 3, 4],
            "original four House exchanges")
    for capture in ledger:
        name = _relative(capture["body"])
        path = root / name
        transport = _json(path.with_suffix(".transport.json"))
        headers = path.with_suffix(".headers").read_text()
        require(capture["host"] == "www.okhouse.gov" and capture["curl_returncode"] == 0
                and capture["automatic_retries"] is False
                and capture["automatic_redirects"] is False
                and _binding(path) == capture["body_binding"]
                and transport["http_code"] == capture["status"]
                and transport["url_effective"] == capture["url"]
                and transport["num_redirects"] == 0 and transport["ssl_verify_result"] == 0
                and re.search(r"(?m)^HTTP/\S+\s+" + str(capture["status"]) + r"\b", headers),
                "retained House HTTP entity/transport binding")
    batch = _json(root / "source-batch.json")
    specs = {
        "2023-session-announcement": (
            "2023", "first session of the 59th Legislature",
            "House Completes Bill Filing for 2023 Session", "Jan 20, 2023",
        ),
        "2024-session-announcement": (
            "2024", "second regular session of the 59th Legislature",
            "House Completes Bill Filing for 2024 Session", "Jan 19, 2024",
        ),
    }
    witnesses = {}
    require(len(batch["documents"]) == 3, "three complete House HTML publications required")
    for document in batch["documents"]:
        capture, label = document["capture"], document["label"]
        require(_equal(capture, ledger[capture["ordinal"] - 1]), "House source-batch receipt")
        raw = (root / _relative(capture["body"])).read_text()
        parser = _Nodes(raw)
        parser.feed(raw)
        parser.close()
        require(_equal(_json(root / f"{label}-complete-source-nodes.json"), {
            "capture": capture, "all_original_HTML_text_nodes": parser.nodes,
            "raw_HTML_preserved": True,
        }), "complete original House HTML node replay")
        if label not in specs:
            continue
        year, phrase, title, date = specs[label]
        visible = [node for node in parser.nodes
                   if node["visible_text_not_script_style_noscript"] and "main" in node["tag_path"]]
        titles = [node for node in visible if node["text"] == title]
        dates = [node for node in visible if node["text"] == date]
        paragraphs = [
            node for node in visible
            if node["text"].startswith(
                "The Oklahoma House of Representatives completed bill filing"
            )
            and phrase in node["text"]
        ]
        require(len(titles) == len(dates) == len(paragraphs) == 1,
                "visible own publication title/year/session evidence")
        paragraph = paragraphs[0]
        start = raw.index(phrase, paragraph["raw_source_start"], paragraph["raw_source_end"])
        witnesses[year] = {
            "original_session_identifier": year, "legislature_number": 59,
            "publisher": "Oklahoma House of Representatives", "capture": capture,
            "literal_visible_title_node": titles[0],
            "literal_visible_publication_date_node": dates[0],
            "literal_visible_own_session_paragraph": paragraph,
            "literal_raw_own_session_span": {
                "start": start, "end": start + len(phrase), "text": raw[start:start + len(phrase)],
            },
            "publication_date_is_not_a_bill_filing_or_introduction_date": True,
        }
    require(set(witnesses) == {"2023", "2024"}
            and _equal(witnesses, reviewed["original_annual_session_witnesses"]),
            "both primary annual contexts independently rederived")
    require(reviewed["schema"] == "state-politics.reviewed-ok-session-context.v1"
            and reviewed["relation"] == RELATION and reviewed["state"] == "OK"
            and reviewed["legislature_number"] == 59
            and reviewed["allowed_source_annual_session"] == "2023"
            and reviewed["allowed_target_annual_session"] == "2024"
            and set(reviewed["allowed_original_document_types"]) == ALLOWED
            and reviewed["canonical_session_alias_or_bill_merge"] is False
            and reviewed["canonical_population_or_filing_date_admission"] is False
            and reviewed[
                "particular_bill_introduced_reintroduced_or_carried_over_in_target_year_inferred"
            ] is False, "reviewed same-legislature context limits")
    return {"relation": RELATION, "reviewed_context_sha256": REVIEW_SHA256,
            "house_manifest_sha256": HOUSE_SHA256, "witnesses": witnesses,
            "bill_specific_status_or_dates_inferred": False}


def _printed(text, identifier):
    head = text[:2000]
    matches = list(re.finditer(
        r"\b(HOUSE|SENATE)\s+(JOINT\s+RESOLUTION|CONCURRENT\s+RESOLUTION|RESOLUTION|BILL)"
        r"\s+(?:NO\.?\s*)?([0-9]+)\b", head,
    ))
    own = matches[0] if matches else None
    typed = (
        TYPES[own[1], " ".join(own[2].split())] + " " + own[3] if own else None
    )
    state = re.search(r"\bSTATE OF OKLAHOMA\b", head)
    session = re.search(
        r"\b1st\s+Session\s+of\s+the\s+59th\s+Legislature\s*\(2023\)", head,
    )
    evidence = [
        {"kind": kind, "start": match.start(), "end": match.end(), "text": match[0]}
        for kind, match in [("own_typed_primary_bill", own), ("own_state", state),
                            ("own_first_59th_2023_session", session)] if match
    ]
    return {
        "exact_own_typed_identifier": typed == identifier,
        "printed_primary_identifier": typed, "state_present": state is not None,
        "first_59th_2023_present": session is not None, "printed_evidence": evidence,
        "literal_as_introduced": bool(re.search(r"\bAS\s+INTRODUCED\b", head)),
        "policy_section_start": 0,
    }


def _unique(rows, key):
    result = {}
    for row in rows:
        require(row[key] not in result, f"duplicate original {key}")
        result[row[key]] = row
    return result


def _data(source, gap, house):
    require(gap.num_rows == 21562, "complete unchanged 21562-row queue required")
    queue = _unique(gap.to_pylist(), "bill_id")
    metadata = _unique(pq.read_table(
        source / "ok_target_source_bill_metadata.original.parquet",
    ).to_pylist(), "bill_id")
    versions = _unique(pq.read_table(
        source / "ok_version_alternatives.original.parquet",
    ).to_pylist(), "id")
    links = _unique(pq.read_table(
        source / "ok_version_link_alternatives.original.parquet",
    ).to_pylist(), "id")
    searchable = _unique(pq.read_table(
        source / "ok_target_source_searchablebill.original.parquet",
    ).to_pylist(), "bill_id")
    contexts = _unique(pq.read_table(
        source / "ok_target_source_snapshot_contexts.original.parquet",
    ).to_pylist(), "bill_id")
    sessions = {}
    require((source / "legislative_session_original_rows.jsonl").read_bytes()
            == (house / "legislative_session_original_rows.jsonl").read_bytes(),
            "identical two complete original legislative-session rows")
    for _, row, _ in _rows(source / "legislative_session_original_rows.jsonl"):
        original = row["original_record"]
        require(original["identifier"] not in sessions, "duplicate original annual session")
        sessions[original["identifier"]] = original
    require(set(sessions) == {"2023", "2024"}, "both original annual session rows required")
    for year, row in sessions.items():
        require(row["name"] == f"{year} Regular Session"
                and row["jurisdiction_id"] == "ocd-jurisdiction/country:us/state:ok/government",
                "original regular Oklahoma annual session")
    alternatives = {key: defaultdict(list) for key in ("versions", "links", "references")}
    for row in versions.values():
        alternatives["versions"][row["bill_id"]].append(row)
    by_url = defaultdict(list)
    for row in links.values():
        alternatives["links"][row["bill_id"]].append(row)
        if row["bill_id"] in queue:
            by_url[row["url"]].append(row)
    for row in pq.read_table(
        source / "ok_source_reference_alternatives.original.parquet",
    ).to_pylist():
        alternatives["references"][row["bill_id"]].append(row)
    return {
        "queue": queue, "metadata": metadata, "versions": versions, "links": links,
        "searchable": searchable, "snapshot_contexts": contexts,
        "sessions": sessions, "alternatives": alternatives, "target_links_by_url": by_url,
    }


def _regular_context(metadata, year, sessions):
    row = sessions[year]
    return metadata["state"] == "OK" and all(
        metadata[field] == row[original] for field, original in [
            ("legislative_session_id", "id"), ("session_identifier", "identifier"),
            ("session_name", "name"), ("session_start_date", "start_date"),
            ("session_end_date", "end_date"),
        ]
    )


def _prologue(source):
    flag = source.get("archive_generated_prologue_preserved", False)
    if type(flag) is not bool:
        return None
    text = source["source_record"]["raw_text"]
    if flag:
        start = source.get("source_identity", {}).get("policy_section_start")
        if type(start) is int and 0 < start < len(text) and "Section 1:" in text[:start]:
            return flag, start
        return None
    if text.startswith("Title:") and (
        "\nRaw Text:\n" in text[:2000] or "Section 1:" in text[:2000]
    ):
        return None
    return False, 0


def _source_guard(source, original, data):
    """Require original exporter facts and independently follow the retained text FK."""
    reasons = []
    body = original.get("raw_text")
    context = source.get("source_context")
    context = context if isinstance(context, dict) else {}
    snapshot = source.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    provider_flags = snapshot.get("provider_flags")
    source_id = source["bill_id"]
    if type(body) is not str or not body.strip():
        reasons.append("original_searchablebill_body_missing_or_empty")
    if original.get("is_error") != "f":
        reasons.append(
            "original_searchablebill_provider_error"
            if original.get("is_error") == "t"
            else "original_searchablebill_error_flag_missing_or_unrecognized"
        )
    if not (
        context.get("has_raw_text") is True
        and snapshot.get("has_nonempty_raw_text") is True
        and context.get("source_noerror") is True
        and context.get("nonempty_bound_noerror") is True
        and context.get("source_is_error") == "f"
        and isinstance(provider_flags, dict) and provider_flags.get("is_error") == "f"
    ):
        reasons.append("original_snapshot_nonempty_noerror_facts_missing_or_inconsistent")
    foreign_key = original.get("version_link_id")
    link = data["links"].get(foreign_key)
    version = data["versions"].get(link.get("version_id")) if link else None
    selected = source.get("source_version")
    selected = selected if isinstance(selected, dict) else {}
    if not foreign_key or link is None or version is None:
        reasons.append("original_searchablebill_version_fk_missing_or_unresolved")
    elif not (
        original.get("bill_id") == source_id
        and context.get("searchablebill_id") == original.get("id")
        and context.get("bill_id") == source_id
        and link.get("bill_id") == version.get("bill_id") == source_id
        and context.get("version_link_id") == foreign_key == link.get("id")
        and context.get("version_id") == version.get("id")
        and context.get("linked_bill_id") == context.get("version_bill_id") == source_id
        and isinstance(selected.get("link"), dict)
        and isinstance(selected.get("version"), dict)
        and selected["link"].get("id") == link["id"]
        and selected["version"].get("id") == version["id"]
        and selected["link"].get("version_id") == version["id"]
        and snapshot.get("source_url") == context.get("source_url") == link.get("url")
    ):
        reasons.append("original_searchablebill_text_version_fk_conflict")
    if not (
        context.get("exact_version_foreign_keys") is True
        and context.get("source_reference_status") == "exact_version_foreign_keys"
        and snapshot.get("version_binding_status") == "exact_version_foreign_keys"
    ):
        reasons.append("original_snapshot_version_fk_missing_or_ambiguous")
    return reasons


def _derive_source(source, ordinal, record_sha, data, house_proof):
    """Derive relations from raw original records, not prior eligibility booleans."""
    source_id = source["bill_id"]
    original = data["searchable"][source_id]
    require(_equal(source["source_record"], {
        key: value for key, value in original.items() if key != "source_row_ordinal"
    }) and source["source_row_ordinal"] == original["source_row_ordinal"],
            "full original searchable-bill/source record equality")
    require(_equal(source["source_context"], data["snapshot_contexts"][source_id]),
            "full original snapshot context equality")
    body = source["source_record"].get("raw_text")
    guard_reasons = _source_guard(source, original, data)
    if guard_reasons:
        return [], {
            "source_ordinal": ordinal, "source_bill_id": source_id,
            "source_view_id": source["view_id"], "source_record_sha256": record_sha,
            "body_sha256": _sha((body if type(body) is str else "").encode()),
            "original_source_session": source["session_identifier"],
            "exact_original_url": (
                source["source_context"].get("source_url")
                if isinstance(source.get("source_context"), dict) else None
            ),
            "printed_identity": _printed(
                body if type(body) is str else "", source["identifier"],
            ),
            "original_searchablebill_error_flag_present": "is_error" in original,
            "original_searchablebill_error_flag": original.get("is_error"),
            "original_searchablebill_version_link_id": original.get("version_link_id"),
            "original_snapshot_nonempty_noerror_and_fk_facts": source["source_context"],
            "target_bill_ids": [], "disposition": "quarantine",
            "negative_conditions": guard_reasons, "emitted_views": 0,
            **dict.fromkeys(FLAGS, False),
        }
    require(type(body) is str, "complete original raw_text string required")
    require(_sha(body.encode()) == source["source_context"]["raw_text_sha256"],
            "complete source body hash")
    link, version = source["source_version"]["link"], source["source_version"]["version"]
    require(link["id"] in data["links"] and version["id"] in data["versions"],
            "source original version/link retained")
    require(all(_equal(value, link[key]) for key, value in data["links"][link["id"]].items())
            and all(_equal(value, version[key]) for key, value in
                    data["versions"][version["id"]].items()), "original selected version fields")
    require(link["bill_id"] == version["bill_id"] == source_id
            and link["version_id"] == version["id"]
            and original["version_link_id"] == link["id"]
            and source["snapshot"]["source_url"] == source["source_context"]["source_url"]
            == link["url"], "exact source version/link/URL foreign keys")
    source_metadata = data["metadata"][source_id]
    target_links = data["target_links_by_url"].get(link["url"], [])
    reasons, views = [], []
    if len(target_links) != 1:
        reasons.append("missing_or_ambiguous_exact_existing_target_version_pointer")
    prologue = _prologue(source)
    if prologue is None:
        reasons.append("unbound_or_conflicting_machine_prologue_metadata")
        printed = _printed(body, source["identifier"])
    else:
        _, offset = prologue
        printed = _printed(body[offset:], source["identifier"])
        printed["policy_section_start"] = offset
        for span in printed["printed_evidence"]:
            span["start"] += offset
            span["end"] += offset
    kind = source["identifier"].split(" ")[0]
    if kind not in ALLOWED:
        reasons.append("excluded_simple_concurrent_or_unsupported_document_type")
    if not printed["exact_own_typed_identifier"]:
        reasons.append("missing_or_wrong_exact_primary_typed_own_bill")
    if not printed["state_present"]:
        reasons.append("missing_literal_own_state")
    if not printed["first_59th_2023_present"]:
        reasons.append("missing_or_wrong_literal_first_59th_2023")
    if not _regular_context(source_metadata, "2023", data["sessions"]):
        reasons.append("unsupported_reverse_special_or_source_annual_context")
    if not (source["state"] == "OK" and source["session_identifier"] == "2023"
            and source["identifier"] == source_metadata["identifier"]
            and source["source_context"]["exact_version_foreign_keys"] is True
            and source["source_context"]["source_noerror"] is True
            and original["is_error"] == "f"):
        reasons.append("source_identity_or_provider_error_context")
    if len(target_links) == 1:
        target_link = target_links[0]
        target_version = data["versions"][target_link["version_id"]]
        target = data["queue"][target_link["bill_id"]]
        target_metadata = data["metadata"][target["bill_id"]]
        if not (
            _regular_context(target_metadata, "2024", data["sessions"])
            and target["bill_id"] != source_id and target["state"] == "OK"
            and target["session_identifier"] == "2024"
            and target["identifier"] == source["identifier"]
            and target_link["bill_id"] == target_version["bill_id"] == target["bill_id"]
            and target_link["url"] == link["url"]
        ):
            reasons.append("unsupported_target_or_exact_pointer_identity")
        for field in (
            "identifier", "state", "session_identifier", "legislative_session_id",
            "session_name", "session_start_date", "session_end_date", "first_action_date",
        ):
            if not _equal(target[field], target_metadata[field]):
                reasons.append("original_target_metadata_conflict")
                break
        if not reasons:
            source_alts = {
                key: value[source_id] for key, value in data["alternatives"].items()
            }
            target_alts = {
                key: value[target["bill_id"]] for key, value in data["alternatives"].items()
            }
            relation = {
                "kind": RELATION_KIND, "legislature_number": 59,
                "source_state": source["state"], "target_state": target["state"],
                "source_bill_id": source_id, "target_bill_id": target["bill_id"],
                "source_session_identifier": "2023", "target_session_identifier": "2024",
                "source_legislative_session_id": source_metadata["legislative_session_id"],
                "target_legislative_session_id": target_metadata["legislative_session_id"],
                "exact_original_document_url": link["url"],
                "source_version_id": version["id"], "source_link_id": link["id"],
                "target_version_id": target_version["id"], "target_link_id": target_link["id"],
                "source_authority": "third_party_OpenStates_snapshot_extraction",
                "house_context_authority_does_not_upgrade_body_authority": True,
                "proves_target_year_filing_or_version": False,
                "proves_bill_specific_carryover_or_pending": False,
                "session_alias_or_bill_merge": False,
                "particular_bill_carried_over_pending_or_reintroduced_inferred": False,
                "filing_introduction_or_party_date_inferred": False,
                "house_proof_binding": {
                    key: house_proof[key] for key in (
                        "reviewed_context_sha256", "house_manifest_sha256",
                    )
                },
                "primary_session_context_witnesses": house_proof["witnesses"],
            }
            views.append({
                "source_type": "archive_text",
                "view_id": f"ok-retained-context:{original['id']}:{target_link['id']}",
                "bill_id": target["bill_id"], "state": target["state"],
                "identifier": target["identifier"],
                "session_identifier": target["session_identifier"], "title": target["title"],
                "text": body, "raw_text_sha256": _sha(body.encode()),
                "raw_text_characters": len(body), "source_status": STATUS,
                "context_relation": relation, "target_context": target,
                "original_source_context": source["source_context"],
                "original_target_context": target,
                "original_source_metadata": source_metadata,
                "original_target_metadata": target_metadata,
                "source_searchablebill_record": original,
                "source_record": source,
                "source_identity": {
                    "state": source["state"], "identifier": source["identifier"],
                    "session_identifier": source["session_identifier"], **printed,
                },
                "source_version": {
                    "version": version, "link": link,
                    "target_version": target_version, "target_link": target_link,
                    "all_original_source_alternatives": source_alts,
                    "all_original_target_alternatives": target_alts,
                },
                "source_members": {
                    "original_snapshot_record_file":
                        "source-conditional/ok_witness_source_records.original.jsonl",
                    "original_record_ordinal": ordinal,
                    "original_record_sha256": record_sha,
                    "source_manifest_sha256": CONDITIONAL_SHA256,
                    "original_annual_sessions": data["sessions"],
                },
                "archive_generated_prologue_preserved": prologue[0],
                "source_availability": (
                    "research_evidence_observation_not_unique_legislation_admission"
                ),
                "introduced_stage_diagnostic_not_filing_certification": (
                    version["note"] == target_version["note"] == "Introduced"
                    and printed["literal_as_introduced"]
                ),
                **dict.fromkeys(FLAGS, False),
            })
    return views, {
        "source_ordinal": ordinal, "source_bill_id": source_id,
        "source_view_id": source["view_id"], "source_record_sha256": record_sha,
        "body_sha256": _sha(body.encode()), "original_source_session": source["session_identifier"],
        "exact_original_url": link["url"], "printed_identity": printed,
        "target_bill_ids": sorted({row["bill_id"] for row in target_links}),
        "disposition": "exact_document_same_legislature_research_observation"
        if views else "quarantine",
        "negative_conditions": reasons, "emitted_views": len(views),
        **dict.fromkeys(FLAGS, False),
    }


def _replay(source, house, gap):
    proof = _house_witnesses(house)
    data = _data(source, gap, house)
    views, dispositions = [], []
    for ordinal, record, record_sha in _rows(source / "ok_witness_source_records.original.jsonl"):
        emitted, disposition = _derive_source(record, ordinal, record_sha, data, proof)
        views.extend(emitted)
        dispositions.append(disposition)
    require(len(dispositions) == 2135, "all original 2135 witnesses and negatives required")
    require(len({row["view_id"] for row in views}) == len(views), "globally unique view namespace")
    coverage = Counter(row["bill_id"] for row in views)
    queue_rows = gap.to_pylist()
    contexts = gap.filter(pa.array([row["bill_id"] in coverage for row in queue_rows]))
    candidates = gap.append_column(
        "ok_context_view_count", pa.array([coverage[row["bill_id"]] for row in queue_rows]),
    ).append_column("ok_context_disposition", pa.array([
        "same_legislature_exact_document_research_observation" if row["bill_id"] in coverage
        else "no_eligible_ok_exact_document_relation" for row in queue_rows
    ]))
    report = {
        "schema": SCHEMA, "source_status": STATUS, "context_relation": RELATION,
        "counts": {
            "text_views": len(views), "newly_observed_contexts": contexts.num_rows,
            "full_original_queue": gap.num_rows, "source_witnesses": len(dispositions),
            "rejected_source_witnesses": sum(not row["emitted_views"] for row in dispositions),
            "body_characters": sum(len(row["text"]) for row in views),
            "by_document_type": dict(Counter(row["identifier"].split()[0] for row in views)),
            "introduced_stage_diagnostics_not_filing_certified": sum(
                row["introduced_stage_diagnostic_not_filing_certification"] for row in views
            ),
            "negative_reasons": dict(Counter(
                reason for row in dispositions for reason in row["negative_conditions"]
            )),
            "full_original_text_hash_equal_views": sum(
                row["raw_text_sha256"] == row["source_record"]["source_context"]["raw_text_sha256"]
                for row in views
            ),
            "no_machine_prologue_views": sum(
                row["archive_generated_prologue_preserved"] is False for row in views
            ),
        },
        "approvals": dict.fromkeys(FLAGS, False),
        "source_availability_is_research_observation_only": True,
        "original_searchablebill_nonempty_noerror_exact_version_fk_required": True,
        "no_native_body_or_procedural_PDF_requests": True, "new_network_requests": 0,
        "model_or_tokenizer_operations": 0,
        "bill_specific_carryover_status_or_filing_dates_inferred": False,
        "Senate_challenge_and_all_other_publisher_stops_remain_binding": True,
    }
    return views, contexts, candidates, dispositions, report, proof


def _expected_files(conditional, house):
    return GENERATED | {
        *(f"source-conditional/{name}" for name in conditional),
        *(f"reviewed-context/{name}" for name in house),
    }


def build_ok_retained_context(source_conditional_packet, reviewed_context_packet,
                              gap_queue, out_directory):
    """Build a new immutable packet without changing any input or canonical identity."""
    source, house = _root(source_conditional_packet), _root(reviewed_context_packet)
    queue = _regular(Path(gap_queue).absolute())
    out = Path(out_directory).absolute()
    require(not out.exists() and not out.is_symlink() and out.resolve() == out,
            "new unlinked output required")
    require(not source.is_relative_to(house) and not house.is_relative_to(source),
            "overlapping source packets")
    require(not any(out.is_relative_to(path) or path.is_relative_to(out)
                    for path in (source, house, queue)), "overlapping input/output")
    inventories = {
        "source-conditional": _inventory(source, CONDITIONAL_SHA256),
        "reviewed-context": _inventory(house, HOUSE_SHA256, house=True),
    }
    require(_binding(queue)["sha256"] == QUEUE_SHA256, "full original queue trust anchor")
    producer = _regular(Path(__file__).absolute())
    paths = [queue, producer, *(source / name for name in inventories["source-conditional"]),
             *(house / name for name in inventories["reviewed-context"])]
    before = {
        str(path): {**_binding(path), "mtime_ns": path.stat().st_mtime_ns,
                    "inode": path.stat().st_ino} for path in paths
    }
    out.mkdir(parents=True)
    for label, root in (("source-conditional", source), ("reviewed-context", house)):
        for name in inventories[label]:
            target = out / label / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, target)
    shutil.copy2(queue, out / "input_gap_queue.parquet")
    gap = pq.read_table(out / "input_gap_queue.parquet")
    views, contexts, candidates, dispositions, report, proof = _replay(
        out / "source-conditional", out / "reviewed-context", gap,
    )
    _write_rows(out / "views.jsonl", views)
    pq.write_table(contexts, out / "context_inventory.parquet", compression="zstd")
    pq.write_table(candidates, out / "candidate_dispositions.parquet", compression="zstd")
    _write_rows(out / "source_dispositions.jsonl", dispositions)
    _write(out / "report.json", report)
    _write(out / "reviewed_house_replay.json", proof)
    after = {
        str(path): {**_binding(path), "mtime_ns": path.stat().st_mtime_ns,
                    "inode": path.stat().st_ino} for path in paths
    }
    require(_equal(before, after), "consumed originals changed")
    _write(out / "source_immutability.json", {
        "before": before, "after": after, "all_original_hashes_bytes_stats_unchanged": True,
    })
    (out / "producer").mkdir()
    shutil.copy2(producer, out / "producer/ok_retained_context_text.py")
    names = _expected_files(inventories["source-conditional"], inventories["reviewed-context"])
    manifest = {
        "schema": SCHEMA, "source_status": STATUS, "context_relation": RELATION,
        "source_conditional_manifest_sha256": CONDITIONAL_SHA256,
        "reviewed_context_manifest_sha256": HOUSE_SHA256,
        "full_original_queue_sha256": QUEUE_SHA256,
        "producer_dependencies": ["producer/ok_retained_context_text.py"],
        "runtime_dependencies": ["Python standard library", "pyarrow"],
        "approvals": dict.fromkeys(FLAGS, False), "counts": report["counts"],
        "packet_artifacts": {name: _binding(out / name) for name in sorted(names)},
    }
    _write(out / "manifest.json", manifest)
    load_ok_retained_context(out)
    return manifest


def _current_metadata(contexts, metadata):
    rows = metadata.to_pylist() if isinstance(metadata, pa.Table) else list(metadata)
    current = _unique(rows, "bill_id")
    for row in contexts:
        require(row["bill_id"] in current, "current target metadata missing")
        other = current[row["bill_id"]]
        require(all(field in other for field in (
            "state", "identifier", "session_identifier", "legislative_session_id",
        )) and all(_equal(value, other[key]) for key, value in row.items() if key in other),
                "current target metadata identity/date/null rewrite")


def load_ok_retained_context(directory, metadata=None):
    """Replay raw House HTML and all original relations; return views, contexts, pins, manifest."""
    root = _root(directory)
    manifest = _json(root / "manifest.json")
    require(set(manifest) == {
        "schema", "source_status", "context_relation", "source_conditional_manifest_sha256",
        "reviewed_context_manifest_sha256", "full_original_queue_sha256",
        "producer_dependencies", "runtime_dependencies", "approvals", "counts", "packet_artifacts",
    }, "unexpected or incomplete manifest fields")
    require(manifest.get("schema") == SCHEMA and manifest.get("source_status") == STATUS
            and manifest.get("context_relation") == RELATION
            and manifest.get("source_conditional_manifest_sha256") == CONDITIONAL_SHA256
            and manifest.get("reviewed_context_manifest_sha256") == HOUSE_SHA256
            and manifest.get("full_original_queue_sha256") == QUEUE_SHA256
            and _equal(manifest.get("approvals"), dict.fromkeys(FLAGS, False)),
            "schema/trust anchor/approval mismatch")
    require(manifest.get("producer_dependencies") == ["producer/ok_retained_context_text.py"]
            and manifest.get("runtime_dependencies") == ["Python standard library", "pyarrow"],
            "producer dependency inventory")
    conditional = _inventory(root / "source-conditional", CONDITIONAL_SHA256)
    house = _inventory(root / "reviewed-context", HOUSE_SHA256, house=True)
    names = _expected_files(conditional, house)
    require(set(manifest["packet_artifacts"]) == names
            and _walk(root) == names | {"manifest.json"}, "complete artifact inventory mismatch")
    pins = {"manifest.json": _binding(root / "manifest.json")["sha256"]}
    for name, binding in manifest["packet_artifacts"].items():
        _relative(name)
        require(_binding(root / name) == binding, f"packet artifact binding mismatch: {name}")
        pins[name] = binding["sha256"]
    require(_binding(root / "producer/ok_retained_context_text.py")
            == _binding(_regular(Path(__file__).absolute())), "producer mismatch")
    require(_binding(root / "input_gap_queue.parquet")["sha256"] == QUEUE_SHA256,
            "original full queue changed")
    gap = pq.read_table(root / "input_gap_queue.parquet")
    views, contexts, candidates, dispositions, report, proof = _replay(
        root / "source-conditional", root / "reviewed-context", gap,
    )
    require(_equal([row for _, row, _ in _rows(root / "views.jsonl")], views),
            "full view/text/source-session/identity/approval replay mismatch")
    require(pq.read_table(root / "context_inventory.parquet").equals(contexts, check_metadata=True)
            and pq.read_table(root / "candidate_dispositions.parquet").equals(
                candidates, check_metadata=True),
            "full original queue/context/null replay mismatch")
    require(_equal([row for _, row, _ in _rows(root / "source_dispositions.jsonl")], dispositions)
            and _equal(_json(root / "report.json"), report)
            and _equal(_json(root / "reviewed_house_replay.json"), proof)
            and _equal(manifest["counts"], report["counts"]),
            "report/dispositions/primary proof replay mismatch")
    immutability = _json(root / "source_immutability.json")
    require(immutability["all_original_hashes_bytes_stats_unchanged"] is True
            and _equal(immutability["before"], immutability["after"]),
            "original source immutability receipt")
    expected_bindings = Counter(
        (binding["sha256"], binding["bytes"]) for binding in [
            *conditional.values(), *house.values(), _binding(root / "input_gap_queue.parquet"),
            _binding(root / "producer/ok_retained_context_text.py"),
        ]
    )
    require(Counter((row["sha256"], row["bytes"]) for row in
                    immutability["before"].values()) == expected_bindings,
            "complete consumed source immutability inventory")
    context_rows = contexts.to_pylist()
    if metadata is not None:
        _current_metadata(context_rows, metadata)
    return views, context_rows, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--source-conditional-packet", type=Path, required=True)
    build.add_argument("--reviewed-context-packet", type=Path, required=True)
    build.add_argument("--gap-queue", type=Path, required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--directory", type=Path, required=True)
    verify.add_argument("--metadata", type=Path)
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_ok_retained_context(
            args.source_conditional_packet, args.reviewed_context_packet,
            args.gap_queue, args.out_dir,
        )
    else:
        _, _, _, manifest = load_ok_retained_context(
            args.directory, pq.read_table(args.metadata) if args.metadata else None,
        )
    print(json.dumps({"schema": SCHEMA, "counts": manifest["counts"],
                      "all_approvals": manifest["approvals"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

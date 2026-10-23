"""Replay independently published bill HTML without certifying its native original."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import stat
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

SCHEMA = "state-politics.billcam-retained-html.v1"
SOURCE_SCHEMA = "state-politics.billcam-public-source.v1"
STATUS = "independent_provider_published_HTML_not_native_original_or_filing_certified"
PROVIDER = "BillCam"
FLAGS = (
    "scientific_approval", "model_input_approved", "training_approved",
    "training_admission", "publication_approved", "party_attribution_approved",
    "filing_time_text_certified", "analytical_admission", "publisher_original_verified",
    "native_original_verified", "native_identity_certified", "source_rights_approved",
    "rights_approved", "canonical_population_admission", "source_date_or_party_inferred",
    "bill_specific_carryover_status_inferred", "native_URL_alias_inferred",
)
TOOLS = {"python": platform.python_version(), "pyarrow": pa.__version__}
PRODUCTS = {
    "views.jsonl", "source_dispositions.jsonl", "candidate_dispositions.jsonl",
    "context_inventory.parquet", "input_gap_queue.parquet", "report.json",
    "source_inventory.json", "source_immutability.json", "producer/billcam_text.py",
}
TYPES = {"HB", "SB", "HR", "SR", "HCR", "SCR", "HJR", "SJR"}


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible BillCam archive: {message}")


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"incompatible BillCam archive: nonfinite JSON {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


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
        raise ValueError(f"incompatible BillCam archive: missing artifact: {path}") from exc
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


class _Page(HTMLParser):
    BLOCKS = {"p", "div", "tr", "td", "th", "li", "br", "h1", "h2", "h3", "hr"}

    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.source = raw.decode("utf-8")
        self.starts = [0] + [m.end() for m in re.finditer("\n", self.source)]
        self.bills, self.canonical, self.links, self.spans, self.parts = (
            [] for _ in range(5)
        )
        self.container_depth = self.ignored = 0
        self.container_start = None
        self.feed(self.source)
        self.close()
        require(self.container_depth == 0 and self.ignored == 0, "unclosed source container")

    def _position(self):
        line, column = self.getpos()
        return self.starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        require(len(values) == len(attrs), "duplicate source HTML attributes")
        if tag == "bill-vote-panel":
            require(":bill" in values, "missing published bill object")
            self.bills.append(_decode(values[":bill"]))
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag == "link" and values.get("rel") == "canonical":
            self.canonical.append(values["href"])
        if tag == "div" and "container" in values.get("class", "").split():
            require(not self.container_depth, "nested source container")
            self.container_depth = 1
            self.container_start = self._position() + len(self.get_starttag_text())
        elif self.container_depth and tag == "div":
            self.container_depth += 1
        if self.container_depth:
            if tag in ("script", "style"):
                self.ignored += 1
            if not self.ignored and tag in self.BLOCKS:
                self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.container_depth:
            if tag in ("script", "style"):
                self.ignored -= 1
            require(self.ignored >= 0, "unpaired ignored source element")
            if not self.ignored and tag in self.BLOCKS:
                self.parts.append("\n")
            if tag == "div":
                self.container_depth -= 1
                if not self.container_depth:
                    self.spans.append([self.container_start, self._position()])

    def handle_data(self, data):
        if self.container_depth and not self.ignored:
            self.parts.append(data)


def _url(value):
    require(type(value) is str, "untyped source URL")
    parts = urlsplit(value)
    require(parts.scheme == "https" and parts.hostname == "billcam.com"
            and not parts.username and parts.port is None and not parts.fragment,
            "source request is not the independent public provider")
    return value


def _body(raw, url):
    page = _Page(raw)
    require(page.canonical == [url] and not page.bills and len(page.spans) == 1,
            "not one canonical published bill-text container")
    text = "".join(page.parts).strip()
    require(bool(text), "empty published source container")
    start, end = page.spans[0]
    return text, {
        "container_source_character_span": [start, end],
        "complete_container_html_sha256": hashlib.sha256(
            page.source[start:end].encode()
        ).hexdigest(),
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "text_characters": len(text),
        "reader": "stdlib_HTMLParser_all_container_character_data_with_block_boundaries",
        "complete_provider_published_body_not_native_completeness_certification": True,
    }


def _targets(bill, originals):
    session = bill["legislative_session"]
    if session["state"]["abbr"] != "HI":
        return [], "outside_initial_HI_reader_profile"
    match = re.fullmatch(r"(2023|2024) Regular Session", session["name"])
    if not match:
        return [], "outside_existing_HI_target_session_years"
    require(bill["display_legislative_session"] == f"Hawaii {session['name']}",
            "provider session display/object disagreement")
    require(bill["bill_type"] in TYPES and type(bill["bill_number"]) is int
            and bill["bill_number"] > 0, "unsupported or untyped provider identifier")
    identifier, year = f"{bill['bill_type']} {bill['bill_number']}", match[1]
    candidates = [
        row for row in originals if row["state"] == "HI"
        and row["identifier"] == identifier
        and row["session_identifier"] in (year, f"{year} Regular Session")
    ]
    if not candidates:
        return [], "no_original_missing_context_for_declared_state_year_identifier"
    matches = [
        row for row in candidates
        if " ".join(row["title"].casefold().split())
        == " ".join(bill["title"].casefold().split())
    ]
    if not matches:
        return [], "original_and_provider_titles_conflict_not_fuzzy_joined"
    require(len(matches) == 1, "ambiguous original missing context")
    return matches, "matched_original_candidate_pending_printed_header"


def printed_identity(text, context):
    head = text[:2000]
    own = re.search(r"\b([HS])\.\s*(?:([CJ])\.\s*)?([BR])\.\s*NO\.\s*(\d+)\b",
                    head, re.I)
    venue = re.search(r"THIRTY-SECOND LEGISLATURE,\s*(2023|2024)\b", head)
    state = re.search(r"\bSTATE\s+OF\s+HAWAII\b", head)
    if not own or not venue or not state:
        return None
    identifier = "".join(x or "" for x in own.groups()[:3]).upper() + f" {int(own[4])}"
    year = venue[1]
    if (context["state"] != "HI" or context["identifier"] != identifier
            or context["session_identifier"] not in (year, f"{year} Regular Session")):
        return None
    compact = " ".join(text.split())
    if identifier.split()[0] in ("HB", "SB"):
        if ("A BILL FOR AN ACT" not in compact
                or "BE IT ENACTED BY THE LEGISLATURE OF THE STATE OF HAWAII:" not in compact):
            return None
    elif "BE IT RESOLVED" not in compact:
        return None
    return {
        "state": "HI", "identifier": identifier, "printed_year": year,
        "printed_legislature": "THIRTY-SECOND",
        "session_identifier": context["session_identifier"],
        "source_relation": "independent_provider_context_and_printed_own_state_year_typed_number",
        "original_native_URL_equality_or_alias_not_asserted": True,
        "printed_evidence": [
            {"start": m.start(), "end": m.end(), "text": m[0]}
            for m in (own, venue, state)
        ],
    }


def _source(source, expected_sha):
    manifest_path = source / "manifest.json"
    require(_binding(manifest_path)["sha256"] == _hash(expected_sha),
            "caller-pinned source manifest changed")
    manifest = _json(manifest_path)
    require(manifest["schema"] == SOURCE_SCHEMA and manifest["network_closed"] is True
            and manifest["source_admission"] is False and manifest["publication"] is False,
            "closed unapproved source packet required")
    artifacts = manifest["artifacts"]
    require(type(artifacts) is dict and _tree(source) == set(artifacts) | {"manifest.json"},
            "source inventory omissions or extra members")
    for name, value in artifacts.items():
        _relative(name)
        require(_equal(_binding(source / name), value), f"source artifact changed: {name}")
    scope, report = _json(source / "scope.json"), _json(source / "report.json")
    require(report["network_closed"] is True and report["source_admissions"] == 0
            and report["encoder_calls"] == 0 and report["publication"] is False,
            "source capture made analytical admissions")
    old = list(_rows(source / "inherited-probe/request-ledger.jsonl"))
    new = list(_rows(source / "request-ledger.jsonl"))
    attempts = list(_rows(source / "request-attempts.jsonl"))
    require(len(old) == report["inherited_closed_probe_requests"]
            == scope["inherited_probe_allowance_and_requests_forever_closed"]
            and len(new) == report["new_HTTP_responses_retained"]
            and len(attempts) == report["new_GET_invocations"]
            and len(new) == len(attempts)
            and len(new) <= scope["additional_identified_frontier_GET_allowance"]
            and report["known_aggregate_GET_invocations"] == len(old) + len(new),
            "source GET accounting is not independently reconcilable")
    responses = {}
    for inherited, rows in ((True, old), (False, new)):
        for ordinal, original in enumerate(rows, 1):
            require(original["ordinal"] == ordinal, "nonconsecutive source request ledger")
            row = {**original, "inherited": inherited}
            if inherited:
                row["body"] = "inherited-probe/" + original["body"]
            _url(row["url"])
            _relative(row["body"])
            require(row["url"] not in responses, "duplicate physical source URL")
            require(_equal(_binding(source / row["body"]), row["body_binding"]),
                    "source response body binding mismatch")
            responses[row["url"]] = row
    return manifest, report, responses


def _replay(source, queue_path, source_sha, queue_sha):
    source_manifest, source_report, responses = _source(source, source_sha)
    require(_binding(queue_path)["sha256"] == _hash(queue_sha)
            and _equal(_binding(queue_path), source_manifest["input_gap_queue"])
            and _equal(_binding(queue_path), _binding(source / "input_gap_queue.parquet")),
            "original complete gap queue changed")
    queue = pq.read_table(queue_path)
    originals = queue.to_pylist()
    require(len({row["bill_id"] for row in originals}) == len(originals),
            "duplicate original gap context")
    views, dispositions, counts = [], [], {}
    for response in responses.values():
        parts = urlsplit(response["url"])
        if not re.fullmatch(r"/bills/[A-Za-z0-9]+/g/[^/]+/[^/]+", parts.path):
            continue
        if response["http_status"] != 200 or response["curl_returncode"] != 0:
            dispositions.append({
                "source_url": response["url"], "disposition": "detail_unavailable",
            })
            continue
        page = _Page((source / response["body"]).read_bytes())
        require(page.canonical == [response["url"]] and len(page.bills) == 1,
                "detail page is not one canonical provider bill")
        bill = page.bills[0]
        require(bill["path"] == response["url"], "provider bill path mismatch")
        targets, reason = _targets(bill, originals)
        hashes = set()
        for version in bill["texts"]:
            require(version["bill_id"] == bill["id"] and version["text_hash"] not in hashes,
                    "provider text foreign key or duplicate source version")
            hashes.add(version["text_hash"])
            links = {
                link for link in page.links
                if urlsplit(link).path == f"/bill-texts/{version['text_hash']}"
                and _url(link) == link and not urlsplit(link).query
            }
            require(len(links) == 1, "no unique actually published source body link")
            url = next(iter(links))
            body_response = responses.get(url)
            disposition = {
                "provider_bill_id": bill["id"], "provider_bill_hash": bill["bill_hash"],
                "provider_text": version, "detail_source_url": response["url"],
                "body_source_url": url, "original_target_contexts": targets,
                "disposition": reason, "body_response": body_response,
            }
            if targets and body_response is None:
                disposition["disposition"] = "full_source_body_not_captured_metadata_preserved"
            elif targets and (body_response["http_status"] != 200
                              or body_response["curl_returncode"] != 0):
                disposition["disposition"] = "captured_body_unavailable_not_a_fill"
            elif targets:
                try:
                    text, extraction = _body((source / body_response["body"]).read_bytes(), url)
                except (ValueError, UnicodeDecodeError) as exc:
                    disposition.update(
                        disposition="unsupported_full_source_container_not_a_fill", error=str(exc),
                    )
                else:
                    context = targets[0]
                    identity = printed_identity(text, context)
                    if identity is None:
                        disposition["disposition"] = (
                            "printed_own_identity_or_year_conflict_not_a_fill"
                        )
                    elif version["mime"] != "text/html":
                        disposition["disposition"] = "unsupported_provider_media_not_a_fill"
                    else:
                        view_id = (
                            f"billcam:{bill['bill_hash']}:{version['text_hash']}:"
                            f"{context['bill_id']}"
                        )
                        require(view_id not in {view["view_id"] for view in views},
                                "duplicate accepted source view")
                        views.append({
                            "view_id": view_id, "source_type": "archive_text",
                            **{key: context[key] for key in (
                                "bill_id", "state", "identifier", "session_identifier", "title",
                            )},
                            "text": text, "raw_text_characters": len(text),
                            "raw_text_sha256": extraction["text_sha256"],
                            "source_record": bill, "source_identity": identity,
                            "source_version": {
                                "version": version, "link": {"url": url, "media_type": "text/html"},
                            },
                            "source_members": {
                                "metadata": {
                                    "path": "source-evidence/" + response["body"],
                                    **response["body_binding"],
                                },
                                "html": {
                                    "path": "source-evidence/" + body_response["body"],
                                    **body_response["body_binding"],
                                },
                                "original_queue": "input_gap_queue.parquet",
                            },
                            "body_extraction": extraction, "archive_provider": PROVIDER,
                            "source_status": STATUS, "archive_generated_prologue_preserved": False,
                            "original_target_context": context,
                            **dict.fromkeys(FLAGS, False),
                        })
                        counts[context["bill_id"]] = counts.get(context["bill_id"], 0) + 1
                        disposition.update(
                            disposition="complete_published_body_original_candidate_identity",
                            view_id=view_id, body_extraction=extraction,
                        )
            dispositions.append(disposition)
    contexts = queue.filter(pc.is_in(
        queue["bill_id"], value_set=pa.array(list(counts), type=pa.string()),
    ))
    candidate_dispositions = [
        {"bill_id": row["bill_id"], "state": row["state"],
         "identifier": row["identifier"], "session_identifier": row["session_identifier"],
         "n_retained_source_views": counts.get(row["bill_id"], 0),
         "disposition": "retained_provider_body" if row["bill_id"] in counts
         else "still_unavailable_from_this_finite_source_scope"}
        for row in originals
    ]
    report = {
        "status": STATUS, "provider": PROVIDER, "source_capture_status": source_report["status"],
        "source_capture_error": source_report["error"], "source_manifest_sha256": source_sha,
        "original_gap_queue_sha256": queue_sha, "all_original_fields_preserved": True,
        "counts": {
            "original_gap_contexts": len(originals), "n_recovered_contexts": len(counts),
            "n_retained_views": len(views), "n_source_version_dispositions": len(dispositions),
            "remaining_unavailable_from_this_source": len(originals) - len(counts),
            "full_retained_text_characters": sum(len(view["text"]) for view in views),
        },
        "no_original_native_URL_requested_or_URL_alias_inferred": True,
        "provider_dates_and_current_sponsors_preserved_not_used_as_time_or_party_evidence": True,
        "provider_tags_summaries_and_community_material_not_added_to_body_input": True,
        "native_completeness_or_originality_not_certified": True,
        "approval_flags": dict.fromkeys(FLAGS, False),
        "encoder_calls": 0, "publication": False,
    }
    return {
        "views.jsonl": views, "source_dispositions.jsonl": dispositions,
        "candidate_dispositions.jsonl": candidate_dispositions,
    }, contexts, report


def build_billcam(source_directory, gap_queue, out_directory, *,
                  source_manifest_sha256, gap_queue_sha256):
    source, queue = _root(source_directory), _regular(Path(gap_queue).absolute())
    out = Path(out_directory).absolute()
    require(not out.exists() and out.resolve() == out and not out.is_symlink()
            and not out.is_relative_to(source) and not source.is_relative_to(out)
            and not queue.is_relative_to(out), "new nonoverlapping output directory required")
    source_sha, queue_sha = _hash(source_manifest_sha256), _hash(gap_queue_sha256)
    manifest, _, _ = _source(source, source_sha)
    source_names = set(manifest["artifacts"]) | {"manifest.json"}
    before = {name: _binding(source / name) for name in sorted(source_names)}
    queue_before, producer = _binding(queue), _binding(Path(__file__).absolute())
    out.mkdir(parents=True)
    for name in sorted(source_names):
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
    after = {name: _binding(source / name) for name in sorted(source_names)}
    require(_tree(source) == source_names and _equal(before, after)
            and _equal(queue_before, _binding(queue))
            and _equal(producer, _binding(Path(__file__).absolute())),
            "source, original queue or producer changed during normalization")
    _write(out / "source_inventory.json", before)
    _write(out / "source_immutability.json", {
        "before": before, "after": after,
        "original_queue_before": queue_before, "original_queue_after": queue_before,
        "all_original_inputs_unchanged": True,
    })
    (out / "producer").mkdir()
    shutil.copyfile(Path(__file__).absolute(), out / "producer/billcam_text.py")
    names = PRODUCTS | {"source-evidence/" + name for name in source_names}
    result = {
        "schema": SCHEMA, "provider": PROVIDER, "status": STATUS, "tools": TOOLS,
        "source_manifest_sha256": source_sha, "gap_queue_sha256": queue_sha,
        "approvals": dict.fromkeys(FLAGS, False), "counts": report["counts"],
        "packet_artifacts": {name: _binding(out / name) for name in sorted(names)},
    }
    _write(out / "manifest.json", result)
    load_billcam(out, source_manifest_sha256=source_sha, gap_queue_sha256=queue_sha)
    return result


def load_billcam(directory, metadata=None, *, source_manifest_sha256=None, gap_queue_sha256=None):
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
    require(_equal(artifacts["producer/billcam_text.py"], _binding(Path(__file__).absolute())),
            "installed/archived producer mismatch")
    source = _root(root / "source-evidence")
    source_manifest, _, _ = _source(source, manifest["source_manifest_sha256"])
    source_names = set(source_manifest["artifacts"]) | {"manifest.json"}
    require(set(artifacts) == PRODUCTS | {"source-evidence/" + name for name in source_names},
            "unexpected normalized/source inventory")
    inventory = {name: _binding(source / name) for name in sorted(source_names)}
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
        for row in context_rows:
            require(row["bill_id"] in metadata, "matched original context no longer exists")
            original = metadata[row["bill_id"]]
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
    verify = commands.add_parser("verify", aliases=["replay"])
    verify.add_argument("--directory", type=Path, required=True)
    verify.add_argument("--metadata", type=Path)
    verify.add_argument("--source-manifest-sha256")
    verify.add_argument("--gap-queue-sha256")
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_billcam(
            args.source_dir, args.gap_queue, args.out_dir,
            source_manifest_sha256=args.source_manifest_sha256,
            gap_queue_sha256=args.gap_queue_sha256,
        )
    else:
        metadata = None
        if args.metadata:
            rows = pq.read_table(args.metadata).to_pylist()
            require(len({row["bill_id"] for row in rows}) == len(rows),
                    "duplicate supplied original metadata")
            metadata = {row["bill_id"]: row for row in rows}
        _, _, _, manifest = load_billcam(
            args.directory, metadata, source_manifest_sha256=args.source_manifest_sha256,
            gap_queue_sha256=args.gap_queue_sha256,
        )
    print(json.dumps(manifest["counts"], indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

"""Bounded, per-exchange native census capture and entirely offline inventory replay.

This is metadata/source-link recovery, not policy-text or introduction-date certification.
The collector never follows redirects or retries implicitly. Adapters describe archived
record structure; they do not grant collection authority.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import pandas as pd
import requests
import yaml

from ..provenance import USER_AGENT, sha256_file, url_is_fetchable, utc_now_iso
from .openstates_dump import STATE_CODES

MAX_RESPONSE_BYTES = 100 * 1024 * 1024
MAX_STATE_BYTES = 250 * 1024 * 1024
MAX_EXCHANGES = 15
FLAGS = {
    "scientific_approval": False,
    "model_approval": False,
    "analytical_admission": False,
    "full_text_certified": False,
}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        import os

        os.fsync(handle.fileno())


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


class Refusal(RuntimeError):
    """Collection stopped; existing evidence is retained and no retry is authorized."""


class _NoRedirectSession(requests.Session):
    def resolve_redirects(self, *args, **kwargs):
        # Session.send otherwise consumes redirect bodies even with stream=True.
        return iter(())


class Capture:
    """A durable hard-budget capture ledger, resumable only within the same allowance."""

    def __init__(
        self,
        root: Path,
        authorization: dict,
        *,
        session=None,
        sleeper=time.sleep,
        clock=time.monotonic,
    ):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.authorization = authorization
        self.session = session or _NoRedirectSession()
        if session is None:
            self.session.trust_env = False
            self.session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
            self.session.mount("http://", requests.adapters.HTTPAdapter(max_retries=0))
        self.sleep, self.clock = sleeper, clock
        self.last_request = None
        self.ledger = root / "exchanges.jsonl"
        self.events = (
            [json.loads(line) for line in self.ledger.read_text().splitlines()]
            if self.ledger.exists()
            else []
        )
        frozen = root / "authorization.json"
        if frozen.exists():
            if json.loads(frozen.read_text()) != authorization:
                raise Refusal("authorization differs from the frozen allowance")
        else:
            write_json(frozen, authorization)

    def used(self, state: str) -> int:
        return sum(e["event"] == "start" and e["state"] == state for e in self.events)

    def _new_exchange_limit(self, allowed: dict) -> int:
        limit = MAX_EXCHANGES
        if named := allowed.get("explicit_named_exchange_authorization"):
            limit = named.get("physical_exchange_cap", 0)
            if (
                not named.get("scope")
                or not isinstance(limit, int)
                or not 1 <= limit <= 150
                or limit != allowed.get("new_exchange_cap")
            ):
                raise Refusal("invalid explicit named physical exchange authorization")
        return min(limit, allowed.get("new_exchange_cap", 0))

    def _record(self, value: dict) -> None:
        _append(self.ledger, value)
        self.events.append(value)

    def _stop(self, state: str, reason: str) -> None:
        self._record({"event": "stop", "state": state, "reason": reason, "at": utc_now_iso()})
        raise Refusal(reason)

    def _robots(self, state: str, origin: str) -> RobotFileParser:
        event = next(
            (
                event
                for event in reversed(self.events)
                if (
                    event["event"] == "result"
                    and event["state"] == state
                    and event["url"] == origin + "/robots.txt"
                )
            ),
            None,
        )
        retained = event is None
        if retained:
            event = next(
                (
                    item
                    for item in self.authorization["states"][state].get("retained_robots", [])
                    if item["state"] == state and item["url"] == origin + "/robots.txt"
                ),
                None,
            )
        if event is None:
            self._stop(state, f"robots must be archived before retrieving {origin}")
        if retained:
            age = (
                datetime.now(UTC) - datetime.fromisoformat(event["at"].replace("Z", "+00:00"))
            ).total_seconds()
            if not 0 <= age < 86400:
                self._stop(state, "retained robots evidence is outside the allowed 24-hour window")
            if (
                sha256_file(self.root / event["body"]) != event["sha256"]
                or sha256_file(self.root / event["headers_file"]) != event["headers_sha256"]
            ):
                self._stop(state, "retained robots evidence checksum mismatch")
        if not event["complete_body"] or event.get("error"):
            self._stop(state, "robots unavailable or incomplete; no substantive retrieval")
        body = (self.root / event["body"]).read_bytes()
        parser = RobotFileParser()
        if event["status"] == 200:
            parser.parse(body.decode("utf-8-sig", errors="replace").splitlines())
            return parser
        policy = self.authorization["states"][state].get("unavailable_robots_policy")
        if policy != "allow_404_410_only" or event["status"] not in {404, 410}:
            self._stop(state, "robots unavailable or incomplete; no substantive retrieval")
        headers = json.loads((self.root / event["headers_file"]).read_text())
        if (
            any(key.lower() == "location" for key, _ in headers)
            or re.search(rb"(?im)^\s*disallow\s*:\s*\S", body)
            or any(
                token in body.lower()
                for token in (
                    b"cf-chl-",
                    b"verify you are human",
                    b"access denied",
                    b"request blocked",
                    b"blocked by robots",
                    b"captcha",
                )
            )
            or re.search(rb"<input\b[^>]*\btype\s*=\s*['\"]?password", body.lower())
        ):
            self._stop(state, "404/410 robots evidence contains a restriction or redirect")
        if not any(
            item["event"] == "robots_policy"
            and item["state"] == state
            and item.get("evidence_sha256") == event["sha256"]
            for item in self.events
        ):
            self._record(
                {
                    "event": "robots_policy",
                    "state": state,
                    "origin": origin,
                    "decision": policy,
                    "status": event["status"],
                    "retained": retained,
                    "evidence_sha256": event["sha256"],
                    "source_exchange": event["id"],
                    "standard": "RFC9309 section 2.3.1.3; explicit MAY choice, not authorization",
                    "at": utc_now_iso(),
                }
            )
        parser.parse(["User-agent: *", "Allow: /"])
        return parser

    def get(self, state: str, url: str, *, purpose: str, form: dict | None = None) -> dict:
        """Perform exactly one physical exchange; a redirect is returned, not followed."""
        allowed = self.authorization["states"].get(state, {})
        if allowed.get("binding_restriction"):
            raise Refusal(allowed["binding_restriction"])
        if not allowed.get("requests_authorized"):
            raise Refusal("no request authorization")
        if any(e["event"] in {"stop", "closure"} and e["state"] == state for e in self.events):
            raise Refusal("state already stopped; no continuation")
        unfinished = {
            e["id"] for e in self.events if e["event"] == "start" and e["state"] == state
        } - {e["id"] for e in self.events if e["event"] == "result" and e["state"] == state}
        if unfinished:
            self._stop(state, "unresolved prior physical exchange")
        if _origin(url) not in allowed.get("origins", []):
            raise Refusal("origin is not explicitly authorized")
        if reason := url_is_fetchable(url):
            raise Refusal(reason)
        delay = 1.0
        if url != _origin(url) + "/robots.txt":
            robots = self._robots(state, _origin(url))
            if not robots.can_fetch(USER_AGENT, url):
                self._stop(state, f"robots disallows {url}")
            delay = max(delay, robots.crawl_delay(USER_AGENT) or 0)
            rate = robots.request_rate(USER_AGENT)
            if rate:
                delay = max(delay, rate.seconds / rate.requests)
        if self.used(state) >= self._new_exchange_limit(allowed):
            raise Refusal("new physical exchange budget exhausted")
        if (
            allowed.get("known_prior_physical_http_used", 0) + self.used(state)
            >= allowed.get("aggregate_exchange_cap", MAX_EXCHANGES)
        ):
            raise Refusal("known aggregate physical exchange budget exhausted")
        consumed = sum(
            e.get("bytes", 0) for e in self.events if e["event"] == "result" and e["state"] == state
        )
        limit = min(MAX_RESPONSE_BYTES, MAX_STATE_BYTES - consumed)
        if limit <= 0:
            self._stop(state, "state payload limit exhausted")
        if self.last_request is not None:
            self.sleep(max(0, delay - (self.clock() - self.last_request)))
        elif self.used(state):
            self.sleep(delay)
        number = self.used(state) + 1
        exchange_id = f"{state}-{number:02d}"
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        method = "GET" if form is None else "POST"
        start = {
            "event": "start",
            "id": exchange_id,
            "state": state,
            "url": url,
            "method": method,
            "headers": headers,
            "form": form,
            "purpose": purpose,
            "at": utc_now_iso(),
        }
        self._record(start)
        self.last_request = self.clock()
        body_path = self.root / f"{exchange_id}.body"
        result = {
            "event": "result",
            "id": exchange_id,
            "state": state,
            "url": url,
            "status": None,
            "headers": [],
            "body": body_path.name,
            "bytes": 0,
            "complete_body": False,
        }
        response = None
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                data=form,
                allow_redirects=False,
                timeout=(20, 90),
                stream=True,
            )
            result["status"] = response.status_code
            result["headers"] = list(response.raw.headers.items())
            with body_path.open("xb") as handle:
                # decode_content=False plus identity retain the actual response entity bytes.
                chunks = (
                    [response.content]
                    if response._content_consumed
                    else response.raw.stream(65536, decode_content=False)
                )
                for chunk in chunks:
                    if result["bytes"] + len(chunk) > limit:
                        remaining = limit - result["bytes"]
                        handle.write(chunk[:remaining])
                        result["bytes"] += remaining
                        raise Refusal("response/state payload bound reached; partial body retained")
                    handle.write(chunk)
                    result["bytes"] += len(chunk)
            content_length = next(
                (value for key, value in result["headers"] if key.lower() == "content-length"),
                None,
            )
            if content_length is not None and int(content_length) != result["bytes"]:
                raise Refusal("response Content-Length mismatch; captured bytes retained")
            result["complete_body"] = True
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            body_path.touch(exist_ok=True)
        finally:
            if response is not None:
                response.close()
            result["at"] = utc_now_iso()
            result["sha256"] = sha256_file(body_path)
            header_path = self.root / f"{exchange_id}.headers.json"
            write_json(header_path, result["headers"])
            result["headers_file"] = header_path.name
            result["headers_sha256"] = sha256_file(header_path)
            self._record(result)
        if "error" in result:
            self._stop(state, result["error"])
        status = result["status"]
        if status in {401, 403, 407, 429} or status >= 500:
            self._stop(state, f"HTTP {status}: no retry or alternate-host continuation")
        location = next(
            (value for key, value in result["headers"] if key.lower() == "location"), ""
        )
        if 300 <= status < 400 and re.search(
            r"/(?:login|signin|sign-in|authenticate)(?:[/.?]|$)", location, re.I
        ):
            self._stop(state, "authentication redirect; no continuation")
        text = body_path.read_bytes()[:262144].lower()
        if any(
            token in text
            for token in (
                b"cf-chl-",
                b"verify you are human",
                b"access denied",
                b"request blocked",
                b"captcha",
            )
        ):
            self._stop(state, "publisher challenge/block response")
        if re.search(rb"<input\b[^>]*\btype\s*=\s*['\"]?password", text):
            self._stop(state, "password form; no authentication or continuation")
        return result

    def seal(self) -> dict:
        """Hash-bind every raw byte/header/event; this never changes collection status."""
        manifest = {
            "schema_version": 1,
            "status": "raw_capture_not_census_or_text_certification",
            "historical_usage_unknown": True,
            "historical_physical_http_used": None,
            "automatic_redirects": False,
            "automatic_retries": False,
            "capture_integrity_exceptions": (
                json.loads((self.root / "capture_integrity_exceptions.json").read_text())
                if (self.root / "capture_integrity_exceptions.json").exists()
                else []
            ),
            "states": {
                state: {
                    "new_physical_http_cap": spec["new_exchange_cap"],
                    "new_physical_http_used": self.used(state),
                    **(
                        {
                            "known_prior_physical_http_used": (
                                spec["known_prior_physical_http_used"]
                            ),
                            "known_aggregate_physical_http_used": (
                                spec["known_prior_physical_http_used"] + self.used(state)
                            ),
                            "aggregate_exchange_cap": spec["aggregate_exchange_cap"],
                            "known_aggregate_remaining": (
                                spec["aggregate_exchange_cap"]
                                - spec["known_prior_physical_http_used"]
                                - self.used(state)
                            ),
                        }
                        if "known_prior_physical_http_used" in spec
                        else {}
                    ),
                    "new_physical_http_remaining": spec["new_exchange_cap"] - self.used(state),
                    "new_payload_bytes": sum(
                        e.get("bytes", 0)
                        for e in self.events
                        if e["event"] == "result" and e["state"] == state
                    ),
                    "binding_restriction": spec.get("binding_restriction")
                    or next(
                        (
                            e["reason"]
                            for e in self.events
                            if e["event"] == "stop" and e["state"] == state
                        ),
                        None,
                    ),
                    "requests_authorized": spec.get("requests_authorized", False),
                    "closed_for_this_run": any(
                        e["event"] == "closure" and e["state"] == state for e in self.events
                    ),
                    "dispatchable_remaining": (
                        min(
                            self._new_exchange_limit(spec) - self.used(state),
                            spec.get("aggregate_exchange_cap", MAX_EXCHANGES)
                            - spec.get("known_prior_physical_http_used", 0)
                            - self.used(state),
                        )
                        if spec.get("requests_authorized")
                        and not spec.get("binding_restriction")
                        and not any(
                            e["event"] in {"stop", "closure"} and e["state"] == state
                            for e in self.events
                        )
                        else 0
                    ),
                    "unarchived_received_payload_bytes": sum(
                        e.get("unarchived_received_entity_bytes", 0)
                        for e in self.events
                        if e["event"] == "correction" and e["state"] == state
                    ),
                    "stops": [
                        e["reason"]
                        for e in self.events
                        if e["event"] == "stop" and e["state"] == state
                    ],
                    **FLAGS,
                }
                for state, spec in self.authorization["states"].items()
            },
            "files": {
                p.name: sha256_file(p)
                for p in sorted(self.root.iterdir())
                if p.is_file() and p.name != "manifest.json"
            },
            **FLAGS,
        }
        write_json(self.root / "manifest.json", manifest)
        return manifest


@dataclass
class Node:
    tag: str
    attrs: list[tuple[str, str | None]]
    start: int
    end: int = 0
    content: list = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(item.text if isinstance(item, Node) else item for item in self.content)

    def descendants(self):
        for item in self.content:
            if isinstance(item, Node):
                yield item
                yield from item.descendants()


class ArchivedHTML(HTMLParser):
    """Retain exact record spans alongside decoded, unabridged source fields."""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.source = text
        self.lines = [0]
        self.lines.extend(match.end() for match in re.finditer("\n", text))
        self.root = Node("", [], 0, len(text))
        self.stack = [self.root]
        self.feed(text)
        if len(self.stack) != 1:
            raise ValueError("unclosed source HTML; refuse silently truncated record spans")

    def position(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        start = self.position()
        node = Node(tag, attrs, start, start + len(self.get_starttag_text()))
        self.stack[-1].content.append(node)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                end = self.source.find(">", self.position()) + 1
                for node in self.stack[index:]:
                    node.end = end
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].content.append(data)


def select(node: Node, selector: dict | list) -> list[Node]:
    if isinstance(selector, list):
        current = [node]
        for step in selector:
            current = [match for item in current for match in select(item, step)]
        return current
    found = []
    for item in node.descendants():
        attrs = dict(item.attrs)
        if selector.get("tag", item.tag) != item.tag:
            continue
        if any(attrs.get(key) != value for key, value in selector.get("attrs", {}).items()):
            continue
        if not set(selector.get("classes", [])) <= set((attrs.get("class") or "").split()):
            continue
        if any(key not in attrs for key in selector.get("requires", [])):
            continue
        if any(
            value not in (attrs.get(key) or "")
            for key, value in selector.get("attrs_contain", {}).items()
        ):
            continue
        found.append(item)
    return found


def normalized_identifier(literal: str) -> tuple[str | None, str | None, str | None]:
    match = re.fullmatch(r"\s*([A-Za-z]+)\s*0*(\d+)([-\w]*)\s*", literal)
    if match is None:
        return None, None, None
    kind, number, suffix = match.groups()
    return f"{kind.upper()} {int(number)}", kind.upper(), suffix


def parse_page(body: bytes, event: dict, adapter: dict, page: dict) -> dict:
    text = body.decode(adapter.get("encoding", "utf-8"), errors="strict")
    document = ArchivedHTML(text)
    records, links = [], []
    prefixes = (
        select(document.root, adapter["record_prefix_selector"])
        if "record_prefix_selector" in adapter
        else []
    )
    suffixes = (
        select(document.root, adapter["record_suffix_selector"])
        if "record_suffix_selector" in adapter
        else []
    )
    for node in select(document.root, adapter["record_selector"]):
        identity = select(node, adapter["identifier_selector"])
        if not identity:
            continue
        literal = identity[0].text.strip()
        identifier, kind, suffix = normalized_identifier(literal)
        if "identifier_regex" in adapter:
            match = re.fullmatch(adapter["identifier_regex"], literal)
            if match is None:
                raise ValueError(f"source identifier does not match adapter: {literal}")
            kind = match["kind"].upper()
            identifier = f"{kind} {int(match['number'])}"
            suffix = match.groupdict().get("suffix", "")
        session_nodes = (
            select(node, adapter["session_selector"]) if "session_selector" in adapter else []
        )
        session_literal = session_nodes[0].text.strip() if session_nodes else page["session"]
        if "session_regex" in adapter:
            match = re.fullmatch(adapter["session_regex"], session_literal)
            if match is None or match["session"] != page["session"]:
                raise ValueError("record session does not match declared archived query")
        native_id = f"{page['state']}:{page['session']}:{identifier or literal}"
        if adapter.get("native_identity_includes_suffix") and suffix:
            native_id += suffix
        prefix = next(
            (
                candidate
                for candidate in reversed(prefixes)
                if candidate.end <= node.start and not text[candidate.end : node.start].strip()
            ),
            None,
        )
        start = prefix.start if prefix else node.start
        suffix_node = next(
            (
                candidate
                for candidate in suffixes
                if candidate.start >= node.end and not text[node.end : candidate.start].strip()
            ),
            None,
        )
        if "record_suffix_required_selector" in adapter and (
            suffix_node is None
            or not select(suffix_node, adapter["record_suffix_required_selector"])
        ):
            raise ValueError("adjacent source summary row missing or changed")
        end = suffix_node.end if suffix_node else node.end
        field_nodes = [node, suffix_node] if suffix_node else [node]
        source_record_id = f"{event['id']}:{start}"
        fields = {
            key: [
                match.text for field_node in field_nodes for match in select(field_node, selector)
            ]
            for key, selector in adapter.get("fields", {}).items()
        }
        terms = select(node, {"tag": "dt"})
        values = select(node, {"tag": "dd"})
        if len(terms) != len(values):
            raise ValueError("source definition-list labels/values do not pair")
        definitions = [
            {"label": term.text, "literal": value.text}
            for term, value in zip(terms, values, strict=True)
        ]
        dates = [
            {
                **definition,
                "date_basis": adapter["date_labels"][definition["label"].strip()],
                "filing_or_introduction_certified": False,
            }
            for definition in definitions
            if definition["label"].strip() in adapter.get("date_labels", {})
        ]
        dates.extend(
            {
                "label": spec["label"],
                "literal": match.text,
                "date_basis": spec["date_basis"],
                "filing_or_introduction_certified": False,
            }
            for spec in adapter.get("literal_date_selectors", [])
            for match in select(node, spec["selector"])
        )
        record = {
            "source_record_id": source_record_id,
            "native_id": native_id,
            "state": page["state"],
            "session_identifier": page["session"],
            "session_literal": session_literal,
            "session_kind": page["session_kind"],
            "biennium_literal": page.get("biennium_literal"),
            "identifier_literal": literal,
            "identifier": identifier,
            "measure_type": kind,
            "identifier_suffix_literal": suffix,
            "is_bill": kind in adapter.get("bill_types", []),
            "source_record_attrs": node.attrs,
            "publisher_record_key_literal": dict(node.attrs).get(
                adapter.get("publisher_record_key_attribute", "aria-labelledby")
            ),
            "source_record_html_unchanged": text[start:end],
            "source_record_character_span": [start, end],
            "source_fields": fields,
            "source_definition_fields": definitions,
            "literal_date_fields": dates,
            "introduction_date_literal": None,
            "filing_date_literal": None,
            "date_basis": "unknown_no_literal_filing_or_introduction_field_in_census",
            "source_exchange": event["id"],
            "source_url": event["url"],
            "source_body_sha256": event["sha256"],
            "canonical_join_status": "unresolved_native_identity_not_proven_against_canonical",
            **FLAGS,
        }
        if prefix:
            record["source_prefix_attrs"] = prefix.attrs
            record["publisher_record_key_literal"] = dict(prefix.attrs).get("value")
        if adapter.get("canonical_candidate_requires_literal_suffix"):
            record["canonical_candidate_identifier"] = f"{identifier}{suffix or ''}"
        if adapter.get("include_query_context"):
            record["publisher_query_context"] = {
                "session": page["session"],
                "measure_type_scope": page.get("measure_type_scope"),
                "query_semantics": page["query_semantics"],
            }
        if query_key := adapter.get("publisher_record_key_query_parameter"):
            record["publisher_record_key_literal"] = parse_qs(urlsplit(event["url"]).query).get(
                query_key, [None]
            )[0]
        if event.get("event") == "retained_result":
            record["retained_source_provenance"] = event["retained_provenance"]
        records.append(record)
        anchors = [
            match
            for field_node in field_nodes
            for match in select(field_node, {"tag": "a", "requires": ["href"]})
        ]
        if node.tag == "a" and "href" in dict(node.attrs):
            anchors.insert(0, node)
        for ordinal, anchor in enumerate(anchors):
            attrs = dict(anchor.attrs)
            href = attrs["href"]
            url = urljoin(event["url"], href)
            version = parse_qs(urlsplit(url).query).get("v", [None])[0]
            links.append(
                {
                    "source_record_id": source_record_id,
                    "native_id": native_id,
                    "state": page["state"],
                    "session_identifier": page["session"],
                    "identifier": identifier,
                    "ordinal": ordinal,
                    "source_href_literal": href,
                    "absolute_url": url,
                    "source_label_literal": anchor.text,
                    "source_anchor_attrs": anchor.attrs,
                    "version_literal": version,
                    "source_url_query_fields": parse_qs(
                        urlsplit(url).query, keep_blank_values=True
                    ),
                    "version_role": (
                        "explicit_current_not_original"
                        if version == "current"
                        else "publisher_link_version_unverified"
                    ),
                    "original_version_certified": False,
                    "full_original_downloaded": False,
                    **FLAGS,
                }
            )
    pagination = adapter["pagination"]
    count = None
    if pagination.get("count_regex"):
        match = re.search(pagination["count_regex"], document.root.text)
        if match is None:
            raise ValueError("publisher count evidence missing")
        count = int(match["count"])
    page_number, page_count = 1, 1
    if pagination.get("page_regex"):
        match = re.search(pagination["page_regex"], document.root.text)
        if match is None:
            raise ValueError("publisher page/terminal evidence missing")
        page_number, page_count = int(match["page"]), int(match["pages"])
    if pagination.get("range_regex"):
        match = re.search(pagination["range_regex"], document.root.text)
        if match is None:
            raise ValueError("publisher result-range evidence missing")
        query = parse_qs(urlsplit(event["url"]).query)
        page_number = int(query.get(pagination["page_parameter"], ["1"])[0])
        size = int(
            query.get(
                pagination["size_parameter"], [str(pagination["default_page_size"])]
            )[0]
        )
        if (
            size <= 0
            or int(match["start"]) != (page_number - 1) * size + 1
            or int(match["end"]) - int(match["start"]) + 1 != len(records)
            or int(match["end"]) > count
        ):
            raise ValueError("publisher result range disagrees with archived records/query")
        page_count = (count + size - 1) // size
    page_links = [
        {
            "href_literal": dict(anchor.attrs)["href"],
            "url": urldefrag(urljoin(event["url"], dict(anchor.attrs)["href"]))[0],
            "label": anchor.text,
        }
        for anchor in select(document.root, pagination.get("link_selector", {"tag": "never"}))
    ]
    if postback := pagination.get("postback"):
        current = select(document.root, postback["current_page_selector"])
        implicit_single = (
            not current
            and postback.get("implicit_single_page_count_satisfied")
            and count == len(records)
        )
        if len(current) != 1 and not implicit_single:
            raise ValueError("publisher current postback page evidence missing or ambiguous")
        page_number = 1 if implicit_single else int(current[0].text)
        numbered = [int(link["label"]) for link in page_links if link["label"].strip().isdigit()]
        page_count = max([page_number, *numbered])
        for link in page_links:
            match = re.fullmatch(postback["target_regex"], link["href_literal"])
            if match is None:
                raise ValueError("publisher pagination link is not a declared literal postback")
            link["postback_target"] = match["target"]
    closed_document = text.rstrip().lower().endswith("</html>")
    if pagination.get("terminal_regex"):
        closed_document = bool(re.search(pagination["terminal_regex"], text))
    result = {
        "records": records,
        "links": links,
        "evidence": {
            "source_exchange": event["id"],
            "state": page["state"],
            "session": page["session"],
            "measure_type_scope": page.get("measure_type_scope", "all_publisher_query_types"),
            "observed_records": len(records),
            "publisher_reported_count": count,
            "page": page_number,
            "pages": page_count,
            "request_urls": [event["url"]],
            "pagination_links": page_links,
            "terminal_document_closed": closed_document,
            "page_body_complete": event["complete_body"],
            "query_semantics": page["query_semantics"],
            "full_query_count_satisfied": (count == len(records) if count is not None else None),
            "publisher_query_complete": (
                closed_document
                and event["complete_body"]
                and page_number == page_count == 1
                and (count is None or count == len(records))
            ),
            "all_introduced_measures_certified": False,
            **FLAGS,
        },
    }
    if pagination.get("postback"):
        result["evidence"].update(
            {
                "publisher_postback_pagination": True,
                "request_postback_target": (event.get("request_form") or {}).get("__EVENTTARGET"),
                "record_native_ids": [record["native_id"] for record in records],
            }
        )
        if "query_entry_submit_field" in postback:
            form = event.get("request_form") or {}
            result["evidence"]["verified_finite_query_entry_request"] = (
                form.get(postback["query_entry_submit_field"]) == "Search"
                and bool(page.get("query_entry_fields"))
                and all(form.get(key) == value for key, value in page["query_entry_fields"].items())
            )
    return result


def parse_file_index(body: bytes, event: dict, spec: dict) -> list[dict]:
    """Preserve publisher directory entries, never promote files to a measure census."""
    text = body.decode(spec.get("encoding", "utf-8"), errors="strict")
    document = ArchivedHTML(text)
    if not text.rstrip().lower().endswith("</html>") or not event["complete_body"]:
        raise ValueError("incomplete publisher file-index entity")
    records = []
    for directory in select(document.root, {"tag": "pre"}):
        for match in re.finditer(
            r"<br\s*/?>(?P<entry>.*?)(?=<br\s*/?>|</pre>)",
            text[directory.start : directory.end],
            re.S | re.I,
        ):
            entry = match["entry"]
            fragment = ArchivedHTML(entry)
            anchors = select(fragment.root, {"tag": "a", "requires": ["href"]})
            if not anchors:
                continue
            if len(anchors) != 1:
                raise ValueError("ambiguous publisher directory entry")
            anchor = anchors[0]
            columns = unescape(entry[: anchor.start]).strip()
            metadata = re.fullmatch(
                r"(?P<modified>\d+/\d+/\d+\s+\d+:\d+\s+[AP]M)\s+"
                r"(?P<size>\d+|<dir>)",
                columns,
                re.I,
            )
            if metadata is None:
                raise ValueError("publisher file-index columns do not match declared shape")
            start = directory.start + match.start("entry")
            href = dict(anchor.attrs)["href"]
            candidate = re.fullmatch(spec["filename_identity_regex"], anchor.text, re.I)
            records.append(
                {
                    "source_record_id": f"{event['id']}:file:{start}",
                    "state": event["state"],
                    "source_session_context_literal": spec["session"],
                    "source_record_kind": "publisher_file_listing_not_measure_census",
                    "source_record_html_unchanged": entry,
                    "source_record_character_span": [start, start + len(entry)],
                    "filename_literal": anchor.text,
                    "source_href_literal": href,
                    "absolute_url": urljoin(event["url"], href),
                    "source_anchor_attrs": anchor.attrs,
                    "listing_columns_literal": columns,
                    "listing_modified_literal": metadata["modified"],
                    "listing_size_literal": metadata["size"],
                    "filename_identity_candidate": candidate.groupdict() if candidate else None,
                    "candidate_status": "unapproved_filename_not_measure_or_original_stage_proof",
                    "source_exchange": event["id"],
                    "source_url": event["url"],
                    "source_body_sha256": event["sha256"],
                    "introduction_date_literal": None,
                    "filing_date_literal": None,
                    "date_basis": "directory_modified_time_not_filing_or_introduction",
                    "canonical_join_certified": False,
                    "original_version_certified": False,
                    "full_original_downloaded": False,
                    **FLAGS,
                }
            )
    return records


def pagination_complete(pages: list[dict]) -> bool:
    """Require every page, terminal evidence and no duplicate/missing page number."""
    if not pages:
        return False
    expected = pages[0]["pages"]
    ordered = sorted(pages, key=lambda page: page["page"])
    postback = all(page.get("publisher_postback_pagination") for page in pages)
    unique_ids = [
        native_id for page in pages for native_id in page.get("record_native_ids", [])
    ]
    return (
        len(pages) == expected
        and {page["page"] for page in pages} == set(range(1, expected + 1))
        and all(
            page["pages"] == expected
            and page["page_body_complete"]
            and page["terminal_document_closed"]
            for page in pages
        )
        and all(
            any(
                (
                    (
                        link.get("postback_target")
                        == ordered[index + 1].get("request_postback_target")
                        or (
                            ordered[index + 1].get("verified_finite_query_entry_request")
                            and link["label"].strip() == str(ordered[index + 1]["page"])
                        )
                    )
                    if postback
                    else link["url"] in ordered[index + 1].get("request_urls", [])
                )
                for link in page["pagination_links"]
            )
            for index, page in enumerate(ordered[:-1])
        )
        and (
            not postback
            or (
                len(unique_ids) == len(set(unique_ids))
                and all(
                    page["publisher_reported_count"] == len(unique_ids) for page in pages
                )
            )
        )
    )


def _jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def replay(raw: Path, config_path: Path, baseline: Path, out: Path) -> dict:
    """Verify raw captures, preserve entire records and emit identity-only join candidates."""
    if out.exists():
        raise FileExistsError(out)
    manifest = json.loads((raw / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        if sha256_file(raw / name) != digest:
            raise ValueError(f"raw archive checksum mismatch: {name}")
    config = yaml.safe_load(config_path.read_text())
    baseline_manifest = json.loads((baseline / "manifest.json").read_text())
    for name in ("bill_document_coverage.parquet", "document_candidates.parquet"):
        if sha256_file(baseline / name) != baseline_manifest["files"][name]:
            raise ValueError(f"baseline checksum mismatch: {name}")
    events = [json.loads(line) for line in (raw / "exchanges.jsonl").read_text().splitlines()]
    results = {
        event["id"]: event
        for event in events
        if event["event"] in {"result", "retained_result"}
    }
    requests_by_id = {event["id"]: event for event in events if event["event"] == "start"}
    for event in results.values():
        if (
            sha256_file(raw / event["body"]) != event["sha256"]
            or sha256_file(raw / event["headers_file"]) != event["headers_sha256"]
        ):
            raise ValueError("exchange body/header digest disagrees with raw manifest")
        if event["event"] == "retained_result":
            provenance = event["retained_provenance"]
            source_manifest = raw / provenance["manifest_file"]
            if sha256_file(source_manifest) != provenance["manifest_sha256"]:
                raise ValueError("retained source manifest checksum mismatch")
            source_files = json.loads(source_manifest.read_text())["files"]
            if (
                source_files[provenance["original_body_file"]] != event["sha256"]
                or source_files[provenance["original_headers_file"]] != event["headers_sha256"]
            ):
                raise ValueError("retained source entity is not bound by its original manifest")
            requests_by_id[event["id"]] = event["retained_request"]
    records, links, pages = [], [], []
    for page in config["pages"]:
        event = results[page["exchange"]]
        if event["state"] != page["state"] or event["status"] != 200:
            raise ValueError("adapter page is not an archived successful state response")
        parsed = parse_page(
            (raw / event["body"]).read_bytes(),
            {**event, "request_form": requests_by_id[event["id"]].get("form")},
            config["adapters"][page["adapter"]],
            page,
        )
        records.extend(parsed["records"])
        links.extend(parsed["links"])
        pages.append(parsed["evidence"])
    out.mkdir(parents=True)
    _jsonl(out / "native_source_records.jsonl", records)
    _jsonl(out / "source_original_and_version_urls.jsonl", links)
    write_json(out / "source_page_counts.json", pages)
    paginated_queries = []
    for spec in config.get("paginated_queries", []):
        selected = [page for page in pages if page["source_exchange"] in spec["exchanges"]]
        paginated_queries.append(
            {
                **spec,
                "observed_records": sum(page["observed_records"] for page in selected),
                "all_declared_exchanges_present": len(selected) == len(spec["exchanges"]),
                "publisher_query_complete": (
                    len(selected) == len(spec["exchanges"]) and pagination_complete(selected)
                ),
                "introduced_universe_certified": False,
                **FLAGS,
            }
        )
    if config.get("paginated_queries"):
        write_json(out / "publisher_paginated_query_status.json", paginated_queries)
    scope_indexes = []
    query_by_id = {item["id"]: item for item in paginated_queries if "id" in item}
    for spec in config.get("publisher_scope_indexes", []):
        event = results[spec["exchange"]]
        document = ArchivedHTML((raw / event["body"]).read_bytes().decode("utf-8"))
        options = [
            {"value": dict(node.attrs)["value"], "label": node.text}
            for node in select(document.root, spec["option_selector"])
        ]
        mapping = spec["query_ids_by_option_value"]
        scope_indexes.append(
            {
                "state": event["state"],
                "session": spec["session"],
                "source_exchange": event["id"],
                "publisher_listed_options": options,
                "uncompleted_options": [
                    item
                    for item in options
                    if item["value"] not in mapping
                    or not query_by_id.get(mapping[item["value"]], {}).get(
                        "publisher_query_complete"
                    )
                ],
                "all_publisher_listed_queries_complete": (
                    event["status"] == 200
                    and event["complete_body"]
                    and bool(options)
                    and all(
                        item["value"] in mapping
                        and query_by_id.get(mapping[item["value"]], {}).get(
                            "publisher_query_complete"
                        )
                        for item in options
                    )
                ),
                "introduced_universe_certified": False,
                **FLAGS,
            }
        )
    if config.get("publisher_scope_indexes"):
        write_json(out / "publisher_scope_index_status.json", scope_indexes)
    session_index = None
    if spec := config.get("publisher_session_index"):
        event = results[spec["exchange"]]
        document = ArchivedHTML((raw / event["body"]).read_bytes().decode("utf-8"))
        options = [
            {"value": dict(node.attrs)["value"], "label": node.text}
            for node in select(document.root, spec["option_selector"])
            if re.search(spec["target_label_regex"], node.text)
        ]
        by_session = {item["session"]: item for item in scope_indexes}
        contexts = []
        for option in options:
            context = {**option, "introduced_universe_certified": False, **FLAGS}
            if re.search(spec["query_scope_label_regex"], option["label"]):
                context["publisher_query_inventory_complete"] = by_session.get(
                    option["value"], {}
                ).get("all_publisher_listed_queries_complete", False)
            else:
                proof_spec = spec["other_contexts"].get(option["value"])
                if proof_spec:
                    proof = results[proof_spec["exchange"]]
                    body = (raw / proof["body"]).read_bytes().decode("utf-8")
                    proof_document = ArchivedHTML(body)
                    context["source_exchange"] = proof["id"]
                    context["literal_publisher_notice"] = proof_spec["notice"]
                    context["notice_verified"] = (
                        proof["status"] == 200
                        and proof["complete_body"]
                        and proof_spec["notice"] in proof_document.root.text
                    )
                context["publisher_query_inventory_complete"] = None
                context["status"] = "publisher_no_assigned_bills_notice_not_zero_introductions"
            contexts.append(context)
        required = [
            item
            for item in contexts
            if re.search(spec["query_scope_label_regex"], item["label"])
        ]
        session_index = {
            "state": event["state"],
            "source_exchange": event["id"],
            "publisher_target_session_contexts": contexts,
            "all_listed_regular_extraordinary_query_inventories_complete": (
                bool(required)
                and event["status"] == 200
                and event["complete_body"]
                and all(item["publisher_query_inventory_complete"] for item in required)
            ),
            "introduced_universe_certified": False,
            **FLAGS,
        }
        write_json(out / "publisher_session_index_status.json", session_index)
    type_indexes = []
    for spec in config.get("type_indexes", []):
        event = results[spec["exchange"]]
        document = ArchivedHTML((raw / event["body"]).read_bytes().decode("utf-8"))
        listed = sorted(
            {
                urldefrag(urljoin(event["url"], dict(node.attrs)["href"]))[0]
                for node in select(document.root, spec["link_selector"])
            }
        )
        captured = {
            results[page["source_exchange"]]["url"]: page
            for page in pages
            if page["state"] == spec["state"] and page["session"] == spec["session"]
        }
        type_indexes.append(
            {
                "state": spec["state"],
                "session": spec["session"],
                "source_exchange": spec["exchange"],
                "publisher_listed_type_urls": listed,
                "omitted_type_urls": [url for url in listed if url not in captured],
                "all_listed_type_queries_complete": (
                    bool(listed)
                    and event["status"] == 200
                    and event["complete_body"]
                    and all(
                        url in captured and captured[url]["publisher_query_complete"]
                        for url in listed
                    )
                ),
                "introduced_universe_certified": False,
                **FLAGS,
            }
        )
    write_json(out / "publisher_type_index_status.json", type_indexes)
    auxiliary = []
    for spec in config.get("auxiliary_delimited_sources", []):
        event = results[spec["exchange"]]
        text = (raw / event["body"]).read_bytes().decode(spec.get("encoding", "utf-8-sig"))
        for number, line in enumerate(text.split("\n")):
            if line:
                auxiliary.append(
                    {
                        "state": event["state"],
                        "source_exchange": event["id"],
                        "source_line_number": number + 1,
                        "source_record_unchanged": line,
                        "source_columns_without_inferred_schema": line.rstrip("\r").split(
                            spec["sep"]
                        ),
                        "target_scope_status": spec["target_scope_status"],
                        "date_basis": "uninterpreted_literal_columns_no_introduction_inference",
                        **FLAGS,
                    }
                )
    _jsonl(out / "auxiliary_source_records.jsonl", auxiliary)
    auxiliary_html, auxiliary_links = [], []
    for spec in config.get("auxiliary_html_sources", []):
        event = results[spec["exchange"]]
        if event["status"] != 200 or not event["complete_body"]:
            raise ValueError("auxiliary HTML requires a complete successful archived entity")
        text = (raw / event["body"]).read_bytes().decode(spec.get("encoding", "utf-8"))
        document = ArchivedHTML(text)
        for node in select(document.root, spec["record_selector"]):
            source_id = f"{event['id']}:auxiliary:{node.start}"
            auxiliary_html.append(
                {
                    "source_record_id": source_id,
                    "state": event["state"],
                    "source_exchange": event["id"],
                    "source_url": event["url"],
                    "source_body_sha256": event["sha256"],
                    "source_record_html_unchanged": text[node.start : node.end],
                    "source_record_character_span": [node.start, node.end],
                    "source_fields": {
                        key: [match.text for match in select(node, selector)]
                        for key, selector in spec.get("fields", {}).items()
                    },
                    "target_scope_status": spec["target_scope_status"],
                    "native_measure_identity_certified": False,
                    "introduction_date_literal": None,
                    "filing_date_literal": None,
                    **FLAGS,
                }
            )
            for anchor in select(node, {"tag": "a", "requires": ["href"]}):
                href = dict(anchor.attrs)["href"]
                auxiliary_links.append(
                    {
                        "source_record_id": source_id,
                        "source_href_literal": href,
                        "absolute_url": urljoin(event["url"], href),
                        "source_label_literal": anchor.text,
                        "source_anchor_attrs": anchor.attrs,
                        "target_scope_status": spec["target_scope_status"],
                        "source_link_is_not_fetch_authorization": True,
                        "original_version_certified": False,
                        "full_original_downloaded": False,
                        **FLAGS,
                    }
                )
    if config.get("auxiliary_html_sources"):
        _jsonl(out / "auxiliary_html_source_records.jsonl", auxiliary_html)
        _jsonl(out / "auxiliary_html_source_links.jsonl", auxiliary_links)
    file_entries = []
    for spec in config.get("auxiliary_file_indexes", []):
        event = results[spec["exchange"]]
        if event["status"] != 200:
            raise ValueError("file-index adapter requires a successful archived response")
        file_entries.extend(parse_file_index((raw / event["body"]).read_bytes(), event, spec))
    if config.get("auxiliary_file_indexes"):
        _jsonl(out / "publisher_file_index_records.jsonl", file_entries)
        _jsonl(
            out / "publisher_file_index_source_urls.jsonl",
            [
                {
                    key: row[key]
                    for key in (
                        "source_record_id",
                        "state",
                        "source_session_context_literal",
                        "filename_literal",
                        "source_href_literal",
                        "absolute_url",
                        "candidate_status",
                        "original_version_certified",
                        "full_original_downloaded",
                        *FLAGS,
                    )
                }
                for row in file_entries
            ],
        )

    target_states = list(manifest["states"])
    canonical = pd.read_parquet(
        baseline / "bill_document_coverage.parquet", filters=[("state", "in", target_states)]
    )
    canonical.to_parquet(out / "retained_canonical_coverage_unchanged.parquet", index=False)
    references = pd.read_parquet(
        baseline / "document_candidates.parquet", filters=[("state", "in", target_states)]
    )
    references.to_parquet(out / "retained_canonical_references_unchanged.parquet", index=False)
    keys = {}
    for record in canonical.to_dict("records"):
        identifier, _, _ = normalized_identifier(record["identifier"])
        key = (record["state"], record["session_identifier"], identifier)
        keys.setdefault(key, []).append(record["bill_id"])
    joins = []
    for record in records:
        state, session = record["state"], record["session_identifier"]
        candidate_session = (
            config.get("canonical_session_candidate_aliases", {})
            .get(state, {})
            .get(session, session)
        )
        candidates = keys.get(
            (
                state,
                candidate_session,
                record.get("canonical_candidate_identifier", record["identifier"]),
            ),
            [],
        )
        joins.append(
            {
                "source_record_id": record["source_record_id"],
                "native_id": record["native_id"],
                "candidate_canonical_bill_ids": candidates,
                "status": (
                    "unresolved_exact_typed_session_identifier_candidate_not_source_identity_proof"
                    if candidates
                    else "unresolved_no_exact_typed_session_identifier_candidate"
                ),
                "canonical_join_certified": False,
                **FLAGS,
            }
        )
    _jsonl(out / "canonical_identity_candidates.jsonl", joins)
    observed_keys = {
        (
            row["state"],
            config.get("canonical_session_candidate_aliases", {})
            .get(row["state"], {})
            .get(row["session_identifier"], row["session_identifier"]),
            row.get("canonical_candidate_identifier", row["identifier"]),
        )
        for row in records
    }
    observed_sessions = {(state, session) for state, session, _ in observed_keys}
    canonical_only = [
        {
            **row,
            "status": "canonical_only_observed_session_not_missing_introduction_proof",
        }
        for row in canonical.to_dict("records")
        if (row["state"], row["session_identifier"]) in observed_sessions
        and (
            row["state"],
            row["session_identifier"],
            normalized_identifier(row["identifier"])[0],
        )
        not in observed_keys
    ]
    _jsonl(out / "canonical_only_in_observed_sessions.jsonl", canonical_only)
    statuses = {}
    for code in sorted(STATE_CODES):
        state = code.upper()
        state_pages = [page for page in pages if page["state"] == state]
        native = [record for record in records if record["state"] == state]
        statuses[state] = {
            "state": state,
            "status": config.get("state_status", {}).get(state, "outside_this_bounded_batch"),
            "observed_native_records": len(native),
            "observed_native_identities": len({record["native_id"] for record in native}),
            "publisher_query_pages_complete": sum(
                page["publisher_query_complete"] for page in state_pages
            ),
            "introduced_universe_complete": False,
            "source_session_status": state_pages,
            "literal_date_basis": "no_filing_or_introduction_field_in_archived_censuses",
            "historical_usage_unknown": True,
            "historical_physical_http_used": None,
            "new_budget_is_increment_not_historical_usage": True,
            "all_originals_available_or_recovered": False,
            "native_introduced_universe_count": None,
            "new_full_original_documents": 0,
            "full_original_archives": [],
            **manifest["states"].get(state, {}),
            **FLAGS,
        }
    report = {
        "schema_version": 1,
        "status": "bounded_native_metadata_inventory_not_introduced_or_full_text_certification",
        "states": statuses,
        "n_native_records": len(records),
        "n_source_links_including_duplicates": len(links),
        "n_auxiliary_out_of_target_source_records": len(auxiliary),
        "n_candidate_exact_identity_matches": sum(
            bool(join["candidate_canonical_bill_ids"]) for join in joins
        ),
        "n_certified_canonical_joins": 0,
        "publisher_type_indexes": type_indexes,
        "canonical_only_counts_in_observed_sessions": {
            state: {
                session: sum(
                    row["state"] == state and row["session_identifier"] == session
                    for row in canonical_only
                )
                for observed_state, session in sorted(observed_sessions)
                if observed_state == state
            }
            for state in target_states
        },
        "raw_manifest_sha256": sha256_file(raw / "manifest.json"),
        "raw_archive": str(raw),
        "original_version_limitation": (
            "No no-login bulk full-original archive discovered. No per-bill documents fetched. "
            "Publisher current and unversioned source links remain distinct, not originals proof."
        ),
        "scope_limitations": config["scope_limitations"],
        "capture_integrity_exceptions": manifest.get("capture_integrity_exceptions", []),
        **FLAGS,
    }
    if config.get("auxiliary_file_indexes"):
        report["publisher_file_index_counts_not_measure_censuses"] = {
            "total_entries": len(file_entries),
            "sessions": {
                spec["session"]: sum(
                    row["source_exchange"] == spec["exchange"] for row in file_entries
                )
                for spec in config["auxiliary_file_indexes"]
            },
            "file_entries_are_not_downloaded_originals": True,
            "listing_modified_times_are_not_introduction_dates": True,
        }
    if config.get("paginated_queries"):
        report["publisher_paginated_queries"] = paginated_queries
    if config.get("auxiliary_html_sources"):
        report["auxiliary_html_out_of_target_record_count"] = len(auxiliary_html)
        report["auxiliary_html_unverified_links"] = len(auxiliary_links)
    if config.get("publisher_scope_indexes"):
        report["publisher_scope_indexes"] = scope_indexes
    if session_index is not None:
        report["publisher_session_index"] = session_index
    write_json(out / "report.json", report)
    with (out / "state_session_type_counts.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["state", "session", "measure_type", "is_bill", "n_records"]
        )
        writer.writeheader()
        groups = {}
        for record in records:
            key = (
                record["state"],
                record["session_identifier"],
                record["measure_type"],
                record["is_bill"],
            )
            groups[key] = groups.get(key, 0) + 1
        for (state, session, kind, is_bill), count in sorted(groups.items()):
            writer.writerow(
                dict(
                    state=state,
                    session=session,
                    measure_type=kind,
                    is_bill=is_bill,
                    n_records=count,
                )
            )
    output_manifest = {
        "schema_version": 1,
        "status": report["status"],
        "inputs": {
            "raw_manifest": {
                "path": str(raw / "manifest.json"),
                "sha256": sha256_file(raw / "manifest.json"),
            },
            "adapter_configuration": {"path": str(config_path), "sha256": sha256_file(config_path)},
            "producer": {"path": str(Path(__file__)), "sha256": sha256_file(Path(__file__))},
            "baseline_manifest": {
                "path": str(baseline / "manifest.json"),
                "sha256": sha256_file(baseline / "manifest.json"),
            },
        },
        "files": {path.name: sha256_file(path) for path in sorted(out.iterdir())},
        **FLAGS,
    }
    write_json(out / "manifest.json", output_manifest)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture", help="one explicitly authorized physical GET")
    capture.add_argument("--raw", type=Path, required=True)
    capture.add_argument("--authorization", type=Path, required=True)
    capture.add_argument("--state", required=True)
    capture.add_argument("--url", required=True)
    capture.add_argument("--purpose", required=True)
    capture.add_argument("--form-json", help="literal publisher form fields; sends one POST")
    offline = sub.add_parser(
        "replay", help="offline-only parse, counts and unresolved exact-key joins"
    )
    offline.add_argument("--raw", type=Path, required=True)
    offline.add_argument("--config", type=Path, required=True)
    offline.add_argument("--baseline", type=Path, required=True)
    offline.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "replay":
        report = replay(args.raw, args.config, args.baseline, args.out)
        print(
            json.dumps({key: value for key, value in report.items() if key != "states"}, indent=2)
        )
        return 0
    archive = Capture(args.raw, json.loads(args.authorization.read_text()))
    try:
        result = archive.get(
            args.state,
            args.url,
            purpose=args.purpose,
            form=json.loads(args.form_json) if args.form_json else None,
        )
        print(json.dumps(result, indent=2))
        return 0
    except Refusal as exc:
        print(json.dumps({"status": "stopped", "reason": str(exc)}))
        return 2
    finally:
        archive.seal()


if __name__ == "__main__":
    raise SystemExit(main())

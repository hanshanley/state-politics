"""One operator-selected KY-R caucus source, using unchanged native Capture.

The new allowance is at most 15 physical exchanges, including fresh robots.
Only the exact retained source and necessary same-origin redirects are eligible.
Unknown historical request usage remains unknown. A stopped capture is never
reopened; complete received source may still be inspected entirely offline.
An additive packet is emitted only for actual native agenda text, not registry
descriptions or challenge/error pages. No legacy caucus table is fabricated.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import yaml

from state_politics import provenance
from state_politics.bills import native_inventory as native

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "https://kysenaterepublicans.com"
URL = ORIGIN + "/new-page-34"
ROBOTS = ORIGIN + "/robots.txt"
CAP = 15
FLAGS = {
    "model_input_approved": False, "training_admission": False,
    "analytical_admission": False, "operative_approval": False,
    "scientific_approval": False, "publication_approved": False,
    "adoption_certified": False, "human_gold": False,
}


def _write(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _pin(path: Path) -> dict:
    return {"path": str(path), "sha256": provenance.sha256_file(path),
            "bytes": path.stat().st_size}


def _same_origin(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.scheme, parts.netloc) == ("https", "kysenaterepublicans.com")


def _url(value) -> bool:
    return isinstance(value, str) and _same_origin(value)


def _objects(value, pointer=""):
    if isinstance(value, dict):
        yield pointer, value
        for key, child in value.items():
            yield from _objects(child, pointer + "/" + str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _objects(child, pointer + "/" + str(index))


def _restrictions(row: dict) -> list[dict]:
    found = []
    for pointer, obj in _objects(row):
        bound = any(_url(obj.get(key)) for key in (
            "url", "final_url", "fetched_url", "request_url", "origin"
        )) or any(_url(item) for item in obj.get("origins", []) if isinstance(item, str))
        if not bound:
            continue
        status = obj.get("status", obj.get("http_status"))
        if status in {401, 403, 407, 429}:
            found.append({"pointer": pointer, "reason": f"retained HTTP {status}",
                          "evidence": obj})
        explicit = obj.get("binding_restriction")
        if explicit:
            found.append({"pointer": pointer, "reason": str(explicit), "evidence": obj})
        reason = str(obj.get("error") or obj.get("reason") or "")
        if re.search(
            r"SSLError|TLS|certificate|robots.{0,35}(?:disallow|block)|"
            r"(?:authentication|password|challenge|HTTP (?:401|403|407|429))",
            reason, re.I,
        ):
            found.append({"pointer": pointer, "reason": reason, "evidence": obj})
        if obj.get("url") == ROBOTS and isinstance(obj.get("extracted_text"), str):
            parser = RobotFileParser()
            parser.parse(obj["extracted_text"].splitlines())
            if not parser.can_fetch(provenance.USER_AGENT, URL):
                found.append({"pointer": pointer, "reason": "retained robots disallows source",
                              "evidence": obj})
    return found


def preflight(
    baseline: Path, source_manifest: Path, *, global_provenance: Path | None,
) -> dict:
    """Inspect only exact retained bindings and the documented provenance ledger."""
    base = _json(baseline / "manifest.json")
    pins = {}
    for name, expected in base["files"].items():
        path = baseline / name
        actual = _pin(path)
        if actual["sha256"] != expected["sha256"] or actual["bytes"] != expected["bytes"]:
            raise ValueError(f"baseline hash/size mismatch: {name}")
        pins[str(path)] = actual
    manifest_pin = _pin(baseline / "manifest.json")
    source_pin = _pin(source_manifest)
    retained_binding = next(p for p in base["inputs"] if p["path"] == str(source_manifest))
    if source_pin["sha256"] != retained_binding["sha256"]:
        raise ValueError("baseline platform-source manifest binding mismatch")
    inputs = _json(source_manifest)["inputs"]
    selected = {
        str(baseline / "retained_evidence_views.jsonl"): pins[
            str(baseline / "retained_evidence_views.jsonl")
        ],
        str(baseline / "caucus_observations.jsonl"): pins[
            str(baseline / "caucus_observations.jsonl")
        ],
    }
    for pin in inputs:
        if Path(pin["path"]).suffix in {".json", ".jsonl", ".yaml", ".yml", ".csv"}:
            selected[pin["path"]] = pin
    if global_provenance is not None and global_provenance.exists():
        selected[str(global_provenance)] = _pin(global_provenance)
    matches, restrictions, scanned = [], [], []
    for name, expected in sorted(selected.items()):
        path = Path(name)
        actual = _pin(path)
        if any(actual[k] != expected[k] for k in ("sha256", "bytes")):
            raise ValueError(f"retained preflight input changed: {name}")
        scanned.append(actual)
        raw = path.read_bytes()
        if b"kysenaterepublicans.com" not in raw.lower():
            continue
        if path.suffix == ".jsonl":
            values, contexts = [], {}
            for i, line in enumerate(raw.split(b"\n"), 1):
                if not line:
                    continue
                row = json.loads(line)
                if row.get("event") in {"start", "result"} and isinstance(row.get("url"), str):
                    if _url(row["url"]):
                        contexts[row.get("state")] = {"request_line": i, "request": row}
                    else:
                        contexts.pop(row.get("state"), None)
                if (row.get("event") == "stop" and row.get("state") in contexts):
                    restrictions.append({
                        "path": name, "line": i, "file_sha256": actual["sha256"],
                        "reason": row["reason"], "evidence": row,
                        "associated_origin_request": contexts[row["state"]],
                    })
                    values.append((i, row))
                elif b"kysenaterepublicans.com" in line.lower():
                    values.append((i, row))
        elif path.suffix in {".yml", ".yaml"}:
            values = [(None, yaml.safe_load(raw))]
        elif path.suffix == ".json":
            values = [(None, json.loads(raw))]
        else:
            raise ValueError("origin found in CSV: explicit review required before dispatch")
        for line, row in values:
            evidence = {"path": name, "sha256": actual["sha256"], "line": line, "record": row}
            matches.append(evidence)
            restrictions.extend({**r, "path": name, "line": line,
                                 "file_sha256": actual["sha256"]} for r in _restrictions(row))
    caucus = next(
        row for row in (
            json.loads(line) for line in
            (baseline / "caucus_observations.jsonl").read_text().split("\n") if line
        ) if row["record_id"] == "caucus:KY:R"
    )
    if (caucus["institution_type"] != "legislative_caucus"
            or caucus["retained_record"]["urls"][0] != URL
            or caucus["extracted_text"] is not None):
        raise ValueError("operator-selected missing caucus source does not match baseline")
    return {
        "schema": "single_caucus_source_preflight_v1",
        "status": "blocked_by_retained_evidence" if restrictions else
                  "no_binding_restriction_found_in_bounded_retained_inputs",
        "source_url": URL, "origin": ORIGIN, "baseline_manifest": manifest_pin,
        "baseline_files": list(pins.values()), "source_manifest": source_pin,
        "scanned_inputs": scanned, "matching_records": matches,
        "binding_restrictions": restrictions, "selected_caucus_record": caucus,
        "historical_usage_unknown": True, "historical_physical_http_used": None,
        "scope_limitation": (
            "These exact source-hashed ledgers plus the documented current provenance ledger; "
            "no recursive campaign search and no assertion that unretained usage was zero."
        ),
        **FLAGS,
    }


class NativePage(HTMLParser):
    """Complete visible native text plus source-exact anchor attribute spans."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source, self.chunks, self.links = source, [], []
        self.ignored = []
        self.anchor = None
        self.line_offsets = [0]
        for match in re.finditer("\n", source):
            self.line_offsets.append(match.end())
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored.append(tag)
        if self.ignored:
            return
        if tag in {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "section", "article"}:
            self.chunks.append("\n")
        if tag == "a":
            href = dict(attrs).get("href")
            if href is None:
                return
            raw = self.get_starttag_text()
            match = re.search(
                r"""\bhref\s*=\s*(?:["'](?P<quoted>[^"']*)["']|(?P<bare>[^\s>]+))""",
                raw, re.I,
            )
            line, column = self.getpos()
            offset = self.line_offsets[line - 1] + column
            span = None
            if match:
                group = "quoted" if match.group("quoted") is not None else "bare"
                start, end = offset + match.start(group), offset + match.end(group)
                span = {"start": start, "end": end, "exact_text": self.source[start:end]}
            self.anchor = {"href": href, "href_source_span": span, "label_chunks": []}

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag == "a" and self.anchor is not None:
            self.anchor["anchor_text"] = re.sub(
                r"\s+", " ", "".join(self.anchor.pop("label_chunks"))
            ).strip()
            self.links.append(self.anchor)
            self.anchor = None
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "section", "article"}:
            self.chunks.append("\n")

    def handle_data(self, data):
        if not self.ignored:
            self.chunks.append(data)
            if self.anchor is not None:
                self.anchor["label_chunks"].append(data)

    @property
    def text(self):
        text = re.sub(r"[ \t\r\f\v]+", " ", "".join(self.chunks))
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def _literal_spans(text: str) -> list[dict]:
    return [{
        "start": m.start(), "end": m.end(), "exact_text": m.group(),
        "year": int(m.group()),
        "context_start": max(0, m.start() - 100),
        "context_end": min(len(text), m.end() + 100),
        "context": text[max(0, m.start() - 100):min(len(text), m.end() + 100)],
        "interpretation": "native_visible_year_literal_not_adoption_or_applicability",
    } for m in re.finditer(r"\b(?:19|20)\d{2}\b", text)]


def _headers(result: dict) -> dict:
    return {key.lower(): value for key, value in result["headers"]}


def extract_received(raw: Path, results: list[dict]) -> dict | None:
    """Offline only. Even a generic literal stop remains a closed stop in the ledger."""
    received = next((r for r in reversed(results) if r["url"] != ROBOTS
                     and _same_origin(r["url"]) and r["status"] == 200
                     and r["complete_body"] and not r.get("error")), None)
    if received is None:
        return None
    body = (raw / received["body"]).read_bytes()
    if hashlib.sha256(body).hexdigest() != received["sha256"]:
        raise ValueError("received native source bytes changed")
    headers = _headers(received)
    encoding = headers.get("content-encoding", "identity").lower()
    if encoding == "gzip":
        body = gzip.decompress(body)
    elif encoding != "identity":
        return None
    if "html" not in headers.get("content-type", "").lower():
        return None
    charset = re.search(r"charset=([-\w]+)", headers.get("content-type", ""), re.I)
    codec = charset.group(1) if charset else "utf-8"
    source = body.decode(codec, errors="strict")
    page = NativePage(source)
    links = []
    for link in page.links:
        absolute = urljoin(received["url"], unescape(link["href"]))
        parsed = urlsplit(absolute)
        links.append({
            **link, "resolved_reference_only_not_requested": absolute,
            "native_24rs_senate_bill_reference": (
                parsed.netloc == "apps.legislature.ky.gov"
                and bool(re.fullmatch(r"/record/24rs/sb\d+\.html", parsed.path, re.I))
            ),
        })
    text = page.text
    if not (len(text) >= 80 and re.search(r"\b(?:legislation|priorit(?:y|ies)|agenda)\b", text,
                                        re.I)
            and (any(link["native_24rs_senate_bill_reference"] for link in links)
                 or re.search(r"\b(?:senate|senator|Republican)\b", text, re.I))):
        return None
    return {
        "received": received, "source_html": source, "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "decoded_charset": codec, "received_content_encoding": encoding,
        "native_year_literals": _literal_spans(text), "native_links": links,
    }


def _assert_stable(pins: list[dict]) -> None:
    for pin in pins:
        if _pin(Path(pin["path"])) != pin:
            raise ValueError(f"bound input changed: {pin['path']}")


def _seal(root: Path, report: dict) -> dict:
    report["files"] = {
        str(path.relative_to(root)): {
            "sha256": provenance.sha256_file(path), "bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*")) if path.is_file() and path != root / "manifest.json"
    }
    _write(root / "manifest.json", report)
    return report


def _additive(out: Path, baseline: Path, operation: Path, pre: dict, extracted: dict) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    selected = pre["selected_caucus_record"]
    (out / "source.html").write_text(extracted["source_html"], encoding="utf-8")
    (out / "source_text.txt").write_text(extracted["text"], encoding="utf-8")
    _write(out / "native_links.json", extracted["native_links"])
    _write(out / "native_year_literals.json", extracted["native_year_literals"])
    printed = sorted({r["year"] for r in extracted["native_year_literals"]})
    observation = {
        "record_id": "caucus-native:KY:R:" + extracted["received"]["sha256"],
        "state": "KY", "party": "R", "institution_type": "legislative_caucus",
        "institution": selected["institution"], "record_kind": "supplementary_caucus_native_page",
        "source_url": URL, "received_url": extracted["received"]["url"],
        "source_sha256": extracted["received"]["sha256"],
        "source_body": str(operation / "raw" / extracted["received"]["body"]),
        "source_headers": str(operation / "raw" / extracted["received"]["headers_file"]),
        "extraction_method": "stdlib_htmlparser_visible_text_scripts_styles_excluded_v1",
        "complete_received_visible_text": extracted["text"],
        "text_sha256": extracted["text_sha256"],
        "native_year_literals": extracted["native_year_literals"],
        "native_printed_years_not_interpreted_as_adoption": printed,
        "n_native_24rs_bill_link_occurrences": sum(
            link["native_24rs_senate_bill_reference"] for link in extracted["native_links"]
        ),
        "registry_metadata_year_hint_not_source_date": 2024,
        "source_reported_adoption_date": None, "source_reported_applicability": None,
        "operative_platform_status": "unresolved", "cycle_applicability": "unresolved",
        "analysis_cutoff": None,
        "cycle_relation": ("native_2024_literal_requires_role_review_not_target_admitted"
                           if 2024 in printed else
                           "ancillary_undated_or_later_not_target_cycle_recovery"),
        "availability": "complete_received_native_text",
        **FLAGS,
    }
    with (out / "caucus_native_observations.jsonl").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(observation, ensure_ascii=False, allow_nan=False) + "\n")
    return _seal(out, {
        "schema": "additive_single_caucus_graph_inputs_v2", "status": "observation_only",
        "baseline_packet": str(baseline), "baseline_manifest": pre["baseline_manifest"],
        "operation_manifest": _pin(operation / "manifest.json"),
        "n_new_native_source_observations": 1, "n_canonical_or_original_table_rows_inferred": 0,
        "all_other_caucus_sources_not_requested": ["MD:D:2026", "NJ:R:2025", "PA:D:2025"],
        "source_year_literal_role_not_adoption_or_applicability": True,
        "no_legacy_caucus_table_emitted": True, "baseline_modified": False,
        **FLAGS,
    })


def run(
    operation: Path, out: Path, *, baseline: Path, source_manifest: Path,
    global_provenance: Path | None, capture_factory=native.Capture,
) -> dict:
    """Preflight, dispatch one new closed allowance, and optionally add native text."""
    if out.exists():
        raise FileExistsError("refusing an existing additive packet")
    operation.mkdir(parents=True, exist_ok=False)
    pre = preflight(baseline, source_manifest, global_provenance=global_provenance)
    _write(operation / "preflight.json", pre)
    code = [
        _pin(Path(__file__)), _pin(Path(native.__file__)), _pin(Path(provenance.__file__)),
    ]
    for pin in code:
        (operation / Path(pin["path"]).name).write_bytes(Path(pin["path"]).read_bytes())
    selection = {
        "selection": "new_explicit_operator_selected_single_missing_caucus_source",
        "authorization_recorded_at": provenance.utc_now_iso(), "source_url": URL,
        "allowed_origin": ORIGIN, "new_physical_exchange_cap": CAP,
        "scope": "fresh robots, exact retained page, necessary same-origin redirects only",
        "no_search_or_other_hosts_or_underlying_bill_requests": True,
        "historical_usage_unknown": True, "historical_physical_http_used": None,
        "new_allowance_is_not_a_cap_increase_or_renewal_of_a_closed_allowance": True,
        "no_source_restriction_lifted": True,
        "user_agent_unchanged": provenance.USER_AGENT,
        "automatic_redirects": False, "automatic_retries": False,
        "capture_class": "state_politics.bills.native_inventory.Capture",
        "code_bindings": code, "preflight_sha256": provenance.sha256_file(
            operation / "preflight.json"
        ),
        **FLAGS,
    }
    _write(operation / "operator_selection.json", selection)
    blocked = pre["binding_restrictions"]
    authorization = {
        "states": {"KY": {
            "origins": [ORIGIN], "requests_authorized": not bool(blocked),
            "new_exchange_cap": CAP if not blocked else 0,
            "binding_restriction": blocked[0]["reason"] if blocked else None,
            "historical_physical_http_used": None,
            "operator_selection_sha256": provenance.sha256_file(
                operation / "operator_selection.json"
            ),
        }},
        "historical_usage_unknown": True, **FLAGS,
    }
    capture = capture_factory(operation / "raw", authorization)
    stop = None
    try:
        if blocked:
            stop = "pre-existing binding restriction; no physical exchange dispatched"
        else:
            robots = capture.get(
                "KY", ROBOTS, purpose="fresh robots for exact selected caucus page"
            )
            if robots["status"] != 200:
                stop = "fresh robots not HTTP 200; no substantive retrieval or redirect workaround"
            else:
                current, seen = URL, set()
                while current not in seen:
                    seen.add(current)
                    result = capture.get("KY", current, purpose="exact selected caucus source")
                    if not 300 <= result["status"] < 400:
                        stop = "selected source received; no additional sources authorized"
                        break
                    location = _headers(result).get("location")
                    following = urldefrag(urljoin(current, location or ""))[0]
                    if not location or not _same_origin(following):
                        stop = "redirect is absent or outside exact authorized origin; not followed"
                        break
                    current = following
                else:
                    stop = "redirect loop; no retry authorized"
    except native.Refusal as error:
        stop = str(error)
    finally:
        closure = {
            "event": "closure", "state": "KY", "reason": stop or "capture closed after exception",
            "at": provenance.utc_now_iso(), "new_physical_http_used": capture.used("KY"),
            "new_physical_http_cap": CAP if not blocked else 0,
            "historical_usage_unknown": True, "historical_physical_http_used": None,
            "continuation_authorized": False, **FLAGS,
        }
        capture._record(closure)
        _write(operation / "closure.json", closure)
        raw_manifest = capture.seal()
    results = [event for event in capture.events if event["event"] == "result"]
    extracted = extract_received(operation / "raw", results)
    bound_inputs = [
        pre["baseline_manifest"], pre["source_manifest"], *pre["baseline_files"],
        *pre["scanned_inputs"], *code,
    ]
    _assert_stable(bound_inputs)
    report = _seal(operation, {
        "schema": "closed_single_caucus_source_followup_v2",
        "status": "closed_native_text_received" if extracted else "closed_no_native_text_recovery",
        "source_url": URL, "baseline_manifest": pre["baseline_manifest"],
        "new_physical_http_used": capture.used("KY"),
        "new_payload_bytes": sum(row["bytes"] for row in results),
        "historical_usage_unknown": True, "historical_physical_http_used": None,
        "binding_restrictions_before_dispatch": blocked,
        "capture_binding_restriction": raw_manifest["states"]["KY"]["binding_restriction"],
        "capture_closed": raw_manifest["states"]["KY"]["closed_for_this_run"],
        "dispatchable_remaining": raw_manifest["states"]["KY"]["dispatchable_remaining"],
        "closure_reason": closure["reason"],
        "generic_challenge_stop_does_not_prove_waf": True,
        "n_complete_received_native_texts": int(extracted is not None),
        "new_native_text_chars": len(extracted["text"]) if extracted else 0,
        "raw_results": results, "code_bindings": code,
        "input_stability_verified": True, **FLAGS,
    })
    if extracted:
        _additive(out, baseline, operation, pre, extracted)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--operation", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--baseline", type=Path, default=ROOT /
                        "data/processed/recovered-platform-graph-inputs-20261022-v1")
    parser.add_argument("--source-manifest", type=Path, default=ROOT /
                        "data/preview-cycle-evidence-v7/downloads/platform_source_manifest.json")
    parser.add_argument("--provenance", type=Path, default=ROOT / "data/provenance.jsonl")
    args = parser.parse_args(argv)
    report = run(args.operation.absolute(), args.out.absolute(), baseline=args.baseline,
                 source_manifest=args.source_manifest, global_provenance=args.provenance)
    print(json.dumps({key: report[key] for key in (
        "status", "new_physical_http_used", "new_payload_bytes", "capture_binding_restriction",
        "capture_closed", "dispatchable_remaining", "new_native_text_chars", "closure_reason"
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

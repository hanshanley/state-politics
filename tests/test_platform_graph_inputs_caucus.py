"""Single-origin native Capture follow-through; no test performs network I/O."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import requests

from state_politics.bills import native_inventory as native
from state_politics.platforms import graph_inputs_caucus as followup


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


ROBOTS = b"User-agent: *\nAllow: /\n"
PAGE = (
    b"<html><head><title>Senate Republican Legislation</title></head><body>"
    b"<h1>2024 Priority Legislation</h1><p>Senate Republicans traditionally identify "
    b"Senate Bills 1 through 10 as priority legislation.</p>"
    b'<a href="https://apps.legislature.ky.gov/record/24rs/sb1.html">Senate Bill 1</a>'
    b'<a href="https://apps.legislature.ky.gov/record/24rs/sb2.html">Senate Bill 2</a>'
    b"</body></html>"
)


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        assert kwargs["allow_redirects"] is False
        assert kwargs["headers"]["User-Agent"] == followup.provenance.USER_AGENT
        self.requests.append({"method": method, "url": url, **kwargs})
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        status, body, headers = response
        return SimpleNamespace(
            status_code=status, content=body, _content_consumed=True,
            raw=SimpleNamespace(headers=headers), close=lambda: None,
        )


@pytest.fixture
def packet(request, monkeypatch):
    root = Path(request.config.rootpath) / (
        "data/processed/platform-graph-inputs-caucus-followup-20261022-v2-work"
    ) / uuid4().hex
    root.mkdir(parents=True)
    baseline = root / "v1"
    baseline.mkdir()
    row = {
        "record_id": "caucus:KY:R", "state": "KY", "party": "R",
        "institution_type": "legislative_caucus", "institution": "Kentucky Senate Republicans",
        "extracted_text": None,
        "retained_record": {"year": 2024, "urls": [followup.URL]},
    }
    jsonl(baseline / "retained_evidence_views.jsonl", [row])
    jsonl(baseline / "caucus_observations.jsonl", [row])
    (baseline / "producer.py").write_text("# immutable v1 fixture\n")
    ledgers = root / "retained.jsonl"
    jsonl(ledgers, [])
    source = root / "platform_source_manifest.json"

    def reseal():
        dump(source, {"inputs": [followup._pin(ledgers)]})
        dump(baseline / "manifest.json", {
            "files": {
                p.name: {k: v for k, v in followup._pin(p).items() if k != "path"}
                for p in baseline.iterdir() if p.name != "manifest.json"
            },
            "inputs": [followup._pin(source)],
        })

    reseal()
    monkeypatch.setattr(native, "url_is_fetchable", lambda _: None)
    yield {
        "root": root, "baseline": baseline, "source": source,
        "ledgers": ledgers, "reseal": reseal,
    }
    shutil.rmtree(root)


def run(packet, responses):
    session = Session(responses)

    def factory(root, authorization):
        return native.Capture(root, authorization, session=session, sleeper=lambda _: None)

    report = followup.run(
        packet["root"] / "operation", packet["root"] / "v2",
        baseline=packet["baseline"], source_manifest=packet["source"],
        global_provenance=None, capture_factory=factory,
    )
    return report, session


def html(body=PAGE, status=200, **headers):
    return status, body, {"Content-Type": "text/html; charset=utf-8", **headers}


def robots(status=200, body=ROBOTS):
    return status, body, {"Content-Type": "text/plain"}


def test_complete_native_text_spans_links_closure_and_immutable_baseline(packet):
    before = followup._pin(packet["baseline"] / "producer.py")
    report, session = run(packet, [robots(), html()])
    assert report["new_physical_http_used"] == 2
    assert report["new_payload_bytes"] == len(ROBOTS) + len(PAGE)
    assert report["capture_closed"] and report["dispatchable_remaining"] == 0
    assert report["historical_physical_http_used"] is None
    assert before == followup._pin(packet["baseline"] / "producer.py")
    assert [r["url"] for r in session.requests] == [followup.ROBOTS, followup.URL]
    out = packet["root"] / "v2"
    row = json.loads((out / "caucus_native_observations.jsonl").read_text())
    text = row["complete_received_visible_text"]
    assert row["institution_type"] == "legislative_caucus"
    assert row["n_native_24rs_bill_link_occurrences"] == 2
    assert row["source_reported_adoption_date"] is None
    assert row["cycle_applicability"] == "unresolved"
    assert all(row[key] is False for key in followup.FLAGS)
    for span in row["native_year_literals"]:
        assert text[span["start"]:span["end"]] == span["exact_text"]
    links = json.loads((out / "native_links.json").read_text())
    source = (out / "source.html").read_text()
    for link in links:
        span = link["href_source_span"]
        assert source[span["start"]:span["end"]] == span["exact_text"]
    assert not list(out.rglob("caucus_priorities.parquet"))
    assert row["source_sha256"] == hashlib.sha256(PAGE).hexdigest()


def test_generic_challenge_literal_stop_remains_closed_despite_offline_text(packet):
    body = PAGE.replace(b"</body>", b'<script>var captcha = "widget";</script></body>')
    report, session = run(packet, [robots(), html(body)])
    assert len(session.requests) == 2
    assert report["capture_binding_restriction"] == "publisher challenge/block response"
    assert report["capture_closed"] and report["dispatchable_remaining"] == 0
    assert report["generic_challenge_stop_does_not_prove_waf"] is True
    assert report["n_complete_received_native_texts"] == 1
    assert (packet["root"] / "v2/source_text.txt").exists()


def test_later_page_is_ancillary_and_24rs_urls_do_not_supply_2024(packet):
    report, _ = run(packet, [robots(), html(PAGE.replace(b"2024", b"2025"))])
    assert report["n_complete_received_native_texts"] == 1
    row = json.loads((packet["root"] / "v2/caucus_native_observations.jsonl").read_text())
    assert row["native_printed_years_not_interpreted_as_adoption"] == [2025]
    assert row["cycle_relation"] == "ancillary_undated_or_later_not_target_cycle_recovery"
    assert row["registry_metadata_year_hint_not_source_date"] == 2024


@pytest.mark.parametrize("fault", ["robots403", "challenge_page", "tls", "cross_origin"])
def test_restrictions_never_retry_or_fetch_substitutes(packet, fault):
    if fault == "robots403":
        responses = [robots(403)]
    elif fault == "challenge_page":
        responses = [robots(), html(b"<html>Verify you are human: captcha</html>")]
    elif fault == "tls":
        responses = [robots(), requests.exceptions.SSLError("certificate verification failed")]
    else:
        responses = [robots(), html(b"", 301, Location="https://www.kysenaterepublicans.com/")]
    report, session = run(packet, responses)
    assert len(session.requests) == (1 if fault == "robots403" else 2)
    assert report["capture_closed"] and report["dispatchable_remaining"] == 0
    assert report["n_complete_received_native_texts"] == 0
    assert not (packet["root"] / "v2").exists()
    for request in session.requests:
        assert followup._same_origin(request["url"])


def test_same_origin_redirect_is_an_explicit_extra_exchange(packet):
    report, session = run(packet, [robots(), html(b"", 301, Location="/new-page-34/"), html()])
    assert report["new_physical_http_used"] == 3
    assert session.requests[-1]["url"] == followup.URL + "/"


@pytest.mark.parametrize("kind", ["http403", "robots", "stop"])
def test_preflight_binding_restriction_prevents_all_new_dispatch(packet, kind):
    if kind == "http403":
        rows = [{"url": followup.URL, "http_status": 403, "error": "publisher refused"}]
    elif kind == "robots":
        rows = [{"url": followup.ROBOTS, "status": 200,
                 "extracted_text": "User-agent: *\nDisallow: /\n"}]
    else:
        rows = [
            {"event": "start", "state": "KY", "url": followup.URL},
            {"event": "stop", "state": "KY", "reason": "publisher challenge/block response"},
        ]
    jsonl(packet["ledgers"], rows)
    packet["reseal"]()
    report, session = run(packet, [])
    assert report["binding_restrictions_before_dispatch"]
    assert session.requests == []
    assert report["new_physical_http_used"] == 0
    assert report["historical_physical_http_used"] is None
    assert report["capture_closed"] and report["dispatchable_remaining"] == 0
    assert not (packet["root"] / "v2").exists()


def test_no_more_than_fifteen_physical_exchanges_even_for_redirect_chain(packet):
    report, session = run(packet, [
        robots(), *(html(b"", 302, Location=f"/redirect-{i}") for i in range(14))
    ])
    assert len(session.requests) == report["new_physical_http_used"] == 15
    assert report["closure_reason"] == "new physical exchange budget exhausted"
    assert report["capture_closed"] and report["dispatchable_remaining"] == 0


def test_native_parser_ignores_script_years_and_preserves_text_separator():
    source = '<p>Senate priorities\u2028remain undated.</p><script>var year=2024;</script>'
    page = followup.NativePage(source)
    assert "\u2028" in page.text
    assert followup._literal_spans(page.text) == []

"""Archived fixture parsing and hard collection gates, not mocked source-recovery credit."""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
import yaml

from state_politics.bills import native_inventory as inventory

ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / "conf/native_inventory_sources.yml").read_text())


def event():
    return {
        "id": "NH-10",
        "state": "NH",
        "url": "https://www.gc.nh.gov/bill_status/legacy/bs2016/results.aspx",
        "sha256": "fixture",
        "complete_body": True,
    }


def test_archived_article_preserves_identity_type_every_field_and_literal_dates():
    article = """<article class="bill" aria-labelledby="bill-2023-19">
<h3>CACR001-FN</h3><p class="session-year">Session Year 2023</p>
<div class="bill-detail"><p><strong>Title:</strong> A &amp; B\u2028complete</p>
<dl><dt>G-Status:</dt><dd>RETAINED</dd>
<dt>Next/Last Hearing:</dt><dd> 01/02/2024 at 10:00 AM </dd>
<dt>Unanticipated:</dt><dd>preserve entire extra column</dd></dl></div>
<a href="billText.aspx?sy=2023&amp;id=19&amp;v=current">Current PDF</a>
<a href="billText.aspx?sy=2023&amp;id=19">Unversioned</a></article>"""
    body = f"<html><p>Bills Found :&#xA0;1</p>{article}</html>".encode()
    parsed = inventory.parse_page(
        body, event(), CONFIG["adapters"]["bill_articles"], CONFIG["pages"][-2]
    )
    record = parsed["records"][0]
    assert record["source_record_html_unchanged"] == article
    start, end = record["source_record_character_span"]
    assert body.decode()[start:end] == article
    assert record["identifier_literal"] == "CACR001-FN"
    assert record["identifier"] == "CACR 1"
    assert record["identifier_suffix_literal"] == "-FN"
    assert record["measure_type"] == "CACR"
    assert record["is_bill"] is False
    assert record["source_fields"]["title"] == ["Title: A & B\u2028complete"]
    assert record["source_definition_fields"][-1]["literal"] == "preserve entire extra column"
    assert record["literal_date_fields"][0]["literal"] == " 01/02/2024 at 10:00 AM "
    assert record["introduction_date_literal"] is None
    assert record["filing_date_literal"] is None
    assert parsed["evidence"]["publisher_query_complete"] is True
    assert parsed["links"][0]["version_role"] == "explicit_current_not_original"
    assert parsed["links"][1]["version_role"] == "publisher_link_version_unverified"
    assert not any(link["original_version_certified"] for link in parsed["links"])
    with pytest.raises(ValueError, match="publisher count"):
        inventory.parse_page(
            body.replace(b"Bills Found", b"Count changed"),
            event(),
            CONFIG["adapters"]["bill_articles"],
            CONFIG["pages"][-2],
        )


def test_archived_pagination_requires_exact_all_pages_next_link_and_terminal():
    def page(number, total=2):
        return {
            "page": number,
            "pages": total,
            "page_body_complete": True,
            "terminal_document_closed": True,
            "request_urls": [f"https://publisher.test/?page={number}"],
            "pagination_links": [{"url": f"https://publisher.test/?page={number + 1}"}],
        }

    assert inventory.pagination_complete([page(1), page(2)])
    assert not inventory.pagination_complete([page(1)])
    assert not inventory.pagination_complete([page(1, 3), page(3, 3)])
    assert not inventory.pagination_complete([page(1), page(1)])
    changed = page(2)
    changed["terminal_document_closed"] = False
    assert not inventory.pagination_complete([page(1), changed])
    changed = page(1)
    changed["pagination_links"] = [{"url": "https://publisher.test/?page=3"}]
    assert not inventory.pagination_complete([changed, page(2)])


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        status, body, headers = result
        response = requests.Response()
        response.status_code = status
        response.raw = SimpleNamespace(
            headers=headers,
            stream=lambda *_args, **_kwargs: iter([body]),
            close=lambda: None,
        )
        return response


def capture(tmp_path, monkeypatch, responses, cap=15, restriction=None):
    monkeypatch.setattr(inventory, "url_is_fetchable", lambda url: None)
    transport = Transport(responses)
    authorization = {
        "states": {
            "AR": {
                "requests_authorized": True,
                "binding_restriction": restriction,
                "new_exchange_cap": cap,
                "origins": ["https://publisher.test"],
            }
        }
    }
    return inventory.Capture(
        tmp_path, authorization, session=transport, sleeper=lambda _: None
    ), transport


ROBOTS = (200, b"\xef\xbb\xbfUser-agent: *\nAllow: /\nCrawl-delay: 11\n", {})


def test_physical_redirects_manual_budget_and_literal_post_count(tmp_path, monkeypatch):
    collector, transport = capture(
        tmp_path,
        monkeypatch,
        [ROBOTS, (301, b"complete redirect body", {"Location": "/next"})],
        cap=2,
    )
    waits = []
    collector.sleep = waits.append
    collector.clock = lambda: 0
    collector.get("AR", "https://publisher.test/robots.txt", purpose="robots")
    response = collector.get(
        "AR", "https://publisher.test/census", purpose="fixture", form={"year": "2023"}
    )
    assert response["status"] == 301
    assert (tmp_path / response["body"]).read_bytes() == b"complete redirect body"
    assert collector.used("AR") == 2
    assert len(transport.calls) == 2
    assert transport.calls[-1][0] == "POST"
    assert transport.calls[-1][2]["allow_redirects"] is False
    assert transport.calls[-1][2]["data"] == {"year": "2023"}
    assert waits == [11]
    with pytest.raises(inventory.Refusal, match="budget exhausted"):
        collector.get("AR", "https://publisher.test/next", purpose="manual redirect")
    assert len(transport.calls) == 2
    assert collector.seal()["states"]["AR"]["new_physical_http_remaining"] == 0


def test_requests_session_does_not_preconsume_redirect_entities():
    transport = Transport([(301, b"redirect entity survives Session.send", {"Location": "/next"})])

    class Adapter(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            response = transport.request(request.method, request.url, **kwargs)
            response.url = request.url
            response.request = request
            response.raw._original_response = None
            return response

        def close(self):
            pass

    session = inventory._NoRedirectSession()
    session.mount("https://", Adapter())
    response = session.get("https://publisher.test/start", stream=True, allow_redirects=False)
    assert response.status_code == 301
    assert response._content_consumed is False
    assert list(response.raw.stream()) == [b"redirect entity survives Session.send"]
    assert len(transport.calls) == 1


def test_short_redirect_body_is_retained_but_never_marked_complete(tmp_path, monkeypatch):
    collector, transport = capture(
        tmp_path,
        monkeypatch,
        [ROBOTS, (301, b"partial", {"Location": "/next", "Content-Length": "161"})],
    )
    collector.get("AR", "https://publisher.test/robots.txt", purpose="robots")
    with pytest.raises(inventory.Refusal, match="Content-Length mismatch"):
        collector.get("AR", "https://publisher.test/start", purpose="short redirect")
    result = [e for e in collector.events if e["event"] == "result"][-1]
    assert result["complete_body"] is False
    assert (tmp_path / result["body"]).read_bytes() == b"partial"
    assert collector.used("AR") == len(transport.calls) == 2
    with pytest.raises(inventory.Refusal, match="already stopped"):
        collector.get("AR", "https://publisher.test/next", purpose="no retry")


def test_robots_delay_refusal_and_persistent_stop(tmp_path, monkeypatch):
    collector, transport = capture(
        tmp_path, monkeypatch, [(200, b"User-agent: *\nDisallow: /private\n", {})]
    )
    collector.get("AR", "https://publisher.test/robots.txt", purpose="robots")
    with pytest.raises(inventory.Refusal, match="robots disallows"):
        collector.get("AR", "https://publisher.test/private", purpose="refused")
    with pytest.raises(inventory.Refusal, match="already stopped"):
        collector.get("AR", "https://publisher.test/other", purpose="no workaround")
    assert len(transport.calls) == collector.used("AR") == 1


@pytest.mark.parametrize(
    "restriction", ["exhausted binding historical budget", "publisher authentication restriction"]
)
def test_inherited_restrictions_send_nothing(tmp_path, monkeypatch, restriction):
    collector, transport = capture(tmp_path, monkeypatch, [], restriction=restriction)
    with pytest.raises(inventory.Refusal, match=restriction):
        collector.get("AR", "https://publisher.test/robots.txt", purpose="refused")
    assert collector.used("AR") == 0
    assert transport.calls == []


@pytest.mark.parametrize(
    "failure",
    [
        (429, b"rate-limit original evidence", {}),
        (302, b"authentication redirect", {"Location": "/login?return=census"}),
        requests.ConnectionError("fixture failure"),
    ],
)
def test_block_or_transport_failure_consumes_one_exchange_without_retry(
    tmp_path, monkeypatch, failure
):
    collector, transport = capture(tmp_path, monkeypatch, [ROBOTS, failure])
    collector.get("AR", "https://publisher.test/robots.txt", purpose="robots")
    with pytest.raises(inventory.Refusal):
        collector.get("AR", "https://publisher.test/census", purpose="failure")
    assert collector.used("AR") == len(transport.calls) == 2
    with pytest.raises(inventory.Refusal, match="already stopped"):
        collector.get("AR", "https://publisher.test/alternate", purpose="refused")
    results = [e for e in collector.events if e["event"] == "result"]
    assert (tmp_path / results[-1]["body"]).exists()


def test_bound_failure_keeps_partial_bytes_and_refuses_resume(tmp_path, monkeypatch):
    collector, transport = capture(tmp_path, monkeypatch, [ROBOTS, (200, b"0123456789", {})])
    collector.get("AR", "https://publisher.test/robots.txt", purpose="robots")
    monkeypatch.setattr(inventory, "MAX_RESPONSE_BYTES", 6)
    with pytest.raises(inventory.Refusal, match="payload bound"):
        collector.get("AR", "https://publisher.test/bulk", purpose="bound")
    result = [e for e in collector.events if e["event"] == "result"][-1]
    assert (tmp_path / result["body"]).read_bytes() == b"012345"
    assert result["complete_body"] is False
    assert len(transport.calls) == 2


def test_retained_actual_archive_counts_and_exact_source_record_spans_offline():
    raw = ROOT / "data/raw/native-inventory-ar-id-nh-v1"
    if not raw.exists():
        pytest.skip("Actual ignored source archive is not installed; fixtures are not recovery")
    results = {
        row["id"]: row
        for row in map(json.loads, (raw / "exchanges.jsonl").read_text().splitlines())
        if row["event"] == "result"
    }
    counts = []
    for page in CONFIG["pages"]:
        response = results[page["exchange"]]
        body = (raw / response["body"]).read_bytes()
        assert inventory.sha256_file(raw / response["body"]) == response["sha256"]
        parsed = inventory.parse_page(body, response, CONFIG["adapters"][page["adapter"]], page)
        counts.append(len(parsed["records"]))
        assert len({r["native_id"] for r in parsed["records"]}) == len(parsed["records"])
        for record in parsed["records"]:
            start, end = record["source_record_character_span"]
            assert body.decode()[start:end] == record["source_record_html_unchanged"]
            assert record["introduction_date_literal"] is None
            assert record["filing_date_literal"] is None
        evidence = parsed["evidence"]
        if response["id"] == "AR-06":
            assert evidence["pages"] == 30
            assert evidence["publisher_query_complete"] is False
        else:
            assert evidence["publisher_query_complete"] is True
    assert counts == [20, 2, 6, 2, 3, 5, 1, 675, 1321]
    modified = copy.deepcopy(CONFIG["pages"][-1])
    modified["session"] = "2023"
    with pytest.raises(ValueError, match="record session"):
        inventory.parse_page(
            (raw / results["NH-11"]["body"]).read_bytes(),
            results["NH-11"],
            CONFIG["adapters"]["bill_articles"],
            modified,
        )


def test_fragment_keeps_hidden_key_starred_identity_and_real_finite_range():
    config = yaml.safe_load((ROOT / "conf/native_inventory_remaining.yml").read_text())
    adapter = config["adapters"]["nevada_list_fragment"]
    source = """<div id="billTab"><form><div id="content"><p>1-1 of 2 results</p>
<input name="ListItems[0].ContentKey" value="777" />
<div class="row"><div class="col"><a href="/Bill/777/Overview">AB65*</a></div>
<div class="col">Every title and unanticipated column</div></div>
<script>terminal()</script></div></form></div>
"""
    response = {
        **event(),
        "id": "NV-04",
        "state": "NV",
        "url": "https://publisher.test/BillsTab?Page=1&Filters.PageSize=1",
    }
    page = config["pages"][3]
    parsed = inventory.parse_page(source.encode(), response, adapter, page)
    record = parsed["records"][0]
    assert record["publisher_record_key_literal"] == "777"
    assert record["identifier_literal"] == "AB65*"
    assert record["identifier_suffix_literal"] == "*"
    assert record["native_id"].endswith(":AB 65*")
    assert record["canonical_candidate_identifier"] == "AB 65*"
    start, end = record["source_record_character_span"]
    assert source[start:end] == record["source_record_html_unchanged"]
    assert record["source_record_html_unchanged"].startswith("<input ")
    assert "Every title and unanticipated column" in record["source_fields"]["all_source_columns"]
    assert parsed["links"][0]["absolute_url"] == "https://publisher.test/Bill/777/Overview"
    assert parsed["evidence"]["page"] == 1
    assert parsed["evidence"]["pages"] == 2
    assert parsed["evidence"]["publisher_query_complete"] is False
    full = inventory.parse_page(
        source.replace("of 2", "of 1").encode(), response, adapter, page
    )
    assert full["evidence"]["publisher_query_complete"] is True
    with pytest.raises(ValueError, match="unclosed source HTML"):
        inventory.parse_page(
            source.replace("</form></div>", "").encode(), response, adapter, page
        )
    with pytest.raises(ValueError, match="result range"):
        inventory.parse_page(
            source.replace("1-1", "1-2").encode(), response, adapter, page
        )


def test_anchor_record_keeps_its_own_link_and_literal_non_introduction_dates():
    config = yaml.safe_load((ROOT / "conf/native_inventory_remaining.yml").read_text())
    source = """<html><a class="card-link" id="3001" href="regular/bill-overview/bo3001.html">
<h4 class="bill-name">HCR 3001</h4><li class="last-action-date">20230425</li>
<p class="title">Entire resolution title</p></a></html>"""
    parsed = inventory.parse_page(
        source.encode(),
        {**event(), "id": "ND-03", "state": "ND"},
        config["adapters"]["north_dakota_regular"],
        config["pages"][1],
    )
    record = parsed["records"][0]
    assert record["is_bill"] is False
    assert record["publisher_record_key_literal"] == "3001"
    assert record["literal_date_fields"][0]["literal"] == "20230425"
    assert record["literal_date_fields"][0]["filing_or_introduction_certified"] is False
    assert record["introduction_date_literal"] is None
    assert record["filing_date_literal"] is None
    assert len(parsed["links"]) == 1
    assert parsed["links"][0]["source_href_literal"] == "regular/bill-overview/bo3001.html"


def test_directory_preserves_every_filename_column_and_span_without_original_credit():
    config = yaml.safe_load((ROOT / "conf/native_inventory_remaining.yml").read_text())
    spec = config["auxiliary_file_indexes"][0]
    source = """<html><body><pre><a href="/sessions/">[To Parent Directory]</a><br><br>
 1/3/2025  4:11 AM  1234 <A HREF="/sessions/session2024/Bills/HB1_HD1_.PDF">HB1_HD1_.PDF</A><br>
 5/27/2021  3:06 PM  168 <A HREF="/sessions/session2024/Bills/web.config">web.config</A><br>
</pre><hr></body></html>"""
    response = {**event(), "id": "HI-04", "state": "HI"}
    entries = inventory.parse_file_index(source.encode(), response, spec)
    assert [row["filename_literal"] for row in entries] == ["HB1_HD1_.PDF", "web.config"]
    assert entries[0]["filename_identity_candidate"]["suffix"] == "_HD1_"
    assert entries[1]["filename_identity_candidate"] is None
    assert entries[0]["listing_size_literal"] == "1234"
    assert entries[0]["listing_modified_literal"] == "1/3/2025  4:11 AM"
    for row in entries:
        start, end = row["source_record_character_span"]
        assert source[start:end] == row["source_record_html_unchanged"]
        assert row["introduction_date_literal"] is None
        assert row["filing_date_literal"] is None
        assert row["full_original_downloaded"] is False
        assert row["canonical_join_certified"] is False
    with pytest.raises(ValueError, match="columns"):
        inventory.parse_file_index(source.replace("1234", "unknown").encode(), response, spec)
    with pytest.raises(ValueError, match="incomplete"):
        inventory.parse_file_index(
            source.encode(), {**response, "complete_body": False}, spec
        )


def missing_robots_capture(tmp_path, monkeypatch, responses, *, proof=None, prior=0, opt_in=True):
    monkeypatch.setattr(inventory, "url_is_fetchable", lambda url: None)
    transport = Transport(responses)
    spec = {
        "requests_authorized": True,
        "binding_restriction": None,
        "new_exchange_cap": 15,
        "aggregate_exchange_cap": 15,
        "known_prior_physical_http_used": prior,
        "origins": ["https://publisher.test"],
        "unavailable_robots_policy": "allow_404_410_only" if opt_in else None,
        "retained_robots": [proof] if proof else [],
    }
    return inventory.Capture(
        tmp_path, {"states": {"AR": spec}}, session=transport, sleeper=lambda _: None
    ), transport


def retained_missing_robots_proof(tmp_path, **overrides):
    tmp_path.mkdir(parents=True, exist_ok=True)
    body = tmp_path / "retained.body"
    headers = tmp_path / "retained.headers.json"
    body.write_bytes(b"404 file not found")
    inventory.write_json(headers, [])
    return {
        "id": "AR-prior-01",
        "state": "AR",
        "url": "https://publisher.test/robots.txt",
        "at": datetime.now(UTC).isoformat(),
        "status": 404,
        "complete_body": True,
        "body": body.name,
        "headers_file": headers.name,
        "sha256": inventory.sha256_file(body),
        "headers_sha256": inventory.sha256_file(headers),
        **overrides,
    }


@pytest.mark.parametrize("status", [404, 410])
def test_absent_robots_requires_explicit_opt_in_and_still_counts_new_exchanges(
    tmp_path, monkeypatch, status
):
    absent = (status, b"file not found", {})
    default, default_transport = missing_robots_capture(
        tmp_path / "default", monkeypatch, [absent], opt_in=False
    )
    default.get("AR", "https://publisher.test/robots.txt", purpose="robots")
    with pytest.raises(inventory.Refusal, match="robots unavailable"):
        default.get("AR", "https://publisher.test/list", purpose="conservative default")
    assert len(default_transport.calls) == 1
    opted, transport = missing_robots_capture(
        tmp_path / "opted", monkeypatch, [absent, (200, b"complete census entity", {})]
    )
    opted.get("AR", "https://publisher.test/robots.txt", purpose="robots")
    opted.get("AR", "https://publisher.test/list", purpose="explicitly authorized absence policy")
    assert opted.used("AR") == len(transport.calls) == 2
    decisions = [e for e in opted.events if e["event"] == "robots_policy"]
    assert decisions[0]["status"] == status
    assert decisions[0]["retained"] is False


def test_fresh_retained_absence_reuse_does_not_reset_known_aggregate_allowance(
    tmp_path, monkeypatch
):
    proof = retained_missing_robots_proof(tmp_path)
    collector, transport = missing_robots_capture(
        tmp_path, monkeypatch, [(200, b"metadata list", {})], proof=proof, prior=14
    )
    collector.get("AR", "https://publisher.test/list", purpose="last aggregate exchange")
    assert collector.used("AR") == len(transport.calls) == 1
    assert [e for e in collector.events if e["event"] == "robots_policy"][0]["retained"] is True
    with pytest.raises(inventory.Refusal, match="aggregate"):
        collector.get("AR", "https://publisher.test/next", purpose="no reset")
    state = collector.seal()["states"]["AR"]
    assert state["known_prior_physical_http_used"] == 14
    assert state["known_aggregate_physical_http_used"] == 15
    assert state["dispatchable_remaining"] == 0


@pytest.mark.parametrize(
    "failure",
    ["401", "403", "429", "500", "redirect", "disallow", "waf", "tool_block", "stale", "hash"],
)
def test_opt_in_never_overrides_restrictions_or_invalid_retained_evidence(
    tmp_path, monkeypatch, failure
):
    proof = retained_missing_robots_proof(tmp_path)
    if failure.isdigit():
        proof["status"] = int(failure)
    elif failure == "stale":
        proof["at"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    elif failure == "redirect":
        inventory.write_json(tmp_path / proof["headers_file"], [["Location", "/login"]])
        proof["headers_sha256"] = inventory.sha256_file(tmp_path / proof["headers_file"])
    else:
        text = {
            "disallow": b"User-agent: *\nDisallow: /\n",
            "waf": b"verify you are human",
            "tool_block": b"Blocked by robots.txt",
            "hash": b"mutated original evidence",
        }[failure]
        (tmp_path / proof["body"]).write_bytes(text)
        if failure != "hash":
            proof["sha256"] = inventory.sha256_file(tmp_path / proof["body"])
    collector, transport = missing_robots_capture(tmp_path, monkeypatch, [], proof=proof)
    with pytest.raises(inventory.Refusal):
        collector.get("AR", "https://publisher.test/list", purpose="must refuse")
    assert collector.used("AR") == len(transport.calls) == 0
    with pytest.raises(inventory.Refusal, match="already stopped"):
        collector.get("AR", "https://publisher.test/other", purpose="no alternative route")


def test_new_explicit_robots_rule_takes_precedence_over_retained_404(tmp_path, monkeypatch):
    proof = retained_missing_robots_proof(tmp_path)
    collector, transport = missing_robots_capture(
        tmp_path, monkeypatch, [(200, b"User-agent: *\nDisallow: /\n", {})], proof=proof
    )
    collector.get("AR", "https://publisher.test/robots.txt", purpose="new policy")
    with pytest.raises(inventory.Refusal, match="robots disallows"):
        collector.get("AR", "https://publisher.test/list", purpose="new rule is binding")
    assert len(transport.calls) == 1


def test_paired_source_rows_require_exact_postback_chain_and_unique_complete_census():
    config = yaml.safe_load(
        (ROOT / "conf/native_inventory_missing_robots_followup.yml").read_text()
    )
    adapter = config["adapters"]["louisiana_paired_rows"]
    page = config["pages"][0]

    def parse(number):
        other = 3 - number
        source = f"""<html><span>There are 2 Instruments in this List</span>
<table class="ResultsListTable"><tr><td>
<a id="item_HyperLink1" href="BillInfo.aspx?i={number}">HB{number}</a></td></tr>
<tr><td><span id="item_LabelKWordAndSTitle">Complete subject and title {number}</span>
</td></tr></table>
<span id="DataPager1"><span>{number}</span>
<a href="javascript:__doPostBack('go{other}','')">{other}</a></span></html>"""
        result = inventory.parse_page(
            source.encode(),
            {**event(), "request_form": {"__EVENTTARGET": f"go{number}"}},
            adapter,
            page,
        )
        record = result["records"][0]
        assert record["source_fields"]["subject_and_full_title"] == [
            f"Complete subject and title {number}"
        ]
        assert record["source_record_html_unchanged"].count("<tr>") == 2
        assert record["introduction_date_literal"] is None
        changed = source.replace(
            f'<span id="item_LabelKWordAndSTitle">Complete subject and title {number}</span>',
            "changed publisher structure",
        )
        with pytest.raises(ValueError, match="summary row"):
            inventory.parse_page(changed.encode(), event(), adapter, page)
        return result["evidence"]

    pages = [parse(1), parse(2)]
    assert inventory.pagination_complete(pages)
    assert not inventory.pagination_complete(pages[:1])
    changed = copy.deepcopy(pages)
    changed[1]["request_postback_target"] = "unobserved-target"
    assert not inventory.pagination_complete(changed)
    changed = copy.deepcopy(pages)
    changed[1]["record_native_ids"] = changed[0]["record_native_ids"]
    assert not inventory.pagination_complete(changed)


def test_actual_missing_robots_followup_archive_postbacks_and_full_source_pairs_offline():
    raw = ROOT / "data/raw/native-inventory-missing-robots-followup-v1"
    if not (raw / "exchanges.jsonl").exists():
        pytest.skip("Actual ignored follow-up archive not installed; no recovery credit")
    config = yaml.safe_load(
        (ROOT / "conf/native_inventory_missing_robots_followup.yml").read_text()
    )
    events = [json.loads(line) for line in (raw / "exchanges.jsonl").read_text().splitlines()]
    results = {e["id"]: e for e in events if e["event"] == "result"}
    requests_by_id = {e["id"]: e for e in events if e["event"] == "start"}
    evidence = {}
    for page in config["pages"]:
        response = results[page["exchange"]]
        body = (raw / response["body"]).read_bytes()
        parsed = inventory.parse_page(
            body,
            {**response, "request_form": requests_by_id[response["id"]]["form"]},
            config["adapters"][page["adapter"]],
            page,
        )
        evidence[response["id"]] = parsed["evidence"]
        for row in parsed["records"]:
            assert row["source_fields"]["subject_and_full_title"]
            start, end = row["source_record_character_span"]
            assert body.decode()[start:end] == row["source_record_html_unchanged"]
            assert row["filing_date_literal"] is None
    query = [evidence[e] for e in config["paginated_queries"][0]["exchanges"]]
    assert inventory.pagination_complete(query)
    assert sum(e["observed_records"] for e in query) == 661


@pytest.mark.parametrize("explicit", [False, True])
def test_larger_named_increment_needs_explicit_authority_and_preserves_prior_usage(
    tmp_path, monkeypatch, explicit
):
    monkeypatch.setattr(inventory, "url_is_fetchable", lambda url: None)
    proof = retained_missing_robots_proof(tmp_path)
    spec = {
        "requests_authorized": True,
        "new_exchange_cap": 20,
        "known_prior_physical_http_used": 15,
        "aggregate_exchange_cap": 35,
        "origins": ["https://publisher.test"],
        "unavailable_robots_policy": "allow_404_410_only",
        "retained_robots": [proof],
    }
    if explicit:
        spec["explicit_named_exchange_authorization"] = {
            "scope": "Explicit fresh named metadata increment; prior usage not reset",
            "physical_exchange_cap": 20,
        }
    limit = 20 if explicit else 15
    transport = Transport([(200, b"fixture metadata", {})] * limit)
    collector = inventory.Capture(
        tmp_path, {"states": {"AR": spec}}, session=transport, sleeper=lambda _: None
    )
    for _ in range(limit):
        collector.get("AR", "https://publisher.test/list", purpose="finite fixture query")
    with pytest.raises(inventory.Refusal, match="budget exhausted"):
        collector.get("AR", "https://publisher.test/list", purpose="one beyond new limit")
    assert collector.used("AR") == len(transport.calls) == limit
    state = collector.seal()["states"]["AR"]
    assert state["known_prior_physical_http_used"] == 15
    assert state["known_aggregate_physical_http_used"] == 15 + limit
    assert state["dispatchable_remaining"] == 0


def test_counted_single_page_and_verified_query_entry_preserve_actual_publisher_pages():
    config = yaml.safe_load((ROOT / "conf/native_inventory_la_complete.yml").read_text())
    adapter = config["adapters"]["louisiana_paired_rows"]
    page = {
        **config["pages"][0],
        "measure_type_scope": "HR",
        "query_entry_fields": {"type": "HR-2", "start": "1", "stop": "2"},
    }

    def parse(number, *, single=False, entry=False, mismatch=False):
        pager = "" if single else (
            f'<span>{number}</span><a href="javascript:__doPostBack(\'go{3-number}\',\'\')">'
            f"{3-number}</a>"
        )
        count = 1 if single else 2
        body = f"""<html><p>There are {count} Instruments in this List</p>
<table class="ResultsListTable"><tr><td><a id="bill_HyperLink1">HR{number}</a></td></tr>
<tr><td><span id="bill_LabelKWordAndSTitle">Full subject/title</span></td></tr></table>
<span id="DataPager1">{pager}</span></html>""".encode()
        form = {"__EVENTTARGET": f"go{number}"}
        if entry:
            form = {
                "ctl00$ctl00$PageBody$PageContent$btnSearchByInstRange": "Search",
                **page["query_entry_fields"],
            }
        if mismatch:
            form["type"] = "wrong-query"
        return inventory.parse_page(body, {**event(), "request_form": form}, adapter, page)

    assert parse(1, single=True)["evidence"]["publisher_query_complete"] is True
    first = parse(1)["evidence"]
    entered_second = parse(2, entry=True)["evidence"]
    assert entered_second["verified_finite_query_entry_request"] is True
    assert inventory.pagination_complete([first, entered_second])
    wrong = parse(2, entry=True, mismatch=True)["evidence"]
    assert wrong["verified_finite_query_entry_request"] is False
    assert not inventory.pagination_complete([first, wrong])


def test_actual_complete_louisiana_scopes_and_retained_hb_pages_are_not_new_requests():
    raw = ROOT / "data/raw/native-inventory-la-ri-completion-v1"
    if not (raw / "publisher_scope_inventory.json").exists():
        pytest.skip("Actual ignored completion archive not installed; no recovery credit")
    config = yaml.safe_load((ROOT / "conf/native_inventory_la_complete.yml").read_text())
    events = [json.loads(line) for line in (raw / "exchanges.jsonl").read_text().splitlines()]
    results = {
        e["id"]: e for e in events if e["event"] in {"result", "retained_result"}
    }
    requests_by_id = {e["id"]: e for e in events if e["event"] == "start"}
    pages = {}
    all_records = []
    for spec in config["pages"]:
        response = results[spec["exchange"]]
        request = (
            response["retained_request"]
            if response["event"] == "retained_result"
            else requests_by_id[response["id"]]
        )
        body = (raw / response["body"]).read_bytes()
        parsed = inventory.parse_page(
            body,
            {**response, "request_form": request["form"]},
            config["adapters"][spec["adapter"]],
            spec,
        )
        pages[response["id"]] = parsed["evidence"]
        all_records.extend(parsed["records"])
        for row in parsed["records"]:
            start, end = row["source_record_character_span"]
            assert body.decode()[start:end] == row["source_record_html_unchanged"]
            assert row["filing_date_literal"] is None
            assert row["introduction_date_literal"] is None
            assert (
                row["publisher_query_context"]["measure_type_scope"] == spec["measure_type_scope"]
            )
    assert all(
        inventory.pagination_complete([pages[e] for e in query["exchanges"]])
        for query in config["paginated_queries"]
    )
    reused = [e for e in results.values() if e["event"] == "retained_result"]
    assert len(reused) == 7
    assert all(e["id"] not in requests_by_id for e in reused)
    assert len(all_records) == 5300
    assert len({r["native_id"] for r in all_records}) == 3996

"""Tests for 2018-present platform discovery.

The URLs below are all real, taken from live Wayback CDX results for state party domains.
Two of them encode bugs that produced confidently wrong results and must not regress:
descriptive document filenames being scored as news noise, and Cloudflare's bot-check
endpoint crowding real documents out of the CDX result window.
"""

from __future__ import annotations

import json

import pytest

from state_politics.platforms.discover import (
    DISCOVERY_TERMS,
    STRONG_SCORE,
    Candidate,
    discover_for_org,
    is_excluded,
    normalize_url,
    score_candidate,
    wayback_candidates,
    write_candidates,
)


class StubResponse:
    def __init__(self, status_code: int, content: bytes = b"", url: str = "https://x.test/"):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": "application/json"}
        self.url = url


@pytest.mark.parametrize(
    "url",
    [
        "https://idahodems.org/wp-content/uploads/2024/06/2024-Idaho-Democratic-Party-Platform.pdf",
        "https://idahodems.org/2014-idaho-democratic-party-platform/",
        "http://www.dfl.org/wp-content/uploads/2018/09/DFL-Ongoing-Platform.pdf",
        "https://wisdems.org/wp-content/uploads/2021/04/DPW-2013-Resolutions.pdf",
        "https://texasgop.org/2022platform/",
        "https://www.iowagop.org/about/platform/",
        "https://texasgop.org/2024-platform-and-legislative-priorities/",
    ],
)
def test_real_platform_documents_score_as_strong(url):
    """Descriptive names like '2024-Idaho-Democratic-Party-Platform' are what real docs use.

    An earlier hyphen-count penalty scored exactly those zero while passing terse blog slugs.
    """
    score, _ = score_candidate(url, "application/pdf" if url.endswith(".pdf") else None)
    assert score >= STRONG_SCORE, f"{url} scored {score}"


@pytest.mark.parametrize(
    "url",
    [
        "https://idahodems.org/a-message-from-the-chair-the-platform-purity-the-gop-demands-would-mean-utter-chaos/",
        "https://www.iowagop.org/icymi_dem_priorities_are_already_law_thank",
        "https://dfl.org/press-release/dfl-chairman-statement-on-supreme-court-upholding-governor",
    ],
)
def test_news_posts_do_not_score_as_documents(url):
    score, _ = score_candidate(url)
    assert score < STRONG_SCORE, f"{url} scored {score}"


@pytest.mark.parametrize(
    "url",
    [
        "https://dfl.org/cdn-cgi/challenge-platform/h/b/cv/result/74050db2cf4a7db9",
        "https://texasgop.org/2022platform/embed/",
        "https://texasgop.org/wp-json/oembed/1.0/embed?url=x",
        "https://idahodems.org/about/platform/feed/",
        "https://example.org/tag/platform/",
        "https://example.org/assets/platform.css",
    ],
)
def test_known_noise_is_excluded(url):
    assert is_excluded(url)


def test_normalize_url_collapses_archive_and_www_and_index():
    canonical = "texasgop.org/2022platform"
    for variant in (
        "https://texasgop.org/2022platform/",
        "https://www.texasgop.org/2022platform",
        "https://archive.texasgop.org/2022platform/index.html",
    ):
        assert normalize_url(variant) == canonical


def _cdx_body(rows):
    return json.dumps([["timestamp", "original", "mimetype"], *rows]).encode()


def test_wayback_candidates_deduplicates_equivalent_urls():
    rows = [
        ["20220710092122", "https://texasgop.org/2022platform/", "text/html"],
        ["20230321213140", "https://archive.texasgop.org/2022platform/index.html", "text/html"],
        ["20240608014532", "https://texasgop.org/2024-platform-and-legislative-priorities/",
         "text/html"],
    ]
    found, error = wayback_candidates(
        "texasgop.org", state="TX", party="R",
        transport=lambda url, *, timeout, headers: StubResponse(200, _cdx_body(rows)),
    )
    assert error is None
    assert len(found) == 2


def test_cdx_query_excludes_cloudflare_server_side():
    """The bug that made the Minnesota DFL look platform-less.

    /cdn-cgi/challenge-platform/ contains the discovery term, so on a Cloudflare-fronted site
    those URLs filled every returned row and pushed the real documents out of the window.
    Excluding them only on the client yielded a confident, wrong "no platform found".
    """
    captured = {}

    def transport(url, *, timeout, headers):
        captured["url"] = url
        return StubResponse(200, _cdx_body([]))

    wayback_candidates("dfl.org", state="MN", party="D", transport=transport)
    assert "cdn-cgi" in captured["url"]
    assert "%21original" in captured["url"] or "!original" in captured["url"]


def test_wayback_candidates_handles_a_failed_query():
    found, error = wayback_candidates(
        "example.org", state="XX", party="D",
        transport=lambda url, *, timeout, headers: StubResponse(503),
        sleep=lambda _: None,
    )
    assert found == []
    # A failed query must be reported, not silently look like "nothing published".
    assert error is not None and "failed" in error


def test_wayback_candidates_handles_malformed_json():
    found, error = wayback_candidates(
        "example.org", state="XX", party="D",
        transport=lambda url, *, timeout, headers: StubResponse(200, b"not json"),
    )
    assert found == []
    assert error is not None


def test_year_hint_prefers_the_url_over_the_capture_date():
    """A 2022 platform captured in 2023 is still the 2022 platform."""
    rows = [["20230321213140", "https://texasgop.org/2022platform/", "text/html"]]
    found, _ = wayback_candidates(
        "texasgop.org", state="TX", party="R",
        transport=lambda url, *, timeout, headers: StubResponse(200, _cdx_body(rows)),
    )
    assert found[0].year_hint == 2022


def test_year_hint_falls_back_to_the_capture_date():
    rows = [["20210517044815", "https://dfl.org/about/platform/", "text/html"]]
    found, _ = wayback_candidates(
        "dfl.org", state="MN", party="D",
        transport=lambda url, *, timeout, headers: StubResponse(200, _cdx_body(rows)),
    )
    assert found[0].year_hint == 2021


def test_discover_for_org_without_a_website_reports_why():
    outcome = discover_for_org({"state": "MD", "party": "D", "website": None})
    assert outcome.candidates == []
    assert outcome.searched is False
    assert "no website" in outcome.wayback_error


def test_a_failed_search_is_not_reported_as_an_empty_result():
    """Four organizations were wrongly recorded as platform-less when CDX errored out."""
    outcome = discover_for_org(
        {"state": "MN", "party": "D", "website": "https://dfl.org/"},
        include_live=False,
        transport=lambda url, *, timeout, headers: StubResponse(504),
        sleep=lambda _: None,
    )
    assert outcome.candidates == []
    assert outcome.searched is False          # <- the distinction that matters
    assert outcome.wayback_error is not None


def test_a_successful_search_with_no_hits_is_marked_searched():
    outcome = discover_for_org(
        {"state": "MD", "party": "R", "website": "https://mdgop.org/"},
        include_live=False,
        transport=lambda url, *, timeout, headers: StubResponse(200, _cdx_body([])),
    )
    assert outcome.candidates == []
    assert outcome.searched is True
    assert outcome.wayback_error is None


def test_write_candidates_keeps_rejected_ones(tmp_path):
    """A 'no platform found' conclusion must be auditable against what was rejected."""
    candidates = [
        Candidate(state="TX", party="R", url="https://texasgop.org/2022platform/",
                  source="wayback", score=7),
        Candidate(state="TX", party="R", url="https://texasgop.org/some-news-post/",
                  source="wayback", score=-4, reasons=["slug reads like a news headline"]),
    ]
    path = write_candidates(candidates, tmp_path / "candidates.jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert min(r["score"] for r in rows) == -4


def test_discovery_terms_are_lowercase_and_nonempty():
    assert DISCOVERY_TERMS
    assert all(term == term.lower() and term.isalpha() for term in DISCOVERY_TERMS)

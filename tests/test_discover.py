"""Tests for 2018-present platform discovery.

The URLs below are all real, taken from live Wayback CDX results for state party domains.
Two of them encode bugs that produced confidently wrong results and must not regress:
descriptive document filenames being scored as news noise, and Cloudflare's bot-check
endpoint crowding real documents out of the CDX result window.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from state_politics.platforms.discover import (
    DISCOVERY_TERMS,
    STRONG_SCORE,
    Candidate,
    discover_for_org,
    homepage_candidates,
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


def test_homepage_retains_officially_labelled_opaque_pdf_with_evidence():
    homepage = "https://example.org/"
    body = b'''<a href="/_files/ugd/061e99_153b98fadd5d43039829c3ce89c47905.pdf?x=1&amp;y=2"
               ><span>PARTY</span> PLATFORM</a>
               <a href="https://elsewhere.org/opaque.pdf">Party Platform</a>
               <a href="/unrelated.pdf">Download</a>
               <a href="/news">Party Platform debate</a>'''
    candidates, error = homepage_candidates(
        homepage, state="TX", party="D",
        transport=lambda url, **kwargs: StubResponse(200, body, homepage),
    )
    assert error is None
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.url == (
        "https://example.org/_files/ugd/061e99_153b98fadd5d43039829c3ce89c47905.pdf?x=1&y=2"
    )
    assert candidate.score >= STRONG_SCORE
    assert candidate.link_text == "PARTY PLATFORM"
    assert candidate.link_source_url == homepage
    assert candidate.link_source_sha256 == sha256(body).hexdigest()
    assert candidate.year_hint is None


def test_homepage_retains_distinct_replayable_bodies(tmp_path):
    from state_politics.provenance import ProvenanceLog

    log = ProvenanceLog(tmp_path / "provenance.jsonl")
    bodies = [
        b'<a href="/platform.pdf">Party platform</a>',
        b'<a href="/2026-platform.pdf">2026 platform</a>',
    ]
    for body in bodies:
        candidates, error = homepage_candidates(
            "https://example.org/", state="TX", party="D", log=log,
            raw_dir=tmp_path / "raw",
            transport=lambda url, body=body, **kwargs: StubResponse(200, body),
        )
        assert error is None
        assert candidates[0].link_source_sha256 == sha256(body).hexdigest()
    records = list(log)
    assert len(records) == 2
    assert records[0].stored_path != records[1].stored_path
    for body, record in zip(bodies, records, strict=True):
        assert Path(record.stored_path).read_bytes() == body
        assert record.content_sha256 == sha256(body).hexdigest()


def test_homepage_retains_opaque_embedded_drive_reference_without_certifying_it():
    homepage = "https://example.org/platform"
    viewer = "https://drive.google.com/file/d/CaseSensitive_FileID/preview"
    body = f'''<h2>Our Core Values</h2><iframe src="{viewer}"></iframe>
        <iframe src="https://video.example.org/platform"></iframe>
        <iframe src="https://drive.google.com.evil.test/file/d/Fake/preview"></iframe>
        <a href="https://elsewhere.org/platform.pdf">Party platform</a>'''.encode()
    requests = []

    def transport(url, **kwargs):
        requests.append(url)
        return StubResponse(200, body, homepage)

    candidates, error = homepage_candidates(
        homepage, state="NM", party="D", transport=transport,
    )
    assert error is None
    assert requests == [homepage]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.url == viewer
    assert candidate.link_tag == "iframe"
    assert candidate.link_source_url == homepage
    assert candidate.link_source_sha256 == sha256(body).hexdigest()
    assert candidate.score < STRONG_SCORE
    assert candidate.mimetype is None
    assert "embedded document reference: iframe[src]" in candidate.reasons


@pytest.mark.parametrize(
    "markup,tag,mimetype",
    [
        ('<iframe src="/opaque.pdf" title="Party Platform"></iframe>', "iframe", None),
        ('<embed src="https://cdn.example.net/opaque.pdf" title="Party Platform">',
         "embed", None),
        ('<object data="https://cdn.example.net/opaque" type="application/pdf" '
         'aria-label="Party Platform"></object>', "object", "application/pdf"),
    ],
)
def test_homepage_retains_labelled_embedded_pdfs(markup, tag, mimetype):
    homepage = "https://example.org/"
    candidates, error = homepage_candidates(
        homepage, state="TX", party="D",
        transport=lambda url, **kwargs: StubResponse(200, markup.encode(), homepage),
    )
    assert error is None
    assert len(candidates) == 1
    assert candidates[0].link_tag == tag
    assert candidates[0].mimetype == mimetype
    assert candidates[0].score >= STRONG_SCORE
    assert candidates[0].link_text == "Party Platform"


def test_drive_file_normalization_preserves_case_sensitive_document_identity():
    assert normalize_url("https://drive.google.com/file/d/FileA/preview") != normalize_url(
        "https://drive.google.com/file/d/Filea/preview"
    )


def test_homepage_retains_linked_drive_file_but_not_unrelated_external_anchors():
    homepage = "https://example.org/platform"
    viewer = "https://drive.google.com/file/d/CaseSensitive_Platform/view?usp=sharing"
    body = f'''<a href="{viewer}">2025 Party Platform</a>
        <a href="https://drive.google.com.evil.test/file/d/Fake/view">Party Platform</a>
        <a href="https://drive.google.com/drive/folders/FolderID">Platform</a>
        <a href="https://elsewhere.org/platform.pdf">Party Platform</a>'''.encode()
    requests = []

    def transport(url, **kwargs):
        requests.append(url)
        return StubResponse(200, body, homepage)

    candidates, error = homepage_candidates(
        homepage, state="MA", party="D", transport=transport,
    )
    assert error is None
    assert requests == [homepage]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.url == viewer
    assert candidate.link_tag == "a"
    assert candidate.link_text == "2025 Party Platform"
    assert candidate.link_source_sha256 == sha256(body).hexdigest()
    assert candidate.score < STRONG_SCORE


@pytest.mark.parametrize("secondary", [False, True])
def test_homepage_does_not_promote_fragment_only_navigation_to_documents(secondary):
    homepage = "https://example.org/platform/"
    body = b'''<a href="#content">Skip to content</a>
        <a href="#elementor-action:popup:open">Open menu</a>
        <a href="/platform-2024.pdf">Party platform</a>'''
    candidates, error = homepage_candidates(
        homepage, state="MN", party="D", secondary=secondary,
        transport=lambda url, **kwargs: StubResponse(200, body, homepage),
    )
    assert error is None
    assert [c.url for c in candidates] == ["https://example.org/platform-2024.pdf"]


@pytest.mark.parametrize(
    "path", ["/partydocuments/", "/party-documents/", "/party_documents/",
             "/constitution/", "/bylaws/"],
)
def test_deep_discovery_retains_weak_institutional_indexes_without_widening_primary(path):
    homepage = "https://example.org/"
    body = (f'<a href="{path}">Party documents</a>'
            f'<a href="https://elsewhere.org{path}">Party documents</a>').encode()
    requests = []

    def transport(url, **kwargs):
        requests.append(url)
        return StubResponse(200, body, homepage)

    primary, error = homepage_candidates(
        homepage, state="MN", party="D", transport=transport,
    )
    assert error is None and primary == []
    assert requests == [homepage]
    secondary, error = homepage_candidates(
        homepage, state="MN", party="D", transport=transport, secondary=True,
    )
    assert error is None
    assert len(secondary) == 1
    assert secondary[0].url == homepage.rstrip("/") + path
    assert secondary[0].score < STRONG_SCORE
    assert secondary[0].link_source_sha256 == sha256(body).hexdigest()
    assert requests == [homepage, homepage]


@pytest.mark.parametrize("label", ["Education Resolution", "Education Resolutions"])
def test_official_singular_or_plural_resolution_label_preserves_opaque_pdf(label):
    homepage = "https://example.org/"
    body = f'<a href="/opaque.pdf">{label}</a>'.encode()
    candidates, error = homepage_candidates(
        homepage, state="FL", party="D",
        transport=lambda url, **kwargs: StubResponse(200, body, homepage),
    )
    assert error is None
    assert len(candidates) == 1
    assert candidates[0].score >= STRONG_SCORE
    assert candidates[0].link_text == label


def test_cli_checkpoints_results_before_a_later_interruption(tmp_path, monkeypatch):
    from state_politics.platforms import discover

    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"organizations": [
        {"state": "AK", "party": "D"}, {"state": "AK", "party": "R"},
    ]}))
    out = tmp_path / "candidates.jsonl"
    checkpoint_dir = tmp_path / "checkpoints"
    raw_dir = tmp_path / "raw"

    def run(org, **kwargs):
        assert kwargs["raw_dir"] == str(raw_dir)
        if org["party"] == "R":
            raise RuntimeError("interrupted")
        return discover.DiscoveryOutcome(
            state="AK", party="D", wayback_ok=True,
            candidates=[Candidate(
                state="AK", party="D", url="https://example.org/platform.pdf",
                source="live", score=5, link_text="Party platform",
            )],
        )

    monkeypatch.setattr(discover, "discover_for_org", run)
    with pytest.raises(RuntimeError, match="interrupted"):
        discover.main([
            "--registry", str(registry), "--out", str(out), "--delay", "0",
            "--raw-dir", str(raw_dir), "--checkpoint-dir", str(checkpoint_dir),
        ])
    checkpoint = json.loads((checkpoint_dir / "AK-D-initial.json").read_text())
    assert checkpoint["outcome"]["candidates"][0]["link_text"] == "Party platform"
    assert checkpoint["registry_sha256"] == sha256(registry.read_bytes()).hexdigest()
    assert checkpoint["discovery_code_sha256"] == sha256(
        Path(discover.__file__).read_bytes()
    ).hexdigest()
    assert not out.exists()
    assert not list(checkpoint_dir.glob("*.part"))
    with pytest.raises(SystemExit):
        discover.main([
            "--registry", str(registry), "--out", str(out),
            "--checkpoint-dir", str(checkpoint_dir),
        ])


def test_cli_keeps_failed_archive_retries_separate_from_initial_results(tmp_path, monkeypatch):
    from state_politics.platforms import discover

    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"organizations": [{"state": "AK", "party": "D"}]}))
    out = tmp_path / "candidates.jsonl"
    checkpoint_dir = tmp_path / "checkpoints"

    def run(org, *, include_live, **kwargs):
        return discover.DiscoveryOutcome(
            state=org["state"], party=org["party"],
            wayback_error="initial failure" if include_live else "retry failure",
            candidates=[Candidate(
                state="AK", party="D", url="https://example.org/platform.pdf",
                source="live", score=5,
            )] if include_live else [],
        )

    monkeypatch.setattr(discover, "discover_for_org", run)
    monkeypatch.setattr(discover.time, "sleep", lambda _: None)
    assert discover.main([
        "--registry", str(registry), "--out", str(out), "--delay", "0",
        "--checkpoint-dir", str(checkpoint_dir),
    ]) == 0
    initial = json.loads((checkpoint_dir / "AK-D-initial.json").read_text())
    retry = json.loads((checkpoint_dir / "AK-D-wayback-retry.json").read_text())
    assert initial["outcome"]["wayback_error"] == "initial failure"
    assert initial["retry_outcome"] is None
    assert retry["retry_outcome"]["wayback_error"] == "retry failure"
    assert len(retry["outcome"]["candidates"]) == 1
    assert len(out.read_text().splitlines()) == 1


def test_live_only_discovery_never_queries_the_archive():
    def transport(url, **kwargs):
        assert "web.archive.org" not in url
        return StubResponse(200, b'<a href="/platform.pdf">Party platform</a>', url)

    outcome = discover_for_org(
        {"state": "TX", "party": "D", "website": "https://example.org/"},
        include_wayback=False, transport=transport,
    )
    assert outcome.live_ok
    assert not outcome.wayback_ok
    assert outcome.wayback_error is None
    assert len(outcome.candidates) == 1


def test_cli_rejects_disabling_both_discovery_channels():
    from state_politics.platforms.discover import main

    with pytest.raises(SystemExit) as error:
        main(["--no-live", "--no-wayback"])
    assert error.value.code == 2


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
        "https://floridadems.org/wp-content/uploads/2026/08/FDP-Public-Ed-Resolution.pdf",
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
        "https://example.org/platform/061e99_153b98fadd5d43039829c3ce89c47905",
        "https://example.org/platform/061e99_153b98fadd5d43039829c3ce89c47905.png",
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


@pytest.mark.parametrize(
    "url,year",
    [
        ("https://iowademocrats.org/wp-content/uploads/2025/07/Platform-2024-reformatted.pdf",
         2024),
        ("https://iowagop.org/wp-content/uploads/sites/40/2026/02/"
         "2024_Iowa_Republican_Platform_FINAL-FINAL.pdf", 2024),
    ],
)
def test_year_hint_prefers_named_document_year_over_upload_directory(url, year):
    rows = [["20261018000000", url, "application/pdf"]]
    found, error = wayback_candidates(
        "example.org", state="IA", party="D",
        transport=lambda url, **kwargs: StubResponse(200, _cdx_body(rows)),
    )
    assert error is None
    assert found[0].year_hint == year


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


@pytest.mark.parametrize(
    "url",
    [
        "https://www.delawaregop.com/platform/-0.88",
        "https://www.delawaregop.com/platform/0.45em",
        "https://www.delawaregop.com/platform/0.23",
        "https://www.delawaregop.com/_api/wix-laboratory-server/v1/laboratory/platform/run",
    ],
)
def test_wix_synthetic_urls_are_excluded(url):
    """Wix emits thousands of /platform/<css-value> URLs; Delaware alone produced 1,899."""
    assert is_excluded(url)


def test_the_real_wix_platform_page_survives():
    assert not is_excluded("https://www.delawaregop.com/platform")


def test_secondary_terms_are_a_fallback_not_the_default():
    """Applied to every organization they bury real documents under news posts."""
    from state_politics.platforms.discover import DISCOVERY_TERMS, SECONDARY_TERMS

    assert not set(SECONDARY_TERMS) & set(DISCOVERY_TERMS)
    assert "issues" in SECONDARY_TERMS
    assert "platform" in DISCOVERY_TERMS


def test_domain_aliases_point_at_pre_rebrand_domains():
    from state_politics.platforms.discover import DOMAIN_ALIASES

    assert "delawaregop.com" in DOMAIN_ALIASES["degop.gop"]
    assert "rpv.org" in DOMAIN_ALIASES["virginia.gop"]
    assert "azdem.org" in DOMAIN_ALIASES["azdems.org"]
    assert all(isinstance(v, tuple) and v for v in DOMAIN_ALIASES.values())


def test_repeated_path_segments_are_excluded():
    """The signature of a generated URL; no genuine document path repeats a segment."""
    assert is_excluded("https://www.delawaregop.com/platform/10K/black/10K/black/white")
    assert is_excluded("https://x.org/platform/a/b/a")


@pytest.mark.parametrize(
    "url",
    [
        "https://idahodems.org/wp-content/uploads/2024/06/2024-Idaho-Democratic-Party-Platform.pdf",
        "https://texasgop.org/2022platform/",
        "https://www.iowagop.org/about/platform/",
        "https://www.delawaregop.com/platform",
        "https://www.nydems.org/about/issues",
    ],
)
def test_real_document_urls_survive_every_exclusion(url):
    assert not is_excluded(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://x.org/platform/c17c8a_046660a3ab9f8b540df3b653de779ce2_664.json",
        "https://x.org/platform/09-Icons-/-Social-/-Twitter",
        "https://x.org/platform/1.4em",
        "https://x.org/platform/robots.txt",
    ],
)
def test_wix_asset_paths_are_excluded(url):
    assert is_excluded(url)

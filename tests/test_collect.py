"""Tests for platform fetching, extraction and confirmation.

The behaviour that matters here is the project's data rule: a document counts only when its
own text shows it is a platform, and a state party with nothing found must be recorded with a
status that says *why*, not simply omitted.
"""

from __future__ import annotations

from state_politics.platforms.collect import (
    DOC_TYPES,
    MIN_CHARS,
    CollectedDocument,
    classify_doc_type,
    collect_candidate,
    collect_for_org,
    confirm_platform,
    extract_text,
    gap_report,
    wayback_snapshot_url,
)
from state_politics.platforms.discover import Candidate

PLATFORM_PROSE = (
    "We believe in limited government. We support the right of every citizen to vote. "
    "We oppose unfunded mandates. We affirm our commitment to public education. "
    "Be it resolved that our party stands for fiscal responsibility. "
) * 20


def platform_prose(state_name: str) -> bytes:
    """Platform prose that also names its state, as a real state platform does."""
    return (
        PLATFORM_PROSE
        + f" The {state_name} party adopted this platform in {state_name}. "
    ).encode()


class StubResponse:
    def __init__(self, status_code: int, content: bytes = b"",
                 content_type: str = "text/html", url: str = "https://x.test/"):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.url = url


def test_wayback_snapshot_url_requests_original_bytes():
    """Without the id_ modifier the archive injects its own banner into the text."""
    url = wayback_snapshot_url("20220710092122", "https://texasgop.org/2022platform/")
    assert url == "https://web.archive.org/web/20220710092122id_/https://texasgop.org/2022platform/"


def test_extract_text_strips_scripts_and_chrome():
    html = (
        b"<html><head><style>body{color:red}</style><script>var x=1;</script></head>"
        b"<body><nav>menu menu menu</nav><p>We believe in liberty.</p>"
        b"<footer>copyright</footer></body></html>"
    )
    text = extract_text(html, "text/html", "https://x.test/platform/")
    assert "We believe in liberty." in text
    for chrome in ("var x=1", "color:red", "menu menu", "copyright"):
        assert chrome not in text


def test_confirm_platform_requires_length_and_declarative_language():
    ok, reason, hits = confirm_platform(PLATFORM_PROSE)
    assert ok
    assert hits >= 3
    assert "confirmed" in reason


def test_confirm_platform_rejects_a_short_landing_page():
    ok, reason, _ = confirm_platform("We believe. We support. We oppose.")
    assert not ok
    assert "too short" in reason


def test_confirm_platform_rejects_long_text_without_platform_voice():
    """A party's news archive is long too; length alone must not qualify it."""
    newsy = "The chairman announced a new fundraising record today. " * 200
    ok, reason, hits = confirm_platform(newsy)
    assert not ok
    assert "lacks platform language" in reason
    assert hits < 3


def test_confirm_platform_rejects_empty_extraction():
    ok, reason, _ = confirm_platform("")
    assert not ok
    assert "no text" in reason


def test_min_chars_is_meaningfully_large():
    assert MIN_CHARS >= 1000


def test_classify_doc_type_distinguishes_priorities_from_platforms():
    assert classify_doc_type(
        "https://texasgop.org/2024-platform-and-legislative-priorities/", ""
    ) == "legislative_priorities"
    assert classify_doc_type("https://texasgop.org/2022platform/", "") == "platform"
    assert classify_doc_type("https://x.org/2024convention/resolutions", "") == "resolutions"
    assert classify_doc_type("https://x.org/our-principles/", "") == "principles"
    assert set(DOC_TYPES) >= {"platform", "resolutions", "legislative_priorities"}


def test_collect_candidate_prefers_the_wayback_snapshot():
    """Live pages change; the archived capture is what makes the corpus reproducible."""
    seen = {}

    def transport(url, *, timeout, headers):
        seen["url"] = url
        return StubResponse(200, platform_prose("Texas"))

    candidate = Candidate(state="TX", party="R", url="https://texasgop.org/2022platform/",
                          source="wayback", wayback_timestamp="20220710092122", score=7,
                          year_hint=2022)
    document = collect_candidate(candidate, transport=transport)
    assert seen["url"].startswith("https://web.archive.org/web/20220710092122id_/")
    assert document.confirmed
    assert document.doc_type == "platform"
    assert document.year == 2022
    assert document.source == "wayback"


def test_collect_candidate_records_a_failed_fetch_without_raising():
    candidate = Candidate(state="TX", party="D", url="https://texasdemocrats.org/platform/",
                          source="live", score=5)
    document = collect_candidate(
        candidate, transport=lambda url, *, timeout, headers: StubResponse(404)
    )
    assert document.confirmed is False
    assert "fetch failed" in document.reason
    assert document.http_status == 404


def test_collect_candidate_keeps_no_text_for_a_rejected_document():
    """Only confirmed documents carry text, so the corpus cannot fill with news pages."""
    candidate = Candidate(state="IA", party="R", url="https://iowagop.org/about/platform/",
                          source="live", score=5)
    document = collect_candidate(
        candidate,
        transport=lambda url, *, timeout, headers: StubResponse(200, b"<p>short</p>"),
    )
    assert not document.confirmed
    assert document.text == ""


def test_collect_for_org_respects_score_threshold_and_cap():
    calls = []

    def transport(url, *, timeout, headers):
        calls.append(url)
        return StubResponse(200, platform_prose("Texas"))

    candidates = [
        Candidate(state="TX", party="R", url=f"https://x.org/p{i}", source="live", score=score)
        for i, score in enumerate([7, 6, 5, 4, -3])
    ]
    collected = collect_for_org(
        candidates, min_score=5, max_documents=2, transport=transport, sleep=lambda _: None
    )
    assert len(collected) == 2
    assert len(calls) == 2


def _doc(state, party, confirmed, year=2024, doc_type="platform"):
    return CollectedDocument(
        state=state, party=party, url="https://x.org/p", fetched_url="https://x.org/p",
        source="wayback", doc_type=doc_type if confirmed else None, year=year,
        confirmed=confirmed, reason="",
    )


def test_gap_report_distinguishes_the_four_absence_reasons():
    """'No candidates existed' and 'candidates all turned out not to be platforms' differ."""
    registry = [
        {"state": "TX", "party": "R", "website": "https://texasgop.org/"},
        {"state": "IA", "party": "R", "website": "https://iowagop.org/"},
        {"state": "MN", "party": "D", "website": "https://dfl.org/"},
        {"state": "MD", "party": "D", "website": None},
    ]
    candidates_by_org = {
        ("TX", "R"): [Candidate(state="TX", party="R", url="u", source="wayback", score=7)],
        ("IA", "R"): [Candidate(state="IA", party="R", url="u", source="wayback", score=6)],
        ("MN", "D"): [Candidate(state="MN", party="D", url="u", source="wayback", score=-3)],
    }
    documents = [_doc("TX", "R", True), _doc("IA", "R", False)]

    report = gap_report(registry, candidates_by_org, documents)
    status = dict(zip(report["state"] + "-" + report["party"], report["status"], strict=True))
    assert status["TX-R"] == "found"
    assert status["IA-R"] == "candidates_rejected"
    assert status["MN-D"] == "no_strong_candidates"
    assert status["MD-D"] == "no_candidates"
    assert len(report) == 4


def test_gap_report_records_every_organization_even_with_no_documents():
    registry = [{"state": "MD", "party": "D", "website": None},
                {"state": "MD", "party": "R", "website": None}]
    report = gap_report(registry, {}, [])
    assert len(report) == 2
    assert (report["n_confirmed"] == 0).all()
    assert report["latest_year"].isna().all()


def test_collect_for_org_flags_the_same_document_served_from_two_urls():
    """Parties serve one platform from several paths; counting each would inflate the corpus."""
    candidates = [
        Candidate(state="TX", party="R", url="https://texasgop.org/2024-platform/",
                  source="live", score=7),
        Candidate(state="TX", party="R", url="https://archive.texasgop.org/2024-platform/x",
                  source="live", score=6),
    ]
    collected = collect_for_org(
        candidates,
        transport=lambda url, *, timeout, headers: StubResponse(200, platform_prose("Texas")),
        sleep=lambda _: None,
    )
    assert len(collected) == 2
    assert sum(d.confirmed for d in collected) == 1
    duplicate = next(d for d in collected if not d.confirmed)
    assert duplicate.reason.startswith("duplicate of ")
    assert duplicate.text == ""


def test_confirm_platform_handles_pdfs_that_lost_their_word_spacing():
    """A real 31,817-char platform extracted as 'SouthDakotaDemocraticParty...' scored 0 hits.

    Some party PDFs embed fonts with no space glyphs, so the spaced patterns never match and
    a genuine platform was discarded.
    """
    mangled = (
        "SouthDakotaDemocraticPartyPlatformAdoptedbytheConvention"
        "WebelieveinpubliceducationWesupportfamilyfarmsWeopposecorporateconsolidation"
        "WeaffirmtherightoworganizeBeitresolvedthatourpartystandsfirm"
    ) * 30
    ok, reason, hits = confirm_platform(mangled)
    assert ok, reason
    assert hits >= 3


def test_confirm_platform_still_rejects_mangled_text_that_is_not_a_platform():
    noise = "AnnualFundraisingDinnerTicketsAvailableNowContactTheOfficeForDetails" * 60
    ok, _, _ = confirm_platform(noise)
    assert not ok


def test_space_ratio_detects_lost_spacing():
    from state_politics.platforms.collect import _space_ratio

    assert _space_ratio("we believe in a fair and open government today") > 0.12
    assert _space_ratio("webelieveinafairandopengovernmenttoday") < 0.08


def test_collect_candidate_falls_back_to_live_when_the_snapshot_is_thin():
    """The archive's capture of massdems.org/our-platform had 1,743 chars; live had 94,756."""
    def transport(url, *, timeout, headers):
        if "web.archive.org" in url:
            return StubResponse(200, b"<p>short capture</p>")
        return StubResponse(200, platform_prose("Massachusetts"))

    candidate = Candidate(state="MA", party="D", url="https://massdems.org/our-platform",
                          source="wayback", wayback_timestamp="20240101000000", score=6)
    document = collect_candidate(candidate, transport=transport, sleep=lambda _: None)
    assert document.confirmed
    assert document.source == "live"
    assert document.fetched_url == "https://massdems.org/our-platform"


def test_collect_candidate_keeps_the_snapshot_when_it_is_adequate():
    """Ties and adequate captures favour the archive, which is the reproducible copy."""
    def transport(url, *, timeout, headers):
        return StubResponse(200, platform_prose("Texas"))

    candidate = Candidate(state="TX", party="R", url="https://texasgop.org/2022platform/",
                          source="wayback", wayback_timestamp="20220710092122", score=7)
    document = collect_candidate(candidate, transport=transport, sleep=lambda _: None)
    assert document.source == "wayback"
    assert document.fetched_url.startswith("https://web.archive.org/")


def test_collect_candidate_uses_live_when_the_snapshot_fetch_fails():
    def transport(url, *, timeout, headers):
        if "web.archive.org" in url:
            raise ConnectionError("refused")
        return StubResponse(200, platform_prose("Iowa"))

    candidate = Candidate(state="IA", party="R", url="https://iowagop.org/about/platform/",
                          source="wayback", wayback_timestamp="20180213194308", score=5)
    document = collect_candidate(candidate, transport=transport, sleep=lambda _: None)
    assert document.confirmed
    assert document.source == "live"


NATIONAL_PROSE = (
    "We believe in a fair economy. We support working families. We oppose corporate excess. "
    "This platform was approved by the Democratic National Convention. The Democratic "
    "National Committee affirms these principles for our nation. We affirm our commitment. "
) * 20


def test_confirm_platform_rejects_a_national_platform_hosted_by_a_state_party():
    """State sites host the DNC/RNC document; it is longer and more fluent than most state
    platforms, so it passes every other test and gets misattributed."""
    ok, reason, _ = confirm_platform(NATIONAL_PROSE, state_name="Oklahoma")
    assert not ok
    assert "national party platform" in reason


def test_confirm_platform_rejects_text_that_never_names_its_state():
    ok, reason, _ = confirm_platform(PLATFORM_PROSE, state_name="Hawaii")
    assert not ok
    assert "never names Hawaii" in reason


def test_confirm_platform_accepts_a_document_that_names_its_state():
    text = PLATFORM_PROSE + " The Montana Democratic Party adopted this in Montana. "
    ok, _, _ = confirm_platform(text, state_name="Montana")
    assert ok


def test_state_attribution_is_skipped_when_no_state_name_is_supplied():
    """The check is opt-in so the function stays usable for non-state documents."""
    ok, _, _ = confirm_platform(PLATFORM_PROSE)
    assert ok


def test_a_national_platform_that_also_discusses_the_state_is_kept():
    """A state platform may cite the national convention; two state mentions is enough."""
    text = NATIONAL_PROSE + " Texas Democrats adopted this in Texas for Texas voters. "
    ok, _, _ = confirm_platform(text, state_name="Texas")
    assert ok


def test_extract_text_rejects_binary_served_as_a_page():
    """Connecticut and Virginia Republicans soft-404 /platform with a 426 KB PNG.

    Without this, those bytes were decoded as text and reached the confirmation stage as a
    426,078-character 'document'.
    """
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4000
    assert extract_text(png, "image/png", "https://ct.gop/platform") == ""
    # Also caught when the server lies about the content type.
    assert extract_text(png, "text/html", "https://ct.gop/platform") == ""


def test_extract_text_rejects_other_binary_signatures():
    for signature in (b"GIF8", b"\xff\xd8\xff", b"PK\x03\x04", b"\x1f\x8b"):
        assert extract_text(signature + b"\x00" * 3000, "text/html", "https://x/p") == ""


def test_extract_text_still_reads_html_and_pdf():
    assert "We believe" in extract_text(b"<p>We believe in liberty.</p>", "text/html",
                                        "https://x/p")
    # A malformed PDF yields empty text rather than raising.
    assert extract_text(b"%PDF-1.4 truncated", "application/pdf", "https://x/a.pdf") == ""


def test_extract_text_handles_content_type_with_charset():
    assert "plank" in extract_text(b"<p>plank</p>", "text/html; charset=utf-8", "https://x/p")

"""Tests for the state party registry builder.

The behaviour these lock down is the one that actually mattered in practice: several
Wikidata URLs for state parties are stale and now resolve to unrelated commercial sites, so
a row is only trusted when the live page itself names the state and the party.
"""

from __future__ import annotations

import pytest
import yaml

from state_politics.platforms.registry import (
    MANUAL_OVERRIDES,
    STATE_NAMES,
    PartyOrg,
    _content_confirms,
    _url_variants,
    match_state,
    parse_sparql_csv,
    verify_homepage,
    write_registry,
)


class StubResponse:
    def __init__(self, status_code: int, content: bytes = b"", url: str = "https://x.test/"):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": "text/html"}
        self.url = url


def test_state_names_covers_fifty_states():
    assert len(STATE_NAMES) == 50
    assert len(set(STATE_NAMES.values())) == 50


@pytest.mark.parametrize(
    ("label", "adm", "expected"),
    [
        ("Republican Party of Texas", "", "TX"),
        ("Alaska Democratic Party", "Alaska", "AK"),
        ("New York Republican State Committee", "", "NY"),
        ("New Jersey Republican State Committee", "", "NJ"),
        ("Hawai\u02bbi Republican Party", "", "HI"),
        # "West Virginia" must not be matched as "Virginia": longest name wins.
        ("West Virginia Republican Party", "", "WV"),
    ],
)
def test_match_state_resolves_real_labels(label, adm, expected):
    assert match_state(label, adm) == expected


@pytest.mark.parametrize(
    "label",
    [
        "Erie County Republican Committee",
        "California Republican Assembly",
        "Greenville County Republican Party",
        "Young Republican",
        "Democratic-Republican Party",
        "National Republican Party",
    ],
)
def test_match_state_rejects_county_and_auxiliary_bodies(label):
    assert match_state(label) is None


def test_match_state_prefers_structural_p131_over_label():
    """P131 is stronger evidence than a name that merely contains a state."""
    assert match_state("Some Ambiguous Committee", "Vermont") == "VT"


def test_url_variants_normalizes_stale_www_urls():
    variants = _url_variants("http://www.ctgop.org")
    assert variants[0] == "http://www.ctgop.org"
    assert "https://ctgop.org" in variants
    assert "https://www.ctgop.org" in variants


def test_content_confirms_requires_both_state_and_party():
    page = b"<title>Home</title> The Texas Republican Party convention"
    assert _content_confirms(page, "TX", "R")
    assert not _content_confirms(page, "TX", "D")
    assert not _content_confirms(b"Republican Party of somewhere", "TX", "R")


def test_verify_homepage_rejects_a_hijacked_domain():
    """Wikidata's migop.org redirected to an unrelated site; a 200 alone must not pass."""
    spam = b"<title>Premium Domain For Sale</title> buy this domain now"
    org = PartyOrg(state="MI", party="R", website="https://migop.org/")
    verified = verify_homepage(
        org, transport=lambda url, *, timeout, headers: StubResponse(200, spam, url)
    )
    assert verified.needs_review is True
    assert "did not name" in verified.note


def test_verify_homepage_accepts_a_confirming_page():
    page = b"<title>Home - MTGOP</title> The Montana Republican Party"
    org = PartyOrg(state="MT", party="R", website="https://mtgop.org/")
    verified = verify_homepage(
        org, transport=lambda url, *, timeout, headers: StubResponse(200, page, url)
    )
    assert verified.needs_review is False
    assert verified.homepage_status == 200
    assert verified.verified_on


def test_verify_homepage_falls_back_to_a_url_variant():
    """A dead http://www. host must not condemn a site that is live at bare https."""
    page = b"The Connecticut Republican Party"

    def transport(url, *, timeout, headers):
        if url.startswith("http://www."):
            raise ConnectionError("name resolution failed")
        return StubResponse(200, page, url)

    org = PartyOrg(state="CT", party="R", website="http://www.ctgop.org")
    verified = verify_homepage(org, transport=transport)
    assert verified.needs_review is False
    assert not verified.website.startswith("http://www.")


def test_verify_homepage_flags_bot_protection_without_claiming_success():
    org = PartyOrg(state="OK", party="R", website="https://okgop.com/")
    verified = verify_homepage(
        org, transport=lambda url, *, timeout, headers: StubResponse(403)
    )
    assert verified.needs_review is True
    assert verified.homepage_status == 403
    assert "refused a scripted request" in verified.note


def test_verify_homepage_handles_missing_website():
    verified = verify_homepage(PartyOrg(state="MD", party="D"))
    assert verified.needs_review is True
    assert verified.note == "no website in Wikidata"


def test_overrides_are_well_formed():
    for (state, party), override in MANUAL_OVERRIDES.items():
        assert state in STATE_NAMES.values()
        assert party in {"D", "R"}
        assert override.website.startswith("https://")
        # Every correction must say how it was established.
        assert "2026-07-28" in override.evidence


def test_parse_sparql_csv():
    rows = parse_sparql_csv("party,partyLabel,website\nQ1,Texas Republican Party,https://x.test\n")
    assert rows == [{"party": "Q1", "partyLabel": "Texas Republican Party",
                     "website": "https://x.test"}]


def test_write_registry_records_source_and_review_flags(tmp_path):
    path = write_registry(
        [
            PartyOrg(state="TX", party="R", website="https://x.test", needs_review=False),
            PartyOrg(state="MD", party="D", needs_review=True, note="no website in Wikidata"),
        ],
        tmp_path / "party_registry.yml",
    )
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "query.wikidata.org" in payload["source"]
    assert payload["generated_at"].endswith("Z")
    assert len(payload["organizations"]) == 2
    assert payload["organizations"][1]["needs_review"] is True

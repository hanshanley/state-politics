"""Tests for the Open States legislator ingest.

This table is the join key for the entire bills stream, so the cases that matter are the ones
where a wrong party assignment would silently misattribute legislation: nonpartisan Nebraska,
the state-specific Democratic labels, and a partial download being mistaken for a complete one.
"""

from __future__ import annotations

import pytest

from state_politics.bills.people import (
    PEOPLE_CSV_URL,
    STATE_CODES,
    download_people,
    normalize_party,
    parse_people_csv,
)

CSV = (
    "id,name,current_party,current_district,current_chamber\n"
    "ocd-person/1,Jane Doe,Democratic,12,upper\n"
    "ocd-person/2,John Roe,Republican,7,lower\n"
)


class StubResponse:
    def __init__(self, status_code: int, content: bytes = b"", url: str = "https://x.test/"):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": "text/csv"}
        self.url = url


def test_state_codes_are_exactly_the_fifty_states():
    assert len(STATE_CODES) == 50
    assert len(set(STATE_CODES)) == 50
    # Congress and the territories are deliberately excluded: this project is about states.
    for excluded in ("us", "dc", "pr", "gu", "vi", "mp", "as"):
        assert excluded not in STATE_CODES


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Democratic", "D"),
        ("democratic", "D"),
        ("Democratic-Farmer-Labor", "D"),   # Minnesota
        ("Democratic-NPL", "D"),            # North Dakota
        ("Republican", "R"),
        ("Independent", "other"),
        ("Nonpartisan", "other"),           # Nebraska's unicameral
        ("Libertarian", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_normalize_party(raw, expected):
    assert normalize_party(raw) == expected


def test_third_parties_are_not_folded_into_the_major_two():
    """Misfiling an independent as D or R would misattribute their bills."""
    for raw in ("Independent", "Green", "Libertarian", "Nonpartisan"):
        assert normalize_party(raw) == "other"


def test_parse_people_csv_keeps_the_raw_party_string():
    people = parse_people_csv(CSV, "tx")
    assert [p.state for p in people] == ["TX", "TX"]
    assert [p.party for p in people] == ["D", "R"]
    assert people[0].party_raw == "Democratic"
    assert people[0].chamber == "upper"
    assert people[0].district == "12"
    assert people[0].is_major_party


def test_download_people_reports_failures_instead_of_dropping_states():
    """A partial download must not be mistakable for a complete one."""
    def transport(url, *, timeout, headers):
        if "/ak.csv" in url:
            return StubResponse(503)
        return StubResponse(200, CSV.encode())

    people, errors = download_people(
        states=("al", "ak"), transport=transport, delay=0, sleep=lambda _: None
    )
    assert len(people) == 2          # only Alabama's two rows
    assert set(errors) == {"AK"}
    assert "503" in errors["AK"]


def test_download_people_uses_the_public_no_auth_url():
    seen = []

    def transport(url, *, timeout, headers):
        seen.append(url)
        return StubResponse(200, CSV.encode())

    download_people(states=("tx",), transport=transport, delay=0, sleep=lambda _: None)
    assert seen == [PEOPLE_CSV_URL.format(code="tx")]
    assert "data.openstates.org/people/current" in seen[0]

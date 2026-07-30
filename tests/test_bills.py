"""Tests for the Open States dump reader and the bills ingest.

The cases that matter here are the ones where a parsing slip would silently corrupt a
million-row table: PostgreSQL's ``\\N`` null marker being read as the literal string, Congress
and the territories leaking into a table described as covering the states, and cosponsors
outvoting primary sponsors in party attribution.
"""

from __future__ import annotations

import pytest

from state_politics.bills.ingest import (
    MAX_FILING_LEAD,
    _filing_year,
    attribute_party,
    normalize_party,
)
from state_politics.bills.openstates_dump import STATE_CODES, copy_blocks, state_of


def test_copy_blocks_parses_a_copy_section():
    lines = iter([
        "--",
        "COPY public.opencivicdata_bill (id, identifier, title) FROM stdin;",
        "ocd-bill/1\tHB 1\tAn Act relating to schools",
        "ocd-bill/2\tSB 2\tAn Act relating to roads",
        "\\.",
        "",
    ])
    rows = list(copy_blocks(lines))
    assert len(rows) == 2
    assert rows[0] == {"id": "ocd-bill/1", "identifier": "HB 1",
                       "title": "An Act relating to schools"}


def test_copy_blocks_maps_the_null_marker_to_none():
    """Reading \\N as a literal string would turn every missing value into data."""
    lines = iter([
        'COPY public.t (id, title) FROM stdin;',
        "ocd-bill/1\t\\N",
        "\\.",
    ])
    rows = list(copy_blocks(lines))
    assert rows[0]["title"] is None


def test_copy_blocks_unescapes_tabs_and_newlines():
    lines = iter([
        'COPY public.t (id, title) FROM stdin;',
        "ocd-bill/1\tAn Act\\nrelating to\\ttaxes",
        "\\.",
    ])
    assert list(copy_blocks(lines))[0]["title"] == "An Act\nrelating to\ttaxes"


def test_copy_blocks_skips_rows_with_the_wrong_column_count():
    lines = iter([
        'COPY public.t (id, title) FROM stdin;',
        "only-one-field",
        "ocd-bill/2\tgood row",
        "\\.",
    ])
    rows = list(copy_blocks(lines))
    assert len(rows) == 1
    assert rows[0]["id"] == "ocd-bill/2"


def test_copy_blocks_handles_several_sections():
    lines = iter([
        'COPY public.a (id) FROM stdin;', "1", "\\.",
        'COPY public.b (id) FROM stdin;', "2", "\\.",
    ])
    assert [row["id"] for row in copy_blocks(lines)] == ["1", "2"]


@pytest.mark.parametrize(
    ("jurisdiction", "expected"),
    [
        ("ocd-jurisdiction/country:us/state:tx/government", "TX"),
        ("ocd-jurisdiction/country:us/state:ak/government", "AK"),
        # Congress is explicitly out of scope for this project.
        ("ocd-jurisdiction/country:us/government", None),
        # Territories would quietly widen the population being described.
        ("ocd-jurisdiction/country:us/district:dc/government", None),
        ("ocd-jurisdiction/country:us/territory:pr/government", None),
        (None, None),
        ("", None),
    ],
)
def test_state_of_admits_only_the_fifty_states(jurisdiction, expected):
    assert state_of(jurisdiction) == expected


def test_state_codes_is_exactly_fifty():
    assert len(STATE_CODES) == 50


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Democratic", "D"),
        ("Republican", "R"),
        ("Democratic-Farmer-Labor", "D"),
        ("Independent", "other"),
        ("Nonpartisan", "other"),
        (None, "other"),
    ],
)
def test_normalize_party(raw, expected):
    assert normalize_party(raw) == expected


def test_attribute_party_is_decided_by_primary_sponsors():
    """Cosponsor lists are long, cross-party and procedural; letting them vote blurs the
    distinction the table exists to draw."""
    assert attribute_party(["D"], ["D", "R", "R", "R", "R"]) == "D"
    assert attribute_party(["R"], ["R", "D", "D", "D"]) == "R"


def test_attribute_party_marks_genuinely_bipartisan_bills():
    assert attribute_party(["D", "R"], ["D", "R"]) == "bipartisan"


def test_attribute_party_falls_back_to_all_sponsors_when_no_primary_resolves():
    assert attribute_party([], ["D", "D"]) == "D"
    assert attribute_party(["unknown"], ["R", "R"]) == "R"


def test_attribute_party_returns_unknown_rather_than_guessing():
    assert attribute_party([], []) == "unknown"
    assert attribute_party(["other"], ["other", "unknown"]) == "unknown"


def test_third_party_sponsors_do_not_become_major_party_bills():
    assert attribute_party(["other"], ["other"]) == "unknown"


def test_filing_year_rejects_dates_the_session_contradicts():
    """A few source rows carry impossible first-action dates.

    They are too rare to move a topic share but ``year`` dates diffusion clusters, where one
    bad row reports a modern model bill as first appearing decades early.
    """
    assert _filing_year(2021, 202) == 2021        # Montana HB 73, truncated year
    assert _filing_year(2019, 1959) == 2019       # Michigan HR 290, a 2019 resolution
    assert _filing_year(2023, 2003) == 2023       # West Virginia SB 746


def test_filing_year_keeps_genuine_early_filing():
    """New Hampshire files service requests the year before a session convenes."""
    assert _filing_year(2018, 2016) == 2016
    assert _filing_year(2018, 2017) == 2017
    assert _filing_year(2018, 2018 - MAX_FILING_LEAD) == 2018 - MAX_FILING_LEAD


def test_filing_year_falls_back_when_a_date_is_missing():
    assert _filing_year(2020, None) == 2020
    assert _filing_year(None, 2021) == 2021
    assert _filing_year(None, None) is None

"""Tests for the Open States dump reader and the bills ingest.

The cases that matter here are the ones where a parsing slip would silently corrupt a
million-row table: PostgreSQL's ``\\N`` null marker being read as the literal string, Congress
and the territories leaking into a table described as covering the states, and cosponsors
outvoting primary sponsors in party attribution.
"""

from __future__ import annotations

import json

import pandas as pd
import pyarrow.parquet as pq
import pytest

from state_politics.bills import openstates_dump as dump_module
from state_politics.bills.ingest import (
    MAX_FILING_LEAD,
    _filing_year,
    attribute_party,
    normalize_party,
)
from state_politics.bills.openstates_dump import STATE_CODES, copy_blocks, state_of
from state_politics.provenance import FetchRecord, ProvenanceLog, sha256_file


def test_configured_pg_restore_takes_precedence_and_invalid_override_fails(monkeypatch):
    monkeypatch.setattr(
        dump_module.shutil, "which",
        lambda value: {
            "/verified/pg_restore": "/verified/pg_restore", "pg_restore": "/other/pg_restore",
        }.get(value),
    )
    monkeypatch.setenv("PG_RESTORE", "/verified/pg_restore")
    assert dump_module.find_pg_restore() == "/verified/pg_restore"
    monkeypatch.setenv("PG_RESTORE", "/invalid/pg_restore")
    with pytest.raises(RuntimeError, match="PG_RESTORE is not an executable"):
        dump_module.find_pg_restore()


def test_dump_reuse_requires_matching_month_path_and_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(dump_module, "find_pg_restore", lambda: "/verified/pg_restore")
    monkeypatch.setattr(
        dump_module, "download_to_file", lambda *a, **kw: pytest.fail("must not overwrite"),
    )
    path = tmp_path / "source.pgdump"
    path.write_bytes(b"synthetic archive fixture")
    log = ProvenanceLog(tmp_path / "provenance.jsonl")
    record = FetchRecord(
        url=dump_module.DUMP_URL.format(month="2026-10"), source_org=dump_module.SOURCE_ORG,
        retrieved_at="2026-10-18T00:00:00Z", ok=True, stored_path=str(path),
        content_sha256=sha256_file(path),
    )
    log.append(record)
    assert dump_module.download_dump(path, "2026-10", log=log) == record
    with pytest.raises(ValueError, match="source/checksum provenance"):
        dump_module.download_dump(path, "2026-09", log=log)
    path.write_bytes(b"damaged fixture")
    with pytest.raises(ValueError, match="source/checksum provenance"):
        dump_module.download_dump(path, "2026-10", log=log)
    assert path.read_bytes() == b"damaged fixture"


def test_dump_download_preflights_tools_and_propagates_failure(tmp_path, monkeypatch):
    def unavailable():
        raise RuntimeError("pg_restore not found")

    calls = []
    monkeypatch.setattr(dump_module, "find_pg_restore", unavailable)
    monkeypatch.setattr(dump_module, "download_to_file", lambda *a, **kw: calls.append(a))
    log = ProvenanceLog(tmp_path / "provenance.jsonl")
    path = tmp_path / "source.pgdump"
    with pytest.raises(RuntimeError, match="pg_restore not found"):
        dump_module.download_dump(path, "2026-10", log=log)
    assert not calls and not path.exists()
    monkeypatch.setattr(dump_module, "find_pg_restore", lambda: "/verified/pg_restore")
    monkeypatch.setattr(
        dump_module, "download_to_file", lambda *a, **kw: FetchRecord(
            url=a[0], source_org=dump_module.SOURCE_ORG,
            retrieved_at="2026-10-18T00:00:00Z", ok=False, error="timeout",
        ),
    )
    with pytest.raises(RuntimeError, match="timeout"):
        dump_module.download_dump(path, "2026-10", log=log)
    with pytest.raises(ValueError, match="YYYY-MM"):
        dump_module.download_dump(path, "2026-13", log=log)


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


def test_copy_blocks_rejects_rows_with_the_wrong_column_count():
    lines = iter([
        'COPY public.t (id, title) FROM stdin;',
        "only-one-field",
        "ocd-bill/2\tgood row",
        "\\.",
    ])
    with pytest.raises(ValueError, match="expected 2 columns, found 1"):
        list(copy_blocks(lines))


def test_copy_blocks_requires_terminator_and_requested_source_table():
    with pytest.raises(ValueError, match="unterminated COPY"):
        list(copy_blocks(iter(["COPY public.t (id) FROM stdin;", "1"])))
    with pytest.raises(ValueError, match="no COPY block"):
        list(copy_blocks(iter(["-- requested table absent"]), require_copy=True))


def test_copy_blocks_preserves_control_escapes_and_encoded_unicode():
    rows = list(copy_blocks(iter([
        "COPY public.t (id, text) FROM stdin;",
        r"one" + "\t" + r"\b\f\v\303\251\xC3\xA9\\n",
        "\\.",
    ])))
    assert rows[0]["text"] == "\b\f\véé\\n"


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


def test_attribute_party_falls_back_only_when_no_primary_is_recorded():
    assert attribute_party([], ["D", "D"]) == "D"
    assert attribute_party(["unknown"], ["R", "R"]) == "unknown"
    assert attribute_party(["D", "unknown"], ["D", "R"]) == "unknown"
    assert attribute_party(["other"], ["other", "D"]) == "other"


def test_attribute_party_returns_unknown_rather_than_guessing():
    assert attribute_party([], []) == "unknown"
    assert attribute_party(["other"], ["other", "unknown"]) == "other"


def test_third_party_sponsors_do_not_become_major_party_bills():
    assert attribute_party(["other"], ["other"]) == "other"


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


def test_build_bills_uses_historical_memberships_and_preserves_unresolved_primary(monkeypatch):
    from state_politics.bills import ingest

    jurisdiction = "ocd-jurisdiction/country:us/state:tx/government"
    tables = {
        "opencivicdata_jurisdiction": [{"id": jurisdiction}],
        "opencivicdata_legislativesession": [{
            "id": "session", "jurisdiction_id": jurisdiction, "start_date": "2019-01-01",
        }],
        "opencivicdata_organization": [
            {"id": "dem", "classification": "party", "name": "Democratic"},
            {"id": "rep", "classification": "party", "name": "Republican"},
        ],
        "opencivicdata_membership": [
            {"person_id": "switcher", "organization_id": "dem",
             "start_date": "2018-01-01", "end_date": "2021-12-31"},
            {"person_id": "switcher", "organization_id": "rep",
             "start_date": "2022-01-01", "end_date": ""},
        ],
        "opencivicdata_bill": [
            {"id": bill_id, "legislative_session_id": "session", "first_action_date": filed,
             "title": "Provide funding for public education"}
            for bill_id, filed in (
                ("early", "2019-02-01"), ("late", "2023-02-01"), ("unknown", "2019-02-01")
            )
        ],
        "opencivicdata_billsponsorship": [
            {"bill_id": bill_id, "person_id": "switcher", "primary": "t"}
            for bill_id in ("early", "late")
        ] + [
            {"bill_id": "unknown", "person_id": "missing", "primary": "t"},
            {"bill_id": "unknown", "person_id": "switcher", "primary": "f"},
        ],
    }
    def stream(path, table):
        return iter(tables.get(table, []))

    monkeypatch.setattr(ingest, "stream_table", stream)
    from state_politics.bills import openstates_dump
    monkeypatch.setattr(openstates_dump, "stream_table", stream)
    bills, sponsors = ingest.build_bills("fixture")
    indexed = bills.set_index("bill_id")
    assert indexed.at["early", "sponsor_party"] == "D"
    assert indexed.at["late", "sponsor_party"] == "R"
    assert indexed.at["unknown", "sponsor_party"] == "unknown"
    assert indexed.at["early", "party_attribution_date_basis"] == "first_action_proxy"
    assert indexed.at["early", "party_attribution_date"] == "2019-02-01"
    assert len(sponsors) == 4
    assert set(sponsors.loc[sponsors.person_id.eq("switcher"), "party_resolution_reason"]) == {
        "active_membership",
    }
    assert sponsors.loc[sponsors.person_id.eq("missing"), "party_resolution_reason"].tolist() == [
        "missing_membership",
    ]


@pytest.mark.parametrize(("event_date", "valid"), [
    ("2024-06-01Tnot-a-time", False),
    ("2024-06-01T25:00:00", False),
    ("2024-06-01/2025-06-01", False),
    ("2024-06-01 trailing text", False),
    ("20240601T235959", True),
    ("2024-W22-6T23:59:59", True),
    ("2024-06-01T23:59:59-05:00", True),
])
def test_sponsor_and_voter_parties_validate_the_complete_event_date(
    monkeypatch, tmp_path, event_date, valid,
):
    from state_politics.bills import ingest, openstates_dump, outcomes

    jurisdiction = "ocd-jurisdiction/country:us/state:tx/government"
    tables = {
        "opencivicdata_jurisdiction": [{"id": jurisdiction}],
        "opencivicdata_legislativesession": [{
            "id": "session", "jurisdiction_id": jurisdiction, "start_date": "2024-01-01",
        }],
        "opencivicdata_organization": [{
            "id": "dem", "classification": "party", "name": "Democratic",
        }],
        "opencivicdata_membership": [{
            "person_id": "person", "organization_id": "dem",
            "start_date": "2024-06-01", "end_date": "2024-06-01",
        }],
        "opencivicdata_bill": [{
            "id": "bill", "legislative_session_id": "session", "first_action_date": event_date,
        }],
        "opencivicdata_billsponsorship": [{
            "bill_id": "bill", "person_id": "person", "primary": "t",
        }],
        "opencivicdata_voteevent": [{
            "id": "vote", "bill_id": "bill", "start_date": event_date,
        }],
        "opencivicdata_personvote": [{
            "vote_event_id": "vote", "voter_id": "person", "option": "yes",
        }],
    }

    def stream(path, table):
        return iter(tables.get(table, []))

    monkeypatch.setattr(ingest, "stream_table", stream)
    monkeypatch.setattr(openstates_dump, "stream_table", stream)
    bills, sponsors = ingest.build_bills("synthetic")
    expected_party = "D" if valid else "unknown"
    assert bills.sponsor_party.tolist() == [expected_party]
    assert bills.party_attribution_date.tolist() == ["2024-06-01" if valid else ""]
    assert bills.party_attribution_date_basis.tolist() == [
        "first_action_proxy" if valid else "invalid_first_action",
    ]
    assert sponsors.party_resolution_reason.tolist() == [
        "active_membership" if valid else "missing_event_date",
    ]
    assert outcomes.resolve_party_on_date(
        [("2024-06-01", "2024-06-01", "D")], event_date,
    ) == (
        expected_party, "active_membership" if valid else "invalid_event_date",
    )
    outcomes.extract_outcomes("synthetic", bills, tmp_path)
    counts = pd.read_parquet(tmp_path / "vote_party_counts.parquet")
    assert counts.voter_party.tolist() == [expected_party]
    assert counts.sponsor_party.tolist() == [expected_party]
    assert counts.n_votes.tolist() == [1]


@pytest.mark.parametrize(("primary", "person_id", "entity_type", "expected"), [
    ("t", None, "organization", "unknown"),
    ("t", "missing", "person", "unknown"),
    ("f", None, "organization", "D"),
])
def test_build_bills_preserves_sponsor_roles_and_partially_unresolved_primaries(
    monkeypatch, primary, person_id, entity_type, expected,
):
    from state_politics.bills import ingest, openstates_dump

    jurisdiction = "ocd-jurisdiction/country:us/state:tx/government"
    unresolved = {
        "id": "unresolved", "bill_id": "bill", "person_id": person_id,
        "entity_type": entity_type, "organization_id": "committee", "name": "Source name",
        "classification": "source-role", "primary": primary,
    }
    tables = {
        "opencivicdata_jurisdiction": [{"id": jurisdiction}],
        "opencivicdata_legislativesession": [{
            "id": "session", "jurisdiction_id": jurisdiction, "start_date": "2024-01-01",
        }],
        "opencivicdata_organization": [
            {"id": "dem", "classification": "party", "name": "Democratic"},
        ],
        "opencivicdata_membership": [
            {"person_id": "known", "organization_id": "dem",
             "start_date": "2020-01-01", "end_date": None},
            {"person_id": None, "organization_id": "dem",
             "start_date": "2020-01-01", "end_date": None},
        ],
        "opencivicdata_bill": [{
            "id": "bill", "legislative_session_id": "session",
            "first_action_date": "2024-06-01",
        }],
        "opencivicdata_billsponsorship": [
            {"bill_id": "bill", "person_id": "known", "entity_type": "person",
             "primary": "t"},
            unresolved,
        ],
    }
    def stream(path, table):
        return iter(tables.get(table, []))

    monkeypatch.setattr(ingest, "stream_table", stream)
    monkeypatch.setattr(openstates_dump, "stream_table", stream)
    bills, sponsors = ingest.build_bills("fixture")
    assert bills.sponsor_party.tolist() == [expected]
    assert bills.n_sponsors.tolist() == [2]
    assert bills.n_primary_sponsors.tolist() == [2 if primary == "t" else 1]
    assert bills.n_unresolved_primary_sponsors.tolist() == [int(primary == "t")]
    assert bills.sponsor_attribution_basis.tolist() == ["primary"]
    original = sponsors.iloc[1]
    for field in ("person_id", "entity_type", "organization_id", "classification"):
        if unresolved[field] is None:
            assert pd.isna(original[field])
        else:
            assert original[field] == unresolved[field]
    assert original.sponsor_name == unresolved["name"]
    assert original.party == "unknown"
    assert original.party_resolution == "unresolved"
    assert original.party_resolution_reason == (
        "missing_person_id" if person_id is None else "missing_membership"
    )


def test_evidence_retains_source_versions_and_reconciles_exact_bill_joins(tmp_path, monkeypatch):
    from state_politics.bills import ingest

    bills = pd.DataFrame({"bill_id": ["included", "no-evidence"], "state": ["TX", "AK"]})
    abstract = {
        "id": "a", "abstract": "Original introduced summary\nincluding its second line.",
        "note": "as introduced", "bill_id": "included",
    }
    version = {
        "id": "v", "note": "Signed act", "date": None, "bill_id": "included",
        "extras": "{}", "classification": "{}",
    }
    tables = {
        "opencivicdata_billabstract": [
            abstract, {**abstract, "id": "excluded", "bill_id": "outside-window"},
        ],
        "opencivicdata_billsource": [
            {"id": "s", "note": "", "url": "", "bill_id": "included"},
        ],
        "opencivicdata_billversion": [
            version, {**version, "id": "excluded-version", "bill_id": "outside-window"},
        ],
        "opencivicdata_billversionlink": [
            {"id": "l", "media_type": "text/html",
             "url": "https://legislature.example/act", "version_id": "v"},
            {"id": "excluded-link", "media_type": "text/html",
             "url": "https://legislature.example/other", "version_id": "excluded-version"},
        ],
    }
    monkeypatch.setattr(ingest, "stream_table", lambda path, table: iter(tables[table]))
    report = ingest.extract_bill_evidence("fixture", bills, tmp_path)
    assert pd.read_parquet(tmp_path / "bill_abstracts.parquet").to_dict("records") == [abstract]
    assert pq.read_table(tmp_path / "bill_versions.parquet").to_pylist() == [version]
    links = pd.read_parquet(tmp_path / "bill_version_links.parquet")
    assert links["bill_id"].tolist() == ["included"]
    assert links["version_id"].tolist() == ["v"]
    coverage = pd.read_parquet(tmp_path / "bill_evidence_coverage.parquet").set_index("bill_id")
    assert coverage.at["included", "n_nonempty_abstracts"] == 1
    assert coverage.at["no-evidence", "n_abstracts"] == 0
    assert report["source_rows"]["billabstract"] == 2
    assert report["retained_rows"]["billabstract"] == 1
    assert report["bills_with_source_urls"] == 0
    assert report["bills_with_version_references"] == 1
    assert report["rich_text_automatically_used_for_filing_classification"] is False


def test_extraction_failure_preserves_incomplete_manifest(tmp_path, monkeypatch):
    from state_politics.bills import ingest

    dump = tmp_path / "fixture.pgdump"
    dump.write_bytes(b"synthetic source")
    out = tmp_path / "output"
    monkeypatch.setattr(ingest, "find_pg_restore", lambda: "/verified/pg_restore")

    def fail(*args, **kwargs):
        raise RuntimeError("source extraction failed")

    monkeypatch.setattr(ingest, "build_bills", fail)
    with pytest.raises(RuntimeError, match="source extraction failed"):
        ingest.main(["--dump", str(dump), "--out-dir", str(out),
                     "--provenance", str(tmp_path / "provenance.jsonl")])
    manifest = json.loads((out / "bill_extraction_manifest.json").read_text())
    assert manifest["status"] == "incomplete"
    assert manifest["source_sha256"] == sha256_file(dump)
    assert not (out / "bills.parquet").exists()
    with pytest.raises(FileExistsError, match="never overwrite"):
        ingest.main(["--dump", str(dump), "--out-dir", str(out)])


def test_ingest_promotes_complete_reconciled_artifact_bundle(tmp_path, monkeypatch):
    from state_politics.bills import ingest

    jurisdiction = "ocd-jurisdiction/country:us/state:tx/government"
    tables = {
        "opencivicdata_jurisdiction": [{"id": jurisdiction}],
        "opencivicdata_legislativesession": [{
            "id": "session", "jurisdiction_id": jurisdiction,
            "identifier": "2025", "start_date": "2025-01-01",
        }],
        "opencivicdata_bill": [{
            "id": "bill", "legislative_session_id": "session",
            "title": "Fund public schools", "first_action_date": "2025-02-01",
        }],
        "opencivicdata_billabstract": [{
            "id": "abstract", "abstract": "Provide school funding.",
            "note": "As introduced", "bill_id": "bill",
        }],
    }
    monkeypatch.setattr(
        ingest, "stream_table", lambda path, table: iter(tables.get(table, [])),
    )
    monkeypatch.setattr(dump_module, "stream_table", ingest.stream_table)
    monkeypatch.setattr(ingest, "find_pg_restore", lambda: "/verified/pg_restore")
    dump = tmp_path / "fixture.pgdump"
    dump.write_bytes(b"synthetic source")
    out = tmp_path / "output"
    assert ingest.main([
        "--dump", str(dump), "--out-dir", str(out),
        "--provenance", str(tmp_path / "provenance.jsonl"),
    ]) == 0
    manifest = json.loads((out / "bill_extraction_manifest.json").read_text())
    assert manifest["status"] == "complete_extraction_not_source_certification"
    assert manifest["scientific_certification"] == "not_performed"
    assert manifest["source_row_counts"]["opencivicdata_bill"] == 1
    assert manifest["bill_admission_counts"]["retained_source_context"] == 1
    for name, artifact in manifest["artifacts"].items():
        assert artifact["sha256"] == sha256_file(out / name)
        assert artifact["rows"] == pq.read_metadata(out / name).num_rows
    assert manifest["artifacts"]["bills.parquet"]["rows"] == 1
    assert manifest["evidence"]["bills_with_nonempty_abstracts"] == 1
    assert not list(out.glob(".bill-extraction-*"))

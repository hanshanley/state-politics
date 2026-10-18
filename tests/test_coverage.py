"""Tests for machine-readable analytical capability reporting."""

from __future__ import annotations

import io
import tarfile

import pandas as pd
import pytest

from state_politics.analysis.audit_bills import (
    audit_bill_sources,
    inspect_dump_party_memberships,
    inspect_party_history_archive,
)
from state_politics.analysis.coverage import build_capability_report
from state_politics.provenance import sha256_file


def _bill_source_fixtures():
    bills = pd.DataFrame([{
        "bill_id": "bill", "state": "TX", "session_identifier": "2025",
        "session_year": 2025, "year": 2025, "first_action_date": "2025-02-01",
        "latest_action_date": "2025-01-01", "title": "Fund schools",
        "sponsor_party": "unknown", "n_unresolved_primary_sponsors": 1,
        "n_sponsors": 2, "sponsor_attribution_basis": "primary",
        "party_attribution_date_basis": "first_action_proxy",
        "n_actions": 2, "n_vote_events": 0,
    }, {
        "bill_id": "context", "state": "NE", "session_identifier": "2018",
        "session_year": 2018, "year": 2017, "first_action_date": "invalid source date",
        "latest_action_date": "2027-01-01", "title": " ",
        "sponsor_party": "nonpartisan", "n_unresolved_primary_sponsors": 0,
        "n_sponsors": 0, "sponsor_attribution_basis": "all_sponsors_fallback",
        "party_attribution_date_basis": "invalid_first_action",
        "n_actions": 0, "n_vote_events": 0,
    }])
    evidence = bills[["bill_id", "state"]].copy()
    evidence["n_nonempty_abstracts"] = [1, 0]
    evidence["n_nonempty_source_urls"] = [1, 0]
    evidence["n_nonempty_version_urls"] = [0, 0]
    return bills, evidence


def test_bill_source_audit_preserves_missingness_and_raw_context_denominators():
    bills, evidence = _bill_source_fixtures()
    summary, states, sessions, flags = audit_bill_sources(
        bills, evidence, observed_on="2026-10-18",
    )
    assert summary["analysis_cutoff"] is None
    assert summary["n_source_context_bills"] == 2
    assert summary["counts"]["before_2018_context"] == 1
    assert summary["counts"]["latest_precedes_first_action"] == 1
    assert summary["counts"]["first_action_invalid"] == 1
    assert summary["counts"]["latest_action_after_observation"] == 1
    assert summary["counts"]["unknown_sponsor_party"] == 1
    assert summary["counts"]["no_nonempty_abstract"] == 1
    assert states["n_source_context_bills"].sum() == sessions["n_source_context_bills"].sum() == 2
    assert len(states) == 50
    assert states.set_index("state").at["AK", "source_row_status"] == "no_retained_source_rows"
    assert flags.set_index("bill_id").at["context", "before_2018_context"]


@pytest.mark.parametrize("defect", ["duplicate", "unmatched", "wrong_state"])
def test_bill_source_audit_rejects_nonidentical_evidence_joins(defect):
    bills, evidence = _bill_source_fixtures()
    if defect == "duplicate":
        evidence.loc[1, "bill_id"] = "bill"
    elif defect == "unmatched":
        evidence.loc[1, "bill_id"] = "unmatched"
    else:
        evidence.loc[1, "state"] = "AK"
    with pytest.raises(ValueError):
        audit_bill_sources(bills, evidence, observed_on="2026-10-18")


def test_party_history_inventory_keeps_undated_records_unknown(tmp_path):
    revision = "a" * 40
    path = tmp_path / "people.tar.gz"
    content = (
        b"id: ocd-person/example\nparty:\n- name: Democratic\n"
        b"- name: Republican\n  start_date: 2020-01-01\n"
    )
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(f"people-{revision}/data/tx/retired/person.yml")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    report = inspect_party_history_archive(
        path, revision=revision, expected_sha256=sha256_file(path),
    )
    assert report["counts"]["people"] == 1
    assert report["counts"]["multiple_party_records"] == 1
    assert report["party_date_bounds"] == {"start=False,end=False": 1, "start=True,end=False": 1}
    with pytest.raises(ValueError, match="checksum/revision mismatch"):
        inspect_party_history_archive(path, revision=revision, expected_sha256="0" * 64)


def test_membership_reference_preserves_raw_undated_and_dated_source_rows(monkeypatch):
    from state_politics.bills import openstates_dump

    undated = {
        "id": "undated", "person_id": "one", "organization_id": "dem",
        "start_date": "", "end_date": "",
    }
    dated = {**undated, "id": "dated", "person_id": "two", "start_date": "2020-01-01"}
    tables = {
        "opencivicdata_organization": [
            {"id": "dem", "classification": "party", "name": "Democratic"},
        ],
        "opencivicdata_membership": [
            undated, dated, {**dated, "id": "chamber", "organization_id": "senate"},
        ],
    }
    monkeypatch.setattr(
        openstates_dump, "stream_table", lambda path, table: iter(tables[table]),
    )
    counts, reference = inspect_dump_party_memberships("fixture")
    assert counts == {
        "all_source_memberships": 3, "party_memberships": 2,
        "entirely_undated": 1, "with_any_date_bound": 1,
    }
    assert reference[list(undated)].to_dict("records") == [undated, dated]
    assert reference.set_index("id").at["undated", "timing_status"] == "undated"


def test_capability_report_distinguishes_unsupported_questions(tmp_path):
    pd.DataFrame(
        [
            {
                "state": "TX", "party": "D", "confirmed": True, "year": 2024,
                "subject": "", "sponsor_party": "D",
            }
        ]
    ).drop(columns=["subject", "sponsor_party"]).to_parquet(
        tmp_path / "platforms_2018_present.parquet"
    )
    pd.DataFrame(
        [{"state": "KY", "party": "R"}]
    ).to_parquet(tmp_path / "caucus_priorities.parquet")
    pd.DataFrame(
        [{"state": "TX", "sponsor_party": "D", "subject": "Elections"}]
    ).to_parquet(tmp_path / "bills.parquet")
    pd.DataFrame(
        [
            {
                "state": "TX", "party": "D", "n_attributed": 1,
                "n_procedural_excluded": 0,
            }
        ]
    ).to_csv(tmp_path / "bill_classification_coverage.csv", index=False)
    pd.DataFrame(
        [
            {
                "state": "TX", "party": "D", "stated_focus_reliable": True,
            }
        ]
    ).to_csv(tmp_path / "state_party_focus.csv", index=False)
    pd.DataFrame(
        [{"state": "TX", "party": "D", "n_election_bills": 1}]
    ).to_csv(tmp_path / "election_focus_by_state_party.csv", index=False)
    pd.DataFrame(
        [{"state": "TX", "party": "D", "n_confirmed": 1}]
    ).to_csv(tmp_path / "platform_gap_report.csv", index=False)

    report = build_capability_report(tmp_path).set_index("question")

    assert report.loc["Bill enactment/pass rates", "support"] == "unsupported"
    assert report.loc["Roll-call voting behavior", "support"] == "unsupported"
    assert report.loc["Policy stance or ideological direction", "support"] == "limited"
    assert report.loc["Current stated state-level agenda", "support"] == "supported"

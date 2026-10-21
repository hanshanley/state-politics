"""Reviewed full descriptions remain a separate, non-admitted evidence channel."""

import csv
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from state_politics.bills.study_description_evidence import (
    CHANNEL,
    LITERALS,
    build_inventory,
    description_disposition,
)
from state_politics.provenance import sha256_file


def bill(**changes):
    return {
        "bill_id": "b1",
        "state": "NY",
        "identifier": "K 1",
        "session_identifier": "2023-2024",
        "classification": "resolution",
        "from_organization_id": "house",
        "originating_chamber": "lower",
        "source_introduction_date": "",
        "window_disposition": "no_source_introduction_action",
        "source_filing_date": "",
        "filing_window_disposition": "no_source_filing_action",
        **changes,
    }


def action(**changes):
    return {
        "action_id": "a1",
        "bill_id": "b1",
        "state": "NY",
        "date": "2023-01-09",
        "description": "INTRODUCED",
        "classification": "",
        "organization_id": "house",
        "chamber": "lower",
        "order": 0,
        **changes,
    }


@pytest.mark.parametrize(
    "actions,changes,expected,day",
    [
        ([action()], {}, "in_window", "2023-01-09"),
        ([action(date="2024-12-31T23:30:00-06:00")], {}, "in_window", "2024-12-31"),
        ([action(date="2022-12-31")], {}, "before_window", "2022-12-31"),
        ([action(date="2025-01-01")], {}, "after_window", "2025-01-01"),
        ([action(date="2023-01-09garbage")], {}, "invalid_date", None),
        ([action(date="")], {}, "missing_date", None),
        ([action(date=None)], {}, "missing_date", None),
        ([action()], {"from_organization_id": ""}, "missing_originating_organization", None),
        ([action(organization_id="senate")], {}, "no_origin_literal_action", None),
        ([action(chamber="upper")], {}, "origin_chamber_unresolved", None),
        ([action()], {"originating_chamber": ""}, "unknown_originating_chamber", None),
        ([action(), action(action_id="a2")], {}, "multiple_origin_literal_actions", None),
        ([action(classification="introduction")], {}, "only_source_coded_literal_actions", None),
        ([], {}, "no_reviewed_literal_action", None),
    ],
)
def test_literal_dates_identity_and_ambiguities_are_not_repaired(actions, changes, expected, day):
    source_bill = bill(**changes)
    original_bill, original_actions = dict(source_bill), [dict(a) for a in actions]
    result = description_disposition(source_bill, actions, kind="introduction")
    assert result["description_introduction_disposition"] == expected
    assert result["description_introduction_candidate_date"] == day
    assert source_bill == original_bill
    assert actions == original_actions
    assert "source_introduction_date" not in result


def test_other_chamber_events_are_preserved_without_overriding_origin_or_inventing_codes():
    actions = [action(), action(action_id="opposite", organization_id="senate", chamber="upper")]
    result = description_disposition(bill(), actions, kind="introduction")
    assert json.loads(result["description_introduction_action_ids"]) == ["a1", "opposite"]
    assert result["description_introduction_n_origin_actions"] == 1
    assert result["description_introduction_candidate_date"] == "2023-01-09"
    assert all(a["classification"] == "" for a in actions)


@pytest.mark.parametrize(
    "state,text",
    [
        ("NY", "introduced"),
        ("NY", "INTRODUCED "),
        ("MA", "INTRODUCED"),
        ("MA", "Placed on file"),
        ("MA", "Read first and referred to committee"),
        ("ME", "Approved for introduction and ordered printed"),
        ("ME", "Not Presented."),
    ],
)
def test_nearby_words_or_other_states_are_not_literal_contracts(state, text):
    assert (state, text) not in LITERALS
    with pytest.raises(ValueError, match="reviewed description"):
        description_disposition(
            bill(state=state),
            [action(state=state, description=text)],
            kind="introduction",
        )


def test_reviewed_ma_petition_filing_is_not_an_introduction():
    a = action(state="MA", description="Petition filed")
    result = description_disposition(bill(state="MA"), [a], kind="petition_filing")
    assert result["description_petition_filing_candidate_date"] == "2023-01-09"
    with pytest.raises(ValueError, match="reviewed description"):
        description_disposition(bill(state="MA"), [a], kind="introduction")


def packet(base):
    window, filing = base / "window", base / "filing"
    window.mkdir()
    filing.mkdir()
    rows = [
        bill(),
        bill(bill_id="b2", state="MA", identifier="S 1", classification="bill"),
        bill(bill_id="b3", state="ME", identifier="LD 1", classification="bill"),
        bill(bill_id="b4", state="AK"),
    ]
    for path in [window / "bill_window_ledger.csv", filing / "bill_filing_evidence.csv"]:
        with path.open("x", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    source_actions = [
        action(),
        action(action_id="other", organization_id="senate", chamber="upper"),
        action(action_id="ma", bill_id="b2", state="MA", description="Petition filed"),
        action(action_id="me", bill_id="b3", state="ME", description="Approved for introduction"),
        action(action_id="coded", classification="introduction", date="2022-01-01"),
        action(action_id="ak", bill_id="b4", state="AK"),
    ]
    actions = base / "actions.parquet"
    pq.write_table(pa.Table.from_pylist(source_actions), actions)
    extraction_path = base / "extraction.json"
    extraction_path.write_text(
        json.dumps(
            {
                "status": "complete_extraction_not_source_certification",
                "artifacts": {
                    "bill_actions.parquet": {
                        "sha256": sha256_file(actions),
                        "rows": len(source_actions),
                    },
                },
            }
        )
    )
    window_manifest = {
        "status": "complete_source_window_inventory_not_analytical_admission",
        "window_start": "2023-01-01",
        "window_end": "2024-12-31",
        "inputs": {
            "bill_actions.parquet": {"sha256": sha256_file(actions)},
            "bill_extraction_manifest.json": {"sha256": sha256_file(extraction_path)},
        },
        "artifacts": {
            "bill_window_ledger.csv": {"sha256": sha256_file(window / "bill_window_ledger.csv")},
        },
    }
    (window / "manifest.json").write_text(json.dumps(window_manifest))
    (filing / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete_source_filing_inventory_not_native_or_analytical_certification",
                "window_start": "2023-01-01",
                "window_end": "2024-12-31",
                "inputs": {
                    "window_manifest": {"sha256": sha256_file(window / "manifest.json")},
                    "introduction_ledger": {
                        "sha256": sha256_file(window / "bill_window_ledger.csv"),
                    },
                    "actions": {"sha256": sha256_file(actions)},
                },
                "artifacts": {
                    "bill_filing_evidence.csv": {
                        "sha256": sha256_file(filing / "bill_filing_evidence.csv"),
                    },
                },
            }
        )
    )
    return filing, window, actions, extraction_path, rows, source_actions


def test_offline_packet_preserves_source_rows_exact_joins_and_unresolved_gaps(tmp_path):
    filing, window, actions, extraction, rows, source_actions = packet(tmp_path)
    out = tmp_path / "out"
    report = build_inventory(filing, window, actions, extraction, out)
    assert report["n_original_all_state_bill_contexts"] == 4
    assert report["n_scoped_bill_contexts"] == 3
    assert report["n_literal_actions"] == 4
    assert report["analytical_admission"] is False
    raw = pq.read_table(out / "literal_actions.parquet")
    assert raw.schema == pq.read_schema(actions)
    assert raw.to_pylist() == [source_actions[i] for i in [0, 1, 2, 4]]
    with (out / "candidate_bill_ledger.csv").open() as handle:
        saved = list(csv.DictReader(handle))
    assert [{key: row[key] for key in rows[0]} for row in saved] == rows[:3]
    assert saved[0]["source_channel"] == CHANNEL
    assert saved[0]["description_introduction_n_literal_actions"] == "3"
    assert saved[0]["description_introduction_n_uncoded_actions"] == "2"
    assert saved[0]["description_introduction_candidate_date"] == "2023-01-09"
    assert saved[1]["description_petition_filing_candidate_date"] == "2023-01-09"
    assert saved[2]["description_introduction_disposition"] == "no_reviewed_literal_action"
    with (out / "literal_action_evidence.csv").open() as handle:
        joined = list(csv.DictReader(handle))
    assert joined[1]["origin_identity_status"] == "other_or_missing_organization"
    assert joined[3]["is_uncoded_candidate"] == "False"
    assert joined[0]["bill_session_identifier"] == "2023-2024"
    assert joined[0]["classification"] == ""
    assert joined[0]["bill_classification"] == "resolution"
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["inputs_unchanged"] is True
    for name, binding in manifest["artifacts"].items():
        assert sha256_file(out / name) == binding["sha256"]
    with pytest.raises(FileExistsError):
        build_inventory(filing, window, actions, extraction, out)


def test_changed_raw_source_is_rejected_before_output_creation(tmp_path):
    filing, window, actions, extraction, _, _ = packet(tmp_path)
    pq.write_table(pa.Table.from_pylist([action(date="2024-01-01")]), actions)
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="lineage"):
        build_inventory(filing, window, actions, extraction, out)
    assert not out.exists()

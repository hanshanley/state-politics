"""Cycle inclusion must use source introduction evidence, not a plausible year."""

import csv
import json

import pandas as pd
import pytest

from state_politics.bills.study_window import build_inventory, introduction_disposition
from state_politics.provenance import sha256_file


def bill(**changes):
    return {
        "bill_id": "b1",
        "state": "NJ",
        "identifier": "S 1",
        "legislative_session_id": "session1",
        "session_identifier": "2022-2023",
        "session_name": "2022-2023 Regular Session",
        "session_start_date": "2022-01-11",
        "session_end_date": "2024-01-08",
        "from_organization_id": "senate",
        "originating_chamber": "upper",
        "classification": "bill",
        "first_action_date": "2023-01-01",
        **changes,
    }


def action(**changes):
    return {
        "action_id": "a1",
        "bill_id": "b1",
        "state": "NJ",
        "date": "2023-01-01",
        "classification": "introduction|referral-committee",
        "organization_id": "senate",
        "chamber": "upper",
        "description": "Introduced",
        "order": 0,
        **changes,
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2022-12-31", "source_introduction_before_window"),
        ("2023-01-01", "source_introduction_in_window"),
        ("2024-12-31T23:30:00-05:00", "source_introduction_in_window"),
        ("2025-01-01", "source_introduction_after_window"),
        ("2023-02-30", "invalid_origin_introduction_date"),
        ("2023-01-01garbage", "invalid_origin_introduction_date"),
        (None, "missing_origin_introduction_date"),
        ("", "missing_origin_introduction_date"),
        (20230101, "invalid_origin_introduction_date"),
    ],
)
def test_window_uses_complete_origin_date_and_source_local_day(value, expected):
    result = introduction_disposition(bill(), [action(date=value)])
    assert result["window_disposition"] == expected


def test_first_action_session_label_and_opposite_chamber_cannot_supply_filing_date():
    assert (
        introduction_disposition(
            bill(session_identifier="2023-2024"),
            [],
        )["window_disposition"]
        == "no_source_introduction_action"
    )
    other = action(action_id="a2", organization_id="house", chamber="lower", date="2024-01-01")
    result = introduction_disposition(bill(), [action(date="2022-12-31"), other])
    assert result["window_disposition"] == "source_introduction_before_window"
    assert result["n_introduction_actions"] == 2
    assert result["n_origin_introduction_actions"] == 1
    assert introduction_disposition(bill(), [other])["source_introduction_date"] is None


def test_duplicates_unknown_chambers_and_mismatched_joins_are_explicit():
    for second_date in ("2023-01-01", "2024-01-01"):
        result = introduction_disposition(
            bill(),
            [action(), action(action_id="a2", date=second_date)],
        )
        assert result["window_disposition"] == "multiple_origin_introduction_actions"
        assert result["source_introduction_date"] is None
        assert json.loads(result["origin_introduction_action_ids"]) == ["a1", "a2"]
    assert (
        introduction_disposition(
            bill(from_organization_id=None),
            [action()],
        )["window_disposition"]
        == "missing_originating_organization"
    )
    assert (
        introduction_disposition(
            bill(originating_chamber="unknown"),
            [action()],
        )["window_disposition"]
        == "unknown_originating_chamber"
    )
    assert (
        introduction_disposition(
            bill(),
            [action(chamber="lower")],
        )["window_disposition"]
        == "origin_introduction_chamber_unresolved"
    )
    for changes in ({"state": "NY"}, {"bill_id": "b2"}, {"classification": "reintroduction"}):
        with pytest.raises(ValueError, match="does not match"):
            introduction_disposition(bill(), [action(**changes)])


def inputs(tmp_path, *, actions=None, bills=None):
    data = tmp_path / "inputs"
    data.mkdir()
    source_bills = (
        bills
        if bills is not None
        else [
            bill(),
            bill(
                bill_id="b2", classification="resolution", session_identifier="2024 Special Session"
            ),
        ]
    )
    pd.DataFrame(source_bills).to_parquet(data / "bills.parquet", index=False)
    pd.DataFrame(
        actions
        if actions is not None
        else [
            action(),
            action(action_id="a2", bill_id="b2", classification="referral-committee"),
            action(action_id="a3", bill_id="b2", classification="reintroduction"),
        ]
    ).to_parquet(data / "bill_actions.parquet", index=False)
    manifest = {
        "status": "complete_extraction_not_source_certification",
        "artifacts": {
            name: {"sha256": sha256_file(data / name), "rows": rows}
            for name, rows in (
                ("bills.parquet", len(source_bills)),
                ("bill_actions.parquet", len(actions) if actions is not None else 3),
            )
        },
    }
    (data / "bill_extraction_manifest.json").write_text(json.dumps(manifest))
    return data


def test_persisted_inventory_preserves_full_population_types_and_raw_evidence(tmp_path):
    data = inputs(tmp_path)
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    out = tmp_path / "inventory"
    report = build_inventory(data, out)
    with (out / "bill_window_ledger.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == report["n_source_contexts"] == 2
    assert rows[0]["session_identifier"] == "2022-2023"
    assert rows[0]["window_disposition"] == "source_introduction_in_window"
    assert rows[1]["session_identifier"] == "2024 Special Session"
    assert rows[1]["classification"] == "resolution"
    assert rows[1]["window_disposition"] == "no_source_introduction_action"
    assert rows[1]["source_introduction_date"] == ""
    assert pd.read_parquet(out / "source_introduction_actions.parquet").to_dict("records") == [
        action(),
    ]
    assert len(report["states"]) == 50 and not report["analytical_admission"]
    assert {p.name: p.read_bytes() for p in data.iterdir()} == before
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["inputs_unchanged"] and manifest["status"].startswith("complete_")
    for name, binding in manifest["artifacts"].items():
        assert binding["sha256"] == sha256_file(out / name)
    with pytest.raises(FileExistsError):
        build_inventory(data, out)


@pytest.mark.parametrize(
    "actions",
    [
        [action(), action()],
        [action(bill_id="absent")],
        [action(state="NY")],
    ],
)
def test_bad_joins_leave_only_incomplete_inventory(tmp_path, actions):
    data = inputs(tmp_path, actions=actions)
    out = tmp_path / "inventory"
    with pytest.raises(ValueError):
        build_inventory(data, out)
    assert json.loads((out / "manifest.json").read_text())["status"] == "incomplete"


def test_unbound_extraction_is_rejected_before_output_creation(tmp_path):
    data = inputs(tmp_path)
    pd.DataFrame([bill()]).to_parquet(data / "bills.parquet", index=False)
    with pytest.raises(ValueError, match="binding mismatch"):
        build_inventory(data, tmp_path / "inventory")
    assert not (tmp_path / "inventory").exists()


def test_session_counts_do_not_merge_distinct_native_ids_with_identical_labels(tmp_path):
    data = inputs(
        tmp_path,
        bills=[bill(), bill(bill_id="b2", legislative_session_id="session2")],
        actions=[action(), action(action_id="a2", bill_id="b2")],
    )
    out = tmp_path / "inventory"
    build_inventory(data, out)
    with (out / "state_session_counts.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["legislative_session_id"] for row in rows} == {"session1", "session2"}
    assert [row["n_source_contexts"] for row in rows] == ["1", "1"]

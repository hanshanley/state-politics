"""Source-coded filings add evidence without guessing introduction dates."""

import json

import pandas as pd
import pytest

from state_politics.bills.study_filing import build_inventory
from state_politics.bills.study_window import _STATES, source_event_disposition
from state_politics.provenance import sha256_file


def bill():
    return {
        "bill_id": "b1",
        "state": "AK",
        "identifier": "HB 1",
        "session_identifier": "2023",
        "classification": "bill",
        "from_organization_id": "house",
        "originating_chamber": "lower",
        "source_introduction_date": "",
        "window_disposition": "no_source_introduction_action",
    }


def action(**changes):
    return {
        "action_id": "a1",
        "bill_id": "b1",
        "state": "AK",
        "classification": "filing",
        "organization_id": "house",
        "chamber": "lower",
        "date": "2023-01-09",
        "description": "Prefile released",
        "order": 0,
        **changes,
    }


def test_explicit_filing_uses_its_own_origin_date_not_introduction_or_session():
    result = source_event_disposition(bill(), [action()], event_class="filing")
    assert result["source_filing_date"] == "2023-01-09"
    assert result["window_disposition"] == "source_filing_in_window"
    assert result["n_filing_actions"] == 1
    assert "source_introduction_date" not in result
    with pytest.raises(ValueError, match="classification"):
        source_event_disposition(bill(), [action(classification="reading-1")], event_class="filing")


@pytest.mark.parametrize(
    "actions,expected",
    [
        ([], "no_source_filing_action"),
        ([action(date="2022-12-31")], "source_filing_before_window"),
        ([action(date="2024-12-31T23:30:00-06:00")], "source_filing_in_window"),
        ([action(date="2025-01-01")], "source_filing_after_window"),
        ([action(date="2023-01-01garbage")], "invalid_origin_filing_date"),
        ([action(organization_id="senate", chamber="upper")], "no_origin_filing_action"),
        ([action(), action(action_id="a2")], "multiple_origin_filing_actions"),
    ],
)
def test_filing_identity_ambiguity_and_dates_are_not_silently_repaired(actions, expected):
    assert (
        source_event_disposition(bill(), actions, event_class="filing")["window_disposition"]
        == expected
    )


def packet(tmp_path):
    window = tmp_path / "window"
    window.mkdir()
    rows = [bill(), {**bill(), "bill_id": "b2", "identifier": "HB 2"}]
    pd.DataFrame(rows).to_csv(window / "bill_window_ledger.csv", index=False)
    actions = tmp_path / "actions.parquet"
    pd.DataFrame(
        [
            action(),
            action(
                action_id="a2",
                bill_id="b2",
                classification="reading-1",
                description="Introduced but no filing classification",
            ),
        ]
    ).to_parquet(actions, index=False)
    (window / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete_source_window_inventory_not_analytical_admission",
                "window_start": "2023-01-01",
                "window_end": "2024-12-31",
                "inputs": {"bill_actions.parquet": {"sha256": sha256_file(actions)}},
                "artifacts": {
                    "bill_window_ledger.csv": {
                        "sha256": sha256_file(window / "bill_window_ledger.csv"),
                    }
                },
            }
        )
    )
    matrix = tmp_path / "matrix"
    matrix.mkdir()
    pd.DataFrame({"state": sorted(_STATES), "n_source_in_window": 0}).to_csv(
        matrix / "state_matrix.csv",
        index=False,
    )
    (matrix / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete_all_state_triage_not_native_coverage_or_analytical_admission",
                "inputs": {"ledger": {"sha256": sha256_file(window / "bill_window_ledger.csv")}},
                "artifacts": {
                    "state_matrix.csv": {
                        "sha256": sha256_file(matrix / "state_matrix.csv"),
                    }
                },
            }
        )
    )
    return window, actions, rows, matrix


def test_complete_filing_ledger_preserves_every_original_field_and_raw_action(tmp_path):
    window, actions, rows, matrix = packet(tmp_path)
    out = tmp_path / "out"
    report = build_inventory(window, actions, out, matrix_dir=matrix)
    assert report["n_contexts"] == 2
    assert report["n_source_filing_actions"] == 1
    assert report["n_filing_in_window_without_introduction_date"] == 1
    assert len(report["states"]) == 50
    combined = pd.read_csv(out / "state_matrix.csv").set_index("state")
    assert combined.loc["AK", "n_filing_or_introduction_in_window"] == 1
    saved = pd.read_csv(out / "bill_filing_evidence.csv", dtype=str, keep_default_na=False)
    assert saved[list(rows[0])].to_dict("records") == rows
    assert saved.loc[saved.bill_id.eq("b2"), "filing_window_disposition"].iloc[0] == (
        "no_source_filing_action"
    )
    raw = pd.read_parquet(out / "source_filing_actions.parquet")
    assert raw.to_dict("records") == [action()]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["inputs_unchanged"]
    for name, binding in manifest["artifacts"].items():
        assert sha256_file(out / name) == binding["sha256"]
    with pytest.raises(FileExistsError):
        build_inventory(window, actions, out, matrix_dir=matrix)


def test_wrong_bound_actions_fail_before_output_creation(tmp_path):
    window, actions, _, matrix = packet(tmp_path)
    pd.DataFrame([action(date="2024-01-01")]).to_parquet(actions, index=False)
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="original bound action"):
        build_inventory(window, actions, out, matrix_dir=matrix)
    assert not out.exists()

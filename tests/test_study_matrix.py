"""Shared national triage preserves accepted scopes and unknown evidence."""

import json
from pathlib import Path

import pandas as pd
import pytest

from state_politics.bills.study_matrix import build_matrix, read_tracker, reconcile_matrix
from state_politics.bills.study_window import _STATES
from state_politics.provenance import sha256_file


def fixture(tmp_path):
    tracker_path = tmp_path / "tracker.md"
    statuses = {"CA": "Closed scope", "FL": "Partial", "GA": "Blocked"}
    tracker_path.write_text(
        "\n".join(
            f"| State ({state}) | {statuses.get(state, 'Inventory')} | Named gap. | Evidence. |"
            for state in sorted(_STATES)
        )
    )
    ledger = pd.DataFrame(
        [
            {
                "bill_id": bill,
                "state": state,
                "identifier": "HB 1",
                "session_identifier": session,
                "legislative_session_id": f"{state}-{session}",
                "session_name": session,
                "originating_chamber": chamber,
                "classification": "bill",
                "window_disposition": disposition,
            }
            for bill, state, session, chamber, disposition in [
                ("fl-old", "FL", "2019", "lower", "source_introduction_before_window"),
                ("fl-now", "FL", "2023", "upper", "source_introduction_in_window"),
                ("fl-unknown", "FL", "2024", "lower", "no_source_introduction_action"),
                ("ca-now", "CA", "2023", "lower", "source_introduction_in_window"),
            ]
        ]
    )
    coverage = ledger[["bill_id", "state", "identifier", "session_identifier"]].assign(
        n_version_links=[1, 2, 0, 1],
        n_usable_url_links=[1, 2, 0, 0],
        n_original_note_links=[1, 1, 0, 0],
    )
    return tracker_path, ledger, coverage


def test_all_states_no_fabricated_text_or_dates_and_closed_scope_not_redispatched(tmp_path):
    tracker_path, ledger, coverage = fixture(tmp_path)
    matrix, groups, queue = reconcile_matrix(ledger, coverage, read_tracker(tracker_path))
    assert len(matrix) == 50
    assert groups["n_contexts"].sum() == len(ledger)
    assert groups["n_reference_links"].sum() == 4
    by_state = matrix.set_index("state")
    assert by_state.loc["FL", "n_source_in_window"] == 1
    assert by_state.loc["FL", "n_in_window_upper"] == 1
    assert by_state.loc["FL", "n_in_window_lower"] == 0
    assert by_state.loc["FL", "n_unresolved_dates_wider_history"] == 1
    assert by_state.loc["FL", "n_in_window_with_original_note"] == 1
    assert by_state.loc["AL", "date_evidence"] == "no_observed_dates_not_zero_activity"
    assert by_state.loc["CA", "next_action"] == "reuse_accepted_scope"
    assert "CA" not in queue["state"].tolist()
    assert by_state.loc["GA", "next_action"] == "resolve_blocker_without_collection"
    assert matrix["recovered_cycle_text_count"].isna().all()
    assert matrix["native_cycle_denominator"].isna().all()
    assert not matrix["collection_authorized"].any()
    assert not matrix["analytical_admission"].any()


@pytest.mark.parametrize("defect", ["missing", "duplicate", "status"])
def test_tracker_drift_fails_instead_of_silently_dropping_states(tmp_path, defect):
    path, _, _ = fixture(tmp_path)
    lines = path.read_text().splitlines()
    if defect == "missing":
        lines.pop()
    elif defect == "duplicate":
        lines.append(lines[0])
    else:
        lines[0] = lines[0].replace("Inventory", "Complete")
    path.write_text("\n".join(lines))
    with pytest.raises(ValueError, match="exactly the 50 states"):
        read_tracker(path)


@pytest.mark.parametrize("defect", ["nullable", "session", "population", "count", "disposition"])
def test_shared_context_gates_reject_corrupt_inputs(tmp_path, defect):
    path, ledger, coverage = fixture(tmp_path)
    if defect == "nullable":
        coverage["identifier"] = coverage["identifier"].astype("string")
        coverage.loc[0, "identifier"] = pd.NA
    elif defect == "session":
        coverage.loc[0, "session_identifier"] = "2023"
    elif defect == "population":
        coverage = coverage.iloc[1:]
    elif defect == "count":
        coverage.loc[0, "n_original_note_links"] = 2
    else:
        ledger.loc[0, "window_disposition"] = "guessed_from_url"
    with pytest.raises(ValueError):
        reconcile_matrix(ledger, coverage, read_tracker(path))


def packet(tmp_path):
    tracker, ledger, coverage = fixture(tmp_path)
    window, reference = (tmp_path / name for name in ("window", "reference"))
    window.mkdir()
    reference.mkdir()
    ledger.to_csv(window / "bill_window_ledger.csv", index=False)
    (window / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete_source_window_inventory_not_analytical_admission",
                "window_start": "2023-01-01",
                "window_end": "2024-12-31",
                "artifacts": {
                    "bill_window_ledger.csv": {
                        "sha256": sha256_file(window / "bill_window_ledger.csv"),
                    }
                },
                "inputs": {"bill_extraction_manifest.json": {"sha256": "same-extraction"}},
            }
        )
    )
    coverage.to_parquet(reference / "bill_document_coverage.parquet", index=False)
    (reference / "report.json").write_text(
        json.dumps(
            {
                "status": "reference_inventory_not_text_certification",
                "extraction_manifest_sha256": "same-extraction",
                "n_source_context_bills": 4,
            }
        )
    )
    (reference / "manifest.json").write_text(
        json.dumps(
            {
                "files": {p.name: sha256_file(p) for p in reference.iterdir()},
            }
        )
    )
    return window, reference, tracker


def test_persistent_matrix_is_bound_and_refuses_overwrite(tmp_path):
    window, reference, tracker = packet(tmp_path)
    out = tmp_path / "output"
    report = build_matrix(window, reference, tracker, out)
    assert report["n_states"] == 50
    assert report["n_source_in_window"] == 2
    assert report["n_gap_queue_states"] == 49
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["inputs_unchanged"]
    for name, binding in manifest["artifacts"].items():
        assert binding["sha256"] == sha256_file(out / name)
    assert len(pd.read_csv(out / "state_matrix.csv")) == 50
    before = manifest_path.read_bytes()
    with pytest.raises(FileExistsError):
        build_matrix(window, reference, tracker, out)
    assert manifest_path.read_bytes() == before


@pytest.mark.parametrize("defect", ["checksum", "lineage", "population"])
def test_bad_bindings_fail_closed_and_leave_no_success_manifest(tmp_path, defect):
    window, reference, tracker = packet(tmp_path)
    report_path = reference / "report.json"
    report = json.loads(report_path.read_text())
    report["extraction_manifest_sha256"] = "other-extraction"
    if defect == "population":
        report["extraction_manifest_sha256"] = "same-extraction"
        report["n_source_context_bills"] = 5
    report_path.write_text(json.dumps(report))
    if defect != "checksum":
        manifest_path = reference / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][report_path.name] = sha256_file(report_path)
        manifest_path.write_text(json.dumps(manifest))
    out = tmp_path / "output"
    with pytest.raises(ValueError):
        build_matrix(window, reference, tracker, out)
    if out.exists():
        assert json.loads((out / "manifest.json").read_text())["status"] == "incomplete"
    assert not (out / "report.json").exists()


def test_committed_dispatch_tracker_has_exact_state_registry():
    tracker = read_tracker(Path("docs/STATE_PROGRESS.md"))
    assert set(tracker["state"]) == _STATES

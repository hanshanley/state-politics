"""Offline recovery tests; all fixtures live under data/, never temporary directories."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from state_politics.analysis import cycle_outcome_evidence as recovery
from state_politics.analysis.cycle_outcome_evidence import (
    APPROVALS,
    CHANNELS,
    ROOT,
    STAGES,
    STATES,
    TABLES,
    build_evidence,
    main,
    verify_packet,
)
from state_politics.bills.outcomes import recorded_outcome
from state_politics.provenance import sha256_file


def _write_json(path: Path, value: dict):
    path.write_text(json.dumps(value), encoding="utf-8")


def _bind(source: Path, cohort: Path):
    extraction = {
        "status": "complete_extraction_not_source_certification",
        "source_sha256": "a" * 64,
        "source_bytes": 123,
        "analysis_cutoff": None,
        "artifacts": {
            f"{name}.parquet": {
                "sha256": sha256_file(source / f"{name}.parquet"),
                "rows": pq.ParquetFile(source / f"{name}.parquet").metadata.num_rows,
            }
            for name in TABLES
        },
    }
    _write_json(source / "bill_extraction_manifest.json", extraction)
    _write_json(cohort / "manifest.json", {
        "status": "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted",
        "analytical_admission": False, "model_input_approved": False,
        "inputs": {
            "extraction_manifest": {
                "sha256": sha256_file(source / "bill_extraction_manifest.json"),
            },
            "bills": extraction["artifacts"]["bills.parquet"],
        },
        "artifacts": {
            name: {"sha256": sha256_file(cohort / name)}
            for name in ("bill_evidence.parquet", "state_matrix.csv")
        },
    })


@pytest.fixture
def retained():
    root = ROOT / "data/test-fixtures" / f"cycle-outcome-evidence-{uuid4().hex}"
    source, cohort = root / "source", root / "cohort"
    source.mkdir(parents=True)
    cohort.mkdir()
    specifications = [
        ("b1", "WA", "HB 1", "bill", "Original title", False, False, CHANNELS[0]),
        ("b2", "NY", "HB 1", "bill", "No retained actions", False, False, CHANNELS[1]),
        ("b3", "IL", "HB 1", "bill", "Unclassified actions", False, False, CHANNELS[1]),
        ("b4", "TX", "HR 1", "resolution", "Resolution title", False, False, CHANNELS[0]),
        ("b5", "MT", "LC 123", "bill", "Draft request", False, True, CHANNELS[0]),
        ("b6", "CA", "AB 1", "bill", "Passage chamber unresolved", False, False, CHANNELS[0]),
        ("b7", "WA", "HB 7", "bill", "bill 4 for system testing", True, False, CHANNELS[0]),
        ("b8", "NE", "LB 8", "proposed bill", "Other source type", False, False, CHANNELS[0]),
        ("b9", "NY", "SB 9", "bill", "Recorded withdrawal", False, False, CHANNELS[2]),
    ]
    actions = []
    for bill_id, classes, chamber, date in (
        ("b1", "introduction", "lower", "2023-01-02"),
        ("b1", "passage", "lower", "2023-06-01"),
        ("b1", "passage", "upper", "2024-02-01"),
        ("b1", "executive-signature", "legislature", "2025-01-02"),
        ("b3", "", "lower", "2024-01-02"),
        ("b3", None, "lower", None),
        ("b4", "executive-signature", "legislature", "2023-02-01"),
        ("b5", "executive-signature", "legislature", "2023-02-01"),
        ("b6", "passage", "unknown", "2023-02-01"),
        ("b7", "introduction", "lower", "2023-02-01"),
        ("b8", "referral-committee", "legislature", "2023-02-01"),
        ("b9", "withdrawal", "upper", "2024-02-01"),
    ):
        state = next(spec[1] for spec in specifications if spec[0] == bill_id)
        actions.append({
            "action_id": f"a{len(actions)}", "bill_id": bill_id, "state": state,
            "date": date, "description": "Original action text", "classification": classes,
            "organization_id": "organization", "chamber": chamber, "order": len(actions),
        })
    votes = [{
        "vote_id": "v1", "bill_id": "b1", "state": "WA", "start_date": "2024-01-02",
        "identifier": "1", "motion_text": "Original motion", "motion_classification": "passage",
        "result": "pass", "organization_id": "organization", "chamber": "lower",
        "bill_action_id": "a1", "order": 0,
    }]
    sponsorships = []
    for spec in specifications:
        bill_id, state = spec[:2]
        sponsorships.append({
            "sponsorship_id": f"s-{bill_id}", "bill_id": bill_id, "state": state,
            "person_id": f"p-{bill_id}", "sponsor_name": "Original sponsor",
            "entity_type": "person", "organization_id": None, "primary": True,
            "classification": "primary", "party": "nonpartisan" if state == "NE" else "unknown",
            "party_attribution_date": "2023-01-02",
            "party_attribution_date_basis": "first_action_proxy",
            "party_resolution": "nonpartisan_legislature" if state == "NE" else "unresolved",
        })
    sponsorships.append({
        **sponsorships[0], "sponsorship_id": "partial-dated-D", "person_id": "partial-person",
        "primary": False, "party": "D", "party_resolution": "active_membership",
    })
    bills, candidates = [], []
    for spec in specifications:
        bill_id, state, identifier, kind, title, test, draft, scope = spec
        selected = [row for row in actions if row["bill_id"] == bill_id]
        classes = {value for row in selected for value in (row["classification"] or "").split("|")
                   if value}
        passage = {row["chamber"] for row in selected if row["classification"] == "passage"}
        sponsors = [row for row in sponsorships if row["bill_id"] == bill_id]
        primary = [row for row in sponsors if row["primary"]]
        bills.append({
            "bill_id": bill_id, "state": state, "identifier": identifier, "classification": kind,
            "classification_raw": f'{{"{kind}"}}', "title": title,
            "session_identifier": "spans-2022-2025", "session_name": "Original session name",
            "session_start_date": "2022-01-01", "session_end_date": None,
            "legislative_session_id": f"session-{state}", "year": 2022,
            "first_action_date": "2023-01-02", "latest_action_date": "2025-01-02",
            "originating_chamber": "legislature" if state == "NE" else "lower",
            "from_organization_id": "organization",
            "sponsor_party": "nonpartisan" if state == "NE" else "unknown",
            "sponsor_attribution_basis": "primary", "party_attribution_date": "2023-01-02",
            "party_attribution_date_basis": "first_action_proxy",
            "n_sponsors": len(sponsors), "n_primary_sponsors": len(primary),
            "n_unresolved_primary_sponsors": sum(row["party"] == "unknown" for row in primary),
            "n_actions": len(selected), "action_classifications": "|".join(sorted(classes)),
            "passage_chambers": "|".join(sorted(passage)), "committee_passage": False,
            "recorded_outcome": "no_action_data" if bill_id == "b3" else recorded_outcome(
                classes, passage, n_actions=len(selected),
            ),
            "recorded_enacted": "executive-signature" in classes,
            "n_vote_events": int(bill_id == "b1"), "n_passage_votes": int(bill_id == "b1"),
            "n_passed_votes": int(bill_id == "b1"), "n_failed_votes": 0,
        })
        candidates.append({
            **{key: bills[-1][key] for key in (
                "bill_id", "state", "identifier", "classification", "title",
                "session_identifier", "session_name", "session_start_date", "session_end_date",
                "legislative_session_id", "first_action_date", "originating_chamber",
                "from_organization_id",
            )},
            "source_introduction_date": "2023-01-02" if scope == CHANNELS[0] else "",
            "source_filing_date": "", "native_introduction_date": (
                "2024-01-02" if scope == CHANNELS[1] else None
            ),
            "description_introduction_candidate_date": (
                "2024-01-02" if scope == CHANNELS[2] else None
            ),
            "description_petition_filing_candidate_date": None,
            "source_event_in_window": scope == CHANNELS[0],
            "native_introduction_in_window": scope == CHANNELS[1],
            "description_event_in_window": scope == CHANNELS[2], "cohort_scope": scope,
            "source_test_record": test, "source_draft_request": draft,
            **APPROVALS,
        })
    tables = {
        "bills": bills, "bill_actions": actions, "vote_events": votes,
        "vote_counts": [{
            "vote_event_id": "v1", "bill_id": "b1", "state": "WA", "option": option, "value": value,
        } for option, value in (("yes", 3), ("no", 2))],
        "vote_party_counts": [{
            "vote_event_id": "v1", "bill_id": "b1", "state": "WA",
            "sponsor_party": "unknown", "voter_party": party, "option": "yes", "n_votes": count,
        } for party, count in (("D", 1), ("unknown", 2))],
        "bill_sponsorships": sponsorships,
    }
    bills.append({
        **bills[0], "bill_id": "outside", "n_actions": 1, "n_vote_events": 0,
        "n_passage_votes": 0, "n_passed_votes": 0, "n_sponsors": 0,
        "n_primary_sponsors": 0, "n_unresolved_primary_sponsors": 0,
        "action_classifications": "introduction", "passage_chambers": "",
        "recorded_outcome": "introduced_or_pending", "recorded_enacted": False,
    })
    actions.append({**actions[0], "bill_id": "outside", "action_id": "outside-action"})
    for name, records in tables.items():
        pq.write_table(pa.Table.from_pylist(records), source / f"{name}.parquet")
    pq.write_table(pa.Table.from_pylist(candidates), cohort / "bill_evidence.parquet")
    matrix = []
    for state in STATES:
        rows = [row for row in candidates if row["state"] == state]
        counts = Counter(row["cohort_scope"] for row in rows)
        matrix.append({
            "state": state, "state_name": state, "original_unknown": "unknown",
            "n_cycle_evidence_candidate_contexts": len(rows),
            "n_filing_or_introduction_in_window": counts[CHANNELS[0]],
            "n_native_only_scope_candidates": counts[CHANNELS[1]],
            "n_description_only_scope_candidates": counts[CHANNELS[2]],
        })
    pd.DataFrame(matrix).to_csv(cohort / "state_matrix.csv", index=False)
    _bind(source, cohort)
    try:
        yield root, source, cohort
    finally:
        shutil.rmtree(root)


def test_recovers_actual_records_without_party_or_date_substitution(retained):
    root, source, cohort = retained
    hashes = {file: sha256_file(file) for folder in (source, cohort) for file in folder.iterdir()}
    report = build_evidence(source, cohort, root / "packet", plots=False)
    out = root / "packet"
    frame = pd.read_parquet(out / "bill_context_evidence.parquet").set_index("bill_id")
    assert len(frame) == 9
    assert report["cohort"]["date_channels"] == dict(zip(CHANNELS, (6, 2, 1), strict=True))
    assert frame.loc["b1", "recorded_stage"] == "signed"
    assert frame.loc["b1", "n_after_cycle_actions"] == 1
    assert frame.loc["b2", "recorded_stage"] == "no_action_data"
    assert frame.loc["b3", "recorded_stage"] == "action_stage_unclassified"
    assert frame.loc["b3", "source_bill__recorded_outcome"] == "no_action_data"
    assert frame.loc["b3", "n_null_classification_actions"] == 1
    assert frame.loc["b3", "n_empty_classification_actions"] == 1
    assert frame.loc["b3", "n_missing_date_actions"] == 1
    assert frame.loc["b6", "n_unknown_chamber_passage_actions"] == 1
    assert frame.loc["b6", "observed_passage_chambers"] == "unknown"
    assert frame.loc["b9", "recorded_stage"] == "recorded_failure_or_withdrawal"
    assert frame.loc["b5", "measure_scope"] == "source_draft_request"
    assert frame.loc["b7", "measure_scope"] == "source_test_record"
    assert not frame.loc[["b4", "b5", "b7", "b8"], "law_eligible"].any()
    assert frame.loc["b1", "sponsor_party_bucket"] == "unknown"
    assert frame.loc["b1", "n_D_sponsorships"] == 1
    assert frame.loc["b1", "source_bill__year"] == 2022
    assert frame.loc["b8", "source_sponsor_party"] == "nonpartisan"
    assert frame.loc["b8", "sponsor_party_bucket"] == "other"
    assert report["party"]["comparison_performed"] is False
    assert report["party"]["source_bill_labels"] == {"unknown": 8, "nonpartisan": 1}
    assert report["party"]["n_source_person_votes"] == 3
    assert report["party"]["n_known_party_person_votes"] == 1
    assert report["party"]["sponsorship_resolution_reason_retained"] is False
    assert frame.certified_final_legal_disposition.isna().all()
    assert all(frame[field].eq(False).all() for field in APPROVALS)
    assert report["n_legacy_missing_action_labels_corrected"] == 1
    assert report["raw_selected_rows"]["bill_actions"] == 12
    assert "outside" not in pd.read_parquet(out / "bill_actions.parquet").bill_id.tolist()
    assert all(sha256_file(file) == digest for file, digest in hashes.items())
    original = pq.read_table(cohort / "bill_evidence.parquet")
    actual = pq.read_table(out / "bill_context_evidence.parquet")
    assert actual.select(original.column_names).equals(original)
    assert (out / "primary_state_matrix.csv").read_bytes() == (
        cohort / "state_matrix.csv"
    ).read_bytes()
    assert verify_packet(out)["verified"] is True
    with pytest.raises(FileExistsError, match="new evidence output"):
        build_evidence(source, cohort, out, plots=False)


def test_complete_zero_denominator_coverage_is_not_zero_success(retained):
    root, source, cohort = retained
    build_evidence(source, cohort, root / "packet", plots=False)
    out = root / "packet"
    state = pd.read_csv(out / "state_coverage.csv").set_index("state")
    assert len(state) == 50
    assert state.loc["AL", "n_contexts"] == 0
    assert pd.isna(state.loc["AL", "action_availability"])
    stages = pd.read_csv(out / "state_recorded_stages.csv")
    assert len(stages) == 50 * len(STAGES) * 2
    assert stages.loc[stages.state.eq("AL"), "share"].isna().all()
    cubes = pd.read_csv(out / "state_chamber_type_coverage.csv")
    assert set(cubes.state) == set(STATES)
    assert not cubes.duplicated(["state", "originating_chamber", "classification_label"]).any()
    assert cubes.n_contexts.sum() == 9
    assert cubes.certified_final_legal_disposition_availability.isna().all()
    assert set(pd.read_csv(out / "sponsor_party_availability.csv").source_party_bucket) == {
        "D", "R", "other", "unknown",
    }


@pytest.mark.parametrize("damage", [
    "checksum", "duplicate-candidate", "candidate-identity", "action-state", "action-count",
    "action-duplicate", "malformed-date", "vote-join", "negative-count", "channel",
    "approval", "matrix",
])
def test_fails_explicitly_on_unbound_or_inconsistent_source(retained, damage):
    root, source, cohort = retained
    if damage == "checksum":
        with (source / "bill_actions.parquet").open("ab") as stream:
            stream.write(b"changed source")
        pattern = "SHA-256"
    else:
        path = cohort / "bill_evidence.parquet"
        frame = pd.read_parquet(path)
        pattern = "."
        if damage == "duplicate-candidate":
            frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
            pattern = "unique bill_id"
        elif damage == "candidate-identity":
            frame.loc[0, "identifier"] = "Wrong original identifier"
            pattern = "candidate/source mismatch"
        elif damage == "channel":
            frame.loc[0, "source_introduction_date"] = "2022-01-02"
            pattern = "date/channel mismatch"
        elif damage == "approval":
            frame.loc[0, "analytical_admission"] = True
            pattern = "approval"
        elif damage == "matrix":
            path = cohort / "state_matrix.csv"
            frame = pd.read_csv(path)
            frame.loc[0, "n_cycle_evidence_candidate_contexts"] = 2
            pattern = "multiplicity mismatch"
        else:
            table = "vote_counts" if damage in {"vote-join", "negative-count"} else (
                "bills" if damage == "action-count" else "bill_actions"
            )
            path = source / f"{table}.parquet"
            frame = pd.read_parquet(path)
            if damage == "action-state":
                frame.loc[0, "state"] = "NY"
                pattern = "source-context state mismatch"
            elif damage == "action-count":
                frame.loc[0, "n_actions"] += 1
                pattern = "count mismatch"
            elif damage == "action-duplicate":
                frame.loc[1, "action_id"] = frame.loc[0, "action_id"]
                pattern = "duplicate source action_id"
            elif damage == "malformed-date":
                frame.loc[0, "date"] = "2024-bogus"
                pattern = "malformed source event date"
            elif damage == "vote-join":
                frame.loc[0, "vote_event_id"] = "absent"
                pattern = "exact identity mismatch"
            elif damage == "negative-count":
                frame.loc[0, "value"] = -1
                pattern = "nonnegative"
        if path.suffix == ".csv":
            frame.to_csv(path, index=False)
        else:
            frame.to_parquet(path, index=False)
        _bind(source, cohort)
    with pytest.raises(ValueError, match=pattern):
        build_evidence(source, cohort, root / "packet", plots=False)


def test_detects_inputs_changed_during_recovery(retained, monkeypatch):
    root, source, cohort = retained
    original = recovery._write_summaries

    def changed_input(frame, out):
        result = original(frame, out)
        with (source / "bill_actions.parquet").open("ab") as stream:
            stream.write(b"changed during recovery")
        return result

    monkeypatch.setattr(recovery, "_write_summaries", changed_input)
    with pytest.raises(ValueError, match="input changed during evidence recovery"):
        build_evidence(source, cohort, root / "packet", plots=False)
    manifest = json.loads((root / "packet/manifest.json").read_text())
    assert manifest["status"] == "building_not_complete"


def test_actual_graph_pairs_and_cli_verification(retained, capsys, monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    root, source, cohort = retained
    figures = []
    close = plt.close

    def capture(figure=None):
        if hasattr(figure, "axes"):
            figures.append(figure)
        close(figure)

    monkeypatch.setattr(plt, "close", capture)
    report = build_evidence(source, cohort, root / "packet", plots=True)
    assert len(report["graph_files"]) == 4
    for filename in report["graph_files"]:
        assert (root / "packet" / filename).stat().st_size > 1000
    state_figure = figures[-1]
    canvas = FigureCanvasAgg(state_figure)
    canvas.draw()
    renderer = canvas.get_renderer()
    legend_bounds = state_figure.legends[0].get_window_extent(renderer)
    label_bounds = state_figure.axes[0].xaxis.label.get_window_extent(renderer)
    note_bounds = state_figure.texts[-1].get_window_extent(renderer)
    assert label_bounds.y0 > legend_bounds.y1
    assert legend_bounds.y0 > note_bounds.y1
    assert main(["--verify-packet", str(root / "packet")]) == 0
    assert json.loads(capsys.readouterr().out)["verified"] is True
    with (root / "packet/state_coverage.csv").open("a") as stream:
        stream.write("changed")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_packet(root / "packet")

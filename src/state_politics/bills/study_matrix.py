"""Build one offline 50-state evidence matrix and gap queue for the selected cycle."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from ..provenance import utc_now_iso
from .study_sources import _matching_identity, _unique
from .study_window import _STATES, END, START, _snapshot

_IN_WINDOW = "source_introduction_in_window"
_BEFORE = "source_introduction_before_window"
_AFTER = "source_introduction_after_window"
_UNRESOLVED = {
    "no_source_introduction_action",
    "missing_originating_organization",
    "no_origin_introduction_action",
    "multiple_origin_introduction_actions",
    "unknown_originating_chamber",
    "origin_introduction_chamber_unresolved",
    "missing_origin_introduction_date",
    "invalid_origin_introduction_date",
}
_ACTIONS = {
    "Closed scope": "reuse_accepted_scope",
    "Partial": "close_named_gap",
    "Inventory": "establish_native_cohort",
    "Blocked": "resolve_blocker_without_collection",
    "In progress": "continue_existing_owner",
}
_COUNTS = ["n_version_links", "n_usable_url_links", "n_original_note_links"]
_GROUPS = [
    "state",
    "legislative_session_id",
    "session_identifier",
    "session_name",
    "originating_chamber",
    "classification",
    "window_disposition",
]
_STATUS = "complete_all_state_triage_not_native_coverage_or_analytical_admission"


def read_tracker(path: Path) -> pd.DataFrame:
    """Read the current dispatch table, never historical task/process messages."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) != 6:
            continue
        match = re.fullmatch(r"(.+) \(([A-Z]{2})\)", cells[1])
        if match:
            rows.append(
                {
                    "state": match[2],
                    "state_name": match[1],
                    "legislative_status": cells[2],
                    "remaining_scope": cells[3],
                    "accepted_evidence": cells[4],
                }
            )
    tracker = pd.DataFrame(rows)
    if (
        tracker.empty
        or tracker["state"].duplicated().any()
        or set(tracker["state"]) != _STATES
        or not tracker["legislative_status"].isin(_ACTIONS).all()
        or tracker[["remaining_scope", "accepted_evidence"]].eq("").any().any()
    ):
        raise ValueError("tracker must contain exactly the 50 states with valid statuses/evidence")
    return tracker.sort_values("state").reset_index(drop=True)


def reconcile_matrix(
    ledger: pd.DataFrame,
    coverage: pd.DataFrame,
    tracker: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Aggregate exact context joins; observed dates and URLs never become native coverage."""
    for frame in (ledger, coverage):
        _unique(frame, "bill_id")
    if set(ledger["bill_id"]) != set(coverage["bill_id"]):
        raise ValueError("coverage must account for the exact national ledger population")
    if not ledger["state"].isin(tracker["state"]).all():
        raise ValueError("ledger contains a state absent from the tracker")
    _matching_identity(coverage, ledger)
    if not ledger["window_disposition"].isin({_IN_WINDOW, _BEFORE, _AFTER} | _UNRESOLVED).all():
        raise ValueError("unrecognized source-date disposition")
    for column in _COUNTS:
        values = coverage[column]
        if (
            not pd.api.types.is_integer_dtype(values.dtype)
            or values.isna().any()
            or values.lt(0).any()
        ):
            raise ValueError(f"nonnegative integer coverage counts required: {column}")
    if any(coverage[c].gt(coverage["n_version_links"]).any() for c in _COUNTS[1:]):
        raise ValueError("coverage subset counts exceed reference count")
    joined = ledger.merge(
        coverage[["bill_id", *_COUNTS]],
        on="bill_id",
        validate="one_to_one",
    )
    groups = (
        joined.groupby(_GROUPS, dropna=False)
        .agg(
            n_contexts=("bill_id", "size"),
            n_reference_links=("n_version_links", "sum"),
            n_usable_url_links=("n_usable_url_links", "sum"),
            n_original_note_links=("n_original_note_links", "sum"),
            n_contexts_with_reference=("n_version_links", lambda s: int(s.gt(0).sum())),
            n_contexts_with_usable_url=("n_usable_url_links", lambda s: int(s.gt(0).sum())),
            n_contexts_with_original_note=("n_original_note_links", lambda s: int(s.gt(0).sum())),
        )
        .reset_index()
    )
    records = []
    for row in tracker.to_dict("records"):
        state = joined.loc[joined["state"].eq(row["state"])]
        target = state.loc[state["window_disposition"].eq(_IN_WINDOW)]
        records.append(
            {
                **row,
                "n_retained_contexts_wider_history": len(state),
                "n_source_in_window": len(target),
                "n_before_window": int(state["window_disposition"].eq(_BEFORE).sum()),
                "n_after_window": int(state["window_disposition"].eq(_AFTER).sum()),
                "n_unresolved_dates_wider_history": int(
                    state["window_disposition"].isin(_UNRESOLVED).sum()
                ),
                "n_in_window_lower": int(target["originating_chamber"].eq("lower").sum()),
                "n_in_window_upper": int(target["originating_chamber"].eq("upper").sum()),
                "n_in_window_legislature": int(
                    target["originating_chamber"].eq("legislature").sum()
                ),
                "n_in_window_with_reference": int(target["n_version_links"].gt(0).sum()),
                "n_in_window_with_usable_url": int(target["n_usable_url_links"].gt(0).sum()),
                "n_in_window_with_original_note": int(target["n_original_note_links"].gt(0).sum()),
                "n_in_window_reference_links": int(target["n_version_links"].sum()),
                "next_action": _ACTIONS[row["legislative_status"]],
                "date_evidence": (
                    "observed_dates_not_native_census"
                    if len(target)
                    else "no_observed_dates_not_zero_activity"
                ),
                "native_cycle_denominator": None,
                "recovered_cycle_text_count": None,
                "collection_authorized": False,
                "analytical_admission": False,
            }
        )
    matrix = pd.DataFrame(records)
    queue = matrix.loc[matrix["legislative_status"].ne("Closed scope")].copy()
    queue = queue.sort_values(["next_action", "state"]).reset_index(drop=True)
    return matrix, groups, queue


def build_matrix(
    window_dir: Path,
    reference_dir: Path,
    tracker_path: Path,
    out_dir: Path,
) -> dict:
    """Consume shared inputs once; immutable outputs never dispatch network work."""
    if out_dir.exists():
        raise FileExistsError(out_dir)
    paths = {
        "window_manifest": window_dir / "manifest.json",
        "ledger": window_dir / "bill_window_ledger.csv",
        "reference_manifest": reference_dir / "manifest.json",
        "reference_report": reference_dir / "report.json",
        "coverage": reference_dir / "bill_document_coverage.parquet",
        "tracker": tracker_path,
        "producer": Path(__file__),
        "study_sources": Path(__file__).with_name("study_sources.py"),
        "study_window": Path(__file__).with_name("study_window.py"),
        "openstates_dump": Path(__file__).with_name("openstates_dump.py"),
        "provenance": Path(__file__).parent.parent / "provenance.py",
    }
    before = {key: _snapshot(path) for key, path in paths.items()}
    window = json.loads(paths["window_manifest"].read_text(encoding="utf-8"))
    reference = json.loads(paths["reference_manifest"].read_text(encoding="utf-8"))
    if (
        window["status"] != "complete_source_window_inventory_not_analytical_admission"
        or (window["window_start"], window["window_end"]) != (START, END)
        or window["artifacts"]["bill_window_ledger.csv"]["sha256"] != before["ledger"]["sha256"]
    ):
        raise ValueError("completed, checksum-bound 2023-2024 ledger required")
    for key in ("reference_report", "coverage"):
        if reference["files"][paths[key].name] != before[key]["sha256"]:
            raise ValueError(f"reference checksum mismatch: {key}")
    report = json.loads(paths["reference_report"].read_text(encoding="utf-8"))
    if (
        report["status"] != "reference_inventory_not_text_certification"
        or report["extraction_manifest_sha256"]
        != window["inputs"]["bill_extraction_manifest.json"]["sha256"]
    ):
        raise ValueError("date and reference inputs must bind the same extraction")
    tracker = read_tracker(tracker_path)
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "status": "incomplete",
        "started_at": utc_now_iso(),
        "window_start": START,
        "window_end": END,
        "inputs": before,
        "new_requests": 0,
        "collection_authorized": False,
        "analytical_admission": False,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    ledger = pd.read_csv(paths["ledger"], dtype=str, keep_default_na=False)
    coverage = pd.read_parquet(
        paths["coverage"],
        columns=["bill_id", "state", "identifier", "session_identifier", *_COUNTS],
    )
    if len(ledger) != report["n_source_context_bills"]:
        raise ValueError("national context count disagrees with reference report")
    matrix, groups, queue = reconcile_matrix(ledger, coverage, tracker)
    for name, frame in (
        ("state_matrix.csv", matrix),
        ("state_session_chamber_counts.csv", groups),
        ("gap_queue.csv", queue),
    ):
        frame.to_csv(out_dir / name, index=False)
    result = {
        "status": _STATUS,
        "n_states": len(matrix),
        "n_gap_queue_states": len(queue),
        "n_retained_contexts_wider_history": len(ledger),
        "n_source_in_window": int(matrix["n_source_in_window"].sum()),
        "legislative_status_counts": matrix["legislative_status"].value_counts().to_dict(),
        "states_without_observed_in_window_dates": matrix.loc[
            matrix["n_source_in_window"].eq(0), "state"
        ].tolist(),
        "limitations": [
            "Source dates are not native-census or filing-time certification.",
            "Unresolved dates span wider history, not a count of target-cycle missing filings.",
            "Reference links are not recovered texts; native/text totals remain unknown.",
            "Closed scopes are reused; their exceptions remain in the tracker.",
            "Queue order is alphabetical within action, not a scientific priority ranking.",
            "Statuses are reviewed tracker judgments, not inferred from counts or stale tasks.",
            "Platforms, party attribution and classifier approval require separate evidence.",
        ],
        "new_requests": 0,
        "collection_authorized": False,
        "analytical_admission": False,
    }
    (out_dir / "report.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if {key: _snapshot(path) for key, path in paths.items()} != before:
        raise ValueError("matrix inputs changed; output remains incomplete")
    manifest.update(
        status=_STATUS,
        completed_at=utc_now_iso(),
        inputs_unchanged=True,
        artifacts={
            path.name: {"sha256": snap["sha256"], "bytes": snap["size"]}
            for path in sorted(out_dir.iterdir())
            if path.name != "manifest.json"
            for snap in [_snapshot(path)]
        },
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-dir", required=True, type=Path)
    parser.add_argument("--reference-dir", required=True, type=Path)
    parser.add_argument("--tracker", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            build_matrix(
                args.window_dir,
                args.reference_dir,
                args.tracker,
                args.out_dir,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

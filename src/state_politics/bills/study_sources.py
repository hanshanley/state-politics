"""Reconcile a supplied retained-input packet with cycle dates and source references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ..provenance import utc_now_iso
from .study_window import END, START, _snapshot

_IDENTITY = ["state", "identifier", "session_identifier"]
_GROUPS = [
    "state",
    "legislative_session_id",
    "session_identifier",
    "session_name",
    "originating_chamber",
    "classification",
    "window_disposition",
]
_IN_WINDOW = "source_introduction_in_window"
_STATUS = "complete_packet_overlap_not_native_coverage_or_analytical_admission"


def _unique(frame: pd.DataFrame, column: str) -> None:
    if frame[column].isna().any() or frame[column].eq("").any() or frame[column].duplicated().any():
        raise ValueError(f"empty or duplicate {column}")


def _matching_identity(left: pd.DataFrame, right: pd.DataFrame) -> None:
    joined = left[["bill_id", *_IDENTITY]].merge(
        right[["bill_id", *_IDENTITY]],
        on="bill_id",
        how="left",
        suffixes=("_left", "_right"),
        validate="many_to_one",
        indicator=True,
    )
    if not joined["_merge"].eq("both").all() or any(
        not joined[f"{key}_left"].eq(joined[f"{key}_right"]).fillna(False).all()
        for key in _IDENTITY
    ):
        raise ValueError("source context identity mismatch")


def reconcile_sources(
    ledger: pd.DataFrame,
    coverage: pd.DataFrame,
    references: pd.DataFrame,
    retained: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Preserve every state context, link and supplied input without inferring missing dates."""
    for frame in (ledger, coverage, retained):
        _unique(frame, "bill_id")
    _unique(references, "link_id")
    if set(ledger["bill_id"]) != set(coverage["bill_id"]):
        raise ValueError("source coverage must account for every state context")
    for frame in (coverage, references, retained):
        _matching_identity(frame, ledger)
    imported = retained.loc[retained["link_id"].notna() & retained["link_id"].ne("")]
    link_join = imported[["bill_id", "link_id"]].merge(
        references[["bill_id", "link_id"]],
        on="link_id",
        how="left",
        suffixes=("_input", "_reference"),
        validate="many_to_one",
        indicator=True,
    )
    if not link_join["_merge"].eq("both").all() or not link_join["bill_id_input"].eq(
        link_join["bill_id_reference"]
    ).all():
        raise ValueError("supplied input link identity mismatch")
    reference_counts = references.groupby("bill_id").size()
    counts = coverage["bill_id"].map(reference_counts).fillna(0).astype("int64")
    if not counts.eq(coverage["n_version_links"]).all():
        raise ValueError("reference links disagree with frozen coverage")
    if ledger.empty or ledger["state"].nunique() != 1:
        raise ValueError("one nonempty state ledger is required")

    details = coverage.drop(columns=_IDENTITY)
    contexts = ledger.merge(details, on="bill_id", validate="one_to_one")
    contexts["input_present_in_supplied_packet"] = contexts["bill_id"].isin(retained["bill_id"])
    contexts["source_in_window"] = contexts["window_disposition"].eq(_IN_WINDOW)
    contexts["analytical_admission"] = False
    timing = ledger.drop(columns=_IDENTITY)
    links = references.merge(timing, on="bill_id", validate="many_to_one")
    links["input_present_in_supplied_packet"] = links["bill_id"].isin(retained["bill_id"])
    links["source_in_window"] = links["window_disposition"].eq(_IN_WINDOW)
    overlap = retained.merge(timing, on="bill_id", validate="one_to_one")
    overlap["source_in_window"] = overlap["window_disposition"].eq(_IN_WINDOW)
    for frame in (links, overlap):
        frame["analytical_admission"] = False

    groups = (
        contexts.groupby(_GROUPS, dropna=False)
        .agg(
            n_contexts=("bill_id", "size"),
            n_inputs_in_supplied_packet=("input_present_in_supplied_packet", "sum"),
            n_version_links=("n_version_links", "sum"),
            n_original_note_links=("n_original_note_links", "sum"),
        )
        .reset_index()
    )
    return contexts, links, overlap, groups


def build_inventory(
    window_dir: Path,
    reference_dir: Path,
    input_dir: Path,
    out_dir: Path,
    *,
    state: str,
) -> dict:
    """Bind existing manifests, preserve full records and refuse packet overwrite."""
    if out_dir.exists():
        raise FileExistsError(out_dir)
    paths = {
        "window_manifest": window_dir / "manifest.json",
        "window_ledger": window_dir / "bill_window_ledger.csv",
        "reference_manifest": reference_dir / "manifest.json",
        "reference_report": reference_dir / "report.json",
        "coverage": reference_dir / "bill_document_coverage.parquet",
        "references": reference_dir / "document_candidates.parquet",
        "input_manifest": input_dir / "manifest.json",
        "input_report": input_dir / "report.json",
        "inputs": input_dir / "candidate_inputs.parquet",
        "producer": Path(__file__),
        "study_window": Path(__file__).with_name("study_window.py"),
        "provenance": Path(__file__).parent.parent / "provenance.py",
    }
    before = {key: _snapshot(path) for key, path in paths.items()}
    window = json.loads(paths["window_manifest"].read_text(encoding="utf-8"))
    if (
        window["status"] != "complete_source_window_inventory_not_analytical_admission"
        or window["window_start"] != START
        or window["window_end"] != END
    ):
        raise ValueError("a completed 2023-2024 source-date ledger is required")
    if window["artifacts"]["bill_window_ledger.csv"]["sha256"] != before["window_ledger"]["sha256"]:
        raise ValueError("source-date ledger checksum mismatch")
    for manifest_key, keys in (
        ("reference_manifest", ("reference_report", "coverage", "references")),
        ("input_manifest", ("input_report", "inputs")),
    ):
        manifest = json.loads(paths[manifest_key].read_text(encoding="utf-8"))
        for key in keys:
            if manifest["files"][paths[key].name] != before[key]["sha256"]:
                raise ValueError(f"{key}: packet checksum mismatch")
    reference_report = json.loads(paths["reference_report"].read_text(encoding="utf-8"))
    if (
        reference_report["status"] != "reference_inventory_not_text_certification"
        or reference_report["extraction_manifest_sha256"]
        != window["inputs"]["bill_extraction_manifest.json"]["sha256"]
    ):
        raise ValueError("reference inventory and dates must bind the same extraction")
    input_report = json.loads(paths["input_report"].read_text(encoding="utf-8"))
    if input_report["status"] != (
        "unlabelled_complete_input_inventory_not_inference_or_certification"
    ):
        raise ValueError("a completed unlabelled candidate-input packet is required")

    ledger = pd.read_csv(paths["window_ledger"], dtype=str, keep_default_na=False)
    ledger = ledger.loc[ledger["state"].eq(state)].copy()
    coverage = pd.read_parquet(paths["coverage"], filters=[("state", "==", state)])
    references = pd.read_parquet(paths["references"], filters=[("state", "==", state)])
    retained = pd.read_parquet(paths["inputs"])
    if len(retained) != input_report["n_bill_inputs"] or not retained["state"].eq(state).all():
        raise ValueError("supplied input packet must contain only the requested state")
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "status": "incomplete",
        "started_at": utc_now_iso(),
        "state": state,
        "window_start": START,
        "window_end": END,
        "inputs": before,
        "new_requests": 0,
        "requests_authorized": False,
        "analytical_admission": False,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    contexts, links, overlap, groups = reconcile_sources(ledger, coverage, references, retained)
    for name, frame in (
        ("state_contexts.parquet", contexts),
        ("source_reference_links.parquet", links),
        ("supplied_input_overlap.parquet", overlap),
    ):
        frame.to_parquet(out_dir / name, index=False)
    groups.to_csv(out_dir / "state_session_counts.csv", index=False)
    target = contexts.loc[contexts["source_in_window"]]
    target_links = links.loc[links["source_in_window"]]
    report = {
        "status": _STATUS,
        "state": state,
        "n_retained_state_contexts": len(contexts),
        "n_supplied_inputs": len(overlap),
        "n_source_in_window": len(target),
        "n_source_in_window_with_supplied_input": int(
            target["input_present_in_supplied_packet"].sum()
        ),
        "n_source_in_window_reference_links": len(target_links),
        "n_source_in_window_usable_original_note_links": int(
            (
                target_links["version_note_hint"].eq("original_note")
                & target_links["collection_eligible"].eq(True)
            ).sum()
        ),
        "n_source_in_window_without_reference_links": int(target["n_version_links"].eq(0).sum()),
        "source_disposition_counts": contexts["window_disposition"].value_counts().to_dict(),
        "supplied_input_session_counts": overlap["session_identifier"].value_counts().to_dict(),
        "supplied_input_disposition_counts": overlap["window_disposition"].value_counts().to_dict(),
        "limitations": [
            "Input presence is relative to the supplied packet, not all local source archives.",
            "Unknown dates remain unknown; session labels and source URLs never supply dates.",
            "References, Filed notes and usable URL syntax are not retrieved native originals.",
            "Source-coded dates are not independently verified native filing dates.",
            "No native census, historical absence, eligibility or certification follows.",
            "Full input strings and all reference rows survive; no inference or new labels.",
            "This inventory does not authorize collection, even for in-window source observations.",
        ],
        "analytical_admission": False,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if {key: _snapshot(path) for key, path in paths.items()} != before:
        raise ValueError("input or producer changed during source reconciliation")
    manifest.update(
        status=_STATUS,
        completed_at=utc_now_iso(),
        inputs_unchanged=True,
        artifacts={
            path.name: {"sha256": snapshot["sha256"], "bytes": snapshot["size"]}
            for path in sorted(out_dir.iterdir())
            if path.name != "manifest.json"
            for snapshot in [_snapshot(path)]
        },
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-dir", required=True, type=Path)
    parser.add_argument("--reference-dir", required=True, type=Path)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    report = build_inventory(
        args.window_dir,
        args.reference_dir,
        args.input_dir,
        args.out_dir,
        state=args.state,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

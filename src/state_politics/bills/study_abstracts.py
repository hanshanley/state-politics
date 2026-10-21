"""Preserve national cycle titles and abstract alternatives without approving inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from ..analysis.revealed import build_bill_input, is_procedural_shell_title, is_source_test_title
from ..provenance import utc_now_iso
from .montana import source_draft_request_mask
from .outcomes import _event_calendar_date
from .study_sources import _matching_identity, _unique
from .study_window import _STATES, END, START, _snapshot

_STATUS = "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted"
_IDENTITY = ["bill_id", "state", "identifier", "session_identifier"]
_DATES = ["source_introduction_date", "source_filing_date"]


def reconcile_evidence(
    bills: pd.DataFrame,
    abstracts: pd.DataFrame,
    ledger: pd.DataFrame,
    native: pd.DataFrame,
    registered_states: list[str],
    descriptions: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Keep every selected abstract and every alternative; never guess a latest summary."""
    for frame in (bills, ledger):
        _unique(frame, "bill_id")
    _unique(abstracts, "id")
    if set(bills["bill_id"]) != set(ledger["bill_id"]):
        raise ValueError("bill metadata and cycle ledger must have the same exact population")
    _matching_identity(bills, ledger)
    if not abstracts["bill_id"].isin(bills["bill_id"]).all():
        raise ValueError("abstract references a bill absent from the extraction")
    for frame, column in ((bills, "title"), (abstracts, "abstract"), (abstracts, "note")):
        if (
            not frame.loc[frame[column].notna(), column]
            .map(lambda value: isinstance(value, str))
            .all()
        ):
            raise ValueError(f"{column} must retain source strings or null")
    ledger = ledger.copy()
    ledger["source_event_in_window"] = ledger["window_disposition"].eq(
        "source_introduction_in_window"
    ) | ledger["filing_window_disposition"].eq("source_filing_in_window")
    ledger["description_event_in_window"] = pd.Series(pd.NA, index=ledger.index, dtype="boolean")
    if descriptions is not None:
        _unique(descriptions, "bill_id")
        _matching_identity(descriptions, ledger)
        selected = pd.Series(False, index=descriptions.index)
        for kind in ("introduction", "petition_filing"):
            prefix = f"description_{kind}"
            positive = descriptions[f"{prefix}_disposition"].eq("in_window")
            for value in descriptions.loc[positive, f"{prefix}_candidate_date"]:
                if (
                    not isinstance(value, str)
                    or not START <= (_event_calendar_date(value).isoformat()) <= END
                ):
                    raise ValueError("description candidate requires a complete in-window date")
            selected |= positive
        flags = pd.Series(selected.to_numpy(), index=descriptions["bill_id"])
        covered = ledger["state"].isin(descriptions["state"].unique())
        ledger.loc[covered, "description_event_in_window"] = (
            ledger.loc[covered, "bill_id"].map(flags).fillna(False).to_numpy()
        )
        details = descriptions[
            ["bill_id", *[c for c in descriptions if c.startswith("description_")]]
        ]
        ledger = ledger.merge(details, on="bill_id", how="left", validate="one_to_one")
    known_native = native.loc[native["bill_id"].notna()].copy()
    _unique(known_native, "bill_id")
    _matching_identity(known_native, ledger)
    if not known_native["state"].isin(registered_states).all():
        raise ValueError("native context state is not registered")
    if (
        not pd.api.types.is_integer_dtype(known_native["n_retained_views"].dtype)
        or known_native["n_retained_views"].isna().any()
        or known_native["n_retained_views"].lt(0).any()
    ):
        raise ValueError("native view counts must be nonnegative integers")
    if known_native["native_in_window"].isna().any() or not pd.api.types.is_bool_dtype(
        known_native["native_in_window"].dtype
    ):
        raise ValueError("explicit native in-window flags required")
    for record in known_native[["native_in_window", "native_introduction_date"]].to_dict("records"):
        value = record["native_introduction_date"]
        if pd.isna(value):
            if record["native_in_window"]:
                raise ValueError("native date flag requires its explicit date")
        elif (
            not isinstance(value, str)
            or (START <= _event_calendar_date(value).isoformat() <= END)
            != record["native_in_window"]
        ):
            raise ValueError("native date flag disagrees with its date")
    indexed_native = known_native.set_index("bill_id")
    for field in ("native_introduction_raw", "native_introduction_date", "date_evidence_status"):
        ledger[field] = ledger["bill_id"].map(indexed_native[field])
    ledger["native_introduction_in_window"] = pd.Series(
        pd.NA,
        index=ledger.index,
        dtype="boolean",
    )
    native_dates = indexed_native["native_in_window"]
    registered = ledger["state"].isin(registered_states)
    ledger.loc[registered, "native_introduction_in_window"] = (
        ledger.loc[registered, "bill_id"].map(native_dates).fillna(False).to_numpy()
    )
    selected = (
        ledger["source_event_in_window"]
        | ledger["native_introduction_in_window"].eq(True).fillna(False)
        | ledger["description_event_in_window"].eq(True).fillna(False)
    )
    cohort = ledger.loc[selected].merge(
        bills[["bill_id", "title"]],
        on="bill_id",
        validate="one_to_one",
    )
    cohort["cohort_scope"] = "description_stated_event_candidate"
    native_candidate = cohort["native_introduction_in_window"].eq(True).fillna(False)
    cohort.loc[native_candidate, "cohort_scope"] = "native_reported_date_candidate"
    cohort.loc[cohort["source_event_in_window"], "cohort_scope"] = "source_coded_event"
    cohort["source_test_record"] = [
        is_source_test_title(title if isinstance(title, str) else "", state)
        for title, state in zip(cohort["title"], cohort["state"], strict=True)
    ]
    cohort["source_draft_request"] = source_draft_request_mask(cohort)
    native_counts = known_native.set_index("bill_id")["n_retained_views"]
    cohort["n_indexed_native_views"] = pd.Series(pd.NA, index=cohort.index, dtype="Int64")
    known = cohort["state"].isin(registered_states)
    cohort.loc[known, "n_indexed_native_views"] = (
        cohort.loc[known, "bill_id"].map(native_counts).fillna(0).astype("int64").to_numpy()
    )
    kept = abstracts.loc[abstracts["bill_id"].isin(cohort["bill_id"])].copy()
    kept["abstract_nonempty"] = kept["abstract"].map(
        lambda value: isinstance(value, str) and bool(value.strip())
    )
    kept["abstract_sha256"] = kept["abstract"].map(
        lambda value: (
            hashlib.sha256(value.encode("utf-8")).hexdigest() if isinstance(value, str) else None
        )
    )
    kept = kept.merge(
        cohort[[*_IDENTITY, "title", *_DATES]],
        on="bill_id",
        validate="many_to_one",
    )
    nonempty = kept.loc[kept["abstract_nonempty"]]
    counts = nonempty.groupby("bill_id").size()
    variants = nonempty.groupby("bill_id")["abstract"].nunique()
    cohort["n_nonempty_abstract_records"] = cohort["bill_id"].map(counts).fillna(0).astype("int64")
    cohort["n_distinct_abstract_texts"] = cohort["bill_id"].map(variants).fillna(0).astype("int64")
    cohort["metadata_tier"] = [
        "retained_abstract_unaligned"
        if count
        else "title_only"
        if isinstance(title, str) and title.strip()
        else "missing_metadata"
        for count, title in zip(cohort["n_nonempty_abstract_records"], cohort["title"], strict=True)
    ]
    cohort["model_input_approved"] = False
    cohort["filing_time_text_certified"] = False
    cohort["analytical_admission"] = False
    sources = nonempty[["bill_id", "id", "abstract", "note"]].to_dict("records")
    sources.extend(
        {"bill_id": bill_id, "id": None, "abstract": None, "note": None}
        for bill_id in cohort.loc[cohort["n_nonempty_abstract_records"].eq(0), "bill_id"]
    )
    by_bill = cohort.set_index("bill_id").to_dict("index")
    views = []
    for source in sources:
        bill_id = source["bill_id"]
        row = by_bill[bill_id]
        title = row["title"] if isinstance(row["title"], str) else ""
        summary = source["abstract"] if source["abstract"] is not None else ""
        text, fields = build_bill_input(title, summary)
        shell = is_procedural_shell_title(title, row["state"]) and not summary.strip()
        status = (
            "excluded_source_test"
            if row["source_test_record"]
            else "excluded_source_draft_request"
            if row["source_draft_request"]
            else "procedural_title_without_summary"
            if shell
            else "empty_metadata_no_input"
            if not text
            else "unreviewed_metadata_candidate"
        )
        views.append(
            {
                "view_id": f"abstract:{source['id']}" if source["id"] else f"title:{bill_id}",
                "bill_id": bill_id,
                "state": row["state"],
                "identifier": row["identifier"],
                "session_identifier": row["session_identifier"],
                "title": row["title"],
                "abstract_id": source["id"],
                "abstract": source["abstract"],
                "abstract_note": source["note"],
                "text": text,
                "input_fields": json.dumps(fields),
                "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "n_input_characters": len(text),
                "input_status": status,
                "metadata_tier": row["metadata_tier"],
                "cohort_scope": row["cohort_scope"],
                "multiple_abstract_variants": row["n_distinct_abstract_texts"] > 1,
                "n_input_tokens": None,
                "n_discarded_tokens": None,
                "chunking_status": "not_tokenized",
                "model_input_approved": False,
                "filing_time_text_certified": False,
                "training_admission": False,
                "analytical_admission": False,
            }
        )
    columns = [
        "view_id",
        "bill_id",
        "state",
        "identifier",
        "session_identifier",
        "title",
        "abstract_id",
        "abstract",
        "abstract_note",
        "text",
        "input_fields",
        "input_sha256",
        "n_input_characters",
        "input_status",
        "metadata_tier",
        "multiple_abstract_variants",
        "n_input_tokens",
        "n_discarded_tokens",
        "chunking_status",
        "model_input_approved",
        "filing_time_text_certified",
        "training_admission",
        "analytical_admission",
        "cohort_scope",
    ]
    view_frame = pd.DataFrame(views, columns=columns)
    _unique(view_frame, "view_id")
    return cohort, kept, view_frame


def build_inventory(
    data_dir: Path,
    filing_dir: Path,
    native_dir: Path,
    out_dir: Path,
    *,
    description_dir: Path | None = None,
) -> dict:
    if out_dir.exists():
        raise FileExistsError(out_dir)
    paths = {
        "extraction_manifest": data_dir / "bill_extraction_manifest.json",
        "bills": data_dir / "bills.parquet",
        "abstracts": data_dir / "bill_abstracts.parquet",
        "filing_manifest": filing_dir / "manifest.json",
        "ledger": filing_dir / "bill_filing_evidence.csv",
        "matrix": filing_dir / "state_matrix.csv",
        "native_manifest": native_dir / "manifest.json",
        "native_contexts": native_dir / "native_context_overlap.parquet",
        "native_report": native_dir / "report.json",
        "producer": Path(__file__),
        "revealed": Path(__file__).parent.parent / "analysis/revealed.py",
        "montana": Path(__file__).with_name("montana.py"),
        "outcomes": Path(__file__).with_name("outcomes.py"),
        "study_sources": Path(__file__).with_name("study_sources.py"),
        "study_window": Path(__file__).with_name("study_window.py"),
        "provenance": Path(__file__).parent.parent / "provenance.py",
    }
    if description_dir is not None:
        paths["description_manifest"] = description_dir / "manifest.json"
        paths["description_ledger"] = description_dir / "candidate_bill_ledger.csv"
    before = {key: _snapshot(path) for key, path in paths.items()}
    extraction = json.loads(paths["extraction_manifest"].read_text(encoding="utf-8"))
    filing = json.loads(paths["filing_manifest"].read_text(encoding="utf-8"))
    native_manifest = json.loads(paths["native_manifest"].read_text(encoding="utf-8"))
    window_path = Path(filing["inputs"]["window_manifest"]["path"])
    paths["window_manifest"] = window_path
    before["window_manifest"] = _snapshot(window_path)
    window = json.loads(window_path.read_text(encoding="utf-8"))
    if (
        extraction["status"] != "complete_extraction_not_source_certification"
        or filing["status"]
        != "complete_source_filing_inventory_not_native_or_analytical_certification"
        or native_manifest["status"]
        != "complete_supplied_native_overlap_not_native_census_or_analytical_admission"
        or before["window_manifest"]["sha256"] != filing["inputs"]["window_manifest"]["sha256"]
        or before["extraction_manifest"]["sha256"]
        != window["inputs"]["bill_extraction_manifest.json"]["sha256"]
        or before["native_manifest"]["sha256"] != filing["inputs"]["matrix_manifest"]["sha256"]
    ):
        raise ValueError("completed extraction, filing and native packets must share exact lineage")
    for key, filename in (("bills", "bills.parquet"), ("abstracts", "bill_abstracts.parquet")):
        if extraction["artifacts"][filename]["sha256"] != before[key]["sha256"]:
            raise ValueError(f"{key}: extraction checksum mismatch")
    for manifest, pairs in (
        (filing, (("ledger", "bill_filing_evidence.csv"), ("matrix", "state_matrix.csv"))),
        (
            native_manifest,
            (
                ("native_contexts", "native_context_overlap.parquet"),
                ("native_report", "report.json"),
            ),
        ),
    ):
        for key, filename in pairs:
            if manifest["artifacts"][filename]["sha256"] != before[key]["sha256"]:
                raise ValueError(f"{key}: packet checksum mismatch")
    native_report = json.loads(paths["native_report"].read_text(encoding="utf-8"))
    descriptions = None
    if description_dir is not None:
        description_manifest = json.loads(paths["description_manifest"].read_text(encoding="utf-8"))
        if (
            description_manifest["status"]
            != "complete_literal_description_inventory_not_analytical_admission"
            or description_manifest["inputs"]["filing_ledger"]["sha256"]
            != before["ledger"]["sha256"]
            or description_manifest["inputs"]["window_manifest"]["sha256"]
            != before["window_manifest"]["sha256"]
            or description_manifest["inputs"]["extraction_manifest"]["sha256"]
            != before["extraction_manifest"]["sha256"]
            or description_manifest["artifacts"]["candidate_bill_ledger.csv"]["sha256"]
            != before["description_ledger"]["sha256"]
        ):
            raise ValueError(
                "description evidence must bind identical filing/window/extraction bytes"
            )
        descriptions = pd.read_csv(
            paths["description_ledger"],
            dtype=str,
            keep_default_na=False,
            usecols=lambda name: name in _IDENTITY or name.startswith("description_"),
        )
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "status": "incomplete",
        "started_at": utc_now_iso(),
        "inputs": before,
        "new_requests": 0,
        "model_input_approved": False,
        "analytical_admission": False,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    bills = pd.read_parquet(paths["bills"], columns=[*_IDENTITY, "title"])
    abstracts = pd.read_parquet(paths["abstracts"])
    for frame, name in ((bills, "bills.parquet"), (abstracts, "bill_abstracts.parquet")):
        if len(frame) != extraction["artifacts"][name]["rows"]:
            raise ValueError(f"{name}: extraction row count mismatch")
    ledger = pd.read_csv(paths["ledger"], dtype=str, keep_default_na=False)
    registered = native_report["registered_states"]
    cohort, kept, views = reconcile_evidence(
        bills,
        abstracts,
        ledger,
        pd.read_parquet(paths["native_contexts"]),
        registered,
        descriptions,
    )
    matrix = pd.read_csv(paths["matrix"], keep_default_na=False)
    if matrix["state"].duplicated().any() or set(matrix["state"]) != _STATES:
        raise ValueError("exact 50-state matrix required")
    metrics = []
    for row in matrix.to_dict("records"):
        state = cohort.loc[cohort["state"].eq(row["state"])]
        state_views = views.loc[views["state"].eq(row["state"])]
        if int(state["source_event_in_window"].sum()) != row["n_filing_or_introduction_in_window"]:
            raise ValueError("cohort does not reconcile with source-event matrix")
        metrics.append(
            {
                "n_cycle_evidence_candidate_contexts": len(state),
                "n_native_only_scope_candidates": int(
                    state["cohort_scope"].eq("native_reported_date_candidate").sum()
                ),
                "n_description_only_scope_candidates": int(
                    state["cohort_scope"].eq("description_stated_event_candidate").sum()
                ),
                "n_cycle_contexts_with_nonempty_abstract": int(
                    state["n_nonempty_abstract_records"].gt(0).sum()
                ),
                "n_cycle_contexts_with_multiple_abstract_variants": int(
                    state["n_distinct_abstract_texts"].gt(1).sum()
                ),
                "n_cycle_title_only_metadata_contexts": int(
                    state["metadata_tier"].eq("title_only").sum()
                ),
                "n_cycle_missing_metadata_contexts": int(
                    state["metadata_tier"].eq("missing_metadata").sum()
                ),
                "n_cycle_metadata_candidate_views": len(state_views),
                "n_cycle_source_test_contexts": int(state["source_test_record"].sum()),
                "n_cycle_draft_request_contexts": int(state["source_draft_request"].sum()),
                "n_cycle_contexts_with_indexed_native_text": int(
                    state["n_indexed_native_views"].gt(0).sum()
                )
                if row["state"] in registered
                else None,
            }
        )
    matrix = pd.concat([matrix, pd.DataFrame(metrics, index=matrix.index)], axis=1)
    for name, frame in (
        ("bill_evidence.parquet", cohort),
        ("abstract_evidence.parquet", kept),
        ("candidate_metadata_views.parquet", views),
    ):
        frame.to_parquet(out_dir / name, index=False)
    matrix.to_csv(out_dir / "state_matrix.csv", index=False)
    result = {
        "status": _STATUS,
        "n_source_contexts": len(bills),
        "n_source_abstract_records": len(abstracts),
        "n_cycle_contexts": len(cohort),
        "cohort_scope_counts": cohort["cohort_scope"].value_counts().to_dict(),
        "n_cycle_abstract_records": len(kept),
        "n_cycle_contexts_with_nonempty_abstract": int(
            cohort["n_nonempty_abstract_records"].gt(0).sum()
        ),
        "n_cycle_contexts_with_multiple_abstract_variants": int(
            cohort["n_distinct_abstract_texts"].gt(1).sum()
        ),
        "n_metadata_candidate_views_not_bills": len(views),
        "limitations": [
            "Source abstracts/titles are not certified official filing-time text.",
            "Every selected abstract and note survives; no latest/longest or deduplication choice.",
            "Alternative abstracts are not additional bills or approved classifier inputs.",
            "Native/description-only scope candidates are distinct from source-coded event counts.",
            "Native input presence is relative to registered packets; other states remain unknown.",
            "No introduced source is prepended with potentially later title/summary metadata.",
            "Full strings survive; no tokenizer, model, new labels or analytical admission is run.",
        ],
        "model_input_approved": False,
        "new_requests": 0,
        "analytical_admission": False,
    }
    (out_dir / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if {key: _snapshot(path) for key, path in paths.items()} != before:
        raise ValueError("metadata evidence inputs changed; output remains incomplete")
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
    for name in ("data-dir", "filing-dir", "native-dir", "out-dir"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--description-dir", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            build_inventory(
                args.data_dir,
                args.filing_dir,
                args.native_dir,
                args.out_dir,
                description_dir=args.description_dir,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

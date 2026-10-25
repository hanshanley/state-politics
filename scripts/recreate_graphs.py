#!/usr/bin/env python3
"""Recreate supported evidence graphs; preserve unsupported old figures as references."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import runpy
import shutil
import sys
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from matplotlib.ticker import PercentFormatter, StrMethodFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.bills.archive_text import SCHEMA as ARCHIVE_SCHEMA  # noqa: E402
from state_politics.bills.archive_text import load_archive  # noqa: E402
from state_politics.bills.research_corpus_text import FLAGS, SCHEMA, load_corpus  # noqa: E402
from state_politics.bills.study_matrix import read_tracker  # noqa: E402
from state_politics.platforms.dataverse import coverage_matrix  # noqa: E402
from state_politics.plotting import charts, theme  # noqa: E402

SOURCES = {
    "metadata": "data/processed/study-abstract-evidence-2023-2024-v4",
    "native": "data/processed/native-inventory-catalog-2023-2024-v2",
    "sessions": "data/processed/verified-session-comparison-2023-2024-v3",
}
MODELS = {
    "Mixed full-document": "cycle-native-document-evaluation-20261021-v1",
    "Reviewed-only": "cycle-reviewed-only-evaluation-20261021-v1",
}
DATASETS = {
    "cycle_metadata_190": "Metadata",
    "cycle_native_39": "Native text (agreed only)",
    "platform_52": "Platform",
    "development_50": "Development",
}
STATUS_COLORS = {
    "Closed scope": theme.GREEN,
    "Partial": theme.BLUE,
    "Blocked": theme.ACCENT,
    "Inventory": theme.MUTED,
}
MODEL_COLORS = {"Mixed full-document": theme.BLUE, "Reviewed-only": theme.GOLD}
CHART_TABLES = {
    "state_source_status": "state_source_status",
    "bill_evidence_by_state": "bill_evidence_by_state",
    "native_inventory_observations": "native_source_observations",
    "session_calendar_comparison": "session_calendar_comparison",
    "classifier_development_diagnostics": "classifier_metrics",
    "native_precision_and_coverage": "classifier_metrics",
    "platform_corpus_recency": "historical_platform_coverage",
}
NOTICE = (
    "Evidence inspection and assistant-reviewed development diagnostics, not validated "
    "party-policy findings. Source scopes are not completed studies. Models remain "
    "provisional; no human gold, new predictions, publication or scientific approval."
)
RECOVERED_PACKETS = {
    "platforms": "data/processed/recovered-platform-graph-inputs-20261022-v1",
    "outcomes": "data/processed/cycle-outcome-evidence-20261022-v2",
    "arkansas": "data/processed/native-text-ar-20261022-v3",
    "caucus": "data/processed/recovered-platform-graph-inputs-20261022-v2",
    "caucus_capture": "data/processed/platform-graph-inputs-caucus-followup-20261022-v2",
    "snapshot": "data/processed/retained-dump-gap-recovery-20261022-v1",
}
RECOVERED_GRAPHS = (
    ("platforms", "modern_collection_outcomes", "modern_collection_status_counts.csv",
     "Modern platform collection observations",
     "Original snapshot outcomes, not operative 2023-2024 platform coverage"),
    ("platforms", "retained_response_bodies", "capture_ledger.csv",
     "Retained responses and repeated bodies",
     "All 1,559 capture attempts; repetitions and failures remain visible"),
    ("platforms", "modern_collection_metadata_years", "modern_metadata_year_counts.csv",
     "Years recorded in the recovered source tables",
     "Metadata years are not adoption dates or cycle-applicability certification"),
    ("outcomes", "pooled_recorded_stages", "pooled_recorded_stages.csv",
     "Pooled recorded legislative stages",
     "Law-eligible bills; all retained action dates, not party comparisons or final outcomes"),
    ("outcomes", "state_recorded_stages", "state_recorded_stages.csv",
     "Recorded stages by state",
     "Source classification evidence, not classifier policy labels or final legal dispositions"),
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def binding(path: Path) -> dict:
    return {"sha256": digest(path), "bytes": path.stat().st_size}


def checked_file(root: Path, relative: str, inputs: dict, expected=None) -> Path:
    path = root / relative
    if not path.is_file() or path.resolve() != path:
        raise ValueError(f"missing or linked graph input: {relative}")
    actual = binding(path)
    wanted = expected.get("sha256") if isinstance(expected, dict) else expected
    if wanted is not None and actual["sha256"] != wanted:
        raise ValueError(f"graph input hash mismatch: {relative}")
    if isinstance(expected, dict) and actual["bytes"] != expected["bytes"]:
        raise ValueError(f"graph input size mismatch: {relative}")
    inputs[relative] = actual
    return path


def source_table(root: Path, kind: str, name: str, inputs: dict) -> pd.DataFrame:
    directory = SOURCES[kind]
    manifest_path = checked_file(root, f"{directory}/manifest.json", inputs)
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("analytical_admission") is not False:
        raise ValueError("only explicitly unapproved evidence inputs are supported")
    path = checked_file(
        root, f"{directory}/{name}", inputs, manifest["artifacts"][name],
    )
    frame = pd.read_csv(path)
    if len(frame) != 50 or frame["state"].nunique() != 50:
        raise ValueError(f"all fifty unique states required: {kind}")
    return frame.sort_values("state").reset_index(drop=True)


def recovery_packet(
    root: Path, directory: str, inputs: dict, *, snapshot=False, corpus=False, archive=False,
) -> dict[str, Path]:
    manifest_name = "sealed_manifest.json" if snapshot else "manifest.json"
    path = checked_file(root, f"{directory}/{manifest_name}", inputs)
    manifest = json.loads(path.read_bytes())
    if archive:
        if (
            manifest.get("schema") not in (
                ARCHIVE_SCHEMA, "state-politics.lawatlas-archive-text.v1",
                "state-politics.maryland-archive-text.v1",
                "state-politics.nj-library-text.v1",
                "state-politics.nj-library-collection-text.v1",
                "state-politics.ok-retained-context-text.v1",
                "state-politics.billcam-retained-html.v1",
                "state-politics.govbot-archived-documents.v1",
                "state-politics.published-ai-corpus-text.v1",
                "state-politics.billcommons-archive-text.v1",
                "state-politics.billcommons-nevada-archive-text.v1",
                "state-politics.nebraska-journal-text.v1",
                "state-politics.nebraska-journal-collection-text.v1",
                "state-politics.nebraska-journal-collection-text.v2",
            )
            or not all(manifest.get("approvals", {}).get(flag) is False for flag in FLAGS)
        ):
            raise ValueError("unapproved independent archive required")
        files = manifest["packet_artifacts"]
    elif corpus:
        if (
            manifest.get("schema") != SCHEMA
            or not all(manifest.get("approvals", {}).get(flag) is False for flag in FLAGS)
        ):
            raise ValueError("unapproved header-joined research corpus required")
        files = manifest["packet_artifacts"]
    elif snapshot:
        if (
            manifest.get("status")
            != "complete_bounded_retained_dump_gap_recovery_not_scientific_certification"
            or not manifest.get("approvals")
            or any(value is not False for value in manifest["approvals"].values())
        ):
            raise ValueError("unapproved sealed snapshot recovery required")
        files = manifest["packet_artifacts"]
    elif (
        manifest.get("analytical_admission") is not False
        or manifest.get("scientific_approval") is not False
    ):
        raise ValueError("recovered research packets must remain explicitly unapproved")
    else:
        files = manifest.get("files", manifest.get("artifacts"))
    if not isinstance(files, dict) or not files:
        raise ValueError("a complete hash-bound recovery packet is required")
    result = {manifest_name: path}
    for name, expected in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name == manifest_name:
            raise ValueError("invalid recovery artifact path")
        result[name] = checked_file(root, f"{directory}/{name}", inputs, expected)
    if snapshot:
        for name, expected in manifest["inspection_artifacts"].items():
            source = Path(expected["path"])
            if not source.is_relative_to(root / "data/processed"):
                raise ValueError("snapshot inspection must remain within processed research data")
            result[f"original-inspection/{name}"] = checked_file(
                root, source.relative_to(root).as_posix(), inputs, expected,
            )
    return result


def archive_packet(files: dict[str, Path], output: Path) -> dict:
    with zipfile.ZipFile(
        output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True,
    ) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
    return {
        "path": f"research-data/{output.name}", "files": len(files),
        "uncompressed_bytes": sum(path.stat().st_size for path in files.values()),
        **binding(output),
    }


def arkansas_rows(files: dict[str, Path]) -> pd.DataFrame:
    contexts = pd.read_parquet(files["context_inventory.parquet"])
    views = pd.read_parquet(files["source_view_inputs.parquet"])
    if (
        contexts["context_id"].duplicated().any()
        or views.duplicated(["context_id", "reader"]).any()
        or not set(views["context_id"]) <= set(contexts["context_id"])
    ):
        raise ValueError("native context and complete-reader identities must reconcile")
    counts = views.groupby("context_id").size()
    if not counts.eq(2).all():
        raise ValueError("two complete reader alternatives required per captured PDF")
    contexts = contexts.assign(
        complete_pdf_context=contexts["context_id"].isin(counts.index),
        complete_reader_views=contexts["context_id"].map(counts).fillna(0).astype(int),
    )
    result = contexts.groupby("native_session_identifier", sort=True).agg(
        native_metadata_contexts=("context_id", "size"),
        complete_pdf_contexts=("complete_pdf_context", "sum"),
        complete_reader_views=("complete_reader_views", "sum"),
    ).reset_index()
    result["metadata_only_contexts"] = (
        result["native_metadata_contexts"] - result["complete_pdf_contexts"]
    )
    return result


def snapshot_coverage(root, packet, inputs, *, corpus_directory=None, archive_directories=()):
    base = SOURCES["metadata"]
    manifest = json.loads((root / base / "manifest.json").read_bytes())
    metadata = checked_file(
        root, f"{base}/bill_evidence.parquet", inputs,
        manifest["artifacts"]["bill_evidence.parquet"],
    )
    bills = pd.read_parquet(metadata)
    # Strict source replay needs original nulls, not Pandas' NaN conversions.
    original_metadata = pq.read_table(metadata).to_pylist()
    contexts = pd.read_parquet(packet["context_inventory.parquet"])
    if (
        bills["bill_id"].duplicated().any() or contexts["bill_id"].duplicated().any()
        or set(bills["bill_id"]) != set(contexts["bill_id"])
    ):
        raise ValueError("snapshot text must match every exact existing candidate identity")
    joined = bills.merge(contexts.add_prefix("snapshot_"), left_on="bill_id",
                         right_on="snapshot_bill_id", validate="one_to_one")
    if not joined["state"].equals(joined["snapshot_state"]):
        raise ValueError("snapshot state identity conflict")
    joined["native_text_observed"] = joined["n_indexed_native_views"].gt(0).fillna(False)
    joined["snapshot_text_observed"] = joined["snapshot_nonempty_bound_noerror"]
    joined["both_sources"] = joined["native_text_observed"] & joined["snapshot_text_observed"]
    joined["native_only"] = joined["native_text_observed"] & ~joined["snapshot_text_observed"]
    joined["snapshot_only"] = joined["snapshot_text_observed"] & ~joined["native_text_observed"]
    joined["neither_source_observed"] = ~(
        joined["native_text_observed"] | joined["snapshot_text_observed"]
    )
    original_gaps = set(joined.loc[joined["neither_source_observed"], "bill_id"])
    extra = {}
    if corpus_directory is not None:
        _, corpus_contexts, _, _ = load_corpus(corpus_directory, original_metadata)
        corpus_ids = {row["bill_id"] for row in corpus_contexts}
        if not corpus_ids <= set(joined.loc[joined["neither_source_observed"], "bill_id"]):
            raise ValueError("research recovery must cover only exact remaining source gaps")
        joined["research_corpus_text_observed"] = joined["bill_id"].isin(corpus_ids)
        joined["neither_source_observed"] &= ~joined["research_corpus_text_observed"]
        extra["research_corpus_only"] = ("research_corpus_text_observed", "sum")
    if archive_directories:
        archive_ids = set()
        for directory in archive_directories:
            _, contexts, _, _ = load_archive(directory, original_metadata)
            archive_ids.update(row["bill_id"] for row in contexts)
        if not archive_ids <= original_gaps:
            raise ValueError("archive recovery must cover only exact remaining source gaps")
        joined["archive_text_observed"] = joined["bill_id"].isin(archive_ids)
        joined["independent_archive_only"] = (
            joined["archive_text_observed"] & joined["neither_source_observed"]
        )
        joined["neither_source_observed"] &= ~joined["archive_text_observed"]
        extra["independent_archive_only"] = ("independent_archive_only", "sum")
    grouped = joined.groupby("state").agg(
        candidate_contexts=("bill_id", "size"), both_sources=("both_sources", "sum"),
        native_only=("native_only", "sum"), snapshot_only=("snapshot_only", "sum"),
        neither_source_observed=("neither_source_observed", "sum"),
        **extra,
    )
    grouped = grouped.reindex(sorted(read_tracker(root / "docs/STATE_PROGRESS.md")["state"]),
                              fill_value=0).reset_index()
    return grouped, joined.loc[joined["neither_source_observed"]].copy()


def snapshot_graph(output, coverage):
    fig, ax = plt.subplots(figsize=(13, 16))
    left = np.zeros(len(coverage))
    categories = [
        ("both_sources", "Native + snapshot text", theme.GREEN),
        ("snapshot_only", "Snapshot text only", theme.BLUE),
        ("native_only", "Native reader text only", theme.GOLD),
    ]
    independent = [
        name for name in ("research_corpus_only", "independent_archive_only") if name in coverage
    ]
    if independent:
        coverage = coverage.assign(independent_text_only=coverage[independent].sum(axis=1))
        categories.append((
            "independent_text_only", "Independent corpus / archive text", theme.MUTED,
        ))
    categories.append(("neither_source_observed", "No text observed in these inputs", theme.GRID))
    for column, label, color in categories:
        values = coverage[column]
        ax.barh(coverage["state"], values, left=left, color=color, label=label, height=0.65)
        left += values.to_numpy()
    ax.invert_yaxis()
    count_axis(ax)
    ax.set_xlabel("Existing calendar-candidate contexts")
    ax.legend(loc="lower right", fontsize=9)
    figure = save(
        fig, output / "graphs", "retained_snapshot_text_coverage",
        "Recovered text without double-counting bills",
        "Separate source channels complement retained native reader views",
        "Source: sealed retained-dump recovery and unchanged metadata v4. Snapshot versions "
        "may be amended/later, not introduced originals. Source overlap is de-duplicated by "
        "exact bill ID. Unregistered native channels remain unknown; no observed text is "
        "not publisher absence. Independent corpus/archive joins are not publisher-original "
        "certification. Empty/no-candidate states do not mean no legislative activity.",
    )
    figure["chart_data"] = "chart-data/retained_text_coverage.csv"
    return figure


def recovered_graphs(output: Path, packets: dict, arkansas: pd.DataFrame) -> list[dict]:
    figures = []
    for kind, name, table, title, subtitle in RECOVERED_GRAPHS:
        for suffix in ("png", "svg"):
            shutil.copy2(packets[kind][f"{name}.{suffix}"], output / "graphs" / f"{name}.{suffix}")
        data_name = f"{kind}_{table}"
        shutil.copy2(packets[kind][table], output / "chart-data" / data_name)
        figures.append({
            "name": name, "title": title, "subtitle": subtitle,
            "chart_data": f"chart-data/{data_name}",
            "rendering": "unchanged_graph_from_hash_bound_recovery_packet",
            "source_packet": RECOVERED_PACKETS[kind],
        })
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.barh(
        arkansas["native_session_identifier"], arkansas["complete_pdf_contexts"],
        color=theme.BLUE, label="Complete PDF / both readers",
    )
    ax.barh(
        arkansas["native_session_identifier"], arkansas["metadata_only_contexts"],
        left=arkansas["complete_pdf_contexts"], color=theme.GOLD, label="Metadata only",
    )
    for position, row in enumerate(arkansas.itertuples()):
        ax.text(
            row.native_metadata_contexts + 25, position,
            f"{row.complete_pdf_contexts:,} of {row.native_metadata_contexts:,} have text",
            va="center", fontsize=10,
        )
    ax.invert_yaxis()
    ax.set_xlim(0, arkansas["native_metadata_contexts"].max() * 1.30)
    ax.set_xlabel("Retained publisher metadata contexts")
    ax.legend(loc="lower right")
    count_axis(ax)
    figure = save(
        fig, output / "graphs", "arkansas_native_text", "Arkansas: text recovered, gaps preserved",
        "149 complete publisher-linked PDFs / 298 reader alternatives across four sessions",
        "Source: native-text-ar v3. The closed 150-exchange batch does not complete the "
        "1,991-context native inventory. Printed identity/session observations do not certify "
        "original or filing-time versions. No introduction dates or policy labels inferred.",
    )
    figure["chart_data"] = "chart-data/arkansas_text_by_session.csv"
    figures.append(figure)
    return figures


def diagnostic_rows(root: Path, inputs: dict) -> pd.DataFrame:
    rows = []
    for model, directory in MODELS.items():
        base = f"data/processed/{directory}"
        manifest_path = checked_file(root, f"{base}/manifest.json", inputs)
        manifest = json.loads(manifest_path.read_bytes())
        path = checked_file(
            root, f"{base}/comparison.json", inputs, manifest["files"]["comparison.json"],
        )
        comparison = json.loads(path.read_bytes())
        if (
            comparison.get("model_promotion") is not False
            or comparison.get("human_gold") is not False
            or comparison.get("publication") is not False
        ):
            raise ValueError("unapproved development diagnostic required")
        for dataset, label in DATASETS.items():
            result = comparison["reference_results"][dataset]
            selected = ("primary_agreed_metrics" if dataset == "cycle_native_39"
                        else "all_reference_metrics")
            metrics = result[selected]
            fields = (
                "n_eligible", "n_classified", "n_abstained", "n_correct_topic",
                "correct_abstention_count",
            )
            if any(type(metrics[key]) is not int or metrics[key] < 0 for key in fields):
                raise ValueError("diagnostic counts must be nonnegative integers")
            n, classified = metrics["n_eligible"], metrics["n_classified"]
            correct, abstained_correct = (
                metrics["n_correct_topic"], metrics["correct_abstention_count"],
            )
            if (
                n <= 0 or classified <= 0
                or classified + metrics["n_abstained"] != n or correct > classified
                or abstained_correct > metrics["n_abstained"]
            ):
                raise ValueError("diagnostic counts do not reconcile")
            rates = {
                "decision_accuracy": (correct + abstained_correct) / n,
                "coverage": classified / n,
                "classified_precision": correct / classified,
            }
            if any(abs(metrics[key] - value) > 1e-12 for key, value in rates.items()):
                raise ValueError("diagnostic rates do not match their denominators")
            rows.append({
                "model": model, "dataset": dataset, "dataset_label": label,
                "metric_scope": selected, **{key: metrics[key] for key in fields}, **rates,
                "reference_basis": "assistant-reviewed development evidence, not human gold",
            })
    return pd.DataFrame(rows)


def save(fig, out: Path, name: str, title: str, subtitle: str, note: str) -> dict:
    fig.suptitle(title, x=0.02, y=0.99, ha="left", fontsize=18, fontweight="bold")
    fig.text(0.02, 0.94, subtitle, va="top", fontsize=10.5, color=theme.MUTED)
    source = theme.source_note(fig, note, x=0.02)
    theme.layout_with_note(fig, source, top=0.87)
    for suffix in ("png", "svg"):
        kwargs = {"metadata": {"Date": None}} if suffix == "svg" else {}
        fig.savefig(out / f"{name}.{suffix}", dpi=200, bbox_inches="tight", **kwargs)
    plt.close(fig)
    return {"name": name, "title": title, "subtitle": subtitle, "source_note": note}


def count_axis(ax):
    ax.grid(axis="x", color=theme.GRID, linewidth=0.5)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))


def render_graphs(out, tracker, metadata, native, sessions, diagnostics, historical):
    theme.apply()
    plt.rcParams["svg.fonttype"] = "none"
    figures = []
    status = tracker["legislative_status"].value_counts().reindex(STATUS_COLORS, fill_value=0)
    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.barh(list(status.index), status.values, color=list(STATUS_COLORS.values()),
                   height=0.55)
    ax.bar_label(bars, padding=7, fontsize=11)
    ax.invert_yaxis()
    ax.set_xlim(0, max(25, status.max() * 1.18))
    ax.set_xlabel("States")
    count_axis(ax)
    figures.append(save(
        fig, out, "state_source_status", "Fifty-state source progress",
        "A closed source scope is not a completed state study",
        "Source: current STATE_PROGRESS.md. Closed scopes: CA, CO, NC, OH, SD, WI. "
        "Partial and blocked scopes retain explicit gaps; zero states are scientifically complete.",
    ))

    fig, axes = plt.subplots(1, 3, figsize=(14, 16), sharey=True, sharex=True)
    columns = [
        ("n_cycle_evidence_candidate_contexts", "Calendar candidates", theme.MUTED),
        ("n_cycle_contexts_with_nonempty_abstract", "Have an abstract", theme.BLUE),
        ("n_cycle_contexts_with_indexed_native_text", "Have retained native text", theme.GREEN),
    ]
    y = np.arange(len(metadata))
    for ax, (column, title, color) in zip(axes, columns, strict=True):
        values = metadata[column]
        known = values.notna()
        ax.barh(y[known], values[known], color=color, height=0.65)
        for position in y[~known]:
            ax.text(0, position, "not supplied", va="center", fontsize=7, color=theme.MUTED)
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_xlabel("Retained contexts", fontsize=10)
        count_axis(ax)
        ax.tick_params(axis="x", labelsize=8)
    axes[0].set_yticks(y, metadata["state"], fontsize=8)
    axes[0].invert_yaxis()
    figures.append(save(
        fig, out, "bill_evidence_by_state", "The retained 2023-2024 bill evidence",
        "Distinct candidate contexts, not source views or a certified introduced-bill universe",
        "Source: hash-bound study-abstract-evidence v4 state matrix. Abstract and native-text "
        "columns overlap and must not be added together. Missing native channels stay unknown, "
        "not zero. No calendar candidates means no qualifying date evidence, not no activity.",
    ))

    observed = native[native["native_source_record_observations"].gt(0)].copy()
    fig, ax = plt.subplots(figsize=(11, 6))
    base = observed["distinct_native_source_identity_observations"]
    repeated = observed["duplicate_identity_observations_preserved"]
    ax.barh(observed["state"], base, color=theme.BLUE, label="Native identities")
    ax.barh(observed["state"], repeated, left=base, color=theme.GOLD,
            label="Repeated observations")
    for position, (_, row) in enumerate(observed.iterrows()):
        total = int(row["native_source_record_observations"])
        repeat = int(row["duplicate_identity_observations_preserved"])
        label = f"{total:,}" + (f" ({repeat:,} repeated)" if repeat else "")
        ax.text(total + 60, position, label, va="center", fontsize=10)
    ax.invert_yaxis()
    ax.set_xlim(0, observed["native_source_record_observations"].max() * 1.40)
    ax.set_xlabel("Publisher metadata observations")
    ax.legend(loc="lower right")
    count_axis(ax)
    figures.append(save(
        fig, out, "native_inventory_observations",
        "Recovered metadata without inflated bill counts",
        "Six sources returned measure metadata; other source channels remain separately accounted",
        "Source: native inventory catalog v2. LA ACT subsets and NV prefix repetitions are "
        "preserved, not additional identities. HI covers passed bills only; its separate "
        "filename inventory is excluded. These are not introduced-bill or original-text counts.",
    ))

    supplied = sessions[sessions["session_members"].notna()]
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.barh(supplied["state"], supplied["also_calendar_candidates"], color=theme.BLUE,
            label="Also calendar candidates")
    ax.barh(supplied["state"], supplied["session_only_members"],
            left=supplied["also_calendar_candidates"], color=theme.GOLD,
            label="Session frame only")
    for position, value in enumerate(supplied["session_members"]):
        ax.text(value + 300, position, f"{int(value):,}", va="center", fontsize=11)
    ax.invert_yaxis()
    ax.set_xlim(0, supplied["session_members"].max() * 1.16)
    ax.set_xlabel("Retained session-member contexts")
    ax.legend(loc="lower right")
    count_axis(ax)
    figures.append(save(
        fig, out, "session_calendar_comparison", "Session membership and calendar evidence differ",
        "Only the explicitly reviewed NY 2023-2024, IL 103rd and TX 88R scopes",
        "Source: verified-session-comparison v3. Session-only membership does not establish "
        "filing dates or admission to the primary calendar cohort. The other 47 states lack "
        "a supplied scope in this comparison, not legislative activity.",
    ))

    fig, ax = plt.subplots(figsize=(11, 6))
    first = diagnostics[diagnostics["model"] == "Mixed full-document"].set_index("dataset")
    second = diagnostics[diagnostics["model"] == "Reviewed-only"].set_index("dataset")
    order = list(DATASETS)
    labels = [f"{DATASETS[key]} (n={first.loc[key, 'n_eligible']})" for key in order]
    charts.dumbbell(
        ax, labels, first.loc[order, "decision_accuracy"] * 100,
        second.loc[order, "decision_accuracy"] * 100,
        left_color=theme.BLUE, right_color=theme.GOLD,
        left_label="Mixed full-document", right_label="Reviewed-only",
    )
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(PercentFormatter())
    ax.set_xlabel("Correct topic or correct abstention")
    ax.legend(loc="lower right")
    figures.append(save(
        fig, out, "classifier_development_diagnostics", "Classifier candidates show mixed results",
        "Saved assistant-reviewed development diagnostics, not independent validation",
        "Source: the two frozen complete-document evaluation comparisons. Thresholds remain "
        "confidence 0.8 / margin 0.2 / temperature 1. Native results exclude three disputed "
        "references. These inspected sets cannot certify population accuracy; neither model "
        "is promoted. Coverage and denominators remain in the complete CSV export.",
    ))

    native_metrics = diagnostics[diagnostics["dataset"] == "cycle_native_39"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, metric, title in zip(
        axes, ("classified_precision", "coverage"),
        ("Correct among classified", "Share receiving a topic"), strict=True,
    ):
        bars = ax.barh(
            native_metrics["model"], native_metrics[metric] * 100,
            color=[MODEL_COLORS[name] for name in native_metrics["model"]], height=0.5,
        )
        for bar, (_, row) in zip(bars, native_metrics.iterrows(), strict=True):
            numerator = row["n_correct_topic"] if metric == "classified_precision" else (
                row["n_classified"]
            )
            denominator = row["n_classified"] if metric == "classified_precision" else (
                row["n_eligible"]
            )
            ax.text(
                2, bar.get_y() + bar.get_height() / 2, f"{numerator}/{denominator}",
                va="center", color=theme.TEXT if row["model"] == "Reviewed-only" else "white",
                fontsize=11,
            )
        ax.set_xlim(0, 100)
        ax.xaxis.set_major_formatter(PercentFormatter())
        ax.set_title(title, fontsize=12)
        ax.grid(axis="x", color=theme.GRID, linewidth=0.5)
        ax.set_axisbelow(True)
    axes[0].invert_yaxis()
    figures.append(save(
        fig, out, "native_precision_and_coverage", "Native-text precision and abstention",
        "The same 36 agreed development references; three disputes remain unscored",
        "Source: primary_agreed_metrics in the fixed saved comparisons. Precision is "
        "conditional on classification; coverage uses all 36 agreed inputs. These small, "
        "assistant-reviewed development samples are not independent human validation.",
    ))

    builder = runpy.run_path(str(Path(__file__).with_name("plot_platform_coverage.py")))[
        "build_figure"
    ]
    note = (
        "Source: retained Harvard Dataverse historical platform corpus; major D/R records "
        "only. Original archive years, including missing state-party observations, are "
        "preserved. This reproduces a historical corpus view, not operative 2023-2024 "
        "platform coverage. No new collection or later-platform substitution."
    )
    for suffix in ("png", "svg"):
        builder(historical, out / f"platform_corpus_recency.{suffix}", source=note)
    figures.append({
        "name": "platform_corpus_recency",
        "title": "Historical platform corpus recency",
        "subtitle": "Recreated original graph from the retained historical corpus",
        "source_note": note,
    })
    for figure in figures:
        figure["chart_data"] = f"chart-data/{CHART_TABLES[figure['name']]}.csv"
    return figures


def gallery(output: Path, figures: list[dict], legacy: list[str], research: dict):
    def card(name, title, text, directory, extra=""):
        return (
            f'<article><h2>{html.escape(title)}</h2><p>{html.escape(text)}</p>'
            f'<a href="{directory}/{name}.png"><img src="{directory}/{name}.png" '
            f'alt="{html.escape(title)}" loading="lazy"></a>{extra}</article>'
        )

    fresh = "".join(card(
        row["name"], row["title"], row["subtitle"], "graphs",
        f'<p><a href="graphs/{row["name"]}.svg">SVG</a> | '
        f'<a href="{row["chart_data"]}" download>Complete chart data (CSV)</a></p>',
    ) for row in figures)
    old = "".join(card(Path(name).stem, Path(name).stem.replace("_", " "),
                       "Unchanged old image; not regenerated or revalidated.", "legacy-reference")
                  for name in legacy)
    downloads = "".join(
        f'<li><a href="chart-data/{path.name}">{path.name}</a></li>'
        for path in sorted((output / "chart-data").glob("*.csv"))
    )
    if (output / "chart-data/missing_retained_text.parquet").is_file():
        downloads += (
            '<li><a href="chart-data/missing_retained_text.parquet" download>'
            'Complete remaining no-retained-text queue (Parquet; no collection authorization)'
            '</a></li>'
        )
    research_downloads = "".join(
        f'<li><a href="{row["path"]}" download>{html.escape(name)}: complete research packet '
        f'(ZIP, {row["bytes"] / 1024 / 1024:.1f} MiB)</a></li>'
        for name, row in research.items()
    )
    (output / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>State politics: recreated graphs</title><style>'
        f'body{{background:{theme.BG};color:{theme.TEXT};font:16px/1.6 Georgia,serif;'
        'max-width:1100px;margin:40px auto;padding:0 24px}'
        f'article{{border-top:1px solid {theme.GRID};padding:20px 0}}'
        f'p{{color:{theme.MUTED}}}img{{max-width:100%;height:auto}}'
        f'a{{color:{theme.BLUE};overflow-wrap:anywhere}}h1,h2{{font-weight:normal}}</style><main>'
        '<p>LOCAL / UNPUBLISHED</p><h1>State politics: recreated graphs</h1>'
        f'<p>{html.escape(NOTICE)}</p><h2>Freshly rendered graphs</h2>{fresh}'
        f'<h2>Complete chart data</h2><ul>{downloads}</ul>'
        '<h2>Complete recovered research records</h2><p>These ZIPs include full evidence '
        'texts, original table rows, actions, votes, sponsorships, or native PDFs and '
        'reader pages as appropriate, plus source manifests. They are not metadata-only '
        'downloads. Caucus evidence remains separate from party platforms; the Kentucky '
        'page states 2024 priorities but does not certify operative adoption. Its capture '
        'remains closed after a generic challenge-literal stop.</p>'
        f'<ul>{research_downloads}</ul>'
        '<h2>Legacy reference images</h2><p>The original numerical inputs for most '
        'analytical figures are missing. These copies preserve the old images only; '
        f'they are not new 2023-2024 findings.</p>{old}</main></html>',
        encoding="utf-8",
    )


def recreate(
    root: Path, output: Path, *, research_corpus: Path | None = None,
    archive_text: tuple[Path, ...] = (),
) -> dict:
    root, output = root.resolve(), output.absolute()
    if output.exists():
        raise FileExistsError("refusing to overwrite an existing graph bundle")
    if output.resolve() != output or not any(
        output.is_relative_to(root / name) and output != root / name
        for name in ("outputs", "data")
    ):
        raise ValueError("use a new non-symlink output directory under project outputs/ or data/")
    inputs = {}
    tracker_path = checked_file(root, "docs/STATE_PROGRESS.md", inputs)
    tracker = read_tracker(tracker_path)
    if not set(tracker["legislative_status"]) <= STATUS_COLORS.keys():
        raise ValueError("source status cannot be omitted from the chart")
    metadata = source_table(root, "metadata", "state_matrix.csv", inputs)
    native = source_table(root, "native", "state_inventory_matrix.csv", inputs)
    sessions = source_table(root, "sessions", "state_comparison.csv", inputs)
    for frame in (metadata, native, sessions):
        if set(frame["state"]) != set(tracker["state"]):
            raise ValueError("state tables disagree with the current fifty-state tracker")
    diagnostics = diagnostic_rows(root, inputs)
    packets = {
        name: recovery_packet(root, directory, inputs, snapshot=name == "snapshot")
        for name, directory in RECOVERED_PACKETS.items()
    }
    if research_corpus is not None:
        research_corpus = research_corpus.absolute()
        if not research_corpus.is_relative_to(root / "data/processed"):
            raise ValueError("research corpus must remain under processed project data")
        packets["research_corpus"] = recovery_packet(
            root, research_corpus.relative_to(root).as_posix(), inputs, corpus=True,
        )
    archive_directories = tuple(directory.absolute() for directory in archive_text)
    for index, directory in enumerate(archive_directories, 1):
        if not directory.is_relative_to(root / "data/processed"):
            raise ValueError("independent archives must remain under processed project data")
        packets[f"independent_archive_{index}"] = recovery_packet(
            root, directory.relative_to(root).as_posix(), inputs, archive=True,
        )
    outcome_manifest = json.loads(packets["outcomes"]["manifest.json"].read_bytes())
    producer = outcome_manifest["inputs"]["producer"]
    producer_path = root / "src/state_politics/analysis/cycle_outcome_evidence.py"
    packets["outcomes"]["source-code/cycle_outcome_evidence.py"] = checked_file(
        root, producer_path.relative_to(root).as_posix(), inputs, producer,
    )
    arkansas = arkansas_rows(packets["arkansas"])
    retained_text, missing_text = snapshot_coverage(
        root, packets["snapshot"], inputs, corpus_directory=research_corpus,
        archive_directories=archive_directories,
    )
    historical_path = checked_file(root, "data/processed/platforms_historical.parquet", inputs)
    historical = coverage_matrix(pd.read_parquet(historical_path))
    legacy = sorted(path for path in (root / "outputs").glob("*.png") if path.is_file())
    for path in legacy:
        checked_file(root, path.relative_to(root).as_posix(), inputs)
    producers = (
        Path(__file__), Path(__file__).with_name("plot_platform_coverage.py"),
        ROOT / "src/state_politics/plotting/theme.py",
        ROOT / "src/state_politics/plotting/charts.py",
    ) + (tuple(
        ROOT / "src/state_politics/bills" / name
        for name in (
            "archive_text.py", "lawatlas_text.py", "maryland_archive_text.py",
            "nj_library_text.py", "nj_library_collection.py", "ok_retained_context_text.py",
            "billcam_text.py", "govbot_text.py", "native_text.py", "published_corpus_text.py",
            "billcommons_text.py", "billcommons_nv_text.py",
            "ne_journal_text.py",
            "ne_journal_collection.py",
        )
    ) + (ROOT / "src/state_politics/platforms/registry.py",) if archive_directories else ())
    for path in producers:
        inputs[f"producer:{path.name}"] = binding(path)
    for name in ("graphs", "chart-data", "legacy-reference", "producers", "research-data"):
        (output / name).mkdir(parents=True)
    for path in producers:
        shutil.copy2(path, output / "producers" / path.name)
    tables = {
        "state_source_status": tracker,
        "bill_evidence_by_state": metadata,
        "native_source_observations": native,
        "session_calendar_comparison": sessions,
        "classifier_metrics": diagnostics,
        "historical_platform_coverage": historical,
        "arkansas_text_by_session": arkansas,
        "retained_text_coverage": retained_text,
    }
    for name, frame in tables.items():
        frame.to_csv(output / "chart-data" / f"{name}.csv", index=False)
    figures = render_graphs(
        output / "graphs", tracker, metadata, native, sessions, diagnostics, historical,
    )
    figures.extend(recovered_graphs(output, packets, arkansas))
    figures.append(snapshot_graph(output, retained_text))
    missing_text.to_parquet(output / "chart-data/missing_retained_text.parquet", index=False)
    research = {
        name: archive_packet(files, output / "research-data" / f"{name}.zip")
        for name, files in packets.items()
    }
    for path in legacy:
        shutil.copy2(path, output / "legacy-reference" / path.name)
    gallery(output, figures, [path.name for path in legacy], research)
    for relative, expected in inputs.items():
        if not relative.startswith("producer:") and binding(root / relative) != expected:
            raise ValueError(f"graph source changed during rendering: {relative}")
    for path in producers:
        if binding(path) != inputs[f"producer:{path.name}"]:
            raise ValueError(f"graph producer changed during rendering: {path.name}")
    artifacts = {
        path.relative_to(output).as_posix(): binding(path)
        for path in sorted(output.rglob("*")) if path.is_file()
    }
    report = {
        "status": "recreated_evidence_graphs_and_separate_legacy_references",
        "notice": NOTICE, "fresh_graphs": figures, "legacy_images_copied_not_regenerated": [
            path.name for path in legacy
        ],
        "complete_chart_tables": sorted(
            path.stem for path in (output / "chart-data").glob("*.csv")
        ),
        "complete_research_packets": research, "inputs": inputs, "artifacts": artifacts,
        "missing_retained_text_queue": {
            "path": "chart-data/missing_retained_text.parquet", "contexts": len(missing_text),
            "automatic_collection_authorized": False,
        },
        "source_collection": False, "model_execution": False, "model_promotion": False,
        "publication": False, "scientific_certification": "not_performed",
    }
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "outputs/recreated-2023-2024")
    parser.add_argument(
        "--research-corpus", type=Path,
        help="Optional header-joined research-corpus recovery; no publisher/model approval",
    )
    parser.add_argument(
        "--archive-text", type=Path, action="append", default=[],
        help="Complete independent archive; repeat for alternatives, de-duplicated by bill ID",
    )
    args = parser.parse_args(argv)
    result = recreate(
        ROOT, args.out_dir, research_corpus=args.research_corpus,
        archive_text=tuple(args.archive_text),
    )
    print(f"Wrote {len(result['fresh_graphs'])} fresh PNG/SVG graphs and "
          f"{len(result['legacy_images_copied_not_regenerated'])} separate legacy images "
          f"to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

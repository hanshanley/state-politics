#!/usr/bin/env python3
"""Regenerate the current, dual-background graph collection from pinned saved tables."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import sys
import textwrap
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.ticker import StrMethodFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from state_politics.plotting import theme  # noqa: E402

BACKGROUNDS = {"substack": "#F7F5F0", "themarginoferror": "#F5F5F5"}
SOURCES = {
    "evidence": (
        "recreated-2023-2024-v36",
        "7195df736637821c2bd345b7a282b38382da8757b467f1f83e07843143c52ed1",
    ),
    "topics": (
        "topic-inference-retained-text-2023-2024-v23",
        "c02cb6b755b2167ab10bea579ba470482637b74b1d24f35a7189e372add3cefc",
    ),
    "majority": (
        "topic-majority-2023-2024-v7",
        "4790c23da21afd83f97c95fd69ceb111dbe6b84f53468da42620c106b65dfccb",
    ),
    "scores": (
        "topic-score-diagnostics-2023-2024-v7",
        "a9ff25deb1037b6260ec0e7254c825fa4b1712fb8657a429024c0531cf77c216",
    ),
    "inputs": (
        "topic-input-comparison-2023-2024-v21",
        "ccc977cb8c595f8128b712c04ab842339fc7af7a7f057d62ab36d074339a0319",
    ),
    "context": (
        "topic-context-pilot-2023-2024-v1",
        "ef7857499a3783fed82a8884979b01f3f7b72c7c46afce16246fd24e24be5a6e",
    ),
}
TABLES = {
    "evidence": (
        "state_source_status",
        "bill_evidence_by_state",
        "native_source_observations",
        "session_calendar_comparison",
        "classifier_metrics",
        "historical_platform_coverage",
        "platforms_modern_collection_status_counts",
        "platforms_capture_ledger",
        "platforms_modern_metadata_year_counts",
        "outcomes_pooled_recorded_stages",
        "outcomes_state_recorded_stages",
        "arkansas_text_by_session",
        "retained_text_coverage",
    ),
    "topics": (
        "retained_text_topic_counts",
        "retained_text_classification_coverage",
        "retained_text_state_topics",
    ),
    "majority": (
        "status_comparison",
        "topic_comparison",
        "new_assignment_origins",
        "state_comparison",
        "transitions",
        "selected_assistant_comparison",
    ),
    "scores": ("decision_reasons", "output_scores", "state_output_scores"),
    "inputs": (
        "topic_shares",
        "topic_transitions",
        "national_summary",
        "state_summary",
        "state_topic_shares",
        "state_topic_transitions",
    ),
    "context": ("profile_summary", "encoder_work", "context_comparison", "rescue_only_comparison"),
}
COLORS = [
    theme.BLUE,
    theme.GOLD,
    theme.GREEN,
    theme.ACCENT,
    "#8D809B",
    theme.MUTED,
    "#B5ADA0",
    "#D6D3CC",
    "#889B9A",
    "#C6B693",
]
NOTICE = (
    "2023-2024 research snapshot. Provisional assignments and assistant-reviewed "
    "diagnostics are not independently validated findings. No party-policy comparison "
    "or website publication is approved."
)


def binding(path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": digest, "bytes": path.stat().st_size}


def load_tables(root=ROOT):
    """Validate external manifest pins and copy no inferred or recalculated labels."""
    tables, bindings, manifests = {}, {}, {}
    for group, (folder, pin) in SOURCES.items():
        directory = root / "outputs" / folder
        manifest_path = directory / "manifest.json"
        if binding(manifest_path)["sha256"] != pin:
            raise ValueError(f"source manifest changed: {group}")
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("publication", False) or manifest.get("model_promotion", False):
            raise ValueError("unapproved saved graph sources required")
        manifests[group] = manifest
        bindings[str(manifest_path.relative_to(root))] = binding(manifest_path)
        for name in TABLES[group]:
            path = directory / f"chart-data/{name}.csv"
            actual = binding(path)
            if actual != manifest["artifacts"][f"chart-data/{name}.csv"]:
                raise ValueError(f"chart table changed: {group}/{name}")
            bindings[str(path.relative_to(root))] = actual
            tables[group, name] = pd.read_csv(path)
    status = tables["majority", "status_comparison"]
    if status["baseline_contexts"].sum() != 157598 or status["candidate_contexts"].sum() != 157598:
        raise ValueError("complete original context denominator required")
    return tables, bindings, manifests


def axes(rows=6, *, panels=1, height=None, width=11):
    fig, axs = plt.subplots(
        1,
        panels,
        figsize=(width, height or max(4.3, min(13, 2.3 + rows * 0.27))),
        squeeze=False,
    )
    for ax in axs.flat:
        ax.set_axisbelow(True)
        ax.grid(axis="x", linewidth=0.5, alpha=0.6)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(labelsize=10, pad=5)
        ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    return fig, list(axs.flat)


def population_counts(tables):
    status = tables["majority", "status_comparison"]
    if not status.status.is_unique:
        raise ValueError("one row per original/candidate disposition required")
    status = status.set_index("status")
    contexts = int(status.baseline_contexts.sum())
    if int(status.candidate_contexts.sum()) != contexts:
        raise ValueError("same original context population required")
    assigned = int(status.loc["classified", "baseline_contexts"])
    candidate = int(status.loc["classified", "candidate_contexts"])
    missing = int(status.loc["unavailable", "baseline_contexts"])
    if int(status.loc["unavailable", "candidate_contexts"]) != missing or candidate < assigned:
        raise ValueError("majority must preserve missing inputs and baseline assignments")
    return {
        "original_candidate_contexts": contexts,
        "original_assigned": assigned,
        "original_abstained": contexts - assigned - missing,
        "majority_candidate_assigned": candidate,
        "majority_additional_assignments": candidate - assigned,
        "missing_retained_text": missing,
        "available_retained_text": contexts - missing,
    }


def bars(ax, labels, values, *, colors=theme.BLUE, xlabel="Candidate bill contexts"):
    labels = [textwrap.fill(str(label), 32) for label in labels]
    positions = np.arange(len(labels))
    result = ax.barh(positions, values, color=colors, height=0.62)
    ax.set_yticks(positions, labels)
    ax.invert_yaxis()
    maximum = max(values, default=0)
    ax.set_xlim(0, max(1, maximum * 1.15))
    ax.set_xlabel(xlabel, fontsize=11)
    ax.bar_label(result, labels=[f"{v:,.0f}" for v in values], padding=5, fontsize=9)
    return result


def stacked(ax, labels, frame, categories, *, percent=False):
    positions, left = np.arange(len(labels)), np.zeros(len(labels))
    denominator = frame[[key for key, _ in categories]].sum(axis=1).replace(0, np.nan)
    for i, (key, label) in enumerate(categories):
        values = frame[key].astype(float)
        if percent:
            values = (values / denominator * 100).fillna(0)
        ax.barh(positions, values, left=left, color=COLORS[i], height=0.66, label=label)
        left += values.to_numpy()
    ax.set_yticks(positions, [textwrap.fill(str(v), 30) for v in labels])
    ax.invert_yaxis()
    ax.set_xlim(0, 100 if percent else max(1, max(left, default=1) * 1.03))
    if percent:
        ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
        for i, value in enumerate(denominator):
            if pd.isna(value):
                ax.text(2, i, "no candidates supplied", va="center", fontsize=8)
    ax.set_xlabel(
        "Share of candidate contexts" if percent else "Retained observations", fontsize=10
    )


def paired(
    ax,
    labels,
    first,
    second,
    *,
    names=("Frozen unanimity", "Majority candidate"),
    xlabel="Provisional candidate-bill assignments",
    colors=(theme.MUTED, theme.BLUE),
):
    positions = np.arange(len(labels))
    for offset, values, color, label in (
        (-0.17, first, colors[0], names[0]),
        (0.17, second, colors[1], names[1]),
    ):
        ax.barh(positions + offset, values, height=0.29, color=color, label=label)
    ax.set_yticks(positions, [textwrap.fill(str(v), 34) for v in labels])
    ax.invert_yaxis()
    ax.set_xlabel(xlabel, fontsize=11)
    ax.margins(x=0.04)


def parts(frame, count):
    return [frame.iloc[index] for index in np.array_split(np.arange(len(frame)), count)]


def heatmap(frame, *, xlabel, ylabel, label, percent=True, size=(13, 12)):
    fig, ax = plt.subplots(figsize=size)
    cmap = LinearSegmentedColormap.from_list("current_topics", ["#FFFFFF", theme.BLUE])
    cmap.set_bad("#D6D3CC")
    values = np.ma.masked_invalid(frame.to_numpy(dtype=float))
    image = ax.imshow(values * (100 if percent else 1), aspect="auto", cmap=cmap, vmin=0)
    ax.set_xticks(
        range(len(frame.columns)),
        [textwrap.fill(str(v), 22) for v in frame.columns],
        rotation=55,
        ha="right",
        fontsize=8.5,
    )
    ax.set_yticks(
        range(len(frame.index)), [textwrap.fill(str(v), 24) for v in frame.index], fontsize=9
    )
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    fig.colorbar(image, ax=ax, fraction=0.028, pad=0.025, label=label)
    return fig


def specifications(tables):
    """Yield actual figures and exact complete input tables for every current family."""
    counts = population_counts(tables)
    versions = {group: folder.rsplit("-", 1)[-1] for group, (folder, _) in SOURCES.items()}

    def get(group, name):
        return tables[group, name].copy()

    def item(group, name, fig, title, subtitle, note, *names):
        return dict(
            group=group,
            name=name,
            fig=fig,
            title=title,
            subtitle=subtitle,
            note=note,
            tables=[f"chart-data/{group}/{n}.csv" for n in names],
        )

    f = get("majority", "topic_comparison").sort_values("candidate_contexts", ascending=False)
    fig, (ax,) = axes(len(f))
    paired(ax, f.label, f.baseline_contexts, f.candidate_contexts)
    yield item(
        "majority",
        "topic_comparison",
        fig,
        "Which topics receive a bill assignment?",
        f"Same {counts['original_candidate_contexts']:,} contexts; original rule and "
        "unpromoted majority candidate",
        f"Source: frozen majority {versions['majority']}. Topic counts are provisional, "
        f"not policy prevalence or party positions. All {counts['original_assigned']:,} "
        "original-rule assignments are retained.",
        "topic_comparison",
    )

    f = get("majority", "status_comparison")
    fig, (ax,) = axes(height=4.4)
    wide = pd.DataFrame(
        {
            "Frozen unanimity": f.baseline_contexts.to_numpy(),
            "Majority candidate": f.candidate_contexts.to_numpy(),
        },
        index=f.status,
    ).T
    labels = f.label.where(f.status.ne("uncertain"), "Other abstentions / uncertainty")
    stacked(ax, wide.index, wide, list(zip(f.status, labels, strict=True)))
    for i, column in enumerate(("baseline_contexts", "candidate_contexts")):
        count = int(f.loc[f.status.eq("classified"), column].iloc[0])
        ax.text(
            count / 2,
            i,
            f"{count:,}\nassigned",
            color="white",
            ha="center",
            va="center",
            fontsize=11,
        )
    ax.set_xlabel(
        f"Original candidate contexts; each row totals {counts['original_candidate_contexts']:,}"
    )
    yield item(
        "majority",
        "decision_comparison",
        fig,
        "What changes under majority voting?",
        f"{counts['majority_additional_assignments']:,} additional topic assignments; "
        "the candidate is not validated",
        f"Source: majority {versions['majority']}. The baseline separates rejection and "
        f"other abstentions; all {counts['original_abstained']:,} unanimity abstentions "
        "remain inspectable.",
        "status_comparison",
    )

    f = get("majority", "new_assignment_origins").query("new_assignments > 0")
    f = f.sort_values("new_assignments", ascending=False)
    fig, (ax,) = axes(len(f))
    bars(ax, f.label, f.new_assignments, xlabel="Previously abstained contexts")
    yield item(
        "majority",
        "new_assignments",
        fig,
        "Where the new assignments come from",
        "Reasons recorded under the original unanimity rule",
        f"Source: majority {versions['majority']}. Fewer abstentions do not establish "
        "better accuracy. "
        "Conditional supporting-window gates are not whole-document confidence.",
        "new_assignment_origins",
    )

    for group, table, name, title, categories in (
        (
            "majority",
            "state_comparison",
            "state_classification_coverage",
            "Majority decisions, state by state",
            [
                ("candidate_assigned", "Topic assigned"),
                ("model_rejected", "Model rejection"),
                ("uncertain", "Uncertain"),
                ("excluded", "Excluded"),
                ("unavailable", "No text"),
            ],
        ),
        (
            "topics",
            "retained_text_classification_coverage",
            "classification_coverage",
            "Original assignments and abstentions, state by state",
            [
                ("classified", "Topic assigned"),
                ("abstained", "Abstained"),
                ("unavailable", "No text"),
            ],
        ),
    ):
        f = get(group, table).sort_values("state")
        fig, axs = axes(25, panels=2, width=12.5)
        for ax, part in zip(axs, parts(f, 2), strict=True):
            stacked(ax, part.state, part, categories, percent=True)
        yield item(
            group,
            name,
            fig,
            title,
            "All fifty states; common 0-100% scale",
            f"Source: full-body topic gallery {versions['topics']} / majority "
            f"{versions['majority']}. Denominator is each "
            "state's retained candidate contexts, not a complete introduced-bill universe. "
            "No supplied candidates does not mean no activity.",
            table,
        )

    f = get("topics", "retained_text_topic_counts").sort_values(
        "model_assigned_contexts", ascending=False
    )
    fig, (ax,) = axes(len(f))
    bars(ax, f.topic_name, f.model_assigned_contexts)
    yield item(
        "topics",
        "topic_counts",
        fig,
        "Original full-text topic assignments",
        f"{counts['original_assigned']:,} assigned; "
        f"{counts['original_abstained']:,} abstained; "
        f"{counts['missing_retained_text']:,} without retained body text",
        f"Source: complete retained-text topic gallery {versions['topics']}. "
        "Frozen unanimity, not the "
        "majority candidate. No independent human validation or party attribution.",
        "retained_text_topic_counts",
    )

    f = get("topics", "retained_text_state_topics")
    matrix = f.pivot(index="state", columns="topic_name", values="share_of_all_candidates")
    fig = heatmap(
        matrix,
        xlabel="Assigned topic",
        ylabel="State",
        label="Assigned topic / all candidate contexts (%)",
    )
    yield item(
        "topics",
        "state_topics",
        fig,
        "The original topic profile across states",
        "All candidate contexts in the denominator; grey means no scored inputs",
        f"Source: full-body topic gallery {versions['topics']}. Missing inputs and "
        "abstentions are not "
        "redistributed across topics. This is a model-output diagnostic, not party policy.",
        "retained_text_state_topics",
    )

    for table, value, title, subtitle, note in (
        (
            "decision_reasons",
            "contexts",
            "Why the original model did not assign every bill",
            "Every original context is retained, including missing text and exclusions",
            f"Source: full-score diagnostics {versions['scores']}. Reasons are model/source "
            "dispositions, not "
            "human judgments about whether a bill has a substantive topic.",
        ),
        (
            "output_scores",
            "mean_context_score",
            "All 22 outputs, including model rejection",
            "Complete score vectors, not only the accepted topic",
            f"Source: full-score diagnostics {versions['scores']}; "
            f"{int(tables['scores', 'output_scores'].scored_contexts.iloc[0]):,} scored "
            "contexts. Whiskers represent "
            "source variation, not confidence intervals. Scores are uncalibrated; "
            "rejection stays in.",
        ),
    ):
        f = get("scores", table).sort_values(value, ascending=False)
        fig, (ax,) = axes(len(f))
        values = f[value] * (100 if table == "output_scores" else 1)
        colors = [
            theme.MUTED if pd.isna(v) else theme.BLUE
            for v in f.get("output_code", pd.Series([1] * len(f)))
        ]
        bars(
            ax,
            f.label,
            values,
            colors=colors,
            xlabel="Mean uncalibrated output score (%)"
            if table == "output_scores"
            else "Original candidate contexts",
        )
        if table == "output_scores":
            ax.errorbar(
                values,
                np.arange(len(f)),
                xerr=np.maximum(
                    0,
                    np.array(
                        [
                            f[value] - f.mean_source_minimum,
                            f.mean_source_maximum - f[value],
                        ]
                    )
                    * 100,
                ),
                fmt="none",
                ecolor=theme.TEXT,
                elinewidth=0.8,
                capsize=2,
            )
            for mean, upper, number in zip(
                values,
                f.mean_source_maximum * 100,
                ax.texts,
                strict=True,
            ):
                number.set_text("<0.1" if 0 < mean < 0.05 else f"{mean:.1f}")
                number.xy = (upper, number.xy[1])
        yield item("scores", table, fig, title, subtitle, note, table)

    f = get("inputs", "topic_shares").sort_values(
        "retained_text_assigned_contexts", ascending=False
    )
    fig, (ax,) = axes(len(f))
    paired(
        ax,
        f.topic_name,
        f.metadata_share_of_paired * 100,
        f.retained_text_share_of_paired * 100,
        names=("Title / abstract", "Retained full text"),
        xlabel="Share of exactly paired candidate contexts (%)",
    )
    yield item(
        "inputs",
        "topic_shares",
        fig,
        "Titles and full texts do not give the same profile",
        "Exactly paired inputs; agreement is not accuracy",
        f"Source: input comparison {versions['inputs']}. Both tiers use the frozen "
        "unanimity rule. "
        "Unavailable inputs stay outside the paired denominator; no majority substitution.",
        "topic_shares",
        "national_summary",
    )
    f = get("inputs", "topic_transitions")
    matrix = f.pivot(
        index="metadata_topic_name",
        columns="retained_text_topic_name",
        values="share_of_metadata_row",
    )
    fig = heatmap(
        matrix,
        xlabel="Retained full-text output",
        ylabel="Title / abstract output",
        label="Share within each metadata-output row (%)",
        size=(13, 12),
    )
    yield item(
        "inputs",
        "topic_transitions",
        fig,
        "How assignments change with the input",
        "Abstention is retained as an output; rows have separate denominators",
        f"Source: input comparison {versions['inputs']}. Descriptive transitions, "
        "not validated corrections. "
        "The complete CSV preserves transition counts and every row denominator.",
        "topic_transitions",
    )

    f = get("context", "profile_summary")
    fig, (ax,) = axes(height=5)
    stacked(
        ax,
        ["Unanimity / 1,024", "Majority / 1,024", "Majority / 4,096", "Majority / 8,192"],
        f,
        [
            ("same_assigned_topic", "Matches assistant proposal"),
            ("different_assigned_topic", "Differs from assistant proposal"),
            ("assigned_advisory_unresolved", "Assistant unresolved"),
            ("unassigned", "Not assigned"),
        ],
    )
    ax.set_xlabel("Same selected 109 contexts; assistant agreement is not accuracy")
    yield item(
        "context",
        "context_comparison",
        fig,
        "Longer context adds assignments and differences",
        "Selected pilot only; no population result or model has been replaced",
        "Source: context pilot v1. The 109 selected contexts are not a representative "
        "accuracy sample. Assistant proposals are not independent human gold.",
        "profile_summary",
        "context_comparison",
        "rescue_only_comparison",
    )
    f = get("context", "encoder_work")
    fig, (ax,) = axes(height=4.3)
    bars(
        ax, f.profile, f.new_encoder_windows, xlabel="Additional encoder windows actually executed"
    )
    yield item(
        "context",
        "encoder_work",
        fig,
        "The measured cost of longer context",
        "Exact cached windows were reused, not counted as new work",
        "Source: context pilot v1. Complete tokens, padded tokens and elapsed encoder "
        "seconds remain in the CSV. This graph build executes no model.",
        "encoder_work",
    )

    f = get("evidence", "state_source_status")
    status_counts = f.legislative_status.value_counts()
    fig, (ax,) = axes(height=4.5)
    bars(
        ax,
        status_counts.index,
        status_counts.values,
        xlabel="States with each recorded source status",
    )
    yield item(
        "evidence",
        "state_source_status",
        fig,
        "Fifty-state source progress",
        "Closed collection scopes are not completed studies",
        f"Source: saved fifty-state tracker in evidence {versions['evidence']}. "
        "Blocked and partial scopes "
        "retain explicit gaps; no status certifies scientific completeness.",
        "state_source_status",
    )
    f = get("evidence", "bill_evidence_by_state")
    fig, axs = axes(50, panels=3, width=13, height=12.5)
    for ax, key, title in zip(
        axs,
        [
            "n_cycle_evidence_candidate_contexts",
            "n_cycle_contexts_with_nonempty_abstract",
            "n_cycle_contexts_with_indexed_native_text",
        ],
        ["Calendar candidates", "Abstract supplied", "Native text supplied"],
        strict=True,
    ):
        ax.barh(np.arange(len(f)), f[key], color=theme.BLUE, height=0.7)
        ax.set_yticks(range(len(f)), f.state, fontsize=8.5)
        ax.invert_yaxis()
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("Contexts", fontsize=10)
        ax.tick_params(axis="x", labelsize=8)
        ax.set_xlim(0, f.n_cycle_evidence_candidate_contexts.max() * 1.03)
        for i in np.flatnonzero(f[key].isna()):
            ax.text(0, i, "not supplied", fontsize=7, va="center")
    yield item(
        "evidence",
        "bill_evidence_by_state",
        fig,
        "The retained 2023-2024 bill evidence",
        "Separate overlapping metadata/native channels; not the final recovered-text totals",
        f"Source: original metadata v4 matrix in evidence {versions['evidence']}. "
        "These columns overlap and "
        "must not be added. Later recovered text appears in the separate coverage chart.",
        "bill_evidence_by_state",
    )

    for table, name, title, label_column, categories, note in (
        (
            "native_source_observations",
            "native_inventory_observations",
            "Publisher identities without inflated bill counts",
            "state",
            [
                ("distinct_native_source_identity_observations", "Distinct source identities"),
                ("duplicate_identity_observations_preserved", "Repeated observations"),
            ],
            "Native inventory v2. Only sources with observations are plotted. Repetitions are "
            "not new bills; unobserved source channels are not zero legislative activity.",
        ),
        (
            "session_calendar_comparison",
            "session_calendar_comparison",
            "Session membership and calendar evidence differ",
            "state",
            [
                ("also_calendar_candidates", "Also calendar candidates"),
                ("session_only_members", "Session frame only"),
            ],
            "Verified sessions v3: NY 2023-24, IL 103rd and TX 88R only. Other states lack a "
            "supplied comparison scope. Session membership does not establish filing dates.",
        ),
        (
            "arkansas_text_by_session",
            "arkansas_native_text",
            "Arkansas: text recovered, gaps retained",
            "native_session_identifier",
            [
                ("complete_pdf_contexts", "Complete PDF / both readers"),
                ("metadata_only_contexts", "Metadata only"),
            ],
            "Native-text-ar v3. 149 complete PDFs, 298 reader alternatives. The closed batch "
            "does not complete the 1,991-context inventory or certify filing-time versions.",
        ),
        (
            "retained_text_coverage",
            "retained_snapshot_text_coverage",
            "Recovered text without double-counting bills",
            "state",
            [
                ("both_sources", "Native + snapshot"),
                ("snapshot_only", "Snapshot only"),
                ("native_only", "Native only"),
                ("independent_only", "Independent corpus / archive"),
                ("neither_source_observed", "No retained text"),
            ],
            f"Evidence {versions['evidence']}: {counts['available_retained_text']:,} of "
            f"{counts['original_candidate_contexts']:,} contexts have text. Exact bill IDs "
            "de-duplicate "
            "source channels. Missing or later-version text is not publisher-original "
            "certification.",
        ),
    ):
        f = get("evidence", table)
        if table == "native_source_observations":
            f = f[f.native_source_record_observations.gt(0)]
        elif table == "session_calendar_comparison":
            f = f[f.session_members.notna()]
        elif table == "retained_text_coverage":
            f["independent_only"] = f.research_corpus_only + f.independent_archive_only
        fig, axs = axes(
            25 if len(f) > 25 else len(f),
            panels=2 if len(f) > 25 else 1,
            width=12 if len(f) > 25 else 11,
        )
        for ax, part in zip(axs, parts(f, len(axs)), strict=True):
            stacked(ax, part[label_column], part, categories)
            ax.set_xlim(0, max(1, f[[key for key, _ in categories]].sum(axis=1).max() * 1.03))
        yield item(
            "evidence",
            name,
            fig,
            title,
            "Complete retained source evidence; unknowns preserved",
            "Source: " + note,
            table,
        )

    f = get("evidence", "classifier_metrics")
    for name, metrics, title in (
        (
            "classifier_development_diagnostics",
            ["decision_accuracy"],
            "Classifier candidates have mixed development results",
        ),
        (
            "native_precision_and_coverage",
            ["classified_precision", "coverage"],
            "Native-text precision and coverage are different",
        ),
    ):
        selected = f if len(metrics) == 1 else f[f.dataset.eq("cycle_native_39")]
        fig, axs = axes(panels=len(metrics), height=4.8, width=12 if len(metrics) == 2 else 11)
        for ax, metric in zip(axs, metrics, strict=True):
            left = selected[selected.model.eq("Mixed full-document")]
            right = selected[selected.model.eq("Reviewed-only")]
            labels = [f"{r.dataset_label} (n={r.n_eligible})" for r in left.itertuples()]
            paired(
                ax,
                labels,
                left[metric] * 100,
                right[metric] * 100,
                names=("Mixed full-document", "Reviewed-only"),
                xlabel=metric.replace("_", " ").capitalize() + " (%)",
            )
            ax.set_xlim(0, 100)
        yield item(
            "evidence",
            name,
            fig,
            title,
            "Saved assistant-reviewed development sets, not independent validation",
            f"Source: frozen development comparisons in evidence {versions['evidence']}. "
            "Native results use "
            "36 agreed references; three disputes remain excluded. Small inspected "
            "samples do not certify population accuracy.",
            "classifier_metrics",
        )

    f = get("evidence", "historical_platform_coverage").query("state != 'US'")
    f = f.sort_values(["latest_any", "state"], na_position="first")
    fig, axs = axes(25, panels=2, width=12)
    for ax, part in zip(axs, parts(f, 2), strict=True):
        for key, color, marker, size in [
            ("latest_D", theme.BLUE, "o", 68),
            ("latest_R", theme.ACCENT, "s", 20),
        ]:
            ax.scatter(
                part[key],
                np.arange(len(part)),
                color=color,
                marker=marker,
                s=size,
                label="Democratic" if key.endswith("D") else "Republican",
            )
        for i, row in enumerate(part.itertuples()):
            if pd.isna(row.latest_any):
                ax.text(1940, i, "no document in corpus", fontsize=8, va="center")
        ax.set_yticks(range(len(part)), part.state)
        ax.invert_yaxis()
        ax.set_xlim(1935, 2020)
        ax.set_xticks([1940, 1960, 1980, 2000, 2017], ["1940", "1960", "1980", "2000", "2017"])
        ax.set_xlabel("Latest archived platform year", fontsize=10)
    yield item(
        "evidence",
        "platform_corpus_recency",
        fig,
        "The historical platform record ends in 2017",
        "Missing state-party documents remain missing",
        "Source: retained Harvard Dataverse corpus. Historical archive recency is not "
        "operative platform coverage for the 2023-2024 study.",
        "historical_platform_coverage",
    )

    for table, name, column, value, title in (
        (
            "platforms_modern_collection_status_counts",
            "modern_collection_outcomes",
            "modern_collection_status",
            "n_organizations",
            "Modern platform collection outcomes",
        ),
        (
            "platforms_modern_metadata_year_counts",
            "modern_collection_metadata_years",
            "metadata_year_band",
            "n_original_rows",
            "Years in the recovered platform metadata",
        ),
    ):
        f = get("evidence", table)
        wide = f.pivot_table(
            index=column, columns="party", values=value, aggfunc="sum", fill_value=0
        )
        fig, (ax,) = axes(len(wide))
        paired(
            ax,
            [v.replace("_", " ") for v in wide.index],
            wide["D"],
            wide["R"],
            names=("Democratic organizations", "Republican organizations"),
            colors=(theme.BLUE, theme.ACCENT),
            xlabel="Organizations" if value == "n_organizations" else "Original metadata rows",
        )
        yield item(
            "evidence",
            name,
            fig,
            title,
            "Recorded source outcomes, not adopted 2023-2024 platforms",
            f"Source: frozen recovered-platform tables in evidence {versions['evidence']}. "
            "Automated filters "
            "and metadata years do not establish adoption, applicability or human validation.",
            table,
        )
    f = get("evidence", "platforms_capture_ledger")
    retained = f.source_sha256.notna()
    identities = int(f.loc[retained, "source_sha256"].nunique())
    values = [identities, int(retained.sum()) - identities, int((~retained).sum())]
    fig, (ax,) = axes(height=4.5)
    bars(
        ax,
        [
            "Distinct retained response bodies",
            "Repeated response bodies",
            "No retained response body",
        ],
        values,
        xlabel="Recorded capture attempts",
    )
    yield item(
        "evidence",
        "retained_response_bodies",
        fig,
        "Retained responses are not distinct platforms",
        f"All {len(f):,} capture attempts; duplicates and failures stay visible",
        f"Source: full platform capture ledger in evidence {versions['evidence']}. "
        "Bodies are de-duplicated "
        "by exact source SHA-256, not a guessed policy or platform identity.",
        "platforms_capture_ledger",
    )

    for table, name, state_view in (
        ("outcomes_pooled_recorded_stages", "pooled_recorded_stages", False),
        ("outcomes_state_recorded_stages", "state_recorded_stages", True),
    ):
        f = get("evidence", table).query("population == 'law_eligible'")
        if state_view:
            matrix = f.pivot(index="state", columns="stage_label", values="share")
            fig = heatmap(
                matrix,
                xlabel="Recorded stage",
                ylabel="State",
                label="Share of law-eligible contexts (%)",
                size=(12, 12),
            )
        else:
            f = f.sort_values("n_contexts", ascending=False)
            fig, (ax,) = axes(len(f))
            bars(ax, f.stage_label, f.n_contexts, xlabel="Law-eligible candidate contexts")
        yield item(
            "evidence",
            name,
            fig,
            "Recorded legislative stages" + (", by state" if state_view else ""),
            "Source action classifications; not certified final legal outcomes",
            "Source: cycle-outcome evidence v2. Law-eligible denominator retained; stages use "
            "all recorded action dates, not only study-window final outcomes. No party comparison.",
            table,
        )


def save_figure(spec, output):
    fig = spec["fig"]
    fig.text(
        0.015,
        0.987,
        spec["title"],
        ha="left",
        va="top",
        fontsize=17,
        fontweight="bold",
        color=theme.TEXT,
    )
    subtitle = fig.text(
        0.015,
        0.987 - 0.34 / fig.get_figheight(),
        textwrap.fill(spec["subtitle"], round(fig.get_figwidth() * 12)),
        va="top",
        fontsize=10.5,
        color=theme.MUTED,
        linespacing=1.4,
    )
    note = fig.text(
        0.015,
        0.012,
        textwrap.fill(spec["note"], round(fig.get_figwidth() * 12)),
        va="bottom",
        fontsize=8.5,
        color=theme.MUTED,
        style="italic",
        linespacing=1.4,
    )
    handles, labels = [], []
    for ax in fig.axes:
        for handle, label in zip(*ax.get_legend_handles_labels(), strict=True):
            if label not in labels:
                handles.append(handle)
                labels.append(label)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    top = subtitle.get_window_extent(renderer).y0 / fig.bbox.height - 0.12 / fig.get_figheight()
    bottom = note.get_window_extent(renderer).y1 / fig.bbox.height + 0.12 / fig.get_figheight()
    if handles:
        for columns in range(min(5, len(labels)), 0, -1):
            legend = fig.legend(
                handles,
                labels,
                loc="lower center",
                bbox_to_anchor=(0.5, bottom),
                ncol=columns,
                frameon=False,
                fontsize=9,
            )
            fig.canvas.draw()
            if legend.get_window_extent(renderer).width <= fig.bbox.width * 0.96:
                break
            legend.remove()
        bottom = legend.get_window_extent(renderer).y1 / fig.bbox.height + (
            0.12 / fig.get_figheight()
        )
    fig.tight_layout(rect=(0.005, bottom, 0.995, top), pad=0.7, w_pad=2)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    text_bounds = []
    visible_text = [*fig.texts, *[text for legend in fig.legends for text in legend.get_texts()]]
    for ax in fig.axes:
        visible_text.extend([ax.title, ax.xaxis.label, ax.yaxis.label, *ax.texts])
        for axis in (ax.xaxis, ax.yaxis):
            low, high = sorted(axis.get_view_interval())
            visible_text.extend(
                label
                for tick in axis.get_major_ticks()
                if low <= tick.get_loc() <= high
                for label in (tick.label1, tick.label2)
            )
    for text in visible_text:
        if text.get_visible() and text.get_text():
            extent = text.get_window_extent(renderer)
            text_bounds.append([float(v) for v in extent.extents])
            if (
                extent.x0 < -1
                or extent.y0 < -1
                or extent.x1 > fig.bbox.width + 1
                or extent.y1 > fig.bbox.height + 1
            ):
                raise ValueError(f"clipped label: {spec['name']} / {text.get_text()}")
    geometry = [[float(v) for v in ax.get_position().bounds] for ax in fig.axes]
    marks = [
        {
            "bars": [
                [
                    float(v) if np.isfinite(v) else None
                    for v in (p.get_x(), p.get_y(), p.get_width(), p.get_height())
                ]
                for p in ax.patches
            ],
            "images": [np.ma.filled(image.get_array(), np.nan).tolist() for image in ax.images],
            "points": [
                [
                    [float(value) if np.isfinite(value) else None for value in row]
                    for row in np.ma.filled(collection.get_offsets(), np.nan)
                ]
                for collection in ax.collections
                if type(collection).__name__ == "PathCollection"
            ],
            "segments": [
                [segment.tolist() for segment in collection.get_segments()]
                for collection in ax.collections
                if hasattr(collection, "get_segments")
            ],
            "x_limits": [float(v) for v in ax.get_xlim()],
            "y_labels": [text.get_text() for text in ax.get_yticklabels()],
        }
        for ax in fig.axes
    ]
    for mark in marks:
        mark["images"] = [
            [[float(value) if np.isfinite(value) else None for value in row] for row in image]
            for image in mark["images"]
        ]
    files = []
    for background, color in BACKGROUNDS.items():
        fig.set_facecolor(color)
        for ax in fig.axes:
            ax.set_facecolor(color)
        directory = output / background / spec["group"]
        directory.mkdir(parents=True, exist_ok=True)
        for suffix in ("png", "svg"):
            path = directory / f"{spec['name']}.{suffix}"
            with plt.rc_context({"svg.fonttype": "none"}):
                fig.savefig(
                    path,
                    dpi=300,
                    facecolor=color,
                    metadata={"Date": None} if suffix == "svg" else None,
                )
            files.append(path.relative_to(output).as_posix())
    plt.close(fig)
    return {key: value for key, value in spec.items() if key != "fig"} | {
        "files": files,
        "canvas_inches": list(fig.get_size_inches()),
        "axes_geometry": geometry,
        "marks": marks,
        "text_bounds": text_bounds,
    }


def gallery(output, figures, *, root=ROOT):
    sections = []
    for group in ("majority", "topics", "evidence", "scores", "inputs", "context"):
        cards = []
        for figure in figures:
            if figure["group"] != group:
                continue
            links = " · ".join(
                f'<a href="{html.escape(name)}">{html.escape(name.split("/")[0])} '
                f"{Path(name).suffix[1:].upper()}</a>"
                for name in figure["files"]
            )
            data = " · ".join(
                f'<a href="{name}">Complete chart CSV'
                f"{' ' + str(i + 1) if len(figure['tables']) > 1 else ''}</a>"
                for i, name in enumerate(figure["tables"])
            )
            image = figure["files"][0]
            cards.append(
                f"<article><h3>{html.escape(figure['title'])}</h3>"
                f"<p>{html.escape(figure['subtitle'])}</p>"
                f'<a href="{image}"><img src="{image}" '
                f'alt="{html.escape(figure["title"])}" loading="lazy"></a>'
                f"<p>{links}</p><p>{data}</p>"
                f'<p class="note">{html.escape(figure["note"])}</p></article>'
            )
        sections.append(
            f'<section id="{group}"><h2>{group.capitalize()}</h2>' + "".join(cards) + "</section>"
        )
    local_links = []
    for group, (folder, _) in SOURCES.items():
        target = root / "outputs" / folder / "index.html"
        href = html.escape(Path(os.path.relpath(target, output)).as_posix())
        local_links.append(f'<a href="{href}">{group}: complete original evidence</a>')
    local = " · ".join(local_links)
    audit_link = html.escape(
        Path(os.path.relpath(root / "docs/AUDIT_STATUS.md", output)).as_posix()
    )
    content = (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>State politics: current graph collection</title>
<style>:root{color-scheme:light;background:#f5f5f5;color:#1a1a1a;font:17px/1.6 Georgia,serif}
body{max-width:1080px;margin:36px auto;padding:0 20px}h1,h2,h3{line-height:1.3}
h2{border-top:1px solid #d6d3cc;padding-top:24px}article{margin:30px 0 48px}
img{width:100%;height:auto;display:block}a{color:#3d6f8c}.note{font-size:14px;color:#626262}
nav{display:flex;flex-wrap:wrap;gap:16px}p{max-width:95ch}</style>
<h1>State politics, 2023-2024</h1>
<p>Current regenerated research graphs. Each chart has a cream Substack version,
a #F5F5F5 The Margin of Error version, a 300-dpi PNG, editable-text SVG and complete
chart data. Both backgrounds use identical data and geometry.</p>
<p class="note">"""
        + html.escape(NOTICE)
        + """</p>
<nav>"""
        + "".join(f'<a href="#{g}">{g.capitalize()}</a>' for g in SOURCES)
        + """</nav>
<p><a href="current-chart-data.zip">All complete chart tables</a> ·
<a href="current-graphs-manifest.json">Provenance and file hashes</a> ·
"""
        + f'<a href="{audit_link}">Scientific gates and legacy status</a></p>'
        + """
"""
        + "".join(sections)
        + """
<h2>Original full-source research packets</h2><p class="note">These separately saved
local bundles contain the complete original policy text, predictions and source
alternatives. They are not replaced by metadata downloads, and are not supplied
by a Git clone. Their historical graphs remain frozen.</p><p>"""
        + local
        + """
</p><h2>Legacy references</h2><p>The thirteen historical PNGs directly in the
outputs directory are legacy, not regenerated findings. Use this index and the
two categorized background folders for the current collection. Unsupported
party/platform comparisons have not been relabelled as current results.</p></html>"""
    )
    (output / "index.html").write_text(content)


def build(output, root=ROOT):
    output = output.absolute()
    if output.resolve() != output or not output.is_relative_to(root / "outputs"):
        raise ValueError("explicit non-symlink output within project outputs required")
    owned = (
        "substack",
        "themarginoferror",
        "chart-data",
        "current-chart-data.zip",
        "current-graphs-manifest.json",
        "index.html",
    )
    if any((output / name).exists() for name in owned):
        raise FileExistsError("refusing to overwrite an existing current graph collection")
    tables, inputs, manifests = load_tables(root)
    output.mkdir(parents=True, exist_ok=True)
    for group, names in TABLES.items():
        destination = output / "chart-data" / group
        destination.mkdir(parents=True)
        folder = root / "outputs" / SOURCES[group][0] / "chart-data"
        for name in names:
            shutil.copyfile(folder / f"{name}.csv", destination / f"{name}.csv")
    with plt.rc_context(
        theme.RC_PARAMS | {"svg.fonttype": "none", "svg.hashsalt": "state-politics"}
    ):
        figures = [save_figure(spec, output) for spec in specifications(tables)]
    gallery(output, figures, root=root)
    with zipfile.ZipFile(
        output / "current-chart-data.zip", "x", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in sorted((output / "chart-data").rglob("*.csv")):
            archive.write(path, path.relative_to(output))
    for path, expected in inputs.items():
        if binding(root / path) != expected:
            raise ValueError(f"source changed during rendering: {path}")
    artifacts = {}
    for name in owned:
        path = output / name
        for file in sorted(path.rglob("*")) if path.is_dir() else [path]:
            if file.is_file():
                artifacts[file.relative_to(output).as_posix()] = binding(file)
    report = {
        "schema": "state-politics.current-graph-collection.v1",
        "status": "complete_regenerated_provisional_graphs_not_validated_findings",
        "study_period": [2023, 2024],
        "notice": NOTICE,
        "backgrounds": BACKGROUNDS,
        "dpi": 300,
        "svg_text_editable": True,
        "figures": figures,
        "inputs": inputs,
        "artifacts": artifacts,
        **population_counts(tables),
        "source_manifests": {
            group: binding(root / "outputs" / folder / "manifest.json")
            for group, (folder, _) in SOURCES.items()
        },
        "producer": binding(Path(__file__)),
        "theme": binding(Path(theme.__file__)),
        "model_execution": False,
        "model_promotion": False,
        "source_collection": False,
        "publication": False,
        "independent_human_validation": False,
        "scientific_certification": "not_performed",
        "original_bundles_and_legacy_images_unchanged": True,
        "original_bundle_statuses": {key: value.get("status") for key, value in manifests.items()},
    }
    (output / "current-graphs-manifest.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "outputs")
    args = parser.parse_args(argv)
    report = build(args.out_dir)
    print(
        f"Regenerated {len(report['figures'])} charts / "
        f"{sum(len(f['files']) for f in report['figures'])} PNG/SVG exports: {args.out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

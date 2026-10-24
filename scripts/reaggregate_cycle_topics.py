#!/usr/bin/env python3
"""Compare strict-majority bill decisions with immutable saved unanimity results."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pyarrow.compute as pc  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import recreate_score_diagnostics as diagnostics  # noqa: E402

from state_politics.analysis import majority_topics  # noqa: E402
from state_politics.analysis.cycle_topics import (  # noqa: E402
    FLAGS,
    binding,
    checked,
    checked_job,
    read,
    records,
    require,
    write_row,
)
from state_politics.analysis.majority_topics import (  # noqa: E402
    POLICY,
    source_majority,
    window_majority,
)
from state_politics.analysis.taxonomy import load_topics  # noqa: E402
from state_politics.bills.openstates_dump import STATE_CODES  # noqa: E402
from state_politics.plotting import theme  # noqa: E402

NOTICE = (
    "Provisional strict-majority candidate, not independent human validation or policy prevalence. "
    "More than half of all windows, then more than half of distinct scored source strings. "
    "The 0.80/0.20 gates now apply to supporting-window scores, not the whole-document mean. "
    "Rejection, minority evidence, original scores and all historical assignments remain intact."
)
STATUSES = ("classified", "model_rejected", "uncertain", "excluded", "unavailable")
STATUS_LABELS = {
    "classified": "Topic assigned", "model_rejected": "Learned model rejection",
    "uncertain": "No accepted majority", "excluded": "Source exclusions",
    "unavailable": "No retained text",
}
ADVISORY = ROOT / "outputs/assistant-advisory-topic-review-2023-2024-v7"
ADVISORY_PIN = "df01ac822204da4b5c92b8d157bce574bb1c164358bbfdc31e1a3870f1e4298b"


def charts(output, baseline, candidate, topics, gains):
    theme.apply()
    colors = (theme.BLUE, theme.MUTED, "#B9B0A1", "#DDD8CD", "#E9E5DC")
    fig, ax = plt.subplots(figsize=(11, 5))
    for y, values in enumerate((baseline, candidate)):
        left = 0
        for status, color in zip(STATUSES, colors, strict=True):
            count = values.get(status, 0)
            ax.barh(y, count, left=left, height=0.5, color=color,
                    label=STATUS_LABELS[status] if y == 0 else None)
            left += count
    ax.set_yticks([0, 1], ["Frozen unanimity", "Strict-majority candidate"])
    ax.invert_yaxis()
    ax.set_xlabel("Same original candidate contexts; no new text or encoder calls")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.03), ncol=3, frameon=False, fontsize=8)
    fig.subplots_adjust(left=0.22, right=0.97, top=0.69, bottom=0.28)
    figures = [("decision_comparison", fig, "Majority rather than unanimity")]
    fig, ax = plt.subplots(figsize=(11, 9))
    ordered = sorted(topics, key=lambda row: row["candidate_contexts"], reverse=True)
    positions = list(range(len(ordered)))
    ax.barh([p - 0.17 for p in positions], [r["baseline_contexts"] for r in ordered],
            height=0.30, color=theme.MUTED, label="Frozen unanimity")
    ax.barh([p + 0.17 for p in positions], [r["candidate_contexts"] for r in ordered],
            height=0.30, color=theme.BLUE, label="Strict majority")
    ax.set_yticks(positions, [r["label"] for r in ordered], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Provisional bill-context assignments, not validated policy attention")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.subplots_adjust(left=0.35, right=0.97, top=0.88, bottom=0.20)
    figures.append(("topic_comparison", fig, "Topic assignments under strict majority"))
    fig, ax = plt.subplots(figsize=(11, 6))
    rows = sorted((row for row in gains if row["new_assignments"]),
                  key=lambda row: row["new_assignments"], reverse=True)
    ax.barh([row["label"] for row in rows], [row["new_assignments"] for row in rows],
            color=theme.BLUE)
    ax.invert_yaxis()
    ax.set_xlabel("Previously abstained contexts receiving a provisional majority topic")
    fig.subplots_adjust(left=0.40, right=0.97, top=0.84, bottom=0.26)
    figures.append(("new_assignments", fig, "Which abstentions the rule changes"))
    for name, figure, title in figures:
        figure.suptitle(title, x=0.03, ha="left", fontsize=16, fontweight="bold")
        theme.source_note(figure, NOTICE, width=115)
        for suffix in ("png", "svg"):
            figure.savefig(output / f"{name}.{suffix}", dpi=160, facecolor=theme.BG)
        plt.close(figure)
    return [name for name, _, _ in figures]


def recreate(directory, gallery, output, gallery_sha256):
    directory, gallery, output = directory.absolute(), gallery.absolute(), output.absolute()
    require(not output.exists() and output.resolve() == output
            and output.is_relative_to(ROOT / "outputs"), "fresh project output required")
    require(binding(gallery / "manifest.json")["sha256"] == gallery_sha256,
            "externally pinned baseline gallery changed")
    baseline_manifest = read(gallery / "manifest.json")
    for name, expected in baseline_manifest["artifacts"].items():
        checked(gallery / name, expected)
    require(baseline_manifest["tiers"] == ["retained_text"], "retained-text baseline required")
    plan = checked_job(directory)
    training = read(Path(plan["checkpoint"]) / "training_manifest.json")
    require(plan["model_run"] == baseline_manifest["model_run"], "mixed baseline model runs")
    progress = read(directory / "progress-retained_text.json")
    states = sorted(state.upper() for state in STATE_CODES)
    require(progress["status"] == "complete_provisional_inference_not_scientific_validation"
            and set(progress["states"]) == set(states), "complete fifty-state baseline required")
    inputs = baseline_manifest["inference_inputs"]
    require(len(inputs) == 108, "complete original inference members required")
    for name, expected in inputs.items():
        checked(directory / name, expected)
    producers = {
        "reaggregate_cycle_topics.py": Path(__file__).absolute(),
        "majority_topics.py": Path(majority_topics.__file__).absolute(),
        "recreate_score_diagnostics.py": Path(diagnostics.__file__).absolute(),
        "theme.py": Path(theme.__file__).absolute(),
    }
    producer_pins = {name: binding(path) for name, path in producers.items()}
    require(binding(ADVISORY / "manifest.json")["sha256"] == ADVISORY_PIN,
            "selected advisory diagnostic manifest changed")
    advisory_manifest = read(ADVISORY / "manifest.json")
    checked(ADVISORY / "comparison.json", advisory_manifest["artifacts"]["comparison.json"])
    advisory = read(ADVISORY / "comparison.json")
    require(advisory["human_gold"] is False and advisory["independent_human_validation"] is False,
            "assistant diagnostics must not masquerade as human gold")
    selected_ids = {case["bill_id"] for case in advisory["cases"]}
    table = pq.read_table(directory / "bill_assignments-retained_text.parquet")
    require(table.num_rows == plan["n_contexts"]
            and len(set(table["bill_id"].to_pylist())) == table.num_rows,
            "complete unique original contexts required")
    topics = load_topics(plan["topics_path"])
    codes = [topic.code for topic in topics] + [None]
    gates = {name: plan["decision"][name] for name in ("min_confidence", "min_margin")}
    for folder in ("decisions", "chart-data", "graphs", "research-data", "producers", "evidence"):
        (output / folder).mkdir(parents=True)
    for name, path in producers.items():
        shutil.copyfile(path, output / "producers" / name)
        checked(output / "producers" / name, producer_pins[name])
    shutil.copyfile(
        ADVISORY / "comparison.json", output / "evidence/original_assistant_comparison.json")
    policy_plan = {
        "policy": POLICY, "status": "frozen_before_provisional_majority_reaggregation",
        "baseline_model_run": plan["model_run"], "original_gallery_sha256": gallery_sha256,
        "decision": plan["decision"], "output_codes": codes,
        "window_rule": "strict_more_than_half_of_all_window_argmax_votes",
        "source_rule": "strict_more_than_half_of_distinct_exact_input_strings",
        "quality_gate_scope": "mean_complete_output_vector_of_supporting_windows",
        "overlapping_windows": "retained_frozen_windows_not_independent_semantic_judges",
        "uncertain_source_votes": "remain_in_denominator_not_counted_as_policy_or_rejection",
        "minority_sources": "retained_and_flagged_not_an_automatic_veto",
        "source_independence": "exact_duplicates_removed_not_independent_edition_certification",
        "supporting_scores_are_not_full_document_scores_or_calibrated_accuracy": True,
        "source_inputs": inputs, "producers": producer_pins, **dict.fromkeys(FLAGS, False),
    }
    (output / "policy_plan.json").write_text(json.dumps(policy_plan, indent=2) + "\n")
    policy_run = binding(output / "policy_plan.json")["sha256"]
    counts, old_reasons, transitions, gains = Counter(), Counter(), Counter(), Counter()
    before_topics, after_topics = Counter(), Counter()
    state_rows, selected_results = [], {}
    n_views = n_windows = exact_duplicates = 0
    n_new = n_unchanged = n_source_dissent = n_window_dissent = 0
    seen = set()
    with ((output / "decisions/context_assignments.jsonl").open("w") as context_file,
          (output / "decisions/source_decisions.jsonl").open("w") as source_file):
        for state in states:
            originals = table.filter(pc.equal(table["state"], state)).to_pylist()
            by_id = {row["bill_id"]: row for row in originals}
            source_results, original_views = defaultdict(list), defaultdict(list)
            for _, original in records(directory / f"predictions/retained_text-{state}.jsonl"):
                require(original["state"] == state and original["bill_id"] in by_id
                        and original["input_id"] not in seen,
                        "invalid original prediction identity")
                require("majority_candidate" not in original, "prediction namespace collision")
                seen.add(original["input_id"])
                scores = diagnostics.prediction_scores(original, codes, plan["decision"])
                if scores is None:
                    result = None
                    derived = {
                        "status": "excluded", "reason": original["abstention_reason"],
                        "mean_output_scores": None, "supporting_output_scores": None}
                else:
                    result = window_majority(
                        json.loads(original["logits"]), codes, **plan["decision"])
                    derived = asdict(result)
                    source_results[original["bill_id"]].append((original["input_sha256"], result))
                    n_windows += result.electorate
                write_row(source_file, {**original, "majority_candidate": {
                    **derived, "policy_run": policy_run, "output_codes": codes,
                    "independent_human_validation": False}})
                original_views[original["bill_id"]].append({
                    **{name: original[name] for name in
                       ("bill_id", "input_id", "input_sha256", "topic", "abstention_reason")},
                    "score_diagnostics": {"output_scores": scores},
                })
                n_views += 1
            state_counts = Counter()
            old_assigned = new_assigned = 0
            for original in originals:
                require("majority_candidate" not in original
                        and all(original.get(flag) is False for flag in FLAGS),
                        "original assignment namespace or approvals changed")
                views = original_views[original["bill_id"]]
                baseline = diagnostics.context_diagnostics(original, views, codes)
                sources = source_results[original["bill_id"]]
                result = source_majority(sources, codes, **gates)
                derived = asdict(result)
                if result.status == "unscored":
                    derived["status"] = "excluded" if views else "unavailable"
                    derived["reason"] = (
                        "all_source_records_excluded" if views else "no_retained_text")
                status = derived["status"]
                require(status in STATUSES, "unknown candidate status")
                exact_duplicates += len(sources) - result.electorate
                window_dissent = any(source.disagreement_present for _, source in sources)
                source_dissent = result.disagreement_present or result.abstaining_votes > 0
                derived.update({
                    "policy_run": policy_run, "output_codes": codes,
                    "original_source_views": len(views),
                    "distinct_scored_inputs": result.electorate,
                    "source_disagreement_or_uncertainty": source_dissent,
                    "window_disagreement_present": window_dissent,
                    "conditional_support_score_is_not_full_document_confidence": True,
                    "independent_human_validation": False, **dict.fromkeys(FLAGS, False),
                })
                write_row(context_file, {**original, "majority_candidate": derived})
                if original["bill_id"] in selected_ids:
                    selected_results[original["bill_id"]] = (original, derived)
                counts[status] += 1
                state_counts[status] += 1
                category = baseline["decision_category"]
                old_reasons[category] += 1
                transitions[category, status] += 1
                if original["inference_status"] == "classified":
                    require(status == "classified" and derived["topic"] == original["topic"],
                            "majority policy lost or changed an accepted baseline topic")
                    n_unchanged += 1
                    old_assigned += 1
                    before_topics[original["topic"]] += 1
                if status == "classified":
                    new_assigned += 1
                    after_topics[derived["topic"]] += 1
                    n_source_dissent += source_dissent
                    n_window_dissent += window_dissent
                    if original["inference_status"] != "classified":
                        require(original["inference_status"] == "abstained",
                                "missing input gained a topic")
                        n_new += 1
                        gains[category] += 1
            state_rows.append({
                "state": state, "original_contexts": len(originals),
                "baseline_assigned": old_assigned, "candidate_assigned": new_assigned,
                "new_assignments": new_assigned - old_assigned,
                **{status: state_counts[status] for status in STATUSES if status != "classified"},
            })
    require(n_views == plan["n_views_by_tier"]["retained_text"], "missing original source views")
    require(sum(counts.values()) == table.num_rows and n_unchanged == old_reasons["classified"],
            "original population or accepted-topic preservation failed")
    require(counts["unavailable"] == old_reasons["unavailable"], "missing-text population changed")
    old_status = {
        "classified": old_reasons["classified"],
        "model_rejected": old_reasons["supervised_rejection"],
        "excluded": old_reasons["source_test_record"] + old_reasons["source_draft_request"],
        "unavailable": old_reasons["unavailable"],
    }
    old_status["uncertain"] = table.num_rows - sum(old_status.values())
    status_rows = [{"status": status, "label": STATUS_LABELS[status],
                    "baseline_contexts": old_status[status], "candidate_contexts": counts[status]}
                   for status in STATUSES]
    topic_rows = [{"topic": topic.code, "label": topic.name,
                   "baseline_contexts": before_topics[topic.code],
                   "candidate_contexts": after_topics[topic.code]} for topic in topics]
    gain_rows = [{"baseline_reason": reason, "label": diagnostics.REASONS[reason],
                  "new_assignments": gains[reason]}
                 for reason in diagnostics.REASONS if reason not in ("classified", "unavailable")]
    transition_rows = [{"baseline_reason": old, "candidate_status": new, "contexts": count}
                       for (old, new), count in sorted(transitions.items())]
    for name, rows in (
        ("status_comparison", status_rows), ("topic_comparison", topic_rows),
        ("new_assignment_origins", gain_rows), ("transitions", transition_rows),
        ("state_comparison", state_rows),
    ):
        diagnostics.write_csv(output / "chart-data" / f"{name}.csv", rows)
    advisory_rows, advisory_counts = [], Counter()
    for case in advisory["cases"]:
        original, candidate = selected_results[case["bill_id"]]
        require(case["model_topic"] == original["topic"]
                and case["model_inference_status"] == original["inference_status"],
                "advisory comparison is not the same frozen baseline")
        comparison = (
            "same_assigned_topic" if candidate["status"] == "classified"
            and candidate["topic"] == case["advisory_topic"]
            else "different_assigned_topic" if candidate["status"] == "classified"
            and case["advisory_topic"] is not None
            else "candidate_assigned_advisory_unresolved" if candidate["status"] == "classified"
            else "candidate_unassigned_advisory_assigned" if case["advisory_topic"] is not None
            else "both_unresolved"
        )
        advisory_counts[comparison] += 1
        advisory_rows.append({
            "bill_id": case["bill_id"], "state": case["state"], "identifier": case["identifier"],
            "baseline_status": original["inference_status"], "baseline_topic": original["topic"],
            "candidate_status": candidate["status"], "candidate_topic": candidate["topic"],
            "advisory_topic": case["advisory_topic"], "comparison": comparison,
            "independent_human_gold": False,
        })
    diagnostics.write_csv(output / "chart-data/selected_assistant_comparison.csv", advisory_rows)
    summary = {
        "status": "complete_provisional_majority_candidate_not_human_validated",
        "policy": POLICY, "policy_run": policy_run, "notice": NOTICE,
        "original_contexts": table.num_rows, "original_source_views": n_views,
        "complete_original_windows": n_windows, "output_codes": codes,
        "baseline_status_counts": old_status, "candidate_status_counts": dict(counts),
        "baseline_abstentions": (
            table.num_rows - old_status["classified"] - old_status["unavailable"]),
        "candidate_unassigned_available_contexts": counts["model_rejected"] + counts["uncertain"]
        + counts["excluded"],
        "new_majority_assignments": n_new, "baseline_assigned_topics_preserved": n_unchanged,
        "baseline_assigned_topics_changed": 0,
        "exact_duplicate_source_votes_removed": exact_duplicates,
        "assigned_with_source_disagreement_or_uncertainty": n_source_dissent,
        "assigned_with_window_disagreement": n_window_dissent,
        "new_assignment_origins": dict(gains),
        "selected_assistant_diagnostic_contexts": len(advisory_rows),
        "selected_assistant_comparison_not_accuracy": dict(advisory_counts),
        "encoder_calls": 0, "independent_human_validation": False,
        "unchanged_numerical_gates": gates, "changed_gate_scope": "supporting_window_coalition",
        "source_votes_are_not_independent_edition_certification": True,
        "frozen_training_reviewer_types": training["reviewer_types"],
        "frozen_training_split_counts": training["split_counts"],
        "frozen_training_unit_policy": training["training_unit_policy"],
        "new_policy_is_not_the_original_training_objective": True,
        **dict.fromkeys(FLAGS, False),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    figures = charts(output / "graphs", old_status, counts, topic_rows, gain_rows)
    additions = {
        "majority-candidate/" + path.relative_to(output).as_posix(): path
        for folder in ("decisions", "chart-data", "producers", "evidence")
        for path in (output / folder).iterdir() if path.is_file()
    }
    additions.update({
        "majority-candidate/policy_plan.json": output / "policy_plan.json",
        "majority-candidate/summary.json": output / "summary.json",
    })
    members = diagnostics.complete_zip(
        gallery / "research-data/complete_inference_inputs_and_predictions.zip",
        output / "research-data/complete_inference_and_majority_candidate.zip", inputs, additions)
    cards = "".join(
        f'<section><h2>{html.escape(name.replace("_", " "))}</h2>'
        f'<a href="graphs/{name}.png"><img src="graphs/{name}.png" alt="{name}"></a>'
        f'<p><a href="graphs/{name}.svg">SVG</a></p></section>' for name in figures)
    (output / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Strict-majority bill-topic candidate</title><style>'
        f'body{{max-width:1100px;margin:36px auto;padding:0 22px;background:{theme.BG};'
        f'color:{theme.TEXT};font:16px/1.6 Georgia,serif}}a{{color:{theme.BLUE};'
        'overflow-wrap:anywhere}img{max-width:100%;height:auto}'
        'section{margin:36px 0;border-top:1px solid #D6D3CC}h1,h2{font-weight:normal}'
        '</style><p>LOCAL / UNPUBLISHED / UNVALIDATED CANDIDATE</p>'
        '<h1>Majority, not unanimity</h1>'
        f'<p>{html.escape(NOTICE)}</p>'
        f'<p>{counts["classified"]:,} provisional topic assignments versus '
        f'{old_status["classified"]:,} under unanimity: {n_new:,} additional assignments. '
        f'All {n_unchanged:,} previously accepted topics are preserved. '
        f'{counts["model_rejected"]:,} learned rejections; {counts["uncertain"]:,} unresolved '
        f'majorities; {counts["excluded"]:,} exclusions; '
        f'{counts["unavailable"]:,} missing texts.</p>'
        '<p>Ties and pluralities do not count as majorities. Uncertain sources remain in the '
        'denominator. Exact duplicate input strings count once. Different extraction strings '
        'are not certified independent editions; minority evidence remains visible. '
        'Supporting-window scores are conditional diagnostics, not whole-bill confidence.</p>'
        '<p><a download href="research-data/complete_inference_and_majority_candidate.zip">'
        'Complete original policy texts, predictions, majority decisions and producers (ZIP)</a>'
        ' &middot; <a href="summary.json">Summary</a>'
        ' &middot; <a href="policy_plan.json">Frozen policy plan</a></p>'
        f'{cards}'
    )
    for name, expected in inputs.items():
        checked(directory / name, expected)
    for name, path in producers.items():
        checked(path, producer_pins[name])
    require(binding(gallery / "manifest.json")["sha256"] == gallery_sha256,
            "baseline gallery changed during candidate execution")
    result = {
        **summary, "source_gallery_manifest": binding(gallery / "manifest.json"),
        "source_inference_inputs": inputs, "complete_research_zip_members": members,
        "artifacts": {str(path.relative_to(output)): binding(path)
                      for path in sorted(output.rglob("*")) if path.is_file()},
    }
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--gallery", type=Path, required=True)
    parser.add_argument("--gallery-sha256", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    result = recreate(args.directory, args.gallery, args.out_dir, args.gallery_sha256)
    print(json.dumps({key: result[key] for key in (
        "original_contexts", "candidate_status_counts", "new_majority_assignments",
        "baseline_assigned_topics_preserved", "new_assignment_origins",
        "selected_assistant_comparison_not_accuracy")}, indent=2))


if __name__ == "__main__":
    main()

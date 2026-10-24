#!/usr/bin/env python3
"""Expose every frozen output score without changing assignments or hiding rejection."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pyarrow.compute as pc  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

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
from state_politics.analysis.modernbert import decide  # noqa: E402
from state_politics.analysis.taxonomy import load_topics  # noqa: E402
from state_politics.bills.openstates_dump import STATE_CODES  # noqa: E402
from state_politics.plotting import theme  # noqa: E402

NOTICE = (
    "Frozen, uncalibrated model-score diagnostics, not accuracy, policy prevalence or new labels. "
    "Rejection stays in the output space. Missing and excluded inputs have no scores, not zeros. "
    "All canonical assignments, thresholds, weights and source-consensus rules remain unchanged. "
    "Retained versions and filing-time alignment remain uncertified."
)
REASONS = {
    "classified": "Assigned one topic",
    "supervised_rejection": "Model rejection output only",
    "mixed_chunk_topics": "Within-document window disagreement",
    "low_confidence": "Low score only",
    "ambiguous_margin": "Small score margin only",
    "insufficient_evidence": "Insufficient model evidence",
    "mixed_view_abstentions": "Multiple source-view abstention reasons",
    "source_alternative_disagreement": "Source-alternative disagreement",
    "source_test_record": "Source test records excluded",
    "source_draft_request": "Source draft requests excluded",
    "unavailable": "No supplied retained text",
}
EXCLUSIONS = {"source_test_record", "source_draft_request"}


def prediction_scores(row, codes, decision):
    """Check saved scores against the unchanged window decision, including rejection."""
    actual_codes = json.loads(row["output_codes"])
    require(
        actual_codes == codes
        and all(type(code) is int for code in actual_codes if code is not None),
        "saved output-code order/type changed",
    )
    require(all(row.get(flag) is False for flag in FLAGS), "prediction approval flag changed")
    require(row.get("score_type") == "uncalibrated_softmax"
            and row.get("calibration_sha256") is None, "unsupported score calibration")
    logits, scores = json.loads(row["logits"]), json.loads(row["scores"])
    if row["abstention_reason"] in EXCLUSIONS:
        require(
            logits == scores == [] and row["n_chunks"] == 0 and row["topic"] is None
            and row["n_input_tokens"] is None and row["candidate_topic"] is None
            and row["runner_up"] is None and row["score"] == row["margin"] == 0,
            "excluded source has fabricated model scores",
        )
        return None
    require(bool(logits), "unexplained missing saved logits")
    expected = decide(logits, codes, **decision)
    require(
        scores == list(expected.scores) and all(
            row[name] == getattr(expected, name) for name in (
                "topic", "candidate_topic", "runner_up", "score", "margin",
                "abstention_reason", "n_chunks",
            )
        ),
        "saved scores or decision disagree with complete original logits",
    )
    require(
        len(scores) == len(codes) and all(math.isfinite(value) for value in scores)
        and all(0 <= value <= 1 for value in scores)
        and math.isclose(math.fsum(scores), 1, abs_tol=1e-12),
        "invalid complete output-score vector",
    )
    return scores


def context_diagnostics(original, views, codes):
    """Keep the original decision and summarize every distinct scored source string."""
    require(len(views) == original["n_source_views"], "context/source-view count changed")
    require(all(view["bill_id"] == original["bill_id"] for view in views), "wrong source context")
    require(len({view["input_id"] for view in views}) == len(views), "duplicate input record")
    status = original["inference_status"]
    require(status in {"classified", "abstained", "unavailable"}, "unknown original decision")
    reasons = Counter(view["abstention_reason"] for view in views
                      if view["abstention_reason"] is not None)
    require(dict(reasons) == json.loads(original["view_abstention_reasons"]),
            "original view-abstention accounting changed")
    if status == "unavailable":
        require(not views and original["topic"] is None, "missing input has model evidence")
        category = "unavailable"
    elif status == "classified":
        require(bool(views) and all(view["topic"] == original["topic"] for view in views),
                "canonical source consensus changed")
        category = "classified"
    elif original["abstention_reason"] == "source_alternative_disagreement":
        category = "source_alternative_disagreement"
    else:
        require(original["abstention_reason"] == "all_source_views_abstained"
                and bool(reasons), "unexplained context abstention")
        category = next(iter(reasons)) if len(reasons) == 1 else "mixed_view_abstentions"
    require(category in REASONS, "unsupported original abstention reason")
    unique, scored_views = {}, 0
    for view in views:
        scores = view["score_diagnostics"]["output_scores"]
        if scores is None:
            continue
        scored_views += 1
        sha = view["input_sha256"]
        require(type(sha) is str and len(sha) == 64, "missing complete input identity")
        if sha in unique:
            require(unique[sha] == scores, "same input has different frozen scores")
        else:
            unique[sha] = scores
    result = {
        "diagnostic_only_not_an_assignment": True,
        "decision_category": category,
        "n_source_views": len(views), "n_scored_views": scored_views,
        "n_excluded_views": len(views) - scored_views,
        "n_distinct_scored_inputs": len(unique),
        "output_codes": codes, "mean_output_scores": None,
        "minimum_source_output_scores": None, "maximum_source_output_scores": None,
        "mean_score_entropy_bits": None, "mean_rejection_score": None,
        "source_argmax_disagrees": None,
        "source_weighting": "equal_exact_input_sha256_within_each_original_context",
    }
    if unique:
        values = np.asarray(list(unique.values()), dtype=float)
        require(values.ndim == 2 and values.shape[1] == len(codes)
                and np.isfinite(values).all(), "invalid source-score matrix")
        means = values.mean(axis=0)
        result.update({
            "mean_output_scores": means.tolist(),
            "minimum_source_output_scores": values.min(axis=0).tolist(),
            "maximum_source_output_scores": values.max(axis=0).tolist(),
            "mean_score_entropy_bits": -sum(float(p) * math.log2(float(p))
                                           for p in means if p > 0),
            "mean_rejection_score": float(means[-1]),
            "source_argmax_disagrees": len(set(values.argmax(axis=1).tolist())) > 1,
        })
    return result


def complete_zip(source, target, original_members, additions):
    """Copy the complete inference ZIP and append diagnostics, never a metadata-only replacement."""
    require(not target.exists() and source.resolve() != target.resolve(), "fresh ZIP required")
    with ZipFile(source) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and set(names) == set(original_members),
                "complete original inference ZIP membership changed")
    before = binding(source)
    shutil.copyfile(source, target)
    require((source.stat().st_dev, source.stat().st_ino)
            != (target.stat().st_dev, target.stat().st_ino), "source ZIP must not be modified")
    with ZipFile(target, "a", compression=ZIP_DEFLATED, compresslevel=1) as archive:
        for name, path in additions.items():
            require(name not in original_members, "diagnostic ZIP member collision")
            archive.write(path, name)
    expected = {**original_members, **{name: binding(path) for name, path in additions.items()}}
    with ZipFile(target) as archive:
        require(len(archive.namelist()) == len(set(archive.namelist())) == len(expected),
                "complete diagnostic ZIP membership mismatch")
        for name, value in expected.items():
            with archive.open(name) as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            require({"sha256": sha, "bytes": archive.getinfo(name).file_size} == value,
                    f"complete diagnostic ZIP member changed: {name}")
    require(binding(source) == before, "original complete source ZIP changed")
    return expected


def write_csv(path, rows):
    require(bool(rows), "empty chart table")
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def render(output, reason_rows, score_rows):
    theme.apply()
    fig, ax = plt.subplots(figsize=(11, 7))
    present = [row for row in reason_rows if row["contexts"]]
    ax.barh([row["label"] for row in present], [row["contexts"] for row in present],
            color=[theme.BLUE if row["category"] == "classified" else theme.MUTED
                   for row in present])
    ax.invert_yaxis()
    ax.set_xlabel("Original candidate contexts; mutually exclusive recorded decisions")
    fig.subplots_adjust(left=0.39, right=0.97, top=0.87, bottom=0.20)
    figures = [("decision_reasons", fig, "What the hard-label headline leaves out")]
    fig, ax = plt.subplots(figsize=(11, 10))
    rows = sorted(score_rows, key=lambda row: row["mean_context_score"], reverse=True)
    means = np.array([row["mean_context_score"] for row in rows]) * 100
    lower = np.array([row["mean_source_minimum"] for row in rows]) * 100
    upper = np.array([row["mean_source_maximum"] for row in rows]) * 100
    require(np.all(lower <= means + 1e-10) and np.all(means <= upper + 1e-10),
            "source score envelope excludes its mean")
    ax.barh([row["label"] for row in rows], means,
            xerr=np.maximum(0, np.array([means - lower, upper - means])),
            color=[theme.MUTED if row["output_code"] is None else theme.BLUE for row in rows],
            error_kw={"ecolor": theme.MUTED, "elinewidth": 0.7, "capsize": 2})
    ax.invert_yaxis()
    ax.set_xlabel("Mean uncalibrated output score (%); rejection is not removed")
    ax.tick_params(axis="y", labelsize=10)
    fig.subplots_adjust(left=0.35, right=0.97, top=0.89, bottom=0.18)
    figures.append(("all_output_scores", fig, "All saved outputs, not only accepted topics"))
    for name, figure, title in figures:
        figure.suptitle(title, x=0.03, ha="left", fontsize=17, fontweight="bold")
        theme.source_note(figure, NOTICE + " Score whiskers show source variation, not confidence.",
                          width=115)
        for suffix in ("png", "svg"):
            figure.savefig(output / f"{name}.{suffix}", dpi=160, facecolor=theme.BG)
        plt.close(figure)
    return [name for name, _, _ in figures]


def recreate(directory, gallery, output, gallery_sha256):
    directory, gallery, output = directory.absolute(), gallery.absolute(), output.absolute()
    require(not output.exists() and output.resolve() == output
            and output.is_relative_to(ROOT / "outputs"), "new project output required")
    producers = {
        "recreate_score_diagnostics.py": Path(__file__).absolute(),
        "theme.py": Path(theme.__file__).absolute(),
    }
    producer_bindings = {name: binding(path) for name, path in producers.items()}
    anchor = gallery / "manifest.json"
    require(binding(anchor)["sha256"] == gallery_sha256, "externally pinned gallery changed")
    manifest = read(anchor)
    require(manifest["tiers"] == ["retained_text"], "complete retained-text gallery required")
    for name, value in manifest["artifacts"].items():
        checked(gallery / name, value)
    plan = checked_job(directory)
    require(manifest["model_run"] == plan["model_run"], "mixed model runs")
    progress = read(directory / "progress-retained_text.json")
    states = sorted(state.upper() for state in STATE_CODES)
    require(progress["status"] == "complete_provisional_inference_not_scientific_validation"
            and set(progress["states"]) == set(states), "complete fifty-state inference required")
    inputs = manifest["inference_inputs"]
    require(len(inputs) == 108, "all 108 full inference members required")
    for name, value in inputs.items():
        checked(directory / name, value)
    before = {name: binding(directory / name) for name in inputs}
    table = pq.read_table(directory / "bill_assignments-retained_text.parquet")
    require(table.num_rows == plan["n_contexts"], "original population changed")
    require(len(set(table["bill_id"].to_pylist())) == table.num_rows, "duplicate original contexts")
    topics = load_topics(plan["topics_path"])
    codes = [topic.code for topic in topics] + [None]
    labels = {topic.code: topic.name for topic in topics} | {None: "Model rejection output"}
    for folder in ("diagnostics", "chart-data", "graphs", "research-data", "producers"):
        (output / folder).mkdir(parents=True)
    for name, path in producers.items():
        shutil.copyfile(path, output / "producers" / name)
        require(binding(output / "producers" / name) == producer_bindings[name],
                "copied diagnostic producer changed")
    reasons, decisions, state_scores = Counter(), Counter(), []
    total_means = np.zeros(len(codes))
    total_lower, total_upper = total_means.copy(), total_means.copy()
    scored_contexts = views_total = scored_views = 0
    seen = set()
    with ((output / "diagnostics/context_scores.jsonl").open("w") as context_stream,
          (output / "diagnostics/view_scores.jsonl").open("w") as view_stream):
        for state in states:
            originals = table.filter(pc.equal(table["state"], state)).to_pylist()
            by_id = {row["bill_id"]: row for row in originals}
            by_bill = defaultdict(list)
            for _, row in records(directory / f"predictions/retained_text-{state}.jsonl"):
                require(row["bill_id"] in by_id and row["state"] == state,
                        "prediction outside original state/context")
                require(row["input_id"] not in seen, "duplicate complete prediction")
                require("score_diagnostics" not in row, "original prediction namespace collision")
                seen.add(row["input_id"])
                scores = prediction_scores(row, codes, plan["decision"])
                enriched = {**row, "score_diagnostics": {
                    "diagnostic_only_not_an_assignment": True,
                    "output_codes": codes, "output_scores": scores,
                    "rejection_output_retained": True,
                    "has_score_vector": scores is not None,
                }}
                write_row(view_stream, enriched)
                by_bill[row["bill_id"]].append(enriched)
                views_total += 1
                scored_views += scores is not None
            means, lower, upper = (np.zeros(len(codes)) for _ in range(3))
            count = 0
            for original in originals:
                require("score_diagnostics" not in original, "original context namespace collision")
                require(all(original.get(flag) is False for flag in FLAGS),
                        "original assignment approval changed")
                diagnostic = context_diagnostics(original, by_bill[original["bill_id"]], codes)
                write_row(context_stream, {**original, "score_diagnostics": diagnostic})
                decisions[original["inference_status"]] += 1
                reasons[diagnostic["decision_category"]] += 1
                if diagnostic["mean_output_scores"] is not None:
                    count += 1
                    means += diagnostic["mean_output_scores"]
                    lower += diagnostic["minimum_source_output_scores"]
                    upper += diagnostic["maximum_source_output_scores"]
            scored_contexts += count
            total_means += means
            total_lower += lower
            total_upper += upper
            state_scores.extend({
                "state": state, "output_code": code, "label": labels[code],
                "original_contexts": len(originals), "scored_contexts": count,
                "mean_context_score": float(means[i] / count) if count else None,
                "mean_source_minimum": float(lower[i] / count) if count else None,
                "mean_source_maximum": float(upper[i] / count) if count else None,
            } for i, code in enumerate(codes))
    require(views_total == plan["n_views_by_tier"]["retained_text"], "missing source predictions")
    require(dict(decisions) == {
        key: value for key, value in manifest["assignment_counts_by_tier"]["retained_text"].items()
        if key != "candidate_contexts"}, "canonical assignment counts changed")
    require(scored_contexts > 0, "no modeled score vectors")
    score_rows = [{
        "output_code": code, "label": labels[code], "scored_contexts": scored_contexts,
        "mean_context_score": float(total_means[i] / scored_contexts),
        "mean_source_minimum": float(total_lower[i] / scored_contexts),
        "mean_source_maximum": float(total_upper[i] / scored_contexts),
    } for i, code in enumerate(codes)]
    reason_rows = [{"category": key, "label": label, "contexts": reasons[key]}
                   for key, label in REASONS.items()]
    write_csv(output / "chart-data/decision_reasons.csv", reason_rows)
    write_csv(output / "chart-data/output_scores.csv", score_rows)
    write_csv(output / "chart-data/state_output_scores.csv", state_scores)
    summary = {
        "schema": "state-politics.full-score-diagnostics.v1",
        "notice": NOTICE, "original_contexts": table.num_rows,
        "canonical_assignment_counts": dict(decisions),
        "decision_reason_counts": dict(reasons), "source_views": views_total,
        "scored_source_views": scored_views, "scored_contexts": scored_contexts,
        "output_codes": codes, "output_labels": [labels[code] for code in codes],
        "source_weighting": "equal exact input strings within context; equal scored contexts",
        "source_envelopes_are_not_confidence_intervals": True,
        "no_rejection_renormalization_or_new_labels": True,
        "encoder_calls": 0, "independent_human_validation": False,
        **dict.fromkeys(FLAGS, False),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    figures = render(output / "graphs", reason_rows, score_rows)
    for name, path in producers.items():
        require(binding(path) == producer_bindings[name], "diagnostic producer changed")
    additions = {
        "score-diagnostics/" + path.relative_to(output).as_posix(): path
        for folder in ("diagnostics", "chart-data", "producers")
        for path in (output / folder).iterdir() if path.is_file()}
    additions["score-diagnostics/summary.json"] = output / "summary.json"
    members = complete_zip(
        gallery / "research-data/complete_inference_inputs_and_predictions.zip",
        output / "research-data/complete_inference_and_score_diagnostics.zip", inputs, additions,
    )
    cards = "".join(
        f'<section><h2>{html.escape(name.replace("_", " "))}</h2>'
        f'<a href="graphs/{name}.png"><img src="graphs/{name}.png" alt="{name}"></a>'
        f'<p><a href="graphs/{name}.svg">SVG</a></p></section>' for name in figures)
    (output / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Complete model-score diagnostics</title><style>'
        f'body{{max-width:1100px;margin:36px auto;padding:0 22px;background:{theme.BG};'
        f'color:{theme.TEXT};font:16px/1.6 Georgia,serif}}a{{color:{theme.BLUE};'
        'overflow-wrap:anywhere}img{max-width:100%;height:auto}'
        'section{margin:36px 0;border-top:1px solid #D6D3CC}h1,h2{font-weight:normal}'
        '</style><p>LOCAL / UNPUBLISHED / DIAGNOSTIC ONLY</p>'
        '<h1>More than one hard label</h1>'
        f'<p>{html.escape(NOTICE)}</p>'
        f'<p>{table.num_rows:,} original contexts; {scored_contexts:,} with complete '
        f'{len(codes)}-output vectors; {views_total:,} preserved source predictions. '
        'Text availability and actual score availability are reported separately.</p>'
        '<p>Identical complete input strings count once within each context. Contexts have equal '
        'weight. Score envelopes measure variation across supplied source alternatives, '
        'not statistical confidence or true policy proportions.</p>'
        '<p><a download href="research-data/complete_inference_and_score_diagnostics.zip">'
        'Complete original texts, source records, predictions, frozen plan and all score '
        'diagnostics (ZIP)</a> · <a href="summary.json">Diagnostic summary</a></p>'
        f'{cards}'
    )
    for name, value in before.items():
        require(binding(directory / name) == value, "original inference artifact changed")
    require(all(binding(path) == producer_bindings[name] for name, path in producers.items()),
            "diagnostic producer changed during execution")
    require(binding(anchor)["sha256"] == gallery_sha256, "original gallery manifest changed")
    result = {
        **summary, "status": "complete_full_score_diagnostics_not_new_assignments_or_validation",
        "source_gallery_manifest": {"path": str(anchor), **binding(anchor)},
        "source_inference_inputs": before, "complete_research_zip_members": members,
        "artifacts": {path.relative_to(output).as_posix(): binding(path)
                      for path in sorted(output.rglob("*")) if path.is_file()},
    }
    (output / "manifest.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--gallery", type=Path, required=True)
    parser.add_argument("--gallery-sha256", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    result = recreate(args.directory, args.gallery, args.out_dir, args.gallery_sha256)
    fields = ("original_contexts", "source_views", "scored_contexts", "decision_reason_counts")
    print(json.dumps({key: result[key] for key in fields}, indent=2))


if __name__ == "__main__":
    main()

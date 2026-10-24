#!/usr/bin/env python3
"""Freeze and run longer-window inference on a complete selected review cohort."""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import math
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import recreate_score_diagnostics as diagnostics  # noqa: E402

from state_politics.analysis import context_profiles, majority_topics, modernbert  # noqa: E402
from state_politics.analysis.context_profiles import (  # noqa: E402
    encode_window_batches,
    encoder_window_key,
    profile_windows,
)
from state_politics.analysis.cycle_topics import (  # noqa: E402
    FLAGS,
    binding,
    checked,
    checked_job,
    input_text,
    read,
    records,
    require,
    write_row,
)
from state_politics.analysis.majority_topics import source_majority, window_majority  # noqa: E402
from state_politics.analysis.modernbert import ModernBertClassifier  # noqa: E402
from state_politics.analysis.taxonomy import load_topics  # noqa: E402
from state_politics.compute import select_device  # noqa: E402
from state_politics.plotting import theme  # noqa: E402

PROFILES = {
    "context4096": {"max_tokens": 4096, "overlap": 512},
    "context8192": {"max_tokens": 8192, "overlap": 1024},
}
NOTICE = (
    "Selected assistant-reviewed cohort, not independent human accuracy or population coverage. "
    "Same frozen weights; longer inference windows are not retraining. Every input token and "
    "source alternative is preserved. Old majority/population results are not replaced."
)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_rows(path, values):
    with path.open("w") as stream:
        for value in values:
            write_row(stream, value)


def sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def comparison(topic, status, proposal):
    return (
        "same_assigned_topic"
        if status == "classified" and topic == proposal
        else "different_assigned_topic"
        if status == "classified" and proposal is not None
        else "assigned_advisory_unresolved"
        if status == "classified"
        else "unassigned_advisory_assigned"
        if proposal is not None
        else "both_unresolved"
    )


def render(output, rows, work):
    theme.apply()
    fig, ax = plt.subplots(figsize=(11, 6))
    categories = (
        ("same_assigned_topic", "Same assistant proposal", theme.BLUE),
        ("different_assigned_topic", "Different assistant proposal", theme.MUTED),
        ("assigned_advisory_unresolved", "Assigned; advisory unresolved", "#B9B0A1"),
        ("unassigned", "Not assigned", "#DDD8CD"),
    )
    for position, row in enumerate(rows):
        left = 0
        for key, label, color in categories:
            value = row.get(key, 0)
            ax.barh(
                position,
                value,
                left=left,
                color=color,
                height=0.6,
                label=label if position == 0 else None,
            )
            left += value
    ax.set_yticks(range(len(rows)), [row["label"] for row in rows])
    ax.invert_yaxis()
    ax.set_xlabel("Same selected original contexts; assistant agreement is not accuracy")
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="lower left", bbox_to_anchor=(0, 1.02))
    fig.subplots_adjust(left=0.25, right=0.97, top=0.72, bottom=0.25)
    figures = [("context_comparison", fig, "Does longer context help this cohort?")]
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.barh(
        [row["profile"] for row in work],
        [row["new_encoder_windows"] for row in work],
        color=theme.BLUE,
    )
    ax.invert_yaxis()
    ax.set_xlabel("Actual new encoder windows; identical cached windows are not re-encoded")
    fig.subplots_adjust(left=0.19, right=0.97, top=0.80, bottom=0.29)
    figures.append(("encoder_work", fig, "Measured additional encoder work"))
    for name, figure, title in figures:
        figure.suptitle(title, x=0.03, ha="left", fontsize=16, fontweight="bold")
        theme.source_note(figure, NOTICE, width=115)
        for suffix in ("png", "svg"):
            figure.savefig(output / f"{name}.{suffix}", dpi=160, facecolor=theme.BG)
        plt.close(figure)
    return [name for name, _, _ in figures]


def run(args):
    import torch
    import transformers

    job, majority, casebook, output = (
        path.absolute() for path in (args.job, args.majority_gallery, args.casebook, args.out_dir)
    )
    require(args.allow_provisional, "explicit --allow-provisional research permission required")
    require(
        output.resolve() == output and output.is_relative_to(ROOT / "outputs"),
        "unlinked project output required",
    )
    require(
        (args.resume and output.is_dir()) or (not args.resume and not output.exists()),
        "fresh output required unless explicitly resuming",
    )
    checked(
        majority / "manifest.json",
        {"sha256": args.majority_sha256, "bytes": (majority / "manifest.json").stat().st_size},
    )
    require(
        binding(casebook / "manifest.json")["sha256"] == args.casebook_sha256,
        "casebook external pin changed",
    )
    original_plan = checked_job(job)
    majority_manifest = read(majority / "manifest.json")
    for name, expected in majority_manifest["artifacts"].items():
        checked(majority / name, expected)
    for name, expected in majority_manifest["source_inference_inputs"].items():
        checked(job / name, expected)
    checked(
        casebook / "comparison.json",
        read(casebook / "manifest.json")["artifacts"]["comparison.json"],
    )
    advisory = read(casebook / "comparison.json")
    require(
        advisory["human_gold"] is False and advisory["independent_human_validation"] is False,
        "selected assistant references must remain nonhuman diagnostics",
    )
    cases = {case["bill_id"]: case for case in advisory["cases"]}
    inputs, old_predictions, baseline_contexts = {}, {}, {}
    for name in sorted(original_plan["inputs"]):
        for _, row in records(job / name):
            if row["bill_id"] in cases:
                require(
                    row["pre_inference_exclusion"] is None, "review cohort contains excluded input"
                )
                require(row["input_id"] not in inputs, "duplicate original input identity")
                input_text(row)
                inputs[row["input_id"]] = row
    for state in sorted(read(job / "progress-retained_text.json")["states"]):
        for _, row in records(job / f"predictions/retained_text-{state}.jsonl"):
            if row["bill_id"] in cases:
                require(row["input_id"] in inputs, "prediction lacks complete original source")
                old_predictions[row["input_id"]] = row
    for _, row in records(majority / "decisions/context_assignments.jsonl"):
        if row["bill_id"] in cases:
            baseline_contexts[row["bill_id"]] = row
    require(
        len(cases) == len(baseline_contexts) == advisory["complete_contexts"]
        and len(inputs) == len(old_predictions) == advisory["complete_source_views"],
        "all selected contexts and source alternatives required",
    )
    checkpoint = Path(original_plan["checkpoint"])
    training = read(checkpoint / "training_manifest.json")
    configuration = read(checkpoint / "config.json")
    require(
        all(
            value["max_tokens"] <= configuration["max_position_embeddings"]
            for value in PROFILES.values()
        ),
        "profile exceeds native model context",
    )
    producers = {
        "pilot_context_windows.py": Path(__file__).absolute(),
        "context_profiles.py": Path(context_profiles.__file__).absolute(),
        "majority_topics.py": Path(majority_topics.__file__).absolute(),
        "modernbert.py": Path(modernbert.__file__).absolute(),
        "recreate_score_diagnostics.py": Path(diagnostics.__file__).absolute(),
        "theme.py": Path(theme.__file__).absolute(),
    }
    producer_pins = {name: binding(path) for name, path in producers.items()}
    device = select_device()
    plan = {
        "schema": "state-politics.context-window-pilot.v1",
        "status": "frozen_before_longer_context_encoder_calls",
        "base_training_manifest": binding(checkpoint / "training_manifest.json"),
        "trained_input_configuration_unchanged": training["input"],
        "inference_profiles_not_retraining": PROFILES,
        "decision": original_plan["decision"],
        "majority_policy": majority_topics.POLICY,
        "selected_context_ids": sorted(cases),
        "complete_contexts": len(cases),
        "complete_source_views": len(inputs),
        "source_job": str(job),
        "source_input_bindings": majority_manifest["source_inference_inputs"],
        "majority_manifest": binding(majority / "manifest.json"),
        "casebook_manifest": binding(casebook / "manifest.json"),
        "selected_not_representative_or_independent_human_validation": True,
        "encoder_cache_unit": "model_plus_document_sha_plus_token_interval_plus_exact_encoder_ids",
        "old_short_document_decisions_are_never_used_as_long_context_logits": True,
        "batch_order": "longest_first",
        "padded_token_budget": 8192,
        "maximum_batch_size": 2,
        "device": device,
        "torch_version": torch.__version__,
        "transformers_version": transformers.__version__,
        "attention_implementation": "sdpa",
        "producers": producer_pins,
        **dict.fromkeys(FLAGS, False),
    }
    if args.resume:
        require(read(output / "plan.json") == plan, "resume plan/weights/runtime/source changed")
        for name, expected in producer_pins.items():
            checked(output / "producers" / name, expected)
        if (output / "manifest.json").exists():
            require(
                (output / "complete_download.json").exists(),
                "encoder finished but ZIP finalization interrupted; preserve this output",
            )
            completed = read(output / "manifest.json")
            for name, expected in completed["artifacts"].items():
                checked(output / name, expected)
            download = read(output / "complete_download.json")
            checked(output / "manifest.json", download["manifest"])
            checked(
                output / "research-data/complete_context_window_pilot.zip",
                {key: download["complete_research_zip"][key] for key in ("sha256", "bytes")},
            )
            return completed
    else:
        for folder in (
            "evidence",
            "producers",
            "profiles",
            "source-texts",
            "chart-data",
            "graphs",
            "research-data",
        ):
            (output / folder).mkdir(parents=True)
        save(output / "plan.json", plan)
        for name, path in producers.items():
            shutil.copyfile(path, output / "producers" / name)
        write_rows(output / "evidence/complete_original_inputs.jsonl", inputs.values())
        write_rows(
            output / "evidence/complete_original_predictions.jsonl", old_predictions.values()
        )
        write_rows(
            output / "evidence/complete_majority_baseline_contexts.jsonl",
            baseline_contexts.values(),
        )
        shutil.copyfile(
            casebook / "comparison.json", output / "evidence/original_assistant_reviews.json"
        )
        shutil.copyfile(
            checkpoint / "training_manifest.json", output / "evidence/training_manifest.json"
        )
    run_sha = binding(output / "plan.json")["sha256"]
    topics = load_topics(original_plan["topics_path"])
    classifier = ModernBertClassifier(
        topics,
        checkpoint,
        allow_provisional=True,
        device=device,
        topics_path=original_plan["topics_path"],
    )
    require(classifier.base_model_run == original_plan["model_run"], "wrong frozen weights")
    untouched_manifest = copy.deepcopy(classifier.manifest)
    codes = classifier.output_codes
    gates = {name: original_plan["decision"][name] for name in ("min_confidence", "min_margin")}
    tokenizations, windows_by_profile, baseline_windows = {}, {}, {}
    for input_id, source in inputs.items():
        text = input_text(source)
        digest = source["input_sha256"]
        if digest not in tokenizations:
            encoded = classifier.tokenizer(
                text, add_special_tokens=False, return_offsets_mapping=True, truncation=False
            )
            tokenizations[digest] = {
                "input_sha256": digest,
                "complete_text_characters": len(text),
                "input_ids": encoded["input_ids"],
                "offset_mapping": [list(pair) for pair in encoded["offset_mapping"]],
            }
            target = output / "source-texts" / f"{digest}.txt"
            if target.exists():
                require(target.read_bytes() == text.encode("utf-8"), "resumed source text changed")
            else:
                target.write_bytes(text.encode("utf-8"))
        encoded = tokenizations[digest]
        base = profile_windows(
            classifier.tokenizer,
            text,
            encoded["input_ids"],
            encoded["offset_mapping"],
            max_tokens=training["input"]["max_tokens"],
            overlap=training["input"]["overlap"],
        )
        old = old_predictions[input_id]
        require(
            old["input_sha256"] == digest and old["bill_id"] == source["bill_id"],
            "original prediction does not belong to this complete source input",
        )
        diagnostics.prediction_scores(old, codes, original_plan["decision"])
        require(
            base["chunk_spans"] == json.loads(old["chunk_spans"])
            and base["n_input_tokens"] == old["n_input_tokens"],
            "baseline tokenizer/window reconstruction changed",
        )
        for span, ids, logits in zip(
            base["token_spans"], base["encoder_inputs"], json.loads(old["logits"]), strict=True
        ):
            key = encoder_window_key(classifier.base_model_run, digest, span, ids)
            value = {
                "input_sha256": digest,
                "token_span": span,
                "encoder_input_ids": ids,
                "logits": logits,
                "origin": "frozen1024",
            }
            require(
                key not in baseline_windows or baseline_windows[key] == value,
                "conflicting exact baseline encoder-window evidence",
            )
            baseline_windows[key] = value
        for profile, settings in PROFILES.items():
            prepared = profile_windows(
                classifier.tokenizer,
                text,
                encoded["input_ids"],
                encoded["offset_mapping"],
                **settings,
            )
            prepared["window_keys"] = [
                encoder_window_key(classifier.base_model_run, digest, span, ids)
                for span, ids in zip(
                    prepared["token_spans"], prepared["encoder_inputs"], strict=True
                )
            ]
            windows_by_profile[profile, input_id] = prepared
    if not args.resume:
        write_rows(output / "evidence/complete_tokenizations.jsonl", tokenizations.values())
    else:
        require(
            list(row for _, row in records(output / "evidence/complete_tokenizations.jsonl"))
            == list(tokenizations.values()),
            "resumed complete tokenization changed",
        )
    connection = sqlite3.connect(output / "encoder_windows.sqlite")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS windows (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
        "sha256 TEXT NOT NULL, batch_id INTEGER)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS batches (id INTEGER PRIMARY KEY, profile TEXT NOT NULL, "
        "value TEXT NOT NULL)"
    )
    existing = connection.execute("SELECT value FROM metadata WHERE key='plan'").fetchone()
    if existing:
        require(existing[0] == run_sha, "encoder cache belongs to another experiment")
    else:
        require(
            connection.execute("SELECT count(*) FROM windows").fetchone()[0] == 0
            and connection.execute("SELECT count(*) FROM batches").fetchone()[0] == 0,
            "unbound encoder cache contains completed work",
        )
        connection.execute("INSERT INTO metadata VALUES ('plan',?)", (run_sha,))
    planned = {
        profile: {
            key
            for input_id in inputs
            for key in windows_by_profile[profile, input_id]["window_keys"]
        }
        for profile in PROFILES
    }
    cache = {}
    for key, raw, digest in connection.execute("SELECT key,value,sha256 FROM windows"):
        value = json.loads(raw)
        require(
            sha(value) == digest
            and key
            == encoder_window_key(
                classifier.base_model_run,
                value["input_sha256"],
                value["token_span"],
                value["encoder_input_ids"],
            ),
            "poisoned encoder-window cache identity or payload",
        )
        require(
            len(value["logits"]) == len(codes) and all(math.isfinite(x) for x in value["logits"]),
            "invalid cached logits",
        )
        require(
            key in baseline_windows
            if value["origin"] == "frozen1024"
            else value["origin"] in PROFILES and key in planned[value["origin"]],
            "cached encoder window does not belong to its declared profile",
        )
        cache[key] = value
    with connection:
        for key, value in baseline_windows.items():
            if key in cache:
                require(cache[key] == value, "cached baseline encoder logits changed")
            else:
                connection.execute(
                    "INSERT INTO windows VALUES (?,?,?,NULL)", (key, json.dumps(value), sha(value))
                )
                cache[key] = value
    profile_sources, work_rows = {}, []
    for profile in PROFILES:
        wanted = {}
        for input_id, source in inputs.items():
            prepared = windows_by_profile[profile, input_id]
            for key, span, ids in zip(
                prepared["window_keys"],
                prepared["token_spans"],
                prepared["encoder_inputs"],
                strict=True,
            ):
                if key not in cache:
                    wanted[key] = {
                        "input_sha256": source["input_sha256"],
                        "token_span": span,
                        "encoder_input_ids": ids,
                    }
        ordered = list(wanted.items())
        print("PROFILE_START", profile, "NEW_WINDOWS", len(ordered), flush=True)
        for batch in encode_window_batches(
            classifier,
            [value["encoder_input_ids"] for _, value in ordered],
            batch_size=2,
            padded_token_budget=8192,
        ):
            batch["window_keys"] = [ordered[index][0] for index in batch["indices"]]
            with connection:
                cursor = connection.execute(
                    "INSERT INTO batches(profile,value) VALUES (?,?)", (profile, json.dumps(batch))
                )
                for index, logits in zip(batch["indices"], batch["logits"], strict=True):
                    key, base = ordered[index]
                    value = {**base, "logits": logits, "origin": profile}
                    require(key not in cache, "encoder repeated a completed bound window")
                    connection.execute(
                        "INSERT INTO windows VALUES (?,?,?,?)",
                        (key, json.dumps(value), sha(value), cursor.lastrowid),
                    )
                    cache[key] = value
            print(
                "ENCODER_BATCH",
                profile,
                cursor.lastrowid,
                len(batch["indices"]),
                "PADDED_TOKENS",
                batch["padded_tokens"],
                flush=True,
            )
        by_bill, predictions = defaultdict(list), []
        reused_baseline = reused_profile = 0
        for input_id, source in inputs.items():
            prepared = windows_by_profile[profile, input_id]
            logits = [cache[key]["logits"] for key in prepared["window_keys"]]
            decision = window_majority(logits, codes, **original_plan["decision"])
            by_bill[source["bill_id"]].append((source["input_sha256"], decision))
            for key in prepared["window_keys"]:
                reused_baseline += cache[key]["origin"] == "frozen1024"
                reused_profile += cache[key]["origin"] not in ("frozen1024", profile)
            predictions.append(
                {
                    "input_id": input_id,
                    "bill_id": source["bill_id"],
                    "input_sha256": source["input_sha256"],
                    "base_model_run": classifier.base_model_run,
                    "context_profile": profile,
                    "context_profile_run": sha([run_sha, profile]),
                    "n_input_tokens": prepared["n_input_tokens"],
                    "n_discarded_tokens": 0,
                    "token_spans": prepared["token_spans"],
                    "chunk_spans": prepared["chunk_spans"],
                    "encoder_window_keys": prepared["window_keys"],
                    "logits": logits,
                    "majority_decision": asdict(decision),
                    **dict.fromkeys(FLAGS, False),
                }
            )
        write_rows(output / "profiles" / f"{profile}-source-predictions.jsonl", predictions)
        profile_sources[profile] = {
            bill_id: asdict(source_majority(values, codes, **gates))
            for bill_id, values in by_bill.items()
        }
        batches = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT value FROM batches WHERE profile=? ORDER BY id", (profile,)
            )
        ]
        work_rows.append(
            {
                "profile": profile,
                "planned_windows": sum(
                    len(windows_by_profile[profile, key]["window_keys"]) for key in inputs
                ),
                "new_encoder_windows": sum(len(batch["indices"]) for batch in batches),
                "new_encoder_tokens_without_padding": sum(
                    sum(batch["input_lengths"]) for batch in batches
                ),
                "actual_padded_encoder_tokens": sum(batch["padded_tokens"] for batch in batches),
                "exact_baseline_windows_reused": reused_baseline,
                "exact_prior_profile_windows_reused": reused_profile,
                "encoder_seconds": sum(batch["encoder_seconds"] for batch in batches),
            }
        )
        require(classifier.manifest == untouched_manifest, "trained checkpoint manifest mutated")
        print("PROFILE_COMPLETE", profile, json.dumps(work_rows[-1]), flush=True)
    require(
        connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
        "encoder cache integrity failure",
    )
    write_rows(
        output / "evidence/complete_encoder_window_cache.jsonl",
        ({"key": key, **value} for key, value in sorted(cache.items())),
    )
    write_rows(
        output / "evidence/complete_encoder_batch_receipts.jsonl",
        (
            {"batch_id": index, "profile": profile, **json.loads(value)}
            for index, profile, value in connection.execute(
                "SELECT id,profile,value FROM batches ORDER BY id"
            )
        ),
    )
    connection.close()
    summaries, comparisons, rescued, contexts = [], [], [], []
    modes = ["unanimity1024", "majority1024", *PROFILES]
    for mode in modes:
        counts, matches, rescue_counts = Counter(), Counter(), Counter()
        additions = losses = changed = 0
        for bill_id, case in cases.items():
            baseline = baseline_contexts[bill_id]["majority_candidate"]
            if mode == "unanimity1024":
                old = baseline_contexts[bill_id]
                decision = {
                    "status": "classified" if old["topic"] is not None else "uncertain",
                    "topic": old["topic"],
                }
            elif mode == "majority1024":
                decision = baseline
            else:
                decision = profile_sources[mode][bill_id]
            label = comparison(decision["topic"], decision["status"], case["advisory_topic"])
            matches[label] += 1
            counts[decision["status"]] += 1
            additions += baseline["status"] != "classified" and decision["status"] == "classified"
            losses += baseline["status"] == "classified" and decision["status"] != "classified"
            changed += (
                baseline["status"] == decision["status"] == "classified"
                and baseline["topic"] != decision["topic"]
            )
            row = {
                "profile": mode,
                "bill_id": bill_id,
                "state": case["state"],
                "identifier": case["identifier"],
                "candidate_status": decision["status"],
                "candidate_topic": decision["topic"],
                "assistant_proposal_not_gold": case["advisory_topic"],
                "comparison_not_accuracy": label,
            }
            comparisons.append(row)
            rescue = baseline if baseline["status"] == "classified" else decision
            rescue_label = comparison(rescue["topic"], rescue["status"], case["advisory_topic"])
            rescue_counts[rescue_label] += 1
            rescued.append(
                {
                    **row,
                    "candidate_status": rescue["status"],
                    "candidate_topic": rescue["topic"],
                    "comparison_not_accuracy": rescue_label,
                }
            )
        summaries.append(
            {
                "profile": mode,
                "label": mode,
                "contexts": len(cases),
                "assigned": counts["classified"],
                "unassigned": len(cases) - counts["classified"],
                **{
                    key: matches[key]
                    for key in (
                        "same_assigned_topic",
                        "different_assigned_topic",
                        "assigned_advisory_unresolved",
                    )
                },
                "new_assignments_over_majority1024": additions,
                "lost_assignments_against_majority1024": losses,
                "changed_assigned_topics_against_majority1024": changed,
                "rescue_only_assistant_comparisons_not_accuracy": dict(rescue_counts),
            }
        )
    for bill_id, original in baseline_contexts.items():
        contexts.append(
            {
                **original,
                "long_context_candidates": {
                    profile: profile_sources[profile][bill_id] for profile in PROFILES
                },
            }
        )
    write_rows(output / "profiles/complete_context_comparisons.jsonl", contexts)
    csv_summaries = [
        {
            **row,
            "rescue_only_assistant_comparisons_not_accuracy": json.dumps(
                row["rescue_only_assistant_comparisons_not_accuracy"], sort_keys=True
            ),
        }
        for row in summaries
    ]
    for name, values in (
        ("profile_summary", csv_summaries),
        ("context_comparison", comparisons),
        ("rescue_only_comparison", rescued),
        ("encoder_work", work_rows),
    ):
        diagnostics.write_csv(output / "chart-data" / f"{name}.csv", values)
    figures = render(output / "graphs", summaries, work_rows)
    summary = {
        "status": "complete_selected_context_window_pilot_not_human_validation",
        "notice": NOTICE,
        "plan_sha256": run_sha,
        "contexts": len(cases),
        "source_views": len(inputs),
        "unique_complete_input_strings": len(tokenizations),
        "complete_policy_characters": sum(len(input_text(row)) for row in inputs.values()),
        "base_model_run": classifier.base_model_run,
        "trained_input_configuration_unchanged": training["input"],
        "native_model_maximum_positions": configuration["max_position_embeddings"],
        "profile_comparisons": summaries,
        "actual_encoder_work": work_rows,
        "no_original_or_new_profile_tokens_discarded": True,
        "old_short_document_logits_never_misused_as_long_window_logits": True,
        "training_manifest_or_weights_updated": False,
        "primary_population_outputs_replaced": False,
        "independent_human_validation": False,
        **dict.fromkeys(FLAGS, False),
    }
    save(output / "summary.json", summary)
    cards = "".join(
        f"<section><h2>{html.escape(name.replace('_', ' '))}</h2>"
        f'<a href="graphs/{name}.png"><img src="graphs/{name}.png" alt="{name}"></a>'
        f'<p><a href="graphs/{name}.svg">SVG</a></p></section>'
        for name in figures
    )
    source_links = "".join(
        f"<li>{html.escape(row['state'] + ' ' + row['identifier'])} "
        f'<a href="source-texts/{row["input_sha256"]}.txt">Complete model input</a></li>'
        for row in inputs.values()
    )
    (output / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Longer-context classification pilot</title><style>"
        f"body{{max-width:1100px;margin:36px auto;padding:0 22px;background:{theme.BG};"
        f"color:{theme.TEXT};font:16px/1.6 Georgia,serif}}a{{color:{theme.BLUE};"
        "overflow-wrap:anywhere}img{max-width:100%;height:auto}section{margin:36px 0}"
        "</style><p>LOCAL / UNPUBLISHED / SELECTED PILOT ONLY</p>"
        "<h1>Longer context, same frozen weights</h1>"
        f"<p>{html.escape(NOTICE)}</p><p>{len(cases)} selected contexts; {len(inputs)} "
        "complete source views. No policy text is truncated. The registered training "
        "configuration remains 1,024 tokens; 4,096/8,192 are explicit inference experiments.</p>"
        '<p><a download href="research-data/complete_context_window_pilot.zip">'
        "Complete source inputs, tokenizations, encoder windows, logits and comparisons (ZIP)</a>"
        ' &middot; <a href="summary.json">Summary</a> &middot; '
        '<a href="plan.json">Frozen pilot plan</a></p>'
        f"{cards}<details><summary>All complete model-input texts</summary>"
        f"<ul>{source_links}</ul></details>"
    )
    for name, path in producers.items():
        checked(path, producer_pins[name])
    checked(checkpoint / "training_manifest.json", plan["base_training_manifest"])
    for name, digest in training["checkpoint_files"].items():
        require(
            binding(checkpoint / name)["sha256"] == digest, "frozen model/tokenizer file changed"
        )
    require(
        binding(majority / "manifest.json")["sha256"] == args.majority_sha256
        and binding(casebook / "manifest.json")["sha256"] == args.casebook_sha256,
        "original cohort/gallery changed",
    )
    artifacts = {
        str(path.relative_to(output)): binding(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    save(output / "manifest.json", {**summary, "artifacts": artifacts})
    members = {**artifacts, "manifest.json": binding(output / "manifest.json")}
    archive_path = output / "research-data/complete_context_window_pilot.zip"
    with ZipFile(archive_path, "x", compression=ZIP_DEFLATED, compresslevel=1) as archive:
        for name in members:
            archive.write(output / name, name)
    with ZipFile(archive_path) as archive:
        require(
            set(archive.namelist()) == set(members) and len(archive.namelist()) == len(members),
            "complete pilot ZIP members changed",
        )
        for name, expected in members.items():
            with archive.open(name) as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            require(
                {"sha256": digest, "bytes": archive.getinfo(name).file_size} == expected,
                "complete pilot ZIP member mismatch",
            )
    save(
        output / "complete_download.json",
        {
            "manifest": binding(output / "manifest.json"),
            "complete_research_zip": {**binding(archive_path), "members": len(members)},
            "metadata_only": False,
        },
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--majority-gallery", type=Path, required=True)
    parser.add_argument("--majority-sha256", required=True)
    parser.add_argument("--casebook", type=Path, required=True)
    parser.add_argument("--casebook-sha256", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--allow-provisional", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()

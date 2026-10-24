#!/usr/bin/env python3
"""Replay a complete retained-text snapshot offline, without an encoder or certification."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import pyarrow.parquet as pq
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.analysis.cycle_topics import (  # noqa: E402
    FLAGS,
    binding,
    checked,
    checked_job,
    input_text,
    records,
    require,
)
from state_politics.analysis.modernbert import (  # noqa: E402
    decide,
    model_input_ids,
    policy_tokens,
    section_windows,
)
from state_politics.bills.openstates_dump import STATE_CODES  # noqa: E402


def member(root, name):
    relative = PurePosixPath(name)
    require(
        relative.as_posix() == name
        and not relative.is_absolute()
        and ".." not in relative.parts
        and "\\" not in name,
        f"unsafe snapshot member: {name}",
    )
    path = root / name
    require(path.resolve() == path and path.is_file(), f"missing or linked member: {name}")
    return path


def audit(job, gallery, output, *, token_cache=None, token_cache_sha256=None):
    job, gallery, output = (Path(path).absolute() for path in (job, gallery, output))
    require(
        not output.exists()
        and output.resolve() == output
        and output.parent.is_dir()
        and not output.is_relative_to(job)
        and not output.is_relative_to(gallery),
        "audit requires a fresh report outside the immutable snapshot",
    )
    require(
        (token_cache is None) == (token_cache_sha256 is None),
        "verified token-cache path and external SHA-256 must be supplied together",
    )
    plan = checked_job(job)
    require("retained_text" in plan["tiers"], "retained-text inputs were not supplied")
    originals = {
        name: binding(member(job, name))
        for name in (
            "inference_plan.json",
            "contexts.jsonl",
            "progress-retained_text.json",
            "summary-retained_text.json",
            "bill_assignments-retained_text.parquet",
            "prediction_cache.sqlite",
        )
    }
    progress = json.loads((job / "progress-retained_text.json").read_bytes())
    require(
        progress["status"] == "complete_provisional_inference_not_scientific_validation"
        and set(progress["states"]) == {state.upper() for state in STATE_CODES}
        and progress["model_run"] == plan["model_run"]
        and progress["inference_plan_sha256"] == originals["inference_plan.json"]["sha256"]
        and all(progress[flag] is False for flag in FLAGS),
        "incomplete, changed or promoted inference progress",
    )
    training_path = Path(plan["checkpoint"]) / "training_manifest.json"
    training = json.loads(training_path.read_bytes())
    codes, config = training["output_codes"], training["input"]
    tokenizer = AutoTokenizer.from_pretrained(
        plan["checkpoint"],
        local_files_only=True,
        trust_remote_code=False,
    )
    prefix, _ = policy_tokens(tokenizer, "", "bill")
    budget = config["max_tokens"] - len(prefix) - tokenizer.num_special_tokens_to_add()
    cache_identity = json.dumps(
        {
            "training_manifest": plan["training_manifest"],
            "input_config": config,
            "prefix": prefix,
            "runtime": plan["frozen_inference_runtime"],
            "transformers": importlib.metadata.version("transformers"),
            "tokenizers": importlib.metadata.version("tokenizers"),
        },
        sort_keys=True,
    )
    token_cache = Path(token_cache).absolute() if token_cache is not None else None
    cache_binding, connection = None, None
    if token_cache is not None:
        require(
            token_cache.resolve() == token_cache and token_cache.is_file(),
            "verified token cache is missing or linked",
        )
        cache_binding = binding(token_cache)
        require(cache_binding["sha256"] == token_cache_sha256, "verified token-cache hash changed")
        connection = sqlite3.connect(f"{token_cache.as_uri()}?mode=ro", uri=True)
    memo = {}
    grouped = defaultdict(lambda: {"topics": set(), "n": 0, "reasons": Counter()})
    seen, pins, state_totals, reason_counts = set(), {}, {}, Counter()
    fresh = reused = excluded_tokens = 0
    try:
        if connection is not None:
            require(
                connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
                and connection.execute("SELECT value FROM identity").fetchall()
                == [(cache_identity,)],
                "verified token-cache contents or tokenizer identity changed",
            )
        for state, checkpoint in sorted(progress["states"].items()):
            name = f"inputs/retained_text-{state}.jsonl"
            source = member(job, name)
            predicted = member(job, f"predictions/retained_text-{state}.jsonl")
            checked(source, {key: plan["inputs"][name][key] for key in ("sha256", "bytes")})
            checked(predicted, checkpoint["artifact"])
            pins[str(source)], pins[str(predicted)] = binding(source), binding(predicted)
            count = tokens = windows = exclusions = 0
            pairs = zip(records(source), records(predicted), strict=True)
            for (_, original), (_, prediction) in pairs:
                text = input_text(original)
                sha = hashlib.sha256(text.encode()).hexdigest()
                require(
                    prediction["input_sha256"] == original["input_sha256"] == sha
                    and all(
                        prediction[key] == original[key]
                        for key in (
                            "input_id",
                            "view_id",
                            "bill_id",
                            "state",
                            "tier",
                        )
                    )
                    and prediction["input_id"] not in seen
                    and original["state"] == state
                    and original["tier"] == "retained_text"
                    and prediction["model_run"] == plan["model_run"]
                    and all(prediction[flag] is False for flag in FLAGS),
                    f"changed, duplicate or promoted source prediction: {original['input_id']}",
                )
                seen.add(prediction["input_id"])
                if original["pre_inference_exclusion"]:
                    require(
                        prediction["topic"] is None
                        and prediction["n_chunks"] == 0
                        and prediction["n_input_tokens"] is None
                        and prediction["n_discarded_tokens"] is None
                        and prediction["abstention_reason"] == original["pre_inference_exclusion"],
                        f"explicit source exclusion changed: {original['input_id']}",
                    )
                    excluded_tokens += len(
                        tokenizer(
                            text,
                            add_special_tokens=False,
                            truncation=False,
                        )["input_ids"]
                    )
                    exclusions += 1
                else:
                    cached = (
                        connection.execute(
                            "SELECT n_chars,n_tokens,spans FROM tokens WHERE sha=?",
                            (sha,),
                        ).fetchone()
                        if connection is not None
                        else memo.get(sha)
                    )
                    if connection is not None:
                        require(
                            cached is not None, f"input absent from verified token cache: {sha}"
                        )
                    if cached is None:
                        encoded = tokenizer(
                            text,
                            add_special_tokens=False,
                            return_offsets_mapping=True,
                            truncation=False,
                        )
                        ids, offsets = encoded["input_ids"], encoded["offset_mapping"]
                        ranges = section_windows(text, offsets, budget, config["overlap"])
                        require(
                            (not ids and not ranges)
                            or (
                                ranges[0][0] == 0
                                and ranges[-1][1] == len(ids)
                                and all(
                                    left <= right
                                    for (_, right), (left, _) in zip(
                                        ranges, ranges[1:], strict=False
                                    )
                                )
                            ),
                            f"token windows omit source text: {original['input_id']}",
                        )
                        require(
                            all(
                                0
                                < len(model_input_ids(tokenizer, prefix + ids[left:right]))
                                <= config["max_tokens"]
                                for left, right in ranges
                            ),
                            f"token window exceeds the frozen budget: {original['input_id']}",
                        )
                        spans = [
                            [offsets[left][0], offsets[right - 1][1]] for left, right in ranges
                        ]
                        expected_tokens = len(ids)
                        memo[sha] = len(text), expected_tokens, json.dumps(spans)
                        fresh += 1
                    else:
                        require(cached[0] == len(text), f"cached source length changed: {sha}")
                        expected_tokens, spans = cached[1], json.loads(cached[2])
                        reused += 1
                    require(
                        prediction["n_input_tokens"] == expected_tokens
                        and json.loads(prediction["chunk_spans"]) == spans
                        and prediction["n_chunks"] == len(spans)
                        and prediction["n_discarded_tokens"] == 0
                        and json.loads(prediction["output_codes"]) == codes,
                        f"saved token coverage or taxonomy changed: {original['input_id']}",
                    )
                    logits = json.loads(prediction["logits"])
                    require(len(logits) == len(spans), "saved logit/window counts disagree")
                    decision = decide(logits, codes, **plan["decision"])
                    for key, value in asdict(decision).items():
                        actual = json.loads(prediction[key]) if key == "scores" else prediction[key]
                        expected = list(value) if key == "scores" else value
                        require(
                            actual == expected,
                            f"saved decision differs: {original['input_id']} {key}",
                        )
                    tokens += expected_tokens
                    windows += len(spans)
                group = grouped[prediction["bill_id"]]
                group["topics"].add(prediction["topic"])
                group["n"] += 1
                if prediction["abstention_reason"]:
                    group["reasons"][prediction["abstention_reason"]] += 1
                    reason_counts[prediction["abstention_reason"]] += 1
                count += 1
            require(
                count == checkpoint["views"] == plan["inputs"][name]["views"]
                and tokens == checkpoint["source_tokens"]
                and windows == checkpoint["windows"]
                and exclusions == checkpoint["explicit_pre_inference_exclusions"],
                f"saved state totals disagree: {state}",
            )
            state_totals[state] = {
                "views": count,
                "logical_source_tokens": tokens,
                "logical_windows": windows,
                "explicit_exclusions": exclusions,
            }
            print("REPLAYED_STATE", state, count, flush=True)
        unique_tokens = (
            connection.execute("SELECT count(*) FROM tokens").fetchone()[0]
            if connection is not None
            else len(memo)
        )
    finally:
        if connection is not None:
            connection.close()
    assignment_counts, topic_counts, context_ids = Counter(), Counter(), set()
    assignments = job / "bill_assignments-retained_text.parquet"
    saved = (
        row
        for batch in pq.ParquetFile(assignments).iter_batches(batch_size=256)
        for row in batch.to_pylist()
    )
    for (_, context), actual in zip(records(job / "contexts.jsonl"), saved, strict=True):
        identifier = context["bill_id"]
        require(identifier not in context_ids, f"duplicate original context: {identifier}")
        context_ids.add(identifier)
        group = grouped.get(identifier)
        topics, n_views = (group["topics"], group["n"]) if group else (set(), 0)
        topic = next(iter(topics)) if len(topics) == 1 and None not in topics else None
        status = (
            "unavailable" if not n_views else "classified" if topic is not None else "abstained"
        )
        reason = (
            "no_supplied_retained_text"
            if not n_views
            else "source_alternative_disagreement"
            if len(topics) > 1
            else "all_source_views_abstained"
            if topic is None
            else None
        )
        expected = {
            **context,
            "topic": topic,
            "inference_status": status,
            "abstention_reason": reason,
            "n_source_views": n_views,
            "view_abstention_reasons": json.dumps(dict(group["reasons"])) if group else "{}",
            "model_run": plan["model_run"] if n_views else None,
            **FLAGS,
        }
        require(
            json.dumps(actual, sort_keys=True, allow_nan=False)
            == json.dumps(expected, sort_keys=True, allow_nan=False),
            f"original fields, unknowns or consensus changed: {identifier}",
        )
        assignment_counts[status] += 1
        if topic is not None:
            topic_counts[str(topic)] += 1
    require(
        grouped.keys() <= context_ids
        and len(context_ids) == plan["n_contexts"]
        and len(seen) == plan["n_views_by_tier"]["retained_text"],
        "source views or original contexts are incomplete",
    )
    summary = json.loads((job / "summary-retained_text.json").read_bytes())
    require(
        summary["contexts"] == len(context_ids)
        and summary["source_views"] == len(seen)
        and summary["assignment_counts"] == dict(assignment_counts)
        and summary["topic_counts"] == dict(topic_counts)
        and all(summary[flag] is False for flag in FLAGS),
        "saved summary disagrees with complete replay",
    )
    checked(assignments, summary["assignments"])
    gallery_path = member(gallery, "manifest.json")
    gallery_binding = binding(gallery_path)
    manifest = json.loads(gallery_path.read_bytes())
    require(
        manifest["status"] == "complete_provisional_topic_graphs_not_scientific_validation"
        and manifest["tiers"] == ["retained_text"]
        and all(manifest[flag] is False for flag in FLAGS)
        and manifest["model_promotion"] is False
        and manifest["publication"] is False
        and manifest["candidate_contexts"] == len(context_ids)
        and manifest["model_run"] == plan["model_run"]
        and manifest["assignment_counts_by_tier"]["retained_text"]
        == {
            "candidate_contexts": len(context_ids),
            **assignment_counts,
        },
        "gallery is incomplete, promoted or inconsistent with the saved inference",
    )
    for name, expected in manifest["artifacts"].items():
        checked(member(gallery, name), expected)
    inventory = list(gallery.rglob("*"))
    require(
        all(not path.is_symlink() for path in inventory)
        and {path.relative_to(gallery).as_posix() for path in inventory if path.is_file()}
        == set(manifest["artifacts"]) | {"manifest.json"},
        "gallery contains unlisted or linked files",
    )
    expected_members = {
        "inference_plan.json",
        "contexts.jsonl",
        "progress-retained_text.json",
        "summary-retained_text.json",
        "bill_assignments-retained_text.parquet",
        "producer/cycle_topics.py",
        "producer/modernbert.py",
        "producer/topics.yml",
    } | {
        f"{kind}/retained_text-{state}.jsonl"
        for state in progress["states"]
        for kind in ("inputs", "predictions")
    }
    require(
        set(manifest["inference_inputs"]) == expected_members,
        "complete inference download omits required frozen inputs, predictions or producers",
    )
    checked(member(job, "producer/cycle_topics.py"), plan["producer"])
    checked(member(job, "producer/modernbert.py"), plan["frozen_inference_runtime"])
    require(
        binding(member(job, "producer/topics.yml"))["sha256"] == plan["taxonomy_sha256"],
        "downloaded taxonomy differs from the frozen model",
    )
    zip_path = member(gallery, "research-data/complete_inference_inputs_and_predictions.zip")
    with ZipFile(zip_path) as archive:
        names = archive.namelist()
        require(
            len(names) == len(set(names)) and set(names) == set(manifest["inference_inputs"]),
            "complete inference ZIP contains duplicate, missing or extra members",
        )
        for name, expected in manifest["inference_inputs"].items():
            checked(member(job, name), expected)
            digest, size = hashlib.sha256(), 0
            with archive.open(name) as stream:
                for block in iter(lambda: stream.read(2**20), b""):
                    digest.update(block)
                    size += len(block)
            require(
                {"sha256": digest.hexdigest(), "bytes": size} == expected,
                f"complete ZIP member differs from the original inference: {name}",
            )
    for name, expected in originals.items():
        checked(job / name, expected)
    for path, expected in pins.items():
        checked(Path(path), expected)
    checked(gallery_path, gallery_binding)
    if token_cache is not None:
        checked(token_cache, cache_binding)
    report = {
        "status": "passed_complete_saved_inference_replay_not_scientific_validation",
        "job": str(job),
        "original_job_bindings": originals,
        "completed_states_replayed": len(state_totals),
        "state_totals": state_totals,
        "source_views": len(seen),
        "candidate_contexts": len(context_ids),
        "assignment_counts": dict(assignment_counts),
        "topic_counts": dict(topic_counts),
        "logical_source_view_tokens": sum(
            r["logical_source_tokens"] for r in state_totals.values()
        ),
        "logical_source_view_windows": sum(r["logical_windows"] for r in state_totals.values()),
        "view_abstention_reasons": dict(reason_counts),
        "explicitly_excluded_source_tokens_separate_from_inferred_totals": excluded_tokens,
        "every_source_hash_saved_logit_decision_token_window_and_original_context_replayed": True,
        "new_independent_tokenizations": fresh,
        "reused_independently_verified_tokenizations": reused,
        "verified_token_cache": {
            "path": str(token_cache),
            **cache_binding,
            "unique_verified_inputs": unique_tokens,
            "read_only": True,
        }
        if token_cache is not None
        else None,
        "gallery_manifest": {"path": str(gallery_path), **gallery_binding},
        "gallery_artifacts_verified": len(manifest["artifacts"]),
        "complete_research_zip": {
            "path": str(zip_path),
            **binding(zip_path),
            "members": len(names),
        },
        "auditor": binding(Path(__file__).absolute()),
        "independent_encoder_passes": 0,
        "independent_human_validation": False,
        "model_promotion": False,
        "publication": False,
    }
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--gallery", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verified-token-cache", type=Path)
    parser.add_argument("--verified-token-cache-sha256")
    args = parser.parse_args(argv)
    result = audit(
        args.job,
        args.gallery,
        args.out,
        token_cache=args.verified_token_cache,
        token_cache_sha256=args.verified_token_cache_sha256,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

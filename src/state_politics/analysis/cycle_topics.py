"""Resumable, explicitly provisional topic inference over frozen cycle evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from itertools import islice
from pathlib import Path

from ..bills.missouri import parse_withdrawal_notice
from ..bills.openstates_dump import STATE_CODES
from ..provenance import sha256_file
from .modernbert import (
    ModernBertClassifier,
    decide,
    model_input_ids,
    policy_tokens,
    section_windows,
)
from .revealed import is_procedural_shell_title, is_source_test_title
from .taxonomy import DEFAULT_TOPICS_PATH, load_topics

SCHEMA = "state-politics.provisional-cycle-topics.v1"
SOURCES = {
    "metadata": ("bills",),
    "retained_text": ("native", "snapshot", "corpus", "archive"),
}
FLAGS = {
    "scientific_approval": False,
    "model_input_approved": False,
    "training_admission": False,
    "analytical_admission": False,
    "filing_time_text_certified": False,
    "publication_approved": False,
    "party_attribution_approved": False,
}
ROOT = Path(__file__).resolve().parents[3]


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible provisional inference: {message}")


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def binding(path):
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def read(path):
    return json.loads(path.read_bytes())


def records(path):
    with path.open("rb") as handle:
        for ordinal, line in enumerate(handle, 1):
            require(bool(line.strip()), "blank physical input record")
            yield ordinal, json.loads(line)


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def write_row(handle, row):
    handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")


def checked(path, expected):
    require(path.is_file() and path.resolve() == path.absolute(), f"missing/linked file: {path}")
    require(binding(path) == expected, f"file binding mismatch: {path}")


def source_text(row):
    if row["source_type"] == "snapshot_text":
        return row["source_record"]["raw_text"]
    if row["source_type"] == "research_corpus_text":
        return row["source_record"]["text"]
    return row["text"]


def input_text(row):
    text = source_text(row["original_source_view"])
    span = row["source_text_span"]
    require(isinstance(text, str) and 0 <= span[0] <= span[1] <= len(text), "source text span")
    require(digest(text) == row["raw_source_text_sha256"], "original raw source text changed")
    value = text[span[0] : span[1]]
    require(digest(value) == row["input_sha256"], "complete selected input changed")
    return value


def make_input(row, tier, source, ordinal):
    for flag in ("model_input_approved", "filing_time_text_certified", "analytical_admission"):
        require(row.get(flag) is False, f"source admission changed: {flag}")
    text = source_text(row)
    require(isinstance(text, str), "retained input text must be a complete string")
    start = 0
    if row.get("archive_generated_prologue_preserved"):
        start = row["source_identity"]["policy_section_start"]
        require(
            type(start) is int and start > 0 and "Section 1:" in text[:start],
            "unbound archive machine-prologue boundary",
        )
    selected = text[start:]
    excluded = None
    if is_source_test_title(row["title"], row["state"]):
        excluded = "source_test_record"
    elif tier == "retained_text" and row["state"] == "MO" and parse_withdrawal_notice(selected):
        excluded = "withdrawal_notice_no_policy_text"
    elif (
        tier == "metadata"
        and not row.get("abstract")
        and is_procedural_shell_title(row["title"], row["state"])
    ):
        excluded = "procedural_shell"
    return {
        "input_id": f"{tier}:{row['view_id']}",
        "view_id": row["view_id"],
        "bill_id": row["bill_id"],
        "state": row["state"],
        "identifier": row["identifier"],
        "session_identifier": row["session_identifier"],
        "tier": tier,
        "input_sha256": digest(selected),
        "domain": "bill",
        "source_path": source,
        "source_row_ordinal": ordinal,
        "source_text_span": [start, len(text)],
        "raw_source_text_sha256": digest(text),
        "archive_machine_prologue_excluded_from_inference": start > 0,
        "pre_inference_exclusion": excluded,
        "original_source_view": row,
        **FLAGS,
    }


def freeze(preview: Path, checkpoint: Path, out: Path, *, tiers, topics=DEFAULT_TOPICS_PATH):
    preview, checkpoint, out = (path.absolute() for path in (preview, checkpoint, out))
    require(
        not out.exists() and out.resolve() == out and out.is_relative_to(ROOT / "data"),
        "new ignored project data output required",
    )
    require(set(tiers) <= SOURCES.keys() and len(set(tiers)) == len(tiers) > 0, "input tiers")
    manifest_path = preview / "downloads/build_manifest.json"
    require(manifest_path.resolve() == manifest_path, "linked preview manifest")
    preview_manifest = read(manifest_path)
    require(
        preview_manifest["publication_status"] == "local_only_unpublished"
        and preview_manifest["model_input_approved"] is False
        and preview_manifest["study_start"] == "2023-01-01"
        and preview_manifest["study_end"] == "2024-12-31",
        "unchanged cycle evidence required",
    )
    training = read(checkpoint / "training_manifest.json")
    require(
        training["status"] != "certified"
        and training["taxonomy_sha256"] == sha256_file(Path(topics)),
        "provisional model/taxonomy",
    )
    out.mkdir(parents=True)
    (out / "inputs").mkdir()
    (out / "producer").mkdir()
    producer = Path(__file__)
    shutil.copy2(producer, out / "producer/cycle_topics.py")
    shutil.copy2(producer.with_name("modernbert.py"), out / "producer/modernbert.py")
    shutil.copy2(topics, out / "producer/topics.yml")
    inputs, sources, contexts = {}, {}, {}
    totals = Counter()
    for state in sorted(code.upper() for code in STATE_CODES):
        metadata_path = preview / f"evidence/bills-{state}.jsonl"
        expected = preview_manifest["outputs"][f"evidence/bills-{state}.jsonl"]
        checked(metadata_path, expected)
        metadata_rows = [row for _, row in records(metadata_path)]
        state_contexts = {}
        for row in metadata_rows:
            context = row["bill_context"]
            if row["bill_id"] in state_contexts:
                require(state_contexts[row["bill_id"]] == context, "conflicting bill contexts")
            state_contexts[row["bill_id"]] = context
        require(not contexts.keys() & state_contexts.keys(), "cross-state duplicate bill identity")
        contexts.update(state_contexts)
        for tier in tiers:
            relative = f"inputs/{tier}-{state}.jsonl"
            count = 0
            seen = set()
            with (out / relative).open("w") as handle:
                for prefix in SOURCES[tier]:
                    source = f"evidence/{prefix}-{state}.jsonl"
                    require(source in preview_manifest["outputs"], f"source not supplied: {source}")
                    path = preview / source
                    checked(path, preview_manifest["outputs"][source])
                    sources[source] = preview_manifest["outputs"][source]
                    for ordinal, row in records(path):
                        require(
                            row["state"] == state and row["bill_id"] in state_contexts,
                            "source outside existing candidate identity",
                        )
                        context = state_contexts[row["bill_id"]]
                        require(
                            all(
                                row[key] == context[key]
                                for key in (
                                    "state",
                                    "identifier",
                                    "session_identifier",
                                )
                            ),
                            "source context identity mismatch",
                        )
                        if prefix == "snapshot":
                            snapshot = row["snapshot"]
                            if not snapshot["has_nonempty_raw_text"]:
                                continue
                            require(
                                snapshot["provider_flags"]["is_error"] in ("f", False),
                                "nonempty provider error cannot enter inference",
                            )
                            require(
                                snapshot["version_binding_status"] == "exact_version_foreign_keys",
                                "unbound provider text version",
                            )
                        unit = make_input(row, tier, source, ordinal)
                        require(unit["input_id"] not in seen, "duplicate source-view identity")
                        seen.add(unit["input_id"])
                        write_row(handle, unit)
                        count += 1
            inputs[relative] = {
                **binding(out / relative),
                "views": count,
                "state": state,
                "tier": tier,
            }
            totals[tier] += count
    with (out / "contexts.jsonl").open("w") as handle:
        for key in sorted(contexts):
            write_row(handle, contexts[key])
    require(
        len(contexts) == preview_manifest["counts"]["n_cycle_contexts"], "complete candidate union"
    )
    for source, expected in sources.items():
        checked(preview / source, expected)
    plan = {
        "schema": SCHEMA,
        "status": "frozen_before_provisional_population_inference",
        "preview": str(preview),
        "preview_manifest": binding(manifest_path),
        "checkpoint": str(checkpoint),
        "training_manifest": binding(checkpoint / "training_manifest.json"),
        "model_run": sha256_file(checkpoint / "training_manifest.json"),
        "model_status": training["status"],
        "decision": training["decision"],
        "topics_path": str(Path(topics).absolute()),
        "taxonomy_sha256": sha256_file(Path(topics)),
        "source_files": sources,
        "inputs": inputs,
        "tiers": list(tiers),
        "contexts": binding(out / "contexts.jsonl"),
        "n_contexts": len(contexts),
        "n_views_by_tier": dict(totals),
        "producer": binding(out / "producer/cycle_topics.py"),
        "frozen_inference_runtime": binding(out / "producer/modernbert.py"),
        "scope": "descriptive_model_assignments_not_validated_filing_attention_or_party_positions",
        "source_alternative_policy": "unanimous_nonnull_view_decisions_else_abstain",
        "source_selection": "all_complete_supplied_candidate_views_no_later_version_selection",
        "inference_engine": "cross_document_padded_windows_frozen_decision_v1",
        "record_block_size": 128,
        "padded_window_token_budget": 8192,
        "human_review_packet_modified_or_scored": False,
        **FLAGS,
    }
    write_json(out / "inference_plan.json", plan)
    return plan


def prediction_record(classifier, text, logits, spans, n_tokens):
    decision = decide(logits, classifier.output_codes, **classifier.manifest["decision"])
    return {
        **asdict(decision),
        "input_sha256": digest(text),
        "model_run": classifier.run_id,
        "base_model_run": classifier.base_model_run,
        "model_status": classifier.manifest["status"],
        "score_type": "uncalibrated_softmax",
        "input_domain": "bill",
        "n_input_tokens": n_tokens,
        "n_discarded_tokens": 0,
        "chunk_spans": json.dumps(spans),
        "logits": json.dumps(logits),
        "scores": json.dumps(decision.scores),
        "output_codes": json.dumps(classifier.output_codes),
        "taxonomy_sha256": classifier.manifest["taxonomy_sha256"],
        "calibration_sha256": classifier.calibration_sha256,
        "rejection_score": (
            decision.scores[-1] if classifier.output_codes[-1] is None and decision.scores else None
        ),
    }


def pooled_predictions(classifier, texts, *, batch_size=32, padded_token_budget=8192):
    """Batch windows across documents; preserve the frozen per-document decision rule."""
    import torch

    require(
        batch_size > 0 and padded_token_budget >= classifier.manifest["input"]["max_tokens"],
        "positive batch and sufficient padded token budget",
    )
    config = classifier.manifest["input"]
    prefix, _ = policy_tokens(classifier.tokenizer, "", "bill")
    budget = config["max_tokens"] - len(prefix) - classifier.tokenizer.num_special_tokens_to_add()
    documents, windows = [], []
    for index, text in enumerate(texts):
        encoded = classifier.tokenizer(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        ids, offsets = encoded["input_ids"], encoded["offset_mapping"]
        document_windows = section_windows(text, offsets, budget, config["overlap"])
        spans = [[offsets[left][0], offsets[right - 1][1]] for left, right in document_windows]
        documents.append({"logits": [None] * len(spans), "spans": spans, "tokens": len(ids)})
        for ordinal, (left, right) in enumerate(document_windows):
            windows.append(
                (index, ordinal, model_input_ids(classifier.tokenizer, prefix + ids[left:right]))
            )
    windows.sort(key=lambda item: len(item[2]))
    start = 0
    while start < len(windows):
        stop = start
        while stop < len(windows) and stop - start < batch_size:
            if (stop - start + 1) * len(windows[stop][2]) > padded_token_budget:
                break
            stop += 1
        require(stop > start, "individual model window exceeds the batch budget")
        batch = windows[start:stop]
        encoded = classifier.tokenizer.pad(
            [{"input_ids": item[2]} for item in batch],
            padding=True,
            return_attention_mask=True,
            return_tensors="pt",
        ).to(classifier.device)
        with torch.inference_mode():
            logits = classifier.model(**encoded).logits.float().cpu().tolist()
        require(len(logits) == len(batch), "one logit row required per submitted window")
        for (index, ordinal, _), value in zip(batch, logits, strict=True):
            documents[index]["logits"][ordinal] = value
        start = stop
    return [
        prediction_record(
            classifier, text, document["logits"], document["spans"], document["tokens"]
        )
        for text, document in zip(texts, documents, strict=True)
    ]


def checked_job(directory):
    plan = read(directory / "inference_plan.json")
    require(
        plan["schema"] == SCHEMA and all(plan.get(k) is False for k in FLAGS),
        "provisional inference plan/flags",
    )
    checked(Path(__file__), plan["producer"])
    checked(Path(__file__).with_name("modernbert.py"), plan["frozen_inference_runtime"])
    checked(Path(plan["checkpoint"]) / "training_manifest.json", plan["training_manifest"])
    checked(directory / "contexts.jsonl", plan["contexts"])
    require(sha256_file(Path(plan["topics_path"])) == plan["taxonomy_sha256"], "taxonomy changed")
    return plan


def predict_input_block(classifier, block, cache, batch_size):
    unique, resolved = {}, {}
    for row in block:
        text = input_text(row)
        if row["pre_inference_exclusion"]:
            result = prediction_record(classifier, text, [], [], 0)
            result.update(
                abstention_reason=row["pre_inference_exclusion"],
                n_input_tokens=None,
                n_discarded_tokens=None,
            )
            resolved[row["input_id"]] = result
            continue
        cached = cache.execute(
            "SELECT result FROM predictions WHERE input_sha256=?",
            (row["input_sha256"],),
        ).fetchone()
        if cached:
            result = json.loads(cached[0])
            require(
                result["input_sha256"] == row["input_sha256"]
                and result["model_run"] == classifier.run_id,
                "cached input/model",
            )
            expected = decide(
                json.loads(result["logits"]),
                classifier.output_codes,
                **classifier.manifest["decision"],
            )
            require(
                all(
                    result[key] == value
                    for key, value in asdict(expected).items()
                    if key != "scores"
                ),
                "cached decision does not match its complete logits",
            )
            require(
                json.loads(result["scores"]) == list(expected.scores)
                and json.loads(result["output_codes"]) == classifier.output_codes
                and result["n_discarded_tokens"] == 0
                and type(result["n_input_tokens"]) is int
                and result["n_input_tokens"] >= 0
                and len(json.loads(result["chunk_spans"])) == expected.n_chunks,
                "cached score/window coverage mismatch",
            )
            resolved[row["input_id"]] = result
        else:
            unique[row["input_sha256"]] = text
    fresh = dict(
        zip(
            unique,
            pooled_predictions(classifier, list(unique.values()), batch_size=batch_size),
            strict=True,
        )
    )
    for key, value in fresh.items():
        cache.execute(
            "INSERT INTO predictions VALUES (?,?)",
            (key, json.dumps(value, allow_nan=False)),
        )
    cache.commit()
    results = []
    for row in block:
        result = resolved.get(row["input_id"], fresh.get(row["input_sha256"]))
        require(result is not None, "missing exact input prediction")
        results.append(
            {
                **{
                    key: row[key]
                    for key in (
                        "input_id",
                        "view_id",
                        "bill_id",
                        "state",
                        "identifier",
                        "session_identifier",
                        "tier",
                        "source_path",
                        "source_row_ordinal",
                        "source_text_span",
                        "archive_machine_prologue_excluded_from_inference",
                    )
                },
                **result,
                **FLAGS,
            }
        )
    return results


def run(directory, *, tier, allow_provisional=False, batch_size=32):
    require(allow_provisional, "explicit --allow-provisional research use required")
    plan = checked_job(directory)
    require(tier in plan["tiers"], "tier absent from frozen plan")
    classifier = ModernBertClassifier(
        load_topics(plan["topics_path"]),
        Path(plan["checkpoint"]),
        allow_provisional=True,
        topics_path=plan["topics_path"],
    )
    require(
        classifier.run_id == plan["model_run"]
        and classifier.manifest["decision"] == plan["decision"],
        "frozen model/policy mismatch",
    )
    output = directory / "predictions"
    output.mkdir(exist_ok=True)
    progress_path = directory / f"progress-{tier}.json"
    progress = (
        read(progress_path)
        if progress_path.exists()
        else {
            "status": "running",
            "tier": tier,
            "model_run": plan["model_run"],
            "batch_size": batch_size,
            "inference_plan_sha256": sha256_file(directory / "inference_plan.json"),
            "token_count_scope": (
                "all_input_views_including_exact_cache_reuse_not_actual_encoder_work"
            ),
            "states": {},
            **FLAGS,
        }
    )
    require(
        progress["inference_plan_sha256"] == sha256_file(directory / "inference_plan.json"),
        "resume plan changed",
    )
    require(progress["batch_size"] == batch_size, "resume batch configuration changed")
    require(
        not progress["states"] or (directory / "prediction_cache.sqlite").is_file(),
        "missing persistent prediction cache on resume",
    )
    cache = sqlite3.connect(directory / "prediction_cache.sqlite")
    cache.execute(
        "CREATE TABLE IF NOT EXISTS predictions (input_sha256 TEXT PRIMARY KEY, result TEXT)"
    )
    started = time.monotonic()
    try:
        for name, entry in sorted(plan["inputs"].items()):
            if entry["tier"] != tier:
                continue
            source = directory / name
            checked(source, {key: entry[key] for key in ("sha256", "bytes")})
            state = entry["state"]
            destination = output / f"{tier}-{state}.jsonl"
            if state in progress["states"]:
                checked(destination, progress["states"][state]["artifact"])
                continue
            partial = destination.with_suffix(".jsonl.part")
            for previous in (partial, destination):
                if previous.exists():
                    serial = 1
                    while previous.with_name(previous.name + f".interrupted-{serial}").exists():
                        serial += 1
                    previous.rename(previous.with_name(previous.name + f".interrupted-{serial}"))
            count = tokens = chunks = exclusions = 0
            with partial.open("w") as handle:
                source_rows = (row for _, row in records(source))
                while block := list(islice(source_rows, 128)):
                    for result in predict_input_block(classifier, block, cache, batch_size):
                        write_row(handle, result)
                        count += 1
                        tokens += result["n_input_tokens"] or 0
                        chunks += result["n_chunks"]
                    exclusions += sum(row["pre_inference_exclusion"] is not None for row in block)
            require(count == entry["views"], "complete source-view output count")
            partial.replace(destination)
            progress["states"][state] = {
                "views": count,
                "source_tokens": tokens,
                "windows": chunks,
                "explicit_pre_inference_exclusions": exclusions,
                "artifact": binding(destination),
            }
            progress["elapsed_this_invocation_seconds"] = time.monotonic() - started
            write_json(progress_path, progress)
            print(
                json.dumps(
                    {
                        "tier": tier,
                        "state": state,
                        "views": count,
                        "tokens": tokens,
                        "states_done": len(progress["states"]),
                    }
                ),
                flush=True,
            )
        require(len(progress["states"]) == 50, "all fifty states required")
        progress["status"] = "complete_provisional_inference_not_scientific_validation"
        write_json(progress_path, progress)
    finally:
        cache.close()
    return progress


def collapse_bill_views(contexts, predictions):
    grouped = defaultdict(list)
    seen = set()
    for row in predictions:
        require(row["input_id"] not in seen, "duplicate predicted source view")
        seen.add(row["input_id"])
        grouped[row["bill_id"]].append(
            {key: row[key] for key in ("topic", "abstention_reason", "model_run")}
        )
    require(grouped.keys() <= {r["bill_id"] for r in contexts}, "prediction outside cohort")
    result = []
    for context in contexts:
        views = grouped[context["bill_id"]]
        topics = {row["topic"] for row in views}
        topic = next(iter(topics)) if len(topics) == 1 and None not in topics else None
        reason = (
            "no_supplied_retained_text"
            if not views
            else "source_alternative_disagreement"
            if len(topics) > 1
            else "all_source_views_abstained"
            if topic is None
            else None
        )
        result.append(
            {
                **context,
                "topic": topic,
                "inference_status": "unavailable"
                if not views
                else "classified"
                if topic is not None
                else "abstained",
                "abstention_reason": reason,
                "n_source_views": len(views),
                "view_abstention_reasons": json.dumps(
                    dict(Counter(r["abstention_reason"] for r in views if r["abstention_reason"]))
                ),
                "model_run": views[0]["model_run"] if views else None,
                **FLAGS,
            }
        )
    return result


def summarize(directory, tier):
    import pyarrow as pa
    import pyarrow.parquet as pq

    plan = checked_job(directory)
    progress = read(directory / f"progress-{tier}.json")
    require(
        progress["status"] == "complete_provisional_inference_not_scientific_validation",
        "inference incomplete; do not render a completed population",
    )
    require(len(progress["states"]) == 50, "missing state completion records")

    def predictions():
        count = 0
        for state, entry in sorted(progress["states"].items()):
            path = directory / f"predictions/{tier}-{state}.jsonl"
            checked(path, entry["artifact"])
            for _, row in records(path):
                count += 1
                yield row
        require(count == plan["n_views_by_tier"][tier], "complete prediction population")

    contexts = [r for _, r in records(directory / "contexts.jsonl")]
    assignments = collapse_bill_views(contexts, predictions())
    destination = directory / f"bill_assignments-{tier}.parquet"
    require(not destination.exists(), "do not overwrite an accepted inference summary")
    pq.write_table(pa.Table.from_pylist(assignments), destination)
    summary = {
        "tier": tier,
        "contexts": len(assignments),
        "source_views": plan["n_views_by_tier"][tier],
        "assignment_counts": dict(Counter(r["inference_status"] for r in assignments)),
        "topic_counts": dict(
            Counter(str(r["topic"]) for r in assignments if r["topic"] is not None)
        ),
        "assignments": binding(destination),
        **FLAGS,
    }
    write_json(directory / f"summary-{tier}.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--preview", type=Path, required=True)
    prepare.add_argument("--checkpoint", type=Path, required=True)
    prepare.add_argument("--out-dir", type=Path, required=True)
    prepare.add_argument("--tiers", nargs="+", choices=tuple(SOURCES), default=list(SOURCES))
    execute = sub.add_parser("run")
    execute.add_argument("--directory", type=Path, required=True)
    execute.add_argument("--tier", choices=tuple(SOURCES), required=True)
    execute.add_argument("--allow-provisional", action="store_true")
    execute.add_argument("--batch-size", type=int, default=32)
    report = sub.add_parser("summarize")
    report.add_argument("--directory", type=Path, required=True)
    report.add_argument("--tier", choices=tuple(SOURCES), required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        result = freeze(args.preview, args.checkpoint, args.out_dir, tiers=args.tiers)
    elif args.command == "run":
        result = run(
            args.directory.absolute(),
            tier=args.tier,
            allow_provisional=args.allow_provisional,
            batch_size=args.batch_size,
        )
    else:
        result = summarize(args.directory.absolute(), args.tier)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Census saved-label exposure; absence of a match does not establish independence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from scripts.audit_current_research import (  # noqa: E402
    binding,
    fingerprint,
    safe_path,
    strict_json,
)
from state_politics.analysis.cycle_topics import (  # noqa: E402
    FLAGS,
    checked_job,
    input_text,
    require,
)
from state_politics.bills.openstates_dump import STATE_CODES  # noqa: E402

STATES = sorted(state.upper() for state in STATE_CODES)
KINDS = ("exact_text", "normalized_text", "bill_identity")
LIMIT = 10 * 1024 * 1024


def normalized(text):
    return hashlib.sha256(re.sub(r"\W+", " ", text.casefold()).strip().encode()).hexdigest()


def audit(job, labels, output, plan_sha256):
    job, labels, output = (Path(path).absolute() for path in (job, labels, output))
    require(
        job.resolve() == job and labels.resolve() == labels
        and output.resolve() == output and output.parent.is_dir()
        and not output.exists() and not output.is_relative_to(job)
        and not output.is_relative_to(labels.parent),
        "fresh unlinked report directory outside the frozen job required",
    )
    snapshots, consumed = {}, {}

    def rows(path, expected):
        require(path.resolve() == path and path.is_file(), f"missing/linked input: {path}")
        before = fingerprint(path)
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as handle:
            for ordinal, raw in enumerate(handle, 1):
                digest.update(raw)
                size += len(raw)
                require(bool(raw.strip()), f"blank physical JSONL record: {path}:{ordinal}")
                value = strict_json(raw)
                require(isinstance(value, dict), f"JSONL object required: {path}:{ordinal}")
                yield ordinal, value
        actual = {"sha256": digest.hexdigest(), "bytes": size}
        require(actual == expected and fingerprint(path) == before, f"changed input: {path}")
        snapshots[path] = before
        consumed[str(path)] = actual

    plan_path = safe_path(job, job, "inference_plan.json")
    before = fingerprint(plan_path)
    plan_binding = binding(plan_path)
    require(plan_binding["sha256"] == plan_sha256, "external inference-plan pin mismatch")
    strict_json(plan_path.read_bytes())
    plan = checked_job(job)
    require(fingerprint(plan_path) == before, "inference plan changed while reading")
    snapshots[plan_path], consumed[str(plan_path)] = before, plan_binding
    producer = Path(checked_job.__code__.co_filename)
    for path, expected in (
        (producer, plan["producer"]),
        (producer.with_name("modernbert.py"), plan["frozen_inference_runtime"]),
    ):
        snapshots[path] = fingerprint(path)
        require(binding(path) == expected, f"frozen runtime changed: {path}")
        consumed[str(path)] = expected
    require(
        plan["tiers"] == ["retained_text"] and plan["n_contexts"] > 0,
        "complete retained-text population required",
    )
    model_path = Path(plan["checkpoint"]) / "training_manifest.json"
    require(not output.is_relative_to(model_path.parent), "report cannot mutate the model")
    before = fingerprint(model_path)
    training = strict_json(model_path.read_bytes())
    require(binding(model_path) == plan["training_manifest"], "training manifest changed")
    snapshots[model_path], consumed[str(model_path)] = before, plan["training_manifest"]
    require(plan["model_run"] == plan["training_manifest"]["sha256"], "model identity mismatch")
    label_binding = {"sha256": training["labels_sha256"], "bytes": labels.stat().st_size}
    references, index, split_counts = {}, defaultdict(set), Counter()
    for ordinal, row in rows(labels, label_binding):
        identity = row.get("record_id")
        require(
            isinstance(identity, str) and identity and identity not in references
            and row.get("split") in {"train", "dev", "test", "challenge"}
            and row.get("domain") in {"bill", "plank"}
            and isinstance(row.get("group_id"), str) and bool(row["group_id"])
            and isinstance(row.get("text"), str) and bool(row["text"].strip()),
            f"invalid/duplicate saved reference: {identity}",
        )
        sha = hashlib.sha256(row["text"].encode()).hexdigest()
        require(row.get("text_sha256", sha) == sha, f"changed reference text: {identity}")
        references[identity] = ordinal
        split_counts[row["split"]] += 1
        if row["domain"] == "bill":
            split = row["split"]
            index[split, "exact_text", sha].add(identity)
            index[split, "normalized_text", normalized(row["text"])].add(identity)
            if row["group_id"].startswith("ocd-bill/"):
                index[split, "bill_identity", row["group_id"]].add(identity)
    require(dict(split_counts) == training["split_counts"], "saved label split counts changed")
    splits = sorted(split_counts)
    states = {state: Counter(state=state) for state in STATES}
    contexts, context_matches, seen_views = {}, defaultdict(dict), set()
    for _, row in rows(job / "contexts.jsonl", plan["contexts"]):
        identity, state = row["bill_id"], row["state"]
        require(
            isinstance(identity, str) and identity.startswith("ocd-bill/")
            and identity not in contexts and state in states,
            f"duplicate/foreign context: {identity}",
        )
        contexts[identity] = state
        states[state]["n_contexts"] += 1
        for split in splits:
            ids = index.get((split, "bill_identity", identity), ())
            if ids:
                context_matches[identity][split, "bill_identity"] = set(ids)
    require(len(contexts) == plan["n_contexts"], "incomplete context population")
    inputs = plan["inputs"]
    require(
        set(inputs) == {f"inputs/retained_text-{state}.jsonl" for state in STATES},
        "exactly all 50 retained-text partitions required",
    )
    output.mkdir()
    matched_views = output / "matched_views.jsonl"
    total_views = report_bytes = 0
    body_contexts = set()
    with matched_views.open("x") as handle:
        for name, expected in sorted(inputs.items()):
            state = expected["state"]
            require(
                expected["tier"] == "retained_text" and state in states
                and name == f"inputs/retained_text-{state}.jsonl",
                "partition identity mismatch",
            )
            count = 0
            path = safe_path(job, job, name)
            for ordinal, row in rows(path, {key: expected[key] for key in ("sha256", "bytes")}):
                identity, view = row["bill_id"], row["input_id"]
                require(
                    row["state"] == state and contexts.get(identity) == state
                    and row["tier"] == "retained_text" and row["domain"] == "bill"
                    and isinstance(row["view_id"], str)
                    and view == f"retained_text:{row['view_id']}"
                    and view not in seen_views
                    and all(row.get(flag) is False for flag in FLAGS),
                    f"foreign, duplicate or promoted source view: {view}",
                )
                text = input_text(row)
                require(bool(text.strip()), f"empty retained body: {view}")
                seen_views.add(view)
                body_contexts.add(identity)
                count += 1
                states[state]["n_views"] += 1
                states[state]["n_pre_excluded_views"] += row["pre_inference_exclusion"] is not None
                keys = {
                    "exact_text": row["input_sha256"],
                    "normalized_text": normalized(text),
                    "bill_identity": identity,
                }
                matches = {}
                for split in splits:
                    found = {}
                    for kind, key in keys.items():
                        ids = index.get((split, kind, key), ())
                        if ids:
                            found[kind] = sorted(ids)
                            states[state][f"{split}_{kind}_views"] += 1
                            context_matches[identity].setdefault((split, kind), set()).update(ids)
                    if found:
                        matches[split] = found
                        states[state][f"{split}_any_match_views"] += 1
                if matches:
                    value = {
                        "input_file": name, "physical_record": ordinal,
                        **{key: row[key] for key in (
                            "input_id", "view_id", "bill_id", "state", "input_sha256",
                            "pre_inference_exclusion",
                        )},
                        "matches": matches,
                    }
                    raw = json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n"
                    report_bytes += len(raw.encode())
                    require(report_bytes < LIMIT // 2, "matched-view report exceeds bounded budget")
                    handle.write(raw)
            require(count == expected["views"], f"partition view count changed: {state}")
            total_views += count
    require(total_views == plan["n_views_by_tier"]["retained_text"], "incomplete view population")
    context_rows = []
    for identity, state in contexts.items():
        has_body = identity in body_contexts
        states[state]["n_contexts_with_body"] += has_body
        states[state]["n_body_gaps"] += not has_body
        found = context_matches.get(identity, {})
        for split in splits:
            if any(owner == split for owner, _ in found):
                states[state][f"{split}_any_match_contexts"] += 1
            for kind in KINDS:
                states[state][f"{split}_{kind}_contexts"] += bool(found.get((split, kind)))
        if found:
            context_rows.append({
                "bill_id": identity, "state": state, "body_available": has_body,
                "matches": {
                    f"{split}:{kind}": sorted(ids) for (split, kind), ids in sorted(found.items())
                },
            })
    with (output / "matched_contexts.jsonl").open("x") as handle:
        for row in sorted(context_rows, key=lambda row: row["bill_id"]):
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    fields = ["state", "n_contexts", "n_contexts_with_body", "n_body_gaps",
              "n_views", "n_pre_excluded_views"]
    for split in splits:
        for unit in ("contexts", "views"):
            fields += [f"{split}_{kind}_{unit}" for kind in (*KINDS, "any_match")]
    with (output / "state_counts.csv").open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: states[state].get(key, 0) for key in fields} for state in STATES)
    for path, before in snapshots.items():
        require(path.resolve() == path and fingerprint(path) == before, f"input raced: {path}")
    result = {
        "schema": "state-politics.training-exposure-census.v1",
        "status": "complete_saved_label_exposure_census_not_independent_validation",
        "definitions": {
            "exact_text": "Same domain and exact complete selected input text.",
            "normalized_text": "Same domain after casefold/nonword normalization; includes exact.",
            "bill_identity": "Same stable OCD bill ID; does not establish same input or version.",
            "no_match": "No match to these saved labels; NOT independently held out.",
            "channels": "Overlapping channels: do not add them. All alternatives retained.",
            "exclusions": "Views include explicit pre-inference exclusions; not all were encoded.",
            "scope": (
                "Saved model train/dev/test/challenge labels only, not all consumed diagnostics."
            ),
            "ledgers": (
                "Complete matched-only joins, not replacements for full source/query exports."
            ),
        },
        "training_split_counts": dict(split_counts),
        "reference_physical_records": references,
        "counts": {key: sum(states[state].get(key, 0) for state in STATES) for key in fields[1:]},
        "states_accounted_for": len(states),
        "inputs": consumed,
        "producer": binding(Path(__file__)),
        "integrity_helper": binding(ROOT / "scripts/audit_current_research.py"),
        "artifacts": {
            name: binding(output / name)
            for name in ("matched_views.jsonl", "matched_contexts.jsonl", "state_counts.csv")
        },
        **FLAGS,
        "independent_human_validation": False,
        "model_execution": False,
        "model_promotion": False,
        "project_complete": False,
    }
    raw = json.dumps(result, indent=2, allow_nan=False) + "\n"
    require(
        sum(path.stat().st_size for path in output.iterdir()) + len(raw.encode()) < LIMIT,
        "report exceeds 10 MiB budget",
    )
    with (output / "manifest.json").open("x") as handle:
        handle.write(raw)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.job, args.labels, args.out, args.plan_sha256)
        print(json.dumps({"status": result["status"], "counts": result["counts"]}, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

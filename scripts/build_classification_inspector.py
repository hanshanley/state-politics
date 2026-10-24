#!/usr/bin/env python3
"""Build a local, full-source original/majority decision inspector without inference."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.analysis.cycle_topics import (  # noqa: E402
    FLAGS,
    binding,
    checked,
    checked_job,
    input_text,
    read,
    require,
    source_text,
)
from state_politics.analysis.taxonomy import load_topics  # noqa: E402
from state_politics.bills.openstates_dump import STATE_CODES  # noqa: E402

SCHEMA = "state-politics.classification-inspector.v1"
ASTRAL = re.compile("[\U00010000-\U0010ffff]")
ARCHIVE = "research-data/complete_inference_and_majority_candidate.zip"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def rows_with_ranges(path, name):
    with path.open("rb") as stream:
        offset = 0
        for raw in stream:
            require(raw.endswith(b"\n") and bool(raw.strip()), "complete physical JSONL required")
            yield (
                json.loads(raw),
                {
                    "path": name,
                    "offset": offset,
                    "length": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                },
            )
            offset += len(raw)


def unicode_spans(text, span):
    positions = [match.start() for match in ASTRAL.finditer(text)]
    selected = [point - span[0] for point in positions if span[0] <= point < span[1]]
    return [point + bisect_left(positions, point) for point in span], selected


def safe_name(name):
    return (
        bool(name)
        and not name.startswith("/")
        and "\\" not in name
        and all(part not in {"", ".", ".."} for part in name.split("/"))
        and PurePosixPath(name).as_posix() == name
    )


def build(job, majority, majority_sha256, output):
    job, majority, output = (path.absolute() for path in (job, majority, output))
    require(
        output.resolve() == output
        and not output.exists()
        and any(output.is_relative_to(ROOT / name) for name in ("data", "outputs")),
        "fresh unlinked project output required",
    )
    require(
        binding(majority / "manifest.json")["sha256"] == majority_sha256,
        "majority external manifest pin changed",
    )
    manifest = read(majority / "manifest.json")
    require(
        all(manifest.get(flag) is False for flag in FLAGS)
        and manifest["independent_human_validation"] is False,
        "unapproved research candidate required",
    )
    codes = manifest["output_codes"]
    require(
        len(codes) == 22
        and codes[-1] is None
        and all(type(code) is int for code in codes[:-1])
        and len(set(codes)) == 22,
        "complete 21-topic plus rejection map required",
    )
    plan = checked_job(job)
    for name, expected in manifest["artifacts"].items():
        require(safe_name(name), "unsafe candidate artifact")
        checked(majority / name, expected)
    for name, expected in manifest["source_inference_inputs"].items():
        require(safe_name(name), "unsafe original inference artifact")
        checked(job / name, expected)
    output.mkdir(parents=True)

    def copy(source, name):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        require(binding(source) == binding(target), f"copied complete evidence changed: {name}")

    for name in (
        "classification-inspector.html",
        "classification-inspector.css",
        "classification-inspector.js",
    ):
        copy(ROOT / "web" / name, "index.html" if name.endswith(".html") else name)
    copy(Path(__file__), "producers/build_classification_inspector.py")
    copy(ROOT / "scripts/serve_research.py", "producers/serve_research.py")
    copy(Path(plan["topics_path"]), "taxonomy.yml")
    copy(majority / "manifest.json", "evidence/majority_manifest.json")
    copy(job / "inference_plan.json", "evidence/inference_plan.json")
    for name in ("context_assignments.jsonl", "source_decisions.jsonl"):
        copy(majority / "decisions" / name, "evidence/" + name)
    copy(majority / ARCHIVE, ARCHIVE)

    inputs = {}
    for name in sorted(manifest["source_inference_inputs"]):
        if not name.startswith("inputs/"):
            continue
        target = "evidence/job/" + name
        copy(job / name, target)
        for row, reference in rows_with_ranges(output / target, target):
            require(row["input_id"] not in inputs, "duplicate original input")
            require(all(row.get(flag) is False for flag in FLAGS), "input approval changed")
            text = input_text(row)
            utf16_span, astral = unicode_spans(
                source_text(row["original_source_view"]), row["source_text_span"]
            )
            inputs[row["input_id"]] = {
                "input_id": row["input_id"],
                "bill_id": row["bill_id"],
                "state": row["state"],
                "input": reference,
                "input_sha256": row["input_sha256"],
                "characters": len(text),
                "utf16_span": utf16_span,
                "astral_offsets": astral,
            }
    by_bill, predictions = defaultdict(list), set()
    source_name = "evidence/source_decisions.jsonl"
    for row, reference in rows_with_ranges(output / source_name, source_name):
        key = row["input_id"]
        require(key in inputs and key not in predictions, "missing/duplicate source prediction")
        item = inputs[key]
        require(
            row["bill_id"] == item["bill_id"]
            and row["state"] == item["state"]
            and row["input_sha256"] == item["input_sha256"]
            and all(row.get(flag) is False for flag in FLAGS)
            and json.loads(row["output_codes"]) == codes,
            "source prediction identity, scores or approval changed",
        )
        item["prediction"] = reference
        by_bill[row["bill_id"]].append(item)
        predictions.add(key)
    require(
        len(predictions) == len(inputs) == manifest["original_source_views"],
        "not every complete original source view has a prediction",
    )
    states = {state.upper(): [] for state in STATE_CODES}
    counts, baseline, seen = Counter(), Counter(), set()
    context_name = "evidence/context_assignments.jsonl"
    for row, reference in rows_with_ranges(output / context_name, context_name):
        key, state, candidate = row["bill_id"], row["state"], row["majority_candidate"]
        require(key not in seen and state in states, "duplicate/unknown context")
        require(all(row.get(flag) is False for flag in FLAGS), "context approval changed")
        require(
            candidate["status"]
            in {
                "classified",
                "model_rejected",
                "uncertain",
                "excluded",
                "unavailable",
            },
            "unknown candidate status",
        )
        sources = by_bill.get(key, [])
        require(len(sources) == row["n_source_views"], "context/source count changed")
        require(all(source["state"] == state for source in sources), "wrong source state")
        require(
            row["topic"] is None or row["topic"] == candidate["topic"],
            "original accepted topic was changed",
        )
        states[state].append(
            {
                "bill_id": key,
                "state": state,
                "identifier": row["identifier"],
                "title": row["title"],
                "session": row["session_identifier"],
                "baseline_topic": row["topic"],
                "baseline_status": row["inference_status"],
                "baseline_reason": row["abstention_reason"],
                "candidate_topic": candidate["topic"],
                "candidate_status": candidate["status"],
                "candidate_reason": candidate["reason"],
                "source_disagreement": candidate.get("source_disagreement_or_uncertainty"),
                "window_disagreement": candidate.get("window_disagreement_present"),
                "context": reference,
                "sources": sources,
            }
        )
        counts[candidate["status"]] += 1
        baseline[row["inference_status"]] += 1
        seen.add(key)
    require(set(by_bill) <= seen, "source view is orphaned from original contexts")
    require(
        len(seen) == manifest["original_contexts"]
        and dict(counts) == manifest["candidate_status_counts"],
        "population counts changed",
    )
    topics = load_topics(Path(plan["topics_path"]))
    topic_rows = [
        {"code": topic.code, "name": topic.name, "description": topic.description}
        for topic in topics
    ]
    require([row["code"] for row in topic_rows] == codes[:-1], "taxonomy/output order changed")
    state_rows = []
    for state, rows in states.items():
        rows.sort(key=lambda item: (item["identifier"], item["bill_id"]))
        save(output / "states" / f"{state}.json", {"state": state, "records": rows})
        state_rows.append(
            {
                "state": state,
                "contexts": len(rows),
                "path": f"states/{state}.json",
                **binding(output / "states" / f"{state}.json"),
            }
        )
        cells = "".join(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(value))}</td>"
                for value in (
                    row["identifier"],
                    row["title"],
                    row["baseline_status"],
                    row["baseline_topic"] if row["baseline_topic"] is not None else "Unassigned",
                    row["candidate_status"],
                    row["candidate_topic"] if row["candidate_topic"] is not None else "Unassigned",
                    len(row["sources"]),
                )
            )
            + "</tr>"
            for row in rows
        )
        (output / "states" / f"{state}.html").write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{state} classification records</title>"
            '<link rel="stylesheet" href="../classification-inspector.css">'
            f"<main><h1>{state}: complete candidate table</h1>"
            "<p>Unpublished, unvalidated model outputs. Unassigned is not zero policy activity. "
            "An empty candidate frame does not establish zero legislative activity.</p>"
            '<p><a href="../index.html">Interactive inspector</a> · '
            f'<a download href="../{ARCHIVE}">Complete sources and predictions (ZIP)</a> · '
            f'<a download href="{state}.json">Complete index and source byte references</a></p>'
            '<div class="scroll"><table><thead><tr><th>Measure</th><th>Title</th>'
            "<th>Original status</th><th>Original topic</th><th>Majority status</th>"
            "<th>Majority topic</th><th>Source views</th></tr></thead>"
            f"<tbody>{cells}</tbody></table></div></main></html>"
        )
    save(
        output / "config.json",
        {
            "schema": SCHEMA,
            "states": state_rows,
            "topics": topic_rows,
            "output_codes": codes,
            "contexts": len(seen),
            "source_views": len(inputs),
            "candidate_counts": dict(counts),
            "baseline_counts": dict(baseline),
            "majority_policy": manifest["policy"],
            "majority_policy_run": manifest["policy_run"],
            "decision": plan["decision"],
            "complete_source_archive": ARCHIVE,
        },
    )
    index = (output / "index.html").read_text()
    links = "".join(
        f'<li><a href="states/{state}.html">{state} complete table</a></li>' for state in states
    )
    require("@@STATE_TABLES@@" in index, "missing no-JavaScript state fallback")
    (output / "index.html").write_text(index.replace("@@STATE_TABLES@@", links))
    for name, expected in manifest["artifacts"].items():
        checked(majority / name, expected)
    for name, expected in manifest["source_inference_inputs"].items():
        checked(job / name, expected)
    result = {
        "schema": SCHEMA,
        "status": "complete_local_inspector_not_validated_findings",
        "scientific_certification": "not_performed",
        "model_execution": False,
        "model_promotion": False,
        "publication": False,
        **dict.fromkeys(FLAGS, False),
        "original_contexts": len(seen),
        "original_source_views": len(inputs),
        "candidate_status_counts": dict(counts),
        "original_status_counts": dict(baseline),
        "original_majority_manifest": binding(majority / "manifest.json"),
        "original_job": str(job),
        "copied_complete_source_archive": binding(output / ARCHIVE),
        "query_downloads": "complete_raw_context_input_and_prediction_records_not_metadata_only",
        "raw_integers_and_physical_JSONL_preserved": True,
        "artifacts": {
            str(path.relative_to(output)): binding(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    save(output / "manifest.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--majority-gallery", type=Path, required=True)
    parser.add_argument("--majority-sha256", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.job, args.majority_gallery, args.majority_sha256, args.out_dir)
    print(json.dumps({key: value for key, value in result.items() if key != "artifacts"}, indent=2))


if __name__ == "__main__":
    main()

"""Plan complete metadata token windows locally, without loading encoder weights."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ..bills.study_window import _snapshot
from ..provenance import utc_now_iso
from .modernbert import model_input_ids, policy_tokens, section_windows

POLICY_MANIFEST_SHA256 = "21520fcde171e9bc1026c6a3dce790f0f381a31cb35262c67db01b55be35d7c4"
_STATUS = "complete_unlabelled_metadata_token_plan_not_inference_or_admission"
_LISTS = [
    "token_ids",
    "token_offset_starts",
    "token_offset_ends",
    "window_token_starts",
    "window_token_ends",
    "window_character_starts",
    "window_character_ends",
    "window_model_input_lengths",
]


def plan_view(tokenizer, view: dict, *, budget: int, overlap: int) -> dict:
    """Bound each model window while covering every token from the full original string."""
    text = view["text"]
    if (
        not isinstance(text, str)
        or hashlib.sha256(text.encode()).hexdigest() != view["input_sha256"]
    ):
        raise ValueError("metadata input text/hash mismatch")
    prefix, _ = policy_tokens(tokenizer, "", "bill")
    overhead = len(model_input_ids(tokenizer, prefix))
    source_budget = budget - overhead
    encoded = tokenizer(
        text,
        add_special_tokens=False,
        return_offsets_mapping=True,
        truncation=False,
    )
    tokens, offsets = encoded["input_ids"], encoded["offset_mapping"]
    if (
        len(tokens) != len(offsets)
        or any(type(token) is not int or token < 0 for token in tokens)
        or any(not 0 <= start < end <= len(text) for start, end in offsets)
        or any(left[0] > right[0] for left, right in zip(offsets[:-1], offsets[1:], strict=True))
    ):
        raise ValueError("invalid full-source token offsets")
    windows = section_windows(text, offsets, source_budget, overlap)
    covered = end = 0
    for left, right in windows:
        if not 0 <= left <= end < right <= len(tokens) or right - left > source_budget:
            raise ValueError("token windows must cover the source without gaps")
        covered += right - end
        end = right
    if covered != len(tokens):
        raise ValueError("source tokens were discarded")
    lengths = [right - left + overhead for left, right in windows]
    if any(length > budget for length in lengths):
        raise ValueError("planned input exceeds the frozen model token budget")
    return {
        "view_id": view["view_id"],
        "bill_id": view["bill_id"],
        "input_sha256": view["input_sha256"],
        "n_input_characters": len(text),
        "n_input_tokens": len(tokens),
        "n_windows": len(windows),
        "n_unique_covered_tokens": covered,
        "n_overlap_token_positions": sum(right - left for left, right in windows) - covered,
        "n_discarded_tokens": len(tokens) - covered,
        "token_ids": tokens,
        "token_offset_starts": [a for a, _ in offsets],
        "token_offset_ends": [b for _, b in offsets],
        "window_token_starts": [a for a, _ in windows],
        "window_token_ends": [b for _, b in windows],
        "window_character_starts": [offsets[a][0] for a, _ in windows],
        "window_character_ends": [offsets[b - 1][1] for _, b in windows],
        "window_model_input_lengths": lengths,
        "model_input_approved": False,
        "analytical_admission": False,
    }


def build_plan(evidence_dir: Path, policy_dir: Path, out_dir: Path) -> dict:
    if out_dir.exists():
        raise FileExistsError(out_dir)
    paths = {
        "evidence_manifest": evidence_dir / "manifest.json",
        "views": evidence_dir / "candidate_metadata_views.parquet",
        "policy_manifest": policy_dir / "manifest.json",
        "policy_report": policy_dir / "report.json",
        "tokenizer": policy_dir / "tokenizer.json",
        "tokenizer_config": policy_dir / "tokenizer_config.json",
        "config": policy_dir / "config.json",
        "producer": Path(__file__),
        "modernbert": Path(__file__).with_name("modernbert.py"),
        "study_window": Path(__file__).parent.parent / "bills/study_window.py",
        "provenance": Path(__file__).parent.parent / "provenance.py",
    }
    before = {key: _snapshot(path) for key, path in paths.items()}
    evidence = json.loads(paths["evidence_manifest"].read_text(encoding="utf-8"))
    policy_manifest = json.loads(paths["policy_manifest"].read_text(encoding="utf-8"))
    policy = json.loads(paths["policy_report"].read_text(encoding="utf-8"))
    if (
        evidence["status"]
        != "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted"
        or evidence["artifacts"]["candidate_metadata_views.parquet"]["sha256"]
        != before["views"]["sha256"]
    ):
        raise ValueError("completed checksum-bound metadata views required")
    if before["policy_manifest"]["sha256"] != POLICY_MANIFEST_SHA256:
        raise ValueError("the accepted tokenizer-policy manifest is required")
    for key in ("policy_report", "tokenizer", "tokenizer_config", "config"):
        if policy_manifest["files"][paths[key].name] != before[key]["sha256"]:
            raise ValueError(f"{key}: tokenizer policy checksum mismatch")
    if (
        policy["tokenizer_model_id"] != "answerdotai/ModernBERT-base"
        or policy["tokenizer_base_revision"] != "8949b909ec900327062f0ebf497f51aef5e6f0c8"
        or type(policy["model_token_budget"]) is not int
        or type(policy["overlap_tokens"]) is not int
    ):
        raise ValueError("official revision-pinned ModernBERT policy required")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        policy_dir,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    prefix, _ = policy_tokens(tokenizer, "", "bill")
    overhead = len(model_input_ids(tokenizer, prefix))
    if policy["source_token_budget"] != policy["model_token_budget"] - overhead:
        raise ValueError("tokenizer marker/wrapper disagrees with frozen source budget")
    # Validate the window policy even when the source has no token-bearing views.
    section_windows("", [], policy["source_token_budget"], policy["overlap_tokens"])
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = out_dir / "manifest.json"
    manifest = {
        "schema_version": 1,
        "status": "incomplete",
        "started_at": utc_now_iso(),
        "inputs": before,
        "model_inference_performed": False,
        "model_input_approved": False,
        "analytical_admission": False,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    schema = pa.schema(
        [
            *[(name, pa.string()) for name in ("view_id", "bill_id", "input_sha256")],
            *[
                (name, pa.int64())
                for name in (
                    "n_input_characters",
                    "n_input_tokens",
                    "n_windows",
                    "n_unique_covered_tokens",
                    "n_overlap_token_positions",
                    "n_discarded_tokens",
                )
            ],
            *[(name, pa.list_(pa.int64())) for name in _LISTS],
            ("model_input_approved", pa.bool_()),
            ("analytical_admission", pa.bool_()),
        ]
    )
    totals = {"n_views": 0, "n_input_tokens": 0, "n_windows": 0, "n_multichunk_views": 0}
    seen = set()
    maximum = None
    with pq.ParquetWriter(out_dir / "token_window_plan.parquet", schema) as writer:
        for batch in pq.ParquetFile(paths["views"]).iter_batches(
            batch_size=256,
            columns=["view_id", "bill_id", "text", "input_sha256"],
        ):
            rows = []
            for view in batch.to_pylist():
                if not view["view_id"] or view["view_id"] in seen or not view["bill_id"]:
                    raise ValueError("unique view IDs and nonempty bill IDs required")
                seen.add(view["view_id"])
                row = plan_view(
                    tokenizer,
                    view,
                    budget=policy["model_token_budget"],
                    overlap=policy["overlap_tokens"],
                )
                rows.append(row)
                totals["n_views"] += 1
                totals["n_input_tokens"] += row["n_input_tokens"]
                totals["n_windows"] += row["n_windows"]
                totals["n_multichunk_views"] += int(row["n_windows"] > 1)
                if maximum is None or row["n_input_tokens"] > maximum["n_input_tokens"]:
                    maximum = {k: row[k] for k in ("view_id", "n_input_tokens", "n_windows")}
            writer.write_table(pa.Table.from_pylist(rows, schema=schema))
    result = {
        "status": _STATUS,
        **totals,
        "maximum_view": maximum,
        "tokenizer_model_id": policy["tokenizer_model_id"],
        "tokenizer_base_revision": policy["tokenizer_base_revision"],
        "model_token_budget": policy["model_token_budget"],
        "source_token_budget": policy["source_token_budget"],
        "overlap_tokens": policy["overlap_tokens"],
        "domain_marker_token_ids": prefix,
        "wrapper_token_ids": model_input_ids(tokenizer, []),
        "n_discarded_tokens": 0,
        "model_forward_passes": 0,
        "model_input_approved": False,
        "analytical_admission": False,
        "limitations": [
            "Token coverage is not accuracy, legal/version alignment or filing-time eligibility.",
            "All full source strings remain in the bound metadata evidence packet.",
            "Every tokenizer-produced source token is covered; no character-level semantic claim.",
            "Source tests, drafts and ambiguous summaries remain marked in original evidence.",
            "No encoder weights, calibration, predictions or training labels are loaded.",
        ],
    }
    (out_dir / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if {key: _snapshot(path) for key, path in paths.items()} != before:
        raise ValueError("token-plan inputs changed; output remains incomplete")
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
    for name in ("evidence-dir", "policy-dir", "out-dir"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build_plan(args.evidence_dir, args.policy_dir, args.out_dir), indent=2))


if __name__ == "__main__":
    main()

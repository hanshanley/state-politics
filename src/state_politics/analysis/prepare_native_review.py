"""Freeze complete retained native texts for blind review, without models or collection."""

from __future__ import annotations

import argparse
import gzip
import json
import shlex
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .prepare_cycle_review import (
    FALSE_FLAGS,
    RESERVATIONS,
    STATES,
    TAXONOMY,
    Reservation,
    assemble,
    assemble_decisions,
    assert_binding,
    binding,
    canonical,
    digest,
    fingerprint,
    read_frozen_plan,
    read_jsonl,
    reservation_paths,
    validate_review_plan,
    write_json,
    write_jsonl,
    write_review_batches,
)
from .taxonomy import load_topics
from .train_topics import load_examples

SEED = "cycle-native-complete-input-review-v1"
LIMITATIONS = (
    "Blind complete retained-native-text review, not human/independent gold or legal "
    "identity, original-stage, filing-time or analytical certification. Only the exact "
    "chosen input is semantic evidence. Full alternative readers/references survive; "
    "they are not extra bills. Length-bounded, state-balanced diagnostic selection is "
    "not population sampling. No source is truncated and no model is consulted."
)


def view_key(row: dict) -> str:
    return canonical([row["packet_root"], row["view_id"]])


def validate_native(row: dict, state: str) -> None:
    if row.get("source_type") != "native_text" or row.get("state") != state:
        raise ValueError("native source/state mismatch")
    for field in ("packet_root", "view_id", "bill_id", "context_id", "input_sha256"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ValueError(f"missing native identity: {field}")
    text = row.get("text")
    if (
        not isinstance(text, str) or digest(text) != row["input_sha256"]
        or type(row.get("n_input_characters")) is not int
        or len(text) != row["n_input_characters"]
    ):
        raise ValueError("native complete text/hash/length mismatch")
    for flag in (*FALSE_FLAGS, "native_identity_certified"):
        if row.get(flag) is not False:
            raise ValueError("native approvals must remain false")
    bill = row.get("bill_context")
    native = row.get("native_context")
    if not isinstance(bill, dict) or not isinstance(native, dict):
        raise ValueError("native original contexts required")
    for field in ("bill_id", "state", "identifier", "session_identifier"):
        if row.get(field) != bill.get(field) or row.get(field) != native.get(field):
            raise ValueError(f"native/bill context mismatch: {field}")
    for flag in ("source_test_record", "source_draft_request"):
        if type(bill.get(flag)) is not bool:
            raise ValueError("native source exclusions require explicit booleans")
    for flag in ("model_input_approved", "filing_time_text_certified", "analytical_admission"):
        if bill.get(flag) is not False:
            raise ValueError("original bill approvals must remain false")


def sample_state(
    records: list[dict], reservation: Reservation, *, state: str, seed: str,
    per_state: int, max_characters: int,
) -> tuple[list[dict], dict]:
    if type(per_state) is not int or per_state < 1:
        raise ValueError("per_state must be a positive integer")
    if type(max_characters) is not int or max_characters < 1:
        raise ValueError("max_characters must be a positive integer")
    groups = defaultdict(list)
    seen = set()
    for row in records:
        validate_native(row, state)
        key = view_key(row)
        if key in seen:
            raise ValueError("duplicate namespaced native view")
        seen.add(key)
        groups[row["bill_id"]].append(row)

    def rank(kind, value):
        return digest(canonical([seed, kind, value])), value

    pool = []
    source_excluded = length_excluded = empty_excluded = 0
    for bill_id, alternatives in groups.items():
        bill = alternatives[0]["bill_context"]
        if any(row["bill_context"] != bill for row in alternatives):
            raise ValueError("native alternatives disagree on original bill context")
        if bill["source_test_record"] or bill["source_draft_request"]:
            source_excluded += 1
            continue
        nonempty = [row for row in alternatives if row["text"].strip()]
        usable = [row for row in nonempty if len(row["text"]) <= max_characters]
        if not usable:
            length_excluded += bool(nonempty)
            empty_excluded += not nonempty
            continue
        chosen = min(usable, key=lambda row: rank("view", view_key(row)))
        stratum = "up_to_2000_characters" if len(chosen["text"]) <= 2000 else "longer_complete"
        pool.append((bill_id, stratum, chosen))
    pool.sort(key=lambda item: rank("bill", item[0]))
    selected, checked, excluded = [], set(), []

    def take(candidates, quota):
        for bill_id, stratum, chosen in candidates:
            if not quota or len(selected) == per_state:
                break
            if bill_id in checked:
                continue
            checked.add(bill_id)
            alternatives = groups[bill_id]
            reason = next(
                (reason for row in alternatives if (reason := reservation.overlap(row))), None,
            )
            if reason:
                excluded.append({"bill_id": bill_id, "reason": reason})
                continue
            selected.append({
                "record_id": f"cycle-native-review-v1:{digest(view_key(chosen))}",
                "group_id": bill_id, "bill_id": bill_id, "state": state, "stratum": stratum,
                "view_id": view_key(chosen), "input_sha256": chosen["input_sha256"],
                "text": chosen["text"], "input_basis": "retained_native_text",
                "document_text_sha256": chosen["input_sha256"],
                "review_label_version": SEED, "original_view": chosen,
                "original_bill_evidence": chosen["bill_context"],
                "source_view_sha256": digest(canonical(chosen)),
                "source_bill_evidence_sha256": digest(canonical(chosen["bill_context"])),
                "alternative_view_ids": sorted(view_key(row) for row in alternatives),
                "field_lineage": {
                    "text": {"source": f"downloads/native-{state}.jsonl.gz", "field": "text",
                             "utf8_sha256": chosen["input_sha256"]},
                },
            })
            for row in alternatives:
                reservation.add(row)
            quota -= 1

    for stratum, quota in (
        ("up_to_2000_characters", (per_state + 1) // 2),
        ("longer_complete", per_state // 2),
    ):
        take((row for row in pool if row[1] == stratum), quota)
    take(pool, per_state - len(selected))
    return selected, {
        "retained_native_views": len(records), "distinct_native_candidate_bills": len(groups),
        "excluded_test_or_draft_bills": source_excluded,
        "excluded_all_views_over_character_limit": length_excluded,
        "excluded_all_views_empty": empty_excluded,
        "length_eligible_bills": len(pool), "examined_reservation_exclusions": excluded,
        "selected": len(selected), "deficit_to_per_state_limit": per_state - len(selected),
        "selected_strata": dict(Counter(row["stratum"] for row in selected)),
        "status": "sampled" if selected else "no_eligible_native_input_not_zero_activity",
    }


def freeze_native(
    preview: Path, output: Path, *, reservations=RESERVATIONS, reservation_inputs=(),
    taxonomy: Path = TAXONOMY, seed: str = SEED, per_state: int = 2,
    max_characters: int = 12000, review_split: str = "challenge",
    quarantine_rubric_ambiguity: bool = False,
) -> dict:
    validate_review_plan(review_split, per_state, quarantine_rubric_ambiguity)
    if type(max_characters) is not int or max_characters < 1:
        raise ValueError("max_characters must be a positive integer")
    if output.exists():
        raise FileExistsError(f"refusing overwrite: {output}")
    manifest_path = preview / "downloads/build_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if (
        manifest.get("schema") != "local_cycle_evidence_preview_v1"
        or manifest.get("publication_status") != "local_only_unpublished"
        or any(manifest.get(flag) is not False for flag in (
            "model_input_approved", "analytical_admission",
        ))
        or "native_evidence" not in manifest.get("inputs", {})
    ):
        raise ValueError("completed unapproved native evidence export required")
    parts = [preview / f"downloads/native-{state}.jsonl.gz" for state in STATES]
    sources = [manifest_path, *parts, taxonomy, *reservations, *reservation_inputs]
    before = [fingerprint(path) for path in sources]
    codes = [topic.code for topic in load_topics(taxonomy)]
    reserved = []
    for path in reservations:
        reserved.extend(load_examples(path, codes))
    for path in reservation_inputs:
        for row in read_jsonl(path):
            if (
                not isinstance(row.get("text"), str)
                or digest(row["text"]) != row.get("input_sha256")
            ):
                raise ValueError("reservation input text/hash mismatch")
            reserved.append(row)
    reserve = Reservation(reserved)
    selected, alternatives, accounting = [], [], {}
    total_views = total_bills = 0
    for state, path in zip(STATES, parts, strict=True):
        relative = path.relative_to(preview).as_posix()
        assert_binding(path, manifest["outputs"][relative])
        with gzip.open(path, "rb") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        chosen, counts = sample_state(
            records, reserve, state=state, seed=seed, per_state=per_state,
            max_characters=max_characters,
        )
        picked = {row["bill_id"] for row in chosen}
        alternatives.extend(row for row in records if row["bill_id"] in picked)
        selected.extend(chosen)
        accounting[state] = counts
        total_views += counts["retained_native_views"]
        total_bills += counts["distinct_native_candidate_bills"]
    if (
        total_views != manifest["counts"]["native_full_text_candidate_views"]
        or total_bills != manifest["counts"]["native_full_text_candidate_contexts"]
    ):
        raise ValueError("complete native export counts mismatch")
    for number, row in enumerate(selected, 1):
        row["review_number"] = number
        row["review_split"] = review_split
    if [fingerprint(path) for path in sources] != before:
        raise ValueError("sources changed during native review freeze")
    output.mkdir(parents=True)
    write_jsonl(output / "review_packet.jsonl", selected)
    write_jsonl(output / "selected_alternative_views.jsonl", alternatives)
    plan = {
        "review_split": review_split, "per_state": per_state,
        "quarantine_rubric_ambiguity": quarantine_rubric_ambiguity,
        "input_basis": "retained_native_text", "max_characters": max_characters,
        "seed": seed, "limitations": LIMITATIONS,
    }
    write_json(output / "review_plan.json", plan)
    write_json(output / "sampling_manifest.json", {
        **plan, "states": accounting, "n_selected": len(selected),
        "native_views_accounted_for": total_views, "native_bills_accounted_for": total_bills,
        "selection": "seeded hash within complete-source character strata, never truncation",
        "reservation_use": "source identity and exact/near full-input text only, not labels",
        "all_selected_bill_alternatives": binding(output / "selected_alternative_views.jsonl"),
    })
    shutil.copyfile(taxonomy, output / "topics.yml")
    shutil.copyfile(manifest_path, output / "original_packet_manifest.json")
    shutil.copyfile(Path(__file__), output / "producer.py")
    (output / "review_inputs.txt").write_text(LIMITATIONS + "\n\n" + "".join(
        f"===== {row['review_number']:03d} {row['state']} {row['record_id']} =====\n"
        f"INPUT SHA256: {row['input_sha256']}\nFULL INPUT START\n{row['text']}"
        "\nFULL INPUT END\n\n" for row in selected
    ), encoding="utf-8")
    batches = write_review_batches(output, selected, review_split)
    names = (
        "review_packet.jsonl", "selected_alternative_views.jsonl", "review_plan.json",
        "sampling_manifest.json", "topics.yml", "original_packet_manifest.json",
        "producer.py", "review_inputs.txt", *batches,
    )
    frozen = {
        "schema_version": 1, "status": "frozen_inputs_before_semantic_decisions",
        **plan, "n_selected": len(selected),
        "reservation_paths": [str(Path(path).resolve()) for path in reservations],
        "reservation_input_paths": [str(Path(path).resolve()) for path in reservation_inputs],
        "sources_before": before, "sources_after": before, "sources_unchanged": True,
        "frozen_artifacts": {name: binding(output / name) for name in names},
        "freeze_command": (
            f"{shlex.quote(sys.executable)} -I -B"
            " -m state_politics.analysis.prepare_native_review"
            f" --preview {shlex.quote(str(preview))} --output {shlex.quote(str(output))}"
            f" --per-state {per_state} --max-characters {max_characters}"
            f" --seed {shlex.quote(seed)} --review-split {review_split}"
            + (" --quarantine-rubric-ambiguity" if quarantine_rubric_ambiguity else "")
            + "".join(f" --reserve-labels {shlex.quote(str(path))}" for path in reservations
                      if Path(path).resolve() not in {p.resolve() for p in RESERVATIONS})
            + "".join(f" --reserve-inputs {shlex.quote(str(path))}"
                      for path in reservation_inputs)
        ),
    }
    write_json(output / "source_manifest.json", frozen)
    return frozen


def compare_reviews(packet: list[dict], first: list[dict], second: list[dict],
                    codes: list[int], **plan) -> tuple[list[dict], dict]:
    for decisions in (first, second):
        assemble_decisions(packet, decisions, codes, **plan)
    a, b = ({row["record_id"]: row for row in rows} for rows in (first, second))
    merged, agreed, disputed = [], [], []
    for original in packet:
        key = original["record_id"]
        left, right = a[key], b[key]
        if left["reviewer_id"] == right["reviewer_id"]:
            raise ValueError("independent reviews require distinct reviewer identities")

        def verdict(row):
            return row["topic"], row["abstention_reason"] if row["topic"] is None else None

        agreement = verdict(left) == verdict(right)
        (agreed if agreement else disputed).append(key)
        merged.append({
            **left, "topic": left["topic"] if agreement else None,
            "abstention_reason": verdict(left)[1] if agreement else "rubric_ambiguity",
            "reviewer_id": f"{left['reviewer_id']} & {right['reviewer_id']}",
            "rationale": (
                f"Two independent assistant executions {'agree' if agreement else 'disagree'}; "
                "not independent human gold. "
                f"A ({verdict(left)}): {left['rationale']} "
                f"B ({verdict(right)}): {right['rationale']}"
            ),
            "evidence_spans": list(dict.fromkeys(left["evidence_spans"] + right["evidence_spans"])),
        })
    return merged, {
        "n_reviewed_by_each": len(packet), "n_agreed": len(agreed), "n_disputed": len(disputed),
        "agreement_fraction": len(agreed) / len(packet) if packet else None,
        "agreed_record_ids": agreed, "disputed_record_ids": disputed,
        "all_original_reviews": {"a": first, "b": second},
        "disagreement_policy": "no winner; unresolved sensitivity only, exclude from primary score",
        "independent_human_gold": False, "analytical_admission": False,
    }


def compare_files(output: Path, first: Path, second: Path) -> dict:
    names = ("consensus_decisions.jsonl", "review_agreement.json", "review_consensus_manifest.json")
    if any((output / name).exists() for name in (*names, "labels.jsonl")):
        raise FileExistsError("refusing overwrite of review comparison")
    frozen = json.loads((output / "source_manifest.json").read_bytes())
    plan = read_frozen_plan(output, frozen)
    codes = [topic.code for topic in load_topics(output / "topics.yml")]
    paths = [first, second, output / "source_manifest.json", output / "review_packet.jsonl"]
    before = [fingerprint(path) for path in paths]
    decisions, comparison = compare_reviews(
        read_jsonl(output / "review_packet.jsonl"), read_jsonl(first), read_jsonl(second), codes,
        review_split=plan["review_split"],
        quarantine_rubric_ambiguity=plan["quarantine_rubric_ambiguity"],
    )
    write_jsonl(output / names[0], decisions)
    write_json(output / names[1], comparison)
    assemble(output, output / names[0])
    if before != [fingerprint(path) for path in paths]:
        raise ValueError("original reviews or packet changed during comparison")
    write_json(output / names[2], {
        "status": "validated_independent_assistant_agreement_not_human_gold",
        "inputs_before": before, "inputs_after": before,
        "comparison_producer": binding(Path(__file__)),
        "artifacts": {name: binding(output / name) for name in (
            *names[:2], "labels.jsonl", "validation_receipt.json",
        )},
    })
    return comparison


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("freeze", "compare"), default="freeze")
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-state", type=int, default=2)
    parser.add_argument("--max-characters", type=int, default=12000)
    parser.add_argument("--seed", default=SEED)
    parser.add_argument("--review-split", choices=("challenge", "train"), default="challenge")
    parser.add_argument("--quarantine-rubric-ambiguity", action="store_true")
    parser.add_argument("--reserve-labels", type=Path, action="append", default=[])
    parser.add_argument("--reserve-inputs", type=Path, action="append", default=[])
    parser.add_argument("--review-a", type=Path)
    parser.add_argument("--review-b", type=Path)
    args = parser.parse_args()
    if args.action == "compare":
        if args.review_a is None or args.review_b is None:
            parser.error("compare requires both --review-a and --review-b")
        result = compare_files(args.output, args.review_a, args.review_b)
        print(json.dumps({key: result[key] for key in ("n_reviewed_by_each", "n_agreed")}))
        return
    if args.preview is None or args.review_a is not None or args.review_b is not None:
        parser.error("freeze requires --preview and cannot consume review decisions")
    result = freeze_native(
        args.preview, args.output, reservations=reservation_paths(args.reserve_labels),
        reservation_inputs=args.reserve_inputs, per_state=args.per_state,
        max_characters=args.max_characters, seed=args.seed, review_split=args.review_split,
        quarantine_rubric_ambiguity=args.quarantine_rubric_ambiguity,
    )
    print(json.dumps({key: result[key] for key in ("status", "n_selected")}))


if __name__ == "__main__":
    main()

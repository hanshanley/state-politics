"""Freeze blind review inputs and assemble advisory labels; never run a model.

Run ``python -m state_politics.analysis.prepare_cycle_review freeze`` first. Read
every complete input in ``review_inputs.txt`` against the frozen taxonomy, then
write one explicit decision per input and run ``assemble --decisions PATH``.
Only the frozen metadata input is review evidence, not linked/native documents.
``freeze --per-state 12 --review-split train --quarantine-rubric-ambiguity``
plans experimental training review, not canonical training admission. Repeat
``--reserve-labels PATH`` to extend, never replace, the default reservations.
Use a distinct ``--output``. Roles and ambiguity disposition are frozen before
decisions, not assembly options.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from ..bills.openstates_dump import STATE_CODES
from ..provenance import sha256_file
from .prepare_topics import _shingles, near_overlap, normalized_text
from .taxonomy import load_topics
from .train_topics import load_examples, validate_split_isolation

PACKET = Path("data/processed/study-abstract-evidence-2023-2024-v2")
OUTPUT = Path("data/labels/cycle-metadata-blind-review-20261021-v1")
RESERVATIONS = (
    Path("data/labels/republican-platform-curriculum-v1/labels.jsonl"),
    Path("data/labels/cap-conflict-exclusion-experiment-20261021-v1/labels.jsonl"),
    Path("data/labels/source-disjoint-platform-challenge-v1/challenge_labels.jsonl"),
)
TAXONOMY = Path("conf/topics.yml")
SEED = "cycle-metadata-blind-review-20261021-v1"
STATUS = "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted"
STATES = tuple(sorted(state.upper() for state in STATE_CODES))
ABSTENTIONS = {"non_policy", "mixed_policy", "insufficient_evidence", "rubric_ambiguity"}
FALSE_FLAGS = (
    "model_input_approved", "filing_time_text_certified", "training_admission",
    "analytical_admission",
)
LIMITATIONS = (
    "BLIND ASSISTANT diagnostic labels, not human or independent gold. "
    "No population accuracy, filing-time validity, primary-source completeness, "
    "science certification or publication authorization is established. "
    "All original metadata approval flags remain false; challenge only, never training."
)
TRAIN_LIMITATIONS = (
    "BLIND ASSISTANT research-training review, advisory and experimental only, "
    "not human or independent gold and not canonical training admission. "
    "No population accuracy, filing-time validity, primary-source completeness, "
    "science certification or publication authorization is established. "
    "All original metadata/source approval flags remain false. "
    "Rubric-ambiguity decisions retain their original reason and full input in quarantine, "
    "never a fabricated topic or remapped training rejection."
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": str(path.resolve()), "sha256": sha256_file(path), "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino, "mode": stat.st_mode,
    }


def binding(path: Path) -> dict:
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def assert_binding(path: Path, expected: dict) -> None:
    if binding(path) != {key: expected[key] for key in ("sha256", "bytes")}:
        raise ValueError(f"frozen artifact mismatch: {path}")


def validate_review_plan(
    review_split: str, per_state: int, quarantine_rubric_ambiguity: bool,
) -> None:
    if review_split not in ("challenge", "train"):
        raise ValueError("review_split must be challenge or train")
    if type(per_state) is not int or per_state < 1:
        raise ValueError("per_state must be a positive integer")
    if type(quarantine_rubric_ambiguity) is not bool:
        raise ValueError("quarantine option must be boolean")
    if review_split == "train" and not quarantine_rubric_ambiguity:
        raise ValueError("train review requires explicit quarantine-rubric-ambiguity")
    if review_split == "challenge" and quarantine_rubric_ambiguity:
        raise ValueError("quarantine-rubric-ambiguity is only for train review")


def reservation_paths(extras=()) -> tuple[Path, ...]:
    """CLI extensions cannot remove any of the canonical default reservations."""
    paths = {}
    for path in (*RESERVATIONS, *extras):
        path = Path(path)
        paths.setdefault(path.resolve(), path)
    return tuple(paths.values())


class Reservation:
    """Text and identity reservation only; labels/scores never enter selection."""

    def __init__(self, rows=()):
        self.identities: set[str] = set()
        self.exact: set[str] = set()
        self.signatures: dict[int, list[set[tuple[str, ...]]]] = defaultdict(list)
        for row in rows:
            self.add(row)

    def add(self, row: dict) -> None:
        for field in ("record_id", "group_id", "bill_id", "view_id"):
            if isinstance(row.get(field), str):
                self.identities.add(row[field])
        text = row["text"]
        normalized = normalized_text(text)
        if normalized not in self.exact:
            self.exact.add(normalized)
            signature = _shingles(text)
            if signature:
                self.signatures[len(signature)].append(signature)

    def overlap(self, row: dict) -> str | None:
        if any(
            row.get(key) in self.identities
            for key in ("record_id", "group_id", "bill_id", "view_id")
            if isinstance(row.get(key), str)
        ):
            return "reserved_identity"
        # Check complete inputs AND their source fields; do not reuse a reserved
        # abstract by merely prepending a new title.
        texts = {
            row[key] for key in ("text", "title", "abstract")
            if isinstance(row.get(key), str) and normalized_text(row[key])
        }
        for text in texts:
            if normalized_text(text) in self.exact:
                return "reserved_exact_text"
            size = len(_shingles(text))
            if not size:
                continue
            references = [
                signature
                for length, signatures in self.signatures.items()
                if min(length, size) / max(length, size) >= 0.8
                for signature in signatures
            ]
            if near_overlap(text, references):
                return "reserved_near_text"
        return None


def sample_views(
    views: list[dict], bills: list[dict], reservation: Reservation, *,
    states=STATES, seed=SEED, per_state: int = 4,
) -> tuple[list[dict], dict]:
    """Balance abstract/title strata up to per_state, then stable fill.

    All alternative views of a considered context are checked for reservations.
    One complete view per context is chosen solely by a seeded SHA256 ordering.
    Reservation exclusions are counted for examined contexts, not extrapolated to
    the unexamined population. Default four preserves the original two-plus-two
    selection. For odd limits the abstract stratum gets the extra preferred slot.
    """
    if type(per_state) is not int or per_state < 1:
        raise ValueError("per_state must be a positive integer")
    by_bill = {}
    for bill in bills:
        key = bill["bill_id"]
        if key in by_bill:
            raise ValueError("duplicate bill_id")
        if bill["state"] not in states:
            raise ValueError("unknown state")
        by_bill[key] = bill
    grouped = defaultdict(list)
    seen_views = set()
    for view in views:
        if view["view_id"] in seen_views:
            raise ValueError("duplicate view_id")
        seen_views.add(view["view_id"])
        bill = by_bill.get(view["bill_id"])
        if bill is None:
            raise ValueError("view missing bill evidence")
        for key in ("state", "identifier", "session_identifier", "title", "cohort_scope"):
            if view[key] != bill[key]:
                raise ValueError(f"view/bill identity mismatch: {key}")
        for flag in FALSE_FLAGS:
            if flag in view and view[flag] is not False:
                raise ValueError("original approval flag must remain false")
            if flag in bill and bill[flag] is not False:
                raise ValueError("original bill approval flag must remain false")
        if digest(view["text"]) != view["input_sha256"]:
            raise ValueError("source input hash mismatch")
        if len(view["text"]) != view["n_input_characters"]:
            raise ValueError("source character count mismatch")
        grouped[view["bill_id"]].append(view)
    if set(grouped) != set(by_bill):
        raise ValueError("bill evidence and views must have exact context coverage")

    def rank(kind: str, value: str) -> tuple[str, str]:
        return digest(canonical([seed, kind, value])), value

    by_state = defaultdict(list)
    excluded_source = Counter()
    for bill_id, alternatives in grouped.items():
        bill = by_bill[bill_id]
        if bill["source_test_record"] or bill["source_draft_request"]:
            excluded_source[bill["state"]] += 1
            continue
        usable = [
            view for view in alternatives
            if view["input_status"] in {
                "unreviewed_metadata_candidate", "procedural_title_without_summary",
            } and normalized_text(view["text"])
        ]
        if not usable:
            continue
        chosen = min(usable, key=lambda row: rank("view", row["view_id"]))
        stratum = "abstract_containing" if chosen.get("abstract") else "title_only"
        by_state[bill["state"]].append((bill_id, stratum, chosen))
    selected = []
    accounting = {}
    exclusions = []
    for state in states:
        pool = sorted(by_state[state], key=lambda item: rank("context", item[0]))
        picked = []
        checked = set()

        def take(candidates, quota, *, picked=picked, checked=checked, state=state):
            for bill_id, stratum, chosen in candidates:
                if len(picked) >= per_state or quota <= 0:
                    break
                if bill_id in checked:
                    continue
                checked.add(bill_id)
                reason = next(
                    (reason for alt in grouped[bill_id]
                     if (reason := reservation.overlap(alt))),
                    None,
                )
                if reason:
                    exclusions.append({"state": state, "bill_id": bill_id, "reason": reason})
                    continue
                item = {
                    "record_id": f"cycle-blind-v1:{chosen['view_id']}",
                    "group_id": bill_id, "state": state, "stratum": stratum,
                    "view_id": chosen["view_id"], "input_sha256": chosen["input_sha256"],
                    "text": chosen["text"], "original_view": chosen,
                    "original_bill_evidence": by_bill[bill_id],
                    "source_view_sha256": digest(canonical(chosen)),
                    "source_bill_evidence_sha256": digest(canonical(by_bill[bill_id])),
                    "alternative_view_ids": sorted(row["view_id"] for row in grouped[bill_id]),
                    "field_lineage": {
                        field: {
                            "source": "candidate_metadata_views.parquet", "field": field,
                            "utf8_sha256": digest(chosen[field])
                            if isinstance(chosen.get(field), str) else None,
                        }
                        for field in ("text", "title", "abstract", "abstract_note", "input_fields")
                    },
                }
                picked.append(item)
                reservation.add({**chosen, "record_id": item["record_id"], "group_id": bill_id})
                quota -= 1

        for stratum, quota in (
            ("abstract_containing", (per_state + 1) // 2), ("title_only", per_state // 2),
        ):
            take((row for row in pool if row[1] == stratum), quota)
        take(pool, per_state - len(picked))
        selected.extend(picked)
        accounting[state] = {
            "candidate_contexts": sum(bill["state"] == state for bill in bills),
            "non_test_non_draft_nonempty_contexts": len(pool),
            "pool_strata": dict(Counter(row[1] for row in pool)),
            "excluded_test_or_draft_contexts": excluded_source[state],
            "reservation_checked_contexts": len(checked),
            "selected": len(picked),
            "deficit_to_per_state_limit": per_state - len(picked),
            "actual_selected_strata": dict(Counter(row["stratum"] for row in picked)),
            "status": "sampled" if picked else "no_eligible_candidate_not_zero_activity",
        }
    for number, item in enumerate(selected, 1):
        item["review_number"] = number
    return selected, {"states": accounting, "examined_context_exclusions": exclusions}


def write_review_batches(output: Path, selected: list[dict], review_split: str) -> list[str]:
    names = []
    for offset, batch_id in enumerate(("a", "b")):
        names.append(f"review_batch_{batch_id}_indices.json")
        entries = [
            {
                "source_line_1based": index + 1, "review_number": row["review_number"],
                "record_id": row["record_id"], "state": row["state"],
                "input_sha256": row["input_sha256"],
            }
            for index, row in enumerate(selected) if index % 2 == offset
        ]
        write_json(output / names[-1], {
            "batch_id": batch_id, "review_split": review_split, "n_inputs": len(entries),
            "source_file": "review_packet.jsonl",
            "source_file_binding": binding(output / "review_packet.jsonl"),
            "index_basis": "one-based JSONL lines, disjoint alternating indices",
            "instructions": (
                "Read every assigned complete text from the bound source file and frozen "
                "taxonomy before authoring decisions. Do not infer linked context or consult "
                "model outputs. Merge both complete decision batches before assembly."
            ),
            "indices": entries,
        })
    return names


def freeze(
    packet: Path = PACKET, output: Path = OUTPUT, *,
    reservations=RESERVATIONS, taxonomy: Path = TAXONOMY, seed: str = SEED,
    per_state: int = 4, review_split: str = "challenge",
    quarantine_rubric_ambiguity: bool = False,
) -> dict:
    validate_review_plan(review_split, per_state, quarantine_rubric_ambiguity)
    if output.exists():
        raise FileExistsError(f"refusing overwrite: {output}")
    manifest_path = packet / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if (
        manifest.get("status") != STATUS or manifest.get("inputs_unchanged") is not True
        or manifest.get("model_input_approved") is not False
        or manifest.get("analytical_admission") is not False
    ):
        raise ValueError("source manifest status/approval mismatch")
    artifacts = ("candidate_metadata_views.parquet", "bill_evidence.parquet", "state_matrix.csv")
    sources = [manifest_path, *[packet / name for name in artifacts], taxonomy, *reservations]
    before = [fingerprint(path) for path in sources]
    for name in artifacts:
        assert_binding(packet / name, manifest["artifacts"][name])
    topics = load_topics(taxonomy)
    codes = [topic.code for topic in topics]
    reserved_rows = []
    reservation_counts = {}
    for path in reservations:
        loaded = load_examples(path, codes)
        reservation_counts[str(path)] = len(loaded)
        # Immediately discard all labels and other non-reservation fields.
        reserved_rows.extend(
            {key: row[key] for key in ("record_id", "group_id", "text")} for row in loaded
        )
    views = json.loads(pd.read_parquet(packet / artifacts[0]).to_json(orient="records"))
    bills = json.loads(pd.read_parquet(packet / artifacts[1]).to_json(orient="records"))
    selected, accounting = sample_views(
        views, bills, Reservation(reserved_rows), seed=seed, per_state=per_state,
    )
    for row in selected:
        row["review_split"] = review_split
        if review_split == "train":
            row["record_id"] = f"cycle-training-review-v1:{row['view_id']}"
    matrix = json.loads(pd.read_csv(packet / artifacts[2]).to_json(orient="records"))
    if set(row["state"] for row in matrix) != set(STATES) or len(matrix) != 50:
        raise ValueError("source matrix must account for exactly all 50 states")
    for row in matrix:
        accounting["states"][row["state"]]["n_retained_contexts_wider_history"] = row[
            "n_retained_contexts_wider_history"
        ]
        accounting["states"][row["state"]]["original_state_matrix"] = row
    after = [fingerprint(path) for path in sources]
    if before != after:
        raise ValueError("sources changed during freeze")
    limitations = LIMITATIONS if review_split == "challenge" else TRAIN_LIMITATIONS
    plan = {
        "review_split": review_split, "per_state": per_state,
        "quarantine_rubric_ambiguity": quarantine_rubric_ambiguity,
        "reservation_paths": [str(Path(path).resolve()) for path in reservations],
        "seed": seed, "limitations": limitations,
    }
    output.mkdir(parents=True, exist_ok=False)
    write_jsonl(output / "review_packet.jsonl", selected)
    write_json(output / "review_plan.json", plan)
    batch_names = write_review_batches(output, selected, review_split)
    shutil.copyfile(taxonomy, output / "topics.yml")
    shutil.copyfile(manifest_path, output / "original_packet_manifest.json")
    shutil.copyfile(Path(__file__), output / "producer.py")
    (output / "review_inputs.txt").write_text(
        limitations + "\n\n" + "".join(
            f"===== {row['review_number']:03d} {row['state']} {row['view_id']} =====\n"
            f"INPUT SHA256: {row['input_sha256']}\n"
            f"STRATUM: {row['stratum']}\n"
            f"FULL INPUT START\n{row['text']}\nFULL INPUT END\n\n"
            for row in selected
        ), encoding="utf-8",
    )
    sampling = {
        "seed": seed, "ordering": "SHA256(canonical JSON [seed, kind, identifier])",
        "design": (
            f"{(per_state + 1) // 2} abstract-containing plus {per_state // 2} title-only "
            "when available; stable fill"
        ),
        "view_selection": "stable seeded hash, never longest/latest/truncated",
        "context_limit_per_state": per_state, "n_selected": len(selected),
        "review_split": review_split, "quarantine_rubric_ambiguity": quarantine_rubric_ambiguity,
        "state_count": len(STATES), "reservation_file_rows": reservation_counts,
        "reservation_unique_normalized_texts": len({normalized_text(r["text"])
                                                   for r in reserved_rows}),
        "reservation_use": "text/record/group evidence only; no labels used for selection",
        "exclusion_scope": "all alternative views of each considered context",
        "near_overlap": "existing 3-word-shingle size-ratio >=0.8 and Jaccard >=0.8",
        "all_unselected_alternatives": "preserved unchanged in bound original parquet bundle",
        **accounting, "limitations": limitations,
    }
    write_json(output / "sampling_manifest.json", sampling)
    frozen_names = (
        "review_packet.jsonl", "review_inputs.txt", "topics.yml",
        "original_packet_manifest.json", "producer.py", "sampling_manifest.json",
        "review_plan.json", *batch_names,
    )
    frozen = {
        "schema_version": 1, "status": "frozen_inputs_before_semantic_decisions",
        "prepared_on": "2026-10-21", "n_selected": len(selected),
        **plan,
        "sources_before": before, "sources_after": after,
        "sources_unchanged": True,
        "frozen_artifacts": {name: binding(output / name) for name in frozen_names},
        "freeze_command": (
            f"{shlex.quote(sys.executable)} -m state_politics.analysis.prepare_cycle_review freeze"
            f" --packet {shlex.quote(str(packet))} --output {shlex.quote(str(output))}"
            f" --seed {shlex.quote(seed)} --per-state {per_state} --review-split {review_split}"
            + (" --quarantine-rubric-ambiguity" if quarantine_rubric_ambiguity else "")
            + "".join(f" --reserve-labels {shlex.quote(str(path))}" for path in reservations
                      if Path(path).resolve() not in {p.resolve() for p in RESERVATIONS})
        ),
    }
    write_json(output / "source_manifest.json", frozen)
    return frozen


def assemble_decisions(
    packet: list[dict], decisions: list[dict], codes: list[int], *,
    review_split: str = "challenge", quarantine_rubric_ambiguity: bool = False,
) -> list[dict]:
    validate_review_plan(review_split, 4, quarantine_rubric_ambiguity)
    if any(row.get("review_split", "challenge") != review_split for row in packet):
        raise ValueError("cannot change the frozen review_split")
    expected = {row["record_id"]: row for row in packet}
    if len(expected) != len(packet):
        raise ValueError("duplicate frozen record")
    received = [row.get("record_id") for row in decisions]
    if len(received) != len(set(received)):
        raise ValueError("duplicate decisions")
    if set(received) != set(expected):
        raise ValueError("missing/extra decisions")
    by_id = {row["record_id"]: row for row in decisions}
    labels = []
    for original in packet:
        decision = by_id[original["record_id"]]
        allowed = {
            "record_id", "input_sha256", "topic", "abstention_reason", "reviewer_id",
            "reviewer_type", "reviewed_on", "input_reviewed_in_full",
            "input_only_no_external_context", "rationale", "evidence_spans",
        }
        if set(decision) - allowed:
            raise ValueError("unexpected decision fields cannot replace frozen inputs")
        text = original["text"]
        if (
            digest(text) != original["input_sha256"]
            or decision.get("input_sha256") != original["input_sha256"]
        ):
            raise ValueError("wrong input hash")
        topic = decision.get("topic")
        if "topic" not in decision or (
            topic is not None and (type(topic) is not int or topic not in codes)
        ):
            raise ValueError("invalid topic")
        if topic is None:
            if decision.get("abstention_reason") not in ABSTENTIONS:
                raise ValueError("explicit valid abstention required")
        elif decision.get("abstention_reason") not in (None, ""):
            raise ValueError("topic and abstention conflict")
        if (
            not isinstance(decision.get("reviewer_id"), str)
            or not decision["reviewer_id"].strip()
            or decision.get("reviewer_type") != "assistant"
            or decision.get("reviewed_on") != "2026-10-21"
            or decision.get("input_reviewed_in_full") is not True
            or decision.get("input_only_no_external_context") is not True
            or not isinstance(decision.get("rationale"), str)
            or len(decision["rationale"].strip()) < 20
        ):
            raise ValueError("insufficient review provenance")
        spans = decision.get("evidence_spans")
        if (
            not isinstance(spans, list) or not spans
            or any(not isinstance(span, str) or not span.strip() or span not in text
                   for span in spans)
        ):
            raise ValueError("evidence spans must be exact nonempty input substrings")
        labels.append({
            **original, **decision, "text_sha256": original["input_sha256"],
            "split": review_split, "domain": "bill", "label_origin": "reviewed_target",
            "label_version": SEED if review_split == "challenge"
            else "cycle-metadata-research-training-review-v1",
            "evidence_tier": "blind_assistant_input_diagnostic" if review_split == "challenge"
            else "blind_assistant_research_training_advisory",
            "source_url": (
                f"urn:state-politics:cycle-metadata:sha256:{original['input_sha256']}"
                f":view:{original['view_id']}"
            ),
            "source_sha256": original["source_view_sha256"],
            "review_status": "blind_assistant_not_human_or_independent_gold"
            if review_split == "challenge"
            else "research_training_advisory_not_canonical_or_independent_gold",
            **({"research_training_advisory": True, "canonical_gold": False}
               if review_split == "train" else {}),
            "independent_gold": False, "human_gold": False,
            **dict.fromkeys(FALSE_FLAGS, False),
        })
    return labels


def read_frozen_plan(output: Path, frozen: dict) -> dict:
    plan = {
        "review_split": frozen.get("review_split", "challenge"),
        "per_state": frozen.get("per_state", 4),
        "quarantine_rubric_ambiguity": frozen.get("quarantine_rubric_ambiguity", False),
    }
    validate_review_plan(**plan)
    if "review_plan.json" in frozen["frozen_artifacts"]:
        recorded = json.loads((output / "review_plan.json").read_text())
        if any(recorded.get(key) != value for key, value in plan.items()):
            raise ValueError("frozen review plan mismatch")
    elif plan != {
        "review_split": "challenge", "per_state": 4, "quarantine_rubric_ambiguity": False,
    }:
        raise ValueError("legacy challenge packet cannot change review role or limit")
    return plan


def assemble(output: Path, decisions_path: Path) -> dict:
    if any((output / name).exists() for name in (
        "labels.jsonl", "validation_receipt.json", "quarantined_units.jsonl",
    )):
        raise FileExistsError("refusing overwrite of assembled labels/receipt")
    source_manifest = output / "source_manifest.json"
    manifest_binding = binding(source_manifest)
    frozen = json.loads(source_manifest.read_text())
    for name, expected in frozen["frozen_artifacts"].items():
        assert_binding(output / name, expected)
    plan = read_frozen_plan(output, frozen)
    source_paths = [Path(row["path"]) for row in frozen["sources_before"]]
    if [fingerprint(path) for path in source_paths] != frozen["sources_before"]:
        raise ValueError("source fingerprints changed since freeze")
    packet = [
        json.loads(line) for line in (output / "review_packet.jsonl").read_text().splitlines()
    ]
    decisions_binding = binding(decisions_path)
    decisions = [
        json.loads(line) for line in decisions_path.read_text().splitlines() if line.strip()
    ]
    codes = [topic.code for topic in load_topics(output / "topics.yml")]
    reviewed = assemble_decisions(
        packet, decisions, codes, review_split=plan["review_split"],
        quarantine_rubric_ambiguity=plan["quarantine_rubric_ambiguity"],
    )
    quarantined = [
        {**row, "quarantined": True, "quarantine_reason": "rubric_ambiguity"}
        for row in reviewed
        if plan["review_split"] == "train" and row.get("abstention_reason") == "rubric_ambiguity"
    ]
    quarantined_ids = {row["record_id"] for row in quarantined}
    labels = [row for row in reviewed if row["record_id"] not in quarantined_ids]
    destination = output / "semantic_decisions.jsonl"
    if decisions_path.resolve() != destination.resolve():
        if destination.exists():
            raise FileExistsError("refusing overwrite of semantic decisions")
        shutil.copyfile(decisions_path, destination)
    assert_binding(destination, decisions_binding)
    write_jsonl(output / "labels.jsonl", labels)
    if plan["review_split"] == "train":
        write_jsonl(output / "quarantined_units.jsonl", quarantined)
    validated = load_examples(output / "labels.jsonl", codes) if labels else []
    reserved = []
    reserved_paths = frozen.get("reservation_paths", [
        str(path) for path in source_paths
        if path.name in ("labels.jsonl", "challenge_labels.jsonl")
    ])
    for path in source_paths:
        if str(path) in reserved_paths:
            reserved.extend(load_examples(path, codes))
    validate_split_isolation([*reserved, *validated])
    # Repeat the text/identity reservation check, independent of sampler state.
    reservation = Reservation(reserved)
    for row in reviewed:
        if reason := reservation.overlap(row["original_view"]):
            raise ValueError(f"assembled reservation collision: {reason}")
        reservation.add(row)
    after = [fingerprint(path) for path in source_paths]
    if after != frozen["sources_before"]:
        raise ValueError("sources changed during assembly")
    assert_binding(source_manifest, manifest_binding)
    assert_binding(decisions_path, decisions_binding)
    receipt = {
        "status": "validated_blind_assistant_diagnostic_not_gold"
        if plan["review_split"] == "challenge" else "research_training_advisory_review_not_gold",
        "n_labels": len(validated), "n_selected": frozen["n_selected"],
        "n_reviewed": len(reviewed), "n_quarantined": len(quarantined), **plan,
        "load_examples_status": "passed" if labels else "no_emitted_labels_all_quarantined",
        "n_decisions": len(decisions), "state_count_accounted_for": 50,
        "topic_counts": dict(Counter(str(row["topic"]) for row in validated)),
        "abstention_counts": dict(Counter(
            row["abstention_reason"] for row in validated if row["topic"] is None
        )),
        "commands": [
            frozen["freeze_command"],
            f"{shlex.quote(sys.executable)}"
            " -m state_politics.analysis.prepare_cycle_review assemble"
            f" --output {shlex.quote(str(output))} --decisions {shlex.quote(str(decisions_path))}",
            "load_examples(labels.jsonl, frozen_taxonomy_codes)",
            "validate_split_isolation(reservation_rows + assembled_labels)",
            "Reservation.overlap(all assembled original views)",
        ],
        "sources_before": frozen["sources_before"], "sources_after": after,
        "sources_unchanged": True, "source_manifest": manifest_binding,
        "artifacts": {
            **frozen["frozen_artifacts"],
            "semantic_decisions.jsonl": binding(destination),
            "labels.jsonl": binding(output / "labels.jsonl"),
            **({"quarantined_units.jsonl": binding(output / "quarantined_units.jsonl")}
               if plan["review_split"] == "train" else {}),
        },
        "limitations": frozen["limitations"],
        **dict.fromkeys(FALSE_FLAGS, False),
    }
    write_json(output / "validation_receipt.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "assemble"))
    parser.add_argument("--packet", type=Path, default=PACKET)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--seed", default=SEED)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--per-state", type=int, help="freeze-only context limit (default: 4)")
    parser.add_argument("--review-split", choices=("challenge", "train"),
                        help="freeze-only planned review role (default: challenge)")
    parser.add_argument("--quarantine-rubric-ambiguity", action="store_true",
                        help="required for train freeze; preserve ambiguity units in quarantine")
    parser.add_argument("--reserve-labels", type=Path, action="append", default=[],
                        help="freeze-only reservation extension; all defaults are always retained")
    args = parser.parse_args()
    if args.action == "freeze":
        result = freeze(
            args.packet, args.output, seed=args.seed, reservations=reservation_paths(
                args.reserve_labels,
            ), per_state=args.per_state if args.per_state is not None else 4,
            review_split=args.review_split or "challenge",
            quarantine_rubric_ambiguity=args.quarantine_rubric_ambiguity,
        )
    else:
        if (
            args.per_state is not None or args.review_split is not None
            or args.quarantine_rubric_ambiguity or args.reserve_labels
        ):
            parser.error("review role, limit, quarantine and reservations are freeze-only")
        if args.decisions is None:
            parser.error("assemble requires --decisions")
        result = assemble(args.output, args.decisions)
    print(json.dumps({key: result[key] for key in ("status", "n_selected")}))


if __name__ == "__main__":
    main()

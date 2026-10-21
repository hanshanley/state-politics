"""Focused tests for a model-blind sampler and strict review assembler."""

import copy
import json
import shutil
import sys
import uuid
from pathlib import Path

import pandas as pd
import pytest

from state_politics.analysis import prepare_cycle_review as review
from state_politics.analysis.prepare_cycle_review import (
    LIMITATIONS,
    RESERVATIONS,
    STATES,
    STATUS,
    TAXONOMY,
    TRAIN_LIMITATIONS,
    Reservation,
    assemble,
    assemble_decisions,
    binding,
    digest,
    freeze,
    main,
    read_frozen_plan,
    reservation_paths,
    sample_views,
    write_json,
    write_jsonl,
)


def context(number, state="AA", abstract=None):
    title = f"Distinct policy {number}"
    text = f"  {title}\n\n{abstract}  " if abstract else f"  {title}\n"
    bill = {
        "bill_id": f"bill:{number}", "state": state, "identifier": str(number),
        "session_identifier": "2024", "title": title, "cohort_scope": "source_coded_event",
        "source_test_record": False, "source_draft_request": False,
    }
    view = {
        **{key: bill[key] for key in (
            "bill_id", "state", "identifier", "session_identifier", "title", "cohort_scope",
        )},
        "view_id": f"view:{number}", "text": text, "abstract": abstract,
        "input_sha256": digest(text), "n_input_characters": len(text),
        "input_status": "unreviewed_metadata_candidate",
        "model_input_approved": False,
    }
    return bill, view


def test_strata_fill_no_candidate_state_and_full_strings():
    pairs = [context(n, abstract=f"Unmodified abstract {n}\n\nEnd" if n < 3 else None)
             for n in range(6)]
    bills, views = map(list, zip(*pairs, strict=True))
    original = copy.deepcopy(views)
    selected, accounting = sample_views(views, bills, Reservation(), states=("AA", "ME"))
    repeated, _ = sample_views(views[::-1], bills[::-1], Reservation(), states=("AA", "ME"))
    explicit, _ = sample_views(views, bills, Reservation(), states=("AA", "ME"), per_state=4)
    assert selected == repeated
    assert selected == explicit
    assert len(selected) == 4
    assert accounting["states"]["AA"]["actual_selected_strata"] == {
        "abstract_containing": 2, "title_only": 2,
    }
    assert accounting["states"]["ME"]["selected"] == 0
    assert accounting["states"]["ME"]["status"] == "no_eligible_candidate_not_zero_activity"
    assert views == original
    assert all(row["text"] == row["original_view"]["text"] for row in selected)


def test_reservations_duplicate_alternative_and_near_text():
    text = " ".join(f"unique{i}" for i in range(40))
    reservation = Reservation([{"record_id": "old", "group_id": "used", "text": text}])
    assert reservation.overlap({"text": "Another input", "bill_id": "used"})
    assert reservation.overlap({"text": text.upper()}) == "reserved_exact_text"
    assert reservation.overlap({"text": text + " addition"}) == "reserved_near_text"
    bill, view = context(1)
    alternate = {**view, "view_id": "alternative", "text": text,
                 "input_sha256": digest(text), "n_input_characters": len(text)}
    selected, accounting = sample_views([view, alternate], [bill], reservation, states=("AA",))
    assert not selected
    assert accounting["examined_context_exclusions"][0]["reason"] == "reserved_exact_text"
    with pytest.raises(ValueError, match="duplicate view"):
        sample_views([view, view], [bill], Reservation(), states=("AA",))


def reviewed_packet():
    bill, view = context(1)
    packet, _ = sample_views([view], [bill], Reservation(), states=("AA",))
    decision = {
        "record_id": packet[0]["record_id"], "input_sha256": packet[0]["input_sha256"],
        "topic": None, "abstention_reason": "insufficient_evidence",
        "reviewer_id": "GPT-6.1 Sol", "reviewer_type": "assistant", "reviewed_on": "2026-10-21",
        "input_reviewed_in_full": True, "input_only_no_external_context": True,
        "rationale": "This complete input names no substantive policy mechanism.",
        "evidence_spans": ["Distinct policy 1"],
    }
    return packet, decision


@pytest.mark.parametrize("topic", [True, False, 1.0, "1", 999])
def test_reject_noninteger_or_invalid_topics(topic):
    packet, decision = reviewed_packet()
    decision.update(topic=topic, abstention_reason=None)
    with pytest.raises(ValueError, match="invalid topic"):
        assemble_decisions(packet, [decision], [1, 2])


def test_reject_missing_duplicate_extra_hash_and_provenance():
    packet, decision = reviewed_packet()
    assert assemble_decisions(packet, [decision], [1])[0]["text"] == packet[0]["text"]
    cases = [
        [], [decision, decision], [{**decision, "record_id": "extra"}],
        [{**decision, "input_sha256": "0" * 64}],
        [{**decision, "reviewer_type": "human"}],
        [{**decision, "reviewer_id": ""}],
        [{**decision, "reviewer_id": None}],
        [{**decision, "input_reviewed_in_full": False}],
        [{**decision, "text": "malicious replacement"}],
        [{**decision, "evidence_spans": ["not in the provided input"]}],
    ]
    for decisions in cases:
        with pytest.raises(ValueError):
            assemble_decisions(packet, decisions, [1])


def test_distinct_assistant_reviewer_identity_is_preserved():
    packet, decision = reviewed_packet()
    decision["reviewer_id"] = "GPT-6.1Sol-training-A"
    labels = assemble_decisions(packet, [decision], [1])
    assert labels[0]["reviewer_id"] == decision["reviewer_id"]
    assert labels[0]["reviewer_type"] == "assistant"
    assert labels[0]["human_gold"] is False


def test_native_full_input_reservation_does_not_treat_unused_title_as_input():
    reservation = Reservation([{"record_id": "old", "text": "A generic title"}])
    native = {"source_type": "native_text", "text": "Entirely distinct complete policy body",
              "title": "A generic title"}
    assert reservation.overlap(native) is None
    assert reservation.overlap({**native, "text": "A generic title"}) == "reserved_exact_text"
    assert reservation.overlap({**native, "source_type": "bill_metadata"}) == "reserved_exact_text"


@pytest.fixture
def project_workspace():
    # Keep filesystem tests inside the project, never OS temporary directories.
    root = Path.cwd() / f".pytest-cycle-review-{uuid.uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root)


def source_packet(root, n_contexts=5):
    packet = root / "source"
    packet.mkdir()
    pairs = [context(n, state="AK") for n in range(n_contexts)]
    bills, views = map(list, zip(*pairs, strict=True))
    pd.DataFrame(views).to_parquet(packet / "candidate_metadata_views.parquet")
    pd.DataFrame(bills).to_parquet(packet / "bill_evidence.parquet")
    pd.DataFrame([
        {"state": state, "n_retained_contexts_wider_history": 9877 if state == "ME" else 10}
        for state in STATES
    ]).to_csv(packet / "state_matrix.csv", index=False)
    write_json(packet / "manifest.json", {
        "status": STATUS, "inputs_unchanged": True, "model_input_approved": False,
        "analytical_admission": False, "artifacts": {
            name: binding(packet / name) for name in (
                "candidate_metadata_views.parquet", "bill_evidence.parquet", "state_matrix.csv",
            )
        },
    })
    return packet


def test_custom_limit_and_reservation_extensions():
    pairs = [context(n, abstract=f"Complete separate abstract {n}" if n < 8 else None)
             for n in range(16)]
    bills, views = map(list, zip(*pairs, strict=True))
    selected, accounting = sample_views(
        views, bills, Reservation(), states=("AA",), per_state=12,
    )
    assert len(selected) == 12
    assert accounting["states"]["AA"]["actual_selected_strata"] == {
        "abstract_containing": 6, "title_only": 6,
    }
    paths = reservation_paths([Path("extra-review.jsonl"), RESERVATIONS[0]])
    assert paths == (*RESERVATIONS, Path("extra-review.jsonl"))


@pytest.mark.parametrize("per_state", [True, 0, -1, 4.0])
def test_invalid_limit(per_state):
    with pytest.raises(ValueError, match="positive integer"):
        sample_views([], [], Reservation(), states=(), per_state=per_state)


def test_invalid_role_and_existing_output_are_rejected(project_workspace):
    output = project_workspace / "existing"
    output.mkdir()
    marker = output / "original"
    marker.write_text("preserved")
    with pytest.raises(ValueError, match="review_split"):
        freeze(output=output, review_split="test")
    with pytest.raises(ValueError, match="explicit quarantine"):
        freeze(output=output, review_split="train")
    with pytest.raises(FileExistsError, match="refusing overwrite"):
        freeze(output=output)
    assert marker.read_text() == "preserved"


def test_default_role_is_locked_and_cannot_be_relabelled(
    project_workspace, monkeypatch,
):
    packet = source_packet(project_workspace)
    output = project_workspace / "challenge"
    frozen = freeze(packet, output, reservations=(), taxonomy=TAXONOMY)
    assert frozen["review_split"] == "challenge" and frozen["per_state"] == 4
    assert frozen["limitations"] == LIMITATIONS
    before = {path.name: binding(path) for path in output.iterdir()}
    rows = [json.loads(line) for line in (output / "review_packet.jsonl").read_text().splitlines()]
    with pytest.raises(ValueError, match="frozen review_split"):
        assemble_decisions(
            rows, [], [1], review_split="train", quarantine_rubric_ambiguity=True,
        )
    legacy = {"frozen_artifacts": {}, "review_split": "train",
              "quarantine_rubric_ambiguity": True}
    with pytest.raises(ValueError, match="legacy challenge"):
        read_frozen_plan(output, legacy)
    assert read_frozen_plan(output, {"frozen_artifacts": {}})["review_split"] == "challenge"
    monkeypatch.setattr(sys, "argv", [
        "prepare_cycle_review", "assemble", "--output", str(output),
        "--decisions", "unused.jsonl", "--review-split", "train",
    ])
    with pytest.raises(SystemExit):
        main()
    assert {path.name: binding(path) for path in output.iterdir()} == before


@pytest.mark.parametrize("all_ambiguous", [False, True])
def test_train_ambiguity_is_quarantined_without_reason_or_input_remapping(
    project_workspace, all_ambiguous,
):
    packet = source_packet(project_workspace)
    output = project_workspace / "training"
    frozen = freeze(
        packet, output, reservations=(), taxonomy=TAXONOMY, per_state=12,
        review_split="train", quarantine_rubric_ambiguity=True,
    )
    assert frozen["review_split"] == "train" and frozen["per_state"] == 12
    assert frozen["limitations"] == TRAIN_LIMITATIONS
    rows = [json.loads(line) for line in (output / "review_packet.jsonl").read_text().splitlines()]
    reasons = (None, "rubric_ambiguity", "non_policy", "mixed_policy", "insufficient_evidence")
    if all_ambiguous:
        reasons = ("rubric_ambiguity",) * 5
    decisions = [
        {
            "record_id": row["record_id"], "input_sha256": row["input_sha256"],
            "topic": 1 if reason is None else None, "abstention_reason": reason,
            "reviewer_id": "GPT-6.1 Sol", "reviewer_type": "assistant",
            "reviewed_on": "2026-10-21", "input_reviewed_in_full": True,
            "input_only_no_external_context": True,
            "rationale": "Synthetic test review with explicit, unremapped disposition.",
            "evidence_spans": [row["original_view"]["title"]],
        }
        for row, reason in zip(rows, reasons, strict=True)
    ]
    decisions_path = project_workspace / "decisions.jsonl"
    write_jsonl(decisions_path, decisions)
    receipt = assemble(output, decisions_path)
    assert receipt["n_labels"] == (0 if all_ambiguous else 4)
    assert receipt["n_quarantined"] == (5 if all_ambiguous else 1)
    assert receipt["n_decisions"] == receipt["n_reviewed"] == 5
    labels = review.load_examples(output / "labels.jsonl", [1]) if not all_ambiguous else []
    assert all(row["split"] == "train" and row["training_admission"] is False for row in labels)
    if not all_ambiguous:
        assert {row["abstention_reason"] for row in labels if row["topic"] is None} == {
            "non_policy", "mixed_policy", "insufficient_evidence",
        }
    sidecar = [
        json.loads(line)
        for line in (output / "quarantined_units.jsonl").read_text().splitlines()
    ]
    quarantined = sidecar[1] if all_ambiguous else sidecar[0]
    assert quarantined["abstention_reason"] == "rubric_ambiguity"
    assert quarantined["topic"] is None and quarantined["quarantined"] is True
    assert quarantined["text"] == rows[1]["text"]
    assert quarantined["input_sha256"] == rows[1]["input_sha256"]
    assert len((output / "semantic_decisions.jsonl").read_text().splitlines()) == 5
    batches = [json.loads((output / f"review_batch_{batch}_indices.json").read_text())
               for batch in ("a", "b")]
    indices = [{row["source_line_1based"] for row in batch["indices"]} for batch in batches]
    assert indices[0].isdisjoint(indices[1])
    assert indices[0] | indices[1] == set(range(1, 6))
    before = {path.name: binding(path) for path in output.iterdir()}
    with pytest.raises(FileExistsError):
        assemble(output, decisions_path)
    assert {path.name: binding(path) for path in output.iterdir()} == before


def test_jsonl_unicode_separators_survive_full_assembly(project_workspace):
    packet = source_packet(project_workspace, n_contexts=1)
    path = packet / "candidate_metadata_views.parquet"
    views = pd.read_parquet(path)
    text = views.loc[0, "text"] + "preserved\u2028line\u2029paragraph"
    views.loc[0, "text"] = text
    views.loc[0, "input_sha256"] = digest(text)
    views.loc[0, "n_input_characters"] = len(text)
    views.to_parquet(path)
    manifest_path = packet / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["artifacts"][path.name] = binding(path)
    write_json(manifest_path, manifest)
    output = project_workspace / "unicode-review"
    freeze(packet, output, reservations=())
    row = review.read_jsonl(output / "review_packet.jsonl")[0]
    decisions = project_workspace / "decisions.jsonl"
    write_jsonl(decisions, [{
        "record_id": row["record_id"], "input_sha256": row["input_sha256"],
        "topic": 1, "abstention_reason": None,
        "reviewer_id": "fixture", "reviewer_type": "assistant", "reviewed_on": "2026-10-21",
        "input_reviewed_in_full": True, "input_only_no_external_context": True,
        "rationale": "Complete synthetic review preserving Unicode source separators.",
        "evidence_spans": ["preserved\u2028line\u2029paragraph"],
    }])
    assert assemble(output, decisions)["n_labels"] == 1
    assert review.read_jsonl(output / "labels.jsonl")[0]["text"] == text

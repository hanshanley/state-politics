"""Complete native-input sampling, provenance and reservation integration."""

import copy
import gzip
import json
from pathlib import Path

import pytest

from state_politics.analysis.prepare_cycle_review import (
    Reservation,
    assemble,
    binding,
    digest,
    read_jsonl,
    write_json,
    write_jsonl,
)
from state_politics.analysis.prepare_native_review import (
    STATES,
    TAXONOMY,
    compare_reviews,
    freeze_native,
    sample_state,
    view_key,
)


def native(number=1, text="A complete source law on schools.", state="AK", root="native"):
    bill = {
        "bill_id": f"bill:{number}", "state": state, "identifier": f"HB {number}",
        "session_identifier": "2024", "source_test_record": False, "source_draft_request": False,
        "model_input_approved": False, "filing_time_text_certified": False,
        "analytical_admission": False,
    }
    return {
        "source_type": "native_text", "state": state, "packet_root": root,
        "view_id": f"view:{number}", "context_id": f"context:{number}",
        "bill_id": bill["bill_id"], "identifier": bill["identifier"],
        "session_identifier": "2024", "text": text, "n_input_characters": len(text),
        "input_sha256": digest(text), "bill_context": bill, "native_context": dict(bill),
        "native_identity_certified": False, "model_input_approved": False,
        "filing_time_text_certified": False, "training_admission": False,
        "analytical_admission": False,
    }


def sample(records, reservation=None, **kwargs):
    return sample_state(
        records, reservation or Reservation(), state="AK", seed="fixture", per_state=2,
        max_characters=12000, **kwargs,
    )


def test_whole_inputs_state_strata_and_namespaced_reader_alternatives():
    short = native(1, text="All characters\u2028remain unchanged.\r\n")
    long = native(2, text="Complete education provisions. " * 90)
    alternate = {**short, "packet_root": "another", "text": short["text"] + "reader"}
    alternate.update(input_sha256=digest(alternate["text"]),
                     n_input_characters=len(alternate["text"]))
    original = copy.deepcopy([short, long, alternate])
    rows, counts = sample(original)
    repeated, _ = sample(original[::-1])
    assert rows == repeated
    assert counts["selected_strata"] == {"up_to_2000_characters": 1, "longer_complete": 1}
    selected = next(row for row in rows if row["bill_id"] == "bill:1")
    assert len(selected["alternative_view_ids"]) == 2
    assert len(set(selected["alternative_view_ids"])) == 2
    assert selected["text"] in (short["text"], alternate["text"])
    assert selected["original_view"]["text"] == selected["text"]
    assert original == [short, long, alternate]


def test_all_reader_alternatives_and_bill_identity_are_reserved():
    row = native(1, text="A new and otherwise independent body")
    other = native(1, text="Previously held out policy body")
    other["view_id"] = "another-reader"
    reservation = Reservation([{"record_id": "heldout", "text": other["text"]}])
    assert not sample([row, other], reservation)[0]
    reservation = Reservation([{"record_id": "old", "group_id": row["bill_id"],
                                "text": "Entirely different prior metadata"}])
    assert not sample([row], reservation)[0]


@pytest.mark.parametrize("mutate", [
    lambda row: row.update(text="replacement"),
    lambda row: row.update(n_input_characters=1),
    lambda row: row.update(analytical_admission=True),
    lambda row: row.update(state="CA"),
    lambda row: row["native_context"].update(identifier="SB 99"),
    lambda row: row["bill_context"].update(source_test_record=None),
])
def test_corrupt_or_admitted_sources_fail(mutate):
    row = native()
    mutate(row)
    with pytest.raises(ValueError):
        sample([row])


def test_long_and_source_excluded_bodies_are_not_truncated_or_admitted():
    row = native(1, text="whole source " * 1001)
    draft = native(2)
    draft["bill_context"]["source_draft_request"] = True
    before = copy.deepcopy([row, draft])
    selected, counts = sample([row, draft])
    assert not selected
    assert counts["excluded_all_views_over_character_limit"] == 1
    assert counts["excluded_test_or_draft_bills"] == 1
    assert [row, draft] == before


def preview_fixture(root: Path):
    preview = root / "preview"
    (preview / "downloads").mkdir(parents=True)
    row = native()
    outputs = {}
    for state in STATES:
        path = preview / f"downloads/native-{state}.jsonl.gz"
        with gzip.open(path, "wb") as handle:
            if state == "AK":
                handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode())
        outputs[path.relative_to(preview).as_posix()] = binding(path)
    write_json(preview / "downloads/build_manifest.json", {
        "schema": "local_cycle_evidence_preview_v1", "publication_status": "local_only_unpublished",
        "model_input_approved": False, "analytical_admission": False,
        "inputs": {"native_evidence": {"manifest.json": "fixture"}},
        "outputs": outputs,
        "counts": {"native_full_text_candidate_views": 1, "native_full_text_candidate_contexts": 1},
    })
    return preview, row


def test_freeze_keeps_all_states_originals_and_native_assembly(tmp_path):
    preview, source = preview_fixture(tmp_path)
    output = tmp_path / "review"
    manifest = freeze_native(preview, output, reservations=(), taxonomy=TAXONOMY)
    assert manifest["sources_unchanged"] is True
    assert read_jsonl(output / "selected_alternative_views.jsonl") == [source]
    accounting = json.loads((output / "sampling_manifest.json").read_bytes())
    assert set(accounting["states"]) == set(STATES)
    assert accounting["states"]["ME"]["selected"] == 0
    row = read_jsonl(output / "review_packet.jsonl")[0]
    decisions = tmp_path / "decisions.jsonl"
    write_jsonl(decisions, [{
        "record_id": row["record_id"], "input_sha256": row["input_sha256"],
        "topic": 6, "abstention_reason": None, "reviewer_id": "native-fixture",
        "reviewer_type": "assistant", "reviewed_on": "2026-10-21",
        "input_reviewed_in_full": True, "input_only_no_external_context": True,
        "rationale": "The entire supplied policy source explicitly concerns schools.",
        "evidence_spans": ["schools"],
    }])
    assert assemble(output, decisions)["n_labels"] == 1
    label = read_jsonl(output / "labels.jsonl")[0]
    assert label["text"] == source["text"]
    assert ":cycle-native:" in label["source_url"]
    assert label["document_text_sha256"] == source["input_sha256"]
    assert label["human_gold"] is label["training_admission"] is False


def test_unlabelled_reserved_inputs_and_corrupt_partition(tmp_path):
    preview, source = preview_fixture(tmp_path)
    reservation = tmp_path / "prior_inputs.jsonl"
    write_jsonl(reservation, [{"record_id": "previous", "bill_id": source["bill_id"],
                              "text": "Prior metadata", "input_sha256": digest("Prior metadata")}])
    output = tmp_path / "empty-review"
    assert freeze_native(
        preview, output, reservations=(), reservation_inputs=(reservation,),
    )["n_selected"] == 0
    path = preview / "downloads/native-AK.jsonl.gz"
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="frozen artifact mismatch"):
        freeze_native(preview, tmp_path / "bad", reservations=())
    assert not (tmp_path / "bad").exists()


def test_duplicate_views_and_invalid_limits():
    row = native()
    with pytest.raises(ValueError, match="duplicate namespaced"):
        sample([row, row])
    for value in (True, 0, -1, 2.0):
        with pytest.raises(ValueError, match="positive integer"):
            sample_state([], Reservation(), state="AK", seed="x",
                         per_state=value, max_characters=12000)
    assert view_key(row) != view_key({**row, "packet_root": "other"})


def test_independent_reviews_preserve_disagreement_without_a_winner():
    rows, _ = sample([native()])
    row = rows[0]
    first = {
        "record_id": row["record_id"], "input_sha256": row["input_sha256"],
        "topic": 6, "abstention_reason": None, "reviewer_id": "reviewer-a",
        "reviewer_type": "assistant", "reviewed_on": "2026-10-21",
        "input_reviewed_in_full": True, "input_only_no_external_context": True,
        "rationale": "The supplied complete source concerns public school policy.",
        "evidence_spans": ["schools"],
    }
    second = {**first, "reviewer_id": "reviewer-b"}
    merged, audit = compare_reviews(rows, [first], [second], [6, 20])
    assert audit["n_agreed"] == 1 and merged[0]["topic"] == 6
    second.update(topic=20, rationale="Alternative synthetic judgment of government policy.")
    merged, audit = compare_reviews(rows, [first], [second], [6, 20])
    assert audit["n_agreed"] == 0
    assert audit["disputed_record_ids"] == [row["record_id"]]
    assert merged[0]["topic"] is None
    assert merged[0]["abstention_reason"] == "rubric_ambiguity"
    assert audit["all_original_reviews"]["a"] == [first]
    assert audit["all_original_reviews"]["b"] == [second]
    with pytest.raises(ValueError, match="distinct reviewer"):
        compare_reviews(rows, [first], [first], [6, 20])

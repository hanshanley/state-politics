import hashlib
import json

import pandas as pd
import pytest

from state_politics.analysis import prepare_republican_curriculum as republican
from state_politics.analysis.prepare_platform_curriculum import (
    numbered_span,
    paragraph_span,
    section_span,
)
from state_politics.platforms.recovery import load_jsonl, verify_manifest
from state_politics.provenance import sha256_file


def test_numbered_unit_keeps_scope_and_excludes_a_trailing_pdf_page_number():
    text = "Title\n\nFirst\n1. First policy.\n 13\n2. Second policy.\n\nNext\n1. Other.\n"
    bounds = section_span(text, "\nFirst\n", "\nNext\n")
    start, end = numbered_span(text, 1, bounds)
    assert text[start:end] == "1. First policy."
    with pytest.raises(ValueError, match="ambiguous"):
        numbered_span(text, 1)


def test_numbered_unit_does_not_truncate_a_policy_at_an_internal_page_break():
    text = "1. Require restoration to the\n 3\n\n original condition.\n2. Another policy.\n"
    start, end = numbered_span(text, 1)
    assert text[start:end] == "1. Require restoration to the\n 3\n\n original condition."


def test_paragraph_selection_preserves_heading_and_preceding_policy_sentences():
    text = "Previous.\n\nHealth\nFirst commitment.\nSecond commitment.\n\nNext."
    start, end = paragraph_span(text, "Second commitment")
    assert text[start:end] == "Health\nFirst commitment.\nSecond commitment."


def test_ambiguous_or_absent_source_selectors_fail_explicitly():
    with pytest.raises(ValueError, match="ambiguous"):
        paragraph_span("Repeated.\n\nRepeated.", "Repeated")
    with pytest.raises(ValueError, match="absent"):
        section_span("No such heading.", "\nMissing\n")
    with pytest.raises(ValueError, match="absent"):
        numbered_span("1. Only policy.", 2)


def _republican_inputs(tmp_path, monkeypatch, *, copy_heldout=False):
    def manifest(root):
        path = root / "manifest.json"
        path.write_text(json.dumps({"files": {
            file.name: sha256_file(file) for file in root.iterdir()
            if file.is_file() and file != path
        }}))
        return sha256_file(path)

    context = tmp_path / "context"
    context.mkdir()
    unit = (
        "Education\nFund public school classrooms across the state.\u2028"
        "Keep the complete source unit."
    )
    text = f"Cover metadata\n\n{unit}\n\nNext native section.\n"
    raw = context / "KS-R.bin"
    raw.write_bytes(b"synthetic retained source, not an actual platform")
    (context / "KS-R.txt").write_text(text)
    parquet = context / "KS-R.parquet"
    pd.DataFrame([{
        "state": "KS", "party": "R", "url": "https://example.test/platform",
        "sha256": sha256_file(raw), "text": text,
    }]).to_parquet(parquet, index=False)
    (context / "sources.json").write_text(json.dumps({"sources": [{
        "organization": "KS-R", "state": "KS", "party": "R",
        "source_url": "https://example.test/platform", "source_sha256": sha256_file(raw),
        "document_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "source_parquet_sha256": sha256_file(parquet), "capture_id": "synthetic:one",
    }]}))
    labels = tmp_path / "previous.jsonl"
    common = {
        "domain": "bill", "source_url": "https://example.test/bills",
        "label_version": "synthetic", "evidence_tier": "official_summary", "topic": 6,
        "reviewer_id": "synthetic-assistant", "reviewer_type": "assistant",
        "reviewed_on": "2026-10-19", "rationale": "Synthetic test evidence.",
    }
    original = [
        {**common, "record_id": "train", "group_id": "train", "split": "train",
         "label_origin": "external_coded", "text": "Existing external training policy."},
        {**common, "record_id": "dev", "group_id": "dev", "split": "dev",
         "label_origin": "reviewed_target",
         "text": unit if copy_heldout else "Existing unrelated development reference."},
    ]
    labels.write_text("".join(json.dumps(row) + "\n" for row in original))
    reservation = tmp_path / "reservation"
    reservation.mkdir()
    reservation_path = reservation / "reservation.json"
    reservation_path.write_text(json.dumps({"sources": [{
        "organization": "WA-R", "state": "WA", "party": "R",
        "source_sha256": "a" * 64, "document_text_sha256": "b" * 64,
    }]}))
    challenge = tmp_path / "challenge"
    challenge.mkdir()
    heldout = {
        **common, "domain": "plank", "record_id": "challenge", "group_id": "challenge",
        "state": "WA", "party": "R", "split": "challenge",
        "source_sha256": "a" * 64, "document_text_sha256": "b" * 64,
        "label_origin": "reviewed_target", "text": "Unrelated reserved policy reference.",
    }
    (challenge / "labels.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in original + [heldout])
    )
    for key, value in {
        "CONTEXT": context, "CONTEXT_SHA256": manifest(context),
        "BASE_LABELS": labels, "BASE_SHA256": sha256_file(labels),
        "RESERVATION": reservation_path, "RESERVATION_SHA256": manifest(reservation),
        "CHALLENGE": challenge, "CHALLENGE_SHA256": manifest(challenge),
        "REVIEW": {"KS-R": (
            ("Fund public school classrooms", None, 6, "Funds school classrooms."),
        )},
        "QUARANTINE": {"KS-R": (
            ("Next native section.", None, "Synthetic unresolved scope."),
        )},
        "FRONT_MARKERS": {"KS-R": "Education\n"},
    }.items():
        monkeypatch.setattr(republican, key, value)
    return original, text, unit


def test_republican_successor_preserves_references_native_text_and_complete_sources(
    tmp_path, monkeypatch,
):
    original, text, unit = _republican_inputs(tmp_path, monkeypatch)
    out = tmp_path / "successor"
    report = republican.build(out)
    rows = load_jsonl(out / "labels.jsonl")
    assert rows[:len(original)] == original
    assert (out / "previous_labels.jsonl").read_bytes() == republican.BASE_LABELS.read_bytes()
    assert (out / "source" / "KS-R.txt").read_text() == text
    assert (out / "source" / "KS-R.bin").read_bytes() == (
        republican.CONTEXT / "KS-R.bin"
    ).read_bytes()
    policy = next(row for row in rows[len(original):] if row["topic"] == 6)
    assert policy["text"] == unit
    assert text[policy["span_start"]:policy["span_end"]] == unit
    assert text[policy["context_start"]:policy["context_end"]] == policy["context_text"]
    assert report["new_policy_units"] == 1
    assert report["new_abstentions"] == {"non_policy": 1}
    assert report["challenge_rows_unchanged"] == 1
    quarantine = load_jsonl(out / "quarantined_units.jsonl")
    assert len(quarantine) == 1
    assert "topic" not in quarantine[0] and "split" not in quarantine[0]
    assert quarantine[0]["training_admission"] is False
    verify_manifest(out, {"labels.jsonl", "previous_labels.jsonl", "preparation.json"})
    with pytest.raises(FileExistsError):
        republican.build(out)


@pytest.mark.parametrize("failure", ["heldout_copy", "changed_source", "changed_reference"])
def test_republican_successor_rejects_leakage_or_changed_evidence_before_writing(
    tmp_path, monkeypatch, failure,
):
    _republican_inputs(tmp_path, monkeypatch, copy_heldout=failure == "heldout_copy")
    expected = "closely copies held-out"
    if failure == "changed_source":
        (republican.CONTEXT / "KS-R.bin").write_bytes(b"changed bytes")
        expected = "manifest hash mismatch"
    elif failure == "changed_reference":
        republican.BASE_LABELS.write_text(republican.BASE_LABELS.read_text() + "\n")
        expected = "frozen curriculum input changed"
    out = tmp_path / "rejected"
    with pytest.raises(ValueError, match=expected):
        republican.build(out)
    assert not out.exists()

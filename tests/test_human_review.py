"""Synthetic review only: actual recruitment texts must remain unseen/unannotated."""

import copy
import gzip
import json
import os
import shutil
import zipfile
from datetime import date
from pathlib import Path

import pytest
from test_prepare_native_review import native

from state_politics.analysis.human_review import (
    ATTESTATION,
    FLAGS,
    SCHEMA,
    build,
    compare,
    import_annotation,
    load_packet,
    strict_json,
    validate_annotation,
)
from state_politics.analysis.prepare_cycle_review import (
    binding,
    read_jsonl,
    write_json,
    write_jsonl,
)
from state_politics.analysis.prepare_native_review import STATES, freeze_native


def fixture_packet(root):
    preview = root / "preview"
    (preview / "downloads").mkdir(parents=True)
    text = (
        'SYNTHETIC source: education policy.\r\n'
        'Unicode separators \u2028remain\u2029literal 😀. '
        '<img src=x onerror="window.sourceInjected=true">'
        '<script>window.sourceInjected=true</script>'
    )
    first = native(701, text=text)
    first["giant_provenance_integer"] = 184467440737095516171234567890
    alternative = {
        **first, "packet_root": "second-reader",
        "text": first["text"] + "\nAn entire preserved synthetic alternative.",
    }
    from state_politics.analysis.prepare_cycle_review import digest

    alternative["input_sha256"] = digest(alternative["text"])
    alternative["n_input_characters"] = len(alternative["text"])
    second = native(702, text="SYNTHETIC ceremonial input. " * 5)
    outputs = {}
    for state in STATES:
        path = preview / f"downloads/native-{state}.jsonl.gz"
        with gzip.open(path, "wb") as handle:
            if state == "AK":
                for row in (first, alternative, second):
                    handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode())
        outputs[path.relative_to(preview).as_posix()] = binding(path)
    write_json(preview / "downloads/build_manifest.json", {
        "schema": "local_cycle_evidence_preview_v1", "publication_status": "local_only_unpublished",
        "model_input_approved": False, "analytical_admission": False,
        "inputs": {"native_evidence": {}}, "outputs": outputs,
        "counts": {"native_full_text_candidate_views": 3, "native_full_text_candidate_contexts": 2},
    })
    frozen = root / "frozen"
    freeze_native(preview, frozen, reservations=(), seed="synthetic-only")
    # Ensure the downloadable source is genuinely original whitespace/Unicode,
    # not a new compact serialization that happens to parse to the same value.
    source = frozen / "selected_alternative_views.jsonl"
    source.write_bytes(source.read_bytes().replace(b'{"', b'{ "', 1))
    manifest = json.loads((frozen / "source_manifest.json").read_bytes())
    manifest["frozen_artifacts"][source.name] = binding(source)
    write_json(frozen / "source_manifest.json", manifest)
    output = root / "packet"
    build(frozen, output)
    return frozen, output


@pytest.fixture
def packet(tmp_path):
    return fixture_packet(tmp_path)


def completed(root, reviewer="synthetic-rater-a"):
    manifest, records = load_packet(root)
    return {
        "schema": SCHEMA, "packet_id": manifest["packet_id"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "reviewer_id": reviewer, "human_provenance": ATTESTATION,
        "all_records_reviewed_in_full": True, "no_model_assistance": True,
        "decisions": [{
            "record_id": row["record_id"], "input_sha256": row["input_sha256"],
            "topic": 6 if index == 0 else None,
            "abstention_reason": None if index == 0 else "insufficient_evidence",
            "reviewer_id": reviewer, "reviewer_type": "human_self_attested",
            "reviewed_on": date.today().isoformat(), "input_reviewed_in_full": True,
            "input_only_no_external_context": True,
            "rationale": "SYNTHETIC automation fixture, not a real human annotation.",
            "evidence_spans": [row["text"][:25]],
        } for index, row in enumerate(records)],
    }


def test_complete_byte_preserving_build_and_import(packet, tmp_path):
    frozen, root = packet
    manifest, records = load_packet(root)
    assert manifest["n_selected"] == 2 and manifest["states_accounted_for"] == 50
    assert len(json.loads((root / "ui-data.json").read_bytes())["topics"]) == 21
    for name in manifest["complete_inputs"]:
        assert (root / "complete-inputs" / name).read_bytes() == (frozen / name).read_bytes()
    with zipfile.ZipFile(root / "complete-inputs.zip") as archive:
        for name in manifest["complete_inputs"]:
            assert archive.read(f"complete-inputs/{name}") == (frozen / name).read_bytes()
    alternatives = (root / "complete-inputs/selected_alternative_views.jsonl").read_bytes()
    assert b"184467440737095516171234567890" in alternatives
    assert "\u2028".encode() in alternatives
    assert len(records) == 2
    annotations = tmp_path / "annotation.json"
    raw = (json.dumps(completed(root), ensure_ascii=False, indent=3) + "\n").encode()
    annotations.write_bytes(raw)
    target = tmp_path / "imported"
    receipt = import_annotation(root, annotations, target)
    assert all(receipt[flag] is False for flag in FLAGS)
    assert (target / "annotations-only.json").read_bytes() == raw
    assert not (target / "labels.jsonl").exists()
    assert read_jsonl(target / "decisions-only.jsonl") == completed(root)["decisions"]
    for name in manifest["complete_inputs"]:
        assert (target / "complete-inputs" / name).read_bytes() == (frozen / name).read_bytes()
    validate_annotation(target, strict_json(raw))
    with pytest.raises(FileExistsError):
        import_annotation(root, annotations, target)


@pytest.mark.parametrize("change", [
    lambda a: a.update(packet_id="foreign"),
    lambda a: a.update(source_manifest_sha256="foreign"),
    lambda a: a.update(human_provenance="CERTIFIED_HUMAN"),
    lambda a: a.update(reviewer_id="person@example.com"),
    lambda a: a.update(all_records_reviewed_in_full=1),
    lambda a: a.update(no_model_assistance="true"),
    lambda a: a.update(human_gold=True),
    lambda a: a.update(decisions=a["decisions"][:1]),
    lambda a: a["decisions"].append(copy.deepcopy(a["decisions"][0])),
    lambda a: a["decisions"].__setitem__(1, copy.deepcopy(a["decisions"][0])),
    lambda a: a["decisions"][0].update(record_id="foreign"),
    lambda a: a["decisions"][0].update(record_id=[]),
    lambda a: a["decisions"][0].update(input_sha256="wrong"),
    lambda a: a["decisions"][0].update(topic=True),
    lambda a: a["decisions"][0].update(topic=6.0),
    lambda a: a["decisions"][0].update(topic=999),
    lambda a: a["decisions"][0].update(topic=None, abstention_reason=None),
    lambda a: a["decisions"][0].update(abstention_reason="non_policy"),
    lambda a: a["decisions"][0].update(input_reviewed_in_full=1),
    lambda a: a["decisions"][0].update(input_only_no_external_context=False),
    lambda a: a["decisions"][0].update(reviewer_type="human"),
    lambda a: a["decisions"][0].update(reviewer_id="other-reviewer"),
    lambda a: a["decisions"][0].update(reviewed_on="2099-01-01"),
    lambda a: a["decisions"][0].update(reviewed_on="2026-02-30"),
    lambda a: a["decisions"][0].update(rationale="too short"),
    lambda a: a["decisions"][0].update(evidence_spans=[]),
    lambda a: a["decisions"][0].update(evidence_spans=["not present in source"]),
    lambda a: a["decisions"][0].update(text="cannot replace source"),
    lambda a: a["decisions"].__setitem__(0, None),
])
def test_strict_annotation_refusal(packet, change):
    _, root = packet
    annotation = completed(root)
    change(annotation)
    with pytest.raises(ValueError):
        validate_annotation(root, annotation)


@pytest.mark.parametrize("raw", [
    '{"x":1,"x":2}', '{"nested":{"x":1,"x":2}}', '{"x":NaN}',
    '{"x":Infinity}', "[", "null", "[]",
])
def test_malformed_imports_never_materialize(packet, tmp_path, raw):
    _, root = packet
    source = tmp_path / "bad.json"
    source.write_text(raw)
    with pytest.raises(ValueError):
        import_annotation(root, source, tmp_path / "bad-output")
    assert not (tmp_path / "bad-output").exists()


@pytest.mark.parametrize("name", [
    "complete-inputs/review_packet.jsonl",
    "complete-inputs/selected_alternative_views.jsonl",
    "ui-data.json", "complete-inputs.zip", "human-review.js",
])
def test_changed_source_or_ui_refused(packet, name):
    _, root = packet
    path = root / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="mismatch"):
        load_packet(root)


def test_self_attested_comparison_preserves_disagreements(packet, tmp_path):
    _, root = packet
    first, second = completed(root), completed(root, "synthetic-rater-b")
    second["decisions"][0].update(topic=None, abstention_reason="rubric_ambiguity")
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    write_json(a, first)
    write_json(b, second)
    report = compare(root, a, b, tmp_path / "comparison.json")
    assert report["n_agreed"] == report["n_disputed"] == 1
    assert report["all_original_reviews"] == {"a": first, "b": second}
    assert report["disputed_record_ids"] == [first["decisions"][0]["record_id"]]
    assert "no winner" in report["disagreement_policy"]
    assert not report["human_gold"]
    assert "assistant" not in json.dumps(report)
    with pytest.raises(ValueError, match="distinct reviewer"):
        compare(root, a, a, tmp_path / "same-reviewer.json")


@pytest.mark.parametrize("field,value", [
    ("record_id", "foreign-record"),
    ("bill_id", "foreign-bill"),
    ("input_sha256", "wrong"),
    ("source_view_sha256", "wrong"),
    ("alternative_view_ids", []),
])
def test_frozen_identity_checks_even_if_artifact_hash_is_rebound(packet, tmp_path, field, value):
    frozen, _ = packet
    path = frozen / "review_packet.jsonl"
    rows = read_jsonl(path)
    rows[0][field] = value
    write_jsonl(path, rows)
    manifest_path = frozen / "source_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["frozen_artifacts"][path.name] = binding(path)
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="mismatch|alternatives"):
        build(frozen, tmp_path / "bad-rebound-packet")


def test_explicit_empty_packet_is_not_an_annotation_opportunity(tmp_path):
    frozen, _ = fixture_packet(tmp_path)
    write_jsonl(frozen / "review_packet.jsonl", [])
    write_jsonl(frozen / "selected_alternative_views.jsonl", [])
    sampling_path = frozen / "sampling_manifest.json"
    sampling = json.loads(sampling_path.read_bytes())
    sampling["n_selected"] = 0
    for value in sampling["states"].values():
        value["selected"] = 0
        value["deficit_to_per_state_limit"] = 2
    write_json(sampling_path, sampling)
    manifest_path = frozen / "source_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["n_selected"] = 0
    for name in (
        "review_packet.jsonl", "selected_alternative_views.jsonl", "sampling_manifest.json",
    ):
        manifest["frozen_artifacts"][name] = binding(frozen / name)
    write_json(manifest_path, manifest)
    root = tmp_path / "empty"
    result = build(frozen, root)
    assert result["n_selected"] == 0
    with pytest.raises(ValueError, match="no eligible"):
        validate_annotation(root, completed(root))


def test_persist_browser_fixture(packet):
    """Opt-in output only under ignored data/, for the real Chromium runner."""
    target = os.environ.get("HUMAN_REVIEW_BROWSER_FIXTURE")
    if not target:
        return
    target = Path(target).resolve()
    data_root = (Path(__file__).resolve().parents[1] / "data").resolve()
    assert target.is_relative_to(data_root)
    _, root = packet
    shutil.copytree(root, target)

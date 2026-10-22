"""Local model-blind human review: build, validate/import, and compare.

Build only from ``prepare_native_review freeze`` output. Serve the resulting
directory on 127.0.0.1, never publish it. Imported annotations are self-attestations,
not verified identities, canonical training labels, human gold, or model approval.
Freeze an evaluation plan before annotation, export complete validated reviews as
advisory challenge references, then score saved logits through evaluate_topics.
No action here runs a model or grants training/gold admission.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import sys
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

from .prepare_cycle_review import (
    ABSTENTIONS,
    FALSE_FLAGS,
    STATES,
    Reservation,
    assert_binding,
    binding,
    canonical,
    digest,
    read_frozen_plan,
    write_json,
    write_jsonl,
)
from .prepare_native_review import compare_reviews, validate_native, view_key
from .taxonomy import load_topics
from .train_topics import load_examples, validate_split_isolation

SCHEMA = "local_self_attested_human_review_v1"
ATTESTATION = "SELF_ATTESTED_HUMAN_NOT_IDENTITY_CERTIFIED"
NOTICE = (
    "Local-only, model-blind HUMAN annotation. Human provenance is SELF-ATTESTED, "
    "not certified identity. Use a pseudonymous reviewer ID; do not enter personal data. "
    "No checkbox grants human gold, canonical training status, model approval, "
    "legal identity, filing-time validity, or analytical admission. "
    "This length/state-balanced research recruitment is NOT representative sampling. "
    "Only the entire chosen retained native input is decision evidence. All preserved "
    "alternatives/provenance remain available for source audit, not extra records or "
    "external decision evidence. Complete inputs means the complete selected frozen "
    "packet, not remote original PDF/HTML binaries or the entire candidate corpus."
)
FLAGS = (*FALSE_FLAGS, "human_gold", "independent_gold", "canonical_gold")
DECISION_FIELDS = {
    "record_id", "input_sha256", "topic", "abstention_reason", "reviewer_id",
    "reviewer_type", "reviewed_on", "input_reviewed_in_full",
    "input_only_no_external_context", "rationale", "evidence_spans",
}
ENVELOPE_FIELDS = {
    "schema", "packet_id", "source_manifest_sha256", "reviewer_id", "human_provenance",
    "all_records_reviewed_in_full", "no_model_assistance", "decisions",
}
REVIEWER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,47}\Z")
EVALUATION_SCHEMA = "self_attested_human_evaluation_v1"
POLICY = {"temperature": 1.0, "min_confidence": 0.8, "min_margin": 0.2}
PRIMARY_EXCLUDED_REASONS = ("mixed_policy", "rubric_ambiguity")


def strict_json(raw: bytes | str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (json.JSONDecodeError, UnicodeError, TypeError) as exc:
        raise ValueError("malformed JSON") from exc


def json_lines(path: Path) -> list[dict]:
    rows = [strict_json(line) for line in path.read_bytes().split(b"\n") if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("JSONL objects required")
    return rows


def safe_name(name: str) -> str:
    if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
        raise ValueError("unsafe artifact name")
    return name


def frozen_inputs(root: Path) -> tuple[dict, list[dict], list[dict]]:
    manifest = strict_json((root / "source_manifest.json").read_bytes())
    if (
        not isinstance(manifest, dict)
        or manifest.get("status") != "frozen_inputs_before_semantic_decisions"
        or manifest.get("input_basis") != "retained_native_text"
        or manifest.get("review_split") != "challenge"
        or manifest.get("sources_unchanged") is not True
    ):
        raise ValueError("immutable complete native challenge freeze required")
    artifacts = manifest.get("frozen_artifacts")
    required = {
        "review_packet.jsonl", "selected_alternative_views.jsonl", "topics.yml",
        "sampling_manifest.json", "review_plan.json", "original_packet_manifest.json",
    }
    if not isinstance(artifacts, dict) or not required <= artifacts.keys():
        raise ValueError("incomplete frozen packet")
    for name, expected in artifacts.items():
        assert_binding(root / safe_name(name), expected)
    read_frozen_plan(root, manifest)
    records = json_lines(root / "review_packet.jsonl")
    alternatives = json_lines(root / "selected_alternative_views.jsonl")
    by_view = {}
    for alternative in alternatives:
        validate_native(alternative, alternative.get("state"))
        key = view_key(alternative)
        if key in by_view:
            raise ValueError("duplicate native alternative")
        by_view[key] = alternative
    seen, bills, used = set(), set(), set()
    for row in records:
        if not isinstance(row.get("record_id"), str) or row["record_id"] in seen:
            raise ValueError("duplicate/invalid record identity")
        seen.add(row["record_id"])
        if row.get("bill_id") in bills:
            raise ValueError("duplicate bill")
        bills.add(row.get("bill_id"))
        chosen = by_view.get(row.get("view_id"))
        if chosen is None or chosen != row.get("original_view"):
            raise ValueError("chosen source mismatch")
        if row.get("state") not in STATES or row["state"] != chosen["state"]:
            raise ValueError("record state mismatch")
        if (
            row["record_id"] != f"cycle-native-review-v1:{digest(view_key(chosen))}"
            or row.get("group_id") != chosen["bill_id"] or row.get("bill_id") != chosen["bill_id"]
            or row.get("text") != chosen["text"]
            or row.get("input_sha256") != chosen["input_sha256"]
            or row.get("document_text_sha256") != chosen["input_sha256"]
            or row.get("source_view_sha256") != digest(canonical(chosen))
            or row.get("original_bill_evidence") != chosen["bill_context"]
            or row.get("source_bill_evidence_sha256") != digest(canonical(chosen["bill_context"]))
            or row.get("input_basis") != "retained_native_text"
            or row.get("review_split") != "challenge"
            or not row["text"].strip()
            or len(row["text"]) > manifest["max_characters"]
        ):
            raise ValueError("record identity/text/provenance mismatch")
        expected = sorted(
            key for key, alt in by_view.items() if alt["bill_id"] == row["bill_id"]
        )
        if row.get("alternative_view_ids") != expected:
            raise ValueError("missing/extra preserved alternatives")
        if any(by_view[key]["bill_context"] != chosen["bill_context"] for key in expected):
            raise ValueError("alternative bill context mismatch")
        used.update(expected)
    if used != by_view.keys() or manifest.get("n_selected") != len(records):
        raise ValueError("frozen coverage mismatch")
    sampling = strict_json((root / "sampling_manifest.json").read_bytes())
    if (
        set(sampling.get("states", {})) != set(STATES)
        or sampling.get("n_selected") != len(records)
        or any(sampling["states"][state]["selected"] != sum(
            row["state"] == state for row in records
        ) for state in STATES)
    ):
        raise ValueError("all-50 sampling accounting mismatch")
    return manifest, records, alternatives


def make_ui_data(root: Path, records: list[dict]) -> dict:
    raw_alternatives = {}
    for raw in (root / "selected_alternative_views.jsonl").read_bytes().split(b"\n"):
        if raw.strip():
            row = strict_json(raw)
            raw_alternatives[view_key(row)] = raw.decode("utf-8")
    topics = load_topics(root / "topics.yml")
    if len(topics) != 21:
        raise ValueError("complete 21-topic rubric required")
    return {
        "notice": NOTICE,
        "topics": [{"code": t.code, "name": t.name, "description": t.description} for t in topics],
        "abstentions": sorted(ABSTENTIONS),
        "states": strict_json((root / "sampling_manifest.json").read_bytes())["states"],
        "records": [{
            "record_id": row["record_id"], "input_sha256": row["input_sha256"],
            "state": row["state"], "bill_id": row["bill_id"], "text": row["text"],
            "alternatives": [{
                "view_id": key, "text": strict_json(raw_alternatives[key])["text"],
                "raw_provenance": raw_alternatives[key],
            } for key in row["alternative_view_ids"]],
        } for row in records],
    }


def build(frozen: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("refusing overwrite")
    manifest, records, _ = frozen_inputs(frozen)
    names = sorted([*manifest["frozen_artifacts"], "source_manifest.json"])
    before = {name: binding(frozen / name) for name in names}
    ui_data = make_ui_data(frozen, records)
    output.mkdir(parents=True)
    source = output / "complete-inputs"
    source.mkdir()
    for name in names:
        shutil.copyfile(frozen / name, source / name)
        assert_binding(source / name, before[name])
    if before != {name: binding(frozen / name) for name in names}:
        raise ValueError("frozen source changed during build")
    assets = Path(__file__).resolve().parents[3] / "web"
    for suffix in ("html", "js", "css"):
        shutil.copyfile(assets / f"human-review.{suffix}", output / f"human-review.{suffix}")
    write_json(output / "ui-data.json", ui_data)
    with zipfile.ZipFile(output / "complete-inputs.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(source / name, f"complete-inputs/{name}")
    result = {
        "schema": SCHEMA, "status": "local_only_unpublished_unannotated",
        "packet_id": digest(canonical(before)),
        "source_manifest_sha256": before["source_manifest.json"]["sha256"],
        "n_selected": len(records), "states_accounted_for": 50, "notice": NOTICE,
        "complete_inputs": before, "ui_data": binding(output / "ui-data.json"),
        "complete_inputs_zip": binding(output / "complete-inputs.zip"),
        "assets": {f"human-review.{s}": binding(output / f"human-review.{s}")
                   for s in ("html", "js", "css")},
        **dict.fromkeys(FLAGS, False),
    }
    write_json(output / "human_packet_manifest.json", result)
    return result


def load_packet(root: Path) -> tuple[dict, list[dict]]:
    manifest = strict_json((root / "human_packet_manifest.json").read_bytes())
    if (
        not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA
        or manifest.get("status") != "local_only_unpublished_unannotated"
        or any(manifest.get(flag) is not False for flag in FLAGS)
    ):
        raise ValueError("invalid human packet")
    sources = manifest["complete_inputs"]
    if manifest["packet_id"] != digest(canonical(sources)):
        raise ValueError("packet binding mismatch")
    for name, expected in sources.items():
        assert_binding(root / "complete-inputs" / safe_name(name), expected)
    frozen, records, _ = frozen_inputs(root / "complete-inputs")
    if set(sources) != set(frozen["frozen_artifacts"]) | {"source_manifest.json"}:
        raise ValueError("complete input inventory mismatch")
    if manifest["source_manifest_sha256"] != sources["source_manifest.json"]["sha256"]:
        raise ValueError("source manifest binding mismatch")
    if manifest["n_selected"] != len(records) or manifest["states_accounted_for"] != 50:
        raise ValueError("human packet coverage mismatch")
    assert_binding(root / "ui-data.json", manifest["ui_data"])
    if strict_json((root / "ui-data.json").read_bytes()) != make_ui_data(
        root / "complete-inputs", records,
    ):
        raise ValueError("UI does not match frozen sources")
    assert_binding(root / "complete-inputs.zip", manifest["complete_inputs_zip"])
    with zipfile.ZipFile(root / "complete-inputs.zip") as archive:
        expected_names = {f"complete-inputs/{name}" for name in sources}
        if (
            len(archive.namelist()) != len(expected_names)
            or set(archive.namelist()) != expected_names
        ):
            raise ValueError("complete archive inventory mismatch")
        for name in sources:
            if archive.read(f"complete-inputs/{name}") != (
                root / "complete-inputs" / name
            ).read_bytes():
                raise ValueError("complete archive bytes mismatch")
    for name, expected in manifest["assets"].items():
        assert_binding(root / safe_name(name), expected)
    return manifest, records


def validate_annotation(root: Path, annotation: dict) -> tuple[dict, list[dict]]:
    manifest, records = load_packet(root)
    if not isinstance(annotation, dict) or set(annotation) != ENVELOPE_FIELDS:
        raise ValueError("invalid annotation envelope")
    if (
        annotation["schema"] != SCHEMA
        or annotation["packet_id"] != manifest["packet_id"]
        or annotation["source_manifest_sha256"] != manifest["source_manifest_sha256"]
    ):
        raise ValueError("foreign packet/source binding")
    reviewer = annotation["reviewer_id"]
    if not isinstance(reviewer, str) or not REVIEWER.fullmatch(reviewer):
        raise ValueError("pseudonymous reviewer ID required")
    if (
        annotation["human_provenance"] != ATTESTATION
        or annotation["all_records_reviewed_in_full"] is not True
        or annotation["no_model_assistance"] is not True
    ):
        raise ValueError("explicit SELF-ATTESTED full-review/no-model attestations required")
    decisions = annotation["decisions"]
    if not isinstance(decisions, list) or not records or len(decisions) != len(records):
        raise ValueError("missing/extra decisions or no eligible records")
    expected = {row["record_id"]: row for row in records}
    codes = {t.code for t in load_topics(root / "complete-inputs/topics.yml")}
    seen = set()
    for row in decisions:
        if not isinstance(row, dict) or set(row) != DECISION_FIELDS:
            raise ValueError("invalid decision schema")
        key = row["record_id"]
        if not isinstance(key, str) or key not in expected or key in seen:
            raise ValueError("duplicate/missing/extra record identity")
        seen.add(key)
        original = expected[key]
        if row["input_sha256"] != original["input_sha256"]:
            raise ValueError("wrong input hash")
        topic, reason = row["topic"], row["abstention_reason"]
        if (topic is not None and (type(topic) is not int or topic not in codes)) or (
            topic is None and (not isinstance(reason, str) or reason not in ABSTENTIONS)
        ) or (topic is not None and reason is not None):
            raise ValueError("invalid topic/abstention pairing")
        if (
            row["reviewer_id"] != reviewer or row["reviewer_type"] != "human_self_attested"
            or row["input_reviewed_in_full"] is not True
            or row["input_only_no_external_context"] is not True
            or not isinstance(row["rationale"], str) or len(row["rationale"].strip()) < 20
        ):
            raise ValueError("invalid full-review provenance/rationale")
        reviewed_on = row["reviewed_on"]
        try:
            if (
                not isinstance(reviewed_on, str)
                or date.fromisoformat(reviewed_on).isoformat() != reviewed_on
                or date.fromisoformat(reviewed_on) > date.today()
            ):
                raise ValueError("invalid reviewed_on date")
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid reviewed_on date") from exc
        spans = row["evidence_spans"]
        if not isinstance(spans, list) or not spans or any(
            not isinstance(span, str) or not span.strip() or span not in original["text"]
            for span in spans
        ):
            raise ValueError("exact nonempty chosen-input evidence spans required")
    if seen != expected.keys():
        raise ValueError("missing/extra records")
    return manifest, records


def import_annotation(root: Path, annotations: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("refusing overwrite")
    raw = annotations.read_bytes()
    manifest, records = validate_annotation(root, strict_json(raw))
    output.mkdir(parents=True)
    for name in (
        "complete-inputs", "complete-inputs.zip", "human_packet_manifest.json",
        "ui-data.json", "human-review.html", "human-review.js", "human-review.css",
    ):
        if (root / name).is_dir():
            shutil.copytree(root / name, output / name)
        else:
            shutil.copyfile(root / name, output / name)
    (output / "annotations-only.json").write_bytes(raw)
    annotation = strict_json(raw)
    write_jsonl(output / "decisions-only.jsonl", annotation["decisions"])
    receipt = {
        "schema": SCHEMA, "status": "validated_self_attested_annotations_not_gold_or_training",
        "packet_id": manifest["packet_id"], "n_decisions": len(records),
        "human_provenance": ATTESTATION,
        "annotations_only": binding(output / "annotations-only.json"),
        "decisions_only": binding(output / "decisions-only.jsonl"),
        "complete_inputs": manifest["complete_inputs"], "notice": NOTICE,
        **dict.fromkeys(FLAGS, False),
    }
    load_packet(output)
    validate_annotation(output, strict_json((output / "annotations-only.json").read_bytes()))
    write_json(output / "import_receipt.json", receipt)
    return receipt


def compare(root: Path, first: Path, second: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("refusing overwrite")
    a, b = (strict_json(path.read_bytes()) for path in (first, second))
    manifest, records = validate_annotation(root, a)
    validate_annotation(root, b)
    # The existing comparer only accepts its historical assistant/date schema.
    # This in-memory structural adapter does NOT assert assistant execution or
    # independence. Never persist its merged labels or provenance.
    def adapter(annotation):
        return [{**row, "reviewer_type": "assistant", "reviewed_on": "2026-10-21"}
                for row in annotation["decisions"]]

    _, audit = compare_reviews(
        records, adapter(a), adapter(b),
        [topic.code for topic in load_topics(root / "complete-inputs/topics.yml")],
    )
    report = {
        key: value for key, value in audit.items() if key not in ("all_original_reviews",)
    }
    report.update({
        "schema": SCHEMA, "packet_id": manifest["packet_id"],
        "status": "self_attested_comparison_not_identity_or_independence_certification",
        "all_original_reviews": {"a": a, "b": b},
        "human_provenance": ATTESTATION, **dict.fromkeys(FLAGS, False),
    })
    write_json(output, report)
    return report


def _model_evidence(checkpoint: Path, training: Path, packet: Path) -> dict:
    from .modernbert import (
        INPUT_CONSTRUCTION,
        MODEL_ID,
        MODEL_REVISION,
        WINDOWING,
        checked_output_codes,
    )

    taxonomy = packet / "complete-inputs/topics.yml"
    codes = [topic.code for topic in load_topics(taxonomy)]
    path = checkpoint / "training_manifest.json"
    manifest = strict_json(path.read_bytes())
    files = manifest.get("checkpoint_files", {})
    construction = manifest.get("input", {})
    if (
        manifest.get("model_id") != MODEL_ID or manifest.get("base_revision") != MODEL_REVISION
        or manifest.get("status") != "provisional" or manifest.get("schema_version") != 2
        or manifest.get("taxonomy_sha256") != binding(taxonomy)["sha256"]
        or manifest.get("topic_codes") != codes
        or manifest.get("labels_sha256") != binding(training)["sha256"]
        or manifest.get("decision") != POLICY
        or construction.get("construction") != INPUT_CONSTRUCTION
        or construction.get("windowing") != WINDOWING
        or type(construction.get("max_tokens")) is not int
        or not 32 <= construction["max_tokens"] <= 8192
        or type(construction.get("overlap")) is not int
        or not 0 <= construction["overlap"] < construction["max_tokens"] - 16
        or manifest.get("complete_document_coverage", {}).get("n_discarded_source_tokens") != 0
        or not isinstance(files, dict)
        or not {"model.safetensors", "config.json", "tokenizer.json",
                "tokenizer_config.json"} <= files.keys()
    ):
        raise ValueError("model/training/taxonomy/full-coverage policy differs from fixed plan")
    if checked_output_codes(codes, manifest.get("output_codes")) != [*codes, None]:
        raise ValueError("planned rejection-output mapping required")
    rows = load_examples(training, codes)
    if not any(row["split"] == "train" for row in rows):
        raise ValueError("original complete training evidence has no training rows")
    _, records = load_packet(packet)
    reserve = Reservation(rows)
    _, _, alternatives = frozen_inputs(packet / "complete-inputs")
    if any(reserve.overlap(row) for row in alternatives):
        raise ValueError("training/source reservation overlap with human packet")
    validate_split_isolation([
        *rows, *({**row, "split": "challenge", "domain": "bill",
                  "label_origin": "reviewed_target"} for row in records),
    ])
    original = {str(path.resolve()): binding(path), str(training.resolve()): binding(training)}
    for name, expected in files.items():
        candidate = checkpoint / safe_name(name)
        actual = binding(candidate)
        if actual["sha256"] != expected:
            raise ValueError(f"changed checkpoint file: {name}")
        original[str(candidate.resolve())] = actual
    return {
        "checkpoint": str(checkpoint.resolve()), "training_labels": str(training.resolve()),
        "original_bindings": original, "training_manifest_sha256": binding(path)["sha256"],
        "training_labels_sha256": binding(training)["sha256"], "input": construction,
        "output_codes": manifest["output_codes"],
        "training_unit_policy": manifest.get("training_unit_policy"),
        "complete_document_coverage": manifest["complete_document_coverage"],
        "decision_status": manifest.get("decision_status"),
    }


def freeze_evaluation_plan(
    packet: Path, output: Path, models: list[tuple[str, Path, Path]], *, raters: int = 2,
) -> dict:
    """Snapshot a pre-annotation plan; hash models without loading or running them."""
    if output.exists():
        raise FileExistsError("refusing overwrite of frozen evaluation plan")
    if type(raters) is not int or raters not in (1, 2) or not models:
        raise ValueError("one/two predeclared raters and explicit fixed models required")
    manifest, records = load_packet(packet)
    if not records or any((packet / name).exists() for name in (
        "annotations-only.json", "decisions-only.jsonl", "import_receipt.json",
    )):
        raise ValueError("freeze plan before annotations on an unannotated nonempty packet")
    aliases = [alias for alias, _, _ in models]
    if len(set(aliases)) != len(aliases) or any(
        not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", alias) for alias in aliases
    ):
        raise ValueError("unique safe model aliases required")
    evidence = {alias: _model_evidence(checkpoint, training, packet)
                for alias, checkpoint, training in models}
    output.mkdir(parents=True)
    shutil.copytree(packet, output / "packet")
    write_json(output / "policy.json", POLICY)
    code = Path(__file__).resolve().parent
    for name in ("human_review.py", "train_topics.py", "evaluate_topics.py",
                 "modernbert.py", "taxonomy.py"):
        destination = output / "code" / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(code / name, destination)
    for alias, model in evidence.items():
        destination = output / "models" / alias
        destination.mkdir(parents=True)
        shutil.copyfile(model["training_labels"], destination / "training-labels.jsonl")
        for original, expected in model["original_bindings"].items():
            source = Path(original)
            assert_binding(source, expected)
            if source.name != "model.safetensors" and original != model["training_labels"]:
                shutil.copyfile(source, destination / source.name)
        model["training_snapshot"] = f"models/{alias}/training-labels.jsonl"
        model["manifest_snapshot"] = f"models/{alias}/training_manifest.json"
    artifacts = {p.relative_to(output).as_posix(): binding(p)
                 for p in sorted(output.rglob("*")) if p.is_file()}
    plan = {
        "schema": EVALUATION_SCHEMA, "status": "frozen_before_human_annotations_no_predictions",
        "created_at": datetime.now(UTC).isoformat(),
        "packet_id": manifest["packet_id"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "taxonomy_sha256": manifest["complete_inputs"]["topics.yml"]["sha256"],
        "raters": raters, "models": evidence, "decision": POLICY,
        "inference": {"strict_inference_unchanged": True, "full_token_coverage": True,
                      "n_discarded_tokens": 0, "calibration": None},
        "primary": "agreed_resolved_only" if raters == 2 else "single_rater_resolved_only",
        "primary_excluded_reasons": list(PRIMARY_EXCLUDED_REASONS),
        "sensitivities": ["review_a_all", "review_b_all"] if raters == 2 else ["review_a_all"],
        "disagreements": "preserve both exact envelopes; no winner; never primary",
        "model_comparison": (
            "report all predeclared models; no result-dependent model/threshold choice"
        ),
        "human_provenance": ATTESTATION, "artifacts": artifacts,
        "evaluation_only": True, **dict.fromkeys(FLAGS, False),
    }
    for model in evidence.values():
        for original, expected in model["original_bindings"].items():
            assert_binding(Path(original), expected)
    write_json(output / "evaluation_plan.json", plan)
    return plan


def load_evaluation_plan(root: Path) -> dict:
    plan = strict_json((root / "evaluation_plan.json").read_bytes())
    if (
        plan.get("schema") != EVALUATION_SCHEMA
        or plan.get("status") != "frozen_before_human_annotations_no_predictions"
        or plan.get("decision") != POLICY
        or type(plan.get("raters")) is not int or plan["raters"] not in (1, 2)
        or plan.get("primary_excluded_reasons") != list(PRIMARY_EXCLUDED_REASONS)
        or plan.get("human_provenance") != ATTESTATION
        or plan.get("evaluation_only") is not True
        or any(plan.get(flag) is not False for flag in FLAGS)
    ):
        raise ValueError("invalid frozen advisory evaluation plan/policy")
    for name, expected in plan["artifacts"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("unsafe plan artifact")
        assert_binding(path, expected)
    for model in plan["models"].values():
        for original, expected in model["original_bindings"].items():
            assert_binding(Path(original), expected)
    for name in ("human_review.py", "train_topics.py", "evaluate_topics.py",
                 "modernbert.py", "taxonomy.py"):
        assert_binding(Path(__file__).resolve().parent / name, plan["artifacts"][f"code/{name}"])
    manifest, _ = load_packet(root / "packet")
    if (
        manifest["packet_id"] != plan["packet_id"]
        or manifest["source_manifest_sha256"] != plan["source_manifest_sha256"]
        or manifest["complete_inputs"]["topics.yml"]["sha256"] != plan["taxonomy_sha256"]
    ):
        raise ValueError("foreign packet/source/taxonomy in frozen evaluation plan")
    return plan


def _reference_sets(plan: dict, records: list[dict], annotations: dict):
    decisions = {key: {row["record_id"]: row for row in annotation["decisions"]}
                 for key, annotation in annotations.items()}
    agreed = [
        row["record_id"] for row in records if plan["raters"] == 1 or all(
            decisions["a"][row["record_id"]][field] == decisions["b"][row["record_id"]][field]
            for field in ("topic", "abstention_reason")
        )
    ]
    primary = [key for key in agreed
               if decisions["a"][key]["abstention_reason"] not in PRIMARY_EXCLUDED_REASONS]
    roles = {"primary": ("a", primary),
             **{f"sensitivity_review_{key}_all": (key, [r["record_id"] for r in records])
                for key in decisions}}
    return decisions, agreed, primary, roles


def _reference_rows(plan, plan_binding, records, decisions, annotation_bindings, role, selection):
    review, selected = selection
    return [{
        **original, **decisions[review][original["record_id"]],
        "split": "challenge", "domain": "bill", "text_sha256": original["input_sha256"],
        "source_url": f"urn:state-politics:human-evaluation:{original['input_sha256']}",
        "label_origin": "reviewed_target", "label_version": EVALUATION_SCHEMA,
        "evidence_tier": "self_attested_human_advisory_evaluation_not_gold",
        "evaluation_reference_schema": EVALUATION_SCHEMA,
        "evaluation_role": role, "evaluation_only": True,
        "human_provenance": ATTESTATION, "human_packet_id": plan["packet_id"],
        "evaluation_plan": plan_binding, "original_annotation_bindings": annotation_bindings,
        "original_human_reviews": {r: decisions[r][original["record_id"]] for r in decisions},
        "reference_basis": "identical explicit verdicts only" if role == "primary"
        and plan["raters"] == 2 else "unmodified self-attested individual review",
        **dict.fromkeys(FLAGS, False),
    } for original in records if original["record_id"] in selected]


def export_references(plan_root: Path, first: Path, output: Path, second: Path | None = None):
    """Export reviewed references, not canonical labels, after complete validation."""
    if output.exists():
        raise FileExistsError("refusing overwrite of advisory evaluation references")
    plan = load_evaluation_plan(plan_root)
    if (second is not None) != (plan["raters"] == 2):
        raise ValueError("complete annotations for the predeclared number of raters required")
    packet = plan_root / "packet"
    paths = {"a": first, **({"b": second} if second is not None else {})}
    raw = {key: path.read_bytes() for key, path in paths.items()}
    annotations = {key: strict_json(value) for key, value in raw.items()}
    for annotation in annotations.values():
        validate_annotation(packet, annotation)
    if second and annotations["a"]["reviewer_id"] == annotations["b"]["reviewer_id"]:
        raise ValueError(
            "two distinct self-attested pseudonyms required, not certified independence"
        )
    _, records = load_packet(packet)
    # Repeat reservations at the admission boundary, including all source alternatives.
    for model in plan["models"].values():
        _model_evidence(Path(model["checkpoint"]), Path(model["training_labels"]), packet)
    decisions, agreed, primary, roles = _reference_sets(plan, records, annotations)
    output.mkdir(parents=True)
    for key, value in raw.items():
        (output / f"review-{key}-annotations-only.json").write_bytes(value)
    if second:
        compare(packet, first, second, output / "self-attested-comparison.json")
    annotation_bindings = {key: binding(output / f"review-{key}-annotations-only.json")
                           for key in raw}
    reference_files = {}
    plan_binding = binding(plan_root / "evaluation_plan.json")
    for role, selection in roles.items():
        rows = _reference_rows(
            plan, plan_binding, records, decisions, annotation_bindings, role, selection,
        )
        name = f"{role}-advisory-evaluation-references.jsonl"
        write_jsonl(output / name, rows)
        if rows:
            codes = [t.code for t in load_topics(packet / "complete-inputs/topics.yml")]
            loaded = load_examples(output / name, codes)
            for model in plan["models"].values():
                validate_split_isolation([
                    *load_examples(plan_root / model["training_snapshot"], codes), *loaded,
                ])
        reference_files[role] = {"file": name, "n_references": len(rows), **binding(output / name)}
    result = {
        "schema": EVALUATION_SCHEMA,
        "status": "advisory_evaluation_references_not_gold_or_training",
        "packet_id": plan["packet_id"], "plan_root": str(plan_root.resolve()),
        "evaluation_plan": binding(plan_root / "evaluation_plan.json"),
        "original_annotation_bindings": annotation_bindings,
        "reference_files": reference_files, "n_primary": len(primary),
        "agreed_record_ids": agreed,
        "disputed_record_ids": [r["record_id"] for r in records if r["record_id"] not in agreed],
        "agreed_unresolved_excluded_from_primary": [key for key in agreed if key not in primary],
        "comparison": binding(output / "self-attested-comparison.json") if second else None,
        "human_provenance": ATTESTATION, "evaluation_only": True, **dict.fromkeys(FLAGS, False),
    }
    write_json(output / "evaluation_reference_manifest.json", result)
    return result


def score_references(
    references: Path, model_alias: str, role: str, predictions: Path, output: Path,
):
    """Strict provenance wrapper; all scores come from the existing evaluate_topics CLI."""
    from . import evaluate_topics

    if output.exists():
        raise FileExistsError("refusing overwrite of advisory evaluation report")
    receipt = strict_json((references / "evaluation_reference_manifest.json").read_bytes())
    plan_root = Path(receipt["plan_root"])
    plan = load_evaluation_plan(plan_root)
    assert_binding(plan_root / "evaluation_plan.json", receipt["evaluation_plan"])
    if (
        receipt.get("schema") != EVALUATION_SCHEMA or receipt.get("packet_id") != plan["packet_id"]
        or receipt.get("human_provenance") != ATTESTATION
        or receipt.get("evaluation_only") is not True
        or any(receipt.get(flag) is not False for flag in FLAGS)
        or set(receipt["original_annotation_bindings"]) != (
            {"a", "b"} if plan["raters"] == 2 else {"a"}
        )
    ):
        raise ValueError("invalid advisory reference manifest/provenance")
    if model_alias not in plan["models"] or role not in receipt["reference_files"]:
        raise ValueError("model/role not predeclared")
    reference = receipt["reference_files"][role]
    if not reference["n_references"]:
        raise ValueError("no eligible references for this predeclared role; no score fabricated")
    path = references / safe_name(reference["file"])
    assert_binding(path, reference)
    annotations = {}
    for key, expected in receipt["original_annotation_bindings"].items():
        annotation_path = references / f"review-{safe_name(key)}-annotations-only.json"
        assert_binding(annotation_path, expected)
        annotations[key] = strict_json(annotation_path.read_bytes())
        validate_annotation(plan_root / "packet", annotations[key])
    if plan["raters"] == 2:
        if annotations["a"]["reviewer_id"] == annotations["b"]["reviewer_id"]:
            raise ValueError("two distinct self-attested pseudonyms required")
        assert_binding(references / "self-attested-comparison.json", receipt["comparison"])
    _, records = load_packet(plan_root / "packet")
    decisions, _, _, roles = _reference_sets(plan, records, annotations)
    if set(receipt["reference_files"]) != set(roles):
        raise ValueError("missing/extra predeclared reference roles")
    for name, selection in roles.items():
        description = receipt["reference_files"][name]
        reference_path = references / safe_name(description["file"])
        assert_binding(reference_path, description)
        expected = _reference_rows(
            plan, receipt["evaluation_plan"], records, decisions,
            receipt["original_annotation_bindings"], name, selection,
        )
        if json_lines(reference_path) != expected or description["n_references"] != len(expected):
            raise ValueError("references differ from exact annotations/predeclared subset")
    model = plan["models"][model_alias]
    for row in json_lines(predictions):
        if (
            row.get("model_run") != model["training_manifest_sha256"]
            or row.get("base_model_run") != model["training_manifest_sha256"]
            or row.get("taxonomy_sha256") != plan["taxonomy_sha256"]
            or row.get("calibration_sha256") is not None
            or type(row.get("n_discarded_tokens")) is not int or row["n_discarded_tokens"] != 0
            or type(row.get("n_input_tokens")) is not int or row["n_input_tokens"] < 1
        ):
            raise ValueError(
                "prediction model/policy/full-token-coverage provenance differs from plan"
            )
    command = [
        "--labels", str(path), "--training-manifest", str(plan_root / model["manifest_snapshot"]),
        "--training-labels", str(plan_root / model["training_snapshot"]),
        "--predictions", str(predictions),
        "--topics", str(plan_root / "packet/complete-inputs/topics.yml"),
        "--split", "challenge", "--policy", str(plan_root / "policy.json"), "--out", str(output),
    ]
    evaluate_topics.main(command)
    report = strict_json(output.read_bytes())
    report.update(evaluation_only=True, **dict.fromkeys(FLAGS, False))
    report["human_evaluation_context"] = {
        "status": "self_attested_advisory_evaluation_not_gold",
        "role": role, "human_provenance": ATTESTATION,
        "evaluation_reference_manifest": binding(references / "evaluation_reference_manifest.json"),
        "evaluation_plan": receipt["evaluation_plan"],
        "original_annotation_bindings": receipt["original_annotation_bindings"],
        "identity_and_independence": "self-attested, not certified",
        "historical_metric_key_notice": "gold_abstention_count is not a gold-status claim",
        "existing_evaluator_invocation": shlex.join([
            sys.executable, "-m", "state_politics.analysis.evaluate_topics", *command,
        ]),
        "evaluation_only": True, **dict.fromkeys(FLAGS, False),
    }
    write_json(output, report)
    return {
        "status": "evaluated_self_attested_advisory_not_gold", "n_primary": receipt["n_primary"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=(
        "build", "validate", "import", "compare", "freeze-evaluation-plan",
        "export-references", "score-references",
    ))
    parser.add_argument("--frozen", type=Path)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--review-b", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--model", nargs=3, action="append", default=[],
                        metavar=("ALIAS", "CHECKPOINT", "TRAINING_LABELS"))
    parser.add_argument("--raters", type=int, choices=(1, 2), default=2)
    parser.add_argument("--references", type=Path)
    parser.add_argument("--model-alias")
    parser.add_argument("--role", default="primary")
    parser.add_argument("--predictions", type=Path)
    args = parser.parse_args()
    if args.action == "build" and args.frozen and args.output:
        result = build(args.frozen, args.output)
    elif args.action == "validate" and args.packet and args.annotations:
        manifest, records = validate_annotation(
            args.packet, strict_json(args.annotations.read_bytes()),
        )
        result = {"packet_id": manifest["packet_id"], "validated_decisions": len(records)}
    elif args.action == "import" and args.packet and args.annotations and args.output:
        result = import_annotation(args.packet, args.annotations, args.output)
    elif args.action == "compare" and all((
        args.packet, args.annotations, args.review_b, args.output,
    )):
        result = compare(args.packet, args.annotations, args.review_b, args.output)
    elif args.action == "freeze-evaluation-plan" and args.packet and args.output:
        result = freeze_evaluation_plan(args.packet, args.output, [
            (alias, Path(checkpoint), Path(training)) for alias, checkpoint, training in args.model
        ], raters=args.raters)
    elif args.action == "export-references" and args.plan and args.annotations and args.output:
        result = export_references(args.plan, args.annotations, args.output, args.review_b)
    elif args.action == "score-references" and all((
        args.references, args.model_alias, args.predictions, args.output,
    )):
        result = score_references(
            args.references, args.model_alias, args.role, args.predictions, args.output,
        )
    else:
        parser.error("required paths missing; see action and --help")
    print(json.dumps({key: result[key] for key in (
        "status", "packet_id", "n_selected", "n_decisions", "validated_decisions",
        "n_agreed", "n_disputed", "n_primary",
    ) if key in result}))


if __name__ == "__main__":
    main()

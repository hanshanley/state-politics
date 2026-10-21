"""Local model-blind human review: build, validate/import, and compare.

Build only from ``prepare_native_review freeze`` output. Serve the resulting
directory on 127.0.0.1, never publish it. Imported annotations are self-attestations,
not verified identities, canonical training labels, human gold, or model approval.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from datetime import date
from pathlib import Path

from .prepare_cycle_review import (
    ABSTENTIONS,
    FALSE_FLAGS,
    STATES,
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "validate", "import", "compare"))
    parser.add_argument("--frozen", type=Path)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--review-b", type=Path)
    parser.add_argument("--output", type=Path)
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
    else:
        parser.error("required paths missing; see action and --help")
    print(json.dumps({key: result[key] for key in (
        "status", "packet_id", "n_selected", "n_decisions", "validated_decisions",
        "n_agreed", "n_disputed",
    ) if key in result}))


if __name__ == "__main__":
    main()

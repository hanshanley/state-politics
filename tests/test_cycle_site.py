"""Evidence-only mode retains original source strings and never promotes candidate admission."""

import gzip
import hashlib
import json
import os
import runpy
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as csv
import pyarrow.parquet as pq
import pytest
import yaml

from state_politics.bills.study_native_overlap import normalize_packet
from state_politics.provenance import sha256_file
from state_politics.site_evidence import (
    COHORTS,
    ORGANIZATIONS,
    ROOT,
    STATES,
    _scalar_source,
    build_cycle_preview,
)

SOURCE_TEXT = (
    'literal <script>window.EVIDENCE_INJECTED=true</script>'
    ' <img src=x onerror="window.EVIDENCE_INJECTED=true"> "quoted phrase"'
    "\u2028\u2029\nFull source ending; never truncated."
)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def write_jsonl(path, rows):
    path.write_text("".join(
        json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows
    ), encoding="utf-8")


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def repin(bundle, *, platform=False):
    manifest = json.loads((bundle / "manifest.json").read_text())
    if platform:
        manifest["files"] = {
            name: sha256_file(bundle / name) for name in ("records.jsonl", "organizations.jsonl")
        }
    else:
        manifest["artifacts"] = {
            name: {"sha256": sha256_file(bundle / name), "bytes": (bundle / name).stat().st_size}
            for name in (
                "report.json", "state_matrix.csv", "bill_evidence.parquet",
                "abstract_evidence.parquet", "candidate_metadata_views.parquet",
            )
        }
    write_json(bundle / "manifest.json", manifest)


@pytest.fixture
def cycle_bundle(tmp_path):
    metadata, platform = tmp_path / "metadata", tmp_path / "platform"
    metadata.mkdir()
    platform.mkdir()
    contexts, abstracts, views = [], [], []
    for index in range(14):
        state = "TX" if index < 12 else "CA" if index == 12 else "MA"
        context = {
            "bill_id": f"bill:{index}", "state": state, "identifier": f"HB {index}",
            "session_identifier": "2023", "title": f"{SOURCE_TEXT} title {index}",
            "cohort_scope": COHORTS[0 if index < 12 else index - 11],
            "n_indexed_native_views": None if state == "MA" else int(state == "CA"),
            "n_nonempty_abstract_records": 2 if index == 0 else 0,
            "n_distinct_abstract_texts": 2 if index == 0 else 0,
            "source_introduction_date": "", "source_filing_date": "2023-02-01",
            "native_introduction_date": None,
            "model_input_approved": False, "filing_time_text_certified": False,
            "analytical_admission": False,
        }
        contexts.append(context)
        for variant in range(2 if index == 0 else 1):
            abstract = None
            if index == 0:
                text = f"{SOURCE_TEXT} variant {variant}"
                abstract = {
                    "id": f"abstract:{variant}", "bill_id": context["bill_id"], "state": state,
                    "abstract": text, "note": f"{SOURCE_TEXT} note {variant}",
                    "abstract_sha256": digest(text),
                }
                abstracts.append(abstract)
            text = context["title"] + ("\n\n" + abstract["abstract"] if abstract else "")
            views.append({
                **{key: context[key] for key in (
                    "state", "identifier", "bill_id", "title", "session_identifier", "cohort_scope",
                )},
                "view_id": f"view:{index}:{variant}",
                "abstract_id": abstract["id"] if abstract else None,
                "abstract": abstract["abstract"] if abstract else None,
                "abstract_note": abstract["note"] if abstract else None, "text": text,
                "input_sha256": digest(text), "n_input_characters": len(text),
                "metadata_tier": "retained_abstract_unaligned" if abstract else "title_only",
                "multiple_abstract_variants": index == 0, "n_input_tokens": None,
                "n_discarded_tokens": None, "chunking_status": "not_tokenized",
                "model_input_approved": False, "filing_time_text_certified": False,
                "training_admission": False, "analytical_admission": False,
            })
    for name, rows in (
        ("bill_evidence", contexts), ("abstract_evidence", abstracts),
        ("candidate_metadata_views", views),
    ):
        pq.write_table(pa.Table.from_pylist(rows), metadata / f"{name}.parquet")
    matrix = []
    for state in sorted(STATES):
        rows = [row for row in contexts if row["state"] == state]
        counts = Counter(row["cohort_scope"] for row in rows)
        matrix.append({
            "state": state, "state_name": f"{state} {SOURCE_TEXT}" if state == "TX" else state,
            "n_retained_contexts_wider_history": 9877 if state == "ME" else len(rows),
            "n_cycle_evidence_candidate_contexts": len(rows),
            "n_filing_or_introduction_in_window": counts[COHORTS[0]],
            "n_native_only_scope_candidates": counts[COHORTS[1]],
            "n_description_only_scope_candidates": counts[COHORTS[2]],
            "n_cycle_metadata_candidate_views": sum(row["state"] == state for row in views),
            "n_cycle_contexts_with_nonempty_abstract": int(state == "TX"),
            "n_cycle_contexts_with_multiple_abstract_variants": int(state == "TX"),
            "n_cycle_contexts_with_indexed_native_text": int(state == "CA")
            if state in ("TX", "CA") else None,
        })
    csv.write_csv(pa.Table.from_pylist(matrix), metadata / "state_matrix.csv")
    write_json(metadata / "report.json", {
        "status": "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted",
        "n_cycle_contexts": 14, "n_cycle_abstract_records": 2,
        "n_metadata_candidate_views_not_bills": 15,
        "n_cycle_contexts_with_nonempty_abstract": 1,
        "n_cycle_contexts_with_multiple_abstract_variants": 1,
        "cohort_scope_counts": dict(Counter(row["cohort_scope"] for row in contexts)),
        "model_input_approved": False, "analytical_admission": False,
    })
    write_json(metadata / "manifest.json", {
        "schema_version": 1,
        "status": "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted",
        "inputs_unchanged": True, "model_input_approved": False, "analytical_admission": False,
    })
    repin(metadata)
    records = []
    for index in range(13):
        text = None if index == 11 else f"{SOURCE_TEXT} platform {index}"
        records.append({
            "record_id": f"record:{index}", "state": "TX" if index < 12 else "US",
            "party": "D", "record_kind": "recovery_capture",
            "extracted_text": text, "text_sha256": digest(text) if text else None,
            "source_sha256": None, "url": "javascript:window.EVIDENCE_INJECTED=true",
            "origin": {"path": "/unserved/original.jsonl", "sha256": "b" * 64},
            "retained_record": {"text": text, "unverified_claim": SOURCE_TEXT},
            "source_path": "/unserved/source.pdf", "advisory_reviews": [],
            "source_observed_dates": [], "retained_metadata_year": None,
            "metadata_year_disposition": "unavailable", "cycle_applicability": "unresolved",
            "operative_platform_status": "unresolved", "analysis_cutoff": None,
            "training_admission": False, "analytical_admission": False,
            "adoption_certified": False, "human_gold": False,
            "cycle_date_dispositions": [
                "source_observed_2023_2024_candidate" if index == 0 else "undated_candidate",
            ],
            **({"organization_scope": "excluded_national_or_other_party"} if index == 12 else {}),
        })
    orgs = []
    for state, party in sorted(ORGANIZATIONS):
        rows = [row for row in records if (row["state"], row["party"]) == (state, party)]
        orgs.append({
            "state": state, "party": party, "name": f"{state} / {party} {SOURCE_TEXT}",
            "n_evidence_records": len(rows),
            "n_retained_nonempty_text_views": sum(bool(row["extracted_text"]) for row in rows),
            "record_kind_counts": dict(Counter(row["record_kind"] for row in rows)),
            "cycle_date_counts": dict(Counter(
                date for row in rows for date in row["cycle_date_dispositions"]
            )),
            "cycle_applicability": "unresolved", "operative_platform_status": "unresolved",
            "training_admission": False, "analytical_admission": False,
        })
    write_jsonl(platform / "records.jsonl", records)
    write_jsonl(platform / "organizations.jsonl", orgs)
    write_json(platform / "manifest.json", {
        "schema": "platform_study_evidence_v1",
        "status": "complete_evidence_inventory_not_scientific_admission",
        "scientific_certification": "not_performed", "analysis_cutoff": None,
        "study_start": "2023-01-01", "study_end": "2024-12-31",
        "n_evidence_records": 13, "n_organization_rows": 100, "expected_organizations": 100,
        "n_historical_outside_organization_scope": 1,
        "record_kind_counts": {"recovery_capture": 13},
        "cycle_date_counts": {"source_observed_2023_2024_candidate": 1, "undated_candidate": 12},
    })
    repin(platform, platform=True)
    return metadata, platform, contexts, abstracts, views, records


def repin_optional(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["artifacts"] = {
        path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in directory.iterdir() if path.name != "manifest.json"
    }
    write_json(directory / "manifest.json", manifest)


def input_pin(path):
    return {"path": str(path), "sha256": sha256_file(path), "size": path.stat().st_size}


@pytest.fixture
def optional_bundle(cycle_bundle, tmp_path):
    metadata, _, contexts, _, views, _ = cycle_bundle
    native = tmp_path / "native"
    native.mkdir()
    specs, overlaps, indexes, inputs = [], [], [], {}
    for profile, packet, state in (
        ("views", "TX", "TX"), ("reader_rows", "CA_readers", "CA"),
        ("single", "CA_alternate_root", "CA"),
    ):
        root = tmp_path / packet
        root.mkdir()
        spec = {
            "state": state, "packet_id": packet, "root": str(root),
            "profile": profile, "contexts": "contexts.parquet",
            "context_id": "native_id", "identifier": "identifier", "bill_id": "bill_id",
            "canonical_session": "2023", "status": "stage",
            "preserve_context_fields": ["negative_flags_json", "native_date_observations_json"],
        }
        if state == "TX":
            spec.update(
                view_reader_allowlist=["retained-reader"],
                source_only={"selector": "stage", "values": ["known-wrong-source-only"]},
            )
        raw, raw_views = [], []
        for number in range(14 if state == "TX" else 2 if profile == "reader_rows" else 1):
            bill_number = number if state == "TX" else 12
            text = (
                f'{SOURCE_TEXT}\nNative complete retained view {packet}/{number}. '
                f'NATIVE-END-{number}'
            )
            identity = f"native:{number if state == 'TX' else 12}"
            row = {
                "native_id": identity, "identifier": f"HB {bill_number}",
                "bill_id": (
                    f"bill:{bill_number}" if state != "TX" or number < 12
                    else "outside-cohort:12" if number == 12 else None
                ),
                "stage": "later-stage retained; introduced semantics unverified",
                "negative_flags_json": '["identity_unverified","INSERT/DELETE_unverified"]',
                "native_date_observations_json": '[{"date":null,"status":"unresolved"}]',
            }
            if state == "TX" and number == 13:
                row.update(
                    identifier="HB 0", bill_id="bill:0", stage="known-wrong-source-only",
                )
            source_view = {
                "record_id": f"native-view:{number}", "text": text,
                "input_sha256": digest(text), "n_input_characters": len(text),
                "filing_time_text_certified": False, "analytical_admission": False,
            }
            if profile == "views":
                raw.append(row)
                raw_views.append({
                    **source_view, "view_id": source_view["record_id"],
                    "context_id": identity, "reader": "retained-reader",
                    "native_date_observation_status": "unresolved",
                    "negative_flags_json": row["negative_flags_json"],
                    "token_ids": [999] * 10,
                })
            else:
                raw.append({**row, **source_view, **(
                    {"reader": f"reader-{number}"} if profile == "reader_rows" else {
                        "input_text": text, "n_body_characters": len(text),
                        "classifier_input_available": True,
                    }
                )})
        if profile == "views":
            spec["views"] = "views.parquet"
            excluded_text = "EXCLUDED MARKUP / ANCILLARY HEADER; NOT A POLICY-TEXT VIEW"
            raw_views.append({
                **raw_views[0], "view_id": "excluded-markup", "reader": "markup",
                "text": excluded_text, "input_sha256": digest(excluded_text),
                "n_input_characters": len(excluded_text),
            })
        elif profile == "single":
            spec.update(
                source_kind="native_html_body", view_character_count="n_body_characters",
                view_available="classifier_input_available",
            )
        pq.write_table(pa.Table.from_pylist(raw), root / "contexts.parquet")
        if raw_views:
            pq.write_table(pa.Table.from_pylist(raw_views), root / "views.parquet")
        write_json(root / "manifest.json", {"files": {
            path.name: sha256_file(path) for path in root.iterdir()
        }})
        spec["manifest_sha256"] = sha256_file(root / "manifest.json")
        raw_table = pq.read_table(root / "contexts.parquet").to_pandas()
        normalized_contexts, normalized_views = normalize_packet(
            spec, raw_table,
            pq.read_table(root / "views.parquet").to_pandas() if raw_views else None,
        )
        spec.update(
            expected_contexts=len(normalized_contexts), expected_views=len(normalized_views),
        )
        specs.append(spec)
        indexes.extend(normalized_views.to_dict("records"))
        for row in pa.Table.from_pandas(normalized_contexts, preserve_index=False).to_pylist():
            declared = row["declared_bill_id"]
            overlaps.append({
                **row,
                "bill_id": None if row["canonical_join_mode"] == "source_only" else declared,
                "identifier": row["native_identifier"],
                "canonical_join_basis": (
                    "source_only_unresolved_identity"
                    if row["canonical_join_mode"] == "source_only"
                    else "declared_bill_id_exact_session_typed_identity"
                ),
                "date_evidence_status": "unresolved_not_a_source_date",
            })
        for role, name in (("manifest", "manifest.json"), ("contexts", "contexts.parquet"),
                           ("views", "views.parquet")):
            if (root / name).exists():
                inputs[f"{packet}_{role}"] = input_pin(root / name)
    registry = tmp_path / "registry.yml"
    registry.write_text(yaml.safe_dump({"schema_version": 1, "packets": specs}))
    inputs["registry"] = input_pin(registry)
    pq.write_table(pa.Table.from_pylist(overlaps), native / "native_context_overlap.parquet")
    pq.write_table(pa.Table.from_pylist(indexes), native / "native_view_index.parquet")
    write_json(native / "report.json", {"analytical_admission": False})
    write_json(native / "manifest.json", {
        "schema_version": 1,
        "status": "complete_supplied_native_overlap_not_native_census_or_analytical_admission",
        "inputs_unchanged": True, "analytical_admission": False, "inputs": inputs,
    })
    repin_optional(native)
    for context in contexts:
        if context["state"] == "TX":
            context["n_indexed_native_views"] = 1
        elif context["state"] == "CA":
            context["n_indexed_native_views"] = 3
    pq.write_table(pa.Table.from_pylist(contexts), metadata / "bill_evidence.parquet")
    matrix = csv.read_csv(metadata / "state_matrix.csv").to_pylist()
    next(row for row in matrix if row["state"] == "TX")[
        "n_cycle_contexts_with_indexed_native_text"
    ] = 12
    csv.write_csv(pa.Table.from_pylist(matrix), metadata / "state_matrix.csv")
    repin(metadata)
    older = tmp_path / "older_metadata_manifest.json"
    shutil.copyfile(metadata / "manifest.json", older)
    manifest = json.loads((metadata / "manifest.json").read_text())
    manifest["inputs"] = {"native_manifest": input_pin(native / "manifest.json")}
    write_json(metadata / "manifest.json", manifest)
    plan = tmp_path / "plan"
    plan.mkdir()
    planned = []
    for index, view in enumerate(views):
        planned.append({
            **{key: view[key] for key in (
                "view_id", "bill_id", "input_sha256", "n_input_characters",
            )},
            "n_input_tokens": 1800 if index == 0 else 20,
            "n_windows": 2 if index == 0 else 1,
            "n_unique_covered_tokens": 1800 if index == 0 else 20,
            "n_overlap_token_positions": 100 if index == 0 else 0,
            "n_discarded_tokens": 0,
            "window_model_input_lengths": [1000, 900] if index == 0 else [26],
            "token_ids": [12345] * 100, "model_input_approved": False,
            "analytical_admission": False,
        })
    pq.write_table(pa.Table.from_pylist(planned), plan / "token_window_plan.parquet")
    write_json(plan / "report.json", {
        "n_views": len(planned), "model_forward_passes": 0, "model_token_budget": 1024,
        **{key: sum(row[key] for row in planned) for key in (
            "n_input_tokens", "n_windows", "n_discarded_tokens",
        )},
        "model_input_approved": False, "analytical_admission": False,
    })
    write_json(plan / "manifest.json", {
        "schema_version": 1,
        "status": "complete_unlabelled_metadata_token_plan_not_inference_or_admission",
        "inputs_unchanged": True, "model_inference_performed": False,
        "model_input_approved": False, "analytical_admission": False,
        "inputs": {
            "evidence_manifest": input_pin(older),
            "views": input_pin(metadata / "candidate_metadata_views.parquet"),
        },
    })
    repin_optional(plan)
    return native, plan


def test_optional_native_full_text_and_verified_token_plan(cycle_bundle, optional_bundle, tmp_path):
    metadata, platform, *_ = cycle_bundle
    native, plan = optional_bundle
    out = tmp_path / "preview"
    manifest = build_cycle_preview(
        metadata, platform, out, native_evidence=native, metadata_token_plan=plan,
    )
    assert manifest["counts"]["native_full_text_candidate_views"] == 15
    assert manifest["counts"]["native_full_text_candidate_contexts"] == 13
    assert manifest["counts"]["metadata_token_plan"]["n_views"] == 15
    tx = [
        json.loads(line) for line in (out / "evidence/native-TX.jsonl").read_text().split("\n")
        if line
    ]
    assert len(tx) == 12
    assert tx[0]["native_context"]["n_excluded_views"] == 1
    assert all(row["view_id"] not in ("excluded-markup", "native-view:13") for row in tx)
    assert all(row["text"].endswith(f"NATIVE-END-{index}") for index, row in enumerate(tx))
    assert all(digest(row["text"]) == row["input_sha256"] for row in tx)
    assert all("INSERT/DELETE_unverified" in row["native_context"]["negative_flags_json"]
               for row in tx)
    assert all(
        row["source_type"] == "native_text" and not row["model_input_approved"] for row in tx
    )
    assert all(row["source_lineage"]["native_manifest_sha256"]
               == sha256_file(native / "manifest.json") for row in tx)
    ca = [
        json.loads(line) for line in (out / "evidence/native-CA.jsonl").read_text().split("\n")
        if line
    ]
    assert len(ca) == 3 and len({row["bill_id"] for row in ca}) == 1
    assert len({row["packet_root"] for row in ca}) == 2
    with gzip.open(out / "downloads/native-TX.jsonl.gz", "rt") as handle:
        assert [json.loads(line) for line in handle] == tx
    bills = [
        json.loads(line) for line in (out / "evidence/bills-TX.jsonl").read_text().split("\n")
        if line
    ]
    assert bills[0]["n_input_tokens"] is None
    assert bills[0]["token_plan"]["n_input_tokens"] == 1800
    assert bills[0]["token_plan"]["n_discarded_tokens"] == 0
    assert "token_ids" not in bills[0]["token_plan"]
    assert all("token_ids" not in row["source_record"] for row in tx)
    lineage = bills[0]["token_plan"]["source_lineage"]
    assert (
        lineage["current_metadata_manifest_sha256"] != lineage["planned_metadata_manifest_sha256"]
    )
    document = (out / "index.html").read_text()
    assert "Verified complete tokenization planning" in document
    assert "15 complete retained native views" in document
    assert document.count('<tr data-state="') == 150
    assert "Native documents are not included" not in document
    assert document.count('href="downloads/native-') == 50


@pytest.mark.parametrize("profile", ["observations", "views"])
def test_zero_view_native_roots_bind_observations_without_materializing_text(
    cycle_bundle, optional_bundle, tmp_path, monkeypatch, profile,
):
    metadata, platform, *_ = cycle_bundle
    native, _ = optional_bundle
    root = tmp_path / "zero-view-packet"
    root.mkdir()
    spec = {
        "state": "CA", "packet_id": "zero_views", "root": str(root), "profile": profile,
        "contexts": "contexts.parquet", "context_id": "native_id", "identifier": "identifier",
        "bill_id": "bill_id", "canonical_session": "2023", "status": "stage",
        "source_only": {"selector": "stage", "values": ["draft-request"]},
        "native_introduction_field": "observed_date",
        "native_introduction_when": [{"selector": "stage", "values": ["formally-introduced"]}],
        "expected_contexts": 2, "expected_views": 0,
    }
    raw = [{
        "native_id": f"observation:{index}", "identifier": "HB 12", "bill_id": "bill:12",
        "stage": "formally-introduced" if index == 0 else "draft-request",
        "observed_date": "2023-04-05" if index == 0 else None,
        "text": "OBSERVATION/ANCILLARY HEADER MUST NOT BE MATERIALIZED AS POLICY TEXT",
    } for index in range(2)]
    pq.write_table(pa.Table.from_pylist(raw), root / "contexts.parquet")
    raw_views = None
    if profile == "views":
        spec.update(views="views.parquet", view_reader_allowlist=["policy-text-reader"])
        text = raw[0]["text"]
        pq.write_table(pa.Table.from_pylist([{
            "view_id": "excluded-ancillary", "context_id": raw[0]["native_id"],
            "reader": "ancillary-header", "input_sha256": digest(text),
            "n_input_characters": len(text), "text": text,
        }]), root / "views.parquet")
        raw_views = pq.read_table(root / "views.parquet").to_pandas()
    write_json(root / "manifest.json", {"files": {
        path.name: sha256_file(path) for path in root.iterdir()
    }})
    spec["manifest_sha256"] = sha256_file(root / "manifest.json")
    contexts, views = normalize_packet(
        spec, pq.read_table(root / "contexts.parquet").to_pandas(), raw_views,
    )
    assert views.empty
    native_manifest = json.loads((native / "manifest.json").read_text())
    registry = Path(native_manifest["inputs"]["registry"]["path"])
    config = yaml.safe_load(registry.read_text())
    config["packets"].append(spec)
    registry.write_text(yaml.safe_dump(config))
    native_manifest["inputs"]["registry"] = input_pin(registry)
    for role, name in (("manifest", "manifest.json"), ("contexts", "contexts.parquet"),
                       ("views", "views.parquet")):
        if (root / name).exists():
            native_manifest["inputs"][f"zero_views_{role}"] = input_pin(root / name)
    path = native / "native_context_overlap.parquet"
    overlaps = pq.read_table(path).to_pylist()
    for row in pa.Table.from_pandas(contexts, preserve_index=False).to_pylist():
        source_only = row["canonical_join_mode"] == "source_only"
        overlaps.append({
            **row, "bill_id": None if source_only else "bill:12",
            "identifier": row["native_identifier"],
            "canonical_join_basis": (
                "source_only_unresolved_identity" if source_only
                else "declared_bill_id_exact_session_typed_identity"
            ),
            "date_evidence_status": row["native_window_disposition"],
        })
    pq.write_table(pa.Table.from_pylist(overlaps), path)
    write_json(native / "manifest.json", native_manifest)
    repin_optional(native)
    metadata_manifest = json.loads((metadata / "manifest.json").read_text())
    metadata_manifest["inputs"]["native_manifest"] = input_pin(native / "manifest.json")
    write_json(metadata / "manifest.json", metadata_manifest)
    projections = []

    def read_projected(path, *, include_text=True):
        result = _scalar_source(path, include_text=include_text)
        if Path(path).parent == root:
            assert include_text is False and "text" not in result.column_names
            projections.append(Path(path).name)
        return result

    monkeypatch.setattr("state_politics.site_evidence._scalar_source", read_projected)
    out = tmp_path / "preview"
    manifest = build_cycle_preview(metadata, platform, out, native_evidence=native)
    assert manifest["counts"]["native_full_text_candidate_views"] == 15
    assert projections == (
        ["contexts.parquet", "views.parquet"] if profile == "views" else ["contexts.parquet"]
    )
    consumed = manifest["inputs"]["native_evidence"]["consumed_source_inputs"]
    assert consumed["zero_views_contexts"] == input_pin(root / "contexts.parquet")
    assert contexts.loc[0, "native_introduction_date"] == "2023-04-05"
    assert contexts.loc[1, "canonical_join_mode"] == "source_only"
    with gzip.open(out / "downloads/native-CA.jsonl.gz", "rt") as handle:
        rows = [json.loads(line) for line in handle]
    assert len(rows) == 3
    assert all(row["packet_root"] != str(root) for row in rows)


def test_native_duplicate_source_flags_are_retained_without_ambiguous_projection(tmp_path):
    path = tmp_path / "duplicate-source-fields.parquet"
    text = SOURCE_TEXT
    table = pa.Table.from_arrays(
        [pa.array([text]), pa.array([False]), pa.array([False]), pa.array([[1, 2, 3]])],
        names=["text", "training_admission", "training_admission", "token_ids"],
    )
    pq.write_table(table, path)
    before = sha256_file(path)
    row = _scalar_source(path).to_pylist()[0]
    assert row["text"] == text
    assert row["training_admission"] is row["training_admission__retained_duplicate_2"] is False
    assert json.loads(row["source_duplicate_columns_json"]) == {
        "training_admission": ["training_admission", "training_admission__retained_duplicate_2"],
    }
    assert "token_ids" not in row
    assert sha256_file(path) == before
    table = table.set_column(2, "training_admission", pa.array([True]))
    pq.write_table(table, path)
    with pytest.raises(ValueError, match="duplicate admission"):
        _scalar_source(path)


def test_native_source_references_keep_all_views_without_inflating_bill_counts(
    cycle_bundle, optional_bundle, tmp_path,
):
    metadata, platform, *_ = cycle_bundle
    native, _ = optional_bundle
    native_manifest = json.loads((native / "manifest.json").read_text())
    registry = Path(native_manifest["inputs"]["registry"]["path"])
    config = yaml.safe_load(registry.read_text())
    spec = config["packets"][0]
    spec["context_granularity"] = "source_reference"
    root = Path(spec["root"])
    path = root / spec["contexts"]
    raw = pq.read_table(path).to_pylist()
    raw[12].update(identifier="HB 0", bill_id="bill:0")
    pq.write_table(pa.Table.from_pylist(raw), path)
    source_manifest = json.loads((root / "manifest.json").read_text())
    source_manifest["files"][path.name] = sha256_file(path)
    write_json(root / "manifest.json", source_manifest)
    spec["manifest_sha256"] = sha256_file(root / "manifest.json")
    registry.write_text(yaml.safe_dump(config))
    for role, target in (("registry", registry), ("TX_contexts", path),
                         ("TX_manifest", root / "manifest.json")):
        native_manifest["inputs"][role] = input_pin(target)
    contexts, _ = normalize_packet(
        spec, pq.read_table(path).to_pandas(), pq.read_table(root / spec["views"]).to_pandas(),
    )
    overlap_path = native / "native_context_overlap.parquet"
    overlap_table = pq.read_table(overlap_path)
    overlaps = [
        row for row in overlap_table.to_pylist() if row["packet_root"] != str(root)
    ]
    for row in pa.Table.from_pandas(contexts, preserve_index=False).to_pylist():
        source_only = row["canonical_join_mode"] == "source_only"
        overlaps.append({
            **row, "bill_id": None if source_only else row["declared_bill_id"],
            "identifier": row["native_identifier"],
            "canonical_join_basis": (
                "source_only_unresolved_identity" if source_only
                else "declared_bill_id_exact_session_typed_identity"
            ),
            "date_evidence_status": "unresolved_not_a_source_date",
        })
    pq.write_table(pa.Table.from_pylist(overlaps, schema=overlap_table.schema), overlap_path)
    write_json(native / "manifest.json", native_manifest)
    repin_optional(native)
    path = metadata / "bill_evidence.parquet"
    bills = pq.read_table(path).to_pylist()
    next(row for row in bills if row["bill_id"] == "bill:0")["n_indexed_native_views"] = 2
    pq.write_table(pa.Table.from_pylist(bills), path)
    repin(metadata)
    metadata_manifest = json.loads((metadata / "manifest.json").read_text())
    metadata_manifest["inputs"]["native_manifest"] = input_pin(native / "manifest.json")
    write_json(metadata / "manifest.json", metadata_manifest)
    out = tmp_path / "preview"
    manifest = build_cycle_preview(metadata, platform, out, native_evidence=native)
    assert manifest["counts"]["native_full_text_candidate_views"] == 16
    assert manifest["counts"]["native_full_text_candidate_contexts"] == 13
    with gzip.open(out / "downloads/native-TX.jsonl.gz", "rt") as handle:
        references = [row for line in handle if (row := json.loads(line))["bill_id"] == "bill:0"]
    assert len(references) == 2
    assert {row["context_id"] for row in references} == {"native:0", "native:12"}
    assert all(row["native_context"]["context_granularity"] == "source_reference"
               for row in references)
    assert all(row["bill_context"]["n_indexed_native_views"] == 2 for row in references)


@pytest.mark.parametrize("defect", [
    "native_binding", "registry", "native_source", "native_text", "candidate_mapping",
    "source_only_join",
    "plan_artifact", "plan_stale_views", "plan_view", "plan_bill", "plan_hash",
    "plan_characters", "plan_discarded", "plan_coverage", "plan_window", "plan_missing",
    "plan_approval",
])
def test_optional_inputs_fail_closed(cycle_bundle, optional_bundle, tmp_path, defect):
    metadata, platform, *_ = cycle_bundle
    native, plan = optional_bundle
    if defect == "native_binding":
        value = json.loads((metadata / "manifest.json").read_text())
        value["inputs"]["native_manifest"]["sha256"] = "0" * 64
        write_json(metadata / "manifest.json", value)
    elif defect == "registry":
        value = json.loads((native / "manifest.json").read_text())
        path = Path(value["inputs"]["registry"]["path"])
        path.write_text(path.read_text() + "\n# silently mutated current registry\n")
    elif defect in ("native_source", "native_text"):
        value = json.loads((native / "manifest.json").read_text())
        path = Path(value["inputs"]["TX_views"]["path"])
        table = pq.read_table(path).to_pylist()
        table[0]["text"] = "not the complete indexed native string"
        pq.write_table(pa.Table.from_pylist(table), path)
        if defect == "native_text":
            source_manifest = path.parent / "manifest.json"
            source = json.loads(source_manifest.read_text())
            source["files"][path.name] = sha256_file(path)
            write_json(source_manifest, source)
            registry = Path(value["inputs"]["registry"]["path"])
            config = yaml.safe_load(registry.read_text())
            config["packets"][0]["manifest_sha256"] = sha256_file(source_manifest)
            registry.write_text(yaml.safe_dump(config))
            for role, target in (("TX_views", path), ("TX_manifest", source_manifest),
                                 ("registry", registry)):
                value["inputs"][role] = input_pin(target)
            write_json(native / "manifest.json", value)
    elif defect in ("candidate_mapping", "source_only_join"):
        path = native / "native_context_overlap.parquet"
        rows = pq.read_table(path).to_pylist()
        if defect == "candidate_mapping":
            rows[0]["identifier"] = "HB 999"
        else:
            next(row for row in rows if row["canonical_join_mode"] == "source_only")[
                "bill_id"
            ] = "bill:0"
        pq.write_table(pa.Table.from_pylist(rows), path)
        repin_optional(native)
    elif defect == "plan_artifact":
        (plan / "report.json").write_text("{}")
    elif defect == "plan_stale_views":
        value = json.loads((plan / "manifest.json").read_text())
        value["inputs"]["views"]["sha256"] = "0" * 64
        write_json(plan / "manifest.json", value)
    else:
        path = plan / "token_window_plan.parquet"
        rows = pq.read_table(path).to_pylist()
        if defect == "plan_missing":
            rows.pop()
        else:
            key, value = {
                "plan_view": ("view_id", "stale-view"),
                "plan_bill": ("bill_id", "wrong-bill"),
                "plan_hash": ("input_sha256", "0" * 64),
                "plan_characters": ("n_input_characters", 9999),
                "plan_discarded": ("n_discarded_tokens", 1),
                "plan_coverage": ("n_unique_covered_tokens", 1),
                "plan_window": ("window_model_input_lengths", [1025, 900]),
                "plan_approval": ("model_input_approved", True),
            }[defect]
            rows[0][key] = value
        pq.write_table(pa.Table.from_pylist(rows), path)
        repin_optional(plan)
    if defect in ("native_text", "candidate_mapping", "source_only_join"):
        # Rebind the new native manifest so rejection reaches the specific broken source/mapping.
        value = json.loads((metadata / "manifest.json").read_text())
        value["inputs"]["native_manifest"] = input_pin(native / "manifest.json")
        write_json(metadata / "manifest.json", value)
    out = tmp_path / "preview"
    with pytest.raises(ValueError):
        build_cycle_preview(
            metadata, platform, out, native_evidence=native, metadata_token_plan=plan,
        )
    assert not out.exists()


def test_cycle_export_reconciles_and_downloads_full_sources_and_unknowns(cycle_bundle, tmp_path):
    metadata, platform, contexts, abstracts, views, records = cycle_bundle
    source_pins = {
        str(path): sha256_file(path) for directory in (metadata, platform)
        for path in directory.iterdir()
    }
    out = tmp_path / "preview"
    manifest = build_cycle_preview(metadata, platform, out)
    assert manifest["publication_status"] == "local_only_unpublished"
    assert manifest["counts"]["states"] == 50
    assert manifest["counts"]["organizations"] == 100
    assert manifest["counts"]["n_cycle_contexts"] == 14
    assert manifest["counts"]["n_metadata_candidate_views_not_bills"] == 15
    assert manifest["counts"]["cohort_scope_counts"] == dict(Counter(
        row["cohort_scope"] for row in contexts
    ))
    assert len(list((out / "evidence").glob("bills-*.jsonl"))) == 50
    assert len(list((out / "evidence").glob("platform-*.jsonl"))) == 101
    exported = []
    for path in sorted((out / "downloads").glob("bills-*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            exported.extend(json.loads(line) for line in handle)
    assert len(exported) == len(views)
    original = {row["view_id"]: row for row in views}
    for row in exported:
        assert {key: row[key] for key in original[row["view_id"]]} == original[row["view_id"]]
        assert row["source_bundle_manifest_sha256"] == sha256_file(metadata / "manifest.json")
        assert row["model_input_approved"] is row["training_admission"] is False
        assert row["n_input_tokens"] is None
    assert {row["source_abstract"]["id"]: row["source_abstract"] for row in exported
            if row["source_abstract"]} == {row["id"]: row for row in abstracts}
    assert next(row for row in exported if row["state"] == "MA")[
        "bill_context"
    ]["n_indexed_native_views"] is None
    assert next(row for row in exported if row["state"] == "TX")[
        "bill_context"
    ]["n_indexed_native_views"] == 0
    platform_export = []
    for path in sorted((out / "downloads").glob("platform-*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            platform_export.extend(json.loads(line) for line in handle)
    assert {row["record_id"]: {k: v for k, v in row.items() if k != "source_type"}
            for row in platform_export} == {row["record_id"]: row for row in records}
    assert all(row["human_gold"] is row["analytical_admission"] is False for row in platform_export)
    assert json.loads((out / "downloads/metadata_source_manifest.json").read_text()) == json.loads(
        (metadata / "manifest.json").read_text()
    )
    document = (out / "index.html").read_text()
    assert document.count('<tr data-state="') == 150
    assert "<script>window.EVIDENCE_INJECTED" not in document
    assert "&lt;script&gt;window.EVIDENCE_INJECTED" in document
    assert "@@" not in document
    assert "Unknown (not registered)" in document
    assert "relative to 2 registered state packets" in document
    assert len(list(out.rglob("*.pdf"))) == 0
    for relative, pin in manifest["outputs"].items():
        assert sha256_file(out / relative) == pin["sha256"]
    assert all(sha256_file(Path(path)) == digest for path, digest in source_pins.items())


@pytest.mark.parametrize("defect", [
    "hash", "missing", "admission", "unknown_as_zero", "matrix_count", "duplicate_view",
    "missing_abstract", "platform_count", "platform_admission", "platform_text", "platform_dates",
])
def test_cycle_preview_rejects_bad_bundles_before_output(cycle_bundle, tmp_path, defect):
    metadata, platform, *_ = cycle_bundle
    if defect == "hash":
        (metadata / "report.json").write_text("{}")
    elif defect == "missing":
        (metadata / "abstract_evidence.parquet").unlink()
    elif defect in ("admission", "duplicate_view", "missing_abstract"):
        path = metadata / "candidate_metadata_views.parquet"
        rows = pq.read_table(path).to_pylist()
        if defect == "admission":
            rows[0]["model_input_approved"] = True
        elif defect == "duplicate_view":
            rows[1]["view_id"] = rows[0]["view_id"]
        else:
            rows[0]["abstract_id"] = "missing"
        pq.write_table(pa.Table.from_pylist(rows), path)
        repin(metadata)
    elif defect == "unknown_as_zero":
        path = metadata / "bill_evidence.parquet"
        rows = pq.read_table(path).to_pylist()
        rows[-1]["n_indexed_native_views"] = 0
        pq.write_table(pa.Table.from_pylist(rows), path)
        repin(metadata)
    elif defect == "matrix_count":
        path = metadata / "state_matrix.csv"
        rows = csv.read_csv(path).to_pylist()
        rows[0]["n_cycle_evidence_candidate_contexts"] += 1
        csv.write_csv(pa.Table.from_pylist(rows), path)
        repin(metadata)
    elif defect == "platform_dates":
        path = platform / "manifest.json"
        value = json.loads(path.read_text())
        value["study_end"] = "2026-12-31"
        write_json(path, value)
    else:
        path = platform / ("organizations.jsonl" if defect == "platform_count" else "records.jsonl")
        rows = [json.loads(line) for line in path.read_text().split("\n") if line]
        if defect == "platform_count":
            rows[0]["n_evidence_records"] += 1
        elif defect == "platform_admission":
            rows[0]["human_gold"] = True
        else:
            rows[0]["extracted_text"] += "changed"
        write_jsonl(path, rows)
        repin(platform, platform=True)
    out = tmp_path / "preview"
    with pytest.raises((ValueError, FileNotFoundError)):
        build_cycle_preview(metadata, platform, out)
    assert not out.exists()


def test_cycle_refuses_overlapping_or_nonempty_output(cycle_bundle, tmp_path):
    metadata, platform, *_ = cycle_bundle
    for out in (metadata, tmp_path, ROOT / "web" / "forbidden-preview"):
        with pytest.raises(ValueError, match="output"):
            build_cycle_preview(metadata, platform, out)


def test_query_download_uses_all_matches_and_safe_literal_text(cycle_bundle, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable; no browser validation implied")
    metadata, platform, *_ = cycle_bundle
    out = tmp_path / "preview"
    build_cycle_preview(metadata, platform, out)
    check = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { filterEvidence, fullQueryJSONL, safeSourceURL } = require(process.argv[1]);
const rows = fs.readFileSync(process.argv[2], "utf8").trimEnd().split("\n").map(JSON.parse);
const matches = filterEvidence(rows, '"quoted phrase"');
assert.equal(matches.length, 13);
assert.ok(matches.length > 10);
const downloaded = fullQueryJSONL(matches).trimEnd().split("\n").map(JSON.parse);
assert.deepEqual(downloaded, matches);
assert.ok(downloaded[12].text.includes("<script>window.EVIDENCE_INJECTED=true</script>"));
assert.equal(downloaded[0].training_admission, false);
assert.equal(downloaded[0].n_input_tokens, null);
assert.equal(filterEvidence(rows, "no-such-text").length, 0);
assert.equal(fullQueryJSONL([]), "");
assert.equal(filterEvidence(rows, "HB 11").length, 1);
assert.equal(safeSourceURL("javascript:alert(1)"), null);
assert.equal(safeSourceURL("file:///unserved/source.pdf"), null);
assert.equal(safeSourceURL("/unserved/source.pdf"), null);
assert.equal(safeSourceURL("https://example.org/platform"), "https://example.org/platform");
"""
    subprocess.run(
        [node, "-e", check, str(out / "cycle-evidence.js"), str(out / "evidence/bills-TX.jsonl")],
        check=True, capture_output=True, text=True,
    )


def test_cycle_cli_mode_builds_separate_unpublished_preview(
    cycle_bundle, tmp_path, capsys, monkeypatch,
):
    metadata, platform, *_ = cycle_bundle
    main = runpy.run_path(str(ROOT / "scripts/build_site.py"))["main"]
    out = tmp_path / "preview"
    assert main([
        "--cycle-evidence", "--bill-evidence", str(metadata), "--platform-evidence", str(platform),
        "--out", str(out),
    ]) == 0
    assert "build manifest sha256:" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--cycle-evidence", "--recovery", str(platform)])
    captured = []

    def capture_defaults(metadata_dir, platform_dir, output, **optional):
        captured.append((metadata_dir, platform_dir, output, optional))
        return {"counts": {}}

    monkeypatch.setattr("state_politics.site_evidence.build_cycle_preview", capture_defaults)
    monkeypatch.setitem(main.__globals__, "sha256_file", lambda _: "test-default-paths")
    assert main(["--cycle-evidence"]) == 0
    assert captured == [(
        ROOT / "data/processed/study-abstract-evidence-2023-2024-v3",
        ROOT / "data/processed/platform-study-evidence-2023-2024-v5",
        ROOT / "data/preview-cycle-evidence-v3", {
            "native_evidence": ROOT / "data/processed/study-native-overlap-2023-2024-v14",
            "metadata_token_plan": ROOT / "data/processed/study-metadata-token-plan-2023-2024-v2",
        },
    )]
    assert main(["--cycle-evidence", "--bill-evidence", str(metadata)]) == 0
    assert captured[-1] == (
        metadata, ROOT / "data/processed/platform-study-evidence-2023-2024-v5",
        ROOT / "data/preview-cycle-evidence-v3", {},
    )


@pytest.mark.parametrize("option", ["--native-evidence", "--metadata-token-plan"])
def test_cycle_cli_optional_sources_work_independently(
    cycle_bundle, optional_bundle, tmp_path, option,
):
    metadata, platform, *_ = cycle_bundle
    native, plan = optional_bundle
    main = runpy.run_path(str(ROOT / "scripts/build_site.py"))["main"]
    out = tmp_path / "preview"
    assert main([
        "--cycle-evidence", "--bill-evidence", str(metadata), "--platform-evidence", str(platform),
        option, str(native if option == "--native-evidence" else plan), "--out", str(out),
    ]) == 0
    rows = [
        json.loads(line) for line in (out / "evidence/bills-TX.jsonl").read_text().split("\n")
        if line
    ]
    assert ("token_plan" in rows[0]) == (option == "--metadata-token-plan")
    assert rows[0]["n_input_tokens"] is None
    assert (out / "evidence/native-TX.jsonl").exists() == (option == "--native-evidence")
    with pytest.raises(SystemExit):
        main([option, str(native)])


@pytest.mark.skipif(not os.environ.get("CYCLE_BROWSER_CHROME"), reason="No real browser configured")
def test_cycle_real_browser_controls_downloads_markup_nojs_and_mobile(cycle_bundle, tmp_path):
    metadata, platform, *_ = cycle_bundle
    out = tmp_path / "preview"
    build_cycle_preview(metadata, platform, out)
    result = subprocess.run([
        shutil.which("node"), str(ROOT / "tests/browser_cycle_site.cjs"), str(out),
        str(tmp_path / "browser-check"), os.environ["CYCLE_BROWSER_CHROME"], "fixture",
    ], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not os.environ.get("CYCLE_BROWSER_CHROME"), reason="No real browser configured")
def test_cycle_real_browser_native_full_query_and_token_plan(
    cycle_bundle, optional_bundle, tmp_path,
):
    metadata, platform, *_ = cycle_bundle
    native, plan = optional_bundle
    out = tmp_path / "preview"
    build_cycle_preview(
        metadata, platform, out, native_evidence=native, metadata_token_plan=plan,
    )
    result = subprocess.run([
        shutil.which("node"), str(ROOT / "tests/browser_cycle_site.cjs"), str(out),
        str(tmp_path / "browser-check"), os.environ["CYCLE_BROWSER_CHROME"], "fixture",
    ], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr

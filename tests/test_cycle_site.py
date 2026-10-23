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
from state_politics.bills.study_window import _snapshot
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


@pytest.fixture
def snapshot_bundle(cycle_bundle, tmp_path):
    from state_politics.site_snapshot_text import FLAGS, STATUS

    metadata, *_ = cycle_bundle
    directory = tmp_path / "snapshot"
    directory.mkdir()
    contexts, originals, links, versions = [], [], [], []
    source_contexts = pq.read_table(metadata / "bill_evidence.parquet").to_pylist()
    for index, source in enumerate(source_contexts):
        text = SOURCE_TEXT if index == 0 else " \n\f\u2028" if index == 2 else None
        has_text = bool(text and text.strip())
        bill_id, link_id, version_id = source["bill_id"], f"link:{index}", f"version:{index}"
        originals.append({
            "source_row_ordinal": index + 1, "id": str(index), "bill_id": bill_id,
            "version_link_id": link_id, "raw_text": text, "is_error": "f" if has_text else "t",
            "created_at": "2026-10-01 00:00:00+00", "search_vector": "'unchanged':1",
            "all_titles": source["title"],
        })
        contexts.append({
            **{key: source[key] for key in (
                "bill_id", "state", "identifier", "session_identifier",
            )},
            "searchablebill_id": str(index), "version_link_id": link_id,
            "version_id": version_id, "exact_version_foreign_keys": True,
            "raw_text_sha256": digest(text or ""),
            "raw_text_n_characters": len(text or ""), "has_raw_text": has_text,
            "nonempty_bound_noerror": has_text,
            "source_reference_status": "exact_version_foreign_keys",
            "source_url": "https://example.gov/version",
            **dict.fromkeys(FLAGS, False),
        })
        links.append({
            "id": link_id, "bill_id": bill_id, "version_id": version_id,
            "url": "https://example.gov/version", "media_type": "application/pdf",
        })
        versions.append({
            "id": version_id, "bill_id": bill_id, "note": "Current Version",
            "date": "2025-01-01", "extras": "{}", "classification": "{}",
        })
    for name, rows in (
        ("context_inventory", contexts), ("searchablebill", originals),
        ("version_links", links), ("versions", versions),
    ):
        pq.write_table(pa.Table.from_pylist(rows), directory / f"{name}.parquet")
    coverage = [{
        "state": state, "context_rows": sum(row["state"] == state for row in contexts),
        "nonempty_retained_rows": int(state == "TX"),
        "error_flagged_rows": sum(row["state"] == state and not row["has_raw_text"]
                                  for row in contexts),
    } for state in sorted(STATES)]
    csv.write_csv(pa.Table.from_pylist(coverage), directory / "state_text_coverage.csv")
    for name in ("interface.json", "report.json"):
        write_json(directory / name, {})
    write_json(directory / "sealed_manifest.json", {
        "schema_version": 1, "status": STATUS, "approvals": dict.fromkeys(FLAGS, False),
        "validation": {"all_context_to_source_record_bindings_verified": True},
        "packet_artifacts": {
            path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in directory.iterdir() if path.is_file()
        },
    })
    return directory, originals


def repin_snapshot(directory):
    manifest = json.loads((directory / "sealed_manifest.json").read_text())
    for name in manifest["packet_artifacts"]:
        path = directory / name
        manifest["packet_artifacts"][name] = {
            "sha256": sha256_file(path), "bytes": path.stat().st_size,
        }
    write_json(directory / "sealed_manifest.json", manifest)


def test_snapshot_preserves_complete_source_fields_errors_and_separate_version_scope(
    cycle_bundle, snapshot_bundle, tmp_path,
):
    metadata, platform, *_ = cycle_bundle
    snapshot, originals = snapshot_bundle
    out = tmp_path / "preview"
    manifest = build_cycle_preview(
        metadata, platform, out, snapshot_text_evidence=snapshot,
    )
    assert manifest["counts"]["snapshot_text"] == {
        "n_records": 14, "n_nonempty_retained_texts": 1,
        "raw_text_characters": len(SOURCE_TEXT) + len(" \n\f\u2028"),
        "nonempty_raw_text_characters": len(SOURCE_TEXT), "states_with_nonempty_text": 1,
        "filing_time_text_certified": False,
    }
    assert manifest["counts"]["n_cycle_contexts"] == 14
    with gzip.open(out / "downloads/snapshot-TX.jsonl.gz", "rt") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    assert len(rows) == 12
    for row, original in zip(rows, originals[:12], strict=True):
        assert row["source_record"] == {
            key: value for key, value in original.items() if key != "source_row_ordinal"
        }
        assert row["source_row_ordinal"] == original["source_row_ordinal"]
        assert row["source_version"]["version"]["note"] == "Current Version"
        assert row["filing_time_text_certified"] is False
        assert row["source_date_or_party_inferred"] is False
        assert "token_plan" not in row and "text" not in row
    assert rows[0]["source_record"]["raw_text"] == SOURCE_TEXT
    assert rows[1]["source_record"]["raw_text"] is None
    assert rows[2]["source_record"]["raw_text"] == " \n\f\u2028"
    assert rows[2]["snapshot"]["has_nonempty_raw_text"] is False
    assert rows[1]["snapshot"]["provider_flags"] == {"is_error": "t"}
    document = (out / "index.html").read_text()
    assert 'value="snapshot_text"' in document
    assert document.count("complete source records and retained text</a>") == 50
    assert "not introduced text" in document
    assert (out / "evidence/snapshot-ME.jsonl").read_bytes() == b""
    assert (out / "downloads/producers/site_snapshot_text.py").is_file()


@pytest.mark.parametrize("with_ancestry", [False, True])
def test_research_corpus_exports_complete_alternatives_without_new_bill_admission(
    cycle_bundle, tmp_path, with_ancestry,
):
    from state_politics.bills.research_corpus_text import (
        ANCESTOR_FILES,
        REVISION,
        SOURCE_FILES,
        recover,
    )

    metadata, platform, *_ = cycle_bundle
    for name in ("bill_evidence", "abstract_evidence", "candidate_metadata_views"):
        rows = pq.read_table(metadata / f"{name}.parquet").to_pylist()
        for row in rows:
            if row["state"] == "TX":
                row["state"] = "NH"
        pq.write_table(pa.Table.from_pylist(rows), metadata / f"{name}.parquet")
    matrix = csv.read_csv(metadata / "state_matrix.csv").to_pylist()
    original = {row["state"]: dict(row) for row in matrix}
    for row in matrix:
        if row["state"] in ("TX", "NH"):
            other = original["NH" if row["state"] == "TX" else "TX"]
            row.update({key: value for key, value in other.items()
                        if key not in ("state", "state_name")})
    csv.write_csv(pa.Table.from_pylist(matrix), metadata / "state_matrix.csv")
    repin(metadata)
    source = tmp_path / "corpus-source"
    source.mkdir()
    text = (
        "HB 0 - AS INTRODUCED 2023 SESSION STATE OF NEW HAMPSHIRE "
        "Be it Enacted by the Senate and House of Representatives: " + SOURCE_TEXT
    )
    records = [
        {"title": "Original", "summary": "Not gold", "text": text},
        {"title": None, "summary": "Original duplicate", "text": text},
    ]
    raw = source / SOURCE_FILES["NH"]
    write_json(raw, records)
    write_json(source / "mtsu-dataset-metadata.json", {
        "sha": REVISION, "cardData": {"license": "apache-2.0"},
    })
    write_json(source / "mtsu-file-tree.json", [{
        "path": raw.name, "size": raw.stat().st_size, "lfs": {"oid": sha256_file(raw)},
    }])
    if with_ancestry:
        old = source / ANCESTOR_FILES["NH"]
        write_json(old, {
            f"0000{index}": {**row, "source_file": f"HB0-{index}.json"}
            for index, row in enumerate(records)
        })
        write_json(source / "mtsu-original-file-tree.json", [{
            "path": old.name, "size": old.stat().st_size, "lfs": {"oid": sha256_file(old)},
        }])
    contexts = pq.read_table(metadata / "bill_evidence.parquet").to_pylist()
    gap = source / "gap.parquet"
    pq.write_table(pa.Table.from_pylist([
        {**row, "neither_source_observed": True} for row in contexts if row["state"] == "NH"
    ]), gap)
    packet = tmp_path / "corpus-packet"
    recover(source, gap, packet, states=("NH",), source_ancestry=with_ancestry)
    out = tmp_path / "corpus-preview"
    manifest = build_cycle_preview(metadata, platform, out, research_corpus_evidence=packet)
    assert manifest["counts"]["n_cycle_contexts"] == 14
    assert manifest["counts"]["research_corpus_text"] == {
        "n_contexts": 1, "n_views": 2, "publisher_original_verified": False,
        "filing_time_text_certified": False,
    }
    exported = [json.loads(line) for line in (
        out / "evidence/corpus-NH.jsonl"
    ).read_text().split("\n") if line]
    assert [row["source_record"] for row in exported] == records
    if with_ancestry:
        assert [row["source_ancestry"][0]["original_dataset_key"] for row in exported] == [
            "00000", "00001",
        ]
    assert gzip.decompress((out / "downloads/corpus-NH.jsonl.gz").read_bytes()) == (
        out / "evidence/corpus-NH.jsonl"
    ).read_bytes()
    assert (out / "evidence/corpus-ME.jsonl").read_bytes() == b""
    assert (out / "downloads/producers/research_corpus_text.py").is_file()
    document = (out / "index.html").read_text()
    assert 'value="research_corpus_text"' in document
    assert document.count('href="downloads/corpus-') == 50
    assert "not publisher originals" in document


@pytest.mark.parametrize("duplicate_view", [False, True])
def test_independent_archive_exports_preserve_provider_alternatives_and_full_text(
    cycle_bundle, tmp_path, monkeypatch, duplicate_view,
):
    metadata, platform, *_ = cycle_bundle
    context = pq.read_table(metadata / "bill_evidence.parquet").to_pylist()[0]
    packets, originals = [], []
    for index in range(2):
        directory = tmp_path / f"archive-{index}"
        directory.mkdir()
        write_json(directory / "manifest.json", {"schema": "consumer-wiring-fixture"})
        write_json(directory / "report.json", {"source": index})
        packets.append(directory)
        originals.append({
            **{key: context[key] for key in (
                "bill_id", "state", "identifier", "session_identifier", "title",
            )},
            "view_id": f"archive:{0 if duplicate_view else index}",
            "source_type": "archive_text", "archive_provider": f"fixture:{index}",
            "text": SOURCE_TEXT + "\u2028Complete original ending.\u2029",
            "source_record": {"original_null": None, "original_field": SOURCE_TEXT},
            "source_identity": {"printed_evidence": []}, "source_members": {},
            "archive_generated_prologue_preserved": True, "training_admission": False,
            "model_input_approved": False, "analytical_admission": False,
        })

    def supplied_archive(directory, current):
        assert context in current
        index = packets.index(directory)
        return [originals[index]], [context], {
            name: sha256_file(directory / name) for name in ("manifest.json", "report.json")
        }, {"schema": "consumer-wiring-fixture"}

    monkeypatch.setattr("state_politics.site_evidence.load_archive", supplied_archive)
    out = tmp_path / "archive-preview"
    if duplicate_view:
        with pytest.raises(ValueError, match="duplicate independent-archive source view"):
            build_cycle_preview(metadata, platform, out, archive_text_evidence=tuple(packets))
        assert not out.exists()
        return
    manifest = build_cycle_preview(
        metadata, platform, out, archive_text_evidence=tuple(packets),
    )
    assert manifest["counts"]["n_cycle_contexts"] == 14
    assert manifest["counts"]["archive_text"] == {
        "n_contexts": 1, "n_views": 2, "n_packets": 2,
        "publisher_original_verified": False, "filing_time_text_certified": False,
    }
    body = (out / "evidence/archive-TX.jsonl").read_bytes()
    rows = [json.loads(line) for line in body.decode().split("\n") if line]
    for row, original in zip(rows, originals, strict=True):
        assert {key: row[key] for key in original} == original
        assert row["source_bundle_manifest_sha256"] in {
            sha256_file(directory / "manifest.json") for directory in packets
        }
    assert gzip.decompress((out / "downloads/archive-TX.jsonl.gz").read_bytes()) == body
    assert (out / "evidence/archive-ME.jsonl").read_bytes() == b""
    assert (out / "downloads/producers/archive_text.py").is_file()
    assert (out / "downloads/producers/lawatlas_text.py").is_file()
    for name in ("nj_library_collection.py", "ok_retained_context_text.py"):
        assert (out / "downloads/producers" / name).read_bytes() == (
            ROOT / "src/state_politics/bills" / name
        ).read_bytes()
    document = (out / "index.html").read_text()
    assert 'value="archive_text"' in document
    assert document.count('href="downloads/archive-') == 50
    assert "not publisher-version certification" in document


@pytest.mark.parametrize("defect", ["scope", "version", "body", "approval", "linked_manifest"])
def test_snapshot_rejects_wrong_scope_version_body_and_approval(
    cycle_bundle, snapshot_bundle, tmp_path, defect,
):
    metadata, platform, *_ = cycle_bundle
    directory, _ = snapshot_bundle
    if defect == "linked_manifest":
        target = directory.parent / "linked-source-manifest.json"
        shutil.copyfile(directory / "sealed_manifest.json", target)
        (directory / "sealed_manifest.json").unlink()
        (directory / "sealed_manifest.json").symlink_to(target)
        with pytest.raises(ValueError, match="linked sealed manifest"):
            build_cycle_preview(
                metadata, platform, tmp_path / "bad-preview", snapshot_text_evidence=directory,
            )
        return
    if defect == "version":
        path = directory / "versions.parquet"
        rows = pq.read_table(path).to_pylist()
        rows[0]["bill_id"] = "another-bill"
    elif defect == "body":
        path = directory / "searchablebill.parquet"
        rows = pq.read_table(path).to_pylist()
        rows[0]["raw_text"] = "same identity but fabricated replacement body"
    else:
        path = directory / "context_inventory.parquet"
        rows = pq.read_table(path).to_pylist()
        rows[0]["state" if defect == "scope" else "model_input_approved"] = (
            "AK" if defect == "scope" else True
        )
    pq.write_table(pa.Table.from_pylist(rows), path)
    repin_snapshot(directory)
    with pytest.raises(ValueError, match="incompatible snapshot text"):
        build_cycle_preview(
            metadata, platform, tmp_path / "bad-preview", snapshot_text_evidence=directory,
        )


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
def receipt_bundle(tmp_path):
    directory = tmp_path / "receipts"
    directory.mkdir()
    source = tmp_path / "retained_receipt_source.json"
    write_json(source, {"unchanged_original": SOURCE_TEXT})
    records, bills, actions, contexts, dispositions = [], [], [], [], []
    for index in range(2):
        day = "2023-12-11" if index == 0 else "2023-12-20"
        raw_date = "December 11, 2023" if index == 0 else "December 20, 2022"
        literal = "2023-12-11" if index == 0 else "2022-12-20"
        description = f"Received by the Clerk of the House on {raw_date}."
        bill = {
            "bill_id": f"receipt-bill:{index}", "state": "ME",
            "identifier": "LD 2081" if index else "LD 2000",
            "session_identifier": "131", "title": SOURCE_TEXT,
            "from_organization_id": "maine-house", "originating_chamber": "lower",
            "original_unknown_field": {"unaltered": SOURCE_TEXT, "missing": None},
        }
        action = {
            "action_id": f"receipt-action:{index}", "bill_id": bill["bill_id"], "state": "ME",
            "date": day, "description": description, "classification": "receipt",
            "organization_id": "maine-house", "chamber": "lower", "order": 1,
        }
        start = description.index(raw_date)
        receiver = "Clerk of the House"
        receiver_start = description.index(receiver)
        spans = [{
            "receipt_raw": description[:-1], "receipt_span": [0, len(description) - 1],
            "receiver_raw": receiver,
            "receiver_span": [receiver_start, receiver_start + len(receiver)],
            "literal_date_raw": raw_date, "literal_date_span": [start, start + len(raw_date)],
            "literal_calendar_date": literal, "literal_chamber": "lower",
            "uninterpreted_description_suffix": ".",
        }]
        observation = {
            "source_event_date_raw": day, "event_calendar_date": day,
            "literal_calendar_date": literal, "date_agreement": (
                "dates_agree" if index == 0 else "dates_disagree"
            ),
            "receipt_statement_count": 1, "receipt_spans_json": json.dumps(spans),
            "target_calendar_interest": True, "is_unambiguous_origin_receipt": index == 0,
            "bill_exact_receipt_action_count": 1, "action_id_occurrences": 1,
            "same_observed_event_occurrences": 1,
            "origin_identity_status": "origin_identity_matches",
            "negative_flags_json": "[]" if index == 0 else '["dates_disagree"]',
            "analytical_admission": False,
        }
        context = {
            "bill_id": bill["bill_id"], "original_bill": bill,
            "original_action_ids": [action["action_id"]],
            "original_bill_abstracts": [{
                "id": f"abstract:{index}", "bill_id": bill["bill_id"],
                "abstract": SOURCE_TEXT, "note": SOURCE_TEXT,
            }],
            "original_bill_sources": [{"url": "javascript:untrusted()", "note": SOURCE_TEXT}],
            "original_filing_ledger": {"original_unresolved": SOURCE_TEXT},
        }
        records.append({
            "source_action": action, "source_bill": bill, "observation": observation,
            "source_context_join": {
                "artifact": "source_contexts.jsonl", "bill_id": bill["bill_id"],
            },
            "raw_event_date_span": {
                "source_field": "date", "raw_value": day, "span": [0, len(day)],
            },
        })
        bills.append(bill)
        actions.append(action)
        contexts.append(context)
        dispositions.append({**action, **observation})
    write_jsonl(directory / "target_calendar_receipt_observations.jsonl", records)
    write_jsonl(directory / "source_contexts.jsonl", contexts)
    for name, rows in (
        ("source_bills", bills), ("source_bill_actions", actions),
        ("all_action_dispositions", dispositions),
    ):
        pq.write_table(pa.Table.from_pylist(rows), directory / f"{name}.parquet")
    status = "complete_retained_maine_receipt_observations_not_source_admission"
    counts = {
        "target_calendar_interest_actions": 2, "all_retained_me_bills": 2,
        "unambiguous_origin_in_window_receipt_observations": 1,
    }
    write_json(directory / "report.json", {
        "status": status, "counts": counts, "inputs_unchanged": True,
        "analytical_admission": False, "new_requests": 0,
    })
    write_json(directory / "verification.json", {"original_string_and_null_preservation": True})
    inputs = {"retained_original": _snapshot(source)}
    write_json(directory / "manifest.json", {
        "schema_version": 1, "status": status, "state": "ME",
        "window_start": "2023-01-01", "window_end": "2024-12-31",
        "analytical_admission": False, "introduction_or_filing_inference": False,
        "original_source_writes": 0, "new_requests": 0, "inputs_unchanged": True,
        "inputs": inputs, "inputs_after": inputs, "counts": counts,
    })
    repin_optional(directory)
    return directory


def test_receipts_remain_separate_complete_source_observations(
    cycle_bundle, receipt_bundle, tmp_path,
):
    metadata, platform, *_ = cycle_bundle
    before = _snapshot(receipt_bundle / "manifest.json")
    out = tmp_path / "preview"
    manifest = build_cycle_preview(metadata, platform, out, receipt_evidence=receipt_bundle)
    assert manifest["counts"]["n_cycle_contexts"] == 14
    assert manifest["counts"]["n_metadata_candidate_views_not_bills"] == 15
    assert manifest["counts"]["source_receipt_evidence"] == {
        "target_calendar_interest_views": 2, "unique_origin_date_agreeing_views": 1,
        "unresolved_views": 1, "provided_states": ["ME"],
        "other_states": "unknown_not_supplied", "retained_wider_history_contexts": 2,
        "cohort_admissions": 0,
    }
    assert (out / "evidence/bills-ME.jsonl").read_text() == ""
    assert not (out / "evidence/receipts-TX.jsonl").exists()
    originals = [
        json.loads(line) for line in
        (receipt_bundle / "target_calendar_receipt_observations.jsonl").read_text().split("\n")
        if line
    ]
    with gzip.open(out / "downloads/receipts-ME.jsonl.gz", "rt") as handle:
        rows = [json.loads(line) for line in handle]
    assert len(rows) == 2
    for row, original in zip(rows, originals, strict=True):
        assert {key: row[key] for key in original} == original
        assert row["source_context"]["original_bill"] == original["source_bill"]
        assert row["source_context"]["original_bill_abstracts"][0]["abstract"] == SOURCE_TEXT
        assert row["native_evidence"] is row["eligible_cycle_admission"] is False
    assert rows[1]["source_action"]["date"] == "2023-12-20"
    assert rows[1]["observation"]["literal_calendar_date"] == "2022-12-20"
    assert rows[1]["receipt_status"] == "unresolved_receipt"
    document = (out / "index.html").read_text()
    assert document.count("Unknown — no receipt packet supplied") == 49
    assert 'value="source_receipt"' in document
    assert "not introduction, filing, native evidence or eligible-cycle admission" in document
    assert "<script>window.EVIDENCE_INJECTED" not in document
    assert before == _snapshot(receipt_bundle / "manifest.json")


@pytest.mark.parametrize("defect", [
    "unfinished", "hash", "manifest_inference", "original_source_stat", "admission",
    "missing_target", "hidden_mismatch", "changed_original", "dropped_context_field",
    "source_admission_flag",
])
def test_receipt_inputs_fail_closed(cycle_bundle, receipt_bundle, tmp_path, defect):
    metadata, platform, *_ = cycle_bundle
    manifest_path = receipt_bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    target_path = receipt_bundle / "target_calendar_receipt_observations.jsonl"
    if defect == "unfinished":
        manifest["status"] = "incomplete"
    elif defect == "hash":
        target_path.write_text("{}\n")
    elif defect == "manifest_inference":
        manifest["introduction_or_filing_inference"] = True
    elif defect == "original_source_stat":
        source = Path(manifest["inputs"]["retained_original"]["path"])
        original = source.stat()
        os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000))
    else:
        rows = [json.loads(line) for line in target_path.read_text().split("\n") if line]
        if defect == "admission":
            rows[0]["observation"]["analytical_admission"] = True
        elif defect == "source_admission_flag":
            rows[0]["source_admission"] = True
        elif defect == "missing_target":
            rows.pop()
        elif defect == "hidden_mismatch":
            rows[1]["observation"]["literal_calendar_date"] = "2023-12-20"
        elif defect == "changed_original":
            rows[0]["source_action"]["description"] += " silent amendment"
        elif defect == "dropped_context_field":
            rows[0]["source_bill"].pop("original_unknown_field")
        write_jsonl(target_path, rows)
    write_json(manifest_path, manifest)
    if defect not in {"hash", "original_source_stat"}:
        repin_optional(receipt_bundle)
    out = tmp_path / "preview"
    with pytest.raises(ValueError):
        build_cycle_preview(metadata, platform, out, receipt_evidence=receipt_bundle)
    assert not out.exists()


def test_receipt_source_mutation_during_export_rejected(
    cycle_bundle, receipt_bundle, tmp_path, monkeypatch,
):
    from state_politics import site_evidence

    metadata, platform, *_ = cycle_bundle
    manifest = json.loads((receipt_bundle / "manifest.json").read_text())
    source = Path(manifest["inputs"]["retained_original"]["path"])
    original = site_evidence._write_partition

    def mutate(out, name, rows):
        original(out, name, rows)
        if name == "receipts-ME":
            source.write_text("source changed during export")

    monkeypatch.setattr(site_evidence, "_write_partition", mutate)
    with pytest.raises(ValueError, match="receipt source changed during build"):
        build_cycle_preview(
            metadata, platform, tmp_path / "preview", receipt_evidence=receipt_bundle,
        )


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


def test_streamed_query_download_preserves_raw_fields_utf8_and_complete_matches():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    check = r"""
const assert = require("node:assert/strict");
const { fullQueryBlob } = require(process.argv[1]);
const lines = Array.from({ length: 13 }, (_, index) =>
  `{"view_id":"${index}","mtime_ns":1792435050043987571,`
  + `"text":"${index < 12 ? "Keep" : "Drop"} 😀 full ending ${index}",`
  + `"receipt_status":"${index % 2 ? "unresolved_receipt" : "unique_origin_date_agreeing"}"}`);
const sources = {
  "evidence/one.jsonl": lines.slice(0, 7).join("\n") + "\n",
  "evidence/two.jsonl": lines.slice(7).join("\n"),
};
global.fetch = async name => {
  assert.ok(Object.hasOwn(sources, name));
  const bytes = new TextEncoder().encode(sources[name]);
  let offset = 0;
  return new Response(new ReadableStream({
    pull(controller) {
      if (offset === bytes.length) return controller.close();
      controller.enqueue(bytes.slice(offset, offset + 7));
      offset = Math.min(bytes.length, offset + 7);
    },
  }));
};
Response.prototype.text = Blob.prototype.text = () => {
  throw new Error("Whole-source text forbidden");
};
(async () => {
  const stringify = JSON.stringify;
  JSON.stringify = () => { throw new Error("Do not reserialize raw provenance integers"); };
  const blob = await fullQueryBlob(["one", "two"], "keep", "", 12);
  JSON.stringify = stringify;
  assert.equal(Buffer.from(await blob.arrayBuffer()).toString(),
    lines.slice(0, 12).join("\n") + "\n");
  const blank = await fullQueryBlob(["one", "two"], "", "", 13);
  assert.equal(Buffer.from(await blank.arrayBuffer()).toString(), lines.join("\n") + "\n");
  const receipt = await fullQueryBlob(["one", "two"], "keep", "unresolved_receipt", 6);
  assert.equal(Buffer.from(await receipt.arrayBuffer()).toString(),
    lines.slice(0, 12).filter((_, index) => index % 2).join("\n") + "\n");
  assert.equal((await fullQueryBlob(["one", "two"], "not-present", "", 0)).size, 0);
  await assert.rejects(fullQueryBlob(["one", "two"], "keep", "", 11), /count changed/);
  global.fetch = async () => new Response("missing", { status: 404 });
  await assert.rejects(fullQueryBlob(["one"], "", "", 0), /HTTP 404/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(
        [node, "-e", check, str(ROOT / "web/cycle-evidence.js")],
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
    first, second = tmp_path / "first-archive", tmp_path / "second-archive"
    assert main([
        "--cycle-evidence", "--bill-evidence", str(metadata),
        "--archive-text", str(first), "--archive-text", str(second),
    ]) == 0
    assert captured[-1][3] == {"archive_text_evidence": (first, second)}
    with pytest.raises(SystemExit):
        main(["--archive-text", str(first)])


@pytest.mark.parametrize("option", [
    "--native-evidence", "--metadata-token-plan", "--receipt-evidence",
])
def test_cycle_cli_optional_sources_work_independently(
    cycle_bundle, optional_bundle, receipt_bundle, tmp_path, option,
):
    metadata, platform, *_ = cycle_bundle
    native, plan = optional_bundle
    main = runpy.run_path(str(ROOT / "scripts/build_site.py"))["main"]
    out = tmp_path / "preview"
    assert main([
        "--cycle-evidence", "--bill-evidence", str(metadata), "--platform-evidence", str(platform),
        option, str({
            "--native-evidence": native, "--metadata-token-plan": plan,
            "--receipt-evidence": receipt_bundle,
        }[option]), "--out", str(out),
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
    cycle_bundle, optional_bundle, receipt_bundle, tmp_path,
):
    metadata, platform, *_ = cycle_bundle
    native, plan = optional_bundle
    out = tmp_path / "preview"
    build_cycle_preview(
        metadata, platform, out, native_evidence=native, metadata_token_plan=plan,
        receipt_evidence=receipt_bundle,
    )
    result = subprocess.run([
        shutil.which("node"), str(ROOT / "tests/browser_cycle_site.cjs"), str(out),
        str(tmp_path / "browser-check"), os.environ["CYCLE_BROWSER_CHROME"], "fixture",
    ], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def session_bundle(cycle_bundle, optional_bundle, tmp_path, monkeypatch):
    """Small checksum-bound reviewed scopes; production scope pins are never relaxed."""
    from state_politics import site_evidence

    metadata, _, contexts, _, views, _ = cycle_bundle
    native, _ = optional_bundle
    manifest = json.loads((native / "manifest.json").read_text())
    registry = Path(manifest["inputs"]["registry"]["path"])
    config = yaml.safe_load(registry.read_text())
    overlaps = pq.read_table(native / "native_context_overlap.parquet").to_pylist()
    indexes = pq.read_table(native / "native_view_index.parquet").to_pylist()
    contracts = {}
    for state, scope, session in (
        ("NY", "ny-2023-2024", "2023-2024"), ("IL", "il-103rd", "103rd"),
    ):
        root = tmp_path / f"session-{state}"
        root.mkdir()
        spec = {
            "state": state, "root": str(root), "profile": "views",
            "contexts": "contexts.parquet", "views": "views.parquet",
            "context_id": "context_id", "allow_missing_identity": True,
            "identifier": (
                "original_source_record_json.identifier" if state == "NY" else "identifier"
            ),
            "source_only": {
                "selector": "original_source_record_json.population_kind",
                "values": ["native_untyped", "canonical_only"],
            },
            "preserve_context_fields": ["native_date_observations_json", "negative_flags_json"],
            "view_reader_allowlist": ["reader-a", "reader-b"],
        }
        if state == "NY":
            proof = root / "contract.json"
            write_json(proof, {
                "scope": "all 24,315 typed identities in the frozen 2023-2024 NY native census",
            })
            spec.update(canonical_session=session, binding_evidence=[{
                "path": str(proof), "sha256": sha256_file(proof), "selector": "scope",
                "expected": json.loads(proof.read_text())["scope"],
            }])
            manifest["inputs"]["NY_binding_evidence_0"] = input_pin(proof)
        else:
            spec.update(
                session_identifier="native_session_identifier", session_map={"103": session},
                context_granularity="source_reference",
            )
        raw, source_views = [], []
        size = 14 if state == "NY" else 15
        for index in range(size):
            source_only = index == size - 2
            bill_number = 1 if state == "IL" and index == 12 else index
            identifier = f"HB {0 if source_only else bill_number}"
            record = {
                "context_id": f"{state}:{index}", "identifier": identifier,
                "native_session_identifier": "104" if source_only and state == "IL" else "103",
                "original_source_record_json": json.dumps({
                    "identifier": identifier,
                    "population_kind": "canonical_only" if source_only else "native_identity",
                    "original_unknown": SOURCE_TEXT,
                }),
                "native_date_observations_json": '[{"printed_date":"2022-12-01"}]',
                "negative_flags_json": '["no_filing_or_version_certification"]',
                "analytical_admission": False,
            }
            raw.append(record)
            for reader in ["reader-a", "reader-b"] + (["excluded-markup"] if index == 1 else []):
                text = f"{SOURCE_TEXT}\n{state} FULL {index} {reader} SESSION-TAIL-{index}"
                source_views.append({
                    "view_id": f"{state}-view:{index}:{reader}", "context_id": record["context_id"],
                    "reader": reader, "text": text, "input_sha256": digest(text),
                    "n_input_characters": len(text), "source_record_sha256": digest(str(index)),
                    "original_source_sha256": digest(f"source {index}"),
                    "analytical_admission": False, "training_admission": False,
                })
            if index == 0:
                candidate = {
                    **contexts[1], "bill_id": f"{state}-bill:0", "state": state,
                    "session_identifier": session, "identifier": identifier,
                    "n_indexed_native_views": 2,
                }
                contexts.append(candidate)
                views.append({
                    **views[2],
                    **{key: candidate[key] for key in (
                        "bill_id", "state", "session_identifier", "identifier",
                    )},
                    "view_id": f"{state}-candidate:0",
                })
        pq.write_table(pa.Table.from_pylist(raw), root / "contexts.parquet")
        pq.write_table(pa.Table.from_pylist(source_views), root / "views.parquet")
        write_json(root / "manifest.json", {"files": {
            name: sha256_file(root / name) for name in ("contexts.parquet", "views.parquet")
        }})
        spec["manifest_sha256"] = sha256_file(root / "manifest.json")
        normalized_contexts, normalized_views = normalize_packet(
            spec, pq.read_table(root / "contexts.parquet").to_pandas(),
            pq.read_table(root / "views.parquet").to_pandas(),
        )
        spec.update(
            expected_contexts=len(normalized_contexts), expected_views=len(normalized_views),
        )
        for index, row in enumerate(
            pa.Table.from_pandas(normalized_contexts, preserve_index=False).to_pylist()
        ):
            joined = index < size - 2
            bill_number = 1 if state == "IL" and index == 12 else index
            overlaps.append({
                **row, "bill_id": f"{state}-bill:{bill_number}" if joined else None,
                "identifier": row["native_identifier"],
                "canonical_join_basis": (
                    "unique_declared_session_typed_identity" if joined
                    else "source_only_unresolved_identity"
                    if row["canonical_join_mode"] == "source_only"
                    else "native_only_unmatched"
                ),
                "source_introduction_date": "2022-12-01" if index == 1 else "",
                "window_disposition": (
                    "source_introduction_before_window" if index == 1
                    else "no_source_introduction_action"
                ),
                "date_evidence_status": row["native_window_disposition"],
            })
        indexes.extend(pa.Table.from_pandas(normalized_views, preserve_index=False).to_pylist())
        config["packets"].append(spec)
        for role, name in (
            ("manifest", "manifest.json"), ("contexts", "contexts.parquet"),
            ("views", "views.parquet"),
        ):
            manifest["inputs"][f"{state}_{role}"] = input_pin(root / name)
        contracts[scope] = {
            "state": state, "session_identifier": session, "packet_root": str(root),
            "packet_spec_sha256": digest(json.dumps(
                spec, sort_keys=True, ensure_ascii=True, allow_nan=False,
            )),
        }
    monkeypatch.setattr(site_evidence, "NATIVE_SESSION_SCOPES", contracts)
    registry.write_text(yaml.safe_dump(config))
    manifest["inputs"]["registry"] = input_pin(registry)
    write_json(native / "manifest.json", manifest)
    overlap_columns = dict.fromkeys(key for row in overlaps for key in row)
    pq.write_table(pa.Table.from_pylist([
        {key: row.get(key) for key in overlap_columns} for row in overlaps
    ]), native / "native_context_overlap.parquet")
    pq.write_table(pa.Table.from_pylist(indexes), native / "native_view_index.parquet")
    repin_optional(native)
    pq.write_table(pa.Table.from_pylist(contexts), metadata / "bill_evidence.parquet")
    pq.write_table(pa.Table.from_pylist(views), metadata / "candidate_metadata_views.parquet")
    matrix = csv.read_csv(metadata / "state_matrix.csv").to_pylist()
    for row in matrix:
        if row["state"] in {"NY", "IL"}:
            for key in (
                "n_retained_contexts_wider_history", "n_cycle_evidence_candidate_contexts",
                "n_filing_or_introduction_in_window", "n_cycle_metadata_candidate_views",
                "n_cycle_contexts_with_indexed_native_text",
            ):
                row[key] = 1
    csv.write_csv(pa.Table.from_pylist(matrix), metadata / "state_matrix.csv")
    report = json.loads((metadata / "report.json").read_text())
    report["n_cycle_contexts"] += 2
    report["n_metadata_candidate_views_not_bills"] += 2
    report["cohort_scope_counts"][COHORTS[0]] += 2
    write_json(metadata / "report.json", report)
    manifest = json.loads((metadata / "manifest.json").read_text())
    manifest["inputs"]["native_manifest"] = input_pin(native / "manifest.json")
    write_json(metadata / "manifest.json", manifest)
    repin(metadata)
    return native, tuple(contracts)


def test_reviewed_session_sources_preserve_full_strings_references_and_no_admissions(
    cycle_bundle, session_bundle, receipt_bundle, tmp_path,
):
    metadata, platform, *_ = cycle_bundle
    native, scopes = session_bundle
    baseline = tmp_path / "baseline"
    old = build_cycle_preview(
        metadata, platform, baseline, native_evidence=native, receipt_evidence=receipt_bundle,
    )
    out = tmp_path / "preview"
    result = build_cycle_preview(
        metadata, platform, out, native_evidence=native, native_session_scopes=scopes,
        receipt_evidence=receipt_bundle,
    )
    assert "producer_archive" not in old
    assert not (baseline / "downloads/producers").exists()
    assert old["counts"] == {
        key: value for key, value in result["counts"].items()
        if key != "native_session_source_evidence"
    }
    for name, binding in result["producer_archive"].items():
        archived = out / binding["path"]
        assert archived.read_bytes() == (ROOT / binding["original_path"]).read_bytes()
        assert sha256_file(archived) == binding["sha256"]
        assert result["outputs"][binding["path"]]["sha256"] == binding["sha256"]
        assert name == archived.name
    assert result["producer_sha256"] == result["producer_archive"]["site_evidence.py"]["sha256"]
    assert result["entrypoint_sha256"] == result["producer_archive"]["build_site.py"]["sha256"]
    assert result["inputs"]["native_evidence"]["normalizer_sha256"] == (
        result["producer_archive"]["study_native_overlap.py"]["sha256"]
    )
    for path in (baseline / "evidence").iterdir():
        assert path.read_bytes() == (out / "evidence" / path.name).read_bytes()
    counts = result["counts"]["native_session_source_evidence"]
    assert counts["other_states_and_sessions"] == "unknown_not_supplied"
    for state, scope, expected in (
        ("NY", scopes[0], (22, 11, 11)), ("IL", scopes[1], (24, 12, 11)),
    ):
        values = counts["scopes"][scope]
        assert (
            values["exported_views"], values["exported_references"],
            values["exported_unique_canonical_bills"],
        ) == expected
        assert values["candidate_excluded_views"] == 2
        assert values["reader_excluded_views"] == 1
        rows = [json.loads(line) for line in
                (out / f"evidence/native-session-{state}.jsonl").read_text().split("\n") if line]
        with gzip.open(out / f"downloads/native-session-{state}.jsonl.gz", "rt") as handle:
            assert rows == [json.loads(line) for line in handle]
        for row in rows:
            assert row["bill_id"] != f"{state}-bill:0"
            assert row["source_type"] == "native_session_text"
            assert row["scope_label"].startswith("Publisher-session-bound evidence OUTSIDE")
            assert "bill_context" not in row and "title" not in row and "token_plan" not in row
            assert row["input_sha256"] == digest(row["text"])
            assert row["text"].startswith(SOURCE_TEXT)
            assert all(row[key] is False for key in (
                "model_input_approved", "training_admission", "analytical_admission",
                "native_identity_certified", "filing_time_text_certified",
                "candidate_cohort_member", "eligible_cycle_admission",
            ))
            assert row["source_context_record"]["native_date_observations_json"] == (
                '[{"printed_date":"2022-12-01"}]'
            )
            assert row["source_text_bindings"] == {"source_record.text": "text"}
        outside = [row for row in rows if row["identifier"] == "HB 1"]
        assert all(row["native_context"]["source_introduction_date"] == "2022-12-01"
                   for row in outside if row["context_id"].endswith(":1"))
        assert values["source_window_dispositions_by_reference"][
            "source_introduction_before_window"
        ] == 1
    html = (out / "index.html").read_text()
    assert html.count("Unknown — no reviewed publisher-session scope supplied") == 48
    assert 'value="native_session_text"' in html
    assert "not eligible 2023–2024" in html


def test_independent_session_frame_retains_all_members_and_full_downloads(
    cycle_bundle, session_bundle, tmp_path,
):
    from state_politics import site_evidence
    from state_politics.analysis.prepare_session_cohort import freeze_session_cohort

    metadata, platform, _, _, _, _ = cycle_bundle
    native, scopes = session_bundle
    native_rows = pq.read_table(native / "native_context_overlap.parquet").to_pylist()
    contracts = {
        spec["packet_root"]: spec for spec in site_evidence.NATIVE_SESSION_SCOPES.values()
    }
    bills = {}
    for row in native_rows:
        contract = contracts.get(row["packet_root"])
        if contract and site_evidence._session_exact_match(row, contract):
            bills[row["bill_id"]] = {
                **{key: row[key] for key in (
                    "bill_id", "state", "identifier", "session_identifier",
                )}, "title": SOURCE_TEXT, "source_extra": 1792612374203564526,
                "source_introduction_date": None,
            }
    original_bills = tmp_path / "original_bills.parquet"
    pq.write_table(pa.Table.from_pylist(list(bills.values())), original_bills)
    original_abstracts = tmp_path / "original_abstracts.parquet"
    pq.write_table(pa.Table.from_pylist([{
        "id": "new-full-abstract", "bill_id": "NY-bill:1",
        "abstract": SOURCE_TEXT + " full abstract ending", "note": "full note",
    }]), original_abstracts)
    original_ledger = tmp_path / "original_ledger.csv"
    csv.write_csv(pa.Table.from_pylist([{
        **{key: bill[key] for key in (
            "bill_id", "state", "identifier", "session_identifier",
        )}, "source_filing_date": "2022-12-15" if bill["bill_id"] == "NY-bill:1" else "",
        "unknown_original_field": SOURCE_TEXT,
    } for bill in bills.values()]), original_ledger)
    manifest = json.loads((metadata / "manifest.json").read_bytes())
    manifest["inputs"].update(
        bills=input_pin(original_bills), abstracts=input_pin(original_abstracts),
        ledger=input_pin(original_ledger),
    )
    write_json(metadata / "manifest.json", manifest)
    preview = tmp_path / "session-preview"
    build_cycle_preview(
        metadata, platform, preview, native_evidence=native, native_session_scopes=scopes,
    )
    original_manifest = (metadata / "manifest.json").read_bytes()
    out = tmp_path / "independent-frame"
    result = freeze_session_cohort(metadata, native, preview, out, scopes=scopes)
    assert result["counts"]["session_members"] == 24
    assert result["counts"]["native_references"] == 25
    assert result["counts"]["complete_native_views"] == 50
    assert result["counts"]["session_only_members"] == 22
    assert result["counts"]["also_calendar_candidates"] == 2
    assert result["all_states_accounted"] == 50
    assert result["new_primary_cohort_admissions"] == 0
    assert result["event_dates_inferred"] is False
    assert result["excluded_native_contexts_preserved"] == 4
    assert result["inputs_before"] == result["inputs_after"]
    assert (metadata / "manifest.json").read_bytes() == original_manifest
    members = [json.loads(raw) for raw in (out / "session_members.jsonl").read_bytes().split(b"\n")
               if raw]
    before_date = next(row for row in members if row["bill_id"] == "NY-bill:1")
    assert before_date["source_bill"]["source_introduction_date"] is None
    assert before_date["native_contexts"][0]["source_introduction_date"] == "2022-12-01"
    assert before_date["calendar_candidate_member"] is False
    assert before_date["abstract_records"][0]["note"] == "full note"
    assert before_date["source_date_ledger"]["source_filing_date"] == "2022-12-15"
    assert before_date["source_date_ledger"]["unknown_original_field"] == SOURCE_TEXT
    for state, expected in (("NY", 24), ("IL", 26)):
        raw = (out / f"native-{state}.jsonl").read_bytes()
        assert gzip.decompress((out / f"native-{state}.jsonl.gz").read_bytes()) == raw
        exported = [json.loads(line) for line in raw.split(b"\n") if line]
        assert len(exported) == expected
        assert all(row["text"].endswith(f"SESSION-TAIL-{row['context_id'].split(':')[1]}")
                   for row in exported)
    comparison = csv.read_csv(out / "state_comparison.csv").to_pylist()
    assert len(comparison) == 50
    assert next(row for row in comparison if row["state"] == "ME")["session_members"] is None
    for name, entry in result["artifacts"].items():
        assert sha256_file(out / name) == entry["sha256"]
    with pytest.raises(FileExistsError):
        freeze_session_cohort(metadata, native, preview, out, scopes=scopes)


@pytest.mark.parametrize("defect", [
    "unknown_scope", "missing_native", "changed_selector", "proof_checksum", "proof_value",
    "source_only_alias", "duplicate_scope",
])
def test_reviewed_session_scope_and_proof_fail_closed(
    cycle_bundle, session_bundle, tmp_path, defect,
):
    from state_politics import site_evidence

    metadata, platform, *_ = cycle_bundle
    native, scopes = session_bundle
    manifest = json.loads((native / "manifest.json").read_text())
    registry = Path(manifest["inputs"]["registry"]["path"])
    config = yaml.safe_load(registry.read_text())
    spec = next(spec for spec in config["packets"] if spec["state"] == "NY")
    if defect == "unknown_scope":
        scopes = ("ny-2025-2026",)
    elif defect == "duplicate_scope":
        scopes = (scopes[0], scopes[0])
    elif defect == "changed_selector":
        spec["source_only"]["values"] = []
        registry.write_text(yaml.safe_dump(config))
        manifest["inputs"]["registry"] = input_pin(registry)
    elif defect in {"proof_checksum", "proof_value"}:
        proof = Path(spec["binding_evidence"][0]["path"])
        write_json(proof, {"scope": "some unrelated historical/current archive"})
        if defect == "proof_value":
            spec["binding_evidence"][0]["sha256"] = sha256_file(proof)
            manifest["inputs"]["NY_binding_evidence_0"] = input_pin(proof)
            registry.write_text(yaml.safe_dump(config))
            manifest["inputs"]["registry"] = input_pin(registry)
            site_evidence.NATIVE_SESSION_SCOPES[scopes[0]]["packet_spec_sha256"] = digest(
                json.dumps(spec, sort_keys=True, ensure_ascii=True, allow_nan=False)
            )
    elif defect == "source_only_alias":
        path = native / "native_context_overlap.parquet"
        rows = pq.read_table(path).to_pylist()
        next(row for row in rows if row["context_id"] == "NY:12")["bill_id"] = "NY-bill:0"
        pq.write_table(pa.Table.from_pylist(rows), path)
    write_json(native / "manifest.json", manifest)
    repin_optional(native)
    manifest = json.loads((metadata / "manifest.json").read_text())
    manifest["inputs"]["native_manifest"] = input_pin(native / "manifest.json")
    write_json(metadata / "manifest.json", manifest)
    repin(metadata)
    out = tmp_path / "preview"
    with pytest.raises(ValueError):
        build_cycle_preview(
            metadata, platform, out, native_evidence=None if defect == "missing_native" else native,
            native_session_scopes=scopes,
        )
    assert not out.exists()


def test_reviewed_session_cli_requires_explicit_native_and_opt_in(
    cycle_bundle, session_bundle, tmp_path,
):
    metadata, platform, *_ = cycle_bundle
    native, scopes = session_bundle
    main = runpy.run_path(str(ROOT / "scripts/build_site.py"))["main"]
    for args in ([], ["--cycle-evidence"], ["--native-evidence", str(native)]):
        with pytest.raises(SystemExit):
            main([*args, "--native-session-scope", scopes[0]])
    out = tmp_path / "preview"
    assert main([
        "--cycle-evidence", "--bill-evidence", str(metadata), "--platform-evidence", str(platform),
        "--native-evidence", str(native), "--native-session-scope", scopes[0], "--out", str(out),
    ]) == 0
    assert (out / "evidence/native-session-NY.jsonl").exists()
    assert not (out / "evidence/native-session-IL.jsonl").exists()


@pytest.mark.skipif(not os.environ.get("CYCLE_BROWSER_CHROME"), reason="No real browser configured")
def test_cycle_real_browser_reviewed_session_sources(
    cycle_bundle, session_bundle, receipt_bundle, tmp_path,
):
    metadata, platform, *_ = cycle_bundle
    native, scopes = session_bundle
    out = tmp_path / "preview"
    build_cycle_preview(
        metadata, platform, out, native_evidence=native, native_session_scopes=scopes,
        receipt_evidence=receipt_bundle,
    )
    result = subprocess.run([
        shutil.which("node"), str(ROOT / "tests/browser_cycle_site.cjs"), str(out),
        str(tmp_path / "browser-check"), os.environ["CYCLE_BROWSER_CHROME"], "fixture",
    ], capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr

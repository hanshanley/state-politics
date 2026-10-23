import copy
import hashlib
import json
import shutil
import uuid
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from state_politics.bills import ok_retained_context_text as ok

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "data/processed/retained-url-cross-context-ok-conditional-eligibility-20261023-v1"
HOUSE = REPO / "data/processed/ok-house-rules-context-20261023-v1"
QUEUE = REPO / "outputs/recreated-2023-2024-v14/chart-data/missing_retained_text.parquet"


@pytest.fixture(scope="module")
def packet():
    if not all(path.exists() for path in (SOURCE, HOUSE, QUEUE)):
        pytest.skip("actual sealed Oklahoma evidence is not available")
    workspace = REPO / "data/processed" / f"ok-retained-context-tests-{uuid.uuid4().hex}"
    workspace.mkdir()
    try:
        out = workspace / "packet"
        ok.build_ok_retained_context(SOURCE, HOUSE, QUEUE, out)
        yield out
    finally:
        shutil.rmtree(workspace)


@pytest.fixture(scope="module")
def original_data(packet):
    proof = ok._house_witnesses(HOUSE)
    data = ok._data(SOURCE, pq.read_table(QUEUE), HOUSE)
    sources = list(ok._rows(SOURCE / "ok_witness_source_records.original.jsonl"))
    return data, proof, sources


def repin(packet, name):
    path = packet / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["packet_artifacts"][name] = ok._binding(packet / name)
    ok._write(path, manifest)


def test_actual_primary_HTML_replay_and_all_complete_originals(packet):
    views, contexts, pins, manifest = ok.load_ok_retained_context(packet, pq.read_table(QUEUE))
    assert len(views) == len(contexts) == 2000
    assert len(pins) == len(manifest["packet_artifacts"]) + 1
    assert manifest["counts"]["source_witnesses"] == 2135
    assert manifest["counts"]["rejected_source_witnesses"] == 135
    assert manifest["counts"]["introduced_stage_diagnostics_not_filing_certified"] == 1932
    proof = ok._json(packet / "reviewed_house_replay.json")
    assert set(proof["witnesses"]) == {"2023", "2024"}
    assert proof["witnesses"]["2024"]["literal_visible_publication_date_node"]["text"] == (
        "Jan 19, 2024"
    )
    assert "news-20230119_1" in proof["witnesses"]["2024"]["capture"]["url"]
    full_queue = pq.read_table(QUEUE)
    ids = {row["bill_id"] for row in contexts}
    assert pq.read_table(packet / "input_gap_queue.parquet").equals(full_queue, check_metadata=True)
    assert pq.read_table(packet / "context_inventory.parquet").equals(
        full_queue.filter([row["bill_id"] in ids for row in full_queue.to_pylist()]),
        check_metadata=True,
    )
    dispositions = pq.read_table(packet / "candidate_dispositions.parquet")
    assert dispositions.num_rows == 21562
    assert dispositions.select(full_queue.schema.names).equals(full_queue, check_metadata=True)
    assert all(row["source_version"]["all_original_target_alternatives"]["links"] for row in views)
    assert len({row["view_id"] for row in views}) == 2000
    for row in views:
        assert row["view_id"].startswith("ok-retained-context:")
        assert row["text"] == row["source_record"]["source_record"]["raw_text"]
        assert row["text"] == row["source_searchablebill_record"]["raw_text"]
        assert hashlib.sha256(row["text"].encode()).hexdigest() == row["raw_text_sha256"]
        assert row["source_identity"]["session_identifier"] == "2023"
        assert row["session_identifier"] == "2024"
        assert row["target_context"]["bill_id"] == row["bill_id"]
        assert row["original_target_context"] == row["target_context"]
        assert row["context_relation"]["kind"] == (
            "same_legislature_exact_existing_document_pointer"
        )
        assert row["context_relation"]["source_session_identifier"] == "2023"
        assert row["context_relation"]["target_session_identifier"] == "2024"
        assert set(row["context_relation"]["primary_session_context_witnesses"]) == {"2023", "2024"}
        assert row["original_source_metadata"]["bill_id"] != row["bill_id"]
        assert row["source_version"]["link"]["url"] == row["source_version"]["target_link"]["url"]
        assert " " in row["source_version"]["link"]["url"]
        assert row["archive_generated_prologue_preserved"] is False
        assert all(row[flag] is False for flag in ok.FLAGS)
        for span in row["source_identity"]["printed_evidence"]:
            assert row["text"][span["start"]:span["end"]] == span["text"]
    assert any(len(row["text"]) > 20000 for row in views)
    assert any(not row["introduced_stage_diagnostic_not_filing_certification"] for row in views)
    for name, binding in ok._inventory(SOURCE, ok.CONDITIONAL_SHA256).items():
        assert ok._binding(packet / "source-conditional" / name) == binding


def test_plain_raw_text_existing_inference_entry_is_cache_compatible(packet):
    from state_politics.analysis.cycle_topics import input_text, make_input

    row = next(ok._rows(packet / "views.jsonl"))[1]
    archived = make_input(row, "retained_text", "archive-OK.jsonl", 1)
    old = make_input(row["source_record"], "retained_text", "snapshot-OK.jsonl", 1)
    assert archived["input_sha256"] == old["input_sha256"] == row["raw_text_sha256"]
    assert archived["domain"] == old["domain"] == "bill"
    assert archived["source_text_span"] == [0, len(row["text"])]
    assert input_text(archived) == input_text(old) == row["text"]
    assert archived["archive_machine_prologue_excluded_from_inference"] is False


@pytest.mark.parametrize("defect", [
    "truncated_text", "typed_body", "source_session", "approval",
    "prologue", "original_context_null", "version_url", "report",
    "relation_kind", "relation_source_session", "relation_target_session",
])
def test_repinned_outputs_cannot_change_full_bodies_metadata_or_approvals(packet, defect):
    name = "report.json" if defect == "report" else "views.jsonl"
    path, manifest_path = packet / name, packet / "manifest.json"
    saved, saved_manifest = path.read_bytes(), manifest_path.read_bytes()
    try:
        if defect == "report":
            report = ok._json(path)
            report["counts"]["text_views"] -= 1
            ok._write(path, report)
        else:
            with path.open("rb") as stream:
                first, rest = stream.readline(), stream.read()
            row = json.loads(first)
            if defect == "truncated_text":
                row["text"] = row["text"].rstrip()
                if row["text"] == json.loads(first)["text"]:
                    row["text"] = row["text"][:-1]
                row["raw_text_sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
            elif defect == "typed_body":
                row["text"] = row["text"].replace("HOUSE BILL", "SENATE BILL", 1)
                if row["text"] == json.loads(first)["text"]:
                    row["text"] = "HOUSE BILL 99999\n" + row["text"]
            elif defect == "source_session":
                row["source_identity"]["session_identifier"] = "2024"
            elif defect == "approval":
                row["model_input_approved"] = 0
            elif defect == "prologue":
                row["archive_generated_prologue_preserved"] = True
            elif defect == "original_context_null":
                key = next(k for k, v in row["target_context"].items() if v is None)
                row["target_context"][key] = ""
            elif defect == "relation_kind":
                row["context_relation"]["kind"] = "session_alias"
            elif defect == "relation_source_session":
                row["context_relation"]["source_session_identifier"] = "2024"
            elif defect == "relation_target_session":
                row["context_relation"]["target_session_identifier"] = "2023"
            else:
                row["source_version"]["target_link"]["url"] = (
                    row["source_version"]["target_link"]["url"].replace(" ", "%20")
                )
            path.write_bytes(json.dumps(row, ensure_ascii=False).encode() + b"\n" + rest)
        repin(packet, name)
        with pytest.raises(ValueError, match="replay mismatch"):
            ok.load_ok_retained_context(packet)
    finally:
        path.write_bytes(saved)
        manifest_path.write_bytes(saved_manifest)


@pytest.mark.parametrize("defect", ["wrong_year", "hidden_only", "absent_primary_proof"])
def test_primary_context_is_rederived_from_actual_visible_raw_HTML(packet, defect):
    root = packet / "reviewed-context"
    path = root / ("raw/004-2024-session-announcement.body" if defect != "absent_primary_proof"
                   else "reviewed-session-context.json")
    saved = path.read_bytes()
    try:
        if defect == "wrong_year":
            path.write_bytes(saved.replace(b"Jan 19, 2024", b"Jan 19, 2023"))
        elif defect == "hidden_only":
            text = saved.decode().replace(
                "second regular session of the 59th Legislature",
                "unproved regular session of the 59th Legislature",
            )
            path.write_text(
                text + "<script>second regular session of the 59th Legislature</script>"
            )
        else:
            path.write_text("{}")
        with pytest.raises((ValueError, KeyError), match="context|binding|evidence"):
            ok._house_witnesses(root)
    finally:
        path.write_bytes(saved)


@pytest.mark.parametrize("defect", ["encoded_url", "source_session", "special_session"])
def test_actual_original_relation_quarantines_unsupported_context_or_url(original_data, defect):
    original, proof, sources = original_data
    ordinal, source, digest = next(
        item for item in sources if item[1]["identifier"] == "HB 1375"
    )
    data = copy.deepcopy(original)
    if defect == "encoded_url":
        url = source["source_version"]["link"]["url"]
        data["target_links_by_url"][url.replace(" ", "%20")] = data["target_links_by_url"].pop(url)
    elif defect == "source_session":
        data["metadata"][source["bill_id"]]["session_identifier"] = "2024"
    else:
        link = data["target_links_by_url"][source["source_version"]["link"]["url"]][0]
        data["metadata"][link["bill_id"]]["session_name"] = "2024 Special Session"
    emitted, disposition = ok._derive_source(source, ordinal, digest, data, proof)
    assert not emitted and disposition["negative_conditions"]


def test_actual_excluded_types_headerless_and_2022_bodies_remain_negative(original_data):
    data, proof, sources = original_data
    seen = set()
    for ordinal, source, digest in sources:
        if source["identifier"].startswith(("HR ", "HCR ", "HJR ")):
            emitted, disposition = ok._derive_source(source, ordinal, digest, data, proof)
            assert not emitted
            if source["identifier"].startswith(("HR ", "HCR ")):
                assert "excluded_simple_concurrent_or_unsupported_document_type" in (
                    disposition["negative_conditions"]
                )
            else:
                assert "missing_or_wrong_exact_primary_typed_own_bill" in (
                    disposition["negative_conditions"]
                )
            seen.add(source["identifier"].split()[0])
    assert seen == {"HR", "HCR", "HJR"}
    text = "STATE OF OKLAHOMA\n1st Session of the 59th Legislature (2022)\nHOUSE BILL 1375"
    assert ok._printed(text, "HB 1375")["first_59th_2023_present"] is False
    assert ok._printed(text.replace("1375", "1376"), "HB 1375")[
        "exact_own_typed_identifier"
    ] is False


def test_actual_source_with_unbound_machine_prologue_flag_is_quarantined(original_data):
    data, proof, sources = original_data
    ordinal, original, digest = next(
        item for item in sources if item[1]["identifier"] == "HB 1375"
    )
    source = copy.deepcopy(original)
    source["archive_generated_prologue_preserved"] = True
    emitted, disposition = ok._derive_source(source, ordinal, digest, data, proof)
    assert not emitted
    assert "unbound_or_conflicting_machine_prologue_metadata" in disposition["negative_conditions"]


@pytest.mark.parametrize("defect,reason", [
    ("provider_error", "original_searchablebill_provider_error"),
    ("missing_error_flag", "original_searchablebill_error_flag_missing_or_unrecognized"),
    ("boolean_error_flag", "original_searchablebill_error_flag_missing_or_unrecognized"),
    ("missing_fk", "original_searchablebill_version_fk_missing_or_unresolved"),
    ("missing_selected_version", "original_searchablebill_text_version_fk_conflict"),
    ("cross_bill_fk", "original_searchablebill_text_version_fk_conflict"),
    ("ambiguous_fk", "original_snapshot_version_fk_missing_or_ambiguous"),
    ("empty_body", "original_searchablebill_body_missing_or_empty"),
    ("missing_noerror_fact", "original_snapshot_nonempty_noerror_facts_missing_or_inconsistent"),
])
def test_original_provider_and_text_FK_guard_never_recovers_typed_looking_errors(
    original_data, defect, reason,
):
    original_data_map, proof, sources = original_data
    ordinal, original_source, digest = next(
        item for item in sources if item[1]["identifier"] == "HB 1375"
    )
    source, data = copy.deepcopy(original_source), copy.deepcopy(original_data_map)
    source_id = source["bill_id"]
    original = data["searchable"][source_id]
    if defect == "provider_error":
        original["is_error"] = source["source_record"]["is_error"] = "t"
    elif defect == "missing_error_flag":
        original.pop("is_error")
        source["source_record"].pop("is_error")
    elif defect == "boolean_error_flag":
        original["is_error"] = source["source_record"]["is_error"] = False
    elif defect == "missing_fk":
        original["version_link_id"] = source["source_record"]["version_link_id"] = None
        source["source_version"] = {"link": None, "version": None}
    elif defect == "cross_bill_fk":
        other = next(row for row in data["links"].values() if row["bill_id"] != source_id)
        original["version_link_id"] = source["source_record"]["version_link_id"] = other["id"]
    elif defect == "missing_selected_version":
        source["source_version"] = None
    elif defect == "ambiguous_fk":
        source["source_context"]["exact_version_foreign_keys"] = False
        source["source_context"]["source_reference_status"] = "multiple_version_links"
    elif defect == "empty_body":
        original["raw_text"] = source["source_record"]["raw_text"] = " \n"
    else:
        source["source_context"].pop("source_noerror")
    data["snapshot_contexts"][source_id] = copy.deepcopy(source["source_context"])
    saved_source = copy.deepcopy(source)
    emitted, disposition = ok._derive_source(source, ordinal, digest, data, proof)
    assert not emitted
    assert reason in disposition["negative_conditions"]
    assert source == saved_source


def test_manifest_has_every_shared_archive_approval_false(packet):
    from state_politics.bills.research_corpus_text import FLAGS

    manifest = ok._json(packet / "manifest.json")
    assert manifest["packet_artifacts"]
    assert all(manifest["approvals"][flag] is False for flag in FLAGS)


def test_safe_outputs_paths_and_repinned_original_inputs_fail_closed(packet):
    with pytest.raises(ValueError, match="new unlinked output"):
        ok.build_ok_retained_context(SOURCE, HOUSE, QUEUE, packet)
    for unsafe in ("../outside", "/outside", "a/../b", "a\\b"):
        with pytest.raises(ValueError, match="unsafe"):
            ok._relative(unsafe)
    path = packet / "source-conditional/ok_witness_session_conditions.parquet"
    saved = path.read_bytes()
    manifest_path = packet / "manifest.json"
    saved_manifest = manifest_path.read_bytes()
    try:
        path.write_bytes(saved + b"repinned corruption")
        repin(packet, path.relative_to(packet).as_posix())
        with pytest.raises(ValueError, match="immutable source binding"):
            ok.load_ok_retained_context(packet)
    finally:
        path.write_bytes(saved)
        manifest_path.write_bytes(saved_manifest)
    linked = packet / "unexpected-link"
    linked.symlink_to(packet / "views.jsonl")
    try:
        with pytest.raises(ValueError, match="linked"):
            ok.load_ok_retained_context(packet)
    finally:
        linked.unlink()

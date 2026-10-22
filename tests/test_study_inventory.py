"""A shared state catalog preserves source records without inflating native identities."""

import hashlib
import json

import pyarrow as pa
import pyarrow.csv as arrow_csv
import pytest
import yaml

from state_politics.bills.study_inventory import FLAGS, build_catalog, reconcile_records
from state_politics.site_evidence import STATES


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def packet_manifest(root):
    result = {"files": {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.iterdir() if path.is_file() and path.name != "manifest.json"
    }, **dict.fromkeys(FLAGS, False)}
    write_json(root / "manifest.json", result)
    return result


def source_record(number):
    return {
        "source_record_id": f"physical:{number}", "native_id": "NV:2023:AB 1", "state": "NV",
        "full_original_field": "complete\u2028source\u2029ending",
        "source_stat": 1792612374203564526,
        **dict.fromkeys(FLAGS, False),
    }


def state_reports():
    return {
        state: {
            "status": "publisher_list_returned" if state == "NV" else "outside_this_bounded_batch",
            "observed_native_records": 2 if state == "NV" else 0,
            "observed_native_identities": 1 if state == "NV" else 0,
            "new_full_original_documents": 0, **dict.fromkeys(FLAGS, False),
        } for state in STATES
    }


def test_native_identity_counts_do_not_count_repeated_prefix_as_new_bill():
    rows = [source_record(1), source_record(2)]
    result = reconcile_records(rows, state_reports(), ["NV"])
    assert result["NV"][0] == rows
    assert result["NV"][2] == 1
    assert len(result["NV"][0]) == 2


@pytest.mark.parametrize("defect", ["duplicate", "approval", "identity_count", "outside"])
def test_catalog_refuses_ambiguous_counts_and_admission(defect):
    rows, reports = [source_record(1), source_record(2)], state_reports()
    if defect == "duplicate":
        rows[1]["source_record_id"] = rows[0]["source_record_id"]
    elif defect == "approval":
        rows[0]["model_approval"] = True
    elif defect == "identity_count":
        reports["NV"]["observed_native_identities"] = 2
    else:
        reports["NV"]["status"] = "outside_this_bounded_batch"
    with pytest.raises(ValueError):
        reconcile_records(rows, reports, ["NV"])


@pytest.fixture
def catalog_inputs(tmp_path):
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    arrow_csv.write_csv(pa.Table.from_pylist([
        {"state": state, "n_cycle_evidence_candidate_contexts": 2 if state == "NV" else 0}
        for state in sorted(STATES)
    ]), metadata / "state_matrix.csv")
    write_json(metadata / "report.json", {"status": "unchanged metadata fixture"})
    write_json(metadata / "manifest.json", {
        "schema_version": 1,
        "status": "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted",
        "inputs_unchanged": True, "model_input_approved": False, "analytical_admission": False,
        "artifacts": {name: {
            "sha256": hashlib.sha256((metadata / name).read_bytes()).hexdigest(),
            "bytes": (metadata / name).stat().st_size,
        } for name in ("state_matrix.csv", "report.json")},
    })
    tracker = tmp_path / "tracker.md"
    tracker.write_text("\n".join(
        f"| State ({state}) | Inventory | Remaining native gap | Retained source |"
        for state in sorted(STATES)
    ))
    raw = tmp_path / "raw"
    raw.mkdir()
    raw_bytes = b"Every original response byte, not reconstructed."
    (raw / "response.body").write_bytes(raw_bytes)
    packet_manifest(raw)
    processed = tmp_path / "processed"
    processed.mkdir()
    write_json(processed / "report.json", {"states": state_reports()})
    (processed / "native_source_records.jsonl").write_text(
        "".join(json.dumps(source_record(i), ensure_ascii=False) + "\n" for i in (1, 2)),
        encoding="utf-8",
    )
    p = packet_manifest(processed)
    p["inputs"] = {"raw_manifest": {
        "path": str(raw / "manifest.json"),
        "sha256": hashlib.sha256((raw / "manifest.json").read_bytes()).hexdigest(),
    }}
    write_json(processed / "manifest.json", p)
    registry = tmp_path / "registry.yml"
    entry = {
        "packet_id": "test-native", "directory": str(processed), "effective_states": ["NV"],
        "manifest_sha256": hashlib.sha256((processed / "manifest.json").read_bytes()).hexdigest(),
        "raw_archives": [{
            "directory": str(raw),
            "manifest_sha256": hashlib.sha256((raw / "manifest.json").read_bytes()).hexdigest(),
        }],
    }
    registry.write_text(yaml.safe_dump({"schema_version": 1, "packets": [entry]}))
    return registry, metadata, tracker, processed, raw, raw_bytes


def test_shared_catalog_copies_every_original_field_and_raw_byte(catalog_inputs, tmp_path):
    registry, metadata, tracker, processed, _, raw_bytes = catalog_inputs
    out = tmp_path / "catalog"
    result = build_catalog(registry, metadata, tracker, out)
    assert result["states_accounted_for"] == 50
    assert result["effective_native_record_observations"] == 2
    assert result["effective_native_identity_observations"] == 1
    assert result["calendar_candidates_unchanged"] == 2
    assert result["inputs_before"] == result["inputs_after"]
    assert (out / "packets/test-native/raw-0/response.body").read_bytes() == raw_bytes
    assert (out / "packets/test-native/processed/native_source_records.jsonl").read_bytes() == (
        processed / "native_source_records.jsonl"
    ).read_bytes()
    rows = [json.loads(raw) for raw in (out / "effective_native_records.jsonl").read_bytes()
            .split(b"\n") if raw]
    assert [row["original_record"] for row in rows] == [source_record(1), source_record(2)]
    states = arrow_csv.read_csv(out / "state_inventory_matrix.csv").to_pylist()
    nv = next(row for row in states if row["state"] == "NV")
    assert nv["native_source_record_observations"] == 2
    assert nv["distinct_native_source_identity_observations"] == 1
    assert nv["duplicate_identity_observations_preserved"] == 1
    unsupplied = next(row for row in states if row["state"] == "ME")
    assert unsupplied["native_source_record_observations"] is None
    assert unsupplied["zero_activity_inferred"] is False
    assert all(result[flag] is False for flag in FLAGS)
    for name, entry in result["artifacts"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == entry["sha256"]
    with pytest.raises(FileExistsError):
        build_catalog(registry, metadata, tracker, out)


def test_catalog_requires_explicit_nonoverlapping_state_selection(catalog_inputs, tmp_path):
    registry, metadata, tracker, *_ = catalog_inputs
    config = yaml.safe_load(registry.read_text())
    config["packets"].append({**config["packets"][0], "packet_id": "duplicate-effective-state"})
    registry.write_text(yaml.safe_dump(config))
    out = tmp_path / "rejected"
    with pytest.raises(ValueError, match="nonoverlapping effective states"):
        build_catalog(registry, metadata, tracker, out)
    assert not out.exists()


def test_catalog_accepts_exact_raw_binding_through_a_named_aggregate_input(
    catalog_inputs, tmp_path,
):
    registry, metadata, tracker, processed, _, _ = catalog_inputs
    source = json.loads((processed / "manifest.json").read_bytes())
    source["inputs"]["projection_manifest"] = source["inputs"].pop("raw_manifest")
    write_json(processed / "manifest.json", source)
    config = yaml.safe_load(registry.read_text())
    config["packets"][0]["manifest_sha256"] = hashlib.sha256(
        (processed / "manifest.json").read_bytes()
    ).hexdigest()
    registry.write_text(yaml.safe_dump(config))
    result = build_catalog(registry, metadata, tracker, tmp_path / "aggregate")
    assert result["effective_native_identity_observations"] == 1

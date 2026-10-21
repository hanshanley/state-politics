"""Accepted input indexes are reusable evidence, not reader-duplicated bill counts."""

import json

import pandas as pd
import pytest
import yaml

from state_politics.bills.study_native_overlap import (
    build_overlap,
    join_contexts,
    normalize_packet,
)
from state_politics.bills.study_window import _STATES
from state_politics.provenance import sha256_file


def inputs(profile="single"):
    spec = {
        "state": "CA",
        "root": "packet",
        "profile": profile,
        "context_id": "record_id",
        "identifier": "identifier",
        "bill_id": "bill_id",
        "canonical_session": "20232024",
    }
    raw = pd.DataFrame(
        {
            "record_id": ["one", "old", "native-only"],
            "identifier": ["HB 1", "HB 2", "HB 3"],
            "bill_id": ["b1", "b2", None],
            "input_sha256": ["a" * 64, "b" * 64, "c" * 64],
            "n_input_characters": [11, 22, 33],
        }
    )
    views = None
    if profile == "views":
        views = pd.DataFrame(
            {
                "view_id": ["one:pypdf", "one:pymupdf"],
                "context_id": ["one", "one"],
                "reader": ["pypdf", "pymupdf"],
                "input_sha256": ["a" * 64, "b" * 64],
                "n_input_characters": [11, 12],
            }
        )
    elif profile == "reader_rows":
        spec.pop("bill_id")
        spec["context_id"] = "native_id"
        raw = pd.concat([raw.iloc[:1], raw.iloc[:1]], ignore_index=True)
        raw["native_id"] = ["native-one", "native-one"]
        raw["record_id"] = ["native-one:pypdf", "native-one:pymupdf"]
        raw["reader"] = ["pypdf", "pymupdf"]
    return spec, raw, views


def ledger():
    return pd.DataFrame(
        {
            "state": ["CA"] * 3,
            "bill_id": ["b1", "b2", "b3"],
            "identifier": ["HB 1", "HB 2", "HB 3"],
            "session_identifier": ["20232024"] * 3,
            "window_disposition": [
                "source_introduction_in_window",
                "source_introduction_before_window",
                "no_source_introduction_action",
            ],
        }
    )


@pytest.mark.parametrize("profile", ["single", "reader_rows", "views"])
def test_alternative_views_never_become_extra_bills(profile):
    spec, raw, source_views = inputs(profile)
    contexts, views = normalize_packet(spec, raw, source_views)
    result = join_contexts(contexts, ledger())
    assert contexts["n_retained_views"].sum() == len(views)
    assert result["source_in_window"].sum() == 1
    assert not result["analytical_admission"].any()
    assert not result["native_identity_certified"].any()
    if profile == "reader_rows":
        assert len(contexts) == 1 and len(views) == 2
        assert result["canonical_join_basis"].iloc[0] == "unique_declared_session_typed_identity"
    else:
        source_only = result.loc[result["context_id"].eq("native-only")].iloc[0]
        assert pd.isna(source_only["bill_id"])
        assert source_only["canonical_join_basis"] == "source_only_no_declared_bill_id"
        assert not source_only["source_in_window"]


@pytest.mark.parametrize("defect", ["session", "identifier", "duplicate-canonical"])
def test_identity_or_cross_session_conflicts_fail(defect):
    spec, raw, views = inputs()
    contexts, _ = normalize_packet(spec, raw, views)
    canonical = ledger()
    if defect == "session":
        canonical.loc[0, "session_identifier"] = "20192020"
    elif defect == "identifier":
        canonical.loc[0, "identifier"] = "HB 999"
    else:
        canonical = pd.concat([canonical, canonical.iloc[:1]])
    with pytest.raises(ValueError):
        join_contexts(contexts, canonical)


@pytest.mark.parametrize("defect", ["orphan", "duplicate-reader", "empty", "bad-hash"])
def test_invalid_view_indexes_fail(defect):
    spec, raw, views = inputs("views")
    if defect == "orphan":
        views.loc[0, "context_id"] = "foreign"
    elif defect == "duplicate-reader":
        views.loc[0, "reader"] = "pymupdf"
    elif defect == "empty":
        views.loc[0, "n_input_characters"] = 0
    else:
        views.loc[0, "input_sha256"] = "missing"
    with pytest.raises(ValueError, match="invalid or orphaned"):
        normalize_packet(spec, raw, views)


def test_reader_context_disagreement_is_not_silently_deduplicated():
    spec, raw, views = inputs("reader_rows")
    raw.loc[1, "identifier"] = "HB 2"
    with pytest.raises(ValueError, match="reader variants disagree"):
        normalize_packet(spec, raw, views)


def test_null_id_packet_never_falls_back_to_guessing_aliases():
    spec, raw, views = inputs()
    raw["bill_id"] = None
    contexts, _ = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, ledger())
    assert result["bill_id"].isna().all()
    assert not result["source_in_window"].any()


def test_explicit_native_special_session_crosswalk_links_only_mapped_contexts():
    spec, raw, views = inputs()
    spec.update(
        source_only_session_fields=["native_session_num"],
        source_only_session_map={"1": "20232024 Special Session 1"},
    )
    raw["native_session_num"] = ["0", "0", "1"]
    contexts, _ = normalize_packet(spec, raw, views)
    canonical = ledger()
    canonical.loc[canonical.bill_id.eq("b3"), "session_identifier"] = "20232024 Special Session 1"
    result = join_contexts(contexts, canonical).set_index("context_id")
    assert result.loc["native-only", "bill_id"] == "b3"
    assert result.loc["native-only", "session_binding"] == "explicit_native_session_code_crosswalk"
    assert not result.loc["native-only", "source_in_window"]
    raw.loc[2, "native_session_num"] = "99"
    contexts, _ = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, canonical).set_index("context_id")
    assert pd.isna(result.loc["native-only", "bill_id"])


def test_colorado_hyphenated_identifier_is_preserved_not_rewritten():
    spec, raw, views = inputs()
    spec.update(state="CO", canonical_session="2023A")
    raw = raw.iloc[:1].copy()
    raw["identifier"] = "HB 23-1001"
    canonical = ledger().iloc[:1].copy()
    canonical["state"] = "CO"
    canonical["identifier"] = "HB 23-1001"
    canonical["session_identifier"] = "2023A"
    contexts, _ = normalize_packet(spec, raw, views)
    result = join_contexts(contexts, canonical)
    assert result["bill_id"].tolist() == ["b1"]
    assert result["native_identifier"].tolist() == ["HB 23-1001"]


def test_unselected_sessions_do_not_expand_adapter_scope():
    spec, raw, views = inputs()
    contexts, _ = normalize_packet(spec, raw, views)
    canonical = ledger()
    canonical.loc[len(canonical)] = [
        "CA",
        "unselected",
        "UNREVIEWED-SPECIAL-FORMAT",
        "other-special-session",
        "source_introduction_in_window",
    ]
    result = join_contexts(contexts, canonical)
    assert result["bill_id"].dropna().tolist() == ["b1", "b2"]


def packet(tmp_path):
    spec, raw, _ = inputs()
    root = tmp_path / "native"
    root.mkdir()
    raw.to_parquet(root / "candidate_inputs.parquet", index=False)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    "candidate_inputs.parquet": sha256_file(root / "candidate_inputs.parquet")
                },
            }
        )
    )
    spec.update(
        {
            "root": str(root),
            "contexts": "candidate_inputs.parquet",
            "manifest_sha256": sha256_file(root / "manifest.json"),
            "expected_contexts": 3,
            "expected_views": 3,
        }
    )
    registry = tmp_path / "registry.yml"
    registry.write_text(yaml.safe_dump({"schema_version": 1, "packets": [spec]}))
    matrix_dir = tmp_path / "matrix"
    matrix_dir.mkdir()
    ledger_path = tmp_path / "ledger.csv"
    original = ledger()
    original.loc[len(original)] = [
        "CA",
        "b4",
        "HB 4",
        "20232024",
        "source_introduction_in_window",
    ]
    original.to_csv(ledger_path, index=False)
    pd.DataFrame(
        {
            "state": sorted(_STATES),
            "native_cycle_denominator": None,
            "recovered_cycle_text_count": None,
            "n_source_in_window": [2 if state == "CA" else 0 for state in sorted(_STATES)],
        }
    ).to_csv(matrix_dir / "state_matrix.csv", index=False)
    (matrix_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete_all_state_triage_not_native_coverage_or_analytical_admission",
                "inputs": {
                    "ledger": {
                        "path": str(ledger_path),
                        "sha256": sha256_file(ledger_path),
                    }
                },
                "artifacts": {
                    "state_matrix.csv": {
                        "sha256": sha256_file(matrix_dir / "state_matrix.csv"),
                    }
                },
            }
        )
    )
    return matrix_dir, registry, root


def test_persistent_overlap_keeps_unregistered_unknown_and_exports_exact_missing_ids(tmp_path):
    matrix, registry, _ = packet(tmp_path)
    out = tmp_path / "out"
    report = build_overlap(matrix, registry, out)
    assert report["n_native_contexts"] == 3
    assert report["n_reader_or_source_views_not_bills"] == 3
    assert report["n_source_only_contexts"] == 1
    assert report["n_source_in_window_without_supplied_native_text"] == 1
    missing = pd.read_parquet(out / "missing_supplied_native_text.parquet")
    assert missing["bill_id"].tolist() == ["b4"]
    result = pd.read_csv(out / "state_matrix.csv").set_index("state")
    assert result.loc["CA", "n_source_in_window_with_supplied_native_text"] == 1
    assert pd.isna(result.loc["AL", "n_source_in_window_with_supplied_native_text"])
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["inputs_unchanged"]
    for name, binding in manifest["artifacts"].items():
        assert sha256_file(out / name) == binding["sha256"]
    with pytest.raises(FileExistsError):
        build_overlap(matrix, registry, out)


def test_modified_native_packet_is_not_accepted_by_stale_manifest(tmp_path):
    matrix, registry, root = packet(tmp_path)
    raw = pd.read_parquet(root / "candidate_inputs.parquet")
    raw.loc[0, "input_sha256"] = "d" * 64
    raw.to_parquet(root / "candidate_inputs.parquet", index=False)
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="checksum mismatch"):
        build_overlap(matrix, registry, out)
    assert not out.exists()


def test_second_accepted_packet_fills_a_gap_without_recollecting_or_session_year_filter(tmp_path):
    matrix, registry, _ = packet(tmp_path)
    original = yaml.safe_load(registry.read_text())
    second = dict(original["packets"][0])
    second.update(
        packet_id="CA_second",
        root=str(tmp_path / "second"),
        expected_contexts=1,
        expected_views=1,
        canonical_session="20252026",
    )
    root = tmp_path / "second"
    root.mkdir()
    _, raw, _ = inputs()
    raw = raw.iloc[:1].copy()
    raw["record_id"] = "prefiled"
    raw["bill_id"] = "b4"
    raw["identifier"] = "HB 4"
    raw.to_parquet(root / "candidate_inputs.parquet", index=False)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    "candidate_inputs.parquet": sha256_file(root / "candidate_inputs.parquet")
                },
            }
        )
    )
    second["manifest_sha256"] = sha256_file(root / "manifest.json")
    original["packets"].append(second)
    registry.write_text(yaml.safe_dump(original))
    source = json.loads((matrix / "manifest.json").read_text())
    ledger_path = tmp_path / "ledger.csv"
    source_ledger = pd.read_csv(ledger_path, dtype=str, keep_default_na=False)
    source_ledger.loc[source_ledger.bill_id.eq("b4"), "session_identifier"] = "20252026"
    source_ledger.to_csv(ledger_path, index=False)
    source["inputs"]["ledger"]["sha256"] = sha256_file(ledger_path)
    (matrix / "manifest.json").write_text(json.dumps(source))
    out = tmp_path / "out"
    report = build_overlap(matrix, registry, out)
    assert report["registered_states"] == ["CA"]
    assert report["n_native_contexts"] == 4
    assert report["n_source_in_window_without_supplied_native_text"] == 0
    saved = pd.read_parquet(out / "native_context_overlap.parquet").set_index("context_id")
    assert saved.loc["prefiled", "source_in_window"]
    assert saved.loc["prefiled", "session_identifier"] == "20252026"

"""Retained historical text cannot silently become current-cycle source coverage."""

import json

import pandas as pd
import pytest

from state_politics.bills.study_sources import build_inventory, reconcile_sources
from state_politics.provenance import sha256_file


def frames():
    ledger = pd.DataFrame(
        [
            {
                "bill_id": bill_id,
                "state": "FL",
                "identifier": "HB 1",
                "session_identifier": session,
                "session_name": session,
                "legislative_session_id": f"session-{session}",
                "originating_chamber": "lower",
                "classification": "bill",
                "source_introduction_date": date,
                "window_disposition": disposition,
            }
            for bill_id, session, date, disposition in [
                ("old", "2019", "2019-03-05", "source_introduction_before_window"),
                ("current", "2023", "2023-03-07", "source_introduction_in_window"),
                ("unknown", "2024", "", "no_source_introduction_action"),
            ]
        ]
    )
    identity = ledger[["bill_id", "state", "identifier", "session_identifier"]]
    coverage = identity.assign(
        n_version_links=[1, 2, 0],
        n_original_note_links=[1, 1, 0],
        filing_time_text_certified=False,
        analytical_admission=False,
    )
    references = pd.concat([identity.iloc[[0]], identity.iloc[[1]], identity.iloc[[1]]])
    references = references.assign(
        link_id=["old-link", "filed-link", "later-link"],
        source_url=["https://example.com/2023", "https://example.com/filed", "https://example.com/filed"],
        version_note_hint=["original_note", "original_note", "later_note"],
        collection_eligible=True,
        analytical_admission=False,
    )
    retained = identity.iloc[[0, 2]].assign(
        link_id=["old-link", None],
        text=["Complete old source.\u2028Keep it all.", "Complete undated source."],
        input_sha256=["old-text-hash", "unknown-text-hash"],
        analytical_admission=False,
    )
    return ledger, coverage, references, retained


def test_exact_context_join_preserves_unknown_dates_full_inputs_and_later_links():
    ledger, coverage, references, retained = frames()
    contexts, links, overlap, groups = reconcile_sources(ledger, coverage, references, retained)
    assert len(contexts) == 3
    assert contexts.loc[contexts["source_in_window"], "bill_id"].tolist() == ["current"]
    assert not contexts.loc[contexts["source_in_window"], "input_present_in_supplied_packet"].any()
    assert overlap["text"].tolist() == retained["text"].tolist()
    assert pd.isna(overlap.loc[overlap["bill_id"].eq("unknown"), "link_id"].iloc[0])
    unknown = overlap.loc[overlap["bill_id"].eq("unknown")].iloc[0]
    assert unknown["source_introduction_date"] == ""
    assert not unknown["source_in_window"]
    assert links["link_id"].tolist() == references["link_id"].tolist()
    pd.testing.assert_frame_equal(contexts[coverage.columns], coverage)
    assert groups["n_contexts"].sum() == 3
    assert not any(frame["analytical_admission"].any() for frame in (contexts, links, overlap))
    pd.testing.assert_frame_equal(retained, frames()[3])


@pytest.mark.parametrize(
    "defect", ["identifier", "session", "foreign", "duplicate", "link", "missing-link"]
)
def test_conflicting_or_unaccounted_source_identities_fail(defect):
    ledger, coverage, references, retained = frames()
    if defect == "identifier":
        retained.loc[retained["bill_id"].eq("old"), "identifier"] = "HB 2"
    elif defect == "session":
        retained.loc[retained["bill_id"].eq("old"), "session_identifier"] = "2023"
    elif defect == "foreign":
        retained.loc[retained["bill_id"].eq("old"), "bill_id"] = "not-in-ledger"
    elif defect == "duplicate":
        retained = pd.concat([retained, retained.iloc[[0]]])
    elif defect == "link":
        retained.loc[retained["bill_id"].eq("old"), "link_id"] = "filed-link"
    else:
        references = references.loc[references["link_id"].ne("later-link")]
    with pytest.raises(ValueError):
        reconcile_sources(ledger, coverage, references, retained)


@pytest.mark.parametrize("frame_index", [1, 2, 3])
def test_nullable_missing_context_identity_is_rejected(frame_index):
    sources = frames()
    source = sources[frame_index]
    source["identifier"] = source["identifier"].astype("string")
    source.loc[source["bill_id"].eq("old"), "identifier"] = pd.NA
    with pytest.raises(ValueError, match="identity mismatch"):
        reconcile_sources(*sources)


def packet(tmp_path):
    window, reference, inputs = [tmp_path / name for name in ("window", "reference", "inputs")]
    for directory in (window, reference, inputs):
        directory.mkdir()
    ledger, coverage, references, retained = frames()
    ledger.to_csv(window / "bill_window_ledger.csv", index=False)
    (window / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete_source_window_inventory_not_analytical_admission",
                "window_start": "2023-01-01",
                "window_end": "2024-12-31",
                "artifacts": {
                    "bill_window_ledger.csv": {
                        "sha256": sha256_file(window / "bill_window_ledger.csv")
                    }
                },
                "inputs": {"bill_extraction_manifest.json": {"sha256": "same-extraction"}},
            }
        )
    )
    coverage.to_parquet(reference / "bill_document_coverage.parquet", index=False)
    references.to_parquet(reference / "document_candidates.parquet", index=False)
    retained.to_parquet(inputs / "candidate_inputs.parquet", index=False)
    (reference / "report.json").write_text(
        json.dumps(
            {
                "status": "reference_inventory_not_text_certification",
                "extraction_manifest_sha256": "same-extraction",
            }
        )
    )
    (inputs / "report.json").write_text(
        json.dumps(
            {
                "status": "unlabelled_complete_input_inventory_not_inference_or_certification",
                "n_bill_inputs": 2,
            }
        )
    )
    for directory in (reference, inputs):
        (directory / "manifest.json").write_text(
            json.dumps({"files": {p.name: sha256_file(p) for p in directory.iterdir()}})
        )
    return window, reference, inputs


def test_persistent_inventory_binds_full_outputs_and_refuses_overwrite(tmp_path):
    window, reference, inputs = packet(tmp_path)
    out = tmp_path / "out"
    report = build_inventory(window, reference, inputs, out, state="FL")
    assert report["n_source_in_window"] == 1
    assert report["n_source_in_window_with_supplied_input"] == 0
    assert report["n_source_in_window_reference_links"] == 2
    assert report["n_source_in_window_usable_original_note_links"] == 1
    assert report["supplied_input_session_counts"] == {"2019": 1, "2024": 1}
    saved = pd.read_parquet(out / "supplied_input_overlap.parquet")
    assert saved["text"].tolist() == frames()[3]["text"].tolist()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["inputs_unchanged"] is True
    assert manifest["requests_authorized"] is False
    for name, binding in manifest["artifacts"].items():
        assert sha256_file(out / name) == binding["sha256"]
    before = (out / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        build_inventory(window, reference, inputs, out, state="FL")
    assert (out / "manifest.json").read_bytes() == before


def test_changed_bound_packet_fails_before_output_creation(tmp_path):
    window, reference, inputs = packet(tmp_path)
    (inputs / "report.json").write_text("{}")
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="packet checksum mismatch"):
        build_inventory(window, reference, inputs, out, state="FL")
    assert not out.exists()


def test_validly_bound_but_different_extraction_lineage_is_rejected(tmp_path):
    window, reference, inputs = packet(tmp_path)
    report_path = reference / "report.json"
    report = json.loads(report_path.read_text())
    report["extraction_manifest_sha256"] = "different-extraction"
    report_path.write_text(json.dumps(report))
    manifest_path = reference / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["report.json"] = sha256_file(report_path)
    manifest_path.write_text(json.dumps(manifest))
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="same extraction"):
        build_inventory(window, reference, inputs, out, state="FL")
    assert not out.exists()


def test_reconciliation_failure_preserves_explicitly_incomplete_output(tmp_path):
    window, reference, inputs = packet(tmp_path)
    input_path = inputs / "candidate_inputs.parquet"
    retained = pd.read_parquet(input_path)
    retained.loc[retained["bill_id"].eq("old"), "identifier"] = "HB 2"
    retained.to_parquet(input_path, index=False)
    manifest_path = inputs / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][input_path.name] = sha256_file(input_path)
    manifest_path.write_text(json.dumps(manifest))
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="identity mismatch"):
        build_inventory(window, reference, inputs, out, state="FL")
    assert json.loads((out / "manifest.json").read_text())["status"] == "incomplete"
    assert not (out / "report.json").exists()

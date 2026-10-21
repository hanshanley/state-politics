"""Full abstract alternatives must not become silently selected or filing-aligned inputs."""

import json

import pandas as pd
import pytest

from state_politics.bills.study_abstracts import build_inventory, reconcile_evidence
from state_politics.bills.study_window import _STATES
from state_politics.provenance import sha256_file


def frames():
    bills = pd.DataFrame(
        {
            "bill_id": ["one", "test", "draft", "old"],
            "state": ["CA", "WA", "MT", "NJ"],
            "identifier": ["HB 1", "HB 4", "LC 1", "HB 2"],
            "session_identifier": ["2023"] * 4,
            "title": ["A full title.", "bill 4 for system testing", "Draft request", "Older title"],
        }
    )
    ledger = bills.drop(columns="title").assign(
        classification="bill",
        source_introduction_date=["2023-01-01", "2023-01-01", "", "2022-01-01"],
        source_filing_date=["", "", "2023-01-01", ""],
        window_disposition=[
            "source_introduction_in_window",
            "source_introduction_in_window",
            "no_source_introduction_action",
            "source_introduction_before_window",
        ],
        filing_window_disposition=[
            "no_source_filing_action",
            "no_source_filing_action",
            "source_filing_in_window",
            "no_source_filing_action",
        ],
    )
    abstracts = pd.DataFrame(
        {
            "id": ["a", "b", "empty", "older"],
            "bill_id": ["one", "one", "test", "old"],
            "abstract": [
                "Complete first.\u2028Still complete.",
                "Different later summary.",
                " \n ",
                "Old.",
            ],
            "note": ["Introduced", "Engrossed", None, "Older"],
        }
    )
    native = bills.loc[bills.bill_id.eq("one"), bills.columns != "title"].assign(
        n_retained_views=2,
        native_in_window=False,
        native_introduction_date=None,
        native_introduction_raw=None,
        date_evidence_status="not_supplied_by_registered_packet",
    )
    return bills, abstracts, ledger, native


def test_all_abstract_texts_notes_alternatives_and_unknown_native_presence_survive():
    bills, abstracts, ledger, native = frames()
    cohort, kept, views = reconcile_evidence(bills, abstracts, ledger, native, ["CA"])
    assert set(cohort.bill_id) == {"one", "test", "draft"}
    pd.testing.assert_frame_equal(
        kept[abstracts.columns],
        abstracts.loc[abstracts.bill_id.ne("old")].reset_index(drop=True),
    )
    source = cohort.set_index("bill_id")
    assert source.loc["one", "n_distinct_abstract_texts"] == 2
    assert source.loc["one", "n_indexed_native_views"] == 2
    assert pd.isna(source.loc["test", "n_indexed_native_views"])
    assert len(views) == 4
    texts = views.loc[views.bill_id.eq("one"), "text"].tolist()
    assert texts == [
        "A full title.\n\nComplete first.\u2028Still complete.",
        "A full title.\n\nDifferent later summary.",
    ]
    assert views.loc[views.bill_id.eq("test"), "input_status"].iloc[0] == "excluded_source_test"
    assert (
        views.loc[views.bill_id.eq("draft"), "input_status"].iloc[0]
        == "excluded_source_draft_request"
    )
    assert views.n_input_tokens.isna().all()
    assert not views.model_input_approved.any()
    assert not views.filing_time_text_certified.any()


def test_identical_summary_text_is_not_dropped_or_confused_with_a_variant():
    bills, abstracts, ledger, native = frames()
    abstracts.loc[1, "abstract"] = abstracts.loc[0, "abstract"]
    cohort, kept, views = reconcile_evidence(bills, abstracts, ledger, native, ["CA"])
    assert cohort.set_index("bill_id").loc["one", "n_nonempty_abstract_records"] == 2
    assert cohort.set_index("bill_id").loc["one", "n_distinct_abstract_texts"] == 1
    assert views.loc[views.bill_id.eq("one"), "view_id"].tolist() == ["abstract:a", "abstract:b"]
    assert len(kept) == 3


@pytest.mark.parametrize("defect", ["orphan", "duplicate", "identity", "title-type", "native"])
def test_corrupt_record_identity_or_nonstring_text_fails(defect):
    bills, abstracts, ledger, native = frames()
    if defect == "orphan":
        abstracts.loc[0, "bill_id"] = "absent"
    elif defect == "duplicate":
        abstracts.loc[0, "id"] = "b"
    elif defect == "identity":
        ledger.loc[0, "session_identifier"] = "2019"
    elif defect == "native":
        native.loc[0, "identifier"] = "HB 999"
    else:
        bills["title"] = bills["title"].astype(object)
        bills.loc[0, "title"] = True
    with pytest.raises(ValueError):
        reconcile_evidence(bills, abstracts, ledger, native, ["CA"])


def test_empty_source_event_cohort_retains_readable_schemas():
    bills, abstracts, ledger, native = frames()
    ledger["window_disposition"] = "no_source_introduction_action"
    ledger["filing_window_disposition"] = "no_source_filing_action"
    cohort, kept, views = reconcile_evidence(bills, abstracts, ledger, native, ["CA"])
    assert cohort.empty and kept.empty and views.empty
    assert {"view_id", "text", "input_status"}.issubset(views.columns)


def test_native_only_candidates_preserve_source_dates_and_do_not_gain_admission():
    bills, abstracts, ledger, native = frames()
    extra = bills.loc[bills.bill_id.eq("old"), bills.columns != "title"].assign(
        n_retained_views=1,
        native_in_window=True,
        native_introduction_date="2023-04-05",
        native_introduction_raw="2023-04-05",
        date_evidence_status="native_source_dates_differ",
    )
    native = pd.concat([native, extra], ignore_index=True)
    cohort, _, views = reconcile_evidence(bills, abstracts, ledger, native, ["CA", "NJ"])
    row = cohort.set_index("bill_id").loc["old"]
    assert row.cohort_scope == "native_reported_date_candidate"
    assert row.source_introduction_date == "2022-01-01"
    assert row.native_introduction_date == "2023-04-05"
    assert row.date_evidence_status == "native_source_dates_differ"
    assert not views.loc[views.bill_id.eq("old"), "model_input_approved"].any()


def test_uncoded_description_candidates_remain_a_distinct_evidence_channel():
    bills, abstracts, ledger, native = frames()
    extra = pd.DataFrame(
        {
            "bill_id": ["ma"],
            "state": ["MA"],
            "identifier": ["S 1"],
            "session_identifier": ["193"],
            "title": ["Petition for a policy"],
        }
    )
    bills = pd.concat([bills, extra], ignore_index=True)
    extra_ledger = extra.drop(columns="title").assign(
        classification="bill",
        source_introduction_date="",
        source_filing_date="",
        window_disposition="no_source_introduction_action",
        filing_window_disposition="no_source_filing_action",
    )
    ledger = pd.concat([ledger, extra_ledger], ignore_index=True)
    descriptions = extra.drop(columns="title").assign(
        description_introduction_disposition="no_reviewed_literal_action",
        description_introduction_candidate_date="",
        description_petition_filing_disposition="in_window",
        description_petition_filing_candidate_date="2023-01-20",
    )
    cohort, _, views = reconcile_evidence(bills, abstracts, ledger, native, ["CA"], descriptions)
    row = cohort.set_index("bill_id").loc["ma"]
    assert row.cohort_scope == "description_stated_event_candidate"
    assert not row.source_event_in_window
    assert row.source_filing_date == ""
    assert pd.isna(row.native_introduction_in_window)
    assert views.loc[views.bill_id.eq("ma"), "metadata_tier"].tolist() == ["title_only"]
    descriptions.loc[0, "description_petition_filing_candidate_date"] = "2023-01-20garbage"
    with pytest.raises(ValueError):
        reconcile_evidence(bills, abstracts, ledger, native, ["CA"], descriptions)


def packet(tmp_path):
    data, filing, native_dir, window = [
        tmp_path / p for p in ("data", "filing", "native", "window")
    ]
    for directory in (data, filing, native_dir, window):
        directory.mkdir()
    bills, abstracts, ledger, native = frames()
    bills.to_parquet(data / "bills.parquet", index=False)
    abstracts.to_parquet(data / "bill_abstracts.parquet", index=False)
    (data / "bill_extraction_manifest.json").write_text(
        json.dumps(
            {
                "status": "complete_extraction_not_source_certification",
                "artifacts": {
                    name: {"sha256": sha256_file(data / name), "rows": len(frame)}
                    for name, frame in (
                        ("bills.parquet", bills),
                        ("bill_abstracts.parquet", abstracts),
                    )
                },
            }
        )
    )
    (window / "manifest.json").write_text(
        json.dumps(
            {
                "inputs": {
                    "bill_extraction_manifest.json": {
                        "sha256": sha256_file(data / "bill_extraction_manifest.json"),
                    }
                },
            }
        )
    )
    native.to_parquet(native_dir / "native_context_overlap.parquet", index=False)
    (native_dir / "report.json").write_text(json.dumps({"registered_states": ["CA"]}))
    (native_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": (
                    "complete_supplied_native_overlap_not_native_census_or_analytical_admission"
                ),
                "artifacts": {
                    name: {"sha256": sha256_file(native_dir / name)}
                    for name in ("native_context_overlap.parquet", "report.json")
                },
            }
        )
    )
    ledger.to_csv(filing / "bill_filing_evidence.csv", index=False)
    pd.DataFrame(
        {
            "state": sorted(_STATES),
            "n_filing_or_introduction_in_window": [
                1 if state in {"CA", "MT", "WA"} else 0 for state in sorted(_STATES)
            ],
        }
    ).to_csv(filing / "state_matrix.csv", index=False)
    (filing / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete_source_filing_inventory_not_native_or_analytical_certification",
                "inputs": {
                    "window_manifest": {
                        "path": str(window / "manifest.json"),
                        "sha256": sha256_file(window / "manifest.json"),
                    },
                    "matrix_manifest": {"sha256": sha256_file(native_dir / "manifest.json")},
                },
                "artifacts": {
                    name: {"sha256": sha256_file(filing / name)}
                    for name in ("bill_filing_evidence.csv", "state_matrix.csv")
                },
            }
        )
    )
    return data, filing, native_dir


def test_full_evidence_exports_and_enriched_matrix_are_hash_bound(tmp_path):
    data, filing, native = packet(tmp_path)
    out = tmp_path / "out"
    report = build_inventory(data, filing, native, out)
    assert report["n_cycle_contexts"] == 3
    assert report["n_cycle_abstract_records"] == 3
    assert report["n_cycle_contexts_with_nonempty_abstract"] == 1
    assert report["n_metadata_candidate_views_not_bills"] == 4
    saved = pd.read_parquet(out / "candidate_metadata_views.parquet")
    assert "\u2028" in saved.loc[saved.view_id.eq("abstract:a"), "text"].iloc[0]
    matrix = pd.read_csv(out / "state_matrix.csv").set_index("state")
    assert matrix.loc["CA", "n_cycle_contexts_with_multiple_abstract_variants"] == 1
    assert pd.isna(matrix.loc["WA", "n_cycle_contexts_with_indexed_native_text"])
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["inputs_unchanged"]
    for name, binding in manifest["artifacts"].items():
        assert sha256_file(out / name) == binding["sha256"]
    with pytest.raises(FileExistsError):
        build_inventory(data, filing, native, out)


def test_changed_source_text_fails_before_output_creation(tmp_path):
    data, filing, native = packet(tmp_path)
    source = data / "bill_abstracts.parquet"
    abstracts = pd.read_parquet(source)
    abstracts.loc[0, "abstract"] = "Changed source text."
    abstracts.to_parquet(source, index=False)
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="extraction checksum"):
        build_inventory(data, filing, native, out)
    assert not out.exists()


@pytest.mark.parametrize("corrupt_bill_binding", [False, True])
def test_declared_canonical_bill_index_prevents_reference_context_double_counting(
    tmp_path, corrupt_bill_binding,
):
    data, filing, native = packet(tmp_path)
    raw_path = native / "native_context_overlap.parquet"
    bills = pd.read_parquet(raw_path)
    bills.loc[0, "n_retained_views"] = 5
    bill_path = native / "native_bill_overlap.parquet"
    bills.to_parquet(bill_path, index=False)
    pd.concat([bills, bills.iloc[:1]], ignore_index=True).to_parquet(raw_path, index=False)
    manifest_path = native / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"]["native_context_overlap.parquet"]["sha256"] = sha256_file(raw_path)
    manifest["artifacts"][bill_path.name] = {
        "sha256": "bad" if corrupt_bill_binding else sha256_file(bill_path),
    }
    manifest_path.write_text(json.dumps(manifest))
    filing_path = filing / "manifest.json"
    filing_manifest = json.loads(filing_path.read_text())
    filing_manifest["inputs"]["matrix_manifest"]["sha256"] = sha256_file(manifest_path)
    filing_path.write_text(json.dumps(filing_manifest))
    out = tmp_path / "out"
    if corrupt_bill_binding:
        with pytest.raises(ValueError, match="native_contexts: packet checksum"):
            build_inventory(data, filing, native, out)
        assert not out.exists()
    else:
        build_inventory(data, filing, native, out)
        result = pd.read_parquet(out / "bill_evidence.parquet")
        observed = result.loc[
            result.bill_id.eq(bills.bill_id.iloc[0]), "n_indexed_native_views",
        ].item()
        assert observed == 5
        binding = json.loads((out / "manifest.json").read_text())["inputs"]["native_contexts"]
        assert binding["path"] == str(bill_path.resolve())


@pytest.mark.parametrize("changed_ledger", [False, True])
def test_description_reuse_binds_relevant_event_bytes_not_unrelated_native_matrix(
    tmp_path,
    changed_ledger,
):
    data, filing, native = packet(tmp_path)
    description = tmp_path / "description"
    description.mkdir()
    _, _, ledger, _ = frames()
    fields = ["bill_id", "state", "identifier", "session_identifier"]
    ledger[fields].assign(
        description_introduction_disposition="no_reviewed_literal_action",
        description_introduction_candidate_date="",
        description_petition_filing_disposition="no_reviewed_literal_action",
        description_petition_filing_candidate_date="",
    ).to_csv(description / "candidate_bill_ledger.csv", index=False)
    filing_manifest = json.loads((filing / "manifest.json").read_text())
    (description / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete_literal_description_inventory_not_analytical_admission",
                "inputs": {
                    "filing_manifest": {"sha256": "older-manifest-with-a-different-native-matrix"},
                    "filing_ledger": {
                        "sha256": "bad"
                        if changed_ledger
                        else sha256_file(filing / "bill_filing_evidence.csv")
                    },
                    "window_manifest": filing_manifest["inputs"]["window_manifest"],
                    "extraction_manifest": {
                        "sha256": sha256_file(data / "bill_extraction_manifest.json"),
                    },
                },
                "artifacts": {
                    "candidate_bill_ledger.csv": {
                        "sha256": sha256_file(description / "candidate_bill_ledger.csv"),
                    }
                },
            }
        )
    )
    out = tmp_path / "out"
    if changed_ledger:
        with pytest.raises(ValueError, match="identical filing/window/extraction"):
            build_inventory(data, filing, native, out, description_dir=description)
    else:
        result = build_inventory(data, filing, native, out, description_dir=description)
        assert result["n_cycle_contexts"] == 3

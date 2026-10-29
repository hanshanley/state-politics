"""Printed introduction fields retain exact sources and never become a date fallback."""

import json

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pymupdf
import pytest

from state_politics.bills import pa_printed_dates as dates
from state_politics.bills.study_native_overlap import join_contexts, normalize_packet

HEADER = (
    "PRINTER'S NO. 3\nTHE GENERAL ASSEMBLY OF PENNSYLVANIA\n"
    "SENATE RESOLUTION\nNo.\n3\nSession of\n2023\n"
    "INTRODUCED BY PITTMAN AND COSTA, JANUARY 3,\n2023\n"
)
BODY = "A RESOLUTION\nAdopting the Rules of the Senate.\n"


@pytest.mark.parametrize("confirmation", [
    "", "INTRODUCED, JANUARY 3, 2023\n", "INTRODUCED AND ADOPTED, JANUARY 3, 2023\n",
])
def test_labelled_confirmations_preserve_every_raw_span(confirmation):
    text = HEADER + confirmation + BODY
    result = dates.observe_header(text, "SR 3")
    assert result["date"] == "2023-01-03"
    assert len(result["labelled_date_witnesses"]) == (2 if confirmation else 1)
    for witness in result["labelled_date_witnesses"]:
        for key in ("event_label", "date_literal"):
            start, end = witness[key]["span"]
            assert text[start:end] == witness[key]["text"]
    assert all(result[flag] is False for flag in dates.FLAGS)


@pytest.mark.parametrize("text,identifier,reason", [
    (HEADER + "INTRODUCED, JANUARY 4, 2023\n" + BODY, "SR 3", "conflicting"),
    (HEADER.replace("JANUARY 3,\n2023", "") + "REFERRED TO RULES, JANUARY 3, 2023\n"
     + BODY, "SR 3", "explicit date"),
    (HEADER.replace("JANUARY 3,\n2023", "") + "INTRODUCED, JANUARY 3, 2023\n"
     + BODY, "SR 3", "explicit date"),
    (HEADER.replace("INTRODUCED BY", "ADOPTED BY") + BODY, "SR 3", "introduced-by"),
    (HEADER + BODY, "SR 6", "identity"),
    (HEADER.replace("PENNSYLVANIA", "VIRGINIA") + BODY, "SR 3", "own printed"),
    (HEADER.replace("Session of\n2023", "Session of\n2025") + BODY, "SR 3", "session"),
    (HEADER.replace("JANUARY 3,\n2023", "FEBRUARY 29, 2023") + BODY, "SR 3", "invalid"),
    (HEADER + HEADER + BODY, "SR 3", "unique own"),
    (HEADER.replace("JANUARY 3,\n2023", "") + BODY + "JANUARY 3, 2023", "SR 3", "explicit"),
])
def test_unknown_conflicting_foreign_and_body_dates_never_supply_an_introduction(text, identifier,
                                                                               reason):
    with pytest.raises(ValueError, match=reason):
        dates.observe_header(text, identifier)


def test_referral_and_amendment_dates_remain_separate_from_introduction():
    result = dates.observe_header(
        HEADER + "REFERRED TO RULES, FEBRUARY 2, 2023\n"
        "AS AMENDED, MARCH 5, 2023\n" + BODY, "SR 3",
    )
    assert result["date"] == "2023-01-03"
    assert result["version_notes"]
    assert result["filing_time_text_certified"] is False


def test_concurrent_body_does_not_change_printed_type_or_supply_a_date():
    text = (
        HEADER + "REFERRED TO RULES, FEBRUARY 2, 2023\n"
        "A CONCURRENT RESOLUTION\nRecognizing DECEMBER 14, 2022.\n"
    )
    result = dates.observe_header(text, "SR 3")
    assert result["printed_identifier"] == "SR3"
    assert result["date"] == "2023-01-03"


def test_literal_unicode_line_separators_keep_original_date_coordinates():
    text = HEADER.replace("\n", "\u2028") + BODY
    result = dates.observe_header(text, "SR 3")
    witness = result["labelled_date_witnesses"][0]["date_literal"]
    start, end = witness["span"]
    assert witness["text"] == text[start:end] == "JANUARY 3,\u20282023"
    assert result["date"] == "2023-01-03"


@pytest.fixture
def packet(tmp_path):
    source = tmp_path / "data/source"
    source.mkdir(parents=True)
    pdf = source / "original.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((40, 50), HEADER + "INTRODUCED AND ADOPTED, JANUARY 3, 2023\n" + BODY)
    document.save(pdf)
    document.close()
    views = source / "views.parquet"
    pq.write_table(pa.Table.from_pylist([{
        "view_id": "original-view", "context_id": "source-context", "state": "PA",
        "identifier": "SR 3", "reader": "pdf_stored_reader",
        "input_sha256": "a" * 64, "original_source_path": str(pdf),
        "original_source_sha256": dates.binding(pdf)["sha256"],
        "negative_flags_json": '["original_capture_limitations_remain"]',
    }]), views)
    joined = source / "joined.parquet"
    canonical = {
        "context_id": "source-context", "bill_id": "bill-3", "identifier": "SR 3",
        "session_identifier": "2023-2024", "state": "PA", "state_native": None,
        "source_introduction_date": None,
        "canonical_join_basis": "unique_declared_session_typed_identity",
    }
    pq.write_table(pa.Table.from_pylist([canonical]), joined)
    assessment = tmp_path / "data/assessment"
    assessment.mkdir()
    dates._json(assessment / "probe.json", {
        "source": str(views.relative_to(tmp_path)), "sha256": dates.binding(views)["sha256"],
    })
    dates._json(assessment / "join-incidence-v2.json", {
        "shared_join": str(joined.relative_to(tmp_path)), "binding": dates.binding(joined),
    })
    manifest = {
        "status": "complete_bounded_source_date_assessment_not_qualified_cohort_extension",
        "date_admission": False, "cohort_change": False,
        "model_execution": False, "publication": False,
        "artifacts": {p.name: dates.binding(p) for p in assessment.iterdir()},
    }
    dates._json(assessment / "manifest.json", manifest)
    out = tmp_path / "data/qualified"
    dates.build(assessment / "manifest.json", dates.binding(assessment / "manifest.json")["sha256"],
                out, root=tmp_path)
    return tmp_path, out, pdf, canonical


def test_real_pdf_packet_replays_and_enters_shared_registry_without_source_date_backfill(packet):
    root, out, _, canonical = packet
    pin = dates.binding(out / "manifest.json")["sha256"]
    manifest = dates.verify(out, pin, root=root)
    assert manifest["counts"]["qualified_contexts"] == 1
    spec = dates.registry_entry(out, pin, root=root)
    raw = pd.read_parquet(out / "observations.parquet")
    contexts, views = normalize_packet(spec, raw, None)
    assert views.empty and contexts["n_retained_views"].sum() == 0
    ledger = pd.DataFrame([{
        key: canonical[key] for key in
        ("bill_id", "state", "identifier", "session_identifier", "source_introduction_date")
    }])
    ledger["window_disposition"] = "unresolved_source_date"
    joined = join_contexts(contexts, ledger)
    assert joined["bill_id"].tolist() == ["bill-3"]
    assert joined["native_introduction_date"].tolist() == ["2023-01-03"]
    assert joined["source_introduction_date"].isna().all()
    assert joined["analytical_admission"].eq(False).all()


@pytest.mark.parametrize("name", ["observations.parquet", "observations.csv", "producer.py"])
def test_rebound_packet_payloads_do_not_waive_replay(packet, name):
    root, out, _, _ = packet
    if name.endswith(".parquet"):
        rows = pq.read_table(out / name).to_pylist()
        rows[0]["printed_introduction_date"] = "2023-01-04"
        pq.write_table(pa.Table.from_pylist(rows), out / name)
    else:
        (out / name).write_bytes((out / name).read_bytes() + b"\nforged payload\n")
    manifest = json.loads((out / "manifest.json").read_bytes())
    manifest["files"][name] = dates.binding(out / name)
    (out / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="replay|producer"):
        dates.verify(out, dates.binding(out / "manifest.json")["sha256"], root=root)


def test_source_corruption_and_existing_output_are_rejected(packet):
    root, out, pdf, _ = packet
    manifest = json.loads((out / "manifest.json").read_bytes())
    with pytest.raises(ValueError, match="existing output"):
        dates.build(root / manifest["assessment"]["path"], manifest["assessment"]["sha256"],
                    out, root=root)
    with pytest.raises(ValueError, match="direct child"):
        dates.build(root / manifest["assessment"]["path"], manifest["assessment"]["sha256"],
                    root / "data/source/new-packet", root=root)
    assert not (root / "data/source/new-packet").exists()
    pdf.write_bytes(pdf.read_bytes() + b"\nchanged original\n")
    with pytest.raises(ValueError, match="source hash"):
        dates.verify(out, dates.binding(out / "manifest.json")["sha256"], root=root)


def test_reader_disagreement_remains_unknown_and_retains_both_complete_first_pages(
    packet, monkeypatch,
):
    root, original, _, _ = packet
    manifest = json.loads((original / "manifest.json").read_bytes())
    monkeypatch.setattr(dates, "_pages", lambda _: {
        "pymupdf": {"text": HEADER + BODY},
        "pypdf": {"text": HEADER.replace("JANUARY 3,\n2023", "JANUARY 4, 2023") + BODY},
    })
    out = root / "data/disagreement"
    result = dates.build(root / manifest["assessment"]["path"],
                         manifest["assessment"]["sha256"], out, root=root)
    assert result["counts"]["qualified_contexts"] == 0
    row = pq.read_table(out / "observations.parquet").to_pylist()[0]
    assert row["printed_introduction_date"] is None
    disposition = json.loads((out / "source_dispositions.jsonl").read_text())
    assert {v["date"] for v in disposition["reader_observations"].values()} == {
        "2023-01-03", "2023-01-04",
    }
    assert dates.verify(out, dates.binding(out / "manifest.json")["sha256"], root=root)


@pytest.mark.parametrize(
    "flag", ["date_admission", "independent_human_validation", "model_execution"],
)
def test_rebound_manifest_cannot_promote_observations(packet, flag):
    root, out, _, _ = packet
    manifest = json.loads((out / "manifest.json").read_bytes())
    manifest[flag] = True
    (out / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="approval"):
        dates.verify(out, dates.binding(out / "manifest.json")["sha256"], root=root)

"""Official bill-key joins must not become invented historical affiliations."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pandas as pd
import pytest

from state_politics.bills.washington import (
    BIENNIA,
    NS,
    build_reconciliation,
    parse_records,
    reconcile,
    resolve_native_primary,
)
from state_politics.platforms.recovery import verify_manifest
from state_politics.provenance import sha256_file


def _xml(rows, *, members=False):
    kind = "Member" if members else "Legislation"
    root = ET.Element(f"{{{NS}}}ArrayOf{kind}")
    for row in rows:
        element = ET.SubElement(root, f"{{{NS}}}{kind}")
        for key, value in row.items():
            ET.SubElement(element, f"{{{NS}}}{key}").text = value
    return ET.tostring(root)


def _bill(**updates):
    return {
        "bill_id": "ocd-bill/example", "state": "WA", "session_identifier": "2019-2020",
        "identifier": "HB 1001", "title": "Housing", "originating_chamber": "lower",
        "sponsor_party": "unknown", **updates,
    }


def _legislation(**updates):
    return {
        "Biennium": "2019-20", "BillId": "HB 1001", "BillNumber": "1001",
        "SubstituteVersion": "0", "EngrossedVersion": "0", "OriginalAgency": "House",
        "IntroducedDate": "2019-01-14T00:00:00", "PrimeSponsorID": "101",
        "LegalTitle": "AN ACT Relating to housing;", **updates,
    }


def _members():
    return [
        {"Biennium": "2019-20", **row}
        for row in parse_records(_xml([
            {"Id": "101", "Name": "Example Member", "Agency": "House", "Party": "D"},
            {"Id": "101", "Name": "Example Member", "Agency": "Senate", "Party": "R"},
        ], members=True), members=True)
    ]


def test_exact_bill_and_chamber_join_retains_session_evidence_not_filing_party():
    versions = parse_records(_xml([
        _legislation(), _legislation(BillId="SHB 1001", SubstituteVersion="1"),
        _legislation(Biennium="2021-22", PrimeSponsorID="999"),
    ]))
    row, = reconcile([_bill()], versions, _members())
    assert row["record_link_status"] == "unique_original_record"
    assert row["official_record_rows"] == [0]
    assert row["official_roster_rows"] == [0]
    assert row["session_roster_party"] == "D"
    assert row["official_LegalTitle"] == "AN ACT Relating to housing;"
    assert row["sponsor_party"] == row["filing_time_party"] == "unknown"
    assert row["analytical_admission"] is False


def test_duplicate_originals_are_retained_not_arbitrarily_selected():
    versions = parse_records(_xml([_legislation(), _legislation(PrimeSponsorID="202")]))
    row, = reconcile([_bill()], versions, _members())
    assert row["record_link_status"] == "multiple_original_records"
    assert row["official_record_rows"] == [0, 1]
    assert row["session_roster_party"] == "unknown"


@pytest.mark.parametrize(("members", "reason"), [
    ([], "missing_chamber_scoped_roster_member"),
    (_members()[1:], "missing_chamber_scoped_roster_member"),
    ([{**_members()[0], "Party": "", "Name": ""}], "missing_or_unsupported_roster_party"),
    ([_members()[0], _members()[0]], "multiple_chamber_scoped_roster_members"),
])
def test_roster_gaps_never_borrow_another_chamber_or_choose_duplicate(members, reason):
    row, = reconcile([_bill()], parse_records(_xml([_legislation()])), members)
    assert row["session_roster_party"] == "unknown"
    assert row["session_roster_party_reason"] == reason


def test_missing_original_chamber_conflict_and_repeated_baseline_are_explicit():
    records = parse_records(_xml([_legislation()]))
    missing, = reconcile([_bill(identifier="HB 1002")], records, _members())
    assert missing["record_link_status"] == "missing_original_record"
    conflict, = reconcile([_bill(originating_chamber="upper")], records, _members())
    assert conflict["record_link_status"] == "chamber_or_identifier_conflict"
    assert conflict["session_roster_party"] == "unknown"
    with pytest.raises(ValueError, match="unique Washington"):
        reconcile([_bill(), _bill()], records, _members())


def test_xml_rejects_wrong_schema_and_out_of_scope_or_duplicate_fields():
    with pytest.raises(ValueError, match="unexpected official"):
        parse_records(b"<html>Unavailable</html>")
    with pytest.raises(ValueError, match="out-of-scope"):
        parse_records(_xml([_legislation(Biennium="2027-28")]))
    root = ET.fromstring(_xml([_legislation()]))
    ET.SubElement(root[0], f"{{{NS}}}PrimeSponsorID").text = "202"
    with pytest.raises(ValueError, match="duplicate PrimeSponsorID"):
        parse_records(ET.tostring(root))


def _packet(tmp_path):
    source = tmp_path / "original"
    (source / "source").mkdir(parents=True)
    (source / "plan.json").write_text("{}\n")
    files = {"introduced_since_2017.xml": _xml([
        _legislation(), _legislation(BillId="HB 1002", BillNumber="1002"),
    ])}
    for biennium in BIENNIA:
        files[f"roster_{biennium}.xml"] = _xml([
            {"Id": "101", "Agency": "House", "Name": "Example Member", "Party": "D"},
        ], members=True)
    receipts = []
    for name, body in files.items():
        path = source / "source" / name
        path.write_bytes(body)
        receipts.append({"file": name, "ok": True, "content_sha256": sha256_file(path)})
    (source / "receipts.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in receipts)
    )
    (source / "manifest.json").write_text(json.dumps({
        "files": {str(p.relative_to(source)): sha256_file(p)
                  for p in sorted(source.rglob("*")) if p.is_file()},
    }))
    bills = tmp_path / "bills.parquet"
    pd.DataFrame([_bill(), _bill(bill_id="other", state="OR")]).to_parquet(bills)
    return source, bills


def test_packet_freezes_complete_source_and_exact_baseline_without_modifying_inputs(tmp_path):
    source, bills = _packet(tmp_path)
    source_hash, bills_hash = sha256_file(source / "manifest.json"), sha256_file(bills)
    out = tmp_path / "reconciliation"
    report = build_reconciliation(
        source, bills, out, source_sha256=source_hash, bills_sha256=bills_hash,
    )
    assert report["baseline_bills"] == 1
    assert report["source_only_original_records"] == 1
    assert report["session_roster_party"] == {"D": 1}
    assert report["unique_original_records_with_legal_title"] == 1
    assert sha256_file(bills) == bills_hash
    original = source / "source/introduced_since_2017.xml"
    assert (out / "source/official_packet/source/introduced_since_2017.xml").read_bytes() == (
        original.read_bytes()
    )
    verify_manifest(out, {"bill_reconciliation.jsonl", "source_only_originals.jsonl"})
    with pytest.raises(FileExistsError):
        build_reconciliation(source, bills, out)
    original.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        build_reconciliation(
            source, bills, tmp_path / "changed", source_sha256=source_hash,
            bills_sha256=bills_hash,
        )
    assert not (tmp_path / "changed").exists()


def _supplement(tmp_path, source, bills, *, successful=True, wrong_bill=False):
    pd.DataFrame([
        _bill(),
        _bill(bill_id="resolution", identifier="SR 8663", originating_chamber="upper"),
    ]).to_parquet(bills)
    supplement = tmp_path / "supplement"
    (supplement / "source").mkdir(parents=True)
    url = (
        "https://wslwebservices.leg.wa.gov/LegislationService.asmx/GetLegislation?"
        "biennium=2019-20&billNumber=8663"
    )
    name = "2019-20_SR_8663.xml"
    (supplement / "plan.json").write_text(json.dumps({
        "initial_source_manifest_sha256": sha256_file(source / "manifest.json"),
        "requests": [{
            "file": name, "bill_id": "resolution", "identifier": "SR 8663",
            "biennium": "2019-20", "url": url,
        }],
    }))
    receipt = {"file": name, "url": url, "ok": successful, "content_sha256": None}
    if successful:
        path = supplement / "source" / name
        path.write_bytes(_xml([_legislation(
            BillId="SR 8663", BillNumber="8664" if wrong_bill else "8663",
            OriginalAgency="Senate", IntroducedDate="0001-01-01T00:00:00",
        )]))
        receipt["content_sha256"] = sha256_file(path)
    (supplement / "receipts.jsonl").write_text(json.dumps(receipt) + "\n")
    (supplement / "run.json").write_text("{}\n")
    (supplement / "manifest.json").write_text(json.dumps({
        "files": {str(p.relative_to(supplement)): sha256_file(p)
                  for p in sorted(supplement.rglob("*")) if p.is_file()},
    }))
    return supplement


@pytest.mark.parametrize("successful", [True, False])
def test_resolution_supplement_preserves_placeholder_dates_and_explicit_failures(
    tmp_path, successful,
):
    source, bills = _packet(tmp_path)
    supplement = _supplement(tmp_path, source, bills, successful=successful)
    out = tmp_path / "successor"
    report = build_reconciliation(
        source, bills, out, source_sha256=sha256_file(source / "manifest.json"),
        bills_sha256=sha256_file(bills), supplementary=supplement,
        supplementary_sha256=sha256_file(supplement / "manifest.json"),
    )
    with (out / "bill_reconciliation.jsonl").open() as stream:
        rows = [json.loads(line) for line in stream]
    assert rows[1]["filing_time_party"] == "unknown"
    assert report["unique_original_records_with_placeholder_introduction_date"] == int(successful)
    assert len(report["supplementary_retrieval_failures"]) == int(not successful)
    if successful:
        assert rows[1]["session_roster_party"] == "unknown"
        assert rows[1]["record_link_status"] == "unique_original_record"
        assert rows[1]["official_record_rows"] == [2]
        assert rows[1]["official_source_file_row_index"] == 0
        assert rows[1]["official_source_file"].endswith("source/2019-20_SR_8663.xml")
    else:
        assert rows[1]["record_link_status"] == "missing_original_record"
    verify_manifest(out, {"source/supplementary_packet/manifest.json"})


def test_supplement_rejects_unbound_or_wrong_bill_responses_before_writing(tmp_path):
    source, bills = _packet(tmp_path)
    supplement = _supplement(tmp_path, source, bills, wrong_bill=True)
    with pytest.raises(ValueError, match="supplied together"):
        build_reconciliation(source, bills, tmp_path / "unbound", supplementary=supplement)
    out = tmp_path / "wrong"
    with pytest.raises(ValueError, match="different bill"):
        build_reconciliation(
            source, bills, out, source_sha256=sha256_file(source / "manifest.json"),
            bills_sha256=sha256_file(bills), supplementary=supplement,
            supplementary_sha256=sha256_file(supplement / "manifest.json"),
        )
    assert not out.exists()


def _native(rows):
    return parse_records(_xml_sponsors(rows), sponsors=True)


def _xml_sponsors(rows):
    root = ET.Element(f"{{{NS}}}ArrayOfSponsor")
    for row in rows:
        element = ET.SubElement(root, f"{{{NS}}}Sponsor")
        for key, value in row.items():
            ET.SubElement(element, f"{{{NS}}}{key}").text = value
    return ET.tostring(root)


def test_native_primary_uses_explicit_type_not_first_position_or_order():
    rows = _native([
        {"Id": "999", "Agency": "House", "Type": "Secondary", "Order": "0"},
        {"Id": "101", "Agency": "House", "Type": "Primary", "Order": "9"},
    ])
    result = resolve_native_primary(rows, _members(), biennium="2019-20", agency="House")
    assert result["native_primary_session_roster_party"] == "D"
    assert result["native_primary_resolution"][0]["sponsor_row_index"] == 1
    assert result["filing_time_party"] == "unknown"
    assert result["analytical_admission"] is False


@pytest.mark.parametrize(("rows", "reason"), [
    ([("101", "Secondary")], "no_explicit_primary_sponsor"),
    ([("999", "Primary"), ("101", "Secondary")], "unresolved_explicit_primary_sponsor"),
    ([("101", "Unspecified")], "unsupported_native_sponsor_type"),
    ([("101", "Primary"), ("202", "Primary")], "conflicting_explicit_primary_parties"),
])
def test_native_primary_preserves_unresolved_and_mixed_party_cases(rows, reason):
    sponsors = _native([{"Id": identity, "Agency": "House", "Type": kind}
                        for identity, kind in rows])
    members = [*_members(), {
        "Biennium": "2019-20", "Id": "202", "Agency": "House", "Party": "R",
        "Name": "Another Member", "source_row_index": 2,
    }]
    result = resolve_native_primary(sponsors, members, biennium="2019-20", agency="House")
    assert result["native_primary_session_roster_party"] == "unknown"
    assert result["native_primary_party_reason"] == reason


def test_native_primary_cannot_borrow_another_chamber():
    sponsors = _native([{"Id": "101", "Agency": "Senate", "Type": "Primary"}])
    result = resolve_native_primary(sponsors, _members(), biennium="2019-20", agency="House")
    assert result["native_primary_session_roster_party"] == "unknown"
    assert result["native_primary_resolution"][0]["reason"] == "native_primary_chamber_conflict"


def test_identical_primary_ids_keep_every_row_and_duplicate_flag_without_inventing_disagreement():
    sponsors = _native([
        {"Id": "101", "Agency": "House", "Type": "Primary"},
        {"Id": "101", "Agency": "House", "Type": "Primary"},
    ])
    result = resolve_native_primary(sponsors, _members(), biennium="2019-20", agency="House")
    assert result["native_primary_session_roster_party"] == "D"
    assert result["native_primary_duplicate_ids"] == {"101": 2}
    assert [row["sponsor_row_index"] for row in result["native_primary_resolution"]] == [0, 1]

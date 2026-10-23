import csv
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from state_politics.analysis.cycle_topics import input_text, make_input
from state_politics.bills.published_corpus_text import (
    CSV_MEMBER,
    DATASET_URL,
    FLAGS,
    SOURCE_SCHEMA,
    build,
    load,
    printed_identity,
)
from state_politics.provenance import sha256_file

HI = (
    "HOUSE OF REPRESENTATIVES\nH.B. NO.\n1607\nTHIRTY-SECOND\nLEGISLATURE, 2024\n"
    "STATE OF HAWAII\nA BILL FOR AN ACT\nRELATING TO TESTING.\n"
    "BE IT ENACTED BY THE LEGISLATURE OF THE STATE OF HAWAII:\n"
    "SECTION 1. Complete policy.\u2028No words or Unicode are removed.\n"
)
RI = (
    "2023 -- H 5866\nSTATE OF RHODE ISLAND\nIN GENERAL ASSEMBLY\n"
    "JANUARY SESSION, A.D. 2023\nAN ACT\nRELATING TO TESTING\n"
    "It is enacted by the General Assembly as follows:\n"
    "SECTION 1. Complete policy.\nThis act would take effect upon passage.\n"
)
MI = (
    "HB-5569, As Passed House, June 12, 2024\nSUBSTITUTE FOR\nHOUSE BILL NO. 5569\n"
    "A bill concerning testing.\nTHE PEOPLE OF THE STATE OF MICHIGAN ENACT:\n"
    "Sec. 1. Complete policy; no machine summary.\n"
)
NE = (
    "ONE HUNDRED EIGHTH LEGISLATURE\nSECOND SESSION\nLEGISLATIVE RESOLUTION 430\n"
    "Introduced by a Senator.\nPURPOSE: Complete policy.\n"
    "NOW, THEREFORE, BE IT RESOLVED BY THE MEMBERS OF THE ONE HUNDRED EIGHTH "
    "LEGISLATURE OF NEBRASKA, SECOND SESSION:\n"
    "1. That an interim study be conducted.\n2. That the committee report its findings.\n"
)


def binding(path):
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def repin(root, member):
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["packet_artifacts"][member] = binding(root / member)
    write_json(root / "manifest.json", manifest)


@pytest.fixture
def packet_source(tmp_path):
    source = tmp_path / "source"
    (source / "raw").mkdir(parents=True)
    prologue = (
        "2023 HI H 1607\nAuthor: A source field, not historical party\nVersion: Introduced\n"
        "Version Date: 01/17/2024\n"
    )
    records = [
        {"Bill_Number": "H 1607", "Jurisdiction": "Hawaii", "Bill_Text": prologue + HI,
         "Year": "2024", "Version_Date": "01/17/2024", "summary": "AI summary, never gold",
         "analyst_results": "{'topic': 'not a model input'}"},
        {"Bill_Number": "H 5866", "Jurisdiction": "Rhode Island", "Bill_Text": RI,
         "Year": "2024", "Version_Date": "03/01/2023", "summary": "Not human coding",
         "analyst_results": "{}"},
        {"Bill_Number": "H 1607", "Jurisdiction": "Hawaii",
         "Bill_Text": prologue + HI.replace("LEGISLATURE, 2024", "LEGISLATURE, 2023"),
         "Year": "2024", "Version_Date": "01/17/2024", "summary": "",
         "analyst_results": "{}"},
    ]
    with (source / CSV_MEMBER).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    csv_path = source / CSV_MEMBER
    md5 = hashlib.md5(csv_path.read_bytes(), usedforsecurity=False).hexdigest()
    write_json(source / "report.json", {
        "network_closed": True, "error": None, "source_admissions": 0,
        "classifier_calls": 0, "human_gold": False, "publication": False,
    })
    write_json(source / "dataset-inventory.json", {
        "dataset_response": {
            "url": DATASET_URL, "body": CSV_MEMBER, "http_status": 200, "curl_returncode": 0,
            "body_binding": binding(csv_path),
        },
        "advertised_md5": md5, "actual_md5": md5,
        "original_fieldnames": list(records[0]), "n_complete_csv_records": len(records),
    })
    write_json(source / "manifest.json", {
        "schema": SOURCE_SCHEMA, "network_closed": True,
        "source_admission": False, "publication": False,
        "artifacts": {p.relative_to(source).as_posix(): binding(p)
                      for p in sorted(source.rglob("*")) if p.is_file()},
    })
    gap = tmp_path / "gap.parquet"
    contexts = [
        {"bill_id": "hi1607", "state": "HI", "identifier": "HB 1607",
         "session_identifier": "2024", "title": "Relating to Testing.",
         "neither_source_observed": True, "source_filing_date": None},
        {"bill_id": "ri5866", "state": "RI", "identifier": "HB 5866",
         "session_identifier": "2023", "title": "Canonical title unchanged",
         "neither_source_observed": True, "source_filing_date": ""},
    ]
    pq.write_table(pa.Table.from_pylist(contexts), gap)
    return source, gap, tmp_path / "packet", records, contexts


def recover(source, gap, out):
    return build(
        source, gap, out,
        source_manifest_sha256=sha256_file(source / "manifest.json"),
        gap_queue_sha256=sha256_file(gap),
    )


def test_full_source_records_metadata_conflicts_and_exact_policy_spans_survive(packet_source):
    source, gap, out, records, contexts = packet_source
    result = recover(source, gap, out)
    views, recovered, _, _ = load(out, contexts)
    assert recovered == contexts
    assert [view["text"] for view in views] == [HI, RI]
    assert [view["source_record"] for view in views] == records[:2]
    assert views[0]["publisher_prologue"] + views[0]["text"] == records[0]["Bill_Text"]
    assert views[0]["native_body_source_span"] == [
        len(views[0]["publisher_prologue"]), len(records[0]["Bill_Text"]),
    ]
    assert views[1]["session_identifier"] == "2023"
    assert views[1]["source_record"]["Year"] == "2024"
    assert result["counts"]["n_recovered_contexts"] == 2
    assert result["counts"]["source_dispositions"] == {
        "exact_original_gap_own_printed_identity": 2,
        "unresolved_or_conflicting_own_printed_identity_session_or_body": 1,
    }
    assert (out / "source-evidence" / CSV_MEMBER).read_bytes() == (source / CSV_MEMBER).read_bytes()
    assert pq.read_table(out / "context_inventory.parquet").schema == pq.read_table(gap).schema
    for view in views:
        assert all(view[flag] is False for flag in FLAGS)
        assert all(view["text"][span["start"]:span["end"]] == span["text"]
                   for span in view["source_identity"]["printed_evidence"])
        model_input = make_input(view, "retained_text", "a/bound/source", 0)
        assert input_text(model_input) == view["text"]
        assert "AI summary" not in input_text(model_input)
        assert "Section 1:" not in input_text(model_input)
        assert view["archive_generated_prologue_preserved"] is False


@pytest.mark.parametrize("text,context", [
    (HI.replace("1607", "1608"), {"state": "HI", "identifier": "HB 1607",
                                "session_identifier": "2024", "title": "Relating to Testing."}),
    (HI.replace("LEGISLATURE, 2024", "LEGISLATURE, 2023"),
     {"state": "HI", "identifier": "HB 1607", "session_identifier": "2024",
      "title": "Relating to Testing."}),
    (HI, {"state": "HI", "identifier": "HB 1607", "session_identifier": "2024",
          "title": "Conflicting own bill caption."}),
    (RI.replace("JANUARY SESSION, A.D. 2023", "effective January 1, 2023"),
     {"state": "RI", "identifier": "HB 5866", "session_identifier": "2023"}),
    (RI.replace("2023 -- H 5866", "2024 -- H 5866"),
     {"state": "RI", "identifier": "HB 5866", "session_identifier": "2023"}),
    (RI.replace("It is enacted", "This is a summary"),
     {"state": "RI", "identifier": "HB 5866", "session_identifier": "2023"}),
    (MI.replace("June 12, 2024", "June 12, 2025"),
     {"state": "MI", "identifier": "HB 5569", "session_identifier": "2023-2024"}),
])
def test_rejects_other_years_effective_dates_wrong_numbers_and_metadata_substitutes(text, context):
    assert printed_identity(text, context) is None


@pytest.mark.parametrize("text,context", [
    (MI, {"state": "MI", "identifier": "HB 5569", "session_identifier": "2023-2024"}),
    (NE, {"state": "NE", "identifier": "LR 430", "session_identifier": "108"}),
])
def test_actual_edition_year_and_full_resolution_venue_are_not_aliases(text, context):
    identity = printed_identity(text, context)
    assert identity["session_identifier"] == context["session_identifier"]
    assert all(text[span["start"]:span["end"]] == span["text"]
               for span in identity["printed_evidence"])


@pytest.mark.parametrize("state,session,preamble,clause", [
    ("CT", "2024",
     "STATE OF CONNECTICUT\nFebruary Session, 2024\nSubstitute House Bill No. 42\n",
     "Be it enacted by the Senate and House of Representatives in General Assembly convened:"),
    ("IN", "2024",
     "Second Regular Session of the 123rd General Assembly (2024)\nHOUSE ENROLLED ACT No. 42\n",
     "Be it enacted by the General Assembly of the State of Indiana:"),
    ("KS", "2023-2024", "Session of 2024\nHOUSE BILL No. 42\n",
     "Be it enacted by the Legislature of the State of Kansas:"),
    ("MD", "2024",
     "HOUSE BILL 42\nRequested: October 5, 2023\n"
     "Introduced and read first time: January 10, 2024\n",
     "SECTION 1. BE IT ENACTED BY THE GENERAL ASSEMBLY OF MARYLAND:"),
    ("MS", "2024", "MISSISSIPPI LEGISLATURE\n2024 Regular Session\nHouse Bill 42\n",
     "BE IT ENACTED BY THE LEGISLATURE OF THE STATE OF MISSISSIPPI:"),
    ("OK", "2024",
     "STATE OF OKLAHOMA\n2nd Session of the 59th Legislature (2024)\nHOUSE BILL 42\n",
     "BE IT ENACTED BY THE PEOPLE OF THE STATE OF OKLAHOMA:"),
    ("UT", "2024", "H.B. 42 Enrolled\n2024 GENERAL SESSION\nSTATE OF UTAH\n",
     "Be it enacted by the Legislature of the state of Utah:"),
    ("VA", "2024", "HOUSE BILL NO. 42\nOffered January 10, 2024\nPrefiled December 1, 2023\n",
     "Be it enacted by the General Assembly of Virginia:"),
    ("WV", "2024", "WEST VIRGINIA LEGISLATURE\n2024 REGULAR SESSION\nHouse Bill 42\n",
     "Be it enacted by the Legislature of West Virginia:"),
])
def test_reviewed_formal_profiles_keep_own_years_separate_from_dates(
    state, session, preamble, clause,
):
    text = preamble + "AN ACT concerning testing.\n" + clause + "\nSection 1. Complete policy."
    context = {"state": state, "identifier": "HB 42", "session_identifier": session}
    identity = printed_identity(text, context)
    assert identity is not None
    assert all(text[span["start"]:span["end"]] == span["text"]
               for span in identity["printed_evidence"])
    assert printed_identity(text, {**context, "session_identifier": "2025"}) is None
    assert printed_identity(text, {**context, "identifier": "HB 43"}) is None


@pytest.mark.parametrize("defect", [
    "policy_body", "original_record", "ordinal", "approval", "negative_disposition",
    "original_missingness", "producer",
])
def test_rejects_rebound_corrupt_views_negatives_contexts_and_producers(packet_source, defect):
    source, gap, out, _, _ = packet_source
    recover(source, gap, out)
    if defect == "negative_disposition":
        member = "source_row_dispositions.jsonl"
        rows = [json.loads(line) for line in (out / member).open()]
        rows[2]["disposition"] = "exact_original_gap_own_printed_identity"
        (out / member).write_text("".join(json.dumps(row) + "\n" for row in rows))
    elif defect == "original_missingness":
        member = "context_inventory.parquet"
        rows = pq.read_table(out / member).to_pylist()
        rows[0]["source_filing_date"] = ""
        pq.write_table(pa.Table.from_pylist(rows), out / member)
    elif defect == "producer":
        member = "producer/published_corpus_text.py"
        with (out / member).open("a") as stream:
            stream.write("\n# Unbound replacement\n")
    else:
        member = "views.jsonl"
        rows = [json.loads(line) for line in (out / member).open()]
        if defect == "policy_body":
            rows[0]["text"] = rows[0]["text"][:100]
        elif defect == "original_record":
            rows[0]["source_record"]["summary"] = "Silently replaced original metadata"
        elif defect == "ordinal":
            rows[0]["source_record_ordinal"] = 2
        else:
            rows[0]["training_approved"] = True
        (out / member).write_text("".join(json.dumps(row) + "\n" for row in rows))
    repin(out, member)
    with pytest.raises(ValueError, match="incompatible published corpus"):
        load(out)


def test_metadata_nulls_and_external_pins_are_not_silently_replaced(packet_source):
    source, gap, out, _, contexts = packet_source
    recover(source, gap, out)
    contexts[0]["source_filing_date"] = ""
    with pytest.raises(ValueError, match="missingness/type changed"):
        load(out, contexts)
    with pytest.raises(ValueError, match="external source or queue anchor"):
        load(out, source_manifest_sha256="0" * 64)

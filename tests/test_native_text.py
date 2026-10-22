"""Complete native-reader inputs and finite, non-restarting source-text collection."""

import hashlib
import json

import fitz
import pytest
from test_native_inventory import ROBOTS, Transport

from state_politics.bills import native_inventory, native_text


def record():
    return {
        "native_id": "AR:2024S2:HB 1001", "state": "AR", "measure_type": "HB",
        "identifier": "HB 1001", "session_kind": "Second Extraordinary Session, 2024",
    }


@pytest.mark.parametrize("layout", ["lines", "inline", "abbreviated"])
def test_printed_identity_observation_never_infers_dates_from_metadata(layout):
    text = "State of Arkansas\nSecond Extraordinary Session, 2024\nHOUSE BILL 1001\nBy: A\n"
    if layout == "inline":
        text = text.replace("\n", " ")
    elif layout == "abbreviated":
        text = text.replace("HOUSE BILL", "HB")
    observed = native_text.observe_header(text, record(), "Arkansas")
    assert observed["all_expected_header_observations_present"]
    for field in ("printed_identifier", "printed_session", "printed_state"):
        span = observed[field]
        assert text[span["start"]:span["end"]] == span["text"]
    assert observed["filing_date_inferred"] is False
    assert observed["original_version_certified"] is False


@pytest.mark.parametrize("wrong", ["identity", "session", "body-reference"])
def test_unmatched_or_body_only_identity_cannot_support_source_join(wrong):
    text = "State of Arkansas\nSecond Extraordinary Session, 2024\nHOUSE BILL 1001\nBy: A\n"
    if wrong == "identity":
        text = text.replace("1001", "10010")
    elif wrong == "session":
        text = text.replace("Second Extraordinary Session", "Regular Session")
    else:
        text = text.replace("1001", "9999") + "This amends HOUSE BILL 1001."
    assert not native_text.observe_header(
        text, record(), "Arkansas",
    )["all_expected_header_observations_present"]


def test_two_readers_retain_all_pages_empty_page_and_declared_joiner(tmp_path):
    path = tmp_path / "bill.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((60, 60), "State of Arkansas\nSecond Extraordinary Session, 2024\n"
                         "HOUSE BILL 1001\nBy: A\nComplete first-page source.")
        pdf.new_page()
        pdf.save(path)
    original = path.read_bytes()
    pages, views = native_text.extract_pdf(path, record(), "Arkansas")
    assert len(pages) == 4 and len(views) == 2
    for view in views:
        selected = [row for row in pages if row["reader"] == view["reader"]]
        assert view["text"] == "\f".join(row["text"] for row in selected)
        assert view["text"].endswith("\f") and view["n_pages"] == 2
        assert view["input_sha256"] == hashlib.sha256(view["text"].encode()).hexdigest()
        assert view["n_input_characters"] == len(view["text"])
    assert path.read_bytes() == original


def prepare_capture(tmp_path, monkeypatch, responses, cap):
    monkeypatch.setattr(native_inventory, "url_is_fetchable", lambda _: None)
    transport = Transport([ROBOTS, *responses])
    raw = tmp_path / "raw"
    auth = {"states": {"AR": {
        "requests_authorized": True, "new_exchange_cap": cap,
        "origins": ["https://publisher.test"],
    }}}
    capture = native_inventory.Capture(
        raw, auth, session=transport, sleeper=lambda _: None, clock=lambda: 0,
    )
    capture.get("AR", "https://publisher.test/robots.txt", purpose="fixture robots")
    rows = [{
        "record": {**record(), "native_id": f"AR:2024S2:HB {number}"},
        "publisher_pdf_link": {"absolute_url": f"https://publisher.test/bill-{number}.pdf"},
    } for number in range(1, 4)]
    (raw / "source_plan.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setattr(native_text, "Capture", lambda *_: capture)
    return raw, capture, transport


def test_collector_seals_at_physical_budget_and_cannot_restart(tmp_path, monkeypatch):
    raw, capture, transport = prepare_capture(
        tmp_path, monkeypatch, [(200, b"%PDF-one", {}), (200, b"%PDF-two", {})], cap=3,
    )
    report = native_text.collect(raw)
    assert report["states"]["AR"]["new_physical_http_used"] == 3
    assert report["states"]["AR"]["closed_for_this_run"]
    assert report["states"]["AR"]["dispatchable_remaining"] == 0
    assert len(native_text.json_rows(raw / "document_receipts.jsonl")) == 2
    with pytest.raises(native_inventory.Refusal, match="closed/stopped"):
        native_text.collect(raw)
    assert capture.used("AR") == len(transport.calls) == 3


@pytest.mark.parametrize("status", [403, 429, 503])
def test_access_or_service_stop_preserves_failed_body_and_sends_no_next_request(
    tmp_path, monkeypatch, status,
):
    raw, capture, transport = prepare_capture(
        tmp_path, monkeypatch, [(status, b"retained failure body", {})], cap=4,
    )
    report = native_text.collect(raw)
    receipts = native_text.json_rows(raw / "document_receipts.jsonl")
    assert len(receipts) == 1 and receipts[0]["explicit_stop"]
    assert receipts[0]["exchanges"] == ["AR-02"]
    assert (raw / "AR-02.body").read_bytes() == b"retained failure body"
    assert report["states"]["AR"]["binding_restriction"]
    assert capture.used("AR") == len(transport.calls) == 2


def test_physical_lf_jsonl_keeps_unicode_source_separators(tmp_path):
    path = tmp_path / "source.jsonl"
    value = {"text": "complete\u2028source\u2029ending"}
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n")
    assert native_text.json_rows(path) == [value]


def test_original_single_exchange_prototype_receipt_has_an_exact_nonrewriting_adapter():
    receipt = {
        "native_id": "AR:2024S2:HB 1001", "source_plan_ordinal": 0,
        "exchanges": ["AR-02"], "status": 200, "source_url": "https://publisher.test/bill.pdf",
    }
    original = json.dumps(receipt)
    event = {"status": 200, "url": receipt["source_url"], "complete_body": True}
    assert native_text.terminal_result(receipt, {"AR-02": event}) is event
    assert json.dumps(receipt) == original
    assert native_text.terminal_result(
        receipt, {"AR-02": {**event, "url": "https://publisher.test/another.pdf"}},
    ) is None
    assert native_text.terminal_result(
        {**receipt, "unverified_extra": True}, {"AR-02": event},
    ) is None

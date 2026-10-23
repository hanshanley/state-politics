"""Offline dual-reader, complete-version, queue and tamper replay checks."""

from __future__ import annotations

import copy
import shutil
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pymupdf
import pytest

from state_politics.bills import nj_library_text as nj


def _cover(kind, number):
    return (
        f"{kind}, No. {number}\n\nSTATE OF NEW JERSEY\n220th LEGISLATURE\n"
        "INTRODUCED MAY 8, 2023\nSponsored by:\nMember é\nSYNOPSIS\nA policy.\n"
        "CURRENT VERSION OF TEXT\nAs introduced.\n"
    )


def _texts():
    return [
        "LEGISLATIVE HISTORY CHECKLIST\nS200 is a companion; not an own bill cover.\n",
        "EXPLANATION – Matter underlined is new matter.\n"
        "P.L. 2023, CHAPTER 1, approved May 9, 2023\nAssembly, No. 100 (First Reprint)\n"
        "AN ACT concerning testing.\nBE IT ENACTED by the State\nof New Jersey:\nPolicy é.\n",
        "A100 [1R]\n2\n2. This act shall take effect immediately.\nFull enacted ending é.\n",
        _cover("ASSEMBLY", 100),
        "A100 MEMBER\n2\nAN ACT concerning testing.\n"
        "BE IT ENACTED by the State of New Jersey:\n"
        "2. This act shall take effect immediately.\nSTATEMENT\nThe statement continues\n",
        "A100 MEMBER\n3\nwith the final complete statement paragraph: é §123.\n",
        "Office of Legislative Services\nFISCAL ESTIMATE\nASSEMBLY, No. 100\n"
        "STATE OF NEW JERSEY\n220th LEGISLATURE\nNot a policy cover.\n",
        _cover("SENATE", 200),
        "S200 OTHER\n2\nAN ACT concerning another policy.\n"
        "BE IT ENACTED by the State of New Jersey:\n"
        "2. This act shall take effect immediately.\nSTATEMENT\nFull second bill é.\n",
        "COMMITTEE\nSTATEMENT TO\nASSEMBLY, No. 100\nSTATE OF NEW JERSEY\n"
        "220th LEGISLATURE\nAncillary, citing S200 and A100.\n",
    ]


@pytest.fixture
def work():
    # Never use pytest's system temporary directory for source or packet files.
    directory = Path.cwd() / ".pytest_cache" / "nj-library-text" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def _capture(source, ordinal, label, url, content, *, robots=False):
    stem = f"raw/{ordinal:04d}-{label}"
    (source / "raw").mkdir(exist_ok=True)
    (source / f"{stem}.body").write_bytes(content)
    (source / f"{stem}.headers").write_bytes(b"HTTP/2 200\r\ncontent-type: test\r\n\r\n")
    nj._write(source / f"{stem}.transport.json", {
        "url": url, "url_effective": url, "http_code": 200, "response_code": 200,
        "exitcode": 0, "num_redirects": 0, "method": "GET", "size_download": len(content),
    })
    (source / f"{stem}.stderr").write_bytes(b"")
    return {
        "ordinal": ordinal, "url": url, "host": "repo.njstatelib.org", "label": label,
        "status": 200, "curl_returncode": 0, "access_stop": False,
        "body": f"{stem}.body", "body_sha256": nj._sha(content), "body_bytes": len(content),
        "headers": f"{stem}.headers", "transport": f"{stem}.transport.json",
        "stderr": f"{stem}.stderr", "is_robots": robots,
        "automatic_retries": False, "automatic_redirects": False,
        "original_capture_extra_metadata": {"preserve": ["all", "fields", "é"]},
    }


@pytest.fixture
def packet(work, monkeypatch):
    source = work / "source"
    source.mkdir()
    with pymupdf.open() as pdf:
        for text in _texts():
            pdf.new_page().insert_text((40, 40), text, fontsize=10)
        content = pdf.tobytes()
    robot = _capture(source, 2, "robots", "https://repo.njstatelib.org/robots.txt",
                     b"User-agent: *\nDisallow: /admin\n", robots=True)
    capture = _capture(
        source, 3, "fixture", "https://repo.njstatelib.org/server/api/core/bitstreams/fixture/content",
        content,
    )
    entry = {"capture": capture, "pdf": "fixture/" + capture["body"],
             "pdf_sha256": nj._sha(content), "n_pages": len(_texts())}
    nj._write(source / nj.BATCH_NAME, {
        "pdfs": [entry], "queue": nj.QUEUE_NAME, "all_source_approvals": False,
        "source_urls_directly_discovered_or_retained_302_location": True,
    })
    nj._write_rows(source / "request-ledger.jsonl", [robot, capture])
    nj._write(source / "scope.json", {
        "inherited_exchange": {
            "raw_response_retained": False, "response_body_sha256": None,
            "url": "https://api.github.com/user",
        }, "all_original_scope_fields": ["retained", "é"],
    })
    originals = [{
        "bill_id": f"ocd-bill/{number}", "state": "NJ", "session_identifier": "220",
        "identifier": f"{kind} {number}", "title": f"Original title {number} é",
        "session_start_date": "2022-01-11", "session_end_date": "2023-12-31",
        "source_introduction_date": "2023-05-08", "source_filing_date": "",
        "neither_source_observed": True, "model_input_approved": False,
        "filing_time_text_certified": False, "analytical_admission": False,
        "all_original_fields": {"nested": ["é", "null-preserved"], "nullable": None},
        "origin_filing_action_ids": [], "original_nullable": None,
    } for kind, number in [("A", 100), ("S", 200)]]
    filler = {**originals[0], "bill_id": "outside", "identifier": "AR 10"}
    queue = work / "queue.parquet"
    pq.write_table(pa.Table.from_pylist(originals + [filler] * (21576 - 2)), queue)
    monkeypatch.setattr(nj, "PINNED_PDFS", {
        capture["body"]: (nj._sha(content), len(content), len(_texts()), ("A 100", "S 200")),
    })
    monkeypatch.setattr(nj, "BATCH_SHA256", nj._binding(source / nj.BATCH_NAME)["sha256"])
    monkeypatch.setattr(nj, "GAP_SHA256", nj._binding(queue)["sha256"])
    out = work / "packet"
    nj.build_nj_library(source, queue, out)
    return out, source, queue, originals


def _rebind(packet, name):
    manifest = nj._json(packet / "manifest.json")
    manifest["packet_artifacts"][name] = nj._binding(packet / name)
    nj._write(packet / "manifest.json", manifest)


def test_separates_companions_versions_and_all_statement_continuations():
    versions, dispositions = nj.separate_versions(_texts())
    assert [(v["identifier"], v["kind"], v["page_ordinals"]) for v in versions] == [
        ("A 100", "enacted_version", [2, 3]),
        ("A 100", "bill_cover", [4, 5, 6]),
        ("S 200", "bill_cover", [8, 9]),
    ]
    assert versions[0]["external_same_bill_cover_spans"][2]["page_ordinal"] == 4
    assert versions[0]["printed_version"]["text"].endswith("(First Reprint)\n")
    assert versions[1]["continuations"][-1]["folio"] == 3
    assert [r["page_ordinal"] for r in dispositions
            if r["disposition"] != "selected_complete_version"] == [1, 7, 10]
    assert len(dispositions) == len(_texts())


@pytest.mark.parametrize("prefix", [
    "Office of Legislative Services\nFISCAL ESTIMATE\n",
    "COMMITTEE\nSTATEMENT TO\n", "LEGISLATIVE HISTORY CHECKLIST\n", "See companion bill:\n",
])
def test_rejects_ancillary_or_cited_headers_even_with_all_cover_words(prefix):
    with pytest.raises(ValueError, match="own typed bill cover"):
        nj.printed_identity(prefix + _cover("ASSEMBLY", 100))


@pytest.mark.parametrize("old,new,reason", [
    ("220th", "221st", "session"),
    ("2023", "2024", "year"),
])
def test_rejects_wrong_printed_session_or_year(old, new, reason):
    with pytest.raises(ValueError, match=reason):
        nj.printed_identity(_cover("ASSEMBLY", 100).replace(old, new))


@pytest.mark.parametrize("change", ["folio", "number", "lost_final_header", "unknown_boundary"])
def test_rejects_ambiguous_or_missing_continuation_boundaries(change):
    pages = _texts()
    if change == "folio":
        pages[5] = pages[5].replace("\n3\n", "\n4\n")
    elif change == "number":
        pages[5] = pages[5].replace("A100", "S200")
    elif change == "lost_final_header":
        pages[5] = pages[5].replace("A100 MEMBER\n3", "A100 MEMBER")
    else:
        pages[6] = "An unidentified page cannot silently terminate a policy."
    with pytest.raises(ValueError, match="folio|header|boundary"):
        nj.separate_versions(pages)


def test_both_readers_full_unicode_text_spans_layout_and_original_rows(packet):
    out, _, queue, originals = packet
    rows, contexts, pins, manifest = nj.load_nj_library(out, originals)
    assert len(rows) == 6 and len(contexts) == 2
    assert contexts == pq.read_table(queue).slice(0, 2).to_pylist()
    assert manifest["counts"]["source_versions"] == 3
    assert manifest["counts"]["selected_reader_pages"] == 14
    assert len(pins) == len(manifest["packet_artifacts"]) + 1
    pages = nj._jsonl(out / "pages.jsonl")
    assert len(pages) == 20
    by_page = {(p["reader"], p["page_ordinal"]): p for p in pages}
    assert all(p.get("text_layout") for p in pages if p["reader"] == "pymupdf")
    assert all(p["layout_text"] for p in pages if p["reader"] == "pypdf")
    for row in rows:
        selected = row["source_version"]["page_ordinals"]
        expected = "\n".join(by_page[(row["reader"], i)]["text"] for i in selected)
        assert row["text"] == expected and "é" in expected
        assert row["text_binding"] == nj._text_binding(expected)
        assert row["source_record"]["original_queue_row"] in contexts
        assert all(row[flag] is False for flag in nj.FLAGS)
        for span in row["source_identity"]["printed_evidence"]:
            full_page = by_page[(row["reader"], span["page_ordinal"])]["text"]
            assert full_page[span["start"]:span["end"]] == span["text"]
            assert full_page.encode()[span["utf8_byte_start"]:span["utf8_byte_end"]] == (
                span["text"].encode()
            )
            if span["in_policy_text"]:
                assert expected[span["view_character_start"]:span["view_character_end"]] == (
                    span["text"]
                )
        version_span = row["source_version"]["printed_version"]
        if row["source_version"]["kind"] == "bill_cover":
            assert version_span["utf8_byte_start"] > version_span["start"]
        if row["identifier"] == "A 100" and row["source_version"]["kind"] == "bill_cover":
            assert expected.endswith(by_page[(row["reader"], 6)]["text"])
            assert "final complete statement paragraph" in expected
            assert "FISCAL ESTIMATE" not in expected and "Full second bill" not in expected


@pytest.mark.parametrize("change", [
    "session", "number", "state", "original_date", "duplicate", "mistyped_session",
])
def test_metadata_join_rejects_identity_dates_or_duplicate_changes(packet, change):
    out, _, _, originals = packet
    metadata = copy.deepcopy(originals)
    if change == "duplicate":
        metadata.append(copy.deepcopy(metadata[0]))
    elif change == "mistyped_session":
        metadata[0]["session_identifier"] = 220
    else:
        key, value = {
            "session": ("session_identifier", "221"), "number": ("identifier", "A 101"),
            "state": ("state", "HI"), "original_date": ("source_introduction_date", "2024-05-08"),
        }[change]
        metadata[0][key] = value
    with pytest.raises(ValueError, match="metadata|candidate|typed literal"):
        nj.load_nj_library(out, metadata)


@pytest.mark.parametrize("change", [
    "crop", "identity_span", "promote_flag", "mistyped_false", "context", "layout",
])
def test_rehashing_corrupt_output_does_not_bypass_full_replay(packet, change):
    out, _, _, _ = packet
    if change == "context":
        table = pq.read_table(out / "context_inventory.parquet")
        rows = table.to_pylist()
        rows[0]["all_original_fields"]["nested"].append("changed")
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema),
                       out / "context_inventory.parquet")
        name = "context_inventory.parquet"
    elif change == "layout":
        name = "pages.jsonl"
        rows = nj._jsonl(out / name)
        rows[0]["layout_text"] = "fabricated layout"
        nj._write_rows(out / name, rows)
    else:
        name = "views.jsonl"
        rows = nj._jsonl(out / name)
        if change == "crop":
            rows[0]["text"] = rows[0]["text"][:-15]
            rows[0]["raw_text_sha256"] = nj._sha(rows[0]["text"].encode())
        elif change == "identity_span":
            rows[0]["source_identity"]["printed_evidence"][0]["start"] += 1
        elif change == "promote_flag":
            rows[0]["scientific_approval"] = True
        else:
            rows[0]["training_admission"] = 0
        nj._write_rows(out / name, rows)
    _rebind(out, name)
    with pytest.raises(ValueError, match="replay|fields|schema"):
        nj.load_nj_library(out)


@pytest.mark.parametrize("change", [
    "pdf", "symlink", "hardlink", "outside", "producer", "manifest",
])
def test_rejects_corrupt_or_linked_sources_and_inventory(packet, change):
    out, _, _, _ = packet
    source_name = "source-evidence/raw/0003-fixture.body"
    target = out / source_name
    if change == "pdf":
        target.write_bytes(target.read_bytes() + b"\ncorruption")
        _rebind(out, source_name)
    elif change in {"symlink", "hardlink"}:
        other = out.parent / "linked-original.body"
        target.rename(other)
        if change == "symlink":
            target.symlink_to(other)
        else:
            target.hardlink_to(other)
    elif change == "producer":
        name = "producer/nj_library_text.py"
        (out / name).write_text("print('not the producer')\n")
        _rebind(out, name)
    else:
        manifest = nj._json(out / "manifest.json")
        if change == "outside":
            manifest["packet_artifacts"]["../outside"] = nj._binding(target)
        else:
            manifest["approvals"]["model_input_approved"] = 0
        nj._write(out / "manifest.json", manifest)
    with pytest.raises(ValueError, match="hash|binding|linked|unsafe|producer|approval"):
        nj.load_nj_library(out)


def test_growing_parent_ledger_is_not_a_sealed_root_and_extra_batch_is_finite(packet):
    out, source, queue, originals = packet
    ledger = nj._jsonl(source / "request-ledger.jsonl")
    existing = nj._json(source / nj.BATCH_NAME)["pdfs"][0]
    content = (source / existing["capture"]["body"]).read_bytes()
    extra = _capture(
        source, 12, "extension",
        "https://repo.njstatelib.org/server/api/core/bitstreams/extension/content", content,
    )
    ledger.extend([
        {**extra, "ordinal": 10, "url": "https://repo.njstatelib.org/bitstreams/unrelated/download",
         "status": 302, "transport": "raw/not-retained-and-must-not-be-read.transport.json"},
        extra,
    ])
    nj._write_rows(source / "request-ledger.jsonl", ledger)
    nj.load_nj_library(out, originals)
    extension = source / "later-batch.json"
    nj._write(extension, {
        "pdfs": [{"capture": extra, "pdf": "later/" + extra["body"],
                  "pdf_sha256": nj._sha(content), "n_pages": len(_texts())}],
        "queue": nj.QUEUE_NAME, "all_source_approvals": False,
        "source_urls_directly_discovered_or_retained_302_location": True,
    })
    later = out.parent / "extended-packet"
    nj.build_nj_library(source, queue, later, batch_list=extension,
                        batch_sha256=nj._binding(extension)["sha256"])
    rows, contexts, _, manifest = nj.load_nj_library(later, originals)
    assert len(rows) == 12 and len(contexts) == 2
    assert len({row["view_id"] for row in rows}) == 12
    assert manifest["counts"]["source_pdfs"] == 2
    assert manifest["counts"]["retained_http_captures"] == 3
    unrelated = later / "source-evidence/raw/not-retained-and-must-not-be-read.transport.json"
    assert not unrelated.exists()
    before_after = nj._json(later / "consumed_input_hashes.json")
    assert before_after["before"] == before_after["after"]
    assert "additional-source-batch.json" in before_after["before"]


def _checklist_texts():
    return [
        "27:1D-10 & 27:1D-11\nLEGISLATIVE HISTORY CHECKLIST\n"
        "Compiled by the NJ State Law Library\nLAWS OF: 2023 CHAPTER: 184\n"
        "NJSA: 27:1D-10 & 27:1D-11\nBILL NO: S3976 (Substituted for A4934 (2R))\n"
        "DATE INTRODUCED: 6/15/2023\nFOLLOWING ARE ATTACHED IF AVAILABLE:\n"
        "FINAL TEXT OF BILL (S3976 Sca (1R) enacted) Yes\nINTRODUCED BILL: Yes\n",
        "VETO MESSAGE: No\nGOVERNOR'S PRESS RELEASE ON SIGNING: Yes\n"
        "FOLLOWING WERE PRINTED:\nTo check for circulating copies, "
        "contact New Jersey State Government\nREPORTS: No\nHEARINGS: No\n"
        "NEWSPAPER ARTICLES: No\nCL/JA\n",
    ]


def test_checklist_only_is_explicit_negative_without_aborting_valid_sources(packet):
    out, source, queue, originals = packet
    with pymupdf.open() as pdf:
        for text in _checklist_texts():
            pdf.new_page().insert_text((40, 40), text, fontsize=10)
        content = pdf.tobytes()
    capture = _capture(
        source, 16, "checklist-only",
        "https://repo.njstatelib.org/server/api/core/bitstreams/checklist-only/content", content,
    )
    nj._write_rows(source / "request-ledger.jsonl",
                   [*nj._jsonl(source / "request-ledger.jsonl"), capture])
    extension = source / "checklist-batch.json"
    nj._write(extension, {
        "pdfs": [{"capture": capture, "pdf": "later/" + capture["body"],
                  "pdf_sha256": nj._sha(content), "n_pages": 2}],
        "queue": nj.QUEUE_NAME, "all_source_approvals": False,
        "source_urls_directly_discovered_or_retained_302_location": True,
    })
    later = out.parent / "with-checklist-negative"
    nj.build_nj_library(source, queue, later, batch_list=extension,
                        batch_sha256=nj._binding(extension)["sha256"])
    rows, contexts, _, manifest = nj.load_nj_library(later, originals)
    assert len(rows) == 6 and len(contexts) == 2
    assert manifest["counts"]["source_pdfs"] == 2
    assert manifest["counts"]["source_versions"] == 3
    assert manifest["counts"]["all_reader_pages"] == 24
    assert manifest["counts"]["selected_reader_pages"] == 14
    assert all(row["identifier"] not in {"S 3976", "A 4934"} for row in rows)
    negatives = [row for row in nj._jsonl(later / "page_dispositions.jsonl")
                 if row["source_id"] == "checklist-only"]
    assert {(row["reader"], row["page_ordinal"]) for row in negatives} == {
        (reader, page) for reader in nj.TOOLS for page in (1, 2)
    }
    assert all(row["disposition"] == "library_checklist_only_no_bill_text"
               and row["version_ordinal"] is None and row["text_preserved_in_full"]
               for row in negatives)
    assert nj._json(later / "report.json")["source_negative_dispositions"] == [{
        "source_id": "checklist-only", "disposition": "library_checklist_only_no_bill_text",
        "recovered_text_views": 0, "page_ordinals": [1, 2], "readers": ["pypdf", "pymupdf"],
    }]
    pages = [row for row in nj._jsonl(later / "pages.jsonl")
             if row["source_id"] == "checklist-only"]
    assert len(pages) == 4
    assert all(row["text_binding"] == nj._text_binding(row["text"]) for row in pages)


def test_checklist_negative_does_not_relax_malformed_or_missing_bill_identity():
    pages = _checklist_texts()
    bad_inputs = [
        [pages[0].replace("NJ State Law Library", "another library"), pages[1]],
        [pages[0].replace("LAWS OF: 2023", "LAWS OF: 2024"), pages[1]],
        [pages[0].replace("BILL NO:", "MISSING:"), pages[1]],
        [pages[0] + "LAWS OF: 2024 CHAPTER: 1\n", pages[1]],
        [pages[0] + "STATE OF NEW YORK\n", pages[1]],
        [pages[0] + "SENATE,No. 3976\n", pages[1]],
        [pages[0], pages[1], "An unidentified third page."],
        [pages[0], pages[1] + "ASSEMBLY, No. 4934\nSTATE OF NEW JERSEY\n"],
        [pages[0], pages[1].replace("NEWSPAPER ARTICLES:", "AN ACT concerning policy.")],
        [pages[0], _cover("SENATE", 3976).replace("220th", "221st")],
        [pages[0], _texts()[4]],
    ]
    for bad in bad_inputs:
        with pytest.raises(ValueError):
            nj.separate_versions(bad)


@pytest.mark.parametrize(("ordinal", "marker", "state"), [
    ("Second", "2", "of New Jersey:"),
    ("Third", "3", "of New Jer sey:"),
])
def test_reprint_header_requires_matching_folios_and_exact_reader_state(ordinal, marker, state):
    # Real chapters 186/187 pair Second/Third Reprint with [2R]/[3R] continuations.
    pages = _texts()
    pages[1] = pages[1].replace("(First Reprint)", f"({ordinal} Reprint)")
    pages[1] = pages[1].replace("of New Jersey:", state)
    pages[2] = pages[2].replace("[1R]", f"[{marker}R]")
    versions, dispositions = nj.separate_versions(pages)
    enacted = versions[0]
    assert enacted["identifier"] == "A 100" and enacted["kind"] == "enacted_version"
    assert enacted["page_ordinals"] == [2, 3]
    assert f"({ordinal} Reprint)" in enacted["printed_version"]["text"]
    assert enacted["continuations"][0]["printed_label"] == f" [{marker}R]"
    state_span = enacted["identity_spans"][1]
    assert state_span["text"] == state
    assert pages[1][state_span["start"]:state_span["end"]] == state
    assert enacted["external_same_bill_cover_spans"][2]["page_ordinal"] == 4
    assert len(dispositions) == len(pages)
    bad_marker = pages.copy()
    bad_marker[2] = bad_marker[2].replace(f"[{marker}R]", "[1R]")
    with pytest.raises(ValueError, match="enacted printed reprint mismatch"):
        nj.separate_versions(bad_marker)
    unsupported = [text.replace(f"{ordinal} Reprint", "Fourth Reprint")
                   .replace(f"[{marker}R]", "[4R]")
                   for text in pages]
    with pytest.raises(ValueError, match="orphan printed bill continuation"):
        nj.separate_versions(unsupported)
    wrong_state = [text.replace(state, "of New York:") for text in pages]
    with pytest.raises(ValueError, match="absent printed enacted state"):
        nj.separate_versions(wrong_state)

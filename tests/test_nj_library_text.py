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


def test_single_page_policy_requires_explicit_profile_and_complete_body():
    texts = _texts()
    texts[1] += "2. This act shall take effect immediately.\nComplete final policy paragraph.\n"
    del texts[2]
    with pytest.raises(ValueError, match="missing complete bill continuation"):
        nj.separate_versions(texts)
    versions, dispositions = nj.separate_versions(
        texts, context_qualified_introductions={}, qualify_supported_years=True,
        allow_single_page_versions=True,
    )
    single = versions[0]
    assert single["kind"] == "enacted_version" and single["page_ordinals"] == [2]
    assert single["complete_single_page_policy_version"] is True
    assert single["boundary"] == {
        "reason": "next_distinct_own_version", "next_page_ordinal": 3,
    }
    assert len(dispositions) == len(texts)
    with pytest.raises(ValueError, match="explicit extended profile"):
        nj.separate_versions(texts, allow_single_page_versions=True)


def test_partial_single_page_is_preserved_but_never_admitted():
    texts = _texts()
    del texts[2]
    versions, dispositions = nj.separate_versions(
        texts, context_qualified_introductions={}, qualify_supported_years=True,
        allow_single_page_versions=True,
    )
    assert all(version["kind"] != "enacted_version" for version in versions)
    assert dispositions[1]["disposition"] == "quarantined_unproven_version"
    assert dispositions[1]["text_preserved_in_full"] is True
    introduced = next(version for version in versions if version["identifier"] == "A 100")
    assert introduced["quarantined_same_bill_source_versions"][0]["page_ordinals"] == [2]


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


def test_context_qualified_220_tail_preserves_original_dates_and_full_versions():
    context = {
        "bill_id": "ocd-bill/exact-original", "state": "NJ", "identifier": "A 100",
        "session_identifier": "220", "session_end_date": "2023-12-31",
        "source_introduction_date": "2024-01-04",
        "from_organization_id": "ocd-organization/original",
        "originating_chamber": "lower", "n_origin_introduction_actions": "1",
        "origin_introduction_action_ids": '["403ef215-b047-4664-888b-da4ca632b87c"]',
        "original_nullable": None, "original_unicode": "é",
    }
    actions = [{
        "action_id": "403ef215-b047-4664-888b-da4ca632b87c",
        "bill_id": context["bill_id"], "state": "NJ", "date": "2024-01-04T05:00:00+00:00",
        "organization_id": context["from_organization_id"], "description": "Introduced",
        "classification": "introduction|referral-committee", "chamber": "lower",
    }]
    qualified = {"original_context": context, "origin_introduction_actions": actions}
    pages = [_cover("ASSEMBLY", 100).replace("MAY 8, 2023", "JANUARY 4, 2024"),
             _texts()[4]]
    with pytest.raises(ValueError, match="year"):
        nj.separate_versions(pages)
    versions, dispositions = nj.separate_versions(
        pages, context_qualified_introductions={"A 100": qualified},
    )
    assert versions[0]["page_ordinals"] == [1, 2]
    assert len(dispositions) == 2
    proof = versions[0]["original_context_introduction_proof"]
    assert proof["original_context"] == context
    assert proof["original_context"]["session_end_date"] == "2023-12-31"
    assert proof["printed_introduction_date"] == "2024-01-04"
    assert proof["source_date_or_session_end_inferred"] is False
    span = proof["printed_date_span"]
    assert pages[0][span["start"]:span["end"]] == span["text"]
    section_pages = [pages[0], pages[1].replace(
        "2. This act shall take effect immediately.",
        "2. Sections 1 and 2 of this act shall take e ffect immediately.",
    )]
    section_versions, _ = nj.separate_versions(
        section_pages, context_qualified_introductions={"A 100": qualified},
    )
    effective = section_versions[0]["section_specific_effective_clause_evidence"]
    full = "\n".join(section_pages)
    assert full[effective["start"]:effective["end"]] == effective["text"]
    assert "take e ffect" in effective["text"]
    with pytest.raises(ValueError, match="effective section"):
        nj.separate_versions([
            _cover("ASSEMBLY", 100), section_pages[1],
        ])
    earlier = {
        "original_context": {**context, "source_introduction_date": "2023-05-08"},
        "origin_introduction_actions": [{**actions[0], "date": "2023-05-08T04:00:00+00:00"}],
    }
    earlier_pages = [_cover("ASSEMBLY", 100), section_pages[1]]
    with pytest.raises(ValueError, match="effective section"):
        nj.separate_versions(earlier_pages, context_qualified_introductions={"A 100": earlier})
    earlier_versions, _ = nj.separate_versions(
        earlier_pages, context_qualified_introductions={"A 100": earlier},
        qualify_supported_years=True,
    )
    assert earlier_versions[0]["original_context_introduction_proof"][
        "printed_introduction_date"
    ] == "2023-05-08"
    for change in (
        {"source_introduction_date": "2024-01-03"},
        {"identifier": "A 101"},
        {"session_identifier": "221"},
        {"origin_introduction_action_ids": "[]"},
        {"n_origin_introduction_actions": 2},
    ):
        with pytest.raises(ValueError, match="context"):
            nj.separate_versions(
                pages, context_qualified_introductions={"A 100": {
                    "original_context": {**context, **change},
                    "origin_introduction_actions": actions,
                }},
            )
    for change in ({"date": "2024-01-03"}, {"organization_id": "another-chamber"},
                   {"bill_id": "ocd-bill/another"}, {"chamber": "upper"},
                   {"classification": "referral-committee"}):
        with pytest.raises(ValueError, match="context"):
            nj.separate_versions(
                pages, context_qualified_introductions={"A 100": {
                    "original_context": context,
                    "origin_introduction_actions": [{**actions[0], **change}],
                }},
            )


def test_extended_profile_keeps_complete_versions_and_all_unproven_version_pages():
    pages = _texts()
    pages[2] = pages[2].replace(
        "2. This act shall take effect immediately.", "2. Unproven terminal policy text.",
    )
    with pytest.raises(ValueError, match="effective section"):
        nj.separate_versions(pages)
    versions, dispositions = nj.separate_versions(
        pages, context_qualified_introductions={}, qualify_supported_years=True,
    )
    assert [(row["identifier"], row["kind"]) for row in versions] == [
        ("A 100", "bill_cover"), ("S 200", "bill_cover"),
    ]
    quarantined = [row for row in dispositions
                   if row["disposition"] == "quarantined_unproven_version"]
    assert [row["page_ordinal"] for row in quarantined] == [2, 3]
    assert all(row["text_preserved_in_full"] for row in quarantined)
    assert versions[0]["quarantined_same_bill_source_versions"][0]["page_ordinals"] == [2, 3]
    assert "quarantined_same_bill_source_versions" not in versions[1]
    assert len(dispositions) == len(pages)
    ambiguous = list(pages)
    ambiguous[6] = "An unidentified boundary is still fatal, not a source of cropped text."
    with pytest.raises(ValueError, match="boundary"):
        nj.separate_versions(
            ambiguous, context_qualified_introductions={}, qualify_supported_years=True,
        )


def test_fourth_reprint_and_literal_word_spacing_require_the_extended_profile():
    pages = _texts()
    pages[1] = pages[1].replace("First Reprint", "Fourth Reprint")
    pages[2] = pages[2].replace("[1R]", "[4R]")
    pages[4] = pages[4].replace(
        "This act shall take effect immediately.",
        "This ac t shall ta ke e ffect immediately.",
    )
    with pytest.raises(ValueError):
        nj.separate_versions(pages)
    versions, _ = nj.separate_versions(
        pages, context_qualified_introductions={}, qualify_supported_years=True,
    )
    assert len(versions) == 3 and versions[0]["continuations"][0]["printed_label"] == " [4R]"
    raw = "\n".join(pages[p - 1] for p in versions[1]["page_ordinals"])
    span = versions[1]["literal_effective_clause_evidence"]
    assert raw[span["start"]:span["end"]] == span["text"]
    assert "ac t shall ta ke e ffect" in span["text"]


def test_unlabelled_page_requires_exact_bytes_and_two_printed_neighbors():
    original = _texts()
    bridge = "Literal original unlabelled policy page; no header or folio is inserted.\n"
    following = "A100 [1R]\n4\nFull final enacted continuation.\n"
    pages = original[:3] + [bridge, following] + original[3:]
    profile = {
        4: {
            "identifier": "A 100", "preceding_folio": 2, "following_folio": 4,
            "printed_reprint_label": "[1R]", "source_pdf_sha256": "1" * 64,
            "before_text_sha256": nj._sha(pages[2].encode()),
            "page_text_sha256": nj._sha(bridge.encode()),
            "after_text_sha256": nj._sha(following.encode()),
        },
    }
    with pytest.raises(ValueError, match="boundary"):
        nj.separate_versions(
            pages, context_qualified_introductions={}, qualify_supported_years=True,
        )
    versions, dispositions = nj.separate_versions(
        pages, context_qualified_introductions={}, qualify_supported_years=True,
        unlabelled_page_bridges=profile,
    )
    assert versions[0]["page_ordinals"] == [2, 3, 4, 5]
    witness = versions[0]["unlabelled_page_bridges"][0]
    assert witness["extracted_bill_header"] is witness["extracted_folio"] is None
    assert witness["no_header_folio_or_text_inserted"] is True
    assert witness["preceding_printed_witness"]["folio"] == 2
    assert witness["following_printed_witness"]["folio"] == 4
    assert len(dispositions) == len(pages)
    for index, altered in ((3, bridge + "changed"), (4, following.replace("\n4\n", "\n5\n"))):
        changed = list(pages)
        changed[index] = altered
        with pytest.raises(ValueError, match="pinned"):
            nj.separate_versions(
                changed, context_qualified_introductions={}, qualify_supported_years=True,
                unlabelled_page_bridges=profile,
            )


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


def test_library_views_enter_inference_without_a_fabricated_machine_prologue(packet):
    from state_politics.analysis.cycle_topics import input_text, make_input

    out, _, _, _ = packet
    rows, _, _, _ = nj.load_nj_library(out)
    for ordinal, row in enumerate(rows, 1):
        unit = make_input(row, "retained_text", "evidence/archive-NJ.jsonl", ordinal)
        assert row["archive_generated_prologue_preserved"] is False
        assert unit["source_text_span"] == [0, len(row["text"])]
        assert unit["archive_machine_prologue_excluded_from_inference"] is False
        assert unit["input_sha256"] == row["raw_text_sha256"]
        assert input_text(unit) == row["text"]
        assert unit["original_source_view"] == row


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
    "crop", "identity_span", "promote_flag", "mistyped_false", "context", "layout", "prologue",
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
        elif change == "prologue":
            rows[0]["archive_generated_prologue_preserved"] = True
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

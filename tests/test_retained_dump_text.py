"""Retained search-index recovery must preserve bodies without promoting evidence."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from state_politics.bills.openstates_dump import copy_blocks
from state_politics.bills.retained_dump_text import (
    SOURCE_COLUMNS,
    extract_retained_search_index,
    recover_retained_text,
)


def _references(root: Path, *, cross_bill=False):
    links = root / "links.parquet"
    versions = root / "versions.parquet"
    pq.write_table(pa.Table.from_pylist([{
        "id": "link", "media_type": "application/pdf", "url": "retained://body",
        "version_id": "version", "bill_id": "other" if cross_bill else "bill",
    }]), links)
    pq.write_table(pa.Table.from_pylist([{
        "id": "version", "note": "Introduced", "date": "",
        "bill_id": "bill", "extras": "{}", "classification": "{}",
    }]), versions)
    return links, versions


def _row(ordinal=1, **values):
    row = dict.fromkeys(SOURCE_COLUMNS)
    row.update(id="same", bill_id="bill", version_link_id="link", is_error="f")
    row.update(values)
    return {"source_row_ordinal": ordinal, "source_record": row}


def test_complete_strings_nulls_duplicates_and_error_flags_survive_without_certification(tmp_path):
    links, versions = _references(tmp_path)
    text = "  Exact § bill text\n\t\\N\\literal\r\n" + "é" * 12000
    rows = [
        _row(raw_text=text, all_titles="{Title,Other}", search_vector="'exact':1"),
        _row(3, raw_text=text, is_error="t"),
        _row(9, raw_text=None, version_link_id=None),
    ]
    out = tmp_path / "packet"
    report = recover_retained_text(rows, {"bill": "HI"}, links, versions, out)
    actual = pq.read_table(out / "searchablebill.parquet").to_pylist()
    assert actual == [
        {"source_row_ordinal": row["source_row_ordinal"], **row["source_record"]} for row in rows
    ]
    assert report["counts"]["nonempty_raw_text_rows"] == 2
    assert report["counts"]["nonempty_error_flagged_rows"] == 1
    assert report["repeated_source_id_rows"] == 2
    assert report["full_source_record_roundtrip_verified"]
    assert not any(report["approvals"].values())
    assert pq.read_table(out / "versions.parquet").to_pylist()[0]["date"] == ""


def test_dangling_and_cross_bill_links_are_retained_but_never_certified(tmp_path):
    links, versions = _references(tmp_path, cross_bill=True)
    rows = [_row(raw_text="actual text"), _row(2, raw_text="other", version_link_id="missing")]
    out = tmp_path / "packet"
    report = recover_retained_text(rows, {"bill": "AR"}, links, versions, out)
    assert report["relationship_counts"] == {
        "nonempty_text_cross_bill_version_link": 1, "nonempty_text_missing_version_link": 1,
    }
    assert pq.read_table(out / "searchablebill.parquet").num_rows == 2
    assert pq.read_table(out / "version_links.parquet").to_pylist()[0]["bill_id"] == "other"
    assert not any(report["approvals"].values())


def test_repeated_reference_ids_preserve_all_original_rows_instead_of_picking_a_version(tmp_path):
    links, versions = _references(tmp_path)
    original = pq.read_table(links).to_pylist()[0]
    repeated = {**original, "url": "retained://different", "media_type": "text/html"}
    pq.write_table(pa.Table.from_pylist([original, repeated]), links)
    out = tmp_path / "packet"
    report = recover_retained_text([_row(raw_text="body")], {"bill": "HI"}, links, versions, out)
    assert report["relationship_counts"] == {"nonempty_text_multiple_version_links": 1}
    assert pq.read_table(out / "version_links.parquet").to_pylist() == [
        {**row, "retained_table_row_ordinal": i} for i, row in enumerate([original, repeated], 1)
    ]
    assert not any(report["approvals"].values())


@pytest.mark.parametrize(
    "records,match",
    [
        ([_row(bill_id="outside")], "outside the bound calendar cohort"),
        ([_row(), _row()], "strictly increasing"),
        ([_row(raw_text=123)], "original strings or nulls"),
    ],
)
def test_scope_order_and_full_string_contract_fail_closed(tmp_path, records, match):
    links, versions = _references(tmp_path)
    with pytest.raises(ValueError, match=match):
        recover_retained_text(records, {"bill": "TX"}, links, versions, tmp_path / "packet")


def test_module_cli_streams_copy_fields_exact_ids_errors_and_original_ordinals(tmp_path):
    body = (
        "same\t'§':1\t{\"Title\"}\t  § exact\\n\\t\\\\N\\\\literal\\r\\n  \tt\tstamp\tbill\tlink\n"
    )
    copy_fixture = (
        f"COPY public.opencivicdata_searchablebill ({', '.join(SOURCE_COLUMNS)}) FROM stdin;\n"
        "outside\t'unused':1\tOther\tignore\tf\tstamp\tbill-more\tlink\n"
        + body
        + "missing\t\\N\t\\N\t\\N\t\\N\t\\N\tbill\t\\N\n"
        "empty\t\t{}\t\tf\t\tbill\t\n"
        "near\t\t{}\tuntouched\tf\t\tbill \t\n"
        + body + "\\.\n"
    )
    restore = tmp_path / "pg_restore"
    restore.write_text("#!/bin/sh\ncat <<'RETAINED_COPY_FIXTURE'\n" + copy_fixture
                       + "RETAINED_COPY_FIXTURE\n", encoding="utf-8")
    restore.chmod(0o700)
    dump = tmp_path / "synthetic.pgdump"
    dump.write_bytes(b"synthetic archive; only the local fixture pg_restore reads this")
    cohort = tmp_path / "cohort.parquet"
    pq.write_table(pa.table({"bill_id": ["bill", "bill", "unmatched"]}), cohort)
    inputs_before = (dump.read_bytes(), cohort.read_bytes())
    out = tmp_path / "extracted"
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-m", "state_politics.bills.retained_dump_text",
         "--dump", str(dump), "--candidate-cohort", str(cohort), "--out-dir", str(out)],
        env={**os.environ, "PG_RESTORE": str(restore)},
        capture_output=True, text=True, check=True, timeout=30,
    )
    report = json.loads(result.stdout)
    actual = [
        json.loads(line) for line in (out / "target_searchablebill_records.jsonl").read_text(
            encoding="utf-8",
        ).splitlines()
    ]
    decoded = list(copy_blocks(iter(copy_fixture.splitlines(keepends=True)), require_copy=True))
    assert actual == [
        {"source_row_ordinal": ordinal, "source_record": row}
        for ordinal, row in enumerate(decoded, 1) if row["bill_id"] == "bill"
    ]
    assert [row["source_row_ordinal"] for row in actual] == [2, 3, 4, 6]
    assert actual[0]["source_record"]["raw_text"] == "  § exact\n\t\\N\\literal\r\n  "
    assert actual[1]["source_record"]["raw_text"] is None
    assert actual[2]["source_record"]["raw_text"] == ""
    assert actual[0]["source_record"] == actual[3]["source_record"]
    assert report["counts"] == {
        "source_rows_scanned": 6, "retained_rows": 4, "nonempty_raw_text_rows": 2,
        "error_flagged_rows": 2,
    }
    assert report["candidate_rows"] == 3
    assert report["unique_candidate_bill_ids"] == 2
    assert report["unmatched_candidate_bill_ids"] == ["unmatched"]
    assert not any(report["approvals"].values())
    assert (dump.read_bytes(), cohort.read_bytes()) == inputs_before

    links, versions = _references(tmp_path)
    recovered = tmp_path / "recovered"
    recovery_report = recover_retained_text(actual, {"bill": "HI"}, links, versions, recovered)
    assert recovery_report["counts"]["rows"] == 4
    assert recovery_report["full_source_record_roundtrip_verified"]


@pytest.mark.parametrize("bill_ids", [[], [None]])
def test_dump_extraction_rejects_invalid_candidate_ids_before_streaming(tmp_path, bill_ids):
    dump, cohort = tmp_path / "source.pgdump", tmp_path / "cohort.parquet"
    dump.write_bytes(b"synthetic archive")
    pq.write_table(pa.table({"bill_id": bill_ids}), cohort)
    out = tmp_path / "new"
    with pytest.raises(ValueError, match="must not be empty|nonempty source strings"):
        extract_retained_search_index(dump, cohort, out)
    assert not out.exists()


def test_dump_extraction_never_reuses_or_modifies_existing_outputs(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    original = out / "target_searchablebill_records.jsonl"
    original.write_text("preserved exactly\n")
    with pytest.raises(FileExistsError):
        extract_retained_search_index(tmp_path / "absent", tmp_path / "absent.parquet", out)
    assert original.read_text() == "preserved exactly\n"

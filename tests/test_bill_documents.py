"""Source-reference planning must not lose versions or certify imported notes."""

import json

import pandas as pd
import pytest

from state_politics.bills.documents import build_document_inventory, freeze_document_inventory
from state_politics.provenance import sha256_file


def _sources():
    bills = pd.DataFrame(
        [
            {"bill_id": "policy", "state": "WA", "title": "Adopting permanent Senate rules."},
            {"bill_id": "gap", "state": "TX", "title": "Funding public education."},
            {"bill_id": "test", "state": "WA", "title": "Bill 4 for System Testing"},
        ]
    ).assign(identifier="SR 8601", session_identifier="2019-2020")
    versions = pd.DataFrame(
        [
            {"id": "plain", "bill_id": "policy", "note": "Substitute Resolution"},
            {"id": "engrossed", "bill_id": "policy", "note": "Engrossed Resolution"},
            {"id": "unlinked", "bill_id": "gap", "note": "Introduced"},
            {"id": "test-version", "bill_id": "test", "note": "Introduced"},
        ]
    ).assign(date="", extras="{}", classification="")
    links = pd.DataFrame(
        [
            {"id": "plain-link", "bill_id": "policy", "version_id": "plain"},
            {"id": "engrossed-link", "bill_id": "policy", "version_id": "engrossed"},
            {"id": "test-link", "bill_id": "test", "version_id": "test-version"},
        ]
    ).assign(media_type="text/html", url="https://example.org/bill.htm")
    return bills, versions, links


def test_all_version_notes_and_duplicate_urls_survive_without_certification():
    bills, versions, links = _sources()
    candidates, coverage, unlinked = build_document_inventory(bills, versions, links)
    assert candidates["link_id"].tolist() == links["id"].tolist()
    assert candidates["source_url"].tolist() == links["url"].tolist()
    assert candidates["version_note"].tolist() == [
        "Substitute Resolution",
        "Engrossed Resolution",
        "Introduced",
    ]
    assert candidates["collection_eligible"].tolist() == [True, True, False]
    assert not candidates["version_identity_certified"].any()
    assert not candidates["filing_time_text_certified"].any()
    assert not coverage["analytical_admission"].any()
    indexed = coverage.set_index("bill_id")
    assert indexed.at["policy", "n_version_links"] == 2
    assert indexed.at["policy", "n_later_note_links"] == 2
    assert indexed.at["gap", "reference_status"] == "no_retained_version_link"
    assert indexed.at["gap", "n_unlinked_versions"] == 1
    assert indexed.at["test", "reference_status"] == "excluded_source_test"
    assert unlinked["id"].tolist() == ["unlinked"]
    pd.testing.assert_frame_equal(coverage[bills.columns], bills)


def test_missing_version_metadata_is_explicit_not_dropped_or_inferred():
    bills, versions, links = _sources()
    links.loc[0, "version_id"] = "missing"
    candidates, coverage, unlinked = build_document_inventory(bills, versions, links)
    assert len(candidates) == 3
    assert candidates.iloc[0]["version_metadata_missing"]
    assert candidates.iloc[0]["version_note_hint"] == "unclassified_note"
    assert candidates.iloc[0]["collection_eligible"]
    assert coverage.set_index("bill_id").at["policy", "n_missing_version_metadata"] == 1
    assert set(unlinked["id"]) == {"plain", "unlinked"}


@pytest.mark.parametrize("defect", ["duplicate_link", "wrong_bill", "outside_bill", "wrong_schema"])
def test_conflicting_source_identity_fails_explicitly(defect):
    bills, versions, links = _sources()
    if defect == "duplicate_link":
        links.loc[1, "id"] = links.loc[0, "id"]
    elif defect == "wrong_bill":
        links.loc[0, "bill_id"] = "gap"
    elif defect == "outside_bill":
        versions.loc[0, "bill_id"] = "outside"
    else:
        versions = versions.drop(columns="date")
    with pytest.raises(ValueError):
        build_document_inventory(bills, versions, links)


@pytest.mark.parametrize(
    "url,status",
    [
        ("", "missing_url"),
        ("https://[bad", "malformed_url"),
        ("file:///tmp/bill", "unsupported_scheme"),
        ("https:///bill", "missing_host"),
        ("https://example.org:99999/bill", "malformed_url"),
        ("https://exa mple.org/bill", "invalid_host_whitespace"),
        ("https://example.org/bi\nll", "invalid_control_character"),
        (" https://example.org/bill", "surrounding_whitespace"),
    ],
)
def test_unusable_source_urls_remain_traceable(url, status):
    bills, versions, links = _sources()
    links.loc[0, "url"] = url
    candidates, _, _ = build_document_inventory(bills, versions, links)
    assert candidates.iloc[0]["source_url"] == url
    assert candidates.iloc[0]["url_status"] == status
    assert not candidates.iloc[0]["collection_eligible"]


def test_whitespace_encoding_is_explicit_and_never_changes_the_source_url():
    bills, versions, links = _sources()
    source = "https://example.org/2021-22 INT/HB1 INT.PDF?Version=House Judiciary"
    links.loc[0, "url"] = source
    candidates, coverage, _ = build_document_inventory(bills, versions, links)
    row = candidates.iloc[0]
    assert row["source_url"] == source
    assert row["request_url"] == (
        "https://example.org/2021-22%20INT/HB1%20INT.PDF?Version=House%20Judiciary"
    )
    assert row["url_normalization"] == "percent_encode_whitespace"
    assert row["collection_eligible"]
    assert coverage.set_index("bill_id").at["policy", "n_usable_url_links"] == 2
    assert not row["version_identity_certified"]


def test_empty_links_preserve_every_bill_and_unlinked_version():
    bills, versions, links = _sources()
    candidates, coverage, unlinked = build_document_inventory(bills, versions, links.iloc[:0])
    assert candidates.empty and len(coverage) == len(bills)
    assert coverage["n_version_links"].eq(0).all()
    assert len(unlinked) == len(versions)


def _write_extraction(tmp_path, *, url=None):
    bills, versions, links = _sources()
    if url is not None:
        links["url"] = url
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    metadata = {"status": "complete_extraction_not_source_certification", "artifacts": {}}
    for name, frame in [
        ("bills.parquet", bills),
        ("bill_versions.parquet", versions),
        ("bill_version_links.parquet", links),
    ]:
        frame.to_parquet(inputs / name, index=False)
        metadata["artifacts"][name] = {"rows": len(frame), "sha256": sha256_file(inputs / name)}
    manifest = inputs / "bill_extraction_manifest.json"
    manifest.write_text(json.dumps(metadata))
    expected = sha256_file(manifest)
    return inputs, expected


def test_freezing_checks_source_hashes_and_never_overwrites(tmp_path):
    inputs, expected = _write_extraction(tmp_path)
    out = tmp_path / "inventory"
    report = freeze_document_inventory(inputs, out, extraction_manifest_sha256=expected)
    assert report["n_source_context_bills"] == 3
    assert report["n_version_links"] == 3
    assert report["n_unlinked_versions"] == 1
    assert pd.read_parquet(out / "document_candidates.parquet").shape[0] == 3
    assert (out / "manifest.json").is_file()
    with pytest.raises(FileExistsError):
        freeze_document_inventory(inputs, out, extraction_manifest_sha256=expected)
    with pytest.raises(ValueError, match="manifest checksum"):
        freeze_document_inventory(
            inputs, tmp_path / "bad-manifest", extraction_manifest_sha256="0" * 64
        )
    (inputs / "bill_version_links.parquet").write_bytes(b"changed source")
    with pytest.raises(ValueError, match="extraction checksum"):
        freeze_document_inventory(inputs, tmp_path / "changed", extraction_manifest_sha256=expected)
    assert not (tmp_path / "changed").exists()


@pytest.mark.parametrize("https_fails", [False, True])
def test_collection_preserves_failures_encoded_urls_and_later_version_candidates(
    tmp_path,
    monkeypatch,
    https_fails,
):
    from types import SimpleNamespace

    from state_politics.bills.documents import collect_document_candidates
    from state_politics.platforms.recovery import verify_manifest

    inputs, extraction_sha = _write_extraction(
        tmp_path,
        url="http://example.org/2021 INT/bill.pdf",
    )
    inventory, out = tmp_path / "inventory", tmp_path / "captures"
    freeze_document_inventory(inputs, inventory, extraction_manifest_sha256=extraction_sha)
    inventory_sha = sha256_file(inventory / "manifest.json")
    monkeypatch.setattr("state_politics.provenance.url_is_fetchable", lambda url: None)
    requests = []

    def transport(url, **kwargs):
        assert " " not in url and "/2021%20INT/" in url
        requests.append(url)
        status = 404 if url.startswith("http:") or https_fails else 200
        return SimpleNamespace(
            status_code=status,
            content=b"retained native bytes",
            headers={"Content-Type": "application/pdf"},
            url=url,
        )

    report = collect_document_candidates(
        inventory,
        out,
        inventory_manifest_sha256=inventory_sha,
        link_ids={"plain-link", "engrossed-link", "test-link"},
        transport=transport,
        sleep=lambda seconds: None,
    )
    assert len(requests) == report["n_fetch_receipts"] == 4
    assert report["n_retained_links"] == (0 if https_fails else 2)
    assert report["n_failed_receipts"] == (4 if https_fails else 2)
    assert report["unresolved_link_ids"] == (
        ["engrossed-link", "plain-link"] if https_fails else []
    )
    assert report["skipped_links"] == [{"link_id": "test-link", "reason": "source_test_record"}]
    assert not report["filing_time_text_certified"]
    assert not report["analytical_admission"]
    with (out / "receipts.jsonl").open() as stream:
        receipts = [json.loads(line) for line in stream]
    assert {row["attempt_kind"] for row in receipts} == {"recorded_request", "https_alternative"}
    assert all(row["source_url"] == "http://example.org/2021 INT/bill.pdf" for row in receipts)
    assert len(list((out / "source").glob("*.bin"))) == (0 if https_fails else 2)
    verify_manifest(out, {"report.json", "selected_candidates.parquet", "receipts.jsonl"})
    with pytest.raises(FileExistsError):
        collect_document_candidates(
            inventory,
            out,
            inventory_manifest_sha256=inventory_sha,
            link_ids={"plain-link"},
        )
    with pytest.raises(ValueError, match="selected source link IDs"):
        collect_document_candidates(
            inventory,
            tmp_path / "unknown",
            inventory_manifest_sha256=inventory_sha,
            link_ids={"unknown-link"},
        )
    assert not (tmp_path / "unknown").exists()

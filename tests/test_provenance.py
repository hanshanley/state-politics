"""Tests for the provenance layer.

The point of these tests is the project's central rule: data must be traceable and never
invented. So they check that a failed fetch is *recorded* rather than silently dropped,
that hashes are real, and that the log round-trips without loss.
"""

from __future__ import annotations

import json

import pytest

from state_politics.provenance import (
    FetchRecord,
    ProvenanceLog,
    fetch,
    record_local_file,
    sha256_bytes,
    sha256_file,
    url_is_fetchable,
    utc_now_iso,
)


class StubResponse:
    def __init__(self, status_code: int, content: bytes = b"", content_type: str | None = None,
                 url: str = "https://example.org/x"):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type} if content_type else {}
        self.url = url


def test_sha256_bytes_matches_known_value():
    # SHA-256 of the empty string, a fixed published constant.
    assert sha256_bytes(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_sha256_file_matches_sha256_bytes(tmp_path):
    payload = b"state party platform text" * 1000
    path = tmp_path / "doc.txt"
    path.write_bytes(payload)
    assert sha256_file(path) == sha256_bytes(payload)


def test_utc_now_iso_is_zulu_second_precision():
    stamp = utc_now_iso()
    assert stamp.endswith("Z")
    assert "." not in stamp


def test_record_round_trips_through_log(tmp_path):
    log = ProvenanceLog(tmp_path / "provenance.jsonl")
    record = FetchRecord(
        url="https://example.org/platform.pdf",
        source_org="Example State Party",
        retrieved_at=utc_now_iso(),
        ok=True,
        http_status=200,
        content_sha256=sha256_bytes(b"abc"),
        content_bytes=3,
        content_type="application/pdf",
    )
    log.append(record)
    assert log.records() == [record]


def test_log_rejects_unknown_fields(tmp_path):
    path = tmp_path / "provenance.jsonl"
    path.write_text(json.dumps({"url": "u", "surprise": 1}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt record"):
        ProvenanceLog(path).records()


def test_fetch_success_records_hash_and_writes_file(tmp_path):
    body = b"2024 platform text"
    log = ProvenanceLog(tmp_path / "provenance.jsonl")
    dest = tmp_path / "out" / "platform.txt"

    content, record = fetch(
        "https://example.org/platform",
        source_org="Example State Party",
        log=log,
        dest=dest,
        transport=lambda url, *, timeout, headers: StubResponse(200, body, "text/html"),
    )

    assert content == body
    assert record.ok is True
    assert record.http_status == 200
    assert record.content_sha256 == sha256_bytes(body)
    assert record.content_bytes == len(body)
    assert record.content_type == "text/html"
    assert dest.read_bytes() == body
    assert record.stored_path == str(dest)
    assert log.successful_urls() == {"https://example.org/platform"}


def test_fetch_404_is_recorded_not_raised(tmp_path):
    """A missing platform is a finding, so it must be logged rather than thrown away."""
    log = ProvenanceLog(tmp_path / "provenance.jsonl")

    content, record = fetch(
        "https://example.org/missing",
        source_org="Example State Party",
        log=log,
        transport=lambda url, *, timeout, headers: StubResponse(404),
    )

    assert content is None
    assert record.ok is False
    assert record.http_status == 404
    assert record.content_sha256 is None
    assert log.records() == [record]
    assert log.successful_urls() == set()


def test_fetch_does_not_retry_404():
    calls = []

    def transport(url, *, timeout, headers):
        calls.append(url)
        return StubResponse(404)

    fetch("https://example.org/missing", source_org="org", transport=transport,
          max_attempts=3, sleep=lambda _: None)
    assert len(calls) == 1


def test_fetch_retries_transient_status_then_succeeds():
    statuses = [503, 503, 200]

    def transport(url, *, timeout, headers):
        return StubResponse(statuses.pop(0), b"ok")

    content, record = fetch("https://example.org/x", source_org="org", transport=transport,
                            max_attempts=3, sleep=lambda _: None)
    assert content == b"ok"
    assert record.attempts == 3
    assert record.ok is True


def test_fetch_records_transport_error_after_exhausting_attempts():
    def transport(url, *, timeout, headers):
        raise TimeoutError("connection timed out")

    content, record = fetch("https://example.org/x", source_org="org", transport=transport,
                            max_attempts=2, sleep=lambda _: None)
    assert content is None
    assert record.ok is False
    assert record.http_status is None
    assert record.attempts == 2
    assert "TimeoutError" in record.error


def test_record_local_file_hashes_out_of_band_download(tmp_path):
    """Large dumps fetched by curl must meet the same evidentiary standard."""
    payload = b"pgdump bytes"
    path = tmp_path / "2026-07-public.pgdump"
    path.write_bytes(payload)
    log = ProvenanceLog(tmp_path / "provenance.jsonl")

    record = record_local_file(
        path,
        url="https://data.openstates.org/postgres/monthly/2026-07-public.pgdump",
        source_org="Open States / Plural Policy",
        log=log,
    )

    assert record.content_sha256 == sha256_bytes(payload)
    assert record.content_bytes == len(payload)
    assert log.records() == [record]


def test_latest_for_returns_most_recent_attempt(tmp_path):
    log = ProvenanceLog(tmp_path / "provenance.jsonl")
    url = "https://example.org/x"
    for status in (503, 200):
        fetch(url, source_org="org", log=log,
              transport=lambda u, *, timeout, headers, s=status: StubResponse(s, b"b"),
              max_attempts=1, sleep=lambda _: None)
    latest = log.latest_for(url)
    assert latest is not None
    assert latest.http_status == 200
    assert log.latest_for("https://example.org/never") is None


def test_session_writes_are_append_only_and_flushed(tmp_path):
    """Holding the handle open must not weaken the append-only or crash-safety guarantee."""
    log = ProvenanceLog(tmp_path / "provenance.jsonl")
    log.append(FetchRecord(url="https://a", source_org="o", retrieved_at=utc_now_iso(), ok=True))
    with log.session():
        log.append(
            FetchRecord(url="https://b", source_org="o", retrieved_at=utc_now_iso(), ok=True)
        )
        # Readable from disk before the session closes.
        assert [r.url for r in log.records()] == ["https://a", "https://b"]
    log.append(FetchRecord(url="https://c", source_org="o", retrieved_at=utc_now_iso(), ok=True))
    assert [r.url for r in log.records()] == ["https://a", "https://b", "https://c"]


def test_nested_sessions_do_not_close_early(tmp_path):
    log = ProvenanceLog(tmp_path / "provenance.jsonl")
    with log.session():
        with log.session():
            log.append(
                FetchRecord(url="https://a", source_org="o", retrieved_at=utc_now_iso(), ok=True)
            )
        log.append(
            FetchRecord(url="https://b", source_org="o", retrieved_at=utc_now_iso(), ok=True)
        )
    assert len(log.records()) == 2


def test_extend_writes_every_record(tmp_path):
    log = ProvenanceLog(tmp_path / "provenance.jsonl")
    written = log.extend(
        FetchRecord(url=f"https://x/{i}", source_org="o", retrieved_at=utc_now_iso(), ok=True)
        for i in range(50)
    )
    assert written == 50
    assert len(log.records()) == 50


def test_index_gives_the_latest_record_per_url(tmp_path):
    log = ProvenanceLog(tmp_path / "provenance.jsonl")
    log.append(FetchRecord(url="https://a", source_org="o", retrieved_at=utc_now_iso(),
                           ok=False, http_status=503))
    log.append(FetchRecord(url="https://a", source_org="o", retrieved_at=utc_now_iso(),
                           ok=True, http_status=200))
    index = log.index()
    assert set(index) == {"https://a"}
    assert index["https://a"].http_status == 200


def test_fetch_rejects_private_and_non_http_targets(tmp_path):
    """A lapsed party domain must not be able to point the crawler at localhost."""
    log = ProvenanceLog(tmp_path / "provenance.jsonl")
    for url in ("http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data/",
                "file:///etc/passwd", "http://10.0.0.5/"):
        content, record = fetch(url, source_org="o", log=log,
                                transport=lambda *a, **k: StubResponse(200, b"secret"))
        assert content is None
        assert record.ok is False
        assert "refusing" in record.error


def test_fetch_caps_an_oversized_body():
    content, record = fetch(
        "https://example.org/huge", source_org="o", max_bytes=10,
        transport=lambda url, *, timeout, headers: StubResponse(200, b"x" * 100),
    )
    assert content is None
    assert record.ok is False
    assert "max_bytes" in record.error


@pytest.mark.parametrize("url", [
    "http://2130706433/",              # decimal-encoded 127.0.0.1
    "http://0177.0.0.1/",              # octal-encoded
    "http://127.1/",                   # short form
    "http://[::ffff:127.0.0.1]/",      # IPv4-mapped IPv6
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://localhost:5432/",
    "http://[fd00::1]/",               # unique local IPv6
    "http://10.0.0.5/",
])
def test_ssrf_guard_rejects_encoded_private_addresses(url):
    """A literal-string blocklist misses every one of these.

    This crawler deliberately fetches lapsed party domains, several already documented as
    repointed to unrelated sites, so a hostile or hijacked host reaching loopback or the cloud
    metadata endpoint is a live risk rather than a theoretical one.
    """
    assert url_is_fetchable(url) is not None, url


@pytest.mark.parametrize("url", [
    "https://web.archive.org/cdx/search/cdx",
    "https://texasgop.org/platform",
    "https://data.openstates.org/postgres/monthly/x.pgdump",
])
def test_ssrf_guard_allows_the_hosts_the_project_actually_uses(url):
    assert url_is_fetchable(url) is None, url


def test_ssrf_guard_allows_a_domain_that_no_longer_resolves():
    """A dead domain is a research finding, not a security event.

    The request will fail on its own and be recorded with ok=False; rejecting it here would
    report the wrong reason for the gap.
    """
    assert url_is_fetchable("https://this-domain-does-not-exist-xyzzy-42.example/") is None

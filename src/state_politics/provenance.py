"""Provenance-tracked retrieval.

Every remote artifact this project uses is fetched through :func:`fetch`, which writes an
append-only JSONL record capturing *where the bytes came from and when*: the requested URL,
the final URL after redirects, the HTTP status, the SHA-256 of the body, the byte count, the
content type, the UTC retrieval timestamp, and the organization that collected the data.

This is what makes the project's "no fabricated or interpolated data" rule checkable rather
than aspirational: any downstream table can be traced back to a logged HTTP response, and an
observation with no such record is simply absent rather than guessed at.

Design notes
------------
* :func:`fetch` **never raises on an HTTP error status**. A 404 is a legitimate research
  finding ("this state party published no platform"), so it is recorded with ``ok=False``
  and returned to the caller, not thrown away as an exception.
* Network transport is injected, so the retry/record logic is testable without a network.
* Retries cover transport errors plus 429/5xx, which are transient. A 404 is not retried.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

__all__ = [
    "USER_AGENT",
    "FetchRecord",
    "ProvenanceLog",
    "fetch",
    "record_local_file",
    "sha256_bytes",
    "sha256_file",
    "utc_now_iso",
]

#: Identifying UA. Sites are entitled to know who is crawling them and why.
USER_AGENT = (
    "state-politics-research/0.1 (+https://github.com/hanshanley/state-politics; "
    "academic research on state party priorities)"
)

#: HTTP statuses worth retrying: rate limiting and server-side faults.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


def utc_now_iso() -> str:
    """Current UTC time as a second-precision ISO-8601 string ending in ``Z``."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str, *, chunk_size: int = 1 << 20) -> str:
    """Hex SHA-256 of a file, read in chunks so multi-gigabyte dumps stay streamable."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class FetchRecord:
    """An immutable account of one retrieval attempt.

    Attributes
    ----------
    url:
        The URL as requested.
    source_org:
        The organization that *collected* the data, not merely the host serving it
        (e.g. ``"Internet Archive"`` for a Wayback capture, but the state party
        committee is recorded separately as the document's publisher).
    http_status:
        HTTP status of the final response, or ``None`` if no response was obtained.
    ok:
        True only for a 2xx response whose body was read successfully.
    """

    url: str
    source_org: str
    retrieved_at: str
    ok: bool
    http_status: int | None = None
    content_sha256: str | None = None
    content_bytes: int | None = None
    content_type: str | None = None
    final_url: str | None = None
    stored_path: str | None = None
    attempts: int = 1
    error: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FetchRecord:
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(payload) - known
        if unknown:
            raise ValueError(f"unknown FetchRecord field(s): {sorted(unknown)}")
        return cls(**payload)


class ProvenanceLog:
    """Append-only JSONL log of :class:`FetchRecord` entries.

    Append-only is deliberate: rewriting history would let a later run quietly erase
    evidence that an earlier fetch failed, which is exactly the failure mode the log
    exists to prevent.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, record: FetchRecord) -> FetchRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(record.to_json() + "\n")
        return record

    def __iter__(self) -> Iterator[FetchRecord]:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield FetchRecord.from_dict(json.loads(line))
                except (json.JSONDecodeError, ValueError) as exc:
                    raise ValueError(f"{self.path}:{line_number}: corrupt record: {exc}") from exc

    def records(self) -> list[FetchRecord]:
        return list(self)

    def latest_for(self, url: str) -> FetchRecord | None:
        """Most recent record for ``url``, or ``None`` if never attempted."""
        found = None
        for record in self:
            if record.url == url:
                found = record
        return found

    def successful_urls(self) -> set[str]:
        """URLs with at least one successful retrieval, for resumable crawls."""
        return {record.url for record in self if record.ok}


class Response(Protocol):
    """The subset of ``requests.Response`` this module relies on."""

    status_code: int
    content: bytes
    headers: Any
    url: str


class Transport(Protocol):
    """A callable that performs one HTTP GET."""

    def __call__(self, url: str, *, timeout: float, headers: dict[str, str]) -> Response: ...


def _default_transport(url: str, *, timeout: float, headers: dict[str, str]) -> Response:
    import requests  # imported lazily so the pure logic stays importable without requests

    return requests.get(url, timeout=timeout, headers=headers, allow_redirects=True)


def fetch(
    url: str,
    *,
    source_org: str,
    log: ProvenanceLog | None = None,
    transport: Transport | None = None,
    dest: Path | str | None = None,
    timeout: float = 60.0,
    max_attempts: int = 3,
    backoff: float = 2.0,
    headers: dict[str, str] | None = None,
    note: str | None = None,
    sleep: Any = time.sleep,
) -> tuple[bytes | None, FetchRecord]:
    """GET ``url``, recording provenance; return ``(body_or_None, record)``.

    Returns rather than raises on HTTP errors, because a missing document is a result
    this project needs to record, not an exception to swallow. Callers decide whether a
    non-OK record is fatal.

    Parameters
    ----------
    source_org:
        Organization credited as the collector of the data.
    dest:
        If given and the fetch succeeds, the body is written here and the path is
        recorded on the returned record.
    max_attempts:
        Total attempts, including the first. Only transport errors and
        :data:`RETRYABLE_STATUSES` are retried.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    transport = transport or _default_transport
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}

    record: FetchRecord | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = transport(url, timeout=timeout, headers=request_headers)
        except Exception as exc:  # noqa: BLE001 - any transport failure is recorded, not raised
            record = FetchRecord(
                url=url,
                source_org=source_org,
                retrieved_at=utc_now_iso(),
                ok=False,
                attempts=attempt,
                error=f"{type(exc).__name__}: {exc}",
                note=note,
            )
            if attempt < max_attempts:
                sleep(backoff * attempt)
                continue
            break

        status = int(response.status_code)
        body = response.content if 200 <= status < 300 else b""
        ok = 200 <= status < 300
        record = FetchRecord(
            url=url,
            source_org=source_org,
            retrieved_at=utc_now_iso(),
            ok=ok,
            http_status=status,
            content_sha256=sha256_bytes(body) if ok else None,
            content_bytes=len(body) if ok else None,
            content_type=_header(response, "Content-Type"),
            final_url=getattr(response, "url", None) or url,
            attempts=attempt,
            note=note,
        )
        if ok or status not in RETRYABLE_STATUSES or attempt == max_attempts:
            break
        sleep(backoff * attempt)

    assert record is not None  # loop always assigns on every path

    if record.ok and dest is not None:
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(body)
        record = replace(record, stored_path=str(dest_path))

    if log is not None:
        log.append(record)
    return (body if record.ok else None), record


def _header(response: Response, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        return headers.get(name)
    except AttributeError:
        return None


def record_local_file(
    path: Path | str,
    *,
    url: str,
    source_org: str,
    log: ProvenanceLog | None = None,
    note: str | None = None,
) -> FetchRecord:
    """Record provenance for a file already on disk (e.g. a multi-GB dump fetched by curl).

    Hashes the file so an out-of-band download is held to the same evidentiary standard as
    one made through :func:`fetch`.
    """
    path = Path(path)
    record = FetchRecord(
        url=url,
        source_org=source_org,
        retrieved_at=utc_now_iso(),
        ok=True,
        http_status=None,
        content_sha256=sha256_file(path),
        content_bytes=path.stat().st_size,
        content_type=None,
        final_url=url,
        stored_path=str(path),
        note=note or "recorded from local file",
    )
    if log is not None:
        log.append(record)
    return record

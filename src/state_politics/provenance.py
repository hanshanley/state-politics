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
import ipaddress
import json
import re
import socket
import time
import urllib.parse
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

__all__ = [
    "DEFAULT_MAX_BYTES",
    "USER_AGENT",
    "FetchRecord",
    "ProvenanceLog",
    "download_to_file",
    "fetch",
    "record_local_file",
    "sha256_bytes",
    "sha256_file",
    "url_is_fetchable",
    "utc_now_iso",
]

#: Identifying UA. Sites are entitled to know who is crawling them and why.
USER_AGENT = (
    "state-politics-research/0.1 (+https://github.com/hanshanley/state-politics; "
    "academic research on state party priorities)"
)

#: HTTP statuses worth retrying: rate limiting and server-side faults.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

#: Default ceiling on an in-memory response body. Web pages are small; anything far larger is
#: either a mistake or a hostile host slow-dripping bytes to exhaust memory (``timeout`` is a
#: per-read timeout, not a total one). Large files must go through :func:`download_to_file`.
DEFAULT_MAX_BYTES = 64 * 1024 * 1024

#: Hosts that must never be fetched. A lapsed party domain can point its DNS at loopback or
#: cloud metadata, turning the crawler into an SSRF gadget.
_BLOCKED_HOST_RE = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+"
    r"|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|169\.254\.\d+\.\d+|\[?::1\]?)$",
    re.I,
)


#: Redirect hops followed before giving up. Each hop is re-validated against the SSRF
#: guard, so this only bounds work, not safety.
MAX_REDIRECTS = 5


def _host_of(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""


def url_is_fetchable(url: str) -> str | None:
    """Return a rejection reason for ``url``, or ``None`` if it is safe to fetch."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return f"refusing non-http(s) scheme {parts.scheme!r}"
    host = parts.hostname or ""
    if not host:
        return "refusing URL with no host"
    if _BLOCKED_HOST_RE.match(host):
        return f"refusing private/loopback host {host!r}"
    return _reject_private_address(host)


def _reject_private_address(host: str) -> str | None:
    """Reject a host that *resolves* to a private, loopback or link-local address.

    Matching the hostname as a string is not enough. The literal blocklist above passes
    ``2130706433``, ``0177.0.0.1``, ``127.1`` and ``[::ffff:127.0.0.1]`` -- all of which reach
    loopback -- and it cannot see a DNS name that simply points there. That matters here
    because this crawler deliberately fetches lapsed party domains, several of which are
    already documented as repointed to unrelated sites, and the cloud metadata endpoint at
    169.254.169.254 is one redirect away.

    Resolution failures are *not* treated as rejections: a domain that no longer resolves is a
    normal research finding, and the request will fail on its own with that recorded.
    """
    try:
        parsed = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        parsed = None
    if parsed is not None:
        return _address_rejection(parsed, host)

    # inet_aton accepts the legacy shorthands that getaddrinfo rejects but every HTTP client
    # still honours: octal ("0177.0.0.1"), and dotted forms with fewer than four parts.
    try:
        packed = socket.inet_aton(host)
    except OSError:
        pass
    else:
        reason = _address_rejection(ipaddress.ip_address(packed), host)
        if reason:
            return reason

    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return None
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        reason = _address_rejection(address, host)
        if reason:
            return reason
    return None


def _address_rejection(address, host: str) -> str | None:
    if (address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_multicast or address.is_unspecified):
        return f"refusing private/loopback host {host!r} (resolves to {address})"
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        return _address_rejection(mapped, host)
    return None


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

    Append-only is deliberate: rewriting history would let a later run quietly erase evidence
    that an earlier fetch failed, which is exactly the failure mode the log exists to prevent.

    :meth:`append` reopens the file per record, which costs ~11 ms on this machine. That is
    irrelevant for a handful of downloads and ruinous for a crawl of hundreds of thousands of
    URLs, so :meth:`session` holds one handle open for the duration of a crawl while keeping
    the same append-only, flush-per-record guarantee.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._handle = None

    def append(self, record: FetchRecord) -> FetchRecord:
        if self._handle is not None:
            self._handle.write(record.to_json() + "\n")
            self._handle.flush()
            return record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(record.to_json() + "\n")
        return record

    def extend(self, records: Iterable[FetchRecord]) -> int:
        """Append many records with a single open/close."""
        with self.session():
            count = 0
            for record in records:
                self.append(record)
                count += 1
        return count

    @contextmanager
    def session(self):
        """Hold the log open for the duration of a crawl.

        Records are still flushed individually, so an interrupted crawl keeps everything it
        had already written.
        """
        if self._handle is not None:  # already inside a session; do not reopen or close
            yield self
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Not a `with` block: the handle deliberately outlives this statement and is closed
        # in the finally clause, which is the whole point of holding it open for a crawl.
        self._handle = open(self.path, "a", encoding="utf-8")  # noqa: SIM115
        try:
            yield self
        finally:
            self._handle.close()
            self._handle = None

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
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    raise ValueError(f"{self.path}:{line_number}: corrupt record: {exc}") from exc

    def records(self) -> list[FetchRecord]:
        return list(self)

    def index(self) -> dict[str, FetchRecord]:
        """Single-pass ``{url: latest record}`` index, for resumable crawls.

        :meth:`latest_for` re-parses the whole log per call, which is fine for a one-off
        lookup but quadratic when used inside a loop. Callers resuming a crawl should build
        this index once and query it in memory.
        """
        return {record.url: record for record in self}

    def latest_for(self, url: str) -> FetchRecord | None:
        """Most recent record for ``url``, or ``None`` if never attempted.

        Scans the whole log. Use :meth:`index` when checking many URLs.
        """
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


def _read_capped(response, max_bytes: int | None) -> bytes:
    """Read a response body, stopping one byte past ``max_bytes``.

    Reading one byte extra is deliberate: it lets the caller still detect that the limit was
    exceeded, rather than silently truncating a document to exactly the cap.
    """
    if max_bytes is None or not hasattr(response, "iter_content"):
        return response.content
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=1 << 16):
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            break
    return b"".join(chunks)


def _default_transport(url: str, *, timeout: float, headers: dict[str, str]) -> Response:
    import requests  # imported lazily so the pure logic stays importable without requests

    # Redirects are followed manually so every hop is checked. Letting requests follow them
    # means only the *first* URL is validated, and any third-party site -- or any page served
    # through the Wayback Machine -- can then 302 the crawler to the cloud metadata endpoint
    # or to a database port on localhost, with the body recorded into the corpus.
    for _ in range(MAX_REDIRECTS):
        response = requests.get(url, timeout=timeout, headers=headers, allow_redirects=False,
                                stream=True)
        if response.status_code not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get("location")
        response.close()
        if not location:
            return response
        url = urllib.parse.urljoin(url, location)
        reason = url_is_fetchable(url)
        if reason:
            raise PermissionError(f"redirect blocked: {reason}")
    raise RuntimeError(f"too many redirects (> {MAX_REDIRECTS})")


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
    max_bytes: int | None = DEFAULT_MAX_BYTES,
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
    max_bytes:
        Ceiling on the in-memory body. Pass ``None`` to disable, but prefer
        :func:`download_to_file` for anything large — this function holds the whole body in
        RAM and would need a multi-gigabyte dump resident twice.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    rejection = url_is_fetchable(url)
    if rejection is not None:
        record = FetchRecord(
            url=url,
            source_org=source_org,
            retrieved_at=utc_now_iso(),
            ok=False,
            attempts=0,
            error=rejection,
            note=note,
        )
        if log is not None:
            log.append(record)
        return None, record

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
        ok = 200 <= status < 300
        # Read with a hard ceiling rather than touching ``.content``, which buffers the whole
        # body first: a hostile or misconfigured host serving a multi-gigabyte response would
        # otherwise exhaust memory before the size check below ever ran.
        body = _read_capped(response, max_bytes) if ok else b""
        oversize = ok and max_bytes is not None and len(body) > max_bytes
        if oversize:
            ok, body = False, b""
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
            error=(f"response exceeded max_bytes={max_bytes}" if oversize else None),
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


def download_to_file(
    url: str,
    dest: Path | str,
    *,
    source_org: str,
    log: ProvenanceLog | None = None,
    timeout: float = 120.0,
    chunk_size: int = 1 << 20,
    max_bytes: int | None = None,
    note: str | None = None,
    expected_sha256: str | None = None,
) -> FetchRecord:
    """Stream ``url`` to ``dest``, hashing incrementally; never buffers the body in RAM.

    :func:`fetch` materializes the whole response, which cannot work for the multi-gigabyte
    database dumps this project consumes on a 16 GB machine. This streams to disk while
    updating the SHA-256 as it goes, so the "hash exactly the bytes stored" property is
    preserved without the buffer.

    The file is written to a ``.part`` sibling and only moved into place once complete, so an
    interrupted download can never masquerade as a finished one.
    """
    import requests

    rejection = url_is_fetchable(url)
    if rejection is not None:
        record = FetchRecord(url=url, source_org=source_org, retrieved_at=utc_now_iso(),
                             ok=False, attempts=0, error=rejection, note=note)
        if log is not None:
            log.append(record)
        return record

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    written = 0
    status: int | None = None
    content_type: str | None = None
    final_url: str | None = None
    error: str | None = None

    try:
        with requests.get(
            url, timeout=timeout, headers={"User-Agent": USER_AGENT}, stream=True,
            allow_redirects=True,
        ) as response:
            status = int(response.status_code)
            content_type = response.headers.get("Content-Type")
            final_url = response.url
            if 200 <= status < 300:
                declared = response.headers.get("Content-Length")
                if max_bytes is not None and declared and int(declared) > max_bytes:
                    error = f"Content-Length {declared} exceeds max_bytes={max_bytes}"
                else:
                    with open(partial, "wb") as handle:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if not chunk:
                                continue
                            written += len(chunk)
                            if max_bytes is not None and written > max_bytes:
                                error = f"stream exceeded max_bytes={max_bytes}"
                                break
                            digest.update(chunk)
                            handle.write(chunk)
    except Exception as exc:  # noqa: BLE001 - recorded, not raised; see module docstring
        error = f"{type(exc).__name__}: {exc}"

    ok = error is None and status is not None and 200 <= status < 300
    actual = digest.hexdigest() if ok else None
    if ok and expected_sha256 and actual != expected_sha256:
        ok = False
        error = f"sha256 mismatch: expected {expected_sha256}, got {actual}"

    if ok:
        partial.replace(dest)
    else:
        partial.unlink(missing_ok=True)

    record = FetchRecord(
        url=url,
        source_org=source_org,
        retrieved_at=utc_now_iso(),
        ok=ok,
        http_status=status,
        content_sha256=actual if ok else None,
        content_bytes=written if ok else None,
        content_type=content_type,
        final_url=final_url or url,
        stored_path=str(dest) if ok else None,
        error=error,
        note=note,
    )
    if log is not None:
        log.append(record)
    return record


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

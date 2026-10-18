"""Extract state bills and sponsorships from the Open States public PostgreSQL dump.

Why this route
--------------
Open States offers three ways to get bill data and only this one is both complete and free:

* the per-session CSV/JSON archives are **login-gated** -- every path under
  ``data.openstates.org/csv/`` and ``/json/`` returns HTTP 403;
* the API v3 needs an API key;
* the monthly public PostgreSQL dump is open, needs no credentials, and covers all 50 states.

The dump is a **PostgreSQL custom-format archive** (``PGDMP``), not plain SQL, so it cannot
simply be read as text. It does not, however, need a running database: ``pg_restore`` can emit
a chosen table's rows to stdout, which this module streams and parses. That matters because the
archive is 10.7 GB and restoring it into a real database would need far more disk than the
extraction itself.

Scope
-----
State legislatures only. The dump also contains the U.S. Congress and the territories; Congress
is explicitly out of scope for this project, and letting the territories through would quietly
widen the population being described.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

from ..provenance import FetchRecord, ProvenanceLog, download_to_file, sha256_file

__all__ = [
    "DUMP_URL",
    "SOURCE_ORG",
    "copy_blocks",
    "download_dump",
    "find_pg_restore",
    "list_tables",
    "stream_table",
]

DUMP_URL = "https://data.openstates.org/postgres/monthly/{month}-public.pgdump"

SOURCE_ORG = "Open States / Plural Policy (public PostgreSQL dump)"

#: Homebrew keeps libpq's binaries out of the default PATH because they clash with a full
#: PostgreSQL install, so look there explicitly before giving up.
_EXTRA_BIN_DIRS = (
    "/opt/homebrew/opt/libpq/bin",
    "/usr/local/opt/libpq/bin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
)

#: Postal codes of the 50 states, as they appear in Open States jurisdiction ids
#: (``ocd-jurisdiction/country:us/state:tx/government``).
STATE_CODES = frozenset({
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
})

_JURISDICTION_RE = re.compile(r"state:([a-z]{2})\b")


def find_pg_restore() -> str:
    """Locate ``pg_restore``, or raise with an actionable message."""
    configured = os.environ.get("PG_RESTORE")
    if configured:
        found = shutil.which(configured)
        if not found:
            raise RuntimeError(f"PG_RESTORE is not an executable: {configured}")
        return found
    found = shutil.which("pg_restore")
    if found:
        return found
    for directory in _EXTRA_BIN_DIRS:
        candidate = Path(directory) / "pg_restore"
        if candidate.exists():
            return str(candidate)
    raise RuntimeError(
        "pg_restore not found. Install the PostgreSQL client tools, e.g. `brew install libpq` "
        "or set PG_RESTORE to a verified local executable. "
        "(Homebrew keeps them out of PATH; this module also looks in "
        f"{_EXTRA_BIN_DIRS[0]})."
    )


def download_dump(dump_path: Path | str, month: str, *, log: ProvenanceLog) -> FetchRecord:
    """Reuse only a source-bound, checksum-verified snapshot; never overwrite unknown data."""
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) is None:
        raise ValueError("dump month must be YYYY-MM")
    find_pg_restore()
    dump_path = Path(dump_path)
    url = DUMP_URL.format(month=month)
    if dump_path.exists():
        retained = [
            record for record in log
            if record.ok and record.url == url and record.stored_path
            and Path(record.stored_path).resolve() == dump_path.resolve()
        ]
        if (
            not dump_path.is_file() or not retained
            or sha256_file(dump_path) != retained[-1].content_sha256
        ):
            raise ValueError(
                f"{dump_path}: existing dump lacks matching source/checksum provenance; "
                "preserve it and select another --dump path"
            )
        return retained[-1]
    record = download_to_file(
        url, dump_path, source_org=SOURCE_ORG, log=log, timeout=300.0,
    )
    if not record.ok:
        raise RuntimeError(f"dump download failed: {record.error}")
    return record


def list_tables(dump_path: Path | str) -> list[str]:
    """Table names present in the archive's table of contents."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [find_pg_restore(), "--list", str(dump_path)],
        capture_output=True, text=True, check=True,
    )
    tables = []
    for line in result.stdout.splitlines():
        match = re.search(r"TABLE DATA \S+ (\S+) ", line)
        if match:
            tables.append(match.group(1))
    return sorted(set(tables))


def copy_blocks(
    lines: Iterator[str], *, require_copy: bool = False,
) -> Iterator[dict[str, str | None]]:
    """Parse ``COPY ... FROM stdin;`` blocks into dicts.

    ``pg_restore --data-only`` emits PostgreSQL's text COPY format: a header naming the
    columns, tab-separated rows, then a ``\\.`` terminator. Backslash escapes are decoded and
    ``\\N`` becomes ``None`` -- treating it as the literal string "\\N" would silently turn
    every missing value into data.
    """
    columns: list[str] | None = None
    found = False
    for number, line in enumerate(lines, 1):
        line = line.rstrip("\n")
        if columns is None:
            match = re.match(r"COPY [^(]+\(([^)]*)\) FROM stdin;", line)
            if match:
                found = True
                columns = [c.strip().strip('"') for c in match.group(1).split(",")]
            continue
        if line == "\\.":
            columns = None
            continue
        values = line.split("\t")
        if len(values) != len(columns):
            raise ValueError(
                f"malformed COPY row at line {number}: expected {len(columns)} columns, "
                f"found {len(values)}"
            )
        yield {
            column: None if value == "\\N" else _unescape(value)
            for column, value in zip(columns, values, strict=True)
        }
    if columns is not None:
        raise ValueError("unterminated COPY block")
    if require_copy and not found:
        raise ValueError("pg_restore emitted no COPY block for the requested table")


_ESCAPES = {
    b"b": b"\b", b"f": b"\f", b"n": b"\n", b"r": b"\r",
    b"t": b"\t", b"v": b"\v", b"\\": b"\\",
}
_COPY_ESCAPE = re.compile(rb"\\([0-7]{1,3}|x[0-9a-fA-F]{1,2}|.)", re.DOTALL)


def _unescape(value: str) -> str:
    if "\\" not in value:
        return value
    def decode(match):
        escaped = match.group(1)
        if escaped[:1] in b"01234567":
            return bytes([int(escaped, 8)])
        if escaped.startswith(b"x") and len(escaped) > 1:
            return bytes([int(escaped[1:], 16)])
        return _ESCAPES.get(escaped, escaped)

    return _COPY_ESCAPE.sub(decode, value.encode("utf-8")).decode("utf-8")


def stream_table(dump_path: Path | str, table: str) -> Iterator[dict[str, str | None]]:
    """Yield every row of one table, without restoring the archive into a database."""
    # `-f -` is required: pg_restore 18 refuses to run without an explicit destination, even
    # when that destination is stdout.
    command = [find_pg_restore(), "--data-only", "--no-owner", "--table", table,
               "-f", "-", str(dump_path)]
    env = {**os.environ, "PATH": os.pathsep.join((*_EXTRA_BIN_DIRS, os.environ.get("PATH", "")))}
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        bufsize=1 << 20, env=env,
    )
    exhausted = False
    try:
        yield from copy_blocks(process.stdout, require_copy=True)
        exhausted = True
    finally:
        if process.stdout:
            process.stdout.close()
        if not exhausted:
            # The consumer abandoned the generator; terminate rather than block, and do not
            # read the resulting non-zero status as a failure of the extraction.
            process.terminate()
            process.wait()
            if process.stderr:
                process.stderr.close()
        else:
            stderr = process.stderr.read() if process.stderr else ""
            if process.stderr:
                process.stderr.close()
            process.wait()
            if process.returncode:
                # Without this, a corrupt or unreadable archive yields zero rows and the
                # pipeline writes empty tables while exiting 0 -- an empty corpus reported as
                # a successful run.
                raise RuntimeError(
                    f"pg_restore failed for table {table!r} (exit {process.returncode}): "
                    f"{stderr.strip()[:400]}"
                )


def state_of(jurisdiction_id: str | None) -> str | None:
    """Postal code for a jurisdiction id, or ``None`` if it is not one of the 50 states.

    Congress (``ocd-jurisdiction/country:us/government``) and the territories both fail this
    test, which is the point: they are in the dump and must not leak into a table described as
    covering the states.
    """
    if not jurisdiction_id:
        return None
    match = _JURISDICTION_RE.search(jurisdiction_id)
    if not match:
        return None
    code = match.group(1)
    return code.upper() if code in STATE_CODES else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dump", required=True)
    parser.add_argument("--download-month", help="fetch/reuse an explicit YYYY-MM snapshot")
    parser.add_argument("--provenance", type=Path, default=Path("data/provenance.jsonl"))
    parser.add_argument("--list", action="store_true", help="print the archive's tables")
    args = parser.parse_args(argv)

    dump = Path(args.dump)
    if args.download_month:
        record = download_dump(dump, args.download_month, log=ProvenanceLog(args.provenance))
        print(record.to_json())
        if not args.list:
            return 0
    if not dump.exists():
        parser.error(f"{dump} not found")
    if args.list:
        for table in list_tables(dump):
            print(table)
        return 0
    parser.error("nothing to do; pass --list, --download-month or use bills.ingest")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

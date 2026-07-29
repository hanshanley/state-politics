"""Ingest the historical state party platform corpus (1846-2017) from Harvard Dataverse.

Source
------
Hopkins, Daniel J.; Coffey, Daniel J.; Galvin, Daniel J.; Gamm, Gerald; Henderson, John;
Paddock, Joel W.; Schickler, Eric (2022). *Select American State Party Platforms,
1846-2017* (V3.0, 2025-04-23) [Data set]. Harvard Dataverse.
https://doi.org/10.7910/DVN/KNOSHL. CC0 1.0.

Two things about this dataset are easy to get wrong, so they are handled explicitly here.

**The two archives are not additive.** The dataset ships ``05 for public.zip`` (2,063
documents) and ``platform-update-04212025.zip`` (2,091 documents). The second *supersedes*
the first; the bundled changelog lists 49 additions and 21 deletions, and those reconcile
exactly against the two archives. Unioning them inflates the corpus to a spurious 4,154
"documents" -- resurrecting files the authors deliberately deleted and double-counting the
rest. :func:`load_corpus` reads the update archive alone, and :func:`reconcile` checks that
claim against the changelog rather than trusting it.

**Files must be fetched by numeric id.** The ``:persistentId`` access pattern returns HTTP
404 for these files; ``/api/access/datafile/{id}`` works.

Filename grammar
----------------
``STATE-YEAR-PARTY[-FLAG]*.ext`` -- e.g. ``TX-2016-R-B-GG.txt``, ``OH-1966-D.txt``,
``SD-1920-Non Partisan League-B.txt``. The party field may contain spaces but never a
hyphen, so every hyphen-separated token after the party is a flag (a coder or source
marker). Verified against all 2,091 filenames in the authoritative archive.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..provenance import ProvenanceLog, download_to_file, record_local_file, sha256_bytes

__all__ = [
    "DATASET_DOI",
    "DATASET_FILES",
    "SOURCE_ORG",
    "US_STATES",
    "PlatformDocument",
    "Reconciliation",
    "archive_members",
    "coverage_matrix",
    "decode_text",
    "download_dataset",
    "load_changelog",
    "load_corpus",
    "parse_filename",
    "reconcile",
]

DATASET_DOI = "doi:10.7910/DVN/KNOSHL"
DATASET_TITLE = "Select American State Party Platforms, 1846-2017"
DATASET_VERSION = "3.0"

#: Credit the authors who collected the corpus, not the repository that redistributes it.
SOURCE_ORG = (
    "Hopkins, Coffey, Galvin, Gamm, Henderson, Paddock & Schickler "
    "(Select American State Party Platforms, 1846-2017; Harvard Dataverse)"
)

_ACCESS_URL = "https://dataverse.harvard.edu/api/access/datafile/{file_id}"


@dataclass(frozen=True, slots=True)
class DatasetFile:
    """One file in the Dataverse dataset."""

    file_id: int
    filename: str
    role: str
    md5: str

    @property
    def url(self) -> str:
        return _ACCESS_URL.format(file_id=self.file_id)


#: Verified against the Dataverse dataset metadata on 2026-07-28. The MD5s are the
#: publisher's own digests, taken from the dataset's file metadata; checking downloads
#: against them means substituted or truncated content fails loudly instead of quietly
#: becoming "the corpus".
DATASET_FILES: tuple[DatasetFile, ...] = (
    DatasetFile(11106328, "platform-update-04212025.zip", "authoritative",
                "bab1654d0a4754b5beeb7f28241a63b3"),
    DatasetFile(5746322, "05 for public.zip", "superseded",
                "7c7e05a6c6b6de246c8e5c2f38efb613"),
    DatasetFile(11112198, "file_changes_04232025KG.txt", "changelog",
                "6d4aa4ded1b2ac59e3e94f790b45c25c"),
)

#: Party tokens treated as the two major parties. Historical factions such as ``GoldD``
#: (Gold Democrats) or ``RadR`` (Radical Republicans) are deliberately *not* folded into
#: D/R -- they were rival organizations, and collapsing them would misstate what the
#: state party of record actually said.
MAJOR_PARTIES = frozenset({"D", "R"})

#: The 50 states. ``US`` (national platforms) is intentionally excluded.
US_STATES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
)

_FILENAME_RE = re.compile(r"^(?P<state>[A-Z]{2})-(?P<year>\d{4})-(?P<rest>.+)$")


@dataclass(frozen=True, slots=True)
class PlatformDocument:
    """One platform document, parsed from its filename plus decoded text."""

    state: str
    year: int
    party: str
    party_raw: str
    flags: tuple[str, ...]
    filename: str
    member: str
    text: str
    sha256: str

    @property
    def is_major_party(self) -> bool:
        return self.party_raw in MAJOR_PARTIES

    @property
    def n_chars(self) -> int:
        return len(self.text)

    @property
    def n_words(self) -> int:
        return len(self.text.split())


def parse_filename(filename: str) -> tuple[str, int, str, tuple[str, ...]]:
    """Parse ``STATE-YEAR-PARTY[-FLAG]*.ext`` into ``(state, year, party_raw, flags)``.

    Raises :class:`ValueError` on anything that does not match, rather than skipping it --
    a silently dropped document would be a hole in the corpus that nothing else would
    catch.
    """
    stem = filename.rsplit(".", 1)[0]
    match = _FILENAME_RE.match(stem)
    if not match:
        raise ValueError(f"unparseable platform filename: {filename!r}")
    tokens = match.group("rest").split("-")
    party_raw = tokens[0].strip()
    if not party_raw:
        raise ValueError(f"empty party field in filename: {filename!r}")
    flags = tuple(t.strip() for t in tokens[1:] if t.strip())
    return match.group("state"), int(match.group("year")), party_raw, flags


def normalize_party(party_raw: str) -> str:
    """Map a raw party token to ``"D"``, ``"R"`` or ``"other"``."""
    return party_raw if party_raw in MAJOR_PARTIES else "other"


_RTF_GROUP_RE = re.compile(r"\{\\\*.*?\}", re.S)
_RTF_CONTROL_RE = re.compile(r"\\[a-zA-Z]+-?\d* ?")
_RTF_HEX_RE = re.compile(r"\\'([0-9a-fA-F]{2})")


def strip_rtf(text: str) -> str:
    """Reduce RTF source to its prose.

    Exactly one payload in the corpus is RTF (``US-1916-Socialist-B-EA.rtf``). Stored raw it
    contributed 3,319 "words" of control words and font/colour tables against a corpus median
    of 2,569 real ones, silently contaminating any length or term statistic computed over the
    corpus. This is a deliberately minimal stripper -- enough for one plain document, not a
    general RTF parser.
    """
    if not text.lstrip().startswith("{\\rtf"):
        return text
    text = _RTF_GROUP_RE.sub(" ", text)
    text = _RTF_HEX_RE.sub(lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), text)
    text = text.replace("\\par", "\n").replace("\\line", "\n").replace("\\tab", "\t")
    text = _RTF_CONTROL_RE.sub(" ", text)
    text = text.replace("{", " ").replace("}", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def decode_text(raw: bytes) -> str:
    """Decode platform text, tolerating the corpus's mixed encodings.

    Verified over the authoritative archive: 1,916 files are UTF-8 (376 of them with a BOM)
    and 175 are Windows-1252. ``utf-8-sig`` strips the BOM; cp1252 covers the rest. No file
    fails both.
    """
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _md5_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.md5()  # noqa: S324 - integrity check against the publisher's own digest
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def download_dataset(
    dest_dir: Path | str,
    *,
    log: ProvenanceLog | None = None,
    only: str | None = None,
) -> dict[str, Path]:
    """Download the dataset files into ``dest_dir``, recording provenance for each.

    Returns a mapping of role -> local path. Every file, whether freshly downloaded or found
    already on disk, is checked against the publisher's MD5; a mismatch raises rather than
    letting corrupted or substituted content silently become "the corpus". ``only`` restricts
    the download to a single role (e.g. ``"authoritative"``).
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for spec in DATASET_FILES:
        if only and spec.role != only:
            continue
        target = dest_dir / spec.filename
        if target.exists():
            # Still record provenance for a file that was already on disk, so the log never
            # has a silent hole where an input came from nowhere.
            record_local_file(
                target,
                url=spec.url,
                source_org=SOURCE_ORG,
                log=log,
                note=(
                    f"{DATASET_DOI} {spec.filename} ({spec.role}); "
                    "already present, not re-downloaded"
                ),
            )
        else:
            record = download_to_file(
                spec.url,
                target,
                source_org=SOURCE_ORG,
                log=log,
                timeout=300.0,
                note=f"{DATASET_DOI} {spec.filename} ({spec.role})",
            )
            if not record.ok:
                raise RuntimeError(
                    f"failed to download {spec.filename} from {spec.url}: "
                    f"status={record.http_status} error={record.error}"
                )

        actual = _md5_file(target)
        if actual != spec.md5:
            raise RuntimeError(
                f"{target} failed its integrity check: expected MD5 {spec.md5}, got {actual}. "
                "Delete the file and re-run to re-download."
            )
        paths[spec.role] = target
    return paths


def _is_payload(member: str) -> bool:
    """True for real corpus entries, excluding macOS AppleDouble cruft.

    ``__MACOSX/`` sidecar entries account for roughly half of every name list in these
    archives; counting them would double the corpus.
    """
    base = os.path.basename(member)
    return not (member.startswith("__MACOSX") or base.startswith("._") or member.endswith("/"))


def archive_members(zip_path: Path | str) -> list[str]:
    """Payload member names inside an archive, excluding AppleDouble sidecars."""
    with zipfile.ZipFile(zip_path) as archive:
        return [m for m in archive.namelist() if _is_payload(m)]


def _payload_digests(zip_path: Path | str) -> dict[str, str]:
    """``{basename: sha256}`` for every payload member of an archive."""
    with zipfile.ZipFile(zip_path) as archive:
        return {
            os.path.basename(member): sha256_bytes(archive.read(member))
            for member in archive.namelist()
            if _is_payload(member)
        }


def iter_documents(zip_path: Path | str) -> Iterator[PlatformDocument]:
    """Yield every platform document in ``zip_path``."""
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            if not _is_payload(member):
                continue
            filename = os.path.basename(member)
            state, year, party_raw, flags = parse_filename(filename)
            raw = archive.read(member)
            yield PlatformDocument(
                state=state,
                year=year,
                party=normalize_party(party_raw),
                party_raw=party_raw,
                flags=flags,
                filename=filename,
                member=member,
                text=strip_rtf(decode_text(raw)),
                sha256=sha256_bytes(raw),
            )


def load_changelog(path: Path | str) -> tuple[frozenset[str], frozenset[str]]:
    """Parse ``file_changes_*.txt`` into ``(added, deleted)`` filename sets."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    sections: dict[str, set[str]] = {"added": set(), "deleted": set()}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower().rstrip(":")
        if lowered == "added":
            current = "added"
            continue
        if lowered == "deleted":
            current = "deleted"
            continue
        if current and stripped.lower().endswith((".txt", ".rtf")):
            sections[current].add(stripped)
    return frozenset(sections["added"]), frozenset(sections["deleted"])


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Result of checking the two archives against the bundled changelog."""

    authoritative_count: int
    superseded_count: int
    added_expected: int
    deleted_expected: int
    added_confirmed: frozenset[str] = field(default_factory=frozenset)
    deleted_confirmed: frozenset[str] = field(default_factory=frozenset)
    added_unconfirmed: frozenset[str] = field(default_factory=frozenset)
    deleted_unconfirmed: frozenset[str] = field(default_factory=frozenset)
    revised_in_place: int = 0

    @property
    def consistent(self) -> bool:
        return not self.added_unconfirmed and not self.deleted_unconfirmed

    def summary(self) -> str:
        verdict = "consistent" if self.consistent else "INCONSISTENT"
        return (
            f"changelog {verdict}: authoritative={self.authoritative_count} "
            f"superseded={self.superseded_count} "
            f"added {len(self.added_confirmed)}/{self.added_expected} confirmed, "
            f"deleted {len(self.deleted_confirmed)}/{self.deleted_expected} confirmed, "
            f"revised_in_place={self.revised_in_place}"
        )


def reconcile(
    authoritative_zip: Path | str,
    superseded_zip: Path | str,
    changelog: Path | str,
) -> Reconciliation:
    """Verify that the update archive supersedes the older one exactly as documented.

    This exists so the "use the update archive alone" decision is *checked* against the
    authors' own changelog on every run, instead of being a comment someone has to trust.

    Members are reduced to digests rather than retained as bytes: the comparison only needs
    to know whether content differs, and holding both archives decompressed in memory costs
    ~118 MB for a result that fits in a few hundred kilobytes.
    """
    new_digests = _payload_digests(authoritative_zip)
    old_digests = _payload_digests(superseded_zip)

    added, deleted = load_changelog(changelog)
    only_new = set(new_digests) - set(old_digests)
    only_old = set(old_digests) - set(new_digests)
    shared = set(new_digests) & set(old_digests)
    revised = sum(1 for name in shared if new_digests[name] != old_digests[name])

    return Reconciliation(
        authoritative_count=len(new_digests),
        superseded_count=len(old_digests),
        added_expected=len(added),
        deleted_expected=len(deleted),
        added_confirmed=frozenset(added & only_new),
        deleted_confirmed=frozenset(deleted & only_old),
        added_unconfirmed=frozenset(added - only_new),
        deleted_unconfirmed=frozenset(deleted - only_old),
        revised_in_place=revised,
    )


def load_corpus(authoritative_zip: Path | str, *, include_text: bool = True):
    """Load the authoritative archive into a pandas DataFrame, one row per document."""
    import pandas as pd

    rows = []
    for doc in iter_documents(authoritative_zip):
        row = {
            "state": doc.state,
            "year": doc.year,
            "party": doc.party,
            "party_raw": doc.party_raw,
            "is_major_party": doc.is_major_party,
            "flags": "|".join(doc.flags),
            "filename": doc.filename,
            "member": doc.member,
            "sha256": doc.sha256,
            "n_chars": doc.n_chars,
            "n_words": doc.n_words,
        }
        if include_text:
            row["text"] = doc.text
        rows.append(row)
    frame = pd.DataFrame(rows)
    return frame.sort_values(["state", "year", "party_raw", "filename"], ignore_index=True)


def coverage_matrix(frame):
    """Per-state × major-party coverage: document count and most recent year.

    Rows are emitted for every U.S. state, including states the corpus does not cover at
    all, so an absence such as Maryland's shows up as an explicit zero rather than a
    missing row that a reader would never notice.
    """
    import pandas as pd

    major = frame[frame["party_raw"].isin(MAJOR_PARTIES)]
    counts = major.pivot_table(
        index="state", columns="party_raw", values="filename", aggfunc="count"
    )
    latest = major.pivot_table(index="state", columns="party_raw", values="year", aggfunc="max")

    index = sorted(set(US_STATES) | set(counts.index))
    out = pd.DataFrame(index=pd.Index(index, name="state"))
    for party in sorted(MAJOR_PARTIES):
        if party in counts.columns:
            out[f"n_{party}"] = counts[party].reindex(index).fillna(0).astype(int)
            out[f"latest_{party}"] = latest[party].reindex(index).astype("Int64")
        else:
            out[f"n_{party}"] = 0
            out[f"latest_{party}"] = pd.Series(pd.NA, index=index, dtype="Int64")
    out["n_total"] = out[[f"n_{p}" for p in sorted(MAJOR_PARTIES)]].sum(axis=1)
    out["latest_any"] = out[[f"latest_{p}" for p in sorted(MAJOR_PARTIES)]].max(axis=1)
    return out.reset_index()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", default="data/raw/dataverse",
                        help="where the downloaded archives live")
    parser.add_argument("--out-dir", default="data/processed",
                        help="where the parquet and coverage CSV are written")
    parser.add_argument("--provenance", default="data/provenance.jsonl")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args(argv)

    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = ProvenanceLog(args.provenance)

    if args.skip_download:
        paths = {spec.role: raw_dir / spec.filename for spec in DATASET_FILES}
        missing = [str(p) for p in paths.values() if not p.exists()]
        if missing:
            parser.error(f"--skip-download but these are missing: {missing}")
    else:
        paths = download_dataset(raw_dir, log=log)

    report = reconcile(paths["authoritative"], paths["superseded"], paths["changelog"])
    print(report.summary())
    if not report.consistent:
        print("  unconfirmed additions:", sorted(report.added_unconfirmed)[:10])
        print("  unconfirmed deletions:", sorted(report.deleted_unconfirmed)[:10])
        return 1

    frame = load_corpus(paths["authoritative"])
    parquet_path = out_dir / "platforms_historical.parquet"
    frame.to_parquet(parquet_path, index=False)

    coverage = coverage_matrix(frame)
    coverage_path = out_dir / "platforms_historical_coverage.csv"
    coverage.to_csv(coverage_path, index=False)

    major = frame[frame["is_major_party"]]
    uncovered = coverage[coverage["n_total"] == 0]["state"].tolist()
    unique = frame[["state", "year", "party_raw"]].drop_duplicates().shape[0]
    print(f"documents:            {len(frame)}")
    print(f"unique state/yr/party {unique}")
    print(f"major-party docs:     {len(major)} (D={int((major['party_raw'] == 'D').sum())}, "
          f"R={int((major['party_raw'] == 'R').sum())})")
    print(f"year range:           {int(frame['year'].min())}-{int(frame['year'].max())}")
    print(f"states with no major-party platform at all: {uncovered or 'none'}")
    print(f"wrote {parquet_path}")
    print(f"wrote {coverage_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Rebuild official party documents that require OCR.

Most platform documents expose text directly and are handled by :mod:`platforms.collect`.
Two reputable primary sources do not:

* New York Democrats publish an official State Committee resolutions archive as page images
  on their Issuu account.
* Louisiana Republicans publish quarterly State Central Committee resolution packets as
  scanned PDFs linked by the official LAGOP page and served by Wix's CDN.

This module makes those recoveries deterministic and auditable. It verifies source hashes from
``conf/official_document_registry.yml``, records every network fetch, records the Tesseract
version, OCRs in a fixed order, confirms state attribution, and merges rows by stable source ID.
No OCR-derived text or document row needs to be inserted by hand.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import subprocess
from pathlib import Path

from ..provenance import ProvenanceLog, fetch, sha256_bytes
from .collect import confirm_platform, repair_ligatures

__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "load_registry",
    "ocr_image",
    "ocr_pdf",
    "collect_official_documents",
    "merge_documents",
]

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_PATH = ROOT / "conf" / "official_document_registry.yml"
DEFAULT_CORPUS_PATH = ROOT / "data" / "processed" / "platforms_2018_present.parquet"
DEFAULT_PROVENANCE_PATH = ROOT / "data" / "provenance.jsonl"
ISSUU_IMAGE_TEMPLATE = (
    "https://image.isu.pub/{revision}-{publication}/jpg/page_{page}.jpg"
)
OCR_DPI = 200
OCR_CONFIG = "--psm 3"


def load_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> list[dict]:
    """Load and minimally validate the official-source registry."""
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    sources = raw.get("sources", [])
    ids = [source.get("id") for source in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("official document source IDs must be unique")
    required = {"id", "state", "party", "year", "institution", "document_type",
                "extraction", "primary_source", "page_url"}
    for source in sources:
        missing = required - set(source)
        if missing:
            raise ValueError(f"{source.get('id', '<unknown>')} missing {sorted(missing)}")
        if source["primary_source"] is not True:
            raise ValueError(f"{source['id']} is not marked as a primary source")
    return sources


def _tesseract_version() -> str:
    """Exact OCR executable version, recorded with every derived row."""
    output = subprocess.run(
        ["tesseract", "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if not output:
        raise RuntimeError("tesseract --version returned no output")
    return output[0].strip()


def ocr_image(image: bytes) -> str:
    """OCR one image with fixed configuration."""
    import pytesseract
    from PIL import Image

    with Image.open(io.BytesIO(image)) as opened:
        rgb = opened.convert("RGB")
        text = pytesseract.image_to_string(rgb, config=OCR_CONFIG)
    return repair_ligatures(text).strip()


def ocr_pdf(pdf: bytes) -> str:
    """Rasterize and OCR a scanned PDF in page order."""
    import fitz
    from PIL import Image

    pages = []
    with fitz.open(stream=pdf, filetype="pdf") as document:
        matrix = fitz.Matrix(OCR_DPI / 72, OCR_DPI / 72)
        for page in document:
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            pages.append(ocr_image(buffer.getvalue()))
    return "\n\n\f\n\n".join(pages).strip()


def _verified_fetch(
    url: str,
    *,
    expected_sha256: str,
    source_org: str,
    note: str,
    log: ProvenanceLog,
    max_bytes: int = 10 * 1024 * 1024,
) -> tuple[bytes, object]:
    body, record = fetch(
        url,
        source_org=source_org,
        note=note,
        log=log,
        max_bytes=max_bytes,
    )
    if not record.ok or body is None:
        raise RuntimeError(f"failed to fetch {url}: {record.error}")
    actual = sha256_bytes(body)
    if actual != expected_sha256:
        raise ValueError(
            f"source hash changed for {url}: expected {expected_sha256}, got {actual}"
        )
    return body, record


def _issuu_text(source: dict, log: ProvenanceLog) -> tuple[str, list[str], str]:
    page_body, page_record = fetch(
        source["page_url"],
        source_org=source["institution"],
        note=f"official document metadata {source['id']}",
        log=log,
        max_bytes=5 * 1024 * 1024,
    )
    if not page_record.ok or page_body is None:
        raise RuntimeError(f"failed to fetch {source['page_url']}: {page_record.error}")
    page_html = page_body.decode("utf-8", errors="replace")
    expected_title = source["expected_title"]
    if expected_title not in page_html:
        raise ValueError(f"Issuu metadata no longer identifies {expected_title!r}")

    hashes = [sha256_bytes(page_body)]
    pages = []
    for page in range(1, int(source["page_count"]) + 1):
        image_url = ISSUU_IMAGE_TEMPLATE.format(
            revision=source["issuu_revision_id"],
            publication=source["issuu_publication_id"],
            page=page,
        )
        image, record = fetch(
            image_url,
            source_org=source["institution"],
            note=f"{source['id']} page {page}/{source['page_count']}",
            log=log,
            max_bytes=5 * 1024 * 1024,
        )
        if not record.ok or image is None:
            raise RuntimeError(f"failed to fetch Issuu page {page}: {record.error}")
        hashes.append(sha256_bytes(image))
        pages.append(ocr_image(image))
    return "\n\n\f\n\n".join(pages), hashes, source["page_url"]


def _pdf_text(source: dict, log: ProvenanceLog) -> tuple[str, list[str], str]:
    pdf, _ = _verified_fetch(
        source["document_url"],
        expected_sha256=source["expected_document_sha256"],
        source_org=source["institution"],
        note=f"official scanned document {source['id']}",
        log=log,
    )
    return ocr_pdf(pdf), [source["expected_document_sha256"]], source["document_url"]


def collect_official_documents(
    sources: list[dict],
    *,
    log: ProvenanceLog,
) -> list[dict]:
    """Fetch, OCR, confirm and return reproducible corpus rows."""
    ocr_version = _tesseract_version()
    rows = []
    for source in sources:
        if source["extraction"] == "issuu_images":
            text, hashes, fetched_url = _issuu_text(source, log)
        elif source["extraction"] == "scanned_pdf":
            text, hashes, fetched_url = _pdf_text(source, log)
        else:
            raise ValueError(f"unknown extraction mode {source['extraction']!r}")

        state_name = {
            "NY": "New York",
            "LA": "Louisiana",
        }.get(source["state"], source["state"])
        confirmed, reason, hits = confirm_platform(text, state_name)
        if not confirmed:
            raise ValueError(f"{source['id']} did not confirm: {reason}")
        rows.append(
            {
                "official_source_id": source["id"],
                "state": source["state"],
                "party": source["party"],
                "url": source["page_url"],
                "fetched_url": fetched_url,
                "source": source["extraction"],
                "doc_type": source["document_type"],
                "year": int(source["year"]),
                "confirmed": True,
                "reason": f"{reason}; OCR {ocr_version}",
                "http_status": 200,
                "content_type": (
                    "image/jpeg pages" if source["extraction"] == "issuu_images"
                    else "application/pdf"
                ),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "n_chars": len(text),
                "n_words": len(text.split()),
                "phrase_hits": hits,
                "candidate_score": 5,
                "wayback_timestamp": None,
                "text": text,
                "source_hashes": hashes,
                "ocr_version": ocr_version,
            }
        )
    return rows


def merge_documents(corpus, rows: list[dict]):
    """Replace prior OCR rows by stable source ID or canonical URL."""
    import pandas as pd

    incoming = pd.DataFrame(rows)
    ids = set(incoming["official_source_id"])
    urls = set(incoming["url"])
    existing_ids = (
        corpus["official_source_id"]
        if "official_source_id" in corpus
        else pd.Series(index=corpus.index, dtype=object)
    )
    keep = ~existing_ids.isin(ids) & ~corpus["url"].isin(urls)
    base = corpus.loc[keep].copy()
    for column in incoming.columns:
        if column not in base:
            base[column] = None
    for column in base.columns:
        if column not in incoming:
            incoming[column] = None
    return pd.concat([base, incoming[base.columns]], ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--corpus", default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--provenance", default=DEFAULT_PROVENANCE_PATH)
    args = parser.parse_args(argv)

    sources = load_registry(args.registry)
    rows = collect_official_documents(
        sources,
        log=ProvenanceLog(args.provenance),
    )
    path = Path(args.corpus)
    corpus = pd.read_parquet(path)
    merged = merge_documents(corpus, rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(path, index=False)

    print(f"official OCR sources: {len(rows)}")
    for row in rows:
        print(
            f"  {row['state']}-{row['party']} {row['n_words']:,} words "
            f"{row['official_source_id']}"
        )
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

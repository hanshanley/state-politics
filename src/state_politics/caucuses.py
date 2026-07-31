"""Collect explicitly labelled state legislative caucus priority documents.

This is a **supplement**, not a back door around missing party platforms. Some state party
committees do not publish a platform at all; their legislative caucuses may still publish an
official agenda, such as a priority-bills list or a session priorities page. Those documents
are useful evidence of a state-level party agenda, but they come from a different institution,
so they live in their own corpus and are never concatenated with party platforms.

The distinction matters:

* ``platforms_2018_present.parquet`` answers what a **state party committee** formally says.
* ``caucus_priorities.parquet`` answers what a **state legislative caucus** publicly identifies
  as its priorities.
* ``bills.parquet`` answers what legislators actually introduce, for every state and both
  major parties.

The current registry covers Kentucky Republican senators, Maryland Senate Democrats, New Jersey
Assembly Republicans and Pennsylvania Senate Democrats. That provides at least one stated,
state-level agenda source for every state while preserving the honest 46/50 party-platform
coverage figure.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from .platforms.collect import extract_text
from .provenance import ProvenanceLog, fetch

__all__ = ["CaucusSource", "collect_sources", "load_registry"]

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "conf" / "caucus_priority_registry.yml"
)


@dataclass(frozen=True, slots=True)
class CaucusSource:
    """One curated state legislative caucus agenda source."""

    state: str
    party: str
    year: int
    institution: str
    document_type: str
    description: str
    urls: tuple[str, ...]


def load_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> list[CaucusSource]:
    """Load the small, hand-curated supplemental-source registry."""
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [
        CaucusSource(
            state=item["state"],
            party=item["party"],
            year=int(item["year"]),
            institution=item["institution"],
            document_type=item["document_type"],
            description=item["description"],
            urls=tuple(item["urls"]),
        )
        for item in raw.get("sources", [])
    ]


def collect_sources(
    sources: list[CaucusSource],
    *,
    log: ProvenanceLog,
    fetcher=fetch,
) -> list[dict]:
    """Fetch and combine every page listed for a caucus agenda source.

    A priority agenda often has one index page plus several detail pages. Combining only the
    curated URLs keeps that relationship explicit and avoids a keyword crawler silently
    expanding a caucus source into every press release it ever issued.
    """
    rows = []
    for source in sources:
        texts: list[str] = []
        fetched_urls: list[str] = []
        failed_urls: list[str] = []
        hashes: list[str] = []
        for url in source.urls:
            body, record = fetcher(
                url,
                source_org=source.institution,
                log=log,
                max_bytes=5 * 1024 * 1024,
                note=f"caucus priority source {source.state}-{source.party}",
            )
            if not record.ok or body is None:
                failed_urls.append(url)
                continue
            text = extract_text(body, record.content_type, record.final_url or url)
            if text:
                texts.append(text)
                fetched_urls.append(record.final_url or url)
                if record.content_sha256:
                    hashes.append(record.content_sha256)
        if not texts:
            raise RuntimeError(
                f"all listed URLs failed for {source.state}-{source.party} {source.institution}: "
                f"{', '.join(failed_urls)}"
            )
        text = "\n\n".join(texts)
        rows.append(
            {
                "state": source.state,
                "party": source.party,
                "year": source.year,
                "institution": source.institution,
                "document_type": source.document_type,
                "description": source.description,
                "urls": json.dumps(fetched_urls),
                "failed_urls": json.dumps(failed_urls),
                "source_hashes": json.dumps(hashes),
                "n_pages": len(fetched_urls),
                "n_words": len(text.split()),
                "text": text,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--out", default=root / "data/processed/caucus_priorities.parquet")
    parser.add_argument("--provenance", default=root / "data/provenance.jsonl")
    args = parser.parse_args(argv)

    sources = load_registry(args.registry)
    rows = collect_sources(sources, log=ProvenanceLog(args.provenance))
    frame = pd.DataFrame(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)

    print(f"caucus agenda sources: {len(frame)}")
    for row in rows:
        print(f"  {row['state']}-{row['party']}  {row['n_words']:,} words "
              f"from {row['n_pages']} pages ({row['institution']})")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

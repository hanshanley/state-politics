"""Fetch, extract and confirm the platform documents that :mod:`discover` located.

Discovery produces candidate URLs; this module turns the credible ones into text and decides
whether each really is a party platform. The decision is made on the document's own content,
not on its URL, for the same reason the registry check is: a URL that merely *looks* like a
platform is not evidence that it is one.

Retrieval prefers the Wayback snapshot over the live URL. Platforms are routinely replaced
rather than archived by the parties themselves, so the archived capture is frequently the only
remaining copy, and it is stable -- a live page can change under a later re-run, which would
make the corpus unreproducible. The ``id_`` modifier is used so the archive returns the
original bytes rather than a copy with its own navigation banner injected.

Output
------
* ``platforms_2018_present.parquet`` -- one row per confirmed document, with full text.
* ``platform_gap_report.csv`` -- one row per (state, party), each with an explicit status.
  A state party with no document is recorded as such, with the number of candidates that were
  considered and rejected, so an absence is auditable rather than merely asserted.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..provenance import ProvenanceLog, fetch
from .discover import STRONG_SCORE, Candidate

__all__ = [
    "DOC_TYPES",
    "CollectedDocument",
    "classify_doc_type",
    "collect_for_org",
    "confirm_platform",
    "extract_text",
    "gap_report",
    "wayback_snapshot_url",
]

#: Document classes. Platforms and convention resolutions are the party organization's own
#: statements of position; a legislative-priorities agenda is the narrower "what we intend to
#: pass this session" list. They are kept distinct so they can be analysed together or apart.
DOC_TYPES = ("platform", "resolutions", "principles", "legislative_priorities")

#: Phrases characteristic of a platform's prose. A platform declares positions; a news post
#: about a platform does not.
_PLATFORM_PHRASES = (
    r"\bwe believe\b", r"\bwe support\b", r"\bwe oppose\b", r"\bwe call (?:on|for)\b",
    r"\bwe affirm\b", r"\bwe urge\b", r"\bbe it resolved\b", r"\bwhereas\b",
    r"\bthe \w+ party (?:believes|supports|opposes|affirms)\b", r"\bplank\b",
    r"\bwe demand\b", r"\bwe recognize\b", r"\bour party\b", r"\bwe stand\b",
)
_PLATFORM_PHRASE_RE = re.compile("|".join(_PLATFORM_PHRASES), re.I)

#: A confirmed document must be at least this long. Real platforms run to thousands of words;
#: this excludes landing pages that merely link to one.
MIN_CHARS = 2500

_SCRIPT_RE = re.compile(r"<(script|style|nav|header|footer)\b[^>]*>.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class CollectedDocument:
    """One fetched candidate, whether or not it was confirmed as a platform."""

    state: str
    party: str
    url: str
    fetched_url: str
    source: str
    doc_type: str | None
    year: int | None
    confirmed: bool
    reason: str
    http_status: int | None = None
    content_type: str | None = None
    sha256: str | None = None
    n_chars: int = 0
    n_words: int = 0
    phrase_hits: int = 0
    candidate_score: int = 0
    wayback_timestamp: str | None = None
    text: str = ""

    def to_row(self) -> dict:
        row = asdict(self)
        return row


def wayback_snapshot_url(timestamp: str, url: str) -> str:
    """Archive URL returning the *original* bytes.

    The ``id_`` modifier suppresses the Wayback rewriting and banner, which would otherwise be
    extracted as part of the platform's text.
    """
    return f"https://web.archive.org/web/{timestamp}id_/{url}"


def extract_text(body: bytes, content_type: str | None, url: str) -> str:
    """Extract plain text from an HTML or PDF response."""
    is_pdf = (content_type or "").lower().startswith("application/pdf") or \
        url.lower().split("?")[0].endswith(".pdf") or body[:5] == b"%PDF-"
    if is_pdf:
        return _extract_pdf(body)
    html = body.decode("utf-8", errors="replace")
    html = _SCRIPT_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&amp;", "&", text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def _extract_pdf(body: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception:  # noqa: BLE001 - a malformed PDF is a data condition, not a crash
        return ""
    return re.sub(r"[ \t]+", " ", "\n".join(pages)).strip()


def classify_doc_type(url: str, text: str) -> str:
    """Classify a confirmed document. URL evidence first, then the text's own language."""
    haystack = f"{url}\n{text[:4000]}".lower()
    if re.search(r"legislative[-_ ]?priorit|policy[-_ ]?agenda", haystack):
        return "legislative_priorities"
    if re.search(r"\bplatform\b|\bplanks?\b", haystack):
        return "platform"
    if re.search(r"\bresolution", haystack):
        return "resolutions"
    if re.search(r"\bprinciples\b|\bcreed\b", haystack):
        return "principles"
    return "platform"


def confirm_platform(text: str, state_name: str | None = None) -> tuple[bool, str, int]:
    """Decide whether extracted text really is a party platform.

    Returns ``(confirmed, reason, phrase_hits)``. Length alone is not enough -- a party's news
    archive page is long too -- so the text must also speak in the declarative voice platforms
    use ("we believe", "we oppose", "be it resolved").
    """
    if not text:
        return False, "no text could be extracted", 0
    hits = len(_PLATFORM_PHRASE_RE.findall(text))
    if len(text) < MIN_CHARS:
        return False, f"too short to be a platform ({len(text)} chars < {MIN_CHARS})", hits
    if hits < 3:
        return False, f"lacks platform language (only {hits} declarative phrases)", hits
    return True, f"platform language confirmed ({hits} declarative phrases)", hits


def collect_candidate(
    candidate: Candidate,
    *,
    log: ProvenanceLog | None = None,
    transport=None,
    prefer_wayback: bool = True,
    timeout: float = 60.0,
) -> CollectedDocument:
    """Fetch one candidate and decide whether it is a platform document."""
    if prefer_wayback and candidate.wayback_timestamp:
        target = wayback_snapshot_url(candidate.wayback_timestamp, candidate.url)
        source = "wayback"
    else:
        target, source = candidate.url, "live"

    body, record = fetch(
        target,
        source_org=f"{candidate.state} state party ({candidate.party})",
        log=log,
        transport=transport,
        timeout=timeout,
        max_attempts=2,
        note=f"platform candidate {candidate.state}-{candidate.party}",
    )

    document = CollectedDocument(
        state=candidate.state, party=candidate.party, url=candidate.url,
        fetched_url=target, source=source, doc_type=None, year=candidate.year_hint,
        confirmed=False, reason="", http_status=record.http_status,
        content_type=record.content_type, sha256=record.content_sha256,
        candidate_score=candidate.score, wayback_timestamp=candidate.wayback_timestamp,
    )
    if not record.ok or not body:
        document.reason = f"fetch failed: status={record.http_status} error={record.error}"
        return document

    text = extract_text(body, record.content_type, candidate.url)
    confirmed, reason, hits = confirm_platform(text)
    document.n_chars = len(text)
    document.n_words = len(text.split())
    document.phrase_hits = hits
    document.confirmed = confirmed
    document.reason = reason
    if confirmed:
        document.doc_type = classify_doc_type(candidate.url, text)
        document.text = text
    return document


def collect_for_org(
    candidates: list[Candidate],
    *,
    min_score: int = STRONG_SCORE,
    max_documents: int = 12,
    log: ProvenanceLog | None = None,
    transport=None,
    delay: float = 0.5,
    sleep=time.sleep,
) -> list[CollectedDocument]:
    """Fetch the credible candidates for one organization, best-scoring first."""
    ranked = sorted(
        (c for c in candidates if c.score >= min_score),
        key=lambda c: (-c.score, -(c.year_hint or 0)),
    )[:max_documents]
    collected = []
    for index, candidate in enumerate(ranked):
        collected.append(collect_candidate(candidate, log=log, transport=transport))
        if delay and index < len(ranked) - 1:
            sleep(delay)
    return collected


def gap_report(
    registry: list[dict],
    candidates_by_org: dict[tuple[str, str], list[Candidate]],
    documents: list[CollectedDocument],
):
    """One row per (state, party) with an explicit, evidenced status.

    The four statuses are deliberately distinct: "no candidate URLs existed at all" is a very
    different finding from "candidates existed but none of them turned out to be a platform",
    and collapsing them would hide why a state is missing.
    """
    import pandas as pd

    confirmed_by_org: dict[tuple[str, str], list[CollectedDocument]] = {}
    attempted_by_org: dict[tuple[str, str], int] = {}
    for document in documents:
        key = (document.state, document.party)
        attempted_by_org[key] = attempted_by_org.get(key, 0) + 1
        if document.confirmed:
            confirmed_by_org.setdefault(key, []).append(document)

    rows = []
    for org in registry:
        key = (org["state"], org["party"])
        found = confirmed_by_org.get(key, [])
        candidates = candidates_by_org.get(key, [])
        strong = [c for c in candidates if c.score >= STRONG_SCORE]
        years = sorted({d.year for d in found if d.year})
        if found:
            status = "found"
        elif attempted_by_org.get(key):
            status = "candidates_rejected"
        elif candidates:
            status = "no_strong_candidates"
        else:
            status = "no_candidates"
        rows.append({
            "state": org["state"],
            "party": org["party"],
            "website": org.get("website"),
            "status": status,
            "n_confirmed": len(found),
            "n_candidates": len(candidates),
            "n_strong_candidates": len(strong),
            "n_fetched": attempted_by_org.get(key, 0),
            "years": ",".join(str(y) for y in years),
            "latest_year": years[-1] if years else None,
            "doc_types": ",".join(sorted({d.doc_type for d in found if d.doc_type})),
            "registry_needs_review": org.get("needs_review"),
        })
    return pd.DataFrame(rows)


def _load_candidates(path: Path) -> dict[tuple[str, str], list[Candidate]]:
    grouped: dict[tuple[str, str], list[Candidate]] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            candidate = Candidate(**json.loads(line))
            grouped.setdefault((candidate.state, candidate.party), []).append(candidate)
    return grouped


def main(argv: list[str] | None = None) -> int:
    import pandas as pd
    import yaml

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", default="conf/party_registry.yml")
    parser.add_argument("--candidates", default="data/processed/platform_candidates.jsonl")
    parser.add_argument("--out-dir", default="data/processed")
    parser.add_argument("--provenance", default="data/provenance.jsonl")
    parser.add_argument("--min-score", type=int, default=STRONG_SCORE)
    parser.add_argument("--max-documents", type=int, default=12)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--states", default="")
    args = parser.parse_args(argv)

    registry = yaml.safe_load(Path(args.registry).read_text(encoding="utf-8"))["organizations"]
    if args.states:
        wanted = {s.strip().upper() for s in args.states.split(",") if s.strip()}
        registry = [o for o in registry if o["state"] in wanted]

    grouped = _load_candidates(Path(args.candidates))
    log = ProvenanceLog(args.provenance)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    documents: list[CollectedDocument] = []
    for index, org in enumerate(registry, start=1):
        key = (org["state"], org["party"])
        collected = collect_for_org(
            grouped.get(key, []), min_score=args.min_score,
            max_documents=args.max_documents, log=log, delay=args.delay,
        )
        documents.extend(collected)
        confirmed = sum(1 for d in collected if d.confirmed)
        print(f"[{index:>3}/{len(registry)}] {org['state']}-{org['party']:<2} "
              f"fetched={len(collected):<3} confirmed={confirmed}")

    frame = pd.DataFrame([d.to_row() for d in documents])
    docs_path = out_dir / "platforms_2018_present.parquet"
    if not frame.empty:
        frame.to_parquet(docs_path, index=False)

    report = gap_report(registry, grouped, documents)
    report_path = out_dir / "platform_gap_report.csv"
    report.to_csv(report_path, index=False)

    confirmed = [d for d in documents if d.confirmed]
    print(f"\ndocuments fetched:   {len(documents)}")
    print(f"documents confirmed: {len(confirmed)}")
    print(f"organizations with >=1 document: "
          f"{report['n_confirmed'].gt(0).sum()}/{len(registry)}")
    print(report["status"].value_counts().to_string())
    print(f"wrote {docs_path}")
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

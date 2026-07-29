"""Discover state party platform documents published 2018-present.

The Harvard Dataverse corpus stops at 2017, so for the present-day question this project
exists to answer there is no dataset to download -- the documents have to be found. This
module locates *candidate* URLs; :mod:`state_politics.platforms.collect` fetches and
classifies them.

Two discovery channels, deliberately in this order:

1. **The Wayback Machine's CDX index.** One request per party domain returns every capture
   ever made whose URL matches the discovery terms, including documents the party has since
   deleted -- which matters, because platforms are routinely replaced rather than archived.
   It also puts no load on the party's own server.
2. **A single fetch of the live homepage**, scanning its links for the same terms. This
   catches pages the archive missed, at a cost of exactly one request per site.

Why candidates are scored rather than filtered
----------------------------------------------
A bare keyword match is far too noisy: a party's news feed is full of posts like
"a-message-from-the-chair-the-platform-purity-the-gop-demands-would-mean-utter-chaos", which
matches "platform" but is an op-ed, not a platform. Rather than silently discarding those,
every candidate is kept with a score and the reasons behind it, so the gap report can
distinguish "no document found" from "found nothing above threshold" -- an absence has to be
explainable, not merely asserted.

Verified traps
--------------
* ``*/cdn-cgi/challenge-platform/*`` -- Cloudflare's bot-check endpoint contains the word
  "platform" and swamped early results for four of the five domains first tested.
* WordPress ``/wp-json/``, ``/feed/``, ``/embed/`` and ``oembed`` URLs mirror real page URLs
  and would double-count every hit.
* A CDX query without a server-side filter hits the row cap: ``texasgop.org`` alone returns
  40,000+ captures, of which 17 are relevant.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..provenance import ProvenanceLog, fetch

__all__ = [
    "CDX_URL",
    "Candidate",
    "discover_for_org",
    "homepage_candidates",
    "is_excluded",
    "normalize_url",
    "score_candidate",
    "wayback_candidates",
]

CDX_URL = "https://web.archive.org/cdx/search/cdx"
WAYBACK_SOURCE_ORG = "Internet Archive (Wayback Machine CDX Server API)"

#: Terms that a platform-like document's URL tends to contain. Used both as the server-side
#: CDX regex and as the client-side link filter.
DISCOVERY_TERMS = (
    "platform", "principles", "resolutions", "priorities", "manifesto", "creed", "planks",
)

_TERMS_RE = re.compile("|".join(DISCOVERY_TERMS), re.I)

#: URLs that match a discovery term but can never be a platform document.
_EXCLUDE_RE = re.compile(
    r"cdn-cgi"                      # Cloudflare bot check: /cdn-cgi/challenge-platform/
    r"|/wp-json/|oembed|/feed/?$|/embed/?$|/amp/?$"   # WordPress mirrors of real pages
    r"|/tag/|/category/|/author/|/page/\d+"           # taxonomy and pagination
    r"|\?(?:replytocom|share|utm_)"                   # tracking and comment permalinks
    r"|/comment|/trackback"
    r"|\.(?:css|js|jpe?g|png|gif|svg|woff2?|ico|xml)(?:$|\?)",
    re.I,
)

#: A path segment that *is* the document, rather than a page that merely mentions one.
_DOC_WORD = r"(?:platform|platforms|principles|resolutions|planks|creed|manifesto)"
_STRONG_SEGMENT_RE = re.compile(
    rf"^(?:\d{{4}}[-_]?)?(?:party[-_])?{_DOC_WORD}(?:[-_]?\d{{4}})?$", re.I
)
#: A descriptive filename that *ends* with the document type, e.g.
#: ``2024-Idaho-Democratic-Party-Platform`` or ``2023-and-2024-Resolutions``. Real documents
#: are frequently named this way, so the news-headline penalty must not apply to them.
_DOC_SUFFIX_RE = re.compile(rf"(?:^|[-_]){_DOC_WORD}$", re.I)
_YEAR_IN_URL_RE = re.compile(r"(?:^|[^\d])(19[89]\d|20[0-4]\d)(?:[^\d]|$)")
_PRIORITIES_RE = re.compile(r"legislative[-_ ]?priorities|policy[-_ ]?agenda", re.I)


def normalize_url(url: str) -> str:
    """Canonical form used for de-duplication.

    Collapses the variants the archive is full of -- tracking query strings, ``index.html``,
    trailing slashes, and the ``archive.`` / ``www.`` host prefixes a party uses when it moves
    its old site aside -- so the same document is not counted several times.
    """
    parts = urllib.parse.urlsplit(url)
    host = re.sub(r"^(?:www\.|archive\.)", "", parts.netloc.lower())
    path = re.sub(r"/index\.html?$", "/", parts.path, flags=re.I).rstrip("/")
    return f"{host}{path.lower()}"


@dataclass
class Candidate:
    """One possible platform document, with why it is thought to be one."""

    state: str
    party: str
    url: str
    source: str
    mimetype: str | None = None
    wayback_timestamp: str | None = None
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    year_hint: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def is_excluded(url: str) -> bool:
    """True for URLs that match a discovery term but cannot be a platform document."""
    return bool(_EXCLUDE_RE.search(url))


def _path_segments(url: str) -> list[str]:
    path = urllib.parse.urlsplit(url).path
    return [segment for segment in path.split("/") if segment]


def score_candidate(url: str, mimetype: str | None = None) -> tuple[int, list[str]]:
    """Score how likely ``url`` is to be an actual platform document.

    Positive evidence is structural (a path segment that *is* "platform", a four-digit year
    beside it, a PDF whose filename says so). Negative evidence is the shape of a news post:
    a long hyphenated slug under a dated archive path.
    """
    score = 0
    reasons: list[str] = []
    segments = _path_segments(url)
    if not segments:
        return 0, ["no path"]

    last = segments[-1]
    stem = re.sub(r"\.(?:pdf|docx?|html?)$", "", last, flags=re.I)
    is_document = (mimetype or "").lower() == "application/pdf" or stem != last

    if any(_STRONG_SEGMENT_RE.match(segment) for segment in segments):
        score += 5
        reasons.append("path segment is the document type")
        strong = True
    elif _DOC_SUFFIX_RE.search(stem):
        # e.g. 2024-idaho-democratic-party-platform, 2023-and-2024-Resolutions
        score += 5
        reasons.append("name ends with the document type")
        strong = True
    else:
        strong = False

    if _PRIORITIES_RE.search(url):
        score += 4
        reasons.append("legislative priorities document")
        strong = True

    if is_document and _TERMS_RE.search(stem):
        score += 3
        reasons.append("PDF/document filename matches a discovery term")

    if _YEAR_IN_URL_RE.search(url) and _TERMS_RE.search(url):
        score += 2
        reasons.append("year appears alongside a discovery term")

    # News posts are long hyphenated sentences. This must not fire on a document whose name
    # merely happens to be descriptive -- "2024-idaho-democratic-party-platform" is exactly
    # what a real platform is called, and an earlier version of this scored it zero.
    if not strong:
        hyphens = stem.count("-") + stem.count("_")
        if hyphens >= 5:
            score -= 4
            reasons.append(f"slug reads like a news headline ({hyphens} words)")
        elif hyphens >= 3:
            score -= 2
            reasons.append(f"long slug ({hyphens} words)")

    if re.search(r"/20\d\d/\d\d/", url) and not is_document:
        score -= 3
        reasons.append("sits under a dated blog archive path")

    if not _TERMS_RE.search(url):
        score -= 5
        reasons.append("no discovery term in URL")

    return score, reasons


def wayback_candidates(
    domain: str,
    *,
    state: str,
    party: str,
    from_year: int = 2018,
    log: ProvenanceLog | None = None,
    transport=None,
    limit: int = 2000,
) -> list[Candidate]:
    """Query the Wayback CDX index for platform-like captures of ``domain``.

    Two server-side filters are essential, not optimisations:

    * the discovery-term regex, because an unfiltered query for ``texasgop.org`` returns more
      than 40,000 captures and silently truncates at the row cap; and
    * a negative filter on ``cdn-cgi``, because Cloudflare's bot-check endpoint lives at
      ``/cdn-cgi/challenge-platform/`` and therefore *matches the discovery term*. On
      ``dfl.org`` those junk URLs filled all 2,000 returned rows, pushing the real platform
      pages out of the window; filtering them only on the client produced a confident and
      completely wrong "no platform found" for the Minnesota DFL.
    """
    query = {
        "url": domain,
        "matchType": "domain",
        "output": "json",
        "collapse": "urlkey",
        "filter": [
            "statuscode:200",
            f"original:.*(?i)({'|'.join(DISCOVERY_TERMS)}).*",
            "!original:.*cdn-cgi.*",
        ],
        "from": str(from_year),
        "limit": str(limit),
        "fl": "timestamp,original,mimetype",
    }
    url = f"{CDX_URL}?{urllib.parse.urlencode(query, doseq=True)}"
    body, record = fetch(
        url,
        source_org=WAYBACK_SOURCE_ORG,
        log=log,
        transport=transport,
        timeout=120.0,
        max_attempts=3,
        note=f"CDX platform discovery for {state}-{party} ({domain})",
    )
    if not record.ok or not body:
        return []

    try:
        rows = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not rows or len(rows) < 2:
        return []

    candidates: list[Candidate] = []
    seen: set[str] = set()
    for timestamp, original, mimetype in (row[:3] for row in rows[1:]):
        if is_excluded(original):
            continue
        key = normalize_url(original)
        if key in seen:
            continue
        seen.add(key)
        score, reasons = score_candidate(original, mimetype)
        candidates.append(Candidate(
            state=state, party=party, url=original, source="wayback",
            mimetype=mimetype, wayback_timestamp=timestamp,
            score=score, reasons=reasons, year_hint=_year_hint(original, timestamp),
        ))
    return candidates


_HREF_RE = re.compile(r"""<a[^>]+href=["']([^"'#]+)["']""", re.I)


def homepage_candidates(
    homepage: str,
    *,
    state: str,
    party: str,
    log: ProvenanceLog | None = None,
    transport=None,
) -> list[Candidate]:
    """Scan the live homepage's links for platform-like URLs. Exactly one request."""
    body, record = fetch(
        homepage,
        source_org=f"{state} state party ({party}) homepage",
        log=log,
        transport=transport,
        timeout=30.0,
        max_attempts=1,
        note=f"live link scan for {state}-{party}",
    )
    if not record.ok or not body:
        return []

    html = body.decode("utf-8", errors="replace")
    base = record.final_url or homepage
    seen: set[str] = set()
    candidates = []
    for href in _HREF_RE.findall(html):
        absolute = urllib.parse.urljoin(base, href)
        if absolute in seen or is_excluded(absolute):
            continue
        if not _TERMS_RE.search(absolute):
            continue
        # Stay on the party's own site; an outbound link is somebody else's document.
        if urllib.parse.urlsplit(absolute).netloc != urllib.parse.urlsplit(base).netloc:
            continue
        seen.add(absolute)
        score, reasons = score_candidate(absolute)
        candidates.append(Candidate(
            state=state, party=party, url=absolute, source="live",
            score=score, reasons=reasons, year_hint=_year_hint(absolute, None),
        ))
    return candidates


def _year_hint(url: str, timestamp: str | None) -> int | None:
    """Best guess at the document's year from its URL, else the capture year.

    The URL wins when it carries one: ``/2022platform/`` captured in 2023 is the 2022
    platform, and dating it by the capture would be wrong.
    """
    match = _YEAR_IN_URL_RE.search(url)
    if match:
        return int(match.group(1))
    if timestamp and len(timestamp) >= 4 and timestamp[:4].isdigit():
        return int(timestamp[:4])
    return None


def discover_for_org(
    org: dict,
    *,
    from_year: int = 2018,
    log: ProvenanceLog | None = None,
    transport=None,
    include_live: bool = True,
) -> list[Candidate]:
    """Discover candidates for one registry row, merging both channels.

    Where the same URL is found by both channels the Wayback record is kept, because it
    carries a capture timestamp and remains retrievable even if the live page later changes.
    """
    website = org.get("website")
    if not website:
        return []
    state, party = org["state"], org["party"]
    domain = urllib.parse.urlsplit(website).netloc or website

    candidates = wayback_candidates(
        domain, state=state, party=party, from_year=from_year, log=log, transport=transport
    )
    if include_live:
        seen = {normalize_url(candidate.url) for candidate in candidates}
        for candidate in homepage_candidates(
            website, state=state, party=party, log=log, transport=transport
        ):
            key = normalize_url(candidate.url)
            if key not in seen:
                seen.add(key)
                candidates.append(candidate)
    return sorted(candidates, key=lambda c: (-c.score, c.url))


def write_candidates(candidates: list[Candidate], path: Path | str) -> Path:
    """Write every candidate, above threshold or not, as JSONL.

    Low-scoring candidates are retained deliberately: a later "no platform found" conclusion
    has to be auditable against what was actually considered and rejected.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for candidate in candidates:
            handle.write(json.dumps(candidate.to_dict(), sort_keys=True) + "\n")
    return path


#: Candidates at or above this score are treated as documents worth fetching.
STRONG_SCORE = 5


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time

    import yaml

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", default="conf/party_registry.yml")
    parser.add_argument("--out", default="data/processed/platform_candidates.jsonl")
    parser.add_argument("--provenance", default="data/provenance.jsonl")
    parser.add_argument("--from-year", type=int, default=2018)
    parser.add_argument("--no-live", action="store_true",
                        help="skip the live homepage scan (Wayback only)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds to pause between organizations")
    parser.add_argument("--states", default="",
                        help="comma-separated state codes to restrict to")
    args = parser.parse_args(argv)

    orgs = yaml.safe_load(Path(args.registry).read_text(encoding="utf-8"))["organizations"]
    if args.states:
        wanted = {s.strip().upper() for s in args.states.split(",") if s.strip()}
        orgs = [o for o in orgs if o["state"] in wanted]

    log = ProvenanceLog(args.provenance)
    all_candidates: list[Candidate] = []
    found_strong = 0
    for index, org in enumerate(orgs, start=1):
        candidates = discover_for_org(
            org, from_year=args.from_year, log=log, include_live=not args.no_live
        )
        strong = [c for c in candidates if c.score >= STRONG_SCORE]
        found_strong += bool(strong)
        all_candidates.extend(candidates)
        print(f"[{index:>3}/{len(orgs)}] {org['state']}-{org['party']:<2} "
              f"candidates={len(candidates):<4} strong={len(strong)}")
        if args.delay:
            time.sleep(args.delay)

    path = write_candidates(all_candidates, args.out)
    strong_total = sum(1 for c in all_candidates if c.score >= STRONG_SCORE)
    print(f"\norganizations:            {len(orgs)}")
    print(f"with >=1 strong candidate: {found_strong}")
    print(f"candidates written:        {len(all_candidates)} ({strong_total} strong)")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

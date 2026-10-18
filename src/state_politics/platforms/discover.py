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
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

from ..provenance import ProvenanceLog, fetch

__all__ = [
    "DOMAIN_ALIASES",
    "SECONDARY_TERMS",
    "DiscoveryOutcome",
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
    "platform", "principles", "resolution", "priorities", "manifesto", "creed", "planks",
)

_TERMS_RE = re.compile("|".join(DISCOVERY_TERMS), re.I)

#: Secondary terms, used only for organizations the primary pass found nothing for. Many state
#: parties do not use the word "platform" in their URLs at all: the New York Democrats file
#: theirs under ``/about/issues`` and the Kentucky Democrats under ``/about/``. Searching these
#: for every organization would bury the real documents in news posts, which is why they are a
#: fallback rather than part of the main term list.
SECONDARY_TERMS = (
    "issues", "beliefs", "values", "where-we-stand", "our-party", "agenda", "goals",
    "mission", "positions", "what-we-believe", "our-vision", "convention",
    "party-documents", "party_documents", "partydocuments", "constitution", "bylaws",
)
_SECONDARY_RE = re.compile("|".join(SECONDARY_TERMS), re.I)

#: Domains a state party used before rebranding. Several parties moved to short ``.gop``
#: addresses, and the archive's history -- including their older platforms -- sits under the
#: old name, so a search of the current domain alone returns nothing at all.
DOMAIN_ALIASES: dict[str, tuple[str, ...]] = {
    "degop.gop": ("delawaregop.com",),
    "florida.gop": ("floridagop.org",),
    "virginia.gop": ("rpv.org",),
    "mi.gop": ("migop.org",),
    "ne.gop": ("negop.org",),
    "ct.gop": ("ctgop.org",),
    "indiana.gop": ("indgop.org", "ingop.com"),
    "ri.gop": ("rigop.org",),
    "sc.gop": ("scgop.com",),
    "colorado.gop": ("cologop.org",),
    "illinois.gop": ("ilgop.org",),
    "missouri.gop": ("mogop.org",),
    "nh.gop": ("nhgop.org",),
    "wagop.org": ("wsrp.org",),
    "kansas.gop": ("kansasgop.org",),
    "nc.gop": ("ncgop.org",),
    "oregon.gop": ("oregonrepublicanparty.org",),
    "az.gop": ("azgop.com",),
    "azgop.com": ("az.gop",),
}

#: URLs that match a discovery term but can never be a platform document.
_EXCLUDE_RE = re.compile(
    r"cdn-cgi"                      # Cloudflare bot check: /cdn-cgi/challenge-platform/
    r"|/wp-json/|oembed|/feed/?$|/embed/?$|/amp/?$"   # WordPress mirrors of real pages
    r"|/tag/|/category/|/author/|/page/\d+"           # taxonomy and pagination
    r"|\?(?:replytocom|share|utm_)"                   # tracking and comment permalinks
    r"|/comment|/trackback"
    r"|\.(?:css|js|jpe?g|png|gif|svg|woff2?|ico|xml)(?:$|\?)"
    # Wix sites expose an internal API under a path containing "platform", and mint synthetic
    # sub-paths under every real page for design-system assets, media hashes and CSS values.
    # Delaware Republicans alone produced 1,883 of these, swamping the genuine /platform page.
    r"|/_api/|wix-laboratory"
    r"|\.json(?:$|\?)"                        # JSON assets are never platform documents
    r"|-Icons-|/-Social-|/-Sitemap-"           # Wix design-system paths
    r"|/-?[\d.]+(?:em|px|rem|vh|vw|%)(?:$|/)"  # CSS values appended as path segments
    r"|/\d+K?/(?:month|year)"
    r"|/robots\.txt|/sitemap|/favicon"
    r"|(?:/\d+K){2,}",                        # repeated synthetic segments
    re.I,
)

#: A path segment that *is* the document, rather than a page that merely mentions one.
_DOC_WORD = r"(?:platform|platforms|principles|resolutions?|planks|creed|manifesto)"
_STRONG_SEGMENT_RE = re.compile(
    rf"^(?:\d{{4}}[-_]?)?(?:party[-_])?{_DOC_WORD}(?:[-_]?\d{{4}})?$", re.I
)
#: A descriptive filename that *ends* with the document type, e.g.
#: ``2024-Idaho-Democratic-Party-Platform`` or ``2023-and-2024-Resolutions``. Real documents
#: are frequently named this way, so the news-headline penalty must not apply to them.
_DOC_SUFFIX_RE = re.compile(rf"(?:^|[-_]){_DOC_WORD}$", re.I)
_YEAR_IN_URL_RE = re.compile(r"(?:^|[^\d])(19[89]\d|20[0-4]\d)(?:[^\d]|$)")
_PRIORITIES_RE = re.compile(r"legislative[-_ ]?priorities|policy[-_ ]?agenda", re.I)
_DRIVE_FILE_RE = re.compile(r"/file/d/[A-Za-z0-9_-]+/(?:preview|view)/?$")


def normalize_url(url: str) -> str:
    """Canonical form used for de-duplication.

    Collapses the variants the archive is full of -- tracking query strings, ``index.html``,
    trailing slashes, and the ``archive.`` / ``www.`` host prefixes a party uses when it moves
    its old site aside -- so the same document is not counted several times.
    """
    parts = urllib.parse.urlsplit(url)
    host = re.sub(r"^(?:www\.|archive\.)", "", parts.netloc.lower())
    if host == "drive.google.com" and _DRIVE_FILE_RE.fullmatch(parts.path):
        return f"{host}{parts.path.rstrip('/')}"
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
    link_text: str | None = None
    link_source_url: str | None = None
    link_source_sha256: str | None = None
    link_tag: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DiscoveryOutcome:
    """What discovery found for one organization, and whether it actually ran.

    The distinction matters more than it looks. An empty candidate list can mean "this party
    has published nothing" or "the archive refused the query", and those are opposite
    findings. Collapsing them once already produced a confident, wrong "no platform found"
    for four organizations whose CDX queries had simply failed, so the outcome carries the
    query status explicitly and the gap report keys off it.
    """

    state: str
    party: str
    candidates: list[Candidate] = field(default_factory=list)
    wayback_ok: bool = False
    wayback_error: str | None = None
    live_ok: bool = False
    live_error: str | None = None

    @property
    def searched(self) -> bool:
        """True if at least one channel actually returned a result."""
        return self.wayback_ok or self.live_ok

    def to_status_row(self) -> dict:
        strong = sum(1 for c in self.candidates if c.score >= STRONG_SCORE)
        return {
            "state": self.state,
            "party": self.party,
            "searched": self.searched,
            "wayback_ok": self.wayback_ok,
            "wayback_error": self.wayback_error,
            "live_ok": self.live_ok,
            "live_error": self.live_error,
            "n_candidates": len(self.candidates),
            "n_strong": strong,
        }


def is_excluded(url: str) -> bool:
    """True for URLs that match a discovery term but cannot be a platform document."""
    if _EXCLUDE_RE.search(url):
        return True
    path = urllib.parse.urlsplit(url).path
    if re.search(r"/[0-9a-f]{6}_[0-9a-f]{12,}", path, re.I) and not path.lower().endswith(".pdf"):
        return True
    # A repeated path segment is the signature of a generated URL, not a document. Wix mints
    # paths such as /platform/10K/black/10K/black/white beneath every real page; no genuine
    # document path repeats a segment.
    segments = [s for s in path.split("/") if s]
    if len(segments) != len(set(segments)):
        return True
    # A purely numeric trailing segment is a CSS value or coordinate, not a document.
    return bool(segments) and bool(re.fullmatch(r"-?\d+(?:\.\d+)?", segments[-1]))


def _path_segments(url: str) -> list[str]:
    path = urllib.parse.urlsplit(url).path
    return [segment for segment in path.split("/") if segment]


def score_candidate(
    url: str, mimetype: str | None = None, *, link_text: str | None = None,
    link_tag: str | None = None,
) -> tuple[int, list[str]]:
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
    #: A file the browser downloads rather than renders. Unlike `is_document` this excludes
    #: .htm/.html, which are ordinary web pages and can perfectly well be news posts.
    is_downloadable = ((mimetype or "").lower() == "application/pdf"
                       or bool(re.search(r"\.(?:pdf|docx?)$", last, re.I)))

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
    #
    # It must also not fire on a *downloadable document*. Parties name platform files
    # descriptively: "2024-HRP-Platform-Convention-Updates.pdf" was penalised two points for
    # looking chatty, which dropped Hawaii's Republican platform below the strong-candidate
    # threshold and left the state recorded as publishing nothing. The guard above only caught
    # names *ending* in the document type, so "Platform" in the middle slipped through.
    #
    # The exemption is deliberately narrower than `is_document`, which is also true for .html:
    # exempting every HTML page would let dated blog posts such as
    # "/2009/02/on-reagan-day-his-principles-are-still.html" score as strong candidates, which
    # is precisely what this penalty exists to prevent.
    if not strong and not is_downloadable:
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

    if is_downloadable and link_text and _TERMS_RE.search(link_text):
        score = max(score, STRONG_SCORE)
        reasons.append(f"official document link label: {link_text[:200]}")

    if link_tag in {"iframe", "embed", "object"}:
        attribute = "data" if link_tag == "object" else "src"
        reasons.append(f"embedded document reference: {link_tag}[{attribute}]")

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
    sleep=time.sleep,
    terms: tuple[str, ...] = DISCOVERY_TERMS,
) -> tuple[list[Candidate], str | None]:
    """Query the Wayback CDX index for platform-like captures of ``domain``.

    Returns ``(candidates, error)``. ``error`` is ``None`` only when the query genuinely
    succeeded, so callers can tell "nothing published" from "the query did not run" -- an
    empty list from a failed request would otherwise read as a confident absence.

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
            f"original:.*(?i)({'|'.join(terms)}).*",
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
        max_attempts=4,
        backoff=5.0,
        sleep=sleep,
        note=f"CDX platform discovery for {state}-{party} ({domain})",
    )
    if not record.ok or not body:
        return [], f"CDX query failed: status={record.http_status} error={record.error}"

    try:
        rows = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [], f"CDX response was not valid JSON: {exc}"
    if not rows or len(rows) < 2:
        return [], None  # a genuine, successful "no captures matched"

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
    return candidates, None


class _HomepageLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, str, str | None]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def _finish(self):
        if self._href is not None:
            self.links.append((self._href, " ".join(" ".join(self._text).split()), "a", None))
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a":
            self._finish()
            self._href = attributes.get("href")
            self._text = [attributes.get("aria-label") or attributes.get("title") or ""]
        elif tag in {"iframe", "embed", "object"}:
            target = attributes.get("data" if tag == "object" else "src")
            if target:
                label = attributes.get("aria-label") or attributes.get("title") or ""
                mimetype = (attributes.get("type") or "").lower().split(";")[0].strip()
                self.links.append((target, " ".join(label.split()), tag, mimetype or None))

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self._finish()

    def close(self):
        super().close()
        self._finish()


def homepage_candidates(
    homepage: str,
    *,
    state: str,
    party: str,
    log: ProvenanceLog | None = None,
    transport=None,
    sleep=time.sleep,
    secondary: bool = False,
    raw_dir: Path | str | None = None,
) -> tuple[list[Candidate], str | None]:
    """Scan same-origin links, embedded PDFs and linked/embedded Drive files. One request.

    Returns ``(candidates, error)`` for the same reason as :func:`wayback_candidates`.
    An embed establishes a reference, not authorship, adoption or a scoring shortcut.
    """
    body, record = fetch(
        homepage,
        source_org=f"{state} state party ({party}) homepage",
        log=log,
        transport=transport,
        timeout=30.0,
        max_attempts=1,
        sleep=sleep,
        dest=Path(raw_dir) / f"homepage-{uuid4().hex}.html" if raw_dir is not None else None,
        note=f"live link scan for {state}-{party}",
    )
    if not record.ok or not body:
        return [], f"homepage fetch failed: status={record.http_status} error={record.error}"

    html = body.decode("utf-8", errors="replace")
    parser = _HomepageLinks()
    parser.feed(html)
    parser.close()
    base = record.final_url or homepage
    seen: set[str] = set()
    candidates = []
    for href, label, tag, mimetype in parser.links:
        if href.startswith("#"):
            continue
        absolute = urllib.parse.urljoin(base, href)
        if absolute in seen or is_excluded(absolute):
            continue
        parts = urllib.parse.urlsplit(absolute)
        drive_document = (
            parts.scheme in {"http", "https"} and parts.netloc.lower() == "drive.google.com"
            and _DRIVE_FILE_RE.fullmatch(parts.path) is not None
        )
        embedded_document = (
            tag != "a" and parts.scheme in {"http", "https"}
            and (
                parts.path.lower().endswith(".pdf") or mimetype == "application/pdf"
                or drive_document
            )
        )
        labelled_pdf = (
            parts.path.lower().endswith(".pdf")
            and _TERMS_RE.search(label)
        )
        matches = (
            _TERMS_RE.search(absolute) or (secondary and _SECONDARY_RE.search(absolute))
            or labelled_pdf or embedded_document or drive_document
        )
        if not matches:
            continue
        if tag != "a" and not embedded_document:
            continue
        if (parts.netloc != urllib.parse.urlsplit(base).netloc
                and not embedded_document and not drive_document):
            continue
        seen.add(absolute)
        score, reasons = score_candidate(absolute, mimetype, link_text=label, link_tag=tag)
        candidates.append(Candidate(
            state=state, party=party, url=absolute, source="live", mimetype=mimetype,
            score=score, reasons=reasons, year_hint=_year_hint(absolute, None),
            link_text=label, link_source_url=base,
            link_source_sha256=record.content_sha256, link_tag=tag,
        ))
    return candidates, None


def _year_hint(url: str, timestamp: str | None) -> int | None:
    """Prefer a filename/last-segment year over other URL years, then capture year.

    The URL wins when it carries one: ``/2022platform/`` captured in 2023 is the 2022
    platform. An upload directory can be newer than its named document. This remains
    a discovery hint, not an adoption or operative date.
    """
    last = urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    match = _YEAR_IN_URL_RE.search(last)
    if match:
        return int(match.group(1))
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
    include_wayback: bool = True,
    sleep=time.sleep,
    deep: bool = False,
    raw_dir: Path | str | None = None,
) -> DiscoveryOutcome:
    """Discover candidates for one registry row, merging both channels.

    Where the same URL is found by both channels the Wayback record is kept, because it
    carries a capture timestamp and remains retrievable even if the live page later changes.

    ``deep`` widens the search for organizations the ordinary pass found nothing for. It adds
    :data:`SECONDARY_TERMS` -- many parties never use the word "platform" in a URL, filing
    theirs under ``/about/issues`` or ``/issues/`` -- and searches any domain the party used
    before rebranding, since a party that moved to a short ``.gop`` address has all of its
    archived history under the old name. Both are off by default because, applied everywhere,
    they bury real documents under news posts.
    """
    state, party = org["state"], org["party"]
    outcome = DiscoveryOutcome(state=state, party=party)

    website = org.get("website")
    if not website:
        outcome.wayback_error = "no website configured"
        outcome.live_error = "no website configured"
        return outcome

    domain = urllib.parse.urlsplit(website).netloc or website
    searches: list[tuple[str, tuple[str, ...]]] = [(domain, DISCOVERY_TERMS)]
    if deep:
        bare = domain[4:] if domain.startswith("www.") else domain
        searches.append((domain, SECONDARY_TERMS))
        for alias in DOMAIN_ALIASES.get(bare, ()):
            searches.append((alias, DISCOVERY_TERMS))
            searches.append((alias, SECONDARY_TERMS))

    candidates: list[Candidate] = []
    seen: set[str] = set()
    errors: list[str] = []
    any_ok = False
    for search_domain, terms in searches if include_wayback else []:
        found, error = wayback_candidates(
            search_domain, state=state, party=party, from_year=from_year, log=log,
            transport=transport, sleep=sleep, terms=terms,
        )
        any_ok = any_ok or error is None
        if error:
            errors.append(f"{search_domain}: {error}")
        for candidate in found:
            key = normalize_url(candidate.url)
            if key not in seen:
                seen.add(key)
                candidates.append(candidate)
    outcome.wayback_ok = any_ok
    outcome.wayback_error = "; ".join(errors) or None

    if include_live:
        live, live_error = homepage_candidates(
            website, state=state, party=party, log=log, transport=transport, sleep=sleep,
            secondary=deep, raw_dir=raw_dir,
        )
        outcome.live_ok = live_error is None
        outcome.live_error = live_error
        for candidate in live:
            key = normalize_url(candidate.url)
            if key not in seen:
                seen.add(key)
                candidates.append(candidate)

    outcome.candidates = sorted(candidates, key=lambda c: (-c.score, c.url))
    return outcome


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

    import yaml

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", default="conf/party_registry.yml")
    parser.add_argument("--out", default="data/processed/platform_candidates.jsonl")
    parser.add_argument("--provenance", default="data/provenance.jsonl")
    parser.add_argument("--raw-dir", default="data/raw/platforms/discovery",
                        help="retain homepage response bodies referenced by provenance")
    parser.add_argument("--checkpoint-dir",
                        help="new directory for per-organization results; defaults beside --out")
    parser.add_argument("--from-year", type=int, default=2018)
    parser.add_argument("--no-live", action="store_true",
                        help="skip the live homepage scan (Wayback only)")
    parser.add_argument("--no-wayback", action="store_true",
                        help="scan live homepages only, without archive queries or retries")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds to pause between organizations")
    parser.add_argument("--states", default="",
                        help="comma-separated state codes to restrict to")
    parser.add_argument("--deep", action="store_true",
                        help="widen the search with secondary terms and pre-rebrand domains; "
                             "for organizations the ordinary pass found nothing for")
    args = parser.parse_args(argv)
    if args.no_live and args.no_wayback:
        parser.error("at least one discovery channel must be enabled")

    orgs = yaml.safe_load(Path(args.registry).read_text(encoding="utf-8"))["organizations"]
    if args.states:
        wanted = {s.strip().upper() for s in args.states.split(",") if s.strip()}
        orgs = [o for o in orgs if o["state"] in wanted]

    log = ProvenanceLog(args.provenance)
    output_path = Path(args.out)
    checkpoint_dir = (
        Path(args.checkpoint_dir) if args.checkpoint_dir else
        output_path.with_name(output_path.stem + "_checkpoints")
    )
    if checkpoint_dir.exists():
        parser.error(f"checkpoint directory exists: {checkpoint_dir}; choose a new output run")
    checkpoint_dir.mkdir(parents=True)
    context = {
        "schema_version": 1,
        "registry_sha256": sha256(Path(args.registry).read_bytes()).hexdigest(),
        "discovery_code_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "arguments": vars(args),
    }

    def save_checkpoint(outcome, phase, retried=None):
        path = checkpoint_dir / f"{outcome.state}-{outcome.party}-{phase}.json"
        temporary = path.with_suffix(".json.part")
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump({
                **context, "phase": phase, "outcome": asdict(outcome),
                "retry_outcome": asdict(retried) if retried is not None else None,
            }, handle, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)

    all_candidates: list[Candidate] = []
    outcomes: list[DiscoveryOutcome] = []
    for index, org in enumerate(orgs, start=1):
        outcome = discover_for_org(
            org, from_year=args.from_year, log=log, include_live=not args.no_live,
            deep=args.deep, raw_dir=args.raw_dir, include_wayback=not args.no_wayback,
        )
        strong = [c for c in outcome.candidates if c.score >= STRONG_SCORE]
        outcomes.append(outcome)
        all_candidates.extend(outcome.candidates)
        save_checkpoint(outcome, "initial")
        flag = "" if outcome.searched else "  <-- SEARCH FAILED"
        print(f"[{index:>3}/{len(orgs)}] {org['state']}-{org['party']:<2} "
              f"candidates={len(outcome.candidates):<4} strong={len(strong)}{flag}", flush=True)
        if args.delay:
            time.sleep(args.delay)

    # Retry organizations whose Wayback query failed outright. Leaving them as an empty
    # result would be indistinguishable from a party that has published nothing.
    failed = [o for o in outcomes if not o.wayback_ok and o.wayback_error
              and "no website" not in o.wayback_error]
    if failed:
        print(f"\nretrying {len(failed)} failed Wayback queries...", flush=True)
        by_key = {(o["state"], o["party"]): o for o in orgs}
        for outcome in failed:
            time.sleep(max(args.delay, 3.0))
            org = by_key[(outcome.state, outcome.party)]
            retried = discover_for_org(org, from_year=args.from_year, log=log,
                                       include_live=False, deep=args.deep)
            if retried.wayback_ok:
                seen = {normalize_url(c.url) for c in outcome.candidates}
                added = [c for c in retried.candidates if normalize_url(c.url) not in seen]
                outcome.candidates.extend(added)
                outcome.wayback_ok, outcome.wayback_error = True, None
                all_candidates.extend(added)
                print(f"  {outcome.state}-{outcome.party}: recovered "
                      f"{len(retried.candidates)} candidates", flush=True)
            else:
                print(f"  {outcome.state}-{outcome.party}: still failing "
                      f"({retried.wayback_error})", flush=True)
            save_checkpoint(outcome, "wayback-retry", retried)

    path = write_candidates(all_candidates, args.out)
    status_path = Path(args.out).with_name("platform_discovery_status.csv")
    _write_status(outcomes, status_path)

    strong_total = sum(1 for c in all_candidates if c.score >= STRONG_SCORE)
    searched = sum(1 for o in outcomes if o.searched)
    with_strong = sum(
        1 for o in outcomes if any(c.score >= STRONG_SCORE for c in o.candidates)
    )
    print(f"\norganizations:             {len(orgs)}")
    print(f"successfully searched:     {searched}")
    print(f"with >=1 strong candidate: {with_strong}")
    print(f"candidates written:        {len(all_candidates)} ({strong_total} strong)")
    print(f"wrote {path}")
    print(f"wrote {status_path}")
    return 0


def _write_status(outcomes: list[DiscoveryOutcome], path: Path) -> Path:
    import csv as _csv

    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [o.to_status_row() for o in outcomes]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = _csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["state"])
        writer.writeheader()
        writer.writerows(rows)
    return path


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

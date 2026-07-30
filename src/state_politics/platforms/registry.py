"""Build the registry of all 100 state party organizations (50 states x 2 parties).

Everything in the 2018-present collection depends on knowing, for each state, the official
website of that state's Democratic and Republican party committee. There is no single
authoritative machine-readable list, so this module assembles candidates from Wikidata and
then *checks* them, rather than trusting them.

Why two different Wikidata queries
----------------------------------
Wikidata's coverage of the two parties is lopsided, which was verified before writing this:

* Democratic state parties are modelled cleanly. ``?p wdt:P31/wdt:P279* wd:Q7278 ;
  wdt:P17 wd:Q30 ; wdt:P131 ?state`` returns an entity with an official website (P856) for
  **all 50 states**.
* Republican state parties largely **lack ``P131``** (located in the administrative
  territorial entity). The same query returns only **7** states. A label-based query returns
  81 Republican-named entities, 54 with a website, which then have to be matched to states
  by name.

So the Democratic side is resolved structurally and the Republican side by name, and every
row is marked with how it was resolved so the weaker path is visible rather than hidden.

County and auxiliary organizations
----------------------------------
The label query also returns county committees (``Erie County Republican Committee``) and
auxiliary groups (``California Republican Assembly``, ``Young Republican``), which are not
the state committee. These are filtered out. The filter cannot simply blacklist the word
"Committee", because several genuine state parties are named that way -- ``New York
Republican State Committee``, ``New Jersey Republican State Committee``.

Output
------
``conf/party_registry.yml``, one row per (state, party), each carrying ``source_url`` and
``verified_on`` plus the HTTP status observed for its homepage. Rows that could not be
resolved, or whose site did not respond, are emitted with ``needs_review: true`` rather than
dropped -- a missing state party must be visible, not silently absent.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from ..provenance import USER_AGENT, ProvenanceLog, fetch, utc_now_iso

__all__ = [
    "STATE_NAMES",
    "PartyOrg",
    "build_registry",
    "match_state",
    "parse_sparql_csv",
    "query_wikidata",
    "verify_homepage",
    "write_registry",
]

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_SOURCE_ORG = "Wikidata contributors (Wikimedia Foundation)"

STATE_NAMES: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
    "Wyoming": "WY",
}

#: Alternate spellings that appear in Wikidata labels.
_LABEL_ALIASES = {"Hawai\u02bbi": "Hawaii"}

#: Labels containing these are county or auxiliary bodies, not the state committee.
#: Note this deliberately does *not* include "Committee": several state parties are
#: officially named "... Republican State Committee".
_EXCLUDE_PATTERNS = (
    r"\bcounty\b", r"\bcity\b", r"\bborough\b", r"\bparish\b", r"\bward\b",
    r"\bassembly\b", r"\byoung\b", r"\bcollege\b", r"\bwomen'?s\b", r"\bclub\b",
    r"\bfederation\b", r"\bcaucus\b", r"\bmoderate\b", r"\bindependent\b",
    r"\bdemocratic-republican\b", r"\bnational\b", r"\bliberal\b", r"\bjefferson",
)

DEMOCRATIC_QUERY = """
SELECT DISTINCT ?party ?partyLabel ?website ?admLabel WHERE {
  ?party wdt:P31/wdt:P279* wd:Q7278 ; wdt:P17 wd:Q30 ; wdt:P131 ?adm .
  ?adm wdt:P31 wd:Q35657 .
  OPTIONAL { ?party wdt:P856 ?website }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

REPUBLICAN_QUERY = """
SELECT DISTINCT ?party ?partyLabel ?website ?admLabel WHERE {
  ?party wdt:P31/wdt:P279* wd:Q7278 ; wdt:P17 wd:Q30 ; rdfs:label ?lab .
  FILTER(LANG(?lab) = "en" && CONTAINS(?lab, "Republican"))
  OPTIONAL { ?party wdt:P856 ?website }
  OPTIONAL { ?party wdt:P131 ?adm }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


@dataclass(frozen=True, slots=True)
class Override:
    """A state party site resolved outside Wikidata, with how the candidate was found."""

    website: str
    name: str
    evidence: str


#: Corrections applied on top of Wikidata, each established by a direct check on
#: 2026-07-28. Two kinds appear here:
#:
#: * states where Wikidata carries no website at all, and
#: * states where Wikidata's URL is stale and now resolves somewhere else entirely --
#:   ``migop.org`` and ``negop.org`` currently redirect to unrelated commercial sites, and
#:   ``southdakotagop.com`` now serves a law-firm directory. Writing those into the registry
#:   unchecked would have silently pointed the whole platform crawl at spam.
#:
#: These are *candidates*: whether a row is trusted is still decided empirically by
#: :func:`verify_homepage`, which confirms the live page names the state and the party.
MANUAL_OVERRIDES: dict[tuple[str, str], Override] = {
    ("MT", "R"): Override(
        "https://mtgop.org/", "Montana Republican Party",
        "Wikidata has no website; direct check 2026-07-28: HTTP 200, title 'Home - MTGOP'"),
    ("NH", "R"): Override(
        "https://nh.gop/", "New Hampshire Republican State Committee",
        "Wikidata has no website; direct check 2026-07-28: nhgop.org redirects to nh.gop, "
        "HTTP 200, title 'New Hampshire Republican Party'"),
    ("PA", "R"): Override(
        "https://pagop.org/", "Republican Party of Pennsylvania",
        "Wikidata has no website; direct check 2026-07-28: HTTP 200, title "
        "'Home - Republican Party of Pennsylvania'"),
    ("KY", "R"): Override(
        "https://rpk.org/", "Republican Party of Kentucky",
        "Wikidata has no website; direct check 2026-07-28: host answered but refused a "
        "scripted request (HTTP 403)"),
    ("OK", "R"): Override(
        "https://okgop.com/", "Oklahoma Republican Party",
        "Wikidata has no website; direct check 2026-07-28: host answered but refused a "
        "scripted request (HTTP 403)"),
    ("AZ", "R"): Override(
        "https://azgop.com/", "Arizona Republican Party",
        "corrects Wikidata's az.gop, which on 2026-07-28 redirected to an image file on "
        "media.kjzz.org; azgop.com returned HTTP 200, title 'Home - AZGOP'"),
    ("SD", "R"): Override(
        "https://www.sdgop.com/", "South Dakota Republican Party",
        "corrects Wikidata's southdakotagop.com, which on 2026-07-28 served a law-firm "
        "directory ('SD TOP LAW FIRMS'); sdgop.com returned HTTP 200, title "
        "'South Dakota Republican Party'"),
    ("MI", "R"): Override(
        "https://mi.gop/", "Michigan Republican Party",
        "corrects Wikidata's migop.org, which on 2026-07-28 redirected to the unrelated "
        "site kiss918menang.com; mi.gop answered but refused a scripted request (HTTP 403)"),
    ("NE", "R"): Override(
        "https://ne.gop/", "Nebraska Republican Party",
        "corrects Wikidata's negop.org, which on 2026-07-28 redirected to the unrelated "
        "site wildarms4.com; ne.gop answered but refused a scripted request (HTTP 403)"),
    ("WA", "R"): Override(
        "https://wagop.org/", "Washington State Republican Party",
        "corrects Wikidata's wsrp.org, whose host did not resolve on 2026-07-28; "
        "wagop.org returned HTTP 200, title 'Washington State Republican Party'"),
    ("CT", "R"): Override(
        "https://ct.gop/", "Connecticut Republican Party",
        "corrects Wikidata's www.ctgop.org, whose host did not resolve on 2026-07-28; "
        "ct.gop answered but refused a scripted request (HTTP 403)"),
    ("IN", "R"): Override(
        "https://indiana.gop/", "Indiana Republican Party",
        "corrects Wikidata's www.indgop.org, which timed out on 2026-07-28 (ingop.com is a "
        "domain-resale listing); indiana.gop answered but refused a scripted request "
        "(HTTP 403)"),
    ("RI", "R"): Override(
        "https://ri.gop/", "Rhode Island Republican Party",
        "corrects Wikidata's www.rigop.org, whose host did not resolve on 2026-07-28; "
        "ri.gop answered but refused a scripted request (HTTP 403)"),
    # Six state Republican parties have rebranded onto .gop domains and their old hosts now
    # redirect. Recording the destination directly keeps the crawl on a first-party URL
    # instead of relying on a redirect chain that could later be repointed.
    ("CO", "R"): Override(
        "https://colorado.gop/", "Colorado Republican Committee",
        "cologop.org redirects here; direct check 2026-07-29: HTTP 200, "
        "title 'Home - Colorado GOP'"),
    ("DE", "R"): Override(
        "https://degop.gop/", "Delaware Republican Party",
        "delawaregop.com redirects here; direct check 2026-07-29: HTTP 200, "
        "title 'Delaware Republican Party | Official Website'"),
    ("IL", "R"): Override(
        "https://illinois.gop/", "Illinois Republican Party",
        "ILGOP.org redirects here; direct check 2026-07-29: HTTP 200, "
        "title 'Home - The Illinois Republican Party'"),
    ("MO", "R"): Override(
        "https://missouri.gop/", "Missouri Republican Party",
        "mogop.org redirects here; direct check 2026-07-29: HTTP 200, "
        "title 'Home - The Republican Party of Missouri'"),
    ("SC", "R"): Override(
        "https://sc.gop/", "South Carolina Republican Party",
        "scgop.com redirects here; direct check 2026-07-29: HTTP 200, "
        "title 'Home | South Carolina GOP'"),
    ("VA", "R"): Override(
        "https://virginia.gop/", "Republican Party of Virginia",
        "rpv.org redirects here; direct check 2026-07-29: HTTP 200, "
        "title 'Home - Republican Party of Virginia'"),
}


@dataclass
class PartyOrg:
    """One state party organization in the registry."""

    state: str
    party: str
    name: str | None = None
    website: str | None = None
    wikidata_id: str | None = None
    resolved_by: str | None = None
    candidate_evidence: str | None = None
    homepage_status: int | None = None
    final_url: str | None = None
    verified_on: str | None = None
    source_url: str = WIKIDATA_SPARQL
    needs_review: bool = True
    note: str | None = None


def query_wikidata(query: str, *, log: ProvenanceLog | None = None,
                   transport=None) -> list[dict[str, str]]:
    """Run a SPARQL query and return its CSV rows as dicts."""
    import urllib.parse

    url = f"{WIKIDATA_SPARQL}?{urllib.parse.urlencode({'query': query})}"
    body, record = fetch(
        url,
        source_org=WIKIDATA_SOURCE_ORG,
        log=log,
        transport=transport,
        # WDQS hard-caps queries at 60 s, so waiting longer can never be productive.
        timeout=60.0,
        max_attempts=3,
        headers={"Accept": "text/csv", "User-Agent": USER_AGENT},
        note="state party registry candidates",
    )
    if not record.ok or body is None:
        raise RuntimeError(
            f"Wikidata query failed: status={record.http_status} error={record.error}"
        )
    return parse_sparql_csv(body.decode("utf-8"))


def parse_sparql_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _normalize_label(label: str) -> str:
    for alias, replacement in _LABEL_ALIASES.items():
        label = label.replace(alias, replacement)
    return label


def match_state(label: str, adm_label: str = "") -> str | None:
    """Resolve a state postal code from an entity label, or ``None`` if not a state party.

    Prefers the structural ``P131`` value when present, since a label match is weaker: it
    would otherwise read "Republican Party of Texas" and "Erie County Republican Committee"
    with equal confidence.
    """
    adm = _normalize_label(adm_label or "").strip()
    if adm in STATE_NAMES:
        return STATE_NAMES[adm]

    label = _normalize_label(label or "")
    lowered = label.lower()
    if any(re.search(pattern, lowered) for pattern in _EXCLUDE_PATTERNS):
        return None
    # Longest name first so "West Virginia" is not matched as "Virginia".
    for name in sorted(STATE_NAMES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name.lower())}\b", lowered):
            return STATE_NAMES[name]
    return None


def _is_party_label(label: str, party: str) -> bool:
    lowered = (label or "").lower()
    if party == "D":
        return "democratic" in lowered or "democrat" in lowered
    return "republican" in lowered or "gop" in lowered


def _collect(rows: list[dict[str, str]], party: str) -> dict[str, PartyOrg]:
    found: dict[str, PartyOrg] = {}
    for row in rows:
        label = row.get("partyLabel", "")
        if not _is_party_label(label, party):
            continue
        adm_label = row.get("admLabel", "")
        state = match_state(label, adm_label)
        if state is None:
            continue
        website = (row.get("website") or "").strip() or None
        existing = found.get(state)
        # Prefer an entry that actually carries a website.
        if existing and (existing.website or not website):
            continue
        # Record the structural path only when P131 genuinely resolved the state. A P131 that
        # points at a county still leaves the state to be inferred from the label, and
        # labelling that as structural would hide the weaker evidence.
        structural = _normalize_label(adm_label).strip() in STATE_NAMES
        found[state] = PartyOrg(
            state=state,
            party=party,
            name=_normalize_label(label),
            website=website,
            wikidata_id=(row.get("party") or "").rsplit("/", 1)[-1] or None,
            resolved_by="wikidata-P131" if structural else "label",
        )
    return found


def _url_variants(url: str) -> list[str]:
    """Candidate forms of the same registrable domain, most-specific first.

    Several Wikidata entries carry stale ``http://www.`` URLs whose hosts no longer resolve
    even though the party's site is live at the bare https domain. Trying these variants is
    a normalization of the *same* domain, not a guess at a different one.

    Variants are compared with any trailing slash removed, because ``https://x.org`` and
    ``https://x.org/`` are the same HTTP request and retrying one after the other just
    doubles the timeout cost on hosts that are down.
    """
    variants: list[str] = []
    seen: set[str] = set()
    host = re.sub(r"^https?://", "", url).rstrip("/").split("/", 1)[0]
    bare = host[4:] if host.startswith("www.") else host
    for candidate in (url, f"https://{host}", f"https://{bare}", f"http://{bare}"):
        key = candidate.rstrip("/")
        if key not in seen:
            seen.add(key)
            variants.append(candidate)
    return variants


def registrable_domain(url: str) -> str:
    """The last two labels of the host, e.g. ``https://www.mtgop.org/x`` -> ``mtgop.org``."""
    host = re.sub(r"^https?://", "", url or "").split("/", 1)[0].lower()
    host = host.split(":", 1)[0]
    labels = [label for label in host.split(".") if label]
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


#: Opening tag of a block whose contents are markup, not prose.
_BLOCK_TAGS = ("script", "style")
_BLOCK_OPEN_RE = re.compile(r"<(" + "|".join(_BLOCK_TAGS) + r")\b[^>]*>", re.I)

def strip_blocks(html: str, tags: tuple[str, ...]) -> str:
    """Remove ``<tag>...</tag>`` blocks with a linear scan.

    The obvious regex for this -- ``<(script|nav|...)\b[^>]*>.*?</\1>`` -- backtracks
    quadratically on hostile input, because every opening tag that never closes rescans to the
    end of the document. Measured here: 14 KB of unclosed ``<nav>`` took 0.11 s, 112 KB took
    6.5 s, and a fetch is allowed to be 64 MB. Since every byte scanned comes from a
    third-party website, that is a denial-of-service vector on the crawler, so the scan is done
    explicitly with ``str.find`` instead. An unclosed tag drops the tag and keeps the text.
    """
    if not html:
        return html
    lowered = html.lower()
    out: list[str] = []
    position = 0
    # Once no closing tag for a name exists after some offset, none exists after any later
    # offset either. Without remembering that, a document full of unclosed tags re-scans to
    # the end for every one of them, which is the same quadratic blow-up in a different guise:
    # 1.4 MB of unclosed <nav> took 196 s before this set was added.
    exhausted: set[str] = set()
    while True:
        match = _BLOCK_OPEN_RE.search(html, position)
        if match is None:
            out.append(html[position:])
            return "".join(out)
        out.append(html[position:match.start()])
        out.append(" ")
        tag = match.group(1).lower()
        if tag in exhausted:
            position = match.end()
            continue
        closing = lowered.find(f"</{tag}", match.end())
        if closing == -1:
            exhausted.add(tag)
            position = match.end()
            continue
        end = html.find(">", closing)
        position = len(html) if end == -1 else end + 1

_TAG_RE = re.compile(r"<[^>]+>")
#: URLs, e-mail addresses and bare domain tokens. Stripped before matching so that a page's
#: own domain name cannot supply the very words we are testing for.
_URLISH_RE = re.compile(
    r"https?://\S+|[\w.+-]+@[\w.-]+|\b[\w-]+\.(?:org|com|net|gov|edu|us|gop|io|co)\b", re.I
)
#: Titles/phrases that positively disconfirm a live party site.
_PARKED_MARKERS = (
    "account suspended",
    "domain for sale",
    "this domain is parked",
    "buy this domain",
    "domain is for sale",
    "hugedomains",
    "website coming soon",
    "under construction",
    "default web page",
    "index of /",
)

_PARTY_TERMS = {
    "D": (r"democratic party", r"democrats", r"democratic", r"democrat"),
    "R": (r"republican party", r"republicans", r"republican", r"\bgop\b"),
}


def visible_text(body: bytes) -> str:
    """Lowercased visible text of an HTML page, with scripts, tags and URLs removed."""
    html = body.decode("utf-8", errors="replace")
    html = strip_blocks(html, _BLOCK_TAGS)
    html = _TAG_RE.sub(" ", html)
    return re.sub(r"\s+", " ", html).lower()


def _term_hits(text: str, party: str) -> int:
    return sum(len(re.findall(term, text)) for term in _PARTY_TERMS[party])


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def _title_confirms(html: str, state_name: str, party: str) -> bool:
    """True if the page's own ``<title>`` names this state and only this party.

    A party site names itself in its title ("New York Republican State Committee"), whereas a
    hijacked or parked page does not. This is a second, stricter route to confirmation: the
    body-frequency test alone rejects state parties whose homepage attacks the other party as
    often as it names itself, which on the New York GOP homepage is an exact 5-5 tie.
    """
    match = _TITLE_RE.search(html)
    if not match:
        return False
    title = _URLISH_RE.sub(" ", re.sub(r"<[^>]+>", " ", match.group(1)).lower())
    if not re.search(rf"\b{re.escape(state_name)}\b", title):
        return False
    other = "R" if party == "D" else "D"
    return _term_hits(title, party) > 0 and _term_hits(title, other) == 0


def _content_confirms(body: bytes, state_code: str, party: str) -> bool:
    """True if the page's visible text identifies it as *this* state's *this* party.

    Four traps this has to survive, all of which earlier versions fell into and which are the
    reason it is written so defensively:

    1. **The domain name self-confirms.** Matching raw HTML let a page prove itself simply by
       linking to itself: ``http://www.alaskagop.org`` serves an "Account Suspended" page whose
       only occurrences of "alaska" and "gop" are inside ``webmaster@alaskagop.org``, and it was
       accepted as a verified state party homepage. URLs, e-mails and bare domain tokens are
       therefore stripped before any matching.
    2. **The other party's name is everywhere.** Republican sites talk about "democrats"
       constantly, so a bare substring test for "democrat" confirmed a GOP page as the state
       Democratic party. Confirmation requires the page to mention its *own* party more often
       than the other one.
    3. **Parked and suspended pages still return HTTP 200.** Those are matched explicitly and
       treated as disconfirming rather than merely unconvincing.
    4. **Some parties attack the other side as often as they name themselves.** A pure
       frequency test rejects them, so a page whose ``<title>`` names this state and only this
       party is also accepted.
    """
    html = body.decode("utf-8", errors="replace")
    text = visible_text(body)
    if any(marker in text for marker in _PARKED_MARKERS):
        return False

    text = _URLISH_RE.sub(" ", text)
    state_name = next((n for n, c in STATE_NAMES.items() if c == state_code), "").lower()
    if not state_name or not re.search(rf"\b{re.escape(state_name)}\b", text):
        return False

    own = _term_hits(text, party)
    if own == 0:
        return False
    other = _term_hits(text, "R" if party == "D" else "D")
    return own > other or _title_confirms(html, state_name, party)


def verify_homepage(org: PartyOrg, *, log: ProvenanceLog | None = None,
                    transport=None, timeout: float = 20.0) -> PartyOrg:
    """Fetch the org's homepage, confirm it names the party, and record what was observed.

    A non-200 is not fatal: many state party sites sit behind bot protection and answer 403 to
    a scripted request while still being the correct domain. Both the status and whether the
    content confirmed the party are recorded, so a reviewer can see why a row is or is not
    trusted.

    The URL the crawl will later use is **never** taken from the redirect chain. A domain that
    has lapsed can redirect anywhere, so ``website`` keeps the configured value and the
    observed destination is recorded separately in ``final_url``; a redirect that leaves the
    registrable domain forces human review.
    """
    if not org.website:
        org.needs_review = True
        org.note = "no website configured"
        return org

    configured = org.website
    best_status: int | None = None
    last_error: str | None = None

    for candidate in _url_variants(configured):
        body, record = fetch(
            candidate,
            source_org=f"{org.name or org.state} ({org.party})",
            log=log,
            transport=transport,
            timeout=timeout,
            max_attempts=2 if candidate == configured else 1,
            note="state party homepage verification",
        )
        org.verified_on = record.retrieved_at[:10]
        # Keep the most informative observation across variants: a 403 proves the host is
        # alive, and must not be overwritten by a later variant's DNS failure.
        if record.http_status is not None and best_status is None:
            best_status = record.http_status
        if record.error:
            last_error = record.error
        if not record.ok or body is None:
            continue

        org.homepage_status = record.http_status
        org.final_url = record.final_url or candidate
        off_domain = registrable_domain(org.final_url) != registrable_domain(configured)
        if off_domain:
            org.needs_review = True
            org.note = (
                f"redirected off-domain to {registrable_domain(org.final_url)}; "
                "not trusted without human review"
            )
        elif _content_confirms(body, org.state, org.party):
            org.needs_review = False
            org.note = "visible page text identifies this state's party"
        else:
            org.needs_review = True
            org.note = "HTTP 200 but visible page text did not identify this state's party"
        return org

    org.homepage_status = best_status
    if best_status in (401, 403, 405, 406, 429):
        org.note = (
            f"host answers but refused a scripted request (HTTP {best_status}); "
            "content could not be confirmed"
        )
    else:
        org.note = f"unreachable: status={best_status} error={last_error}"
    org.needs_review = True
    return org


def build_registry(*, log: ProvenanceLog | None = None, verify: bool = True,
                   transport=None) -> list[PartyOrg]:
    """Assemble the 100-row registry, one entry per state per major party."""
    democratic = _collect(query_wikidata(DEMOCRATIC_QUERY, log=log, transport=transport), "D")
    republican = _collect(query_wikidata(REPUBLICAN_QUERY, log=log, transport=transport), "R")

    registry: list[PartyOrg] = []
    for state in sorted(STATE_NAMES.values()):
        for party, found in (("D", democratic), ("R", republican)):
            org = found.get(state)
            # A hand-checked correction always wins over Wikidata: several Wikidata URLs are
            # stale and now resolve to unrelated sites, so "Wikidata has a value" is not
            # evidence that the value is right.
            override = MANUAL_OVERRIDES.get((state, party))
            if override is not None:
                org = PartyOrg(
                    state=state,
                    party=party,
                    name=override.name,
                    website=override.website,
                    wikidata_id=org.wikidata_id if org else None,
                    resolved_by="manual-override",
                    candidate_evidence=override.evidence,
                    source_url=override.website,
                )
            if org is None:
                org = PartyOrg(
                    state=state, party=party, resolved_by=None,
                    note="no Wikidata entity matched this state party",
                )
            if verify:
                org = verify_homepage(org, log=log, transport=transport)
            registry.append(org)
    return registry


def write_registry(registry: list[PartyOrg], path: Path | str) -> Path:
    import yaml

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": utc_now_iso(),
        "source": (
            "Wikidata contributors (2026). Wikidata [Knowledge base]. Wikimedia Foundation. "
            "https://query.wikidata.org/sparql. CC0 1.0. Candidates are machine-resolved and "
            "then homepage-checked; rows with needs_review: true require human confirmation "
            "against the party's own website before use."
        ),
        "organizations": [asdict(org) for org in registry],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="conf/party_registry.yml")
    parser.add_argument("--provenance", default="data/provenance.jsonl")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip homepage checks (offline candidate build only)")
    args = parser.parse_args(argv)

    log = ProvenanceLog(args.provenance)
    registry = build_registry(log=log, verify=not args.no_verify)
    path = write_registry(registry, args.out)

    resolved = [o for o in registry if o.website]
    ok = [o for o in registry if not o.needs_review]
    print(f"rows:               {len(registry)} (expected 100)")
    for party in ("D", "R"):
        subset = [o for o in registry if o.party == party]
        print(f"  {party}: website found {sum(1 for o in subset if o.website)}/50, "
              f"verified {sum(1 for o in subset if not o.needs_review)}/50")
    print(f"websites resolved:  {len(resolved)}/100")
    print(f"homepage verified:  {len(ok)}/100")
    missing = [f"{o.state}-{o.party}" for o in registry if not o.website]
    if missing:
        print(f"no website found:   {missing}")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

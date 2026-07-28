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


#: Wikidata carries no website for these five Republican state parties. Each domain was
#: located and checked directly on 2026-07-28. These are *candidates*: whether a row is
#: trusted is decided empirically by :func:`verify_homepage`, which confirms the live page
#: actually names the state and the party, so nothing here is asserted on faith.
MANUAL_OVERRIDES: dict[tuple[str, str], Override] = {
    ("MT", "R"): Override(
        "https://mtgop.org/", "Montana Republican Party",
        "direct check 2026-07-28: HTTP 200, page title 'Home - MTGOP'"),
    ("NH", "R"): Override(
        "https://nh.gop/", "New Hampshire Republican State Committee",
        "direct check 2026-07-28: nhgop.org redirects to nh.gop, HTTP 200, "
        "page title 'New Hampshire Republican Party'"),
    ("PA", "R"): Override(
        "https://pagop.org/", "Republican Party of Pennsylvania",
        "direct check 2026-07-28: HTTP 200, page title "
        "'Home - Republican Party of Pennsylvania'"),
    ("KY", "R"): Override(
        "https://rpk.org/", "Republican Party of Kentucky",
        "direct check 2026-07-28: host answered but refused a scripted request (HTTP 403)"),
    ("OK", "R"): Override(
        "https://okgop.com/", "Oklahoma Republican Party",
        "direct check 2026-07-28: host answered but refused a scripted request (HTTP 403)"),
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
        timeout=180.0,
        max_attempts=4,
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


def _collect(rows: list[dict[str, str]], party: str, resolved_by: str) -> dict[str, PartyOrg]:
    found: dict[str, PartyOrg] = {}
    for row in rows:
        label = row.get("partyLabel", "")
        if not _is_party_label(label, party):
            continue
        state = match_state(label, row.get("admLabel", ""))
        if state is None:
            continue
        website = (row.get("website") or "").strip() or None
        existing = found.get(state)
        # Prefer an entry that actually carries a website.
        if existing and (existing.website or not website):
            continue
        found[state] = PartyOrg(
            state=state,
            party=party,
            name=_normalize_label(label),
            website=website,
            wikidata_id=(row.get("party") or "").rsplit("/", 1)[-1] or None,
            resolved_by=resolved_by if row.get("admLabel") else "label",
        )
    return found


def _url_variants(url: str) -> list[str]:
    """Candidate forms of the same registrable domain, most-specific first.

    Several Wikidata entries carry stale ``http://www.`` URLs whose hosts no longer resolve
    even though the party's site is live at the bare https domain. Trying these variants is
    a normalization of the *same* domain, not a guess at a different one.
    """
    variants = [url]
    stripped = re.sub(r"^https?://", "", url).rstrip("/")
    host = stripped.split("/", 1)[0]
    bare = host[4:] if host.startswith("www.") else host
    for candidate in (f"https://{host}", f"https://{bare}", f"http://{bare}"):
        if candidate not in variants:
            variants.append(candidate)
    return variants


def _content_confirms(body: bytes, state_code: str, party: str) -> bool:
    """True if the page text names both the state and the party.

    Confirming from the page itself means a registry entry is validated by evidence on every
    run, rather than by a hard-coded assertion that silently rots when a domain changes
    hands.
    """
    try:
        text = body.decode("utf-8", errors="replace").lower()
    except (UnicodeDecodeError, AttributeError):
        return False
    state_name = next((n for n, c in STATE_NAMES.items() if c == state_code), "")
    if state_name.lower() not in text:
        return False
    keywords = ("democrat",) if party == "D" else ("republican", "gop")
    return any(word in text for word in keywords)


def verify_homepage(org: PartyOrg, *, log: ProvenanceLog | None = None,
                    transport=None, timeout: float = 45.0) -> PartyOrg:
    """Fetch the org's homepage, confirm it names the party, and record what was observed.

    A non-200 is *not* treated as fatal: many state party sites sit behind bot protection and
    answer 403 to a scripted request while still being the correct domain. Both the status
    and whether the page content confirmed the party are recorded, so a reviewer can see
    exactly why a row is or is not trusted.
    """
    if not org.website:
        org.needs_review = True
        org.note = "no website in Wikidata"
        return org

    last_status: int | None = None
    last_error: str | None = None
    for candidate in _url_variants(org.website):
        body, record = fetch(
            candidate,
            source_org=f"{org.name or org.state} ({org.party})",
            log=log,
            transport=transport,
            timeout=timeout,
            max_attempts=2,
            note="state party homepage verification",
        )
        last_status, last_error = record.http_status, record.error
        org.verified_on = record.retrieved_at[:10]
        if not record.ok or body is None:
            continue

        org.website = record.final_url or candidate
        org.homepage_status = record.http_status
        if _content_confirms(body, org.state, org.party):
            org.needs_review = False
            org.note = "homepage HTTP 200 and page text names the state and party"
        else:
            org.needs_review = True
            org.note = "homepage HTTP 200 but page text did not name the state and party"
        return org

    org.homepage_status = last_status
    if last_status in (401, 403, 405, 406, 429):
        org.note = (
            f"host answers but refused a scripted request (HTTP {last_status}); "
            "content could not be confirmed"
        )
    else:
        org.note = f"unreachable: status={last_status} error={last_error}"
    org.needs_review = True
    return org


def build_registry(*, log: ProvenanceLog | None = None, verify: bool = True,
                   transport=None) -> list[PartyOrg]:
    """Assemble the 100-row registry, one entry per state per major party."""
    democratic = _collect(query_wikidata(DEMOCRATIC_QUERY, log=log, transport=transport),
                          "D", "wikidata-P131")
    republican_rows = query_wikidata(REPUBLICAN_QUERY, log=log, transport=transport)
    republican = _collect(republican_rows, "R", "wikidata-P131")

    registry: list[PartyOrg] = []
    for state in sorted(STATE_NAMES.values()):
        for party, found in (("D", democratic), ("R", republican)):
            org = found.get(state)
            if org is None or not org.website:
                override = MANUAL_OVERRIDES.get((state, party))
                if override is not None:
                    org = PartyOrg(
                        state=state,
                        party=party,
                        name=override.name,
                        website=override.website,
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

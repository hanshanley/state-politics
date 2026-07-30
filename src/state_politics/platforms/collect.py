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
import hashlib
import io
import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ..provenance import ProvenanceLog, fetch
from .discover import STRONG_SCORE, Candidate, score_candidate
from .registry import STATE_NAMES

#: Postal code -> state name, for attributing a document to the state party that wrote it.
STATE_NAMES_BY_CODE = {code: name for name, code in STATE_NAMES.items()}

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

#: The same declarations with word separators removed, for PDFs whose embedded fonts carry no
#: usable word spacing. Without this a genuine 31,817-character platform that extracted as
#: "SouthDakotaDemocraticPartyPlatform..." scores zero declarative phrases and is discarded.
_DESPACED_PHRASES = (
    "webelieve", "wesupport", "weoppose", "wecallon", "wecallfor", "weaffirm", "weurge",
    "beitresolved", "whereas", "plank", "wedemand", "werecognize", "ourparty", "westand",
)
_DESPACED_PHRASE_RE = re.compile("|".join(_DESPACED_PHRASES), re.I)

#: A confirmed document must be at least this long. Real platforms run to thousands of words;
#: this excludes landing pages that merely link to one.
MIN_CHARS = 2500

#: Hand-checked explanations for the parties with no platform, joined into the gap report.
_GAP_FINDINGS_PATH = Path(__file__).resolve().parents[3] / "conf" / "platform_gaps.yml"

#: Opening tag of a block whose contents are markup, not prose.
_BLOCK_TAGS = ("script", "style", "nav", "header", "footer")
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


#: Magic numbers for binary formats a soft-404 may serve in place of a page. Connecticut and
#: Virginia Republicans both return a 426 KB PNG for /platform; without this check that binary
#: was decoded as "text" and passed to the confirmation stage as a 426,078-character document.
_BINARY_SIGNATURES = (
    b"\x89PNG", b"GIF8", b"\xff\xd8\xff", b"RIFF", b"\x00\x00\x01\x00",
    b"PK\x03\x04", b"\x1f\x8b", b"OggS", b"\x00\x00\x00 ftyp",
)


_BINARY_CONTENT_TYPES = ("image/", "video/", "audio/", "font/", "application/zip",
                         "application/octet-stream")


def _is_binary(body: bytes, content_type: str) -> bool:
    if content_type.startswith(_BINARY_CONTENT_TYPES):
        return True
    if any(body.startswith(signature) for signature in _BINARY_SIGNATURES):
        return True
    # A high proportion of NUL bytes in the head is the surest sign of binary content.
    head = body[:2048]
    return bool(head) and head.count(b"\x00") / len(head) > 0.05


#: Ligature glyphs that PDF text extraction returns as single characters, mapped back to the
#: letters they stand for.
#:
#: Two different problems land here. The U+FB0x block is *correct* Unicode -- a real "fi"
#: ligature -- but leaves "fulfill" spelled "fulﬁll", which no tokenizer, keyword list or
#: embedding will match. The rest are *wrong*: TeX-derived fonts routinely ship a broken
#: glyph-to-Unicode map, so a "ti" ligature arrives as U+019F and "Constitutions" reads
#: "ConsƟtuƟons". One Hawaii platform contained 484 of them, which is why it read as a
#: foreign-language document and was rejected.
_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\ufb05": "st", "\ufb06": "st",
    "\u019f": "ti", "\u019e": "tf", "\u01a9": "tt", "\u01ab": "tti",
}
_LIGATURE_RE = re.compile("|".join(map(re.escape, _LIGATURES)))

#: Private-use bullets from Symbol/Wingdings fonts, which carry no textual meaning.
_PRIVATE_USE_RE = re.compile(r"[\uf000-\uf8ff]")


def repair_ligatures(text: str) -> str:
    """Expand ligature glyphs back into their component letters.

    Applied to every extracted document, because a document that reaches the classifier with
    "ﬁrst" and "ConsƟtuƟons" in it is silently degraded rather than visibly broken.
    """
    if not text:
        return text
    return _PRIVATE_USE_RE.sub(" ", _LIGATURE_RE.sub(lambda m: _LIGATURES[m.group(0)], text))


def extract_text(body: bytes, content_type: str | None, url: str) -> str:
    """Extract plain text from an HTML or PDF response.

    Returns an empty string for binary content. A site that soft-404s by serving an image
    would otherwise have those bytes decoded as text and judged on length, which is how a
    426 KB PNG came to be treated as a candidate platform document.
    """
    normalized = (content_type or "").lower().split(";")[0].strip()
    is_pdf = normalized.startswith("application/pdf") or \
        url.lower().split("?")[0].endswith(".pdf") or body[:5] == b"%PDF-"
    if is_pdf:
        return repair_ligatures(_extract_pdf(body))
    if _is_binary(body, normalized):
        return ""
    html = body.decode("utf-8", errors="replace")
    html = strip_blocks(html, _BLOCK_TAGS)
    text = _TAG_RE.sub(" ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&amp;", "&", text)
    return repair_ligatures(
        re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip())


def _extract_pdf(body: bytes) -> str:
    """Extract text from a PDF, preferring the layout-aware mode.

    Some party PDFs embed fonts without usable word spacing, and pypdf's default mode then
    returns runs like ``SouthDakotaDemocraticPartyPlatform``. Layout mode reconstructs spacing
    from glyph positions and recovers most of them; :func:`confirm_platform` handles whatever
    is still mangled.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        try:
            pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
            text = "\n".join(pages)
            if _space_ratio(text) >= 0.08:
                return re.sub(r"[ \t]+", " ", text).strip()
        except Exception:  # noqa: BLE001 - layout mode is best-effort; fall back to plain
            pass
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception:  # noqa: BLE001 - a malformed PDF is a data condition, not a crash
        return ""
    return re.sub(r"[ \t]+", " ", "\n".join(pages)).strip()


def _space_ratio(text: str) -> float:
    """Fraction of characters that are spaces. Ordinary English prose sits near 0.16."""
    if not text:
        return 0.0
    return text.count(" ") / len(text)


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


#: Markers of a *national* party platform. State party sites routinely host the DNC/RNC
#: document, and it is far longer and more fluent than most state platforms, so it sails
#: through every other check. Three of the first 200 confirmed documents were national
#: platforms filed under a state.
_NATIONAL_MARKERS = (
    r"\b(?:democratic|republican)\s+national\s+convention\b",
    r"\bnational\s+platform\b",
    r"\bdemocratic\s+national\s+committee\b",
    r"\brepublican\s+national\s+committee\b",
)
_NATIONAL_RE = re.compile("|".join(_NATIONAL_MARKERS), re.I)


#: Apostrophe-like marks need two different treatments, and conflating them breaks one case or
#: the other. Deleting them all welds a possessive onto the name -- "Ohio's" becomes "Ohios",
#: so r"\bOhio\b" stops matching, which cost 140 of 201 documents at least one state-name hit.
#: Keeping them all leaves "Hawai'i" unable to match "Hawaii". Position decides which is which.
#: A mark *inside* a word that is not a possessive: the okina in "Hawai'i". Deleted, so the
#: name matches "Hawaii". The negative lookahead is what spares possessives -- "Ohio's" keeps
#: its apostrophe and so still ends the word "Ohio".
_INTRAWORD_MARK_RE = re.compile(r"(?<=[^\W\d_])['\u2018\u2019\u02bb\u02bc`\u00b4]"
                                r"(?!s\b)(?=[^\W\d_])")
_APOSTROPHE_RE = re.compile(r"[\u2018\u2019\u02bb\u02bc`\u00b4]")


def fold_for_name_match(text: str) -> str:
    """Fold text so a state name matches however the party chooses to spell it.

    Decomposes accents and drops the okina, so "Hawai'i", "Hawaii" and "HAWAI'I" all compare
    equal. Without this the Hawaii Republican Party's own platform was rejected for "never
    naming Hawaii" -- it names it on the title page, spelled correctly.

    Typographic apostrophes become a plain apostrophe rather than vanishing, so a possessive
    still terminates the word it follows.
    """
    marks_removed = _INTRAWORD_MARK_RE.sub("", text)
    decomposed = unicodedata.normalize("NFKD", _APOSTROPHE_RE.sub("'", marks_removed))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def dominant_state(text: str, state_name: str) -> tuple[int, str, int]:
    """How often the document names its own state, and the most-named *other* state.

    A state party platform is about one state. A national platform hosted on a state party's
    site enumerates many states and privileges none, which is exactly how the 2016 DNC platform
    -- 26,698 words, naming Hawaii once and Alaska ten times -- came to be filed as the Hawaii
    Democrats' own platform. Counting national slogans was not enough to catch it; comparing
    which state the document is actually *about* is.

    Returns ``(own_hits, rival_name, rival_hits)``.
    """
    folded = fold_for_name_match(text)
    own = len(re.findall(rf"\b{re.escape(fold_for_name_match(state_name))}\b", folded, re.I))
    rival_name, rival_hits = "", 0
    for other in STATE_NAMES:
        if other == state_name:
            continue
        # Skip names contained in the target, so "Virginia" is not counted inside
        # "West Virginia" and vice versa.
        if other in state_name or state_name in other:
            continue
        hits = len(re.findall(rf"\b{re.escape(fold_for_name_match(other))}\b", folded, re.I))
        if hits > rival_hits:
            rival_name, rival_hits = other, hits
    return own, rival_name, rival_hits


def confirm_platform(text: str, state_name: str | None = None) -> tuple[bool, str, int]:
    """Decide whether extracted text really is *this state's* party platform.

    Returns ``(confirmed, reason, phrase_hits)``. Three things must hold, and each was added
    because its absence let something wrong into the corpus:

    1. **Length.** A landing page that links to the platform is not the platform.
    2. **Declarative voice.** A party's news archive is long too, so the text must speak the
       way platforms speak ("we believe", "we oppose", "be it resolved"). Phrase counting
       falls back to a separator-free match for PDFs that lost their word spacing, which
       otherwise discarded real platforms of tens of thousands of characters.
    3. **State attribution.** The document must name its own state. Without this, the DNC and
       RNC national platforms -- which state parties host on their own sites, and which are
       longer and more fluent than most state platforms -- pass every other test and are
       silently attributed to a state party that did not write them.
    """
    if not text:
        return False, "no text could be extracted", 0

    hits = len(_PLATFORM_PHRASE_RE.findall(text))
    despaced = None
    if _space_ratio(text) < 0.08:
        # Folded first: the despaced form strips every non-ASCII character, so an accented
        # spelling would otherwise lose the letter entirely rather than being normalised.
        despaced = re.sub(r"[^0-9a-z]+", "", fold_for_name_match(text).lower())
        hits = max(hits, len(_DESPACED_PHRASE_RE.findall(despaced)))

    if len(text) < MIN_CHARS:
        return False, f"too short to be a platform ({len(text)} chars < {MIN_CHARS})", hits
    if hits < 3:
        return False, f"lacks platform language (only {hits} declarative phrases)", hits

    if state_name:
        folded = fold_for_name_match(text)
        folded_name = fold_for_name_match(state_name)
        state_hits = len(re.findall(rf"\b{re.escape(folded_name)}\b", folded, re.I))
        if state_hits == 0 and despaced is not None:
            state_hits = despaced.count(re.sub(r"[^a-z]", "", folded_name.lower()))
        national_hits = len(_NATIONAL_RE.findall(text))
        if state_hits < 2 and national_hits >= 2:
            return False, (
                f"reads as a national party platform hosted by a state party "
                f"({national_hits} national references vs {state_hits} mentions of "
                f"{state_name})"
            ), hits
        if state_hits == 0:
            return False, f"never names {state_name}; cannot attribute it to this state party", hits
        own, rival_name, rival_hits = dominant_state(text, state_name)
        if rival_hits > own:
            return False, (
                f"names {rival_name} more often than {state_name} "
                f"({rival_hits} vs {own}); this is not {state_name}'s own platform"
            ), hits

    return True, f"platform language confirmed ({hits} declarative phrases)", hits


def _fetch_once(candidate: Candidate, target: str, log, transport, timeout: float,
                max_attempts: int, backoff: float, sleep):
    return fetch(
        target,
        source_org=f"{candidate.state} state party ({candidate.party})",
        log=log,
        transport=transport,
        timeout=timeout,
        max_attempts=max_attempts,
        backoff=backoff,
        sleep=sleep,
        note=f"platform candidate {candidate.state}-{candidate.party}",
    )


def collect_candidate(
    candidate: Candidate,
    *,
    log: ProvenanceLog | None = None,
    transport=None,
    prefer_wayback: bool = True,
    timeout: float = 60.0,
    max_attempts: int = 4,
    backoff: float = 8.0,
    sleep=time.sleep,
    live_fallback: bool = True,
) -> CollectedDocument:
    """Fetch one candidate and decide whether it is a platform document.

    Retries are patient by design. Nearly every fetch here goes to a single host --
    web.archive.org -- and an earlier run at roughly one request per second had 305 of 456
    fetches refused with connection errors. That is both a politeness failure and a 66% data
    loss, so this backs off hard rather than treating a refusal as "document not available".

    The archived snapshot is preferred for reproducibility, but it is not always the better
    copy: the Massachusetts Democrats' platform page yields 1,743 characters from the capture
    the archive happened to take and 94,756 from the live page. So when the snapshot fails or
    comes back too thin to be a platform, the live URL is tried and whichever copy carries
    more text is used, with ``source`` recording which one won.
    """
    attempts: list[tuple[str, str, bytes | None, object]] = []

    if prefer_wayback and candidate.wayback_timestamp:
        target = wayback_snapshot_url(candidate.wayback_timestamp, candidate.url)
        body, record = _fetch_once(candidate, target, log, transport, timeout, max_attempts,
                                   backoff, sleep)
        attempts.append(("wayback", target, body, record))
        snapshot_text = extract_text(body, record.content_type, candidate.url) if body else ""
        if live_fallback and len(snapshot_text) < MIN_CHARS:
            if sleep and record.ok:
                sleep(1.0)
            body2, record2 = _fetch_once(candidate, candidate.url, log, transport, timeout,
                                         max_attempts, backoff, sleep)
            attempts.append(("live", candidate.url, body2, record2))
    else:
        body, record = _fetch_once(candidate, candidate.url, log, transport, timeout,
                                   max_attempts, backoff, sleep)
        attempts.append(("live", candidate.url, body, record))

    # Keep whichever copy yielded the most text; ties favour the archived one, which came
    # first and is the reproducible choice.
    best = max(
        attempts,
        key=lambda a: len(extract_text(a[2], a[3].content_type, candidate.url)) if a[2] else -1,
    )
    source, target, body, record = best

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
    state_name = STATE_NAMES_BY_CODE.get(candidate.state)
    confirmed, reason, hits = confirm_platform(text, state_name=state_name)
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
    """Fetch the credible candidates for one organization, best-scoring first.

    Documents are de-duplicated on their extracted text, not their URL. A party routinely
    serves the same platform from several paths -- a dated permalink, an ``archive.`` copy, a
    print view -- and counting each as a separate document would inflate the corpus in exactly
    the way the two Dataverse archives did. The duplicate is retained as an unconfirmed row so
    the double-count is visible rather than silently dropped.
    """
    ranked = sorted(
        (c for c in candidates if c.score >= min_score),
        key=lambda c: (-c.score, -(c.year_hint or 0)),
    )[:max_documents]

    collected: list[CollectedDocument] = []
    seen_text: dict[str, str] = {}
    for index, candidate in enumerate(ranked):
        document = collect_candidate(candidate, log=log, transport=transport, sleep=sleep)
        if document.confirmed:
            fingerprint = _text_fingerprint(document.text)
            first_url = seen_text.get(fingerprint)
            if first_url is not None:
                document.confirmed = False
                document.reason = f"duplicate of {first_url}"
                document.doc_type = None
                document.text = ""
            else:
                seen_text[fingerprint] = document.url
        collected.append(document)
        if delay and index < len(ranked) - 1:
            sleep(delay)
    return collected


def _text_fingerprint(text: str) -> str:
    """Hash of the document's normalized text, for duplicate detection."""
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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

    findings = load_gap_findings()
    rows = []
    for org in registry:
        key = (org["state"], org["party"])
        found = confirmed_by_org.get(key, [])
        gap = findings.get(key, {}) if not found else {}
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
            "gap_finding": gap.get("finding", ""),
            "gap_cause": gap.get("cause", ""),
            "gap_checked": gap.get("checked", ""),
        })
    return pd.DataFrame(rows)


def load_gap_findings(path: Path | str | None = None) -> dict[tuple[str, str], dict]:
    """Hand-checked explanations for why a party has no platform, keyed by (state, party).

    The pipeline can report that nothing was collected but not why, and the three reasons that
    matter - publishes nothing, site is broken, platform exists but needs a JS runtime - are
    not distinguishable from the outside. Those verdicts come from probing each site directly,
    so they live in version-controlled config and are joined in here. Keeping them in the
    generated CSV instead would delete them on the next run.
    """
    import yaml

    path = Path(path) if path else _GAP_FINDINGS_PATH
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        (state, party): entry
        for state, parties in raw.items()
        for party, entry in (parties or {}).items()
    }


def _load_candidates(path: Path, *, rescore: bool = True
                     ) -> dict[tuple[str, str], list[Candidate]]:
    """Load discovered candidates, recomputing each score by default.

    The stored score is a cache of a pure function of (url, mimetype), and collection filters
    on it. Trusting the cached value silently binds the fetch set to whichever scorer ran at
    discovery time: after the scorer was corrected, Hawaii's Republican platform PDF still
    carried its old score of 3, stayed below the strong threshold, and was never fetched --
    even though the very fix that admitted it had already shipped. Recomputing on load means a
    scorer change takes effect without re-crawling the discovery pass.
    """
    grouped: dict[tuple[str, str], list[Candidate]] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            candidate = Candidate(**json.loads(line))
            if rescore:
                score, reasons = score_candidate(candidate.url, candidate.mimetype)
                candidate = replace(candidate, score=score, reasons=reasons)
            grouped.setdefault((candidate.state, candidate.party), []).append(candidate)
    return grouped


def _load_previous(
    path: Path,
) -> tuple[dict[tuple[str, str], list[CollectedDocument]], set[str]]:
    """Load a previous run's rows, and the set of URLs whose fetch failed.

    Only fetch failures are retried. A document that was retrieved and judged not to be a
    platform is a settled result; re-requesting it would put load on third-party sites for no
    new information.
    """
    import pandas as pd

    frame = pd.read_parquet(path)
    grouped: dict[tuple[str, str], list[CollectedDocument]] = {}
    retry: set[str] = set()
    fields = set(CollectedDocument.__dataclass_fields__)
    for row in frame.to_dict("records"):
        document = CollectedDocument(**{k: v for k, v in row.items() if k in fields})
        if str(document.reason).startswith("fetch failed"):
            retry.add(document.url)
            continue
        grouped.setdefault((document.state, document.party), []).append(document)
    return grouped, retry


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
    parser.add_argument("--delay", type=float, default=2.5,
                        help="seconds between fetches; nearly all go to one host "
                             "(web.archive.org), so this is a politeness setting")
    parser.add_argument("--states", default="")
    parser.add_argument("--report-only", action="store_true",
                        help="rebuild the gap report from already-collected documents, "
                             "without fetching anything. Editing conf/platform_gaps.yml "
                             "should not require re-crawling 100 party websites.")
    parser.add_argument("--resume", action="store_true",
                        help="reuse an existing parquet and re-fetch only rows whose fetch "
                             "failed, rather than re-requesting documents already retrieved")
    args = parser.parse_args(argv)

    registry = yaml.safe_load(Path(args.registry).read_text(encoding="utf-8"))["organizations"]
    if args.states:
        wanted = {s.strip().upper() for s in args.states.split(",") if s.strip()}
        registry = [o for o in registry if o["state"] in wanted]

    grouped = _load_candidates(Path(args.candidates))
    log = ProvenanceLog(args.provenance)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    docs_path = out_dir / "platforms_2018_present.parquet"

    if args.report_only:
        if not docs_path.exists():
            print(f"nothing to report on: {docs_path} does not exist", flush=True)
            return 1
        documents = [d for docs in _load_previous(docs_path)[0].values() for d in docs]
        report = gap_report(registry, grouped, documents)
        report_path = out_dir / "platform_gap_report.csv"
        report.to_csv(report_path, index=False)
        explained = int((report["gap_finding"].fillna("") != "").sum())
        unexplained = int((report["n_confirmed"].eq(0)
                           & (report["gap_finding"].fillna("") == "")).sum())
        print(f"organizations with >=1 document: "
              f"{report['n_confirmed'].gt(0).sum()}/{len(registry)}")
        print(f"gaps with a hand-checked finding: {explained} "
              f"({unexplained} unexplained)")
        print(f"wrote {report_path}")
        return 0

    previous: dict[tuple[str, str], list[CollectedDocument]] = {}
    retry_urls: set[str] = set()
    if args.resume and docs_path.exists():
        previous, retry_urls = _load_previous(docs_path)
        print(f"resuming: {sum(len(v) for v in previous.values())} rows kept, "
              f"{len(retry_urls)} failed fetches to retry", flush=True)

    documents: list[CollectedDocument] = []
    # One open handle for the whole crawl: reopening the log per record costs ~11 ms, which
    # is irrelevant for a few downloads and ruinous across thousands of fetches.
    with log.session():
        for index, org in enumerate(registry, start=1):
            key = (org["state"], org["party"])
            candidates = grouped.get(key, [])
            if args.resume and previous:
                keep = [d for d in previous.get(key, []) if d.url not in retry_urls]
                candidates = [c for c in candidates if c.url in retry_urls]
                documents.extend(keep)
            collected = collect_for_org(
                candidates, min_score=args.min_score,
                max_documents=args.max_documents, log=log, delay=args.delay,
            )
            documents.extend(collected)
            confirmed = sum(1 for d in collected if d.confirmed)
            print(f"[{index:>3}/{len(registry)}] {org['state']}-{org['party']:<2} "
                  f"fetched={len(collected):<3} confirmed={confirmed}", flush=True)

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

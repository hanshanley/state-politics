# Implementation Plan — What Are the 50 State Democratic & Republican Parties Emphasizing?

**Repo:** `hanshanley/state-politics`
**Date:** 2026-07-28
**Status:** Phases 0–7 implemented

---

## 0. The question, restated

For **both** the Democratic and Republican parties, in **all 50 states**, measure what each *state-level* party
organization emphasizes and prioritizes, using two complementary evidence streams:

| Stream | What it captures | Actor |
|---|---|---|
| **A. Platforms / manifestos** | *Stated* priorities — what the party organization says it wants | State party committee (extra-governmental) |
| **B. State-level bills** | *Revealed* priorities — what the party's legislators actually file | Party caucus in the state legislature |

Explicitly **excludes** congressional bills. Both streams must run **up to the present (2026)** and cover **all 50 states**.

---

## 1. Feasibility findings (every source below was fetched and verified on 2026-07-28)

### 1.1 Platforms — a real corpus exists, but it **stops at 2017**

Verified by downloading the dataset and enumerating its contents:

- Dataset resolves (Dataverse API `200`), licensed **CC0 1.0**, latest version **3.0** released **2025-04-23**.
- Contains **3 files**: `05 for public.zip` (21.6 MB), `platform-update-04212025.zip` (22.2 MB), `file_changes_04232025KG.txt`.
- ⚠️ **The two zips are not additive.** `platform-update-04212025.zip` (2,091 documents) **supersedes**
  `05 for public.zip` (2,063 documents). The bundled changelog reconciles them exactly: its 49 listed
  additions appear only in the update, its 21 listed deletions only in the older archive, and 47 further
  overlapping files were revised in place. Unioning the archives inflates the corpus to a spurious 4,154
  "documents" — resurrecting deleted files and double-counting the rest. **Use the update archive alone.**
- Parsing the authoritative archive (`STATE-YEAR-PARTY[-flags].txt`):
  - **2,091** platform documents, **2,086** unique `(state, year, party)` observations
  - **49 states** (⚠️ **Maryland is absent entirely**) plus `US` for national platforms
  - **Year range 1840–2017**
  - Party tokens: **D = 1,066**, **R = 909**, plus Prohibition (16), Progressive (12), Socialist,
    People's, Libertarian, Green, Whig, Greenback, Nonpartisan League
  - Flag suffixes seen: `-B`, `-GG`, `-JS`, `-JD`, `-BP`, `-EA`, `-MG`, `-SM` (coder/source markers)
- **Answer to "is this up to the present?" → No.** Max year in the entire corpus is **2017**, and coverage is
  very uneven per state. Verified latest year per state/party includes large gaps:

| State | latest D | latest R | | State | latest D | latest R |
|---|---|---|---|---|---|---|
| **MD** | **none** | **none** | | NJ | **1996** | **1991** |
| KY | **1943** | 2008 | | OH | **1998** | 2000 |
| NY | **1958** | 2014 | | MO | **1995** | 2016 |
| PA | **1966** | 2006 | | FL | 2016 | **none** |
| IL | **2002** | 2016 | | LA | **none** | 2008 |

  Only 33 state codes have *any* D or R platform at 2016 or later, and five states (KY, LA, NJ, OH, PA)
  have nothing from either major party since before 2010. **Nothing after 2017 anywhere.**

> **Citation (original collectors, not the redistributor):**
> Hopkins, Daniel J.; Coffey, Daniel J.; Galvin, Daniel J.; Gamm, Gerald; Henderson, John; Paddock, Joel W.;
> Schickler, Eric (2022). *Select American State Party Platforms, 1846–2017* (V3.0, 2025-04-23) [Data set].
> Harvard Dataverse. https://doi.org/10.7910/DVN/KNOSHL. CC0 1.0. Accessed 2026-07-28.

**Consequence: a 2018–2026 platform corpus does not exist and must be built by this project.** This is the
single largest piece of original work in the plan.

### 1.2 Platforms 2018–2026 — collectable, feasibility proven

Two verified discovery mechanisms:

**(a) Internet Archive Wayback CDX API** — tested live, returns real platform documents:
```
https://web.archive.org/cdx/search/cdx?url=texasgop.org&matchType=domain
  &filter=original:.*[Pp]latform.*&filter=statuscode:200&collapse=urlkey&from=2023
```
returned, among others:
- `https://texasgop.org/2024-platform-and-legislative-priorities/` (captured 2024-06-08)
- `https://texasgop.org/2022platform/` (captured 2022-07-10)
- `https://www.iowagop.org/about/platform/`, `https://idahodems.org/2014-idaho-democratic-party-platform/`

> ⚠️ **Verified pitfall:** a naive `platform` substring filter is heavily polluted by Cloudflare
> `\*/cdn-cgi/challenge-platform/\*` URLs — these dominated results for `mngop.org`, `azgop.com`,
> `wisdems.org`, `michigandems.com`. **Must exclude `cdn-cgi` before anything else.**

> **Citation:** Internet Archive (2026). *Wayback Machine CDX Server API*. Internet Archive.
> https://web.archive.org/cdx/search/cdx. Accessed 2026-07-28.

**(b) Wikidata** — for the registry of the ~100 official party domains. Verified via SPARQL:
- Democratic side: `?p wdt:P31/wdt:P279* wd:Q7278 ; wdt:P17 wd:Q30 ; wdt:P131 ?state` →
  **all 50 states** have a Democratic state party entity with an official website (P856).
- Republican side: **the same query returns only 7 states** — GOP state party items largely
  **lack `P131` (located in administrative entity)**. A label-based query
  (`CONTAINS(?label,"Republican")` + `P17 = wd:Q30`) returns **81 entities, 54 with a P856 website**,
  including `Alabama Republican Party → algop.org`, `Arizona Republican Party → az.gop`,
  `Kansas Republican Party → kansas.gop`, `North Carolina Republican Party → nc.gop`, etc.
- **Implication:** Wikidata alone is *not* sufficient for the GOP registry. The registry needs
  name→state mapping plus **manual human verification of all 100 entries** (recorded with source URL
  + verification date). Third-party/committee items (`Erie County Republican Committee`,
  `California Republican Assembly`, `Greenville County Republican Party`) must be filtered out —
  they are county or auxiliary organizations, not the state committee.

> **Citation:** Wikidata contributors (2026). *Wikidata* [Knowledge base]. Wikimedia Foundation.
> https://query.wikidata.org/sparql. Accessed 2026-07-28.

### 1.3 Bills — fully solved, all 50 states, current to 2026

Verified against Open States / Plural Policy:

- **PostgreSQL public dump is genuinely public (no login):** `HEAD` on
  `https://data.openstates.org/postgres/monthly/2026-07-public.pgdump` → `HTTP 200`,
  `content-length: 10,711,908,617` (**10.7 GB**), `last-modified: 2026-07-01`. **Current to present.**
- **Legislator CSVs are public (no login)** — one per state, all 50 present:
  `https://data.openstates.org/people/current/{tx,ca,ny,...}.csv`. Confirmed the page is **not** login-gated.
  `Person` schema includes **`party`** — this is the join key that attaches partisanship to sponsorship.
- ⚠️ **Verified gotcha:** the per-session **CSV and JSON** archive pages *are* login-gated
  ("Please log in to access download links"). Plan around the pgdump + API v3, not those.
- **API v3** (`https://v3.openstates.org`) exposes `/bills`, `/people`, `/committees`, `/events`;
  `Bill` includes `subject`, `sponsorships`, `abstracts`, `versions`, `actions`;
  `BillSponsorship` includes **`primary`** and **`classification`** — enough to separate lead sponsors
  from cosigners.
- **All 50 states are covered.** An initial count suggested 12 missing states; on inspection those states
  simply use legislature-numbered session names rather than year-prefixed ones, e.g.
  `Alaska 33rd Legislature (2023-2024)`, `Texas 87th Legislature (2021)`,
  `Massachusetts 193rd Legislature (2023-2024)`, `Illinois 102nd Regular Session`.
  **Session-name parsing must not assume a leading year.** Sessions run through **2026** (and one 2027 VA entry).

> **Citation:** Open States / Plural Policy (2026). *Open States Bulk Data — 2026-07 public PostgreSQL dump
> and current legislator CSVs* [Data set]. Plural Policy. https://open.pluralpolicy.com/data/.
> Public domain dedication. Accessed 2026-07-28.

### 1.4 Verdict

| Requirement | Platforms | Bills |
|---|---|---|
| All 50 states | ✅ historical / ⚠️ must be built for 2018–26 | ✅ verified |
| Both parties | ✅ | ✅ (via sponsor party) |
| Up to the present (2026) | ❌ **gap 2018–2026 — this project must close it** | ✅ verified current |

---

## 2. Guiding constraints

1. **No fabricated or interpolated data.** Every platform document and every bill row traces to a fetched
   URL with an HTTP status, retrieval timestamp, and content hash. If a state party published no platform
   in a cycle, the observation is **omitted**, never imputed.
2. **Cite the collector, not the redistributor.** Bibliographic citations name the collecting
   organization/authors (see §1). A `CITATIONS.md` is a first-class deliverable.
3. **Absence is a finding.** "Ohio GOP has no public platform since 2000" is a legitimate result, not a bug.
4. **No hosted LLM APIs — all models run locally on the M4.** Classification, embedding and topic modeling
   run on Apple Silicon via MPS (16 GB unified memory), never through a paid or hosted inference endpoint.
   Rationale: a hosted model is an unversioned dependency, so a result that cannot be regenerated from
   pinned local weights is not reproducible. Enforced by `compute.audit_source_tree`, which scans the whole
   source tree for hosted-provider imports and endpoints and fails the test suite on any hit.
   The 16 GB budget bounds model choice: sentence-embedding models and small/medium quantized
   transformers fit; large unquantized models do not.
5. **Figures match the portfolio house style.** All charts use the shared "Substack" theme already used by
   `congressional_record` and `pre1870_reapportionment_package` — cream `#F7F5F0` ground, serif type, muted
   grid, tickless axes, borderless legend, bold title over a muted subtitle, italic source note,
   end-of-line series labels, `dpi=200`, `bbox_inches="tight"`; Democrats `#3D6F8C`, Republicans `#C85A3D`.
   The palette is pinned by tests so it cannot drift from the other repos.

---

## 3. Proposed repository layout

```
state-politics/
├── README.md
├── CITATIONS.md                 # bibliographic citations, collector-first
├── pyproject.toml
├── conf/
│   ├── party_registry.yml       # 100 state party orgs: state, party, domain, source_url, verified_on
│   └── topics.yml               # issue taxonomy + seed terms
├── src/state_politics/
│   ├── platforms/
│   │   ├── dataverse.py         # 1846–2017 corpus ingest
│   │   ├── registry.py          # Wikidata + manual verification -> party_registry.yml
│   │   ├── discover.py          # Wayback CDX + live-site candidate discovery
│   │   ├── fetch.py             # polite fetch, hash, provenance log
│   │   └── extract.py           # PDF/HTML -> text, plank segmentation
│   ├── bills/
│   │   ├── openstates_dump.py   # pgdump restore + extract
│   │   ├── people.py            # legislator CSVs -> sponsor party
│   │   └── sponsorship.py       # bill -> party-weighted attribution
│   ├── analysis/
│   │   ├── topics.py            # classification / topic modeling
│   │   ├── emphasis.py          # emphasis scores, salience, divergence
│   │   └── diffusion.py         # cross-state text reuse
│   └── provenance.py            # shared: URL, status, sha256, retrieved_at
├── data/                        # gitignored; all artifacts reproducible from code
└── tests/
```

---

## 4. Phased plan

### Phase 0 — Scaffolding (0.5 day)
- Init Python project, `pyproject.toml`, ruff + pytest, `.gitignore` for `data/`.
- Implement `provenance.py`: every fetch records `url, http_status, sha256, content_type, retrieved_at, source_org`.
- Seed `CITATIONS.md` with the four verified sources from §1.

**Done when:** `pytest` passes on a provenance round-trip test.

### Phase 1 — Historical platform corpus, 1846–2017 (1 day)
- Ingest from Dataverse by **numeric file id** (verified: `5746322`, `11106328`, changelog `11112198`).
  ⚠️ The `:persistentId` access pattern **404s** for these files — use `/api/access/datafile/{id}`.
- Treat **`platform-update-04212025.zip` (id `11106328`) as the authoritative archive**; the older
  `05 for public.zip` is superseded. Verify against the changelog rather than unioning.
- Parse `STATE-YEAR-PARTY[-flags].txt`; skip `__MACOSX/` and `._` AppleDouble entries (they are ~50% of names).
- Handle the single `.rtf` payload separately (`US-1916-Socialist-B-EA.rtf`); the "2" seen
  earlier came from counting the same file in both archives.
- Emit `platforms_historical.parquet` + a **per-state × party × year coverage matrix**.

**Done when:** 2,091 documents / 2,086 unique observations load; the coverage matrix reproduces the §1.1
gap table, including Maryland's total absence.

### Phase 2 — Party registry for all 100 organizations (1.5 days) ⭐ gating step — **DONE**
- Pull Democratic entities via the P131 query (50/50 verified).
- Pull Republican entities via the label query (81 entities / 54 websites verified), map name→state.
- Filter out county and auxiliary organizations.
- **Verify all 100 rows**; each gets `source_url` + `verified_on`.

**Outcome:** `conf/party_registry.yml`, 100 rows, **100/100 websites resolved, 92/100
machine-verified**. A row is trusted only when the live page's **visible text** identifies that
state's party. That check caught stale Wikidata URLs now resolving to unrelated commercial sites
(`migop.org` → `kiss918menang.com`, `negop.org` → `wildarms4.com`, `southdakotagop.com` → a
law-firm directory, `az.gop` → an image file), four dead hosts (`ctgop.org`, `indgop.org`,
`rigop.org`, `wsrp.org`), and six parties that have rebranded onto `.gop` domains (CO, DE, IL,
MO, SC, VA). Nineteen hand-checked corrections are recorded with their evidence. The remaining
eight rows are bot-protected (403), JavaScript-rendered, or — in Alaska's Republican case —
genuinely serving a suspended-account page.

> **Lessons carried into Phase 3:**
> 1. "Wikidata has a value" is not evidence the value is right. Any domain used for crawling must
>    be content-confirmed at fetch time, not trusted from a list.
> 2. A content check must run on **visible text with URLs and the site's own domain stripped**.
>    The first version matched raw HTML, so `alaskagop.org`'s "Account Suspended" page confirmed
>    itself via `webmaster@alaskagop.org` and was recorded as verified.
> 3. A redirect must never become the crawl target: keep the configured URL, record the
>    destination separately, and force review when the registrable domain changes.

### Phase 3 — Close the 2018–2026 platform gap (3–5 days) ⭐ the hard part — **DONE**
- Discovery (`platforms/discover.py`): Wayback CDX per domain + one live homepage scan, with
  candidates *scored* rather than filtered so rejections stay auditable.
- Collection (`platforms/collect.py`): fetches the credible candidates (preferring the archived
  snapshot via the `id_` modifier so the corpus is reproducible), extracts HTML/PDF text, and
  confirms each document against its own content.

**Current outcome:** **249 confirmed documents across 82/100 organizations and 46 states**:
233 are dated 2018+ across 80 organizations; 16 are older fallbacks excluded from current
comparisons. Every organization without any confirmed document was probed directly on ten likely
platform paths, so each gap carries an evidenced `gap_finding` and none is unexplained. Every organization gets an explicit status in
`platform_gap_report.csv` (`found` 76 / `candidates_rejected` 11 / `no_strong_candidates` 12 /
`no_candidates` 1).

> **Three bugs found and fixed here, all of the same family — a silent absence:**
> 1. **Cloudflare crowded out the real results.** `/cdn-cgi/challenge-platform/` contains the
>    word "platform", so on Cloudflare-fronted domains those URLs filled all 2,000 CDX rows and
>    pushed genuine documents out of the window. Excluding them *server-side* took the Minnesota
>    DFL from 0 candidates to 69. Filtering client-side is not enough.
> 2. **A failed query looked like an empty one.** Four organizations had their CDX request fail
>    with a network error or 504, and the code returned `[]` — indistinguishable from "this party
>    published nothing". Discovery now returns an explicit outcome carrying `searched` /
>    `wayback_ok`, and the CLI retries.
> 3. **Politeness failure destroyed two-thirds of the data.** Fetching at ~1 req/s against the
>    single host `web.archive.org` had 305 of 456 fetches refused. At 2.5s spacing with patient
>    backoff the success rate went from 34% to 93%, and confirmed documents from 72 to 197.
>
> Plus a data bug: some party PDFs embed fonts with no space glyphs, so a genuine
> 31,817-character South Dakota platform extracted as `SouthDakotaDemocraticPartyPlatform...`
> (space ratio 0.044 vs ~0.16) and scored **zero** declarative phrases. Fixed with pypdf layout
> mode plus a separator-free phrase fallback.

**Gap-filling pass (2026-07-29).** A second, wider search was run for every organization the
first pass found nothing for: :data:`SECONDARY_TERMS` (parties file platforms under `/issues` or
`/about/` as often as `/platform`) and :data:`DOMAIN_ALIASES` (a party that moved to a short
`.gop` address has all of its archived history under the old name). Then all 24 remaining gaps
were **probed directly** on ten likely platform paths.

Three more bugs surfaced, all of the same silent-corruption family:

1. **Wix mints thousands of synthetic sub-paths** under every real page — `/platform/0.45em`,
   `/platform/09-Icons-/-Social-/-Twitter`, media-hash JSON. Delaware Republicans alone produced
   **1,883**, swamping the one genuine `/platform` page. Now excluded by asset-pattern rules plus
   a general one: *a repeated path segment is the signature of a generated URL*, since no real
   document path repeats a segment.
2. **Seven Republican state sites soft-404 `/platform` with a 426 KB PNG**, and `extract_text`
   was decoding those bytes as text and offering the confirmation stage a "426,078-character
   document". It now rejects binary by signature and content type.
3. A **purely numeric trailing path segment** (`/platform/-0.88`) is a CSS value, not a document.

**Outcome of the gap pass:** every one of the 24 remaining gaps carries a directly-observed
finding, and **zero are unexplained**. The findings live in `conf/platform_gaps.yml` and are
joined into `platform_gap_report.csv` by `gap_report()`; they were previously hand-written into
the generated CSV, where the next pipeline run would have erased them. `collect --report-only`
rebuilds the report from cached documents so editing a finding costs no network traffic.

Categorised at the time of that phase: **18 publish no platform, 3 publish only a summary blurb, 1 site is suspended, 1
had candidates that did not confirm, and 1 is genuinely JavaScript-rendered.**

A follow-up re-check cut the JavaScript-rendered count from 3 to 1, which changes the
conclusion. Florida GOP's `/platform` does not render client-side at all — it soft-404s to the
site home page, and the party's own WordPress index lists 54 pages with no platform among them,
while a full-text search over pages, posts and media returns nothing. The Louisiana Democrats'
`/issues` is likewise an archive listing, and their WordPress index contains no platform page or
media file. Both are genuine absences. Only Hawaii's Democrats have a platform this pipeline
cannot reach: their Wix page manifest lists both `platform` and `platform-old`, but the text is
fetched client-side, and all 37 Wayback snapshots between 2021-10 and 2026-06 are the same empty
shell, so the archive cannot substitute for a renderer.

> **Lesson:** "static fetching cannot reach it" is a claim about the crawler and needs to be
> tested as carefully as any claim about the data. Queried directly, a site's own CMS index
> (`wp-json`, the Wix page manifest) settles whether a document exists far more definitively
> than guessing from a rendered page. Two of three assumed-blocked cases were actually the
> party publishing nothing — headless rendering would have recovered nothing and the effort
> would have been spent on a misdiagnosis.

### Phase 4 — State bills, all 50 states, to present — **DONE**

**Legislators:** `bills/people.py` — 7,359 current legislators, 50/50 states (R 4,045 / D 3,240 /
other 74) from Open States' public no-auth CSVs. Fusion-voting ballot lines
(`Democratic/Working Families`) resolve to the major party on the ticket; read literally they
matched nothing and stranded 119 legislators in `other`.

**Bills:** `bills/openstates_dump.py` + `bills/ingest.py` — **1,087,327 bills filed 2018–2026 in
all 50 states, 5,000,761 sponsorships**; attribution D 436,641 / R 376,436 / bipartisan 68,529 /
unknown 205,721.

Three obstacles, and how each was cleared:

| Obstacle | Resolution |
|---|---|
| Session CSV/JSON archives login-gated (403), API v3 needs a key | Used the public PostgreSQL dump, the only complete free route |
| Dump is 10.7 GB; machine had 32 GB free | Streamed to disk with incremental hashing, extracted selectively, deleted after — URL + SHA-256 remain in the provenance log |
| Dump is custom-format `PGDMP`, not SQL, and no PostgreSQL installed | `brew install libpq` for `pg_restore`, which streams one table to stdout — **no database restore needed** |

Party attribution uses **primary** sponsors; cosponsor lists are long, cross-party and
procedural, so letting them vote would blur the distinction the table exists to draw.
Unresolvable sponsors give `unknown`, never a guess. Congress and the territories are excluded
by `state_of()`, which admits only the 50 state jurisdiction ids.

### Phase 5 — Common issue taxonomy (2 days) — **DONE**
- `conf/topics.yml` holds 21 topics anchored to the Comparative Agendas Project major-topic
  codes, each with a prose description (what the local model embeds) and seed terms (what the
  transparent baseline uses). Rare topics — Defense, Foreign trade, International affairs — are
  retained deliberately: dropping them would push genuine foreign-policy planks into whichever
  domestic topic was nearest.
- `analysis/taxonomy.py` segments documents into planks and classifies them with a local
  sentence-transformer on MPS, plus a keyword baseline for comparison. No hosted inference.
- `analysis/validate.py` scores both against a hand-labelled gold set.

**Outcome:** embedding classifier **62% top-1 / 78% top-2**, keyword baseline 56% top-1, on 50
randomly-sampled hand-labelled planks (chance ≈ 5% on a 21-way task). The gold set is committed
at `data/gold/plank_topics_gold.csv` so a future taxonomy or model change can be re-scored
against identical labels.

> **Two segmentation bugs caught here, both producing confident nonsense:**
> 1. PDF **tables of contents** were being segmented into "planks" — each contents row survives
>    every length test while carrying no position at all, and the classifier assigned them
>    topics at similarities of 0.10–0.19.
> 2. A plank resembling **no** topic was pushed into whichever was least far away. Below a
>    similarity threshold it is now recorded as unclassified and excluded from the denominator.

### Phase 6 — Emphasis measures & comparisons — **DONE**

**Platform emphasis** (`analysis/emphasis.py`): share of planks per topic over 41,030 planks
from 898 documents (37,297 classified). Democrats emphasize labour, environment, housing, health,
social welfare; Republicans government operations (10.8% vs 7.1%), public lands, macroeconomics,
culture/family, law and crime.

**Stated vs revealed** (`analysis/revealed.py`): 542,508 party-attributed bills classified into
the same taxonomy and compared with platform emphasis. The headline finding is symmetric across
both parties — the topics that dominate *rhetoric* are largely national fights state
legislatures have limited power over, while the topics that dominate *filing* are the
bread-and-butter business of state government:

| Topic | D said | D filed | R said | R filed |
|---|---|---|---|---|
| Civil rights and liberties | 10.9% | 3.0% | 11.9% | 2.8% |
| Immigration | 4.6% | 0.9% | 5.6% | 0.9% |
| Law, crime and justice | 9.4% | 13.8% | 9.6% | 15.5% |
| Housing and community development | 3.3% | 9.4% | 1.1% | 6.0% |

Outputs: `emphasis_by_party.csv`, `emphasis_by_org.csv`, `bill_emphasis_by_party.csv`,
`bill_emphasis_by_state.csv`, `stated_vs_revealed.csv`, and figures `party_emphasis.png` and
`stated_vs_revealed.png`.

**Caveats carried with every number:** bills are classified from titles (shorter and noisier
than planks; the 62%/78% validation was measured on planks), ~20% of bills cannot be resolved to
a party and are excluded rather than guessed, and filing is not passing — this is agenda, not
achievement.



### Phase 7 — Outputs — **DONE**

- `analysis/profiles.py`: per-organization profiles (top platform topics, top filing topics,
  platform status) plus cross-state outliers measured as cosine distance from the state party's
  own national party average, within party, with a 30-observation floor.
- `Makefile`: `make setup / all / analysis / figures / test / lint`, with the network-heavy
  stages (`registry`, `platforms`, `bills-dump`) kept out of `all` so rebuilding the analysis
  never re-crawls third-party sites.
- Four figures in the shared portfolio style: `platform_corpus_recency.png`,
  `platform_coverage_2018_present.png`, `party_emphasis.png`, `stated_vs_revealed.png`.

> **One more silent-corruption bug caught here.** `emphasis_by_org.csv` is split by era and each
> era's shares already sum to 1, so pooling them by summing produced topic shares above 100%
> (Tennessee Democrats "110.8% law and crime"). Shares are now recomputed from raw counts.

## 5. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Many state parties simply never publish a platform (esp. 2018–26) | **High** | Report `confirmed-none` explicitly; lean on the bills stream for those states |
| Cloudflare / bot protection blocks live crawling | **High** (observed on `mngop.org`, `azgop.com`, `wisdems.org`, `michigandems.com`) | Wayback-first strategy; polite live fetch as fallback only |
| GOP registry incomplete on Wikidata (verified: only 7 states via P131) | **Medium** | Name-based query + mandatory manual verification of all 100 rows |
| 10.7 GB pgdump restore is heavy | **Medium** | One-time restore; or API v3 for targeted refreshes |
| Platform ≠ caucus agenda (party org and legislators can diverge) | **Medium** | This divergence is a *research finding*, not an error — measure it (Phase 6) |
| Comparing platform text share to bill counts is apples-to-oranges | **Medium** | Report within-stream ranks and rank correlation, not raw cross-stream ratios |

---

## Phase 8 — validating the bill classifier against statehouse subject tags

**Why:** every claim on the revealed-preference side rested on a classifier that had never been
measured on bill titles. The gold set validating the model is made entirely of platform planks,
and `conf/topics.yml` had noted since Phase 4 that the Open States `subject` tags "will map onto
the same scheme" — the check was always planned and never built.

**What:** `conf/subject_topic_map.yml` maps 181 unambiguous tags (of 88,716 distinct normalised
strings) onto the CAP topic codes, and `analysis/validate_bills.py` scores the classifier
against them. The mapping is written from tag names and the CAP codebook only — never from
classifier output, and deliberately not reusing the keyword seeds in `conf/topics.yml`, which
would have tested the seeds against themselves. Tags that name a procedure, a funding
instrument, a unit of government, or a regulated commodity are excluded, and bills whose tags
map to two topics are dropped rather than scored.

**Result:** 63.2% agreement on 46,659 bills across 35 states, against 62% for the same model on
planks. The aggregate was reassuring and the breakdown was not.

**The finding that mattered:** reporting *precision* rather than recall exposed one systematic
failure — **the classifier reads a tax bill by the thing being taxed rather than by the tax.**
Macroeconomics recall is 18.1%; those bills land in housing (property tax), public lands and
social welfare. Housing precision is 34.8%, with taxation the single largest contaminant.

Because the tags are model-independent, they re-derive the headline outright over 111,521
bills. **33 of 40 topic-party rows replicate; the housing row does not** — tag-labelled housing
is 3.0% (D) and 0.9% (R) against stated shares of 3.5% and 1.7%, erasing the gap and reversing
its sign for Republicans. The row was withdrawn from the headline table and struck through
rather than deleted, and the headline claim was rewritten from "housing, crime and
transportation" to "crime, transportation and education". The other five failures are the same
tax confusion or its mirror, except two where the gap is a fraction of a point and its sign is
noise.

> **Lessons:**
> 1. An aggregate accuracy figure can be reassuring and still conceal a claim-breaking error.
>    63.2% overall looked fine; one topic at 34.8% precision was carrying a headline row.
> 2. **Precision, not recall, is what licenses a share.** Every number in this project is a
>    share of items assigned to a topic, and recall says nothing about what was wrongly swept in.
> 3. Where a second, independent labelling exists, use it to re-derive the result rather than
>    merely to score the model. Scoring gives a number; replication gives a verdict per claim.
> 4. Validate the *thing you ship*. The model was validated on planks and deployed on titles,
>    and the gap between those two went unmeasured through seven phases.

---

## Phase 8b — exhaustive platform sweep

**Why:** discovery had only ever looked at URLs whose *path* contained a platform-ish keyword.
That is a guess about where parties put things, and it was wrong at least once: Hawaii's
Republican platform sat at `/documents/2024-HRP-Platform-Convention-Updates.pdf` and was found
but scored below threshold.

**What:** for each of the 21 remaining gap organizations, every archived PDF >= 25 KB on the
registry domain **and every known alias domain** was enumerated from the Wayback CDX API with
no path filtering at all -- 791 documents -- then fetched and run through `confirm_platform`.

**Result: 32 passed automated confirmation; hand review found 31 were false positives** --
newsletters ("Pennsylvania Republican", "The Insider", "Elephants Heard"), meeting minutes,
annual reports, a town-chairman manual, a shareholders' report and a campaign brochure. Exactly
one was a genuine policy document: the **Delaware Republican Party's "Rescue Delaware Plan"
(June 2022)**, 6,709 words, which closed the DE-R gap.

**That 1-in-791 rate is itself the finding.** It is the strongest evidence available that the
remaining gaps are real: these parties do not publish platforms, rather than publishing them
somewhere the crawler failed to look.

**Second-order fix.** 31 false positives out of 32 meant `confirm_platform` was too permissive,
so two rejections were added: a set of newsletter/minutes/report *furniture* markers ("Volume
II, Issue 1", "Non-Profit Org", "US Postage", "Inside this issue", "Minutes of the"), requiring
two or more before rejecting; and a filename rule, because a file called
`PADEMS-NEWSLETTER.pdf` or `2022-Bylaws-State.pdf` needs no text analysis. Together they reject
30 of the 32 sweep hits and **zero of the 250 documents already in the corpus**.

> **Lessons:**
> 1. A keyword-on-path filter encodes an assumption about other people's URL schemes. Enumerate
>    first, filter on content second.
> 2. When a confirmation rule is applied to candidates a *scorer* pre-filtered, the scorer is
>    silently doing much of the work. Removing the scorer exposed how weak the rule was alone.
> 3. A near-zero hit rate on an exhaustive search is a positive result, not a wasted afternoon:
>    it converts "we did not find one" into "there is not one".

---

## Phase 9 — intra-party comparison

**Why:** every earlier figure treats each party as a single actor. With 50 state organizations
per party that assumption is testable rather than necessary, and it is the question a 50-state
dataset is uniquely able to answer.

**What:** `analysis/intraparty.py` measures, separately for platforms and bills:
dispersion (mean pairwise cosine distance between a party's own state organizations),
divisive topics (cross-state SD of each topic's share), distance to the party centroid, and
**coherence** -- within-party distance against between-party distance.

Two guards are built in rather than left to the reader. Dispersion is only compared between
parties over the **same set of states**, because a party whose surviving platforms come from
more unusual states would otherwise look more divided for compositional reasons alone; that
restriction is what limits the current platform comparison to 18 states. And a permutation test
shuffles the party labels across the same vectors, so a dispersion gap is only reported as a
difference when it survives.

**Result:** the within/between ratio is **0.852 for platforms and 0.849 for bills** -- two
co-partisan state organizations are about 85% as far apart as two opposed ones, replicated
across two independent streams with different authors, sources and years.

**The permutation test earned its place immediately.** On the first pass, with only 12 states
qualifying, Republicans looked more scattered in platforms and Democrats in bills -- a tidy
reversal that would have been very quotable, and that shuffling the labels put squarely inside
chance (p = 0.41 and p = 0.30). Both were reported as null results.

With the corpus enlarged to 18 qualifying states the platform half became real and survives:
Republican state platforms are more internally varied than Democratic ones (0.319 vs 0.223,
p = 0.026). The bill half remains null (p = 0.30). So the finding is one-sided --
**Republican state committees write more varied platforms, while their legislators file
strikingly similar bills** -- which is a different and better-supported claim than the reversal
the first pass appeared to show.

Public lands is a top-three source of internal disagreement in three of four party-stream
comparisons and fourth for Republican platforms: geography still matters, because a Nevada
party of either stripe has a public-lands agenda and a Rhode Island one does not.

> **Lessons:**
> 1. A measure of "who differs from whom" needs a null model before it needs a chart. The most
>    interesting-looking result in this phase was noise, and only the permutation test said so.
> 2. Comparing dispersion across groups requires holding the group *composition* fixed. Two
>    parties with platforms in different states are not comparable on how divided they look.
> 3. Cosine over topic shares measures **agenda overlap, not agreement** -- two parties that
>    both spend 10% of their planks on abortion are adjacent on it. Stating that limit is the
>    difference between a finding and a misreading.

---

## Phase 10 — state focus atlas, election bills, and distinctive language

**Why:** national and intra-party dispersion figures establish that state parties differ, but
do not answer the practical lookup question: *what does this particular state's Democratic or
Republican organization focus on?*

**State focus atlas.** `analysis/state_focus.py` writes one row for every state × party pair.
The baseline is leave-one-state-out: a state is compared with the other states of its own party,
so it cannot pull its own comparison point toward itself. The atlas combines:

- current party-committee stated evidence where available;
- the separately labelled caucus supplement only where committee evidence is absent;
- classified bill-title shares for 98 partisan caucuses in 49 states;
- an explicit nonpartisan marker for Nebraska rather than invented D/R bill results.

**Election lens.** `analysis/elections.py` separates voting and election bills from the broad
Government Operations category. The high-precision title rule covers election administration,
voting access, campaign finance, redistricting, candidate/party rules and election security. It
scores 85.6% precision and 75.6% recall against legislature-assigned subject tags. Republican
caucuses devote 3.43% of filings to these bills, Democrats 3.05%; Tennessee Democrats (8.0%)
and Nevada Republicans (8.4%) are the strongest reliable same-party outliers.

**Language concentration.** `analysis/terms.py` computes both TF-IDF and a same-party log2
concentration score for unigrams and bigrams. +1 means twice the peer-state concentration; +2
means four times. State names, markup remnants, legislative boilerplate, ceremonial language
and dates are filtered from public highlights, while the raw scores remain available.

> **Lessons:**
> 1. A national party average is not a state profile. Use a leave-one-out same-party baseline
>    for claims about what makes a state distinctive.
> 2. A broad taxonomy can conceal a politically important subtopic. Elections needed a dedicated
>    lens rather than another interpretation of Government Operations.
> 3. Raw TF-IDF is as good at detecting drafting conventions as policy. The raw output should
>    remain auditable, but public highlights need transparent boilerplate filtering.
> 4. Missing evidence and zero emphasis are different. The atlas records missing stated sources
>    and Nebraska's nonpartisan legislature explicitly.

---

## 6. Assumptions made (autopilot; flag if wrong)

1. **Python** + pandas/parquet stack, since this is data collection and text analysis.
2. **50 states only** — DC and territories excluded by default (togglable).
3. **2018–2026** is the priority window; the 1846–2017 corpus is bonus historical depth.
4. Analysis unit is the **state party organization** (state committee), not county parties or auxiliaries.
5. Free/open sources only — **no LegiScan paid subscription** (Open States covers the need at no cost).
6. Deliverable is a **reproducible research repo**, not a web app.

## 7. Open questions

- Should **legislative priority agendas** and **convention resolutions** count as platforms, or be a separate
  document class? (Plan currently: separate `doc_type`, jointly analyzable.)
- Should third parties in the historical corpus (Prohibition, Progressive, Socialist, Green, Libertarian —
  116 documents) be retained? (Plan currently: ingest and retain, analyze D/R.)
- Preferred issue taxonomy — Comparative Agendas major topics, or a custom scheme?

---

## Appendix — verified source ledger

| # | Source | Verified | Access |
|---|---|---|---|
| 1 | Hopkins, Coffey, Galvin, Gamm, Henderson, Paddock & Schickler (2022), *Select American State Party Platforms, 1846–2017*, V3.0 2025-04-23, Harvard Dataverse, doi:10.7910/DVN/KNOSHL, CC0 1.0 | Downloaded; **2,091 docs** (update archive supersedes the older zip); 1840–2017; **49 states**, Maryland absent | `/api/access/datafile/{5746322,11106328,11112198}` |
| 2 | Open States / Plural Policy (2026), *Open States Bulk Data*, public domain | `HTTP 200`, 10.7 GB, modified 2026-07-01; 50 public legislator CSVs; all 50 states in session index | `data.openstates.org` |
| 3 | Open States API v3 | OpenAPI fetched; `Bill.sponsorships`, `Person.party` confirmed | `v3.openstates.org` |
| 4 | Internet Archive (2026), *Wayback CDX Server API* | Live query returned TX GOP 2024 & 2022 platforms, IA GOP, ID Dems | `web.archive.org/cdx/search/cdx` |
| 5 | Wikidata contributors (2026), *Wikidata* | 50/50 Dem parties w/ website; 54 Republican entities w/ website | `query.wikidata.org/sparql` |

Raw verification artifacts retained in this session folder: `kn.json`, `kn_summary.txt`, `file_changes.txt`,
`platforms_05.zip`, `platforms_update.zip`, `openstates_data.html`, `os_session_csv.html`,
`os_session_json.html`, `os_people.html`, `os_openapi.json`, `wd_parties.csv`, `wd_gop2.csv`.

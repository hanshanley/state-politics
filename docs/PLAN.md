# Implementation Plan — What Are the 50 State Democratic & Republican Parties Emphasizing?

**Repo:** `hanshanley/state-politics` (currently **empty** — greenfield; no code, no commits on disk)
**Date:** 2026-07-28
**Status:** plan — not yet implemented

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
  - Party tokens: **D = 1,066**, **R = 909**, plus Prohibition (16), Progressive (13), Socialist,
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
- Handle the 2 `.rtf` files separately.
- Emit `platforms_historical.parquet` + a **per-state × party × year coverage matrix**.

**Done when:** 2,091 documents / 2,086 unique observations load; the coverage matrix reproduces the §1.1
gap table, including Maryland's total absence.

### Phase 2 — Party registry for all 100 organizations (1.5 days) ⭐ gating step
- Pull Democratic entities via the P131 query (50/50 verified).
- Pull Republican entities via the label query (81 entities / 54 websites verified), map name→state.
- Filter out county and auxiliary organizations.
- **Human-verify all 100 rows**; each gets `source_url` + `verified_on`. Missing/dead domains resolved via
  Wayback and recorded as such.

**Done when:** `party_registry.yml` has exactly 100 verified rows (50 states × 2 parties), each with provenance.
Any state party that genuinely has no web presence is recorded with `domain: null` and a reason.

### Phase 3 — Close the 2018–2026 platform gap (3–5 days) ⭐ the hard part
- For each of the 100 domains, discover candidates from **two** channels:
  1. Wayback CDX, `from=2018`, `collapse=urlkey`, `statuscode:200`
  2. Live-site crawl of the current domain (robots-respecting, rate-limited, identifying UA)
- **Filter `cdn-cgi` first** (verified necessary), then keep URLs/PDFs matching
  `platform | principles | resolutions | legislative priorities | agenda`.
- Fetch → hash → extract text (PDF and HTML) → assign `(state, party, year, doc_type)`.
- Note that some parties publish **"legislative priorities"** rather than a platform
  (verified: `texasgop.org/2024-platform-and-legislative-priorities/`). Model `doc_type` explicitly so
  platforms and priority agendas are distinguishable but jointly analyzable.
- Produce a **gap report**: for each state × party × cycle, `found` / `confirmed-none` / `unresolved`.

**Done when:** every one of the 100 orgs has an explicit, evidenced status for 2018–2026. Target: recover
documents for a strong majority; **honestly report the rest as absent** rather than filling them in.

### Phase 4 — State bills, all 50 states, to present (2–3 days)
- Restore the **2026-07 public pgdump** (10.7 GB) locally; extract bills, sponsorships, subjects, versions, actions.
- Load the 50 public `people/current/{state}.csv` files for sponsor **party**.
- Join sponsorships → party; compute per-bill party attribution using `primary` and `classification`
  (lead sponsor vs cosponsor weighting; flag bipartisan bills).
- **Session parsing must not assume a leading year** (verified: Alaska/Texas/Massachusetts/Illinois naming).
- Restrict strictly to state legislatures; exclude the `us` jurisdiction (Congress) and, by default, territories
  (`pr`, `gu`, `vi`, `mp`, `as`, `dc`) — these exist in the source and would otherwise leak in.

**Done when:** bill counts by state × session × sponsor party reconcile against the Open States API v3
for a random sample of 10 states.

### Phase 5 — Common issue taxonomy (2 days)
- Define one taxonomy applied to **both** platforms and bills so the two streams are comparable.
- Anchor it to an existing scheme rather than inventing one (Comparative Agendas / Policy Agendas major
  topics is the natural anchor); map Open States `subject` tags onto it.
- Classify plank-level platform text and bill titles/abstracts **using local models only**
  (`select_device()` → `mps` on the M4): sentence-transformer embeddings + a scikit-learn classifier,
  or a small local transformer. No hosted inference at any point.
- Hold out a hand-labeled validation set and report accuracy. No unvalidated classifier output ships.

**Done when:** validation accuracy is reported per topic, the confusion matrix is committed, and the
run manifest records `describe_hardware()` so the compute environment is reproducible.

### Phase 6 — Emphasis measures & comparisons (2–3 days)
- **Emphasis score** per (state, party, cycle, topic): share of platform text, and share of sponsored bills.
- **Stated vs revealed divergence:** where does a state party's platform emphasis diverge from what its
  legislators actually file?
- **Cross-state within party:** which state Democratic/Republican parties are outliers from their national party?
- **Trend to present:** 2018–2026 movement, and — where the historical corpus permits — the long arc from 1846.
- **Diffusion:** near-duplicate plank/bill text across states (model legislation signature).

### Phase 7 — Outputs (1–2 days)
- `CITATIONS.md`, coverage matrices, and a reproducible end-to-end `make all`.
- Per-state two-page profiles; cross-state comparison tables; a written methods note that states the
  2018–2026 collection method and its limits plainly.

---

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
  ~150 documents) be retained? (Plan currently: ingest and retain, analyze D/R.)
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

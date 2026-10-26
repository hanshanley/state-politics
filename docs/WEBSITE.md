# Unpublished evidence companion

## Boundary and information architecture

The platform-only companion described below is built **only inside the ignored
`state-politics/data/` directory**,
normally `data/preview/` or a separately versioned recovery preview. It has no publication
route, card, navigation entry, sitemap/RSS entry or deployment staging. A future report and
separate publication approval are required before any integration into themarginoferror.com.
No report title, conclusions or publication date are assumed.

The separately tracked current graph exports live under `outputs/substack/`
and `outputs/themarginoferror/`; they are local preparation, not a registered
production companion. Open `outputs/index.html`, or build a fresh graph replay
using the reproducibility guide. Replays at nested output paths preserve working
links to methodology and the separately saved original evidence galleries.
Those local source archives remain prerequisites, not files automatically
copied into a future publication. Root and nested gallery navigation has been
verified independently; no publication route or approval gate is changed.

## Current saved 2023-2024 research handoff

Use the existing artifacts for design and inspection. Bulk acquisition,
inference and full-snapshot generation remain paused; the preserved platform
build commands below are not instructions to recreate the current workspace.

| Saved surface | Current contract |
|---|---|
| `outputs/index.html` | Local 27-chart gallery; 108 PNG/editable-SVG exports and 35 complete chart CSVs. See the [current collection](../outputs/README.md). |
| `outputs/current-graphs-manifest.json` | Pins the six saved table families, every full chart table and the actual exported bytes. Manifest SHA-256: `b89ad3fa5e3bad582f85899e88b6e8886fed2b6f35171240e942c5b619cddbaf`. |
| `outputs/classification-inspector-2023-2024-v8/` | Private original/majority inspector: 157,598 original contexts and 179,849 complete source alternatives. Manifest SHA-256: `1bc6cf4832681cc588303b1af61186bad2d7fa788fb38cba311e88ee7254d339`. The large bundle is local/Git-ignored, not supplied by cloning the code. |
| `outputs/substack/` and `outputs/themarginoferror/` | Matching data/geometry, with warm cream `#F7F5F0` and page grey `#F5F5F5` respectively. These are verified export backgrounds, not approval to copy assets into production. |

The manifest-declared chart payload is **18,089,904 bytes**, before the
manifest itself, a report or separately approved research archives. It is not
the full research dataset. A future release should stage an explicit approved
artifact allowlist, not recursively copy `data/`, `outputs/`, or the retained
preview/model versions.

Open the existing chart gallery directly. With the saved inspector bundle
present, this command serves it locally without generating another snapshot:

```bash
.venv/bin/python -I -B scripts/serve_research.py \
  --classifications outputs/classification-inspector-2023-2024-v8 \
  --port 8765
```

Do not expose predictions to model-blind annotators before their review.
Use the separate review-only workspace for annotation. The current inspector's
scientific, model-input, training, analytical, filing-time, publication and
party-attribution approval flags remain false. Serving an existing bundle or
verifying its hashes does not change those statuses.

The research gallery's relative methodology and evidence links have been
verified locally, including nested replays. **Do not publish its HTML
unchanged:** some destinations are ignored local bundles or repository-relative
documentation. A future approved companion must resolve those destinations
under its actual canonical base path and include only explicitly approved
assets. Missing private bundles must not become silent 404s or links implying
that cloning GitHub provides the complete research data.

Keep chart-table downloads distinct from complete classification-query
downloads. The latter must retain every matching original context, full input
and prediction, not a metadata-only or visible-page subset. Before exposing
them publicly, resolve redistribution rights for that exact release scope.
If a required complete download cannot be released, hold that surface behind
the release gate; do not relabel reduced metadata as complete evidence.

An author-supplied report and explicit artifact/publication approval remain
required. Independent classification evaluation, operative-platform/source
versions, filing-time party attribution and rights remain unresolved for their
respective analytical claims. Do not toggle research approval flags or infer
those approvals as a staging convenience. The [integration handoff](#integration-handoff-not-deployment)
below remains a design only: no production route, report card, navigation,
sitemap, RSS entry, production asset copy or deployment is created here.
Current replay/version details remain in the
[reproducibility guide](REPRODUCIBILITY.md#current-successor-literal-position-hyphen-evidence-v26).

## Preserved platform-only companion

The initial implementation leads with source coverage, not an unvalidated partisan ranking:

1. Evidence status and explicit unavailable classifier/bill/cutoff states.
2. All 100 state-party rows, with historical document counts, last archive year and unresolved
   operative-platform status. Nebraska's D/R bill comparison is not applicable.
3. State/party-filtered historical and optional bounded-recovery browsing, with original
   text, source attribution, explicit retrieval failures and separately typed OCR/DOCX alternatives.
4. Complete source/evidence downloads, input hashes and methodology caveats.

Warm paper (`#f2efe7`), ink (`#171713`), restrained red, serif headings and thin rules follow
the publication's understated visual language. The coverage table and downloads work
without JavaScript. Native controls, visible focus, table headers, live status messages and
paged evidence avoid hover-only interactions. Source text is inserted as text, not HTML.
Topic controls are visibly disabled until real, evaluated topic predictions exist.

## Build from saved evidence

```bash
uv run python -m state_politics.analysis.coverage \
  --sources-only --out data/processed/source_coverage.json
uv run python scripts/build_site.py
```

Equivalent target: `make preview`. The build does not crawl sites, train models or invent
replacement analytical values. It refuses mismatched organization/source counts.
Serve `data/preview/` with a local static server for interactive source partition loading;
the coverage table and downloads remain readable without that interactive loading.

To include an already frozen, reconciled recovery inventory:

```bash
uv run python scripts/build_site.py \
  --coverage data/processed/source-coverage-recovery-v8.json \
  --recovery data/processed/recovery-source-inventory-v7/inventory.json \
  --out data/preview-recovery-v8
```

The builder verifies the packet manifest, complete native/alternative text hashes, source
bindings, all 100 organization rows and aggregate counts before producing output. Schema v2
also verifies every retained raw body and byte count; older schema-v1 inventories remain
readable with their original manifest/text validation. It does not re-fetch sources or
resolve platform adoption. Failed requests and
byte-identical responses remain separate captures. Building again without `--recovery`
removes the known recovery partitions and downloads so stale evidence is not left exposed.

| Output | Contract |
|---|---|
| `index.html` | Static all-organization coverage table and research-status warning. |
| `evidence/{STATE}-{PARTY}.json` | Complete recovered historical records for one state-major-party organization; all 100 partitions exist, including empty arrays. |
| `downloads/historical_documents.jsonl.gz` | Complete recovered archive, including original text and historical national/non-major-party records excluded from the state-major-party table. |
| `downloads/source_coverage.json` | All 100 source-ledger rows; unknown current coverage remains unresolved. |
| `downloads/build_manifest.json` | Schema version, unpublished/uncertified status, source and template hashes, record counts and uncertified analytical cutoff. |
| `evidence/recovery-{STATE}-{PARTY}.json` | Optional complete capture records, including unsuccessful requests and separately source-bound OCR/DOCX alternatives; all 100 partitions exist when enabled. |
| `downloads/recovery_captures.jsonl.gz` | Optional byte-preserving complete frozen capture stream, not deduplicated or reduced to accepted extractions. |
| `downloads/recovery_inventory.json` | Original bounded inventory, all 100 organization rows and its unresolved version/admission statuses. |
| `downloads/recovery_inventory_manifest.json` | Original packet manifest. Its paths and file hashes describe the research packet, not renamed/compressed website outputs; compare decompressed capture bytes and the original inventory bytes. |

The JSONL download is actual source data, not a metadata-only substitute. The browser
loads one state's partitions lazily and pages ten documents at a time; this is a display
limit, not a truncated research download. Public redistribution permissions remain a
release gate.

Chromium checks have exercised filtering, pagination, exact source text, keyboard focus,
375px mobile overflow, failed requests, stale-response races and no-JavaScript access.
The downloaded gzip was decompressed and matched byte-for-byte to the complete recovered
JSONL. `data/processed/preview_browser_validation.json` identifies the tested build hash.
This validates interface behavior, not classifications, scientific findings or publication.

The current recovery build exposes **1,559 capture records, 1,440 retained responses,
119 failures and 1,371 distinct body hashes across all 100 organizations**. The recovered
Arizona platform, Illinois short statement, Oklahoma platform and administrative rules are
not interchangeable source types or certified adopted policy. The 1,440 retained responses
are not 1,440 verified platforms.
Fifty-five bodies have OCR alternatives; three have separately typed DOCX main-document text.
There are 57 OCR extraction identities because repeated source bytes can retain multiple
separate extraction records, plus three DOCX alternatives: 60 total identities.
All 1,503 prior native records and prior alternatives are preserved. The three older Hawaii
volumes now have reproduced OCR across 663 pages, with 62 empty primary-OCR pages and
explicitly unresolved cover transcription. The separately retained image-only Massachusetts
resolution has OCR but no native text; its empty native field is not a missing response.

Recorded OCR runtime versions are displayed per extraction, including historical 5.5.3
where retained on the row; missing row-level runtime metadata is explicit, not replaced
with the current executable's version. The Montana incomplete-font warning is visible
despite nonempty native text. OCR remains uncertified and does not preserve map geometry
or spatial ballot-selection marks. DOCX is not labelled OCR.

`data/processed/recovery-preview-browser-check-v9/` binds the exact build/capture hashes,
screenshots and checker. Chromium reconciled all 100 partitions, all 60 extraction identities,
all 119 failures and complete byte-exact recovery/historical gzip streams. The refreshed
source ledger includes the corrected Arizona and Alaska homepages and verification dates.
Preview v8 retains inventory v7 unchanged. Its source-only ledger does not consume the
collector's gap-observation catalogue; all 100 operative-platform statuses remain unresolved
after the separate retirement of unsupported legacy absence claims.
The image-only resolution has explicit empty-native disclosure and separate OCR. It also covers
runtime/warning disclosures, keyboard/mobile/no-JavaScript behavior, literal markup and
HTTP/race handling. The zero-capture edge case uses a synthetic empty partition because
all real organizations now have requests. Neither this check nor a retained homepage
certifies source role, current platform coverage, adoption or analytical eligibility.

The current successor is reproducible from saved packets:

```bash
uv run python scripts/build_recovery_inventory.py \
  --baseline data/processed/recovery-source-inventory-v6/inventory.json \
  --captures data/processed/stale-gap-primary-source-recovery-v1/captures.jsonl \
  --captures data/processed/ma-image-resolution-recovery-v1/captures.jsonl \
  --ocr data/processed/deferred-historical-hawaii-ocr-v1/extractions.jsonl \
  --ocr data/processed/stale-gap-primary-source-pinned-ocr-v1/extractions.jsonl \
  --ocr data/processed/ma-image-resolution-recovery-v1/extractions.jsonl \
  --out data/processed/recovery-source-inventory-v7

uv run python -m state_politics.analysis.coverage --sources-only \
  --out data/processed/source-coverage-recovery-v7.json
```

Use a fresh version path when the output already exists. Previously retained alternatives
are reused for repeated source bytes within the same state-party organization row, not
across state-party rows, and conflicting extraction identities fail before output. This
does not adjudicate the underlying document's institution. Raw data remains
local/Git-ignored; pushing documentation does not remotely back it up.

### Preserved earlier recovery build

The earlier v4 inventory / preview v3 exposes 488 capture records, 469 retained responses, 19 failures
and 460 distinct body hashes across 55 organizations. The other 45 organization rows are
not evidenced policy absences. This remains a selected union, not the full recovery campaign
or 469 verified platforms. Seven bodies have OCR alternatives and two have DOCX
main-document text; DOCX alternatives exclude layout, images and other XML parts and must
not be labelled OCR. Native extraction remains separate, including empty/null failures.
Chromium checked every partition, all nine alternative bodies, all 19 failures, pagination,
390px overflow, zero-capture disclosures, collection-switch races, legacy OCR compatibility
and literal script/image markup in all three text surfaces. The corresponding local packet
is `data/processed/recovery-preview-browser-check-v4/`; its manifest freezes the checker,
screenshots and results bound to the exact build/capture-stream hashes. Earlier preview
and verification packets remain unchanged. Inventory v3 is superseded because it normalized
empty failed-native strings to null; v4 preserves every baseline native field exactly.

The successor was produced with the command below. Completed inventory directories refuse
overwrite; use a fresh version path for another run rather than modifying an old packet.

```bash
uv run python scripts/build_recovery_inventory.py \
  --baseline data/processed/recovery-source-inventory-v2/inventory.json \
  --captures data/processed/nm-embedded-core-values-recovery-v1/captures.jsonl \
  --captures data/processed/nm-platform-version-followup-v1/captures.jsonl \
  --captures data/processed/nm-linked-policy-recovery-v1/captures.jsonl \
  --captures data/processed/fl-embedded-resolution-recovery-v1/captures.jsonl \
  --captures data/processed/discovery-reference-followup-v1/captures.jsonl \
  --captures data/processed/four-state-primary-source-followup-v1/captures.jsonl \
  --captures data/processed/four-state-public-download-followup-v1/captures.jsonl \
  --captures data/processed/institutional-index-followup-v1/captures.jsonl \
  --ocr data/processed/four-state-scan-ocr-v1/extractions.jsonl \
  --docx data/processed/recovered-docx-alternate-extraction-v1/extractions.jsonl \
  --out data/processed/recovery-source-inventory-v4
```

## Future analytical contract

Once audit gates pass, add versioned aggregates and evidence partitions tied to the same
canonical predictions. Required record fields include source/record ID, source hash and text,
institution/document type, adoption/session/evidence dates, input tier, model/taxonomy/run
identity, one topic or null, runner-up diagnostic, score type, abstention reason and
chunk/source spans. Downloads must include every contributing/excluded row, denominators,
codebook and manifests, not just chart metadata.

Add period/session/topic/source controls only when those dimensions have audited values.
Show classified-only shares beside eligible/classified/abstained counts. Missing values
are not zeros. Latest operative platforms and pooled modern documents are separate views;
party committees and legislative caucuses stay distinguishable. Filing attention,
recorded outcomes and voting are different lenses.

## Integration handoff, not deployment

The publication's `PUBLISHING.md` and `src/styles/global.css` were inspected locally.
The following is a design, not authorization or an implemented publication change.
The existing UK/congressional staging examples are references, not a reason to enable
automatic refresh of this project's uncertified data.

| Surface | Proposed boundary |
|---|---|
| Project companion | A standalone static bundle at a future approved subpath; `/state-politics/` is only a candidate, not a registered route. Keep source coverage, source text and complete downloads ahead of analytical summaries. |
| Report | Author-supplied article, title, subtitle, figures and date. Link its artifact fields to the frozen companion and code; do not generate a substitute report or duplicate the dashboard inside an article iframe. |
| Visual shell | Preserve paper/ink typography, thin rules, modest red accents and the publication's navigation conventions. Use red for notices, not as an unexplained party/metric encoding. No decorative arrows, giant metric cards or unsupported rankings. |
| Artifact staging | Only an explicitly approved release pinned to a research commit and artifact manifest. Verify hashes, schema, counts and certification before copying. Generated local `data/` bytes are ignored and are not backed up or delivered merely by pushing code. |
| Build/deployment | Static rendering only. No crawling, OCR, model training or live inference. Missing/incompatible artifacts fail the build; do not substitute legacy or provisional predictions. Preserve existing projects and navigation. |
| Publication discovery | Add a report/analysis card, canonical URLs and intentional analysis-count assertions only after approval. Coordinate any shared navigation changes with the existing standalone project generators. |
| Personal index | Follow the publication runbook only after the approved canonical article is live. No draft link or speculative article entry. |

The release packet must bind the original evidence inventory and raw-source references,
full normalized texts, source-version dispositions, classifier checkpoint/tokenizer,
taxonomy/rubric, exact predictions, analytical denominators, exclusions, uncertainty,
chart data and website-output hashes. Preserve the distinction between research-packet
hashes and renamed/compressed web downloads. Confirm redistribution permissions before
shipping source text or PDFs; hash retention alone is not permission.

Before release, every organization needs an approved dated disposition: an evidenced
operative version, or a documented unresolved/unavailable status under the same search
standard. A failed request or no selected capture cannot establish publication absence.
Set an evidence-based analytical cutoff; retain historical, modern pooled, operative
platform and caucus evidence as separate strata. Resolve historical bill affiliations and
filing-time eligibility before comparisons. Finalize topic boundaries and representative
independent target evaluation before certifying a model; neither current pilot is approved.
Do not choose gates after seeing test outcomes or conceal abstentions in denominators.

After separate report/artifact approval, validate exact displayed/downloaded totals,
full-source availability, keyboard controls, request errors/races, no-JavaScript fallback,
390px/1360px layout, navigation and canonical routes. Run the publication's existing checks
and match the deployed commit to the release; its current push-triggered workflow means
an experimental `main` push there is not a harmless preview. None of those production
changes, routes, assets, navigation entries or deployment operations are made here.

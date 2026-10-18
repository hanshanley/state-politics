# Unpublished evidence companion

## Boundary and information architecture

The companion is built **only inside the ignored `state-politics/data/` directory**,
normally `data/preview/` or a separately versioned recovery preview. It has no publication
route, card, navigation entry, sitemap/RSS entry or deployment staging. A future report and
separate publication approval are required before any integration into themarginoferror.com.
No report title, conclusions or publication date are assumed.

The initial implementation leads with source coverage, not an unvalidated partisan ranking:

1. Evidence status and explicit unavailable classifier/bill/cutoff states.
2. All 100 state-party rows, with historical document counts, last archive year and unresolved
   operative-platform status. Nebraska's D/R bill comparison is not applicable.
3. State/party-filtered historical and optional bounded-recovery browsing, with original
   text, source attribution, explicit retrieval failures and separately labelled alternate OCR.
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
  --coverage data/processed/source_coverage.json \
  --recovery data/processed/recovery-source-inventory-v2/inventory.json \
  --out data/preview-recovery-v1
```

The builder verifies the packet manifest, complete text/OCR hashes, source bindings, all
100 organization rows and aggregate counts before producing output. It does not re-fetch
sources, reverify every original raw body or resolve platform adoption. Failed requests and
byte-identical responses remain separate captures. Building again without `--recovery`
removes the known recovery partitions and downloads so stale evidence is not left exposed.

| Output | Contract |
|---|---|
| `index.html` | Static all-organization coverage table and research-status warning. |
| `evidence/{STATE}-{PARTY}.json` | Complete recovered historical records for one state-major-party organization; all 100 partitions exist, including empty arrays. |
| `downloads/historical_documents.jsonl.gz` | Complete recovered archive, including original text and historical national/non-major-party records excluded from the state-major-party table. |
| `downloads/source_coverage.json` | All 100 source-ledger rows; unknown current coverage remains unresolved. |
| `downloads/build_manifest.json` | Schema version, unpublished/uncertified status, source and template hashes, record counts and uncertified analytical cutoff. |
| `evidence/recovery-{STATE}-{PARTY}.json` | Optional complete capture records, including unsuccessful requests and separately source-bound alternate OCR; all 100 partitions exist when enabled. |
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

The recovery build separately exposes 309 attempts, 299 retained responses and 296 distinct
body hashes. Its packet is a selected union, not the full recovery campaign or 299 verified
platforms. Chromium checks additionally exercise recovery pagination, null-text failures,
complete alternate OCR, 390px overflow, zero-capture disclosures, collection-switch races
and literal rendering of synthetic script/image markup. The corresponding local check
packet is `data/processed/recovery-preview-browser-check-v2/`; its manifest freezes the
checker, screenshots and result bound to the exact build/capture-stream hashes. This does
not replace the historical-only validation packet.

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

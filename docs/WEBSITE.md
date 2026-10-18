# Unpublished evidence companion

## Boundary and information architecture

The companion is built **only inside `state-politics/data/preview/`**. It has no publication
route, card, navigation entry, sitemap/RSS entry or deployment staging. A future report and
separate publication approval are required before any integration into themarginoferror.com.
No report title, conclusions or publication date are assumed.

The initial implementation leads with source coverage, not an unvalidated partisan ranking:

1. Evidence status and explicit unavailable classifier/bill/cutoff states.
2. All 100 state-party rows, with historical document counts, last archive year and unresolved
   operative-platform status. Nebraska's D/R bill comparison is not applicable.
3. State/party-filtered historical source browsing, with original text and archive attribution.
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

| Output | Contract |
|---|---|
| `index.html` | Static all-organization coverage table and research-status warning. |
| `evidence/{STATE}-{PARTY}.json` | Complete recovered historical records for one state-major-party organization; all 100 partitions exist, including empty arrays. |
| `downloads/historical_documents.jsonl.gz` | Complete recovered archive, including original text and historical national/non-major-party records excluded from the state-major-party table. |
| `downloads/source_coverage.json` | All 100 source-ledger rows; unknown current coverage remains unresolved. |
| `downloads/build_manifest.json` | Schema version, unpublished/uncertified status, source and template hashes, record counts and uncertified analytical cutoff. |

The JSONL download is actual source data, not a metadata-only substitute. The browser
loads one state's partitions lazily and pages ten documents at a time; this is a display
limit, not a truncated research download. Public redistribution permissions remain a
release gate.

Chromium checks have exercised filtering, pagination, exact source text, keyboard focus,
375px mobile overflow, failed requests, stale-response races and no-JavaScript access.
The downloaded gzip was decompressed and matched byte-for-byte to the complete recovered
JSONL. `data/processed/preview_browser_validation.json` identifies the tested build hash.
This validates interface behavior, not classifications, scientific findings or publication.

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

After the report and artifact receive explicit approval, choose the final project subpath;
stage only the frozen certified bundle in the publication workflow; add a report/analysis
card and canonical URLs; intentionally update the existing analysis-count build check;
then validate navigation, sitemap, accessibility and displayed/downloaded totals.
Deployment must fail on missing or incompatible artifacts, never run training/crawling or
silently substitute provisional results. None of those production changes are made here.

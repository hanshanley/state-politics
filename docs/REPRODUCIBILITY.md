# Reproducibility and traceability

This repository separates **authored inputs**, **primary-source collections**, and **generated
artifacts**. Nothing is described as reproducible merely because a final CSV exists.

**Current status:** the historical analytical results are under audit, not certified.
See [AUDIT_STATUS.md](AUDIT_STATUS.md). Run `scripts/audit_reproducibility.py --inventory-only`
to persist missing prerequisites without attempting data-dependent scientific checks.
Failures still produce a nonzero exit and a report. Dependency hashes were deliberately
updated for the ModernBERT migration; the unchanged legacy analysis parameters describe
the old baseline, not a newly trained model.

The active study is limited to **2023–2024** and platforms applicable during that
cycle. Wider retained corpora, historical training data and old audit reports
remain unchanged. Broad rebuild commands below are not a request to complete
other years; target-cycle selection and its inclusion/exclusion provenance must
be bound explicitly before regenerated outputs can support the narrowed study.

## Separate 2023–2024 source-date ledger

```bash
.venv/bin/python -I -B -m state_politics.bills.study_window \
  --data-dir data/processed \
  --out-dir data/processed/study-window-2023-2024-v2
```

The completed local execution uses the directory above. Choose a **new directory**
for another execution; existing outputs are never overwritten. The earlier v1
is preserved; v2 adds exact native session IDs to grouped counts and explicitly
discloses that proposed bills/draft requests are not automatically eligible.
This command reads the wider extraction, not a previously filtered cycle dataset.
It verifies the extraction manifest's Parquet hashes/row counts, records full
input/code hashes and seven stat fields, and rechecks them before completion.
A failed build leaves an explicitly incomplete manifest.

Outputs are `bill_window_ledger.csv` (every retained bill-context row and its
date disposition), `source_introduction_actions.parquet` (complete raw rows
with an exact introduction classification token), `state_session_counts.csv`,
`report.json` and the hash-bound `manifest.json`. Record and grouped exports
preserve native session IDs, session metadata, chamber and measure type.

A usable source-date observation requires exactly one introduction action
matching the bill's originating organization and known chamber. Duplicate
origin introductions remain unresolved even on the same date. Other-chamber
introductions stay in the evidence export, not new originating filings.
First/latest actions, session years, URL dates and filenames never supply an
introduction date. Complete ISO event strings are validated, retaining their
source-local calendar day rather than converting time zones.

The actual run accounts for all **1,090,369 contexts**, **760,947 raw introduction
actions** and **4,162 state/session/type/disposition groups**. Only **130,803**
contexts have unambiguous source-coded introductions inside the window.
These are source observations, **not a certified filing population**: native
verification, prefiling/carryover interpretation, original-version eligibility,
formal-measure selection and party timing remain separate gates. Wider-history
unresolved contexts are not automatically target-cycle gaps or exclusions.
No canonical table, label, model, platform selection or analytical output changes.

The local completed manifest SHA-256 is
`d19544a98d8b1ce29da414970d445a9da111ede5b8cbe3de53af50639012dfc1`.
The separate session verifier `verify_study_window_actual_v2.py` compares all
original bill fields, every raw introduction action, originating-event joins,
date dispositions and persisted aggregate counts; its receipt is
`study_window_2023_2024_verified_v2.json`. Generated evidence remains Git-ignored
and local-only; committing this documentation does not back up those files.

## Shared 50-state matrix and gap queue

```bash
.venv/bin/python -I -B -m state_politics.bills.study_matrix \
  --window-dir data/processed/study-window-2023-2024-v2 \
  --reference-dir data/processed/bill-document-reference-inventory-v4 \
  --tracker docs/STATE_PROGRESS.md \
  --out-dir data/processed/study-matrix-2023-2024-v1
```

This is the common offline baseline for all 50 states, replacing repeated
state-by-state date/reference audits. It binds both source manifests to the
same extraction, checks exact bill/state/identifier/session identities and
requires exactly the state registry's 50 unique tracker entries. Inputs and
producer hashes/stat fields must remain unchanged during execution.

The output contains `state_matrix.csv`, `state_session_chamber_counts.csv`,
`gap_queue.csv`, `report.json` and a completed/incomplete `manifest.json`.
Existing output directories are refused. The matrix preserves reviewed scope,
evidence and next gaps; the queue excludes Closed scope states and explicitly
separates blocked work from collection. Queue sorting is alphabetical within
action, not an impact or completeness ranking. Zero observed introduction dates
means missing qualifying date evidence, not zero legislative activity.
Unresolved-date counts span retained wider history; they are not target-cycle
missing-filing counts. Links are not recovered original texts. Native-cycle
denominators and recovered-cycle-text counts are null because this join does
not reconcile the state-native packets. No collection, classifier execution,
platform approval or analytical admission is performed.

The committed tracker remains the single reviewed source for dispatch status;
the generated matrix is a hash-bound snapshot, not a second editable status
registry. Rerun into a new output directory after changing that tracker or its
bound inputs. Generated packets remain local/Git-ignored, not backed up by a
code/documentation push.

The actual v1 run contains 50 matrix rows, 44 gap entries and 4,162 detailed
groups. Manifest SHA-256:
`666cef19585cba7c2f980ca9503ea479303bd3005ef367c12a4685f3abff8732`.
All detailed context counts match the previously accepted source-window
group export; wider-history context/reference totals are 1,090,369/2,617,690.

## Shared accepted-native-packet overlap

```bash
.venv/bin/python -I -B -m state_politics.bills.study_native_overlap \
  --matrix-dir data/processed/study-matrix-2023-2024-v1 \
  --registry conf/study_native_packets.yml \
  --out-dir data/processed/study-native-overlap-2023-2024-v9
```

The registry pins nine previously accepted input manifests covering CA, CO,
NC, OH, SD, WI, TX and FL. It selects the California 2023–2024 packet **and** the wider
archive: the latter contains source-dated 2024 prefilings in a 2025–2026
session, which cannot be excluded by session-name substring. Source dates
still come only from the existing national ledger.

Three shared profiles normalize single-source inputs, separate context/view
tables and paired-reader rows. Exact bill-ID/session/typed-identifier agreement
or a unique explicitly declared session/typed-identifier join is required.
California native special-session codes have an explicit registry crosswalk
to canonical session keys. This is an identity crosswalk, not a source of dates.
Unmapped source-only contexts remain unmatched; no HJR/HR/HB aliases or
ambiguous joins are guessed. NC's two identity-unresolved inputs stay marked.
Texas `88R` maps explicitly to canonical `88`; its original native key survives.
Its unavailable HB1 shell is retained as a context with zero input views.

Outputs are `native_context_overlap.parquet`, `native_view_index.parquet`,
`missing_supplied_native_text.parquet`, `native_introduction_observations.parquet`,
`date_resolution_queue.parquet`, the enriched `state_matrix.csv`,
`report.json` and `manifest.json`. The view index is an index, not a text
download: complete original strings remain in the bound input tables.
Alternative readers never count as additional measures. Unregistered states
retain null packet counts rather than zero recovery.

The actual v9 manifest is
`5e145ead121a3b5610531bc23750c1ece202bf4adc896f9b89d060b18784f51e`.
It indexes 43,480 wider-scope native contexts and 59,494 alternative/source
views. Of 18,690 source-in-window observations in these eight states, 10,905
have indexed nonempty retained views; the residual export has exactly 7,785
bill IDs, including 5,894 TX and 1,847 FL contexts. The earlier six-state
residual remains 44. These are supplied-packet/date-observed counts, not native-universe
denominators, eligibility, classification accuracy or all-state completeness.
No native documents were recollected, re-extracted or tokenized.

California's introduced-version date and South Dakota's introduced field form
a **separate native-reported date channel**. Complete timestamp/date values
are validated with source-local days; missing/invalid observations stay explicit.
No canonical source date is overwritten. Native in-window text contexts include
3,463 with unresolved source dates (CA 3,285 / SD 178). The date-resolution queue
also retains 569 different native/source dates (CA 17 / SD 552); an earlier
native date can describe prefiling rather than an error in a later event date.
The 4,032-row queue requires event/eligibility adjudication, not automatic
earliest-date selection. Native date evidence is not analytical admission.

V1/v2 incomplete attempts preserve strict-format failures: Colorado's
hyphenated identifiers needed literal support, and unselected special-session
formats must not expand a packet adapter's normalization scope. Focused
regressions preserve both failures. V3/v4 are intermediate completed snapshots;
v5 additionally reuses California wider/special-session evidence. Earlier
outputs/logs remain unchanged. All original input bindings are checked before
and after the shared run; existing output directories are refused.
V6's explicit native `88R`/canonical `88` join failure remains incomplete;
v7 adds the reviewed crosswalk, partial packets and native date evidence,
and v8 exports the explicit date-resolution queue.
V9 binds the generalized origin-event helper while retaining the same native
data; all original introduction semantics remain unchanged.

## Separate explicit filing evidence and final combined matrix

```bash
.venv/bin/python -I -B -m state_politics.bills.study_filing \
  --window-dir data/processed/study-window-2023-2024-v2 \
  --actions data/processed/bill_actions.parquet \
  --matrix-dir data/processed/study-native-overlap-2023-2024-v9 \
  --out-dir data/processed/study-filing-2023-2024-v2
```

The earlier source-window ledger intentionally counted only coded
`introduction` events. The study permits filing **or** introduction, so a
separate pass now preserves exact `filing` action codes as well. It requires
one event in the originating organization/chamber and a complete valid date;
multiple events remain unresolved. Reading-1 actions and uncoded descriptions
such as INTRODUCED are not silently recoded. Filing and introduction retain
distinct dates and dispositions; every original ledger field remains unchanged.

The output contains the full `bill_filing_evidence.csv`, all 251,835 original
coded actions in `source_filing_actions.parquet`, session/chamber/type filing
counts and the enriched `state_matrix.csv`. The matrix retains all native-text
and native-date columns from the prior stage. It adds 45,184 in-window filing
observations: 18,695 have no resolved introduction date and 2,117 have an
introduction outside the window. Deduplicated filing-or-introduction coverage
is 151,615 source contexts, **not a native census or eligible-bill denominator**.
Measure types, source tests and draft contexts still require their own gates.

AK, AZ, CT, IN and LA gain observed source-date evidence from explicit filings;
MA, ME and NY still lack either qualifying source code in this retained window.
This does not mean zero activity. Florida gains 85 lower-chamber filing-date
observations, not complete House coverage.

The shared origin-event helper was generalized without changing introduction
semantics: all 1,090,369 results exactly match the committed original function
and every accepted introduction-ledger field. The final filing output was
also compared field-for-field with that ledger and its raw action export with
the original source table; the 50-state union counts and retained native columns
reconcile exactly. Final manifest:
`b6d05b23bdec09461492df13b190a43c0b138afe953ee40915a3fd458d82fc7b`.
The native v9 matrix it consumes has unchanged v8 data and a new code-bound
manifest `5e145ead121a3b5610531bc23750c1ece202bf4adc896f9b89d060b18784f51e`.
No canonical extraction, earlier ledger, label or model was rewritten.

## All-organization platform evidence and advisory source-date claims

```bash
.venv/bin/python -I -B -m state_politics.platforms.study_evidence \
  --record-reviews data/processed/platform-cycle-date-advisory-2023-2024-v1/reviews.jsonl \
  --out data/processed/platform-study-evidence-2023-2024-v5
```

This consumes accepted retained platform inventories, exact extraction
alternatives, modern/historical table views, supplementary caucus entries and
explicit advisory review packets. It preserves 3,917 full evidence records in
`records.jsonl`, all 100 organization allocations in `organizations.jsonl`,
the producer copy and a checksum-bound manifest. Full text survives, including
views excluded by the original collector; table filtering is not source loss.
National/other-party historical rows stay retained but outside state-D/R counts.

Source-stated dates, metadata-year hints, document role and operative
applicability are distinct. No URL/filename/year hint supplies adoption or
continued applicability. The bounded 16-record follow-up fully read 15
available texts and retained KY-R as text-unavailable; five empty table views
use exact capture-text joins. Its 40 claims bind exact source character spans,
reviewed text hashes and full UTF-8 texts, including original CR/LF content.
The reviews are advisory, not canonical labels or independent certification.

V5 retains 100 organizations / 3,917 views, including eight source-date
candidate views. Four newly reviewed views explicitly claim 2023–2024
passage/adoption; other candidates can be narrow agenda-year claims.
Counts are not distinct platforms or whole-cycle operative coverage, and
section-level date bands may overlap. Every applicability status stays
unresolved. V4 and its original 25 reviews/texts remain unchanged.

V5 manifest:
`3d17be52163ab449158e8ca38ee8b95a7ac7a5d52838f77e9f4ddf2fec8df19b`.
Advisory manifest:
`c85d4afa2f000a03cabbb733e8efdf0b78c1bc3b372d092cc6cb17e2b279a002`.
The inventory's `inputs[].stat` is ordered as device, inode, mode, link count,
size, mtime_ns and ctime_ns. All 1,762 consumed bindings were checked unchanged;
parent reconciliation verifies full original texts/records, allocations and
spans, not a second semantic review. No new collection, model inference,
training, canonical source rewrite or website publication is part of this step.
All generated evidence remains local/Git-ignored, not backed up by pushing code.

## State packet and cycle overlap

```bash
.venv/bin/python -I -B -m state_politics.bills.study_sources \
  --window-dir data/processed/study-window-2023-2024-v2 \
  --reference-dir data/processed/bill-document-reference-inventory-v4 \
  --input-dir data/processed/florida-native-bill-input-inventory-v1 \
  --state FL \
  --out-dir data/processed/florida-study-source-overlap-2023-2024-v3
```

This is an offline reconciliation of **the supplied packet**, not permission to
collect references or proof that all local archives were searched. Use a new
output directory for another execution. Consumed manifests must bind exact
file hashes, matching extraction lineage and a completed unlabelled input
inventory. Exact bill IDs must also agree on state, identifier and session;
imported link IDs must match the same bill in the reference inventory.

Outputs preserve every state context in `state_contexts.parquet`, every source
reference in `source_reference_links.parquet`, and all supplied input fields,
including complete text, in `supplied_input_overlap.parquet`. Native-session/
chamber/type/date-disposition groups are in `state_session_counts.csv`.
`report.json` and `manifest.json` bind counts, limits, input/code snapshots and
output digests/bytes. No dates are inferred and no analytical admission is granted.
Reconciliation failures leave an incomplete manifest; existing outputs are not
overwritten.

The actual Florida v3 manifest is
`26ab544fa6544a766bc62dc6dd719731923ff7e8fe729b92352e9c07f474e313`.
Separate session verifier `verify_florida_study_source_overlap_v3.py` checks every
original/export field and grouped count without calling producer helpers,
rehashing native PDFs or retokenizing inputs. Its receipt is
`florida_study_source_overlap_verified_v3.json`.
The 2,868 historical inputs have zero observed in-window overlap; all 1,847
qualifying date observations are Senate-side, not a statewide denominator.
V1, its original producer and the missing-coverage-flag regression remain
preserved as superseded diagnostics. V2 restored full coverage fields; v3 also
rejects nullable missing context identities. V2 and its independently verified
receipt remain preserved. All accepted source packets are unchanged.
Outputs/session evidence remain Git-ignored and local-only.

## One-command audit

```bash
make audit
```

The audit validates:

- SHA-256 hashes for every manually curated analytical input;
- gold-label schema, sample metadata and taxonomy codes;
- the 100-row party registry and all 50 states;
- the gap registry against the generated gap report;
- primary-source status and HTTPS URLs for official document/caucus registries;
- named Python producers for generated tables and figures;
- 50-state stated-agenda coverage and 50-state bill coverage;
- one row per state × party in the focus atlas;
- Nebraska's explicit nonpartisan status;
- election numerator/denominator consistency;
- action/vote artifact scale, historical chamber completeness, outcome-rate bounds, and
  roll-call probability bounds;
- literal reproducibility of every numeric log2 concentration from raw counts;
- stable source IDs and OCR versions on OCR-derived corpus rows;
- missing figures and machine-specific prose in the public README.
- a Markdown code-guide entry for every Python file.
- equality between named analytical constants in code and `conf/reproducibility.yml`, so
  thresholds and seeds cannot drift as hidden magic numbers.

It writes `data/processed/reproducibility_report.json` with computed results, input hashes and
random seeds. In CI or after committing, use:

```bash
uv run python scripts/audit_reproducibility.py --require-tracked
```

## Manual inputs

Manual judgment cannot be generated by code, so it is preserved and audited:

| Input | Judgment | Documentation |
|---|---|---|
| `data/gold/plank_topics_gold.csv` | 50 previously supplied topic labels; reviewer provenance unresolved | `data/gold/README.md` + `.meta.yml` |
| `conf/topics.yml` | CAP-adapted topic descriptions and keyword seeds | file header + `CITATIONS.md` |
| `conf/subject_topic_map.yml` | unambiguous Open States tag → CAP mapping | file header |
| `conf/platform_gaps.yml` | hand-verified reasons no committee document exists | file entries, checked dates |
| `conf/party_registry.yml` | official organization websites and overrides | source URL + verification fields |
| `conf/caucus_priority_registry.yml` | curated official caucus agenda sources | institution + URLs |
| `conf/official_document_registry.yml` | official OCR-only party documents | source URLs + fixed PDF hashes |

Their expected hashes are in `conf/reproducibility.yml`. Any edit requires an explicit manifest
update and review; otherwise `make audit` fails.

## Random processes

Every random process and seed is listed in `conf/reproducibility.yml`: `20260729` for gold
sampling, bill-tag validation and intra-party permutations; `20260731` for trend/profile
inference; and `20260801` for the outcome paired-state test.

Generate a new unlabeled gold template with:

```bash
uv run python scripts/sample_gold_planks.py --seed 20260729 --size 50
```

This does not overwrite the existing manually labelled snapshot.

## OCR-only official documents

The New York Democratic State Committee resolutions archive and Louisiana Republican State
Central Committee resolution packets are primary sources whose text is available only as page
images/scanned PDFs. Rebuild them with:

```bash
make official-documents
```

This target:

1. reads `conf/official_document_registry.yml`;
2. fetches the official Issuu/Wix objects;
3. verifies fixed PDF hashes;
4. records every fetch in `data/provenance.jsonl`;
5. records the Tesseract version;
6. OCRs pages in deterministic order and fixed configuration;
7. confirms state attribution and platform/resolution language;
8. replaces prior rows by stable `official_source_id`.

System dependency: `tesseract`. Python OCR dependencies are pinned in the `ocr` optional extra
and in `uv.lock`.

The platform collector evaluates every candidate clearing the strong-score threshold. Resumed
runs preserve all existing provenance fields, fetch both previously failed and newly discovered
URLs, and de-duplicate new text against documents already in the corpus. Network read failures
after HTTP headers are recorded and retried rather than terminating the crawl.
The checked artifact contains a row for all 1,948 strong candidate URLs, including explicit
failure rows where a source returned 404/403 or could not be retrieved.

## Open States actions and votes

The legacy outcome expansion used the 2026-07 public PostgreSQL dump.
That 10,711,908,617-byte object has SHA-256
`e4b8eb6d40d2da768074dab29bbf0d6949b8f24a50d75c5807669edcee5af78c`, recorded repeatedly in
`data/provenance.jsonl`. During the outcome expansion, a throttled download was reconstructed
from independently size-checked HTTP ranges and accepted only after matching that prior full-file
hash exactly.

The current audit instead retains `data/raw/openstates/2026-10-public.pgdump`, SHA-256
`6aa8341edc9ec251f4fb1eafb134b3415e72296e5391e05b39aded5e1ae2580c`.
Its extraction manifest binds all eleven saved tables. Current extraction retains the raw
dump and stages outputs before promotion; it does not delete the source after success.
The older source/hash must not be used to describe the October artifacts.

`bills/outcomes.py` streams large action/vote tables directly into compressed Parquet.
Historical chamber comes from organization ancestry; voter party is resolved only from
usable membership intervals covering the vote date. Undated memberships remain unknown,
and chamber/party field availability is not scientific certification. The capability
report distinguishes retained files from analytical support and names missing inputs.

## Clean-room rebuild order

```bash
make setup
make historical
make registry
make platforms            # includes OCR-only official documents
make caucus-priorities
make legislators
make bills-dump
make all
make test lint audit
```

The network-heavy steps are explicit because they access third-party services. Derived data is
gitignored; the code, curated inputs, source registries, citations, lockfile and tests are the
reproducible research package.

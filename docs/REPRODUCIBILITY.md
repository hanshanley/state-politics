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

## Reusing bounded accepted partial-native originals

```bash
.venv/bin/python -I -B -m state_politics.bills.study_partial_native \
  --data-dir data/processed \
  --out-dir data/processed/partial-native-input-index-2023-2024-v3
```

This normalizes only accepted initial-original selections for
MI/MD/MN/KY/AZ/KS/OR/VA,
using their stored extraction segments, not new collection, PDF extraction or
OCR. Each state exports a context inventory, complete alternative-view inputs
and pinned manifest. Negative flags, exact record/source hashes and raw native
date observations survive; dates are not normalized or admitted here.

| State | Selected contexts | Alternative views | Unavailable selected originals |
|---|---:|---:|---|
| MI | 32 | 64 | None |
| MD | 8 | 16 | None |
| MN | 32 | 93 | SR61 |
| KY | 32 | 60 | HJR21/HJR22 |

The table describes the original four-state selection; v3 adds AZ/KS/OR/VA
for **164 contexts / 337 views**, with text for 156 contexts. Root manifest:
`4fd4d59c89399504cf0d887d10e267be791fe7df1ff4822027fe414f20b13051`.
V2 remains preserved with manifest
`340c652dec60090a538710f2af75f5ed0623645935c063e4bd76e6d7bade078b`,
104 contexts / 233 views and all 335 original source fingerprints unchanged.
The failed v1 and failure receipt also remain preserved. These bounded
selections do not close any statewide source universe. Existing outputs are
refused; reproduction requires a fresh output directory and corresponding
explicit registry pins.

## Normalizing complete retained campaign projections

```bash
.venv/bin/python -I -B -m state_politics.bills.study_retained_campaigns \
  --data-dir data/processed \
  --evidence-dir data/processed/study-abstract-evidence-2023-2024-v2 \
  --states MO NY IL PA \
  --out-dir data/processed/retained-campaign-input-index-2023-2024-v1
```

The first common offline pass preserves 62,208 complete stored views /
688,174,798 UTF-8 bytes; manifest:
`5f8d64fc42a75476e0c01fdb21045d67c78364161c956e7ab2e9f552ec67e84a`.
The same command with `--states TX WA MT NM UT OK WV` and distinct output
`data/processed/retained-supplement-input-index-2023-2024-v1` preserves
30,730 contexts / 12,659 stored views / 299,118,518 UTF-8 bytes; manifest:
`d98970398a02b5967a41a60c4867d48f6ceeeb779157edb2fe7f43dfcd606892`.
Original metadata, partial bodies, negative flags and literal dates remain
bound to source fingerprints. Markup/history readers are not automatically
policy text; NM wrong-session/later documents retain quarantine. The MT
supplement's 22 history/ancillary views are not registered as policy originals.
No HTTP, PDF/HTML re-extraction or repeated campaign-closure audit runs here.

## Shared accepted-native-packet overlap

```bash
.venv/bin/python -I -B -m state_politics.bills.study_native_overlap \
  --matrix-dir data/processed/study-matrix-2023-2024-v1 \
  --registry conf/study_native_packets.yml \
  --out-dir data/processed/study-native-overlap-2023-2024-v14
```

The registry pins **28 packets across 26 states**, retaining earlier accepted
scopes while adding the common partial/campaign indexes and MT date observations.
It selects the California 2023–2024 packet **and** the wider
archive: the latter contains source-dated 2024 prefilings in a 2025–2026
session, which cannot be excluded by session-name substring. Canonical source
dates still come only from the existing national ledger; native dates remain
in their separate observation channel.

Shared profiles normalize single-source inputs, separate context/view
tables, paired-reader rows and guarded date-only observations.
Exact bill-ID/session/typed-identifier agreement
or a unique explicitly declared session/typed-identifier join is required.
California native special-session codes have an explicit registry crosswalk
to canonical session keys. This is an identity crosswalk, not a source of dates.
Unmapped source-only contexts remain unmatched; no HJR/HR/HB aliases or
ambiguous joins are guessed. NC's two identity-unresolved inputs stay marked.
MI alone additionally permits exact single-letter HJR/SJR identifiers; this
does not extend the grammar to another state or alias measure types.
Texas `88R` maps explicitly to canonical `88`; its original native key survives.
Its unavailable HB1 shell is retained as a context with zero input views.

Outputs are `native_context_overlap.parquet`, `native_bill_overlap.parquet`,
`native_view_index.parquet`,
`missing_supplied_native_text.parquet`, `native_introduction_observations.parquet`,
`date_resolution_queue.parquet`, the enriched `state_matrix.csv`,
`report.json` and `manifest.json`. The view index is an index, not a text
download: complete original strings remain in the bound input tables.
Alternative readers never count as additional measures. Unregistered states
retain null packet counts rather than zero recovery.

The current v14 manifest is
`867eb6c6adfcbc8274114819f561794567cd60eb860b399fb1b33a6faac4e60e`.
It indexes **118,009 raw contexts / 128,486 alternative views**, including
15,433 source-only contexts and 102,365 unique canonical bills with native
contexts. The separate bill aggregate prevents physical-reference inflation
while retaining every raw context. Conflicting native dates remain null with
an explicit conflict status; they are never resolved by earliest/latest.
Its 52,237 introduction-observed missing-text contexts reflect wider
registered scope, not a cycle denominator.

Opt-in missing identities and negative-flag source-only rules do not weaken
default matching. JSON scope proofs bind NY/PA session constants, not dates.
Explicit reader allowlists exclude 6,190 markup/alternative views while
preserving the complete original source packets. Empty zero-view tables are
valid; nonempty malformed views remain errors. MT uses the accepted native
event observations, requiring both exact formal identity and a unique origin
introduction event: 1,640 calendar-2023–2024 observations, including 213
calendar-2024 prefilings in session 2025. Drafts and history text are not policy
originals. All admissions remain false.

The preserved v9 manifest is
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
data; all original introduction semantics remain unchanged. V10 adds the four
bounded partial indexes and state-scoped MI identifier grammar.
V10 remains preserved with manifest
`f16998d466855fe653d988792f8707651541a7d45c9c7dc2459afb71266f8198`
(43,584 contexts / 59,727 views / 12 states). Failed v11–v13 attempts remain
preserved: duplicate packet IDs, an incorrect TX selector, zero-view schema
types and legitimate repeated reference contexts were repaired explicitly
rather than dropping records or changing earlier artifacts.

## Separate explicit filing evidence and final combined matrix

```bash
.venv/bin/python -I -B -m state_politics.bills.study_filing \
  --window-dir data/processed/study-window-2023-2024-v2 \
  --actions data/processed/bill_actions.parquet \
  --matrix-dir data/processed/study-native-overlap-2023-2024-v14 \
  --out-dir data/processed/study-filing-2023-2024-v4
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
reconcile exactly. Current v4 manifest:
`9be1ee10f4269774646a0e117e04873ed2914004f0e46df3652ff97072c31ce0`.
It consumes native v14, preserving the original filing ledger/actions while
updating native fields. V3 remains preserved with manifest
`a0824a1b5cfd25ae9ade853f01ea7d023dbf9932ebdacbc0511ca4c48b2423d3`.
V2 remains
preserved with manifest
`b6d05b23bdec09461492df13b190a43c0b138afe953ee40915a3fd458d82fc7b`;
its native v9 input was
`5e145ead121a3b5610531bc23750c1ece202bf4adc896f9b89d060b18784f51e`.
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

## Uncoded action-description evidence

The separate `state_politics.bills.study_description_evidence` producer binds
the existing filing/source-action inputs, retains exact original records and
recognizes reviewed literal self-descriptions, not guessed first-action dates.
Its MA/ME/NY packet preserves 184,977 contexts / 3,473 raw actions. The in-window
candidate channel contains 860 NY introduction records (856 resolutions / four
concurrent resolutions) and one MA petition filing. ME's approval/referral/
printing descriptions remain unresolved, not recoded introductions.

The actual output is `data/processed/study-description-evidence-2023-2024-v1/`,
manifest `df4cec9dea19c7a506588747afd659a864cf50ef6205969a1a4ef75a12f19b63`.
It is description-stated, not original source-coded or native-certified evidence.
Original action classifications and canonical date fields remain unchanged.
The accepted v1 description packet is reused with filing v3 only after exact
filing-ledger, source-window, extraction-manifest and description-ledger hash
agreement. A changed upstream manifest alone does not require repeating
description extraction when all relevant input bytes remain identical.

## Full national title/abstract evidence

```bash
.venv/bin/python -I -B -m state_politics.bills.study_abstracts \
  --data-dir data/processed \
  --filing-dir data/processed/study-filing-2023-2024-v4 \
  --native-dir data/processed/study-native-overlap-2023-2024-v14 \
  --description-dir data/processed/study-description-evidence-2023-2024-v1 \
  --out-dir data/processed/study-abstract-evidence-2023-2024-v3
```

This exports `bill_evidence.parquet`, `abstract_evidence.parquet`,
`candidate_metadata_views.parquet`, the enriched `state_matrix.csv`, report and
immutable manifest. Every selected abstract, original note, source title and
alternative survives, including literal Unicode separators. No latest/longest
selection or near-duplicate collapse is performed. Native text presence is
known only relative to registered packets; other states retain nulls.

The 157,598 candidate contexts comprise 151,615 coded-event records, 5,122
native-date-only and 861 description-only records. Conditional channels and
their source dates remain distinct from the coded count. Full abstracts cover
49,242 contexts / 50,959 records; 1,409 contexts have different abstract texts.
The 159,315 metadata views never prepend summaries to native introduced text.
Source tests, drafts and procedural title-only cases are flagged, not dropped
or falsely admitted. All model/training/filing-time/analytical approval flags
remain false; no tokenizer or classifier runs in this producer.

Manifest:
`38bf92a35831fe6ca75003f16caf2fce3354f48f54208bbf11a2b09d79b76c9d`.
Exact source fields, full strings/input hashes and all 50 prior matrix rows
reconcile to original extraction and upstream evidence.
V1 remains unchanged with manifest
`931a2ce0bcdb0a7ed328dc966cd21a3a14ff2c77cd561c5208d25753792f1150`.
V2 remains preserved with manifest
`69af46267bdc8c6ce4adb02a1bf4ec6ab1c06eee897f75af4efd38fd7611616b`:
its metadata-view and abstract artifacts were byte-identical to v1.
V3 adds 1,640 MT date candidates; the complete abstract artifact is still
byte-identical. It consumes the manifest-declared canonical native-bill
aggregate, not duplicate raw references. A corrupt declared aggregate fails
rather than silently falling back.

## Complete metadata token-window plan

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B -m state_politics.analysis.study_token_plan \
  --evidence-dir data/processed/study-abstract-evidence-2023-2024-v3 \
  --policy-dir data/processed/california-native-bill-input-inventory-v2 \
  --out-dir data/processed/study-metadata-token-plan-2023-2024-v2
```

Only local tokenizer files from the pinned accepted policy manifest are loaded;
no encoder weights or remote code/network are used. The official tokenizer
revision is `8949b909ec900327062f0ebf497f51aef5e6f0c8`. Source tokens retain their
character offsets, and paragraph-aware overlapping windows use the existing
1,024-token model budget, 1,018 source-token budget and 128-token overlap.
Marker IDs are `[25310, 3646, 27, 187]`, wrapper IDs `[50281, 50282]`.

The output `token_window_plan.parquet` contains every source token/offset,
window range and wrapped input length keyed to the original view/input hash;
full strings remain in the metadata bundle. It covers all 159,315 views /
10,059,370 source tokens in 160,146 windows, zero discarded tokens. The maximum
source has 16,848 tokens / 21 windows; every wrapped input is at most 1,024.
The full-source tokenizer emits a long-sequence warning for some inputs, but
the encoder is never called on these strings. Independent low-level tokenizer
replay of every current view reproduced all saved token IDs/offsets and
window-coverage invariants. All 157,675 old plan rows are exactly unchanged;
the 1,640 additional rows are preserved without discarded tokens.

Manifest:
`f251ec5da26987c61d2ddee4987c150b606504a6d82b52330cc6ce6dce2fb83b`.
This is an unlabelled coverage plan, not model accuracy, source-date alignment,
eligibility, calibration, predictions or analytical admission.
V1 remains preserved with manifest
`4b9f5dce745031ecefa8058037e69457dd79559aa9e2b15c1fba48333a937cfe`
(157,675 views / 10,044,063 tokens / 158,506 windows). Its plan is reusable for metadata
v2 because the entire `candidate_metadata_views.parquet` artifact has the same
SHA-256, `2010b82b02dc7b6da884c3e206f718544622599e035a99b8f86b538dfa83586b`.
The corresponding complete abstract artifact is also unchanged:
`4d36e2deef8b99a7c5456b070c327a5c790a131ee841eb11db59c5d5ed74ebd1`.
This is exact artifact reuse, not an assumption that similar text tokenizes
identically. The original token-plan manifest is not rewritten.

## Explicit conflict-exclusion classifier experiment

Conflicting eligible CAP labels still fail preparation by default. The
experimental whole-group exclusion mode must be explicitly selected:

```bash
.venv/bin/python -I -B -m state_politics.analysis.prepare_topics \
  --cap-dir data/raw/cap \
  --reviewed-target data/labels/retained-target-review-input-20261021-v1/reviewed_target.jsonl \
  --out data/labels/cap-conflict-exclusion-experiment-20261021-v1 \
  --per-source-topic 100 --min-year 2000 --seed 20261018 \
  --conflict-policy exclude-groups
```

The reviewed-target input contains all 263 original assistant-reviewed records,
copied as complete original JSONL records from the unchanged canonical
6,158-row manifest. Its receipt binds the original physical-LF positions,
canonical hash/stat fields and exact subset hash. No source topic is corrected,
no assistant review is renamed human gold and no challenge label is tuned.
Existing outputs are refused; choose distinct paths for a new experiment.

A first pass finds competing eligible codes across all three source files;
the second excludes every group member before deduplication and sampling.
`conflict_exclusions.jsonl` preserves every complete original excluded row,
source filename/CSV record position/hash and competing topics. The manifest
binds its hash/count and archives the exact preparation producer. Source
hashes are rechecked after scanning. Known compatibility flags and
reviewed-target exact/near-copy reservations remain in effect.

Actual preparation excludes 2,228 groups / 6,120 eligible source rows and
produces 6,103 training / 50 development records. Labels SHA-256:
`2b9d0c833846341c7ef94b72b2358c9033ef4aceba0e8ebb6d7be2b3407393ed`.
Preparation manifest:
`66a75a42301b0a1d54e1f5f5b5586eed981f90ef08e1f36024cf75b7afc2a849`.
The same original 116 conflict-exposed canonical records map to excluded
groups, but replacement sampling means this is not simply a 116-row deletion.
The canonical file retains SHA-256
`395ffa760c684619199ac005df8e52b3d42a5e94d9a8a7e9772b7b1642a33361`.

Preflight checks all source/group/text split identities and the 52 previously
examined challenge records; no detected exact/near training copy survives.
All training inputs fit 1,024 tokens without truncation (maximum 468).
The actual fresh full-encoder/head run uses the prior settings:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_ENABLE_MPS_FALLBACK=1 \
  .venv/bin/python -I -B -m state_politics.analysis.train_topics \
  --labels data/labels/cap-conflict-exclusion-experiment-20261021-v1/labels.jsonl \
  --source-reservation data/labels/platform-challenge-reserved-sources-v1/reservation.json \
  --out data/models/modernbert-conflict-exclusion-experiment-20261021-v1 \
  --epochs 3 --batch-size 4 --max-tokens 1024 --overlap 128 \
  --learning-rate 0.00002 --seed 20261018
```

The pre-training evaluation plan is frozen at
`data/processed/conflict-exclusion-model-evaluation-20261021-v1/evaluation_plan.json`,
SHA-256 `78fa1a516dd53cf2035e6f55f95fdef653e8e28214beb927a37651ce27c5c807`.
It pins baseline/code/input/reservation hashes and the unchanged decision
policy. Completed evaluation found 54% development / 88.46% earlier-challenge
decision accuracy, versus 62% / 94.23% for the prior Republican curriculum;
the exclusion experiment is not promoted. No thresholds/references changed. Previously
examined assistant-labelled diagnostics are not independent human gold,
population accuracy, causal proof of an exclusion effect or release approval.
Default loading must still reject provisional checkpoints.

## Frozen cycle diagnostics and target-source curriculum

`state_politics.analysis.prepare_cycle_review` provides `freeze` and `assemble`
actions. Freezing binds complete metadata inputs and all exact/near/group/source
reservations before annotation. Assembly requires evidence spans and explicit
assistant reviewer provenance; it preserves separate reviewer IDs. Challenge
and training roles are frozen, and `--quarantine-rubric-ambiguity` is an
explicit training-only choice, not relabeling locked challenge answers.

Actual blind references are in
`data/labels/cycle-metadata-blind-review-20261021-v1/`: 190 complete inputs,
50 states accounted for, 110 topics / 80 abstentions. Labels SHA-256:
`edaf5b57d3590635612a03c662fc618e3460a2066b32ff194a5a72c0b557d8ef`.
Five-model results and complete decisions are retained in
`data/processed/cycle-metadata-blind-evaluation-20261021-v1/`; the best fixed-policy
decision accuracy was 61.58%. These manually read assistant references are
not independent human gold. After inspection they are development diagnostics,
not untouched final holdout data.

Two separate GPT-6.1 Sol reviewers read 564 new training-review units, excluding
the locked 190 inputs, the earlier 52-input challenge and prior training/source
reservations. All original decisions survive. The explicit quarantine retains
34 rubric-ambiguity cases, leaving 530 labels, SHA-256
`972dab8b867304b5cc17edb310d95256a9932bea682a3b2e94e19452f7f89277`.
Composition preserves the prior 6,153 rows, adds 529 bounded units and preserves
one complete 1,538-token unit outside the training budget without truncation.
The resulting 6,632 train / 50 dev labels have SHA-256
`58bfd46ab4044ad3bec68b3a5e0c131f926f98e6d4ff11beec89d5aa92417a3d`.
All labels remain assistant/external evidence, not adjudicated scientific gold.

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_ENABLE_MPS_FALLBACK=1 \
  .venv/bin/python -I -B -m state_politics.analysis.train_topics \
  --labels data/labels/cycle-target-curriculum-20261021-v1/labels.jsonl \
  --source-reservation data/labels/platform-challenge-reserved-sources-v1/reservation.json \
  --out data/models/modernbert-cycle-target-balanced-20261021-v1 \
  --epochs 3 --batch-size 4 --max-tokens 1024 --overlap 128 \
  --learning-rate 0.00002 --seed 20261018 \
  --reviewed-target-sampling-weight 8
```

Weight 1 preserves the original deterministic shuffle. Explicit other weights
sample with replacement for the same epoch length, recording actual origin,
domain and unique-record counts without duplicating label rows. This actual
three-epoch run completed with finite losses 1.04416, .49240 and .30613 and a
verified encoder update; each epoch drew 6,632 examples.
The pre-training plan
`data/processed/cycle-target-balanced-evaluation-20261021-v1/evaluation_plan.json`
has SHA-256 `9f6a7877c71e5e6c46878d6ee1fc2925b832a7e2c6f0b1ea47ed6f555254e239`.
It freezes the original temperature/confidence/margin, source references and
producer hashes; neither curriculum changes nor sampling establish a causal
accuracy improvement or independent release approval.

Actual fixed-policy results were **61.05%** decision accuracy on cycle 190,
**92.31%** on the earlier platform 52 and **60%** on dev 50. Cycle classified
precision was 58.73% (74 correct topics / 126 classified), with 42 correct
abstentions. The best retained prior cycle decision result remains 61.58%.
The new model is not promoted; default provisional refusal was checked.
Training manifest SHA-256:
`d3c751dee57437e7e3d21b35eaac611da2e1040fc17bdf238b72048f89b18faf`.
Evaluation manifest:
`e5b9cc3e48ad01f297241a9f893db051e346b843c65e19870368555536b15da4`.
Complete predictions, decision ledgers and the six-model comparison remain
in the pre-planned evaluation directory; no reference/threshold edit occurred.

## Complete native-input review and document-level training

```bash
.venv/bin/python -I -B -m state_politics.analysis.prepare_native_review \
  --preview data/preview-cycle-evidence-v3 \
  --output data/labels/cycle-native-blind-review-20261021-v1 \
  --reserve-labels data/labels/cycle-target-curriculum-20261021-v1/labels.jsonl \
  --reserve-labels data/labels/cycle-metadata-blind-review-20261021-v1/labels.jsonl \
  --reserve-inputs data/labels/cycle-metadata-training-review-20261021-v1/review_packet.jsonl
```

Existing output directories are refused. This records the actual 39-input
freeze; choose a fresh directory for reproduction. The complete chosen native
string is the input, not a title/summary concatenation. All selected bills'
reader/reference alternatives are separately retained in full, with exact
input hashes and canonical-bill reservation. The default character ceiling
is 12,000 and the two-per-state strata are explicit diagnostic selection,
not truncated sources or population sampling. All 50 states retain accounting;
20 had selected inputs after source/length/reservation restrictions.

Two isolated GPT-6.1 Sol reviewers each read all 39 inputs / 143,398 characters.
Comparison preserves both full original decisions; disagreement never chooses
the first/majority topic:

```bash
.venv/bin/python -I -B -m state_politics.analysis.prepare_native_review compare \
  --output data/labels/cycle-native-blind-review-20261021-v1 \
  --review-a data/labels/cycle-native-blind-review-20261021-v1/reviewer_a_decisions.jsonl \
  --review-b data/labels/cycle-native-blind-review-20261021-v1/reviewer_b_decisions.jsonl
```

The pre-review plan
`data/processed/cycle-native-input-diagnostic-20261021-v1/evaluation_plan.json`
has SHA-256 `cffe58358b988566ad318205977c0be7f92a3dd25176bd0b60795d0a74ca321e`.
It excludes three disagreements from the primary 36-input metric before
predictions, with all-input sensitivities reported separately. The joint-target
model reached 55.56% decision accuracy / 68.18% precision; the balanced model
72.22% / 86.36%, respectively. Both preserve all 37,326 tokens / 57 windows
with zero discarded tokens. This is small, character-bounded assistant
evidence, not human gold or a causal comparison to the different metadata
sample. After inspection it is a development diagnostic. No model is promoted.
Evaluation manifest:
`2ea3479d0c5e8285b16996758f52e15aab96dc1701d40a044902da6f13ef11f3`.

The separate training freeze uses `--per-state 4 --review-split train
--quarantine-rubric-ambiguity`, a distinct seed/output, and reserves both the
39-input labels and all their full reader alternatives. All 68 inputs were
fully reviewed; 65 labels survive and three unresolved rubric cases remain
complete in quarantine. The composed document curriculum preserves all 6,682
prior rows and adds those 65 plus the complete previously quarantined
1,538-token unit: **6,698 train / 50 dev**. Labels SHA-256:
`4b1bb1affd9094ee4cad52f4d2fedb039435be9747ba7e3ecc12cba88e9448d8`.

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_ENABLE_MPS_FALLBACK=1 \
  .venv/bin/python -I -B -m state_politics.analysis.train_topics \
  --labels data/labels/cycle-native-document-curriculum-20261021-v1/labels.jsonl \
  --source-reservation data/labels/platform-challenge-reserved-sources-v1/reservation.json \
  --out data/models/modernbert-native-document-curriculum-20261021-v1 \
  --epochs 3 --batch-size 4 --max-tokens 1024 --overlap 128 \
  --learning-rate 0.00002 --seed 20261018 \
  --reviewed-target-sampling-weight 8 --allow-document-windows
```

The new flag is opt-in; default over-budget refusal remains. It computes
log-mean class probability across a complete unit's bounded windows, applying
**one target per unit**, never separate labels to arbitrary chunks. This
matches the existing probability aggregation while preserving its strict
inference disagreement/rejection guards. Every source token survives.
Preflight encodes 275,643 tokens / 6,728 windows / 23 multichunk units; these
are unique-input planning counts, not claims that a weighted epoch sampled
every row. The saved model archives exact producer Python and taxonomy bytes
alongside tokenizer/config/weights hashes. Unit checks cover finite gradients
through every window, extreme logits and single-window loss equivalence.

The separate pre-training plan
`data/processed/cycle-native-document-evaluation-20261021-v1/evaluation_plan.json`
has SHA-256 `ff480571923800ae12e6c12f6371b3e40de25716cd529028bb2295beaf95bf75`.
Actual three-epoch encoder training completed with finite losses 1.10301,
.45965 and .31895 and a verified encoder update. All 65 native units were
actually sampled; optimizer replay counts 17 uses of the restored long unit.
Fixed-policy decision results: metadata 190 **65.79%**, native agreed 36
**75%**, platform 52 **86.54%**, dev 50 **54%**. Native precision is 84%
(21/25 classified), so higher decision coverage does not establish superior
precision across sources. No promotion occurred. Training manifest:
`18d3e7c6c1349c96f363832078561775340c449bc1c87261a91371ce93411d13`.
Evaluation manifest:
`5853e29cc746f51fee427bbfa7d090878286d74d39cd82fa4b1cb0c24b73555b`.

The separate reviewed-only experiment keeps all 858 assistant-reviewed rows,
including all 50 original dev rows, while preserving all 5,890 omitted
external rows in full outside this experiment. All 21 topics retain positive
support; two-example rare classes are not certified by that fact.

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_ENABLE_MPS_FALLBACK=1 \
  .venv/bin/python -I -B -m state_politics.analysis.train_topics \
  --labels data/labels/cycle-reviewed-only-experiment-20261021-v1/labels.jsonl \
  --source-reservation data/labels/platform-challenge-reserved-sources-v1/reservation.json \
  --out data/models/modernbert-reviewed-only-20261021-v1 \
  --epochs 6 --batch-size 4 --max-tokens 1024 --overlap 128 \
  --learning-rate 0.00002 --seed 20261018 \
  --allow-document-windows --class-weighting uniform
```

This is explicit uniform loss, not a changed default: absent this flag,
inverse-frequency class loss remains unchanged. With the default sampling
weight 1, each epoch shuffles all 808 train units once without replacement.
Preflight preserves 94,935 source tokens / 838 windows / 23 multichunk units.
Its frozen pre-training plan is
`data/processed/cycle-reviewed-only-evaluation-20261021-v1/evaluation_plan.json`,
SHA-256 `c87a9792e787d8d59d7234a11c84a86dc766b032fcab27b0471cd5e78f2b4f9a`.
Training/results are pending. External removal, exposure and class loss
change jointly; do not claim a causal source effect. All references already
informed development. Original labels, reference texts, thresholds and
scientific/publication gates remain unchanged.

## Receipt observations and additional publisher-session text

`data/processed/maine-source-receipt-evidence-2023-2024-v1/` preserves all
9,877 Maine bill contexts and 166,141 source actions, plus original child
tables/ledgers and every receipt disposition. Manifest:
`68e6302fce9f4c6a97193aedb715aa04c4c90b0e05ca89b81e7769c1795d437b`.
The packet includes 61 unique origin/date-agreeing receipts and one unresolved
LD 2081 discrepancy (`2023-12-20` action versus `2022-12-20` literal receipt).
Neither value is chosen as a filing/introduction date. No Maine HTTP,
canonical rewrite or cohort admission occurred.

The opt-in `--native-session-scope` export uses only the fixed reviewed
`ny-2023-2024` and `il-103rd` scope contracts, requiring an explicit compatible
`--native-evidence`. It preserves complete text for exact canonical matches
outside the metadata candidate cohort. Native session/proof selectors do not
infer dates. Source-only/wrong-session contexts are never assigned aliases,
and candidate views are excluded to prevent double counting.

New York contributes 46,776 views / 23,388 references and canonical IDs;
Illinois 5,189 views / references / IDs. These 51,965 additional views are
**publisher-session-bound source evidence, not new eligible-cycle measures**.
Original candidate-native views remain 39,576 across 27,444 candidate IDs.
All extra fields, date dispositions, reader alternatives and false approvals
survive, and other states/sessions remain unknown rather than zero.

## Unpublished cycle-evidence explorer

```bash
.venv/bin/python -I -B scripts/build_site.py \
  --cycle-evidence \
  --bill-evidence data/processed/study-abstract-evidence-2023-2024-v3 \
  --platform-evidence data/processed/platform-study-evidence-2023-2024-v5 \
  --native-evidence data/processed/study-native-overlap-2023-2024-v14 \
  --metadata-token-plan data/processed/study-metadata-token-plan-2023-2024-v2 \
  --receipt-evidence data/processed/maine-source-receipt-evidence-2023-2024-v1 \
  --native-session-scope ny-2023-2024 --native-session-scope il-103rd \
  --out data/preview-cycle-evidence-v6
```

Evidence mode defaults to metadata v3 and platform evidence v5, with matching
native v14 / token-plan v2 enrichments. Custom metadata does not silently
attach these default optional bundles; pass compatible explicit directories.
The output includes all 50 state coverage rows / 100 organization rows,
complete metadata/platform texts, lazy state partitions, full-text gzip
downloads and `downloads/build_manifest.json`. The current build manifest is
`3a1cf3e980502edefde3121af229baebccb38e0a076e8813966f8ab9da90a0d9`.
Receipt/session additions are explicit opt-ins only; the default/custom
metadata behavior does not silently attach them. Build producers are archived
with their exact source hashes. V3–v5 remain preserved.

For interactive use, serve the output with a local static HTTP server:

```bash
.venv/bin/python -I -B -m http.server 8765 \
  --bind 127.0.0.1 --directory data/preview-cycle-evidence-v6
```

No server is left running by the build or verification. JavaScript fetches
require HTTP; no-JS coverage tables and full-text download links remain
available. Filtering/search/downloads are scoped to the selected state,
source and applicable party, not national full-text search. Downloads include
every matching full-text view, not just the displayed page or metadata.
Query export streams original NDJSON rather than reserializing parsed
records, preserving large-integer provenance and avoiding whole-file string
limits. Real single-Chromium checks exercised both blank and broad `"the"`
queries over all **46,776 NY records / 1,216,462,528 bytes**. Both downloaded
files exactly match the original complete partition, including all fields
and text hashes; no giant string was transferred through CDP. Proof:
`data/cycle-session-v6-giant-query/receipt.json`.
Maine's empty cycle query explicitly retains the wider 9,877-context inventory
and missing-date distinction. Real Chromium exercised pagination, complete
query downloads, literal-markup safety, keyboard, mobile and no-JS behavior.

The actual enriched preview exports 39,576 complete native text views /
27,512 source references / 27,444 distinct candidate bills. It does not
embed raw PDFs or certify original-stage identity. Planning statistics are
in a separate `token_plan` namespace; original metadata token fields remain
null. All 159,315 metadata views have bound token counts/windows with zero
discarded source tokens. Native inputs without that supplied metadata plan
do not acquire invented token statistics. No model, source collector, certified findings,
report, public route or deployment is part of this build. Source bundles,
earlier previews and full-text artifacts remain unchanged and local/Git-ignored.

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

# Reproducibility and traceability

This repository separates **authored inputs**, **primary-source collections**, and **generated
artifacts**. Nothing is described as reproducible merely because a final CSV exists.

**Current status:** the historical analytical results are under audit, not certified.
See [AUDIT_STATUS.md](AUDIT_STATUS.md). Run `scripts/audit_reproducibility.py --inventory-only`
to print missing prerequisites without attempting data-dependent scientific checks;
add `--report` with a fresh path to save them. Failures still produce a nonzero
exit and a report. Dependency hashes were deliberately
updated for the ModernBERT migration; the unchanged legacy analysis parameters describe
the old baseline, not a newly trained model.

The active study is limited to **2023–2024** and platforms applicable during that
cycle. Wider retained corpora, historical training data and old audit reports
remain unchanged. Broad rebuild commands below are not a request to complete
other years; target-cycle selection and its inclusion/exclusion provenance must
be bound explicitly before regenerated outputs can support the narrowed study.
The broad legacy `all`, `analysis` and `legacy-figures` targets refuse to run
without `ALLOW_LEGACY_ANALYSIS=1`, before any prerequisites can fetch or
recompute data, including parallel Make. This opt-in preserves intentional
legacy work; it does not approve collection, model promotion or scientific claims.

## Current saved-research integrity check

Run the public read-only checker against the pinned current graph collection
and inspector, with the original saved bundles present:

```bash
.venv/bin/python -I -B scripts/audit_current_research.py
# Equivalent Make entry point, using the existing interpreter:
make audit-current PY='.venv/bin/python -I -B'
# Optional successful-run JSON receipt; choose a fresh name:
.venv/bin/python -I -B scripts/audit_current_research.py \
  --report data/current-research-integrity-REPLAY.json
```

The checker verifies every declared graph/inspector artifact and every direct
graph-input binding, then follows the externally bound graph-source manifests,
including the context pilot. It streams file hashes rather than copying inputs,
checks unchanged fingerprints, and rejects missing/changed/linked paths, invalid
bindings, promoted status or a pre-existing report. It performs no collection,
model execution, graph rendering or population rebuild. The optional report must
be a new unlinked path under project `data/`; no existing receipt is replaced.

Default graph/inspector SHA pins are explicit, not discovered by choosing the
latest filename. An intentional new snapshot requires explicit
`--graphs`/`--graphs-sha256` and/or `--inspector`/`--inspector-sha256` values
(and later a reviewed default-pin update). The graph's own pinned input
bindings supply the source-bundle identities.

**A successful exit certifies only byte integrity for these declared saved
artifacts.** It does not certify their topic labels, source completeness,
filing-time eligibility, human references, scientific claims or publication.
It is not a recursive re-audit of every historical source/model dependency or
a replacement for independent chart/record reconstruction. `make audit` and
its known legacy-artifact failures remain separate and unchanged.

## Retained Pennsylvania introduction-date observations

The public adapter reopens already retained raw PDFs with the locked PyMuPDF
1.28.0 and pypdf 6.14.2 readers. It requires the own printed state/type/number/
session and a uniquely labelled introduced-by date; separate introduction
confirmations must agree. Raw spans and complete first pages are retained.
Referrals, body/adoption dates and URLs are not date fallbacks. Disagreement
stays unknown; amended/reprint warnings do not become original-version approval.

The accepted **v4** packet's externally recorded manifest SHA-256 is
`025d07b4955cf2ebeb309fb86a10d575138662be98775cef8c08cca651b4ec55`.
Replay it and write a fresh, explicit proposed registry:

```bash
.venv/bin/python -I -B -m state_politics.bills.pa_printed_dates verify \
  --directory data/processed/pa-printed-introduction-observations-20261028-v4 \
  --manifest-sha256 025d07b4955cf2ebeb309fb86a10d575138662be98775cef8c08cca651b4ec55
.venv/bin/python -I -B -m state_politics.bills.pa_printed_dates registry \
  --directory data/processed/pa-printed-introduction-observations-20261028-v4 \
  --manifest-sha256 025d07b4955cf2ebeb309fb86a10d575138662be98775cef8c08cca651b4ec55 \
  --base conf/study_native_packets.yml \
  --out data/proposed-pa-printed-dates-registry-REPLAY.yml
```

For a new packet, use the externally pinned assessment and an unused direct
child of `data/` or `data/processed/`; existing evidence is never overwritten:

```bash
.venv/bin/python -I -B -m state_politics.bills.pa_printed_dates build \
  --assessment data/retained-native-date-evidence-20261028-v1/manifest.json \
  --assessment-sha256 b49fb1292d4bf9c08f654f5cd80024485e31e9f642e50f3b53cfebd6288ce5ce \
  --out-dir data/processed/pa-printed-introduction-observations-REPLAY
```

Verification binds source/assessment/shared-join hashes, installed and archived
producer bytes, both fresh readers, complete CSV/Parquet/first-page/disposition
content, counts and all 15 false approval fields. Archived code is not executed.
The complete 170-row date export accounts for 232 selected PDF views / 170 raw
PDFs and retains dispositions for all 614 original views, including 382 views
not selected as PDF date sources.

The proposed registry preserves all 29 existing entries and declares the new
packet as `source_reference` with zero policy views. Actual common integration
preserves 4,786 PA bill rows / 454 policy views and every original source-date/
window field: 168 source dates remain exact empty strings and two remain
`2023-01-03`, agreeing with the new native observations. The primary cohort
remains SHA-identical: 168 observations are outside it and two are already inside.
This does not replace the current registry, build a national population, run a
model or admit data for analysis/publication. Ignored originals, v1-v3 packets,
failed attempts and proofs at `data/pa-printed-date-qualification-20261028-v1/`
remain local; a code push is not a data backup.

## Storage-safe continuation

The legacy `make clean-derived` target is disabled: its broad deletion would
remove retained processed tables and historical root figures. It now refuses
the operation with a nonzero exit and leaves all files intact. Use an inspected,
manifest-bound reclamation plan below instead; do not substitute manual globs.

Batch small source recoveries and reuse immutable inputs; do not create
another complete data copy merely to save a checkpoint. Estimate incremental
storage before a full replay. On APFS, the standalone reclamation tool defaults
to a manifest-only dry run over completed generated bundles:

```bash
.venv/bin/python -I -B scripts/reclaim_generated_storage.py \
  --report data/generated-storage-plan-REPLAY.json
# Only after inspecting the plan, with research servers/builders stopped:
.venv/bin/python -I -B scripts/reclaim_generated_storage.py --apply \
  --report data/generated-storage-reclaimed-REPLAY.json
```

The default `--scope bundles` does not include preview snapshots. To inspect
and reclaim only completed previews without repeating the earlier bundle batch:

```bash
.venv/bin/python -I -B scripts/reclaim_generated_storage.py --scope previews \
  --report data/generated-preview-storage-plan-REPLAY.json
.venv/bin/python -I -B scripts/reclaim_generated_storage.py --scope previews --apply \
  --report data/generated-preview-storage-reclaimed-REPLAY.json
```

Preview scope accepts only exact versioned directories, an unlinked complete
`downloads/build_manifest.json` with the known preview schema, and bound
`evidence/` or `downloads/` artifacts. Equal filenames are not evidence of
equal content. Partial/failed snapshots and all other directories are excluded.

Use fresh report names. Application verifies original, duplicate and clone
SHA/size bindings, requires independent inodes, preserves content/permissions/
modification times and rechecks all manifests. It refuses changed or linked paths,
active research servers/builders and unsupported cloning instead of falling
back to another full copy. Per-file completion is journaled. Raw sources,
model weights, failed attempts and original logical paths are not deleted.
Reported physical recovery is measured, not inferred from logical file sizes.
Already-shared clones can still appear in that logical upper bound; do not
repeat an unchanged batch after its successful reclamation receipt.
Copy-on-write reuse is not an off-device backup.

Future classification-inspector builds now create their complete evidence files
with native copy-on-write clones on macOS, rather than first making ordinary
full copies and requiring later reclamation. Every JSONL, complete research ZIP
and byte-range reference remains local to the new bundle, with independent
inodes and the same full-content SHA checks. Unsupported or cross-volume native
cloning stops the build without a full-copy fallback or overwriting an existing
destination. Other operating systems retain full streaming copies with exclusive
file creation. The shared storage helper is retained with each new inspector's
producer code. Existing bundles are unchanged; this does not authorize another
full build or change any source/model/publication gate.

The October 26 verified reclamation replaced 1,897 generated duplicate copies
without changing logical paths or payloads. Free space increased from
12,761,374,720 to 339,733,323,776 bytes: **326,971,949,056 bytes recovered**.
Receipt/journal: `data/generated-storage-reclaimed-20261026-v1.json` and its
`.journal.jsonl` sibling. The exact executed producer is retained in
`data/reclaim_generated_storage_executed_20261026_v1.py`; all pairs were on
the same APFS volume. The public tool additionally uses the direct native
`clonefile` syscall so future failures cannot silently fall back to full copies.
All current graph exports/tables/marks and 85 controls remain unchanged.

The separate previews-only pass replaces 4,238 duplicate generated artifacts
across **41 complete snapshots**; unfinished `preview-cycle-evidence-v9` is
excluded. Free space rises from 341,116,792,832 to 614,814,695,424 bytes:
**273,697,902,592 additional bytes recovered**. Receipt/journal:
`data/generated-preview-storage-reclaimed-20261026-v1.json` and its
`.journal.jsonl` sibling. The exact executed producer is preserved at
`data/reclaim_preview_storage_executed_20261026_v1.py`.
No targets overlap the earlier bundle pass. All 41 manifests, complete
evidence/download bytes and paths remain unchanged. Post-reclamation graph
verification again reconciles all 108 exports / 35 CSVs / 3,176 marks and
85 controls. The public tool also refuses active `build_site.py` preview
builders; all 24 focused tests pass. No acquisition, inference, new full
snapshot, other-project/session change or website deployment follows.
The full tracked audit is byte-identical to the earlier storage checkpoint:
462/496, the same 34 legacy failures and all report fields unchanged.
Public-documentation checks: 220. Bulk generation remains paused.

## Current successor: literal-position hyphen evidence, v26

**Future extensions start from completed v26 / independent token cache v23.**
All 157,598 contexts remain: **139,869 with text / 17,729 missing** (1,256 NE).
Unanimity gives 65,306 assigned / 74,563 abstained. Separate, unpromoted
majority gives 78,522 assigned / 23,816 rejected / 37,528 uncertain /
three excluded / 17,729 unavailable. Its 13,216 additional assignments and
uncalibrated scores do not certify independent accuracy.

Exactly 14 new raw strings / 210,419 characters / 53,596 tokens / 67 windows
reach the unchanged encoder, with zero old repeats or discarded tokens.
All 179,835 old predictions, 169,493 old cache rows, 157,591 other whole
assignments and 85 controls remain unchanged. New unanimity: one assigned /
six abstained; new majority: four assigned / three uncertain. Only the nine
independently proved PDF positions can differ between readers; stored text
is never normalized or relabelled as introduced. Original dates stay intact.

Preview42 manifest:
`fd420bcb5e3c446b6c5687902773fc55958cf0857a3f111da6b44e134845e2ac`.
Job26 plan:
`b5d9b3a0df60c48dc06a1edaf2c32d540507bd00e10e01d7fe99fad242c2f840`.
Prediction cache26: 754,925,568 bytes / 169,507 rows, SHA-256
`e166ebdc053272586f5130d4530dad5bcb7745fd70e9d093c86bfe7c8a742dce`.
Independent token23: 40,394,752 bytes / 169,507 strings, SHA-256
`1f69ba2a796af9e7795c2bf3f427b80e8e73dc64e5f7f1aa9e313f2985b766bb`.
Parents v25/token22 remain byte-identical. Full replay performs no encoder work:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B scripts/audit_cycle_topics.py \
  --job data/processed/cycle-topic-inference-retained-text-20261026-v26 \
  --gallery outputs/topic-inference-retained-text-2023-2024-v24 \
  --verified-token-cache data/cycle-topic-independent-token-verification-cache-20261026-v23.sqlite \
  --verified-token-cache-sha256 1f69ba2a796af9e7795c2bf3f427b80e8e73dc64e5f7f1aa9e313f2985b766bb \
  --out data/ne-enacted-hyphen-tracked-cycle-audit-REPLAY.json
```

Current manifests: source37
`13a97537c009a190b79772ca7a229ed86ed634b444ca88e08d70b2eafa17e20e`;
topic24 `3ae4eb659a28205c34121063280c216185376d1d0726849f9aa4c6af6c04992b`;
majority8 `61fd909f4892b8d7a1199d433293e938bb14601fb2a95c20bfdd7243b415231b`;
score8 `2f6b9650bbe8ea546186cf44de34443b781d2ec04d847e6204a18f542cdafcbb`;
paired22 `59255a7a52652bf45d894e4d87e9734c931dbd811df0fd02bb34dcf782945fca`;
original inspector8 `1bc6cf4832681cc588303b1af61186bad2d7fa788fb38cba311e88ee7254d339`.
The current UI-only inspector v9, with identical data, is documented in the
[per-bill inspector section](#per-bill-classification-evidence-inspector).
Original v26 delivery manifest (preserved; the current presentation is below):
`b89ad3fa5e3bad582f85899e88b6e8886fed2b6f35171240e942c5b619cddbaf`.
The prior collection/exact producer/copied README remain in
`outputs/preserved-current-source36-20261026-v1/`.

All 27 actual charts / 108 exports / 35 full CSVs are regenerated and
independently reconcile 3,176 marks and root/nested image/table bytes.
Actual Chromium verifies all 14 complete texts/scores/long windows,
the complete NE query (2,128 contexts / 1,424 pairs / 10,787,454 characters),
LB989 query (one context / two pairs / 60,630 characters) and all 50 source
ZIP members. The graph source ZIP is 167,567,934 bytes, SHA-256
`b1d8f0d0908622e371c694b8db79acf1b91b7018f13c2befd0e4a511d488e232`;
its payloads equal the source-checkpoint ZIP despite different compression.
All 38 older complete research ZIPs remain byte-identical. Both galleries
pass 27 images / 180 links / seven destinations at 1360/390/320px.
Actual PNGs were inspected; 477 integration tests pass with three optional skips.

Proof names use `data/ne-enacted-hyphen-`; the successful inspector browser
receipt is `data/ne-enacted-hyphen-browser-20261026-v4/receipt.json`, with
generic gallery v17/v18 receipts. Disk-pressure failures and every first-attempt
file remain preserved. Verified independent APFS copy-on-write copies recover
duplicate storage, without hardlinks or changed source/inspector bytes.
Complete downloads then pass with unchanged application code/data. The final
tracked audit is **460/494**, with the same 34 legacy failures and every report
field byte-identical to the saved source checkpoint; all **218 public-document
checks** and scoped Ruff/format/diff checks pass. Actual report/comparison:
`data/ne-enacted-hyphen-delivery-full-audit-20261026-v1.json` and
`data/ne-enacted-hyphen-delivery-full-audit-comparison-20261026-v1.json`.
Actual graph checkpoint **`7f67656`** is saved/pushed Hans-only. Independent
readback verifies all **427 tracked remote blobs**, Git and working bytes,
plus all 85 controls, with a clean worktree. Receipt:
`data/ne-enacted-hyphen-graph-save-checkpoint-20261026-v1.json`,
SHA-256 `a13cb397df39c2bf9dcca5f3b1f570ad0892a716d4d6310085800a9e5897e22a`.
Before-save proof:
`data/ne-enacted-hyphen-delivery-verification-before-save-20261026-v1.json`.
It binds all twenty primary proofs and removes only four inspected completed
fixture/Chrome subtrees. Every failed attempt and original remains retained.
No independent-human, filing-time,
party, rights or publication approval is promoted; large archives remain local
and ignored.

## Preserved source qualification: literal source-proven hyphen positions

This source-only checkpoint did **not** update the actual v25 baseline below;
the separately verified v26 propagation is now described above.
It qualifies seven original contexts / 14 complete raw views / 210,419
characters, accepting only the nine independently witnessed PDF byte/font/
glyph positions. All other character/identity/body/folio/date requirements
stay strict. The original whitespace-only module is byte-identical, the
entire earlier 51-context / 102-string law packet is preserved, and no raw
input string is normalized or relabelled as introduced text.

```bash
.venv/bin/python -I -B -m state_politics.bills.ne_enacted_hyphen_text \
  --parent-packet data/processed/ne-enacted-laws-qualified-20261026-v1 \
  --glyph-evidence data/ne-enacted-law-hyphen-glyphs-20261026-v2 \
  --independent-witness data/ne-enacted-law-hyphen-independent-20261026-v1.json \
  --gap-queue outputs/recreated-2023-2024-v36/chart-data/missing_retained_text.parquet \
  --out-dir data/processed/ne-enacted-hyphen-qualified-REPLAY
```

Use a fresh output directory. The original independent verifier and first
failed observer/log/crop under `data/` are required provenance inputs; all
are retained in the completed source ZIP. The source36 gap queue is externally
pinned to `819618e953b550d66e2bc38c56b2f6d6a1984c88af83f4628d83543b351759a6`.
Parent packet: `56732a9b8f5dc0881d877556c2b6883e7cfd7a8ee009606988fa0e8a7b1a9e31`.
Literal glyph report:
`4de7c1bdbd748ca7e4d304c7bf5e0d6aba8b476fdee91ed4b26d37cef5aa571d`;
independent direct-source witness:
`f523ba371bf03739ec49b618693eace20be49932917f4f7581baefbbe2162edc`.

Qualified manifest:
`16b98b79d853c1c72b22972b2f00ffb16abaa22b2551d20803001b5a9049e57b`.
Complete 50-member / 163,773,485-byte ZIP:
`data/ne-enacted-hyphen-qualified-complete-20261026-v1.zip`,
SHA-256 `6f0610466d986839bdb587f52e7026bff7cf62f7c23b42ec55f504f5a98c5a9e`.
Independent packet proof:
`data/ne-enacted-hyphen-qualified-independent-20261026-v1.json`,
SHA-256 `d4ad1924ed98ea0bde30f217ae0d7d1db452a4727f27fc5ce3c28aa49627d46c`.
It replays all 157,598 actual current metadata contexts, original raw strings/
dates, the prior parent packet/source candidates, all 31 earlier archive
manifest pins and all 85 controls; all source ZIP members match byte-for-byte.

Validation: 120 focused passes / 477 integration passes / three optional
integration skips; full tracked audit 460/494, the same 34 legacy failures
and every non-counter field unchanged from 458/492. Only two added passing
code-guide checks increase the counters. No HTTP, encoder execution, source
version reinterpretation or human/filing-time/party/rights/publication
approval follows from qualification alone. DATA-17 separately executes and
verifies the v26/token23 successor above; large raw/source/model archives
remain local and ignored.
The source checkpoint is saved/pushed Hans-only **`bbb01b9`**, with all 427
tracked remote blobs and all 85 post-save controls verified; worktree clean.
Final source receipt:
`data/ne-enacted-hyphen-source-final-delivery-20261026-v1.json`,
SHA-256 `6106e892aec04edcea44cef7484035fd001d47903ff31abfa3fe28c9be37ffb0`.

## Preserved v25 successor: explicitly versioned enacted-law evidence

**This checkpoint completed v25 / independent token cache v22.**
All 157,598 original contexts remain: **139,862 with text / 17,736 missing**
(1,263 NE). Unanimity gives 65,305 assigned / 74,557 abstained. Separate,
unpromoted majority gives 78,518 assigned / 23,816 rejected / 37,525 uncertain /
three excluded / 17,736 unavailable. Scores and 13,213 additional majority
assignments do not certify human accuracy.

Exactly 102 genuinely new strings / 361,645 characters / 97,596 tokens /
165 windows are encoded, zero old repeats or discarded tokens. All 179,733
old predictions, 169,391 cache rows, 157,547 other whole assignments and
85 controls remain unchanged. The new 51 contexts add 17 unanimity assignments /
34 abstentions and 19 majority assignments / six rejections / 26 uncertain.
All source-version notes and original dates remain intact: enacted text is
not introduced text, and approval does not replace introduction.

Preview41 manifest:
`88040e95f71e3fc2654f559c0f7069da126d693cd56b000a76897ae0d09feb1f`.
Job25 plan:
`faea0cae5666cf96f46c58ec01465a7e630b61214e368ece8baeaa3bec97c674`.
Prediction cache25: 754,864,128 bytes / 169,493 rows, SHA-256
`3d3e12166d8ea616092ae6c340c100cfa02e0904ba98881aefc8de9fcfb49b41`.
Independent token22: 40,390,656 bytes / 169,493 strings, SHA-256
`b7a0d198f142d6aba2180990896050751cec968df2fdff194a1ab8834f2f51a8`.
Parents v24/token21 remain byte-identical. Full replay performs no encoder work:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B scripts/audit_cycle_topics.py \
  --job data/processed/cycle-topic-inference-retained-text-20261026-v25 \
  --gallery outputs/topic-inference-retained-text-2023-2024-v23 \
  --verified-token-cache data/cycle-topic-independent-token-verification-cache-20261026-v22.sqlite \
  --verified-token-cache-sha256 b7a0d198f142d6aba2180990896050751cec968df2fdff194a1ab8834f2f51a8 \
  --out data/ne-enacted-law-tracked-cycle-audit-REPLAY.json
```

Current manifests: source36
`7195df736637821c2bd345b7a282b38382da8757b467f1f83e07843143c52ed1`;
topic23 `c02cb6b755b2167ab10bea579ba470482637b74b1d24f35a7189e372add3cefc`;
majority7 `4790c23da21afd83f97c95fd69ceb111dbe6b84f53468da42620c106b65dfccb`;
score7 `a9ff25deb1037b6260ec0e7254c825fa4b1712fb8657a429024c0531cf77c216`;
paired21 `ccc977cb8c595f8128b712c04ab842339fc7af7a7f057d62ab36d074339a0319`;
inspector7 `14aba6b0a6cb442a956cab9f5c3828941e2984f365add699de80622ee0f082cd`.
The selected-context pilot and metadata inference remain unchanged.

The actual root and fresh nested collections contain 27 charts / 108 exports /
35 complete CSVs; all 3,176 marks and identical image/table bytes reconcile.
Root manifest:
`326c3fef65eea0c5e2bd4f0f96b243926800ff63f5fd6c78af629ebc5e66fd49`.
The complete source35 collection, exact producer and copied authored README
remain in `outputs/preserved-current-source35-20261026-v1/`.
Actual Chromium checks all 102 complete bodies/scores/long windows, complete
NE query (2,128 contexts / 1,410 pairs / 10,577,035 characters), LB1143 query
(one context / two pairs / 38,665 characters), the complete 21-member source ZIP
and root/nested 27-image/180-link/seven-destination galleries at 1360/390/320px.
The graph source ZIP is 156,325,298 bytes, SHA-256
`ed5139e15beba74cd03fd1fc1a9aea5cac9d96664cd366a4fe3154136896c964`;
it has different compression from the source-checkpoint ZIP but identical
member payloads. All 37 older complete research ZIPs remain byte-identical.
Final suite: 453 passes / three optional skips; actual PNGs visually inspected.
Final tracked audit: **458/492**, with the same 34 legacy failures and every
report field identical to the saved source checkpoint; 216 docs checks/Ruff pass.
Actual report/comparison:
`data/ne-enacted-law-delivery-full-audit-20261026-v1.json` and
`data/ne-enacted-law-delivery-full-audit-comparison-20261026-v1.json`.
Proof names use `data/ne-enacted-law-`; browser receipts use that prefix and
generic gallery v15/v16. No human, filing-time, party, rights or publication
approval is promoted. Large source/model/research archives remain local and ignored.

The actual graph checkpoint is saved/pushed Hans-only **`706c263`**.
Independent readback checks the nontruncated GitHub tree, all **425 tracked
file hashes** and actual working bytes, plus all 85 post-save controls.
Clean-tree receipt:
`data/ne-enacted-law-graph-save-checkpoint-20261026-v1.json`,
SHA-256 `10f192286a30931a23797ffc5bb577407f401fe9e153a108373ba4fba1ebe76d`.
Before-save proof:
`data/ne-enacted-law-delivery-verification-before-save-20261026-v1.json`,
SHA-256 `2d61adc34a0a2fd765e11e067c106b70c9082bb1feab7c19813d8f36bd1ff593`.
It binds all twenty actual primary proofs, caches/controls/root+nested outputs
and only the four inspected completed temporary subtrees removed. All real
sources, failed attempts, downloads and historical collections remain intact.

## Preserved source qualification: separately typed enacted laws

This source-only checkpoint did not update the preserved v24 baseline below;
the separate verified v25 propagation is now described above.
It qualifies 51 existing contexts / 102 complete enacted-law views / 361,645
characters from three explicitly listed official-library books, retaining
all 4,330 raw page strings, every candidate/negative and original context.
The literal governor approval is a source-version date, never a repaired
introduction date. These bodies must not be described as introduced versions.
All scientific, human, filing-time, party, rights and publication gates remain
unpromoted.

```bash
.venv/bin/python -I -B -m state_politics.bills.ne_enacted_law_text \
  --source-capture data/processed/ne-enacted-laws-source-20261026-v1 \
  --source-readers data/processed/ne-enacted-laws-readers-20261026-v1 \
  --gap-queue outputs/recreated-2023-2024-v35/chart-data/missing_retained_text.parquet \
  --out-dir data/processed/ne-enacted-laws-qualified-REPLAY
```

Use a fresh output path. The source35 queue is externally pinned to
`712543ae5b85ed784ad6e968d24a0b33b55b032f2fa2e454753baac60e03a43b`;
capture/readers to
`a1331dc8bc45ff6a6c0f57857a53fba23d6118d3f41a009213db73ccb06780e0` /
`51da1e432ff2bfd1d59c49843dafd0e90befca112de737433b9eea81c9d50a36`.
Actual qualified manifest:
`56732a9b8f5dc0881d877556c2b6883e7cfd7a8ee009606988fa0e8a7b1a9e31`.
All source collection occurred in the separate four-controlled-GET capture;
qualification/replay performs no network or inference.

Generic replay checks the 157,598 real current metadata contexts. The complete
21-member / 153,746,734-byte source ZIP is
`data/ne-enacted-laws-qualified-complete-20261026-v1.zip`,
SHA-256 `81fe63871effb0c84aface5f832537d03a36928928677c079b1a5a1f953b6d70`.
Independent proof `data/ne-enacted-law-qualified-independent-20261026-v1.json`,
SHA-256 `e6c7d6f5efb523967af5aa3fdd7268e8d4b19bbbe427ecbfbc4d9e09bf1142cc`,
matches all bodies to the earlier independently reread 4,330 original pages,
all candidate spans, original dates/unknowns and enacted approval evidence.
It preserves all 30 prior archive-manifest pins, all 85 controls and actual
v24/token21 cache and graph hashes. The first failed observer is preserved:
only its preview binding lookup changes to the actual ordered `archive_text`
list; source/admission rules do not change.

Validation: 96 focused passes; 453 integration passes / three optional skips;
actual full tracked audit 458/492, the same 34 legacy failures and every
non-counter field unchanged from 456/490. Only two new passing code-guide
checks increase the counters. Source/ZIP/model archives remain local/ignored;
code pushes do not remotely back them up. DATA-14 must separately freeze,
execute and verify a v24/token21 successor before any actual graph refresh.
The typed-source checkpoint is saved/pushed Hans-only **`21dda3a`**; all 425
tracked remote blobs and 85 post-save controls match, with a clean worktree.
Final source receipt:
`data/ne-enacted-law-source-final-delivery-20261026-v1.json`,
SHA-256 `0fce498c50dfce4dccb7a3f8b9075a64cc10dfe86f32d009fea8c55c75c23294`.

## Preserved v24 successor: complete constitutional proposals

**This checkpoint is superseded by completed v25/token22 above.**
All 157,598 original contexts remain: **139,811 with text / 17,787 missing**
(1,314 NE). Preview40 manifest:
`08bacd43b88d5cc8547e71d23b1e25b47c48f6a5a789008461be69daec76e729`.
Job24 plan:
`05ee3aa8c4fc8ba201666c0aa9071712db6d0fa7d94664f10eac4ef6b622d8b9`.
Source35 manifest:
`8bf8627de0239cf375b51801a2c96c43b634fd73d52a1d615a34a409f53561c4`.
The 993-view NE archive preserves all 933 earlier alternatives; 354 other
partitions, all other remaining gap rows and 36 complete old source ZIPs are
unchanged. The new 83-member graph ZIP is 134,558,332 bytes, SHA-256
`d2ae24772e72d97fe7c0bd5ebb9dfce98807e274b48ee05f891a0c08f4b3f5f2`.

Actual new encoder work is exactly **60 strings / 233,061 characters /
53,166 tokens / 96 windows**, zero old repeats and zero discarded tokens.
All 179,673 earlier predictions, 169,331 cache rows, 157,568 other whole
assignments and 85 controls remain unchanged. New contexts add 16 assignments /
14 abstentions: **65,288 assigned / 74,523 abstained / 17,787 unavailable**.
Separate, unpromoted majority gives **78,499 assigned / 23,810 rejected /
37,499 uncertain / three excluded / 17,787 unavailable**, with 13,211 additional
assignments. Scores and agreement do not establish human accuracy.

Prediction cache24: 754,577,408 bytes / 169,391 rows, SHA-256
`fdf3e8dbdde014cb0f08b24c90c221a3e638218da5ca7350596c0111d23b2937`.
Independent token21: 40,370,176 bytes / 169,391 strings, SHA-256
`508bb035ab3116b21c38e9bcc4ad9dcc9ffd342048bbecc27f6dd0dabed43b3f`.
Parents v23/token20 remain byte-identical. Complete fifty-state replay does
not execute an encoder:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B scripts/audit_cycle_topics.py \
  --job data/processed/cycle-topic-inference-retained-text-20261026-v24 \
  --gallery outputs/topic-inference-retained-text-2023-2024-v22 \
  --verified-token-cache data/cycle-topic-independent-token-verification-cache-20261026-v21.sqlite \
  --verified-token-cache-sha256 508bb035ab3116b21c38e9bcc4ad9dcc9ffd342048bbecc27f6dd0dabed43b3f \
  --out data/ne-constitutional-tracked-cycle-audit-REPLAY.json
```

Current manifests: topic22
`70712ffec5b2d0757482d78d2440f2261dc25e90eaa99c488310a55dc446b96b`;
majority6 `0918641c5315071623e9b1f8819675940f047f9b3943311ad049f52ee9c0175f`;
score6 `626bd89db782554b5dd2325667a9342effaf9e9d51f9ba3de805a5768298834f`;
paired20 `aaad897221a24f33a5594a8806d08f7a668970038799b5df4723a4254cd5c111`;
inspector6 `a6b2955db603274318fbdbe226bf07c7465ffc0fb3eb070def854a99a29d52b6`.
The selected-context pilot and metadata inference remain unchanged.

All 27 current charts / 108 exports / 35 complete CSVs are genuinely rendered
in root and fresh nested collections. All 3,176 marks reconcile and image/
table bytes match. Current manifest:
`4a4670a00bb43a5102630cecec7affeef0765b45e4686436a07cf638f45c776c`.
The prior complete source34 collection, exact renderer and copied authored
README remain in `outputs/preserved-current-source34-20261026-v1/`.
Chromium checks all 60 new bodies, all 22 scores and long first/last windows,
complete NE query records (2,128 contexts / 1,308 pairs / 10,215,390 characters),
the complete LR2CA substring query (two contexts / three pairs / 100,809
characters), the full 83-member source ZIP, root/nested gallery images/links
and seven actual evidence navigations at 1360/390/320px.
Final suite: **433 passes / three optional skips**. Actual final tracked audit:
**456/490**, the same 34 legacy failures and every report field identical to
the saved constitutional source audit; 214 documentation checks and Ruff pass.
The report and exact comparison are
`data/ne-constitutional-delivery-full-audit-20261026-v1.json` and
`data/ne-constitutional-delivery-full-audit-comparison-20261026-v1.json`.
Proof names use
`data/ne-constitutional-`; browser receipts are
`data/ne-constitutional-browser-20261026-v1/receipt.json` and
`data/current-graphs-browser-20261025-v13/receipt.json` / `v14`.
No human gold, scientific approval, source-rights certification or website
publication is granted. Large original archives remain local and ignored.

The actual graph checkpoint is saved/pushed Hans-only **`d3c0d3b`**.
Independent readback of the nontruncated GitHub tree checks **all 423 tracked
files**, their saved Git hashes and actual working-file bytes, not just the
changed exports. All 85 post-save controls pass. The clean-tree receipt is
`data/ne-constitutional-graph-save-checkpoint-20261026-v1.json`,
SHA-256 `3f0546aa44977c8906eb5b46e9a69c6878e9d7291448e9e1edfa532e772a6636`.
Before-save proof:
`data/ne-constitutional-delivery-verification-before-save-20261026-v1.json`,
SHA-256 `df06ef3367b1cae0ed69ab498314353d41cb8433a6ebd40bc746bdb27fb7975c`.
It binds all twenty primary proofs, both caches, current/nested exports and
the exact four inspected completed temporary subtrees removed. Real evidence,
failed attempts, downloads and historical collections remain intact.

## Preserved source qualification: complete constitutional proposals

`data/processed/ne-constitutional-journal-qualified-20261026-v1/` qualifies
30 original contexts / 60 full reader views / 233,061 characters from the
retained official journals. Manifest:
`bc94cca96abecfb3471f0669ca8d0b7fb4ae7304ec3dd098366552afe6aabbea`.
The original source34 gap queue is externally pinned:
`f1631e502f6913dce8d7cd3a79ff63d6a5cef01fb71a29e24c6b073a6f6f86e7`.

The CA suffix is part of identity and never aliases an ordinary resolution.
Qualification requires the own 108th-session constitutional resolving clause,
the complete first/consecutive outer sections, constitutional submission
clause, every terminal ballot question and a literal following publication
boundary. Inline `Sec. 2.` and the nine observed journal proceedings headings
are separately typed rules; old defaults and packet semantics are unchanged.
Raw policy text is not trimmed or normalized. All 464 old dates / 928 strings,
all 95 new source candidates, every original row/unknown and all negatives
remain retained; no journal bill mention is promoted to a complete bill.

Independent raw evidence re-extracts all 106 new body pages and checks 136
body spans, alongside the exact earlier 11,500-page verification. The packet
observer checks all view/terminator spans and all 83 complete ZIP members.
Complete ZIP: 128,539,305 bytes, SHA-256
`f6cf0d59840d6ccb4bab8486d5137e7b32d58c8ba868a55f28687851388b5f5a`.
Proof: `data/ne-constitutional-journal-independent-20261026-v1.json`.
The real shared-loader replay passes against the entire 157,598-row preview
metadata table. All 76 focused cases and 433 integration cases pass, with
three optional integration skips; the 214 public-documentation checks pass.
The real tracked full audit is 456/490, with the same 34 legacy failures and
all non-counter fields unchanged; only the two added code-guide checks differ.
Its nonzero exit and comparison are retained in
`data/ne-constitutional-source-full-audit-20261026-v1.json` and
`data/ne-constitutional-source-full-audit-comparison-20261026-v1.json`.

This source-only checkpoint did not update classifications or graphs.
DATA-11 now completes the separate v24/token21 propagation above; old
caches and all approval flags remain unchanged. Original large archives remain
local and ignored, not backed up by a code push.

## Preserved v23 successor: literal-boundary journal evidence

**This preserved checkpoint is superseded by completed v24/token21 above.**
All 157,598 original contexts remain: **139,781 have text / 17,817 are missing**
(1,344 NE). Preview v39 preserves all 28 prior archive packets:
`b6de88fd5b671f800bd03805282fc89a12512f62f49cccb00b26bc838768efdb`.
Source34 manifest:
`54d341145440a6f8b9d10e7fbdd12e05b14cab6201bfea9b6966e4ae682d753d`.
Its NE archive has 933 views, preserving all 927 old alternatives. All 354
other partitions, remaining gap rows and 35 earlier complete ZIPs are unchanged.
The new graph-source ZIP contains all 71 complete members: 129,643,133 bytes,
SHA-256 `95971ff8c342ce86250e99bcbbb1a31dd22758bd3c83dacccb7e4d9420b2874e`.

Actual `data/processed/cycle-topic-inference-retained-text-20261026-v23/`
encodes only six new strings / 12,106 characters / 3,076 tokens / six windows,
zero old repeats and zero discarded tokens. All 179,667 old predictions,
169,325 cache rows, 157,595 other whole assignments and 85 controls remain
unchanged. All three new contexts abstain: **65,272 assigned / 74,509 abstained /
17,817 unavailable**. Unpromoted majority gives **78,481 assigned / 23,807
rejected / 37,490 uncertain / three excluded / 17,817 unavailable**. Its 13,209
additional assignments remain unchanged and are not independent validation.

Prediction cache23: 754,413,568 bytes / 169,331 rows, SHA-256
`0a7cff2a6644dbbe160ff6d65876b6600c800ac4ea94dc0cb1313318d0a11985`.
Independent token20: 40,357,888 bytes / 169,331 strings, SHA-256
`9477ea7982b06dc34414f1580babf4bce44439b470bb127323ab10c3ff2da59a`.
The parent v22/token19 caches remain byte-identical. Full fifty-state replay
requires no encoder:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B scripts/audit_cycle_topics.py \
  --job data/processed/cycle-topic-inference-retained-text-20261026-v23 \
  --gallery outputs/topic-inference-retained-text-2023-2024-v21 \
  --verified-token-cache data/cycle-topic-independent-token-verification-cache-20261026-v20.sqlite \
  --verified-token-cache-sha256 9477ea7982b06dc34414f1580babf4bce44439b470bb127323ab10c3ff2da59a \
  --out data/ne-journal-boundary-tracked-cycle-audit-REPLAY.json
```

Current manifests: topic21
`f6a50ad4c0fe3b49c9c93902adc97945028ea6064950c261d9c98b94f7a3ca4f`;
majority5 `b8402ed812ef6ef2eb0c284135cc185a3950a38965da369c086cbbf4b64a81aa`;
score5 `13dc32292cc75953b3ec149d6801c343c71b132d4bd18eb13664da68acc74583`;
paired19 `87e6d00c50ae7623b41f5b11c62a6a6b3e1f3febb36a77eb04e28e1f7d73de38`;
inspector5 `cf31906905dba1b271abf411ad7e5f024c81f750d9de373fed892ef3796ef3e8`.
Metadata inference and the context pilot remain unchanged.

The actual current root and fresh nested collections regenerate all 27 charts /
108 exports / 35 complete CSVs; all 3,176 marks and image/table bytes reconcile.
Current manifest:
`abd91ac3360a6fa95a0b0e8cc85e756c24625735f954ee656de71aa671467809`.
The old source33 collection and exact renderer remain preserved in
`outputs/preserved-current-source33-20261026-v1/`, including a copied authored
README. Chromium verifies root/nested 1360/390/320px galleries, all six complete
new source texts/scores/windows, all 2,128 NE query contexts / 1,248 pairs /
9,982,329 selected characters, the full LR282 query and the complete source ZIP.
The final suite passes 412 tests / three optional skips. Proof names use
`data/ne-journal-boundary-`; browser receipts are
`data/ne-journal-boundary-browser-20261026-v1/receipt.json` and
`data/current-graphs-browser-20261025-v11/receipt.json` / `v12`.
All original evidence, unknowns and scientific/publication gates remain intact.
Large source/model/research archives remain local and ignored, not backed up by
the code/graph push.
The final tracked full audit is 454/488, with the same 34 legacy failures and
every report field identical to the saved source checkpoint. Its real nonzero
exit and comparison are retained in
`data/ne-journal-boundary-delivery-full-audit-20261026-v1.json` and
`data/ne-journal-boundary-delivery-full-audit-comparison-20261026-v1.json`.
All 212 public-documentation checks and scoped Ruff pass.

## Preserved source qualification: literal publication boundaries

The separate packet
`data/processed/ne-journal-boundary-qualified-20261026-v1/` qualifies LR5,
LR282 and LR449: **three original contexts / six complete views / 12,106
characters**. It preserves the complete prior four-book packet, externally
pinned source33 gap queue, all raw fragments, literal terminator fragments,
exact original dates, all negatives and all original fields/unknowns.
Its opt-in boundary profile records a next introduced resolution separately
from the complete numbered operative body, or excludes only the proved
synthetic page-join newline before an explicit next-page disposition. Raw
policy whitespace is never trimmed or normalized; old schemas/defaults and
461 prior context dates / 922 strings remain unchanged.

Manifest SHA-256:
`2c3b261f145325d5f38b185105efb1f21ff659e294dcd6ccd94fd0b85810b03b`.
Complete 71-member ZIP: 123,684,706 bytes, SHA-256
`1a90af77df69b0ece35a4b9fb1778c66456725831027ed22146c68ae98c9b65e`.
The independent witness re-extracts all 11,500 unique raw reader pages and
checks eight body spans / six terminator spans, every source candidate and
NE disposition, all earlier dates/strings, 85 controls and zero human-
reservation overlap. Proof:
`data/ne-journal-boundary-independent-20261026-v1.json`.
The shared archive dispatcher replays all 71 members against the complete
17,820-row source33 queue. The combined suite passes 412 tests / three
optional skips; all 55 focused journal cases pass.
The actual tracked audit is 454/488, with exactly the same 34 legacy failures
and every non-counter field unchanged from 453/487. The real nonzero exit
and exact comparison are retained in
`data/ne-journal-boundary-full-audit-20261026-v1.json` and
`data/ne-journal-boundary-full-audit-comparison-20261026-v1.json`.
All 212 public-documentation checks and scoped Ruff pass.

Source qualification did not itself update classifications or graphs.
DATA-09 now completes the separate v23/token20 propagation above.
Raw source/model/research archives remain local
and ignored; no model, human-gold, source-rights or publication approval changes.

## Preserved v22 successor: explicit printed-day journal evidence

**This preserved checkpoint is superseded by v23 / token cache v20 above.**
The v21/v18 and earlier instructions below are preserved history, not targets
to overwrite. All 157,598 original contexts remain: **139,778 have text /
17,820 remain missing** (1,347 NE). Preview v38 preserves all 27 earlier archive
packets and appends only the 104-context explicit-day packet:
`981aacf89070044d807845403dc93f19e127c155b8e6e7ca5fa1bb2ce612c97c`.
Source gallery `outputs/recreated-2023-2024-v33/` has manifest
`9ea7d4a30f712461747c093eef0ba695a990b207b0b98ae8838850bed150498d`.
Its 927-view NE archive retains all 719 earlier alternatives; 354 other
partitions, all remaining gap rows and 34 earlier complete source ZIPs are
unchanged. The new source ZIP preserves all 60 packet members, not metadata
alone (122,199,519-byte graph container, SHA-256
`8da1cafb9eeec342462d0e886bc54da4f22c088068ed1dcba88d04567f182f4a`).

Actual `data/processed/cycle-topic-inference-retained-text-20261025-v22/`
processes only **208 new strings / 87,278 tokens / 208 windows**, with zero
old encoder repeats or discarded tokens. All 179,459 prior predictions,
169,117 cache rows, 157,494 other whole assignments, original context fields
and 85 controls are unchanged. New contexts add 38 assignments and 66
abstentions: **65,272 assigned / 74,506 abstained / 17,820 unavailable**.
The unpromoted majority candidate is **78,481 assigned / 23,804 rejected /
37,490 uncertain / three excluded / 17,820 unavailable**. These are provisional
model dispositions, not independent human accuracy.

Prediction cache v22 is 754,397,184 bytes / 169,325 rows, SHA-256
`fc6aa5c10c41086addbac53c754f6ef77078b2889ca9a5eaf8335490f6416e11`.
Independent token cache v19 is 40,353,792 bytes / 169,325 strings, SHA-256
`15103891f42c99c1aaad7270559d584975ee15365af43d54a5090c5595d4bc4f`.
Parent v21/v18 caches remain byte-identical. The full fifty-state source/token/
logit/window/assignment/108-member-inference-ZIP replay passes without an encoder:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B scripts/audit_cycle_topics.py \
  --job data/processed/cycle-topic-inference-retained-text-20261025-v22 \
  --gallery outputs/topic-inference-retained-text-2023-2024-v20 \
  --verified-token-cache data/cycle-topic-independent-token-verification-cache-20261025-v19.sqlite \
  --verified-token-cache-sha256 15103891f42c99c1aaad7270559d584975ee15365af43d54a5090c5595d4bc4f \
  --out data/ne-journal-day-tracked-cycle-audit-REPLAY.json
```

Current manifests: topic v20
`6b851e7d128960befc8af6e9664d1f220275ffc09908cf6128fc1dfcfbfdfb27`;
majority v4 `977d4e8446458627a14a779f2e3587f2b65a8616394f92f3462afe7ea8ee297a`;
full-score v4 `82223423ba0bf5e7d22c739819960b95558fa6e7f6970eabee422dc3116671f0`;
paired-input v18 `84af2d80f3456c2b05b0b1f9c542d5ed566c3ae376eb1159f9d98a1f6dbb61b3`;
inspector v4 `bc4da1d14aa4dde747593ce0f5cf6ed3e4e25195f169c3b4d84968c4e1d3c7b9`.
Metadata inference and the selected-context pilot are unchanged.

Serve the inspector with `scripts/serve_research.py --classifications
outputs/classification-inspector-2023-2024-v4`. Actual Chromium verifies all 208
new complete bodies, all 22 scores and complete windows. The full NE query has
2,128 contexts / 1,242 complete input/prediction pairs / 9,970,223 selected
characters; LR96 has one context / two pairs / 2,362 characters. The actual
source download contains every one of the 60 original files.

The current root and fresh `outputs/current-render-ne-journal-day-REPLAY-v1/`
galleries regenerate **27 charts / 108 exports / 35 complete CSVs**, reconciling
all 3,176 marks. Their image/table bytes are identical; Chromium passes at
1360/390/320px with 27 loaded images, 180 checked links, seven actual
methodology/evidence navigations and no overflow/errors/external HTTP.
The complete old source32 collection and producer remain in the ignored
`outputs/preserved-current-source32-20261025-v1/`. The authored output README
is copied, not removed by render preservation. Current manifest:
`e636e33205bfd0ec308c8e9552dad8e9db7fbf8e3eb02e7ed3bd22ebc56e2b78`.
The combined suite has **397 passes / three optional skips** (400 cases).
Proofs use `data/ne-journal-day-` prefixes; browser receipts are
`data/ne-journal-day-browser-20261025-v1/receipt.json` and
`data/current-graphs-browser-20261025-v9/receipt.json` / `v10`.
Raw source/model/research archives remain local and ignored. No human gold,
model promotion, party/source-rights certification or website publication is granted.
The actual tracked audit is **453/487**, with the same 34 legacy failures and
every non-counter report field identical to 452/486; its nonzero exit and exact
comparison are retained in `data/ne-journal-day-full-audit-20261025-v1.json`
and `data/ne-journal-day-full-audit-comparison-20261025-v1.json`.
All 211 public-documentation checks and scoped Ruff pass.

## Preserved v21 successor: expanded journal collection

This section's former extension instruction is superseded by v22/token19 above.

**Use completed v21 / independent token cache v18 for subsequent extensions.**
All earlier jobs, caches, source packets and graph snapshots remain immutable;
the historical v20 instructions below are superseded, not a request to rerun.
The actual union is **139,674 / 157,598 contexts**, with **17,924 missing**
(1,451 in Nebraska). Preview v37 retains all 26 earlier archive packets and
adds only the independently qualified collection:
`data/preview-cycle-evidence-v37/`, manifest
`38496e7f3039de43fd553ccfb34c10e73dbfcaa350cb483f871dbc127600fc35`.
All 354 other partitions and 221 prior NE archive views are unchanged; the
complete NE archive partition/download now has 719 views. Source gallery v32
preserves all 33 previous complete research ZIPs byte-for-byte:
`outputs/recreated-2023-2024-v32/`, manifest
`6eaba423ca12e9844577c9d8bfc889ddbeb5cf36268b68976695c2f89281fc55`.

The completed job is
`data/processed/cycle-topic-inference-retained-text-20261025-v21/`.
Only **498 fresh strings / 207,256 tokens / 502 windows** reached the encoder,
with zero old inputs repeated or tokens discarded. All 178,961 prior complete
predictions, 168,619 cached results, 157,349 other whole assignment rows,
original context fields and 85 controls are unchanged. New contexts contribute
95 unanimity assignments and 154 abstentions, for **65,234 assigned / 74,440
abstained / 17,924 unavailable**. The unchanged model, taxonomy and numerical
gates do not confer independent human validation.

Prediction cache v21: 169,117 rows / 753,946,624 bytes, SHA-256
`ea55351fa0c674d5fbcac06ded28f1cd39c67e298522f507411e87cbdf88134d`.
Independent token cache v18:
`data/cycle-topic-independent-token-verification-cache-20261025-v18.sqlite`,
169,117 strings / 40,312,832 bytes, SHA-256
`7cd0f336942e83bbb8b7b2280afe56641b7f3ce57b8172bbff27a2869e171c5e`.
Both parent v20/v17 caches remain byte-identical. All fifty states, complete
source strings, saved logits/windows, assignments and the full 108-member
inference ZIP pass the offline replay:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B scripts/audit_cycle_topics.py \
  --job data/processed/cycle-topic-inference-retained-text-20261025-v21 \
  --gallery outputs/topic-inference-retained-text-2023-2024-v19 \
  --verified-token-cache data/cycle-topic-independent-token-verification-cache-20261025-v18.sqlite \
  --verified-token-cache-sha256 7cd0f336942e83bbb8b7b2280afe56641b7f3ce57b8172bbff27a2869e171c5e \
  --out data/ne-journal-collection-tracked-cycle-audit-REPLAY.json
```

Topic v19 is
`165ea39bec929078917280778a63a16a1d8bbd93ab40209f7c95511657c4ae48`;
majority v3 is
`3bb04ed8259342b4c11818ff8edd01f8739cf395b168a5227df4e1fa0e780976`;
full-score v3 is
`4097d78124f32403be3cd3f5a4ec456124caeaff09144535d19a1b8a5af855d3`;
paired-input v17 is
`1418d6916527210a64007457c03e1d3222a4fc3dddd3c05fed1157d34c6e9e09`.
Majority remains unpromoted: **78,443 assigned / 23,754 rejected / 37,474
uncertain / three excluded / 17,924 unavailable**. The 13,209 additional
assignments do not establish accuracy. The metadata gallery and selected
context pilot are unchanged historical inputs.

Inspector v3 manifest:
`772d1f6ac32a5a4324d1e150aeb9d7f3d57c4dfb2fb5f28cfb0e33081092363c`.
Serve it independently with `scripts/serve_research.py --classifications
outputs/classification-inspector-2023-2024-v3`. Actual Chromium checks all 498
new full texts, all 22 scores and complete windows. Its full NE query exports
2,128 contexts / 1,034 complete input/prediction pairs / 9,615,271 selected
characters. The literal `LR 10` search deliberately exports all 12 substring
matches, including longer identifiers, with 19 source pairs; it is not a
single-record claim. The actual source ZIP has all 28 packet members. Its
54,784,646-byte graph-download container has SHA-256
`e3b28cdc0eafb0eb8f7363d83fc1474b8a01468baac257cc5f13f1616c342cf6`;
its complete payload matches the separately retained qualification packet.

The actual current collection again has **27 charts / 108 exports / 35 full
CSVs**, with 3,176 independently reconciled marks/cells. Both root and fresh
nested galleries pass Chromium at 1360/390/320px, with 27 loaded images,
180 checked links, seven actual evidence/methodology navigations and no
overflow/errors/external HTTP. Their image/table bytes are identical.
The prior source31 collection and its exact producer remain preserved under
`outputs/preserved-current-source31-20261025-v1/`; legacy root PNGs are intact.
Current manifest:
`a7c0e004bc9853c5293e49f03c0d3129dde655024a5e932ca7e329cfb56ff467`.
The combined regression suite has **390 passes / three optional skips**:
`data/ne-journal-collection-final-regressions-20261025-v1.xml`.
Proofs use `data/ne-journal-collection-` prefixes; browser receipts are
`data/ne-journal-collection-browser-20261025-v1/receipt.json` and
`data/current-graphs-browser-20261025-v7/receipt.json` / `v8`.
No source rights, human gold, model promotion or website publication is granted.
The actual tracked full audit is **452/486**, preserving the same 34 legacy
failures and every non-counter report field from 450/484. Its nonzero exit and
exact comparison are retained in
`data/ne-journal-collection-full-audit-20261025-v1.json` and
`data/ne-journal-collection-full-audit-comparison-20261025-v1.json`;
210 public-documentation checks and scoped Ruff pass.

## Preserved v20 successor: first Nebraska journal propagation

This historical checkpoint's former extension instruction is superseded by
completed v21/token18 above. Keep its commands and original evidence intact.

**Use completed v20 / independent token cache v17 for subsequent source
extensions.** This dispatch instruction supersedes historical "future extension"
instructions below. V19 / token v16 and every earlier source/model bundle remain
immutable historical checkpoints, not targets to overwrite.

The source union is **139,425 / 157,598 contexts**, leaving **18,173 gaps**,
including 1,700 in Nebraska. Preview v36 retains all 25 previous archive
packets and other source dependencies and appends only the qualified journal:
`data/preview-cycle-evidence-v36/`, manifest
`b5fe4a6e257b15a5fdd841e012c6dfe72a11382934756ef847c9bfe2b5026bcf`.
All 354 other complete source partitions and all original context bytes remain
unchanged. Nebraska's five earlier archive views survive alongside 216 new
views; its complete partition and download contain 221 views, not 216.
All 32 earlier complete source ZIPs are byte-identical. The new source gallery
is `outputs/recreated-2023-2024-v31/`, manifest
`03898b27177f88bce51330e9e9ce01eb739515f380d65a1980e3f21641dbfb50`.

Actual inference is
`data/processed/cycle-topic-inference-retained-text-20261025-v20/`.
It preserves all 178,745 earlier predictions and encodes only **216 new exact
strings / 87,803 tokens / 216 windows**, with no discarded tokens or old
encoder inputs repeated. Its 178,961 complete source views produce **65,139
unanimity assignments / 74,286 abstentions / 18,173 unavailable contexts**.
The newly observed contexts yield 48 assignments and 60 abstentions; the latter
were previously unavailable, not changed old predictions. The unchanged model,
taxonomy, thresholds and human reservations confer no independent validation.

The successor prediction cache has 168,619 rows / 752,889,856 bytes, SHA-256
`57a5cbb278088e0fa2d1ba878a023a7f7ea890c78abe678eab3b6a5cbf8f5de9`.
The independent cache is
`data/cycle-topic-independent-token-verification-cache-20261025-v17.sqlite`,
168,619 strings / 40,235,008 bytes, SHA-256
`c0b07f7e8d3ce3eafb8566dea6854c85b894397be3f471b3324fba1ea47c4687`.
Both original v19/v16 cache hashes remain unchanged. The initial token observer
computed and committed its entire cache before a SQLite URI attachment error;
the retained failure and read-only completion prove that no model or token
work was repeated to finish verification.

The completed topic gallery is
`outputs/topic-inference-retained-text-2023-2024-v18/`, manifest
`4cb804252a086e1a89935bc8336d6ae39ba1f0971a8772edc6e49f588b7d2f03`.
Majority v2 assigns 78,348, with 23,652 learned rejections, 37,422 uncertain,
three excluded and 18,173 unavailable contexts; it remains unpromoted.
Its manifest is
`a02d80df8c64d5c22a4ddbac8a4b0f1c293175e53e58c39d7b741af2025b1d87`.
Full-score v2 is
`0b8a9d80790d16b76f0cb2434548bcdd9381bb497e68777ed5873821c45d9b4a`;
paired-input v16 is
`187634008ccc5bb1ca95f92a3fcdb1c398abfe72e2c98018f67a8f1b522c9921`.
The unchanged metadata gallery and selected-context pilot remain historical
inputs; no training or context experiment was rerun.

Inspector v2 preserves complete original/candidate rows, full texts, all 22
scores and every window in
`outputs/classification-inspector-2023-2024-v2/`, manifest
`e51d407243344bf00f03a076dffc70dab9627c38056a1fa3f438661009b8b59c`.
Serve that current bundle independently:

```bash
.venv/bin/python -I -B scripts/serve_research.py \
  --classifications outputs/classification-inspector-2023-2024-v2 \
  --port 8765
```

The full fifty-state source/token/logit/window/assignment/108-member-ZIP replay
is `data/ne-journal-tracked-cycle-audit-20261025-v1.json`. Reproduce against
the completed source job without an encoder or mutable token cache:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B scripts/audit_cycle_topics.py \
  --job data/processed/cycle-topic-inference-retained-text-20261025-v20 \
  --gallery outputs/topic-inference-retained-text-2023-2024-v18 \
  --verified-token-cache data/cycle-topic-independent-token-verification-cache-20261025-v17.sqlite \
  --verified-token-cache-sha256 c0b07f7e8d3ce3eafb8566dea6854c85b894397be3f471b3324fba1ea47c4687 \
  --out data/ne-journal-tracked-cycle-audit-REPLAY.json
```

The focused integration suite has 369 passes / three optional fixture skips.
Its fresh fixtures must be inside ignored project `data/`, as required by the
existing source/export/server boundaries; do not relax those guards to use
system temporary directories:

```bash
.venv/bin/python -I -B -m pytest -q \
  tests/test_archive_text.py tests/test_billcommons_nv_text.py \
  tests/test_billcommons_text.py tests/test_classification_inspector.py \
  tests/test_current_graphs.py tests/test_cycle_site.py \
  tests/test_ne_journal_text.py tests/test_plotting.py \
  tests/test_recreated_graphs.py tests/test_research_server.py \
  --basetemp=data/ne-journal-regression-fixtures-REPLAY
```

## Nebraska official journal resolution recovery

The pinned source is the complete 2024 Volume 1 of Nebraska's official
Legislative Journal, independently retained by the State Library. The
qualified packet is `data/processed/ne-journal-qualified-text-20261025-v1/`;
its manifest is
`d4496cc9af71061371c8575acaae3257e074488d06e59d8c7deaf1114bcbef61`.
Replay from the already saved source and two complete page-reader streams:

```bash
.venv/bin/python -I -B -m state_politics.bills.ne_journal_text \
  --source data/processed/ne-journal-source-20261025-v1 \
  --readers data/processed/ne-journal-readers-20261025-v1 \
  --gap-queue outputs/recreated-2023-2024-v30/chart-data/missing_retained_text.parquet \
  --out-dir data/processed/ne-journal-qualified-text-REPLAY
```

No network or model is invoked. The raw PDF, capture inventory, complete
two-reader inventory and original gap queue have fixed external SHA-256 pins.
All 1,370 pages per reader survive, including non-policy and rejected content.
Accepted views retain exact raw-page spans and original whitespace; comparison
keys do not replace source text. Ordinary resolution number, 108th Legislature,
Second Session, exact original introduction date, complete resolving clause and
explicit journal boundaries are mandatory. The source's date is checked
against the original context, never used to repair or invent that date.

The new schema dispatches through `archive_text.load_archive` and is supported
by evidence/graph builders with archived producer code. Its 108 qualified
contexts and 216 reader alternatives remain unapproved research inputs.
The completed downstream successor is described above; source qualification
alone never certifies its classifications.
The full source ZIP is `data/ne-journal-qualified-complete-20261025-v1.zip`,
not a metadata-only download. Qualification/provenance validation never creates
human gold, filing-time originality or redistribution permission.

## Expanded official journal collection

This is a separate source qualification, now propagated into **v21 inference
and its current graphs** as described above. The official 2023 catalogue identifies both
First Session volumes; three bounded GETs retained that catalogue and both
complete books. The existing 2024 Second Session book is reused unchanged.
All four PDFs and both full reader streams remain in the packet.

The corrected collection qualifies **249 original missing contexts / 498
complete views / 862,477 policy characters**: 78 contexts from 2023 Volume 1,
164 from Volume 2 and seven from 2024 Volume 1. The earlier 166-context packet
is preserved and still replays. Its 83 reader disagreements were printed
running headers such as pypdf's `LEGISLA TIVEJOURNAL120`, not policy conflicts.
Schema v2 accepts whitespace differences inside that fixed page-prefix
literal, records its exact removed text/span/hash and retains untouched raw
pages. It does not change whole-body whitespace-only agreement, original
dates, numbered identities, session clauses or complete-ending requirements.
Policy lookalikes inside a body are not removed.

```bash
.venv/bin/python -I -B -m state_politics.bills.ne_journal_collection \
  --first-source data/processed/ne-journal-first-session-source-20261025-v1 \
  --first-readers data/processed/ne-journal-first-session-readers-20261025-v1 \
  --second-source data/processed/ne-journal-source-20261025-v1 \
  --second-readers data/processed/ne-journal-readers-20261025-v1 \
  --gap-queue outputs/recreated-2023-2024-v31/chart-data/missing_retained_text.parquet \
  --out-dir data/processed/ne-journal-collection-qualified-REPLAY
```

Saved packet: `data/processed/ne-journal-collection-qualified-20261025-v2/`,
manifest `3948e5160a060654ee1c65b1c334e3366dee9fb168b68f3a046ed43f5f877123`.
The schema routes through the generic archive loader and evidence/graph
builders, which archive both producers. Schema v1 replays with its original
header behavior and IDs; v2 uses a new namespace. The sealed 108-context
parser/packet remains unchanged. All original context fields, all 1,700 gap
dispositions and all 857 source candidates remain, including malformed and
unmatched records. These local, ignored source files are not backed up by
pushing code, and qualification grants no model or publication approval.

Independent proof `data/ne-journal-collection-independent-20261025-v2.json`
re-extracts all **8,274 page strings**, verifies **812 raw body spans / 520
literal excluded prefixes**, and proves all 332 previously qualified policy
strings byte-identical. It also verifies that malformed boundary candidates
remain rejected, not that every negative is a complete body. All 85 frozen
controls and human-review reservations remain unchanged. The complete
28-member ZIP is `data/ne-journal-collection-qualified-complete-20261025-v2.zip`
(52,353,556 bytes), SHA-256
`93db5a0079a58cb26ba3ad768651e5771b2376d132a06a9581710bd273d05d70`.
All 276 source integration tests pass, with three optional fixture skips.

## Explicit printed-day source qualification

This was a separate source qualification, now propagated into the verified
v22/token19/source33 delivery above; qualification alone never certified it.
The official Library Commission journal catalogue explicitly lists 2024 Volume 2.
Exactly two bounded GETs retain that catalogue and its listed 33,072,638-byte /
1,613-page PDF, without redirects, retries, native endpoint access or a new
robots lookup. Both complete readers retain all 3,226 physical page strings.
The PDF SHA-256 is
`2cf21b90fb163a1f1e20220996e6af5b490221095c3cb4b446b1f9b4d99e8355`.

Daily opening pages can print `1131` before `SIXTY-THIRD DAY - APRIL 17, 2023`.
The opt-in explicit-day profile recognizes that anchored literal prefix,
instead of carrying forward April 14 from the preceding proceedings. LR96
and LR336 are concrete preserved negatives explained by this layout. The
original introduction dates are never modified or relaxed; all prior v1/v2
defaults, IDs, packets and cached predictions remain intact.

The new `state-politics.nebraska-journal-day-text.v1` packet supplies
104 candidate recoveries / 208 complete views / 354,952 characters:
88 from the later 2024 book and 16 from explicit day openings in the older books.
Its complete payload embeds both older packets, the full later capture/readers,
the original current gap queue and all accepted/rejected candidates. Every
prior 357-context date / 714 policy-string comparison passes unchanged.
The three remaining ordinary-resolution negatives remain excluded.

```bash
.venv/bin/python -I -B -m state_politics.bills.ne_journal_day_text \
  --parent-collection data/processed/ne-journal-collection-qualified-20261025-v2 \
  --sealed-packet data/processed/ne-journal-qualified-text-20261025-v1 \
  --late-source data/processed/ne-late-journal-source-20261025-v1 \
  --late-readers data/processed/ne-late-journal-readers-20261025-v1 \
  --gap-queue outputs/recreated-2023-2024-v32/chart-data/missing_retained_text.parquet \
  --out-dir data/processed/ne-journal-day-qualified-REPLAY
```

Saved packet manifest:
`ac27e166a4d5a0481106391e4b70b38ba9d131ab511f18c02a8f1ca88616bb9a`.
Full raw-source/date/span and complete-archive verification is separate from
the producer replay; no source qualification creates human gold, filing-time
party certification, redistribution rights or website approval.

Independent verification now passes:
`data/ne-journal-day-independent-20261025-v1.json`. It re-extracts **11,500
unique original reader-page strings**, verifies 350 raw body spans / 226
literal prefix exclusions and observes 294 number-first printed day headers.
All 357 prior dates / 714 policy strings, 85 frozen controls and model-blind
reservations are unchanged. Every new context was genuinely unavailable with
a null topic in v21; no graph or encoder work is performed by qualification.
All 1,037 positive/negative candidates and 1,451 gap dispositions remain.

The complete 60-member ZIP is
`data/ne-journal-day-qualified-complete-20261025-v1.zip` (116,711,254 bytes),
SHA-256 `e906bbc3b05d492adcdb35eb7740022529c259cbe925c47ebaad66df043fa348`.
Forty focused tests and 283 archive/evidence/source-graph integration tests
pass, with three optional integration fixture skips; 211 public-documentation
checks and scoped Ruff pass. Generic loading also verifies all 157,598 current
metadata records. These ignored sources are local, not backed up by code pushes.
The remaining three ordinary negatives are retained boundary issues, including
LR449's next-page disposition and LR5/LR282's adjoining introduced headers;
they are not falsely described as inaccessible publisher documents.

## Recreated graph bundle

### Current dual-background graph collection

The current entry point is `outputs/index.html`, not the thirteen historical
root PNGs or a guessed versioned gallery. The tracked collection contains
**27 genuinely regenerated charts / 108 exports**, organized by evidence,
original topics, majority candidate, full scores, input comparison and context
experiments under both `outputs/substack/` and `outputs/themarginoferror/`.
Substack uses `#F7F5F0`; The Margin of Error uses `#F5F5F5`, matching the local
`uk_decline` reference. Both versions preserve identical marks, axes and data.
PNGs are 300 dpi; SVG labels remain editable text. No website is deployed.

The October 29 session/calendar comparison adds aligned exact counts for its
three supplied scopes, including small overlaps that are difficult to estimate
from the shared scale. Current manifest:
`5be564561d6693f7cc08a3951b1fbd0ea68010bf800052c753c2ef338119c014`.
Its 145 artifacts total **19,012,550 bytes**, excluding the manifest and original
research archives. All existing bar values/limits, 47 unsupplied scopes, other
104 images, all 35 complete CSVs, original ZIP and gallery are unchanged.
Only the four session-chart PNG/SVG files and manifest change. Original
`392b1a7c` collection/README/exact renderer:
`outputs/preserved-current-session-counts-20261029-v1/`. Graph-only replay:
`outputs/current-render-session-counts-20261029-v1/`. Proofs:
`data/session-comparison-counts-20261029-v1/`.

The earlier October 28 bill-evidence repair aligns all state rows across its three
metadata-channel panels and labels all 150 count/unknown cells. Shared linear
limits are extended equally for label space; no bar value, missingness or
cohort changes. Its preserved checkpoint manifest:
`392b1a7cecb603be4c2e4e2ff834dae08927ed2827edc29e8e7198fb09d3ce71`.
At that checkpoint, 145 artifacts totalled **18,934,809 bytes**, excluding the manifest and original
research archives. Only the four bill-evidence PNG/SVG files and manifest change;
the other 104 images, all 35 complete CSVs, original ZIP and gallery stay
byte-identical. The preceding `548f9cb8` collection, README and exact renderer are
preserved at `outputs/preserved-current-bill-evidence-20261028-v1/` using
independent native clones. Proofs: `data/bill-evidence-readability-20261028-v1/`.

The October 28 recovered-text chart repair labels all exact per-state cohort
totals, including Massachusetts's single context and Maine's "No cohort contexts".
Its caption distinguishes 50 accounted states from 49 with cohort contexts,
not actual legislative volume. Its preserved checkpoint manifest:
`548f9cb890b55642a2556c91ca88c6dd86eae68306ab3bd6670e519325cc1ea8`.
Only this chart's four PNG/SVG variants and its gallery/manifest change.
At that checkpoint, 145 declared artifact files totalled **18,636,751 bytes**,
excluding the manifest and separately retained research archives. The later
bill-evidence repair's current handoff budget is above.
All 35 CSVs, the original complete chart ZIP and the other 104 images remain
byte-identical. All numeric mark values are preserved. The prior collection,
README and exact Git-bound renderer remain independently preserved at
`outputs/preserved-cohort-counts-20261028-v1/`. Actual root/replay Chromium
checks pass at 1360/390/320px, as does the public current-integrity audit.
Proofs: `data/cohort-chart-readability-20261028-v1/`.

The earlier October 27 presentation-only refresh added aligned exact unanimity/majority
counts beside the topic-comparison bars, including explicit zeros. Its historical
manifest was `16f6cee05fc0c72cec23d1340531af97b388f487435c52ee720379191f57e471`.
Its declared payload was 18,374,672 bytes, excluding the manifest and original
research archives. All 35 CSVs and the other 104 image exports are unchanged;
all 42 numeric cells, 3,176 original marks, complete CSV ZIP, 13 legacy PNGs and
85 controls independently reconcile. Both actual backgrounds were visually
inspected; root and nested Chromium checks pass at 1360/390/320px.
The prior collection, authored README and exact renderer remain in
`outputs/preserved-current-topic-counts-20261027-v1/` using independent native
clones. Proof: `data/topic-count-readability-current-graphs-independent-20261027-v1.json`.
No population/model/source snapshot or scientific promotion is involved.

All 35 complete original chart CSVs are copied byte-for-byte to
`outputs/chart-data/`; `outputs/current-chart-data.zip` contains those full
tables, not metadata or a visible-page subset. The original full-policy-text
research ZIPs remain in the separately linked local source galleries and are
not replaced by the small chart-table download.

The renderer externally pins the manifests for evidence v37, original-rule
retained-text topics v24, majority v8, full-score diagnostics v8, paired-input
comparison v22 and the unchanged context pilot v1. It validates each entire input table before
rendering and rechecks inputs afterward. The output manifest records all
original bindings, exported hashes, actual bar/heatmap values, axes geometry
and label extents. It refuses an existing collection rather than overwriting
the historical evidence:

```bash
.venv/bin/python -I -B scripts/render_current_graphs.py \
  --out-dir outputs/current-render-REPLAY
# Equivalent Make target, with the saved input bundles present:
make figures GRAPH_OUT=outputs/current-render-REPLAY
```

Methodology and original-evidence links are resolved relative to the actual
output directory, including nested replay paths. Both root and nested galleries
are verified in Chromium with actual navigation to all seven destinations,
not just checks that the link text exists. The replay still needs its original
local source bundles; it does not download or publish them automatically.

The original `make figures` producers are now explicitly `make legacy-figures`;
they require `ALLOW_LEGACY_ANALYSIS=1` and are not the current study's
regeneration path. Party/platform attention
comparisons remain withheld: graph polishing does not resolve independent
human validation, operative-platform, event-time party or source-rights gates.
Original unanimity and unpromoted majority remain distinctly labelled.

### Per-bill classification evidence inspector

The inspector exposes individual source-backed model decisions without
promoting the majority rule or altering any prediction. Build a new bundle
from the externally pinned current majority gallery and completed v26 job:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B scripts/build_classification_inspector.py \
  --job data/processed/cycle-topic-inference-retained-text-20261026-v26 \
  --majority-gallery outputs/topic-majority-2023-2024-v8 \
  --majority-sha256 61fd909f4892b8d7a1199d433293e938bb14601fb2a95c20bfdd7243b415231b \
  --out-dir outputs/classification-inspector-2023-2024-REPLAY
```

The current actual bundle is `outputs/classification-inspector-2023-2024-v9/`,
manifest `10e0a930c0d6f8f91e153612f0701d88c94b735baff502650d85e7668316d2e5`.
It is a UI-only revision over v8: all 160 data/index/original-producer artifacts
are byte-identical independent native clones, including the complete source
ZIP. Only HTML/JavaScript change, and two exact update-producer/dependency files
are added. All earlier bundles remain preserved unchanged; no population
builder, inference or source acquisition is rerun.
Serve it independently through the loopback workspace; no evidence, session
or review bundle is required:

```bash
.venv/bin/python -I -B scripts/serve_research.py \
  --classifications outputs/classification-inspector-2023-2024-v9 \
  --port 8765
```

Every bundle flag is optional, but at least one explicit bundle is required.
The home page links only to bound bundles; all unbound routes return 404.
Do not open the interactive page with `file://` or a server that silently
ignores byte-range requests. If all the other saved bundles are available,
the existing combined workspace remains supported:

```bash
.venv/bin/python -I -B scripts/serve_research.py \
  --evidence data/preview-cycle-evidence-v42 \
  --sessions data/processed/verified-session-comparison-2023-2024-v3 \
  --review data/human-review-native-20261021-v3 \
  --sources data/processed/native-inventory-catalog-2023-2024-v2 \
  --graphs outputs/recreated-2023-2024-v37 \
  --topics outputs/topic-inference-retained-text-2023-2024-v24 \
  --classifications outputs/classification-inspector-2023-2024-v9 \
  --port 8765
```

The workspace home links to `/classifications/index.html`. This is an explicit
optional research mount, not a public deployment or a blind-review input.
The server hashes every whitelisted artifact before binding, refuses changed
or linked files and foreign Hosts, and serves exact single byte ranges with
their original content length. HEAD remains a full-representation header
request. Unsupported/invalid ranges never become a metadata-only record.

All 157,598 contexts preserve the original assignment plus separate majority
status/topic. State/topic/title/disagreement filters and pagination never
change the eligible source population. Source details show the complete
22-output whole-document and supporting-window vectors, including learned
rejection, all saved overlapping-window votes and complete window text.
Supporting scores are not whole-document confidence; no output is
renormalized away. Excluded sources have no scores, missing bodies have no
synthetic text, and empty state cohorts do not establish zero activity.

The fifty state JSON indexes contain SHA-bound byte references into complete
copied input/context/prediction JSONLs. The browser verifies every fetched
record and selected text hash before displaying it. UTF-16 spans and
supplementary-character positions preserve exact Python source offsets.
The complete query export is one physical JSONL row per matched context:
`schema`, the entire raw `context`, and all complete raw `inputs` and
`predictions`. It streams every matching row, not just the current page, and
retains original unknowns, full policy texts and large-integer lexemes.
An unavailable/corrupt source aborts the export; no partial or metadata-only
download substitutes for it.

In a secure browser exposing the native save picker, the download button obtains
a destination during the trusted click, then awaits each validated UTF-8 chunk
write. It closes the file only after the complete query succeeds, and attempts
to abort on source, write or close errors without masking the original failure.
Cancellation restores the controls without fetching records. Unsupported
browsers retain the complete Blob-based download; that fallback does not gain
the direct-file memory benefit. No query-size cap or metadata-only substitute
is introduced. The loaded state index and current complete record still require
memory; this removes the query-sized output Blob, not every allocation.

All 87 focused inspector/server/storage tests pass. A generated 10,000-context,
494,716,670-byte query completes without a Blob under a 32-MiB old-space limit;
the measured total V8 heap limit is 83,886,080 bytes. This is a bounded synthetic
writer test, not model evaluation or a browser-memory certification.
Actual Chromium tests use real OPFS writable handles in place of the picker
dialog, verify a trusted click before the first record fetch, full 35,831,484-byte
NE output, complete LB989 output and the unsupported-picker fallback. Cancellation
and injected late-read/write errors preserve the existing complete file.
The operating-system picker dialog itself is not automated. All 2,128 full-state
contexts, 1,424 input/prediction pairs and 10,787,454 selected policy characters
match their frozen raw records byte-for-byte; the one-context LB989 query retains
both source alternatives and 60,630 policy characters.
Proofs: `data/streaming-inspector-browser-20261028-v2/receipt.json` and
`data/streaming-inspector-query-replay-20261028-v1.json`. The failed first
browser observer/profile/logs remain retained; the corrected harness binds
native fetch to its Window receiver without changing the application or data.

Fifty complete `states/STATE.html` tables and the unchanged original full-source
majority research ZIP provide no-JavaScript access. The ZIP is
`research-data/complete_inference_and_majority_candidate.zip`, SHA-256
`328e86e56ef4b5d085fdcab41c641cbfef5d4766f63de0061b1f357d66986078`.
It contains all original full inference members and candidate outputs, not the
inspector's derived index in place of research data. The current manifest binds
164 artifacts and all original unapproved research flags remain false.

#### Preserved first journal-inspector checkpoint

The earlier journal inspector's original research ZIP has SHA-256
`e6d72f0dc467cf9bf80deded92c7b43ed37877d744031f2e06b1a2bcef96b379`; its
162-artifact manifest is
`e51d407243344bf00f03a076dffc70dab9627c38056a1fa3f438661009b8b59c`.
Its preserved Chromium proof is `data/ne-journal-browser-20261025-v1/receipt.json`:
all 216 new complete reader bodies, every score vector and complete first/last
window, at desktop/390px/320px with no overflow, JavaScript errors or external
HTTP requests. Its actual all-Nebraska query preserves all 2,128 contexts /
536 complete input/prediction pairs / 8,752,794 selected text characters; a
separate LR315 query preserves its complete context and both full inputs.
Every raw field, unknown and large integer matches in
`data/ne-journal-query-download-replay-20261025-v1.json`. The actual downloaded
14-member journal ZIP includes the complete raw PDF, both full reader streams
and all accepted/rejected evidence, not metadata-only pointers.

The following are preserved **v1** regressions, not new v2 browser executions.
Independent all-record/range/Unicode replay is
`data/classification-inspector-independent-replay-20261024-v1.json`.
Actual browser proof is
`data/classification-inspector-browser-20261024-v3/receipt.json`.
It checks desktop/mobile and keyboard/no-JavaScript behavior, the complete
15,384,142-character Ohio input, supplementary Unicode, source alternatives,
all scoreless exclusions and fourteen complete first/last window texts.
The actual 154-context full-state and fifteen-context filtered query downloads
are independently compared field-for-field with their entire original
contexts, source inputs and predictions in
`data/classification-inspector-query-download-replay-20261024-v3.json`.
The complete research ZIP is also byte-identical. The failed first observer
is preserved; successful observers use separate directories for successive
same-named downloads rather than overwriting the earlier export.
No source collection, encoder, training, annotation, calibration or promotion
runs during the build; all scientific/publication gates remain closed.
The actual tracked audit is
`data/classification-inspector-post-save-full-audit-20261024-v1.json`:
446/480, with the same 34 legacy failures and all other preceding report
fields unchanged. This is not a passing scientific-validation claim.

### Longer-context and cross-input experiments

The selected-cohort pilot is a separate inference experiment, not a population
rerun, retraining or validation against independent human labels. It uses the
same frozen model and strict-majority policy on all 109 selected contexts and
255 complete source views. Reproduce into a **new** output directory:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
  .venv/bin/python -I -B scripts/pilot_context_windows.py \
  --job data/processed/cycle-topic-inference-retained-text-20261024-v19 \
  --majority-gallery outputs/topic-majority-2023-2024-v1 \
  --majority-sha256 ea392fae9eed070199e47d894f6a93c15ac4bc4af1e4aeb470676b565afe6845 \
  --casebook outputs/assistant-advisory-topic-review-2023-2024-v7 \
  --casebook-sha256 df01ac822204da4b5c92b8d157bce574bb1c164358bbfdc31e1a3870f1e4298b \
  --out-dir outputs/topic-context-pilot-2023-2024-REPLAY \
  --allow-provisional
```

`plan.json` freezes all original source bindings, selected IDs, runtime,
producers, weights and profiles before encoder work. The unchanged training
configuration is 1,024 tokens / 128 overlap; native model capacity is 8,192.
The explicit inference profiles are 4,096/512 and 8,192/1,024. No trained
manifest is monkeypatched, no policy text is truncated, and every original
source and context field remains recoverable.

The separate SQLite cache binds each window to model run, complete input SHA,
token interval and actual wrapped encoder IDs. It reuses only exact matching
windows, never an old short-document decision in place of larger-window
logits. Longest-first batches have an 8,192 padded-token budget and maximum
batch size two. Cache windows and complete batch receipts commit atomically.
Repeating the same command with `--resume` verifies the frozen plan and reuses
completed exact windows. A completed resume verifies all artifact and archive
bindings without loading the encoder or writing the cache. Interrupted ZIP
finalization is explicitly refused, not returned as successful completion.

Actual results are in `outputs/topic-context-pilot-2023-2024-v1/`. The
1,024-token majority assigns seventy selected cases; 4,096 assigns 74 and
8,192 assigns 79. Corresponding disagreements with assistant proposals are
ten, thirteen and sixteen, with two advisory-unresolved assignments in each
condition. The longer profiles also lose two and one existing assignments.
Rescue-only comparisons preserve all primary assignments and assign 76 or 80,
but have fourteen or seventeen differing topics. These selected diagnostics
have been used for hypothesis development and are not untouched evaluation,
representative accuracy, proof that the proposals are correct, or grounds for
population promotion.

The two PNG/SVG pairs and four complete tables describe the selected
comparisons and actual encoder work. The complete 285-member ZIP retains all
255 full source texts, complete original input/prediction/context records,
token IDs/offsets, all 4,776 cached windows, 768 atomic batch receipts, raw and
rescue-only decisions and executed producers. It is **not metadata-only**.
Manifest:
`ef7857499a3783fed82a8884979b01f3f7b72c7c46afce16246fd24e24be5a6e`.
`complete_download.json` separately pins that manifest and
`research-data/complete_context_window_pilot.zip`:
**57,192,305 bytes**, SHA-256
`954b953ff32af95ca2e7a0bb4941ccfa5e1a288bf4eac6e8fb066caeceb29419`.
The archive and download receipt are excluded from the manifest to avoid
circular hashing; verify them separately as well as the 284 payload artifacts.

Independent replay is
`data/context-pilot-independent-replay-20261024-v1.json`, produced by
`data/verify_context_pilot_20261024_v1.py` under the predeclared
`data/context-pilot-verification-protocol-20261024-v1.json`.
It freshly tokenizes all inputs and reconstructs every window, cache identity,
source/context decision, chart table and ZIP member without importing the new
implementations. Four predeclared independent encoder batch checks repeat
seven windows and reproduce their logits exactly. Those intentional validation
repeats are separate from the producer's 1,208 new windows. Completed-resume
evidence is `data/context-pilot-completed-resume-20261024-v1.log`.
Browser evidence is `data/context-pilot-browser-20261024-v1/receipt.json`:
desktop/mobile, both SVGs, all 255 complete UTF-8 inputs and seven exact
downloads; helpers exit and no external requests or JavaScript errors occur.

The further cross-input annex is separately exploratory. Its rule is frozen
in `data/context-cross-input-rescue-plan-20261024-v1.json` before the selected
metadata predictions are inspected. Keep all seventy primary assignments;
for an unresolved case, require an accepted metadata policy topic supported
by more than half of metadata/4,096-body/8,192-body votes, including a body
vote. Uncertain/rejected votes stay in the denominator; there is no metadata-
only fallback. All signals share the same weights and are not independent
semantic raters.

Actual output is `data/processed/context-cross-input-rescue-20261024-v1/`.
It adds four assignments, two matching assistant proposals and two differing,
with **zero new encoder calls**. The complete twelve-member
`complete_cross_input_exploration.zip` includes all 114 complete selected
metadata inputs and predictions, all 109 contexts/comparisons and the entire
285-member body-pilot ZIP. Full archive: **57,617,097 bytes**, SHA-256
`0b20aac414d5d4999e07f5b7cb90d08d535ea40a3f6bcc284bed5d0b11bd244e`.
The executed producer is
`data/run_context_cross_input_rescue_20261024_v1.py`; independent reconstruction
of all records, CSV fields and outer/nested archive members is recorded in
`data/context-cross-input-independent-replay-20261024-v1.json`, from
`data/verify_context_cross_input_rescue_20261024_v1.py`. Download bindings are
in `data/context-cross-input-exploration-complete-download-20261024-v1.json`.
Existing output directories/receipts must not be overwritten for a replay.

Neither experiment changes the frozen human evaluation plan or supplies human
annotations, retrains weights, certifies accuracy, replaces population results
or publishes anything. The majority candidate remains 78,300 assignments;
the next source/encoder extension still starts from **v19 / token v16**.
The actual tracked full audit is
`data/context-pilot-code-checkpoint-full-audit-20261024-v1.json`: 444/478,
with the same 34 legacy failures and every other preceding report field
unchanged. Generated source/model/graph evidence remains local and Git-ignored;
pushing the code is not a backup of these complete research downloads.

### Strict-majority bill-topic candidate

The new decision policy is a separate, explicitly provisional alternative to
the preserved unanimity baseline. Reproduce it from the complete saved **v19**
windows without rerunning the encoder:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B scripts/reaggregate_cycle_topics.py \
  --directory data/processed/cycle-topic-inference-retained-text-20261024-v19 \
  --gallery outputs/topic-inference-retained-text-2023-2024-v17 \
  --gallery-sha256 6dcb6e1ef7df9b40e4c53bb106f437ba9a0e67220d5b4dbbb824d5a024a52932 \
  --out-dir outputs/topic-majority-2023-2024-REPLAY
```

The output directory must be new. The producer SHA-binds the full original
gallery/job, all four executed producers and the selected assistant comparison.
It freezes `policy_plan.json` **before** population reaggregation. Its actual
policy-run hash is
`bbf6f887cbed4f703416e90723c9e015292dc582784007756c27f774c5cb223a`.
The unchanged frozen runtime reconstructs every window's complete softmax
vector; all 22 outputs, including supervised rejection, remain present.

The policy has two strict-majority stages. First, more than half of **all**
window argmax votes must support one output. A tie or a largest plurality below
that quorum is uncertain. The score/margin gates remain numerically 0.80/0.20,
but are evaluated on the complete mean vector of the **supporting windows**,
not the unconditional whole-document mean. No rejection score is redistributed
to policy topics. Both conditional and unconditional vectors are exported.
The conditional score is not calibrated whole-bill confidence.

Second, more than half of distinct exact `input_sha256` source strings must
yield one accepted window-majority output. Exact repeated strings count once;
inconsistent repeated evidence fails explicitly. Uncertain sources stay in the
denominator rather than being dropped. Learned rejection counts separately
from uncertainty. A minority of differing accepted sources is retained and
flagged, not an automatic veto. This is not certification that different
extractions are independent editions. Model windows retain their original
1024-token/128-overlap construction, not independent semantic-rater status.

The completed gallery is `outputs/topic-majority-2023-2024-v1/index.html`.
It has **78,300 assignments / 23,618 learned rejections / 37,396 unresolved /
three exclusions / 18,281 missing**. All 65,091 original accepted topics remain
unchanged; the 13,209 additions reduce available-but-unassigned contexts from
74,226 to 61,017. Entire original context/prediction fields survive in
`decisions/context_assignments.jsonl` and `decisions/source_decisions.jsonl`
alongside a `majority_candidate` namespace. All source dates/nulls, output
vectors, minority votes and approval gates remain explicit.

Six chart tables cover status, all 21 policy topics, transition reasons,
new-assignment origins, all fifty states and the selected assistant comparison.
Three PNG/SVG pairs show the actual results. The complete **123-member ZIP**
preserves all 108 original full-source inference members and appends both
candidate JSONLs, all tables, the original assistant comparison, four producers,
policy and summary. It is not a metadata-only research download. No old
inference/gallery/cache files are rewritten and no tokenizer/encoder runs.

Actual independent replay is
`data/majority-candidate-independent-replay-20261024-v1.json`, executed from
`data/verify_majority_candidate_20261024_v1.py`. It independently reconstructs
all 785,550 windows, source quorums, 157,598 context decisions, all original
fields, chart tables and 123 complete ZIP members without importing either new
implementation. Actual browser proof is
`data/majority-candidate-browser-20261024-v1/receipt.json`: desktop/mobile,
three decoded SVGs and nine byte-identical downloads, zero external requests
or JavaScript errors, helpers exited.

The selected assistant diagnostics are development evidence, not untouched
evaluation or population accuracy estimates:
of 32 newly assigned selected cases, 25 match existing proposals, six differ and
one has no proposal. The checkpoint's registered 808 train / fifty dev rows
are assistant-reviewed, not independent human validation. Its original
complete-document mean-probability training objective is not the new majority
policy. The immutable human plan must not be rewritten to retroactively certify
this candidate. Independent evaluation and any promotion require a separate
explicitly registered evaluation/promotion step. Original **v19 / token v16**
remains the source/encoder continuation baseline.

### Complete unresolved-source query sets

The additional offline frontier audit is
`data/processed/retained-source-frontier-20261024-v1/`.
Its `complete_unresolved_source_evidence.zip` preserves the complete source
records, not just a list of failed bill numbers. All **180 source dossiers**
retain every original CSV field, full `Bill_Text`, the 190 unchanged candidate
contexts and their complete selected action/version/link rows.
Source AI annotations remain untrusted source fields, never gold, predictions
or training inputs. A shared state/typed number is not a verified session match.
Missing dates and unproven source editions stay unknown.

The ZIP contains the full 2,571-record publication CSV, complete 4,046-record
retained Hawaii corpus, whole current 18,281-row queue, previous source
dispositions/queue, complete original-reference query tables and the exact
executed producer. The 17 members independently verify; no source policy text
is truncated or replaced with a summary. Manifest:
`8565da6d3993b362685da5607ba0ac534a1093cf3793fc6418f90114325d5807`.
The actual download binding is in
`data/retained-source-frontier-complete-download-20261024-v1.json`;
independent replay is
`data/retained-source-frontier-independent-replay-20261024-v1.json`.

The producer and independent observer are retained at
`data/build_retained_source_frontier_20261024_v1.py` and
`data/verify_retained_source_frontier_20261024_v1.py`. Both require fresh
outputs/receipts and rehash their complete original inputs. Further discovery
is retained separately in `data/new-open-corpus-discovery-20261024-v2.json`.
No bodies were admitted, no encoder ran, no previous access stop reopened and
no inference/gallery refresh was necessary: **v19 / token v16 and all existing
graphs remain the actual current baseline**. These are complete bounded audit
deliverables, not proof of an exhaustive absence or completed scientific study.

### Full-score diagnostics without new classifications

The separate additive gallery is
`outputs/topic-score-diagnostics-2023-2024-v1/index.html`.
Rebuild it from completed **v19**, not an older inference job:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B scripts/recreate_score_diagnostics.py \
  --directory data/processed/cycle-topic-inference-retained-text-20261024-v19 \
  --gallery outputs/topic-inference-retained-text-2023-2024-v17 \
  --gallery-sha256 6dcb6e1ef7df9b40e4c53bb106f437ba9a0e67220d5b4dbbb824d5a024a52932 \
  --out-dir outputs/topic-score-diagnostics-2023-2024-REPLAY
```

The output path must be fresh. This command verifies the externally pinned
gallery and every original source member, replays the unchanged frozen
window-softmax/decision function and exports complete vectors without an
encoder. It does not average logits before softmax, remove the supervised
rejection output, force a topic from the largest diagnostic mean or treat
missing/excluded inputs as zero scores. The original candidate fields, dates,
unknowns, decisions and approval flags survive unchanged outside an explicitly
diagnostic namespace.

`diagnostics/context_scores.jsonl` contains all **157,598 original contexts**.
`diagnostics/view_scores.jsonl` contains all **178,745 original predictions**,
including complete saved logits and the added parsed 22-output vectors.
Exactly 178,742 views / **139,314 contexts** have scores. Three source-test
contexts retain empty original scores and null diagnostic vectors, separately
from 18,281 contexts without text. Equal exact `input_sha256` strings count
once within a context's diagnostic mean; all original views remain exported.
National/state charts give each scored context equal weight and preserve all
21 topic outputs plus supervised rejection. No-candidate/unscored state means
stay null. Source envelopes describe supplied-view variation, not confidence.
These scores are uncalibrated diagnostics, not policy proportions or new labels.

The fourteen-artifact gallery includes two PNG/SVG pairs, three complete chart
tables, both frozen plotting producers and a complete **116-member ZIP**.
That ZIP preserves all 108 original inference members, including complete
policy texts, source records, predictions and frozen provenance; it appends the
two diagnostic JSONLs, three chart tables, two producers and summary. It is not
a metadata-only replacement. Both producer copies are frozen before processing,
and original inputs, source ZIP, gallery pin and producers are rechecked after
execution. Existing galleries are not rewritten.

Actual independent replay is
`data/full-score-diagnostics-independent-replay-20261024-v1.json`.
It independently reconstructs every scored view from all 785,550 saved windows,
every context vector and all chart aggregates; it checks every original field
and every complete ZIP member without importing the diagnostic producer.
Actual browser evidence is
`data/full-score-diagnostics-browser-20261024-v1/receipt.json`.
Both layouts, both SVGs and five exact downloads pass; no external requests or
JavaScript errors occur, and helpers exit. The original model, token-cache v16,
human evidence, missing-body queue and publication gates remain unchanged.

### Current-snapshot replay versus the historical analysis audit

The saved 2023–2024 retained-text snapshot has a tracked offline replay command:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B scripts/audit_cycle_topics.py \
  --job data/processed/cycle-topic-inference-retained-text-20261024-v19 \
  --gallery outputs/topic-inference-retained-text-2023-2024-v17 \
  --verified-token-cache data/cycle-topic-independent-token-verification-cache-20261024-v16.sqlite \
  --verified-token-cache-sha256 68432beb05e121d8681915798c7a208e055461b9d3f785f47bb414bdf3a3e34f \
  --out data/current-cycle-audit-NEW-UNUSED.json
```

The report path must be fresh and outside the immutable inputs. The optional
cache/path hash pair identifies a previously independently verified tokenizer
cache; it is opened **read-only**, checked against the frozen tokenizer/runtime
identity and rehashed afterward. Missing cached verification is an error, not a
silent fallback. Omit both cache options to independently tokenize every unique
supplied policy string without an encoder; that mode may take substantially longer.
Neither mode edits the job, prediction cache, source evidence, graphs or labels.

The command checks every saved source/logit/token/window decision and reconstructs
all-view consensus against every original context, including unknown fields.
All fifty state partitions, gallery artifacts and **all 108 required complete ZIP
members** are checked. Required source inputs, predictions or frozen producers
cannot be omitted by changing the download manifest to match a smaller ZIP.
The current actual replay is
`data/published-va-tracked-current-cycle-audit-20261024-v1.json`: **178,745 views /
157,598 contexts**, identical saved decisions, counts and byte bindings to the
independent private replay, with zero encoder passes and no token-cache writes.
The preceding v18/v17/v16/v15 replays and token v15/v14/v13/v12 remain unchanged.

This is a structural/provenance replay, **not independent accuracy validation or
study completion**. The original full `audit_reproducibility.py --require-tracked`
remains separate and unchanged: its 34 failures are missing legacy
2018–present platform/party-analysis artifacts and required derivatives. New
2023–2024 model assignments are not written into those old paths to manufacture
an apparent pass. Human accuracy, operative platforms, event-time party, source
rights and publication remain open requirements.

The current full audit reports **441/475**, compared with **438/472** at the
full-score checkpoint: the majority module, producer and documented test file
add three passing Python-file documentation checks. The exact same 34 legacy
failures and all other report fields remain identical in
`data/majority-candidate-code-checkpoint-full-audit-20261024-v1.json`.
The preceding full-score/source audit reports remain unchanged.

```bash
.venv/bin/python -I -B scripts/recreate_graphs.py \
  --research-corpus data/processed/research-corpus-text-20261022-v4 \
  --archive-text data/processed/independent-archive-text-20261022-v2 \
  --archive-text data/processed/lawatlas-text-evidence-20261022-v1 \
  --archive-text data/processed/maryland-archive-text-20261022-v1 \
  --archive-text data/processed/nj-library-text-20261023-v5 \
  --archive-text data/processed/nj-library-collection-text-full-20261023-v1 \
  --archive-text data/processed/ok-retained-context-text-20261023-v2 \
  --archive-text data/processed/billcam-hi-retained-html-full-20261023-v1 \
  --archive-text data/processed/billcam-hi-retained-html-delta-20261023-v1 \
  --archive-text data/processed/billcam-four-subject-html-20261023-v1 \
  --archive-text data/processed/billcam-wrapped-heading-html-20261023-v1 \
  --archive-text data/processed/govbot-exact-original-documents-20261023-v2 \
  --archive-text data/processed/published-ai-corpus-documents-20261023-v2 \
  --archive-text data/processed/billcam-action-bound-html-delta-20261023-v1 \
  --archive-text data/processed/billcam-action-bound-html-four-subject-20261023-v1 \
  --archive-text data/processed/billcam-prestop-public-documents-html-20261023-v1 \
  --archive-text data/processed/published-carryover-documents-20261023-v1 \
  --archive-text data/processed/billcam-provider-context-html-delta-20261023-v1 \
  --archive-text data/processed/billcam-provider-context-html-four-subject-20261023-v1 \
  --archive-text data/processed/nj-library-tail-context-text-20261024-v1 \
  --archive-text data/processed/nj-library-effective-context-text-20261024-v1 \
  --archive-text data/processed/nj-library-single-page-context-text-20261024-v1 \
  --archive-text data/processed/nj-library-printed-variant-context-text-20261024-v1 \
  --archive-text data/processed/billcommons-de-original-context-text-20261024-v1 \
  --archive-text data/processed/billcommons-nv83-original-context-text-20261024-v1 \
  --archive-text data/processed/published-va-carryover-documents-20261024-v1 \
  --out-dir outputs/recreated-2023-2024-REPLAY
```

The accepted local build is `outputs/recreated-2023-2024-v30/index.html`.
The command above requires a fresh output directory. The bundle contains 14
current evidence graphs in PNG and SVG, 13 complete chart-data CSVs, thirty-two complete
research-packet ZIPs and a hash manifest. It also archives the exact seventeen
plotting/source-consumer producers and the recovered producers within their research packets.
The current bundle has **thirty-two** complete research ZIPs, 105 bound artifacts
and manifest `74cfe8aad94e8c3da7d217f6486f7714ab4961666242204b2d4865d3c4aa45e7`.
All thirty-one preceding source ZIPs remain byte-identical under independent replay.
It uses saved evidence
tables and existing development diagnostics without
collecting sources or executing a classifier. Missing native channels remain
unknown, repeated metadata observations are not inflated into new identities,
and assistant-reviewed diagnostics are not independent human validation.

The historical corpus-recency graph is faithfully rebuilt from the retained
historical records, not treated as operative 2023–2024 platform coverage. New collection-observation and recorded-stage graphs use the
actual recovered inputs; the Arkansas chart separates 149 complete PDF contexts
from 1,842 metadata-only contexts. ZIPs contain full text/records, native pages
and PDFs where applicable, not metadata-only substitutes. Caucus source text and
its permanently closed capture are separate from party platforms.
The original 13 PNGs are copied unchanged into `legacy-reference/`, clearly
separate from freshly rendered graphs: most old analytical source tables are
missing, so those images are **not** claimed to have been regenerated or
validated. No party-topic, trend or D/R outcome results are invented to fill them.
Existing output directories are refused; use a new `outputs/recreated-*`
directory for another run. Generated bundles are local and Git-ignored.

## Original-action-bound Virginia text and current v19 outputs

Five original Virginia contexts now retain **five complete published views /
58,325 characters**. Three are own offered editions; two are complete committee
substitutes with their own printed proposal dates and operative enactment clauses.
All are explicitly dated 2024. Their unchanged original 2025-labelled contexts
have exact origin-filing IDs/chambers/organizations and final literal
`Continued to 2025 ...` actions. A recommendation to continue, provider year,
effective date or inferred session alias cannot supply that bridge.
The separately opted-in source profile never changes earlier replay behavior.
Complete original actions and every published CSV field/negative remain
available in `research-data/independent_archive_25.zip`; original dates,
session labels and unknowns are not repaired or certified.

```bash
.venv/bin/python -I -B -m state_politics.bills.published_corpus_text verify \
  --directory data/processed/published-va-carryover-documents-20261024-v1 \
  --source-manifest-sha256 381017f4333a36f0b415368b5ef0e45e860b346c143208feaec7bb35dc3539e8 \
  --gap-queue-sha256 c40b913b750dae4f68e24463cefff23869bb4e47d53182aa29fdb4e6c1331b3e
```

Actual source availability is **139,317 / 157,598**, leaving **18,281** gaps,
including 771 VA / 422 DE / 73 NV / 1,600 NJ / 5,717 HI. Twenty-five archives
contain **10,862 contexts / 13,374 views**. Explorer v35 has 799 artifacts,
manifest `6c4fdb0e21d712c3fa95bbb411b12650c1adb50aaabf67ab37434f8121610799`.
The source replay rehashes 1,805 artifacts and preserves all 13,369 prior
archive rows, 305 other source partitions, twelve other chart tables and
31 preceding complete source ZIPs.

Completed full-document **v19** yields **65,091 assignments / 74,226 abstentions /
18,281 unavailable contexts**, with **178,745 full source alternatives**.
The five new contexts yield two assignments / three abstentions; all 157,593
other whole assignment rows and all 178,740 earlier predictions are unchanged.
Exactly **five new strings / 12,028 tokens / fifteen windows** reach the frozen
encoder, with zero discarded tokens or repeated old inputs. Both private and
tracked read-only token/logit/window/consensus replays pass. All seven paired
tables independently reconstruct for all fifty states and 139,317 observed-body
contexts. Metadata inference, weights, taxonomy, thresholds and human labels
remain unchanged.

Topic gallery v17 has 13 artifacts, manifest
`6dcb6e1ef7df9b40e4c53bb106f437ba9a0e67220d5b4dbbb824d5a024a52932`;
paired gallery v15 has 22 artifacts, manifest
`0a443592b2a89c8a7fcd4c8eba5debf69d4a8a63cbe387432bf4a068e8fa7c23`.
The complete population inference ZIP contains 108 members / 1,732,997,111 bytes,
SHA `95801911bb059f446ed59737212b48a3e595f8565146867cc7bceac356ee821b`.
Current source/model/comparison receipts have the `data/published-va-` prefix:
`source-union-replay-20261024-v1.json`,
`assignment-reconciliation-20261024-v1.json`,
`comparison-replay-20261024-v1.json` and
`tracked-current-cycle-audit-20261024-v1.json`.

Future extensions must start **completed v19 / token v16**, not an earlier
historical job. Its prediction cache has 168,403 rows / 752,422,912 bytes, SHA
`5ce833127e14ce81cf8654acec5068df97b53b55073fed9d71735e5185044305`.
The independent token cache is
`data/cycle-topic-independent-token-verification-cache-20261024-v16.sqlite`,
168,403 strings / 40,194,048 bytes, SHA
`68432beb05e121d8681915798c7a208e055461b9d3f785f47bb414bdf3a3e34f`.
Earlier caches remain byte-identical.

Real Chromium renders 541 complete workspace bodies, all five new original
Virginia continued-action/edition proofs, all 112 earlier Bill Commons metadata
proofs and 61 earlier NJ introduction proofs. Fifteen additional complete state
queries, all fourteen source SVGs and 22 exact workspace downloads pass.
The casebook separately renders all 255 complete UTF-8 texts and three exact
downloads. Both suites pass desktop/mobile with zero JavaScript errors or
external requests; every helper exits and only the two inspected owned
profiles are removed.

## Preceding independently published Delaware and Nevada text

Two new offline packets recover **46 original contexts / 112 complete views /
6,353,892 characters**. Delaware contributes six contexts / twelve views;
Nevada contributes forty original 2024 prefilings / 100 complete views.
Neither source adds original cohort members or repairs session/date metadata.
Delaware's own printed 153rd Assembly and full caption support the unchanged
original contexts despite conflicting provider session dates. Nevada's exact
original bill/version/link foreign keys and own formal body support its
83rd-session context; no year is inferred from a URL. Introduced-text printed
prefiling dates match the original records without certifying filing-time truth.

All 143 received Nevada texts, 350 offered document dispositions and both
complete original national version-reference tables survive. Forty-three
amendment documents are negative evidence, not whole-bill inputs; 207 other
attachments remain unrequested. The separate Delaware fiscal note is also
excluded. Stored extraction flags are not publisher-original or independent
reader certification. Complete source packets are available in the current
gallery's `research-data/independent_archive_23.zip` and
`research-data/independent_archive_24.zip`, never metadata-only replacements.

```bash
.venv/bin/python -I -B -m state_politics.bills.billcommons_text verify \
  --directory data/processed/billcommons-de-original-context-text-20261024-v1 \
  --source-manifest-sha256 1ee32f28ee064b20da9d867423e20868cbb70b990f7080dffc2fa1da1726f0ab \
  --gap-queue-sha256 04e318948601afb208c6c93a404f3079ce45e750ed27b68cfe15b652ad761aa5
.venv/bin/python -I -B -m state_politics.bills.billcommons_nv_text verify \
  --directory data/processed/billcommons-nv83-original-context-text-20261024-v1 \
  --source-manifest-sha256 dbe364c0d0a08e5c0c3041bec40356f4db7e07614be9d55c15959482d924c125 \
  --gap-queue-sha256 04e318948601afb208c6c93a404f3079ce45e750ed27b68cfe15b652ad761aa5
```

At this completed checkpoint, source availability was **139,312 / 157,598**,
with **18,286** remaining gaps,
including 422 DE / 73 NV / 1,600 NJ / 5,717 HI. Twenty-four archives contain
10,857 contexts / 13,369 views. Explorer v34 has **797 artifacts**, manifest
`3aee2c7b853af84152455ac87c0360812f836b50951e57569c77433255848588`.
The source-union replay rehashes 1,792 output artifacts, preserves all 13,257
old archive rows, 305 other source partitions, twelve other chart tables
and twenty-nine preceding complete source ZIPs unchanged.

Actual full-document **v18** yields **65,089 assignments / 74,223 abstentions /
18,286 unavailable contexts** across **178,740 source alternatives**.
The newest 46 contexts yield nine assignments / 37 abstentions. All 157,552
other whole assignment rows and 178,628 preceding view predictions remain
unchanged. Exactly **112 new strings / 1,538,904 tokens / 2,353 windows** reach
the original frozen encoder, with zero discarded tokens or old repeats.
No weights, taxonomy, thresholds, human labels or metadata inference change.
Both private and tracked read-only token/logit/window/consensus replays pass;
all seven paired tables independently reconstruct for all fifty states and
139,312 observed-body contexts.

Topic gallery v16 has 13 artifacts, manifest
`7ad0ad4f988a7bd34eb1630e45a0a89d69080f5c9cdb3529a7d370e9ac280f56`;
paired gallery v14 has 22 artifacts, manifest
`528e6aa30773cb4e93501c847bf03e44e3f86d9545b44bb2c03cce75aff48a6b`.
The full 108-member inference ZIP has 1,732,941,081 bytes, SHA
`121f95b9857eb4ce9014481dbf3cdbf0c1fca80113a531da1b1910f63387e300`.
Source/model/comparison receipts use the `data/billcommons-combined-` prefix:
`source-union-replay-20261024-v1.json`,
`assignment-reconciliation-20261024-v1.json`,
`comparison-replay-20261024-v1.json` and
`tracked-current-cycle-audit-20261024-v1.json`.

The preceding completed v18 / token v15 stays preserved; future extensions
use **completed v19 / token v16** above. Its historical prediction cache has **168,398 rows /
752,402,432 bytes**, SHA
`ea3be36006116de7e9e90e3ab9e9f9a94a7c673daf39ab840501892a567cc951`.
The independent token cache is
`data/cycle-topic-independent-token-verification-cache-20261024-v15.sqlite`,
**168,398 strings / 40,194,048 bytes**, SHA
`cda9ba11c805ba74bb758d03855f5657fb7d3ac846ba4272047fc1479c98d144`.
All preceding v17/v14 cache bytes stay unchanged.

Real Chromium renders all 536 selected full bodies and every one of the
112 new source/context/provider-date proofs, plus all 61 preceding NJ
introduction proofs. Fifteen additional complete state queries and the full
8,272-view NJ / 1,742-view HI queries stay downloadable. All fourteen source
SVGs decode. The separate casebook renders all 150 complete UTF-8 texts.
Both suites pass desktop/mobile checks and 24 byte-identical downloads with
zero JavaScript errors or external requests; every helper exits.
Only the two inspected owned browser profiles are removed.

## Assistant-advisory semantic review

`outputs/assistant-advisory-topic-review-2023-2024-v7/index.html` is a separate
private casebook, not a replacement population inference or graph bundle.
Twenty-one model-blind GPT-6.1 Sol assignments examine all 109 selected recovered
Delaware/Hawaii/NJ/Nevada/Virginia contexts and all 255 complete policy views.
Every input hash and all 604 exact
evidence spans are checked before revealing the frozen model comparison.
Frozen human evaluation IDs, identities and body hashes are excluded; no
overlap is found. Original evaluation inputs, predictions and labels remain
unchanged.

The primary download,
`research-data/complete_review_inputs_results_and_comparison.zip`, contains
344 hash-bound members: all complete reviewed texts, original blind inputs,
review results, the complete comparison, selected original model predictions
and assignments, and `executed_verifier.py`. `comparison.csv` is explicitly a
comparison table, **not a substitute for source-text downloads**.
The outer manifest binds every artifact and every ZIP member. The selected
model rows retain their original fields and unknowns.

The comparison records 33 matching assigned-topic proposals, 68 model abstentions
with advisory proposals, three contexts unresolved in both, four different
assigned topics and one model assignment without advisory consensus.
Fourteen individual view disagreements and one model-assigned/advisory-unresolved
view remain explicit.
These are descriptive results for a nonrepresentative cohort. They cannot
estimate population accuracy or become human gold, training labels,
analytical assignments, model promotion or publication permission.
Adjudication flags are a review queue, not automatic corrections.
All view disagreements enter that queue even if both context results abstain.
V4 added the missing A 5610 flag; V5 preserved that rule for the preceding 22
contexts; V6 added six complete Delaware comparisons. V7 adds all forty recovered
Nevada contexts and five original-action-bound Virginia contexts. The independent
Nevada read-range verifier checks all 100 full views and 557 contiguous bounded
intervals; it is read accounting, not a human accuracy estimate. All earlier
casebooks stay immutable.
There are 74 selected triage contexts, not 74 established model errors.
Construction-permit bills A 5036/S 3551 have model topic 15 and differing
advisory proposals 14/20. Such taxonomy-boundary disagreement cannot establish
which label is correct or substitute for independent human adjudication.
The unchanged population graphs must not be regenerated from these advisory
proposals as if they were validated labels.
The preceding 20-context casebooks v1/v2 and their complete 48-member downloads
remain byte-identical historical evidence.

## Complete retained searchable-bill text

The omitted search-index table is now recovered in
`data/processed/retained-dump-gap-recovery-20261022-v1/`. Its
`sealed_manifest.json` is
`b56c1264c545c168e946eef1b7e10016d807409d8f7b153b4df3c2947ae96cce`.
It preserves all 157,598 selected source rows, 123,182 nonempty bodies,
full search_vector/all_titles/error fields and all 135,046 selected link/version
pairs. Complete original JSONL and supplementary extras/citations remain in the
separately sealed inspection packet and the gallery's complete snapshot ZIP.
The field-bearing source is **provider-selected snapshot text, not necessarily
an introduced or original version**; all admission flags remain false.

Future extraction uses the tracked opt-in command below, not a rewrite of the
historical eleven-table extraction. The actual source extraction is already
complete; use a genuinely **new output directory** for any replay.

```bash
PG_RESTORE="$PWD/data/tools/Postgres.app/Contents/Versions/18/bin/pg_restore" \
  .venv/bin/python -I -B -m state_politics.bills.retained_dump_text \
  --dump data/raw/openstates/2026-10-public.pgdump \
  --candidate-cohort data/processed/cycle-outcome-evidence-20261022-v2/source_bills.parquet \
  --out-dir data/processed/retained-search-index-NEW-UNUSED
```

The command streams only the named source table and retains every matching
original record/ordinal, including duplicates, missing strings and provider
errors. It performs no network call, date/party inference, tokenization or model
execution. The original normalization/source-version binding producers are
archived in the complete recovery packet. Index creation timestamps and version
notes/dates are never substituted for filing dates.

The current explorer explicitly includes this source with
`--snapshot-text data/processed/retained-dump-gap-recovery-20261022-v1`.
Its fifty state JSONL/gzip partitions preserve every full original field, raw_text
and selected version/link row. Whitespace-only strings remain unchanged and
separately counted, rather than being stripped or advertised as substantive
bodies. The metadata token plan still covers metadata only, not these new texts.

The earlier v6 `chart-data/retained_text_coverage.csv` de-duplicates native/snapshot availability:
126,376 candidate contexts have some retained text; 31,222 do not in the supplied
inputs. `chart-data/missing_retained_text.parquet` contains the complete remaining
queue and explicitly authorizes no collection. Counts overlap between sources;
do not add them or interpret unknown native channels as publisher absence.

## Exact additional research-corpus text

The next source packet, `data/processed/research-corpus-text-20261022-v4/`,
recovers 2,079 previously missing contexts / 2,315 complete views from pinned
NH/IL/TX source files. Reproduce it offline into a **new** output directory:

```bash
.venv/bin/python -I -B -m state_politics.bills.research_corpus_text \
  --source-dir data/processed/remaining-gap-public-source-discovery-20261022-v1 \
  --gap-queue outputs/recreated-2023-2024-v6/chart-data/missing_retained_text.parquet \
  --states NH IL TX --source-ancestry \
  --out-dir data/processed/research-corpus-text-REPLAY
```

The source directory retains dataset metadata, file-tree/LFS hashes and complete
downloaded JSON under revision `d4f15948c8af7733df9aa70ce68b14a65dec3d82`;
see [source attribution and license observations](../CITATIONS.md#11-independent-research-corpus-text).
No request is made by this producer. It verifies complete input hashes, requires
literal state/session/bill evidence plus substantive body text, preserves exact
source spans and all alternatives, and records every unmatched/rejected row.
Written assembly declarations and explicit constitutional-amendment aliases
are handled without deleting line numbers or inferring dates. Existing
later-session prefilings remain within the unchanged candidate cohort.

The packet contains complete original JSON arrays, full matched JSONL, exact
original gap-context rows, every source-row disposition and archived producer.
Its current manifest SHA-256 is
`e57833697a71ca2a6a0edbb9e54068425db681cd8fedf1a5ed3c93540db2eb02`.
The explicit ancestry option additionally includes all 12,340 original keyed
NH/IL records from revision `9411b4690c3ba8c0c28ab19eb9370316908c00af`.
Whole-field matches restore removed dataset keys/source filenames: all 2,546
references for 2,306 views are retained without arbitrarily selecting an
alternative or interpreting keys as external bill IDs. The nine TX views
have no supplied keyed ancestors; their complete current records are preserved.
Texas own session/number declarations and certifications must match existing
canonical session names; special-session namespace suffixes are not guessed.
The consumer replays source ordinals, original records, body hashes and printed
identities against the unchanged candidate cohort. All model/training/party/
filing-time/scientific/publisher-original/publication approvals remain false;
source summaries are not gold or predictions. Earlier 2,060-context v1 stays
sealed and still verifies under the stronger parser.

The explicit `--research-corpus` preview/graph option adds a distinct source,
complete state JSONL/gzip exports and a complete research ZIP. The v9 coverage
CSV de-duplicates all three channels: 128,455 candidate contexts have some
retained text and 29,143 remain without an observed body in these inputs.
The remaining full-context Parquet preserves unknown native counts and
authorizes no automatic collection. No source is silently promoted to a
publisher-native or introduced version.

## Independent archived bill text

### Current residual New Jersey recovery: October 24, 2026

The independently replayed single-page and printed-variant packets add
**22 original contexts / 61 complete views / 1,144,522 policy characters**.
Packets are `data/processed/nj-library-single-page-context-text-20261024-v1/`
(3 contexts / 8 views; manifest
`5298ca4dc50ee84b343573402db8e92443700f911838ecf6dfb7645c17aef256`)
and `data/processed/nj-library-printed-variant-context-text-20261024-v1/`
(19 contexts / 53 views; manifest
`4cd0c22ae7581609aefe621175ece7d1a1623f45fd28976dfc82fdad1550b62d`).
Both preserve all supplied source pages and complete original context/action
references; the second exact original-row queue excludes the three first
recoveries. Distinct context-evidence schemas preserve old profile behaviour.
No source date, session, header, folio or policy text is repaired or invented.
Unproven prefiling/session versions stay quarantined. Exact PDF/reader/prefix/
content-stream witnesses expose retained codification and whitespace metadata.

The combined receipt `data/nj-residual-context-packet-replay-20261024-v1.json`
has SHA `94d0753c45a92a31306e56926f2e63aa74078421b7d283f97443dd0cb1cadf6c`.
Actual availability is **139,266 / 157,598**, with **18,332** remaining gaps,
including **1,600 NJ / 5,717 HI**. Twenty-two archives contain **10,811 contexts /
13,257 views**. Actual explorer v33 has 791 artifacts, manifest
`2c13118effff5ffa2c621dd3f11f7d8b2b9de65ec576c0f32fd86a242b75bd05`;
the recreated source gallery v28 is described above.

Actual full-text v17 inference and downstream galleries are complete against
the unchanged frozen v16 model/cache and token v13. The job has **178,628
supplied source views / 157,598 original contexts**, yielding **65,080 classified /
74,186 abstained / 18,332 unavailable**. The new 22 contexts yield fifteen
assignments and seven abstentions. Every other 157,576 whole assignment row and
all 178,567 old per-view predictions remain unchanged. The genuine original
encoder processes **61 new strings / 302,904 tokens / 397 windows**, with no
discarded tokens or old encoder repeats. Metadata inference is not rerun.

Topic gallery v15 has 13 artifacts, manifest
`e4d63894e082a8475bf06200a9e392e1361eb76eb96e01208d3afe9661d90795`;
paired gallery v13 has 22 artifacts, manifest
`52338cdf9ba86ab2d38a627a2185916ce0e3e7cbb4a19fc0444f5da3ea472471`.
The full 108-member inference ZIP has SHA
`cbb40766c7073f0d7af1bb27c08e54c8b1a2823c37197d020fdd76996993d19f`.
Source, assignment, paired-table and complete-replay receipts are
`data/nj-residual-source-union-replay-20261024-v1.json`,
`data/nj-residual-assignment-reconciliation-20261024-v1.json`,
`data/nj-residual-comparison-replay-20261024-v1.json` and
`data/nj-single-page-tracked-current-cycle-audit-20261024-v1.json`.
Both private and tracked source/logit/token/window/consensus replays pass.

The preceding v17 / token v14 checkpoint stays preserved; future extensions
use completed v19 / token v16 above. Its historical v17 prediction
cache has **168,286 rows / 751,034,368 bytes**, SHA-256
`54ab9a5cfb991374993d1faa968196a379d7653a78887180438301032b11d51e`.
The independent token cache is
`data/cycle-topic-independent-token-verification-cache-20261024-v14.sqlite`,
**168,286 strings / 40,128,512 bytes**, SHA-256
`d7b3d106fe0f71d5edfb18eb90d2c54c7638f0b3958c7c6df1c8003d3662610b`.
Original v16/v13 caches remain byte-identical and read-only.
All 61 new complete policy views have separate model-blind advisory reviews
with 138 verified literal evidence spans; they are not human labels or training
data. No source request, metadata replacement or approval promotion occurs.
Real Chromium verifies 424 full workspace bodies, all 61 new action/context
proofs and byte-identical complete downloads; the full NJ query contains 8,272
views. Eight prologue witnesses, six whitespace witnesses and two printed
reprint covers remain visible and match original source metadata exactly.
All fourteen source SVGs decode. The separate 58-context casebook renders all
138 complete UTF-8 texts and its complete 184-member review ZIP. Both suites
pass desktop/mobile layout checks and 22 exact downloads with no external
requests or JavaScript errors; all owned helpers exit.

### Preceding original-context New Jersey recovery and inference: October 24, 2026

Two offline packets add **16 original contexts / 42 complete reader views /
2,000,505 policy characters**. The tail profile recovers six January 2024
introductions whose own covers print the 220th Legislature. The separate
all-original-date profile recovers ten further contexts using fourth-reprint
recognition, exact source-spacing evidence and bounded version quarantine.
Every accepted view has complete original bill-specific introduction evidence.
Literal ISO calendar components are compared without timezone conversion;
original timestamps and the contradictory `2023-12-31` session end are preserved.

The packets are `data/processed/nj-library-tail-context-text-20261024-v1/`
(6 contexts / 16 views; manifest
`3922c090c6d937385c57818b9a3f065ebee1f6168a3cedc9b842b8095e5bdeae`)
and `data/processed/nj-library-effective-context-text-20261024-v1/`
(10 contexts / 26 views; manifest
`81771d07dc9f41a79547193e26e220bfa71015e57d912eb587ad749373d426ab`).
Both retain the complete supplied PDF collection, both reader outputs and
complete original context/action reference files. Their queues are exact,
disjoint whole-row/schema subsets of the original missing-context queue.
Four accepted views expose quarantined same-bill alternatives. Two views bind
one exact unlabelled PDF page using the pinned PDF, all three reader-page hashes
and both printed same-bill/reprint/folio neighbours. No header, folio or source
character is inserted.

Combined receipt `data/nj-context-packet-replay-20261024-v1.json` has SHA
`ea104ae0dc0d5743778d48d2021dcc707d6162639b249ce977b9e5bcb2e20653`.
Availability is **139,244 / 157,598**, with **18,354** remaining, including
**1,622 NJ / 5,717 HI**. Twenty archives contain **10,789 contexts / 13,196 views**.
Actual explorer v32 has 787 artifacts, manifest
`8bff39638fa30416e33e3f394995932c96801965c456a208869597772befd78a`.
Source gallery v27 remains the preserved preceding source snapshot; current v28
is described above.

Actual completed job
`data/processed/cycle-topic-inference-retained-text-20261024-v16/` contains
**178,567 views / 157,598 original contexts** and yields **65,065 classified /
74,179 abstained / 18,354 unavailable**. The sixteen new contexts yield two
assignments and fourteen abstentions. All 157,582 other complete assignment
rows and all 178,525 preceding view predictions remain unchanged.
The actual original encoder processes **42 genuinely new strings / 536,323
tokens / 684 windows**, with no discarded tokens or repeated old inputs.
Model run, weights, taxonomy and thresholds remain frozen.

The topic gallery v14 has 13 artifacts, manifest
`2292a9e4a77a17b1a9b374c11ca71285a33a4f3f43998a4f3d821f62bbb719b7`;
paired gallery v12 has 22 artifacts, manifest
`b2ae4582f3ecdcfe93750364626229a81b7664fef0305ba829c1170aa4b94590`.
All seven paired tables are independently reconstructed for all fifty states
and 139,244 observed-body contexts. The complete 108-member inference ZIP
contains every full input, prediction and frozen producer.
Private and tracked source/logit/token/window/consensus replays both pass;
the tracked report is
`data/nj-context-tracked-current-cycle-audit-20261024-v1.json`.
Independent source and assignment receipts are
`data/nj-context-source-union-replay-20261024-v1.json` and
`data/nj-context-assignment-reconciliation-20261024-v1.json`.

The preceding v16 / token v13 checkpoint stays preserved; future extensions
use completed v19 / token v16 above. The historical v16 prediction
cache has **168,225 rows / 750,690,304 bytes**, SHA-256
`b7e52e96d73ccf9357a2f9db0d5ebad7694b1ac7168e3bca63138034b0eb774b`.
The independent token cache is
`data/cycle-topic-independent-token-verification-cache-20261024-v13.sqlite`,
**168,225 strings / 40,108,032 bytes**, SHA-256
`344d61bce7857299abef0ecdb28340f8e6391bbbd626a33384c3f2c3436f56d0`.
Both v15/v12 source caches remain unchanged.

Real Chromium verifies 14 source SVGs, complete state query/download bytes,
all 42 new full bodies with unchanged action/context/version metadata, four
visible quarantine warnings and two exact page bridges. It also renders all
77 complete advisory sources and checks all galleries at desktop/mobile sizes.
All 22 downloads are byte-identical; all browser/server helpers exit.
No source request, date repair, human-label change or scientific/rights/
party-time/publication promotion occurs.

### Preceding provider-context recovery and completed inference: October 24, 2026

Two disjoint opt-in packets recover **20 original 2024 Hawaii contexts /
35 complete views / 396,533 policy characters** from already retained
provider-declared `2023 Regular Session` records. The old annual reader
filtered that provider year before considering actual original carryover
actions. The new profile explicitly selects this relation and requires
the exact original bill's carryover event and origin-introduction action
IDs/chamber, matching own typed number/caption and a single printed 2023
venue. A matching 2024 heading cannot bypass the action proof. Provider
sessions, original context years, dates and metadata remain unchanged;
no annual/native URL alias is inferred and no request is made.

Packets are `data/processed/billcam-provider-context-html-delta-20261023-v1/`
(17 contexts / 26 views; manifest
`8711b3ed9b15286118b8057d254c7e62fc83f2f4594d1d6f8315c0237ddc5ff4`)
and `data/processed/billcam-provider-context-html-four-subject-20261023-v1/`
(3 contexts / 9 views; manifest
`dffe4352c2bb177433a35ae85eb1e55a78af3f497343a014c2f040cd77a26b3f`).
Both preserve complete original captures, all request accounting, the
complete original action table/extraction manifest and every old negative.
All seven preceding HTML packets and both accepted published packets
still replay through exact historical producer/dependency bindings.

Availability is **139,228 / 157,598**, with **18,370** remaining, including
**5,717 HI**. Eighteen archives contain **10,773 contexts / 13,154 views**.
All 13,119 preceding archive rows, 305 other source partitions, twelve
other chart tables and 23 preceding complete source ZIPs remain unchanged.
Explorer **v31** has 783 artifacts, manifest
`4c335b69b0a99ba9c05b0f9eb158f4dedc33daceb23ddb607cb55996a714623a`;
source gallery **v26** has 96 artifacts and 25 complete research ZIPs.

Actual completed job
`data/processed/cycle-topic-inference-retained-text-20261023-v15/`,
frozen from v31, contains **178,525 views / 157,598 original contexts**.
It yields **65,063 classified / 74,165 abstained / 18,370 unavailable**.
New contexts yield **ten assignments / ten abstentions**; all **157,578
other whole assignment rows / 178,490 preceding view predictions** are
unchanged. Read-only extension of completed v14 reuses all 35 supplied
texts: **zero new encoder strings, tokens, windows or old-input repeats**.
The actual run and full independent replay still execute. Logical all-view
totals are **597,362,161 tokens / 782,101 windows**, with 615 excluded-source
tokens separate. All saved logits, windows, tokens, decisions, consensus,
original context fields and complete 108-member inference ZIP are checked.
Weights, thresholds, labels, scientific code, human-plan bindings and
metadata inference stay unchanged; explicit summarization precedes graphing.

Current body gallery:
`outputs/topic-inference-retained-text-2023-2024-v13/`, 13 artifacts,
manifest `4f1dc2f8066e5b26212438599d3e46eae819278b6b0f7cd6bc7a6d5d0347ad59`.
Current comparison:
`outputs/topic-input-comparison-2023-2024-v11/`, 22 artifacts,
manifest `9b828bd5bb94217ee214b8429a004493dce1abe1600ea2090527fab1a5551303`.
All 139,228 paired contexts and all seven tables are independently rebuilt:
42,031 same assigned topics / 6,110 different / 43,237 both abstaining /
47,850 exactly one abstaining. The 18,370 missing bodies stay separate;
these are descriptive input differences, not accuracy measurements.
Every source and model research download remains a complete packet.

The preceding v15 / token v12 checkpoint remains preserved; future extensions
use the completed v19 / token v16 checkpoint above. Its historical v15 prediction
cache has **168,183 rows / 750,272,512 bytes**, SHA-256
`788fbfef3118167ddc67be24265e5242922ab8c89bb979e328ddfa4450b646c8`.
The independently verified cache is
`data/cycle-topic-independent-token-verification-cache-20261023-v12.sqlite`,
**168,183 strings / 40,087,552 bytes**, SHA-256
`000252b2fd9b2679e3dc9f25f6da682978c7cb63f762a4684d365fe2397a9f13`.
Both preceding v14/v11 caches remain unchanged; no cached result is replaced.

Receipts: `data/provider-context-packet-replay-20261023-v1.json`,
`data/provider-context-source-union-replay-20261023-v1.json`,
`data/provider-context-cache-extension-20261023-v1.json`,
`data/provider-context-assignment-reconciliation-20261023-v1.json`,
`data/provider-context-complete-inference-replay-20261023-v1.json` and
`data/provider-context-comparison-replay-20261023-v1.json`.
Real Chromium proof
`data/provider-context-browser-workspace-20261023-v1/receipt.json`
checks **321 complete bodies / 266 full carryover proofs**, all 35 new
unchanged provider-session/source-record/target-context observations,
fifteen full-state queries (1,742 HI / 8,169 NJ), nineteen byte-identical
downloads, fourteen SVGs and desktop/mobile layouts. JavaScript/external
errors are zero and all helpers exit.
The opposite-direction offline audit finds zero still-missing 2023 matches
among 2,609 retained 2024 detail occurrences:
`data/retained-reverse-provider-year-probe-20261023-v1.json`.
Residual bodies printing 2022 or the wrong chamber remain rejected, not
repaired by dropping dates/type letters. All network stops and human,
source-original, rights, party-time, scientific, report and publication
gaps remain unresolved; the public site is unchanged.

### Preceding context-qualified published recovery and completed inference

The opt-in packet
`data/processed/published-carryover-documents-20261023-v1/`, manifest
`2c44d7284ccf5c934871e79dc8a860c33d7cf7fe78260a535daa0367c817f01b`,
adds **two original 2024 Hawaii contexts / two complete views / 7,722
policy characters** without network requests. Its source packet retains the
complete original CSV, complete 9,002,451-row action Parquet and extraction
manifest. Actual bill-specific carryover and origin-introduction actions
support the link to own printed 2023 bodies; annual-session or URL aliases
are not inferred. Only these new view IDs append `:context:<original bill ID>`.
All old 27 published views/IDs, source fields, prologues, dates and negatives
remain unchanged. Ordinal 1203 already had a view with the literal
`2023 Regular Session` label; ordinal 1205 was retained but not previously
accepted. The first observer's contrary assumptions are corrected in
`data/published-carryover-packet-replay-20261023-v2.json`, not by rewriting
original evidence.

Availability is **139,208 / 157,598**, with **18,390** remaining, including
**5,737 HI**. Sixteen archives cover **10,753 contexts / 13,119 views**.
All 13,117 preceding archive rows, 305 other source partitions, twelve
other chart tables and 22 preceding complete source ZIPs remain unchanged.
Explorer **v30** has 779 artifacts, manifest
`c199a54c230be8c3329e25073ba2a3d473706d1a550db14c948c3050eb570aea`;
source gallery **v25** has 94 artifacts and 23 complete research ZIPs.

Actual completed job
`data/processed/cycle-topic-inference-retained-text-20261023-v14/`,
frozen from v30, contains **178,490 views / 157,598 original contexts**.
It yields **65,053 classified / 74,155 abstained / 18,390 unavailable**.
Both new contexts receive provisional assignments; all **157,596 other
whole assignment rows / 178,488 preceding view predictions** are unchanged.
Read-only extension of completed v13 encodes **one new string / 778 tokens /
one window**, with zero old encoder repeats. The other supplied text was
already cached. Logical all-view totals are **597,270,851 tokens / 781,982
windows**, with 615 excluded-source tokens separate. Full independent
token/logit/window/consensus/assignment replay and the complete 108-member
inference ZIP pass without encoder execution. Weights, thresholds, labels,
scientific code, human-plan bindings and metadata inference remain unchanged;
explicit summarization precedes graphing.

The current body gallery is
`outputs/topic-inference-retained-text-2023-2024-v12/`, 13 artifacts, manifest
`0bb2af5c041da819e08f5c28f9228d216697759ba3af541119a89b5b7c3ef73e`.
The current comparison is `outputs/topic-input-comparison-2023-2024-v10/`,
22 artifacts, manifest
`f627a8ce7ebbab5181809245add7bd46ee87d8c1b87161d729a05d7aab88d7f4`.
All 139,208 paired contexts and all seven tables are independently rebuilt:
42,024 same assigned topics / 6,109 different / 43,234 both abstaining /
47,841 exactly one abstaining. Missing bodies remain separate; these are not
accuracy measurements. All research downloads contain complete inputs.

The preceding completed v14 prediction cache has
**168,183 rows / 750,272,512 bytes**, SHA-256
`23ec30a9107a990368e3712363bde3893f791ae3db1e60f041bca479a23ce82b`.
The independently verified token cache is
`data/cycle-topic-independent-token-verification-cache-20261023-v11.sqlite`,
**168,183 strings / 40,087,552 bytes**, SHA-256
`3e7d36701df24f009f7af63c5dae24b27343b3dbd43a53a2944d057a42be0cbf`.
Both preceding caches remain unchanged.

Receipts are `data/published-context-source-union-replay-20261023-v1.json`,
`data/published-context-cache-extension-20261023-v1.json`,
`data/published-context-assignment-reconciliation-20261023-v1.json`,
`data/published-context-complete-inference-replay-20261023-v1.json` and
`data/published-context-comparison-replay-20261023-v1.json`.
Real Chromium proof
`data/published-context-browser-workspace-20261023-v1/receipt.json`
checks **286 complete bodies / 231 full carryover proofs**, including both
new published rows' complete source records, prologues and action/context
metadata; fifteen full-state queries (1,707 HI / 8,169 NJ), eighteen
byte-identical downloads, fourteen SVGs and desktop/mobile layouts pass.
JavaScript/external errors are zero and all helpers exit.
An independent offline NH audit admits zero sources: eleven of thirteen
leads lack a body, two retain own-2025 HTML, none has a PDF and the 178
original actions contain no literal session-transfer statement. Receipt:
`data/nh-original-action-carryover-audit-20261023-v1.json`.
All existing network stops and independent-human, source-original, rights,
party-time, scientific, report and publication gaps remain unresolved.

### Preceding finite public-identity recovery and completed inference

The new, disjoint packet
`data/processed/billcam-prestop-public-documents-html-20261023-v1/`
has manifest `2e68a62ad0323c0d78daea5e2a823b0bb22bb47fba287e3b2971d4a4dbddd9cf`
and recovers **15 original 2024 Hawaii contexts / 16 complete views /
58,828 characters**. It supplements all fourteen preceding archives.
Own printed state, 32nd Legislature/2024, typed number and caption match
the exact original gap contexts without date/session/URL repair.

Twenty exact identities were predeclared for ordinary public state/bill
search. Discovery retains 24 successful result pages before an explicit
search-login HTTP 401. That endpoint stays closed: no login, retry,
cookie reset, alternate search route or denied-result request is used.
A separate GET-only scope follows only fifteen public document links
already returned before the denial and their actual cached-text links.
It uses 31 GETs without cookies, accounts, API/search or native requests.
The failed search, every response/payload, partial result census and full
public bodies survive in the complete source packet. This is not a
completed twenty-query or statewide census. Controlled totals, including
failure, are **3,081 GETs / 26 POSTs**; inheritance is not new transport.

Source availability at that checkpoint is **139,206 / 157,598**, with **18,392**
remaining, including **5,739 HI**. Fifteen archives cover **10,751 contexts /
13,117 views**. Exact source replay preserves all previous archive rows,
305 other source partitions, twelve other chart tables and all 21 old
complete source ZIPs unchanged. Its explorer **v29** has 777 artifacts,
manifest `8aa1de9ab592a4e8569c77f9806c1d0dc31e17e338d1b0c262dcb26e8c331b2d`;
source gallery **v24** has 93 artifacts and 22 complete research ZIPs.

Actual completed job
`data/processed/cycle-topic-inference-retained-text-20261023-v13/`
is frozen from v29 with **178,488 source views / 157,598 original contexts**.
It yields **65,051 classified / 74,155 abstained / 18,392 unavailable**.
New contexts yield **eight provisional assignments / seven abstentions**;
all 157,583 other whole assignments and 178,472 old predictions are
unchanged. Read-only extension of completed v12 encodes only **16 new
strings / 15,303 tokens / 23 windows**, repeating no old inputs.
Logical all-view totals are 597,269,253 tokens / 781,980 windows, with
615 excluded-source tokens separate. Weights, thresholds, training labels,
scientific code, all human-plan bindings and metadata inference are unchanged.
Explicit summarization precedes graphing.

The preceding body gallery is
`outputs/topic-inference-retained-text-2023-2024-v11/`, 13 artifacts,
manifest `6c0793ff12c2a60df5a0a4d9ac5ad7842b4fa64bb3f6535f81f13c9c254c0061`.
Its comparison is `outputs/topic-input-comparison-2023-2024-v9/`,
22 artifacts, manifest
`8cb6cd4225c36e4d7d083b3f8d34bf1d93538e523f83bb26ed922f033f5b3671`.
Its 139,206 paired contexts contain 42,024 same assigned topics, 6,108
different topics, 43,234 both abstaining and 47,840 exactly one abstaining.
The 18,392 missing bodies remain separate; this is not an accuracy estimate.
Every cell of all seven tables and every full inference ZIP member is
independently checked. The source and model downloads remain complete bodies,
not metadata-only substitutes.

The preceding completed v13 prediction cache has **168,182 rows /
750,268,416 bytes**, SHA-256
`b0d2513e034448ce463422d36b5c30dbd4eaa17f58fdef15fd901072879a228f`.
The independently verified token cache is
`data/cycle-topic-independent-token-verification-cache-20261023-v10.sqlite`,
**168,182 strings / 40,087,552 bytes**, SHA-256
`2c74bf18f93e11f86acdeba0a3271503235a0fba1bece8f62c6ca8d4adc2ad3d`.
Both preceding caches remain unchanged.

Receipts are `data/identity-source-union-replay-20261023-v1.json`,
`data/identity-cache-extension-20261023-v1.json`,
`data/identity-assignment-reconciliation-20261023-v1.json`,
`data/identity-complete-inference-replay-20261023-v1.json` and
`data/identity-comparison-replay-20261023-v1.json`.
Actual Chromium proof
`data/identity-browser-workspace-20261023-v1/receipt.json`
checks all sixteen new bodies plus 268 preceding regression bodies,
fifteen full-state queries (1,705 HI / 8,169 NJ), eighteen byte-identical
downloads, fourteen SVGs and desktop/mobile layouts. JavaScript/external
errors are zero and every helper exits.
At that checkpoint, two separately observed published-corpus carryover
leads remain provisional; the subsequent context-qualified proof and
recovery are documented above, without modifying this preceding snapshot.
All human, rights, party-time, filing-originality, scientific, report
and publication gates remain unresolved.

### Preceding explicit original-action recovery and completed inference

Two opt-in packets recover **213 additional original Hawaii contexts /
229 unique complete views / 1,827,636 policy characters**:

- `data/processed/billcam-action-bound-html-delta-20261023-v1/`:
  27 contexts / 29 views, manifest
  `8cd20f56dde8d69ef9e1f8bed694526ecc1eddf091a508a53ff02a02d3f20b23`.
- `data/processed/billcam-action-bound-html-four-subject-20261023-v1/`:
  186 contexts / 200 views, manifest
  `0754dcbf9c7ba56eaf876575be54e232e1641637e58de635721f689eafd5dd37`.

These supplement, not replace, all twelve preceding archives. An unchanged
2024 context must have its own original "Carried over to 2024 Regular Session."
action and matching 2023 origin-introduction action IDs/chamber. The complete
9,002,451-row original action Parquet must match its original extraction
manifest. Own printed state, 32nd Legislature/2023, typed number and caption
must also agree. Printed 2023 and context 2024 are both retained; no original
date, session, unknown, native URL alias or filing-time version is repaired
or inferred. Without the explicit action packet, the default annual-heading
profile still rejects the mismatch.

The source manifest's opt-in `explicit_carryover_evidence` contains schema
`state-politics.original-carryover-actions.v1`, relative `actions` and
`extraction_manifest` paths and `extraction_manifest_sha256`.
Both complete source members are hash-bound; selected event summaries alone
cannot replace the original action table.
The lossless original-source inventory map replays every captured artifact.
All five earlier normalized packets and negative decisions remain immutable.

```bash
.venv/bin/python -I -B -m state_politics.bills.billcam_text build \
  --source-dir data/processed/billcam-action-bound-source-delta-20261023-v1 \
  --source-manifest-sha256 cf0ea3b743ec2df6b29cb35c22482b86243224238aa985ed09504d5dd9beca20 \
  --gap-queue outputs/recreated-2023-2024-v22/chart-data/missing_retained_text.parquet \
  --gap-queue-sha256 66e70f9247505eaacac96ee18a8bd5373c5454303fbd8aff6b61d584844ae6b9 \
  --out-dir data/processed/billcam-action-bound-html-delta-REPLAY
.venv/bin/python -I -B -m state_politics.bills.billcam_text build \
  --source-dir data/processed/billcam-action-bound-source-four-subject-20261023-v1 \
  --source-manifest-sha256 f09595888504e7937326174f8fb2a4ddde069d52d20281b0889455f4ebd273a4 \
  --gap-queue outputs/recreated-2023-2024-v22/chart-data/missing_retained_text.parquet \
  --gap-queue-sha256 66e70f9247505eaacac96ee18a8bd5373c5454303fbd8aff6b61d584844ae6b9 \
  --out-dir data/processed/billcam-action-bound-html-four-subject-REPLAY
```

Every output directory must be fresh. The first audit counted 238 historical
occurrences; exact view/body/context reconciliation finds nine repetitions
in an inherited capture. Select only the two packets above, not the redundant
nine-view `billcam-action-bound-html-full-20261023-v1` intermediate. Both that
intermediate and the failed union check remain evidence. The active union
is **229 views**, not 238. Proof:
`data/billcam-action-bound-packets-20261023-v2.json`.

The first source-gallery preflight correctly refuses the published corpus's
old BillCam dependency. Exact v1/v2 manifest/dependency bindings now preserve
their archived producers without switching observation-name profiles or
weakening source/certification guards. Both complete published packets still
replay all 27 bodies and all negatives unchanged. The browser explicitly
discloses the distinct printed/context years and full original action proof.

Source availability is **139,191 / 157,598**, leaving **18,407** missing,
including **5,754 HI**. Fourteen archival packets cover **10,736 contexts /
13,101 views**. The source-union proof checks all 12,872 old archive rows,
305 other source partitions, twelve other chart tables and nineteen
preceding complete ZIPs unchanged. Current source outputs are the
**775-artifact v28** explorer and **92-artifact v23** graph gallery.
Receipt: `data/action-bound-source-union-replay-20261023-v1.json`.

Actual completed job
`data/processed/cycle-topic-inference-retained-text-20261023-v12/` is frozen
from v28 with **178,472 views / 157,598 original contexts**. It yields
**65,043 classified / 74,148 abstained / 18,407 unavailable**; the 213
new contexts yield **143 provisional assignments / 70 abstentions**.
Every one of 157,385 other whole assignment rows and 178,243 preceding
predictions remains unchanged. The read-only completed v11 cache supplies
all previous inputs; only **188 new strings / 358,727 tokens / 479 windows**
reach the unchanged encoder, with **zero old inputs repeated**.
Logical all-view totals are **597,253,950 tokens / 781,957 windows**, with
615 excluded-source tokens separate. Weights, thresholds, training labels,
frozen scientific code and all human-plan bindings remain untouched.

Explicit summarization precedes graphing:

```bash
.venv/bin/python -I -B -m state_politics.analysis.cycle_topics summarize \
  --directory data/processed/cycle-topic-inference-retained-text-20261023-v12 \
  --tier retained_text
.venv/bin/python -I -B scripts/recreate_topic_graphs.py \
  --directory data/processed/cycle-topic-inference-retained-text-20261023-v12 \
  --tiers retained_text --out-dir outputs/topic-inference-retained-text-REPLAY
.venv/bin/python -I -B scripts/compare_cycle_topic_inputs.py \
  --metadata-gallery outputs/topic-inference-2023-2024-v2 \
  --retained-text-gallery outputs/topic-inference-retained-text-2023-2024-v10 \
  --out-dir outputs/topic-input-comparison-REPLAY
```

Current body gallery: `outputs/topic-inference-retained-text-2023-2024-v10/`,
13 artifacts, manifest
`49150f85814a2b42cafb1ce5cf25a9e186128b4ace90b2026c55f8870d4825c8`.
Its complete **108-member / 1,727,044,074-byte** inference ZIP has SHA-256
`a4a9aa2f4dce18704e1201c3ccb49c17a00d845da39e3b8748a2bd813696a7a7`.
The actual assignment Parquet is **25,965,041 bytes**, SHA-256
`b5e11a5f36c0a4146d2bcd184013703e7f1edc19d57332717363a5a16edeab47`.

The preceding completed v12 prediction cache has **168,166 rows / 750,219,264 bytes**,
SHA-256 `83fae74274e49121273c4a043bf21f2acf639ab9018d82a3354122073117f106`.
Future extensions use **v19 / token v16** above, not this older cache.
The preceding independently verified token cache is
`data/cycle-topic-independent-token-verification-cache-20261023-v9.sqlite`,
**168,166 strings / 40,087,552 bytes**, SHA-256
`e911fd6ad76440e7e8541bde4b6ee4cf0a2b495c530e9cd69a1256bdd2148d74`.
The original v11 prediction and v8 token caches remain unchanged.

Current comparison: `outputs/topic-input-comparison-2023-2024-v8/`,
22 artifacts, manifest
`ab36ffa405b3ab3fc2f4cc97f689f494dac88c062ee41f3c459da0a519fca447`.
Its 139,191 paired contexts contain 42,018 same assigned topics, 6,108
different topics, 43,229 both abstaining and 47,836 exactly one abstaining;
18,407 unavailable bodies remain separate. Every cell of all seven tables
and all fifty states, including empty Maine, is independently reconstructed.
This is input sensitivity, not accuracy. Metadata inference is not rerun.

Independent receipts are
`data/action-bound-cache-extension-20261023-v1.json`,
`data/action-bound-assignment-reconciliation-20261023-v1.json`,
`data/action-bound-complete-inference-replay-20261023-v1.json` and
`data/action-bound-comparison-replay-20261023-v1.json`.
Complete saved-logit/decision/source-consensus/token/window/ZIP replay uses
zero encoder passes and only 188 new independent tokenizations.
Actual Chromium proof
`data/action-bound-browser-workspace-20261023-v1/receipt.json` checks all
229 new bodies and original action metadata plus 39 preceding regression
bodies, fifteen full-state queries, nineteen byte-identical downloads,
fourteen SVGs, desktop/mobile, zero JavaScript/external-request errors and
exited helpers. Focused regression is 153 passes / three browser opt-in
skips; the enabled permanent browser fixture separately passes.
The full audit remains 430 / 464 with every baseline field and the same
34 legacy failures unchanged, not scientific certification.

All access stops remain binding. A separate ordinary anonymous state-search
discovery has two GETs and one POST, not new body requests; controlled
BillCam totals are 3,048 GETs plus one POST. Open States metadata discovery
stops at robots403 after four GETs, without a new dump acquisition or an
account-route workaround. Wider source discovery is a bounded negative,
not an acquired corpus or human benchmark. No independent-human, rights,
party-time, filing-originality, report, scientific or publication gate closes.

### Preceding cross-state independent publications

Two additional, disjoint archives recover **30 original contexts across fourteen
states / 179 complete supplied views / 10,117,496 policy characters**. They are
required alongside all ten preceding archives, not replacements for them:

- `data/processed/govbot-exact-original-documents-20261023-v2/`: three MT 2025
  contexts, 76 PDF file/version occurrences and 152 paired-reader views; manifest
  `8edb6c6de1f0af693092ba5d67d09ab0780898d304843f7ad14776241a1431d4`.
- `data/processed/published-ai-corpus-documents-20261023-v2/`: 27 contexts
  across thirteen states and 27 complete published `Bill_Text` bodies; manifest
  `207702b7bf4bdaac9e8fc61a55d385beb25edf55adef5c963d8c6e9a765aef4e`.

```bash
.venv/bin/python -I -B -m state_politics.bills.govbot_text build \
  --source-dir data/processed/govbot-exact-original-lead-source-20261023-v3 \
  --source-manifest-sha256 d5ab101b125c8dcf2ee75981b5938b841bea267d645dace9b5cb5378a68643dd \
  --gap-queue outputs/recreated-2023-2024-v19/chart-data/missing_retained_text.parquet \
  --gap-queue-sha256 e4a0e7de7c2fb789c5e7bbfa3ed04e04d8763507232f95199b99231a3a19b439 \
  --out-dir data/processed/govbot-exact-original-documents-REPLAY

.venv/bin/python -I -B -m state_politics.bills.published_corpus_text build \
  --source-dir data/processed/independent-ai-bill-corpus-source-20261023-v1 \
  --source-manifest-sha256 27e124cd8f99e58cb50e9e33b9036504fc3eb96a981394991d091441e9cc1ce1 \
  --gap-queue outputs/recreated-2023-2024-v19/chart-data/missing_retained_text.parquet \
  --gap-queue-sha256 e4a0e7de7c2fb789c5e7bbfa3ed04e04d8763507232f95199b99231a3a19b439 \
  --out-dir data/processed/published-ai-corpus-documents-REPLAY
```

The Govbot packet replays immutable Git membership and all thirty original
leads, 83 versions, 166 files and both readers' 2,263 PDF pages. Five received
PDFs remain rejected; whole source bodies are never replaced by amendments,
drafts, metadata or generated extraction prologues. The distinct 107-invocation
discovery and 161-total-invocation targeted capture preserve earlier failures
without budget resets; those are logical CLI, not physical HTTP counts.

The actual-page follow-up fixes a genuine first-page/every-page header
assumption: three same-byte enrolled SJ 1 occurrences print their own typed
header on page one, Senate-origin certificate on page 32 and formal title on
page 33. The narrow corrected profile binds all those own spans and preserves
all 33 pages in both reader inputs. Six views / 426,810 characters are restored
offline, not six new contexts. All 146 preceding v1 view rows and original
source/page bytes remain unchanged. The exact v1 manifest/producer still
replays its older negative decisions; neither v1 nor its first-pass outputs
is overwritten. Receipt:
`data/processed/govbot-enrolled-correction-20261023-v1.json`.
The superseded v9 job is only a frozen, unexecuted 178,237-view snapshot;
it has no classifier progress or prediction cache and is not a completed run.

The separately published CSV retains all 2,571 records / 29 original fields,
including every duplicate and negative. Its complete bytes and advertised MD5
are verified. Own printed headers, not the non-authoritative provider year,
establish the relation to unchanged original contexts. All source text and exact
prologue/body spans survive; AI excerpts, summaries, scores and party/control
fields remain opaque original metadata, never policy inputs or human gold.
Original/native completeness, source cleaning, dates and rights remain uncertified.
The author-described version-year derivation is not assumed correct: all 2,571
rows are audited and **74** disagree with their literal `Version_Date` year.
The complete discrepancy inventory preserves those original values without
repair, including the correctly recovered RI H 5866 2023 context despite its
provider `Year=2024`.

The v22 source union is **138,978 / 157,598** original contexts with some
retained text; **18,620** remain unavailable, including **5,967 HI**.
Twelve independent archives cover 10,523 distinct contexts / 12,872 views.
Both new complete research ZIPs preserve all packet members and negatives.
All prior outputs and original rows, unknowns, annual/session keys and access
stops remain intact. See [source attribution and limits](../CITATIONS.md#15-independently-published-govbot-legislative-archives).

External human-benchmark discovery is unresolved, not replaced with the CSV's
AI annotations. The metadata-only Florida capture stops at a retained robots403;
bounded archival alternatives stop at explicit robots/challenge restrictions.
No external labels, CSV field headers or scores enter the frozen human plan.

### Preceding v11 full-document inference

The completed job is
`data/processed/cycle-topic-inference-retained-text-20261023-v11/`, frozen
from the 771-artifact v26 explorer with **178,243 views / 157,598 original
contexts**. Actual conservative source consensus yields **64,900 classified /
74,078 abstained / 18,620 unavailable**. The thirty newly observed contexts
produce **eight provisional assignments / 22 abstentions**; uncertainty is
not replaced with forced labels. All **157,568 other whole assignment rows**
and all 178,064 preceding view predictions remain unchanged.

The observer extends the completed v8 cache through a read-only backup and
calls the original unchanged encoder for exactly **41 new strings / 253,863
tokens / 314 windows**, repeating zero old inputs. All 179 new views remain
separate, including same-body provider versions and both PDF readers.
Logical all-view totals are **596,816,865 tokens / 781,368 windows**, with
615 explicitly excluded source tokens separate. No model weights, thresholds,
training labels, source dates, frozen scientific runtimes or human-plan
bindings change; metadata inference is not rerun.

The actual encoder execution is preserved in completed v10. The comparison
guard then refuses a v1 descriptive uncertainty key ending `_certified`.
Published-source v2 renames only that observation, not a body or approval;
the exact v1 producer/profile still reproduces its historical packet.
Final v11 copies the completed v10 cache read-only and explicitly forbids
every nonempty encoder call. All **178,243 prediction rows / fifty state
prediction files / 157,598 assignment rows** remain byte-identical; only
27 source-observation metadata rows change. The first observer's overstrict
rejection of an empty no-op call is retained as a diagnostic; the corrected
observer permits only the original empty-list no-op, never a real encoder
input. Receipt: `data/cross-state-zero-encoder-replay-20261023-v1.json`.
The strict comparison guard itself is unchanged.

```bash
.venv/bin/python -I -B scripts/recreate_topic_graphs.py \
  --directory data/processed/cycle-topic-inference-retained-text-20261023-v11 \
  --tiers retained_text --out-dir outputs/topic-inference-retained-text-REPLAY
.venv/bin/python -I -B scripts/compare_cycle_topic_inputs.py \
  --metadata-gallery outputs/topic-inference-2023-2024-v2 \
  --retained-text-gallery outputs/topic-inference-retained-text-2023-2024-v9 \
  --out-dir outputs/topic-input-comparison-REPLAY
```

The actual body gallery is
`outputs/topic-inference-retained-text-2023-2024-v9/`: thirteen artifacts,
manifest `c171ec5cad159a201e6ce6ab1c8bb7be5539ad9e942402ac943f2f9e865db3a2`.
Its complete 108-member research archive is **1,724,918,983 bytes**, SHA-256
`ba3442a84e12346355750a601d84c6bb492236d04459f6d5f1d840d168126858`.
The actual assignments are 25,964,882 bytes, SHA-256
`0e09725b9ef5dbde09a4b9cdaa9059f2c589af26742b31f6ea3e6371d1875133`.

The preceding completed v11 prediction cache has **167,978 rows /
749,453,312 bytes**, SHA-256
`5fcab211a7885bccb6fde48351eeaeb71365e0f1328df1cc5bf4e3a2069809c0`.
Future extensions use completed **v19 / token v16**, as specified above;
neither this historical cache nor the superseded unexecuted v9 is current.
The preceding matching independent token cache is
`data/cycle-topic-independent-token-verification-cache-20261023-v8.sqlite`;
its original 167,937-row v7 baseline is backed up read-only and preserved.
The final cache holds 167,978 independently verified strings / 40,054,784
bytes, SHA-256
`658923403c935e0cc24680b0ff4e207dc8d6770c36c4dd7a2aabed649da17ba6`.
Archived observer source:
`data/cross-state-cache-extension-executed-source-20261023-v1.py`.
That source replays this exact v8-to-v10 encoder increment; it is not a generic
future-wave script or permission to rerun the full encoder population.

Exact source and assignment receipts are
`data/cross-state-source-union-replay-20261023-v3.json` and
`data/cross-state-assignment-reconciliation-20261023-v2.json`.
These establish computational/source consistency, not independent human
accuracy, filing-time text, party positions or publication approval.

The final comparison is `outputs/topic-input-comparison-2023-2024-v7/`:
22 artifacts, manifest
`9b77d2429c4aa33a0a88999965f67f3f83f08702d04e0fb8cc6ef17ad7dac999`.
Among 138,978 paired contexts, 41,898 have the same assigned topic, 6,104
different assigned topics, 43,205 both abstain and 47,771 exactly one abstains;
18,620 unavailable bodies remain separate. All seven comparison tables and
all fifty states, including empty Maine, are independently reconciled.
Both complete inference ZIPs are independent byte-identical copies, not
metadata-only substitutes.

Final complete replay:
`data/cross-state-complete-inference-replay-20261023-v2.json`.
Every saved input/logit/decision, conservative source consensus, complete
token/window span, original context and 108 ZIP members is rechecked with
zero encoder passes and zero new tokenizations. The original v10 replay,
failed strict-guard comparison log, empty-no-op observer diagnostic and
all previous snapshots remain preserved.

### Preceding NJ and independent PDF baseline

The preceding offline pass adds **7,004 existing contexts / 7,875 complete views**,
mostly NJ, with one additional NE context. Source packets:

- `data/processed/independent-archive-text-20261022-v2/`: pinned NJ mirror,
  7,001 contexts / 7,871 views; manifest
  `af315112eed07fb4fd0228d5182516ebd4f4d72ec263df218e134ed736c8a54b`.
- `data/processed/lawatlas-text-evidence-20261022-v1/`: four complete PDFs,
  including an overlapping A1899 alternative; manifest
  `f3efd87b8170dc5d414bd744cac9829ab0aab56560e66bd6a42788ae8fe3e12f`.

Both tracked producers are offline-only and refuse existing output directories:

```bash
.venv/bin/python -I -B -m state_politics.bills.archive_text \
  --archive data/processed/independent-archive-history-recovery-20261022-v1/nj-c99d1624.tar.gz \
  --gap-queue outputs/recreated-2023-2024-v9/chart-data/missing_retained_text.parquet \
  --out-dir data/processed/independent-archive-text-NEW

.venv/bin/python -I -B -m state_politics.bills.lawatlas_text build \
  --source-dir data/processed/new-public-corpora-nj-ok-ne-20261022-v1 \
  --gap-queue outputs/recreated-2023-2024-v9/chart-data/missing_retained_text.parquet \
  --out-dir data/processed/lawatlas-text-evidence-NEW
```

The NJ consumer replays every tar member, verifies the complete pinned Git
country tree, and requires exact original metadata, own printed identity and
one associated archived version link. Complete strings retain the archive's
existing machine prologue and all Unicode; raw HTML stays in the complete tar.
Combined substitutes retain all explicit own numbers without becoming extra
bills. A3493's session conflict, S2025's A4700 title conflict and A3857's
ancillary committee statement remain excluded. Older v1 is unchanged and
verifies under its original header profile.

The LawAtlas adapter replays all six PDFs and preserves original records,
675-row source/disposition accounting, duplicate references, source responses,
extraction alternatives and the original partial-size-abort caveat. Four
attachments match exact current candidate state/session/number identities;
two remain rejected. PDF text is never prepended with a title or summary.
Source licensing/version limitations remain explicit in
[the citation ledger](../CITATIONS.md#12-independent-legislative-archives).

Repeat `--archive-text` for both packets in the preview and graph CLIs.
The preview exports all 50 state plain/gzip archive partitions, full strings,
raw metadata, printed spans and source-member hashes. The gallery's two
additional ZIPs include every packet artifact, full raw tar/PDF/HTML evidence
and rejected rows, not metadata-only downloads. Provider overlap is counted
once per bill ID, while all 7,875 views remain available. All 632 prior
non-code explorer outputs remain byte-identical.

The v10 chart-data union now contains **135,459 / 157,598 contexts with some
retained text; 22,139 without observed text**. Its complete
`chart-data/missing_retained_text.parquet` preserves every original remaining
context field and authorizes no automatic collection. The coverage CSV keeps
separate research-corpus-only and independent-archive-only columns; the plot
combines their color without inflating totals. All approval flags remain false.

### Additional Maryland archive

`data/processed/maryland-archive-text-20261022-v1/` adds 563 previously
uncovered contexts and 1,070 complete source alternatives. These are existing
calendar-2024 prefilings with literal **2025 session labels**, not newly admitted
2023 bills or inferred filing dates. Its normalized adapter preserves original
metadata, full text, exact printed spans and the extraction prologue; 57 rejected
views and scoped source negatives remain separate. Its manifest is
`dc620e189324c6be284fc12fe6635cb4bbaac9c7536a861b608b9843703667ed`.

The v11 source-gallery union is **136,022 / 157,598 contexts with some retained
text; 21,576 remaining**. Its missing-text Parquet preserves every original
remaining context field. The gallery manifest is
`9f712cad707f1f2c8aa3a814be6d61b7c3e97af1b7735475efdc52a61efe0301`.
The complete Maryland source ZIP contains all 1,766 packet members, not just
the new query metadata. The packet does not certify filing-time versions,
redistribution rights, scientific completeness or further collection.

### Independent State Library bill texts

`data/processed/nj-library-text-20261023-v5/` retains 14 additional existing
New Jersey session-220 contexts, retaining 40 reader views / 20 source versions.
All eight complete PDFs / 231 physical pages are preserved in both readers;
228 reader pages form bill versions and 234 remain ancillary evidence.
A two-page checklist contributes no policy body. Exact source-proven reprint
boundaries preserve complete second/third reprints rather than dropping their
continuations; pypdf's literal spacing remains unchanged.

The archive loader strictly replays all original fields, identity/session
witnesses, page dispositions, raw HTTP evidence and full source texts.
The current source manifest is
`a27a57b4f72d43f0fc4235713e23b994bebc1a39f49f2284c2a990c1aa70df30`.
The v14 union remains **136,036 / 157,598 contexts with some retained text;
21,562 remaining**. The complete source ZIP includes the compiled originals,
both full reader-page records and every retained alternative, not just
query metadata. Introduced/enacted versions remain distinct and uncertified
for filing-time analysis; all scientific/model/publication approvals stay false.
The v14 graph manifest is
`aa19f6abf32ea11ff795326b2c550058647eabf7192a8d1635c8265a4e25466b`.
This is a source-metadata correction, not another recovery: v4 incorrectly
claimed a generated archive prologue where the complete library text has none.
The strict first extension freeze stopped before inference rather than guessing
a boundary. V5 changes only that false flag and its archived producer; all
original strings, page spans, versions, identities and gap fields remain exact.
Both sealed v1/v4 packets and the failed freeze remain preserved and replayable.
The inference producer and prologue-boundary validation are unchanged.

```bash
.venv/bin/python -I -B -m state_politics.bills.nj_library_text verify \
  --directory data/processed/nj-library-text-20261023-v5
```

The accepted source/current-metadata reconciliation is recorded in
`data/nj-library-parent-current-metadata-reconciliation-20261023-v1.json`.
Complete artifact/query/ZIP and original-field verification is in
`data/nj-library-parent-delivery-verification-20261023-v1.json`; the actual
desktop/mobile proof is under
`data/nj-library-workspace-browser-proof-20261023-v1/`.
The comparable tracked-input artifact audit is
`data/nj-library-tracked-artifact-audit-20261023-v2.json`:
418 / 452 checks, with the same 34 legacy missing-output failures.
The subsequent metadata correction is independently replayed in
`data/nj-library-prologue-repair-parent-verification-20261023-v2.json`:
all 748 preview / 75 source-gallery outputs, 65 complete ZIP members and all
original strings/fields, with only four expected preview exports changed.
These receipts do not certify source versions, independent accuracy or
independent accuracy of the separate full-text inference.

### Complete library collection and distinct annual-context source relations

The separately sealed full 2023 library packet is
`data/processed/nj-library-2023-collection-20261023-v1/`: 237 items, 229 newly
captured PDFs and eight exact-URL reuses. Its new normalized archive,
`data/processed/nj-library-collection-text-full-20261023-v1/`, preserves all
9,952 physical pages from both readers, including 19,904 complete page/layout
records and every negative disposition. It recovers **97 exact original
contexts / 255 reader views**, not 229 new bills. Only 58 PDFs contribute
matching views; unsupported identity/boundary/continuation cases remain
quarantined. One new URL with old chapter-329 bytes is not counted as new text.
The earlier first-sixteen archive contains four of these same contexts and
must **not** be added alongside the full archive.

```bash
.venv/bin/python -I -B -m state_politics.bills.nj_library_collection verify \
  --directory data/processed/nj-library-collection-text-full-20261023-v1 \
  --metadata data/processed/study-abstract-evidence-2023-2024-v4/bill_evidence.parquet \
  --source-manifest-sha256 195c78827c877ceb3c9e22ba4d0693585abad4121224c2be78bd0d66ea7ef1de \
  --gap-queue-sha256 839b4874c7c8343caf3ecb831f1179f70691c27e92cf10af9372cf2acba5eb69
```

The full normalized manifest is
`e8933b0d69ab9a791ef4830e35044fde4022e8df2880f4a9c544426a9f9601a6`.
It archives both its collection producer and the unchanged legacy library
dependency. A successful build independently re-extracts every original PDF
page with both readers and compares the complete replay; the post-build audit
additionally rehashes all 2,209 artifacts. This does not certify reader truth,
introduced-version dates, complete statewide coverage or source rights.

`data/processed/ok-retained-context-text-20261023-v2/` adds **2,000 exact
original missing contexts / 14,394,639 body characters**. The original
2023-source / 2024-candidate contexts remain distinct. Two complete primary
House announcements bind their legislative-cycle context, while both existing
version pointers and the original source text/version foreign keys bind each
body. A generic session relation is not a bill-specific carryover, pending,
filing or introduction finding. The body authority remains a third-party
snapshot extraction, not native publisher bytes. All 2,135 witnesses,
135 rejections, original references and full 21,562-row source queue survive.

```bash
.venv/bin/python -I -B -m state_politics.bills.ok_retained_context_text verify \
  --directory data/processed/ok-retained-context-text-20261023-v2 \
  --metadata data/processed/study-abstract-evidence-2023-2024-v4/bill_evidence.parquet
```

The current manifest is
`de881d50d6fe4ce29d466e6fc83253ba68b0bf6701555a090aa47bcee40af9d8`;
the prior v1 archive remains unchanged and replayable with its own producer.
Missing/error/empty source facts and missing or ambiguous original version
foreign keys fail closed. The source explorer explicitly discloses the two
annual contexts and retains both original records rather than claiming an
exact annual-session match or calling a snapshot extraction a PDF.
These two new packets are supplied **in addition to the original four
archives**, including the unchanged eight-PDF library v5 packet. None grants
training, source, filing-time, native, party, human-gold, scientific or
publication approval.

### Current four-subject recovery, corrected headings and actual inference

All four additional published subject catalogues are captured completely as
query results: **187 pages / 3,707 occurrences / 3,603 distinct provider records**,
with two duplicate occurrences preserved. The finite 605 original-context
leads include one already captured but unadmitted provider path; all 604 new
details and 825 offered-version dispositions are accounted for. The thirteen-GET
discovery and distinct **1,612 / 2,000-GET** capture remain closed. Known
controlled curl capture totals **3,046 GETs**, not distinct URLs or all
unrelated transport. Source manifest:
`fcda8cfced4df5e35630247a49e603d4d1316dccb8ea751b0fb41dad0a07fd82`.

The ninth archive is `data/processed/billcam-four-subject-html-20261023-v1/`,
manifest `801644d9387b094f142e544a638e13e3a942d9d31eecf8c181d6345ae674c15e`:
**415 contexts / 619 views / 4,674,311 characters**. A separate GPT-6.1 Sol
audit of all 206 rejected versions finds zero different-context candidates
but proves a literal-space venue-regex bug in two same-context HB 1993 views.
The corrected reader accepts their actual wrapped heading and requires the
own printed bill caption. The conflicting HB 2699 caption remains quarantined.
No legislative heading, prologue, URL alias, filing date or carryover is invented.

The tenth archive is `data/processed/billcam-wrapped-heading-html-20261023-v1/`,
manifest `23343ed2edc6a4b38e8a32808079e2507bf6c4048def1f30debcd345437adab5`:
**one context / two views / 10,687 characters**. Its source is an offline
lossless projection of the same capture onto the exact original remaining
18,651-row subset, not another network scope. Every original source artifact
and historical ledger survives; projected historical requests are not counted
again. Both new archives are disjoint and required alongside the preceding
eight. Four exact SHA-pinned historical normalizations replay their old
identity profile without rewriting previous accepted or rejected records.

```bash
.venv/bin/python -I -B -m state_politics.bills.billcam_text verify \
  --directory data/processed/billcam-four-subject-html-20261023-v1
.venv/bin/python -I -B -m state_politics.bills.billcam_text build \
  --source-dir data/processed/billcam-wrapped-heading-source-projection-20261023-v1 \
  --source-manifest-sha256 0f56ea100ff074ba61565add690a5c6b857008844ff025f48d92be30b094e74f \
  --gap-queue outputs/recreated-2023-2024-v18/chart-data/missing_retained_text.parquet \
  --gap-queue-sha256 9c008774665e2c0186bc84f5b8475025bf496cd859f8396be1dce917f70158d7 \
  --out-dir data/processed/billcam-wrapped-heading-REPLAY
```

The preceding wrapped-heading job is
`data/processed/cycle-topic-inference-retained-text-20261023-v8/`, from the
**763-artifact v23** preview: **178,064 views / 157,598 original contexts**,
**64,892 classified / 74,056 abstained / 18,650 unavailable**.
The latest 416 contexts yield 253 assignments and 163 abstentions; all
**157,182 other whole assignment rows** and all 177,443 preceding view
predictions are unchanged. Sequential read-only cache backups extend completed
v6 to v7 to v8. Exactly **621 new strings / 1,116,712 tokens / 1,507 windows**
reach the original encoder, with no old input repeated. Logical all-view totals
are **594,380,337 tokens / 778,554 windows**; 615 excluded tokens remain
separate. Weights, thresholds, labels, five frozen scientific runtimes and the
unannotated human plan/packet are unchanged. Metadata inference is not rerun.
`run` requires an explicit `summarize` before graphing; accepted jobs are already
summarized and must not be overwritten.

```bash
.venv/bin/python -I -B scripts/recreate_topic_graphs.py \
  --directory data/processed/cycle-topic-inference-retained-text-20261023-v8 \
  --tiers retained_text --out-dir outputs/topic-inference-retained-text-REPLAY
.venv/bin/python -I -B scripts/compare_cycle_topic_inputs.py \
  --metadata-gallery outputs/topic-inference-2023-2024-v2 \
  --retained-text-gallery outputs/topic-inference-retained-text-2023-2024-v7 \
  --out-dir outputs/topic-input-comparison-REPLAY
```

The preceding completed v8 prediction cache was:
167,937 rows / 749,195,264 bytes, SHA-256
`37a31f1792a52226efb1b5b5f9ed4a607952c46c7bb18e619226acc1ffeb0f1f`.
The matching independent token cache is
`data/cycle-topic-independent-token-verification-cache-20261023-v7.sqlite`,
167,937 inputs / 40,046,592 bytes, SHA-256
`44071865c5cd4411e7d5cc4ef1f54c3f155121ea30fa67e6ec0e811f89dadac5`.
Copy read-only before extension; retain every old cache and job.

Current body gallery: `outputs/topic-inference-retained-text-2023-2024-v7/`,
manifest `a71232a4b4f79a366183e24da016b5129b3574672fb220d7459cb91ca4a44964`.
Its complete 108-member / **1,720,113,960-byte** inference ZIP has SHA-256
`0b8e55dc26fbd6268d495cb55c92954eace058d16654760048d1c0d500ba919c`.
Comparison: `outputs/topic-input-comparison-2023-2024-v6/`, manifest
`cfcc91561818050b9974cead8bb4812d0914c370db2ee4f896d3e2ab2d481983`.
The paired **138,948** denominator includes 41,895 same assigned topics,
6,102 differing topics, 43,192 both abstaining and 47,759 exactly-one
abstentions. The other 18,650 contexts are unavailable, not disagreements.
All seven tables retain original fields and all fifty states, including empty
Maine; both complete inference source ZIPs are independent byte-identical copies.

Independent computational and browser receipts use the
`data/billcam-wrapped-heading-` prefix: `complete-inference-replay-20261023-v1.json`,
`cumulative-assignment-reconciliation-20261023-v1.json`,
`comparison-replay-20261023-v1.json` and
`browser-workspace-20261023-v1/receipt.json`. Real Chromium verifies all fourteen
source SVGs, desktop/mobile, full 1,453-view HI and 8,169-view NJ downloads,
both new source ZIPs, both inference ZIPs and exact 54,215-/6,236-character
new bodies. Independent inert-DOM checks pass all 619 + two new views without
source scripts or external traffic; all helpers exit. These are source,
computational and UX checks, not human accuracy or release approval.

### Preceding 399-context HTML recovery and actual inference

The initial BillCam source packet retains the closed 16 + 500-GET wave,
including its invalid first URL and catalogue-parser failure:
`data/processed/billcam-hi-target-source-20261023-v2/`, source manifest
`a1137754c36f2a4847c458eebaeaf20e33e1b7e4ba983892ccc65c8153e0d54a`.
The separate identified follow-up and terminal tail retain all prior ledger
prefixes and every original source byte, without resetting either allowance:
`data/processed/billcam-hi-identified-tail-20261023-v1/`, manifest
`3ceff25fa1b2951b06a4bb2cc83eb71839fe8a6ab4d0328ec60e057a983317a9`.
All three subject catalogues are fully retained as published query results,
including duplicate rows; that is not a statewide census or a random sample.
Known capture total: **16 + 500 + 800 + 105 = 1,421 GETs**.

Use **both disjoint** normalized packets, never the two-context prototype:
`billcam-hi-retained-html-full-20261023-v1` supplies 111 contexts / 253 views,
manifest `9bfeaefd6fa650f37fe8248f0ba3fff2834979022240cafe67cb24adb5c90c4b`;
`billcam-hi-retained-html-delta-20261023-v1` supplies 288 / 579, manifest
`588d4280d8476623864527595969c751f2bff2085b2f687e6098c51d1b95a89d`.
Together they retain **399 original contexts / 832 views / 9,370,186
characters**. Original fields, IDs, unknowns and version references survive.
Own printed state/year/32nd-Legislature/typed-number and provider-context/title
checks do not infer native URL aliases, carryover, filing dates, historical
party or rights. Complete source-container HTML remains independently
available; provider UI/tags/current sponsors are not body inputs or gold.

Exact historical replay uses the archived producer and fresh output directories.
The current builder intentionally applies the corrected identity profile;
the current verifier selects legacy behavior only for the exact sealed hashes:

```bash
.venv/bin/python -I -B data/processed/billcam-hi-retained-html-full-20261023-v1/producer/billcam_text.py build \
  --source-dir data/processed/billcam-hi-target-source-20261023-v2 \
  --source-manifest-sha256 a1137754c36f2a4847c458eebaeaf20e33e1b7e4ba983892ccc65c8153e0d54a \
  --gap-queue outputs/recreated-2023-2024-v15/chart-data/missing_retained_text.parquet \
  --gap-queue-sha256 5a1579117cf5db171fced211022269c6a03d9f8ae142eb74ec534e050dc32f46 \
  --out-dir data/processed/billcam-first-REPLAY

.venv/bin/python -I -B data/processed/billcam-hi-retained-html-delta-20261023-v1/producer/billcam_text.py build \
  --source-dir data/processed/billcam-hi-identified-tail-20261023-v1 \
  --source-manifest-sha256 3ceff25fa1b2951b06a4bb2cc83eb71839fe8a6ab4d0328ec60e057a983317a9 \
  --gap-queue data/billcam-hi-identified-followup-gap-queue-20261023-v1.parquet \
  --gap-queue-sha256 55d5bd82e84b7b70d92677208bd4db03f68fec64e2e847d5f32f17317fdfe004 \
  --out-dir data/processed/billcam-delta-REPLAY
```

The preceding retained-body job is
`data/processed/cycle-topic-inference-retained-text-20261023-v6/`, frozen from
the 759-artifact v21 preview: **177,443 views / 157,598 original contexts**,
**64,639 classified / 73,893 abstained / 19,066 unavailable**. The increment
is 204 classifications and 195 abstentions; all 157,199 other whole assignment
rows and every preceding view prediction are unchanged. Two read-only backups
extend the latest completed cache in order, v4 to v5 to v6. Exactly **832 new
strings / 2,183,697 unique tokens / 2,810 windows** reach the original encoder,
with no old strings repeated. Logical all-view totals are **593,263,625 tokens /
777,047 windows**, not unique encoder work. Model, policy, labels and all
frozen scientific runtimes remain unchanged; metadata inference is not rerun.
The `run` command must be followed by `summarize` before plotting.
For a newly completed replay job only:

```bash
.venv/bin/python -I -B -m state_politics.analysis.cycle_topics summarize \
  --directory data/processed/cycle-topic-inference-retained-text-NEW \
  --tier retained_text
```

The accepted v6 job is already summarized; leave it immutable and regenerate
its graphs into fresh directories:

```bash
.venv/bin/python -I -B scripts/recreate_topic_graphs.py \
  --directory data/processed/cycle-topic-inference-retained-text-20261023-v6 \
  --tiers retained_text --out-dir outputs/topic-inference-retained-text-REPLAY
.venv/bin/python -I -B scripts/compare_cycle_topic_inputs.py \
  --metadata-gallery outputs/topic-inference-2023-2024-v2 \
  --retained-text-gallery outputs/topic-inference-retained-text-2023-2024-v5 \
  --out-dir outputs/topic-input-comparison-REPLAY
```

The completed cache at that checkpoint was **v6**; current extensions
must use completed **v8** as documented above.
Its 167,316-row prediction cache is 746,754,048 bytes, SHA-256
`8989a4489a3c75a69755eefbbf02891c509ad02a108af623505eb8d8e8213626`.
The separate 167,316-input independent token cache is
`data/cycle-topic-independent-token-verification-cache-20261023-v5.sqlite`,
39,911,424 bytes, SHA-256
`378c9d05e45ee4f6d140a8d1b90af89b76cbc06b68d9d663a0ee9646dbe0c2e9`.
Copy caches read-only before extension; do not mutate old jobs or repeat
their encoder work.

The preceding body gallery is `outputs/topic-inference-retained-text-2023-2024-v5/`,
manifest `cfe0bd8a3348076fb8d22c73de9f9cfbd2115d8b7c456b1782a3adf0bc4e151a`.
Its **108-member / 1,714,773,128-byte** full inference ZIP has SHA-256
`7c788450ca050507a3606ad31c8afb43dee96db1dd57255574c23d6178ea7da8`.
Comparison: `outputs/topic-input-comparison-2023-2024-v4/`, manifest
`bbc4d4a7256f30e0efc73f99edec81d35283fe1f24f5a2c69a79cf9a3a013513`.
The **138,532** paired denominator includes 41,727 same assigned topics,
6,092 differing topics, 43,106 both abstaining and 47,607 exactly-one
abstentions. The other 19,066 contexts are unavailable, not disagreements.
Every original bill field and all seven comparison tables are independently
reconstructed, including all fifty states and empty Maine. Both complete
source inference ZIPs are independent byte-identical copies.

Actual Chromium checks complete HI/NJ queries, exact bodies from both new
packets, all fourteen source SVGs, desktop/mobile layouts and complete source
and inference ZIP bytes. Separate inert-DOM checks preserve every supplied
source character stream without source scripts or external traffic.
These are computational/source/UX checks, not human topic accuracy,
native-original certification, filing eligibility, party evidence or release.
Final independent receipts include
`data/billcam-final-complete-inference-replay-20261023-v1.json`,
`data/billcam-final-cumulative-assignment-reconciliation-20261023-v1.json`,
`data/billcam-final-comparison-replay-20261023-v1.json` and
`data/billcam-final-browser-workspace-20261023-v1/receipt.json`.

### Preceding complete-collection inference and delivered graphs

The preceding retained-body freeze is
`data/processed/cycle-topic-inference-retained-text-20261023-v4/`, made from the
754-artifact v19 preview. Its **176,611 views / 157,598 original contexts** produce
**64,435 assignments / 73,698 abstentions / 19,465 unavailable bodies**.
Of the 2,097 newly observed contexts, 1,336 classify and 761 abstain; all other
155,501 complete original assignment rows remain unchanged. The source-current
2023/2024 relations are not target-year filing-time certification.

A separately copied read-only v3 prediction cache preserves all 166,232 old
entries and 174,356 old view predictions. Observed original encoder calls
process exactly **252 new strings / 3,256,075 tokens / 4,166 windows**, with no old
encoder string repeated. Logical source-view totals are
**591,079,928 tokens / 774,237 windows**, including repeated-text reuse.
The model, thresholds, labels, original contexts and frozen runtime remain
unchanged. No metadata inference is rerun.

```bash
.venv/bin/python -I -B scripts/recreate_topic_graphs.py \
  --directory data/processed/cycle-topic-inference-retained-text-20261023-v4 \
  --tiers retained_text --out-dir outputs/topic-inference-retained-text-REPLAY

.venv/bin/python -I -B scripts/compare_cycle_topic_inputs.py \
  --metadata-gallery outputs/topic-inference-2023-2024-v2 \
  --retained-text-gallery outputs/topic-inference-retained-text-2023-2024-v3 \
  --out-dir outputs/topic-input-comparison-REPLAY
```

The preceding body gallery is `outputs/topic-inference-retained-text-2023-2024-v3/`,
manifest `13a0804ddbd386f479c48657eafe678a5953fa61856f61b3c16feb1f6f4fec09`.
Its full 108-member inference ZIP is 1,704,563,375 bytes, SHA-256
`b81b33b0ce244a138a5eb3223dde0a4d96dbfed64925efe152028d24af140b9e`.
The preceding comparison is `outputs/topic-input-comparison-2023-2024-v2/`,
manifest `0567f781b1d332ecc24f8faa258c17b01084207a09914f425b73b3f552d5cbcf`.
All **138,133 paired contexts** include abstentions: 41,575 share an assigned
topic, 6,083 differ, 43,014 both abstain and 47,461 have exactly one abstention.
The other 19,465 contexts are unavailable, not disagreements. All fifty state
rows, including Maine's zero observed candidate population, remain explicit.
Both complete original source inference ZIPs are independently copied into the
comparison bundle.

Full independent computational replay is recorded in
`data/new-recovery-complete-full-text-replay-20261023-v1.json`; all seven
comparison CSVs and every bill field are reconstructed in
`data/new-recovery-comparison-independent-replay-20261023-v1.json`.
The old independent token cache is copied before extension, never mutated.
Real Chromium verifies the different annual-context disclosure, complete query
downloads, all topic/source images and SVGs, both source ZIPs and both full
inference ZIPs, desktop/mobile layouts and a **1,035,255-character** new library
body with its exact hash. Proofs:
`data/new-recovery-browser-evidence-20261023-v2/receipt.json` and
`data/new-recovery-browser-workspace-20261023-v1/receipt.json`.
All helper processes exit. These are implementation and source-preservation
checks, not independent classifier accuracy, human annotation or publication.

For the comparable full tracked-artifact audit, use the already installed
**exact pinned OCR runtime**, not the separate 5.5.3 environment or a bare
non-login shell PATH:

```bash
PATH="$PWD/data/tools/ocr-5.5.2/bin:$PATH" \
  .venv/bin/python -I -B scripts/audit_reproducibility.py \
  --require-tracked --report data/REPLAY-tracked-artifact-audit.json
```

The preceding report,
`data/new-recovery-tracked-artifact-audit-20261023-v3.json`, is **424 / 458**,
with precisely the same 34 legacy missing-output failures and every other
baseline report field unchanged. Its expected nonzero exit is retained.
An inventory-only invocation is not comparable to that full audit. The
preserved diagnostic mismatches were not promoted into a successful audit or
used to fabricate the missing analytical outputs.
The current comparable report,
`data/billcam-wrapped-heading-tracked-artifact-audit-20261023-v1.json`, is **426 / 460**:
the two added checks pass, the same 34 legacy failures remain, and all other
baseline fields are unchanged. The preceding
`data/billcam-final-tracked-artifact-audit-20261023-v2.json` is preserved.

## Provisional population topic inference

The user has requested actual inference and topic graphs, not only source
coverage charts. The saved reviewed-only ModernBERT checkpoint can be run
explicitly for **research-only descriptive assignments** at its unchanged
temperature 1 / confidence 0.8 / margin 0.2 policy. It is not independently
certified or promoted. Source/model/party/filing-time/publication approvals
remain false. No new training, threshold tuning or human labels are involved.
Metadata inference and retained-full-text inference are separate evidence
tiers; later or unknown source versions are not certified filing-time text.

Freeze into a new directory before running:

```bash
.venv/bin/python -I -B -m state_politics.analysis.cycle_topics freeze \
  --preview data/preview-cycle-evidence-v26 \
  --checkpoint data/models/modernbert-reviewed-only-20261021-v1 \
  --tiers metadata \
  --out-dir data/processed/cycle-topic-inference-metadata-NEW

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -I -B -m state_politics.analysis.cycle_topics run \
  --directory data/processed/cycle-topic-inference-metadata-NEW \
  --tier metadata --allow-provisional --batch-size 32

.venv/bin/python -I -B -m state_politics.analysis.cycle_topics summarize \
  --directory data/processed/cycle-topic-inference-metadata-NEW --tier metadata

.venv/bin/python -I -B scripts/recreate_topic_graphs.py \
  --directory data/processed/cycle-topic-inference-metadata-NEW \
  --tiers metadata --out-dir outputs/topic-inference-2023-2024-NEW
```

The completed metadata run is
`data/processed/cycle-topic-inference-metadata-20261022-v1/`, frozen from the
preserved v15 metadata inputs. It processed all 159,315 views / 157,598
contexts and yielded **89,950 assignments / 67,648 abstentions**.
Its three actual topic graph pairs, four CSVs and complete 108-member
inference ZIP are in `outputs/topic-inference-2023-2024-v2/`; manifest
`0dad7b9f4e871fd4aae93c5d84b17284c7df0d64455105cbe0d6e8d7123c868d`.
The ZIP retains all complete source-view inputs and predictions.

Use a separate freeze with `--tiers retained_text` for a full-text pass.
The actual separate job
`data/processed/cycle-topic-inference-retained-text-20261022-v1/` freezes
174,316 full-body alternatives from v16. It completed all 50 states with
63,089 assignments / 72,933 abstentions / 21,576 unavailable body contexts.
Its three actual graph pairs and complete 108-member inference ZIP are in
`outputs/topic-inference-retained-text-2023-2024-v1/`.
The 584,371,720 token / 765,016 window totals include repeated source-view
cache reuse, not unique encoder work. Full parent replay and the separate
library-inclusive extension have now completed. Preserve the completed freeze
and its hash-bound producer/runtime rather than rerunning or editing it.
Full bodies and all source alternatives are retained, not truncated or
silently replaced by titles. The archive's machine-generated prologue is
excluded only by its exact source-bound span; the complete original string
still travels in the inference input/download. Empty/error snapshot rows
do not become bill-body inputs. Missing full text remains an explicit
unavailable context, not a topic zero or a hidden metadata fallback.

Every selected view has complete original source fields, input/source hashes,
token/window spans, full logits and the frozen model/taxonomy identity.
Cross-document window batching reuses the unchanged per-document decision
rule. Exact repeated input strings reuse a persistent cache; logical
source-view token totals are not misrepresented as actual encoder work.
Completed state outputs, input files, model/policy and batch configuration
are bound for resume. Interrupted outputs are preserved, not silently
overwritten, and invalid caches/changed outputs fail explicitly.

A bill counts once per tier. All its supplied usable views must agree on
the same non-null topic; disagreements or abstaining alternatives produce
an explicit bill-level abstention. Topic shares use all candidate contexts,
with abstentions visible. No-candidate or entirely unavailable state/topic
cells remain unknown. The three topic graphs show assigned counts,
state assignment/abstention coverage and all-candidate state/topic shares;
they do not estimate accuracy, ideology, policy agreement or party positions.

Graph ZIPs include **every complete selected-tier inference input and
prediction**, raw source-view fields, bill assignments and frozen producers,
not only chart metadata. An optional `--topics` argument to
`scripts/serve_research.py` mounts a completed topic gallery beside the
existing source graphs. It never exposes models/cache/unlisted files or
executes inference. Blind human reviewers must not inspect these predictions
before independently submitting annotations; the human-review packet and
its frozen evaluation plan remain separate and unchanged.

### Adding recovered text without repeating completed encoder work

Never modify an active or completed freeze to attach later source evidence.
After accepting a new evidence preview, freeze it into a **new** retained-text
job using the same checkpoint and policy. Only after the original full-text
run completes, copy its exact-input cache with SQLite's read-only backup API:

```python
import sqlite3
from pathlib import Path
from state_politics.analysis.cycle_topics import checked_job, read

source = Path("data/processed/cycle-topic-inference-retained-text-20261022-v1").absolute()
target = Path("data/processed/cycle-topic-inference-retained-text-NEW").absolute()
progress = read(source / "progress-retained_text.json")
assert progress["status"] == "complete_provisional_inference_not_scientific_validation"
assert len(progress["states"]) == 50
old, new = checked_job(source), checked_job(target)
for key in (
    "model_run", "decision", "taxonomy_sha256", "contexts", "n_contexts",
    "producer", "frozen_inference_runtime", "scope", "source_alternative_policy",
    "source_selection", "inference_engine", "padded_window_token_budget",
):
    assert old[key] == new[key], key
assert not (target / "progress-retained_text.json").exists()
assert not (target / "prediction_cache.sqlite").exists()
with sqlite3.connect(
    f"file:{source / 'prediction_cache.sqlite'}?mode=ro", uri=True,
) as original, sqlite3.connect(target / "prediction_cache.sqlite") as copied:
    original.backup(copied)
```

Run and summarize the new job normally with the unchanged batch size 32.
The runner validates each reused input/model/logit decision and encodes only
genuinely new text. Repeated source views still retain their own identities
and original fields. All alternatives are reaggregated in the new version,
including newly recovered views of previously unavailable bills.
The original job, cache, inputs and predictions remain unchanged. A focused
integration regression verifies that a new source freeze makes only the new
encoder call while preserving every original job binding. This is an
extension procedure, not independent validation or permission to alter the
completed baseline.

The accepted extension is
`data/processed/cycle-topic-inference-retained-text-20261023-v3/`, frozen from
preview v18 after the library-prologue repair. It retains **174,356 views**;
all original context, model, policy, producer and runtime bindings match.
The original cache is unchanged and all 174,316 prior view predictions are
identical. Observed original encoder work is exactly **40 new input strings /
144,143 tokens / 195 windows**, not a repeat of the completed population.
The final **157,598** bill rows contain **63,099 assignments / 72,937
abstentions / 21,562 unavailable bodies**. Logical view totals are
584,515,863 tokens / 765,211 windows. The full parent replay checks all
decisions, original fields, complete token spans, bill consensus and all
108 research ZIP members; original and extension proofs are
`data/cycle-topic-complete-full-text-replay-20261023-v1.json` and `v2.json`.
The separate new-only encoder/cache proof is
`data/cycle-topic-library-cache-extension-20261023-v1.json`.

The accepted final body-topic gallery is
`outputs/topic-inference-retained-text-2023-2024-v2/`; its manifest is
`7654413cc4e2b5b473a8007abe06778235b0d546b82d3ce35232ae6a0d9ff08f`.
It contains three PNG/SVG pairs, four CSVs and the complete
1,665,943,130-byte / 108-member inference ZIP.

### Matched metadata/body comparison

```bash
.venv/bin/python -I -B scripts/compare_cycle_topic_inputs.py \
  --metadata-gallery outputs/topic-inference-2023-2024-v2 \
  --retained-text-gallery outputs/topic-inference-retained-text-2023-2024-v2 \
  --out-dir outputs/topic-input-comparison-REPLAY
```

The actual accepted build is
`outputs/topic-input-comparison-2023-2024-v1/`, manifest
`950dab8cc1dfa7c7ba39b6302b494bfeb27b69ec492927afe67f17a9c4a52fbf`.
The consumer needs only the two completed, self-contained source galleries;
it neither opens their original model paths nor executes inference. It
verifies every source member, cohort/model/policy identity, false approval
and original view before creating a fresh output directory.

Two graph pairs show topic-share differences on the **same 136,036 paired
available candidates**, including abstentions, and row-conditional topic /
abstention transitions. Seven CSVs include all 157,598 bill-level comparisons,
national/all-50-state summaries and every topic/transition cell. Empty paired
groups and zero-denominator transition shares remain unknown; observed zeros
remain zero. Missing body evidence is not a disagreement, and both abstaining
is not accuracy. Full text remains in both complete original research ZIPs,
copied as independent files with exact hashes, alongside source manifests,
plans and producers. The companion is not a metadata-only download.

Independent reconstruction of every exported row and all seven tables is in
`data/cycle-topic-input-comparison-independent-replay-20261023-v2.json`.
The actual six-mount Chromium proof checks final body/comparison galleries
at desktop/mobile widths, both full inference ZIP downloads, the corrected
library ZIP, complete NJ query and original body rendering:
`data/cycle-topic-final-browser-proof-20261023-v2/receipt.json`.
All helpers exited. Source versions, classifier accuracy, filing-time
alignment, independent human evaluation and publication remain uncertified.
The final comparable tracked-artifact audit,
`data/cycle-topic-final-tracked-artifact-audit-20261023-v1.json`, reports
**420 / 454**, with exactly the same 34 legacy missing-output failures
and all other report fields unchanged. The 178 public-documentation checks
and targeted source/comparison passes do not turn that red artifact gate
or the independent scientific gates green. Five inspected owned scratch/profile
trees were removed only after helper exit; actual sources, failed real builds,
logs, JUnit files, downloads, caches and model weights remain retained.

## October 22 recovered inputs

The accepted packets are:

| Packet | Complete retained evidence |
|---|---|
| `data/processed/recovered-platform-graph-inputs-20261022-v1` | Both original modern table snapshots, 202 original rows, 3,917 full evidence views, 1,559 capture attempts and repetition/failure accounting. |
| `data/processed/cycle-outcome-evidence-20261022-v2` | 157,598 candidate contexts, 1,509,874 selected actions and complete selected vote/count/sponsorship tables. |
| `data/processed/native-text-ar-20261022-v3` | 1,991 source metadata contexts, 149 complete PDFs / 298 reader alternatives, every reader page, raw exchanges and exact identity/session observations. |
| `data/processed/recovered-platform-graph-inputs-20261022-v2` | Additive Kentucky Republican caucus native text and literal 2024 heading/link spans; not a replacement for the v1 collection packet. |
| `data/processed/platform-graph-inputs-caucus-followup-20261022-v2` | Closed two-exchange caucus capture, preflight, raw bytes and generic challenge-literal stop evidence. |

Read-only verification of the two recovered analytical-input packets:

```bash
.venv/bin/python -I -B -m state_politics.platforms.graph_inputs \
  --out data/processed/recovered-platform-graph-inputs-20261022-v1 --verify-only
.venv/bin/python -I -B -m state_politics.analysis.cycle_outcome_evidence \
  --verify-packet data/processed/cycle-outcome-evidence-20261022-v2
```

An offline rebuild of the calendar action packet uses `--source-dir data/processed`,
`--cohort-dir data/processed/study-abstract-evidence-2023-2024-v3` and a **new**
`--out-dir`. Its original v3 calendar cohort is unchanged by metadata v4.
Recorded stages use all retained action dates, including before/after the
calendar window, under the existing highest-stage precedence; they are not
final chronological/legal outcomes or a party comparison. The original values
behind 104 corrected missing-versus-unclassified action labels remain retained.

Offline Arkansas projection can be repeated without any network:

```bash
.venv/bin/python -I -B -m state_politics.bills.native_text project \
  --raw data/raw/native-text-ar-20261022-v1 \
  --source data/processed/native-inventory-ar-complete-v3 \
  --metadata data/processed/study-abstract-evidence-2023-2024-v3 \
  --out data/processed/native-text-ar-NEW-UNUSED
```

Do not restart either closed collector. Arkansas's operator-selected 150-exchange
batch is exhausted; Kentucky's unused allowance is permanently closed after its
generic literal stop. No access restriction was removed. The native packet
archives the exact pre-update tracker and reviewed session crosswalk.
Printed identity/session evidence does not certify original/filing-time versions,
adoption, analytical labels or any new dates.

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
  --out-dir data/processed/study-native-overlap-2023-2024-v15
```

The registry pins **29 packets across 27 states**, retaining earlier accepted
scopes while adding the common partial/campaign indexes, MT date observations
and the 149 captured Arkansas PDF contexts.
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

The current v15 manifest is
`7443e4fe0c0079f2ac4d58161e555e33999418dcd03ebeeedf09822d53b188b7`.
It indexes **120,000 raw contexts / 128,784 alternative views**, including
17,275 source-only contexts and 102,514 unique canonical bills with native
contexts. The separate bill aggregate prevents physical-reference inflation
while retaining every raw context. Conflicting native dates remain null with
an explicit conflict status; they are never resolved by earliest/latest.
Its 54,117 introduction-observed missing-text contexts reflect wider
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
  --matrix-dir data/processed/study-native-overlap-2023-2024-v15 \
  --out-dir data/processed/study-filing-2023-2024-v5
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
reconcile exactly. Current v5 manifest:
`ea2a13427e9d0860de5d2a829c0afc8afae1fc24ddfb8ab415e0f4849a1e73c3`.
It consumes native v15, preserving the original filing ledger/actions while
updating native fields. V4 remains preserved with manifest
`9be1ee10f4269774646a0e117e04873ed2914004f0e46df3652ff97072c31ce0`.
V3 remains preserved with manifest
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
  --filing-dir data/processed/study-filing-2023-2024-v5 \
  --native-dir data/processed/study-native-overlap-2023-2024-v15 \
  --description-dir data/processed/study-description-evidence-2023-2024-v1 \
  --out-dir data/processed/study-abstract-evidence-2023-2024-v4
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

Current v4 manifest:
`725663244d667bf5d639d33780bcbbf8994c5d52ea9c701d1ff0bddeb04d6f27`.
Exact source fields, full strings/input hashes and all 50 prior matrix rows
reconcile to original extraction and upstream evidence.
V1 remains unchanged with manifest
`931a2ce0bcdb0a7ed328dc966cd21a3a14ff2c77cd561c5208d25753792f1150`.
V2 remains preserved with manifest
`69af46267bdc8c6ce4adb02a1bf4ec6ab1c06eee897f75af4efd38fd7611616b`:
its metadata-view and abstract artifacts were byte-identical to v1.
V3 adds 1,640 MT date candidates; v4 updates native-presence/status fields and
lineage for the Arkansas recovery without changing resolved dates or inclusion.
Complete metadata-view and abstract
artifacts remain byte-identical to v3, whose manifest is
`38bf92a35831fe6ca75003f16caf2fce3354f48f54208bbf11a2b09d79b76c9d`.
It consumes the manifest-declared canonical native-bill
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
Training and fixed evaluation completed. All six epochs visited every one
of the 808 units exactly once, the encoder changed, all 65 native training
units participated and the restored complete long unit had six exposures.
Losses were 2.47722595, 1.28487319, .44146607, .13042140, .05887739 and
.02038712. Training manifest:
`2660bca48e99a27058724d3a1e0113e3492c6ef48a974b2acbde729fe131d127`.

Evaluation output is
`data/processed/cycle-reviewed-only-evaluation-20261021-v1/`, manifest
`6c2c589bc867620bf37b065c0390c343d3cfb5a198d19726310a7f7656e95319`.
All 22 manifest-bound evaluation files, archived producers, original label
bytes, frozen plan and default provisional-loader refusal were verified.
At confidence .8, margin .2 and temperature 1, decision accuracy was
62.11% on metadata 190, 72.22% on native agreed 36, 75% on platform 52 and
56% on dev 50. Native precision was 18/19 = 94.74%, at 19/36 coverage;
eight additional decisions were correct abstentions. Relative to the
mixed full-document model, higher native precision costs coverage and
does not improve native, metadata or platform decision accuracy.

External removal, exposure and class loss change jointly; do not claim a
causal source effect. All references already informed development.
Original labels, reference texts, thresholds and scientific/publication
gates remain unchanged. The checkpoint remains provisional; no promotion
or additional tuning on these diagnostics is planned.

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
`ny-2023-2024`, `il-103rd` and `tx-88r-retained` scope contracts, requiring an explicit compatible
`--native-evidence`. It preserves complete text for exact canonical matches
outside the metadata candidate cohort. Native session/proof selectors do not
infer dates. Source-only/wrong-session contexts are never assigned aliases,
and candidate views are excluded to prevent double counting.

New York contributes 46,776 views / 23,388 references and canonical IDs;
Illinois 5,189 views / references / IDs. These 51,965 additional views are
**publisher-session-bound source evidence, not new eligible-cycle measures**.
V7 additionally exposes 84 retained Texas views / 60 IDs through the
literal 88R-to-88 crosswalk: total additional views are 52,049. Primary
candidate-native views remain unchanged. All 419 older source exports are
byte-identical; no new Texas HTTP or filing-date inference occurred.
Original candidate-native views remain 39,576 across 27,444 candidate IDs.
All extra fields, date dispositions, reader alternatives and false approvals
survive, and other states/sessions remain unknown rather than zero.

## Shared bounded source recovery and all-state catalog

`state_politics.bills.native_inventory` separates explicitly authorized,
paced physical capture from offline declarative replay. Closed packets
must not be resumed merely because a numerical allowance remains.
Robots/redirect/error/retry exchanges count, original bodies/headers
survive, and historical usage remains unknown. Default missing-policy
handling remains conservative; a specifically authorized opt-in covers
404/410 only under RFC 9309 section 2.3.1.3. It does not authorize access
or bypass actual Disallow, auth, rate, TLS or challenge restrictions.

Replay already retained final LA/RI evidence without any HTTP:

```bash
.venv/bin/python -I -B -m state_politics.bills.native_inventory replay \
  --raw data/raw/native-inventory-la-ri-completion-v1 \
  --config conf/native_inventory_la_complete.yml \
  --baseline data/processed/bill-document-reference-inventory-v4 \
  --out data/processed/native-inventory-la-ri-REPLAY-UNUSED
```

Its actual final manifest is
`717ead624f3272b680c32fe8a54b57d5a9fcf424185300dc65e8365f986a8cfb`.
All 37 LA query groups and six complete publisher selector scopes were
independently replayed; 5,300 observations contain 3,996 identities,
including 1,304 ACT-subset repetitions. RI's actual bill-status origin
disallows robots; target data remains unrecovered. Seven accepted LA
pages were reused byte-identically. No original policy body was fetched.

Full finite-page/type aggregation also has a reusable offline producer,
not a private per-state report patch:

```bash
.venv/bin/python -I -B -m state_politics.bills.native_inventory_aggregate \
  --base-packet data/processed/native-inventory-ar-complete-v1 \
  --raw-projection-manifest data/raw/native-inventory-ar-complete-projection-v1/manifest.json \
  --capture-manifest data/raw/native-inventory-ar-complete-v1/manifest.json \
  --contract conf/native_inventory_ar_aggregate.yml \
  --out data/processed/native-inventory-ar-aggregate-REPLAY-UNUSED
```

The actual production AR v3 manifest is
`c3723323c437c1835cf40392d75e57a30c50257f08c62fa8ec069fd85864fc44`.
Its 1,991 identities / 119 pages / 29 type groups preserve original
single-page diagnostic failures while proving the complete declared
queries through exact source edges and narrowly bound aliases. Parent
production replay reproduces all 25 artifacts. No HTTP or source
certification occurs in aggregation.

One registry then selects the effective source packet per state, avoiding
double counting of superseded prefixes without deleting their evidence:

```bash
.venv/bin/python -I -B -m state_politics.bills.study_inventory \
  --registry conf/study_inventory_packets.yml \
  --metadata data/processed/study-abstract-evidence-2023-2024-v3 \
  --tracker docs/STATE_PROGRESS.md \
  --out data/processed/native-inventory-catalog-REPLAY-UNUSED
```

The actual catalog `data/processed/native-inventory-catalog-2023-2024-v2/`
has manifest
`2029d93fc3fe65b56c18017be4843d0fc93fd777875cc3eb586d6b45d8a81700`.
It exports 50 state rows and 11,711 complete original source observations
with 10,357 native identity observations; 1,354 repetitions remain
explicit. HI's 39,499 filenames are separate reference candidates, not
extra measures or originals. All selected original processed/raw files,
headers, metadata, source-only records and capture exceptions are copied
unchanged under `packets/`, with complete paths/hashes in the manifest.
Parent verification receipt:
`data/processed/native-inventory-catalog-parent-verification-20261021-v2.json`,
SHA-256 `fe200a927276b6bc33568c911b7e396747322a4ad77daded105519fb2cf1d675`.

Unregistered states in this particular channel are unknown, not zero
activity; existing accepted native-text packets remain separate.
No new policy originals, actual filing dates or introduced universes
are claimed. The historical NH discovery redirect's 161 missing bytes
remain a declared exception; do not label the entire transport archive
complete. Data/source permissions and all scientific gates remain
unchanged. Source/model/generated bytes are local and Git-ignored;
pushing code/manifests in documentation is not a backup of those bytes.

## Separate verified publisher-session comparison

```bash
.venv/bin/python -I -B -m state_politics.analysis.prepare_session_cohort \
  --metadata data/processed/study-abstract-evidence-2023-2024-v3 \
  --native data/processed/study-native-overlap-2023-2024-v14 \
  --preview data/preview-cycle-evidence-v7 \
  --scope ny-2023-2024 --scope il-103rd --scope tx-88r-retained \
  --out data/processed/verified-session-comparison-2023-2024-REPLAY
```

Outputs must not exist. The actual v3 has 49,450 full member records and
metadata views, 15,854 calendar overlaps, 33,596 session-only members,
65,322 complete native views, 8,486 members lacking retained text and
67 preserved negative contexts. Each member retains original canonical
bill fields, every abstract and the complete unchanged source-date CSV
record, including dates outside the calendar window. No date is inferred.
Physical native references are not counted as extra bills.

Manifest:
`25114b926fdb74d6947c67839da216e6e9b59620e61ff792652396d8242c1dc1`.
Independent complete-field/native-byte receipt:
`data/processed/session-comparison-parent-verification-20261021-v3.json`,
SHA-256 `6605102a548f004fd461347329147a460347c95cc7e81e7ad290623df52f08dd`.
The 47 other states remain unsupplied/unknown for this particular frame;
the original 157,598 calendar candidates and all scientific gates are unchanged.

## Model-blind human annotation and one local workspace

The actual fresh frozen source is
`data/labels/cycle-native-human-review-frozen-20261021-v1/`.
Its source manifest is
`fde2ca1af51f2d505d11cef31af281fd0be761d2710e9573a97bc81345e8b570`.
The complete recruitment packet has 28 chosen inputs and 52 alternatives,
14 selected states and all 50 accounted for. Known training/inspected
source/group/text reservations were supplied before selection, including
all native and metadata quarantines. No model was consulted or human
decision fabricated. This is a bounded recruitment packet, not a
population-accuracy reference.

```bash
.venv/bin/python -I -B -m state_politics.analysis.human_review build \
  --frozen data/labels/cycle-native-human-review-frozen-20261021-v1 \
  --output data/human-review-native-REPLAY

.venv/bin/python -I -B scripts/serve_research.py \
  --review data/human-review-native-20261021-v3 \
  --port 8766
```

Open the printed loopback address. Review-only serving omits prediction links
and returns 404 for all other research mounts. This reduces accidental exposure;
it does not certify reviewer identity or independence. Reviewers must not inspect
topic graphs or the classification inspector before completing annotations.
Keep this process separate from the combined research workspace documented
above; other bundles are not prerequisites for annotation.

The server checks complete artifact
hashes at startup and changed-file fingerprints before serving, permits
only manifest-listed paths and binds only 127.0.0.1. It does not expose the
repository or all of `data/`, create symlinks/copies, publish or load models.
Graph, topic and classification bundles may be explicitly mounted from
`outputs/`; other bundle kinds must remain under `data/`. Only their
manifest-listed files are served, never the surrounding directory.
Human packet manifest:
`a1fa21d6842f34ebc6bebb8ea51261abce1448b757dfa116bc5157823b7df457`.

Reviewers use pseudonymous IDs and must explicitly select each decision,
provide exact evidence/rationale and attest complete reading. Full original
inputs are available separately from clearly named annotation-only exports.
Draft recovery is browser/origin-local, not a backup or identity check.
After a real reviewer exports a file:

```bash
.venv/bin/python -I -B -m state_politics.analysis.human_review validate \
  --packet data/human-review-native-20261021-v3 \
  --annotations ANNOTATIONS_ONLY_JSON
.venv/bin/python -I -B -m state_politics.analysis.human_review import \
  --packet data/human-review-native-20261021-v3 \
  --annotations ANNOTATIONS_ONLY_JSON --output data/human-review-import-UNIQUE
.venv/bin/python -I -B -m state_politics.analysis.human_review compare \
  --packet data/human-review-native-20261021-v3 \
  --annotations REVIEW_A_JSON --review-b REVIEW_B_JSON \
  --output data/human-review-comparison-UNIQUE.json
```

These commands preserve original source and annotation bytes, reject
changed/missing/duplicate/foreign records and retain both disputed reviews.
Human provenance is explicitly self-attested; neither UI attestations,
different pseudonyms nor agreement certify identity, independence or gold.
No imported packet automatically enters training/evaluation or changes
provisional-loader refusal. No real annotations currently exist.

The subsequent classifier-validation step is also implemented, using the
existing evaluator rather than rewriting human reviewers as assistants or
duplicating metrics. The actual pre-annotation plan is
`data/human-review-evaluation-plan-20261021-v1/`, SHA-256
`9d5bdf784c97e21b7ead18be9389bbe00e8b7f6e15d38c17910214b74bf4725f`.
It fixes exactly the two existing models and .8 confidence/.2 margin/
temperature 1, complete-window inference, resolved two-rater agreements
as primary and separate full-rater sensitivities. It retains 41 artifacts
and binds the original weights without copying them. All five runtime
source files and both original checkpoints are checked for drift.

To independently freeze a new plan before any real annotations:

```bash
.venv/bin/python -I -B -m state_politics.analysis.human_review freeze-evaluation-plan \
  --packet data/human-review-native-20261021-v3 --raters 2 \
  --model mixed_full_document data/models/modernbert-native-document-curriculum-20261021-v1 \
    data/labels/cycle-native-document-curriculum-20261021-v1/labels.jsonl \
  --model reviewed_only data/models/modernbert-reviewed-only-20261021-v1 \
    data/labels/cycle-reviewed-only-experiment-20261021-v1/labels.jsonl \
  --output data/human-review-evaluation-plan-NEW-UNUSED
```

**Only after complete real annotations**, export challenge-only advisory
references against the already frozen actual plan:

```bash
.venv/bin/python -I -B -m state_politics.analysis.human_review export-references \
  --plan data/human-review-evaluation-plan-20261021-v1 \
  --annotations REAL_REVIEW_A_JSON --review-b REAL_REVIEW_B_JSON \
  --output data/human-evaluation-references-UNIQUE
.venv/bin/python -I -B -m state_politics.analysis.modernbert \
  --inputs data/human-evaluation-references-UNIQUE/primary-advisory-evaluation-references.jsonl \
  --out data/human-evaluation-mixed-primary-predictions-UNIQUE.jsonl \
  --topics data/human-review-evaluation-plan-20261021-v1/packet/complete-inputs/topics.yml \
  --split challenge --checkpoint data/models/modernbert-native-document-curriculum-20261021-v1 \
  --allow-provisional
.venv/bin/python -I -B -m state_politics.analysis.human_review score-references \
  --references data/human-evaluation-references-UNIQUE \
  --model-alias mixed_full_document --role primary \
  --predictions data/human-evaluation-mixed-primary-predictions-UNIQUE.jsonl \
  --output data/human-evaluation-mixed-primary-advisory-report-UNIQUE.json
```

Apply the same predeclared policy to `reviewed_only` and both
`sensitivity_review_a_all` / `sensitivity_review_b_all` roles, preserving
their separate input/reference files. An empty agreed primary cannot be
replaced with a fabricated score. The loader rejects converting these
references into training rows. Actual human inputs remain unannotated and
unpredicted; the only executed end-to-end scoring proof uses explicitly
synthetic references/logits and is not classifier validation.

## Unpublished cycle-evidence explorer

```bash
.venv/bin/python -I -B scripts/build_site.py \
  --cycle-evidence \
  --bill-evidence data/processed/study-abstract-evidence-2023-2024-v4 \
  --platform-evidence data/processed/platform-study-evidence-2023-2024-v5 \
  --native-evidence data/processed/study-native-overlap-2023-2024-v15 \
  --metadata-token-plan data/processed/study-metadata-token-plan-2023-2024-v2 \
  --snapshot-text data/processed/retained-dump-gap-recovery-20261022-v1 \
  --research-corpus data/processed/research-corpus-text-20261022-v4 \
  --archive-text data/processed/independent-archive-text-20261022-v2 \
  --archive-text data/processed/lawatlas-text-evidence-20261022-v1 \
  --archive-text data/processed/maryland-archive-text-20261022-v1 \
  --archive-text data/processed/nj-library-text-20261023-v5 \
  --archive-text data/processed/nj-library-collection-text-full-20261023-v1 \
  --archive-text data/processed/ok-retained-context-text-20261023-v2 \
  --archive-text data/processed/billcam-hi-retained-html-full-20261023-v1 \
  --archive-text data/processed/billcam-hi-retained-html-delta-20261023-v1 \
  --archive-text data/processed/billcam-four-subject-html-20261023-v1 \
  --archive-text data/processed/billcam-wrapped-heading-html-20261023-v1 \
  --archive-text data/processed/govbot-exact-original-documents-20261023-v2 \
  --archive-text data/processed/published-ai-corpus-documents-20261023-v2 \
  --archive-text data/processed/billcam-action-bound-html-delta-20261023-v1 \
  --archive-text data/processed/billcam-action-bound-html-four-subject-20261023-v1 \
  --archive-text data/processed/billcam-prestop-public-documents-html-20261023-v1 \
  --archive-text data/processed/published-carryover-documents-20261023-v1 \
  --archive-text data/processed/billcam-provider-context-html-delta-20261023-v1 \
  --archive-text data/processed/billcam-provider-context-html-four-subject-20261023-v1 \
  --receipt-evidence data/processed/maine-source-receipt-evidence-2023-2024-v1 \
  --native-session-scope ny-2023-2024 --native-session-scope il-103rd \
  --native-session-scope tx-88r-retained \
  --out data/preview-cycle-evidence-REPLAY
```

The accepted displayed build is `data/preview-cycle-evidence-v31/`; reproduction requires
a fresh output directory. It adds all eighteen archival packets to metadata v4 /
native v15 and research-corpus v4, with the unchanged
platform evidence v5 and token-plan v2. The latter is reusable because the
complete 159,315-view metadata input Parquet is byte-identical to v3.
CLI defaults remain the earlier metadata v3 / native v14 selection; custom
metadata does not silently attach optional bundles. Pass the compatible
explicit directories above.
The current **783-artifact** manifest is
`4c335b69b0a99ba9c05b0f9eb158f4dedc33daceb23ddb607cb55996a714623a`.
Actual v15 inference is bound to this build. Thirty-five complete action-proven
provider-context views supplement the preceding source set without modifying any old row.
Current workspace proof is
`data/provider-context-browser-workspace-20261023-v1/receipt.json`: 321 exact
complete bodies including all 266 carryover proofs, fifteen full-state queries, nineteen byte-identical
downloads, fourteen SVGs, desktop/mobile, no JS/external errors, all helpers
exited.

The preceding **779-artifact v30** manifest is
`c199a54c230be8c3329e25073ba2a3d473706d1a550db14c948c3050eb570aea`.
Actual v14 inference remains bound to that unchanged build. Its two new
published views and 286-body browser proof remain preserved:
`data/published-context-browser-workspace-20261023-v1/receipt.json`.

The preceding **777-artifact v29** manifest is
`8aa1de9ab592a4e8569c77f9806c1d0dc31e17e338d1b0c262dcb26e8c331b2d`.
Actual v13 inference remains bound to that unchanged build. Its sixteen
own-2024 views and 284-body browser proof remain preserved:
`data/identity-browser-workspace-20261023-v1/receipt.json`.

The preceding **775-artifact v28** build manifest is
`5997376c9702db82b04d3e5a96badaed3e221e5bd4fe8f9135422ee482263a7f`.
Actual v12 inference is frozen from this build. All complete prior source
views remain unchanged; the two action-bound packets add 229 unique views.
The UI explicitly distinguishes printed 2023 and candidate 2024 using the
full original carryover/introduction-action proof, never an annual alias.
Current workspace proof is
`data/action-bound-browser-workspace-20261023-v1/receipt.json`: 268 exact
complete bodies (all 229 carryover proofs), fifteen full-state queries,
nineteen byte-identical downloads, fourteen source SVGs, desktop/mobile
and zero JavaScript/external-request errors. All helpers exit.

The preserved v27 manifest is
`f1df0481e6a5f11481bb376713cb144fcdb3a64ec2180bdf3afe2ec381944a7d`.
V27 is a verified UI-only successor to v26, the actual frozen v11 model
source: all **770 other exported artifacts are byte-identical**. Only the
browser script changes. Published-corpus rows now use the independent-text
renderer rather than falling through to the platform renderer; complete
policy text, publisher-prologue spans and all original metadata are visible.
No source, model input, prediction, assignment or encoder work changes.
The permanent real-Chromium regression covers literal markup, full text,
original metadata, complete downloads, keyboard, mobile and no-JS behavior.
UI-only proof: `data/cross-state-ui-only-replay-20261023-v1.json`.
Preceding real-Chromium workspace proof:
`data/cross-state-browser-workspace-20261023-v2/receipt.json`. It checks
39 complete new-source body streams, fifteen full-state queries, nineteen
complete byte-identical downloads, all fourteen source SVGs and
desktop/mobile layouts. The separate helper-cleanup receipt confirms all
processes exited; no JavaScript exceptions or external source requests
occur. The failed v1 attempt is retained as a diagnostic, not a successful
check. The permanent published-corpus browser fixture independently passes.
The output includes all 50 state coverage rows / 100 organization rows,
complete metadata/platform texts, lazy state partitions, full-text gzip
downloads and `downloads/build_manifest.json`. The earlier v11 build manifest is
`0a04fa86cdac4895c4e3148df03fa34b6afe84c45d78720b49793f1c190660d1`.
The preserved v14 manifest is
`f9ae658b13b0ba76d20c60fd9d023e0bf1415d4a6b5a4ab9950896e58cac3e60`;
528 older non-code source exports remain byte-identical. V14 additionally
exposes all 2,315 complete research-corpus views and restored original metadata,
without changing candidate admission or metadata token plans.
The preserved v15 manifest is
`cca5cd91d57bae8ac6f5ce84a2c7110a9a45014f998f18956ebc5bd6eacb984b`:
742 bound outputs and all 7,875 new archive views, including all alternatives.
All 632 non-code exports from v14 remain byte-identical. The v10 gallery
manifest is `245d39f6f730f39b379e38f5728d21b06ecd31498238f49f6f83c456cc3b0322`.
The preserved v16 manifest is
`0087426c82a729b7b30b56a8502f80aaf6e2daeeb547a3f9dcf79345622dc965`:
745 bound outputs, including all 1,070 additional Maryland alternatives.
Exactly five existing v15 outputs change: the index, two archived consumers
and the two Maryland archive exports; all other 737 outputs remain identical.
V17 adds the independent library packet without changing metadata, calendar
membership, the token plan or any prior Maryland/NE source view. Existing
New Jersey archive exports retain the earlier views and add all 40 library
alternatives. The source gallery's complete missing-text queue preserves
every original field for its 21,562 remaining contexts.
Its manifest is
`07699c0d0cf37cb3c36533b220d8ca2473d34e08ac30571685ef452f60119809`:
748 bound outputs. The v12 source gallery has 75 bound artifacts; the separate
completed metadata topic gallery remains unchanged.
Receipt/session additions are explicit opt-ins only; the default/custom
metadata behavior does not silently attach them. Build producers are archived
with their exact source hashes. Earlier builds remain preserved. V11 retains
91,923 complete native views and separately exposes 157,598 complete snapshot
records, of which 123,182 have nonempty retained text. These are not extra bills,
introduced-version certification or additional tokenized model inputs.

For interactive use, serve the output with a local static HTTP server:

```bash
.venv/bin/python -I -B -m http.server 8765 \
  --bind 127.0.0.1 --directory data/preview-cycle-evidence-v18
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

The primary candidate channel exports 39,576 complete native text views /
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

By default it prints JSON with computed results, input hashes and random seeds
to stdout, with the check summary on stderr. It does not update the historical
`data/processed/reproducibility_report.json`. To save a report, explicitly choose
a fresh destination; existing files and symlinks are refused before checks,
and exclusive creation also protects against another writer creating the path
during the audit. A fresh blocked report is retained before the nonzero exit.
Git-ignore checks query only the named authored inputs, not the entire ignored
data tree.
In CI or after committing, use:

```bash
uv run python scripts/audit_reproducibility.py --require-tracked
# Optional saved report; use a new name for each run:
uv run python scripts/audit_reproducibility.py --require-tracked \
  --report data/legacy-artifact-audit-REPLAY.json
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

## Legacy clean-room rebuild order

This is the historical broad pipeline, not the current pinned 2023-2024
workflow. Do not run these acquisition/rebuild steps under the current storage
pause or against closed source campaigns. The explicit legacy opt-in below
does not waive those boundaries.

```bash
make setup
make historical
make registry
make platforms            # includes OCR-only official documents
make caucus-priorities
make legislators
make bills-dump
make all ALLOW_LEGACY_ANALYSIS=1
make test lint audit
```

The network-heavy steps are explicit because they access third-party services. Derived data is
gitignored; the code, curated inputs, source registries, citations, lockfile and tests are the
reproducible research package.

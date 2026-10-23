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

## Recreated graph bundle

```bash
.venv/bin/python -I -B scripts/recreate_graphs.py \
  --research-corpus data/processed/research-corpus-text-20261022-v4 \
  --archive-text data/processed/independent-archive-text-20261022-v2 \
  --archive-text data/processed/lawatlas-text-evidence-20261022-v1 \
  --archive-text data/processed/maryland-archive-text-20261022-v1 \
  --archive-text data/processed/nj-library-text-20261023-v5 \
  --out-dir outputs/recreated-2023-2024-REPLAY
```

The accepted local build is `outputs/recreated-2023-2024-v14/index.html`.
The command above requires a fresh output directory. The bundle contains 14
current evidence graphs in PNG and SVG, 13 complete chart-data CSVs, eleven complete
research-packet ZIPs and a hash manifest. It also archives the exact eight
plotting/source-consumer producers and the recovered producers within their research packets.
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

The newest offline pass adds **7,004 existing contexts / 7,875 complete views**,
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
  --preview data/preview-cycle-evidence-v18 \
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
  --evidence data/preview-cycle-evidence-v18 \
  --sessions data/processed/verified-session-comparison-2023-2024-v3 \
  --review data/human-review-native-20261021-v3 \
  --sources data/processed/native-inventory-catalog-2023-2024-v2 \
  --graphs outputs/recreated-2023-2024-v14 \
  --topics outputs/topic-input-comparison-2023-2024-v1 \
  --port 8765
```

Open the printed loopback address. The server checks complete artifact
hashes at startup and changed-file fingerprints before serving, permits
only manifest-listed paths and binds only 127.0.0.1. It does not expose the
repository or all of `data/`, create symlinks/copies, publish or load models.
Use `--topics outputs/topic-inference-retained-text-2023-2024-v2` instead
to mount the three full-body topic graphs; the comparison mount preserves
both complete original tier downloads. Blind reviewers must not inspect either.
The optional graph mount serves its exact manifest-listed ZIP/CSV/Parquet/image
artifacts under `/graphs/`; no other bundle may be mounted from `outputs/`.
The optional `/topics/` mount contains provisional model predictions; independent
human reviewers must not inspect it before completing their annotations.
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
  --receipt-evidence data/processed/maine-source-receipt-evidence-2023-2024-v1 \
  --native-session-scope ny-2023-2024 --native-session-scope il-103rd \
  --native-session-scope tx-88r-retained \
  --out data/preview-cycle-evidence-REPLAY
```

The accepted build is `data/preview-cycle-evidence-v18/`; reproduction requires
a fresh output directory. It adds all four independent archives to metadata v4 /
native v15 and research-corpus v4, with the unchanged
platform evidence v5 and token-plan v2. The latter is reusable because the
complete 159,315-view metadata input Parquet is byte-identical to v3.
CLI defaults remain the earlier metadata v3 / native v14 selection; custom
metadata does not silently attach optional bundles. Pass the compatible
explicit directories above.
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

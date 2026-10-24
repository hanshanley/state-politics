# State Politics

**What are the 50 state Democratic and Republican party organizations emphasizing?**

This project studies policy attention through state party platforms and legislative
bills, using a shared topic taxonomy. Platforms describe stated priorities; bills
describe individual sponsors' filed agendas, not necessarily party positions.
Topic attention measures neither policy agreement nor legislative achievement.

## Status

The active study covers **2023–2024 calendar filing/introduction candidates and
platforms applicable during that cycle**. Existing later-session prefilings keep
their original dates, IDs and session labels. Wider historical/current-cycle
collections are retained separately, not silently pooled into the study.

Research is in progress. A supervised ModernBERT-base classifier candidate exists,
but remains provisional and has not been independently certified. Source
completeness and filing-time party attribution remain unresolved; existing figures
and analytical claims are legacy results, not revalidated findings.

See the [50-state progress tracker](docs/STATE_PROGRESS.md) for completed source
cohorts and remaining work, and the [research status](docs/AUDIT_STATUS.md) for evidence.

The retained dump exposes **123,182 nonempty snapshot-text records**. Additional
printed-header joins recover **2,079 previously missing contexts** from independent
research text. Independent archived bill records now add **7,004 more contexts**,
mostly New Jersey; a further **563 Maryland contexts** and **14 contexts from
independent library compilations** formed the preceding source baseline.
A full library-collection pass adds **97 contexts / 255 reader views**;
strict retained-document relations add **2,000 Oklahoma contexts**, preserving
their distinct original annual sessions and exact source pointers. Independently
published Hawaii HTML adds **399 contexts / 832 full views / 9,370,186 body
characters**. All 426 original-context leads in the three bounded subject queries
were processed. Four further complete catalogues recover **415 contexts / 619
views**; fixing a real wrapped-heading parser defect recovers **one further
context / two views**, entirely offline. Two further independent publications
recover **30 original contexts across fourteen states / 179 complete supplied
views / 10,117,496 policy characters**. A real enrolled-resolution header/terminal
page defect is fixed without rewriting the earlier packet or dropping pages.
All earlier source packets and negative dispositions remain reproducible;
conflicting captions and provider years are not silently admitted or repaired.
A further offline pass binds actual original carryover and origin-introduction
actions to **213 Hawaii contexts / 229 unique complete views / 1,827,636 characters**.
The actual printed 2023 headings and original 2024 contexts remain distinct;
no year, date or URL alias is repaired or inferred. Nine repeated historical
source occurrences are preserved but not counted twice.
A further finite public-identity pass adds **15 original 2024 Hawaii contexts /
16 complete views**. Search stops at an explicit login requirement; only public
document links already returned before that stop are followed, without cookies,
login, alternate search routes or native requests.
Two more original Hawaii contexts now have **two complete published views /
7,722 policy characters**, linked by their own original carryover actions.
Context-qualified view IDs preserve the earlier source identity rather than
merging the printed 2023 and original 2024 sessions.
A separate explicit action-bound projection of retained provider-declared 2023
records recovers **20 further original contexts / 35 full views / 396,533
characters**, without rewriting provider sessions or making new requests.
Two original-action-qualified New Jersey library packets recover **16 more
contexts / 42 complete reader views / 2,000,505 policy characters**. Exact
original introduction evidence supports January 2024 tail-session covers;
bounded reprints and extraction-spacing fixes preserve all uncertain source
alternatives, original dates and contradictory session-end metadata.
Two further independently replayed packets add **22 contexts / 61 complete
views / 1,144,522 characters** using complete single-page and literal printed-
variant evidence. Unproven prefiling/session variants remain quarantined, and
source-scoped codification/whitespace proofs retain the original source strings.
Two independently replayed Bill Commons packets now add **46 original Delaware/
Nevada contexts / 112 complete views / 6,353,892 characters**. Exact original
version references and own formal bodies preserve forty Nevada prefilings;
six Delaware contexts retain both full extraction alternatives. Fiscal notes,
amendment instructions and account notices are not bill-body substitutes.
Complete source records, negative dispositions and national reference tables
remain available without repairing dates or provider session labels.
Five further Virginia contexts retain **five complete views / 58,325 characters**.
Their own 2024 editions link to unchanged 2025-labelled contexts through exact
original origin-filing IDs and final continued-to-2025 actions, not a session alias.
Combined source availability is **139,317 of 157,598 existing candidate contexts**,
with **18,281 remaining gaps**. These are not certified unique-legislation or
filing-cohort counts. Complete alternative views and
original source metadata are retained. Source versions, archive extraction,
research-corpus cleaning and classifications remain uncertified.
The local graph bundle includes complete research downloads and an explicit
remaining-text queue; see the [recovery commands](docs/REPRODUCIBILITY.md#independent-archived-bill-text).

Completed provisional topic inference yields
**89,950 assignments / 67,648 abstentions**; retained bodies yield
**65,091 assignments / 74,226 abstentions / 18,281 unavailable bodies**
across **178,745 full source alternatives**.
The newest five Virginia contexts yield two provisional assignments and three
abstentions; uncertainty is not replaced with forced labels.
All **157,593 other complete assignment rows** and all 178,740 preceding view
predictions remain unchanged. The actual run encodes only the five new strings,
covering 12,028 tokens / fifteen windows without discarded tokens or repeated
old encoder inputs. No model or threshold changes.
Local graphs and complete research downloads are in
`outputs/recreated-2023-2024-v30/`,
`outputs/topic-inference-retained-text-2023-2024-v17/` and
`outputs/topic-input-comparison-2023-2024-v15/`.
The unpublished full-text explorer is `data/preview-cycle-evidence-v35/`.
The source gallery and explorer now contain all twenty-five archives and the
latest five-context recovery. Completed full-text inference v19, independent
saved-token/logit/consensus replay and the paired-input comparison use those
same actual sources; metadata inference is unchanged.
The tracked `scripts/audit_cycle_topics.py` independently replays the saved
whole-source decisions and complete downloads offline without an encoder;
see the [current-snapshot audit command](docs/REPRODUCIBILITY.md#current-snapshot-replay-versus-the-historical-analysis-audit).
The paired-input comparison preserves missingness and abstentions; differences
between inputs are not accuracy measurements. These remain model assignments,
not validated policy findings or party positions; see the
[inference contract](docs/REPRODUCIBILITY.md#provisional-population-topic-inference).

Twenty-one model-blind GPT-6.1 Sol reviews cover **109 selected Delaware/Hawaii/
NJ/Nevada/Virginia contexts / 255 complete source views**, with 604 exact evidence
spans verified. Thirty-three assigned topics match advisory proposals; four
assigned topics differ, 68 model abstentions have proposals, three contexts
remain unresolved in both and one model assignment has no advisory consensus.
All 74 triage flags request independent adjudication, not automatic correction.
These are selected-cohort diagnostics, **not independent human
accuracy or replacement labels**. The complete local casebook and full-source
download are in `outputs/assistant-advisory-topic-review-2023-2024-v7/`;
see the [review contract](docs/REPRODUCIBILITY.md#assistant-advisory-semantic-review).

## Setup

Requires Python 3.11+ and uv. From the repository root:

```bash
make setup  # install dependencies, including model and OCR extras
make help   # list collection, analysis and checking commands
```

Setup alone does not recover the required data or model checkpoints. `make all`
is an analysis-and-figures entry point, not a currently verified end-to-end rebuild;
network-heavy collection stages must be run explicitly. See the
[reproducibility guide](docs/REPRODUCIBILITY.md) before running the pipeline.

## Documentation

- [Methods](docs/METHODS.md) — sources, topic classification and comparison limits.
- [Code guide](docs/CODE_GUIDE.md) — pipeline components and their inputs and outputs.
- [Citations](CITATIONS.md) — source attribution and dataset licensing.

Project metadata declares an MIT code license; underlying sources retain their
respective terms.

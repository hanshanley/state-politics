# Code guide

This guide accompanies every Python file in `src/`, `scripts/`, and `tests/`. It explains what
each file owns, its inputs/outputs, and where it sits in the reproducible pipeline. The
repository audit fails when a Python file is added without an entry here.

## Package and infrastructure

| File | Responsibility |
|---|---|
| `src/state_politics/__init__.py` | Package version and public package metadata. |
| `src/state_politics/provenance.py` | Fetches network resources, blocks SSRF/private addresses, follows checked redirects, hashes content, and appends immutable JSONL provenance records. |
| `src/state_politics/compute.py` | Selects the available model execution device and enforces the no-hosted-inference dependency rule. |
| `src/state_politics/caucuses.py` | Collects the four explicitly separate legislative-caucus priority sources into `caucus_priorities.parquet`; never labels them party platforms. |

## Platform collection

| File | Responsibility |
|---|---|
| `src/state_politics/platforms/__init__.py` | Platform subpackage marker. |
| `src/state_politics/platforms/dataverse.py` | Downloads and reconciles the Harvard Dataverse historical platform corpus, treating the update archive as authoritative. |
| `src/state_politics/platforms/registry.py` | Builds the 100-organization official website registry from Wikidata candidates plus homepage verification and explicit overrides. |
| `src/state_politics/platforms/discover.py` | Discovers candidate platform/resolution URLs from Wayback CDX and live homepages, scores candidates, and records search outcomes. |
| `src/state_politics/platforms/collect.py` | Fetches candidates, extracts HTML/PDF text, repairs broken ligatures, rejects false positives, confirms state attribution, deduplicates documents, and writes the modern corpus/gap report. |
| `src/state_politics/platforms/official_documents.py` | Deterministically rebuilds the NY-D Issuu page-image archive and LA-R scanned Wix PDFs with fixed source IDs, source hashes, OCR configuration, and Tesseract version. |

## Bill collection

| File | Responsibility |
|---|---|
| `src/state_politics/bills/__init__.py` | Bill subpackage marker. |
| `src/state_politics/bills/openstates_dump.py` | Streams selected tables from the Open States PostgreSQL custom dump through `pg_restore` without restoring a database. |
| `src/state_politics/bills/people.py` | Downloads current legislators and normalizes party labels, including fusion-voting ballot lines. |
| `src/state_politics/bills/ingest.py` | Builds bill and sponsorship parquet files, resolves sponsor parties, parses PostgreSQL arrays, and validates filing/session years. |
| `src/state_politics/bills/outcomes.py` | Streams action/vote tables, resolves historical chambers and date-aware voter party, and adds explicit recorded-stage fields to bills. |

## Analysis

| File | Responsibility |
|---|---|
| `src/state_politics/analysis/__init__.py` | Analysis subpackage marker. |
| `src/state_politics/analysis/taxonomy.py` | Defines the CAP topic schema, segments platforms into planks, and implements keyword/embedding classifiers with bounded-memory inference. |
| `src/state_politics/analysis/gold_sample.py` | Creates the deterministic sampling frame and seeded unlabeled template used for new human-labeling rounds. |
| `src/state_politics/analysis/validate.py` | Scores keyword and embedding classifiers against the fixed 50-plank human-labelled gold snapshot. |
| `src/state_politics/analysis/emphasis.py` | Classifies platform planks, clusters redundant collected/cross-corpus documents, and computes equal-state matched-party topic shares plus pooled sensitivity outputs. |
| `src/state_politics/analysis/revealed.py` | Classifies bills state-by-state, excludes drafting placeholders/pre-2018 leakage, reports coverage, and computes equal-state matched headline shares plus pooled sensitivity. |
| `src/state_politics/analysis/validate_bills.py` | Validates bill-title topics against legislative-staff subject tags and independently replicates headline shares from tags. |
| `src/state_politics/analysis/profiles.py` | Produces era-matched state summaries and leave-one-out outlier rankings gated by sample floors and multinomial null simulations. |
| `src/state_politics/analysis/intraparty.py` | Measures within-party dispersion, within-vs-between coherence, divisive topics, centroid distance, and permutation significance. |
| `src/state_politics/analysis/state_focus.py` | Builds the 100-row state × party atlas with leave-one-out baselines, 500-bill reliability floors, classification coverage and curated caucus units. |
| `src/state_politics/analysis/elections.py` | Detects election/voting bills, validates the title rule against subject tags, and measures same-party state concentration. |
| `src/state_politics/analysis/terms.py` | Computes TF-IDF and literal same-party log2 term concentration against peers of the same party and evidence genre; peer-absent terms are categorical. |
| `src/state_politics/analysis/trends.py` | Computes equal-state 2018–2019 vs 2024–2025 bill-topic change, paired sign-flip inference, FDR correction and supported state slopes. |
| `src/state_politics/analysis/outcomes.py` | Computes recorded chamber-passage/later-stage and enactment rates, chamber summaries, paired-state tests, and passage-vote party support. |
| `src/state_politics/analysis/coverage.py` | Produces a machine-readable account of supported, partial, limited, and unsupported analytical questions from current artifact schemas. |
| `src/state_politics/analysis/diffusion.py` | Detects exact/near-duplicate bill-title clusters without dropping observed candidate blocks and reports cohesion and ceremonial status. |

## Plotting library

| File | Responsibility |
|---|---|
| `src/state_politics/plotting/__init__.py` | Exposes shared plotting helpers. |
| `src/state_politics/plotting/theme.py` | Defines the shared palette, typography, source-note measurement, and reusable figure styling. |
| `src/state_politics/plotting/charts.py` | Provides figure, axes, line, marker, dumbbell, unreliable-row, and save/layout primitives. |

## Command-line scripts

| File | Responsibility |
|---|---|
| `scripts/sample_gold_planks.py` | Thin CLI wrapper around `analysis.gold_sample`; writes a seeded unlabeled template and never overwrites the fixed gold snapshot. |
| `scripts/audit_reproducibility.py` | Validates manual-input hashes, sources, seeds, producers, OCR rows, artifact relationships, state coverage, formulas, and public documentation. |
| `scripts/report_figures.py` | Recomputes and prints every canonical number quoted in public documentation/figures. |
| `scripts/plot_platform_coverage.py` | Plots historical corpus recency by state and party. |
| `scripts/plot_platform_gap.py` | Plots modern organization coverage and explicit gap statuses. |
| `scripts/plot_party_emphasis.py` | Plots Democratic vs Republican platform-topic shares. |
| `scripts/plot_stated_vs_revealed.py` | Plots platform-vs-bill shares, with independently contradicted rows marked rather than hidden. |
| `scripts/plot_intraparty.py` | Plots within-party versus between-party agenda distance. |
| `scripts/plot_state_agenda_coverage.py` | Shows 46 party-committee states plus four separately labelled caucus-supplement states. |
| `scripts/plot_state_focus.py` | Plots state bill agendas most unlike same-party peers. |
| `scripts/plot_all_state_focus.py` | Produces separate 50-state Democratic and Republican topic-share heatmaps with top-three labels and explicit missingness. |
| `scripts/plot_election_focus.py` | Plots election/voting bill concentration among sufficiently large state caucuses. |
| `scripts/plot_bill_trends.py` | Plots FDR-significant filing changes with explicit staff-tag agreement or reversal labels. |
| `scripts/plot_outcomes.py` | Plots explicit action-based passage/later-stage and enactment rates plus sponsor/voter-party roll-call support. |

## Tests and what they assert

| File | Assertion scope |
|---|---|
| `tests/test_provenance.py` | Fetch records, hashes, capped streaming, SSRF encodings, safe domains, and append-only logs. |
| `tests/test_dataverse.py` | Dataverse archive selection, AppleDouble exclusion, metadata and coverage. |
| `tests/test_registry.py` | 100 unique organizations, website resolution, party confirmation and overrides. |
| `tests/test_discover.py` | Candidate scoring, URL exclusions, Wayback status, aliases and deep retries. |
| `tests/test_collect.py` | Text extraction, OCR/ligature repair, platform confirmation, state attribution, false-positive rejection, gap findings and linear-time markup stripping. |
| `tests/test_people.py` | Legislator parsing and party/fusion-label normalization. |
| `tests/test_bills.py` | Dump parsing, party attribution, date sanity, PostgreSQL arrays and state filtering. |
| `tests/test_taxonomy.py` | Topic loading, plank segmentation, threshold behavior, chunked inference equivalence and keyword normalization. |
| `tests/test_emphasis.py` | Gold snapshot existence/coverage, emphasis denominators and classifier score handling. |
| `tests/test_validate_bills.py` | Subject-tag normalization, no-guess conflict handling, precision/recall and tag replication. |
| `tests/test_diffusion.py` | Title normalization, duplicate-index safety, clustering, transitive cohesion and ceremonial flags. |
| `tests/test_intraparty.py` | Cosine behavior, common-state composition, coherence, permutation null/power and centroid/topic spread. |
| `tests/test_state_focus.py` | Curated caucus units, committee precedence, leave-one-out baselines, all 100 rows and Nebraska's nonpartisan status. |
| `tests/test_elections.py` | Election subtypes, false-positive terms, leave-one-out shares and subject-tag validation. |
| `tests/test_terms.py` | State-party document construction, committee precedence, peer-absent handling and literal numeric log2 ratios. |
| `tests/test_trends.py` | Early/late shares, slope direction, BH correction and state-year observation floors. |
| `tests/test_outcomes.py` | Historical chamber resolution, date-aware voter party, recorded-stage precedence, outcome floors, and roll-call aggregation. |
| `tests/test_coverage.py` | Capability report distinguishes supported, partial, limited, and unavailable analytical questions. |
| `tests/test_caucuses.py` | Curated source collection, failure recording, institutional separation and 50-state coverage plot invariants. |
| `tests/test_plotting.py` | Portfolio palette, measured source-note layout, top-label spacing, shared panel order/count, and contradicted-row styling. |
| `tests/test_reproducibility.py` | Manifest hashes, trusted hosts, source-hash failure paths, deterministic sampling, OCR row replacement and full audit success. |
| `tests/test_no_hosted_llm.py` | Source tree contains no hosted inference clients/endpoints. |

## Maintenance rule

When adding a `.py` file under `src/`, `scripts/`, or `tests/`, add its exact repository-relative
path to this guide. `make audit` enforces this rule.

# Analytical depth and data requirements

This document distinguishes analyses the repository supports from questions the processed data
cannot answer. It is generated as structured data by:

```bash
uv run python -m state_politics.analysis.coverage
```

The machine-readable outputs are:

- `data/processed/analysis_capabilities.json`
- `data/processed/analysis_capabilities.csv`

## Supported analyses

### Stated and revealed agenda

- 233 party-committee platforms/resolutions dated 2018+ across 80 organizations
- 16 older fallback documents, kept for provenance but excluded from current comparisons
- four separately labelled caucus priority sources completing state-level stated coverage
- 1,087,327 bills and 5,000,761 sponsorship records
- topic shares with validation, thresholded unclassified rows, and independent tag replication

### State and within-party analysis

- 100 state × party atlas rows
- leave-one-state-out same-party baselines
- reliable stated comparisons only at 30+ classified units
- 98 partisan bill profiles; Nebraska explicitly marked formally nonpartisan
- same-party and opposite-party topic-profile similarity
- permutation test for party dispersion differences

### Specific issue and language lenses

- election/voting title detector validated against legislative subject tags
- separate subtypes for voting administration, campaign finance, redistricting, candidate rules
  and election security
- TF-IDF plus literal same-party log2 concentration
- peer-absent terms reported categorically rather than with pseudo-ratios
- exact and near-duplicate/model-legislation clusters with cohesion

### Longitudinal analysis

`analysis/trends.py` compares equal-state 2018–2019 shares with 2024–2025 shares. The partial
2026 year remains in the raw artifact but is excluded from trend inference. It reports:

- early and late counts/shares
- percentage-point change
- state-balanced paired changes with a 100-bill floor in both periods
- deterministic paired sign-flip permutation tests rather than bill-level pseudo-replication
- Benjamini-Hochberg q-values across party-topic tests
- yearly linear slope
- state-party topic slopes only when at least five years meet a 50-classified-bill floor

## Partially supported

- Party-committee stated comparisons are reliable for the rows clearing the 30-unit floor; small
  statements remain descriptive only.
- Legislative-staff subject-tag validation covers 37 states because 13 publish no source tags.
- Platform history is uneven across organizations and years, so current cross-state comparisons
  are stronger than platform time-series claims.
- Topic attention does not identify whether an organization supports or opposes policy within
  that topic.

## Not supported by current processed data

### Enactment or success rates

`bills.parquet` does not retain actions, status, result, or enactment fields. The project measures
what legislators file, not what passes.

### Roll-call voting behavior

No votes table is retained by the current ingest.

### Chamber-specific historical agenda

Bills are not linked to a historical chamber field in the processed artifact. Current
legislator chamber data cannot reconstruct the chamber of every historical sponsor safely.

These are explicit data requirements, not analyses inferred from titles. Supporting them would
require extending the Open States dump ingest to retain actions/results, votes, and chamber
relationships, followed by separate validation.

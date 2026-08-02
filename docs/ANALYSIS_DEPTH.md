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

- 502 current party-committee platforms/resolutions across 81 organizations
- 185 older fallback documents, kept for provenance but excluded from current comparisons
- four separately labelled caucus priority sources completing state-level stated coverage
- 1,087,327 bills and 5,000,761 sponsorship records
- topic shares with validation, thresholded unclassified rows, and independent tag replication

### State and within-party analysis

- 100 state × party atlas rows
- leave-one-state-out same-party baselines
- reliable stated comparisons only at 30+ classified units
- reliable filed-focus comparisons only at 500+ classified bills and above a
  sample-size-specific multinomial null threshold
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
- a second trend calculation using legislative-staff subject tags, with failed directional
  replications retained rather than hidden

### Recorded outcomes and roll calls

- 8,954,085 explicit bill actions and 869,001 bill-linked vote events
- historical originating/action/vote chamber resolved from organization hierarchies
- action-based chamber-passage/later-stage and enactment definitions, never inferred from titles
- state-party estimates gated at 500 law-eligible bills and 80% action coverage
- equal-state party summaries and paired-state sign-flip inference
- date-aware voter-party resolution for passage-roll-call support

## Partially supported

- Party-committee stated comparisons are reliable for the rows clearing the 30-unit floor; small
  statements remain descriptive only.
- Legislative-staff subject-tag validation covers 37 states because 13 publish no source tags.
- Platform history is uneven across organizations and years, so current cross-state comparisons
  are stronger than platform time-series claims.
- Person-level roll-call data cover 49 states; Missouri has vote events but no resolved
  person-vote rows.
- Vote results identify support for particular motions, not the policy direction or ideological
  meaning of every bill.

## Not supported as causal claims

The project can now describe recorded passage/later stages, enactment, chambers and roll calls.
It still
cannot attribute those differences causally to party. Majority control, agenda access, bill mix,
institutional rules and selection into roll-call votes are not randomized or fully modeled.
Topic attention also does not identify support/opposition within the topic.

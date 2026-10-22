# State Politics

**What are the 50 state Democratic and Republican party organizations emphasizing?**

This project studies policy attention through state party platforms and legislative
bills, using a shared topic taxonomy. Platforms describe stated priorities; bills
describe individual sponsors' filed agendas, not necessarily party positions.
Topic attention measures neither policy agreement nor legislative achievement.

## Status

The active study covers **2023–2024 bills and platforms applicable during that
cycle**. Older and 2025–2026 evidence is retained separately, not required for
completion or silently pooled into the study.

Research is in progress. A supervised ModernBERT-base classifier candidate exists,
but remains provisional and has not been independently certified. Source
completeness and filing-time party attribution remain unresolved; existing figures
and analytical claims are legacy results, not revalidated findings.

See the [50-state progress tracker](docs/STATE_PROGRESS.md) for completed source
cohorts and remaining work, and the [research status](docs/AUDIT_STATUS.md) for evidence.

The retained dump exposes **123,182 nonempty snapshot-text records**. Additional
printed-header joins recover **2,079 previously missing contexts** from independent
research text. Independent archived bill records now add **7,004 more contexts**,
mostly New Jersey; combined availability is **135,459 of 157,598 existing calendar
candidates**, with **22,139 remaining gaps**. Complete alternative views and
original source metadata are retained. Source versions, archive extraction,
research-corpus cleaning and classifications remain uncertified.
The local graph bundle includes complete research downloads and an explicit
remaining-text queue; see the [recovery commands](docs/REPRODUCIBILITY.md#independent-archived-bill-text).

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

<div align="center">
  <h1>State Politics</h1>
  <p>
    <a href="#overview">Overview</a> ·
    <a href="#explore-the-evidence">Evidence</a> ·
    <a href="#setup">Setup</a> ·
    <a href="docs/METHODS.md">Methods</a>
  </p>
</div>

---

## Overview

What do state parties emphasize, and what do legislators file?

This project studies policy attention in Democratic and Republican state-party
platforms and legislative bills during **2023–2024**, using a shared topic
taxonomy. Platforms describe stated priorities; sponsored bills describe
individual legislators' agendas, not necessarily party positions. Topic shares
do not measure policy agreement, ideology or legislative achievement.

**Research is in progress.** The working snapshot contains 157,598 candidate
contexts, with 18,281 still missing body text. Source completeness, filing-time
party attribution and independent classifier validation remain unresolved.
The research companion is local-only; nothing has been integrated into
themarginoferror.com.

## Explore the evidence

**Sources and coverage:** the [50-state tracker](docs/STATE_PROGRESS.md) records
completed source scopes and remaining gaps. The
[recovery guide](docs/REPRODUCIBILITY.md#independent-archived-bill-text)
documents retained texts, source alternatives and provenance.

**Classifications:** the
[per-bill inspector](docs/REPRODUCIBILITY.md#per-bill-classification-evidence-inspector)
compares original and majority decisions alongside complete source texts,
window votes and all topic/rejection scores.
[Full-score diagnostics](docs/REPRODUCIBILITY.md#full-score-diagnostics-without-new-classifications)
keep information that a single assigned label would hide.

**Graphs and comparisons:** the
[graph bundles](docs/REPRODUCIBILITY.md#recreated-graph-bundle) include complete
chart data and research downloads.
[Majority voting](docs/REPRODUCIBILITY.md#strict-majority-bill-topic-candidate)
and [longer-context experiments](docs/REPRODUCIBILITY.md#longer-context-and-cross-input-experiments)
remain separate, explicitly provisional alternatives.

## Working with the charts

Generated figures, the classification inspector and full research downloads
live under `outputs/`; source bundles and model checkpoints live under `data/`.
These are local, Git-ignored artifacts, not data supplied by cloning the code.
The [reproducibility guide](docs/REPRODUCIBILITY.md) provides the current build
and local-workspace commands.

The inspector downloads every matching complete context, source input and
prediction, not just the visible page. Missing text, abstentions and source
disagreements remain explicit. Retained legacy figures are not revalidated
findings; see the [audit status](docs/AUDIT_STATUS.md).

## Setup

Requires Python 3.11+ and uv. From the repository root:

```bash
make setup
make help
```

Setup installs dependencies; it does not recover source data or trained weights.
Follow the reproducibility guide before running collection or rebuilding analyses.

## Data integrity

Classification uses a locally fine-tuned ModernBERT-base model with explicit
abstention. Scores are uncalibrated, and assistant reviews are not independent
human gold. The frozen baseline and majority candidate are preserved separately;
more assignments do not establish better accuracy.

See [Methods](docs/METHODS.md) for analytical definitions,
the [code guide](docs/CODE_GUIDE.md) for pipeline components, and
[Citations](CITATIONS.md) for source attribution and licensing.

Project metadata declares an MIT code license; underlying sources retain their
respective terms.

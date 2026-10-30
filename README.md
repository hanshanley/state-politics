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
contexts, with 17,729 still missing body text. Source completeness, filing-time
party attribution and independent classifier validation remain unresolved.
The research companion is local-only; nothing has been integrated into
themarginoferror.com.

For what is working and what is still missing, see
[Project status and gaps](docs/PROJECT_STATUS.md).

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
The [retained-text training-exposure census](docs/REPRODUCIBILITY.md#population-training-exposure-census)
finds 65 exact training-input matches and 610 training-seen bill identities.
Population predictions and unmatched rows are not independent validation.
A [saved-prediction sensitivity check](docs/REPRODUCIBILITY.md#saved-label-exposure-sensitivity)
finds national topic-share changes of at most 0.0111 percentage points.
That is not a state-level bound: the
[complete state sensitivity check](docs/REPRODUCIBILITY.md#state-local-exposure-sensitivity)
finds changes up to 1.79 points under unanimity and 4.55 under majority in
Pennsylvania's 56-to-44-context diagnostic subset. Neither estimates accuracy.

**Graphs and comparisons:** the
[current collection](outputs/README.md) has **27 regenerated charts** with
Substack and The Margin of Error backgrounds, 300-dpi PNGs, editable SVGs and
[complete chart tables](outputs/chart-data/). Browse
[`outputs/substack/`](outputs/substack/) or
[`outputs/themarginoferror/`](outputs/themarginoferror/).
[Original research bundles](docs/REPRODUCIBILITY.md#recreated-graph-bundle)
retain the full source evidence.
[Majority voting](docs/REPRODUCIBILITY.md#strict-majority-bill-topic-candidate)
and [longer-context experiments](docs/REPRODUCIBILITY.md#longer-context-and-cross-input-experiments)
remain separate, explicitly provisional alternatives.

## Working with the charts

Open `outputs/index.html` locally for the current chart gallery. Its categorized
exports and complete chart CSVs are tracked; the thirteen old root-level PNGs
are preserved legacy references, not the current collection.

The classification inspector and full original research downloads remain
local, Git-ignored artifacts under `outputs/`. Source bundles and model
checkpoints live under `data/`; cloning the code does not supply them.
The [reproducibility guide](docs/REPRODUCIBILITY.md) provides the current build
and local-workspace commands.

`make audit-current` verifies pinned saved bytes and current handoff references
without rebuilding;
success is not scientific validation or publication approval.
Broad legacy `all`, `analysis` and `legacy-figures` targets refuse to run unless
explicitly opted into with `ALLOW_LEGACY_ANALYSIS=1`; use the current workflow instead.

With the saved inspector bundle present, start it independently:

```bash
.venv/bin/python -I -B scripts/serve_research.py \
  --classifications outputs/classification-inspector-2023-2024-v9
```

Open the printed loopback address. Other research bundles are not required.

Where supported, choose a destination first to stream complete query records
directly to disk rather than assemble a query-sized Blob. Other browsers retain
the complete-file download; cancellation or failure never substitutes metadata.

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

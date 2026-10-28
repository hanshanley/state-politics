# What this project does, and what is missing

**Status: unfinished research, with working data tools and regenerated charts.**
Updated October 28, 2026. A working interface or a completed engineering task
does not mean the underlying political analysis has been validated.

The fresh full audit passes **2,469 code tests** and integrity-checks every
artifact in the six current research bundles. It also finds **12 lint
violations** and **34 failed legacy artifact checks, covering 28 distinct
missing paths**. The duplicate artifact-test assertion was run as the separate
audit rather than allowed to overwrite the historical report. These engineering
results do not resolve the scientific gaps below.

## What the project is trying to answer

State Politics asks what Democratic and Republican state-party organizations
emphasize, and how those stated priorities compare with the subjects of
legislative measures filed during **2023-2024**.

The intended population covers all 50 states and 100 major-party organizations.
The project preserves actual legislative sessions, filing/introduction evidence,
source versions, resolutions and other measure types. A candidate context is
not necessarily an independently verified introduced bill.

The comparison is about **policy attention**, not agreement, ideology,
legislative achievement or proof that a legislator speaks for their party.
Nebraska's nonpartisan legislature must not be forced into a D/R comparison.

## What is already working

- Source recovery, provenance and explicit missing-text accounting, with
  original texts, alternative versions, extraction readers and unknowns retained.
- A locally fine-tuned ModernBERT-base topic classifier, with complete-input
  windowing, one primary topic or abstention, and retained topic/rejection scores.
  The original unanimity rule and provisional majority alternative remain separate.
- A local classification inspector showing complete texts, source alternatives,
  scores and window decisions. Downloads include every matching complete record,
  not just the visible page or metadata.
- A model-blind human-review interface and a frozen, still-unannotated review
  packet. Building the interface is not the same as obtaining human judgments.
- **27 current research charts / 108 PNG and editable-SVG exports / 35 complete
  CSV tables**, with matching Substack and The Margin of Error backgrounds.
- Source-identity, date/party-resolution, abstention, missingness and export
  safeguards, plus versioned diagnostics and reproducibility checks.

The current chart gallery is [`outputs/index.html`](../outputs/index.html).
The thirteen older root PNGs are preserved legacy references, not revalidated
findings. Large source/model/inspector bundles are local and Git-ignored:
cloning the repository does not recover them.

## What data is still missing

The observed study cohort has **157,598 candidate legislative contexts**:

| Body-text availability | Contexts |
|---|---:|
| At least one retained body | 139,869 |
| No retained body | **17,729** |

This accounts for the retained candidate cohort. It does **not** prove that the
cohort includes every official measure in every state/session, or that every
available body is the original introduced version.

There is a separate **cohort/date-eligibility gap**, not included in the 17,729
missing-body count. All 50 states are accounted for in the exports, but only
49 have eligible contexts in the frozen primary cohort. Maine has **zero**;
Massachusetts has **one**, Pennsylvania **56** and New York **860**. These are
selected cohort counts, not actual state legislative volumes. Unresolved
filing/introduction evidence and differences between calendar and native-session
populations must be reconciled before broad state comparisons. Do not repair
this by inventing dates or silently changing the study population.

The largest remaining body-text gaps are:

| State | Missing contexts |
|---|---:|
| Hawaii | 5,717 |
| New Jersey | 1,600 |
| Oklahoma | 1,335 |
| Nebraska | 1,256 |
| Connecticut | 1,096 |
| West Virginia | 956 |
| Michigan | 828 |
| Virginia | 771 |
| Other 30 states with observed gaps | 4,170 |
| **Total** | **17,729** |

See the [complete 50-state text-coverage table](../outputs/chart-data/evidence/retained_text_coverage.csv)
and [state completion tracker](STATE_PROGRESS.md). A zero gap count in this
subset is not certification of a state's complete official universe.
Failed or restricted sources must remain explicit, not become zero activity.

## What is missing beyond body text

| Area | Remaining work and consequence |
|---|---|
| Official source universes | Reconcile remaining native state/session/type/chamber populations. A complete extraction of one provider is not proof of complete official coverage. No state is certified complete end to end. |
| Filing-time text | Establish which source version actually represents the filing/introduction being studied. Snapshot, amended and enacted texts must stay distinguished; an enacted law cannot be relabelled introduced text. |
| Operative party platforms | Establish the actual documents applicable during 2023-2024 for all 100 organizations. Their operative/applicability statuses remain unresolved. Historical texts, later platforms, short statements and caucus agendas are not interchangeable. This does not mean all platform text is absent. |
| Historical party attribution | Recover or substantiate party membership at the relevant event date. Predominantly undated memberships cannot justify copying current affiliations backward. Unsupported D/R comparisons must be withheld. |
| Independent human reference labels | Obtain genuine independent review and resolve disagreements. The frozen packet contains 28 selected inputs, not completed human gold or a representative national test. Assistant reviews cannot substitute for independent truth. |
| Taxonomy and classifier validation | Resolve rubric boundaries and label provenance, then evaluate on untouched target-domain evidence with predeclared accuracy/precision, coverage, uncertainty and subgroup gates. Existing scores are uncalibrated; more assigned labels do not establish better accuracy. |
| Final analytical results | Recompute only supported comparisons from eligible sources, defensible attribution and validated classifications. Current research graphics inspect evidence and model sensitivity; old party/platform findings and historical analytical PNGs are not certified. |
| Unified reproducibility | The canonical artifact manifest still describes the legacy 2018+ pipeline and MiniLM-era outputs. Current 2023-2024 bundles have separate manifests and checks; that is not one completed end-to-end certified-study rebuild. Missing legacy artifacts and the 12 current lint diagnostics remain visible in the audit. |
| Preservation and redistribution | Establish durable backup/restore for ignored source/model bundles and review source-specific redistribution rights. A successful code push does not back up those bundles or authorize their publication; same-volume copy-on-write clones are not a disaster-recovery backup. |
| Report and publication | Finish the report and claim-by-claim evidence review, then obtain explicit publication approval. The local companion is not integrated into themarginoferror.com. |

## Why the classifications are still provisional

The original rule assigns **65,306** contexts and abstains on **74,563**;
another **17,729** have no body text.

The separate majority candidate assigns **78,522**, rejects **23,816**,
leaves **37,528** uncertain and **three** excluded, with the same **17,729**
unavailable. The additional assignments are a sensitivity result, not a measured
accuracy improvement.

Actual model training and full-text inference have been performed. What is
missing is defensible independent target-domain validation and approval to
promote those research outputs into substantive findings. Examined assistant
diagnostics and falling training loss do not supply that validation.

## What completion would require

1. A defensible study population, source-version ledger and explicit disposition
   for remaining source gaps, together with operative-platform and party evidence.
2. Independently reviewed labels, an adjudicated rubric and a frozen held-out
   evaluation that satisfies declared classifier and analytical release gates.
3. Reproducible, source-linked analyses and figures, with unsupported claims
   removed or qualified and residual missingness visible.
4. A reviewed report, preserved research artifacts, appropriate rights and a
   separate publication decision before website integration.

Residual gaps may remain if they are accounted for and the affected claims are
withheld or appropriately limited. Completion must not be manufactured by
inventing text, dates, party labels, human judgments or approval.

For fresh audit results and historical failures, see [Audit status](AUDIT_STATUS.md).
For commands and artifact pins, see [Reproducibility](REPRODUCIBILITY.md).
[`TASKS.md`](../TASKS.md) is the engineering work ledger, not proof of scientific
completion.

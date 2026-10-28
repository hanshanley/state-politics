# State Politics: purpose, missing data and missing analyses

**Status: unfinished research, with working data tools and regenerated charts.**
Updated October 28, 2026. A working interface or a completed engineering task
does not mean the underlying political analysis has been validated.

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

The intended end product is a source-linked report and local explorer comparing
eligible party-platform priorities with eligible legislative topic profiles.
The project is not yet a completed national comparison or a published website.

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

Actions, vote events/counts, sponsorships and organization/membership records
have also been retained. Their presence does not establish complete 2023-2024
coverage, correct event-time party joins, comparable motions or final outcomes.
The gap is not simply that all these kinds of data are absent.

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
| Unified reproducibility | The canonical artifact manifest still describes the legacy 2018+ pipeline and MiniLM-era outputs. Current bundles now have a [shared read-only integrity check](REPRODUCIBILITY.md#current-saved-research-integrity-check), but byte integrity is not one completed end-to-end certified-study rebuild. Missing legacy artifacts remain unresolved. The audit's 12 lint violations have since been repaired while preserving original producer compatibility. |
| Preservation and redistribution | Establish durable backup/restore for ignored source/model bundles and review source-specific redistribution rights. A successful code push does not back up those bundles or authorize their publication; same-volume copy-on-write clones are not a disaster-recovery backup. |
| Report and publication | Finish the report and claim-by-claim evidence review, then obtain explicit publication approval. The local companion is not integrated into themarginoferror.com. |

## What analyses are still missing

Much of the analytical code exists. What is missing is the **qualified,
regenerated and validated result**, not necessarily another Python module.
Current source-coverage and classifier-diagnostic charts do not substitute for
the substantive comparisons below.

### Work needed for the main stated-versus-filed comparison

| Analysis | What exists | What still needs to be done |
|---|---|---|
| Cohort coverage and selection bias | State/session inventories, date-evidence ledgers, a missing-text queue and coverage charts. | Reconcile official versus observed populations; explain calendar/session differences, excluded or undated records and uneven source availability. Determine which states and measure types can actually be compared. |
| Target-domain classifier performance | Fine-tuned ModernBERT, full-text predictions, abstentions, score exports and assistant-reviewed development diagnostics. | Obtain independent references; assess bill and plank accuracy, per-topic precision/recall, coverage, calibration and uncertainty on untouched target evidence. Report extraction/input-tier and state differences where support permits. Do not select thresholds on the final test. |
| Stated party priorities | Platform/caucus recovery and topic-emphasis methods. | Select genuinely operative 2023-2024 party documents, verify coherent policy units and labels, and justify document/plank weighting. Keep party committees, caucuses and supplemental statements separate. |
| Filed legislative priorities | Retained measures, body-text classifications and party/state/chamber aggregation methods. | Bind eligible filing-time versions and historical sponsor affiliations; distinguish bills from resolutions and other types. Recompute profiles with missing texts, unknown parties and abstentions visible in denominators. |
| Matched stated-versus-filed differences | Comparison, state-focus and reporting code; legacy comparison artifacts are not certified. | Build a defensible same-state/party/period matched sample, regenerate topic-share differences and disclose unmatched cases. Distinguish pooled volume from equal-state summaries, and withhold unsupported D/R claims. |
| Robustness and uncertainty of the main findings | Input-tier, unanimity/majority and longer-context diagnostics; existing paired-state inference and multiple-testing methods. | Test whether any substantive finding survives source/version choices, abstention rules, measure mix, state inclusion and weighting. Quantify uncertainty at the relevant unit without interpreting uncalibrated model scores as validated error bars. |

### Additional analyses that are not ready as findings

These are conditional extensions if included in the eventual report, not a
requirement to restore every legacy result or expand the study beyond 2023-2024.

| Analysis family | Existing pieces | Missing data or analytical qualification |
|---|---|---|
| Within-party state differences, focus and outliers | State-party atlas, profile similarity, intraparty comparisons and outlier methods. | Comparable operative sources, reliable dated party/topic profiles, adequate support and uncertainty/sensitivity checks. A legacy sample-size floor does not certify reliability. |
| Chamber-specific agendas | Originating-chamber fields and aggregation methods. | Consistent chamber/session/type eligibility and dated affiliations. Do not treat different chamber mixes as party effects. |
| Election and voting legislation | Title-based election detectors and focus calculations. | Review substantive inclusion using complete text, measure detector errors and rebuild on eligible attributed records. Title hits are candidates, not verified election-policy measures. |
| Policy wording and distinctive language | Term-frequency/concentration and highlight methods. | Comparable full policy units and corpora; checks for legal boilerplate, quotations, source/extraction artifacts and changing document mix before interpreting terms as priorities. |
| Cross-state reuse or diffusion | Exact/near-duplicate title candidate clusters. | Verify actual text similarity, identities and chronology. Shared titles do not prove shared policy text, coordination or model-law authorship. |
| Recorded outcomes and enactment | Action histories, stage classification and outcome methods; provisional pooled recorded-stage graphics. | Verify law-eligible populations, passage/veto/override chronology, follow-up and censoring. Missing actions are unknown, not failure; a latest recorded stage is not necessarily a final outcome. |
| Roll-call party behavior | Vote events/counts, party-count records and voting-summary methods. | Resolve party at the vote date, exact motion/chamber meaning, voter denominators and roll-call coverage. A procedural yes vote is not automatically substantive support for the bill. |
| Changes over time | Date fields and legacy trend methods. | Demonstrate comparable observations within the chosen window and separate observed zeros from missing periods. Longer historical trends are outside the current completion requirement; do not infer change from unmatched snapshots. |
| Source-tag replication | Source subjects and a topic crosswalk. | Establish tag provenance and ambiguity, account for state-specific coverage and compare matched populations. Tag agreement is not independent human accuracy or automatically legislative-staff gold. |
| Policy stance or ideology | Topic labels and retained vote records, but no validated stance measure. | A separate substantive coding/validation design would be needed. Topic frequency alone cannot answer whether parties support or oppose the same policy; this is not supplied by the existing classifier. |

The [analytical capability inventory](ANALYSIS_DEPTH.md) and
[code guide](CODE_GUIDE.md) document implemented methods. Their existence, and
the existence of legacy numerical outputs, do not establish current analytical
support.

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

## What the engineering checks establish

The October 28 full offline code run passed **2,469 tests**. The underlying
legacy artifact audit was run separately with a fresh report, rather than via
the assertion that would overwrite the historical report: **34 checks failed,
covering 28 distinct missing paths**. Full Python lint initially found **12
violations**, now repaired with exact prior-producer compatibility and unchanged
parsing functions. Audit reports no longer overwrite saved evidence by default;
explicit reports must be fresh. Broad legacy builds require an opt-in before
any dependencies can run. The audit's ignored-file check is now restricted to
its named authored inputs rather than walking the whole retained research tree.
The later public current-integrity command verified **784 artifact paths across
eight manifests**; its separate 56-test focused run overlaps existing tests and
must not be added to the full-suite count.

These checks establish useful software and saved-byte integrity, not complete
data, validated political findings or permission to publish.

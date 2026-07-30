# state-politics

**What are the 50 state Democratic and Republican party organizations actually emphasizing?**

This project measures the policy priorities of all 100 U.S. state-level party organizations
(50 states × 2 parties) using two complementary evidence streams:

| Stream | What it captures | Actor | Source |
|---|---|---|---|
| **A. Platforms / manifestos** | *Stated* priorities — what the party organization says it wants | State party committee | Harvard Dataverse corpus (1846–2017) + original collection (2018–present) |
| **B. State legislative bills** | *Revealed* priorities — what the party's legislators actually file | Party caucus in the state legislature | Open States / Plural Policy |

Congressional bills are **out of scope**. This is about *state* politics.

---

## Why this project exists

There is no ready-made dataset answering this question for the present day.

The best existing platform corpus — *Select American State Party Platforms, 1846–2017*
(Harvard Dataverse, `doi:10.7910/DVN/KNOSHL`) — is excellent but **stops at 2017**. We verified this by
downloading it and enumerating every file: **2,091 platform documents**, 2,086 unique
`(state, party, year)` observations, **49 states plus national platforms**, **maximum year 2017**.
Coverage is also very uneven (**Maryland is absent entirely**; Kentucky Democrats last appear in
**1943**; New York Democrats in **1958**; Florida Republicans not at all).

> The dataset ships two archives. `platform-update-04212025.zip` **supersedes** `05 for public.zip`;
> the included changelog reconciles exactly (49 files added, 21 removed). Naively unioning the two
> archives inflates the corpus to 4,154 "documents" by resurrecting files the authors deliberately
> deleted and double-counting the rest. This project uses the update archive as authoritative.

So **the 2018–present platform corpus does not exist and this project builds it**, from official state
party websites and the Internet Archive.

The bills side, by contrast, is well served: Open States publishes free, public, current bulk data for
all 50 states.

---

## Core principles

1. **No fabricated or interpolated data.** Every platform document and every bill row traces to a fetched
   URL with an HTTP status, retrieval timestamp, and SHA-256 content hash. If a state party published no
   platform in a cycle, that observation is **omitted** — never imputed, never smoothed, never guessed.
2. **Absence is a finding.** "No platform page exists on the New York Democratic Party's site"
   is a legitimate research result, not a pipeline bug — and every such gap in this project
   carries a directly-probed reason. The gap report is a deliverable.
3. **No hosted LLM APIs. Models run locally.** Every model this project runs — embeddings, classifiers,
   topic models — runs on this machine's Apple Silicon GPU (M4, 16 GB unified memory) via Metal
   Performance Shaders, falling back to CPU. This is enforced in code, not just documented: a test
   scans the entire source tree for hosted-provider imports and inference endpoints and fails the
   build if any appear. See [`src/state_politics/compute.py`](src/state_politics/compute.py).
   The reason is reproducibility — a hosted model is an unversioned dependency, and a result that
   cannot be regenerated from pinned local weights is not reproducible research.
4. **Cite the collector, not the redistributor.** Citations name the organization or authors who
   *collected* the data, not merely the API that served it. See [`CITATIONS.md`](CITATIONS.md).
5. **Reproducible from source.** Nothing in `data/` is committed except the hand-labelled
   validation set (`data/gold/`), which is authored input rather than a derived artifact and
   cannot be regenerated. Everything else is rebuilt by running the pipeline.

---

## Data sources

All sources were fetched and verified live on **2026-07-28**. Full bibliographic citations, with the
collecting organizations credited, are in [`CITATIONS.md`](CITATIONS.md).

| # | Source | Role | Verified |
|---|---|---|---|
| 1 | Hopkins, Coffey, Galvin, Gamm, Henderson, Paddock & Schickler — *Select American State Party Platforms, 1846–2017* (Harvard Dataverse, CC0) | Historical platforms | 2,091 docs, 49 states, 1840–2017 |
| 2 | Open States / Plural Policy — bulk data | State bills, votes, legislators (all 50 states, current) | 2026-07 public dump, 10.7 GB |
| 3 | Open States API v3 | Targeted bill/sponsorship refresh | `Bill.sponsorships`, `Person.party` |
| 4 | Internet Archive — Wayback CDX Server API | Discovery of 2018–present platform documents | Returned real platform docs |
| 5 | Wikidata | Registry of official state party websites | 100/100 resolved, 92 machine-verified, 19 hand-checked corrections |

---

## Project status

Greenfield. Work is organized in phases:

| Phase | Description | Status |
|---|---|---|
| 0 | Scaffolding + provenance layer | ✅ done |
| 1 | Ingest historical platform corpus (1846–2017) | ✅ done |
| 2 | Build verified registry of all 100 state party organizations | ✅ done |
| 3 | Collect 2018–present platforms (the hard part) | ✅ done |
| 4 | Build 50-state bill + sponsor-party pipeline | ✅ done |
| 5 | Define a shared issue taxonomy for both streams | ✅ done |
| 6 | Compute emphasis scores and stated-vs-revealed divergence | ✅ done |
| 7 | Outputs, per-state profiles, reproducible build | ✅ done |
| 8 | Validate the bill classifier against statehouse subject tags | ✅ done |

Full roadmap, including the source-verification work behind it, is in [`docs/PLAN.md`](docs/PLAN.md).

### The 24 parties with no platform

76 of 100 state party organizations yielded a platform. The remaining 24 are the deliverable
that a scraper normally throws away: **every one was probed by hand and carries a recorded
reason**, in [`conf/platform_gaps.yml`](conf/platform_gaps.yml), joined into the gap report by
`gap_report()`. They live in version-controlled config rather than in the generated CSV,
because an explanation written into a derived file is erased by the next run.

| Cause | Orgs | Meaning |
|---|---|---|
| `no_platform_published` | 18 | Site is healthy and simply has no platform document |
| `summary_only` | 3 | A short position blurb (1.3–2.5 KB), not a platform |
| `broken_site` | 1 | Alaska GOP is serving an "Account Suspended" page |
| `not_confirmed` | 1 | Candidates fetched, none read as a platform |
| `client_rendered` | 1 | A real platform page whose text needs a JS runtime |

The distinction matters: **a missing platform is mostly a real finding about the party, not a
failure of the crawler.** Only one org (Hawaii Democrats, a Wix site whose page manifest lists
both `platform` and `platform-old`) has a platform this pipeline cannot reach — and all 37 of
its Wayback snapshots from 2021-10 to 2026-06 are the same empty shell, so the archive cannot
recover it either. Two cases first recorded as JS-rendered turned out on re-checking to be
genuine absences: Florida GOP's `/platform` soft-404s to its home page, and neither its nor the
Louisiana Democrats' own CMS index contains a platform page or media file at all.

Regenerate the report after editing the findings, without re-crawling anything:

```bash
uv run python -m state_politics.platforms.collect --report-only
```

### Stream B: legislators and bills

`state_politics.bills.people` ingests the current legislators for all 50 states from Open
States' **public, no-auth** per-state CSVs. This is the join key for the whole bills stream —
a bill records who sponsored it, and this records which party that sponsor belongs to.

```bash
uv run python -m state_politics.bills.people
```

**Result: 7,359 currently-serving legislators across all 50 states** — 4,045 Republican,
3,240 Democratic, 74 other. Chambers: 5,389 lower, 1,921 upper, 49 `legislature` (Nebraska's
nonpartisan unicameral). Third parties and independents are deliberately kept as `other`
rather than folded into the major two, since misfiling them would misattribute their bills.

One wrinkle worth naming: New York, Connecticut, Vermont and Oregon permit **fusion voting**,
where one candidate is cross-endorsed by several parties and the source records the combined
ballot lines — `Democratic/Working Families`, `Republican/Conservative/Independence`. Read
literally these match no party and fall to `other`, which stranded 119 legislators (most of
the New York legislature's majority among them). A slash-delimited label naming exactly one
major party now resolves to it; a label naming both stays `other`, because nothing in the
string says which side they caucus with.

`state_politics.bills.openstates_dump` + `bills.ingest` extract the bills themselves from
Open States' public PostgreSQL dump.

```bash
# ~8 min to download at 20 MB/s, then ~10 min to extract. Needs pg_restore:
#   brew install libpq     (Homebrew keeps it out of PATH; the module looks there anyway)
uv run python -m state_politics.bills.ingest
```

**Result: 1,087,327 bills filed 2018–2026 across all 50 states, and 5,000,761 sponsorships.**
Party attribution: 436,641 Democratic, 376,436 Republican, 68,529 bipartisan, 205,721 unknown.

Three notes on how this was done, because each was a real obstacle:

* The per-session CSV/JSON archives are **login-gated** (every path under
  `data.openstates.org/csv/` and `/json/` returns HTTP 403) and API v3 needs a key, so the
  public dump is the only complete free route.
* The dump is 10.7 GB and this machine had 32 GB free, so it is **streamed to disk with
  incremental hashing** (`provenance.download_to_file`) rather than buffered, extracted
  selectively, and deleted afterwards — its URL and SHA-256 stay in the provenance log, so it
  is reproducible without keeping 10.7 GB around.
* It is a **PostgreSQL custom-format archive**, not SQL, but it does *not* need a running
  database: `pg_restore` streams one table at a time to stdout, which avoids restoring 10.7 GB
  into a server that would not fit.

**Dating a bill takes two dates, not one.** Open States records when a *session* convened and
when a *bill* first saw action. Filtering on session start alone excluded the entire 2017–2018
biennium: 20 states — New York, Texas, Massachusetts, Illinois and Ohio among them — had no
calendar-2018 bills at all, while California's 2018-convened session stamped "2018" onto bills
actually filed in 2019–20. A session is now admitted when *either* date overlaps the window,
and `session_year` and `first_action_year` are both kept alongside the resolved `year`. That
recovered **42,576 bills** and took the states with 2018 filings from 30 to 49. The fiftieth is
North Dakota, whose legislature meets only in odd-numbered years — a fact about North Dakota,
not a gap.

First-action dates are also *sanity-checked against their own session*, because a few are
corrupt: a Montana bill dated year `202`, a 2019 Michigan resolution dated 1959, a 2023 West
Virginia bill dated 2003. A first action more than two years before its session is not believed
and the session year is used instead. Only 39 rows are affected and no topic share moves, but
`year` is what dates a diffusion cluster, and one 1959 row would report a 2019 model bill as
first appearing sixty years early. Two years of leeway is deliberate: New Hampshire genuinely
files legislative service requests the year before a session opens.

A bill is attributed to a party by its **primary** sponsors. Cosponsor lists are long,
cross-party and procedural, so letting them decide would blur the very distinction the table
exists to draw. Where no primary sponsor resolves to a major party, the attribution falls back
to all sponsors — this decides 5.7% of party-attributed bills — and bills whose sponsors cannot
be resolved at all are `unknown`, never guessed.

---

## What the parties actually emphasize

With both platform corpora in hand, `state_politics.analysis` segments every document into
planks, classifies each against a shared issue taxonomy, and measures **share of planks** —
share rather than count, because platforms differ by an order of magnitude in length and raw
counts would measure verbosity rather than priority.

```bash
uv run python -m state_politics.analysis.validate   # score the classifiers first
uv run python -m state_politics.analysis.emphasis
uv run python scripts/plot_party_emphasis.py
```

The taxonomy (`conf/topics.yml`) is anchored to the **Comparative Agendas Project** major topic
codes rather than invented here, so results are comparable with the wider literature and so the
Open States `subject` tags could be mapped onto the same scheme; that is not implemented —
bills are classified from their titles.

Classification runs **locally on the M4 via MPS** — a pinned sentence-transformer embeds each
plank and each topic description and assigns the nearest topic. A transparent keyword baseline
runs alongside it, not as a fallback but so the model's output can be checked against something
a human can read and argue with.

**Validation, on 36,886 planks from 876 documents (34,396 classified):**

| Classifier | Top-1 | Top-2 |
|---|---|---|
| Keyword baseline | 56% | — |
| Embedding (MPS) | **62%** | **78%** |

Scored against `data/gold/plank_topics_gold.csv` — 50 planks drawn at random (seed 20260729)
from the **2018-present** corpus and hand-labelled by the author. Accuracy is therefore measured
on modern planks; the 1990–2017 era supplies 69% of classified planks and is not sampled. It is small and single-annotator, so it supports claims about
broad aggregate emphasis and not about any individual plank; some planks are genuinely ambiguous
between two defensible topics, which is why top-2 is reported alongside top-1. Chance on this
21-way task is about 5%.

![What Democratic and Republican state parties talk about](outputs/party_emphasis.png)

---

## The headline result: what parties say vs. what they file

With both streams classified into the same taxonomy, the two can finally be compared. This is
what the project was built to do.

```bash
uv run python -m state_politics.analysis.revealed
uv run python scripts/plot_stated_vs_revealed.py
```

![What state parties say, and what they actually file](outputs/stated_vs_revealed.png)

**Both parties talk far more about rights and identity than they legislate, and legislate far
more about crime, transportation and education than they talk about.**

Every row below was re-derived a second time using topic labels written by legislative staff
instead of by this project's model (see [the replication](#checking-the-bill-classifier-against-statehouse-subject-tags)).
The third column is that independent check.

| Topic | D said → filed | R said → filed | Replicates? |
|---|---|---|---|
| Civil rights and liberties | 10.7% → **3.0%** | 12.1% → **2.8%** | ✅ gap is *larger* (1.5% / 0.7%) |
| Immigration | 4.9% → **0.9%** | 6.0% → **0.9%** | ✅ gap is *larger* (0.3% / 0.2%) |
| Culture, family, social issues | 3.0% → **1.8%** | 5.3% → **1.5%** | ✅ (2.6% / 2.4%) |
| Law, crime and justice | 8.9% → **13.8%** | 10.0% → **15.5%** | ✅ (13.8% / 13.5%) |
| Transportation | 2.3% → **4.7%** | 1.4% → **5.2%** | ✅ gap is *larger* (7.0% / 9.7%) |
| Education | 9.3% → **10.3%** | 9.3% → **12.2%** | ✅ gap is *larger* (14.3% / 19.5%) |
| ~~Housing and community development~~ | ~~3.5% → 9.4%~~ | ~~1.7% → 6.0%~~ | ❌ **does not replicate** (3.0% / 0.9%) |

**The housing row does not survive the check and should not be believed.** Tag-labelled bills
put housing at 3.0% for Democrats and 0.9% for Republicans — against stated shares of 3.5% and
1.7%, which erases the gap and reverses its sign for Republicans. The cause is specific and
documented below: the classifier reads a property-tax bill by the thing being taxed rather than
by the tax, so "authorize a property tax freeze for owner-occupied homes" lands in housing.
It is left in the table struck through rather than quietly deleted, because a corrected claim
is more useful than a tidy one.

Both sides are restricted to the same **2018-present** window. An earlier version compared a
1990–2026 platform average against 2018–2026 bills; since 69% of the plank corpus predates 2018,
that understated exactly the topics that have risen since. Matching the windows *widened* every
gap in this table rather than narrowing it.

The pattern is symmetric across both parties, which is what makes it interesting: the topics
that dominate platform rhetoric are largely *national* fights that state legislatures have
limited power over, while the topics that dominate actual filing are the bread-and-butter
business of state government. Immigration is the sharpest case — Republican platforms give it
6.0% of their planks and Republican legislators 0.9% of their bills.

**Read these numbers with their limits.** Bills are classified from *titles*, which are short
and often procedural — a noisier signal than a platform plank. Title classification agrees with
statehouse subject tags 63.2% of the time, close to the 62% the same model scores on planks,
but that agreement is very uneven by topic and the replication above is the reason one row had
to be withdrawn. 18.9% of bills cannot be resolved to a party and are excluded rather than
guessed at. And filing a bill is not passing one: this measures **agenda, not achievement**.

Democratic state parties devote more of their platforms to labour, the environment, housing,
health and social welfare; Republican state parties to government operations, public lands,
taxation, culture and family questions, and law and crime. Planks below a similarity threshold
are recorded as **unclassified** and excluded from the denominator rather than pushed into
whichever topic was least far away — 2,490 of the 36,886 planks fall there.

---

## Checking the bill classifier against statehouse subject tags

The plank classifier is scored against a hand-labelled gold set — but every item in that set is
a platform plank. Bills are classified from titles, which are shorter, more procedural and
written for a different purpose, so the plank accuracy figure does not transfer to them. That
left the *revealed* half of the headline resting on a classifier nobody had measured.

Roughly half of all bills carry `subject` tags applied by the legislature's own staff. Those
tags are a genuinely independent signal — a different labeller, a different process, recorded
before this project existed. `conf/subject_topic_map.yml` maps the unambiguous ones onto the
project's topic scheme, and `analysis/validate_bills.py` compares the two.

```bash
uv run python -m state_politics.analysis.validate_bills
```

The mapping covers **181 tags** out of 88,716 distinct normalised tag strings. That sounds
tiny and is the point: only tags whose policy area is determined by the tag name alone are
included. Procedural tags (`memorials`, `subject index`, `rules`), money tags that say nothing
about the policy being funded (`appropriations`, `bonds`, `fees`), unit-of-government tags
(`counties`, `municipalities`), and genuinely two-topic tags are all excluded — the last group
including tags that name a regulated *commodity* rather than a policy area, since
`alcoholic beverages` covers both liquor licensing and prohibition. Bills whose tags map to two
different topics are dropped rather than scored, because there is no single right answer. The
mapping is written from tag names and the CAP codebook, never from classifier output, and does
not reuse the keyword seeds in `conf/topics.yml` — doing so would test the seeds against
themselves.

**Overall agreement: 63.2% on 46,659 bills across 35 states** — close to the 62% the same model
scores on hand-labelled planks. But the aggregate hides a lot, and the useful measure is
**precision** rather than recall, because every headline number is a *share of bills assigned to
a topic*:

| Topic | Recall | Precision | Chiefly contaminated by |
|---|---|---|---|
| Education | 79.0% | **88.1%** | Macroeconomics |
| Transportation | 61.9% | **79.3%** | Education |
| Health | 76.4% | **74.2%** | Social welfare |
| Law, crime and justice | 70.7% | **71.8%** | Government operations |
| Macroeconomics | **18.1%** | 71.9% | Government operations |
| Housing and community development | 81.6% | **34.8%** | **Macroeconomics** |
| Public lands and water | 68.8% | **31.2%** | Environment |
| Civil rights and liberties | 46.5% | **16.4%** | Law, crime and justice |

One failure mode explains almost all of the damage: **the classifier reads a tax bill by the
thing being taxed rather than by the tax.** Macroeconomics recall is 18.1% — the model finds
fewer than one tax bill in five — and those bills do not vanish, they land in housing (property
tax), public lands (land tax) and social welfare (income-tax credits). That simultaneously
deflates Macroeconomics and inflates whatever the tax was levied on.

### The replication

Because the tags are independent of the model, they can be used to re-derive the headline
outright, replacing the classifier entirely. `bill_emphasis_by_tag.csv` does exactly that over
**111,521 tag-labelled, party-attributed bills**. A row "holds" when both labellings put the
filed share on the same side of the stated share — which is the claim the headline actually
makes.

**33 of 40 topic-party rows hold.** The seven that do not are:

| Topic | Party | Said | Model | Tags |
|---|---|---|---|---|
| Housing and community development | D | 3.5% | 9.4% | 3.0% |
| Housing and community development | R | 1.7% | 6.0% | 0.9% |
| Public lands and water | D | 7.9% | 8.1% | 2.1% |
| Public lands and water | R | 10.6% | 10.7% | 2.8% |
| Macroeconomics | R | 2.7% | 2.2% | 9.9% |
| Government operations | D | 6.3% | 6.1% | 8.3% |
| Science, technology and communications | D | 1.7% | 2.2% | 1.6% |

Every one is the tax failure or its mirror image, except the last two, where the model and the
stated share differ by a fraction of a point and the "sign" of a gap that small is noise.

**This is a subsample replication, not a second census.** Only 35 states publish tags, only
28.2% of tagged bills map unambiguously, and the tags are themselves imperfect — a clerk's tag
can be coarse or wrong. Levels are therefore not comparable to the full-corpus figures; the
direction and rough size of each gap is. Neither labelling is ground truth, which is precisely
why agreement between two independent ones is worth more than either alone.

---

## Model legislation: the same bill in a dozen capitols

State legislatures do not draft in isolation. Advocacy groups circulate template bills, and the
same text surfaces in many capitols in the same session — visible in the data as a title
appearing near-verbatim in states that share nothing but a sponsor's party.

```bash
uv run python -m state_politics.analysis.diffusion
```

Titles are normalised (bill numbers, years and ordinals stripped — exactly what two states
running one template differ on), reduced to content words, and clustered by Jaccard similarity.
Comparing a million titles pairwise is impossible, so candidates are blocked by their **rarest**
content words; blocking on several rather than one matters, because two versions of a template
often differ in precisely which rare word they keep.

**187 clusters spanning 3+ states, 2,027 bills, the widest reaching 19 states.** Ceremonial
resolutions ("recognizing National Donate Life Month") circulate just as widely as policy but
say nothing about an agenda, so they are flagged separately — 65 of the 187.

| States | Bills | Cohesion | Template |
|---|---|---|---|
| 19 | 37 | 0.57 | Audiology and speech-language pathology interstate compact |
| 12 | 81 | 0.54 | Agreement Among the States to Elect the President by National Popular Vote |
| 12 | 54 | 0.31 | Sales and use tax exemption for feminine hygiene products |
| 9 | 18 | 0.62 | Uniform Civil Remedies for Unauthorized Disclosure of Intimate Images |
| 8 | 38 | 0.43 | Health insurance coverage for hearing aids |
| 7 | 13 | 0.50 | Health insurance coverage for biomarker testing |
| 6 | 38 | 0.36 | Applying for an Article V convention to amend the U.S. Constitution |
| 6 | 26 | 0.50 | Forming Open and Robust University Minds (FORUM) Act |

The recovered set is face-valid: interstate professional-licensure compacts, the National
Popular Vote campaign, Article V convention applications, and the FORUM Act all circulate as
named model bills.

**Read the state counts as an upper bound.** Clusters are connected components, so membership
is transitive: if A resembles B and B resembles C, all three land in one cluster even when A
and C are not themselves similar. Every cluster therefore reports `min_similarity`, the lowest
pairwise score between any two of its members. Across the 187 clusters that runs 0.31–1.00
(median 0.71), and **132 of 187 contain at least one pair below the 0.80 pairing threshold** —
the 19-state compact cluster sits at 0.57, because states retitle the same compact freely
("enacting the...", "adopting the...", "...licensure compact act"). Treat a cluster as one
tight template when that value is high, and as a family of related bills when it is not.

**This shows text reuse, not authorship or coordination.** Two states can independently choose
the same words, which is why generic administrative titles are excluded, a length floor applies,
and each cluster is evidence worth examining rather than proof of copying.

---

## Per-state profiles and cross-state outliers

National averages hide the interesting cases, so `analysis/profiles.py` also asks what *each*
state party emphasizes and which ones are unlike their own national party.

```bash
uv run python -m state_politics.analysis.profiles
```

Distance is cosine over the topic-share vector — cosine because it compares the *shape* of an
agenda rather than its volume, which varies by an order of magnitude between New York and
Wyoming. Comparison is **within party**, so the result is "unusual for a Democrat" rather than
the trivial finding that Democrats differ from Republicans. Organizations with fewer than 30
classified planks or bills are dropped, since one plank there moves a share by tens of points.

Most distinctive by platform emphasis:

| Org | Distance | Most distinctive topic | vs party average |
|---|---|---|---|
| NJ-D | 0.393 | Macroeconomics | 18.2% vs 1.9% |
| KY-R | 0.342 | International affairs | 18.3% vs 2.1% |
| FL-D | 0.269 | Health | 35.6% vs 11.6% |
| NJ-R | 0.267 | Macroeconomics | 19.2% vs 4.6% |
| MT-D | 0.262 | Public lands and water | 33.0% vs 8.9% |

Most distinctive by what their legislators actually file:

| Org | Distance | Most distinctive topic | vs party average |
|---|---|---|---|
| ID-D | 0.373 | Civil rights and liberties | 22.5% vs 4.3% |
| IL-R | 0.167 | Science, technology and communications | 14.0% vs 2.0% |
| NM-D | 0.161 | Social welfare | 19.7% vs 4.0% |
| SD-D | 0.158 | Public lands and water | 20.2% vs 8.4% |
| ND-R | 0.151 | Public lands and water | 28.8% vs 11.2% |

Outputs: `state_party_profiles.csv` (one row per organization, with its top platform topics,
top filing topics and platform status), `platform_outliers.csv`, `bill_outliers.csv`.

---

## Reproduce everything

The whole pipeline is a `make` target away. Everything is idempotent, and anything fetched is
recorded in `data/provenance.jsonl` with its URL, HTTP status, SHA-256 and retrieval time.

```bash
make setup      # install dependencies, including the local model stack
make all        # analysis + figures (needs `make platforms` and `make bills-dump` first)
make test lint  # 260 tests, ruff
```

The network-heavy stages are deliberately **not** part of `make all`, so rebuilding the
analysis never re-crawls anyone's website:

```bash
make registry     # verify all 100 state party websites  (~10 min)
make platforms    # discover + collect 2018-present platforms (~1 h, polite crawl)
make bills-dump   # download the 10.7 GB dump, extract bills, delete it (~20 min)
```

## Setup

Requires Python 3.11+ and Apple Silicon (for local GPU inference). Uses
[uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev                  # create .venv and install dependencies
uv sync --extra dev --extra models   # add local-only model stack (torch + MPS)
uv run pytest                        # run the test suite
uv run ruff check .                  # lint
```

The `models` extra installs **torch, sentence-transformers and scikit-learn** — all of which run
locally. No API keys are required by this project, and none should ever be added.

---

## Layout

```
state-politics/
├── CITATIONS.md                 # bibliographic citations, collector-first
├── conf/
│   ├── party_registry.yml       # 100 state party orgs: state, party, domain, source_url, verified_on
│   ├── topics.yml               # CAP-anchored issue taxonomy shared by both streams
│   ├── platform_gaps.yml        # hand-checked reason each of the 24 gaps has no platform
│   └── subject_topic_map.yml    # Open States subject tags -> topic codes, for validation
├── data/gold/
│   └── plank_topics_gold.csv    # 50 hand-labelled planks; authored input, not an artifact
├── src/state_politics/
│   ├── provenance.py            # url, http_status, sha256, retrieved_at, source_org
│   ├── compute.py               # local device selection + hosted-LLM guard
│   ├── plotting/                # shared portfolio chart theme
│   ├── platforms/               # stream A: manifesto collection + extraction
│   ├── bills/                   # stream B: Open States ingest + sponsor party join
│   └── analysis/                # topics, emphasis, divergence, diffusion, validation
├── data/                        # gitignored; fully reproducible from code
└── tests/
```

## Provenance

Every network fetch in this project goes through `state_politics.provenance`, which writes an
append-only JSONL log recording the URL, HTTP status, SHA-256 of the body, byte count, content type,
UTC retrieval timestamp, and the organization that collected the data. That log is what makes the
"no fabricated data" principle checkable rather than aspirational.

Notably, `fetch()` **does not raise on HTTP errors**. A 404 is a legitimate research finding — the
state party published no platform — so it is recorded with `ok=False` rather than thrown away.

## Figures

Figures use the shared portfolio theme in `state_politics.plotting`, matched to
`congressional_record` and `pre1870_reapportionment_package`: cream `#F7F5F0` background, serif
type, muted grid, tickless axes, borderless legend, bold title with a muted subtitle, italic source
note, direct end-of-line series labels, saved at `dpi=200` with `bbox_inches="tight"`. Democratic
series use the muted blue `#3D6F8C`, Republican series the terracotta `#C85A3D`. The palette is
pinned by tests so it cannot drift away from the other repos.

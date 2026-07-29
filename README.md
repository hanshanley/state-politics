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
2. **Absence is a finding.** "The Ohio Republican Party has published no platform since 2000" is a
   legitimate research result, not a pipeline bug. The gap report is a deliverable.
3. **No hosted LLM APIs. Models run locally.** Every model this project runs — embeddings, classifiers,
   topic models — runs on this machine's Apple Silicon GPU (M4, 16 GB unified memory) via Metal
   Performance Shaders, falling back to CPU. This is enforced in code, not just documented: a test
   scans the entire source tree for hosted-provider imports and inference endpoints and fails the
   build if any appear. See [`src/state_politics/compute.py`](src/state_politics/compute.py).
   The reason is reproducibility — a hosted model is an unversioned dependency, and a result that
   cannot be regenerated from pinned local weights is not reproducible research.
4. **Cite the collector, not the redistributor.** Citations name the organization or authors who
   *collected* the data, not merely the API that served it. See [`CITATIONS.md`](CITATIONS.md).
5. **Reproducible from source.** Nothing in `data/` is committed. Everything is rebuildable by running
   the pipeline.

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
| 5 | Wikidata | Registry of official state party websites | 50/50 Democratic; Republican needs extra work |

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

Full roadmap, including the source-verification work behind it, is in [`docs/PLAN.md`](docs/PLAN.md).

### Stream B: legislators and bills

`state_politics.bills.people` ingests the current legislators for all 50 states from Open
States' **public, no-auth** per-state CSVs. This is the join key for the whole bills stream —
a bill records who sponsored it, and this records which party that sponsor belongs to.

```bash
uv run python -m state_politics.bills.people
```

**Result: 7,359 currently-serving legislators across all 50 states** — 4,000 Republican,
3,166 Democratic, 193 other. Chambers: 5,389 lower, 1,921 upper, 49 `legislature` (Nebraska's
nonpartisan unicameral). Third parties and independents are deliberately kept as `other`
rather than folded into the major two, since misfiling them would misattribute their bills.

`state_politics.bills.openstates_dump` + `bills.ingest` extract the bills themselves from
Open States' public PostgreSQL dump.

```bash
# ~8 min to download at 20 MB/s, then ~10 min to extract. Needs pg_restore:
#   brew install libpq     (Homebrew keeps it out of PATH; the module looks there anyway)
uv run python -m state_politics.bills.ingest
```

**Result: 1,044,751 bills filed 2018–2026 across all 50 states, and 4,770,793 sponsorships.**
Party attribution: 412,984 Democratic, 352,811 Republican, 66,300 bipartisan, 212,656 unknown.

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

A bill is attributed to a party by its **primary** sponsors. Cosponsor lists are long,
cross-party and procedural, so letting them vote would blur the very distinction the table
exists to draw; bills whose sponsors cannot be resolved are `unknown`, not guessed.

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
Open States `subject` tags can be mapped onto the same scheme when the bills stream unblocks.

Classification runs **locally on the M4 via MPS** — a pinned sentence-transformer embeds each
plank and each topic description and assigns the nearest topic. A transparent keyword baseline
runs alongside it, not as a fallback but so the model's output can be checked against something
a human can read and argue with.

**Validation, on 43,104 planks from 872 documents:**

| Classifier | Top-1 | Top-2 |
|---|---|---|
| Keyword baseline | 56% | — |
| Embedding (MPS) | **62%** | **78%** |

Scored against `data/gold/plank_topics_gold.csv` — 50 planks drawn at random (seed 20260729)
and hand-labelled by the author. It is small and single-annotator, so it supports claims about
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
more about housing, crime and transportation than they talk about.**

| | Said (platform) | Filed (bills) |
|---|---|---|
| **Civil rights and liberties** — D | 8.2% | 3.0% |
| **Civil rights and liberties** — R | 9.7% | 2.8% |
| **Culture, family and social issues** — R | 4.8% | 1.5% |
| **Immigration** — R | 4.1% | 0.9% |
| **Law, crime and justice** — D | 7.3% | 13.9% |
| **Law, crime and justice** — R | 9.4% | 15.5% |
| **Housing and community development** — D | 3.3% | 9.4% |
| **Housing and community development** — R | 1.1% | 6.0% |

The pattern is symmetric across both parties, which is what makes it interesting: the topics
that dominate platform rhetoric are largely *national* fights that state legislatures have
limited power over, while the topics that dominate actual filing are the bread-and-butter
business of state government. Immigration is the sharpest case — Republican platforms give it
4.1% of their planks and Republican legislators 0.9% of their bills.

**Read these numbers with their limits.** Bills are classified from *titles*, which are short
and often procedural — a noisier signal than a platform plank, and the 62%/78% validation
figures were measured on planks, not titles. Roughly a fifth of bills cannot be resolved to a
party and are excluded rather than guessed at. And filing a bill is not passing one: this
measures **agenda, not achievement**.

Democratic state parties devote more of their platforms to labour, the environment, housing,
health and social welfare; Republican state parties to government operations, public lands,
taxation, culture and family questions, and law and crime. Planks below a similarity threshold
are recorded as **unclassified** and excluded from the denominator rather than pushed into
whichever topic was least far away — 3,051 of the 43,104 planks fall there.

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
| NY-R | 0.382 | Energy | 20.0% vs 2.6% |
| KY-R | 0.334 | International affairs | 18.3% vs 2.1% |
| NJ-D | 0.317 | Macroeconomics | 17.0% vs 2.0% |
| FL-D | 0.290 | Health | 35.3% vs 11.1% |
| MT-D | 0.226 | Public lands and water | 27.8% vs 8.5% |

Most distinctive by what their legislators actually file:

| Org | Distance | Most distinctive topic | vs party average |
|---|---|---|---|
| ID-D | 0.373 | Civil rights and liberties | 22.5% vs 4.3% |
| IL-R | 0.170 | Science, technology and communications | 14.3% vs 2.0% |
| NM-D | 0.161 | Social welfare | 19.7% vs 4.0% |
| SD-D | 0.159 | Public lands and water | 20.2% vs 8.4% |
| ND-R | 0.152 | Public lands and water | 28.8% vs 11.2% |

Outputs: `state_party_profiles.csv` (one row per organization, with its top platform topics,
top filing topics and platform status), `platform_outliers.csv`, `bill_outliers.csv`.

---

## Reproduce everything

The whole pipeline is a `make` target away. Everything is idempotent, and anything fetched is
recorded in `data/provenance.jsonl` with its URL, HTTP status, SHA-256 and retrieval time.

```bash
make setup      # install dependencies, including the local model stack
make all        # historical corpus + analysis + figures (no crawling)
make test lint  # 218 tests, ruff
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
│   └── party_registry.yml       # 100 state party orgs: state, party, domain, source_url, verified_on
├── src/state_politics/
│   ├── provenance.py            # url, http_status, sha256, retrieved_at, source_org
│   ├── compute.py               # local device selection + hosted-LLM guard
│   ├── plotting/                # shared portfolio chart theme
│   ├── platforms/               # stream A: manifesto collection + extraction
│   ├── bills/                   # stream B: Open States ingest + sponsor party join
│   └── analysis/                # topics, emphasis, diffusion
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

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
downloading it and enumerating every file: 4,154 platform documents, 2,105 unique
`(state, party, year)` observations, all 50 states, **maximum year 2017**. Coverage is also very uneven
(Kentucky Democrats last appear in **1943**; New York Democrats in **1958**; Florida Republicans not at all).

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
| 1 | Hopkins, Coffey, Galvin, Gamm, Henderson, Paddock & Schickler — *Select American State Party Platforms, 1846–2017* (Harvard Dataverse, CC0) | Historical platforms | 4,154 files, 50 states, 1840–2017 |
| 2 | Open States / Plural Policy — bulk data | State bills, votes, legislators (all 50 states, current) | 2026-07 public dump, 10.7 GB |
| 3 | Open States API v3 | Targeted bill/sponsorship refresh | `Bill.sponsorships`, `Person.party` |
| 4 | Internet Archive — Wayback CDX Server API | Discovery of 2018–present platform documents | Returned real platform docs |
| 5 | Wikidata | Registry of official state party websites | 50/50 Democratic; Republican needs extra work |

---

## Project status

Greenfield. Work is organized in phases:

| Phase | Description | Status |
|---|---|---|
| 0 | Scaffolding + provenance layer | 🚧 in progress |
| 1 | Ingest historical platform corpus (1846–2017) | ⬜ |
| 2 | Build verified registry of all 100 state party organizations | ⬜ |
| 3 | Collect 2018–present platforms (the hard part) | ⬜ |
| 4 | Build 50-state bill + sponsor-party pipeline | ⬜ |
| 5 | Define a shared issue taxonomy for both streams | ⬜ |
| 6 | Compute emphasis scores and stated-vs-revealed divergence | ⬜ |
| 7 | Outputs, per-state profiles, reproducible build | ⬜ |

---

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
│   └── topics.yml               # issue taxonomy + seed terms
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

# Citations

This project credits the organizations and authors who **collected** each dataset, not merely the API
or platform that redistributes it. Every source below was fetched and verified on the stated access date.

---

## 1. Historical state party platforms (1846–2017)

> Hopkins, Daniel J.; Coffey, Daniel J.; Galvin, Daniel J.; Gamm, Gerald; Henderson, John;
> Paddock, Joel W.; Schickler, Eric (2022). *Select American State Party Platforms, 1846–2017*
> (Version 3.0, released 2025-04-23) [Data set]. Harvard Dataverse.
> https://doi.org/10.7910/DVN/KNOSHL. Licensed CC0 1.0. Accessed 2026-07-28.

**Verified contents (authoritative archive `platform-update-04212025.zip`):** 2,091 platform documents;
2,086 unique `(state, party, year)` observations; **49 states** plus `US` national platforms; year range
1840–2017; Democratic = 1,066 documents, Republican = 909, remainder third parties (Prohibition,
Progressive, Socialist, People's, Libertarian, Green, Whig, Greenback, Nonpartisan League and others).

**Archive structure.** The dataset ships two zips. `platform-update-04212025.zip` (2,091 documents) is the
current archive and **supersedes** `05 for public.zip` (2,063 documents); the bundled
`file_changes_04232025KG.txt` reconciles them exactly — the 49 listed additions appear only in the update
and the 21 listed deletions only in the older archive, while 47 further files were revised in place.
Unioning the two archives would resurrect deleted files and double-count the rest, so this project treats
the update archive as authoritative.

**Known limitations:**

* The corpus ends at **2017** and cannot speak to the present day.
* **Maryland is absent entirely** — no document of any party or year.
* Recency is very uneven. The most recent major-party platform is earlier than 2010 for Kentucky,
  Louisiana, New Jersey, Ohio and Pennsylvania; Florida has no Republican document and Louisiana no
  Democratic one.

---

## 2. State legislative bills, votes, and legislators

> Open States / Plural Policy (2026). *Open States Bulk Data: 2026-07 public PostgreSQL dump and
> current legislator CSV files* [Data set]. Plural Policy. https://open.pluralpolicy.com/data/.
> Released under a public domain dedication. Accessed 2026-08-01.

Open States collects this data by scraping official state legislative websites; those legislatures are
the ultimate originating source, and Open States is the collecting and standardizing organization.

**Verified:** public PostgreSQL dump `2026-07-public.pgdump`, 10,711,908,617 bytes, last modified
2026-07-01, SHA-256
`e4b8eb6d40d2da768074dab29bbf0d6949b8f24a50d75c5807669edcee5af78c`, no authentication
required. The extracted outcome corpus includes 8,954,085 bill actions and 869,001 bill-linked
vote events. Per-state current legislator CSVs are public for all 50 states.

---

## 3. Open States API v3

> Open States / Plural Policy (2026). *Open States API v3* [API]. Plural Policy.
> https://v3.openstates.org. Accessed 2026-07-28.

Used for targeted refreshes of bill and sponsorship data between monthly bulk dumps.

---

## 4. Web archive captures of state party platform documents

> Internet Archive (2026). *Wayback Machine CDX Server API* [Web archive].
> Internet Archive. https://web.archive.org/cdx/search/cdx. Accessed 2026-07-28.

Used to discover and retrieve platform documents published 2018–present by state party organizations.
The **originating publisher of each platform document is the individual state party committee**, and
each retrieved document is attributed to that committee in the dataset, with the Internet Archive
credited as the archival intermediary.

---

## 5. Registry of official state party websites

> Wikidata contributors (2026). *Wikidata* [Knowledge base]. Wikimedia Foundation.
> https://query.wikidata.org/sparql. Licensed CC0 1.0. Accessed 2026-07-28.

Used as the starting point for the registry of the 100 state party organizations. Every entry is
checked against the party's own live homepage before use — a row is trusted only when the visible
page text identifies that state's party, so a parked, suspended or hijacked domain cannot pass.
Each registry row records its own `source_url`, `verified_on` date and observed HTTP status. Rows
that could not be confirmed carry `needs_review: true` and require human confirmation; they are not
treated as verified.

---

## Citation of this project

If you use the 2018–present platform corpus produced here, please cite both this repository and the
individual state party committees that published the underlying documents.

---

## 6. Issue taxonomy

> Comparative Agendas Project (2026). *Master Codebook: major topic codes* [Coding scheme].
> Comparative Agendas Project. https://www.comparativeagendas.net/pages/master-codebook.
> Accessed 2026-07-29.

`conf/topics.yml` adapts the CAP major topic codes; the topic descriptions and seed terms were
written for this project. Anchoring to an existing scheme rather than inventing one keeps the
results comparable with the wider agenda-setting literature and lets the Open States `subject`
tags be mapped onto the same taxonomy.

## 7. Plank classification model

> Reimers, Nils & Gurevych, Iryna (2019). *Sentence-BERT: Sentence Embeddings using Siamese
> BERT-Networks.* Proceedings of EMNLP-IJCNLP 2019. Model weights:
> `sentence-transformers/all-MiniLM-L6-v2`, Hugging Face. Accessed 2026-07-29.

The exact Python dependency versions are pinned in `uv.lock`; validation results are computed
from the fixed hand-labelled snapshot in `data/gold/plank_topics_gold.csv`.

## 8. Official state-party documents hosted by Issuu and Wix

> New York State Democratic Committee (2023, updated 2025). *NYDems Resolutions Archive*
> [State committee resolutions]. Official NYDems Issuu account.
> https://issuu.com/nydems/docs/resolutions. Accessed 2026-07-31.

> Republican Party of Louisiana (2025). *2025 RSCC Resolutions, Q1–Q4*
> [State Central Committee resolution packets]. Official LAGOP resolutions page:
> https://www.lagop.com/2025-rscc-resolutions; scanned PDFs served by Wix's official document
> CDN. Accessed 2026-07-31.

These are primary party-committee sources. Issuu and Wix are delivery intermediaries, not the
credited authors. The documents require OCR; fixed source identifiers/PDF hashes and the
deterministic reconstruction code are in `conf/official_document_registry.yml` and
`src/state_politics/platforms/official_documents.py`.

## 9. Supplemental legislative-caucus priority agendas

The following primary sources complete stated state-level agenda coverage while remaining a
separate corpus from party-committee platforms:

> Kentucky Senate Republican Caucus Campaign Committee (2024). *Priority Legislation for
> Regular Session 2024*. https://kysenaterepublicans.com/new-page-34 and linked official
> Kentucky Legislative Research Commission bill records.

> Maryland Senate Democratic Caucus (2025). *Senate President Bill Ferguson Announces
> Committee Leadership Changes, Member Assignments for 2026* [agenda statement].
> https://www.mdsenate.com/news/2025/12/16/senate-president-bill-ferguson-announces-committee-leadership-changes-member-assignments-for-2026/

> New Jersey General Assembly Republican Office (2025). *Priorities / Agenda Center*.
> https://www.njassemblygop.com/35/Priorities and linked priority pages.

> Pennsylvania Senate Democratic Caucus (2025). *Priorities*.
> https://pasenate.com/priorities/.

The curated source registry is `conf/caucus_priority_registry.yml`; collection code is
`src/state_politics/caucuses.py`.

## 10. Authored validation labels

> State Politics Project (2026). *Hand-labelled state-party platform plank validation
> snapshot* [50 labelled planks]. `data/gold/plank_topics_gold.csv`.

Sampling metadata, seed, source frame, and the labeling protocol are preserved in
`data/gold/plank_topics_gold.meta.yml` and `data/gold/README.md`. These labels are authored
evidence—not a generated artifact—and are hashed in `conf/reproducibility.yml`.

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
> Released under a public domain dedication. Accessed 2026-07-28.

Open States collects this data by scraping official state legislative websites; those legislatures are
the ultimate originating source, and Open States is the collecting and standardizing organization.

**Verified:** public PostgreSQL dump `2026-07-public.pgdump`, 10,711,908,617 bytes, last modified
2026-07-01, no authentication required. Per-state current legislator CSVs public for all 50 states.

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

Run locally on Apple Silicon via MPS. No hosted inference API is used anywhere in this project.

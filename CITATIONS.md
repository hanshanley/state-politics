# Citations

This project credits the organizations and authors who **collected** each dataset, not merely the API
or platform that redistributes it. Every source below was fetched and verified on the stated access date.

---

## 1. Historical state party platforms (1846–2017)

> Hopkins, Daniel J.; Coffey, Daniel J.; Galvin, Daniel J.; Gamm, Gerald; Henderson, John;
> Paddock, Joel W.; Schickler, Eric (2022). *Select American State Party Platforms, 1846–2017*
> (Version 3.0, released 2025-04-23) [Data set]. Harvard Dataverse.
> https://doi.org/10.7910/DVN/KNOSHL. Licensed CC0 1.0. Accessed 2026-07-28.

**Verified contents:** 4,154 platform text files; 2,105 unique `(state, party, year)` observations;
50 state codes plus `US` for national platforms; year range 1840–2017; Democratic = 2,113 files,
Republican = 1,809 files, remainder third parties (Prohibition, Progressive, Socialist, People's,
Libertarian, Green, Whig, Greenback).

**Known limitation:** the corpus ends at **2017**. It cannot answer questions about the present day.

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
manually verified against the party's own website before use, and each registry row records its own
`source_url` and `verified_on` date.

---

## Citation of this project

If you use the 2018–present platform corpus produced here, please cite both this repository and the
individual state party committees that published the underlying documents.

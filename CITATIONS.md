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

## 11. Independent research-corpus text

MTSUs-Fall-2025-Software-Engineering-Pr (2025). *United States State Legislation
with Summaries* [Data set], published through Hugging Face. Accessed 2026-10-22;
pinned revision `d4f15948c8af7733df9aa70ce68b14a65dec3d82`.
Original keyed NH/IL records are additionally pinned to revision
`9411b4690c3ba8c0c28ab19eb9370316908c00af`; whole-record comparisons
restore removed source filenames and original dataset keys, without interpreting
those keys as external bill IDs or inventing a session.

Source: `https://huggingface.co/datasets/MTSUs-Fall-2025-Software-Engineering-Pr/United_States_State_Legislation_with_Summaries`.
The dataset card declares Apache-2.0; this is a recorded publisher license
observation, not verification of every upstream right or cleaning step.
The credited corpus publisher is an intermediary; legislative bodies are the
originating institutions represented in the printed source text.

Complete NH/IL/TX JSON files match the pinned tree's advertised LFS SHA-256 and
byte counts. Original text/title/summary fields and duplicate records are
preserved. Printed state, assembly/session and bill identities link only
existing missing-text candidates. Source summaries are neither independent
human gold nor classifier output. Publisher-original/version completeness,
cleaning quality, filing-time alignment and redistribution remain uncertified;
this source is exposed only in the unpublished research workspace.

## 12. Independent legislative archives

Windy Civi Pipelines. *New Jersey data pipeline*, immutable commit
`c99d1624d45dd8bc0b282a6469e19ee28e112097` (December 14, 2025), accessed
2026-10-22. Repository: `windy-civi-pipelines/nj-data-pipeline`. This older
archive actually retains session 221, unlike the newer repository's session
catalog alone. The complete downloaded tar SHA-256 is
`0d5f348f6db36b57503ca894907fe44e70eeba071610b4d057b85640ab862f18`.
Reconstructing every archived `country:us` Git blob/tree reproduces the
pinned data-tree object `4b57fb6de51433a6673c1e68443eb79e7d28be49`;
a truncated recursive-tree API response is not treated as a complete census.

The originating records are New Jersey legislative materials; the repository
and its extractor are intermediaries. Full archived text includes the
extractor's existing machine-generated prologue, explicitly distinguished
from printed bill evidence and never used as human gold. No standalone data
license was observed in this older repository. A newer project's CC BY 4.0
dashboard/download notice is not assumed to license this predecessor archive.
The complete raw archive, original HTML, metadata, source-version links and
rejected/conflicting documents remain local research evidence. No publisher
original, introduced-version, redistribution or model approval is inferred.

LawAtlas / MonQcle, Temple University Center for Public Health Law Research,
with ASTHO under Act for Public Health. *State Bills Relating to Vaccines in
Schools and Provider Scopes of Practice*, study `65249f4d9cd360fa468b4573`.
Public research records and attached legislative PDFs, accessed 2026-10-22.
Four exact existing candidates retain complete attached
bill text: NJ S3841 and A5445 (220th Legislature), NJ A1899 (221st Legislature)
and NE LB202 (108th Legislature). New Jersey and Nebraska legislative bodies
are the originating institutions; LawAtlas is an independent archive, not
an original-version certification. Full original public records, duplicate
source-row references, all six downloaded attachments, extraction alternatives,
HTTP evidence, 675-row source dispositions and the partial-size-abort caveat
are retained in `data/processed/lawatlas-text-evidence-20261022-v1/`.
Recorded source/rights observations remain in its
`source-evidence/source_findings.json`. This legacy study's retained Terms of
Download declares CC BY 4.0 except otherwise noted, with attribution and change
notice conditions. The retained public viewer constructs the legal-record
and attachment URLs used here; no credentials or cookies were supplied.
Its agreement checkbox/statistical export was not executed, no statistical
export was downloaded, and not all external scripts/site-wide terms were
retained. Public HTTP responses alone do not prove blanket attachment rights.
The different Hawaii lead's explicit account restriction remains binding for
that lead; this study is not a way around it. No general redistribution or
filing-time approval is asserted.

Windy Civi Pipelines. *Maryland data pipeline*, immutable commit
`0e17cc31f8830462eed3caaf578a9f0a370ec79d`, accessed 2026-10-22.
Repository: `windy-civi-pipelines/md-data-pipeline`. Complete root Git tree:
`0a68f74d4cbeb9902d308245851d7e702dea97ba`; downloaded tar SHA-256:
`d47c374e8f5da1455b9bc1a74bdc1c61d34bafc24e1293890b3c9148ab43f9f4`.
All 33,167 blobs reconstruct the complete pinned tree. The matched materials
are 2025-session bill views joined only to already retained 2024 prefiling
contexts, not a newly inferred 2023/2024 session universe.

The originating institution is the Maryland legislature; this intermediary
archive/extractor is not publisher-original or filing-time certification.
Complete original extraction strings retain their machine prologues; exact
source-bound body starts permit explicitly separate inference inputs.
The packet preserves all 1,755 original copied evidence files and every
negative/rejected disposition. No standalone data license was observed in
the complete archive. Local research retention does not confer redistribution,
publication, model certification or event-time party approval.

New Jersey State Library. *New Jersey Legislative Histories: 2023*, accessed
2026-10-22. Collection:
https://repo.njstatelib.org/collections/f596cfea-88be-454e-9c43-acb0c0f8c18c.
The library's compiled PDFs retain introduced bills, separately identified
enacted versions, companion bills and ancillary statements/checklists.
The originating legislative institution remains the New Jersey Legislature;
the library compilation is a distinct archive, not filing-time certification.

Complete captured PDFs, public item metadata, original catalogue records,
robots policy, response bodies/headers and explicit redirect entities are
retained in `data/processed/remaining-hi-nj-independent-corpus-20261022-v1/`.
Both PDF readers and all ancillary pages remain separate evidence. A
checklist-only PDF is not a recovered bill body, and another version's
printed session witness is not appended to the policy input. No blanket
redistribution, introduced-version, model or publication approval is inferred.
The corrected v5 normalization declares that these library views contain no
machine-generated archive prologue. It preserves all original PDF/page strings,
printed witnesses and versions; no new retrieval or source-date inference
accompanies that metadata correction.

## 13. Subsequent complete collection and official session-context witnesses

New Jersey State Library. *New Jersey Legislative Histories: 2023*, complete
finite published collection captured 2026-10-23. The retained twelve catalogue
pages enumerate 237 items. A new bounded capture adds 229 complete PDFs
(301,943,898 bytes / 9,952 physical pages), while eight earlier PDFs are reused
only through exact original published bitstream URLs. All 237 current published
bitstream sizes match the retained bytes. Source packet:
`data/processed/nj-library-2023-collection-20261023-v1/`; manifest SHA-256
`195c78827c877ceb3c9e22ba4d0693585abad4121224c2be78bd0d66ea7ef1de`.
The original thirteen-response parser failure and its no-refetch continuation
remain explicit; 479 new exchanges stay under the original 500 allowance.
This completes that collection capture, not statewide native coverage, successful
text normalization, filing-time identity or scientific approval.

Oklahoma House of Representatives. *House Completes Bill Filing for 2023
Session*, January 20, 2023,
https://www.okhouse.gov/posts/news-20230120_1; and *House Completes Bill Filing
for 2024 Session*, January 19, 2024,
https://www.okhouse.gov/posts/news-20230119_1. The latter URL's embedded year
is not substituted for the page's actual displayed publication date. Full raw
HTML, visible text nodes, exact raw-source spans and the separately captured
House rules index remain in
`data/processed/ok-house-rules-context-20261023-v1/`; manifest SHA-256
`a59fea589165294a5a1eadaeea5530eeca4e63f67f937a93056cd72d47f8827d`.
These primary publications establish first-2023 / second-2024 session context
within the 59th Legislature. They do not establish that a named bill carried
over, remained pending, was reintroduced or acquired a target-year filing date.
Both original annual source contexts, exact document pointers and source-body
authority limitations must remain separate. The retained bodies under review
are OpenStates snapshot extractions, not upgraded native publisher captures.

The independent Senate context attempt remains an explicitly sealed
JavaScript/cookie access stop, not a captured source page or permission to try
an alias. The distinct House publications are not copies of that challenged
resource. The later all-state LawAtlas/MonQcle attachment lead packet likewise
preserves its new robots prohibition and zero attachment requests; earlier
captured PDFs are neither erased nor used to imply current retrieval permission.
No new body count, source rights, filing-time, model, human-gold or publication
approval follows merely from these acquisition receipts.

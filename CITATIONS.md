# Citations

This project credits the organizations and authors who **collected** each dataset, not merely the API
or platform that redistributes it. Acquisition receipts identify the versions actually retained;
historical declarations, failed leads and unresolved rights are distinguished below.

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

> Open States / Plural Policy (2026). *Open States Bulk Data: 2026-10 public PostgreSQL dump and
> current legislator CSV files* [Data set]. Plural Policy. https://open.pluralpolicy.com/data/.
> Provider public-domain dedication; individual source rights remain unapproved here.
> Target-study dump accessed 2026-10-18.

Open States collects this data by scraping official state legislative websites; those legislatures are
the ultimate originating source, and Open States is the collecting and standardizing organization.

**Current target-study source:** the actual retained dump is
`data/raw/openstates/2026-10-public.pgdump`, **10,768,629,207 bytes**, SHA-256
`6aa8341edc9ec251f4fb1eafb134b3415e72296e5391e05b39aded5e1ae2580c`.
Its original fetch records one HTTP 200 at **2026-10-18T16:07:19Z**.
The original extraction manifest is
`data/processed/bill_extraction_manifest.json`, SHA-256
`9a3555e5194ac3d45ab30c4107df4f720ad40f3ce85e040fa5336138d8ee8a29`;
its complete retained action table has 9,002,451 rows. Original fetch
metadata does not retain ETag or Last-Modified, so neither is invented.
The October 23 metadata follow-up encounters `data.openstates.org/robots.txt`
HTTP 403 and stops without probing/redownloading the bulk object or bypassing
the account-gated session JSON route. No newer object version is established.

**Historical July declaration, not the current extraction:** the earlier provenance
records `2026-07-public.pgdump`, 10,711,908,617 bytes, last modified
2026-07-01, SHA-256
`e4b8eb6d40d2da768074dab29bbf0d6949b8f24a50d75c5807669edcee5af78c`, no authentication
required, accessed 2026-08-01. That earlier outcome corpus records 8,954,085
bill actions and 869,001 bill-linked vote events. The July dump is not the
retained file used by the current study and is not reverified here. Per-state
current legislator CSVs are a separate source from filing-time party evidence.

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

The subsequent offline full-collection normalization retains all 19,904
independent reader-page/layout records and recovers 97 exact original missing
NJ contexts / 255 complete reader views. Unsupported, incomplete, ambiguous,
checklist-only and prior-content duplicates remain explicit negatives, not
additional recovered bills. The normalized packet is
`data/processed/nj-library-collection-text-full-20261023-v1/`, manifest
`e8933b0d69ab9a791ef4830e35044fde4022e8df2880f4a9c544426a9f9601a6`.
The separately replayed Oklahoma packet is
`data/processed/ok-retained-context-text-20261023-v2/`, manifest
`de881d50d6fe4ce29d466e6fc83253ba68b0bf6701555a090aa47bcee40af9d8`:
2,000 exact historical-document relations, with all 135 rejected witnesses and
both original annual contexts preserved. These observed body-source additions
do not waive the authority, version, date, rights or approval limits above.

## 14. Independently published Hawaii HTML copies

Hawaii State Legislature, originating legislative text; BillCam / DailyClout,
independently served public cached copies, accessed 2026-10-23. An inspected
example is the provider's HB 2152 context,
https://billcam.com/bills/6Xs1uySRd3/g/hb-2152/relating-to-artificial-intelligence,
and its actually linked full HTML,
https://billcam.com/bill-texts/BnfQ9OxCv3. Provider metadata retains
state and LegiScan source URLs, local-copy paths, version IDs and stage/date
claims. That metadata is not independently certified source-transfer history;
neither those native URLs nor LegiScan's API/body endpoints were requested.

### Current supplement: explicit original bill actions

Two offline packets recover **213 further original contexts / 229 unique
complete views / 1,827,636 characters**:
`data/processed/billcam-action-bound-html-delta-20261023-v1/`
(manifest `8cd20f56dde8d69ef9e1f8bed694526ecc1eddf091a508a53ff02a02d3f20b23`)
and `data/processed/billcam-action-bound-html-four-subject-20261023-v1/`
(manifest `0754dcbf9c7ba56eaf876575be54e232e1641637e58de635721f689eafd5dd37`).
Each body's own printed 2023 identity is linked to its unchanged 2024
candidate only through that original bill's explicit carryover event and
exact origin-introduction action IDs/chamber in the complete original
Open States action extraction above. Both years, all dates, raw HTML,
negative decisions and original metadata remain intact; no native URL
alias or filing-time-originality claim is made.

All old capture artifacts are retained through a lossless replayed map.
Nine repeated inherited source occurrences remain evidence, not extra
views or contexts; the active union has 229 views, not the provisional
238 occurrences. This recovery makes no new body requests and does not
restart a closed query. Separate public state-search metadata discovery
uses the publisher's ordinary anonymous form, including its normal
same-origin CSRF/session workflow, through **two GETs and one POST**.
It removes its private cookie jar and exports no cookie values, makes no
account/challenge/native request and is not a statewide census.
Current controlled BillCam counts are **3,048 GETs plus one POST**.
No reuse-rights, scientific, classification or publication approval follows.

### Preceding annual-heading-only captures

The first closed wave retains 16 probe GETs and 500 subsequent GETs, with
all earlier responses, parser failures and explicit corrections preserved.
The first unsupported underscore-path request was not a verified discovery
and returned 404; it is not evidence that the correct hyphenated publication
was missing. Three source-linked subject queries retain all 129 advertised
pages. Their repeated result rows are preserved rather than silently dropped
or counted as additional bills. They are not a statewide or random sample.
Sealed source:
`data/processed/billcam-hi-target-source-20261023-v2/`, manifest
`a1137754c36f2a4847c458eebaeaf20e33e1b7e4ba983892ccc65c8153e0d54a`.

Strict offline normalization yields 111 original missing contexts / 253
complete published HTML views / 5,027,861 body characters:
`data/processed/billcam-hi-retained-html-full-20261023-v1/`, manifest
`9bfeaefd6fa650f37fe8248f0ba3fff2834979022240cafe67cb24adb5c90c4b`.
The entire source container and markup survive; provider UI, topic tags,
community material and current sponsor data are not appended to model inputs.
Each supplied version remains separate. A complete provider extraction is
not certification of the native original's completeness or authenticity.

Admission requires actual own printed state, 32nd Legislature, year and
typed number, independently matched to the provider context and unchanged
original candidate title. Conflicting years and identities stay unavailable.
The distinct literal native URLs are preserved without inferring aliases.
Provider date fields do not replace original filing/introduction evidence,
and current sponsor sessions do not establish 2023/2024 party affiliations.
No rights, introduced-version, model-accuracy, source, scientific or
publication approval is granted. A subsequent identified-document follow-up
has its own explicit scope and accounting; it does not reset this closed wave.

The subsequently enumerated document frontier was completed through a
separate 800-GET follow-up and a final 105-GET tail under its own 300
allowance. Together with the closed 16 + 500 wave, the known cumulative
total is 1,421 GETs; no original allowance was reset or native source stop
reopened. Source:
`data/processed/billcam-hi-identified-tail-20261023-v1/`, manifest
`3ceff25fa1b2951b06a4bb2cc83eb71839fe8a6ab4d0328ec60e057a983317a9`.
A lossless inventory map preserves every byte of the closed preceding
source packet, including prior ledger prefixes and overwritten operational
reports, without recursively duplicating another complete source tree.

The disjoint normalized delta is
`data/processed/billcam-hi-retained-html-delta-20261023-v1/`, manifest
`588d4280d8476623864527595969c751f2bff2085b2f687e6098c51d1b95a89d`:
288 further original contexts / 579 HTML views / 4,342,325 body characters.
It is built against the exact original queue minus the first 111 accepted
contexts, not a new cohort. Together the two normalized packets retain
399 contexts / 832 views; all 426 original missing-context leads from the
three subject queries were processed. The other 27 are not admitted under
the strict identity/source profile, not declared nonexistent legislation.
Both independent actual Chromium inert-DOM audits preserve every supplied
non-whitespace source character in order without executing source scripts
or requesting external resources. These checks are not human accuracy or
native-original certification.

### Completed subsequent four-subject discovery and acquisition

Replaying the 426 retained provider details identifies 945 actually published
subject links outside the three completed queries. Separate first-page
discovery retains thirteen GETs, including a refreshed robots policy:
`data/processed/billcam-new-subject-discovery-20261023-v1/`, manifest
`e12d3814c4e449ec0c79da93e0a6285be6904ce7775cb232ffa0c521aa58c7ea`.
This packet explicitly records the auxiliary web-tool observations separately;
neither unrelated transport nor all historical requests are asserted as zero.
The published search POST route is not used.
The scope's auxiliary web-URL list is not a retained exchange ledger and
does not certify a complete invocation history or transport count. Its
qualification is preserved in
`data/billcam-auxiliary-web-scope-correction-20261023-v1.json`; the fresh
robots policy is independently retained as discovery curl ordinal one.

The new four-subject scope has retained every advertised page for the
University of Hawaii, expenditure-ceiling, Department of Health and Department
of Education queries: 187 pages, 3,707 occurrences, 3,603 distinct provider
records and two repeated occurrences. It identifies 605 exact original
remaining-context leads, not 605 complete bills. The already captured but
unadmitted provider path is retained as a negative rather than requested again.
Acquisition of all 604 other provider details and eligible full HTML versions
closes after **1,612 / 2,000 GETs**, with no old detail/body request repeated.
Source: `data/processed/billcam-four-subject-source-20261023-v1/`, manifest
`fcda8cfced4df5e35630247a49e603d4d1316dccb8ea751b0fb41dad0a07fd82`.
Together with the preceding 1,421 GETs and separate thirteen-GET discovery,
that preceding checkpoint's controlled total is 3,046; the refreshed robots request is not a
distinct URL, and unrelated transport is not asserted reconstructed or zero.

Strict own-header/context normalization supplies **415 additional original
contexts / 619 complete published views / 4,674,311 characters**:
`data/processed/billcam-four-subject-html-20261023-v1/`, manifest
`801644d9387b094f142e544a638e13e3a942d9d31eecf8c181d6345ae674c15e`.
This is a third disjoint packet, not a replacement for the preceding two.
All 605 original leads and every offered version are accounted for by
`data/billcam-four-subject-frontier-replay-20261023-v1.json`; 190 original
leads remain unadmitted, not nonexistent. Prior scopes and publisher/account
stops remain closed; original dates, titles, session IDs, unknowns and all
approval gates are unchanged. No inference or human-accuracy result follows
from source capture alone.

### Offline wrapped-heading correction, with all prior packets preserved

The independent rejected-document audit identifies no different-context
fills. Its narrower HB 1993 diagnosis proves the source's actual line break
between `THIRTY-SECOND` and `LEGISLATURE, 2024`; the original reader's literal
space check rejected both otherwise complete versions. Both legislative
headings are present. The separate superseding diagnostic distinguishes this
case from two SB 2351 versions with genuinely absent headings.

The corrected reader preserves exact source spans and requires matching
own printed bill captions; it does not infer dates, aliases or carryover.
HB 2699's conflicting caption is not admitted. An offline projection of the
same immutable capture onto the exact remaining 18,651-row original subset
recovers HB 1993 as **one context / two views / 10,687 characters**:
`data/processed/billcam-wrapped-heading-html-20261023-v1/`, manifest
`23343ed2edc6a4b38e8a32808079e2507bf6c4048def1f30debcd345437adab5`.
Projection source manifest:
`0f56ea100ff074ba61565add690a5c6b857008844ff025f48d92be30b094e74f`.
All 6,522 original source artifacts and original context fields survive
unchanged; the lossless map reconstructs the original captured packet.
No new request is issued and no historical ledger is counted twice.
Exact SHA-pinned legacy profiles preserve earlier normalized packets,
including their previous negative dispositions. Source, scientific,
native-original, date/party and publication gates remain false.

## 15. Independently published Govbot legislative archives

State legislatures, originating legislative text; Govbot and the
`govbot-data` project, independent archival collection. Project:
https://github.com/chihacknight/govbot. Inspected archives:
https://github.com/govbot-data/de-legislation,
https://github.com/govbot-data/mt-legislation and
https://github.com/govbot-data/nh-legislation. Accessed 2026-10-23.
GitHub is the delivery intermediary, not the legislative author; rights
are not inferred from repository hosting.

The exact-original-session inventory inspects all 38 states with remaining
gaps through 107 logical `gh` invocations. It identifies thirty original
state/session/typed-number leads in three exact sessions, not a complete
national bill-text census. Targeted capture closes after **161 total logical
invocations**, including the retained failed prefixes; discovery's 107 are
separate. Physical HTTP retries/exchanges are not inferred from CLI counts.
The closed source, retaining 153 unique Git-verified blobs / 10,195,082 bytes:
`data/processed/govbot-exact-original-lead-source-20261023-v3/`, manifest
`d5ab101b125c8dcf2ee75981b5938b841bea267d645dace9b5cb5378a68643dd`.

The immutable DE 153 session tree is
`9dd4353ce7b94f45d5223627d3ffb47416526408`; MT 2025 is
`84690ba2d3f4aefeaf839054fa1743bccd8781b2`. DE and NH have complete
received recursive structure. The MT recursive response is truncated;
complete nonrecursive root/bills and selected-bill branches establish
membership of the selected records, not receipt of every MT session blob.
Git symlinks are preserved structurally and never followed or extracted.

Corrected offline normalization recovers **three original MT 2025 contexts /
76 PDF file/version occurrences / 152 complete paired-reader views /
9,888,817 characters**:
`data/processed/govbot-exact-original-documents-20261023-v2/`, manifest
`8edb6c6de1f0af693092ba5d67d09ab0780898d304843f7ad14776241a1431d4`.
Both readers retain every one of 2,263 pages across all 81 received PDFs.
All 83 provider versions, 166 files, thirty contexts, five rejected PDFs
and exact same-stem published extraction witnesses remain accounted for.
Provider-generated extraction prologues are not appended to PDF policy
inputs. Own formal resolution headings, 69th Legislature and printed 2025
are required; LC abbreviations never substitute for the formal number.

The original v1 gate genuinely misread three enrolled SJ 1 file occurrences:
the own typed `SJ 1` is on page one, Senate-origin certification on page 32
and long-form `SENATE JOINT RESOLUTION NO. 1` on page 33. The same raw PDF
SHA-256, `80243766a01264287aaa459b0624ce313c8b09bbbad13f126cabd3f2b8664588`,
is retained under three provider versions; these are not three new laws or
contexts. A narrow enrolled profile corroborates all those own spans in both
complete readers, recognizes only the two actual terminal page types, and
retains all 33 pages rather than relaxing ordinary-page identity or trimming
certificates from model input. Six views / 426,810 characters are restored
with zero requests. All 146 original v1 view rows and all source/reader bytes
remain unchanged. The exact v1 manifest
`dfd21e9aa3651d1afa158d42c526a25560b7c21069682296c78c51b94fb49802`
selects the old profile/archived producer and reproduces its original
rejections; it is not silently rewritten. Full correction receipt:
`data/processed/govbot-enrolled-correction-20261023-v1.json`.

DE's empty version/file lists and NH's conflicting own printed years remain
unavailable. Three drafts and two amendment-context documents remain
quarantined. No original state
publisher URL is requested, source stop reopened, annual/session alias
inferred or native/original/filing-time/party/rights/human-accuracy gate closed.

## 16. Independent published AI-legislation research corpus

> Bhargava, H. K.; Soliman, M. (2026). *The Structure of U.S. State AI Policy:
> Evidence from a Multi-Dimensional Bill Classification* [Research dataset
> and accompanying materials]. Zenodo record 20781731.
> https://zenodo.org/records/20781731. Accessed 2026-10-23.

The authors are credited for compilation and enrichment, NCSL for the
underlying collected legislative metadata/text, LegiScan for the authors'
sponsor enrichment, and the state legislatures for the legislative texts.
The Zenodo record advertises CC BY 4.0; that observation does not certify
all underlying material's rights or authorize production integration.

A separately bounded capture retains robots, the actual publication page
and its explicitly linked `Final_Database_10.csv` in **three GETs**:
`data/processed/independent-ai-bill-corpus-source-20261023-v1/`, manifest
`27e124cd8f99e58cb50e9e33b9036504fc3eb96a981394991d091441e9cc1ce1`.
The complete 51,825,469-byte CSV has SHA-256
`188aba4f4e50c6d0acb3532d143b9a81d9cccdf7c0729ba7ded6410399eff232`;
its advertised and calculated MD5 are
`397a13c53e719e64e52725e7995fd8ca`. It preserves all **2,571 rows / 29
fields**, including original provider records outside the study. None of
the separately linked human-annotator files is requested.

The authors' construction document is independently retained from the
actual published `v1.0.1-rp-submission` release:
https://github.com/marksoliman3/Bill_Analyst_Agent.
Its immutable Git blob is `3362595ae231a576061cd917ba21485b43c97551`,
31,521 bytes, verified with Git's blob-object hash. It documents source
cleaning, a 1,500–40,000-character length filter and describes provider `Year`
as derived from version metadata. A complete retained-row audit nevertheless
finds **74 of 2,571** `Year` values disagreeing with the literal `Version_Date`
year. For example, RI H 5866 preserves provider `Year=2024`,
`Version_Date=03/01/2023` and the body's own January 2023 session; the unchanged
original 2023 context, not a guessed 2024 alias, is recovered. No source date
is silently repaired. Full discrepancy inventory:
`data/published-ai-corpus-provider-year-audit-20261023-v1.json`.
These metadata descriptions are not native-completeness or canonical
filing/session certifications. Original source URLs and all unknowns remain
unchanged; NCSL, LexisNexis and LegiScan endpoints are not requested here.

Strict own printed state/session/type/number/body checks recover **27
original missing contexts across thirteen states / 27 published bodies /
228,679 policy characters**:
`data/processed/published-ai-corpus-documents-20261023-v2/`, manifest
`207702b7bf4bdaac9e8fc61a55d385beb25edf55adef5c963d8c6e9a765aef4e`.
Every original record/field, duplicate, rejected row and exact
publisher-prologue/body character boundary is preserved. `Bill_Text` alone
supplies policy bodies; the source's AI `bill_extracts`, `summary`,
`analyst_results`, scores and party/control fields are neither classifier
inputs nor gold labels. No source-original, filing-time, party, human-review,
scientific or publication approval follows from this recovery.

The v1 packet's true uncertainty observation had an ambiguous name ending
in `_certified`, so the conservative comparison guard refused it. V2 renames
only that observation to `source_cleaning_and_native_edition_uncertainty_preserved`;
all 27 bodies, IDs, dates, unknowns, source records and real false approval
flags remain identical. The comparison guard is not relaxed. The exact
historical v1 manifest
`114e8fdc585a52d469a0df1469a19e5b78f788aa9163dbdb3c1d0d47df951cd2`
selects its archived producer and old metadata profile without rewriting
any original packet or completed inference. Correction receipt:
`data/processed/published-corpus-observation-correction-20261023-v1.json`.

## 17. External human-benchmark discovery, not acquired reference labels

The Florida Policy Agendas official dataset catalogue,
https://www.comparativeagendas.net/project/florida/datasets, and published
methodological descriptions identify a potentially useful historical
human-coded collection. They do not establish a verified 2023–2024 benchmark
or a row-level direct crosswalk to this project's taxonomy.

A metadata-only capture stops at an actual MinIO robots403 after **two
GETs**, before any CSV body, CSV field header or reference-label acquisition:
`data/processed/florida-policy-agendas-benchmark-discovery-20261023-v1/`,
manifest `f91ba05e6be96d76649e4a35507f7cab7ae3bfda56d4b5ad9e428e984e4b29cd`.
That origin remains closed; no direct-file or alternate-endpoint workaround
is used. The bounded independent-archive follow-up finds a legacy Florida
codebook pointer blocked by Dropbox robots and an author-documented Harvard
collection stopped by a robot challenge. Those stops also remain closed.
The research-agent report is preserved in
`data/external-human-benchmark-discovery-20261023-v1-followup.json`,
explicitly as a reported discovery result rather than a reconstructed
transport ledger.

No external reference labels are acquired or scored, no AI annotation is
promoted to human gold, and the frozen human packet, evaluation plan,
training labels, checkpoints and inference policy remain unchanged.
This is a bounded unresolved discovery, not evidence that an independent
human benchmark does not exist.

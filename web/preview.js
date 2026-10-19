"use strict";
const state = document.getElementById("state");
const party = document.getElementById("party");
const collection = document.getElementById("collection");
const status = document.getElementById("evidence-status");
const evidence = document.getElementById("evidence");
const pagination = document.getElementById("pagination");
const previous = document.getElementById("previous");
const next = document.getElementById("next");
let records = [];
let page = 0;
let generation = 0;
const pageSize = 10;

function render() {
  evidence.replaceChildren();
  const begin = page * pageSize;
  for (const row of records.slice(begin, begin + pageSize)) {
    const article = document.createElement("article");
    const heading = document.createElement("h3");
    const recovery = collection.value === "recovery";
    heading.textContent = recovery
      ? `${row.state} / ${row.party} — ${row.capture_id}`
      : `${row.state} / ${row.party} / ${row.year} — ${row.filename}`;
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = recovery
      ? `${row.retrieval_status.replaceAll("_", " ")} · Operative version unresolved · Not admitted to analysis`
      : "Historical archive · Not classified by ModernBERT";
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Read recovered source text";
    const text = document.createElement("div");
    text.className = "source-text";
    text.tabIndex = 0;
    text.textContent = recovery
      ? (row.retrieval_status === "retrieval_failed"
        ? "Retrieval failed. No response body or source text was retained."
        : (row.extracted_text || "Response body retained, but standard extraction produced no text."))
      : row.text;
    details.append(summary, text);
    const source = document.createElement("a");
    source.href = recovery ? row.url : "https://doi.org/10.7910/DVN/KNOSHL";
    source.textContent = recovery ? row.url : "Publisher archive and provenance";
    article.append(heading, note, source, details);
    if (recovery) {
      const identity = document.createElement("p");
      identity.className = "note";
      identity.textContent = `${row.extraction_method} · Body SHA-256: ${row.source_sha256 || "none retained"}`;
      article.append(identity);
      const alternatives = row.alternate_extractions
        || (row.alternate_ocr ? [{ ...row.alternate_ocr, kind: "ocr" }] : []);
      for (const alternate of alternatives) {
        const detail = document.createElement("details");
        const label = document.createElement("summary");
        const labels = {
          docx_main_document: "Read alternate DOCX main-document text (no layout, images or other XML parts; original extraction preserved above)",
          pdf_native_blocks: "Read alternate native PDF blocks (not OCR; reading order uncertified; original extraction preserved above)",
          ocr: "Read alternate OCR (uncertified transcription; original extraction preserved above)",
        };
        if (!Object.hasOwn(labels, alternate.kind)) {
          throw new Error(`Unsupported alternate extraction kind: ${alternate.kind}`);
        }
        label.textContent = labels[alternate.kind];
        const transcription = document.createElement("div");
        transcription.className = "source-text";
        transcription.tabIndex = 0;
        transcription.textContent = alternate.extracted_text;
        detail.append(label);
        const provenance = alternate.input_disposition || alternate;
        if (alternate.kind === "pdf_native_blocks") {
          const warning = document.createElement("p");
          warning.className = "note";
          const reviewed = provenance.visually_checked_pages.join(", ") || "none";
          warning.textContent = `${provenance.page_count} physical PDF pages. Visually checked physical pages: ${reviewed}. Visual checks do not certify full-document reading order. No original text was replaced.`;
          detail.append(warning);
        }
        if (alternate.kind === "ocr"
            && provenance.selection_reason === "native_extraction_reported_incomplete_font") {
          const warning = document.createElement("p");
          warning.className = "note";
          warning.textContent = "The native PDF extractor reported incomplete font output. Its unchanged text above is incomplete; this OCR remains an uncertified alternative.";
          detail.append(warning);
        }
        if (alternate.kind === "ocr") {
          const runtime = document.createElement("p");
          runtime.className = "note";
          const version = provenance.tesseract_version ?? provenance.ocr_version;
          runtime.textContent = typeof version === "string"
            ? `OCR runtime: ${version}` : "OCR runtime: not recorded on this extraction row.";
          detail.append(runtime);
        }
        detail.append(transcription);
        article.append(detail);
      }
    }
    evidence.append(article);
  }
  pagination.hidden = records.length <= pageSize;
  previous.disabled = page === 0;
  next.disabled = begin + pageSize >= records.length;
  status.textContent = records.length
    ? `Documents ${begin + 1}–${Math.min(begin + pageSize, records.length)} of ${records.length}.`
    : `No ${collection.value === "recovery" ? "captures in these selected recovery packets" : "recovered historical documents"} for this selection. This is not publication absence; operative coverage remains unresolved.`;
}

async function update() {
  const request = ++generation;
  page = 0;
  records = [];
  evidence.replaceChildren();
  pagination.hidden = true;
  let visible = 0;
  for (const row of document.querySelectorAll("#coverage tbody tr")) {
    row.hidden = Boolean((state.value && row.dataset.state !== state.value)
      || (party.value && row.dataset.party !== party.value));
    if (!row.hidden) visible++;
  }
  document.getElementById("row-count").textContent = `${visible} organization rows`;
  if (!state.value) {
    status.textContent = "Choose a state; complete records are also available below.";
    return;
  }
  status.textContent = "Loading source records…";
  try {
    const parties = party.value ? [party.value] : ["D", "R"];
    const groups = await Promise.all(parties.map(async (code) => {
      const prefix = collection.value === "recovery" ? "recovery-" : "";
      const response = await fetch(`evidence/${prefix}${state.value}-${code}.json`);
      if (!response.ok) throw new Error(`Source partition unavailable (HTTP ${response.status}).`);
      return response.json();
    }));
    if (request !== generation) return;
    records = groups.flat().sort(collection.value === "recovery"
      ? (a, b) => a.capture_id.localeCompare(b.capture_id, undefined, { numeric: true })
      : (a, b) => b.year - a.year || a.filename.localeCompare(b.filename));
    render();
  } catch (error) {
    if (request !== generation) return;
    status.textContent = `Evidence could not be loaded: ${error.message} Use the full download or check the local build.`;
  }
}

state.addEventListener("change", update);
party.addEventListener("change", update);
collection.addEventListener("change", update);
document.getElementById("filters").addEventListener("submit", event => event.preventDefault());
previous.addEventListener("click", () => { page--; render(); });
next.addEventListener("click", () => { page++; render(); });

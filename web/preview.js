"use strict";
const state = document.getElementById("state");
const party = document.getElementById("party");
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
    heading.textContent = `${row.state} / ${row.party} / ${row.year} — ${row.filename}`;
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = "Historical archive · Not classified by ModernBERT";
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Read recovered source text";
    const text = document.createElement("div");
    text.className = "source-text";
    text.tabIndex = 0;
    text.textContent = row.text;
    details.append(summary, text);
    const source = document.createElement("a");
    source.href = "https://doi.org/10.7910/DVN/KNOSHL";
    source.textContent = "Publisher archive and provenance";
    article.append(heading, note, source, details);
    evidence.append(article);
  }
  pagination.hidden = records.length <= pageSize;
  previous.disabled = page === 0;
  next.disabled = begin + pageSize >= records.length;
  status.textContent = records.length
    ? `Documents ${begin + 1}–${Math.min(begin + pageSize, records.length)} of ${records.length}.`
    : "No recovered historical documents for this selection. Contemporary evidence remains unresolved.";
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
      const response = await fetch(`evidence/${state.value}-${code}.json`);
      if (!response.ok) throw new Error(`Source partition unavailable (HTTP ${response.status}).`);
      return response.json();
    }));
    if (request !== generation) return;
    records = groups.flat().sort((a, b) => b.year - a.year
      || a.filename.localeCompare(b.filename));
    render();
  } catch (error) {
    if (request !== generation) return;
    status.textContent = `Evidence could not be loaded: ${error.message} Use the full download or check the local build.`;
  }
}

state.addEventListener("change", update);
party.addEventListener("change", update);
document.getElementById("filters").addEventListener("submit", event => event.preventDefault());
previous.addEventListener("click", () => { page--; render(); });
next.addEventListener("click", () => { page++; render(); });

"use strict";

function filterEvidence(rows, query) {
  const needle = query.trim().toLocaleLowerCase();
  function literalText(value) {
    if (value !== null && typeof value === "object") {
      return Object.entries(value).map(([key, item]) => `${key}\n${literalText(item)}`).join("\n");
    }
    return String(value);
  }
  return needle ? rows.filter(row => literalText(row).toLocaleLowerCase().includes(needle)) : rows;
}

function fullQueryJSONL(rows) {
  return rows.map(row => JSON.stringify(row) + "\n").join("");
}

function safeSourceURL(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

if (typeof module !== "undefined") module.exports = { filterEvidence, fullQueryJSONL, safeSourceURL };

if (typeof document !== "undefined") {
  const state = document.getElementById("state");
  const collection = document.getElementById("collection");
  const party = document.getElementById("party");
  const query = document.getElementById("query");
  const status = document.getElementById("evidence-status");
  const evidence = document.getElementById("evidence");
  const download = document.getElementById("download-query");
  const pagination = document.getElementById("pagination");
  const previous = document.getElementById("previous");
  const next = document.getElementById("next");
  const pageSize = 10;
  let records = [], matches = [], page = 0, generation = 0, loading = false, loaded = false;

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function sourceText(label, value) {
    const details = element("details");
    const text = element("div", value === null ? "Not retained / unknown." : value, "source-text");
    text.tabIndex = 0;
    details.append(element("summary", label), text);
    return details;
  }

  function render() {
    evidence.replaceChildren();
    const begin = page * pageSize;
    for (const row of matches.slice(begin, begin + pageSize)) {
      const article = element("article");
      const bill = row.source_type === "bill_metadata";
      article.append(element("h3", bill
        ? `${row.state} / ${row.identifier} / ${row.session_identifier} — ${row.title ?? "No title"}`
        : `${row.state} / ${row.party} — ${row.record_kind}`));
      article.append(element("p", bill
        ? `View: ${row.view_id} · Bill: ${row.bill_id} · Abstract: ${row.abstract_id ?? "none"}`
        : `Record: ${row.record_id} · Source: ${row.source_sha256 ?? "none retained"}`, "note record-id"));
      if (bill) {
        const context = row.bill_context;
        const cohortNote = {
          source_coded_event: "Source-coded filing/introduction candidate, not a certified policy.",
          native_reported_date_candidate: "Native-reported-date-only candidate, not a source-coded bill date.",
          description_stated_event_candidate: "Conditional self-description candidate, not a source-coded bill date.",
        }[row.cohort_scope];
        article.append(element("p",
          `Cohort: ${row.cohort_scope} · ${row.metadata_tier} · `
          + `${row.multiple_abstract_variants ? "Different abstract variants retained" : "No different abstract variants recorded"}. `
          + `${cohortNote} `
          + "Authorship/time alignment unverified. Model input, filing-time certification, training and analytical admission: false.",
          "note"));
        article.append(element("p",
          `Source introduction: ${context.source_introduction_date || "unknown"} · `
          + `Source filing: ${context.source_filing_date || "unknown"} · `
          + `Native-date candidate: ${context.native_introduction_date || "unknown"} · `
          + `Indexed native views: ${context.n_indexed_native_views ?? "unknown (state packet not registered)"}. `
          + "Index only; no native document text/PDFs included.", "note"));
        article.append(sourceText("Read full raw title", row.title ?? null));
        article.append(sourceText("Read full source abstract / summary (unverified alignment)", row.abstract));
        article.append(sourceText("Read full source abstract note", row.abstract_note));
        article.append(sourceText("Read full title + abstract metadata view (not native text)", row.text));
      } else {
        article.append(element("p",
          `${row.retrieval_status ?? row.availability ?? "Retained evidence view"} · `
          + `Date dispositions: ${row.cycle_date_dispositions.join(", ")} · `
          + `Metadata year: ${row.retained_metadata_year ?? "unknown"} (${row.metadata_year_disposition}). `
          + "Applicability unresolved; adoption certification, human gold, training and analytical admission: false. "
          + "GPT-assisted source reviews are advisory.", "note"));
        const url = safeSourceURL(row.url);
        if (url) {
          const link = element("a", "Original source URL (external; not fetched by this preview)");
          link.href = url;
          link.rel = "noreferrer noopener";
          article.append(link);
        }
        article.append(sourceText("Read complete retained source text", row.extracted_text));
      }
      const provenance = element("details");
      const raw = element("pre", JSON.stringify(row, null, 2), "provenance-text");
      raw.tabIndex = 0;
      provenance.append(element("summary", "Inspect complete record, provenance and unchanged flags"), raw);
      article.append(provenance);
      evidence.append(article);
    }
    pagination.hidden = matches.length <= pageSize;
    previous.disabled = page === 0;
    next.disabled = begin + pageSize >= matches.length;
    document.getElementById("page-label").textContent =
      `Page ${page + 1} of ${Math.max(1, Math.ceil(matches.length / pageSize))}`;
    download.disabled = loading || !loaded;
    download.textContent = `Download all ${matches.length.toLocaleString()} query matches (full-text JSONL)`;
    const identities = new Set(matches.map(row =>
      row.source_type === "bill_metadata" ? row.bill_id : `${row.state}/${row.party}`));
    status.textContent = matches.length
      ? `Views ${begin + 1}–${Math.min(begin + pageSize, matches.length)} of ${matches.length.toLocaleString()} matching views`
        + (collection.value === "bill_metadata" ? ` · ${identities.size.toLocaleString()} distinct candidate bill contexts.`
          : " · Views are not certified platforms or distinct documents.")
      : "No matching views in this saved selection. This is not evidence of zero activity or publication absence.";
  }

  function search() {
    page = 0;
    matches = filterEvidence(records, query.value);
    render();
  }

  function coverage() {
    const platform = collection.value === "platform";
    party.disabled = !platform || state.value === "outside";
    const selected = [...document.querySelectorAll("#state-coverage tbody tr")]
      .find(row => row.dataset.state === state.value);
    document.getElementById("selection-scope").textContent = !platform && selected
      ? (Number(selected.dataset.contexts) === 0
        ? `${state.value}: date/cohort evidence unavailable in this cycle candidate dataset. `
          + "No source-coded filing/introduction, reviewed literal candidate or registered native-date candidate is available here. "
          + `${selected.dataset.widerContexts} retained wider-history source contexts are outside this candidate download. `
          + "An empty query download is not zero legislative activity or zero policies."
        : `${state.value}: ${Number(selected.dataset.contexts).toLocaleString()} saved cycle candidate contexts. `
          + "Native-only and description-only candidates are distinct from source-coded dates. "
          + "This is not a certified denominator or full native-text corpus.")
      : platform
        ? "Platform evidence views overlap; unknown dates and unresolved applicability are not publication absence."
        : "Choose a state to inspect its saved cycle evidence scope; a missing cohort is not zero activity.";
    for (const [table, label, count] of [
      ["state-coverage", "state", "state-count"], ["org-coverage", "organization", "org-count"],
    ]) {
      let visible = 0;
      for (const row of document.querySelectorAll(`#${table} tbody tr`)) {
        row.hidden = Boolean((state.value && row.dataset.state !== state.value)
          || (table === "org-coverage" && platform && party.value && row.dataset.party !== party.value));
        if (!row.hidden) visible++;
      }
      document.getElementById(count).textContent = `${visible} ${label} rows`;
    }
  }

  async function update() {
    const request = ++generation;
    records = [];
    matches = [];
    page = 0;
    loading = true;
    loaded = false;
    evidence.replaceChildren();
    pagination.hidden = true;
    download.disabled = true;
    coverage();
    if (!state.value || (state.value === "outside" && collection.value !== "platform")) {
      loading = false;
      status.textContent = state.value === "outside"
        ? "Outside-organization records belong to Platform evidence views; select that source type."
        : "Choose a state; no source records loaded.";
      return;
    }
    status.textContent = "Loading complete saved source records…";
    try {
      const names = collection.value === "bill_metadata" ? [`bills-${state.value}`]
        : state.value === "outside" ? ["platform-outside"]
          : (party.value ? [party.value] : ["D", "R"]).map(code => `platform-${state.value}-${code}`);
      const groups = await Promise.all(names.map(async name => {
        const response = await fetch(`evidence/${name}.jsonl`);
        if (!response.ok) throw new Error(`Partition unavailable (HTTP ${response.status})`);
        const body = await response.text();
        return body.split("\n").filter(line => line.trim()).map(line => JSON.parse(line));
      }));
      if (request !== generation) return;
      records = groups.flat();
      loading = false;
      loaded = true;
      search();
    } catch (error) {
      if (request !== generation) return;
      loading = false;
      status.textContent = `Evidence could not be loaded: ${error.message}. Check this build or use complete table downloads.`;
    }
  }

  document.getElementById("filters").addEventListener("submit", event => {
    event.preventDefault();
    if (!loading) search();
  });
  for (const control of [state, collection, party]) control.addEventListener("change", update);
  previous.addEventListener("click", () => { page--; render(); });
  next.addEventListener("click", () => { page++; render(); });
  download.addEventListener("click", () => {
    if (loading || !loaded) return;
    const blob = new Blob([fullQueryJSONL(matches)], { type: "application/x-ndjson;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = element("a");
    link.href = url;
    link.download = `${collection.value}-${state.value}-${party.disabled ? "all" : party.value || "both"}-query-fulltext.jsonl`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
}

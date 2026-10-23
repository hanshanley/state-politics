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

async function* savedJSONLLines(names) {
  for (const name of names) {
    const response = await fetch(`evidence/${name}.jsonl`);
    if (!response.ok) throw new Error(`Partition unavailable (HTTP ${response.status})`);
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let remaining = "";
    try {
      while (true) {
        const { value, done } = await reader.read();
        remaining += decoder.decode(value, { stream: !done });
        let end;
        while ((end = remaining.indexOf("\n")) !== -1) {
          const line = remaining.slice(0, end);
          remaining = remaining.slice(end + 1);
          if (line.trim()) yield line;
        }
        if (done) break;
      }
      if (remaining.trim()) yield remaining;
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
  }
}

async function fullQueryBlob(names, query, receiptStatus, expectedCount) {
  const lines = savedJSONLLines(names), encoder = new TextEncoder();
  let count = 0;
  const stream = new ReadableStream({
    async pull(controller) {
      try {
        while (true) {
          const { value, done } = await lines.next();
          if (done) {
            if (count !== expectedCount) throw new Error("Complete query count changed during export");
            controller.close();
            return;
          }
          const row = JSON.parse(value);
          if (!filterEvidence([row], query).length
              || (receiptStatus && row.receipt_status !== receiptStatus)) continue;
          count++;
          // Keep the saved line, including integers beyond Number's precision, unchanged.
          controller.enqueue(encoder.encode(value + "\n"));
          return;
        }
      } catch (error) {
        await lines.return();
        controller.error(error);
      }
    },
    cancel() { return lines.return(); },
  }, { highWaterMark: 1 });
  // Native Blob storage consumes the stream; no all-record JS string/parts array is retained.
  return new Response(stream, {
    headers: { "Content-Type": "application/x-ndjson;charset=utf-8" },
  }).blob();
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

if (typeof module !== "undefined") {
  module.exports = { filterEvidence, fullQueryJSONL, fullQueryBlob, safeSourceURL };
}

if (typeof document !== "undefined") {
  const state = document.getElementById("state");
  const collection = document.getElementById("collection");
  const party = document.getElementById("party");
  const query = document.getElementById("query");
  const receiptStatus = document.getElementById("receipt-status");
  const status = document.getElementById("evidence-status");
  const evidence = document.getElementById("evidence");
  const download = document.getElementById("download-query");
  const pagination = document.getElementById("pagination");
  const previous = document.getElementById("previous");
  const next = document.getElementById("next");
  const pageSize = 10;
  let records = [], matches = [], loadedNames = [], page = 0, generation = 0;
  let loading = false, loaded = false, exporting = false, appliedQuery = "", appliedReceiptStatus = "";

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
      const sessionText = row.source_type === "native_session_text";
      const native = row.source_type === "native_text" || sessionText;
      const receipt = row.source_type === "source_receipt";
      const snapshot = row.source_type === "snapshot_text";
      const corpus = row.source_type === "research_corpus_text";
      const archive = row.source_type === "archive_text";
      const crossContext = archive
        && row.context_relation?.kind === "same_legislature_exact_existing_document_pointer";
      article.append(element("h3", receipt
        ? `${row.state} / ${row.identifier} — source-receipt observation only`
        : sessionText
          ? `${row.state} / ${row.identifier} / ${row.session_identifier} — publisher-session source only`
        : bill || native || snapshot || corpus || archive
          ? `${row.state} / ${row.identifier} / ${row.session_identifier} — ${row.title ?? "No title"}`
        : `${row.state} / ${row.party} — ${row.record_kind}`));
      article.append(element("p", receipt
        ? `Action: ${row.source_action.action_id} · Bill: ${row.bill_id} · Session: ${row.source_bill.session_identifier}`
        : snapshot
        ? `View: ${row.view_id} · Bill: ${row.bill_id} · Retained provider snapshot, not an introduced-version certification`
        : corpus
        ? `View: ${row.view_id} · Bill: ${row.bill_id} · Independent cleaned research text, not publisher-certified`
        : archive
        ? `View: ${row.view_id} · Bill: ${row.bill_id} · Archive: ${row.archive_provider} · Not publisher-version certification`
        : bill || native
        ? `View: ${row.view_id} · Bill: ${row.bill_id} · `
          + (native ? `Native context: ${row.context_id}` : `Abstract: ${row.abstract_id ?? "none"}`)
        : `Record: ${row.record_id} · Source: ${row.source_sha256 ?? "none retained"}`, "note record-id"));
      if (receipt) {
        const observation = row.observation;
        article.append(element("p",
          `Receipt status: ${row.receipt_status === "unique_origin_date_agreeing"
            ? "unique origin / date-agreeing source receipt"
            : "unresolved receipt observation — no date repaired"}. `
          + "Receipt is not introduction, filing, native evidence or eligible-cycle admission. "
          + "This separate observation is not added to the active candidate, native or model cohort.",
          "note receipt-observation"));
        article.append(element("p",
          `Source action date (unaltered): ${row.source_action.date} · `
          + `Literal receipt date: ${observation.literal_calendar_date ?? "unresolved"} · `
          + `Agreement: ${observation.date_agreement}. Both original dates are retained.`,
          "note receipt-dates"));
        article.append(element("p",
          `Source action organization: ${row.source_action.organization_id} / ${row.source_action.chamber} · `
          + `Originating organization: ${row.source_bill.from_organization_id} / ${row.source_bill.originating_chamber} · `
          + `Identity status: ${observation.origin_identity_status}.`, "note"));
        article.append(sourceText("Read original receipt description (unaltered)", row.source_action.description));
        article.append(sourceText("Inspect original action, raw date and literal date spans", JSON.stringify({
          source_action: row.source_action, raw_event_date_span: row.raw_event_date_span,
          literal_spans: JSON.parse(observation.receipt_spans_json),
          negative_flags: JSON.parse(observation.negative_flags_json),
        }, null, 2)));
        article.append(sourceText("Inspect all original bill metadata and source context fields",
          JSON.stringify(row.source_context, null, 2)));
      } else if (archive) {
        article.append(element("p",
          (crossContext
            ? `Retained source session ${row.context_relation.source_session_identifier}; `
              + `candidate session ${row.context_relation.target_session_identifier}. `
              + "Exact existing document pointers link distinct annual contexts of the same legislature, "
              + "not session aliases or a canonical bill merge. This is not evidence of target-year "
              + "filing, introduction, reintroduction, carryover or pending status. "
            : "Exact printed state, session and own bill identity match an existing candidate. ")
          + "Provider alternatives and combined substitutes are not extra bills. Complete "
          + "source metadata and original source-member references remain available. "
          + "No dates, party, introduced version, human gold or model approval are inferred. "
          + (row.archive_generated_prologue_preserved
            ? "This full string includes the archive's existing machine-generated extraction prologue, not our added summary."
            : "This is the complete retained source extraction, without an added summary."),
          "note archive-observation"));
        article.append(sourceText("Read complete archived bill text (unaltered)", row.text));
        article.append(sourceText("Inspect printed identity, source version and all original metadata",
          JSON.stringify({source_identity: row.source_identity, source_version: row.source_version,
            source_record: row.source_record, source_members: row.source_members,
            context_relation: row.context_relation,
            original_source_context: row.original_source_context,
            original_target_context: row.original_target_context,
            archive_provider: row.archive_provider, archive_commit: row.archive_commit,
            archive_country_git_tree: row.archive_country_git_tree}, null, 2)));
      } else if (corpus) {
        article.append(element("p",
          "Joined by printed state, session and bill identity to an existing candidate. "
          + "This independently published cleaned text is not a certified publisher-original "
          + "or introduced version. Source summaries are not human gold or predictions; "
          + "no filing date, party affiliation, token plan or model approval is inferred.",
          "note corpus-observation"));
        if (row.source_ancestry) {
          article.append(element("p",
            row.source_ancestry.length
              ? `${row.source_ancestry.length} exact original keyed-record reference(s) retained. `
                + "Original dataset keys and source filenames are visible in complete provenance; "
                + "keys are not interpreted as external bill IDs."
              : "No keyed ancestor metadata is supplied for this source; this is not a claim that none exists.",
            "note"));
        }
        article.append(sourceText("Read complete research-corpus text (unaltered source string)",
          row.source_record.text));
        article.append(sourceText("Inspect printed identity evidence and source record",
          JSON.stringify({source_identity: row.source_identity, source_record: row.source_record,
            source_file: row.source_file, source_row_ordinal: row.source_row_ordinal,
            source_file_sha256: row.source_file_sha256, dataset: row.dataset,
            dataset_revision: row.dataset_revision}, null, 2)));
      } else if (snapshot) {
        article.append(element("p",
          `Retained nonempty text: ${row.snapshot.has_nonempty_raw_text} · `
          + `Version-link binding: ${row.snapshot.version_binding_status}. `
          + "This is the provider-selected search text in the retained dump snapshot, not "
          + "necessarily an original or introduced version. Error flags, missing text and "
          + "unresolved versions remain visible; source text is never silently replaced.",
          "note snapshot-observation"));
        article.append(element("p",
          `Provider flags (unaltered): ${JSON.stringify(row.snapshot.provider_flags)}. `
          + "No introduction date, filing-time party, token plan, model prediction, training "
          + "or analytical approval is inferred from this text.", "note"));
        const url = safeSourceURL(row.snapshot.source_url);
        if (url) {
          const link = element("a", "Selected version URL (external; not fetched by this preview)");
          link.href = url;
          link.rel = "noreferrer noopener";
          article.append(link);
        }
        article.append(sourceText("Read complete retained snapshot raw_text (unaltered)",
          row.source_record.raw_text));
        article.append(sourceText("Inspect complete selected version/link binding",
          JSON.stringify(row.source_version, null, 2)));
      } else if (bill) {
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
          + "This count is an index, not full native text in this metadata view; use the separate native source if included.",
          "note"));
        if (row.token_plan) {
          const plan = row.token_plan;
          article.append(element("p",
            `Verified tokenization planning: ${plan.n_input_tokens.toLocaleString()} source tokens · `
            + `${plan.n_windows.toLocaleString()} windows · `
            + `${plan.n_unique_covered_tokens.toLocaleString()} unique covered tokens · `
            + `${plan.n_overlap_token_positions.toLocaleString()} overlapping token positions · `
            + `${plan.n_discarded_tokens} discarded tokens. `
            + `Model-input window lengths: ${plan.window_model_input_lengths.join(", ")} (maximum 1,024). `
            + "Original source token fields remain null. Planning is not predictions, certainty, model admission "
            + "or filing-time eligibility; all approval flags remain false.", "note token-plan"));
        }
        article.append(sourceText("Read full raw title", row.title ?? null));
        article.append(sourceText("Read full source abstract / summary (unverified alignment)", row.abstract));
        article.append(sourceText("Read full source abstract note", row.abstract_note));
        article.append(sourceText("Read full title + abstract metadata view (not native text)", row.text));
      } else if (native) {
        const context = row.native_context;
        if (sessionText) {
          article.append(element("p",
            `${row.scope_label}. This exact canonical match is not in the metadata candidate cohort. `
            + "No date was required or inferred; retained printed/session dates are not filing dates. "
            + "No token planning or model statistics are supplied.", "note session-observation"));
        }
        article.append(element("p",
          `Native reader/source: ${row.reader} · Packet root: ${row.packet_root} · `
          + `Exact native context: ${row.context_id} · Join: ${context.canonical_join_basis}. `
          + "Reader alternatives and repeated source roots are views, not extra bills.", "note"));
        article.append(element("p",
          `Retained native status/stage: ${context.packet_status ?? "unresolved"} · `
          + `Native identifier: ${context.native_identifier} · `
          + `Native-reported date: ${context.native_introduction_date || "unknown"} · `
          + `Date disposition: ${context.date_evidence_status ?? context.native_window_disposition} · `
          + `Source introduction: ${(sessionText ? context : row.bill_context).source_introduction_date || "unknown"} · `
          + `Original source window disposition: ${context.window_disposition ?? "unknown"}. `
          + "Native identity, original/introduced stage, filing-time alignment and legal/markup semantics "
          + "are not certified. Model input, filing-time certification, training and analytical admission: false.",
          "note"));
        for (const [label, source] of [
          ["Native context caveats and negative observations", context],
          ["Original native source caveats", row.source_record],
          ["Original native context caveats", row.source_context_record],
        ]) {
          const caveats = Object.fromEntries(Object.entries(source).filter(([key]) =>
            /negative|date|identity|stage|version|status|semantics|certif|eligible|approv|admission|input_tier|construction|source_kind/i.test(key)));
          article.append(sourceText(label, JSON.stringify(caveats, null, 2)));
        }
        article.append(sourceText("Read complete retained native source text (no summary prepended)", row.text));
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
    download.disabled = loading || !loaded || exporting;
    download.textContent = `Download all ${matches.length.toLocaleString()} query matches (full-text JSONL)`;
    const identities = new Set(matches.map(row =>
      row.source_type !== "platform" ? row.bill_id : `${row.state}/${row.party}`));
    status.textContent = matches.length
      ? `Views ${begin + 1}–${Math.min(begin + pageSize, matches.length)} of ${matches.length.toLocaleString()} matching views`
        + (collection.value === "source_receipt"
          ? ` · ${identities.size.toLocaleString()} distinct observed source bill contexts; not cycle candidates.`
          : collection.value === "native_session_text"
            ? ` · ${new Set(matches.map(row => `${row.packet_root}/${row.context_id}`)).size.toLocaleString()} source references`
              + ` · ${identities.size.toLocaleString()} unique canonical bill IDs; OUTSIDE candidate date cohort, not admissions.`
          : collection.value !== "platform" ? ` · ${identities.size.toLocaleString()} distinct candidate bill contexts.`
          : " · Views are not certified platforms or distinct documents.")
      : "No matching views in this saved selection. This is not evidence of zero activity or publication absence.";
  }

  function search() {
    page = 0;
    appliedQuery = query.value;
    appliedReceiptStatus = collection.value === "source_receipt" ? receiptStatus.value : "";
    matches = filterEvidence(records, appliedQuery).filter(row =>
      !appliedReceiptStatus || row.receipt_status === appliedReceiptStatus);
    render();
  }

  function coverage() {
    const platform = collection.value === "platform";
    const receipt = collection.value === "source_receipt";
    const sessionText = collection.value === "native_session_text";
    const snapshot = collection.value === "snapshot_text";
    const corpus = collection.value === "research_corpus_text";
    const archive = collection.value === "archive_text";
    document.getElementById("receipt-status-label").hidden = !receipt;
    receiptStatus.disabled = !receipt;
    party.disabled = !platform || state.value === "outside";
    const selected = [...document.querySelectorAll("#state-coverage tbody tr")]
      .find(row => row.dataset.state === state.value);
    const receiptCoverage = [...document.querySelectorAll("#receipt-coverage tbody tr")]
      .find(row => row.dataset.state === state.value);
    const sessionCoverage = [...document.querySelectorAll("#session-coverage tbody tr")]
      .find(row => row.dataset.state === state.value);
    const snapshotCoverage = [...document.querySelectorAll("#snapshot-coverage tbody tr")]
      .find(row => row.dataset.state === state.value);
    const corpusCoverage = [...document.querySelectorAll("#corpus-coverage tbody tr")]
      .find(row => row.dataset.state === state.value);
    const archiveCoverage = [...document.querySelectorAll("#archive-coverage tbody tr")]
      .find(row => row.dataset.state === state.value);
    document.getElementById("selection-scope").textContent = archive
      ? (archiveCoverage
        ? `${state.value}: ${archiveCoverage.dataset.contexts} existing contexts / `
          + `${archiveCoverage.dataset.views} complete archived bill views. `
          + "Alternative providers overlap; not extra bills or introduced-version certification. "
          + "No supplied matching text is not publisher absence; all model approvals remain false."
        : "No independent archive packet was supplied; coverage is unknown.")
      : corpus
      ? (corpusCoverage
        ? `${state.value}: ${corpusCoverage.dataset.contexts} existing candidate contexts / `
          + `${corpusCoverage.dataset.views} complete research-corpus views. `
          + "Printed-header joins, not publisher-original or introduced-version certification. "
          + "No matching recovered view is not publisher absence; all model approvals remain false."
        : "No independent research-corpus packet was supplied; coverage is unknown.")
      : snapshot
      ? (snapshotCoverage
        ? `${state.value}: ${snapshotCoverage.dataset.records} candidate snapshot records, `
          + `${snapshotCoverage.dataset.nonempty} with retained nonempty raw_text. `
          + "Selected versions may be amended/later; retained errors and missing text are not "
          + "new bills or evidence of no activity. No filing-time or model admission."
        : "No retained snapshot-text packet was supplied for this selection; coverage is unknown.")
      : sessionText
      ? (sessionCoverage?.dataset.sessionProvided === "true"
        ? `${state.value}: ${sessionCoverage.dataset.views} full publisher-session source views / `
          + `${sessionCoverage.dataset.references} source references / ${sessionCoverage.dataset.bills} unique canonical bill IDs. `
          + "OUTSIDE candidate date cohort, not native/date/analytical admission. "
          + "No filing date required or inferred; observed dates/window dispositions unchanged. "
          + `${selected?.dataset.contexts ?? "Unknown"} active cycle candidate contexts remain unchanged.`
        : "Publisher-session source coverage unknown: no reviewed scope supplied for this state/session; "
          + "not a measured zero. Only explicitly selected NY 2023–2024 / IL 103rd scopes are supported.")
      : receipt
      ? (receiptCoverage?.dataset.receiptProvided === "true"
        ? `${state.value}: ${receiptCoverage.dataset.observations} separate source-receipt observations. `
          + `${selected?.dataset.contexts ?? "Unknown"} active cycle candidate contexts remain unchanged; `
          + `${selected?.dataset.widerContexts ?? "unknown"} retained wider-history source contexts. `
          + "Receipt is not introduction, filing, native evidence or eligible-cycle admission. "
          + "Both literal and action dates, including unresolved discrepancies, are retained."
        : "Receipt coverage unknown: this optional packet covers ME only. "
          + "No receipt observations were supplied for this state; this is not a measured zero.")
      : !platform && selected
      ? (Number(selected.dataset.contexts) === 0
        ? `${state.value}: date/cohort evidence unavailable in this cycle candidate dataset. `
          + "No source-coded filing/introduction, reviewed literal candidate or registered native-date candidate is available here. "
          + `${selected.dataset.widerContexts} retained wider-history source contexts are outside this candidate download. `
          + "An empty query download is not zero legislative activity or zero policies."
        : `${state.value}: ${Number(selected.dataset.contexts).toLocaleString()} saved cycle candidate contexts. `
          + "Native-only and description-only candidates are distinct from source-coded dates. "
          + (collection.value === "native_text"
            ? "Only exact joined native views in this candidate cohort are shown; excluded/unmatched contexts "
              + "are not evidence of source absence. This is not a native census or introduced-stage certification."
            : "This is not a certified denominator or full native-text corpus."))
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
    for (const row of document.querySelectorAll(
      "#receipt-coverage tbody tr, #session-coverage tbody tr, #snapshot-coverage tbody tr, "
      + "#corpus-coverage tbody tr",
    )) {
      row.hidden = Boolean(state.value && row.dataset.state !== state.value);
    }
  }

  async function update() {
    const request = ++generation;
    records = [];
    matches = [];
    loadedNames = [];
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
    if (collection.value === "source_receipt" && state.value !== "ME") {
      loading = false;
      status.textContent = "Receipt coverage unknown: this packet only covers ME. "
        + "No receipt observations were supplied for this state; not a measured zero.";
      return;
    }
    if (collection.value === "native_session_text"
        && ![...document.querySelectorAll("#session-coverage tbody tr")].some(row =>
          row.dataset.state === state.value && row.dataset.sessionProvided === "true")) {
      loading = false;
      status.textContent = "Publisher-session source coverage unknown: no reviewed scope supplied "
        + "for this state/session; not a measured zero.";
      return;
    }
    status.textContent = "Loading complete saved source records…";
    try {
      const names = collection.value === "bill_metadata" ? [`bills-${state.value}`]
        : collection.value === "native_text" ? [`native-${state.value}`]
        : collection.value === "source_receipt" ? [`receipts-${state.value}`]
        : collection.value === "native_session_text" ? [`native-session-${state.value}`]
        : collection.value === "snapshot_text" ? [`snapshot-${state.value}`]
        : collection.value === "research_corpus_text" ? [`corpus-${state.value}`]
        : collection.value === "archive_text" ? [`archive-${state.value}`]
        : state.value === "outside" ? ["platform-outside"]
          : (party.value ? [party.value] : ["D", "R"]).map(code => `platform-${state.value}-${code}`);
      const groups = await Promise.all(names.map(async name => {
        const rows = [];
        for await (const line of savedJSONLLines([name])) {
          if (request !== generation) return [];
          rows.push(JSON.parse(line));
        }
        return rows;
      }));
      if (request !== generation) return;
      records = groups.flat();
      loadedNames = names;
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
  receiptStatus.addEventListener("change", () => { if (!loading) search(); });
  previous.addEventListener("click", () => { page--; render(); });
  next.addEventListener("click", () => { page++; render(); });
  download.addEventListener("click", async () => {
    if (loading || !loaded || exporting) return;
    const request = generation;
    const filename = `${collection.value}-${state.value}-${party.disabled ? "all" : party.value || "both"}-query-fulltext.jsonl`;
    exporting = true;
    download.disabled = true;
    download.textContent = `Preparing all ${matches.length.toLocaleString()} complete query matches…`;
    try {
      const blob = await fullQueryBlob([...loadedNames], appliedQuery, appliedReceiptStatus, matches.length);
      const url = URL.createObjectURL(blob), link = element("a");
      link.href = url;
      link.download = filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      if (request === generation) {
        status.textContent = `Complete query export failed: ${error.message}. No partial download was substituted.`;
      }
    } finally {
      exporting = false;
      download.disabled = loading || !loaded;
      download.textContent = `Download all ${matches.length.toLocaleString()} query matches (full-text JSONL)`;
    }
  });
}

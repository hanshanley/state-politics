"use strict";

const inspectorEncoder = new TextEncoder();
const inspectorDecoder = new TextDecoder("utf-8", { fatal: true });

async function inspectorSHA(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, "0")).join("");
}

async function completeRange(reference) {
  if (!/^evidence\/[A-Za-z0-9_./-]+$/.test(reference.path)
      || reference.path.split("/").includes("..")
      || !Number.isSafeInteger(reference.offset) || reference.offset < 0
      || !Number.isSafeInteger(reference.length) || reference.length < 1) {
    throw new Error("Invalid saved evidence range");
  }
  const end = reference.offset + reference.length - 1;
  const response = await fetch(reference.path, {
    headers: { Range: `bytes=${reference.offset}-${end}` }, cache: "no-store",
  });
  const contentRange = response.headers.get("Content-Range");
  if (response.status !== 206 || !contentRange
      || !contentRange.startsWith(`bytes ${reference.offset}-${end}/`)) {
    throw new Error(`Complete evidence range unavailable (HTTP ${response.status}); use the bound workspace server`);
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.length !== reference.length || await inspectorSHA(bytes) !== reference.sha256) {
    throw new Error("Complete saved record failed its byte/SHA binding");
  }
  const text = inspectorDecoder.decode(bytes);
  if (!text.endsWith("\n")) throw new Error("Incomplete physical JSONL record");
  return { raw: text.slice(0, -1), value: JSON.parse(text) };
}

function inspectorMatches(row, query, slice, topic) {
  const needle = query.trim().toLocaleLowerCase();
  if (needle && !`${row.identifier}\n${row.title ?? ""}\n${row.bill_id}`.toLocaleLowerCase().includes(needle)) return false;
  if (topic && String(row.candidate_topic) !== topic) return false;
  if (slice === "new") return row.baseline_topic === null && row.candidate_status === "classified";
  if (slice === "source") return row.source_disagreement === true;
  if (slice === "window") return row.window_disagreement === true;
  return !slice || row.candidate_status === slice;
}

function utf16Position(offset, astral) {
  let left = 0, right = astral.length;
  while (left < right) {
    const middle = (left + right) >>> 1;
    if (astral[middle] < offset) left = middle + 1;
    else right = middle;
  }
  return offset + left;
}

async function* completeQueryChunks(rows, get = completeRange) {
  for (const row of rows) {
    const context = await get(row.context);
    if (context.value.bill_id !== row.bill_id) throw new Error("Context identity changed");
    yield inspectorEncoder.encode('{"schema":"state-politics.classification-query.v1","context":');
    yield inspectorEncoder.encode(context.raw);
    for (const [key, field] of [["inputs", "input"], ["predictions", "prediction"]]) {
      yield inspectorEncoder.encode(`,"${key}":[`);
      for (let i = 0; i < row.sources.length; i++) {
        const source = row.sources[i], record = await get(source[field]);
        if (record.value.bill_id !== row.bill_id || record.value.input_id !== source.input_id
            || record.value.input_sha256 !== source.input_sha256) {
          throw new Error("Complete query source identity changed");
        }
        if (i) yield inspectorEncoder.encode(",");
        yield inspectorEncoder.encode(record.raw);
      }
      yield inspectorEncoder.encode("]");
    }
    yield inspectorEncoder.encode("}\n");
  }
}

async function completeQueryBlob(rows, get = completeRange) {
  const chunks = completeQueryChunks(rows, get);
  return new Response(new ReadableStream({
    async pull(controller) {
      try {
        const result = await chunks.next();
        if (result.done) controller.close();
        else controller.enqueue(result.value);
      } catch (error) {
        await chunks.return();
        controller.error(error);
      }
    },
    cancel() { return chunks.return(); },
  }, { highWaterMark: 1 }), {
    headers: { "Content-Type": "application/x-ndjson;charset=utf-8" },
  }).blob();
}

async function completeQueryToWritable(rows, writable, get = completeRange) {
  try {
    for await (const chunk of completeQueryChunks(rows, get)) {
      await writable.write(chunk);
    }
    await writable.close();
  } catch (error) {
    try { await writable.abort(); } catch {}
    throw error;
  }
}

function policyText(input, meta) {
  const source = input.original_source_view;
  const raw = source.source_type === "snapshot_text" ? source.source_record.raw_text
    : source.source_type === "research_corpus_text" ? source.source_record.text : source.text;
  if (typeof raw !== "string") throw new Error("Complete original source text is missing");
  return raw.slice(meta.utf16_span[0], meta.utf16_span[1]);
}

if (typeof module !== "undefined") {
  module.exports = {
    completeRange, inspectorMatches, utf16Position, completeQueryChunks, completeQueryBlob,
    completeQueryToWritable, policyText,
  };
}

if (typeof document !== "undefined") {
  (async () => {
    const element = id => document.getElementById(id);
    const state = element("state"), query = element("query"), slice = element("slice");
    const topic = element("topic"), status = element("status"), detail = element("detail");
    const download = element("download"), previous = element("previous"), next = element("next");
    const tbody = element("results").tBodies[0];
    let config, records = [], matches = [], page = 0, loaded = false, exporting = false;
    let loadVersion = 0, detailVersion = 0;
    const pageSize = 25;
    const make = (tag, text, parent) => {
      const node = document.createElement(tag);
      if (text !== undefined) node.textContent = text;
      if (parent) parent.append(node);
      return node;
    };
    const topicName = code => code === null ? "Unassigned"
      : `${code}: ${config.topics.find(t => t.code === code)?.name ?? "Unknown output"}`;
    const decisionName = (code, kind, reason) => code !== null ? topicName(code)
      : `${kind.replaceAll("_", " ")}${reason ? " · " + reason : ""}`;
    function message(text, error = false) {
      status.textContent = text;
      status.className = error ? "error" : "";
    }
    function saveBlob(blob, filename) {
      const href = URL.createObjectURL(blob), link = make("a");
      link.href = href; link.download = filename; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(href), 60000);
    }
    function render() {
      tbody.replaceChildren();
      for (const row of matches.slice(page * pageSize, (page + 1) * pageSize)) {
        const tr = make("tr", undefined, tbody);
        const cell = make("td", undefined, tr), button = make("button", row.identifier, cell);
        button.addEventListener("click", () => inspect(row, true));
        make("td", row.title ?? "Title not recorded", tr);
        make("td", decisionName(row.baseline_topic, row.baseline_status, row.baseline_reason), tr);
        make("td", decisionName(row.candidate_topic, row.candidate_status, row.candidate_reason), tr);
        make("td", `${row.sources.length} full source view${row.sources.length === 1 ? "" : "s"}`, tr);
      }
      element("page").textContent = matches.length
        ? `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, matches.length)} of ${matches.length.toLocaleString()}`
        : "No matching contexts";
      previous.disabled = exporting || !page;
      next.disabled = exporting || (page + 1) * pageSize >= matches.length;
      download.disabled = !loaded || exporting;
      download.textContent = `Download all ${matches.length.toLocaleString()} query contexts (complete records)`;
    }
    function apply() {
      matches = records.filter(row => inspectorMatches(row, query.value, slice.value, topic.value));
      page = 0;
      detail.hidden = true; detailVersion++;
      render();
      message(`${matches.length.toLocaleString()} of ${records.length.toLocaleString()} supplied ${state.value} candidate contexts. `
        + "Unassigned and missing text remain explicit; this is not a census of all legislation.");
    }
    async function loadState() {
      const version = ++loadVersion;
      const linked = new URLSearchParams(location.search);
      if (linked.get("state") !== state.value) {
        history.replaceState(null, "", `?${new URLSearchParams({ state: state.value })}`);
      }
      detailVersion++; loaded = false; records = []; matches = []; detail.hidden = true; render();
      message(`Loading the complete ${state.value} candidate index...`);
      try {
        const expected = config.states.find(row => row.state === state.value);
        if (!expected) throw new Error("Choose a registered state");
        const response = await fetch(expected.path, { cache: "no-store" });
        if (!response.ok) throw new Error(`State index HTTP ${response.status}`);
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (bytes.length !== expected.bytes || await inspectorSHA(bytes) !== expected.sha256) {
          throw new Error("State index failed its complete byte/SHA binding");
        }
        const index = JSON.parse(inspectorDecoder.decode(bytes));
        if (index.state !== expected.state || index.records.length !== expected.contexts) {
          throw new Error("State/context count changed");
        }
        if (version !== loadVersion) return;
        records = index.records; loaded = true; apply();
        const params = new URLSearchParams(location.search), bill = params.get("bill");
        if (params.get("state") === state.value && bill) {
          const row = records.find(item => item.bill_id === bill);
          if (!row) throw new Error("Linked context is not in this state index");
          await inspect(row, false);
        }
      } catch (error) {
        if (version === loadVersion) { loaded = false; render(); message(error.message, true); }
      }
    }
    function vectorsTable(prediction, parent) {
      const whole = JSON.parse(prediction.scores);
      const support = prediction.majority_candidate?.supporting_output_scores;
      if (!whole.length) {
        make("p", "No model scores exist for this excluded source. No zero or uniform vector is substituted.", parent);
        return;
      }
      if (whole.length !== config.output_codes.length || (support && support.length !== whole.length)
          || [...whole, ...(support ?? [])].some(value => !Number.isFinite(value) || value < 0 || value > 1)) {
        throw new Error("Invalid complete output-score vector");
      }
      make("h3", "All 21 topics plus learned rejection", parent);
      make("p", "Whole-document scores include every window. Supporting-window scores use only windows "
        + "voting for the majority output; they are not whole-bill confidence. Rejection is not removed or renormalized.", parent);
      const scroll = make("div", undefined, parent); scroll.className = "scroll";
      const table = make("table", undefined, scroll); table.className = "scores";
      const header = make("tr", undefined, make("thead", undefined, table));
      for (const name of ["Output", "Whole-document mean", "Supporting-window mean"]) make("th", name, header);
      const body = make("tbody", undefined, table);
      for (let i = 0; i < whole.length; i++) {
        const tr = make("tr", undefined, body);
        make("td", config.output_codes[i] === null ? "Learned rejection" : topicName(config.output_codes[i]), tr);
        for (const [values, conditional] of [[whole, false], [support, true]]) {
          const cell = make("td", undefined, tr);
          if (conditional) cell.className = "conditional";
          if (!values) make("span", "Not calculated", cell);
          else {
            const bar = make("span", undefined, cell); bar.className = "score-bar";
            bar.style.width = `${values[i] * 100}px`; bar.setAttribute("aria-hidden", "true");
            make("span", values[i].toPrecision(5), cell);
          }
        }
      }
    }
    function windowsTable(prediction, meta, text, parent) {
      const logits = JSON.parse(prediction.logits), spans = JSON.parse(prediction.chunk_spans);
      if (!logits.length) return;
      if (logits.length !== spans.length) throw new Error("Complete window records disagree");
      if (logits.some(values => values.length !== config.output_codes.length
          || values.some(value => !Number.isFinite(value)))
          || spans.some(pair => pair.length !== 2 || !pair.every(Number.isSafeInteger)
            || pair[0] < 0 || pair[1] <= pair[0] || pair[1] > meta.characters)) {
        throw new Error("Invalid complete window logits or character intervals");
      }
      make("h3", `All ${logits.length.toLocaleString()} overlapping model windows`, parent);
      make("p", "Windows are not independent raters or causal explanations. Every full window and logit vector remains in the complete query download.", parent);
      const controls = make("div", undefined, parent); controls.className = "controls";
      const back = make("button", "Previous windows", controls), label = make("span", "", controls);
      const forward = make("button", "Next windows", controls);
      const scroll = make("div", undefined, parent); scroll.className = "scroll";
      const table = make("table", undefined, scroll);
      const header = make("tr", undefined, make("thead", undefined, table));
      for (const title of ["Window", "Source character interval", "Top output", "Complete text"]) make("th", title, header);
      const body = make("tbody", undefined, table), shown = make("pre", "", parent);
      shown.hidden = true;
      let windowPage = 0;
      function paint() {
        body.replaceChildren(); back.disabled = !windowPage;
        forward.disabled = (windowPage + 1) * pageSize >= logits.length;
        label.textContent = `${windowPage * pageSize + 1}–${Math.min((windowPage + 1) * pageSize, logits.length)} of ${logits.length}`;
        for (let i = windowPage * pageSize; i < Math.min((windowPage + 1) * pageSize, logits.length); i++) {
          const winner = logits[i].indexOf(Math.max(...logits[i])), tr = make("tr", undefined, body);
          make("td", String(i + 1), tr); make("td", `${spans[i][0]}–${spans[i][1]} (end excluded)`, tr);
          make("td", config.output_codes[winner] === null ? "Learned rejection" : topicName(config.output_codes[winner]), tr);
          const button = make("button", "Read whole window", make("td", undefined, tr));
          button.addEventListener("click", () => {
            shown.hidden = false;
            shown.textContent = text.slice(utf16Position(spans[i][0], meta.astral_offsets),
              utf16Position(spans[i][1], meta.astral_offsets));
          });
        }
      }
      back.onclick = () => { windowPage--; paint(); };
      forward.onclick = () => { windowPage++; paint(); };
      paint();
    }
    async function inspect(row, focus) {
      const version = ++detailVersion;
      detail.hidden = false; detail.replaceChildren();
      make("p", "Loading and verifying complete evidence...", detail);
      try {
        const context = await completeRange(row.context);
        if (context.value.bill_id !== row.bill_id) throw new Error("Context identity changed");
        if (version !== detailVersion) return;
        detail.replaceChildren();
        make("h2", `${row.state} ${row.identifier}: ${row.title ?? "Title not recorded"}`, detail);
        make("p", `Original: ${decisionName(row.baseline_topic, row.baseline_status, row.baseline_reason)}. `
          + `Majority candidate: ${decisionName(row.candidate_topic, row.candidate_status, row.candidate_reason)}.`, detail);
        const candidate = context.value.majority_candidate;
        make("p", `Distinct accepted-source support: ${candidate.support ?? "not calculated"} / `
          + `${candidate.electorate ?? "not calculated"}. Source dissent/uncertainty: `
          + `${row.source_disagreement === null ? "not calculated" : row.source_disagreement}. `
          + `Window dissent: ${row.window_disagreement === null ? "not calculated" : row.window_disagreement}.`, detail);
        const params = new URLSearchParams({ state: row.state, bill: row.bill_id });
        history.replaceState(null, "", `?${params}`);
        if (!row.sources.length) {
          make("p", "No retained body is supplied for this context. No title-only fallback or synthetic score is shown.", detail);
        } else {
          const label = make("label", "Complete source alternative", detail);
          const select = make("select", undefined, label);
          row.sources.forEach((source, i) => {
            const option = make("option", `${i + 1}. ${source.input_id}`, select); option.value = String(i);
          });
          const view = make("div", undefined, detail);
          let sourceVersion = 0;
          async function showSource() {
            const current = ++sourceVersion, meta = row.sources[Number(select.value)];
            view.replaceChildren(); make("p", "Loading complete source text and saved predictions...", view);
            try {
              const [input, prediction] = await Promise.all([
                completeRange(meta.input), completeRange(meta.prediction),
              ]);
              for (const record of [input.value, prediction.value]) {
                if (record.bill_id !== row.bill_id || record.input_id !== meta.input_id
                    || record.input_sha256 !== meta.input_sha256) throw new Error("Source/context binding changed");
              }
              const text = policyText(input.value, meta);
              if (await inspectorSHA(inspectorEncoder.encode(text)) !== meta.input_sha256) {
                throw new Error("Complete model-input text failed its original SHA binding");
              }
              if (version !== detailVersion || current !== sourceVersion) return;
              view.replaceChildren();
              make("p", `${meta.characters.toLocaleString()} complete Unicode characters; `
                + `${prediction.value.n_input_tokens ?? "unscored"} source tokens; `
                + `${prediction.value.n_chunks} original windows. Input SHA-256: ${meta.input_sha256}`, view);
              const vote = prediction.value.majority_candidate;
              make("p", `Original source: ${decisionName(prediction.value.topic, "unassigned", prediction.value.abstention_reason)}. `
                + `Window-majority source: ${decisionName(vote.status === "excluded" ? null : vote.topic, vote.status, vote.reason)}. `
                + `Window support: ${vote.support ?? "not calculated"} / ${vote.electorate ?? "not calculated"}.`, view);
              vectorsTable(prediction.value, view);
              const sourceDetails = make("details", undefined, view);
              make("summary", "Read complete model-input policy text (not truncated)", sourceDetails);
              const pre = make("pre", text, sourceDetails); pre.dataset.completeSource = meta.input_sha256;
              windowsTable(prediction.value, meta, text, view);
            } catch (error) {
              if (version === detailVersion && current === sourceVersion) {
                view.replaceChildren(); make("p", `Complete source evidence could not be loaded: ${error.message}`, view).className = "error";
              }
            }
          }
          select.addEventListener("change", showSource);
          await showSource();
        }
        if (focus && version === detailVersion) detail.focus();
      } catch (error) {
        if (version === detailVersion) {
          detail.replaceChildren(); make("p", `Complete evidence could not be loaded: ${error.message}`, detail).className = "error";
        }
      }
    }
    download.addEventListener("click", async () => {
      if (!loaded || exporting) return;
      const selected = [...matches], selectedState = state.value;
      exporting = true;
      const controls = [...element("filters").querySelectorAll("input,select,button")];
      controls.forEach(control => { control.disabled = true; }); render();
      message(`Preparing all ${selected.length.toLocaleString()} complete contexts and every source alternative...`);
      try {
        const filename = `${selectedState}-complete-classification-query.jsonl`;
        if (window.isSecureContext && typeof window.showSaveFilePicker === "function") {
          const handle = await window.showSaveFilePicker({
            suggestedName: filename,
            types: [{
              description: "Complete classification query",
              accept: { "application/x-ndjson": [".jsonl"] },
            }],
          });
          await completeQueryToWritable(selected, await handle.createWritable());
        } else {
          const blob = await completeQueryBlob(selected);
          saveBlob(blob, filename);
        }
        message(`Downloaded all ${selected.length.toLocaleString()} complete contexts, source inputs and predictions; no metadata-only fallback.`);
      } catch (error) {
        if (error.name === "AbortError") {
          message("Complete query export canceled. No partial download was substituted.");
        } else {
          message(`Complete query export failed: ${error.message}. No partial download was substituted.`, true);
        }
      } finally {
        exporting = false; controls.forEach(control => { control.disabled = false; }); render();
      }
    });
    previous.onclick = () => { page--; render(); };
    next.onclick = () => { page++; render(); };
    state.addEventListener("change", loadState);
    query.addEventListener("input", () => { if (loaded) apply(); });
    slice.addEventListener("change", () => { if (loaded) apply(); });
    topic.addEventListener("change", () => { if (loaded) apply(); });
    element("filters").addEventListener("submit", event => { event.preventDefault(); if (loaded) apply(); });
    try {
      const response = await fetch("config.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`Configuration HTTP ${response.status}`);
      config = await response.json();
      if (config.schema !== "state-politics.classification-inspector.v1"
          || config.states.length !== 50 || config.output_codes.length !== 22) {
        throw new Error("Incompatible complete classification inspector");
      }
      for (const row of config.states) {
        const option = make("option", `${row.state} (${row.contexts.toLocaleString()} contexts)`, state);
        option.value = row.state;
      }
      for (const row of config.topics) {
        const option = make("option", `${row.code}: ${row.name}`, topic); option.value = String(row.code);
      }
      element("national").textContent = `${config.contexts.toLocaleString()} original contexts; `
        + `${config.source_views.toLocaleString()} full source alternatives. Majority candidate: `
        + `${config.candidate_counts.classified.toLocaleString()} assigned; `
        + `${config.candidate_counts.unavailable.toLocaleString()} without supplied text. `
        + "The frozen original decisions are preserved.";
      state.disabled = false;
      const requested = new URLSearchParams(location.search).get("state");
      state.value = config.states.some(row => row.state === requested) ? requested
        : config.states.find(row => row.contexts)?.state ?? config.states[0].state;
      await loadState();
    } catch (error) {
      element("national").textContent = `Classification evidence unavailable: ${error.message}`;
      element("national").className = "error";
      download.disabled = true;
    }
  })();
}

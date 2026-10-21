"use strict";
(() => {
  const SCHEMA = "local_self_attested_human_review_v1";
  const ATTESTATION = "SELF_ATTESTED_HUMAN_NOT_IDENTITY_CERTIFIED";
  const $ = id => document.getElementById(id);
  const hash = async bytes => [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map(x => x.toString(16).padStart(2, "0")).join("");
  const utf8 = text => new TextEncoder().encode(text);
  const scalarLength = text => [...text].length;
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const keys = (value, expected) => object(value) &&
    Object.keys(value).sort().join("\0") === [...expected].sort().join("\0");
  const envelopeFields = ["schema", "packet_id", "source_manifest_sha256", "reviewer_id",
    "human_provenance", "all_records_reviewed_in_full", "no_model_assistance", "decisions"];
  const decisionFields = ["record_id", "input_sha256", "topic", "abstention_reason",
    "reviewer_id", "reviewer_type", "reviewed_on", "input_reviewed_in_full",
    "input_only_no_external_context", "rationale", "evidence_spans"];
  function strictJSON(text) {
    // Validate ordinary JSON syntax first; then reject duplicate keys at every depth.
    const result = JSON.parse(text);
    let position = 0;
    const whitespace = () => { while (/\s/.test(text[position] || "") && position < text.length) position++; };
    const stringToken = () => {
      const start = position++;
      while (position < text.length) {
        if (text[position++] === "\\") position++;
        else if (text[position-1] === '"') return JSON.parse(text.slice(start, position));
      }
      throw Error("Malformed JSON string");
    };
    const value = () => {
      whitespace();
      if (text[position] === "{") {
        position++; whitespace(); const seen = new Set();
        if (text[position] === "}") { position++; return; }
        for (;;) {
          whitespace(); const key = stringToken();
          if (seen.has(key)) throw Error("Duplicate JSON key");
          seen.add(key); whitespace(); position++; value(); whitespace();
          if (text[position++] === "}") return;
        }
      }
      if (text[position] === "[") {
        position++; whitespace();
        if (text[position] === "]") { position++; return; }
        for (;;) { value(); whitespace(); if (text[position++] === "]") return; }
      }
      if (text[position] === '"') { stringToken(); return; }
      const start = position;
      while (position < text.length && !/[\s,\]}]/.test(text[position])) position++;
      const token = text.slice(start, position);
      if (!["true", "false", "null"].includes(token) && !Number.isFinite(Number(token)))
        throw Error("Non-finite JSON number");
    };
    value();
    return result;
  }
  let manifest, data, index = 0, draft, storageKey;
  const status = message => { $("status").textContent = message; };
  const element = (tag, text) => {
    const node = document.createElement(tag); node.textContent = text; return node;
  };
  async function checked(path, expected) {
    const response = await fetch(path, {cache: "no-store"});
    if (!response.ok) throw Error(`Cannot load ${path}`);
    const bytes = await response.arrayBuffer();
    if (expected && (bytes.byteLength !== expected.bytes || await hash(bytes) !== expected.sha256))
      throw Error(`Frozen bytes mismatch: ${path}`);
    return bytes;
  }
  function persist() {
    try { localStorage.setItem(storageKey, JSON.stringify(draft)); }
    catch { status("Draft storage unavailable. Keep this page open and export when complete."); }
  }
  function save() {
    const row = data.records[index];
    if (row) draft.entries[row.record_id] = {
      ...draft.entries[row.record_id],
      decision: $("decision").value, rationale: $("rationale").value,
      spans: $("spans").value, full: $("full").checked, inputOnly: $("input-only").checked,
    };
    draft.reviewer = $("reviewer").value; draft.date = $("reviewed-on").value;
    draft.human = $("human").checked; draft.noModel = $("no-model").checked;
    draft.allFull = $("all-full").checked; persist();
  }
  function render() {
    const row = data.records[index];
    $("progress").textContent = `${Object.values(draft.entries).filter(e => e.decision).length} / ${data.records.length} explicit decisions (not yet validated)`;
    $("record-picker").value = String(index);
    if (!row) {
      $("record-title").textContent = "No eligible native inputs. No human decisions can be exported.";
      $("export").disabled = true; return;
    }
    $("record-title").textContent = `${index + 1} / ${data.records.length}: ${row.state}`;
    $("record-identity").textContent = `${row.record_id}\n${row.bill_id}\nInput SHA256 ${row.input_sha256}`;
    $("chosen-text").textContent = row.text;
    $("alternatives").replaceChildren();
    row.alternatives.forEach((alt, i) => {
      const details = element("details", "");
      details.append(element("summary", `Alternative ${i + 1}: ${alt.view_id}`),
        element("h4", "Entire preserved text"), element("pre", alt.text),
        element("h4", "Exact original JSON line (integers/Unicode not reserialized)"),
        element("pre", alt.raw_provenance));
      $("alternatives").append(details);
    });
    const entry = draft.entries[row.record_id] || {};
    $("decision").value = entry.decision || ""; $("rationale").value = entry.rationale || "";
    $("spans").value = entry.spans || ""; $("full").checked = entry.full === true;
    $("input-only").checked = entry.inputOnly === true;
    $("previous").disabled = index === 0; $("next").disabled = index + 1 === data.records.length;
  }
  function validDate(value) {
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`;
    return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
      !Number.isNaN(Date.parse(value)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0,10) === value &&
      value <= today;
  }
  function validate(annotation) {
    if (!keys(annotation, envelopeFields)) throw Error("Invalid annotation envelope");
    if (annotation.schema !== SCHEMA || annotation.packet_id !== manifest.packet_id ||
        annotation.source_manifest_sha256 !== manifest.source_manifest_sha256)
      throw Error("Foreign packet/source binding");
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{2,47}$/.test(annotation.reviewer_id) ||
        typeof annotation.reviewer_id !== "string") throw Error("Use a pseudonymous reviewer ID");
    if (annotation.human_provenance !== ATTESTATION || annotation.no_model_assistance !== true ||
        annotation.all_records_reviewed_in_full !== true) throw Error("Full human/no-model self-attestations required");
    if (!Array.isArray(annotation.decisions) || !data.records.length ||
        annotation.decisions.length !== data.records.length) throw Error("Missing/extra decisions");
    const expected = new Map(data.records.map(row => [row.record_id, row])), seen = new Set();
    for (const row of annotation.decisions) {
      if (!keys(row, decisionFields)) throw Error("Invalid decision schema");
      const source = expected.get(row.record_id);
      if (!source || seen.has(row.record_id)) throw Error("Duplicate/extra record");
      seen.add(row.record_id);
      if (row.input_sha256 !== source.input_sha256) throw Error("Wrong input hash");
      if (row.topic === null ? !data.abstentions.includes(row.abstention_reason) :
        (!Number.isInteger(row.topic) || !data.topics.some(t => t.code === row.topic) ||
          row.abstention_reason !== null)) throw Error("Invalid topic/abstention pairing");
      if (row.reviewer_id !== annotation.reviewer_id || row.reviewer_type !== "human_self_attested" ||
          row.input_reviewed_in_full !== true || row.input_only_no_external_context !== true ||
          typeof row.rationale !== "string" || scalarLength(row.rationale.trim()) < 20 ||
          !validDate(row.reviewed_on)) throw Error("Invalid full-review provenance/rationale/date");
      if (!Array.isArray(row.evidence_spans) || !row.evidence_spans.length ||
          row.evidence_spans.some(s => typeof s !== "string" || !s.trim() || !source.text.includes(s)))
        throw Error("Evidence spans must be exact nonempty chosen-input substrings");
    }
    return annotation;
  }
  function annotation() {
    save();
    if (!draft.human) throw Error("Human self-attestation required (not identity certification)");
    return validate({
      schema: SCHEMA, packet_id: manifest.packet_id,
      source_manifest_sha256: manifest.source_manifest_sha256, reviewer_id: draft.reviewer,
      human_provenance: ATTESTATION, all_records_reviewed_in_full: draft.allFull,
      no_model_assistance: draft.noModel,
      decisions: data.records.map(row => {
        const e = draft.entries[row.record_id] || {};
        if (!e.decision) throw Error(`Undecided record: ${row.record_id}`);
        return {
          record_id: row.record_id, input_sha256: row.input_sha256,
          topic: e.decision.startsWith("topic:") ? Number(e.decision.slice(6)) : null,
          abstention_reason: e.decision.startsWith("abstain:") ? e.decision.slice(8) : null,
          reviewer_id: draft.reviewer, reviewer_type: "human_self_attested",
          reviewed_on: draft.date === draft.importedDate && e.reviewedOn ? e.reviewedOn : draft.date,
          input_reviewed_in_full: e.full, input_only_no_external_context: e.inputOnly,
          rationale: e.rationale,
          evidence_spans: e.preservedSpans && (e.spans || "").replace(/\r\n?/g, "\n") ===
            e.preservedSpans.join("\n").replace(/\r\n?/g, "\n") ? e.preservedSpans :
            (e.spans || "").split("\n").filter(s => s.trim()),
        };
      }),
    });
  }
  function download(bytes, filename, type) {
    const url = URL.createObjectURL(new Blob([bytes], {type}));
    const link = element("a", ""); link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function start() {
    if (!["localhost", "127.0.0.1", "[::1]"].includes(location.hostname))
      throw Error("Local loopback HTTP serving required. Do not publish this packet.");
    manifest = JSON.parse(new TextDecoder("utf-8", {fatal:true}).decode(
      await checked("human_packet_manifest.json")));
    if (manifest.schema !== SCHEMA || manifest.status !== "local_only_unpublished_unannotated")
      throw Error("Invalid human packet manifest");
    data = JSON.parse(new TextDecoder("utf-8", {fatal:true}).decode(
      await checked("ui-data.json", manifest.ui_data)));
    if (data.topics.length !== 21 || data.records.length !== manifest.n_selected ||
        Object.keys(data.states).length !== 50) throw Error("Incomplete packet/rubric/accounting");
    for (const row of data.records) {
      if (await hash(utf8(row.text)) !== row.input_sha256) throw Error("Chosen text hash mismatch");
    }
    // Verify/download the original bytes, never JSON.stringify source provenance.
    for (const [name, expected] of Object.entries(manifest.complete_inputs)) {
      await checked(`complete-inputs/${encodeURIComponent(name)}`, expected);
    }
    const downloads = [
      ["complete-inputs.zip", "Complete selected frozen inputs ZIP", manifest.complete_inputs_zip],
      ["complete-inputs/review_packet.jsonl", "Complete chosen inputs NDJSON", manifest.complete_inputs["review_packet.jsonl"]],
      ["complete-inputs/selected_alternative_views.jsonl", "All complete alternatives + original provenance NDJSON", manifest.complete_inputs["selected_alternative_views.jsonl"]],
      ["complete-inputs/topics.yml", "Frozen topic rubric YAML", manifest.complete_inputs["topics.yml"]],
      ["complete-inputs/source_manifest.json", "Original frozen source manifest", manifest.complete_inputs["source_manifest.json"]],
    ];
    for (const [path, title, expected] of downloads) {
      const button = element("button", title); button.type = "button";
      button.addEventListener("click", async () => {
        try { download(await checked(path, expected), path.split("/").pop(), "application/octet-stream"); }
        catch (error) { status(`Download refused: ${error.message}`); }
      });
      $("downloads").append(button);
    }
    $("notice").textContent = data.notice;
    $("binding").textContent = `Packet ${manifest.packet_id}\nFrozen manifest ${manifest.source_manifest_sha256}`;
    $("accounting").textContent = JSON.stringify(data.states, null, 2);
    for (const topic of data.topics) {
      $("rubric").append(element("h3", `${topic.code}: ${topic.name}`), element("p", topic.description));
      const option = element("option", `${topic.code}: ${topic.name}`); option.value = `topic:${topic.code}`;
      $("decision").append(option);
    }
    for (const reason of data.abstentions) {
      const option = element("option", `Abstain: ${reason}`); option.value = `abstain:${reason}`;
      $("decision").append(option);
    }
    data.records.forEach((row, i) => {
      const option = element("option", `${i+1}: ${row.state} — ${row.record_id}`);
      option.value = String(i); $("record-picker").append(option);
    });
    storageKey = `${SCHEMA}:${manifest.packet_id}`;
    draft = {entries: {}, reviewer: "", date: "", human: false, noModel: false, allFull: false};
    let recovery = "Ready. No decisions prefilled.";
    try {
      const stored = localStorage.getItem(storageKey);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (!object(parsed) || !object(parsed.entries)) throw Error("Invalid local draft");
        draft = {...draft, ...parsed}; recovery = "Local draft restored (not a validated annotation).";
      }
    } catch { recovery = "Local draft could not be restored; no decisions prefilled."; }
    $("reviewer").value = typeof draft.reviewer === "string" ? draft.reviewer : "";
    $("reviewed-on").value = typeof draft.date === "string" ? draft.date : "";
    $("human").checked = draft.human === true; $("no-model").checked = draft.noModel === true;
    $("all-full").checked = draft.allFull === true;
    for (const id of ["reviewer", "reviewed-on", "human", "no-model", "all-full",
      "decision", "rationale", "spans", "full", "input-only"]) {
      $(id).addEventListener("input", save); $(id).addEventListener("change", save);
    }
    $("record-picker").addEventListener("change", () => { save(); index = Number($("record-picker").value); render(); });
    $("previous").addEventListener("click", () => { save(); index = Math.max(0,index-1); render(); });
    $("next").addEventListener("click", () => { save(); index = Math.min(data.records.length-1,index+1); render(); });
    $("clear").addEventListener("click", () => { localStorage.removeItem(storageKey); location.reload(); });
    $("export").addEventListener("click", () => {
      try {
        download(JSON.stringify(annotation(), null, 2)+"\n", `annotations-only-${draft.reviewer}.json`, "application/json");
        status("Annotations-only export validated in browser. Run independent Python validation/import; not gold or training.");
      } catch (error) { status(`Export refused: ${error.message}`); }
    });
    $("import").addEventListener("change", async () => {
      const file = $("import").files[0];
      if (!file) return;
      try {
        const result = validate(strictJSON(await file.text()));
        const entries = {};
        result.decisions.forEach(row => {
          entries[row.record_id] = {
            decision: row.topic === null ? `abstain:${row.abstention_reason}` : `topic:${row.topic}`,
            rationale: row.rationale, spans: row.evidence_spans.join("\n"), full: true, inputOnly: true,
            preservedSpans: row.evidence_spans, reviewedOn: row.reviewed_on,
          };
        });
        draft = {entries, reviewer: result.reviewer_id, date: result.decisions[0].reviewed_on,
          importedDate: result.decisions[0].reviewed_on,
          human: true, noModel: true, allFull: true};
        $("reviewer").value = draft.reviewer; $("reviewed-on").value = draft.date;
        $("human").checked = $("no-model").checked = $("all-full").checked = true;
        persist(); render(); status("Imported self-attested annotation. Python validation still required.");
      } catch (error) { status(`Import refused: ${error.message}`); }
      $("import").value = "";
    });
    $("workspace").hidden = false; render(); status(recovery);
  }
  start().catch(error => { $("workspace").hidden = true; status(`Packet refused: ${error.message}`); });
})();

// Real Chromium checks via its native DevTools protocol; no DOM emulator or new dependency.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { createReadStream } = require("node:fs");
const { createInterface } = require("node:readline");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { createHash } = require("node:crypto");
const { createGunzip } = require("node:zlib");

const root = path.resolve(__dirname, "..");
const [previewArg, runArg, chrome, fixture] = process.argv.slice(2);
if (!previewArg || !runArg || !chrome || typeof WebSocket === "undefined") {
  throw new Error("Usage (Node with WebSocket): browser_cycle_site.cjs PREVIEW RUN_DIRECTORY CHROMIUM [fixture]");
}
const preview = path.resolve(previewArg), run = path.resolve(runArg);
for (const directory of [preview, run]) {
  assert.ok(directory.startsWith(path.join(root, "data") + path.sep), "Use ignored project data/ only");
}
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
let browser, server, socket;
const pending = new Map(), exceptions = [], requests = [];
let sequence = 0;

function send(method, params = {}, sessionId) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`CDP timeout: ${method}`));
    }, 60000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
}

function outputMatch(process, pattern) {
  return new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`Process readiness timeout: ${output}`)), 30000);
    const read = chunk => {
      output += chunk.toString();
      const match = output.match(pattern);
      if (match) {
        clearTimeout(timer);
        resolve(match);
      }
    };
    process.stdout.on("data", read);
    process.stderr.on("data", read);
    process.once("error", error => { clearTimeout(timer); reject(error); });
    process.once("exit", code => {
      clearTimeout(timer);
      reject(new Error(`Process exited ${code}: ${output}`));
    });
  });
}

async function evaluate(session, expression) {
  const result = await send("Runtime.evaluate", {
    expression, returnByValue: true, awaitPromise: true,
  }, session);
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}

async function waitFor(session, expression) {
  for (let attempt = 0; attempt < 1200; attempt++) {
    if (await evaluate(session, expression)) return;
    await sleep(100);
  }
  const status = await evaluate(session, 'document.getElementById("evidence-status")?.textContent');
  throw new Error(`Browser condition timed out: ${expression}; status: ${status}`);
}

async function target(url, scripts = true) {
  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Page.enable", {}, sessionId);
  await send("Runtime.enable", {}, sessionId);
  await send("Network.enable", {}, sessionId);
  if (!scripts) await send("Emulation.setScriptExecutionDisabled", { value: true }, sessionId);
  await send("Page.navigate", { url }, sessionId);
  await waitFor(sessionId, 'document.readyState === "complete"');
  return { targetId, sessionId };
}

async function change(session, id, value) {
  await evaluate(session, `(() => { const control = document.getElementById(${JSON.stringify(id)});
    control.value = ${JSON.stringify(value)}; control.dispatchEvent(new Event("change")); })()`);
}

async function search(session, text) {
  await evaluate(session, `(() => { const control = document.getElementById("query");
    control.value = ${JSON.stringify(text)}; control.focus(); })()`);
  await key(session, "Enter", 13);
}

async function key(session, key, code) {
  await send("Input.dispatchKeyEvent", {
    type: "keyDown", key, code: key, windowsVirtualKeyCode: code,
    ...(key === "Enter" ? { text: "\r", unmodifiedText: "\r" } : {}),
  }, session);
  await send("Input.dispatchKeyEvent", {
    type: "keyUp", key, code: key, windowsVirtualKeyCode: code,
  }, session);
}

async function download(session, expected, name, selector = "#download-query", compressed = false) {
  const directory = path.join(run, "downloads", name.replace(/[^a-z0-9]+/gi, "-"));
  await fs.mkdir(directory, { recursive: true });
  await send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: directory });
  await evaluate(session, `document.querySelector(${JSON.stringify(selector)}).click()`);
  for (let attempt = 0; attempt < 300; attempt++) {
    const names = (await fs.readdir(directory)).filter(entry =>
      entry.endsWith(compressed ? ".jsonl.gz" : ".jsonl"));
    if (names.length) {
      const saved = path.join(directory, names[0]);
      const iterator = typeof expected === "function" ? expected()[Symbol.asyncIterator]() : null;
      let count = 0;
      for await (const row of jsonRows(saved, compressed)) {
        const original = iterator ? await iterator.next() : { value: expected[count], done: count >= expected.length };
        assert.equal(original.done, false, `${name}: extra downloaded row ${count}`);
        assert.deepEqual(row, original.value, `${name}: full-source row ${count} differs`);
        count++;
      }
      assert.ok(iterator ? (await iterator.next()).done : count === expected.length,
        `${name}: missing complete source rows`);
      return { file: path.relative(run, saved), rows: count };
    }
    await sleep(100);
  }
  throw new Error(`Browser download did not complete: ${name}`);
}

async function readRows(name) {
  const rows = [];
  for await (const row of sourceRows(name)) rows.push(row);
  return rows;
}

async function* jsonRows(file, compressed = false) {
  const stream = createReadStream(file);
  const lines = createInterface({
    input: compressed ? stream.pipe(createGunzip()) : stream, crlfDelay: Infinity,
  });
  for await (const line of lines) if (line.trim()) yield JSON.parse(line);
}

function sourceRows(name) {
  return jsonRows(path.join(preview, "evidence", name + ".jsonl"));
}

async function terminate(child) {
  if (!child || child.exitCode !== null) return;
  const exited = new Promise(resolve => child.once("exit", resolve));
  child.kill("SIGTERM");
  await Promise.race([exited, sleep(3000)]);
  if (child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL");
    await exited;
  }
}

(async () => {
  await fs.mkdir(path.join(run, "downloads"), { recursive: true });
  await fs.mkdir(path.join(run, "browser-runtime"), { recursive: true });
  const env = { ...process.env, TMPDIR: path.join(run, "browser-runtime") };
  let receipt;
  try {
    server = spawn(path.join(root, ".venv/bin/python"), [
      "-u", "-m", "http.server", "0", "--bind", "127.0.0.1", "--directory", preview,
    ], { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] });
    const ready = await outputMatch(server, /Serving HTTP on 127\.0\.0\.1 port (\d+)/);
    const base = `http://127.0.0.1:${ready[1]}`;
    browser = spawn(chrome, [
      "--headless=new", "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
      "--disable-background-networking", "--disable-component-update", "--disable-extensions",
      "--disable-default-apps", "--disable-sync", "--disable-breakpad", "--no-first-run",
      "--no-default-browser-check", `--user-data-dir=${path.join(run, "profile")}`,
      `--disk-cache-dir=${path.join(run, "cache")}`, "about:blank",
    ], { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] });
    const endpoint = await outputMatch(browser, /DevTools listening on (ws:\/\/[^\s]+)/);
    socket = new WebSocket(endpoint[1]);
    await new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve, { once: true });
      socket.addEventListener("error", reject, { once: true });
    });
    socket.addEventListener("message", event => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const item = pending.get(message.id);
        if (!item) return;
        pending.delete(message.id);
        clearTimeout(item.timer);
        if (message.error) item.reject(new Error(JSON.stringify(message.error)));
        else item.resolve(message.result);
      } else if (message.method === "Runtime.exceptionThrown") {
        exceptions.push(message.params);
      } else if (message.method === "Network.requestWillBeSent") {
        requests.push({ session: message.sessionId, url: message.params.request.url });
      }
    });
    await send("Browser.setDownloadBehavior", {
      behavior: "allow", downloadPath: path.join(run, "downloads"),
    });
    const version = await send("Browser.getVersion");
    const page = await target(base + "/");
    const session = page.sessionId;
    assert.equal(await evaluate(session, 'document.querySelectorAll("#state-coverage tbody tr").length'), 50);
    assert.equal(await evaluate(session, 'document.querySelectorAll("#org-coverage tbody tr").length'), 100);
    assert.equal(requests.filter(entry => entry.url.includes("/evidence/")).length, 0);
    await key(session, "Tab", 9);
    assert.equal(await evaluate(session, "document.activeElement.className"), "skip-link");
    await key(session, "Enter", 13);
    assert.equal(await evaluate(session, "document.activeElement.id"), "evidence-heading");

    const billRows = await readRows("bills-TX");
    const hasNative = await evaluate(session, 'Boolean(document.querySelector("#collection option[value=native_text]"))');
    const hasReceipt = await evaluate(session, 'Boolean(document.querySelector("#collection option[value=source_receipt]"))');
    const hasSessionText = await evaluate(session, 'Boolean(document.querySelector("#collection option[value=native_session_text]"))');
    const hasArchive = await evaluate(session, 'Boolean(document.querySelector("#collection option[value=archive_text]"))');
    const hasSnapshot = await evaluate(session, 'Boolean(document.querySelector("#collection option[value=snapshot_text]"))');
    const hasCorpus = await evaluate(session, 'Boolean(document.querySelector("#collection option[value=research_corpus_text]"))');
    const buildManifest = JSON.parse(await fs.readFile(
      path.join(preview, "downloads/build_manifest.json"), "utf8"));
    for (const binding of Object.values(buildManifest.producer_archive || {})) {
      const archived = await fs.readFile(path.join(preview, binding.path));
      assert.equal(createHash("sha256").update(archived).digest("hex"), binding.sha256);
      assert.deepEqual(buildManifest.outputs[binding.path], {
        sha256: binding.sha256, bytes: archived.length,
      });
      const servedHash = await evaluate(session, `(async () => {
        const response = await fetch(${JSON.stringify(binding.path)});
        if (!response.ok) throw new Error("Archived producer source unavailable");
        const bytes = await crypto.subtle.digest("SHA-256", await response.arrayBuffer());
        return [...new Uint8Array(bytes)].map(value => value.toString(16).padStart(2, "0")).join("");
      })()`);
      assert.equal(servedHash, binding.sha256);
    }
    assert.ok(billRows.every(row => row.source_bundle_manifest_sha256
      === buildManifest.inputs.bill_metadata["manifest.json"]));
    assert.ok(billRows.length > 10);
    await change(session, "state", "TX");
    await waitFor(session, 'document.querySelectorAll("#evidence article").length === 10');
    if (billRows[0].token_plan) {
      const planText = await evaluate(session, 'document.querySelector("#evidence .token-plan").textContent');
      assert.ok(planText.includes(billRows[0].token_plan.n_input_tokens.toLocaleString("en-US")));
      assert.ok(planText.includes("not predictions"));
      assert.equal(billRows[0].n_input_tokens, null);
    }
    assert.equal(await evaluate(session, 'document.querySelectorAll("#state-coverage tbody tr:not([hidden])").length'), 1);
    const first = await evaluate(session, 'document.querySelector("#evidence .record-id").textContent');
    await evaluate(session, 'document.getElementById("next").click()');
    assert.notEqual(await evaluate(session, 'document.querySelector("#evidence .record-id").textContent'), first);
    const billsDownload = await download(session, billRows, "all TX bill views, from page 2");
    await search(session, billRows[0].bill_id);
    const specific = billRows.filter(row => row.bill_id === billRows[0].bill_id);
    await waitFor(session, `document.querySelectorAll("#evidence article").length === ${specific.length}`);
    const searchDownload = await download(session, specific, "bill ID query");
    await search(session, "this-string-does-not-exist-in-any-evidence-record-759193");
    await waitFor(session, 'document.querySelectorAll("#evidence article").length === 0');
    assert.equal(await evaluate(session, 'document.getElementById("download-query").disabled'), false);
    const emptyQueryDownload = await download(session, [], "empty literal query");
    await search(session, "");
    if (fixture === "fixture") {
      await evaluate(session, 'document.querySelector("#evidence details").open = true');
      assert.ok((await evaluate(session, 'document.querySelector("#evidence .source-text").textContent'))
        .includes("<script>window.EVIDENCE_INJECTED=true</script>"));
    }
    assert.equal(await evaluate(session, 'document.querySelectorAll("#evidence script, #evidence img").length'), 0);
    assert.equal(await evaluate(session, 'typeof window.EVIDENCE_INJECTED'), "undefined");

    const nativeDownloads = [];
    if (hasNative) {
      const nativeRows = await readRows("native-TX");
      assert.ok(nativeRows.length > 10);
      await change(session, "collection", "native_text");
      await waitFor(session, 'document.querySelectorAll("#evidence article").length === 10');
      assert.ok((await evaluate(session, 'document.getElementById("selection-scope").textContent'))
        .includes("not a native census"));
      const distinctBills = new Set(nativeRows.map(row => row.bill_id)).size;
      assert.ok((await evaluate(session, 'document.getElementById("evidence-status").textContent'))
        .includes(`${distinctBills.toLocaleString("en-US")} distinct candidate bill contexts`));
      const nativeFirst = await evaluate(session, 'document.querySelector("#evidence .record-id").textContent');
      await evaluate(session, 'document.getElementById("next").click()');
      assert.notEqual(await evaluate(session, 'document.querySelector("#evidence .record-id").textContent'), nativeFirst);
      nativeDownloads.push(await download(session, nativeRows, "native complete views from page 2"));
      if (fixture === "fixture") {
        await search(session, '"quoted phrase"');
        await waitFor(session, 'document.querySelectorAll("#evidence article").length === 10');
        await evaluate(session, 'document.getElementById("next").click()');
        nativeDownloads.push(await download(session, nativeRows, "native full-text filtered matches beyond page 1"));
        await search(session, "NATIVE-END-11");
        const filtered = nativeRows.filter(row => row.text.includes("NATIVE-END-11"));
        await waitFor(session, `document.querySelectorAll("#evidence article").length === ${filtered.length}`);
        nativeDownloads.push(await download(session, filtered, "native complete string tail query"));
        assert.ok(await evaluate(session,
          '[...document.querySelectorAll("#evidence .source-text")].some(node => node.textContent.endsWith("NATIVE-END-11"))'));
        assert.equal(await evaluate(session, 'document.querySelectorAll("#evidence script, #evidence img").length'), 0);
        assert.equal(await evaluate(session, 'typeof window.EVIDENCE_INJECTED'), "undefined");
      } else {
        await search(session, "native_text");
        await waitFor(session, 'document.querySelectorAll("#evidence article").length === 10');
        await evaluate(session, 'document.getElementById("next").click()');
        nativeDownloads.push(await download(session, nativeRows, "native filtered full-source query beyond page 1"));
        const { filterEvidence } = require(path.join(preview, "cycle-evidence.js"));
        const needle = nativeRows[0].text.split(/[\r\n\u2028\u2029]+/)
          .map(line => line.trim()).filter(line => line.length >= 20).at(-1)?.slice(-80);
        assert.ok(needle, "Need an actual retained native-text query");
        const filtered = filterEvidence(nativeRows, needle);
        assert.ok(filtered.length > 0);
        await search(session, needle);
        await waitFor(session, `document.querySelectorAll("#evidence article").length === ${Math.min(10, filtered.length)}`);
        nativeDownloads.push(await download(session, filtered, "native literal retained-text query"));
        const displayedHash = await evaluate(session, `(async () => {
          const text = [...document.querySelector("#evidence article").querySelectorAll(".source-text")].at(-1).textContent;
          const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
          return [...new Uint8Array(bytes)].map(value => value.toString(16).padStart(2, "0")).join("");
        })()`);
        assert.equal(displayedHash, filtered[0].input_sha256);
        assert.equal(createHash("sha256").update(filtered[0].text).digest("hex"), displayedHash);
      }
      await search(session, "");
    }
    await change(session, "collection", "platform");
    const platformD = await readRows("platform-TX-D");
    await waitFor(session, 'document.getElementById("evidence-status").textContent.startsWith("Views ")');
    await change(session, "party", "D");
    await waitFor(session, 'document.getElementById("evidence-status").textContent.startsWith("Views ")');
    const platformDownload = await download(session, platformD, "TX/D platform views");
    assert.equal(await evaluate(session, 'document.querySelectorAll("#org-coverage tbody tr:not([hidden])").length'), 1);
    if (fixture === "fixture") {
      assert.ok((await evaluate(session, 'document.querySelector("#evidence .source-text").textContent'))
        .includes("<script>window.EVIDENCE_INJECTED=true</script>"));
      assert.equal(await evaluate(session, 'document.querySelectorAll("#evidence script, #evidence img").length'), 0);
      assert.equal(await evaluate(session, 'typeof window.EVIDENCE_INJECTED'), "undefined");
      assert.equal(await evaluate(session,
        `document.querySelectorAll('#evidence a[href^="javascript:"]').length`), 0);
      await change(session, "party", "R");
      await waitFor(session, 'document.getElementById("evidence-status").textContent.startsWith("No matching")');
      assert.equal(await evaluate(session, 'document.getElementById("download-query").disabled'), false);
    }
    const outside = await readRows("platform-outside");
    await change(session, "state", "outside");
    await waitFor(session, 'document.getElementById("evidence-status").textContent.startsWith("Views ")');
    const outsideDownload = await download(session, outside, "all outside-organization views");
    assert.equal(await evaluate(session, 'document.querySelectorAll("#org-coverage tbody tr:not([hidden])").length'), 0);
    await change(session, "collection", "bill_metadata");
    await change(session, "state", "ME");
    await waitFor(session, 'document.getElementById("evidence-status").textContent.startsWith("No matching")');
    assert.equal(await evaluate(session, 'document.querySelectorAll("#evidence article").length'), 0);
    const maineScope = await evaluate(session, 'document.getElementById("selection-scope").textContent');
    assert.ok(maineScope.includes("date/cohort evidence unavailable"));
    assert.ok(maineScope.includes("9877 retained wider-history source contexts"));
    assert.ok(maineScope.includes("not zero legislative activity"));
    const maineDownload = await download(session, [], "ME missing cycle cohort");
    const receiptDownloads = [];
    let receiptRows = [];
    if (hasReceipt) {
      receiptRows = await readRows("receipts-ME");
      assert.equal(receiptRows.length, fixture === "fixture" ? 2 : 62);
      assert.ok(receiptRows.every(row => row.source_type === "source_receipt"
        && row.analytical_admission === false && row.native_evidence === false
        && row.eligible_cycle_admission === false && row.model_input_approved === false));
      assert.ok(receiptRows.every(row => row.source_context.original_bill.title === row.source_bill.title));
      assert.equal(buildManifest.counts.source_receipt_evidence.target_calendar_interest_views,
        receiptRows.length);
      await change(session, "collection", "source_receipt");
      await waitFor(session, `document.querySelectorAll("#evidence article").length === ${Math.min(10, receiptRows.length)}`);
      assert.equal(await evaluate(session, 'document.getElementById("receipt-status").disabled'), false);
      assert.ok((await evaluate(session, 'document.getElementById("selection-scope").textContent'))
        .includes("0 active cycle candidate contexts remain unchanged"));
      assert.ok((await evaluate(session, 'document.getElementById("evidence-status").textContent'))
        .includes("not cycle candidates"));
      if (receiptRows.length > 10) {
        await evaluate(session, 'document.getElementById("next").click()');
      }
      receiptDownloads.push(await download(session, receiptRows, "ME all separate receipts including unresolved"));
      await search(session, "LD 2081");
      const discrepant = receiptRows.filter(row => row.identifier === "LD 2081");
      assert.equal(discrepant.length, 1);
      await waitFor(session, 'document.querySelectorAll("#evidence article").length === 1');
      assert.equal(discrepant[0].source_action.date, "2023-12-20");
      assert.equal(discrepant[0].observation.literal_calendar_date, "2022-12-20");
      const dates = await evaluate(session, 'document.querySelector("#evidence .receipt-dates").textContent');
      assert.ok(dates.includes("2023-12-20") && dates.includes("2022-12-20"));
      assert.ok((await evaluate(session, 'document.querySelector("#evidence .receipt-observation").textContent'))
        .includes("unresolved receipt observation"));
      receiptDownloads.push(await download(session, discrepant, "ME LD 2081 both discrepant dates and original full fields"));
      await search(session, "");
      await change(session, "receipt-status", "unresolved_receipt");
      await waitFor(session, 'document.querySelectorAll("#evidence article").length === 1');
      receiptDownloads.push(await download(session, discrepant, "ME unresolved receipt status filter"));
      await change(session, "receipt-status", "unique_origin_date_agreeing");
      const agreeing = receiptRows.filter(row => row.receipt_status === "unique_origin_date_agreeing");
      assert.equal(agreeing.length, fixture === "fixture" ? 1 : 61);
      await waitFor(session, `document.querySelectorAll("#evidence article").length === ${Math.min(10, agreeing.length)}`);
      receiptDownloads.push(await download(session, agreeing, "ME only unique origin date agreeing receipts"));
      await change(session, "receipt-status", "");
      await change(session, "state", "TX");
      await waitFor(session, 'document.getElementById("evidence-status").textContent.startsWith("Receipt coverage unknown")');
      assert.ok((await evaluate(session, 'document.getElementById("selection-scope").textContent'))
        .includes("not a measured zero"));
      assert.equal(await evaluate(session, 'document.getElementById("download-query").disabled'), true);
      assert.equal(requests.filter(entry => entry.url.includes("receipts-TX")).length, 0);
      await change(session, "state", "ME");
      await change(session, "collection", "bill_metadata");
      await waitFor(session, 'document.getElementById("evidence-status").textContent.startsWith("No matching")');
      assert.equal(await evaluate(session, 'document.getElementById("receipt-status").disabled'), true);
      assert.ok((await evaluate(session, 'document.getElementById("selection-scope").textContent'))
        .includes("9877 retained wider-history source contexts"));
      assert.equal(await evaluate(session, 'document.querySelectorAll("#evidence article").length'), 0);
      if (fixture === "fixture") {
        assert.equal(await evaluate(session, 'typeof window.EVIDENCE_INJECTED'), "undefined");
      }
    }
    const montanaDownloads = [];
    if (hasNative && fixture !== "fixture") {
      const montana = await readRows("bills-MT");
      const nativeDateOnly = montana.filter(row => row.cohort_scope === "native_reported_date_candidate");
      assert.equal(nativeDateOnly.length, 1640, "Additional Montana native-date-only metadata cohort");
      assert.ok(montana.every(row => row.n_input_tokens === null && row.token_plan?.n_discarded_tokens === 0));
      const prefilings = nativeDateOnly.filter(row => row.session_identifier === "2025"
        && row.bill_context.native_introduction_date?.startsWith("2024-"));
      assert.equal(prefilings.length, 213, "Calendar 2024 observations in declared 2025 session");
      await change(session, "state", "MT");
      await waitFor(session, 'document.querySelectorAll("#evidence article").length === 10');
      await evaluate(session, 'document.getElementById("next").click()');
      montanaDownloads.push(await download(session, montana, "MT complete expanded metadata and token planning from page 2"));
      await search(session, prefilings[0].bill_id);
      const selected = montana.filter(row => row.bill_id === prefilings[0].bill_id);
      await waitFor(session, `document.querySelectorAll("#evidence article").length === ${selected.length}`);
      assert.ok((await evaluate(session, 'document.querySelector("#evidence article").textContent'))
        .includes("not a source-coded bill date"));
      montanaDownloads.push(await download(session, selected, "MT calendar 2024 prefiling in session 2025"));
      await search(session, "");
      await change(session, "collection", "native_text");
      await waitFor(session, 'document.getElementById("evidence-status").textContent.startsWith("No matching")');
      montanaDownloads.push(await download(session, [], "MT date observations are not native policy text"));
      assert.ok((await evaluate(session, 'document.getElementById("selection-scope").textContent'))
        .includes("not evidence of source absence"));
    }

    const sessionDownloads = [], sessionScopes = [];
    if (hasSessionText) {
      const { filterEvidence } = require(path.join(preview, "cycle-evidence.js"));
      for (const [scope, binding] of Object.entries(buildManifest.inputs.native_session_scopes)) {
        const stateCode = binding.state, partition = `native-session-${stateCode}`;
        const values = buildManifest.counts.native_session_source_evidence.scopes[scope];
        const prefixes = new Map();
        let views = 0;
        for await (const row of sourceRows(partition)) {
          assert.equal(row.source_type, "native_session_text");
          assert.equal(row.evidence_scope, scope);
          assert.ok(row.bill_id && !row.bill_context && !row.title && !row.token_plan);
          assert.ok(row.candidate_cohort_member === false && row.eligible_cycle_admission === false
            && row.native_identity_certified === false && row.model_input_approved === false
            && row.training_admission === false && row.analytical_admission === false);
          assert.equal(createHash("sha256").update(row.text).digest("hex"), row.input_sha256);
          for (const width of [1, 2]) {
            const prefix = row.context_id.slice(0, -width);
            prefixes.set(prefix, (prefixes.get(prefix) || 0) + 1);
          }
          views++;
        }
        assert.equal(views, values.exported_views);
        const needle = fixture === "fixture" ? "SESSION-TAIL-"
          : [...prefixes].filter(([, count]) => count > 10 && count < 200)
            .sort((a, b) => a[1] - b[1])[0]?.[0];
        assert.ok(needle, "Need a finite actual publisher-session query beyond page 1");
        const selected = [];
        for await (const row of sourceRows(partition)) {
          if (filterEvidence([row], needle).length) selected.push(row);
        }
        assert.ok(selected.length > 10);
        await change(session, "state", stateCode);
        await change(session, "collection", "native_session_text");
        await waitFor(session, 'document.getElementById("evidence-status").textContent.startsWith("Views ")');
        assert.ok((await evaluate(session, 'document.getElementById("selection-scope").textContent'))
          .includes("OUTSIDE candidate date cohort, not native/date/analytical admission"));
        assert.ok((await evaluate(session, 'document.getElementById("evidence-status").textContent'))
          .includes(`${values.exported_unique_canonical_bills.toLocaleString("en-US")} unique canonical bill IDs`));
        await search(session, needle);
        await waitFor(session, `document.getElementById("download-query").textContent.includes("all ${selected.length.toLocaleString("en-US")} query")`);
        const firstRecord = await evaluate(session, 'document.querySelector("#evidence .record-id").textContent');
        await evaluate(session, 'document.getElementById("next").click()');
        assert.notEqual(await evaluate(session, 'document.querySelector("#evidence .record-id").textContent'), firstRecord);
        sessionDownloads.push(await download(session, selected, `${stateCode} complete session source query beyond page 1`));
        assert.ok((await evaluate(session, 'document.querySelector("#evidence .session-observation").textContent'))
          .includes("No date was required or inferred"));
        await search(session, selected[0].bill_id);
        const byBill = selected.filter(row => row.bill_id === selected[0].bill_id);
        const allBill = [];
        for await (const row of sourceRows(partition)) {
          if (filterEvidence([row], selected[0].bill_id).length) allBill.push(row);
        }
        assert.ok(allBill.length >= byBill.length);
        await waitFor(session, `document.querySelectorAll("#evidence article").length === ${Math.min(10, allBill.length)}`);
        sessionDownloads.push(await download(session, allBill, `${stateCode} exact canonical ID session text query`));
        const displayedHash = await evaluate(session, `(async () => {
          const text = [...document.querySelector("#evidence article").querySelectorAll(".source-text")].at(-1).textContent;
          const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
          return [...new Uint8Array(bytes)].map(value => value.toString(16).padStart(2, "0")).join("");
        })()`);
        assert.equal(displayedHash, allBill[0].input_sha256);
        sessionScopes.push({ scope, views, references: values.exported_references,
          unique_canonical_bills: values.exported_unique_canonical_bills,
          candidate_excluded_views: values.candidate_excluded_views, searched_views: selected.length });
        await search(session, "");
      }
      const suppliedStates = Object.values(buildManifest.inputs.native_session_scopes)
        .map(binding => binding.state);
      const unknownState = await evaluate(session, `[...document.getElementById("state").options]
        .map(option => option.value).find(value => /^[A-Z]{2}$/.test(value)
          && !${JSON.stringify(suppliedStates)}.includes(value))`);
      if (unknownState) {
        await change(session, "state", unknownState);
        await waitFor(session, 'document.getElementById("evidence-status").textContent.startsWith("Publisher-session source coverage unknown")');
        assert.equal(await evaluate(session, 'document.getElementById("download-query").disabled'), true);
        assert.equal(requests.filter(entry => entry.url.includes(`native-session-${unknownState}`)).length, 0);
      }
    }

    const archiveDownloads = [];
    let crossContextProof = null;
    if (hasArchive) {
      const storedRows = (await readRows("archive-TX"))
        .filter(row => row.archive_provider === "Bill Commons");
      for (const row of storedRows) {
        await change(session, "state", "TX");
        await change(session, "collection", "archive_text");
        await search(session, row.view_id);
        await waitFor(session, `document.querySelector("#evidence article .source-text")?.textContent
          === ${JSON.stringify(row.text)}`);
        const notice = await evaluate(session,
          'document.querySelector(".stored-text-observation").textContent');
        assert.ok(notice.includes(row.source_session.identifier));
        assert.ok(notice.includes(row.source_session.start_date));
        assert.ok(notice.includes(row.source_session.end_date));
        assert.ok(notice.includes(row.original_target_context.source_introduction_date));
        assert.ok(notice.includes("do not override original context dates"));
        assert.ok(notice.includes("raw publisher PDF/HTML bytes"));
        assert.ok(!notice.includes("Exact printed state, session and own bill identity match"));
        const metadata = JSON.parse(await evaluate(session,
          'document.querySelectorAll("#evidence article .source-text")[1].textContent'));
        assert.deepEqual(metadata.source_session, row.source_session);
        assert.deepEqual(metadata.original_target_context, row.original_target_context);
        assert.equal(metadata.raw_publisher_PDF_or_HTML_bytes_supplied, false);
        assert.equal(metadata.provider_dates_preserved_not_original_context_overrides, true);
        archiveDownloads.push(await download(session, [row],
          "complete stored extraction and separate original/provider session metadata"));
        await search(session, "");
      }
      const publishedRows = (await readRows("archive-TX"))
        .filter(row => row.source_type === "published_corpus_text");
      if (publishedRows.length) {
        await change(session, "state", "TX");
        await change(session, "collection", "archive_text");
        await search(session, publishedRows[0].view_id);
        await waitFor(session, `document.querySelector("#evidence article .source-text")?.textContent
          === ${JSON.stringify(publishedRows[0].text)}`);
        const notice = await evaluate(session,
          'document.querySelector(".published-corpus-observation").textContent');
        assert.ok(notice.includes("not model inputs or human gold"));
        const metadata = JSON.parse(await evaluate(session,
          'document.querySelectorAll("#evidence article .source-text")[1].textContent'));
        assert.equal(metadata.publisher_prologue, publishedRows[0].publisher_prologue);
        assert.deepEqual(metadata.native_body_source_span, publishedRows[0].native_body_source_span);
        assert.deepEqual(metadata.source_record, publishedRows[0].source_record);
        archiveDownloads.push(await download(session, [publishedRows[0]],
          "published-corpus complete policy body and original source metadata"));
        await search(session, "");
      }
      const carryoverRows = (await readRows("archive-TX"))
        .filter(row => row.source_identity?.explicit_original_carryover_evidence);
      if (carryoverRows.length) {
        const row = carryoverRows[0];
        await change(session, "state", "TX");
        await change(session, "collection", "archive_text");
        await search(session, row.view_id);
        await waitFor(session, `document.querySelector("#evidence article .source-text")?.textContent
          === ${JSON.stringify(row.text)}`);
        const note = await evaluate(session,
          'document.querySelector(".carryover-action-observation").textContent');
        assert.ok(note.includes("Printed source year 2023"));
        assert.ok(note.includes("original bill-specific carryover"));
        assert.ok(note.includes("not inferred from annual-session or URL aliases"));
        assert.ok(!note.includes("Exact printed state, session and own bill identity match"));
        const metadata = JSON.parse(await evaluate(session,
          'document.querySelectorAll("#evidence article .source-text")[1].textContent'));
        assert.deepEqual(metadata.source_identity, row.source_identity);
        archiveDownloads.push(await download(session, [row],
          "complete carryover body and original distinct-year action evidence"));
        await search(session, "");
      }
      let linked;
      for await (const row of sourceRows("archive-OK")) {
        if (!linked && row.context_relation?.kind === "same_legislature_exact_existing_document_pointer") {
          linked = row;
        }
      }
      if (linked) {
        await change(session, "state", "OK");
        await change(session, "collection", "archive_text");
        await waitFor(session, 'document.getElementById("evidence-status").textContent.startsWith("Views ")');
        await search(session, linked.view_id);
        await waitFor(session, 'document.querySelectorAll("#evidence article").length === 1');
        const notice = await evaluate(session,
          'document.querySelector("#evidence .archive-observation").textContent');
        assert.ok(notice.includes(`Retained source session ${linked.context_relation.source_session_identifier}`));
        assert.ok(notice.includes(`candidate session ${linked.context_relation.target_session_identifier}`));
        assert.ok(notice.includes("not session aliases or a canonical bill merge"));
        assert.ok(notice.includes("not evidence of target-year filing"));
        assert.ok(!notice.includes("Exact printed state, session and own bill identity match"));
        assert.ok(!notice.includes("retained PDF extraction"));
        const bodyHash = await evaluate(session, `(async () => {
          const text = document.querySelector("#evidence article .source-text").textContent;
          const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
          return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, "0")).join("");
        })()`);
        assert.equal(bodyHash, createHash("sha256").update(linked.text).digest("hex"));
        const provenance = JSON.parse(await evaluate(session,
          'document.querySelectorAll("#evidence article .source-text")[1].textContent'));
        assert.deepEqual(provenance.context_relation, linked.context_relation);
        assert.deepEqual(provenance.original_source_context, linked.original_source_context);
        assert.deepEqual(provenance.original_target_context, linked.original_target_context);
        archiveDownloads.push(await download(session, [linked],
          "OK linked full body and retained original context provenance"));
        crossContextProof = {
          view_id: linked.view_id, source: linked.context_relation.source_session_identifier,
          target: linked.context_relation.target_session_identifier,
          displayed_body_sha256: bodyHash, distinct_contexts_disclosed: true,
        };
        await search(session, "");
      }
    }

    await send("Emulation.setDeviceMetricsOverride", {
      width: 390, height: 844, deviceScaleFactor: 1, mobile: true,
    }, session);
    await send("Page.navigate", { url: base + "/" }, session);
    await waitFor(session, 'document.readyState === "complete"');
    assert.ok(await evaluate(session, "document.documentElement.scrollWidth <= innerWidth"));
    const mobile = await evaluate(session, `({
      viewport: innerWidth, document: document.documentElement.scrollWidth,
      state: document.getElementById("state").getBoundingClientRect().width
    })`);
    assert.ok(mobile.state <= 342, JSON.stringify(mobile));
    await change(session, "state", "TX");
    await waitFor(session, 'document.querySelectorAll("#evidence article").length === 10');
    const screenshot = await send("Page.captureScreenshot", { format: "png" }, session);
    await fs.writeFile(path.join(run, "mobile.png"), Buffer.from(screenshot.data, "base64"));

    const noJS = await target(base + "/", false);
    const additionalTextTiers = [hasSnapshot, hasCorpus, hasArchive].filter(Boolean).length;
    assert.equal(await evaluate(noJS.sessionId, 'document.querySelectorAll("tbody tr").length'),
      150 + (hasReceipt ? 50 : 0) + (hasSessionText ? 50 : 0) + 50 * additionalTextTiers);
    assert.equal(await evaluate(noJS.sessionId, 'document.querySelectorAll("a[download][href$=\'.jsonl.gz\']").length'),
      (hasNative ? 201 : 151) + (hasReceipt ? 1 : 0) + sessionScopes.length
        + 50 * additionalTextTiers);
    if (hasNative) {
      assert.equal(await evaluate(noJS.sessionId, 'document.querySelectorAll("#state-coverage a[download][href^=\'downloads/native-\']").length'), 50);
    }
    if (hasReceipt) {
      assert.equal(await evaluate(noJS.sessionId,
        '[...document.querySelectorAll("#receipt-coverage tbody tr")].filter(row => row.textContent.includes("Unknown")).length'), 49);
      receiptDownloads.push(await download(noJS.sessionId, receiptRows,
        "ME no JS complete original receipt gzip download",
        '#receipt-coverage a[href="downloads/receipts-ME.jsonl.gz"]', true));
    }
    if (hasSessionText) {
      assert.equal(await evaluate(noJS.sessionId,
        '[...document.querySelectorAll("#session-coverage tbody tr")].filter(row => row.textContent.includes("Unknown")).length'),
      50 - sessionScopes.length);
      for (const { scope } of sessionScopes) {
        const stateCode = buildManifest.inputs.native_session_scopes[scope].state;
        for (const compressed of [false, true]) {
          sessionDownloads.push(await download(noJS.sessionId,
            () => sourceRows(`native-session-${stateCode}`),
            `${stateCode} no JS complete session source ${compressed ? "gzip" : "plain"} download`,
            `#session-coverage a[href="${compressed ? "downloads" : "evidence"}/native-session-${stateCode}.jsonl${compressed ? ".gz" : ""}"]`,
            compressed));
        }
      }
    }
    assert.ok(await evaluate(noJS.sessionId, 'document.querySelector("noscript").textContent.includes("without it")'));
    assert.equal(requests.filter(entry => entry.session === noJS.sessionId && entry.url.includes("/evidence/")).length, 0);
    assert.equal(exceptions.length, 0, "Unexpected real-browser JavaScript errors");
    receipt = {
      browser: version.product, transport: "real Chromium DevTools protocol, Node built-in WebSocket",
      preview, fixture: fixture === "fixture", states: 50, organizations: 100,
      checks: ["lazy loading", "state/source/party filters", "pagination", "literal search",
        "complete actual query downloads", "empty query/status", "markup rendered as text",
        "keyboard skip link", "390px mobile layout", "no-JS coverage and full-text links"],
      downloads: [billsDownload, searchDownload, emptyQueryDownload, platformDownload,
        outsideDownload, maineDownload, ...nativeDownloads, ...montanaDownloads, ...receiptDownloads,
        ...sessionDownloads, ...archiveDownloads],
      native_full_text: hasNative, verified_metadata_token_plan: Boolean(billRows[0].token_plan),
      maine_missing_cycle_cohort_disclosed: true,
      separate_receipt_evidence: hasReceipt, receipt_observations: receiptRows.length,
      receipt_unknown_states: hasReceipt ? 49 : null,
      receipt_discrepant_dates_preserved: hasReceipt,
      separate_publisher_session_evidence: hasSessionText, publisher_session_scopes: sessionScopes,
      separate_archive_evidence: hasArchive, original_annual_context_disclosure: crossContextProof,
      archived_producer_source_files: Object.keys(buildManifest.producer_archive || {}).length,
      javascript_exceptions: exceptions.length, no_js_evidence_requests: 0,
    };
  } finally {
    for (const item of pending.values()) clearTimeout(item.timer);
    if (socket) socket.close();
    await Promise.all([terminate(browser), terminate(server)]);
    for (const name of ["profile", "cache", "browser-runtime"]) {
      await fs.rm(path.join(run, name), { recursive: true, force: true });
    }
  }
  assert.ok(browser.exitCode !== null || browser.signalCode !== null);
  assert.ok(server.exitCode !== null || server.signalCode !== null);
  receipt.processes_stopped = true;
  await fs.writeFile(path.join(run, "receipt.json"), JSON.stringify(receipt, null, 2) + "\n");
  console.log(JSON.stringify(receipt));
})().catch(error => { console.error(error); process.exitCode = 1; });

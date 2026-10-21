// Real Chromium checks via its native DevTools protocol; no DOM emulator or new dependency.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { spawn } = require("node:child_process");

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
  for (let attempt = 0; attempt < 300; attempt++) {
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

async function download(session, expected, name) {
  const directory = path.join(run, "downloads", name.replace(/[^a-z0-9]+/gi, "-"));
  await fs.mkdir(directory, { recursive: true });
  await send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: directory });
  await evaluate(session, 'document.getElementById("download-query").click()');
  for (let attempt = 0; attempt < 300; attempt++) {
    const names = (await fs.readdir(directory)).filter(entry => entry.endsWith(".jsonl"));
    if (names.length) {
      const saved = path.join(directory, names[0]);
      const rows = (await fs.readFile(saved, "utf8")).split("\n").filter(Boolean).map(JSON.parse);
      assert.deepEqual(rows, expected, `${name}: actual full-query download differs from complete source`);
      return { file: path.relative(run, saved), rows: rows.length };
    }
    await sleep(100);
  }
  throw new Error(`Browser download did not complete: ${name}`);
}

async function readRows(name) {
  const text = await fs.readFile(path.join(preview, "evidence", name + ".jsonl"), "utf8");
  return text.split("\n").filter(Boolean).map(JSON.parse);
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
    const buildManifest = JSON.parse(await fs.readFile(
      path.join(preview, "downloads/build_manifest.json"), "utf8"));
    assert.ok(billRows.every(row => row.source_bundle_manifest_sha256
      === buildManifest.inputs.bill_metadata["manifest.json"]));
    assert.ok(billRows.length > 10);
    await change(session, "state", "TX");
    await waitFor(session, 'document.querySelectorAll("#evidence article").length === 10');
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
    assert.equal(await evaluate(noJS.sessionId, 'document.querySelectorAll("tbody tr").length'), 150);
    assert.equal(await evaluate(noJS.sessionId, 'document.querySelectorAll("a[download][href$=\'.jsonl.gz\']").length'), 151);
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
        outsideDownload, maineDownload],
      maine_missing_cycle_cohort_disclosed: true,
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

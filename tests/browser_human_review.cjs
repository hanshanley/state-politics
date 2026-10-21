// Real Chromium/CDP; all annotation activity is explicitly SYNTHETIC, never human gold.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const http = require("node:http");
const {spawn} = require("node:child_process");
const {createHash} = require("node:crypto");
const root = path.resolve(__dirname, "..");
const [fixtureArg, runArg, chromeArg, actualArg] = process.argv.slice(2);
if (!fixtureArg || !runArg || !(chromeArg || process.env.CYCLE_BROWSER_CHROME) ||
    typeof WebSocket === "undefined") throw Error(
  "Usage: node tests/browser_human_review.cjs FIXTURE RUN CHROMIUM [ACTUAL_PACKET]");
const fixture = path.resolve(fixtureArg), run = path.resolve(runArg);
const actual = actualArg ? path.resolve(actualArg) : null;
for (const directory of [fixture, run, ...(actual ? [actual] : [])])
  assert.ok(directory.startsWith(path.join(root, "data") + path.sep), "Use ignored project data only");
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
let browser, server, socket, sequence = 0;
const pending = new Map(), exceptions = [], requests = [];
function send(method, params = {}, sessionId) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(Error(`Timeout: ${method}`)); }, 30000);
    pending.set(id, {resolve, reject, timer});
    socket.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
  });
}
async function evaluate(session, expression) {
  const result = await send("Runtime.evaluate", {expression, returnByValue:true, awaitPromise:true}, session);
  if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function wait(session, expression) {
  for (let i=0; i<300; i++) {
    if (await evaluate(session, expression)) return;
    await sleep(100);
  }
  throw Error(`Condition failed: ${expression}; ${await evaluate(session, "document.getElementById('status')?.textContent")}`);
}
async function page(url) {
  const {targetId} = await send("Target.createTarget", {url:"about:blank"});
  const {sessionId} = await send("Target.attachToTarget", {targetId, flatten:true});
  await send("Page.enable", {}, sessionId);
  await send("Runtime.enable", {}, sessionId);
  await send("Network.enable", {}, sessionId);
  await send("Page.navigate", {url}, sessionId);
  await wait(sessionId, "document.getElementById('workspace')?.hidden === false");
  return sessionId;
}
async function change(session, id, value) {
  await evaluate(session, `(() => { const e=document.getElementById(${JSON.stringify(id)});
    e.${typeof value === "boolean" ? "checked" : "value"}=${JSON.stringify(value)};
    e.dispatchEvent(new Event("input"));e.dispatchEvent(new Event("change")); })()`);
}
async function click(session, id) {
  await evaluate(session, `document.getElementById(${JSON.stringify(id)}).click()`);
}
async function downloaded(session, trigger, filename) {
  const directory = path.join(run, "downloads", String(++sequence));
  await fs.mkdir(directory, {recursive:true});
  await send("Browser.setDownloadBehavior", {behavior:"allow", downloadPath:directory});
  await evaluate(session, trigger);
  const file = path.join(directory, filename);
  for (let i=0; i<200; i++) {
    try { const bytes=await fs.readFile(file); if (bytes.length) return {file, bytes}; } catch {}
    await sleep(100);
  }
  throw Error(`No completed download: ${filename}`);
}
async function importFile(session, file) {
  const {root: dom} = await send("DOM.getDocument", {}, session);
  const {nodeId} = await send("DOM.querySelector", {nodeId:dom.nodeId, selector:"#import"}, session);
  await send("DOM.setFileInputFiles", {nodeId, files:[file]}, session);
}
async function terminate(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  const exited = new Promise(resolve => child.once("exit", resolve));
  child.kill("SIGTERM");
  await Promise.race([exited,sleep(3000)]);
  if (child.exitCode === null && child.signalCode === null) { child.kill("SIGKILL"); await exited; }
}
async function startChrome(env) {
  browser = spawn(chromeArg || process.env.CYCLE_BROWSER_CHROME, [
    "--headless=new", "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
    "--disable-background-networking", "--disable-component-update", "--disable-extensions",
    "--disable-default-apps", "--disable-sync", "--disable-breakpad", "--no-first-run",
    "--no-default-browser-check", `--user-data-dir=${path.join(run,"profile")}`,
    `--disk-cache-dir=${path.join(run,"cache")}`, "about:blank",
  ], {cwd:root, env, stdio:["ignore","pipe","pipe"]});
  const endpoint = await new Promise((resolve,reject) => {
    let text = "";
    const timer=setTimeout(() => reject(Error("Chromium readiness timeout")),30000);
    const read = chunk => {
      text += chunk;
      const match=text.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    };
    browser.stdout.on("data", read); browser.stderr.on("data", read);
    browser.once("error", reject); browser.once("exit", code => reject(Error(`Chromium exited ${code}`)));
  });
  socket = new WebSocket(endpoint);
  await new Promise((resolve,reject) => {
    socket.addEventListener("open", resolve, {once:true});
    socket.addEventListener("error", reject, {once:true});
  });
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const item=pending.get(message.id); if (!item) return;
      pending.delete(message.id); clearTimeout(item.timer);
      if (message.error) item.reject(Error(JSON.stringify(message.error))); else item.resolve(message.result);
    } else if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params);
    else if (message.method === "Network.requestWillBeSent") requests.push(message.params.request.url);
  });
}
(async () => {
  await fs.mkdir(run); // A fresh directory is required; never overwrite proof.
  const runtime=path.join(run,"browser-runtime"); await fs.mkdir(runtime);
  let receipt;
  try {
    server=http.createServer(async (request,response) => {
      try {
        const url=new URL(request.url,"http://127.0.0.1"), decoded=decodeURIComponent(url.pathname);
        const match=decoded.match(/^\/(fixture|actual)\/(.+)$/);
        const base=match && match[1] === "fixture" ? fixture : actual;
        if (!match || !base) { response.writeHead(404).end(); return; }
        const file=path.resolve(base,match[2]);
        if (!file.startsWith(base+path.sep)) { response.writeHead(403).end(); return; }
        const bytes=await fs.readFile(file);
        const types={".html":"text/html; charset=utf-8",".js":"text/javascript; charset=utf-8",
          ".css":"text/css; charset=utf-8",".json":"application/json",".jsonl":"application/x-ndjson"};
        response.writeHead(200, {"Content-Type":types[path.extname(file)] || "application/octet-stream"});
        response.end(bytes);
      } catch { response.writeHead(404).end(); }
    });
    await new Promise(resolve => server.listen(0,"127.0.0.1",resolve));
    const base=`http://127.0.0.1:${server.address().port}`;
    assert.equal((await fetch(`${base}/fixture/human-review.html`)).status,200);
    await startChrome({...process.env,TMPDIR:runtime,TMP:runtime,TEMP:runtime});
    const version=await send("Browser.getVersion");
    const session=await page(`${base}/fixture/human-review.html`);
    const fixtureData=JSON.parse(await fs.readFile(path.join(fixture,"ui-data.json"),"utf8"));
    assert.equal(fixtureData.records.length,2);
    assert.equal(await evaluate(session,'document.querySelectorAll("#decision option").length'),26);
    assert.equal(await evaluate(session,'document.querySelectorAll("#rubric h3").length'),21);
    assert.equal(await evaluate(session,'document.getElementById("decision").value'),"");
    assert.equal(await evaluate(session,'document.getElementById("reviewer").value'),"");
    await click(session,"export");
    await wait(session,'document.getElementById("status").textContent.startsWith("Export refused:")');
    await change(session,"reviewer","synthetic-browser-rater");
    await change(session,"reviewed-on",new Date().toISOString().slice(0,10));
    for (const id of ["human","no-model","all-full"]) await change(session,id,true);
    for (let i=0;i<fixtureData.records.length;i++) {
      await change(session,"record-picker",String(i));
      const expected=fixtureData.records[i];
      assert.equal(await evaluate(session,'document.getElementById("chosen-text").textContent'),expected.text);
      assert.equal(await evaluate(session,'document.querySelectorAll("#alternatives > details").length'),expected.alternatives.length);
      assert.equal(await evaluate(session,'document.querySelectorAll("#chosen-text img, #alternatives img, #chosen-text script").length'),0);
      assert.equal(await evaluate(session,'Boolean(window.sourceInjected)'),false);
      for (let j=0;j<expected.alternatives.length;j++) {
        const raw=await evaluate(session,`document.querySelectorAll("#alternatives > details")[${j}].querySelectorAll("pre")[1].textContent`);
        assert.equal(raw,expected.alternatives[j].raw_provenance);
      }
      await change(session,"decision",i===0 ? "topic:6" : "abstain:rubric_ambiguity");
      await change(session,"rationale","SYNTHETIC browser automation only; not a human judgment.");
      await change(session,"spans",expected.text.slice(0,25));
      await change(session,"full",true); await change(session,"input-only",true);
    }
    await send("Page.reload", {ignoreCache:true},session);
    await wait(session,'document.getElementById("status").textContent.startsWith("Local draft restored")');
    assert.equal(await evaluate(session,'document.getElementById("reviewer").value'),"synthetic-browser-rater");
    assert.equal(await evaluate(session,'document.getElementById("decision").value'),"topic:6");
    await change(session,"record-picker","1");
    assert.equal(await evaluate(session,'document.getElementById("decision").value'),"abstain:rubric_ambiguity");
    const exported=await downloaded(session,'document.getElementById("export").click()',
      "annotations-only-synthetic-browser-rater.json");
    const annotation=JSON.parse(exported.bytes);
    assert.equal(annotation.human_provenance,"SELF_ATTESTED_HUMAN_NOT_IDENTITY_CERTIFIED");
    assert.equal(annotation.decisions[1].abstention_reason,"rubric_ambiguity");
    const downloads=[];
    for (const [index,name,source] of [
      [0,"complete-inputs.zip","complete-inputs.zip"],
      [1,"review_packet.jsonl","complete-inputs/review_packet.jsonl"],
      [2,"selected_alternative_views.jsonl","complete-inputs/selected_alternative_views.jsonl"],
    ]) {
      const saved=await downloaded(session,`document.querySelectorAll("#downloads button")[${index}].click()`,name);
      assert.deepEqual(saved.bytes,await fs.readFile(path.join(fixture,source)));
      downloads.push({file:path.relative(run,saved.file),bytes:saved.bytes.length,sha256:sha(saved.bytes)});
    }
    await click(session,"clear");
    await wait(session,'document.getElementById("status").textContent === "Ready. No decisions prefilled."');
    assert.equal(await evaluate(session,'document.getElementById("decision").value'),"");
    await importFile(session,exported.file);
    await wait(session,'document.getElementById("status").textContent.startsWith("Imported self-attested")');
    assert.equal(await evaluate(session,'document.getElementById("decision").value'),"topic:6");
    const multiline=JSON.parse(exported.bytes);
    multiline.decisions[0].evidence_spans=[fixtureData.records[0].text];
    multiline.decisions[0].reviewed_on="2020-01-02";
    multiline.decisions[1].reviewed_on="2021-03-04";
    const multilinePath=path.join(run,"synthetic-multiline-annotations-only.json");
    await fs.writeFile(multilinePath,JSON.stringify(multiline));
    await importFile(session,multilinePath);
    await wait(session,'document.getElementById("reviewed-on").value === "2020-01-02"');
    const multilineExport=await downloaded(session,'document.getElementById("export").click()',
      "annotations-only-synthetic-browser-rater.json");
    assert.deepEqual(JSON.parse(multilineExport.bytes),multiline,
      "Imported exact multiline/CRLF evidence spans and per-record dates must survive re-export");
    const malformedCases=[
      ["foreign",{...annotation,packet_id:"foreign"}],
      ["boolean",{...annotation,no_model_assistance:1}],
      ["duplicate",{...annotation,decisions:[annotation.decisions[0],annotation.decisions[0]]}],
      ["topic-reason",{...annotation,decisions:annotation.decisions.map((r,i)=>i ? r : {...r,abstention_reason:"non_policy"})}],
      ["bad-hash",{...annotation,decisions:annotation.decisions.map((r,i)=>i ? r : {...r,input_sha256:"wrong"})}],
      ["missing",{...annotation,decisions:annotation.decisions.slice(0,1)}],
      ["invalid-evidence",{...annotation,decisions:annotation.decisions.map((r,i)=>i ? r : {...r,evidence_spans:["not in chosen source"]})}],
    ];
    for (const [name,bad] of malformedCases) {
      const file=path.join(run,`${name}-annotation.json`); await fs.writeFile(file,JSON.stringify(bad));
      await importFile(session,file);
      await wait(session,'document.getElementById("status").textContent.startsWith("Import refused:")');
      assert.equal(await evaluate(session,'document.getElementById("decision").value'),"topic:6");
    }
    for (const [name,text] of [
      ["duplicate-key",'{"schema":"x",'+JSON.stringify(annotation).slice(1)],
      ["malformed","{not-json"],
    ]) {
      const file=path.join(run,`${name}-annotation.json`); await fs.writeFile(file,text);
      await importFile(session,file);
      await wait(session,'document.getElementById("status").textContent.startsWith("Import refused:")');
    }
    const screenshot=await send("Page.captureScreenshot",{format:"png",captureBeyondViewport:false},session);
    await fs.writeFile(path.join(run,"synthetic-browser-proof.png"),Buffer.from(screenshot.data,"base64"));
    await evaluate(session,'document.getElementById("chosen-text").scrollIntoView()');
    const sourceScreenshot=await send("Page.captureScreenshot",{format:"png",captureBeyondViewport:false},session);
    await fs.writeFile(path.join(run,"synthetic-source-proof.png"),Buffer.from(sourceScreenshot.data,"base64"));
    await evaluate(session,'document.getElementById("decision").scrollIntoView()');
    const decisionScreenshot=await send("Page.captureScreenshot",{format:"png",captureBeyondViewport:false},session);
    await fs.writeFile(path.join(run,"synthetic-decision-proof.png"),Buffer.from(decisionScreenshot.data,"base64"));
    let actualProof=null;
    if (actual) {
      // No actual source text, provenance, screenshot, or decisions are returned to the evaluator.
      const actualSession=await page(`${base}/actual/human-review.html`);
      actualProof=await evaluate(actualSession,`(() => ({
        record_options:document.getElementById("record-picker").options.length,
        topic_definitions:document.querySelectorAll("#rubric h3").length,
        decision_is_blank:document.getElementById("decision").value==="",
        reviewer_is_blank:document.getElementById("reviewer").value==="",
        source_injection:Boolean(window.sourceInjected)
      }))()`);
      assert.ok(actualProof.record_options>0);
      assert.equal(actualProof.decision_is_blank,true); assert.equal(actualProof.reviewer_is_blank,true);
      assert.equal(actualProof.topic_definitions,21); assert.equal(actualProof.source_injection,false);
    }
    assert.equal(exceptions.length,0);
    // Chromium's native date control uses an internal data: calendar icon.
    const external=requests.filter(url => /^(https?|wss?):/.test(url) && !url.startsWith(base+"/"));
    assert.deepEqual(external,[]);
    receipt={status:"passed",scope:"SYNTHETIC automation, not human annotation or model certification",
      chromium:version,checks:["load","21-topic-rubric","no-prefill","label","abstention","rationale",
        "reload-draft-recovery","annotation-export","annotation-import","complete-source-byte-downloads",
        "multiline-CRLF-evidence-and-per-record-dates-roundtrip",
        "giant-integer-and-Unicode-preserved","malformed-and-foreign-import-refusal","no-source-injection",
        "no-external-requests"],downloads,
      annotation_export:{file:path.relative(run,exported.file),sha256:sha(exported.bytes)},
      screenshots:["synthetic-browser-proof.png","synthetic-source-proof.png","synthetic-decision-proof.png"],
      actual_packet_blind_smoke:actualProof,
      runtime_exceptions:exceptions,external_requests:external};
    await fs.writeFile(path.join(run,"browser_receipt.json"),JSON.stringify(receipt,null,2)+"\n");
    console.log(JSON.stringify(receipt,null,2));
  } finally {
    if (socket) socket.close();
    for (const item of pending.values()) clearTimeout(item.timer);
    await terminate(browser);
    if (server) await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode=1; });

import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "scripts/build_classification_inspector.py"))
FLAGS = dict.fromkeys(MODULE["FLAGS"], False)
CODES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, None]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n")


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def inspector_sources(tmp_path, monkeypatch):
    job, majority = tmp_path / "job", tmp_path / "majority"
    text = "prologue 😀\nComplete\u2028policy\u2029text with 😀 and a final clause."
    span = [text.index("Complete"), len(text)]
    source = {
        "input_id": "retained_text:v1",
        "bill_id": "bill1",
        "state": "AK",
        "input_sha256": digest(text[span[0] : span[1]]),
        "source_text_span": span,
        "raw_source_text_sha256": digest(text),
        "original_source_view": {
            "source_type": "snapshot_text",
            "source_record": {"raw_text": text, "large_id": 9007199254740999},
        },
        **FLAGS,
    }
    write(job / "inputs/retained_text-AK.jsonl", source)
    plan = {
        "topics_path": str(ROOT / "conf/topics.yml"),
        "decision": {
            "temperature": 1.0,
            "min_confidence": 0.8,
            "min_margin": 0.2,
        },
    }
    write(job / "inference_plan.json", plan)
    candidate = {
        "status": "classified",
        "topic": 1,
        "reason": None,
        "source_disagreement_or_uncertainty": False,
        "window_disagreement_present": True,
    }
    context = {
        "bill_id": "bill1",
        "state": "AK",
        "identifier": "HB 1",
        "title": "A complete policy",
        "session_identifier": "2023",
        "topic": None,
        "inference_status": "abstained",
        "abstention_reason": "chunk_disagreement",
        "n_source_views": 1,
        "majority_candidate": candidate,
        **FLAGS,
    }
    missing = {
        **context,
        "bill_id": "bill2",
        "identifier": "HB 2",
        "title": None,
        "inference_status": "unavailable",
        "abstention_reason": "no_supplied_text",
        "n_source_views": 0,
        "majority_candidate": {
            "status": "unavailable",
            "topic": None,
            "reason": "no_supplied_text",
        },
    }
    path = majority / "decisions/context_assignments.jsonl"
    write(path, context)
    with path.open("a") as stream:
        stream.write(json.dumps(missing) + "\n")
    prediction = {
        "input_id": source["input_id"],
        "bill_id": "bill1",
        "state": "AK",
        "input_sha256": source["input_sha256"],
        "output_codes": json.dumps(CODES),
        "topic": None,
        "majority_candidate": candidate,
        **FLAGS,
    }
    write(majority / "decisions/source_decisions.jsonl", prediction)
    archive = majority / MODULE["ARCHIVE"]
    archive.parent.mkdir(parents=True)
    with ZipFile(archive, "w") as output:
        output.write(job / "inputs/retained_text-AK.jsonl", "complete-inputs.jsonl")
    manifest = {
        "output_codes": CODES,
        **FLAGS,
        "independent_human_validation": False,
        "original_source_views": 1,
        "original_contexts": 2,
        "candidate_status_counts": {"classified": 1, "unavailable": 1},
        "policy": "strict-majority-fixture",
        "policy_run": "a" * 64,
        "source_inference_inputs": {
            "inputs/retained_text-AK.jsonl": MODULE["binding"](
                job / "inputs/retained_text-AK.jsonl"
            ),
        },
        "artifacts": {
            str(path.relative_to(majority)): MODULE["binding"](path)
            for path in majority.rglob("*")
            if path.is_file()
        },
    }
    write(majority / "manifest.json", manifest)
    monkeypatch.setitem(MODULE["build"].__globals__, "checked_job", lambda _: plan)
    return job, majority, manifest, source, tmp_path / "inspector"


def build_fixture(values):
    job, majority, _, _, output = values
    return MODULE["build"](
        job, majority, MODULE["binding"](majority / "manifest.json")["sha256"], output
    )


def test_inspector_preserves_complete_raw_records_ranges_unicode_and_missingness(inspector_sources):
    job, _, _, source, output = inspector_sources
    result = build_fixture(inspector_sources)
    assert result["original_contexts"] == 2 and result["original_source_views"] == 1
    index = json.loads((output / "states/AK.json").read_bytes())["records"]
    actual, missing = index
    assert actual["baseline_topic"] is None and actual["candidate_topic"] == 1
    assert missing["candidate_status"] == "unavailable" and missing["sources"] == []
    assert len(json.loads((output / "config.json").read_bytes())["states"]) == 50
    evidence = actual["sources"][0]
    for reference in (actual["context"], evidence["input"], evidence["prediction"]):
        with (output / reference["path"]).open("rb") as stream:
            stream.seek(reference["offset"])
            raw = stream.read(reference["length"])
        assert hashlib.sha256(raw).hexdigest() == reference["sha256"]
        assert json.loads(raw)["bill_id"] == "bill1"
    assert (output / evidence["input"]["path"]).read_bytes() == (
        job / "inputs/retained_text-AK.jsonl"
    ).read_bytes()
    raw = source["original_source_view"]["source_record"]["raw_text"]
    left, right = evidence["utf16_span"]
    selected = raw.encode("utf-16-le")[left * 2 : right * 2].decode("utf-16-le")
    assert selected == MODULE["input_text"](source)
    assert evidence["characters"] == len(selected)
    assert evidence["astral_offsets"] == [selected.index("😀")]
    assert b"9007199254740999" in (output / evidence["input"]["path"]).read_bytes()
    assert b"Unassigned" in (output / "states/AK.html").read_bytes()
    assert (output / MODULE["ARCHIVE"]).read_bytes().startswith(b"PK")


@pytest.mark.skipif(sys.platform != "darwin", reason="requires native APFS clone support")
def test_inspector_build_clones_complete_evidence_without_full_copy(
    inspector_sources,
    monkeypatch,
):
    from state_politics import storage

    job, majority, _, _, output = inspector_sources
    original_clone = storage.native_clone
    calls = []

    def clone(source, target):
        original_clone(source, target)
        calls.append((source, target))

    monkeypatch.setattr(storage, "native_clone", clone)
    monkeypatch.setattr(
        storage.shutil, "copyfileobj", lambda *args: pytest.fail("must not make a full copy")
    )
    result = build_fixture(inspector_sources)
    for source, target in (
        (
            job / "inputs/retained_text-AK.jsonl",
            output / "evidence/job/inputs/retained_text-AK.jsonl",
        ),
        (majority / "decisions/source_decisions.jsonl", output / "evidence/source_decisions.jsonl"),
        (majority / MODULE["ARCHIVE"], output / MODULE["ARCHIVE"]),
    ):
        assert (source, target) in calls
        assert MODULE["binding"](source) == MODULE["binding"](target)
        assert source.stat().st_ino != target.stat().st_ino
    source, target = calls[-1]
    before = source.read_bytes()
    target.write_bytes(b"later independent output")
    assert source.read_bytes() == before
    helper = output / "producers/storage.py"
    assert result["artifacts"]["producers/storage.py"] == MODULE["binding"](helper)
    assert helper.read_bytes() == (ROOT / "src/state_politics/storage.py").read_bytes()


def test_inspector_preserves_sources_and_failure_when_cloning_is_unavailable(
    inspector_sources,
    monkeypatch,
):
    job, majority, _, _, output = inspector_sources
    originals = {
        path: MODULE["binding"](path)
        for directory in (job, majority)
        for path in directory.rglob("*")
        if path.is_file()
    }
    original_copy = MODULE["copy_evidence"]

    def unavailable(source, target):
        if target.name == "context_assignments.jsonl":
            raise OSError("native cloning unsupported")
        return original_copy(source, target)

    monkeypatch.setitem(MODULE["build"].__globals__, "copy_evidence", unavailable)
    with pytest.raises(OSError, match="unsupported"):
        build_fixture(inspector_sources)
    assert output.is_dir() and not (output / "manifest.json").exists()
    assert not (output / "evidence/context_assignments.jsonl").exists()
    assert all(MODULE["binding"](path) == expected for path, expected in originals.items())


@pytest.mark.parametrize(
    "defect", ["source-sha", "missing-prediction", "changed-topic", "approval"]
)
def test_inspector_rejects_broken_joins_or_promoted_records(inspector_sources, defect):
    job, majority, manifest, source, _ = inspector_sources
    if defect == "source-sha":
        source["input_sha256"] = "b" * 64
        write(job / "inputs/retained_text-AK.jsonl", source)
        manifest["source_inference_inputs"]["inputs/retained_text-AK.jsonl"] = MODULE["binding"](
            job / "inputs/retained_text-AK.jsonl"
        )
    elif defect == "missing-prediction":
        (majority / "decisions/source_decisions.jsonl").write_bytes(b"")
    else:
        path = majority / "decisions/context_assignments.jsonl"
        with path.open() as stream:
            rows = [json.loads(line) for line in stream]
        rows[0]["topic" if defect == "changed-topic" else "analytical_admission"] = (
            2 if defect == "changed-topic" else True
        )
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest["artifacts"] = {
        name: MODULE["binding"](majority / name) for name in manifest["artifacts"]
    }
    write(majority / "manifest.json", manifest)
    with pytest.raises(ValueError):
        build_fixture(inspector_sources)


def test_query_download_preserves_full_records_large_integers_and_errors():
    script = r"""
const assert = require("node:assert/strict");
const {completeQueryBlob, inspectorMatches, utf16Position, policyText} = require(process.argv[1]);
(async () => {
  const unicode = String.fromCodePoint(0x1f600, 0x2028, 0x2029);
  const records = {
    context: '{"bill_id":"b","topic":null,"original_unknown":null}',
    input: '{"bill_id":"b","input_id":"i","input_sha256":"sha",'
      + '"large":9007199254740999,"text":"' + unicode + ' complete ending"}',
    prediction: '{"bill_id":"b","input_id":"i","input_sha256":"sha","logits":[[1,2]]}',
  };
  const row = {bill_id:"b",context:"context",sources:[{
    input_id:"i",input_sha256:"sha",input:"input",prediction:"prediction"}]};
  const get = async key => ({raw:records[key], value:JSON.parse(records[key])});
  const blob = await completeQueryBlob([row], get), text = await blob.text();
  assert.ok(text.includes("9007199254740999"));
  assert.ok(text.includes(unicode + " complete ending"));
  assert.equal(text.split("\n").length, 2);
  const query = JSON.parse(text);
  assert.equal(query.context.original_unknown, null);
  assert.equal(query.inputs[0].text, unicode + " complete ending");
  assert.deepEqual(query.predictions[0].logits, [[1,2]]);
  assert.equal((await completeQueryBlob([], get)).size, 0);
  await assert.rejects(completeQueryBlob([row], async key => {
    if(key === "prediction") throw new Error("last complete record unavailable");
    return get(key);
  }), /last complete record/);
  assert.equal(utf16Position(3,[1]),4);
  assert.equal(policyText({original_source_view:{source_type:"snapshot_text",
    source_record:{raw_text:"a😀b"}}},{utf16_span:[1,4]}),"😀b");
  assert.ok(inspectorMatches({identifier:"HB 1",title:"Exact title",bill_id:"b",
    baseline_topic:null,candidate_topic:3,candidate_status:"classified"},"title","new","3"));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    subprocess.run(
        ["node", "-e", script, str(ROOT / "web/classification-inspector.js")],
        check=True,
        capture_output=True,
        text=True,
    )


def test_query_file_stream_matches_complete_download_and_obeys_backpressure():
    script = r"""
const assert = require("node:assert/strict");
const {completeQueryBlob, completeQueryToWritable} = require(process.argv[1]);
(async () => {
  const records = {
    context: '{"bill_id":"b","topic":null,"unknown":null}',
    missing: '{"bill_id":"missing","status":"unavailable","topic":null}',
    input: '{"bill_id":"b","input_id":"i","input_sha256":"sha",'
      + '"large":9007199254740999,"text":"😀\u2028complete\u2029ending"}',
    prediction: '{"bill_id":"b","input_id":"i","input_sha256":"sha","scores":[1,2]}',
  };
  const rows = [
    {bill_id:"b",context:"context",sources:[{
      input_id:"i",input_sha256:"sha",input:"input",prediction:"prediction"}]},
    {bill_id:"missing",context:"missing",sources:[]},
  ];
  let writing = false, closed = 0, aborted = 0;
  const chunks = [];
  const get = async key => {
    assert.equal(writing, false, "reading ahead while a disk write is pending");
    return {raw:records[key], value:JSON.parse(records[key])};
  };
  await completeQueryToWritable(rows, {
    async write(chunk) {
      assert.equal(writing, false);
      writing = true;
      await new Promise(resolve => setImmediate(resolve));
      chunks.push(Buffer.from(chunk));
      writing = false;
    },
    async close() { closed++; },
    async abort() { aborted++; },
  }, get);
  const expected = Buffer.from(await (await completeQueryBlob(rows, get)).arrayBuffer());
  assert.deepEqual(Buffer.concat(chunks), expected);
  assert.ok(expected.toString().includes("9007199254740999"));
  assert.ok(expected.toString().includes("😀\u2028complete\u2029ending"));
  assert.equal(closed, 1); assert.equal(aborted, 0);
  let emptyClosed = false;
  await completeQueryToWritable([], {
    async write() { assert.fail("empty query must not invent records"); },
    async close() { emptyClosed = true; },
    async abort() { assert.fail("empty complete query is not an error"); },
  }, () => assert.fail("empty query must not read sources"));
  assert.equal(emptyClosed, true);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(
        ["node", "-e", script, str(ROOT / "web/classification-inspector.js")],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("failure", ["read", "write", "close", "abort"])
def test_query_file_stream_aborts_without_committing_partial_or_masking_errors(failure):
    script = r"""
const assert = require("node:assert/strict");
const {completeQueryToWritable} = require(process.argv[1]);
(async () => {
  const failure = process.argv[2], primary = new Error("original export failure");
  const row = {bill_id:"b",context:"context",sources:[{
    input_id:"i",input_sha256:"sha",input:"input",prediction:"prediction"}]};
  let written = 0, aborted = 0, closed = 0, committed = "existing complete file";
  const get = async key => {
    if (key === "prediction" && ["read", "abort"].includes(failure)) throw primary;
    const value = {bill_id:"b",input_id:"i",input_sha256:"sha",text:"complete text"};
    return {raw:JSON.stringify(value),value};
  };
  await assert.rejects(completeQueryToWritable([row], {
    async write() {
      written++;
      if (failure === "write" && written === 3) throw primary;
    },
    async close() {
      closed++;
      if (failure === "close") throw primary;
      committed = "new complete file";
    },
    async abort() {
      aborted++;
      if (failure === "abort") throw new Error("abort itself failed");
    },
  }, get), error => error === primary);
  assert.ok(written > 0, "exercise a failure after output has started");
  assert.equal(aborted, 1);
  assert.equal(closed, failure === "close" ? 1 : 0);
  assert.equal(committed, "existing complete file");
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(
        ["node", "-e", script, str(ROOT / "web/classification-inspector.js"), failure],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_large_query_file_stream_does_not_buffer_a_query_sized_blob():
    script = r"""
const assert = require("node:assert/strict");
const v8 = require("node:v8");
const {completeQueryToWritable} = require(process.argv[1]);
(async () => {
  globalThis.Blob = globalThis.Response = class {
    constructor() { assert.fail("direct file export must not buffer a query-sized Blob"); }
  };
  const payload = "x".repeat(48 * 1024), count = 10000;
  function* rows() {
    for (let i = 0; i < count; i++) {
      const bill_id = `b-${i}`;
      yield {bill_id,context:{bill_id,kind:"context"},sources:[{
        input_id:"i",input_sha256:"sha",
        input:{bill_id,kind:"input"},prediction:{bill_id,kind:"prediction"}}]};
    }
  }
  let bytes = 0, endings = 0, maximumChunk = 0, closed = false;
  const get = async reference => {
    const value = {bill_id:reference.bill_id,input_id:"i",input_sha256:"sha",
      text:reference.kind === "input" ? payload : "complete record"};
    return {raw:JSON.stringify(value),value};
  };
  await completeQueryToWritable(rows(), {
    async write(chunk) {
      bytes += chunk.length; maximumChunk = Math.max(maximumChunk, chunk.length);
      if (chunk.length === 2 && chunk[0] === 125 && chunk[1] === 10) endings++;
      assert.ok(chunk.length < 65536, "only one complete saved record per write");
    },
    async close() { closed = true; },
    async abort() { assert.fail("complete generated query must not abort"); },
  }, get);
  const heapLimit = v8.getHeapStatistics().heap_size_limit;
  assert.ok(closed); assert.equal(endings, count);
  assert.ok(bytes >= payload.length * count && bytes > heapLimit);
  console.log(JSON.stringify({contexts:count,logical_bytes:bytes,
    maximum_chunk_bytes:maximumChunk,JS_heap_limit_bytes:heapLimit,
    old_space_limit_MiB:32,closed,query_sized_Blob:false}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [
            "node",
            "--max-old-space-size=32",
            "-e",
            script,
            str(ROOT / "web/classification-inspector.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(result.stdout.strip())

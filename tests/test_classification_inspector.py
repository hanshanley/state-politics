import hashlib
import json
import runpy
import subprocess
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

import importlib.metadata
import json
import runpy
import sqlite3
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_cycle_topics import job  # noqa: F401

from state_politics.analysis import cycle_topics as cycle
from state_politics.analysis.modernbert import policy_tokens

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit_cycle_topics.py"


@pytest.fixture
def snapshot(job, monkeypatch):  # noqa: F811
    original, model, text, _ = job
    first = cycle.read(original / "inference_plan.json")
    checkpoint = Path(first["checkpoint"])
    training = cycle.read(checkpoint / "training_manifest.json")
    training["output_codes"] = model.output_codes
    cycle.write_json(checkpoint / "training_manifest.json", training)
    model.run_id = model.base_model_run = cycle.sha256_file(checkpoint / "training_manifest.json")
    directory = original.with_name("audited-job")
    cycle.freeze(Path(first["preview"]), checkpoint, directory, tiers=("retained_text",))
    cycle.run(directory, tier="retained_text", allow_provisional=True)
    summary = cycle.summarize(directory, "retained_text")
    gallery = original.with_name("gallery")
    (gallery / "research-data").mkdir(parents=True)
    names = {
        "inference_plan.json",
        "contexts.jsonl",
        "progress-retained_text.json",
        "summary-retained_text.json",
        "bill_assignments-retained_text.parquet",
        "producer/cycle_topics.py",
        "producer/modernbert.py",
        "producer/topics.yml",
    } | {
        f"{kind}/retained_text-{state}.jsonl"
        for state in cycle.read(directory / "progress-retained_text.json")["states"]
        for kind in ("inputs", "predictions")
    }
    zip_name = "research-data/complete_inference_inputs_and_predictions.zip"
    with ZipFile(gallery / zip_name, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(names):
            archive.write(directory / name, name)
    cycle.write_json(
        gallery / "manifest.json",
        {
            "status": "complete_provisional_topic_graphs_not_scientific_validation",
            "tiers": ["retained_text"],
            "model_promotion": False,
            "publication": False,
            "candidate_contexts": 1,
            "model_run": model.run_id,
            "assignment_counts_by_tier": {
                "retained_text": {"candidate_contexts": 1, **summary["assignment_counts"]},
            },
            "artifacts": {zip_name: cycle.binding(gallery / zip_name)},
            "inference_inputs": {name: cycle.binding(directory / name) for name in sorted(names)},
            **cycle.FLAGS,
        },
    )
    module = runpy.run_path(str(SCRIPT))
    monkeypatch.setattr(module["AutoTokenizer"], "from_pretrained", lambda *a, **k: model.tokenizer)
    return module["audit"], directory, gallery, original.with_name("report.json"), model, text


def rewrite_prediction(directory, update):
    path = directory / "predictions/retained_text-NJ.jsonl"
    rows = [row for _, row in cycle.records(path)]
    update(rows[0])
    with path.open("w") as stream:
        for row in rows:
            cycle.write_row(stream, row)
    progress = cycle.read(directory / "progress-retained_text.json")
    progress["states"]["NJ"]["artifact"] = cycle.binding(path)
    cycle.write_json(directory / "progress-retained_text.json", progress)


def test_offline_replay_preserves_complete_unicode_sources_unknowns_and_snapshot(snapshot):
    audit, directory, gallery, output, model, text = snapshot
    before = {
        path: cycle.binding(path)
        for root in (directory, gallery)
        for path in root.rglob("*")
        if path.is_file()
    }
    calls = model.model.calls
    report = audit(directory, gallery, output)
    assert report["completed_states_replayed"] == 50
    assert report["source_views"] == report["candidate_contexts"] == 1
    assert report["complete_research_zip"]["members"] == 108
    assert report["new_independent_tokenizations"] == 1
    assert report["independent_encoder_passes"] == 0 and model.model.calls == calls
    assert report["independent_human_validation"] is report["publication"] is False
    assert "\u2028" in text and report["logical_source_view_tokens"] == len(text)
    assert all(cycle.binding(path) == binding for path, binding in before.items())
    with pytest.raises(ValueError, match="fresh report"):
        audit(directory, gallery, output)


def test_rebound_saved_decision_must_still_match_the_actual_logits(snapshot):
    audit, directory, gallery, output, _, _ = snapshot
    rewrite_prediction(directory, lambda row: row.update(topic=2 if row["topic"] != 2 else 1))
    with pytest.raises(ValueError, match="saved decision differs"):
        audit(directory, gallery, output)
    assert not output.exists()


def test_rebound_saved_windows_cannot_drop_the_end_of_the_source(snapshot):
    audit, directory, gallery, output, _, _ = snapshot

    def truncate(row):
        spans = json.loads(row["chunk_spans"])
        spans[-1][1] -= 1
        row["chunk_spans"] = json.dumps(spans)

    rewrite_prediction(directory, truncate)
    with pytest.raises(ValueError, match="saved token coverage"):
        audit(directory, gallery, output)


def test_original_unknown_party_cannot_be_replaced_by_an_assignment(snapshot):
    audit, directory, gallery, output, _, _ = snapshot
    path = directory / "bill_assignments-retained_text.parquet"
    rows = pq.read_table(path).to_pylist()
    rows[0]["unknown_party"] = "D"
    pq.write_table(pa.Table.from_pylist(rows), path)
    summary = cycle.read(directory / "summary-retained_text.json")
    summary["assignments"] = cycle.binding(path)
    cycle.write_json(directory / "summary-retained_text.json", summary)
    with pytest.raises(ValueError, match="original fields, unknowns or consensus changed"):
        audit(directory, gallery, output)


def test_rebound_manifest_and_zip_cannot_omit_required_whole_inputs(snapshot):
    audit, directory, gallery, output, _, _ = snapshot
    manifest = cycle.read(gallery / "manifest.json")
    zip_name = "research-data/complete_inference_inputs_and_predictions.zip"
    del manifest["inference_inputs"]["inputs/retained_text-NJ.jsonl"]
    with ZipFile(gallery / zip_name, "w", compression=ZIP_DEFLATED) as archive:
        for name in manifest["inference_inputs"]:
            archive.write(directory / name, name)
    manifest["artifacts"][zip_name] = cycle.binding(gallery / zip_name)
    cycle.write_json(gallery / "manifest.json", manifest)
    with pytest.raises(ValueError, match="omits required frozen inputs"):
        audit(directory, gallery, output)


def verified_cache(directory, model):
    plan = cycle.read(directory / "inference_plan.json")
    prefix, _ = policy_tokens(model.tokenizer, "", "bill")
    identity = json.dumps(
        {
            "training_manifest": plan["training_manifest"],
            "input_config": model.manifest["input"],
            "prefix": prefix,
            "runtime": plan["frozen_inference_runtime"],
            "transformers": importlib.metadata.version("transformers"),
            "tokenizers": importlib.metadata.version("tokenizers"),
        },
        sort_keys=True,
    )
    original = next(cycle.records(directory / "inputs/retained_text-NJ.jsonl"))[1]
    prediction = next(cycle.records(directory / "predictions/retained_text-NJ.jsonl"))[1]
    path = directory.with_name("verified-tokens.sqlite")
    with sqlite3.connect(path) as cache:
        cache.execute("CREATE TABLE identity (value TEXT NOT NULL)")
        cache.execute("INSERT INTO identity VALUES (?)", (identity,))
        cache.execute(
            "CREATE TABLE tokens (sha TEXT PRIMARY KEY,n_chars INTEGER,n_tokens INTEGER,spans TEXT)"
        )
        cache.execute(
            "INSERT INTO tokens VALUES (?,?,?,?)",
            (
                prediction["input_sha256"],
                len(cycle.input_text(original)),
                prediction["n_input_tokens"],
                prediction["chunk_spans"],
            ),
        )
    return path


def test_pinned_verified_cache_is_reused_without_writes_or_retokenization(snapshot, monkeypatch):
    audit, directory, gallery, output, model, _ = snapshot
    cache = verified_cache(directory, model)
    before = cycle.binding(cache)

    def forbidden_tokenization(*args, **kwargs):
        raise AssertionError("A previously independently verified source was retokenized")

    monkeypatch.setattr(type(model.tokenizer), "__call__", forbidden_tokenization)
    report = audit(
        directory,
        gallery,
        output,
        token_cache=cache,
        token_cache_sha256=before["sha256"],
    )
    assert report["new_independent_tokenizations"] == 0
    assert report["reused_independently_verified_tokenizations"] == 1
    assert report["verified_token_cache"]["read_only"] is True
    assert cycle.binding(cache) == before


def test_missing_verified_row_fails_instead_of_writing_or_falling_back(snapshot):
    audit, directory, gallery, output, model, _ = snapshot
    cache = verified_cache(directory, model)
    with sqlite3.connect(cache) as connection:
        connection.execute("DELETE FROM tokens")
    before = cycle.binding(cache)
    with pytest.raises(ValueError, match="input absent from verified token cache"):
        audit(directory, gallery, output, token_cache=cache, token_cache_sha256=before["sha256"])
    assert cycle.binding(cache) == before and not output.exists()

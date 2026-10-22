"""Complete-source population inference, batching and alternative-view accounting."""

import json
import runpy
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import torch

from state_politics.analysis import cycle_topics as cycle
from state_politics.analysis.modernbert import ModernBertClassifier
from state_politics.analysis.taxonomy import DEFAULT_TOPICS_PATH


class Batch(dict):
    def to(self, device):
        return Batch({key: value.to(device) for key, value in self.items()})


class Tokenizer:
    cls_token_id = 101
    sep_token_id = 102

    def encode(self, text, add_special_tokens=False):
        values = [ord(character) % 11 + 10 for character in text]
        return [101, *values, 102] if add_special_tokens else values

    def __call__(self, text, **options):
        assert options["truncation"] is False
        return {
            "input_ids": self.encode(text),
            "offset_mapping": [(index, index + 1) for index in range(len(text))],
        }

    def num_special_tokens_to_add(self):
        return 2

    def pad(self, rows, **options):
        width = max(len(row["input_ids"]) for row in rows)
        return Batch(
            {
                "input_ids": torch.tensor(
                    [row["input_ids"] + [0] * (width - len(row["input_ids"])) for row in rows]
                ),
                "attention_mask": torch.tensor(
                    [
                        [1] * len(row["input_ids"]) + [0] * (width - len(row["input_ids"]))
                        for row in rows
                    ]
                ),
            }
        )


class Model:
    def __init__(self):
        self.calls = 0
        self.extra = False

    def __call__(self, input_ids, attention_mask):
        self.calls += 1
        score = (input_ids * attention_mask).sum(dim=1).float() / 100
        logits = torch.stack([score, -score, torch.zeros_like(score)], dim=1)
        return SimpleNamespace(logits=torch.cat([logits, logits[:1]]) if self.extra else logits)


def classifier():
    return SimpleNamespace(
        tokenizer=Tokenizer(),
        model=Model(),
        device="cpu",
        output_codes=[1, 2, None],
        manifest={
            "input": {"max_tokens": 32, "overlap": 3},
            "decision": {"temperature": 1.0, "min_confidence": 0.6, "min_margin": 0.2},
            "status": "provisional",
            "decision_status": "uncalibrated_research_defaults",
            "taxonomy_sha256": cycle.sha256_file(DEFAULT_TOPICS_PATH),
        },
        run_id="frozen-model",
        base_model_run="frozen-model",
        calibration_sha256=None,
    )


def test_cross_document_window_batching_matches_frozen_decisions_and_covers_every_character():
    model = classifier()
    texts = ["", "Short", ("Complete\u2028original\u2029source\n\n" * 7) + "final ending"]
    expected = ModernBertClassifier.predict_records(model, texts, domain="bill", batch_size=2)
    actual = cycle.pooled_predictions(model, texts, batch_size=4, padded_token_budget=128)
    assert actual == expected
    assert actual[2]["n_chunks"] > 1 and actual[2]["n_discarded_tokens"] == 0
    spans = json.loads(actual[2]["chunk_spans"])
    assert set().union(*(set(range(start, end)) for start, end in spans)) == set(
        range(len(texts[2]))
    )
    model.model.extra = True
    with pytest.raises(ValueError, match="one logit row"):
        cycle.pooled_predictions(model, ["complete source"])


@pytest.mark.parametrize("topics", [[1, 1], [1, 2], [1, None], [None, None]])
def test_bill_alternatives_count_once_and_disagreements_abstain_without_losing_unknowns(topics):
    contexts = [
        {"bill_id": "one", "state": "NJ", "unknown_party": None},
        {"bill_id": "missing", "state": "HI", "unknown_party": None},
    ]
    rows = [
        {
            "bill_id": "one",
            "input_id": str(index),
            "topic": topic,
            "abstention_reason": None if topic else "low_confidence",
            "model_run": "fixed",
        }
        for index, topic in enumerate(topics)
    ]
    result = cycle.collapse_bill_views(contexts, rows)
    assert len(result) == 2 and result[0]["n_source_views"] == 2
    assert result[0]["topic"] == (1 if topics == [1, 1] else None)
    assert result[0]["inference_status"] == ("classified" if topics == [1, 1] else "abstained")
    assert result[1]["inference_status"] == "unavailable" and result[1]["unknown_party"] is None
    assert all(result[0][flag] is False for flag in cycle.FLAGS)
    with pytest.raises(ValueError, match="duplicate predicted"):
        cycle.collapse_bill_views(contexts, rows + [rows[0]])


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(cycle, "ROOT", tmp_path)
    preview = tmp_path / "data/preview"
    (preview / "evidence").mkdir(parents=True)
    (preview / "downloads").mkdir()
    checkpoint = tmp_path / "data/checkpoint"
    checkpoint.mkdir()
    model = classifier()
    training = {**model.manifest}
    cycle.write_json(checkpoint / "training_manifest.json", training)
    context = {
        "bill_id": "one",
        "state": "NJ",
        "identifier": "A 17",
        "session_identifier": "221",
        "title": "Canonical",
        "unknown_party": None,
    }
    text = "Complete \u2028source <literal> & final ending."
    metadata = [
        {
            **context,
            **cycle.FLAGS,
            "source_type": "bill_metadata",
            "view_id": f"metadata:{i}",
            "bill_context": context,
            "text": text,
            "abstract": "Full abstract",
            "source_original_null": None,
        }
        for i in range(2)
    ]
    prologue = "Title: machine title\nSection 1:\n"
    archived = {
        **context,
        **cycle.FLAGS,
        "source_type": "archive_text",
        "view_id": "archive:one",
        "text": prologue + text,
        "archive_generated_prologue_preserved": True,
        "source_identity": {"policy_section_start": len(prologue)},
    }
    outputs = {}
    for state in sorted(s.upper() for s in cycle.STATE_CODES):
        for prefix in ("bills", "native", "snapshot", "corpus", "archive"):
            path = preview / f"evidence/{prefix}-{state}.jsonl"
            values = (
                metadata
                if state == "NJ" and prefix == "bills"
                else ([archived] if state == "NJ" and prefix == "archive" else [])
            )
            with path.open("w") as handle:
                for row in values:
                    cycle.write_row(handle, row)
            outputs[path.relative_to(preview).as_posix()] = cycle.binding(path)
    cycle.write_json(
        preview / "downloads/build_manifest.json",
        {
            "publication_status": "local_only_unpublished",
            "model_input_approved": False,
            "study_start": "2023-01-01",
            "study_end": "2024-12-31",
            "outputs": outputs,
            "counts": {"n_cycle_contexts": 1},
        },
    )
    directory = tmp_path / "data/job"
    cycle.freeze(preview, checkpoint, directory, tiers=("metadata", "retained_text"))
    model.run_id = model.base_model_run = cycle.sha256_file(checkpoint / "training_manifest.json")
    monkeypatch.setattr(cycle, "ModernBertClassifier", lambda *args, **kwargs: model)
    return directory, model, text, prologue


def test_frozen_full_sources_exclude_only_declared_machine_prologue_and_reject_changed_text(job):
    directory, _, text, prologue = job
    rows = [row for _, row in cycle.records(directory / "inputs/retained_text-NJ.jsonl")]
    assert len(rows) == 1 and cycle.input_text(rows[0]) == text
    assert rows[0]["original_source_view"]["text"] == prologue + text
    assert rows[0]["archive_machine_prologue_excluded_from_inference"] is True
    rows[0]["original_source_view"]["text"] += " silently changed"
    with pytest.raises(ValueError, match="source text changed"):
        changed = rows[0]
        changed["source_text_span"][1] += len(" silently changed")
        cycle.input_text(changed)


def test_population_cache_resume_and_changed_output_refusal(job):
    directory, model, _, _ = job
    with pytest.raises(ValueError, match="allow-provisional"):
        cycle.run(directory, tier="metadata")
    result = cycle.run(directory, tier="metadata", allow_provisional=True, batch_size=4)
    assert len(result["states"]) == 50 and result["states"]["NJ"]["views"] == 2
    assert model.model.calls == 1
    with sqlite3.connect(directory / "prediction_cache.sqlite") as cache:
        assert cache.execute("SELECT count(*) FROM predictions").fetchone()[0] == 1
    cycle.run(directory, tier="metadata", allow_provisional=True, batch_size=4)
    assert model.model.calls == 1
    summary = cycle.summarize(directory, "metadata")
    assert summary["contexts"] == 1 and summary["source_views"] == 2
    assert sum(summary["assignment_counts"].values()) == 1
    target = directory / "predictions/metadata-NJ.jsonl"
    target.write_text("altered completed output\n")
    with pytest.raises(ValueError, match="file binding mismatch"):
        cycle.run(directory, tier="metadata", allow_provisional=True, batch_size=4)


def test_poisoned_cache_cannot_silently_change_the_saved_single_topic_decision(job):
    directory, model, _, _ = job
    rows = [r for _, r in cycle.records(directory / "inputs/metadata-NJ.jsonl")]
    with sqlite3.connect(":memory:") as cache:
        cache.execute("CREATE TABLE predictions (input_sha256 TEXT PRIMARY KEY,result TEXT)")
        cycle.predict_input_block(model, rows, cache, 4)
        key, value = cache.execute("SELECT * FROM predictions").fetchone()
        changed = json.loads(value)
        changed["topic"] = 2 if changed["topic"] != 2 else 1
        cache.execute(
            "UPDATE predictions SET result=? WHERE input_sha256=?", (json.dumps(changed), key)
        )
        with pytest.raises(ValueError, match="cached decision"):
            cycle.predict_input_block(model, rows, cache, 4)


def test_complete_reviewed_withdrawal_cover_abstains_without_title_fallback():
    text = (
        "SECOND REGULAR SESSION [WITHDRAWN] SENATE BILL NO. 961 "
        "102ND GENERAL ASSEMBLY INTRODUCED BY SENATOR TEST. "
        "3811S.01W KRISTINA MARTIN, Secretary WITHDRAWN"
    )
    source = {
        "source_type": "native_text",
        "view_id": "withdrawal",
        "bill_id": "mo961",
        "state": "MO",
        "identifier": "SB 961",
        "session_identifier": "2024",
        "title": "This metadata title does not replace the withdrawn source",
        "text": text,
        **cycle.FLAGS,
    }
    unit = cycle.make_input(source, "retained_text", "source.jsonl", 1)
    assert unit["pre_inference_exclusion"] == "withdrawal_notice_no_policy_text"
    assert cycle.input_text(unit) == text


def test_topic_graph_denominators_keep_abstentions_and_unknown_text_distinct():
    graph = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/recreate_topic_graphs.py")
    )
    topics = [SimpleNamespace(code=1, name="One"), SimpleNamespace(code=2, name="Two")]
    frame = pd.DataFrame(
        [
            {
                "bill_id": "a",
                "state": "CA",
                "topic": 1,
                "inference_status": "classified",
                **cycle.FLAGS,
            },
            {
                "bill_id": "b",
                "state": "CA",
                "topic": None,
                "inference_status": "abstained",
                **cycle.FLAGS,
            },
            {
                "bill_id": "c",
                "state": "NJ",
                "topic": None,
                "inference_status": "unavailable",
                **cycle.FLAGS,
            },
            {
                "bill_id": "d",
                "state": "NE",
                "topic": 2,
                "inference_status": "classified",
                **cycle.FLAGS,
            },
        ]
    )
    national, states, shares = graph["topic_tables"](frame, topics)
    assert national["candidate_contexts"].tolist() == [4, 4]
    assert national["model_assigned_contexts"].tolist() == [1, 1]
    assert len(states) == 50 and states["candidate_contexts"].sum() == 4
    ca = shares[(shares["state"] == "CA") & (shares["topic"] == 1)].iloc[0]
    assert ca["share_of_all_candidates"] == 0.5
    assert shares[shares["state"].isin(["ME", "NJ"])]["share_of_all_candidates"].isna().all()
    frame.loc[0, "state"] = "XX"
    with pytest.raises(ValueError, match="unexpected state"):
        graph["topic_tables"](frame, topics)


def test_completed_topic_gallery_includes_full_inputs_and_never_just_chart_metadata(
    job, monkeypatch
):
    import zipfile

    directory, _, text, _ = job
    cycle.run(directory, tier="metadata", allow_provisional=True)
    cycle.summarize(directory, "metadata")
    graph = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/recreate_topic_graphs.py")
    )
    monkeypatch.setitem(graph["recreate"].__globals__, "ROOT", directory.parent.parent)
    output = directory.parent.parent / "outputs/topic-graphs"
    result = graph["recreate"](directory, output, tiers=("metadata",))
    assert result["candidate_contexts"] == 1 and len(result["graphs"]) == 3
    assert all(result[key] is False for key in cycle.FLAGS)
    with zipfile.ZipFile(
        output / "research-data/complete_inference_inputs_and_predictions.zip"
    ) as z:
        rows = [
            json.loads(line)
            for line in z.read("inputs/metadata-NJ.jsonl").decode().split("\n")
            if line
        ]
        assert len(rows) == 2
        assert [cycle.input_text(row) for row in rows] == [text, text]
        assert "predictions/metadata-NJ.jsonl" in z.namelist()
        assert "bill_assignments-metadata.parquet" in z.namelist()
    with pytest.raises(ValueError, match="new project output"):
        graph["recreate"](directory, output, tiers=("metadata",))

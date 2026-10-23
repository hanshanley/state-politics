"""Matched-input denominators and fail-closed, self-contained research downloads."""

import hashlib
import importlib.util
import io
import json
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "compare_cycle_topic_inputs", ROOT / "scripts/compare_cycle_topic_inputs.py"
)
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)
TOPICS_BYTES = (ROOT / "conf/topics.yml").read_bytes()
TOPICS = [
    SimpleNamespace(code=row["code"], name=row["name"])
    for row in yaml.safe_load(TOPICS_BYTES)["topics"]
]
MODEL = "a" * 64


def encoded(value):
    return (json.dumps(value, allow_nan=False) + "\n").encode()


def bound(value):
    return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}


def assignment(bill_id, topic, status=None, state="CA"):
    status = status or ("classified" if topic else "abstained")
    return {
        "bill_id": bill_id,
        "state": state,
        "identifier": f"AB {bill_id}",
        "session_identifier": "2023-2024",
        "topic": topic,
        "inference_status": status,
        "abstention_reason": None
        if topic
        else (
            "no_supplied_retained_text" if status == "unavailable" else "all_source_views_abstained"
        ),
        "n_source_views": 0 if status == "unavailable" else 1,
        "view_abstention_reasons": "{}"
        if topic or status == "unavailable"
        else ('{"low_confidence": 1}'),
        "model_run": None if status == "unavailable" else MODEL,
        **comparison.FLAGS,
    }


def frames():
    metadata = pd.DataFrame(
        [
            assignment("same", 1),
            assignment("different", 1),
            assignment("both", None),
            assignment("one", None),
            assignment("missing", 1, state="NJ"),
        ]
    )
    retained = pd.DataFrame(
        [
            assignment("same", 1),
            assignment("different", 2),
            assignment("both", None),
            assignment("one", 2),
            assignment("missing", None, "unavailable", "NJ"),
        ]
    )
    return metadata, retained


def gallery(directory, tier, frame):
    """A miniature producer-contract bundle without any original jobs, models or network."""
    directory.mkdir(parents=True)
    context_rows = [
        {key: row[key] for key in comparison.IDENTITY} for row in frame.to_dict("records")
    ]
    members = {
        "contexts.jsonl": b"".join(encoded(row) for row in context_rows),
        "producer/cycle_topics.py": b"frozen source producer; never executed\n",
        "producer/modernbert.py": b"frozen input policy; never executed\n",
        "producer/topics.yml": TOPICS_BYTES,
    }
    plan_inputs, progress_states = {}, {}
    for state in comparison.STATES:
        available = (
            frame[frame["state"].eq(state) & frame["inference_status"].ne("unavailable")]
            .astype(object)
            .where(lambda values: values.notna(), None)
            .to_dict("records")
        )
        inputs = [
            {
                **{key: row[key] for key in comparison.IDENTITY},
                "input_id": f"{tier}:{row['bill_id']}",
                "tier": tier,
                "input_sha256": bound(f"original {tier} {row['bill_id']}".encode())["sha256"],
                "original_source_view": {
                    "text": f"FULL ORIGINAL {tier} body <literal> & ending {row['bill_id']}",
                    "retained_source_record": {"never_lost": [None, "full source record"]},
                    **comparison.FLAGS,
                },
                **comparison.FLAGS,
            }
            for row in available
        ]
        predictions = [
            {
                **row,
                "input_id": f"{tier}:{row['bill_id']}",
                "tier": tier,
                "input_sha256": bound(f"original {tier} {row['bill_id']}".encode())["sha256"],
                "taxonomy_sha256": bound(TOPICS_BYTES)["sha256"],
            }
            for row in available
        ]
        name, predicted = f"inputs/{tier}-{state}.jsonl", f"predictions/{tier}-{state}.jsonl"
        members[name] = b"".join(encoded(row) for row in inputs)
        members[predicted] = b"".join(encoded(row) for row in predictions)
        plan_inputs[name] = {
            **bound(members[name]),
            "views": len(inputs),
            "state": state,
            "tier": tier,
        }
        progress_states[state] = {"views": len(inputs), "artifact": bound(members[predicted])}
    plan = {
        "schema": comparison.SCHEMA,
        "status": "frozen_before_provisional_population_inference",
        "preview": "/missing/preview",
        "preview_manifest": bound(b"preview"),
        "checkpoint": "/missing/model",
        "training_manifest": {"sha256": MODEL, "bytes": 123},
        "topics_path": "/missing/topics.yml",
        "model_run": MODEL,
        "model_status": "provisional",
        "decision": {"temperature": 1.0, "min_confidence": 0.8, "min_margin": 0.2},
        "taxonomy_sha256": bound(TOPICS_BYTES)["sha256"],
        "source_files": {f"evidence/{tier}-CA.jsonl": bound(b"full original source binding")},
        "inputs": plan_inputs,
        "tiers": [tier],
        "contexts": bound(members["contexts.jsonl"]),
        "n_contexts": len(frame),
        "n_views_by_tier": {tier: int(frame["n_source_views"].sum())},
        "producer": bound(members["producer/cycle_topics.py"]),
        "frozen_inference_runtime": bound(members["producer/modernbert.py"]),
        "inference_engine": "cross_document_padded_windows_frozen_decision_v1",
        "record_block_size": 128,
        "padded_window_token_budget": 8192,
        "human_review_packet_modified_or_scored": False,
        **comparison.POLICY,
        **comparison.FLAGS,
    }
    members["inference_plan.json"] = encoded(plan)
    members[f"progress-{tier}.json"] = encoded(
        {
            "status": "complete_provisional_inference_not_scientific_validation",
            "tier": tier,
            "model_run": MODEL,
            "inference_plan_sha256": bound(members["inference_plan.json"])["sha256"],
            "states": progress_states,
            **comparison.FLAGS,
        }
    )
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    members[f"bill_assignments-{tier}.parquet"] = buffer.getvalue()
    counts = {
        status: int(frame["inference_status"].eq(status).sum())
        for status in comparison.DISPOSITIONS
    }
    members[f"summary-{tier}.json"] = encoded(
        {
            "tier": tier,
            "contexts": len(frame),
            "source_views": plan["n_views_by_tier"][tier],
            "assignments": bound(members[f"bill_assignments-{tier}.parquet"]),
            "assignment_counts": {key: n for key, n in counts.items() if n},
            "topic_counts": {
                str(topic.code): int(frame["topic"].eq(topic.code).sum())
                for topic in TOPICS
                if frame["topic"].eq(topic.code).any()
            },
            **comparison.FLAGS,
        }
    )
    archive_path = directory / comparison.ARCHIVE
    archive_path.parent.mkdir()
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    graphs = [
        f"{tier}_{name}" for name in ("topic_counts", "classification_coverage", "state_topics")
    ]
    files = {
        "index.html": b"<html>complete synthetic source gallery</html>",
        "producers/recreate_topic_graphs.py": b"original graph producer; never executed",
        **{
            f"graphs/{name}.{suffix}": b"synthetic chart"
            for name in graphs
            for suffix in ("png", "svg")
        },
        **{
            f"chart-data/{name}.csv": b"complete,synthetic,chart,data\n"
            for name in [*graphs, f"{tier}_bill_assignments"]
        },
    }
    for name, value in files.items():
        path = directory / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(value)
    manifest = {
        "status": comparison.STATUS,
        "tiers": [tier],
        "model_run": MODEL,
        "candidate_contexts": len(frame),
        "assignment_counts_by_tier": {tier: {"candidate_contexts": len(frame), **counts}},
        "scientific_certification": "not_performed",
        "model_promotion": False,
        "publication": False,
        "inference_was_executed": True,
        "model_execution_during_graph_build": False,
        "inference_inputs": {name: bound(value) for name, value in members.items()},
        "graphs": graphs,
        "artifacts": {
            **{name: bound(value) for name, value in files.items()},
            comparison.ARCHIVE: comparison.binding(archive_path),
        },
        **comparison.FLAGS,
    }
    (directory / "manifest.json").write_bytes(encoded(manifest))
    return directory


@pytest.fixture
def completed(tmp_path, monkeypatch):
    monkeypatch.setattr(comparison, "ROOT", tmp_path)
    metadata, retained = frames()
    return (
        gallery(tmp_path / "metadata", "metadata", metadata),
        gallery(tmp_path / "retained", "retained_text", retained),
        tmp_path / "outputs/comparison",
    )


def rewrite_member(directory, name, transform):
    """Rebind all producer layers so semantic validation, not a stale outer hash, is tested."""
    archive_path = directory / comparison.ARCHIVE
    manifest = json.loads((directory / "manifest.json").read_bytes())
    with zipfile.ZipFile(archive_path) as archive:
        members = {item: archive.read(item) for item in archive.namelist()}
    members[name] = transform(members[name])
    if name == "inference_plan.json":
        for tier in manifest["tiers"]:
            progress_name = f"progress-{tier}.json"
            progress = json.loads(members[progress_name])
            progress["inference_plan_sha256"] = bound(members[name])["sha256"]
            members[progress_name] = encoded(progress)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, value in members.items():
            archive.writestr(member, value)
    manifest["inference_inputs"] = {member: bound(value) for member, value in members.items()}
    manifest["artifacts"][comparison.ARCHIVE] = comparison.binding(archive_path)
    (directory / "manifest.json").write_bytes(encoded(manifest))


def test_paired_denominator_includes_abstentions_and_excludes_absent_body():
    metadata, retained = frames()
    tables = comparison.comparison_tables(metadata, retained, TOPICS)
    summary = tables["national_summary"].iloc[0]
    assert summary["all_candidate_contexts"] == 5
    assert summary["paired_contexts"] == 4
    assert summary["retained_text_unavailable_contexts"] == 1
    assert summary["metadata_paired_abstained_contexts"] == 2
    assert summary["retained_text_paired_abstained_contexts"] == 1
    assert all(summary[category] == 1 for category in comparison.CATEGORIES)
    topic = tables["topic_shares"].set_index("topic").loc[1]
    assert topic["metadata_assigned_contexts"] == 2
    assert topic["metadata_share_of_paired"] == 0.5
    assert topic["retained_text_share_of_paired"] == 0.25
    assert (
        tables["bill_comparison"].set_index("bill_id").loc["missing", "comparison_category"]
        == "unavailable"
    )
    assert "accuracy" not in " ".join(tables["national_summary"].columns)
    assert len(tables["state_summary"]) == 50
    nj = tables["state_topic_shares"].query("scope == 'NJ'")
    assert nj["paired_contexts"].eq(0).all()
    assert nj["metadata_assigned_contexts"].isna().all()
    assert nj["metadata_share_of_paired"].isna().all()


def test_all_topics_observed_zero_and_unknown_transition_rows_remain_distinct():
    tables = comparison.comparison_tables(*frames(), TOPICS)
    assert len(tables["topic_shares"]) == 21
    assert len(tables["topic_transitions"]) == 22 * 22
    assert len(tables["state_topic_transitions"]) == 50 * 22 * 22
    assert tables["topic_shares"].set_index("topic").loc[23, "metadata_share_of_paired"] == 0
    transitions = tables["topic_transitions"]
    row = transitions[transitions["metadata_topic"].eq("1")].set_index("retained_text_topic")
    assert row.loc["1", "metadata_row_contexts"] == 2
    assert row.loc["1", "share_of_metadata_row"] == 0.5
    assert row.loc["23", "share_of_metadata_row"] == 0
    unknown = transitions[transitions["metadata_topic"].eq("23")]
    assert unknown["metadata_row_contexts"].eq(0).all()
    assert unknown["share_of_metadata_row"].isna().all()
    abstained = transitions[
        transitions["metadata_topic"].eq("abstained")
        & transitions["retained_text_topic"].eq("abstained")
    ].iloc[0]
    assert abstained["paired_transition_contexts"] == 1
    assert abstained["share_of_metadata_row"] == 0.5


def test_no_paired_population_is_unknown_not_zero_or_accuracy():
    metadata, retained = frames()
    retained = pd.DataFrame(
        [assignment(row.bill_id, None, "unavailable", row.state) for row in retained.itertuples()]
    )
    tables = comparison.comparison_tables(metadata, retained, TOPICS)
    assert tables["national_summary"].iloc[0]["paired_contexts"] == 0
    for key in ("metadata_share_of_paired", "retained_text_share_of_paired"):
        assert tables["topic_shares"][key].isna().all()
    assert tables["topic_transitions"]["share_of_metadata_row"].isna().all()
    assert tables["topic_transitions"]["paired_transition_contexts"].isna().all()
    assert tables["national_summary"].iloc[0]["unavailable"] == 5


@pytest.mark.parametrize("drift", ["id", "state", "duplicate", "flag", "absent"])
def test_assignment_identity_flags_and_missing_input_semantics_refuse_drift(drift):
    metadata, retained = frames()
    if drift == "id":
        retained.loc[0, "bill_id"] = "different-id"
    elif drift == "state":
        retained.loc[0, "state"] = "NJ"
    elif drift == "duplicate":
        retained.loc[0, "bill_id"] = retained.loc[1, "bill_id"]
    elif drift == "flag":
        retained.loc[0, "scientific_approval"] = True
    else:
        retained.loc[0, "n_source_views"] = 0
    with pytest.raises(ValueError):
        comparison.comparison_tables(metadata, retained, TOPICS)


def test_complete_self_contained_gallery_preserves_both_full_source_zips(completed, capsys):
    metadata, retained, output = completed
    assert (
        comparison.main(
            [
                "--metadata-gallery",
                str(metadata),
                "--retained-text-gallery",
                str(retained),
                "--out-dir",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == comparison.STATUS
    result = json.loads((output / "manifest.json").read_bytes())
    assert len(result["graphs"]) == 2
    assert all(result[flag] is False for flag in comparison.FLAGS)
    assert result["model_execution"] is False
    assert len(list((output / "graphs").iterdir())) == 4
    assert len(list((output / "chart-data").iterdir())) == 7
    for tier, source in zip(comparison.TIERS, (metadata, retained), strict=True):
        original = source / comparison.ARCHIVE
        copied = output / result["source_bundles"][tier]["download"]
        assert not copied.samefile(original)
        assert copied.stat().st_ino != original.stat().st_ino
        assert copied.read_bytes() == original.read_bytes()
        assert result["source_bundles"][tier]["full_source_zip"] == comparison.binding(copied)
        with zipfile.ZipFile(copied) as archive:
            rows = [
                json.loads(line) for line in archive.read(f"inputs/{tier}-CA.jsonl").splitlines()
            ]
            assert f"FULL ORIGINAL {tier}" in rows[0]["original_source_view"]["text"]
            assert rows[0]["original_source_view"]["retained_source_record"]["never_lost"] == [
                None,
                "full source record",
            ]
            assert f"predictions/{tier}-CA.jsonl" in archive.namelist()
            assert f"bill_assignments-{tier}.parquet" in archive.namelist()
        assert (output / f"research-data/{tier}_gallery_manifest.json").read_bytes() == (
            source / "manifest.json"
        ).read_bytes()
    inventory = {
        path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()
    }
    assert inventory == set(result["artifacts"]) | {"manifest.json"}
    assert all(
        comparison.binding(output / name) == value for name, value in result["artifacts"].items()
    )
    page = (output / "index.html").read_text()
    assert "not accuracy" in page and "both abstaining" in page.lower()
    with pytest.raises(ValueError, match="new project output"):
        comparison.compare(metadata, retained, output)


@pytest.mark.parametrize("drift", ["decision", "context", "runtime", "scope", "model", "flag"])
def test_frozen_plan_drift_fails_before_output_creation(completed, drift):
    metadata, retained, output = completed

    def modify(value):
        plan = json.loads(value)
        if drift == "decision":
            plan["decision"]["min_margin"] = 0.3
        elif drift == "context":
            plan["n_contexts"] += 1
        elif drift == "runtime":
            plan["inference_engine"] = "changed-input-policy"
        elif drift == "scope":
            plan["scope"] = "certified-party-attention"
        elif drift == "model":
            plan["model_run"] = "b" * 64
        else:
            plan["model_input_approved"] = True
        return encoded(plan)

    rewrite_member(retained, "inference_plan.json", modify)
    with pytest.raises(ValueError):
        comparison.compare(metadata, retained, output)
    assert not output.exists()


@pytest.mark.parametrize("drift", ["model", "flag", "id"])
def test_full_original_prediction_records_cannot_hide_drift(completed, drift):
    metadata, retained, output = completed

    def modify(value):
        rows = [json.loads(line) for line in value.splitlines()]
        if drift == "model":
            rows[0]["model_run"] = "b" * 64
        elif drift == "flag":
            rows[0]["analytical_admission"] = True
        else:
            rows[0]["input_id"] = "unmatched-original-source"
        return b"".join(encoded(row) for row in rows)

    rewrite_member(retained, "predictions/retained_text-CA.jsonl", modify)
    with pytest.raises(ValueError):
        comparison.compare(metadata, retained, output)
    assert not output.exists()


@pytest.mark.parametrize("drift", ["archive", "member", "incomplete", "traversal", "symlink"])
def test_corrupt_incomplete_or_unsafe_source_refused_without_output(completed, drift):
    metadata, retained, output = completed
    if drift == "archive":
        with (retained / comparison.ARCHIVE).open("ab") as handle:
            handle.write(b"changed original archive")
    elif drift == "member":
        manifest = json.loads((retained / "manifest.json").read_bytes())
        manifest["inference_inputs"]["inputs/retained_text-CA.jsonl"]["sha256"] = "0" * 64
        (retained / "manifest.json").write_bytes(encoded(manifest))
    elif drift == "incomplete":

        def modify(value):
            progress = json.loads(value)
            del progress["states"]["NJ"]
            return encoded(progress)

        rewrite_member(retained, "progress-retained_text.json", modify)
    elif drift == "traversal":
        manifest = json.loads((retained / "manifest.json").read_bytes())
        manifest["inference_inputs"]["../outside"] = bound(b"unsafe")
        (retained / "manifest.json").write_bytes(encoded(manifest))
    else:
        source = retained / "index.html"
        target = retained / "elsewhere.html"
        shutil.move(source, target)
        source.symlink_to(target)
    with pytest.raises(ValueError):
        comparison.compare(metadata, retained, output)
    assert not output.exists()


def test_unknown_empty_pair_graphs_render_without_invented_zero_data(completed):
    metadata, retained, output = completed
    left, right = frames()
    right = pd.DataFrame(
        [assignment(row.bill_id, None, "unavailable", row.state) for row in right.itertuples()]
    )
    tables = comparison.comparison_tables(left, right, TOPICS)
    graph_dir = output.parent / "synthetic-empty-graphs"
    graph_dir.mkdir(parents=True)
    assert comparison.render(graph_dir, tables) == ["topic_shares", "topic_transitions"]
    assert len(list(graph_dir.iterdir())) == 4

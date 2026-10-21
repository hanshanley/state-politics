"""Synthetic integrity checks for provisional external-label preparation."""

import csv
import hashlib
import json
from functools import partial

import pytest

from state_politics.analysis import prepare_topics
from state_politics.analysis.prepare_topics import prepare

TEXT = (
    "This proposal establishes a comprehensive program supporting local communities "
    "through improved public services and long term planning."
)


def source(directory, filename, topics, *, texts=None, subtopics=None):
    path = directory / filename
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "id", "year", "majortopic", "subtopic", "pap_majortopic",
            "pap_subtopic", "description", "bill_id",
        ])
        writer.writeheader()
        for index, topic in enumerate(topics):
            subtopic = subtopics[index] if subtopics else topic * 100
            writer.writerow({
                "id": f"source-{index}", "year": 2020,
                "majortopic": topic, "subtopic": subtopic,
                "pap_majortopic": topic, "pap_subtopic": subtopic,
                "description": texts[index] if texts else TEXT,
                "bill_id": f"family-{index}",
            })
    return filename, "bill", f"https://example.invalid/{filename}", hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def run_prepare(directory, sources, *, cap=10):
    return prepare(
        directory, [1, 3], per_source_topic=cap, min_year=2000,
        seed=17, reviewed=[], sources=sources,
    )


@pytest.mark.parametrize("topics", [[1, 3], [3, 1]])
def test_conflicting_duplicate_labels_fail_closed(tmp_path, topics):
    descriptor = source(
        tmp_path, "synthetic.csv", topics,
        texts=[TEXT, TEXT.upper().replace(".", "!")],
    )
    with pytest.raises(ValueError, match="conflicting external labels") as error:
        run_prepare(tmp_path, [descriptor], cap=1)
    assert "synthetic.csv:2" in str(error.value)
    assert "synthetic.csv:3" in str(error.value)


@pytest.mark.parametrize("topics", [[1, 3], [3, 1]])
def test_conflicting_duplicates_across_sources_fail_closed(tmp_path, topics):
    sources = [
        source(tmp_path, "first.csv", [topics[0]]),
        source(tmp_path, "second.csv", [topics[1]]),
    ]
    with pytest.raises(ValueError, match="conflicting external labels") as error:
        run_prepare(tmp_path, sources)
    assert "first.csv:2" in str(error.value)
    assert "second.csv:2" in str(error.value)


def test_same_label_duplicate_preserves_evidence_and_accounting(tmp_path):
    descriptor = source(tmp_path, "synthetic.csv", [1, 1])
    rows, report = run_prepare(tmp_path, [descriptor])
    assert len(rows) == 1
    assert rows[0]["text"] == TEXT
    assert rows[0]["topic"] == 1
    assert rows[0]["source_record_id"] == "source-0"
    assert rows[0]["source_csv_line"] == 2
    assert rows[0]["source_sha256"] == descriptor[3]
    assert report["sources"][0]["n_raw"] == 2
    assert report["sources"][0]["dispositions"] == {
        "eligible_initialization_candidate": 1,
        "exact_duplicate_or_target_overlap": 1,
    }


def test_quarantined_label_does_not_create_duplicate_conflict(tmp_path):
    descriptor = source(
        tmp_path, "synthetic.csv", [1, 3], subtopics=[100, 100],
    )
    rows, report = run_prepare(tmp_path, [descriptor])
    assert [row["topic"] for row in rows] == [1]
    assert report["sources"][0]["dispositions"] == {
        "eligible_initialization_candidate": 1, "quarantined": 1,
    }


@pytest.mark.parametrize("reverse_sources", [False, True])
def test_explicit_policy_excludes_every_cross_source_member_before_sampling(
    tmp_path, reverse_sources,
):
    different = TEXT + " Additional provisions address a distinct local issue."
    sources = [
        source(tmp_path, "first.csv", [1, 1], texts=[TEXT, different]),
        source(tmp_path, "second.csv", [3, 3], texts=[TEXT.upper(), TEXT]),
    ]
    if reverse_sources:
        sources.reverse()
    rows, report = prepare(
        tmp_path, [1, 3], per_source_topic=1, min_year=2000,
        seed=17, reviewed=[], sources=sources, conflict_policy="exclude-groups",
    )
    assert [row["text"] for row in rows] == [different]
    assert report["conflicting_eligible_group_count"] == 1
    assert report["excluded_conflicting_row_count"] == 3
    excluded = report["excluded_conflicting_rows"]
    assert {row["source_file"] for row in excluded} == {"first.csv", "second.csv"}
    assert {row["source_csv_line"] for row in excluded} == {2, 3}
    assert all(row["competing_topics"] == [1, 3] for row in excluded)
    assert len({row["normalized_text_sha256"] for row in excluded}) == 1
    assert {row["source_record"]["description"] for row in excluded} == {
        TEXT, TEXT.upper(),
    }
    assert sum(
        item["dispositions"].get("quarantined_conflicting_label_group", 0)
        for item in report["sources"]
    ) == 3


def test_explicit_policy_preserves_same_topic_and_existing_compatibility_rules(tmp_path):
    descriptor = source(
        tmp_path, "synthetic.csv", [1, 1, 3], subtopics=[100, 100, 100],
    )
    rows, report = prepare(
        tmp_path, [1, 3], per_source_topic=10, min_year=2000,
        seed=17, reviewed=[], sources=[descriptor], conflict_policy="exclude-groups",
    )
    assert [row["topic"] for row in rows] == [1]
    assert report["conflicting_eligible_group_count"] == 0
    assert report["excluded_conflicting_rows"] == []
    assert report["sources"][0]["dispositions"] == {
        "eligible_initialization_candidate": 1,
        "exact_duplicate_or_target_overlap": 1, "quarantined": 1,
    }


def test_explicit_policy_writes_auditable_full_source_exclusions(tmp_path, monkeypatch):
    descriptor = source(
        tmp_path, "synthetic.csv", [1, 3, 1],
        texts=[TEXT, TEXT, TEXT + " A separate program addresses another issue."],
    )
    monkeypatch.setattr(prepare_topics, "prepare", partial(prepare, sources=[descriptor]))
    out = tmp_path / "prepared"
    assert prepare_topics.main([
        "--cap-dir", str(tmp_path), "--out", str(out),
        "--conflict-policy", "exclude-groups",
    ]) == 0
    manifest = json.loads((out / "source_manifest.json").read_text())
    exclusions = out / manifest["conflict_exclusions"]["path"]
    assert hashlib.sha256(exclusions.read_bytes()).hexdigest() == (
        manifest["conflict_exclusions"]["sha256"]
    )
    rows = [json.loads(line) for line in exclusions.read_text().splitlines()]
    assert len(rows) == manifest["conflict_exclusions"]["n_rows"] == 2
    assert rows[0]["source_record"]["description"] == TEXT
    assert "excluded_conflicting_rows" not in manifest


def test_unknown_conflict_policy_fails_explicitly(tmp_path):
    with pytest.raises(ValueError, match="conflict policy"):
        prepare(
            tmp_path, [1, 3], per_source_topic=1, min_year=2000,
            seed=17, reviewed=[], sources=[], conflict_policy="choose-first",
        )

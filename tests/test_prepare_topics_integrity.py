"""Synthetic integrity checks for provisional external-label preparation."""

import csv
import hashlib

import pytest

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

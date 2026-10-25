"""Journal mentions cannot silently become complete same-edition resolution bodies."""

import hashlib
import json

import pytest

from state_politics.bills import ne_journal_text as journal


def page(number, text):
    return {
        "page": number,
        "text": text,
        "characters": len(text),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def fixture_pages():
    return [
        page(
            1,
            "THIRTY-SEVENTH DAY - MARCH 4, 2024\n897\n"
            "LEGISLATIVE RESOLUTION 315. Introduced by Wishart, 27.\n"
            "WHEREAS, community programs create learning opportunities;\n",
        ),
        page(
            2,
            "LEGISLATIVE JOURNAL\n898\n"
            "NOW, THEREFORE, BE IT RESOLVED BY THE MEMBERS OF THE\n"
            "ONE HUNDRED EIGHTH LEGISLATURE OF NEBRASKA, SECOND\n"
            "SESSION:\n"
            "1. That the Legislature recognizes expanded learning programs.\n"
            "Laid over.\nGENERAL FILE\nLEGISLATIVE BILL 906. Title read.\n",
        ),
    ]


def context(**changes):
    return {
        "bill_id": "original-context",
        "state": "NE",
        "identifier": "LR 315",
        "session_identifier": "108",
        "source_introduction_date": "2024-03-04",
        "title": "Recognize expanded learning programs",
        **changes,
    }


def test_two_reader_complete_body_and_raw_fragments_preserve_source_not_footer():
    pages = fixture_pages()
    alternative = [page(row["page"], row["text"].replace(" ", "")) for row in pages]
    views, dispositions, _ = journal.qualify(
        {"pymupdf": pages, "pypdf": alternative},
        [context()],
    )
    assert len(views) == 2
    assert dispositions[0]["disposition"] == "complete_two_reader_original_context_match"
    for view, raw in zip(views, (pages, alternative), strict=True):
        assert "906" not in view["text"] and "Laid" not in view["text"]
        assert len(view["source_record"]["page_fragments"]) == 2
        fragments = view["source_record"]["page_fragments"]
        rebuilt = "\n".join(
            raw[span["page"] - 1]["text"][span["start"] : span["end"]] for span in fragments
        )
        assert rebuilt == view["text"]
        assert all(view[flag] is False for flag in journal.FLAGS)
    assert views[0]["text"] != views[1]["text"]


@pytest.mark.parametrize(
    "defect",
    [
        "no_end",
        "next_bill",
        "wrong_session",
        "wrong_date",
        "reader_disagreement",
        "missing_page",
        "constitutional",
        "duplicate_context",
    ],
)
def test_incomplete_unresolved_or_conflicting_sources_are_not_admitted(defect):
    a = fixture_pages()
    b = fixture_pages()
    originals = [context()]
    if defect == "no_end":
        a[1] = page(2, a[1]["text"].replace("Laid over.", ""))
    elif defect == "next_bill":
        a[1] = page(
            2,
            a[1]["text"].replace(
                "Laid over.",
                "LEGISLATIVE BILL 99. Next item.\nLaid over.",
            ),
        )
    elif defect == "wrong_session":
        a[1] = page(2, a[1]["text"].replace("SECOND", "FIRST"))
    elif defect == "wrong_date":
        originals = [context(source_introduction_date="2023-03-04")]
    elif defect == "reader_disagreement":
        b[1] = page(2, b[1]["text"].replace("expanded", "reduced"))
    elif defect == "missing_page":
        a = [a[0]]
    elif defect == "constitutional":
        a[0] = page(1, a[0]["text"].replace("315.", "315CA."))
    elif defect == "duplicate_context":
        originals.append(context(bill_id="other-original"))
    views, dispositions, _ = journal.qualify({"pymupdf": a, "pypdf": b}, originals)
    assert not views
    assert all(
        row["disposition"] != "complete_two_reader_original_context_match" for row in dispositions
    )


def test_wrong_page_hash_is_rejected_not_repaired():
    pages = fixture_pages()
    pages[0]["text"] += "changed"
    with pytest.raises(ValueError, match="page identity"):
        journal.resolution_candidates(pages)


def test_archive_dispatch_preserves_typed_loader_and_current_metadata(tmp_path, monkeypatch):
    from state_politics.bills import archive_text

    (tmp_path / "manifest.json").write_text(json.dumps({"schema": journal.SCHEMA}))
    metadata = [context()]
    sentinel = object()

    def loader(directory, current):
        assert directory == tmp_path and current is metadata
        return sentinel

    monkeypatch.setattr(journal, "load_ne_journal", loader)
    assert archive_text.load_archive(tmp_path, metadata) is sentinel


def test_builder_refuses_public_or_external_output_before_reading_inputs(tmp_path):
    with pytest.raises(ValueError, match="under project data/processed"):
        journal.build(
            tmp_path / "source",
            tmp_path / "readers",
            tmp_path / "queue.parquet",
            tmp_path / "public",
        )
    assert not (tmp_path / "public").exists()

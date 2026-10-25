"""Expanded fixed journal profiles preserve complete sources and sealed v1 behavior."""

import hashlib
import json

import pytest

from state_politics.bills import ne_journal_collection as collection
from state_politics.bills import ne_journal_text as sealed


def page(number, text):
    return {
        "page": number,
        "text": text,
        "characters": len(text),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def context(year=2023, **changes):
    return {
        "bill_id": "original-context",
        "state": "NE",
        "identifier": "LR 5",
        "session_identifier": "108",
        "source_introduction_date": f"{year}-01-05",
        "title": "A complete original resolution",
        "unknown_party": None,
        **changes,
    }


def book(year=2023, **changes):
    return {
        "year": year,
        "session": "FIRST" if year == 2023 else "SECOND",
        "volume": 1,
        "pages": 2,
        "sha256": "a" * 64,
        "url": "https://example.org/complete-journal.pdf",
        **changes,
    }


def source_pages(year=2023, *, wrapped=True, recital=True):
    introduction = (
        "LEGISLATIVE\nRESOLUTION\n5.\nIntroduced\nby\nAuthor, 1;\n"
        if wrapped
        else "LEGISLATIVE RESOLUTION 5. Introduced by Author, 1;\n"
    )
    first = (
        f"SECOND DAY - JANUARY 5, {year}\n1\n"
        + introduction
        + ("WHEREAS, public services provide community opportunities;\n" if recital else "")
    )
    session = "FIRST" if year == 2023 else "SECOND"
    second = (
        "LEGISLATIVE JOURNAL\n2\n"
        "NOW, THEREFORE, BE IT RESOLVED BY THE MEMBERS OF THE\n"
        f"ONE HUNDRED EIGHTH LEGISLATURE OF NEBRASKA, {session}\nSESSION:\n"
        "1. That the Legislature directs a complete study of community public services.\n"
        "Laid over.\nGENERAL FILE\nLEGISLATIVE BILL 906. Next unrelated item.\n"
    )
    return [page(1, first), page(2, second)]


def readers(pages):
    return {
        "pymupdf": pages,
        "pypdf": [page(row["page"], row["text"].replace(" ", "")) for row in pages],
    }


@pytest.mark.parametrize("year", [2023, 2024])
def test_whole_reader_bodies_dates_fragments_and_distinct_view_namespace(year):
    raw = source_pages(year)
    supplied = readers(raw)
    views, dispositions, _ = collection.qualify(
        {"book": supplied}, [context(year)], books={"book": book(year)}
    )
    assert len(views) == 2
    assert dispositions[0]["disposition"] == "complete_two_reader_original_context_match"
    assert views[0]["text"] != views[1]["text"]
    assert sealed.compact(views[0]["text"]) == sealed.compact(views[1]["text"])
    assert len({row["view_id"] for row in views}) == 2
    assert all(not row["view_id"].startswith("ne-journal:") for row in views)
    for view in views:
        original = supplied[view["source_record"]["reader"]]
        rebuilt = "\n".join(
            original[s["page"] - 1]["text"][s["start"] : s["end"]]
            for s in view["source_record"]["page_fragments"]
        )
        assert rebuilt == view["text"]
        assert "906" not in rebuilt and "Laid" not in rebuilt
        assert view["source_record"]["journal_date"] == f"{year}-01-05"
        assert all(view[flag] is False for flag in sealed.FLAGS)


def test_complete_numbered_operative_resolution_does_not_require_optional_recitals():
    views, _, _ = collection.qualify(
        {"book": readers(source_pages(recital=False))},
        [context()],
        books={"book": book()},
    )
    assert len(views) == 2 and all("WHEREAS" not in row["text"] for row in views)


def test_literal_printed_header_repair_preserves_policy_and_legacy_profile():
    raw = source_pages()
    raw[1] = page(
        2,
        raw[1]["text"].replace("1. That", "LEGISLATIVE JOURNAL2\n1. That", 1),
    )
    supplied = readers(raw)
    supplied["pypdf"][1] = page(
        2,
        supplied["pypdf"][1]["text"].replace(
            "LEGISLATIVEJOURNAL\n2\n", "LEGISLA TIVEJOURNAL2\n", 1
        ),
    )
    args = ({"book": supplied}, [context()])
    legacy, rejected, _ = collection.qualify(
        *args, books={"book": book()}, header_profile=collection.LEGACY_HEADERS
    )
    assert not legacy
    assert rejected[0]["disposition"] == "PDF_readers_disagree_on_complete_body"
    views, _, _ = collection.qualify(*args, books={"book": book()})
    assert len(views) == 2
    assert all(view["view_id"].startswith("ne-journal-collection-v2:") for view in views)
    for view in views:
        assert "LEGISLATIVEJOURNAL2" in sealed.compact(view["text"])
        fragment = view["source_record"]["page_fragments"][1]
        prefix = fragment["excluded_page_prefix"]
        text = supplied[view["source_record"]["reader"]][1]["text"]
        assert prefix["start"] == 0 and prefix["end"] == fragment["start"]
        assert prefix["text"] == text[: prefix["end"]]
        assert prefix["sha256"] == hashlib.sha256(prefix["text"].encode()).hexdigest()
        assert sealed.compact(prefix["text"]) == "LEGISLATIVEJOURNAL2"
    assert sealed.compact(views[0]["text"]) == sealed.compact(views[1]["text"])


def test_literal_header_rule_does_not_remove_a_policy_lookalike():
    text = "LEGISLATIVE JOURNAL RIGHTS\nProtect complete public policy text.\n"
    stream, spans = collection.collection_stream([page(1, text)], collection.LITERAL_HEADERS)
    assert stream == text
    assert spans[0]["raw_start"] == 0
    assert spans[0]["excluded_page_prefix"] is None


@pytest.mark.parametrize(
    "defect",
    [
        "no_end",
        "next_bill",
        "wrong_venue",
        "wrong_year",
        "wrong_original_date",
        "reader_disagrees",
        "missing_page",
        "constitutional",
        "duplicate_context",
        "no_own_header",
    ],
)
def test_incomplete_wrong_scope_or_conflicting_text_never_becomes_a_body(defect):
    supplied = readers(source_pages())
    originals = [context()]
    books = {"book": book()}
    if defect == "no_end":
        supplied["pymupdf"][1] = page(2, supplied["pymupdf"][1]["text"].replace("Laid over.", ""))
    elif defect == "next_bill":
        supplied["pymupdf"][1] = page(
            2,
            supplied["pymupdf"][1]["text"].replace(
                "Laid over.", "LEGISLATIVE BILL 99. Intervening legislation.\nLaid over."
            ),
        )
    elif defect == "wrong_venue":
        supplied["pymupdf"][1] = page(2, supplied["pymupdf"][1]["text"].replace("FIRST", "SECOND"))
    elif defect == "wrong_year":
        books["book"] = book(2024)
    elif defect == "wrong_original_date":
        originals = [context(source_introduction_date="2023-01-06")]
    elif defect == "reader_disagrees":
        supplied["pypdf"][1] = page(2, supplied["pypdf"][1]["text"].replace("public", "private"))
    elif defect == "missing_page":
        supplied["pymupdf"] = supplied["pymupdf"][:1]
    elif defect == "constitutional":
        supplied["pymupdf"][0] = page(1, supplied["pymupdf"][0]["text"].replace("5.", "5CA."))
    elif defect == "duplicate_context":
        originals.append(context(bill_id="other-original"))
    elif defect == "no_own_header":
        supplied["pymupdf"][0] = page(
            1, "SECOND DAY - JANUARY 5, 2023\n1\nWHEREAS, a mere mention of LR 5;\n"
        )
    views, dispositions, _ = collection.qualify({"book": supplied}, originals, books=books)
    assert not views
    assert all(
        row["disposition"] != "complete_two_reader_original_context_match" for row in dispositions
    )


def test_reader_agreement_cannot_bridge_two_different_pdf_documents():
    a, b = readers(source_pages()), readers(source_pages())
    a["pypdf"][1] = page(2, a["pypdf"][1]["text"].replace("Laidover.", ""))
    b["pymupdf"][1] = page(2, b["pymupdf"][1]["text"].replace("Laid over.", ""))
    views, dispositions, _ = collection.qualify(
        {"a": a, "b": b},
        [context()],
        books={"a": book(), "b": book(sha256="b" * 64)},
    )
    assert (
        not views and dispositions[0]["disposition"] == "readers_select_different_source_documents"
    )


def test_expanded_profile_does_not_modify_sealed_v1_default_parser():
    original = readers(source_pages(2024, wrapped=False))
    before = sealed.qualify(original, [context(2024)])
    assert len(before[0]) == 2
    collection.qualify({"book": readers(source_pages())}, [context()], books={"book": book()})
    assert sealed.qualify(original, [context(2024)]) == before


def test_tampered_page_text_is_refused_not_silently_fixed():
    pages = source_pages()
    pages[0]["text"] += "modified after hashing"
    with pytest.raises(ValueError, match="page identity"):
        collection.candidates(pages, book())


@pytest.mark.parametrize("schema", [collection.LEGACY_SCHEMA, collection.SCHEMA])
def test_new_archive_schema_dispatch_passes_all_current_metadata(tmp_path, monkeypatch, schema):
    from state_politics.bills import archive_text

    (tmp_path / "manifest.json").write_text(json.dumps({"schema": schema}))
    metadata = [context()]
    sentinel = object()

    def loader(directory, current):
        assert directory == tmp_path and current is metadata
        return sentinel

    monkeypatch.setattr(collection, "load_ne_journal_collection", loader)
    assert archive_text.load_archive(tmp_path, metadata) is sentinel


def test_builder_refuses_nonprocessed_output_before_reading_any_source(tmp_path):
    with pytest.raises(ValueError, match="under project data/processed"):
        collection.build(*(tmp_path / name for name in ("s1", "r1", "s2", "r2", "gap", "public")))
    assert not (tmp_path / "public").exists()

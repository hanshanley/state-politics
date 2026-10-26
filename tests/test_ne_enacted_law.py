"""Enacted law evidence must not become introduced versions or repaired dates."""

import hashlib
import json
from pathlib import Path

import pytest

from state_politics.bills import ne_enacted_law_text as laws
from state_politics.bills.ne_journal_text import FLAGS, compact


def page(number, text):
    return {
        "page": number,
        "text": text,
        "characters": len(text),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def book():
    return {
        "year": 2024,
        "session": "SECOND",
        "volume": 2,
        "pages": 3,
        "sha256": "a" * 64,
        "url": "https://example.org/enacted-laws.pdf",
    }


def original(**changes):
    return {
        "bill_id": "original-bill",
        "state": "NE",
        "session_identifier": "108",
        "identifier": "LB 1143",
        "source_introduction_date": "2023-01-11",
        "title": "Original title remains unchanged",
        "unknown_party": None,
        **changes,
    }


def source():
    return [
        page(
            1,
            "LB1143\n2024\nLEGISLATIVE BILL 1143\n"
            "Approved by the Governor April 2, 2024\nIntroduced by Author, 1.\n"
            "A BILL FOR AN ACT relating to public health.\n"
            "Be it enacted by the people of the State of Nebraska,\n"
            "Section 1. The complete first provision continues\n-1-\n695\n",
        ),
        page(
            2,
            "LB1143\n2024\nwith all of its operative language.\n"
            "Sec. 2. The complete final provision is retained.\n-2-\n696\n",
        ),
        page(
            3,
            "LB1144\n2024\nLEGISLATIVE BILL 1144\n"
            "Approved by the Governor April 3, 2024\nIntroduced by Another, 2.\n"
            "A BILL FOR AN ACT relating to a different subject.\n"
            "Be it enacted by the people of the State of Nebraska,\n"
            "Section 1. Other legislation must not enter the prior body.\n-1-\n697\n",
        ),
    ]


def qualify(raw=None, originals=None, py=None):
    raw = source() if raw is None else raw
    py = [page(row["page"], row["text"].replace(" ", "\t")) for row in raw] if py is None else py
    return laws.qualify(
        {"book": {"pymupdf": raw, "pypdf": py}},
        [original()] if originals is None else originals,
        books={"book": book()},
    )


def test_complete_enacted_law_preserves_original_date_and_every_raw_character():
    context = original()
    before = context.copy()
    raw = source()
    views, dispositions, _ = qualify(raw, [context])
    assert len(views) == 2 and context == before
    assert dispositions[0]["disposition"] == "complete_two_reader_enacted_version_match"
    assert compact(views[0]["text"]) == compact(views[1]["text"])
    assert views[0]["text"] == "\n".join(row["text"] for row in raw[:2])
    for view in views:
        record = view["source_record"]
        assert record["original_introduction_date"] == "2023-01-11"
        assert record["approval_date"] == "2024-04-02"
        assert record["version_scope"] == "enacted_law_not_introduced"
        assert view["source_version"]["note"] == "Enacted law, not introduced text"
        assert all(view[flag] is False for flag in FLAGS)
        assert "Other legislation" not in view["text"]
        selected = (
            raw
            if record["reader"] == "pymupdf"
            else [page(row["page"], row["text"].replace(" ", "\t")) for row in raw]
        )
        assert (
            "\n".join(
                selected[part["page"] - 1]["text"][part["start"] : part["end"]]
                for part in record["page_fragments"]
            )
            == view["text"]
        )


@pytest.mark.parametrize(
    "defect",
    [
        "wrong_session",
        "wrong_typed_identifier",
        "approval_before_introduction",
        "missing_original_date",
        "missing_caption",
        "missing_enacting_clause",
        "missing_first_section",
        "missing_terminal_period",
        "missing_folio",
        "nonconsecutive_folio",
        "wrong_running_header",
        "missing_approval",
        "wrong_approval_year",
        "malformed_approval_date",
    ],
)
def test_incomplete_misidentified_or_date_conflicting_laws_are_not_admitted(defect):
    raw = source()
    context = original()
    if defect == "wrong_session":
        context["session_identifier"] = "107"
    elif defect == "wrong_typed_identifier":
        context["identifier"] = "LR 1143"
    elif defect == "approval_before_introduction":
        context["source_introduction_date"] = "2024-04-03"
    elif defect == "missing_original_date":
        context["source_introduction_date"] = None
    else:
        index = (
            1
            if defect
            in {
                "missing_terminal_period",
                "missing_folio",
                "nonconsecutive_folio",
                "wrong_running_header",
            }
            else 0
        )
        replacements = {
            "missing_caption": ("A BILL FOR AN ACT", "A SUMMARY"),
            "missing_enacting_clause": ("Be it enacted", "Described"),
            "missing_first_section": ("Section 1.", "Article 1."),
            "missing_terminal_period": ("retained.", "retained"),
            "missing_folio": ("-2-", ""),
            "nonconsecutive_folio": ("-2-", "-3-"),
            "wrong_running_header": ("LB1143", "LB1144"),
            "missing_approval": ("Approved by the Governor", "Discussed"),
            "wrong_approval_year": ("April 2, 2024", "April 2, 2023"),
            "malformed_approval_date": ("April 2, 2024", "April 32, 2024"),
        }
        old, new = replacements[defect]
        raw[index] = page(index + 1, raw[index]["text"].replace(old, new, 1))
    views, dispositions, candidates = qualify(raw, [context])
    assert (
        not views and dispositions[0]["disposition"] != "complete_two_reader_enacted_version_match"
    )
    assert len(candidates) == 4


def test_whole_reader_policy_conflicts_are_preserved_and_rejected():
    raw = source()
    py = list(raw)
    py[1] = page(2, raw[1]["text"].replace("final provision", "different final provision"))
    views, dispositions, inventory = qualify(raw, py=py)
    assert not views and dispositions[0]["disposition"] == "whole_enacted_law_reader_disagreement"
    assert any("different final provision" in row["text"] for row in inventory)


def test_original_identity_collisions_do_not_select_an_arbitrary_bill():
    views, dispositions, _ = qualify(
        originals=[
            original(),
            original(bill_id="another-original", unknown_party="unknown"),
        ]
    )
    assert not views
    assert all(row["disposition"] == "ambiguous_original_context_identity" for row in dispositions)


def test_appropriation_suffix_remains_a_distinct_typed_identity():
    raw = [page(row["page"], row["text"].replace("1143", "1143A")) for row in source()]
    views, dispositions, _ = qualify(
        raw,
        [
            original(identifier="LB 1143A"),
            original(bill_id="ordinary", identifier="LB 1143"),
        ],
    )
    assert len(views) == 2 and {view["bill_id"] for view in views} == {"original-bill"}
    assert dispositions[1]["disposition"] != "complete_two_reader_enacted_version_match"


def test_generic_archive_dispatches_the_new_typed_schema(tmp_path, monkeypatch):
    from state_politics.bills import archive_text

    (tmp_path / "manifest.json").write_text(json.dumps({"schema": laws.SCHEMA}))
    sentinel = object()
    monkeypatch.setattr(laws, "load_ne_enacted_law", lambda directory, metadata: sentinel)
    assert archive_text.load_archive(tmp_path, [{"bill_id": "original"}]) is sentinel


def test_source_builder_refuses_public_output_before_any_copy():
    with pytest.raises(ValueError, match="fresh unlinked output"):
        laws.build(Path("/unused"), Path("/unused"), Path("/unused"), laws.ROOT / "outputs")

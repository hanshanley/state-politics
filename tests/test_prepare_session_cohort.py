"""A session frame adds complete evidence, not invented dates or primary admission."""

import copy
import gzip
import hashlib
import json

import pytest

from state_politics.analysis.prepare_session_cohort import (
    _copy_native,
    metadata_views,
    reconcile_members,
)
from state_politics.site_evidence import ADMISSIONS


def fixture_rows():
    bill = {
        "bill_id": "bill:1", "state": "NY", "identifier": "HB 1",
        "session_identifier": "2023-2024", "title": "Complete bill title",
        "source_unknown_field": "retain unchanged", "source_introduction_date": None,
    }
    context = {
        **{key: bill[key] for key in ("bill_id", "state", "identifier", "session_identifier")},
        "context_id": "reference:1", "packet_root": "retained/NY",
        "canonical_join_mode": "typed_key",
        "canonical_join_basis": "unique_declared_session_typed_identity",
        "state_native": "NY", "session_identifier_native": "2023-2024",
        "n_retained_views": 2, "native_identity_certified": False,
        "analytical_admission": False, "source_introduction_date": None,
    }
    contracts = {"retained/NY": {"state": "NY", "session_identifier": "2023-2024"}}
    return bill, context, contracts


def test_session_members_preserve_physical_references_missing_dates_and_exclusions():
    bill, context, contracts = fixture_rows()
    repeated = {**context, "context_id": "reference:2", "n_retained_views": 0}
    negative = {
        **context, "context_id": "reference:negative", "canonical_join_mode": "source_only",
        "bill_id": None,
    }
    abstract = {"id": "abstract:1", "bill_id": bill["bill_id"], "abstract": "Full summary",
                "note": "Keep the complete original note"}
    original = copy.deepcopy([bill, context, repeated, negative, abstract])
    members, excluded = reconcile_members(
        [context, repeated, negative], [bill], [], [abstract], contracts,
    )
    assert len(members) == 1
    member = members[0]
    assert member["n_native_references"] == 2
    assert member["n_retained_native_views"] == 2
    assert member["source_bill"] == bill
    assert member["native_contexts"] == [context, repeated]
    assert member["abstract_records"] == [abstract]
    assert member["calendar_context"] is None
    assert member["calendar_candidate_member"] is False
    assert member["event_dates_inferred"] is False
    assert all(member[key] is False for key in ADMISSIONS)
    assert excluded == [negative]
    assert [bill, context, repeated, negative, abstract] == original


@pytest.mark.parametrize("defect", ["bill", "calendar", "admission", "duplicate_reference"])
def test_session_member_refuses_identity_errors_and_false_approval(defect):
    bill, context, contracts = fixture_rows()
    contexts, calendar = [context], []
    if defect == "bill":
        bill["identifier"] = "HB 2"
    elif defect == "calendar":
        calendar = [{**bill, "session_identifier": "2025-2026", "analytical_admission": False}]
    elif defect == "admission":
        context["native_identity_certified"] = True
    else:
        contexts.append(context.copy())
    with pytest.raises(ValueError):
        reconcile_members(contexts, [bill], calendar, [], contracts)


def test_metadata_preserves_complete_unicode_variants_without_propagating_dates():
    bill, context, contracts = fixture_rows()
    source = "Full\u2028source\u2029text with an arbitrarily long ending " + "ending " * 3000
    abstracts = [
        {"id": f"a:{index}", "bill_id": bill["bill_id"], "abstract": source + str(index),
         "note": f"Full note {index}"} for index in range(2)
    ]
    members, _ = reconcile_members([context], [bill], [], abstracts, contracts)
    views = metadata_views(members[0])
    assert len(views) == 2
    assert len({row["view_id"] for row in views}) == 2
    for view, abstract in zip(views, abstracts, strict=True):
        assert view["text"] == bill["title"] + "\n\n" + abstract["abstract"]
        assert view["input_sha256"] == hashlib.sha256(view["text"].encode()).hexdigest()
        assert view["n_input_characters"] == len(view["text"])
        assert view["abstract_record"] == abstract
        assert view["source_bill"] == bill
        assert view["calendar_candidate_member"] is False
        assert view["event_dates_inferred"] is False
        assert all(view[key] is False for key in ADMISSIONS)


def test_metadata_with_no_summary_keeps_missing_title_explicit():
    bill, context, contracts = fixture_rows()
    bill["title"] = None
    members, _ = reconcile_members([context], [bill], [], [], contracts)
    views = metadata_views(members[0])
    assert len(views) == 1
    assert views[0]["text"] == ""
    assert views[0]["metadata_tier"] == "missing_metadata"
    assert views[0]["source_bill"]["title"] is None
    assert views[0]["abstract_record"] is None


def test_native_copy_is_original_bytes_including_large_integers_and_unicode(tmp_path):
    bill, context, contracts = fixture_rows()
    members, _ = reconcile_members([context], [bill], [], [], contracts)
    row = {
        **{key: bill[key] for key in ("bill_id", "state", "identifier", "session_identifier")},
        "packet_root": "retained/NY", "view_id": "view:1", "source_type": "native_text",
        "text": "Complete\u2028native\u2029text", "source_stat": 1792612374203564526,
        **dict.fromkeys(ADMISSIONS, False),
    }
    row["input_sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
    row["n_input_characters"] = len(row["text"])
    raw = (json.dumps(row, ensure_ascii=False, separators=(", ", ": ")) + "\n").encode()
    source = tmp_path / "source.jsonl.gz"
    source.write_bytes(gzip.compress(raw))
    out = tmp_path / "out"
    out.mkdir()
    assert _copy_native("NY", [source], {bill["bill_id"]: members[0]}, {
        ("retained/NY", "view:1"): row,
    }, out) == 1
    assert (out / "native-NY.jsonl").read_bytes() == raw
    assert gzip.decompress((out / "native-NY.jsonl.gz").read_bytes()) == raw


def test_native_copy_refuses_missing_or_modified_text(tmp_path):
    bill, context, contracts = fixture_rows()
    members, _ = reconcile_members([context], [bill], [], [], contracts)
    source = tmp_path / "empty.gz"
    source.write_bytes(gzip.compress(b""))
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(ValueError, match="missing complete retained native views"):
        _copy_native("NY", [source], {bill["bill_id"]: members[0]}, {
            ("retained/NY", "missing"): {"input_sha256": "a" * 64},
        }, output)

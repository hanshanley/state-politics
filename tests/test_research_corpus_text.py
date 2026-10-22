import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from state_politics.bills.research_corpus_text import (
    ANCESTOR_FILES,
    FLAGS,
    REVISION,
    SOURCE_FILES,
    load_corpus,
    printed_identity,
    recover,
)
from state_politics.provenance import sha256_file

NH = (
    "HB 0042-FN - AS INTRODUCED 2023 SESSION 23-0012 01/02 "
    "HOUSE BILL 42-FN STATE OF NEW HAMPSHIRE "
    "Be it Enacted by the Senate and House of Representatives in General Court convened: "
    "1 Complete policy text.\u2028Alternative line.\n"
)
IL = (
    "104TH GENERAL ASSEMBLY State of Illinois 2025 and 2026 HB0027 Introduced "
    "A BILL FOR HB0027 Be it enacted by the People of the State of Illinois: "
    "Section 1. Complete text."
)


@pytest.fixture
def corpus_sources(tmp_path):
    directory = tmp_path / "sources"
    directory.mkdir()
    tree = []
    for state, text in (("NH", NH), ("IL", IL)):
        rows = [
            {"text": text, "summary": "Source summary, NOT human gold", "title": "Source title"},
            {"text": text, "summary": "Original duplicate alternative", "title": None},
            {"text": "Title only; effective July 1, 2023.", "summary": None, "title": "Other"},
        ]
        p = directory / SOURCE_FILES[state]
        p.write_text(json.dumps(rows, ensure_ascii=False))
        tree.append({"path": p.name, "size": p.stat().st_size,
                     "lfs": {"oid": sha256_file(p)}})
    (directory / "mtsu-file-tree.json").write_text(json.dumps(tree))
    (directory / "mtsu-dataset-metadata.json").write_text(json.dumps({
        "sha": REVISION, "cardData": {"license": "apache-2.0"},
    }))
    gap = tmp_path / "gaps.parquet"
    pq.write_table(pa.Table.from_pylist([
        {"bill_id": "nh42", "state": "NH", "identifier": "HB 42",
         "session_identifier": "2023", "title": "Canonical title",
         "neither_source_observed": True},
        {"bill_id": "il27", "state": "IL", "identifier": "HB 27",
         "session_identifier": "104th", "title": "Prefiled during study window",
         "neither_source_observed": True},
    ]), gap)
    return directory, gap, tmp_path / "packet"


def repin(directory, relative):
    p = directory / "manifest.json"
    manifest = json.loads(p.read_bytes())
    source = directory / relative
    manifest["packet_artifacts"][relative] = {
        "bytes": source.stat().st_size, "sha256": sha256_file(source),
    }
    p.write_text(json.dumps(manifest))


def test_preserves_full_records_alternatives_and_existing_prefiling_identities(corpus_sources):
    source, gap, out = corpus_sources
    recover(source, gap, out)
    rows, contexts, _, manifest = load_corpus(out)
    assert len(rows) == 4 and len(contexts) == 2
    assert rows[0]["source_record"]["text"] == NH
    assert rows[0]["raw_text_sha256"] == hashlib.sha256(NH.encode()).hexdigest()
    assert rows[0]["source_record"]["summary"] == "Source summary, NOT human gold"
    assert {row["source_row_ordinal"] for row in rows} == {0, 1}
    assert rows[2]["session_identifier"] == "104th"
    assert all(all(row[flag] is False for flag in FLAGS) for row in rows)
    assert manifest["counts"]["dispositions"] == {
        "exact_existing_gap_identity": 4, "unresolved_printed_identity_or_body": 2,
    }
    assert len((out / "views.jsonl").read_bytes().split(b"\n")) == 5
    assert (out / "source-data" / SOURCE_FILES["NH"]).read_bytes() == (
        source / SOURCE_FILES["NH"]
    ).read_bytes()


@pytest.mark.parametrize("state,text", [
    ("NH", NH.replace("2023 SESSION", "effective July 1, 2023")),
    ("NH", NH.replace("NEW HAMPSHIRE", "NEW JERSEY")),
    ("NH", NH.replace("Be it Enacted", "Description only")),
    ("NH", NH.replace("2023 SESSION", "2023 SESSION 2024 SESSION")),
    ("IL", IL.replace("State of Illinois", "State of Hawaii")),
])
def test_requires_printed_state_session_identity_and_body_not_title_or_effective_date(state, text):
    assert printed_identity(state, text) is None


@pytest.mark.parametrize("prefix,identifier", [
    ("HR0001 HEE104 00006 HJR 10006 r 1 HOUSE RESOLUTION NO. 1", "HR 1"),
    (
        "104TH GENERAL ASSEMBLY State of Illinois 2025 and 2026 "
        "HOUSE JOINT RESOLUTION CONSTITUTIONAL AMENDMENT HC0002",
        "HJRCA 2",
    ),
])
def test_resolution_written_assembly_and_constitutional_alias_preserve_original_spans(
    prefix, identifier,
):
    text = (
        prefix + " 2 BE IT RESOLVED, BY THE HOUSE OF REPRESENTATIVES OF THE ONE "
        "3 HUNDRED FOURTH GENERAL ASSEMBLY OF THE STATE OF ILLINOIS, that "
        "4 the following policy is resolved."
    )
    identity = printed_identity("IL", text)
    assert identity["session_identifier"] == "104th"
    assert identity["identifier"] == identifier
    assert all(text[item["start"]:item["end"]] == item["text"]
               for item in identity["printed_evidence"])
    assert "3 HUNDRED" in identity["printed_evidence"][1]["text"]
    assert printed_identity("IL", text.replace("HEE104", "HEE103")
                            .replace("104TH GENERAL", "103RD GENERAL")) is None


@pytest.mark.parametrize("defect", [
    "approval", "body", "ordinal", "negative_ordinal", "source_hash", "state", "version_scope",
])
def test_loader_rejects_rebound_but_incompatible_source_records(corpus_sources, defect):
    source, gap, out = corpus_sources
    recover(source, gap, out)
    p = out / "views.jsonl"
    rows = [json.loads(line) for line in p.read_text().split("\n") if line]
    if defect == "approval":
        rows[0]["training_approved"] = True
    elif defect == "body":
        rows[0]["source_record"]["text"] += " silently changed"
    elif defect == "ordinal":
        rows[0]["source_row_ordinal"] = 1
    elif defect == "negative_ordinal":
        rows[0]["source_row_ordinal"] = -3
        rows[0]["view_id"] = rows[0]["view_id"].rsplit(":", 1)[0] + ":-3"
    elif defect == "source_hash":
        rows[1]["source_file_sha256"] = "0" * 64
    elif defect == "state":
        rows[0]["state"] = "IL"
    else:
        rows[0]["source_identity"]["session_identifier"] = "2024"
    p.write_text("".join(json.dumps(row) + "\n" for row in rows))
    repin(out, "views.jsonl")
    with pytest.raises(ValueError, match="incompatible research corpus"):
        load_corpus(out)


def test_rejects_changed_source_and_linked_manifest(corpus_sources):
    source, gap, out = corpus_sources
    p = source / SOURCE_FILES["NH"]
    original = p.read_bytes()
    p.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="advertised complete source"):
        recover(source, gap, out)
    assert not out.exists()
    p.write_bytes(original)
    recover(source, gap, out)
    manifest = out / "manifest.json"
    target = out.parent / "linked-manifest.json"
    manifest.rename(target)
    manifest.symlink_to(target)
    with pytest.raises(ValueError, match="linked manifest"):
        load_corpus(out)


def test_wrong_current_cohort_identity_is_not_admitted(corpus_sources):
    source, gap, out = corpus_sources
    recover(source, gap, out)
    current = pq.read_table(gap).to_pylist()
    current[0]["session_identifier"] = "2024"
    with pytest.raises(ValueError, match="candidate identity"):
        load_corpus(out, current)


@pytest.mark.parametrize("defect", [False, True])
def test_original_keyed_records_restore_removed_metadata_without_arbitrary_deduplication(
    corpus_sources, defect,
):
    source, gap, out = corpus_sources
    current = json.loads((source / SOURCE_FILES["NH"]).read_bytes())
    originals = {
        "000001": {**current[0], "source_file": "HB42.json"},
        "000002": {**current[0], "source_file": "HB42-alternative.json"},
        "unmatched": {**current[2], "source_file": "not-a-body.json"},
    }
    raw = source / ANCESTOR_FILES["NH"]
    raw.write_text(json.dumps(originals))
    (source / "mtsu-original-file-tree.json").write_text(json.dumps([{
        "path": raw.name, "size": raw.stat().st_size, "lfs": {"oid": sha256_file(raw)},
    }]))
    recover(source, gap, out, states=("NH",), source_ancestry=True)
    rows, _, _, manifest = load_corpus(out)
    assert [r["original_dataset_key"] for r in rows[0]["source_ancestry"]] == [
        "000001", "000002",
    ]
    assert rows[0]["source_ancestry"][1]["original_fields"] == {
        "source_file": "HB42-alternative.json",
    }
    assert rows[1]["source_ancestry"] == []
    assert manifest["counts"]["views_with_original_dataset_metadata"] == 1
    assert (out / "source-ancestry" / raw.name).read_bytes() == raw.read_bytes()
    if defect:
        rows[0]["source_ancestry"].pop()
        (out / "views.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
        )
        repin(out, "views.jsonl")
        with pytest.raises(ValueError, match="complete original ancestor"):
            load_corpus(out)


@pytest.mark.parametrize("style", ["browser", "draft", "called", "certification"])
def test_texas_own_session_and_identifier_do_not_come_from_citations_or_suffix_guesses(style):
    context = {"state": "TX", "identifier": "HB 77", "session_identifier": "88",
               "session_name": "88th Legislature (2023)"}
    operative = (
        "BE IT ENACTED BY THE LEGISLATURE OF THE STATE OF TEXAS: "
        "SECTION 1. The board shall publish a complete annual report describing "
        "its findings and shall make that report publicly available to all residents."
    )
    if style == "certification":
        context["identifier"] = "SR 77"
        text = (
            "WHEREAS, The members recognize important public service; "
            "RESOLVED, That the Senate of the 88th Legislature of the State of Texas, "
            "Regular Session, request a complete public report on the program "
            "established by H.B. No. 999. I certify that S.R. No. 77 was adopted."
        )
    else:
        header = {
            "browser": "88(R) HB 77-Introduced version-Bill Text 88R1834 CAE-F H.B. No. 77",
            "draft": "88R1834 CAE-F\n1\nH.B.\n2\nNo.\n77\n",
            "called": "88(3) HB 77-Introduced version-Bill Text 88S30123 AMF-F H.B. No. 77",
        }[style]
        if style == "called":
            context.update(session_identifier="existing-special-namespace",
                           session_name="88th Legislature, 3rd Called Session (2023)")
        text = header + " AN ACT " + operative + " H.B. No. 999 is cited; effective July 1, 2024."
    identity = printed_identity("TX", text, context)
    assert identity["identifier"] == context["identifier"]
    assert identity["session_identifier"] == context["session_identifier"]
    assert all(text[span["start"]:span["end"]] == span["text"]
               for span in identity["printed_evidence"])
    assert printed_identity("TX", text, {**context, "session_name": "2024 Regular Session"}) is None
    assert printed_identity("TX", text.replace("STATE OF TEXAS", "STATE OF MISSISSIPPI")
                            .replace("State of Texas", "State of Mississippi"), context) is None

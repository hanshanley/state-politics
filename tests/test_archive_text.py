import hashlib
import importlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from state_politics.bills import archive_text as archive
from state_politics.provenance import sha256_file

TEXT = (
    "Title: A17\nOfficial Title:\nNumber of Sections: 1\n"
    "Source: versions - Introduced Version\nMedia Type: text/html\n\nSection 1:\n"
    "A17 ASSEMBLY, No. 17 STATE OF NEW JERSEY 221st LEGISLATURE "
    "PRE-FILED FOR INTRODUCTION IN THE 2024 SESSION "
    "Be It Enacted by the Senate and General Assembly of the State of New Jersey: "
    "1. Complete original source.\u2028Another source line.\nFinal source ending."
)


def json_file(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))


def git_tree(tmp_path, contents):
    repo = tmp_path / "git-objects"
    subprocess.run(["git", "init", "--bare", "--quiet", str(repo)], check=True)
    trees = {}
    for name, data in contents.items():
        digest = subprocess.check_output(
            ["git", "--git-dir", str(repo), "hash-object", "-w", "--stdin"], input=data,
        ).strip()
        path = Path(name)
        trees.setdefault(path.parent.as_posix(), {})[path.name] = (b"100644", b"blob", digest)
        for parent in path.parents:
            if parent.as_posix() == ".":
                break
            trees.setdefault(parent.as_posix(), {})
    for directory in sorted(trees, key=lambda p: (len(Path(p).parts), p), reverse=True):
        body = b"".join(mode + b" " + kind + b" " + digest + b"\t" + name.encode() + b"\0"
                        for name, (mode, kind, digest) in trees[directory].items())
        digest = subprocess.check_output(
            ["git", "--git-dir", str(repo), "mktree", "-z"], input=body,
        ).strip()
        if directory == "country:us":
            return digest.decode()
        path = Path(directory)
        trees[path.parent.as_posix()][path.name] = (b"040000", b"tree", digest)


def write_tar(path, contents):
    with tarfile.open(path, "w:gz") as handle:
        for name, body in contents.items():
            member = tarfile.TarInfo("pinned-source/" + name)
            member.mode = 0o644
            member.size = len(body)
            handle.addfile(member, io.BytesIO(body))


@pytest.fixture
def source(tmp_path, monkeypatch):
    base = "country:us/state:nj/sessions/221/bills/A17"
    metadata = {
        "legislative_session": "221", "identifier": "A17", "title": "Source title",
        "jurisdiction": {"id": "ocd-jurisdiction/country:us/state:nj/government"},
        "versions": [{"note": "Introduced Version", "date": "", "links": [{
            "url": "https://example.invalid/17_I1.HTM", "media_type": "text/html",
        }]}],
        "sponsorships": [{"name": "Original source name", "person_id": "~unresolved"}],
        "_processing": {"logs_latest_update": "2025-10-25"},
    }
    contents = {
        base + "/metadata.json": json.dumps(metadata).encode(),
        base + "/files/17_I1_Introduced_Version.HTM": b"<html>Original markup and strike</html>",
        base + "/files/17_I1_Introduced_Version_extracted.txt": TEXT.encode(),
    }
    monkeypatch.setattr(archive, "COUNTRY_TREE", git_tree(tmp_path, contents))
    path = tmp_path / "source.tar.gz"
    write_tar(path, contents)
    queue = tmp_path / "gap.parquet"
    pq.write_table(pa.Table.from_pylist([{
        "bill_id": "nj17", "state": "NJ", "identifier": "A 17",
        "session_identifier": "221", "title": "Canonical title",
        "neither_source_observed": True, "unknown_native_count": None,
    }]), queue)
    return path, queue, tmp_path / "packet", contents


def repin(out, name):
    p = out / "manifest.json"
    m = json.loads(p.read_bytes())
    m["packet_artifacts"][name] = {
        "bytes": (out / name).stat().st_size, "sha256": sha256_file(out / name),
    }
    json_file(p, m)


@pytest.mark.parametrize(("schema", "module", "loader"), [
    ("state-politics.nj-library-text.v1", "nj_library_text", "load_nj_library"),
    ("state-politics.nj-library-collection-text.v1", "nj_library_collection", "load_nj_collection"),
    ("state-politics.billcam-retained-html.v1", "billcam_text", "load_billcam"),
    ("state-politics.published-ai-corpus-text.v1", "published_corpus_text", "load"),
    (
        "state-politics.ok-retained-context-text.v1",
        "ok_retained_context_text", "load_ok_retained_context",
    ),
])
def test_archive_packet_routes_to_its_strict_loader_without_changing_metadata(
    tmp_path, monkeypatch, schema, module, loader,
):
    library = importlib.import_module(f"state_politics.bills.{module}")

    json_file(tmp_path / "manifest.json", {"schema": schema})
    metadata = {"unchanged_original_context": None}
    expected = (
        ["complete reader view"], ["complete context"], {"raw": "pin"}, {"source": "library"},
    )
    calls = []

    def load(directory, original_metadata):
        calls.append((directory, original_metadata))
        return expected

    monkeypatch.setattr(library, loader, load)
    assert archive.load_archive(tmp_path, metadata) is expected
    assert calls == [(tmp_path, metadata)] and calls[0][1] is metadata


def test_full_archive_records_markup_bindings_and_original_gap_values_are_preserved(source):
    path, queue, out, _ = source
    archive.recover(path, queue, out)
    rows, contexts, _, manifest = archive.load_archive(out)
    assert len(rows) == len(contexts) == 1
    assert rows[0]["text"] == TEXT
    assert rows[0]["raw_text_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
    assert rows[0]["source_record"]["_processing"] == {"logs_latest_update": "2025-10-25"}
    assert rows[0]["source_record"]["sponsorships"][0]["person_id"] == "~unresolved"
    assert rows[0]["source_members"]["html"]["bytes"] > 0
    assert contexts[0]["unknown_native_count"] is None
    assert all(rows[0][flag] is False for flag in archive.FLAGS)
    assert (out / "source_archive.tar.gz").read_bytes() == path.read_bytes()
    assert manifest["counts"]["country_git_tree_verified"] is True


@pytest.mark.parametrize("defect", ["text", "source_record", "approval", "disposition"])
def test_rebound_but_incompatible_exports_and_missingness_fail_closed(source, defect):
    path, queue, out, _ = source
    archive.recover(path, queue, out)
    if defect == "approval":
        p = out / "manifest.json"
        m = json.loads(p.read_bytes())
        m["approvals"]["training_approved"] = True
        json_file(p, m)
    elif defect == "disposition":
        p = out / "candidate_dispositions.parquet"
        rows = pq.read_table(p).to_pylist()
        rows[0]["archive_gap_status"] = "fabricated_complete"
        pq.write_table(pa.Table.from_pylist(rows), p)
        repin(out, p.name)
    else:
        p = out / "views.jsonl"
        row = json.loads(p.read_text())
        if defect == "text":
            row["text"] += " silently changed"
        else:
            row["source_record"]["_processing"]["logs_latest_update"] = "2024-01-01"
        p.write_text(json.dumps(row) + "\n")
        repin(out, p.name)
    with pytest.raises(ValueError, match="incompatible independent archive"):
        archive.load_archive(out)


@pytest.mark.parametrize("changed", [
    TEXT.replace("221st", "220th"), TEXT.replace("ASSEMBLY, No. 17", "ASSEMBLY, No. 18"),
    TEXT.replace("STATE OF NEW JERSEY", "STATE OF NEW YORK"),
])
def test_identity_requires_own_printed_state_session_number_not_machine_wrapper(changed):
    assert archive.printed_identity(changed, "A 17") is None


@pytest.mark.parametrize("header", [
    "0ASSEMBLY, No. 17", "ASSEMBLY, Nos. 17, 18 and 19",
])
def test_actual_stray_digit_and_combined_substitute_headers_keep_all_original_evidence(header):
    text = TEXT.replace("ASSEMBLY, No. 17", header)
    identity = archive.printed_identity(text, "A 17")
    assert identity["identifier"] == "A 17"
    assert all(text[item["start"]:item["end"]] == item["text"]
               for item in identity["printed_evidence"])
    wrong = text.replace(header, "ASSEMBLY, No. 18") + " ASSEMBLY, No. 17 is cited."
    assert archive.printed_identity(wrong, "A 17") is None


def test_partial_or_injected_archive_cannot_become_a_completed_source_census(source):
    path, queue, out, contents = source
    changed = dict(contents)
    changed.pop(next(name for name in contents if name.endswith(".HTM")))
    write_tar(path, changed)
    with pytest.raises(ValueError, match="pinned complete Git data tree"):
        archive.recover(path, queue, out)
    assert not out.exists()
    write_tar(path, {**contents, "country:us/../../outside": b"not an allowed source"})
    with pytest.raises(ValueError, match="unsafe archive path"):
        archive.recover(path, queue, out)


def test_linked_manifest_is_rejected_before_reading(source):
    path, queue, out, _ = source
    archive.recover(path, queue, out)
    manifest = out / "manifest.json"
    target = out.parent / "original-manifest.json"
    manifest.rename(target)
    manifest.symlink_to(target)
    with pytest.raises(ValueError, match="linked or missing"):
        archive.load_archive(out)

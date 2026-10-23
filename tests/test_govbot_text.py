import base64
import copy
import hashlib
import json
import runpy
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

import fitz
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from state_politics.bills import govbot_text as archive
from state_politics.bills.archive_text import load_archive


def header(kind="SJ", number=1, year="2025"):
    long = "SENATE JOINT RESOLUTION" if kind == "SJ" else "SENATE RESOLUTION"
    return (
        f"69th Legislature {year}\nLC 1.1\n- 1 -\n1\n{long} NO. {number}\n"
        "2\nINTRODUCED BY A. MEMBER\n"
        "5\nA RESOLUTION OF THE STATE OF\n6\nMONTANA ABOUT COMPLETE RULES.\n"
        "7\nNOW, THEREFORE, BE IT RESOLVED BY THE SENATE:\n"
        "8\nThe complete rules shall apply.\n"
    )


def pdf_bytes(text, year="2025", last_page=None):
    with fitz.open() as document:
        document.new_page().insert_text((50, 50), text, fontsize=10)
        tail = (f"69th Legislature {year}\nLC 1.1\n"
                "Last complete source page; never omit this passage.")
        document.new_page().insert_text(
            (50, 50), tail if last_page is None else last_page, fontsize=10,
        )
        return document.tobytes()


def tree_response(blobs):
    directories = {"": {}}
    nodes = {}
    for name, raw in blobs.items():
        path = PurePosixPath(name)
        nodes[name] = {
            "path": name, "mode": "100644", "type": "blob",
            "sha": archive._git_hash("blob", raw), "size": len(raw),
        }
        parent = path.parent
        while parent.as_posix() != ".":
            directories.setdefault(parent.as_posix(), {})
            parent = parent.parent
    for name, node in nodes.items():
        path = PurePosixPath(name)
        directories[path.parent.as_posix()][path.name] = node
    for directory in sorted(directories, key=lambda p: (len(p.split("/")), p), reverse=True):
        entries = directories[directory]
        names = sorted(entries, key=lambda n: n.encode() + (
            b"/" if entries[n]["type"] == "tree" else b""
        ))
        raw = b"".join(
            entries[n]["mode"].lstrip("0").encode() + b" " + n.encode()
            + b"\0" + bytes.fromhex(entries[n]["sha"]) for n in names
        )
        digest = archive._git_hash("tree", raw)
        if not directory:
            return {"sha": digest, "truncated": False,
                    "tree": [nodes[name] for name in sorted(nodes)]}
        node = {"path": directory, "mode": "040000", "type": "tree", "sha": digest}
        nodes[directory] = node
        path = PurePosixPath(directory)
        parent = path.parent.as_posix()
        directories["" if parent == "." else parent][path.name] = node


def seal(source):
    archive._write(source / "manifest.json", {
        "schema": archive.SOURCE_SCHEMA, "network_closed": True,
        "source_admission": False, "publication": False,
        "input_gap_queue": archive._binding(source / "input_gap_queue.parquet"),
        "artifacts": {
            p.relative_to(source).as_posix(): archive._binding(p)
            for p in source.rglob("*") if p.is_file() and p.name != "manifest.json"
        },
    })


@pytest.fixture
def make_source(tmp_path):
    def make(*, witness_note=None, duplicate_version=False, last_page=None, truncated_root=False):
        source = tmp_path / "source"
        source.mkdir()
        (source / "raw").mkdir()
        (source / "objects").mkdir()
        contexts = [
            {"bill_id": bill_id, "state": state, "identifier": identifier,
             "session_identifier": session, "title": f"Exact title {identifier}",
             "native_introduction_date": date, "unknown": unknown,
             "neither_source_observed": True}
            for bill_id, state, identifier, session, date, unknown in [
                ("mt-sj1", "MT", "SJ 1", "2025", "2024-12-12", None),
                ("mt-sr1", "MT", "SR 1", "2025", "2024-12-12", False),
                ("nh-hb65", "NH", "HB 65", "2026", "2024-12-20", None),
                ("untouched", "DE", "SB 1", "153", None, None),
            ]
        ]
        queue = pa.Table.from_pylist(contexts).replace_schema_metadata({"test": "full original"})
        pq.write_table(queue, source / "input_gap_queue.parquet")
        ledger, records, proofs, leads, object_names = [], [], [], [], set()

        def capture(state, kind, data, recursive=True):
            endpoint = (f"repos/govbot-data/{state.lower()}-legislation/git/{kind}/"
                        + data["sha"] + ("?recursive=1" if kind == "trees" and recursive else ""))
            ordinal = len(ledger) + 1
            name = f"raw/{ordinal:03}.response"
            raw = json.dumps(data).encode()
            (source / name).write_bytes(b"HTTP/2.0 200 OK\r\nContent-Type: application/json"
                                       b"\r\n\r\n" + raw)
            archive._write((source / name).with_suffix(".json"), data)
            row = {
                "ordinal": ordinal, "endpoint": endpoint, "http_status": 200,
                "gh_returncode": 0, "response": name,
                "response_binding": archive._binding(source / name),
            }
            ledger.append(row)
            return row

        for state, session in [("MT", "2025"), ("NH", "2026")]:
            blobs, bill_records = {}, []
            for context in contexts:
                if context["state"] != state:
                    continue
                identifier = context["identifier"].replace(" ", "")
                base = f"bills/{identifier}"
                offered = []
                documents = (
                    [("SJ0001_1(1).pdf", header()),
                     ("LC2243.pdf", header().replace(
                         "SENATE JOINT RESOLUTION NO. 1",
                         "_____________ JOINT RESOLUTION NO. _____________",
                     )),
                     ("SJ0001_Amendments-in-Context.pdf", header())]
                    if identifier == "SJ1" else
                    [("SR0001_1.pdf", header("SR", year="2024"))]
                    if state == "MT" else [("HB65.html", "2025 SESSION\nHOUSE BILL 65")]
                )
                for index, (note, text) in enumerate(documents):
                    pdf = state == "MT"
                    offered.append({
                        "note": note, "date": "", "classification": "",
                        "links": [{"media_type": "application/pdf" if pdf else "text/html",
                                   "url": f"https://publisher.invalid/{identifier}?document={index}"}],
                    })
                    stem = f"{base}/files/published_{index}"
                    blobs[stem + (".pdf" if pdf else ".html")] = (
                        pdf_bytes(text, "2024" if identifier == "SR1" else "2025", last_page)
                        if pdf else text.encode()
                    )
                    printed_note = witness_note if witness_note and index == 0 else note
                    blobs[stem + "_extracted.txt"] = (
                        "Title: GENERATED TITLE NOT POLICY INPUT\nOfficial Title: \n"
                        f"Source: versions - {printed_note}\n"
                        f"Media Type: {'application/pdf' if pdf else 'text/html'}\n"
                        "Visual Markup Detected: true -- preserve this warning.\n\n"
                        + "=" * 80 + "\n\n" + text
                    ).encode()
                if duplicate_version:
                    offered.append(copy.deepcopy(offered[0]))
                provider = {
                    "identifier": context["identifier"], "title": context["title"],
                    "legislative_session": session,
                    "jurisdiction": {"id": f"ocd-jurisdiction/country:us/state:"
                                          f"{state.lower()}/government"},
                    "versions": offered, "sponsorships": [], "subject": ["not gold"],
                }
                blobs[f"{base}/metadata.json"] = json.dumps(provider).encode()
                bill_records.append((context, provider, base))
            tree = tree_response(blobs)
            root_response = copy.deepcopy(tree)
            if truncated_root and state == "MT":
                root_response["truncated"] = True
                root_response["tree"] = root_response["tree"][:2]
            tree_ref = capture(state, "trees", root_response)
            nodes = {node["path"]: node for node in tree["tree"]}
            branches = []
            if root_response["truncated"]:
                direct = {**tree, "tree": [n for n in tree["tree"] if "/" not in n["path"]]}
                direct_ref = capture(state, "trees", direct, recursive=False)
                bills = {
                    "sha": nodes["bills"]["sha"], "truncated": False,
                    "tree": [{**n, "path": n["path"][6:]} for n in tree["tree"]
                             if n["path"].startswith("bills/") and n["path"].count("/") == 1],
                }
                bills_ref = capture(state, "trees", bills, recursive=False)
                for _, _, base in bill_records:
                    selected = {
                        "sha": nodes[base]["sha"], "truncated": False,
                        "tree": [{**n, "path": n["path"][len(base) + 1:]}
                                 for n in tree["tree"] if n["path"].startswith(base + "/")],
                    }
                    branches.append({
                        "published_bill_directory": {**nodes[base], "path": base[6:]},
                        "direct_session_response": direct_ref,
                        "direct_bill_directories_response": bills_ref,
                        "selected_bill_tree_response": capture(state, "trees", selected),
                        "complete_selected_branch_reconstructed": True,
                    })
            objects = {}
            for name, raw in blobs.items():
                digest = nodes[name]["sha"]
                blob = {"sha": digest, "size": len(raw), "encoding": "base64",
                        "content": base64.b64encode(raw).decode()}
                ref = capture(state, "blobs", blob)
                path = f"objects/{digest}"
                (source / path).write_bytes(raw)
                object_names.add(path)
                objects[name] = {
                    "path": path, "git_blob_sha1": digest, **archive._binding(source / path),
                    "response": ref,
                }
            for context, provider, base in bill_records:
                records.append({
                    "original_target_context": context, "provider_record": provider,
                    "provider_bill_ID_equals_original": False,
                    "source_session_tree": tree["sha"], "source_admission": False,
                    "metadata_node": nodes[f"{base}/metadata.json"],
                    "metadata_object": objects[f"{base}/metadata.json"],
                    "complete_published_bill_files": [
                        {"published_git_path": name, "node": nodes[name],
                         "captured_object": objects[name]}
                        for name in blobs if name.startswith(f"{base}/files/")
                    ],
                })
            proofs.append({
                "state": state, "session_identifier": session, "tree_sha1": tree["sha"],
                "response": tree_ref,
                "structural_tree_reconstructed": not root_response["truncated"],
                "all_selected_branch_membership_verified": True,
                "all_nonselected_blobs_downloaded": False, "targeted_branch_proofs": branches,
            })
            leads.append({
                "state": state, "session_identifier": session,
                "published_session_tree": {"sha": tree["sha"]},
                "original_bill_ids": [r["bill_id"] for r, _, _ in bill_records],
            })
        archive._write_rows(source / "retained-original-bill-records.jsonl", records)
        archive._write_rows(source / "invocation-ledger.jsonl", ledger)
        archive._write(source / "session-tree-proofs.json", proofs)
        archive._write(source / "scope.json", {
            "session_leads": leads, "maximum_new_gh_CLI_invocations": 250,
            "closed_previous_discovery_invocations": 107,
            "maximum_individual_blob_bytes": 50000000,
            "maximum_selected_original_blob_bytes": 500000000,
        })
        archive._write(source / "report.json", {
            "network_closed": True, "source_admissions": 0, "model_calls": 0,
            "publication": False, "native_publisher_requests": 0,
            "new_gh_CLI_invocations": len(ledger), "original_250_allowance_not_reset": True,
            "closed_preceding_capture_invocations": 0,
            "new_invocations_in_this_continuation": len(ledger),
            "closed_prior_discovery_invocations": 107,
            "retained_bill_records": len(records),
            "selected_complete_blob_objects": len(object_names),
            "selected_blob_bytes": sum((source / n).stat().st_size for n in object_names),
        })
        seal(source)
        return source, queue, tmp_path / "normalized"
    return make


def build(source, out):
    return archive.build_govbot(
        source, source / "input_gap_queue.parquet", out,
        source_manifest_sha256=archive._binding(source / "manifest.json")["sha256"],
        gap_queue_sha256=archive._binding(source / "input_gap_queue.parquet")["sha256"],
    )


def repin(out, name):
    manifest = archive._json(out / "manifest.json")
    manifest["packet_artifacts"][name] = archive._binding(out / name)
    archive._write(out / "manifest.json", manifest)


def test_complete_both_readers_original_queue_and_route(make_source):
    source, original, out = make_source()
    before = {p.relative_to(source).as_posix(): archive._binding(p)
              for p in source.rglob("*") if p.is_file()}
    result = build(source, out)
    views, contexts, pins, manifest = load_archive(out, original)
    assert manifest == result
    assert len(views) == 2 and len(contexts) == 1
    assert pq.read_table(out / "context_inventory.parquet").equals(
        original.slice(0, 1), check_metadata=True,
    )
    assert contexts[0]["native_introduction_date"] == "2024-12-12"
    assert contexts[0]["unknown"] is None
    assert {view["reader"] for view in views} == {"pymupdf", "pypdf"}
    assert all(view["n_pages"] == 2 and "\f" in view["text"]
               and "Last complete source page" in view["text"]
               and "GENERATED TITLE" not in view["text"]
               and "Section 1" not in view["text"]
               and view["archive_generated_prologue_preserved"] is False
               and all(view[flag] is False for flag in archive.FLAGS) for view in views)
    assert all(view["source_version"]["version"]["note"] == "SJ0001_1(1).pdf"
               and view["source_version"]["visual_markup_warning_preserved"] for view in views)
    for view in views:
        for span in view["source_identity"]["printed_evidence"]:
            assert view["text"][span["start"]:span["end"]] == span["text"]
    pages = list(archive._rows(out / "reader_pages.jsonl"))
    assert len(pages) == 16
    assert all("words" in page and "blocks" in page
               for page in pages if page["reader"] == "pymupdf")
    assert manifest["counts"]["n_rejected_PDF_documents"] == 3
    assert manifest["counts"]["n_source_version_dispositions"] == 5
    assert {"producer/native_text.py", "producer/govbot_text.py"} <= pins.keys()
    assert before == {p.relative_to(source).as_posix(): archive._binding(p)
                      for p in source.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="new nonoverlapping"):
        build(source, out)


@pytest.mark.parametrize("mutation", [
    "malformed_prefix", "citation", "wrong_year", "blank_formal", "wrong_number",
])
def test_own_header_not_citation_draft_or_another_year(mutation):
    text = header()
    if mutation == "malformed_prefix":
        text = "Malformed provider prefix\n" + text
    elif mutation == "citation":
        text = text.replace("SENATE JOINT RESOLUTION NO. 1", "SENATE RESOLUTION NO. 1")
        text += "\nSENATE JOINT RESOLUTION NO. 1\n"
    elif mutation == "wrong_year":
        text = text.replace("Legislature 2025", "Legislature 2024")
    elif mutation == "blank_formal":
        text = text.replace("SENATE JOINT RESOLUTION NO. 1",
                            "_____________ JOINT RESOLUTION NO. _____________")
    else:
        text = text.replace("RESOLUTION NO. 1", "RESOLUTION NO. 10")
    context = {"state": "MT", "identifier": "SJ 1", "session_identifier": "2025"}
    assert archive.printed_identity(text, context) is None
    assert archive.printed_identity(header(), context) is not None


def test_literal_hyphenated_venue_and_trailing_line_number_not_LC_alias():
    text = header().replace("Legislature 2025", "Legislature  - 2025")
    text = text.replace("RESOLUTION NO. 1\n", "RESOLUTION NO. 1 1\n")
    context = {"state": "MT", "identifier": "SJ 1", "session_identifier": "2025"}
    identity = archive.printed_identity(text, context)
    assert identity is not None
    for span in identity["printed_evidence"]:
        assert text[span["start"]:span["end"]] == span["text"]
    assert archive.printed_identity(
        text.replace("RESOLUTION NO. 1 1", "RESOLUTION NO. 11"), context,
    ) is None


@pytest.mark.parametrize("mode", ["wrong_note", "duplicate_version"])
def test_exact_unique_note_witness_is_required(make_source, mode):
    source, _, out = make_source(
        witness_note="SJ0001_11.pdf" if mode == "wrong_note" else None,
        duplicate_version=mode == "duplicate_version",
    )
    build(source, out)
    assert archive.load_govbot(out)[0] == []


@pytest.mark.parametrize("name", [
    "views.jsonl", "reader_pages.jsonl", "version_dispositions.jsonl",
    "context_inventory.parquet",
])
def test_repinned_derived_text_lost_page_version_and_original_date_fail(make_source, name):
    source, _, out = make_source()
    build(source, out)
    if name.endswith(".parquet"):
        table = pq.read_table(out / name)
        rows = table.to_pylist()
        rows[0]["native_introduction_date"] = "2025-01-01"
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), out / name)
    else:
        rows = list(archive._rows(out / name))
        if name == "views.jsonl":
            rows[0]["text"] = rows[0]["text"][:100]
            rows[0]["raw_text_characters"] = len(rows[0]["text"])
            rows[0]["raw_text_sha256"] = hashlib.sha256(rows[0]["text"].encode()).hexdigest()
        else:
            rows.pop()
        archive._write_rows(out / name, rows)
    repin(out, name)
    with pytest.raises(ValueError, match="replay mismatch"):
        archive.load_govbot(out)


@pytest.mark.parametrize("mutation", ["file_loss", "metadata", "wrong_tree", "wrong_blob"])
def test_repinned_source_still_requires_tree_blob_metadata_and_full_files(make_source, mutation):
    source, _, _ = make_source()
    records = list(archive._rows(source / "retained-original-bill-records.jsonl"))
    if mutation == "file_loss":
        records[0]["complete_published_bill_files"].pop()
    elif mutation == "metadata":
        records[0]["provider_record"]["title"] = "Unbound substituted title"
    elif mutation == "wrong_tree":
        records[0]["source_session_tree"] = "0" * 40
    else:
        item = records[0]["complete_published_bill_files"][0]
        path = source / item["captured_object"]["path"]
        raw = path.read_bytes()
        path.write_bytes(b"!" + raw[1:])
    archive._write_rows(source / "retained-original-bill-records.jsonl", records)
    seal(source)
    with pytest.raises(ValueError, match="inventory mismatch|conflict|binding mismatch"):
        archive._source(source, archive._binding(source / "manifest.json")["sha256"])


@pytest.mark.parametrize("last_page", [
    "", "69th Legislature 2024\nWrong session on final page",
    "69th Legislature 2025\nSJ 2.1\nWrong bill header on final page",
])
def test_blank_or_wrong_year_final_page_is_preserved_but_not_admitted(make_source, last_page):
    source, _, out = make_source(last_page=last_page)
    build(source, out)
    assert archive.load_govbot(out)[0] == []
    assert len(list(archive._rows(out / "reader_pages.jsonl"))) == 16
    assert any(row["disposition"] == "blank_or_conflicting_complete_reader_page"
               for row in archive._rows(out / "document_dispositions.jsonl"))


def test_PDF_reader_failure_is_not_swallowed(make_source, monkeypatch):
    source, _, out = make_source()

    def fail(*args):
        raise ValueError("reader failure is not a successful extraction")

    monkeypatch.setattr(archive.native_text, "extract_pdf", fail)
    with pytest.raises(ValueError, match="reader failure"):
        build(source, out)
    assert not (out / "manifest.json").exists()


def test_graph_consumer_archives_new_schema_and_both_producers(make_source):
    source, _, out = make_source()
    build(source, out)
    graph = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/recreate_graphs.py"))
    inputs = {}
    files = graph["recovery_packet"](out.parent, out.name, inputs, archive=True)
    assert {
        "producer/govbot_text.py", "producer/native_text.py", "reader_pages.jsonl",
    } <= files.keys()
    target = out.parent / "graph-download.zip"
    graph["archive_packet"](files, target)
    with zipfile.ZipFile(target) as bundle:
        assert set(bundle.namelist()) == set(archive._tree(out))
        assert bundle.read("views.jsonl") == (out / "views.jsonl").read_bytes()


def test_truncated_root_requires_exact_complete_selected_branch_membership(make_source):
    source, _, out = make_source(truncated_root=True)
    build(source, out)
    assert len(archive.load_govbot(out)[0]) == 2
    proofs = archive._json(source / "session-tree-proofs.json")
    proofs[0]["targeted_branch_proofs"][0]["published_bill_directory"]["sha"] = "0" * 40
    archive._write(source / "session-tree-proofs.json", proofs)
    seal(source)
    with pytest.raises(ValueError, match="not a member"):
        archive._source(source, archive._binding(source / "manifest.json")["sha256"])


def test_fresh_process_build_and_verify_do_not_bind_import_warnings_to_first_PDF(make_source):
    source, _, out = make_source()
    module = [sys.executable, "-m", "state_politics.bills.govbot_text"]
    pins = [
        "--source-manifest-sha256", archive._binding(source / "manifest.json")["sha256"],
        "--gap-queue-sha256", archive._binding(source / "input_gap_queue.parquet")["sha256"],
    ]
    for command in [
        [*module, "build", "--source-dir", str(source),
         "--gap-queue", str(source / "input_gap_queue.parquet"), "--out-dir", str(out), *pins],
        [*module, "verify", "--directory", str(out), *pins],
    ]:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["n_recovered_contexts"] == 1


def test_current_metadata_shapes_preserve_dates_nulls_types_and_unique_ids(make_source):
    source, original, out = make_source()
    build(source, out)
    rows = original.to_pylist()
    for metadata in [rows, original, {row["bill_id"]: row for row in rows}]:
        assert archive.load_govbot(out, metadata)[1] == rows[:1]
    for field, replacement in [("native_introduction_date", "2025-01-01"),
                               ("unknown", ""), ("unknown", False)]:
        changed = copy.deepcopy(rows)
        changed[0][field] = replacement
        with pytest.raises(ValueError, match="missingness/type changed"):
            archive.load_govbot(out, changed)
    with pytest.raises(ValueError, match="missing or duplicated"):
        archive.load_govbot(out, [*rows, rows[0]])
    with pytest.raises(ValueError, match="anchor changed"):
        archive.load_govbot(out, source_manifest_sha256="0" * 64)
    with pytest.raises(ValueError, match="anchor changed"):
        archive.load_govbot(out, gap_queue_sha256="0" * 64)


def test_duplicate_json_keys_unsafe_paths_and_structural_tree_reject():
    with pytest.raises(ValueError, match="duplicate JSON key"):
        archive._decode('{"a": 1, "a": 2}')
    for name in ["../objects/x", "/objects/x", "objects//x", "objects\\x"]:
        with pytest.raises(ValueError, match="path"):
            archive._relative(name)
    data = tree_response({"bills/SJ1/metadata.json": b"metadata"})
    archive._git_tree(data, True)
    data["tree"][-1]["sha"] = "0" * 40
    with pytest.raises(ValueError, match="tree reconstruction mismatch"):
        archive._git_tree(data, True)

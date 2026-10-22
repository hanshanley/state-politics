"""Recover exact remaining bill identities from independently published research text."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from state_politics.provenance import sha256_file

SCHEMA = "state-politics.research-corpus-text.v1"
REVISION = "d4f15948c8af7733df9aa70ce68b14a65dec3d82"
ANCESTOR_REVISION = "9411b4690c3ba8c0c28ab19eb9370316908c00af"
DATASET = (
    "MTSUs-Fall-2025-Software-Engineering-Pr/"
    "United_States_State_Legislation_with_Summaries"
)
SOURCE_FILES = {
    "NH": "reordered_cleaned_data_NH.json",
    "IL": "reordered_cleaned_data_IL.json",
}
ANCESTOR_FILES = {"NH": "cleaned_bills_NH.json", "IL": "cleaned_data_IL.json"}
FLAGS = (
    "scientific_approval", "model_input_approved", "training_approved",
    "publication_approved", "party_attribution_approved", "filing_time_text_certified",
    "analytical_admission", "publisher_original_verified",
)
BODY_CLAUSE = re.compile(
    r"\b(?:Be\s+it\s+enacted|Resolved,?\s+by|Resolved\s+that|BE\s+IT\s+RESOLVED)\b", re.I,
)


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible research corpus: {message}")


def _illinois_resolution(text):
    # Resolutions print the assembly in the resolving clause, with page line numbers.
    space = r"(?:\s+\d+)?\s+"
    words = [
        "RESOLVED,?", "BY", "THE", r"(?:HOUSE" + space + "OF" + space
        + r"REPRESENTATIVES|SENATE)", "OF", "THE", "ONE", "HUNDRED",
        r"(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH)",
        "GENERAL", "ASSEMBLY", "OF", "THE", "STATE", "OF", "ILLINOIS",
    ]
    venue = re.search(r"\b" + space.join(words) + r"\b", text, re.I)
    if venue is None:
        return None
    sessions = {
        "FIRST": "101st", "SECOND": "102nd", "THIRD": "103rd", "FOURTH": "104th",
        "FIFTH": "105th", "SIXTH": "106th", "SEVENTH": "107th", "EIGHTH": "108th",
        "NINTH": "109th",
    }
    session = sessions[venue[1].upper()]
    number = re.match(r"\s*(HR|SR|HJR|SJR)\s*0*(\d+)\b", text, re.I)
    if number:
        identifier = f"{number[1].upper()} {int(number[2])}"
        draft = re.match(r"\s*(?:HR|SR|HJR|SJR)\s*\d+\s+(?:LRB|HEE)(\d{3})\b",
                         text, re.I)
        if draft and draft[1] != session[:-2]:
            return None
    else:
        number = re.match(
            r"\s*(\d+(?:ST|ND|RD|TH))\s+GENERAL\s+ASSEMBLY\s+"
            r"State\s+of\s+Illinois\s+\d{4}\s+and\s+\d{4}\s+"
            r"(HOUSE|SENATE)\s+JOINT\s+RESOLUTION\s+CONSTITUTIONAL\s+AMENDMENT\s+"
            r"(HC|SC)\s*0*(\d+)\b", text[:1200], re.I,
        )
        if not number or number[1].lower() != session:
            return None
        chamber = number[2].upper()
        if number[3].upper() != ("HC" if chamber == "HOUSE" else "SC"):
            return None
        identifier = f"{'HJRCA' if chamber == 'HOUSE' else 'SJRCA'} {int(number[4])}"
    return session, identifier, [number, venue]


def printed_identity(state: str, text: str) -> dict | None:
    """Use printed identity/session/state, never titles or effective-date guesses."""
    head = text[:1200]
    if state == "NH":
        number = re.match(r"\s*(HB|SB|HCR|SCR|HR|SR|CACR)\s+(\d+)(?:\b|-)", head, re.I)
        years = list(re.finditer(r"\b((?:19|20)\d{2})\s+SESSION\b", head, re.I))
        venue = re.search(r"\bSTATE\s+OF\s+NEW\s+HAMPSHIRE\b", text, re.I)
        if not number or not years or len({m[1] for m in years}) != 1 or not venue:
            return None
        session = years[0][1]
        identifier = f"{number[1].upper()} {int(number[2])}"
        matches = [number, years[0], venue]
    elif state == "IL":
        header = re.match(
            r"\s*(\d+(?:ST|ND|RD|TH))\s+GENERAL\s+ASSEMBLY\s+"
            r"State\s+of\s+Illinois\s+(\d{4})\s+and\s+(\d{4})\s+"
            r"(HJRCA|SJRCA|HJR|SJR|HB|SB|HR|SR)\s*0*(\d+)", head, re.I,
        )
        if header:
            session = header[1].lower()
            identifier = f"{header[4].upper()} {int(header[5])}"
            matches = [header]
        else:
            resolution = _illinois_resolution(text)
            if resolution is None:
                return None
            session, identifier, matches = resolution
    else:
        raise ValueError(f"unsupported research corpus state: {state}")
    clause = BODY_CLAUSE.search(text)
    if not clause:
        return None
    return {
        "state": state, "session_identifier": session, "identifier": identifier,
        "printed_evidence": [
            {"start": match.start(), "end": match.end(), "text": match[0]}
            for match in [*matches, clause]
        ],
    }


def _json(path):
    return json.loads(path.read_bytes())


def _binding(path):
    return {"bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def _signature(record):
    return tuple(record.get(field) for field in ("title", "summary", "text"))


def _ancestor_index(name, digest, originals):
    require(isinstance(originals, dict), "ancestor must preserve its original keyed object")
    index = defaultdict(list)
    for key, record in originals.items():
        require(isinstance(record, dict) and all(
            field in record and (record[field] is None or isinstance(record[field], str))
            for field in ("title", "summary", "text")
        ), "incomplete original ancestor record")
        index[_signature(record)].append({
            "dataset_revision": ANCESTOR_REVISION, "source_file": name,
            "source_file_sha256": digest, "original_dataset_key": key,
            "original_fields": {k: v for k, v in record.items()
                                if k not in ("title", "summary", "text")},
            "key_semantics": "original_dataset_key_not_interpreted_as_an_external_identifier",
        })
    return index


def _ancestry(source_dir, out, states, bindings):
    tree_name = "mtsu-original-file-tree.json"
    tree = {row["path"]: row for row in _json(source_dir / tree_name)}
    target = out / "source-ancestry"
    target.mkdir()
    shutil.copy2(source_dir / tree_name, target / tree_name)
    indexes = {}
    for state in states:
        name = ANCESTOR_FILES[state]
        require(bindings[str(source_dir / name)] == {
            "bytes": tree[name]["size"], "sha256": tree[name]["lfs"]["oid"],
        }, f"advertised complete ancestor bytes/hash: {name}")
        shutil.copy2(source_dir / name, target / name)
        indexes[state] = _ancestor_index(
            name, tree[name]["lfs"]["oid"], _json(source_dir / name),
        )
    return indexes


def recover(
    source_dir: Path, gap_queue: Path, out: Path, *, states=("NH", "IL"),
    source_ancestry=False,
):
    require(bool(states) and len(set(states)) == len(states)
            and set(states) <= SOURCE_FILES.keys(), "unsupported or duplicate source profiles")
    source_dir, gap_queue, out = map(lambda p: p.absolute(), (source_dir, gap_queue, out))
    require(not out.exists(), "output must not already exist")
    require(out.resolve() == out and source_dir.resolve() == source_dir,
            "linked source/output directory")
    require(not out.is_relative_to(source_dir) and not source_dir.is_relative_to(out),
            "output overlaps source directory")
    paths = [gap_queue, source_dir / "mtsu-dataset-metadata.json",
             source_dir / "mtsu-file-tree.json"]
    paths += [source_dir / SOURCE_FILES[state] for state in states]
    if source_ancestry:
        paths += [source_dir / "mtsu-original-file-tree.json"]
        paths += [source_dir / ANCESTOR_FILES[state] for state in states]
    require(all(p.is_file() and p.resolve() == p for p in paths), "linked or missing input")
    metadata = _json(source_dir / "mtsu-dataset-metadata.json")
    require(metadata["sha"] == REVISION and metadata["cardData"]["license"] == "apache-2.0",
            "pinned dataset revision/license")
    tree = {row["path"]: row for row in _json(source_dir / "mtsu-file-tree.json")}
    table = pq.read_table(gap_queue)
    candidates = table.to_pylist()
    require(len({r["bill_id"] for r in candidates}) == len(candidates), "duplicate bill ID")
    require(all(r["neither_source_observed"] is True for r in candidates),
            "only the explicit existing missing-text queue may be recovered")
    index = defaultdict(list)
    for row in candidates:
        index[row["state"], row["session_identifier"], row["identifier"]].append(row)
    before = {str(p): _binding(p) for p in paths}
    for state in states:
        name = SOURCE_FILES[state]
        require(before[str(source_dir / name)] == {
            "bytes": tree[name]["size"], "sha256": tree[name]["lfs"]["oid"],
        }, f"advertised complete source bytes/hash: {name}")
    out.mkdir(parents=True)
    (out / "source-data").mkdir()
    (out / "producer").mkdir()
    shutil.copy2(gap_queue, out / "input_gap_queue.parquet")
    for name in ("mtsu-dataset-metadata.json", "mtsu-file-tree.json"):
        shutil.copy2(source_dir / name, out / name)
    shutil.copy2(Path(__file__), out / "producer/research_corpus_text.py")
    ancestors = _ancestry(source_dir, out, states, before) if source_ancestry else {}
    views, dispositions, counts = [], [], Counter()
    by_bill = Counter()
    for state in states:
        name = SOURCE_FILES[state]
        shutil.copy2(source_dir / name, out / "source-data" / name)
        records = _json(source_dir / name)
        require(isinstance(records, list), "source must remain an original JSON array")
        for ordinal, record in enumerate(records):
            require(isinstance(record, dict), f"non-object source row {name}:{ordinal}")
            text = record.get("text")
            require(text is None or isinstance(text, str), f"non-string body {name}:{ordinal}")
            identity = printed_identity(state, text or "")
            matches = (
                index.get((state, identity["session_identifier"], identity["identifier"]), [])
                if identity else []
            )
            disposition = (
                "unresolved_printed_identity_or_body" if identity is None
                else "not_remaining_candidate" if not matches
                else "ambiguous_remaining_identity" if len(matches) != 1
                else "exact_existing_gap_identity"
            )
            counts[disposition] += 1
            dispositions.append({
                "source_file": name, "source_row_ordinal": ordinal, "state": state,
                "disposition": disposition,
                "printed_session": identity["session_identifier"] if identity else None,
                "printed_identifier": identity["identifier"] if identity else None,
            })
            if disposition != "exact_existing_gap_identity":
                continue
            context = matches[0]
            by_bill[context["bill_id"]] += 1
            views.append({
                "view_id": f"research-corpus:{REVISION}:{name}:{ordinal}",
                "source_type": "research_corpus_text", "bill_id": context["bill_id"],
                "state": state, "identifier": context["identifier"],
                "session_identifier": context["session_identifier"], "title": context["title"],
                "source_file": name, "source_file_sha256": tree[name]["lfs"]["oid"],
                "source_row_ordinal": ordinal, "source_record": record,
                "source_identity": identity, "raw_text_characters": len(text),
                "raw_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "dataset": DATASET, "dataset_revision": REVISION,
                "dataset_license_observation": "apache-2.0",
                "source_status": "third_party_cleaned_text_not_publisher_version_certification",
                "training_admission": False, "source_date_or_party_inferred": False,
                **dict.fromkeys(FLAGS, False),
            })
            if source_ancestry:
                views[-1]["source_ancestry"] = ancestors[state].get(_signature(record), [])
    require(bool(views), "no exact remaining identities with complete source bodies recovered")
    with (out / "views.jsonl").open("w") as handle:
        for row in views:
            handle.write(json.dumps(
                row, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ) + "\n")
    recovered = table.filter(pa.array([row["bill_id"] in by_bill for row in candidates]))
    recovered = recovered.append_column(
        "research_corpus_text_views",
        pa.array([by_bill[row["bill_id"]] for row in recovered.to_pylist()], type=pa.int64()),
    )
    pq.write_table(recovered, out / "context_inventory.parquet")
    pq.write_table(pa.Table.from_pylist(dispositions), out / "source_row_dispositions.parquet")
    report = {
        "source_rows": len(dispositions), "dispositions": dict(counts),
        "text_views": len(views), "newly_covered_contexts": len(by_bill),
        "states": {
            state: {
                "newly_covered_contexts": sum(
                    row["state"] == state for row in recovered.to_pylist()
                ), "text_views": sum(row["state"] == state for row in views),
            } for state in states
        },
        "limitation": (
            "Cleaned third-party source, not verified publisher-original or filing-time text; "
            "summaries are source fields, never human gold or model predictions."
        ),
        "approvals": dict.fromkeys(FLAGS, False),
    }
    if source_ancestry:
        report["original_dataset_records_preserved"] = sum(
            len(references) for index in ancestors.values() for references in index.values()
        )
        report["views_with_original_dataset_metadata"] = sum(
            bool(row["source_ancestry"]) for row in views
        )
        report["original_dataset_record_references"] = sum(
            len(row["source_ancestry"]) for row in views
        )
    _write_json(out / "report.json", report)
    require(all(_binding(p) == before[str(p)] for p in paths), "input changed during recovery")
    manifest = {
        "schema": SCHEMA, "status": "header_joined_research_text_not_scientific_certification",
        "dataset": DATASET, "revision": REVISION, "approvals": dict.fromkeys(FLAGS, False),
        "input_bindings": before, "counts": report,
        "packet_artifacts": {
            p.relative_to(out).as_posix(): _binding(p) for p in sorted(out.rglob("*"))
            if p.is_file()
        },
    }
    if source_ancestry:
        manifest["source_ancestry_revision"] = ANCESTOR_REVISION
    _write_json(out / "manifest.json", manifest)
    return manifest


def load_corpus(directory: Path, metadata=None):
    directory = directory.absolute()
    require(directory.resolve() == directory, "linked packet directory")
    path = directory / "manifest.json"
    require(path.is_file() and path.resolve() == path, "missing or linked manifest")
    manifest = _json(path)
    require(manifest["schema"] == SCHEMA and manifest["revision"] == REVISION,
            "packet schema/revision")
    require(all(manifest["approvals"].get(flag) is False for flag in FLAGS),
            "all approvals must remain false")
    require({
        "views.jsonl", "context_inventory.parquet", "input_gap_queue.parquet",
        "source_row_dispositions.parquet", "report.json",
    } <= manifest["packet_artifacts"].keys(), "missing complete packet tables")
    pins = {"manifest.json": sha256_file(path)}
    for name, binding in manifest["packet_artifacts"].items():
        p = directory / name
        require(not Path(name).is_absolute() and ".." not in Path(name).parts
                and p.is_file() and p.resolve() == p, "unsafe or linked packet artifact")
        require(_binding(p) == binding, f"artifact mismatch: {name}")
        pins[name] = binding["sha256"]
    rows = [json.loads(line) for line in (directory / "views.jsonl").read_text().split("\n")
            if line]
    contexts = pq.read_table(directory / "context_inventory.parquet").to_pylist()
    gap_rows = pq.read_table(directory / "input_gap_queue.parquet").to_pylist()
    original_gap = {row["bill_id"]: row for row in gap_rows}
    by_bill = {row["bill_id"]: row for row in contexts}
    require(len(by_bill) == len(contexts), "duplicate recovered context")
    require(all(
        key in original_gap and all(row[field] == value
                                   for field, value in original_gap[key].items())
        for key, row in by_bill.items()
    ), "original missing-context fields changed")
    current = {row["bill_id"]: row for row in metadata} if metadata is not None else by_bill
    require(set(by_bill) <= current.keys(), "unknown existing candidate")
    require(len({row["view_id"] for row in rows}) == len(rows), "duplicate source view")
    by_file = defaultdict(list)
    observed = Counter()
    for row in rows:
        text = row["source_record"]["text"]
        context = by_bill.get(row["bill_id"])
        require(context is not None and original_gap[row["bill_id"]]["neither_source_observed"]
                is True, "source outside original missing-text queue")
        require(all(row.get(flag) is False for flag in FLAGS)
                and row["training_admission"] is False
                and row["source_date_or_party_inferred"] is False, "source approvals")
        require(row["source_type"] == "research_corpus_text"
                and row["dataset"] == DATASET and row["dataset_revision"] == REVISION
                and row["state"] in SOURCE_FILES
                and SOURCE_FILES[row["state"]] == row["source_file"]
                and row["view_id"] == (
                    f"research-corpus:{REVISION}:{row['source_file']}:{row['source_row_ordinal']}"
                ), "source dataset/file/view identity")
        require(all(row[field] == context[field] == current[row["bill_id"]][field]
                    for field in ("state", "identifier", "session_identifier")),
                "candidate identity mismatch")
        identity = printed_identity(row["state"], text)
        require(identity == row["source_identity"]
                and all(identity[field] == row[field]
                        for field in ("state", "identifier", "session_identifier")),
                "printed source identity mismatch")
        require(len(text) == row["raw_text_characters"]
                and hashlib.sha256(text.encode()).hexdigest() == row["raw_text_sha256"],
                "complete source text mismatch")
        by_file[row["source_file"]].append(row)
        observed[row["bill_id"]] += 1
    for name, records in by_file.items():
        require(name in SOURCE_FILES.values(), "unknown source file")
        source = directory / "source-data" / name
        require(f"source-data/{name}" in pins, "unbound original source file")
        originals = _json(source)
        digest = sha256_file(source)
        require(all(digest == row["source_file_sha256"] for row in records),
                "original source file binding")
        require(all(type(row["source_row_ordinal"]) is int
                    and 0 <= row["source_row_ordinal"] < len(originals) for row in records),
                "invalid original source ordinal")
        require(all(originals[row["source_row_ordinal"]] == row["source_record"]
                    for row in records),
                "source record altered or bound to wrong original ordinal")
    has_ancestry = "source_ancestry_revision" in manifest
    require(all(("source_ancestry" in row) == has_ancestry for row in rows),
            "unbound or missing original-source ancestry")
    if has_ancestry:
        require(manifest["source_ancestry_revision"] == ANCESTOR_REVISION,
                "original-source revision")
        for state in {row["state"] for row in rows}:
            name = ANCESTOR_FILES[state]
            path = directory / "source-ancestry" / name
            require(f"source-ancestry/{name}" in pins, "unbound ancestor source")
            index = _ancestor_index(name, sha256_file(path), _json(path))
            for row in (item for item in rows if item["state"] == state):
                require(row["source_ancestry"] == index.get(_signature(row["source_record"]), []),
                        "complete original ancestor record binding")
    require(set(observed) == set(by_bill)
            and all(observed[key] == row["research_corpus_text_views"]
                    for key, row in by_bill.items()), "recovered context/view counts")
    require(len(rows) == manifest["counts"]["text_views"]
            and len(contexts) == manifest["counts"]["newly_covered_contexts"], "packet counts")
    return rows, contexts, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--gap-queue", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--states", nargs="+", choices=sorted(SOURCE_FILES), default=["NH", "IL"])
    parser.add_argument(
        "--source-ancestry", action="store_true",
        help="Include pinned original keyed records and source filenames removed by later cleaning",
    )
    args = parser.parse_args(argv)
    manifest = recover(
        args.source_dir, args.gap_queue, args.out_dir, states=tuple(args.states),
        source_ancestry=args.source_ancestry,
    )
    load_corpus(args.out_dir)
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

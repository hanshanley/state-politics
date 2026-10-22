"""Recover exact existing candidates from a pinned independent government-record archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tarfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from state_politics.provenance import sha256_file

SCHEMA = "state-politics.independent-archive-text.v1"
COMMIT = "c99d1624d45dd8bc0b282a6469e19ee28e112097"
COUNTRY_TREE = "4b57fb6de51433a6673c1e68443eb79e7d28be49"
PROVIDER = "windy-civi-pipelines/nj-data-pipeline"
FLAGS = (
    "scientific_approval", "model_input_approved", "training_approved",
    "publication_approved", "party_attribution_approved", "filing_time_text_certified",
    "analytical_admission", "publisher_original_verified",
)
KINDS = {
    "A": "ASSEMBLY", "S": "SENATE", "AR": "ASSEMBLY RESOLUTION",
    "SR": "SENATE RESOLUTION", "ACR": "ASSEMBLY CONCURRENT RESOLUTION",
    "SCR": "SENATE CONCURRENT RESOLUTION", "AJR": "ASSEMBLY JOINT RESOLUTION",
    "SJR": "SENATE JOINT RESOLUTION",
}


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible independent archive: {message}")


def _binding(path):
    return {"bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _json(path):
    return json.loads(path.read_bytes())


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def _git_hash(kind, content):
    return hashlib.sha1(
        kind.encode() + b" " + str(len(content)).encode() + b"\0" + content,
    ).digest()


def _identifier(value):
    match = re.fullmatch(r"([A-Z]+)\s*0*(\d+)", value)
    return f"{match[1]} {int(match[2])}" if match and match[1] in KINDS else None


def printed_identity(text, identifier, *, version=2):
    section = re.search(r"(?m)^Section 1:\s*\n", text)
    if section is None:
        return None
    start = section.end()
    head = text[start:start + 3000]
    kind, number = identifier.split()
    if kind not in KINDS:
        return None
    compact = re.match(r"\s*" + re.escape(kind) + r"\s*0*" + number + r"\b", head)
    venue = re.search(r"\bSTATE\s+OF\s+NEW\s+JERSEY\s+221st\s+LEGISLATURE\b", head, re.I)
    label = r"\s+".join(KINDS[kind].split())
    if version == 1:
        own = re.search(r"\b" + label + r",?\s+No\.?\s*0*" + number + r"\b", head, re.I)
    else:
        require(version == 2, "unsupported printed-identity profile")
        own = re.search(
            r"(?<![A-Za-z])" + label + r",?\s+Nos?\.?\s*"
            r"(?P<numbers>\d+\b(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+)\d+\b)*)",
            head, re.I,
        )
        if own and int(number) not in {int(value) for value in re.findall(r"\d+", own["numbers"])}:
            own = None
    if not compact or not venue or not own:
        return None
    return {
        "state": "NJ", "session_identifier": "221", "identifier": identifier,
        "policy_section_start": start, "archive_extractor_prologue_preserved": True,
        "printed_evidence": [
            {"start": start + match.start(), "end": start + match.end(), "text": match[0]}
            for match in (compact, venue, own)
        ],
    }


def _country_digest(nodes):
    for directory in sorted(
        nodes, key=lambda value: (len(PurePosixPath(value).parts), value), reverse=True,
    ):
        entries = nodes[directory]
        names = sorted(entries, key=lambda name: name.encode() + (
            b"/" if entries[name][0] == b"40000" else b""
        ))
        content = b"".join(
            mode + b" " + name.encode() + b"\0" + digest
            for name in names for mode, digest in [entries[name]]
        )
        digest = _git_hash("tree", content)
        if directory == "country:us":
            return digest.hex()
        path = PurePosixPath(directory)
        nodes[path.parent.as_posix()][path.name] = (b"40000", digest)
    raise ValueError("independent archive has no complete country tree")


def scan_archive(archive_path, candidates, *, identity_version=2):
    targets = defaultdict(list)
    for row in candidates:
        if row["state"] == "NJ" and row["session_identifier"] == "221":
            targets[row["identifier"]].append(row)
    require(bool(targets), "no existing unresolved target session")
    nodes = defaultdict(dict)
    metadata, texts, sources, inventory = {}, [], {}, []
    total_bytes = members = 0
    archive_root = None
    with tarfile.open(archive_path, "r|gz") as archive:
        for ordinal, member in enumerate(archive):
            members += 1
            require(members <= 250000, "archive member ceiling")
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and ".." not in path.parts, "unsafe archive path")
            archive_root = archive_root or path.parts[0]
            require(path.parts[0] == archive_root, "multiple archive roots")
            if member.isdir():
                continue
            require(member.isfile() and 0 <= member.size <= 100000000,
                    "linked, special or oversized archive member")
            total_bytes += member.size
            require(total_bytes <= 3000000000, "uncompressed byte ceiling")
            content = archive.extractfile(member).read()
            require(len(content) == member.size, "incomplete archive member")
            relative = PurePosixPath(*path.parts[1:])
            if not relative.parts or relative.parts[0] != "country:us":
                continue
            digest = _git_hash("blob", content)
            mode = b"100755" if member.mode & 0o111 else b"100644"
            parent = relative.parent.as_posix()
            require(relative.name not in nodes[parent], "duplicate archive member")
            nodes[parent][relative.name] = (mode, digest)
            while parent != "country:us":
                parent = PurePosixPath(parent).parent.as_posix()
                nodes[parent]
            binding = {
                "archive_member": member.name, "archive_ordinal": ordinal,
                "bytes": member.size, "sha256": hashlib.sha256(content).hexdigest(),
                "git_blob_sha1": digest.hex(),
            }
            inventory.append(binding)
            parts = relative.parts
            if len(parts) < 7 or parts[:5] != (
                "country:us", "state:nj", "sessions", "221", "bills",
            ):
                continue
            identifier = _identifier(parts[5])
            if identifier not in targets:
                continue
            if len(parts) == 7 and relative.name == "metadata.json":
                record = json.loads(content)
                require(record["legislative_session"] == "221"
                        and _identifier(record["identifier"]) == identifier
                        and record["jurisdiction"]["id"] == (
                            "ocd-jurisdiction/country:us/state:nj/government"
                        ), "archived metadata state/session/bill conflict")
                metadata[identifier] = (record, binding)
            elif len(parts) == 8 and parts[6] == "files":
                sources[relative.as_posix()] = binding
                if relative.suffix.lower() == ".txt":
                    texts.append((identifier, content.decode("utf-8"), binding, relative))
    tree = _country_digest(nodes)
    require(tree == COUNTRY_TREE, "archive does not reconstruct the pinned complete Git data tree")
    views, dispositions = [], []
    counts = Counter()
    for identifier, text, binding, relative in texts:
        identity = printed_identity(text, identifier, version=identity_version)
        note = re.search(r"(?m)^Source:\s*versions\s*-\s*(.+?)\s*$", text)
        html_name = relative.name.removesuffix("_extracted.txt") + ".HTM"
        html = sources.get((relative.parent / html_name).as_posix())
        record, metadata_binding = metadata.get(identifier, (None, None))
        versions = []
        if record and note and html:
            for version in record["versions"]:
                if version["note"] != note[1]:
                    continue
                for link in version["links"]:
                    original = PurePosixPath(unquote(urlsplit(link["url"]).path))
                    if (link["media_type"] == "text/html"
                            and html_name.startswith(original.stem + "_")
                            and original.suffix.lower() == ".htm"):
                        versions.append({"version": version, "link": link})
        matches = targets[identifier]
        reason = (
            "ambiguous_existing_identity" if len(matches) != 1
            else "missing_archived_metadata" if record is None
            else "unresolved_printed_own_identity" if identity is None
            else "no_unique_archived_version_source" if len(versions) != 1
            else "exact_existing_gap_identity"
        )
        dispositions.append({
            **binding, "identifier": identifier, "disposition": reason,
        })
        counts[reason] += 1
        if reason != "exact_existing_gap_identity":
            continue
        context = matches[0]
        views.append({
            "view_id": f"archive:{COMMIT}:{relative.as_posix()}",
            "source_type": "archive_text", "bill_id": context["bill_id"], "state": "NJ",
            "identifier": identifier, "session_identifier": "221", "title": context["title"],
            "text": text, "raw_text_characters": len(text),
            "raw_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_record": record, "source_identity": identity,
            "source_version": versions[0],
            "source_members": {"text": binding, "html": html, "metadata": metadata_binding},
            "archive_provider": PROVIDER, "archive_commit": COMMIT,
            "archive_country_git_tree": tree,
            "source_status": "independent_mirror_and_extraction_not_publisher_certified",
            "archive_generated_prologue_preserved": True,
            "source_date_or_party_inferred": False, "training_admission": False,
            **dict.fromkeys(FLAGS, False),
        })
    coverage = Counter(row["bill_id"] for row in views)
    candidate_dispositions = []
    for candidates_for_key in targets.values():
        for context in candidates_for_key:
            identifier = context["identifier"]
            candidate_dispositions.append({
                **context, "archive_text_views": coverage[context["bill_id"]],
                "archive_gap_status": (
                    "matching_archived_version_text" if coverage[context["bill_id"]]
                    else "missing_archived_metadata" if identifier not in metadata
                    else "no_compatible_archived_version_text"
                ),
            })
    return views, candidate_dispositions, dispositions, inventory, {
        "archive_members": members, "uncompressed_file_bytes": total_bytes,
        "country_git_tree": tree, "country_git_tree_verified": True,
        "archived_target_metadata": len(metadata), "target_text_sources": len(texts),
        "source_dispositions": dict(counts), "text_views": len(views),
        "newly_covered_contexts": len(coverage),
    }


def recover(archive_path: Path, gap_queue: Path, out: Path):
    archive_path, gap_queue, out = (
        path.absolute() for path in (archive_path, gap_queue, out)
    )
    require(not out.exists() and out.resolve() == out, "new unlinked output required")
    require(all(path.is_file() and path.resolve() == path for path in (archive_path, gap_queue)),
            "missing or linked original inputs")
    inputs = {str(path): _binding(path) for path in (archive_path, gap_queue)}
    table = pq.read_table(gap_queue)
    contexts = table.to_pylist()
    require(len({r["bill_id"] for r in contexts}) == len(contexts)
            and all(r["neither_source_observed"] is True for r in contexts),
            "exact original remaining-text queue required")
    views, gaps, dispositions, inventory, counts = scan_archive(archive_path, contexts)
    require(bool(views), "no compatible substantive archived source views")
    out.mkdir(parents=True)
    (out / "producer").mkdir()
    shutil.copy2(archive_path, out / "source_archive.tar.gz")
    shutil.copy2(gap_queue, out / "input_gap_queue.parquet")
    shutil.copy2(Path(__file__), out / "producer/archive_text.py")
    with (out / "views.jsonl").open("w") as handle:
        for row in views:
            handle.write(json.dumps(
                row, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ) + "\n")
    accepted = {r["bill_id"] for r in views}
    pq.write_table(table.filter(pa.array([
        row["bill_id"] in accepted for row in contexts
    ])), out / "context_inventory.parquet")
    for name, rows in (
        ("candidate_dispositions", gaps), ("source_view_dispositions", dispositions),
        ("archive_inventory", inventory),
    ):
        pq.write_table(pa.Table.from_pylist(rows), out / f"{name}.parquet")
    report = {
        **counts, "approvals": dict.fromkeys(FLAGS, False),
        "source_kind": "independent_archived_government_records",
        "license_observation": (
            "No standalone legacy-repository data license observed. Government bill records "
            "are retained for local research; no redistribution, publisher or version approval."
        ),
        "limitation": (
            "Complete archived extraction includes its existing machine prologue; this is not "
            "an introduced-version/markup/filing-time certification. Raw HTML remains in the "
            "complete pinned archive; processing timestamps and sponsor names infer no date/party."
        ),
    }
    _write(out / "report.json", report)
    require(all(_binding(Path(path)) == value for path, value in inputs.items()),
            "original input changed during recovery")
    manifest = {
        "schema": SCHEMA, "provider": PROVIDER, "source_commit": COMMIT,
        "identity_profile_version": 2,
        "country_git_tree": COUNTRY_TREE, "approvals": dict.fromkeys(FLAGS, False),
        "input_bindings": inputs, "counts": counts,
        "packet_artifacts": {
            path.relative_to(out).as_posix(): _binding(path)
            for path in sorted(out.rglob("*")) if path.is_file()
        },
    }
    _write(out / "manifest.json", manifest)
    return manifest


def load_archive(directory: Path, metadata=None):
    directory = directory.absolute()
    path = directory / "manifest.json"
    require(directory.resolve() == directory and path.is_file() and path.resolve() == path,
            "linked or missing packet/manifest")
    manifest = _json(path)
    if manifest.get("schema") == "state-politics.lawatlas-archive-text.v1":
        from state_politics.bills.lawatlas_text import load_lawatlas

        return load_lawatlas(directory, metadata)
    if manifest.get("schema") == "state-politics.maryland-archive-text.v1":
        from state_politics.bills.maryland_archive_text import load_maryland

        return load_maryland(directory, metadata)
    require(manifest["schema"] == SCHEMA and manifest["provider"] == PROVIDER
            and manifest["source_commit"] == COMMIT
            and manifest["country_git_tree"] == COUNTRY_TREE, "pinned archive source/schema")
    require(all(manifest["approvals"].get(flag) is False for flag in FLAGS), "source approvals")
    artifacts = manifest["packet_artifacts"]
    require({
        "source_archive.tar.gz", "input_gap_queue.parquet", "views.jsonl",
        "context_inventory.parquet", "candidate_dispositions.parquet",
        "source_view_dispositions.parquet", "archive_inventory.parquet", "report.json",
    } <= artifacts.keys(), "incomplete original source packet")
    pins = {"manifest.json": sha256_file(path)}
    for name, binding in artifacts.items():
        target = directory / name
        require(not Path(name).is_absolute() and ".." not in Path(name).parts
                and target.is_file() and target.resolve() == target,
                "unsafe or missing source artifact")
        require(_binding(target) == binding, f"source artifact mismatch: {name}")
        pins[name] = binding["sha256"]
    gap = pq.read_table(directory / "input_gap_queue.parquet").to_pylist()
    original = {row["bill_id"]: row for row in gap}
    require(len(original) == len(gap) and all(r["neither_source_observed"] is True for r in gap),
            "original source gap queue")
    replay, dispositions, sources, inventory, counts = scan_archive(
        directory / "source_archive.tar.gz", gap,
        identity_version=manifest.get("identity_profile_version", 1),
    )
    rows = [json.loads(line) for line in (directory / "views.jsonl").read_text().split("\n")
            if line]
    require(rows == replay and counts == manifest["counts"], "complete archive replay mismatch")
    contexts = pq.read_table(directory / "context_inventory.parquet").to_pylist()
    require(len({r["bill_id"] for r in contexts}) == len(contexts)
            and {r["bill_id"] for r in contexts} == {r["bill_id"] for r in rows}
            and all(row == original[row["bill_id"]] for row in contexts),
            "original recovered contexts changed")
    if metadata is not None:
        current = {row["bill_id"]: row for row in metadata}
        require(all(
            row["bill_id"] in current and all(
                row[key] == current[row["bill_id"]][key]
                for key in ("state", "identifier", "session_identifier")
            ) for row in contexts
        ), "current candidate identity mismatch")
    for name, expected in (
        ("candidate_dispositions", dispositions), ("source_view_dispositions", sources),
        ("archive_inventory", inventory),
    ):
        require(pq.read_table(directory / f"{name}.parquet").to_pylist() == expected,
                "complete source/disposition inventory mismatch")
    return rows, contexts, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--gap-queue", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = recover(args.archive, args.gap_queue, args.out_dir)
    load_archive(args.out_dir)
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

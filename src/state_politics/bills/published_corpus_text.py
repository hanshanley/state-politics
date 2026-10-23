"""Replay a sealed independently published CSV without importing its AI annotations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

import pyarrow as pa
import pyarrow.parquet as pq

from state_politics.bills import billcam_text, maryland_archive_text
from state_politics.platforms import registry
from state_politics.provenance import sha256_file

SCHEMA = "state-politics.published-ai-corpus-text.v1"
SOURCE_SCHEMA = "state-politics.independent-ai-corpus-source.v1"
RECORD_URL = "https://zenodo.org/records/20781731"
DATASET_URL = RECORD_URL + "/files/Final_Database_10.csv?download=1"
CSV_MEMBER = "raw/03-published-complete-dataset.body"
FLAGS = (
    "scientific_approval", "model_input_approved", "training_approved",
    "publication_approved", "party_attribution_approved", "filing_time_text_certified",
    "analytical_admission", "publisher_original_verified",
)
PRODUCERS = {
    "published_corpus_text.py": Path(__file__),
    "billcam_text.py": Path(billcam_text.__file__),
    "maryland_archive_text.py": Path(maryland_archive_text.__file__),
    "registry.py": Path(registry.__file__),
}
PRODUCTS = {
    "views.jsonl", "context_inventory.parquet", "input_gap_queue.parquet",
    "source_row_dispositions.jsonl", "candidate_dispositions.jsonl", "report.json",
    "source_inventory.json", "source_immutability.json",
} | {"producer/" + name for name in PRODUCERS}
SUPPORTED = frozenset((
    "CT", "HI", "IN", "KS", "MD", "MI", "MS", "NE", "OK", "RI", "UT", "VA", "WV",
))
STATUS = "independently_published_cleaned_text_not_original_or_filing_time_certification"
SEALED_PRODUCERS = {
    "114e8fdc585a52d469a0df1469a19e5b78f788aa9163dbdb3c1d0d47df951cd2": {
        "sha256": "f7707aad97b53ba0022e740fedeb9002cc03b09bf0e6f38f3e04081afa6a0681",
        "bytes": 28378,
    },
}
PROLOGUE = re.compile(
    r"\A(?:19|20)\d{2}[ \t]+([A-Z]{2})[ \t]+([A-Z]+[ \t]+\d+)\r?\n"
    r"Author:[^\r\n]*\r?\nVersion:[^\r\n]*\r?\n"
    r"Version Date:[ \t]*\d{2}/\d{2}/\d{4}[ \t]*\r?\n"
)
BODY = re.compile(
    r"\b(?:BE\s+IT\s+ENACTED|THE\s+PEOPLE\s+OF\s+THE\s+STATE\s+OF\s+MICHIGAN\s+ENACT"
    r"|IT\s+IS\s+ENACTED|BE\s+IT\s+RESOLVED)\b", re.I,
)


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible published corpus: {message}")


def _same(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False,
    )


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _binding(path):
    require(path.is_file() and path.resolve() == path, f"missing or linked file: {path}")
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def _tree(root):
    require(root.is_dir() and root.resolve() == root, "missing or linked packet directory")
    paths = list(root.rglob("*"))
    require(all(not path.is_symlink() for path in paths), "linked packet member")
    return {path.relative_to(root).as_posix() for path in paths if path.is_file()}


def _json(path):
    return json.loads(path.read_bytes())


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def _write_rows(path, rows):
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def _relative(name):
    require(type(name) is str and bool(name), "typed nonempty member name")
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts
            and path.as_posix() == name and "\\" not in name, "unsafe member path")


def _hash(value):
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value),
            "explicit SHA-256 anchor required")
    return value


def _identifier(value):
    match = re.fullmatch(r"([A-Z]+)[ \t]+0*(\d+)", value)
    if not match:
        return None
    kind = {"H": "HB", "S": "SB", "L": "LB", "A": "AB"}.get(match[1], match[1])
    return f"{kind} {int(match[2])}"


def _body_start(record, state, identifier):
    text = record["Bill_Text"]
    match = PROLOGUE.match(text)
    if match:
        if match[1] != state or _identifier(match[2]) != identifier:
            return None
        return match.end()
    if re.match(r"\A(?:19|20)\d{2}[ \t]+[A-Z]{2}[ \t]+", text):
        return None
    return 0


def _span(match):
    return {"start": match.start(), "end": match.end(), "text": match[0]}


def printed_identity(text, context):
    """Use only a body's own typed header, formal venue and bill-facing session evidence."""
    state = context["state"]
    if state not in SUPPORTED:
        return None
    if state == "HI":
        result = billcam_text.printed_identity(text, context)
        years = set(re.findall(
            r"THIRTY-SECOND\s+LEGISLATURE,\s*(2023|2024)\b", text[:2000],
        ))
        return result if result and len(years) == 1 else None
    if state == "MD":
        observation = maryland_archive_text._printed(
            text, context["identifier"], context["session_identifier"], prologue=False,
        )
        if observation["disposition"] != "exact_existing_gap_identity" or not BODY.search(text):
            return None
        return {
            "state": state, "identifier": context["identifier"],
            "session_identifier": context["session_identifier"],
            "printed_evidence": [
                {"start": span["character_start"], "end": span["character_end"],
                 "text": span["text"]}
                for span in observation["identity_spans"]
            ],
            "session_evidence_limit": observation["session_evidence_limit"],
        }
    body = BODY.search(text)
    if not body:
        return None
    head = text[:min(2000, body.start())]
    if state == "CT":
        own = re.search(r"\b(House|Senate)\s+Bill\s+No\.\s*(\d+)\b", head, re.I)
        sessions = list(re.finditer(r"\b(?:January|February)\s+Session,\s*(20\d{2})\b",
                                   head, re.I))
        venue = re.search(r"\bSTATE\s+OF\s+CONNECTICUT\b", head, re.I)
    elif state == "IN":
        own = re.search(
            r"\b(HOUSE|SENATE)\s+(?:BILL|ENROLLED\s+ACT)\s+No\.\s*(\d+)\b", head, re.I,
        )
        sessions = list(re.finditer(
            r"\b(?:First|Second)\s+Regular\s+Session\s+of\s+the\s+\d+(?:st|nd|rd|th)"
            r"\s+General\s+Assembly\s+\((20\d{2})\)", head, re.I,
        ))
        venue = re.search(r"\bGeneral\s+Assembly\s+of\s+the\s+State\s+of\s+Indiana\b",
                          text, re.I)
    elif state == "KS":
        own = re.search(r"\b(HOUSE|SENATE)\s+BILL\s+No\.\s*(\d+)\b", head, re.I)
        sessions = list(re.finditer(r"\bSession\s+of\s+(20\d{2})\b", head, re.I))
        venue = re.search(r"\bLegislature\s+of\s+the\s+State\s+of\s+Kansas\b", text, re.I)
    elif state == "MI":
        own = re.search(r"\b(HOUSE|SENATE)\s+BILL\s+NO\.\s*(\d+)\b", head, re.I)
        sessions = list(re.finditer(r"\bREGULAR\s+SESSION\s+OF\s+(20\d{2})\b", head, re.I))
        if not sessions:
            sessions = list(re.finditer(
                r"\A[HS]B-\d+,\s+As\s+Passed\s+(?:House|Senate),\s+[A-Za-z]+"
                r"\s+\d{1,2},\s+(20\d{2})\b", head, re.I,
            ))
        venue = re.search(r"\b(?:THE\s+PEOPLE\s+OF\s+THE\s+)?STATE\s+OF\s+MICHIGAN\b",
                          text, re.I)
    elif state == "MS":
        own = re.search(r"\b(House|Senate)\s+Bill\s+(\d+)\b", head, re.I)
        sessions = list(re.finditer(r"\b(20\d{2})\s+Regular\s+Session\b", head, re.I))
        venue = re.search(r"\bMISSISSIPPI\s+LEGISLATURE\b", head, re.I)
    elif state == "NE":
        own = re.search(r"\bLEGISLATIVE\s+(BILL|RESOLUTION)\s+(\d+)\b", head, re.I)
        sessions = list(re.finditer(r"\bONE\s+HUNDRED\s+(EIGHTH|NINTH)\s+LEGISLATURE\b",
                                   head, re.I))
        venue = re.search(
            r"\b(?:Be\s+it\s+enacted\s+by\s+the\s+people\s+of\s+the\s+State\s+of"
            r"|BE\s+IT\s+RESOLVED\s+BY\s+THE\s+MEMBERS\s+OF\s+THE\s+ONE\s+HUNDRED"
            r"\s+(?:EIGHTH|NINTH)\s+LEGISLATURE\s+OF)\s+NEBRASKA\b", text, re.I,
        )
    elif state == "OK":
        own = re.search(r"(?m)^(HOUSE|SENATE)\s+BILL\s+(\d+)\b", head, re.I)
        sessions = list(re.finditer(
            r"\b(?:1st|2nd)\s+Session\s+of\s+the\s+59th\s+Legislature\s+\((2023|2024)\)",
            head, re.I,
        ))
        venue = re.search(r"\bSTATE\s+OF\s+OKLAHOMA\b", head, re.I)
    elif state == "RI":
        own = re.match(r"\s*\d{4}\s+--\s+([HS])\s+(\d+)\b", head, re.I)
        sessions = list(re.finditer(r"\bJANUARY\s+SESSION,\s+A\.D\.\s+(20\d{2})\b",
                                   head, re.I))
        venue = re.search(r"\bSTATE\s+OF\s+RHODE\s+ISLAND\b", head, re.I)
    elif state == "UT":
        own = re.match(r"\s*([HS])\.B\.\s*(\d+)\b", head, re.I)
        sessions = list(re.finditer(r"\b(20\d{2})\s+GENERAL\s+SESSION\b", head, re.I))
        venue = re.search(r"\bSTATE\s+OF\s+UTAH\b", head, re.I)
    elif state == "VA":
        own = re.match(r"\s*(HOUSE|SENATE)\s+BILL\s+NO\.\s*(\d+)\b", head, re.I)
        sessions = list(re.finditer(
            r"(?m)^Offered\s+[A-Za-z]+\s+\d{1,2},\s+(20\d{2})\b", head, re.I,
        ))
        venue = re.search(r"\bGeneral\s+Assembly\s+of\s+Virginia\b", text, re.I)
    else:
        own = re.search(r"\b(House|Senate)\s+Bill\s+(\d+)\b", head, re.I)
        sessions = list(re.finditer(r"\b(20\d{2})\s+REGULAR\s+SESSION\b", head, re.I))
        venue = re.search(r"\bWEST\s+VIRGINIA\s+LEGISLATURE\b", head, re.I)
    if not own or not venue or not sessions:
        return None
    if own.start() >= body.start() or any(match.start() >= body.start() for match in sessions):
        return None
    if state == "NE":
        kind = "LB" if own[1].upper() == "BILL" else "LR"
        values = {{"EIGHTH": "108", "NINTH": "109"}[m[1].upper()] for m in sessions}
    else:
        kind = "HB" if own[1].upper() in ("HOUSE", "H") else "SB"
        values = {m[1] for m in sessions}
    identifier = f"{kind} {int(own[2])}"
    session = context["session_identifier"]
    allowed = {"2023", "2024"} if state in ("KS", "MI") and session == "2023-2024" else {session}
    if identifier != context["identifier"] or len(values) != 1 or not values <= allowed:
        return None
    if state == "RI" and re.match(r"\s*(\d{4})", head)[1] not in values:
        return None
    return {
        "state": state, "identifier": identifier, "session_identifier": session,
        "printed_session_observations": sorted(values),
        "printed_evidence": [_span(match) for match in (own, venue, *sessions, body)],
        "session_evidence_limit": (
            "Own bill-facing printed session, introduced/edition year or literal legislature "
            "within unchanged original session; no filing date, introduced-version or alias."
        ),
    }


def _source(source, source_sha):
    require(_binding(source / "manifest.json")["sha256"] == _hash(source_sha),
            "caller-pinned source manifest changed")
    manifest = _json(source / "manifest.json")
    require(manifest["schema"] == SOURCE_SCHEMA and manifest["network_closed"] is True
            and manifest["source_admission"] is False and manifest["publication"] is False,
            "closed unapproved source packet required")
    files = manifest["artifacts"]
    require(type(files) is dict and _tree(source) == set(files) | {"manifest.json"},
            "source inventory omissions or extra members")
    for name, value in files.items():
        _relative(name)
        require(_same(_binding(source / name), value), f"source artifact changed: {name}")
    report, inventory = _json(source / "report.json"), _json(source / "dataset-inventory.json")
    require(report["network_closed"] is True and report["error"] is None
            and report["source_admissions"] == 0 and report["classifier_calls"] == 0
            and report["human_gold"] is False and report["publication"] is False,
            "incomplete or promoted source capture")
    response = inventory["dataset_response"]
    require(response["url"] == DATASET_URL and response["body"] == CSV_MEMBER
            and response["http_status"] == 200 and response["curl_returncode"] == 0
            and _same(response["body_binding"], _binding(source / CSV_MEMBER)),
            "published exact dataset response")
    with (source / CSV_MEMBER).open("rb") as stream:
        md5 = hashlib.file_digest(stream, "md5").hexdigest()
    require(md5 == inventory["advertised_md5"] == inventory["actual_md5"],
            "published checksum mismatch")
    return manifest, inventory


def _replay(source, queue_path, source_sha, queue_sha, *, legacy_observation_name=False):
    _, inventory = _source(source, source_sha)
    require(_binding(queue_path)["sha256"] == _hash(queue_sha), "original gap queue changed")
    table = pq.read_table(queue_path)
    originals = table.to_pylist()
    require(len({r["bill_id"] for r in originals}) == len(originals)
            and all(r["neither_source_observed"] is True for r in originals),
            "only distinct original missing-text contexts permitted")
    index = defaultdict(list)
    for row in originals:
        index[row["state"], row["identifier"]].append(row)
    views, dispositions, counts = [], [], Counter()
    csv_sha = _binding(source / CSV_MEMBER)["sha256"]
    previous_limit = csv.field_size_limit(32000000)
    try:
        with (source / CSV_MEMBER).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            require(reader.fieldnames == inventory["original_fieldnames"],
                    "complete original CSV fieldnames")
            for ordinal, record in enumerate(reader, 1):
                require(None not in record and all(type(v) is str for v in record.values()),
                        "malformed or incomplete original CSV record")
                state = registry.STATE_NAMES.get(record["Jurisdiction"])
                identifier = _identifier(record["Bill_Number"])
                hits = index.get((state, identifier), [])
                start = _body_start(record, state, identifier) if hits else None
                matches = []
                if start is not None and state in SUPPORTED:
                    text = record["Bill_Text"][start:]
                    matches = [
                        (row, identity) for row in hits
                        if (identity := printed_identity(text, row)) is not None
                    ]
                disposition = (
                    "outside_original_fifty_state_population" if state is None
                    else "unparsed_provider_identifier_no_suffix_or_alias_guessed" if not identifier
                    else "no_original_state_typed_number_gap" if not hits
                    else "outside_reviewed_printed_identity_profiles" if state not in SUPPORTED
                    else "unrecognized_or_conflicting_provider_prologue" if start is None
                    else "unresolved_or_conflicting_own_printed_identity_session_or_body"
                    if not matches
                    else "ambiguous_original_context" if len(matches) != 1
                    else "exact_original_gap_own_printed_identity"
                )
                entry = {
                    "source_record_ordinal": ordinal, "source_csv_sha256": csv_sha,
                    "source_state": record["Jurisdiction"],
                    "source_identifier": record["Bill_Number"],
                    "source_Year_not_session_authority": record["Year"],
                    "source_Version_Date_not_filing_authority": record["Version_Date"],
                    "source_record_sha256": _digest(json.dumps(
                        record, ensure_ascii=False, sort_keys=True, allow_nan=False,
                    )),
                    "candidate_original_bill_ids": [row["bill_id"] for row in hits],
                    "disposition": disposition,
                }
                if disposition == "exact_original_gap_own_printed_identity":
                    context, identity = matches[0]
                    view_id = f"published-ai-corpus:{csv_sha}:{ordinal}"
                    views.append({
                        "view_id": view_id, "source_type": "published_corpus_text",
                        **{key: context[key] for key in (
                            "bill_id", "state", "identifier", "session_identifier", "title",
                        )},
                        "dataset_url": DATASET_URL, "source_csv_sha256": csv_sha,
                        "source_record_ordinal": ordinal, "source_record": record,
                        "original_target_context": context, "source_identity": identity,
                        "text": text, "raw_text_sha256": _digest(text),
                        "raw_text_characters": len(text),
                        "full_published_Bill_Text_sha256": _digest(record["Bill_Text"]),
                        "native_body_source_span": [start, len(record["Bill_Text"])],
                        "publisher_prologue": record["Bill_Text"][:start],
                        "publisher_prologue_not_used_as_own_identity": True,
                        "archive_generated_prologue_preserved": False,
                        "source_status": STATUS,
                        ("source_cleaning_not_reversed_or_native_edition_certified"
                         if legacy_observation_name
                         else "source_cleaning_and_native_edition_uncertainty_preserved"): True,
                        "AI_extracts_summaries_scores_and_parties_not_used": True,
                        "training_admission": False, "source_date_or_party_inferred": False,
                        **dict.fromkeys(FLAGS, False),
                    })
                    counts[context["bill_id"]] += 1
                    entry.update(bill_id=context["bill_id"], view_id=view_id)
                dispositions.append(entry)
    finally:
        csv.field_size_limit(previous_limit)
    require(len(dispositions) == inventory["n_complete_csv_records"],
            "complete published CSV population")
    require(bool(views), "no supported exact original gaps recovered")
    contexts = table.filter(pa.array([r["bill_id"] in counts for r in originals]))
    candidate_dispositions = [
        {"bill_id": row["bill_id"], "state": row["state"],
         "identifier": row["identifier"], "session_identifier": row["session_identifier"],
         "n_retained_source_views": counts.get(row["bill_id"], 0),
         "disposition": "retained_published_body" if row["bill_id"] in counts
         else "still_unavailable_from_this_independent_publication"}
        for row in originals
    ]
    report = {
        "status": STATUS, "source_manifest_sha256": source_sha,
        "original_gap_queue_sha256": queue_sha,
        "all_original_fields_nulls_and_contexts_preserved": True,
        "all_source_records_fields_duplicates_and_negatives_preserved": True,
        "counts": {
            "original_gap_contexts": len(originals), "n_source_rows": len(dispositions),
            "n_recovered_contexts": len(counts), "n_retained_views": len(views),
            "full_retained_policy_characters": sum(len(v["text"]) for v in views),
            "remaining_unavailable_from_this_source": len(originals) - len(counts),
            "by_state": dict(sorted(Counter(v["state"] for v in views).items())),
            "source_dispositions": dict(sorted(
                Counter(r["disposition"] for r in dispositions).items(),
            )),
        },
        "source_Year_derived_from_version_date_not_used_as_session_identity": True,
        "source_AI_outputs_not_gold_training_or_inference_inputs": True,
        "native_fullness_originality_dates_parties_and_rights_not_certified": True,
        "approval_flags": dict.fromkeys(FLAGS, False),
        "new_network_requests": 0, "encoder_calls": 0, "publication": False,
    }
    return {
        "views.jsonl": views, "source_row_dispositions.jsonl": dispositions,
        "candidate_dispositions.jsonl": candidate_dispositions,
    }, contexts, report


def build(source_directory, gap_queue, out_directory, *, source_manifest_sha256, gap_queue_sha256):
    source, queue = Path(source_directory).absolute(), Path(gap_queue).absolute()
    out = Path(out_directory).absolute()
    require(not out.exists() and out.resolve() == out
            and not out.is_relative_to(source) and not source.is_relative_to(out)
            and not queue.is_relative_to(out), "new nonoverlapping output required")
    source_manifest, _ = _source(source, source_manifest_sha256)
    source_names = set(source_manifest["artifacts"]) | {"manifest.json"}
    before = {name: _binding(source / name) for name in sorted(source_names)}
    queue_before = _binding(queue)
    require(queue_before["sha256"] == _hash(gap_queue_sha256), "original gap queue changed")
    producers = {name: _binding(path.absolute()) for name, path in PRODUCERS.items()}
    out.mkdir(parents=True)
    for name in sorted(source_names):
        target = out / "source-evidence" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    shutil.copyfile(queue, out / "input_gap_queue.parquet")
    products, contexts, report = _replay(
        out / "source-evidence", out / "input_gap_queue.parquet",
        source_manifest_sha256, gap_queue_sha256,
    )
    for name, rows in products.items():
        _write_rows(out / name, rows)
    pq.write_table(contexts, out / "context_inventory.parquet")
    _write(out / "report.json", report)
    after = {name: _binding(source / name) for name in sorted(source_names)}
    require(_tree(source) == source_names and _same(before, after)
            and _same(queue_before, _binding(queue))
            and _same(producers, {name: _binding(path.absolute())
                                  for name, path in PRODUCERS.items()}),
            "source, queue or producer changed during normalization")
    _write(out / "source_inventory.json", before)
    _write(out / "source_immutability.json", {
        "before": before, "after": after,
        "original_queue_before": queue_before, "original_queue_after": queue_before,
        "all_original_inputs_unchanged": True,
    })
    (out / "producer").mkdir()
    for name, path in PRODUCERS.items():
        shutil.copyfile(path, out / "producer" / name)
    names = PRODUCTS | {"source-evidence/" + name for name in source_names}
    manifest = {
        "schema": SCHEMA, "status": STATUS,
        "source_manifest_sha256": source_manifest_sha256,
        "gap_queue_sha256": gap_queue_sha256, "approvals": dict.fromkeys(FLAGS, False),
        "counts": report["counts"],
        "packet_artifacts": {name: _binding(out / name) for name in sorted(names)},
    }
    _write(out / "manifest.json", manifest)
    load(out, source_manifest_sha256=source_manifest_sha256, gap_queue_sha256=gap_queue_sha256)
    return manifest


def load(directory, metadata=None, *, source_manifest_sha256=None, gap_queue_sha256=None):
    root = Path(directory).absolute()
    require(root.is_dir() and root.resolve() == root, "missing or linked normalized directory")
    manifest = _json(root / "manifest.json")
    require(manifest["schema"] == SCHEMA and manifest["status"] == STATUS
            and _same(manifest["approvals"], dict.fromkeys(FLAGS, False)),
            "normalized schema, status or approvals")
    for key, anchor in (("source_manifest_sha256", source_manifest_sha256),
                        ("gap_queue_sha256", gap_queue_sha256)):
        _hash(manifest[key])
        if anchor is not None:
            require(manifest[key] == _hash(anchor), "external source or queue anchor changed")
    artifacts = manifest["packet_artifacts"]
    require(type(artifacts) is dict and _tree(root) == set(artifacts) | {"manifest.json"}
            and set(artifacts) >= PRODUCTS, "normalized omissions or extra members")
    pins = {"manifest.json": _binding(root / "manifest.json")["sha256"]}
    for name, expected in artifacts.items():
        _relative(name)
        require(_same(_binding(root / name), expected), f"normalized artifact changed: {name}")
        pins[name] = expected["sha256"]
    for name, path in PRODUCERS.items():
        expected = (
            SEALED_PRODUCERS[pins["manifest.json"]]
            if name == "published_corpus_text.py" and pins["manifest.json"] in SEALED_PRODUCERS
            else _binding(path.absolute())
        )
        require(_same(artifacts["producer/" + name], expected),
                f"installed/archived producer mismatch: {name}")
    source = root / "source-evidence"
    source_manifest, _ = _source(source, manifest["source_manifest_sha256"])
    source_names = set(source_manifest["artifacts"]) | {"manifest.json"}
    require(set(artifacts) == PRODUCTS | {"source-evidence/" + name for name in source_names},
            "unexpected normalized/source inventory")
    inventory = {name: _binding(source / name) for name in sorted(source_names)}
    require(_same(_json(root / "source_inventory.json"), inventory), "source inventory replay")
    products, expected_contexts, report = _replay(
        source, root / "input_gap_queue.parquet",
        manifest["source_manifest_sha256"], manifest["gap_queue_sha256"],
        legacy_observation_name=pins["manifest.json"] in SEALED_PRODUCERS,
    )
    for name, rows in products.items():
        with (root / name).open() as stream:
            actual = [json.loads(line) for line in stream]
        require(_same(actual, rows), f"full {name} replay mismatch")
    contexts = pq.read_table(root / "context_inventory.parquet")
    require(contexts.equals(expected_contexts, check_metadata=True)
            and _same(_json(root / "report.json"), report)
            and _same(manifest["counts"], report["counts"]), "original context/report replay")
    require(_same(_json(root / "source_immutability.json"), {
        "before": inventory, "after": inventory,
        "original_queue_before": artifacts["input_gap_queue.parquet"],
        "original_queue_after": artifacts["input_gap_queue.parquet"],
        "all_original_inputs_unchanged": True,
    }), "input immutability receipt")
    context_rows = contexts.to_pylist()
    if metadata is not None:
        if isinstance(metadata, dict):
            require(all(type(v) is dict and v.get("bill_id") == k for k, v in metadata.items()),
                    "current metadata key/ID mismatch")
            current = list(metadata.values())
        else:
            current = metadata.to_pylist() if isinstance(metadata, pa.Table) else list(metadata)
        index = defaultdict(list)
        for row in current:
            require(type(row) is dict and type(row.get("bill_id")) is str,
                    "typed current original metadata")
            index[row["bill_id"]].append(row)
        for row in context_rows:
            matches = index[row["bill_id"]]
            require(len(matches) == 1 and all(
                key in matches[0]
                for key in ("bill_id", "state", "identifier", "session_identifier")
            ) and all(_same(row[key], value)
                      for key, value in matches[0].items() if key in row),
                    "original metadata field or missingness/type changed")
    return products["views.jsonl"], context_rows, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("build")
    create.add_argument("--source-dir", type=Path, required=True)
    create.add_argument("--source-manifest-sha256", required=True)
    create.add_argument("--gap-queue", type=Path, required=True)
    create.add_argument("--gap-queue-sha256", required=True)
    create.add_argument("--out-dir", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--directory", type=Path, required=True)
    verify.add_argument("--source-manifest-sha256")
    verify.add_argument("--gap-queue-sha256")
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build(
            args.source_dir, args.gap_queue, args.out_dir,
            source_manifest_sha256=args.source_manifest_sha256,
            gap_queue_sha256=args.gap_queue_sha256,
        )
    else:
        _, _, _, manifest = load(
            args.directory, source_manifest_sha256=args.source_manifest_sha256,
            gap_queue_sha256=args.gap_queue_sha256,
        )
    print(json.dumps(manifest["counts"], indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Freeze a separate publisher-session comparison, without changing calendar eligibility."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as arrow_csv
import pyarrow.parquet as pq
import yaml

from state_politics import site_evidence as site
from state_politics.analysis.revealed import build_bill_input
from state_politics.bills.study_window import _snapshot
from state_politics.provenance import sha256_file, utc_now_iso

STATUS = "complete_verified_session_comparison_not_primary_cohort_or_scientific_admission"
IDENTITY = ("bill_id", "state", "identifier", "session_identifier")
LIMITATIONS = (
    "Separate, opt-in publisher-session inspection frame, not a replacement calendar cohort, "
    "native introduction census, independent gold, model input or analytical admission. "
    "Only exact checksum-bound reviewed sessions are supplied; all other states remain "
    "unknown, not zero activity. Session membership never supplies a filing date. "
    "Original readers, references, dates, source-only negatives and complete metadata survive."
)


def _require(condition, message):
    if not condition:
        raise ValueError(f"incompatible session comparison: {message}")


def _unique(rows, key):
    result = {}
    for row in rows:
        _require(isinstance(row.get(key), str) and bool(row[key]), f"missing {key}")
        _require(row[key] not in result, f"duplicate {key}")
        result[row[key]] = row
    return result


def reconcile_members(contexts, bills, calendar, abstracts, contracts):
    """Keep physical references separate from bills and preserve unknown event dates."""
    original = _unique(bills, "bill_id")
    primary = _unique(calendar, "bill_id")
    _unique(abstracts, "id")
    summaries = defaultdict(list)
    for abstract in abstracts:
        _require(abstract["bill_id"] in original, "orphan abstract")
        summaries[abstract["bill_id"]].append(abstract)
    groups, excluded, seen = defaultdict(list), [], set()
    for context in contexts:
        key = context["packet_root"], context["context_id"]
        _require(key not in seen, "duplicate native context")
        seen.add(key)
        contract = contracts.get(context["packet_root"])
        _require(contract is not None, "unreviewed native packet")
        site._unapproved(context, ("native_identity_certified", "analytical_admission"))
        if not site._session_exact_match(context, contract):
            excluded.append(context)
            continue
        bill = original.get(context["bill_id"])
        _require(bill is not None, "exact native match absent from original bills")
        _require(all(bill.get(k) == context.get(k) for k in IDENTITY), "native/bill identity")
        _require(type(context["n_retained_views"]) is int and context["n_retained_views"] >= 0,
                 "nonnegative native view count")
        if context["bill_id"] in primary:
            _require(all(primary[context["bill_id"]].get(k) == bill[k] for k in IDENTITY),
                     "calendar/bill identity")
            site._unapproved(primary[context["bill_id"]], ("analytical_admission",))
        groups[context["bill_id"]].append(context)
    _require(set(groups) == set(original), "original bills must match the exact session frame")
    members = []
    for bill_id, references in sorted(groups.items()):
        bill = original[bill_id]
        members.append({
            **{key: bill[key] for key in IDENTITY},
            "cohort_role": "alternative_verified_session_not_primary_calendar_cohort",
            "membership_basis": "exact_reviewed_publisher_session_typed_identity",
            "calendar_candidate_member": bill_id in primary,
            "event_dates_inferred": False,
            "source_bill": bill,
            "calendar_context": primary.get(bill_id),
            "native_contexts": references,
            "abstract_records": summaries[bill_id],
            "n_native_references": len(references),
            "n_retained_native_views": sum(row["n_retained_views"] for row in references),
            "native_identity_certified": False,
            **dict.fromkeys(site.ADMISSIONS, False),
        })
    return members, excluded


def metadata_views(member):
    """Preserve every full nonempty abstract variant; a title is never a bill text."""
    bill = member["source_bill"]
    variants = []
    for row in member["abstract_records"]:
        _require(row.get("abstract") is None or isinstance(row["abstract"], str),
                 "abstract must be a source string or null")
        if isinstance(row.get("abstract"), str) and row["abstract"].strip():
            variants.append(row)
    _require(bill.get("title") is None or isinstance(bill["title"], str),
             "title must be a source string or null")
    result = []
    for abstract in variants or [None]:
        text, fields = build_bill_input(
            bill.get("title") or "", abstract["abstract"] if abstract else "",
        )
        view_key = json.dumps([bill["bill_id"], abstract["id"] if abstract else None])
        result.append({
            "view_id": f"session-metadata:{hashlib.sha256(view_key.encode()).hexdigest()}",
            **{key: bill[key] for key in IDENTITY},
            "source_type": "verified_session_metadata",
            "input_basis": "complete_title_and_abstract" if abstract else "complete_title_only",
            "metadata_tier": "retained_abstract_unaligned" if abstract
            else "title_only" if text.strip() else "missing_metadata",
            "text_fields": fields,
            "text": text, "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "n_input_characters": len(text), "source_bill": bill,
            "abstract_record": abstract, "calendar_candidate_member": member[
                "calendar_candidate_member"
            ], "event_dates_inferred": False,
            **dict.fromkeys(site.ADMISSIONS, False),
        })
    return result


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
                    encoding="utf-8")


def _write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def _preview_input(preview, manifest, name):
    path = preview / name
    expected = manifest["outputs"].get(name)
    _require(
        expected is not None and path.is_file() and not path.is_symlink()
        and path.stat().st_size == expected["bytes"]
        and sha256_file(path) == expected["sha256"], f"preview source binding: {name}",
    )
    return path


def _date_ledger(path, members):
    records = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["bill_id"] not in members:
                continue
            _require(row["bill_id"] not in records, "duplicate source date-ledger context")
            _require(all(row.get(key) == members[row["bill_id"]][key] for key in IDENTITY),
                     "source date-ledger/member identity")
            records[row["bill_id"]] = row
    _require(records.keys() == members.keys(), "missing source date-ledger contexts")
    return records


def _copy_native(state, paths, members, expected, output):
    seen = set()
    path = output / f"native-{state}.jsonl"
    with (
        path.open("wb") as plain,
        (output / f"native-{state}.jsonl.gz").open("wb") as compressed,
        gzip.GzipFile(fileobj=compressed, filename="", mode="wb", mtime=0) as zipped,
    ):
        for source in paths:
            with gzip.open(source, "rb") as handle:
                for raw in handle:
                    _require(raw.endswith(b"\n"), "unterminated native JSONL")
                    row = json.loads(raw)
                    bill = members.get(row["bill_id"])
                    if bill is None:
                        continue
                    key = row["packet_root"], row["view_id"]
                    if key not in expected:
                        continue
                    _require(key not in seen, "duplicate exported native view")
                    index = expected[key]
                    _require(all(row.get(k) == bill[k] for k in IDENTITY),
                             "exported native/member identity")
                    _require(row.get("source_type") in {"native_text", "native_session_text"},
                             "native export source type")
                    _require(isinstance(row.get("text"), str), "complete native source text")
                    _require(
                        row["input_sha256"] == index["input_sha256"]
                        == hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
                        and row["n_input_characters"] == index["n_input_characters"]
                        == len(row["text"]), "complete native/index text binding",
                    )
                    site._unapproved(row, site.ADMISSIONS)
                    plain.write(raw)
                    zipped.write(raw)
                    seen.add(key)
    _require(seen == expected.keys(), f"missing complete retained native views: {state}")
    return len(seen)


def freeze_session_cohort(metadata: Path, native: Path, preview: Path, output: Path, *,
                          scopes=("ny-2023-2024", "il-103rd")):
    if output.exists():
        raise FileExistsError(f"refusing overwrite: {output}")
    _require(
        not isinstance(scopes, str) and bool(scopes) and len(set(scopes)) == len(scopes)
        and set(scopes) <= site.NATIVE_SESSION_SCOPES.keys(), "explicit reviewed session scopes",
    )
    meta, meta_pins = site._bind_bundle(metadata, {
        "bill_evidence.parquet", "abstract_evidence.parquet", "state_matrix.csv",
    })
    source, source_pins = site._bind_bundle(native, {
        "native_context_overlap.parquet", "native_view_index.parquet", "report.json",
    }, status="complete_supplied_native_overlap_not_native_census_or_analytical_admission")
    _require(meta["inputs"]["native_manifest"]["sha256"] == source_pins["manifest.json"],
             "metadata/native binding")
    preview_manifest = site._json(preview / "downloads/build_manifest.json")
    _require(
        preview_manifest.get("schema") == "local_cycle_evidence_preview_v1"
        and preview_manifest.get("publication_status") == "local_only_unpublished"
        and preview_manifest.get("study_start") == "2023-01-01"
        and preview_manifest.get("study_end") == "2024-12-31",
        "unpublished complete preview contract",
    )
    site._unapproved(preview_manifest, ("model_input_approved", "analytical_admission"))
    for kind, pins in (("bill_metadata", meta_pins), ("native_evidence", source_pins)):
        _require(all(preview_manifest["inputs"][kind].get(k) == v for k, v in pins.items()),
                 f"preview/source bundle binding: {kind}")
    registry = site._bound_input(source["inputs"]["registry"])
    specs = yaml.safe_load(registry.read_text(encoding="utf-8"))["packets"]
    reviewed, proofs = site._reviewed_session_specs(scopes, specs, source["inputs"])
    contracts = {root: item[1] for root, item in reviewed.items()}
    states = sorted(contract["state"] for contract in contracts.values())
    _require(len(set(states)) == len(states), "one reviewed session per supplied state")
    paths = {
        "metadata_manifest": metadata / "manifest.json",
        "native_manifest": native / "manifest.json",
        "preview_manifest": preview / "downloads/build_manifest.json", "registry": registry,
        "calendar_contexts": metadata / "bill_evidence.parquet",
        "state_matrix": metadata / "state_matrix.csv",
        "native_contexts": native / "native_context_overlap.parquet",
        "native_index": native / "native_view_index.parquet",
        "bills": site._bound_input(meta["inputs"]["bills"]),
        "abstracts": site._bound_input(meta["inputs"]["abstracts"]),
        "date_ledger": site._bound_input(meta["inputs"]["ledger"]),
        "style": site.ROOT / "web/preview.css",
        **{key: site._bound_input(value) for key, value in proofs.items()},
    }
    partitions = {}
    for state in states:
        partitions[state] = [
            _preview_input(preview, preview_manifest, f"downloads/{kind}-{state}.jsonl.gz")
            for kind in ("native", "native-session")
        ]
        paths.update({f"{state}_native_{i}": path
                      for i, path in enumerate(partitions[state])})
    for _, _, spec in reviewed.values():
        packet = spec.get("packet_id", spec["state"])
        for role in ("manifest", "contexts"):
            paths[f"{packet}_{role}"] = site._bound_input(source["inputs"][f"{packet}_{role}"])
    producers = [Path(__file__), Path(site.__file__),
                 Path(site.__file__).parent / "bills/study_native_overlap.py",
                 Path(site.__file__).parent / "bills/study_window.py",
                 Path(__file__).with_name("revealed.py")]
    paths.update({f"producer_{path.stem}": path for path in producers})
    before = {key: _snapshot(path) for key, path in paths.items()}
    contexts = pq.read_table(paths["native_contexts"], filters=[
        ("packet_root", "in", list(contracts)),
    ]).to_pylist()
    identities = {
        row["bill_id"] for row in contexts
        if site._session_exact_match(row, contracts[row["packet_root"]])
    }
    _require(bool(identities), "no exact canonical session members")
    selected = [("bill_id", "in", sorted(identities))]
    bills = pq.read_table(paths["bills"], filters=selected).to_pylist()
    abstracts = pq.read_table(paths["abstracts"], filters=selected).to_pylist()
    calendar = pq.read_table(paths["calendar_contexts"], filters=selected).to_pylist()
    members, excluded = reconcile_members(contexts, bills, calendar, abstracts, contracts)
    date_ledger = _date_ledger(paths["date_ledger"], {row["bill_id"]: row for row in members})
    for member in members:
        member["source_date_ledger"] = date_ledger[member["bill_id"]]
    indexed = pq.read_table(paths["native_index"], filters=[
        ("packet_root", "in", list(contracts)),
    ]).to_pylist()
    member_keys = {(row["packet_root"], row["context_id"])
                   for member in members for row in member["native_contexts"]}
    expected = {
        (row["packet_root"], row["view_id"]): row for row in indexed
        if (row["packet_root"], row["context_id"]) in member_keys
    }
    _require(len(expected) == sum(row["n_retained_native_views"] for row in members),
             "complete native index/reference counts")
    matrix = arrow_csv.read_csv(paths["state_matrix"]).to_pylist()
    _require(len(matrix) == len(site.STATES) and {r["state"] for r in matrix} == site.STATES,
             "exactly fifty original state rows")
    output.mkdir(parents=True)
    (output / "sources").mkdir()
    (output / "producers").mkdir()
    shutil.copyfile(paths["style"], output / "preview.css")
    for path in producers:
        shutil.copyfile(path, output / "producers" / path.name)
    for _, contract, spec in reviewed.values():
        packet = spec.get("packet_id", spec["state"])
        shutil.copyfile(paths[f"{packet}_contexts"],
                        output / "sources" / f"contexts-{contract['state']}.parquet")
        shutil.copyfile(paths[f"{packet}_manifest"],
                        output / "sources" / f"manifest-{contract['state']}.json")
    _write_json(output / "reviewed_scope_proofs.json", {
        scope: {"contract": contract, "registry_spec": spec,
                "binding_proofs": {key: site._json(site._bound_input(value))
                                   for key, value in proofs.items()}}
        for scope, contract, spec in reviewed.values()
    })
    _write_rows(output / "session_members.jsonl", members)
    _write_rows(output / "excluded_native_contexts.jsonl", excluded)
    all_counts = Counter()
    summary = []
    for original in matrix:
        state = original["state"]
        rows = [row for row in members if row["state"] == state]
        count = {
            "session_members": len(rows),
            "also_calendar_candidates": sum(row["calendar_candidate_member"] for row in rows),
            "session_only_members": sum(not row["calendar_candidate_member"] for row in rows),
            "native_references": sum(row["n_native_references"] for row in rows),
            "members_with_retained_native_text": sum(
                row["n_retained_native_views"] > 0 for row in rows
            ),
            "members_without_retained_native_text": sum(
                row["n_retained_native_views"] == 0 for row in rows
            ),
            "complete_native_views": sum(row["n_retained_native_views"] for row in rows),
        }
        if state in states:
            by_id = {row["bill_id"]: row for row in rows}
            _require(_copy_native(state, partitions[state], by_id, {
                key: row for key, row in expected.items() if row["state"] == state
            }, output) == count["complete_native_views"], "native exported population")
            views = [view for row in rows for view in metadata_views(row)]
            _write_rows(output / f"metadata-{state}.jsonl", views)
            count["complete_metadata_views"] = len(views)
            all_counts.update(count)
        else:
            count = dict.fromkeys([*count, "complete_metadata_views"], None)
        summary.append({
            "state": state,
            "session_scope_status": "reviewed_scope_supplied" if state in states
            else "not_supplied_not_zero_activity",
            "calendar_candidate_contexts_unchanged": (
                original["n_cycle_evidence_candidate_contexts"]
            ),
            **count, "event_dates_inferred": False, "analytical_admission": False,
        })
    arrow_csv.write_csv(pa.Table.from_pylist(summary), output / "state_comparison.csv")
    report = {
        "status": STATUS, "completed_at": utc_now_iso(), "scopes": list(scopes),
        "counts": dict(all_counts), "all_states_accounted": 50,
        "states_with_reviewed_session_scope": states,
        "excluded_native_contexts_preserved": len(excluded),
        "primary_calendar_candidate_contexts_unchanged": sum(
            row["n_cycle_evidence_candidate_contexts"] for row in matrix
        ), "new_primary_cohort_admissions": 0, "event_dates_inferred": False,
        "model_promotion": False, "publication": False,
        **dict.fromkeys(site.ADMISSIONS, False), "limitations": LIMITATIONS,
    }
    _write_json(output / "report.json", report)
    links = "".join(
        f'<li>{state}: <a download href="metadata-{state}.jsonl">complete metadata views</a>; '
        f'<a download href="native-{state}.jsonl.gz">every retained full-text view</a>; '
        f'<a download href="sources/contexts-{state}.parquet">original source contexts</a></li>'
        for state in states
    )
    table = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row[key]))}</td>" for key in (
            "state", "session_scope_status", "calendar_candidate_contexts_unchanged",
            "session_members", "session_only_members", "members_without_retained_native_text",
        )) + "</tr>" for row in summary
    )
    (output / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Unpublished legislative-session comparison</title>'
        '<link rel="stylesheet" href="preview.css"><main>'
        '<p class="eyebrow">Local research / unpublished</p>'
        '<h1>Legislative-session comparison</h1>'
        f'<p>{html.escape(LIMITATIONS)}</p><ul>{links}</ul>'
        '<p><a download href="session_members.jsonl">Complete member records, original bill '
        'fields, abstracts and native references</a> · '
        '<a download href="excluded_native_contexts.jsonl">All excluded native contexts</a> · '
        '<a download href="state_comparison.csv">All 50 states</a></p>'
        '<div class="table-wrap"><table>'
        '<caption>Calendar cohort is unchanged; None means unknown, not zero.</caption>'
        '<thead><tr><th>State</th><th>Session evidence</th><th>Calendar candidates</th>'
        '<th>Session members</th><th>Session-only members</th><th>Missing retained text</th>'
        f'</tr></thead><tbody>{table}</tbody></table></div></main></html>\n', encoding="utf-8",
    )
    after = {key: _snapshot(path) for key, path in paths.items()}
    _require(before == after, "immutable source inputs changed while freezing")
    artifacts = {
        path.relative_to(output).as_posix(): {
            "sha256": sha256_file(path), "bytes": path.stat().st_size,
        } for path in sorted(output.rglob("*")) if path.is_file()
    }
    manifest = {
        "schema_version": 1, **report, "inputs_before": before, "inputs_after": after,
        "inputs_unchanged": True, "artifacts": artifacts,
    }
    _write_json(output / "manifest.json", manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument("--scope", action="append", choices=sorted(site.NATIVE_SESSION_SCOPES))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = freeze_session_cohort(
        args.metadata, args.native, args.preview, args.out,
        scopes=tuple(args.scope) if args.scope else tuple(site.NATIVE_SESSION_SCOPES),
    )
    print(json.dumps({"status": result["status"], "counts": result["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

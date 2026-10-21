"""Local-only cycle evidence export. No collection, classification or analytical admission."""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.parquet as pq

from state_politics.bills.openstates_dump import STATE_CODES
from state_politics.provenance import sha256_file

ROOT = Path(__file__).resolve().parents[2]
STATES = frozenset(state.upper() for state in STATE_CODES)
ORGANIZATIONS = frozenset((state, party) for state in STATES for party in ("D", "R"))
COHORTS = (
    "source_coded_event", "native_reported_date_candidate", "description_stated_event_candidate",
)
ADMISSIONS = (
    "model_input_approved", "filing_time_text_certified", "training_admission",
    "analytical_admission",
)


def _require(condition, message):
    if not condition:
        raise ValueError(f"incompatible cycle evidence: {message}")


def _json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _jsonl(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unapproved(row, required):
    _require(
        all(row.get(key) is False for key in required), "admission/certification must be false",
    )
    _require(
        all(row[key] is False or row[key] is None for key in ADMISSIONS if key in row),
        "unexpected admission flag",
    )


def _bind_bundle(directory, required, *, platform=False):
    _require(directory.is_dir() and not directory.is_symlink(), "missing or linked input bundle")
    manifest_path = directory / "manifest.json"
    _require(manifest_path.is_file() and not manifest_path.is_symlink(), "missing source manifest")
    manifest = _json(manifest_path)
    if platform:
        _require(manifest.get("schema") == "platform_study_evidence_v1", "platform schema")
        _require(
            manifest.get("status") == "complete_evidence_inventory_not_scientific_admission"
            and manifest.get("scientific_certification") == "not_performed"
            and manifest.get("analysis_cutoff") is None
            and manifest.get("study_start") == "2023-01-01"
            and manifest.get("study_end") == "2024-12-31",
            "platform status/cutoff",
        )
        artifacts = manifest.get("files", {})
    else:
        _require(
            manifest.get("schema_version") == 1
            and manifest.get("status")
            == "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted"
            and manifest.get("inputs_unchanged") is True,
            "metadata schema/status",
        )
        _unapproved(manifest, ("model_input_approved", "analytical_admission"))
        artifacts = manifest.get("artifacts", {})
    _require(required <= artifacts.keys(), "missing required manifest artifact")
    pins = {"manifest.json": sha256_file(manifest_path)}
    for name, entry in artifacts.items():
        _require(Path(name).name == name and name != "manifest.json", "unsafe artifact name")
        path = directory / name
        _require(path.is_file() and not path.is_symlink(), f"missing artifact {name}")
        expected = entry if platform else entry["sha256"]
        digest = sha256_file(path)
        _require(digest == expected, f"artifact hash mismatch: {name}")
        if not platform:
            _require(path.stat().st_size == entry["bytes"], f"artifact size mismatch: {name}")
        pins[name] = digest
    return manifest, pins


def _unique(rows, key):
    result = {row[key]: row for row in rows}
    _require(len(result) == len(rows) and None not in result, f"duplicate/missing {key}")
    return result


def _state_rows(table, state):
    return table.filter(pc.equal(table["state"], state)).to_pylist()


def _bill_rows(state, tables):
    contexts, abstracts, views = (_state_rows(table, state) for table in tables)
    bills = _unique(contexts, "bill_id")
    sources = _unique(abstracts, "id")
    seen_bills, seen_abstracts = set(), set()
    result = []
    for context in contexts:
        _unapproved(
            context, ("model_input_approved", "filing_time_text_certified", "analytical_admission"),
        )
        _require(context["cohort_scope"] in COHORTS, "unknown candidate cohort")
    for abstract in abstracts:
        _require(
            abstract["bill_id"] in bills
            and isinstance(abstract["abstract"], str)
            and _digest(abstract["abstract"]) == abstract["abstract_sha256"],
            "abstract identity/text hash",
        )
    for view in views:
        _unapproved(view, ADMISSIONS)
        _require(
            view["n_input_tokens"] is None and view["n_discarded_tokens"] is None
            and view["chunking_status"] == "not_tokenized",
            "unexpected tokenization",
        )
        context = bills.get(view["bill_id"])
        _require(context is not None, "view missing bill context")
        _require(
            all(view[key] == context[key] for key in (
                "state", "identifier", "session_identifier", "title", "cohort_scope",
            )),
            "view/context identity",
        )
        _require(
            isinstance(view["text"], str) and _digest(view["text"]) == view["input_sha256"]
            and len(view["text"]) == view["n_input_characters"],
            "metadata full-text hash/length",
        )
        abstract = sources.get(view["abstract_id"])
        if view["abstract_id"] is not None:
            _require(
                abstract is not None and abstract["bill_id"] == view["bill_id"]
                and view["abstract"] == abstract["abstract"]
                and view["abstract_note"] == abstract["note"],
                "view/source abstract mismatch",
            )
            seen_abstracts.add(view["abstract_id"])
        else:
            _require(view["abstract"] is None, "unbound abstract text")
        seen_bills.add(view["bill_id"])
        result.append({
            "source_type": "bill_metadata", **view, "bill_context": context,
            "source_abstract": abstract,
        })
    _require(seen_bills == bills.keys(), "bill contexts missing candidate views")
    _require(seen_abstracts == sources.keys(), "source abstracts missing candidate views")
    return result, contexts, abstracts


def _validate_metadata(report, matrix, tables):
    _require(len(matrix) == 50 and {row["state"] for row in matrix} == STATES, "50-state matrix")
    for table, key in zip(tables, ("bill_id", "id", "view_id"), strict=True):
        values = table[key].to_pylist()
        _require(len(set(values)) == len(values) and None not in values, f"duplicate {key}")
        _require(set(table["state"].to_pylist()) <= STATES, "unexpected metadata state")
    _unapproved(report, ("model_input_approved", "analytical_admission"))
    _require(
        report.get("status")
        == "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted",
        "metadata report status",
    )
    cohorts, counts = Counter(), Counter()
    for row in matrix:
        state = row["state"]
        views, contexts, abstracts = _bill_rows(state, tables)
        state_cohorts = Counter(context["cohort_scope"] for context in contexts)
        expected_counts = {
            "n_cycle_evidence_candidate_contexts": len(contexts),
            "n_cycle_metadata_candidate_views": len(views),
            "n_native_only_scope_candidates": state_cohorts[COHORTS[1]],
            "n_description_only_scope_candidates": state_cohorts[COHORTS[2]],
            "n_filing_or_introduction_in_window": state_cohorts[COHORTS[0]],
            "n_cycle_contexts_with_nonempty_abstract": sum(
                context["n_nonempty_abstract_records"] > 0 for context in contexts
            ),
            "n_cycle_contexts_with_multiple_abstract_variants": sum(
                context["n_distinct_abstract_texts"] > 1 for context in contexts
            ),
        }
        for key, value in expected_counts.items():
            _require(row[key] == value, f"state counts do not reconcile: {state}/{key}")
        native = [context["n_indexed_native_views"] for context in contexts]
        if row["n_cycle_contexts_with_indexed_native_text"] is None:
            _require(all(value is None for value in native), "native unknown changed to zero")
        else:
            _require(
                all(value is not None for value in native)
                and row["n_cycle_contexts_with_indexed_native_text"]
                == sum(value > 0 for value in native),
                "native index counts do not reconcile",
            )
        cohorts.update(state_cohorts)
        counts.update({
            "n_cycle_contexts": len(contexts), "n_cycle_abstract_records": len(abstracts),
            "n_metadata_candidate_views_not_bills": len(views),
            "n_cycle_contexts_with_nonempty_abstract": expected_counts[
                "n_cycle_contexts_with_nonempty_abstract"
            ],
            "n_cycle_contexts_with_multiple_abstract_variants": expected_counts[
                "n_cycle_contexts_with_multiple_abstract_variants"
            ],
        })
    _require(dict(cohorts) == report["cohort_scope_counts"], "cohort report counts")
    _require(all(report[key] == value for key, value in counts.items()), "metadata report counts")
    return dict(counts), dict(cohorts)


def _validate_platform(manifest, organizations, records):
    keys = [(row["state"], row["party"]) for row in organizations]
    _require(len(keys) == 100 and set(keys) == ORGANIZATIONS, "100 unique organizations")
    _unique(records, "record_id")
    partitions = defaultdict(list)
    for row in records:
        _unapproved(row, ("training_admission", "analytical_admission"))
        _require(
            row["adoption_certified"] is False and row["human_gold"] is False
            and row["analysis_cutoff"] is None
            and row["cycle_applicability"] == "unresolved"
            and row["operative_platform_status"] == "unresolved",
            "unexpected certified platform/applicability",
        )
        text = row["extracted_text"]
        _require(
            (text is None and row["text_sha256"] is None)
            or (isinstance(text, str) and _digest(text) == row["text_sha256"]),
            "platform full-text hash",
        )
        key = (row["state"], row["party"])
        if key not in ORGANIZATIONS:
            _require(
                row.get("organization_scope") == "excluded_national_or_other_party",
                "unrecognized outside-organization evidence",
            )
            key = ("outside", "")
        partitions[key].append({"source_type": "platform", **row})
    for org in organizations:
        _unapproved(org, ("training_admission", "analytical_admission"))
        _require(
            org["cycle_applicability"] == "unresolved"
            and org["operative_platform_status"] == "unresolved",
            "organization applicability must remain unresolved",
        )
        rows = partitions[org["state"], org["party"]]
        _require(
            org["n_evidence_records"] == len(rows)
            and org["record_kind_counts"] == dict(Counter(row["record_kind"] for row in rows))
            and org["cycle_date_counts"] == dict(Counter(
                date for row in rows for date in row["cycle_date_dispositions"]
            ))
            and org["n_retained_nonempty_text_views"]
            == sum(bool(row["extracted_text"] and row["extracted_text"].strip()) for row in rows),
            f"organization counts do not reconcile: {org['state']}/{org['party']}",
        )
    _require(
        manifest["n_evidence_records"] == len(records)
        and manifest["n_organization_rows"] == manifest["expected_organizations"] == 100
        and manifest["n_historical_outside_organization_scope"] == len(partitions["outside", ""])
        and manifest["record_kind_counts"] == dict(Counter(row["record_kind"] for row in records))
        and manifest["cycle_date_counts"] == dict(Counter(
            date for row in records for date in row["cycle_date_dispositions"]
        )),
        "platform manifest counts do not reconcile",
    )
    return partitions


def _write_partition(out, name, rows):
    path = out / "evidence" / f"{name}.jsonl"
    with (
        path.open("w", encoding="utf-8", newline="\n") as plain,
        (out / "downloads" / f"{name}.jsonl.gz").open("wb") as compressed,
        gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as zipped,
    ):
        for row in rows:
            line = json.dumps(
                row, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ) + "\n"
            plain.write(line)
            zipped.write(line.encode("utf-8"))


def build_cycle_preview(metadata_dir: Path, platform_dir: Path, out: Path) -> dict:
    """Build an unpublished preview into a fresh ignored directory, after validating inputs."""
    data = (ROOT / "data").resolve()
    _require(
        out.resolve().is_relative_to(data) and out.resolve() != data
        and not out.is_symlink(),
        "output must be a distinct directory under ignored project data/",
    )
    _require(
        not any(out.resolve().is_relative_to(source.resolve())
                or source.resolve().is_relative_to(out.resolve())
                for source in (metadata_dir, platform_dir)),
        "output overlaps source bundle",
    )
    _require(not out.exists() or (out.is_dir() and not any(out.iterdir())), "output must be empty")
    _, metadata_pins = _bind_bundle(metadata_dir, {
        "report.json", "state_matrix.csv", "bill_evidence.parquet", "abstract_evidence.parquet",
        "candidate_metadata_views.parquet",
    })
    platform_manifest, platform_pins = _bind_bundle(
        platform_dir, {"records.jsonl", "organizations.jsonl"}, platform=True,
    )
    report = _json(metadata_dir / "report.json")
    matrix = csv.read_csv(
        metadata_dir / "state_matrix.csv",
        convert_options=csv.ConvertOptions(strings_can_be_null=True, null_values=[""]),
    ).to_pylist()
    tables = tuple(pq.read_table(metadata_dir / f"{name}.parquet") for name in (
        "bill_evidence", "abstract_evidence", "candidate_metadata_views",
    ))
    counts, cohorts = _validate_metadata(report, matrix, tables)
    registered_states = sum(
        row["n_cycle_contexts_with_indexed_native_text"] is not None for row in matrix
    )
    organizations = _jsonl(platform_dir / "organizations.jsonl")
    records = _jsonl(platform_dir / "records.jsonl")
    partitions = _validate_platform(platform_manifest, organizations, records)
    out.mkdir(parents=True, exist_ok=True)
    (out / "evidence").mkdir()
    (out / "downloads").mkdir()
    for state in sorted(STATES):
        views, _, _ = _bill_rows(state, tables)
        for view in views:
            view["source_bundle_manifest_sha256"] = metadata_pins["manifest.json"]
        _write_partition(out, f"bills-{state}", views)
        for party in ("D", "R"):
            _write_partition(out, f"platform-{state}-{party}", partitions[state, party])
    _write_partition(out, "platform-outside", partitions["outside", ""])
    for source, target in (
        (metadata_dir / "manifest.json", "metadata_source_manifest.json"),
        (platform_dir / "manifest.json", "platform_source_manifest.json"),
        (metadata_dir / "report.json", "metadata_source_report.json"),
        (metadata_dir / "state_matrix.csv", "state_matrix.csv"),
        (platform_dir / "organizations.jsonl", "organizations.jsonl"),
    ):
        shutil.copyfile(source, out / "downloads" / target)
    def escape(value):
        return html.escape(str(value), quote=True)

    state_rows, org_rows = [], []
    for row in sorted(matrix, key=lambda item: item["state"]):
        state = row["state"]
        native = row["n_cycle_contexts_with_indexed_native_text"]
        values = (
            f"{state} — {row['state_name']}", row["n_cycle_evidence_candidate_contexts"],
            row["n_filing_or_introduction_in_window"], row["n_native_only_scope_candidates"],
            row["n_description_only_scope_candidates"], row["n_cycle_metadata_candidate_views"],
            row["n_cycle_contexts_with_nonempty_abstract"],
            "Unknown (not registered)" if native is None else f"{native} (index only)",
        )
        cells = "".join(f"<td>{escape(value)}</td>" for value in values)
        wider_contexts = escape(row.get("n_retained_contexts_wider_history", "unknown"))
        state_rows.append(
            f'<tr data-state="{state}" '
            f'data-contexts="{row["n_cycle_evidence_candidate_contexts"]}" '
            f'data-wider-contexts="{wider_contexts}">'
            f'{cells}<td><a download '
            f'href="downloads/bills-{state}.jsonl.gz">{state} full metadata text</a></td></tr>'
        )
    for org in sorted(organizations, key=lambda item: (item["state"], item["party"])):
        state, party = org["state"], org["party"]
        cells = "".join(f"<td>{escape(value)}</td>" for value in (
            f"{state} / {party}", org["name"], org["n_evidence_records"],
            org["n_retained_nonempty_text_views"], "Unresolved",
        ))
        org_rows.append(
            f'<tr data-state="{state}" data-party="{party}">{cells}<td><a download '
            f'href="downloads/platform-{state}-{party}.jsonl.gz">{state}/{party} complete '
            'source views</a></td></tr>'
        )
    document = (ROOT / "web/cycle-evidence.html").read_text(encoding="utf-8")
    fields = {
        "@@STATE_OPTIONS@@": "".join(
            f'<option value="{row["state"]}">{escape(row["state_name"])} ({row["state"]})</option>'
            for row in sorted(matrix, key=lambda item: item["state_name"])
        ),
        "@@STATE_ROWS@@": "\n".join(state_rows), "@@ORG_ROWS@@": "\n".join(org_rows),
        "@@CONTEXT_COUNT@@": f"{counts['n_cycle_contexts']:,}",
        "@@VIEW_COUNT@@": f"{counts['n_metadata_candidate_views_not_bills']:,}",
        "@@ABSTRACT_COUNT@@": f"{counts['n_cycle_abstract_records']:,}",
        "@@ABSTRACT_CONTEXT_COUNT@@": f"{counts['n_cycle_contexts_with_nonempty_abstract']:,}",
        "@@ALTERNATIVE_CONTEXT_COUNT@@": (
            f"{counts['n_cycle_contexts_with_multiple_abstract_variants']:,}"
        ),
        "@@SOURCE_CODED_COUNT@@": f"{cohorts.get(COHORTS[0], 0):,}",
        "@@NATIVE_ONLY_COUNT@@": f"{cohorts.get(COHORTS[1], 0):,}",
        "@@DESCRIPTION_ONLY_COUNT@@": f"{cohorts.get(COHORTS[2], 0):,}",
        "@@PLATFORM_COUNT@@": f"{len(records):,}",
        "@@OUTSIDE_COUNT@@": f"{len(partitions['outside', '']):,}",
        "@@DATE_CANDIDATE_COUNT@@": str(platform_manifest["cycle_date_counts"].get(
            "source_observed_2023_2024_candidate", 0,
        )),
        "@@NATIVE_PACKET_STATE_COUNT@@": str(registered_states),
    }
    for marker, value in fields.items():
        document = document.replace(marker, value)
    _require("@@" not in document, "unresolved template field")
    (out / "index.html").write_text(document, encoding="utf-8")
    for name in ("preview.css", "cycle-evidence.css", "cycle-evidence.js"):
        shutil.copyfile(ROOT / "web" / name, out / name)
    for directory, pins in ((metadata_dir, metadata_pins), (platform_dir, platform_pins)):
        _require(
            all(sha256_file(directory / name) == digest for name, digest in pins.items()),
            "source bundle changed during build",
        )
    manifest = {
        "schema": "local_cycle_evidence_preview_v1", "publication_status": "local_only_unpublished",
        "scientific_certification": "not_performed", "analytical_admission": False,
        "model_input_approved": False, "study_start": "2023-01-01", "study_end": "2024-12-31",
        "counts": {
            "states": 50, "organizations": 100, **counts, "cohort_scope_counts": cohorts,
            "native_index_registered_states": registered_states,
            "platform_evidence_views": len(records),
            "platform_outside_organization_views": len(partitions["outside", ""]),
            "platform_applicability_unresolved_organizations": 100,
            "platform_cycle_date_candidate_views": platform_manifest["cycle_date_counts"].get(
                "source_observed_2023_2024_candidate", 0,
            ),
        },
        "inputs": {"bill_metadata": metadata_pins, "platform": platform_pins},
        "producer_sha256": sha256_file(Path(__file__)),
        "entrypoint_sha256": sha256_file(ROOT / "scripts/build_site.py"),
        "assets": {
            name: sha256_file(ROOT / "web" / name) for name in (
                "cycle-evidence.html", "preview.css", "cycle-evidence.css", "cycle-evidence.js",
            )
        },
        "outputs": {
            str(path.relative_to(out)): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in sorted(out.rglob("*")) if path.is_file()
        },
        "limitations": [
            "Candidate views/contexts are not certified counts or an analytical denominator.",
            "Bill title/abstract authorship and filing-time alignment are unverified.",
            "Native presence is a registered-packet index only; native text/PDFs are not exported.",
            "Registered packets include bounded partial inventories, not native-text censuses.",
            "Alternative metadata views never prepend summaries to introduced native text.",
            "Platform views overlap; date candidates are not certified platforms.",
            "Metadata-year hints do not prove adoption; old adoption does not prove applicability.",
            "GPT-assisted source review is advisory, not independent/human gold.",
            "All admission/certification flags remain false; unknown native coverage remains null.",
            "Search/download scope is the selected state and source type, not a national query.",
            "No report or public integration is authorized; redistribution needs separate review.",
        ],
    }
    (out / "downloads/build_manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    return manifest

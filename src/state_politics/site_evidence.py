"""Local-only cycle evidence export. No collection, classification or analytical admission."""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.parquet as pq
import yaml

from state_politics.bills.openstates_dump import STATE_CODES
from state_politics.bills.study_native_overlap import _field, normalize_packet
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


def _bind_bundle(directory, required, *, platform=False, status=None):
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
    elif status:
        _require(
            manifest.get("schema_version") == 1 and manifest.get("status") == status
            and manifest.get("inputs_unchanged") is True,
            "optional evidence schema/status",
        )
        _unapproved(manifest, ("analytical_admission",))
        artifacts = manifest.get("artifacts", {})
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


def _bound_input(entry):
    path = Path(entry["path"])
    if not path.is_absolute():
        path = ROOT / path
    _require(path.is_file() and not path.is_symlink(), "missing or linked bound source input")
    _require(
        sha256_file(path) == entry["sha256"] and path.stat().st_size == entry["size"],
        f"bound source input hash/size mismatch: {path.name}",
    )
    return path


def _scalar_source(path, *, include_text=True):
    # Stored token arrays and page/offset arrays are not needed to recover the indexed string.
    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    columns = [
        field.name for field in schema
        if not (pa.types.is_nested(field.type) or field.name in {
            "token_windows_json", "chunk_spans_json",
        } or (not include_text and field.name in {
            "text", "input_text", "body_text", "pymupdf_text", "pypdf_text",
        }))
    ]
    table = parquet.read(columns=list(dict.fromkeys(columns)))
    seen, duplicates, names = Counter(), defaultdict(list), []
    original_names = set(table.column_names)
    for name in table.column_names:
        seen[name] += 1
        alias = name if seen[name] == 1 else f"{name}__retained_duplicate_{seen[name]}"
        _require(alias == name or alias not in original_names, "duplicate source column alias")
        names.append(alias)
        duplicates[name].append(alias)
    table = table.rename_columns(names)
    duplicates = {name: aliases for name, aliases in duplicates.items() if len(aliases) > 1}
    if duplicates:
        _require(
            "source_duplicate_columns_json" not in original_names,
            "duplicate source column provenance collision",
        )
        table = table.append_column(
            "source_duplicate_columns_json",
            pa.array([json.dumps(duplicates, sort_keys=True)] * table.num_rows),
        )
        for name, aliases in duplicates.items():
            if name in ADMISSIONS:
                _require(
                    all(value is False or value is None
                        for alias in aliases for value in table[alias].to_pylist()),
                    "unexpected retained duplicate admission flag",
                )
    return table


def _native_rows(directory, metadata_manifest, metadata_pins, tables):
    manifest, pins = _bind_bundle(directory, {
        "native_context_overlap.parquet", "native_view_index.parquet", "report.json",
    }, status="complete_supplied_native_overlap_not_native_census_or_analytical_admission")
    _require(
        metadata_manifest.get("inputs", {}).get("native_manifest", {}).get("sha256")
        == pins["manifest.json"],
        "metadata/native manifest binding",
    )
    inputs = manifest["inputs"]
    registry_path = _bound_input(inputs["registry"])
    config = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    specs = config["packets"]
    _require(config["schema_version"] == 1 and bool(specs), "native registry schema")
    _require(len({spec["root"] for spec in specs}) == len(specs), "duplicate native packet root")
    contexts = pq.read_table(directory / "native_context_overlap.parquet").to_pylist()
    indexed = pq.read_table(directory / "native_view_index.parquet").to_pylist()
    context_map = {(row["packet_root"], row["context_id"]): row for row in contexts}
    index_map = {(row["packet_root"], row["view_id"]): row for row in indexed}
    text_roots = {row["packet_root"] for row in indexed}
    _require(len(context_map) == len(contexts), "duplicate native context binding")
    _require(len(index_map) == len(indexed), "duplicate native view binding")
    bills = _unique(tables[0].to_pylist(), "bill_id")
    partitions, consumed, seen = defaultdict(list), {"registry": inputs["registry"]}, set()
    seen_contexts = set()
    counts = Counter()
    for spec in specs:
        packet = spec.get("packet_id", spec["state"])
        paths, lineage = {}, {}
        for role in ("manifest", "contexts", "views"):
            if role == "views" and "views" not in spec:
                continue
            key = f"{packet}_{role}"
            paths[role] = _bound_input(inputs[key])
            expected_path = Path(spec["root"]) / (
                "manifest.json" if role == "manifest" else spec[role]
            )
            if not expected_path.is_absolute():
                expected_path = ROOT / expected_path
            _require(
                paths[role].resolve() == expected_path.resolve(), "native registry source path",
            )
            lineage[role] = inputs[key]
            consumed[key] = inputs[key]
        source_manifest = _json(paths["manifest"])
        _require(
            lineage["manifest"]["sha256"] == spec["manifest_sha256"],
            "native registry packet manifest",
        )
        for role in ("contexts", "views"):
            if role in paths:
                binding = source_manifest["files"][paths[role].name]
                expected = binding if isinstance(binding, str) else binding["sha256"]
                _require(expected == lineage[role]["sha256"], "native source table binding")
        materialize_text = spec["root"] in text_roots
        raw_table = _scalar_source(paths["contexts"], include_text=materialize_text)
        raw = raw_table.to_pandas()
        view_table = (
            _scalar_source(paths["views"], include_text=materialize_text)
            if "views" in paths else raw_table
        )
        normalized_contexts, normalized_views = normalize_packet(
            spec, raw, view_table.to_pandas() if "views" in paths else None,
        )
        _require(
            len(normalized_contexts) == spec["expected_contexts"]
            and len(normalized_views) == spec["expected_views"],
            "native registered populations",
        )
        for normalized in pa.Table.from_pandas(
            normalized_contexts, preserve_index=False,
        ).to_pylist():
            key = (spec["root"], normalized["context_id"])
            bound = context_map.get(key)
            _require(bound is not None, "native source context missing overlap binding")
            _require(
                normalized["canonical_join_mode"] != "source_only" or bound["bill_id"] is None,
                "source-only native context cannot join a candidate bill",
            )
            for field, value in normalized.items():
                if field in ("state", "session_identifier"):
                    actual = bound.get(f"{field}_native")
                    if actual is None:
                        actual = bound.get(field)
                else:
                    actual = bound.get(field)
                _require(actual == value, f"native normalized context binding: {field}")
            seen_contexts.add(key)
        if normalized_views.empty:
            continue
        source_key = "view_id" if spec["profile"] == "views" else "record_id"
        sources = _unique(view_table.to_pylist(), source_key)
        source_contexts = {}
        for identifier, source in zip(
            _field(raw, spec["context_id"]).astype("string"), raw_table.to_pylist(), strict=True,
        ):
            source_contexts.setdefault(str(identifier), source)
        for normalized in pa.Table.from_pandas(
            normalized_views, preserve_index=False,
        ).to_pylist():
            key = (spec["root"], normalized["view_id"])
            _require(index_map.get(key) == normalized, "native full-view/index identity")
            seen.add(key)
            native = context_map.get((spec["root"], normalized["context_id"]))
            _require(native is not None, "native view missing exact context")
            _unapproved(native, ("native_identity_certified", "analytical_admission"))
            source = sources[normalized["view_id"]]
            text_column = "input_text" if spec.get("source_kind") == "native_html_body" else "text"
            text = source.get(text_column)
            _require(
                isinstance(text, str) and _digest(text) == normalized["input_sha256"]
                and len(text) == normalized["n_input_characters"],
                "native complete stored text hash/length",
            )
            _unapproved(source, ())
            bill = bills.get(native["bill_id"])
            if bill is None:
                continue
            _require(
                all(native[field] == bill[field] for field in (
                    "bill_id", "state", "identifier", "session_identifier",
                )) and normalized["state"] == bill["state"],
                "native/candidate exact context mapping",
            )
            def source_metadata(row):
                return {key: value for key, value in row.items()
                        if key not in ("text", "input_text", "body_text")}

            record = {
                "source_type": "native_text", **normalized, "text": text,
                "bill_id": bill["bill_id"], "identifier": bill["identifier"],
                "session_identifier": bill["session_identifier"], "title": bill["title"],
                "cohort_scope": bill["cohort_scope"], "bill_context": bill,
                "native_context": native, "source_record": source_metadata(source),
                "source_context_record": source_metadata(
                    source_contexts[normalized["context_id"]],
                ),
                "source_bundle_manifest_sha256": pins["manifest.json"],
                "source_lineage": {
                    "native_manifest_sha256": pins["manifest.json"],
                    "native_index_sha256": pins["native_view_index.parquet"],
                    "native_context_overlap_sha256": pins["native_context_overlap.parquet"],
                    "metadata_manifest_sha256": metadata_pins["manifest.json"],
                    "candidate_contexts_sha256": metadata_pins["bill_evidence.parquet"],
                    "registry": inputs["registry"], "packet_inputs": lineage,
                },
                "native_identity_certified": False, "model_input_approved": False,
                "filing_time_text_certified": False, "training_admission": False,
                "analytical_admission": False,
            }
            partitions[bill["state"]].append(record)
            counts[bill["bill_id"]] += 1
    _require(seen == index_map.keys(), "native index contains unregistered/unrecovered views")
    _require(seen_contexts == context_map.keys(), "native overlap contains unregistered contexts")
    for bill in bills.values():
        if bill["n_indexed_native_views"] is not None:
            _require(
                counts[bill["bill_id"]] == bill["n_indexed_native_views"],
                "native candidate full-view count",
            )
    return partitions, pins, consumed


def _token_plans(directory, metadata_pins, tables):
    manifest, pins = _bind_bundle(directory, {"report.json", "token_window_plan.parquet"},
                                 status=(
        "complete_unlabelled_metadata_token_plan_not_inference_or_admission"
    ))
    _unapproved(manifest, ("model_input_approved", "analytical_admission"))
    _require(manifest.get("model_inference_performed") is False, "token plan inference flag")
    inputs = manifest["inputs"]
    old_manifest = _json(_bound_input(inputs["evidence_manifest"]))
    _bound_input(inputs["views"])
    _require(
        inputs["views"]["sha256"]
        == old_manifest["artifacts"]["candidate_metadata_views.parquet"]["sha256"]
        == metadata_pins["candidate_metadata_views.parquet"],
        "token plan candidate artifact binding",
    )
    views = _unique(tables[2].select([
        "view_id", "bill_id", "input_sha256", "n_input_characters",
    ]).to_pylist(), "view_id")
    columns = [
        "view_id", "bill_id", "input_sha256", "n_input_characters", "n_input_tokens",
        "n_windows", "n_unique_covered_tokens", "n_overlap_token_positions",
        "n_discarded_tokens", "window_model_input_lengths",
        "model_input_approved", "analytical_admission",
    ]
    plans, totals = {}, Counter()
    lineage = {
        "manifest_sha256": pins["manifest.json"],
        "token_window_plan_sha256": pins["token_window_plan.parquet"],
        "candidate_metadata_views_sha256": metadata_pins["candidate_metadata_views.parquet"],
        "current_metadata_manifest_sha256": metadata_pins["manifest.json"],
        "planned_metadata_manifest_sha256": inputs["evidence_manifest"]["sha256"],
        "input_sha256": {key: entry["sha256"] for key, entry in inputs.items()},
        "binding": "identical_complete_candidate_metadata_views_artifact",
    }
    for batch in pq.ParquetFile(directory / "token_window_plan.parquet").iter_batches(
        columns=columns, batch_size=2048,
    ):
        for row in batch.to_pylist():
            _unapproved(row, ("model_input_approved", "analytical_admission"))
            view = views.get(row["view_id"])
            _require(
                view is not None and row["view_id"] not in plans
                and all(row[key] == value for key, value in view.items()),
                "token plan exact view/id/input binding",
            )
            _require(
                all(type(row[key]) is int and row[key] >= 0 for key in (
                    "n_input_tokens", "n_windows", "n_unique_covered_tokens",
                    "n_overlap_token_positions", "n_discarded_tokens",
                ))
                and row["n_discarded_tokens"] == 0
                and row["n_unique_covered_tokens"] == row["n_input_tokens"]
                and isinstance(row["window_model_input_lengths"], list)
                and row["n_windows"] == len(row["window_model_input_lengths"]) > 0
                and all(type(length) is int and 0 < length <= 1024
                        for length in row["window_model_input_lengths"]),
                "token plan coverage/window bounds",
            )
            plans[row["view_id"]] = {**row, "source_lineage": lineage}
            totals.update({key: row[key] for key in (
                "n_input_tokens", "n_windows", "n_discarded_tokens",
            )})
    _require(plans.keys() == views.keys(), "token plan must cover every metadata view")
    report = _json(directory / "report.json")
    _unapproved(report, ("model_input_approved", "analytical_admission"))
    _require(
        report["n_views"] == len(plans) and report["model_forward_passes"] == 0
        and report["model_token_budget"] <= 1024
        and all(report[key] == value for key, value in totals.items()),
        "token plan report counts/budget",
    )
    return plans, pins, inputs, dict(totals)


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


def build_cycle_preview(
    metadata_dir: Path, platform_dir: Path, out: Path, *,
    native_evidence: Path | None = None, metadata_token_plan: Path | None = None,
) -> dict:
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
                for source in (
                    metadata_dir, platform_dir, native_evidence, metadata_token_plan,
                ) if source is not None),
        "output overlaps source bundle",
    )
    _require(not out.exists() or (out.is_dir() and not any(out.iterdir())), "output must be empty")
    metadata_manifest, metadata_pins = _bind_bundle(metadata_dir, {
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
    native_partitions, native_pins, native_inputs = {}, {}, {}
    plans, plan_pins, plan_inputs, plan_counts = {}, {}, {}, {}
    if native_evidence:
        native_partitions, native_pins, native_inputs = _native_rows(
            native_evidence, metadata_manifest, metadata_pins, tables,
        )
    if metadata_token_plan:
        plans, plan_pins, plan_inputs, plan_counts = _token_plans(
            metadata_token_plan, metadata_pins, tables,
        )
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
            if metadata_token_plan:
                view["token_plan"] = plans[view["view_id"]]
        _write_partition(out, f"bills-{state}", views)
        if native_evidence:
            _write_partition(out, f"native-{state}", native_partitions.get(state, []))
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
    for directory, prefix in (
        (native_evidence, "native"), (metadata_token_plan, "metadata_token_plan"),
    ):
        if directory:
            for name in ("manifest", "report"):
                shutil.copyfile(
                    directory / f"{name}.json", out / "downloads" / f"{prefix}_source_{name}.json",
                )
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
            f'href="downloads/bills-{state}.jsonl.gz">{state} full metadata text</a>'
            + (f'<br><a download href="downloads/native-{state}.jsonl.gz">'
               f'{state} complete native cohort views</a>' if native_evidence else "")
            + '</td></tr>'
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
        "@@NATIVE_OPTION@@": (
            '<option value="native_text">Native retained full text (candidate cohort only)</option>'
            if native_evidence else ""
        ),
        "@@TOKEN_PLAN_NOTE@@": (
            f"Verified complete tokenization planning for {len(plans):,} metadata views: "
            f"{plan_counts['n_input_tokens']:,} source tokens, "
            f"{plan_counts['n_windows']:,} windows, zero discarded tokens; every window "
            "is at most 1,024 model-input tokens. Counts live in a separate token_plan namespace; "
            "original metadata token fields remain null / not assessed. "
            if metadata_token_plan else
            "Metadata token fields remain null / not assessed in this preview. "
            "A separate offline token-window plan is not included here; "
        ) + "Tokenization planning is not predictions, certainty, model admission "
        "or classification.",
        "@@NATIVE_NOTE@@": (
            f"<strong>{sum(map(len, native_partitions.values())):,} complete retained native "
            "views are included for exact joined candidate contexts only.</strong> "
            "Reader/source alternatives and duplicate source roots remain separate views, "
            "not extra bills. Unmatched and out-of-cohort contexts are excluded without asserting "
            "source absence. Native identity, dates, stage and negative caveats remain unverified; "
            "no introduced-stage or filing-time certification is supplied. "
            if native_evidence else
            "<strong>Native documents are not included.</strong> Even a positive index count "
            "here does not provide native PDF/document text. "
        ) + f"Native presence is relative to {registered_states} registered state packets only; "
        "other states remain unknown. Bounded packets are not native-text censuses. "
        "Zero means no matching indexed view, not no native text. Original PDFs are not included.",
        "@@OPTIONAL_DOWNLOADS@@": "".join(
            f' · <a download href="downloads/{prefix}_source_manifest.json">'
            f'Original {label} manifest</a> · <a download '
            f'href="downloads/{prefix}_source_report.json">{label} scope report</a>'
            for included, prefix, label in (
                (native_evidence, "native", "native full-text source"),
                (metadata_token_plan, "metadata_token_plan", "tokenization planning"),
            ) if included
        ),
        "@@NATIVE_DOWNLOAD_NOTE@@": (
            "Native downloads contain every matching complete stored native string, exact "
            "candidate mapping, reader/root identity, source lineage and original caveats; "
            "they do not prepend title/abstract summaries. Original PDFs are not included."
            if native_evidence else "Native originals are not included."
        ),
    }
    for marker, value in fields.items():
        document = document.replace(marker, value)
    _require("@@" not in document, "unresolved template field")
    (out / "index.html").write_text(document, encoding="utf-8")
    for name in ("preview.css", "cycle-evidence.css", "cycle-evidence.js"):
        shutil.copyfile(ROOT / "web" / name, out / name)
    for directory, pins in (
        (metadata_dir, metadata_pins), (platform_dir, platform_pins),
        (native_evidence, native_pins), (metadata_token_plan, plan_pins),
    ):
        if directory is None:
            continue
        _require(
            all(sha256_file(directory / name) == digest for name, digest in pins.items()),
            "source bundle changed during build",
        )
    for entry in (*native_inputs.values(), *(
        entry for key, entry in plan_inputs.items() if key in ("evidence_manifest", "views")
    )):
        _bound_input(entry)
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
            (
                "Native full text is restricted to exact candidate contexts, not a native census."
                if native_evidence else
                "Native presence is a registered-packet index only; "
                "native text/PDFs are not exported."
            ),
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
    if native_evidence:
        manifest["inputs"]["native_evidence"] = {
            **native_pins, "consumed_source_inputs": native_inputs,
            "normalizer_sha256": sha256_file(
                Path(__file__).with_name("bills") / "study_native_overlap.py",
            ),
        }
        manifest["counts"]["native_full_text_candidate_views"] = sum(
            map(len, native_partitions.values()),
        )
        manifest["counts"]["native_full_text_candidate_contexts"] = len({
            row["bill_id"] for rows in native_partitions.values() for row in rows
        })
    if metadata_token_plan:
        manifest["inputs"]["metadata_token_plan"] = {
            **plan_pins, "accepted_plan_inputs": plan_inputs,
            "binding": "identical_complete_candidate_metadata_views_artifact",
        }
        manifest["counts"]["metadata_token_plan"] = {"n_views": len(plans), **plan_counts}
    (out / "downloads/build_manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    return manifest

"""Local-only cycle evidence export. No collection, classification or analytical admission."""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.parquet as pq
import yaml

from state_politics.bills.archive_text import load_archive
from state_politics.bills.openstates_dump import STATE_CODES
from state_politics.bills.research_corpus_text import load_corpus
from state_politics.bills.study_native_overlap import _field, normalize_packet
from state_politics.bills.study_window import _snapshot
from state_politics.provenance import sha256_file
from state_politics.site_snapshot_text import export_snapshot

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
# These bind the entire reviewed registry specification, including selectors, source-only
# exclusions, reader policy, populations and (for NY) the checksum-bound campaign proof.
NATIVE_SESSION_SCOPES = {
    "ny-2023-2024": {
        "state": "NY", "session_identifier": "2023-2024",
        "packet_root": "data/processed/retained-campaign-input-index-2023-2024-v1/NY",
        "packet_spec_sha256": "01690f363095cf7050574ac6048e0a5d07490c77367c366f7a10af5cd1f694a1",
    },
    "il-103rd": {
        "state": "IL", "session_identifier": "103rd",
        "packet_root": "data/processed/retained-campaign-input-index-2023-2024-v1/IL",
        "packet_spec_sha256": "9328f3c3f8c8df2b77dad21625e804b7091e275ea2feea5fe25e25d7664d8835",
    },
    "tx-88r-retained": {
        "state": "TX", "session_identifier": "88",
        "packet_root": "data/processed/retained-supplement-input-index-2023-2024-v1/TX",
        "packet_spec_sha256": "499691e7105f0f81f50c549425e2325bf83be6abfd570b3cff2e340b1b68f227",
    },
}
SESSION_SCOPE_LABEL = (
    "Publisher-session-bound evidence OUTSIDE candidate date cohort; "
    "not native/date/analytical admission"
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


def _reviewed_session_specs(scopes, specs, inputs):
    reviewed, proofs = {}, {}
    for scope in scopes:
        contract = NATIVE_SESSION_SCOPES[scope]
        matches = [spec for spec in specs if spec["root"] == contract["packet_root"]]
        _require(len(matches) == 1, f"missing exact reviewed publisher-session packet: {scope}")
        spec = matches[0]
        _require(
            _digest(json.dumps(spec, sort_keys=True, ensure_ascii=True, allow_nan=False))
            == contract["packet_spec_sha256"],
            f"reviewed publisher-session registry selectors/proof changed: {scope}",
        )
        for index, binding in enumerate(spec.get("binding_evidence", [])):
            key = f"{spec.get('packet_id', spec['state'])}_binding_evidence_{index}"
            _require(key in inputs, "missing publisher-session binding proof")
            path = _bound_input(inputs[key])
            expected = Path(binding["path"])
            if not expected.is_absolute():
                expected = ROOT / expected
            _require(
                path.resolve() == expected.resolve()
                and inputs[key]["sha256"] == binding["sha256"],
                "publisher-session proof path/checksum binding",
            )
            value = _json(path)
            try:
                for part in binding["selector"].split("."):
                    value = value[part]
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    "incompatible cycle evidence: publisher-session proof selector",
                ) from exc
            _require(
                json.dumps(value, sort_keys=True, allow_nan=False)
                == json.dumps(binding["expected"], sort_keys=True, allow_nan=False),
                "publisher-session proof value",
            )
            proofs[key] = inputs[key]
        reviewed[spec["root"]] = (scope, contract, spec)
    return reviewed, proofs


def _session_exact_match(native, contract):
    if native["bill_id"] is None or native["canonical_join_mode"] == "source_only":
        return False
    return (
        native["canonical_join_basis"] in {
            "unique_declared_session_typed_identity",
            "declared_bill_id_exact_session_typed_identity",
        }
        and native["state"] == contract["state"]
        and (native.get("state_native") or native["state"]) == contract["state"]
        and native["session_identifier"] == contract["session_identifier"]
        and (native.get("session_identifier_native") or native["session_identifier"])
        == contract["session_identifier"]
    )


def _native_rows(directory, metadata_manifest, metadata_pins, tables, session_scopes=()):
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
    reviewed, proof_inputs = _reviewed_session_specs(session_scopes, specs, inputs)
    contexts = pq.read_table(directory / "native_context_overlap.parquet").to_pylist()
    indexed = pq.read_table(directory / "native_view_index.parquet").to_pylist()
    context_map = {(row["packet_root"], row["context_id"]): row for row in contexts}
    index_map = {(row["packet_root"], row["view_id"]): row for row in indexed}
    text_roots = {row["packet_root"] for row in indexed}
    _require(len(context_map) == len(contexts), "duplicate native context binding")
    _require(len(index_map) == len(indexed), "duplicate native view binding")
    bills = _unique(tables[0].to_pylist(), "bill_id")
    partitions, consumed, seen = defaultdict(list), {"registry": inputs["registry"]}, set()
    consumed.update(proof_inputs)
    session_partitions, session_counts, session_bindings = {}, {}, {}
    seen_contexts = set()
    counts = Counter()
    for spec in specs:
        session_scope = reviewed.get(spec["root"])
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
        if session_scope:
            scope, contract, _ = session_scope
            scoped_contexts = [
                context_map[spec["root"], identifier]
                for identifier in normalized_contexts["context_id"]
            ]
            exact = [row for row in scoped_contexts if _session_exact_match(row, contract)]
            text_exact = [row for row in exact if row["n_retained_views"] > 0]
            excluded = [row for row in text_exact if row["bill_id"] in bills]
            exported = [row for row in text_exact if row["bill_id"] not in bills]
            session_partitions[contract["state"]] = []
            session_counts[scope] = {
                "state": contract["state"], "session_identifier": contract["session_identifier"],
                "registered_contexts": len(scoped_contexts),
                "indexed_views": len(normalized_views),
                "exact_canonical_references": len(exact),
                "exact_canonical_bills": len({row["bill_id"] for row in exact}),
                "exact_canonical_full_text_views": sum(
                    row["n_retained_views"] for row in text_exact
                ),
                "exact_canonical_full_text_references": len(text_exact),
                "exact_canonical_full_text_bills": len({row["bill_id"] for row in text_exact}),
                "candidate_excluded_views": sum(row["n_retained_views"] for row in excluded),
                "candidate_excluded_references": len(excluded),
                "candidate_excluded_bills": len({row["bill_id"] for row in excluded}),
                "exported_views": sum(row["n_retained_views"] for row in exported),
                "exported_references": len(exported),
                "exported_unique_canonical_bills": len({row["bill_id"] for row in exported}),
                "excluded_unmatched_source_only_or_wrong_session_contexts": (
                    len(scoped_contexts) - len(exact)
                ),
                "excluded_unmatched_source_only_or_wrong_session_views": (
                    len(normalized_views) - sum(row["n_retained_views"] for row in text_exact)
                ),
                "reader_excluded_views": sum(row.get("n_excluded_views") or 0
                                             for row in scoped_contexts),
                "source_window_dispositions_by_reference": dict(Counter(
                    row.get("window_disposition") for row in exported
                )),
                "cohort_admissions": 0,
            }
            session_bindings[scope] = {
                **contract, "scope_label": SESSION_SCOPE_LABEL, "registry_spec": spec,
                "registry": inputs["registry"], "packet_inputs": lineage,
                "binding_proofs": {
                    key: value for key, value in proof_inputs.items()
                    if key.startswith(f"{packet}_binding_evidence_")
                },
            }
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
                if session_scope and _session_exact_match(native, session_scope[1]):
                    source_context = source_contexts[normalized["context_id"]]
                    _unapproved(source_context, ())
                    session_partitions[session_scope[1]["state"]].append({
                        **normalized, "source_type": "native_session_text", "text": text,
                        "bill_id": native["bill_id"], "identifier": native["identifier"],
                        "session_identifier": native["session_identifier"],
                        "evidence_scope": session_scope[0], "scope_label": SESSION_SCOPE_LABEL,
                        "candidate_cohort_member": False, "eligible_cycle_admission": False,
                        "native_context": native,
                        "source_record": {
                            key: value for key, value in source.items() if key != text_column
                        },
                        "source_text_bindings": {f"source_record.{text_column}": "text"},
                        "source_context_record": source_context,
                        "source_bundle_manifest_sha256": pins["manifest.json"],
                        "source_lineage": {
                            "native_manifest_sha256": pins["manifest.json"],
                            "native_index_sha256": pins["native_view_index.parquet"],
                            "native_context_overlap_sha256": pins["native_context_overlap.parquet"],
                            "metadata_manifest_sha256": metadata_pins["manifest.json"],
                            "candidate_exclusion_contexts_sha256": metadata_pins[
                                "bill_evidence.parquet"
                            ],
                            "registry": inputs["registry"], "packet_inputs": lineage,
                            "reviewed_session_scope": session_bindings[session_scope[0]],
                        },
                        "native_identity_certified": False,
                        **dict.fromkeys(ADMISSIONS, False),
                    })
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
    for scope, values in session_counts.items():
        _require(
            len(session_partitions[values["state"]]) == values["exported_views"],
            f"publisher-session complete retained view reconciliation: {scope}",
        )
    return partitions, pins, consumed, session_partitions, session_counts, session_bindings


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


def _receipt_rows(directory):
    def source_flags(row):
        _unapproved(row, ())
        _require(
            all(row[key] is False for key in (
                "source_admission", "native_census", "native_evidence",
                "introduction_or_filing_inference", "eligible_cycle_admission",
                "model_inference_performed",
            ) if key in row),
            "receipt source admission/inference flags must be false",
        )

    manifest, pins = _bind_bundle(directory, {
        "report.json", "verification.json", "target_calendar_receipt_observations.jsonl",
        "source_contexts.jsonl", "source_bills.parquet", "source_bill_actions.parquet",
        "all_action_dispositions.parquet",
    }, status="complete_retained_maine_receipt_observations_not_source_admission")
    source_flags(manifest)
    _require(
        manifest.get("state") == "ME"
        and (manifest.get("window_start"), manifest.get("window_end"))
        == ("2023-01-01", "2024-12-31")
        and manifest.get("introduction_or_filing_inference") is False
        and manifest.get("original_source_writes") == manifest.get("new_requests") == 0,
        "receipt scope/inference/collection flags",
    )
    report = _json(directory / "report.json")
    source_flags(report)
    _unapproved(report, ("analytical_admission",))
    _require(
        report.get("status") == manifest["status"]
        and report.get("counts") == manifest.get("counts")
        and report.get("inputs_unchanged") is True and report.get("new_requests") == 0,
        "receipt report contract",
    )
    inputs = manifest.get("inputs", {})
    _require(bool(inputs) and inputs == manifest.get("inputs_after"), "receipt immutable inputs")
    for entry in inputs.values():
        _bound_input(entry)
        _require(_snapshot(Path(entry["path"])) == entry, "receipt source seven-stat binding")
    packet_files = {name: _snapshot(directory / name) for name in pins}
    _require(
        all(entry["sha256"] == pins[name] for name, entry in packet_files.items()),
        "receipt packet changed while binding",
    )
    target = _jsonl(directory / "target_calendar_receipt_observations.jsonl")
    _require(
        len(target) == manifest["counts"]["target_calendar_interest_actions"],
        "receipt target counts",
    )
    action_ids = [row["source_action"]["action_id"] for row in target]
    _require(
        all(isinstance(value, str) and value for value in action_ids)
        and len(set(action_ids)) == len(action_ids), "receipt unique source action IDs",
    )
    bill_ids = {row["source_action"]["bill_id"] for row in target}
    contexts = {}
    n_contexts = 0
    with (directory / "source_contexts.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            context = json.loads(line)
            n_contexts += 1
            if context["bill_id"] in bill_ids:
                _require(context["bill_id"] not in contexts, "receipt duplicate source context")
                contexts[context["bill_id"]] = context
    _require(
        contexts.keys() == bill_ids
        and n_contexts == manifest["counts"]["all_retained_me_bills"],
        "receipt complete original context joins",
    )
    actions = _unique(pq.read_table(
        directory / "source_bill_actions.parquet",
        filters=[("action_id", "in", action_ids)],
    ).to_pylist(), "action_id")
    bills = _unique(pq.read_table(
        directory / "source_bills.parquet", filters=[("bill_id", "in", sorted(bill_ids))],
    ).to_pylist(), "bill_id")
    dispositions = pq.read_table(
        directory / "all_action_dispositions.parquet",
        filters=[("target_calendar_interest", "=", True)],
    ).to_pylist()
    observed = _unique(dispositions, "action_id")
    _require(observed.keys() == set(action_ids), "receipt complete target population")
    rows = []
    for original in target:
        action, bill, observation = (
            original["source_action"], original["source_bill"], original["observation"]
        )
        action_id, bill_id = action["action_id"], action["bill_id"]
        context = contexts[bill_id]
        for source in (original, action, bill, context):
            source_flags(source)
        source_flags(observation)
        _unapproved(observation, ("analytical_admission",))
        _require(
            action == actions.get(action_id) and bill == bills.get(bill_id)
            and bill == context["original_bill"]
            and bill["state"] == action["state"] == "ME"
            and action_id in context["original_action_ids"],
            "receipt exact original action/bill/context join",
        )
        _require(
            observation == {key: value for key, value in observed[action_id].items()
                            if key not in action}
            and observation["target_calendar_interest"] is True,
            "receipt complete unchanged observation fields",
        )
        event = datetime.fromisoformat(action["date"]).date().isoformat()
        spans = json.loads(observation["receipt_spans_json"])
        _require(len(spans) == observation["receipt_statement_count"] == 1, "receipt literal spans")
        span = spans[0]
        for raw, offsets in (
            ("receipt_raw", "receipt_span"), ("receiver_raw", "receiver_span"),
            ("literal_date_raw", "literal_date_span"),
        ):
            start, end = span[offsets]
            _require(action["description"][start:end] == span[raw], "receipt raw literal span")
        literal = datetime.strptime(span["literal_date_raw"], "%B %d, %Y").date().isoformat()
        _require(
            span["receipt_span"][0] == 0
            and span["receipt_raw"]
            == f"Received by the {span['receiver_raw']} on {span['literal_date_raw']}"
            and span["receiver_raw"] in {"Clerk of the House", "Secretary of the Senate"}
            and event == observation["event_calendar_date"]
            and literal == span["literal_calendar_date"] == observation["literal_calendar_date"]
            and (("2023-01-01" <= event <= "2024-12-31")
                 or ("2023-01-01" <= literal <= "2024-12-31"))
            and observation["date_agreement"]
            == ("dates_agree" if event == literal else "dates_disagree"),
            "receipt calendar/literal agreement",
        )
        _require(
            original["raw_event_date_span"]
            == {"source_field": "date", "raw_value": action["date"],
                "span": [0, len(action["date"])]},
            "receipt raw event date",
        )
        if observation["is_unambiguous_origin_receipt"]:
            _require(
                event == literal and "2023-01-01" <= event <= "2024-12-31"
                and bill["from_organization_id"] == action["organization_id"]
                and bill["originating_chamber"] == action["chamber"] == span["literal_chamber"]
                and observation["bill_exact_receipt_action_count"]
                == observation["action_id_occurrences"]
                == observation["same_observed_event_occurrences"] == 1,
                "receipt unique origin/date-agreeing identity",
            )
        rows.append({
            **original, "source_type": "source_receipt", "state": "ME", "bill_id": bill_id,
            "identifier": bill["identifier"], "view_id": action_id,
            "receipt_status": (
                "unique_origin_date_agreeing" if observation["is_unambiguous_origin_receipt"]
                else "unresolved_receipt"
            ),
            "source_context": context,
            "source_lineage": {
                "receipt_manifest_sha256": pins["manifest.json"],
                "source_artifact_sha256": pins["target_calendar_receipt_observations.jsonl"],
                "source_context_artifact_sha256": pins["source_contexts.jsonl"],
                "original_record_sha256": _digest(json.dumps(
                    original, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                )),
            },
            **dict.fromkeys(ADMISSIONS, False),
            "native_evidence": False, "source_admission": False,
            "introduction_or_filing_inference": False, "eligible_cycle_admission": False,
        })
    counts = {
        "target_calendar_interest_views": len(rows),
        "unique_origin_date_agreeing_views": sum(
            row["receipt_status"] == "unique_origin_date_agreeing" for row in rows
        ),
        "unresolved_views": sum(row["receipt_status"] == "unresolved_receipt" for row in rows),
        "provided_states": ["ME"], "other_states": "unknown_not_supplied",
        "retained_wider_history_contexts": n_contexts, "cohort_admissions": 0,
    }
    _require(
        counts["unique_origin_date_agreeing_views"]
        == manifest["counts"]["unambiguous_origin_in_window_receipt_observations"],
        "receipt origin/date-agreeing counts",
    )
    return rows, pins, {"packet_files": packet_files, "retained_source_inputs": inputs}, counts


def build_cycle_preview(
    metadata_dir: Path, platform_dir: Path, out: Path, *,
    native_evidence: Path | None = None, metadata_token_plan: Path | None = None,
    receipt_evidence: Path | None = None,
    native_session_scopes: tuple[str, ...] = (),
    snapshot_text_evidence: Path | None = None,
    research_corpus_evidence: Path | None = None,
    archive_text_evidence: tuple[Path, ...] = (),
) -> dict:
    """Build an unpublished preview into a fresh ignored directory, after validating inputs."""
    data = (ROOT / "data").resolve()
    _require(
        not isinstance(native_session_scopes, str)
        and len(set(native_session_scopes)) == len(native_session_scopes)
        and set(native_session_scopes) <= NATIVE_SESSION_SCOPES.keys(),
        "only distinct fixed reviewed publisher-session scopes may be selected",
    )
    _require(not native_session_scopes or native_evidence is not None,
             "publisher-session source evidence requires compatible native evidence")
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
                    receipt_evidence,
                    snapshot_text_evidence,
                    research_corpus_evidence,
                    *archive_text_evidence,
                ) if source is not None),
        "output overlaps source bundle",
    )
    _require(not out.exists() or (out.is_dir() and not any(out.iterdir())), "output must be empty")
    producer_paths = {
        "site_evidence.py": Path(__file__),
        "build_site.py": ROOT / "scripts/build_site.py",
    }
    if native_evidence:
        producer_paths["study_native_overlap.py"] = (
            Path(__file__).with_name("bills") / "study_native_overlap.py"
        )
    if snapshot_text_evidence:
        producer_paths["site_snapshot_text.py"] = Path(__file__).with_name("site_snapshot_text.py")
    if research_corpus_evidence:
        producer_paths["research_corpus_text.py"] = (
            Path(__file__).with_name("bills") / "research_corpus_text.py"
        )
        producer_paths["research_texas_identity.py"] = (
            Path(__file__).with_name("bills") / "research_texas_identity.py"
        )
    if archive_text_evidence:
        for name in (
            "archive_text.py", "lawatlas_text.py", "maryland_archive_text.py",
            "nj_library_text.py", "nj_library_collection.py", "ok_retained_context_text.py",
            "billcam_text.py", "billcommons_text.py", "billcommons_nv_text.py",
            "govbot_text.py", "native_text.py",
            "published_corpus_text.py",
            "ne_journal_text.py",
            "ne_journal_collection.py",
            "ne_journal_day_text.py",
            "ne_journal_boundary_text.py",
            "ne_journal_constitutional_text.py",
            "ne_enacted_law_text.py",
            "ne_enacted_hyphen_text.py",
        ):
            producer_paths[name] = Path(__file__).with_name("bills") / name
        producer_paths["registry.py"] = Path(__file__).with_name("platforms") / "registry.py"
    archive_producers = bool(
        native_session_scopes or snapshot_text_evidence or research_corpus_evidence
        or archive_text_evidence
    )
    producer_sources = {name: path.read_bytes() for name, path in producer_paths.items()}
    producer_pins = {
        name: hashlib.sha256(source).hexdigest() for name, source in producer_sources.items()
    }
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
    corpus_views, corpus_contexts, corpus_pins = [], [], {}
    if research_corpus_evidence:
        corpus_views, corpus_contexts, corpus_pins, _ = load_corpus(
            research_corpus_evidence, tables[0].to_pylist(),
        )
    archive_views, archive_contexts, archive_bindings = [], {}, []
    for directory in archive_text_evidence:
        rows, contexts, pins, source_manifest = load_archive(directory, tables[0].to_pylist())
        archive_views.extend(
            {**row, "source_bundle_manifest_sha256": pins["manifest.json"]} for row in rows
        )
        for row in contexts:
            archive_contexts[row["bill_id"]] = row
        archive_bindings.append((directory, pins, source_manifest))
    _require(len({row["view_id"] for row in archive_views}) == len(archive_views),
             "duplicate independent-archive source view")
    native_partitions, native_pins, native_inputs = {}, {}, {}
    session_partitions, session_counts, session_bindings = {}, {}, {}
    plans, plan_pins, plan_inputs, plan_counts = {}, {}, {}, {}
    receipts, receipt_pins, receipt_inputs, receipt_counts = [], {}, {}, {}
    if receipt_evidence:
        receipts, receipt_pins, receipt_inputs, receipt_counts = _receipt_rows(receipt_evidence)
    if native_evidence:
        (
            native_partitions, native_pins, native_inputs,
            session_partitions, session_counts, session_bindings,
        ) = _native_rows(
            native_evidence, metadata_manifest, metadata_pins, tables, native_session_scopes,
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
    if archive_producers:
        (out / "downloads/producers").mkdir()
        for name, source in producer_sources.items():
            (out / "downloads/producers" / name).write_bytes(source)
    snapshot_counts, snapshot_coverage, snapshot_pins = {}, [], {}
    if snapshot_text_evidence:
        snapshot_counts, snapshot_coverage, snapshot_pins, _ = export_snapshot(
            snapshot_text_evidence, out, tables[0].to_pylist(), STATES,
        )
        for source, target in (
            ("sealed_manifest.json", "snapshot_source_manifest.json"),
            ("state_text_coverage.csv", "snapshot_state_coverage.csv"),
            ("report.json", "snapshot_source_report.json"),
        ):
            shutil.copyfile(snapshot_text_evidence / source, out / "downloads" / target)
    for state in sorted(STATES):
        views, _, _ = _bill_rows(state, tables)
        for view in views:
            view["source_bundle_manifest_sha256"] = metadata_pins["manifest.json"]
            if metadata_token_plan:
                view["token_plan"] = plans[view["view_id"]]
        _write_partition(out, f"bills-{state}", views)
        if native_evidence:
            _write_partition(out, f"native-{state}", native_partitions.get(state, []))
        if research_corpus_evidence:
            _write_partition(out, f"corpus-{state}", [
                {**row, "source_bundle_manifest_sha256": corpus_pins["manifest.json"]}
                for row in corpus_views if row["state"] == state
            ])
        if archive_text_evidence:
            _write_partition(out, f"archive-{state}", [
                row for row in archive_views if row["state"] == state
            ])
        for party in ("D", "R"):
            _write_partition(out, f"platform-{state}-{party}", partitions[state, party])
    _write_partition(out, "platform-outside", partitions["outside", ""])
    if receipt_evidence:
        _write_partition(out, "receipts-ME", receipts)
    for state, rows in session_partitions.items():
        _write_partition(out, f"native-session-{state}", rows)
    for source, target in (
        (metadata_dir / "manifest.json", "metadata_source_manifest.json"),
        (platform_dir / "manifest.json", "platform_source_manifest.json"),
        (metadata_dir / "report.json", "metadata_source_report.json"),
        (metadata_dir / "state_matrix.csv", "state_matrix.csv"),
        (platform_dir / "organizations.jsonl", "organizations.jsonl"),
    ):
        shutil.copyfile(source, out / "downloads" / target)
    if research_corpus_evidence:
        for source, target in (
            ("manifest.json", "corpus_source_manifest.json"),
            ("report.json", "corpus_source_report.json"),
        ):
            shutil.copyfile(research_corpus_evidence / source, out / "downloads" / target)
    for index, (directory, _, _) in enumerate(archive_bindings, 1):
        for name in ("manifest.json", "report.json"):
            shutil.copyfile(directory / name, out / "downloads" / f"archive_{index}_{name}")
    for directory, prefix in (
        (native_evidence, "native"), (metadata_token_plan, "metadata_token_plan"),
        (receipt_evidence, "receipt"),
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
    session_section = ""
    if native_session_scopes:
        session_rows = []
        by_state = {values["state"]: values for values in session_counts.values()}
        for state in sorted(STATES):
            values = by_state.get(state)
            session_rows.append(
                f'<tr data-state="{state}" '
                f'data-session-provided="{str(values is not None).lower()}" '
                f'data-views="{values["exported_views"] if values else ""}" '
                f'data-references="{values["exported_references"] if values else ""}" '
                f'data-bills="{values["exported_unique_canonical_bills"] if values else ""}">'
                f'<td>{state}</td><td>'
                + (f'{escape(values["session_identifier"])}: '
                   f'{values["exported_views"]} full views / '
                   f'{values["exported_references"]} source references / '
                   f'{values["exported_unique_canonical_bills"]} unique canonical bill IDs; '
                   f'{values["candidate_excluded_views"]} candidate views excluded'
                   if values else "Unknown — no reviewed publisher-session scope supplied")
                + '</td><td>'
                + (f'<a download href="evidence/native-session-{state}.jsonl">'
                   f'{state} full source text (plain JSONL)</a> · '
                   f'<a download href="downloads/native-session-{state}.jsonl.gz">'
                   f'{state} full source text (gzip JSONL)</a>' if values else "Not supplied")
                + '</td></tr>'
            )
        session_section = (
            '<section aria-labelledby="session-coverage-heading">'
            '<h2 id="session-coverage-heading">Publisher-session-bound evidence OUTSIDE '
            'candidate date cohort</h2>'
            '<p>Explicitly selected reviewed publisher sessions only; not eligible 2023–2024 '
            'bills, native/date/analytical admission, or a native-text census. Exact canonical '
            'matches already in the metadata candidate cohort are excluded here. Reader '
            'alternatives and physical source references are not extra bills. Full original '
            'observed dates/window dispositions remain unchanged, including known outside-window '
            'dates; printed/session dates are not filing dates. No date is required or inferred. '
            'No token plan or model statistics are supplied for this source. '
            'Other states/sessions are unknown, not measured zero.</p>'
            '<div class="table-wrap" tabindex="0" aria-label="Publisher-session source coverage">'
            '<table id="session-coverage"><caption>Separate reviewed publisher-session source '
            'scope, not candidate/date admission</caption><thead><tr><th scope="col">State</th>'
            '<th scope="col">Publisher-session source status</th><th scope="col">'
            'Complete text downloads</th></tr></thead><tbody>'
            + "".join(session_rows) + '</tbody></table></div></section>'
        )
    receipt_section = ""
    if receipt_evidence:
        receipt_rows = []
        for state in sorted(STATES):
            provided = state == "ME"
            receipt_rows.append(
                f'<tr data-state="{state}" data-receipt-provided="{str(provided).lower()}" '
                f'data-observations="{len(receipts) if provided else ""}"><td>{state}</td><td>'
                + (f'{len(receipts)} observed source-receipt views' if provided
                   else "Unknown — no receipt packet supplied")
                + '</td><td>'
                + ('<a download href="downloads/receipts-ME.jsonl.gz">'
                   'ME complete source-receipt observations</a>' if provided else "Not supplied")
                + '</td></tr>'
            )
        receipt_section = (
            '<section aria-labelledby="receipt-coverage-heading">'
            '<h2 id="receipt-coverage-heading">Separate source-receipt observations '
            '— not cycle candidates</h2>'
            f'<p>{len(receipts)} target-calendar-interest Maine observations: '
            f'{receipt_counts["unique_origin_date_agreeing_views"]} unique origin/date-agreeing '
            f'and {receipt_counts["unresolved_views"]} unresolved. Original action and literal '
            'description dates are both retained; a discrepancy is never repaired. Receipt is '
            'not introduction, filing, native evidence or eligible-cycle admission. Maine’s '
            'active candidate count remains unchanged. '
            'Other states are unknown, not measured zero.</p>'
            '<div class="table-wrap" tabindex="0" aria-label="Separate source-receipt coverage">'
            '<table id="receipt-coverage"><caption>Optional receipt packet scope, independent of '
            'the active bill/native/model cohort</caption><thead><tr><th scope="col">State</th>'
            '<th scope="col">Receipt evidence status</th>'
            '<th scope="col">Full original fields download</th>'
            '</tr></thead><tbody>' + "".join(receipt_rows) + '</tbody></table></div></section>'
        )
    snapshot_section = ""
    if snapshot_text_evidence:
        snapshot_rows = []
        for row in snapshot_coverage:
            state = row["state"]
            snapshot_rows.append(
                f'<tr data-state="{state}" data-records="{row["context_rows"]}" '
                f'data-nonempty="{row["nonempty_retained_rows"]}">'
                f'<td>{state}</td><td>{row["context_rows"]:,}</td>'
                f'<td>{row["nonempty_retained_rows"]:,}</td>'
                f'<td>{row["error_flagged_rows"]:,}</td>'
                f'<td><a download href="downloads/snapshot-{state}.jsonl.gz">'
                f'{state} complete source records and retained text</a></td></tr>'
            )
        snapshot_section = (
            '<section aria-labelledby="snapshot-heading"><h2 id="snapshot-heading">'
            'Retained search-text snapshot: version-bound, not introduced text</h2>'
            '<p>Complete selected source records include raw_text, search_vector, all_titles, '
            'provider errors and exact selected version/link metadata. Missing and error rows '
            'are preserved, not filled from another version. Index creation timestamps are '
            'not filing dates; nonempty text and source metadata do not certify introduced '
            'versions, party affiliation or model inputs. A zero candidate count, including '
            'Maine, is not zero source activity outside this calendar frame.</p>'
            '<div class="table-wrap" tabindex="0" aria-label="Retained snapshot text coverage">'
            '<table id="snapshot-coverage"><caption>All fifty states; overlapping with native '
            'and metadata sources, not additional bills</caption><thead><tr>'
            '<th scope="col">State</th><th scope="col">Candidate source records</th>'
            '<th scope="col">Nonempty retained text</th><th scope="col">Provider errors</th>'
            '<th scope="col">Complete records download</th></tr></thead><tbody>'
            + "".join(snapshot_rows) + '</tbody></table></div></section>'
        )
    corpus_section = ""
    if research_corpus_evidence:
        corpus_rows = []
        for state in sorted(STATES):
            n_contexts = sum(row["state"] == state for row in corpus_contexts)
            n_views = sum(row["state"] == state for row in corpus_views)
            corpus_rows.append(
                f'<tr data-state="{state}" data-contexts="{n_contexts}" '
                f'data-views="{n_views}"><td>{state}</td><td>{n_contexts:,}</td>'
                f'<td>{n_views:,}</td><td><a download href="downloads/corpus-{state}.jsonl.gz">'
                f'{state} complete research-corpus records</a></td></tr>'
            )
        corpus_section = (
            '<section aria-labelledby="corpus-heading"><h2 id="corpus-heading">'
            'Independent research-corpus text: printed-header joins, not publisher originals</h2>'
            '<p>Original cleaned text and every original source-record field are preserved. '
            'Printed state, session and bill identity join only existing missing-text candidates; '
            'titles, effective dates and filenames never establish a join. Source summaries are '
            'not human gold or predictions. Existing later-session prefilings remain in their '
            'unchanged candidate cohort. Versions, provenance quality, filing-time alignment '
            'and all scientific/model approvals remain uncertified. Zero means no matching '
            'recovered text in this supplied packet, not publisher absence.</p>'
            '<p><a download href="downloads/corpus_source_manifest.json">'
            'Complete research-source manifest and original-record ancestry</a> · '
            '<a download href="downloads/corpus_source_report.json">'
            'Source scope and rejected-row accounting</a></p>'
            '<div class="table-wrap" tabindex="0" aria-label="Research-corpus text coverage">'
            '<table id="corpus-coverage"><caption>Complete matching research text, overlapping '
            'existing bill identities rather than new bills</caption><thead><tr>'
            '<th scope="col">State</th><th scope="col">Existing candidate contexts</th>'
            '<th scope="col">Complete source views</th><th scope="col">Full record download</th>'
            '</tr></thead><tbody>' + "".join(corpus_rows) + '</tbody></table></div></section>'
        )
    archive_section = ""
    if archive_text_evidence:
        archive_rows = []
        for state in sorted(STATES):
            n_contexts = sum(row["state"] == state for row in archive_contexts.values())
            n_views = sum(row["state"] == state for row in archive_views)
            archive_rows.append(
                f'<tr data-state="{state}" data-contexts="{n_contexts}" data-views="{n_views}">'
                f'<td>{state}</td><td>{n_contexts:,}</td><td>{n_views:,}</td><td>'
                f'<a download href="downloads/archive-{state}.jsonl.gz">'
                f'{state} complete independent-archive records</a></td></tr>'
            )
        archive_links = "".join(
            f'<li><a download href="downloads/archive_{index}_manifest.json">'
            f'Archive {index}: full source manifest</a> / '
            f'<a download href="downloads/archive_{index}_report.json">scope report</a></li>'
            for index in range(1, len(archive_bindings) + 1)
        )
        archive_section = (
            '<section aria-labelledby="archive-heading"><h2 id="archive-heading">'
            'Independent archived bill text: not publisher-version certification</h2>'
            '<p>Printed identity, exact document pointers and retained session evidence join '
            'existing candidates. Separately reviewed same-legislature annual-context relations '
            'are not session aliases: original source and candidate sessions remain distinct, '
            'without target-year filing, introduction or bill-specific carryover certification. '
            'Alternative providers and combined substitutes remain separate complete views, '
            'not extra bills. Archived extraction prologues, when present, remain unaltered '
            'and are not human labels. Original metadata, versions and source-member hashes '
            'are retained. Complete research ZIPs in the graph gallery additionally preserve '
            'the original archived HTML/PDF bytes and negative evidence. Licensing, original '
            'version, filing-time, party and all scientific/model approvals remain unresolved. '
            'No matching supplied text is not publisher absence.</p><ul>' + archive_links
            + '</ul><div class="table-wrap" tabindex="0" aria-label="Independent archive coverage">'
            '<table id="archive-coverage"><caption>Provider overlaps counted once per candidate; '
            'all source alternatives preserved</caption><thead><tr><th scope="col">State</th>'
            '<th scope="col">Existing candidate contexts</th><th scope="col">Full source views</th>'
            '<th scope="col">Complete record download</th></tr></thead><tbody>'
            + "".join(archive_rows) + '</tbody></table></div></section>'
        )
    fields = {
        "@@ARCHIVE_SECTION@@": archive_section,
        "@@ARCHIVE_OPTION@@": (
            '<option value="archive_text">Independent archived bill text '
            '(printed identity; not publisher-certified)</option>' if archive_text_evidence else ""
        ),
        "@@ARCHIVE_NOTE@@": (
            f'<p id="archive-scope"><strong>{len(archive_contexts):,} existing contexts / '
            f'{len(archive_views):,} complete archive views.</strong> Provider overlaps are '
            'not additional bills; retained text is not introduced-version or model approval.</p>'
            if archive_text_evidence else ""
        ),
        "@@CORPUS_SECTION@@": corpus_section,
        "@@CORPUS_OPTION@@": (
            '<option value="research_corpus_text">Independent research-corpus text '
            '(printed-header joins; not publisher-certified)</option>'
            if research_corpus_evidence else ""
        ),
        "@@CORPUS_NOTE@@": (
            f'<p id="corpus-scope"><strong>{len(corpus_contexts):,} existing candidate contexts '
            f'have {len(corpus_views):,} complete matching research-corpus views.</strong> '
            'This separately identified third-party cleaned source is not a publisher-original, '
            'introduced-version, classification or model-input certification.</p>'
            if research_corpus_evidence else ""
        ),
        "@@SNAPSHOT_SECTION@@": snapshot_section,
        "@@SNAPSHOT_OPTION@@": (
            '<option value="snapshot_text">Retained snapshot text (selected version, '
            'not certified introduced)</option>' if snapshot_text_evidence else ""
        ),
        "@@SNAPSHOT_NOTE@@": (
            f'<p id="snapshot-scope"><strong>{snapshot_counts["n_nonempty_retained_texts"]:,} '
            'candidate contexts have nonempty retained snapshot text.</strong> '
            f'All {snapshot_counts["n_records"]:,} source records, including errors/missing '
            'text, are preserved. This provider-selected text is separate from publisher-native '
            'reader views and may be amended/later. No introduced-version or model approval.</p>'
            if snapshot_text_evidence else ""
        ),
        "@@SNAPSHOT_DOWNLOAD_NOTE@@": (
            '<p class="note">Snapshot downloads retain every original source field and full '
            'raw_text without truncation, all provider flags, and exact selected version/link '
            'records. Source row ordinals remain explicit. They do not prepend summaries, '
            'replace missing versions or authorize model use.</p>' if snapshot_text_evidence else ""
        ),
        "@@SESSION_SECTION@@": session_section,
        "@@SESSION_OPTION@@": (
            '<option value="native_session_text">Publisher-session native text '
            '(OUTSIDE candidate date cohort)</option>' if native_session_scopes else ""
        ),
        "@@SESSION_DOWNLOAD_NOTE@@": (
            "Publisher-session source downloads retain complete native text, all indexed "
            "reader/reference alternatives, original source context, hashes and observed dates "
            "outside the candidate date cohort; they never add candidate or model inputs."
            if native_session_scopes else ""
        ),
        "@@RECEIPT_SECTION@@": receipt_section,
        "@@RECEIPT_OPTION@@": (
            '<option value="source_receipt">Source-receipt observations '
            '(separate; not cycle candidates)</option>'
            if receipt_evidence else ""
        ),
        "@@RECEIPT_DOWNLOAD_NOTE@@": (
            "Receipt downloads preserve the full original action/date/description, date spans, "
            "all original bill/context/abstract fields, provenance and unresolved observations. "
            "They do not add cycle candidates." if receipt_evidence else ""
        ),
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
                (receipt_evidence, "receipt", "separate source-receipt evidence"),
            ) if included
        ) + ("".join(
            f' · <a download href="downloads/producers/{name}">'
            f'Archived producer source: {name}</a>' for name in producer_paths
        ) if archive_producers else ""),
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
        (receipt_evidence, receipt_pins),
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
    for entries in receipt_inputs.values():
        for entry in entries.values():
            _require(
                _snapshot(Path(entry["path"])) == entry,
                "receipt source changed during build (SHA/seven-stat)",
            )
    if snapshot_text_evidence:
        _require(
            all(sha256_file(snapshot_text_evidence / name) == digest
                for name, digest in snapshot_pins.items()),
            "snapshot source changed during build",
        )
    if research_corpus_evidence:
        _require(
            all(sha256_file(research_corpus_evidence / name) == digest
                for name, digest in corpus_pins.items()),
            "research-corpus source changed during build",
        )
    for directory, pins, _ in archive_bindings:
        _require(
            all(sha256_file(directory / name) == digest for name, digest in pins.items()),
            "independent-archive source changed during build",
        )
    if archive_producers:
        for name, path in producer_paths.items():
            _require(
                sha256_file(path) == producer_pins[name]
                == sha256_file(out / "downloads/producers" / name),
                "producer source changed during build or archive binding mismatch",
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
        "producer_sha256": (
            producer_pins["site_evidence.py"] if native_session_scopes
            else sha256_file(Path(__file__))
        ),
        "entrypoint_sha256": (
            producer_pins["build_site.py"] if native_session_scopes
            else sha256_file(ROOT / "scripts/build_site.py")
        ),
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
                "Candidate-native full text remains restricted to exact candidate contexts; "
                "the separately selected publisher-session source is outside that date cohort."
                if native_session_scopes else
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
            "normalizer_sha256": (
                producer_pins["study_native_overlap.py"] if native_session_scopes
                else sha256_file(producer_paths["study_native_overlap.py"])
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
    if receipt_evidence:
        manifest["inputs"]["receipt_evidence"] = {
            **receipt_pins, "consumed_source_inputs": receipt_inputs,
        }
        manifest["counts"]["source_receipt_evidence"] = receipt_counts
        manifest["limitations"].append(
            "Optional Maine receipt observations are separate evidence, never bill/native/model "
            "cohort members. Other states' receipt coverage is unknown; both dates persist.",
        )
    if archive_producers:
        manifest["producer_archive"] = {
            name: {
                "path": f"downloads/producers/{name}", "sha256": producer_pins[name],
                "original_path": str(path.relative_to(ROOT)),
            } for name, path in producer_paths.items()
        }
    if snapshot_text_evidence:
        manifest["inputs"]["snapshot_text"] = snapshot_pins
        manifest["counts"]["snapshot_text"] = snapshot_counts
        manifest["limitations"].append(
            "Retained searchable-bill text is source-snapshot/version bound, not certified "
            "introduced/native original text. Error and missing rows remain complete; index "
            "timestamps and source version notes do not establish filing-time dates or parties.",
        )
    if research_corpus_evidence:
        manifest["inputs"]["research_corpus_text"] = corpus_pins
        manifest["counts"]["research_corpus_text"] = {
            "n_contexts": len(corpus_contexts), "n_views": len(corpus_views),
            "publisher_original_verified": False, "filing_time_text_certified": False,
        }
        manifest["limitations"].append(
            "Independent cleaned research-corpus text is joined by printed headers, not "
            "certified publisher originals. All original source fields and alternatives "
            "remain complete; summaries are not human gold and no new dates/bills are admitted.",
        )
    if archive_text_evidence:
        manifest["inputs"]["archive_text"] = [
            {"schema": source["schema"], "packet_files": pins}
            for _, pins, source in archive_bindings
        ]
        manifest["counts"]["archive_text"] = {
            "n_contexts": len(archive_contexts), "n_views": len(archive_views),
            "n_packets": len(archive_bindings),
            "publisher_original_verified": False, "filing_time_text_certified": False,
        }
        manifest["limitations"].append(
            "Independent archived bill text preserves complete provider strings, metadata and "
            "printed identity evidence. Provider overlaps and combined versions are not extra "
            "bills. Original HTML/PDF bytes live in the separately delivered complete research "
            "ZIPs. Existing extraction prologues are not human gold; no dates, party, filing-time, "
            "version, licensing, scientific, publication or model approval is inferred.",
        )
    if native_session_scopes:
        manifest["inputs"]["native_session_scopes"] = session_bindings
        manifest["counts"]["native_session_source_evidence"] = {
            "scopes": session_counts, "other_states_and_sessions": "unknown_not_supplied",
            "cohort_admissions": 0,
        }
        manifest["limitations"].append(
            "Separate publisher-session-bound native source evidence is OUTSIDE the candidate "
            "date cohort; no filing date is required or inferred. Exact canonical matches only, "
            "excluding all candidate bill IDs; source-only/unmatched/reader-excluded records stay "
            "excluded and bound in original inputs. Dates/window dispositions are unaltered. "
            "No native/date/model/training/analytical admission or token statistics are supplied.",
        )
    (out / "downloads/build_manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    return manifest

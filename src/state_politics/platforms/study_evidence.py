"""Build an offline, unadmitted 2023–2024 platform evidence inventory.

Run ``python -m state_politics.platforms.study_evidence --out PATH``. Outputs are
exclusive: a failed attempt keeps an incomplete manifest and needs a new directory.
Capture attempts, alternative extractions, frozen table views and caucus registry
entries are distinct records, not additive counts of independent platforms.

Only retained structured source-date observations with checked verbatim spans enter
the source-observed date bands. Collector/archive years remain explicitly advisory;
neither dates nor assistant reviews establish adoption or continued applicability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import yaml

from state_politics.platforms.dataverse import US_STATES
from state_politics.platforms.recovery import load_recovery
from state_politics.provenance import sha256_file, utc_now_iso

ROOT = Path(__file__).resolve().parents[3]
PROCESSED = ROOT / "data/processed"
EXPECTED = {(state, party) for state in US_STATES for party in ("D", "R")}
DEFAULT_REVIEWS = (
    "source-version-visual-review-v1",
    "remaining-organization-source-role-review-v1",
    "nm-platform-version-review-v1",
    "registry-selected-source-review-v1",
)
MODERN_TABLES = (
    "completed-discovery-collection-v1",
    "linked-platform-source-recovery-v1",
)


def _json(path: Path):
    def reject(value):
        raise ValueError(f"nonfinite JSON value: {value}")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"),
                      parse_constant=reject, object_pairs_hook=pairs)


def _jsonl(path: Path) -> list[dict]:
    # str.splitlines() would split valid U+2028 characters inside retained text.
    def reject(value):
        raise ValueError(f"nonfinite JSON value: {value}")

    with path.open(encoding="utf-8") as handle:
        rows = [json.loads(line, parse_constant=reject) for line in handle if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"JSONL records must be objects: {path}")
    return rows


def _clean(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


class Inputs:
    """Hash and stat every consumed file before and after producing the packet."""

    def __init__(self):
        self.pins = {}

    def add(self, path: Path, *, role: str) -> dict:
        path = path.resolve()
        stat = path.stat()
        pin = {
            "path": str(path), "sha256": sha256_file(path), "bytes": stat.st_size,
            "stat": [stat.st_dev, stat.st_ino, stat.st_mode, stat.st_nlink,
                     stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns],
            "role": role,
        }
        prior = self.pins.get(str(path))
        if prior and any(prior[key] != pin[key] for key in ("sha256", "stat")):
            raise ValueError(f"input changed while reading: {path}")
        self.pins.setdefault(str(path), pin)
        return pin

    def packet(self, root: Path, required: set[str]) -> dict:
        self.add(root / "manifest.json", role="packet_manifest")
        manifest = _json(root / "manifest.json")
        files = manifest["files"]
        if not isinstance(files, dict) or not required.issubset(files):
            raise ValueError(f"incomplete source manifest: {root}")
        for name, digest in files.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError("source manifest path escapes packet")
            if self.add(path, role="manifested_source_file")["sha256"] != digest:
                raise ValueError(f"source manifest hash mismatch: {path}")
        return manifest

    def stable(self):
        for path, pin in list(self.pins.items()):
            self.add(Path(path), role=pin["role"])


def _identity(row: dict) -> tuple[str, str]:
    key = row["state"], row["party"]
    if key not in EXPECTED:
        raise ValueError(f"wrong state-party identity: {key}")
    return key


def date_band(value: str) -> str:
    """Band a structured date, never search a filename, URL or policy text."""
    if not isinstance(value, str):
        raise ValueError("source date must be a string")
    if len(value) == 4 and value.isascii() and value.isdigit():
        year = int(value)
        date(year, 1, 1)
    elif len(value) == 7:
        parsed = date.fromisoformat(value + "-01")
        if parsed.strftime("%Y-%m") != value:
            raise ValueError("noncanonical source date")
        year = parsed.year
    else:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("noncanonical source date")
        year = parsed.year
    if year < 2023:
        return "older_applicability_unresolved"
    if year <= 2024:
        return "source_observed_2023_2024_candidate"
    return "later_candidate_not_a_cycle_substitute"


def _base(record_id: str, row: dict, kind: str, origin: dict) -> dict:
    return {
        "record_id": record_id, "state": row["state"], "party": row["party"],
        "record_kind": kind, "origin": origin,
        "institution_type": "unresolved", "institution": None,
        "source_role": "unreviewed_candidate",
        "operative_platform_status": "unresolved",
        "cycle_applicability": "unresolved", "analysis_cutoff": None,
        "training_admission": False, "analytical_admission": False,
        "adoption_certified": False, "human_gold": False,
        "source_observed_dates": [], "cycle_date_dispositions": ["undated_candidate"],
        "advisory_reviews": [], "retained_metadata_year": None,
        "metadata_year_disposition": "unavailable",
        "extracted_text": None, "text_sha256": None,
        "source_sha256": None, "source_path": None,
    }


def _text(record: dict, value: str | None, expected: str | None = None):
    if value is not None and not isinstance(value, str):
        raise ValueError("retained text must be a string or unavailable")
    digest = hashlib.sha256(value.encode()).hexdigest() if value is not None else None
    if expected is not None and expected != digest:
        raise ValueError(f"text hash mismatch: {record['record_id']}")
    record.update(extracted_text=value, text_sha256=digest)


def _year(record: dict, value):
    if value is None:
        return
    if isinstance(value, str) and len(value) == 4 and value.isascii() and value.isdigit():
        value = int(value)
    if type(value) not in (int, float) or not math.isfinite(value) or int(value) != value:
        raise ValueError("invalid retained metadata year")
    year = int(value)
    record["retained_metadata_year"] = year
    record["metadata_year_disposition"] = {
        "older_applicability_unresolved": "older_metadata_hint_applicability_unresolved",
        "source_observed_2023_2024_candidate": "2023_2024_metadata_hint_not_date_evidence",
        "later_candidate_not_a_cycle_substitute": "later_metadata_hint_not_a_substitute",
    }[date_band(str(year))]


def _origin(path: Path, index: int, inputs: Inputs) -> dict:
    pin = inputs.pins[str(path.resolve())]
    return {"path": str(path), "sha256": pin["sha256"], "record_index": index}


def _reviews(paths: list[Path], captures: dict, inputs: Inputs) -> dict:
    grouped = defaultdict(list)
    for path in paths:
        inputs.packet(path.parent, {path.name})
        seen = set()
        for index, row in enumerate(_jsonl(path)):
            capture_id = row["capture_id"]
            if capture_id in seen or capture_id not in captures:
                raise ValueError("duplicate review or absent review capture join")
            seen.add(capture_id)
            capture = captures[capture_id]
            if row["source_sha256"] != capture["source_sha256"]:
                raise ValueError("review body join mismatch")
            if "state" in row and _identity(row) != _identity(capture):
                raise ValueError("review state-party join mismatch")
            texts = {capture["text_sha256"]: capture["extracted_text"]}
            texts.update({alt["text_sha256"]: alt["extracted_text"]
                          for alt in capture["alternate_extractions"]})
            digest = row.get("source_text_sha256",
                             row.get("text_sha256", row.get("alternate_text_sha256")))
            if digest not in texts:
                raise ValueError("review text join mismatch")
            text = texts[digest]
            complete = row.get("complete_source_text", row.get("extracted_text", text))
            if complete != text:
                raise ValueError("review complete text mismatch")
            spans = row.get("evidence_spans", [])
            if row.get("evidence_span") is not None:
                spans = [*spans, row["evidence_span"]]
            for span in spans:
                start, end = span["start"], span["end"]
                exact = span.get("exact_text", span.get("text"))
                if (type(start) is not int or type(end) is not int
                        or not 0 <= start < end <= len(text)
                        or text[start:end] != exact):
                    raise ValueError("review evidence span mismatch")
            dates = row.get("source_reported_dates", [])
            if row.get("source_reported_date") is not None:
                dates = [*dates, {"value": row["source_reported_date"],
                                 "kind": "source_reported_date"}]
            for observation in dates:
                date_band(observation["value"])
            # An index's claim without a dated span in this source is not a source date.
            direct = [obs for obs in dates
                      if obs.get("kind") != "index_asserted_approval_month_not_event_verification"]
            if direct and not spans:
                raise ValueError("source-date observation lacks exact source evidence")
            grouped[capture_id].append({
                "origin": _origin(path, index, inputs), "review": row,
                "source_text_sha256": digest, "checked_spans": spans,
                "source_date_observations": direct,
                "authority": "retained_advisory_not_adoption_or_human_gold",
            })
    return grouped


def _attach_reviews(record: dict, reviews: list[dict]):
    # Do not transfer observations between differing standard/alternative text views.
    selected = [r for r in reviews if r["source_text_sha256"] == record["text_sha256"]]
    record["advisory_reviews"] = selected
    dates = [observation for review in selected
             for observation in review["source_date_observations"]]
    record["source_observed_dates"] = dates
    if dates:
        record["cycle_date_dispositions"] = sorted({date_band(d["value"]) for d in dates})


def _record_reviews(path: Path, records: list[dict], inputs: Inputs) -> dict:
    """Attach bounded full-reading notes without promoting their authority or source type."""
    packet = inputs.packet(path.parent, {"reviews.jsonl", "selected_records.jsonl"})
    if packet.get("schema") != "platform_cycle_date_advisory_v1":
        raise ValueError("incompatible record-level advisory schema")
    if packet.get("status") != "complete_advisory_not_certification":
        raise ValueError("incomplete record-level advisory packet")
    source = Path(packet["input_records"])
    source = source if source.is_absolute() else ROOT / source
    source_manifest = inputs.packet(
        source.parent, {"records.jsonl", "organizations.jsonl", "producer.py"})
    if (source_manifest["files"]["records.jsonl"] != packet["input_records_sha256"]
            or sha256_file(source.parent / "manifest.json")
            != packet["input_inventory_manifest_sha256"]):
        raise ValueError("advisory inventory input pin mismatch")
    by_id = {row["record_id"]: row for row in records}
    expected = {r["record_id"] for r in records if r["metadata_year_disposition"]
                == "2023_2024_metadata_hint_not_date_evidence"}
    reviews = _jsonl(path)
    ids = [r["record_id"] for r in reviews]
    if (len(ids) != len(set(ids)) or set(ids) != expected
            or len(ids) != packet["expected_selected_records"]):
        raise ValueError("record advisory must account for every selected identity exactly once")
    qualifying = {"source_stated_adoption", "source_stated_amendment",
                  "source_stated_publication", "source_stated_agenda_target_year"}
    for review in reviews:
        record = by_id[review["record_id"]]
        view = by_id[review["reviewed_text_record_id"]]
        allowed = {record["record_id"], *(
            "capture:" + identity for identity in record.get("parent_capture_ids", []))}
        if (review["reviewed_text_record_id"] not in allowed
                or _identity(review) != _identity(record) or _identity(view) != _identity(record)
                or review["source_sha256"] != record["source_sha256"]
                or view["source_sha256"] != record["source_sha256"]
                or review["original_text_sha256"] != record["text_sha256"]
                or review["reviewed_text_sha256"] != view["text_sha256"]
                or review["source_inventory_records_sha256"] != packet["input_records_sha256"]
                or review["source_inventory_manifest_sha256"]
                != packet["input_inventory_manifest_sha256"]):
            raise ValueError("record advisory source/text/organization join mismatch")
        if any(review[key] is not False for key in (
            "training_admission", "analytical_admission", "independent_certification", "human_gold"
        )) or review["operative_platform_status"] != "unresolved" or (
            review["cycle_applicability"] != "unresolved" or review["reviewer_type"] != "assistant"
        ):
            raise ValueError("advisory review cannot certify or admit records")
        text = view["extracted_text"]
        if review["full_text_path"] is not None:
            full = (path.parent / review["full_text_path"]).resolve()
            if (not full.is_relative_to(path.parent.resolve())
                    or review["full_text_path"] not in packet["files"]
                    or sha256_file(full) != view["text_sha256"]):
                raise ValueError("advisory retained full-text hash mismatch")
        elif text is not None:
            raise ValueError("available reviewed text must be retained")
        additions = []
        for claim in review["source_date_claims"]:
            span = claim["evidence_span"]
            start, end = span["start"], span["end"]
            if (text is None or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(text)
                    or text[start:end] != span["exact_text"]):
                raise ValueError("record advisory evidence span mismatch")
            use = claim["use_for_cycle_date_band"]
            if type(use) is not bool or (use and claim["kind"] not in qualifying):
                raise ValueError("cover/archive/external dates cannot become cycle evidence")
            if use:
                date_band(claim["value"])
                additions.append({**claim, "review_id": review["review_id"],
                                  "source_text_sha256": view["text_sha256"],
                                  "authority": "assistant_advisory_not_operative_certification"})
        record["record_level_advisory_reviews"] = [review]
        record["source_observed_dates"].extend(additions)
        if additions:
            record["cycle_date_dispositions"] = sorted({
                date_band(d["value"]) for d in record["source_observed_dates"]})
    return {"path": str(path), "manifest_sha256": sha256_file(path.parent / "manifest.json"),
            "n_record_level_advisory_reviews": len(reviews)}


def build(
    out: Path, *, recovery: Path = PROCESSED / "recovery-source-inventory-v8/inventory.json",
    baseline: Path = PROCESSED / "recovery-source-inventory-v2/inventory.json",
    registry: Path = ROOT / "conf/party_registry.yml",
    caucus_registry: Path = ROOT / "conf/caucus_priority_registry.yml",
    modern_tables: list[Path] | None = None,
    historical: Path | None = PROCESSED / "platforms_historical.parquet",
    review_paths: list[Path] | None = None,
    caucus_table: Path = PROCESSED / "caucus_priorities.parquet",
    record_reviews: Path | None = None,
) -> dict:
    """Produce all organization rows and every selected record, or an incomplete manifest."""
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    inputs = Inputs()
    manifest = {
        "schema": "platform_study_evidence_v1", "status": "incomplete",
        "started_at": utc_now_iso(), "study_start": "2023-01-01", "study_end": "2024-12-31",
        "scientific_certification": "not_performed", "analysis_cutoff": None,
    }
    manifest_path = out / "manifest.json"

    def write_manifest():
        manifest["inputs"] = list(inputs.pins.values())
        manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")

    write_manifest()
    try:
        for path in (registry, caucus_registry, Path(__file__)):
            inputs.add(path, role="registry_or_producer")
        organizations = yaml.safe_load(registry.read_text())["organizations"]
        if len(organizations) != 100 or {_identity(r) for r in organizations} != EXPECTED:
            raise ValueError("registry must contain exactly 100 unique organizations")
        for path in (baseline, recovery):
            inputs.packet(path.parent, {"inventory.json", "captures.jsonl", "organizations.csv"})
        _, original = load_recovery(baseline, EXPECTED)
        inventory, captures = load_recovery(recovery, EXPECTED)
        by_id = {row["capture_id"]: row for row in captures}
        for row in original:
            current = by_id.get(row["capture_id"])
            if current is None or any(
                current.get(key) != value for key, value in row.items()
                if key not in {"alternate_ocr", "alternate_extractions"}
            ):
                raise ValueError("historical recovery baseline fields not preserved")
        for row in captures:
            if row["stored_path"]:
                path = Path(row["stored_path"])
                inputs.add(path if path.is_absolute() else ROOT / path, role="retained_raw_body")
            disposition = row["input_disposition"]
            if "state" in disposition and _identity(disposition) != _identity(row):
                raise ValueError("capture input-disposition identity mismatch")
        paths = review_paths if review_paths is not None else [
            PROCESSED / name / "reviews.jsonl" for name in DEFAULT_REVIEWS
        ]
        reviews = _reviews(paths, by_id, inputs)
        records, ids, alternates = [], set(), {}

        def append(record):
            if record["record_id"] in ids:
                raise ValueError("duplicate evidence record identity")
            ids.add(record["record_id"])
            records.append(record)

        body_join = defaultdict(list)
        for index, row in enumerate(captures):
            capture_id = row["capture_id"]
            record = _base(f"capture:{capture_id}", row, "recovery_capture",
                           _origin(recovery.parent / "captures.jsonl", index, inputs))
            record.update(
                capture_id=capture_id, source_sha256=row["source_sha256"],
                source_path=row["stored_path"], url=row["url"],
                retrieval_status=row["retrieval_status"],
                extraction_method=row["extraction_method"],
                retained_record=row, source_role=row["input_disposition"].get(
                    "source_role", "unreviewed_candidate"),
            )
            _text(record, row["extracted_text"],
                  row["text_sha256"] if isinstance(row["extracted_text"], str) else None)
            _year(record, row["input_disposition"].get("year"))
            _attach_reviews(record, reviews[capture_id])
            append(record)
            body_join[row["state"], row["party"], row["source_sha256"]].append(row)
            for alt in row["alternate_extractions"]:
                aid = alt["extraction_id"]
                if aid in alternates:
                    if alternates[aid]["retained_record"] != alt:
                        raise ValueError("conflicting alternate extraction identity")
                    if (alternates[aid]["state"], alternates[aid]["party"]) != _identity(row):
                        raise ValueError("alternate extraction state-party mismatch")
                    alternates[aid]["parent_capture_ids"].append(capture_id)
                    continue
                alternative = _base(f"extraction:{aid}", row, "alternative_extraction",
                                    record["origin"])
                alternative.update(
                    extraction_id=aid, extraction_kind=alt["kind"],
                    source_sha256=row["source_sha256"], source_path=row["stored_path"],
                    parent_capture_ids=[capture_id], retained_record=alt,
                    extraction_method=alt.get("extraction_method"),
                )
                _text(alternative, alt["extracted_text"], alt["text_sha256"])
                _attach_reviews(alternative, reviews[capture_id])
                alternates[aid] = alternative
                append(alternative)
        table_schemas = {}
        tables = modern_tables if modern_tables is not None else [
            PROCESSED / name / "platforms_2018_present.parquet" for name in MODERN_TABLES
        ]
        for path in tables:
            inputs.packet(path.parent, {path.name})
            table = pq.read_table(path)
            table_schemas[str(path)] = str(table.schema)
            seen = set()
            for index, raw in enumerate(table.to_pylist()):
                row = _clean(raw)
                _identity(row)
                key = row["state"], row["party"], row["sha256"]
                signature = (*key, row["url"])
                if signature in seen:
                    raise ValueError("duplicate frozen modern table identity")
                seen.add(signature)
                joins = body_join[key]
                text = row["text"]
                matching = [r for r in joins if r["url"] == row["url"]]
                exact_text = any(r["extracted_text"] == text for r in matching)
                filtered_empty = (text == "" and row.get("confirmed") is False
                                  and isinstance(row.get("reason"), str) and row["reason"])
                if not matching or not (exact_text or filtered_empty):
                    raise ValueError("frozen table missing exact source/text capture join")
                failed = row["sha256"] is None
                if failed and (row["stored_path"] is not None or any(
                    r["retrieval_status"] != "retrieval_failed" for r in matching
                )):
                    raise ValueError("failed frozen table view has a retained source")
                record = _base(f"table:{path.parent.name}:{index}", row, "frozen_modern_table_view",
                               _origin(path, index, inputs))
                record.update(retained_record=row, source_sha256=row["sha256"],
                              source_path=row["stored_path"],
                              parent_capture_ids=[r["capture_id"] for r in matching],
                              text_join_disposition=(
                                  "failed_capture_no_retained_body" if failed else
                                  "exact_capture_text" if exact_text else
                                  "empty_filtered_table_view_full_capture_text_retained"))
                _text(record, text)
                _year(record, row["year"])
                for capture in matching:
                    _attach_reviews(record, [*record["advisory_reviews"],
                                             *reviews[capture["capture_id"]]])
                append(record)
        historical_excluded = 0
        if historical is not None:
            inputs.add(historical, role="retained_historical_table")
            table = pq.read_table(historical)
            table_schemas[str(historical)] = str(table.schema)
            members = set()
            for index, row in enumerate(table.to_pylist()):
                if row["member"] in members:
                    raise ValueError("duplicate historical archive member")
                members.add(row["member"])
                in_scope = (row["state"], row["party"]) in EXPECTED
                if row["state"] not in (*US_STATES, "US") or row["party"] not in (
                    "D", "R", "other"
                ):
                    raise ValueError("invalid historical state-party identity")
                if row["party"] != row["party_raw"] and row["party_raw"] in ("D", "R"):
                    raise ValueError("historical party identity mismatch")
                if in_scope and row["party_raw"] != row["party"]:
                    raise ValueError("historical faction misattributed to D/R")
                record = _base(f"historical:{row['member']}", row, "historical_archive_view",
                               _origin(historical, index, inputs))
                record.update(retained_record=row, source_sha256=row["sha256"],
                              source_hash_verification="retained_metadata_only_raw_archive_not_read",
                              organization_scope="expected" if in_scope else
                              "excluded_national_or_other_party",
                              metadata_year_basis="archive_filename_not_source_date")
                if not in_scope:
                    historical_excluded += 1
                _text(record, row["text"])
                _year(record, row["year"])
                append(record)
        caucus_sources = yaml.safe_load(caucus_registry.read_text())["sources"]
        caucus_by_key = {}
        for row in caucus_sources:
            key = _identity(row)
            if key in caucus_by_key:
                raise ValueError("duplicate caucus registry state-party identity")
            caucus_by_key[key] = row
        caucus_rows = []
        if caucus_table.exists():
            inputs.add(caucus_table, role="retained_caucus_table")
            table = pq.read_table(caucus_table)
            table_schemas[str(caucus_table)] = str(table.schema)
            caucus_rows = [_clean(row) for row in table.to_pylist()]
        seen = set()
        for index, row in enumerate(caucus_rows or caucus_sources):
            key = _identity(row)
            if key in seen or key not in caucus_by_key:
                raise ValueError("duplicate or unregistered caucus table identity")
            seen.add(key)
            registered = caucus_by_key[key]
            if (row["institution"], row["document_type"], row["year"]) != (
                registered["institution"], registered["document_type"], registered["year"]
            ):
                raise ValueError("caucus registry/table identity mismatch")
            available = bool(caucus_rows)
            record = _base(
                f"caucus:{row['state']}:{row['party']}", row, "supplementary_caucus",
                _origin(caucus_table if available else caucus_registry, index, inputs),
            )
            record.update(
                institution_type="legislative_caucus", institution=row["institution"],
                source_role=row["document_type"], retained_record=row,
                availability="retained_text" if available else "registry_only_text_unavailable",
            )
            _text(record, row["text"] if available else None)
            _year(record, row["year"])
            append(record)
        if caucus_rows and seen != set(caucus_by_key):
            raise ValueError("caucus table omits registered sources")
        if record_reviews is not None:
            manifest["record_review_input"] = _record_reviews(record_reviews, records, inputs)
        grouped = defaultdict(list)
        for record in records:
            if record.get("organization_scope") != "excluded_national_or_other_party":
                _identity(record)
                grouped[record["state"], record["party"]].append(record)
        org_rows = []
        for organization in sorted(organizations, key=lambda r: (r["state"], r["party"])):
            selected = grouped[_identity(organization)]
            org_rows.append({
                "state": organization["state"], "party": organization["party"],
                "name": organization["name"], "n_evidence_records": len(selected),
                "record_kind_counts": dict(Counter(r["record_kind"] for r in selected)),
                "cycle_date_counts": dict(Counter(
                    band for r in selected for band in r["cycle_date_dispositions"])),
                "n_retained_nonempty_text_views": sum(
                    bool((r["extracted_text"] or "").strip()) for r in selected),
                "operative_platform_status": "unresolved", "cycle_applicability": "unresolved",
                "training_admission": False, "analytical_admission": False,
            })
        for name, rows in (("records.jsonl", records), ("organizations.jsonl", org_rows)):
            with (out / name).open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        (out / "producer.py").write_bytes(Path(__file__).read_bytes())
        inputs.stable()
        manifest.update(
            status="complete_evidence_inventory_not_scientific_admission",
            completed_at=utc_now_iso(), expected_organizations=100,
            n_evidence_records=len(records), n_organization_rows=len(org_rows),
            n_recovery_captures=len(captures),
            n_retained_response_captures=inventory["n_retained_response_captures"],
            n_failed_retrieval_attempts=inventory["n_failed_retrieval_attempts"],
            n_preserved_baseline_captures=len(original), n_alternative_extractions=len(alternates),
            n_historical_outside_organization_scope=historical_excluded,
            record_kind_counts=dict(Counter(r["record_kind"] for r in records)),
            cycle_date_counts=dict(Counter(
                band for r in records for band in r["cycle_date_dispositions"])),
            metadata_year_counts=dict(Counter(r["metadata_year_disposition"] for r in records)),
            n_review_observations=sum(map(len, reviews.values())),
            unavailable_inputs=[] if caucus_table.exists() else [str(caucus_table)],
            table_schemas=table_schemas,
            files={name: sha256_file(out / name)
                   for name in ("records.jsonl", "organizations.jsonl", "producer.py")},
            limitations=[
                "Inventory completion is not operative-platform or scientific completion.",
                "All source reviews are advisory; no independent human gold is asserted.",
                "Source-observed dates and metadata hints never imply analytical admission.",
                "Older evidence needs applicability evidence; later text cannot substitute.",
                "Captures, table views and alternative text views overlap and are not documents.",
                "Historical national/other-party records stay outside the 100 organizations.",
                "Caucus agendas are supplementary institutions, never party committee platforms.",
                "Undated text is not replaced; failed and empty extractions remain explicit.",
                "Historical raw hashes are metadata, not a fresh archive-byte check.",
                "Review inventory is bounded; unconsumed reviews/packets are not evidenced absent.",
                "Different section-date claims within a record can overlap date-band counts.",
                "Ignored local outputs are not remotely backed up by a Git commit.",
            ],
        )
        write_manifest()
        return manifest
    except Exception as error:
        manifest.update(status="incomplete", error_type=type(error).__name__, error=str(error),
                        failed_at=utc_now_iso(),
                        files={p.name: sha256_file(p) for p in out.iterdir()
                               if p.is_file() and p.name != "manifest.json"})
        write_manifest()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path,
                        default=PROCESSED / "platform-study-evidence-2023-2024-v1")
    parser.add_argument("--record-reviews", type=Path,
                        help="Optional complete, source-bound metadata-hint advisory review packet")
    args = parser.parse_args(argv)
    manifest = build(args.out, record_reviews=args.record_reviews)
    print(json.dumps({key: value for key, value in manifest.items()
                      if key.startswith("n_") or key in
                      {"status", "record_kind_counts", "cycle_date_counts"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

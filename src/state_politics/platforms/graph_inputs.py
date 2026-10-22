"""Recover observation-only collection graph inputs from frozen local platform exports.

Run ``python -m state_politics.platforms.graph_inputs --out PATH``. No retrieval,
extraction, classification or source selection is performed. Original table snapshots
are kept separate: their rows include failed/rejected collection attempts, and their
``confirmed`` fields are old automated-filter observations, not operative approvals.
Caucus registry entries without original table text never become a caucus corpus.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from state_politics.platforms.dataverse import US_STATES
from state_politics.platforms.recovery import validate_capture
from state_politics.platforms.study_evidence import Inputs, _clean, _json
from state_politics.provenance import sha256_file, utc_now_iso

ROOT = Path(__file__).resolve().parents[3]
EXPECTED = {(state, party) for state in US_STATES for party in ("D", "R")}
KINDS = {
    "recovery_capture", "alternative_extraction", "frozen_modern_table_view",
    "historical_archive_view", "supplementary_caucus",
}
STATUSES = (
    "automated_filter_accepted", "candidates_partially_unresolved", "fetch_failed",
    "candidates_rejected", "not_in_retained_modern_tables",
)
YEAR_BANDS = ("before_2023", "2023_2024_metadata_only", "after_2024", "unknown")
APPROVALS = {
    "model_input_approved": False, "training_admission": False,
    "analytical_admission": False, "operative_approval": False,
    "scientific_approval": False, "publication_approved": False,
    "adoption_certified": False, "human_gold": False,
}
LIMITATIONS = [
    "Observation-only reuse of retained sources, not operative 2023–2024 platforms.",
    "Modern table snapshots are collection dispositions, including rejected/failed attempts.",
    "Old confirmed fields mean automated content-filter outcomes, not current approvals.",
    "Rows, captures, alternative extractions and repeated bodies are not distinct platforms.",
    "Metadata years, archive years and date unknowns are preserved, not applicability evidence.",
    "Historical/national/other-party records and caucus institutions remain separate.",
    "Registry-only caucus entries cannot reconstruct absent original caucus table texts.",
    "No missing canonical selection, labels, emphasis, adoption or model outputs are inferred.",
    "Input hashes attest retained bytes, not original authority or scientific validity.",
    "This ignored local packet is not a remote backup.",
]


def _dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def _jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("refusing an empty graph table")
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _digest_text(value: str | None) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError("retained text must be a string or null")
    return hashlib.sha256(value.encode()).hexdigest() if value is not None else None


def _row_hash(row: dict) -> str:
    data = json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def _band(year) -> str:
    if year is None:
        return "unknown"
    if type(year) not in (int, float) or int(year) != year:
        raise ValueError("invalid original metadata year")
    return ("before_2023" if year < 2023 else
            "2023_2024_metadata_only" if year <= 2024 else "after_2024")


def _collection_status(rows: list[dict]) -> str:
    # Same attempted-document precedence as collect.gap_report; candidates not retained
    # in these tables are unknown, not evidence of no candidates or no platform.
    if any(row["confirmed"] for row in rows):
        return STATUSES[0]
    failed = sum(str(row["reason"]).startswith("fetch failed") for row in rows)
    if failed:
        return STATUSES[1] if failed < len(rows) else STATUSES[2]
    return STATUSES[3] if rows else STATUSES[4]


class Sources:
    def __init__(self, root: Path, manifest: dict, inputs: Inputs):
        self.root, self.inputs = root.resolve(), inputs
        self.pins = {}
        self.checked_paths = set()
        for pin in manifest["inputs"]:
            path = self.path(pin["path"])
            if str(path) in self.pins and self.pins[str(path)] != pin:
                raise ValueError("conflicting retained source pins")
            self.pins[str(path)] = pin

    def path(self, value: str) -> Path:
        path = Path(value)
        path = path if path.is_absolute() else self.root / path
        if path.resolve() != path or not path.is_relative_to(self.root):
            raise ValueError(f"source path escapes root or is linked: {value}")
        return path

    def checked(self, value: str) -> Path:
        path = self.path(value)
        pin = self.pins.get(str(path))
        if pin is None:
            raise ValueError(f"unbound retained source: {path}")
        if str(path) in self.checked_paths:
            return path
        actual = self.inputs.add(path, role=pin["role"])
        if any(actual[key] != pin[key] for key in ("sha256", "bytes")):
            raise ValueError(f"retained source hash/size mismatch: {path}")
        self.checked_paths.add(str(path))
        return path

    def optional(self, value: str) -> Path | None:
        path = self.path(value)
        return self.checked(value) if path.exists() else None


def _exports(preview: Path, build: dict, source: dict, inputs: Inputs) -> list[dict]:
    rows, ids = [], set()
    for identity in [*sorted(EXPECTED), ("outside", None)]:
        state, party = identity
        stem = f"platform-{state}" + (f"-{party}" if party else "")
        relative = f"downloads/{stem}.jsonl.gz"
        path = preview / relative
        pin = inputs.add(path, role="source_hashed_platform_export")
        expected = build["outputs"][relative]
        if any(pin[key] != expected[key] for key in ("sha256", "bytes")):
            raise ValueError(f"platform export hash/size mismatch: {relative}")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            selected = [json.loads(line) for line in handle if line.strip()]
        for row in selected:
            if row["source_type"] != "platform" or row["record_kind"] not in KINDS:
                raise ValueError("unknown platform evidence type")
            key = row["state"], row["party"]
            if party and key != identity:
                raise ValueError("platform export organization mismatch")
            if not party and (
                key in EXPECTED or row["record_kind"] != "historical_archive_view"
                or row["organization_scope"] != "excluded_national_or_other_party"
            ):
                raise ValueError("outside export cannot admit organization records")
            if row["record_id"] in ids:
                raise ValueError("duplicate exported evidence identity")
            ids.add(row["record_id"])
            if (row["operative_platform_status"] != "unresolved"
                    or row["cycle_applicability"] != "unresolved"
                    or row["analysis_cutoff"] is not None
                    or any(row[key] is not False for key in (
                        "training_admission", "analytical_admission",
                        "adoption_certified", "human_gold"
                    ))):
                raise ValueError("platform evidence cannot carry operative admission")
            if _digest_text(row["extracted_text"]) != row["text_sha256"]:
                raise ValueError("exported evidence text hash mismatch")
        rows.extend(selected)
    outside = sum((r["state"], r["party"]) not in EXPECTED for r in rows)
    if (len(rows) != source["n_evidence_records"]
            or len(rows) != build["counts"]["platform_evidence_views"]
            or outside != source["n_historical_outside_organization_scope"]
            or outside != build["counts"]["platform_outside_organization_views"]
            or Counter(r["record_kind"] for r in rows) != source["record_kind_counts"]):
        raise ValueError("platform export counts do not reconcile")
    return rows


def _original_tables(
    records: list[dict], sources: Sources, out: Path,
) -> tuple[list[dict], list[dict], list[dict]]:
    grouped, ledger, caucus = defaultdict(list), [], []
    for row in records:
        if row["record_kind"] == "frozen_modern_table_view":
            grouped[row["origin"]["path"]].append(row)
        elif row["record_kind"] == "supplementary_caucus":
            if row["availability"] == "retained_text":
                if (row["institution_type"] != "legislative_caucus"
                        or row["retained_record"].get("text") != row["extracted_text"]
                        or not row["extracted_text"]):
                    raise ValueError("caucus original table text/identity mismatch")
                grouped[row["origin"]["path"]].append(row)
            elif (row["availability"] != "registry_only_text_unavailable"
                  or row["extracted_text"] is not None
                  or "text" in row["retained_record"]):
                raise ValueError("registry-only caucus entry cannot supply table text")
            caucus.append(row)
    recovered = []
    for value, views in sorted(grouped.items()):
        origin = views[0]["origin"]
        if any(r["origin"]["sha256"] != origin["sha256"] for r in views):
            raise ValueError("conflicting original table pins")
        ordered = sorted(views, key=lambda r: r["origin"]["record_index"])
        if [r["origin"]["record_index"] for r in ordered] != list(range(len(ordered))):
            raise ValueError("original table row indices are incomplete or duplicated")
        path = sources.optional(value)
        raw = [r["retained_record"] for r in ordered]
        if any(r["extracted_text"] != original.get("text") for r, original in zip(
            ordered, raw, strict=True
        )):
            raise ValueError("original table text differs from exported view")
        if path:
            if sources.pins[str(path)]["sha256"] != origin["sha256"]:
                raise ValueError("original table origin hash mismatch")
            if [_clean(r) for r in pq.read_table(path).to_pylist()] != raw:
                raise ValueError("original table fields differ from retained records")
        elif sources.pins.get(str(sources.path(value)), {}).get("sha256") != origin["sha256"]:
            raise ValueError("missing original table lacks a source-manifest binding")
        relative = Path("original_tables") / sources.path(value).parent.name / Path(value).name
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ValueError("original table snapshot name collision")
        if path:
            target.write_bytes(path.read_bytes())
            fidelity = "identical_original_parquet_bytes_and_fields"
        else:
            pq.write_table(pa.Table.from_pylist(raw), target)
            fidelity = "field_exact_reconstruction_not_original_parquet_bytes"
        if [_clean(r) for r in pq.read_table(target).to_pylist()] != raw:
            raise ValueError("recovered table round-trip changed original fields")
        recovered.append({
            "output": str(relative), "original_path": value,
            "original_sha256": origin["sha256"], "n_rows": len(raw),
            "record_kind": ordered[0]["record_kind"], "fidelity": fidelity,
            "original_fields": list(raw[0]),
        })
        if path:
            parent_manifest = path.parent / "manifest.json"
            if str(parent_manifest) in sources.pins:
                packet = _json(sources.checked(str(parent_manifest)))
                for name in ("platform_gap_report.csv",):
                    if name in packet.get("files", {}):
                        gap = path.parent / name
                        actual = sources.inputs.add(gap, role="original_collection_gap_report")
                        if actual["sha256"] != packet["files"][name]:
                            raise ValueError("original gap report hash mismatch")
                        target.parent.joinpath(name).write_bytes(gap.read_bytes())
        for view, original in zip(ordered, raw, strict=True):
            ledger.append({
                "record_id": view["record_id"], "record_kind": view["record_kind"],
                "state": view["state"], "party": view["party"],
                "original_path": value, "original_sha256": origin["sha256"],
                "original_row_index": view["origin"]["record_index"],
                "recovered_table": str(relative), "original_fields_sha256": _row_hash(original),
                "text_sha256": view["text_sha256"],
                "source_sha256": view["source_sha256"],
                "parent_capture_ids": view.get("parent_capture_ids", []),
                "metadata_year_disposition": view["metadata_year_disposition"],
                "cycle_date_dispositions": view["cycle_date_dispositions"],
            })
    return recovered, ledger, caucus


def _captures(records: list[dict], sources: Sources) -> list[dict]:
    captures, originals = [], {}
    for view in records:
        if view["record_kind"] != "recovery_capture":
            continue
        row, origin = view["retained_record"], view["origin"]
        path = sources.checked(origin["path"])
        if sources.pins[str(path)]["sha256"] != origin["sha256"]:
            raise ValueError("capture origin hash mismatch")
        if str(path) not in originals:
            originals[str(path)] = _jsonl(path)
        if originals[str(path)][origin["record_index"]] != row:
            raise ValueError("capture original fields do not reconcile")
        if (view["capture_id"] != row["capture_id"]
                or (view["state"], view["party"]) != (row["state"], row["party"])
                or view["extracted_text"] != row["extracted_text"]
                or view["text_sha256"] != row["text_sha256"]
                or view["source_sha256"] != row["source_sha256"]):
            raise ValueError("capture source/text join mismatch")
        if row["stored_path"]:
            sources.checked(row["stored_path"])
        validate_capture(row, EXPECTED, typed=True)
        captures.append(view)
    ids = [r["capture_id"] for r in captures]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate original capture identity")
    by_id = {row["capture_id"]: row for row in captures}
    for view in records:
        if view["record_kind"] == "frozen_modern_table_view":
            original = view["retained_record"]
            parents = [by_id[i] for i in view["parent_capture_ids"]]
            if not parents or any(
                (p["state"], p["party"], p["source_sha256"], p["url"])
                != (view["state"], view["party"], original["sha256"], original["url"])
                for p in parents
            ):
                raise ValueError("modern table capture join mismatch")
            exact = any(p["extracted_text"] == original["text"] for p in parents)
            filtered_empty = (original["text"] == "" and original["confirmed"] is False
                              and bool(original["reason"]))
            if not (exact or filtered_empty):
                raise ValueError("modern table cannot substitute alternative extraction text")
        elif view["record_kind"] == "alternative_extraction":
            parents = [by_id[i] for i in view["parent_capture_ids"]]
            if not parents or any(
                (p["state"], p["party"], p["source_sha256"])
                != (view["state"], view["party"], view["source_sha256"])
                or not any(a == view["retained_record"] for a in
                           p["retained_record"]["alternate_extractions"])
                for p in parents
            ) or view["extracted_text"] != view["retained_record"]["extracted_text"]:
                raise ValueError("alternate extraction parent/source join mismatch")
    return captures


def _other_originals(records: list[dict], sources: Sources) -> None:
    originals = {}
    for view in records:
        historical = view["record_kind"] == "historical_archive_view"
        registry = (view["record_kind"] == "supplementary_caucus"
                    and view["availability"] == "registry_only_text_unavailable")
        if not historical and not registry:
            continue
        raw, origin = view["retained_record"], view["origin"]
        if historical and (raw["text"] != view["extracted_text"]
                           or raw.get("sha256") != view["source_sha256"]):
            raise ValueError("historical original source/text fields mismatch")
        path = sources.optional(origin["path"])
        if path is None:
            if sources.pins.get(str(sources.path(origin["path"])), {}).get(
                "sha256"
            ) != origin["sha256"]:
                raise ValueError("missing historical/registry origin is not source-bound")
            continue
        if sources.pins[str(path)]["sha256"] != origin["sha256"]:
            raise ValueError("historical/registry origin hash mismatch")
        if str(path) not in originals:
            originals[str(path)] = (
                [_clean(r) for r in pq.read_table(path).to_pylist()] if historical else
                yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]
            )
        if originals[str(path)][origin["record_index"]] != raw:
            raise ValueError("historical/registry original row fields mismatch")


def _tables(records: list[dict], out: Path) -> dict:
    grouped = defaultdict(list)
    for row in records:
        if (row["state"], row["party"]) in EXPECTED:
            grouped[row["state"], row["party"]].append(row)
    orgs, capture_rows, modern_rows = [], [], []
    for state, party in sorted(EXPECTED):
        selected = grouped[state, party]
        captures = [r for r in selected if r["record_kind"] == "recovery_capture"]
        retained = [r for r in captures if r["retrieval_status"] == "response_retained"]
        modern = [r["retained_record"] for r in selected
                  if r["record_kind"] == "frozen_modern_table_view"]
        accepted = sum(r["retained_record"]["passed_automated_content_filter"] is True
                       for r in captures)
        rejected = sum(r["retained_record"]["passed_automated_content_filter"] is False
                       for r in captures)
        kinds = Counter(r["record_kind"] for r in selected)
        orgs.append({
            "state": state, "party": party, "n_evidence_views": len(selected),
            "n_capture_attempts": len(captures),
            "n_retained_response_captures": len(retained),
            "n_failed_retrieval_attempts": len(captures) - len(retained),
            "n_distinct_response_body_hashes": len({r["source_sha256"] for r in retained}),
            "n_nonempty_standard_text_body_hashes": len({
                r["source_sha256"] for r in retained if (r["extracted_text"] or "").strip()
            }),
            "n_automated_filter_accepted_capture_views": accepted,
            "n_automated_filter_rejected_capture_views": rejected,
            "n_filter_not_applied_capture_views": len(captures) - accepted - rejected,
            "n_original_modern_table_rows": len(modern),
            "n_original_modern_filter_accepted_rows": sum(r["confirmed"] for r in modern),
            "n_original_modern_nonempty_text_rows": sum(bool(r["text"]) for r in modern),
            "n_alternative_extraction_views": kinds["alternative_extraction"],
            "n_historical_archive_views": kinds["historical_archive_view"],
            "n_caucus_registry_only_entries": sum(
                r["record_kind"] == "supplementary_caucus"
                and r["availability"] == "registry_only_text_unavailable" for r in selected
            ),
            "n_caucus_original_table_rows": sum(
                r["record_kind"] == "supplementary_caucus"
                and r["availability"] == "retained_text" for r in selected
            ),
            "capture_status": ("response_retained" if retained else
                               "retrieval_failed" if captures else "not_attempted"),
            "modern_collection_status": _collection_status(modern),
            "operative_platform_status": "unresolved", "cycle_applicability": "unresolved",
            **APPROVALS,
        })
        for view in captures:
            raw = view["retained_record"]
            capture_rows.append({
                "record_id": view["record_id"], "capture_id": raw["capture_id"],
                "state": state, "party": party, "packet": raw["packet"],
                "input_record_index": raw["input_record_index"],
                "retrieval_status": raw["retrieval_status"],
                "source_sha256": raw["source_sha256"], "source_bytes": raw["source_bytes"],
                "text_sha256": raw["text_sha256"], "n_text_chars": len(raw["extracted_text"] or ""),
                "stored_path": raw["stored_path"], "url": raw["url"],
                "passed_automated_content_filter": raw["passed_automated_content_filter"],
                "n_alternate_extractions": len(raw["alternate_extractions"]),
            })
        for original in modern:
            if type(original["confirmed"]) is not bool:
                raise ValueError("original confirmed field is not Boolean")
            modern_rows.append({"state": state, "party": party, **original})
    _write_csv(out / "collection_status.csv", orgs)
    _write_csv(out / "capture_ledger.csv", capture_rows)
    status_counts = [{
        "party": party, "modern_collection_status": status,
        "n_organizations": sum(r["party"] == party and r["modern_collection_status"] == status
                               for r in orgs),
    } for party in ("D", "R") for status in STATUSES]
    _write_csv(out / "modern_collection_status_counts.csv", status_counts)
    year_counts = [{
        "party": party, "metadata_year_band": band, "original_confirmed_filter": confirmed,
        "n_original_rows": sum(
            r["party"] == party and _band(r["year"]) == band and r["confirmed"] is confirmed
            for r in modern_rows
        ),
    } for party in ("D", "R") for band in YEAR_BANDS for confirmed in (False, True)]
    _write_csv(out / "modern_metadata_year_counts.csv", year_counts)
    body_groups = defaultdict(list)
    for view in records:
        if view["source_sha256"] and view["record_kind"] != "historical_archive_view":
            body_groups[view["source_sha256"]].append(view)
    duplicates = [{
        "source_sha256": digest,
        "organizations": [list(key) for key in sorted({(r["state"], r["party"]) for r in views})],
        "n_evidence_views": len(views),
        "record_kind_counts": dict(Counter(r["record_kind"] for r in views)),
        "record_ids": [r["record_id"] for r in views],
        "capture_ids": [r["capture_id"] for r in views if r["record_kind"] == "recovery_capture"],
        "text_sha256s": sorted({r["text_sha256"] for r in views if r["text_sha256"]}),
    } for digest, views in sorted(body_groups.items()) if len(views) > 1]
    _write_jsonl(out / "duplicate_body_groups.jsonl", duplicates)
    return {
        "n_organizations": len(orgs), "n_evidence_views": len(records),
        "n_organization_views": sum(r["n_evidence_views"] for r in orgs),
        "n_outside_organization_views": sum(
            (r["state"], r["party"]) not in EXPECTED for r in records
        ),
        "n_capture_attempts": len(capture_rows),
        "n_retained_response_captures": sum(r["n_retained_response_captures"] for r in orgs),
        "n_failed_retrieval_attempts": sum(r["n_failed_retrieval_attempts"] for r in orgs),
        "n_distinct_retained_capture_body_hashes": len({
            r["source_sha256"] for r in capture_rows if r["source_sha256"]
        }),
        "n_original_modern_rows": len(modern_rows),
        "n_original_modern_filter_accepted_rows": sum(r["confirmed"] for r in modern_rows),
        "n_original_modern_nonempty_text_rows": sum(bool(r["text"]) for r in modern_rows),
        "n_duplicate_body_groups": len(duplicates),
        "record_kind_counts": dict(Counter(r["record_kind"] for r in records)),
        "modern_collection_status_counts": dict(Counter(
            r["modern_collection_status"] for r in orgs
        )),
    }


def _plots(out: Path) -> None:
    cache = out / ".plot-cache"
    cache.mkdir()
    prior_config = os.environ.get("MPLCONFIGDIR")
    os.environ["MPLCONFIGDIR"] = str(cache)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    from state_politics.plotting import theme

    theme.apply()

    def read(name):
        with (out / name).open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def save(fig, name, note):
        text = theme.source_note(
            fig, note + " Observation-only; no operative or analytical approval."
        )
        theme.layout_with_note(fig, text)
        for suffix in ("png", "svg"):
            fig.savefig(out / f"{name}.{suffix}", dpi=180, bbox_inches="tight")
        plt.close(fig)

    counts = read("modern_collection_status_counts.csv")
    labels = ("Filter accepted", "Mixed unresolved", "Fetch failed", "Filter rejected",
              "Not in retained tables")
    fig, ax = plt.subplots(figsize=(12, 5))
    colors = (theme.GREEN, theme.GOLD, theme.ACCENT, theme.BLUE, theme.GRID)
    left = [0, 0]
    for status, label, color in zip(STATUSES, labels, colors, strict=True):
        values = [next(int(r["n_organizations"]) for r in counts
                       if r["party"] == party and r["modern_collection_status"] == status)
                  for party in ("D", "R")]
        ax.barh(["Democratic", "Republican"], values, left=left, color=color, label=label)
        for i, value in enumerate(values):
            if value >= 3:
                ax.text(left[i] + value / 2, i, str(value), ha="center", va="center", fontsize=10)
            left[i] += value
    ax.set(xlim=(0, 50), xlabel="State organizations (50 per party)",
           title="Original collection-table outcomes")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.19), ncol=3, fontsize=9)
    save(fig, "modern_collection_outcomes",
         "Source: retained original table rows, grouped across both source snapshots. "
         "Accepted means the original automated filter; missing rows do not mean no platform.")

    orgs = read("collection_status.csv")
    states = sorted(US_STATES)
    values = [[next(int(r["n_distinct_response_body_hashes"]) for r in orgs
                    if r["state"] == state and r["party"] == party)
               for party in ("D", "R")] for state in states]
    fig, ax = plt.subplots(figsize=(7, 15))
    image = ax.imshow(values, aspect="auto", cmap=ListedColormap([
        theme.tint(theme.BLUE, 1 - i / 100) for i in range(101)
    ]), vmin=0)
    ax.set_xticks([0, 1], ["Democratic", "Republican"])
    ax.set_yticks(range(50), states, fontsize=8)
    ax.set_title("Retained response bodies", pad=15)
    for i, row in enumerate(values):
        for j, value in enumerate(row):
            ax.text(j, i, str(value), ha="center", va="center", fontsize=8,
                    color="white" if value > max(map(max, values)) * 0.65 else theme.TEXT)
    fig.colorbar(image, ax=ax, label="Distinct body hashes within each organization", shrink=0.7)
    save(fig, "retained_response_bodies",
         "Source: all retained capture outcomes. Repeated capture hashes count once per "
         "organization. Bodies may be indexes, failed-page responses or non-platform sources; "
         "they are not platforms or 2023–2024 applicability counts.")

    years = read("modern_metadata_year_counts.csv")
    fig, ax = plt.subplots(figsize=(11, 5))
    positions = list(range(4))
    for offset, party in ((-0.19, "D"), (0.19, "R")):
        values = [sum(int(r["n_original_rows"]) for r in years
                      if r["party"] == party and r["metadata_year_band"] == band)
                  for band in YEAR_BANDS]
        bars = ax.bar([i + offset for i in positions], values, width=0.38,
                      color=theme.party_color(party), label=party)
        ax.bar_label(bars, fontsize=9, padding=3)
    ax.set_xticks(positions, ["Before 2023", "2023–2024\nmetadata only", "After 2024", "Unknown"])
    ax.set(ylabel="Original collection-table rows", title="Recorded years—not adoption dates")
    ax.legend()
    save(fig, "modern_collection_metadata_years",
         "Source: original modern collection-table fields, including failed/rejected rows. "
         "Unknowns and repeated views are retained; historical archive and caucus rows "
         "are excluded.")
    shutil.rmtree(cache)
    if prior_config is None:
        os.environ.pop("MPLCONFIGDIR", None)
    else:
        os.environ["MPLCONFIGDIR"] = prior_config


def _artifacts(out: Path) -> dict:
    files = {}
    for path in sorted(out.rglob("*")):
        if not path.is_file() or path == out / "manifest.json":
            continue
        pin = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        if path.suffix == ".parquet":
            pin["rows"] = pq.read_metadata(path).num_rows
        elif path.suffix == ".jsonl":
            with path.open(encoding="utf-8") as handle:
                pin["rows"] = sum(bool(line.strip()) for line in handle)
        elif path.suffix == ".csv":
            with path.open(newline="", encoding="utf-8") as handle:
                pin["rows"] = sum(1 for _ in csv.DictReader(handle))
        files[str(path.relative_to(out))] = pin
    return files


def verify_packet(out: Path) -> dict:
    """Recheck output hashes, complete chart denominators and original-row round trips."""
    manifest = _json(out / "manifest.json")
    if manifest["status"] != "complete_observation_only" or any(
        manifest[key] is not False for key in APPROVALS
    ):
        raise ValueError("only a completed unapproved packet can be verified")
    if _artifacts(out) != manifest["files"]:
        raise ValueError("recovered packet output hash/count mismatch")
    records = _jsonl(out / "retained_evidence_views.jsonl")
    by_id = {r["record_id"]: r for r in records}
    if len(by_id) != len(records):
        raise ValueError("duplicate recovered evidence record")
    with (out / "collection_status.csv").open(newline="", encoding="utf-8") as handle:
        orgs = list(csv.DictReader(handle))
    counts = manifest["counts"]
    if (len(orgs) != 100 or {(r["state"], r["party"]) for r in orgs} != EXPECTED
            or len(records) != counts["n_evidence_views"]
            or sum(int(r["n_evidence_views"]) for r in orgs) != counts["n_organization_views"]
            or counts["n_organization_views"] + counts["n_outside_organization_views"]
            != len(records)):
        raise ValueError("recovered graph denominators do not reconcile")
    tables = {}
    for row in _jsonl(out / "original_row_ledger.jsonl"):
        name = row["recovered_table"]
        if name not in tables:
            tables[name] = [_clean(r) for r in pq.read_table(out / name).to_pylist()]
        original = tables[name][row["original_row_index"]]
        if (original != by_id[row["record_id"]]["retained_record"]
                or _row_hash(original) != row["original_fields_sha256"]):
            raise ValueError("recovered original fields changed")
    for name, expected in (
        ("modern_collection_status_counts.csv", 100),
        ("modern_metadata_year_counts.csv", counts["n_original_modern_rows"]),
    ):
        with (out / name).open(newline="", encoding="utf-8") as handle:
            values = list(csv.DictReader(handle))
        key = "n_organizations" if "status_counts" in name else "n_original_rows"
        if sum(int(r[key]) for r in values) != expected:
            raise ValueError("chart-data denominator mismatch")
    return {"status": "verified", "n_hashed_outputs": len(manifest["files"]),
            "n_original_rows_round_tripped": len(_jsonl(out / "original_row_ledger.jsonl"))}


def build(
    out: Path, *, preview: Path = ROOT / "data/preview-cycle-evidence-v7",
    root: Path = ROOT, plots: bool = True,
) -> dict:
    """Build a new exclusive packet. A failed attempt stays explicitly incomplete."""
    out, preview = out.absolute(), preview.absolute()
    if out.resolve() != out or preview.resolve() != preview:
        raise ValueError("linked output/preview paths are not supported")
    out.mkdir(parents=True, exist_ok=False)
    inputs = Inputs()
    manifest = {
        "schema": "recovered_platform_graph_inputs_v1", "status": "incomplete",
        "started_at": utc_now_iso(), "analysis_cutoff": None,
        "operative_platform_status": "unresolved", "cycle_applicability": "unresolved",
        "scientific_certification": "not_performed", **APPROVALS,
        "limitations": LIMITATIONS,
    }

    def seal():
        manifest["inputs"] = list(inputs.pins.values())
        manifest["files"] = _artifacts(out)
        _dump(out / "manifest.json", manifest)

    seal()
    try:
        build_path = preview / "downloads/build_manifest.json"
        source_path = preview / "downloads/platform_source_manifest.json"
        inputs.add(build_path, role="retained_preview_export_bindings")
        original_build = _json(build_path)
        source_pin = inputs.add(source_path, role="retained_platform_source_manifest")
        if source_pin["sha256"] != original_build["inputs"]["platform"]["manifest.json"]:
            raise ValueError("platform source manifest does not match preview binding")
        source = _json(source_path)
        if (source["schema"] != "platform_study_evidence_v1"
                or source["status"] != "complete_evidence_inventory_not_scientific_admission"
                or source["files"]["records.jsonl"]
                != original_build["inputs"]["platform"]["records.jsonl"]):
            raise ValueError("incompatible platform provenance manifest")
        sources = Sources(root, source, inputs)
        records = _exports(preview, original_build, source, inputs)
        captures = _captures(records, sources)
        _other_originals(records, sources)
        recovered, ledger, caucus = _original_tables(records, sources, out)
        _write_jsonl(out / "retained_evidence_views.jsonl", records)
        _write_jsonl(out / "original_row_ledger.jsonl", ledger)
        _write_jsonl(out / "caucus_observations.jsonl", caucus)
        counts = _tables(records, out)
        if (len(captures) != source["n_recovery_captures"]
                or counts["n_retained_response_captures"] != source["n_retained_response_captures"]
                or counts["n_failed_retrieval_attempts"] != source["n_failed_retrieval_attempts"]):
            raise ValueError("capture totals differ from retained source inventory")
        producer = inputs.add(Path(__file__), role="graph_input_recovery_producer")
        (out / "producer.py").write_bytes(Path(producer["path"]).read_bytes())
        if plots:
            theme_pin = inputs.add(Path(__file__).resolve().parents[1] / "plotting/theme.py",
                                   role="existing_plotting_theme")
            (out / "plotting_theme.py").write_bytes(Path(theme_pin["path"]).read_bytes())
            _plots(out)
        inputs.stable()
        manifest.update(
            status="complete_observation_only", completed_at=utc_now_iso(),
            counts=counts, recovered_original_tables=recovered,
            n_caucus_original_rows=sum(
                r["record_kind"] == "supplementary_caucus" for r in ledger
            ),
            n_caucus_registry_only_entries=sum(
                r["availability"] == "registry_only_text_unavailable" for r in caucus
            ),
            graph_inputs=[
                "collection_status.csv", "modern_collection_status_counts.csv",
                "modern_metadata_year_counts.csv",
            ],
            canonical_tables_modified=False, source_bytes_modified=False,
            input_stability_verified=True,
        )
        seal()
        result = verify_packet(out)
        inputs.stable()
        manifest["verification"] = result
        seal()
        return manifest
    except Exception as error:
        manifest.update(status="incomplete", error_type=type(error).__name__,
                        error=str(error), failed_at=utc_now_iso())
        seal()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--preview", type=Path, default=ROOT / "data/preview-cycle-evidence-v7")
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    result = (verify_packet(args.out) if args.verify_only else
              build(args.out, preview=args.preview, plots=not args.no_plots))
    print(json.dumps({key: result[key] for key in (
        "status", "counts", "verification", "n_caucus_original_rows",
        "n_caucus_registry_only_entries", "n_hashed_outputs"
    ) if key in result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

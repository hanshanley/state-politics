"""Reconcile bounded native-list evidence into one unapproved all-state catalog."""

from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
from collections import defaultdict
from pathlib import Path

import pyarrow.csv as arrow_csv
import yaml

from state_politics import site_evidence as site
from state_politics.bills.study_matrix import read_tracker
from state_politics.bills.study_window import _snapshot
from state_politics.provenance import sha256_file, utc_now_iso

STATUS = "complete_all_state_native_inventory_catalog_not_scientific_admission"
FLAGS = ("scientific_approval", "model_approval", "analytical_admission", "full_text_certified")


def _require(condition, message):
    if not condition:
        raise ValueError(f"incompatible native inventory catalog: {message}")


def _json(path):
    return json.loads(path.read_bytes())


def _rows(path):
    with path.open("rb") as handle:
        for raw in handle:
            if raw.strip():
                yield json.loads(raw)


def _root(value):
    path = Path(value)
    if not path.is_absolute():
        path = site.ROOT / path
    _require(path.is_dir() and not path.is_symlink() and path.resolve() == path,
             "explicit nonlinked source packet required")
    _require(path.is_relative_to(site.ROOT / "data"), "source packet outside project data")
    return path


def _bind(directory):
    manifest_path = directory / "manifest.json"
    _require(manifest_path.is_file() and manifest_path.resolve() == manifest_path,
             "missing or linked source manifest")
    manifest = _json(manifest_path)
    _require(all(manifest.get(flag) is False for flag in FLAGS),
             "source scientific/model/full-text gates must remain false")
    files = {"manifest.json": manifest_path}
    for name, entry in manifest["files"].items():
        _require(
            isinstance(name, str) and bool(name) and not name.startswith("/")
            and "\\" not in name and all(part not in {"", ".", ".."} for part in name.split("/")),
            "unsafe source artifact path",
        )
        path = directory / name
        expected = entry if isinstance(entry, str) else entry["sha256"]
        _require(path.is_file() and path.resolve() == path
                 and sha256_file(path) == expected, f"source artifact binding: {name}")
        files[name] = path
    return manifest, files


def reconcile_records(records, state_reports, effective_states):
    """Count exact native IDs, not repeated prefix observations or filename candidates."""
    grouped, seen = defaultdict(list), set()
    for row in records:
        _require(row.get("state") in site.STATES, "unknown record state")
        _require(all(row.get(flag) is False for flag in FLAGS), "approved source record")
        _require(isinstance(row.get("source_record_id"), str) and bool(row["source_record_id"]),
                 "missing physical source record ID")
        _require(row["source_record_id"] not in seen, "duplicate physical source record")
        seen.add(row["source_record_id"])
        _require(isinstance(row.get("native_id"), str) and bool(row["native_id"]),
                 "missing native identity")
        grouped[row["state"]].append(row)
    result = {}
    for state in effective_states:
        report = state_reports[state]
        rows = grouped[state]
        unique = len({row["native_id"] for row in rows})
        _require(
            report["observed_native_records"] == len(rows)
            and report["observed_native_identities"] == unique,
            f"exact observed record/identity counts: {state}",
        )
        _require(report["status"] != "outside_this_bounded_batch", "unsupplied effective state")
        _require(all(report.get(flag) is False for flag in FLAGS), "approved state report")
        result[state] = (rows, report, unique)
    return result


def build_catalog(registry: Path, metadata: Path, tracker: Path, output: Path):
    if output.exists():
        raise FileExistsError(f"refusing overwrite: {output}")
    config = yaml.safe_load(registry.read_text(encoding="utf-8"))
    _require(config.get("schema_version") == 1 and bool(config.get("packets")),
             "nonempty reviewed packet registry")
    _, metadata_pins = site._bind_bundle(metadata, {"state_matrix.csv", "report.json"})
    baseline = arrow_csv.read_csv(metadata / "state_matrix.csv").to_pylist()
    _require(len(baseline) == 50 and {row["state"] for row in baseline} == site.STATES,
             "exact all-state metadata baseline")
    current = read_tracker(tracker).set_index("state").to_dict("index")
    paths = {
        "registry": registry, "tracker": tracker, "producer": Path(__file__),
        "metadata_manifest": metadata / "manifest.json",
        "metadata_state_matrix": metadata / "state_matrix.csv",
        "style": site.ROOT / "web/preview.css",
    }
    helpers = [
        Path(site.__file__), Path(__file__).with_name("study_matrix.py"),
        Path(__file__).with_name("study_window.py"),
        Path(site.__file__).with_name("provenance.py"),
    ]
    paths.update({f"shared_producer_{path.stem}": path for path in helpers})
    selected, bound, all_inputs, seen_packets = {}, {}, {}, set()
    for entry in config["packets"]:
        key = entry["packet_id"]
        _require(
            isinstance(key, str) and key and key not in seen_packets
            and key.replace("-", "").replace("_", "").isalnum(),
            "unique simple packet ID",
        )
        seen_packets.add(key)
        states = entry["effective_states"]
        _require(
            isinstance(states, list) and bool(states) and len(set(states)) == len(states)
            and set(states) <= site.STATES and not (set(states) & selected.keys()),
            "explicit nonoverlapping effective states; never sum superseded packets",
        )
        root = _root(entry["directory"])
        manifest, files = _bind(root)
        _require(sha256_file(files["manifest.json"]) == entry["manifest_sha256"],
                 "reviewed processed manifest pin")
        _require({"report.json", "native_source_records.jsonl"} <= files.keys(),
                 "complete report and original native records required")
        report = _json(files["report.json"])
        _require(set(report["states"]) == site.STATES, "all-state source report required")
        reconciled = reconcile_records(
            _rows(files["native_source_records.jsonl"]), report["states"], states,
        )
        raw_roots = {}
        raw_bound = False
        source_manifest_hashes = {
            value["sha256"] for value in manifest["inputs"].values()
            if isinstance(value, dict) and "sha256" in value
            and Path(value.get("path", "")).name == "manifest.json"
        }
        for index, raw_entry in enumerate(entry["raw_archives"]):
            raw_root = _root(raw_entry["directory"])
            raw_manifest, raw_files = _bind(raw_root)
            raw_sha = sha256_file(raw_files["manifest.json"])
            _require(raw_sha == raw_entry["manifest_sha256"], "reviewed raw manifest pin")
            if raw_sha in source_manifest_hashes:
                raw_bound = True
            raw_roots[f"raw-{index}"] = (raw_root, raw_manifest, raw_files)
        _require(raw_bound, "processed source must bind a copied raw archive")
        bound[key] = (root, manifest, files, raw_roots, states)
        for name, path in files.items():
            all_inputs[f"{key}/processed/{name}"] = path
        for raw_key, (_, _, raw_files) in raw_roots.items():
            for name, path in raw_files.items():
                all_inputs[f"{key}/{raw_key}/{name}"] = path
        for state, (rows, state_report, unique) in reconciled.items():
            selected[state] = (key, rows, state_report, unique)
    paths.update(all_inputs)
    before = {key: _snapshot(path) for key, path in paths.items()}
    output.mkdir(parents=True)
    for name, path in all_inputs.items():
        destination = output / "packets" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    shutil.copyfile(registry, output / "reviewed_registry.yml")
    shutil.copyfile(Path(__file__), output / "producer.py")
    shutil.copyfile(paths["style"], output / "preview.css")
    (output / "producers").mkdir()
    for path in helpers:
        shutil.copyfile(path, output / "producers" / path.name)
    summary = []
    with (output / "effective_native_records.jsonl").open(
        "w", encoding="utf-8", newline="\n",
    ) as records:
        for base in sorted(baseline, key=lambda row: row["state"]):
            state = base["state"]
            data = selected.get(state)
            if data:
                packet, rows, state_report, unique = data
                for row in rows:
                    records.write(json.dumps({
                        "source_packet": packet, "original_record": row,
                        "canonical_join_certified": False, "analytical_admission": False,
                    }, ensure_ascii=False, allow_nan=False) + "\n")
            else:
                packet, rows, state_report, unique = None, None, None, None
            summary.append({
                "state": state, "legislative_status": current[state]["legislative_status"],
                "remaining_scope": current[state]["remaining_scope"],
                "calendar_candidate_contexts_unchanged": (
                    base["n_cycle_evidence_candidate_contexts"]
                ),
                "effective_source_packet": packet,
                "new_inventory_status": state_report["status"] if state_report
                else "not_registered_in_this_channel_not_zero_activity",
                "native_source_record_observations": len(rows) if rows is not None else None,
                "distinct_native_source_identity_observations": unique,
                "duplicate_identity_observations_preserved": (
                    len(rows) - unique if rows is not None else None
                ),
                "native_introduced_universe": None, "new_original_texts_from_this_channel": (
                    state_report["new_full_original_documents"] if state_report else None
                ), "zero_activity_inferred": False, "analytical_admission": False,
            })
    with (output / "state_inventory_matrix.csv").open(
        "w", encoding="utf-8", newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    catalog = {
        "status": STATUS, "completed_at": utc_now_iso(), "states_accounted_for": 50,
        "states_with_registered_observed_or_blocked_scope": sorted(selected),
        "effective_native_record_observations": sum(
            len(value[1]) for value in selected.values()
        ), "effective_native_identity_observations": sum(
            value[3] for value in selected.values()
        ), "calendar_candidates_unchanged": sum(
            row["calendar_candidate_contexts_unchanged"] for row in summary
        ),
        "metadata_manifest_sha256": metadata_pins["manifest.json"],
        "source_packets": {
            key: {"effective_states": states, "original_manifest": manifest,
                  "raw_capture_integrity_exceptions": {
                      raw_key: raw_manifest.get("capture_integrity_exceptions", [])
                      for raw_key, (_, raw_manifest, _) in raw_roots.items()
                  }}
            for key, (_, manifest, _, raw_roots, states) in bound.items()
        },
        "publication": False, "model_input_approved": False,
        **dict.fromkeys(FLAGS, False),
        "limitations": (
            "Observed publisher metadata and raw captures, not introduced-bill/full-text "
            "completeness, certified joins, zero activity or scientific admission. "
            "Explicit state selections avoid double-counting superseded prefixes; original "
            "packets, raw bytes, filename candidates and all exceptions remain unchanged."
        ),
    }
    (output / "report.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    links = "".join(
        f'<li>{html.escape(key)}: <a download href="packets/{key}/processed/report.json">'
        'complete original report</a> · '
        f'<a download href="packets/{key}/processed/native_source_records.jsonl">'
        'every original source record</a></li>' for key in bound
    )
    table = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row[key]))}</td>" for key in (
            "state", "legislative_status", "new_inventory_status",
            "native_source_record_observations", "distinct_native_source_identity_observations",
        )) + "</tr>" for row in summary
    )
    (output / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Unpublished all-state source inventory</title>'
        '<link rel="stylesheet" href="preview.css"><main>'
        '<p class="eyebrow">Local research / unpublished</p><h1>Native-source inventory</h1>'
        f'<p>{html.escape(catalog["limitations"])}</p><ul>{links}</ul>'
        '<p><a download href="effective_native_records.jsonl">All effective complete source '
        'records</a> · <a download href="state_inventory_matrix.csv">All 50 state rows</a> · '
        '<a download href="manifest.json">Every retained packet/raw-file download path and hash'
        '</a></p><div class="table-wrap"><table>'
        '<caption>None means unsupplied, not zero activity.</caption>'
        '<thead><tr><th>State</th><th>Tracker status</th><th>Observed source scope</th>'
        '<th>Records</th><th>Native identities</th></tr></thead>'
        f'<tbody>{table}</tbody></table></div></main></html>\n', encoding="utf-8",
    )
    after = {key: _snapshot(path) for key, path in paths.items()}
    _require(before == after, "source input changed during catalog build")
    artifacts = {
        path.relative_to(output).as_posix(): {
            "sha256": sha256_file(path), "bytes": path.stat().st_size,
        } for path in sorted(output.rglob("*")) if path.is_file()
    }
    manifest = {
        "schema_version": 1, **catalog, "inputs_before": before, "inputs_after": after,
        "inputs_unchanged": True, "artifacts": artifacts,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--tracker", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    result = build_catalog(args.registry, args.metadata, args.tracker, args.out)
    print(json.dumps({key: result[key] for key in (
        "status", "effective_native_record_observations", "effective_native_identity_observations",
        "states_accounted_for",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

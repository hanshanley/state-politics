"""Add explicit source-coded filing evidence without replacing introduction dates."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..provenance import sha256_file, utc_now_iso
from .study_window import _STATES, END, START, _snapshot, source_event_disposition

_STATUS = "complete_source_filing_inventory_not_native_or_analytical_certification"
_FIELDS = [
    "n_filing_actions",
    "n_origin_filing_actions",
    "origin_filing_action_ids",
    "source_filing_date",
    "filing_window_disposition",
]
_GROUPS = [
    "state",
    "session_identifier",
    "originating_chamber",
    "classification",
    "filing_window_disposition",
]


def build_inventory(
    window_dir: Path,
    actions_path: Path,
    out_dir: Path,
    *,
    matrix_dir: Path,
) -> dict:
    """Preserve all prior ledger fields and every raw filing-class action in new outputs."""
    if out_dir.exists():
        raise FileExistsError(out_dir)
    paths = {
        "window_manifest": window_dir / "manifest.json",
        "introduction_ledger": window_dir / "bill_window_ledger.csv",
        "actions": actions_path,
        "matrix_manifest": matrix_dir / "manifest.json",
        "matrix": matrix_dir / "state_matrix.csv",
        "producer": Path(__file__),
        "study_window": Path(__file__).with_name("study_window.py"),
        "outcomes": Path(__file__).with_name("outcomes.py"),
        "provenance": Path(__file__).parent.parent / "provenance.py",
    }
    before = {key: _snapshot(path) for key, path in paths.items()}
    source_manifest = json.loads(paths["window_manifest"].read_text(encoding="utf-8"))
    matrix_manifest = json.loads(paths["matrix_manifest"].read_text(encoding="utf-8"))
    if (
        source_manifest["status"] != "complete_source_window_inventory_not_analytical_admission"
        or (source_manifest["window_start"], source_manifest["window_end"]) != (START, END)
        or source_manifest["inputs"]["bill_actions.parquet"]["sha256"]
        != before["actions"]["sha256"]
        or source_manifest["artifacts"]["bill_window_ledger.csv"]["sha256"]
        != before["introduction_ledger"]["sha256"]
    ):
        raise ValueError("completed introduction ledger and original bound action table required")
    if (
        matrix_manifest["status"]
        not in {
            "complete_all_state_triage_not_native_coverage_or_analytical_admission",
            "complete_supplied_native_overlap_not_native_census_or_analytical_admission",
        }
        or matrix_manifest["artifacts"]["state_matrix.csv"]["sha256"] != before["matrix"]["sha256"]
        or matrix_manifest["inputs"]["ledger"]["sha256"] != before["introduction_ledger"]["sha256"]
    ):
        raise ValueError("completed shared matrix must bind the same introduction ledger")
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = out_dir / "manifest.json"
    manifest = {
        "schema_version": 1,
        "status": "incomplete",
        "started_at": utc_now_iso(),
        "window_start": START,
        "window_end": END,
        "inputs": before,
        "new_requests": 0,
        "analytical_admission": False,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    source = pq.ParquetFile(actions_path)
    actions = defaultdict(list)
    seen_actions = set()
    with pq.ParquetWriter(out_dir / "source_filing_actions.parquet", source.schema_arrow) as writer:
        for batch in source.iter_batches(batch_size=65536):
            selected = batch.filter(
                pc.match_substring_regex(
                    batch.column("classification"),
                    r"(^|\|)filing(\||$)",
                )
            )
            writer.write_batch(selected)
            for action in selected.to_pylist():
                action_id = action["action_id"]
                if not action_id or action_id in seen_actions or not action["bill_id"]:
                    raise ValueError("filing actions require unique IDs and nonempty bill IDs")
                seen_actions.add(action_id)
                actions[action["bill_id"]].append(action)
    counts = {state: Counter() for state in sorted(_STATES)}
    groups = Counter()
    seen_bills = set()
    with (
        paths["introduction_ledger"].open(encoding="utf-8", newline="") as source_handle,
        (out_dir / "bill_filing_evidence.csv").open("x", encoding="utf-8", newline="") as target,
    ):
        reader = csv.DictReader(source_handle)
        writer = csv.DictWriter(target, fieldnames=[*reader.fieldnames, *_FIELDS])
        writer.writeheader()
        for row in reader:
            bill_id, state = row["bill_id"], row["state"]
            if not bill_id or bill_id in seen_bills or state not in _STATES:
                raise ValueError("ledger requires unique bill IDs and known states")
            seen_bills.add(bill_id)
            result = source_event_disposition(
                row,
                actions.pop(bill_id, []),
                event_class="filing",
            )
            result["filing_window_disposition"] = result.pop("window_disposition")
            writer.writerow({**row, **result})
            count = counts[state]
            count["n_contexts"] += 1
            count[result["filing_window_disposition"]] += 1
            intro = row["window_disposition"] == "source_introduction_in_window"
            filing = result["filing_window_disposition"] == "source_filing_in_window"
            count["n_introduction_in_window"] += int(intro)
            count["n_filing_or_introduction_in_window"] += int(intro or filing)
            count["n_both_in_window"] += int(intro and filing)
            if result["filing_window_disposition"] == "source_filing_in_window":
                count["n_filing_in_window"] += 1
                if not row["source_introduction_date"]:
                    count["n_filing_in_window_without_introduction_date"] += 1
                elif row["window_disposition"] != "source_introduction_in_window":
                    count["n_filing_in_window_introduction_outside"] += 1
            joined = {**row, **result}
            groups[tuple(joined[key] for key in _GROUPS)] += 1
    if actions:
        raise ValueError("filing actions reference bills absent from the bound ledger")
    matrix = pd.read_csv(paths["matrix"], keep_default_na=False)
    if (
        matrix["state"].duplicated().any()
        or set(matrix["state"]) != _STATES
        or any(
            row["n_source_in_window"] != counts[row["state"]]["n_introduction_in_window"]
            for row in matrix.to_dict("records")
        )
    ):
        raise ValueError("matrix must exactly account for all 50 state introduction counts")
    for name in (
        "n_filing_in_window",
        "n_filing_in_window_without_introduction_date",
        "n_filing_in_window_introduction_outside",
        "n_filing_or_introduction_in_window",
        "n_both_in_window",
    ):
        matrix[name] = matrix["state"].map(lambda state, name=name: counts[state][name])
    matrix.to_csv(out_dir / "state_matrix.csv", index=False)
    with (out_dir / "state_session_filing_counts.csv").open(
        "x",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=[*_GROUPS, "n_contexts"])
        writer.writeheader()
        for key, count in sorted(groups.items()):
            writer.writerow({**dict(zip(_GROUPS, key, strict=True)), "n_contexts": count})
    result = {
        "status": _STATUS,
        "n_contexts": len(seen_bills),
        "n_source_filing_actions": len(seen_actions),
        "n_filing_in_window": sum(c["n_filing_in_window"] for c in counts.values()),
        "n_filing_in_window_without_introduction_date": sum(
            c["n_filing_in_window_without_introduction_date"] for c in counts.values()
        ),
        "n_filing_in_window_introduction_outside": sum(
            c["n_filing_in_window_introduction_outside"] for c in counts.values()
        ),
        "n_filing_or_introduction_in_window": sum(
            c["n_filing_or_introduction_in_window"] for c in counts.values()
        ),
        "states_without_observed_filing_or_introduction": [
            state
            for state, count in counts.items()
            if not count["n_filing_or_introduction_in_window"]
        ],
        "states": [{"state": state, **count} for state, count in counts.items()],
        "limitations": [
            "Filing and introduction are distinct source-coded events, not interchangeable dates.",
            "Exactly one originating filing event is required; repeated events remain unresolved.",
            "No first-reading, unclassified description, URL or session-year fallback is used.",
            "Introduction fields unchanged; native validation and party timing remain open.",
            "No native census, policy labels, classifier or analytical admission follows.",
        ],
        "new_requests": 0,
        "analytical_admission": False,
    }
    (out_dir / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if {key: _snapshot(path) for key, path in paths.items()} != before:
        raise ValueError("filing inventory inputs changed; output remains incomplete")
    manifest.update(
        status=_STATUS,
        completed_at=utc_now_iso(),
        inputs_unchanged=True,
        artifacts={
            path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in sorted(out_dir.iterdir())
            if path.name != "manifest.json"
        },
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-dir", required=True, type=Path)
    parser.add_argument("--actions", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--matrix-dir", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            build_inventory(
                args.window_dir,
                args.actions,
                args.out_dir,
                matrix_dir=args.matrix_dir,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

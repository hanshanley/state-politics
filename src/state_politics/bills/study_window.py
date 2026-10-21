"""Inventory source introduction evidence for 2023-2024 without admitting analytical rows."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..provenance import sha256_file, utc_now_iso
from .openstates_dump import STATE_CODES
from .outcomes import _event_calendar_date

START = "2023-01-01"
END = "2024-12-31"
_STATES = frozenset(state.upper() for state in STATE_CODES)
_BILL_COLUMNS = [
    "bill_id",
    "state",
    "identifier",
    "legislative_session_id",
    "session_identifier",
    "session_name",
    "session_start_date",
    "session_end_date",
    "from_organization_id",
    "originating_chamber",
    "classification",
    "first_action_date",
]
_LEDGER_COLUMNS = [
    *_BILL_COLUMNS,
    "n_introduction_actions",
    "n_origin_introduction_actions",
    "origin_introduction_action_ids",
    "source_introduction_date",
    "window_disposition",
]
_GROUP_COLUMNS = [
    "state",
    "legislative_session_id",
    "session_identifier",
    "session_name",
    "session_start_date",
    "session_end_date",
    "originating_chamber",
    "classification",
    "window_disposition",
]


def introduction_disposition(bill: dict, actions: list[dict]) -> dict:
    """Require one source-coded introduction in the originating organization and chamber."""
    for action in actions:
        if (
            action["bill_id"] != bill["bill_id"]
            or action["state"] != bill["state"]
            or "introduction" not in (action["classification"] or "").split("|")
        ):
            raise ValueError("introduction evidence does not match its bill/classification")
    origin = bill["from_organization_id"]
    matched = [action for action in actions if origin and action["organization_id"] == origin]
    observed_date = None
    if not actions:
        disposition = "no_source_introduction_action"
    elif not origin:
        disposition = "missing_originating_organization"
    elif not matched:
        disposition = "no_origin_introduction_action"
    elif len(matched) != 1:
        disposition = "multiple_origin_introduction_actions"
    elif bill["originating_chamber"] not in {"upper", "lower", "legislature"}:
        disposition = "unknown_originating_chamber"
    elif matched[0]["chamber"] != bill["originating_chamber"]:
        disposition = "origin_introduction_chamber_unresolved"
    elif matched[0]["date"] is None or matched[0]["date"] == "":
        disposition = "missing_origin_introduction_date"
    else:
        raw_date = matched[0]["date"]
        try:
            if not isinstance(raw_date, str) or not raw_date:
                raise ValueError("missing introduction date")
            observed_date = _event_calendar_date(raw_date).isoformat()
        except ValueError:
            disposition = "invalid_origin_introduction_date"
        else:
            disposition = (
                "source_introduction_before_window"
                if observed_date < START
                else "source_introduction_after_window"
                if observed_date > END
                else "source_introduction_in_window"
            )
    return {
        "n_introduction_actions": len(actions),
        "n_origin_introduction_actions": len(matched),
        "origin_introduction_action_ids": json.dumps([a["action_id"] for a in matched]),
        "source_introduction_date": observed_date,
        "window_disposition": disposition,
    }


def _snapshot(path: Path) -> dict:
    def stat_fields():
        stat = path.stat()
        return {
            key: getattr(stat, f"st_{key}")
            for key in ("size", "mtime_ns", "ctime_ns", "dev", "ino", "nlink", "mode")
        }

    before = stat_fields()
    digest = sha256_file(path)
    if stat_fields() != before:
        raise ValueError(f"input changed while hashing: {path}")
    return {"path": str(path.resolve()), "sha256": digest, **before}


def build_inventory(data_dir: Path, out_dir: Path) -> dict:
    """Write a new, complete-record ledger; existing extraction files are read-only inputs."""
    paths = {
        name: data_dir / name
        for name in ("bills.parquet", "bill_actions.parquet", "bill_extraction_manifest.json")
    }
    paths.update(
        {
            "study_window.py": Path(__file__),
            "outcomes.py": Path(__file__).with_name("outcomes.py"),
            "openstates_dump.py": Path(__file__).with_name("openstates_dump.py"),
            "provenance.py": Path(__file__).parent.parent / "provenance.py",
        }
    )
    before = {name: _snapshot(path) for name, path in paths.items()}
    extraction = json.loads(paths["bill_extraction_manifest.json"].read_text(encoding="utf-8"))
    if extraction["status"] != "complete_extraction_not_source_certification":
        raise ValueError("a completed extraction manifest is required")
    for name in ("bills.parquet", "bill_actions.parquet"):
        expected = extraction["artifacts"][name]
        if (
            expected["sha256"] != before[name]["sha256"]
            or expected["rows"] != pq.ParquetFile(paths[name]).metadata.num_rows
        ):
            raise ValueError(f"extraction binding mismatch: {name}")

    out_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = out_dir / "manifest.json"
    manifest = {
        "schema_version": 1,
        "status": "incomplete",
        "started_at": utc_now_iso(),
        "window_start": START,
        "window_end": END,
        "inputs": before,
        "analytical_admission": False,
        "scientific_certification": "not_performed",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    introductions = defaultdict(list)
    action_ids = set()
    source = pq.ParquetFile(paths["bill_actions.parquet"])
    with pq.ParquetWriter(
        out_dir / "source_introduction_actions.parquet", source.schema_arrow
    ) as writer:
        for batch in source.iter_batches(batch_size=65536):
            selected = batch.filter(
                pc.match_substring_regex(
                    batch.column("classification"),
                    r"(^|\|)introduction(\||$)",
                )
            )
            writer.write_batch(selected)
            for action in selected.to_pylist():
                action_id = action["action_id"]
                if not isinstance(action_id, str) or not action_id or action_id in action_ids:
                    raise ValueError("source introduction action IDs must be nonempty and unique")
                if not isinstance(action["bill_id"], str) or not action["bill_id"]:
                    raise ValueError("source introduction action lacks bill ID")
                action_ids.add(action_id)
                introductions[action["bill_id"]].append(action)

    counts = Counter()
    groups = Counter()
    states = defaultdict(Counter)
    seen = set()
    with (out_dir / "bill_window_ledger.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_LEDGER_COLUMNS)
        writer.writeheader()
        for batch in pq.ParquetFile(paths["bills.parquet"]).iter_batches(
            batch_size=16384,
            columns=_BILL_COLUMNS,
        ):
            for bill in batch.to_pylist():
                bill_id = bill["bill_id"]
                if not isinstance(bill_id, str) or not bill_id or bill_id in seen:
                    raise ValueError("source bill IDs must be nonempty and unique")
                if bill["state"] not in _STATES:
                    raise ValueError(f"unknown source bill state: {bill['state']}")
                seen.add(bill_id)
                row = {
                    **bill,
                    **introduction_disposition(
                        bill,
                        introductions.pop(bill_id, []),
                    ),
                }
                writer.writerow(row)
                disposition = row["window_disposition"]
                counts[disposition] += 1
                states[row["state"]][disposition] += 1
                groups[tuple(row[key] for key in _GROUP_COLUMNS)] += 1
    if introductions:
        raise ValueError("source introduction actions reference bills absent from extraction")
    if len(seen) != extraction["artifacts"]["bills.parquet"]["rows"]:
        raise ValueError("bill ledger does not account for every extracted row")
    with (out_dir / "state_session_counts.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*_GROUP_COLUMNS, "n_source_contexts"])
        writer.writeheader()
        for key, count in sorted(
            groups.items(),
            key=lambda item: tuple("" if value is None else value for value in item[0]),
        ):
            writer.writerow(
                {**dict(zip(_GROUP_COLUMNS, key, strict=True)), "n_source_contexts": count}
            )
    report = {
        "window_start": START,
        "window_end": END,
        "n_source_contexts": len(seen),
        "n_source_introduction_actions": len(action_ids),
        "disposition_counts": dict(sorted(counts.items())),
        "states": [
            {
                "state": state,
                "n_source_contexts": sum(states[state].values()),
                "disposition_counts": dict(sorted(states[state].items())),
            }
            for state in sorted(_STATES)
        ],
        "analytical_admission": False,
        "limitations": [
            "Source-coded introduction actions are not independently verified native dates.",
            "First/latest action dates and session names/years never supply missing introductions.",
            "Multiple origin introductions remain unresolved, even on the same calendar day.",
            "Other-chamber introductions remain evidence, not new originating filings.",
            "Native session completeness, prefiling/version eligibility and party timing are open.",
            "Measure types and native session identifiers remain separate; no platform selection.",
            "Date observations include proposed bills/draft requests, not just eligible measures.",
            "This ledger does not filter or certify downstream analytical outputs.",
        ],
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    after = {name: _snapshot(path) for name, path in paths.items()}
    if before != after:
        raise ValueError("inventory inputs changed; output remains incomplete")
    manifest.update(
        {
            "status": "complete_source_window_inventory_not_analytical_admission",
            "completed_at": utc_now_iso(),
            "inputs_unchanged": True,
            "artifacts": {
                name: {
                    "sha256": sha256_file(out_dir / name),
                    "bytes": (out_dir / name).stat().st_size,
                }
                for name in (
                    "bill_window_ledger.csv",
                    "source_introduction_actions.parquet",
                    "state_session_counts.csv",
                    "report.json",
                )
            },
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--out-dir", type=Path, required=True, help="new output directory only")
    args = parser.parse_args(argv)
    report = build_inventory(args.data_dir, args.out_dir)
    print(
        json.dumps(
            {
                "n_source_contexts": report["n_source_contexts"],
                "disposition_counts": report["disposition_counts"],
                "analytical_admission": False,
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

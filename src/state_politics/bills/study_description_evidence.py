"""Offline, literal description-stated evidence; never source-coded or native certification."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..provenance import sha256_file, utc_now_iso
from .outcomes import _event_calendar_date
from .study_window import END, START, _snapshot

CHANNEL = "description_stated_not_coded_not_native_certified"
STATES = ("MA", "ME", "NY")
STATUS = "complete_literal_description_inventory_not_analytical_admission"
# Reviewed complete retained descriptions and their bill/action joins, not keyword matches.
LITERALS = {("NY", "INTRODUCED"): "introduction", ("MA", "Petition filed"): "petition_filing"}
KINDS = ("introduction", "petition_filing")


def explicit_date(value: str | None) -> tuple[str | None, str]:
    """Validate the entire value, retaining its source-local calendar date."""
    if value is None or value == "":
        return None, "missing_date"
    try:
        day = _event_calendar_date(value).isoformat()
    except (TypeError, ValueError):
        return None, "invalid_date"
    return day, "before_window" if day < START else "after_window" if day > END else "in_window"


def _uncoded(action: dict) -> bool:
    return not {"introduction", "filing"}.intersection(
        (action["classification"] or "").split("|")
    )


def origin_status(bill: dict, action: dict) -> str:
    if not bill["from_organization_id"]:
        return "missing_originating_organization"
    if bill["from_organization_id"] != action["organization_id"]:
        return "other_or_missing_organization"
    if bill["originating_chamber"] not in {"upper", "lower", "legislature"}:
        return "unknown_originating_chamber"
    if bill["originating_chamber"] != action["chamber"]:
        return "origin_chamber_unresolved"
    return "origin_identity_matches"


def description_disposition(bill: dict, actions: list[dict], *, kind: str) -> dict:
    """Keep exact literals and unresolved multiple/other-chamber events without recoding."""
    if kind not in KINDS:
        raise ValueError("unknown description-stated event kind")
    for action in actions:
        if (
            action["bill_id"] != bill["bill_id"]
            or action["state"] != bill["state"]
            or LITERALS.get((action["state"], action["description"])) != kind
        ):
            raise ValueError("literal evidence does not match bill/state/reviewed description")
    uncoded = [action for action in actions if _uncoded(action)]
    origin = [
        action
        for action in uncoded
        if bill["from_organization_id"]
        and action["organization_id"] == bill["from_organization_id"]
    ]
    day = None
    if not actions:
        status = "no_reviewed_literal_action"
    elif not uncoded:
        status = "only_source_coded_literal_actions"
    elif not bill["from_organization_id"]:
        status = "missing_originating_organization"
    elif not origin:
        status = "no_origin_literal_action"
    elif len(origin) != 1:
        status = "multiple_origin_literal_actions"
    elif origin_status(bill, origin[0]) != "origin_identity_matches":
        status = origin_status(bill, origin[0])
    else:
        day, status = explicit_date(origin[0]["date"])
    return {
        f"description_{kind}_n_literal_actions": len(actions),
        f"description_{kind}_n_uncoded_actions": len(uncoded),
        f"description_{kind}_n_origin_actions": len(origin),
        f"description_{kind}_action_ids": json.dumps([a["action_id"] for a in actions]),
        f"description_{kind}_origin_action_ids": json.dumps([a["action_id"] for a in origin]),
        f"description_{kind}_candidate_date": day,
        f"description_{kind}_disposition": status,
    }


def build_inventory(
    filing_dir: Path, window_dir: Path, actions_path: Path, extraction_path: Path, out_dir: Path
) -> dict:
    """Create a new bounded packet, preserving every original field for MA/ME/NY bills."""
    if out_dir.exists():
        raise FileExistsError(out_dir)
    paths = {
        "filing_manifest": filing_dir / "manifest.json",
        "filing_ledger": filing_dir / "bill_filing_evidence.csv",
        "window_manifest": window_dir / "manifest.json",
        "introduction_ledger": window_dir / "bill_window_ledger.csv",
        "actions": actions_path,
        "extraction_manifest": extraction_path,
        "producer": Path(__file__),
        "study_window": Path(__file__).with_name("study_window.py"),
        "outcomes": Path(__file__).with_name("outcomes.py"),
        "provenance": Path(__file__).parent.parent / "provenance.py",
    }
    before = {name: _snapshot(path) for name, path in paths.items()}
    filing, window, extraction = (
        json.loads(paths[name].read_text(encoding="utf-8"))
        for name in ("filing_manifest", "window_manifest", "extraction_manifest")
    )
    bindings = [
        (filing["artifacts"]["bill_filing_evidence.csv"], "filing_ledger"),
        (filing["inputs"]["window_manifest"], "window_manifest"),
        (filing["inputs"]["introduction_ledger"], "introduction_ledger"),
        (filing["inputs"]["actions"], "actions"),
        (window["artifacts"]["bill_window_ledger.csv"], "introduction_ledger"),
        (window["inputs"]["bill_actions.parquet"], "actions"),
        (window["inputs"]["bill_extraction_manifest.json"], "extraction_manifest"),
        (extraction["artifacts"]["bill_actions.parquet"], "actions"),
    ]
    source = pq.ParquetFile(actions_path)
    if (
        filing["status"]
        != "complete_source_filing_inventory_not_native_or_analytical_certification"
        or window["status"] != "complete_source_window_inventory_not_analytical_admission"
        or extraction["status"] != "complete_extraction_not_source_certification"
        or any((m["window_start"], m["window_end"]) != (START, END) for m in (filing, window))
        or any(binding["sha256"] != before[name]["sha256"] for binding, name in bindings)
        or extraction["artifacts"]["bill_actions.parquet"]["rows"] != source.metadata.num_rows
    ):
        raise ValueError("completed original ledger/action/extraction lineage required")

    bills = {}
    n_all_bills = 0
    with paths["filing_ledger"].open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        bill_fields = reader.fieldnames
        for row in reader:
            n_all_bills += 1
            if row["state"] not in STATES:
                continue
            if not row["bill_id"] or row["bill_id"] in bills:
                raise ValueError("scoped bill IDs must be nonempty and unique")
            bills[row["bill_id"]] = row
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = out_dir / "manifest.json"
    manifest = {
        "schema_version": 1,
        "status": "incomplete",
        "started_at": utc_now_iso(),
        "window_start": START,
        "window_end": END,
        "states": STATES,
        "inputs": before,
        "source_channel": CHANNEL,
        "analytical_admission": False,
        "new_requests": 0,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    literal_actions = defaultdict(list)
    distribution = Counter()
    counts = {state: Counter() for state in STATES}
    seen = set()
    evidence_fields = [
        *source.schema_arrow.names,
        *[f"bill_{name}" for name in bill_fields],
        "description_event_kind",
        "is_uncoded_candidate",
        "explicit_calendar_date",
        "explicit_date_status",
        "origin_identity_status",
        "source_channel",
        "analytical_admission",
    ]
    with (
        pq.ParquetWriter(out_dir / "literal_actions.parquet", source.schema_arrow) as raw,
        (out_dir / "literal_action_evidence.csv").open("x", encoding="utf-8", newline="") as handle,
    ):
        writer = csv.DictWriter(handle, fieldnames=evidence_fields)
        writer.writeheader()
        for batch in source.iter_batches(batch_size=65536):
            scoped = batch.filter(pc.is_in(batch.column("state"), value_set=pa.array(STATES)))
            selected = []
            for action in scoped.to_pylist():
                state = action["state"]
                day, date_status = explicit_date(action["date"])
                counts[state]["n_retained_actions"] += 1
                counts[state][f"n_retained_actions_{date_status}"] += 1
                distribution[
                    state, date_status, action["classification"], action["description"]
                ] += 1
                kind = LITERALS.get((state, action["description"]))
                if not kind:
                    continue
                bill = bills.get(action["bill_id"])
                if not bill or bill["state"] != state:
                    raise ValueError("literal action lacks an exact scoped bill/state join")
                if not action["action_id"] or action["action_id"] in seen:
                    raise ValueError("literal action IDs must be nonempty and unique")
                seen.add(action["action_id"])
                selected.append(action)
                literal_actions[action["bill_id"]].append(action)
                counts[state]["n_literal_actions"] += 1
                counts[state]["n_uncoded_literal_actions"] += int(_uncoded(action))
                writer.writerow(
                    {
                        **action,
                        **{f"bill_{name}": bill[name] for name in bill_fields},
                        "description_event_kind": kind,
                        "is_uncoded_candidate": _uncoded(action),
                        "explicit_calendar_date": day,
                        "explicit_date_status": date_status,
                        "origin_identity_status": origin_status(bill, action),
                        "source_channel": CHANNEL,
                        "analytical_admission": False,
                    }
                )
            raw.write_table(pa.Table.from_pylist(selected, schema=source.schema_arrow))

    derived_fields = list(description_disposition({}, [], kind=KINDS[0]))
    derived_fields += list(description_disposition({}, [], kind=KINDS[1]))
    with (out_dir / "candidate_bill_ledger.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[*bill_fields, *derived_fields, "source_channel", "analytical_admission"],
        )
        writer.writeheader()
        for bill in bills.values():
            row = {**bill, "source_channel": CHANNEL, "analytical_admission": False}
            counts[bill["state"]]["n_retained_bill_contexts"] += 1
            for kind in KINDS:
                actions = [
                    a
                    for a in literal_actions.get(bill["bill_id"], [])
                    if LITERALS[(a["state"], a["description"])] == kind
                ]
                result = description_disposition(bill, actions, kind=kind)
                row.update(result)
                disposition = result[f"description_{kind}_disposition"]
                counts[bill["state"]][f"{kind}:{disposition}"] += 1
            writer.writerow(row)
    with (out_dir / "description_distribution.csv").open(
        "x", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["state", "explicit_date_status", "classification", "description", "n_actions"]
        )
        for key, count in sorted(
            distribution.items(), key=lambda item: tuple("" if v is None else v for v in item[0])
        ):
            writer.writerow([*key, count])
    report = {
        "status": STATUS,
        "window_start": START,
        "window_end": END,
        "source_channel": CHANNEL,
        "n_original_all_state_bill_contexts": n_all_bills,
        "n_scoped_bill_contexts": len(bills),
        "n_literal_actions": len(seen),
        "literal_contracts": [
            {
                "state": state,
                "exact_description": text,
                "description_event_kind": kind,
                "scope": "exact case-sensitive full-string equality; no wording expansion",
            }
            for (state, text), kind in LITERALS.items()
        ],
        "states": [{"state": state, **counts[state]} for state in STATES],
        "limitations": [
            "All retained MA/ME/NY contexts and dates are inventoried, not session-year filtered.",
            "Only exact NY INTRODUCED and MA Petition filed descriptions have reviewed mappings.",
            "Petition filing is not introduction or general bill eligibility certification.",
            "ME approval for introduction is permission plus referral/printing, not introduction.",
            "First readings, placed-on-file, printed, referrals and receipt are not introductions.",
            "No reviewed literal observed means unresolved missing evidence, not zero activity.",
            "Matching raw actions, including coded/other-chamber/multiple events, are retained.",
            "Coded literal matches are audit-only; candidate dates use only uncoded origin events.",
            "Missing/invalid dates are not repaired from session, first action, order or URL.",
            "Original source dates, classifications and unknowns are never replaced.",
            "No native completeness, policy labels, party timing or analytical admission follows.",
        ],
        "new_requests": 0,
        "analytical_admission": False,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if {name: _snapshot(path) for name, path in paths.items()} != before:
        raise ValueError("description inventory inputs changed; packet remains incomplete")
    manifest.update(
        status=STATUS,
        completed_at=utc_now_iso(),
        inputs_unchanged=True,
        artifacts={
            path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in sorted(out_dir.iterdir())
            if path.name != "manifest.json"
        },
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filing-dir", type=Path, required=True)
    parser.add_argument("--window-dir", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--extraction-manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_inventory(
                args.filing_dir,
                args.window_dir,
                args.actions,
                args.extraction_manifest,
                args.out_dir,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

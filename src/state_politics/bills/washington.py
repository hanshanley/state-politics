"""Reconcile official Washington records without inventing filing-time affiliations."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

from ..platforms.recovery import verify_manifest
from ..provenance import sha256_file, utc_now_iso

SOURCE = Path("data/processed/washington-official-legislative-recovery-v1")
SOURCE_SHA256 = "fe98a43d5add0dcc058f9d80f256f36a1dfeddf76a32af45b4fda9d35aa47ecb"
BILLS_SHA256 = "732bf0a7583fb102a201497ccb90d51e07b2d57c62f3f808ce9fedfad0b48f7f"
BIENNIA = tuple(f"{year}-{str(year + 1)[2:]}" for year in range(2017, 2026, 2))
NS = "http://WSLWebServices.leg.wa.gov/"
BILL_FIELDS = (
    "Biennium", "BillId", "BillNumber", "SubstituteVersion", "EngrossedVersion",
    "OriginalAgency", "IntroducedDate", "PrimeSponsorID", "Sponsor",
    "ShortDescription", "LongDescription", "LegalTitle", "Active",
)
MEMBER_FIELDS = ("Id", "Name", "Agency", "Party", "District")
BASELINE_FIELDS = (
    "bill_id", "state", "session_identifier", "identifier", "title",
    "originating_chamber", "sponsor_party",
)


def parse_records(body: bytes, *, members: bool = False) -> list[dict]:
    """Preserve source row positions and reject unexpected publisher response schemas."""
    if b"<!doctype" in body.lower() or b"<!entity" in body.lower():
        raise ValueError("DTD/entity declarations are not legislative evidence")
    root = ET.fromstring(body)
    kind = "Member" if members else "Legislation"
    if root.tag != f"{{{NS}}}ArrayOf{kind}":
        raise ValueError(f"unexpected official {kind} response")
    fields = MEMBER_FIELDS if members else BILL_FIELDS
    required = ("Id", "Agency") if members else BILL_FIELDS[:8]
    rows = []
    for index, element in enumerate(root):
        if element.tag != f"{{{NS}}}{kind}":
            raise ValueError(f"unexpected official row {index}")
        row = {"source_row_index": index}
        for field in fields:
            nodes = element.findall(f"{{{NS}}}{field}")
            if len(nodes) > 1 or (nodes and len(nodes[0])):
                raise ValueError(f"non-scalar or duplicate {field} in row {index}")
            row[field] = (nodes[0].text or "").strip() if nodes else ""
        if any(not row[field] for field in required):
            raise ValueError(f"missing required official fields in row {index}")
        if members:
            if row["Agency"] not in {"House", "Senate"} or not row["Id"].isdigit():
                raise ValueError(f"invalid official member identity in row {index}")
        else:
            if row["Biennium"] not in BIENNIA:
                raise ValueError(f"out-of-scope biennium in row {index}")
            for field in ("BillNumber", "SubstituteVersion", "EngrossedVersion"):
                if not row[field].isdigit():
                    raise ValueError(f"invalid {field} in row {index}")
            if row["OriginalAgency"] not in {"House", "Senate"}:
                raise ValueError(f"invalid original chamber in row {index}")
        rows.append(row)
    return rows


def reconcile(baseline: list[dict], legislation: list[dict], members: list[dict]) -> list[dict]:
    """Join exact original bill keys and chamber-scoped IDs, retaining every ambiguity."""
    bills = defaultdict(list)
    roster = defaultdict(list)
    for row in legislation:
        if row["SubstituteVersion"] == "0" and row["EngrossedVersion"] == "0":
            year = row["Biennium"][:4]
            session = f"{year}-{int(year) + 1}"
            bills[session, row["BillId"]].append(row)
    for row in members:
        roster[row["Biennium"], row["Id"], row["Agency"]].append(row)
    seen = set()
    decisions = []
    for bill in baseline:
        key = bill["session_identifier"], bill["identifier"]
        if bill["state"] != "WA" or key in seen:
            raise ValueError("baseline must contain unique Washington bill keys")
        seen.add(key)
        candidates = bills.get(key, [])
        result = {
            **bill,
            "official_record_rows": [row["source_row_index"] for row in candidates],
            "official_roster_rows": [],
            "record_link_status": "missing_original_record",
            "session_roster_party": "unknown",
            "session_roster_party_reason": "no_unique_original_record",
            "filing_time_party": "unknown",
            "filing_time_party_reason": "session_roster_is_not_event_dated_membership",
            "analytical_admission": False,
        }
        if len(candidates) > 1:
            result["record_link_status"] = "multiple_original_records"
        elif len(candidates) == 1:
            source = candidates[0]
            result.update({f"official_{field}": value for field, value in source.items()
                           if field != "source_row_index"})
            expected = {"House": "lower", "Senate": "upper"}[source["OriginalAgency"]]
            prefix = "H" if expected == "lower" else "S"
            chamber = bill["originating_chamber"]
            if (not re.fullmatch(rf"{prefix}(?:B|JR|JM|CR|R|I) \d+", source["BillId"])
                    or chamber not in {expected, "unknown", ""}):
                result["record_link_status"] = "chamber_or_identifier_conflict"
            else:
                result["record_link_status"] = "unique_original_record"
                found = roster.get(
                    (source["Biennium"], source["PrimeSponsorID"], source["OriginalAgency"]), []
                )
                result["official_roster_rows"] = [row["source_row_index"] for row in found]
                if not found:
                    reason = "missing_chamber_scoped_roster_member"
                elif len(found) > 1:
                    reason = "multiple_chamber_scoped_roster_members"
                elif found[0]["Party"] not in {"D", "R"} or not found[0]["Name"]:
                    reason = "missing_or_unsupported_roster_party"
                else:
                    reason = "official_biennium_and_chamber_roster"
                    result["session_roster_party"] = found[0]["Party"]
                    result["official_roster_name"] = found[0]["Name"]
                result["session_roster_party_reason"] = reason
        decisions.append(result)
    return decisions


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def build_reconciliation(
    source: Path, bills: Path, out: Path, *,
    source_sha256: str = SOURCE_SHA256, bills_sha256: str = BILLS_SHA256,
    supplementary: Path | None = None, supplementary_sha256: str | None = None,
) -> dict:
    if out.exists():
        raise FileExistsError(out)
    if out.resolve().is_relative_to(source.resolve()):
        raise ValueError("output must not be inside the immutable source packet")
    if (supplementary is None) != (supplementary_sha256 is None):
        raise ValueError("supplementary source and its manifest identity must be supplied together")
    if supplementary is not None and out.resolve().is_relative_to(supplementary.resolve()):
        raise ValueError("output must not be inside the supplementary packet")
    if sha256_file(source / "manifest.json") != source_sha256:
        raise ValueError("official source packet identity changed")
    required = {"plan.json", "receipts.jsonl", "source/introduced_since_2017.xml"}
    required.update(f"source/roster_{biennium}.xml" for biennium in BIENNIA)
    verify_manifest(source, required)
    if sha256_file(bills) != bills_sha256:
        raise ValueError("baseline bill artifact identity changed")
    receipts = [json.loads(line) for line in (source / "receipts.jsonl").open()]
    for name in sorted(required - {"plan.json", "receipts.jsonl"}):
        matches = [row for row in receipts if row["file"] == Path(name).name]
        if (len(matches) != 1 or matches[0]["ok"] is not True
                or matches[0]["content_sha256"] != sha256_file(source / name)):
            raise ValueError(f"missing or inconsistent retained-source receipt: {name}")
    legislation = parse_records((source / "source/introduced_since_2017.xml").read_bytes())
    members = []
    for biennium in BIENNIA:
        rows = parse_records(
            (source / f"source/roster_{biennium}.xml").read_bytes(), members=True
        )
        members.extend({"Biennium": biennium, **row} for row in rows)
    baseline = pd.read_parquet(bills, columns=list(BASELINE_FIELDS))
    baseline = baseline.loc[baseline.state.eq("WA")].copy()
    if baseline.empty or baseline.isna().any().any() or baseline.bill_id.duplicated().any():
        raise ValueError("empty, incomplete or duplicate Washington baseline")
    supplementary_failures = []
    if supplementary is not None:
        if sha256_file(supplementary / "manifest.json") != supplementary_sha256:
            raise ValueError("supplementary source packet identity changed")
        packet_manifest = verify_manifest(
            supplementary, {"plan.json", "receipts.jsonl", "run.json"}
        )
        plan = json.loads((supplementary / "plan.json").read_text())
        if plan["initial_source_manifest_sha256"] != source_sha256:
            raise ValueError("supplementary source belongs to a different initial packet")
        initial = reconcile(baseline.to_dict("records"), legislation, members)
        expected_targets = {
            row["bill_id"] for row in initial
            if row["record_link_status"] == "missing_original_record"
            and row["identifier"].split()[0] in {"SR", "HR"}
        }
        requests = plan["requests"]
        if (len(requests) != len(expected_targets)
                or {row["bill_id"] for row in requests} != expected_targets):
            raise ValueError("supplementary plan must cover the exact missing-resolution set")
        by_id = {row["bill_id"]: row for row in initial}
        supplement_receipts = [
            json.loads(line) for line in (supplementary / "receipts.jsonl").open()
        ]
        if len(supplement_receipts) != len(requests):
            raise ValueError("supplementary receipt population differs from its plan")
        for row in legislation:
            row["source_file"] = "source/official_packet/source/introduced_since_2017.xml"
            row["source_file_row_index"] = row["source_row_index"]
        for request in requests:
            target = by_id[request["bill_id"]]
            biennium = target["session_identifier"][:4] + "-" + target["session_identifier"][-2:]
            name = f"{biennium}_{target['identifier'].replace(' ', '_')}.xml"
            url = (
                "https://wslwebservices.leg.wa.gov/LegislationService.asmx/GetLegislation?"
                + urlencode({"biennium": biennium, "billNumber": target["identifier"].split()[1]})
            )
            if (request["biennium"] != biennium or request["identifier"] != target["identifier"]
                    or request["file"] != name or request["url"] != url):
                raise ValueError("supplementary request does not match its exact baseline target")
            matches = [row for row in supplement_receipts if row["file"] == name]
            if len(matches) != 1 or matches[0]["url"] != url:
                raise ValueError(f"missing or inconsistent supplementary receipt: {name}")
            receipt = matches[0]
            if receipt["ok"] is not True:
                supplementary_failures.append(receipt)
                continue
            relative = f"source/{name}"
            if (relative not in packet_manifest["files"]
                    or receipt["content_sha256"] != sha256_file(supplementary / relative)):
                raise ValueError(f"supplementary source/receipt mismatch: {name}")
            added = parse_records((supplementary / relative).read_bytes())
            for row in added:
                if (row["Biennium"] != biennium
                        or row["BillNumber"] != target["identifier"].split()[1]
                        or row["OriginalAgency"] != (
                            "House" if target["identifier"].startswith("H") else "Senate"
                        )):
                    raise ValueError(f"supplementary response contains a different bill: {name}")
                row["source_file"] = f"source/supplementary_packet/{relative}"
                row["source_file_row_index"] = row["source_row_index"]
                row["source_row_index"] = len(legislation)
                legislation.append(row)
    decisions = reconcile(baseline.to_dict("records"), legislation, members)
    original = [row for row in legislation
                if row["SubstituteVersion"] == "0" and row["EngrossedVersion"] == "0"]
    baseline_keys = {(row["session_identifier"], row["identifier"]) for row in decisions}
    source_only = [row for row in original
                   if (f"{row['Biennium'][:4]}-{int(row['Biennium'][:4]) + 1}",
                       row["BillId"]) not in baseline_keys]
    report = {
        "created_at": utc_now_iso(),
        "source_manifest_sha256": source_sha256, "bills_sha256": bills_sha256,
        "supplementary_manifest_sha256": supplementary_sha256,
        "supplementary_retrieval_failures": supplementary_failures,
        "official_version_records": len(legislation),
        "official_original_records": len(original),
        "official_unique_original_keys": len({
            (row["Biennium"], row["BillId"]) for row in original
        }),
        "roster_records": len(members), "baseline_bills": len(decisions),
        "record_link_status": dict(Counter(row["record_link_status"] for row in decisions)),
        "session_roster_party": dict(Counter(row["session_roster_party"] for row in decisions)),
        "session_roster_party_reason": dict(Counter(
            row["session_roster_party_reason"] for row in decisions
        )),
        "unique_original_records_with_legal_title": sum(
            row["record_link_status"] == "unique_original_record"
            and bool(row.get("official_LegalTitle")) for row in decisions
        ),
        "unique_original_records_with_placeholder_introduction_date": sum(
            row["record_link_status"] == "unique_original_record"
            and row.get("official_IntroducedDate", "").startswith("0001-01-01")
            for row in decisions
        ),
        "source_only_original_records": len(source_only),
        "source_only_unique_keys": len({(row["Biennium"], row["BillId"]) for row in source_only}),
        "analytical_admission": False, "training_admission": False,
        "limitations": [
            "Exact official bill-key and numeric-ID joins, not name-based person resolution.",
            "Duplicate originals and chamber-scoped roster ambiguities remain unresolved.",
            "Session roster party is not affiliation at filing, introduction or any action date.",
            f"The {len(decisions)} baseline Washington measures include resolutions "
            "and other bill types.",
            "Source-only records are a completeness discrepancy, not admitted additional bills.",
            "Official titles/descriptions are retrieval-time version evidence, not certified "
            "filing-time text, policy classifications or a verified exhaustive universe.",
            "The baseline, its sponsor_party decisions and canonical analyses remain unchanged.",
        ],
    }
    out.mkdir(parents=True)
    (out / "source").mkdir()
    shutil.copytree(source, out / "source/official_packet")
    if supplementary is not None:
        shutil.copytree(supplementary, out / "source/supplementary_packet")
    baseline.to_parquet(out / "source/baseline_washington_bills.parquet", index=False)
    shutil.copyfile(__file__, out / "producer.py")
    _write_jsonl(out / "official_legislation.jsonl", legislation)
    _write_jsonl(out / "official_rosters.jsonl", members)
    _write_jsonl(out / "bill_reconciliation.jsonl", decisions)
    _write_jsonl(out / "source_only_originals.jsonl", source_only)
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "manifest.json").write_text(json.dumps({
        "files": {str(path.relative_to(out)): sha256_file(path)
                  for path in sorted(out.rglob("*")) if path.is_file()},
    }, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--bills", type=Path, default=Path("data/processed/bills.parquet"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--supplementary", type=Path)
    parser.add_argument("--supplementary-manifest-sha256")
    args = parser.parse_args()
    print(json.dumps(build_reconciliation(
        args.source, args.bills, args.out, supplementary=args.supplementary,
        supplementary_sha256=args.supplementary_manifest_sha256,
    ), indent=2))


if __name__ == "__main__":
    main()

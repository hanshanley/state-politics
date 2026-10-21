#!/usr/bin/env python3
"""Build an explicitly unpublished evidence preview from saved sources, never model inference."""

from __future__ import annotations

import argparse
import gzip
import html
import json
import shutil
from collections import defaultdict
from pathlib import Path

from state_politics.bills.openstates_dump import STATE_CODES
from state_politics.platforms.recovery import load_recovery
from state_politics.provenance import sha256_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA = ROOT / "data/processed/study-abstract-evidence-2023-2024-v3"
DEFAULT_NATIVE = ROOT / "data/processed/study-native-overlap-2023-2024-v14"
DEFAULT_TOKEN_PLAN = ROOT / "data/processed/study-metadata-token-plan-2023-2024-v2"


def build_preview(
    ledger_path: Path, historical_path: Path, out: Path, *, recovery_path: Path | None = None,
) -> dict:
    ledger = json.loads(ledger_path.read_text())
    if ledger.get("schema_version") != 1 or ledger.get("expected_organizations") != 100:
        raise ValueError("incompatible source coverage contract")
    rows = ledger["rows"]
    keys = {(row["state"], row["party"]) for row in rows}
    expected = {(state.upper(), party) for state in STATE_CODES for party in ("D", "R")}
    if len(rows) != 100 or keys != expected:
        raise ValueError("preview requires all 100 unique expected organization rows")
    recovery, captures = load_recovery(recovery_path, expected) if recovery_path else (None, [])
    recovery_rows = (
        {(row["state"], row["party"]): row for row in recovery["rows"]} if recovery else {}
    )
    recovered = defaultdict(list)
    for row in captures:
        recovered[row["state"], row["party"]].append(row)
    archive = [
        json.loads(line) for line in historical_path.read_text().split("\n") if line.strip()
    ]
    partitions = defaultdict(list)
    for row in archive:
        if (row["state"], row["party"]) in keys:
            partitions[row["state"], row["party"]].append(row)
    table = []
    def escape(value):
        return html.escape(str(value), quote=True)

    for row in rows:
        key = (row["state"], row["party"])
        if row["historical_document_count"] != len(partitions[key]):
            raise ValueError(f"coverage does not reconcile with source rows: {key}")
        cells = [
            f"{row['state']} / {row['party']}", row["historical_document_count"],
            row["historical_latest_year"] if row["historical_latest_year"] is not None else "—",
            row["operative_platform_status"],
            (
                f"{recovery_rows[key]['n_retained_response_captures']} retained / "
                f"{recovery_rows[key]['n_selected_capture_attempts']} attempts"
                if recovery else "Not included in this build"
            ),
            "Not applicable: nonpartisan" if row["state"] == "NE" else "Not rebuilt",
        ]
        table.append(
            f'<tr data-state="{escape(key[0])}" data-party="{escape(key[1])}">'
            + "".join(f"<td>{escape(value)}</td>" for value in cells) + "</tr>"
        )
    options = "".join(
        f'<option value="{escape(state)}">{escape(state)}</option>'
        for state in sorted({row["state"] for row in rows})
    )
    document = (ROOT / "web/preview.html").read_text()
    for marker, value in {
        "@@ARCHIVE_COUNT@@": f"{len(archive):,}",
        "@@STATE_OPTIONS@@": options, "@@COVERAGE_ROWS@@": "\n".join(table),
        "@@RECOVERY_OPTION@@": (
            '<option value="recovery">Bounded recovery captures</option>' if recovery else ""
        ),
        "@@RECOVERY_NOTE@@": (
            f"<p class=\"note\">Selected recovery packets: {len(captures)} attempts, "
            f"{recovery['n_retained_response_captures']} retained responses and "
            f"{recovery['n_distinct_response_body_hashes']} distinct body hashes. "
            "These include shells, drafts and repeated captures, not verified platforms. "
            "This bounded inventory excludes other campaign packets; zero here is not "
            "publication absence.</p>" if recovery else ""
        ),
        "@@RECOVERY_DOWNLOADS@@": (
            '<p><a href="downloads/recovery_captures.jsonl.gz" download>'
            'Complete selected recovery captures '
            '(JSONL, gzip; full text and alternate extractions)</a>'
            ' · <a href="downloads/recovery_inventory.json" download>'
            'Recovery inventory and all 100 organization rows</a>'
            ' · <a href="downloads/recovery_inventory_manifest.json" download>'
            'Original recovery packet hashes</a></p>' if recovery else ""
        ),
    }.items():
        document = document.replace(marker, value)
    if "@@" in document:
        raise ValueError("unresolved template fields")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(document)
    for name in ("preview.css", "preview.js"):
        shutil.copyfile(ROOT / "web" / name, out / name)
    evidence = out / "evidence"
    evidence.mkdir(exist_ok=True)
    for state, party in keys:
        (evidence / f"{state}-{party}.json").write_text(
            json.dumps(partitions[state, party], ensure_ascii=True)
        )
        if recovery:
            (evidence / f"recovery-{state}-{party}.json").write_text(
                json.dumps(recovered[state, party], ensure_ascii=True, allow_nan=False)
            )
        else:
            (evidence / f"recovery-{state}-{party}.json").unlink(missing_ok=True)
    downloads = out / "downloads"
    downloads.mkdir(exist_ok=True)
    shutil.copyfile(ledger_path, downloads / "source_coverage.json")
    with (
        gzip.open(downloads / "historical_documents.jsonl.gz", "wb") as handle,
        historical_path.open("rb") as source,
    ):
        shutil.copyfileobj(source, handle)
    if recovery_path:
        shutil.copyfile(recovery_path, downloads / "recovery_inventory.json")
        shutil.copyfile(
            recovery_path.parent / "manifest.json", downloads / "recovery_inventory_manifest.json"
        )
        with (
            gzip.open(downloads / "recovery_captures.jsonl.gz", "wb") as handle,
            (recovery_path.parent / "captures.jsonl").open("rb") as source,
        ):
            shutil.copyfileobj(source, handle)
    else:
        for name in (
            "recovery_inventory.json", "recovery_inventory_manifest.json",
            "recovery_captures.jsonl.gz",
        ):
            (downloads / name).unlink(missing_ok=True)
    manifest = {
        "schema_version": 1, "publication_status": "local_only_unpublished",
        "scientific_certification": "not_performed", "archive_documents": len(archive),
        "state_major_party_documents": sum(map(len, partitions.values())),
        "analysis_cutoff": ledger["analysis_cutoff"],
        "recovery_capture_attempts": len(captures) if recovery else None,
        "recovery_retained_responses": (
            recovery["n_retained_response_captures"] if recovery else None
        ),
        "recovery_inventory_scope": "selected_packets_not_full_campaign" if recovery else None,
        "inputs": {
            "source_coverage_sha256": sha256_file(ledger_path),
            "historical_documents_sha256": sha256_file(historical_path),
        },
        "assets": {
            path.name: sha256_file(path) for path in (ROOT / "web").iterdir() if path.is_file()
        },
    }
    if recovery_path:
        manifest["inputs"]["recovery_manifest_sha256"] = sha256_file(
            recovery_path.parent / "manifest.json"
        )
    (downloads / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coverage", type=Path, default=ROOT / "data/processed/source_coverage.json"
    )
    parser.add_argument(
        "--historical", type=Path, default=ROOT / "data/processed/platforms_historical.jsonl"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "data/preview")
    parser.add_argument(
        "--recovery", type=Path,
        help="Optional verified bounded-recovery inventory.json; not analytical admission",
    )
    parser.add_argument(
        "--cycle-evidence", action="store_true",
        help="Evidence-only 2023–2024 preview; no report, inference or public integration",
    )
    parser.add_argument(
        "--bill-evidence", type=Path,
        help="Full-string metadata bundle (default: v3 with matching native v14/token plan v2)",
    )
    parser.add_argument(
        "--platform-evidence", type=Path,
        default=ROOT / "data/processed/platform-study-evidence-2023-2024-v5",
        help="Immutable full-text platform evidence bundle",
    )
    parser.add_argument(
        "--native-evidence", type=Path,
        help="Optional matching native bundle; default v14 only with default metadata selection",
    )
    parser.add_argument(
        "--metadata-token-plan", type=Path,
        help="Optional tokenization plan; default v2 only with the default metadata selection",
    )
    args = parser.parse_args(argv)
    default_evidence = args.bill_evidence is None
    if default_evidence:
        args.bill_evidence = DEFAULT_METADATA
    if args.cycle_evidence and args.out == ROOT / "data/preview":
        args.out = ROOT / "data/preview-cycle-evidence-v3"
    if not args.out.resolve().is_relative_to((ROOT / "data").resolve()):
        parser.error("preview output must remain under this project's ignored data/ directory")
    if args.cycle_evidence:
        if args.recovery:
            parser.error("--recovery belongs to the legacy preview, not --cycle-evidence")
        from state_politics.site_evidence import build_cycle_preview

        optional = {}
        if args.native_evidence or default_evidence:
            optional["native_evidence"] = args.native_evidence or DEFAULT_NATIVE
        if args.metadata_token_plan or default_evidence:
            optional["metadata_token_plan"] = args.metadata_token_plan or DEFAULT_TOKEN_PLAN
        result = build_cycle_preview(
            args.bill_evidence, args.platform_evidence, args.out, **optional,
        )
        print(f"wrote local-only cycle evidence preview: {args.out / 'index.html'}")
        print(json.dumps(result["counts"], sort_keys=True))
        print(f"build manifest sha256: {sha256_file(args.out / 'downloads/build_manifest.json')}")
        return 0
    if args.native_evidence or args.metadata_token_plan:
        parser.error("--native-evidence and --metadata-token-plan require --cycle-evidence")
    result = build_preview(
        args.coverage, args.historical, args.out, recovery_path=args.recovery,
    )
    print(f"wrote local-only preview: {args.out / 'index.html'}")
    print(f"archive documents: {result['archive_documents']}; no analytical findings published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

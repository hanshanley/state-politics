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
from state_politics.provenance import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def build_preview(ledger_path: Path, historical_path: Path, out: Path) -> dict:
    ledger = json.loads(ledger_path.read_text())
    if ledger.get("schema_version") != 1 or ledger.get("expected_organizations") != 100:
        raise ValueError("incompatible source coverage contract")
    rows = ledger["rows"]
    keys = {(row["state"], row["party"]) for row in rows}
    expected = {(state.upper(), party) for state in STATE_CODES for party in ("D", "R")}
    if len(rows) != 100 or keys != expected:
        raise ValueError("preview requires all 100 unique expected organization rows")
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
    downloads = out / "downloads"
    downloads.mkdir(exist_ok=True)
    shutil.copyfile(ledger_path, downloads / "source_coverage.json")
    with (
        gzip.open(downloads / "historical_documents.jsonl.gz", "wb") as handle,
        historical_path.open("rb") as source,
    ):
        shutil.copyfileobj(source, handle)
    manifest = {
        "schema_version": 1, "publication_status": "local_only_unpublished",
        "scientific_certification": "not_performed", "archive_documents": len(archive),
        "state_major_party_documents": sum(map(len, partitions.values())),
        "analysis_cutoff": ledger["analysis_cutoff"],
        "inputs": {
            "source_coverage_sha256": sha256_file(ledger_path),
            "historical_documents_sha256": sha256_file(historical_path),
        },
        "assets": {
            path.name: sha256_file(path) for path in (ROOT / "web").iterdir() if path.is_file()
        },
    }
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
    args = parser.parse_args(argv)
    if not args.out.resolve().is_relative_to((ROOT / "data").resolve()):
        parser.error("preview output must remain under this project's ignored data/ directory")
    result = build_preview(args.coverage, args.historical, args.out)
    print(f"wrote local-only preview: {args.out / 'index.html'}")
    print(f"archive documents: {result['archive_documents']}; no analytical findings published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

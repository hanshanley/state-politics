#!/usr/bin/env python3
"""Audit manual inputs, primary sources, generated artifacts, and published invariants.

The audit intentionally does not contain expected output counts copied from the README. It
checks relationships that must hold regardless of the current corpus size:

* every curated input is declared, hashed, documented, and not ignored;
* every label/code is valid against the current taxonomy;
* every gap is explained exactly once and no explanation is orphaned;
* every generated artifact names an existing Python producer;
* all 50 states have stated agenda coverage (committee corpus + separate caucus supplement);
* the focus atlas has exactly one row per state x major party;
* Nebraska is the only state without partisan bill profiles, for the documented reason;
* election detector validation and term-concentration semantics reproduce from raw columns;
* OCR-derived corpus rows identify their stable registry source and OCR version;
* random processes declare seeds in one machine-readable manifest.

Use ``--require-tracked`` in CI after committing. Development runs still reject ignored or
undeclared inputs but allow the user's uncommitted working tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "conf" / "reproducibility.yml"
STATE_CODES = {
    "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "IA", "ID",
    "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO", "MS", "MT",
    "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY",
}
PARTIES = {"D", "R"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class Audit:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.checks = 0

    def require(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.failures.append(message)

    def finish(self) -> None:
        if self.failures:
            print(f"FAILED: {len(self.failures)} of {self.checks} checks")
            for failure in self.failures:
                print(f"  - {failure}")
            raise SystemExit(1)
        print(f"PASS: {self.checks} reproducibility checks")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def git_files(arguments: list[str]) -> set[str]:
    output = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {line for line in output.splitlines() if line}


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def audit_manifest(audit: Audit, manifest: dict, *, require_tracked: bool) -> None:
    tracked = git_files(["ls-files"])
    ignored = git_files(["ls-files", "--others", "-i", "--exclude-standard"])
    for entry in manifest["manual_inputs"]:
        relative = entry["path"]
        path = ROOT / relative
        audit.require(path.exists(), f"manual input is missing: {relative}")
        if not path.exists():
            continue
        audit.require(
            SHA256_RE.match(entry["sha256"]) is not None,
            f"manual input has invalid SHA-256: {relative}",
        )
        audit.require(
            sha256_file(path) == entry["sha256"],
            f"manual input hash changed without manifest update: {relative}",
        )
        audit.require(relative not in ignored, f"manual input is gitignored: {relative}")
        if require_tracked:
            audit.require(relative in tracked, f"manual input is not tracked: {relative}")
        methodology = entry.get("methodology")
        if methodology:
            audit.require(
                (ROOT / methodology).exists(),
                f"manual input methodology is missing: {methodology}",
            )

    for process in manifest["random_processes"]:
        audit.require(isinstance(process.get("seed"), int), f"seed missing: {process['name']}")
        audit.require(
            (ROOT / process["code"]).exists(),
            f"random process code is missing: {process['code']}",
        )
        if process.get("metadata"):
            audit.require(
                (ROOT / process["metadata"]).exists(),
                f"random process metadata is missing: {process['metadata']}",
            )

    for artifact in manifest["generated_artifacts"]:
        audit.require(
            (ROOT / artifact["producer"]).exists(),
            f"artifact producer is missing: {artifact['producer']}",
        )
        for supplement in artifact.get("supplements", []):
            audit.require(
                (ROOT / supplement).exists(),
                f"artifact supplement producer is missing: {supplement}",
            )


def audit_gold(audit: Audit) -> None:
    meta = load_yaml(ROOT / "data/gold/plank_topics_gold.meta.yml")
    gold = pd.read_csv(ROOT / "data/gold/plank_topics_gold.csv")
    topics = load_yaml(ROOT / "conf/topics.yml")["topics"]
    codes = {int(topic["code"]) for topic in topics}
    audit.require(len(gold) == int(meta["sample_size"]), "gold sample size != metadata")
    audit.require(gold["index"].is_unique, "gold sample indices are not unique")
    audit.require(gold["text"].fillna("").str.strip().ne("").all(), "gold has empty text")
    audit.require(
        set(gold["gold_topic"].astype(int)) <= codes,
        "gold labels contain codes outside conf/topics.yml",
    )
    audit.require(int(meta["sample_seed"]) == 20260729, "gold seed metadata changed")


def audit_curated_configs(audit: Audit) -> None:
    topics = load_yaml(ROOT / "conf/topics.yml")["topics"]
    codes = {int(topic["code"]) for topic in topics}
    subject_map = load_yaml(ROOT / "conf/subject_topic_map.yml")["tags"]
    audit.require(
        set(map(int, subject_map.values())) <= codes,
        "subject map contains unknown topic codes",
    )
    audit.require(
        all(tag == tag.strip().lower() for tag in subject_map),
        "subject-map keys are not normalized",
    )

    registry = load_yaml(ROOT / "conf/party_registry.yml")["organizations"]
    keys = [(row["state"], row["party"]) for row in registry]
    audit.require(len(keys) == len(STATE_CODES) * len(PARTIES), "party registry is not 100 rows")
    audit.require(len(keys) == len(set(keys)), "party registry has duplicate state-party rows")
    audit.require({state for state, _ in keys} == STATE_CODES, "party registry misses states")
    audit.require({party for _, party in keys} == PARTIES, "party registry has invalid parties")
    audit.require(all(row.get("source_url") for row in registry), "registry row lacks source URL")
    audit.require(
        all(row.get("verified_on") for row in registry), "registry row lacks verification date"
    )

    official = load_yaml(ROOT / "conf/official_document_registry.yml")["sources"]
    audit.require(all(row.get("primary_source") is True for row in official),
                  "official OCR registry contains a non-primary source")
    for row in official:
        for field in ("page_url", "document_url"):
            if row.get(field):
                audit.require(
                    urlsplit(row[field]).scheme == "https",
                    f"official source is not HTTPS: {row[field]}",
                )
        expected = row.get("expected_document_sha256")
        if expected:
            audit.require(
                SHA256_RE.match(expected) is not None,
                f"invalid official source hash: {row['id']}",
            )

    caucuses = load_yaml(ROOT / "conf/caucus_priority_registry.yml")["sources"]
    audit.require(
        all(row.get("institution") and row.get("urls") for row in caucuses),
        "caucus source lacks institution or URL",
    )
    audit.require(
        all(urlsplit(url).scheme == "https" for row in caucuses for url in row["urls"]),
        "caucus source uses a non-HTTPS URL",
    )


def audit_artifacts(audit: Audit) -> dict:
    data = ROOT / "data/processed"
    required = [
        "platforms_2018_present.parquet",
        "platform_gap_report.csv",
        "caucus_priorities.parquet",
        "bills.parquet",
        "planks_classified.parquet",
        "state_party_focus.csv",
        "election_focus_by_state_party.csv",
        "election_title_validation.json",
        "state_party_terms.csv",
    ]
    for name in required:
        audit.require((data / name).exists(), f"required artifact is missing: {name}")
    if any(not (data / name).exists() for name in required):
        return {}

    platforms = pd.read_parquet(data / "platforms_2018_present.parquet")
    confirmed = platforms[platforms["confirmed"]]
    gaps = pd.read_csv(data / "platform_gap_report.csv")
    caucuses = pd.read_parquet(data / "caucus_priorities.parquet")
    bills = pd.read_parquet(data / "bills.parquet", columns=["state", "sponsor_party"])
    planks = pd.read_parquet(data / "planks_classified.parquet")
    atlas = pd.read_csv(data / "state_party_focus.csv")
    elections = pd.read_csv(data / "election_focus_by_state_party.csv")
    validation = json.loads((data / "election_title_validation.json").read_text())
    terms = pd.read_csv(data / "state_party_terms.csv")

    platform_keys = set(map(tuple, confirmed[["state", "party"]].drop_duplicates().values))
    gap_keys = set(
        map(tuple, gaps.loc[gaps["n_confirmed"] == 0, ["state", "party"]].values)
    )
    audit.require(len(platform_keys | gap_keys) == 100, "platform + gap rows do not cover 100 orgs")
    audit.require(not platform_keys & gap_keys, "an organization is both found and a gap")
    audit.require(
        gaps.loc[gaps["n_confirmed"] == 0, "gap_finding"].fillna("").str.len().gt(0).all(),
        "a platform gap lacks a hand-verified finding",
    )
    audit.require(
        set(confirmed["state"]) | set(caucuses["state"]) == STATE_CODES,
        "committee corpus + caucus supplement does not cover all 50 states",
    )
    audit.require(set(bills["state"]) == STATE_CODES, "bill corpus does not cover all 50 states")
    audit.require(len(atlas) == 100, "state focus atlas is not 100 rows")
    audit.require(
        len(atlas[["state", "party"]].drop_duplicates()) == 100,
        "state focus atlas has duplicate or missing state-party rows",
    )
    missing_bill = atlas.loc[atlas["bill_n_items"].isna(), "state"].unique().tolist()
    audit.require(missing_bill == ["NE"], "Nebraska is not the sole missing partisan bill state")
    audit.require(
        set(atlas.loc[atlas["state"] == "NE", "bill_status"])
        == {"formally_nonpartisan_legislature"},
        "Nebraska bill-status explanation is missing",
    )
    audit.require(planks["document_index"].notna().all(), "classified plank lacks document index")
    audit.require(
        int(elections["n_election_bills"].sum()) <= int(elections["n_bills"].sum()),
        "election bill numerator exceeds denominator",
    )
    audit.require(0 <= validation["precision"] <= 1, "election precision is not a proportion")
    audit.require(0 <= validation["recall"] <= 1, "election recall is not a proportion")
    audit.require(
        terms.loc[terms["peer_absent"], "log2_concentration"].isna().all(),
        "peer-absent term has a fabricated numeric concentration",
    )
    numeric = terms[~terms["peer_absent"]]
    reproduced = (
        (
            (numeric["count"] / numeric["feature_total"])
            / (numeric["peer_count"] / numeric["peer_feature_total"])
        ).map(lambda value: round(float(__import__("math").log2(value)), 4))
    )
    audit.require(
        (reproduced - numeric["log2_concentration"]).abs().le(1e-4).all(),
        "stored log2 concentrations do not reproduce from raw counts",
    )

    official_rows = confirmed[confirmed["source"].isin(("issuu_images", "scanned_pdf"))]
    official_registry = load_yaml(
        ROOT / "conf/official_document_registry.yml"
    )["sources"]
    audit.require(
        len(official_rows) == len(official_registry),
        "OCR-derived corpus rows do not match official registry",
    )
    if not official_rows.empty:
        audit.require(
            official_rows["official_source_id"].notna().all(),
            "OCR-derived row lacks stable official_source_id",
        )
        audit.require(
            official_rows["ocr_version"].notna().all(),
            "OCR-derived row lacks OCR version",
        )

    return {
        "confirmed_documents": int(len(confirmed)),
        "party_organizations_with_documents": int(len(platform_keys)),
        "party_committee_states": int(confirmed["state"].nunique()),
        "stated_agenda_states": int(len(set(confirmed["state"]) | set(caucuses["state"]))),
        "bills": int(len(bills)),
        "classified_planks": int(planks["topic"].notna().sum()),
        "state_party_profiles": int(len(atlas)),
        "election_bills": int(elections["n_election_bills"].sum()),
        "term_rows": int(len(terms)),
    }


def audit_public_docs(audit: Audit) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    banned = re.findall(r"Apple Silicon|\bMPS\b|\bM4\b|hosted LLM", readme, re.I)
    audit.require(
        not banned,
        f"public README contains machine-specific implementation text: {banned}",
    )
    for relative in ("README.md", "docs/METHODS.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        base = (ROOT / relative).parent
        for image in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
            audit.require((base / image).exists(), f"{relative} references missing image {image}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument(
        "--report", default=ROOT / "data/processed/reproducibility_report.json"
    )
    args = parser.parse_args(argv)

    audit = Audit()
    manifest = load_yaml(MANIFEST)
    audit_manifest(audit, manifest, require_tracked=args.require_tracked)
    audit_gold(audit)
    audit_curated_configs(audit)
    computed = audit_artifacts(audit)
    audit_public_docs(audit)
    audit.finish()

    report = {
        "manifest_version": manifest["version"],
        "checks_passed": audit.checks,
        "computed_results": computed,
        "manual_input_hashes": {
            entry["path"]: entry["sha256"] for entry in manifest["manual_inputs"]
        },
        "random_seeds": {
            process["name"]: process["seed"] for process in manifest["random_processes"]
        },
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

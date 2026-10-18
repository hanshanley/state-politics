"""Audit recovered legislative evidence without running or endorsing a classifier."""

from __future__ import annotations

import argparse
import json
import re
import tarfile
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

from ..bills.openstates_dump import STATE_CODES
from ..provenance import sha256_file, utc_now_iso


def inspect_party_history_archive(path: Path, *, revision: str, expected_sha256: str):
    """Measure a pinned alternative source; do not turn undated records into affiliations."""
    import yaml

    actual = sha256_file(path)
    if actual != expected_sha256 or not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("party-history archive checksum/revision mismatch")
    counts = Counter()
    bounds = Counter()
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    pattern = re.compile(
        rf"people-{revision}/data/[a-z]{{2}}/(?:legislature|retired)/[^/]+\.ya?ml"
    )
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if not member.isfile() or not pattern.fullmatch(member.name):
                continue
            with archive.extractfile(member) as handle:
                person = yaml.load(handle, Loader=loader)
            if not person["id"].startswith("ocd-person/"):
                raise ValueError(f"unexpected person identity: {member.name}")
            counts["people"] += 1
            parties = person.get("party") or []
            counts["people_without_party_records"] += not parties
            counts["multiple_party_records"] += len(parties) > 1
            for party in parties:
                start, end = bool(party.get("start_date")), bool(party.get("end_date"))
                bounds[f"start={start},end={end}"] += 1
    if not counts["people"]:
        raise ValueError("no person records matching the frozen archive revision")
    return {
        "status": "source_inventory_not_verified_affiliation_history",
        "source_revision": revision, "source_sha256": actual, "source_path": str(path),
        "counts": dict(counts), "party_date_bounds": dict(bounds),
        "limitations": [
            "An undated party record remains undated, even when legislative tenure is known.",
            "A date bound is source metadata, not independent verification of party history.",
            "No affiliations from this archive have been applied to bills or votes.",
        ],
    }


def inspect_dump_party_memberships(dump_path):
    from ..bills.openstates_dump import stream_table
    from ..bills.people import normalize_party

    parties = {
        row["id"]: row["name"]
        for row in stream_table(dump_path, "opencivicdata_organization")
        if row.get("classification") == "party"
    }
    counts = Counter()
    rows = []
    for row in stream_table(dump_path, "opencivicdata_membership"):
        counts["all_source_memberships"] += 1
        if row.get("organization_id") not in parties:
            continue
        party_name = parties[row["organization_id"]]
        dated = bool(row.get("start_date") or row.get("end_date"))
        counts["party_memberships"] += 1
        counts["with_any_date_bound" if dated else "entirely_undated"] += 1
        rows.append({
            **row, "party_name": party_name, "normalized_party": normalize_party(party_name),
            "timing_status": "date_bounds_not_independently_reviewed" if dated else "undated",
        })
    return dict(counts), pd.DataFrame(rows)


def audit_bill_sources(bills, evidence, *, observed_on: str):
    """Return coverage, source-quality flags and denominators, not scientific certification."""
    observed = date.fromisoformat(observed_on)
    if observed.isoformat() != observed_on:
        raise ValueError("observed_on must be an exact YYYY-MM-DD date")
    for frame in (bills, evidence):
        ids = frame["bill_id"]
        if (
            not ids.map(lambda value: isinstance(value, str) and bool(value.strip())).all()
            or ids.duplicated().any()
        ):
            raise ValueError("source audit requires unique nonempty string bill IDs")
    if set(bills["bill_id"]) != set(evidence["bill_id"]):
        raise ValueError("bill/evidence coverage joins must match exactly")
    expected = {state.upper() for state in STATE_CODES}
    if not bills["state"].isin(expected).all():
        raise ValueError("source audit accepts only the 50 state jurisdictions")
    frame = bills.merge(evidence.drop(columns="state"), on="bill_id", validate="one_to_one")
    if not bills.set_index("bill_id")["state"].sort_index().equals(
        evidence.set_index("bill_id")["state"].sort_index()
    ):
        raise ValueError("bill/evidence state identities disagree")
    first_raw = frame["first_action_date"].astype("string").fillna("").str.strip()
    latest_raw = frame["latest_action_date"].astype("string").fillna("").str.strip()
    first = pd.to_datetime(first_raw.where(first_raw.ne("")), format="ISO8601",
                           errors="coerce", utc=True)
    latest = pd.to_datetime(latest_raw.where(latest_raw.ne("")), format="ISO8601",
                            errors="coerce", utc=True)
    after_observed = pd.Timestamp(observed, tz="UTC") + pd.Timedelta(days=1)
    year = pd.to_numeric(frame["year"], errors="raise")
    flag_values = {
        "before_2018_context": year.lt(2018),
        "filing_year_after_observation": year.gt(observed.year),
        "first_action_missing": first_raw.eq(""),
        "first_action_invalid": first_raw.ne("") & first.isna(),
        "first_action_after_observation": first.ge(after_observed),
        "latest_action_invalid": latest_raw.ne("") & latest.isna(),
        "latest_action_after_observation": latest.ge(after_observed),
        "latest_precedes_first_action": latest.lt(first),
        "blank_title": frame["title"].fillna("").str.strip().eq(""),
        "unknown_sponsor_party": frame["sponsor_party"].eq("unknown"),
        "unresolved_primary_sponsor": frame["n_unresolved_primary_sponsors"].gt(0),
        "no_sponsors": frame["n_sponsors"].eq(0),
        "all_sponsors_fallback": frame["sponsor_attribution_basis"].eq("all_sponsors_fallback"),
        "no_dated_attribution_proxy": (
            frame["party_attribution_date_basis"].ne("first_action_proxy")
        ),
        "no_recorded_actions": frame["n_actions"].eq(0),
        "no_recorded_vote_events": frame["n_vote_events"].eq(0),
        "no_nonempty_abstract": frame["n_nonempty_abstracts"].eq(0),
        "no_nonempty_source_url": frame["n_nonempty_source_urls"].eq(0),
        "no_nonempty_version_url": frame["n_nonempty_version_urls"].eq(0),
    }
    keys = ["bill_id", "state", "session_identifier", "session_year", "year"]
    flags = frame[keys].copy()
    for name, values in flag_values.items():
        flags[name] = values
    flags["n_source_context_bills"] = 1
    counters = ["n_source_context_bills", *flag_values]
    by_session = flags.groupby(keys[1:], dropna=False)[counters].sum().reset_index()
    by_state = flags.groupby("state")[counters].sum().reindex(sorted(expected), fill_value=0)
    by_state["source_row_status"] = by_state["n_source_context_bills"].map(
        lambda count: "observed_source_rows" if count else "no_retained_source_rows"
    )
    by_state = by_state.reset_index()
    summary = {
        "schema_version": 1, "generated_at": utc_now_iso(), "observed_on": observed_on,
        "status": "source_inventory_not_scientific_certification", "analysis_cutoff": None,
        "n_source_context_bills": len(frame), "states_with_source_rows": frame["state"].nunique(),
        "counts": {name: int(values.sum()) for name, values in flag_values.items()},
        "sponsor_party_counts": frame["sponsor_party"].value_counts().to_dict(),
        "attribution_date_basis_counts": (
            frame["party_attribution_date_basis"].value_counts().to_dict()
        ),
        "limitations": [
            "Source rows have not been reconciled to official state legislative universes.",
            "Session context can include pre-2018 records; it is not an analytical denominator.",
            "The observation date flags future source events, not a certified analytical cutoff.",
            "Future latest-action dates may be scheduled effective dates; review, do not erase.",
            "Missing actions, votes or text concern availability, not bill failure or zero policy.",
            "Abstract/version availability does not establish filing-time timing or accuracy.",
            "Party resolution uses historical memberships at a first-action proxy.",
            "No topic predictions, classifier certification or substantive findings are produced.",
        ],
    }
    return summary, by_state, by_session, flags


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--observed-on", required=True, help="explicit YYYY-MM-DD observation date")
    parser.add_argument("--people-archive", type=Path)
    parser.add_argument("--people-revision")
    parser.add_argument("--people-sha256")
    args = parser.parse_args(argv)
    if any((args.people_archive, args.people_revision, args.people_sha256)) and not all(
        (args.people_archive, args.people_revision, args.people_sha256)
    ):
        parser.error("party-history inspection requires archive, revision and SHA-256 together")
    root = args.data_dir
    extraction_path = root / "bill_extraction_manifest.json"
    extraction = json.loads(extraction_path.read_text())
    if extraction.get("status") != "complete_extraction_not_source_certification":
        raise ValueError("source auditing requires a completed extraction manifest")
    for name in ("bills.parquet", "bill_evidence_coverage.parquet"):
        if sha256_file(root / name) != extraction["artifacts"][name]["sha256"]:
            raise ValueError(f"{name}: extraction checksum mismatch")
    columns = [
        "bill_id", "state", "session_identifier", "session_year", "year",
        "first_action_date", "latest_action_date", "title", "sponsor_party",
        "n_unresolved_primary_sponsors", "n_sponsors", "sponsor_attribution_basis",
        "party_attribution_date_basis", "n_actions", "n_vote_events",
    ]
    summary, states, sessions, flags = audit_bill_sources(
        pd.read_parquet(root / "bills.parquet", columns=columns),
        pd.read_parquet(root / "bill_evidence_coverage.parquet"), observed_on=args.observed_on,
    )
    summary["extraction_manifest_sha256"] = sha256_file(extraction_path)
    summary["source_dump_sha256"] = extraction["source_sha256"]
    summary["source_artifacts"] = {
        name: extraction["artifacts"][name]
        for name in ("bills.parquet", "bill_evidence_coverage.parquet")
    }
    summary["artifacts"] = {}
    exports = [
        ("bill_source_state_coverage.csv", states),
        ("bill_source_session_year_coverage.csv", sessions),
        ("bill_source_audit_flags.parquet", flags),
    ]
    if args.people_archive:
        summary["alternative_affiliation_source"] = inspect_party_history_archive(
            args.people_archive, revision=args.people_revision, expected_sha256=args.people_sha256,
        )
        dump_path = Path(extraction["source_path"])
        if sha256_file(dump_path) != extraction["source_sha256"]:
            raise ValueError("party-membership source dump checksum mismatch")
        counts, reference = inspect_dump_party_memberships(dump_path)
        summary["dump_party_membership_inventory"] = counts
        exports.append(("party_membership_reference.parquet", reference))
    for name, frame in exports:
        path = root / name
        partial = path.with_suffix(path.suffix + ".part")
        if name.endswith(".csv"):
            frame.to_csv(partial, index=False)
        else:
            frame.to_parquet(partial, index=False)
        partial.replace(path)
        summary["artifacts"][name] = {"sha256": sha256_file(path), "rows": len(frame)}
    path = root / "bill_source_audit.json"
    partial = path.with_suffix(".json.part")
    partial.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    partial.replace(path)
    print(f"wrote {path}: {len(flags):,} source-context bills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Inventory every retained bill-document reference without certifying its version or text."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import pandas as pd

from ..analysis.revealed import is_source_test_title
from ..platforms.recovery import verify_manifest
from ..provenance import fetch, sha256_file, utc_now_iso
from .openstates_dump import STATE_CODES

_BILL_FIELDS = ["bill_id", "state", "identifier", "session_identifier", "title"]
_VERSION_FIELDS = {"id", "bill_id", "note", "date", "extras", "classification"}
_LINK_FIELDS = {"id", "bill_id", "version_id", "media_type", "url"}
_ORIGINAL_NOTES = frozenset(
    {
        "introduced",
        "introduced version",
        "introduction",
        "as introduced",
        "filed",
        "bill",
        "resolution",
        "joint memorial",
        "joint resolution",
        "concurrent resolution",
        "house introduced bill",
        "senate introduced bill",
        "introduced house bill (h)",
        "introduced senate bill (s)",
    }
)
_LATER_NOTE = re.compile(r"\b(substitute|engrossed|enrolled|amendment|passed)\b")
# Bill numbers recur across sessions; quarantine only the reviewed bill/response pair.
_KNOWN_CONTEXT_CONFLICTS = {
    (
        "ocd-bill/2fc27653-f567-4bb0-b7b1-e7818d05ef55",
        "ae998c9f771f91f7a307433cd8f7c3ce28b0ba43bd28caad9c437e69cb5f23fe",
    ): "1f4a9534cee09411816309c2fb18ea09ed614c5f39668038bf1a66df682c920f",
    (
        "ocd-bill/31eb97a6-bc4c-4a7c-9d69-f463c935deaa",
        "770136eae8feff51faf6cdf53523c7110e25d8899aa490f450caae31d4294fd6",
    ): "1f4a9534cee09411816309c2fb18ea09ed614c5f39668038bf1a66df682c920f",
}
_COUNTS = [
    "n_version_links",
    "n_usable_url_links",
    "n_original_note_links",
    "n_later_note_links",
    "n_unclassified_note_links",
    "n_missing_version_metadata",
]


def _require_ids(frame: pd.DataFrame, column: str) -> None:
    values = frame[column]
    if (
        not values.map(lambda value: isinstance(value, str) and bool(value.strip())).all()
        or values.duplicated().any()
    ):
        raise ValueError(f"{column}: expected unique nonempty source IDs")


def _note_hint(note: object) -> str:
    if not isinstance(note, str):
        return "unclassified_note"
    normalized = " ".join(note.split()).casefold()
    if _LATER_NOTE.search(normalized):
        return "later_note"
    return "original_note" if normalized in _ORIGINAL_NOTES else "unclassified_note"


def _url_plan(url: object) -> tuple[str, str | None, str]:
    if not isinstance(url, str) or not url.strip():
        return "missing_url", None, "none"
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        return "invalid_control_character", None, "none"
    if url != url.strip():
        return "surrounding_whitespace", None, "none"
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        return "malformed_url", None, "none"
    if parsed.scheme not in {"http", "https"}:
        return "unsupported_scheme", None, "none"
    if not host:
        return "missing_host", None, "none"
    if any(character.isspace() for character in parsed.netloc):
        return "invalid_host_whitespace", None, "none"
    if port == 0:
        return "invalid_port", None, "none"
    if any(character.isspace() for character in url):
        request = "".join(
            quote(character, safe="") if character.isspace() else character for character in url
        )
        return "usable_after_encoding_not_network_verified", request, "percent_encode_whitespace"
    return "syntactically_usable_not_network_verified", url, "none"


def build_document_inventory(bills, versions, links):
    """Return complete link candidates, bill coverage and unlinked version metadata."""
    if set(versions) != _VERSION_FIELDS or set(links) != _LINK_FIELDS:
        raise ValueError("unexpected bill version/link source schema")
    _require_ids(bills, "bill_id")
    _require_ids(versions, "id")
    _require_ids(links, "id")
    if not bills["state"].isin({state.upper() for state in STATE_CODES}).all():
        raise ValueError("document inventory accepts only the 50 state jurisdictions")
    bill_ids = set(bills["bill_id"])
    if not versions["bill_id"].isin(bill_ids).all() or not links["bill_id"].isin(bill_ids).all():
        raise ValueError("version/link records refer to bills outside the source inventory")
    base = bills[_BILL_FIELDS].copy()
    base["source_test_record"] = [
        is_source_test_title(title if isinstance(title, str) else "", state)
        for title, state in zip(base["title"], base["state"], strict=True)
    ]
    metadata = versions.rename(
        columns={
            "id": "version_id",
            "bill_id": "version_bill_id",
            "note": "version_note",
            "date": "version_date",
            "extras": "version_extras",
            "classification": "version_classification",
        }
    )
    candidates = links.rename(
        columns={
            "id": "link_id",
            "url": "source_url",
            "media_type": "source_media_type",
        }
    ).merge(metadata, on="version_id", how="left", validate="many_to_one", indicator=True)
    candidates["version_metadata_missing"] = candidates["_merge"].eq("left_only")
    conflicts = ~candidates["version_metadata_missing"] & candidates["bill_id"].ne(
        candidates["version_bill_id"]
    )
    if conflicts.any():
        raise ValueError("link and version disagree about source bill identity")
    candidates = candidates.drop(columns="_merge").merge(
        base,
        on="bill_id",
        how="left",
        validate="many_to_one",
    )
    candidates["version_note_hint"] = candidates["version_note"].map(_note_hint)
    url_plans = [_url_plan(url) for url in candidates["source_url"]]
    for index, column in enumerate(("url_status", "request_url", "url_normalization")):
        candidates[column] = [plan[index] for plan in url_plans]
    candidates["collection_eligible"] = (
        candidates["request_url"].notna() & ~candidates["source_test_record"]
    )
    candidates["version_identity_certified"] = False
    candidates["filing_time_text_certified"] = False
    candidates["analytical_admission"] = False

    flags = (
        pd.DataFrame(
            {
                "bill_id": candidates["bill_id"],
                "n_version_links": 1,
                "n_usable_url_links": candidates["request_url"].notna(),
                "n_original_note_links": candidates["version_note_hint"].eq("original_note"),
                "n_later_note_links": candidates["version_note_hint"].eq("later_note"),
                "n_unclassified_note_links": candidates["version_note_hint"].eq(
                    "unclassified_note"
                ),
                "n_missing_version_metadata": candidates["version_metadata_missing"],
            }
        )
        .groupby("bill_id")[_COUNTS]
        .sum()
    )
    coverage = base.copy()
    for column in _COUNTS:
        coverage[column] = coverage["bill_id"].map(flags[column]).fillna(0).astype("int64")
    coverage["n_versions"] = (
        coverage["bill_id"].map(versions.groupby("bill_id").size()).fillna(0).astype("int64")
    )
    unlinked = versions[~versions["id"].isin(links["version_id"])].copy()
    coverage["n_unlinked_versions"] = (
        coverage["bill_id"].map(unlinked.groupby("bill_id").size()).fillna(0).astype("int64")
    )
    coverage["reference_status"] = "candidate_links_only"
    coverage.loc[coverage["n_usable_url_links"].eq(0), "reference_status"] = "unusable_links_only"
    coverage.loc[coverage["n_version_links"].eq(0), "reference_status"] = "no_retained_version_link"
    coverage.loc[coverage["source_test_record"], "reference_status"] = "excluded_source_test"
    coverage["filing_time_text_certified"] = False
    coverage["analytical_admission"] = False
    return candidates, coverage, unlinked


def freeze_document_inventory(data_dir: Path, out: Path, *, extraction_manifest_sha256: str):
    """Bind the complete reference plan to a completed, checksum-verified source extraction."""
    if out.exists():
        raise FileExistsError(out)
    extraction_path = data_dir / "bill_extraction_manifest.json"
    if sha256_file(extraction_path) != extraction_manifest_sha256:
        raise ValueError("extraction manifest checksum mismatch")
    extraction = json.loads(extraction_path.read_text())
    if extraction.get("status") != "complete_extraction_not_source_certification":
        raise ValueError("document inventory requires a completed source extraction")
    sources = {}
    frames = []
    for name in ("bills.parquet", "bill_versions.parquet", "bill_version_links.parquet"):
        path = data_dir / name
        expected = extraction["artifacts"][name]
        if sha256_file(path) != expected["sha256"]:
            raise ValueError(f"{name}: extraction checksum mismatch")
        frame = pd.read_parquet(path, columns=_BILL_FIELDS if name == "bills.parquet" else None)
        if len(frame) != expected["rows"]:
            raise ValueError(f"{name}: extraction row-count mismatch")
        sources[name] = {"path": str(path.resolve()), **expected}
        frames.append(frame)
    candidates, coverage, unlinked = build_document_inventory(*frames)
    if any(sha256_file(data_dir / name) != value["sha256"] for name, value in sources.items()):
        raise ValueError("source artifacts changed during document inventory")
    state_counts = coverage.groupby("state")[
        [
            "n_versions",
            "n_version_links",
            "n_usable_url_links",
            "n_original_note_links",
            "n_later_note_links",
            "n_unclassified_note_links",
            "n_unlinked_versions",
        ]
    ].sum()
    state_counts["n_source_context_bills"] = coverage.groupby("state").size()
    state_counts["n_bills_with_usable_url"] = coverage.groupby("state")["n_usable_url_links"].agg(
        lambda values: int(values.gt(0).sum())
    )
    out.mkdir(parents=True)
    candidates.to_parquet(out / "document_candidates.parquet", index=False)
    coverage.to_parquet(out / "bill_document_coverage.parquet", index=False)
    unlinked.to_parquet(out / "unlinked_versions.parquet", index=False)
    state_counts.reset_index().to_csv(out / "state_document_coverage.csv", index=False)
    shutil.copyfile(extraction_path, out / extraction_path.name)
    shutil.copyfile(__file__, out / "producer.py")
    shutil.copyfile(
        Path(__file__).parents[1] / "analysis/revealed.py", out / "source_test_guard.py"
    )
    report = {
        "schema_version": 2,
        "status": "reference_inventory_not_text_certification",
        "completed_at": utc_now_iso(),
        "extraction_manifest_sha256": extraction_manifest_sha256,
        "source_artifacts": sources,
        "n_source_context_bills": len(coverage),
        "n_version_records": len(frames[1]),
        "n_version_links": len(candidates),
        "n_unlinked_versions": len(unlinked),
        "n_source_test_records": int(coverage["source_test_record"].sum()),
        "n_bills_with_usable_url": int(coverage["n_usable_url_links"].gt(0).sum()),
        "reference_status_counts": coverage["reference_status"].value_counts().to_dict(),
        "url_status_counts": candidates["url_status"].value_counts().to_dict(),
        "url_normalization_counts": candidates["url_normalization"].value_counts().to_dict(),
        "version_note_hint_counts": candidates["version_note_hint"].value_counts().to_dict(),
        "training_admission": False,
        "analytical_admission": False,
        "limitations": [
            "All links survive, including later/unclassified notes and duplicate URLs.",
            "Original-note hints are claims, not native-version or filing-time verification.",
            "URL syntax checks do not perform DNS, retrieval, native identity or document review.",
            "No retained link does not establish that the publisher has no document.",
            "Previously recovered research captures are separate; no download is counted here.",
            "Source-context bills are not a certified all-state analytical denominator.",
        ],
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    path.name: sha256_file(path) for path in sorted(out.iterdir()) if path.is_file()
                },
            },
            indent=2,
        )
        + "\n"
    )
    return report


def collect_document_candidates(
    inventory: Path,
    out: Path,
    *,
    inventory_manifest_sha256: str,
    link_ids: set[str],
    transport=None,
    sleep=time.sleep,
):
    """Retain an explicit reference batch without inferring version or text admission."""
    import pyarrow.parquet as pq

    if out.exists():
        raise FileExistsError(out)
    if not link_ids or any(not isinstance(value, str) or not value.strip() for value in link_ids):
        raise ValueError("collection requires explicit nonempty source link IDs")
    if sha256_file(inventory / "manifest.json") != inventory_manifest_sha256:
        raise ValueError("document inventory manifest checksum mismatch")
    verify_manifest(inventory, {"document_candidates.parquet", "report.json", "producer.py"})
    inventory_report = json.loads((inventory / "report.json").read_text())
    if (
        inventory_report.get("schema_version") != 2
        or inventory_report.get("status") != "reference_inventory_not_text_certification"
    ):
        raise ValueError("collection requires a schema-2 request-URL inventory")
    selected = pq.read_table(
        inventory / "document_candidates.parquet",
        filters=[("link_id", "in", sorted(link_ids))],
    ).to_pandas()
    if set(selected["link_id"]) != link_ids or selected["link_id"].duplicated().any():
        raise ValueError("selected source link IDs do not match the retained inventory")
    selected = selected.sort_values("link_id").reset_index(drop=True)
    out.mkdir(parents=True)
    selected.to_parquet(out / "selected_candidates.parquet", index=False)
    shutil.copyfile(inventory / "manifest.json", out / "inventory_manifest.json")
    shutil.copyfile(__file__, out / "producer.py")
    shutil.copyfile(Path(__file__).parents[1] / "provenance.py", out / "retrieval_helper.py")
    receipts, retained, skipped, quarantined = [], set(), [], set()
    for index, row in enumerate(selected.to_dict("records")):
        if not row["collection_eligible"]:
            skipped.append(
                {
                    "link_id": row["link_id"],
                    "reason": "source_test_record"
                    if row["source_test_record"]
                    else row["url_status"],
                }
            )
            continue
        request = row["request_url"]
        for attempt_kind in ("recorded_request", "https_alternative"):
            if attempt_kind == "https_alternative":
                if urlsplit(request).scheme != "http":
                    break
                request = "https:" + request[len("http:") :]
            source_file = f"source/{index:07d}_{attempt_kind}.bin"
            _, record = fetch(
                request,
                source_org=f"{row['state']} legislative document source",
                dest=out / source_file,
                transport=transport,
                sleep=sleep,
                timeout=45,
                max_attempts=2,
                max_bytes=32 * 1024 * 1024,
                note="research candidate; native version and filing-time identity unverified",
            )
            context_review = (
                _KNOWN_CONTEXT_CONFLICTS.get((row["bill_id"], record.content_sha256))
                if record.ok
                else None
            )
            receipt = {
                **record.to_dict(),
                "link_id": row["link_id"],
                "bill_id": row["bill_id"],
                "source_url": row["source_url"],
                "url_normalization": row["url_normalization"],
                "attempt_kind": attempt_kind,
                "source_file": source_file if record.ok else None,
                "native_context_status": "quarantined_known_cross_session_document"
                if context_review
                else "not_reviewed",
                "context_review_manifest_sha256": context_review,
            }
            receipts.append(receipt)
            with (out / "receipts.jsonl").open("a") as stream:
                stream.write(json.dumps(receipt, allow_nan=False) + "\n")
            sleep(1.1)
            if record.ok:
                retained.add(row["link_id"])
                if context_review:
                    quarantined.add(row["link_id"])
                break
    if not receipts:
        (out / "receipts.jsonl").touch()
    excluded = set(selected.loc[selected["source_test_record"], "link_id"])
    unresolved = sorted(link_ids - retained - excluded)
    report = {
        "schema_version": 2,
        "completed_at": utc_now_iso(),
        "status": "completed_with_unresolved_links"
        if unresolved
        else "completed_with_quarantined_documents"
        if quarantined
        else "source_capture_not_certified",
        "inventory_manifest_sha256": inventory_manifest_sha256,
        "selected_link_ids": sorted(link_ids),
        "n_retained_links": len(retained),
        "n_fetch_receipts": len(receipts),
        "n_failed_receipts": sum(not receipt["ok"] for receipt in receipts),
        "n_transport_attempts": sum(receipt["attempts"] for receipt in receipts),
        "skipped_links": skipped,
        "unresolved_link_ids": unresolved,
        "quarantined_link_ids": sorted(quarantined),
        "native_document_identity_review": "known_conflict_fingerprints_only_not_certification",
        "filing_time_text_certified": False,
        "training_admission": False,
        "analytical_admission": False,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    str(path.relative_to(out)): sha256_file(path)
                    for path in sorted(out.rglob("*"))
                    if path.is_file()
                },
            },
            indent=2,
        )
        + "\n"
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    inventory.add_argument("--extraction-manifest-sha256", required=True)
    capture = commands.add_parser("collect")
    capture.add_argument("--inventory", required=True, type=Path)
    capture.add_argument("--inventory-manifest-sha256", required=True)
    capture.add_argument("--link-id", action="append", required=True)
    for command in (inventory, capture):
        command.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "inventory":
        report = freeze_document_inventory(
            args.data_dir,
            args.out,
            extraction_manifest_sha256=args.extraction_manifest_sha256,
        )
    else:
        report = collect_document_candidates(
            args.inventory,
            args.out,
            inventory_manifest_sha256=args.inventory_manifest_sha256,
            link_ids=set(args.link_id),
        )
    print(json.dumps(report, indent=2, allow_nan=False))
    print("Manifest:", sha256_file(args.out / "manifest.json"))
    return 1 if report.get("unresolved_link_ids") or report.get("quarantined_link_ids") else 0


if __name__ == "__main__":
    raise SystemExit(main())

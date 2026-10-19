"""Inventory external state-bill codes without admitting them as evaluation gold."""

from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path

from .prepare_topics import _shingles, normalized_text


def read_source_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    """Keep every original string and distinguish logical records from physical lines."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if not required <= set(fields) or len(fields) != len(set(fields)):
            raise ValueError(f"{path}: missing or duplicate source columns")
        rows = []
        for number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}: malformed logical CSV record {number}")
            rows.append(row)
    if not rows:
        raise ValueError(f"{path}: empty source")
    return rows


def source_profile(rows: list[dict[str, str]]) -> dict:
    return {
        "n_rows": len(rows),
        "columns": list(rows[0]),
        "year_counts": dict(sorted(Counter(row["year"] for row in rows).items())),
        "major_counts": dict(sorted(Counter(row["majortopic"] for row in rows).items())),
        "nonblank_external_titles": sum(bool(row.get("Bill_Title", "").strip()) for row in rows),
    }


def bind_florida(
    rows: list[dict[str, str]], bills: list[dict], codes: set[int], *, min_year: int = 2018,
) -> list[dict]:
    """Link literal regular-session contexts; never repair IDs or infer label equivalence."""
    contexts = defaultdict(list)
    seen_bills = set()
    for bill in bills:
        if bill["state"] != "FL":
            continue
        fields = ("bill_id", "session_identifier", "identifier", "title")
        if any(not isinstance(bill.get(field), str) or not bill[field].strip()
               for field in fields):
            raise ValueError(
                "Florida source context requires nonempty string identity/title fields"
            )
        if bill["bill_id"] in seen_bills:
            raise ValueError("duplicate Florida source bill ID")
        seen_bills.add(bill["bill_id"])
        contexts[(bill["session_identifier"], bill["identifier"])].append(bill)
    parsed = []
    for row in rows:
        match = re.fullmatch(r"(HB|SB)\s*(\d+)", row["id"])
        parsed.append(f"{match[1]} {int(match[2])}" if match else None)
    counts = Counter((row["year"], key) for row, key in zip(rows, parsed, strict=True) if key)
    result = []
    for number, (row, key) in enumerate(zip(rows, parsed, strict=True), 2):
        year = row["year"]
        flags = ["annotation_provenance_unresolved", "rubric_mapping_unreviewed",
                 "external_subtopic_unavailable"]
        if not row["Bill_Title"].strip():
            flags.append("external_title_missing")
        if not row["majortopic"].isdecimal() or int(row["majortopic"]) not in codes:
            flags.append("unsupported_external_major")
        in_window = bool(re.fullmatch(r"\d{4}", year)) and int(year) >= min_year
        matches = contexts.get((year, key), []) if in_window and key else []
        if not in_window:
            status = "outside_year_window"
        elif key is None:
            status = "unparsed_external_identifier"
        elif not matches:
            status = "missing_source_context"
        elif len(matches) != 1:
            status = "ambiguous_source_context"
        else:
            status = "unique_source_context"
        if key and counts[(year, key)] > 1:
            flags.append("duplicate_external_context")
        bill_match = matches[0] if len(matches) == 1 else None
        title = bill_match["title"] if bill_match else None
        if bill_match:
            flags.append("candidate_title_version_unverified")
        result.append({
            "record_id": f"cap:florida:csv-record-{number}",
            "source_csv_record_number": number,
            "source_id": row["id"], "source_year": year,
            "source_major": row["majortopic"], "source_title": row["Bill_Title"],
            "parsed_identifier": key, "link_status": status,
            "source_context_bill_ids": sorted(bill["bill_id"] for bill in matches),
            "matched_bill_id": bill_match["bill_id"] if bill_match else None,
            "candidate_title": title,
            "candidate_title_sha256": (
                hashlib.sha256(title.encode()).hexdigest() if title is not None else None
            ),
            "review_flags": sorted(flags),
            "training_admission": False, "evaluation_admission": False,
            "analytical_admission": False, "independent_gold": False,
        })
    return result


class ReferenceIndex:
    """Retain all exact/near text witnesses, including short exact copies and aliases."""

    def __init__(self, rows: list[dict[str, str]]):
        owners = defaultdict(set)
        for row in rows:
            if not isinstance(row.get("text"), str) or not normalized_text(row["text"]):
                raise ValueError("reference text must be nonempty")
            if not isinstance(row.get("record_id"), str) or not row["record_id"]:
                raise ValueError("reference identity must be nonempty")
            owners[normalized_text(row["text"])].add(row["record_id"])
        self.owners = {key: sorted(values) for key, values in owners.items()}
        self.signatures = {key: _shingles(key) for key in owners}
        self.inverted = defaultdict(set)
        for key, signature in self.signatures.items():
            for shingle in signature:
                self.inverted[shingle].add(key)

    def overlaps(self, text: str) -> dict[str, list[str]]:
        normalized = normalized_text(text)
        signature = _shingles(text)
        possible = set().union(*(self.inverted.get(shingle, set()) for shingle in signature))
        near = set()
        for key in possible - {normalized}:
            other = self.signatures[key]
            if (
                min(len(signature), len(other)) / max(len(signature), len(other)) >= 0.8
                and len(signature & other) / len(signature | other) >= 0.8
            ):
                near.update(self.owners[key])
        return {
            "exact_text_reference_ids": self.owners.get(normalized, []),
            "near_text_reference_ids": sorted(near),
        }

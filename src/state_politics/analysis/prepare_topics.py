"""Prepare a frozen, provisional external-label initialization corpus, never evaluation gold."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from ..provenance import sha256_file, utc_now_iso
from .taxonomy import DEFAULT_TOPICS_PATH, load_topics
from .train_topics import load_examples

SOURCES = (
    (
        "congressional_bills.csv", "bill",
        "https://minio.la.utexas.edu/compagendas/datasetfiles/"
        "US-Legislative-congressional_bills_19.3_3_3%20%281%29.csv",
        "28662e351835aa6c78abee931427f1c5a245f3cfd93fff7d11aadfbd95761230",
    ),
    (
        "democratic_platforms.csv", "plank",
        "https://minio.la.utexas.edu/compagendas/datasetfiles/Dem_partyplatform_20.2.csv",
        "42bfe406468aeeac22a3c16a61d1bb1e1cbc2ce3e5020fc6bbea1a433043de3a",
    ),
    (
        "republican_platforms.csv", "plank",
        "https://minio.la.utexas.edu/compagendas/datasetfiles/US-Party-Rep_Platform_19.3_0.csv",
        "863d24341ae7be71def0f50e97524bd2aed0635a3cc76b8f49c6fddb80ff8907",
    ),
)
LABEL_VERSION = "cap_major_initialization_v1_not_project_gold"
SOURCE_USE_URL = "https://www.comparativeagendas.net/pages/Copyright-and-Legal"
REVIEWED_CODE_MIGRATIONS = {("23", "2300", "6", "609")}
ADAPTED_SUBTOPIC_BOUNDARIES = {
    "1208": "adapted_family_boundary",
    "1308": "adapted_child_care_leave_boundary",
    "1405": "adapted_rural_development_boundary",
    "1526": "adapted_sports_boundary",
    "2030": "adapted_holiday_boundary",
    "2101": "adapted_historic_site_boundary",
}


def normalized_text(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()


def compatibility_flags(row: dict, codes: set[int], min_year: int) -> list[str]:
    """Quarantine known incompatibilities; absence of a flag is not label certification."""
    flags = []
    major = row["majortopic"].strip()
    subtopic = row["subtopic"].strip()
    text = row["description"].strip()
    if not major.isdecimal() or int(major) not in codes:
        flags.append("unsupported_major_code")
    if not subtopic.isdecimal() or (
        major.isdecimal() and int(subtopic) // 100 != int(major)
    ):
        flags.append("major_subtopic_disagreement")
    source_codes = (
        major, subtopic, row["pap_majortopic"].strip(), row["pap_subtopic"].strip()
    )
    if source_codes not in REVIEWED_CODE_MIGRATIONS and (
        source_codes[2] != major or source_codes[3] != subtopic
    ):
        flags.append("source_code_versions_disagree")
    if not row["year"].strip().isdecimal() or int(row["year"]) < min_year:
        flags.append("outside_initialization_year_window")
    if len(text.split()) < 12:
        flags.append("short_context_dependent_unit")
    if re.search(r"√|Ã|Â|â[€™œž]", text):
        flags.append("text_encoding_review")
    if major == "2" and subtopic in ("202", "208"):
        flags.append("rights_reproductive_health_boundary")
    if major != "3" and re.search(
        r"\b(?:abortion|reproductive|contraception|contraceptive)\b", text, re.I
    ):
        flags.append("rights_reproductive_health_boundary")
    if major != "1" and re.search(r"\btax(?:es|ation|payer|payers)?\b", text, re.I):
        flags.append("adapted_tax_boundary")
    if major == "20" and subtopic == "2011":
        flags.append("voting_rights_administration_boundary")
    if subtopic in ADAPTED_SUBTOPIC_BOUNDARIES:
        flags.append(ADAPTED_SUBTOPIC_BOUNDARIES[subtopic])
    return sorted(set(flags))


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = normalized_text(text).split()
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def near_overlap(text: str, references: list[set[tuple[str, ...]]]) -> bool:
    """Conservatively quarantine close textual copies, not infer shared legislative origin."""
    signature = _shingles(text)
    if not signature:
        return False
    for other in references:
        if (
            other
            and min(len(signature), len(other)) / max(len(signature), len(other)) >= 0.8
            and len(signature & other) / len(signature | other) >= 0.8
        ):
            return True
    return False


def prepare(
    cap_dir: Path,
    codes: list[int],
    *,
    per_source_topic: int,
    min_year: int,
    seed: int,
    reviewed: list[dict],
    sources=SOURCES,
) -> tuple[list[dict], dict]:
    """Prepare initialization rows, rejecting conflicting eligible duplicate labels."""
    if per_source_topic < 1:
        raise ValueError("per-source-topic must be positive")
    if any(row["label_origin"] != "reviewed_target" for row in reviewed):
        raise ValueError("target review file must not contain external labels or predictions")
    reserved = {normalized_text(row["text"]) for row in reviewed}
    reference_shingles = [_shingles(row["text"]) for row in reviewed]
    seen = set(reserved)
    external_labels = {}
    chosen = []
    source_reports = []
    for filename, domain, url, expected_sha in sources:
        path = cap_dir / filename
        actual_sha = sha256_file(path)
        if actual_sha != expected_sha:
            raise ValueError(f"{filename}: frozen source checksum mismatch")
        buckets = defaultdict(list)
        dispositions = Counter()
        flag_counts = Counter()
        n_raw = 0
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {
                "id", "year", "majortopic", "subtopic", "pap_majortopic",
                "pap_subtopic", "description",
            }
            if not required <= set(reader.fieldnames or []):
                raise ValueError(f"{filename}: source schema changed")
            for number, row in enumerate(reader, 2):
                n_raw += 1
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"{filename}:{number}: malformed CSV row")
                flags = compatibility_flags(row, set(codes), min_year)
                flag_counts.update(flags)
                if flags:
                    dispositions["quarantined"] += 1
                    continue
                text = row["description"].strip()
                fingerprint = normalized_text(text)
                topic = int(row["majortopic"])
                previous = external_labels.get(fingerprint)
                if previous is not None and previous[0] != topic:
                    raise ValueError(
                        f"{filename}:{number}: conflicting external labels for normalized "
                        f"duplicate text: topic {topic} versus topic {previous[0]} "
                        f"at {previous[1]}:{previous[2]}"
                    )
                if fingerprint in seen:
                    dispositions["exact_duplicate_or_target_overlap"] += 1
                    continue
                external_labels[fingerprint] = (topic, filename, number)
                seen.add(fingerprint)
                record_id = f"cap:{Path(filename).stem}:row-{number}"
                group = (
                    row.get("bill_id") if domain == "bill" else row["year"]
                )
                if not group:
                    raise ValueError(f"{filename}:{number}: missing source family identifier")
                candidate = {
                    "record_id": record_id,
                    "group_id": f"cap:{Path(filename).stem}:{group}",
                    "split": "train", "domain": domain, "text": text,
                    "source_url": url, "source_sha256": actual_sha,
                    "source_record_id": row["id"], "source_csv_line": number,
                    "source_major": row["majortopic"], "source_subtopic": row["subtopic"],
                    "year": int(row["year"]), "label_origin": "external_coded",
                    "label_version": LABEL_VERSION, "topic": topic,
                    "evidence_tier": (
                        "external_bill_description" if domain == "bill"
                        else "external_national_platform_quasi_sentence"
                    ),
                    "source_use_url": SOURCE_USE_URL,
                    "source_license": "CC-BY-NC-SA-4.0 for project-generated variables; "
                    "original-text rights may also apply",
                    "compatibility_status": "provisional_initialization_not_gold",
                }
                priority = hashlib.sha256(f"{seed}:{record_id}".encode()).hexdigest()
                buckets[topic].append((priority, candidate))
                dispositions["eligible_initialization_candidate"] += 1
        source_selected = []
        overlap_count = 0
        for bucket in buckets.values():
            for _, candidate in sorted(bucket, key=lambda item: item[0]):
                if near_overlap(candidate["text"], reference_shingles):
                    overlap_count += 1
                    continue
                source_selected.append(candidate)
                if sum(item["topic"] == candidate["topic"] for item in source_selected) >= (
                    per_source_topic
                ):
                    break
        chosen.extend(source_selected)
        source_reports.append({
            "filename": filename, "source_url": url, "sha256": actual_sha,
            "n_raw": n_raw, "dispositions": dict(dispositions),
            "quarantine_flags_overlapping": dict(flag_counts),
            "selected": len(source_selected),
            "target_near_copy_candidates_rejected": overlap_count,
            "selected_topic_counts": dict(Counter(row["topic"] for row in source_selected)),
        })
    chosen.extend(reviewed)
    return chosen, {
        "schema_version": 1, "created_at": utc_now_iso(),
        "preparation_code_sha256": sha256_file(__file__),
        "status": "provisional_initialization_not_independent_validation",
        "seed": seed, "minimum_external_year": min_year,
        "reviewed_code_migrations": sorted(REVIEWED_CODE_MIGRATIONS),
        "per_source_topic_cap": per_source_topic, "sources": source_reports,
        "split_counts": dict(Counter(row["split"] for row in chosen)),
        "training_topic_counts": dict(Counter(
            row["topic"] for row in chosen
            if row["split"] == "train" and row["topic"] is not None
        )),
        "training_abstention_count": sum(
            row["split"] == "train" and row["topic"] is None for row in chosen
        ),
        "limitations": [
            "External numeric codes are provisional initialization labels, not project gold.",
            "Quarantine rules detect known conflicts; they do not prove remaining compatibility.",
            "National/historical descriptions and quasi-sentences differ from state policy units.",
            "Culture initialization covers arts, not the full adapted family/moral category.",
            "Family, child-care/leave, rural-development, sports, holiday and historic-site "
            "subtopics require adapted-scope review; quarantine is not a corrected topic label.",
            "Exact/close textual copies excluded; paraphrased legislative families need review.",
            "Assistant review is not independent human gold; no certification or publication.",
            "Source-use constraints retained; source/weight redistribution is not authorized.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap-dir", type=Path, default=Path("data/raw/cap"))
    parser.add_argument("--reviewed-target", type=Path)
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-source-topic", type=int, default=100)
    parser.add_argument("--min-year", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261018)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite {args.out}")
    codes = [topic.code for topic in load_topics(args.topics)]
    reviewed = load_examples(args.reviewed_target, codes) if args.reviewed_target else []
    rows, report = prepare(
        args.cap_dir, codes, per_source_topic=args.per_source_topic,
        min_year=args.min_year, seed=args.seed, reviewed=reviewed,
    )
    report["taxonomy_sha256"] = sha256_file(args.topics)
    report["reviewed_target_sha256"] = (
        sha256_file(args.reviewed_target) if args.reviewed_target else None
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".topic-labels-", dir=args.out.parent) as directory:
        staging = Path(directory)
        labels = staging / "labels.jsonl"
        labels.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        load_examples(labels, codes)
        report["labels_sha256"] = sha256_file(labels)
        (staging / "source_manifest.json").write_text(json.dumps(report, indent=2) + "\n")
        staging.rename(args.out)
    print(json.dumps({
        "out": str(args.out), "split_counts": report["split_counts"],
        "training_topic_counts": report["training_topic_counts"], "status": report["status"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

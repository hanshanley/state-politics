"""Build a source-bound, assistant-reviewed research curriculum, not independent gold."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd

from ..provenance import sha256_file, utc_now_iso
from .prepare_topics import _shingles, near_overlap
from .taxonomy import DEFAULT_TOPICS_PATH, load_topics
from .train_topics import label_support, load_examples

INVENTORY = Path("data/processed/recovery-source-inventory-v7")
CAPTURES_SHA256 = "2a01d8c4da98676fd568ec45093ea1d7ab0d225949ebdcf03eb273eed8a8edf2"
BASE_LABELS = Path("data/labels/cap-target-rejection-pilot-v1/labels.jsonl")
BASE_SHA256 = "693195cc478fcc65003ef30da005824b2c884dc59fd9636cb5b26ea51ccf44fe"
DEVELOPMENT = Path("data/processed/platform-label-support-audit-v2/development-metadata-only.jsonl")
SOURCES = {
    "IA-R": "ae7d5d14f996cf2bbf15e5e33be9b43905d8b0bbb174fa6fe6f6de9093639822",
    "AZ-D": "dbbcf91a5792bb84e3b033b176c25fd5f1d934708b66c93b6669cdd0e1c57333",
    "IA-D": "fe2cbf06fd6eed53edea7b745378fea3b646d19c1cf8ee768a228282ebf289bf",
    "NM-D": "61e4a72fd57420ac329fd40f15f0f72d52106cc52661d59a02ab21fda3f4cb28",
}
IOWA_SECTIONS = (
    "Life",
    "Liberty",
    "Property",
    "National Sovereignty & Defense",
    "Commerce",
    "Government",
)
IOWA_REVIEW = (
    (
        "Property",
        8,
        1,
        "Property-tax elimination and an interim age-related tax freeze are fiscal policy.",
    ),
    (
        "Government",
        5,
        1,
        "Changes the income-tax system; it is not general governmental structure.",
    ),
    (
        "Liberty",
        1,
        2,
        "Changes protected classes in civil-rights law, regardless of its exclusionary stance.",
    ),
    (
        "Government",
        34,
        2,
        "Protects personal-data privacy against warrantless governmental collection.",
    ),
    ("Life", 3, 3, "Regulates end-of-life medical care and assisted death."),
    ("Liberty", 20, 3, "Requires patient billing transparency in outpatient health care."),
    ("Commerce", 15, 4, "Regulates vaccines administered to livestock, not human health services."),
    ("Commerce", 4, 5, "Changes public-sector union rights, not the structure of government."),
    ("Commerce", 11, 6, "Changes student-loan financing and higher-education debt policy."),
    (
        "Commerce",
        1,
        7,
        "Opposes climate mandates and carbon capture; opposition does not change the topic.",
    ),
    (
        "National Sovereignty & Defense",
        1,
        9,
        "Sets immigration admissions, enforcement and legalization policy.",
    ),
    (
        "National Sovereignty & Defense",
        7,
        9,
        "Requires employment eligibility checks for immigration enforcement.",
    ),
    ("Commerce", 7, 10, "Reviews hours-of-service and electronic-log regulations for trucking."),
    ("Liberty", 11, 12, "Changes criminal asset-seizure and forfeiture procedures."),
    ("Government", 19, 12, "Supports the death penalty, a criminal-sentencing policy."),
    ("National Sovereignty & Defense", 10, 12, "Criminalizes and prosecutes human trafficking."),
    ("Property", 10, 14, "Changes tenant and squatter possession rights, a housing-tenure policy."),
    (
        "Commerce",
        13,
        15,
        "Deregulates the alcohol-distribution market, not moral attitudes to alcohol.",
    ),
    (
        "National Sovereignty & Defense",
        5,
        16,
        "Changes veterans' health benefits; the beneficiary-specific topic is veterans.",
    ),
    (
        "National Sovereignty & Defense",
        13,
        16,
        "Maintains an overseas military installation, not diplomatic recognition.",
    ),
    (
        "Government",
        33,
        17,
        "Requires oversight of AI applications across sectors; AI governance is the common object.",
    ),
    (
        "Commerce",
        12,
        18,
        "Changes a foreign country's trading status, not generic international relations.",
    ),
    ("National Sovereignty & Defense", 2, 19, "Recognizes a foreign state's sovereign existence."),
    (
        "National Sovereignty & Defense",
        3,
        19,
        "Sets requirements for agreements with foreign nations.",
    ),
    ("Government", 1, 20, "Changes legislative procedure and omnibus-bill rules."),
    (
        "Government",
        10,
        20,
        "Changes presidential-election institutions, not nondiscriminatory voting access.",
    ),
    (
        "Liberty",
        14,
        None,
        "Combines sexual-abuse criminalization with labelling all AI-generated images.",
    ),
    (
        "Government",
        16,
        None,
        "Combines military/veterans funding with policing and first-responder funding.",
    ),
)
ARIZONA_REVIEW = (
    (
        "No one should face discrimination",
        2,
        "Protects against discrimination across classes and activities.",
    ),
    (
        "We support the Voting Rights Act",
        2,
        "Protects voting access against discriminatory restrictions.",
    ),
    (
        "Arizona Democrats believe that human rights are women's rights",
        3,
        "The complete paragraph concerns abortion, pregnancy care and reproductive health.",
    ),
    (
        "Arizona Democrats support universal access",
        3,
        "Supports comprehensive single-payer health insurance, "
        "not general insurance-market regulation.",
    ),
    (
        "Arizona Democrats support the right of workers",
        5,
        "Supports workplace conditions, living wages and collective bargaining.",
    ),
    (
        "We believe in accountability in education",
        6,
        "Funds and oversees public education and tuition.",
    ),
    (
        "Arizona Democrats recognize the urgency",
        7,
        "Commits to greenhouse-gas reduction to address climate change.",
    ),
    (
        "While understanding that our security",
        9,
        "The complete paragraph changes immigration policy and pathways to citizenship.",
    ),
    (
        "Arizona Democrats support the DREAM Act",
        9,
        "Changes immigration status and deferred-action protections.",
    ),
    (
        "Arizona Democrats believe in effective enforcement",
        12,
        "The complete paragraph changes firearm purchasing and gun-safety rules.",
    ),
    (
        "Arizona democrats believe in prison reform",
        12,
        "Changes incarceration and sentencing alternatives; "
        "treatment is part of correctional reform.",
    ),
    (
        "Arizona Democrats support family caregivers",
        13,
        "Supports caregiving families and services for elderly and disabled people.",
    ),
    (
        "Democrats are committed to keeping the sacred trust",
        16,
        "Provides benefits and services specifically to service members and veterans.",
    ),
    (
        "Democrats affirm the inherent right of Arizona tribes",
        21,
        "Addresses tribal self-government, "
        "expressly within the adapted Native American affairs topic.",
    ),
    (
        "Democrats continue to support measures",
        None,
        "Bundles education, infrastructure, housing finance, "
        "business taxes and veterans' employment.",
    ),
)
IOWA_DEMOCRATIC_REVIEW = (
    (5, 4, "Funds farmers' agricultural transition and new farmers."),
    (38, 8, "Improves the electricity grid, not generic infrastructure."),
    (43, 8, "Changes wind and solar net-metering charges."),
    (118, 15, "Protects consumers against predatory lending."),
    (
        119,
        15,
        "Regulates consumer-loan interest and financial-product transparency, "
        "not macroeconomic rates.",
    ),
    (124, 1, "Changes income-tax progressivity."),
    (
        147,
        17,
        "Provides broadband internet access; the Commerce heading does not determine the topic.",
    ),
    (151, 18, "Requires importer-financed inspections of imports, an international-trade rule."),
    (345, 10, "Expands public transportation, including rural service."),
    (710, 13, "Changes eligibility restrictions for food-assistance programs."),
    (714, 13, "Funds foster-care support through age 26."),
)
ARTS_REVIEW = (
    (1, "Funds visual and performing arts and their dissemination."),
    (3, "Provides public art facilities; young beneficiaries do not make it school policy."),
    (5, "Funds arts and humanities institutions, not scientific research."),
)


def section_span(text: str, start: str, end: str | None = None) -> tuple[int, int]:
    if text.count(start) != 1:
        raise ValueError(f"source section is absent or ambiguous: {start!r}")
    left = text.index(start) + len(start)
    return left, text.index(end, left) if end is not None else len(text)


def numbered_span(
    text: str,
    number: int,
    bounds: tuple[int, int] | None = None,
) -> tuple[int, int]:
    left, right = bounds if bounds is not None else (0, len(text))
    matches = list(re.finditer(rf"(?m)^ *{number}\. ", text[left:right]))
    if len(matches) != 1:
        raise ValueError(f"source unit {number} is absent or ambiguous in its scope")
    start = left + matches[0].start()
    prefix_end = left + matches[0].end()
    following = re.search(r"(?m)^ *\d+\. ", text[prefix_end:right])
    end = prefix_end + following.start() if following else right
    unit = text[start:end].rstrip()
    footer = re.search(r"(?<=[.;])\n\s*\d+\s*$", unit)
    if footer:
        unit = unit[: footer.start()].rstrip()
    return start, start + len(unit)


def paragraph_span(text: str, anchor: str) -> tuple[int, int]:
    if text.count(anchor) != 1:
        raise ValueError(f"source paragraph is absent or ambiguous: {anchor!r}")
    anchor_at = text.index(anchor)
    preceding = text.rfind("\n\n", 0, anchor_at)
    start = preceding + 2 if preceding >= 0 else 0
    end = text.find("\n\n", anchor_at)
    end = len(text) if end < 0 else end
    return start, start + len(text[start:end].rstrip())


def build(out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    if sha256_file(INVENTORY / "captures.jsonl") != CAPTURES_SHA256:
        raise ValueError("recovery inventory changed")
    if sha256_file(BASE_LABELS) != BASE_SHA256:
        raise ValueError("original training/development labels changed")
    codes = [topic.code for topic in load_topics(DEFAULT_TOPICS_PATH)]
    original = load_examples(BASE_LABELS, codes)
    development = load_examples(DEVELOPMENT, codes)
    prior_dev = {row["record_id"]: row for row in original if row["split"] == "dev"}
    if {row["record_id"] for row in development} != prior_dev.keys():
        raise ValueError("development metadata successor changes the evaluation population")
    for row in development:
        previous = prior_dev[row["record_id"]]
        for key in (
            "record_id",
            "group_id",
            "split",
            "domain",
            "text",
            "topic",
            "abstention_reason",
            "source_sha256",
            "source_url",
        ):
            if row.get(key) != previous.get(key):
                raise ValueError(f"development semantic content changed: {row['record_id']} {key}")
    captures = {}
    with (INVENTORY / "captures.jsonl").open() as handle:
        for line in handle:
            record = json.loads(line)
            if record["source_sha256"] in SOURCES.values():
                captures.setdefault(record["source_sha256"], record)
    if captures.keys() != set(SOURCES.values()):
        raise ValueError("one or more reviewed source bodies are missing")
    for name, body in SOURCES.items():
        record = captures[body]
        if f"{record['state']}-{record['party']}" != name:
            raise ValueError("source organization mismatch")
        if sha256_file(record["stored_path"]) != body:
            raise ValueError(f"{name}: retained source-body checksum mismatch")
        if hashlib.sha256(record["extracted_text"].encode()).hexdigest() != record["text_sha256"]:
            raise ValueError(f"{name}: complete extraction checksum mismatch")
    out.mkdir(parents=True)
    source_dir = out / "source"
    source_dir.mkdir()
    metadata = {}
    for name, body in SOURCES.items():
        record = captures[body]
        parquet = source_dir / f"{name}.parquet"
        pd.DataFrame(
            [
                {
                    "state": record["state"],
                    "party": record["party"],
                    "url": record["url"],
                    "sha256": body,
                    "text": record["extracted_text"],
                }
            ]
        ).to_parquet(parquet, index=False)
        (source_dir / f"{name}.txt").write_text(record["extracted_text"])
        shutil.copyfile(record["stored_path"], source_dir / f"{name}.bin")
        metadata[name] = {
            "state": record["state"],
            "party": record["party"],
            "source_url": record["url"],
            "source_sha256": body,
            "source_path": str(parquet),
            "source_parquet_sha256": sha256_file(parquet),
            "document_text_sha256": record["text_sha256"],
            "capture_id": record["capture_id"],
        }
    new = []
    quarantine = []

    def add(
        name: str,
        bounds: tuple[int, int],
        topic: int | None,
        rationale: str,
        *,
        scope: str,
        quarantine_reason: str | None = None,
    ) -> None:
        start, end = bounds
        text = captures[SOURCES[name]]["extracted_text"][start:end]
        row = {
            **metadata[name],
            "record_id": f"curriculum-v1:{name}:{start}:{end}",
            "group_id": f"platform-organization:{name}",
            "domain": "plank",
            "text": text,
            "span_start": start,
            "span_end": end,
            "source_scope": scope,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "evidence_tier": "complete_extracted_policy_unit",
            "selection": "purposive_topic_coverage_not_population_sample",
            "extraction_review_status": "selected_native_unit_assistant_checked",
            "label_origin": "reviewed_target",
            "label_version": "diverse_platform_curriculum_v1",
            "reviewer_id": "assistant:gpt-6.1-sol",
            "reviewer_type": "assistant",
            "reviewed_on": utc_now_iso()[:10],
            "rationale": rationale,
            "independent_gold": False,
            "review_status": "provisional_pending_independent_review",
            "operative_platform_status": "unresolved",
            "analytical_admission": False,
        }
        if quarantine_reason:
            quarantine.append(
                {
                    **row,
                    "quarantine_reason": quarantine_reason,
                    "training_admission": False,
                }
            )
        else:
            row.update(topic=topic, split="train", review_disposition="train")
            if topic is None:
                row["abstention_reason"] = (
                    "non_policy" if scope == "document_front_matter" else "mixed_policy"
                )
            new.append(row)

    text = captures[SOURCES["IA-R"]]["extracted_text"]
    for section, number, topic, rationale in IOWA_REVIEW:
        index = IOWA_SECTIONS.index(section)
        end = f"\n{IOWA_SECTIONS[index + 1]}\n" if index + 1 < len(IOWA_SECTIONS) else None
        bounds = section_span(text, f"\n{section}\n", end)
        add("IA-R", numbered_span(text, number, bounds), topic, rationale, scope=section)
    bounds = section_span(text, "\nLiberty\n", "\nProperty\n")
    add(
        "IA-R",
        numbered_span(text, 15, bounds),
        None,
        "Marriage recognition overlaps adapted topics 2 and 23; "
        "do not force a label from its stance.",
        scope="Liberty",
        quarantine_reason="civil_rights_marriage_scope_unadjudicated",
    )
    text = captures[SOURCES["AZ-D"]]["extracted_text"]
    for anchor, topic, rationale in ARIZONA_REVIEW:
        add(
            "AZ-D",
            paragraph_span(text, anchor),
            topic,
            rationale,
            scope="complete_native_paragraph",
        )
    add(
        "AZ-D",
        paragraph_span(text, "We support marriage equality"),
        None,
        "Hold the affirming marriage-rights paragraph at the same boundary "
        "as the opposing Iowa unit.",
        scope="Civil Rights",
        quarantine_reason="civil_rights_marriage_scope_unadjudicated",
    )
    text = captures[SOURCES["IA-D"]]["extracted_text"]
    for number, topic, rationale in IOWA_DEMOCRATIC_REVIEW:
        add("IA-D", numbered_span(text, number), topic, rationale, scope="native_numbered_unit")
    text = captures[SOURCES["NM-D"]]["extracted_text"]
    left, right = section_span(text, "\n Arts\n", "\n Business, Economy, and Revenue Sources\n")
    will = text.index("\n We will:\n", left, right) + len("\n We will:\n")
    for number, rationale in ARTS_REVIEW:
        add(
            "NM-D",
            numbered_span(text, number, (will, right)),
            23,
            rationale,
            scope="Arts > We will",
        )
    left = text.index("\n Arts democracy")
    right = text.index("\n Business, Economy, and Revenue Sources", left)
    add(
        "NM-D",
        (left, right),
        None,
        "Native extraction interleaves the arts and education columns; "
        "this is extraction corruption, "
        "not evidence that the source author wrote a mixed-policy unit.",
        scope="summary_columns",
        quarantine_reason="column_interleaving_requires_reextraction",
    )
    for name in SOURCES:
        text = captures[SOURCES[name]]["extracted_text"]
        end = text.index("\n 1\n") if name == "IA-D" else text.index("\n\n")
        add(
            name,
            (0, end),
            None,
            "Cover or contents metadata, not a policy commitment.",
            scope="document_front_matter",
        )
    reserved = [_shingles(row["text"]) for row in development]
    for row in new:
        if near_overlap(row["text"], reserved):
            raise ValueError(
                f"new training unit is a close development-text copy: {row['record_id']}"
            )
    rows = [row for row in original if row["split"] != "dev"] + development + new
    for name, content in (
        ("new_platform_labels.jsonl", new),
        ("quarantined_units.jsonl", quarantine),
        ("labels.jsonl", rows),
    ):
        (out / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in content)
        )
    validated = load_examples(out / "labels.jsonl", codes)
    for row in new + quarantine:
        source = pd.read_parquet(row["source_path"]).iloc[0]
        if source["text"][row["span_start"] : row["span_end"]] != row["text"]:
            raise ValueError("reviewed span no longer matches its frozen complete source")
    support = label_support(validated, codes)
    report = {
        "created_at": utc_now_iso(),
        "status": "provisional_curriculum_not_independent_gold",
        "base_labels_sha256": sha256_file(BASE_LABELS),
        "development_metadata_sha256": sha256_file(DEVELOPMENT),
        "inventory_captures_sha256": CAPTURES_SHA256,
        "inventory_manifest_sha256": sha256_file(INVENTORY / "manifest.json"),
        "taxonomy_sha256": sha256_file(DEFAULT_TOPICS_PATH),
        "original_training_rows_preserved": sum(row["split"] == "train" for row in original),
        "development_rows_semantically_unchanged": len(development),
        "new_policy_units": sum(row["topic"] is not None for row in new),
        "new_abstentions": dict(
            Counter(row["abstention_reason"] for row in new if row["topic"] is None)
        ),
        "new_topic_counts": dict(Counter(row["topic"] for row in new if row["topic"] is not None)),
        "quarantined_units": len(quarantine),
        "source_documents": list(metadata.values()),
        "label_support": support,
        "limitations": [
            "Assistant-selected curriculum, not random or representative sampling "
            "or independent gold.",
            "Topic coverage is not adequate per-topic, subgroup or subcategory validation.",
            "Only one new Republican organization; party counts do not establish source balance.",
            "Arts examples do not adjudicate the adapted marriage, family or moral category.",
            "Native numbered items may inherit support/opposition from parent scope; "
            "no stance is predicted.",
            "Selected New Mexico arts chapter is coherent; its interleaved summary is quarantined.",
            "Document editions and historical statements are not "
            "current operative policy certification.",
            "Original checkpoint manifests, weights, predictions "
            "and canonical analytical inputs unchanged.",
            "Record/group/text/body/document isolation and close-unit checks "
            "do not settle all source families.",
            "No source-use or model-redistribution permission is granted by this packet.",
        ],
    }
    (out / "preparation.json").write_text(json.dumps(report, indent=2) + "\n")
    shutil.copyfile(__file__, out / "producer.py")
    manifest = {
        "completed_at": utc_now_iso(),
        "files": {
            str(path.relative_to(out)): sha256_file(path)
            for path in sorted(out.rglob("*"))
            if path.is_file()
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build(args.out)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "original_training_rows_preserved",
                    "development_rows_semantically_unchanged",
                    "new_policy_units",
                    "new_abstentions",
                    "new_topic_counts",
                    "quarantined_units",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

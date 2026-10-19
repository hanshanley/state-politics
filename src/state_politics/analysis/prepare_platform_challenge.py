"""Freeze source-disjoint, assistant-reviewed challenge references, not independent gold."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd

from ..provenance import sha256_file, utc_now_iso
from .prepare_platform_curriculum import paragraph_span
from .prepare_topics import _shingles, near_overlap
from .taxonomy import DEFAULT_TOPICS_PATH, load_topics
from .train_topics import label_support, load_examples

POOL = Path("data/labels/platform-challenge-reserved-sources-v1")
POOL_SHA256 = "11d22bd486e2bcd46eaa1171fb1090cea12c682290674c2e6c044b7e00a2deae"
BASE = Path("data/labels/diverse-platform-curriculum-v1/labels.jsonl")
BASE_SHA256 = "3fcb9d5c6f2fefaf7fb40cd83daeb45c9dd4e825391e39a72653ea6812664f1a"

# A missing stop selects the complete blank-line-delimited native paragraph.
REVIEWS = (
    (
        "WA-R",
        "We call for Congress to implement",
        None,
        1,
        "Caps aggregate public spending growth relative to GDP, a macro-fiscal policy.",
    ),
    (
        "WA-R",
        "Our freedom of religion ensures",
        None,
        2,
        "Protects public religious exercise and conscience exemptions, regardless of stance.",
    ),
    (
        "ID-R",
        "We support a private enterprise health care delivery",
        None,
        3,
        "Sets the organization and regulation of health-care delivery.",
    ),
    (
        "ID-R",
        "We endorse the preservation and strengthening of the family farm",
        "ARTICLE V. WATER",
        4,
        "Preserves agricultural family farms, not generic family policy.",
    ),
    (
        "MT-R",
        "Ensure union membership remains strictly voluntary",
        "Maintain a competitive, fair",
        5,
        "Changes union membership and prevailing-wage rules.",
    ),
    (
        "MT-R",
        "School Choice and Funding: Preserve",
        "Local Control: Uphold",
        6,
        "Sets school choice and school-funding allocation.",
    ),
    (
        "WA-R",
        "The Environmental Protection Agency (EPA)",
        None,
        7,
        "Reassigns environmental protection and pollution regulation, not generic administration.",
    ),
    (
        "ID-R",
        "We strongly support energy policies that encourage research",
        None,
        8,
        "Promotes research specifically into energy resources and generation.",
    ),
    (
        "MT-R",
        "Require E-Verify and sanction",
        "Refuse relocation of illegal aliens",
        9,
        "Changes immigration employment verification.",
    ),
    (
        "ID-R",
        "We believe transportation is an integral part",
        None,
        10,
        "Specifies transportation planning and funding authority.",
    ),
    (
        "WA-R",
        "Laws should reduce and deter crime",
        None,
        12,
        "Changes criminal punishment, restitution and offender reintegration.",
    ),
    (
        "MT-R",
        "7. Social Programs:",
        "8. Natural Resources:",
        13,
        "Sets public-assistance eligibility and accountability, not a budget-wide fiscal rule.",
    ),
    (
        "WA-R",
        "We support facilitating the creation",
        None,
        14,
        "Removes regulatory costs and impact fees to expand affordable housing.",
    ),
    (
        "ID-R",
        "A. We recognize the important role of small businesses",
        "B. We support a tax code",
        15,
        "Changes business regulation for small enterprises.",
    ),
    (
        "WA-R",
        "We believe United States armed forces",
        None,
        16,
        "Restricts command authority over armed forces, not generic diplomacy.",
    ),
    (
        "WA-R",
        "To protect national security, we support international",
        None,
        18,
        "Sets reciprocal international trade and import-concentration policy.",
    ),
    (
        "WA-R",
        "United States foreign policy should support",
        None,
        19,
        "Sets diplomatic support for foreign allies and strategic partners.",
    ),
    (
        "MT-R",
        "Oppose Ranked-Choice Voting",
        "Maintain the Electoral College.",
        20,
        "Changes electoral institutions and primary design.",
    ),
    (
        "MT-R",
        "Support transferring federally managed lands",
        "Release Wilderness Study Areas.",
        21,
        "Transfers public-land management and preserves access.",
    ),
    (
        "VT-D",
        "Roll back the regressive Republican tax cuts",
        "Implement tax policies that encourage local investment.",
        1,
        "Reverses tax reductions for high incomes and corporations.",
    ),
    (
        "MN-D",
        "Discrimination against any person on the basis",
        "Government interference in all matters",
        2,
        "Opposes discrimination across protected classes.",
    ),
    (
        "VT-D",
        "Support a national Medicare for All plan",
        "Implement paid family and medical leave",
        3,
        "Creates comprehensive health insurance and pharmaceutical-price negotiation.",
    ),
    (
        "MN-D",
        "Access to farm credit at reasonable terms",
        "Educational research and development programs",
        4,
        "Provides sector-specific agricultural credit and emergency relief.",
    ),
    (
        "VT-D",
        "Support and encourage the right to organize a union",
        "Increase the minimum wage to a living wage.",
        5,
        "Protects union organizing and collective bargaining for workers.",
    ),
    (
        "MN-D",
        "A strong system of public education at all levels",
        "Academic freedom, student and faculty rights",
        6,
        "Funds public schooling and equal educational opportunities.",
    ),
    (
        "VT-D",
        "Encourage the identification and protection of Vermont",
        "Eliminate the use of non-essential",
        7,
        "Protects ecological habitats, wildlife corridors and threatened species.",
    ),
    (
        "MN-D",
        "Increased use of renewable energy sources.",
        "Aggressive energy conservation in transportation",
        8,
        "Promotes renewable energy deployment.",
    ),
    (
        "MN-D",
        "An immigration policy based on respect",
        "We Oppose:\n• Discrimination",
        9,
        "Sets immigration policy, not a general nondiscrimination rule.",
    ),
    (
        "VT-D",
        "Grow public transportation options including commuter rail.",
        "Create pedestrian and bike friendly streets.",
        10,
        "Expands transit and commuter rail services.",
    ),
    (
        "MN-D",
        "Mandatory sentencing practices for drug-related crimes.",
        "Racial, Ethnic, Gender",
        12,
        "Opposes mandatory criminal drug sentencing.",
    ),
    (
        "MN-D",
        "The independent status of Social Security",
        "Full funding of Medicare and Medicaid.",
        13,
        "Protects the public retirement-benefit program and its dedicated funds.",
    ),
    (
        "VT-D",
        "Increase investment in Vermont",
        "Tax corporate ownership of single-family homes",
        14,
        "Funds affordable housing and shelter; the complete paragraph is retained.",
    ),
    (
        "MN-D",
        "Fully funded consumer education and public enforcement",
        "Food quality and labeling standards",
        15,
        "Funds public consumer protection and enforcement against marketplace fraud.",
    ),
    (
        "MN-D",
        "Providing veterans’ benefits to members of the state militia",
        "Providing timely and sufficient funding",
        16,
        "Equalizes deployed Guard/reserve veterans' benefits with active military benefits.",
    ),
    (
        "VT-D",
        "Expand affordable high-speed internet",
        "Support the implementation of President Biden",
        17,
        "Expands broadband and mobile telecommunications infrastructure.",
    ),
    (
        "MN-D",
        "Adequate government funding for research and development",
        "Government agency actions that ensure",
        17,
        "Funds general scientific research, not a sector-specific research program.",
    ),
    (
        "WA-D",
        "Import taxes and tariffs to be based",
        "Stronger antitrust laws that regulators",
        18,
        "Conditions international tariffs on origin-country standards and enforcement.",
    ),
    (
        "MN-D",
        "Foreign aid that helps people achieve",
        "Fair trade policies based on mutual",
        19,
        "Provides foreign development assistance, not domestic public assistance.",
    ),
    (
        "MN-D",
        "A ban on gifts from lobbyists",
        "Disclosure of financial political campaign",
        20,
        "Changes governmental ethics and lobbying rules.",
    ),
    (
        "MN-D",
        "Native American tribes’ rights to self-government",
        "The use of ranked choice voting",
        21,
        "Protects tribal sovereignty and tribal revenue authority in the adapted topic.",
    ),
    (
        "WA-D",
        "Federal, State, and Local governments to provide easy",
        "2134",
        23,
        "Provides public access to diverse art events, exhibits and performances.",
    ),
    (
        "WA-D",
        "Efforts to cut public funding of the arts",
        "Any use of public funding of the arts",
        23,
        "Opposes cutting arts support; stance does not change the policy object.",
    ),
    (
        "MT-R",
        "1. Tax Policy:",
        "2. Role of Government:",
        None,
        "One native priority combines general taxation, markets and international tariffs.",
    ),
    (
        "WA-R",
        "We believe the greatest economic opportunity can best",
        None,
        None,
        "Bundles taxation, business regulation, union rights and prevailing-wage rules.",
    ),
    (
        "MN-D",
        "Equally available and affordable goods and services",
        "Retirement Security",
        None,
        "Enumerates utilities, transportation, credit, insurance, telecom and housing together.",
    ),
    (
        "WA-D",
        "Government regulations that put our society",
        "Transparent, readily accessible accounting",
        None,
        "A complete parent bullet bundles taxes, banking, workforce programs and antitrust.",
    ),
)

QUARANTINES = (
    (
        "MT-R",
        "Recognize that artificial intelligence and digital infrastructure",
        "Assert that reserved State powers",
        "technology_infrastructure_federalism_scope",
        "AI infrastructure, water/energy constraints and federalism overlap; no forced topic.",
    ),
    (
        "ID-R",
        "A. We call upon Idaho government officials and legislators",
        "B. We recognize traditional marriage",
        "marriage_civil_rights_family_scope",
        "The marriage/federalism boundary remains unadjudicated; exclude from scoring.",
    ),
    (
        "VT-D",
        "Affirm and support the safety and well-being of the LGBTQ+",
        "Provide support and outreach to new residents",
        "civil_rights_health_scope",
        "One paragraph combines protected rights and gender-related health coverage.",
    ),
)

FRONT_MATTER = (
    ("MT-R", "Platform of the Montana Republican Party Adopted", "Preamble"),
    (
        "WA-R",
        "2024 WASHINGTON STATE REPUBLICAN PARTY PLATFORM",
        "The Washington State Republican Party stands",
    ),
    ("ID-R", "2026 IDAHO REPUBLICAN", "Table of Contents"),
    (
        "MN-D",
        "Minnesota Democratic-Farmer Labor Party Ongoing Platform",
        "Agriculture, Food, & Land Stewardship",
    ),
    ("WA-D", "2022 WSDCC Platform", "2 Injustice"),
    (
        "VT-D",
        "top of page VERMONT DEMOCRATS Party Platform VDP Staff",
        "VDP Party Platform ADOPTED",
    ),
)


def bounded_span(text: str, anchor: str, stop: str) -> tuple[int, int]:
    """Retain complete native lines between two explicitly reviewed unique markers."""
    if text.count(anchor) != 1:
        raise ValueError("challenge start marker is absent or ambiguous")
    position = text.index(anchor)
    start = text.rfind("\n", 0, position) + 1
    following = text[position + len(anchor) :]
    if following.count(stop) != 1:
        raise ValueError("challenge end marker is absent or ambiguous")
    end_position = position + len(anchor) + following.index(stop)
    end = text.rfind("\n", start, end_position) + 1
    if end <= start:
        raise ValueError("challenge boundaries do not contain a complete native unit")
    return start, start + len(text[start:end].rstrip())


def build(out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    if sha256_file(POOL / "manifest.json") != POOL_SHA256:
        raise ValueError("reserved challenge source packet changed")
    pool_manifest = json.loads((POOL / "manifest.json").read_text())
    for name, digest in pool_manifest["files"].items():
        if sha256_file(POOL / name) != digest:
            raise ValueError(f"reserved source checksum mismatch: {name}")
    if sha256_file(BASE) != BASE_SHA256:
        raise ValueError("the complete preceding training/development manifest changed")
    codes = [topic.code for topic in load_topics()]
    previous = load_examples(BASE, codes)
    reservation = json.loads((POOL / "reservation.json").read_text())
    if reservation["previous_labels_sha256"] != BASE_SHA256:
        raise ValueError("source reservation is not bound to the preceding evidence")
    metadata = {row["organization"]: row for row in reservation["sources"]}
    for row in previous:
        if row["domain"] == "plank" and f"{row.get('state')}-{row.get('party')}" in metadata:
            raise ValueError("a reserved organization already has supervision")
    texts = {name: (POOL / f"{name}.txt").read_text() for name in metadata}
    for name, source in metadata.items():
        if (
            hashlib.sha256(texts[name].encode()).hexdigest() != source["document_text_sha256"]
            or sha256_file(POOL / f"{name}.bin") != source["source_sha256"]
        ):
            raise ValueError("reserved source-body/document hash mismatch")
    out.mkdir(parents=True)
    source_dir = out / "source"
    source_dir.mkdir()
    for name, source in metadata.items():
        parquet = source_dir / f"{name}.parquet"
        pd.DataFrame(
            [
                {
                    "state": source["state"],
                    "party": source["party"],
                    "url": source["source_url"],
                    "sha256": source["source_sha256"],
                    "text": texts[name],
                }
            ]
        ).to_parquet(parquet, index=False)
        for extension in ("bin", "txt"):
            shutil.copyfile(POOL / f"{name}.{extension}", source_dir / f"{name}.{extension}")
        source["source_path"] = str(parquet)
        source["source_parquet_sha256"] = sha256_file(parquet)
    challenge = []
    quarantines = []

    def make(name: str, anchor: str, stop: str | None, rationale: str) -> dict:
        text = texts[name]
        start, end = (
            bounded_span(text, anchor, stop) if stop is not None else paragraph_span(text, anchor)
        )
        selected = text[start:end]
        return {
            **metadata[name],
            "record_id": f"platform-challenge-v1:{name}:{start}:{end}",
            "group_id": f"platform-organization:{name}",
            "domain": "plank",
            "text": selected,
            "span_start": start,
            "span_end": end,
            "text_sha256": hashlib.sha256(selected.encode()).hexdigest(),
            "label_origin": "reviewed_target",
            "label_version": "source_disjoint_challenge_v1",
            "evidence_tier": "complete_extracted_policy_unit",
            "source_scope": "complete_native_unit_with_full_reserved_document",
            "review_context_start": max(0, start - 800),
            "review_context_end": min(len(text), end + 400),
            "review_context": text[max(0, start - 800) : min(len(text), end + 400)],
            "reviewer_id": "assistant:gpt-6.1-sol",
            "reviewer_type": "assistant",
            "reviewed_on": utc_now_iso()[:10],
            "rationale": rationale,
            "independent_gold": False,
            "review_status": "provisional_assistant_reference",
            "selection": "purposive_topic_coverage_not_population_sample",
        }

    for name, anchor, stop, topic, rationale in REVIEWS:
        row = make(name, anchor, stop, rationale)
        row.update(topic=topic, split="challenge", review_disposition="challenge")
        if topic is None:
            row["abstention_reason"] = "mixed_policy"
        challenge.append(row)
    for name, anchor, stop in FRONT_MATTER:
        row = make(
            name,
            anchor,
            stop,
            "Title, adoption metadata, publication description or navigation, not a policy unit.",
        )
        row.update(
            topic=None,
            split="challenge",
            review_disposition="challenge",
            abstention_reason="non_policy",
            evidence_tier="complete_extracted_front_matter",
            source_scope="non_policy_front_matter",
            selection="purposive_non_policy_front_matter",
        )
        challenge.append(row)
    for name, anchor, stop, reason, rationale in QUARANTINES:
        row = make(name, anchor, stop, rationale)
        row["quarantine_reason"] = reason
        quarantines.append(row)
    signatures = [_shingles(row["text"]) for row in previous]
    for index, row in enumerate(challenge):
        if near_overlap(row["text"], signatures):
            raise ValueError(f"challenge unit is a close prior-text copy: {row['record_id']}")
        for other in challenge[:index]:
            if row["organization"] == other["organization"] and (
                max(row["span_start"], other["span_start"])
                < min(row["span_end"], other["span_end"])
            ):
                raise ValueError("challenge references overlap within a source document")
    for name, rows in (
        ("challenge_labels.jsonl", challenge),
        ("quarantined_units.jsonl", quarantines),
        ("labels.jsonl", previous + challenge),
    ):
        (out / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
    validated = load_examples(out / "labels.jsonl", codes)
    for row in challenge + quarantines:
        source = pd.read_parquet(row["source_path"]).iloc[0]
        if source["text"][row["span_start"] : row["span_end"]] != row["text"]:
            raise ValueError("challenge unit does not match its frozen complete source")
    report = {
        "created_at": utc_now_iso(),
        "status": "provisional_source_disjoint_challenge",
        "previous_labels_sha256": BASE_SHA256,
        "reservation_manifest_sha256": POOL_SHA256,
        "taxonomy_sha256": sha256_file(DEFAULT_TOPICS_PATH),
        "n_challenge": len(challenge),
        "topic_counts": dict(
            Counter(row["topic"] for row in challenge if row["topic"] is not None)
        ),
        "party_counts": dict(Counter(row["party"] for row in challenge)),
        "organization_counts": dict(Counter(row["organization"] for row in challenge)),
        "abstention_counts": dict(
            Counter(row["abstention_reason"] for row in challenge if row["topic"] is None)
        ),
        "n_quarantines": len(quarantines),
        "source_documents": list(metadata.values()),
        "label_support": label_support(validated, codes),
        "limitations": [
            "Assistant-reviewed purposive references, not independent human gold or prevalence.",
            "Six held-out organizations, not representative state/party/source-family coverage.",
            "Only two positive units per topic; no stable topic-accuracy or clustered estimates.",
            "Topics 17 and 23 have only Democratic references; no forced Republican labels.",
            "Arts cases do not adjudicate the adapted family/moral category.",
            "Native headings may supply stance; classification predicts topic, not agreement.",
            "Identity and close-unit checks do not settle all near-duplicate source families.",
            "No adoption certification, redistribution permission or production admission.",
            "No original training/development labels, saved model or thresholds changed.",
        ],
    }
    if (
        report["topic_counts"] != dict.fromkeys(codes, 2)
        or report["n_challenge"] != 52
        or report["abstention_counts"] != {"mixed_policy": 4, "non_policy": 6}
    ):
        raise ValueError("reviewed challenge does not have two positive cases in every topic")
    (out / "preparation.json").write_text(json.dumps(report, indent=2) + "\n")
    shutil.copyfile(__file__, out / "producer.py")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "completed_at": utc_now_iso(),
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


def main(argv: list[str] | None = None) -> None:
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
                    "n_challenge",
                    "topic_counts",
                    "party_counts",
                    "organization_counts",
                    "abstention_counts",
                    "n_quarantines",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

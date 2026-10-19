"""Expand provisional platform supervision without changing frozen evaluation references."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd

from ..platforms.recovery import load_json, load_jsonl, verify_manifest
from ..provenance import sha256_file, utc_now_iso
from .prepare_platform_challenge import bounded_span
from .prepare_platform_curriculum import paragraph_span
from .prepare_topics import _shingles, near_overlap
from .taxonomy import DEFAULT_TOPICS_PATH, load_topics
from .train_topics import label_support, load_examples, validate_source_reservation

CONTEXT = Path("data/processed/nonreserved-republican-source-context-v1")
CONTEXT_SHA256 = "84031d84dc4f91e091be314f4e42c928f970363c051eac46156d82b270c627b1"
BASE_LABELS = Path("data/labels/diverse-platform-curriculum-v1/labels.jsonl")
BASE_SHA256 = "3fcb9d5c6f2fefaf7fb40cd83daeb45c9dd4e825391e39a72653ea6812664f1a"
RESERVATION = Path("data/labels/platform-challenge-reserved-sources-v1/reservation.json")
RESERVATION_SHA256 = "11d22bd486e2bcd46eaa1171fb1090cea12c682290674c2e6c044b7e00a2deae"
CHALLENGE = Path("data/labels/source-disjoint-platform-challenge-v1")
CHALLENGE_SHA256 = "b125ba94eb2a77fb2ab48b22ba84e8c3cadef0b286784f603064ee2944796fb8"

# A missing stop selects a complete native paragraph, not a sentence-sized substring.
REVIEW = {
    "KS-R": (
        ("Kansas should change its judicial selection process",
         "We support the use of American law", 12,
         "Changes selection of judges in the court system, not general election administration."),
        ("The Republican Party supports the right of all individuals and groups",
         "The Republican plan empowers people", 2,
         "Protects political expression and debate from governmental interference."),
        ("We oppose the licensing of law-abiding gun and ammunition owners",
         "We affirm the preeminent role", 12,
         "Changes firearm licensing, registration, purchasing and confiscation rules."),
        ("The Veterans Administration needs to provide", "A strong national defense requires", 16,
         "Changes veterans' benefits, employment support and medical-care access; "
         "the beneficiary-specific object is veterans."),
        ("Sanctuary jurisdictions, which are cities", "English is the official language", 9,
         "Changes immigration detainers, sanctuary jurisdictions and immigrant-specific "
         "tuition eligibility, not general policing or education."),
        ("Kansas should support enlarging health savings accounts",
         "Imperative to lowering", 3,
         "Changes financing of health insurance through medical savings accounts; "
         "tax treatment is the health-policy instrument."),
        ("Government should always seek first to constrain its expenditures",
         "The Legislature should periodically", 1,
         "Sets general spending, taxation and property-tax policy."),
        ("Understanding that business, and not government",
         "Equally important, we must create a tax policy", 15,
         "Changes business regulation and the conditions for locating businesses."),
        ("Welfare programs are a temporary last resort",
         "X. BUILDING THE KNOWLEDGE", 13,
         "Changes anti-poverty assistance eligibility, work support and program oversight."),
        ("Our students, upon high school graduation",
         "XI. BUILDING SAFER COMMUNITIES", 6,
         "Changes educational preparation, remediation and higher-education tuition."),
        ("We encourage the development of alternative energy supplies",
         "Kansas leaders should not be allowed", 8,
         "Changes energy supply, industry support and subsidies; economic language "
         "does not replace the energy-policy object."),
        ("We support the use of American law for American courts",
         "III. RESPECTING INDIVIDUAL FREEDOMS", 12,
         "Sets the legal authorities courts may use in their decisions."),
        ("We affirm the rights guaranteed by the Bill of Rights",
         "Local control should be preferred", None,
         "One native paragraph combines religious freedom and searches/privacy with "
         "gun policy and property takings; these are distinct adapted policy objects."),
    ),
    "NE-R": (
        ("We believe the agricultural economy must", None, 4,
         "Changes agricultural market support and transitional commodity programs."),
        ("We support capital punishment for the most heinous crimes", None, 12,
         "Changes criminal sentencing and capital-appeal procedures."),
        ("We support the continuous strengthening of our military", None, 16,
         "Funds military capabilities and regulates military organization and command."),
        ("Homeownership expands personal liberty", None, 14,
         "Promotes homeownership through borrower assistance and housing-market safeguards."),
        ("We support statewide assessments of educational achievement", None, 6,
         "Sets school assessment and testing requirements, including parental consent."),
        ("The Nebraska Republican Party supports reorganizing the presidential primary system",
         None, 20,
         "Changes primary-election institutions and electoral allocation, "
         "rather than nondiscriminatory voting access."),
        ("We support a pragmatic, effective, and reasonable approach", None, 7,
         "Changes environmental protection, regulatory implementation, recycling and planting; "
         "business language describes implementation of that environmental object."),
        ("We acknowledge the importance of coal", None, 8,
         "Changes coal-based electricity generation and replacement supply."),
        ("We call upon Congress to reduce the size of federal government", None, 1,
         "Changes national debt, deficits and balanced-budget requirements."),
        ("In order to give all citizens greater control over their health care options", None, 3,
         "Changes medical savings and health-insurance financing, not general tax policy."),
        ("The Nebraska Republican Party believes that those who cannot provide", None, 13,
         "Supports public and societal assistance for people unable to provide for themselves."),
        ("Mindful of our religious diversity",
         "The Nebraska Republican Party emphasizes its belief", 2,
         "Protects religious expression and voluntary prayer across public institutions; "
         "the complete paragraph continues across a native page gap."),
        ("The Nebraska Republican Party believes foreign policy must", None, 19,
         "Sets principles for foreign relations and the use of food in diplomacy."),
        ("Recognizing the special sacrifices of those that are serving", None, 16,
         "Changes compensation, tax benefits and medical access specifically for "
         "service members, veterans and survivors."),
        ("We support aggressive and judicious recruitment", None, None,
         "One native paragraph combines business recruitment and regulation with "
         "general capital-gains and taxation policies; no single specific intervention dominates."),
        ("Maintaining necessary infrastructure that would include", None, None,
         "One native paragraph combines roads and bridges, enterprise zones, "
         "electronic commerce and rural repopulation, not one transport project."),
    ),
    "HI-R": (
        ("Ensure that public funding follows the student",
         "Give the right of homeschoolers", 6,
         "Education and opportunity > support: changes school-choice funding."),
        ("Eliminating excessive and punitive over-regulation",
         "Providing incentive programs for entrepreneurs", 15,
         "Jobs and wages > support: changes business regulation, not wage or labor rules."),
        ("Upgrading the Information Technology",
         "We oppose:\n\n ● A 100 percent", 17,
         "Jobs and wages > support: develops IT infrastructure and AI technology."),
        ("Land, designated as agricultural",
         "Providing agricultural and aquacultural classes", 4,
         "Agriculture > support: reserves designated agricultural land for farming."),
        ("Eliminating the state individual income tax",
         "Balancing the increase of a tax", 1,
         "Taxation > support: eliminates a general state income tax."),
        ("Reducing bureaucratic delays and streamlining the permitting process",
         "Expanding opportunities for homeowners", 14,
         "Housing affordability > support: changes permitting for housing development."),
        ("The establishment of an adequate local prison system",
         "“Stand your ground” laws", 12,
         "Crime and public safety > support: provides correctional capacity."),
        ("Requiring asylum seekers to apply in the first safe country",
         "Strengthening efforts to combat human trafficking", 9,
         "Immigration > support: changes asylum application rules."),
        ("Maintaining a strong military presence to deter threats",
         "Allowing military training activities", 16,
         "Military > support: maintains military deterrence capabilities."),
        ("A ferry system for transportation within neighboring islands",
         "We oppose:\n\n ● Expanding the Honolulu Rail", 10,
         "Transportation > support: provides inter-island ferry transportation."),
        ("Reactivating the coal plant, implementing alternative energy resources",
         "\n 15\n", 8,
         "Energy > support: changes coal, waste-to-energy and nuclear generation; "
         "the trailing printed page number is not part of this complete bullet."),
        ("Eliminating the Certificate-of-Need (CON)",
         "Incentivizing the creation of private medical practices", 3,
         "Healthcare > support: changes authorization of new medical facilities."),
        ("Passing the 2025 provisions of SB 542",
         "Research alternatives beyond septic tanks", 7,
         "Environment > support: the full parent bullet and all three subitems "
         "change sewage pollution control; grants and tax credits fund that object."),
        ("Legislation that incentivizes nuclear families",
         "Passing legislation that protects life from preborn", None,
         "Family life > support: one complete bullet combines child/general tax relief, "
         "first-home-buyer assistance and small-business assistance."),
    ),
}

QUARANTINE = {
    "KS-R": (
        ("A moral culture is best preserved", "We support the courageous efforts",
         "Marriage recognition and constitutional restrictions overlap adapted civil-rights "
         "and family scopes; the precedence rule remains unadjudicated."),
    ),
    "NE-R": (
        ("The Nebraska Republican Party affirms the family as the natural", None,
         "The intact paragraph includes divorce and marriage recognition; do not settle "
         "the unresolved rights/family boundary by its political stance."),
        ("We believe that Nebraska’s water is a resource", None,
         "Water allocation/ownership and environmental regulation share the paragraph; "
         "the adapted water-supply/environment boundary needs adjudication."),
    ),
    "HI-R": (
        ("Repealing The Jones Act.", "We support:\n\n ● Prayer",
         "The short principles bullet does not spell out the regulated activity; "
         "transportation/trade scope requires additional rubric review."),
        ("‘Olelo Hawai‘i as an official language",
         "Native Hawaiian rights to participate",
         "The complete language bullet includes school curricula and translation services "
         "under Native Hawaiian culture; Native affairs, rights, education and culture "
         "precedence is not settled."),
    ),
}
FRONT_MARKERS = {
    "KS-R": " PREAMBLE\n",
    "NE-R": " Agriculture\n",
    "HI-R": "\n Hawaiʻi Republican Party Platform",
}


def build(out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    for path, digest in (
        (CONTEXT / "manifest.json", CONTEXT_SHA256),
        (BASE_LABELS, BASE_SHA256),
        (RESERVATION.parent / "manifest.json", RESERVATION_SHA256),
        (CHALLENGE / "manifest.json", CHALLENGE_SHA256),
    ):
        if sha256_file(path) != digest:
            raise ValueError(f"frozen curriculum input changed: {path}")
    verify_manifest(CONTEXT, {
        "sources.json", *(f"{name}.{suffix}" for name in REVIEW for suffix in
                          ("bin", "txt", "parquet")),
    })
    verify_manifest(CHALLENGE, {"labels.jsonl"})
    codes = [topic.code for topic in load_topics(DEFAULT_TOPICS_PATH)]
    original = load_jsonl(BASE_LABELS)
    load_examples(BASE_LABELS, codes)
    challenge = load_examples(CHALLENGE / "labels.jsonl", codes)
    if load_jsonl(CHALLENGE / "labels.jsonl")[:len(original)] != original:
        raise ValueError("challenge no longer preserves every original label dictionary")
    reservation = validate_source_reservation(original, RESERVATION)
    sources = load_json(CONTEXT / "sources.json")["sources"]
    if {row["organization"] for row in sources} != set(REVIEW) or len(sources) != len(REVIEW):
        raise ValueError("unexpected or duplicate curriculum source organizations")
    metadata = {}
    texts = {}
    for source in sources:
        name = source["organization"]
        text = (CONTEXT / f"{name}.txt").read_text()
        document = pd.read_parquet(CONTEXT / f"{name}.parquet")
        if (
            len(document) != 1
            or document.iloc[0]["text"] != text
            or document.iloc[0]["sha256"] != source["source_sha256"]
            or document.iloc[0]["url"] != source["source_url"]
            or (document.iloc[0]["state"], document.iloc[0]["party"])
            != (source["state"], source["party"])
            or name != f"{source['state']}-{source['party']}"
            or sha256_file(CONTEXT / f"{name}.bin") != source["source_sha256"]
            or hashlib.sha256(text.encode()).hexdigest() != source["document_text_sha256"]
            or sha256_file(CONTEXT / f"{name}.parquet") != source["source_parquet_sha256"]
        ):
            raise ValueError(f"{name}: complete source identity mismatch")
        texts[name] = text
        metadata[name] = {
            key: source[key] for key in (
                "organization", "state", "party", "source_url", "source_sha256",
                "document_text_sha256", "source_parquet_sha256", "capture_id",
            )
        }
        metadata[name]["source_path"] = str(out / "source" / f"{name}.parquet")
    new = []
    quarantine = []

    def add(name, bounds, topic, rationale, *, scope, quarantined=False):
        start, end = bounds
        text = texts[name][start:end]
        if not 0 <= start < end <= len(texts[name]) or not text.strip():
            raise ValueError(f"{name}: empty or invalid reviewed source span")
        context_start = max(0, start - 800)
        context_end = min(len(texts[name]), end + 800)
        context = texts[name][context_start:context_end]
        row = {
            **metadata[name],
            "record_id": f"republican-curriculum-v1:{name}:{start}:{end}",
            "group_id": f"platform-organization:{name}",
            "domain": "plank", "text": text, "span_start": start, "span_end": end,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "context_start": context_start, "context_end": context_end, "context_text": context,
            "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
            "source_scope": scope,
            "evidence_tier": "complete_extracted_policy_unit",
            "selection": "purposive_nonreserved_source_expansion_not_population_sample",
            "extraction_review_status": "selected_native_unit_assistant_checked",
            "label_origin": "reviewed_target",
            "label_version": "republican_platform_curriculum_v1",
            "reviewer_id": "assistant:gpt-6.1-sol", "reviewer_type": "assistant",
            "reviewed_on": utc_now_iso()[:10], "rationale": rationale,
            "independent_gold": False, "review_status": "provisional_pending_independent_review",
            "operative_platform_status": "unresolved", "analytical_admission": False,
        }
        if quarantined:
            quarantine.append({
                **row, "quarantine_reason": "adapted_scope_or_evidence_unadjudicated",
                "training_admission": False,
            })
        else:
            row.update(topic=topic, split="train", review_disposition="train")
            if topic is None:
                row["abstention_reason"] = (
                    "non_policy" if scope == "document_front_matter" else "mixed_policy"
                )
            new.append(row)

    for name, specifications in REVIEW.items():
        for anchor, stop, topic, rationale in specifications:
            bounds = (
                bounded_span(texts[name], anchor, stop) if stop is not None
                else paragraph_span(texts[name], anchor)
            )
            add(name, bounds, topic, rationale, scope="complete_native_policy_unit")
        for anchor, stop, rationale in QUARANTINE.get(name, ()):
            bounds = (
                bounded_span(texts[name], anchor, stop) if stop is not None
                else paragraph_span(texts[name], anchor)
            )
            add(name, bounds, None, rationale, scope="complete_native_policy_unit",
                quarantined=True)
        marker = FRONT_MARKERS[name]
        if texts[name].count(marker) != 1:
            raise ValueError(f"{name}: front-matter boundary is absent or ambiguous")
        add(name, (0, len(texts[name][:texts[name].index(marker)].rstrip())), None,
            "Cover and version metadata only, not a policy commitment.",
            scope="document_front_matter")

    for name in REVIEW:
        spans = sorted(
            (row["span_start"], row["span_end"]) for row in new + quarantine
            if row["organization"] == name
        )
        if any(left[1] > right[0] for left, right in zip(spans, spans[1:], strict=False)):
            raise ValueError(f"{name}: reviewed curriculum spans overlap")
    held_out = [
        _shingles(row["text"]) for row in challenge if row["split"] != "train"
    ]
    for row in new:
        if near_overlap(row["text"], held_out):
            raise ValueError(f"new training unit closely copies held-out text: {row['record_id']}")
    combined = original + new
    validate_source_reservation(combined, RESERVATION)
    out.mkdir(parents=True)
    (out / "source").mkdir()
    for name in REVIEW:
        for suffix in ("bin", "txt", "parquet"):
            shutil.copyfile(CONTEXT / f"{name}.{suffix}", out / "source" / f"{name}.{suffix}")
    shutil.copyfile(BASE_LABELS, out / "previous_labels.jsonl")
    for name, rows in (
        ("labels.jsonl", combined), ("new_platform_labels.jsonl", new),
        ("quarantined_units.jsonl", quarantine),
    ):
        (out / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        )
    validated = load_examples(out / "labels.jsonl", codes)
    report = {
        "created_at": utc_now_iso(), "status": "provisional_curriculum_not_independent_gold",
        "previous_labels_sha256": BASE_SHA256,
        "source_context_manifest_sha256": CONTEXT_SHA256,
        "source_reservation": reservation,
        "challenge_manifest_sha256": CHALLENGE_SHA256,
        "challenge_labels_sha256": sha256_file(CHALLENGE / "labels.jsonl"),
        "taxonomy_sha256": sha256_file(DEFAULT_TOPICS_PATH),
        "previous_label_dictionaries_preserved": len(original),
        "development_rows_unchanged": sum(row["split"] == "dev" for row in original),
        "challenge_rows_unchanged": sum(row["split"] == "challenge" for row in challenge),
        "new_policy_units": sum(row["topic"] is not None for row in new),
        "new_abstentions": dict(Counter(
            row["abstention_reason"] for row in new if row["topic"] is None
        )),
        "new_topic_counts": dict(Counter(row["topic"] for row in new if row["topic"] is not None)),
        "quarantined_units": len(quarantine),
        "new_organizations": sorted(REVIEW),
        "label_support": label_support(validated, codes),
        "limitations": [
            "Assistant semantic judgments, not independent human gold or representative sampling.",
            "Complete source documents were read; only the selected native units are labelled.",
            "Additional source diversity and mixed examples change together; "
            "a later comparison cannot isolate either effect.",
            "No new family/marriage or Native Hawaiian culture precedence rule is adopted.",
            "Existing development and examined challenge are diagnostics, not a fresh blind test.",
            "Body, document and close-unit checks do not settle "
            "every near-duplicate source family.",
            "No operative-version, analytical, publication or source-use permission certification.",
            "No weights, thresholds or previous references are changed by preparation.",
        ],
    }
    (out / "preparation.json").write_text(json.dumps(report, indent=2) + "\n")
    for filename in (
        "prepare_republican_curriculum.py", "prepare_platform_curriculum.py",
        "prepare_platform_challenge.py", "prepare_topics.py", "train_topics.py",
    ):
        shutil.copyfile(Path(__file__).with_name(filename), out / filename)
    manifest = {
        "completed_at": utc_now_iso(),
        "files": {
            str(path.relative_to(out)): sha256_file(path)
            for path in sorted(out.rglob("*")) if path.is_file()
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build(args.out)
    print(json.dumps({key: report[key] for key in (
        "status", "previous_label_dictionaries_preserved", "development_rows_unchanged",
        "challenge_rows_unchanged", "new_policy_units", "new_abstentions", "new_topic_counts",
        "quarantined_units", "new_organizations",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

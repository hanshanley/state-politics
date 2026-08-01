"""Check the bill-title classifier against subject tags assigned by legislative staff.

Why this module exists
----------------------
The plank classifier is scored against a hand-labelled gold set, but every plank in that set
is a *platform plank*. Bills are classified from their titles, which are shorter, more
procedural and written to a different purpose, so the plank accuracy figure does not transfer
to them. That left the revealed-preference half of the headline comparison resting on an
unmeasured classifier.

Roughly half of all bills carry ``subject`` tags applied by the legislature's own staff. Those
tags are a genuinely independent signal: a different labeller, a different labelling process,
recorded before this project existed. Mapping the unambiguous ones onto the project's topic
scheme (``conf/subject_topic_map.yml``) gives a large-sample agreement rate that nobody in this
project chose.

How to read the number
----------------------
It is **agreement between two imperfect labellers, not accuracy against truth**. Neither side
is ground truth: a clerk's tag can be wrong or coarse, and a bill can genuinely span topics.
Three specific cautions:

* Only bills whose tags map unambiguously are scored. Those bills are easier than average --
  a bill tagged "motor vehicles" usually says so in its title -- so this is an **upper bound**
  on the classifier's accuracy over all bills, and is reported as such.
* Bills carrying tags that map to two or more different topics are dropped rather than counted
  wrong, because there is no single correct answer to compare against.
* 13 states publish no tags at all, so coverage is not nationally representative.

Agreement is still worth measuring: a low number would mean the revealed-preference shares are
not trustworthy, and that is a claim this project should be able to check rather than assume.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from .taxonomy import DEFAULT_TOPICS_PATH, EmbeddingClassifier, load_topics

__all__ = [
    "DEFAULT_MAP_PATH",
    "load_subject_map",
    "normalize_tag",
    "tag_topic",
    "agreement_report",
    "tag_replication",
    "tag_replication_by_state",
]

DEFAULT_MAP_PATH = Path(__file__).resolve().parents[3] / "conf" / "subject_topic_map.yml"

#: Trailing state reference codes, e.g. "Resolutions--Congratulatory & Honorary (I0705)".
_TRAILING_CODE_RE = re.compile(r"\s*\([A-Z]?\d+\)\s*$")


def normalize_tag(tag: str) -> str:
    """Lowercase, collapse whitespace and drop any trailing state reference code."""
    return re.sub(r"\s+", " ", _TRAILING_CODE_RE.sub("", tag.strip())).strip().lower()


def load_subject_map(path: Path | str | None = None) -> dict[str, int]:
    """Load the tag -> topic-code mapping."""
    import yaml

    path = Path(path) if path else DEFAULT_MAP_PATH
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {normalize_tag(tag): int(code) for tag, code in (raw.get("tags") or {}).items()}


def tag_topic(subject: str | None, subject_map: dict[str, int]) -> int | None:
    """The single topic a bill's tags agree on, or None.

    Returns None when no tag is mappable *and* when the mappable tags disagree. A bill tagged
    both "education" and "taxation" has no single right answer, so scoring the classifier
    against either one would be measuring coin flips.
    """
    if not subject:
        return None
    codes = {subject_map[tag] for tag in
             (normalize_tag(part) for part in str(subject).split("|") if part.strip())
             if tag in subject_map}
    return codes.pop() if len(codes) == 1 else None


def agreement_report(frame, subject_map: dict[str, int], topic_names: dict[int, str]):
    """Per-topic and overall agreement between predicted topic and tag-derived topic.

    ``frame`` must carry ``subject`` and a predicted ``topic`` column.
    """
    import pandas as pd

    reference = frame["subject"].map(lambda s: tag_topic(s, subject_map))
    scored = frame.assign(reference=reference)
    scored = scored[scored["reference"].notna() & scored["topic"].notna()]
    if scored.empty:
        return pd.DataFrame(columns=["topic", "topic_name", "n", "agreed", "agreement"])

    rows = []
    for code, group in scored.groupby("reference"):
        agreed = int((group["topic"] == code).sum())
        # Precision matters more than recall here. Every headline number is a *share of bills
        # assigned to a topic*, so what governs its interpretation is how many bills the
        # classifier puts in a topic that belong there -- not how many it finds.
        predicted = scored[scored["topic"] == code]
        precise = int((predicted["reference"] == code).sum())
        rows.append({
            "topic": int(code),
            "topic_name": topic_names.get(int(code), str(code)),
            "n": len(group),
            "agreed": agreed,
            "agreement": round(agreed / len(group), 4),
            "n_predicted": len(predicted),
            "precision": round(precise / len(predicted), 4) if len(predicted) else None,
            # What the classifier says instead, when it disagrees. A single dominant confusion
            # is a taxonomy boundary problem; a scatter is ordinary title noise.
            "top_confusion": _top_confusion(group, code, topic_names),
            # And what it wrongly pulls *in*, which is what inflates a topic's share.
            "top_contaminant": _top_contaminant(predicted, code, topic_names),
        })
    return pd.DataFrame(rows).sort_values("n", ascending=False).reset_index(drop=True)


def _top_confusion(group, code: int, topic_names: dict[int, str]) -> str:
    wrong = group[group["topic"] != code]["topic"]
    if wrong.empty:
        return ""
    predicted, count = Counter(wrong.tolist()).most_common(1)[0]
    return f"{topic_names.get(int(predicted), predicted)} ({count})"


def _top_contaminant(predicted, code: int, topic_names: dict[int, str]) -> str:
    """The topic most often wrongly classified *into* ``code``."""
    wrong = predicted[predicted["reference"] != code]["reference"]
    if wrong.empty:
        return ""
    reference, count = Counter(int(r) for r in wrong).most_common(1)[0]
    return f"{topic_names.get(reference, reference)} ({count})"


def tag_replication(bills, subject_map: dict[str, int], topic_names: dict[int, str]):
    """Re-derive each party's revealed emphasis using tags instead of the model.

    This is the strongest check available on the headline comparison, because it replaces the
    classifier entirely: the topic labels come from legislative staff, so a finding that
    survives it does not depend on this project's model at all.

    It is a replication on a *subsample* -- only the 35 states with unambiguously mappable
    published tags, and only bills whose tags map to one topic -- so the shares are not directly
    comparable in level to the full-corpus figures. What is comparable is the direction and
    rough size of each party's gap between what it says and what it files.
    """
    import pandas as pd

    frame = bills[bills["sponsor_party"].isin(("D", "R"))].copy()
    frame["reference"] = frame["subject"].map(lambda s: tag_topic(s, subject_map))
    frame = frame[frame["reference"].notna()]
    if frame.empty:
        return pd.DataFrame(columns=["topic", "topic_name", "party", "tag_share", "n_bills"])

    counts = frame.groupby(["sponsor_party", "reference"]).size().rename("n_bills")
    totals = frame.groupby("sponsor_party").size()
    table = counts.reset_index()
    table["tag_share"] = table.apply(
        lambda row: row["n_bills"] / totals[row["sponsor_party"]], axis=1)
    table = table.rename(columns={"sponsor_party": "party", "reference": "topic"})
    table["topic"] = table["topic"].astype(int)
    table["topic_name"] = table["topic"].map(topic_names)
    return table[["topic", "topic_name", "party", "tag_share", "n_bills"]]


def tag_replication_by_state(bills, subject_map: dict[str, int], topic_names: dict[int, str]):
    """State-party topic shares derived solely from legislative-staff tags."""
    import pandas as pd

    frame = bills[bills["sponsor_party"].isin(("D", "R"))].copy()
    frame["topic"] = frame["subject"].map(lambda value: tag_topic(value, subject_map))
    frame = frame[frame["topic"].notna()]
    if frame.empty:
        return pd.DataFrame(
            columns=["state", "party", "topic", "topic_name", "n_bills", "share"]
        )
    counts = (
        frame.groupby(["state", "sponsor_party", "topic"])
        .size()
        .rename("n_bills")
        .reset_index()
        .rename(columns={"sponsor_party": "party"})
    )
    counts["share"] = counts["n_bills"] / counts.groupby(["state", "party"])[
        "n_bills"
    ].transform("sum")
    counts["topic"] = counts["topic"].astype(int)
    counts["topic_name"] = counts["topic"].map(topic_names)
    return counts


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    from .revealed import classify_bills, party_emphasis_from_states

    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bills", default=root / "data/processed/bills.parquet")
    parser.add_argument("--map", default=DEFAULT_MAP_PATH)
    parser.add_argument("--topics", default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--out", default=root / "data/processed/bill_tag_agreement.csv")
    parser.add_argument("--sample", type=int, default=60000,
                        help="bills to score; the full tagged set is far larger than needed "
                             "for a stable rate and slower to embed")
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--stated-vs-revealed",
                        default=root / "data/processed/stated_vs_revealed.csv")
    parser.add_argument(
        "--platform-by-org",
        default=root / "data/processed/emphasis_by_org.csv",
    )
    parser.add_argument(
        "--bill-by-state",
        default=root / "data/processed/bill_emphasis_by_state.csv",
    )
    args = parser.parse_args(argv)

    bills_path = Path(args.bills)
    if not bills_path.exists():
        parser.error(f"{bills_path} not found - run 'python -m state_politics.bills.ingest'")

    subject_map = load_subject_map(args.map)
    topics = load_topics(args.topics)
    topic_names = {t.code: t.name for t in topics}

    frame = pd.read_parquet(bills_path, columns=["state", "year", "title", "subject"])
    frame = frame[frame["subject"].astype(str).str.len() > 0]
    frame = frame.assign(reference=frame["subject"].map(lambda s: tag_topic(s, subject_map)))
    usable = frame[frame["reference"].notna()]
    print(f"bills with tags:        {len(frame):,}")
    print(f"tags map to one topic:  {len(usable):,} ({100 * len(usable) / len(frame):.1f}%)")
    print(f"states represented:     {usable['state'].nunique()}/50")

    if len(usable) > args.sample:
        usable = usable.sample(args.sample, random_state=args.seed)
    print(f"scoring:                {len(usable):,} bills", flush=True)

    classifier = EmbeddingClassifier(topics)
    classified = classify_bills(usable.drop(columns=["reference"]), classifier)
    classified["subject"] = usable["subject"].to_numpy()

    report = agreement_report(classified, subject_map, topic_names)
    total = int(report["n"].sum())
    agreed = int(report["agreed"].sum())
    print(f"\noverall agreement:      {agreed:,}/{total:,} ({100 * agreed / total:.1f}%)")
    print("\nby topic (recall = tagged bills the model finds; "
          "precision = model's picks the tag confirms):")
    print(f"  {'topic':<38} {'recall':>7} {'prec':>7}  {'n':>6}  most common contaminant")
    for _, row in report.sort_values("precision").iterrows():
        precision = f"{row['precision'] * 100:5.1f}%" if row["precision"] is not None else "    -"
        print(f"  {row['topic_name']:<38} {row['agreement'] * 100:5.1f}%  {precision}  "
              f"{int(row['n']):>6,}  {row['top_contaminant'] or '-'}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(out, index=False)

    # The replication uses every tagged bill, not the scoring sample: it needs no embedding
    # pass, so there is no reason to subsample it.
    full = pd.read_parquet(
        bills_path,
        columns=["state", "year", "subject", "sponsor_party"],
    )
    full = full[
        (full["year"] >= 2018)
        & full["subject"].astype(str).str.len().gt(0)
    ]
    tag_state = tag_replication_by_state(full, subject_map, topic_names)
    platform_by_org = pd.read_csv(args.platform_by_org)
    current_platform = platform_by_org[
        platform_by_org["era"] == "2018-present"
    ]
    platform_states = {
        party: set(current_platform.loc[current_platform["party"] == party, "state"])
        for party in ("D", "R")
    }
    tag_states = {
        party: set(tag_state.loc[tag_state["party"] == party, "state"])
        for party in ("D", "R")
    }
    comparison_states = (
        platform_states["D"]
        & platform_states["R"]
        & tag_states["D"]
        & tag_states["R"]
    )
    replication = party_emphasis_from_states(
        tag_state,
        states=comparison_states,
    ).rename(columns={"share": "tag_share"})
    replication_path = out.with_name("bill_emphasis_by_tag.csv")
    replication.to_csv(replication_path, index=False)

    model_state = pd.read_csv(args.bill_by_state)
    model = party_emphasis_from_states(
        model_state,
        states=comparison_states,
    ).rename(columns={"share": "model_share"})
    stated_vectors = current_platform[
        current_platform["state"].isin(comparison_states)
    ].pivot_table(
        index=["state", "party"],
        columns="topic",
        values="share",
        fill_value=0.0,
    )
    stated = (
        stated_vectors.groupby(level="party")
        .mean()
        .stack(future_stack=True)
        .rename("stated_share")
        .reset_index()
    )
    comparison = (
        stated.merge(
            model[["party", "topic", "model_share"]],
            on=["party", "topic"],
            how="outer",
        )
        .merge(
            replication[["party", "topic", "tag_share"]],
            on=["party", "topic"],
            how="outer",
        )
        .fillna(0.0)
    )
    comparison["holds"] = (
        (comparison["model_share"] - comparison["stated_share"])
        * (comparison["tag_share"] - comparison["stated_share"])
        > 0
    )
    comparison["n_states"] = len(comparison_states)
    comparison["topic_name"] = comparison["topic"].map(topic_names)
    comparison_path = out.with_name("headline_tag_replication.csv")
    comparison.to_csv(comparison_path, index=False)
    if not comparison.empty:
        print("\nheadline replicated with tag labels instead of the model "
              f"({len(comparison_states)} matched states):")
        print(f"  {'topic':<34}{'party':>6}{'said':>8}{'model':>8}{'tags':>8}  verdict")
        order = (
            comparison["model_share"] - comparison["tag_share"]
        ).abs().sort_values(ascending=False).index
        for _, row in comparison.reindex(order).iterrows():
            print(f"  {row['topic_name'][:33]:<34}{row['party']:>6}"
                  f"{row['stated_share'] * 100:7.1f}%"
                  f"{row['model_share'] * 100:7.1f}%{row['tag_share'] * 100:7.1f}%  "
                  f"{'holds' if row['holds'] else 'DOES NOT HOLD'}")
    print(f"\nwrote {out}")
    print(f"wrote {replication_path}")
    print(f"wrote {comparison_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""What does each state emphasize relative to other states of the same party?

National D-vs-R averages answer a different question from this module. Here, Idaho Democrats
are compared with Democrats in the *other* states, and Illinois Republicans with Republicans
elsewhere. The baseline is leave-one-state-out so the state being described cannot pull its own
comparison point toward itself.

Two evidence streams remain separate:

* **Stated focus** uses current party-committee platforms/resolutions where available and the
  explicitly labelled legislative-caucus supplement only where committee evidence is absent.
* **Filed focus** uses classified bill titles. It covers 98 partisan state caucuses across 49
  states; Nebraska has no D/R bill profile because its legislature is formally nonpartisan.

The output is a 100-row atlas (50 states x two parties) with top topics, the topic each state
over-emphasizes most relative to co-partisans, its leave-one-out party baseline, cosine distance,
sample size and evidence type. Missing evidence stays missing instead of being guessed.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from .profiles import MIN_OBSERVATIONS, topic_vectors
from .taxonomy import (
    DEFAULT_TOPICS_PATH,
    EmbeddingClassifier,
    load_topics,
    segment_planks,
)

__all__ = [
    "caucus_units",
    "classify_caucus_priorities",
    "combine_stated_emphasis",
    "focus_metrics",
    "build_state_focus_atlas",
]

STATE_CODES = (
    "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "IA", "ID",
    "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO", "MS", "MT",
    "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY",
)


def _kentucky_priority_units(text: str) -> list[str]:
    """Extract only the explicitly numbered priority bills from Kentucky's combined pages.

    The caucus index also lists every other Senate bill. Classifying the raw page therefore
    makes the supplement an analysis of the whole session, not the caucus's stated priority
    list. The linked bill pages repeat ``24RS SB N`` and carry a title plus an official summary;
    those are the analytical units. Bill 9 has no public record page and is not fabricated.
    """
    starts = list(re.finditer(r"\b24RS SB\s+(\d+)\b", text, re.I))
    units: dict[int, str] = {}
    for index, match in enumerate(starts):
        number = int(match.group(1))
        if number > 10 or number in units:
            continue
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        section = text[match.start():end]
        title_match = re.search(
            r"\bTitle\s+(.*?)\s+Bill Documents\b", section, re.I | re.S
        )
        summary_match = re.search(
            r"Summary of (?:Original|Enacted) Version\s+(.*?)(?:"
            r"Index Headings|Legislative History|Amendments|$)",
            section,
            re.I | re.S,
        )
        if not title_match:
            continue
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        summary = (
            re.sub(r"\s+", " ", summary_match.group(1)).strip()
            if summary_match else ""
        )
        units[number] = f"Kentucky Senate Bill {number}. {title} {summary}".strip()
    return [units[number] for number in sorted(units)]


def _maryland_agenda_units(text: str) -> list[str]:
    """Extract the caucus's verbatim agenda sentence, not the committee-assignment story."""
    match = re.search(
        r"(?:Senate Democratic Caucus )?agenda will focus on .*?Legislative Session\.",
        text,
        re.I | re.S,
    )
    if not match:
        return []
    return [re.sub(r"\s+", " ", match.group(0)).strip()]


def caucus_units(frame):
    """Turn each supplemental source into policy-bearing analytical units."""
    import pandas as pd

    rows = []
    for document_index, row in enumerate(frame.itertuples(index=False)):
        if row.state == "KY" and row.party == "R":
            texts = _kentucky_priority_units(row.text)
        elif row.state == "MD" and row.party == "D":
            texts = _maryland_agenda_units(row.text)
        else:
            texts = [plank.text for plank in segment_planks(row.text, document_index)]
        for unit_index, text in enumerate(texts):
            rows.append(
                {
                    "document_index": document_index,
                    "unit_index": unit_index,
                    "state": row.state,
                    "party": row.party,
                    "year": row.year,
                    "evidence_type": "legislative_caucus",
                    "institution": row.institution,
                    "text": text,
                    "n_words": len(text.split()),
                }
            )
    return pd.DataFrame(rows)


def classify_caucus_priorities(frame, classifier: EmbeddingClassifier, topics):
    """Classify curated caucus units and return plank- and emphasis-level tables."""
    import pandas as pd

    units = caucus_units(frame)
    if units.empty:
        return units, pd.DataFrame()
    predictions = classifier.predict_many(units["text"].tolist(), batch_size=64)
    units["topic"] = [code for code, _, _ in predictions]
    units["similarity"] = [round(score, 4) for _, score, _ in predictions]
    units["margin"] = [round(margin, 4) for _, _, margin in predictions]

    named = {topic.code: topic.name for topic in topics}
    classified = units[units["topic"].notna()]
    counts = (
        classified.groupby(["state", "party", "topic"]).size()
        .rename("n_items").reset_index()
    )
    totals = counts.groupby(["state", "party"])["n_items"].transform("sum")
    counts["share"] = counts["n_items"] / totals
    counts["topic_name"] = counts["topic"].map(named)
    counts["evidence_type"] = "legislative_caucus"
    return units, counts


def combine_stated_emphasis(committee, caucus):
    """Use caucus evidence only where current committee evidence is absent."""
    import pandas as pd

    committee = committee[committee["era"] == "2018-present"].copy()
    committee = committee.rename(columns={"n_planks": "n_items"})
    committee["evidence_type"] = "party_committee"
    keys = set(map(tuple, committee[["state", "party"]].drop_duplicates().values))
    if not caucus.empty:
        caucus = caucus[
            ~caucus[["state", "party"]].apply(tuple, axis=1).isin(keys)
        ].copy()
    columns = [
        "state", "party", "topic", "topic_name", "n_items", "share", "evidence_type"
    ]
    return pd.concat([committee[columns], caucus[columns]], ignore_index=True)


def _format_top(vector, names: dict[int, str], top_n: int = 3) -> str:
    return "; ".join(
        f"{names.get(int(code), code)} ({share:.0%})"
        for code, share in vector[vector > 0].sort_values(ascending=False).head(top_n).items()
    )


def focus_metrics(vectors, counts, topic_names, *, min_items: int = 5):
    """Leave-one-state-out focus metrics for each state party vector."""
    import numpy as np
    import pandas as pd

    columns = [
        "state", "party", "n_items", "top_topics", "focus_topic", "focus_share",
        "peer_share", "overemphasis", "cosine_distance", "focus_reliable",
    ]
    if vectors.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    totals = counts.groupby(["state", "party"])["n_items"].sum()
    for party in ("D", "R"):
        if party not in vectors.index.get_level_values("party"):
            continue
        block = vectors.xs(party, level="party")
        for state, vector in block.iterrows():
            peers = block.drop(index=state)
            n_items = int(totals.get((state, party), 0))
            if peers.empty:
                rows.append(
                    {
                        "state": state,
                        "party": party,
                        "n_items": n_items,
                        "top_topics": _format_top(vector, topic_names),
                        "focus_topic": None,
                        "focus_share": None,
                        "peer_share": None,
                        "overemphasis": None,
                        "cosine_distance": None,
                        "focus_reliable": False,
                    }
                )
                continue
            baseline = peers.mean(axis=0)
            difference = vector - baseline
            topic = int(difference.idxmax())
            norm = float(np.linalg.norm(vector) * np.linalg.norm(baseline))
            distance = 1.0 - float(vector @ baseline) / norm if norm else float("nan")
            rows.append(
                {
                    "state": state,
                    "party": party,
                    "n_items": n_items,
                    "top_topics": _format_top(vector, topic_names),
                    "focus_topic": topic_names.get(topic, str(topic)),
                    "focus_share": round(float(vector[topic]), 4),
                    "peer_share": round(float(baseline[topic]), 4),
                    "overemphasis": round(float(difference[topic]), 4),
                    "cosine_distance": round(distance, 4),
                    "focus_reliable": n_items >= min_items,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def build_state_focus_atlas(stated, bills, topics):
    """Return one row for every state x party, preserving missing evidence explicitly."""
    import pandas as pd

    names = {topic.code: topic.name for topic in topics}
    stated_counts = stated.rename(columns={"n_items": "n_items"})
    stated_vectors = topic_vectors(
        stated_counts, count_column="n_items", min_observations=1
    )
    stated_focus = focus_metrics(stated_vectors, stated_counts, names).add_prefix("stated_")
    stated_focus = stated_focus.rename(
        columns={"stated_state": "state", "stated_party": "party"}
    )
    evidence = (
        stated.groupby(["state", "party"])["evidence_type"].first().rename("stated_source")
    )

    bill_counts = bills.rename(columns={"n_bills": "n_items"})
    bill_vectors = topic_vectors(
        bill_counts, count_column="n_items", min_observations=MIN_OBSERVATIONS
    )
    bill_focus = focus_metrics(
        bill_vectors, bill_counts, names, min_items=MIN_OBSERVATIONS
    ).add_prefix("bill_")
    bill_focus = bill_focus.rename(columns={"bill_state": "state", "bill_party": "party"})

    grid = pd.DataFrame(
        [(state, party) for state in STATE_CODES for party in ("D", "R")],
        columns=["state", "party"],
    )
    grid = grid.merge(stated_focus, on=["state", "party"], how="left")
    grid = grid.merge(evidence.reset_index(), on=["state", "party"], how="left")
    grid = grid.merge(bill_focus, on=["state", "party"], how="left")
    grid["stated_source"] = grid["stated_source"].fillna("none")
    grid["bill_status"] = "available"
    grid.loc[grid["bill_n_items"].isna(), "bill_status"] = "not_available"
    grid.loc[
        (grid["state"] == "NE") & grid["bill_n_items"].isna(), "bill_status"
    ] = "formally_nonpartisan_legislature"
    return grid


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--committee", default=root / "data/processed/emphasis_by_org.csv")
    parser.add_argument("--caucus", default=root / "data/processed/caucus_priorities.parquet")
    parser.add_argument("--bills", default=root / "data/processed/bill_emphasis_by_state.csv")
    parser.add_argument("--topics", default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--out-dir", default=root / "data/processed")
    args = parser.parse_args(argv)

    topics = load_topics(args.topics)
    classifier = EmbeddingClassifier(topics)
    caucus_frame = pd.read_parquet(args.caucus)
    caucus_planks, caucus_emphasis = classify_caucus_priorities(
        caucus_frame, classifier, topics
    )
    committee = pd.read_csv(args.committee)
    stated = combine_stated_emphasis(committee, caucus_emphasis)
    bills = pd.read_csv(args.bills)
    atlas = build_state_focus_atlas(stated, bills, topics)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    caucus_planks.drop(columns=["text"]).to_parquet(
        out / "caucus_priority_planks.parquet", index=False
    )
    caucus_emphasis.to_csv(out / "caucus_priority_emphasis.csv", index=False)
    stated.to_csv(out / "stated_emphasis_with_supplement.csv", index=False)
    atlas.to_csv(out / "state_party_focus.csv", index=False)

    print(f"state-party profiles: {len(atlas)}/100")
    print(f"stated evidence:      {(atlas['stated_source'] != 'none').sum()}/100")
    print(f"bill evidence:        {atlas['bill_n_items'].notna().sum()}/100")
    for party in ("D", "R"):
        top = atlas[
            (atlas["party"] == party) & atlas["bill_focus_reliable"].fillna(False)
        ].nlargest(5, "bill_cosine_distance")
        print(f"\nMost distinctive {party} state bill agendas:")
        for row in top.itertuples():
            print(
                f"  {row.state}: {row.bill_focus_topic} "
                f"{row.bill_focus_share:.1%} vs {row.bill_peer_share:.1%} in peer states"
            )
    print(f"\nwrote {out / 'state_party_focus.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

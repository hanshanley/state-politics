"""Per-state profiles and cross-state outlier analysis.

Two questions the national averages cannot answer:

* **What does *this* state party emphasize?** A one-page profile per organization, giving its
  top platform topics, its top filing topics, and where the two diverge.
* **Which state parties are unlike their own national party?** Emphasis is compared against the
  pooled average for that party across all states, so a state party that is an outlier on some
  topic is identifiable rather than lost in the mean.

Distance measure
----------------
Cosine distance over the topic-share vector. Cosine rather than Euclidean because it compares
the *shape* of a party's agenda -- the relative weighting across topics -- and is not dominated
by how many planks or bills that state happens to produce, which varies by an order of
magnitude between New York and Wyoming.
"""

from __future__ import annotations

import argparse
from pathlib import Path

__all__ = ["build_profiles", "cross_state_outliers", "topic_vectors"]

#: A state party needs at least this many classified planks (or bills) before its emphasis
#: vector means anything. Below it, one plank moves a share by tens of percentage points.
MIN_OBSERVATIONS = 30


def topic_vectors(table, *, count_column: str = "n_planks",
                  min_observations: int = MIN_OBSERVATIONS):
    """Pivot a long emphasis table into one topic-share vector per (state, party).

    Shares are recomputed from raw counts rather than summed. The emphasis tables are split by
    era, and each era's shares already sum to 1, so adding them straight up gave a state with
    two eras a total of 200% -- and produced "distinctive" topics with shares above 100%.

    Groups with too few observations are dropped rather than reported as noisy outliers, which
    is the failure mode a naive ranking of this table would produce.
    """
    import pandas as pd

    counts = table.groupby(["state", "party", "topic"])[count_column].sum().reset_index()
    totals = counts.groupby(["state", "party"])[count_column].transform("sum")
    counts = counts[totals >= min_observations].copy()
    if counts.empty:
        return pd.DataFrame()
    counts["share"] = counts[count_column] / counts.groupby(["state", "party"])[
        count_column].transform("sum")
    return counts.pivot_table(
        index=["state", "party"], columns="topic", values="share", aggfunc="sum"
    ).fillna(0.0)


def cross_state_outliers(vectors, topics):
    """Distance from each state party to its own national party average.

    The comparison is within party: a Democratic state party is measured against the pooled
    Democratic average, not against all parties, so the result is "unusual for a Democrat"
    rather than the trivial finding that Democrats differ from Republicans.
    """
    import numpy as np
    import pandas as pd

    if vectors.empty:
        return pd.DataFrame()

    named = {topic.code: topic.name for topic in topics}
    rows = []
    for party in ("D", "R"):
        subset = vectors[vectors.index.get_level_values("party") == party]
        if len(subset) < 2:
            continue
        mean = subset.mean(axis=0)
        mean_norm = np.linalg.norm(mean)
        for (state, _), vector in subset.iterrows():
            norm = np.linalg.norm(vector)
            similarity = float(vector @ mean / (norm * mean_norm)) if norm and mean_norm else 0.0
            difference = vector - mean
            # Largest absolute departure, breaking ties toward the topic the state emphasizes
            # *more* than its party: "Montana Democrats talk about public lands far more" is a
            # more useful headline than the mirror-image "they talk about labour far less",
            # and the signed difference is reported either way.
            largest = difference.abs().max()
            candidates = difference[difference.abs() >= largest - 1e-12]
            most = candidates.idxmax() if (candidates > 0).any() else candidates.idxmin()
            rows.append({
                "state": state,
                "party": party,
                "cosine_distance": round(1 - similarity, 4),
                "most_distinctive_topic": named.get(most, most),
                "topic_share": round(float(vector[most]), 4),
                "party_average_share": round(float(mean[most]), 4),
                "difference": round(float(difference[most]), 4),
            })
    return pd.DataFrame(rows).sort_values(["party", "cosine_distance"], ascending=[True, False])


def build_profiles(platform_emphasis, bill_emphasis, gap_report, topics, *, top_n: int = 5,
                   era: str | None = "2018-present"):
    """One row per organization summarizing what it says, what it files, and the gap.

    ``era`` restricts the platform side to a single era, because the bill side covers 2018-2026
    only. Pooling every platform era against a 2018-2026 bill window puts a 1990s platform next
    to a 2020s legislative record in the same row -- the era mismatch that ``revealed.py``
    deliberately avoids for the headline. Pass ``era=None`` to pool anyway.
    """
    import pandas as pd

    named = {topic.code: topic.name for topic in topics}
    if era and "era" in platform_emphasis.columns:
        platform_emphasis = platform_emphasis[platform_emphasis["era"] == era]

    def top_topics(table, group, count_column):
        # Re-derive shares from counts: the platform table is split by era and each era's
        # shares already sum to 1, so adding them would exceed 100%.
        subset = table[(table["state"] == group[0]) & (table["party"] == group[1])]
        if subset.empty:
            return ""
        counts = subset.groupby("topic")[count_column].sum()
        total = counts.sum()
        if not total:
            return ""
        shares = (counts / total).sort_values(ascending=False)
        return "; ".join(
            f"{named.get(code, code)} ({share:.0%})" for code, share in shares.head(top_n).items()
        )

    organizations = sorted(
        set(map(tuple, platform_emphasis[["state", "party"]].drop_duplicates().values))
        | set(map(tuple, bill_emphasis[["state", "party"]].drop_duplicates().values))
    )

    status = gap_report.set_index(["state", "party"])
    rows = []
    for state, party in organizations:
        record = {
            "state": state,
            "party": party,
            "top_platform_topics": top_topics(platform_emphasis, (state, party), "n_planks"),
            "top_bill_topics": top_topics(bill_emphasis, (state, party), "n_bills"),
        }
        if (state, party) in status.index:
            entry = status.loc[(state, party)]
            record["platform_status"] = entry["status"]
            record["n_platform_documents"] = int(entry["n_confirmed"])
            record["latest_platform_year"] = entry["latest_year"]
        rows.append(record)
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    from .taxonomy import DEFAULT_TOPICS_PATH, load_topics

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--platform", default="data/processed/emphasis_by_org.csv")
    parser.add_argument("--bills", default="data/processed/bill_emphasis_by_state.csv")
    parser.add_argument("--gaps", default="data/processed/platform_gap_report.csv")
    parser.add_argument("--topics", default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--out-dir", default="data/processed")
    args = parser.parse_args(argv)

    topics = load_topics(args.topics)
    platform = pd.read_csv(args.platform)
    bills = pd.read_csv(args.bills)
    gaps = pd.read_csv(args.gaps)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    profiles = build_profiles(platform, bills, gaps, topics)
    profiles.to_csv(out_dir / "state_party_profiles.csv", index=False)

    platform_outliers = cross_state_outliers(
        topic_vectors(platform, count_column="n_planks"), topics
    )
    platform_outliers.to_csv(out_dir / "platform_outliers.csv", index=False)

    bill_outliers = cross_state_outliers(
        topic_vectors(bills, count_column="n_bills"), topics
    )
    bill_outliers.to_csv(out_dir / "bill_outliers.csv", index=False)

    print(f"profiles:          {len(profiles)} organizations")
    print(f"platform outliers: {len(platform_outliers)} organizations scored")
    print(f"bill outliers:     {len(bill_outliers)} organizations scored")

    for label, table in (("platform", platform_outliers), ("bill filing", bill_outliers)):
        if table.empty:
            continue
        print(f"\nmost distinctive state parties by {label} emphasis:")
        for party in ("D", "R"):
            subset = table[table["party"] == party].head(3)
            for _, row in subset.iterrows():
                print(f"  {row['state']}-{party}  distance={row['cosine_distance']:.3f}  "
                      f"{row['most_distinctive_topic']} "
                      f"{row['topic_share']:.1%} vs {row['party_average_share']:.1%} average")

    print(f"\nwrote {out_dir / 'state_party_profiles.csv'}")
    print(f"wrote {out_dir / 'platform_outliers.csv'}")
    print(f"wrote {out_dir / 'bill_outliers.csv'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

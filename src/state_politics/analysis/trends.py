"""Longitudinal change in state-party bill agendas.

Cross-sectional averages can hide whether an issue is rising or falling. This module compares
an early period (2018-2019) with a late period (2024-2025). The periods each contain one
odd-year and one even-year legislative cycle; years after 2025 are outside this window. Inference
uses paired state-level changes and a sign-flip permutation test rather than treating hundreds
of thousands of bills as independent observations. Benjamini-Hochberg adjustment is applied
across available party-topic tests. Fewer than two paired states
leave inference unavailable.

It also estimates simple yearly slopes for transparency. The period comparison is the primary
result because it is less sensitive to a single unusual session than an endpoint difference.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from ..bills.montana import source_draft_request_mask

EARLY_YEARS = (2018, 2019)
LATE_YEARS = (2024, 2025)
MIN_STATE_YEAR_BILLS = 50
MIN_STATE_YEARS = 5
MIN_STATE_PERIOD_BILLS = 100
TREND_PERMUTATIONS = 10_000
TREND_RANDOM_SEED = 20_260_731

__all__ = ["party_topic_trends", "state_topic_trends", "benjamini_hochberg"]


def benjamini_hochberg(p_values):
    """Benjamini-Hochberg q-values in original row order, preserving unavailable tests."""
    import numpy as np

    values = np.asarray(p_values, dtype=float)
    available = ~np.isnan(values)
    defined = values[available]
    order = np.argsort(defined)
    ranked = defined[order]
    adjusted = ranked * len(defined) / np.arange(1, len(defined) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1].clip(0, 1)
    defined_result = np.empty_like(adjusted)
    defined_result[order] = adjusted
    result = np.full_like(values, np.nan)
    result[available] = defined_result
    return result


def _period_counts(frame, years, group_columns):
    subset = frame[frame["year"].isin(years)]
    return (
        subset.groupby([*group_columns, "topic"])["n_bills"]
        .sum().rename("topic_n").reset_index()
    )


def _paired_state_shares(frame, party, topic):
    """State-balanced early/late shares for one party-topic pair."""
    import numpy as np
    import pandas as pd

    subset = frame[frame["party"] == party]
    totals = (
        subset[subset["year"].isin((*EARLY_YEARS, *LATE_YEARS))]
        .assign(
            period=lambda value: np.where(
                value["year"].isin(EARLY_YEARS), "early", "late"
            )
        )
        .groupby(["state", "period"])["n_bills"]
        .sum()
        .unstack()
        .reindex(columns=["early", "late"])
    )
    eligible = totals.dropna()
    eligible = eligible[
        (eligible["early"] >= MIN_STATE_PERIOD_BILLS)
        & (eligible["late"] >= MIN_STATE_PERIOD_BILLS)
    ]
    if eligible.empty:
        return pd.DataFrame(columns=["early", "late", "change"])

    topic_counts = (
        subset[
            subset["state"].isin(eligible.index)
            & subset["year"].isin((*EARLY_YEARS, *LATE_YEARS))
            & subset["topic"].eq(topic)
        ]
        .assign(
            period=lambda value: np.where(
                value["year"].isin(EARLY_YEARS), "early", "late"
            )
        )
        .groupby(["state", "period"])["n_bills"]
        .sum()
        .unstack(fill_value=0)
        .reindex(index=eligible.index, columns=["early", "late"], fill_value=0)
    )
    shares = pd.DataFrame(index=eligible.index)
    shares["early"] = topic_counts["early"] / eligible["early"]
    shares["late"] = topic_counts["late"] / eligible["late"]
    shares["change"] = shares["late"] - shares["early"]
    return shares


def _sign_flip_p_value(differences, *, seed):
    """Two-sided paired sign-flip permutation p-value."""
    import numpy as np

    if len(differences) < 2:
        return float("nan")
    observed = abs(float(np.mean(differences)))
    rng = np.random.default_rng(seed)
    signs = rng.choice((-1, 1), size=(TREND_PERMUTATIONS, len(differences)))
    permuted = np.abs((signs * differences).mean(axis=1))
    return float((1 + np.count_nonzero(permuted >= observed)) / (TREND_PERMUTATIONS + 1))


def party_topic_trends(frame):
    """Pooled changes plus state-paired uncertainty and FDR correction."""
    import numpy as np
    import pandas as pd

    frame = frame[frame["year"].between(min(EARLY_YEARS), max(LATE_YEARS))]
    early = _period_counts(frame, EARLY_YEARS, ["party"]).rename(
        columns={"topic_n": "early_n"}
    )
    late = _period_counts(frame, LATE_YEARS, ["party"]).rename(
        columns={"topic_n": "late_n"}
    )
    merged = (
        frame[["party", "topic"]].drop_duplicates().sort_values(["party", "topic"])
        .merge(early, on=["party", "topic"], how="left")
        .merge(late, on=["party", "topic"], how="left")
    )
    merged[["early_n", "late_n"]] = merged[["early_n", "late_n"]].fillna(0)
    early_totals = frame[frame["year"].isin(EARLY_YEARS)].groupby("party")[
        "n_bills"
    ].sum()
    late_totals = frame[frame["year"].isin(LATE_YEARS)].groupby("party")[
        "n_bills"
    ].sum()
    merged["early_total"] = merged["party"].map(early_totals)
    merged["late_total"] = merged["party"].map(late_totals)
    merged["early_n"] = merged["early_n"].where(merged["early_total"].notna())
    merged["late_n"] = merged["late_n"].where(merged["late_total"].notna())
    merged["pooled_early_share"] = merged["early_n"] / merged["early_total"]
    merged["pooled_late_share"] = merged["late_n"] / merged["late_total"]
    merged["pooled_change"] = (
        merged["pooled_late_share"] - merged["pooled_early_share"]
    )
    merged["pooled_binomial_se"] = np.sqrt(
        merged["pooled_early_share"]
        * (1 - merged["pooled_early_share"])
        / merged["early_total"]
        + merged["pooled_late_share"]
        * (1 - merged["pooled_late_share"])
        / merged["late_total"]
    )
    inference = []
    for row in merged.itertuples():
        paired = _paired_state_shares(frame, row.party, row.topic)
        differences = paired["change"].to_numpy()
        standard_error = (
            float(np.std(differences, ddof=1) / math.sqrt(len(differences)))
            if len(differences) > 1
            else np.nan
        )
        inference.append(
            {
                "party": row.party,
                "topic": row.topic,
                "paired_state_count": len(differences),
                "early_share": (
                    float(paired["early"].mean()) if len(paired) else np.nan
                ),
                "late_share": (
                    float(paired["late"].mean()) if len(paired) else np.nan
                ),
                "change": (
                    float(np.mean(differences)) if len(differences) else np.nan
                ),
                "state_change_se": standard_error,
                "p_value": _sign_flip_p_value(
                    differences,
                    seed=TREND_RANDOM_SEED
                    + int(row.topic) * 10
                    + (1 if row.party == "R" else 0),
                ),
            }
        )
    merged = merged.merge(
        pd.DataFrame(inference, columns=[
            "party", "topic", "paired_state_count", "early_share", "late_share",
            "change", "state_change_se", "p_value",
        ]),
        on=["party", "topic"],
    )
    merged["q_value"] = benjamini_hochberg(merged["p_value"])

    totals = frame.groupby(["party", "year"])["n_bills"].sum()
    slope_rows = []
    for (party, topic), group in frame.groupby(["party", "topic"]):
        party_totals = totals.loc[party]
        counts = group.groupby("year")["n_bills"].sum().reindex(party_totals.index, fill_value=0)
        by_year = (counts / party_totals.where(party_totals > 0)).dropna().sort_index()
        if len(by_year) < 2:
            continue
        x = by_year.index.to_numpy(dtype=float)
        y = by_year.to_numpy(dtype=float)
        slope = float(((x - x.mean()) @ (y - y.mean())) / ((x - x.mean()) @ (x - x.mean())))
        slope_rows.append({"party": party, "topic": topic, "slope_per_year": slope})
    slopes = pd.DataFrame(slope_rows, columns=["party", "topic", "slope_per_year"])
    return merged.merge(slopes, on=["party", "topic"], how="left")


def state_topic_trends(frame):
    """State-party topic slopes where yearly samples are large enough to interpret."""
    import pandas as pd

    frame = frame[frame["year"].between(min(EARLY_YEARS), max(LATE_YEARS))].copy()
    totals = (
        frame.groupby(["state", "party", "year"])["n_bills"].sum()
        .rename("year_total").reset_index()
    )
    usable_totals = totals[totals["year_total"] >= MIN_STATE_YEAR_BILLS]
    topics = sorted(frame["topic"].dropna().unique())
    rows = []
    for (state, party), group_totals in usable_totals.groupby(["state", "party"]):
        group_totals = group_totals.sort_values("year")
        if len(group_totals) < MIN_STATE_YEARS:
            continue
        years = group_totals["year"].to_numpy()
        denominators = group_totals.set_index("year")["year_total"]
        group = frame[
            frame["state"].eq(state)
            & frame["party"].eq(party)
            & frame["year"].isin(years)
        ]
        counts = (
            group.pivot_table(
                index="year", columns="topic", values="n_bills",
                aggfunc="sum", fill_value=0,
            )
            .reindex(index=years, columns=topics, fill_value=0)
        )
        x = years.astype(float)
        centered_x = x - x.mean()
        denominator = centered_x @ centered_x
        for topic in topics:
            by_year = counts[topic] / denominators
            y = by_year.to_numpy(dtype=float)
            slope = float(centered_x @ (y - y.mean()) / denominator)
            rows.append(
                {
                    "state": state,
                    "party": party,
                    "topic": topic,
                    "n_years": len(years),
                    "first_year": int(years.min()),
                    "last_year": int(years.max()),
                    "slope_per_year": slope,
                    "first_share": float(y[0]),
                    "last_share": float(y[-1]),
                }
            )
    return pd.DataFrame(rows, columns=[
        "state", "party", "topic", "n_years", "first_year", "last_year",
        "slope_per_year", "first_share", "last_share",
    ])


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    from .validate_bills import DEFAULT_MAP_PATH, load_subject_map, tag_topic

    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--by-state-year",
        default=root / "data/processed/bill_emphasis_by_state_year.csv",
    )
    parser.add_argument("--bills", default=root / "data/processed/bills.parquet")
    parser.add_argument("--subject-map", default=DEFAULT_MAP_PATH)
    parser.add_argument("--out-dir", default=root / "data/processed")
    args = parser.parse_args(argv)

    frame = pd.read_csv(args.by_state_year)
    named = frame[["topic", "topic_name"]].drop_duplicates()
    party = party_topic_trends(frame).merge(named, on="topic", how="left")
    state = state_topic_trends(frame).merge(named, on="topic", how="left")
    bills = pd.read_parquet(
        args.bills,
        columns=["state", "identifier", "year", "subject", "sponsor_party"],
    )
    bills = bills[
        bills["sponsor_party"].isin(("D", "R"))
        & bills["year"].between(min(EARLY_YEARS), max(LATE_YEARS))
        & bills["subject"].fillna("").ne("")
        & ~source_draft_request_mask(bills)
    ].copy()
    subject_map = load_subject_map(args.subject_map)
    bills["topic"] = bills["subject"].map(lambda value: tag_topic(value, subject_map))
    tagged_counts = (
        bills[bills["topic"].notna()]
        .rename(columns={"sponsor_party": "party"})
        .groupby(["state", "party", "year", "topic"])
        .size()
        .rename("n_bills")
        .reset_index()
    )
    tag_party = party_topic_trends(tagged_counts).merge(
        named, on="topic", how="left"
    )
    comparison = party.merge(
        tag_party[
            [
                "party",
                "topic",
                "early_share",
                "late_share",
                "change",
                "paired_state_count",
                "q_value",
            ]
        ],
        on=["party", "topic"],
        how="left",
        suffixes=("_model", "_tags"),
    )
    direction_available = comparison["change_model"].notna() & comparison["change_tags"].notna()
    comparison["direction_replicates_with_tags"] = (
        comparison["change_model"].mul(comparison["change_tags"]) > 0
    ).astype("boolean").where(direction_available)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    party.to_csv(out / "bill_topic_trends_by_party.csv", index=False)
    state.to_csv(out / "bill_topic_trends_by_state.csv", index=False)
    tag_party.to_csv(out / "bill_topic_trends_by_party_tags.csv", index=False)
    comparison.to_csv(out / "bill_topic_trend_replication.csv", index=False)

    def display(value, spec):
        return "unavailable" if pd.isna(value) else format(value, spec)

    print("Supplied topic labels, source coverage and subject tags have not been revalidated.")
    print("largest early-to-late changes (FDR-adjusted where inference is available):")
    for party_code in ("D", "R"):
        top = party[party["party"] == party_code].reindex(
            party[party["party"] == party_code]["change"].abs()
            .sort_values(ascending=False).index
        ).head(5)
        print(f"\n  {party_code}:")
        if top.empty:
            print("    unavailable: no party-topic estimates")
        for row in top.itertuples():
            print(
                f"    {row.topic_name}: {display(row.early_share, '.1%')} -> "
                f"{display(row.late_share, '.1%')} "
                f"({display(row.change, '+.1%')}, q={display(row.q_value, '.3g')}, "
                f"paired states={row.paired_state_count})"
            )
    print(f"\nwrote {out / 'bill_topic_trends_by_party.csv'}")
    print(f"wrote {out / 'bill_topic_trends_by_state.csv'}")
    significant = comparison[comparison["q_value_model"] < 0.05]
    if not significant.empty:
        print("\nFDR-significant model changes compared with supplied subject-tag directions:")
        for row in significant.itertuples():
            if pd.isna(row.direction_replicates_with_tags):
                verdict = "tag comparison unavailable"
            else:
                verdict = (
                    "same direction" if row.direction_replicates_with_tags else "not same direction"
                )
            print(
                f"  {row.party} {row.topic_name}: model {display(row.change_model, '+.1%')}, "
                f"tags {display(row.change_tags, '+.1%')} ({verdict}; "
                f"model n={row.paired_state_count_model}, "
                f"tags n={display(row.paired_state_count_tags, '.0f')}; samples may differ)"
            )
    print(f"\nwrote {out / 'bill_topic_trend_replication.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

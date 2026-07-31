"""Longitudinal change in state-party bill agendas.

Cross-sectional averages can hide whether an issue is rising or falling. This module compares
an early period (2018-2019) with a late period (2024-2025). The periods each contain one
odd-year and one even-year legislative cycle; the incomplete 2026 year is excluded. Inference
uses paired state-level changes and a sign-flip permutation test rather than treating hundreds
of thousands of bills as independent observations. Benjamini-Hochberg q-values control the
false discovery rate across all party-topic tests.

It also estimates simple yearly slopes for transparency. The period comparison is the primary
result because it is less sensitive to a single unusual session than an endpoint difference.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

EARLY_YEARS = (2018, 2019)
LATE_YEARS = (2024, 2025)
MIN_STATE_YEAR_BILLS = 50
MIN_STATE_YEARS = 5
MIN_STATE_PERIOD_BILLS = 100
TREND_PERMUTATIONS = 10_000
TREND_RANDOM_SEED = 20_260_731

__all__ = ["party_topic_trends", "state_topic_trends", "benjamini_hochberg"]


def benjamini_hochberg(p_values):
    """Benjamini-Hochberg q-values in original row order."""
    import numpy as np

    values = np.asarray(p_values, dtype=float)
    order = np.argsort(values)
    ranked = values[order]
    adjusted = ranked * len(values) / np.arange(1, len(values) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1].clip(0, 1)
    result = np.empty_like(adjusted)
    result[order] = adjusted
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
        return 1.0
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
    merged = early.merge(late, on=["party", "topic"], how="outer")
    merged[["early_n", "late_n"]] = merged[["early_n", "late_n"]].fillna(0)
    early_totals = frame[frame["year"].isin(EARLY_YEARS)].groupby("party")[
        "n_bills"
    ].sum()
    late_totals = frame[frame["year"].isin(LATE_YEARS)].groupby("party")[
        "n_bills"
    ].sum()
    merged["early_total"] = merged["party"].map(early_totals)
    merged["late_total"] = merged["party"].map(late_totals)
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
    merged = merged.merge(pd.DataFrame(inference), on=["party", "topic"])
    merged["q_value"] = benjamini_hochberg(merged["p_value"])

    yearly = frame.copy()
    totals = yearly.groupby(["year", "party"])["n_bills"].transform("sum")
    yearly["share"] = yearly["n_bills"] / totals
    slope_rows = []
    for (party, topic), group in yearly.groupby(["party", "topic"]):
        by_year = group.groupby("year")["share"].sum().sort_index()
        if len(by_year) < 2:
            continue
        x = by_year.index.to_numpy(dtype=float)
        y = by_year.to_numpy(dtype=float)
        slope = float(((x - x.mean()) @ (y - y.mean())) / ((x - x.mean()) @ (x - x.mean())))
        slope_rows.append({"party": party, "topic": topic, "slope_per_year": slope})
    slopes = pd.DataFrame(slope_rows)
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
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--by-state-year",
        default=root / "data/processed/bill_emphasis_by_state_year.csv",
    )
    parser.add_argument("--out-dir", default=root / "data/processed")
    args = parser.parse_args(argv)

    frame = pd.read_csv(args.by_state_year)
    named = frame[["topic", "topic_name"]].drop_duplicates()
    party = party_topic_trends(frame).merge(named, on="topic", how="left")
    state = state_topic_trends(frame).merge(named, on="topic", how="left")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    party.to_csv(out / "bill_topic_trends_by_party.csv", index=False)
    state.to_csv(out / "bill_topic_trends_by_state.csv", index=False)

    print("largest early-to-late changes (FDR-adjusted):")
    for party_code in ("D", "R"):
        top = party[party["party"] == party_code].reindex(
            party[party["party"] == party_code]["change"].abs()
            .sort_values(ascending=False).index
        ).head(5)
        print(f"\n  {party_code}:")
        for row in top.itertuples():
            print(
                f"    {row.topic_name}: {row.early_share:.1%} -> {row.late_share:.1%} "
                f"({row.change:+.1%}, q={row.q_value:.3g})"
            )
    print(f"\nwrote {out / 'bill_topic_trends_by_party.csv'}")
    print(f"wrote {out / 'bill_topic_trends_by_state.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

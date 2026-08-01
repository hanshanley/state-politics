"""Compare what state parties *say* with what their legislators *file*.

This is the comparison the whole project was built for. Platform emphasis is what a state party
organization declares matters; bill emphasis is what its legislators actually spend the session
filing. The two are produced independently -- different sources, different authors, different
incentives -- and are made comparable only by being classified into the same taxonomy.

Both are measured as **share**: share of platform planks, and share of sponsored bills. Share
rather than count, because states differ enormously in both platform length and legislative
volume (New York files over 100,000 bills in this window and Wyoming a small fraction of
that), so
raw counts would measure institutional throughput rather than priority.

Caveats that belong next to any number produced here
----------------------------------------------------
* Both sides are restricted to the same window. The platform side uses 2018-present planks
  only; pooling the full 1990-2026 corpus against a 2018-2026 bill window would compare
  different eras, and most of the plank corpus predates 2018.
* Bills are classified from their **titles**, which are short and often procedural. That is a
  noisier signal than a platform plank, and the validation figures reported by
  :mod:`state_politics.analysis.validate` are measured on planks, not titles.
* A bill is attributed to a party by its primary sponsors; roughly a fifth cannot be resolved
  to a party at all and are excluded rather than guessed at.
* Filing a bill is not passing one. This measures agenda, not achievement.
"""

from __future__ import annotations

import argparse
import gc
import re
from pathlib import Path

from .taxonomy import DEFAULT_TOPICS_PATH, MIN_TOPIC_SIMILARITY, EmbeddingClassifier, load_topics

__all__ = [
    "classify_bills", "count_topics_by_state", "divergence_table",
    "is_procedural_shell_title", "party_emphasis_from_states",
]

#: Bill titles handed to the classifier per pass. Bounds peak memory on a machine whose RAM is
#: mostly spoken for; the classifier itself slices again internally.
_BILL_SLICE = 100_000
MIN_BILL_YEAR = 2018
_NM_EMERGENCY_CLAUSE_RE = re.compile(
    r"^PUBLIC,?\s+PEACE,\s+HEALTH,\s+SAFETY\s+&\s+WELFARE$",
    re.I,
)


def is_procedural_shell_title(title: str, state: str) -> bool:
    """Known state drafting placeholders that do not describe a bill's subject."""
    title = (title or "").strip()
    return (
        (state == "IL" and title.upper().endswith("-TECH"))
        or (state == "NM" and bool(_NM_EMERGENCY_CLAUSE_RE.fullmatch(title)))
    )


def classify_bills(bills, classifier: EmbeddingClassifier, *, batch_size: int = 512,
                   min_similarity: float = MIN_TOPIC_SIMILARITY, min_title_chars: int = 20):
    """Classify bills by title. Returns the frame with ``topic`` and ``similarity`` columns.

    Very short titles ("Relating to taxation.") carry too little signal to place, and are left
    unclassified rather than assigned on the strength of one word.
    """
    import numpy as np

    # Written to keep peak memory low rather than to read prettily: this runs over ~880k bill
    # titles, and the obvious version (copy the frame, materialise every title, keep a Python
    # list of result tuples) was repeatedly OOM-killed. Nothing here holds more than one slice
    # of embeddings plus two flat arrays.
    frame = bills
    titles = frame["title"].fillna("").astype(str).to_numpy()
    states = (
        frame["state"].fillna("").astype(str).to_numpy()
        if "state" in frame.columns
        else [""] * len(frame)
    )
    procedural = np.fromiter(
        (
            is_procedural_shell_title(title, state)
            for title, state in zip(titles, states, strict=True)
        ),
        dtype=bool,
        count=len(titles),
    )
    long_enough = np.fromiter((len(t) >= min_title_chars for t in titles),
                              dtype=bool, count=len(titles))
    usable = np.flatnonzero(long_enough & ~procedural)

    codes = np.full(len(titles), np.nan, dtype=float)
    scores = np.zeros(len(titles), dtype=float)
    for start in range(0, len(usable), _BILL_SLICE):
        index = usable[start:start + _BILL_SLICE]
        predictions = classifier.predict_many(
            [titles[i] for i in index], batch_size=batch_size, min_similarity=min_similarity,
        )
        for position, (code, similarity, _) in zip(index, predictions, strict=True):
            if code is not None:
                codes[position] = code
            scores[position] = similarity
        del predictions

    return frame.assign(
        topic=codes,
        similarity=np.round(scores, 4),
        procedural_shell=procedural,
    )


def _release_memory() -> None:
    """Drop freed frames and any cached GPU buffers."""
    gc.collect()
    try:
        import torch

        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:  # noqa: BLE001 - releasing memory must never break the run
        pass


def count_topics_by_state(
        bills_path, classifier, *, states=None,
        min_similarity: float = MIN_TOPIC_SIMILARITY,
                          batch_size: int = 512, min_title_chars: int = 20, progress=print):
    """Classify bills **one state at a time**, keeping only the aggregate counts.

    Nothing downstream needs a per-bill topic column: the outputs are counts by
    (state, party, year, topic). Holding 880,000 classified rows in order to group them was
    what kept getting this step OOM-killed on a 16 GB machine.

    Reading is pushed down to the parquet file per state, so peak memory is one state's bills --
    at most New York's ~105,000 -- rather than the whole corpus. The trade is a few seconds of
    extra IO per state, which is nothing next to the embedding pass.
    """
    import pandas as pd

    if states is None:
        states = sorted(pd.read_parquet(bills_path, columns=["state"])["state"].unique())

    frames = []
    coverage_rows = []
    seen = attributed = classified_total = 0
    for position, state in enumerate(states, start=1):
        frame = pd.read_parquet(
            bills_path, columns=["state", "year", "title", "sponsor_party"],
            filters=[("state", "==", state)],
        )
        seen += len(frame)
        frame = frame[frame["sponsor_party"].isin(("D", "R"))].rename(
            columns={"sponsor_party": "party"}).reset_index(drop=True)
        frame = frame[pd.to_numeric(frame["year"], errors="coerce") >= MIN_BILL_YEAR]
        attributed += len(frame)
        if not frame.empty:
            frame = classify_bills(frame, classifier, batch_size=batch_size,
                                   min_similarity=min_similarity,
                                   min_title_chars=min_title_chars)
            usable = frame[frame["topic"].notna()]
            classified_total += len(usable)
            for party, party_frame in frame.groupby("party"):
                substantive = party_frame[~party_frame["procedural_shell"]]
                n_classified = int(substantive["topic"].notna().sum())
                coverage_rows.append(
                    {
                        "state": state,
                        "party": party,
                        "n_attributed": len(party_frame),
                        "n_procedural_excluded": int(
                            party_frame["procedural_shell"].sum()
                        ),
                        "n_substantive_attributed": len(substantive),
                        "n_classified_total": n_classified,
                        "classification_rate": (
                            n_classified / len(substantive) if len(substantive) else 0.0
                        ),
                    }
                )
            if not usable.empty:
                frames.append(usable.groupby(["state", "party", "year", "topic"])
                              .size().rename("n_bills").reset_index())
        del frame
        # Release between states. Python's allocator will not return the freed frame to the OS
        # on its own, and Metal keeps its own cache of buffers from the previous state's
        # embeddings, so without this the footprint creeps upward across 50 iterations and the
        # run dies partway through a corpus it can otherwise handle.
        _release_memory()
        if progress:
            progress(f"  [{position:>2}/{len(states)}] {state}  "
                     f"attributed={attributed:,} classified={classified_total:,}", flush=True)

    counts = (pd.concat(frames, ignore_index=True) if frames
              else pd.DataFrame(
                  columns=["state", "party", "year", "topic", "n_bills"]
              ))
    coverage = pd.DataFrame(coverage_rows)
    return counts, {
        "n_bills": seen,
        "n_attributed": attributed,
        "n_classified": classified_total,
    }, coverage


def divergence_table(platform_emphasis, bill_emphasis):
    """Join stated and revealed emphasis and report the gap between them, per party per topic.

    ``stated_minus_revealed`` is positive where a party's platforms give a topic more room than
    its legislators' bills do.
    """
    import pandas as pd

    stated = platform_emphasis.melt(
        id_vars=["topic", "topic_name"], value_vars=["D", "R"],
        var_name="party", value_name="stated_share",
    )
    merged = stated.merge(
        bill_emphasis.rename(columns={"share": "revealed_share"})[
            ["topic", "party", "revealed_share", "n_bills"]
        ],
        on=["topic", "party"], how="outer",
    )
    merged["stated_share"] = merged["stated_share"].fillna(0.0)
    merged["revealed_share"] = merged["revealed_share"].fillna(0.0)
    merged["stated_minus_revealed"] = merged["stated_share"] - merged["revealed_share"]
    names = (
        pd.concat([platform_emphasis[["topic", "topic_name"]]])
        .drop_duplicates().set_index("topic")["topic_name"]
    )
    merged["topic_name"] = merged["topic"].map(names)
    return merged.sort_values(["party", "stated_minus_revealed"], ascending=[True, False])


def party_emphasis_from_states(state_counts, *, states=None, equal_state=True):
    """Party topic shares, optionally giving every included state equal weight."""
    import pandas as pd

    frame = state_counts.copy()
    if states is not None:
        frame = frame[frame["state"].isin(states)]
    if frame.empty:
        return pd.DataFrame(
            columns=["party", "topic", "n_bills", "share", "topic_name", "n_states"]
        )
    if equal_state:
        vectors = frame.pivot_table(
            index=["state", "party"],
            columns="topic",
            values="share",
            fill_value=0.0,
        )
        means = (
            vectors.groupby(level="party")
            .mean()
            .stack(future_stack=True)
            .rename("share")
            .reset_index()
        )
        counts = (
            frame.groupby(["party", "topic"])["n_bills"]
            .sum()
            .rename("n_bills")
            .reset_index()
        )
        result = means.merge(counts, on=["party", "topic"], how="left")
        result["n_states"] = vectors.index.get_level_values("state").nunique()
    else:
        result = (
            frame.groupby(["party", "topic"])["n_bills"]
            .sum()
            .rename("n_bills")
            .reset_index()
        )
        result["share"] = result["n_bills"] / result.groupby("party")[
            "n_bills"
        ].transform("sum")
        result["n_states"] = frame["state"].nunique()
    names = frame[["topic", "topic_name"]].drop_duplicates().set_index("topic")[
        "topic_name"
    ]
    result["topic_name"] = result["topic"].map(names)
    return result


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bills", default="data/processed/bills.parquet")
    # Default to the era-restricted table: comparing 2018-2026 bills against a platform
    # average that is mostly pre-2018 would not be a like-for-like comparison.
    parser.add_argument("--platform-emphasis",
                        default="data/processed/emphasis_by_party_2018_present.csv")
    parser.add_argument(
        "--platform-by-org",
        default="data/processed/emphasis_by_org.csv",
    )
    parser.add_argument("--topics", default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--out-dir", default="data/processed")
    args = parser.parse_args(argv)

    topics = load_topics(args.topics)
    classifier = EmbeddingClassifier(topics)
    print(f"model {classifier.model_name} on device {classifier.device}")

    by_state, totals, coverage = count_topics_by_state(args.bills, classifier)
    print(f"bills with a party attribution: {totals['n_attributed']:,} "
          f"of {totals['n_bills']:,}")
    print(f"classified: {totals['n_classified']:,}")

    named = {topic.code: topic.name for topic in topics}
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    state_counts = (
        by_state.groupby(["state", "party", "topic"])["n_bills"].sum().reset_index()
    )
    state_counts["share"] = state_counts["n_bills"] / state_counts.groupby(
        ["state", "party"]
    )["n_bills"].transform("sum")
    state_counts["topic_name"] = state_counts["topic"].map(named)
    state_counts = state_counts.merge(
        coverage, on=["state", "party"], how="left", validate="many_to_one"
    )
    state_counts.to_csv(out_dir / "bill_emphasis_by_state.csv", index=False)
    coverage.to_csv(out_dir / "bill_classification_coverage.csv", index=False)

    platform_by_org = pd.read_csv(args.platform_by_org)
    current = platform_by_org[platform_by_org["era"] == "2018-present"]
    platform_states = {
        party: set(current.loc[current["party"] == party, "state"])
        for party in ("D", "R")
    }
    bill_states = {
        party: set(state_counts.loc[state_counts["party"] == party, "state"])
        for party in ("D", "R")
    }
    matched_states = (
        platform_states["D"]
        & platform_states["R"]
        & bill_states["D"]
        & bill_states["R"]
    )
    counts = party_emphasis_from_states(state_counts, states=matched_states)
    counts.to_csv(out_dir / "bill_emphasis_by_party.csv", index=False)
    party_emphasis_from_states(state_counts, equal_state=False).to_csv(
        out_dir / "bill_emphasis_by_party_pooled_sensitivity.csv",
        index=False,
    )

    year_counts = (
        by_state.groupby(["year", "party", "topic"])["n_bills"].sum().reset_index()
    )
    year_counts["share"] = year_counts["n_bills"] / year_counts.groupby(
        ["year", "party"]
    )["n_bills"].transform("sum")
    year_counts["topic_name"] = year_counts["topic"].map(named)
    year_counts.to_csv(out_dir / "bill_emphasis_by_year.csv", index=False)

    state_year_counts = by_state.copy()
    state_year_counts["share"] = (
        state_year_counts["n_bills"]
        / state_year_counts.groupby(["state", "party", "year"])["n_bills"].transform("sum")
    )
    state_year_counts["topic_name"] = state_year_counts["topic"].map(named)
    state_year_counts.to_csv(out_dir / "bill_emphasis_by_state_year.csv", index=False)

    platform_vectors = (
        current[current["state"].isin(matched_states)]
        .pivot_table(
            index=["state", "party"],
            columns="topic",
            values="share",
            fill_value=0.0,
        )
    )
    platform = (
        platform_vectors.groupby(level="party")
        .mean()
        .T.reindex(columns=["D", "R"])
        .fillna(0.0)
        .reset_index()
    )
    platform["topic_name"] = platform["topic"].map(named)
    divergence = divergence_table(platform, counts)
    divergence.to_csv(out_dir / "stated_vs_revealed.csv", index=False)

    print("\nlargest gaps between what a party says and what it files:")
    display = divergence.copy()
    for column in ("stated_share", "revealed_share", "stated_minus_revealed"):
        display[column] = (display[column] * 100).round(1)
    for party in ("D", "R"):
        subset = display[display["party"] == party]
        print(f"\n  {party}: talked about far more than filed")
        print(subset.head(3)[["topic_name", "stated_share", "revealed_share"]]
              .to_string(index=False))
        print(f"  {party}: filed far more than talked about")
        print(subset.tail(3)[["topic_name", "stated_share", "revealed_share"]]
              .to_string(index=False))

    print(f"\nwrote {out_dir / 'bill_emphasis_by_party.csv'}")
    print(f"wrote {out_dir / 'bill_emphasis_by_state.csv'}")
    print(f"wrote {out_dir / 'bill_classification_coverage.csv'}")
    print(f"wrote {out_dir / 'stated_vs_revealed.csv'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

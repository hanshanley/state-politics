"""How much do state parties disagree with each other *within* the same party?

The headline comparison in this project is between the parties. That treats "the Democrats"
and "the Republicans" as two coherent actors, which is exactly the assumption a 50-state
dataset is able to test. Texas Republicans and Massachusetts Republicans are both Republican
parties; whether they emphasise the same things is an empirical question, not a given.

Three measures, each answering a different question:

* **Dispersion** -- how far apart are a party's state organizations, on average? Computed as
  the mean pairwise cosine distance between state topic-share vectors. Comparing the two
  parties' dispersion answers "which party is more internally varied?"
* **Divisive topics** -- which topics do state parties within a party disagree *about*?
  Measured as the cross-state standard deviation of each topic's share. A topic can be large
  and uncontested (every state party talks about health) or small and divisive.
* **Centre and periphery** -- which state parties sit closest to, and furthest from, their own
  party's centroid.

Every measure is computed separately for what parties **say** (platform planks) and what their
legislators **file** (bills), because there is no reason those should agree: a party's
platforms are written by 50 independent committees, while its bills are constrained by what
each legislature is actually able to consider.

**This measures agenda overlap, not agreement.** Every vector here is a distribution over
*topics*, so two organizations are "close" when they devote similar shares of attention to the
same subjects -- not when they want the same things. A Democratic and a Republican platform
that both spend 10% of their planks on abortion are adjacent on this measure while advocating
opposite policies. That makes within-versus-between distance a statement about what parties put
on the agenda, and it is why the ratio below is not evidence that the two parties are
ideologically similar.

Two further cautions built into the code rather than left to the reader:

* Dispersion is compared between parties only over the **same set of states**. The two parties
  do not have platforms in the same places, and a party whose surviving documents come from
  more unusual states would otherwise look more divided for purely compositional reasons.
* Bill vectors exist for all 50 states, platform vectors do not, so the two streams are never
  compared on dispersion without restricting to states present in both.
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

from .profiles import MIN_OBSERVATIONS, topic_vectors

__all__ = [
    "cosine_distance",
    "dispersion",
    "divisive_topics",
    "distance_to_centroid",
    "common_states",
    "dispersion_gap_pvalue",
    "coherence",
]

DEFAULT_PERMUTATIONS = 5000
RANDOM_SEED = 20260729


def cosine_distance(left, right) -> float:
    """Cosine distance between two topic-share vectors.

    Cosine rather than Euclidean because it compares the *shape* of an agenda. State parties
    differ enormously in how much they publish, and a Euclidean measure would mostly rank
    states by volume.
    """
    import numpy as np

    left = np.asarray(left, dtype=float)
    right = np.asarray(right, dtype=float)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator == 0.0:
        return float("nan")
    return 1.0 - float(left @ right) / denominator


def common_states(vectors, parties=("D", "R")) -> list[str]:
    """States that have a vector for every party named.

    Dispersion is only comparable across parties on a common set of states. Otherwise a party
    whose platforms happen to survive in more idiosyncratic states scores as more divided
    without any of its organizations actually disagreeing more.
    """
    if vectors.empty:
        return []
    present = [set(vectors.xs(party, level="party").index) for party in parties
               if party in vectors.index.get_level_values("party")]
    if len(present) < len(parties):
        return []
    return sorted(set.intersection(*present))


def dispersion(vectors, *, states: list[str] | None = None):
    """Mean pairwise cosine distance between a party's state organizations.

    Returns one row per party with the mean, median and spread, plus the state count the
    figure is based on -- which the reader needs, because dispersion over 40 states and over 6
    are not the same claim.
    """
    import numpy as np
    import pandas as pd

    rows = []
    for party in sorted(vectors.index.get_level_values("party").unique()):
        block = vectors.xs(party, level="party")
        if states is not None:
            block = block.loc[block.index.intersection(states)]
        if len(block) < 2:
            continue
        distances = [cosine_distance(block.loc[a], block.loc[b])
                     for a, b in itertools.combinations(block.index, 2)]
        distances = [d for d in distances if not np.isnan(d)]
        if not distances:
            continue
        rows.append({
            "party": party,
            "n_states": len(block),
            "n_pairs": len(distances),
            "mean_distance": round(float(np.mean(distances)), 4),
            "median_distance": round(float(np.median(distances)), 4),
            "p90_distance": round(float(np.percentile(distances, 90)), 4),
        })
    return pd.DataFrame(rows)


def coherence(vectors, *, states: list[str] | None = None):
    """Compare distance *within* each party against distance *between* the parties.

    This is the measure that survives a small sample, and it asks the question the whole
    exercise is about: are the two parties coherent blocs at all? If a Republican state party
    is about as far from another Republican state party as it is from a Democratic one, then
    "the Republican agenda" is not a single object and every national average in this project
    is an average over genuinely different actors.

    The ratio is within/between. Near 0 means tight, clearly separated parties; near 1 means
    the party label carries no information about how alike two state organizations are.
    """
    import numpy as np
    import pandas as pd

    parties = sorted(vectors.index.get_level_values("party").unique())
    if len(parties) != 2:
        return pd.DataFrame()
    blocks = {}
    for party in parties:
        block = vectors.xs(party, level="party")
        if states is not None:
            block = block.loc[block.index.intersection(states)]
        blocks[party] = block
    if min(len(b) for b in blocks.values()) < 2:
        return pd.DataFrame()

    def clean(values):
        values = [v for v in values if not np.isnan(v)]
        return float(np.mean(values)) if values else float("nan")

    within = {
        party: clean([cosine_distance(block.loc[a], block.loc[b])
                      for a, b in itertools.combinations(block.index, 2)])
        for party, block in blocks.items()
    }
    # Same-state pairs are excluded. Within-party pairs are always cross-state (each state
    # appears once per party), so including the D-R pair *inside* a state would compare unlike
    # things -- and those pairs are systematically closer (platforms 0.273 vs 0.317
    # cross-state), which biases the ratio upward, in the direction of this section's own
    # headline. Dropping them makes the two sides comparable and the claim more conservative.
    left, right = blocks[parties[0]], blocks[parties[1]]
    between = clean([cosine_distance(left.loc[a], right.loc[b])
                     for a in left.index for b in right.index if a != b])
    mean_within = float(np.mean(list(within.values())))
    return pd.DataFrame([{
        "within_" + parties[0]: round(within[parties[0]], 4),
        "within_" + parties[1]: round(within[parties[1]], 4),
        "mean_within": round(mean_within, 4),
        "between": round(between, 4),
        "within_over_between": round(mean_within / between, 3) if between else None,
        "n_states": min(len(left), len(right)),
    }])


def dispersion_gap_pvalue(vectors, *, states: list[str] | None = None,
                          n_permutations: int = DEFAULT_PERMUTATIONS,
                          seed: int = RANDOM_SEED) -> dict:
    """Is one party really more internally varied than the other, or is that noise?

    With a dozen state parties per side, a difference in mean pairwise distance is easy to
    produce by chance, and reporting it unqualified would be the sort of claim this project
    exists to avoid. The party labels are shuffled between the same set of vectors and the
    dispersion gap recomputed; the p-value is the share of shuffles producing a gap at least
    as large as the observed one.

    Shuffling *labels* rather than resampling states keeps the state composition fixed, so the
    test asks exactly the intended question: given these organizations, does it matter which
    party each belongs to?
    """
    import numpy as np

    parties = sorted(vectors.index.get_level_values("party").unique())
    if len(parties) != 2:
        return {}
    blocks = {}
    for party in parties:
        block = vectors.xs(party, level="party")
        if states is not None:
            block = block.loc[block.index.intersection(states)]
        blocks[party] = block
    if min(len(b) for b in blocks.values()) < 2:
        return {}

    pooled = np.vstack([blocks[p].to_numpy() for p in parties])
    sizes = [len(blocks[p]) for p in parties]

    def mean_pairwise(matrix) -> float:
        pairs = [cosine_distance(matrix[i], matrix[j])
                 for i, j in itertools.combinations(range(len(matrix)), 2)]
        pairs = [d for d in pairs if not np.isnan(d)]
        return float(np.mean(pairs)) if pairs else float("nan")

    observed = mean_pairwise(pooled[:sizes[0]]) - mean_pairwise(pooled[sizes[0]:])
    rng = np.random.default_rng(seed)
    extreme = 0
    for _ in range(n_permutations):
        order = rng.permutation(len(pooled))
        shuffled = pooled[order]
        gap = mean_pairwise(shuffled[:sizes[0]]) - mean_pairwise(shuffled[sizes[0]:])
        if abs(gap) >= abs(observed):
            extreme += 1
    return {
        "parties": f"{parties[0]}-{parties[1]}",
        "observed_gap": round(observed, 4),
        "p_value": round((extreme + 1) / (n_permutations + 1), 4),
        "n_permutations": n_permutations,
    }


def divisive_topics(vectors, topic_names, *, states: list[str] | None = None):
    """Cross-state standard deviation of each topic's share, within each party.

    Standard deviation is reported next to the mean deliberately. A topic with a high SD and a
    high mean is one every state party addresses but weights differently; a high SD on a low
    mean is a topic a handful of state parties care about and the rest ignore. Those are
    different findings and the ratio alone hides which is which.
    """
    import pandas as pd

    rows = []
    for party in sorted(vectors.index.get_level_values("party").unique()):
        block = vectors.xs(party, level="party")
        if states is not None:
            block = block.loc[block.index.intersection(states)]
        if len(block) < 2:
            continue
        for topic in block.columns:
            column = block[topic]
            mean = float(column.mean())
            rows.append({
                "party": party,
                "topic": int(topic),
                "topic_name": topic_names.get(int(topic), str(topic)),
                "n_states": len(block),
                "mean_share": round(mean, 4),
                "sd_share": round(float(column.std(ddof=1)), 4),
                "max_state": column.idxmax(),
                "max_share": round(float(column.max()), 4),
                "min_share": round(float(column.min()), 4),
            })
    frame = pd.DataFrame(rows)
    return frame.sort_values(["party", "sd_share"], ascending=[True, False])


def distance_to_centroid(vectors, *, states: list[str] | None = None):
    """How far each state party sits from its own party's average agenda.

    The centroid is recomputed per party from the states included, so it is the average of the
    organizations actually being compared rather than a national figure imported from
    elsewhere.
    """
    import pandas as pd

    rows = []
    for party in sorted(vectors.index.get_level_values("party").unique()):
        block = vectors.xs(party, level="party")
        if states is not None:
            block = block.loc[block.index.intersection(states)]
        if len(block) < 2:
            continue
        centroid = block.mean(axis=0)
        for state, vector in block.iterrows():
            difference = (vector - centroid)
            topic = int(difference.abs().idxmax())
            rows.append({
                "state": state,
                "party": party,
                "distance_to_centroid": round(cosine_distance(vector, centroid), 4),
                "most_distinctive_topic": topic,
                "share": round(float(vector[topic]), 4),
                "party_mean_share": round(float(centroid[topic]), 4),
            })
    frame = pd.DataFrame(rows)
    return frame.sort_values(["party", "distance_to_centroid"], ascending=[True, False])


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    from .taxonomy import DEFAULT_TOPICS_PATH, load_topics

    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--platform-emphasis", default=root / "data/processed/emphasis_by_org.csv")
    parser.add_argument("--bill-emphasis",
                        default=root / "data/processed/bill_emphasis_by_state.csv")
    parser.add_argument("--topics", default=DEFAULT_TOPICS_PATH)
    parser.add_argument("--out-dir", default=root / "data/processed")
    parser.add_argument("--min-observations", type=int, default=MIN_OBSERVATIONS)
    parser.add_argument("--permutations", type=int, default=DEFAULT_PERMUTATIONS)
    parser.add_argument("--era", default="2018-present",
                        help="platform era to restrict to; '' pools all eras")
    args = parser.parse_args(argv)

    topic_names = {t.code: t.name for t in load_topics(args.topics)}
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    platforms = pd.read_csv(args.platform_emphasis)
    if args.era and "era" in platforms.columns:
        platforms = platforms[platforms["era"] == args.era]
    platform_vectors = topic_vectors(platforms, count_column="n_planks",
                                     min_observations=args.min_observations)

    bills = pd.read_csv(args.bill_emphasis)
    bill_count_column = "n_bills" if "n_bills" in bills.columns else "n_planks"
    bill_vectors = topic_vectors(bills, count_column=bill_count_column,
                                 min_observations=args.min_observations)

    results = {}
    for label, vectors in (("platform", platform_vectors), ("bill", bill_vectors)):
        if vectors.empty:
            print(f"{label}: no organization met the {args.min_observations}-observation floor")
            continue
        shared = common_states(vectors)
        spread = dispersion(vectors, states=shared)
        results[label] = spread
        print(f"\n=== {label} agendas: how far apart are a party's own state organizations? ===")
        print(f"compared over the {len(shared)} states where both parties qualify")
        for _, row in spread.iterrows():
            print(f"  {row['party']}  mean pairwise distance {row['mean_distance']:.3f}  "
                  f"median {row['median_distance']:.3f}  "
                  f"(n={int(row['n_states'])} states, {int(row['n_pairs'])} pairs)")
        test = dispersion_gap_pvalue(vectors, states=shared,
                                     n_permutations=args.permutations)
        if test:
            verdict = ("distinguishable from chance" if test["p_value"] < 0.05
                       else "NOT distinguishable from chance")
            print(f"  gap {test['observed_gap']:+.3f} ({test['parties']}), "
                  f"permutation p={test['p_value']:.3f} -- {verdict}")
            results.setdefault("_tests", []).append({"stream": label, **test})

        blocs = coherence(vectors, states=shared)
        if not blocs.empty:
            row = blocs.iloc[0]
            print(f"  within-party {row['mean_within']:.3f} vs between-party "
                  f"{row['between']:.3f}  ->  ratio {row['within_over_between']:.2f}")
            blocs.assign(stream=label).to_csv(
                out_dir / f"intraparty_{label}_coherence.csv", index=False)

        divisive = divisive_topics(vectors, topic_names, states=shared)
        divisive.to_csv(out_dir / f"intraparty_{label}_topic_spread.csv", index=False)
        for party in sorted(divisive["party"].unique()):
            top = divisive[divisive["party"] == party].head(3)
            names = ", ".join(f"{r.topic_name} (sd {r.sd_share * 100:.1f}pp)"
                              for r in top.itertuples())
            print(f"  {party} most divisive: {names}")

        centroid = distance_to_centroid(vectors, states=shared)
        centroid.to_csv(out_dir / f"intraparty_{label}_distance.csv", index=False)

    tests = results.pop("_tests", [])
    if tests:
        pd.DataFrame(tests).to_csv(out_dir / "intraparty_dispersion_tests.csv", index=False)
    if results:
        combined = pd.concat([frame.assign(stream=label) for label, frame in results.items()],
                             ignore_index=True)
        combined.to_csv(out_dir / "intraparty_dispersion.csv", index=False)
        print(f"\nwrote {out_dir / 'intraparty_dispersion.csv'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Detect text reuse across states -- the signature of model legislation.

State legislatures do not draft in isolation. Advocacy groups and legislative-exchange
organisations circulate template bills, and the same text surfaces in a dozen capitols in the
same session. That reuse is visible in the data: it looks like a bill title appearing, near
verbatim, in states that share nothing but a sponsor's party.

Method
------
Two passes, both over titles normalised by lowercasing and stripping bill numbers, years and
ordinals -- exactly the parts two states running one template differ on.

1. :func:`find_reuse_clusters` groups by *exact* match on the normalised form. Conservative, and
   finds only templates adopted verbatim.
2. :func:`find_near_duplicates` clusters by Jaccard similarity over content words, which is what
   the published headline figures come from, because real model legislation is edited in
   transit. Candidates are blocked by their rarest content words; clusters are connected
   components, so ``n_states`` is an upper bound on the spread of one template rather than a
   count of titles that each passed the threshold pairwise.

Generic administrative titles are excluded and a length floor applies, because every state files
a budget bill and that is not evidence of copying.

What this does and does not show
--------------------------------
It shows *text reuse*, not authorship or coordination -- two states can independently name a
bill "An Act relating to the state budget", which is why generic administrative titles are
excluded and a length floor is applied. A group is evidence worth looking at, not proof.
"""

from __future__ import annotations

import argparse
import itertools
import re
from pathlib import Path

__all__ = ["find_near_duplicates", "find_reuse_clusters", "is_ceremonial",
           "normalize_title", "significant_tokens"]

#: Titles shorter than this are generic ("Appropriations", "Relating to taxation") and match
#: across states by coincidence rather than by copying.
MIN_TITLE_CHARS = 45
MIN_REUSE_STATES = 3
MIN_NEAR_DUPLICATE_TOKENS = 5
NEAR_DUPLICATE_THRESHOLD = 0.8
MAX_CANDIDATE_BLOCK = 400

#: Boilerplate that varies between states and would otherwise block an exact match.
_BILL_NUMBER_RE = re.compile(r"\b(?:hb|sb|hf|sf|ab|hr|sr|hjr|sjr|lb|ho|so)\s*\.?\s*\d+\b", re.I)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_ORDINAL_RE = re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.I)
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")

#: Purely administrative titles that recur everywhere and mean nothing for diffusion.
_GENERIC_RE = re.compile(
    r"^(?:an act |a bill )?(?:relating to |concerning |regarding )?"
    r"(?:the )?(?:general |state )?"
    r"(?:appropriations?|budget|supplemental appropriations?|revenue|"
    r"making appropriations|adjournment|recess|rules)\b",
    re.I,
)


_CLUSTER_COLUMNS = ["n_states", "n_bills", "states", "first_year", "last_year",
                    "example_title", "min_similarity"]


def _empty_clusters(*, with_normalized: bool = False):
    """Empty frame carrying the full column set, so callers can drop/select without KeyError."""
    import pandas as pd

    columns = (["normalized"] if with_normalized else []) + _CLUSTER_COLUMNS
    return pd.DataFrame(columns=columns)


def normalize_title(title: str) -> str:
    """Reduce a bill title to a comparable form.

    Strips bill numbers, years and ordinals -- the parts guaranteed to differ between two
    states running the same template -- then punctuation and casing.
    """
    text = (title or "").lower()
    text = _BILL_NUMBER_RE.sub(" ", text)
    text = _YEAR_RE.sub(" ", text)
    text = _ORDINAL_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_reuse_clusters(
    bills, *, min_states: int = MIN_REUSE_STATES, min_chars: int = MIN_TITLE_CHARS
):
    """Group bills whose normalised titles match across several states.

    Returns one row per cluster: the shared text, how many states and bills it spans, and the
    party composition of its sponsors -- which is the interesting part, since a template
    circulating through one party's legislators looks very different from a technical
    uniform-law adoption that both parties file.
    """

    frame = bills[["state", "year", "title", "sponsor_party"]].copy()
    frame["normalized"] = frame["title"].fillna("").map(normalize_title)
    frame = frame[
        (frame["normalized"].str.len() >= min_chars)
        & (~frame["normalized"].str.match(_GENERIC_RE))
    ]
    if frame.empty:
        return _empty_clusters(with_normalized=True)

    grouped = frame.groupby("normalized")
    summary = grouped.agg(
        n_states=("state", "nunique"),
        n_bills=("state", "size"),
        states=("state", lambda s: ",".join(sorted(set(s)))),
        first_year=("year", "min"),
        last_year=("year", "max"),
        example_title=("title", "first"),
    ).reset_index()
    summary = summary[summary["n_states"] >= min_states]
    if summary.empty:
        return _empty_clusters(with_normalized=True)

    parties = (
        frame[frame["sponsor_party"].isin(["D", "R"])]
        .groupby(["normalized", "sponsor_party"]).size().unstack(fill_value=0)
        .reindex(columns=["D", "R"]).fillna(0).astype(int)
        .rename(columns={"D": "n_D", "R": "n_R"}).reset_index()
    )
    summary = summary.merge(parties, on="normalized", how="left")
    summary[["n_D", "n_R"]] = summary[["n_D", "n_R"]].fillna(0).astype(int)
    total = (summary["n_D"] + summary["n_R"]).replace(0, 1)
    summary["party_skew"] = ((summary["n_D"] - summary["n_R"]) / total).round(3)
    return summary.sort_values(["n_states", "n_bills"], ascending=False)


#: Words carrying no distinguishing signal in a bill title.
_STOPWORDS = frozenset([
    "a", "an", "the", "of", "to", "in", "for", "on", "and", "or", "by", "with", "from",
    "at", "as", "be", "is", "are", "was", "were", "relating", "relate", "relates", "act",
    "bill", "resolution", "concerning", "regarding", "provide", "providing", "provisions",
    "amend", "amending", "amendment", "establish", "establishing", "certain", "state",
    "states", "general", "public", "new", "law", "laws", "section", "sections",
])


def significant_tokens(normalized: str) -> frozenset[str]:
    """Content words of a normalised title, for set-similarity comparison."""
    return frozenset(
        token for token in normalized.split()
        if len(token) > 2 and token not in _STOPWORDS and not token.isdigit()
    )


def find_near_duplicates(
                         bills, *, min_states: int = MIN_REUSE_STATES,
                         min_tokens: int = MIN_NEAR_DUPLICATE_TOKENS,
                         threshold: float = NEAR_DUPLICATE_THRESHOLD,
                         max_block: int = MAX_CANDIDATE_BLOCK,
                         block_keys: int = 3):
    """Cluster bills whose titles are near-identical, allowing for rewording.

    Exact matching finds only templates adopted verbatim, and real model legislation is edited
    in transit. This compares content-word sets with Jaccard similarity.

    Comparing a million titles pairwise is impossible, so candidates are blocked by their
    *rarest* content word: two near-identical titles must share their rare vocabulary, while a
    common word like "education" would put a hundred thousand titles in one block. Blocks above
    ``max_block`` are skipped rather than allowed to dominate the runtime.
    """

    frame = bills[["state", "year", "title", "sponsor_party"]].copy()
    frame["normalized"] = frame["title"].fillna("").map(normalize_title)
    frame["tokens"] = frame["normalized"].map(significant_tokens)
    frame = frame[frame["tokens"].map(len) >= min_tokens]
    if frame.empty:
        return _empty_clusters()
    # Union-find keys off the index, so a duplicated label would collapse two unrelated bills
    # into one node and union everything they touch -- manufacturing a cluster out of nothing.
    frame = frame.reset_index(drop=True)

    document_frequency: dict[str, int] = {}
    for tokens in frame["tokens"]:
        for token in tokens:
            document_frequency[token] = document_frequency.get(token, 0) + 1

    # Block on the several rarest tokens rather than only the single rarest: two versions of
    # one template often differ in exactly which rare word they keep, and a single key put them
    # in different blocks where they were never compared.
    blocks: dict[str, list[int]] = {}
    for index, tokens in zip(frame.index, frame["tokens"], strict=True):
        rarest = sorted(tokens, key=lambda t: (document_frequency[t], t))[:block_keys]
        for token in rarest:
            blocks.setdefault(token, []).append(index)

    parent = {index: index for index in frame.index}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    token_map = frame["tokens"].to_dict()
    for members in blocks.values():
        if len(members) < 2 or len(members) > max_block:
            continue
        for position, left in enumerate(members):
            left_tokens = token_map[left]
            for right in members[position + 1:]:
                right_tokens = token_map[right]
                overlap = len(left_tokens & right_tokens)
                if not overlap:
                    continue
                if overlap / len(left_tokens | right_tokens) >= threshold:
                    union(left, right)

    frame["cluster"] = [find(index) for index in frame.index]

    # Clusters are connected components, so membership is transitive: A~B and B~C puts A and C
    # together even if they are not themselves similar. Measured on the real corpus the minimum
    # intra-cluster similarity falls as low as 0.17 against a 0.80 threshold. Reporting that
    # minimum lets a reader see how tight a cluster actually is, instead of `n_states` being
    # read as "this many states filed near-identical text".
    cohesion: dict[int, float] = {}
    for cluster, members in frame.groupby("cluster").groups.items():
        variants = {token_map[index] for index in members}
        if len(variants) < 2:
            cohesion[cluster] = 1.0
            continue
        pairs = [
            len(left & right) / len(left | right)
            for left, right in itertools.combinations(variants, 2)
        ]
        cohesion[cluster] = round(min(pairs), 3) if pairs else 1.0
    frame["min_similarity"] = frame["cluster"].map(cohesion)

    summary = frame.groupby("cluster").agg(
        n_states=("state", "nunique"),
        n_bills=("state", "size"),
        states=("state", lambda s: ",".join(sorted(set(s)))),
        first_year=("year", "min"),
        last_year=("year", "max"),
        example_title=("title", "first"),
        min_similarity=("min_similarity", "first"),
    ).reset_index(drop=True)
    summary = summary[summary["n_states"] >= min_states]
    return summary.sort_values(["n_states", "n_bills"], ascending=False)


#: Commemorative and ceremonial language. Templates for "recognizing X month" circulate just as
#: widely as policy bills and would otherwise dominate the results, but they say nothing about
#: a party's legislative agenda, so they are flagged rather than silently mixed in.
_CEREMONIAL_RE = re.compile(
    r"\b(?:recogniz|commemorat|designat|honor|congratulat|celebrat|proclaim|"
    r"condolence|memoriam|mourning|salut|commend)\w*\b"
    r"|\b(?:awareness|appreciation|remembrance)\s+(?:month|week|day)\b"
    r"|\bmonth of\b|\bweek of\b|\bday as\b",
    re.I,
)


def is_ceremonial(title: str) -> bool:
    """True for commemorative resolutions rather than substantive policy."""
    return bool(_CEREMONIAL_RE.search(title or ""))


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bills", default="data/processed/bills.parquet")
    parser.add_argument("--out-dir", default="data/processed")
    parser.add_argument("--min-states", type=int, default=3)
    args = parser.parse_args(argv)

    bills = pd.read_parquet(args.bills, columns=["state", "year", "title", "sponsor_party"])
    clusters = find_reuse_clusters(bills, min_states=args.min_states)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "text_reuse_clusters.csv"
    clusters.drop(columns=["normalized"]).to_csv(path, index=False)

    print(f"bills considered:   {len(bills):,}")
    print(f"reuse clusters:     {len(clusters):,} spanning >= {args.min_states} states")
    if not clusters.empty:
        print(f"bills in clusters:  {int(clusters['n_bills'].sum()):,}")
        print(f"widest cluster:     {int(clusters['n_states'].max())} states")
        print("\nmost widely reused bill text:")
        for _, row in clusters.head(12).iterrows():
            skew = ("D" if row["party_skew"] > 0.5 else
                    "R" if row["party_skew"] < -0.5 else "mixed")
            print(f"  {int(row['n_states']):>2} states, {int(row['n_bills']):>3} bills "
                  f"[{skew:<5}] {row['example_title'][:78]}")
    print(f"\nwrote {path}")

    near = find_near_duplicates(bills, min_states=args.min_states)
    near["ceremonial"] = near["example_title"].map(is_ceremonial)
    near_path = out_dir / "text_reuse_near_duplicates.csv"
    near.to_csv(near_path, index=False)
    print(f"\nnear-duplicate clusters: {len(near):,} spanning >= {args.min_states} states")
    if not near.empty:
        print(f"bills in clusters:       {int(near['n_bills'].sum()):,}")
        print(f"widest cluster:          {int(near['n_states'].max())} states")
        substantive = near[~near["ceremonial"]]
        print(f"substantive:             {len(substantive):,} "
              f"({int(near['ceremonial'].sum()):,} ceremonial, flagged separately)")
        print("\nmost widely reused substantive bill text:")
        for _, row in substantive.head(12).iterrows():
            print(f"  {int(row['n_states']):>2} states, {int(row['n_bills']):>3} bills, "
                  f"cohesion {row['min_similarity']:.2f}  {row['example_title'][:56]}")
    print(f"\nwrote {near_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

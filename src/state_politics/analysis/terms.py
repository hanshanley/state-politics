"""Simple TF-IDF and log2 term concentration within each party.

TF-IDF answers: which words or two-word phrases distinguish this state-party document from all
other state-party documents?

Log2 concentration answers the stricter within-party question:

    log2((term rate in this state party) / (term rate in other states of the same party))

So +1 means twice as concentrated as same-party peers, +2 means four times, and -1 means half
as concentrated. Rates use additive smoothing, and terms must clear a minimum raw count before
they are eligible for highlights.

The analysis runs separately on (1) bill titles and (2) stated agenda text. Party-committee
documents are preferred for the stated stream; the separately labelled caucus supplement is
used only where committee evidence is absent.
"""

from __future__ import annotations

import argparse
from pathlib import Path

__all__ = [
    "build_bill_documents",
    "build_stated_documents",
    "distinctive_terms",
]

_EXTRA_STOP_WORDS = {
    "act", "acts", "amend", "amending", "bill", "bills", "chapter", "code", "concerning",
    "create", "creates", "establish", "establishing", "law", "laws", "provide", "provides",
    "relating", "relative", "require", "requires", "resolution", "revised", "section", "state",
    "states", "house", "senate", "committee", "party", "democrat", "democratic", "republican",
    "shall", "new", "public", "department", "program", "commission", "board",
    # Legislative boilerplate and ceremonial/title furniture.
    "am'd", "sec", "secs", "effective", "date", "providing", "declare",
    "declaring", "emergency", "introduction", "nonappropriation", "authorize", "authorizing",
    "appropriation", "appropriations", "fiscal", "mourned", "commended", "recognize",
    "recognizing", "honoring", "honoured", "champions", "title", "proposal", "passed",
    "adopted", "submitted", "signatures", "meeting", "comments", "yes",
    "existing", "revise", "revising", "regarding", "subsection", "subsections", "sections",
    "reenact", "reenacting", "enact", "enacting", "requirement", "requirements", "increased",
    "expenditure", "expenditures", "funds", "meaning", "inclusive", "added", "continued",
    "review", "general", "technical", "corrections", "proposing", "extending", "urging",
    "directing", "joint", "appointment", "appointments", "confirming", "adjourning",
    "loving", "memory", "memorializing", "governor", "proclaim", "proclaiming", "occasion",
    "celebrating", "commendation", "commendations", "commends", "fisc", "note", "notes",
    "signed", "signature", "known", "session", "regular", "special", "ninety-third",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "year", "day", "chair", "secretary", "floor",
    "headings", "learn", "main", "content", "skip", "websites",
    # HTML entities and common bilingual-page function words, neither of which is policy.
    "ldquo", "rdquo", "lsquo", "rsquo", "nbsp", "mdash", "amp",
    "los", "las", "para", "por", "una", "uno", "del", "que", "con", "como", "sus",
}

_STATE_NAMES = (
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut",
    "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa",
    "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan",
    "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina",
    "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
    "Washington", "West Virginia", "Wisconsin", "Wyoming",
)
_STATE_WORDS = {word.lower() for name in _STATE_NAMES for word in name.split()}
_STATE_CODES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
)
_STATE_NAME_BY_CODE = dict(zip(_STATE_CODES, _STATE_NAMES, strict=True))
_DEMONYMS = {
    "alabamians", "alaskans", "alaskan", "arizonans", "arkansans", "californians",
    "coloradans", "delawareans", "floridians", "georgians", "hawaiians", "hawaiian",
    "idahoans", "illinoisians", "indianans", "iowans", "kansans", "kentuckians",
    "louisianans", "mainers", "marylanders", "michiganders", "minnesotans",
    "mississippians", "missourians", "montanans", "nebraskans", "nevadans",
    "new yorkers", "new mexicans", "ohioans", "oklahomans", "oregonians",
    "pennsylvanians", "carolinians", "dakotans", "tennesseans", "texans", "utahns",
    "vermonters", "virginians", "washingtonians", "wisconsinites", "wyomingites",
}


def build_bill_documents(bills):
    """One concatenated bill-title document per state and major party."""
    frame = bills[bills["sponsor_party"].isin(("D", "R"))].copy()
    frame["party"] = frame["sponsor_party"]
    documents = (
        frame.groupby(["state", "party"])["title"]
        .agg(lambda values: ". ".join(v for v in values.fillna("").astype(str) if v))
        .rename("text").reset_index()
    )
    source_counts = (
        frame.groupby(["state", "party"]).size().rename("n_source_items").reset_index()
    )
    documents = documents.merge(
        source_counts, on=["state", "party"], how="left", validate="one_to_one"
    )
    documents["stream"] = "bills"
    return documents


def _clean_text(text: str) -> str:
    """Remove markup remnants and URLs before tokenization."""
    import html
    import re

    text = html.unescape(text or "")
    text = re.sub(r"\b([a-z]+)-tech\b", r"\1 technology", text, flags=re.I)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def build_stated_documents(platforms, caucuses):
    """One current stated-agenda document per state party, preserving source type."""
    import pandas as pd

    from .state_focus import caucus_units

    current = platforms[
        platforms["confirmed"] & (pd.to_numeric(platforms["year"], errors="coerce") >= 2018)
    ].copy()
    committee = (
        current.groupby(["state", "party"])["text"]
        .agg(lambda values: "\n\n".join(values.fillna("").astype(str)))
        .rename("text").reset_index()
    )
    committee_counts = (
        current.groupby(["state", "party"]).size().rename("n_source_items").reset_index()
    )
    committee = committee.merge(
        committee_counts, on=["state", "party"], how="left", validate="one_to_one"
    )
    committee["evidence_type"] = "party_committee"

    keys = set(map(tuple, committee[["state", "party"]].values))
    supplement_rows = caucus_units(caucuses)
    supplement = (
        supplement_rows[
            ~supplement_rows[["state", "party"]].apply(tuple, axis=1).isin(keys)
        ]
        .groupby(["state", "party"])["text"]
        .agg(lambda values: "\n\n".join(values))
        .rename("text").reset_index()
    )
    supplement_counts = (
        supplement_rows.groupby(["state", "party"]).size()
        .rename("n_source_items").reset_index()
    )
    supplement = supplement.merge(
        supplement_counts, on=["state", "party"], how="left", validate="one_to_one"
    )
    supplement["evidence_type"] = "legislative_caucus"

    documents = pd.concat([committee, supplement], ignore_index=True)
    documents["stream"] = "stated"
    return documents


def _eligible_feature(term: str, state: str) -> bool:
    words = set(term.split())
    if words & (_EXTRA_STOP_WORDS | _DEMONYMS):
        return False
    state_words = set(_STATE_NAME_BY_CODE.get(state, state).lower().split())
    return not bool(words & state_words)


def distinctive_terms(
    documents,
    *,
    min_count: int,
    max_features: int = 30_000,
    top_n: int = 12,
    prior_mass: float = 1.0,
):
    """Top TF-IDF and within-party concentration terms for every state party."""
    import numpy as np
    import pandas as pd
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer, TfidfVectorizer

    stop_words = sorted(set(ENGLISH_STOP_WORDS) | _EXTRA_STOP_WORDS | _STATE_WORDS)
    options = {
        "lowercase": True,
        "stop_words": stop_words,
        "ngram_range": (1, 2),
        "token_pattern": r"(?u)\b[a-zA-Z][a-zA-Z'-]{2,}\b",
        "min_df": 2,
        "max_df": 0.95,
        "max_features": max_features,
        "preprocessor": _clean_text,
        "sublinear_tf": True,
    }
    tfidf_vectorizer = TfidfVectorizer(**options)
    tfidf = tfidf_vectorizer.fit_transform(documents["text"].fillna(""))
    vocabulary = tfidf_vectorizer.vocabulary_
    counter = CountVectorizer(
        lowercase=options["lowercase"],
        stop_words=options["stop_words"],
        ngram_range=options["ngram_range"],
        token_pattern=options["token_pattern"],
        preprocessor=options["preprocessor"],
        vocabulary=vocabulary,
    )
    counts = counter.transform(documents["text"].fillna(""))
    features = tfidf_vectorizer.get_feature_names_out()
    feature_count = len(features)
    rows = []

    for position, document in enumerate(documents.itertuples(index=False)):
        same_party = np.flatnonzero(
            (documents["party"].to_numpy() == document.party)
            & (np.arange(len(documents)) != position)
        )
        if not len(same_party):
            continue
        own = counts.getrow(position).toarray().ravel()
        peers = np.asarray(counts[same_party].sum(axis=0)).ravel()
        # One pseudo-token spread across the vocabulary. The previous alpha=0.5 *per feature*
        # added 15,000 pseudo-tokens to a 30,000-feature model, swamping short documents and
        # making "+1 means twice as concentrated" incomparable across states.
        alpha = prior_mass / feature_count
        own_rate = (own + alpha) / (own.sum() + prior_mass)
        peer_rate = (peers + alpha) / (peers.sum() + prior_mass)
        concentration = np.log2(own_rate / peer_rate)
        tfidf_row = tfidf.getrow(position).toarray().ravel()

        eligible = np.array(
            [
                own[index] >= min_count and concentration[index] > 0
                and _eligible_feature(term, document.state)
                for index, term in enumerate(features)
            ]
        )
        positions = np.flatnonzero(eligible)
        if not len(positions):
            continue
        tfidf_order = positions[np.argsort(-tfidf_row[positions])]
        concentration_order = positions[np.argsort(-concentration[positions])]
        selected = list(dict.fromkeys(
            [*tfidf_order[:top_n], *concentration_order[:top_n]]
        ))
        tfidf_rank = {feature: rank + 1 for rank, feature in enumerate(tfidf_order)}
        concentration_rank = {
            feature: rank + 1 for rank, feature in enumerate(concentration_order)
        }
        for feature in selected:
            rows.append(
                {
                    "state": document.state,
                    "party": document.party,
                    "stream": document.stream,
                    "term": features[feature],
                    "count": int(own[feature]),
                    "peer_count": int(peers[feature]),
                    "tfidf": round(float(tfidf_row[feature]), 6),
                    "log2_concentration": round(float(concentration[feature]), 4),
                    "tfidf_rank": tfidf_rank[feature],
                    "concentration_rank": concentration_rank[feature],
                }
            )
    return pd.DataFrame(rows)


def _highlights(terms, *, top_n: int = 6):
    """One compact term string per state party and stream."""
    import pandas as pd

    if terms.empty:
        return pd.DataFrame(columns=["state", "party", "stream", "distinctive_terms"])
    # Public highlights come from the top TF-IDF terms; concentration explains how unusually
    # state-specific they are. Letting enormous ratios on low-value terms dominate the score
    # is how OCR and procedural fragments surfaced in the first pass.
    ranked = terms[terms["tfidf_rank"] <= top_n].copy()
    ranked["score"] = ranked["tfidf"] * ranked["log2_concentration"].clip(
        lower=0, upper=8
    )
    ranked = ranked.sort_values(
        ["state", "party", "stream", "score"], ascending=[True, True, True, False]
    )
    return (
        ranked.groupby(["state", "party", "stream"]).head(top_n)
        .groupby(["state", "party", "stream"])
        .apply(
            lambda group: "; ".join(
                f"{row.term} ({row.log2_concentration:+.1f} log2)"
                for row in group.itertuples()
            ),
            include_groups=False,
        )
        .rename("distinctive_terms").reset_index()
    )


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bills", default=root / "data/processed/bills.parquet")
    parser.add_argument(
        "--platforms", default=root / "data/processed/platforms_2018_present.parquet"
    )
    parser.add_argument(
        "--caucuses", default=root / "data/processed/caucus_priorities.parquet"
    )
    parser.add_argument("--out-dir", default=root / "data/processed")
    args = parser.parse_args(argv)

    bills = pd.read_parquet(args.bills, columns=["state", "title", "sponsor_party"])
    platforms = pd.read_parquet(args.platforms)
    caucuses = pd.read_parquet(args.caucuses)
    bill_documents = build_bill_documents(bills)
    stated_documents = build_stated_documents(platforms, caucuses)
    bill_terms = distinctive_terms(bill_documents, min_count=25)
    stated_terms = distinctive_terms(stated_documents, min_count=5)
    terms = pd.concat([bill_terms, stated_terms], ignore_index=True)
    highlights = _highlights(terms)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    terms.to_csv(out / "state_party_terms.csv", index=False)
    highlights.to_csv(out / "state_party_term_highlights.csv", index=False)

    print(f"bill state-party documents:   {len(bill_documents)}")
    print(f"stated state-party documents: {len(stated_documents)}")
    print(f"distinctive term rows:        {len(terms):,}")
    for stream in ("bills", "stated"):
        print(f"\nExamples from {stream}:")
        for row in highlights[highlights["stream"] == stream].head(6).itertuples():
            print(f"  {row.state}-{row.party}: {row.distinctive_terms}")
    print(f"\nwrote {out / 'state_party_terms.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

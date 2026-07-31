"""Election- and voting-related bill focus within each party.

The shared CAP taxonomy puts elections inside the broad Government Operations topic, alongside
budgets, agencies and public administration. That is too coarse to answer whether a state
party focuses specifically on elections.

This module applies a deliberately high-precision title rule to every D/R-attributed bill and
reports each state party's election-bill share against a leave-one-state-out same-party
baseline. Human-assigned Open States subject tags provide an independent validation on the 37
states that publish them; tags are used to score the detector, not to define cross-state shares,
because tag availability is uneven.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

__all__ = ["election_subtype", "election_focus", "validate_title_rule"]

MIN_COMPARABLE_BILLS = 500

_ELECTION_RE = re.compile(
    r"\b(?:"
    r"elections?|electoral|voters?|voting|ballots?|polling places?|"
    r"absentee voting|mail[- ]in voting|campaign finance|campaign contributions?|"
    r"political committees?|redistricting|reapportionment|primary elections?|"
    r"candidate filing|candidate qualification|write[- ]in candidates?|political parties"
    r")\b",
    re.I,
)

_SUBJECT_RE = re.compile(
    r"\b(?:elections?|voters?|voting|ballots?|polling places?|absentee|"
    r"campaign finance|redistricting|reapportionment|political parties)\b",
    re.I,
)

_SUBTYPES = (
    (
        "redistricting",
        re.compile(r"\b(?:redistricting|reapportionment|districting plan)\b", re.I),
    ),
    (
        "campaign_finance",
        re.compile(
            r"\b(?:campaign finance|campaign contributions?|campaign expenditures?|"
            r"political committees?|electioneering communications?)\b",
            re.I,
        ),
    ),
    (
        "election_security",
        re.compile(
            r"\b(?:election fraud|voter fraud|election interference|ballot harvesting|"
            r"election offenses?|election crimes?|election security)\b",
            re.I,
        ),
    ),
    (
        "candidates_and_parties",
        re.compile(
            r"\b(?:candidate filing|candidate qualification|candidate nomination|"
            r"write[- ]in candidates?|political parties|party affiliation|primary elections?)\b",
            re.I,
        ),
    ),
    (
        "voting_and_administration",
        re.compile(
            r"\b(?:elections?|electoral|voters?|voting|ballots?|polling places?|"
            r"absentee voting|mail[- ]in voting)\b",
            re.I,
        ),
    ),
)


def election_subtype(title: str | None) -> str | None:
    """High-precision election subtype for a bill title, or ``None``."""
    title = title or ""
    if not _ELECTION_RE.search(title):
        return None
    for name, pattern in _SUBTYPES:
        if pattern.search(title):
            return name
    return "other_election"


def validate_title_rule(frame) -> dict:
    """Precision/recall against legislature-assigned subject tags where available."""
    subject = frame["subject"].fillna("").astype(str)
    has_subject = subject.str.len() > 0
    title_match = frame["election_subtype"].notna()
    subject_match = subject.str.contains(_SUBJECT_RE)
    tagged_title = title_match & has_subject
    tagged_subject = subject_match & has_subject
    return {
        "n_tagged_bills": int(has_subject.sum()),
        "n_title_election": int(tagged_title.sum()),
        "n_subject_election": int(tagged_subject.sum()),
        "precision": (
            float(subject_match[tagged_title].mean()) if tagged_title.any() else 0.0
        ),
        "recall": (
            float(title_match[tagged_subject].mean()) if tagged_subject.any() else 0.0
        ),
    }


def election_focus(frame):
    """State-party election shares and leave-one-state-out peer comparisons."""
    import pandas as pd

    major = frame[frame["sponsor_party"].isin(("D", "R"))].copy()
    if "classification" in major:
        # States differ enormously in ceremonial resolutions and appointments (0% to 58% of
        # rows). Election share over *all* rows therefore measures chamber procedure as much as
        # election policy. Restrict both numerator and denominator to legislative measures.
        substantive = (
            major["classification"].fillna("").str.startswith("bill")
            | major["classification"].isin(("proposed bill", "constitutional amendment"))
        )
        major = major[substantive].copy()
    major["party"] = major["sponsor_party"]
    major["election_subtype"] = major["title"].map(election_subtype)
    totals = major.groupby(["state", "party"]).size().rename("n_bills")
    election = major[major["election_subtype"].notna()]
    counts = election.groupby(["state", "party"]).size().rename("n_election_bills")
    table = pd.concat([totals, counts], axis=1).fillna({"n_election_bills": 0}).reset_index()
    table["n_election_bills"] = table["n_election_bills"].astype(int)
    table["election_share"] = table["n_election_bills"] / table["n_bills"]

    subtype = (
        election.groupby(["state", "party", "election_subtype"]).size()
        .rename("n").reset_index()
        .sort_values(["state", "party", "n"], ascending=[True, True, False])
    )
    top_subtype = subtype.drop_duplicates(["state", "party"]).set_index(["state", "party"])

    rows = []
    for party in ("D", "R"):
        block = table[table["party"] == party].set_index("state")
        for state, row in block.iterrows():
            peers = block.drop(index=state)
            peer_share = float(peers["election_share"].mean())
            key = (state, party)
            rows.append(
                {
                    **row.to_dict(),
                    "state": state,
                    "party": party,
                    "peer_share": round(peer_share, 6),
                    "overemphasis": round(float(row["election_share"]) - peer_share, 6),
                    "focus_reliable": int(row["n_bills"]) >= MIN_COMPARABLE_BILLS,
                    "top_subtype": (
                        top_subtype.loc[key, "election_subtype"]
                        if key in top_subtype.index else None
                    ),
                }
            )
    return pd.DataFrame(rows), subtype, validate_title_rule(major)


def main(argv: list[str] | None = None) -> int:
    import json

    import pandas as pd

    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bills", default=root / "data/processed/bills.parquet")
    parser.add_argument("--out-dir", default=root / "data/processed")
    args = parser.parse_args(argv)

    bills = pd.read_parquet(
        args.bills,
        columns=["state", "title", "subject", "sponsor_party", "classification"],
    )
    focus, subtypes, validation = election_focus(bills)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    focus.to_csv(out / "election_focus_by_state_party.csv", index=False)
    subtypes.to_csv(out / "election_focus_subtypes.csv", index=False)
    (out / "election_title_validation.json").write_text(
        json.dumps(validation, indent=2), encoding="utf-8"
    )

    print(f"election-related bills: {int(focus['n_election_bills'].sum()):,}")
    print(
        f"title rule vs subject tags: precision {validation['precision']:.1%}, "
        f"recall {validation['recall']:.1%}"
    )
    for party in ("D", "R"):
        print(f"\nHighest election focus among {party} state caucuses:")
        eligible = focus[
            (focus["party"] == party) & focus["focus_reliable"]
        ]
        for row in eligible.nlargest(5, "overemphasis").itertuples():
            print(
                f"  {row.state}: {row.election_share:.1%} vs {row.peer_share:.1%} peers "
                f"({row.top_subtype})"
            )
    print(f"\nwrote {out / 'election_focus_by_state_party.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
* Bill inputs use introduced text alone when present, otherwise title plus available summary.
  Source metadata can describe a later version and must not be appended to introduced text.
  These evidence tiers require separate evaluation; input construction does not certify
  version identity, filing-time eligibility, extraction quality or classifier accuracy.
* A bill is attributed to a party by its primary sponsors. Unresolved historical affiliations
  are excluded rather than guessed at; source availability does not certify party at filing.
* Filing a bill is not passing one. This measures agenda, not achievement.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import re
from pathlib import Path

from ..bills.missouri import parse_withdrawal_notice
from ..bills.montana import source_draft_request_mask
from ..provenance import sha256_file
from .modernbert import add_model_arguments, load_classifier, prediction_rows
from .taxonomy import DEFAULT_TOPICS_PATH, MIN_TOPIC_SIMILARITY, load_topics

__all__ = [
    "build_bill_input", "classify_bills", "count_topics_by_state", "divergence_table",
    "is_procedural_shell_title", "is_source_test_title", "party_emphasis_from_states",
]

#: Bill titles handed to the classifier per pass. Bounds peak memory on a machine whose RAM is
#: mostly spoken for; the classifier itself slices again internally.
_BILL_SLICE = 100_000
MIN_BILL_YEAR = 2018
BILL_INPUT_CONSTRUCTION = "introduced_text_only_else_title_summary_v2"
BILL_FILING_SCOPE = "exclude_mt_lc_source_requests_v1"
_NM_EMERGENCY_CLAUSE_RE = re.compile(
    r"^PUBLIC,?\s+PEACE,\s+HEALTH,\s+SAFETY\s+&\s+WELFARE$",
    re.I,
)
# Exact reviewed titles, not a "testing" keyword rule; see AUDIT_STATUS.md.
_WA_SOURCE_TEST_TITLES = frozenset({
    "bill 4 for system testing",
    "bill 2 for system testing",
    "test bill for production testing",
    "test bill for production system testing",
    "testing bill for session 2025 testing and training",
    "training bill for session '25",
})


def is_source_test_title(title: str, state: str) -> bool:
    """Recognize reviewed publisher system-test records, regardless of sample body text."""
    return state == "WA" and " ".join((title or "").split()).casefold() in _WA_SOURCE_TEST_TITLES


def is_procedural_shell_title(title: str, state: str) -> bool:
    """Known state drafting placeholders that do not describe a bill's subject."""
    title = (title or "").strip()
    return (
        (state == "IL" and title.upper().endswith("-TECH"))
        or (state == "NM" and bool(_NM_EMERGENCY_CLAUSE_RE.fullmatch(title)))
    )


def build_bill_input(
    title: str, summary: str = "", introduced_text: str = "",
) -> tuple[str, list[str]]:
    """Keep introduced text separate from metadata with unestablished version alignment."""
    if not all(isinstance(value, str) for value in (title, summary, introduced_text)):
        raise ValueError("bill input fields must be strings")
    parts = (
        [("introduced_text", introduced_text)] if introduced_text.strip()
        else [("title", title), ("summary", summary)]
    )
    selected = [(field, text) for field, text in parts if text.strip()]
    return "\n\n".join(text for _, text in selected), [field for field, _ in selected]


def classify_bills(bills, classifier, *, batch_size: int = 8,
                   min_similarity: float = MIN_TOPIC_SIMILARITY, min_title_chars: int = 20):
    """Classify candidate evidence without certifying its timing or source identity."""
    import pandas as pd

    rows, usable, texts = [], [], []
    draft_requests = source_draft_request_mask(bills).tolist()
    manifest = getattr(classifier, "manifest", {})
    defaults = {
        "topic": None, "candidate_topic": None, "runner_up": None,
        "score": None, "margin": None, "abstention_reason": None,
        "n_chunks": 0, "scores": "[]", "logits": "[]", "chunk_spans": "[]",
        "output_codes": None, "rejection_score": None,
        "input_sha256": None, "input_domain": "bill", "score_type": "not_scored",
        "model_run": getattr(classifier, "run_id", None),
        "base_model_run": getattr(classifier, "base_model_run", None),
        "model_status": manifest.get("status", "legacy_baseline"),
        "taxonomy_sha256": manifest.get("taxonomy_sha256"),
        "calibration_sha256": getattr(classifier, "calibration_sha256", None),
        "n_input_tokens": None, "n_discarded_tokens": None,
        "record_id": None, "procedural_shell": False, "source_test_record": False,
        "source_draft_request": False, "filing_scope_contract": BILL_FILING_SCOPE,
        "source_withdrawal_notice": False, "withdrawal_notice_observation": None,
        "classification_text": "",
        "input_tier": None, "classification_status": None,
        "bill_input_construction": BILL_INPUT_CONSTRUCTION, "input_fields": "[]",
    }
    for position, row in enumerate(bills.to_dict("records")):
        title = str(row.get("title") or "") if pd.notna(row.get("title")) else ""
        summary = row.get("summary", "")
        introduced = row.get("introduced_text", "")
        summary = str(summary) if pd.notna(summary) else ""
        introduced = str(introduced) if pd.notna(introduced) else ""
        text, input_fields = build_bill_input(title, summary, introduced)
        shell = is_procedural_shell_title(title, str(row.get("state", ""))) and not (
            summary.strip() or introduced.strip()
        )
        source_test = is_source_test_title(title, str(row.get("state", "")))
        withdrawal_notice = (
            parse_withdrawal_notice(introduced) if str(row.get("state", "")) == "MO" else None
        )
        draft_request = draft_requests[position]
        if draft_request:
            reason = "source_draft_request"
        elif source_test:
            reason = "source_test_record"
        elif shell:
            reason = "procedural_shell"
        elif withdrawal_notice is not None:
            reason = "withdrawal_notice_no_policy_text"
        else:
            reason = "insufficient_evidence" if len(text.strip()) < min_title_chars else None
        rows.append({
            **defaults,
            "topic": None, "score": None, "margin": None, "abstention_reason": reason,
            "procedural_shell": shell, "source_test_record": source_test,
            "source_draft_request": draft_request,
            "source_withdrawal_notice": withdrawal_notice is not None,
            "withdrawal_notice_observation": (
                json.dumps(withdrawal_notice) if withdrawal_notice is not None else None
            ),
            "classification_text": text,
            "input_fields": json.dumps(input_fields),
            "record_id": row.get("bill_id"),
            "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "classification_status": (
                "excluded" if shell or source_test or draft_request else "abstained"
            ),
            "input_tier": (
                "introduced_text" if introduced.strip()
                else "official_summary" if summary.strip() else "title_only"
            ),
        })
        if reason is None:
            usable.append(position)
            texts.append(text)
    for start in range(0, len(usable), _BILL_SLICE):
        predictions = prediction_rows(
            classifier, texts[start:start + _BILL_SLICE], domain="bill",
            batch_size=batch_size, min_similarity=min_similarity,
        )
        for position, prediction in zip(
            usable[start:start + _BILL_SLICE], predictions, strict=True
        ):
            rows[position].update(prediction)
            rows[position]["classification_status"] = (
                "classified" if prediction["topic"] is not None else "abstained"
            )
    result = bills.copy()
    predictions = pd.DataFrame(rows, index=result.index, columns=list(defaults))
    for column in predictions:
        result[column] = predictions[column]
    return result


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
                          batch_size: int = 8, min_title_chars: int = 20, progress=print,
                          predictions_dir=None):
    """Classify one state at a time, optionally persisting auditable per-bill partitions."""
    import pandas as pd

    if states is None:
        states = sorted(pd.read_parquet(bills_path, columns=["state"])["state"].unique())

    frames = []
    coverage_rows = []
    seen = attributed = classified_total = 0
    for position, state in enumerate(states, start=1):
        frame = pd.read_parquet(
            bills_path,
            filters=[("state", "==", state)],
        )
        seen += len(frame)
        frame = frame[pd.to_numeric(frame["year"], errors="coerce") >= MIN_BILL_YEAR]
        frame = classify_bills(
            frame, classifier, batch_size=batch_size,
            min_similarity=min_similarity, min_title_chars=min_title_chars,
        )
        if predictions_dir is not None:
            if (
                "bill_id" not in frame or frame["bill_id"].isna().any()
                or not frame["bill_id"].map(
                    lambda value: isinstance(value, str) and bool(value.strip())
                ).all()
                or frame["bill_id"].duplicated().any()
            ):
                raise ValueError("record-level exports require unique source bill IDs")
            destination = Path(predictions_dir) / f"{state}.parquet"
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_suffix(".parquet.part")
            frame.to_parquet(partial, index=False)
            partial.replace(destination)
        frame = frame[frame["sponsor_party"].isin(("D", "R"))].rename(
            columns={"sponsor_party": "party"}).reset_index(drop=True)
        attributed += len(frame)
        if not frame.empty:
            usable = frame[frame["topic"].notna()]
            classified_total += len(usable)
            for party, party_frame in frame.groupby("party"):
                substantive = party_frame[
                    ~(party_frame["procedural_shell"] | party_frame["source_test_record"]
                      | party_frame["source_draft_request"])
                ]
                n_classified = int(substantive["topic"].notna().sum())
                coverage_rows.append(
                    {
                        "state": state,
                        "party": party,
                        "n_attributed": len(party_frame),
                        "n_procedural_excluded": int(
                            party_frame["procedural_shell"].sum()
                        ),
                        "n_source_test_excluded": int(party_frame["source_test_record"].sum()),
                        "n_source_draft_excluded": int(party_frame["source_draft_request"].sum()),
                        "n_substantive_attributed": len(substantive),
                        "n_classified_total": n_classified,
                        "n_abstained": len(substantive) - n_classified,
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
    coverage = pd.DataFrame(coverage_rows, columns=[
        "state", "party", "n_attributed", "n_procedural_excluded", "n_source_test_excluded",
        "n_source_draft_excluded",
        "n_substantive_attributed", "n_classified_total", "n_abstained", "classification_rate",
    ])
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
    add_model_arguments(parser)
    args = parser.parse_args(argv)

    topics = load_topics(args.topics)
    classifier = load_classifier(args, topics)
    print(f"model {classifier.model_name} on device {classifier.device}")

    predictions_dir = Path(args.out_dir) / "bill_predictions" / classifier.run_id
    predictions_dir.mkdir(parents=True, exist_ok=False)
    prediction_manifest = {
        "status": "incomplete", "model_run": classifier.run_id,
        "source_bills_sha256": sha256_file(args.bills),
        "scientific_certification": "not_performed",
        "filing_scope_contract": BILL_FILING_SCOPE,
    }
    manifest_path = predictions_dir / "prediction_manifest.json"
    manifest_path.write_text(json.dumps(prediction_manifest, indent=2) + "\n")
    by_state, totals, coverage = count_topics_by_state(
        args.bills, classifier, predictions_dir=predictions_dir
    )
    prediction_manifest.update(status="complete_extraction_not_source_certification", partitions={
        path.name: sha256_file(path) for path in sorted(predictions_dir.glob("*.parquet"))
    })
    manifest_path.write_text(json.dumps(prediction_manifest, indent=2) + "\n")
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

"""Recover recorded action evidence for the fixed 2023–24 candidate frame, entirely offline.

Build with ``python -m state_politics.analysis.cycle_outcome_evidence --out-dir NEW_DIR``;
check a completed packet with ``--verify-packet DIR``. Existing build destinations are
refused. Source-extraction stages are observations, not certified legal dispositions.
The candidate frame's calendar/date channels are never replaced by session years.
"""

from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..bills import montana
from ..bills import outcomes as extraction_outcomes
from ..bills.openstates_dump import STATE_CODES
from ..provenance import sha256_file, utc_now_iso
from . import outcomes as analysis_outcomes

ROOT = Path(__file__).resolve().parents[3]
STATES = tuple(sorted(state.upper() for state in STATE_CODES))
CHANNELS = (
    "source_coded_event",
    "native_reported_date_candidate",
    "description_stated_event_candidate",
)
CHAMBERS = ("lower", "upper", "legislature", "unknown")
PARTIES = ("D", "R", "other", "unknown")
STAGES = (
    "became_law", "signed", "vetoed", "sent_to_executive", "passed_legislature",
    "passed_one_chamber", "recorded_failure_or_withdrawal", "introduced_or_pending",
    "action_stage_unclassified", "no_action_data",
)
STAGE_LABELS = (
    "Became-law classification", "Executive signature", "Executive veto",
    "Executive receipt", "Passage: both chambers / legislature",
    "Passage: one or unresolved chamber", "Failure / withdrawal classification",
    "Other classified history", "Actions, no classifications", "No retained actions",
)
TABLES = (
    "bills", "bill_actions", "vote_events", "vote_counts", "vote_party_counts",
    "bill_sponsorships",
)
APPROVALS = {
    "analytical_admission": False,
    "model_input_approved": False,
    "scientific_approval": False,
    "party_attribution_approved": False,
    "filing_time_text_certified": False,
    "final_legal_disposition_certified": False,
    "publication_approved": False,
}
STATUS = "complete_offline_recorded_stage_evidence_not_outcome_certification"
_ENACTMENT_CLASSES = {"became-law", "executive-signature", "veto-override-passage"}
_PASSAGE_CLASSES = extraction_outcomes._PASSAGE_CLASSES
_COMMITTEE_CLASSES = extraction_outcomes._COMMITTEE_PASSAGE_CLASSES
_MATRIX_COUNTS = {
    "source_coded_event": "n_filing_or_introduction_in_window",
    "native_reported_date_candidate": "n_native_only_scope_candidates",
    "description_stated_event_candidate": "n_description_only_scope_candidates",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _fingerprint(path: Path) -> dict:
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _check_bound(path: Path, binding: dict) -> dict:
    actual = _fingerprint(path)
    _require(actual["sha256"] == binding["sha256"], f"SHA-256 mismatch: {path}")
    if "rows" in binding:
        rows = (
            pq.ParquetFile(path).metadata.num_rows if path.suffix == ".parquet"
            else len(pd.read_csv(path))
        )
        _require(
            rows == binding["rows"],
            f"manifest row-count mismatch: {path}",
        )
    return actual


def _tokens(value: str | None) -> set[str]:
    if value is None or value == "":
        return set()
    _require(isinstance(value, str), "classifications must be source strings or null")
    parts = value.split("|")
    _require(
        all(part and part.strip() == part for part in parts),
        f"malformed source classification: {value!r}",
    )
    return set(parts)


def _label(value) -> str:
    if value is None or pd.isna(value):
        return "<source-null>"
    return "<source-empty>" if value == "" else str(value)


def _party(value) -> str:
    if value in ("D", "R"):
        return value
    if value in ("other", "nonpartisan"):
        return "other"
    _require(value in (None, "", "unknown") or pd.isna(value), f"unknown party code: {value}")
    return "unknown"


def _date_status(value: str | None) -> str:
    if value is None or value == "":
        return "missing_date"
    _require(isinstance(value, str), "event dates must be source strings or null")
    try:
        day = extraction_outcomes._event_calendar_date(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"malformed source event date: {value!r}") from exc
    return "before_cycle" if day < "2023-01-01" else (
        "after_cycle" if day > "2024-12-31" else "in_cycle"
    )


def _unique(frame: pd.DataFrame, key: str) -> None:
    _require(
        key in frame and frame[key].map(
            lambda value: isinstance(value, str) and bool(value)
        ).all() and not frame[key].duplicated().any(),
        f"expected nonempty unique {key}",
    )


def _integer(value, field: str) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0,
        f"{field} must be a nonnegative source integer",
    )
    return value


def _same(left: pd.Series, right: pd.Series) -> bool:
    return bool((left.eq(right) | (left.isna() & right.isna())).fillna(False).all())


def _selected_batches(path: Path, ids: set[str]):
    source = pq.ParquetFile(path)
    _require("bill_id" in source.schema_arrow.names, f"missing bill_id: {path}")
    field = source.schema_arrow.field("bill_id")
    _require(
        pa.types.is_string(field.type) or pa.types.is_large_string(field.type),
        f"bill_id must retain source strings: {path}",
    )
    keys = pa.array(sorted(ids), type=field.type)
    for batch in source.iter_batches(batch_size=65_536):
        selected = batch.filter(pc.is_in(batch.column("bill_id"), value_set=keys))
        if selected.num_rows:
            yield pa.Table.from_batches([selected])


def _copy_selected(path: Path, out: Path, ids: set[str], consume) -> int:
    count = 0
    with pq.ParquetWriter(out, pq.read_schema(path), compression="zstd") as writer:
        for table in _selected_batches(path, ids):
            consume(table.to_pylist())
            writer.write_table(table)
            count += table.num_rows
    return count


def _validate_cohort(cohort: pd.DataFrame, bills: pd.DataFrame, matrix: pd.DataFrame) -> None:
    _unique(cohort, "bill_id")
    _unique(bills, "bill_id")
    _require(set(cohort.bill_id) == set(bills.bill_id), "candidate/bill identity mismatch")
    _require(
        set(matrix.state) == set(STATES) and not matrix.state.duplicated().any(),
        "primary matrix must contain all 50 states exactly once",
    )
    _require(cohort.state.isin(STATES).all(), "unregistered candidate state")
    for column in set(cohort.columns) & set(bills.columns):
        _require(_same(cohort[column], bills[column]), f"candidate/source mismatch: {column}")
    for field in ("source_event_in_window", "source_test_record", "source_draft_request"):
        _require(
            pd.api.types.is_bool_dtype(cohort[field].dtype) and not cohort[field].isna().any(),
            f"candidate {field} must retain explicit Boolean values",
        )
    for field in ("native_introduction_in_window", "description_event_in_window"):
        _require(
            cohort[field].dropna().map(lambda value: isinstance(value, bool)).all(),
            f"candidate {field} must retain nullable Boolean values",
        )
    for field in APPROVALS.keys() & set(cohort.columns):
        _require(
            cohort[field].map(lambda value: isinstance(value, bool) and not value).all(),
            f"candidate approval is not explicitly false: {field}",
        )
    _require(
        _same(cohort.source_draft_request, montana.source_draft_request_mask(bills)),
        "candidate/source draft-request scope mismatch",
    )
    scopes = []
    for row in cohort.to_dict("records"):
        if row["source_event_in_window"]:
            fields = ("source_introduction_date", "source_filing_date")
            scope = CHANNELS[0]
        elif row["native_introduction_in_window"] is True:
            fields = ("native_introduction_date",)
            scope = CHANNELS[1]
        elif row["description_event_in_window"] is True:
            fields = (
                "description_introduction_candidate_date",
                "description_petition_filing_candidate_date",
            )
            scope = CHANNELS[2]
        else:
            raise ValueError(
                f"candidate lacks an eligible calendar evidence channel: {row['bill_id']}",
            )
        dates = [row.get(field) for field in fields]
        _require(
            any(
                isinstance(value, str) and value and _date_status(value) == "in_cycle"
                for value in dates
            ),
            f"candidate date/channel mismatch: {row['bill_id']}",
        )
        scopes.append(scope)
    _require(cohort.cohort_scope.tolist() == scopes, "candidate date-channel priority mismatch")
    indexed = matrix.set_index("state")
    counts = cohort.groupby("state").size().reindex(STATES, fill_value=0)
    _require(
        counts.eq(indexed.loc[list(STATES), "n_cycle_evidence_candidate_contexts"]).all(),
        "primary state-matrix candidate multiplicity mismatch",
    )
    for scope, column in _MATRIX_COUNTS.items():
        observed = cohort.loc[cohort.cohort_scope.eq(scope)].groupby("state").size()
        _require(
            observed.reindex(STATES, fill_value=0).eq(indexed.loc[list(STATES), column]).all(),
            f"primary state-matrix date-channel mismatch: {scope}",
        )


def _metric() -> dict:
    return {
        "n_actions": 0, "n_classified_actions": 0, "n_null_classification_actions": 0,
        "n_empty_classification_actions": 0, "n_before_cycle_actions": 0,
        "n_in_cycle_actions": 0, "n_after_cycle_actions": 0, "n_missing_date_actions": 0,
        "classes": set(), "passage_chambers": set(), "n_unknown_chamber_passage_actions": 0,
        "n_vote_events": 0, "n_passage_votes": 0, "n_passed_votes": 0, "n_failed_votes": 0,
        "n_official_vote_count_rows": 0, "n_party_vote_count_rows": 0,
        "n_source_person_votes": 0, "n_known_party_person_votes": 0,
        "n_sponsorships": 0, "n_primary_sponsorships": 0, "n_unknown_primary_sponsorships": 0,
        "n_D_sponsorships": 0, "n_R_sponsorships": 0, "n_other_sponsorships": 0,
        "n_unknown_sponsorships": 0,
    }


def _counter_table(counter: Counter, columns: list[str], count_name: str) -> pd.DataFrame:
    rows = [{**dict(zip(columns, key, strict=True)), count_name: value}
            for key, value in counter.items()]
    return pd.DataFrame(rows, columns=[*columns, count_name])


def _collect(source: Path, out: Path, bills: pd.DataFrame) -> tuple[list[dict], dict, dict]:
    ids = set(bills.bill_id)
    bill_rows = bills.set_index("bill_id").to_dict("index")
    metrics = {bill_id: _metric() for bill_id in bills.bill_id}
    action_ids, sponsorship_ids = set(), set()
    vote_keys: dict[str, tuple[str, str]] = {}
    official_keys, party_keys = set(), set()
    action_labels, vote_labels, party_labels, sponsor_labels = (
        Counter(), Counter(), Counter(), Counter()
    )
    rows = {}

    def checked(row):
        bill_id = row["bill_id"]
        _require(
            row["state"] == bill_rows[bill_id]["state"],
            f"source-context state mismatch for {bill_id}",
        )
        return metrics[bill_id]

    def unique_row(row, key, seen):
        value = row[key]
        _require(
            isinstance(value, str) and value and value not in seen,
            f"missing/duplicate source {key}: {value}",
        )
        seen.add(value)

    def actions(batch):
        for row in batch:
            metric = checked(row)
            unique_row(row, "action_id", action_ids)
            _integer(row["order"], "action order")
            _require(row["chamber"] in CHAMBERS, "unrecognized extracted action chamber")
            classes = _tokens(row["classification"])
            metric["n_actions"] += 1
            metric["n_classified_actions"] += bool(classes)
            metric["n_null_classification_actions"] += row["classification"] is None
            metric["n_empty_classification_actions"] += row["classification"] == ""
            metric[f"n_{_date_status(row['date'])}_actions"] += 1
            metric["classes"].update(classes)
            if classes & _PASSAGE_CLASSES:
                metric["passage_chambers"].add(row["chamber"])
                metric["n_unknown_chamber_passage_actions"] += row["chamber"] == "unknown"
            action_labels[(row["state"], row["chamber"], row["classification"])] += 1

    rows["bill_actions"] = _copy_selected(
        source / "bill_actions.parquet", out / "bill_actions.parquet", ids, actions,
    )

    def votes(batch):
        for row in batch:
            metric = checked(row)
            vote_id = row["vote_id"]
            _require(
                isinstance(vote_id, str) and vote_id and vote_id not in vote_keys,
                f"missing/duplicate source vote_id: {vote_id}",
            )
            _integer(row["order"], "vote order")
            _require(row["chamber"] in CHAMBERS, "unrecognized extracted vote chamber")
            _date_status(row["start_date"])
            vote_keys[vote_id] = (row["bill_id"], row["state"])
            metric["n_vote_events"] += 1
            metric["n_passage_votes"] += "passage" in _tokens(row["motion_classification"])
            metric["n_passed_votes"] += row["result"] == "pass"
            metric["n_failed_votes"] += row["result"] == "fail"
            vote_labels[
                (row["state"], row["chamber"], row["motion_classification"], row["result"])
            ] += 1

    rows["vote_events"] = _copy_selected(
        source / "vote_events.parquet", out / "vote_events.parquet", ids, votes,
    )

    def counts(batch, *, party: bool):
        for row in batch:
            metric = checked(row)
            _require(
                vote_keys.get(row["vote_event_id"]) == (row["bill_id"], row["state"]),
                "vote-count/event exact identity mismatch",
            )
            key = (row["vote_event_id"], row["option"])
            if party:
                _require(
                    row["sponsor_party"] == bill_rows[row["bill_id"]]["sponsor_party"],
                    "vote-count source sponsor-party mismatch",
                )
                key += (row["sponsor_party"], row["voter_party"])
                _require(key not in party_keys, "duplicate source vote party count")
                party_keys.add(key)
                value = _integer(row["n_votes"], "n_votes")
                metric["n_party_vote_count_rows"] += 1
                metric["n_source_person_votes"] += value
                bucket = _party(row["voter_party"])
                metric["n_known_party_person_votes"] += value if bucket != "unknown" else 0
                party_labels[
                    (row["state"], row["sponsor_party"], row["voter_party"], row["option"])
                ] += value
            else:
                _require(key not in official_keys, "duplicate source official vote count")
                official_keys.add(key)
                _integer(row["value"], "official vote value")
                metric["n_official_vote_count_rows"] += 1

    rows["vote_counts"] = _copy_selected(
        source / "vote_counts.parquet", out / "vote_counts.parquet", ids,
        lambda batch: counts(batch, party=False),
    )
    rows["vote_party_counts"] = _copy_selected(
        source / "vote_party_counts.parquet", out / "vote_party_counts.parquet", ids,
        lambda batch: counts(batch, party=True),
    )

    def sponsors(batch):
        for row in batch:
            metric = checked(row)
            unique_row(row, "sponsorship_id", sponsorship_ids)
            _require(isinstance(row["primary"], bool), "source primary must be Boolean")
            _date_status(row["party_attribution_date"])
            metric["n_sponsorships"] += 1
            metric["n_primary_sponsorships"] += row["primary"]
            bucket = _party(row["party"])
            metric[f"n_{bucket}_sponsorships"] += 1
            metric["n_unknown_primary_sponsorships"] += row["primary"] and bucket == "unknown"
            sponsor_labels[
                (
                    row["state"], row["primary"], row["classification"], row["party"],
                    row["party_resolution"], row["party_attribution_date_basis"],
                    row.get("party_resolution_reason"),
                )
            ] += 1

    rows["bill_sponsorships"] = _copy_selected(
        source / "bill_sponsorships.parquet", out / "bill_sponsorships.parquet", ids, sponsors,
    )
    corrections = Counter()
    derived = []
    for bill_id in bills.bill_id:
        metric = metrics[bill_id]
        source_bill = bill_rows[bill_id]
        classes = metric.pop("classes")
        chambers = metric.pop("passage_chambers")
        metric["recorded_stage"] = extraction_outcomes.recorded_outcome(
            classes, chambers, n_actions=metric["n_actions"],
        )
        metric["recorded_enactment_classification"] = bool(classes & _ENACTMENT_CLASSES)
        metric["observed_action_classifications"] = "|".join(sorted(classes))
        metric["observed_passage_chambers"] = "|".join(sorted(chambers))
        metric["observed_committee_passage"] = bool(classes & _COMMITTEE_CLASSES)
        for field in ("n_actions", "n_vote_events", "n_passage_votes",
                      "n_passed_votes", "n_failed_votes"):
            _integer(source_bill[field], f"source bill {field}")
            _require(
                metric[field] == source_bill[field],
                f"retained raw/source bill count mismatch: {bill_id}: {field}",
            )
        for observed, original in (
            ("n_sponsorships", "n_sponsors"),
            ("n_primary_sponsorships", "n_primary_sponsors"),
            ("n_unknown_primary_sponsorships", "n_unresolved_primary_sponsors"),
            ("observed_action_classifications", "action_classifications"),
            ("observed_passage_chambers", "passage_chambers"),
            ("observed_committee_passage", "committee_passage"),
            ("recorded_enactment_classification", "recorded_enacted"),
        ):
            _require(
                metric[observed] == source_bill[original],
                f"retained raw/source bill evidence mismatch: {bill_id}: {original}",
            )
        stage = metric["recorded_stage"]
        original = source_bill["recorded_outcome"]
        legacy_repair = original == "no_action_data" and stage == "action_stage_unclassified"
        _require(original == stage or legacy_repair, f"unexpected source stage mismatch: {bill_id}")
        metric["legacy_missing_action_label_corrected"] = legacy_repair
        corrections["n_legacy_missing_action_labels_corrected"] += legacy_repair
        metric["has_actions"] = metric["n_actions"] > 0
        metric["has_classified_actions"] = metric["n_classified_actions"] > 0
        metric["has_votes"] = metric["n_vote_events"] > 0
        metric["certified_final_legal_disposition"] = None
        derived.append(metric)
    label_tables = {
        "action_source_labels.csv": _counter_table(
            action_labels, ["state", "chamber", "classification"], "n_action_rows",
        ),
        "vote_source_labels.csv": _counter_table(
            vote_labels, ["state", "chamber", "motion_classification", "result"],
            "n_vote_events",
        ),
        "voter_party_source_labels.csv": _counter_table(
            party_labels, ["state", "sponsor_party", "voter_party", "option"],
            "n_source_person_votes",
        ),
        "sponsorship_party_resolution.csv": _counter_table(
            sponsor_labels,
            ["state", "primary", "classification", "party", "party_resolution",
             "party_attribution_date_basis", "party_resolution_reason"],
            "n_sponsorships",
        ),
    }
    for name, frame in label_tables.items():
        frame.to_csv(out / name, index=False)
    return derived, rows, dict(corrections)


def _summary(frame: pd.DataFrame) -> dict:
    total = len(frame)
    actions = int(frame.has_actions.sum())
    classified = int(frame.has_classified_actions.sum())
    return {
        "n_contexts": total, "n_with_actions": actions,
        "n_with_classified_actions": classified,
        "n_only_unclassified_actions": actions - classified,
        "n_no_action_data": total - actions,
        "n_law_eligible": int(frame.law_eligible.sum()),
        "n_with_votes": int(frame.has_votes.sum()),
        "n_action_rows": int(frame.n_actions.sum()),
        "n_vote_events": int(frame.n_vote_events.sum()),
        "n_source_party_D": int(frame.sponsor_party_bucket.eq("D").sum()),
        "n_source_party_R": int(frame.sponsor_party_bucket.eq("R").sum()),
        "n_source_party_other": int(frame.sponsor_party_bucket.eq("other").sum()),
        "n_source_party_unknown": int(frame.sponsor_party_bucket.eq("unknown").sum()),
        "action_availability": actions / total if total else None,
        "classified_action_availability": classified / total if total else None,
        "vote_availability": int(frame.has_votes.sum()) / total if total else None,
        "source_party_known_availability": (
            int(frame.sponsor_party_bucket.ne("unknown").sum()) / total if total else None
        ),
        "certified_final_legal_disposition_availability": None,
    }


def _write_summaries(frame: pd.DataFrame, out: Path) -> dict:
    dimensions = {
        "state_coverage.csv": {"state": STATES},
        "chamber_coverage.csv": {"originating_chamber": CHAMBERS},
        "measure_type_coverage.csv": {
            "classification_label": sorted(set(frame.classification_label) | {"<source-null>"}),
        },
        "state_date_channel_coverage.csv": {"state": STATES, "cohort_scope": CHANNELS},
        "state_chamber_type_coverage.csv": {
            "state": STATES, "originating_chamber": CHAMBERS,
            "classification_label": sorted(set(frame.classification_label) | {"<source-null>"}),
        },
    }
    for filename, dims in dimensions.items():
        keys = list(dims)
        groups = {
            key if isinstance(key, tuple) else (key,): group
            for key, group in frame.groupby(keys, dropna=False, sort=False)
        }
        rows = [
            {**dict(zip(keys, values, strict=True)),
             **_summary(groups.get(values, frame.iloc[:0]))}
            for values in itertools.product(*dims.values())
        ]
        pd.DataFrame(rows).to_csv(out / filename, index=False)
    stage_tables = {}
    for name, dimension, values in (
        ("pooled_recorded_stages.csv", None, (None,)),
        ("state_recorded_stages.csv", "state", STATES),
        ("chamber_recorded_stages.csv", "originating_chamber", CHAMBERS),
    ):
        rows = []
        for value, population in itertools.product(values, ("all_candidates", "law_eligible")):
            subset = frame if dimension is None else frame.loc[frame[dimension].eq(value)]
            if population == "law_eligible":
                subset = subset.loc[subset.law_eligible]
            counts = subset.recorded_stage.value_counts()
            for stage, label in zip(STAGES, STAGE_LABELS, strict=True):
                row = {
                    "population": population, "recorded_stage": stage, "stage_label": label,
                    "n_contexts": int(counts.get(stage, 0)), "denominator_contexts": len(subset),
                    "share": int(counts.get(stage, 0)) / len(subset) if len(subset) else None,
                    "final_legal_disposition_certified": False,
                }
                if dimension:
                    row[dimension] = value
                rows.append(row)
        table = pd.DataFrame(rows)
        table.to_csv(out / name, index=False)
        stage_tables[name] = table
    party_rows = []
    for state, population, party in itertools.product(
        STATES, ("all_candidates", "law_eligible"), PARTIES,
    ):
        subset = frame.loc[frame.state.eq(state)]
        if population == "law_eligible":
            subset = subset.loc[subset.law_eligible]
        count = int(subset.sponsor_party_bucket.eq(party).sum())
        party_rows.append({
            "state": state, "population": population, "source_party_bucket": party,
            "n_contexts": count, "denominator_contexts": len(subset),
            "share": count / len(subset) if len(subset) else None,
            "party_comparison_performed": False,
        })
    pd.DataFrame(party_rows).to_csv(out / "sponsor_party_availability.csv", index=False)
    frame.groupby(
        ["state", "source_sponsor_party", "source_sponsor_attribution_basis"],
        dropna=False,
    ).size().rename("n_contexts").reset_index().to_csv(
        out / "source_sponsor_party_labels.csv", index=False,
    )
    return stage_tables


def plot_evidence(packet: Path) -> list[str]:
    """Plot the complete, supplied chart CSVs; never fill unavailable rates with zero."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from ..plotting import charts, theme

    matplotlib.rcParams["svg.hashsalt"] = "cycle-outcome-evidence-2023-2024-v1"
    colors = (
        theme.GREEN, theme.tint(theme.GREEN, .35), theme.ACCENT, theme.GOLD, theme.BLUE,
        theme.tint(theme.BLUE, .4), theme.shade(theme.ACCENT, .15), theme.GRID,
        theme.MUTED, theme.TEXT,
    )
    note = (
        "Source: retained Open States / Plural Policy extraction; fixed 2023–24 calendar "
        "candidate contexts, not a session-year cohort. All retained action dates are used "
        "(not a December 2024 cutoff). Source classifications indicate recorded stages, "
        "not certified final legal dispositions. Highest-stage precedence is the existing "
        "extraction helper, not chronology. Missing or unclassified actions are not failures. "
        "Ordinary law-eligible source bills only; source test records and Montana LC requests "
        "excluded. No topic inference or party comparison; no analytical approval."
    )
    paths = []

    def save(fig, stem):
        source_note = theme.source_note(fig, note)
        theme.layout_with_note(fig, source_note)
        for suffix in ("png", "svg"):
            filename = f"{stem}.{suffix}"
            metadata = {"Date": None} if suffix == "svg" else {}
            fig.savefig(packet / filename, dpi=180, bbox_inches="tight", metadata=metadata)
            paths.append(filename)
        plt.close(fig)

    pooled = pd.read_csv(packet / "pooled_recorded_stages.csv")
    selected = pooled.loc[pooled.population.eq("law_eligible")].set_index("recorded_stage")
    selected = selected.loc[list(STAGES)]
    _require(
        len(selected) == len(STAGES) and selected.denominator_contexts.nunique() == 1,
        "incomplete pooled chart data",
    )
    _require(selected.denominator_contexts.iloc[0] > 0, "no law-eligible contexts to plot")
    fig, ax = charts.new_figure((12, 7))
    bars = ax.barh(selected.stage_label, selected["share"] * 100, color=colors)
    for bar, row in zip(bars, selected.to_dict("records"), strict=True):
        ax.text(
            bar.get_width() + .35, bar.get_y() + bar.get_height() / 2,
            f"{row['n_contexts']:,}  ({row['share']:.1%})", va="center", fontsize=9,
        )
    ax.invert_yaxis()
    ax.set_xlim(0, max(10, selected["share"].max() * 100 + 15))
    charts.style_axes(
        ax, "What stages are actually recorded for 2023–24 candidates?",
        "Share of law-eligible candidate contexts (%)", "",
        subtitle=(
            f"{int(selected.denominator_contexts.iloc[0]):,} contexts; "
            "pooled, not party-attributed"
        ),
    )
    ax.grid(axis="x", visible=True)
    ax.grid(axis="y", visible=False)
    save(fig, "pooled_recorded_stages")

    states = pd.read_csv(packet / "state_recorded_stages.csv")
    states = states.loc[states.population.eq("law_eligible")]
    _require(
        len(states) == len(STATES) * len(STAGES)
        and not states.duplicated(["state", "recorded_stage"]).any()
        and set(states.state) == set(STATES),
        "incomplete all-state chart data",
    )
    counts = states.pivot(index="state", columns="recorded_stage", values="n_contexts")
    totals = counts.sum(axis=1).reindex(STATES)
    shares = counts.reindex(STATES).div(totals.where(totals.gt(0)), axis=0) * 100
    fig, ax = charts.new_figure((13, 15))
    left = pd.Series(0., index=STATES)
    positions = pd.Series(range(len(STATES)), index=STATES)
    for stage, label, color in zip(STAGES, STAGE_LABELS, colors, strict=True):
        present = shares[stage].notna()
        ax.barh(
            positions.loc[present], shares.loc[present, stage], left=left.loc[present],
            color=color, label=label, height=.75,
        )
        left.loc[present] += shares.loc[present, stage]
    for state, total in totals.items():
        ax.text(
            101, positions.loc[state], f"n={total:,}" if total else "No eligible contexts",
            va="center", fontsize=8, color=theme.MUTED,
        )
    ax.set_yticks(positions, labels=STATES)
    ax.set_ylim(-1, len(STATES))
    ax.set_xlim(0, 126)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.invert_yaxis()
    charts.style_axes(
        ax, "Recorded stages vary across the 50 states",
        "Share of law-eligible candidate contexts (%)", "",
        subtitle="All states retained; blank rows have no eligible contexts, not zero success",
    )
    ax.grid(axis="x", visible=True)
    ax.grid(axis="y", visible=False)
    handles, labels = ax.get_legend_handles_labels()
    legend = fig.legend(
        handles, labels, loc="lower center", bbox_to_anchor=(.5, .055), ncol=2, fontsize=9,
    )
    legend.set_in_layout(False)
    source_note = theme.source_note(fig, note)
    theme.layout_with_note(fig, source_note, pad=.15)
    for suffix in ("png", "svg"):
        filename = f"state_recorded_stages.{suffix}"
        fig.savefig(
            packet / filename, dpi=180, bbox_inches="tight",
            metadata={"Date": None} if suffix == "svg" else {},
        )
        paths.append(filename)
    plt.close(fig)
    return paths


def build_evidence(
    source_dir: Path, cohort_dir: Path, out_dir: Path, *, plots: bool = True,
) -> dict:
    """Build a fail-closed, byte-bound evidence packet in a previously unused directory."""
    source_dir, cohort_dir, out_dir = (
        Path(path).resolve() for path in (source_dir, cohort_dir, out_dir)
    )
    if out_dir.exists():
        raise FileExistsError(f"Use a new evidence output directory: {out_dir}")
    started_at = utc_now_iso()
    extraction_path = source_dir / "bill_extraction_manifest.json"
    cohort_manifest_path = cohort_dir / "manifest.json"
    extraction = json.loads(extraction_path.read_text())
    primary = json.loads(cohort_manifest_path.read_text())
    _require(
        extraction["status"] == "complete_extraction_not_source_certification",
        "incomplete/unsupported extraction manifest",
    )
    _require(
        primary["status"]
        == "complete_cycle_metadata_evidence_not_version_aligned_or_model_admitted",
        "incomplete/unsupported primary candidate manifest",
    )
    _require(
        primary.get("analytical_admission") is False
        and primary.get("model_input_approved") is False,
        "primary candidate approvals must remain false",
    )
    inputs = {
        "primary_manifest": _fingerprint(cohort_manifest_path),
        "extraction_manifest": _check_bound(
            extraction_path, primary["inputs"]["extraction_manifest"],
        ),
    }
    for table in TABLES:
        name = f"{table}.parquet"
        inputs[table] = _check_bound(source_dir / name, extraction["artifacts"][name])
        inputs[table]["rows"] = pq.ParquetFile(source_dir / name).metadata.num_rows
    _require(
        inputs["bills"]["sha256"] == primary["inputs"]["bills"]["sha256"],
        "primary/extraction bills hash disagreement",
    )
    for name in ("bill_evidence.parquet", "state_matrix.csv"):
        inputs[name] = _check_bound(cohort_dir / name, primary["artifacts"][name])
    for key, file in (
        ("producer", Path(__file__)),
        ("stage_helper", Path(extraction_outcomes.__file__)),
        ("law_eligibility_helper", Path(analysis_outcomes.__file__)),
        ("draft_scope_helper", Path(montana.__file__)),
        ("state_registry", ROOT / "src/state_politics/bills/openstates_dump.py"),
    ):
        inputs[key] = _fingerprint(file)
    if plots:
        for name in ("theme", "charts"):
            inputs[f"plot_{name}"] = _fingerprint(
                ROOT / f"src/state_politics/plotting/{name}.py",
            )
    cohort_table = pq.read_table(cohort_dir / "bill_evidence.parquet")
    cohort = cohort_table.to_pandas()
    _unique(cohort, "bill_id")
    _require(len(cohort) > 0, "primary candidate frame is empty")
    selected = list(_selected_batches(source_dir / "bills.parquet", set(cohort.bill_id)))
    _require(bool(selected), "no exact candidate/source bill matches")
    source_bills = pa.concat_tables(selected)
    bills = source_bills.to_pandas()
    _unique(bills, "bill_id")
    _require(set(bills.bill_id) == set(cohort.bill_id), "missing exact candidate/source bill match")
    positions = pd.Series(range(len(bills)), index=bills.bill_id).loc[cohort.bill_id].tolist()
    source_bills = source_bills.take(pa.array(positions))
    bills = source_bills.to_pandas()
    matrix = pd.read_csv(cohort_dir / "state_matrix.csv", keep_default_na=False)
    _validate_cohort(cohort, bills, matrix)
    _require(bills.originating_chamber.isin(CHAMBERS).all(), "unrecognized source bill chamber")
    out_dir.mkdir(parents=True, exist_ok=False)
    _json(out_dir / "manifest.json", {
        "status": "building_not_complete", "started_at": started_at, "inputs": inputs,
        **APPROVALS,
    })
    pq.write_table(source_bills, out_dir / "source_bills.parquet", compression="zstd")
    # Preserve the supplied matrix literally, including its original unknowns and labels.
    (out_dir / "primary_state_matrix.csv").write_bytes(
        (cohort_dir / "state_matrix.csv").read_bytes(),
    )
    records, raw_rows, corrections = _collect(source_dir, out_dir, bills)
    derived = pd.DataFrame(records)
    draft = montana.source_draft_request_mask(bills)
    derived["law_eligible"] = (
        bills.classification.map(analysis_outcomes.is_law_eligible).astype(bool)
        & ~draft & ~cohort.source_test_record
    )
    derived["measure_scope"] = [
        "source_test_record" if test else "source_draft_request" if request else
        "ordinary_law_eligible_bill" if eligible else
        "missing_source_classification" if not isinstance(kind, str) or not kind else
        "other_source_measure_type"
        for test, request, eligible, kind in zip(
            cohort.source_test_record, draft, derived.law_eligible, bills.classification,
            strict=True,
        )
    ]
    derived["sponsor_party_bucket"] = bills.sponsor_party.map(_party)
    derived["classification_label"] = bills.classification.map(_label)
    derived["source_sponsor_party"] = bills.sponsor_party
    derived["source_sponsor_attribution_basis"] = bills.sponsor_attribution_basis
    # Append, rather than reserialize, every original candidate/source Arrow column.
    context = cohort_table
    for name in source_bills.column_names:
        context = context.append_column(f"source_bill__{name}", source_bills[name])
    for name in derived:
        context = context.append_column(name, pa.array(derived[name], from_pandas=True))
    for name, value in APPROVALS.items():
        if name not in context.column_names:
            context = context.append_column(name, pa.array([value] * len(cohort)))
    _require(
        context.select(cohort_table.column_names).equals(cohort_table),
        "original candidate fields were altered",
    )
    pq.write_table(context, out_dir / "bill_context_evidence.parquet", compression="zstd")
    frame = pd.concat([cohort, derived], axis=1)
    _write_summaries(frame, out_dir)
    graph_files = plot_evidence(out_dir) if plots else []
    law = frame.loc[frame.law_eligible]
    report = {
        "schema_version": 1, "status": STATUS,
        "cohort": {
            "n_source_contexts": len(cohort), "n_unique_bill_ids": cohort.bill_id.nunique(),
            "date_channels": {key: int(cohort.cohort_scope.eq(key).sum()) for key in CHANNELS},
            "calendar_start": "2023-01-01", "calendar_end": "2024-12-31",
            "session_only_comparison_used": False, "calendar_cohort_redefined": False,
        },
        "all_candidates": _summary(frame), "law_eligible": _summary(law),
        "recorded_stages_all_candidates": {
            key: int(frame.recorded_stage.eq(key).sum()) for key in STAGES
        },
        "recorded_stages_law_eligible": {
            key: int(law.recorded_stage.eq(key).sum()) for key in STAGES
        },
        "measure_scope": {
            str(key): int(value) for key, value in frame.measure_scope.value_counts().items()
        },
        "raw_selected_rows": {"source_bills": len(bills), **raw_rows},
        "party": {
            "source_bill_labels": {
                _label(key): int(value)
                for key, value in bills.sponsor_party.value_counts(dropna=False).items()
            },
            "source_party_basis": (
                "unchanged extraction; no current-party/date/session substitution"
            ),
            "nonpartisan_bucket": "other; literal nonpartisan label retained separately",
            "comparison_performed": False, "comparison_available_for_this_packet": False,
            "reason": (
                "No approved party comparison; incomplete source attribution is not reliable."
            ),
            "n_source_person_votes": int(frame.n_source_person_votes.sum()),
            "n_known_party_person_votes": int(frame.n_known_party_person_votes.sum()),
            "n_sponsorships": int(frame.n_sponsorships.sum()),
            "n_known_party_sponsorships": int(
                frame.n_sponsorships.sum() - frame.n_unknown_sponsorships.sum()
            ),
            "sponsorship_resolution_reason_retained": (
                "party_resolution_reason"
                in pq.read_schema(source_dir / "bill_sponsorships.parquet").names
            ),
        },
        "action_dates": {
            status: int(frame[f"n_{status}_actions"].sum())
            for status in ("before_cycle", "in_cycle", "after_cycle", "missing_date")
        },
        **corrections,
        "raw_field_preservation": {
            "candidate_columns": cohort_table.column_names,
            "source_bill_columns": source_bills.column_names,
            "source_bill_prefix": "source_bill__",
            "candidate_values_and_arrow_schema_preserved": True,
            "all_selected_related_table_columns_preserved": True,
            "selected_row_identity_and_multiplicity": (
                "exact bill_id plus validated state; no deduplication"
            ),
        },
        "graph_files": graph_files,
        "source_limitations": [
            "Calendar candidates are evidence channels, not certified formal filing denominators.",
            "All retained action histories are used; no December 2024 action cutoff is asserted.",
            "Highest stage follows the existing helper's precedence, not last-event chronology.",
            "Signature/became-law/override classifications are not certified final "
            "legal dispositions.",
            "Other classified history does not establish introduction, pending status, or success.",
            "Passage at an unknown chamber is preserved and explicitly labelled unresolved.",
            "Missing and unclassified action histories are not failures or zero success.",
            "Source sponsor/voter affiliations are not repaired or extrapolated; undated "
            "memberships cannot establish historical party. Absent retained resolution "
            "reasons are not invented.",
            "Vote counts and party-count rows are different source observations, "
            "not interchangeable.",
            "No policy-topic labels, model inference/training, collection, OCR, "
            "or human gold used.",
        ],
        "source_snapshot": {
            key: extraction.get(key)
            for key in ("source_sha256", "source_bytes", "completed_at", "analysis_cutoff")
        },
        "new_http_requests": 0, "classifier_calls": 0, **APPROVALS,
    }
    _json(out_dir / "report.json", report)
    for binding in inputs.values():
        _require(
            _fingerprint(Path(binding["path"])) == {
                key: value for key, value in binding.items() if key != "rows"
            },
            f"input changed during evidence recovery: {binding['path']}",
        )
    artifacts = {}
    for file in sorted(out_dir.iterdir()):
        if file.name == "manifest.json":
            continue
        artifact = {"sha256": sha256_file(file), "bytes": file.stat().st_size}
        if file.suffix == ".parquet":
            artifact["rows"] = pq.ParquetFile(file).metadata.num_rows
        elif file.suffix == ".csv":
            artifact["rows"] = len(pd.read_csv(file))
        artifacts[file.name] = artifact
    _json(out_dir / "manifest.json", {
        "schema_version": 1, "status": STATUS, "started_at": started_at,
        "completed_at": utc_now_iso(), "inputs": inputs, "inputs_unchanged": True,
        "artifacts": artifacts, "new_http_requests": 0, "classifier_calls": 0,
        "reproduce": {
            "module": "state_politics.analysis.cycle_outcome_evidence",
            "arguments": ["--source-dir", str(source_dir), "--cohort-dir", str(cohort_dir),
                          "--out-dir", "<new-unused-output-directory>",
                          *([] if plots else ["--no-plots"])],
        },
        **APPROVALS,
    })
    verify_packet(out_dir)
    return report


def verify_packet(packet: Path) -> dict:
    """Recheck byte bindings, population identity, coverage partitions, and approval fences."""
    packet = Path(packet).resolve()
    manifest = json.loads((packet / "manifest.json").read_text())
    _require(manifest["status"] == STATUS, "packet is not complete")
    for field in APPROVALS:
        _require(manifest.get(field) is False, f"packet approval is not false: {field}")
    for binding in manifest["inputs"].values():
        _check_bound(Path(binding["path"]), binding)
    for name, binding in manifest["artifacts"].items():
        _check_bound(packet / name, binding)
    original = pq.read_table(manifest["inputs"]["bill_evidence.parquet"]["path"])
    context = pq.read_table(packet / "bill_context_evidence.parquet")
    _require(context.select(original.column_names).equals(original), "candidate fields changed")
    source = pq.read_table(packet / "source_bills.parquet")
    _require(
        all(context[f"source_bill__{name}"].equals(source[name]) for name in source.column_names),
        "raw per-bill fields changed",
    )
    frame = context.to_pandas()
    _unique(frame, "bill_id")
    for field in APPROVALS:
        _require(frame[field].eq(False).all(), f"context approval is not false: {field}")
    _require(frame.certified_final_legal_disposition.isna().all(), "invented legal disposition")
    state = pd.read_csv(packet / "state_coverage.csv")
    _require(
        len(state) == 50 and set(state.state) == set(STATES)
        and not state.state.duplicated().any(),
        "incomplete state coverage",
    )
    _require(int(state.n_contexts.sum()) == len(frame), "state multiplicity mismatch")
    for name in (
        "pooled_recorded_stages.csv", "state_recorded_stages.csv", "chamber_recorded_stages.csv",
    ):
        table = pd.read_csv(packet / name)
        keys = ["population", *[key for key in ("state", "originating_chamber") if key in table]]
        for _, group in table.groupby(keys):
            _require(
                set(group.recorded_stage) == set(STAGES) and len(group) == len(STAGES)
                and group.denominator_contexts.nunique() == 1
                and group.n_contexts.sum() == group.denominator_contexts.iloc[0],
                f"incomplete recorded-stage partition: {name}",
            )
            if group.denominator_contexts.iloc[0] == 0:
                _require(group["share"].isna().all(), "empty denominator became zero rates")
    report = json.loads((packet / "report.json").read_text())
    _require(
        int(frame.n_actions.sum()) == report["raw_selected_rows"]["bill_actions"],
        "action multiplicity mismatch",
    )
    return {
        "verified": True, "packet": str(packet), "n_contexts": len(frame),
        "n_action_rows": int(frame.n_actions.sum()), "n_states": len(state),
        "manifest_sha256": sha256_file(packet / "manifest.json"),
        "inputs_unchanged": True, "raw_candidate_fields_preserved": True,
        "raw_source_bill_fields_preserved": True, "approval_flags_false": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data/processed")
    parser.add_argument(
        "--cohort-dir", type=Path,
        default=ROOT / "data/processed/study-abstract-evidence-2023-2024-v3",
    )
    parser.add_argument(
        "--out-dir", type=Path,
        default=ROOT / "data/processed/cycle-outcome-evidence-20261022-v1",
    )
    parser.add_argument(
        "--no-plots", action="store_true", help="Write evidence tables without figures.",
    )
    parser.add_argument(
        "--verify-packet", type=Path, help="Verify an existing packet; write nothing.",
    )
    args = parser.parse_args(argv)
    result = (
        verify_packet(args.verify_packet) if args.verify_packet else build_evidence(
            args.source_dir, args.cohort_dir, args.out_dir, plots=not args.no_plots,
        )
    )
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

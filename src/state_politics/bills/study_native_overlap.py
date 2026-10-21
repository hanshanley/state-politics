"""Join accepted native input indexes to the shared cycle matrix, without collection."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

import pandas as pd
import yaml

from ..provenance import utc_now_iso
from .outcomes import _event_calendar_date
from .study_sources import _unique
from .study_window import END, START, _snapshot

_STATUS = "complete_supplied_native_overlap_not_native_census_or_analytical_admission"
_IN_WINDOW = "source_introduction_in_window"


def native_introduction_observation(value) -> tuple[str | None, str]:
    """Keep a separate native-reported date channel, never a source-date fallback."""
    if pd.isna(value) or value == "":
        return None, "missing_native_introduction_observation"
    if not isinstance(value, str):
        return None, "invalid_native_introduction_observation"
    try:
        date = _event_calendar_date(value).isoformat()
    except ValueError:
        return None, "invalid_native_introduction_observation"
    return date, (
        "native_introduction_in_window"
        if START <= date <= END
        else "native_introduction_before_window"
        if date < START
        else "native_introduction_after_window"
    )


def _field(frame: pd.DataFrame, selector: str, *, missing_ok: bool = False) -> pd.Series:
    column, *nested = selector.split(".")
    if missing_ok and column not in frame:
        return pd.Series(None, index=frame.index, dtype=object)
    values = frame[column]
    if nested:
        values = values.map(
            lambda value: None if missing_ok and pd.isna(value) else json.loads(value)
        )
        for key in nested:
            if missing_ok:
                values = values.map(
                    lambda value, key=key: value.get(key) if isinstance(value, dict) else None
                )
            else:
                values = values.map(lambda value, key=key: value[key])
    return values


def _read(path: Path, columns: set[str]) -> pd.DataFrame:
    return pd.read_parquet(path, columns=sorted(columns))


def normalize_packet(
    spec: dict,
    raw: pd.DataFrame,
    raw_views: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep context and reader alternatives separate; do not choose a ground-truth reader.

    ``allow_missing_identity: true`` retains missing identifier/session rows as source-only.
    ``source_only: {selector: <field>, values: [<value>, ...]}`` also quarantines explicitly
    selected rows, even when their typed identity or declared bill ID would otherwise match.
    Set its ``match: json_array_any`` to match flags in a JSON string array instead.
    For the views profile, ``view_reader_allowlist: [<reader>, ...]`` retains only those
    readers and records per-context ``n_excluded_views``; full source tables remain bound.
    ``native_introduction_when: [{selector: <field>, values: [<value>, ...]}, ...]``
    requires every condition before reading a date field, only for matching rows.
    The ``observations`` profile supplies context/date metadata with no policy-text views
    and requires no record ID, text hash or character count beyond the context selectors.
    ``context_granularity: source_reference`` permits multiple physical references to a
    canonical bill; the default ``measure`` still permits at most one measure context.
    """
    contexts = pd.DataFrame(
        {
            "state": spec["state"],
            "context_id": _field(raw, spec["context_id"]).astype("string"),
            "native_identifier": _field(raw, spec["identifier"]),
            "session_identifier": (
                _field(raw, spec["session_identifier"])
                if "session_identifier" in spec
                else spec["canonical_session"]
            ),
            "declared_bill_id": _field(raw, spec["bill_id"]) if "bill_id" in spec else None,
        }
    )
    if not isinstance(spec["state"], str) or not spec["state"]:
        raise ValueError("missing native context state")
    if contexts["context_id"].isna().any():
        raise ValueError("missing native context identity")
    if contexts["context_id"].eq("").any():
        raise ValueError("empty native context identity")
    granularity = spec.get("context_granularity", "measure")
    if granularity not in {"measure", "source_reference"}:
        raise ValueError("unsupported native context granularity")
    contexts["context_granularity"] = granularity
    identity = contexts[["native_identifier", "session_identifier"]]
    missing_identity = (identity.isna() | identity.eq("")).any(axis=1)
    if type(spec.get("allow_missing_identity", False)) is not bool:
        raise ValueError("allow_missing_identity requires an explicit boolean")
    if not spec.get("allow_missing_identity", False):
        if identity.isna().any().any():
            raise ValueError("missing native context identity")
        if identity.eq("").any().any():
            raise ValueError("empty native context identity")
    source_only = missing_identity.copy()
    if "source_only" in spec:
        selector = spec["source_only"]
        if not isinstance(selector["values"], list):
            raise ValueError("source-only selector values must be a list")
        selected = _field(raw, selector["selector"])
        match = selector.get("match", "value")
        if match == "json_array_any":
            try:
                selected = selected.map(json.loads)
            except (TypeError, ValueError) as exc:
                raise ValueError("source-only selector requires a JSON string array") from exc
            if not selected.map(
                lambda flags: (
                    isinstance(flags, list) and all(isinstance(flag, str) for flag in flags)
                )
            ).all():
                raise ValueError("source-only selector requires a JSON string array")
            source_only |= selected.map(
                lambda flags: any(flag in selector["values"] for flag in flags)
            )
        elif match == "value":
            source_only |= selected.isin(selector["values"])
        else:
            raise ValueError("unsupported source-only selector match")
    contexts["session_binding"] = (
        "retained_context_field"
        if "session_identifier" in spec
        else "declared_canonical_cohort_not_date_evidence"
    )
    contexts["native_session_identifier"] = (
        contexts["session_identifier"] if "session_identifier" in spec else None
    )
    if "session_map" in spec:
        sessions = contexts["session_identifier"].map(spec["session_map"])
        if sessions.loc[~source_only].isna().any():
            raise ValueError("native session lacks an explicit canonical crosswalk")
        contexts["session_identifier"] = sessions.where(
            sessions.notna(), contexts["session_identifier"]
        )
        contexts.loc[sessions.notna(), "session_binding"] = "explicit_native_session_crosswalk"
    contexts["canonical_join_mode"] = "declared_bill_id" if "bill_id" in spec else "typed_key"
    if "source_only_session_fields" in spec:
        codes = pd.concat(
            [_field(raw, field).astype("string") for field in spec["source_only_session_fields"]],
            axis=1,
        ).agg(":".join, axis=1)
        sessions = codes.map(spec["source_only_session_map"])
        mapped = contexts["declared_bill_id"].isna() & sessions.notna()
        contexts.loc[mapped, "session_identifier"] = sessions.loc[mapped]
        contexts.loc[mapped, "session_binding"] = "explicit_native_session_code_crosswalk"
        contexts.loc[mapped, "canonical_join_mode"] = "typed_key"
    contexts.loc[source_only, "canonical_join_mode"] = "source_only"
    contexts["packet_status"] = (
        _field(raw, spec["status"]) if "status" in spec else "retained_input_unadjudicated"
    )
    for field in spec.get("preserve_context_fields", []):
        if field in contexts:
            raise ValueError("source context fields cannot override normalized identity or flags")
        contexts[field] = _field(raw, field)
    contexts["native_introduction_raw"] = None
    contexts["native_introduction_date"] = None
    contexts["native_window_disposition"] = "not_supplied_by_registered_packet"
    if "native_introduction_field" in spec:
        if "native_introduction_guard" in spec:
            guard = _field(raw, spec["native_introduction_guard"]).loc[~source_only]
            if not guard.empty and (
                guard.isna().any() or not pd.api.types.is_bool_dtype(guard.dtype) or not guard.all()
            ):
                raise ValueError("native introduction date requires explicit introduced records")
        date_rows = ~source_only
        if "native_introduction_when" in spec:
            conditions = spec["native_introduction_when"]
            if not isinstance(conditions, list) or not conditions:
                raise ValueError("native introduction conditions require a nonempty list")
            for condition in conditions:
                if not isinstance(condition["values"], list):
                    raise ValueError("native introduction condition values must be a list")
                selected = _field(raw.loc[date_rows], condition["selector"], missing_ok=True)
                date_rows.loc[date_rows] = selected.notna() & selected.isin(condition["values"])
            observed = pd.Series(None, index=raw.index[date_rows], dtype=object)
            if date_rows.any():
                try:
                    observed = _field(raw.loc[date_rows], spec["native_introduction_field"])
                except KeyError as exc:
                    raise ValueError(
                        "matching native introduction condition lacks a date field"
                    ) from exc
                if observed.isna().any() or observed.eq("").any():
                    raise ValueError("matching native introduction condition lacks a date field")
        else:
            observed = _field(raw, spec["native_introduction_field"])
        contexts.loc[observed.index, "native_introduction_raw"] = observed
        dates = observed.loc[date_rows].map(native_introduction_observation)
        contexts.loc[date_rows, "native_introduction_date"] = dates.map(lambda value: value[0])
        contexts.loc[date_rows, "native_window_disposition"] = dates.map(lambda value: value[1])
    if spec["profile"] == "reader_rows":
        if contexts.groupby("context_id", dropna=False).nunique(dropna=False).gt(1).any().any():
            raise ValueError("reader variants disagree on native context")
        contexts = contexts.drop_duplicates("context_id").reset_index(drop=True)
    _unique(contexts, "context_id")
    if spec["profile"] in {"single", "reader_rows"}:
        character_column = spec.get("view_character_count", "n_input_characters")
        views = (
            raw[["record_id", "input_sha256", character_column]]
            .rename(columns={"record_id": "view_id", character_column: "n_input_characters"})
            .copy()
        )
        views["context_id"] = _field(raw, spec["context_id"]).astype("string")
        views["reader"] = (
            raw["reader"]
            if spec["profile"] == "reader_rows"
            else spec.get("source_kind", "native_caml")
        )
        if "view_available" in spec:
            available = raw[spec["view_available"]]
            if available.isna().any() or not pd.api.types.is_bool_dtype(available.dtype):
                raise ValueError("explicit boolean input availability required")
            views = views.loc[available].copy()
    elif spec["profile"] == "views" and raw_views is not None:
        views = raw_views[
            ["view_id", "context_id", "reader", "input_sha256", "n_input_characters"]
        ].copy()
    elif spec["profile"] == "observations" and raw_views is None:
        views = pd.DataFrame(
            {
                column: pd.Series(dtype="int64" if column == "n_input_characters" else "string")
                for column in (
                    "view_id",
                    "context_id",
                    "reader",
                    "input_sha256",
                    "n_input_characters",
                )
            }
        )
    else:
        raise ValueError("unsupported native input profile")
    if views.empty:
        views = views.astype(
            {column: "int64" if column == "n_input_characters" else "string" for column in views}
        )
    _unique(views, "view_id")
    if (
        views[["context_id", "reader", "input_sha256", "n_input_characters"]].isna().any().any()
        or not pd.api.types.is_integer_dtype(views["n_input_characters"].dtype)
        or views["n_input_characters"].le(0).any()
        or not views["input_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
        or not views["context_id"].isin(contexts["context_id"]).all()
        or views.duplicated(["context_id", "reader"]).any()
    ):
        raise ValueError("invalid or orphaned retained source view")
    if "view_reader_allowlist" in spec:
        readers = spec["view_reader_allowlist"]
        if (
            spec["profile"] != "views"
            or not isinstance(readers, list)
            or not all(isinstance(reader, str) and reader for reader in readers)
        ):
            raise ValueError("explicit reader allowlist requires the views profile")
        excluded = ~views["reader"].isin(readers)
        counts = views.loc[excluded].groupby("context_id").size()
        contexts["n_excluded_views"] = contexts["context_id"].map(counts).fillna(0).astype("int64")
        views = views.loc[~excluded].copy()
    counts = views.groupby("context_id").size()
    contexts["n_retained_views"] = contexts["context_id"].map(counts).fillna(0).astype("int64")
    contexts["packet_root"] = spec["root"]
    contexts["native_identity_certified"] = False
    contexts["analytical_admission"] = False
    views["state"] = spec["state"]
    views["packet_root"] = spec["root"]
    return contexts, views


def _typed_key(values: pd.Series, *, state: str) -> pd.Series:
    if not values.map(lambda value: isinstance(value, str)).all():
        raise ValueError("unsupported typed identifier; no guessed aliases")
    allowed = values.str.fullmatch(r"[A-Za-z]+ *[0-9]+(?:-[0-9]+)?")
    if state == "MI":
        allowed |= values.str.fullmatch(r"(?i)(HJR|SJR) *[A-Z]")
    if values.isna().any() or not allowed.all():
        raise ValueError("unsupported typed identifier; no guessed aliases")
    return values.str.replace(" ", "", regex=False).str.upper()


def join_contexts(contexts: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    """Require exact bill identity or unique explicit session/typed-identity agreement."""
    pieces = []
    for state, native in contexts.groupby("state", sort=True):
        native = native.copy()
        source_only = native["canonical_join_mode"].eq("source_only")
        canonical = ledger.loc[
            ledger["state"].eq(state)
            & ledger["session_identifier"].isin(native.loc[~source_only, "session_identifier"])
        ].copy()
        canonical["_typed"] = (
            _typed_key(canonical["identifier"], state=state) if not canonical.empty else None
        )
        typed = ~source_only | (
            native["native_identifier"].notna() & native["native_identifier"].ne("")
        )
        native["_typed"] = None
        if typed.any():
            native.loc[typed, "_typed"] = _typed_key(
                native.loc[typed, "native_identifier"], state=state
            )
        declared = native.loc[~source_only & native["declared_bill_id"].notna()].copy()
        without = native.loc[source_only | native["declared_bill_id"].isna()].copy()
        if not declared.empty:
            matched = declared.merge(
                canonical,
                left_on="declared_bill_id",
                right_on="bill_id",
                suffixes=("_native", ""),
                how="left",
                validate="many_to_one",
                indicator=True,
            )
            if (
                not matched["_merge"].eq("both").all()
                or not matched["_typed_native"].eq(matched["_typed"]).fillna(False).all()
                or not matched["session_identifier_native"]
                .eq(matched["session_identifier"])
                .fillna(False)
                .all()
            ):
                raise ValueError("declared canonical/native identity mismatch")
            matched["canonical_join_basis"] = "declared_bill_id_exact_session_typed_identity"
            pieces.append(matched.drop(columns=["_merge", "_typed_native", "_typed"]))
        for mode, subset in without.groupby("canonical_join_mode"):
            if mode in {"declared_bill_id", "source_only"}:
                matched = subset.copy()
                for column in canonical:
                    if (
                        mode == "source_only"
                        and column in matched
                        and column not in {"state", "session_identifier", "_typed"}
                    ):
                        matched = matched.rename(columns={column: f"{column}_native"})
                    if column not in matched:
                        matched[column] = None
                matched["canonical_join_basis"] = (
                    "source_only_unresolved_identity"
                    if mode == "source_only"
                    else "source_only_no_declared_bill_id"
                )
            else:
                matched = subset.merge(
                    canonical.drop(columns="state"),
                    on=["session_identifier", "_typed"],
                    how="left",
                    suffixes=("_native", ""),
                    validate="many_to_one",
                )
                matched["canonical_join_basis"] = (
                    matched["bill_id"]
                    .notna()
                    .map(
                        {
                            True: "unique_declared_session_typed_identity",
                            False: "native_only_unmatched",
                        }
                    )
                )
            pieces.append(matched.drop(columns="_typed"))
    result = pd.concat(pieces, ignore_index=True)
    _check_measure_uniqueness(result)
    return _annotate_date_evidence(result)


def _check_measure_uniqueness(contexts: pd.DataFrame) -> None:
    granularity = contexts.get(
        "context_granularity", pd.Series("measure", index=contexts.index)
    ).fillna("measure")
    if not granularity.isin(["measure", "source_reference"]).all():
        raise ValueError("unsupported native context granularity")
    if (
        contexts.loc[contexts["bill_id"].notna() & granularity.eq("measure"), "bill_id"]
        .duplicated()
        .any()
    ):
        raise ValueError("multiple native contexts would double-count a canonical bill")


def _annotate_date_evidence(result: pd.DataFrame) -> pd.DataFrame:
    result["source_in_window"] = result["window_disposition"].eq(_IN_WINDOW).fillna(False)
    result["native_in_window"] = result["native_window_disposition"].eq(
        "native_introduction_in_window"
    )
    result["date_evidence_status"] = result["native_window_disposition"]
    native_date = result["native_introduction_date"].notna()
    source_date = result["source_introduction_date"].notna() & result[
        "source_introduction_date"
    ].ne("")
    joined = result["bill_id"].notna()
    result.loc[native_date & ~joined, "date_evidence_status"] = "native_date_identity_unmatched"
    result.loc[native_date & joined & ~source_date, "date_evidence_status"] = (
        "native_date_only_source_unresolved"
    )
    comparable = native_date & source_date & joined
    agrees = result["native_introduction_date"].eq(result["source_introduction_date"]).fillna(False)
    result.loc[comparable & agrees, "date_evidence_status"] = "native_source_dates_agree"
    result.loc[comparable & ~agrees, "date_evidence_status"] = "native_source_dates_differ"
    return result


def aggregate_bill_contexts(contexts: pd.DataFrame) -> pd.DataFrame:
    """Aggregate joined contexts, never physical references, to one row per canonical bill.

    Canonical identity/source-date fields must agree. A unique normalized native date
    resolves; different native dates produce ``conflicting_native_introduction_observations``
    with no selected date and ``native_in_window=False``. ``native_introduction_raw`` is
    a JSON array of all raw observations; ``source_contexts_json`` binds each observation
    and retained-view count to its unchanged packet root/context ID.
    """
    _check_measure_uniqueness(contexts)
    joined = contexts.loc[contexts["bill_id"].notna()].copy()
    canonical_columns = [
        "bill_id",
        "state",
        "identifier",
        "session_identifier",
        "source_introduction_date",
        "window_disposition",
    ]
    if joined.groupby("bill_id")[canonical_columns[1:]].nunique(dropna=False).gt(1).any().any():
        raise ValueError("canonical bill identity/source-date fields disagree across contexts")
    reference_columns = [
        column
        for column in (
            "packet_root",
            "context_id",
            "context_granularity",
            "packet_status",
            "native_identifier",
            "native_session_identifier",
            "canonical_join_basis",
            "native_introduction_raw",
            "native_introduction_date",
            "native_window_disposition",
            "date_evidence_status",
            "n_retained_views",
            "negative_flags_json",
        )
        if column in joined
    ]
    rows = []
    for _, group in joined.groupby("bill_id", sort=False):
        row = group.iloc[0][canonical_columns].to_dict()
        dates = group["native_introduction_date"].dropna().unique().tolist()
        if len(dates) == 1:
            native_date, disposition = native_introduction_observation(dates[0])
        elif len(dates) > 1:
            native_date, disposition = None, "conflicting_native_introduction_observations"
        else:
            native_date, disposition = None, "not_supplied_by_registered_packet"
            for status in (
                "invalid_native_introduction_observation",
                "missing_native_introduction_observation",
            ):
                if group["native_window_disposition"].eq(status).any():
                    disposition = status
                    break
        references = group[reference_columns].astype(object)
        references = references.where(references.notna(), None)
        observations = group["native_introduction_raw"].astype(object)
        row.update(
            n_native_contexts=len(group),
            n_retained_views=int(group["n_retained_views"].sum()),
            native_introduction_raw=json.dumps(
                observations.where(observations.notna(), None).tolist(),
                ensure_ascii=False,
                default=str,
            ),
            native_introduction_date=native_date,
            native_window_disposition=disposition,
            source_contexts_json=json.dumps(
                references.to_dict("records"), ensure_ascii=False, default=str
            ),
            native_identity_certified=False,
            analytical_admission=False,
        )
        rows.append(row)
    result = pd.DataFrame(
        rows,
        columns=[
            *canonical_columns,
            "n_native_contexts",
            "n_retained_views",
            "native_introduction_raw",
            "native_introduction_date",
            "native_window_disposition",
            "source_contexts_json",
            "native_identity_certified",
            "analytical_admission",
        ],
    )
    result = result.astype({"n_native_contexts": "int64", "n_retained_views": "int64"})
    return _annotate_date_evidence(result)


def build_overlap(matrix_dir: Path, registry: Path, out_dir: Path) -> dict:
    """Bind optional packet ``binding_evidence`` before materializing derived outputs.

    Each entry requires ``path``, exact ``sha256``, dotted JSON ``selector`` and typed
    JSON ``expected`` value. Proofs bind identity scope only; they never supply dates.
    ``expected_views`` counts retained views after any explicit reader allowlist.
    """
    if out_dir.exists():
        raise FileExistsError(out_dir)
    matrix_manifest_path = matrix_dir / "manifest.json"
    initial = {"registry": registry, "matrix_manifest": matrix_manifest_path}
    before = {key: _snapshot(path) for key, path in initial.items()}
    config = yaml.safe_load(registry.read_text(encoding="utf-8"))
    specs = config["packets"]
    states = list(dict.fromkeys(s["state"] for s in specs))
    packet_ids = [s.get("packet_id", s["state"]) for s in specs]
    if (
        config["schema_version"] != 1
        or not specs
        or len(set(packet_ids)) != len(specs)
        or len({s["root"] for s in specs}) != len(specs)
    ):
        raise ValueError("unique registered packet IDs are required")
    matrix_manifest = json.loads(matrix_manifest_path.read_text(encoding="utf-8"))
    if matrix_manifest["status"] != (
        "complete_all_state_triage_not_native_coverage_or_analytical_admission"
    ):
        raise ValueError("completed shared national matrix required")
    paths = {
        "registry": registry,
        "matrix_manifest": matrix_manifest_path,
        "matrix": matrix_dir / "state_matrix.csv",
        "ledger": Path(matrix_manifest["inputs"]["ledger"]["path"]),
        "producer": Path(__file__),
        "study_sources": Path(__file__).with_name("study_sources.py"),
        "study_window": Path(__file__).with_name("study_window.py"),
        "outcomes": Path(__file__).with_name("outcomes.py"),
        "provenance": Path(__file__).parent.parent / "provenance.py",
    }
    for spec in specs:
        packet_id = spec.get("packet_id", spec["state"])
        for role, name in (
            ("manifest", "manifest.json"),
            ("contexts", spec["contexts"]),
            ("views", spec.get("views")),
        ):
            if name:
                paths[f"{packet_id}_{role}"] = Path(spec["root"]) / name
        for index, binding in enumerate(spec.get("binding_evidence", [])):
            paths[f"{packet_id}_binding_evidence_{index}"] = Path(binding["path"])
    before.update({key: _snapshot(path) for key, path in paths.items() if key not in before})
    for spec in specs:
        packet_id = spec.get("packet_id", spec["state"])
        for index, binding in enumerate(spec.get("binding_evidence", [])):
            key = f"{packet_id}_binding_evidence_{index}"
            proof = paths[key].read_bytes()
            if (
                before[key]["sha256"] != binding["sha256"]
                or sha256(proof).hexdigest() != binding["sha256"]
                or _snapshot(paths[key]) != before[key]
            ):
                raise ValueError(f"{packet_id}: binding evidence checksum mismatch")
            try:
                if not isinstance(binding["selector"], str) or not binding["selector"]:
                    raise ValueError("nonempty binding selector required")
                actual = _field(
                    pd.DataFrame({"proof": [proof.decode("utf-8")]}),
                    f"proof.{binding['selector']}",
                ).tolist()[0]
                if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(
                    binding["expected"], sort_keys=True, allow_nan=False
                ):
                    raise ValueError("binding value mismatch")
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{packet_id}: binding evidence JSON value mismatch") from exc
    if (
        before["matrix"]["sha256"] != matrix_manifest["artifacts"]["state_matrix.csv"]["sha256"]
        or before["ledger"]["sha256"] != matrix_manifest["inputs"]["ledger"]["sha256"]
    ):
        raise ValueError("shared matrix input checksum mismatch")
    for spec in specs:
        state = spec["state"]
        packet_id = spec.get("packet_id", state)
        if before[f"{packet_id}_manifest"]["sha256"] != spec["manifest_sha256"]:
            raise ValueError(f"{state}: unaccepted packet manifest")
        manifest = json.loads(paths[f"{packet_id}_manifest"].read_text(encoding="utf-8"))
        for role in ("contexts", "views"):
            key = f"{packet_id}_{role}"
            if key in paths:
                binding = manifest["files"][paths[key].name]
                expected = binding if isinstance(binding, str) else binding["sha256"]
                if before[key]["sha256"] != expected:
                    raise ValueError(f"{state}: native table checksum mismatch")
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = out_dir / "manifest.json"
    manifest = {
        "schema_version": 1,
        "status": "incomplete",
        "started_at": utc_now_iso(),
        "inputs": before,
        "new_requests": 0,
        "analytical_admission": False,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    all_contexts, all_views = [], []
    reader_allowlist_counts = {}
    for spec in specs:
        packet_id = spec.get("packet_id", spec["state"])
        selectors = [
            spec[k]
            for k in ("context_id", "identifier", "bill_id", "session_identifier", "status")
            if k in spec
        ]
        columns = {selector.split(".")[0] for selector in selectors}
        columns |= {field.split(".")[0] for field in spec.get("source_only_session_fields", [])}
        columns |= {field.split(".")[0] for field in spec.get("preserve_context_fields", [])}
        columns |= {
            condition["selector"].split(".")[0]
            for condition in spec.get("native_introduction_when", [])
        }
        if "source_only" in spec:
            columns.add(spec["source_only"]["selector"].split(".")[0])
        columns |= {
            spec[key].split(".")[0]
            for key in ("native_introduction_field", "native_introduction_guard")
            if key in spec
        }
        if spec["profile"] in {"single", "reader_rows"}:
            columns |= {
                "record_id",
                "input_sha256",
                spec.get("view_character_count", "n_input_characters"),
            }
        if "view_available" in spec:
            columns.add(spec["view_available"])
        if spec["profile"] == "reader_rows":
            columns.add("reader")
        raw = _read(paths[f"{packet_id}_contexts"], columns)
        raw_views = None
        if "views" in spec:
            raw_views = _read(
                paths[f"{packet_id}_views"],
                {
                    "view_id",
                    "context_id",
                    "reader",
                    "input_sha256",
                    "n_input_characters",
                },
            )
        contexts, views = normalize_packet(spec, raw, raw_views)
        if len(contexts) != spec["expected_contexts"] or len(views) != spec["expected_views"]:
            raise ValueError(f"{spec['state']}: accepted packet population mismatch")
        if "view_reader_allowlist" in spec:
            excluded = int(contexts["n_excluded_views"].sum())
            reader_allowlist_counts[packet_id] = {
                "state": spec["state"],
                "allowed_readers": spec["view_reader_allowlist"],
                "n_source_views": len(views) + excluded,
                "n_retained_views": len(views),
                "n_excluded_views": excluded,
            }
        all_contexts.append(contexts)
        all_views.append(views)
    ledger = pd.read_csv(paths["ledger"], dtype=str, keep_default_na=False)
    matched = join_contexts(pd.concat(all_contexts, ignore_index=True), ledger)
    bills = aggregate_bill_contexts(matched)
    views = pd.concat(all_views, ignore_index=True)
    matrix = pd.read_csv(paths["matrix"], keep_default_na=False)
    if not set(states).issubset(set(matrix["state"])):
        raise ValueError("registered state absent from national matrix")
    missing = ledger.loc[
        ledger["state"].isin(states)
        & ledger["window_disposition"].eq(_IN_WINDOW)
        & ~ledger["bill_id"].isin(bills.loc[bills["n_retained_views"].gt(0), "bill_id"])
    ].copy()
    for column in (
        "n_supplied_native_contexts",
        "n_supplied_native_views",
        "n_source_in_window_with_supplied_native_text",
        "n_source_in_window_without_supplied_native_text",
        "n_native_in_window_with_join_and_text",
        "n_native_in_window_text_with_unresolved_source_date",
        "n_native_in_window_text_with_outside_source_date",
        "n_native_source_date_disagreements_cycle_relevant",
    ):
        matrix[column] = pd.Series(pd.NA, index=matrix.index, dtype="Int64")
    matrix["native_packet_integration"] = "not_registered_not_zero_recovery"
    for state in states:
        selected_contexts = matched.loc[matched["state"].eq(state)]
        selected = bills.loc[bills["state"].eq(state)]
        mask = matrix["state"].eq(state)
        matrix.loc[mask, "native_packet_integration"] = "supplied_packet_index_bound"
        matrix.loc[mask, "n_supplied_native_contexts"] = len(selected_contexts)
        matrix.loc[mask, "n_supplied_native_views"] = int(views["state"].eq(state).sum())
        matrix.loc[mask, "n_source_in_window_with_supplied_native_text"] = int(
            (selected["source_in_window"] & selected["n_retained_views"].gt(0)).sum()
        )
        matrix.loc[mask, "n_source_in_window_without_supplied_native_text"] = int(
            missing["state"].eq(state).sum()
        )
        if (
            selected_contexts["native_window_disposition"]
            .ne("not_supplied_by_registered_packet")
            .any()
        ):
            native = selected.loc[
                selected["native_in_window"]
                & selected["bill_id"].notna()
                & selected["n_retained_views"].gt(0)
            ]
            outside = native["window_disposition"].isin(
                [
                    "source_introduction_before_window",
                    "source_introduction_after_window",
                ]
            )
            matrix.loc[mask, "n_native_in_window_with_join_and_text"] = len(native)
            matrix.loc[mask, "n_native_in_window_text_with_unresolved_source_date"] = int(
                (~native["source_in_window"] & ~outside).sum()
            )
            matrix.loc[mask, "n_native_in_window_text_with_outside_source_date"] = int(
                outside.sum()
            )
            matrix.loc[mask, "n_native_source_date_disagreements_cycle_relevant"] = int(
                (
                    selected["date_evidence_status"].eq("native_source_dates_differ")
                    & (selected["native_in_window"] | selected["source_in_window"])
                ).sum()
            )
    matched.to_parquet(out_dir / "native_context_overlap.parquet", index=False)
    bills.to_parquet(out_dir / "native_bill_overlap.parquet", index=False)
    views.to_parquet(out_dir / "native_view_index.parquet", index=False)
    missing.to_parquet(out_dir / "missing_supplied_native_text.parquet", index=False)
    matched.loc[
        matched["native_window_disposition"].ne("not_supplied_by_registered_packet")
    ].to_parquet(out_dir / "native_introduction_observations.parquet", index=False)
    date_queue = matched.loc[
        (matched["native_in_window"] | matched["source_in_window"])
        & matched["date_evidence_status"].isin(
            [
                "native_date_only_source_unresolved",
                "native_source_dates_differ",
                "native_date_identity_unmatched",
                "invalid_native_introduction_observation",
                "missing_native_introduction_observation",
            ]
        )
    ]
    date_queue.to_parquet(out_dir / "date_resolution_queue.parquet", index=False)
    matrix.to_csv(out_dir / "state_matrix.csv", index=False)
    result = {
        "status": _STATUS,
        "registered_states": states,
        "n_native_contexts": len(matched),
        "n_canonical_bills_with_native_contexts": len(bills),
        "n_reader_or_source_views_not_bills": len(views),
        "n_source_only_contexts": int(matched["bill_id"].isna().sum()),
        "n_source_in_window_without_supplied_native_text": len(missing),
        "cycle_date_resolution_counts": date_queue["date_evidence_status"].value_counts().to_dict(),
        "limitations": [
            "Only registered accepted packets are indexed, not all local archives.",
            "View text is referenced by full-table binding and input hash, not re-extracted here.",
            "Reader alternatives are not extra bills or adjudicated truth.",
            "Configured canonical sessions select cohorts, never supply missing dates.",
            "Native-reported dates stay separate; conflicts never overwrite source dates.",
            "Retained text does not certify native identity, original stage or filing eligibility.",
            "Unregistered packet counts are unknown, not zero; native census remains uncomputed.",
        ],
        "new_requests": 0,
        "analytical_admission": False,
    }
    if reader_allowlist_counts:
        result["reader_allowlist_counts"] = reader_allowlist_counts
        result["n_reader_views_excluded_by_allowlist"] = sum(
            counts["n_excluded_views"] for counts in reader_allowlist_counts.values()
        )
    (out_dir / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if {key: _snapshot(path) for key, path in paths.items()} != before:
        raise ValueError("native-overlap inputs changed; output remains incomplete")
    manifest.update(
        status=_STATUS,
        completed_at=utc_now_iso(),
        inputs_unchanged=True,
        artifacts={
            path.name: {"sha256": snapshot["sha256"], "bytes": snapshot["size"]}
            for path in sorted(out_dir.iterdir())
            if path.name != "manifest.json"
            for snapshot in [_snapshot(path)]
        },
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-dir", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build_overlap(args.matrix_dir, args.registry, args.out_dir), indent=2))


if __name__ == "__main__":
    main()

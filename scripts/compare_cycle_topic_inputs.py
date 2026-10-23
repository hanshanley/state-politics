#!/usr/bin/env python3
"""Compare completed, local topic galleries on exactly the same available bill inputs."""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import shutil
import stat
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_politics.analysis.cycle_topics import FLAGS, SCHEMA, binding, require  # noqa: E402
from state_politics.bills.openstates_dump import STATE_CODES  # noqa: E402
from state_politics.plotting import theme  # noqa: E402

STATUS = "complete_provisional_topic_graphs_not_scientific_validation"
ARCHIVE = "research-data/complete_inference_inputs_and_predictions.zip"
TIERS = ("metadata", "retained_text")
STATES = sorted(state.upper() for state in STATE_CODES)
IDENTITY = ("bill_id", "state", "identifier", "session_identifier")
DISPOSITIONS = ("classified", "abstained", "unavailable")
CATEGORIES = (
    "same_assigned_topic",
    "different_assigned_topic",
    "both_abstaining",
    "exactly_one_abstaining",
    "unavailable",
)
NOTICE = (
    "Uncertified input-tier agreement, not accuracy or independent policy validation. "
    "Both abstaining is not accurate classification. Missing inputs are unavailable, not "
    "disagreements or topic zeros. Retained source versions and filing-time alignment remain "
    "uncertified. No party, policy agreement, ideology or human-gold claims."
)
POLICY = {
    "scope": "descriptive_model_assignments_not_validated_filing_attention_or_party_positions",
    "source_alternative_policy": "unanimous_nonnull_view_decisions_else_abstain",
    "source_selection": "all_complete_supplied_candidate_views_no_later_version_selection",
}
VARIABLE_PLAN_KEYS = {
    "preview",
    "preview_manifest",
    "checkpoint",
    "topics_path",
    "source_files",
    "inputs",
    "tiers",
    "n_views_by_tier",
}


def safe_name(name):
    require(
        isinstance(name, str)
        and bool(name)
        and all(ord(character) >= 32 for character in name)
        and "\\" not in name
        and not PurePosixPath(name).is_absolute()
        and all(part not in {"", ".", ".."} for part in name.split("/")),
        f"unsafe relative path: {name!r}",
    )
    return name


def json_bytes(value):
    def reject(value):
        raise ValueError(f"non-finite JSON value: {value}")

    def unique(pairs):
        result = {}
        for key, item in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = item
        return result

    return json.loads(value, parse_constant=reject, object_pairs_hook=unique)


def unapproved(value, *, required=True):
    if required:
        require(all(value.get(flag) is False for flag in FLAGS), "approval flag drift")
    for key, item in value.items():
        if key in FLAGS or key.endswith(("_approved", "_approval", "_admission", "_certified")):
            require(item is False, f"approval flag drift: {key}")


def valid_binding(value):
    require(
        isinstance(value, dict)
        and set(value) == {"sha256", "bytes"}
        and isinstance(value["sha256"], str)
        and len(value["sha256"]) == 64
        and all(c in "0123456789abcdef" for c in value["sha256"])
        and type(value["bytes"]) is int
        and value["bytes"] >= 0,
        "malformed artifact binding",
    )
    return value


def fingerprint(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def assignment_shape(frame, topics):
    required = {
        *IDENTITY,
        *FLAGS,
        "topic",
        "inference_status",
        "abstention_reason",
        "n_source_views",
        "view_abstention_reasons",
        "model_run",
    }
    require(required <= set(frame), "missing original assignment fields")
    require(not frame["bill_id"].duplicated().any(), "duplicate bill_id")
    for key in IDENTITY:
        require(
            frame[key].map(lambda x: isinstance(x, str) and bool(x)).all(),
            f"missing stable identifier: {key}",
        )
    require(set(frame["state"]) <= set(STATES), "unexpected candidate state")
    require(set(frame["inference_status"]) <= set(DISPOSITIONS), "unknown assignment status")
    codes = {topic.code for topic in topics}
    require(
        frame["topic"]
        .dropna()
        .map(
            lambda x: (
                not isinstance(x, (bool, np.bool_))
                and isinstance(x, (int, float, np.integer, np.floating))
                and x in codes
            )
        )
        .all(),
        "unknown topic",
    )
    require(
        frame["topic"].notna().equals(frame["inference_status"].eq("classified")),
        "topic/status mismatch",
    )
    require(
        frame["n_source_views"]
        .map(
            lambda x: (
                not isinstance(x, (bool, np.bool_))
                and isinstance(x, (int, float, np.integer, np.floating))
                and np.isfinite(x)
                and x >= 0
                and int(x) == x
            )
        )
        .all(),
        "invalid original source-view count",
    )
    require(
        frame["n_source_views"].eq(0).equals(frame["inference_status"].eq("unavailable")),
        "absent input is not abstention",
    )
    require(
        frame["abstention_reason"].isna().equals(frame["inference_status"].eq("classified")),
        "original abstention reason/status mismatch",
    )
    for reasons in frame["view_abstention_reasons"]:
        counts = json_bytes(reasons)
        require(
            isinstance(counts, dict)
            and all(isinstance(k, str) and type(v) is int and v > 0 for k, v in counts.items()),
            "invalid original view abstention reasons",
        )
    for flag in frame:
        if flag not in FLAGS and not flag.endswith(
            ("_approved", "_approval", "_admission", "_certified")
        ):
            continue
        require(
            frame[flag].map(lambda x: isinstance(x, (bool, np.bool_)) and not x).all(),
            f"assignment approval flag drift: {flag}",
        )


def load_gallery(directory, tier):
    """Validate the self-contained bundle; never dereference original job/model paths."""
    directory = directory.absolute()
    require(
        directory.is_dir() and directory.resolve() == directory and not directory.is_symlink(),
        "real non-symlink gallery root required",
    )
    manifest_path = directory / "manifest.json"
    require(
        manifest_path.is_file() and manifest_path.resolve() == manifest_path,
        "missing/linked gallery manifest",
    )
    manifest = json_bytes(manifest_path.read_bytes())
    unapproved(manifest)
    require(
        manifest.get("status") == STATUS
        and manifest.get("tiers") == [tier]
        and manifest.get("scientific_certification") == "not_performed"
        and manifest.get("model_promotion") is False
        and manifest.get("publication") is False
        and manifest.get("inference_was_executed") is True
        and manifest.get("model_execution_during_graph_build") is False,
        "completed single-tier provisional gallery required",
    )
    graphs = [
        f"{tier}_{name}"
        for name in (
            "topic_counts",
            "classification_coverage",
            "state_topics",
        )
    ]
    require(manifest.get("graphs") == graphs, "source graph inventory changed")
    expected_artifacts = {
        "index.html",
        "producers/recreate_topic_graphs.py",
        ARCHIVE,
        *(f"graphs/{name}.{ext}" for name in graphs for ext in ("png", "svg")),
        *(f"chart-data/{name}.csv" for name in [*graphs, f"{tier}_bill_assignments"]),
    }
    require(set(manifest["artifacts"]) == expected_artifacts, "exact source artifacts required")
    actual = set()
    for path in directory.rglob("*"):
        require(not path.is_symlink() and path.resolve() == path, "linked gallery artifact")
        require(path.is_dir() or path.is_file(), "non-regular gallery artifact")
        if path.is_file():
            actual.add(path.relative_to(directory).as_posix())
    require(actual == expected_artifacts | {"manifest.json"}, "unbound/missing gallery artifacts")
    pins = {}
    for name, expected in manifest["artifacts"].items():
        path = directory / safe_name(name)
        before = fingerprint(path)
        require(binding(path) == valid_binding(expected), f"artifact binding mismatch: {name}")
        require(fingerprint(path) == before, "gallery changed during validation")
        pins[name] = before
    manifest_binding = binding(manifest_path)
    require(json_bytes(manifest_path.read_bytes()) == manifest, "gallery manifest changed")
    inputs = manifest["inference_inputs"]
    for name, expected in inputs.items():
        safe_name(name)
        valid_binding(expected)
    line_counts, view_keys = {}, {"inputs": {}, "predictions": {}}
    with zipfile.ZipFile(directory / ARCHIVE) as archive:
        members = archive.infolist()
        require(
            len(members) == len(inputs) and {item.filename for item in members} == set(inputs),
            "exact full source ZIP members required",
        )
        plan = json_bytes(archive.read("inference_plan.json"))
        for member in members:
            safe_name(member.filename)
            require(
                not member.is_dir()
                and not member.flag_bits & 1
                and stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG),
                "non-regular/encrypted source ZIP member",
            )
            expected = inputs[member.filename]
            require(member.file_size == expected["bytes"], "ZIP member size mismatch")
            digest, size, lines = hashlib.sha256(), 0, 0
            kind = member.filename.split("/")[0]
            with archive.open(member) as handle:
                chunks = (
                    handle if kind in view_keys else iter(lambda: handle.read(1024 * 1024), b"")
                )
                for chunk in chunks:
                    digest.update(chunk)
                    size += len(chunk)
                    lines += chunk.count(b"\n")
                    if kind in view_keys:
                        require(bool(chunk.strip()), "blank original source/prediction record")
                        row = json_bytes(chunk)
                        unapproved(row)
                        require(
                            row["tier"] == tier
                            and row["state"] in STATES
                            and member.filename == f"{kind}/{tier}-{row['state']}.jsonl"
                            and isinstance(row["input_id"], str)
                            and bool(row["input_id"])
                            and row["input_id"] not in view_keys[kind],
                            "source/prediction identity, tier or state drift",
                        )
                        view_keys[kind][row["input_id"]] = tuple(
                            row[key] for key in (*IDENTITY, "input_sha256")
                        )
                        if kind == "predictions":
                            require(
                                row["model_run"] == plan["model_run"]
                                and row["taxonomy_sha256"] == plan["taxonomy_sha256"],
                                "per-view model/taxonomy drift",
                            )
                        else:
                            unapproved(row["original_source_view"], required=False)
            require(
                {"sha256": digest.hexdigest(), "bytes": size} == expected,
                f"ZIP member binding mismatch: {member.filename}",
            )
            line_counts[member.filename] = lines
        require(
            view_keys["inputs"] == view_keys["predictions"], "exact input/prediction IDs required"
        )
        progress = json_bytes(archive.read(f"progress-{tier}.json"))
        summary = json_bytes(archive.read(f"summary-{tier}.json"))
        for document in (plan, progress, summary):
            unapproved(document)
        require(
            plan.get("schema") == SCHEMA
            and plan.get("status") == "frozen_before_provisional_population_inference"
            and plan.get("model_status") == "provisional"
            and plan.get("human_review_packet_modified_or_scored") is False
            and tier in plan["tiers"]
            and len(set(plan["tiers"])) == len(plan["tiers"])
            and set(plan["tiers"]) <= set(TIERS)
            and isinstance(plan["decision"], dict)
            and bool(plan["decision"])
            and all(plan.get(key) == value for key, value in POLICY.items()),
            "frozen inference scope/policy changed",
        )
        require(
            type(plan["n_contexts"]) is int
            and plan["n_contexts"] >= 0
            and plan["model_run"] == valid_binding(plan["training_manifest"])["sha256"]
            and manifest["model_run"] == plan["model_run"]
            and manifest["candidate_contexts"] == plan["n_contexts"],
            "model/cohort identity mismatch",
        )
        require(
            inputs["contexts.jsonl"] == valid_binding(plan["contexts"])
            and inputs["producer/cycle_topics.py"] == valid_binding(plan["producer"])
            and inputs["producer/modernbert.py"] == valid_binding(plan["frozen_inference_runtime"])
            and inputs["producer/topics.yml"]["sha256"] == plan["taxonomy_sha256"],
            "frozen producer/context/taxonomy binding mismatch",
        )
        for name, expected in plan["source_files"].items():
            safe_name(name)
            valid_binding(expected)
        for name, entry in plan["inputs"].items():
            safe_name(name)
            valid_binding({key: entry[key] for key in ("sha256", "bytes")})
            require(
                entry["tier"] in TIERS
                and entry["state"] in STATES
                and name == f"inputs/{entry['tier']}-{entry['state']}.jsonl",
                "unsafe frozen input inventory",
            )
        contexts = [json_bytes(line) for line in archive.read("contexts.jsonl").splitlines()]
        context_frame = pd.DataFrame(contexts, columns=IDENTITY)
        require(
            len(context_frame) == plan["n_contexts"]
            and not context_frame["bill_id"].duplicated().any(),
            "complete unique frozen contexts required",
        )
        for context in contexts:
            unapproved(context, required=False)
        scheme = yaml.safe_load(archive.read("producer/topics.yml"))
        topics = [
            SimpleNamespace(code=item["code"], name=item["name"]) for item in scheme["topics"]
        ]
        require(
            len(topics) == 21
            and len({t.code for t in topics}) == 21
            and len({t.name for t in topics}) == 21
            and all(type(t.code) is int and isinstance(t.name, str) and t.name for t in topics),
            "complete 21-topic taxonomy required",
        )
        frame = pd.read_parquet(io.BytesIO(archive.read(f"bill_assignments-{tier}.parquet")))
        assignment_shape(frame, topics)
        require(set(frame["bill_id"]) == set(context_frame["bill_id"]), "exact bill_id cohort")
        original = context_frame.set_index("bill_id").sort_index()
        aligned = frame.set_index("bill_id").sort_index()
        require(
            all(aligned[key].equals(original[key]) for key in IDENTITY[1:]),
            "assignment/frozen context identity mismatch",
        )
        source_counts = Counter()
        frozen_keys = set(context_frame.itertuples(index=False, name=None))
        for key in view_keys["inputs"].values():
            require(
                key[:-1] in frozen_keys,
                "original source view outside frozen candidate identity",
            )
            source_counts[key[0]] += 1
        require(
            all(
                source_counts[bill_id] == count
                for bill_id, count in aligned["n_source_views"].items()
            ),
            "per-bill original view count mismatch",
        )
        available = frame["inference_status"].ne("unavailable")
        require(
            frame.loc[available, "model_run"].eq(plan["model_run"]).all()
            and frame.loc[~available, "model_run"].isna().all(),
            "assignment model drift",
        )
        require(
            progress.get("status") == "complete_provisional_inference_not_scientific_validation"
            and progress.get("tier") == tier
            and progress.get("model_run") == plan["model_run"]
            and progress.get("inference_plan_sha256") == inputs["inference_plan.json"]["sha256"]
            and set(progress["states"]) == set(STATES),
            "all fifty states must be completed under the frozen plan",
        )
        selected = {name: entry for name, entry in plan["inputs"].items() if entry["tier"] == tier}
        require(
            set(selected) == {f"inputs/{tier}-{state}.jsonl" for state in STATES},
            "exact frozen tier input inventory required",
        )
        expected_members = {
            "inference_plan.json",
            "contexts.jsonl",
            "producer/cycle_topics.py",
            "producer/modernbert.py",
            "producer/topics.yml",
            f"summary-{tier}.json",
            f"progress-{tier}.json",
            f"bill_assignments-{tier}.parquet",
            *selected,
            *(f"predictions/{tier}-{state}.jsonl" for state in STATES),
        }
        require(set(inputs) == expected_members, "complete original input/prediction ZIP required")
        for state in STATES:
            name = f"inputs/{tier}-{state}.jsonl"
            entry, done = selected[name], progress["states"][state]
            predicted = f"predictions/{tier}-{state}.jsonl"
            require(
                entry["state"] == state
                and type(entry["views"]) is int
                and entry["views"] >= 0
                and inputs[name] == {key: entry[key] for key in ("sha256", "bytes")}
                and inputs[predicted] == valid_binding(done["artifact"])
                and line_counts[name] == line_counts[predicted] == done["views"] == entry["views"]
                and int(frame.loc[frame["state"].eq(state), "n_source_views"].sum())
                == entry["views"],
                f"incomplete source-view population: {state}",
            )
        counts = {key: int(frame["inference_status"].eq(key).sum()) for key in DISPOSITIONS}
        require(
            summary.get("tier") == tier
            and summary.get("contexts") == plan["n_contexts"]
            and summary["assignments"] == inputs[f"bill_assignments-{tier}.parquet"]
            and summary["source_views"]
            == plan["n_views_by_tier"][tier]
            == int(frame["n_source_views"].sum())
            and summary["assignment_counts"] == {key: n for key, n in counts.items() if n}
            and summary["topic_counts"]
            == {
                str(t.code): int(frame["topic"].eq(t.code).sum())
                for t in topics
                if frame["topic"].eq(t.code).any()
            }
            and manifest["assignment_counts_by_tier"]
            == {tier: {"candidate_contexts": len(frame), **counts}},
            "source summary/population mismatch",
        )
    return {
        "directory": directory,
        "tier": tier,
        "manifest": manifest,
        "plan": plan,
        "frame": frame,
        "topics": topics,
        "pins": pins,
        "manifest_binding": manifest_binding,
    }


def compatible(metadata, retained):
    left, right = metadata["plan"], retained["plan"]
    require(
        {key: value for key, value in left.items() if key not in VARIABLE_PLAN_KEYS}
        == {key: value for key, value in right.items() if key not in VARIABLE_PLAN_KEYS},
        "frozen cohort/model/decision/input-policy drift",
    )


def bill_comparison(metadata, retained, topics):
    for frame in (metadata, retained):
        assignment_shape(frame, topics)
    require(set(metadata["bill_id"]) == set(retained["bill_id"]), "exact bill_id cohort drift")
    left = metadata.set_index("bill_id").sort_index()
    right = retained.set_index("bill_id").sort_index()
    require(
        all(left[key].equals(right[key]) for key in IDENTITY[1:]),
        "candidate state/stable identity drift",
    )
    result = left[list(IDENTITY[1:])].copy()
    original_columns = (
        "inference_status",
        "topic",
        "abstention_reason",
        "view_abstention_reasons",
        "n_source_views",
        "model_run",
    )
    for tier, frame in zip(TIERS, (left, right), strict=True):
        result[f"{tier}_tier"] = tier
        for column in original_columns:
            result[f"{tier}_{column}"] = frame[column]
        result[f"{tier}_research_download"] = f"research-data/{tier}_complete_inference.zip"
        result[f"{tier}_assignment_member"] = f"bill_assignments-{tier}.parquet"
    paired = left["inference_status"].ne("unavailable") & right["inference_status"].ne(
        "unavailable"
    )
    both_assigned = left["inference_status"].eq("classified") & right["inference_status"].eq(
        "classified"
    )
    both_abstain = left["inference_status"].eq("abstained") & right["inference_status"].eq(
        "abstained"
    )
    result["paired_available"] = paired
    result["comparison_category"] = np.select(
        [~paired, both_assigned & left["topic"].eq(right["topic"]), both_assigned, both_abstain],
        ["unavailable", "same_assigned_topic", "different_assigned_topic", "both_abstaining"],
        default="exactly_one_abstaining",
    )
    return result.reset_index()


def group_tables(frame, topics, scope):
    paired = frame[frame["paired_available"]]
    n = len(paired)
    summary = {"scope": scope, "all_candidate_contexts": len(frame), "paired_contexts": n}
    for tier in TIERS:
        for status in DISPOSITIONS:
            summary[f"{tier}_{status}_contexts"] = int(
                frame[f"{tier}_inference_status"].eq(status).sum()
            )
        summary[f"{tier}_paired_abstained_contexts"] = int(
            paired[f"{tier}_inference_status"].eq("abstained").sum()
        )
    summary["either_unavailable_contexts"] = len(frame) - n
    summary["both_unavailable_contexts"] = int(
        frame["metadata_inference_status"]
        .eq("unavailable")
        .mul(frame["retained_text_inference_status"].eq("unavailable"))
        .sum()
    )
    for category in CATEGORIES:
        summary[category] = int(frame["comparison_category"].eq(category).sum())
    denominator = {
        key: value
        for key, value in summary.items()
        if key in {"scope", "all_candidate_contexts", "paired_contexts"}
        or key.endswith(("_unavailable_contexts", "_paired_abstained_contexts"))
    }
    shares = []
    for topic in topics:
        row = {**denominator, "topic": topic.code, "topic_name": topic.name}
        for tier in TIERS:
            count = int(paired[f"{tier}_topic"].eq(topic.code).sum())
            row[f"{tier}_assigned_contexts"] = count if n else None
            row[f"{tier}_share_of_paired"] = count / n if n else None
        row["retained_text_minus_metadata_share"] = (
            row["retained_text_share_of_paired"] - row["metadata_share_of_paired"] if n else None
        )
        shares.append(row)
    labels = [(str(t.code), t.name) for t in topics] + [("abstained", "Abstained")]
    source = paired["metadata_topic"].map(lambda x: str(int(x)) if pd.notna(x) else "abstained")
    target = paired["retained_text_topic"].map(
        lambda x: str(int(x)) if pd.notna(x) else "abstained"
    )
    counts = pd.crosstab(source, target)
    transitions = []
    for start, start_name in labels:
        row_n = int(source.eq(start).sum())
        for end, end_name in labels:
            count = int(counts.at[start, end]) if start in counts.index and end in counts else 0
            transitions.append(
                {
                    **denominator,
                    "metadata_topic": start,
                    "metadata_topic_name": start_name,
                    "retained_text_topic": end,
                    "retained_text_topic_name": end_name,
                    "paired_transition_contexts": count if n else None,
                    "metadata_row_contexts": row_n,
                    "share_of_metadata_row": count / row_n if row_n else None,
                }
            )
    return summary, shares, transitions


def comparison_tables(metadata, retained, topics):
    bills = bill_comparison(metadata, retained, topics)
    summary, national, transitions = group_tables(bills, topics, "national")
    state_summary, state_topics, state_transitions = [], [], []
    for state in STATES:
        counts, shares, matrix = group_tables(bills[bills["state"].eq(state)], topics, state)
        state_summary.append(counts)
        state_topics.extend(shares)
        state_transitions.extend(matrix)
    return {
        "bill_comparison": bills,
        "national_summary": pd.DataFrame([summary]),
        "state_summary": pd.DataFrame(state_summary),
        "topic_shares": pd.DataFrame(national),
        "state_topic_shares": pd.DataFrame(state_topics),
        "topic_transitions": pd.DataFrame(transitions),
        "state_topic_transitions": pd.DataFrame(state_transitions),
    }


def render(output, tables):
    theme.apply()
    summary = tables["national_summary"].iloc[0]
    denominator = (
        f"Paired available n={summary['paired_contexts']:,} / all candidates "
        f"n={summary['all_candidate_contexts']:,}. Paired abstentions included: "
        f"metadata n={summary['metadata_paired_abstained_contexts']:,}; "
        f"retained text n={summary['retained_text_paired_abstained_contexts']:,}."
    )

    def save(fig, name, title):
        fig.suptitle(title, x=0.02, y=0.98, ha="left", fontsize=16, fontweight="bold")
        note = theme.source_note(fig, f"{denominator} {NOTICE}", x=0.02)
        theme.layout_with_note(fig, note, top=0.93)
        for suffix in ("png", "svg"):
            fig.savefig(output / f"{name}.{suffix}", dpi=160, facecolor=theme.BG)
        plt.close(fig)

    shares = tables["topic_shares"]
    fig, ax = plt.subplots(figsize=(11, 9))
    y = np.arange(len(shares))
    left = shares["metadata_share_of_paired"].to_numpy(dtype=float) * 100
    right = shares["retained_text_share_of_paired"].to_numpy(dtype=float) * 100
    if summary["paired_contexts"]:
        ax.hlines(y, np.minimum(left, right), np.maximum(left, right), color=theme.GRID, lw=2)
        ax.scatter(
            left,
            y,
            s=40,
            facecolors=theme.BG,
            edgecolors=theme.TEXT,
            label="Title / abstract",
            zorder=3,
            clip_on=False,
        )
        ax.scatter(
            right,
            y,
            s=18,
            color=theme.BLUE,
            label="Retained full text",
            zorder=4,
            clip_on=False,
        )
        ax.legend(loc="lower right", fontsize=9)
    else:
        ax.text(
            0.5,
            0.5,
            "No paired available inputs; topic shares unknown",
            transform=ax.transAxes,
            ha="center",
            color=theme.MUTED,
        )
    ax.set_yticks(y, shares["topic_name"], fontsize=10)
    ax.invert_yaxis()
    ax.set_xlim(
        left=0,
        right=max(1, float(np.nanmax([left, right])) * 1.15) if summary["paired_contexts"] else 100,
    )
    ax.set_xlabel("Assigned topic / same paired available bills (%)")
    ax.grid(axis="x")
    save(fig, "topic_shares", "Same bills, different supplied input tiers")

    matrix = tables["topic_transitions"]
    labels = matrix["metadata_topic_name"].drop_duplicates().tolist()
    values = matrix["share_of_metadata_row"].to_numpy(dtype=float).reshape(len(labels), -1)
    row_ns = matrix.groupby("metadata_topic_name", sort=False)["metadata_row_contexts"].first()
    fig, ax = plt.subplots(figsize=(13, 12))
    cmap = LinearSegmentedColormap.from_list(
        "input_tier_transition", [theme.BG, theme.BLUE]
    ).with_extremes(bad=theme.GRID)
    image = ax.imshow(
        np.ma.masked_invalid(values * 100), vmin=0, vmax=100, cmap=cmap, aspect="auto"
    )
    ax.set_xticks(range(len(labels)), labels, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(
        range(len(labels)), [f"{label} (n={int(row_ns[label]):,})" for label in labels], fontsize=8
    )
    ax.set_xlabel("Retained full text disposition")
    ax.set_ylabel("Title / abstract disposition; paired row denominator")
    fig.colorbar(image, ax=ax, shrink=0.55, label="Share of metadata row (%)")
    ax.set_title("Gray: unobserved row / unknown share. Paper: observed zero.", fontsize=10, pad=12)
    save(fig, "topic_transitions", "Input-tier transitions, conditional on metadata disposition")
    return ["topic_shares", "topic_transitions"]


def compare(metadata_gallery, retained_text_gallery, output):
    output = output.absolute()
    require(
        not output.exists()
        and not output.is_symlink()
        and output.resolve() == output
        and output != ROOT / "outputs"
        and output.is_relative_to(ROOT / "outputs"),
        "new project output directory required",
    )
    sources = [
        load_gallery(metadata_gallery, "metadata"),
        load_gallery(retained_text_gallery, "retained_text"),
    ]
    compatible(*sources)
    tables = comparison_tables(sources[0]["frame"], sources[1]["frame"], sources[0]["topics"])
    require(
        not any(source["directory"].is_relative_to(output) for source in sources),
        "output must not contain source galleries",
    )
    output.mkdir(parents=True, exist_ok=False)
    try:
        for name in ("graphs", "chart-data", "research-data", "producers"):
            (output / name).mkdir()
        for name, table in tables.items():
            table.to_csv(output / f"chart-data/{name}.csv", index=False)
        graphs = render(output / "graphs", tables)
        source_bindings = {}
        for source in sources:
            tier, directory = source["tier"], source["directory"]
            destination = output / f"research-data/{tier}_complete_inference.zip"
            shutil.copy2(directory / ARCHIVE, destination)
            require(
                not destination.samefile(directory / ARCHIVE)
                and binding(destination) == source["manifest"]["artifacts"][ARCHIVE],
                "full source ZIP copy changed",
            )
            shutil.copy2(
                directory / "manifest.json", output / f"research-data/{tier}_gallery_manifest.json"
            )
            require(
                binding(output / f"research-data/{tier}_gallery_manifest.json")
                == source["manifest_binding"],
                "source manifest changed during copy",
            )
            with zipfile.ZipFile(destination) as archive:
                (output / f"research-data/{tier}_inference_plan.json").write_bytes(
                    archive.read("inference_plan.json")
                )
            shutil.copy2(
                directory / "producers/recreate_topic_graphs.py",
                output / f"producers/{tier}_recreate_topic_graphs.py",
            )
            source_bindings[tier] = {
                "gallery_root": str(directory),
                "gallery_manifest": source["manifest_binding"],
                "full_source_zip": source["manifest"]["artifacts"][ARCHIVE],
                "download": destination.relative_to(output).as_posix(),
                "frozen_plan": source["manifest"]["inference_inputs"]["inference_plan.json"],
                "contexts": source["plan"]["contexts"],
                "model_run": source["plan"]["model_run"],
                "decision": source["plan"]["decision"],
                "taxonomy_sha256": source["plan"]["taxonomy_sha256"],
                "scope": source["plan"]["scope"],
                "n_contexts": source["plan"]["n_contexts"],
            }
        shutil.copy2(Path(__file__), output / "producers/compare_cycle_topic_inputs.py")
        shutil.copy2(Path(theme.__file__), output / "producers/theme.py")
        summary = tables["national_summary"].iloc[0].to_dict()
        cards = "".join(
            f"<section><h2>{html.escape(name.replace('_', ' ').capitalize())}</h2>"
            f'<a href="graphs/{name}.png"><img src="graphs/{name}.png" '
            f'alt="{html.escape(name.replace("_", " "))}"></a><p>'
            f'<a href="graphs/{name}.svg">SVG</a> · '
            f'<a download href="chart-data/{name}.csv">Complete chart data</a></p></section>'
            for name in graphs
        )
        downloads = "".join(
            f'<li><a download href="{entry["download"]}">{html.escape(tier)}: complete '
            "original inputs, full texts, source-view records, predictions, assignments, "
            "frozen plan and producers (ZIP)</a> · "
            f'<a href="research-data/{tier}_gallery_manifest.json">'
            "Original gallery manifest</a> · "
            f'<a href="research-data/{tier}_inference_plan.json">Frozen plan</a></li>'
            for tier, entry in source_bindings.items()
        )
        csv_links = "".join(
            f'<li><a download href="chart-data/{name}.csv">{name.replace("_", " ")}</a></li>'
            for name in tables
        )
        (output / "index.html").write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Matched-input provisional topic comparison</title><style>"
            f"body{{max-width:1100px;margin:40px auto;padding:0 24px;background:{theme.BG};"
            f"color:{theme.TEXT};font:16px/1.6 Georgia,serif}}a{{color:{theme.BLUE};"
            "overflow-wrap:anywhere}img{max-width:100%;height:auto}section{margin:40px 0;"
            "border-top:1px solid #D6D3CC}h1,h2{font-weight:normal}</style><main>"
            "<p>LOCAL / UNPUBLISHED / PROVISIONAL</p><h1>Same bills, different supplied inputs</h1>"
            f"<p>{html.escape(NOTICE)}</p><p>All candidates "
            f"n={summary['all_candidate_contexts']:,}; "
            f"paired available inputs n={summary['paired_contexts']:,}. "
            f"Metadata unavailable n={summary['metadata_unavailable_contexts']:,}; retained text "
            f"unavailable n={summary['retained_text_unavailable_contexts']:,}. "
            "Every topic share uses the same paired available contexts, including abstentions: "
            f"metadata n={summary['metadata_paired_abstained_contexts']:,}; retained text "
            f"n={summary['retained_text_paired_abstained_contexts']:,}. "
            "No-paired groups are unknown. A transition row uses its displayed paired row "
            "denominator, not all assigned bills. Gray rows are unobserved; observed zeros "
            "are distinct.</p><h2>Full research downloads</h2><ul>"
            f"{downloads}</ul><p>Both ZIPs are complete byte-preserving copies, not chart-only "
            "metadata. Locate original records by bill_id and the assignment member recorded "
            "in the per-bill comparison.</p><h2>Complete tables</h2>"
            f"<ul>{csv_links}</ul>{cards}</main></html>"
        )
        for source in sources:
            directory = source["directory"]
            require(
                binding(directory / "manifest.json") == source["manifest_binding"]
                and all(
                    (directory / name).resolve() == directory / name
                    and fingerprint(directory / name) == pin
                    for name, pin in source["pins"].items()
                ),
                "source gallery changed during comparison",
            )
        result = {
            "schema": "state-politics.matched-input-topic-comparison.v1",
            "status": STATUS,
            "bundle_kind": "matched_input_topic_comparison",
            "notice": NOTICE,
            "tiers": list(TIERS),
            "model_run": sources[0]["plan"]["model_run"],
            "candidate_contexts": summary["all_candidate_contexts"],
            "denominators_and_descriptive_counts": summary,
            "topic_share_denominator": "same_paired_available_contexts_including_abstentions",
            "transition_denominator": "paired_metadata_disposition_row",
            "source_bundles": source_bindings,
            "graphs": graphs,
            "scientific_certification": "not_performed",
            "model_promotion": False,
            "publication": False,
            "inference_was_executed": True,
            "inference_execution_scope": "completed_source_bundles_only_not_this_comparison",
            "model_execution_during_graph_build": False,
            "model_execution": False,
            "source_collection": False,
            **FLAGS,
            "artifacts": {
                path.relative_to(output).as_posix(): binding(path)
                for path in sorted(output.rglob("*"))
                if path.is_file()
            },
        }
        (output / "manifest.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    except BaseException:
        shutil.rmtree(output)
        raise
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-gallery", type=Path, required=True)
    parser.add_argument("--retained-text-gallery", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = compare(args.metadata_gallery, args.retained_text_gallery, args.out_dir)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("status", "graphs", "denominators_and_descriptive_counts")
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Index selected, accepted initial originals offline; never collect or reread PDFs.

The context population is deliberately bounded to the accepted selections, not the
publisher-listed population. Reader alternatives remain complete, separate views.
Run with ``python -I -B -m state_politics.bills.study_partial_native --out-dir ...``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from ..provenance import sha256_file, utc_now_iso
from .study_sources import _unique
from .study_window import _snapshot

PROFILES = {
    "MI": {
        "root": "michigan-2023-2024-native-source-recovery-v3",
        "manifest_sha256": "8cb58b5974ab983f85f08ec18ac5c482bdc1e8c098aefa9571d5ae5b24e5891a",
        "manifest_members": "files",
        "contexts": "v1_input/documents.parquet",
        "canonical": "v1_input/canonical_context.jsonl",
        "expected_contexts": 32,
        "expected_views": 64,
        "accepted_listed_identities": 4043,
        "limitations": [
            "Only the 32 selected genuine PDFs are indexed; 4,011 listed originals remain pending.",
            "Printed session years are absent; no URL/filename year becomes date evidence.",
            "Letter joint-resolution identifiers are retained exactly, never numeric aliases.",
        ],
    },
    "MD": {
        "root": "maryland-2023-2024-native-source-recovery-v2",
        "manifest_sha256": "4aac8eeeb18fb297cb2a376b44577d0a045d8fa4636ef4f87d482108a3a6b9db",
        "manifest_members": "inventory",
        "contexts": "derived/source_views.json",
        "canonical": "inputs/bills.parquet",
        "expected_contexts": 8,
        "expected_views": 16,
        "accepted_listed_identities": 5012,
        "limitations": [
            "Only eight selected introduced contexts are indexed, not all 5,012 inventory rows.",
            "Two calendar PDFs and all 18 non-original HTML documents are excluded from views.",
            "Calendar schedules are not bill text or actual-session-boundary certification.",
        ],
    },
    "MN": {
        "root": "minnesota-2023-2024-native-source-recovery-v1",
        "manifest_sha256": "a5183881c8d1de65151460b31640f73f9def22504c979b5bdcbe78dbde1412c3",
        "manifest_members": "files",
        "contexts": "contexts_evidence.json",
        "canonical": "reconciliation.json",
        "expected_contexts": 32,
        "expected_views": 93,
        "accepted_listed_identities": 11146,
        "limitations": [
            "Only 32 selected native contexts are indexed; SR61 has no complete original pair.",
            "31 HTML/PDF original pairs give 93 alternative views, not 93 bills.",
            "Native row/draft year is not introduction year; cross-year context is retained.",
            "Only 21 selected contexts have printed PDF identity/session support in both readers.",
            "HTML views retain every stored decoded text span, including source front matter.",
        ],
    },
    "KY": {
        "root": "kentucky-2023-2024-native-source-recovery-v1",
        "manifest_sha256": "9e59c24b2ee2a4dae7b4d51d6b6268096091e2eb7a2833d1ee63e83816cdbd81",
        "manifest_members": "members",
        "contexts": "derived/contexts.json",
        "canonical": "inputs/bills.parquet",
        "expected_contexts": 32,
        "expected_views": 60,
        "accepted_listed_identities": 3005,
        "limitations": [
            "Only 32 selected contexts are indexed; 30 genuine introduced PDFs are available.",
            "Withdrawn 2024 HJR21/HJR22 have no Introduced link/action and have no text views.",
            "Detail HTML is not original full-bill text; two boundary PDFs are excluded.",
            "Printed BR numbers are bill requests, not typed bill identities; no BR aliases.",
        ],
    },
}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _one(values, description):
    if len(values) != 1:
        raise ValueError(f"ambiguous or missing {description}")
    return values[0]


class FrozenPacket:
    """Read only checksum-bound members; snapshot exactly the files consumed."""

    def __init__(self, root: Path, spec: dict):
        self.root = root.resolve()
        self.before = {"manifest.json": _snapshot(self.root / "manifest.json")}
        if self.before["manifest.json"]["sha256"] != spec["manifest_sha256"]:
            raise ValueError("unaccepted initial-source manifest")
        manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        members = manifest[spec["manifest_members"]]
        self.members = (
            members if isinstance(members, dict) else {entry["path"]: entry for entry in members}
        )
        self.cache: dict[str, object] = {}

    def pin(self, name: str) -> dict:
        path = self.root / name
        if Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink():
            raise ValueError("source path must be an ordinary packet member")
        if not path.resolve().is_relative_to(self.root) or name not in self.members:
            raise ValueError(f"unbound source member: {name}")
        if name not in self.before:
            binding = self.members[name]
            expected = binding if isinstance(binding, str) else binding["sha256"]
            snapshot = _snapshot(path)
            if snapshot["sha256"] != expected:
                raise ValueError(f"source member checksum mismatch: {name}")
            if isinstance(binding, dict):
                size = binding.get("bytes", binding.get("size"))
                if size is not None and size != snapshot["size"]:
                    raise ValueError(f"source member size mismatch: {name}")
            self.before[name] = snapshot
        return self.before[name]

    def read(self, name: str):
        self.pin(name)
        if name not in self.cache:
            path = self.root / name
            if path.suffix == ".parquet":
                value = json.loads(pd.read_parquet(path).to_json(orient="records"))
            elif path.suffix == ".jsonl":
                value = [
                    json.loads(line)
                    for line in path.read_text(encoding="utf-8").split("\n")
                    if line
                ]
            else:
                value = json.loads(path.read_text(encoding="utf-8"))
            self.cache[name] = value
        return self.cache[name]

    def stable(self) -> dict:
        after = {name: _snapshot(self.root / name) for name in self.before}
        if after != self.before:
            raise ValueError("consumed original source changed")
        return {"before": self.before, "after": after, "all_consumed_files_unchanged": True}


def _canonical_rows(packet: FrozenPacket, state: str, spec: dict) -> list[dict]:
    name = spec["canonical"]
    if name.endswith(".parquet"):
        packet.pin(name)
        return pd.read_parquet(
            packet.root / name,
            columns=["bill_id", "state", "identifier", "session_identifier"],
            filters=[("state", "==", state)],
        ).to_dict("records")
    value = packet.read(name)
    return value["canonical_rows"] if state == "MN" else value


def _records(packet: FrozenPacket, state: str, spec: dict) -> list[dict]:
    """Small schema selectors feed the same context/view builder."""
    raw = packet.read(spec["contexts"])
    canonical = _canonical_rows(packet, state, spec)
    by_id = {row["bill_id"]: row for row in canonical}
    if len(by_id) != len(canonical):
        raise ValueError("nonunique frozen canonical identity")
    selected = {}
    native_to_canonical = {}
    if state == "MD":
        selected = {
            tuple(row["typed_key"]): row for row in packet.read("derived/selected.json")
        }
        raw = raw["contexts"]
    elif state == "MN":
        references = packet.read("native_census.json")["references"]
        reconciliation = packet.read(spec["canonical"])
        for join in reconciliation["joins"]:
            bill = canonical[_one(join["canonical_row_indices"], "canonical row")]
            if join["status"] != "exact":
                raise ValueError("unresolved Minnesota crosswalk")
            for index in join["native_reference_indices"]:
                reference = references[index]
                key = [
                    reference["canonical_session"], reference["chamber"],
                    reference["type"], reference["number"],
                ]
                if key != join["key"]:
                    raise ValueError("Minnesota reference/crosswalk disagreement")
                native_to_canonical[_json(reference)] = bill
    rows = []
    for index, row in enumerate(raw):
        if state == "MI":
            bill = _one(
                [bill for bill in canonical if bill["identifier"] == row["identifier"]],
                "Michigan identifier crosswalk",
            )
            context_id, native_identifier = row["pdf_url"], row["identifier"]
            native_session = bill["session_identifier"]
            available = row["failed"] is False
            flags = ["printed_session_year_absent"]
        elif state == "MD":
            bill = by_id[_one(row["canonical_bill_ids"], "Maryland bill ID")]
            native = selected[tuple(row["typed_key"])]
            context_id, native_identifier = native["url"], native["literal_identifier"]
            native_session = native["literal_session_key"]
            available, flags = True, []
        elif state == "MN":
            reference = row["reference"]
            bill = native_to_canonical[_json(reference)]
            context_id, native_identifier = reference["url"], reference["printed_identifier"]
            native_session = reference["native_session"]
            available = row["recovered_full_original_pair"] is True
            flags = list(row["gaps"])
            if not row["pdf_printed_identity_both_readers"]:
                flags.append("printed_pdf_identity_not_established")
            if not row["pdf_printed_session_both_readers"]:
                flags.append("printed_pdf_session_not_established")
        else:
            crosswalk = _one(row["canonical_exact_typed_session_rows"], "Kentucky crosswalk")
            if crosswalk["typed_key"] != row["typed_key"]:
                raise ValueError("Kentucky native/canonical key disagreement")
            bill = by_id[crosswalk["bill_id"]]
            context_id, native_identifier = row["detail_url"], crosswalk["identifier"]
            native_session = row["printed_session"]["identifier"]
            available = row["original_exchange"] is not None and row["original_stage"] is not None
            flags = ["printed_BR_is_not_bill_identity", "printed_pdf_typed_identity_absent"]
            if not available:
                if row["introduction_events"]:
                    raise ValueError("unexpected Kentucky selected gap")
                flags.append("withdrawn_selected_gap_no_introduced_link_or_action")
        if bill.get("state", state) != state:
            raise ValueError("canonical cross-state disagreement")
        rows.append({
            "context_id": context_id,
            "identifier": bill["identifier"],
            "native_identifier": native_identifier,
            "session_identifier": bill["session_identifier"],
            "native_session_identifier": native_session,
            "canonical_bill_id": bill["bill_id"],
            "source_record": row,
            "source_record_locator": f"{'contexts/' if state == 'MD' else ''}{index}",
            "available": available,
            "negative_flags": flags,
        })
    return rows


def _reader_inputs(packet: FrozenPacket, state: str, spec: dict, context: dict):
    row = context["source_record"]
    if not context["available"]:
        return
    if state == "MI":
        for reader in ("pymupdf", "pypdf"):
            stream = row[f"reader_streams.{reader}"]
            name = f"v1_input/{stream['file']}"
            pages = packet.read(name)
            if (
                packet.pin(name)["sha256"] != stream["file_sha256"]
                or len(pages) != stream["page_count"]
                or [page["page_number"] for page in pages] != list(range(1, len(pages) + 1))
                or any(page["reader"] != reader for page in pages)
                or any(_digest(page["text"]) != page["utf8_sha256"] for page in pages)
            ):
                raise ValueError("Michigan retained page stream mismatch")
            yield {
                "reader": reader, "source_reader": reader,
                "segments": [page["text"] for page in pages],
                "extraction_path": name, "extraction_selector": "all JSONL rows / text",
                "source_path": f"v1_input/{row['raw_pdf_file']}",
                "source_url": row["pdf_url"], "source_sha256": row["raw_pdf_sha256"],
                "n_pages": len(pages), "kind": "original_pdf",
            }
    elif state in {"MD", "KY"}:
        name = spec["contexts"] if state == "MD" else "derived/source_views.json"
        data = packet.read(name)
        exchange = row["pdf_exchange"] if state == "MD" else row["original_exchange"]
        if state == "MD":
            view = data["pdf_views"][exchange]
            if view["purpose"] != "selected_first_text_pdf":
                raise ValueError("calendar or non-original Maryland PDF")
            source_url = view["source_url"]
            if source_url != row["first_text_url"]:
                raise ValueError("Maryland original-link disagreement")
            selector = f"pdf_views/{exchange}"
        else:
            if data[exchange]["kind"] != "PDF":
                raise ValueError("Kentucky original is not a PDF")
            view = data[exchange]["view"]
            source_url = row["original_stage"]["url"]
            selector = f"{exchange}/view"
        for reader in ("pymupdf", "pypdf"):
            pages = view[f"{reader}_pages"] if state == "MD" else view[reader]
            if state == "MD":
                if len(pages) != view["page_count"]:
                    raise ValueError("Maryland incomplete stored reader")
                segments = pages
            else:
                if [page["physical_page"] for page in pages] != list(range(1, len(pages) + 1)):
                    raise ValueError("Kentucky incomplete stored reader")
                segments = [page["text"] for page in pages]
            yield {
                "reader": reader, "source_reader": reader, "segments": segments,
                "extraction_path": name,
                "extraction_selector": f"{selector}/{reader}"
                + ("_pages" if state == "MD" else "/*/text"),
                "source_path": f"transport/{exchange}.body", "source_url": source_url,
                "source_sha256": view.get("sha256"),
                "n_pages": len(pages), "kind": "original_pdf",
            }
    else:
        for kind in ("html", "pdf"):
            exchange = row[f"{kind}_exchange"]
            name = f"projections/{exchange:03}.{kind}.json"
            projection = packet.read(name)
            metadata = packet.read(f"transport/{exchange:03}/writeout.json")
            if metadata["http_code"] != 200:
                raise ValueError("Minnesota original response is not complete")
            common = {
                "extraction_path": name, "source_path": f"transport/{exchange:03}/body.bin",
                "source_url": metadata["url_effective"], "source_sha256": None,
            }
            if kind == "html":
                spans = projection["text_spans"]
                if not projection["full_source_markup"]:
                    raise ValueError("Minnesota HTML original body unavailable")
                yield {
                    **common, "reader": "html_full_projection",
                    "source_reader": "stored_decoded_text_spans",
                    "segments": [span["decoded"] for span in spans],
                    "extraction_selector": "text_spans/*/decoded",
                    "n_pages": None, "kind": "original_html",
                }
            else:
                for source_reader, reader in (("fitz", "pymupdf"), ("pypdf", "pypdf")):
                    pages = projection[source_reader]
                    if (
                        len(pages) != projection["page_count"]
                        or len(pages) != row["page_count"]
                        or [page["page"] for page in pages] != list(range(1, len(pages) + 1))
                    ):
                        raise ValueError("Minnesota incomplete stored reader")
                    yield {
                        **common, "reader": reader, "source_reader": source_reader,
                        "segments": [page["text"] for page in pages],
                        "extraction_selector": f"{source_reader}/*/text",
                        "n_pages": len(pages), "kind": "original_pdf",
                    }


def native_date_observations(state: str, row: dict) -> list[dict]:
    """Retain explicit saved observations only; no date parsing or calendar inference."""
    observations = []
    if state == "KY":
        for index, event in enumerate(row["introduction_events"]):
            observations.append({
                "event_kind": "introduction",
                "raw_value": event["date"],
                "source_field": f"introduction_events/{index}/date",
                "basis": "publisher detail-page introduced-action date retained in accepted packet",
            })
    elif state == "MN":
        for index, event in enumerate(row["native_introduction_action_rows"]):
            observations.append({
                "event_kind": "introduction",
                "raw_value": event["printed_date"],
                "source_field": f"native_introduction_action_rows/{index}/printed_date",
                "basis": "publisher Introduction action-row date retained in accepted packet",
            })
    elif state == "MD":
        for reader in ("pymupdf", "pypdf"):
            introduced = row["printed_observations"][reader].get("introduced")
            if introduced:
                observations.append({
                    "event_kind": "introduction",
                    "raw_value": introduced["literal"],
                    "source_field": f"printed_observations/{reader}/introduced/literal",
                    "basis": "full saved Introduced and read first time literal, not a header year",
                })
    return observations


def complete_view(packet: FrozenPacket, context: dict, source: dict) -> dict:
    """Concatenate every stored segment unchanged, never mix or select readers."""
    segments = source["segments"]
    if not segments or any(not isinstance(segment, str) for segment in segments):
        raise ValueError("missing complete stored source text")
    text = "".join(segments)
    if not text.strip():
        raise ValueError("empty stored source text")
    extraction = packet.pin(source["extraction_path"])
    original = packet.pin(source["source_path"])
    if source["source_sha256"] and original["sha256"] != source["source_sha256"]:
        raise ValueError("original source checksum disagreement")
    return {
        "view_id": f"{context['context_id']}::{source['reader']}",
        "context_id": context["context_id"],
        "reader": source["reader"],
        "source_reader": source["source_reader"],
        "input_sha256": _digest(text),
        "raw_text_sha256": _digest(text),
        "n_input_characters": len(text),
        "text": text,
        "source_kind": source["kind"],
        "n_pages": source["n_pages"],
        "source_url": source["source_url"],
        "original_source_path": str(packet.root / source["source_path"]),
        "original_source_sha256": original["sha256"],
        "extraction_path": str(packet.root / source["extraction_path"]),
        "extraction_sha256": extraction["sha256"],
        "extraction_selector": source["extraction_selector"],
        "source_record_sha256": _digest(_json(context["source_record"])),
        "segment_character_counts_json": _json([len(segment) for segment in segments]),
        "segment_text_sha256s_json": _json([_digest(segment) for segment in segments]),
        "text_assembly": "all_stored_segments_in_order_no_added_characters",
        "full_source_text_available": True,
        "approved": False,
        "policy_eligible": False,
        "analytical_admission": False,
        "training_admission": False,
    }


def reconcile_tables(contexts: pd.DataFrame, views: pd.DataFrame) -> dict:
    _unique(contexts, "context_id")
    _unique(views, "view_id")
    if (
        not views["context_id"].isin(contexts["context_id"]).all()
        or views.duplicated(["context_id", "reader"]).any()
        or not views["text"].map(_digest).eq(views["input_sha256"]).all()
        or not views["text"].str.len().eq(views["n_input_characters"]).all()
        or views["text"].str.strip().eq("").any()
        or views[["approved", "policy_eligible", "analytical_admission"]].any().any()
    ):
        raise ValueError("whole-text/identity/negative-admission reconciliation failed")
    counts = views.groupby("context_id").size()
    if not contexts["context_id"].map(counts).fillna(0).eq(contexts["n_retained_views"]).all():
        raise ValueError("reader alternatives/context count reconciliation failed")
    return {
        "n_contexts": len(contexts), "n_source_views": len(views),
        "n_contexts_with_views": int(contexts["n_retained_views"].gt(0).sum()),
        "views_by_reader": dict(Counter(views["reader"])),
        "pdf_pages_by_reader": {
            reader: int(group["n_pages"].sum())
            for reader, group in views.loc[views["source_kind"].eq("original_pdf")].groupby(
                "reader"
            )
        },
        "whole_text_sha256_and_character_counts_verified": True,
        "reader_alternatives_are_not_additional_bills": True,
    }


def build_state(data_dir: Path, out_dir: Path, state: str, spec: dict) -> dict:
    packet = FrozenPacket(data_dir / spec["root"], spec)
    records = _records(packet, state, spec)
    source_table = packet.pin(spec["contexts"])
    context_rows, view_rows = [], []
    for context in records:
        date_observations = native_date_observations(state, context["source_record"])
        retained = [
            complete_view(packet, context, source)
            for source in _reader_inputs(packet, state, spec, context)
        ]
        for view in retained:
            view.update({
                "state": state,
                "source_record_locator": context["source_record_locator"],
                "source_table_path": str(packet.root / spec["contexts"]),
                "source_table_sha256": source_table["sha256"],
                "source_manifest_path": str(packet.root / "manifest.json"),
                "source_manifest_sha256": spec["manifest_sha256"],
                "negative_flags_json": _json(context["negative_flags"]),
                "native_date_observations_json": _json(date_observations),
                "native_date_observation_status": (
                    "separate_raw_publisher_observations_not_source_date_replacements"
                    if date_observations else "no_unambiguous_stored_date_field_selected"
                ),
            })
        view_rows.extend(retained)
        context_rows.append({
            key: value for key, value in context.items()
            if key not in {"source_record", "negative_flags", "available"}
        } | {
            "state": state,
            "status": (
                "selected_original_available_unadjudicated" if retained
                else "selected_original_unavailable_retained_gap"
            ),
            "original_source_record_json": _json(context["source_record"]),
            "source_record_sha256": _digest(_json(context["source_record"])),
            "source_table_path": str(packet.root / spec["contexts"]),
            "source_table_sha256": source_table["sha256"],
            "canonical_crosswalk_path": str(packet.root / spec["canonical"]),
            "canonical_crosswalk_sha256": packet.pin(spec["canonical"])["sha256"],
            "source_manifest_path": str(packet.root / "manifest.json"),
            "source_manifest_sha256": spec["manifest_sha256"],
            "negative_flags_json": _json(context["negative_flags"]),
            "native_date_observations_json": _json(date_observations),
            "native_date_observation_status": (
                "separate_raw_publisher_observations_not_source_date_replacements"
                if date_observations else "no_unambiguous_stored_date_field_selected"
            ),
            "n_retained_views": len(retained),
            "full_source_text_available": bool(retained),
            "identity_basis": "explicit_frozen_canonical_crosswalk_and_native_original_linkage",
            "native_identity_certified": False,
            "approved": False,
            "policy_eligible": False,
            "analytical_admission": False,
            "training_admission": False,
        })
    contexts, views = pd.DataFrame(context_rows), pd.DataFrame(view_rows)
    summary = reconcile_tables(contexts, views)
    if (len(contexts), len(views)) != (spec["expected_contexts"], spec["expected_views"]):
        raise ValueError(f"{state}: bounded accepted population mismatch")
    if contexts["canonical_bill_id"].duplicated().any():
        raise ValueError("alternative contexts would duplicate canonical bills")
    out_dir.mkdir(parents=True, exist_ok=False)
    contexts.to_parquet(out_dir / "context_inventory.parquet", index=False)
    views.to_parquet(out_dir / "source_view_inputs.parquet", index=False)
    if reconcile_tables(
        pd.read_parquet(out_dir / "context_inventory.parquet"),
        pd.read_parquet(out_dir / "source_view_inputs.parquet"),
    ) != summary:
        raise ValueError("persisted table reconciliation failed")
    manifest = {
        "schema_version": 1,
        "state": state,
        "status": "complete_bounded_initial_original_index_not_census_or_admission",
        "created_at": utc_now_iso(),
        "profile": "views",
        "context_population": "bounded_accepted_selected_original_contexts_including_selected_gaps",
        "accepted_listed_identities_not_indexed_population": spec["accepted_listed_identities"],
        "source_packet_root": str(packet.root),
        "source_manifest_sha256": spec["manifest_sha256"],
        "counts": summary,
        "limitations": spec["limitations"],
        "native_date_observations": {
            "column": "native_date_observations_json",
            "representation": "raw values with exact per-record source_field and basis",
            "normalized_or_used_as_window_evidence": False,
            "n_contexts_with_observations": int(
                contexts["native_date_observation_status"].eq(
                    "separate_raw_publisher_observations_not_source_date_replacements"
                ).sum()
            ),
        },
        "new_requests": 0,
        "fresh_pdf_extractions": 0,
        "labels_created": 0,
        "model_or_tokenizer_loaded": False,
        "analytical_admission": False,
        "default_admission": False,
        "files": {
            name: {"sha256": sha256_file(out_dir / name), "bytes": (out_dir / name).stat().st_size}
            for name in ("context_inventory.parquet", "source_view_inputs.parquet")
        },
        "source_stability": packet.stable(),
    }
    (out_dir / "manifest.json").write_text(_json(manifest) + "\n", encoding="utf-8")
    return manifest


def build_indexes(data_dir: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=False)
    code_before = _snapshot(Path(__file__))
    manifests = {
        state: build_state(data_dir, out_dir / state, state, spec)
        for state, spec in PROFILES.items()
    }
    code_after = _snapshot(Path(__file__))
    if code_before != code_after:
        raise ValueError("index builder changed during execution")
    result = {
        "status": "complete_four_bounded_initial_source_indexes",
        "created_at": utc_now_iso(),
        "builder_before": code_before,
        "builder_after": code_after,
        "new_requests": 0,
        "analytical_admission": False,
        "states": {state: manifest["counts"] for state, manifest in manifests.items()},
        "files": {
            f"{state}/manifest.json": sha256_file(out_dir / state / "manifest.json")
            for state in manifests
        },
    }
    (out_dir / "manifest.json").write_text(_json(result) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_indexes(args.data_dir, args.out_dir), indent=2))


if __name__ == "__main__":
    main()

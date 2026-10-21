"""Index selected, accepted initial originals offline; never collect or reread PDFs.

The context population is deliberately bounded to the accepted selections, not the
publisher-listed population. Reader alternatives remain complete, separate views.
Run with ``python -I -B -m state_politics.bills.study_partial_native --out-dir ...``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
    "AZ": {
        "root": "arizona-2023-2024-native-source-recovery-v2",
        "manifest_sha256": "572b9f31948b7ca736b2280dc6659f3ca3feeaf19ef22d3964eca05b1f24c007",
        "manifest_members": "files",
        "contexts": "derived/recovery.json",
        "canonical": "derived/canonical.json",
        "expected_contexts": 4,
        "expected_views": 9,
        "accepted_listed_identities": None,
        "limitations": [
            "Four canonical-linked original contexts, not an established native census.",
            "Four PDFs and one original HTML projection; listing HTML is not bill text.",
            "Publisher HTML original-link proof and acquisition history remain unresolved.",
            "Canonical session/identifier linkage is not a certified native identity.",
        ],
    },
    "KS": {
        "root": "kansas-2023-2024-native-source-recovery-v1-r2",
        "manifest_sha256": "abb9c65dc9167f5b20844d7c8d2d1b2e5decd32a65cff9d30c8a7477b9ecf138",
        "manifest_members": None,
        "contexts": "derived/selected_native_contexts.json",
        "canonical": "derived/canonical_regular_rows.jsonl",
        "expected_contexts": 12,
        "expected_views": 15,
        "accepted_listed_identities": 1558,
        "limitations": [
            "Twelve selected contexts contain seven introduced PDFs and one HTML alternative.",
            "Five selected originals lack an introduced PDF link and remain explicit gaps.",
            "Journal PDFs are excluded; their pages are not introduced-bill text.",
            "SR 1742 remains a canonical nonmatch; unrecorded historical requests remain unknown.",
        ],
    },
    "OR": {
        "root": "oregon-2023-2024-native-source-recovery-v2",
        "manifest_sha256": "1ea8f41976e302c2885c8d2a3a74f33d9169c42c3cef75b354938fd244a1b48a",
        "manifest_members": "files",
        "contexts": "derived/recoveries.json",
        "canonical": "derived/canonical.json",
        "expected_contexts": 32,
        "expected_views": 64,
        "accepted_listed_identities": 3263,
        "limitations": [
            "Only 32 selected introduced PDFs are indexed, including two special-session contexts.",
            "The 93 stored HTML responses are listings/version controls, not original bill bodies.",
            "Current listed identities are not a historical introduced-universe certification.",
            "Boundaries, request history and full-source pacing admission remain unresolved.",
        ],
    },
    "VA": {
        "root": "virginia-2023-2024-native-source-recovery-v1",
        "manifest_sha256": "d1c6f9b1a4fb8d3003a399f91ddbb0ccd756d47d2dbbcb2a8981de0753e877a5",
        "manifest_members": "inventory",
        "contexts": "derived/original_contexts.json",
        "canonical": "derived/canonical_regular_rows.json",
        "expected_contexts": 12,
        "expected_views": 16,
        "accepted_listed_identities": 6458,
        "limitations": [
            "Twelve original HTML contexts and two PDF alternatives are bounded selections.",
            "All stored main-source HTML text is retained, without claiming browser rendering.",
            "166 canonical-only 2023 contexts and 6,446 native originals remain unrecovered.",
            "Introduced observations do not establish the complete carryover/pending universe.",
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
        members = (
            manifest[spec["manifest_members"]] if spec["manifest_members"] else manifest
        )
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
    if state == "AZ":
        return value["bills"]
    if state == "OR":
        return [entry["row"] for entry in value["rows"]]
    return value["canonical_rows"] if state == "MN" else value


def _records(packet: FrozenPacket, state: str, spec: dict) -> list[dict]:
    """Small schema selectors feed the same context/view builder."""
    raw = packet.read(spec["contexts"])
    canonical = _canonical_rows(packet, state, spec)
    by_id = {row["bill_id"]: row for row in canonical}
    if len(by_id) != len(canonical):
        raise ValueError("nonunique frozen canonical identity")
    if state in {"AZ", "KS", "OR", "VA"}:
        return _additional_records(packet, state, spec, raw, canonical)
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


def _additional_records(packet, state, spec, raw, canonical):
    """Use saved crosswalks, never derive a session or identifier from a URL."""
    rows = []
    by_id = {row["bill_id"]: row for row in canonical}
    if state == "AZ":
        selected = packet.read("derived/selection.json")["selected"]
    elif state == "KS":
        originals = packet.read("derived/introduced_contexts.json")
        gaps = packet.read("derived/original_context_gaps.json")
        html = packet.read("derived/html_original_contexts.json")
    elif state == "OR":
        selected = packet.read("derived/selections.json")
        natives = packet.read("derived/native_rows.json")
        joins = packet.read("derived/joins.json")
        indexed = {
            entry["canonical_row"]: entry["row"]
            for entry in packet.read(spec["canonical"])["rows"]
        }
    for index, row in enumerate(raw):
        linkage = {}
        if state == "AZ":
            selection = _one(
                [item for item in selected if item["typed_key"] == row["typed_key"]],
                "Arizona accepted selection",
            )
            bill = by_id[row["canonical_version"]["bill_id"]]
            if bill != selection["canonical_bill"] or any(
                link["bill_id"] != bill["bill_id"] for link in row["canonical_links"]
            ):
                raise ValueError("Arizona canonical original-link disagreement")
            context_id = _one(
                [link["url"] for link in row["canonical_links"]
                 if link["media_type"] == "application/pdf"],
                "Arizona canonical original PDF",
            )
            native_identifier = native_session = None
            available = row["substantive_original_retained"] is True
            flags = [
                "native_listing_identity_not_established",
                "publisher_html_original_link_not_proven",
                "native_introduced_population_unknown",
            ]
            linkage = {"selection": selection}
        elif state == "KS":
            bill = _one(
                [item for item in canonical if item["identifier"] == row["identifier"]],
                "Kansas frozen exact identifier/session crosswalk",
            )
            original = [item for item in originals if item["identifier"] == row["identifier"]]
            gap = [item for item in gaps if item["identifier"] == row["identifier"]]
            if len(original) + len(gap) != 1:
                raise ValueError("Kansas selected original/gap disagreement")
            context_id, native_identifier = row["detail_path"], row["formal_identifier_literal"]
            native_session = row["session_label"]
            available = bool(original)
            flags = ["current_listing_not_historical_introduced_census"]
            if not available:
                flags.append("selected_original_unavailable_no_introduced_pdf_link")
            linkage = {
                "original": original[0] if original else None,
                "gap": gap[0] if gap else None,
                "html_originals": [
                    item for item in html if item["identifier"] == row["identifier"]
                ],
            }
        elif state == "OR":
            selection = _one(
                [item for item in selected if item["selection"] == row["selection"]],
                "Oregon accepted selection",
            )
            native = natives[selection["native_row"]]
            if selection["identity"] != row["identity"] or native["identity"] != row["identity"]:
                raise ValueError("Oregon selected/native identity disagreement")
            join = _one(
                [item for item in joins
                 if item["identity"] == {
                     key: row["identity"][key]
                     for key in ("session", "chamber", "measure_type", "measure_number")
                 }],
                "Oregon native/canonical join",
            )
            if selection["native_row"] not in join["native_rows"]:
                raise ValueError("Oregon native/canonical row disagreement")
            bill = indexed[_one(join["canonical_rows"], "Oregon canonical row")]
            context_id, native_identifier = selection["version_url"], native["label"]
            native_session = row["identity"]["session"]
            available = row["original_proof"] is True
            flags = ["current_listing_not_historical_introduced_census"]
            if join["special"]:
                flags.append("special_session_context_not_regular_cohort")
            linkage = {"selection": selection, "native": native, "join": join}
        else:
            bill = _one(
                [item for item in canonical
                 if item["native_comparison_key"] == [
                     row["native_session"], row["native_identifier"]
                 ] and row["population_index"] in item["official_population_indices"]],
                "Virginia saved exact native/canonical crosswalk",
            )
            context_id, native_identifier = row["detail_url"], row["native_identifier"]
            native_session = row["native_session"]
            available = row["source_status"] == "recovered-original-context-not-classified"
            flags = ["carryover_pending_universe_not_certified"]
        if bill.get("state") != state:
            raise ValueError("canonical cross-state disagreement")
        rows.append({
            "context_id": context_id, "identifier": bill["identifier"],
            "native_identifier": native_identifier,
            "session_identifier": bill["session_identifier"],
            "native_session_identifier": native_session,
            "canonical_bill_id": bill["bill_id"],
            "source_record": row, "source_record_locator": str(index),
            "source_linkage_metadata_json": _json(linkage),
            "available": available, "negative_flags": flags,
            "identity_basis": (
                "frozen_canonical_original_links_native_listing_and_publisher_linkage_unproven"
                if state == "AZ"
                else "explicit_frozen_canonical_crosswalk_and_native_original_linkage"
            ),
        })
    return rows


def _reader_inputs(packet: FrozenPacket, state: str, spec: dict, context: dict):
    row = context["source_record"]
    if not context["available"]:
        return
    if state in {"AZ", "KS", "OR", "VA"}:
        for source in _additional_inputs(packet, state, context):
            segments = source["segments"]
            reason = None
            if not source.get("stored_complete", True) or not segments or any(
                not isinstance(segment, str) for segment in segments
            ):
                reason = "stored_projection_truncated_or_missing_pages"
            elif not re.search(
                r"(?:be\s+it\s+(?:enacted|resolved)|resolved|whereas|section\s+\d+)",
                "".join(segments), re.IGNORECASE,
            ):
                reason = "stored_projection_header_only_or_no_substantive_body_marker"
            if reason:
                exclusion = {
                    key: source[key] for key in (
                        "reader", "source_reader", "extraction_path",
                        "extraction_selector", "source_path", "source_url",
                    )
                } | {
                    "reason": reason,
                    "extraction_sha256": packet.pin(source["extraction_path"])["sha256"],
                    "original_source_sha256": packet.pin(source["source_path"])["sha256"],
                }
                context.setdefault("excluded_source_views", []).append(exclusion)
                if reason not in context["negative_flags"]:
                    context["negative_flags"].append(reason)
                continue
            yield source
    elif state == "MI":
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


def _pdf_inputs(name, source_path, source_url, source_sha256, readers, n_pages, page_key):
    for source_reader, reader, pages in readers:
        strings = [page.get("text") for page in pages]
        yield {
            "reader": reader, "source_reader": source_reader, "segments": strings,
            "extraction_path": name,
            "extraction_selector": f"{source_reader}/pages/*/text",
            "source_path": source_path, "source_url": source_url,
            "source_sha256": source_sha256, "n_pages": len(pages), "kind": "original_pdf",
            "stored_complete": (
                len(pages) == n_pages
                and [page.get(page_key) for page in pages] == list(range(1, n_pages + 1))
                and not any(page.get("truncated") or page.get("header_only") for page in pages)
            ),
        }


def _additional_inputs(packet, state, context):
    row = context["source_record"]
    if state == "AZ":
        for exchange in row["original_exchanges"]:
            link = _one(
                [link for link in row["canonical_links"] if link["url"] == exchange["url"]],
                "Arizona saved original exchange/link",
            )
            pdf = link["media_type"] == "application/pdf"
            if not pdf and link["media_type"] != "text/html":
                raise ValueError("Arizona unrecognized original media type")
            name = f"derived/{exchange['exchange_id']}.{'pdf' if pdf else 'html'}.json"
            projection = packet.read(name)
            common = {
                "extraction_path": name, "source_path": exchange["body_path"],
                "source_url": exchange["url"], "source_sha256": exchange["body_sha256"],
                "stored_complete": (
                    exchange["complete"] is True and exchange["http_status"] == 200
                    and exchange["curl_returncode"] == 0
                ),
            }
            if pdf:
                for reader in ("pymupdf", "pypdf"):
                    pages = projection[f"{reader}_pages"]
                    yield {
                        **common, "reader": reader, "source_reader": reader,
                        "segments": pages, "extraction_selector": f"{reader}_pages/*",
                        "n_pages": len(pages), "kind": "original_pdf",
                        "stored_complete": (
                            common["stored_complete"]
                            and len(pages) == projection[f"{reader}_page_count"]
                            and not projection["page_count_discrepancy"]
                        ),
                    }
            else:
                yield {
                    **common, "reader": "html_full_projection",
                    "source_reader": "stored_visible_literal_data_projection",
                    "segments": [projection["visible_literal_data_projection"]],
                    "extraction_selector": "visible_literal_data_projection",
                    "n_pages": None, "kind": "original_html",
                }
    elif state == "KS":
        linkage = json.loads(context["source_linkage_metadata_json"])
        original = linkage["original"]
        exchange = original["original_exchange"]
        name = f"derived/pdf/{exchange:03}.json"
        projection = packet.read(name)
        response = packet.read(f"raw/{exchange:03}/result.json")
        for source in _pdf_inputs(
            name, f"raw/{exchange:03}/body.bin", original["original_url"],
            response["body_sha256"],
            [(reader, "pymupdf" if reader == "fitz" else reader, projection[reader]["pages"])
             for reader in ("fitz", "pypdf")],
            len(projection["fitz"]["pages"]), "number",
        ):
            yield source
        for html in linkage["html_originals"]:
            exchange = html["exchange"]
            name = f"derived/document_html/{exchange:03}.json"
            projection = packet.read(name)
            segments = [segment["text"] for segment in projection["segments"]]
            if "".join(segments) != projection["text"]:
                raise ValueError("Kansas saved HTML segment/text disagreement")
            yield {
                "reader": "html_full_projection",
                "source_reader": "stored_document_html_segments",
                "segments": segments, "extraction_path": name,
                "extraction_selector": "segments/*/text",
                "source_path": f"raw/{exchange:03}/body.bin", "source_url": html["url"],
                "source_sha256": packet.read(f"raw/{exchange:03}/result.json")["body_sha256"],
                "n_pages": None, "kind": "original_html",
            }
    elif state == "OR":
        pdfs = packet.read("derived/pdfs.json")
        for proof in row["proof"]:
            projection = _one(
                [item for item in pdfs if item["exchange"] == proof["pdf_exchange"]],
                "Oregon accepted introduced PDF",
            )
            if (
                projection["identity"] != row["identity"]
                or projection["version"] != "Introduced"
                or projection["url"] != proof["link"]["url"]
            ):
                raise ValueError("Oregon original proof/projection disagreement")
            for source in _pdf_inputs(
                "derived/pdfs.json", f"transport/{projection['exchange']:03}.body",
                projection["url"], projection["body_sha256"],
                [(reader, reader, projection["pages"][reader])
                 for reader in ("pymupdf", "pypdf")],
                projection["page_count"], "page",
            ):
                source["extraction_selector"] = (
                    f"{pdfs.index(projection)}/pages/{source['source_reader']}/*/text"
                )
                yield source
    else:
        yield {
            "reader": "html_full_projection", "source_reader": "stored_exact_main_text",
            "segments": [row["exact_main_text"]],
            "extraction_path": "derived/original_contexts.json",
            "extraction_selector": f"{context['source_record_locator']}/exact_main_text",
            "source_path": row["html_artifact"],
            "source_url": row["introduced_link"]["url"], "source_sha256": None,
            "n_pages": None, "kind": "original_html",
        }
        if row.get("pdf_transport_id") is not None:
            name = "derived/pdf_pages.json"
            pages = packet.read(name)
            selected = [
                page for page in pages if page["transport_id"] == row["pdf_transport_id"]
            ]
            if any(
                (page["native_session"], page["native_identifier"]) != (
                    row["native_session"], row["native_identifier"]
                ) for page in selected
            ):
                raise ValueError("Virginia PDF/context disagreement")
            for source in _pdf_inputs(
                name, f"transport/{row['pdf_transport_id']:03}.body",
                _one(
                    [response["url"] for response in packet.read(
                        "derived/response_classifications.json"
                    ) if response["transport_id"] == row["pdf_transport_id"]],
                    "Virginia stored PDF URL",
                ),
                None,
                [(reader, reader, [
                    {"page_number": page["page_number"], "text": page[f"{reader}_text"]}
                    for page in selected
                ]) for reader in ("pymupdf", "pypdf")],
                row["pdf_page_count"], "page_number",
            ):
                source["extraction_selector"] = (
                    f"transport_id={row['pdf_transport_id']}/*/{source['source_reader']}_text"
                )
                yield source


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
    elif state == "VA":
        for kind in ("offered", "prefiled"):
            observation = row["printed_observations"].get(kind)
            if observation:
                observations.append({
                    "event_kind": kind,
                    "raw_value": observation["raw"],
                    "source_field": f"printed_observations/{kind}/raw",
                    "basis": "saved printed original main-source date literal, not session year",
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
        or not views["raw_text_sha256"].eq(views["input_sha256"]).all()
        or not views["text"].str.len().eq(views["n_input_characters"]).all()
        or views["text"].str.strip().eq("").any()
        or views[[
            "approved", "policy_eligible", "analytical_admission", "training_admission"
        ]].any().any()
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
            if key not in {"source_record", "negative_flags", "available", "excluded_source_views"}
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
            "excluded_source_views_json": _json(context.get("excluded_source_views", [])),
            "native_date_observations_json": _json(date_observations),
            "native_date_observation_status": (
                "separate_raw_publisher_observations_not_source_date_replacements"
                if date_observations else "no_unambiguous_stored_date_field_selected"
            ),
            "n_retained_views": len(retained),
            "full_source_text_available": bool(retained),
            "identity_basis": context.get(
                "identity_basis", "explicit_frozen_canonical_crosswalk_and_native_original_linkage"
            ),
            "native_identity_certified": False,
            "approved": False,
            "policy_eligible": False,
            "analytical_admission": False,
            "training_admission": False,
        })
    contexts, views = pd.DataFrame(context_rows), pd.DataFrame(view_rows)
    if not view_rows:
        views = pd.DataFrame(columns=[
            "view_id", "context_id", "reader", "source_reader", "input_sha256",
            "raw_text_sha256", "n_input_characters", "text", "source_kind", "n_pages",
            "source_url", "original_source_path", "original_source_sha256",
            "extraction_path", "extraction_sha256", "extraction_selector",
            "source_record_sha256", "segment_character_counts_json", "segment_text_sha256s_json",
            "text_assembly", "full_source_text_available", "approved", "policy_eligible",
            "analytical_admission", "training_admission", "state", "source_record_locator",
            "source_table_path", "source_table_sha256", "source_manifest_path",
            "source_manifest_sha256", "negative_flags_json", "native_date_observations_json",
            "native_date_observation_status",
        ])
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
        "n_excluded_source_views": sum(
            len(json.loads(value)) for value in contexts["excluded_source_views_json"]
        ),
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
        "status": "complete_eight_bounded_initial_source_indexes",
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

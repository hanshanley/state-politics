"""Normalize complete, already-stored campaign projections without extraction.

These are bounded, unapproved retained-source inputs, not campaign completion,
native censuses, legal-version findings, or filing-window admission. No collector
or PDF reader is imported. Existing full-text files are exported byte-for-byte;
Pennsylvania's stored page streams are concatenated without adding characters.
Use --states TX WA MT NM UT OK WV for the independent retained supplement;
omitting --states preserves the original MO/NY/IL/PA batch. Source-only history,
drafts, quarantined documents and partial projections never imply original-policy
coverage or target-cycle admission. Existing output directories are never rebuilt.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from ..provenance import sha256_file, utc_now_iso
from .study_sources import _unique
from .study_window import _snapshot

PROFILES = {
    "MO": {
        "root": "missouri-2023-2024-v4-stopped-prefix-recovery-readiness-v1",
        "prefix": "recovered_private_prefix",
        "manifest_sha256": "ad387aa6ac42a2a16878d7427d5efa2581739c680a1ceee978f1e7314fdc983d",
        "receipt": "missouri_returned_packets_parent_actual_v1.json",
        "receipt_sha256": "77bf0b181899d943066db90d6fd4f4ea476bb50262623b20b65c33fd588e2ac5",
        "expected_complete_contexts": 1152,
        "campaign_pending_not_certified": 3808,
        "limitations": [
            "Only 1,152 accepted reconstructed candidate records are indexed, not 4,960 contexts.",
            "All 1,152 original printed-identity negatives remain; header supplements do not "
            "certify identity, printed years, filing time, or legal version.",
            "The original checkpoint-context failure remains unexplained; no resume or seal.",
        ],
    },
    "NY": {
        "root": "ny-full-source-campaign-v1",
        "receipt": "ny_genuine_preseal_parent_binding_actual_v1.json",
        "receipt_sha256": "6499b25c9e951290886588c4b6160576cc189bdbcba4b794b70e2347775d8912",
        "document_evidence": "ny_genuine_preseal_6_1_sol_v1_documents.jsonl",
        "document_evidence_sha256": (
            "ed97ed1fdfd77fc69d674d46577837a6ee3e46fa88a5d85b870fc584a2fc23e0"
        ),
        "expected_complete_contexts": 24295,
        "limitations": [
            "Worker reconstruction of 24,295 PDFs is accepted only as bound retained evidence.",
            "A 255 was cancelled then started/completed under the same request ID; lifecycle "
            "acceptance remains blocked. Historical concurrent status execution does not "
            "identify an exclusive cancellation writer.",
            "The final 43-candidate tail is unsealed; no full-source or campaign closure.",
            "Reader disagreement, publisher census uncertainty and acquisition restrictions "
            "remain unapproved. Base-print URLs do not certify introduced legal versions.",
        ],
    },
    "IL": {
        "root": "illinois-full-source-campaign-v3",
        "receipt": "il_v3_actual_stopped_prefix_parent_reinspection_actual_v1.json",
        "receipt_sha256": "653fb2cc51d4e032b271e3773ccc000864d961faf4988229df4bb9fef29c574d",
        "expected_complete_contexts": 10700,
        "campaign_pending_not_certified": 1925,
        "limitations": [
            "Stopped-prefix reconstruction only: 1,925 pending and two terminal partials remain.",
            "Five curl exit-7 connection failures triggered the stop; their origin is unknown.",
            "Unavailable HTML shells are not complete bill-text projections.",
            "Synthetic INSERT/DELETE rendering is a stored collector convention, not certified "
            "legislative semantics. Identity negatives and publisher census gaps remain.",
            "No safe blind restart, genuine completion seal, or full-campaign acceptance.",
        ],
    },
    "PA": {
        "root": "pennsylvania-full-original-actual-stopped-prefix-inspection-v1",
        "prefix": "stopped_root_copy",
        "manifest_sha256": "076a32cdc010b06015c21e1eb3e679116fb2540f31fdd12fd4ee2072ddd743c3",
        "receipt": "parent_evidence/pa_genuine_v2_actual_checkpoint_stop_parent_v1.json",
        "receipt_sha256": "a47cd40f11559bdb25360870edf97bdf5697d034f44bb125645326c67961a7a8",
        "receipt_in_packet": True,
        "limitations": [
            "62 genuine initial seeds plus the actual stopped prefix, not a full campaign.",
            "The collector stopped on a noncontiguous checkpoint buffer; no repair or resume.",
            "98 newly complete, ten incomplete and 4,616 pending were retained at the stop.",
            "Historical exchange-budget excess and missing redirect bodies remain unresolved.",
            "Decoded HTML markup is preserved separately from complete stored reader text.",
        ],
    },
}
LEGACY_STATES = tuple(PROFILES)
SUPPLEMENT_PACKETS = {
    "TX": {
        "body": ("texas-native-body-input-inventory-v2",
                 "3806bfabb926e03d23dd612eaf493b94d9aee39d516281a5ffe011cf3d03f9ba"),
        "initial": ("texas-official-parallel-recovery-v3",
                    "c0376c019d06084ec1cf74406d3e7095e90bb493f8aff480994f17b87c9eb9ba"),
        "campaign": ("texas-full-source-campaign-v1", None),
    },
    "WA": {
        "text": ("washington-original-document-text-v1",
                 "1843d908a3a93d74fd1f3cc8745482bea18a038142cc006fc6159e9ac22950c4"),
        "alternate": ("washington-resolution-version-note-review-v1",
                      "c519ad5c88c59ef974786b0cd5b0c682ddfb65cdcf5d5ecd99ce7dc14b474079"),
        "originals": ("washington-resolution-alternate-document-recovery-v1",
                      "2fa2355527cb2d25b1e92fc844f3e00eeb5c5c6e69dbf0836612f872cba75ffe"),
    },
    "MT": {
        "native": ("montana-native-universe-reconciliation-v1",
                   "0e922cfdbdfca5c50315fd2c184498fca40a999e0ebfc226536dc52dc34b07d7"),
        "conflicts": ("montana-native-print-identity-conflicts-v1",
                      "0bf1e4245f89c0cbb0d6d414fa027a69f8d5b51dd1eecd18aab40baa9bfbd7e0"),
        "history": ("montana-official-history-census-v2",
                    "b2f8caef475230a775f4ab8e0992f3c6dcaa8f611993e41615df3a38dc2f2ef6"),
    },
    "NM": {
        "text": ("new-mexico-encoded-reference-review-v1",
                 "1f4a9534cee09411816309c2fb18ea09ed614c5f39668038bf1a66df682c920f"),
        "ocr": ("new-mexico-hb99-context-ocr-v1",
                "04017acea74072587c6b9f15f40f8beeb9dc50670ee1695015741920f3889975"),
    },
    "UT": {
        "originals": ("utah-2023-2024-native-source-recovery-v1",
                      "b4ab9759d2785cea761d7bc9b3b1c5c11cc59d61bce31c8bf17068d7ae194803"),
    },
    "OK": {
        "review": ("bill-document-encoded-url-review-v1",
                   "e68a6b151f57cc25bf6aac8b3d2ac86b48296cf32ce0551991417ce3c0fb0222"),
    },
    "WV": {
        "review": ("bill-document-encoded-url-review-v1",
                   "e68a6b151f57cc25bf6aac8b3d2ac86b48296cf32ce0551991417ce3c0fb0222"),
    },
}
SUPPLEMENT_LIMITATIONS = {
    "TX": [
        "The 48-document first-batch body inventory is accepted retained evidence, not closure.",
        "Additional stored campaign strings are an explicitly pinned, unsealed observation; "
        "the earlier first-batch acceptance does not accept the continuation or final tail.",
        "HB 1 is an unavailable HTML shell; no PDF fallback is invented.",
        "Historical budget, collector lifecycle, final-15, source/census and legal-version "
        "closure remain unaccepted. Synthetic postexit fixtures are never inputs.",
    ],
    "WA": [
        "The 241 non-test recovery targets are a bounded multi-biennium cohort, not a census.",
        "All original-note retrieval failures and ten publisher-test contexts remain negative.",
        "SR 8601's substitute/plain-heading version conflict survives, as do styling loss, "
        "HB 2379 primary-sponsor and other metadata gaps; first readings are not filing dates.",
    ],
    "MT": [
        "Formal and LC draft source rows remain separate; aliases are not additional filings.",
        "Native metadata/history documents do not supply missing original policy bodies.",
        "The seven identity-conflict PDFs print 2025 and are ancillary, not 2023 originals.",
        "History volumes are source context, not policy text or inferred introduction dates.",
        "Native nonmatches, null formal identities and historical continuity remain unresolved.",
    ],
    "NM": [
        "All 87 references / 36 bills are retained, including later and unclassified versions.",
        "The two wrong-session Final Version attachments remain quarantined wrong documents.",
        "HB 99 embedded text is header-only; separate complete all-page OCR is a 2026 committee "
        "substitute/amendments-in-context projection, never exact introduced native text.",
        "Styling, OCR accuracy, native census, legal version and filing time remain uncertified.",
    ],
    "UT": [
        "Seven reconstructed original PDF/HTML pairs only; collection-policy acceptance withheld.",
        "Historical and aggregate exchanges are unknown, not zero; further HTTP unauthorized.",
        "The 895 substitute listings, special sessions, actual boundaries and statewide original "
        "policy coverage remain unresolved; neither stored reader is ground truth.",
    ],
    "OK": [
        "Bounded introduced-cover-only evidence remains partial despite an all-page stored "
        "projection; no complete original-policy-text or cycle coverage claim.",
    ],
    "WV": [
        "Bounded main-document-only DOCX projection remains partial, not a complete original "
        "policy document or statewide coverage finding.",
    ],
}
for _state, _packets in SUPPLEMENT_PACKETS.items():
    _root, _manifest = next(iter(_packets.values()))
    PROFILES[_state] = {
        "root": _root, "manifest_sha256": _manifest, "supplement": True,
        "receipt": "manifest.json", "receipt_sha256": _manifest, "receipt_in_packet": True,
        "limitations": SUPPLEMENT_LIMITATIONS[_state],
    }
PROFILES["UT"].update(
    receipt="utah_initial_packet_parent_actual_v1.json",
    receipt_sha256="a00943b271bf585114cb745fbb7df2cecb8e734c84f404d9e288953bcffce020",
    receipt_in_packet=False,
)
TX_SOURCE_PINS = {
    "mutable/population_dispositions.jsonl": (
        "8a373420d8cb749c295c5a5afc6a01fa7399d12d1cb4d65300af8f34d1de2d1c"
    ),
    "mutable/progress.json": "6b5416cb6419a0c87ab32df630c0f1ad10f03091efc0c06c3eebe0903eb3d25e",
    "contract/complete_accounted_population.jsonl": (
        "72b646d4774bab118eda2cc69e2c0de741d10410b0a066a0640a44e389c7f980"
    ),
}
FALSE_FLAGS = {
    name: False for name in (
        "approved", "native_identity_certified", "filing_time_certified",
        "version_identity_certified", "model_admission", "policy_eligible",
        "analytical_admission", "training_admission", "publication_admission",
        "scientific_admission", "identity_admission", "stage_admission", "filing_admission",
        "collection_policy_accepted",
    )
}
VIEW_COLUMNS = [
    "view_id", "context_id", "state", "identifier", "session_identifier", "canonical_bill_id",
    "reader", "source_reader", "text", "input_sha256", "raw_text_sha256",
    "n_input_characters", "n_input_utf8_bytes", "source_kind", "n_pages",
    "source_url", "original_source_path", "original_source_sha256",
    "extraction_path", "extraction_sha256", "extraction_selector",
    "segment_character_counts_json", "segment_utf8_byte_counts_json",
    "segment_text_sha256s_json", "segment_paths_json", "text_assembly",
    "source_record_sha256", "negative_flags_json", "native_date_observations_json",
    "full_source_text_available", *FALSE_FLAGS,
]


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stat(path: Path) -> dict:
    value = path.stat()
    return {
        key: getattr(value, f"st_{key}")
        for key in ("size", "mtime_ns", "ctime_ns", "dev", "ino", "nlink", "mode")
    }


class StoredSources:
    """Fingerprint consumed files only; never traverse campaign descendants."""

    def __init__(self, root: Path):
        if root.is_symlink():
            raise ValueError("symlink source root")
        self.root = root.resolve()
        self.before: dict[str, dict] = {}
        self.roles: dict[str, str] = {}
        self.members: dict | None = None

    def path(self, name: str) -> Path:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("source must be a relative packet member")
        path = self.root
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                raise ValueError("symlink source member")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("source escapes packet")
        return path

    def exists(self, name: str) -> bool:
        return self.path(name).is_file()

    def _bind(self, name: str, snapshot: dict, role: str) -> None:
        if not stat.S_ISREG(snapshot["mode"]):
            raise ValueError("source is not a regular file")
        if self.members is not None and name != "manifest.json":
            binding = self.members.get(name)
            expected = binding if isinstance(binding, str) else (binding or {}).get("sha256")
            if expected != snapshot["sha256"]:
                raise ValueError(f"unbound or changed frozen member: {name}")
            if isinstance(binding, dict):
                size = binding.get("bytes", binding.get("size"))
                if size is not None and size != snapshot["size"]:
                    raise ValueError(f"frozen source size mismatch: {name}")
        if name in self.before and snapshot != self.before[name]:
            raise ValueError(f"source changed: {name}")
        self.before[name] = snapshot
        self.roles[name] = role

    def read(self, name: str, *, role: str = "stored_projection") -> bytes:
        if name in self.before:
            raise ValueError(f"duplicate source data pass: {name}")
        path = self.path(name)
        before = _stat(path)
        data = path.read_bytes()
        if before != _stat(path):
            raise ValueError(f"source changed during read: {name}")
        self._bind(name, {
            "path": str(path), "sha256": hashlib.sha256(data).hexdigest(), **before,
        }, role)
        return data

    def json(self, name: str):
        return json.loads(self.read(name, role="source_metadata").decode("utf-8"))

    def jsonl(self, name: str) -> list[dict]:
        # Physical LF, not splitlines(): source strings can contain Unicode line separators.
        return [
            json.loads(line) for line in self.read(name, role="source_records").split(b"\n")
            if line
        ]

    def parquet(self, name: str) -> list[dict]:
        table = pd.read_parquet(io.BytesIO(self.read(name, role="source_records")))
        # Arrow lists and nullable scalars must retain JSON values, not reprs or NaN.
        return json.loads(table.to_json(orient="records", force_ascii=False))

    def pin(self, name: str, expected: str | None = None) -> dict:
        if name not in self.before:
            self._bind(name, _snapshot(self.path(name)), "source_original_hash_only")
        snapshot = self.before[name]
        if expected is not None and snapshot["sha256"] != expected:
            raise ValueError(f"source checksum mismatch: {name}")
        return snapshot

    def manifest(self, expected: str) -> None:
        value = self.json("manifest.json")
        if self.before["manifest.json"]["sha256"] != expected:
            raise ValueError("unaccepted retained-prefix manifest")
        members = value.get("files", value.get("members"))
        if members is None:
            raise ValueError("retained manifest has no member bindings")
        self.members = (
            members if isinstance(members, dict) else {row["path"]: row for row in members}
        )

    def finish(self, output: Path) -> dict:
        rows = []
        for name, before in self.before.items():
            after = _snapshot(self.path(name))
            if before != after:
                raise ValueError(f"consumed source changed: {name}")
            rows.append({
                "path": before["path"], "role": self.roles[name],
                "sha256_before": before["sha256"], "sha256_after": after["sha256"],
                "stat_before_json": _json({k: v for k, v in before.items() if k != "sha256"}),
                "stat_after_json": _json({k: v for k, v in after.items() if k != "sha256"}),
                "bytes": before["size"], "unchanged": True,
            })
        pd.DataFrame(rows).to_parquet(output, index=False)
        return {
            "files": len(rows), "bytes": sum(row["bytes"] for row in rows),
            "all_consumed_source_sha256_and_stat_before_after_equal": True,
            "scope": "consumed files only; not whole-source census or acquisition immutability",
            "normalization_data_passes_per_file": 1,
            "after_check": "independent SHA-256/stat rehash only; no second normalization pass",
        }


def date_observations(row: dict) -> list[dict]:
    """Keep literal explicit date fields, including action JSON, without interpretation."""
    result = []
    for key, value in row.items():
        if (
            (key.lower() == "date" or key.lower().endswith("_date")
             or key.lower().startswith("date_"))
            and value is not None
        ):
            result.append({"source_field": key, "raw_value": value, "normalized": False})
    if row.get("action_history_json"):
        result.append({
            "source_field": "action_history_json", "raw_value": row["action_history_json"],
            "normalized": False,
            "basis": "all stored publisher actions; not introduction inference",
        })
    return result


def explicit_source_statements(view: dict) -> list[dict]:
    """Retain literal event-word lines; never associate a nearby generic header date."""
    if view["source_kind"] == "original_html_markup":
        return []
    text = view["text"]
    statements = re.compile(
        r"^[ \t]*(?:[0-9]+[ \t]+)?\[?(?P<verb>introduced|filed)\b(?P<rest>[^\r\n\f]*)",
        re.IGNORECASE | re.MULTILINE,
    )
    literal_dates = re.compile(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)\.?[ \t]+[0-9]{1,2},?[ \t]+[0-9]{4}\b"
        r"|\b[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}\b|\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b",
        re.IGNORECASE,
    )
    result = []
    for match in statements.finditer(text):
        dates = []
        for date in literal_dates.finditer(match.group("rest")):
            start = match.start("rest") + date.start()
            end = match.start("rest") + date.end()
            dates.append({"raw_value": text[start:end], "span_start": start, "span_end": end})
        result.append({
            "source_field": view.get("source_field", "source_view_inputs.text"),
            "source_view_id": view["view_id"], "source_input_sha256": view["input_sha256"],
            "extraction_path": view.get("extraction_path"),
            "extraction_selector": view.get("extraction_selector"),
            "event_kind": "literal_event_word_statement_unadjudicated",
            "literal_event_word": match.group("verb"), "raw_value": match.group(),
            "span_start": match.start(), "span_end": match.end(),
            "utf8_byte_start": len(text[:match.start()].encode("utf-8")),
            "utf8_byte_end": len(text[:match.end()].encode("utf-8")),
            "raw_dates_on_same_event_line": dates,
            "date_status": "literal_date_on_same_event_line_not_certified" if dates else (
                "no_explicit_date_on_same_event_line"
            ),
            "basis": "exact stored physical-line span, not header/date proximity inference",
            "normalized": False, "filing_time_certified": False,
            "event_identity_certified": False, "used_as_window_evidence": False,
        })
    return result


def retain_source_date_observations(context: dict, views: list[dict]) -> dict:
    """Annotate existing complete strings in memory, retaining all reader alternatives."""
    base = [
        {
            **observation, "source_path": context.get("source_table_path"),
            "source_record_locator": context.get("source_record_locator"),
        } for observation in json.loads(context["native_date_observations_json"])
        if observation.get("source_field") != "source_view_inputs.text"
    ]
    combined = list(base)
    for view in views:
        observations = explicit_source_statements(view)
        view["native_date_observations_json"] = _json(base + observations)
        combined.extend(observations)
    if context.get("partial_stored_projection_json"):
        partial = json.loads(context["partial_stored_projection_json"])
        combined.extend(explicit_source_statements({
            "text": partial["text"], "view_id": None,
            "input_sha256": partial["sha256"], "source_kind": "partial_stored_projection",
            "source_field": "partial_stored_projection_json.text",
            "extraction_path": partial["source_path"],
            "extraction_selector": "entire stored partial string; not a complete source view",
        }))
    context["native_date_observations_json"] = _json(combined)
    return {
        "literal_statement_spans": len(combined) - len(base),
        "literal_statement_spans_with_same_line_dates": sum(
            bool(observation.get("raw_dates_on_same_event_line")) for observation in combined
        ),
        "dates_normalized_or_used_for_admission": False,
    }


def complete_projection(
    sources: StoredSources, context: dict, *, reader: str, paths: list[str],
    original: str, original_sha256: str, source_url: str | None,
    n_pages: int | None, source_kind: str, segment_bindings: list[dict] | None = None,
    stored_segments: list[str] | None = None, extraction_selector: str | None = None,
    original_sources: StoredSources | None = None,
) -> dict:
    if not paths:
        raise ValueError("no complete stored projection")
    segments = (
        [sources.read(name).decode("utf-8") for name in paths]
        if stored_segments is None else stored_segments
    )
    if len(segments) != len(paths) or any(name not in sources.before for name in paths):
        raise ValueError("inline projection must be bound to consumed stored records")
    if segment_bindings is not None:
        if len(segment_bindings) != len(segments):
            raise ValueError("incomplete stored page stream")
        for index, (segment, binding) in enumerate(zip(segments, segment_bindings, strict=True), 1):
            if (
                binding["page"] != index or binding["characters"] != len(segment)
                or binding["sha256"] != _digest(segment)
            ):
                raise ValueError("stored page number/hash/length mismatch")
    text = "".join(segments)
    if not text.strip():
        raise ValueError("empty projection is not complete source text")
    original_binding = (original_sources or sources).pin(original, original_sha256)
    return {
        **{key: context[key] for key in (
            "context_id", "state", "identifier", "session_identifier", "canonical_bill_id",
            "source_record_sha256", "negative_flags_json", "native_date_observations_json",
        )},
        "view_id": f"{context['context_id']}::{reader}",
        "reader": reader, "source_reader": reader,
        "text": text, "input_sha256": _digest(text), "raw_text_sha256": _digest(text),
        "n_input_characters": len(text), "n_input_utf8_bytes": len(text.encode("utf-8")),
        "source_kind": source_kind, "n_pages": n_pages, "source_url": source_url,
        "original_source_path": original_binding["path"],
        "original_source_sha256": original_binding["sha256"],
        "extraction_path": str(sources.path(paths[0])),
        "extraction_sha256": sources.before[paths[0]]["sha256"],
        "extraction_selector": extraction_selector or (
            "entire UTF-8 file" if len(paths) == 1 else "all listed page files"
        ),
        "segment_paths_json": _json([str(sources.path(name)) for name in paths]),
        "segment_character_counts_json": _json([len(segment) for segment in segments]),
        "segment_utf8_byte_counts_json": _json([len(s.encode("utf-8")) for s in segments]),
        "segment_text_sha256s_json": _json([_digest(segment) for segment in segments]),
        "text_assembly": "all_stored_segments_in_order_no_added_characters",
        "full_source_text_available": True, **FALSE_FLAGS,
    }


def _context(state: str, row: dict, locator: str, record_path: str) -> dict:
    canonical = row.get("canonical_bill_ids", [])
    return {
        "state": state, "context_id": f"{state}::{locator}",
        "identifier": row.get("identifier"), "native_identifier": row.get("identifier"),
        "session_identifier": row.get("session_identifier"),
        "native_session_identifier": row.get(
            "session_identifier",
            str(row["general_assembly"]) if "general_assembly" in row else None,
        ),
        "canonical_bill_id": canonical[0] if len(canonical) == 1 else row.get("bill_id"),
        "canonical_bill_ids_json": _json(canonical),
        "original_source_record_json": _json(row), "source_record_sha256": _digest(_json(row)),
        "source_record_locator": locator, "source_table_path": record_path,
        "source_status": row.get("state", row.get("status", "unknown")),
        "native_date_observations_json": _json(date_observations(row)),
        "native_date_observation_status": "raw_stored_observations_not_filing_window_admission",
        "negative_flags_json": "[]", **FALSE_FLAGS,
    }


def _mo_records(sources: StoredSources, prefix: str):
    directory = sources.path(f"{prefix}/candidates")
    for path in sorted(directory.iterdir()):
        if path.suffix != ".json" or not path.is_file():
            raise ValueError("unexpected candidate entry")
        name = path.relative_to(sources.root).as_posix()
        row = sources.json(name)
        context = _context("MO", row, row["raw_context_id"], str(path))
        context["negative_flags_json"] = _json([
            "stopped_prefix_not_full_campaign", "original_printed_identity_flag_false",
            "printed_session_year_not_inferred", "publisher_census_not_certified",
        ])
        document = row.get("document") or {}
        if document.get("printed_identity_observed") is not False:
            raise ValueError("unexpected Missouri printed-identity disposition")
        base = document.get("archive_directory", f"documents/{row['raw_context_id']}")
        views = []
        for stored_reader, reader in (("fitz", "pymupdf"), ("pypdf", "pypdf")):
            name = f"{prefix}/{base}/{stored_reader}_text.txt"
            if not sources.exists(name):
                continue
            view = complete_projection(
                sources, context, reader=reader, paths=[name],
                original=f"{prefix}/{base}/{document['pdf_file']}",
                original_sha256=document["pdf_sha256"], source_url=row["route"].get("url"),
                n_pages=document[f"{stored_reader}_pages"], source_kind="original_pdf",
            )
            if view["input_sha256"] != document[f"{stored_reader}_text_sha256"]:
                raise ValueError("Missouri stored full-text checksum mismatch")
            views.append(view)
        yield context, views, bool(document.get("first_page_text_prefix")) and not views


def _native_records(sources: StoredSources, state: str, document_evidence: dict | None = None):
    name = "mutable/population_dispositions.jsonl"
    for index, row in enumerate(sources.jsonl(name)):
        context = _context(state, row, str(row.get("population_index", index)), str(
            sources.path(name),
        ))
        context["negative_flags_json"] = _json([
            "retained_reconstruction_not_full_source_certification",
            "filing_and_legal_version_unapproved", "publisher_census_not_certified",
            *(["unsealed_final43", "A255_cancelled_then_started_lifecycle_anomaly"]
              if state == "NY" else ["stopped_1925_pending_two_terminal_partials",
                                     "synthetic_rendering_not_certified"]),
        ])
        base = row.get("document_path")
        views, header_only = [], False
        if base and sources.exists(f"{base}/document.json"):
            document = sources.json(f"{base}/document.json")
            if document["identifier"] != row["identifier"]:
                raise ValueError("document/population identity disagreement")
            context["original_document_metadata_json"] = _json(document)
            context["original_identity_observation"] = document.get(
                "identity_header_pass", document.get("identity_observation_pass"),
            )
            if state == "NY":
                for reader in ("pymupdf", "pypdf"):
                    text_path = f"{base}/full_text_{reader}.txt"
                    if not sources.exists(text_path):
                        continue
                    view = complete_projection(
                        sources, context, reader=reader, paths=[text_path],
                        original=f"{base}/raw.pdf", original_sha256=document["raw_pdf_sha256"],
                        source_url=document.get("requested_url"),
                        n_pages=document[f"{reader}_page_count"], source_kind="original_pdf",
                    )
                    if view["n_input_characters"] != document[f"{reader}_character_count"]:
                        raise ValueError("New York stored complete-reader length mismatch")
                    if document_evidence is not None:
                        proof = document_evidence.get(base, {})
                        reader_proof = proof.get("readers", {}).get(reader, {})
                        if (
                            proof.get("completed") is not True
                            or proof.get("identifier") != row["identifier"]
                            or proof.get("raw_sha256") != document["raw_pdf_sha256"]
                            or view["input_sha256"] != reader_proof.get("saved_full_text_sha256")
                        ):
                            raise ValueError("New York accepted complete-reader proof mismatch")
                    views.append(view)
            else:
                header_only = bool(document.get("html_unavailable_shell"))
                if document.get("policy_text_available") and not header_only:
                    text_path = f"{base}/full_text.txt"
                    if sources.exists(text_path):
                        view = complete_projection(
                            sources, context, reader="html_full_projection", paths=[text_path],
                            original=f"{base}/raw.html",
                            original_sha256=document["raw_html_sha256"],
                            source_url=document.get("requested_url"),
                            n_pages=None, source_kind="original_html",
                        )
                        text = view["text"]
                        # The collector writes rendered text plus one serialization newline.
                        exact = (
                            _digest(text) == document["full_text_sha256"]
                            and len(text) == document["full_text_characters"]
                        )
                        serialized = (
                            text.endswith("\n")
                            and _digest(text[:-1]) == document["full_text_sha256"]
                            and len(text) - 1 == document["full_text_characters"]
                        )
                        if not (exact or serialized):
                            raise ValueError("Illinois stored complete-text binding mismatch")
                        views.append(view)
        yield context, views, header_only


def _pa_records(sources: StoredSources, prefix: str):
    plan_name, status_name = f"{prefix}/source_plan.jsonl", f"{prefix}/candidate_status.jsonl"
    statuses = {row["slug"]: row for row in sources.jsonl(status_name)}
    for row in sources.jsonl(plan_name):
        context = _context("PA", row, row["native_id"], str(sources.path(plan_name)))
        status = statuses.get(row["slug"], {})
        context["source_status"] = status.get("state", "missing_status")
        context["original_candidate_status_json"] = _json(status)
        context["negative_flags_json"] = _json([
            "stopped_prefix_not_full_campaign", "noncontiguous_checkpoint_failure",
            "historical_budget_and_redirect_body_gaps", "publisher_census_not_certified",
        ])
        base, views, header_only = f"{prefix}/documents/{row['slug']}", [], False
        for kind, reader in (("pdf", "pdf_stored_reader"), ("html", "html_full_projection")):
            metadata_name = f"{base}/{kind}_metadata.json"
            if not sources.exists(metadata_name):
                continue
            metadata = sources.json(metadata_name)
            if metadata["identifier"] != row["identifier"]:
                raise ValueError("Pennsylvania metadata identity mismatch")
            context[f"original_{kind}_metadata_json"] = _json(metadata)
            pages = metadata.get("pages", [])
            receipt = metadata.get("receipt", {})
            if receipt and (
                receipt.get("body_complete") is not True
                or receipt.get("body_limit_exceeded") is True
                or receipt.get("http_status") != 200
            ):
                continue
            if pages and all(sources.exists(f"{base}/{page['path']}") for page in pages):
                views.append(complete_projection(
                    sources, context, reader=reader,
                    paths=[f"{base}/{page['path']}" for page in pages],
                    original=f"{base}/{metadata['stored_path']}",
                    original_sha256=metadata["source_sha256"],
                    source_url=metadata.get("source_url"), n_pages=len(pages),
                    source_kind=f"original_{kind}", segment_bindings=pages,
                ))
                parent_paths = [
                    f"{base}/parent_extracted_text/{kind}-page-{page['page']:04}.txt"
                    for page in pages
                ]
                if all(sources.exists(name) for name in parent_paths):
                    views.append(complete_projection(
                        sources, context, reader=f"parent_{kind}_stored_reader",
                        paths=parent_paths, original=f"{base}/{metadata['stored_path']}",
                        original_sha256=metadata["source_sha256"],
                        source_url=metadata.get("source_url"), n_pages=len(pages),
                        source_kind=f"original_{kind}",
                    ))
            else:
                header_only = header_only or bool(metadata.get("printed_identity"))
            decoded = metadata.get("decoding", {})
            decoded_path = decoded.get("decoded_source_path")
            if (
                kind == "html" and decoded_path
                and decoded.get("lossless_roundtrip_verified") is True
                and sources.exists(f"{base}/{decoded_path}")
            ):
                view = complete_projection(
                    sources, context, reader="html_source_decoded",
                    paths=[f"{base}/{decoded_path}"],
                    original=f"{base}/{metadata['stored_path']}",
                    original_sha256=metadata["source_sha256"],
                    source_url=metadata.get("source_url"), n_pages=None,
                    source_kind="original_html_markup",
                )
                if view["input_sha256"] != decoded["decoded_utf8_sha256"]:
                    raise ValueError("Pennsylvania decoded-source hash mismatch")
                views.append(view)
        yield context, views, header_only and not views


def _supplement_context(
    sources: StoredSources, state: str, row: dict, locator: str, table: str,
    *negative_flags: str,
) -> dict:
    context = _context(state, row, locator, str(sources.path(table)))
    context["negative_flags_json"] = _json([
        "bounded_retained_evidence_not_statewide_or_cycle_closure",
        "collection_identity_stage_filing_and_scientific_admission_withheld", *negative_flags,
    ])
    context["source_manifest_path"] = (
        str(sources.path("manifest.json")) if sources.members is not None else None
    )
    context["source_manifest_sha256"] = (
        sources.before["manifest.json"]["sha256"] if sources.members is not None else None
    )
    context["source_table_sha256"] = sources.before[table]["sha256"]
    return context


def _checked_projection(sources, context, *, text_sha256=None, characters=None, **kwargs):
    view = complete_projection(sources, context, **kwargs)
    if (
        (text_sha256 is not None and view["input_sha256"] != text_sha256)
        or (characters is not None and view["n_input_characters"] != characters)
    ):
        raise ValueError("stored complete projection hash/character binding mismatch")
    return view


def _tx_records(bundle):
    sources, body, initial = bundle["campaign"], bundle["body"], bundle["initial"]
    name = "mutable/population_dispositions.jsonl"
    rows = sources.jsonl(name)
    sources.pin(name, TX_SOURCE_PINS[name])
    progress = sources.json("mutable/progress.json")
    sources.pin("mutable/progress.json", TX_SOURCE_PINS["mutable/progress.json"])
    if len(rows) != progress["official_filed_population"]:
        raise ValueError("Texas pinned disposition population mismatch")
    body_name = "candidate_inputs.jsonl"
    body_rows = {row["identifier"]: (index, row)
                 for index, row in enumerate(body.jsonl(body_name))}
    pdf_name, page_name = "document_recovery.parquet", "document_pages.parquet"
    pdf_rows = {row["identifier"]: row for row in initial.parquet(pdf_name)}
    pdf_pages = initial.parquet(page_name)
    for row in rows:
        context = _supplement_context(
            sources, "TX", row, f"88R::{row['identifier']}", name,
            "unsealed_continuation_not_accepted_full_campaign",
            "historical_budget_lifecycle_final15_and_source_closure_unaccepted",
            *(["unavailable_HB1_HTML_shell_PDF_unfetched"] if row["identifier"] == "HB 1" else []),
        )
        context["native_session_identifier"] = "88R"
        context["session_identity_basis"] = "explicit named 88R retained campaign scope"
        views, header_only = [], row["identifier"] == "HB 1"
        base = row.get("document_path")
        if base:
            document = sources.json(f"{base}/document.json")
            context["original_document_metadata_json"] = _json(document)
            if document["identifier"] != row["identifier"]:
                raise ValueError("Texas stored document identifier mismatch")
            if row["state"] == "success" and not header_only:
                for filename, reader, kind, hash_key, length_key in (
                    ("full_source_text.txt", "html_full_source_projection", "original_html",
                     "full_source_text_sha256", "full_source_text_characters"),
                    ("source_decoded_utf8.txt", "html_source_decoded", "original_html_markup",
                     "decoded_source_sha256", "decoded_source_characters"),
                ):
                    if sources.exists(f"{base}/{filename}"):
                        views.append(_checked_projection(
                            sources, context, reader=reader, paths=[f"{base}/{filename}"],
                            original=f"{base}/raw.html",
                            original_sha256=document["raw_html_sha256"],
                            source_url=row["introduced_html_url"], n_pages=None, source_kind=kind,
                            text_sha256=document.get(hash_key, document["raw_html_sha256"])
                            if reader == "html_source_decoded" else document.get(hash_key),
                            characters=document.get(length_key),
                        ))
        if row["identifier"] in body_rows:
            index, stored = body_rows[row["identifier"]]
            context["original_body_inventory_record_json"] = _json(stored)
            if stored["classifier_input_available"]:
                for field, reader, digest, length in (
                    ("body_text", "stored_native_body", "body_text_sha256", "n_body_characters"),
                    ("input_text", "stored_prospective_input", "input_sha256", None),
                ):
                    views.append(_checked_projection(
                        body, context, reader=reader, paths=[body_name],
                        stored_segments=[stored[field]],
                        extraction_selector=f"physical LF JSON row {index}; exact field {field}",
                        original=f"source_archive/{stored['source_document']}/raw.html",
                        original_sha256=stored["raw_html_sha256"],
                        source_url=row["introduced_html_url"], n_pages=None,
                        source_kind="original_html_body_stored_projection",
                        text_sha256=stored[digest],
                        characters=stored[length] if length else None,
                    ))
            else:
                context["partial_stored_projection_json"] = _json({
                    "source_path": str(body.path(body_name)), "row_index": index,
                    "field": "body_text", "text": stored["body_text"],
                    "sha256": stored["body_text_sha256"], "full_policy_text_available": False,
                })
        if row["identifier"] in pdf_rows:
            stored = pdf_rows[row["identifier"]]
            pages = sorted(
                [page for page in pdf_pages
                 if page["identifier"] == row["identifier"] and page["format"] == "pdf"],
                key=lambda page: page["page_number"],
            )
            receipt = json.loads(stored["pdf_receipt_json"])
            # The accepted packet retains a packet-local copy; historical absolute paths
            # are source observations, never locations to reopen.
            originals = [
                member for member, binding in initial.members.items()
                if member.startswith("documents/raw/")
                and (binding if isinstance(binding, str) else binding.get("sha256"))
                == stored["pdf_sha256"]
            ]
            if len(originals) != 1 or len(pages) != stored["pdf_pages"]:
                raise ValueError("Texas accepted original PDF/page binding mismatch")
            context["original_initial_pdf_receipt_json"] = _json(receipt)
            views.append(complete_projection(
                initial, context, reader="initial_pdf_stored_reader",
                paths=[page["text_path"] for page in pages],
                segment_bindings=[{
                    "page": page["page_number"], "characters": page["text_characters"],
                    "sha256": page["text_sha256"],
                } for page in pages],
                original=originals[0], original_sha256=stored["pdf_sha256"],
                source_url=stored["pdf_url"], n_pages=len(pages), source_kind="original_pdf",
            ))
        yield context, views, header_only
    accounted_name = "contract/complete_accounted_population.jsonl"
    accounted = sources.jsonl(accounted_name)
    sources.pin(accounted_name, TX_SOURCE_PINS[accounted_name])
    for index, row in enumerate(accounted):
        if row["identifier"] not in {"SB 15247", "SR 1960"}:
            continue
        yield _supplement_context(
            sources, "TX", row, f"canonical-only::{index}", accounted_name,
            "canonical_only_unmatched_native_identity_no_alias",
        ), [], False


def _wa_records(bundle):
    sources = bundle["text"]
    plan_name = "source_packet/plan.json"
    plan = sources.json(plan_name)
    name = "documents.jsonl"
    for index, row in enumerate(sources.jsonl(name)):
        context = _supplement_context(
            sources, "WA", row,
            f"original-reference::row-{index}::request-{row['request_index']}", name,
            "SR8601_version_conflict_and_HB2379_primary_sponsor_gap_unresolved",
            *(["publisher_test_or_retrieval_failure"]
              if row["reviewed_source_test_record"] or not row["retrieval_ok"] else []),
        )
        context["identifier"] = row.get("expected_identifier")
        context["native_identifier"] = context["identifier"]
        context["session_identifier"] = row.get("expected_session")
        context["native_session_identifier"] = row.get("expected_session")
        context["source_status"] = row["document_scope_status"]
        context["native_date_observations_json"] = _json([
            *date_observations(row),
            {"source_field": "source_version.date", "raw_value": row["source_version"]["date"],
             "normalized": False, "basis": "literal imported version field; not filing truth"},
        ])
        views = []
        if row["retrieval_ok"] and row.get("text_file"):
            views.append(_checked_projection(
                sources, context,
                reader="stored_pdf_reader" if row.get("page_count") else "html_full_projection",
                paths=[row["text_file"]], original=f"source_packet/{row['source_file']}",
                original_sha256=row["source_sha256"], source_url=row["source_url"],
                n_pages=row.get("page_count"),
                source_kind="original_pdf" if row.get("page_count") else "original_html",
                text_sha256=row["text_sha256"], characters=row["text_characters"],
            ))
        yield context, views, False
    baseline = {row["bill_id"]: row for row in plan["baseline_references"]}
    for bill_id in plan["targets_without_original_links"]:
        row = baseline[bill_id]
        context = _supplement_context(
            sources, "WA", row, f"missing-original-note::{bill_id}", plan_name,
            "no_original_note_reference_retained_not_proof_document_absence",
            "SR8601_version_conflict_or_publisher_test_gap_not_silently_repaired",
        )
        context["source_status"] = "original_note_reference_unavailable"
        context["all_retained_version_records_json"] = _json([
            version for version in plan["all_retained_version_rows"]
            if version["bill_id"] == bill_id
        ])
        yield context, [], False
    sources, originals = bundle["alternate"], bundle["originals"]
    name = "review.json"
    for index, row in enumerate(sources.json(name)["version_review"]):
        context = _supplement_context(
            sources, "WA", row, f"SR8601-alternative::{index}", name,
            "SR8601_source_note_plain_heading_version_conflict_unresolved",
            "not_exact_introduced_version_or_filing_time_evidence",
        )
        context["identifier"], context["session_identifier"] = "SR 8601", "2019-2020"
        path = row["full_text_file"]
        # The text and original are frozen in different accepted packets.
        view = _checked_projection(
            sources, context, reader="alternate_html_full_projection", paths=[path],
            original=row["source_file"], original_sha256=row["source_sha256"],
            original_sources=originals,
            source_url=row["source_url"], n_pages=None, source_kind="alternate_version_html",
            text_sha256=row["full_text_sha256"],
        )
        yield context, [view], False


def _mt_records(bundle):
    sources = bundle["native"]
    name = "bill_reconciliation.parquet"
    native_name = "native_bill_records.parquet"
    native = {row["native_record_index"]: row for row in sources.parquet(native_name)}
    for row in sources.parquet(name):
        context = _supplement_context(
            sources, "MT", row, f"source-context::{row['bill_id']}", name,
            "native_metadata_is_not_original_policy_body",
            "LC_draft_source_context_not_additional_formal_filing",
        )
        context["identity_kind"] = row["source_identity_kind"]
        context["source_status"] = row["native_match_status"]
        index = row.get("matched_native_record_index")
        if index is not None:
            context["native_source_record_json"] = _json(native[index])
        yield context, [], False
    sources = bundle["conflicts"]
    name, pages_name = "document_observations.parquet", "reader_physical_pages.parquet"
    pages = sources.parquet(pages_name)
    for row in sources.parquet(name):
        context = _supplement_context(
            sources, "MT", row, f"printed-document::{row['document_id']}", name,
            "ancillary_2025_identity_conflict_not_2023_original",
            "LC_drafts_remain_distinct_from_formal_measures",
        )
        context["identifier"] = row["printed_identifier_observation"]
        context["identity_kind"] = (
            "draft_request" if context["identifier"].startswith("LC ") else "formal_measure"
        )
        context["source_status"] = "retained_printed_native_identity_conflict"
        views = []
        for reader in ("pymupdf", "pypdf"):
            selected = sorted(
                [page for page in pages
                 if page["document_id"] == row["document_id"] and page["reader"] == reader],
                key=lambda page: page["physical_page"],
            )
            if len(selected) != row["n_physical_pages"]:
                raise ValueError("Montana incomplete stored reader page stream")
            views.append(complete_projection(
                sources, context, reader=reader, paths=[pages_name] * len(selected),
                stored_segments=[page["text"] for page in selected],
                segment_bindings=[{
                    "page": page["physical_page"], "characters": len(page["text"]),
                    "sha256": page["text_sha256"],
                } for page in selected],
                extraction_selector=f"document_id={row['document_id']}; reader={reader}; "
                "every physical_page ascending, exact text fields",
                original=f"captures/{row['capture_label']}.bin",
                original_sha256=row["body_sha256"], source_url=row["source_url"],
                n_pages=len(selected), source_kind="ancillary_native_identity_conflict_pdf",
            ))
        yield context, views, False
    sources = bundle["history"]
    name, pages_name = "volume_captures.json", "reader_physical_pages.parquet"
    pages = sources.parquet(pages_name)
    for row in sources.json(name):
        context = _supplement_context(
            sources, "MT", row, f"history-volume::{row['session_identifier']}", name,
            "history_volume_not_original_policy_or_inferred_filing_date",
        )
        context["source_status"] = "complete_native_history_context_not_policy_text"
        views = []
        for reader in ("pymupdf", "pypdf"):
            selected = sorted(
                [page for page in pages if page["session_identifier"] == row["session_identifier"]
                 and page["reader"] == reader], key=lambda page: page["physical_page"],
            )
            if [page["physical_page"] for page in selected] != list(
                range(1, row["n_physical_pages"] + 1),
            ):
                raise ValueError("Montana history page stream incomplete")
            views.append(complete_projection(
                sources, context, reader=reader, paths=[pages_name] * len(selected),
                stored_segments=[page["text"] for page in selected],
                extraction_selector=f"session_identifier={row['session_identifier']}; "
                f"reader={reader}; every physical_page ascending, exact text fields",
                original=row["body_file"], original_sha256=row["body_sha256"],
                source_url=row["url"], n_pages=len(selected), source_kind="native_history_volume",
            ))
        yield context, views, False


def _nm_records(bundle):
    sources, ocr = bundle["text"], bundle["ocr"]
    name = "document_texts.parquet"
    conflicts = sources.json("cross_session_conflicts.json")
    quarantine = {row["link_id"]: row for row in conflicts}
    ocr_report = ocr.json("report.json")
    for row in sources.parquet(name):
        wrong = row["link_id"] in quarantine
        header_only = bool(
            row.get("pdf_page_embedded_text_lengths")
            and any(length == 0 for length in row["pdf_page_embedded_text_lengths"])
        )
        context = _supplement_context(
            sources, "NM", row, f"reference::{row['link_id']}", name,
            *(["quarantined_wrong_session_document_never_exact_native_match"] if wrong else []),
            *(["later_or_unclassified_version_not_exact_introduced"]
              if row["version_note_hint"] != "original_note" else []),
            *(["embedded_reader_partial_missing_image_pages"] if header_only else []),
        )
        context["source_status"] = row["source_scope"]
        views = []
        if wrong:
            if row["source_sha256"] != quarantine[row["link_id"]]["identical_pdf_sha256"]:
                raise ValueError("New Mexico quarantine source binding mismatch")
            context["original_cross_session_quarantine_json"] = _json(quarantine[row["link_id"]])
        if not header_only:
            views.append(_checked_projection(
                sources, context, reader=row["text_method"], paths=[row["text_file"]],
                original=f"source_packet/{row['source_file']}",
                original_sha256=row["source_sha256"], source_url=row["source_url"],
                n_pages=row.get("pdf_pages"),
                source_kind="quarantined_cross_session_pdf" if wrong else (
                    "original_pdf" if row.get("pdf_pages") else "original_html"
                ),
                text_sha256=row["text_sha256"],
            ))
        else:
            partial = sources.read(row["text_file"]).decode("utf-8")
            if _digest(partial) != row["text_sha256"]:
                raise ValueError("New Mexico partial stored text mismatch")
            context["partial_stored_projection_json"] = _json({
                "text": partial, "sha256": _digest(partial),
                "source_path": str(sources.path(row["text_file"])),
                "full_policy_text_available": False,
            })
        if row["link_id"] == ocr_report["source_reference"]["link_id"]:
            context["original_separate_ocr_report_json"] = _json(ocr_report)
            for reader, paths in (
                ("stored_tesseract_full_serialization", ["full_ocr_text.txt"]),
                ("stored_tesseract_all_page_segments", [
                    f"pages/{page:03}.txt" for page in range(1, ocr_report["n_pdf_pages"] + 1)
                ]),
            ):
                views.append(complete_projection(
                    ocr, context, reader=reader, paths=paths, original="source.pdf",
                    original_sha256=row["source_sha256"], source_url=row["source_url"],
                    n_pages=ocr_report["n_pdf_pages"],
                    source_kind="committee_substitute_amendments_in_context_ocr_not_introduced",
                ))
            if json.loads(views[-1]["segment_character_counts_json"]) != (
                ocr_report["ocr_page_text_lengths"]
            ):
                raise ValueError("New Mexico complete stored OCR page lengths mismatch")
        yield context, views, header_only and not views


def _ut_records(bundle):
    sources = bundle["originals"]
    name = "derived/recovered_contexts.json"
    joins = {row["context_exchange"]: row for row in sources.json("derived/source_joins.json")}
    for index, row in enumerate(sources.json(name)):
        context = _supplement_context(
            sources, "UT", row, f"reconstructed-original::{index}", name,
            "collection_policy_acceptance_withheld",
            "aggregate_history_and_allowance_unknown_not_zero",
        )
        context["source_status"] = "bounded_reconstruction_collection_not_accepted"
        context["requested_identity_json"] = _json(row["requested_identity"])
        year, family, number = row["requested_identity"]
        context["identifier"] = f"{family} {number}"
        context["session_identifier"] = str(year)
        context["identity_basis"] = "literal requested identity; not certified printed identity"
        joined = joins[row["context_exchange"]]
        context["original_stored_source_join_json"] = _json(joined)
        context["canonical_bill_ids_json"] = _json(joined["canonical_bill_ids"])
        if len(joined["canonical_bill_ids"]) == 1:
            context["canonical_bill_id"] = joined["canonical_bill_ids"][0]
        pdf_name = f"derived/pdf_x{row['document_exchange']:04}.json"
        pdf = sources.json(pdf_name)
        views = []
        for reader in ("pymupdf", "pypdf"):
            segments = pdf[f"{reader}_pages"]
            original = f"transport/x{row['document_exchange']:04}.body"
            views.append(complete_projection(
                sources, context, reader=reader, paths=[pdf_name] * len(segments),
                stored_segments=segments,
                extraction_selector=f"exact {reader}_pages JSON array, every element in order",
                original=original, original_sha256=sources.members[original]["sha256"],
                source_url=row["selected_original_link"]["url"], n_pages=len(segments),
                source_kind="reconstructed_original_pdf_collection_unaccepted",
            ))
        html_name = f"derived/html_x{row['document_html_exchange']:04}.json"
        html = sources.json(html_name)
        original = f"transport/x{row['document_html_exchange']:04}.body"
        for field, reader, kind in (
            ("full_text", "html_full_projection", "reconstructed_original_html"),
            ("source", "html_source_decoded", "original_html_markup"),
        ):
            views.append(complete_projection(
                sources, context, reader=reader, paths=[html_name], stored_segments=[html[field]],
                extraction_selector=f"entire literal JSON field {field}", original=original,
                original_sha256=sources.members[original]["sha256"],
                source_url=row["introduced_group"]["html_link"]["url"],
                n_pages=None, source_kind=kind,
            ))
        yield context, views, False


def _partial_reference_records(bundle, state):
    sources = bundle["review"]
    name = "review.json"
    for row in sources.json(name)["source_scope_review"]:
        if row.get("state") != state:
            continue
        context = _supplement_context(
            sources, state, row, f"bounded-reference::{row['link_id']}", name,
            "main_document_only_DOCX_not_complete_original_policy" if state == "WV" else (
                "introduced_cover_only_evidence_not_complete_original_policy"
            ),
        )
        context["source_status"] = "partial_retained_projection_not_complete_original_policy"
        partial = sources.read(row["text_file"]).decode("utf-8")
        if _digest(partial) != row["text_sha256"]:
            raise ValueError("partial reference text checksum mismatch")
        receipt = row["original_source_receipt"]
        sources.pin(f"source_packet/{receipt['source_file']}", receipt["content_sha256"])
        context["partial_stored_projection_json"] = _json({
            "text": partial, "sha256": _digest(partial), "characters": len(partial),
            "source_path": str(sources.path(row["text_file"])),
            "full_policy_text_available": False, "method": row["text_method"],
        })
        yield context, [], True


def _supplement_records(bundle, state):
    adapters = {"TX": _tx_records, "WA": _wa_records, "MT": _mt_records,
                "NM": _nm_records, "UT": _ut_records}
    if state in adapters:
        return adapters[state](bundle)
    return _partial_reference_records(bundle, state)


def reconcile_tables(contexts: pd.DataFrame, views: pd.DataFrame) -> dict:
    _unique(contexts, "context_id")
    _unique(views, "view_id")
    if (
        not views["context_id"].isin(contexts["context_id"]).all()
        or views.duplicated(["context_id", "reader"]).any()
        or not views["text"].map(_digest).eq(views["input_sha256"]).all()
        or not views["raw_text_sha256"].eq(views["input_sha256"]).all()
        or not views["text"].str.len().eq(views["n_input_characters"]).all()
        or not views["text"].map(lambda s: len(s.encode("utf-8"))).eq(
            views["n_input_utf8_bytes"],
        ).all()
        or views["text"].str.strip().eq("").any()
        or views[list(FALSE_FLAGS)].any().any()
        or contexts[list(FALSE_FLAGS)].any().any()
    ):
        raise ValueError("complete text/identity/unapproved flags reconciliation failed")
    counts = views.groupby("context_id").size()
    if not contexts["context_id"].map(counts).fillna(0).eq(contexts["n_retained_views"]).all():
        raise ValueError("context alternative-view counts disagree")
    return {
        "n_contexts": len(contexts), "n_source_views": len(views),
        "n_contexts_with_views": int(contexts["n_retained_views"].gt(0).sum()),
        "n_header_only_contexts": int(contexts["status"].eq("header_only_not_full_text").sum()),
        "n_unavailable_contexts": int(
            contexts["status"].eq("complete_projection_unavailable").sum(),
        ),
        "views_by_reader": dict(Counter(views["reader"])),
        "contexts_by_source_status": dict(Counter(contexts["source_status"])),
        "all_original_text_utf8_bytes_sha256_and_lengths_equal": True,
        "reader_alternatives_are_not_extra_bills": True,
    }


def build_state(data_dir: Path, out_dir: Path, evidence_dir: Path, state: str, spec: dict) -> dict:
    sources = StoredSources(data_dir / spec["root"])
    bundle = {}
    if spec.get("supplement"):
        for alias, (root, digest) in SUPPLEMENT_PACKETS[state].items():
            member = sources if root == spec["root"] else StoredSources(data_dir / root)
            if digest is not None:
                member.manifest(digest)
            bundle[alias] = member
    elif "manifest_sha256" in spec:
        sources.manifest(spec["manifest_sha256"])
    proof_sources = sources if spec.get("receipt_in_packet") else StoredSources(evidence_dir)
    receipt_name = spec["receipt"]
    receipt = {} if receipt_name in proof_sources.before else json.loads(proof_sources.read(
        receipt_name, role="accepted_reconstruction_receipt",
    ))
    proof_sources.pin(receipt_name, spec["receipt_sha256"])
    if state == "UT" and spec.get("supplement"):
        authority = "utah_prospective_allowance_authority_clarification_parent_v1.json"
        proof_sources.read(authority, role="collection_authority_withheld_receipt")
        proof_sources.pin(
            authority, "5a559726240b14fc2bcc76a57fa9d9b5ccdf43193515d9477e1cca71ba7a205d",
        )
    document_evidence = None
    if "document_evidence" in spec:
        evidence_name = spec["document_evidence"]
        bound = receipt["worker_artifacts"][str(proof_sources.path(evidence_name))]
        if bound["sha256_or_null"] != spec["document_evidence_sha256"]:
            raise ValueError("document evidence not bound by accepted receipt")
        evidence_rows = proof_sources.jsonl(evidence_name)
        proof_sources.pin(evidence_name, spec["document_evidence_sha256"])
        document_evidence = {row["document_path"]: row for row in evidence_rows}
        if len(document_evidence) != len(evidence_rows):
            raise ValueError("duplicate accepted document-evidence rows")
    prefix = spec.get("prefix", "")
    records = (
        _supplement_records(bundle, state) if spec.get("supplement")
        else _mo_records(sources, prefix) if state == "MO"
        else _pa_records(sources, prefix) if state == "PA"
        else _native_records(sources, state, document_evidence)
    )
    contexts, views = [], []
    date_counts = Counter()
    for context, retained, header_only in records:
        for key, value in retain_source_date_observations(context, retained).items():
            if isinstance(value, int) and not isinstance(value, bool):
                date_counts[key] += value
        context.update({
            "n_retained_views": len(retained), "full_source_text_available": bool(retained),
            "status": "stored_complete_projection_unapproved" if retained else (
                "header_only_not_full_text" if header_only else "complete_projection_unavailable"
            ),
            "source_table_sha256": context.get("source_table_sha256") or sources.before[
                str(Path(context["source_table_path"]).relative_to(sources.root))
            ]["sha256"],
            "source_manifest_path": context.get(
                "source_manifest_path", str(sources.root / "manifest.json")
                if "manifest_sha256" in spec else None,
            ),
            "source_manifest_sha256": context.get(
                "source_manifest_sha256", spec.get("manifest_sha256"),
            ),
            "accepted_reconstruction_receipt_path": str(proof_sources.path(receipt_name)),
            "accepted_reconstruction_receipt_sha256": spec["receipt_sha256"],
            "identity_basis": context.get("identity_basis", (
                "literal_stored_campaign_fields_only_no_new_crosswalk_or_certification"
            )),
        })
        contexts.append(context)
        views.extend(retained)
    context_table = pd.DataFrame(contexts)
    view_table = pd.DataFrame(views, columns=VIEW_COLUMNS)
    summary = reconcile_tables(context_table, view_table)
    expected = spec.get("expected_complete_contexts")
    if expected is not None and summary["n_contexts_with_views"] != expected:
        raise ValueError(f"{state}: unexpected complete-view population: {summary}")
    out_dir.mkdir(parents=True, exist_ok=False)
    context_table.to_parquet(out_dir / "context_inventory.parquet", index=False)
    view_table.to_parquet(out_dir / "source_view_inputs.parquet", index=False)
    persisted_contexts = pd.read_parquet(out_dir / "context_inventory.parquet")
    persisted_views = pd.read_parquet(out_dir / "source_view_inputs.parquet")
    if (
        reconcile_tables(persisted_contexts, persisted_views) != summary
        or persisted_views["text"].tolist() != view_table["text"].tolist()
    ):
        raise ValueError("persisted complete-text byte/hash/length equality failed")
    stability = sources.finish(out_dir / "source_fingerprints.parquet")
    supplemental_stability = {
        alias: member.finish(out_dir / f"source_fingerprints_{alias}.parquet")
        for alias, member in bundle.items() if member is not sources
    }
    if proof_sources is not sources:
        proof_stability = proof_sources.finish(out_dir / "provenance_fingerprints.parquet")
    else:
        proof_stability = {"included_in_source_fingerprints": True}
    manifest = {
        "schema_version": 1, "state": state, "created_at": utc_now_iso(),
        "status": "bounded_retained_projection_index_not_census_or_campaign_closure",
        "profile": "views", "source_packet_root": str(sources.root),
        "source_prefix": prefix, "source_manifest_sha256": spec.get("manifest_sha256"),
        "accepted_reconstruction_receipt": {
            "path": str(proof_sources.path(receipt_name)), "sha256": spec["receipt_sha256"],
            "replayed_or_reaudited": False,
        },
        "accepted_document_evidence_sha256": spec.get("document_evidence_sha256"),
        "counts": summary, "limitations": spec["limitations"],
        "native_date_observations": {
            **date_counts,
            "dates_normalized_or_used_for_admission": False,
            "generic_headers_and_adjacent_dates_not_reclassified_as_introduction": True,
            "scope": (
                "raw record date fields and exact literal introduced/filed physical-line spans"
            ),
        },
        "campaign_pending_not_certified": spec.get("campaign_pending_not_certified"),
        "source_stability": stability, "provenance_stability": proof_stability,
        **({"additional_source_stability": supplemental_stability} if bundle else {}),
        "complete_projection_unavailable_disposition": (
            "No complete stored projection was fabricated from headers or extracted from originals."
        ),
        "context_population": (
            "accepted retained 1152-candidate prefix only" if state == "MO"
            else "stored campaign population, including unavailable and pending dispositions"
        ),
        "new_requests": 0, "fresh_pdf_extractions": 0, "model_or_tokenizer_loaded": False,
        "labels_created": 0, "default_admission": False, "full_campaign_closure": False,
        **FALSE_FLAGS,
        "files": {
            path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in sorted(out_dir.iterdir()) if path.is_file()
        },
    }
    if bundle:
        manifest["source_packet_bindings"] = {
            alias: {
                "root": str(member.root),
                "manifest_sha256": member.before.get("manifest.json", {}).get("sha256"),
                "scope": (
                    "consumed stored members only; no campaign or collection-policy acceptance"
                ),
            } for alias, member in bundle.items()
        }
        manifest["context_population"] = (
            "all named retained packet dispositions; references, aliases and source documents "
            "are not extra bills; multi-session ancillary evidence is not target-cycle admission"
        )
    (out_dir / "manifest.json").write_text(_json(manifest) + "\n", encoding="utf-8")
    return manifest


def build_indexes(
    data_dir: Path, out_dir: Path, evidence_dir: Path, states: list[str] | None = None,
    reuse_existing_states: list[str] | None = None,
) -> dict:
    selected = list(LEGACY_STATES if states is None else states)
    if not selected or len(set(selected)) != len(selected) or any(
        state not in PROFILES for state in selected
    ):
        raise ValueError("select nonempty unique supported states")
    reuse = list(reuse_existing_states or [])
    if len(set(reuse)) != len(reuse) or not set(reuse).issubset(selected):
        raise ValueError("reused states must be unique selected states")
    output = out_dir.resolve()
    for spec in PROFILES.values():
        root = (data_dir / spec["root"]).resolve()
        if output == root or output.is_relative_to(root) or root.is_relative_to(output):
            raise ValueError("output must be disjoint from original source packets")
    if reuse and (out_dir / "manifest.json").exists():
        raise FileExistsError("completed output packets cannot be rebuilt")
    out_dir.mkdir(parents=True, exist_ok=bool(reuse))
    builder_before = _snapshot(Path(__file__))
    manifests = {}
    for state in selected:
        if state not in reuse:
            manifests[state] = build_state(
                data_dir, out_dir / state, evidence_dir, state, PROFILES[state],
            )
            continue
        path = out_dir / state / "manifest.json"
        manifest = json.loads(path.read_bytes())
        if (
            manifest["state"] != state or manifest["profile"] != "views"
            or manifest["source_packet_root"] != str((data_dir / PROFILES[state]["root"]).resolve())
            or manifest["full_campaign_closure"] is not False
            or any(manifest[flag] is not False for flag in FALSE_FLAGS)
        ):
            raise ValueError("existing state is not a matching unapproved retained packet")
        for name, binding in manifest["files"].items():
            relative = Path(name)
            if relative.is_absolute() or len(relative.parts) != 1:
                raise ValueError("unsafe reused output member")
            member = StoredSources(out_dir / state).path(name)
            if (
                sha256_file(member) != binding["sha256"]
                or member.stat().st_size != binding["bytes"]
            ):
                raise ValueError("reused output member changed")
        manifests[state] = manifest
    if _snapshot(Path(__file__)) != builder_before:
        raise ValueError("builder changed during normalization")
    result = {
        "schema_version": 1, "created_at": utc_now_iso(),
        "status": "complete_bounded_stored_projection_packet_not_source_closure",
        "builder_before": builder_before, "builder_after": builder_before,
        "exact_argv": sys.argv,
        "states": {state: manifest["counts"] for state, manifest in manifests.items()},
        "reused_existing_states_without_source_renormalization": reuse,
        "new_requests": 0, "fresh_pdf_extractions": 0, "model_or_tokenizer_loaded": False,
        "public_deployment": False, "source_campaign_closure": False,
        "analytical_admission": False,
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
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--states", nargs="+", choices=tuple(PROFILES), default=None,
                        help="Only these states; default preserves MO NY IL PA legacy batch.")
    parser.add_argument(
        "--reuse-existing-states", nargs="+", choices=tuple(PROFILES), default=None,
        help="After a partial failed build only: verify and reuse these completed state outputs; "
        "never overwrite a completed root packet or reread their source projections.",
    )
    args = parser.parse_args()
    print(json.dumps(build_indexes(
        args.data_dir, args.out_dir, args.evidence_dir, args.states, args.reuse_existing_states,
    ), indent=2))


if __name__ == "__main__":
    main()

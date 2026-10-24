"""Strict offline normalization of an explicitly sealed NJ library collection packet.

Only ``new_pdfs`` are normalized; reused sources never create duplicate views.
An immutable subset is not a complete collection, and a complete catalogue is
not a native bill universe. Both complete reader outputs, including quarantined
and ancillary pages, remain in the packet. Unsupported identity/version profiles
are explicit negatives, never guessed or OCR'd.

Build requires caller-provided SHA256 anchors for both the source manifest and
the original queue. Verify can additionally receive those external anchors.
The archived producer sources are compared with the installed modules; replay
does not execute code from a packet.

An optional context-evidence directory and its SHA256 enable exact 2024
introductions printed in legislature 220. It contains the complete frozen
original context corpus, original action table and extraction manifest.
Only an unchanged whole-row subset of the original source queue is permitted;
the contradictory original session-end metadata is never repaired.

    python -m state_politics.bills.nj_library_collection build \
      --source-dir SEALED --source-manifest-sha256 SHA256 \
      --gap-queue QUEUE --gap-queue-sha256 SHA256 --out-dir NEW
    python -m state_politics.bills.nj_library_collection verify --directory NEW
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from state_politics.bills import nj_library_text as legacy

SCHEMA = "state-politics.nj-library-collection-text.v1"
PROVIDER = legacy.PROVIDER
STATUS = "independent_selected_collection_archive_not_filing_time_certified"
FLAGS = legacy.FLAGS + ("human_gold_approved", "publication", "rights_approved")
TOOLS = legacy.TOOLS
SOURCE_STATUSES = {
    "immutable_first16_subset": "sealed_first16_subset_not_complete_collection",
    "closed_complete_collection_capture": "closed_complete_collection_capture",
}
CONTEXT_SCHEMA = "state-politics.original-nj-tail-introductions.v1"
CONTEXT_ALL_DATES_SCHEMA = "state-politics.original-nj-introduction-contexts.v1"
CONTEXT_SINGLE_PAGE_SCHEMA = "state-politics.original-nj-single-page-contexts.v1"
CONTEXT_PRINTED_VARIANTS_SCHEMA = "state-politics.original-nj-printed-variants-contexts.v1"
ORIGINAL_CONTEXTS_SHA256 = "854ecd4e37ba2f160c8dc46fca92f9b47bbcf29c82939a7726855eaaea304431"
ORIGINAL_EXTRACTION_SHA256 = "9a3555e5194ac3d45ab30c4107df4f720ad40f3ce85e040fa5336138d8ee8a29"
UNLABELLED_PAGE_BRIDGES = {
    "63dce0b123f0ed16796e1c0dea303999dcda78399777835c7f828d03a10c870b": {
        "page_ordinal": 37, "identifier": "S 4023", "preceding_folio": 34,
        "following_folio": 36, "printed_reprint_label": "[1R]",
        "readers": {
            "pypdf": (
                "fd1889d71cbfad5d0ca79ca57982a83eadfe398387a722da111680267651d2d4",
                "c03151a8aac73a65550c70434c0792dea894fdf30bfd1d842a23d75082bd2104",
                "7c10b2963173d6f1998e8d2b86ae00df1e42fd53b172f04ee0c70c8f3b4ece0b",
            ),
            "pymupdf": (
                "4585d1dd791122715a104b24b4c98c7681f362ab9a5512c7540b790cb54ab818",
                "28268cc8547e33ddc5254c838a9eb721cee84f315dd5dee55b9adb0d99bac91f",
                "1dd30ed7a84dfb992c15e384ede68c023b8dce291bb903006b16141de8a4150e",
            ),
        },
    },
}
PRINTED_PROLOGUE_WITNESSES = {
    "d1f6a58c2b05ee0c35b4151c888c8968ffe397073f779f72fd9af2ae49a4939b": {
        "page_ordinal": 4, "role": "printed_statutory_codification",
        "readers": {
            "pypdf": (
                "1b0df46f32f0220c09a4f523418855ff59765cfe808456f0f0a65ee9db346f18",
                "0537303fb71bc094021c3dd796f9b6e06ce8cd6570bf94a741a35686a6210874",
            ),
            "pymupdf": (
                "7aa182a4a72ae97a8a89fc78ee0175a26a3e8668a2e2590dd00ae458db3a60a7",
                "c6eb0f7696927b243f16f941f2905dfe3eff296fb1155bcf239b5ff0376d2429",
            ),
        },
    },
    "bfa88a5cbd001625f63a69f65166359544c1f11305c41ffab57fe507c58c64bf": {
        "page_ordinal": 3, "role": "printed_initial_folio",
        "readers": {
            "pypdf": (
                "46460c930d4f91be01fe3b8464191736c3928ddefa1a7c305cb57e4ac755d73b",
                "67249cba0e648265eecb495ffeb2590be30e7deff6e4b98d3e02c24c681b8d3a",
            ),
            "pymupdf": (
                "3b6b43079e223663c80c3f9614ad547d4f8615b5c5e0106fafb225abcb36cdf8",
                "67249cba0e648265eecb495ffeb2590be30e7deff6e4b98d3e02c24c681b8d3a",
            ),
        },
    },
    "b537e0cd0952ff2df641155cfadec712eb620d3821a1471dd60bd17881339392": {
        "page_ordinal": 3, "role": "printed_statutory_codification",
        "readers": {
            "pypdf": (
                "b2cbc9681bef72c781e95d80a0443b919a5c815f84736d48c2f6347d13a008ec",
                "bab9e1aaeeb5ad6ffa1dcfa42a4c2a311383738e34297f65a743b1320e670238",
            ),
            "pymupdf": (
                "438f1d1e4ef9a2bbdb6d81cbdffc09d220ba989d4b58d442d916e240af5b8a7d",
                "5eddb19ac43dd2f9a02630fba645e6df12c4283b915a99e04195eda12c3d7443",
            ),
        },
    },
    "5c35773602636c587f0bdc353f67d740e77c214e4d5468d7f37eaf2354130350": {
        "page_ordinal": 3, "role": "printed_statutory_codification",
        "readers": {
            "pypdf": (
                "00f62969825ddc8e5f50e210ffbc5f6f2756532252b160e3183d5ab654757cfa",
                "afdce198dbbe5debf2d42ed507ef258891c3b3b3d7100e427253e7e54c600c98",
            ),
            "pymupdf": (
                "5259540a29dc1948d2ca9777e2b88e2e4f414a0ea1259d36a14763fcf00284eb",
                "d8433ac3988d892228918cddeac5b1e9ce4c5ec7e5d81d9302dcd3cea7febc96",
            ),
        },
    },
}
VERIFIED_WHITESPACE_PAGES = {
    "d1f6a58c2b05ee0c35b4151c888c8968ffe397073f779f72fd9af2ae49a4939b": {
        "page_ordinal": 3,
        "content_stream_sha256": "19c1732cc891de7b50e72c6ff693d6292a09157090e38786f74359745f4b8513",
        "readers": {
            "pypdf": "36a9e7f1c95b82ffb99743e0c5c4ce95d83c9a430aac59f84ef3cbfab6145068",
            "pymupdf": "e16f1596201850fd4a63680b27f603cb64e67176159be3d8ed78a4403fdb1700",
        },
    },
}
SEALED_PRODUCERS = {
    "5298ca4dc50ee84b343573402db8e92443700f911838ecf6dfb7645c17aef256": {
        "producer/nj_library_collection.py": {
            "sha256": "f6b5bc86751f9b8b966e2738669f1fb03817c578ddfa764210c63edabbdab2b8",
            "bytes": 71296,
        },
        "producer/nj_library_text.py": {
            "sha256": "cd553e50fe15c258428de12b42285ad12852758d3d2fefad581227573a546174",
            "bytes": 67376,
        },
    },
    "81771d07dc9f41a79547193e26e220bfa71015e57d912eb587ad749373d426ab": {
        "producer/nj_library_collection.py": {
            "sha256": "11808e71439a442f5b3140077b3e2f1f8f7e0bf2ba2c1403dbcabddac356948c",
            "bytes": 68889,
        },
        "producer/nj_library_text.py": {
            "sha256": "4431677fafdcd0a03bb86b4e19ee74e0fc84cedf8717883a7779171e6a7cab47",
            "bytes": 66976,
        },
    },
    "3922c090c6d937385c57818b9a3f065ebee1f6168a3cedc9b842b8095e5bdeae": {
        "producer/nj_library_collection.py": {
            "sha256": "4075e6a5e757ffe092e613cebf0c502eaf9b74fe0fbac95a95f8227dd8576381",
            "bytes": 63939,
        },
        "producer/nj_library_text.py": {
            "sha256": "7d7a58c5ae5d44579088b234864f04e3ec11464dff2113cd0bdfa1c74432a991",
            "bytes": 61032,
        },
    },
    "e8933b0d69ab9a791ef4830e35044fde4022e8df2880f4a9c544426a9f9601a6": {
        "producer/nj_library_collection.py": {
            "sha256": "c7fe4468c5cb17cf821a9140edc7d1b09b8bafdcb54d1d8237c910e4620a66c7",
            "bytes": 54245,
        },
        "producer/nj_library_text.py": legacy.STRICT_2023_PRODUCER,
    },
    "6a436837b31b8f635b47dfa34fb88e3f0e9ccc3f350ab9313f019399183a70b4": {
        "producer/nj_library_collection.py": {
            "sha256": "e7714c3b2eb11e65694be8bb47eb61a13ec469d789846956666d3040457feafe",
            "bytes": 41212,
        },
        "producer/nj_library_text.py": {
            "sha256": "072353f61a0c9cd74a5cd8fc74b9b5caea70945c0a21b3d6d8120788914bef70",
            "bytes": 54845,
        },
    },
}
PRODUCTS = {
    "input_gap_queue.parquet", "context_inventory.parquet", "original_queue_rows.jsonl",
    "queue_dispositions.jsonl", "pages.jsonl", "documents.jsonl", "versions.jsonl",
    "views.jsonl", "page_dispositions.jsonl", "source_dispositions.jsonl",
    "source_inventory.json", "consumed_input_hashes.json", "report.json",
    "producer/nj_library_collection.py", "producer/nj_library_text.py",
}
LIMITS = {
    "no_network_performed": True, "no_ocr_performed": True,
    "neither_reader_is_ground_truth": True,
    "reader_views_are_alternatives_not_independent_contexts": True,
    "no_scientific_model_training_human_or_publication_admission": True,
    "original_cohort_and_null_date_id_fields_preserved": True,
    "no_new_labels_predictions_or_model_forwards": True,
    "no_filing_date_or_alias_inference": True,
    "archive_generated_prologue_preserved": False,
    "transport_scope": "Only the explicitly sealed packet's selected capture records; "
                       "not the parent's complete request history.",
    "catalogue_scope": "A retained public library catalogue, not a native bill universe.",
    "printed_identity_profile": "Own NJ typed bill covers in legislature 220 with an "
                                "explicit 2022/2023 introduced year. Other profiles are "
                                "quarantined, not reassigned to that session.",
    "enacted_session_witness": "Separately retained same-bill, same-PDF, same-reader "
                               "explicit cover only; never appended as policy text.",
    "unsupported_separation": "A reader whose strict complete-version separation fails "
                              "is quarantined in full. No guessed partial version.",
}


def require(condition, message):
    if not condition:
        raise ValueError(f"incompatible NJ collection archive: {message}")


def _hash(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            "explicit SHA256 required")
    return value


def _tree(root):
    files = set()
    for path in root.rglob("*"):
        require(not path.is_symlink() and path.resolve() == path,
                "unsafe or linked packet member")
        if path.is_dir():
            continue
        legacy._regular(path)
        files.add(path.relative_to(root).as_posix())
    return files


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _transfer(path):
    text = path.read_text(encoding="utf-8")
    scripts = re.findall(
        r'<script id="dspace-angular-state" type="application/json">([\s\S]*?)</script>',
        text,
    )
    require(len(scripts) == 1, "missing or ambiguous original Angular transfer state")
    text = scripts[0]
    # Angular's TransferState escaping is not HTML entity escaping.
    for token, literal in (("q", '"'), ("s", "'"), ("l", "<"), ("g", ">"), ("a", "&")):
        text = text.replace(f"&{token};", literal)
    return list(_walk(legacy._decode(text)))


def _abstract(item):
    require(type(item) is dict and type(item.get("uuid")) is str
            and item.get("id") == item["uuid"] and item.get("type") == "item",
            "invalid original catalogue item identity")
    require(item.get("inArchive") is True and item.get("discoverable") is True
            and item.get("withdrawn") is False, "catalogue item not explicitly public")
    values = item.get("metadata", {}).get("dc.description.abstract", [])
    require(type(values) is list and len(values) == 1
            and type(values[0].get("value")) is str
            and re.fullmatch(r"Year: 2023, Chapter: [1-9][0-9]*", values[0]["value"]),
            "unsupported or ambiguous literal catalogue year/chapter")
    return values[0]["value"]


def _catalogue(source, batch, captures):
    originals, page_records = [], []
    catalog_captures = batch["catalog_captures"]
    require(type(catalog_captures) is list and bool(catalog_captures),
            "complete retained catalogue pages required")
    for ordinal, capture in enumerate(catalog_captures):
        require(legacy._equal(captures.get(capture["ordinal"]), capture),
                "catalogue capture missing from selected source ledger")
        result = legacy._json(source / capture["body"])
        require(result["scope"] == batch["collection"], "wrong catalogue collection")
        search = result["_embedded"]["searchResult"]
        page = search["page"]
        require(type(page["number"]) is int and page["number"] == ordinal
                and type(page["size"]) is int and page["size"] > 0
                and type(page["totalPages"]) is int
                and page["totalPages"] == len(catalog_captures)
                and type(page["totalElements"]) is int and page["totalElements"] > 0,
                "incomplete or contradictory catalogue pagination")
        query = parse_qs(urlsplit(capture["url"]).query)
        require(query.get("scope") == [batch["collection"]]
                and query.get("dsoType") == ["ITEM"]
                and query.get("page", ["0"]) == [str(ordinal)],
                "catalogue URL/page membership mismatch")
        if ordinal + 1 < len(catalog_captures):
            require(search["_links"]["next"]["href"] == catalog_captures[ordinal + 1]["url"],
                    "catalogue next-page capture omitted or changed")
        else:
            require("next" not in search["_links"], "catalogue terminal page not retained")
        objects = search["_embedded"].get("objects", [])
        expected_count = min(page["size"], page["totalElements"] - ordinal * page["size"])
        require(len(objects) == expected_count, "catalogue page item count mismatch")
        originals.extend(row["_embedded"]["indexableObject"] for row in objects)
        page_records.append(page)
    require(all(p["size"] == page_records[0]["size"]
                and p["totalElements"] == len(originals) for p in page_records),
            "catalogue totals disagree")
    require(legacy._equal(originals, batch["catalog_items"]),
            "source catalogue items changed or omitted from original captures")
    by_id = {}
    for item in originals:
        _abstract(item)
        require(item["uuid"] not in by_id, "duplicate catalogue item")
        by_id[item["uuid"]] = item
    return by_id


def _ledger_name(source):
    names = [name for name in ("request-ledger.snapshot.json", "request-ledger.jsonl")
             if (source / name).exists()]
    require(len(names) == 1, "one explicit selected or full copied ledger required")
    return names[0]


def _prefix_capture(source, capture):
    if capture["host"] == "repo.njstatelib.org":
        location = legacy._verify_capture(source, capture)
        return legacy._capture_files(capture), location
    parsed = urlsplit(capture["url"])
    require(parsed.scheme == "https" and parsed.hostname == "www.congressmcp.com"
            and capture["host"] == parsed.hostname
            and not parsed.username and not parsed.password and not parsed.fragment
            and parsed.path in {"/robots.txt", "/states/hawaii/"},
            "unexpected retained historical prefix URL")
    require(capture["status"] == 200 and capture["curl_returncode"] == 0
            and capture["access_stop"] is False and capture["automatic_retries"] is False
            and capture["automatic_redirects"] is False,
            "unsuccessful retained historical prefix capture")
    names = [legacy._relative(capture[k]) for k in ("body", "headers", "transport", "stderr")]
    require(len(set(names)) == 4 and all(n.startswith("raw/") for n in names),
            "unsafe retained historical prefix file membership")
    for name in names:
        legacy._regular(source / name)
    require(legacy._binding(source / capture["body"]) == {
        "sha256": capture["body_sha256"], "bytes": capture["body_bytes"],
    }, "historical prefix original body binding mismatch")
    headers = (source / capture["headers"]).read_bytes().decode("iso-8859-1")
    require(re.findall(r"(?m)^HTTP/[0-9.]+[ \t]+([0-9]{3})[^\r\n]*", headers) == ["200"]
            and headers.endswith(("\n\n", "\r\n\r\n")),
            "historical prefix original response headers mismatch")
    transport = legacy._json(source / capture["transport"])
    require(transport["url"] == capture["url"] == transport["url_effective"]
            and transport["http_code"] == transport["response_code"] == 200
            and transport["exitcode"] == transport["num_redirects"] == 0
            and transport["method"] == "GET"
            and transport["size_download"] == capture["body_bytes"],
            "historical prefix original transport mismatch")
    return names, None


def _item_reference(source, entry, pdf_capture):
    item, item_capture = entry["catalog_item"], entry["item_capture"]
    require(item_capture["url"] == "https://repo.njstatelib.org/items/" + item["uuid"],
            "item capture URL does not identify the catalogue item")
    state = _transfer(source / item_capture["body"])
    angular = [r for r in state if r.get("type") == "item" and r.get("uuid") == item["uuid"]]
    require(len(angular) == 1 and angular[0].get("id") == item["id"]
            and angular[0].get("isArchived") is True
            and angular[0].get("isDiscoverable") is True
            and angular[0].get("isWithdrawn") is False
            and [v["value"] for v in angular[0]["metadata"]["dc.description.abstract"]]
            == [_abstract(item)], "original Angular item identity/public flags mismatch")
    bitstream = entry["bitstream_record"]
    candidates = [r for r in state if r.get("type") == "bitstream"
                  and r.get("uuid") == bitstream.get("uuid")]
    require(len(candidates) == 1 and legacy._equal(candidates[0], bitstream)
            and bitstream.get("bundleName") == "ORIGINAL"
            and bitstream.get("sizeBytes") == pdf_capture["body_bytes"]
            and bitstream["_links"]["content"]["href"] == pdf_capture["url"],
            "PDF not an exact original-URL, size-matched item transfer-state bitstream")


def _full_receipt(source, batch, prefix, ledger, artifacts):
    scope = legacy._json(source / "scope.json")
    current = ledger[len(prefix):]
    require(prefix and legacy._equal(ledger[:len(prefix)], prefix),
            "retained original prefix changed or omitted from full ledger")
    require(len(ledger) + 1 == scope["known_inherited_physical_exchanges"] + len(current)
            and scope["inherited_exchange"]["raw_response_retained"] is False
            and scope["inherited_exchange"]["response_body_sha256"] is None,
            "retained prefix cannot reconstruct the unretained inherited identity exchange")
    require(len(current) == batch["new_physical_requests"]
            and len(current) <= scope["maximum_new_physical_requests"]
            and batch["known_aggregate_physical_exchanges"]
            == scope["known_inherited_physical_exchanges"] + len(current),
            "original finite request allowance or aggregate mismatch")
    starts = []
    for capture in current:
        transport = legacy._json(source / capture["transport"])
        require(transport["ssl_verify_result"] == 0, "new capture TLS verification failed")
        require(type(capture["start_monotonic"]) in (int, float),
                "typed retained new-request timing required")
        starts.append(capture["start_monotonic"])
    require(scope["minimum_start_spacing_seconds"] >= 2.2
            and all(b - a >= scope["minimum_start_spacing_seconds"]
                    for a, b in zip(starts, starts[1:], strict=False)),
            "new-request start spacing violates retained original policy")
    receipt = legacy._json(source / "capture-completion-report.json")
    expected = {
        "catalog_items": len(batch["catalog_items"]),
        "catalog_pages": len(batch["catalog_captures"]),
        "new_pdfs": len(batch["new_pdfs"]),
        "exact_original_URL_reused_pdfs": len(batch["reused_pdfs"]),
        "all_current_published_ORIGINAL_bitstream_sizes_verified":
            len(batch["new_pdfs"]) + len(batch["reused_pdfs"]),
        "new_physical_pdf_pages": sum(e["n_pages"] for e in batch["new_pdfs"]),
        "new_complete_pdf_bytes": sum(e["capture"]["body_bytes"] for e in batch["new_pdfs"]),
        "new_physical_requests": len(current),
        "original_new_request_ceiling": scope["maximum_new_physical_requests"],
        "known_aggregate_physical_exchanges": batch["known_aggregate_physical_exchanges"],
        "encoder_or_training_calls": 0, "model_input_approved": False,
        "scientific_approval": False, "publication": False,
    }
    require(all(legacy._equal(receipt[k], v) for k, v in expected.items()),
            "full capture completion receipt disagrees with original packet evidence")
    continuation = legacy._json(source / "schema-v2-continuation.json")
    failure = legacy._json(source / "failure.json")
    require("failure-schema-v2.json" not in artifacts
            and continuation["previous_failure_preserved"] is True
            and continuation["access_stops_retried_or_bypassed"] is False
            and continuation["original_new_request_ceiling"]
            == scope["maximum_new_physical_requests"]
            and continuation["retained_responses_reused_without_refetch"]
            == continuation["new_requests_already_consumed"] == failure["new_physical_requests"]
            and continuation["remaining_new_request_allowance"]
            == scope["maximum_new_physical_requests"] - failure["new_physical_requests"],
            "guard-only continuation/history or unchanged original allowance mismatch")
    require(continuation["previous_source"] == artifacts[
        "producer/capture_nj_library_collection_20261023_failed_v1.py"
    ] and continuation["corrected_source"] == artifacts[
        "producer/capture_nj_library_collection_20261023_v1.py"
    ], "forensic failed/corrected collector producer bindings mismatch")
    nested = legacy._root(source / "sealed-first16")
    nested_sha = artifacts["sealed-first16/manifest.json"]["sha256"]
    nested_manifest, nested_batch, nested_ledger = _source(nested, nested_sha)
    require(nested_manifest["status"] == "immutable_first16_subset"
            and legacy._equal(nested_batch["catalog_items"], batch["catalog_items"])
            and legacy._equal(nested_batch["catalog_captures"], batch["catalog_captures"]),
            "immutable first16 catalogue evidence changed in full packet")
    for record in nested_ledger:
        require(any(legacy._equal(record, original) for original in ledger),
                "immutable first16 capture not retained exactly in full packet")
    for entry in nested_batch["new_pdfs"]:
        require(any(legacy._equal(entry, original) for original in batch["new_pdfs"]),
                "immutable first16 new PDF record changed in full packet")
    for name, binding in nested_manifest["artifacts"].items():
        if name.startswith("raw/") or name == "input-gap-queue.parquet":
            require(artifacts[name] == binding, "immutable first16 original artifact changed")


def _source(source, manifest_sha256):
    require(legacy._binding(legacy._regular(source / "manifest.json"))["sha256"]
            == _hash(manifest_sha256), "caller-pinned source manifest hash mismatch")
    manifest = legacy._json(source / "manifest.json")
    require(manifest.get("status") in SOURCE_STATUSES, "source is not a supported sealed packet")
    artifacts = manifest["artifacts"]
    legacy._inventory(artifacts)
    ledger_name = _ledger_name(source)
    require("manifest.json" not in artifacts
            and {"source-batch.json", "scope.json", ledger_name,
                 "input-gap-queue.parquet"} <= set(artifacts),
            "source packet required original inputs omitted")
    require(_tree(source) == set(artifacts) | {"manifest.json"},
            "source packet artifact inventory incomplete or unexpected member")
    for name, binding in artifacts.items():
        require(legacy._binding(legacy._regular(source / name)) == binding,
                f"sealed source artifact hash/size mismatch: {name}")
    batch = legacy._json(source / "source-batch.json")
    require(batch["status"] == SOURCE_STATUSES[manifest["status"]]
            and batch["all_source_approvals"] is False and batch["publication"] is False
            and batch["network_closed"] is True, "source status/closure/approval mismatch")
    ledger = (legacy._json(source / ledger_name) if ledger_name.endswith(".json")
              else legacy._jsonl(source / ledger_name))
    require(type(ledger) is list and bool(ledger), "selected capture ledger required")
    prefix = (legacy._jsonl(source / "seed-request-ledger.jsonl")
              if ledger_name == "request-ledger.jsonl" else [])
    require(not prefix or legacy._equal(ledger[:len(prefix)], prefix),
            "retained historical source prefix changed")
    prefix_ordinals = {c["ordinal"] for c in prefix}
    captures, raw = {}, set()
    for capture in ledger:
        require(type(capture) is dict and type(capture.get("ordinal")) is int
                and capture["ordinal"] not in captures
                and (capture.get("status") == 200 or capture["ordinal"] in prefix_ordinals),
                "duplicate or unsuccessful selected capture")
        require(type(capture.get("label")) is str and bool(capture["label"]),
                "absent selected capture label")
        if capture["ordinal"] in prefix_ordinals:
            members, location = _prefix_capture(source, capture)
            require(location is None or any(c["url"] == location for c in prefix),
                    "historical prefix redirect final response missing")
        else:
            require(legacy._verify_capture(source, capture) is None,
                    "unexpected unclosed transport redirect")
            members = legacy._capture_files(capture)
        names = set(members)
        require(not raw & names, "overlapping selected capture files")
        raw.update(names)
        captures[capture["ordinal"]] = capture
    require(raw == {name for name in artifacts if name.startswith("raw/")},
            "source capture file membership omission or unlisted raw evidence")
    catalogue = _catalogue(source, batch, captures)
    role_ordinals = {c["ordinal"] for c in batch["catalog_captures"]} | prefix_ordinals
    robots = [c for c in ledger if c.get("is_robots") is True
              and c["host"] == "repo.njstatelib.org"]
    require(bool(robots) and all(urlsplit(c["url"]).path == "/robots.txt" for c in robots),
            "retained original robots evidence missing")
    role_ordinals.update(c["ordinal"] for c in robots)
    require(type(batch["new_pdfs"]) is list and type(batch["reused_pdfs"]) is list,
            "explicit new/reused source lists required")
    item_ids, new_hashes = set(), set()
    for entry in batch["new_pdfs"] + batch["reused_pdfs"]:
        item = entry["catalog_item"]
        require(legacy._equal(catalogue.get(item["uuid"]), item),
                "PDF catalogue source membership mismatch")
        require(item["uuid"] not in item_ids, "duplicate new/reused catalogue source")
        item_ids.add(item["uuid"])
        for field in ("capture", "item_capture"):
            if field in entry:
                capture = entry[field]
                require(legacy._equal(captures.get(capture["ordinal"]), capture),
                        "PDF/item capture missing from selected packet")
                role_ordinals.add(capture["ordinal"])
    if manifest["status"] == "closed_complete_collection_capture":
        require(item_ids == set(catalogue),
                "closed complete collection omits catalogue source dispositions")
    for entry in batch["new_pdfs"]:
        capture = entry["capture"]
        require(entry["pdf"] == capture["body"]
                and entry["pdf_sha256"] == capture["body_sha256"]
                and type(entry["n_pages"]) is int and entry["n_pages"] > 0,
                "PDF original path/hash/page-count mismatch")
        require(entry["pdf_sha256"] not in new_hashes, "duplicate newly normalized PDF")
        new_hashes.add(entry["pdf_sha256"])
        _item_reference(source, entry, capture)
    reused_originals = [
        e.get("original_entry", e) for e in batch["reused_pdfs"]
    ]
    if prefix:
        seeds = legacy._json(source / "seed-source-batch-all8.json")["pdfs"]
        require(len(seeds) == len(reused_originals)
                and all(any(legacy._equal(e, seed) for seed in seeds) for e in reused_originals),
                "reused original entries not exactly retained seed sources")
    for entry, original in zip(batch["reused_pdfs"], reused_originals, strict=True):
        capture = original["capture"]
        require(legacy._equal(captures.get(capture["ordinal"]), capture)
                and original["pdf_sha256"] == capture["body_sha256"],
                "reused original PDF capture/hash missing or changed")
        _item_reference(source, entry, capture)
    reused_urls = {e["capture"]["url"] for e in reused_originals}
    new_urls = {e["capture"]["url"] for e in batch["new_pdfs"]}
    require(len(new_urls) == len(batch["new_pdfs"])
            and not new_urls & reused_urls, "exact reused PDF URL would be normalized again")
    require(role_ordinals == set(captures),
            "source capture is omitted from catalogue/new/reused/robots membership")
    scope = legacy._json(source / "scope.json")
    require(scope["all_state_publishers_remain_closed"] is True
            and scope["old_packets_immutable"] is True
            and scope["scientific_approval"] is False
            and scope["model_input_approved"] is False and scope["publication"] is False,
            "original source scope/approvals changed")
    require(all(record[flag] is False for record in (scope, batch)
                for flag in FLAGS if flag in record), "source approval promotion or mistyped false")
    require(scope["original_queue"] == artifacts["input-gap-queue.parquet"]
            or {k: scope["original_queue"].get(k) for k in ("sha256", "bytes")}
            == artifacts["input-gap-queue.parquet"], "source scope queue binding mismatch")
    if ledger_name == "request-ledger.jsonl":
        require(manifest["status"] == "closed_complete_collection_capture"
                and manifest["network_closed"] is True,
                "full copied source ledger requires an explicitly complete closed packet")
        require(all(manifest[flag] is False for flag in
                    ("model_input_approved", "scientific_approval", "publication")),
                "complete source manifest approval promotion")
        _full_receipt(source, batch, prefix, ledger, artifacts)
    return manifest, batch, ledger


def _separate(page_rows, *, context_qualified_introductions=None,
              qualify_supported_years=False, source_pdf_sha256=None,
              allow_single_page_versions=False, allow_printed_variants=False):
    whitespace = None
    if allow_printed_variants and source_pdf_sha256 in VERIFIED_WHITESPACE_PAGES:
        profile = VERIFIED_WHITESPACE_PAGES[source_pdf_sha256]
        require(bool(page_rows) and len({row["reader"] for row in page_rows}) == 1,
                "one complete reader required for a pinned whitespace page")
        page = next((row for row in page_rows
                     if row["page_ordinal"] == profile["page_ordinal"]), None)
        expected = profile["readers"][page_rows[0]["reader"]]
        require(page is not None and not page["errors"] and type(page["text"]) is str
                and not page["text"].strip()
                and legacy._sha(page["text"].encode()) == expected,
                "pinned whitespace page or physical-content witness changed")
        whitespace = {profile["page_ordinal"]: {
            "source_pdf_sha256": source_pdf_sha256,
            "page_ordinal": profile["page_ordinal"], "page_text_sha256": expected,
            "content_stream_sha256": profile["content_stream_sha256"],
            "only_whitespace_text_operations": True,
        }}
    if any(p["errors"] or type(p["text"]) is not str or (
           not p["text"].strip() and p["page_ordinal"] not in (whitespace or {}))
           for p in page_rows):
        return [], [{
            "page_ordinal": p["page_ordinal"], "disposition": "quarantined_reader",
            "version_ordinal": None, "text_preserved_in_full": True,
            "reason": "reader_error_or_empty_page_no_ocr_or_substitution",
        } for p in page_rows], "reader_error_or_empty_page_no_ocr_or_substitution"
    try:
        bridges = None
        prologues = None
        if allow_printed_variants and source_pdf_sha256 in PRINTED_PROLOGUE_WITNESSES:
            witness = PRINTED_PROLOGUE_WITNESSES[source_pdf_sha256]
            require(bool(page_rows) and len({row["reader"] for row in page_rows}) == 1,
                    "one complete reader required for a pinned enacted prologue")
            page_sha, prefix_sha = witness["readers"][page_rows[0]["reader"]]
            prologues = {witness["page_ordinal"]: {
                "source_pdf_sha256": source_pdf_sha256,
                "page_text_sha256": page_sha, "prefix_sha256": prefix_sha,
                "role": witness["role"],
            }}
        if qualify_supported_years and source_pdf_sha256 in UNLABELLED_PAGE_BRIDGES:
            profile = UNLABELLED_PAGE_BRIDGES[source_pdf_sha256]
            require(bool(page_rows) and len({row["reader"] for row in page_rows}) == 1,
                    "one complete reader required for a pinned page bridge")
            before, page, after = profile["readers"][page_rows[0]["reader"]]
            bridges = {profile["page_ordinal"]: {
                key: value for key, value in profile.items()
                if key not in {"readers", "page_ordinal"}
            } | {
                "source_pdf_sha256": source_pdf_sha256,
                "before_text_sha256": before, "page_text_sha256": page,
                "after_text_sha256": after,
            }}
        versions, dispositions = legacy.separate_versions(
            [p["text"] for p in page_rows],
            context_qualified_introductions=context_qualified_introductions,
            qualify_supported_years=qualify_supported_years,
            unlabelled_page_bridges=bridges,
            allow_single_page_versions=allow_single_page_versions,
            allow_printed_variants=allow_printed_variants,
            enacted_prologue_witnesses=prologues,
            whitespace_page_witnesses=whitespace,
        )
    except ValueError as exc:
        prefix = "incompatible NJ library archive: "
        require(str(exc).startswith(prefix), "unexpected separation failure")
        reason = "unsupported_complete_version_identity_or_boundary: " + str(exc)[len(prefix):]
        return [], [{
            "page_ordinal": p["page_ordinal"], "disposition": "quarantined_reader",
            "version_ordinal": None, "text_preserved_in_full": True, "reason": reason,
        } for p in page_rows], reason
    for disposition in dispositions:
        if disposition["disposition"] == "unselected_ancillary_or_unresolved_page":
            disposition["disposition"] = "quarantined_unresolved_page"
            disposition["reason"] = "no_supported_own_identity_and_complete_version"
    return versions, dispositions, (
        "complete_versions_with_unresolved_pages"
        if any(d["disposition"].startswith("quarantined") for d in dispositions)
        else "complete_versions_and_retained_ancillaries" if versions
        else "library_checklist_only_no_bill_text"
    )


def _extract(path, source_id):
    data = path.read_bytes()
    require(data.startswith(b"%PDF-"), "source is not a PDF")
    require({"pymupdf": legacy.pymupdf.__version__, "pypdf": legacy.pypdf.__version__} == TOOLS,
            "installed dual-reader versions changed")
    handler = legacy._Warnings()
    logger = logging.getLogger("pypdf")
    logger.addHandler(handler)
    try:
        with warnings.catch_warnings(record=True) as probe_warnings:
            warnings.simplefilter("always")
            probe = legacy.pypdf.PdfReader(io.BytesIO(data), strict=True)
            missing_contents = any("/Contents" not in p for p in probe.pages)
    finally:
        logger.removeHandler(handler)
    if not missing_contents:
        return legacy._extract(path, source_id)
    # Valid blank pages have no /Contents. pypdf's layout reader raises KeyError
    # for these, so retain that unsupported output explicitly rather than mutate
    # the PDF, invent a string, or lose the other reader's complete page outputs.
    pages, documents = [], []
    probe_messages = list(handler.rows)
    legacy.pymupdf.TOOLS.mupdf_warnings(reset=True)
    with legacy.pymupdf.open(stream=data, filetype="pdf") as fitz:
        for reader, document in (("pypdf", probe), ("pymupdf", fitz)):
            members = document.pages if reader == "pypdf" else document
            documents.append({
                "source_id": source_id, "reader": reader, "n_pages": len(document.pages)
                if reader == "pypdf" else len(document),
                "metadata": dict(document.metadata) if document.metadata is not None else None,
                "warnings": probe_messages if reader == "pypdf"
                else legacy.pymupdf.TOOLS.mupdf_warnings(reset=True),
                "errors": [], "python_warnings": [str(w.message) for w in probe_warnings]
                if reader == "pypdf" else [],
                "extraction_options": {
                    "profile": "complete_dual_reader_with_explicit_absent_contents",
                    "original_pdf_unchanged": True,
                },
            })
            for ordinal, page in enumerate(members, 1):
                row = {
                    "source_id": source_id, "reader": reader, "page_ordinal": ordinal,
                    "warnings": [], "python_warnings": [], "errors": [],
                    "geometry": {"mediabox": [float(v) for v in page.mediabox],
                                 "rotation": page.rotation},
                }
                handler.rows.clear()
                logger.addHandler(handler)
                try:
                    with warnings.catch_warnings(record=True) as page_warnings:
                        warnings.simplefilter("always")
                        if reader == "pypdf":
                            text = page.extract_text(extraction_mode="plain")
                            if "/Contents" not in page:
                                row["layout_text"] = row["layout_text_binding"] = None
                                row["errors"].append({
                                    "type": "UnsupportedLayoutAbsentContents",
                                    "message": "Original valid blank page has no /Contents; "
                                               "pypdf layout output unavailable, not fabricated.",
                                })
                            else:
                                layout = page.extract_text(extraction_mode="layout")
                                row["layout_text"] = layout
                                row["layout_text_binding"] = legacy._text_binding(layout)
                        else:
                            text = page.get_text("text", sort=False)
                            row["text_layout"] = page.get_text(
                                "dict", sort=False,
                                flags=legacy.pymupdf.TEXTFLAGS_DICT
                                & ~legacy.pymupdf.TEXT_PRESERVE_IMAGES,
                            )
                finally:
                    logger.removeHandler(handler)
                row["python_warnings"] = [str(w.message) for w in page_warnings]
                if reader == "pypdf":
                    row["warnings"] = list(handler.rows)
                else:
                    row["warnings"] = legacy.pymupdf.TOOLS.mupdf_warnings(reset=True)
                row["text"] = text
                row["text_binding"] = legacy._text_binding(text)
                pages.append(row)
    return legacy._decode(json.dumps(pages)), legacy._decode(json.dumps(documents))


def _view(page_rows, version, context, entry, reader, ordinal, ledger_name, source_id):
    row = legacy._view(page_rows, version, context, entry, reader, ordinal)
    row["view_id"] = (
        f"nj-library-collection:{entry['catalog_item']['uuid']}:"
        f"{entry['pdf_sha256']}:{ordinal}:{reader}"
    )
    row["source_status"] = STATUS
    row["source_members"]["capture_records"] = "source-evidence/" + ledger_name
    row["source_members"]["original_queue"] = "input_gap_queue.parquet"
    row["source_members"]["catalogue_and_batch"] = "source-evidence/source-batch.json"
    row["source_members"]["sealed_manifest"] = "source-evidence/manifest.json"
    for span in row["source_identity"]["printed_evidence"]:
        span["source_id"] = source_id
    row.update(dict.fromkeys(FLAGS, False))
    require(row["archive_generated_prologue_preserved"] is False,
            "PDF text must not advertise a fabricated machine prologue")
    return row


def _context_introductions(directory, manifest_sha256):
    directory = legacy._root(directory)
    manifest_path = legacy._regular(directory / "manifest.json")
    require(legacy._binding(manifest_path)["sha256"] == _hash(manifest_sha256),
            "context-evidence manifest anchor changed")
    manifest = legacy._json(manifest_path)
    names = {"contexts.jsonl", "bill_actions.parquet", "bill_extraction_manifest.json"}
    require(set(manifest) == {"schema", "artifacts"}
            and manifest["schema"] in {
                CONTEXT_SCHEMA, CONTEXT_ALL_DATES_SCHEMA, CONTEXT_SINGLE_PAGE_SCHEMA,
                CONTEXT_PRINTED_VARIANTS_SCHEMA,
            }
            and set(manifest["artifacts"]) == names
            and _tree(directory) == names | {"manifest.json"},
            "complete original context/action evidence required")
    for name, expected in manifest["artifacts"].items():
        require(legacy._binding(legacy._regular(directory / name)) == expected,
                f"original context evidence changed: {name}")
    require(manifest["artifacts"]["contexts.jsonl"]["sha256"] == ORIGINAL_CONTEXTS_SHA256
            and manifest["artifacts"]["bill_extraction_manifest.json"]["sha256"]
            == ORIGINAL_EXTRACTION_SHA256,
            "original frozen population/extraction trust anchors changed")
    extraction = legacy._json(directory / "bill_extraction_manifest.json")
    require(extraction["status"] == "complete_extraction_not_source_certification"
            and extraction["scientific_certification"] == "not_performed"
            and extraction["artifacts"]["bill_actions.parquet"]["sha256"]
            == manifest["artifacts"]["bill_actions.parquet"]["sha256"]
            and extraction["artifacts"]["bill_actions.parquet"]["rows"]
            == pq.read_metadata(directory / "bill_actions.parquet").num_rows,
            "actions do not match the complete original extraction")
    contexts, seen = {}, set()
    years = (("2022-", "2023-", "2024-") if manifest["schema"] in {
        CONTEXT_ALL_DATES_SCHEMA, CONTEXT_SINGLE_PAGE_SCHEMA, CONTEXT_PRINTED_VARIANTS_SCHEMA,
    } else ("2024-",))
    with (directory / "contexts.jsonl").open("rb") as stream:
        for line in stream:
            row = legacy._decode(line)
            require(type(row) is dict and type(row.get("bill_id")) is str
                    and row["bill_id"] not in seen, "duplicate or untyped original context")
            seen.add(row["bill_id"])
            if (row.get("state") == "NJ" and row.get("session_identifier") == "220"
                    and re.fullmatch(r"[AS] [1-9][0-9]*", row.get("identifier", ""))
                    and type(row.get("source_introduction_date")) is str
                    and row["source_introduction_date"].startswith(years)):
                require(row["identifier"] not in contexts, "ambiguous original tail context")
                contexts[row["identifier"]] = row
    require(bool(contexts), "no explicit original tail-session contexts")
    actions = pq.read_table(directory / "bill_actions.parquet", filters=[
        ("state", "=", "NJ"),
        ("bill_id", "in", [row["bill_id"] for row in contexts.values()]),
    ]).to_pylist()
    actions_by_bill = defaultdict(list)
    for action in actions:
        actions_by_bill[action["bill_id"]].append(action)
    qualified = {}
    for identifier, row in contexts.items():
        ids = legacy._decode(row["origin_introduction_action_ids"])
        require(type(ids) is list and all(type(value) is str for value in ids),
                "typed original introduction-action ID list required")
        qualified[identifier] = {
            "original_context": row,
            "origin_introduction_actions": [
                action for action in actions_by_bill[row["bill_id"]]
                if action["action_id"] in ids
            ],
        }
    inventory = dict(manifest["artifacts"])
    inventory["manifest.json"] = legacy._binding(manifest_path)
    return qualified, inventory


def _gap_queue(source, queue_path, queue_sha256, *, allow_original_subset=False):
    queue_binding = legacy._binding(legacy._regular(queue_path))
    require(queue_binding["sha256"] == _hash(queue_sha256),
            "caller-pinned queue hash changed")
    original = pq.read_table(source / "input-gap-queue.parquet")
    gap = pq.read_table(queue_path)
    if not allow_original_subset:
        require(queue_binding == legacy._binding(source / "input-gap-queue.parquet"),
                "caller-pinned original queue hash/size mismatch")
    else:
        require(gap.schema.equals(original.schema, check_metadata=True),
                "original gap queue schema changed")
        by_id = {row["bill_id"]: row for row in original.to_pylist()}
        require(len(by_id) == original.num_rows, "duplicate original source queue ID")
        rows = gap.to_pylist()
        require(len({row["bill_id"] for row in rows}) == len(rows)
                and all(row["bill_id"] in by_id
                        and legacy._equal(row, by_id[row["bill_id"]]) for row in rows),
                "tail queue is not an exact whole-row subset of the original queue")
    return gap


def _replay(source, queue_path, source_sha256, queue_sha256, *,
            context_qualified_introductions=None, qualify_supported_years=False,
            allow_single_page_versions=False, allow_printed_variants=False):
    source_manifest, batch, ledger = _source(source, source_sha256)
    ledger_name = _ledger_name(source)
    gap = _gap_queue(
        source, queue_path, queue_sha256,
        allow_original_subset=context_qualified_introductions is not None,
    )
    originals = gap.to_pylist()
    by_key, bill_ids = defaultdict(list), set()
    for index, row in enumerate(originals):
        require(all(type(row.get(k)) is str for k in (
            "bill_id", "state", "session_identifier", "identifier",
        )) and row["bill_id"] not in bill_ids, "original queue typed identity or duplicate ID")
        bill_ids.add(row["bill_id"])
        if row["state"] == "NJ" and re.fullmatch(r"[AS] [1-9][0-9]*", row["identifier"]):
            by_key[legacy._key(row)].append(index)
    pages, documents, versions, views, dispositions, sources, comparisons = (
        [] for _ in range(7)
    )
    accepted, matched = set(), defaultdict(list)
    label_counts = Counter(e["capture"]["label"] for e in batch["new_pdfs"])
    reused_hashes = {e.get("original_entry", e)["pdf_sha256"] for e in batch["reused_pdfs"]}
    for entry in batch["new_pdfs"]:
        label = (
            entry["capture"]["label"]
            if ledger_name == "request-ledger.snapshot.json"
            and label_counts[entry["capture"]["label"]] == 1
            else f"nj-library-collection-source:{entry['catalog_item']['uuid']}:"
                 f"{entry['pdf_sha256']}"
        )
        extracted, docs = _extract(source / entry["pdf"], label)
        require(len(docs) == 2 and {d["reader"] for d in docs} == set(TOOLS)
                and all(d["n_pages"] == entry["n_pages"] for d in docs),
                "source PDF actual dual-reader page-count mismatch")
        pages.extend(extracted)
        documents.extend(docs)
        structures = {}
        for reader in ("pypdf", "pymupdf"):
            page_rows = [p for p in extracted if p["reader"] == reader]
            require([p["page_ordinal"] for p in page_rows]
                    == list(range(1, entry["n_pages"] + 1)),
                    "complete every-page reader extraction required")
            if entry["pdf_sha256"] in reused_hashes:
                reason = "byte_identical_prior_reused_archive_source_not_new_text_evidence"
                source_versions = []
                source_dispositions = [{
                    "page_ordinal": p["page_ordinal"],
                    "disposition": "quarantined_reused_content", "version_ordinal": None,
                    "text_preserved_in_full": True, "reason": reason,
                } for p in page_rows]
            else:
                source_versions, source_dispositions, reason = _separate(
                    page_rows, context_qualified_introductions=context_qualified_introductions,
                    qualify_supported_years=qualify_supported_years,
                    source_pdf_sha256=entry["pdf_sha256"],
                    allow_single_page_versions=allow_single_page_versions,
                    allow_printed_variants=allow_printed_variants,
                )
            structures[reader] = [
                (v["identifier"], v["kind"], v["page_ordinals"], v["boundary"])
                for v in source_versions
            ]
            dispositions.extend({"source_id": label, "reader": reader, **d}
                                for d in source_dispositions)
            source_record = {
                "source_id": label, "catalog_item_id": entry["catalog_item"]["uuid"],
                "reader": reader, "disposition": reason,
                "page_ordinals": list(range(1, entry["n_pages"] + 1)),
                "original_pdf_preserved": True, "complete_reader_output_preserved": True,
                "supported_versions": len(source_versions), "matched_views": 0,
            }
            for ordinal, version in enumerate(source_versions, 1):
                matches = by_key.get(legacy._key(version), [])
                require(len(matches) <= 1, "ambiguous exact original queue identity")
                disposition = "no_exact_original_queue_candidate"
                if matches:
                    index = matches[0]
                    context = originals[index]
                    require(context["neither_source_observed"] is True
                            and all(context[flag] is False for flag in (
                                "model_input_approved", "filing_time_text_certified",
                                "analytical_admission",
                            )), "original gap approval or unresolved status mismatch")
                    accepted.add(index)
                    view = _view(
                        page_rows, version, context, entry, reader, ordinal, ledger_name, label,
                    )
                    if qualify_supported_years:
                        view["view_id"] = (
                            f"nj-library-original-context:{entry['catalog_item']['uuid']}:"
                            f"{entry['pdf_sha256']}:{version['page_ordinals'][0]}:{reader}:"
                            f"context:{context['bill_id']}"
                        )
                    views.append(view)
                    matched[index].append(view["view_id"])
                    source_record["matched_views"] += 1
                    disposition = "exact_original_queue_candidate_retained"
                versions.append({
                    "source_id": label, "reader": reader, "version_ordinal": ordinal,
                    "queue_disposition": disposition,
                    "candidate_bill_id": originals[matches[0]]["bill_id"] if matches else None,
                    **version,
                })
            sources.append(source_record)
        for ordinal in range(1, entry["n_pages"] + 1):
            pair = [p for p in extracted if p["page_ordinal"] == ordinal]
            comparisons.append({
                "source_id": label, "page_ordinal": ordinal,
                "reader_texts_exactly_equal": pair[0]["text"] == pair[1]["text"],
                "reader_text_bindings": {p["reader"]: p["text_binding"] for p in pair},
                "reader_version_structures_equal": legacy._equal(
                    structures["pypdf"], structures["pymupdf"],
                ), "ground_truth_reader": None,
            })
    contexts = gap.filter(pa.array([i in accepted for i in range(len(originals))], type=pa.bool_()))
    queue_dispositions = []
    for index, original in enumerate(originals):
        reason = (
            "retained_exact_context_reader_alternatives_count_once" if index in accepted else
            "no_accepted_candidate_in_selected_source_packet"
            if original["state"] == "NJ" and original["session_identifier"] == "220"
            and re.fullmatch(r"[AS] [1-9][0-9]*", original["identifier"])
            else "outside_supported_printed_identity_profile"
        )
        queue_dispositions.append({
            "original_row_ordinal": index, "original_queue_row": original,
            "disposition": reason, "view_ids": matched.get(index, []),
            "newly_covered": index in accepted, **dict.fromkeys(FLAGS, False),
        })
    source_version_keys = {
        (v["source_id"], v["identifier"], v["kind"], tuple(v["page_ordinals"]))
        for v in versions
    }
    counts = {
        "source_pdfs": len(batch["new_pdfs"]),
        "reused_pdfs_not_normalized": len(batch["reused_pdfs"]),
        "catalogue_items": len(batch["catalog_items"]),
        "catalogue_pages": len(batch["catalog_captures"]),
        "selected_capture_records": len(ledger), "original_gap_contexts": gap.num_rows,
        "newly_covered_contexts": len(accepted),
        "remaining_queue_contexts": gap.num_rows - len(accepted),
        "text_views": len(views), "source_versions": len(source_version_keys),
        "reader_versions": len(versions),
        "versions_without_queue_candidate": sum(
            v["queue_disposition"] == "no_exact_original_queue_candidate" for v in versions
        ),
        "all_source_pdf_pages": sum(e["n_pages"] for e in batch["new_pdfs"]),
        "all_reader_pages": len(pages),
        "selected_reader_pages": sum(len(v["page_ordinals"]) for v in versions),
        "quarantined_reader_pages": sum(
            d["disposition"].startswith("quarantined") for d in dispositions
        ),
        "ancillary_reader_pages": sum(
            not d["disposition"].startswith("quarantined")
            and d["disposition"] != "selected_complete_version" for d in dispositions
        ),
        "reader_page_strings_differ": sum(not c["reader_texts_exactly_equal"] for c in comparisons),
        "reader_pages_with_errors": sum(bool(p["errors"]) for p in pages),
        "reader_pages_with_warnings": sum(
            bool(p["warnings"] or p["python_warnings"]) for p in pages
        ),
        "source_disposition_counts": dict(Counter(s["disposition"] for s in sources)),
        "queue_disposition_counts": dict(Counter(d["disposition"] for d in queue_dispositions)),
    }
    require(counts["selected_reader_pages"] + counts["quarantined_reader_pages"]
            + counts["ancillary_reader_pages"] == counts["all_reader_pages"],
            "complete page disposition accounting mismatch")
    report = {
        "schema": SCHEMA, "counts": counts, "tools": TOOLS, "limits": LIMITS,
        "approvals": dict.fromkeys(FLAGS, False), "source_packet_status": source_manifest["status"],
        "source_batch_status": batch["status"],
        "complete_collection_capture": (
            source_manifest["status"] == "closed_complete_collection_capture"
        ),
        "source_inventory_scope": (
            "explicit_sealed_packet_only_not_complete_parent_transport_history"
        ),
        "selected_capture_records": ledger, "source_batch_record": batch,
        "original_scope_record": legacy._json(source / "scope.json"),
        "reader_comparisons": comparisons, "original_queue_columns": gap.column_names,
        "full_original_queue_schema": str(gap.schema),
        "reused_source_dispositions": [
            {"source_record": e, "disposition": "reused_prior_archive_not_normalized",
             "new_views": 0} for e in batch["reused_pdfs"]
        ],
        "unprocessed_catalogue_item_ids": [
            i["uuid"] for i in batch["catalog_items"]
            if i["uuid"] not in {e["catalog_item"]["uuid"]
                                for e in batch["new_pdfs"] + batch["reused_pdfs"]}
        ],
    }
    if context_qualified_introductions is not None:
        report["limits"] = {
            **LIMITS,
            "printed_identity_profile": "Default own 220th covers, plus 2024 covers only "
            "with an exact unchanged original context and matching original origin-introduction "
            "action IDs, organization, chamber and literal ISO calendar date. No timezone "
            "conversion, session-end repair or implied filing-time certification.",
        }
        count_name = ("context_qualified_original_date_views" if qualify_supported_years
                      else "context_qualified_tail_views")
        counts[count_name] = sum(
            "original_context_introduction_proof" in row["source_version"] for row in views
        )
        report["original_gap_queue_relation"] = "exact_whole_row_subset_of_original_source_queue"
        if qualify_supported_years:
            report["limits"]["printed_identity_profile"] = (
                "Own 220th Legislature covers with exact unchanged original context/action "
                "proof for supplied 2022/2023/2024 introductions. Complete section-specific "
                "effective clauses are retained literally. No session-end, date, party "
                "or policy-text repair; all prior packets and their profiles remain frozen."
            )
            report["limits"]["unsupported_separation"] = (
                "Ambiguous identities, folios or boundaries quarantine the whole reader. "
                "Known disjoint ranges without complete policy/statement evidence are "
                "retained and quarantined individually, never admitted as policy inputs; "
                "complete same-bill siblings expose those source-completeness warnings."
            )
            counts["accepted_views_with_quarantined_same_bill_versions"] = sum(
                bool(row["source_version"].get("quarantined_same_bill_source_versions"))
                for row in views
            )
        if allow_single_page_versions:
            report["limits"]["complete_single_page_versions"] = (
                "Explicit single-page context profile only. A complete own body/effective "
                "clause, introduced statement when applicable, exact identity/action proof "
                "and unambiguous next-version/ancillary/PDF boundary remain required. "
                "Short partial pages are retained in quarantine, never admitted."
            )
            counts["accepted_complete_single_page_views"] = sum(
                row["source_version"].get("complete_single_page_policy_version") is True
                for row in views
            )
        if allow_printed_variants:
            report["limits"]["printed_variants"] = (
                "Explicit printed-variant context profile only. Literal bracketed own "
                "reprint covers, fifth reprints and No, punctuation are preserved, not "
                "rewritten. Printed reprint labels must agree on every continuation; "
                "enacted witnesses prefer a unique independently printed introduced cover. "
                "Exact pinned codification prefixes remain literal. Prefiling covers supply "
                "no inferred introduction date and remain quarantined with their dependent versions. "
                "Bounded enacted versions without a unique same-bill session witness remain "
                "quarantined without an inferred session. A source-scoped whitespace separator "
                "is retained with exact PDF/page/content-stream hashes, never inserted into policy text."
            )
    if ledger_name == "request-ledger.jsonl":
        prefix = legacy._jsonl(source / "seed-request-ledger.jsonl")
        counts["retained_inherited_prefix_records"] = len(prefix)
        counts["current_collection_http_captures"] = len(ledger) - len(prefix)
        counts["known_aggregate_physical_exchanges"] = batch["known_aggregate_physical_exchanges"]
        counts["unretained_inherited_identity_exchanges"] = 1
        counts["new_source_pdf_bytes"] = sum(e["capture"]["body_bytes"] for e in batch["new_pdfs"])
        report["full_capture_completion_receipt"] = legacy._json(
            source / "capture-completion-report.json",
        )
        report["forensic_history_not_current_capture_failure"] = legacy._json(
            source / "failure.json",
        )
        report["guard_only_continuation_receipt"] = legacy._json(
            source / "schema-v2-continuation.json",
        )
        report["retained_original_prefix_records"] = prefix
        report["current_collection_capture_records"] = ledger[len(prefix):]
        report["immutable_first16_source_manifest"] = source_manifest["artifacts"][
            "sealed-first16/manifest.json"
        ]
    products = {
        "views.jsonl": views, "pages.jsonl": pages, "documents.jsonl": documents,
        "versions.jsonl": versions, "page_dispositions.jsonl": dispositions,
        "source_dispositions.jsonl": sources, "queue_dispositions.jsonl": queue_dispositions,
        "original_queue_rows.jsonl": contexts.to_pylist(),
    }
    return products, contexts, report


def _producers():
    return {
        "producer/nj_library_collection.py": legacy._regular(Path(__file__).absolute()),
        "producer/nj_library_text.py": legacy._regular(Path(legacy.__file__).absolute()),
    }


def build_nj_collection(source_directory, gap_queue, out_directory, *,
                        source_manifest_sha256, gap_queue_sha256,
                        context_evidence=None, context_evidence_sha256=None):
    """Build a new ignored packet from caller-pinned, genuinely sealed inputs."""
    source = legacy._root(source_directory)
    queue = legacy._regular(Path(gap_queue).absolute())
    out = Path(out_directory).absolute()
    require(not out.exists() and not out.is_symlink() and out.resolve() == out,
            "new unlinked output directory required")
    require(not out.is_relative_to(source) and not source.is_relative_to(out)
            and not queue.is_relative_to(out), "input/output overlap")
    source_sha, queue_sha = _hash(source_manifest_sha256), _hash(gap_queue_sha256)
    source_manifest, _, _ = _source(source, source_sha)
    require((context_evidence is None) == (context_evidence_sha256 is None),
            "context evidence requires both a directory and external manifest SHA256")
    qualified, context_inventory, qualify_supported_years = None, {}, False
    allow_single_page_versions = False
    allow_printed_variants = False
    if context_evidence is not None:
        context_evidence = legacy._root(context_evidence)
        require(not context_evidence.is_relative_to(out) and not out.is_relative_to(context_evidence),
                "context-evidence/output overlap")
        qualified, context_inventory = _context_introductions(
            context_evidence, context_evidence_sha256,
        )
        context_schema = legacy._json(context_evidence / "manifest.json")["schema"]
        qualify_supported_years = context_schema in {
            CONTEXT_ALL_DATES_SCHEMA, CONTEXT_SINGLE_PAGE_SCHEMA, CONTEXT_PRINTED_VARIANTS_SCHEMA,
        }
        allow_single_page_versions = context_schema in {
            CONTEXT_SINGLE_PAGE_SCHEMA, CONTEXT_PRINTED_VARIANTS_SCHEMA,
        }
        allow_printed_variants = context_schema == CONTEXT_PRINTED_VARIANTS_SCHEMA
    _gap_queue(source, queue, queue_sha, allow_original_subset=qualified is not None)
    source_names = set(source_manifest["artifacts"]) | {"manifest.json"}
    before = {name: legacy._binding(source / name) for name in sorted(source_names)}
    before_queue = legacy._binding(queue)
    before_producers = {name: legacy._binding(path) for name, path in _producers().items()}
    out.mkdir(parents=True)
    evidence = out / "source-evidence"
    for name in sorted(source_names):
        legacy._copy(source / name, evidence / name)
    for name in context_inventory:
        legacy._copy(context_evidence / name, out / "context-evidence" / name)
    legacy._copy(queue, out / "input_gap_queue.parquet")
    products, contexts, report = _replay(evidence, out / "input_gap_queue.parquet",
                                        source_sha, queue_sha,
                                        context_qualified_introductions=qualified,
                                        qualify_supported_years=qualify_supported_years,
                                        allow_single_page_versions=allow_single_page_versions,
                                        allow_printed_variants=allow_printed_variants)
    for name, rows in products.items():
        legacy._write_rows(out / name, rows)
    pq.write_table(contexts, out / "context_inventory.parquet")
    legacy._write(out / "report.json", report)
    legacy._write(out / "source_inventory.json", before)
    after = {name: legacy._binding(legacy._regular(source / name)) for name in sorted(source_names)}
    require(_tree(source) == source_names and legacy._equal(before, after)
            and before_queue == legacy._binding(queue),
            "original inputs changed during normalization")
    require(
        before_producers == {name: legacy._binding(path) for name, path in _producers().items()},
        "producer dependencies changed during normalization",
    )
    consumed = {
        "before": before, "after": after, "original_queue_before": before_queue,
        "original_queue_after": legacy._binding(queue),
        "all_original_inputs_unchanged": True,
        "scope": "explicit_sealed_packet_only_not_parent_root_or_entire_transport_history",
    }
    if context_inventory:
        require(context_inventory == {
            name: legacy._binding(legacy._regular(context_evidence / name))
            for name in context_inventory
        }, "original context evidence changed during normalization")
        consumed["context_introduction_evidence_before"] = context_inventory
        consumed["context_introduction_evidence_after"] = context_inventory
    legacy._write(out / "consumed_input_hashes.json", consumed)
    for name, path in _producers().items():
        legacy._copy(path, out / name)
    artifacts = PRODUCTS | {"source-evidence/" + name for name in source_names}
    artifacts |= {"context-evidence/" + name for name in context_inventory}
    manifest = {
        "schema": SCHEMA, "provider": PROVIDER, "status": STATUS,
        "source_manifest_sha256": source_sha, "gap_queue_sha256": queue_sha,
        "tools": TOOLS, "approvals": dict.fromkeys(FLAGS, False),
        "source_packet_status": source_manifest["status"], "counts": report["counts"],
        "packet_artifacts": {name: legacy._binding(out / name) for name in sorted(artifacts)},
    }
    if context_inventory:
        manifest["context_introduction_evidence_sha256"] = context_evidence_sha256
    legacy._write(out / "manifest.json", manifest)
    del products, contexts, report
    load_nj_collection(out, source_manifest_sha256=source_sha, gap_queue_sha256=queue_sha)
    return manifest


def load_nj_collection(root, metadata=None, *, source_manifest_sha256=None,
                       gap_queue_sha256=None, context_evidence_sha256=None):
    """Independently re-extract and replay; return (views, contexts, pins, manifest).

    Metadata follows the archive loader contract: exact bill/state/session/type,
    no duplicate matched IDs, and exact values/types for every overlapping original
    field. The full original queue is always independently replayed regardless.
    Optional external hashes protect source trust anchors, beyond artifact replay.
    """
    directory = legacy._root(root)
    manifest_path = legacy._regular(directory / "manifest.json")
    manifest = legacy._json(manifest_path)
    required_fields = {
        "schema", "provider", "status", "source_manifest_sha256", "gap_queue_sha256",
        "tools", "approvals", "source_packet_status", "counts", "packet_artifacts",
    }
    require(type(manifest) is dict, "typed normalized manifest required")
    if "context_introduction_evidence_sha256" in manifest:
        required_fields.add("context_introduction_evidence_sha256")
    require(set(manifest) == required_fields, "invalid normalized manifest fields")
    require(manifest["schema"] == SCHEMA and manifest["provider"] == PROVIDER
            and manifest["status"] == STATUS and legacy._equal(manifest["tools"], TOOLS)
            and legacy._equal(manifest["approvals"], dict.fromkeys(FLAGS, False)),
            "normalized schema/provider/tools/approval mismatch")
    for key, external in (("source_manifest_sha256", source_manifest_sha256),
                          ("gap_queue_sha256", gap_queue_sha256)):
        _hash(manifest[key])
        if external is not None:
            require(manifest[key] == _hash(external), "external source/queue trust anchor changed")
    artifacts = manifest["packet_artifacts"]
    legacy._inventory(artifacts)
    require(set(artifacts) >= PRODUCTS
            and _tree(directory) == set(artifacts) | {"manifest.json"},
            "normalized packet inventory omission or unexpected member")
    pins = {"manifest.json": legacy._binding(manifest_path)["sha256"]}
    for name, binding in artifacts.items():
        require(legacy._binding(legacy._regular(directory / name)) == binding,
                f"packet artifact binding mismatch: {name}")
        pins[name] = binding["sha256"]
    historical = SEALED_PRODUCERS.get(pins["manifest.json"])
    for name, path in _producers().items():
        expected = historical[name] if historical else legacy._binding(path)
        require(artifacts[name] == expected, "installed producer dependency mismatch")
        if historical and name == "producer/nj_library_text.py":
            previous_tail = SEALED_PRODUCERS[
                "3922c090c6d937385c57818b9a3f065ebee1f6168a3cedc9b842b8095e5bdeae"
            ]["producer/nj_library_text.py"]
            previous_all_dates = SEALED_PRODUCERS[
                "81771d07dc9f41a79547193e26e220bfa71015e57d912eb587ad749373d426ab"
            ]["producer/nj_library_text.py"]
            previous_single_page = SEALED_PRODUCERS[
                "5298ca4dc50ee84b343573402db8e92443700f911838ecf6dfb7645c17aef256"
            ]["producer/nj_library_text.py"]
            require(expected in (
                legacy._binding(path), legacy.STRICT_2023_PRODUCER,
                previous_tail, previous_all_dates, previous_single_page,
            ),
                    "historical extraction dependency changed")
    qualified, context_inventory, qualify_supported_years = None, {}, False
    allow_single_page_versions = False
    allow_printed_variants = False
    if "context_introduction_evidence_sha256" in manifest:
        context_sha = _hash(manifest["context_introduction_evidence_sha256"])
        if context_evidence_sha256 is not None:
            require(context_sha == _hash(context_evidence_sha256),
                    "external context evidence anchor changed")
        qualified, context_inventory = _context_introductions(
            directory / "context-evidence", context_sha,
        )
        context_schema = legacy._json(directory / "context-evidence/manifest.json")["schema"]
        qualify_supported_years = context_schema in {
            CONTEXT_ALL_DATES_SCHEMA, CONTEXT_SINGLE_PAGE_SCHEMA, CONTEXT_PRINTED_VARIANTS_SCHEMA,
        }
        allow_single_page_versions = context_schema in {
            CONTEXT_SINGLE_PAGE_SCHEMA, CONTEXT_PRINTED_VARIANTS_SCHEMA,
        }
        allow_printed_variants = context_schema == CONTEXT_PRINTED_VARIANTS_SCHEMA
    else:
        require(context_evidence_sha256 is None, "expected context evidence is missing")
    source = legacy._root(directory / "source-evidence")
    source_manifest, _, _ = _source(source, manifest["source_manifest_sha256"])
    source_names = set(source_manifest["artifacts"]) | {"manifest.json"}
    source_inventory = {name: legacy._binding(source / name) for name in sorted(source_names)}
    require(set(artifacts) == PRODUCTS | {"source-evidence/" + n for n in source_names}
            | {"context-evidence/" + n for n in context_inventory}
            and legacy._equal(legacy._json(directory / "source_inventory.json"), source_inventory)
            and manifest["source_packet_status"] == source_manifest["status"],
            "finite source inventory/status mismatch")
    products, expected_contexts, report = _replay(
        source, directory / "input_gap_queue.parquet",
        manifest["source_manifest_sha256"], manifest["gap_queue_sha256"],
        context_qualified_introductions=qualified,
        qualify_supported_years=qualify_supported_years,
        allow_single_page_versions=allow_single_page_versions,
        allow_printed_variants=allow_printed_variants,
    )
    for name, rows in products.items():
        with (directory / name).open("rb") as stream:
            for expected_row in rows:
                line = stream.readline()
                require(bool(line) and legacy._equal(legacy._decode(line), expected_row),
                        f"complete text/identity/queue/flags {name} replay mismatch")
            require(not stream.read(1), f"unexpected additional {name} replay row")
    contexts = pq.read_table(directory / "context_inventory.parquet")
    require(contexts.equals(expected_contexts, check_metadata=True),
            "original full context fields/schema replay mismatch")
    require(legacy._equal(legacy._json(directory / "report.json"), report)
            and legacy._equal(manifest["counts"], report["counts"]),
            "complete report/count replay mismatch")
    queue_binding = artifacts["input_gap_queue.parquet"]
    expected_consumed = {
        "before": source_inventory, "after": source_inventory,
        "original_queue_before": queue_binding, "original_queue_after": queue_binding,
        "all_original_inputs_unchanged": True,
        "scope": "explicit_sealed_packet_only_not_parent_root_or_entire_transport_history",
    }
    if context_inventory:
        expected_consumed["context_introduction_evidence_before"] = context_inventory
        expected_consumed["context_introduction_evidence_after"] = context_inventory
    require(legacy._equal(legacy._json(directory / "consumed_input_hashes.json"), expected_consumed),
            "original input before/after receipt replay mismatch")
    context_rows = contexts.to_pylist()
    if metadata is not None:
        legacy._current_metadata(context_rows, metadata)
    return products["views.jsonl"], context_rows, pins, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--source-dir", type=Path, required=True)
    build.add_argument("--source-manifest-sha256", required=True)
    build.add_argument("--gap-queue", type=Path, required=True)
    build.add_argument("--gap-queue-sha256", required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    build.add_argument("--context-evidence", type=Path,
                       help="complete pinned original context/action evidence for 220th tail covers")
    build.add_argument("--context-evidence-sha256",
                       help="external SHA256 of the context-evidence manifest")
    verify = commands.add_parser("verify", aliases=["replay"])
    verify.add_argument("--directory", type=Path, required=True)
    verify.add_argument("--metadata", type=Path)
    verify.add_argument("--source-manifest-sha256")
    verify.add_argument("--gap-queue-sha256")
    verify.add_argument("--context-evidence-sha256")
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_nj_collection(
            args.source_dir, args.gap_queue, args.out_dir,
            source_manifest_sha256=args.source_manifest_sha256,
            gap_queue_sha256=args.gap_queue_sha256,
            context_evidence=args.context_evidence,
            context_evidence_sha256=args.context_evidence_sha256,
        )
    else:
        metadata = (
            pq.read_table(legacy._regular(args.metadata.absolute())) if args.metadata else None
        )
        _, _, _, manifest = load_nj_collection(
            args.directory, metadata,
            source_manifest_sha256=args.source_manifest_sha256,
            gap_queue_sha256=args.gap_queue_sha256,
            context_evidence_sha256=args.context_evidence_sha256,
        )
    print(json.dumps({"schema": SCHEMA, "counts": manifest["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

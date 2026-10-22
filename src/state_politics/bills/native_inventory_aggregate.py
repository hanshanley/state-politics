"""Offline full-query aggregation over hash-bound native page and source-index evidence.

Collection is deliberately absent. A reviewed contract binds a frozen parser, source
scope and exact aliases; neither query-parameter stripping nor first-page success proves
a complete query. Publisher-listed coverage never grants introduction/text/admission
certification.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import yaml

from ..provenance import sha256_file

FLAGS = {
    "scientific_approval": False,
    "model_approval": False,
    "analytical_admission": False,
    "full_text_certified": False,
    "sourceclosure_certification": False,
    "introduced_universe_certified": False,
    "canonical_join_certification": False,
    "event_date_certification": False,
    "original_version_certification": False,
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_manifest(path: Path) -> dict:
    manifest = _json(path)
    for name, digest in manifest["files"].items():
        target = (path.parent / name).resolve()
        if not target.is_relative_to(path.parent.resolve()) or sha256_file(target) != digest:
            raise ValueError(f"manifest file mismatch: {name}")
    return manifest


def _bound_file(contract_path: Path, specification: dict) -> Path:
    path = (contract_path.parent / specification["path"]).resolve()
    if sha256_file(path) != specification["sha256"]:
        raise ValueError(f"contract input mismatch: {path}")
    return path


def finite_pages_complete(pages: list[dict]) -> bool:
    """Require the entire finite page set and exact forward edges, not page-one success."""
    if not pages:
        return False
    expected = pages[0]["pages"]
    return (
        expected > 0
        and len(pages) == expected
        and [page["page"] for page in pages] == list(range(1, expected + 1))
        and all(
            page["pages"] == expected
            and page["page_body_complete"]
            and page["terminal_document_closed"]
            for page in pages
        )
        and all(
            any(link["url"] in following["request_urls"] for link in page["pagination_links"])
            for page, following in zip(pages[:-1], pages[1:], strict=True)
        )
    )


def prove_aliases(evidence: dict, declarations: list[dict]) -> list[dict]:
    """Only an exact observed source URL and a scope-matching page-one body can alias."""
    proven = []
    ids = Counter(row["alias_id"] for row in declarations)
    for declaration in declarations:
        alias = copy.deepcopy(declaration)
        target = evidence["facts"].get(alias["target_exchange"])
        observations = []
        for index in evidence["indexes"]:
            if alias["kind"] == "type_index" and (index["state"], index["session"]) == (
                alias["state"],
                alias["session"],
            ):
                observations.extend(
                    {"source_exchange": index["source_exchange"], **link}
                    for link in index["links"]
                    if link["url"] == alias["source_url"] and link["measure_type"] == alias["type"]
                )
        for exchange, fact in evidence["facts"].items():
            page = fact["page"]
            if alias["kind"] == "footer_first" and (
                page["state"],
                page["session"],
                page["measure_type_scope"],
            ) == (alias["state"], alias["session"], alias["type"]):
                observations.extend(
                    {"source_exchange": exchange, **link}
                    for link in fact["footer_proofs"]
                    if link["url"] == alias["source_url"] and link["label"].strip() == "1"
                )
        alias["observations"] = observations
        alias["proven"] = bool(
            target
            and observations
            and ids[alias["alias_id"]] == 1
            and alias["target_page"] == target["page"]["page"] == 1
            and target["request_url"] == alias["target_request_url"]
            and (
                target["page"]["state"],
                target["page"]["session"],
                target["page"]["measure_type_scope"],
            )
            == (alias["state"], alias["session"], alias["type"])
            and target["scope_context_matches"]
        )
        alias["target_scope_witness"] = target
        proven.append(alias)
    by_id = {row["alias_id"]: row for row in proven}
    for alias in proven:
        if corroboration := alias.get("corroborating_alias_id"):
            other = by_id.get(corroboration, {})
            alias["proven"] &= (
                other.get("proven", False)
                and other.get("target_exchange") == alias["target_exchange"]
            )
    return proven


def aggregate(evidence: dict, groups: list[dict], aliases: list[dict]) -> dict:
    """Pure aggregation; compact fixtures can exercise it without archived source packets."""
    facts, pages = evidence["facts"], evidence["pages"]
    alias_proofs = prove_aliases(evidence, aliases)
    valid_aliases = [row for row in alias_proofs if row["proven"]]
    ids = Counter(row["source_exchange"] for row in pages)
    present = {row["source_exchange"]: row for row in pages}
    declared_exchanges = {exchange for group in groups for exchange in group["exchanges"]}
    unregistered_pages = sorted(set(present) - declared_exchanges)
    group_keys = [(row["state"], row["session"], row["measure_type"]) for row in groups]
    index_keys = [(row["state"], row["session"]) for row in evidence["expected_indexes"]]
    declarations_consistent = (
        len(group_keys) == len(set(group_keys))
        and len(index_keys) == len(set(index_keys))
        and {key[:2] for key in group_keys} == set(index_keys)
        and all(
            count == 1
            for count in Counter(
                exchange for group in groups for exchange in group["exchanges"]
            ).values()
        )
    )
    edges, results = [], []

    def resolve(url, state, session, kind, page_number=None):
        targets = [
            exchange
            for exchange, row in present.items()
            if exchange in facts
            and row == facts[exchange]["page"]
            and facts[exchange]["request_url"] == url
        ]
        alias_id = None
        if not targets:
            candidates = [
                row
                for row in valid_aliases
                if row["source_url"] == url
                and (row["state"], row["session"], row["type"]) == (state, session, kind)
            ]
            if len(candidates) != 1:
                return None, None
            targets = [candidates[0]["target_exchange"]]
            alias_id = candidates[0]["alias_id"]
        if len(targets) != 1:
            return None, None
        exchange = targets[0]
        if exchange not in present or ids[exchange] != 1 or exchange not in facts:
            return None, None
        row, fact = present[exchange], facts[exchange]
        if (
            row != fact["page"]
            or not fact["scope_context_matches"]
            or (row["state"], row["session"], row["measure_type_scope"]) != (state, session, kind)
            or (page_number is not None and row["page"] != page_number)
        ):
            return None, None
        return exchange, alias_id

    for group in groups:
        state, session, kind = group["state"], group["session"], group["measure_type"]
        selected = sorted(
            [row for row in pages if row["source_exchange"] in group["exchanges"]],
            key=lambda row: row["page"],
        )
        faithful = all(
            row == facts.get(row["source_exchange"], {}).get("page")
            and facts[row["source_exchange"]]["scope_context_matches"]
            and (row["state"], row["session"], row["measure_type_scope"]) == (state, session, kind)
            for row in selected
        )
        once = len(selected) == len(group["exchanges"]) and all(
            ids[exchange] == 1 for exchange in group["exchanges"]
        )
        native_ids, all_edges = [], True
        for row in selected:
            fact = facts.get(row["source_exchange"], {})
            native_ids.extend(fact.get("native_ids", []))
            for link in fact.get("footer_proofs", []):
                label = link["label"].strip()
                target, alias_id = resolve(
                    link["url"], state, session, kind, int(label) if label.isdigit() else None
                )
                all_edges &= target is not None
                edges.append(
                    {
                        "state": state,
                        "session": session,
                        "type": kind,
                        "source_exchange": row["source_exchange"],
                        **link,
                        "target_exchange": target,
                        "exact_alias_id": alias_id,
                        "source_observed_edge_resolved": target is not None,
                    }
                )
        finite = finite_pages_complete(selected)
        results.append(
            {
                **group,
                "page_count": len(selected),
                "record_count": len(set(native_ids)),
                "source_page_fidelity": faithful,
                "every_expected_page_exactly_once": once,
                "finite_successor_and_terminal_complete": finite,
                "every_observed_footer_edge_resolved": all_edges,
                "complete_publisher_listed_type_pages": (
                    faithful
                    and once
                    and finite
                    and all_edges
                    and not unregistered_pages
                    and declarations_consistent
                    and len(native_ids) == len(set(native_ids))
                ),
                **FLAGS,
            }
        )
    lookup = {(row["state"], row["session"], row["measure_type"]): row for row in results}
    corrected = []
    for expected in evidence["expected_indexes"]:
        state, session = expected["state"], expected["session"]
        matches = [
            row
            for row in evidence["indexes"]
            if row["source_exchange"] == expected["source_exchange"]
        ]
        faithful = len(matches) == 1 and matches[0] == expected and expected["source_body_complete"]
        omitted, incomplete, resolutions = [], [], []
        for link in expected["links"]:
            kind = link["measure_type"]
            target, alias_id = resolve(link["url"], state, session, kind, 1)
            group_complete = lookup.get((state, session, kind), {}).get(
                "complete_publisher_listed_type_pages", False
            )
            if target is None:
                omitted.append(link["url"])
            if not group_complete:
                incomplete.append(link["url"])
            resolutions.append(
                {
                    **link,
                    "target_first_page_exchange": target,
                    "exact_alias_id": alias_id,
                    "query_group_complete": group_complete,
                }
            )
        kinds = [row["measure_type"] for row in expected["links"]]
        exact_types = len(kinds) == len(set(kinds)) and set(kinds) == {
            kind
            for actual_state, actual_session, kind in lookup
            if (actual_state, actual_session) == (state, session)
        }
        corrected.append(
            {
                "state": state,
                "session": session,
                "source_exchange": expected["source_exchange"],
                "publisher_listed_type_urls": [row["url"] for row in expected["links"]],
                "source_index_present_and_unchanged": faithful,
                "exact_publisher_type_set_matches_groups": exact_types,
                "omitted_type_urls": omitted,
                "incomplete_type_query_urls": incomplete,
                "type_link_resolutions": resolutions,
                "all_listed_type_queries_complete": (
                    faithful
                    and exact_types
                    and not omitted
                    and not incomplete
                    and not unregistered_pages
                    and declarations_consistent
                ),
                **FLAGS,
            }
        )
    return {
        "publisher_type_indexes": corrected,
        "groups": results,
        "page_edges": edges,
        "exact_alias_proofs": alias_proofs,
        "unregistered_page_exchanges": unregistered_pages,
        "declared_source_graph_consistent": declarations_consistent,
    }


def load_evidence(
    base: Path, projection_manifest: Path, capture_manifest: Path, contract_path: Path
) -> tuple[dict, dict, dict]:
    contract = yaml.safe_load(contract_path.read_text())
    for role, path in (
        ("base_manifest", base / "manifest.json"),
        ("projection_manifest", projection_manifest),
        ("capture_manifest", capture_manifest),
    ):
        verify_manifest(path)
        if sha256_file(path) != contract["bindings"][role]:
            raise ValueError(f"wrong bound {role}")
    parser_path = _bound_file(contract_path, contract["frozen_parser"])
    scopes_path = _bound_file(contract_path, contract["scope_configuration"])
    spec = importlib.util.spec_from_file_location(
        "state_politics.bills._aggregate_bound_" + sha256_file(parser_path)[:16], parser_path
    )
    parser = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = parser
    spec.loader.exec_module(parser)
    scopes = yaml.safe_load(scopes_path.read_text())
    root = projection_manifest.parent
    events = {
        row["id"]: row
        for row in map(json.loads, (root / "exchanges.jsonl").read_text().splitlines())
    }
    facts, pages, records = {}, [], []
    witness = contract["page_identity_witness"]
    for scope in scopes["pages"]:
        event = events[scope["exchange"]]
        body = (root / event["body"]).read_bytes()
        if sha256_file(root / event["body"]) != event["sha256"] or event["status"] != 200:
            raise ValueError("page is not its bound successful source entity")
        parsed = parser.parse_page(body, event, scopes["adapters"][scope["adapter"]], scope)
        page = parsed["evidence"]
        document = parser.ArchivedHTML(body.decode("utf-8"))
        nodes = parser.select(
            document.root, scopes["adapters"][scope["adapter"]]["pagination"]["link_selector"]
        )
        footer = [
            {
                **link,
                "source_body_sha256": event["sha256"],
                "raw_anchor_html": document.source[node.start : node.end],
                "character_span": [node.start, node.end],
            }
            for link, node in zip(page["pagination_links"], nodes, strict=True)
        ]
        hidden = [
            dict(node.attrs).get(witness["type_attribute"])
            for node in parser.select(document.root, witness["type_selector"])
        ]
        details = [
            row["absolute_url"]
            for row in parsed["links"]
            if urlsplit(row["absolute_url"]).path == witness["record_detail_path"]
        ]
        context = (
            bool(details)
            and hidden == [scope["measure_type_scope"]]
            and all(
                parse_qs(urlsplit(url).query).get(witness["session_query_key"])
                == [witness["session_value_template"].format(session=scope["session"])]
                for url in details
            )
            and all(row["measure_type"] == scope["measure_type_scope"] for row in parsed["records"])
        )
        facts[event["id"]] = {
            "page": copy.deepcopy(page),
            "request_url": event["url"],
            "source_body_sha256": event["sha256"],
            "scope_context_matches": context,
            "hidden_type_literals": hidden,
            "record_detail_url_literals": sorted(set(details)),
            "native_ids": [row["native_id"] for row in parsed["records"]],
            "footer_proofs": footer,
        }
        pages.append(page)
        records.extend(parsed["records"])
    if pages != _json(base / "source_page_counts.json"):
        raise ValueError("frozen page evidence does not reproduce the base packet")
    indexes = []
    for scope in scopes["type_indexes"]:
        event = events[scope["exchange"]]
        if (
            event["status"] != 200
            or not event["complete_body"]
            or sha256_file(root / event["body"]) != event["sha256"]
        ):
            raise ValueError("source index is incomplete")
        document = parser.ArchivedHTML((root / event["body"]).read_bytes().decode("utf-8"))
        links = []
        for node in parser.select(document.root, scope["link_selector"]):
            href = dict(node.attrs)["href"]
            url = urljoin(event["url"], href)
            values = parse_qs(urlsplit(url).query).get(contract["type_index_query_key"])
            if not values or len(values) != 1:
                raise ValueError("source index type is not explicit")
            links.append(
                {
                    "url": url,
                    "href_literal": href,
                    "measure_type": values[0],
                    "source_body_sha256": event["sha256"],
                    "raw_anchor_html": document.source[node.start : node.end],
                    "character_span": [node.start, node.end],
                }
            )
        indexes.append(
            {
                "state": scope["state"],
                "session": scope["session"],
                "source_exchange": event["id"],
                "source_body_complete": True,
                "links": links,
            }
        )
    return (
        {
            "facts": facts,
            "pages": pages,
            "records": records,
            "indexes": indexes,
            "expected_indexes": copy.deepcopy(indexes),
        },
        scopes,
        {"parser": parser_path, "scopes": scopes_path, "contract": contract},
    )


def derive(
    base: Path, projection_manifest: Path, capture_manifest: Path, contract_path: Path, out: Path
) -> dict:
    if out.exists():
        raise FileExistsError(out)
    evidence, scopes, inputs = load_evidence(
        base, projection_manifest, capture_manifest, contract_path
    )
    result = aggregate(
        evidence, scopes["complete_census_groups"], inputs["contract"]["exact_aliases"]
    )
    if (
        not result["publisher_type_indexes"]
        or not all(
            row["all_listed_type_queries_complete"] for row in result["publisher_type_indexes"]
        )
        or not all(row["proven"] for row in result["exact_alias_proofs"])
    ):
        raise ValueError("declared source graph is incomplete; no complete output authorized")
    out.mkdir(parents=True)
    for path in base.iterdir():
        if path.is_file() and path.name != "manifest.json":
            shutil.copyfile(path, out / path.name)
    legacy = out / "legacy_generic"
    legacy.mkdir()
    for name in ("report.json", "publisher_type_index_status.json"):
        shutil.copyfile(base / name, legacy / name)
    write_products = {
        "publisher_type_index_status.json": result["publisher_type_indexes"],
        "complete_session_index_coverage.json": result["publisher_type_indexes"],
        "complete_scope_page_type_counts.json": result["groups"],
        "finite_page_edge_proofs.json": result["page_edges"],
        "exact_source_url_alias_proofs.json": result["exact_alias_proofs"],
    }
    report = _json(base / "report.json")
    report["status"] = "production_authoritative_publisher_listed_aggregate_not_sourceclosure"
    report["publisher_type_indexes"] = result["publisher_type_indexes"]
    report["legacy_generic_diagnostics"] = inputs["contract"]["legacy_diagnostics"]
    report["new_physical_http_for_this_derivation"] = 0
    report.update(FLAGS)
    for state in {row["state"] for row in result["groups"]}:
        row = report["states"][state]
        row["source_page_status"] = row.pop("source_session_status", [])
        row["legacy_per_page_single_document_complete_count"] = row.pop(
            "publisher_query_pages_complete", None
        )
        row["source_session_aggregate_status"] = [
            index for index in result["publisher_type_indexes"] if index["state"] == state
        ]
        row["source_page_status_semantics"] = (
            "Frozen per-page diagnostics, not aggregate completeness."
        )
        row.update(FLAGS)
    summary = _json(base / "complete_census_summary.json")
    session_counts = Counter(
        (record["state"], record["session_identifier"]) for record in evidence["records"]
    )
    summary.pop("sessions", None)
    if len({state for state, _ in session_counts}) == 1:
        summary["sessions"] = {
            session: count for (_, session), count in sorted(session_counts.items())
        }
    summary.update(
        {
            "status": report["status"],
            "new_physical_http_for_this_derivation": 0,
            "census_pages": len(evidence["pages"]),
            "type_session_groups": len(result["groups"]),
            "census_record_count": len(evidence["records"]),
            "native_identities": len({row["native_id"] for row in evidence["records"]}),
            "all_groups_complete": all(
                row["complete_publisher_listed_type_pages"] for row in result["groups"]
            ),
            "state_session_counts": [
                {"state": state, "session": session, "records": count}
                for (state, session), count in sorted(
                    Counter(
                        (row["state"], row["session_identifier"]) for row in evidence["records"]
                    ).items()
                )
            ],
            **FLAGS,
        }
    )
    write_products.update({"report.json": report, "complete_census_summary.json": summary})
    for name, value in write_products.items():
        _write(out / name, value)
    reproduction = out / "reproduction_inputs"
    reproduction.mkdir()
    sources = {
        "native_inventory_aggregate.py": Path(__file__),
        "contract.yml": contract_path,
        "scope_configuration.yml": inputs["scopes"],
        "frozen_parser.py": inputs["parser"],
        "base_manifest.json": base / "manifest.json",
        "projection_manifest.json": projection_manifest,
        "capture_manifest.json": capture_manifest,
    }
    for name, path in sources.items():
        shutil.copyfile(path, reproduction / name)
    _write(
        out / "manifest.json",
        {
            "schema_version": 3,
            "status": report["status"],
            "new_physical_http": 0,
            "authoritative_aggregate": True,
            "legacy_diagnostics_preserved": True,
            "inputs": {
                name: {"path": str(path.resolve()), "sha256": sha256_file(path)}
                for name, path in sources.items()
            },
            "files": {
                str(path.relative_to(out)): sha256_file(path)
                for path in sorted(out.rglob("*"))
                if path.is_file()
            },
            **FLAGS,
        },
    )
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-packet", type=Path, required=True)
    parser.add_argument("--raw-projection-manifest", type=Path, required=True)
    parser.add_argument("--capture-manifest", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = derive(
        args.base_packet,
        args.raw_projection_manifest,
        args.capture_manifest,
        args.contract,
        args.out,
    )
    print(
        json.dumps(
            {
                "session_status": [
                    {
                        "state": row["state"],
                        "session": row["session"],
                        "complete": row["all_listed_type_queries_complete"],
                    }
                    for row in result["publisher_type_indexes"]
                ],
                "groups": len(result["groups"]),
                "records": sum(row["record_count"] for row in result["groups"]),
                "footer_edges": len(result["page_edges"]),
                "new_physical_http": 0,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

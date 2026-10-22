"""Compact synthetic graph tests; these fixtures are not actual source recovery."""

import copy
import json
from pathlib import Path

import pytest

from state_politics.bills import native_inventory_aggregate as aggregate


@pytest.fixture
def graph():
    origin = "https://publisher.test/"
    pages, facts, groups, indexes = [], {}, [], []
    for session, kind, size in (("s1", "HB", 3), ("s2", "SB", 2)):
        listed = f"{origin}list?session={session}&type={kind}"
        first = f"{origin}list?start=0&type={kind}&session={session}" if session == "s1" else listed
        first_footer = f"{origin}list?type={kind}&session={session}&start=0"
        urls = [first] + [f"{listed}&page={number}" for number in range(2, size + 1)]
        exchanges = [f"{session}-{number}" for number in range(1, size + 1)]
        for number, (exchange, url) in enumerate(zip(exchanges, urls, strict=True), 1):
            links = [
                {
                    "url": first_footer if target == 1 and session == "s1" else target_url,
                    "label": str(target),
                }
                for target, target_url in enumerate(urls, 1)
                if target != number
            ]
            page = {
                "state": "ZZ",
                "session": session,
                "measure_type_scope": kind,
                "source_exchange": exchange,
                "page": number,
                "pages": size,
                "page_body_complete": True,
                "terminal_document_closed": True,
                "request_urls": [url],
                "pagination_links": links,
                "publisher_query_complete": False,
            }
            pages.append(page)
            facts[exchange] = {
                "page": copy.deepcopy(page),
                "request_url": url,
                "scope_context_matches": True,
                "native_ids": [f"ZZ:{session}:{kind}{number}"],
                "footer_proofs": copy.deepcopy(links),
            }
        groups.append(
            {
                "state": "ZZ",
                "session": session,
                "measure_type": kind,
                "exchanges": exchanges,
            }
        )
        indexes.append(
            {
                "state": "ZZ",
                "session": session,
                "source_exchange": session + "-index",
                "source_body_complete": True,
                "links": [{"url": listed, "measure_type": kind}],
            }
        )
    first = facts["s1-1"]["request_url"]
    aliases = [
        {
            "alias_id": "footer-first",
            "kind": "footer_first",
            "state": "ZZ",
            "session": "s1",
            "type": "HB",
            "target_page": 1,
            "target_exchange": "s1-1",
            "target_request_url": first,
            "source_url": origin + "list?type=HB&session=s1&start=0",
        },
        {
            "alias_id": "index-first",
            "kind": "type_index",
            "state": "ZZ",
            "session": "s1",
            "type": "HB",
            "target_page": 1,
            "target_exchange": "s1-1",
            "target_request_url": first,
            "source_url": origin + "list?session=s1&type=HB",
            "corroborating_alias_id": "footer-first",
        },
    ]
    evidence = {
        "pages": pages,
        "facts": facts,
        "indexes": indexes,
        "expected_indexes": copy.deepcopy(indexes),
        "records": [
            {
                "state": "ZZ",
                "session_identifier": page["session"],
                "native_id": facts[page["source_exchange"]]["native_ids"][0],
            }
            for page in pages
        ],
    }
    return evidence, groups, aliases


def status(result, session):
    return next(
        row["all_listed_type_queries_complete"]
        for row in result["publisher_type_indexes"]
        if row["session"] == session
    )


def test_complete_multipage_queries_not_judged_by_first_page_flag(graph):
    evidence, groups, aliases = graph
    result = aggregate.aggregate(evidence, groups, aliases)
    assert status(result, "s1") and status(result, "s2")
    assert all(row["proven"] for row in result["exact_alias_proofs"])
    assert all(row["source_observed_edge_resolved"] for row in result["page_edges"])
    assert not any(page["publisher_query_complete"] for page in evidence["pages"])
    without_exact_alias = aggregate.aggregate(evidence, groups, aliases[:1])
    assert not status(without_exact_alias, "s1")
    assert status(without_exact_alias, "s2")


@pytest.mark.parametrize("removed", ["s1-2", "s1-3", "s2-2"])
def test_missing_middle_or_last_page(graph, removed):
    evidence, groups, aliases = graph
    evidence["pages"] = [row for row in evidence["pages"] if row["source_exchange"] != removed]
    assert not status(aggregate.aggregate(evidence, groups, aliases), removed.split("-")[0])


@pytest.mark.parametrize(
    "field,value",
    [
        ("session", "s2"),
        ("type", "SB"),
        ("target_page", 2),
        ("target_exchange", "s1-2"),
        ("source_url", "https://publisher.test/list?session=s1&type=HB&unexpected=1"),
    ],
)
def test_wrong_or_unobserved_exact_alias_is_not_normalized(graph, field, value):
    evidence, groups, aliases = graph
    aliases[1][field] = value
    assert not status(aggregate.aggregate(evidence, groups, aliases), "s1")


@pytest.mark.parametrize("rename_exchange", [False, True])
def test_duplicate_page_even_under_unknown_exchange(graph, rename_exchange):
    evidence, groups, aliases = graph
    duplicate = copy.deepcopy(evidence["pages"][0])
    if rename_exchange:
        duplicate["source_exchange"] = "unknown-duplicate"
    evidence["pages"].append(duplicate)
    assert not status(aggregate.aggregate(evidence, groups, aliases), "s1")


@pytest.mark.parametrize("remove_entire_index", [False, True])
def test_source_index_omission(graph, remove_entire_index):
    evidence, groups, aliases = graph
    if remove_entire_index:
        evidence["indexes"].pop(0)
    else:
        evidence["indexes"][0]["links"].clear()
    assert not status(aggregate.aggregate(evidence, groups, aliases), "s1")


def test_missing_declared_index_cannot_hide_a_declared_session(graph):
    evidence, groups, aliases = graph
    evidence["indexes"].pop(0)
    evidence["expected_indexes"].pop(0)
    result = aggregate.aggregate(evidence, groups, aliases)
    assert result["declared_source_graph_consistent"] is False
    assert not all(
        row["all_listed_type_queries_complete"] for row in result["publisher_type_indexes"]
    )


def test_production_derivation_preserves_legacy_and_archives_exact_inputs(
    graph, tmp_path, monkeypatch
):
    evidence, groups, aliases = graph
    base = tmp_path / "base"
    base.mkdir()
    report = {
        "states": {
            "ZZ": {"source_session_status": evidence["pages"], "publisher_query_pages_complete": 0}
        },
        "publisher_type_indexes": [{"legacy": True, "all_listed_type_queries_complete": False}],
    }
    for name, value in {
        "report.json": report,
        "publisher_type_index_status.json": report["publisher_type_indexes"],
        "complete_census_summary.json": {},
        "manifest.json": {"files": {}},
    }.items():
        (base / name).write_text(json.dumps(value))
    for name in ("projection.json", "capture.json", "contract.yml", "scopes.yml", "parser.py"):
        (tmp_path / name).write_text("{}")
    contract = {"exact_aliases": aliases, "legacy_diagnostics": {"explanation": "fixture"}}
    monkeypatch.setattr(
        aggregate,
        "load_evidence",
        lambda *args: (
            evidence,
            {"complete_census_groups": groups},
            {
                "parser": tmp_path / "parser.py",
                "scopes": tmp_path / "scopes.yml",
                "contract": contract,
            },
        ),
    )
    out = tmp_path / "out"
    aggregate.derive(
        base,
        tmp_path / "projection.json",
        tmp_path / "capture.json",
        tmp_path / "contract.yml",
        out,
    )
    final = json.loads((out / "report.json").read_text())
    assert all(row["all_listed_type_queries_complete"] for row in final["publisher_type_indexes"])
    assert final["new_physical_http_for_this_derivation"] == 0
    assert all(final[key] is False for key in aggregate.FLAGS)
    for name in ("report.json", "publisher_type_index_status.json"):
        assert (out / "legacy_generic" / name).read_bytes() == (base / name).read_bytes()
    assert (out / "reproduction_inputs/native_inventory_aggregate.py").read_bytes() == (
        Path(aggregate.__file__).read_bytes()
    )
    aggregate.verify_manifest(out / "manifest.json")

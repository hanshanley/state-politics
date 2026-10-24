import copy
import html
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from state_politics.bills import billcam_text as archive


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def document(number=2152, kind="HB", year="2024", tail=""):
    prefix = ".".join(kind) + "."
    return (
        f"<div><p>{prefix} NO. {number}</p>"
        f"<p>THIRTY-SECOND LEGISLATURE, {year}</p><p>STATE OF HAWAII</p>"
        "<p>A BILL FOR AN ACT</p>"
        "<p>RELATING TO OVERSIGHT.</p>"
        "<p>BE IT ENACTED BY THE LEGISLATURE OF THE STATE OF HAWAII:</p>"
        "<p>SECTION 1. anti<span>discrimination</span> &amp; oversight.</p>"
        f"<p>{tail}</p><p>SECTION 99. This Act shall take effect upon approval.</p></div>"
    )


def body_page(url, content):
    return (
        f'<html><head><link rel="canonical" href="{url}"></head><body>'
        '<p>Provider topic and account material must not enter the bill input.</p>'
        f'<div class="container">{content}</div>'
        "<footer>Provider footer</footer></body></html>"
    ).encode()


@pytest.fixture
def packet_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "raw").mkdir()
    (source / "inherited-probe").mkdir()
    (source / "inherited-probe/request-ledger.jsonl").write_text("")
    originals = pa.table({
        "bill_id": ["original-hb", "original-sb", "unrelated-ma"],
        "state": ["HI", "HI", "MA"],
        "identifier": ["HB 2152", "SB 2890", "H 1"],
        "session_identifier": ["2024", "2024", "193"],
        "title": ["RELATING TO OVERSIGHT.", "RELATING TO PROJECTS.", "Other"],
        "source_introduction_date": ["2024-01-22", "2024-01-19", None],
        "source_unknown": pa.array([None, False, None], type=pa.bool_()),
        "model_input_approved": [False, False, False],
        "snapshot_source_url": [
            "https://capitol.hawaii.gov/sessions/session2024/bills/HB2152_.HTM", None, None,
        ],
    })
    pq.write_table(originals, source / "input_gap_queue.parquet")
    ledger = []

    def capture(url, raw):
        number = len(ledger) + 1
        relative = f"raw/{number}.body"
        (source / relative).write_bytes(raw)
        ledger.append({
            "ordinal": number, "url": url, "body": relative,
            "body_binding": archive._binding(source / relative),
            "http_status": 200, "curl_returncode": 0, "inherited": False,
        })

    for kind, number, bill_hash, title, years in [
        ("HB", 2152, "OriginalHB", "Relating To Oversight.", ["2024", "2024"]),
        ("SB", 2890, "WrongYearSB", "Relating To Projects.", ["2023"]),
    ]:
        url = f"https://billcam.com/bills/{bill_hash}/g/{kind.lower()}-{number}/title"
        versions, links, bodies = [], [], []
        for ordinal, year in enumerate(years):
            text_hash = f"{bill_hash}Text{ordinal}"
            body_url = f"https://billcam.com/bill-texts/{text_hash}"
            versions.append({
                "id": number * 10 + ordinal, "bill_id": number, "text_hash": text_hash,
                "date": "2024-01-20", "type": "Introduced" if not ordinal else "Amended",
                "mime": "text/html",
                "source_urls": {
                    "state": f"https://www.capitol.hawaii.gov/sessions/session{year}"
                    f"/bills/{kind}{number}_.HTM",
                },
            })
            links.append(f'<a href="{body_url}">Full source</a>')
            bodies.append((body_url, body_page(body_url, document(
                number, kind, year, tail="Full source passage. " * 1000,
            ))))
        bill = {
            "id": number, "bill_hash": bill_hash, "bill_type": kind, "bill_number": number,
            "path": url, "title": title,
            "display_legislative_session": "Hawaii 2024 Regular Session",
            "legislative_session": {"name": "2024 Regular Session", "state": {"abbr": "HI"}},
            "texts": versions, "tags": ["Never use provider topics as gold"],
            "current_sponsor_session": "2026",
        }
        raw = (
            f'<html><head><link rel="canonical" href="{url}"></head><body>'
            '<div class="container">'
            f'<bill-vote-panel :bill="{html.escape(json.dumps(bill), quote=True)}">'
            f"</bill-vote-panel>{''.join(links)}</div></body></html>"
        ).encode()
        capture(url, raw)
        for body_url, raw in bodies:
            capture(body_url, raw)
    archive._write_rows(source / "request-ledger.jsonl", ledger)
    archive._write_rows(source / "request-attempts.jsonl", [
        {"ordinal": row["ordinal"], "url": row["url"]} for row in ledger
    ])
    write_json(source / "scope.json", {
        "inherited_probe_allowance_and_requests_forever_closed": 0,
        "additional_identified_frontier_GET_allowance": 500,
    })
    write_json(source / "report.json", {
        "status": "synthetic_test_capture_no_network", "error": None, "network_closed": True,
        "source_admissions": 0, "encoder_calls": 0, "publication": False,
        "inherited_closed_probe_requests": 0, "new_HTTP_responses_retained": len(ledger),
        "new_GET_invocations": len(ledger), "known_aggregate_GET_invocations": len(ledger),
    })
    artifacts = {
        path.relative_to(source).as_posix(): archive._binding(path)
        for path in source.rglob("*") if path.is_file()
    }
    write_json(source / "manifest.json", {
        "schema": archive.SOURCE_SCHEMA, "network_closed": True,
        "source_admission": False, "publication": False,
        "input_gap_queue": archive._binding(source / "input_gap_queue.parquet"),
        "artifacts": artifacts,
    })
    return source, originals, tmp_path / "normalized"


def build(source, out):
    return archive.build_billcam(
        source, source / "input_gap_queue.parquet", out,
        source_manifest_sha256=archive._binding(source / "manifest.json")["sha256"],
        gap_queue_sha256=archive._binding(source / "input_gap_queue.parquet")["sha256"],
    )


def repin(out, name):
    manifest = archive._json(out / "manifest.json")
    manifest["packet_artifacts"][name] = archive._binding(out / name)
    write_json(out / "manifest.json", manifest)


def test_full_published_bodies_original_unknowns_and_all_variants_survive(packet_source):
    source, originals, out = packet_source
    before = {p.relative_to(source).as_posix(): archive._binding(p)
              for p in source.rglob("*") if p.is_file()}
    manifest = build(source, out)
    views, contexts, _, _ = archive.load_billcam(out)
    assert len(views) == 2 and [row["bill_id"] for row in contexts] == ["original-hb"]
    assert pq.read_table(out / "context_inventory.parquet").equals(originals.slice(0, 1))
    assert contexts[0]["source_unknown"] is None
    assert contexts[0]["source_introduction_date"] == "2024-01-22"
    assert [v["source_version"]["version"]["type"] for v in views] == ["Introduced", "Amended"]
    assert all("SECTION 99." in v["text"] and v["text"].count("Full source passage.") == 1000
               and "antidiscrimination & oversight." in v["text"] for v in views)
    assert all("Provider footer" not in v["text"] and "account material" not in v["text"]
               and "Never use provider topics" not in v["text"] for v in views)
    assert all(v["archive_generated_prologue_preserved"] is False
               and all(v[flag] is False for flag in archive.FLAGS) for v in views)
    assert views[0]["source_record"]["current_sponsor_session"] == "2026"
    assert views[0]["source_identity"]["original_native_URL_equality_or_alias_not_asserted"] is True
    assert manifest["counts"]["remaining_unavailable_from_this_source"] == 2
    assert any(row["disposition"] == "printed_own_identity_or_year_conflict_not_a_fill"
               for row in archive._rows(out / "source_dispositions.jsonl"))
    assert before == {p.relative_to(source).as_posix(): archive._binding(p)
                      for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("change", ["full_text", "original_date", "approval", "version"])
def test_rebound_normalized_values_must_replay_actual_sources(packet_source, change):
    source, _, out = packet_source
    build(source, out)
    rows = list(archive._rows(out / "views.jsonl"))
    if change == "full_text":
        rows[0]["text"] = rows[0]["text"][:100]
    elif change == "original_date":
        rows[0]["original_target_context"]["source_introduction_date"] = "2024-01-20"
    elif change == "approval":
        rows[0]["scientific_approval"] = True
    else:
        rows[0]["source_version"]["version"]["type"] = "Introduced-only"
    archive._write_rows(out / "views.jsonl", rows)
    repin(out, "views.jsonl")
    with pytest.raises(ValueError, match="replay mismatch"):
        archive.load_billcam(out)


def test_source_changes_missing_members_and_metadata_unknowns_fail_closed(packet_source):
    source, originals, out = packet_source
    build(source, out)
    metadata = {row["bill_id"]: row for row in originals.to_pylist()}
    altered = copy.deepcopy(metadata)
    altered["original-hb"]["source_unknown"] = ""
    with pytest.raises(ValueError, match="missingness/type changed"):
        archive.load_billcam(out, altered)
    archive.load_billcam(out, metadata)
    (out / "source-evidence/raw/2.body").write_bytes(b"Not the retained source")
    repin(out, "source-evidence/raw/2.body")
    with pytest.raises(ValueError, match="source artifact changed"):
        archive.load_billcam(out)


@pytest.mark.parametrize("shape", ["rows", "arrow", "indexed"])
def test_original_metadata_consumer_shapes_and_duplicate_matched_ids(packet_source, shape):
    source, originals, out = packet_source
    build(source, out)
    rows = originals.to_pylist()
    metadata = (
        originals if shape == "arrow" else
        {row["bill_id"]: row for row in rows} if shape == "indexed" else rows
    )
    views, contexts, _, _ = archive.load_billcam(out, metadata)
    assert len(views) == 2 and contexts[0] == rows[0]
    with pytest.raises(ValueError, match="missing or duplicated"):
        archive.load_billcam(out, [*rows, rows[0]])


@pytest.mark.parametrize(("kind", "year"), [("SB", "2024"), ("HB", "2023")])
def test_cited_numbers_or_other_annual_contexts_are_not_own_identity(kind, year):
    url = "https://billcam.com/bill-texts/ActualBody"
    text, _ = archive._body(body_page(url, document(
        kind=kind, year=year, tail="This cites H.B. NO. 2152 and another 2024 bill.",
    )), url)
    context = {"state": "HI", "identifier": "HB 2152", "session_identifier": "2024"}
    assert archive.printed_identity(text, context) is None


def test_wrapped_legislature_heading_preserves_literal_source_spans():
    url = "https://billcam.com/bill-texts/ActualBody"
    text, _ = archive._body(body_page(url, document().replace(
        "THIRTY-SECOND LEGISLATURE", "THIRTY-SECOND\n  LEGISLATURE",
    )), url)
    context = {"state": "HI", "identifier": "HB 2152", "session_identifier": "2024",
               "title": "RELATING TO OVERSIGHT."}
    identity = archive.printed_identity(text, context)
    assert identity is not None
    venue = identity["printed_evidence"][1]
    assert venue["text"] == text[venue["start"]:venue["end"]] == (
        "THIRTY-SECOND\n  LEGISLATURE, 2024"
    )
    assert archive.printed_identity(text, context, legacy_identity_profile=True) is None
    assert archive.printed_identity(text, {**context, "session_identifier": "2023"}) is None
    assert archive.printed_identity(text, {**context, "title": "A DIFFERENT PURPOSE."}) is None
    caption = identity["printed_caption"]
    assert caption["text"] == text[caption["start"]:caption["end"]] == "RELATING TO OVERSIGHT."


def test_exact_sealed_legacy_profile_does_not_rewrite_prior_negative_views(
    packet_source, monkeypatch,
):
    source, _, out = packet_source
    ledger = list(archive._rows(source / "request-ledger.jsonl"))
    for row in ledger:
        path = source / row["body"]
        path.write_bytes(path.read_bytes().replace(
            b"THIRTY-SECOND LEGISLATURE", b"THIRTY-SECOND\n  LEGISLATURE",
        ))
        row["body_binding"] = archive._binding(path)
    archive._write_rows(source / "request-ledger.jsonl", ledger)
    source_manifest = archive._json(source / "manifest.json")
    source_manifest["artifacts"] = {
        path.relative_to(source).as_posix(): archive._binding(path)
        for path in source.rglob("*") if path.is_file() and path.name != "manifest.json"
    }
    write_json(source / "manifest.json", source_manifest)
    current_reader = archive.printed_identity

    def legacy_reader(text, context, *, legacy_identity_profile=False):
        return current_reader(text, context, legacy_identity_profile=True)

    with monkeypatch.context() as legacy:
        legacy.setattr(archive, "printed_identity", legacy_reader)
        build(source, out)
    with pytest.raises(ValueError, match="replay mismatch"):
        archive.load_billcam(out)
    monkeypatch.setitem(
        archive.SEALED_PRODUCERS, archive._binding(out / "manifest.json")["sha256"],
        archive._binding(out / "producer/billcam_text.py"),
    )
    assert archive.load_billcam(out)[0] == []
    current = out.with_name("current-normalized")
    build(source, current)
    assert len(archive.load_billcam(current)[0]) == 2


def add_explicit_carryover_source(source):
    rows = pq.read_table(source / "input_gap_queue.parquet").to_pylist()
    rows[1].update(
        source_introduction_date="2023-01-19",
        origin_introduction_action_ids='["original-intro-sb"]',
        from_organization_id="original-senate",
    )
    for row in rows:
        row.setdefault("origin_introduction_action_ids", None)
        row.setdefault("from_organization_id", None)
    pq.write_table(pa.Table.from_pylist(rows), source / "input_gap_queue.parquet")
    actions = [
        {
            "action_id": "original-intro-sb", "bill_id": "original-sb", "state": "HI",
            "date": "2023-01-19", "description": "Introduced.",
            "classification": "introduction", "organization_id": "original-senate",
        },
        {
            "action_id": "original-carry-sb", "bill_id": "original-sb", "state": "HI",
            "date": "2023-12-11", "description": "Carried over to 2024 Regular Session.",
            "classification": "carried-over", "organization_id": "original-legislature",
        },
    ]
    (source / "carryover-evidence").mkdir()
    action_path = source / "carryover-evidence/bill_actions.parquet"
    pq.write_table(pa.Table.from_pylist(actions), action_path)
    extraction_path = source / "carryover-evidence/original-extraction.json"
    write_json(extraction_path, {
        "status": "complete_extraction_not_source_certification",
        "scientific_certification": "not_performed",
        "artifacts": {"bill_actions.parquet": {
            "sha256": archive._binding(action_path)["sha256"], "rows": len(actions),
        }},
    })
    ledger = list(archive._rows(source / "request-ledger.jsonl"))
    for row in ledger:
        if "/bill-texts/WrongYearSBText" in row["url"]:
            path = source / row["body"]
            path.write_bytes(path.read_bytes().replace(
                b"RELATING TO OVERSIGHT.", b"RELATING TO PROJECTS.",
            ))
            row["body_binding"] = archive._binding(path)
    archive._write_rows(source / "request-ledger.jsonl", ledger)
    manifest = archive._json(source / "manifest.json")
    manifest["input_gap_queue"] = archive._binding(source / "input_gap_queue.parquet")
    manifest["explicit_carryover_evidence"] = {
        "schema": "state-politics.original-carryover-actions.v1",
        "extraction_manifest": extraction_path.relative_to(source).as_posix(),
        "extraction_manifest_sha256": archive._binding(extraction_path)["sha256"],
        "actions": action_path.relative_to(source).as_posix(),
    }
    manifest["artifacts"] = {
        path.relative_to(source).as_posix(): archive._binding(path)
        for path in source.rglob("*") if path.is_file() and path != source / "manifest.json"
    }
    write_json(source / "manifest.json", manifest)
    return rows[1], actions


def test_explicit_original_actions_recover_body_without_rewriting_printed_or_context_year(
    packet_source,
):
    source, _, out = packet_source
    original, actions = add_explicit_carryover_source(source)
    manifest = build(source, out)
    views, contexts, _, _ = archive.load_billcam(out)
    recovered = next(view for view in views if view["bill_id"] == "original-sb")
    assert len(views) == 3 and manifest["counts"]["n_action_proven_carryover_views"] == 1
    assert next(row for row in contexts if row["bill_id"] == "original-sb") == original
    identity = recovered["source_identity"]
    assert identity["printed_year"] == "2023" and identity["session_identifier"] == "2024"
    proof = identity["explicit_original_carryover_evidence"]
    assert proof["carryover_actions"] == [actions[1]]
    assert proof["original_origin_introduction_actions"] == [actions[0]]
    assert recovered["original_target_context"] == original
    assert recovered["bill_specific_carryover_status_inferred"] is False
    assert recovered["native_URL_alias_inferred"] is False
    assert all(recovered[flag] is False for flag in archive.FLAGS)
    assert "THIRTY-SECOND LEGISLATURE, 2023" in recovered["text"]
    assert "SECTION 99." in recovered["text"] and "Full source passage." in recovered["text"]
    for span in identity["printed_evidence"]:
        assert recovered["text"][span["start"]:span["end"]] == span["text"]


@pytest.mark.parametrize("missing", [
    "carryover", "introduction", "wrong_bill", "wrong_chamber", "quoted_not_carried",
])
def test_dates_and_other_bill_or_unclassified_mentions_are_not_carryover_proof(
    packet_source, missing,
):
    source, _, _ = packet_source
    original, actions = add_explicit_carryover_source(source)
    text, _ = archive._body(body_page(
        "https://billcam.com/bill-texts/ActualBody",
        document(2890, "SB", "2023").replace("RELATING TO OVERSIGHT.", "RELATING TO PROJECTS."),
    ), "https://billcam.com/bill-texts/ActualBody")
    if missing == "carryover":
        actions.pop()
    elif missing == "introduction":
        actions.pop(0)
    elif missing == "wrong_bill":
        actions[1]["bill_id"] = "another-bill"
    elif missing == "wrong_chamber":
        actions[0]["organization_id"] = "another-chamber"
    else:
        actions[1]["classification"] = ""
    assert archive._explicit_carryover_identity(text, original, actions) is None
    assert archive.printed_identity(text, original) is None


def test_action_evidence_rebound_without_original_extraction_fails_closed(packet_source):
    source, _, out = packet_source
    _, actions = add_explicit_carryover_source(source)
    actions[1]["bill_id"] = "another-bill"
    path = source / "carryover-evidence/bill_actions.parquet"
    pq.write_table(pa.Table.from_pylist(actions), path)
    manifest = archive._json(source / "manifest.json")
    manifest["artifacts"][path.relative_to(source).as_posix()] = archive._binding(path)
    write_json(source / "manifest.json", manifest)
    with pytest.raises(ValueError, match="do not match the original complete extraction"):
        build(source, out)


def declared_2023_source(source, *, own_year="2023", extra_venue=""):
    original, _ = add_explicit_carryover_source(source)
    rows = pq.read_table(source / "input_gap_queue.parquet").to_pylist()
    rows.append({
        **original, "bill_id": "earlier-original-sb",
        "session_identifier": "2023 Regular Session",
    })
    pq.write_table(pa.Table.from_pylist(rows), source / "input_gap_queue.parquet")
    ledger = list(archive._rows(source / "request-ledger.jsonl"))
    for row in ledger:
        path = source / row["body"]
        if "/bills/WrongYearSB/" in row["url"]:
            path.write_bytes(path.read_bytes().replace(
                b"2024 Regular Session", b"2023 Regular Session",
            ))
        elif "/bill-texts/WrongYearSBText" in row["url"]:
            path.write_bytes(body_page(row["url"], document(
                2890, "SB", own_year, tail=extra_venue,
            ).replace("RELATING TO OVERSIGHT.", "RELATING TO PROJECTS.")))
        row["body_binding"] = archive._binding(path)
    archive._write_rows(source / "request-ledger.jsonl", ledger)
    manifest = archive._json(source / "manifest.json")
    manifest["input_gap_queue"] = archive._binding(source / "input_gap_queue.parquet")
    manifest["artifacts"] = {
        path.relative_to(source).as_posix(): archive._binding(path)
        for path in source.rglob("*") if path.is_file() and path != source / "manifest.json"
    }
    write_json(source / "manifest.json", manifest)
    return original


def enable_context_projection(source):
    manifest = archive._json(source / "manifest.json")
    manifest["explicit_original_context_projection"] = archive.CONTEXT_PROJECTION
    write_json(source / "manifest.json", manifest)


def test_source_session_projection_is_opt_in_action_bound_and_preserves_earlier_view(packet_source):
    source, _, out = packet_source
    original = declared_2023_source(source)
    build(source, out)
    earlier, _, _, _ = archive.load_billcam(out)
    old = next(row for row in earlier if row["bill_id"] == "earlier-original-sb")
    assert old["session_identifier"] == "2023 Regular Session"
    assert not any(row["bill_id"] == "original-sb" for row in earlier)
    enable_context_projection(source)
    projected = out.with_name("projected")
    build(source, projected)
    views, contexts, _, manifest = archive.load_billcam(projected)
    assert len(views) == len(contexts) == 1
    view = views[0]
    assert contexts == [original] and view["original_target_context"] == original
    assert view["source_record"] == old["source_record"]
    assert view["text"] == old["text"] and view["view_id"] != old["view_id"]
    assert view["view_id"].endswith(":original-sb")
    assert view["source_identity"]["printed_year"] == "2023"
    assert view["source_identity"]["session_identifier"] == "2024"
    projection = view["source_identity"]["explicit_provider_context_projection"]
    assert projection["original_provider_session"]["name"] == "2023 Regular Session"
    assert manifest["counts"]["n_action_proven_carryover_views"] == 1
    assert all(view[flag] is False for flag in archive.FLAGS)
    assert archive.load_billcam(out)[0] == earlier


@pytest.mark.parametrize("wrong", [
    None, False, {}, {"original_context_session_identifier": "2025"},
])
def test_unsupported_context_projection_fails_closed(packet_source, wrong):
    source, _, out = packet_source
    declared_2023_source(source)
    manifest = archive._json(source / "manifest.json")
    manifest["explicit_original_context_projection"] = wrong
    write_json(source / "manifest.json", manifest)
    with pytest.raises(ValueError, match="unsupported or unbound original context projection"):
        build(source, out)


def test_context_projection_without_complete_original_action_binding_fails_closed(packet_source):
    source, _, out = packet_source
    declared_2023_source(source)
    enable_context_projection(source)
    manifest = archive._json(source / "manifest.json")
    del manifest["explicit_carryover_evidence"]
    write_json(source / "manifest.json", manifest)
    with pytest.raises(ValueError, match="unsupported or unbound original context projection"):
        build(source, out)


@pytest.mark.parametrize(("year", "extra_venue"), [
    ("2024", ""),
    ("2023", "THIRTY-SECOND LEGISLATURE, 2024"),
])
def test_projection_never_uses_matching_context_year_or_ambiguous_venue_as_action_proof(
    packet_source, year, extra_venue,
):
    source, _, out = packet_source
    declared_2023_source(source, own_year=year, extra_venue=extra_venue)
    enable_context_projection(source)
    build(source, out)
    assert archive.load_billcam(out)[0] == []
    assert any(row["disposition"] == "printed_own_identity_or_year_conflict_not_a_fill"
               for row in archive._rows(out / "source_dispositions.jsonl"))

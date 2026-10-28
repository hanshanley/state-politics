"""Repository-wide traceability and reproducibility checks."""

from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pandas.testing as pdt
import pytest
import yaml

from state_politics.analysis.gold_sample import sample_frame
from state_politics.platforms import official_documents as official_module
from state_politics.platforms.official_documents import load_registry, merge_documents

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def audit_cli(tmp_path, monkeypatch):
    module = runpy.run_path(str(ROOT / "scripts/audit_reproducibility.py"))
    namespace = module["main"].__globals__
    manifest = {
        "version": 1, "generated_artifacts": [], "manual_inputs": [],
        "random_processes": [], "environment": {}, "analysis_parameters": {},
    }
    calls = []
    monkeypatch.setitem(namespace, "ROOT", tmp_path)
    monkeypatch.setitem(namespace, "load_yaml", lambda _: manifest)
    for name in (
        "audit_manifest", "audit_curated_configs", "audit_gold",
        "audit_analysis_parameters", "audit_public_docs",
    ):
        monkeypatch.setitem(namespace, name, lambda *args, **kwargs: None)
    monkeypatch.setitem(namespace, "audit_artifacts", lambda _: calls.append("audit") or {})
    original = tmp_path / "data/processed/reproducibility_report.json"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"original historical report\n")
    return module["main"], original, calls, namespace


@pytest.mark.parametrize("failed", [False, True])
def test_audit_cli_default_preserves_the_original_report(audit_cli, capsys, failed):
    main, original, _, namespace = audit_cli
    before = original.read_bytes()
    if failed:
        def artifact_failure(audit):
            audit.require(False, "fixture missing prerequisite")
            return {}
        namespace["audit_artifacts"] = artifact_failure
        with pytest.raises(SystemExit) as error:
            main([])
        assert error.value.code == 1
    else:
        assert main([]) == 0
    assert original.read_bytes() == before
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["scientific_certification"] == "not_performed"
    assert report["status"] == ("blocked" if failed else "structural_checks_passed")
    assert "checks" in captured.err


@pytest.mark.parametrize("linked", [False, True])
def test_audit_cli_existing_report_is_rejected_before_data_checks(audit_cli, linked):
    main, original, calls, _ = audit_cli
    before = original.read_bytes()
    target = original.parent / "linked.json" if linked else original
    if linked:
        target.symlink_to(original)
    with pytest.raises(SystemExit) as error:
        main(["--report", str(target)])
    assert error.value.code == 2
    assert original.read_bytes() == before and not calls


def test_audit_cli_concurrent_report_creation_is_preserved(audit_cli):
    main, original, _, namespace = audit_cli
    target = original.parent / "another-writer.json"

    def create_report(audit):
        target.write_bytes(b"another writer's report\n")
        return {}

    namespace["audit_artifacts"] = create_report
    with pytest.raises(SystemExit) as error:
        main(["--report", str(target)])
    assert error.value.code == 2
    assert target.read_bytes() == b"another writer's report\n"
    assert original.read_bytes() == b"original historical report\n"


def test_audit_checks_only_named_manual_inputs_for_git_ignores(monkeypatch):
    module = runpy.run_path(str(ROOT / "scripts/audit_reproducibility.py"))
    namespace = module["audit_manifest"].__globals__
    manifest = yaml.safe_load((ROOT / "conf/reproducibility.yml").read_text())
    paths = [entry["path"] for entry in manifest["manual_inputs"]]
    queries = []

    def git_files(arguments):
        queries.append(arguments)
        return set(paths) if arguments == ["ls-files"] else set()

    monkeypatch.setitem(namespace, "git_files", git_files)
    monkeypatch.setattr(namespace["shutil"], "which", lambda _: None)
    module["audit_manifest"](module["Audit"](), manifest, require_tracked=True)
    assert ["ls-files", "--others", "-i", "--exclude-standard", "--", *paths] in queries


@pytest.mark.parametrize("ignored", [False, True])
def test_scoped_audit_still_detects_ignored_manual_inputs(tmp_path, monkeypatch, ignored):
    module = runpy.run_path(str(ROOT / "scripts/audit_reproducibility.py"))
    namespace = module["audit_manifest"].__globals__
    manifest = yaml.safe_load((ROOT / "conf/reproducibility.yml").read_text())
    payload = b"authored fixture input\n"
    (tmp_path / "manual.csv").write_bytes(payload)
    (tmp_path / ".gitignore").write_text("manual.csv\n" if ignored else "other.csv\n")
    for name in ("CITATIONS.md", "pyproject.toml", "uv.lock"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    manifest["manual_inputs"] = [{
        "path": "manual.csv", "sha256": hashlib.sha256(payload).hexdigest(),
    }]
    monkeypatch.setitem(namespace, "ROOT", tmp_path)
    monkeypatch.setattr(namespace["shutil"], "which", lambda _: None)
    audit = module["Audit"]()
    module["audit_manifest"](audit, manifest, require_tracked=False)
    assert ("manual input is gitignored: manual.csv" in audit.failures) is ignored


@pytest.mark.parametrize("failed", [False, True])
def test_audit_cli_fresh_report_preserves_real_failure_status(audit_cli, failed):
    main, original, _, namespace = audit_cli
    target = original.parent / "fresh.json"
    if failed:
        def artifact_failure(audit):
            audit.require(False, "fixture missing prerequisite")
            return {}
        namespace["audit_artifacts"] = artifact_failure
        with pytest.raises(SystemExit) as error:
            main(["--report", str(target)])
        assert error.value.code == 1
    else:
        assert main(["--report", str(target)]) == 0
    report = json.loads(target.read_text())
    assert report["status"] == ("blocked" if failed else "structural_checks_passed")
    assert report["scientific_certification"] == "not_performed"
    assert bool(report["failures"]) is failed
    assert original.read_bytes() == b"original historical report\n"


def test_manual_input_hashes_match_manifest():
    manifest = yaml.safe_load((ROOT / "conf/reproducibility.yml").read_text())
    for entry in manifest["manual_inputs"]:
        path = ROOT / entry["path"]
        assert path.exists(), entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["path"]


def test_manifested_hosts_are_reputable_explicit_allowlists():
    manifest = yaml.safe_load((ROOT / "conf/reproducibility.yml").read_text())
    hosts = manifest["trusted_source_hosts"]

    assert "issuu.com" in hosts["official_document_pages"]
    assert "static.wixstatic.com" in hosts["official_document_content"]
    assert "apps.legislature.ky.gov" in hosts["caucus_sources"]
    assert all(not host.endswith(".example") for values in hosts.values() for host in values)


def test_official_ocr_registry_is_primary_and_hashed():
    sources = load_registry()
    assert len(sources) == 5
    assert all(source["primary_source"] is True for source in sources)
    pdfs = [source for source in sources if source["extraction"] == "scanned_pdf"]
    assert len(pdfs) == 4
    assert all(len(source["expected_document_sha256"]) == 64 for source in pdfs)


def test_official_document_hash_drift_is_rejected(monkeypatch):
    source = next(
        source for source in load_registry() if source["extraction"] == "scanned_pdf"
    )

    class Record:
        ok = True
        error = None

    monkeypatch.setattr(
        official_module,
        "fetch",
        lambda *args, **kwargs: (b"tampered source", Record()),
    )
    with pytest.raises(ValueError, match="source hash changed"):
        official_module._verified_fetch(
            source["document_url"],
            expected_sha256=source["expected_document_sha256"],
            source_org=source["institution"],
            note="test",
            log=object(),
        )


def test_merge_official_documents_replaces_by_stable_id_and_url():
    corpus = pd.DataFrame(
        [
            {
                "official_source_id": None,
                "state": "NY",
                "party": "D",
                "url": "https://issuu.com/nydems/docs/resolutions",
                "fetched_url": "https://issuu.com/nydems/docs/resolutions",
                "text": "old manual OCR",
            },
            {
                "official_source_id": None,
                "state": "TX",
                "party": "R",
                "url": "https://example.test/platform",
                "fetched_url": "https://example.test/platform.pdf",
                "text": "keep",
            },
            {
                "official_source_id": None,
                "state": "LA",
                "party": "R",
                "url": "https://www.lagop.com/2025-rscc-resolutions#q1",
                "fetched_url": "https://static.wixstatic.com/ugd/q1.pdf",
                "text": "old fragment URL OCR",
            },
        ]
    )
    incoming = [
        {
            "official_source_id": "ny-dem-state-committee-resolutions-2019-2024",
            "state": "NY",
            "party": "D",
            "url": "https://issuu.com/nydems/docs/resolutions",
            "fetched_url": "https://issuu.com/nydems/docs/resolutions",
            "text": "reproducible OCR",
        },
        {
            "official_source_id": "la-q1",
            "state": "LA",
            "party": "R",
            "url": "https://www.lagop.com/2025-rscc-resolutions",
            "fetched_url": "https://static.wixstatic.com/ugd/q1.pdf",
            "text": "reproducible Louisiana OCR",
        },
    ]
    merged = merge_documents(corpus, incoming)

    assert len(merged) == 3
    assert "old manual OCR" not in set(merged["text"])
    assert "old fragment URL OCR" not in set(merged["text"])
    assert "reproducible OCR" in set(merged["text"])
    assert "reproducible Louisiana OCR" in set(merged["text"])
    assert "keep" in set(merged["text"])


def test_reproducibility_audit_passes_current_artifacts():
    result = subprocess.run(
        [sys.executable, "scripts/audit_reproducibility.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_gold_template_sampling_is_deterministic_and_seeded():
    frame = pd.DataFrame(
        {
            "state": ["AK"] * 20,
            "party": ["D"] * 20,
            "year": [2024] * 20,
            "source_document_sha256": [f"{index:064x}" for index in range(20)],
            "plank_index": list(range(20)),
            "text": [f"plank {index}" for index in range(20)],
        }
    )
    first = sample_frame(frame, seed=20260729, size=8)
    second = sample_frame(frame, seed=20260729, size=8)
    other = sample_frame(frame, seed=7, size=8)

    pdt.assert_frame_equal(first, second)
    assert first["text"].tolist() != other["text"].tolist()
    assert first["gold_topic"].eq("").all()


@pytest.mark.parametrize("outcome_p_value", [None, 0.5])
def test_artifact_audit_reports_undefined_election_metrics(
    tmp_path, monkeypatch, outcome_p_value,
):
    import json

    sys.path.insert(0, str(ROOT / "scripts"))
    import audit_reproducibility as script

    data = tmp_path / "data" / "processed"
    data.mkdir(parents=True)
    frames = {
        "platforms_2018_present.parquet": pd.DataFrame({
            "confirmed": [False], "state": ["TX"], "party": ["D"], "year": [2026],
            "source": ["html"],
        }),
        "platform_gap_report.csv": pd.DataFrame(columns=[
            "state", "party", "n_confirmed", "gap_finding",
        ]),
        "caucus_priorities.parquet": pd.DataFrame(columns=["state"]),
        "bills.parquet": pd.DataFrame(columns=[
            "state", "sponsor_party", "originating_chamber", "recorded_outcome",
            "recorded_enacted", "n_actions", "n_vote_events",
        ]),
        "planks_classified.parquet": pd.DataFrame(columns=["document_index", "topic"]),
        "state_party_focus.csv": pd.DataFrame(columns=[
            "state", "party", "stated_source", "bill_n_items", "bill_status",
        ]),
        "election_focus_by_state_party.csv": pd.DataFrame(columns=[
            "n_bills", "n_election_bills",
        ]),
        "state_party_terms.csv": pd.DataFrame({
            "peer_absent": [False], "log2_concentration": [0.0],
            "count": [1], "feature_total": [1], "peer_count": [1],
            "peer_feature_total": [1],
        }),
        "bill_actions.parquet": pd.DataFrame(columns=["bill_id"]),
        "vote_events.parquet": pd.DataFrame(columns=["bill_id"]),
        "bill_outcomes_by_state_party.csv": pd.DataFrame({
            "reliable": pd.Series(dtype=bool),
            **{column: pd.Series(dtype=float) for column in (
                "action_coverage", "advancement_rate", "enactment_rate", "vote_coverage",
            )},
        }),
        "rollcall_party_support.csv": pd.DataFrame(columns=["mean_yes_share"]),
    }
    for name, frame in frames.items():
        if name.endswith(".parquet"):
            frame.to_parquet(data / name, index=False)
        else:
            frame.to_csv(data / name, index=False)
    (data / "election_title_validation.json").write_text(
        json.dumps({"precision": None, "recall": None}),
    )
    (data / "bill_outcome_comparison.json").write_text(
        json.dumps({"n_paired_states": 2, "sign_flip_p_value": outcome_p_value}),
    )
    (tmp_path / "conf").mkdir()
    (tmp_path / "conf" / "official_document_registry.yml").write_text("sources: []\n")
    monkeypatch.setattr(script, "ROOT", tmp_path)
    audit = script.Audit()

    script.audit_artifacts(audit)

    assert "election precision is unavailable or not a proportion" in audit.failures
    assert "election recall is unavailable or not a proportion" in audit.failures
    assert ("outcome sign-flip p-value is not a probability" in audit.failures) == (
        outcome_p_value is None
    )

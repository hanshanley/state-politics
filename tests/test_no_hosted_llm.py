"""Enforce the local-only compute policy.

This project must not call hosted LLM APIs; any model runs locally on Apple Silicon. That
rule is only meaningful if it is checked, so this test fails the build the moment a hosted
provider import or endpoint appears anywhere in the source tree.
"""

from __future__ import annotations

from pathlib import Path

from state_politics.compute import audit_source_tree, describe_hardware, select_device

REPO_ROOT = Path(__file__).resolve().parent.parent

# The "must actually catch something" tests below need to write banned tokens into a
# temporary file. Those tokens are assembled at runtime rather than written as literals,
# so this file does not trip the repo-wide audit and no path has to be excluded from it --
# the guard therefore covers 100% of the source tree, including its own tests.
_BANNED_MODULE = "open" + "ai"
_BANNED_HOST = "api." + "anthropic" + ".com"


def test_no_hosted_llm_usage_anywhere_in_repo():
    violations = audit_source_tree(REPO_ROOT)
    assert violations == [], "hosted LLM usage detected:\n" + "\n".join(
        str(v) for v in violations
    )


def test_audit_flags_a_hosted_import(tmp_path):
    """The guard must actually catch a violation, not just pass vacuously."""
    offender = tmp_path / "bad.py"
    offender.write_text(f"import {_BANNED_MODULE}\n", encoding="utf-8")
    violations = audit_source_tree(tmp_path)
    assert len(violations) == 1
    assert _BANNED_MODULE in violations[0].reason


def test_audit_flags_a_hosted_endpoint(tmp_path):
    offender = tmp_path / "bad.py"
    offender.write_text(f'URL = "https://{_BANNED_HOST}/v1/messages"\n', encoding="utf-8")
    violations = audit_source_tree(tmp_path)
    assert len(violations) == 1
    assert _BANNED_HOST in violations[0].reason


def test_audit_ignores_similarly_named_local_module(tmp_path):
    (tmp_path / "ok.py").write_text("from openstates_helper import load\n", encoding="utf-8")
    assert audit_source_tree(tmp_path) == []


def test_select_device_is_local():
    assert select_device() in {"mps", "cpu"}


def test_describe_hardware_reports_a_local_device():
    info = describe_hardware()
    assert info["device"] in {"mps", "cpu"}
    assert info["python"]

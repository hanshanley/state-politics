"""Only manifest-bound, unchanged, unapproved research files are served locally."""

import functools
import hashlib
import json
import runpy
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/serve_research.py"))


@pytest.fixture
def research_bundle(tmp_path):
    root = tmp_path / "bundle"
    (root / "downloads").mkdir(parents=True)
    data = b'{"complete_source":9007199254740999,"text":"full source ending"}\n'
    (root / "index.html").write_bytes(data)
    (root / "private-not-an-artifact.txt").write_text("must not be served")
    manifest = {
        "schema": "local_cycle_evidence_preview_v1",
        "publication_status": "local_only_unpublished",
        "model_input_approved": False, "analytical_admission": False,
        "outputs": {"index.html": {"sha256": hashlib.sha256(data).hexdigest(),
                                    "bytes": len(data)}},
    }
    path = root / "downloads/build_manifest.json"
    path.write_text(json.dumps(manifest))
    return root, path, manifest, data


@pytest.fixture
def research_http(research_bundle):
    root, *_ = research_bundle
    bundles = {"evidence": MODULE["bind_bundle"](root, "evidence")}
    handler = functools.partial(MODULE["ResearchHandler"], bundles=bundles)
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", root
        finally:
            server.shutdown()
            thread.join()


def test_workspace_serves_exact_bytes_and_manifest_bound_links(research_http, research_bundle):
    address, _ = research_http
    with urllib.request.urlopen(address + "/") as response:
        body = response.read()
    assert b"/evidence/index.html" in body
    assert b"/sessions/index.html" in body
    assert b"/review/human-review.html" in body
    with urllib.request.urlopen(address + "/evidence/index.html") as response:
        assert response.read() == research_bundle[3]
        assert response.headers["X-Content-Type-Options"] == "nosniff"
    with urllib.request.urlopen(urllib.request.Request(
        address + "/evidence/index.html", method="HEAD",
    )) as response:
        assert response.read() == b""
        assert int(response.headers["Content-Length"]) == len(research_bundle[3])


@pytest.mark.parametrize(("path", "status"), [
    ("/evidence/private-not-an-artifact.txt", 404),
    ("/evidence/%2e%2e/private.txt", 400),
    ("/evidence/%5c..%5cprivate.txt", 400),
    ("/evidence//index.html", 400),
    ("/other/index.html", 404),
])
def test_workspace_refuses_unbound_and_traversal_paths(research_http, path, status):
    address, _ = research_http
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(address + path)
    assert caught.value.code == status


def test_workspace_refuses_changed_file_and_foreign_host(research_http):
    address, root = research_http
    (root / "index.html").write_text("changed bytes")
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(address + "/evidence/index.html")
    assert caught.value.code == 409
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(urllib.request.Request(
            address + "/", headers={"Host": "other.test"},
        ))
    assert caught.value.code == 403


@pytest.mark.parametrize("defect", ["approval", "hash", "link"])
def test_workspace_binding_refuses_invalid_bundle(research_bundle, defect):
    root, manifest_path, manifest, _ = research_bundle
    if defect == "approval":
        manifest["analytical_admission"] = True
    elif defect == "hash":
        manifest["outputs"]["index.html"]["sha256"] = "a" * 64
    else:
        (root / "index.html").unlink()
        (root / "index.html").symlink_to(root / "private-not-an-artifact.txt")
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        MODULE["bind_bundle"](root, "evidence")


def test_workspace_cli_does_not_resolve_away_a_linked_bundle(research_bundle, tmp_path):
    root, *_ = research_bundle
    linked = tmp_path / "linked-bundle"
    linked.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="non-symlink"):
        MODULE["main"]([
            "--evidence", str(linked), "--sessions", str(root),
            "--review", str(root), "--port", "0",
        ])

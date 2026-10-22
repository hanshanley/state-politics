#!/usr/bin/env python3
"""Serve only explicitly bound unpublished research bundles on loopback."""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import mimetypes
import os
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = {
    "evidence": "downloads/build_manifest.json",
    "sessions": "manifest.json",
    "review": "human_packet_manifest.json",
    "sources": "manifest.json",
}
HOME = b"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>State politics research workspace</title><style>
:root{color-scheme:light;background:#f6f4ee;color:#242824;font-family:Georgia,serif}
body{max-width:900px;margin:64px auto;padding:0 24px;line-height:1.6}
h1{font-size:2rem;font-weight:normal}h2{font-size:1.3rem;margin-bottom:4px}
article{border-top:1px solid #cbc9bf;padding:16px 0}a{color:#275542}
.note{font:14px/1.6 system-ui,sans-serif;color:#575b53}p{margin-top:4px}
</style><main><p class="note">LOCAL RESEARCH / UNPUBLISHED</p>
<h1>State politics: evidence and review</h1>
<p>Inspect the records, compare cohort definitions, and review complete inputs
without treating provisional classifications as established findings.</p>
<article><h2><a href="/evidence/index.html">Evidence explorer</a></h2>
<p>All-state calendar-candidate and platform evidence, native reader alternatives,
receipt observations, explicit gaps, and complete query downloads.</p></article>
<article><h2><a href="/sessions/index.html">Legislative-session comparison</a></h2>
<p>Verified publisher-session membership, original metadata and date observations.
This separate frame does not replace calendar eligibility or invent filing dates.</p></article>
@@SOURCE_INVENTORY@@
<article><h2><a href="/review/human-review.html">Model-blind human review</a></h2>
<p>Unseen complete inputs and source alternatives, rubric-guided annotation,
local drafts, and independently validated exports. No predictions are shown.</p></article>
<p class="note">Human identity remains self-attested. No checkbox certifies gold,
model accuracy, operative platforms, party attribution, or scientific admission.
Nothing here publishes a report or changes the production website.</p></main></html>"""


def fingerprint(path):
    return stat_fingerprint(path.stat())


def stat_fingerprint(stat):
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, stat.st_dev


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bind_bundle(directory, kind):
    directory = directory.absolute()
    if (
        kind not in MANIFESTS or not directory.is_dir() or directory.is_symlink()
        or directory.resolve() != directory or not directory.is_relative_to(ROOT / "data")
    ):
        raise ValueError("use an explicit non-symlink bundle under project data/")
    manifest_name = MANIFESTS[kind]
    manifest_path = directory / manifest_name
    if not manifest_path.is_file() or manifest_path.resolve() != manifest_path:
        raise ValueError("missing or linked research manifest")
    manifest = json.loads(manifest_path.read_bytes())
    if (
        manifest.get("model_input_approved") is not False
        or manifest.get("analytical_admission") is not False
    ):
        raise ValueError("research bundles must remain explicitly unapproved")
    if kind == "evidence":
        if (
            manifest.get("schema") != "local_cycle_evidence_preview_v1"
            or manifest.get("publication_status") != "local_only_unpublished"
        ):
            raise ValueError("unpublished evidence preview required")
        files = manifest["outputs"]
    elif kind in {"sessions", "sources"}:
        expected_status = {
            "sessions": (
                "complete_verified_session_comparison_not_primary_cohort_or_scientific_admission"
            ),
            "sources": "complete_all_state_native_inventory_catalog_not_scientific_admission",
        }[kind]
        if manifest.get("status") != expected_status or manifest.get("publication") is not False:
            raise ValueError("unpublished source comparison required")
        files = manifest["artifacts"]
    else:
        if (
            manifest.get("schema") != "local_self_attested_human_review_v1"
            or manifest.get("status") != "local_only_unpublished_unannotated"
            or any(manifest.get(flag) is not False
                   for flag in ("human_gold", "independent_gold", "canonical_gold"))
        ):
            raise ValueError("unapproved model-blind review packet required")
        files = {
            **manifest["assets"],
            **{f"complete-inputs/{name}": value
               for name, value in manifest["complete_inputs"].items()},
            "ui-data.json": manifest["ui_data"],
            "complete-inputs.zip": manifest["complete_inputs_zip"],
        }
    files = {**files, manifest_name: {
        "sha256": sha256(manifest_path), "bytes": manifest_path.stat().st_size,
    }}
    bindings = {}
    for name, expected in files.items():
        path = directory / name
        if (
            not name or name.startswith("/") or "\\" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or not path.is_file() or path.resolve() != path
        ):
            raise ValueError(f"unsafe or missing research artifact: {name}")
        if path.stat().st_size != expected["bytes"] or sha256(path) != expected["sha256"]:
            raise ValueError(f"research artifact hash/size mismatch: {name}")
        bindings[name] = (path, fingerprint(path))
    return directory, bindings


class ResearchHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, bundles, **kwargs):
        self.bundles = bundles
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self.respond(send_body=True)

    def do_HEAD(self):
        self.respond(send_body=False)

    def respond(self, *, send_body):
        try:
            host = urlsplit(f"//{self.headers.get('Host', '')}").hostname
            path = unquote(urlsplit(self.path).path, encoding="utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError):
            self.send_error(400, "Malformed local request")
            return
        if host not in {"127.0.0.1", "localhost"}:
            self.send_error(403, "Loopback Host required")
            return
        if path == "/":
            inventory = b"""<article><h2><a href="/sources/index.html">
Native-source collection ledger</a></h2><p>All-state collection status,
original publisher metadata, explicit source restrictions, and retained raw
responses. Filename lists and repeated observations are not new bills or
recovered original texts.</p></article>"""
            home = HOME.replace(
                b"@@SOURCE_INVENTORY@@", inventory if "sources" in self.bundles else b"",
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(home)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if send_body:
                self.wfile.write(home)
            return
        parts = path.split("/")
        if (
            not path.startswith("/") or "\\" in path
            or any(part in {"", ".", ".."} for part in parts[1:])
        ):
            self.send_error(400, "Invalid bundle path")
            return
        if len(parts) < 3 or parts[1] not in self.bundles:
            self.send_error(404, "Unknown research artifact")
            return
        directory, bindings = self.bundles[parts[1]]
        name = PurePosixPath(*parts[2:]).as_posix()
        binding = bindings.get(name)
        if binding is None:
            self.send_error(404, "Artifact is not in the bound manifest")
            return
        target, expected = binding
        if (
            directory.is_symlink() or not target.is_file() or target.resolve() != target
            or fingerprint(target) != expected
        ):
            self.send_error(409, "Bound artifact changed; restart with a verified bundle")
            return
        try:
            handle = target.open("rb")
        except (FileNotFoundError, PermissionError):
            self.send_error(409, "Bound artifact became unavailable")
            return
        with handle:
            if stat_fingerprint(os.fstat(handle.fileno())) != expected:
                self.send_error(409, "Bound artifact changed before serving")
                return
            self.send_response(200)
            self.send_header(
                "Content-Type", mimetypes.guess_type(name)[0] or "application/octet-stream",
            )
            self.send_header("Content-Length", str(expected[0]))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if send_body:
                try:
                    shutil.copyfileobj(handle, self.wfile, length=1024 * 1024)
                except (BrokenPipeError, ConnectionResetError):
                    self.log_error("Client disconnected during bound artifact download: %s", name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    bundles = {kind: bind_bundle(getattr(args, kind), kind)
               for kind in MANIFESTS if getattr(args, kind) is not None}
    handler = functools.partial(ResearchHandler, bundles=bundles)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Unpublished research workspace: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Local research workspace stopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

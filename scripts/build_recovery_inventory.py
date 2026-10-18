#!/usr/bin/env python3
"""Freeze a successor recovery inventory; never overwrite packets or admit policy to analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from state_politics.platforms.recovery import ROOT, build_inventory
from state_politics.provenance import sha256_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--captures", action="append", type=Path, default=[])
    parser.add_argument("--ocr", action="append", type=Path, default=[])
    parser.add_argument("--docx", action="append", type=Path, default=[])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.out.resolve().is_relative_to((ROOT / "data").resolve()):
        parser.error("inventory output must remain under this project's ignored data/ directory")
    summary = build_inventory(
        args.baseline, args.captures,
        [("ocr", path) for path in args.ocr] + [("docx_main_document", path) for path in args.docx],
        args.out,
    )
    print(json.dumps({
        key: value for key, value in summary.items()
        if key.startswith("n_") or key in {"schema", "expected_organizations"}
    }, indent=2))
    print("manifest", sha256_file(args.out / "manifest.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

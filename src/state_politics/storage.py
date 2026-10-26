"""Create independent evidence files without silent full-copy fallback on macOS."""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path


def native_clone(source, target):
    library = ctypes.CDLL(None, use_errno=True)
    clone = library.clonefile
    clone.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int)
    clone.restype = ctypes.c_int
    if clone(os.fsencode(source), os.fsencode(target), 0) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def copy_evidence(source, target):
    """Create a fresh full file; macOS requires native copy-on-write support."""
    source, target = Path(source), Path(target)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"regular, unlinked evidence source required: {source}")
    if sys.platform == "darwin":
        native_clone(source, target)
    else:
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
    return target

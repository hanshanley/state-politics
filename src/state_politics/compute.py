"""Local-only compute policy.

This project does not call hosted LLM APIs. Any model it runs -- embeddings, classifiers,
topic models -- runs **locally on this machine's Apple Silicon GPU** via Metal Performance
Shaders (MPS), falling back to CPU.

Two reasons this is a hard rule rather than a preference:

1. *Provenance.* A hosted model is an unversioned, non-reproducible dependency. A result
   that cannot be regenerated from pinned local weights is not reproducible research.
2. *Cost and control.* Classifying every plank of ~100 party platforms and hundreds of
   thousands of state bills through a paid API is both expensive and rate-limited.

The policy is enforced, not just documented: :func:`audit_source_tree` scans the source
tree for hosted-LLM imports and endpoints, and the test suite fails the build if any
appear.

Hardware note: the development machine is an Apple M4 with 16 GB of unified memory. That
budget comfortably fits sentence-embedding models and small/medium quantized transformers;
it does not fit large unquantized models, so model choices should stay within it.
"""

from __future__ import annotations

import platform
import re
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "REMOTE_LLM_HOSTS",
    "REMOTE_LLM_MODULES",
    "Violation",
    "audit_source_tree",
    "describe_hardware",
    "select_device",
]

#: Python packages that talk to hosted LLM/inference providers.
REMOTE_LLM_MODULES: frozenset[str] = frozenset(
    {
        "openai",
        "anthropic",
        "cohere",
        "replicate",
        "together",
        "mistralai",
        "groq",
        "litellm",
        "langchain_openai",
        "langchain_anthropic",
        "google.generativeai",
        "google_generativeai",
        "vertexai",
        "boto3.bedrock",
        "huggingface_hub.InferenceClient",
    }
)

#: Hostnames of hosted inference endpoints.
REMOTE_LLM_HOSTS: frozenset[str] = frozenset(
    {
        "api.openai.com",
        "api.anthropic.com",
        "api.cohere.ai",
        "api.cohere.com",
        "api.replicate.com",
        "api.together.xyz",
        "api.mistral.ai",
        "api.groq.com",
        "generativelanguage.googleapis.com",
        "api-inference.huggingface.co",
        "bedrock-runtime.us-east-1.amazonaws.com",
    }
)


@dataclass(frozen=True, slots=True)
class Violation:
    """One place where the local-only policy is broken."""

    path: Path
    line_number: int
    line: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line_number}: {self.reason}: {self.line.strip()}"


def select_device(*, prefer_mps: bool = True) -> str:
    """Return the local torch device to use: ``"mps"`` on Apple Silicon, else ``"cpu"``.

    Never returns a remote or hosted backend. Returns ``"cpu"`` when torch is absent, so
    that importing this module does not require the optional model dependencies.
    """
    try:
        import torch
    except ImportError:
        return "cpu"

    if prefer_mps and torch.backends.mps.is_available() and torch.backends.mps.is_built():
        return "mps"
    return "cpu"


def describe_hardware() -> dict[str, str]:
    """Human-readable description of the local machine, for run manifests."""
    info = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "device": select_device(),
    }
    if platform.system() == "Darwin":
        info["cpu"] = _sysctl("machdep.cpu.brand_string") or "unknown"
        memsize = _sysctl("hw.memsize")
        if memsize and memsize.isdigit():
            info["memory_gb"] = f"{int(memsize) / 1024**3:.0f}"
    return info


def _sysctl(key: str) -> str | None:
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            ["/usr/sbin/sysctl", "-n", key],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _import_patterns() -> list[tuple[re.Pattern[str], str]]:
    patterns = []
    for module in REMOTE_LLM_MODULES:
        root = re.escape(module.split(".")[0])
        rest = re.escape(module)
        patterns.append(
            (
                re.compile(rf"^\s*(?:import\s+{rest}\b|from\s+{rest}\b|import\s+{root}\b(?!\w))"),
                f"hosted LLM module {module!r}",
            )
        )
    return patterns


def audit_source_tree(
    root: Path | str,
    *,
    skip_dirs: Iterable[str] = (".git", ".venv", "venv", "__pycache__", "data", "node_modules"),
    skip_files: Iterable[Path | str] = (),
) -> list[Violation]:
    """Scan ``root`` for hosted-LLM imports or endpoints; return every violation found.

    ``skip_files`` exists so this module -- which necessarily *names* the banned modules
    and hosts in order to detect them -- does not flag itself.
    """
    root = Path(root)
    skip_dir_set = set(skip_dirs)
    skip_resolved = {Path(p).resolve() for p in skip_files} | {Path(__file__).resolve()}
    import_patterns = _import_patterns()

    violations: list[Violation] = []
    for path in _python_files(root, skip_dir_set):
        if path.resolve() in skip_resolved:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern, reason in import_patterns:
                if pattern.search(line):
                    violations.append(Violation(path, line_number, line, reason))
            for host in REMOTE_LLM_HOSTS:
                if host in line:
                    violations.append(
                        Violation(path, line_number, line, f"hosted inference endpoint {host!r}")
                    )
    return violations


def _python_files(root: Path, skip_dirs: set[str]) -> Iterator[Path]:
    for path in root.rglob("*.py"):
        if any(part in skip_dirs for part in path.parts):
            continue
        yield path

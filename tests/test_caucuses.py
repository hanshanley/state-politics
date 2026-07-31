"""Tests for the explicitly separate caucus-priorities supplement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from state_politics.caucuses import CaucusSource, collect_sources, load_registry


@dataclass(frozen=True)
class _Record:
    ok: bool
    content_type: str = "text/html"
    final_url: str | None = None
    content_sha256: str | None = "hash"


class _Log:
    pass


def test_registry_keeps_caucus_sources_separate_from_party_platforms():
    sources = load_registry()

    assert {source.state for source in sources} == {"KY", "MD", "NJ", "PA"}
    assert all("caucus" in source.document_type for source in sources)
    assert all(source.urls for source in sources)


def test_collect_sources_combines_only_the_curated_urls():
    source = CaucusSource(
        state="PA",
        party="D",
        year=2025,
        institution="Pennsylvania Senate Democratic Caucus",
        document_type="caucus_priority_agenda",
        description="Test source",
        urls=("https://example.test/index", "https://example.test/detail"),
    )
    calls = []

    def fetcher(url, **kwargs):
        calls.append((url, kwargs["source_org"]))
        body = f"<html><body><p>Priority from {url}</p></body></html>".encode()
        return body, _Record(ok=True, final_url=url)

    rows = collect_sources([source], log=_Log(), fetcher=fetcher)

    assert calls == [
        ("https://example.test/index", "Pennsylvania Senate Democratic Caucus"),
        ("https://example.test/detail", "Pennsylvania Senate Democratic Caucus"),
    ]
    assert len(rows) == 1
    assert rows[0]["n_pages"] == 2
    assert rows[0]["n_words"] == 6
    assert "index" in rows[0]["text"] and "detail" in rows[0]["text"]


def test_collect_sources_records_failed_supplemental_pages():
    source = CaucusSource(
        state="KY",
        party="R",
        year=2024,
        institution="Kentucky Senate Republican Caucus Campaign Committee",
        document_type="caucus_priority_bills",
        description="Test source",
        urls=("https://example.test/works", "https://example.test/fails"),
    )

    def fetcher(url, **kwargs):
        if url.endswith("fails"):
            return None, _Record(ok=False)
        return b"<p>Priority legislation</p>", _Record(ok=True, final_url=url)

    row = collect_sources([source], log=_Log(), fetcher=fetcher)[0]

    assert row["n_pages"] == 1
    assert "fails" in row["failed_urls"]
    assert row["n_words"] == 2


def test_collect_sources_fails_when_no_curated_page_is_available():
    source = CaucusSource(
        state="MD",
        party="D",
        year=2026,
        institution="Maryland Senate Democratic Caucus",
        document_type="caucus_priority_statement",
        description="Test source",
        urls=("https://example.test/fails",),
    )

    def fetcher(url, **kwargs):
        return None, _Record(ok=False)

    with pytest.raises(RuntimeError, match="all listed URLs failed"):
        collect_sources([source], log=_Log(), fetcher=fetcher)


def test_agenda_coverage_plot_requires_every_state_to_have_evidence(tmp_path):
    """The all-state figure must refuse to turn an unresolved state into a blank row."""
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import plot_state_agenda_coverage as plot

    platforms = pd.DataFrame(
        {
            "state": ["AK"],
            "party": ["D"],
            "confirmed": [True],
        }
    )
    caucuses = pd.DataFrame({"state": [], "party": []})

    with pytest.raises(ValueError, match="states have no stated-agenda evidence"):
        plot.build_figure(platforms, caucuses, tmp_path / "coverage.png")


def test_agenda_coverage_plot_rejects_supplement_that_overlaps_platforms(tmp_path):
    """A caucus document must not silently double-count a platform-covered state."""
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import plot_state_agenda_coverage as plot

    states = list(plot.STATE_CODES)
    platforms = pd.DataFrame(
        {
            "state": states,
            "party": ["D"] * len(states),
            "confirmed": [True] * len(states),
        }
    )
    caucuses = pd.DataFrame({"state": ["AK"], "party": ["R"]})

    with pytest.raises(ValueError, match="supplement should contain only states"):
        plot.build_figure(platforms, caucuses, tmp_path / "coverage.png")

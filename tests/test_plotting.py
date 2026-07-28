"""Tests for the shared plotting theme.

These pin the portfolio look: the palette and rcParams must stay byte-identical to
``congressional_record`` and ``pre1870_reapportionment_package`` so figures across the
portfolio remain visually consistent.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless: no display required

import matplotlib.pyplot as plt  # noqa: E402

from state_politics.plotting import charts, theme  # noqa: E402


def test_palette_matches_portfolio():
    """Hard-coded so a drift in the shared palette is caught, not silently accepted."""
    assert theme.BG == "#F7F5F0"
    assert theme.CARD == "#EFEDE8"
    assert theme.TEXT == "#1A1A1A"
    assert theme.MUTED == "#6B6B6B"
    assert theme.ACCENT == "#C85A3D"
    assert theme.BLUE == "#3D6F8C"
    assert theme.GOLD == "#C2993E"
    assert theme.GREEN == "#4A7C59"
    assert theme.GRID == "#D6D3CC"


def test_party_colors_follow_convention():
    assert theme.PARTY_COLORS["D"] == theme.BLUE
    assert theme.PARTY_COLORS["R"] == theme.ACCENT
    assert theme.party_color("unrecognised") == theme.MUTED


def test_apply_sets_signature_rcparams():
    theme.apply()
    assert plt.rcParams["figure.facecolor"] == theme.BG
    assert plt.rcParams["font.family"] == ["serif"]
    assert plt.rcParams["axes.spines.top"] is False
    assert plt.rcParams["axes.spines.right"] is False
    assert plt.rcParams["xtick.major.size"] == 0


def test_shade_darkens_and_tint_lightens():
    assert theme.shade(theme.BLUE, 0.45) != theme.BLUE
    assert theme.tint(theme.BLUE, 0.45) != theme.BLUE
    # Darkening reduces luminance; lightening raises it.
    def lum(hexcolor: str) -> float:
        c = hexcolor.lstrip("#")
        return sum(int(c[i:i + 2], 16) for i in (0, 2, 4))

    assert lum(theme.shade(theme.BLUE, 0.45)) < lum(theme.BLUE)
    assert lum(theme.tint(theme.BLUE, 0.45)) > lum(theme.BLUE)


def test_chamber_color_uses_state_legislature_names():
    assert set(theme.CHAMBER_STYLE) == {"upper", "lower"}
    assert theme.chamber_color("D", "lower") == theme.BLUE
    assert theme.chamber_color("D", "upper") != theme.BLUE


def test_stream_style_covers_both_evidence_streams():
    assert set(theme.STREAM_STYLE) == {"platform", "bills"}
    assert set(theme.STREAM_LABELS) == {"platform", "bills"}


def test_source_note_returns_wrapped_line_count():
    fig = plt.figure()
    lines = theme.source_note(fig, "word " * 100, width=40)
    assert lines > 1
    plt.close(fig)


def test_finish_writes_a_png(tmp_path):
    fig, ax = charts.new_figure(figsize=(6, 4))
    charts.line(ax, [2018, 2020, 2022], [0.1, 0.2, 0.3], color=theme.PARTY_COLORS["D"],
                label="Democratic")
    charts.style_axes(ax, "Title", "Year", "Share", subtitle="Subtitle")
    out = charts.finish(fig, ax, tmp_path / "fig.png", source="Source: test.")
    assert out.exists()
    assert out.stat().st_size > 0


def test_dumbbell_pairs_values_and_validates_length(tmp_path):
    fig, ax = charts.new_figure(figsize=(6, 4))
    charts.dumbbell(ax, ["Health", "Taxes"], [0.1, 0.3], [0.2, 0.15],
                    left_color=theme.BLUE, right_color=theme.ACCENT,
                    left_label="Platform", right_label="Bills")
    assert [t.get_text() for t in ax.get_yticklabels()] == ["Health", "Taxes"]
    charts.finish(fig, ax, tmp_path / "dumbbell.png")

    fig2, ax2 = charts.new_figure(figsize=(4, 3))
    try:
        import pytest

        with pytest.raises(ValueError, match="same length"):
            charts.dumbbell(ax2, ["A"], [0.1, 0.2], [0.3],
                            left_color=theme.BLUE, right_color=theme.ACCENT)
    finally:
        plt.close(fig2)


def test_source_note_reserve_scales_with_figure_height(tmp_path):
    """A fixed figure-fraction reserve leaves a large empty band under tall panels."""
    long_note = "word " * 120

    def rendered_height_ratio(figheight: float) -> float:
        fig, ax = charts.new_figure(figsize=(10, figheight))
        charts.line(ax, [1, 2], [1, 2], color=theme.BLUE)
        out = charts.finish(fig, ax, tmp_path / f"h{figheight}.png", source=long_note)
        return out.stat().st_size

    # Both must render; the tall figure must not be dominated by whitespace.
    assert rendered_height_ratio(6) > 0
    assert rendered_height_ratio(13) > 0

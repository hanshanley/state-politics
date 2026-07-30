"""Substack-style plotting theme, matched to the rest of the personal-projects portfolio.

The palette and rcParams mirror ``congressional_record/analysis/plotting/theme.py`` and
``pre1870_reapportionment_package/scripts/generate_figures.py`` so figures across the
portfolio share one look: cream background, serif font, muted grid, borderless legend,
italic source notes, bold titles, tickless axes.

Project-specific additions on top of the shared base:

* :data:`CHAMBER_STYLE` uses the state-legislature chamber names Open States actually
  emits (``upper``/``lower``) rather than House/Senate, since state chambers carry many
  different official names (General Assembly, House of Delegates, Legislative Assembly).
* :data:`STREAM_STYLE` distinguishes the project's two evidence streams -- what a party
  *says* (platforms) versus what it *files* (bills) -- because nearly every figure here
  puts those two side by side.

Usage::

    from state_politics.plotting import theme
    theme.apply()
    fig, ax = plt.subplots(figsize=(11, 6))
    ...
    theme.source_note(fig, "Source: ...")
"""

from __future__ import annotations

import textwrap

import matplotlib.patheffects as pe
import matplotlib.pyplot as plt

# ── Shared portfolio palette (identical to congressional_record/pre1870) ────────
BG = "#F7F5F0"
CARD = "#EFEDE8"
TEXT = "#1A1A1A"
MUTED = "#6B6B6B"
ACCENT = "#C85A3D"   # terracotta
BLUE = "#3D6F8C"     # muted blue
GOLD = "#C2993E"
GREEN = "#4A7C59"
GRID = "#D6D3CC"

#: Party colours drawn from the shared palette (muted, print-friendly).
PARTY_COLORS = {
    "D": BLUE,
    "R": ACCENT,
    "I": GREEN,
    "other": MUTED,
}
PARTY_LABELS = {
    "D": "Democratic state parties",
    "R": "Republican state parties",
    "I": "Independents",
    "other": "Other",
}


def _hex_to_rgb(color: str) -> tuple[float, float, float]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _rgb_to_hex(rgb) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02X}" for c in rgb)


def shade(color: str, amount: float = 0.4) -> str:
    """Darken ``color`` by mixing it ``amount`` of the way toward near-black.

    Used to separate chambers within a party: the darker variant keeps the party hue but
    gains contrast against the cream background, so two same-party lines stay
    distinguishable even in a small multi-panel grid.
    """
    return _rgb_to_hex(c * (1 - amount) + 0.10 * amount for c in _hex_to_rgb(color))


def tint(color: str, amount: float = 0.4) -> str:
    """Lighten ``color`` by mixing it ``amount`` of the way toward white."""
    return _rgb_to_hex(c + (1.0 - c) * amount for c in _hex_to_rgb(color))


# Chamber styling. Chamber is encoded on three channels at once -- colour depth, dash
# pattern and marker shape -- because a dash pattern alone is not readable at small panel
# sizes, where same-party lines were otherwise indistinguishable.
CHAMBER_STYLE = {
    "lower": {
        "linestyle": "-",
        "marker": "o",
        "linewidth": 2.4,
        "markersize": 4.0,
        "depth": 0.0,          # party colour as-is
    },
    "upper": {
        "linestyle": (0, (5, 2)),   # long, widely spaced dashes
        "marker": "^",
        "linewidth": 1.7,
        "markersize": 4.4,
        "depth": 0.45,         # noticeably darker than the lower-chamber line
    },
}
CHAMBER_LABELS = {"lower": "Lower chamber", "upper": "Upper chamber"}

# The two evidence streams. Platforms are the party organization's stated priorities;
# bills are its legislators' revealed priorities. Solid = said, dashed = done.
STREAM_STYLE = {
    "platform": {"linestyle": "-", "marker": "o", "linewidth": 2.4, "markersize": 4.0},
    "bills": {"linestyle": (0, (5, 2)), "marker": "s", "linewidth": 1.9, "markersize": 4.2},
}
STREAM_LABELS = {
    "platform": "Platform emphasis (stated)",
    "bills": "Bill sponsorship (revealed)",
}


def party_color(party: str) -> str:
    """Colour for a party code, defaulting to the muted grey for unknown codes."""
    return PARTY_COLORS.get(party, MUTED)


def chamber_color(party: str, chamber: str) -> str:
    """Party colour adjusted for chamber (lower chamber base, upper chamber darker)."""
    base = party_color(party)
    depth = CHAMBER_STYLE.get(chamber, {}).get("depth", 0.0)
    return shade(base, depth) if depth else base


RC_PARAMS = {
    "figure.facecolor": BG,
    "axes.facecolor": BG,
    "savefig.facecolor": BG,
    "text.color": TEXT,
    "axes.labelcolor": TEXT,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.edgecolor": GRID,
    "axes.linewidth": 0.8,
    "grid.color": GRID,
    "grid.alpha": 0.6,
    "grid.linewidth": 0.5,
    "font.family": "serif",
    "font.size": 12,
    "axes.titlesize": 16,
    "axes.titleweight": "bold",
    "axes.labelsize": 13,
    "figure.titlesize": 18,
    "legend.framealpha": 0.0,
    "legend.fontsize": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.major.size": 0,      # tickless axes for a cleaner, editorial look
    "ytick.major.size": 0,
    "text.parse_math": False,   # treat '$' literally (titles/labels are plain prose)
}

# A white "halo" so labels drawn over lines/fills stay legible.
_WHITE_STROKE = [pe.withStroke(linewidth=3.0, foreground="white")]


def white_stroke() -> list:
    """Path-effects list giving text a white outline (for labels drawn over data)."""
    return list(_WHITE_STROKE)


def apply() -> None:
    """Apply the shared portfolio theme to matplotlib's global rcParams."""
    plt.rcParams.update(RC_PARAMS)


def source_note(fig, text: str, x: float = 0.01, y: float = 0.01, ha: str = "left",
                width: int = 118):
    """Add the standard italic, muted source note, wrapped to ``width`` characters.

    Figures are saved with ``bbox_inches="tight"``, so a single long note sets the saved
    width and leaves a band of empty space to the right of the axes. Wrapping keeps the
    note inside the plot's own width instead.

    Returns the ``Text`` artist, which :func:`layout_with_note` measures to reserve exactly
    the space the note occupies.
    """
    lines = textwrap.wrap(text, width=width) or [""]
    return fig.text(x, y, "\n".join(lines), ha=ha, va="bottom", fontsize=8, color=MUTED,
                    style="italic", linespacing=1.4)


def layout_with_note(fig, note=None, *, top: float = 1.0, pad: float = 0.018,
                     max_fraction: float = 0.45) -> float:
    """``tight_layout`` reserving the height the source note *actually* renders at.

    Every caller used to guess this from the note's line count with a hand-tuned constant.
    The guess is wrong whenever the note, the figure height or the font changes, and the
    failure is silent and ugly: the note grew past its allowance and the axis label was drawn
    straight through it. Measuring the rendered text removes the guess.

    Returns the reserved bottom fraction.
    """
    if note is None:
        fig.tight_layout(rect=(0, 0, 1, top))
        return 0.0
    # tight_layout only moves the axes; the note is figure-anchored, so its extent is stable
    # and can be measured before the layout pass.
    fig.canvas.draw()
    extent = note.get_window_extent(fig.canvas.get_renderer())
    bottom = min(max_fraction, extent.height / fig.bbox.height + pad)
    fig.tight_layout(rect=(0, bottom, 1, top))
    return bottom


def end_label(ax, x, y, text: str, color: str, *, fontsize: float = 10.5,
              pad: str = "  ") -> None:
    """Label a series at its end point, with a white halo for legibility.

    Direct end-of-line labels replace a legend box on single-series-per-party charts, so
    the eye maps colour to party without a lookup.
    """
    ax.text(x, y, f"{pad}{text}", fontsize=fontsize, fontweight="bold", color=color,
            va="center", ha="left", path_effects=white_stroke())

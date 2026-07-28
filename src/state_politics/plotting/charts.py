"""Reusable Substack-style chart helpers.

Small, composable helpers that apply the shared :mod:`state_politics.plotting.theme`
conventions (o-markers with a background-coloured edge, y-only grid, bold two-line titles,
borderless legend, italic source note, dpi=200) so every figure in the project looks
consistent with the rest of the portfolio with minimal boilerplate.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from . import theme

__all__ = [
    "dumbbell",
    "end_label",
    "finish",
    "line",
    "marker_line",
    "new_figure",
    "style_axes",
]


def new_figure(figsize: tuple[float, float] = (11, 6)):
    """Create a themed ``(fig, ax)``. Applies the theme first."""
    theme.apply()
    return plt.subplots(figsize=figsize)


def style_axes(ax, title: str, xlabel: str, ylabel: str, subtitle: str | None = None) -> None:
    """Apply the standard title/label/grid styling to an axis.

    Renders a two-tier header: a bold title with a muted sub-title beneath it, rather than
    a single newline-joined string.
    """
    ax.set_title(title, fontweight="bold", pad=28 if subtitle else 14)
    if subtitle:
        ax.text(0.5, 1.015, subtitle, transform=ax.transAxes, ha="center", va="bottom",
                fontsize=11, color=theme.MUTED)
    ax.set_xlabel(xlabel, labelpad=2)
    ax.set_ylabel(ylabel, labelpad=2)
    ax.grid(axis="y", linestyle="-", linewidth=0.5)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", pad=2)


def line(ax, xs, ys, color: str, label: str | None = None, linewidth: float = 2.2,
         markersize: float = 4, linestyle: str = "-", marker: str | None = "o") -> None:
    """Draw one Substack-style series. ``marker=None`` gives a clean, markerless line."""
    ax.plot(xs, ys, color=color, linewidth=linewidth, marker=marker, markersize=markersize,
            markeredgecolor=theme.BG, markeredgewidth=0.8, label=label, linestyle=linestyle)


def end_label(ax, x, y, text: str, color: str, **kwargs) -> None:
    """Label a series at its end point (delegates to :func:`theme.end_label`)."""
    theme.end_label(ax, x, y, text, color, **kwargs)


def marker_line(ax, x: float, color: str | None = None, style: str = ":") -> None:
    """Vertical reference marker (e.g. the 2017 end of the historical platform corpus)."""
    ax.axvline(x, color=color or theme.MUTED, linestyle=style, linewidth=0.9, alpha=0.7)


def dumbbell(ax, labels, left_values, right_values, *, left_color: str, right_color: str,
             left_label: str | None = None, right_label: str | None = None,
             connector_color: str | None = None, markersize: float = 7.0) -> None:
    """Horizontal dumbbell chart: two paired values per category.

    This is the project's signature comparison -- platform emphasis (what a state party
    says) against bill-sponsorship share (what its legislators file) for the same topic --
    so the gap between the two dots *is* the finding, and the connector is drawn muted so
    the dots carry the colour.
    """
    if not (len(labels) == len(left_values) == len(right_values)):
        raise ValueError("labels, left_values and right_values must be the same length")

    positions = range(len(labels))
    for pos, left, right in zip(positions, left_values, right_values, strict=True):
        ax.plot([left, right], [pos, pos], color=connector_color or theme.GRID,
                linewidth=2.0, zorder=1, solid_capstyle="round")
    ax.scatter(left_values, list(positions), color=left_color, s=markersize**2, zorder=2,
               edgecolor=theme.BG, linewidth=0.8, label=left_label)
    ax.scatter(right_values, list(positions), color=right_color, s=markersize**2, zorder=2,
               edgecolor=theme.BG, linewidth=0.8, label=right_label)
    ax.set_yticks(list(positions))
    ax.set_yticklabels(list(labels))
    ax.grid(axis="x", linestyle="-", linewidth=0.5)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)


def finish(fig, ax, out_path: Path | str, source: str | None = None,
           legend: bool = True, dpi: int = 200) -> Path:
    """Add legend + source note, tight-layout, and save. Returns the output path."""
    if legend and ax.get_legend_handles_labels()[0]:
        ax.legend(loc="best", frameon=False, labelcolor=theme.TEXT)
    note_lines = theme.source_note(fig, source) if source else 0
    # Reserve bottom margin for the italic source note, growing with its line count so a
    # wrapped two-line note is not overlapped by the x-axis label.
    bottom = 0.0 if not note_lines else min(0.18, 0.03 + 0.035 * (note_lines - 1))
    fig.tight_layout(rect=(0, bottom, 1, 1))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out_path

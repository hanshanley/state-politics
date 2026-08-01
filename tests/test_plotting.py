"""Tests for the shared plotting theme.

These pin the portfolio look: the palette and rcParams must stay byte-identical to
``congressional_record`` and ``pre1870_reapportionment_package`` so figures across the
portfolio remain visually consistent.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless: no display required

import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

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


def test_source_note_wraps_to_the_requested_width():
    fig = plt.figure()
    note = theme.source_note(fig, "word " * 100, width=40)
    rendered = note.get_text().split("\n")
    assert len(rendered) > 1
    assert max(len(line) for line in rendered) <= 40
    plt.close(fig)


def test_default_source_note_uses_more_width_on_wider_figures():
    narrow = plt.figure(figsize=(6, 4))
    wide = plt.figure(figsize=(13, 4))
    text = "source detail " * 100
    narrow_note = theme.source_note(narrow, text)
    wide_note = theme.source_note(wide, text)

    assert len(wide_note.get_text().split("\n")) < len(narrow_note.get_text().split("\n"))
    plt.close(narrow)
    plt.close(wide)


def test_layout_reserves_enough_room_for_a_long_source_note():
    """The axes must not be laid out on top of the note.

    Callers used to guess the reserve from the note's line count with a hand-tuned constant.
    When the note outgrew the guess the axis label was drawn straight through it, which is
    invisible to every test that only checks the file was written.
    """
    fig, ax = charts.new_figure(figsize=(11, 6))
    charts.line(ax, [2018, 2020], [0.1, 0.2], color=theme.PARTY_COLORS["D"])
    charts.style_axes(ax, "Title", "A deliberately long x-axis label", "Share")
    note = theme.source_note(fig, "source detail " * 60)
    theme.layout_with_note(fig, note)

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    note_top = note.get_window_extent(renderer).y1
    label_bottom = ax.xaxis.get_label().get_window_extent(renderer).y0
    plt.close(fig)

    assert label_bottom >= note_top, "x-axis label overlaps the source note"


def test_layout_reserve_grows_with_the_length_of_the_note():
    """A one-line note must not reserve the same band as a fifteen-line one."""
    reserves = []
    for repeats in (1, 60):
        fig, ax = charts.new_figure(figsize=(11, 6))
        charts.line(ax, [2018, 2020], [0.1, 0.2], color=theme.PARTY_COLORS["D"])
        note = theme.source_note(fig, "source detail " * repeats)
        reserves.append(theme.layout_with_note(fig, note))
        plt.close(fig)

    assert reserves[1] > reserves[0]


def test_subtitle_clears_top_tick_labels():
    """A chart that repeats its column headers above the axes must not overprint them."""
    fig, ax = charts.new_figure(figsize=(8, 10))
    ax.set_xticks([-1, 1])
    ax.set_xticklabels(["Democratic", "Republican"])
    ax.tick_params(axis="x", labeltop=True, labelbottom=True)
    charts.style_axes(ax, "Title", "", "", subtitle="A subtitle that must sit clear")

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    subtitle = next(child for child in ax.texts
                    if child.get_text() == "A subtitle that must sit clear")
    subtitle_bottom = subtitle.get_window_extent(renderer).y0
    header_top = max(tick.label2.get_window_extent(renderer).y1
                     for tick in ax.xaxis.get_major_ticks() if tick.label2.get_visible())
    plt.close(fig)

    assert subtitle_bottom >= header_top, "subtitle overlaps the top tick labels"


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


def test_dumbbell_can_use_shape_and_fill_instead_of_shading():
    fig, ax = charts.new_figure(figsize=(6, 4))
    charts.dumbbell(
        ax,
        ["Health"],
        [0.1],
        [0.2],
        left_color=theme.BLUE,
        right_color=theme.BLUE,
        left_marker="o",
        right_marker="s",
        left_filled=False,
        right_filled=True,
    )
    platform, bills = ax.collections[:2]
    assert platform.get_facecolors()[0][:3].tolist() == pytest.approx(
        matplotlib.colors.to_rgb(theme.BG)
    )
    assert bills.get_facecolors()[0][:3].tolist() == pytest.approx(
        matplotlib.colors.to_rgb(theme.BLUE)
    )
    assert platform.get_paths()[0].vertices.shape != bills.get_paths()[0].vertices.shape
    plt.close(fig)


def test_source_note_reserve_scales_with_figure_height(tmp_path):
    """A fixed figure-fraction reserve leaves a large empty band under tall panels.

    Asserted on the axes geometry rather than on file size: an earlier version of this test
    compared PNG byte counts, which passed identically with the reserve logic removed.
    """
    long_note = "word " * 120

    def bottom_fraction(figheight: float) -> float:
        fig, ax = charts.new_figure(figsize=(10, figheight))
        charts.line(ax, [1, 2], [1, 2], color=theme.BLUE)
        charts.finish(fig, ax, tmp_path / f"h{figheight}.png", source=long_note)
        return ax.get_position().y0

    short, tall = bottom_fraction(6), bottom_fraction(13)
    # The note occupies a fixed physical height, so as a fraction of a taller figure the
    # reserved band must shrink.
    assert tall < short
    # And in absolute inches the two reserves should be close, not proportional to height.
    assert abs(tall * 13 - short * 6) < 0.75


def test_stated_vs_revealed_panels_share_one_row_order():
    """Both panels must plot topics in the same order.

    The right panel's tick labels are hidden, so a reader reads its dots against the *left*
    panel's labels. Sorting each party independently silently mislabelled 15 of 21 Republican
    rows -- the Republican government-operations gap was displayed against the label
    "Agriculture".
    """
    import sys
    from pathlib import Path

    import pandas as pd

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import plot_stated_vs_revealed as script

    # Deliberately opposite orderings: sorting each party on its own key reverses the rows.
    topics = ["Health", "Housing", "Immigration", "Labor"]
    rows = []
    for party, gaps in (("D", [0.03, -0.04, 0.01, -0.02]), ("R", [-0.04, 0.03, -0.02, 0.01])):
        for code, (topic, gap) in enumerate(zip(topics, gaps, strict=True), start=1):
            rows.append({"topic": code, "topic_name": topic, "party": party,
                         "stated_share": 0.1, "revealed_share": 0.1 - gap,
                         "stated_minus_revealed": gap})
    table = pd.DataFrame(rows)

    out = script.build_figure(table, root / "outputs" / "_test_stated_vs_revealed.png")
    figure = plt.gcf()
    panels = figure.get_axes()[:2]

    # Recover which topic each plotted row is, by matching its (stated, revealed) pair back to
    # the source table. Tick labels cannot be used: the right panel's are deliberately hidden.
    plotted = []
    for ax, party in zip(panels, ("D", "R"), strict=True):
        stated, revealed = (c.get_offsets() for c in ax.collections[:2])
        lookup = {(round(r.stated_share * 100, 6), round(r.revealed_share * 100, 6)):
                  r.topic_name for r in table[table["party"] == party].itertuples()}
        plotted.append([lookup[(round(float(s[0]), 6), round(float(v[0]), 6))]
                        for s, v in zip(stated, revealed, strict=True)])
    plt.close("all")
    out.unlink(missing_ok=True)

    assert plotted[0] == plotted[1], (
        f"panels plot different topics per row: {plotted[0]} vs {plotted[1]}"
    )


def test_stated_vs_revealed_flags_rows_an_independent_labelling_contradicts():
    """A withdrawn claim must be visibly withdrawn in the figure, not silently dropped.

    The housing gap survived the model but not the subject-tag replication. Removing the row
    would leave the figure disagreeing with the prose with no hint why, so it is daggered.
    """
    import sys
    from pathlib import Path

    import pandas as pd

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import plot_stated_vs_revealed as script

    # Housing: model says filed > said, tags say filed < said -> the gap does not replicate.
    table = pd.DataFrame([
        {"topic": 14, "topic_name": "Housing", "party": "D", "stated_share": 0.035,
         "revealed_share": 0.094, "stated_minus_revealed": -0.059},
        {"topic": 12, "topic_name": "Law", "party": "D", "stated_share": 0.089,
         "revealed_share": 0.138, "stated_minus_revealed": -0.049},
    ])
    tags = pd.DataFrame([
        {"topic": 14, "party": "D", "holds": False},
        {"topic": 12, "party": "D", "holds": True},
    ])

    processed = root / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    path = processed / "headline_tag_replication.csv"
    preserved = path.read_bytes() if path.exists() else None
    try:
        tags.to_csv(path, index=False)
        flagged = script.unreliable_topics(root, table)
    finally:
        if preserved is not None:
            path.write_bytes(preserved)
        else:
            path.unlink(missing_ok=True)

    assert (14, "D") in flagged, "housing gap does not replicate and must be flagged"
    assert (12, "D") not in flagged, "law-and-crime gap replicates and must not be flagged"


def test_stated_vs_revealed_panels_have_equal_row_counts():
    """Sharing a row order is not enough; the panels must have the same number of rows.

    The panels share one set of tick labels, so a topic present for one party and absent for
    the other would give them different y-limits and slide the right panel's dots off the
    labels they are read against.
    """
    import sys
    from pathlib import Path

    import pandas as pd

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import plot_stated_vs_revealed as script

    # Deliberately ragged: "Housing" exists only for the Democrats.
    table = pd.DataFrame([
        {"topic": 12, "topic_name": "Law", "party": "D", "stated_share": 0.09,
         "revealed_share": 0.14, "stated_minus_revealed": -0.05},
        {"topic": 14, "topic_name": "Housing", "party": "D", "stated_share": 0.04,
         "revealed_share": 0.09, "stated_minus_revealed": -0.05},
        {"topic": 12, "topic_name": "Law", "party": "R", "stated_share": 0.10,
         "revealed_share": 0.15, "stated_minus_revealed": -0.05},
    ])
    out = script.build_figure(table, root / "outputs" / "_test_row_counts.png")
    figure = plt.gcf()
    left, right = figure.get_axes()[:2]
    counts = (len(left.get_yticks()), len(right.get_yticks()))
    limits = (left.get_ylim(), right.get_ylim())
    plt.close("all")
    out.unlink(missing_ok=True)

    assert counts[0] == counts[1], f"panels have {counts[0]} and {counts[1]} rows"
    assert limits[0] == limits[1], "panels must share y-limits to share tick labels"

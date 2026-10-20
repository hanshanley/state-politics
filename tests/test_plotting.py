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


@pytest.mark.parametrize("case", ["available", "empty", "unavailable"])
def test_trend_chart_discloses_actual_samples_and_unavailable_results(
    tmp_path, monkeypatch, case,
):
    from pathlib import Path

    import pandas as pd

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import plot_bill_trends as script

    frame = pd.DataFrame([{
        "party": "D", "topic_name": "Education", "q_value_model": 0.01,
        "direction_replicates_with_tags": True, "change_model": 0.1,
        "early_share_model": 0.2, "late_share_model": 0.3,
        "paired_state_count_model": 8, "paired_state_count_tags": 3,
    }])
    if case == "empty":
        frame = frame.iloc[:0]
    elif case == "unavailable":
        frame["direction_replicates_with_tags"] = pd.Series([pd.NA], dtype="boolean")
        frame["paired_state_count_tags"] = float("nan")
    out = tmp_path / "trends.png"
    script.build_figure(frame, out)
    fig = plt.gcf()
    text = " ".join(item.get_text() for item in fig.texts)
    assert out.is_file()
    assert "2026-07" not in text and "legislative-staff" not in text
    assert "ten states" not in text and "not been revalidated" in text
    if case != "available":
        assert any("available" in item.get_text() for item in fig.axes[0].texts)
    else:
        labels = " ".join(item.get_text() for item in fig.axes[0].get_yticklabels())
        assert "model n=8" in labels and "tags n=3" in labels
    plt.close(fig)


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


def test_figure_report_preserves_undefined_intraparty_ratio(tmp_path, monkeypatch, capsys):
    from pathlib import Path

    import pandas as pd

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import report_figures as script

    pd.DataFrame([{
        "mean_within": 0.0, "between": 0.0, "within_over_between": None, "n_states": 2,
    }]).to_csv(tmp_path / "intraparty_platform_coherence.csv", index=False)
    pd.DataFrame([{
        "stream": "platform", "observed_gap": None, "p_value": None, "n_permutations": 4,
    }]).to_csv(tmp_path / "intraparty_dispersion_tests.csv", index=False)
    monkeypatch.setattr(script, "ROOT", tmp_path)
    monkeypatch.setattr(script, "DATA", tmp_path)
    assert script.main() == 0
    text = capsys.readouterr().out
    assert "within 0.000" in text and "between 0.000" in text
    assert "ratio unavailable" in text
    assert "ratio nan" not in text
    assert "dispersion gap unavailable" in text
    assert "not distinguishable from chance" not in text


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


def test_stated_vs_revealed_leaves_unavailable_shares_unplotted(tmp_path):
    import sys
    from pathlib import Path

    import pandas as pd

    from state_politics.analysis.revealed import divergence_table

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import plot_stated_vs_revealed as script

    platform = pd.DataFrame({
        "topic": [5, 6], "topic_name": ["Labor", "Education"],
        "D": [0.6, 0.4], "R": [0.7, 0.3],
    })
    bills = pd.DataFrame({
        "topic": [5, 6], "party": ["D", "D"], "share": [0.8, 0.2], "n_bills": [8, 2],
    })
    try:
        script.build_figure(divergence_table(platform, bills), tmp_path / "comparison.png")
        panels = plt.gcf().get_axes()[:2]
        assert panels[0].collections[1].get_offsets()[:, 0].count() == 2
        assert panels[1].collections[0].get_offsets()[:, 0].count() == 2
        assert panels[1].collections[1].get_offsets()[:, 0].count() == 0
    finally:
        plt.close("all")


def test_stated_vs_revealed_flags_rows_an_independent_labelling_contradicts(tmp_path):
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
        {"topic": 18, "party": "R", "holds": False},
        {"topic": 6, "party": "R", "holds": None},
    ])

    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    path = processed / "headline_tag_replication.csv"
    tags.to_csv(path, index=False)
    flagged = script.unreliable_topics(tmp_path, table)

    assert (14, "D") in flagged, "housing gap does not replicate and must be flagged"
    assert (12, "D") not in flagged, "law-and-crime gap replicates and must not be flagged"
    assert (18, "R") not in flagged, "unmapped tag topics cannot be replication failures"
    assert (6, "R") not in flagged, "missing comparisons cannot be replication failures"


@pytest.mark.parametrize("all_missing", [False, True])
def test_figure_report_excludes_unknown_replication_verdicts(
    tmp_path, monkeypatch, capsys, all_missing,
):
    import sys
    from pathlib import Path

    import pandas as pd

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import report_figures as script

    comparison = pd.DataFrame({
        "topic_name": ["Labor", "Education", "Law"], "party": ["D", "D", "R"],
        "stated_share": [0.5, 0.3, None], "model_share": [0.6, 0.2, None],
        "tag_share": [0.7, 0.4, None],
        "holds": [None] * 3 if all_missing else [True, False, None],
    })
    comparison.to_csv(tmp_path / "headline_tag_replication.csv", index=False)
    monkeypatch.setattr(script, "ROOT", tmp_path)
    monkeypatch.setattr(script, "DATA", tmp_path)
    assert script.main() == 0
    output = capsys.readouterr().out
    if all_missing:
        assert "headline rows replicated unavailable" in output
        assert "headline rows unavailable 3/3" in output
        assert "does not hold" not in output
    else:
        assert "1/2 available rows" in output
        assert "headline rows unavailable 1/3" in output
        assert output.count("does not hold") == 1
        assert "Law" not in output


@pytest.mark.parametrize("paired", [False, True])
@pytest.mark.parametrize("source_counts_available", [False, True])
def test_figure_report_handles_unavailable_outcome_evidence(
    tmp_path, monkeypatch, capsys, paired, source_counts_available,
):
    import json
    from pathlib import Path

    import pandas as pd

    from state_politics.analysis.outcomes import build_outcome_tables

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import report_figures as script

    bills = pd.DataFrame([
        {
            "bill_id": f"{party}-{index}", "state": "TX", "sponsor_party": party,
            "year": 2024, "classification": "bill", "n_actions": 1,
            "recorded_outcome": "introduced_or_pending", "recorded_enacted": False,
            "n_vote_events": 0, "originating_chamber": "lower",
        }
        for party in ("D", "R")
        for index in range(500 if paired else 1)
    ])
    _, outcomes, _, comparison = build_outcome_tables(bills)
    outcomes.to_csv(tmp_path / "bill_outcomes_by_party.csv", index=False)
    (tmp_path / "bill_outcome_comparison.json").write_text(json.dumps(comparison))
    if source_counts_available:
        bills[["bill_id"]].to_parquet(tmp_path / "bill_actions.parquet", index=False)
        pd.DataFrame(columns=["vote_id"]).to_parquet(
            tmp_path / "vote_events.parquet", index=False,
        )
    monkeypatch.setattr(script, "ROOT", tmp_path)
    monkeypatch.setattr(script, "DATA", tmp_path)

    assert script.main() == 0
    output = capsys.readouterr().out
    if source_counts_available:
        assert f"explicit actions     {len(bills):,}" in output
        assert "vote events          0" in output
    else:
        assert "explicit actions     unavailable" in output
        assert "vote events          unavailable" in output
    if paired:
        assert "D-R enactment gap    +0.0%, p=1.000 (1 paired states)" in output
    else:
        assert "D-R enactment gap    unavailable (0 paired states)" in output
        assert "p=1.000" not in output


def test_figure_report_does_not_claim_verified_human_gold(tmp_path, monkeypatch, capsys):
    from pathlib import Path

    import pandas as pd

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import report_figures as script

    pd.DataFrame({
        "embedding_topic": [1, 2, 3], "gold_topic": [1, 3, 2],
        "keyword_topic": [1, 2, 3],
    }).to_csv(tmp_path / "plank_classifier_scores.csv", index=False)
    monkeypatch.setattr(script, "ROOT", tmp_path)
    monkeypatch.setattr(script, "DATA", tmp_path)

    assert script.main() == 0
    output = capsys.readouterr().out
    assert "supplied labels; reviewer provenance unresolved" in output
    assert "hand-labelled gold" not in output
    assert "embedding top-1      1/3 (33%)" in output
    assert "keyword top-1        1/3 (33%)" in output


@pytest.mark.parametrize("paired", [False, True])
def test_outcome_chart_uses_actual_paired_coverage_and_full_rate_range(
    tmp_path, monkeypatch, paired,
):
    from pathlib import Path

    import pandas as pd

    from state_politics.analysis.outcomes import build_outcome_tables

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import plot_outcomes as script

    bills = pd.DataFrame([
        {
            "bill_id": f"{party}-{index}", "state": "TX", "sponsor_party": party,
            "year": 2024, "classification": "bill", "n_actions": 1,
            "recorded_outcome": "signed", "recorded_enacted": True,
            "n_vote_events": 0, "originating_chamber": "lower",
        }
        for party in ("D", "R")
        for index in range(500 if paired else 1)
    ])
    _, outcomes, _, comparison = build_outcome_tables(bills)
    path = tmp_path / "outcomes.csv"
    outcomes.to_csv(path, index=False)
    captured = {}
    original_finish = script.charts.finish

    def finish(fig, ax, out_path, **kwargs):
        captured.update(fig=fig, ax=ax, source=kwargs["source"])
        return original_finish(fig, ax, out_path, **kwargs)

    monkeypatch.setattr(script.charts, "finish", finish)
    output = tmp_path / "stages.png"
    assert script.build_outcome_figure(pd.read_csv(path), comparison, output) == output
    assert output.stat().st_size > 0
    text = " ".join(
        label.get_text() for label in captured["fig"].findobj() if hasattr(label, "get_text")
    )
    assert "41 states" not in text
    assert "2026-07" not in captured["source"]
    if paired:
        assert "Paired states: 1" in text
        assert captured["ax"].get_xlim()[1] >= 100
        assert [bar.get_width() for bar in captured["ax"].patches] == [100] * 4
    else:
        assert "unavailable" in text.lower()
        assert "paired p" not in text
        assert not captured["ax"].patches


@pytest.mark.parametrize("available_pairs,yes_votes", [(0, 10), (2, 10), (4, 10), (4, 0)])
def test_rollcall_chart_preserves_unavailable_cells_and_cell_coverage(
    tmp_path, monkeypatch, available_pairs, yes_votes,
):
    from pathlib import Path

    import pandas as pd

    from state_politics.analysis.outcomes import party_rollcall_support

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import plot_outcomes as script

    pairs = [("D", "D"), ("D", "R"), ("R", "D"), ("R", "R")]
    events = pd.DataFrame([
        {
            "vote_id": f"vote-{index}", "bill_id": f"bill-{index}", "state": "TX",
            "result": "pass", "chamber": "lower", "motion_classification": "passage",
        }
        for index in range(4)
    ])
    counts = pd.DataFrame([
        {
            "vote_event_id": f"vote-{index}", "bill_id": f"bill-{index}", "state": "TX",
            "sponsor_party": sponsor, "voter_party": voter, "option": option,
            "n_votes": yes_votes if option == "yes" else 20 - yes_votes,
        }
        for index, (sponsor, voter) in enumerate(pairs[:available_pairs])
        for option in ("yes", "no")
    ], columns=[
        "vote_event_id", "bill_id", "state", "sponsor_party", "voter_party", "option", "n_votes",
    ])
    summary = party_rollcall_support(events, counts)
    path = tmp_path / "rollcalls.csv"
    summary.to_csv(path, index=False)
    captured = {}
    original_new_figure = script.charts.new_figure

    def new_figure(**kwargs):
        fig, ax = original_new_figure(**kwargs)
        captured.update(fig=fig, ax=ax)
        return fig, ax

    monkeypatch.setattr(script.charts, "new_figure", new_figure)
    output = tmp_path / "votes.png"
    assert script.build_rollcall_figure(pd.read_csv(path), output) == output
    assert output.stat().st_size > 0
    labels = [label.get_text() for label in captured["ax"].texts]
    assert sum(label == "Unavailable" for label in labels) == 4 - available_pairs
    assert sum(label == f"{yes_votes * 5:.1f}%" for label in labels) == available_pairs
    assert captured["ax"].images[0].get_clim() == (0, 100)
    text = " ".join(
        label.get_text() for label in captured["fig"].findobj() if hasattr(label, "get_text")
    )
    assert "same 40 states" not in text
    assert "2026-07" not in text
    if available_pairs:
        assert any("1 state" in label and "1 roll call" in label for label in labels)
    import matplotlib.pyplot as plt

    plt.close(captured["fig"])


@pytest.mark.parametrize("n_paired", [0, 2])
def test_outcome_chart_rejects_conflicting_coverage(tmp_path, monkeypatch, n_paired):
    from pathlib import Path

    import pandas as pd

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import plot_outcomes as script

    outcomes = pd.DataFrame([
        {
            "party": party, "n_states": 1,
            "mean_advancement_rate": 0.5, "mean_enactment_rate": 0.25,
        }
        for party in ("D", "R")
    ])
    comparison = {
        "n_paired_states": n_paired,
        "mean_d_minus_r_enactment_rate": 0,
        "sign_flip_p_value": 1,
    }
    with pytest.raises(ValueError, match="paired-state count"):
        script.build_outcome_figure(outcomes, comparison, tmp_path / "invalid.png")
    assert not (tmp_path / "invalid.png").exists()


def test_all_state_focus_matrix_has_every_state_and_explicit_nebraska_gap():
    import sys
    from pathlib import Path

    import pandas as pd

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import plot_all_state_focus as script

    emphasis = pd.DataFrame(
        [
            {
                "state": "TX", "party": "D", "topic_name": "Health",
                "share": 0.6,
            },
            {
                "state": "TX", "party": "D", "topic_name": "Education",
                "share": 0.4,
            },
            {
                "state": "TX", "party": "R", "topic_name": "Education",
                "share": 1.0,
            },
        ]
    )

    matrix, topics = script.focus_matrix(emphasis, "D")

    assert len(matrix) == 50
    assert matrix.loc["NE"].isna().all()
    assert matrix.loc["TX", "Health"] == 0.6
    assert set(topics) == {"Health", "Education"}


def test_election_focus_axis_ignores_unreliable_outlier(tmp_path):
    import sys
    from pathlib import Path

    import pandas as pd

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import plot_election_focus as script

    focus = pd.DataFrame(
        [
            {
                "state": "TX", "party": "D", "focus_reliable": True,
                "overemphasis": 0.04, "top_subtype": "voting_and_administration",
                "election_share": 0.08, "peer_share": 0.04,
            },
            {
                "state": "FL", "party": "R", "focus_reliable": True,
                "overemphasis": 0.03, "top_subtype": "voting_and_administration",
                "election_share": 0.07, "peer_share": 0.04,
            },
            {
                "state": "ID", "party": "D", "focus_reliable": False,
                "overemphasis": 0.20, "top_subtype": "voting_and_administration",
                "election_share": 0.24, "peer_share": 0.04,
            },
        ]
    )
    out = script.build_figure(
        focus,
        {"precision": 0.9, "recall": 0.8},
        tmp_path / "elections.png",
        top_n=10,
    )
    figure = plt.gcf()
    assert figure.get_axes()[0].get_xlim()[1] < 10
    plt.close("all")
    assert out.exists()


def test_election_focus_plot_preserves_negative_comparisons(tmp_path):
    import sys
    from pathlib import Path

    import pandas as pd

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import plot_election_focus as script

    focus = pd.DataFrame([{
        "state": "TX", "party": "D", "focus_reliable": True,
        "overemphasis": -0.02, "top_subtype": "voting_and_administration",
        "election_share": 0.02, "peer_share": 0.04,
    }])
    script.build_figure(focus, {"precision": 0.0, "recall": 0.0}, tmp_path / "negative.png")
    figure = plt.gcf()
    try:
        assert figure.axes[0].get_xlim()[0] < -2
        assert any("unavailable" in text.get_text().lower() for text in figure.axes[1].texts)
    finally:
        plt.close(figure)


def test_empty_election_exports_render_as_unavailable(tmp_path):
    import sys
    from pathlib import Path

    import pandas as pd

    from state_politics.analysis.elections import election_focus

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import plot_election_focus as script

    focus, _, validation = election_focus(pd.DataFrame({
        "state": [], "sponsor_party": [], "title": [], "subject": [],
    }))
    focus.to_csv(tmp_path / "focus.csv", index=False)
    restored = pd.read_csv(tmp_path / "focus.csv")
    script.build_figure(restored, validation, tmp_path / "empty.png")
    figure = plt.gcf()
    try:
        assert all(
            any("unavailable" in text.get_text().lower() for text in ax.texts)
            for ax in figure.axes
        )
        note = " ".join(text.get_text() for text in figure.texts).lower()
        assert "unavailable" in note and "nan" not in note
        assert "2026-07" not in note and "legislature-assigned" not in note
    finally:
        plt.close(figure)


@pytest.mark.parametrize("population", ["empty", "single_party", "below_floor"])
def test_election_report_handles_missing_metrics_and_rankings(
    tmp_path, monkeypatch, capsys, population,
):
    import json
    import sys
    from pathlib import Path

    import pandas as pd

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import report_figures as script

    rows = [] if population == "empty" else [{
        "state": "TX", "party": "D", "n_election_bills": 0, "n_bills": 500,
        "election_share": 0.0, "peer_share": 0.1, "overemphasis": -0.1,
        "focus_reliable": population == "single_party",
    }]
    pd.DataFrame(rows, columns=[
        "state", "party", "n_election_bills", "n_bills", "election_share",
        "peer_share", "overemphasis", "focus_reliable",
    ]).to_csv(tmp_path / "election_focus_by_state_party.csv", index=False)
    (tmp_path / "election_title_validation.json").write_text(
        json.dumps({"precision": None, "recall": 0.0}),
    )
    monkeypatch.setattr(script, "DATA", tmp_path)
    monkeypatch.setattr(script, "ROOT", tmp_path)

    assert script.main() == 0
    output = capsys.readouterr().out.lower()
    assert "unavailable" in output and "nan" not in output
    assert "0.0%" in output
    if population != "empty":
        assert "0.00%" in output


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


def test_platform_gap_plot_distinguishes_unresolved_retrievals(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    import pandas as pd

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import plot_platform_gap as script

    statuses = [
        "fetch_failed", "candidates_partially_unresolved", "candidates_rejected",
        "candidates_unfetched", "no_strong_candidates", "no_candidates",
    ]
    report = pd.DataFrame([
        {"state": f"S{index}", "party": "D", "status": status,
         "latest_year": None, "doc_types": ""}
        for index, status in enumerate(statuses)
    ])
    figures = []
    finish = script.charts.finish

    def capture_figure(figure, *args, **kwargs):
        figures.append(figure)
        return finish(figure, *args, **kwargs)

    monkeypatch.setattr(script.charts, "finish", capture_figure)
    try:
        output = script.build_figure(report, tmp_path / "gaps.png")
        ax = figures[-1].get_axes()[0]
        marker_paths = [
            collection.get_paths()[0].vertices.tobytes() for collection in ax.collections
        ]
        assert len(set(marker_paths)) == len(report)
        assert output.exists()
        with pytest.raises(ValueError, match="unsupported collection statuses"):
            script.build_figure(report.assign(status="unknown"), tmp_path / "unknown.png")
    finally:
        plt.close("all")

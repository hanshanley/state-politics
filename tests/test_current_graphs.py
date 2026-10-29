"""Current charts preserve source bindings, complete data and dual-background geometry."""

import hashlib
import json
import re
import runpy
from pathlib import Path
from xml.etree import ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from PIL import Image  # noqa: E402

MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/render_current_graphs.py")
)


@pytest.mark.parametrize("defect", [None, "table", "manifest", "publication"])
def test_current_tables_require_pinned_manifest_and_exact_original_bytes(tmp_path, defect):
    group = "majority"
    directory = tmp_path / "outputs/saved"
    (directory / "chart-data").mkdir(parents=True)
    path = directory / "chart-data/status_comparison.csv"
    pd.DataFrame(
        [
            {"status": "classified", "baseline_contexts": 65091, "candidate_contexts": 78300},
            {"status": "unassigned", "baseline_contexts": 92507, "candidate_contexts": 79298},
        ]
    ).to_csv(path, index=False)
    manifest = {
        "publication": defect == "publication",
        "artifacts": {"chart-data/status_comparison.csv": MODULE["binding"](path)},
    }
    anchor = directory / "manifest.json"
    anchor.write_text(json.dumps(manifest))
    pin = MODULE["binding"](anchor)["sha256"]
    namespace = MODULE["load_tables"].__globals__
    before = namespace["SOURCES"], namespace["TABLES"]
    namespace["SOURCES"], namespace["TABLES"] = (
        {group: ("saved", pin)},
        {
            group: ("status_comparison",),
        },
    )
    if defect == "table":
        path.write_text(path.read_text().replace("65091", "65090"))
    elif defect == "manifest":
        anchor.write_text(anchor.read_text() + "\n")
    try:
        if defect:
            with pytest.raises(ValueError, match="changed|unapproved"):
                MODULE["load_tables"](tmp_path)
        else:
            tables, bindings, _ = MODULE["load_tables"](tmp_path)
            assert tables[group, "status_comparison"]["candidate_contexts"].sum() == 157598
            assert len(bindings) == 2
    finally:
        namespace["SOURCES"], namespace["TABLES"] = before


def test_actual_dual_exports_preserve_marks_labels_and_geometry(tmp_path):
    fig, (ax,) = MODULE["axes"](height=4.5)
    MODULE["bars"](ax, ["A complete category", "Other evidence"], [65091, 18281])
    spec = dict(
        group="topics",
        name="counts",
        fig=fig,
        title="Actual retained evidence",
        subtitle="Missing text is not zero activity",
        note="Source: complete original records. No model or human validation is invented.",
        tables=["chart-data/complete.csv"],
    )
    result = MODULE["save_figure"](spec, tmp_path)
    assert len(result["files"]) == 4
    left, bottom, width, height = result["axes_geometry"][0]
    assert width > 0.6 and height > 0.5
    assert left < 0.35 and bottom < 0.3
    texts, dimensions = [], []
    for name, expected in MODULE["BACKGROUNDS"].items():
        directory = tmp_path / name / "topics"
        with Image.open(directory / "counts.png") as image:
            assert image.size[0] >= 3000
            assert image.convert("RGB").getpixel((0, 0)) == tuple(
                bytes.fromhex(expected.lstrip("#"))
            )
            dimensions.append(image.size)
        svg = ET.parse(directory / "counts.svg").getroot()
        text = [node.text for node in svg.iter() if node.tag.endswith("}text")]
        assert "Actual retained evidence" in text
        assert "65,091" in text and "18,281" in text
        assert "A complete category" in text
        texts.append(text)
        assert expected.lower() in (directory / "counts.svg").read_text().lower()
    assert texts[0] == texts[1] and dimensions[0] == dimensions[1]
    assert not plt.fignum_exists(fig.number)


def test_empty_state_coverage_is_not_invented_zero_activity():
    fig, (ax,) = MODULE["axes"]()
    frame = pd.DataFrame({"assigned": [0, 3], "missing": [0, 2]})
    MODULE["stacked"](
        ax, ["CT", "AK"], frame, [("assigned", "Assigned"), ("missing", "Missing")], percent=True
    )
    assert any(text.get_text() == "no candidates supplied" for text in ax.texts)
    assert ax.containers[0].datavalues.tolist() == [0, 60]
    assert ax.containers[1].datavalues.tolist() == [0, 40]
    plt.close(fig)


@pytest.mark.parametrize("check", ["row_alignment", "count_labels"])
def test_bill_evidence_panels_align_states_and_distinguish_zero_from_unknown(check):
    root = Path(__file__).resolve().parents[1]
    tables = {
        (group, name): pd.read_csv(root / "outputs/chart-data" / group / f"{name}.csv")
        for group, names in MODULE["TABLES"].items()
        for name in names
    }
    frame = tables["evidence", "bill_evidence_by_state"].iloc[:5].copy()
    frame["state"] = ["AK", "AL", "MA", "ME", "WY"]
    columns = [
        "n_cycle_evidence_candidate_contexts",
        "n_cycle_contexts_with_nonempty_abstract",
        "n_cycle_contexts_with_indexed_native_text",
    ]
    frame[columns[0]] = [10000, 5000, 1, 0, 10]
    frame[columns[1]] = [500, 0, 1, 0, 0]
    frame[columns[2]] = [float("nan"), 2, 1, 0, float("nan")]
    tables["evidence", "bill_evidence_by_state"] = frame
    specifications = MODULE["specifications"](tables)
    try:
        for spec in specifications:
            if spec["name"] == "bill_evidence_by_state":
                break
            plt.close(spec["fig"])
        axs = spec["fig"].axes
        canvas = FigureCanvasAgg(spec["fig"])
        canvas.draw()
        if check == "row_alignment":
            positions = [
                [ax.transData.transform((0, row))[1] for row in range(len(frame))]
                for ax in axs
            ]
            assert positions[0] == pytest.approx(positions[1])
            assert positions[0] == pytest.approx(positions[2])
        else:
            for ax, column in zip(axs, columns, strict=True):
                expected = [
                    "not supplied" if pd.isna(value) else f"{value:,.0f}"
                    for value in frame[column]
                ]
                assert [text.get_text() for text in ax.texts] == expected
                assert [bar.get_width() for bar in ax.patches] == pytest.approx(
                    frame[column].tolist(), nan_ok=True,
                )
                assert all(
                    text.get_window_extent(canvas.get_renderer()).x1 <= ax.bbox.x1
                    for text in ax.texts
                )
    finally:
        specifications.close()
        plt.close("all")


def test_paired_topic_counts_keep_small_and_zero_values_readable(tmp_path):
    tables = {
        ("majority", "status_comparison"): pd.DataFrame(
            dict(
                status=["classified", "uncertain", "unavailable"],
                baseline_contexts=[12002, 145596, 0],
                candidate_contexts=[15007, 142591, 0],
            )
        ),
        ("majority", "topic_comparison"): pd.DataFrame(
            dict(
                label=["Large topic", "Small topic", "Zero topic"],
                baseline_contexts=[12000, 2, 0],
                candidate_contexts=[15000, 7, 0],
            )
        ),
    }
    specifications = MODULE["specifications"](tables)
    spec = next(specifications)
    specifications.close()
    chart, counts = spec["fig"].axes
    assert [bar.get_width() for bar in chart.patches] == [12000, 2, 0, 15000, 7, 0]
    assert counts.get_ylim() == chart.get_ylim()
    assert [text.get_text() for text in counts.texts] == [
        "Unanimity", "12,000", "2", "0", "Majority", "15,000", "7", "0",
    ]
    assert [text.get_position()[1] for text in counts.texts[1:4]] == [0, 1, 2]
    assert [text.get_position()[1] for text in counts.texts[5:8]] == [0, 1, 2]
    result = MODULE["save_figure"](spec, tmp_path)
    canvas = FigureCanvasAgg(spec["fig"])
    canvas.draw()
    renderer = canvas.get_renderer()
    extents = [text.get_window_extent(renderer) for text in counts.texts]
    assert all(
        not left.overlaps(right)
        for index, left in enumerate(extents)
        for right in extents[index + 1:]
    )
    for background in MODULE["BACKGROUNDS"]:
        path = tmp_path / background / "majority/topic_comparison.svg"
        svg = ET.parse(path).getroot()
        text = [node.text for node in svg.iter() if node.tag.endswith("}text")]
        assert all(
            value in text for value in ("Unanimity", "Majority", "12,000", "15,000", "2", "7")
        )
    assert len(result["files"]) == 4


def test_state_partitions_preserve_dataframe_identity_and_every_row():
    frame = pd.DataFrame({"state": ["AK", "AL", "AR", "AZ", "CA"], "count": range(5)})
    parts = MODULE["parts"](frame, 2)
    assert all(isinstance(part, pd.DataFrame) for part in parts)
    assert pd.concat(parts).equals(frame)


def test_current_builder_refuses_overwrite_before_loading_sources(tmp_path):
    output = tmp_path / "outputs"
    (output / "substack").mkdir(parents=True)
    marker = output / "substack/original.txt"
    marker.write_bytes(b"preserved original")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        MODULE["build"](output, tmp_path)
    assert (
        hashlib.sha256(marker.read_bytes()).digest()
        == hashlib.sha256(b"preserved original").digest()
    )


def test_current_population_captions_follow_actual_source_tables():
    tables = {
        ("majority", "status_comparison"): pd.DataFrame(
            [
                dict(status="classified", label="Assigned", baseline_contexts=4,
                     candidate_contexts=6),
                dict(status="uncertain", label="Uncertain", baseline_contexts=3,
                     candidate_contexts=1),
                dict(status="unavailable", label="No text", baseline_contexts=3,
                     candidate_contexts=3),
            ]
        ),
        ("majority", "topic_comparison"): pd.DataFrame(
            [dict(label="One topic", baseline_contexts=4, candidate_contexts=6)]
        ),
    }
    counts = MODULE["population_counts"](tables)
    assert counts["original_abstained"] == 3
    assert counts["available_retained_text"] == 7
    assert counts["majority_additional_assignments"] == 2
    specifications = MODULE["specifications"](tables)
    first, second = next(specifications), next(specifications)
    try:
        assert "Same 10 contexts" in first["subtitle"]
        assert "All 4 original-rule assignments" in first["note"]
        assert "2 additional topic assignments" in second["subtitle"]
        assert "all 3 unanimity abstentions" in second["note"]
        assert "10" in second["fig"].axes[0].get_xlabel()
    finally:
        specifications.close()
        plt.close(first["fig"])
        plt.close(second["fig"])


@pytest.mark.parametrize("candidate", [[7, 1, 2], [3, 4, 3]])
def test_current_population_refuses_changed_missingness_or_lost_baseline_topics(candidate):
    table = pd.DataFrame(
        dict(status=["classified", "uncertain", "unavailable"],
             baseline_contexts=[4, 3, 3], candidate_contexts=candidate)
    )
    with pytest.raises(ValueError, match="preserve missing inputs and baseline assignments"):
        MODULE["population_counts"]({("majority", "status_comparison"): table})


def test_every_chart_family_preserves_population_counts_after_state_status_plot():
    root = Path(__file__).resolve().parents[1]
    tables = {
        (group, name): pd.read_csv(root / "outputs/chart-data" / group / f"{name}.csv")
        for group, names in MODULE["TABLES"].items()
        for name in names
    }
    population = MODULE["population_counts"](tables)
    try:
        with plt.rc_context({"figure.max_open_warning": 0}):
            figures = list(MODULE["specifications"](tables))
        assert len(figures) == 27
        coverage = next(f for f in figures if f["name"] == "retained_snapshot_text_coverage")
        assert (
            f"{population['available_retained_text']:,} of "
            f"{population['original_candidate_contexts']:,} contexts have text"
        ) in coverage["note"]
        frame = tables["evidence", "retained_text_coverage"]
        assert (
            f"{len(frame)} states accounted for; "
            f"{frame.candidate_contexts.gt(0).sum()} with cohort contexts"
        ) in coverage["subtitle"]
        expected = {
            row.state: "No cohort contexts" if row.candidate_contexts == 0
            else f"{row.candidate_contexts:,}"
            for row in frame.itertuples()
        }
        for ax in coverage["fig"].axes:
            states = [label.get_text() for label in ax.get_yticklabels()]
            assert [text.get_text() for text in ax.texts] == [expected[state] for state in states]
            assert ax.get_xlabel() == "Candidate contexts"
    finally:
        plt.close("all")


@pytest.mark.parametrize("relative", ["outputs", "outputs/current-render-REPLAY"])
def test_gallery_evidence_and_method_links_resolve_from_actual_output_directory(
    tmp_path,
    relative,
):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/AUDIT_STATUS.md").write_text("Research remains provisional.")
    for folder, _ in MODULE["SOURCES"].values():
        directory = tmp_path / "outputs" / folder
        directory.mkdir(parents=True)
        (directory / "index.html").write_text("Complete original source evidence.")
    output = tmp_path / relative
    output.mkdir(parents=True, exist_ok=True)
    for name in ["current-chart-data.zip", "current-graphs-manifest.json"]:
        (output / name).write_bytes(b"complete fixture")
    MODULE["gallery"](output, [], root=tmp_path)
    links = re.findall(r'href="([^"]+)"', (output / "index.html").read_text())
    targets = [(output / link).resolve() for link in links if not link.startswith("#")]
    assert (tmp_path / "docs/AUDIT_STATUS.md") in targets
    for folder, _ in MODULE["SOURCES"].values():
        assert (tmp_path / "outputs" / folder / "index.html") in targets
    assert all(target.is_file() for target in targets)

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

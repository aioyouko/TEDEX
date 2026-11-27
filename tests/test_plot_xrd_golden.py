"""End-to-end tests for plot-xrd using a synthetic .xy pattern.

plot-xrd accepts direct .xy file selectors and a custom output directory,
so this runs fully self-contained. It pins the CLI contract: exit code and
figure output naming for normalized and raw modes.
"""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from _helpers import REPO_ROOT, run_cli

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from te_analysis.tools.xrd import (
    DEFAULT_BOTTOM_PDF_GAP_FRACTION,
    DEFAULT_PDF_HEIGHT_FRACTION,
    PDFStandard,
    XRDPattern,
    plot_xrd_comparison,
)


def _write_synthetic_xy(directory: Path) -> Path:
    rows = []
    for i in range(10 * 50, 80 * 50):  # 10..80 degrees, 0.02 step
        two_theta = i / 50
        intensity = 80 + 40 * math.sin(i) ** 2
        for peak, height in ((27.4, 8000), (31.7, 4500), (45.5, 2600), (56.4, 1400)):
            intensity += height * math.exp(-((two_theta - peak) ** 2) / (2 * 0.05**2))
        rows.append(f"{two_theta:.4f} {intensity:.2f}")
    path = directory / "TE-9999-A_XRD.xy"
    path.write_text("\n".join(rows) + "\n")
    return path


def _write_pdf_card(directory: Path, filename: str, label: str, peak: float) -> Path:
    path = directory / filename
    path.write_text(
        "label,two_theta_deg,intensity\n"
        f"{label},{peak:.3f},100\n"
        f"{label},{peak + 5:.3f},40\n"
    )
    return path


def test_plot_xrd_normalized():
    with tempfile.TemporaryDirectory() as tmp:
        xy = _write_synthetic_xy(Path(tmp))
        out = Path(tmp) / "out"
        result = run_cli(
            ["plot-xrd", str(xy), "--no-pdf-card", "--no-show", "--output-dir", str(out)]
        )
        assert result.returncode == 0, (result.stderr or result.stdout)[-2000:]
        figures = sorted(out.rglob("*_XRD_normalized.svg"))
        assert figures, f"no normalized figure produced under {out}"


def test_plot_xrd_raw_counts():
    with tempfile.TemporaryDirectory() as tmp:
        xy = _write_synthetic_xy(Path(tmp))
        out = Path(tmp) / "out"
        result = run_cli(
            [
                "plot-xrd",
                str(xy),
                "--mode",
                "both",
                "--no-pdf-card",
                "--no-show",
                "--output-dir",
                str(out),
            ]
        )
        assert result.returncode == 0, (result.stderr or result.stdout)[-2000:]
        produced = sorted(p.name for p in out.rglob("*.svg"))
        assert any(n.endswith("_XRD_normalized.svg") for n in produced), produced
        assert any(n.endswith("_XRD_not_normalized.svg") for n in produced), produced


def test_plot_xrd_double_pdf_card_layout_and_optional_labels():
    pattern = XRDPattern(
        label="legend-only sample label",
        two_theta=np.asarray([10.0, 20.0, 30.0]),
        intensity=np.asarray([2.0, 10.0, 3.0]),
        source_path=Path("sample-right-label.xy"),
    )
    bottom_card = PDFStandard(
        label="Bottom phase PDF#1",
        peaks=pd.DataFrame({"two_theta_deg": [15.0, 25.0], "intensity": [100.0, 50.0]}),
        source_path=Path("bottom.csv"),
    )
    top_card = PDFStandard(
        label="Top phase PDF#2",
        peaks=pd.DataFrame({"two_theta_deg": [18.0, 28.0], "intensity": [40.0, 100.0]}),
        source_path=Path("top.csv"),
    )

    fig, ax = plot_xrd_comparison(
        [pattern],
        pdf_standard=bottom_card,
        top_pdf_standard=top_card,
        normalized=True,
        two_theta_range=(10.0, None),
        show_pdf_labels=True,
    )
    try:
        text_positions = {text.get_text(): text.get_position()[1] for text in ax.texts}
        assert "sample-right-label" in text_positions
        assert bottom_card.label in text_positions
        assert top_card.label in text_positions
        assert not fig.legends
        assert ax.get_legend() is None

        trace_y = np.asarray(ax.lines[0].get_ydata())
        pdf_collections = {
            collection.get_label(): collection
            for collection in ax.collections
            if collection.get_label() in {bottom_card.label, top_card.label}
        }
        assert set(pdf_collections) == {bottom_card.label, top_card.label}
        bottom_collection = pdf_collections[bottom_card.label]
        top_collection = pdf_collections[top_card.label]
        bottom_segments = bottom_collection.get_segments()
        top_segments = top_collection.get_segments()
        bottom_min = min(float(segment[:, 1].min()) for segment in bottom_segments)
        bottom_max = max(float(segment[:, 1].max()) for segment in bottom_segments)
        top_min = min(float(segment[:, 1].min()) for segment in top_segments)
        top_max = max(float(segment[:, 1].max()) for segment in top_segments)
        top_axis = ax.lines[-1]

        assert np.isclose(bottom_min, ax.get_ylim()[0])
        assert np.isclose(bottom_min, 0.0)
        assert bottom_max < float(trace_y.min())
        assert top_min > float(trace_y.max())
        assert np.isclose(float(trace_y.min()) - bottom_max, 0.60 * 1.05)
        assert np.isclose(top_min - float(trace_y.max()), 0.60 * 1.05)
        assert bottom_max < text_positions[bottom_card.label] < float(trace_y.min())
        assert top_max < text_positions[top_card.label] < ax.get_ylim()[1]
        assert ax.get_ylim()[1] > top_max
        trace_span = float(trace_y.max() - trace_y.min())
        expected_pdf_height = DEFAULT_PDF_HEIGHT_FRACTION * 1.05
        assert np.isclose(bottom_max - bottom_min, expected_pdf_height)
        assert np.isclose(top_max - top_min, expected_pdf_height)
        assert bottom_max - bottom_min > 0.7 * trace_span
        assert top_max - top_min > 0.7 * trace_span
        assert np.allclose(top_axis.get_ydata(), [top_min, top_min])
        assert np.allclose(top_axis.get_xdata(), [0.0, 1.0])
        assert matplotlib.colors.to_rgba(top_axis.get_color()) == matplotlib.colors.to_rgba("black")
        bottom_color = bottom_collection.get_colors()[0]
        top_color = top_collection.get_colors()[0]
        assert np.allclose(bottom_color, matplotlib.colors.to_rgba("#d62728"))
        assert np.allclose(top_color, matplotlib.colors.to_rgba("#1f77b4"))
        assert not np.allclose(bottom_color, top_color)

        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        bottom_text = next(text for text in ax.texts if text.get_text() == bottom_card.label)
        top_text = next(text for text in ax.texts if text.get_text() == top_card.label)
        bottom_text_bounds = bottom_text.get_window_extent(renderer)
        top_text_bounds = top_text.get_window_extent(renderer)
        bottom_stick_y = ax.transData.transform((0.0, bottom_max))[1]
        first_trace_y = ax.transData.transform((0.0, float(trace_y.min())))[1]
        top_stick_y = ax.transData.transform((0.0, top_max))[1]
        axes_top_y = ax.get_window_extent(renderer).y1
        assert bottom_text_bounds.y0 > bottom_stick_y
        assert bottom_text_bounds.y1 < first_trace_y
        assert top_text_bounds.y0 > top_stick_y
        assert top_text_bounds.y1 < axes_top_y
    finally:
        plt.close(fig)

    fig, ax = plot_xrd_comparison(
        [pattern],
        pdf_standard=bottom_card,
        top_pdf_standard=top_card,
        normalized=True,
        two_theta_range=(10.0, None),
    )
    try:
        visible_text = {text.get_text() for text in ax.texts}
        assert "sample-right-label" in visible_text
        assert bottom_card.label not in visible_text
        assert top_card.label not in visible_text
        hidden_collections = {
            collection.get_label(): collection
            for collection in ax.collections
            if collection.get_label() in {bottom_card.label, top_card.label}
        }
        assert set(hidden_collections) == {bottom_card.label, top_card.label}
        hidden_bottom_max = max(
            float(segment[:, 1].max())
            for segment in hidden_collections[bottom_card.label].get_segments()
        )
        hidden_trace_min = float(np.min(ax.lines[0].get_ydata()))
        assert np.isclose(
            hidden_trace_min - hidden_bottom_max,
            DEFAULT_BOTTOM_PDF_GAP_FRACTION * 1.05,
        )
    finally:
        plt.close(fig)


def test_plot_xrd_keeps_pdf_card_name_when_range_has_no_peaks():
    pattern = XRDPattern(
        label="sample",
        two_theta=np.asarray([10.0, 20.0, 30.0]),
        intensity=np.asarray([1.0, 5.0, 2.0]),
        source_path=Path("sample.xy"),
    )
    out_of_range_card = PDFStandard(
        label="Out-of-range PDF card",
        peaks=pd.DataFrame({"two_theta_deg": [50.0], "intensity": [100.0]}),
        source_path=Path("outside.csv"),
    )

    fig, ax = plot_xrd_comparison(
        [pattern],
        pdf_standard=out_of_range_card,
        normalized=True,
        two_theta_range=(10.0, 30.0),
        show_pdf_labels=True,
    )
    try:
        assert out_of_range_card.label in {text.get_text() for text in ax.texts}
        assert not ax.collections
        assert float(np.min(ax.lines[0].get_ydata())) > 0.0
        assert np.isclose(ax.get_ylim()[0], 0.0)
    finally:
        plt.close(fig)


def test_plot_xrd_cli_accepts_two_pdf_cards():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        xy = _write_synthetic_xy(tmp_path)
        bottom_card = _write_pdf_card(tmp_path, "bottom.csv", "Bottom CLI card", 24.0)
        top_card = _write_pdf_card(tmp_path, "top.csv", "Top CLI card", 30.0)
        hidden_out = tmp_path / "hidden-out"

        hidden_result = run_cli(
            [
                "plot-xrd",
                str(xy),
                "--pdf-card",
                str(bottom_card),
                "--pdf-card",
                str(top_card),
                "--no-show",
                "--output-dir",
                str(hidden_out),
            ]
        )

        assert hidden_result.returncode == 0, (hidden_result.stderr or hidden_result.stdout)[-2000:]
        hidden_figures = sorted(hidden_out.rglob("*_XRD_normalized.svg"))
        assert hidden_figures, f"no normalized figure produced under {hidden_out}"
        hidden_svg = hidden_figures[0].read_text(encoding="utf-8").lower()
        assert "bottom cli card" not in hidden_svg
        assert "top cli card" not in hidden_svg
        assert "te-9999-a_xrd" in hidden_svg
        assert "stroke: #d62728" in hidden_svg
        assert "stroke: #1f77b4" in hidden_svg

        out = tmp_path / "shown-out"

        result = run_cli(
            [
                "plot-xrd",
                str(xy),
                "--pdf-card",
                str(bottom_card),
                "--pdf-card",
                str(top_card),
                "--standard-color",
                "#123456",
                "--top-standard-color",
                "#abcdef",
                "--pdf-height-fraction",
                "0.9",
                "--pdf-labels",
                "--no-show",
                "--output-dir",
                str(out),
            ]
        )

        assert result.returncode == 0, (result.stderr or result.stdout)[-2000:]
        assert "Bottom PDF standard: Bottom CLI card" in result.stdout
        assert "Top PDF standard: Top CLI card" in result.stdout
        figures = sorted(out.rglob("*_XRD_normalized.svg"))
        assert figures, f"no normalized figure produced under {out}"
        svg = figures[0].read_text(encoding="utf-8").lower()
        assert "bottom cli card" in svg
        assert "top cli card" in svg
        assert "te-9999-a_xrd" in svg
        assert "stroke: #123456" in svg
        assert "stroke: #abcdef" in svg

        for case_name, extra_args, expected_count in (
            ("both", ["--both"], 2),
            ("separate", ["--layout", "separate"], 1),
        ):
            case_out = tmp_path / f"shown-{case_name}"
            case_result = run_cli(
                [
                    "plot-xrd",
                    str(xy),
                    "--pdf-card",
                    str(bottom_card),
                    "--pdf-card",
                    str(top_card),
                    "--standard-color",
                    "#123456",
                    "--top-standard-color",
                    "#abcdef",
                    "--pdf-height-fraction",
                    "0.9",
                    "--pdf-card-labels",
                    "--no-show",
                    "--output-dir",
                    str(case_out),
                    *extra_args,
                ]
            )
            assert case_result.returncode == 0, (
                case_result.stderr or case_result.stdout
            )[-2000:]
            case_figures = sorted(case_out.rglob("*.svg"))
            assert len(case_figures) == expected_count, case_figures
            for case_figure in case_figures:
                case_svg = case_figure.read_text(encoding="utf-8").lower()
                assert "bottom cli card" in case_svg
                assert "top cli card" in case_svg
                assert "stroke: #123456" in case_svg
                assert "stroke: #abcdef" in case_svg

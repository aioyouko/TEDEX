"""Regression coverage for folder-order XRD selection and bound legend labels."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from _helpers import REPO_ROOT, run_cli

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from te_analysis.tools.xrd import load_xrd_patterns, plot_xrd_comparison
from te_analysis.tools.xrd.io import select_xrd_patterns_by_index


def _write_folder(directory: Path, count: int = 4) -> tuple[list[str], list[str]]:
    directory.mkdir()
    # Deliberately create these out of order; scan-10 sorts before scan-2.
    names = (
        ["scan-3.xy", "scan-2.xy", "scan-10.xy", "scan-1.xy"]
        if count == 4
        else [f"scan-{index:02d}.xy" for index in range(count, 0, -1)]
    )
    for index, name in enumerate(names, start=1):
        (directory / name).write_text(
            f"10 {index}\n20 {10 + index}\n30 {3 * index}\n40 {2 * index}\n",
            encoding="utf-8",
        )
    labels = [f"LEGEND_ROW_{index:02d}" for index in range(1, count + 1)]
    (directory / "legend.txt").write_text("\n".join(labels) + "\n", encoding="utf-8")
    return sorted(names), labels


def _assert_cli_ok(result):
    assert result.returncode == 0, (result.stderr or result.stdout)[-3000:]


def _assert_svg_labels(path: Path, selected: list[str], excluded: list[str]):
    svg = path.read_text(encoding="utf-8")
    for label in selected:
        assert label in svg, f"{label} missing from {path.name}"
    for label in excluded:
        assert label not in svg, f"unselected {label} included in {path.name}"


def test_xrd_index_selection_keeps_filename_order_and_bound_legend_rows():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "patterns"
        names, labels = _write_folder(folder)
        patterns = load_xrd_patterns([str(folder)])

        assert [pattern.source_path.name for pattern in patterns] == names
        assert [pattern.label for pattern in patterns] == labels
        assert all(pattern.label_from_file for pattern in patterns)
        selected = select_xrd_patterns_by_index(patterns)
        assert len(selected) == 4
        assert all(actual is original for actual, original in zip(selected, patterns))

        for indices in ([1, 2, 4], [2, 3, 4], [4, 2, 1, 2]):
            selected = select_xrd_patterns_by_index(patterns, indices)
            expected_indices = sorted(set(indices))
            assert [pattern.source_path.name for pattern in selected] == [
                names[index - 1] for index in expected_indices
            ]
            assert [pattern.label for pattern in selected] == [
                labels[index - 1] for index in expected_indices
            ]
            assert all(
                actual is patterns[index - 1]
                for actual, index in zip(selected, expected_indices)
            )


def test_xrd_selected_traces_legend_and_right_labels_stay_aligned():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "patterns"
        _, labels = _write_folder(folder)
        patterns = load_xrd_patterns([str(folder)])
        for indices in ([1, 2, 4], [2, 3, 4]):
            selected = select_xrd_patterns_by_index(patterns, indices)
            expected_labels = [labels[index - 1] for index in indices]
            fig, ax = plot_xrd_comparison(
                selected,
                normalized=False,
                baseline="none",
                offset_step=100.0,
                two_theta_range=(10.0, 40.0),
                show_legend=True,
                right_labels=True,
            )
            try:
                assert [line.get_label() for line in ax.lines] == expected_labels
                assert [text.get_text() for text in ax.texts] == expected_labels
                legends = list(fig.legends)
                if ax.get_legend() is not None:
                    legends.append(ax.get_legend())
                assert len(legends) == 1
                assert [text.get_text() for text in legends[0].get_texts()] == expected_labels
                for row, (line, pattern) in enumerate(zip(ax.lines, selected)):
                    assert np.array_equal(line.get_xdata(), pattern.two_theta)
                    assert np.allclose(line.get_ydata(), pattern.intensity + row * 100.0)
            finally:
                plt.close(fig)


def test_xrd_index_selection_supports_ten_and_rejects_invalid_positions():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "patterns"
        _, labels = _write_folder(folder, count=12)
        patterns = load_xrd_patterns([str(folder)])
        selected = select_xrd_patterns_by_index(patterns, [10, 2, 10])
        assert [pattern.label for pattern in selected] == [labels[1], labels[9]]
        for indices in ([], [0], [-1], [13], [1, 13], [True], [1.5], ["2"]):
            try:
                select_xrd_patterns_by_index(patterns, indices)
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid XRD indices accepted: {indices}")


def test_plot_xrd_pick_cli_filters_both_modes_and_separate_figures():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "patterns"
        _, labels = _write_folder(folder)
        for pick, layout, count in (("124", "stack", 2), ("234", "separate", 6)):
            out = root / layout
            result = run_cli(
                [
                    "plot-xrd", str(folder), "--pick", pick,
                    "--both", "--layout", layout, "--legend", "--no-show",
                    "--formats", "svg", "--output-dir", str(out),
                ]
            )
            _assert_cli_ok(result)
            figures = sorted(out.rglob("*.svg"))
            assert len(figures) == count, [path.name for path in figures]
            assert any(path.name.endswith("_XRD_normalized.svg") for path in figures)
            assert any(path.name.endswith("_XRD_not_normalized.svg") for path in figures)
            chosen_labels = [labels[int(digit) - 1] for digit in pick]
            excluded_labels = [label for label in labels if label not in chosen_labels]
            for figure in figures:
                _assert_svg_labels(
                    figure,
                    chosen_labels if layout == "stack" else [],
                    excluded_labels,
                )
                if layout == "separate":
                    svg = figure.read_text(encoding="utf-8")
                    assert sum(label in svg for label in chosen_labels) == 1
            for label in chosen_labels:
                assert sum(label in path.read_text(encoding="utf-8") for path in figures) == 2


def test_plot_xrd_indices_apply_before_name_filter():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "patterns"
        _, labels = _write_folder(folder, count=12)
        out = root / "out"
        result = run_cli(
            [
                "plot-xrd", str(folder), "--indices", "2", "10",
                "--select", labels[9], "--no-show", "--formats", "svg",
                "--output-dir", str(out),
            ]
        )
        _assert_cli_ok(result)
        figures = sorted(out.rglob("*.svg"))
        assert len(figures) == 1
        _assert_svg_labels(figures[0], [labels[9]], [label for label in labels if label != labels[9]])


def test_plot_xrd_list_files_shows_original_labels_without_plotting():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "patterns"
        names, labels = _write_folder(folder)
        out = root / "out"
        result = run_cli(
            [
                "plot-xrd", str(folder), "--list-files", "--pick", "24",
                "--select", labels[3], "--no-show", "--output-dir", str(out),
            ]
        )
        _assert_cli_ok(result)
        positions = []
        for index, (name, label) in enumerate(zip(names, labels), start=1):
            matches = [line for line in result.stdout.splitlines() if name in line and label in line]
            assert len(matches) == 1, result.stdout
            assert matches[0].strip().startswith(f"{index}. "), matches[0]
            positions.append(result.stdout.index(matches[0]))
        assert positions == sorted(positions)
        assert not list(root.rglob("*.svg"))
        assert not list(root.rglob("*.png"))
        assert not list(root.rglob("*.pdf"))


def test_plot_xrd_pick_cli_rejects_invalid_and_conflicting_arguments():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "patterns"
        _write_folder(folder)
        out = root / "out"
        for options in (
            ["--pick", "10"],
            ["--pick", "1a"],
            ["--pick", ""],
            ["--indices", "0"],
            ["--indices", "5"],
            ["--pick", "12", "--indices", "1", "2"],
        ):
            result = run_cli(
                ["plot-xrd", str(folder), *options, "--no-show", "--output-dir", str(out)]
            )
            assert result.returncode != 0, f"invalid options accepted: {options}"
            assert "error" in (result.stderr + result.stdout).lower()
        assert not list(out.rglob("*.svg"))

"""Color selection, gradient sampling, and cross-panel identity regressions."""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_hex
import numpy as np
import pandas as pd

from _helpers import REPO_ROOT, run_cli

sys.path.insert(0, str(REPO_ROOT))
from te_analysis.tools.colors import COLOR_SETS, SEQUENTIAL_COLOR_SETS, get_colors
from te_analysis.tools.plot import get_style_cycles, plot_property_vs_temperature
from te_analysis.tools.flexible.cli import add_direct_cli_args, build_recipe_from_cli, override_recipe_from_cli
from te_analysis.tools.flexible.render import plot_line_or_scatter, plot_multi_panel, plot_dual_line, plot_dual_axis, plot_bar
from te_analysis.tools.xrd import XRDPattern, plot_xrd_comparison, plot_xrd_separate


def test_gradient_spans_full_range_and_remains_monotonic():
    for name in SEQUENTIAL_COLOR_SETS:
        for count in (1, 2, 3, 5, 8, 15):
            colors = get_colors(name, count)
            assert len(colors) == count
            assert to_hex(colors[0]) == to_hex(COLOR_SETS[name][0])
            if count > 1:
                assert to_hex(colors[-1]) == to_hex(COLOR_SETS[name][-1])
                rgb = np.asarray([matplotlib.colors.to_rgb(c) for c in colors])
                linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
                luminance = linear @ np.array([.2126, .7152, .0722])
                assert np.all(np.diff(luminance) > 0)
        assert get_colors(name, 0) == []
        assert to_hex(get_colors(name, 3)[1]) == to_hex(COLOR_SETS[name][2])


def test_default_and_legacy_cycles():
    assert get_colors() == list(COLOR_SETS["science"])
    colors, markers = get_style_cycles("legacy", 3)
    assert [next(colors) for _ in range(25)] == list(COLOR_SETS["legacy"]) + ["#d62728"]
    assert [next(markers) for _ in range(4)] == ["o", "s", "D", "^"]
    for name, count in (("missing", 3), ("blue", -1)):
        try:
            get_colors(name, count)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid palette/count was accepted")


def test_te_missing_property_keeps_sample_color_and_marker():
    samples = {name: pd.DataFrame({"Temperature": [300, 400], "ZT": [.4, .7],
               "Carrier_Thermal_Conductivity": [.2, .3]}) for name in ("A", "B", "C")}
    samples["B"] = samples["B"].drop(columns="Carrier_Thermal_Conductivity")
    fig, axes = plt.subplots(1, 2)
    try:
        plot_property_vs_temperature(axes[0], samples, "zt", color_set="blue")
        plot_property_vs_temperature(axes[1], samples, "carrier_thermal_conductivity", color_set="blue")
        reference = {line.get_label(): (to_hex(line.get_color()), line.get_marker()) for line in axes[0].lines}
        assert list(reference.values())[2][0] == to_hex(COLOR_SETS["blue"][-1])
        assert [line.get_label() for line in axes[1].lines] == ["A", "C"]
        for line in axes[1].lines:
            assert (to_hex(line.get_color()), line.get_marker()) == reference[line.get_label()]
    finally:
        plt.close(fig)


def _normalized():
    rows = []
    for prop in ("p", "q"):
        for index, group in enumerate(("A", "B", "C")):
            if prop == "q" and group == "B":
                continue
            for x in (1, 2):
                rows.append(dict(x=x, y=x + index, property=prop, group=group,
                                 series_order=0 if prop == "p" else 1,
                                 color="#123456" if group == "A" else "", marker="", label=""))
    return pd.DataFrame(rows), {"x_label": "x", "property_labels": {"p": "P", "q": "Q"}, "categorical_x": False}


def test_flexible_panels_and_overlays_keep_explicit_and_group_colors():
    data, metadata = _normalized()
    for renderer in (plot_line_or_scatter, plot_multi_panel, plot_dual_line):
        fig, _ = renderer(data, metadata, {"plot": {"color_set": "purple"}})
        try:
            seen = {}
            for ax in fig.axes:
                for line in ax.lines:
                    # Line/scatter appends the property name; multi-panel uses the group.
                    group = line.get_label().split(" - ")[0]
                    if group in ("P", "Q"):
                        continue
                    color = to_hex(line.get_color())
                    assert seen.setdefault(group, color) == color
            all_colors = {to_hex(line.get_color()) for ax in fig.axes for line in ax.lines}
            assert "#123456" in all_colors
            assert to_hex(COLOR_SETS["purple"][-1]) in all_colors
        finally:
            plt.close(fig)


def test_flexible_bar_and_dual_axis_accept_color_sets():
    data, metadata = _normalized()
    # dual_axis expects one value per group/property.
    data = data[data.x == 1].copy()
    for renderer in (plot_bar, plot_dual_axis):
        fig, _ = renderer(data, metadata, {"plot": {"color_set": "teal"}})
        try:
            assert fig.axes[0].patches
            assert to_hex(fig.axes[0].patches[0].get_facecolor()) == "#123456"
        finally:
            plt.close(fig)


def test_flexible_cli_palette_overrides_recipe_but_keeps_explicit_color():
    parser = argparse.ArgumentParser()
    add_direct_cli_args(parser)
    argv = ["input.csv", "--x", "T", "--y", "ZT", "--color-set", "blue", "--color", "red"]
    args = parser.parse_args(argv)
    direct = build_recipe_from_cli(args)
    assert direct["plot"]["color_set"] == "blue"
    assert direct["plot"]["series"][0]["color"] == "red"
    original = {"plot": {"color_set": "purple", "series": [{"y": {"column": "ZT"}, "color": "black"}]}}
    updated = override_recipe_from_cli(original, args, argv)
    assert updated["plot"]["color_set"] == "blue"
    assert updated["plot"]["series"][0]["color"] == "red"
    unchanged = override_recipe_from_cli(original, parser.parse_args([]), [])
    assert unchanged["plot"]["color_set"] == "purple"
    assert original["plot"]["series"][0]["color"] == "black"


def test_xrd_gradient_and_separate_figures_match_stack():
    patterns = [XRDPattern(label=f"S{i}", two_theta=np.array([10., 20., 30.]),
                intensity=np.array([2., 10., 3.]), source_path=Path(f"S{i}.xy")) for i in range(3)]
    expected = get_colors("blue", 3)
    fig, ax = plot_xrd_comparison(patterns, color_set="blue", close=False)
    try:
        assert [to_hex(line.get_color()) for line in ax.lines] == expected
    finally:
        plt.close(fig)
    with tempfile.TemporaryDirectory() as tmp, patch("te_analysis.tools.xrd.render.plot_xrd_comparison", return_value="test.svg") as render:
        plot_xrd_separate(patterns, None, "demo", save_dir=tmp, color_set="blue")
        assert [call.kwargs["colors"][0] for call in render.call_args_list] == [c for c in expected for _ in range(2)]
    fig, ax = plot_xrd_comparison(patterns, colors=["red"], color_set="blue", close=False)
    try:
        assert all(to_hex(line.get_color()) == "#ff0000" for line in ax.lines)
    finally:
        plt.close(fig)


def test_all_plotting_cli_help_exposes_color_set_and_rejects_typos():
    for command in (["plot-te"], ["plot-xrd"], ["flexible"],
                    ["spb", "effective-mass"], ["spb", "performance"], ["spb", "conductivity"]):
        result = run_cli([*command, "--help"])
        assert result.returncode == 0, result.stderr
        assert "--color-set" in result.stdout
    result = run_cli(["plot-te", "--color-set", "blu"])
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_color_set_reaches_te_flexible_and_xrd_cli_figures():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        csvs = []
        patterns = []
        for i in range(3):
            csv = root / f"palette_batch_{i}.csv"
            csv.write_text(f"Temperature,ZT\n300,{.3 + i * .1}\n400,{.5 + i * .1}\n")
            csvs.append(str(csv))
            xy = root / f"palette_batch_{i}.xy"
            xy.write_text("10 2\n20 10\n30 3\n")
            patterns.append(str(xy))
        cases = [
            (["plot-te", *csvs, "--zt", "--legend", "--comparison-id", "color_set_test", "--color-set", "blue", "--no-show"], root / "figures"),
            (["flexible", *csvs, "--x", "Temperature", "--y", "ZT", "--color-set", "blue", "--formats", "svg", "--no-show", "--output-dir", str(root / "flex")], root / "flex"),
            (["plot-xrd", *patterns, "--color-set", "blue", "--no-pdf-card", "--no-show", "--output-dir", str(root / "xrd")], root / "xrd"),
        ]
        for args, output in cases:
            result = run_cli(args)
            assert result.returncode == 0, result.stderr or result.stdout
            figures = list(output.rglob("*.svg"))
            assert figures, result.stdout
            text = "\n".join(p.read_text(encoding="utf-8").lower() for p in figures)
            for color in get_colors("blue", 3):
                assert color in text, (args[0], color)


def test_spb_color_selection_preserves_all_fit_summaries():
    # Same paths for both runs avoid machine-specific temporary paths in JSON.
    # Relative paths retain separate groups with the same summary filename.
    from test_spb_golden import CASES, DEMO
    for name, case in CASES.items():
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in case["inputs"]:
                shutil.copy(DEMO / relative, root / Path(relative).name)
            output = root / "out"
            args = case["args"](root) + [str(output)]
            baseline = run_cli(args)
            assert baseline.returncode == 0, baseline.stderr
            summaries = {str(p.relative_to(output)): json.loads(p.read_text())
                         for p in output.glob(case["summary_glob"])}
            assert summaries
            colored = run_cli([*args, "--color-set", "blue"])
            assert colored.returncode == 0, colored.stderr
            after = {str(p.relative_to(output)): json.loads(p.read_text())
                     for p in output.glob(case["summary_glob"])}
            assert after == summaries, name


def test_spb_gradient_pairs_model_and_measurement_groups():
    from te_analysis.tools.spb.effective_mass_fit import build_spb_fit_normalized_table
    from te_analysis.tools.spb.performance_fit import build_property_normalized_table as performance
    from te_analysis.tools.spb.conductivity_fit import build_property_normalized_table as conductivity
    points = pd.DataFrame({
        "point_series_id": ["A", "B", "C"], "legend_label": ["A", "B", "C"],
        "nH_cm-3": [1e19] * 3, "Seebeck_abs_uV_K": [100.] * 3,
        "ZT": [.5] * 3, "Conductivity_S_cm-1": [1000.] * 3,
    })
    curves = pd.DataFrame({
        "series_id": ["A", "B", "C"], "legend_label": ["A", "B", "C"],
        "mstar_over_me": [1.] * 3, "nH_cm-3": [1e19] * 3,
        "Seebeck_abs_uV_K": [100.] * 3, "ZT_model": [.5] * 3,
        "Conductivity_model_S_cm-1": [1000.] * 3,
    })
    recipe = {"plot": {"color_set": "blue"}}
    outputs = [build_spb_fit_normalized_table(points, curves, {}, recipe)[0],
               performance(points, curves, "zt", recipe)[0],
               conductivity(points, curves, "zt", recipe)[0]]
    for output in outputs:
        for group, color in zip(("A", "B", "C"), get_colors("blue", 3)):
            assert set(output.loc[output.group == group, "color"].map(to_hex)) == {color}

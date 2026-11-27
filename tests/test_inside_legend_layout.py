"""Tests for smart inside-axes legend placement across TE, XRD, flexible, and multi-axis plots."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from _helpers import REPO_ROOT, load_script

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from te_analysis.tools import plot as te_plot
from te_analysis.tools.flexible.render import plot_dual_line, plot_multi_panel
from te_analysis.tools.flexible.render_bars_waterfall import plot_stacked_bar
from te_analysis.tools.flexible.render_maps import plot_ternary
from te_analysis.tools.flexible.render_stats_special import plot_radar
from te_analysis.tools.xrd import XRDPattern, plot_xrd_comparison


def _legend_axes_bbox(ax: plt.Axes):
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    leg = ax.get_legend()
    assert leg is not None, "Expected inside axes legend, got None"
    return leg.get_window_extent(renderer).transformed(ax.transAxes.inverted())


def test_single_te_legend_expands_headroom_and_avoids_curve_collision():
    # Curves span the entire top band across x so default ylim would force a collision
    temps = np.linspace(300, 800, 11)
    samples = {
        f"Sample_Composition_{idx}": pd.DataFrame(
            {
                "Temperature": temps,
                "ZT": 1.15 + 0.08 * np.sin((temps - 300) / 80.0 + idx) + 0.02 * idx,
            }
        )
        for idx in range(5)
    }
    fig, ax = te_plot.plot_single_property(samples, "zt", legend="inside")
    try:
        assert not fig.legends
        lb = _legend_axes_bbox(ax)
        assert lb.x0 >= 0.0 and lb.x1 <= 1.0
        assert lb.y0 >= 0.0 and lb.y1 <= 1.0
        # Non-negative ZT must never be pushed below zero
        assert ax.get_ylim()[0] >= 0.0

        # Check no plotted data vertex sits inside the legend box
        inv_ax = ax.transAxes.inverted()
        for line in ax.lines:
            pts_disp = ax.transData.transform(np.column_stack([line.get_xdata(), line.get_ydata()]))
            pts_ax = inv_ax.transform(pts_disp)
            inside = (
                (pts_ax[:, 0] >= lb.x0)
                & (pts_ax[:, 0] <= lb.x1)
                & (pts_ax[:, 1] >= lb.y0)
                & (pts_ax[:, 1] <= lb.y1)
            )
            assert not np.any(inside), f"Curve {line.get_label()} collided with inside legend {lb}"
    finally:
        plt.close(fig)


def test_percent_stacked_bar_keeps_legend_inside_and_caps_ticks_at_100():
    rows = []
    for cat in ("x=0", "x=0.02", "x=0.04", "x=0.06"):
        rows.append({"x": np.nan, "x_category": cat, "y": 65.0, "property": "share", "group": "Lattice", "legend_label": "Lattice", "series_order": 0})
        rows.append({"x": np.nan, "x_category": cat, "y": 35.0, "property": "share", "group": "Electronic", "legend_label": "Electronic", "series_order": 1})
    df = pd.DataFrame(rows)
    meta = {"categorical_x": True, "x_categories": ["x=0", "x=0.02", "x=0.04", "x=0.06"], "x_label": "Sample", "property_labels": {"share": "Share (%)"}}

    fig, ax = plot_stacked_bar(df, meta, {"plot": {"legend": "inside"}}, percent=True)
    try:
        assert not fig.legends
        lb = _legend_axes_bbox(ax)
        assert lb.x0 >= 0.0 and lb.x1 <= 1.0 and lb.y1 <= 1.0
        assert ax.get_ylim()[1] > 100.0
        visible_ticks = [t for t in ax.get_yticks() if ax.get_ylim()[0] - 1e-6 <= t <= ax.get_ylim()[1] + 1e-6]
        assert max(visible_ticks) <= 100.0 + 1e-6
    finally:
        plt.close(fig)


def test_multi_panel_and_dual_line_place_legends_inside_axes():
    rows = []
    for prop_idx, prop in enumerate(("seebeck", "zt")):
        for grp_idx, grp in enumerate(("Batch A", "Batch B", "Batch C")):
            for t in (300.0, 500.0, 700.0):
                rows.append(
                    {
                        "x": t,
                        "x_category": None,
                        "y": (120.0 + 20.0 * grp_idx + 0.1 * t) if prop == "seebeck" else (0.3 + 0.15 * grp_idx + 0.001 * t),
                        "property": prop,
                        "group": grp,
                        "legend_label": grp,
                        "series_order": prop_idx,
                    }
                )
    df = pd.DataFrame(rows)
    meta = {"x_label": "$T$ (K)", "property_labels": {"seebeck": "$S$", "zt": "$ZT$"}, "categorical_x": False}

    fig_mp, axes_mp = plot_multi_panel(df, meta, {"plot": {}})
    try:
        assert not fig_mp.legends
        lb = _legend_axes_bbox(axes_mp.ravel()[0])
        assert lb.x0 >= 0.0 and lb.x1 <= 1.0 and lb.y0 >= 0.0 and lb.y1 <= 1.0
    finally:
        plt.close(fig_mp)

    dual_df = df[df["group"] == "Batch A"].copy()
    dual_df["legend_label"] = dual_df["property"].map({"seebeck": "Voltage", "zt": "Power"})
    fig_dl, (ax_l, _ax_r) = plot_dual_line(dual_df, meta, {"plot": {}})
    try:
        assert not fig_dl.legends
        lb_dl = _legend_axes_bbox(ax_l)
        assert lb_dl.x0 >= 0.0 and lb_dl.x1 <= 1.0 and lb_dl.y0 >= 0.0 and lb_dl.y1 <= 1.0
    finally:
        plt.close(fig_dl)


def test_xrd_show_legend_defaults_inside_axes():
    script = load_script("scripts/plotting/plot_xrd.py", "plot_xrd_legend_cli")
    with patch.object(sys, "argv", ["plot_xrd.py", "--legend"]):
        parsed = script.parse_args()
        assert parsed.show_legend is True
        assert parsed.legend_outside is False

    x = np.linspace(10.0, 80.0, 350)
    patterns = [
        XRDPattern(
            label=f"TE-1048-{ch}",
            two_theta=x,
            intensity=10.0 + 120.0 * np.exp(-0.5 * ((x - (27.5 + idx * 0.2)) / 0.25) ** 2),
            source_path=Path(f"TE-1048-{ch}.xy"),
        )
        for idx, ch in enumerate("ABC")
    ]
    fig, ax = plot_xrd_comparison(patterns, normalized=True, show_legend=True)
    try:
        assert not fig.legends
        lb = _legend_axes_bbox(ax)
        assert lb.x0 >= 0.0 and lb.x1 <= 1.0 and lb.y0 >= 0.0 and lb.y1 <= 1.0
    finally:
        plt.close(fig)


def test_radar_and_ternary_keep_legends_inside_axes():
    radar_rows = []
    for grp, scale in (("Baseline", 0.6), ("Optimized", 0.95)):
        for spoke in ("zT", "PF", "sigma", "1/kL", "HV"):
            radar_rows.append({"x": np.nan, "x_category": spoke, "y": scale, "property": "score", "group": grp, "legend_label": grp, "series_order": 0})
    fig_r, ax_r = plot_radar(
        pd.DataFrame(radar_rows),
        {"categorical_x": True, "x_categories": ["zT", "PF", "sigma", "1/kL", "HV"], "property_labels": {"score": "Score"}},
        {"plot": {}},
    )
    try:
        assert not fig_r.legends
        assert ax_r.get_legend() is not None
    finally:
        plt.close(fig_r)

    tern_df = pd.DataFrame(
        {
            "a": [70.0, 25.0],
            "b": [20.0, 55.0],
            "c": [10.0, 20.0],
            "x": [0.0, 1.0],
            "y": [0.0, 1.0],
            "property": ["comp", "comp"],
            "group": ["Series 1", "Series 2"],
            "legend_label": ["Series 1", "Series 2"],
            "series_order": [0, 1],
        }
    )
    fig_t, ax_t = plot_ternary(tern_df, {"a_label": "A", "b_label": "B", "c_label": "C", "property_labels": {"comp": "Comp"}}, {"plot": {}})
    try:
        assert not fig_t.legends
        lb_t = _legend_axes_bbox(ax_t)
        assert lb_t.x1 <= 1.0 and lb_t.y1 <= 1.0
    finally:
        plt.close(fig_t)

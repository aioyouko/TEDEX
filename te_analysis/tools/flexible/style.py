"""Legend, tick, and axis styling for flexible plots.

Split verbatim from flexible_plot.py; behavior unchanged.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from te_analysis.tools.matplotlib_backend import configure_matplotlib_backend, show_interactive_figures  # noqa: E402

configure_matplotlib_backend()

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import ticker

from te_analysis.tools.plot import (  # noqa: E402
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_MARKER_SIZE,
    DEFAULT_SUBPLOT_ASPECT,
    DEFAULT_SUBPLOT_HEIGHT,
    apply_subplot_aspect,
    apply_plot_style,
    figure_size_for_subplot_aspect,
    format_te_axis,
    get_style_cycles,
    save_figure,
)


from te_analysis.tools.flexible.util import (  # noqa: E402
    as_list,
    first_defined,
    optional_bool,
    plain_number_label,
)


SINGLE_TICK_LABEL_SIZE = 10
SUMMARY_TICK_LABEL_SIZE = 9
TICK_FORMAT_CHOICES = ("auto", "plain", "scientific")
DEFAULT_LEGEND_FRAME = True
DEFAULT_LEGEND_EDGE_COLOR = "black"
DEFAULT_LEGEND_FACE_COLOR = "white"
DEFAULT_LEGEND_FRAME_ALPHA = 1.0
DEFAULT_LEGEND_FRAME_LINEWIDTH = 0.8
def legend_font_size(plot: dict[str, Any] | None, fallback: float | None = None) -> float:
    plot = plot or {}
    value = first_defined(plot.get("legend_font_size"), fallback, default=DEFAULT_LEGEND_FONT_SIZE)
    return float(value)


def legend_frame_enabled(plot: dict[str, Any] | None) -> bool:
    plot = plot or {}
    return optional_bool(
        first_defined(plot.get("legend_frame"), plot.get("legend_box")),
        default=DEFAULT_LEGEND_FRAME,
    )


def legend_kwargs(
    plot: dict[str, Any] | None,
    *,
    fontsize: float | None = None,
    loc: str | None = None,
    title: str | None = None,
    bbox_to_anchor: Any = None,
    ncol: int | None = None,
) -> dict[str, Any]:
    plot = plot or {}
    frameon = legend_frame_enabled(plot)
    kwargs: dict[str, Any] = {
        "fontsize": legend_font_size(plot, fontsize),
        "frameon": frameon,
    }
    if loc is not None:
        kwargs["loc"] = loc
    if bbox_to_anchor is not None:
        kwargs["bbox_to_anchor"] = bbox_to_anchor
    if ncol is not None:
        kwargs["ncol"] = ncol

    legend_title = first_defined(title, plot.get("legend_title"))
    if legend_title is not None:
        kwargs["title"] = legend_title

    if frameon:
        kwargs.update(
            {
                "edgecolor": plot.get("legend_edgecolor", DEFAULT_LEGEND_EDGE_COLOR),
                "facecolor": plot.get("legend_facecolor", DEFAULT_LEGEND_FACE_COLOR),
                "fancybox": False,
                "framealpha": float(plot.get("legend_frame_alpha", DEFAULT_LEGEND_FRAME_ALPHA)),
            }
        )

    return kwargs


def apply_legend_style(legend_object: Any, plot: dict[str, Any] | None) -> None:
    if legend_object is None:
        return
    if legend_object.get_title().get_text():
        legend_object.get_title().set_fontsize(legend_font_size(plot))
    if legend_frame_enabled(plot):
        legend_object.get_frame().set_linewidth(
            float((plot or {}).get("legend_frame_linewidth", DEFAULT_LEGEND_FRAME_LINEWIDTH))
        )


def optional_style(group_df: pd.DataFrame, key: str) -> Any:
    if key not in group_df.columns:
        return None
    values = group_df[key].dropna()
    values = values[values.astype(str) != ""]
    if values.empty:
        return None
    return values.iloc[0]


def log_plain_formatter(axis: ticker.Axis) -> ticker.FuncFormatter:
    def formatter(value: float, _position: int | None = None) -> str:
        if value <= 0 or not np.isfinite(value):
            return ""

        low, high = sorted(axis.get_view_interval())
        if low <= 0 or high <= 0:
            return plain_number_label(value)
        if value < low * (1 - 1e-10) or value > high * (1 + 1e-10):
            return ""

        decades = math.log10(high) - math.log10(low)
        exponent = math.floor(math.log10(value))
        mantissa = value / (10**exponent)
        rounded_mantissa = round(mantissa)

        if decades <= 1.25:
            if abs(mantissa - rounded_mantissa) < 1e-8 and 1 <= rounded_mantissa <= 9:
                return plain_number_label(value)
            return ""
        if decades <= 2.5:
            if any(abs(mantissa - item) < 1e-8 for item in (1, 2, 5)):
                return plain_number_label(value)
            return ""
        if abs(mantissa - 1) < 1e-8:
            return plain_number_label(value)
        return ""

    return ticker.FuncFormatter(formatter)


def log_decade_formatter(axis: ticker.Axis) -> ticker.FuncFormatter:
    def formatter(value: float, _position: int | None = None) -> str:
        if value <= 0 or not np.isfinite(value):
            return ""
        low, high = sorted(axis.get_view_interval())
        if low <= 0 or high <= 0:
            return ""
        if value < low * (1 - 1e-10) or value > high * (1 + 1e-10):
            return ""
        exponent = round(math.log10(value))
        if abs(value / (10**exponent) - 1.0) > 1e-8:
            return ""
        return rf"$10^{{{int(exponent)}}}$"

    return ticker.FuncFormatter(formatter)


def apply_tick_format(axis: ticker.Axis, mode: str | None, *, scale: str) -> None:
    if mode in (None, "auto"):
        return

    if mode == "decade":
        if scale == "log":
            axis.set_major_locator(ticker.LogLocator(base=10.0, subs=(1.0,)))
            axis.set_major_formatter(log_decade_formatter(axis))
            axis.set_minor_formatter(ticker.NullFormatter())
        return

    if mode == "plain":
        if scale == "log":
            formatter = log_plain_formatter(axis)
            axis.set_major_formatter(formatter)
            axis.set_minor_formatter(formatter)
        else:
            formatter = ticker.ScalarFormatter(useMathText=False)
            formatter.set_scientific(False)
            formatter.set_useOffset(False)
            axis.set_major_formatter(formatter)
        return

    if mode == "scientific":
        if scale == "log":
            axis.set_major_formatter(ticker.LogFormatterSciNotation())
        else:
            formatter = ticker.ScalarFormatter(useMathText=True)
            formatter.set_powerlimits((0, 0))
            axis.set_major_formatter(formatter)


def apply_axis_options(ax: plt.Axes, plot: dict[str, Any]) -> None:
    if plot.get("xscale") is not None:
        ax.set_xscale(str(plot["xscale"]))
    if plot.get("yscale") is not None:
        ax.set_yscale(str(plot["yscale"]))

    if plot.get("xlim") is not None:
        ax.set_xlim(*plot["xlim"])
    if plot.get("ylim") is not None:
        ax.set_ylim(*plot["ylim"])

    if plot.get("x_major") is not None:
        ax.xaxis.set_major_locator(ticker.MultipleLocator(float(plot["x_major"])))
    if plot.get("y_major") is not None:
        ax.yaxis.set_major_locator(ticker.MultipleLocator(float(plot["y_major"])))
    if plot.get("x_minor") is not None:
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(float(plot["x_minor"])))
    if plot.get("y_minor") is not None:
        ax.yaxis.set_minor_locator(ticker.MultipleLocator(float(plot["y_minor"])))
    if ax.get_xscale() == "log" and plot.get("x_minor") is None:
        ax.xaxis.set_minor_locator(ticker.LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1))
    if ax.get_yscale() == "log" and plot.get("y_minor") is None:
        ax.yaxis.set_minor_locator(ticker.LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1))
    if ax.get_xscale() == "log" and plot.get("x_log_ticks") == "decade":
        ax.xaxis.set_major_locator(ticker.LogLocator(base=10.0, subs=(1.0,)))
        ax.xaxis.set_minor_locator(ticker.LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1))
        ax.xaxis.set_minor_formatter(ticker.NullFormatter())
        plot = {**plot, "x_tick_format": "decade"}
    if ax.get_yscale() == "log" and plot.get("y_log_ticks") == "decade":
        ax.yaxis.set_major_locator(ticker.LogLocator(base=10.0, subs=(1.0,)))
        ax.yaxis.set_minor_locator(ticker.LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1))
        ax.yaxis.set_minor_formatter(ticker.NullFormatter())
        plot = {**plot, "y_tick_format": "decade"}

    apply_tick_format(ax.xaxis, plot.get("x_tick_format"), scale=ax.get_xscale())
    apply_tick_format(ax.yaxis, plot.get("y_tick_format"), scale=ax.get_yscale())


def right_y_axis_options(plot: dict[str, Any]) -> dict[str, Any]:
    options = {
        "yscale": plot.get("right_yscale"),
        "ylim": plot.get("right_ylim"),
        "y_major": plot.get("right_y_major"),
        "y_minor": plot.get("right_y_minor"),
        "y_tick_format": plot.get("right_y_tick_format"),
    }
    return {key: value for key, value in options.items() if value is not None}


def add_text_annotations(ax: plt.Axes, plot: dict[str, Any]) -> None:
    panel_label = plot.get("panel_label")
    if panel_label:
        ax.text(
            -0.20,
            1.08,
            str(panel_label),
            transform=ax.transAxes,
            fontsize=18,
            fontweight="bold",
            va="center",
            ha="left",
            clip_on=False,
        )

    for item in as_list(plot.get("text", plot.get("annotations"))):
        if not item:
            continue
        ax.text(
            item.get("x", 0.0),
            item.get("y", 0.0),
            item.get("text", ""),
            color=item.get("color", "black"),
            fontsize=item.get("fontsize", 10),
            fontweight=item.get("fontweight", "normal"),
            ha=item.get("ha", "left"),
            va=item.get("va", "center"),
            transform=ax.transAxes if item.get("coords") == "axes" else ax.transData,
            clip_on=False,
        )


def style_axis(
    ax: plt.Axes,
    *,
    categorical_x: bool = False,
    legend: bool = True,
    legend_loc: str = "best",
    legend_font_size: float = DEFAULT_LEGEND_FONT_SIZE,
    legend_title: str | None = None,
    legend_plot: dict[str, Any] | None = None,
) -> None:
    format_te_axis(ax, show_grid=False, tick_labelsize=SINGLE_TICK_LABEL_SIZE)
    if categorical_x:
        ax.xaxis.set_minor_locator(ticker.NullLocator())
    if legend:
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            legend_object = ax.legend(
                **legend_kwargs(
                    legend_plot,
                    fontsize=legend_font_size,
                    loc=legend_loc,
                    title=legend_title,
                )
            )
            apply_legend_style(legend_object, legend_plot)


def style_colored_y_axis(ax: plt.Axes, color: Any, *, side: str) -> None:
    is_left = side == "left"
    opposite_side = "right" if is_left else "left"
    ax.yaxis.set_label_position(side)
    ax.yaxis.set_ticks_position(side)
    ax.spines[side].set_visible(True)
    ax.spines[opposite_side].set_visible(False)
    tick_kwargs = {
        "axis": "y",
        "which": "both",
        "left": is_left,
        "right": not is_left,
        "labelleft": is_left,
        "labelright": not is_left,
    }
    if color:
        ax.yaxis.label.set_color(color)
        ax.spines[side].set_color(color)
        tick_kwargs["colors"] = color
    ax.tick_params(**tick_kwargs)


def next_style(style_iterators: tuple[Any, Any]) -> tuple[Any, Any]:
    colors, markers = style_iterators
    return next(colors), next(markers)


def recipe_subplot_aspect(plot: dict[str, Any]) -> str:
    return plot.get("subplot_aspect", DEFAULT_SUBPLOT_ASPECT)


def recipe_figure_size(plot: dict[str, Any], *, ncols: int = 1, nrows: int = 1) -> tuple[float, float]:
    if "figsize" in plot:
        return tuple(plot["figsize"])
    return figure_size_for_subplot_aspect(
        recipe_subplot_aspect(plot),
        ncols=ncols,
        nrows=nrows,
        subplot_height=DEFAULT_SUBPLOT_HEIGHT,
    )



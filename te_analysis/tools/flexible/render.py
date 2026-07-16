"""Plot renderers: line/scatter, multi-panel, bar, and dual-axis.

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
    optional_number,
    plain_number_label,
    unique_in_order,
)
from te_analysis.tools.flexible.normalize import (  # noqa: E402
    unique_properties_by_series_order,
)
from te_analysis.tools.flexible.style import (  # noqa: E402
    SINGLE_TICK_LABEL_SIZE,
    SUMMARY_TICK_LABEL_SIZE,
    add_text_annotations,
    apply_axis_options,
    apply_legend_style,
    legend_kwargs,
    next_style,
    optional_style,
    recipe_figure_size,
    recipe_subplot_aspect,
    right_y_axis_options,
    style_axis,
    style_colored_y_axis,
)


def plot_line_or_scatter(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
    *,
    scatter_only: bool = False,
) -> tuple[plt.Figure, plt.Axes]:
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))

    fig, ax = plt.subplots(figsize=recipe_figure_size(plot))
    style_iterators = get_style_cycles()

    property_names = unique_properties_by_series_order(normalized)
    for property_name in property_names:
        property_df = normalized[normalized["property"] == property_name]
        for group in unique_in_order(property_df["group"]):
            group_df = property_df[property_df["group"] == group].sort_values("x")
            default_color, default_marker = next_style(style_iterators)
            color = optional_style(group_df, "color") or default_color
            marker = optional_style(group_df, "marker") or default_marker
            legend_label = optional_style(group_df, "legend_label") or str(group)
            if len(property_names) > 1:
                legend_label = f"{group} - {metadata['property_labels'].get(property_name, property_name)}"
            marker_size = optional_number(optional_style(group_df, "marker_size")) or DEFAULT_MARKER_SIZE
            line_width = optional_number(optional_style(group_df, "line_width"))
            alpha = optional_number(optional_style(group_df, "alpha")) or 1.0
            linestyle = optional_style(group_df, "linestyle") or "-"

            if scatter_only:
                ax.scatter(
                    group_df["x"],
                    group_df["y"],
                    color=color,
                    marker=marker,
                    s=marker_size**2,
                    label=legend_label,
                    alpha=alpha,
                    zorder=3,
                )
            else:
                plot_kwargs = {}
                if line_width is not None:
                    plot_kwargs["linewidth"] = line_width
                ax.plot(
                    group_df["x"],
                    group_df["y"],
                    color=color,
                    marker=marker,
                    linestyle=linestyle,
                    markersize=marker_size,
                    alpha=alpha,
                    label=legend_label,
                    **plot_kwargs,
                )

    if plot.get("annotate"):
        for _, row in normalized.dropna(subset=["label"]).iterrows():
            ax.annotate(
                str(row["label"]),
                (row["x"], row["y"]),
                xytext=(3, 3),
                textcoords="offset points",
                fontsize=6.5,
                clip_on=False,
            )

    first_property = property_names[0]
    ax.set_xlabel(plot.get("xlabel", metadata["x_label"]))
    ax.set_ylabel(plot.get("ylabel", metadata["property_labels"].get(first_property, first_property)))
    if metadata.get("title") and plot.get("show_title", False):
        ax.set_title(metadata["title"])
    ax.margins(x=float(plot.get("x_margin", 0.04)), y=float(plot.get("y_margin", 0.08)))
    add_text_annotations(ax, plot)
    apply_subplot_aspect(ax, recipe_subplot_aspect(plot))

    legend_mode = plot.get("legend", "inside")
    if legend_mode == "outside":
        style_axis(ax, legend=False)
        apply_axis_options(ax, plot)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            legend_object = fig.legend(
                handles,
                labels,
                **legend_kwargs(
                    plot,
                    loc="upper center",
                    bbox_to_anchor=(0.5, 0.98),
                    ncol=min(len(labels), 4),
                ),
            )
            apply_legend_style(legend_object, plot)
        fig.tight_layout(rect=(0, 0, 1, 0.90))
    else:
        style_axis(
            ax,
            legend=legend_mode != "none",
            legend_loc=plot.get("legend_loc", "best"),
            legend_font_size=plot.get("legend_font_size", DEFAULT_LEGEND_FONT_SIZE),
            legend_title=plot.get("legend_title"),
            legend_plot=plot,
        )
        apply_axis_options(ax, plot)
        fig.tight_layout()
    return fig, ax


def plot_multi_panel(normalized: pd.DataFrame, metadata: dict[str, Any], recipe: dict[str, Any]) -> tuple[plt.Figure, np.ndarray]:
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "summary"))
    property_names = unique_properties_by_series_order(normalized)
    ncols = min(3, len(property_names))
    nrows = int(math.ceil(len(property_names) / ncols))

    fig, axes = plt.subplots(nrows, ncols, figsize=recipe_figure_size(plot, ncols=ncols, nrows=nrows), squeeze=False)
    group_names = unique_in_order(normalized["group"])
    style_by_group = {}
    style_iterators = get_style_cycles()
    for group in group_names:
        style_by_group[group] = next_style(style_iterators)

    for ax, property_name in zip(axes.ravel(), property_names):
        property_df = normalized[normalized["property"] == property_name]
        for group in group_names:
            group_df = property_df[property_df["group"] == group].sort_values("x")
            if group_df.empty:
                continue
            color, marker = style_by_group[group]
            ax.plot(
                group_df["x"],
                group_df["y"],
                color=color,
                marker=marker,
                markersize=4.2,
                label=group,
            )
        ax.set_xlabel(plot.get("xlabel", metadata["x_label"]))
        ax.set_ylabel(metadata["property_labels"].get(property_name, property_name))
        format_te_axis(ax, show_grid=False, tick_labelsize=SUMMARY_TICK_LABEL_SIZE)
        apply_axis_options(ax, plot)
        apply_subplot_aspect(ax, recipe_subplot_aspect(plot))

    for ax in axes.ravel()[len(property_names) :]:
        ax.axis("off")

    handles, labels = axes.ravel()[0].get_legend_handles_labels()
    if handles:
        legend_object = fig.legend(
            handles,
            labels,
            **legend_kwargs(
                plot,
                loc="upper center",
                bbox_to_anchor=(0.5, 0.985),
                ncol=min(len(labels), 4),
            ),
        )
        apply_legend_style(legend_object, plot)
        fig.tight_layout(rect=(0, 0, 1, 0.93))
    else:
        fig.tight_layout()
    return fig, axes


def aggregate_bar_values(values: pd.Series, mode: str) -> float:
    clean_values = pd.to_numeric(values, errors="coerce").dropna()
    if clean_values.empty:
        return np.nan
    if mode == "first":
        return float(clean_values.iloc[0])
    if mode == "sum":
        return float(clean_values.sum())
    if mode == "median":
        return float(clean_values.median())
    if mode == "min":
        return float(clean_values.min())
    if mode == "max":
        return float(clean_values.max())
    return float(clean_values.mean())


def bar_group_label(row: pd.Series, property_names: list[str], property_labels: dict[str, str]) -> str:
    legend_label = row.get("legend_label")
    group_label = str(legend_label) if pd.notna(legend_label) else str(row["group"])
    if len(property_names) <= 1:
        return group_label
    property_label = property_labels.get(str(row["property"]), str(row["property"]))
    return f"{group_label} - {property_label}"


def plot_bar(normalized: pd.DataFrame, metadata: dict[str, Any], recipe: dict[str, Any]) -> tuple[plt.Figure, plt.Axes]:
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))

    fig, ax = plt.subplots(figsize=recipe_figure_size(plot))
    property_names = unique_properties_by_series_order(normalized)
    property_labels = metadata.get("property_labels", {})
    working = normalized.copy()
    working["bar_group"] = working.apply(lambda row: bar_group_label(row, property_names, property_labels), axis=1)

    if metadata.get("categorical_x"):
        categories = metadata.get("x_categories") or unique_in_order(working["x_category"])
        category_labels = [str(category) for category in categories]
        category_mask = working["x_category"].astype(str)
    else:
        categories = unique_in_order(working["x"])
        category_labels = [plain_number_label(float(category)) for category in categories]
        category_mask = working["x"]

    group_names = unique_in_order(working["bar_group"])
    group_count = max(len(group_names), 1)
    positions = np.arange(len(categories), dtype=float)
    total_width = float(plot.get("bar_width", 0.72))
    single_width = total_width / group_count
    offsets = (np.arange(group_count) - (group_count - 1) / 2.0) * single_width
    aggregate_mode = str(plot.get("bar_aggregate", "mean"))
    style_iterators = get_style_cycles()
    bar_containers = []

    for group_index, group in enumerate(group_names):
        group_df = working[working["bar_group"] == group]
        default_color, _ = next_style(style_iterators)
        color = optional_style(group_df, "color") or default_color
        alpha = optional_number(optional_style(group_df, "alpha"))
        if alpha is None:
            alpha = float(plot.get("bar_alpha", 0.86))

        values = []
        for category in categories:
            if metadata.get("categorical_x"):
                category_df = group_df[category_mask.loc[group_df.index] == str(category)]
            else:
                category_df = group_df[category_mask.loc[group_df.index] == category]
            values.append(aggregate_bar_values(category_df["y"], aggregate_mode))

        container = ax.bar(
            positions + offsets[group_index],
            values,
            width=single_width * float(plot.get("bar_fill", 0.92)),
            color=color,
            alpha=alpha,
            label=group,
            edgecolor=plot.get("bar_edgecolor", "none"),
            linewidth=float(plot.get("bar_linewidth", 0.0)),
            zorder=3,
        )
        bar_containers.append((container, values))

    if plot.get("bar_labels", False):
        label_format = plot.get("bar_label_format", "{:.2g}")
        for container, values in bar_containers:
            for patch, value in zip(container.patches, values):
                if not np.isfinite(value):
                    continue
                label = label_format.format(value)
                offset = 3 if value >= 0 else -3
                va = "bottom" if value >= 0 else "top"
                ax.annotate(
                    label,
                    (patch.get_x() + patch.get_width() / 2.0, value),
                    xytext=(0, offset),
                    textcoords="offset points",
                    ha="center",
                    va=va,
                    fontsize=float(plot.get("bar_label_font_size", 7.5)),
                    clip_on=False,
                )

    ax.set_xticks(positions)
    xtick_rotation = plot.get("xtick_rotation", 0)
    xtick_ha = plot.get("xtick_ha") or ("right" if xtick_rotation else "center")
    ax.set_xticklabels(category_labels, rotation=xtick_rotation, ha=xtick_ha)
    ax.set_xlabel(plot.get("xlabel", metadata["x_label"]))
    first_property = property_names[0]
    ax.set_ylabel(plot.get("ylabel", property_labels.get(first_property, first_property)))
    if metadata.get("title") and plot.get("show_title", False):
        ax.set_title(metadata["title"])
    ax.margins(x=float(plot.get("x_margin", 0.04)), y=float(plot.get("y_margin", 0.10)))
    ax.xaxis.set_minor_locator(ticker.NullLocator())
    add_text_annotations(ax, plot)
    apply_subplot_aspect(ax, recipe_subplot_aspect(plot))

    legend_mode = plot.get("legend", "none" if len(group_names) <= 1 else "inside")
    if legend_mode == "outside":
        style_axis(ax, categorical_x=True, legend=False)
        apply_axis_options(ax, plot)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            legend_object = fig.legend(
                handles,
                labels,
                **legend_kwargs(
                    plot,
                    loc="upper center",
                    bbox_to_anchor=(0.5, 0.98),
                    ncol=min(len(labels), 4),
                ),
            )
            apply_legend_style(legend_object, plot)
        fig.tight_layout(rect=(0, 0, 1, 0.90))
    else:
        style_axis(
            ax,
            categorical_x=True,
            legend=legend_mode != "none",
            legend_loc=plot.get("legend_loc", "best"),
            legend_font_size=plot.get("legend_font_size", DEFAULT_LEGEND_FONT_SIZE),
            legend_title=plot.get("legend_title"),
            legend_plot=plot,
        )
        apply_axis_options(ax, plot)
        fig.tight_layout()
    return fig, ax


def plot_dual_axis(normalized: pd.DataFrame, metadata: dict[str, Any], recipe: dict[str, Any]) -> tuple[plt.Figure, tuple[plt.Axes, plt.Axes]]:
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    property_names = unique_properties_by_series_order(normalized)
    if len(property_names) != 2:
        raise ValueError("dual_axis plots need exactly two series")

    fig, ax_left = plt.subplots(figsize=recipe_figure_size(plot))
    ax_right = ax_left.twinx()

    left_property, right_property = property_names
    left_df = normalized[normalized["property"] == left_property].copy()
    right_df = normalized[normalized["property"] == right_property].copy()
    categories = plot.get("order") or unique_in_order(left_df["group"])
    positions = np.arange(len(categories))

    left_values = left_df.set_index("group").reindex(categories)["y"].to_numpy(dtype=float)
    right_values = right_df.set_index("group").reindex(categories)["y"].to_numpy(dtype=float)
    colors, markers = get_style_cycles()
    left_color, _ = next_style((colors, markers))
    right_color, right_marker = next_style((colors, markers))

    ax_left.bar(
        positions,
        left_values,
        color=left_color,
        alpha=0.78,
        width=0.58,
        label=metadata["property_labels"].get(left_property, left_property),
    )
    ax_right.plot(
        positions,
        right_values,
        color=right_color,
        marker=right_marker,
        markersize=DEFAULT_MARKER_SIZE,
        label=metadata["property_labels"].get(right_property, right_property),
    )

    ax_left.set_xticks(positions)
    xtick_rotation = plot.get("xtick_rotation", 0)
    xtick_ha = plot.get("xtick_ha") or ("right" if xtick_rotation else "center")
    ax_left.set_xticklabels(categories, rotation=xtick_rotation, ha=xtick_ha)
    ax_left.set_xlabel(plot.get("xlabel", metadata["x_label"]))
    ax_left.set_ylabel(metadata["property_labels"].get(left_property, left_property), color=left_color)
    ax_right.set_ylabel(metadata["property_labels"].get(right_property, right_property), color=right_color)

    format_te_axis(ax_left, show_grid=False, tick_labelsize=SINGLE_TICK_LABEL_SIZE)
    format_te_axis(ax_right, show_grid=False, tick_labelsize=SINGLE_TICK_LABEL_SIZE)
    apply_subplot_aspect(ax_left, recipe_subplot_aspect(plot))
    ax_left.xaxis.set_minor_locator(ticker.NullLocator())
    ax_right.xaxis.set_minor_locator(ticker.NullLocator())
    apply_axis_options(ax_left, plot)
    right_options = right_y_axis_options(plot)
    if right_options:
        apply_axis_options(ax_right, right_options)
    style_colored_y_axis(ax_left, left_color, side="left")
    style_colored_y_axis(ax_right, right_color, side="right")

    handles_left, labels_left = ax_left.get_legend_handles_labels()
    handles_right, labels_right = ax_right.get_legend_handles_labels()
    legend_object = ax_left.legend(
        handles_left + handles_right,
        labels_left + labels_right,
        **legend_kwargs(plot, loc=plot.get("legend_loc", "best")),
    )
    apply_legend_style(legend_object, plot)
    fig.tight_layout()
    return fig, (ax_left, ax_right)


def plot_dual_line(normalized: pd.DataFrame, metadata: dict[str, Any], recipe: dict[str, Any]) -> tuple[plt.Figure, tuple[plt.Axes, plt.Axes]]:
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    property_names = unique_properties_by_series_order(normalized)
    if len(property_names) != 2:
        raise ValueError("dual_line plots need exactly two series")

    fig, ax_left = plt.subplots(figsize=recipe_figure_size(plot))
    ax_right = ax_left.twinx()
    style_iterators = get_style_cycles()
    group_style = {}
    for group in unique_in_order(normalized["group"]):
        group_style[group] = next_style(style_iterators)

    left_property, right_property = property_names
    axes_by_property = [(ax_left, left_property, "left"), (ax_right, right_property, "right")]
    plotted_handles = []
    plotted_labels = []
    axis_colors = {}
    axis_color_mode = plot.get("axis_color_mode", "property")

    for ax, property_name, side in axes_by_property:
        property_df = normalized[normalized["property"] == property_name]
        for group in unique_in_order(property_df["group"]):
            group_df = property_df[property_df["group"] == group].sort_values("x")
            default_color, default_marker = group_style[group]
            color = optional_style(group_df, "color") or default_color
            marker = optional_style(group_df, "marker") or default_marker
            legend_label = optional_style(group_df, "legend_label") or metadata["property_labels"].get(property_name, property_name)
            marker_size = optional_number(optional_style(group_df, "marker_size")) or DEFAULT_MARKER_SIZE
            line_width = optional_number(optional_style(group_df, "line_width"))
            linestyle = optional_style(group_df, "linestyle") or "-"
            alpha = optional_number(optional_style(group_df, "alpha")) or 1.0
            plot_kwargs = {}
            if line_width is not None:
                plot_kwargs["linewidth"] = line_width
            line = ax.plot(
                group_df["x"],
                group_df["y"],
                color=color,
                marker=marker,
                linestyle=linestyle,
                markersize=marker_size,
                alpha=alpha,
                label=legend_label,
                **plot_kwargs,
            )[0]
            plotted_handles.append(line)
            plotted_labels.append(str(legend_label))
            axis_colors.setdefault(side, color)

    left_axis_color = axis_colors.get("left") if axis_color_mode != "plain" else None
    right_axis_color = axis_colors.get("right") if axis_color_mode != "plain" else None

    ax_left.set_xlabel(plot.get("xlabel", metadata["x_label"]))
    left_ylabel_kwargs = {"color": left_axis_color} if left_axis_color else {}
    right_ylabel_kwargs = {"color": right_axis_color} if right_axis_color else {}
    ax_left.set_ylabel(
        plot.get("ylabel", metadata["property_labels"].get(left_property, left_property)),
        **left_ylabel_kwargs,
    )
    ax_right.set_ylabel(
        plot.get("right_ylabel", metadata["property_labels"].get(right_property, right_property)),
        **right_ylabel_kwargs,
    )

    if metadata.get("title") and plot.get("show_title", False):
        ax_left.set_title(metadata["title"])
    ax_left.margins(x=float(plot.get("x_margin", 0.04)), y=float(plot.get("y_margin", 0.08)))
    ax_right.margins(y=float(plot.get("right_y_margin", plot.get("y_margin", 0.08))))
    add_text_annotations(ax_left, plot)

    format_te_axis(ax_left, show_grid=False, tick_labelsize=SINGLE_TICK_LABEL_SIZE)
    format_te_axis(ax_right, show_grid=False, tick_labelsize=SINGLE_TICK_LABEL_SIZE)
    apply_axis_options(ax_left, plot)

    right_options = right_y_axis_options(plot)
    if right_options:
        apply_axis_options(ax_right, right_options)
    if plot.get("xlim") is not None:
        ax_right.set_xlim(*plot["xlim"])
    if plot.get("xscale") is not None:
        ax_right.set_xscale(str(plot["xscale"]))

    style_colored_y_axis(ax_left, left_axis_color, side="left")
    style_colored_y_axis(ax_right, right_axis_color, side="right")
    apply_subplot_aspect(ax_left, recipe_subplot_aspect(plot))

    legend_mode = plot.get("legend", "inside")
    if legend_mode != "none" and plotted_handles:
        legend_handles = []
        legend_labels = []
        seen_labels = set()
        for handle, label in zip(plotted_handles, plotted_labels):
            if label in seen_labels:
                continue
            seen_labels.add(label)
            legend_handles.append(handle)
            legend_labels.append(label)
        if legend_mode == "outside":
            legend_object = fig.legend(
                legend_handles,
                legend_labels,
                **legend_kwargs(
                    plot,
                    loc="upper center",
                    bbox_to_anchor=(0.5, 0.98),
                    ncol=min(len(legend_labels), 4),
                ),
            )
            apply_legend_style(legend_object, plot)
            fig.tight_layout(rect=(0, 0, 1, 0.90))
        else:
            legend_object = ax_left.legend(
                legend_handles,
                legend_labels,
                **legend_kwargs(plot, loc=plot.get("legend_loc", "best")),
            )
            apply_legend_style(legend_object, plot)
            fig.tight_layout()
    else:
        fig.tight_layout()
    return fig, (ax_left, ax_right)


PLOTTERS = {
    "bar": plot_bar,
    "grouped_bar": plot_bar,
    "line": plot_line_or_scatter,
    "scatter": lambda normalized, metadata, recipe: plot_line_or_scatter(
        normalized,
        metadata,
        recipe,
        scatter_only=True,
    ),
    "multi_panel": plot_multi_panel,
    "dual_axis": plot_dual_axis,
    "dual_line": plot_dual_line,
}



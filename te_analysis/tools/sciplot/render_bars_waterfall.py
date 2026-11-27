"""Stacked bar, 100% stacked bar, and cumulative step waterfall renderers."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import ticker

from te_analysis.tools.plot import (
    DEFAULT_LEGEND_FONT_SIZE,
    apply_plot_style,
    apply_subplot_aspect,
    figure_top_below_legend,
    get_style_cycles,
)
from te_analysis.tools.colors import get_colors
from te_analysis.tools.sciplot.normalize import unique_properties_by_series_order
from te_analysis.tools.sciplot.overlays import apply_reference_guides
from te_analysis.tools.sciplot.style import (
    SINGLE_TICK_LABEL_SIZE,
    add_text_annotations,
    apply_axis_options,
    apply_legend_style,
    legend_kwargs,
    next_style,
    optional_style,
    place_flexible_inside_legend,
    recipe_figure_size,
    recipe_subplot_aspect,
    style_axis,
)
from te_analysis.tools.sciplot.util import (
    as_list,
    optional_bool,
    optional_number,
    plain_number_label,
    unique_in_order,
)


def _aggregate(values: pd.Series, mode: str) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    if mode == "first":
        return float(clean.iloc[0])
    if mode == "sum":
        return float(clean.sum())
    if mode == "median":
        return float(clean.median())
    if mode == "min":
        return float(clean.min())
    if mode == "max":
        return float(clean.max())
    return float(clean.mean())


def _bar_group_name(row: pd.Series, property_names: list[str], property_labels: dict[str, str]) -> str:
    legend_label = row.get("legend_label")
    group_label = str(legend_label) if pd.notna(legend_label) else str(row["group"])
    if len(property_names) <= 1:
        return group_label
    prop_label = property_labels.get(str(row["property"]), str(row["property"]))
    if group_label == prop_label:
        return group_label
    return f"{group_label} - {prop_label}"


def plot_stacked_bar(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
    *,
    percent: bool = False,
) -> tuple[plt.Figure, plt.Axes]:
    """Render vertical stacked bars or 100%-normalized stacked bars."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))

    fig, ax = plt.subplots(figsize=recipe_figure_size(plot))
    property_names = unique_properties_by_series_order(normalized)
    property_labels = metadata.get("property_labels", {})
    working = normalized.copy()
    working["bar_group"] = working.apply(
        lambda row: _bar_group_name(row, property_names, property_labels),
        axis=1,
    )

    if metadata.get("categorical_x"):
        categories = metadata.get("x_categories") or unique_in_order(working["x_category"])
        category_labels = [str(cat) for cat in categories]
        category_col = working["x_category"].astype(str)
    else:
        categories = unique_in_order(working["x"])
        category_labels = [plain_number_label(float(cat)) for cat in categories]
        category_col = working["x"].astype(str)

    group_names = unique_in_order(working["bar_group"])
    positions = np.arange(len(categories), dtype=float)
    bar_width = float(plot.get("bar_width", 0.58))
    aggregate_mode = str(plot.get("bar_aggregate", "sum"))
    style_iterators = get_style_cycles(plot.get("color_set"), len(group_names))

    matrix = np.zeros((len(group_names), len(categories)), dtype=float)
    group_dfs: list[pd.DataFrame] = []
    for g_idx, group in enumerate(group_names):
        gdf = working[working["bar_group"] == group]
        group_dfs.append(gdf)
        for c_idx, category in enumerate(categories):
            cdf = gdf[category_col.loc[gdf.index] == str(category)]
            matrix[g_idx, c_idx] = _aggregate(cdf["y"], aggregate_mode)

    if percent:
        totals = np.sum(np.abs(matrix), axis=0)
        nonzero = totals > 0
        matrix[:, nonzero] = matrix[:, nonzero] / totals[nonzero] * 100.0

    pos_bottom = np.zeros(len(categories), dtype=float)
    neg_bottom = np.zeros(len(categories), dtype=float)
    label_format = plot.get("bar_label_format", "{:.1f}%" if percent else "{:.2g}")
    show_segment_labels = optional_bool(plot.get("bar_labels"), default=False)

    for g_idx, (group, gdf) in enumerate(zip(group_names, group_dfs)):
        default_color, _ = next_style(style_iterators)
        color = optional_style(gdf, "color") or default_color
        alpha = optional_number(optional_style(gdf, "alpha"))
        if alpha is None:
            alpha = float(plot.get("bar_alpha", 0.88))

        vals = matrix[g_idx]
        bottoms = np.where(vals >= 0, pos_bottom, neg_bottom)
        container = ax.bar(
            positions,
            vals,
            width=bar_width,
            bottom=bottoms,
            color=color,
            alpha=alpha,
            label=group,
            edgecolor=plot.get("bar_edgecolor", "white"),
            linewidth=float(plot.get("bar_linewidth", 0.9)),
            zorder=3,
        )
        pos_bottom = np.where(vals >= 0, pos_bottom + vals, pos_bottom)
        neg_bottom = np.where(vals < 0, neg_bottom + vals, neg_bottom)

        if show_segment_labels:
            span = max(np.max(pos_bottom) - np.min(neg_bottom), 1e-9)
            for patch, val, bot in zip(container.patches, vals, bottoms):
                if abs(val) < 0.06 * span:
                    continue
                ax.text(
                    patch.get_x() + patch.get_width() / 2.0,
                    bot + val / 2.0,
                    label_format.format(val),
                    ha="center",
                    va="center",
                    fontsize=float(plot.get("bar_label_font_size", 11.0)),
                    color=plot.get("segment_label_color", "white"),
                    fontweight="bold",
                    zorder=4,
                )

    if optional_bool(plot.get("stack_total_labels"), default=False) and not percent:
        total_fmt = plot.get("stack_total_format", "{:.2f}")
        for pos, top_val in zip(positions, pos_bottom):
            ax.annotate(
                total_fmt.format(top_val),
                (pos, top_val),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=float(plot.get("bar_label_font_size", 11.5)),
                fontweight="bold",
                clip_on=False,
            )

    ax.set_xticks(positions)
    xtick_rotation = plot.get("xtick_rotation", 0)
    xtick_ha = plot.get("xtick_ha") or ("right" if xtick_rotation else "center")
    xtick_fs = SINGLE_TICK_LABEL_SIZE * 0.88 if len(categories) >= 5 and max((len(c) for c in category_labels), default=0) >= 6 else SINGLE_TICK_LABEL_SIZE
    ax.set_xticklabels(category_labels, rotation=xtick_rotation, ha=xtick_ha, fontsize=xtick_fs)
    ax.set_xlabel(plot.get("xlabel", metadata["x_label"]))
    default_ylabel = "Contribution (%)" if percent else property_labels.get(property_names[0], property_names[0])
    ax.set_ylabel(plot.get("ylabel", default_ylabel))
    if percent and plot.get("ylim") is None:
        ax.set_ylim(0, 100)
    else:
        ax.margins(x=float(plot.get("x_margin", 0.08)), y=float(plot.get("y_margin", 0.12)))

    ax.xaxis.set_minor_locator(ticker.NullLocator())
    apply_reference_guides(ax, plot)
    add_text_annotations(ax, plot)
    apply_subplot_aspect(ax, recipe_subplot_aspect(plot))

    legend_mode = plot.get("legend", "inside")
    style_axis(ax, categorical_x=True, legend=False)
    apply_axis_options(ax, plot)
    if legend_mode == "outside":
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            legend_obj = fig.legend(
                handles,
                labels,
                **legend_kwargs(plot, loc="upper center", bbox_to_anchor=(0.5, 0.98), ncol=min(len(labels), 4)),
            )
            apply_legend_style(legend_obj, plot)
        fig.tight_layout(rect=(0, 0, 1, figure_top_below_legend(fig)))
    else:
        if legend_mode != "none":
            place_flexible_inside_legend(
                ax,
                plot,
                default_loc="upper center" if percent else "best",
                ylim_override=(0.0, None) if (percent and plot.get("ylim") is None) else plot.get("ylim"),
                cap_ticks_at=100.0 if (percent and plot.get("ylim") is None) else None,
            )
        fig.tight_layout()
    return fig, ax


def plot_waterfall(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
) -> tuple[plt.Figure, plt.Axes]:
    """Render a step-by-step waterfall chart showing cumulative contributions."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    fig, ax = plt.subplots(figsize=recipe_figure_size(plot))

    property_names = unique_properties_by_series_order(normalized)
    property_labels = metadata.get("property_labels", {})
    first_prop = property_names[0]
    working = normalized[normalized["property"] == first_prop].copy()

    if metadata.get("categorical_x") or working["x_category"].notna().any():
        categories = metadata.get("x_categories") or unique_in_order(working["x_category"])
        key_col = "x_category"
    else:
        categories = unique_in_order(working["x"].map(plain_number_label))
        working["x_category"] = working["x"].map(plain_number_label)
        key_col = "x_category"

    total_names = {str(item).strip().lower() for item in as_list(plot.get("total_categories"))}
    default_total_tokens = {"total", "final", "net", "optimized", "overall", "sum", "总计", "最终"}

    raw_values: list[float] = []
    step_kinds: list[str] = []
    for idx, cat in enumerate(categories):
        cdf = working[working[key_col].astype(str) == str(cat)]
        val = _aggregate(cdf["y"], str(plot.get("bar_aggregate", "first")))
        raw_values.append(val)

        explicit_cond = str(optional_style(cdf, "condition") or optional_style(cdf, "role") or "").strip().lower()
        cat_lower = str(cat).strip().lower()
        if explicit_cond in {"start", "base", "baseline", "initial"}:
            step_kinds.append("start")
        elif explicit_cond in {"total", "subtotal", "final"} or cat_lower in total_names or (
            idx == len(categories) - 1 and any(tok in cat_lower for tok in default_total_tokens)
        ):
            step_kinds.append("total")
        elif idx == 0 and optional_bool(plot.get("first_is_baseline"), default=True):
            step_kinds.append("start")
        else:
            step_kinds.append("delta")

    waterfall_mode = str(plot.get("waterfall_mode", "delta")).strip().lower()
    bottoms = np.zeros(len(categories), dtype=float)
    heights = np.zeros(len(categories), dtype=float)
    tops = np.zeros(len(categories), dtype=float)
    display_deltas = np.zeros(len(categories), dtype=float)

    running = 0.0
    for idx, (val, skind) in enumerate(zip(raw_values, step_kinds)):
        if waterfall_mode == "levels":
            if idx == 0 or skind in {"start", "total"}:
                bottoms[idx] = 0.0
                heights[idx] = val
                running = val
                display_deltas[idx] = val
            else:
                delta = val - running
                bottoms[idx] = running
                heights[idx] = delta
                running = val
                display_deltas[idx] = delta
            tops[idx] = running
        else:
            if skind == "start":
                bottoms[idx] = 0.0
                heights[idx] = val
                running = val
                display_deltas[idx] = val
            elif skind == "total":
                total_val = running if (not np.isfinite(val) or abs(val) < 1e-12) else val
                bottoms[idx] = 0.0
                heights[idx] = total_val
                running = total_val
                display_deltas[idx] = total_val
            else:
                bottoms[idx] = running
                heights[idx] = val
                running = running + val
                display_deltas[idx] = val
            tops[idx] = running

    palette = get_colors(plot.get("color_set"), 4)
    start_color = plot.get("start_color", palette[0])
    pos_color = plot.get("increase_color", palette[2] if len(palette) > 2 else "#00A087")
    neg_color = plot.get("decrease_color", palette[1] if len(palette) > 1 else "#E64B35")
    total_color = plot.get("total_color", palette[3] if len(palette) > 3 else "#3C5488")

    bar_colors = []
    for skind, h_val in zip(step_kinds, heights):
        if skind == "start":
            bar_colors.append(start_color)
        elif skind == "total":
            bar_colors.append(total_color)
        elif h_val >= 0:
            bar_colors.append(pos_color)
        else:
            bar_colors.append(neg_color)

    positions = np.arange(len(categories), dtype=float)
    bar_width = float(plot.get("bar_width", 0.56))
    ax.bar(
        positions,
        heights,
        bottom=bottoms,
        width=bar_width,
        color=bar_colors,
        alpha=float(plot.get("bar_alpha", 0.88)),
        edgecolor=plot.get("bar_edgecolor", "black"),
        linewidth=float(plot.get("bar_linewidth", 0.9)),
        zorder=3,
    )

    if optional_bool(plot.get("connectors"), default=True):
        for idx in range(len(categories) - 1):
            y_conn = tops[idx]
            ax.plot(
                [positions[idx] + bar_width / 2.0, positions[idx + 1] - bar_width / 2.0],
                [y_conn, y_conn],
                color=plot.get("connector_color", "#555555"),
                linestyle="--",
                linewidth=1.2,
                zorder=2,
            )

    if optional_bool(plot.get("bar_labels"), default=True):
        delta_fmt = plot.get("delta_label_format", "{:+.2f}")
        total_fmt = plot.get("bar_label_format", "{:.2f}")
        for pos, bot, h_val, d_val, skind in zip(positions, bottoms, heights, display_deltas, step_kinds):
            y_anchor = bot + h_val
            offset_pts = 4 if h_val >= 0 else -4
            va = "bottom" if h_val >= 0 else "top"
            text = total_fmt.format(d_val) if skind in {"start", "total"} else delta_fmt.format(d_val)
            ax.annotate(
                text,
                (pos, y_anchor),
                xytext=(0, offset_pts),
                textcoords="offset points",
                ha="center",
                va=va,
                fontsize=float(plot.get("bar_label_font_size", 11.5)),
                fontweight="bold" if skind in {"start", "total"} else "normal",
                clip_on=False,
            )

    ax.axhline(0.0, color="black", linewidth=0.9, alpha=0.5, zorder=1.5)
    ax.set_xticks(positions)
    cat_strs = [str(cat) for cat in categories]
    has_multiline = any("\n" in item for item in cat_strs)
    default_rot = 0 if has_multiline else (22 if len(cat_strs) >= 5 and max((len(c) for c in cat_strs), default=0) > 8 else 0)
    xtick_rotation = plot.get("xtick_rotation", default_rot)
    xtick_ha = plot.get("xtick_ha") or ("right" if xtick_rotation else "center")
    max_line_len = max((max((len(part) for part in item.split("\n")), default=0) for item in cat_strs), default=0)
    if has_multiline and len(cat_strs) >= 5 and max_line_len >= 10:
        xtick_fs = SINGLE_TICK_LABEL_SIZE * 0.84
    elif has_multiline and len(cat_strs) >= 5:
        xtick_fs = SINGLE_TICK_LABEL_SIZE * 0.90
    elif len(cat_strs) >= 5:
        xtick_fs = SINGLE_TICK_LABEL_SIZE * 0.92
    else:
        xtick_fs = SINGLE_TICK_LABEL_SIZE
    ax.set_xlabel(plot.get("xlabel", metadata["x_label"]), labelpad=10)
    ax.set_ylabel(plot.get("ylabel", property_labels.get(first_prop, first_prop)))
    ax.margins(x=float(plot.get("x_margin", 0.08)), y=float(plot.get("y_margin", 0.16)))
    ax.xaxis.set_minor_locator(ticker.NullLocator())

    apply_reference_guides(ax, plot)
    add_text_annotations(ax, plot)
    style_axis(ax, categorical_x=True, legend=False)
    ax.set_xticklabels(cat_strs, rotation=xtick_rotation, ha=xtick_ha, fontsize=xtick_fs)
    apply_axis_options(ax, plot)
    apply_subplot_aspect(ax, recipe_subplot_aspect(plot))
    fig.tight_layout()
    return fig, ax

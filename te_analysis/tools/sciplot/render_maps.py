"""2D field and multi-dimensional map renderers: heatmap, contour, bubble, and ternary."""

from __future__ import annotations

import math
from typing import Any

import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
import pandas as pd
from matplotlib import ticker
from matplotlib.patches import Polygon

from te_analysis.tools.plot import (
    DEFAULT_AXIS_LABEL_SIZE,
    DEFAULT_AXIS_LINE_WIDTH,
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_MARKER_SIZE,
    DEFAULT_TICK_LABEL_SIZE,
    DEFAULT_TICK_LINE_WIDTH,
    apply_plot_style,
    apply_subplot_aspect,
    figure_top_below_legend,
    format_te_axis,
    get_style_cycles,
)
from te_analysis.tools.colors import DEFAULT_FIELD_CMAP, resolve_cmap
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
    optional_bool,
    optional_number,
    plain_number_label,
    unique_in_order,
)


def _cmap_is_light(cmap_obj: Any) -> bool:
    r, g, b, _ = cmap_obj(0.5)
    return (0.299 * r + 0.587 * g + 0.114 * b) > 0.55


def _style_colorbar(cbar: Any, label: str | None) -> None:
    cbar.locator = ticker.MaxNLocator(nbins=6)
    cbar.update_ticks()
    cbar.outline.set_linewidth(DEFAULT_AXIS_LINE_WIDTH)
    cbar.ax.tick_params(
        labelsize=SINGLE_TICK_LABEL_SIZE * 0.92,
        width=DEFAULT_TICK_LINE_WIDTH,
        length=4.0,
        direction="in",
    )
    if label:
        cbar.set_label(label, fontsize=DEFAULT_AXIS_LABEL_SIZE * 0.94, labelpad=6)


def _z_limits(z_vals: np.ndarray, plot: dict[str, Any]) -> tuple[float | None, float | None]:
    zlim = plot.get("zlim")
    vmin = optional_number(plot.get("vmin"))
    vmax = optional_number(plot.get("vmax"))
    if isinstance(zlim, (list, tuple)) and len(zlim) == 2:
        if zlim[0] is not None:
            vmin = float(zlim[0])
        if zlim[1] is not None:
            vmax = float(zlim[1])
    return vmin, vmax


def plot_heatmap(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
) -> tuple[plt.Figure, plt.Axes]:
    """Render a 2D categorical or numeric grid heatmap with colorbar and optional cell annotations."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    fig, ax = plt.subplots(figsize=recipe_figure_size(plot))

    if "z" not in normalized.columns:
        raise ValueError("heatmap plots require a z column (use --z <column> or plot.z in recipe)")

    working = normalized.dropna(subset=["z"]).copy()
    x_cats = unique_in_order(working["x_category"] if working["x_category"].notna().any() else working["x"].map(plain_number_label))
    if "y_category" in working.columns and working["y_category"].notna().any():
        y_cats = unique_in_order(working["y_category"])
        y_key = working["y_category"].astype(str)
    else:
        y_cats = unique_in_order(working["y"].map(plain_number_label))
        y_key = working["y"].map(plain_number_label)

    x_key = working["x_category"].astype(str) if working["x_category"].notna().any() else working["x"].map(plain_number_label)
    working["__xk"] = x_key
    working["__yk"] = y_key

    pivoted = working.pivot_table(index="__yk", columns="__xk", values="z", aggfunc="mean")
    pivoted = pivoted.reindex(index=y_cats, columns=x_cats)
    grid = pivoted.to_numpy(dtype=float)

    vmin, vmax = _z_limits(grid[np.isfinite(grid)], plot)
    cmap_obj = resolve_cmap(plot.get("cmap", DEFAULT_FIELD_CMAP))
    im = ax.imshow(
        grid,
        origin="lower",
        aspect="auto",
        cmap=cmap_obj,
        vmin=vmin,
        vmax=vmax,
    )

    if optional_bool(plot.get("annotate_cells"), default=grid.size <= 64):
        cell_fmt = plot.get("cell_format", "{:.2f}")
        for r_idx in range(grid.shape[0]):
            for c_idx in range(grid.shape[1]):
                val = grid[r_idx, c_idx]
                if not np.isfinite(val):
                    continue
                rgba = im.cmap(im.norm(val))
                lum = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
                txt_color = "#1F242B" if lum > 0.48 else "white"
                ax.text(
                    c_idx,
                    r_idx,
                    cell_fmt.format(val),
                    ha="center",
                    va="center",
                    color=plot.get("cell_text_color", txt_color),
                    fontsize=float(plot.get("cell_font_size", 12.0)),
                )

    ax.set_xticks(np.arange(len(x_cats)))
    xtick_rotation = plot.get("xtick_rotation", 0)
    ax.set_xticklabels(x_cats, rotation=xtick_rotation, ha="right" if xtick_rotation else "center")
    ax.set_yticks(np.arange(len(y_cats)))
    ax.set_yticklabels(y_cats)
    ax.set_xlabel(plot.get("xlabel", metadata["x_label"]))
    first_prop = next(iter(metadata["property_labels"]), "y")
    ax.set_ylabel(plot.get("ylabel", metadata["property_labels"].get(first_prop, first_prop)))

    format_te_axis(ax, show_grid=False, tick_labelsize=SINGLE_TICK_LABEL_SIZE)
    ax.xaxis.set_minor_locator(ticker.NullLocator())
    ax.yaxis.set_minor_locator(ticker.NullLocator())
    ax.tick_params(axis="both", which="major", direction="out", length=5)
    apply_subplot_aspect(ax, recipe_subplot_aspect(plot))

    cbar = fig.colorbar(im, ax=ax, pad=0.03, fraction=0.048)
    _style_colorbar(cbar, plot.get("zlabel") or plot.get("cbar_label") or metadata.get("z_label"))
    add_text_annotations(ax, plot)
    fig.tight_layout()
    return fig, ax


def plot_contour(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
) -> tuple[plt.Figure, plt.Axes]:
    """Render a 2D filled contour phase/property map from regular or scattered (x, y, z) data."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    fig, ax = plt.subplots(figsize=recipe_figure_size(plot))

    if "z" not in normalized.columns:
        raise ValueError("contour plots require a z column (use --z <column> or plot.z in recipe)")

    working = normalized.dropna(subset=["x", "y", "z"]).copy()
    x = working["x"].to_numpy(dtype=float)
    y = working["y"].to_numpy(dtype=float)
    z = working["z"].to_numpy(dtype=float)

    levels_count = int(plot.get("levels", 14))
    vmin, vmax = _z_limits(z, plot)
    z_min = float(vmin) if vmin is not None else float(np.nanmin(z))
    z_max = float(vmax) if vmax is not None else float(np.nanmax(z))
    if math.isclose(z_min, z_max):
        z_max = z_min + 1.0
    level_edges = np.linspace(z_min, z_max, levels_count + 1)
    cmap_obj = resolve_cmap(plot.get("cmap", DEFAULT_FIELD_CMAP))
    default_line_color = "#55606E" if _cmap_is_light(cmap_obj) else "white"

    ux = np.unique(x)
    uy = np.unique(y)
    is_regular_grid = (len(ux) >= 2 and len(uy) >= 2 and len(ux) * len(uy) == len(working))
    raw_min, raw_max = float(np.nanmin(z)), float(np.nanmax(z))
    clips_low = z_min > raw_min + 1e-9
    clips_high = z_max < raw_max - 1e-9
    extend_mode = "both" if (clips_low and clips_high) else ("min" if clips_low else ("max" if clips_high else "neither"))

    if is_regular_grid:
        pivoted = working.pivot_table(index="y", columns="x", values="z", aggfunc="mean").reindex(index=uy, columns=ux)
        X, Y = np.meshgrid(ux, uy)
        Z = pivoted.to_numpy(dtype=float)
        cf = ax.contourf(X, Y, Z, levels=level_edges, cmap=cmap_obj, extend=extend_mode)
        if optional_bool(plot.get("contour_lines"), default=True):
            line_levels = np.linspace(z_min, z_max, min(levels_count, 7))
            cs = ax.contour(X, Y, Z, levels=line_levels, colors=plot.get("contour_line_color", default_line_color), linewidths=0.8, alpha=0.55)
            if optional_bool(plot.get("contour_labels"), default=False):
                ax.clabel(cs, inline=True, fontsize=10.5, fmt=plot.get("contour_label_format", "%.2g"))
    else:
        triang = mtri.Triangulation(x, y)
        cf = ax.tricontourf(triang, z, levels=level_edges, cmap=cmap_obj, extend=extend_mode)
        if optional_bool(plot.get("contour_lines"), default=True):
            line_levels = np.linspace(z_min, z_max, min(levels_count, 7))
            cs = ax.tricontour(triang, z, levels=line_levels, colors=plot.get("contour_line_color", default_line_color), linewidths=0.8, alpha=0.55)
            if optional_bool(plot.get("contour_labels"), default=False):
                ax.clabel(cs, inline=True, fontsize=10.5, fmt=plot.get("contour_label_format", "%.2g"))

    if optional_bool(plot.get("show_points"), default=not is_regular_grid):
        ax.scatter(
            x,
            y,
            s=float(plot.get("point_size", 28.0)),
            facecolors=plot.get("point_facecolor", "white"),
            edgecolors=plot.get("point_edgecolor", "black"),
            linewidths=0.9,
            alpha=0.85,
            zorder=4,
        )

    first_prop = next(iter(metadata["property_labels"]), "y")
    ax.set_xlabel(plot.get("xlabel", metadata["x_label"]))
    ax.set_ylabel(plot.get("ylabel", metadata["property_labels"].get(first_prop, first_prop)))
    format_te_axis(ax, show_grid=False, tick_labelsize=SINGLE_TICK_LABEL_SIZE)
    apply_reference_guides(ax, plot)
    apply_axis_options(ax, plot)
    apply_subplot_aspect(ax, recipe_subplot_aspect(plot))

    cbar = fig.colorbar(cf, ax=ax, pad=0.055, fraction=0.048)
    _style_colorbar(cbar, plot.get("zlabel") or plot.get("cbar_label") or metadata.get("z_label"))
    add_text_annotations(ax, plot)
    fig.tight_layout()
    return fig, ax


def plot_bubble(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
) -> tuple[plt.Figure, plt.Axes]:
    """Render a multi-dimensional scatter/bubble plot with optional z-colormap and size scaling."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    fig, ax = plt.subplots(figsize=recipe_figure_size(plot))

    working = normalized.dropna(subset=["x", "y"]).copy()
    has_z = "z" in working.columns and working["z"].notna().any()
    has_size = "size" in working.columns and working["size"].notna().any()

    size_min, size_max = plot.get("size_range", [70.0, 520.0])
    if has_size:
        raw_s = pd.to_numeric(working["size"], errors="coerce").to_numpy(dtype=float)
        s_lo, s_hi = np.nanmin(raw_s), np.nanmax(raw_s)
        if math.isclose(s_lo, s_hi):
            areas = np.full(len(working), 0.5 * (size_min + size_max))
        else:
            norm_s = np.clip((raw_s - s_lo) / (s_hi - s_lo), 0.0, 1.0)
            areas = size_min + norm_s * (size_max - size_min)
    else:
        areas = np.full(len(working), (DEFAULT_MARKER_SIZE * 1.15) ** 2)
    working["__area"] = areas

    mappable = None
    if has_z:
        z_vals = pd.to_numeric(working["z"], errors="coerce").to_numpy(dtype=float)
        vmin, vmax = _z_limits(z_vals, plot)
        cmap_obj = resolve_cmap(plot.get("cmap", DEFAULT_FIELD_CMAP))
        groups = unique_in_order(working["group"])
        _, marker_cycle = get_style_cycles(plot.get("color_set"), len(groups))
        for group in groups:
            gdf = working[working["group"] == group]
            marker = optional_style(gdf, "marker") or (next(marker_cycle) if len(groups) > 1 else "o")
            mappable = ax.scatter(
                gdf["x"],
                gdf["y"],
                c=pd.to_numeric(gdf["z"], errors="coerce"),
                s=gdf["__area"],
                marker=marker,
                cmap=cmap_obj,
                vmin=vmin,
                vmax=vmax,
                alpha=float(plot.get("alpha", 0.90)),
                edgecolors=plot.get("edgecolor", "#2B3038"),
                linewidths=float(plot.get("edgewidth", 0.9)),
                label=optional_style(gdf, "legend_label") or str(group),
                zorder=3,
            )
    else:
        groups = unique_in_order(working["group"])
        style_iters = get_style_cycles(plot.get("color_set"), len(groups))
        for group in groups:
            gdf = working[working["group"] == group]
            default_color, default_marker = next_style(style_iters)
            color = optional_style(gdf, "color") or default_color
            marker = optional_style(gdf, "marker") or default_marker
            ax.scatter(
                gdf["x"],
                gdf["y"],
                s=gdf["__area"],
                color=color,
                marker=marker,
                alpha=float(plot.get("alpha", 0.82)),
                edgecolors=plot.get("edgecolor", "black"),
                linewidths=float(plot.get("edgewidth", 0.9)),
                label=optional_style(gdf, "legend_label") or str(group),
                zorder=3,
            )

    if plot.get("annotate") or ("label" in working.columns and working["label"].notna().any()):
        x_vals_all = working["x"].to_numpy(dtype=float)
        x_lo_ref, x_hi_ref = plot.get("xlim") or (float(np.nanmin(x_vals_all)), float(np.nanmax(x_vals_all)))
        x_threshold = x_lo_ref + 0.68 * (x_hi_ref - x_lo_ref)
        for _, row in working.dropna(subset=["label"]).iterrows():
            if not str(row["label"]).strip():
                continue
            r_pt = math.sqrt(float(row["__area"])) * 0.52 + 4.5
            place_left = float(row["x"]) > x_threshold
            ax.annotate(
                str(row["label"]),
                (row["x"], row["y"]),
                xytext=(-r_pt if place_left else r_pt, 3),
                textcoords="offset points",
                ha="right" if place_left else "left",
                va="center",
                fontsize=float(plot.get("annotation_font_size", 11.5)),
                clip_on=False,
                zorder=5,
            )

    first_prop = next(iter(metadata["property_labels"]), "y")
    ax.set_xlabel(plot.get("xlabel", metadata["x_label"]))
    ax.set_ylabel(plot.get("ylabel", metadata["property_labels"].get(first_prop, first_prop)))
    ax.margins(x=float(plot.get("x_margin", 0.07)), y=float(plot.get("y_margin", 0.10)))
    apply_reference_guides(ax, plot)
    add_text_annotations(ax, plot)
    apply_subplot_aspect(ax, recipe_subplot_aspect(plot))

    legend_mode = plot.get("legend", "none" if (has_z and len(unique_in_order(working["group"])) <= 1) else "inside")
    style_axis(ax, legend=False)
    apply_axis_options(ax, plot)
    if legend_mode != "none":
        if legend_mode == "outside":
            handles, labels = ax.get_legend_handles_labels()
            if handles:
                leg = fig.legend(
                    handles,
                    labels,
                    **legend_kwargs(plot, loc="upper center", bbox_to_anchor=(0.5, 0.98), ncol=min(len(labels), 4)),
                )
                apply_legend_style(leg, plot)
        else:
            place_flexible_inside_legend(ax, plot, allow_xlim_expand=True)

    if mappable is not None:
        cbar = fig.colorbar(mappable, ax=ax, pad=0.03, fraction=0.048)
        _style_colorbar(cbar, plot.get("zlabel") or plot.get("cbar_label") or metadata.get("z_label"))
    if fig.legends:
        fig.tight_layout(rect=(0, 0, 1, figure_top_below_legend(fig)))
    else:
        fig.tight_layout()
    return fig, ax


def _ternary_xy(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project (a=bottom-left, b=bottom-right, c=top-apex) barycentric coordinates onto 2D."""
    total = a + b + c
    safe = np.where(total > 0, total, 1.0)
    an, bn, cn = a / safe, b / safe, c / safe
    tx = bn + 0.5 * cn
    ty = (math.sqrt(3.0) / 2.0) * cn
    return tx, ty


def _draw_ternary_frame(ax: plt.Axes, labels: tuple[str, str, str], steps: int = 5) -> Polygon:
    h = math.sqrt(3.0) / 2.0
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, h]])
    border = Polygon(vertices, closed=True, fill=False, edgecolor="black", linewidth=DEFAULT_AXIS_LINE_WIDTH, zorder=5)
    ax.add_patch(border)

    fractions = np.linspace(0.0, 1.0, steps + 1)
    tick_len = 0.022
    tick_fs = SINGLE_TICK_LABEL_SIZE * 0.78

    for frac in fractions[1:-1]:
        # Constant c (horizontal lines parallel to bottom)
        p1 = _ternary_xy(np.array([1 - frac]), np.array([0.0]), np.array([frac]))
        p2 = _ternary_xy(np.array([0.0]), np.array([1 - frac]), np.array([frac]))
        ax.plot([p1[0][0], p2[0][0]], [p1[1][0], p2[1][0]], color="#BFBFBF", lw=0.8, ls="--", zorder=1.5)

        # Constant b (lines parallel to left edge)
        q1 = _ternary_xy(np.array([1 - frac]), np.array([frac]), np.array([0.0]))
        q2 = _ternary_xy(np.array([0.0]), np.array([frac]), np.array([1 - frac]))
        ax.plot([q1[0][0], q2[0][0]], [q1[1][0], q2[1][0]], color="#BFBFBF", lw=0.8, ls="--", zorder=1.5)

        # Constant a (lines parallel to right edge)
        r1 = _ternary_xy(np.array([frac]), np.array([1 - frac]), np.array([0.0]))
        r2 = _ternary_xy(np.array([frac]), np.array([0.0]), np.array([1 - frac]))
        ax.plot([r1[0][0], r2[0][0]], [r1[1][0], r2[1][0]], color="#BFBFBF", lw=0.8, ls="--", zorder=1.5)

    for frac in fractions[1:-1]:
        pct_text = f"{int(round(frac * 100))}"
        # Bottom edge ticks -> b fraction (20..80)
        bx, by = frac, 0.0
        ax.plot([bx, bx - 0.5 * tick_len], [by, by - h * tick_len], color="black", lw=DEFAULT_TICK_LINE_WIDTH)
        ax.text(bx, by - 0.045, pct_text, ha="center", va="top", fontsize=tick_fs)

        # Right edge ticks -> c fraction (20..80)
        rx, ry = 1.0 - 0.5 * frac, h * frac
        ax.plot([rx, rx + tick_len], [ry, ry], color="black", lw=DEFAULT_TICK_LINE_WIDTH)
        ax.text(rx + 0.036, ry, pct_text, ha="left", va="center", fontsize=tick_fs)

        # Left edge ticks -> a fraction (80..20)
        lx, ly = 0.5 * (1.0 - frac), h * (1.0 - frac)
        ax.plot([lx, lx - 0.5 * tick_len], [ly, ly + h * tick_len], color="black", lw=DEFAULT_TICK_LINE_WIDTH)
        ax.text(lx - 0.036, ly, pct_text, ha="right", va="center", fontsize=tick_fs)

    label_a, label_b, label_c = labels
    lbl_fs = DEFAULT_AXIS_LABEL_SIZE * 0.90
    ax.text(-0.02, -0.055, label_a, ha="center", va="top", fontsize=lbl_fs, fontweight="bold")
    ax.text(1.02, -0.055, label_b, ha="center", va="top", fontsize=lbl_fs, fontweight="bold")
    ax.text(0.50, h + 0.048, label_c, ha="center", va="bottom", fontsize=lbl_fs, fontweight="bold")

    ax.set_xlim(-0.18, 1.18)
    ax.set_ylim(-0.16, h + 0.13)
    ax.set_aspect("equal")
    ax.axis("off")
    return border


def plot_ternary(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
) -> tuple[plt.Figure, plt.Axes]:
    """Render an equilateral ternary composition diagram (scatter or contour heatmap)."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    figsize = tuple(plot["figsize"]) if "figsize" in plot else (6.6, 5.8)
    fig, ax = plt.subplots(figsize=figsize)

    for req in ("a", "b", "c"):
        if req not in normalized.columns:
            raise ValueError("ternary plots require a, b, and c composition columns (use --a, --b, --c)")

    working = normalized.dropna(subset=["a", "b", "c"]).copy()
    a = pd.to_numeric(working["a"], errors="coerce").to_numpy(dtype=float)
    b = pd.to_numeric(working["b"], errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(working["c"], errors="coerce").to_numpy(dtype=float)
    tx, ty = _ternary_xy(a, b, c)
    working["__tx"] = tx
    working["__ty"] = ty

    ternary_labels = (
        plot.get("alabel") or metadata.get("a_label", "A (%)"),
        plot.get("blabel") or metadata.get("b_label", "B (%)"),
        plot.get("clabel") or metadata.get("c_label", "C (%)"),
    )
    clip_poly = _draw_ternary_frame(ax, ternary_labels, steps=int(plot.get("ternary_steps", 5)))

    has_z = "z" in working.columns and working["z"].notna().any()
    mappable = None
    if has_z:
        z = pd.to_numeric(working["z"], errors="coerce").to_numpy(dtype=float)
        vmin, vmax = _z_limits(z, plot)
        cmap_obj = resolve_cmap(plot.get("cmap", DEFAULT_FIELD_CMAP))
        if len(working) >= 4 and optional_bool(plot.get("ternary_contour"), default=True):
            try:
                triang = mtri.Triangulation(tx, ty)
                levels = np.linspace(
                    float(vmin) if vmin is not None else float(np.nanmin(z)),
                    float(vmax) if vmax is not None else float(np.nanmax(z)),
                    int(plot.get("levels", 14)) + 1,
                )
                cf = ax.tricontourf(triang, z, levels=levels, cmap=cmap_obj, extend="neither", zorder=2)
                for coll in getattr(cf, "collections", []):
                    coll.set_clip_path(clip_poly)
                mappable = cf
            except RuntimeError:
                mappable = None

        sc = ax.scatter(
            tx,
            ty,
            c=z,
            cmap=cmap_obj,
            vmin=vmin,
            vmax=vmax,
            s=(DEFAULT_MARKER_SIZE * 1.02) ** 2,
            edgecolors="#2B3038",
            linewidths=0.85,
            zorder=6,
        )
        if mappable is None:
            mappable = sc
    else:
        groups = unique_in_order(working["group"])
        style_iters = get_style_cycles(plot.get("color_set"), len(groups))
        for group in groups:
            gdf = working[working["group"] == group]
            default_color, default_marker = next_style(style_iters)
            color = optional_style(gdf, "color") or default_color
            marker = optional_style(gdf, "marker") or default_marker
            ax.scatter(
                gdf["__tx"],
                gdf["__ty"],
                color=color,
                marker=marker,
                s=(DEFAULT_MARKER_SIZE * 1.05) ** 2,
                edgecolors="black",
                linewidths=0.9,
                label=optional_style(gdf, "legend_label") or str(group),
                zorder=6,
            )

        legend_mode = plot.get("legend", "inside" if len(groups) > 1 else "none")
        if legend_mode != "none":
            handles, labels = ax.get_legend_handles_labels()
            if handles:
                ternary_fs = float(plot.get("legend_font_size") or min(DEFAULT_LEGEND_FONT_SIZE, 10.2))
                leg = ax.legend(
                    handles,
                    labels,
                    **legend_kwargs(
                        plot,
                        fontsize=ternary_fs,
                        loc=plot.get("legend_loc", "upper right"),
                        bbox_to_anchor=plot.get("legend_bbox", (0.98, 0.98)),
                    ),
                )
                apply_legend_style(leg, plot)

    if mappable is not None:
        cbar = fig.colorbar(mappable, ax=ax, pad=0.055, fraction=0.046, shrink=0.82)
        _style_colorbar(cbar, plot.get("zlabel") or plot.get("cbar_label") or metadata.get("z_label"))

    add_text_annotations(ax, plot)
    fig.tight_layout()
    return fig, ax

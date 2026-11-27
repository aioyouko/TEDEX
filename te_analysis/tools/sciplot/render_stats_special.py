"""Statistical and specialized scientific renderers:
boxplot, violin, histogram, parity, arrhenius, broken_y, fit_residual, and radar.
"""

from __future__ import annotations

import math
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import ticker
from scipy import stats
from scipy.constants import e as ELECTRON_CHARGE, k as BOLTZMANN_K

from te_analysis.tools.plot import (
    DEFAULT_AXIS_LABEL_SIZE,
    DEFAULT_AXIS_LINE_WIDTH,
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_LINE_WIDTH,
    DEFAULT_MARKER_SIZE,
    DEFAULT_TICK_LABEL_SIZE,
    apply_plot_style,
    apply_subplot_aspect,
    figure_top_below_legend,
    format_te_axis,
    get_style_cycles,
)
from te_analysis.tools.colors import get_colors
from te_analysis.tools.sciplot.normalize import unique_properties_by_series_order
from te_analysis.tools.sciplot.overlays import apply_reference_guides, draw_uncertainty
from te_analysis.tools.sciplot.style import (
    SINGLE_TICK_LABEL_SIZE,
    add_text_annotations,
    apply_axis_options,
    apply_legend_style,
    effective_legend_label,
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


def plot_distribution(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
    *,
    kind: str = "boxplot",
) -> tuple[plt.Figure, plt.Axes]:
    """Render publication boxplots or violin plots with optional jittered points."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    fig, ax = plt.subplots(figsize=recipe_figure_size(plot))

    property_names = unique_properties_by_series_order(normalized)
    property_labels = metadata.get("property_labels", {})
    first_prop = property_names[0]
    working = normalized.dropna(subset=["y"]).copy()

    if metadata.get("categorical_x") or working["x_category"].notna().any():
        categories = metadata.get("x_categories") or unique_in_order(working["x_category"])
        key_series = working["x_category"].astype(str)
    else:
        categories = unique_in_order(working["group"])
        key_series = working["group"].astype(str)

    datasets = [
        pd.to_numeric(working.loc[key_series == str(cat), "y"], errors="coerce").dropna().to_numpy(dtype=float)
        for cat in categories
    ]
    positions = np.arange(len(categories), dtype=float)
    colors = get_colors(plot.get("color_set"), max(len(categories), 1))
    width = float(plot.get("box_width", 0.52))

    if kind == "violin":
        nonempty_pos = [pos for pos, arr in zip(positions, datasets) if len(arr) >= 2]
        nonempty_data = [arr for arr in datasets if len(arr) >= 2]
        if nonempty_data:
            parts = ax.violinplot(
                nonempty_data,
                positions=nonempty_pos,
                widths=width * 1.15,
                showmeans=False,
                showmedians=True,
                showextrema=True,
            )
            for idx, body in enumerate(parts["bodies"]):
                body.set_facecolor(colors[idx % len(colors)])
                body.set_edgecolor("black")
                body.set_linewidth(1.2)
                body.set_alpha(float(plot.get("violin_alpha", 0.68)))
            for part_name in ("cbars", "cmins", "cmaxes", "cmedians"):
                if part_name in parts:
                    parts[part_name].set_edgecolor("black")
                    parts[part_name].set_linewidth(1.4)
    else:
        bp = ax.boxplot(
            datasets,
            positions=positions,
            widths=width,
            patch_artist=True,
            showfliers=not optional_bool(plot.get("show_points"), default=True),
            medianprops={"color": "black", "linewidth": 1.8},
            boxprops={"linewidth": 1.3, "edgecolor": "black"},
            whiskerprops={"linewidth": 1.3, "color": "black"},
            capprops={"linewidth": 1.3, "color": "black"},
            zorder=3,
        )
        for idx, patch in enumerate(bp["boxes"]):
            patch.set_facecolor(colors[idx % len(colors)])
            patch.set_alpha(float(plot.get("box_alpha", 0.72)))

    if optional_bool(plot.get("show_points"), default=True):
        rng = np.random.default_rng(42)
        jitter_span = width * 0.24
        for idx, (pos, arr) in enumerate(zip(positions, datasets)):
            if len(arr) == 0:
                continue
            offsets = rng.uniform(-jitter_span, jitter_span, size=len(arr))
            ax.scatter(
                pos + offsets,
                arr,
                s=float(plot.get("point_size", 34.0)),
                facecolors="white",
                edgecolors=colors[idx % len(colors)],
                linewidths=1.25,
                alpha=0.88,
                zorder=4,
            )

    if optional_bool(plot.get("show_mean"), default=True):
        means = [float(np.mean(arr)) if len(arr) else np.nan for arr in datasets]
        ax.scatter(
            positions,
            means,
            marker="D",
            s=42.0,
            color="black",
            zorder=5,
            label="Mean",
        )

    ax.set_xticks(positions)
    xtick_rotation = plot.get("xtick_rotation", 0)
    ax.set_xticklabels([str(cat) for cat in categories], rotation=xtick_rotation, ha="right" if xtick_rotation else "center")
    ax.set_xlabel(plot.get("xlabel", metadata["x_label"]))
    ax.set_ylabel(plot.get("ylabel", property_labels.get(first_prop, first_prop)))
    ax.margins(x=float(plot.get("x_margin", 0.08)), y=float(plot.get("y_margin", 0.12)))
    ax.xaxis.set_minor_locator(ticker.NullLocator())

    apply_reference_guides(ax, plot)
    add_text_annotations(ax, plot)
    style_axis(ax, categorical_x=True, legend=False)
    apply_axis_options(ax, plot)
    apply_subplot_aspect(ax, recipe_subplot_aspect(plot))
    fig.tight_layout()
    return fig, ax


def plot_histogram(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
) -> tuple[plt.Figure, plt.Axes]:
    """Render 1D histogram(s) with optional normal, lognormal, or KDE distribution curve."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    fig, ax = plt.subplots(figsize=recipe_figure_size(plot))

    working = normalized.dropna(subset=["y"]).copy()
    groups = unique_in_order(working["group"])
    colors = get_colors(plot.get("color_set"), max(len(groups), 1))
    bins = int(plot.get("bins", 16))
    fit_dist = str(plot.get("fit_dist", "none")).strip().lower()
    density = optional_bool(plot.get("density"), default=fit_dist not in {"", "none"})

    stats_lines: list[str] = []
    for idx, group in enumerate(groups):
        gdf = working[working["group"] == group]
        vals = pd.to_numeric(gdf["y"], errors="coerce").dropna().to_numpy(dtype=float)
        if len(vals) == 0:
            continue
        color = optional_style(gdf, "color") or colors[idx % len(colors)]
        label = effective_legend_label(gdf, working, group)
        alpha = float(plot.get("hist_alpha", 0.52 if len(groups) > 1 else 0.72))

        counts, edges, _ = ax.hist(
            vals,
            bins=bins,
            density=density,
            color=color,
            alpha=alpha,
            edgecolor="black",
            linewidth=1.0,
            label=label,
            zorder=3,
        )

        if fit_dist not in {"", "none"} and len(vals) >= 3:
            x_grid = np.linspace(max(edges[0] * 0.9, 1e-9) if fit_dist == "lognormal" else edges[0], edges[-1] * 1.05, 240)
            bin_width = float(edges[1] - edges[0])
            scale_factor = 1.0 if density else len(vals) * bin_width
            if fit_dist == "normal":
                mu, sigma = stats.norm.fit(vals)
                pdf = stats.norm.pdf(x_grid, loc=mu, scale=max(sigma, 1e-12)) * scale_factor
                ax.plot(x_grid, pdf, color=color, linewidth=DEFAULT_LINE_WIDTH, zorder=4)
                stats_lines.append(rf"{label}: $\mu={mu:.3g}$, $\sigma={sigma:.3g}$")
            elif fit_dist == "lognormal":
                pos_vals = vals[vals > 0]
                if len(pos_vals) >= 3:
                    shape, _, scale = stats.lognorm.fit(pos_vals, floc=0)
                    pdf = stats.lognorm.pdf(x_grid, shape, loc=0, scale=scale) * scale_factor
                    ax.plot(x_grid, pdf, color=color, linewidth=DEFAULT_LINE_WIDTH, zorder=4)
                    stats_lines.append(rf"{label}: $d_{{50}}={scale:.3g}$, $\sigma_{{\mathrm{{g}}}}={math.exp(shape):.2f}$")
            elif fit_dist == "kde":
                kde = stats.gaussian_kde(vals)
                ax.plot(x_grid, kde(x_grid) * scale_factor, color=color, linewidth=DEFAULT_LINE_WIDTH, zorder=4)

    if stats_lines and optional_bool(plot.get("show_fit_stats"), default=True):
        ax.text(
            0.96,
            0.94,
            "\n".join(stats_lines),
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=float(plot.get("stats_font_size", 11.5)),
            bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.9, "pad": 4.0},
            zorder=6,
        )

    first_prop = next(iter(metadata["property_labels"]), "y")
    ax.set_xlabel(plot.get("xlabel") or metadata["property_labels"].get(first_prop, metadata["x_label"]))
    ax.set_ylabel(plot.get("ylabel", "Probability Density" if density else "Count"))
    ax.margins(x=float(plot.get("x_margin", 0.05)), y=float(plot.get("y_margin", 0.12)))

    apply_reference_guides(ax, plot)
    add_text_annotations(ax, plot)
    legend_mode = plot.get("legend", "inside" if len(groups) > 1 else "none")
    style_axis(ax, legend=False)
    apply_axis_options(ax, plot)
    apply_subplot_aspect(ax, recipe_subplot_aspect(plot))
    if legend_mode == "inside":
        place_flexible_inside_legend(ax, plot, default_loc="upper left")
    elif legend_mode == "outside":
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            leg = fig.legend(handles, labels, **legend_kwargs(plot, loc="upper center", bbox_to_anchor=(0.5, 0.98), ncol=min(len(labels), 4)))
            apply_legend_style(leg, plot)
            fig.tight_layout(rect=(0, 0, 1, figure_top_below_legend(fig)))
            return fig, ax
    fig.tight_layout()
    return fig, ax


def plot_parity(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
) -> tuple[plt.Figure, plt.Axes]:
    """Render a predicted-vs-experimental parity plot with 1:1 diagonal, error cone, and R²/MAE/RMSE."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    aspect = plot.get("subplot_aspect", "1:1")
    plot_with_aspect = {**plot, "subplot_aspect": aspect}
    fig, ax = plt.subplots(figsize=recipe_figure_size(plot_with_aspect))

    working = normalized.dropna(subset=["x", "y"]).copy()
    groups = unique_in_order(working["group"])
    style_iters = get_style_cycles(plot.get("color_set"), len(groups))

    for group in groups:
        gdf = working[working["group"] == group]
        default_color, default_marker = next_style(style_iters)
        color = optional_style(gdf, "color") or default_color
        marker = optional_style(gdf, "marker") or default_marker
        x_vals = gdf["x"].to_numpy(dtype=float)
        y_vals = gdf["y"].to_numpy(dtype=float)
        draw_uncertainty(ax, x_vals, y_vals, gdf, plot, color=color, zorder=2.5)
        ax.scatter(
            x_vals,
            y_vals,
            color=color,
            marker=marker,
            s=(optional_number(optional_style(gdf, "marker_size")) or DEFAULT_MARKER_SIZE) ** 2,
            alpha=float(plot.get("alpha", 0.85)),
            edgecolors="black",
            linewidths=0.8,
            label=effective_legend_label(gdf, working, group),
            zorder=4,
        )

    all_x = working["x"].to_numpy(dtype=float)
    all_y = working["y"].to_numpy(dtype=float)
    combined = np.concatenate([all_x, all_y])
    lo, hi = float(np.nanmin(combined)), float(np.nanmax(combined))
    pad = 0.06 * (hi - lo if hi > lo else 1.0)
    bounds = plot.get("xlim") or plot.get("ylim") or [lo - pad, hi + pad]
    grid_line = np.linspace(bounds[0], bounds[1], 200)
    ax.plot(grid_line, grid_line, color="#333333", linestyle="--", linewidth=1.6, zorder=2, label=None)

    band_pct = optional_number(plot.get("parity_band_pct"))
    band_abs = optional_number(plot.get("parity_band_abs"))
    if band_pct is not None and band_pct > 0:
        frac = band_pct / 100.0
        ax.fill_between(grid_line, grid_line * (1.0 - frac), grid_line * (1.0 + frac), color="#8491B4", alpha=0.16, zorder=1.2)
    elif band_abs is not None and band_abs > 0:
        ax.fill_between(grid_line, grid_line - band_abs, grid_line + band_abs, color="#8491B4", alpha=0.16, zorder=1.2)

    if optional_bool(plot.get("show_metrics"), default=True) and len(all_x) >= 2:
        residuals = all_y - all_x
        mae = float(np.mean(np.abs(residuals)))
        rmse = float(np.sqrt(np.mean(residuals ** 2)))
        ss_tot = float(np.sum((all_y - np.mean(all_y)) ** 2))
        r2 = 1.0 - float(np.sum(residuals ** 2)) / ss_tot if ss_tot > 0 else np.nan
        metrics_text = f"$R^2 = {r2:.3f}$\nMAE = {mae:.3g}\nRMSE = {rmse:.3g}"
        ax.text(
            0.05,
            0.95,
            metrics_text,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=float(plot.get("metrics_font_size", 11.5)),
            bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.92, "pad": 4.5},
            zorder=6,
        )

    first_prop = next(iter(metadata["property_labels"]), "y")
    ax.set_xlabel(plot.get("xlabel", metadata["x_label"]))
    ax.set_ylabel(plot.get("ylabel", metadata["property_labels"].get(first_prop, first_prop)))
    ax.set_xlim(bounds[0], bounds[1])
    ax.set_ylim(bounds[0], bounds[1])

    add_text_annotations(ax, plot)
    legend_mode = plot.get("legend", "inside" if len(groups) > 1 else "none")
    style_axis(ax, legend=False)
    apply_axis_options(ax, plot)
    apply_subplot_aspect(ax, aspect)
    if legend_mode == "inside":
        place_flexible_inside_legend(ax, plot, default_loc="lower right", ylim_override=(bounds[0], bounds[1]))
    elif legend_mode == "outside":
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            leg = fig.legend(handles, labels, **legend_kwargs(plot, loc="upper center", bbox_to_anchor=(0.5, 0.98), ncol=min(len(labels), 4)))
            apply_legend_style(leg, plot)
            fig.tight_layout(rect=(0, 0, 1, figure_top_below_legend(fig)))
            return fig, ax
    fig.tight_layout()
    return fig, ax


def plot_arrhenius(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
) -> tuple[plt.Figure, plt.Axes]:
    """Render an Arrhenius plot (1000/T vs y on log scale) with secondary T(K) top axis and E_a fit."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    fig, ax = plt.subplots(figsize=recipe_figure_size(plot))

    working = normalized.dropna(subset=["x", "y"]).copy()
    x_is_inv_t = optional_bool(plot.get("arrhenius_x_is_inv_t"), default=False)
    if x_is_inv_t:
        working["__inv_t"] = working["x"].astype(float)
    else:
        working = working[working["x"] > 0].copy()
        working["__inv_t"] = 1000.0 / working["x"].astype(float)
    working = working[working["y"] > 0].copy()

    groups = unique_in_order(working["group"])
    style_iters = get_style_cycles(plot.get("color_set"), len(groups))
    do_fit = optional_bool(plot.get("fit_arrhenius"), default=True)
    fit_range = plot.get("fit_range")  # Optional [T_min, T_max] in K or [invT_min, invT_max]
    ea_lines: list[str] = []

    for group in groups:
        gdf = working[working["group"] == group].sort_values("__inv_t")
        default_color, default_marker = next_style(style_iters)
        color = optional_style(gdf, "color") or default_color
        marker = optional_style(gdf, "marker") or default_marker
        label = effective_legend_label(gdf, working, group)

        inv_t = gdf["__inv_t"].to_numpy(dtype=float)
        y_vals = gdf["y"].to_numpy(dtype=float)
        ax.scatter(
            inv_t,
            y_vals,
            color=color,
            marker=marker,
            s=(optional_number(optional_style(gdf, "marker_size")) or DEFAULT_MARKER_SIZE) ** 2,
            label=label,
            zorder=4,
        )

        if do_fit and len(inv_t) >= 2:
            mask = np.ones(len(inv_t), dtype=bool)
            if isinstance(fit_range, (list, tuple)) and len(fit_range) == 2:
                lo_r, hi_r = sorted([float(fit_range[0]), float(fit_range[1])])
                if not x_is_inv_t and hi_r > 25.0:
                    t_kelvin = gdf["x"].to_numpy(dtype=float)
                    mask = (t_kelvin >= lo_r) & (t_kelvin <= hi_r)
                else:
                    mask = (inv_t >= lo_r) & (inv_t <= hi_r)
            if np.sum(mask) >= 2:
                x_fit = inv_t[mask]
                ln_y = np.log(y_vals[mask])
                slope, intercept, r_val, _, _ = stats.linregress(x_fit, ln_y)
                # ln(y) = intercept + slope * (1000 / T)  =>  E_a = -slope * 1000 * k_B
                ea_ev = -slope * 1000.0 * BOLTZMANN_K / ELECTRON_CHARGE
                x_line = np.linspace(float(np.min(x_fit)), float(np.max(x_fit)), 100)
                ax.plot(x_line, np.exp(intercept + slope * x_line), color=color, linestyle="--", linewidth=DEFAULT_LINE_WIDTH * 0.9, zorder=3)
                unit_text = f"{ea_ev * 1000.0:.1f} meV" if abs(ea_ev) < 0.25 else f"{ea_ev:.3f} eV"
                ea_lines.append(f"{label}: $E_{{\\mathrm{{a}}}}$ = {unit_text} ($R^2 = {r_val**2:.3f}$)")

    ax.set_yscale(plot.get("yscale", "log"))
    first_prop = next(iter(metadata["property_labels"]), "y")
    ax.set_xlabel(plot.get("xlabel", r"$1000 / T$ (K$^{-1}$)"))
    ax.set_ylabel(plot.get("ylabel", metadata["property_labels"].get(first_prop, first_prop)))
    ax.margins(x=float(plot.get("x_margin", 0.06)), y=float(plot.get("y_margin", 0.14)))

    if ea_lines and optional_bool(plot.get("show_fit_stats"), default=True):
        ax.text(
            0.04,
            0.06,
            "\n".join(ea_lines),
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=float(plot.get("stats_font_size", 11.5)),
            bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.92, "pad": 4.0},
            zorder=6,
        )

    legend_mode = plot.get("legend", "inside")
    style_axis(ax, legend=False)
    apply_axis_options(ax, plot)
    apply_subplot_aspect(ax, recipe_subplot_aspect(plot))

    if optional_bool(plot.get("top_temperature_axis"), default=True):
        inv_lo, inv_hi = sorted(ax.get_xlim())
        if inv_lo > 0:
            t_candidates = [1200, 1000, 900, 800, 700, 600, 500, 450, 400, 350, 300, 250, 200, 150, 100]
            min_inv_gap = 0.135 * (inv_hi - inv_lo)
            chosen_t: list[int] = []
            for t in t_candidates:
                inv_pos = 1000.0 / t
                if inv_lo + 0.02 * (inv_hi - inv_lo) <= inv_pos <= inv_hi - 0.02 * (inv_hi - inv_lo):
                    if not chosen_t or abs(inv_pos - 1000.0 / chosen_t[-1]) >= min_inv_gap:
                        chosen_t.append(t)
            if len(chosen_t) >= 2:
                secax = ax.secondary_xaxis(
                    "top",
                    functions=(lambda u: np.where(u > 0, 1000.0 / u, np.nan), lambda t: np.where(t > 0, 1000.0 / t, np.nan)),
                )
                secax.set_xticks(chosen_t)
                secax.set_xticklabels([str(t) for t in chosen_t], fontsize=SINGLE_TICK_LABEL_SIZE * 0.92)
                secax.xaxis.set_minor_locator(ticker.NullLocator())
                secax.tick_params(axis="x", direction="in", length=5.0, width=DEFAULT_AXIS_LINE_WIDTH, pad=4.5)
                secax.set_xlabel(r"$T$ (K)", fontsize=DEFAULT_AXIS_LABEL_SIZE * 0.94, labelpad=6)
                secax.spines["top"].set_visible(False)

    add_text_annotations(ax, plot)
    if legend_mode == "inside":
        place_flexible_inside_legend(ax, plot, default_loc="upper right")
    elif legend_mode == "outside":
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            leg = fig.legend(handles, labels, **legend_kwargs(plot, loc="upper center", bbox_to_anchor=(0.5, 0.98), ncol=min(len(labels), 4)))
            apply_legend_style(leg, plot)
            fig.tight_layout(rect=(0, 0, 1, figure_top_below_legend(fig)))
            return fig, ax
    fig.tight_layout()
    return fig, ax


def plot_broken_y(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
) -> tuple[plt.Figure, tuple[plt.Axes, plt.Axes]]:
    """Render a split-y-axis plot (top outlier range + bottom main range) with diagonal break marks."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))

    ylim_bottom = plot.get("ylim") or plot.get("ylim_bottom")
    ylim_top = plot.get("ylim_top") or plot.get("right_ylim")
    if not ylim_bottom or not ylim_top:
        y_all = normalized["y"].dropna().to_numpy(dtype=float)
        q75 = float(np.percentile(y_all, 75))
        y_min, y_max = float(np.min(y_all)), float(np.max(y_all))
        ylim_bottom = ylim_bottom or [min(0.0, y_min), q75 * 1.15]
        ylim_top = ylim_top or [y_max * 0.82, y_max * 1.08]

    ratios = plot.get("height_ratios", [1.0, 1.45])
    fig, (ax_top, ax_bot) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=recipe_figure_size(plot),
        gridspec_kw={"height_ratios": ratios, "hspace": 0.08},
    )

    subkind = str(plot.get("broken_subkind", "line")).strip().lower()
    groups = unique_in_order(normalized["group"])
    style_iters = get_style_cycles(plot.get("color_set"), len(groups))

    if subkind == "bar":
        categories = metadata.get("x_categories") or unique_in_order(normalized["x_category"])
        positions = np.arange(len(categories), dtype=float)
        width = float(plot.get("bar_width", 0.62)) / max(len(groups), 1)
        offsets = (np.arange(len(groups)) - (len(groups) - 1) / 2.0) * width
        for g_idx, group in enumerate(groups):
            gdf = normalized[normalized["group"] == group]
            color, _ = next_style(style_iters)
            color = optional_style(gdf, "color") or color
            vals = [
                float(gdf.loc[gdf["x_category"].astype(str) == str(cat), "y"].mean())
                for cat in categories
            ]
            for target_ax in (ax_top, ax_bot):
                target_ax.bar(positions + offsets[g_idx], vals, width=width * 0.92, color=color, label=group)
        ax_bot.set_xticks(positions)
        ax_bot.set_xticklabels([str(cat) for cat in categories])
    else:
        for group in groups:
            gdf = normalized[normalized["group"] == group].sort_values("x")
            color, marker = next_style(style_iters)
            color = optional_style(gdf, "color") or color
            marker = optional_style(gdf, "marker") or marker
            label = effective_legend_label(gdf, normalized, group)
            for target_ax in (ax_top, ax_bot):
                if subkind == "scatter":
                    target_ax.scatter(gdf["x"], gdf["y"], color=color, marker=marker, s=DEFAULT_MARKER_SIZE ** 2, label=label)
                else:
                    target_ax.plot(gdf["x"], gdf["y"], color=color, marker=marker, markersize=DEFAULT_MARKER_SIZE, label=label)

    for target_ax in (ax_top, ax_bot):
        format_te_axis(target_ax, show_grid=False, tick_labelsize=SINGLE_TICK_LABEL_SIZE)
        if plot.get("xlim") is not None:
            target_ax.set_xlim(*plot["xlim"])

    ax_top.set_ylim(*ylim_top)
    ax_bot.set_ylim(*ylim_bottom)
    ax_top.spines["bottom"].set_visible(False)
    ax_bot.spines["top"].set_visible(False)
    ax_top.tick_params(axis="x", which="both", bottom=False, labelbottom=False)

    d_x, d_y = 0.014, 0.028
    slash_kw = {"color": "black", "clip_on": False, "linewidth": DEFAULT_AXIS_LINE_WIDTH}
    ax_top.plot((-d_x, +d_x), (-d_y, +d_y), transform=ax_top.transAxes, **slash_kw)
    ax_top.plot((1 - d_x, 1 + d_x), (-d_y, +d_y), transform=ax_top.transAxes, **slash_kw)
    ax_bot.plot((-d_x, +d_x), (1 - d_y, 1 + d_y), transform=ax_bot.transAxes, **slash_kw)
    ax_bot.plot((1 - d_x, 1 + d_x), (1 - d_y, 1 + d_y), transform=ax_bot.transAxes, **slash_kw)

    first_prop = next(iter(metadata["property_labels"]), "y")
    ax_bot.set_xlabel(plot.get("xlabel", metadata["x_label"]))
    ax_bot.set_ylabel(plot.get("ylabel", metadata["property_labels"].get(first_prop, first_prop)))
    ax_bot.yaxis.set_label_coords(-0.16, 0.90)

    legend_mode = plot.get("legend", "inside")
    if legend_mode != "none":
        handles, labels = ax_top.get_legend_handles_labels()
        if handles:
            if legend_mode == "outside":
                leg = fig.legend(handles, labels, **legend_kwargs(plot, loc="upper center", bbox_to_anchor=(0.5, 0.99), ncol=min(len(labels), 4)))
                apply_legend_style(leg, plot)
            else:
                user_locked_top = plot.get("ylim_top") is not None or plot.get("right_ylim") is not None
                place_flexible_inside_legend(
                    ax_top,
                    plot,
                    handles=handles,
                    labels=labels,
                    default_loc="upper right",
                    ylim_override=(ylim_top[0], ylim_top[1] if user_locked_top else None),
                )

    fig.subplots_adjust(left=0.20, right=0.96, bottom=0.15, top=min(0.92, figure_top_below_legend(fig)) if fig.legends else 0.95)
    return fig, (ax_top, ax_bot)


def plot_fit_residual(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
) -> tuple[plt.Figure, tuple[plt.Axes, plt.Axes]]:
    """Render a two-panel fit + residual plot (Observed scatter, Calculated line, components, and difference)."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))

    fig, (ax_main, ax_res) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=tuple(plot.get("figsize", (6.8, 5.9))),
        gridspec_kw={"height_ratios": plot.get("height_ratios", [3.3, 1.0]), "hspace": 0.07},
    )

    series_orders = sorted(normalized["series_order"].dropna().unique())
    palette = get_colors(plot.get("color_set"), max(len(series_orders) + 2, 4))

    obs_df: pd.DataFrame | None = None
    calc_df: pd.DataFrame | None = None
    res_df: pd.DataFrame | None = None
    components: list[pd.DataFrame] = []

    for idx, s_order in enumerate(series_orders):
        sdf = normalized[normalized["series_order"] == s_order].sort_values("x")
        role = str(optional_style(sdf, "role") or "").strip().lower()
        name_lower = str(optional_style(sdf, "legend_label") or sdf["group"].iloc[0]).lower()
        if role == "observed" or (obs_df is None and (idx == 0 or "obs" in name_lower or "exp" in name_lower)):
            obs_df = sdf
        elif role == "calculated" or (calc_df is None and (idx == 1 or "calc" in name_lower or "fit" in name_lower or "total" in name_lower)):
            calc_df = sdf
        elif role == "residual" or "resid" in name_lower or "diff" in name_lower:
            res_df = sdf
        else:
            components.append(sdf)

    if obs_df is not None:
        raw_obs_lbl = optional_style(obs_df, "legend_label")
        obs_label = "Observed" if raw_obs_lbl is None or str(raw_obs_lbl).replace(".", "", 1).lstrip("-+").isdigit() else str(raw_obs_lbl)
        obs_color = optional_style(obs_df, "color") or "black"
        ax_main.plot(
            obs_df["x"],
            obs_df["y"],
            linestyle="none",
            marker=optional_style(obs_df, "marker") or "o",
            markersize=optional_number(optional_style(obs_df, "marker_size")) or (DEFAULT_MARKER_SIZE * 0.72),
            markerfacecolor="none",
            markeredgecolor=obs_color,
            markeredgewidth=1.2,
            label=obs_label,
            zorder=3,
        )

    if calc_df is not None:
        raw_calc_lbl = optional_style(calc_df, "legend_label")
        calc_label = "Calculated" if raw_calc_lbl is None or str(raw_calc_lbl).replace(".", "", 1).lstrip("-+").isdigit() else str(raw_calc_lbl)
        calc_color = optional_style(calc_df, "color") or palette[1]
        ax_main.plot(
            calc_df["x"],
            calc_df["y"],
            color=calc_color,
            linewidth=DEFAULT_LINE_WIDTH,
            label=calc_label,
            zorder=5,
        )

    for c_idx, comp_df in enumerate(components):
        comp_label = optional_style(comp_df, "legend_label") or f"Peak {c_idx + 1}"
        comp_color = optional_style(comp_df, "color") or palette[(c_idx + 2) % len(palette)]
        ax_main.plot(
            comp_df["x"],
            comp_df["y"],
            color=comp_color,
            linestyle="--",
            linewidth=DEFAULT_LINE_WIDTH * 0.78,
            label=comp_label,
            zorder=4,
        )
        if optional_bool(plot.get("fill_components"), default=True):
            ax_main.fill_between(comp_df["x"], 0.0, comp_df["y"], color=comp_color, alpha=0.16, zorder=2)

    if res_df is not None:
        rx = res_df["x"].to_numpy(dtype=float)
        ry = res_df["y"].to_numpy(dtype=float)
    elif obs_df is not None and calc_df is not None:
        rx = obs_df["x"].to_numpy(dtype=float)
        calc_interp = np.interp(rx, calc_df["x"].to_numpy(dtype=float), calc_df["y"].to_numpy(dtype=float))
        ry = obs_df["y"].to_numpy(dtype=float) - calc_interp
    else:
        rx, ry = np.array([]), np.array([])

    ax_res.axhline(0.0, color="#777777", linestyle="--", linewidth=1.1, zorder=1)
    if len(rx):
        ax_res.plot(rx, ry, color=palette[0], linewidth=DEFAULT_LINE_WIDTH * 0.72, zorder=3)

    first_prop = next(iter(metadata["property_labels"]), "y")
    ax_main.set_ylabel(plot.get("ylabel", metadata["property_labels"].get(first_prop, "Intensity (a.u.)")))
    ax_res.set_ylabel(plot.get("residual_ylabel", "Residual"))
    ax_res.set_xlabel(plot.get("xlabel", metadata["x_label"]))

    format_te_axis(ax_main, show_grid=False, tick_labelsize=SINGLE_TICK_LABEL_SIZE)
    format_te_axis(ax_res, show_grid=False, tick_labelsize=SINGLE_TICK_LABEL_SIZE * 0.85)
    ax_main.tick_params(axis="x", labelbottom=False)
    apply_axis_options(ax_main, plot)
    if plot.get("xlim") is not None:
        ax_res.set_xlim(*plot["xlim"])

    add_text_annotations(ax_main, plot)
    legend_mode = plot.get("legend", "inside")
    if legend_mode != "none":
        handles, labels = ax_main.get_legend_handles_labels()
        if handles:
            if legend_mode == "outside":
                leg = fig.legend(handles, labels, **legend_kwargs(plot, loc="upper center", bbox_to_anchor=(0.5, 0.99), ncol=min(len(labels), 4)))
                apply_legend_style(leg, plot)
                fig.tight_layout(rect=(0, 0, 1, figure_top_below_legend(fig)))
                return fig, (ax_main, ax_res)
            place_flexible_inside_legend(ax_main, plot, handles=handles, labels=labels, default_loc="best")

    fig.tight_layout()
    return fig, (ax_main, ax_res)


def plot_radar(
    normalized: pd.DataFrame,
    metadata: dict[str, Any],
    recipe: dict[str, Any],
) -> tuple[plt.Figure, plt.Axes]:
    """Render a multi-axis polar radar / spider comparison chart."""
    plot = recipe.get("plot", {})
    apply_plot_style(mode=plot.get("style_mode", "single"))
    figsize = tuple(plot.get("figsize", (6.2, 5.8)))
    fig, ax = plt.subplots(figsize=figsize, subplot_kw={"projection": "polar"})

    if metadata.get("categorical_x") or normalized["x_category"].notna().any():
        spokes = metadata.get("x_categories") or unique_in_order(normalized["x_category"])
        spoke_col = "x_category"
    else:
        spokes = unique_in_order(normalized["property"])
        spoke_col = "property"

    n_spokes = len(spokes)
    if n_spokes < 3:
        raise ValueError("radar plots require at least 3 metrics/categories")

    groups = unique_in_order(normalized["group"])
    raw_matrix = np.zeros((len(groups), n_spokes), dtype=float)
    for g_idx, group in enumerate(groups):
        gdf = normalized[normalized["group"] == group]
        for s_idx, spoke in enumerate(spokes):
            sdf = gdf[gdf[spoke_col].astype(str) == str(spoke)]
            raw_matrix[g_idx, s_idx] = float(sdf["y"].mean()) if not sdf.empty else 0.0

    if optional_bool(plot.get("radar_normalize"), default=False):
        col_max = np.nanmax(np.abs(raw_matrix), axis=0)
        col_max = np.where(col_max > 0, col_max, 1.0)
        plot_matrix = raw_matrix / col_max
    else:
        plot_matrix = raw_matrix

    angles = np.linspace(0.0, 2.0 * math.pi, n_spokes, endpoint=False).tolist()
    angles_closed = angles + angles[:1]

    ax.set_theta_offset(math.pi / 2.0)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles)
    ax.set_xticklabels([str(s) for s in spokes], fontsize=SINGLE_TICK_LABEL_SIZE * 0.90)
    ax.tick_params(axis="x", pad=16)
    ax.set_rlabel_position(32)
    ax.tick_params(axis="y", labelsize=DEFAULT_TICK_LABEL_SIZE * 0.70)
    ax.spines["polar"].set_linewidth(DEFAULT_AXIS_LINE_WIDTH)
    ax.grid(color="#BFBFBF", linestyle="--", linewidth=0.85)

    style_iters = get_style_cycles(plot.get("color_set"), len(groups))
    for g_idx, group in enumerate(groups):
        gdf = normalized[normalized["group"] == group]
        default_color, default_marker = next_style(style_iters)
        color = optional_style(gdf, "color") or default_color
        marker = optional_style(gdf, "marker") or default_marker
        label = effective_legend_label(gdf, normalized, group)
        values_closed = plot_matrix[g_idx].tolist() + [float(plot_matrix[g_idx, 0])]

        ax.plot(
            angles_closed,
            values_closed,
            color=color,
            marker=marker,
            markersize=DEFAULT_MARKER_SIZE * 0.85,
            linewidth=DEFAULT_LINE_WIDTH,
            label=label,
            zorder=4,
        )
        ax.fill(angles_closed, values_closed, color=color, alpha=float(plot.get("fill_alpha", 0.16)), zorder=2)

    if plot.get("ylim") is not None:
        ax.set_ylim(*plot["ylim"])
        if float(plot["ylim"][1]) <= 1.2:
            ax.set_yticks([0.25, 0.50, 0.75, 1.00])
            ax.set_yticklabels(["0.25", "0.50", "0.75", ""])

    legend_mode = plot.get("legend", "inside" if len(groups) > 1 else "none")
    if legend_mode != "none":
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            if legend_mode == "outside":
                leg = fig.legend(
                    handles,
                    labels,
                    **legend_kwargs(plot, loc="upper center", bbox_to_anchor=(0.5, 0.99), ncol=min(len(labels), 3)),
                )
                apply_legend_style(leg, plot)
                fig.subplots_adjust(top=min(0.82, figure_top_below_legend(fig)), bottom=0.07, left=0.10, right=0.90)
                return fig, ax
            place_flexible_inside_legend(ax, plot, handles=handles, labels=labels)

    fig.subplots_adjust(top=0.88, bottom=0.08, left=0.10, right=0.90)
    return fig, ax

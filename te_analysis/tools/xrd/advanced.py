"""Advanced XRD publication figures:
- Zoomed peak-shift dual-panel stack (`zoom`)
- Variable-temperature 2D intensity contour/heatmap (`vt-map`)
- Variable-temperature thermal-gradient waterfall stack (`vt-stack`)
- Rietveld / Le Bail whole-pattern refinement + residual + Bragg ticks (`rietveld`)
- Pseudo-Voigt multi-peak deconvolution + residual (`peak-fit`)
- Williamson-Hall crystallite size & microstrain fit (`williamson-hall`)
"""

from __future__ import annotations

import math
import os
import re
from itertools import cycle
from pathlib import Path
from typing import Any, Sequence

from te_analysis.tools.matplotlib_backend import configure_matplotlib_backend

configure_matplotlib_backend()

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import ticker
from matplotlib.colors import LinearSegmentedColormap
from scipy import optimize, signal, stats

from te_analysis.tools.colors import DEFAULT_FIELD_CMAP, get_colors, resolve_cmap
from te_analysis.tools.legend_layout import place_legend_inside
from te_analysis.tools.plot import (
    DEFAULT_AXIS_LABEL_SIZE,
    DEFAULT_AXIS_LINE_WIDTH,
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_LINE_WIDTH,
    DEFAULT_MARKER_SIZE,
    DEFAULT_SUBPLOT_ASPECT,
    DEFAULT_SUBPLOT_HEIGHT,
    DEFAULT_TICK_LABEL_SIZE,
    DEFAULT_TICK_LINE_WIDTH,
    apply_plot_style,
    figure_size_for_subplot_aspect,
    format_te_axis,
    save_figure,
)
from te_analysis.tools.xrd.io import XRDPattern, right_xrd_pattern_label
from te_analysis.tools.xrd.pdf_cards import PDFStandard, _clean_peaks
from te_analysis.tools.xrd.render import (
    DEFAULT_BOTTOM_PDF_GAP_FRACTION,
    DEFAULT_PDF_HEIGHT_FRACTION,
    DEFAULT_TWO_THETA_RANGE,
    DEFAULT_XRD_LINE_WIDTH,
    DEFAULT_XRD_SAVE_DIR,
    _clip_pattern,
    _default_offset_step,
    _draw_pdf_standard,
    prepare_intensity,
)


VT_TRACE_PALETTE_STOPS = (
    "#2B6CB0",
    "#4A90C8",
    "#7FA8CE",
    "#B88A9F",
    "#E07A68",
    "#C8463E",
)


def _style_xrd_axis(ax: plt.Axes, *, tick_labelsize: float = DEFAULT_TICK_LABEL_SIZE, hide_y: bool = True) -> None:
    format_te_axis(ax, show_grid=False, tick_labelsize=tick_labelsize)
    ax.tick_params(axis="x", which="both", direction="out", top=False, bottom=True, labelsize=tick_labelsize)
    if hide_y:
        ax.set_yticks([])
        ax.tick_params(axis="y", which="both", left=False, right=False, labelleft=False)


def _extract_temperature(pattern: XRDPattern, fallback_index: int) -> float:
    """Parse temperature from label or filename (e.g. '300 K', '550K', '400C', 'RT')."""
    for candidate in (pattern.label, pattern.source_path.stem):
        text = str(candidate)
        if re.search(r"\bRT\b", text, flags=re.IGNORECASE):
            return 300.0
        kelvin_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*K\b", text, flags=re.IGNORECASE)
        if kelvin_match:
            return float(kelvin_match.group(1))
        celsius_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*°?\s*C\b", text, flags=re.IGNORECASE)
        if celsius_match:
            return float(celsius_match.group(1)) + 273.15
        bare_match = re.fullmatch(r"\s*([0-9]{2,4}(?:\.[0-9]+)?)\s*", text)
        if bare_match:
            return float(bare_match.group(1))
    return 300.0 + 50.0 * fallback_index


def resolve_pattern_temperatures(
    patterns: Sequence[XRDPattern],
    explicit_temperatures: Sequence[float] | None = None,
) -> list[float]:
    if explicit_temperatures:
        if len(explicit_temperatures) != len(patterns):
            raise ValueError(
                f"--temperatures received {len(explicit_temperatures)} values for {len(patterns)} XRD patterns"
            )
        return [float(val) for val in explicit_temperatures]
    return [_extract_temperature(p, idx) for idx, p in enumerate(patterns)]


def _vt_trace_colors(count: int) -> list[str]:
    cmap = LinearSegmentedColormap.from_list("vt_trace_br", VT_TRACE_PALETTE_STOPS, N=256)
    if count <= 1:
        return ["#2B6CB0"]
    return [
        "#{:02x}{:02x}{:02x}".format(
            int(round(r * 255)),
            int(round(g * 255)),
            int(round(b * 255)),
        )
        for r, g, b, _ in (cmap(i / (count - 1)) for i in range(count))
    ]


# ---------------------------------------------------------------------------
# 1. Full Stack + Zoomed Peak-Shift Dual-Panel Plot
# ---------------------------------------------------------------------------
def plot_xrd_zoom_stack(
    patterns: Sequence[XRDPattern],
    *,
    zoom_range: tuple[float, float],
    pdf_standard: PDFStandard | None = None,
    top_pdf_standard: PDFStandard | None = None,
    normalized: bool = True,
    save_name: str | None = None,
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    two_theta_range: tuple[float | None, float | None] | None = DEFAULT_TWO_THETA_RANGE,
    overlap: float = 1.05,
    colors: Sequence[str] | None = None,
    color_set: str | None = None,
    line_width: float = DEFAULT_XRD_LINE_WIDTH,
    tick_labelsize: float = DEFAULT_TICK_LABEL_SIZE,
    legend_font_size: float | None = None,
    standard_color: str = "#d62728",
    top_standard_color: str = "#1f77b4",
    show_pdf_labels: bool = False,
    standard_height_fraction: float = DEFAULT_PDF_HEIGHT_FRACTION,
    show_peak_guide: bool = True,
    close: bool = True,
):
    """Render full-range stacked XRD on the left and a magnified peak-shift panel on the right."""
    if not patterns:
        raise ValueError("No XRD patterns were provided")
    z_lo, z_hi = float(zoom_range[0]), float(zoom_range[1])
    if z_lo >= z_hi:
        raise ValueError("Zoom lower 2-theta must be smaller than upper 2-theta")

    apply_plot_style(mode="single")
    lbl_fs = 11.5 if legend_font_size is None else legend_font_size

    prepared = []
    for pattern in patterns:
        cx, cy = _clip_pattern(pattern.two_theta, pattern.intensity, two_theta_range)
        py = prepare_intensity(cy, normalized=normalized, baseline="min")
        prepared.append((pattern, cx, py))

    offset_step = _default_offset_step([item[2] for item in prepared], normalized, overlap)
    standard_height = standard_height_fraction * offset_step
    bottom_gap = (0.55 if show_pdf_labels else DEFAULT_BOTTOM_PDF_GAP_FRACTION) * offset_step
    sample_base = standard_height + bottom_gap if pdf_standard else 0.0

    fig, (ax_main, ax_zoom) = plt.subplots(
        1,
        2,
        sharey=True,
        figsize=(7.8, DEFAULT_SUBPLOT_HEIGHT),
        gridspec_kw={"width_ratios": [2.55, 1.15], "wspace": 0.06},
    )

    palette = get_colors(color_set, len(patterns))
    color_cycle = cycle(colors or palette)
    first_zoom_peak: float | None = None

    for idx, (pattern, x_vals, y_vals) in enumerate(prepared):
        offset = sample_base + idx * offset_step
        color = next(color_cycle)
        ax_main.plot(x_vals, y_vals + offset, color=color, linewidth=line_width)

        z_mask = (x_vals >= z_lo) & (x_vals <= z_hi)
        zx = x_vals[z_mask]
        zy = y_vals[z_mask]
        if zx.size:
            ax_zoom.plot(zx, zy + offset, color=color, linewidth=line_width * 1.15)
            if idx == 0 and first_zoom_peak is None:
                first_zoom_peak = float(zx[int(np.argmax(zy))])

        label_y = offset + min(float(np.nanmax(y_vals)) * 0.30, 0.72 * offset_step)
        ax_zoom.text(
            z_hi - 0.04 * (z_hi - z_lo),
            label_y,
            right_xrd_pattern_label(pattern),
            ha="right",
            va="center",
            fontsize=lbl_fs,
            color=color,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.78, "pad": 1.0},
        )

    ax_main.axvspan(z_lo, z_hi, color="#8491B4", alpha=0.14, zorder=1.2)
    ax_main.axvline(z_lo, color="#667080", linestyle="--", linewidth=0.85, alpha=0.75)
    ax_main.axvline(z_hi, color="#667080", linestyle="--", linewidth=0.85, alpha=0.75)

    if show_peak_guide and first_zoom_peak is not None:
        ax_zoom.axvline(first_zoom_peak, color="#555555", linestyle="--", linewidth=1.0, alpha=0.8, zorder=1.8)

    trace_top = max(
        sample_base + idx * offset_step + float(np.nanmax(item[2]))
        for idx, item in enumerate(prepared)
    )
    right_main = float(two_theta_range[1]) if two_theta_range and two_theta_range[1] is not None else float(np.nanmax(prepared[0][1]))

    if pdf_standard is not None:
        _draw_pdf_standard(
            ax_main,
            pdf_standard,
            base=0.0,
            height=standard_height,
            minimum_height_fraction=0.08,
            two_theta_range=two_theta_range,
            color=standard_color,
            line_width=line_width,
            label_x=right_main - 0.8,
            label_y=standard_height + 0.08 * offset_step,
            label_vertical_alignment="bottom",
            label_font_size=lbl_fs,
            show_label=show_pdf_labels,
        )
        _draw_pdf_standard(
            ax_zoom,
            pdf_standard,
            base=0.0,
            height=standard_height,
            minimum_height_fraction=0.08,
            two_theta_range=(z_lo, z_hi),
            color=standard_color,
            line_width=line_width,
            label_x=z_hi,
            label_y=standard_height,
            label_vertical_alignment="bottom",
            label_font_size=lbl_fs,
            show_label=False,
        )

    top_limit = trace_top + 0.28 * offset_step
    if top_pdf_standard is not None:
        top_base = trace_top + 0.55 * offset_step
        ax_main.axhline(top_base, color="black", linewidth=DEFAULT_AXIS_LINE_WIDTH)
        ax_zoom.axhline(top_base, color="black", linewidth=DEFAULT_AXIS_LINE_WIDTH)
        _draw_pdf_standard(
            ax_main,
            top_pdf_standard,
            base=top_base,
            height=standard_height,
            minimum_height_fraction=0.08,
            two_theta_range=two_theta_range,
            color=top_standard_color,
            line_width=line_width,
            label_x=right_main - 0.8,
            label_y=top_base + standard_height + 0.12 * offset_step,
            label_vertical_alignment="bottom",
            label_font_size=lbl_fs,
            show_label=show_pdf_labels,
        )
        _draw_pdf_standard(
            ax_zoom,
            top_pdf_standard,
            base=top_base,
            height=standard_height,
            minimum_height_fraction=0.08,
            two_theta_range=(z_lo, z_hi),
            color=top_standard_color,
            line_width=line_width,
            label_x=z_hi,
            label_y=top_base + standard_height,
            label_vertical_alignment="bottom",
            label_font_size=lbl_fs,
            show_label=False,
        )
        top_limit = top_base + standard_height + (0.45 if show_pdf_labels else 0.18) * offset_step

    if two_theta_range:
        ax_main.set_xlim(*two_theta_range)
    ax_zoom.set_xlim(z_lo, z_hi)
    z_span = z_hi - z_lo
    z_major = 0.5 if z_span <= 2.2 else (1.0 if z_span <= 5.5 else 2.0)
    ax_zoom.xaxis.set_major_locator(ticker.MultipleLocator(z_major))
    ax_zoom.xaxis.set_minor_locator(ticker.MultipleLocator(z_major / 2.0))

    ax_main.set_xlabel(r"$2\theta$ (degree)")
    ax_zoom.set_xlabel(r"$2\theta$ (degree)")
    ax_main.set_ylabel(r"$\mathit{Intensity}$ (a.u.)" if normalized else r"$\mathit{Intensity}$ (counts)")

    _style_xrd_axis(ax_main, tick_labelsize=tick_labelsize, hide_y=True)
    _style_xrd_axis(ax_zoom, tick_labelsize=tick_labelsize, hide_y=True)
    ax_main.set_ylim(0.0 if pdf_standard else -0.05 * offset_step, top_limit)

    fig.tight_layout()
    if save_name:
        path = save_figure(fig, save_name, save_dir=save_dir, formats=list(formats) if formats else None)
        if close:
            plt.close(fig)
        return path
    return fig, (ax_main, ax_zoom)


# ---------------------------------------------------------------------------
# 2. Variable-Temperature In-Situ 2D Contour / Heatmap (`vt-map`)
# ---------------------------------------------------------------------------
def plot_xrd_vt_map(
    patterns: Sequence[XRDPattern],
    *,
    temperatures: Sequence[float] | None = None,
    pdf_standard: PDFStandard | None = None,
    normalized: bool = True,
    intensity_scale: str = "sqrt",
    cmap: str | None = None,
    transition_temps: Sequence[float] | None = None,
    save_name: str | None = None,
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    two_theta_range: tuple[float | None, float | None] | None = DEFAULT_TWO_THETA_RANGE,
    subplot_aspect: str = DEFAULT_SUBPLOT_ASPECT,
    tick_labelsize: float = DEFAULT_TICK_LABEL_SIZE,
    standard_color: str = "#3C5488",
    close: bool = True,
):
    """Render an in-situ variable-temperature XRD 2D color map (low=soft-blue -> high=soft-red)."""
    if len(patterns) < 2:
        raise ValueError("vt-map requires at least 2 XRD patterns measured at different temperatures")

    apply_plot_style(mode="single")
    temps = resolve_pattern_temperatures(patterns, temperatures)
    ordered = sorted(zip(temps, patterns), key=lambda item: item[0])
    sorted_temps = np.asarray([item[0] for item in ordered], dtype=float)
    sorted_patterns = [item[1] for item in ordered]

    clipped = []
    lo_vals, hi_vals = [], []
    for pat in sorted_patterns:
        cx, cy = _clip_pattern(pat.two_theta, pat.intensity, two_theta_range)
        py = prepare_intensity(cy, normalized=normalized, baseline="min")
        clipped.append((cx, py))
        lo_vals.append(float(np.nanmin(cx)))
        hi_vals.append(float(np.nanmax(cx)))

    grid_lo = float(two_theta_range[0]) if two_theta_range and two_theta_range[0] is not None else max(lo_vals)
    grid_hi = float(two_theta_range[1]) if two_theta_range and two_theta_range[1] is not None else min(hi_vals)
    x_grid = np.linspace(grid_lo, grid_hi, 1400)

    z_matrix = np.vstack([np.interp(x_grid, cx, py) for cx, py in clipped])
    scale_mode = str(intensity_scale or "linear").lower()
    if scale_mode == "sqrt":
        z_plot = np.sqrt(np.clip(z_matrix, 0.0, None))
        cbar_lbl = r"Normalized $\sqrt{I}$ (a.u.)" if normalized else r"$\sqrt{I}$ (a.u.)"
    elif scale_mode == "log":
        z_plot = np.log10(np.clip(z_matrix, 0.0, None) + 1e-3)
        cbar_lbl = r"$\log_{10} I$ (a.u.)"
    else:
        z_plot = z_matrix
        cbar_lbl = r"Intensity (a.u.)"

    cmap_obj = resolve_cmap(cmap or DEFAULT_FIELD_CMAP)

    if pdf_standard is not None:
        fig, (ax_map, ax_ref) = plt.subplots(
            2,
            1,
            sharex=True,
            figsize=(6.9, 5.6),
            gridspec_kw={"height_ratios": [4.3, 0.85], "hspace": 0.05},
        )
    else:
        figsize = figure_size_for_subplot_aspect(subplot_aspect, subplot_height=DEFAULT_SUBPLOT_HEIGHT)
        fig, ax_map = plt.subplots(figsize=figsize)
        ax_ref = None

    mesh = ax_map.pcolormesh(
        x_grid,
        sorted_temps,
        z_plot,
        cmap=cmap_obj,
        shading="gouraud",
        rasterized=True,
    )

    for t_trans in transition_temps or []:
        ax_map.axhline(float(t_trans), color="#333333", linestyle="--", linewidth=1.15, alpha=0.85)
        ax_map.text(
            grid_hi - 0.02 * (grid_hi - grid_lo),
            float(t_trans),
            f"{float(t_trans):g} K",
            ha="right",
            va="bottom",
            fontsize=11.5,
            color="#222222",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 1.2},
        )

    ax_map.set_ylabel(r"$T$ (K)")
    format_te_axis(ax_map, show_grid=False, tick_labelsize=tick_labelsize)
    ax_map.set_xlim(grid_lo, grid_hi)

    if ax_ref is not None and pdf_standard is not None:
        ax_map.tick_params(axis="x", which="both", bottom=False, labelbottom=False)
        _draw_pdf_standard(
            ax_ref,
            pdf_standard,
            base=0.0,
            height=1.0,
            minimum_height_fraction=0.08,
            two_theta_range=(grid_lo, grid_hi),
            color=standard_color,
            line_width=DEFAULT_XRD_LINE_WIDTH * 1.1,
            label_x=grid_hi - 0.6,
            label_y=0.78,
            label_vertical_alignment="center",
            label_font_size=11.0,
            show_label=True,
        )
        ax_ref.set_ylim(0.0, 1.18)
        ax_ref.set_xlabel(r"$2\theta$ (degree)")
        _style_xrd_axis(ax_ref, tick_labelsize=tick_labelsize, hide_y=True)
        cbar = fig.colorbar(mesh, ax=[ax_map, ax_ref], pad=0.035, fraction=0.046)
    else:
        ax_map.set_xlabel(r"$2\theta$ (degree)")
        ax_map.tick_params(axis="x", which="both", direction="out", top=False, bottom=True)
        cbar = fig.colorbar(mesh, ax=ax_map, pad=0.04, fraction=0.048)

    cbar.locator = ticker.MaxNLocator(nbins=5)
    cbar.update_ticks()
    cbar.outline.set_linewidth(DEFAULT_AXIS_LINE_WIDTH)
    cbar.ax.tick_params(labelsize=tick_labelsize * 0.9, width=DEFAULT_TICK_LINE_WIDTH, length=4.0, direction="in")
    cbar.set_label(cbar_lbl, fontsize=DEFAULT_AXIS_LABEL_SIZE * 0.92, labelpad=6)

    if ax_ref is None:
        fig.tight_layout()
    if save_name:
        path = save_figure(fig, save_name, save_dir=save_dir, formats=list(formats) if formats else None)
        if close:
            plt.close(fig)
        return path
    return fig, ax_map


# ---------------------------------------------------------------------------
# 3. Variable-Temperature Gradient Stack (`vt-stack`)
# ---------------------------------------------------------------------------
def plot_xrd_vt_stack(
    patterns: Sequence[XRDPattern],
    *,
    temperatures: Sequence[float] | None = None,
    pdf_standard: PDFStandard | None = None,
    guide_peaks: Sequence[float] | None = None,
    normalized: bool = True,
    overlap: float = 0.92,
    save_name: str | None = None,
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    two_theta_range: tuple[float | None, float | None] | None = DEFAULT_TWO_THETA_RANGE,
    subplot_aspect: str = DEFAULT_SUBPLOT_ASPECT,
    tick_labelsize: float = DEFAULT_TICK_LABEL_SIZE,
    line_width: float = DEFAULT_XRD_LINE_WIDTH * 1.15,
    standard_color: str = "#333333",
    close: bool = True,
):
    """Render temperature-ordered XRD patterns with a blue-to-red thermal color progression."""
    if not patterns:
        raise ValueError("No XRD patterns were provided")

    apply_plot_style(mode="single")
    temps = resolve_pattern_temperatures(patterns, temperatures)
    ordered = sorted(zip(temps, patterns), key=lambda item: item[0])

    prepared = []
    for temp_k, pat in ordered:
        cx, cy = _clip_pattern(pat.two_theta, pat.intensity, two_theta_range)
        py = prepare_intensity(cy, normalized=normalized, baseline="min")
        lbl = pat.label if pat.label_from_file else f"{temp_k:g} K"
        prepared.append((temp_k, lbl, cx, py))

    offset_step = _default_offset_step([item[3] for item in prepared], normalized, overlap)
    standard_height = 0.82 * offset_step
    sample_base = standard_height + 0.68 * offset_step if pdf_standard else 0.0

    figsize = figure_size_for_subplot_aspect(subplot_aspect, subplot_height=DEFAULT_SUBPLOT_HEIGHT * 1.06)
    fig, ax = plt.subplots(figsize=figsize)

    trace_colors = _vt_trace_colors(len(prepared))
    right_edge = float(two_theta_range[1]) if two_theta_range and two_theta_range[1] is not None else float(np.nanmax(prepared[0][2]))

    for idx, ((_temp_k, lbl, x_vals, y_vals), color) in enumerate(zip(prepared, trace_colors)):
        offset = sample_base + idx * offset_step
        ax.plot(x_vals, y_vals + offset, color=color, linewidth=line_width, zorder=3 + idx * 0.1)
        ax.fill_between(x_vals, offset, y_vals + offset, color=color, alpha=0.11, linewidth=0.0, zorder=2 + idx * 0.1)
        ax.text(
            right_edge - 0.6,
            offset + 0.22 * offset_step,
            lbl,
            ha="right",
            va="bottom",
            fontsize=11.5,
            color=color,
            fontweight="bold" if idx in (0, len(prepared) - 1) else "normal",
        )

    for g_pos in guide_peaks or []:
        ax.axvline(float(g_pos), color="#666666", linestyle="--", linewidth=0.95, alpha=0.72, zorder=1.6)

    if pdf_standard is not None:
        _draw_pdf_standard(
            ax,
            pdf_standard,
            base=0.0,
            height=standard_height,
            minimum_height_fraction=0.08,
            two_theta_range=two_theta_range,
            color=standard_color,
            line_width=DEFAULT_XRD_LINE_WIDTH,
            label_x=right_edge - 0.6,
            label_y=standard_height + 0.04 * offset_step,
            label_vertical_alignment="bottom",
            label_font_size=11.0,
            show_label=True,
        )

    trace_top = max(sample_base + idx * offset_step + float(np.nanmax(item[3])) for idx, item in enumerate(prepared))
    ax.set_ylim(0.0 if pdf_standard else -0.04 * offset_step, trace_top + 0.25 * offset_step)
    if two_theta_range:
        ax.set_xlim(*two_theta_range)
    ax.set_xlabel(r"$2\theta$ (degree)")
    ax.set_ylabel(r"$\mathit{Intensity}$ (a.u.)")
    _style_xrd_axis(ax, tick_labelsize=tick_labelsize, hide_y=True)
    fig.tight_layout()

    if save_name:
        path = save_figure(fig, save_name, save_dir=save_dir, formats=list(formats) if formats else None)
        if close:
            plt.close(fig)
        return path
    return fig, ax


# ---------------------------------------------------------------------------
# 4. Rietveld / Le Bail Whole-Pattern Refinement Plot (`rietveld`)
# ---------------------------------------------------------------------------
def _load_rietveld_table(path: Path) -> dict[str, np.ndarray]:
    """Read GSAS-II / FullProf / CSV refinement profile or fit a smooth profile to raw .xy."""
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv", ".txt", ".dat"}:
        try:
            df = pd.read_csv(path, sep=None, engine="python", comment="#")
            cols = {re.sub(r"[^a-z0-9]+", "", str(c).lower()): c for c in df.columns}
            x_col = next((cols[k] for k in ("x", "twotheta", "2theta", "2thetadeg", "angle") if k in cols), None)
            obs_col = next((cols[k] for k in ("obs", "yobs", "observed", "iobs", "intensity") if k in cols), None)
            calc_col = next((cols[k] for k in ("calc", "ycalc", "calculated", "icalc", "fit", "model") if k in cols), None)
            if x_col and obs_col and calc_col:
                x = pd.to_numeric(df[x_col], errors="coerce").to_numpy(dtype=float)
                obs = pd.to_numeric(df[obs_col], errors="coerce").to_numpy(dtype=float)
                calc = pd.to_numeric(df[calc_col], errors="coerce").to_numpy(dtype=float)
                diff_col = next((cols[k] for k in ("diff", "difference", "residual", "ydiff") if k in cols), None)
                diff = pd.to_numeric(df[diff_col], errors="coerce").to_numpy(dtype=float) if diff_col else (obs - calc)
                w_col = next((cols[k] for k in ("weight", "weights", "w") if k in cols), None)
                weights = pd.to_numeric(df[w_col], errors="coerce").to_numpy(dtype=float) if w_col else (1.0 / np.maximum(obs, 1.0))
                valid = np.isfinite(x) & np.isfinite(obs) & np.isfinite(calc)
                return {"x": x[valid], "obs": obs[valid], "calc": calc[valid], "diff": diff[valid], "weights": weights[valid]}
        except Exception:
            pass
    raise ValueError(
        f"Rietveld profile {path} must contain 2theta/x, obs/yobs, and calc/ycalc columns."
    )


def plot_xrd_rietveld(
    profile_path: str | os.PathLike[str],
    *,
    pdf_standards: Sequence[PDFStandard] | None = None,
    phase_labels: Sequence[str] | None = None,
    formula_text: str | None = None,
    cell_text: str | None = None,
    rwp: float | None = None,
    rp: float | None = None,
    zoom_range: tuple[float, float] | None = None,
    two_theta_range: tuple[float | None, float | None] | None = DEFAULT_TWO_THETA_RANGE,
    save_name: str | None = None,
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    tick_labelsize: float = DEFAULT_TICK_LABEL_SIZE,
    close: bool = True,
):
    """Render a publication Rietveld refinement figure (Obs, Calc, Bragg ticks, Difference, Rwp/Rp)."""
    apply_plot_style(mode="single")
    prof = _load_rietveld_table(Path(profile_path))
    x, obs, calc, diff, weights = prof["x"], prof["obs"], prof["calc"], prof["diff"], prof["weights"]

    if two_theta_range:
        lo, hi = two_theta_range
        mask = np.ones_like(x, dtype=bool)
        if lo is not None:
            mask &= x >= lo
        if hi is not None:
            mask &= x <= hi
        x, obs, calc, diff, weights = x[mask], obs[mask], calc[mask], diff[mask], weights[mask]

    if rwp is None:
        denom = np.sum(weights * (obs**2))
        rwp = float(100.0 * np.sqrt(np.sum(weights * (diff**2)) / denom)) if denom > 0 else 0.0
    if rp is None:
        denom_p = np.sum(np.abs(obs))
        rp = float(100.0 * np.sum(np.abs(diff)) / denom_p) if denom_p > 0 else 0.0

    norm = float(np.nanmax(obs)) if np.nanmax(obs) > 0 else 1.0
    obs_n, calc_n, diff_n = obs / norm, calc / norm, diff / norm

    standards = list(pdf_standards or [])
    n_phases = len(standards)
    lowest_tick = -0.055 - 0.068 * max(n_phases - 1, 0) if n_phases else -0.02
    diff_offset = min(-0.22, lowest_tick - 0.08 - float(np.nanmax(diff_n)))

    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    palette = get_colors("npg", max(n_phases + 3, 5))

    step_stride = max(1, len(x) // 900)
    ax.plot(
        x[::step_stride],
        obs_n[::step_stride],
        linestyle="none",
        marker="o",
        markersize=4.2,
        markerfacecolor="none",
        markeredgecolor="#222222",
        markeredgewidth=0.8,
        label="Observed",
        zorder=3,
    )
    ax.plot(x, calc_n, color="#E64B35", linewidth=1.45, label="Calculated", zorder=4)
    ax.axhline(diff_offset, color="#999999", linestyle="--", linewidth=0.75, zorder=1.5)
    ax.plot(x, diff_n + diff_offset, color="#3C5488", linewidth=1.0, label="Difference", zorder=3)

    phase_colors = ["#00A087", "#7E6148", "#8491B4", "#D99B32"]
    x_left = float(two_theta_range[0]) if two_theta_range and two_theta_range[0] is not None else float(np.min(x))
    x_right = float(two_theta_range[1]) if two_theta_range and two_theta_range[1] is not None else float(np.max(x))

    for p_idx, std in enumerate(standards):
        peaks = _clean_peaks(std.peaks, (x_left, x_right))
        y_tick = -0.055 - 0.068 * p_idx
        p_color = phase_colors[p_idx % len(phase_colors)]
        if not peaks.empty:
            ax.vlines(peaks["two_theta_deg"], y_tick - 0.020, y_tick + 0.020, color=p_color, linewidth=1.0, zorder=3.5)
        p_lbl = phase_labels[p_idx] if phase_labels and p_idx < len(phase_labels) else std.label
        ax.text(
            x_left + 0.015 * (x_right - x_left),
            y_tick,
            p_lbl,
            color=p_color,
            fontsize=11.0,
            va="center",
            ha="left",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 1.0},
        )

    info_lines = []
    if formula_text:
        info_lines.append(formula_text)
    info_lines.append(rf"$R_{{\mathrm{{wp}}}} = {rwp:.2f}\%$,  $R_{{\mathrm{{p}}}} = {rp:.2f}\%$")
    if cell_text:
        info_lines.append(cell_text)
    ax.text(
        0.975,
        0.975,
        "\n".join(info_lines),
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=11.5,
        linespacing=1.4,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 2.0},
    )

    has_inset = False
    if zoom_range is not None:
        zlo, zhi = float(zoom_range[0]), float(zoom_range[1])
        zmask = (x >= zlo) & (x <= zhi)
        if np.any(zmask):
            has_inset = True
            ax_ins = ax.inset_axes([0.52, 0.49, 0.44, 0.26], zorder=6)
            ax_ins.plot(
                x[zmask],
                obs_n[zmask],
                linestyle="none",
                marker="o",
                markersize=3.6,
                markerfacecolor="none",
                markeredgecolor="#222222",
                markeredgewidth=0.75,
            )
            ax_ins.plot(x[zmask], calc_n[zmask], color="#E64B35", linewidth=1.35)
            ax_ins.set_xlim(zlo, zhi)
            zy_max = float(np.max(np.maximum(obs_n[zmask], calc_n[zmask])))
            zy_min = float(np.min(np.minimum(obs_n[zmask], calc_n[zmask])))
            pad_z = 0.14 * max(zy_max - zy_min, 0.02)
            ax_ins.set_ylim(max(0.0, zy_min - pad_z), zy_max + pad_z)
            _style_xrd_axis(ax_ins, tick_labelsize=tick_labelsize * 0.76, hide_y=True)
            ax_ins.xaxis.set_major_locator(ticker.MaxNLocator(nbins=4))

    y_bottom = float(np.min(diff_n + diff_offset)) - 0.06
    ax.set_ylim(y_bottom, 1.45 if has_inset else 1.38)
    ax.set_xlim(x_left, x_right)
    ax.set_xlabel(r"$2\theta$ (degree)")
    ax.set_ylabel(r"$\mathit{Intensity}$ (a.u.)")
    _style_xrd_axis(ax, tick_labelsize=tick_labelsize, hide_y=True)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(10))
    ax.xaxis.set_minor_locator(ticker.MultipleLocator(5))
    place_legend_inside(
        ax,
        loc="upper left",
        fontsize=11.0,
        frameon=True,
        facecolor="white",
        edgecolor="black",
        fancybox=False,
        ylim_locked=(True, False),
        xlim_locked=(True, True),
    )
    if not has_inset:
        fig.tight_layout()

    if save_name:
        path = save_figure(fig, save_name, save_dir=save_dir, formats=list(formats) if formats else None)
        if close:
            plt.close(fig)
        return path
    return fig, ax


# ---------------------------------------------------------------------------
# 5. Pseudo-Voigt Multi-Peak Deconvolution + Residual (`peak-fit`)
# ---------------------------------------------------------------------------
def _pseudo_voigt_single(x: np.ndarray, amp: float, center: float, fwhm: float, eta: float) -> np.ndarray:
    w = max(abs(fwhm), 1e-4)
    sigma = w / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    gamma = w / 2.0
    gauss = np.exp(-0.5 * ((x - center) / sigma) ** 2)
    lorentz = 1.0 / (1.0 + ((x - center) / gamma) ** 2)
    return amp * (eta * lorentz + (1.0 - eta) * gauss)


def _multi_pv_model(x: np.ndarray, b0: float, b1: float, *params: float) -> np.ndarray:
    y = b0 + b1 * (x - x[0])
    n_peaks = len(params) // 4
    for idx in range(n_peaks):
        amp, center, fwhm, eta = params[4 * idx : 4 * idx + 4]
        y = y + _pseudo_voigt_single(x, amp, center, fwhm, eta)
    return y


def plot_xrd_peak_fit(
    pattern: XRDPattern,
    *,
    fit_window: tuple[float, float] | None = None,
    peak_centers: Sequence[float] | None = None,
    max_peaks: int = 3,
    save_name: str | None = None,
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    tick_labelsize: float = DEFAULT_TICK_LABEL_SIZE,
    close: bool = True,
):
    """Fit 1..N Pseudo-Voigt peaks inside a 2-theta window and render Observed + Components + Residual."""
    apply_plot_style(mode="single")

    x_all, y_all = pattern.two_theta, pattern.intensity
    if fit_window is None:
        max_idx = int(np.argmax(y_all))
        center_guess = float(x_all[max_idx])
        fit_window = (center_guess - 1.8, center_guess + 1.8)

    w_lo, w_hi = float(fit_window[0]), float(fit_window[1])
    x, y_raw = _clip_pattern(x_all, y_all, (w_lo, w_hi))
    if len(x) < 10:
        raise ValueError(f"Too few XRD points ({len(x)}) inside peak-fit window [{w_lo}, {w_hi}]")

    # Normalize to max = 100 for clean display and numerically well-scaled optimization
    y_min = float(np.min(y_raw))
    y_span = max(float(np.max(y_raw)) - y_min, 1e-9)
    y = (y_raw - y_min) / y_span * 100.0

    b0_init = float(0.5 * (np.mean(y[:3]) + np.mean(y[-3:])))
    b1_init = float((y[-1] - y[0]) / max(x[-1] - x[0], 1e-6))
    baseline_est = b0_init + b1_init * (x - x[0])
    y_corr = np.clip(y - baseline_est, 0.0, None)

    if peak_centers:
        centers_init = [float(c) for c in peak_centers]
    else:
        step = float(np.median(np.diff(x)))
        min_dist = max(1, int(round(0.12 / max(step, 1e-4))))
        pk_idx, props = signal.find_peaks(y_corr, prominence=8.0, distance=min_dist)
        if len(pk_idx) == 0:
            pk_idx = np.array([int(np.argmax(y_corr))])
        elif len(pk_idx) > max_peaks:
            order = np.argsort(props["prominences"])[::-1][:max_peaks]
            pk_idx = np.sort(pk_idx[order])
        centers_init = [float(x[idx]) for idx in pk_idx]

    p0: list[float] = [b0_init, b1_init]
    lower: list[float] = [-20.0, -50.0]
    upper: list[float] = [60.0, 50.0]
    for c0 in centers_init:
        amp0 = float(np.interp(c0, x, y_corr))
        p0.extend([max(amp0, 5.0), c0, 0.22, 0.5])
        lower.extend([0.5, max(w_lo, c0 - 0.6), 0.03, 0.0])
        upper.extend([150.0, min(w_hi, c0 + 0.6), 2.5, 1.0])

    popt, _ = optimize.curve_fit(_multi_pv_model, x, y, p0=p0, bounds=(lower, upper), maxfev=12000)
    y_calc = _multi_pv_model(x, *popt)
    residual = y - y_calc
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - float(np.sum(residual**2)) / ss_tot if ss_tot > 0 else 1.0

    b0_fit, b1_fit = popt[0], popt[1]
    bg_curve = b0_fit + b1_fit * (x - x[0])
    n_peaks = (len(popt) - 2) // 4

    fig, (ax_main, ax_res) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=(6.8, 5.6),
        gridspec_kw={"height_ratios": [3.4, 1.0], "hspace": 0.07},
    )

    palette = get_colors("npg", max(n_peaks + 2, 4))
    ax_main.plot(
        x,
        y,
        linestyle="none",
        marker="o",
        markersize=5.0,
        markerfacecolor="none",
        markeredgecolor="#222222",
        markeredgewidth=0.95,
        label="Observed",
        zorder=3,
    )
    ax_main.plot(x, y_calc, color="#E64B35", linewidth=DEFAULT_LINE_WIDTH, label="Total Fit", zorder=5)

    peak_summaries = []
    comp_colors = ["#00A087", "#3C5488", "#4DBBD5", "#7E6148"]
    for idx in range(n_peaks):
        amp, center, fwhm, eta = popt[2 + 4 * idx : 2 + 4 * (idx + 1)]
        comp_y = bg_curve + _pseudo_voigt_single(x, amp, center, fwhm, eta)
        c_col = comp_colors[idx % len(comp_colors)]
        lbl = f"Peak {idx + 1} ({center:.2f}°, FWHM {fwhm:.2f}°)"
        ax_main.plot(x, comp_y, color=c_col, linestyle="--", linewidth=1.4, label=lbl, zorder=4)
        ax_main.fill_between(x, bg_curve, comp_y, color=c_col, alpha=0.18, zorder=2)
        peak_summaries.append({"peak": idx + 1, "center_2theta": center, "fwhm_deg": fwhm, "amplitude": amp, "eta": eta})

    ax_res.axhline(0.0, color="#777777", linestyle="--", linewidth=0.9)
    ax_res.plot(x, residual, color="#3C5488", linewidth=1.2)

    ax_main.text(
        0.03,
        0.95,
        f"{pattern.label}\n$R^2 = {r2:.4f}$",
        transform=ax_main.transAxes,
        ha="left",
        va="top",
        fontsize=11.0,
        bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.92, "pad": 3.8},
    )
    ax_main.set_ylabel("Intensity (a.u.)")
    ax_res.set_ylabel("Residual")
    ax_res.set_xlabel(r"$2\theta$ (degree)")
    ax_main.set_ylim(-5.0, 132.0)
    ax_main.set_yticks([0, 25, 50, 75, 100])
    format_te_axis(ax_main, show_grid=False, tick_labelsize=tick_labelsize)
    format_te_axis(ax_res, show_grid=False, tick_labelsize=tick_labelsize * 0.88)
    ax_main.tick_params(axis="x", labelbottom=False)
    ax_main.set_xlim(w_lo, w_hi)
    ax_res.set_xlim(w_lo, w_hi)
    place_legend_inside(
        ax_main,
        loc="upper right",
        fontsize=10.5,
        frameon=True,
        facecolor="white",
        edgecolor="black",
        fancybox=False,
        ylim_locked=(True, False),
        xlim_locked=(True, True),
        cap_ticks_at=100.0,
    )

    if save_name:
        path = save_figure(fig, save_name, save_dir=save_dir, formats=list(formats) if formats else None)
        summary_csv = Path(save_dir) / f"{Path(save_name).stem}_peaks.csv"
        pd.DataFrame(peak_summaries).to_csv(summary_csv, index=False)
        if close:
            plt.close(fig)
        return path
    return fig, (ax_main, ax_res)


# ---------------------------------------------------------------------------
# 6. Williamson-Hall Crystallite Size & Microstrain Plot (`williamson-hall`)
# ---------------------------------------------------------------------------
def plot_xrd_williamson_hall(
    pattern: XRDPattern,
    *,
    pdf_standard: PDFStandard | None = None,
    instr_fwhm_deg: float = 0.05,
    wavelength_angstrom: float | None = None,
    two_theta_range: tuple[float | None, float | None] | None = (15.0, 80.0),
    save_name: str | None = None,
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    subplot_aspect: str = DEFAULT_SUBPLOT_ASPECT,
    tick_labelsize: float = DEFAULT_TICK_LABEL_SIZE,
    close: bool = True,
):
    """Extract major Bragg peaks, fit FWHM via local Pseudo-Voigt, and plot beta*cos(theta) vs 4*sin(theta)."""
    apply_plot_style(mode="single")
    lam_nm = (wavelength_angstrom or pattern.wavelength_angstrom or 1.5406) * 0.1

    x, y_raw = _clip_pattern(pattern.two_theta, pattern.intensity, two_theta_range)
    y = prepare_intensity(y_raw, normalized=True, baseline="min") * 100.0
    step = float(np.median(np.diff(x)))
    min_dist = max(3, int(round(0.8 / max(step, 1e-4))))
    pk_indices, _ = signal.find_peaks(y, prominence=6.5, distance=min_dist)
    if len(pk_indices) < 3:
        pk_indices, _ = signal.find_peaks(y, prominence=3.0, distance=min_dist)

    wh_rows = []
    std_peaks = _clean_peaks(pdf_standard.peaks, two_theta_range) if pdf_standard is not None else pd.DataFrame()

    for idx in pk_indices:
        c_guess = float(x[idx])
        local_mask = (x >= c_guess - 0.9) & (x <= c_guess + 0.9)
        lx, ly = x[local_mask], y[local_mask]
        if len(lx) < 7:
            continue
        try:
            b0 = float(min(ly[0], ly[-1]))
            popt, _ = optimize.curve_fit(
                lambda arr, bg, amp, cen, w, eta: bg + _pseudo_voigt_single(arr, amp, cen, w, eta),
                lx,
                ly,
                p0=[b0, max(float(ly.max() - b0), 2.0), c_guess, 0.18, 0.5],
                bounds=([-10.0, 0.5, c_guess - 0.35, 0.03, 0.0], [50.0, 150.0, c_guess + 0.35, 1.8, 1.0]),
                maxfev=5000,
            )
            center_deg, fwhm_obs_deg = float(popt[2]), abs(float(popt[3]))
        except Exception:
            continue

        if fwhm_obs_deg <= instr_fwhm_deg * 1.02:
            continue
        fwhm_corr_deg = math.sqrt(max(fwhm_obs_deg**2 - instr_fwhm_deg**2, 0.0))
        theta_rad = math.radians(center_deg / 2.0)
        beta_rad = math.radians(fwhm_corr_deg)
        x_wh = 4.0 * math.sin(theta_rad)
        y_wh_mrad = beta_rad * math.cos(theta_rad) * 1e3

        hkl_label = f"{center_deg:.1f}°"
        if not std_peaks.empty and all(col in std_peaks.columns for col in ("h", "k", "l")):
            diffs = np.abs(std_peaks["two_theta_deg"].to_numpy(dtype=float) - center_deg)
            best_i = int(np.argmin(diffs))
            if diffs[best_i] <= 0.45:
                row_p = std_peaks.iloc[best_i]
                if pd.notna(row_p["h"]) and pd.notna(row_p["k"]) and pd.notna(row_p["l"]):
                    hkl_label = f"({int(row_p['h'])}{int(row_p['k'])}{int(row_p['l'])})"

        wh_rows.append({"two_theta_deg": center_deg, "fwhm_deg": fwhm_obs_deg, "four_sin_theta": x_wh, "beta_cos_theta_mrad": y_wh_mrad, "label": hkl_label})

    if len(wh_rows) < 2:
        raise ValueError("Williamson-Hall fit requires at least 2 resolvable diffraction peaks above instrumental width")

    df_wh = pd.DataFrame(wh_rows).sort_values("four_sin_theta")
    xw = df_wh["four_sin_theta"].to_numpy(dtype=float)
    yw = df_wh["beta_cos_theta_mrad"].to_numpy(dtype=float)  # 10^-3 rad

    slope_mrad, intercept_mrad, r_val, _, _ = stats.linregress(xw, yw)
    # beta*cos(theta) [rad] = (K * lambda_nm / D_nm) + strain * (4 * sin(theta))
    intercept_rad = max(intercept_mrad * 1e-3, 1e-6)
    size_nm = (0.9 * lam_nm) / intercept_rad
    strain_pct = slope_mrad * 0.1  # since slope_mrad * 1e-3 * 100% = slope_mrad * 0.1%

    figsize = figure_size_for_subplot_aspect(subplot_aspect, subplot_height=DEFAULT_SUBPLOT_HEIGHT)
    fig, ax = plt.subplots(figsize=figsize)
    palette = get_colors("npg", 3)

    x_line = np.linspace(float(xw.min()) * 0.92, float(xw.max()) * 1.06, 120)
    y_line = intercept_mrad + slope_mrad * x_line
    ax.plot(x_line, y_line, color=palette[1], linestyle="--", linewidth=DEFAULT_LINE_WIDTH, label="Linear W–H fit", zorder=3)
    ax.scatter(
        xw,
        yw,
        s=(DEFAULT_MARKER_SIZE * 1.05) ** 2,
        color=palette[0],
        edgecolors="black",
        linewidths=0.9,
        label=pattern.label,
        zorder=4,
    )

    for _, row in df_wh.iterrows():
        ax.annotate(
            str(row["label"]),
            (float(row["four_sin_theta"]), float(row["beta_cos_theta_mrad"])),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=11.0,
            color="#333333",
        )

    summary_txt = (
        f"$D = {size_nm:.1f}$ nm\n"
        f"$\\varepsilon = {strain_pct:.3f}\\%$\n"
        f"$R^2 = {r_val**2:.3f}$"
    )
    ax.text(
        0.04,
        0.94,
        summary_txt,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=12.0,
        bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.92, "pad": 4.5},
        zorder=6,
    )

    ax.set_xlabel(r"$4\sin\theta$")
    ax.set_ylabel(r"$\beta\cos\theta$ ($10^{-3}$ rad)")
    ax.margins(x=0.08, y=0.18)
    format_te_axis(ax, show_grid=False, tick_labelsize=tick_labelsize)
    place_legend_inside(
        ax,
        loc="lower right",
        fontsize=DEFAULT_LEGEND_FONT_SIZE,
        frameon=True,
        facecolor="white",
        edgecolor="black",
        fancybox=False,
    )
    fig.tight_layout()

    if save_name:
        path = save_figure(fig, save_name, save_dir=save_dir, formats=list(formats) if formats else None)
        df_wh.to_csv(Path(save_dir) / f"{Path(save_name).stem}_wh_points.csv", index=False)
        if close:
            plt.close(fig)
        return path
    return fig, ax

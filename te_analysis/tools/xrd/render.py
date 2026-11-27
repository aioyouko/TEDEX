"""XRD figure rendering for stacked, raw/normalized, and separate layouts."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from itertools import cycle
from pathlib import Path
from typing import Iterable, Sequence

from te_analysis.tools.matplotlib_backend import configure_matplotlib_backend

configure_matplotlib_backend()

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from te_analysis.tools.selectors import (
    normalize_batch_id as normalize_batch_selector,
    truncate_with_digest,
)
from te_analysis.tools.colors import get_colors
from te_analysis.tools.legend_layout import axis_limit_locked, place_legend_inside
from te_analysis.tools.plot import (
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_SUBPLOT_ASPECT,
    DEFAULT_SUBPLOT_HEIGHT,
    DEFAULT_TICK_LABEL_SIZE,
    apply_plot_style,
    apply_subplot_aspect,
    figure_size_for_subplot_aspect,
    format_te_axis,
    save_figure,
)

from te_analysis.paths import get_workspace
from te_analysis.tools.xrd.io import XRDPattern, right_xrd_pattern_label, safe_filename, format_xrd_pattern_label
from te_analysis.tools.xrd.pdf_cards import PDFStandard, _clean_peaks


DEFAULT_XRD_SAVE_DIR = get_workspace().xrd_figure_dir()
DEFAULT_TWO_THETA_RANGE = (10.0, 80.0)
DEFAULT_XRD_LINE_WIDTH = 0.9
DEFAULT_XRD_LABEL_FONT_SIZE = 7.5
DEFAULT_PDF_HEIGHT_FRACTION = 1.0
DEFAULT_BOTTOM_PDF_GAP_FRACTION = 0.25
_MIN_LABELED_BOTTOM_PDF_GAP_FRACTION = 0.60


def _draw_pdf_standard(
    ax,
    pdf_standard: PDFStandard,
    *,
    base: float,
    height: float,
    minimum_height_fraction: float,
    two_theta_range: tuple[float | None, float | None] | None,
    color: str,
    line_width: float,
    label_x: float,
    label_y: float,
    label_vertical_alignment: str,
    label_font_size: float,
    show_label: bool,
):
    peaks = _clean_peaks(pdf_standard.peaks, two_theta_range)
    if not peaks.empty:
        max_pdf_intensity = peaks["intensity"].max()
        relative_intensity = peaks["intensity"] / max_pdf_intensity
        stick_heights = (
            minimum_height_fraction * height
            + relative_intensity * (1.0 - minimum_height_fraction) * height
        )
        ax.vlines(
            peaks["two_theta_deg"],
            base,
            base + stick_heights,
            color=color,
            linewidth=line_width,
            label=pdf_standard.label,
        )
    if show_label:
        ax.text(
            label_x,
            label_y,
            pdf_standard.label,
            ha="right",
            va=label_vertical_alignment,
            fontsize=label_font_size,
            color=color,
        )
    return plt.Line2D(
        [0],
        [0],
        color=color,
        linewidth=max(line_width, DEFAULT_XRD_LINE_WIDTH),
        label=pdf_standard.label,
    )


def _clip_pattern(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    two_theta_range: tuple[float | None, float | None] | None,
) -> tuple[np.ndarray, np.ndarray]:
    if not two_theta_range:
        return two_theta, intensity
    low, high = two_theta_range
    mask = np.ones(two_theta.shape, dtype=bool)
    if low is not None:
        mask &= two_theta >= low
    if high is not None:
        mask &= two_theta <= high
    if not np.any(mask):
        return two_theta, intensity
    return two_theta[mask], intensity[mask]


def prepare_intensity(
    intensity: np.ndarray,
    normalized: bool,
    baseline: str = "min",
) -> np.ndarray:
    values = intensity.astype(float).copy()
    if baseline == "min":
        values = values - np.nanmin(values)
    elif baseline == "none":
        pass
    else:
        raise ValueError("baseline must be 'min' or 'none'")

    if normalized:
        max_value = np.nanmax(np.abs(values))
        if max_value > 0:
            values = values / max_value
    return values


def _default_offset_step(prepared_intensities: Sequence[np.ndarray], normalized: bool, overlap: float) -> float:
    if normalized:
        return overlap
    max_range = max(float(np.nanmax(values) - np.nanmin(values)) for values in prepared_intensities)
    return max(max_range * overlap, 1.0)


def plot_xrd_comparison(
    patterns: Sequence[XRDPattern],
    pdf_standard: PDFStandard | None = None,
    normalized: bool = False,
    save_name: str | None = None,
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    two_theta_range: tuple[float | None, float | None] | None = DEFAULT_TWO_THETA_RANGE,
    overlap: float = 1.05,
    offset_step: float | None = None,
    baseline: str = "min",
    standard_height_fraction: float = DEFAULT_PDF_HEIGHT_FRACTION,
    standard_gap_fraction: float = 0.60,
    standard_min_height_fraction: float = 0.08,
    figsize: tuple[float, float] | None = None,
    subplot_aspect: str = DEFAULT_SUBPLOT_ASPECT,
    ylim: tuple[float | None, float | None] | None = None,
    colors: Sequence[str] | None = None,
    line_width: float = DEFAULT_XRD_LINE_WIDTH,
    tick_labelsize: float = DEFAULT_TICK_LABEL_SIZE,
    legend_font_size: float | None = None,
    legend_outside: bool = False,
    show_legend: bool = False,
    fixed_aspect: bool = False,
    right_labels: bool = True,
    standard_color: str = "#d62728",
    transparent: bool = False,
    close: bool = True,
    top_pdf_standard: PDFStandard | None = None,
    top_standard_color: str = "#1f77b4",
    show_pdf_labels: bool = False,
    bottom_standard_gap_fraction: float = DEFAULT_BOTTOM_PDF_GAP_FRACTION,
    color_set: str | None = None,
):
    """
    Plot stacked XRD patterns with optional bottom and top PDF-card references.

    ``normalized=False`` keeps the raw count scale after optional baseline
    alignment; ``normalized=True`` scales each trace to its own maximum.
    """
    if not patterns:
        raise ValueError("No XRD patterns were provided")
    if not math.isfinite(standard_height_fraction) or standard_height_fraction <= 0:
        raise ValueError("standard_height_fraction must be a finite positive number")
    if (
        not math.isfinite(bottom_standard_gap_fraction)
        or bottom_standard_gap_fraction < 0
    ):
        raise ValueError("bottom_standard_gap_fraction must be finite and non-negative")

    apply_plot_style(mode="single")
    annotation_font_size = DEFAULT_XRD_LABEL_FONT_SIZE if legend_font_size is None else legend_font_size
    explicit_legend_fs = legend_font_size
    legend_font_size = DEFAULT_LEGEND_FONT_SIZE if legend_font_size is None else legend_font_size
    prepared = []
    for pattern in patterns:
        clipped_x, clipped_y = _clip_pattern(pattern.two_theta, pattern.intensity, two_theta_range)
        prepared_y = prepare_intensity(clipped_y, normalized=normalized, baseline=baseline)
        prepared.append((pattern, clipped_x, prepared_y))

    prepared_intensities = [item[2] for item in prepared]
    offset_step = offset_step or _default_offset_step(prepared_intensities, normalized, overlap)
    standard_height = standard_height_fraction * offset_step
    standard_label_padding = 0.10 * offset_step
    top_standard_label_band = 0.50 * offset_step if show_pdf_labels else 0.0
    effective_bottom_gap_fraction = bottom_standard_gap_fraction
    if show_pdf_labels:
        effective_bottom_gap_fraction = max(
            effective_bottom_gap_fraction,
            _MIN_LABELED_BOTTOM_PDF_GAP_FRACTION,
        )
    sample_base = (
        standard_height + effective_bottom_gap_fraction * offset_step
        if pdf_standard
        else 0.0
    )

    if figsize is None:
        figsize = figure_size_for_subplot_aspect(
            subplot_aspect,
            subplot_height=DEFAULT_SUBPLOT_HEIGHT,
        )
    fig, ax = plt.subplots(figsize=figsize)
    palette = get_colors(color_set, len(patterns))
    color_cycle = cycle(colors or palette)
    handles = []
    labels = []
    range_high = two_theta_range[1] if two_theta_range else None
    right_edge = (
        float(range_high)
        if range_high is not None
        else max(float(np.nanmax(item[1])) for item in prepared)
    )

    for index, (pattern, x_values, y_values) in enumerate(prepared):
        offset = sample_base + index * offset_step
        color = next(color_cycle)
        (line,) = ax.plot(x_values, y_values + offset, color=color, linewidth=line_width, label=pattern.label)
        handles.append(line)
        labels.append(pattern.label)
        if right_labels and x_values.size:
            label_y = offset + min(float(np.nanmax(y_values)) * 0.28, 0.75 * offset_step)
            ax.text(
                right_edge - 0.6,
                label_y,
                right_xrd_pattern_label(pattern),
                ha="right",
                va="center",
                fontsize=annotation_font_size,
                color="black",
            )

    label_x = right_edge - 0.6
    trace_top = max(
        sample_base + index * offset_step + float(np.nanmax(values))
        for index, values in enumerate(prepared_intensities)
    )

    if pdf_standard is not None:
        handle = _draw_pdf_standard(
            ax,
            pdf_standard,
            base=0.0,
            height=standard_height,
            minimum_height_fraction=standard_min_height_fraction,
            two_theta_range=two_theta_range,
            color=standard_color,
            line_width=line_width,
            label_x=label_x,
            label_y=standard_height + standard_label_padding,
            label_vertical_alignment="bottom",
            label_font_size=annotation_font_size,
            show_label=show_pdf_labels,
        )
        handles.append(handle)
        labels.append(pdf_standard.label)

    top_standard_base = None
    top_standard_label_top = None
    if top_pdf_standard is not None:
        top_standard_base = trace_top + standard_gap_fraction * offset_step
        top_standard_label_bottom = (
            top_standard_base + standard_height + standard_label_padding
        )
        top_standard_label_top = top_standard_label_bottom + top_standard_label_band
        ax.axhline(
            top_standard_base,
            color="black",
            linewidth=ax.spines["bottom"].get_linewidth(),
            label="_nolegend_",
            zorder=2.5,
        )
        handle = _draw_pdf_standard(
            ax,
            top_pdf_standard,
            base=top_standard_base,
            height=standard_height,
            minimum_height_fraction=standard_min_height_fraction,
            two_theta_range=two_theta_range,
            color=top_standard_color,
            line_width=line_width,
            label_x=label_x,
            label_y=top_standard_label_bottom + 0.5 * top_standard_label_band,
            label_vertical_alignment="center",
            label_font_size=annotation_font_size,
            show_label=show_pdf_labels,
        )
        handles.append(handle)
        labels.append(top_pdf_standard.label)

    ax.set_xlabel(r"2$\mathit{Theta}$ (Degree)")
    ylabel = r"$\mathit{Intensity}$ (a.u.)" if normalized else r"$\mathit{Intensity}$ (counts)"
    ax.set_ylabel(ylabel)
    if two_theta_range:
        ax.set_xlim(*two_theta_range)
    ax.set_yticks([])
    format_te_axis(ax, show_grid=False, tick_labelsize=tick_labelsize)
    ax.tick_params(axis="x", which="both", direction="out", top=False, bottom=True, labelsize=tick_labelsize)
    ax.tick_params(axis="y", which="both", left=False, right=False, labelleft=False)

    bottom = (
        0.0
        if pdf_standard
        else -0.05 * offset_step
    )
    top = (
        top_standard_label_top
        if top_standard_label_top is not None
        else trace_top + 0.25 * offset_step
    )
    ax.set_ylim(bottom, top)
    if ylim is not None:
        ax.set_ylim(*ylim)
    if fixed_aspect:
        apply_subplot_aspect(ax, subplot_aspect)

    if show_legend and handles:
        if legend_outside:
            fig.legend(
                handles,
                labels,
                loc="center left",
                bbox_to_anchor=(1.01, 0.5),
                fontsize=legend_font_size,
                frameon=False,
            )
            fig.tight_layout(rect=(0, 0, 0.82, 1))
        else:
            y_locks = axis_limit_locked(ylim) if ylim is not None else (True, False)
            place_legend_inside(
                ax,
                handles,
                labels,
                loc="upper left",
                fontsize=legend_font_size,
                fontsize_locked=explicit_legend_fs is not None,
                frameon=True,
                facecolor="white",
                edgecolor="black",
                framealpha=0.92,
                ylim_locked=y_locks,
                xlim_locked=(True, True),
            )
            fig.tight_layout()
    else:
        fig.tight_layout()

    if save_name:
        plot_path = save_figure(
            fig,
            save_name,
            save_dir=save_dir,
            formats=list(formats) if formats else None,
            transparent=transparent,
        )
        if close:
            plt.close(fig)
        return plot_path

    return fig, ax


def plot_xrd_raw_and_normalized(
    patterns: Sequence[XRDPattern],
    pdf_standard: PDFStandard | None,
    comparison_id: str,
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    two_theta_range: tuple[float | None, float | None] | None = DEFAULT_TWO_THETA_RANGE,
    ylim: tuple[float | None, float | None] | None = None,
    overlap: float = 1.05,
    colors: Sequence[str] | None = None,
    line_width: float = DEFAULT_XRD_LINE_WIDTH,
    subplot_aspect: str = DEFAULT_SUBPLOT_ASPECT,
    tick_labelsize: float = DEFAULT_TICK_LABEL_SIZE,
    legend_font_size: float | None = None,
    legend_outside: bool = False,
    show_legend: bool = False,
    fixed_aspect: bool = False,
    right_labels: bool = True,
    standard_color: str = "#d62728",
    close: bool = True,
    nest_in_comparison_dir: bool = True,
    top_pdf_standard: PDFStandard | None = None,
    top_standard_color: str = "#1f77b4",
    show_pdf_labels: bool = False,
    standard_height_fraction: float = DEFAULT_PDF_HEIGHT_FRACTION,
    color_set: str | None = None,
) -> dict[str, str]:
    save_dir = Path(save_dir)
    if nest_in_comparison_dir:
        save_dir = save_dir / safe_filename(comparison_id)
    raw_path = plot_xrd_comparison(
        patterns,
        pdf_standard=pdf_standard,
        top_pdf_standard=top_pdf_standard,
        top_standard_color=top_standard_color,
        show_pdf_labels=show_pdf_labels,
        standard_height_fraction=standard_height_fraction,
        normalized=False,
        save_name=f"{safe_filename(comparison_id)}_XRD_not_normalized.png",
        save_dir=save_dir,
        formats=formats,
        two_theta_range=two_theta_range,
        ylim=ylim,
        overlap=overlap,
        colors=colors,
        color_set=color_set,
        line_width=line_width,
        subplot_aspect=subplot_aspect,
        tick_labelsize=tick_labelsize,
        legend_font_size=legend_font_size,
        legend_outside=legend_outside,
        show_legend=show_legend,
        fixed_aspect=fixed_aspect,
        right_labels=right_labels,
        standard_color=standard_color,
        close=close,
    )
    normalized_path = plot_xrd_comparison(
        patterns,
        pdf_standard=pdf_standard,
        top_pdf_standard=top_pdf_standard,
        top_standard_color=top_standard_color,
        show_pdf_labels=show_pdf_labels,
        standard_height_fraction=standard_height_fraction,
        normalized=True,
        save_name=f"{safe_filename(comparison_id)}_XRD_normalized.png",
        save_dir=save_dir,
        formats=formats,
        two_theta_range=two_theta_range,
        ylim=ylim,
        overlap=overlap,
        colors=colors,
        color_set=color_set,
        line_width=line_width,
        subplot_aspect=subplot_aspect,
        tick_labelsize=tick_labelsize,
        legend_font_size=legend_font_size,
        legend_outside=legend_outside,
        show_legend=show_legend,
        fixed_aspect=fixed_aspect,
        right_labels=right_labels,
        standard_color=standard_color,
        close=close,
    )
    return {"not_normalized": raw_path, "normalized": normalized_path}


def _normalized_modes_for_output_mode(output_mode: str) -> list[tuple[str, bool]]:
    if output_mode == "both":
        return [("not_normalized", False), ("normalized", True)]
    if output_mode == "normalized":
        return [("normalized", True)]
    if output_mode == "not_normalized":
        return [("not_normalized", False)]
    raise ValueError("output_mode must be 'both', 'normalized', or 'not_normalized'")


def plot_xrd_separate(
    patterns: Sequence[XRDPattern],
    pdf_standard: PDFStandard | None,
    comparison_id: str,
    output_mode: str = "both",
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    two_theta_range: tuple[float | None, float | None] | None = DEFAULT_TWO_THETA_RANGE,
    ylim: tuple[float | None, float | None] | None = None,
    overlap: float = 1.05,
    colors: Sequence[str] | None = None,
    line_width: float = DEFAULT_XRD_LINE_WIDTH,
    subplot_aspect: str = DEFAULT_SUBPLOT_ASPECT,
    tick_labelsize: float = DEFAULT_TICK_LABEL_SIZE,
    legend_font_size: float | None = None,
    legend_outside: bool = False,
    show_legend: bool = False,
    fixed_aspect: bool = False,
    right_labels: bool = True,
    standard_color: str = "#d62728",
    close: bool = True,
    nest_in_comparison_dir: bool = True,
    top_pdf_standard: PDFStandard | None = None,
    top_standard_color: str = "#1f77b4",
    show_pdf_labels: bool = False,
    standard_height_fraction: float = DEFAULT_PDF_HEIGHT_FRACTION,
    color_set: str | None = None,
) -> dict[str, str]:
    save_dir = Path(save_dir)
    if nest_in_comparison_dir:
        save_dir = save_dir / safe_filename(comparison_id)
    save_dir = save_dir / "separate"
    paths: dict[str, str] = {}

    palette = get_colors(color_set, len(patterns))
    color_cycle = cycle(colors or palette)
    for pattern in patterns:
        sample_color = next(color_cycle)
        sample_key = safe_filename(pattern.sample_id or pattern.label)
        for suffix, normalized in _normalized_modes_for_output_mode(output_mode):
            plot_path = plot_xrd_comparison(
                [pattern],
                pdf_standard=pdf_standard,
                top_pdf_standard=top_pdf_standard,
                top_standard_color=top_standard_color,
                show_pdf_labels=show_pdf_labels,
                standard_height_fraction=standard_height_fraction,
                normalized=normalized,
                save_name=f"{sample_key}_XRD_{suffix}.png",
                save_dir=save_dir,
                formats=formats,
                two_theta_range=two_theta_range,
                ylim=ylim,
                overlap=overlap,
                colors=[sample_color],
                color_set=color_set,
                line_width=line_width,
                subplot_aspect=subplot_aspect,
                tick_labelsize=tick_labelsize,
                legend_font_size=legend_font_size,
                legend_outside=legend_outside,
                show_legend=show_legend,
                fixed_aspect=fixed_aspect,
                right_labels=right_labels,
                standard_color=standard_color,
                close=close,
            )
            paths[f"{sample_key}_{suffix}"] = plot_path

    return paths


def comparison_id_from_patterns(patterns: Sequence[XRDPattern]) -> str:
    patterns = list(patterns)
    if not patterns:
        return "xrd_comparison"
    if len(patterns) == 1:
        pattern = patterns[0]
        return pattern.batch_id or pattern.sample_id or pattern.source_path.stem or pattern.label

    batches = []
    for pattern in patterns:
        if pattern.batch_id and pattern.batch_id not in batches:
            batches.append(pattern.batch_id)
    if len(batches) == 1:
        return batches[0]
    if len(batches) > 1:
        return "_vs_".join(batches)

    source_dirs = sorted({pattern.source_path.parent.resolve() for pattern in patterns})
    if len(source_dirs) == 1:
        folder_name = source_dirs[0].name or source_dirs[0].parent.name
        return f"{folder_name}_{len(patterns)}patterns"

    stems = []
    for pattern in patterns:
        stem = pattern.sample_id or pattern.source_path.stem
        if stem and stem not in stems:
            stems.append(stem)
    if 1 < len(stems) <= 4:
        return "_vs_".join(stems)

    common_dir = Path(os.path.commonpath([str(path) for path in source_dirs]))
    return f"{common_dir.name or 'xrd'}_{len(patterns)}patterns"


def summarize_patterns(patterns: Iterable[XRDPattern]) -> list[dict[str, str]]:
    return [
        {
            "label": pattern.label,
            "batch_id": pattern.batch_id,
            "sample_id": pattern.sample_id,
            "source_path": str(pattern.source_path),
        }
        for pattern in patterns
    ]

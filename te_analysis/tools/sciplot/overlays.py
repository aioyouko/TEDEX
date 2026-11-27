"""Cross-cutting overlays for flexible plots: error bars/bands, reference guides, insets, and benchmark styling."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from te_analysis.tools.plot import (
    DEFAULT_LINE_WIDTH,
    DEFAULT_MARKER_SIZE,
    DEFAULT_TICK_LABEL_SIZE,
    format_te_axis,
)
from te_analysis.tools.sciplot.style import (
    apply_axis_options,
    optional_style,
)
from te_analysis.tools.sciplot.util import (
    as_list,
    optional_bool,
    optional_number,
    unique_in_order,
)


REFERENCE_PALETTE = (
    "#7F8C9A",
    "#9AA5B1",
    "#6E7B8B",
    "#8D99AE",
    "#A0AAB4",
    "#7B8794",
    "#95A0AB",
)
BENCHMARK_HIGHLIGHT_COLORS = (
    "#E64B35",
    "#3C5488",
    "#00A087",
    "#D55E00",
)


def extract_uncertainty(
    group_df: pd.DataFrame,
    plot: dict[str, Any],
) -> dict[str, np.ndarray | None]:
    """Extract optional x/y error arrays and lower/upper confidence bounds."""
    y = group_df["y"].to_numpy(dtype=float)
    x = group_df["x"].to_numpy(dtype=float)

    yerr: np.ndarray | None = None
    xerr: np.ndarray | None = None
    y_low: np.ndarray | None = None
    y_high: np.ndarray | None = None

    if "y_low" in group_df.columns and "y_high" in group_df.columns:
        low_vals = pd.to_numeric(group_df["y_low"], errors="coerce").to_numpy(dtype=float)
        high_vals = pd.to_numeric(group_df["y_high"], errors="coerce").to_numpy(dtype=float)
        if np.any(np.isfinite(low_vals)) and np.any(np.isfinite(high_vals)):
            y_low = low_vals
            y_high = high_vals
            lower_err = np.clip(y - low_vals, 0.0, None)
            upper_err = np.clip(high_vals - y, 0.0, None)
            yerr = np.vstack([lower_err, upper_err])

    if yerr is None and "yerr" in group_df.columns:
        err_vals = pd.to_numeric(group_df["yerr"], errors="coerce").to_numpy(dtype=float)
        if np.any(np.isfinite(err_vals)):
            err_vals = np.abs(err_vals)
            yerr = err_vals
            y_low = y - err_vals
            y_high = y + err_vals

    if yerr is None:
        pct = optional_number(optional_style(group_df, "yerr_pct"))
        if pct is None:
            pct = optional_number(plot.get("yerr_pct"))
        if pct is not None and pct > 0:
            err_vals = np.abs(y) * (pct / 100.0)
            yerr = err_vals
            y_low = y - err_vals
            y_high = y + err_vals

    if "xerr" in group_df.columns:
        xerr_vals = pd.to_numeric(group_df["xerr"], errors="coerce").to_numpy(dtype=float)
        if np.any(np.isfinite(xerr_vals)):
            xerr = np.abs(xerr_vals)

    if xerr is None:
        xpct = optional_number(optional_style(group_df, "xerr_pct"))
        if xpct is None:
            xpct = optional_number(plot.get("xerr_pct"))
        if xpct is not None and xpct > 0:
            xerr = np.abs(x) * (xpct / 100.0)

    return {
        "yerr": yerr,
        "xerr": xerr,
        "y_low": y_low,
        "y_high": y_high,
    }


def draw_uncertainty(
    ax: plt.Axes,
    x: np.ndarray,
    y: np.ndarray,
    group_df: pd.DataFrame,
    plot: dict[str, Any],
    *,
    color: Any,
    zorder: float = 2.0,
) -> None:
    """Render error bars and/or translucent confidence bands when present."""
    unc = extract_uncertainty(group_df, plot)
    yerr = unc["yerr"]
    xerr = unc["xerr"]
    y_low = unc["y_low"]
    y_high = unc["y_high"]

    if yerr is None and xerr is None and y_low is None:
        return

    mode = str(optional_style(group_df, "error_mode") or plot.get("error_mode", "bar")).strip().lower()
    if mode == "none":
        return

    if mode in {"band", "both", "fill", "shaded"} and y_low is not None and y_high is not None:
        valid = np.isfinite(x) & np.isfinite(y_low) & np.isfinite(y_high)
        if np.any(valid):
            band_alpha = float(plot.get("band_alpha", 0.18))
            ax.fill_between(
                x[valid],
                y_low[valid],
                y_high[valid],
                color=color,
                alpha=band_alpha,
                linewidth=0.0,
                zorder=max(1.0, zorder - 0.5),
            )

    if mode in {"bar", "bars", "both", "errorbar"} and (yerr is not None or xerr is not None):
        elinewidth = float(plot.get("error_linewidth", 1.1))
        capsize = float(plot.get("error_capsize", 3.5))
        ealpha = float(plot.get("error_alpha", 0.85))
        ax.errorbar(
            x,
            y,
            yerr=yerr,
            xerr=xerr,
            fmt="none",
            ecolor=color,
            elinewidth=elinewidth,
            capsize=capsize,
            capthick=elinewidth,
            alpha=ealpha,
            zorder=zorder,
        )


def _parse_line_guide(item: Any, axis_key: str) -> dict[str, Any] | None:
    if item is None or item == "":
        return None
    if isinstance(item, (int, float)):
        return {axis_key: float(item)}
    if isinstance(item, dict):
        return dict(item)
    parts = [part.strip() for part in str(item).split(",")]
    if not parts or not parts[0]:
        return None
    spec: dict[str, Any] = {axis_key: float(parts[0])}
    if len(parts) >= 2 and parts[1]:
        spec["label"] = parts[1]
    if len(parts) >= 3 and parts[2]:
        spec["color"] = parts[2]
    if len(parts) >= 4 and parts[3]:
        spec["linestyle"] = parts[3]
    return spec


def _parse_span_guide(item: Any, low_key: str, high_key: str) -> dict[str, Any] | None:
    if item is None or item == "":
        return None
    if isinstance(item, dict):
        return dict(item)
    parts = [part.strip() for part in str(item).split(",")]
    if len(parts) < 2:
        return None
    spec: dict[str, Any] = {
        low_key: float(parts[0]),
        high_key: float(parts[1]),
    }
    if len(parts) >= 3 and parts[2]:
        spec["label"] = parts[2]
    if len(parts) >= 4 and parts[3]:
        spec["color"] = parts[3]
    return spec


def apply_reference_guides(ax: plt.Axes, plot: dict[str, Any]) -> None:
    """Draw optional horizontal/vertical reference lines and shaded spans."""
    hlines = as_list(plot.get("hline")) + as_list(plot.get("hlines"))
    for raw in hlines:
        spec = _parse_line_guide(raw, "y")
        if not spec or "y" not in spec:
            continue
        y_val = float(spec["y"])
        color = spec.get("color", "#555555")
        linestyle = spec.get("linestyle", "--")
        linewidth = float(spec.get("linewidth", 1.15))
        alpha = float(spec.get("alpha", 0.85))
        ax.axhline(y_val, color=color, linestyle=linestyle, linewidth=linewidth, alpha=alpha, zorder=1.8)
        label = spec.get("label")
        if label:
            x_pos = float(spec.get("label_x", 0.97))
            ha = spec.get("ha", "right" if x_pos >= 0.5 else "left")
            va = spec.get("va", "bottom")
            ax.text(
                x_pos,
                y_val,
                str(label),
                transform=ax.get_yaxis_transform(),
                color=color,
                fontsize=float(spec.get("fontsize", 11.5)),
                ha=ha,
                va=va,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.82, "pad": 1.5},
                clip_on=False,
                zorder=5.5,
            )

    vlines = as_list(plot.get("vline")) + as_list(plot.get("vlines"))
    for raw in vlines:
        spec = _parse_line_guide(raw, "x")
        if not spec or "x" not in spec:
            continue
        x_val = float(spec["x"])
        color = spec.get("color", "#555555")
        linestyle = spec.get("linestyle", "--")
        linewidth = float(spec.get("linewidth", 1.5))
        alpha = float(spec.get("alpha", 0.85))
        ax.axvline(x_val, color=color, linestyle=linestyle, linewidth=linewidth, alpha=alpha, zorder=1.8)
        label = spec.get("label")
        if label:
            y_pos = float(spec.get("label_y", 0.95))
            ax.text(
                x_val,
                y_pos,
                f" {label}",
                transform=ax.get_xaxis_transform(),
                color=color,
                fontsize=float(spec.get("fontsize", 12.5)),
                ha=spec.get("ha", "left"),
                va=spec.get("va", "top"),
                clip_on=False,
            )

    hspans = as_list(plot.get("hspan")) + as_list(plot.get("hspans"))
    for raw in hspans:
        spec = _parse_span_guide(raw, "ymin", "ymax")
        if not spec:
            continue
        color = spec.get("color", "#8491B4")
        alpha = float(spec.get("alpha", 0.14))
        ax.axhspan(float(spec["ymin"]), float(spec["ymax"]), color=color, alpha=alpha, zorder=1.2)
        if spec.get("label"):
            y_mid = 0.5 * (float(spec["ymin"]) + float(spec["ymax"]))
            ax.text(
                float(spec.get("label_x", 0.98)),
                y_mid,
                str(spec["label"]),
                transform=ax.get_yaxis_transform(),
                color=spec.get("text_color", "#444444"),
                fontsize=float(spec.get("fontsize", 12.0)),
                ha="right",
                va="center",
            )

    vspans = as_list(plot.get("vspan")) + as_list(plot.get("vspans"))
    for raw in vspans:
        spec = _parse_span_guide(raw, "xmin", "xmax")
        if not spec:
            continue
        color = spec.get("color", "#8491B4")
        alpha = float(spec.get("alpha", 0.14))
        ax.axvspan(float(spec["xmin"]), float(spec["xmax"]), color=color, alpha=alpha, zorder=1.2)
        if spec.get("label"):
            x_mid = 0.5 * (float(spec["xmin"]) + float(spec["xmax"]))
            ax.text(
                x_mid,
                float(spec.get("label_y", 0.95)),
                str(spec["label"]),
                transform=ax.get_xaxis_transform(),
                color=spec.get("text_color", "#444444"),
                fontsize=float(spec.get("fontsize", 12.0)),
                ha="center",
                va="top",
            )


def is_benchmark_enabled(normalized: pd.DataFrame, plot: dict[str, Any]) -> bool:
    if str(plot.get("kind", "")).lower() == "benchmark":
        return True
    if optional_bool(plot.get("benchmark")):
        return True
    if plot.get("highlight"):
        return True
    if "role" in normalized.columns:
        roles = {str(val).strip().lower() for val in normalized["role"].dropna() if str(val).strip()}
        if roles & {"highlight", "reference", "literature", "this_work"}:
            return True
    return False


def resolve_benchmark_groups(normalized: pd.DataFrame, plot: dict[str, Any]) -> set[str]:
    """Determine which group names are highlighted ('This work') in benchmark mode."""
    explicit = {str(item).strip() for item in as_list(plot.get("highlight")) if str(item).strip()}
    if explicit:
        return explicit

    groups = unique_in_order(normalized["group"])
    role_highlights: set[str] = set()
    if "role" in normalized.columns:
        for group in groups:
            gdf = normalized[normalized["group"] == group]
            role = str(optional_style(gdf, "role") or "").strip().lower()
            if role in {"highlight", "this_work", "ours", "primary"}:
                role_highlights.add(group)
    if role_highlights:
        return role_highlights

    keyword_matches = {
        group
        for group in groups
        if any(token in group.lower() for token in ("this work", "our work", "present work", "this study", "本工作"))
    }
    if keyword_matches:
        return keyword_matches

    return {groups[-1]} if groups else set()


def benchmark_trace_kwargs(
    group: str,
    group_df: pd.DataFrame,
    plot: dict[str, Any],
    *,
    is_highlight: bool,
    highlight_index: int,
    ref_index: int,
    default_color: str,
    default_marker: str,
) -> dict[str, Any]:
    """Return Matplotlib styling kwargs differentiating highlighted vs literature traces."""
    explicit_color = optional_style(group_df, "color")
    explicit_marker = optional_style(group_df, "marker")
    explicit_lw = optional_number(optional_style(group_df, "line_width"))
    explicit_ms = optional_number(optional_style(group_df, "marker_size"))
    explicit_ls = optional_style(group_df, "linestyle")
    explicit_alpha = optional_number(optional_style(group_df, "alpha"))

    if is_highlight:
        color = explicit_color or BENCHMARK_HIGHLIGHT_COLORS[highlight_index % len(BENCHMARK_HIGHLIGHT_COLORS)]
        marker = explicit_marker or ("*" if highlight_index == 0 else default_marker)
        ms_scale = 1.35 if marker == "*" else 1.15
        return {
            "color": color,
            "marker": marker,
            "markersize": explicit_ms or (DEFAULT_MARKER_SIZE * ms_scale),
            "markerfacecolor": color,
            "markeredgecolor": color,
            "markeredgewidth": 1.4,
            "linewidth": explicit_lw or (DEFAULT_LINE_WIDTH * 1.18),
            "linestyle": explicit_ls or "-",
            "alpha": explicit_alpha if explicit_alpha is not None else 1.0,
            "zorder": 6.0 + highlight_index * 0.1,
        }

    color = explicit_color or REFERENCE_PALETTE[ref_index % len(REFERENCE_PALETTE)]
    marker = explicit_marker or default_marker
    return {
        "color": color,
        "marker": marker,
        "markersize": explicit_ms or (DEFAULT_MARKER_SIZE * 0.78),
        "markerfacecolor": "white",
        "markeredgecolor": color,
        "markeredgewidth": 1.3,
        "linewidth": explicit_lw or (DEFAULT_LINE_WIDTH * 0.68),
        "linestyle": explicit_ls or "--",
        "alpha": explicit_alpha if explicit_alpha is not None else 0.76,
        "zorder": 2.2 + ref_index * 0.02,
    }


def draw_end_labels(
    ax: plt.Axes,
    endpoints: list[dict[str, Any]],
    plot: dict[str, Any],
) -> None:
    """Place direct curve labels near the rightmost point with vertical collision avoidance."""
    if not endpoints:
        return
    y_low, y_high = ax.get_ylim()
    span = abs(y_high - y_low) or 1.0
    min_gap = span * float(plot.get("end_label_gap", 0.048))

    ordered = sorted(endpoints, key=lambda item: float(item["y"]))
    adjusted_y = [float(item["y"]) for item in ordered]
    for idx in range(1, len(adjusted_y)):
        if adjusted_y[idx] - adjusted_y[idx - 1] < min_gap:
            adjusted_y[idx] = adjusted_y[idx - 1] + min_gap

    fontsize = float(plot.get("end_label_font_size", 11.5))
    for item, y_target in zip(ordered, adjusted_y):
        fontweight = "bold" if item.get("is_highlight") else "normal"
        ax.annotate(
            str(item["label"]),
            xy=(float(item["x"]), float(item["y"])),
            xytext=(6, (y_target - float(item["y"])) / span * 120.0),
            textcoords="offset points",
            fontsize=fontsize,
            fontweight=fontweight,
            color=item["color"],
            va="center",
            ha="left",
            clip_on=False,
        )


def add_zoom_inset(
    ax: plt.Axes,
    plotted_traces: list[dict[str, Any]],
    plot: dict[str, Any],
) -> plt.Axes | None:
    """Attach an optional magnified inset axes to a 2D plot."""
    inset_cfg = plot.get("inset")
    if not isinstance(inset_cfg, dict):
        return None
    xlim = inset_cfg.get("xlim")
    ylim = inset_cfg.get("ylim")
    if xlim is None and ylim is None:
        return None

    bounds = inset_cfg.get("bounds", [0.52, 0.16, 0.42, 0.38])
    ax_ins = ax.inset_axes([float(val) for val in bounds], zorder=7)
    ax_ins.set_facecolor(inset_cfg.get("facecolor", "white"))

    for trace in plotted_traces:
        x_vals = trace["x"]
        y_vals = trace["y"]
        if trace.get("scatter_only"):
            ax_ins.scatter(
                x_vals,
                y_vals,
                color=trace["color"],
                marker=trace["marker"],
                s=(trace["markersize"] * 0.72) ** 2,
                facecolors=trace.get("markerfacecolor", trace["color"]),
                edgecolors=trace.get("markeredgecolor", trace["color"]),
                alpha=trace["alpha"],
            )
        else:
            ax_ins.plot(
                x_vals,
                y_vals,
                color=trace["color"],
                marker=trace["marker"],
                markersize=trace["markersize"] * 0.72,
                markerfacecolor=trace.get("markerfacecolor", trace["color"]),
                markeredgecolor=trace.get("markeredgecolor", trace["color"]),
                linewidth=trace["linewidth"] * 0.82,
                linestyle=trace["linestyle"],
                alpha=trace["alpha"],
            )

    format_te_axis(ax_ins, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.78)
    apply_axis_options(ax_ins, inset_cfg)
    if optional_bool(inset_cfg.get("connectors"), default=True):
        ax.indicate_inset_zoom(ax_ins, edgecolor=inset_cfg.get("edgecolor", "#555555"), alpha=0.68, linewidth=0.95)
    return ax_ins

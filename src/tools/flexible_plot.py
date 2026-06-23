"""
Recipe-driven plotting for quick comparisons from loosely structured tables.

The module turns CSV/XLSX data with inconsistent column names into a small
normalized table, then renders a few reusable plot recipes with the existing
TE publication style.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.matplotlib_backend import configure_matplotlib_backend, show_interactive_figures  # noqa: E402

configure_matplotlib_backend()

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import ticker

from src.tools.plot import (  # noqa: E402
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


SINGLE_TICK_LABEL_SIZE = 10
SUMMARY_TICK_LABEL_SIZE = 9
TICK_FORMAT_CHOICES = ("auto", "plain", "scientific")
BAR_PLOT_KINDS = {"bar", "grouped_bar"}
DEFAULT_LEGEND_FRAME = True
DEFAULT_LEGEND_EDGE_COLOR = "black"
DEFAULT_LEGEND_FACE_COLOR = "white"
DEFAULT_LEGEND_FRAME_ALPHA = 1.0
DEFAULT_LEGEND_FRAME_LINEWIDTH = 0.8


SEMANTIC_ALIASES = {
    "sample": [
        "sample",
        "sample id",
        "sample_id",
        "specimen",
        "specimen id",
        "id",
        "material",
        "material name",
        "composition",
    ],
    "condition": [
        "condition",
        "batch",
        "source class",
        "source",
        "group",
        "series",
    ],
    "temperature": [
        "temperature",
        "temp",
        "t",
        "t k",
        "temp k",
        "temperature k",
        "temp / k",
        "temperature / k",
    ],
    "seebeck": [
        "seebeck",
        "seebeck coefficient",
        "s",
        "s uv k",
        "s uv/k",
        "s (uv/k)",
        "seebeck_uv_k",
        "seebeck microv k",
        "seebeck_microv_k",
    ],
    "conductivity": [
        "conductivity",
        "electrical conductivity",
        "sigma",
        "sigma s cm",
        "sigma s/cm",
        "sigma [s cm-1]",
        "ec",
        "ec s per m",
        "conductivity_s_cm",
        "conductivity_s_per_m",
    ],
    "power_factor": [
        "power factor",
        "power_factor",
        "pf",
        "pf uw cm k2",
        "pf uw/cm/k2",
    ],
    "thermal_conductivity": [
        "thermal conductivity",
        "kappa",
        "k total",
        "k-total",
        "ktot",
        "k_total",
        "k-total w/m-k",
        "k_total w/mk",
    ],
    "zt": [
        "zt",
        "z t",
        "zt value",
        "ztmax",
        "zt max",
        "best zt",
    ],
}


GREEK_TRANSLATION = str.maketrans(
    {
        "µ": "u",
        "μ": "u",
        "σ": "sigma",
        "Σ": "sigma",
        "κ": "kappa",
        "Κ": "kappa",
        "ρ": "rho",
        "Ω": "ohm",
        "°": "",
    }
)


def normalize_name(value: Any) -> str:
    """Return a loose matching key for column names and aliases."""
    text = str(value).translate(GREEK_TRANSLATION).lower()
    text = text.replace("micro", "u")
    return re.sub(r"[^a-z0-9]+", "", text)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def candidate_names(selector: Any, semantic: str | None = None) -> list[str]:
    candidates: list[str] = []

    if isinstance(selector, dict):
        for key in ("column", "name"):
            candidates.extend(str(item) for item in as_list(selector.get(key)) if item)
        candidates.extend(str(item) for item in as_list(selector.get("aliases")) if item)
        semantic = selector.get("semantic", semantic)
    else:
        candidates.extend(str(item) for item in as_list(selector) if item)

    if semantic:
        candidates.append(semantic)
        candidates.extend(SEMANTIC_ALIASES.get(semantic, []))

    seen = set()
    unique = []
    for candidate in candidates:
        key = normalize_name(candidate)
        if key and key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def resolve_column(
    df: pd.DataFrame,
    selector: Any,
    *,
    semantic: str | None = None,
    required: bool = True,
    role: str = "column",
) -> str | None:
    """Resolve a recipe selector to an actual dataframe column."""
    candidates = candidate_names(selector, semantic)
    if not candidates:
        if required:
            raise ValueError(f"No selector provided for {role}")
        return None

    columns = list(df.columns)
    normalized_to_column = {normalize_name(column): column for column in columns}

    for candidate in candidates:
        if candidate in df.columns:
            return candidate
        normalized = normalize_name(candidate)
        if normalized in normalized_to_column:
            return normalized_to_column[normalized]

    normalized_columns = [(normalize_name(column), column) for column in columns]
    for candidate in candidates:
        normalized = normalize_name(candidate)
        if len(normalized) <= 2:
            continue
        for normalized_column, column in normalized_columns:
            if normalized in normalized_column or normalized_column in normalized:
                return column

    if required:
        available = ", ".join(str(column) for column in columns)
        wanted = ", ".join(candidates)
        raise ValueError(f"Could not resolve {role}. Wanted one of [{wanted}]. Available columns: {available}")
    return None


def selector_label(selector: Any, default: str) -> str:
    if isinstance(selector, dict):
        return str(selector.get("label") or selector.get("title") or default)
    return default


def selector_scale(selector: Any) -> float:
    if isinstance(selector, dict):
        return float(selector.get("scale", 1.0))
    return 1.0


def selector_offset(selector: Any) -> float:
    if isinstance(selector, dict):
        return float(selector.get("offset", 0.0))
    return 0.0


def transform_values(series: pd.Series, selector: Any) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values * selector_scale(selector) + selector_offset(selector)


def categorical_x_enabled(plot: dict[str, Any]) -> bool:
    return bool(plot.get("categorical_x", str(plot.get("kind", "line")) in BAR_PLOT_KINDS))


def resolve_path(path: str | Path, workspace: Path) -> Path:
    raw_path = Path(path).expanduser()
    if raw_path.is_absolute():
        return raw_path
    return workspace / raw_path


def read_source_table(source: Any, workspace: Path) -> pd.DataFrame:
    source_config = {"path": source} if isinstance(source, str) else dict(source)
    path = resolve_path(source_config["path"], workspace)
    suffix = path.suffix.lower()

    read_csv_kwargs = {}
    for key in ("skiprows", "header", "names", "comment", "encoding"):
        if key in source_config:
            read_csv_kwargs[key] = source_config[key]

    if suffix == ".csv":
        df = pd.read_csv(path, **read_csv_kwargs)
    elif suffix == ".tsv":
        df = pd.read_csv(path, sep="\t", **read_csv_kwargs)
    elif suffix in {".txt", ".dat"}:
        df = pd.read_csv(
            path,
            sep=source_config.get("sep", r"\s+"),
            engine=source_config.get("engine", "python"),
            **read_csv_kwargs,
        )
    elif suffix in {".xlsx", ".xls"}:
        read_excel_kwargs = {}
        for key in ("skiprows", "header", "names"):
            if key in source_config:
                read_excel_kwargs[key] = source_config[key]
        df = pd.read_excel(path, sheet_name=source_config.get("sheet", 0), **read_excel_kwargs)
    else:
        raise ValueError(f"Unsupported source file type: {path}")

    df = df.copy()
    df["__source_file"] = path.name
    for key, value in source_config.get("metadata", {}).items():
        df[key] = value
    return df


def load_recipe_data(recipe: dict[str, Any], workspace: Path) -> pd.DataFrame:
    sources = recipe.get("data") or recipe.get("sources")
    if not sources:
        raise ValueError("Recipe needs a data or sources list")

    frames = [read_source_table(source, workspace) for source in as_list(sources)]
    if not frames:
        raise ValueError("No input data was loaded")
    return pd.concat(frames, ignore_index=True, sort=False)


def series_source_table(
    spec: dict[str, Any],
    recipe: dict[str, Any],
    workspace: Path,
    fallback_raw: pd.DataFrame | None,
) -> pd.DataFrame:
    source = spec.get("source", spec.get("data"))
    if source is not None:
        frames = [read_source_table(item, workspace) for item in as_list(source)]
        return pd.concat(frames, ignore_index=True, sort=False)
    if fallback_raw is not None:
        return fallback_raw
    return load_recipe_data(recipe, workspace)


def merge_selector(base: Any, override: dict[str, Any]) -> Any:
    if isinstance(base, dict):
        merged = dict(base)
    else:
        merged = {"column": base}

    for key in ("semantic", "scale", "offset", "label", "aliases"):
        if key in override and key not in merged:
            merged[key] = override[key]
    return merged


def series_y_selector(spec: dict[str, Any]) -> Any:
    if "y" in spec:
        return merge_selector(spec["y"], spec)
    return spec


def fixed_or_column_values(
    df: pd.DataFrame,
    selector: Any,
    *,
    default: Any,
    role: str,
) -> pd.Series:
    if selector is None:
        return pd.Series([default] * len(df), index=df.index)

    if isinstance(selector, dict):
        if "value" in selector:
            return pd.Series([selector["value"]] * len(df), index=df.index)
        column = resolve_column(df, selector, required=False, role=role)
        if column:
            return df[column].astype(str)
        return pd.Series([default] * len(df), index=df.index)

    if isinstance(selector, str) and selector in df.columns:
        return df[selector].astype(str)
    return pd.Series([selector] * len(df), index=df.index)


def first_defined(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is not None:
            return value
    return default


def optional_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


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


def build_normalized_table(recipe: dict[str, Any], workspace: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build one long table: x, y, property, group, label, source."""
    plot = recipe.get("plot", {})
    categorical_x = categorical_x_enabled(plot)
    fallback_raw = load_recipe_data(recipe, workspace) if recipe.get("data") or recipe.get("sources") else None
    global_x_selector = plot.get("x")
    if global_x_selector is None:
        raise ValueError("plot.x is required")
    group_selector = plot.get("group")
    label_selector = plot.get("label")
    condition_selector = plot.get("condition")

    series_specs = plot.get("series") or [plot.get("y")]
    series_specs = [spec for spec in series_specs if spec]
    if not series_specs:
        raise ValueError("Recipe needs plot.series or plot.y")

    rows = []
    property_labels: dict[str, str] = {}

    for series_index, spec in enumerate(series_specs):
        if not isinstance(spec, dict):
            spec = {"column": spec}
        raw = series_source_table(spec, recipe, workspace, fallback_raw)

        x_selector = spec.get("x", global_x_selector)
        x_semantic = x_selector.get("semantic") if isinstance(x_selector, dict) else None
        x_col = resolve_column(raw, x_selector, semantic=x_semantic, role="x")
        x_raw = raw[x_col]
        if categorical_x:
            x_values = pd.to_numeric(x_raw, errors="coerce")
            x_category_values = x_raw.astype("string")
        else:
            x_values = transform_values(x_raw, x_selector)
            x_category_values = x_values.map(lambda value: plain_number_label(float(value)) if pd.notna(value) else "")

        y_selector = series_y_selector(spec)
        semantic = y_selector.get("semantic") if isinstance(y_selector, dict) else spec.get("semantic")
        y_col = resolve_column(raw, y_selector, semantic=semantic, role=spec.get("property", "y"))

        group_values = fixed_or_column_values(
            raw,
            first_defined(spec.get("group"), spec.get("group_value"), default=group_selector),
            default=spec.get("legend_label") or spec.get("series_label") or raw["__source_file"].iloc[0],
            role="group",
        )
        legend_values = fixed_or_column_values(
            raw,
            first_defined(spec.get("legend_label"), spec.get("series_label"), spec.get("group_value"), default=None),
            default=group_values.iloc[0] if len(group_values) else raw["__source_file"].iloc[0],
            role="legend_label",
        )
        label_values = fixed_or_column_values(
            raw,
            spec.get("point_label", spec.get("annotation_label", label_selector)),
            default="",
            role="label",
        )
        condition_values = fixed_or_column_values(
            raw,
            spec.get("condition", condition_selector),
            default="",
            role="condition",
        )

        property_name = str(spec.get("property") or (y_selector.get("property") if isinstance(y_selector, dict) else None) or semantic or y_col)
        property_label = str(
            spec.get("ylabel")
            or spec.get("label")
            or (y_selector.get("label") if isinstance(y_selector, dict) else None)
            or property_name
        )
        property_labels[property_name] = property_label

        working = pd.DataFrame(
            {
                "x": x_values,
                "x_category": x_category_values,
                "y": transform_values(raw[y_col], y_selector),
                "property": property_name,
                "group": group_values.astype(str),
                "legend_label": legend_values.astype(str),
                "label": label_values.astype(str),
                "condition": condition_values.astype(str),
                "source": raw["__source_file"].astype(str),
            }
        )
        working["x_source_column"] = x_col
        working["y_source_column"] = y_col
        working["series_order"] = series_index
        for style_key in ("color", "marker", "linestyle", "line_width", "marker_size", "alpha"):
            working[style_key] = spec.get(style_key, "")
        rows.append(working)

    normalized = pd.concat(rows, ignore_index=True)
    object_columns = normalized.select_dtypes(include="object").columns
    normalized.loc[:, object_columns] = normalized.loc[:, object_columns].mask(
        normalized.loc[:, object_columns] == ""
    )
    drop_subset = ["x_category", "y"] if categorical_x else ["x", "y"]
    normalized = normalized.dropna(subset=drop_subset)

    x_categories: list[str] = []
    if categorical_x:
        x_categories = [str(value) for value in as_list(first_defined(plot.get("x_order"), plot.get("category_order")))]
        seen_x_categories = set(x_categories)
        for category in unique_in_order(normalized["x_category"]):
            if category not in seen_x_categories:
                x_categories.append(category)
                seen_x_categories.add(category)
        normalized["x_category"] = pd.Categorical(normalized["x_category"].astype(str), categories=x_categories, ordered=True)
        normalized["x"] = normalized["x_category"].cat.codes.astype(float)
        normalized["x_category"] = normalized["x_category"].astype(str)

    group_order = plot.get("group_order", plot.get("order"))
    if group_order:
        normalized["group"] = pd.Categorical(normalized["group"], categories=group_order, ordered=True)
    normalized = normalized.sort_values(["property", "series_order", "group", "x"], kind="mergesort")
    if group_order:
        normalized["group"] = normalized["group"].astype(str)

    metadata = {
        "x_label": selector_label(x_selector, x_col),
        "property_labels": property_labels,
        "kind": plot.get("kind", "line"),
        "title": plot.get("title", recipe.get("name", "")),
        "categorical_x": categorical_x,
        "x_categories": x_categories,
    }
    return normalized, metadata


def unique_in_order(values: pd.Series) -> list[str]:
    return [str(value) for value in pd.Series(values).dropna().drop_duplicates().tolist()]


def unique_properties_by_series_order(normalized: pd.DataFrame) -> list[str]:
    ordered = normalized.sort_values("series_order", kind="mergesort")
    return unique_in_order(ordered["property"])


def optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def optional_style(group_df: pd.DataFrame, key: str) -> Any:
    if key not in group_df.columns:
        return None
    values = group_df[key].dropna()
    values = values[values.astype(str) != ""]
    if values.empty:
        return None
    return values.iloc[0]


def plain_number_label(value: float) -> str:
    if not np.isfinite(value):
        return ""
    if abs(value - round(value)) < 1e-10:
        return str(int(round(value)))
    return f"{value:.10g}"


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


def output_config(recipe: dict[str, Any], workspace: Path) -> tuple[Path, str, list[str]]:
    output = recipe.get("output", {})
    output_dir = resolve_path(output.get("dir", "outputs/figures/flexible"), workspace)
    stem = output.get("stem") or re.sub(r"[^a-zA-Z0-9_]+", "_", recipe.get("name", "flexible_plot")).strip("_")
    formats = output.get("formats", ["png", "pdf"])
    return output_dir, stem, formats


def recipe_source_paths(recipe: dict[str, Any], workspace: Path) -> list[Path]:
    sources: list[Any] = []
    sources.extend(as_list(recipe.get("data")))
    sources.extend(as_list(recipe.get("sources")))

    for spec in as_list(recipe.get("plot", {}).get("series")):
        if isinstance(spec, dict):
            sources.extend(as_list(spec.get("source", spec.get("data"))))

    paths = []
    seen = set()
    for source in sources:
        if not source:
            continue
        source_config = {"path": source} if isinstance(source, (str, Path)) else dict(source)
        source_path = source_config.get("path")
        if not source_path:
            continue
        resolved = resolve_path(source_path, workspace)
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            paths.append(resolved)
    return paths


def recipe_data_dirs(recipe: dict[str, Any], workspace: Path) -> list[Path]:
    dirs = []
    seen = set()
    for source_path in recipe_source_paths(recipe, workspace):
        data_dir = source_path.parent
        key = str(data_dir)
        if key not in seen:
            seen.add(key)
            dirs.append(data_dir)
    return dirs


def copy_outputs_to_data_dirs(
    output_paths: list[Path],
    recipe: dict[str, Any],
    workspace: Path,
) -> list[str]:
    if not recipe.get("output", {}).get("copy_to_data_dir", False):
        return []

    copied_paths = []
    for data_dir in recipe_data_dirs(recipe, workspace):
        data_dir.mkdir(parents=True, exist_ok=True)
        for output_path in output_paths:
            if not output_path:
                continue
            target = data_dir / output_path.name
            if output_path.resolve() == target.resolve():
                continue
            shutil.copy2(output_path, target)
            copied_paths.append(str(target))
    return copied_paths


def save_outputs(
    fig: plt.Figure,
    normalized: pd.DataFrame,
    recipe: dict[str, Any],
    workspace: Path,
) -> dict[str, list[str] | str]:
    output_dir, stem, formats = output_config(recipe, workspace)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_figure(fig, stem, save_dir=str(output_dir), formats=formats)
    figure_paths = [str(output_dir / f"{stem}.{str(fmt).lstrip('.').lower()}") for fmt in formats]

    output = recipe.get("output", {})
    normalized_path = ""
    if output.get("normalized_csv", True):
        normalized_path = str(output_dir / f"{stem}_normalized.csv")
        normalized.to_csv(normalized_path, index=False)

    output_paths = [Path(path) for path in figure_paths]
    if normalized_path:
        output_paths.append(Path(normalized_path))
    data_dir_copies = copy_outputs_to_data_dirs(output_paths, recipe, workspace)

    return {
        "figures": figure_paths,
        "normalized_csv": normalized_path,
        "data_dir_copies": data_dir_copies,
    }


def plot_recipe(recipe: dict[str, Any], workspace: str | Path = ".", show: bool = True) -> dict[str, Any]:
    workspace_path = Path(workspace).expanduser().resolve()
    normalized, metadata = build_normalized_table(recipe, workspace_path)
    kind = str(recipe.get("plot", {}).get("kind", "line"))
    if kind not in PLOTTERS:
        raise ValueError(f"Unsupported plot kind: {kind}. Available: {', '.join(PLOTTERS)}")

    fig, axes = PLOTTERS[kind](normalized, metadata, recipe)
    saved = save_outputs(fig, normalized, recipe, workspace_path)
    if show:
        show_interactive_figures()
    plt.close(fig)
    return {
        "kind": kind,
        "rows": int(len(normalized)),
        "axes": str(type(axes).__name__),
        **saved,
    }


def load_recipe(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_cli_value(raw: str) -> int | float | str:
    text = str(raw)
    try:
        if re.fullmatch(r"[-+]?\d+", text):
            return int(text)
        return float(text)
    except ValueError:
        return text


def parse_cli_source(raw: str, args: argparse.Namespace, index: int) -> dict[str, Any]:
    path = raw
    sheet = value_for_index(args.sheet, index)
    if "::" in raw:
        path, inline_sheet = raw.rsplit("::", 1)
        sheet = inline_sheet

    source: dict[str, Any] = {"path": path}
    if sheet is not None:
        source["sheet"] = parse_cli_value(sheet)
    if args.sep is not None:
        source["sep"] = args.sep
    if args.skiprows is not None:
        source["skiprows"] = args.skiprows
    if args.header is not None:
        source["header"] = None if str(args.header).lower() == "none" else parse_cli_value(args.header)
    return source


def cli_data_locations(args: argparse.Namespace) -> list[str]:
    return [*(args.data_paths or []), *(args.data or [])]


def cli_source_configs(args: argparse.Namespace) -> list[dict[str, Any]]:
    return [parse_cli_source(raw, args, index) for index, raw in enumerate(cli_data_locations(args))]


def value_for_index(values: list[Any] | None, index: int, default: Any = None) -> Any:
    if not values:
        return default
    if len(values) == 1:
        return values[0]
    if index < len(values):
        return values[index]
    return default


def parse_axis_limit(values: list[str] | None) -> list[float | None] | None:
    if not values:
        return None
    parsed = []
    for value in values:
        clean_value = str(value).strip().lower()
        if clean_value in {"auto", "none", "null", ""}:
            parsed.append(None)
        else:
            parsed.append(float(value))
    if parsed[0] is None and parsed[1] is None:
        return None
    if parsed[0] is not None and parsed[1] is not None and parsed[0] >= parsed[1]:
        raise ValueError("Axis lower limit must be smaller than upper limit")
    return parsed


def parse_text_item(raw: str, *, coords: str = "data") -> dict[str, Any]:
    parts = [part.strip() for part in raw.split(",", 3)]
    if len(parts) < 3:
        raise ValueError("--text values must look like x,y,text or x,y,text,color")

    item = {
        "x": float(parts[0]),
        "y": float(parts[1]),
        "text": parts[2],
    }
    if coords == "axes":
        item["coords"] = "axes"
    if len(parts) == 4 and parts[3]:
        item["color"] = parts[3]
    return item


def repeated_option(values: list[Any] | None, series_count: int, option_name: str) -> list[Any]:
    if not values:
        return [None] * series_count
    if len(values) == 1:
        return values * series_count
    if len(values) == series_count:
        return values
    raise ValueError(f"{option_name} expects either 1 value or {series_count} values, got {len(values)}")


def mapped_series_option(
    series: list[Any],
    values: list[Any] | None,
    option_name: str,
    *,
    preference: tuple[str, ...] = ("template", "source"),
) -> list[Any]:
    if not values:
        return [None] * len(series)
    if len(values) == 1:
        return values * len(series)
    if len(values) == len(series):
        return values

    series_dicts = [spec for spec in series if isinstance(spec, dict)]
    if len(series_dicts) == len(series):
        for dimension in preference:
            count_key = f"__{dimension}_count"
            index_key = f"__{dimension}_index"
            counts = {spec.get(count_key) for spec in series_dicts}
            if len(counts) == 1:
                count = next(iter(counts))
                if isinstance(count, int) and count == len(values):
                    return [values[int(spec[index_key])] for spec in series_dicts]

    raise ValueError(f"{option_name} expects either 1 value or {len(series)} values, got {len(values)}")


def option_present(argv: list[str], *option_names: str) -> bool:
    for raw in argv:
        for option_name in option_names:
            if raw == option_name or raw.startswith(f"{option_name}="):
                return True
    return False


def selector_with_column(selector: Any, column: str, label: str | None = None) -> dict[str, Any]:
    if isinstance(selector, dict):
        updated = dict(selector)
    else:
        updated = {}
    updated["column"] = column
    if label is not None:
        updated["label"] = label
    return updated


def expand_series_for_bar_overrides(series: list[Any], values: list[str] | None, plot_kind: str) -> None:
    if not values or plot_kind not in BAR_PLOT_KINDS or len(values) <= len(series) or not series:
        return

    original_count = len(series)
    for index in range(original_count, len(values)):
        template = copy.deepcopy(series[index % original_count])
        if not isinstance(template, dict):
            template = {"column": template}
        # Explicit template styles are meaningful for the original slots, but
        # cloned extra bars should fall back to the normal style cycle.
        for style_key in ("color", "marker", "linestyle", "line_width", "marker_size", "alpha"):
            template.pop(style_key, None)
        series.append(template)


def update_series_values(series: list[Any], values: list[Any] | None, key: str, option_name: str) -> None:
    if not values:
        return
    preference = ("source", "template") if key in {"group_value", "legend_label", "series_label"} else ("template", "source")
    mapped_values = mapped_series_option(series, values, option_name, preference=preference)
    for spec, value in zip(series, mapped_values):
        if isinstance(spec, dict) and value is not None:
            if key in {"group_value", "legend_label", "series_label"}:
                spec[key] = {"value": value}
            else:
                spec[key] = value


def update_series_y_columns(
    series: list[Any],
    values: list[str] | None,
    ylabel: str | None = None,
    *,
    default_legend_from_y: bool = False,
) -> None:
    if not values:
        return
    mapped_values = mapped_series_option(series, values, "--y", preference=("template", "source"))
    for index, value in enumerate(mapped_values):
        if not isinstance(series[index], dict):
            series[index] = {"column": series[index]}
        series[index]["y"] = selector_with_column(series[index].get("y", series[index]), value, ylabel)
        if default_legend_from_y:
            series[index]["group_value"] = {"value": value}
            series[index]["legend_label"] = {"value": value}


def update_series_x_columns(series: list[Any], values: list[str] | None, xlabel: str | None = None) -> None:
    if not values or len(values) == 1:
        return
    mapped_values = mapped_series_option(series, values, "--x", preference=("source", "template"))
    for index, value in enumerate(mapped_values):
        if not isinstance(series[index], dict):
            series[index] = {"column": series[index]}
        series[index]["x"] = selector_with_column(series[index].get("x"), value, xlabel)


def override_recipe_data(recipe: dict[str, Any], sources: list[dict[str, Any]]) -> None:
    if not sources:
        return

    plot = recipe.get("plot", {})
    series = plot.get("series") or []
    series_dicts = [spec for spec in series if isinstance(spec, dict)]
    has_series_sources = any("source" in spec or "data" in spec for spec in series_dicts)

    if has_series_sources and len(sources) == len(series):
        for spec, source in zip(series_dicts, sources):
            spec["source"] = source
            spec.pop("data", None)
        recipe.pop("data", None)
        recipe.pop("sources", None)
    elif len(sources) > 1 and len(series_dicts) == 1:
        template = series_dicts[0]
        expanded_series = []
        for source in sources:
            expanded = copy.deepcopy(template)
            expanded["source"] = source
            expanded.pop("data", None)
            # Let multi-file traces use the project color/marker cycle instead
            # of copying one template trace style onto every input file.
            expanded.pop("color", None)
            expanded.pop("marker", None)
            source_label = Path(str(source["path"])).stem
            expanded["group_value"] = {"value": source_label}
            expanded["legend_label"] = {"value": source_label}
            expanded_series.append(expanded)
        plot["series"] = expanded_series
        recipe.pop("data", None)
        recipe.pop("sources", None)
    elif len(sources) > 1 and len(series_dicts) > 1:
        expanded_series = []
        source_count = len(sources)
        template_count = len(series_dicts)
        for source_index, source in enumerate(sources):
            source_label = Path(str(source["path"])).stem
            for template_index, template in enumerate(series_dicts):
                expanded = copy.deepcopy(template)
                expanded["source"] = source
                expanded.pop("data", None)
                expanded["__source_index"] = source_index
                expanded["__source_count"] = source_count
                expanded["__template_index"] = template_index
                expanded["__template_count"] = template_count
                expanded.pop("color", None)
                expanded.pop("marker", None)
                expanded["group_value"] = {"value": source_label}
                expanded["legend_label"] = {"value": source_label}
                expanded_series.append(expanded)
        plot["series"] = expanded_series
        plot.setdefault("axis_color_mode", "plain")
        recipe.pop("data", None)
        recipe.pop("sources", None)
    else:
        recipe["data"] = sources


def override_recipe_from_cli(
    recipe: dict[str, Any],
    args: argparse.Namespace,
    argv: list[str],
) -> dict[str, Any]:
    updated = copy.deepcopy(recipe)
    plot = updated.setdefault("plot", {})
    output = updated.setdefault("output", {})

    override_recipe_data(updated, cli_source_configs(args))

    if option_present(argv, "--name") and args.name:
        updated["name"] = args.name
    if option_present(argv, "--kind", "--plot-kind") and args.kind:
        plot["kind"] = args.kind

    series = plot.get("series")
    if series is None and plot.get("y") is not None:
        series = [plot["y"]]
        plot["series"] = series
        plot.pop("y", None)

    plot_kind = str(plot.get("kind", "line"))
    if series and option_present(argv, "--y") and args.y:
        expand_series_for_bar_overrides(series, args.y, plot_kind)

    if option_present(argv, "--x") and args.x:
        plot["x"] = selector_with_column(plot.get("x"), args.x[0], args.xlabel if option_present(argv, "--xlabel") else None)
        if series:
            update_series_x_columns(series, args.x, args.xlabel if option_present(argv, "--xlabel") else None)
    if option_present(argv, "--y") and args.y:
        if series:
            update_series_y_columns(
                series,
                args.y,
                args.ylabel if option_present(argv, "--ylabel") else None,
                default_legend_from_y=plot_kind in BAR_PLOT_KINDS and not option_present(argv, "--label", "--series-label"),
            )
        else:
            plot["y"] = selector_with_column(plot.get("y"), args.y[0], args.ylabel if option_present(argv, "--ylabel") else None)

    scalar_plot_options = [
        (("--xlabel",), "xlabel", args.xlabel),
        (("--ylabel",), "ylabel", args.ylabel),
        (("--right-ylabel",), "right_ylabel", args.right_ylabel),
        (("--legend",), "legend", args.legend),
        (("--legend-loc",), "legend_loc", args.legend_loc),
        (("--legend-title",), "legend_title", args.legend_title),
        (("--legend-font-size",), "legend_font_size", args.legend_font_size),
        (("--xscale",), "xscale", args.xscale),
        (("--yscale",), "yscale", args.yscale),
        (("--right-yscale", "--right-yscal", "--right-y-scale"), "right_yscale", args.right_yscale),
        (("--x-tick-format",), "x_tick_format", args.x_tick_format),
        (("--y-tick-format",), "y_tick_format", args.y_tick_format),
        (("--right-y-tick-format",), "right_y_tick_format", args.right_y_tick_format),
        (("--x-major",), "x_major", args.x_major),
        (("--x-minor",), "x_minor", args.x_minor),
        (("--y-major",), "y_major", args.y_major),
        (("--y-minor",), "y_minor", args.y_minor),
        (("--right-y-major",), "right_y_major", args.right_y_major),
        (("--right-y-minor",), "right_y_minor", args.right_y_minor),
        (("--panel-label",), "panel_label", args.panel_label),
        (("--subplot-aspect",), "subplot_aspect", args.subplot_aspect),
    ]
    for option_names, plot_key, value in scalar_plot_options:
        if option_present(argv, *option_names) and value is not None:
            plot[plot_key] = value

    if option_present(argv, "--xlim"):
        plot["xlim"] = parse_axis_limit(args.xlim)
    if option_present(argv, "--ylim"):
        plot["ylim"] = parse_axis_limit(args.ylim)
    if option_present(argv, "--right-ylim"):
        plot["right_ylim"] = parse_axis_limit(args.right_ylim)

    text_items = []
    for raw in args.text or []:
        text_items.append(parse_text_item(raw, coords="data"))
    for raw in args.text_axes or []:
        text_items.append(parse_text_item(raw, coords="axes"))
    if text_items:
        plot["text"] = text_items

    if series:
        if option_present(argv, "--label", "--series-label"):
            update_series_values(series, args.label, "group_value", "--label")
            update_series_values(series, args.label, "legend_label", "--label")
        if option_present(argv, "--color"):
            update_series_values(series, args.color, "color", "--color")
        if option_present(argv, "--marker"):
            update_series_values(series, args.marker, "marker", "--marker")
        if option_present(argv, "--line-width"):
            update_series_values(series, args.line_width, "line_width", "--line-width")
        if option_present(argv, "--marker-size"):
            update_series_values(series, args.marker_size, "marker_size", "--marker-size")
        if option_present(argv, "--linestyle"):
            update_series_values(series, args.linestyle, "linestyle", "--linestyle")

    if option_present(argv, "--output-dir"):
        output["dir"] = args.output_dir
    if option_present(argv, "--stem"):
        output["stem"] = args.stem
    if option_present(argv, "--formats", "--format"):
        output["formats"] = args.formats
    if option_present(argv, "--normalized-csv"):
        output["normalized_csv"] = True
    if option_present(argv, "--no-normalized-csv"):
        output["normalized_csv"] = False
    if option_present(argv, "--copy-to-data-dir"):
        output["copy_to_data_dir"] = True
    if option_present(argv, "--no-copy-to-data-dir"):
        output["copy_to_data_dir"] = False

    return updated


def make_cli_series(args: argparse.Namespace, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    data_count = len(sources)
    y_columns = args.y or []
    if not y_columns:
        raise ValueError("Direct CLI mode requires at least one --y column")

    if data_count == 1:
        series_count = len(y_columns)
        x_columns = repeated_option(args.x, series_count, "--x")
        source_values = [None] * series_count
        default_labels = y_columns
    else:
        if len(y_columns) == 1:
            series_count = data_count
            y_columns = y_columns * data_count
        elif len(y_columns) == data_count:
            series_count = data_count
        else:
            raise ValueError(
                "For multiple --data inputs, pass one --y shared by all files "
                "or one --y per file."
            )
        x_columns = repeated_option(args.x, series_count, "--x")
        source_values = sources
        default_labels = [Path(str(source["path"])).stem for source in sources]

    labels = repeated_option(args.label, series_count, "--label")
    colors = repeated_option(args.color, series_count, "--color")
    markers = repeated_option(args.marker, series_count, "--marker")
    line_widths = repeated_option(args.line_width, series_count, "--line-width")
    marker_sizes = repeated_option(args.marker_size, series_count, "--marker-size")
    linestyles = repeated_option(args.linestyle, series_count, "--linestyle")

    series = []
    for index in range(series_count):
        label = labels[index] or default_labels[index]
        if args.property and series_count == 1:
            property_name = args.property
        elif args.kind in {"dual_axis", "dual_line", "multi_panel"}:
            property_name = y_columns[index]
        else:
            property_name = args.property or "y"
        spec: dict[str, Any] = {
            "x": {"column": x_columns[index], "label": args.xlabel or x_columns[index]},
            "y": {"column": y_columns[index], "label": args.ylabel or y_columns[index]},
            "property": property_name,
            "group_value": {"value": label},
            "legend_label": {"value": label},
        }
        if source_values[index] is not None:
            spec["source"] = source_values[index]
        for key, value in {
            "color": colors[index],
            "marker": markers[index],
            "line_width": line_widths[index],
            "marker_size": marker_sizes[index],
            "linestyle": linestyles[index],
        }.items():
            if value is not None:
                spec[key] = value
        series.append(spec)
    return series


def build_recipe_from_cli(args: argparse.Namespace) -> dict[str, Any]:
    if not cli_data_locations(args):
        raise ValueError("Direct CLI mode requires --data")
    if not args.x:
        raise ValueError("Direct CLI mode requires --x")

    sources = cli_source_configs(args)
    series = make_cli_series(args, sources)

    plot: dict[str, Any] = {
        "kind": args.kind,
        "x": {"column": args.x[0], "label": args.xlabel or args.x[0]},
        "series": series,
        "xlabel": args.xlabel or args.x[0],
        "ylabel": args.ylabel or args.y[0],
        "right_ylabel": args.right_ylabel,
        "legend": args.legend,
        "legend_loc": args.legend_loc,
        "xscale": args.xscale,
        "yscale": args.yscale,
        "right_yscale": args.right_yscale,
        "x_tick_format": args.x_tick_format,
        "y_tick_format": args.y_tick_format,
        "right_y_tick_format": args.right_y_tick_format,
        "xlim": parse_axis_limit(args.xlim),
        "ylim": parse_axis_limit(args.ylim),
        "right_ylim": parse_axis_limit(args.right_ylim),
        "x_major": args.x_major,
        "x_minor": args.x_minor,
        "y_major": args.y_major,
        "y_minor": args.y_minor,
        "right_y_major": args.right_y_major,
        "right_y_minor": args.right_y_minor,
        "panel_label": args.panel_label,
        "legend_title": args.legend_title,
        "legend_font_size": args.legend_font_size,
        "subplot_aspect": args.subplot_aspect,
    }
    plot = {key: value for key, value in plot.items() if value is not None}

    text_items = []
    for raw in args.text or []:
        text_items.append(parse_text_item(raw, coords="data"))
    for raw in args.text_axes or []:
        text_items.append(parse_text_item(raw, coords="axes"))
    if text_items:
        plot["text"] = text_items

    recipe: dict[str, Any] = {
        "name": args.name or args.stem or "CLI flexible plot",
        "plot": plot,
        "output": {
            "dir": args.output_dir,
            "stem": args.stem,
            "formats": args.formats,
            "normalized_csv": args.normalized_csv,
            "copy_to_data_dir": args.copy_to_data_dir,
        },
    }
    if len(sources) == 1:
        recipe["data"] = sources
    return recipe


def add_direct_cli_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("data_paths", nargs="*", help="Optional data path(s). With --recipe, these replace recipe data; without --recipe, they are plotted directly.")
    parser.add_argument("--data", action="append", help="Data path. Repeat for multiple files. Use file.xlsx::Sheet for Excel sheet.")
    parser.add_argument("--sheet", action="append", help="Excel sheet name/index. One value applies to all files; repeated values map to --data.")
    parser.add_argument("--sep", help="Delimiter for text-like files, e.g. '\\s+' or ','.")
    parser.add_argument("--skiprows", type=int, help="Rows to skip before reading data.")
    parser.add_argument("--header", help="Header row number, or 'none'.")
    parser.add_argument("--kind", "--plot-kind", default="line", choices=sorted(PLOTTERS), help="Plot kind for direct CLI mode.")
    parser.add_argument("--x", action="append", help="X column. One value applies to all series; repeated values map to series/files.")
    parser.add_argument("--y", action="append", help="Y column. Repeat for multiple curves.")
    parser.add_argument("--xlabel", help="X-axis label.")
    parser.add_argument("--ylabel", help="Y-axis label.")
    parser.add_argument("--right-ylabel", help="Right y-axis label for dual_line plots.")
    parser.add_argument("--label", "--series-label", action="append", help="Legend label. Repeat for multiple curves.")
    parser.add_argument("--property", help="Internal normalized property name.")
    parser.add_argument("--xlim", nargs=2, metavar=("LOW", "HIGH"), help="X-axis limits. Use auto for an open bound.")
    parser.add_argument("--ylim", nargs=2, metavar=("LOW", "HIGH"), help="Y-axis limits. Use auto for an open bound.")
    parser.add_argument("--right-ylim", nargs=2, metavar=("LOW", "HIGH"), help="Right y-axis limits for dual_line plots. Use auto for an open bound.")
    parser.add_argument("--xscale", choices=("linear", "log", "symlog", "logit"), help="X-axis scale.")
    parser.add_argument("--yscale", choices=("linear", "log", "symlog", "logit"), help="Y-axis scale.")
    parser.add_argument(
        "--right-yscale",
        "--right-yscal",
        "--right-y-scale",
        dest="right_yscale",
        choices=("linear", "log", "symlog", "logit"),
        help="Right y-axis scale for dual_line plots.",
    )
    parser.add_argument("--x-tick-format", choices=TICK_FORMAT_CHOICES, help="X tick label style. Use plain to avoid x10 math notation.")
    parser.add_argument("--y-tick-format", choices=TICK_FORMAT_CHOICES, help="Y tick label style. Use plain to avoid x10 math notation.")
    parser.add_argument("--right-y-tick-format", choices=TICK_FORMAT_CHOICES, help="Right y-axis tick label style for dual_line plots.")
    parser.add_argument("--x-major", type=float, help="X major tick spacing.")
    parser.add_argument("--x-minor", type=float, help="X minor tick spacing.")
    parser.add_argument("--y-major", type=float, help="Y major tick spacing.")
    parser.add_argument("--y-minor", type=float, help="Y minor tick spacing.")
    parser.add_argument("--right-y-major", type=float, help="Right y-axis major tick spacing for dual_line plots.")
    parser.add_argument("--right-y-minor", type=float, help="Right y-axis minor tick spacing for dual_line plots.")
    parser.add_argument("--legend", choices=("inside", "outside", "none"), default="inside", help="Legend mode.")
    parser.add_argument("--legend-loc", default="best", help="Matplotlib legend location, e.g. 'upper left'.")
    parser.add_argument("--legend-title", help="Legend title.")
    parser.add_argument("--legend-font-size", type=float, default=DEFAULT_LEGEND_FONT_SIZE)
    parser.add_argument("--color", action="append", help="Series color. One value applies to all; repeated values map to curves.")
    parser.add_argument("--marker", action="append", help="Series marker. One value applies to all; repeated values map to curves.")
    parser.add_argument("--line-width", action="append", type=float, help="Series line width.")
    parser.add_argument("--marker-size", action="append", type=float, help="Series marker size.")
    parser.add_argument("--linestyle", action="append", help="Series line style.")
    parser.add_argument("--panel-label", help="Large panel label such as A or B.")
    parser.add_argument("--text", action="append", help="Add data-coordinate text: x,y,text[,color].")
    parser.add_argument("--text-axes", action="append", help="Add axes-coordinate text: x,y,text[,color].")
    parser.add_argument("--subplot-aspect", default=DEFAULT_SUBPLOT_ASPECT, help="Plot frame width:height, default 10:8.")
    parser.add_argument("--name", help="Recipe/plot name for direct CLI mode.")
    parser.add_argument("--output-dir", default="outputs/figures/flexible_cli", help="Output directory.")
    parser.add_argument("--stem", default="flexible_cli_plot", help="Output filename stem.")
    parser.add_argument("--formats", "--format", nargs="+", default=["png", "pdf"], help="Output formats.")
    parser.add_argument("--normalized-csv", dest="normalized_csv", action="store_true", default=True)
    parser.add_argument("--no-normalized-csv", dest="normalized_csv", action="store_false")
    parser.add_argument("--copy-to-data-dir", dest="copy_to_data_dir", action="store_true", default=False, help="Also copy saved outputs next to the input data file(s).")
    parser.add_argument("--no-copy-to-data-dir", dest="copy_to_data_dir", action="store_false", help="Do not copy saved outputs next to input data file(s).")
    parser.add_argument("--show", dest="show", action="store_true", default=True, help="Display the figure after saving. Default: on.")
    parser.add_argument("--no-show", dest="show", action="store_false", help="Save without displaying the figure.")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description="Render a flexible plot recipe.")
    parser.add_argument("--recipe", action="append", help="JSON recipe path. Can be repeated.")
    parser.add_argument("--workspace", default=".", help="Workspace root for relative paths.")
    add_direct_cli_args(parser)
    args = parser.parse_args(argv)

    if not args.recipe and not cli_data_locations(args):
        parser.error("Provide either --recipe or data/--data plus --x/--y direct plotting arguments.")

    for recipe_path in args.recipe or []:
        recipe = override_recipe_from_cli(load_recipe(recipe_path), args, argv)
        result = plot_recipe(recipe, workspace=args.workspace, show=args.show)
        print(json.dumps({"recipe": recipe_path, **result}, indent=2))

    if not args.recipe and cli_data_locations(args):
        recipe = build_recipe_from_cli(args)
        result = plot_recipe(recipe, workspace=args.workspace, show=args.show)
        print(json.dumps({"mode": "direct", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

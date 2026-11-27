"""Column-semantic aliasing, table loading, and normalized-table building.

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

ROOT = Path(__file__).resolve().parents[3]
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


from te_analysis.tools.sciplot.util import (  # noqa: E402
    BAR_PLOT_KINDS,
    CATEGORICAL_X_KINDS,
    as_list,
    first_defined,
    normalize_name,
    plain_number_label,
    unique_in_order,
)


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
    return bool(plot.get("categorical_x", str(plot.get("kind", "line")).lower() in CATEGORICAL_X_KINDS))


def resolve_path(path: str | Path, workspace: Path) -> Path:
    raw_path = Path(path).expanduser()
    if raw_path.is_absolute():
        return raw_path
    return workspace / raw_path


def source_config_with_defaults(source: Any, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge recipe-wide reader defaults with one source definition."""
    source_config = dict(defaults or {})
    if isinstance(source, (str, Path)):
        source_config["path"] = source
    else:
        source_config.update(dict(source))
    return source_config


def find_header_row(path: Path, prefix: str, encoding: str | None) -> int:
    """Return the zero-based row whose stripped text starts with *prefix*."""
    with path.open("r", encoding=encoding or "utf-8-sig") as handle:
        for row_index, line in enumerate(handle):
            if line.lstrip("\ufeff \t").startswith(prefix):
                return row_index
    raise ValueError(f"Could not find a header starting with {prefix!r} in {path}")


def read_source_table(
    source: Any,
    workspace: Path,
    *,
    source_defaults: dict[str, Any] | None = None,
) -> pd.DataFrame:
    source_config = source_config_with_defaults(source, source_defaults)
    path = resolve_path(source_config["path"], workspace)
    suffix = path.suffix.lower()

    read_csv_kwargs = {}
    for key in ("skiprows", "header", "names", "comment", "encoding"):
        if key in source_config:
            read_csv_kwargs[key] = source_config[key]

    header_prefix = source_config.get("header_startswith", source_config.get("header_prefix"))
    if header_prefix is not None and "skiprows" not in source_config:
        read_csv_kwargs["skiprows"] = find_header_row(
            path,
            str(header_prefix),
            source_config.get("encoding"),
        )

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

    source_defaults = recipe.get("source_defaults")
    frames = [
        read_source_table(source, workspace, source_defaults=source_defaults)
        for source in as_list(sources)
    ]
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
        source_defaults = recipe.get("source_defaults")
        frames = [
            read_source_table(item, workspace, source_defaults=source_defaults)
            for item in as_list(source)
        ]
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


def _resolve_optional_numeric_column(
    raw: pd.DataFrame,
    spec: dict[str, Any],
    plot: dict[str, Any],
    key: str,
) -> tuple[pd.Series | None, str | None, Any]:
    selector = spec.get(key, plot.get(key))
    if selector is None:
        return None, None, None
    semantic = selector.get("semantic") if isinstance(selector, dict) else None
    col = resolve_column(raw, selector, semantic=semantic, required=True, role=key)
    return transform_values(raw[col], selector), col, selector


def build_normalized_table(recipe: dict[str, Any], workspace: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build one long table: x, y, property, group, label, source (plus optional extended columns)."""
    plot = recipe.get("plot", {})
    kind = str(plot.get("kind", "line")).lower()
    categorical_x = categorical_x_enabled(plot)
    fallback_raw = load_recipe_data(recipe, workspace) if recipe.get("data") or recipe.get("sources") else None

    is_ternary = kind == "ternary" or all(plot.get(k) is not None for k in ("a", "b", "c"))
    is_histogram = kind in {"histogram", "hist"}

    global_x_selector = plot.get("x")
    series_specs = plot.get("series") or ([plot.get("y")] if plot.get("y") is not None else [])
    series_specs = [spec for spec in series_specs if spec]

    if is_ternary:
        if global_x_selector is None:
            global_x_selector = plot.get("a")
        if not series_specs:
            b_sel = plot.get("b")
            if b_sel is not None:
                series_specs = [{"y": b_sel, "property": "ternary"}]
    elif is_histogram:
        if global_x_selector is None and series_specs:
            first_spec = series_specs[0]
            global_x_selector = series_y_selector(first_spec) if isinstance(first_spec, dict) else first_spec
        elif not series_specs and global_x_selector is not None:
            series_specs = [global_x_selector]

    if global_x_selector is None:
        raise ValueError("plot.x is required")
    if not series_specs:
        raise ValueError("Recipe needs plot.series or plot.y")

    group_selector = plot.get("group")
    label_selector = plot.get("label")
    condition_selector = plot.get("condition")

    def _any_has(field: str) -> bool:
        if plot.get(field) is not None:
            return True
        return any(isinstance(item, dict) and item.get(field) is not None for item in series_specs)

    has_z = _any_has("z")
    has_size = _any_has("size")
    has_yerr = _any_has("yerr")
    has_xerr = _any_has("xerr")
    has_y_bounds = _any_has("y_low") and _any_has("y_high")
    has_role = _any_has("role")
    has_err_style = any(
        isinstance(item, dict) and any(k in item for k in ("yerr_pct", "xerr_pct", "error_mode"))
        for item in series_specs
    )

    rows = []
    property_labels: dict[str, str] = {}
    extra_metadata: dict[str, Any] = {}
    auto_categorical_x = False
    has_y_category = False

    for series_index, spec in enumerate(series_specs):
        if not isinstance(spec, dict):
            spec = {"column": spec}
        raw = series_source_table(spec, recipe, workspace, fallback_raw)

        x_selector = spec.get("x", global_x_selector)
        x_semantic = x_selector.get("semantic") if isinstance(x_selector, dict) else None
        x_col = resolve_column(raw, x_selector, semantic=x_semantic, role="x")
        x_raw = raw[x_col]

        numeric_x_probe = pd.to_numeric(x_raw, errors="coerce")
        series_cat_x = categorical_x or (kind == "heatmap" and numeric_x_probe.notna().sum() == 0 and x_raw.notna().any())
        if series_cat_x and not categorical_x:
            auto_categorical_x = True

        if series_cat_x:
            x_values = numeric_x_probe
            x_category_values = x_raw.astype("string")
        else:
            x_values = transform_values(x_raw, x_selector)
            x_category_values = x_values.map(lambda value: plain_number_label(float(value)) if pd.notna(value) else "")

        y_selector = series_y_selector(spec)
        semantic = y_selector.get("semantic") if isinstance(y_selector, dict) else spec.get("semantic")
        y_col = resolve_column(raw, y_selector, semantic=semantic, role=spec.get("property", "y"))
        y_transformed = transform_values(raw[y_col], y_selector)
        y_cat_series: pd.Series | None = None
        if kind == "heatmap" and y_transformed.notna().sum() == 0 and raw[y_col].notna().any():
            has_y_category = True
            y_cat_series = raw[y_col].astype(str)
            cats_y = unique_in_order(y_cat_series)
            cat_map_y = {val: float(i) for i, val in enumerate(cats_y)}
            y_transformed = y_cat_series.map(cat_map_y)

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
                "y": y_transformed,
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

        if y_cat_series is not None:
            working["y_category"] = y_cat_series
        if has_z:
            z_vals, z_col, z_sel = _resolve_optional_numeric_column(raw, spec, plot, "z")
            working["z"] = z_vals if z_vals is not None else np.nan
            if z_col and "z_label" not in extra_metadata:
                extra_metadata["z_label"] = selector_label(z_sel, z_col)
        if has_size:
            s_vals, _, _ = _resolve_optional_numeric_column(raw, spec, plot, "size")
            working["size"] = s_vals if s_vals is not None else np.nan
        if has_yerr:
            ye_vals, _, _ = _resolve_optional_numeric_column(raw, spec, plot, "yerr")
            working["yerr"] = ye_vals if ye_vals is not None else np.nan
        if has_xerr:
            xe_vals, _, _ = _resolve_optional_numeric_column(raw, spec, plot, "xerr")
            working["xerr"] = xe_vals if xe_vals is not None else np.nan
        if has_y_bounds:
            yl_vals, _, _ = _resolve_optional_numeric_column(raw, spec, plot, "y_low")
            yh_vals, _, _ = _resolve_optional_numeric_column(raw, spec, plot, "y_high")
            working["y_low"] = yl_vals if yl_vals is not None else np.nan
            working["y_high"] = yh_vals if yh_vals is not None else np.nan
        if is_ternary:
            for t_key in ("a", "b", "c"):
                t_vals, t_col, t_sel = _resolve_optional_numeric_column(raw, spec, plot, t_key)
                working[t_key] = t_vals if t_vals is not None else np.nan
                if t_col and f"{t_key}_label" not in extra_metadata:
                    extra_metadata[f"{t_key}_label"] = selector_label(t_sel, t_col)
        if has_role:
            role_vals = fixed_or_column_values(raw, spec.get("role", plot.get("role")), default="", role="role")
            working["role"] = role_vals.astype(str)
        if has_err_style:
            for e_key in ("yerr_pct", "xerr_pct", "error_mode"):
                working[e_key] = spec.get(e_key, "")

        rows.append(working)

    if auto_categorical_x:
        categorical_x = True

    normalized = pd.concat(rows, ignore_index=True)
    object_columns = normalized.select_dtypes(include="object").columns
    normalized.loc[:, object_columns] = normalized.loc[:, object_columns].mask(
        normalized.loc[:, object_columns] == ""
    )
    if is_ternary:
        drop_subset = ["a", "b", "c"]
    elif categorical_x:
        drop_subset = ["x_category", "y"]
    else:
        drop_subset = ["x", "y"]
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
        "has_y_category": has_y_category,
        **extra_metadata,
    }
    return normalized, metadata


def unique_properties_by_series_order(normalized: pd.DataFrame) -> list[str]:
    ordered = normalized.sort_values("series_order", kind="mergesort")
    return unique_in_order(ordered["property"])


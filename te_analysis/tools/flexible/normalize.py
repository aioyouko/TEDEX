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
    BAR_PLOT_KINDS,
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


def unique_properties_by_series_order(normalized: pd.DataFrame) -> list[str]:
    ordered = normalized.sort_values("series_order", kind="mergesort")
    return unique_in_order(ordered["property"])



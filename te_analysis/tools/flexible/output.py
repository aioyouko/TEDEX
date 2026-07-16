"""Recipe output resolution, figure saving, and the plot_recipe driver.

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
    as_list,
    safe_output_stem,
)
from te_analysis.tools.flexible.normalize import (  # noqa: E402
    build_normalized_table,
    resolve_path,
)
from te_analysis.tools.flexible.render import (  # noqa: E402
    PLOTTERS,
)


LEGACY_CENTRAL_OUTPUT_PREFIXES = ("outputs/figures", "results/plots")


def is_legacy_central_output_dir(value: Any) -> bool:
    if not value:
        return True
    normalized = str(value).replace("\\", "/").strip("/")
    return any(normalized.startswith(prefix) for prefix in LEGACY_CENTRAL_OUTPUT_PREFIXES)


def default_output_dir_for_recipe(recipe: dict[str, Any], workspace: Path) -> Path:
    data_dirs = recipe_data_dirs(recipe, workspace)
    if data_dirs:
        common_dir = Path(os.path.commonpath([str(path) for path in data_dirs]))
        return common_dir / "figures"
    return workspace / "figures"


def output_config(recipe: dict[str, Any], workspace: Path) -> tuple[Path, str, list[str]]:
    output = recipe.get("output", {})
    raw_stem = output.get("stem") or re.sub(r"[^a-zA-Z0-9_]+", "_", recipe.get("name", "flexible_plot")).strip("_")
    stem = safe_output_stem(raw_stem)
    output_dir_value = output.get("dir")
    if output.get("_dir_explicit") or not is_legacy_central_output_dir(output_dir_value):
        output_dir = resolve_path(output_dir_value, workspace)
    else:
        output_dir = default_output_dir_for_recipe(recipe, workspace)
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



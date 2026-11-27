"""Small shared helpers and constants for flexible plotting.

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




BAR_PLOT_KINDS = {"bar", "grouped_bar", "stacked_bar", "percent_stacked_bar", "stacked_bar_100"}
CATEGORICAL_X_KINDS = BAR_PLOT_KINDS | {"waterfall", "boxplot", "box", "violin", "radar", "spider"}
def safe_output_stem(value: Any, max_length: int = 96) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    stem = re.sub(r"_+", "_", stem).strip("_.-") or "flexible_plot"
    if len(stem) <= max_length:
        return stem
    digest = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:8]
    prefix_length = max(1, max_length - len(digest) - 1)
    return f"{stem[:prefix_length].rstrip('_.-')}_{digest}"


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


def unique_in_order(values: pd.Series) -> list[str]:
    return [str(value) for value in pd.Series(values).dropna().drop_duplicates().tolist()]


def optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def plain_number_label(value: float) -> str:
    if not np.isfinite(value):
        return ""
    if abs(value - round(value)) < 1e-10:
        return str(int(round(value)))
    return f"{value:.10g}"



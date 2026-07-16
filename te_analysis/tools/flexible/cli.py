"""Command-line parsing and the flexible plotting entry point.

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
)
from te_analysis.tools.flexible.style import (  # noqa: E402
    TICK_FORMAT_CHOICES,
)
from te_analysis.tools.flexible.render import (  # noqa: E402
    PLOTTERS,
)
from te_analysis.tools.flexible.output import (  # noqa: E402
    load_recipe,
    plot_recipe,
)


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
        output["_dir_explicit"] = True
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
            "stem": args.stem,
            "formats": args.formats,
            "normalized_csv": args.normalized_csv,
            "copy_to_data_dir": args.copy_to_data_dir,
        },
    }
    if args.output_dir:
        recipe["output"]["dir"] = args.output_dir
        recipe["output"]["_dir_explicit"] = True
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
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory. Default: a figures folder beside the input data.",
    )
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

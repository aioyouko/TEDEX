import os
import json
import argparse
import sys
import re
import csv
import hashlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_MPL_CACHE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "te_agent_matplotlib"
_MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(_MPL_CACHE_DIR))

import pandas as pd
from te_analysis.tools.plot import (
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_MARKER_SIZE,
    DEFAULT_SUBPLOT_ASPECT,
    TE_PLOT_SPECS,
    normalize_output_formats,
    parse_aspect_ratio,
    plot_combined_figure,
    plot_single_property,
)
from te_analysis.tools.selectors import (
    normalize_sample_selector as normalize_selector,
    truncate_with_digest,
)
from te_analysis.tools.file_utils import copy_saved_figure_outputs


from te_analysis.tools.te_plotting import *  # noqa: F401,F403,E402
from te_analysis.tools.te_plotting import __all__ as _te_plotting_all  # noqa: F401,E402


PLOT_MODE_CHOICES = ("combined", "single", "both")
AUTO_LIMIT_VALUES = {"auto", "none", "null"}
DEFAULT_PLOT_MODE = "single"
def parse_limit_bound(raw_value, option_name):
    clean_value = str(raw_value).strip()
    if clean_value.lower() in AUTO_LIMIT_VALUES:
        return None

    try:
        return float(clean_value)
    except ValueError as exc:
        raise ValueError(
            f"{option_name} limit {raw_value!r} must be a number or one of "
            f"{', '.join(sorted(AUTO_LIMIT_VALUES))}"
        ) from exc


def normalize_axis_limit_pair(raw_pair, option_name):
    if raw_pair is None:
        return None

    low = parse_limit_bound(raw_pair[0], option_name)
    high = parse_limit_bound(raw_pair[1], option_name)

    if low is None and high is None:
        return None
    if low is not None and high is not None and low >= high:
        raise ValueError(f"{option_name} lower limit must be smaller than upper limit")

    return (low, high)


def parse_property_ylims(raw_ylims, selected_properties=None):
    ylims = {}
    selected_properties = selected_properties or []

    for raw_ylim in raw_ylims or []:
        if len(raw_ylim) == 2:
            if len(selected_properties) != 1:
                raise ValueError(
                    "--ylim LOW HIGH can only be used when exactly one single "
                    "property is selected. Use --ylim PROPERTY LOW HIGH for "
                    "combined or multi-property plots."
                )
            property_key = selected_properties[0]
            low, high = raw_ylim
        elif len(raw_ylim) == 3:
            property_key, low, high = raw_ylim
            property_key = normalize_property_key(property_key, "--ylim property")
        else:
            raise ValueError(
                "--ylim expects either LOW HIGH or PROPERTY LOW HIGH. "
                "Examples: --seebeck --ylim -300 300, or "
                "--ylim seebeck -300 300."
            )

        limit_pair = normalize_axis_limit_pair((low, high), f"--ylim {property_key}")
        if limit_pair is not None:
            ylims[property_key] = limit_pair

    return ylims


def plot_combined_batch(
    processed_data,
    batch_id,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    marker_size=DEFAULT_MARKER_SIZE,
    legend_columns=None,
    show=False,
):
    save_name = f"{batch_id}_summary.png"
    save_dir = get_batch_plot_dir(batch_id)

    return plot_combined_figure(
        processed_data=processed_data,
        save_name=save_name,
        save_dir=save_dir,
        formats=formats,
        xlim=xlim,
        ylims=ylims,
        subplot_aspect=subplot_aspect,
        marker_size=marker_size,
        legend_columns=legend_columns,
        show=show,
    )


def plot_single_batch_properties(
    processed_data,
    batch_id,
    property_keys=None,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    single_legend="none",
    marker_size=DEFAULT_MARKER_SIZE,
    legend_font_size=DEFAULT_LEGEND_FONT_SIZE,
    legend_columns=None,
    show=False,
):
    property_keys = resolve_single_property_keys(processed_data, property_keys)
    if not property_keys:
        print(f"⚠️ no single-property plots available for {batch_id}")
        return []

    save_dir = get_single_plot_dir(batch_id)
    plot_paths = []

    for property_key in property_keys:
        save_name = f"{batch_id}_{property_key}.png"
        plot_path = plot_single_property(
            processed_data=processed_data,
            property_key=property_key,
            save_name=save_name,
            save_dir=save_dir,
            formats=formats,
            xlim=xlim,
            ylim=ylims.get(property_key) if ylims else None,
            subplot_aspect=subplot_aspect,
            legend=single_legend,
            marker_size=marker_size,
            legend_font_size=legend_font_size,
            legend_columns=legend_columns,
            show=show,
        )
        plot_paths.append(plot_path)

    return plot_paths


def plot_combined_interbatch(
    processed_data,
    comparison_id,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    marker_size=DEFAULT_MARKER_SIZE,
    legend_columns=None,
    save_dir=None,
    show=False,
):
    save_name = f"{comparison_id}_summary.png"
    save_dir = save_dir or get_interbatch_plot_dir(comparison_id)

    return plot_combined_figure(
        processed_data=processed_data,
        save_name=save_name,
        save_dir=save_dir,
        formats=formats,
        xlim=xlim,
        ylims=ylims,
        subplot_aspect=subplot_aspect,
        marker_size=marker_size,
        legend_columns=legend_columns,
        show=show,
    )


def plot_single_interbatch_properties(
    processed_data,
    comparison_id,
    property_keys=None,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    single_legend="none",
    marker_size=DEFAULT_MARKER_SIZE,
    legend_font_size=DEFAULT_LEGEND_FONT_SIZE,
    legend_columns=None,
    save_dir=None,
    show=False,
):
    property_keys = resolve_single_property_keys(processed_data, property_keys)
    if not property_keys:
        print(f"⚠️ no single-property plots available for {comparison_id}")
        return []

    save_dir = save_dir or get_interbatch_single_plot_dir(comparison_id)
    plot_paths = []

    for property_key in property_keys:
        save_name = f"{comparison_id}_{property_key}.png"
        plot_path = plot_single_property(
            processed_data=processed_data,
            property_key=property_key,
            save_name=save_name,
            save_dir=save_dir,
            formats=formats,
            xlim=xlim,
            ylim=ylims.get(property_key) if ylims else None,
            subplot_aspect=subplot_aspect,
            legend=single_legend,
            marker_size=marker_size,
            legend_font_size=legend_font_size,
            legend_columns=legend_columns,
            show=show,
        )
        plot_paths.append(plot_path)

    return plot_paths


def execute_interbatch_comparison(
    target_batches,
    plot_mode=DEFAULT_PLOT_MODE,
    single_properties=None,
    comparison_id=None,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    single_legend="none",
    marker_size=DEFAULT_MARKER_SIZE,
    legend_font_size=DEFAULT_LEGEND_FONT_SIZE,
    legend_columns=None,
    data_figures=False,
    data_figures_dir="figures",
    output_dir=None,
    show=False,
):
    if plot_mode not in PLOT_MODE_CHOICES:
        raise ValueError(f"plot_mode must be one of {PLOT_MODE_CHOICES}, got {plot_mode!r}")

    comparison_id = comparison_id or get_interbatch_comparison_id(target_batches)
    processed_data = load_interbatch_processed_data(target_batches)
    output_dir = Path(output_dir) if output_dir is not None else None
    data_figure_dir = (
        resolve_te_data_figure_dir(target_batches, data_figures_dir, comparison_id)
        if data_figures
        else None
    )

    if not processed_data:
        print("⚠️ no processed data found for inter-batch comparison")
        return

    print(f"\n{'='*50}")
    print(f"TE selection: {comparison_id}")
    print(f"✅ total {len(processed_data)} samples, now plotting")

    try:
        if plot_mode in ("combined", "both"):
            plot_path = plot_combined_interbatch(
                processed_data,
                comparison_id,
                formats=formats,
                xlim=xlim,
                ylims=ylims,
                subplot_aspect=subplot_aspect,
                marker_size=marker_size,
                legend_columns=legend_columns,
                save_dir=output_dir,
                show=show,
            )
            print(f"🎉 inter-batch combined plot saved to: {plot_path}")
            if data_figure_dir is not None:
                copied_paths = copy_saved_figure_outputs(plot_path, data_figure_dir, formats=formats)
                if copied_paths:
                    print(f"   copied data figures to: {data_figure_dir}")

        if plot_mode in ("single", "both"):
            plot_paths = plot_single_interbatch_properties(
                processed_data,
                comparison_id,
                property_keys=single_properties,
                formats=formats,
                xlim=xlim,
                ylims=ylims,
                subplot_aspect=subplot_aspect,
                single_legend=single_legend,
                marker_size=marker_size,
                legend_font_size=legend_font_size,
                legend_columns=legend_columns,
                save_dir=output_dir,
                show=show,
            )
            single_save_dir = output_dir or get_interbatch_single_plot_dir(comparison_id)
            print(f"🎉 inter-batch single-property plots saved to: {single_save_dir}")
            print(f"   total single plots: {len(plot_paths)}")
            if data_figure_dir is not None:
                copied_paths = copy_saved_figure_outputs(plot_paths, data_figure_dir, formats=formats)
                if copied_paths:
                    print(f"   copied data figures to: {data_figure_dir}")
    except Exception as e:
        print(f"❌ error for inter-batch comparison {comparison_id}: {e}")


def execute_plot_batches(
    target_batches,
    plot_mode=DEFAULT_PLOT_MODE,
    single_properties=None,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    single_legend="none",
    marker_size=DEFAULT_MARKER_SIZE,
    legend_font_size=DEFAULT_LEGEND_FONT_SIZE,
    legend_columns=None,
    data_figures=False,
    data_figures_dir="figures",
    show=False,
):
    if not ALL_LAB_BATCHES:
        return

    if plot_mode not in PLOT_MODE_CHOICES:
        raise ValueError(f"plot_mode must be one of {PLOT_MODE_CHOICES}, got {plot_mode!r}")
    
    for raw_batch_id in target_batches:
        batch_id = normalize_selector(raw_batch_id)
        if batch_id in ALL_LAB_BATCHES:
            print(f"\n{'='*50}")
            print(f"{'='*50}")
            
            processed_data = load_batch_processed_data(batch_id)
            
            if not processed_data:
                continue
                
            print(f"✅ total {len(processed_data)} samples, now plotting")
            data_figure_dir = Path(get_processed_dir(batch_id)) / data_figures_dir if data_figures else None
            
            try:
                if plot_mode in ("combined", "both"):
                    plot_path = plot_combined_batch(
                        processed_data,
                        batch_id,
                        formats=formats,
                        xlim=xlim,
                        ylims=ylims,
                        subplot_aspect=subplot_aspect,
                        marker_size=marker_size,
                        legend_columns=legend_columns,
                        show=show,
                    )
                    print(f"🎉 combined plot saved to: {plot_path}")
                    if data_figure_dir is not None:
                        copied_paths = copy_saved_figure_outputs(plot_path, data_figure_dir, formats=formats)
                        if copied_paths:
                            print(f"   copied data figures to: {data_figure_dir}")

                if plot_mode in ("single", "both"):
                    plot_paths = plot_single_batch_properties(
                        processed_data,
                        batch_id,
                        property_keys=single_properties,
                        formats=formats,
                        xlim=xlim,
                        ylims=ylims,
                        subplot_aspect=subplot_aspect,
                        single_legend=single_legend,
                        marker_size=marker_size,
                        legend_font_size=legend_font_size,
                        legend_columns=legend_columns,
                        show=show,
                    )
                    print(f"🎉 single-property plots saved to: {get_single_plot_dir(batch_id)}")
                    print(f"   total single plots: {len(plot_paths)}")
                    if data_figure_dir is not None:
                        copied_paths = copy_saved_figure_outputs(plot_paths, data_figure_dir, formats=formats)
                        if copied_paths:
                            print(f"   copied data figures to: {data_figure_dir}")
            except Exception as e:
                print(f"❌ error for {batch_id}: {e}")
                
        else:
            print(f"⚠️ missing {batch_id} JSON")


def parse_args():
    parser = argparse.ArgumentParser(description="Plot processed TE batch data.")
    parser.add_argument(
        "batches",
        nargs="*",
        help=(
            "Batch/sample/path selectors. Examples: CHY-1046 for all samples, "
            "CHY-1040-A for one sample, CHY-1040-Zn_dope_0.02 for one named "
            "sample, CHY-1046/Na_dope for one named sample, or a direct CSV/dir "
            "such as data/processed/CHY-1040/Zn_dope_0.02.csv."
        ),
    )
    parser.add_argument(
        "--plot-mode",
        choices=PLOT_MODE_CHOICES,
        default=None,
        help=(
            "Choose combined summary, single-property plots, or both. "
            f"Default: {DEFAULT_PLOT_MODE}."
        ),
    )
    parser.add_argument(
        "--single-properties",
        "--properties",
        nargs="+",
        metavar="PROPERTY",
        default=None,
        dest="single_properties",
        help="Optional subset of properties for single-property plotting.",
    )
    add_property_flag_arguments(parser)
    parser.add_argument(
        "--inter-batch",
        action="store_true",
        help=(
            "Plot samples from all selected batches together in one comparison. "
            "This is automatic for multiple selectors or any sample/path selector."
        ),
    )
    parser.add_argument(
        "--comparison-id",
        default=None,
        help="Optional folder and filename prefix for --inter-batch output.",
    )
    parser.add_argument(
        "--xlim",
        nargs=2,
        default=None,
        metavar=("LOW", "HIGH"),
        help=(
            "Shared temperature axis limits for all TE plots. "
            "Use 'auto' for an open bound, for example: --xlim 300 auto."
        ),
    )
    parser.add_argument(
        "--ylim",
        nargs="+",
        action="append",
        default=[],
        metavar="VALUE",
        help=(
            "Y-axis limits. Use --ylim LOW HIGH when exactly one property is "
            "selected, or --ylim PROPERTY LOW HIGH. Repeat to set multiple "
            "properties, for example: --ylim zt 0 1.2 --ylim seebeck -300 300."
        ),
    )
    parser.add_argument(
        "--subplot-aspect",
        default=DEFAULT_SUBPLOT_ASPECT,
        help=(
            "Width:height ratio for each plot frame, e.g. 10:8 or 1:1. "
            "Applies to single plots and each panel in combined plots."
        ),
    )
    parser.add_argument(
        "--single-legend",
        choices=("none", "inside", "outside"),
        default="none",
        help="Legend placement for single-property plots. Default: none.",
    )
    parser.add_argument(
        "--legend",
        dest="single_legend",
        action="store_const",
        const="inside",
        help="Add an inside legend to selected single-property plots.",
    )
    parser.add_argument(
        "--legend-font-size",
        type=float,
        default=DEFAULT_LEGEND_FONT_SIZE,
        help=(
            "Legend font size in points for single-property legends. "
            f"Default: {DEFAULT_LEGEND_FONT_SIZE}."
        ),
    )
    parser.add_argument(
        "--legend-columns",
        "--legend-cols",
        "--legend-ncol",
        type=int,
        default=None,
        help=(
            "Number of legend columns for single-property and combined plots. "
            "Default: automatic."
        ),
    )
    parser.add_argument(
        "--marker-size",
        type=float,
        default=DEFAULT_MARKER_SIZE,
        help="Marker size in points for both combined and single-property plots.",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["svg"],
        help="Output formats, for example: --formats svg png pdf.",
    )
    parser.add_argument(
        "--data-figures",
        "--save-near-data",
        action="store_true",
        help="Also copy saved figures into a figures folder beside the processed data.",
    )
    parser.add_argument(
        "--data-figures-dir",
        default="figures",
        help="Folder name for --data-figures copies. Default: figures.",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Also save vector PDF output in addition to the selected formats.",
    )
    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument(
        "--show",
        dest="show",
        action="store_true",
        default=True,
        help="Display each generated figure with matplotlib after saving. Default.",
    )
    display_group.add_argument(
        "--no-show",
        dest="show",
        action="store_false",
        help="Save figures without opening a matplotlib preview window.",
    )
    args = parser.parse_args()

    try:
        args.single_properties = get_requested_single_properties(args)
        args.xlim = normalize_axis_limit_pair(args.xlim, "--xlim")
        args.ylim = parse_property_ylims(
            args.ylim,
            selected_properties=args.single_properties,
        )
        parse_aspect_ratio(args.subplot_aspect)
        if args.marker_size <= 0:
            raise ValueError("--marker-size must be positive")
        if args.legend_font_size <= 0:
            raise ValueError("--legend-font-size must be positive")
        if args.legend_columns is not None and args.legend_columns <= 0:
            raise ValueError("--legend-columns must be a positive integer")
    except ValueError as exc:
        parser.error(str(exc))

    return args

if __name__ == "__main__":
    
    # Select whole batches or individual samples:
    # "CHY-1046" means all samples in CHY-1046.
    # "CHY-1040-A" means only sample A from CHY-1040.
    # "CHY-1046/Na_dope" or "CHY-1046:Na_dope" means one named sample.
    my_targets = ["CHY-1048"]
    inter_batch = False  # set True to compare all my_targets in one plot
    
    args = parse_args()
    target_batches = args.batches or my_targets
    selected_plot_mode = args.plot_mode or DEFAULT_PLOT_MODE
    selected_formats = normalize_output_formats(args.formats, pdf=args.pdf)
    selected_xlim = args.xlim
    selected_ylims = args.ylim
    selected_subplot_aspect = args.subplot_aspect
    selected_single_legend = args.single_legend
    selected_marker_size = args.marker_size
    selected_legend_font_size = args.legend_font_size
    selected_legend_columns = args.legend_columns
    selected_show = args.show
    selected_data_figures = args.data_figures
    selected_data_figures_dir = args.data_figures_dir
    selected_comparison_id = args.comparison_id

    selected_inter_batch = (
        args.inter_batch
        or (inter_batch and not args.batches)
        or (args.batches and len(target_batches) > 1)
        or selectors_need_combined_view(target_batches)
    )
    selected_output_dir = None
    if selected_inter_batch:
        source_output_dir = resolve_te_source_output_dir(target_batches)
        if selected_comparison_id is None and source_output_dir is not None:
            selected_comparison_id = get_path_selection_comparison_id(
                target_batches,
                source_output_dir=source_output_dir,
            )
        if selected_comparison_id is None:
            selected_comparison_id = get_interbatch_comparison_id(target_batches)
        selected_output_dir = resolve_te_data_figure_dir(
            target_batches,
            selected_data_figures_dir,
            selected_comparison_id,
        )

    if selected_inter_batch:
        execute_interbatch_comparison(
            target_batches,
            plot_mode=selected_plot_mode,
            single_properties=args.single_properties,
            comparison_id=selected_comparison_id,
            formats=selected_formats,
            xlim=selected_xlim,
            ylims=selected_ylims,
            subplot_aspect=selected_subplot_aspect,
            single_legend=selected_single_legend,
            marker_size=selected_marker_size,
            legend_font_size=selected_legend_font_size,
            legend_columns=selected_legend_columns,
            data_figures=selected_data_figures,
            data_figures_dir=selected_data_figures_dir,
            output_dir=selected_output_dir,
            show=selected_show,
        )
    else:
        execute_plot_batches(
            target_batches,
            plot_mode=selected_plot_mode,
            single_properties=args.single_properties,
            formats=selected_formats,
            xlim=selected_xlim,
            ylims=selected_ylims,
            subplot_aspect=selected_subplot_aspect,
            single_legend=selected_single_legend,
            marker_size=selected_marker_size,
            legend_font_size=selected_legend_font_size,
            legend_columns=selected_legend_columns,
            data_figures=selected_data_figures,
            data_figures_dir=selected_data_figures_dir,
            show=selected_show,
        )

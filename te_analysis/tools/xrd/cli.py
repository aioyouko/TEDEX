#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

import argparse
import math
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from te_analysis.tools.colors import add_color_set_argument
from te_analysis.tools.figure_naming import add_rename_argument, figure_output_naming
from te_analysis.tools.plot import (
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_SUBPLOT_ASPECT,
    DEFAULT_TICK_LABEL_SIZE,
    normalize_output_formats,
    parse_aspect_ratio,
)
from te_analysis.tools.xrd import (
    DEFAULT_PDF_STANDARD_DIR,
    DEFAULT_TWO_THETA_RANGE,
    DEFAULT_XRD_LINE_WIDTH,
    DEFAULT_PDF_HEIGHT_FRACTION,
    DEFAULT_XRD_ROOT,
    DEFAULT_XRD_SAVE_DIR,
    comparison_id_from_patterns,
    filter_xrd_patterns,
    list_pdf_card_candidates,
    load_xrd_patterns,
    plot_xrd_comparison,
    plot_xrd_peak_fit,
    plot_xrd_raw_and_normalized,
    plot_xrd_rietveld,
    plot_xrd_separate,
    plot_xrd_vt_map,
    plot_xrd_vt_stack,
    plot_xrd_williamson_hall,
    plot_xrd_zoom_stack,
    resolve_pdf_standard,
    select_xrd_patterns_by_index,
    safe_filename,
    summarize_patterns,
)

import matplotlib.pyplot as plt

from te_analysis.tools.matplotlib_backend import show_interactive_figures
from te_analysis.tools.file_utils import copy_saved_figure_outputs

try:
    import argcomplete
except ImportError:  # pragma: no cover - optional shell-completion helper.
    argcomplete = None


OUTPUT_MODE_ALIASES = {
    "both": "both",
    "counts": "not_normalized",
    "raw": "not_normalized",
    "normal": "not_normalized",
    "normal-intensity": "not_normalized",
    "normal_intensity": "not_normalized",
    "not-normalized": "not_normalized",
    "not_normalized": "not_normalized",
    "normalized": "normalized",
}
LAYOUT_ALIASES = {
    "stack": "stack",
    "separate": "separate",
    "seperate": "separate",
    "zoom": "zoom",
    "zoom-stack": "zoom",
    "zoom_stack": "zoom",
    "vt-map": "vt_map",
    "vt_map": "vt_map",
    "vt-heatmap": "vt_map",
    "vt-contour": "vt_map",
    "vt-stack": "vt_stack",
    "vt_stack": "vt_stack",
    "vt-waterfall": "vt_stack",
    "vt": "vt_stack",
    "rietveld": "rietveld",
    "refinement": "rietveld",
    "peak-fit": "peak_fit",
    "peak_fit": "peak_fit",
    "deconv": "peak_fit",
    "williamson-hall": "williamson_hall",
    "williamson_hall": "williamson_hall",
    "wh": "williamson_hall",
}
MODE_ALIASES = {**OUTPUT_MODE_ALIASES, **LAYOUT_ALIASES}
AUTO_LIMIT_VALUES = {"auto", "none", "null", ""}


def normalize_mode_and_layout(mode: str, layout: str) -> tuple[str, str]:
    mode_value = MODE_ALIASES[mode]
    layout_value = LAYOUT_ALIASES[layout]
    if mode_value in LAYOUT_ALIASES.values():
        return "both", mode_value
    return mode_value, layout_value


def parse_limit_bound(value, option_name: str) -> float | None:
    clean_value = str(value).strip().lower()
    if clean_value in AUTO_LIMIT_VALUES:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{option_name} limit {value!r} must be a number or auto") from exc


def normalize_axis_limit_pair(raw_pair, option_name: str):
    if raw_pair is None:
        return None
    low = parse_limit_bound(raw_pair[0], option_name)
    high = parse_limit_bound(raw_pair[1], option_name)
    if low is None and high is None:
        return None
    if low is not None and high is not None and low >= high:
        raise ValueError(f"{option_name} lower limit must be smaller than upper limit")
    return (low, high)


def complete_pdf_cards(prefix, parsed_args, **kwargs):
    standard_dir = getattr(parsed_args, "pdf_standard_dir", DEFAULT_PDF_STANDARD_DIR)
    candidates = list_pdf_card_candidates(standard_dir=standard_dir)
    if "/" in prefix:
        values = [str(path) for path in candidates]
    else:
        values = [path.stem for path in candidates]
    return sorted(value for value in set(values) if value.startswith(prefix))


def _sample_suffix(sample_id: str, batch_id: str = "") -> str:
    if batch_id and sample_id.startswith(f"{batch_id}-"):
        return sample_id[len(batch_id) + 1 :]
    if "-" in sample_id:
        return sample_id.rsplit("-", 1)[-1]
    return ""


def complete_sample_selectors(prefix, parsed_args, **kwargs):
    selectors = getattr(parsed_args, "selectors", None)
    xrd_root = getattr(parsed_args, "xrd_root", DEFAULT_XRD_ROOT)
    try:
        patterns = load_xrd_patterns(selectors, xrd_root=xrd_root)
    except Exception:
        return []

    values = set()
    for pattern in patterns:
        suffix = _sample_suffix(pattern.sample_id, pattern.batch_id)
        values.update(
            value
            for value in (
                suffix,
                pattern.sample_id,
                pattern.source_path.stem,
                pattern.source_path.name,
            )
            if value
        )

    prefix_lower = prefix.lower()
    return sorted(value for value in values if value.lower().startswith(prefix_lower))


def print_pdf_card_candidates(standard_dir=DEFAULT_PDF_STANDARD_DIR):
    candidates = list_pdf_card_candidates(standard_dir=standard_dir)
    if not candidates:
        print("No PDF cards were found.")
        return

    print("Available PDF cards:")
    for path in candidates:
        print(f"  - {path.stem}: {path}")


def resolve_xrd_data_figure_dir(patterns, folder_name="figures", comparison_id=None):
    source_dirs = sorted({pattern.source_path.parent.resolve() for pattern in patterns})
    if not source_dirs:
        return None
    if len(source_dirs) == 1:
        return source_dirs[0] / folder_name

    common_dir = Path(os.path.commonpath([str(path) for path in source_dirs]))
    if comparison_id:
        return common_dir / folder_name / safe_filename(comparison_id)
    return common_dir / folder_name


def parse_pattern_pick(value: str) -> list[int]:
    """Expand compact, single-digit file positions such as 124."""
    if not value or any(char not in "123456789" for char in value):
        raise argparse.ArgumentTypeError(
            "--pick must contain only digits 1-9, e.g. 124 for files 1, 2, 4. "
            "For indices of 10 or higher, use --indices 1 2 10."
        )
    return [int(char) for char in value]


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Plot stacked XRD .xy patterns for selected batches/samples and optionally "
            "compare them with one or two PDF-card stick patterns."
        )
    )
    parser.add_argument(
        "selectors",
        nargs="*",
        help=(
            "Batch/sample/file selectors. Examples: TE-1038, 1038, TE-1038-A, "
            "or data/raw/TE-1038/XRD/TE-1038-A_XRD.xy. With no selector, all "
            "data/raw/*/XRD/*.xy files are plotted."
        ),
    )
    sample_selectors_argument = parser.add_argument(
        "-s",
        "--select",
        "--samples",
        dest="sample_selectors",
        nargs="+",
        default=[],
        help=(
            "Filter loaded XRD files by sample suffix, sample id, file stem, or "
            "composition/sample name. Comma-separated values and globs are allowed."
        ),
    )
    index_selection = parser.add_mutually_exclusive_group()
    index_selection.add_argument(
        "--pick",
        dest="pattern_indices",
        type=parse_pattern_pick,
        metavar="DIGITS",
        help=(
            "Choose files by 1-based position in the original file list: "
            "124 selects files 1, 2, 4; 234 selects files 2, 3, 4. "
            "Preserves file order and matching legend/trace labels."
        ),
    )
    index_selection.add_argument(
        "--indices",
        dest="pattern_indices",
        nargs="+",
        type=int,
        metavar="N",
        help=(
            "Choose explicit 1-based file indices, e.g. --indices 1 2 10. "
            "Applied before --select; preserves original file order."
        ),
    )
    parser.add_argument(
        "--list-files",
        action="store_true",
        help=(
            "List all loaded files with their original 1-based indices and labels, "
            "before any --pick/--indices/--select filtering; do not plot."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=tuple(MODE_ALIASES.keys()),
        default="normalized",
        help=(
            "Choose normalized, raw-count, both figures, or use separate/seperate "
            "as a shorthand for --layout separate. Default: normalized."
        ),
    )
    parser.add_argument(
        "--normalized",
        action="store_const",
        const="normalized",
        dest="mode",
        help="Save normalized intensity plots. This is the default.",
    )
    parser.add_argument(
        "--raw",
        "--counts",
        "--normal-intensity",
        "--not-normalized",
        "--not_normalized",
        action="store_const",
        const="not_normalized",
        dest="mode",
        help="Save raw-count/normal-intensity plots instead of normalized plots.",
    )
    parser.add_argument(
        "--both",
        action="store_const",
        const="both",
        dest="mode",
        help="Save both raw-count and normalized plots.",
    )
    parser.add_argument(
        "--layout",
        "--figure",
        choices=tuple(LAYOUT_ALIASES.keys()),
        default="stack",
        help=(
            "XRD figure type: stack, separate, zoom (dual-panel peak shift), "
            "vt-map (2D temperature-2theta map), vt-stack (thermal gradient stack), "
            "rietveld (Obs/Calc/Bragg/Residual), peak-fit (Pseudo-Voigt deconvolution), "
            "or williamson-hall (size & microstrain)."
        ),
    )
    parser.add_argument("--separate", action="store_const", const="separate", dest="layout", help="Shortcut for --layout separate.")
    parser.add_argument("--seperate", action="store_const", const="separate", dest="layout", help=argparse.SUPPRESS)
    parser.add_argument("--vt-map", action="store_const", const="vt-map", dest="layout", help="Shortcut for --layout vt-map (in-situ 2D temperature map).")
    parser.add_argument("--vt-stack", action="store_const", const="vt-stack", dest="layout", help="Shortcut for --layout vt-stack (temperature gradient stack).")
    parser.add_argument("--rietveld", action="store_const", const="rietveld", dest="layout", help="Shortcut for --layout rietveld.")
    parser.add_argument("--peak-fit", action="store_const", const="peak-fit", dest="layout", help="Shortcut for --layout peak-fit.")
    parser.add_argument("--williamson-hall", "--wh", action="store_const", const="williamson-hall", dest="layout", help="Shortcut for --layout williamson-hall.")
    parser.add_argument(
        "--zoom",
        "--zoom-window",
        dest="zoom",
        nargs=2,
        metavar=("LOW", "HIGH"),
        help="Magnified 2-theta window (activates dual-panel zoom stack or Rietveld zoom inset).",
    )
    parser.add_argument("--temperatures", nargs="+", type=float, help="Explicit temperatures (K) for vt-map or vt-stack.")
    parser.add_argument("--transition-temp", action="append", type=float, help="Horizontal phase-transition temperature guide (K) on vt-map.")
    parser.add_argument("--guide-2theta", nargs="+", type=float, help="Vertical peak-shift guide angle(s) on vt-stack.")
    parser.add_argument("--cmap", default=None, help="Colormap for vt-map (default: soft-br, low=soft blue -> high=soft red).")
    parser.add_argument("--intensity-scale", choices=("linear", "sqrt", "log"), default="sqrt", help="Intensity contrast scaling for vt-map (default: sqrt).")
    parser.add_argument("--peak-centers", nargs="+", type=float, help="Initial peak center guesses (deg) for peak-fit.")
    parser.add_argument("--max-peaks", type=int, default=3, help="Maximum auto-detected peaks in peak-fit (default: 3).")
    parser.add_argument("--instr-fwhm", type=float, default=0.05, help="Instrumental FWHM (deg) subtracted in Williamson-Hall fit.")
    parser.add_argument("--formula", default=None, help="Sample formula label for Rietveld plot.")
    parser.add_argument("--cell-text", default=None, help="Refined lattice cell annotation for Rietveld plot.")
    parser.add_argument("--phase-label", action="append", default=None, help="Phase label(s) for Rietveld Bragg reflection rows.")
    pdf_card_argument = parser.add_argument(
        "--pdf-card",
        "--card",
        action="append",
        dest="pdf_cards",
        default=[],
        metavar="CARD",
        help=(
            "PDF standard CSV/text path or basename. Repeat once for a second card: "
            "the first card is drawn below the XRD traces and the second above them. "
            f"Prefer clean CSV files in {DEFAULT_PDF_STANDARD_DIR}."
        ),
    )
    parser.add_argument(
        "--pdf-standard-dir",
        default=str(DEFAULT_PDF_STANDARD_DIR),
        help="Folder containing clean plotting-ready PDF standard CSV files.",
    )
    parser.add_argument(
        "--list-pdf-cards",
        action="store_true",
        help="Print available PDF-card basenames that can be used with --pdf-card.",
    )
    parser.add_argument(
        "--no-pdf-card",
        action="store_true",
        help="Legacy option; measured XRD patterns are plotted without PDF-card sticks by default.",
    )
    parser.add_argument(
        "--xrd-root",
        default=str(DEFAULT_XRD_ROOT),
        help="Root folder containing batch/XRD/*.xy files.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Base directory for saved XRD figures. Default: a figures folder "
            "beside the selected source XRD data."
        ),
    )
    parser.add_argument(
        "--data-figures",
        "--save-near-data",
        action="store_true",
        help="Also copy saved figures into a figures folder beside the source XRD data.",
    )
    parser.add_argument(
        "--data-figures-dir",
        default="figures",
        help="Folder name for --data-figures copies. Default: figures.",
    )
    parser.add_argument(
        "--comparison-id",
        default=None,
        help="Optional output folder and filename prefix.",
    )
    parser.add_argument(
        "--xlim",
        nargs=2,
        default=list(DEFAULT_TWO_THETA_RANGE),
        metavar=("LOW", "HIGH"),
        help="2-theta plotting window. Use auto for an open bound.",
    )
    parser.add_argument(
        "--ylim",
        nargs=2,
        default=None,
        metavar=("LOW", "HIGH"),
        help="Stacked intensity axis limits after offsets. Use auto for an open bound.",
    )
    parser.add_argument(
        "--overlap",
        type=float,
        default=1.05,
        help="Stack spacing between traces. Smaller values make traces overlap more.",
    )
    parser.add_argument(
        "--pdf-height-fraction",
        "--standard-height-fraction",
        dest="standard_height_fraction",
        type=float,
        default=DEFAULT_PDF_HEIGHT_FRACTION,
        help=(
            "Maximum PDF-stick height relative to one stacked XRD offset step; "
            "applies to both cards. "
            f"Default: {DEFAULT_PDF_HEIGHT_FRACTION}."
        ),
    )
    parser.add_argument(
        "--color",
        "--colors",
        action="append",
        dest="colors",
        help="Trace color. Repeat to set the XRD color cycle.",
    )
    parser.add_argument(
        "--standard-color",
        default="#d62728",
        help="Bottom PDF-card stick/name color. Default: #d62728 (red).",
    )
    parser.add_argument(
        "--top-standard-color",
        "--second-standard-color",
        default="#1f77b4",
        help="Top PDF-card stick/name color. Default: #1f77b4 (blue).",
    )
    parser.add_argument(
        "--line-width",
        type=float,
        default=DEFAULT_XRD_LINE_WIDTH,
        help=f"Line width for XRD traces and PDF sticks. Default: {DEFAULT_XRD_LINE_WIDTH}.",
    )
    parser.add_argument(
        "--subplot-aspect",
        "--aspect",
        default=DEFAULT_SUBPLOT_ASPECT,
        help=(
            "Initial width:height ratio for the plot frame, e.g. 10:8 or 1:1. "
            "The interactive axes remain resizable unless --fixed-aspect is used."
        ),
    )
    parser.add_argument(
        "--fixed-aspect",
        action="store_true",
        help="Lock the axes box aspect to --subplot-aspect, matching the older resize behavior.",
    )
    parser.add_argument(
        "--free-aspect",
        action="store_false",
        dest="fixed_aspect",
        help="Let the axes stretch when the interactive window is resized. This is the default.",
    )
    parser.add_argument(
        "--tick-labelsize",
        type=float,
        default=DEFAULT_TICK_LABEL_SIZE,
        help=f"Axis tick label size in points. Default: {DEFAULT_TICK_LABEL_SIZE}.",
    )
    parser.add_argument(
        "--legend-font-size",
        type=float,
        default=None,
        help=(
            f"Legend font size in points. Default: {DEFAULT_LEGEND_FONT_SIZE}. "
            "When set explicitly, also sizes the trace/PDF labels (otherwise 7.5 pt)."
        ),
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["svg"],
        help="Output formats, for example: --formats svg png pdf.",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Also save vector PDF output in addition to the selected formats.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save figures without calling plt.show() at the end.",
    )
    parser.add_argument(
        "--include-batch",
        action="store_true",
        default=None,
        help="Legacy option; XRD labels use batch+sample id by default.",
    )
    legend_pos_group = parser.add_mutually_exclusive_group()
    legend_pos_group.add_argument(
        "--no-legend-outside",
        dest="legend_outside",
        action="store_false",
        help="Keep the legend inside the axes (default).",
    )
    legend_pos_group.add_argument(
        "--legend-outside",
        dest="legend_outside",
        action="store_true",
        help="Place the legend outside the right edge of the axes.",
    )
    parser.add_argument(
        "--legend",
        action="store_true",
        dest="show_legend",
        help="Show a conventional legend; by default only right-side trace labels are shown.",
    )
    parser.add_argument(
        "--no-legend",
        action="store_false",
        dest="show_legend",
        help="Hide the legend.",
    )
    parser.add_argument(
        "--right-labels",
        action="store_true",
        dest="right_labels",
        help=(
            "Show right-side labels beside stacked traces (the default). Label/legend "
            "files are used in sorted XRD file order; without one, file stems are used."
        ),
    )
    parser.add_argument(
        "--no-right-labels",
        action="store_false",
        dest="right_labels",
        help="Hide the default right-side trace labels.",
    )
    parser.add_argument(
        "--pdf-labels",
        "--pdf-card-labels",
        "--show-pdf-labels",
        "--show-pdf-card-labels",
        action="store_true",
        dest="show_pdf_labels",
        help="Show PDF-card names inside the plot. They are hidden by default.",
    )
    parser.add_argument(
        "--no-pdf-labels",
        "--no-pdf-card-labels",
        action="store_false",
        dest="show_pdf_labels",
        help="Hide PDF-card names inside the plot. This is the default.",
    )
    parser.set_defaults(show_legend=False, legend_outside=False, right_labels=True, show_pdf_labels=False)
    add_rename_argument(parser)
    if argcomplete is not None:
        sample_selectors_argument.completer = complete_sample_selectors
        pdf_card_argument.completer = complete_pdf_cards
        argcomplete.autocomplete(parser)
    add_color_set_argument(parser)
    args = parser.parse_args()
    try:
        args.xlim = normalize_axis_limit_pair(args.xlim, "--xlim")
        args.ylim = normalize_axis_limit_pair(args.ylim, "--ylim")
        args.zoom = normalize_axis_limit_pair(args.zoom, "--zoom") if args.zoom else None
        if args.zoom and any(bound is None for bound in args.zoom):
            raise ValueError("--zoom requires numeric LOW and HIGH bounds")
        parse_aspect_ratio(args.subplot_aspect)
        if args.overlap <= 0:
            raise ValueError("--overlap must be positive")
        if (
            not math.isfinite(args.standard_height_fraction)
            or args.standard_height_fraction <= 0
        ):
            raise ValueError("--pdf-height-fraction must be a finite positive number")
        if args.line_width <= 0:
            raise ValueError("--line-width must be positive")
        if args.tick_labelsize <= 0:
            raise ValueError("--tick-labelsize must be positive")
        if args.legend_font_size is not None and args.legend_font_size <= 0:
            raise ValueError("--legend-font-size must be positive")
        if LAYOUT_ALIASES.get(args.layout) != "rietveld" and len(args.pdf_cards) > 2:
            raise ValueError("--pdf-card may be specified at most twice")
    except ValueError as exc:
        parser.error(str(exc))
    args.pdf_card = args.pdf_cards[0] if args.pdf_cards else None
    args.top_pdf_card = args.pdf_cards[1] if len(args.pdf_cards) == 2 else None
    return args


def execute_xrd_plot(
    selectors=None,
    sample_selectors=None,
    mode="normalized",
    layout="stack",
    pdf_card=None,
    pdf_standard_dir=DEFAULT_PDF_STANDARD_DIR,
    no_pdf_card=False,
    xrd_root=DEFAULT_XRD_ROOT,
    output_dir=None,
    comparison_id=None,
    xlim=DEFAULT_TWO_THETA_RANGE,
    ylim=None,
    overlap=1.05,
    colors=None,
    standard_color="#d62728",
    line_width=DEFAULT_XRD_LINE_WIDTH,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    tick_labelsize=DEFAULT_TICK_LABEL_SIZE,
    legend_font_size=None,
    formats=None,
    pdf=False,
    include_batch=None,
    legend_outside=False,
    show_legend=False,
    fixed_aspect=False,
    right_labels=True,
    data_figures=False,
    data_figures_dir="figures",
    show=True,
    top_pdf_card=None,
    top_standard_color="#1f77b4",
    show_pdf_labels=False,
    standard_height_fraction=DEFAULT_PDF_HEIGHT_FRACTION,
    color_set=None,
    pattern_indices=None,
    list_files=False,
    zoom=None,
    temperatures=None,
    transition_temp=None,
    guide_2theta=None,
    cmap=None,
    intensity_scale="sqrt",
    peak_centers=None,
    max_peaks=3,
    instr_fwhm=0.05,
    formula=None,
    cell_text=None,
    phase_label=None,
    pdf_cards_all=None,
):
    output_mode, layout = normalize_mode_and_layout(mode, layout)
    if layout == "stack" and zoom is not None:
        layout = "zoom"
    xlim = tuple(xlim) if xlim else None

    if layout == "rietveld":
        if not selectors:
            raise ValueError("--layout rietveld requires a refinement profile CSV/TXT/DAT path")
        profile_path = Path(selectors[0])
        if not profile_path.is_file():
            raise FileNotFoundError(f"Rietveld profile file not found: {profile_path}")
        all_cards = pdf_cards_all if pdf_cards_all is not None else ([c for c in (pdf_card, top_pdf_card) if c])
        standards = (
            [resolve_pdf_standard(card, standard_dir=pdf_standard_dir) for card in all_cards]
            if not no_pdf_card
            else []
        )
        comp_id = safe_filename(comparison_id or profile_path.stem)
        save_dir = Path(output_dir) if output_dir is not None else (profile_path.parent / data_figures_dir)
        formats = normalize_output_formats(formats, pdf=pdf)
        plot_path = plot_xrd_rietveld(
            profile_path,
            pdf_standards=standards,
            phase_labels=phase_label,
            formula_text=formula,
            cell_text=cell_text,
            zoom_range=zoom,
            two_theta_range=xlim,
            save_name=f"{comp_id}_XRD_rietveld.png",
            save_dir=save_dir,
            formats=formats,
            tick_labelsize=tick_labelsize,
            close=not show,
        )
        paths = {"rietveld": plot_path}
        print(f"saved rietveld: {plot_path}")
        if show:
            show_interactive_figures()
            plt.close("all")
        return paths
    all_patterns = load_xrd_patterns(selectors, xrd_root=xrd_root, include_batch=include_batch)
    if list_files:
        if not all_patterns:
            print("No XRD .xy files were found.")
        else:
            print("XRD files (original order, before filtering):")
            for index, pattern in enumerate(all_patterns, 1):
                print(f"  {index}. {pattern.source_path} | label: {pattern.label}")
        return {}

    patterns = select_xrd_patterns_by_index(all_patterns, pattern_indices)
    patterns, unmatched_selectors = filter_xrd_patterns(patterns, sample_selectors)
    for selector in unmatched_selectors:
        print(f"warning: no loaded XRD pattern matched --select {selector!r}")

    if not patterns:
        print("No XRD .xy files were found.")
        return {}

    pdf_standard = None
    top_pdf_standard = None
    if pdf_card and not no_pdf_card:
        pdf_standard = resolve_pdf_standard(pdf_card, standard_dir=pdf_standard_dir)
    if top_pdf_card and not no_pdf_card:
        top_pdf_standard = resolve_pdf_standard(top_pdf_card, standard_dir=pdf_standard_dir)

    if not comparison_id:
        comparison_id = comparison_id_from_patterns(patterns)
        if pattern_indices is not None:
            selected_paths = {pattern.source_path for pattern in patterns}
            selected_indices = [
                str(index) for index, pattern in enumerate(all_patterns, 1)
                if pattern.source_path in selected_paths
            ]
            comparison_id += "_pick_" + "_".join(selected_indices)
    comparison_id = safe_filename(comparison_id)
    explicit_output_dir = output_dir is not None
    if output_dir is None:
        output_dir = resolve_xrd_data_figure_dir(patterns, data_figures_dir)
        if output_dir is None:
            output_dir = DEFAULT_XRD_SAVE_DIR
    output_dir = Path(output_dir)
    formats = normalize_output_formats(formats, pdf=pdf)

    print("\nXRD patterns:")
    for item in summarize_patterns(patterns):
        print(f"  - {item['label']}: {item['source_path']}")
    if pdf_standard is not None:
        print(f"Bottom PDF standard: {pdf_standard.label} ({pdf_standard.source_path})")
    if top_pdf_standard is not None:
        print(f"Top PDF standard: {top_pdf_standard.label} ({top_pdf_standard.source_path})")
    print(f"Output group: {comparison_id}")
    print(f"Layout: {layout}")

    if layout == "separate":
        paths = plot_xrd_separate(
            patterns,
            pdf_standard=pdf_standard,
            top_pdf_standard=top_pdf_standard,
            comparison_id=comparison_id,
            output_mode=output_mode,
            save_dir=output_dir,
            formats=formats,
            two_theta_range=xlim,
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
            top_standard_color=top_standard_color,
            show_pdf_labels=show_pdf_labels,
            standard_height_fraction=standard_height_fraction,
            close=not show,
            nest_in_comparison_dir=explicit_output_dir,
        )
    elif layout == "zoom":
        save_dir = output_dir / comparison_id if explicit_output_dir else output_dir
        normalized = output_mode != "not_normalized"
        z_window = zoom or (26.5, 28.8)
        plot_path = plot_xrd_zoom_stack(
            patterns,
            zoom_range=z_window,
            pdf_standard=pdf_standard,
            top_pdf_standard=top_pdf_standard,
            normalized=normalized,
            save_name=f"{comparison_id}_XRD_zoom.png",
            save_dir=save_dir,
            formats=formats,
            two_theta_range=xlim,
            overlap=overlap,
            colors=colors,
            color_set=color_set,
            line_width=line_width,
            tick_labelsize=tick_labelsize,
            legend_font_size=legend_font_size,
            standard_color=standard_color,
            top_standard_color=top_standard_color,
            show_pdf_labels=show_pdf_labels,
            standard_height_fraction=standard_height_fraction,
            close=not show,
        )
        paths = {"zoom": plot_path}
    elif layout == "vt_map":
        save_dir = output_dir / comparison_id if explicit_output_dir else output_dir
        normalized = output_mode != "not_normalized"
        plot_path = plot_xrd_vt_map(
            patterns,
            temperatures=temperatures,
            pdf_standard=pdf_standard,
            normalized=normalized,
            intensity_scale=intensity_scale,
            cmap=cmap,
            transition_temps=transition_temp,
            save_name=f"{comparison_id}_XRD_vt_map.png",
            save_dir=save_dir,
            formats=formats,
            two_theta_range=xlim,
            subplot_aspect=subplot_aspect,
            tick_labelsize=tick_labelsize,
            standard_color=standard_color,
            close=not show,
        )
        paths = {"vt_map": plot_path}
    elif layout == "vt_stack":
        save_dir = output_dir / comparison_id if explicit_output_dir else output_dir
        normalized = output_mode != "not_normalized"
        plot_path = plot_xrd_vt_stack(
            patterns,
            temperatures=temperatures,
            pdf_standard=pdf_standard,
            guide_peaks=guide_2theta,
            normalized=normalized,
            overlap=overlap if overlap != 1.05 else 0.92,
            save_name=f"{comparison_id}_XRD_vt_stack.png",
            save_dir=save_dir,
            formats=formats,
            two_theta_range=xlim,
            subplot_aspect=subplot_aspect,
            tick_labelsize=tick_labelsize,
            line_width=line_width,
            standard_color=standard_color,
            close=not show,
        )
        paths = {"vt_stack": plot_path}
    elif layout == "peak_fit":
        save_dir = output_dir / comparison_id if explicit_output_dir else output_dir
        fit_win = xlim if xlim != DEFAULT_TWO_THETA_RANGE else None
        paths = {}
        for pat in patterns:
            pat_key = safe_filename(pat.sample_id or pat.label)
            p_path = plot_xrd_peak_fit(
                pat,
                fit_window=fit_win,
                peak_centers=peak_centers,
                max_peaks=max_peaks,
                save_name=f"{pat_key}_XRD_peak_fit.png",
                save_dir=save_dir,
                formats=formats,
                tick_labelsize=tick_labelsize,
                close=not show,
            )
            paths[f"{pat_key}_peak_fit"] = p_path
    elif layout == "williamson_hall":
        save_dir = output_dir / comparison_id if explicit_output_dir else output_dir
        paths = {}
        for pat in patterns:
            pat_key = safe_filename(pat.sample_id or pat.label)
            w_path = plot_xrd_williamson_hall(
                pat,
                pdf_standard=pdf_standard,
                instr_fwhm_deg=instr_fwhm,
                two_theta_range=xlim,
                save_name=f"{pat_key}_XRD_williamson_hall.png",
                save_dir=save_dir,
                formats=formats,
                subplot_aspect=subplot_aspect,
                tick_labelsize=tick_labelsize,
                close=not show,
            )
            paths[f"{pat_key}_williamson_hall"] = w_path
    elif output_mode == "both":
        paths = plot_xrd_raw_and_normalized(
            patterns,
            pdf_standard=pdf_standard,
            top_pdf_standard=top_pdf_standard,
            comparison_id=comparison_id,
            save_dir=output_dir,
            formats=formats,
            two_theta_range=xlim,
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
            top_standard_color=top_standard_color,
            show_pdf_labels=show_pdf_labels,
            standard_height_fraction=standard_height_fraction,
            close=not show,
            nest_in_comparison_dir=explicit_output_dir,
        )
    else:
        save_dir = output_dir / comparison_id if explicit_output_dir else output_dir
        normalized = output_mode == "normalized"
        suffix = "normalized" if normalized else "not_normalized"
        plot_path = plot_xrd_comparison(
            patterns,
            pdf_standard=pdf_standard,
            top_pdf_standard=top_pdf_standard,
            normalized=normalized,
            save_name=f"{comparison_id}_XRD_{suffix}.png",
            save_dir=save_dir,
            formats=formats,
            two_theta_range=xlim,
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
            top_standard_color=top_standard_color,
            show_pdf_labels=show_pdf_labels,
            standard_height_fraction=standard_height_fraction,
            close=not show,
        )
        paths = {suffix: plot_path}

    for label, path in paths.items():
        print(f"saved {label}: {path}")
    if data_figures:
        data_figure_dir = (
            resolve_xrd_data_figure_dir(patterns, data_figures_dir, comparison_id)
            if explicit_output_dir
            else output_dir
        )
        if data_figure_dir is not None:
            copied_paths = copy_saved_figure_outputs(paths, data_figure_dir, formats=formats)
            if copied_paths:
                print(f"copied data figures to: {data_figure_dir}")
    if show:
        show_interactive_figures()
        plt.close("all")
    return paths


def _run_cli(args):
    if args.list_pdf_cards:
        print_pdf_card_candidates(args.pdf_standard_dir)
        return

    execute_xrd_plot(
        selectors=args.selectors,
        sample_selectors=args.sample_selectors,
        pattern_indices=args.pattern_indices,
        list_files=args.list_files,
        mode=args.mode,
        layout=args.layout,
        pdf_card=args.pdf_card,
        top_pdf_card=args.top_pdf_card,
        pdf_standard_dir=args.pdf_standard_dir,
        no_pdf_card=args.no_pdf_card,
        xrd_root=args.xrd_root,
        output_dir=args.output_dir,
        comparison_id=args.comparison_id,
        xlim=args.xlim,
        ylim=args.ylim,
        overlap=args.overlap,
        standard_height_fraction=args.standard_height_fraction,
        colors=args.colors,
        color_set=args.color_set,
        standard_color=args.standard_color,
        top_standard_color=args.top_standard_color,
        line_width=args.line_width,
        subplot_aspect=args.subplot_aspect,
        tick_labelsize=args.tick_labelsize,
        legend_font_size=args.legend_font_size,
        formats=args.formats,
        pdf=args.pdf,
        include_batch=args.include_batch,
        legend_outside=args.legend_outside,
        show_legend=args.show_legend,
        fixed_aspect=args.fixed_aspect,
        right_labels=args.right_labels,
        show_pdf_labels=args.show_pdf_labels,
        data_figures=args.data_figures,
        data_figures_dir=args.data_figures_dir,
        show=not args.no_show,
        zoom=args.zoom,
        temperatures=args.temperatures,
        transition_temp=args.transition_temp,
        guide_2theta=args.guide_2theta,
        cmap=args.cmap,
        intensity_scale=args.intensity_scale,
        peak_centers=args.peak_centers,
        max_peaks=args.max_peaks,
        instr_fwhm=args.instr_fwhm,
        formula=args.formula,
        cell_text=args.cell_text,
        phase_label=args.phase_label,
        pdf_cards_all=args.pdf_cards,
    )


def main():
    args = parse_args()
    with figure_output_naming(args.rename):
        return _run_cli(args)


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from None

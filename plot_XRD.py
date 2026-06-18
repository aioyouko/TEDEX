#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

import argparse
from pathlib import Path

from src.tools.plot import normalize_output_formats
from src.tools.plot_XRD_data import (
    DEFAULT_PDF_STANDARD_DIR,
    DEFAULT_TWO_THETA_RANGE,
    DEFAULT_XRD_ROOT,
    DEFAULT_XRD_SAVE_DIR,
    comparison_id_from_patterns,
    filter_xrd_patterns,
    list_pdf_card_candidates,
    load_xrd_patterns,
    plot_xrd_comparison,
    plot_xrd_raw_and_normalized,
    plot_xrd_separate,
    resolve_pdf_standard,
    safe_filename,
    summarize_patterns,
)

import matplotlib.pyplot as plt

try:
    import argcomplete
except ImportError:  # pragma: no cover - optional shell-completion helper.
    argcomplete = None


OUTPUT_MODE_ALIASES = {
    "both": "both",
    "raw": "not_normalized",
    "not-normalized": "not_normalized",
    "not_normalized": "not_normalized",
    "normal": "normalized",
    "normalized": "normalized",
}
LAYOUT_ALIASES = {
    "stack": "stack",
    "separate": "separate",
    "seperate": "separate",
}
MODE_ALIASES = {**OUTPUT_MODE_ALIASES, **LAYOUT_ALIASES}


def normalize_mode_and_layout(mode: str, layout: str) -> tuple[str, str]:
    mode_value = MODE_ALIASES[mode]
    layout_value = LAYOUT_ALIASES[layout]
    if mode_value in LAYOUT_ALIASES.values():
        return "both", mode_value
    return mode_value, layout_value


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


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Plot stacked XRD .xy patterns for selected batches/samples and optionally "
            "compare them with a PDF-card stick pattern."
        )
    )
    parser.add_argument(
        "selectors",
        nargs="*",
        help=(
            "Batch/sample/file selectors. Examples: CHY-1038, 1038, CHY-1038-A, "
            "or data/raw/CHY-1038/XRD/CHY-1038-A_XRD.xy. With no selector, all "
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
    parser.add_argument(
        "--mode",
        choices=tuple(MODE_ALIASES.keys()),
        default="both",
        help=(
            "Choose raw-count, normalized, both figures, or use separate/seperate "
            "as a shorthand for --layout separate."
        ),
    )
    parser.add_argument(
        "--layout",
        choices=tuple(LAYOUT_ALIASES.keys()),
        default="stack",
        help="Plot all selected patterns in one stacked figure or as separate sample figures.",
    )
    parser.add_argument(
        "--separate",
        action="store_const",
        const="separate",
        dest="layout",
        help="Shortcut for --layout separate.",
    )
    parser.add_argument(
        "--seperate",
        action="store_const",
        const="separate",
        dest="layout",
        help=argparse.SUPPRESS,
    )
    pdf_card_argument = parser.add_argument(
        "--pdf-card",
        "--card",
        default=None,
        help=(
            "Optional PDF standard CSV/text path or basename. Prefer clean CSV files in "
            f"{DEFAULT_PDF_STANDARD_DIR}. Extensionless names are allowed."
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
        default=str(DEFAULT_XRD_SAVE_DIR),
        help="Base directory for saved XRD figures.",
    )
    parser.add_argument(
        "--comparison-id",
        default=None,
        help="Optional output folder and filename prefix.",
    )
    parser.add_argument(
        "--xlim",
        nargs=2,
        type=float,
        default=list(DEFAULT_TWO_THETA_RANGE),
        metavar=("LOW", "HIGH"),
        help="2-theta plotting window.",
    )
    parser.add_argument(
        "--overlap",
        type=float,
        default=1.05,
        help="Stack spacing between traces. Smaller values make traces overlap more.",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["png"],
        help="Output formats, for example: --formats svg png pdf.",
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
        default=False,
        help="Display generated figures with matplotlib after saving.",
    )
    display_group.add_argument(
        "--no-show",
        dest="show",
        action="store_false",
        help="Save figures without calling plt.show() at the end. Default.",
    )
    parser.add_argument(
        "--include-batch",
        action="store_true",
        default=None,
        help="Legacy option; XRD labels use batch+sample id by default.",
    )
    parser.add_argument(
        "--no-legend-outside",
        action="store_true",
        help="Keep the legend inside the axes instead of outside the main plot.",
    )
    parser.add_argument(
        "--right-labels",
        action="store_true",
        dest="right_labels",
        help="Add right-side sample labels beside the stacked traces.",
    )
    parser.add_argument(
        "--no-right-labels",
        action="store_false",
        dest="right_labels",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(right_labels=False)
    if argcomplete is not None:
        sample_selectors_argument.completer = complete_sample_selectors
        pdf_card_argument.completer = complete_pdf_cards
        argcomplete.autocomplete(parser)
    return parser.parse_args()


def execute_xrd_plot(
    selectors=None,
    sample_selectors=None,
    mode="both",
    layout="stack",
    pdf_card=None,
    pdf_standard_dir=DEFAULT_PDF_STANDARD_DIR,
    no_pdf_card=False,
    xrd_root=DEFAULT_XRD_ROOT,
    output_dir=DEFAULT_XRD_SAVE_DIR,
    comparison_id=None,
    xlim=DEFAULT_TWO_THETA_RANGE,
    overlap=1.05,
    formats=None,
    pdf=False,
    include_batch=None,
    legend_outside=True,
    right_labels=False,
    show=False,
):
    output_mode, layout = normalize_mode_and_layout(mode, layout)
    xlim = tuple(xlim) if xlim else None
    patterns = load_xrd_patterns(selectors, xrd_root=xrd_root, include_batch=include_batch)
    patterns, unmatched_selectors = filter_xrd_patterns(patterns, sample_selectors)
    for selector in unmatched_selectors:
        print(f"warning: no loaded XRD pattern matched --select {selector!r}")

    if not patterns:
        print("No XRD .xy files were found.")
        return {}

    pdf_standard = None
    if pdf_card and not no_pdf_card:
        pdf_standard = resolve_pdf_standard(pdf_card, standard_dir=pdf_standard_dir)

    comparison_id = comparison_id or comparison_id_from_patterns(patterns)
    comparison_id = safe_filename(comparison_id)
    output_dir = Path(output_dir)
    formats = normalize_output_formats(formats, pdf=pdf)

    print("\nXRD patterns:")
    for item in summarize_patterns(patterns):
        print(f"  - {item['label']}: {item['source_path']}")
    if pdf_standard is not None:
        print(f"PDF standard: {pdf_standard.label} ({pdf_standard.source_path})")
    print(f"Output group: {comparison_id}")
    print(f"Layout: {layout}")

    if layout == "separate":
        paths = plot_xrd_separate(
            patterns,
            pdf_standard=pdf_standard,
            comparison_id=comparison_id,
            output_mode=output_mode,
            save_dir=output_dir,
            formats=formats,
            two_theta_range=xlim,
            overlap=overlap,
            legend_outside=legend_outside,
            right_labels=right_labels,
            close=not show,
        )
    elif output_mode == "both":
        paths = plot_xrd_raw_and_normalized(
            patterns,
            pdf_standard=pdf_standard,
            comparison_id=comparison_id,
            save_dir=output_dir,
            formats=formats,
            two_theta_range=xlim,
            overlap=overlap,
            legend_outside=legend_outside,
            right_labels=right_labels,
            close=not show,
        )
    else:
        save_dir = output_dir / comparison_id
        normalized = output_mode == "normalized"
        suffix = "normalized" if normalized else "not_normalized"
        plot_path = plot_xrd_comparison(
            patterns,
            pdf_standard=pdf_standard,
            normalized=normalized,
            save_name=f"{comparison_id}_XRD_{suffix}.png",
            save_dir=save_dir,
            formats=formats,
            two_theta_range=xlim,
            overlap=overlap,
            legend_outside=legend_outside,
            right_labels=right_labels,
            close=not show,
        )
        paths = {suffix: plot_path}

    for label, path in paths.items():
        print(f"saved {label}: {path}")
    if show:
        plt.show()
        plt.close("all")
    return paths


def main():
    args = parse_args()
    if args.list_pdf_cards:
        print_pdf_card_candidates(args.pdf_standard_dir)
        return

    execute_xrd_plot(
        selectors=args.selectors,
        sample_selectors=args.sample_selectors,
        mode=args.mode,
        layout=args.layout,
        pdf_card=args.pdf_card,
        pdf_standard_dir=args.pdf_standard_dir,
        no_pdf_card=args.no_pdf_card,
        xrd_root=args.xrd_root,
        output_dir=args.output_dir,
        comparison_id=args.comparison_id,
        xlim=args.xlim,
        overlap=args.overlap,
        formats=args.formats,
        pdf=args.pdf,
        include_batch=args.include_batch,
        legend_outside=not args.no_legend_outside,
        right_labels=args.right_labels,
        show=args.show,
    )


if __name__ == "__main__":
    main()

"""Digitize the provided K-edge spectrum image and redraw it as transparent SVG."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")

import numpy as np
from PIL import Image
from scipy.signal import medfilt, savgol_filter

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.matplotlib_backend import configure_matplotlib_backend  # noqa: E402

configure_matplotlib_backend()

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import ticker  # noqa: E402

from src.tools.plot import (  # noqa: E402
    apply_plot_style,
    figure_size_for_subplot_aspect,
    format_te_axis,
    save_figure,
)


DEFAULT_IMAGE = Path(
    "/Users/chenheyang/Library/Containers/me.damir.dropover-mac/Data/tmp/Promises/311/k-edge.jpg"
)

# Pixel calibration from the visible Energy tick marks in the source image.
TICK_ENERGY_KEV = np.array([20, 30, 40, 50, 60, 70, 80, 90], dtype=float)
TICK_X_PIXELS = np.array([53, 118, 184, 250, 317, 383, 449, 514], dtype=float)

# Trace region for the yellow spectrum line, chosen from the inner plot frame.
TRACE_X0 = 37
TRACE_X1 = 535
TRACE_Y_TOP = 134
TRACE_Y_BOTTOM = 292


def safe_output_stem(value: str, max_length: int = 96) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    stem = re.sub(r"_+", "_", stem).strip("_.-") or "plot"
    if len(stem) <= max_length:
        return stem
    digest = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:8]
    prefix_length = max(1, max_length - len(digest) - 1)
    return f"{stem[:prefix_length].rstrip('_.-')}_{digest}"


def pixel_to_energy(x_pixels: np.ndarray) -> np.ndarray:
    """Map image x pixels to Energy (keV) using the visible tick calibration."""
    slope, intercept = np.polyfit(TICK_ENERGY_KEV, TICK_X_PIXELS, 1)
    return (x_pixels - intercept) / slope


def extract_yellow_trace(image_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return digitized Energy and normalized Counts from the yellow spectrum."""
    image = Image.open(image_path).convert("RGB")
    arr = np.asarray(image)
    crop = arr[TRACE_Y_TOP : TRACE_Y_BOTTOM + 1, TRACE_X0 : TRACE_X1 + 1]
    r = crop[:, :, 0].astype(int)
    g = crop[:, :, 1].astype(int)
    b = crop[:, :, 2].astype(int)

    # Yellow spectrum threshold. The crop excludes the top labels, while the
    # artifact cleanup below removes the K-edge dashed guide lines.
    mask = (
        (r > 135)
        & (g > 115)
        & (b < 130)
        & (((r + g) / 2 - b) > 55)
        & ((r - b) > 65)
        & ((g - b) > 45)
    )

    x_grid = np.arange(TRACE_X0, TRACE_X1 + 1)
    y_grid = np.full_like(x_grid, np.nan, dtype=float)
    column_counts = np.zeros_like(x_grid, dtype=int)

    for ix in range(mask.shape[1]):
        rows = np.where(mask[:, ix])[0]
        if rows.size:
            y_grid[ix] = TRACE_Y_TOP + rows.min()
            column_counts[ix] = rows.size

    # Remove isolated vertical guide-line artifacts that jump far above the
    # local curve. Real peaks remain because neighboring columns support them.
    artifact = np.zeros_like(x_grid, dtype=bool)
    for i, y_value in enumerate(y_grid):
        if np.isnan(y_value):
            continue
        left = y_grid[max(0, i - 18) : max(0, i - 5)]
        right = y_grid[min(len(y_grid), i + 5) : min(len(y_grid), i + 18)]
        neighbors = np.r_[left[~np.isnan(left)], right[~np.isnan(right)]]
        if neighbors.size >= 5:
            local_median = np.median(neighbors)
            if column_counts[i] > 18 and y_value < local_median - 30:
                artifact[max(0, i - 1) : min(len(artifact), i + 2)] = True

    cleaned = y_grid.copy()
    cleaned[artifact] = np.nan
    valid = ~np.isnan(cleaned)
    if valid.sum() < 2:
        raise ValueError("Could not extract enough yellow trace points from the image.")

    interpolated = np.interp(x_grid, x_grid[valid], cleaned[valid])
    smoothed = medfilt(interpolated, kernel_size=5)
    smoothed = savgol_filter(smoothed, window_length=9, polyorder=2, mode="interp")

    energy = pixel_to_energy(x_grid.astype(float))
    peak_top = float(smoothed.min())
    counts = (TRACE_Y_BOTTOM - smoothed) / (TRACE_Y_BOTTOM - peak_top)

    in_range = (energy >= 20) & (energy <= 90)
    return energy[in_range], counts[in_range]


def write_csv(path: Path, energy: np.ndarray, counts: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Energy_keV", "Counts_normalized"])
        writer.writerows(zip(np.round(energy, 4), np.round(counts, 6)))


def plot_trace(
    energy: np.ndarray,
    counts: np.ndarray,
    output_dir: Path,
    stem: str,
    formats: list[str],
    annotate_edges: bool = True,
) -> list[Path]:
    apply_plot_style(font="arial", mode="single")
    fig, ax = plt.subplots(figsize=figure_size_for_subplot_aspect("16:8", subplot_height=2.65))
    fig.patch.set_alpha(0)
    ax.patch.set_alpha(0)

    ax.plot(energy, counts, color="#bd9e39", linewidth=1.35)

    ax.set_xlabel("Energy (keV)")
    ax.set_ylabel("Counts")
    ax.set_xlim(20, 90)
    ax.set_ylim(0, 1.05)

    format_te_axis(ax, show_grid=False, tick_labelsize=10)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(10))
    ax.xaxis.set_minor_locator(ticker.MultipleLocator(5))
    ax.yaxis.set_major_locator(ticker.MultipleLocator(0.2))
    ax.yaxis.set_minor_locator(ticker.MultipleLocator(0.1))
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.1f"))

    if annotate_edges:
        edge_items = [
            ("In", pixel_to_energy(np.array([88.0]))[0], "27.9 keV"),
            ("Ba", pixel_to_energy(np.array([180.0]))[0], "37.4 keV"),
            ("Pb", pixel_to_energy(np.array([450.0]))[0], "88.0 keV"),
        ]
        for element, xpos, energy_label in edge_items:
            ax.axvline(xpos, color="0.25", linestyle=(0, (4, 2)), linewidth=0.85, alpha=0.75)
            ax.text(
                xpos,
                1.03,
                f"{element}\nK-edge\n{energy_label}",
                ha="center",
                va="top",
                fontsize=7.5,
                color="black",
                linespacing=1.05,
            )

    fig.tight_layout(pad=0.35)
    save_figure(fig, stem, save_dir=str(output_dir), formats=formats, transparent=True)
    plt.close(fig)
    return [output_dir / f"{stem}.{fmt.lstrip('.').lower()}" for fmt in formats]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Default: a figures folder beside --image.",
    )
    parser.add_argument("--stem", default="k_edge_resolving_traced")
    parser.add_argument("--formats", nargs="+", default=["svg", "png"])
    parser.add_argument("--no-annotations", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output_dir is None:
        args.output_dir = args.image.expanduser().resolve().parent / "figures"
    elif not args.output_dir.is_absolute():
        args.output_dir = ROOT / args.output_dir
    args.stem = safe_output_stem(args.stem)
    energy, counts = extract_yellow_trace(args.image)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / f"{args.stem}_digitized.csv", energy, counts)
    paths = plot_trace(
        energy,
        counts,
        args.output_dir,
        args.stem,
        [fmt.lstrip(".").lower() for fmt in args.formats],
        annotate_edges=not args.no_annotations,
    )
    for path in [args.output_dir / f"{args.stem}_digitized.csv", *paths]:
        print(path)


if __name__ == "__main__":
    main()

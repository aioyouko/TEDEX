"""Regenerate the color galleries in docs/assets/color_sets from the registry."""

import argparse
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TMPDIR", tempfile.gettempdir())
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

from te_analysis.tools.colors import get_colors
from te_analysis.tools.plot import get_style_cycles
from te_analysis.tools.figure_naming import add_rename_argument, figure_output_naming, next_figure_stem

OUTPUT = ROOT / "docs" / "assets" / "color_sets"


def gallery(names, title, filename, count):
    rows = (len(names) + 1) // 2
    fig = plt.figure(figsize=(12, 1.1 + rows * 4.2), facecolor="white")
    fig.text(.055, .967, title, fontsize=20, weight="bold")
    fig.text(.055, .936, "Same simulated data / color + marker identity / white background", fontsize=10, color="#555555")
    panel_height = .84 / rows
    x = np.linspace(300, 800, 10)
    t = (x - 300) / 500
    for k, name in enumerate(names):
        row, col = divmod(k, 2)
        left = .07 + col * .49
        top = .879 - row * panel_height
        fig.text(left, top, f"--color-set {name}" + ("  (default)" if name == "npg" else ""), fontsize=13, weight="bold")
        swatches = fig.add_axes([left, top - panel_height * .18, .39, panel_height * .11])
        swatches.set(xlim=(0, count), ylim=(0, 1))
        swatches.axis("off")
        colors, markers = get_style_cycles(name, count)
        ax = fig.add_axes([left + .017, top - panel_height * .75, .373, panel_height * .49])
        for i, c in enumerate(get_colors(name, count)):
            swatches.add_patch(Rectangle((i + .02, .4), .94, .6, color=c, linewidth=0))
            swatches.text(i + .49, .07, c.upper(), ha="center", fontsize=7)
            y = .22 + .065 * i + (.66 + .016 * i) * t + .07 * np.sin(np.pi * t + .3 * i)
            ax.plot(x, y, color=next(colors), marker=next(markers), ms=4, lw=1.15, label=f"S{i + 1}")
        ax.set(xlim=(280, 820), ylim=(.15, 1.65 if count == 8 else 1.4), xticks=[300, 400, 500, 600, 700, 800])
        ax.set_xlabel("Temperature (K)", fontsize=10, labelpad=2)
        ax.set_ylabel("ZT (simulated)", fontsize=10, labelpad=2)
        ax.tick_params(direction="in", top=True, right=True, labelsize=9)
        ax.legend(ncol=4 if count == 8 else 5, fontsize=8, frameon=False,
                  loc="upper left", handlelength=1.2, handletextpad=.3, columnspacing=.8)
    fig.text(.055, .029, "Shades follow input order, not performance. Explicit curve colors override automatic colors.", fontsize=10, color="#555555")
    filename = f"{next_figure_stem(Path(filename).stem)}{Path(filename).suffix}"
    fig.savefig(OUTPUT / filename, dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_rename_argument(parser)
    args = parser.parse_args()
    with figure_output_naming(args.rename):
        return _run_cli()


def _run_cli():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    gallery(["npg", "science", "classic", "blue-orange"], "Categorical color sets", "categorical.png", 8)
    gallery(["blue", "teal", "purple", "orange", "red", "gray"], "Sequential color sets / five batches", "sequential.png", 5)
    fig, ax = plt.subplots(figsize=(12, 3.7))
    ax.set(xlim=(0, 8), ylim=(-.1, 3.4))
    ax.axis("off")
    for i, color in enumerate(get_colors("legacy")):
        row, col = divmod(i, 8)
        y = 2.6 - row
        ax.add_patch(Rectangle((col + .06, y), .87, .48, color=color, linewidth=0))
        ax.text(col + .5, y - .22, f"{i + 1:02d}  {color.upper()}", ha="center", fontsize=9)
    ax.set_title("--color-set legacy / original 24-color order", loc="left", fontsize=15, pad=15)
    fig.tight_layout()
    fig.savefig(OUTPUT / f"{next_figure_stem('legacy')}.png", dpi=160)
    plt.close(fig)
    print(f"Color galleries saved to {OUTPUT}")


if __name__ == "__main__":
    main()

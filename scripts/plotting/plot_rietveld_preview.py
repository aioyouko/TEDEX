"""Single-panel Rietveld figure using the project's XRD publication style.

This renders saved refinements only; it never refits, smooths, or rescales
observed and calculated intensities independently.
"""
from pathlib import Path
import argparse
import json
import os
import re
import sys
import zipfile

os.environ.setdefault("MPLBACKEND", "Agg")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, NullLocator
from te_analysis.tools.plot import apply_plot_style, format_te_axis
from te_analysis.tools.colors import get_colors

SOURCE = ROOT / "data/inter/CuInGaTe2-04CdZnSe/element_modify/gsas_refinement_2026-10-23"
OUTPUT = ROOT / "results/plots/xrd_rietveld_20261023"


def formula_label(recipe):
    """Keep recipe coefficients while typesetting elemental subscripts."""
    def element(match):
        symbol, amount = match.groups()
        return rf"\mathrm{{{symbol}}}" + (rf"_{{{amount}}}" if amount else "")
    return "$" + re.sub(r"([A-Z][a-z]?)([0-9]+(?:\.[0-9]+)?)?", element,
                         recipe.replace(" ", "")) + "$"


def make_plot(index=8):
    tags = json.loads((SOURCE / "selected_models.json").read_text())["Rietveld"]
    tag = tags[str(index)]
    result = json.loads((SOURCE / "results" / f"{tag}.json").read_text())
    sample = json.loads((SOURCE / "sample_manifest.json").read_text())["samples"][index]
    profile = np.loadtxt(SOURCE / "results" / f"{tag}_profile.csv", delimiter=",", skiprows=1)
    x, obs, calc, background, difference, weights = profile.T
    rwp = 100 * np.sqrt(np.sum(weights * difference**2) / np.sum(weights * obs**2))
    rp = 100 * np.sum(np.abs(difference)) / np.sum(np.abs(obs))
    assert np.isclose(rwp, result["Rwp"], atol=1.e-9)
    assert np.allclose(obs - calc, difference)

    apply_plot_style(mode="single")
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["Arial"],
        "mathtext.rm": "Arial", "mathtext.it": "Arial:italic",
        "mathtext.bf": "Arial:bold", "svg.fonttype": "none", "pdf.fonttype": 42,
    })
    colors = get_colors("npg")
    fig, ax = plt.subplots(figsize=(9.0, 6.1))
    fig.subplots_adjust(left=.105, right=.98, bottom=.14, top=.965)
    format_te_axis(ax)
    for spine in ax.spines.values():
        spine.set_linewidth(1.1)
    ax.tick_params(axis="both", which="both", width=1.1)
    # XRD-specific axis rules, matching te_analysis/tools/xrd/render.py.
    ax.tick_params(axis="x", which="both", direction="out", top=False)
    ax.tick_params(axis="y", which="both", left=False, right=False, labelleft=False)
    ax.xaxis.set_major_locator(MultipleLocator(10))
    ax.xaxis.set_minor_locator(MultipleLocator(5))
    ax.yaxis.set_major_locator(NullLocator())
    ax.yaxis.set_minor_locator(NullLocator())
    ax.set_xlim(10, 80)
    ax.set_xlabel(r"$2\theta$ (degree)")
    ax.set_ylabel(r"$\mathit{Intensity}$ (a.u.)", labelpad=12)

    norm = obs.max()
    lowest_tick = .012 - .065 * (len(result["phases"]) - 1)
    diff_offset = min(-.28, lowest_tick - .09 - difference.max() / norm)
    ax.plot(x, obs / norm, linestyle="none", marker="o", ms=2.8,
            mfc="none", mec="black", mew=.65, label="Observed", zorder=3)
    ax.plot(x, calc / norm, color=colors[1], lw=1.25, label="Calculated", zorder=4)
    ax.plot(x, difference / norm + diff_offset, color=colors[0], lw=.95,
            label="Difference", zorder=3)
    ax.axhline(diff_offset, color="#999999", lw=.55, zorder=1)
    ax.set_ylim(min(-.47, difference.min() / norm + diff_offset - .05), 1.53)

    phase_colors = [colors[2], "#8064A2"]
    space_groups = []
    for k, phase in enumerate(result["phases"]):
        tetragonal = phase["name"].startswith("chalcopyrite")
        sg = r"$I\overline{4}2d$" if tetragonal else r"$F\overline{4}3m$"
        space_groups.append(sg)
        reflections = np.loadtxt(SOURCE / "results" / f"{tag}_{phase['name']}_reflections.csv",
                                 delimiter=",", skiprows=1)
        positions = reflections[:, 5]
        positions = positions[(positions >= 10) & (positions <= 80)]
        y = .012 - .065 * k
        ax.vlines(positions, y - .016, y + .016, color=phase_colors[k], lw=1.0)
        ax.text(11.0, y, sg, color=phase_colors[k], va="center", ha="left",
                fontsize=13, bbox={"facecolor": "white", "edgecolor": "none", "pad": .6})

    ax.legend(loc="upper left", bbox_to_anchor=(.025, .955), fontsize=13.5,
              handlelength=1.7, handletextpad=.6, labelspacing=.5,
              markerscale=2.4, borderaxespad=0)

    # Nominal composition is a sample label, not refined phase chemistry.
    recipe_math = formula_label(sample["nominal_recipe"])
    ax.text(.98, .955, recipe_math, transform=ax.transAxes,
            ha="right", va="top", fontsize=16)
    ax.text(.98, .845, rf"$R_{{\mathrm{{wp}}}}={rwp:.2f}\%$   $R_{{\mathrm{{p}}}}={rp:.2f}\%$",
            transform=ax.transAxes, ha="right", va="top", fontsize=17)
    for k, phase in enumerate(result["phases"]):
        c = phase["cell"]
        line = space_groups[k] + rf": $a={c['length_a']:.3f}$ Å"
        if phase["name"].startswith("chalcopyrite"):
            line += rf", $c={c['length_c']:.3f}$ Å"
        ax.text(.98, .735 - .075 * k, line, transform=ax.transAxes,
                ha="right", va="top", fontsize=14.5, color=phase_colors[k])

    OUTPUT.mkdir(parents=True, exist_ok=True)
    stem = f"{sample['sample_label']}_Rietveld"
    files = []
    for extension in ("png", "pdf", "svg"):
        target = OUTPUT / f"{stem}.{extension}"
        fig.savefig(target, dpi=400, facecolor="white", bbox_inches="tight", pad_inches=.08)
        files.append(str(target.relative_to(ROOT)))
    plt.close(fig)
    metadata = {
        "sample": sample["sample_label"], "source_model": tag,
        "nominal_recipe": sample["nominal_recipe"], "formula_mathtext": recipe_math,
        "sample_identifier_displayed": False,
        "source_profile": str((SOURCE / "results" / f"{tag}_profile.csv").relative_to(ROOT)),
        "source_refinement": str((SOURCE / "results" / f"{tag}.json").relative_to(ROOT)),
        "Rwp_percent": rwp, "Rp_percent": rp,
        "Rp_definition": "100 * sum(abs(observed-calculated)) / sum(abs(observed)); background included",
        "normalization": "All three profiles divided by the same observed maximum; background retained",
        "observed_point_count": len(x), "observed_points_displayed": len(x),
        "smoothing": False, "difference_multiplier": 1,
        "difference_vertical_offset_in_normalized_units": diff_offset,
        "reflection_ticks": "GSAS-II RefList 2theta positions for each selected model component",
        "figure_size_inches": [9.0, 6.1], "files": files,
        "style": {"observed": "black hollow circles", "marker_size_pt": 2.8,
                  "marker_edge_width_pt": .65, "spine_width_pt": 1.1,
                  "major_tick_width_pt": 1.1, "minor_tick_width_pt": 1.1,
                  "Intensity_label_italic": True},
        "limitations": "Fixed-chemistry working model. Phase symmetry/chemistry is not uniquely established. Lattice values are model estimates, not calibrated absolute accuracy. Rwp uses provisional 1/I weights.",
    }
    (OUTPUT / f"{stem}_metadata.json").write_text(json.dumps(metadata, indent=2))
    reflection_caption = (
        "两排刻线分别为 I−42d 和 F−43m 工作组分的反射位置。"
        if len(result["phases"]) == 2 else
        "一排刻线为 I−42d 工作组分的反射位置，单组分拟合不代表已确认相纯。"
    )
    caption = (
        f"{sample['sample_label']} 的粉末 XRD Rietveld 工作模型拟合。黑色空心点：实测强度；红线：计算强度；"
        "蓝线：实测减计算的差谱，向下平移，未放大。" + reflection_caption +
        "三条曲线使用相同归一化因子，保留背景；实测点全部绘出，未平滑。"
        f"Rwp={rwp:.2f}%，Rp={rp:.2f}%。图中成分为名义配方，晶格参数来自所选 Rietveld 工程。"
        "结构组分身份及绝对晶格精度仍受模型假设限制，不能据此认定纯 ZnSe 相或测得元素占位。\n"
    )
    (OUTPUT / f"{stem}_caption.txt").write_text(caption)
    print("\n".join(files))
    print(f"Rwp={rwp:.6f}%; Rp={rp:.6f}%")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, default=8)
    parser.add_argument("--all", action="store_true", help="Render all selected Rietveld models")
    args = parser.parse_args()
    if args.all:
        rows = [make_plot(i) for i in range(12)]
        (OUTPUT / "plot_manifest.json").write_text(json.dumps(rows, indent=2))
        with zipfile.ZipFile(OUTPUT / "Rietveld_all_12_SVG.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
            for row in rows:
                svg = next(ROOT / file for file in row["files"] if file.endswith(".svg"))
                bundle.write(svg, arcname=svg.name)
    else:
        make_plot(args.index)

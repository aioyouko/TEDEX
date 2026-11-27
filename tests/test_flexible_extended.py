"""End-to-end tests for extended flexible plot kinds, overlays, recipes, and --figure CLI."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from _helpers import REPO_ROOT, run_cli


RECIPE_ROOT = REPO_ROOT / "configs" / "plot_recipes"


def _assert_cli_ok(args: list[str], out_dir: Path) -> list[Path]:
    result = run_cli(["sciplot", *args, "--output-dir", str(out_dir), "--no-copy-to-data-dir", "--no-show"])
    assert result.returncode == 0, f"CLI failed for {args}:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    pngs = sorted(out_dir.glob("*.png"))
    assert pngs, f"No PNG generated for {args}"
    return pngs


def test_stacked_bar_and_percent_stacked_bar_recipes():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        csv_path = tmp_path / "kappa_parts.csv"
        pd.DataFrame(
            {
                "Sample": ["x=0", "x=0.02", "x=0.04", "x=0.06"],
                "kappa_L": [1.35, 0.92, 0.64, 0.51],
                "kappa_e": [0.18, 0.31, 0.42, 0.48],
            }
        ).to_csv(csv_path, index=False)

        _assert_cli_ok(
            [
                str(csv_path),
                "--figure",
                "thermal_conductivity_breakdown_stacked",
                "--stem",
                "stacked_k",
            ],
            tmp_path / "out_stacked",
        )
        _assert_cli_ok(
            [
                "--figure",
                "percent_stacked_bar",
                str(csv_path),
                "--x",
                "Sample",
                "--y",
                "kappa_L",
                "--y",
                "kappa_e",
                "--label",
                "Lattice",
                "--label",
                "Electronic",
                "--stem",
                "pct_stacked",
            ],
            tmp_path / "out_pct",
        )


def test_waterfall_delta_and_levels_modes():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        csv_path = tmp_path / "waterfall.csv"
        pd.DataFrame(
            {
                "Step": ["Pristine", "+Ga doping", "+ZnSe alloying", "+Annealing", "Optimized"],
                "Value": [0.45, 0.32, 0.41, 0.22, 1.40],
                "Step_Type": ["start", "delta", "delta", "delta", "total"],
            }
        ).to_csv(csv_path, index=False)

        _assert_cli_ok(
            [str(csv_path), "--recipe", str(RECIPE_ROOT / "bar" / "waterfall_steps.json"), "--ylim", "0", "1.7"],
            tmp_path / "out_wf_recipe",
        )
        _assert_cli_ok(
            ["--figure", "waterfall", str(csv_path), "--x", "Step", "--y", "Value", "--waterfall-mode", "levels"],
            tmp_path / "out_wf_levels",
        )


def test_heatmap_contour_bubble_and_ternary():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Regular (T, x, ZT) grid for heatmap & contour
        rows = []
        for t_k in (300, 450, 600, 750):
            for x_frac in (0.0, 0.02, 0.04, 0.06):
                zt = 0.15 + 0.0016 * (t_k - 300) + 5.5 * x_frac * (0.08 - x_frac)
                rows.append({"T_K": t_k, "Composition_x": x_frac, "ZT": round(zt, 3)})
        grid_csv = tmp_path / "phase_grid.csv"
        pd.DataFrame(rows).to_csv(grid_csv, index=False)

        _assert_cli_ok(
            [str(grid_csv), "--figure", "contour_phase_map", "--xlim", "300", "750", "--zlim", "0.1", "1.2"],
            tmp_path / "out_contour",
        )
        _assert_cli_ok(
            ["--figure", "heatmap", str(grid_csv), "--x", "T_K", "--y", "Composition_x", "--z", "ZT", "--zlabel", "$zT$"],
            tmp_path / "out_heatmap",
        )

        # Bubble screening
        bubble_csv = tmp_path / "bubble.csv"
        pd.DataFrame(
            {
                "Material": ["CuInTe2", "CuGaTe2", "AgInTe2", "CuIn0.8Ga0.2Te2"],
                "kappa_L": [1.8, 2.2, 0.9, 0.65],
                "PF": [6.5, 8.2, 4.8, 11.4],
                "T_K": [700, 750, 650, 750],
                "ZT": [0.42, 0.51, 0.62, 1.32],
            }
        ).to_csv(bubble_csv, index=False)
        _assert_cli_ok([str(bubble_csv), "--figure", "bubble_screening"], tmp_path / "out_bubble")

        # Ternary diagram
        ternary_csv = tmp_path / "ternary.csv"
        pd.DataFrame(
            {
                "Comp_A": [80, 60, 40, 20, 50, 30, 15, 70],
                "Comp_B": [10, 30, 50, 70, 20, 40, 25, 25],
                "Comp_C": [10, 10, 10, 10, 30, 30, 60, 5],
                "ZT": [0.55, 0.82, 0.96, 0.64, 1.25, 1.38, 0.72, 0.68],
            }
        ).to_csv(ternary_csv, index=False)
        _assert_cli_ok(
            [str(ternary_csv), "--figure", "ternary_composition", "--alabel", "CuInTe$_2$", "--blabel", "CuGaTe$_2$", "--clabel", "ZnSe"],
            tmp_path / "out_ternary",
        )


def test_boxplot_violin_histogram_parity_and_arrhenius():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        dist_csv = tmp_path / "hardness.csv"
        rng = np.random.default_rng(7)
        dist_rows = []
        for sample, mean_hv in (("x=0", 1.85), ("x=0.02", 2.15), ("x=0.04", 2.42)):
            for val in rng.normal(mean_hv, 0.11, size=10):
                dist_rows.append({"Sample": sample, "Hardness_GPa": round(float(val), 3)})
        pd.DataFrame(dist_rows).to_csv(dist_csv, index=False)

        _assert_cli_ok([str(dist_csv), "--figure", "boxplot_distribution"], tmp_path / "out_box")
        _assert_cli_ok(
            ["--figure", "violin", str(dist_csv), "--x", "Sample", "--y", "Hardness_GPa"],
            tmp_path / "out_violin",
        )

        grain_csv = tmp_path / "grains.csv"
        pd.DataFrame({"Diameter_nm": np.exp(rng.normal(math.log(42.0), 0.35, size=80))}).to_csv(grain_csv, index=False)
        _assert_cli_ok([str(grain_csv), "--figure", "grain_size_histogram"], tmp_path / "out_hist")

        parity_csv = tmp_path / "parity.csv"
        exp_vals = np.linspace(0.25, 1.45, 16)
        pred_vals = exp_vals + rng.normal(0.0, 0.06, size=16)
        pd.DataFrame(
            {
                "Experimental": exp_vals,
                "Predicted": pred_vals,
                "Split": ["Train"] * 10 + ["Test"] * 6,
            }
        ).to_csv(parity_csv, index=False)
        _assert_cli_ok([str(parity_csv), "--figure", "parity_pred_vs_exp"], tmp_path / "out_parity")

        arr_csv = tmp_path / "arrhenius.csv"
        temps = np.array([300, 350, 400, 500, 600, 700, 800], dtype=float)
        arr_rows = []
        for sample, ea_ev, s0 in (("Undoped", 0.18, 4500.0), ("Doped", 0.08, 1800.0)):
            sig = s0 * np.exp(-ea_ev / (8.617333e-5 * temps))
            for t_val, s_val in zip(temps, sig):
                arr_rows.append({"Sample": sample, "T_K": t_val, "sigma": s_val})
        pd.DataFrame(arr_rows).to_csv(arr_csv, index=False)
        _assert_cli_ok([str(arr_csv), "--figure", "arrhenius_conductivity", "--fit-range", "400", "800"], tmp_path / "out_arr")


def test_broken_axis_fit_residual_radar_benchmark_and_overlays():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Broken axis
        broken_csv = tmp_path / "broken.csv"
        pd.DataFrame(
            {
                "Sample": ["Sample A"] * 4 + ["Sample B"] * 4,
                "T_K": [300, 450, 600, 750] * 2,
                "sigma": [1380, 1210, 280, 210, 195, 170, 145, 125],
            }
        ).to_csv(broken_csv, index=False)
        _assert_cli_ok([str(broken_csv), "--figure", "broken_axis_line"], tmp_path / "out_broken")

        # Fit + residual
        x_deg = np.linspace(26.0, 30.0, 120)
        p1 = 80.0 * np.exp(-((x_deg - 27.6) / 0.32) ** 2)
        p2 = 45.0 * np.exp(-((x_deg - 28.25) / 0.38) ** 2)
        calc = 10.0 + p1 + p2
        rng = np.random.default_rng(12)
        obs = calc + rng.normal(0.0, 1.5, size=len(x_deg))
        fit_csv = tmp_path / "fit_res.csv"
        pd.DataFrame({"X": x_deg, "Observed": obs, "Calculated": calc, "Peak_1": p1, "Peak_2": p2}).to_csv(fit_csv, index=False)
        _assert_cli_ok([str(fit_csv), "--figure", "fit_with_residual"], tmp_path / "out_fit")

        # Radar
        radar_csv = tmp_path / "radar.csv"
        metrics = ["$zT_{\\max}$", "$zT_{\\mathrm{avg}}$", "$\\sigma$", "$1/\\kappa_{\\mathrm{L}}$", "$H_{\\mathrm{V}}$"]
        r_rows = []
        for mat, vals in (("Baseline", [0.65, 0.38, 120, 0.8, 1.8]), ("This work", [1.35, 0.82, 240, 1.9, 2.4])):
            for m_name, v in zip(metrics, vals):
                r_rows.append({"Material": mat, "Metric": m_name, "Score": v})
        pd.DataFrame(r_rows).to_csv(radar_csv, index=False)
        _assert_cli_ok([str(radar_csv), "--figure", "radar_multi_metric"], tmp_path / "out_radar")

        # Benchmark + Error band + Inset + Reference line
        bench_csv = tmp_path / "benchmark.csv"
        t_grid = np.array([300, 400, 500, 600, 700, 800], dtype=float)
        b_rows = []
        for name, scale in (("Ref. A (2022)", 0.55), ("Ref. B (2024)", 0.72), ("This work", 1.15)):
            for t_val in t_grid:
                zt_val = scale * ((t_val - 250.0) / 550.0) ** 1.4 + 0.08
                b_rows.append({"Sample": name, "T_K": t_val, "ZT": zt_val})
        pd.DataFrame(b_rows).to_csv(bench_csv, index=False)

        _assert_cli_ok(
            [str(bench_csv), "--figure", "temperature_vs_zt_benchmark", "--end-labels"],
            tmp_path / "out_bench",
        )
        _assert_cli_ok(
            [
                str(bench_csv),
                "--figure",
                "line",
                "--group",
                "Sample",
                "--x",
                "T_K",
                "--y",
                "ZT",
                "--yerr-pct",
                "8",
                "--error-mode",
                "both",
                "--hline",
                "1.0,$zT=1$,#444444,--",
                "--inset-xlim",
                "650",
                "800",
                "--inset-ylim",
                "0.7",
                "1.35",
            ],
            tmp_path / "out_overlays",
        )

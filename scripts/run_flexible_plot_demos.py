#!/usr/bin/env python3
"""
Generate loose demo tables and render the flexible plotting recipes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.flexible_plot import load_recipe, plot_recipe  # noqa: E402


DEMO_DATA_DIR = Path("data/demo/generated_flexible_plotting")
RECIPE_DIR = Path("configs/flexible_plot_demos")
DEFAULT_RECIPES = [
    RECIPE_DIR / "temperature_seebeck_line.json",
    RECIPE_DIR / "temperature_multi_panel.json",
    RECIPE_DIR / "room_temp_dual_axis.json",
    RECIPE_DIR / "composition_scatter.json",
    RECIPE_DIR / "pbse_tec_dtmax_txt.json",
    RECIPE_DIR / "pbse_tec_qc_excel_multicolumn.json",
    RECIPE_DIR / "pbse_tec_qc_multi_files.json",
]


def generate_temperature_series(workspace: Path) -> pd.DataFrame:
    out_dir = workspace / DEMO_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(12)
    temperatures = np.arange(300, 825, 75)
    sample_params = [
        ("CHY-DEMO-A", 138, 640, 1.62, 0.10),
        ("CHY-DEMO-B", 166, 520, 1.48, 0.15),
        ("CHY-DEMO-C", 188, 410, 1.38, 0.21),
        ("CHY-DEMO-D", 212, 310, 1.31, 0.26),
    ]

    rows = []
    for sample, s0, sigma0, k0, zt0 in sample_params:
        for temp in temperatures:
            dt = temp - 300
            seebeck = s0 + 0.060 * dt - 0.000030 * dt**2 + rng.normal(0, 2.0)
            sigma = sigma0 * np.exp(-0.00095 * dt) + rng.normal(0, 8.0)
            power_factor = seebeck**2 * sigma * 1e-6
            k_total = k0 - 0.00055 * dt + rng.normal(0, 0.025)
            zt = zt0 + 0.00072 * dt + 0.00000040 * dt**2 + rng.normal(0, 0.012)
            rows.append(
                {
                    "Specimen": sample,
                    "Temp / K": temp,
                    "S (uV/K)": round(seebeck, 2),
                    "sigma [S cm-1]": round(max(sigma, 25), 2),
                    "Power factor": round(max(power_factor, 0), 3),
                    "k-total W/m-K": round(max(k_total, 0.55), 3),
                    "zT value": round(max(zt, 0), 3),
                    "operator note": "demo loose column names",
                }
            )

    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "messy_te_temperature_series.csv", index=False)
    return df


def generate_room_temp_snapshot(workspace: Path, temperature_df: pd.DataFrame) -> None:
    out_dir = workspace / DEMO_DATA_DIR
    room_temp = temperature_df[temperature_df["Temp / K"] == 300].copy()
    room_temp = room_temp.rename(
        columns={
            "Specimen": "ID",
            "Temp / K": "Temperature_K",
            "S (uV/K)": "Seebeck_microV_K",
        }
    )
    room_temp["EC_S_per_m"] = (room_temp["sigma [S cm-1]"] * 100).round(1)
    room_temp["batch"] = "demo batch"
    room_temp["nominal Cu"] = [0.00, 0.03, 0.06, 0.10]
    columns = ["ID", "Temperature_K", "Seebeck_microV_K", "EC_S_per_m", "batch", "nominal Cu"]
    room_temp[columns].to_csv(out_dir / "room_temp_snapshot_mixed_units.csv", index=False)


def generate_literature_scatter(workspace: Path) -> None:
    out_dir = workspace / DEMO_DATA_DIR
    rows = [
        ("Base", 0.00, 0.42, "This work"),
        ("Ag-0.02", 0.02, 0.58, "This work"),
        ("Ag-0.05", 0.05, 0.76, "This work"),
        ("Ag-0.08", 0.08, 0.83, "This work"),
        ("Ag-0.12", 0.12, 0.71, "This work"),
        ("Ref-A", 0.01, 0.50, "Literature"),
        ("Ref-B", 0.06, 0.68, "Literature"),
        ("Ref-C", 0.10, 0.79, "Literature"),
        ("Ref-D", 0.16, 0.62, "Literature"),
    ]
    df = pd.DataFrame(rows, columns=["Material name", "Ag fraction x", "Best zT", "Source class"])
    df.to_csv(out_dir / "literature_comparison_loose.csv", index=False)


def generate_pbse_tec_examples(workspace: Path) -> None:
    out_dir = workspace / DEMO_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    dtmax = pd.DataFrame(
        {
            "T_H_K": [303, 312, 322, 333, 343, 353, 363],
            "DeltaTmax_K": [38.5, 40.8, 43.2, 45.5, 48.0, 50.6, 53.1],
        }
    )
    dtmax.to_csv(out_dir / "pbse_tec_dtmax_curve.txt", sep="\t", index=False)

    current = np.arange(0, 21, 1)
    qc = pd.DataFrame(
        {
            "I_A": current,
            "Qc_DT0_W": [
                0.10,
                0.35,
                0.65,
                1.00,
                1.35,
                1.75,
                2.10,
                2.45,
                2.75,
                3.05,
                3.40,
                3.70,
                4.00,
                4.30,
                4.55,
                4.85,
                5.10,
                5.35,
                5.58,
                5.78,
                5.95,
            ],
            "Qc_DT5_W": [
                np.nan,
                np.nan,
                np.nan,
                0.05,
                0.45,
                0.80,
                1.15,
                1.50,
                1.85,
                2.15,
                2.50,
                2.80,
                3.05,
                3.35,
                3.60,
                3.85,
                4.10,
                4.30,
                4.50,
                4.65,
                4.85,
            ],
            "Qc_DT10_W": [
                np.nan,
                np.nan,
                np.nan,
                np.nan,
                np.nan,
                np.nan,
                0.05,
                0.45,
                0.80,
                1.10,
                1.45,
                1.75,
                2.05,
                2.35,
                2.60,
                2.85,
                3.10,
                3.30,
                3.50,
                3.65,
                3.85,
            ],
        }
    )
    qc.to_excel(out_dir / "pbse_tec_qc_multicolumn.xlsx", sheet_name="Qc curves", index=False)

    split_dir = out_dir / "pbse_tec_qc_split"
    split_dir.mkdir(parents=True, exist_ok=True)
    for column, filename in [
        ("Qc_DT0_W", "dt0.csv"),
        ("Qc_DT5_W", "dt5.txt"),
        ("Qc_DT10_W", "dt10.csv"),
    ]:
        split = qc[["I_A", column]].dropna().rename(columns={column: "Qc_W"})
        if filename.endswith(".txt"):
            split.to_csv(split_dir / filename, sep="\t", index=False)
        else:
            split.to_csv(split_dir / filename, index=False)


def generate_demo_data(workspace: Path) -> None:
    temperature_df = generate_temperature_series(workspace)
    generate_room_temp_snapshot(workspace, temperature_df)
    generate_literature_scatter(workspace)
    generate_pbse_tec_examples(workspace)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run flexible plotting demo recipes.")
    parser.add_argument("--workspace", default=str(ROOT), help="Workspace root.")
    parser.add_argument("--skip-data", action="store_true", help="Use existing demo data files.")
    parser.add_argument("--recipe", action="append", help="Recipe path relative to workspace. Can be repeated.")
    parser.add_argument("--show", dest="show", action="store_true", default=True, help="Display each figure after saving. Default: on.")
    parser.add_argument("--no-show", dest="show", action="store_false", help="Save figures without displaying them.")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    if not args.skip_data:
        generate_demo_data(workspace)

    recipe_paths = [Path(path) for path in args.recipe] if args.recipe else DEFAULT_RECIPES
    results = []
    for recipe_path in recipe_paths:
        resolved_recipe_path = recipe_path if recipe_path.is_absolute() else workspace / recipe_path
        recipe = load_recipe(resolved_recipe_path)
        result = plot_recipe(recipe, workspace=workspace, show=args.show)
        results.append({"recipe": str(resolved_recipe_path), **result})

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

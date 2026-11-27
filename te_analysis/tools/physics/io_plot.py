"""Shared I/O, column discovery, Jacobian covariance diagnostics, and house-style plot helpers
for thermoelectric physics fitting models (Callaway, Debye-Einstein, SKB, Two-Band).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from te_analysis.tools.matplotlib_backend import configure_matplotlib_backend

configure_matplotlib_backend()

import matplotlib.pyplot as plt  # noqa: E402

from te_analysis.tools.colors import add_color_set_argument, get_colors  # noqa: E402
from te_analysis.tools.figure_naming import add_rename_argument, figure_output_naming  # noqa: E402
from te_analysis.tools.legend_layout import place_legend_inside  # noqa: E402
from te_analysis.tools.plot import (  # noqa: E402
    DEFAULT_AXIS_LABEL_SIZE,
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_LINE_WIDTH,
    DEFAULT_MARKER_SIZE,
    DEFAULT_SUBPLOT_ASPECT,
    DEFAULT_SUBPLOT_HEIGHT,
    DEFAULT_TICK_LABEL_SIZE,
    apply_plot_style,
    figure_size_for_subplot_aspect,
    format_te_axis,
    normalize_output_formats,
    save_figure_outputs,
)


# Unified house colors for physics fitting plots:
# - Final best-fit curve highlighted in vibrant crimson-coral red (#E64B35)
# - Experimental data points in soft steel-blue fill (#79ADD8) with crisp navy edge (#264B73)
# - Intermediate / reference curves in distinct non-red tones so red exclusively marks the best fit
FIT_RED_COLOR = "#E64B35"
EXP_MARKER_FACE = "#79ADD8"
EXP_MARKER_EDGE = "#264B73"
STAGE_NONRED_PALETTE = (
    "#3C5488",  # deep indigo
    "#00A087",  # emerald teal
    "#7B61A6",  # muted violet
    "#C88A2B",  # warm amber
    "#4DBBD5",  # cyan
    "#7E6148",  # warm brown
)


TEMPERATURE_CANDIDATES = (
    "Temperature",
    "Temperature_K",
    "T_K",
    "T",
    "Temp",
    "Temp_K",
)

KAPPA_L_CANDIDATES = (
    "Lattice_Thermal_Conductivity",
    "Lattice_Thermal_Conductivity_W_m-1_K-1",
    "kappa_L",
    "kappa_L_W_mK",
    "kappa_L_W_m-1_K-1",
    "kL",
    "kL_W_mK",
    "kappa_lattice",
    "k_lat",
)

KAPPA_TOT_CANDIDATES = (
    "Thermal_Conductivity",
    "Thermal_Conductivity_W_m-1_K-1",
    "Thermal_Conductivity_W_mK",
    "kappa",
    "kappa_W_mK",
    "kappa_tot",
    "k_total",
)

SEEBECK_CANDIDATES = (
    "Seebeck",
    "Seebeck_uV_K",
    "S_uV_K",
    "S",
    "seebeck",
)

CONDUCTIVITY_CANDIDATES = (
    "Conductivity",
    "Conductivity_S_cm-1",
    "Conductivity_S_m-1",
    "sigma",
    "electrical_conductivity",
)

RESISTIVITY_CANDIDATES = (
    "Resistivity",
    "Resistivity_uOhm_m",
    "Resistivity_Ohm_m",
    "Resistivity_mOhm_cm",
    "Resistivity_uOhm_cm",
    "Resistivity_Ohm_cm",
    "rho",
    "rho_uOhm_m",
    "electrical_resistivity",
)

NH_CANDIDATES = (
    "nH",
    "nH_cm-3",
    "Hall_Carrier_Concentration",
    "Hall_Carrier_Concentration_cm-3",
    "Carrier_Concentration",
    "carrier_concentration",
    "n_H",
)

HALL_COEFF_CANDIDATES = (
    "RH",
    "R_H",
    "Hall_Coefficient",
    "Hall_Coefficient_m3_C-1",
    "Hall_Coefficient_cm3_C-1",
    "RH_1e-7_m3_C",
    "RH_m3_C",
    "RH_cm3_C",
)

MOBILITY_CANDIDATES = (
    "muH",
    "Hall_Mobility",
    "Hall_Mobility_cm2_V-1_s-1",
    "Mobility",
    "mobility",
    "mu_H",
)

PF_CANDIDATES = (
    "PF",
    "Power_Factor",
    "Power_Factor_uW_cm-1_K-2",
    "PF_uW_cm-1_K-2",
    "power_factor",
)

ZT_CANDIDATES = (
    "ZT",
    "zT",
    "zt",
)

CP_CANDIDATES = (
    "Cp",
    "Cp_J_mol-1_K-1",
    "Heat_Capacity",
    "heat_capacity",
    "C_p",
    "Cv",
    "Cp_J_molK",
    "Cp_mJ_molK",
)


def normalize_col_key(name: str) -> str:
    return (
        str(name)
        .strip()
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
        .replace("(", "")
        .replace(")", "")
        .replace("[", "")
        .replace("]", "")
    )


def find_column(
    df: pd.DataFrame,
    preferred: str | None,
    candidates: Sequence[str],
    *,
    required: bool = True,
) -> str | None:
    if preferred:
        if preferred not in df.columns:
            raise ValueError(f"Column {preferred!r} not found in {list(df.columns)}")
        return preferred
    mapping = {normalize_col_key(col): str(col) for col in df.columns}
    for cand in candidates:
        hit = mapping.get(normalize_col_key(cand))
        if hit is not None:
            return hit
    if required:
        raise ValueError(
            f"Could not find required column among {list(candidates)}. Available: {list(df.columns)}"
        )
    return None


def read_tabular_data(path: str | os.PathLike[str]) -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Input data file not found: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(file_path)
    if suffix in {".tsv", ".txt", ".dat"}:
        return pd.read_csv(file_path, sep=None, engine="python", comment="#")
    return pd.read_csv(file_path)


def infer_seebeck_uv_k(series: pd.Series, explicit_unit: str = "auto") -> pd.Series:
    vals = pd.to_numeric(series, errors="coerce").astype(float)
    u = explicit_unit.strip().lower().replace(" ", "")
    if u in {"v/k", "vk-1", "vk^-1"}:
        return vals * 1e6
    if u in {"uv/k", "uvk-1", "uvk^-1", "microv/k"}:
        return vals
    # Processed TE CSVs store Seebeck in V/K (~1e-4), while summary tables use uV/K (~100)
    finite = vals.dropna().abs()
    if not finite.empty and float(finite.max()) < 2.0:
        return vals * 1e6
    return vals


def infer_conductivity_s_m(series: pd.Series, col_name: str, explicit_unit: str = "auto") -> pd.Series:
    vals = pd.to_numeric(series, errors="coerce").astype(float)
    u = explicit_unit.strip().lower().replace(" ", "")
    if u in {"s/cm", "scm-1", "scm^-1"}:
        return vals * 100.0
    if u in {"s/m", "sm-1", "sm^-1"}:
        return vals
    key = normalize_col_key(col_name)
    if "scm" in key:
        return vals * 100.0
    if "sm" in key:
        return vals
    #Processed TE CSVs use S/m; if explicit S/cm wasn't flagged, default to S/m unless user specifies --sigma-unit S/cm
    return vals


def infer_pf_uw_cm_k2(series: pd.Series, col_name: str, explicit_unit: str = "auto") -> pd.Series:
    vals = pd.to_numeric(series, errors="coerce").astype(float)
    u = explicit_unit.strip().lower().replace(" ", "").replace("µ", "u").replace("μ", "u")
    if u in {"wm-1k-2", "wm^-1k^-2", "w/m/k2", "w/mk2"}:
        return vals * 1e4
    if u in {"uwcm-1k-2", "uwcm^-1k^-2", "uw/cm/k2"}:
        return vals
    key = normalize_col_key(col_name)
    if "wm" in key and "uw" not in key:
        return vals * 1e4
    finite = vals.dropna().abs()
    if not finite.empty and float(finite.max()) < 0.05:
        return vals * 1e4
    return vals


def compute_jacobian_diagnostics(
    jac: np.ndarray,
    residuals: np.ndarray,
    param_names: Sequence[str],
    param_values: Sequence[float],
    *,
    is_log_param: Sequence[bool] | None = None,
) -> dict[str, Any]:
    """Extract parameter standard errors, 95% CIs, condition number, and correlation matrix
    from nonlinear least-squares Jacobian J (shape: n_obs x n_params).

    If `is_log_param[i]` is True, `jac[:, i]` is wrt `ln(theta_i)`, so relative SE of `theta_i`
    is `SE(ln theta_i)` and physical `SE(theta_i) = theta_i * SE(ln theta_i)`.
    """
    n_obs, n_par = jac.shape
    dof = max(n_obs - n_par, 1)
    rss = float(np.sum(np.asarray(residuals, dtype=float) ** 2))
    s2 = rss / dof

    u_mat, s_vals, vt_mat = np.linalg.svd(jac, full_matrices=False)
    s_max = float(s_vals[0]) if s_vals.size else 0.0
    s_min = float(s_vals[-1]) if s_vals.size else 0.0
    cond_num = float(s_max / s_min) if s_min > 1e-15 else float("inf")

    # Truncated pseudo-inverse for covariance stability
    cutoff = max(s_max * 1e-12, 1e-15)
    inv_s2 = np.where(s_vals > cutoff, 1.0 / np.maximum(s_vals**2, 1e-30), 0.0)
    cov_internal = (vt_mat.T * inv_s2[None, :]) @ vt_mat * s2

    diag = np.maximum(np.diag(cov_internal), 0.0)
    se_internal = np.sqrt(diag)
    denom = np.outer(se_internal, se_internal)
    corr = np.where(denom > 0.0, cov_internal / np.maximum(denom, 1e-30), np.eye(n_par))

    t_crit = float(student_t.ppf(0.975, dof)) if n_obs > n_par else 1.96
    log_flags = list(is_log_param) if is_log_param is not None else [False] * n_par

    uncertainties: dict[str, dict[str, float]] = {}
    for idx, (name, val, se_int, is_log) in enumerate(zip(param_names, param_values, se_internal, log_flags)):
        val_f = float(val)
        se_phys = abs(val_f) * float(se_int) if is_log else float(se_int)
        rel_pct = (100.0 * se_phys / abs(val_f)) if abs(val_f) > 1e-30 else float("nan")
        uncertainties[str(name)] = {
            "value": val_f,
            "std_error": se_phys,
            "ci95_halfwidth": t_crit * se_phys,
            "relative_se_pct": rel_pct,
        }

    warnings: list[str] = []
    high_corr_pairs: list[dict[str, Any]] = []
    for i in range(n_par):
        for j in range(i + 1, n_par):
            r_ij = float(corr[i, j])
            if abs(r_ij) >= 0.90:
                high_corr_pairs.append(
                    {"param_a": str(param_names[i]), "param_b": str(param_names[j]), "r": round(r_ij, 4)}
                )
                warnings.append(
                    f"Strong parameter collinearity between {param_names[i]} and {param_names[j]} "
                    f"(r = {r_ij:+.3f}); consider fixing one from independent Hall/optical/DFT data."
                )
    if n_obs <= n_par:
        warnings.append(
            f"Number of observations ({n_obs}) <= fitted parameters ({n_par}); solution is underdetermined."
        )
    elif cond_num > 500.0:
        warnings.append(
            f"High Jacobian condition number ({cond_num:.1f}); check parameter uncertainties and correlations."
        )

    corr_dict = {
        str(param_names[i]): {str(param_names[j]): round(float(corr[i, j]), 4) for j in range(n_par)}
        for i in range(n_par)
    }

    return {
        "n_observations": int(n_obs),
        "n_free_parameters": int(n_par),
        "degrees_of_freedom": int(max(n_obs - n_par, 0)),
        "condition_number": cond_num if np.isfinite(cond_num) else 1e16,
        "parameter_uncertainties": uncertainties,
        "correlation_matrix": corr_dict,
        "collinear_pairs": high_corr_pairs,
        "identifiability_warnings": warnings,
    }


def save_json_clean(data: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return path


def copy_figures_beside_input(figure_paths: Sequence[str | os.PathLike[str]], input_path: str | os.PathLike[str]) -> list[str]:
    target_dir = Path(input_path).expanduser().resolve().parent / "figures"
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for fpath in figure_paths:
        src = Path(fpath).resolve()
        dst = (target_dir / src.name).resolve()
        if src != dst:
            shutil.copy2(src, dst)
        copied.append(str(dst))
    return copied


def export_model_figure(
    fig: plt.Figure,
    stem: str,
    *,
    output_dir: Path,
    formats: Sequence[str],
    show: bool = False,
) -> list[str]:
    paths = save_figure_outputs(fig, f"{stem}.svg", save_dir=str(output_dir), formats=tuple(formats))
    if show:
        plt.show()
    plt.close(fig)
    return paths


__all__ = [
    "CP_CANDIDATES",
    "CONDUCTIVITY_CANDIDATES",
    "place_legend_inside",
    "DEFAULT_AXIS_LABEL_SIZE",
    "DEFAULT_LEGEND_FONT_SIZE",
    "DEFAULT_LINE_WIDTH",
    "DEFAULT_MARKER_SIZE",
    "DEFAULT_SUBPLOT_ASPECT",
    "DEFAULT_SUBPLOT_HEIGHT",
    "DEFAULT_TICK_LABEL_SIZE",
    "EXP_MARKER_EDGE",
    "EXP_MARKER_FACE",
    "FIT_RED_COLOR",
    "HALL_COEFF_CANDIDATES",
    "KAPPA_L_CANDIDATES",
    "KAPPA_TOT_CANDIDATES",
    "MOBILITY_CANDIDATES",
    "NH_CANDIDATES",
    "PF_CANDIDATES",
    "RESISTIVITY_CANDIDATES",
    "SEEBECK_CANDIDATES",
    "STAGE_NONRED_PALETTE",
    "TEMPERATURE_CANDIDATES",
    "ZT_CANDIDATES",
    "add_color_set_argument",
    "add_rename_argument",
    "apply_plot_style",
    "compute_jacobian_diagnostics",
    "copy_figures_beside_input",
    "export_model_figure",
    "figure_output_naming",
    "figure_size_for_subplot_aspect",
    "find_column",
    "format_te_axis",
    "get_colors",
    "infer_conductivity_s_m",
    "infer_pf_uw_cm_k2",
    "infer_seebeck_uv_k",
    "normalize_col_key",
    "normalize_output_formats",
    "read_tabular_data",
    "save_json_clean",
]

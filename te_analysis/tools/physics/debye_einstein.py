#!/usr/bin/env python3
"""Low-temperature heat capacity Cp(T) Debye-Einstein & Boson-peak fitting tool.

Models electronic Sommerfeld + acoustic Debye + N localized Einstein rattler oscillators:
    Cp(T) = gamma * T
          + 9 * w_D * N_at * R * (T / Theta_D)^3 * int_0^(Theta_D / T) x^4 e^x / (e^x - 1)^2 dx
          + sum_{k=1}^{N_E} 3 * w_{E,k} * N_at * R * (Theta_{E,k} / T)^2 e^(Theta_{E,k}/T) / (e^(Theta_{E,k}/T) - 1)^2

Generates a 2-panel publication figure:
  - Panel (a): Cp / T^3 vs T (log-scale) highlighting the Boson peak and individual Einstein rattler modes
  - Panel (b): Low-T Cp / T vs T^2 showing Sommerfeld gamma + Debye beta T^2 tangent vs Einstein curvature
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from numpy.polynomial.legendre import leggauss
from scipy.constants import R as GAS_R, hbar, k
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import ticker  # noqa: E402

from te_analysis.tools.physics.callaway import debye_heat_kernel  # noqa: E402
from te_analysis.tools.physics.io_plot import (  # noqa: E402
    CP_CANDIDATES,
    DEFAULT_LINE_WIDTH,
    DEFAULT_MARKER_SIZE,
    DEFAULT_TICK_LABEL_SIZE,
    EXP_MARKER_EDGE,
    EXP_MARKER_FACE,
    FIT_RED_COLOR,
    TEMPERATURE_CANDIDATES,
    add_color_set_argument,
    add_rename_argument,
    apply_plot_style,
    compute_jacobian_diagnostics,
    copy_figures_beside_input,
    export_model_figure,
    figure_output_naming,
    find_column,
    format_te_axis,
    get_colors,
    normalize_output_formats,
    place_legend_inside,
    read_tabular_data,
    save_json_clean,
)

_GL_NODES, _GL_WEIGHTS = leggauss(96)
_U01 = 0.5 * (_GL_NODES + 1.0)
_W01 = 0.5 * _GL_WEIGHTS


def debye_molar_cv(
    temperatures_k: np.ndarray,
    theta_d_k: float,
    atoms_per_fu: float,
    weight: float = 1.0,
) -> np.ndarray:
    """Debye molar heat capacity [J mol^-1 K^-1] for fraction `weight` of 3 * N_at modes."""
    t_arr = np.atleast_1d(np.asarray(temperatures_k, dtype=float))
    td = max(float(theta_d_k), 1.0)
    x_max = (td / np.maximum(t_arr, 1e-3))[:, None]
    x = x_max * _U01[None, :]
    integ = np.sum(debye_heat_kernel(x) * _W01[None, :], axis=1) * x_max[:, 0]
    return 9.0 * float(weight) * float(atoms_per_fu) * GAS_R * ((t_arr / td) ** 3) * integ


def einstein_molar_cv(
    temperatures_k: np.ndarray,
    theta_e_k: float,
    atoms_per_fu: float,
    weight: float,
) -> np.ndarray:
    """Single Einstein mode molar heat capacity [J mol^-1 K^-1] for oscillator fraction `weight`."""
    t_arr = np.atleast_1d(np.asarray(temperatures_k, dtype=float))
    te = max(float(theta_e_k), 0.5)
    z = te / np.maximum(t_arr, 1e-3)
    # Overflow-free z^2 e^z / (e^z - 1)^2 = (z * exp(-0.5 z) / (1 - exp(-z)))^2
    small = z < 1e-4
    safe_z = np.where(small, 1.0, z)
    half = safe_z * np.exp(-0.5 * safe_z) / (-np.expm1(-safe_z))
    ein_kernel = np.where(small, 1.0 - (z * z) / 12.0, half * half)
    return 3.0 * float(weight) * float(atoms_per_fu) * GAS_R * ein_kernel


def evaluate_debye_einstein_components(
    temperatures_k: np.ndarray,
    *,
    atoms_per_fu: float,
    gamma_mj_mol_k2: float,
    theta_d_k: float,
    w_debye: float,
    einstein_modes: Sequence[tuple[float, float]],  # [(theta_E_k, w_E_k), ...]
) -> dict[str, np.ndarray]:
    t_arr = np.atleast_1d(np.asarray(temperatures_k, dtype=float))
    c_el = (float(gamma_mj_mol_k2) * 1e-3) * t_arr
    c_deb = debye_molar_cv(t_arr, theta_d_k, atoms_per_fu, weight=w_debye)
    c_ein_list = [
        einstein_molar_cv(t_arr, theta_e, atoms_per_fu, weight=w_e) for theta_e, w_e in einstein_modes
    ]
    c_tot = c_el + c_deb + (np.sum(c_ein_list, axis=0) if c_ein_list else 0.0)
    return {
        "electronic": c_el,
        "debye": c_deb,
        "einstein_list": c_ein_list,
        "total": c_tot,
    }


def fit_debye_einstein_model(
    temperatures_k: np.ndarray,
    cp_j_mol_k: np.ndarray,
    *,
    atoms_per_fu: float = 4.0,
    n_einstein: int = 2,
    fix_gamma_mj: float | None = None,
    fix_theta_d: float | None = None,
    sum_rule: bool = True,
    volume_a3_per_fu: float | None = None,
) -> dict[str, Any]:
    """Fit Cp(T) in Cp/T^3 + Cp/T balanced space so both the Boson peak and high-T tail converge cleanly."""
    t_arr = np.asarray(temperatures_k, dtype=float)
    y_arr = np.asarray(cp_j_mol_k, dtype=float)

    # Initial low-T estimate from lowest 4..8 points
    low_mask = t_arr <= max(min(10.0, float(np.percentile(t_arr, 30))), float(t_arr.min()) + 3.5)
    if np.sum(low_mask) >= 3:
        slope_b, inter_g = np.polyfit(t_arr[low_mask] ** 2, y_arr[low_mask] / t_arr[low_mask], 1)
        gamma_init = max(float(inter_g) * 1e3, 0.0)
        beta_pos = max(float(slope_b), 1e-6)
        td_init = float(((12.0 * (math.pi**4) * atoms_per_fu * GAS_R) / (5.0 * beta_pos)) ** (1.0 / 3.0))
        td_init = float(np.clip(td_init, 60.0, 650.0))
    else:
        gamma_init = 0.5
        td_init = 220.0

    param_names: list[str] = []
    x0: list[float] = []
    lb: list[float] = []
    ub: list[float] = []
    is_log: list[bool] = []

    if fix_gamma_mj is None:
        param_names.append("gamma_mJ_molK2")
        x0.append(float(np.clip(gamma_init, 0.0, 50.0)))
        lb.append(0.0)
        ub.append(200.0)
        is_log.append(False)

    if fix_theta_d is None:
        param_names.append("Theta_D_K")
        x0.append(math.log(td_init))
        lb.append(math.log(40.0))
        ub.append(math.log(1200.0))
        is_log.append(True)

    if not sum_rule:
        param_names.append("w_Debye")
        x0.append(0.85)
        lb.append(0.05)
        ub.append(1.5)
        is_log.append(False)

    # Stagger initial Einstein temperatures across [25 K, 0.65 * Theta_D]
    te_guesses = np.linspace(32.0, max(65.0, 0.58 * (fix_theta_d or td_init)), max(n_einstein, 1))
    for k_idx in range(n_einstein):
        param_names.append(f"Theta_E{k_idx + 1}_K")
        x0.append(math.log(float(te_guesses[k_idx])))
        lb.append(math.log(8.0))
        ub.append(math.log(800.0))
        is_log.append(True)

        param_names.append(f"w_E{k_idx + 1}")
        x0.append(0.06 / max(n_einstein, 1))
        lb.append(0.0)
        ub.append(0.85)
        is_log.append(False)

    def unpack(vec: np.ndarray) -> tuple[float, float, float, list[tuple[float, float]]]:
        pos = 0
        if fix_gamma_mj is None:
            gam = float(vec[pos])
            pos += 1
        else:
            gam = float(fix_gamma_mj)

        if fix_theta_d is None:
            td = float(math.exp(float(vec[pos])))
            pos += 1
        else:
            td = float(fix_theta_d)

        if not sum_rule:
            w_d_raw = float(vec[pos])
            pos += 1
        else:
            w_d_raw = -1.0

        ein: list[tuple[float, float]] = []
        w_sum = 0.0
        for _ in range(n_einstein):
            te_k = float(math.exp(float(vec[pos])))
            w_k = float(vec[pos + 1])
            pos += 2
            ein.append((te_k, w_k))
            w_sum += w_k

        w_d = max(1.0 - w_sum, 0.02) if sum_rule else w_d_raw
        return gam, td, w_d, ein

    # Weight residuals by 1 / Cp_exp (relative error) so low-T Boson peak (Cp ~ 0.05 J/mol/K)
    # and higher-T Dulong-Petit regime (Cp ~ 80 J/mol/K) have equal leverage!
    rel_scale = 1.0 / np.maximum(y_arr, 1e-4)

    def resid(vec: np.ndarray) -> np.ndarray:
        gam, td, w_d, ein = unpack(vec)
        comps = evaluate_debye_einstein_components(
            t_arr,
            atoms_per_fu=atoms_per_fu,
            gamma_mj_mol_k2=gam,
            theta_d_k=td,
            w_debye=w_d,
            einstein_modes=ein,
        )
        penalties = []
        if sum_rule and sum(w for _, w in ein) > 0.96:
            penalties.append(20.0 * (sum(w for _, w in ein) - 0.96))
        base_r = (comps["total"] - y_arr) * rel_scale
        return np.concatenate([base_r, penalties]) if penalties else base_r

    opt = least_squares(resid, x0=np.asarray(x0), bounds=(lb, ub), method="trf", ftol=1e-11, xtol=1e-11, max_nfev=6000)
    gam_fit, td_fit, wd_fit, ein_raw = unpack(opt.x)
    # Sort Einstein modes by ascending Theta_E for clean reporting & plotting
    ein_sorted = sorted(ein_raw, key=lambda pair: pair[0])

    comps_pts = evaluate_debye_einstein_components(
        t_arr,
        atoms_per_fu=atoms_per_fu,
        gamma_mj_mol_k2=gam_fit,
        theta_d_k=td_fit,
        w_debye=wd_fit,
        einstein_modes=ein_sorted,
    )
    y_pred = comps_pts["total"]
    raw_res = y_pred - y_arr
    cp_t3_exp = y_arr / (t_arr**3)
    cp_t3_pred = y_pred / (t_arr**3)
    r2_cp = 1.0 - float(np.sum(raw_res**2)) / max(float(np.sum((y_arr - np.mean(y_arr)) ** 2)), 1e-30)
    r2_boson = 1.0 - float(np.sum((cp_t3_pred - cp_t3_exp) ** 2)) / max(
        float(np.sum((cp_t3_exp - np.mean(cp_t3_exp)) ** 2)), 1e-30
    )

    phys_vals = [
        math.exp(float(v)) if lg else float(v)
        for v, lg in zip(opt.x, is_log)
    ]
    jac_data = opt.jac[: len(t_arr), :]
    fun_data = opt.fun[: len(t_arr)]
    diag = compute_jacobian_diagnostics(jac_data, fun_data, param_names, phys_vals, is_log_param=is_log) if param_names else {}

    beta_debye_mj_mol_k4 = (12.0 * (math.pi**4) * wd_fit * atoms_per_fu * GAS_R / (5.0 * (td_fit**3))) * 1e3
    vs_m_s = None
    if volume_a3_per_fu is not None and volume_a3_per_fu > 0:
        n_a = atoms_per_fu / (float(volume_a3_per_fu) * 1e-30)
        vs_m_s = float((k * td_fit) / (hbar * ((6.0 * (math.pi**2) * n_a) ** (1.0 / 3.0))))

    return {
        "converged": bool(opt.success),
        "atoms_per_formula_unit": float(atoms_per_fu),
        "gamma_mJ_molK2": gam_fit,
        "Theta_D_K": td_fit,
        "w_Debye": wd_fit,
        "beta_Debye_mJ_molK4": float(beta_debye_mj_mol_k4),
        "derived_sound_velocity_m_s": vs_m_s,
        "einstein_modes": [
            {
                "mode": idx + 1,
                "Theta_E_K": float(te),
                "frequency_meV": float(te * k / 1.602176634e-22),
                "frequency_cm-1": float(te * 0.6950348),
                "weight_fraction": float(we),
                "oscillators_per_3Nat": float(we * 3.0 * atoms_per_fu),
            }
            for idx, (te, we) in enumerate(ein_sorted)
        ],
        "r2_Cp": float(r2_cp),
        "r2_Cp_over_T3": float(r2_boson),
        "mean_rel_error_pct": float(100.0 * np.mean(np.abs(raw_res) / np.maximum(y_arr, 1e-6))),
        "diagnostics": diag,
        "_ein_tuples": ein_sorted,
    }


def render_debye_einstein_figure(
    points_df: pd.DataFrame,
    curve_df: pd.DataFrame,
    fit_res: dict[str, Any],
    *,
    output_dir: Path,
    stem_prefix: str,
    formats: Sequence[str],
    color_set: str | None = None,
    show: bool = False,
) -> list[str]:
    apply_plot_style(mode="single")
    n_ein = len(fit_res["einstein_modes"])
    palette = get_colors(color_set, max(n_ein + 4, 6))

    fig, (ax_bp, ax_lt) = plt.subplots(1, 2, figsize=(11.4, 4.95))

    # --- Panel (a): Boson peak Cp / T^3 vs T (log scale) ---
    t_exp = points_df["Temperature_K"].to_numpy(dtype=float)
    bp_exp = points_df["Cp_over_T3_mJ_molK4"].to_numpy(dtype=float)
    t_grid = curve_df["Temperature_K"].to_numpy(dtype=float)

    ax_bp.scatter(
        t_exp,
        bp_exp,
        s=(DEFAULT_MARKER_SIZE * 0.88) ** 2,
        facecolor=EXP_MARKER_FACE,
        edgecolor=EXP_MARKER_EDGE,
        linewidths=1.0,
        alpha=0.90,
        label="Experimental",
        zorder=3.8,
    )
    ax_bp.plot(
        t_grid,
        curve_df["Cp_over_T3_total_mJ_molK4"].to_numpy(dtype=float),
        color=FIT_RED_COLOR,
        linewidth=DEFAULT_LINE_WIDTH * 1.2,
        label="Total Debye–Einstein Fit",
        zorder=5,
    )
    ax_bp.plot(
        t_grid,
        curve_df["Cp_over_T3_el_plus_debye_mJ_molK4"].to_numpy(dtype=float),
        color="#3C5488",
        linestyle="--",
        linewidth=1.45,
        label=rf"$\gamma T$ + Debye ($\Theta_{{\mathrm{{D}}}}={fit_res['Theta_D_K']:.0f}$ K)",
        zorder=3,
    )

    ein_colors = ["#00A087", "#7E6148", "#8491B4"]
    for idx, emode in enumerate(fit_res["einstein_modes"]):
        col_e = ein_colors[idx % len(ein_colors)]
        y_ein = curve_df[f"Cp_over_T3_E{idx + 1}_mJ_molK4"].to_numpy(dtype=float)
        ax_bp.plot(
            t_grid,
            y_ein,
            color=col_e,
            linestyle="-.",
            linewidth=1.35,
            label=rf"Einstein {idx + 1} ($\Theta_{{\mathrm{{E}}{idx + 1}}}={emode['Theta_E_K']:.1f}$ K)",
            zorder=3.2,
        )
        ax_bp.fill_between(t_grid, 0.0, y_ein, color=col_e, alpha=0.15, zorder=1.8)

    bp_max = max(float(bp_exp.max()), float(curve_df["Cp_over_T3_total_mJ_molK4"].max()))
    ax_bp.set_xscale("log")
    ax_bp.set_xlim(float(t_grid.min()), float(t_grid.max()))
    ax_bp.set_ylim(0.0, bp_max * 1.36)
    ax_bp.set_xlabel(r"$T$ (K)")
    ax_bp.set_ylabel(r"$C_p / T^3$ (mJ mol$^{-1}$ K$^{-4}$)")
    format_te_axis(ax_bp, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
    ax_bp.xaxis.set_major_formatter(ticker.ScalarFormatter())
    place_legend_inside(
        ax_bp,
        loc="upper right",
        fontsize=10.2,
        frameon=True,
        facecolor="white",
        edgecolor="black",
        fancybox=False,
        ylim_locked=(True, False),
    )

    # --- Panel (b): Low-T Cp / T vs T^2 ---
    t_cut = min(float(t_exp.max()), max(14.0, float(t_exp.min()) + 10.0))
    mask_exp_lt = t_exp <= t_cut
    mask_grd_lt = t_grid <= t_cut
    if np.sum(mask_exp_lt) < 4:
        mask_exp_lt = np.ones_like(t_exp, dtype=bool)
        mask_grd_lt = np.ones_like(t_grid, dtype=bool)

    t2_exp = t_exp[mask_exp_lt] ** 2
    cpt_exp = points_df["Cp_over_T_mJ_molK2"].to_numpy(dtype=float)[mask_exp_lt]
    t2_grd = t_grid[mask_grd_lt] ** 2
    cpt_tot = curve_df["Cp_over_T_total_mJ_molK2"].to_numpy(dtype=float)[mask_grd_lt]
    cpt_lin = fit_res["gamma_mJ_molK2"] + fit_res["beta_Debye_mJ_molK4"] * t2_grd

    ax_lt.scatter(
        t2_exp,
        cpt_exp,
        s=(DEFAULT_MARKER_SIZE * 0.9) ** 2,
        facecolor=EXP_MARKER_FACE,
        edgecolor=EXP_MARKER_EDGE,
        linewidths=1.0,
        alpha=0.90,
        label="Experimental",
        zorder=3.8,
    )
    ax_lt.plot(t2_grd, cpt_tot, color=FIT_RED_COLOR, linewidth=DEFAULT_LINE_WIDTH * 1.2, label="Total Fit", zorder=5)
    ax_lt.plot(
        t2_grd,
        cpt_lin,
        color="#3C5488",
        linestyle="--",
        linewidth=1.4,
        label=r"$\gamma + \beta_{\mathrm{D}} T^2$ baseline",
        zorder=3,
    )

    cpt_max = max(float(cpt_exp.max()), float(cpt_tot.max()))
    ax_lt.set_xlim(0.0, float(t2_grd.max()) * 1.04)
    ax_lt.set_ylim(0.0, cpt_max * 1.28)
    ax_lt.set_xlabel(r"$T^2$ (K$^2$)")
    ax_lt.set_ylabel(r"$C_p / T$ (mJ mol$^{-1}$ K$^{-2}$)")
    format_te_axis(ax_lt, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)

    stat_lines = [
        rf"$\gamma = {fit_res['gamma_mJ_molK2']:.2f}$ mJ mol$^{{-1}}$ K$^{{-2}}$",
        rf"$\beta_{{\mathrm{{D}}}} = {fit_res['beta_Debye_mJ_molK4']:.3f}$ mJ mol$^{{-1}}$ K$^{{-4}}$",
        rf"$R^2(C_p/T^3) = {fit_res['r2_Cp_over_T3']:.4f}$",
    ]
    if fit_res["derived_sound_velocity_m_s"] is not None:
        stat_lines.insert(2, rf"$v_{{\mathrm{{s}}}} = {fit_res['derived_sound_velocity_m_s']:.0f}$ m s$^{{-1}}$")

    ax_lt.text(
        0.04,
        0.95,
        "\n".join(stat_lines),
        transform=ax_lt.transAxes,
        ha="left",
        va="top",
        fontsize=10.6,
        bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.92, "pad": 3.8},
        zorder=6,
    )
    place_legend_inside(
        ax_lt,
        loc="lower right",
        fontsize=10.5,
        frameon=True,
        facecolor="white",
        edgecolor="black",
        fancybox=False,
        ylim_locked=(True, False),
    )

    fig.tight_layout()
    return export_model_figure(
        fig,
        f"{stem_prefix}_debye_einstein_fit",
        output_dir=output_dir,
        formats=formats,
        show=show,
    )


def run_debye_einstein_workflow(
    input_csv: str | os.PathLike[str],
    *,
    output_dir: str | os.PathLike[str] | None = None,
    atoms_per_fu: float = 4.0,
    n_einstein: int = 2,
    cp_unit: str = "J/molK",
    molar_mass_g_mol: float | None = None,
    volume_a3_per_fu: float | None = None,
    fix_gamma_mj: float | None = None,
    fix_theta_d: float | None = None,
    sum_rule: bool = True,
    t_range: tuple[float | None, float | None] | None = None,
    temp_col: str | None = None,
    cp_col: str | None = None,
    formats: Sequence[str] = ("svg",),
    color_set: str | None = None,
    rename: str | None = None,
    copy_to_data_dir: bool = True,
    show: bool = False,
) -> dict[str, Any]:
    df = read_tabular_data(input_csv)
    t_c = find_column(df, temp_col, TEMPERATURE_CANDIDATES, required=True)
    c_c = find_column(df, cp_col, CP_CANDIDATES, required=True)

    pts = df.copy()
    pts["Temperature_K"] = pd.to_numeric(pts[t_c], errors="coerce").astype(float)
    raw_cp = pd.to_numeric(pts[c_c], errors="coerce").astype(float)

    u_clean = cp_unit.strip().lower().replace(" ", "").replace("-", "").replace("^", "")
    if u_clean in {"mj/molk", "mjmol1k1", "mjmolk"}:
        pts["Cp_J_mol-1_K-1"] = raw_cp * 1e-3
    elif u_clean in {"j/gk", "jg1k1", "jgk"}:
        if not molar_mass_g_mol or molar_mass_g_mol <= 0:
            raise ValueError("--cp-unit J/gK requires positive --molar-mass (g/mol)")
        pts["Cp_J_mol-1_K-1"] = raw_cp * float(molar_mass_g_mol)
    else:
        pts["Cp_J_mol-1_K-1"] = raw_cp

    pts = pts.replace([np.inf, -np.inf], np.nan).dropna(subset=["Temperature_K", "Cp_J_mol-1_K-1"])
    pts = pts[(pts["Temperature_K"] > 0.3) & (pts["Cp_J_mol-1_K-1"] > 0)].sort_values("Temperature_K")
    if t_range is not None:
        if t_range[0] is not None:
            pts = pts[pts["Temperature_K"] >= float(t_range[0])]
        if t_range[1] is not None:
            pts = pts[pts["Temperature_K"] <= float(t_range[1])]
    pts = pts.reset_index(drop=True)
    if len(pts) < 5:
        raise ValueError(f"Need at least 5 positive Cp(T) points for Debye-Einstein fitting, got {len(pts)}")

    t_exp = pts["Temperature_K"].to_numpy(dtype=float)
    cp_exp = pts["Cp_J_mol-1_K-1"].to_numpy(dtype=float)

    fit_res = fit_debye_einstein_model(
        t_exp,
        cp_exp,
        atoms_per_fu=atoms_per_fu,
        n_einstein=n_einstein,
        fix_gamma_mj=fix_gamma_mj,
        fix_theta_d=fix_theta_d,
        sum_rule=sum_rule,
        volume_a3_per_fu=volume_a3_per_fu,
    )
    ein_tuples = fit_res.pop("_ein_tuples")

    comps_exp = evaluate_debye_einstein_components(
        t_exp,
        atoms_per_fu=atoms_per_fu,
        gamma_mj_mol_k2=fit_res["gamma_mJ_molK2"],
        theta_d_k=fit_res["Theta_D_K"],
        w_debye=fit_res["w_Debye"],
        einstein_modes=ein_tuples,
    )
    pts["Cp_model_J_mol-1_K-1"] = comps_exp["total"]
    pts["Cp_over_T_mJ_molK2"] = (cp_exp / t_exp) * 1e3
    pts["Cp_over_T3_mJ_molK4"] = (cp_exp / (t_exp**3)) * 1e3

    t_grid = np.geomspace(max(1.5, float(t_exp.min()) * 0.9), float(t_exp.max()) * 1.05, 320)
    comps_grd = evaluate_debye_einstein_components(
        t_grid,
        atoms_per_fu=atoms_per_fu,
        gamma_mj_mol_k2=fit_res["gamma_mJ_molK2"],
        theta_d_k=fit_res["Theta_D_K"],
        w_debye=fit_res["w_Debye"],
        einstein_modes=ein_tuples,
    )
    curve_df = pd.DataFrame(
        {
            "Temperature_K": t_grid,
            "Cp_total_J_mol-1_K-1": comps_grd["total"],
            "Cp_electronic_J_mol-1_K-1": comps_grd["electronic"],
            "Cp_debye_J_mol-1_K-1": comps_grd["debye"],
            "Cp_over_T_total_mJ_molK2": (comps_grd["total"] / t_grid) * 1e3,
            "Cp_over_T3_total_mJ_molK4": (comps_grd["total"] / (t_grid**3)) * 1e3,
            "Cp_over_T3_el_plus_debye_mJ_molK4": ((comps_grd["electronic"] + comps_grd["debye"]) / (t_grid**3)) * 1e3,
        }
    )
    for idx, c_ein in enumerate(comps_grd["einstein_list"]):
        curve_df[f"Cp_E{idx + 1}_J_mol-1_K-1"] = c_ein
        curve_df[f"Cp_over_T3_E{idx + 1}_mJ_molK4"] = (c_ein / (t_grid**3)) * 1e3

    from te_analysis.paths import get_workspace

    out_path = Path(output_dir) if output_dir is not None else get_workspace().model_output_dir("debye_einstein")
    out_path.mkdir(parents=True, exist_ok=True)
    stem = Path(input_csv).stem
    pts_csv = out_path / f"{stem}_debye_einstein_points.csv"
    crv_csv = out_path / f"{stem}_debye_einstein_curve.csv"
    pts.to_csv(pts_csv, index=False)
    curve_df.to_csv(crv_csv, index=False)

    with figure_output_naming(rename):
        fig_paths = render_debye_einstein_figure(
            pts,
            curve_df,
            fit_res,
            output_dir=out_path,
            stem_prefix=stem,
            formats=formats,
            color_set=color_set,
            show=show,
        )

    copied = copy_figures_beside_input(fig_paths, input_csv) if copy_to_data_dir else []
    summary = {
        "model": "Debye-Einstein",
        "input_csv": str(Path(input_csv).resolve()),
        "fit": fit_res,
        "outputs": {
            "points_csv": str(pts_csv),
            "curve_csv": str(crv_csv),
            "figures": fig_paths,
            "data_dir_figures": copied,
        },
    }
    sum_json = save_json_clean(summary, out_path / f"{stem}_debye_einstein_summary.json")
    summary["outputs"]["summary_json"] = str(sum_json)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Fit low-temperature Cp(T) with Sommerfeld + Debye + multi-Einstein rattler models."
    )
    from te_analysis.paths import get_workspace

    p.add_argument("input_csv", help="CSV/TSV/XLSX containing Temperature (K) and Heat Capacity Cp.")
    p.add_argument("-o", "--output-dir", default=str(get_workspace().model_output_dir("debye_einstein")), help="Output directory.")
    p.add_argument("--atoms-per-fu", type=float, default=4.0, help="Atoms per formula unit N_at (default: 4, e.g. CuInTe2).")
    p.add_argument("--n-einstein", type=int, default=2, choices=(0, 1, 2, 3), help="Number of Einstein rattler modes (default: 2).")
    p.add_argument("--cp-unit", default="J/molK", choices=("J/molK", "mJ/molK", "J/gK"), help="Input Cp unit (default: J/molK).")
    p.add_argument("--molar-mass", type=float, default=None, help="Molar mass (g/mol), required if --cp-unit J/gK.")
    p.add_argument("--volume-a3-per-fu", type=float, default=None, help="Formula-unit volume (Angstrom^3) to derive sound velocity v_s.")
    p.add_argument("--fix-gamma", type=float, default=None, help="Fix electronic Sommerfeld gamma (mJ mol^-1 K^-2), e.g. 0 for insulators.")
    p.add_argument("--fix-theta-d", type=float, default=None, help="Fix Debye temperature Theta_D (K).")
    p.add_argument("--free-weights", action="store_true", help="Allow oscillator weights to vary freely without w_D + sum(w_E) = 1.")
    p.add_argument("--t-range", nargs=2, type=float, default=None, metavar=("TMIN", "TMAX"), help="Temperature fitting window (K).")
    p.add_argument("--temp-col", default=None, help="Explicit temperature column name.")
    p.add_argument("--cp-col", default=None, help="Explicit heat capacity column name.")
    p.add_argument("--formats", nargs="+", default=["svg"], help="Figure export formats.")
    p.add_argument("--pdf", action="store_true", help="Also export vector PDF.")
    p.add_argument("--no-copy-to-data-dir", action="store_true", help="Do not copy figures beside input CSV.")
    p.add_argument("--no-show", action="store_true", help="Save figures without GUI window.")
    add_color_set_argument(p)
    add_rename_argument(p)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    formats = normalize_output_formats(args.formats, pdf=args.pdf)
    summary = run_debye_einstein_workflow(
        args.input_csv,
        output_dir=args.output_dir,
        atoms_per_fu=args.atoms_per_fu,
        n_einstein=args.n_einstein,
        cp_unit=args.cp_unit,
        molar_mass_g_mol=args.molar_mass,
        volume_a3_per_fu=args.volume_a3_per_fu,
        fix_gamma_mj=args.fix_gamma,
        fix_theta_d=args.fix_theta_d,
        sum_rule=not args.free_weights,
        t_range=tuple(args.t_range) if args.t_range else None,
        temp_col=args.temp_col,
        cp_col=args.cp_col,
        formats=formats,
        color_set=args.color_set,
        rename=args.rename,
        copy_to_data_dir=not args.no_copy_to_data_dir,
        show=not args.no_show,
    )
    fit = summary["fit"]
    ein_str = ", ".join(f"Theta_E{m['mode']}={m['Theta_E_K']:.1f}K (w={m['weight_fraction']:.3f})" for m in fit["einstein_modes"])
    print(f"Debye-Einstein fit -> Theta_D={fit['Theta_D_K']:.1f}K, gamma={fit['gamma_mJ_molK2']:.2f} mJ/molK^2, {ein_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

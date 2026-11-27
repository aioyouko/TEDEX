#!/usr/bin/env python3
"""Two-Band Thermoelectric Transport Fitting & Semimetal Decomposition Engine.

Covers all four physical regimes of two-band Boltzmann thermoelectric transport:
1. `convergence` (isothermal same-sign light + heavy bands vs n_H, e.g. L+Sigma or Gamma_4+Gamma_5):
   fits (m*_1, m*_2, Delta E, b = mu_{0,1}/mu_{0,2}, mu_{0,1}) with automatic DOF locking.
2. `bipolar` (variable-T opposite-sign e+h global charge-neutrality fit):
   solves exact 1D charge neutrality n_maj(eta, T) - n_min(-eta - E_g(T)/k_BT, T) = N_dop across either
   a positive semiconductor bandgap (E_g > 0) or a negative semimetal band overlap (E_g <= 0 via
   `--allow-semimetal`), supporting Matthiessen defect+acoustic mobility (`--matthiessen`), general
   power-law scattering exponent `r` (`--scattering-r`), optional joint n_H(T) constraint (`--fit-nh`),
   and kappa_tot(T) = kappa_L(T) + kappa_e(T) + kappa_bi(T) separation.
3. `semimetal` / `hall-inversion` (point-by-point opposite-sign e+h transport decomposition vs T,
   cf. Mao et al., Science 2019, Eqs. S11-S17):
   given experimental (T, S, sigma/rho, n_H/R_H) and DFT/known DOS effective masses (--fix-m1, --fix-m2),
   solves exact Fermi-Dirac & parallel conduction equations at each temperature without parametric
   mu(T) assumptions, extracting E_g(T), partial S_{e,h}(T), partial mu_{e,h}(T), weighted mobility
   ratio A(T), kappa_{e,bi}(T), and Hall self-consistency R_{H,calc}/R_{H,exp}.
4. `isothermal-bipolar` (isothermal opposite-sign e+h Pisarenko & weighted-mobility-ratio A map vs n_H,
   cf. Mao et al., Science 2019, Eqs. S1-S10 & Figs. S10-S12):
   fits isothermal narrow-gap / semimetal S(n_H) + PF(n_H) and renders the 2D S(A_0, n) contour map.

All nonlinear least-squares modes export full SVD Jacobian collinearity diagnostics (condition number,
95% confidence intervals, and parameter correlation matrices with |r_ij| >= 0.90 warnings).
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from scipy.constants import e, h, k, m_e
from scipy.optimize import differential_evolution, least_squares

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import ticker  # noqa: E402

from te_analysis.tools.colors import resolve_cmap  # noqa: E402
from te_analysis.tools.physics.fermi import (  # noqa: E402
    fermi_integral_vec,
    parabolic_band_state_general_r,
    single_band_state,
    solve_eta_from_carrier_density_parabolic,
    solve_eta_from_seebeck_skb,
)
from te_analysis.tools.physics.io_plot import (  # noqa: E402
    CONDUCTIVITY_CANDIDATES,
    DEFAULT_LINE_WIDTH,
    DEFAULT_MARKER_SIZE,
    DEFAULT_TICK_LABEL_SIZE,
    EXP_MARKER_EDGE,
    EXP_MARKER_FACE,
    FIT_RED_COLOR,
    HALL_COEFF_CANDIDATES,
    KAPPA_TOT_CANDIDATES,
    MOBILITY_CANDIDATES,
    NH_CANDIDATES,
    PF_CANDIDATES,
    RESISTIVITY_CANDIDATES,
    SEEBECK_CANDIDATES,
    STAGE_NONRED_PALETTE,
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
    infer_conductivity_s_m,
    infer_pf_uw_cm_k2,
    infer_seebeck_uv_k,
    normalize_col_key,
    normalize_output_formats,
    place_legend_inside,
    read_tabular_data,
    save_json_clean,
)
from te_analysis.tools.physics.skb import point_mstar_from_eta_and_nh_skb  # noqa: E402


class MissingMaterialParametersError(ValueError):
    """Raised with exit-code 2 semantics when required physical constants are omitted."""


def _infer_resistivity_ohm_m(series: pd.Series, col_name: str, explicit_unit: str = "auto") -> pd.Series:
    vals = pd.to_numeric(series, errors="coerce").astype(float)
    raw = (explicit_unit if explicit_unit != "auto" else col_name).strip().lower().replace("µ", "u").replace("μ", "u")
    key = normalize_col_key(raw)
    if "uohmm" in key or "microohmm" in key:
        return vals * 1e-6
    if "mohmcm" in key:
        return vals * 1e-5
    if "uohmcm" in key or "microohmcm" in key:
        return vals * 1e-8
    if "ohmcm" in key:
        return vals * 1e-2
    return vals


def _infer_hall_coeff_m3_c(series: pd.Series, col_name: str) -> pd.Series:
    vals = pd.to_numeric(series, errors="coerce").astype(float)
    key = normalize_col_key(col_name.replace("µ", "u").replace("μ", "u"))
    if "1e7m3c" in key or "107m3c" in key:
        return vals * 1e-7
    if "1e6m3c" in key or "cm3c" in key:
        return vals * 1e-6
    return vals


def _extract_conductivity_s_m(df: pd.DataFrame, sigma_unit: str = "auto", *, required: bool = True) -> pd.Series | None:
    c_sig = find_column(df, None, CONDUCTIVITY_CANDIDATES, required=False)
    if c_sig is not None:
        return infer_conductivity_s_m(df[c_sig], c_sig, sigma_unit)
    c_rho = find_column(df, None, RESISTIVITY_CANDIDATES, required=False)
    if c_rho is not None:
        rho_ohm_m = _infer_resistivity_ohm_m(df[c_rho], c_rho)
        return 1.0 / rho_ohm_m.where(rho_ohm_m > 0.0, np.nan)
    if required:
        raise ValueError(
            f"Could not find electrical conductivity or resistivity column among "
            f"{list(CONDUCTIVITY_CANDIDATES) + list(RESISTIVITY_CANDIDATES)}. Available: {list(df.columns)}"
        )
    return None


def _extract_hall_nh_and_rh(
    df: pd.DataFrame,
    nh_unit: str = "cm^-3",
    *,
    fallback_sign: int = -1,
    required: bool = False,
) -> tuple[pd.Series | None, pd.Series | None]:
    """Extract apparent Hall concentration n_H [m^-3] and signed Hall coefficient R_H [m^3 C^-1]."""
    c_rh = find_column(df, None, HALL_COEFF_CANDIDATES, required=False)
    c_nh = find_column(df, None, NH_CANDIDATES, required=False)

    rh_m3_c: pd.Series | None = None
    nh_m3: pd.Series | None = None

    if c_rh is not None:
        rh_m3_c = _infer_hall_coeff_m3_c(df[c_rh], c_rh)
        nh_m3 = 1.0 / (e * rh_m3_c.abs().where(rh_m3_c.abs() > 0.0, np.nan))
    if c_nh is not None:
        nh_raw = pd.to_numeric(df[c_nh], errors="coerce").astype(float)
        nh_m3_col = nh_raw if nh_unit.strip().lower() in {"m^-3", "m-3"} else nh_raw * 1e6
        if nh_m3 is None:
            nh_m3 = nh_m3_col
        if rh_m3_c is None:
            sgn = 1.0 if fallback_sign >= 0 else -1.0
            rh_m3_c = sgn / (e * nh_m3_col.where(nh_m3_col > 0.0, np.nan))

    if required and nh_m3 is None:
        raise ValueError(
            f"Could not find Hall concentration or Hall coefficient column among "
            f"{list(NH_CANDIDATES) + list(HALL_COEFF_CANDIDATES)}. Available: {list(df.columns)}"
        )
    return nh_m3, rh_m3_c


def combine_two_bands(st1: dict[str, np.ndarray], st2: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Exact two-band parallel transport combination for arbitrary carrier signs."""
    sig1 = st1["Conductivity_S_m-1"]
    sig2 = st2["Conductivity_S_m-1"]
    sig_tot = np.maximum(sig1 + sig2, 1e-30)

    f1 = sig1 / sig_tot
    f2 = sig2 / sig_tot

    s1_vk = st1["Seebeck_V_K"]
    s2_vk = st2["Seebeck_V_K"]
    s_tot_vk = f1 * s1_vk + f2 * s2_vk

    rh1 = st1["Hall_Coefficient_m3_C-1"]
    rh2 = st2["Hall_Coefficient_m3_C-1"]
    rh_tot = (rh1 * (sig1**2) + rh2 * (sig2**2)) / (sig_tot**2)
    nh_app_m3 = 1.0 / (e * np.maximum(np.abs(rh_tot), 1e-35))
    mu_app_cm2_vs = np.abs(rh_tot) * sig_tot * 1e4

    temp = st1["Temperature_K"]
    ke1 = st1["Carrier_Thermal_Conductivity_W_m-1_K-1"]
    ke2 = st2["Carrier_Thermal_Conductivity_W_m-1_K-1"]
    k_bi = ((sig1 * sig2) / sig_tot) * ((s1_vk - s2_vk) ** 2) * temp
    pf_si = (s_tot_vk**2) * sig_tot

    return {
        "Temperature_K": temp,
        "Conductivity_1_S_m-1": sig1,
        "Conductivity_2_S_m-1": sig2,
        "Conductivity_S_m-1": sig_tot,
        "Conductivity_S_cm-1": sig_tot * 0.01,
        "Band1_Conductivity_Fraction": f1,
        "Band2_Conductivity_Fraction": f2,
        "Seebeck_1_uV_K": st1["Seebeck_uV_K"],
        "Seebeck_2_uV_K": st2["Seebeck_uV_K"],
        "Seebeck_uV_K": s_tot_vk * 1e6,
        "Seebeck_abs_uV_K": np.abs(s_tot_vk) * 1e6,
        "Hall_Coefficient_m3_C-1": rh_tot,
        "nH_m-3": nh_app_m3,
        "nH_cm-3": nh_app_m3 * 1e-6,
        "Hall_Mobility_cm2_V-1_s-1": mu_app_cm2_vs,
        "Power_Factor_uW_cm-1_K-2": pf_si * 1e4,
        "Carrier_Thermal_Conductivity_W_m-1_K-1": ke1 + ke2,
        "Bipolar_Thermal_Conductivity_W_m-1_K-1": k_bi,
        "Total_Electronic_Thermal_Conductivity_W_m-1_K-1": ke1 + ke2 + k_bi,
    }


def _eval_parabolic_or_acoustic_band(
    eta: np.ndarray,
    *,
    temperature_k: float | np.ndarray,
    mstar_dos_ratio: float,
    mu0_cm2_vs: float,
    carrier_sign: int,
    scattering_r: float = -0.5,
    use_hall_factor: bool = True,
) -> dict[str, np.ndarray]:
    if math.isclose(float(scattering_r), -0.5, abs_tol=1e-12):
        return single_band_state(
            eta,
            temperature_k=temperature_k,
            mstar_dos_ratio=mstar_dos_ratio,
            mu0_cm2_vs=mu0_cm2_vs,
            alpha=0.0,
            carrier_sign=carrier_sign,
            use_hall_factor=use_hall_factor,
        )
    return parabolic_band_state_general_r(
        eta,
        temperature_k=temperature_k,
        mstar_dos_ratio=mstar_dos_ratio,
        mu0_cm2_vs=mu0_cm2_vs,
        scattering_r=scattering_r,
        carrier_sign=carrier_sign,
        use_hall_factor=use_hall_factor,
    )


# ===========================================================================
# MODE 1: Isothermal Two-Band Convergence (`convergence`: Light + Heavy Band)
# ===========================================================================
_ETA_SWEEP_GRID = np.linspace(-10.0, 26.0, 320)


def evaluate_convergence_grid(
    eta1_grid: np.ndarray,
    *,
    temperature_k: float,
    m1_dos: float,
    m2_dos: float,
    delta_e_ev: float,
    mu0_1_cm2_vs: float,
    b_mobility_ratio: float,
    band1_eg_ev: float | None = None,
    carrier_sign: int = 1,
) -> dict[str, np.ndarray]:
    """Evaluate two same-sign bands separated by Delta E [eV] across reduced Fermi level eta_1."""
    alpha1 = (k * temperature_k / (band1_eg_ev * e)) if (band1_eg_ev and band1_eg_ev > 0) else 0.0
    delta_eta = (float(delta_e_ev) * e) / (k * float(temperature_k))
    eta2_grid = eta1_grid - delta_eta
    mu0_2 = float(mu0_1_cm2_vs) / max(float(b_mobility_ratio), 1e-4)

    st1 = single_band_state(
        eta1_grid,
        temperature_k=temperature_k,
        mstar_dos_ratio=m1_dos,
        mu0_cm2_vs=mu0_1_cm2_vs,
        alpha=alpha1,
        carrier_sign=carrier_sign,
    )
    st2 = single_band_state(
        eta2_grid,
        temperature_k=temperature_k,
        mstar_dos_ratio=m2_dos,
        mu0_cm2_vs=mu0_2,
        alpha=0.0,
        carrier_sign=carrier_sign,
    )
    comb = combine_two_bands(st1, st2)
    comb["eta1"] = eta1_grid
    comb["eta2"] = eta2_grid
    return comb


def predict_convergence_at_nh(
    nh_target_m3: np.ndarray,
    *,
    temperature_k: float,
    m1_dos: float,
    m2_dos: float,
    delta_e_ev: float,
    mu0_1_cm2_vs: float,
    b_mobility_ratio: float,
    band1_eg_ev: float | None = None,
    carrier_sign: int = 1,
) -> dict[str, np.ndarray]:
    """Interpolate two-band observables at experimental Hall concentrations n_H."""
    grid = evaluate_convergence_grid(
        _ETA_SWEEP_GRID,
        temperature_k=temperature_k,
        m1_dos=m1_dos,
        m2_dos=m2_dos,
        delta_e_ev=delta_e_ev,
        mu0_1_cm2_vs=mu0_1_cm2_vs,
        b_mobility_ratio=b_mobility_ratio,
        band1_eg_ev=band1_eg_ev,
        carrier_sign=carrier_sign,
    )
    log_nh_grid = np.log(grid["nH_m-3"])
    order = np.argsort(log_nh_grid)
    x_sorted = log_nh_grid[order]
    log_target = np.log(np.asarray(nh_target_m3, dtype=float))
    eta1_interp = np.interp(log_target, x_sorted, _ETA_SWEEP_GRID[order])
    return evaluate_convergence_grid(
        eta1_interp,
        temperature_k=temperature_k,
        m1_dos=m1_dos,
        m2_dos=m2_dos,
        delta_e_ev=delta_e_ev,
        mu0_1_cm2_vs=mu0_1_cm2_vs,
        b_mobility_ratio=b_mobility_ratio,
        band1_eg_ev=band1_eg_ev,
        carrier_sign=carrier_sign,
    )


def fit_two_band_convergence(
    df_raw: pd.DataFrame,
    *,
    temperature_k: float = 300.0,
    band1_eg_ev: float | None = None,
    fix_m1: float | None = None,
    fix_m2: float | None = None,
    fix_delta_e: float | None = None,
    fix_mu1: float | None = None,
    fix_b: float | None = None,
    nh_unit: str = "cm^-3",
    sigma_unit: str = "auto",
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    c_s = find_column(df_raw, None, SEEBECK_CANDIDATES, required=True)
    c_mu = find_column(df_raw, None, MOBILITY_CANDIDATES, required=False)
    c_pf = find_column(df_raw, None, PF_CANDIDATES, required=False)

    pts = df_raw.copy()
    pts["Seebeck_uV_K"] = infer_seebeck_uv_k(pts[c_s])
    pts["Seebeck_abs_uV_K"] = pts["Seebeck_uV_K"].abs()
    carrier_sign = 1 if float(pts["Seebeck_uV_K"].median()) >= 0 else -1

    nh_m3_ser, _ = _extract_hall_nh_and_rh(pts, nh_unit=nh_unit, fallback_sign=carrier_sign, required=True)
    assert nh_m3_ser is not None
    pts["nH_m-3"] = nh_m3_ser
    pts["nH_cm-3"] = nh_m3_ser * 1e-6

    if c_mu is not None:
        pts["Hall_Mobility_exp_cm2_V-1_s-1"] = pd.to_numeric(pts[c_mu], errors="coerce").astype(float)
    sig_sm = _extract_conductivity_s_m(pts, sigma_unit=sigma_unit, required=False)
    if sig_sm is not None:
        pts["Conductivity_exp_S_m-1"] = sig_sm
        if "Hall_Mobility_exp_cm2_V-1_s-1" not in pts.columns:
            pts["Hall_Mobility_exp_cm2_V-1_s-1"] = (sig_sm / (pts["nH_m-3"] * e)) * 1e4
    if c_pf is not None:
        pf_uw = infer_pf_uw_cm_k2(pts[c_pf], c_pf)
        pts["Power_Factor_exp_uW_cm-1_K-2"] = pf_uw
        if "Hall_Mobility_exp_cm2_V-1_s-1" not in pts.columns:
            s_vk = pts["Seebeck_abs_uV_K"] * 1e-6
            sig_est = (pf_uw * 1e-4) / np.maximum(s_vk * s_vk, 1e-30)
            pts["Hall_Mobility_exp_cm2_V-1_s-1"] = (sig_est / (pts["nH_m-3"] * e)) * 1e4
    elif "Conductivity_exp_S_m-1" in pts.columns:
        pts["Power_Factor_exp_uW_cm-1_K-2"] = ((pts["Seebeck_abs_uV_K"] * 1e-6) ** 2) * pts["Conductivity_exp_S_m-1"] * 1e4

    pts = pts.replace([np.inf, -np.inf], np.nan).dropna(subset=["nH_m-3", "Seebeck_abs_uV_K"])
    pts = pts[(pts["nH_m-3"] > 0) & (pts["Seebeck_abs_uV_K"] > 0)].sort_values("nH_cm-3").reset_index(drop=True)
    if len(pts) < 4:
        raise ValueError(f"Two-band convergence fit needs >= 4 (nH, S) samples, got {len(pts)}")

    nh_m3 = pts["nH_m-3"].to_numpy(dtype=float)
    s_exp = pts["Seebeck_abs_uV_K"].to_numpy(dtype=float)
    has_mobility = "Hall_Mobility_exp_cm2_V-1_s-1" in pts.columns
    mu_exp = pts["Hall_Mobility_exp_cm2_V-1_s-1"].to_numpy(dtype=float) if has_mobility else None

    n_low = max(2, len(pts) // 4)
    alpha1 = (k * temperature_k / (band1_eg_ev * e)) if (band1_eg_ev and band1_eg_ev > 0) else 0.0
    m1_low_est = []
    for i in range(n_low):
        ei = solve_eta_from_seebeck_skb(float(s_exp[i]), alpha=alpha1)
        mi, _, _ = point_mstar_from_eta_and_nh_skb(ei, float(nh_m3[i]), temperature_k, alpha1)
        m1_low_est.append(mi)
    m1_init = float(np.clip(np.median(m1_low_est), 0.03, 5.0))
    mu1_init = float(np.clip(np.nanmax(mu_exp) * 1.35, 2.0, 2e4)) if (has_mobility and mu_exp is not None) else 100.0
    effective_fix_mu1 = fix_mu1 if fix_mu1 is not None else (None if has_mobility else 100.0)

    specs = [
        ("m1_dos_over_me", fix_m1, m1_init, 0.02, 8.0, True),
        ("m2_dos_over_me", fix_m2, max(m1_init * 3.2, 0.8), 0.15, 25.0, True),
        ("delta_E_eV", fix_delta_e, 0.12, 0.005, 0.55, False),
        ("b_mu1_over_mu2", fix_b, 5.0, 1.05, 80.0, True),
        ("mu0_1_cm2_Vs", effective_fix_mu1, mu1_init, 0.2, 1e5, True),
    ]

    free_names: list[str] = []
    x0: list[float] = []
    lb: list[float] = []
    ub: list[float] = []
    is_log: list[bool] = []
    for name, fixed_val, init_v, lo, hi, log_flag in specs:
        if fixed_val is None:
            free_names.append(name)
            v_clamped = float(np.clip(init_v, lo * 1.01, hi * 0.99))
            x0.append(math.log(v_clamped) if log_flag else v_clamped)
            lb.append(math.log(lo) if log_flag else lo)
            ub.append(math.log(hi) if log_flag else hi)
            is_log.append(log_flag)

    def unpack(vec: np.ndarray) -> tuple[float, float, float, float, float]:
        vals: list[float] = []
        pos = 0
        for _, fixed_val, _, _, _, log_flag in specs:
            if fixed_val is not None:
                vals.append(float(fixed_val))
            else:
                raw_v = float(vec[pos])
                pos += 1
                vals.append(math.exp(raw_v) if log_flag else raw_v)
        return vals[0], vals[1], vals[2], vals[3], vals[4]

    s_scale = max(float(np.std(s_exp)), 12.0)

    def resid(vec: np.ndarray) -> np.ndarray:
        m1, m2, de, b_rat, mu1 = unpack(vec)
        pred = predict_convergence_at_nh(
            nh_m3,
            temperature_k=temperature_k,
            m1_dos=m1,
            m2_dos=m2,
            delta_e_ev=de,
            mu0_1_cm2_vs=mu1,
            b_mobility_ratio=b_rat,
            band1_eg_ev=band1_eg_ev,
            carrier_sign=carrier_sign,
        )
        r_list = [(pred["Seebeck_abs_uV_K"] - s_exp) / s_scale]
        if has_mobility and mu_exp is not None:
            valid = np.isfinite(mu_exp) & (mu_exp > 0)
            r_list.append((np.log(pred["Hall_Mobility_cm2_V-1_s-1"][valid]) - np.log(mu_exp[valid])) / 0.16)
        if fix_m1 is None and fix_m2 is None and m2 < 1.15 * m1:
            r_list.append(np.asarray([8.0 * (1.15 * m1 - m2) / max(m1, 0.1)]))
        return np.concatenate(r_list)

    if free_names:
        bounds_de = list(zip(lb, ub))
        de_res = differential_evolution(
            lambda v: float(np.sum(resid(v) ** 2)),
            bounds=bounds_de,
            seed=42,
            maxiter=26,
            popsize=7,
            tol=2e-3,
            polish=False,
        )
        opt = least_squares(resid, x0=de_res.x, bounds=(lb, ub), method="trf", ftol=1e-11, xtol=1e-11)
        m1_f, m2_f, de_f, b_f, mu1_f = unpack(opt.x)
        phys_v = [math.exp(float(v)) if lg else float(v) for v, lg in zip(opt.x, is_log)]
        n_data_res = len(s_exp) + (int(np.sum(np.isfinite(mu_exp) & (mu_exp > 0))) if (has_mobility and mu_exp is not None) else 0)
        diag = compute_jacobian_diagnostics(
            opt.jac[:n_data_res, :],
            opt.fun[:n_data_res],
            free_names,
            phys_v,
            is_log_param=is_log,
        )
    else:
        m1_f, m2_f, de_f, b_f, mu1_f = unpack(np.asarray([]))
        diag = {}

    if not has_mobility and fix_mu1 is None:
        diag.setdefault("identifiability_warnings", []).append(
            "Only (nH, Seebeck) were supplied without sigma/muH/PF; absolute mu0_1 cancels out in S(nH) and was locked to 100 cm^2/Vs while fitting mobility ratio b = mu0_1/mu0_2."
        )

    pred_pts = predict_convergence_at_nh(
        nh_m3,
        temperature_k=temperature_k,
        m1_dos=m1_f,
        m2_dos=m2_f,
        delta_e_ev=de_f,
        mu0_1_cm2_vs=mu1_f,
        b_mobility_ratio=b_f,
        band1_eg_ev=band1_eg_ev,
        carrier_sign=carrier_sign,
    )
    pts["Seebeck_model_uV_K"] = pred_pts["Seebeck_abs_uV_K"]
    pts["Hall_Mobility_model_cm2_V-1_s-1"] = pred_pts["Hall_Mobility_cm2_V-1_s-1"]
    pts["Power_Factor_model_uW_cm-1_K-2"] = pred_pts["Power_Factor_uW_cm-1_K-2"]
    pts["Band2_Conductivity_Fraction"] = pred_pts["Band2_Conductivity_Fraction"]

    nh_lo = float(pts["nH_cm-3"].min()) * 0.55
    nh_hi = float(pts["nH_cm-3"].max()) * 1.85
    nh_grid_m3 = np.logspace(math.log10(nh_lo), math.log10(nh_hi), 240) * 1e6

    crv_2b = predict_convergence_at_nh(
        nh_grid_m3,
        temperature_k=temperature_k,
        m1_dos=m1_f,
        m2_dos=m2_f,
        delta_e_ev=de_f,
        mu0_1_cm2_vs=mu1_f,
        b_mobility_ratio=b_f,
        band1_eg_ev=band1_eg_ev,
        carrier_sign=carrier_sign,
    )
    crv_b1 = predict_convergence_at_nh(
        nh_grid_m3,
        temperature_k=temperature_k,
        m1_dos=m1_f,
        m2_dos=m2_f,
        delta_e_ev=5.0,
        mu0_1_cm2_vs=mu1_f,
        b_mobility_ratio=b_f,
        band1_eg_ev=band1_eg_ev,
        carrier_sign=carrier_sign,
    )
    crv_b2 = predict_convergence_at_nh(
        nh_grid_m3,
        temperature_k=temperature_k,
        m1_dos=m2_f,
        m2_dos=m2_f,
        delta_e_ev=5.0,
        mu0_1_cm2_vs=mu1_f / b_f,
        b_mobility_ratio=1.0,
        band1_eg_ev=None,
        carrier_sign=carrier_sign,
    )

    curve_df = pd.DataFrame(
        {
            "nH_cm-3": nh_grid_m3 * 1e-6,
            "Seebeck_TwoBand_uV_K": crv_2b["Seebeck_abs_uV_K"],
            "Seebeck_Band1_only_uV_K": crv_b1["Seebeck_abs_uV_K"],
            "Seebeck_Band2_only_uV_K": crv_b2["Seebeck_abs_uV_K"],
            "Hall_Mobility_TwoBand_cm2_V-1_s-1": crv_2b["Hall_Mobility_cm2_V-1_s-1"],
            "Power_Factor_TwoBand_uW_cm-1_K-2": crv_2b["Power_Factor_uW_cm-1_K-2"],
            "Power_Factor_Band1_only_uW_cm-1_K-2": crv_b1["Power_Factor_uW_cm-1_K-2"],
            "Band2_Conductivity_Fraction": crv_2b["Band2_Conductivity_Fraction"],
        }
    )

    s_res = pred_pts["Seebeck_abs_uV_K"] - s_exp
    fit_summary = {
        "mode": "convergence",
        "Temperature_K": float(temperature_k),
        "carrier_type": "p-type" if carrier_sign > 0 else "n-type",
        "band1_Eg_eV": band1_eg_ev,
        "m1_dos_over_me": m1_f,
        "m2_dos_over_me": m2_f,
        "delta_E_eV": de_f,
        "delta_E_in_kBT": float((de_f * e) / (k * temperature_k)),
        "mu0_1_cm2_Vs": mu1_f if has_mobility or fix_mu1 is not None else None,
        "mu0_2_cm2_Vs": (mu1_f / b_f) if has_mobility or fix_mu1 is not None else None,
        "b_mu1_over_mu2": b_f,
        "seebeck_rmse_uV_K": float(np.sqrt(np.mean(s_res**2))),
        "diagnostics": diag,
    }
    return pts, curve_df, fit_summary


# ===========================================================================
# MODE 2: Temperature-Dependent Bipolar Two-Band (`bipolar`: Majority + Minority)
# ===========================================================================
def solve_bipolar_neutrality_eta(
    temperatures_k: np.ndarray,
    *,
    n_dop_m3: float,
    m_maj_dos: float,
    m_min_dos: float,
    eg0_ev: float,
    beta_eg_ev_k: float = 0.0,
    allow_semimetal: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Solve exact 1D charge neutrality n_maj(eta, T) - n_min(-eta - E_g(T)/k_BT, T) = N_dop.

    Because dF_{1/2}(eta)/d(eta) = 0.5 * F_{-1/2}(eta) > 0 strictly for all real eta, the left-hand side
    is strictly monotonically increasing from -inf to +inf for ANY real E_g(T) (positive semiconductor
    bandgap, zero-gap Dirac/nodal semimetal, OR negative band-overlap semimetal E_g < 0).
    """
    t_arr = np.atleast_1d(np.asarray(temperatures_k, dtype=float))
    raw_eg = float(eg0_ev) + float(beta_eg_ev_k) * t_arr
    if allow_semimetal or float(eg0_ev) <= 0.02:
        eg_t = np.clip(raw_eg, -1.5, 5.0)
    else:
        eg_t = np.maximum(0.02, raw_eg)
    eg_red = (eg_t * e) / (k * t_arr)

    pref_base = 4.0 * math.pi * ((2.0 * m_e * k * t_arr / (h**2)) ** 1.5)
    pref_maj = pref_base * (float(m_maj_dos) ** 1.5)
    pref_min = pref_base * (float(m_min_dos) ** 1.5)
    target = float(n_dop_m3)

    lo = np.full_like(t_arr, -55.0, dtype=float)
    hi = np.full_like(t_arr, 75.0, dtype=float)
    for _ in range(22):
        mid = 0.5 * (lo + hi)
        diff = pref_maj * fermi_integral_vec(mid, 0.5) - pref_min * fermi_integral_vec(-mid - eg_red, 0.5) - target
        hi = np.where(diff > 0.0, mid, hi)
        lo = np.where(diff <= 0.0, mid, lo)

    eta_maj = 0.5 * (lo + hi)
    for _ in range(4):
        f_val = pref_maj * fermi_integral_vec(eta_maj, 0.5) - pref_min * fermi_integral_vec(-eta_maj - eg_red, 0.5) - target
        df_val = 0.5 * (
            pref_maj * fermi_integral_vec(eta_maj, -0.5) + pref_min * fermi_integral_vec(-eta_maj - eg_red, -0.5)
        )
        eta_maj = np.clip(eta_maj - f_val / np.maximum(df_val, 1e-30), lo, hi)

    eta_min = -eta_maj - eg_red
    return eta_maj, eta_min, eg_t


def evaluate_bipolar_temperature_series(
    temperatures_k: np.ndarray,
    *,
    majority_sign: int,
    n_dop_cm3: float,
    m_maj_dos: float,
    m_min_dos: float,
    mu0_maj_300_cm2_vs: float,
    b_min_over_maj: float,
    eg0_ev: float,
    beta_eg_ev_k: float = 0.0,
    acoustic_p: float = 1.5,
    scattering_r: float = -0.5,
    mu_imp_maj_cm2_vs: float | None = None,
    allow_semimetal: bool = False,
    use_hall_factor: bool = True,
) -> dict[str, np.ndarray]:
    t_arr = np.atleast_1d(np.asarray(temperatures_k, dtype=float))
    eta_maj, eta_min, eg_t = solve_bipolar_neutrality_eta(
        t_arr,
        n_dop_m3=float(n_dop_cm3) * 1e6,
        m_maj_dos=m_maj_dos,
        m_min_dos=m_min_dos,
        eg0_ev=eg0_ev,
        beta_eg_ev_k=beta_eg_ev_k,
        allow_semimetal=allow_semimetal,
    )
    if mu_imp_maj_cm2_vs is not None and float(mu_imp_maj_cm2_vs) > 0.0:
        # Exact Matthiessen's rule combining T-independent defect/boundary scattering + T^p phonon scattering
        inv_mu_maj = (1.0 / float(mu_imp_maj_cm2_vs)) + (1.0 / float(mu0_maj_300_cm2_vs)) * (
            (t_arr / 300.0) ** float(acoustic_p)
        )
        mu_maj_t = 1.0 / np.maximum(inv_mu_maj, 1e-30)
    else:
        mu_maj_t = float(mu0_maj_300_cm2_vs) * ((t_arr / 300.0) ** (-float(acoustic_p)))
    mu_min_t = mu_maj_t * float(b_min_over_maj)

    st_maj = _eval_parabolic_or_acoustic_band(
        eta_maj,
        temperature_k=t_arr,
        mstar_dos_ratio=m_maj_dos,
        mu0_cm2_vs=1.0,
        carrier_sign=majority_sign,
        scattering_r=scattering_r,
        use_hall_factor=use_hall_factor,
    )
    st_min = _eval_parabolic_or_acoustic_band(
        eta_min,
        temperature_k=t_arr,
        mstar_dos_ratio=m_min_dos,
        mu0_cm2_vs=1.0,
        carrier_sign=-majority_sign,
        scattering_r=scattering_r,
        use_hall_factor=use_hall_factor,
    )

    for st, mu_vec in ((st_maj, mu_maj_t), (st_min, mu_min_t)):
        st["Drift_Mobility_cm2_V-1_s-1"] = st["Drift_Mobility_cm2_V-1_s-1"] * mu_vec
        st["Hall_Mobility_cm2_V-1_s-1"] = st["Hall_Mobility_cm2_V-1_s-1"] * mu_vec
        st["Conductivity_S_m-1"] = st["Conductivity_S_m-1"] * mu_vec
        st["Conductivity_S_cm-1"] = st["Conductivity_S_cm-1"] * mu_vec
        st["Power_Factor_W_m-1_K-2"] = st["Power_Factor_W_m-1_K-2"] * mu_vec
        st["Power_Factor_uW_cm-1_K-2"] = st["Power_Factor_uW_cm-1_K-2"] * mu_vec
        st["Carrier_Thermal_Conductivity_W_m-1_K-1"] = st["Carrier_Thermal_Conductivity_W_m-1_K-1"] * mu_vec

    comb = combine_two_bands(st_maj, st_min)
    comb["eta_maj"] = eta_maj
    comb["eta_min"] = eta_min
    comb["Eg_T_eV"] = eg_t
    comb["n_maj_cm-3"] = st_maj["n_cm-3"]
    comb["n_min_cm-3"] = st_min["n_cm-3"]
    comb["Drift_Mobility_maj_cm2_V-1_s-1"] = st_maj["Drift_Mobility_cm2_V-1_s-1"]
    comb["Drift_Mobility_min_cm2_V-1_s-1"] = st_min["Drift_Mobility_cm2_V-1_s-1"]
    comb["Seebeck_extrinsic_only_uV_K"] = st_maj["Seebeck_uV_K"]
    comb["Conductivity_maj_S_cm-1"] = st_maj["Conductivity_S_cm-1"]
    comb["Conductivity_min_S_cm-1"] = st_min["Conductivity_S_cm-1"]
    return comb


def _electron_to_hole_weighted_ratio(
    majority_sign: int,
    m_maj_dos: float,
    m_min_dos: float,
    b_min_over_maj: float,
) -> float:
    """Compute electron-to-hole weighted mobility ratio A = (mu_e/mu_h) * (m*_d,e / m*_d,h)^(3/2)."""
    if majority_sign < 0:
        # Majority = electrons, minority = holes -> mu_e / mu_h = 1 / b_min_over_maj
        return float((1.0 / max(b_min_over_maj, 1e-30)) * ((m_maj_dos / m_min_dos) ** 1.5))
    # Majority = holes, minority = electrons -> mu_e / mu_h = b_min_over_maj
    return float(b_min_over_maj * ((m_min_dos / m_maj_dos) ** 1.5))


def fit_two_band_bipolar(
    df_raw: pd.DataFrame,
    *,
    fix_eg0: float | None = None,
    fix_m_maj: float | None = None,
    fix_m_min: float | None = None,
    fix_n_dop_cm3: float | None = None,
    fix_b: float | None = None,
    fix_mu_imp: float | None = None,
    beta_eg_ev_k: float = 0.0,
    acoustic_p: float = 1.5,
    scattering_r: float = -0.5,
    allow_semimetal: bool = False,
    matthiessen: bool = False,
    fit_nh: bool = False,
    nh_unit: str = "cm^-3",
    sigma_unit: str = "auto",
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    c_t = find_column(df_raw, None, TEMPERATURE_CANDIDATES, required=True)
    c_s = find_column(df_raw, None, SEEBECK_CANDIDATES, required=True)
    c_kt = find_column(df_raw, None, KAPPA_TOT_CANDIDATES, required=False)

    pts = df_raw.copy()
    pts["Temperature_K"] = pd.to_numeric(pts[c_t], errors="coerce").astype(float)
    pts["Seebeck_uV_K"] = infer_seebeck_uv_k(pts[c_s])
    sig_sm = _extract_conductivity_s_m(pts, sigma_unit=sigma_unit, required=True)
    assert sig_sm is not None
    pts["Conductivity_exp_S_m-1"] = sig_sm
    pts["Conductivity_exp_S_cm-1"] = sig_sm * 0.01

    maj_sign_guess = 1 if float(pts["Seebeck_uV_K"].dropna().iloc[0]) >= 0.0 else -1
    nh_m3_ser, _ = _extract_hall_nh_and_rh(pts, nh_unit=nh_unit, fallback_sign=maj_sign_guess, required=False)
    has_nh_col = nh_m3_ser is not None
    if nh_m3_ser is not None:
        pts["nH_exp_cm-3"] = nh_m3_ser * 1e-6

    has_kappa = c_kt is not None
    if has_kappa:
        pts["Thermal_Conductivity_exp_W_m-1_K-1"] = pd.to_numeric(pts[c_kt], errors="coerce").astype(float)

    req = ["Temperature_K", "Seebeck_uV_K", "Conductivity_exp_S_m-1"]
    if has_kappa:
        req.append("Thermal_Conductivity_exp_W_m-1_K-1")
    if fit_nh and has_nh_col:
        req.append("nH_exp_cm-3")
    pts = pts.replace([np.inf, -np.inf], np.nan).dropna(subset=req).sort_values("Temperature_K").reset_index(drop=True)
    if len(pts) < 5:
        raise ValueError(f"Bipolar temperature fit requires >= 5 temperature points, got {len(pts)}")

    t_exp = pts["Temperature_K"].to_numpy(dtype=float)
    s_exp = pts["Seebeck_uV_K"].to_numpy(dtype=float)
    sig_exp = pts["Conductivity_exp_S_m-1"].to_numpy(dtype=float)
    kt_exp = pts["Thermal_Conductivity_exp_W_m-1_K-1"].to_numpy(dtype=float) if has_kappa else None
    nh_exp = pts["nH_exp_cm-3"].to_numpy(dtype=float) if (fit_nh and has_nh_col) else None

    maj_sign = 1 if float(s_exp[0]) >= 0.0 else -1
    idx_smax = int(np.argmax(np.abs(s_exp)))
    s_max_abs_vk = float(abs(s_exp[idx_smax])) * 1e-6
    t_smax = float(t_exp[idx_smax])
    eg_goldsmid_sharp = float(2.0 * s_max_abs_vk * t_smax)

    semimetal_enabled = bool(allow_semimetal or (fix_eg0 is not None and float(fix_eg0) < 0.02))
    use_matthiessen = bool(matthiessen or (fix_mu_imp is not None))
    tie_m_min_to_maj = (fix_m_min is None) and (not has_kappa)

    if fix_n_dop_cm3 is not None:
        ndop_spec = ("n_dop_1e19_cm3", float(fix_n_dop_cm3) / 1e19, 0.5, -50.0, 50.0, False)
    else:
        ndop_spec = ("n_dop_1e19_cm3", None, 0.5, 1e-4, 50.0, True)

    if semimetal_enabled:
        eg_init = float(fix_eg0) if fix_eg0 is not None else -0.06
        eg_spec = ("Eg0_eV", fix_eg0, eg_init, -0.45, 0.80, False)
    else:
        eg_spec = ("Eg0_eV", fix_eg0, float(np.clip(eg_goldsmid_sharp, 0.08, 1.5)), 0.03, 2.5, True)

    specs: list[tuple[str, float | None, float, float, float, bool]] = [
        ndop_spec,
        ("m_maj_dos_over_me", fix_m_maj, 1.0, 0.05, 15.0, True),
        ("m_min_dos_over_me", (fix_m_maj if tie_m_min_to_maj and fix_m_maj else fix_m_min), 0.8, 0.05, 15.0, True),
        ("mu0_maj_300K_cm2_Vs", None, 150.0, 0.5, 5e4, True),
        ("b_mu_min_over_maj", fix_b, (0.3 if semimetal_enabled else 1.5), 0.02, 40.0, True),
        eg_spec,
    ]
    if tie_m_min_to_maj:
        specs[2] = ("m_min_dos_over_me", -1.0, 0.8, 0.05, 15.0, True)
    if use_matthiessen:
        specs.append(("mu_imp_maj_cm2_Vs", fix_mu_imp, 2500.0, 5.0, 2e5, True))
    if has_kappa and kt_exp is not None:
        kl_300_guess = max(float(kt_exp[0]) * 0.8, 0.3)
        specs.append(("kL_A_W_m", None, kl_300_guess * float(t_exp[0]) * 0.75, 1.0, 5e4, True))
        specs.append(("kL_inf_W_mK", None, kl_300_guess * 0.25, 0.05, 15.0, True))

    free_names, x0, lb, ub, is_log = [], [], [], [], []
    for name, fval, iv, lo, hi, lg in specs:
        if fval is None:
            free_names.append(name)
            if lg:
                vc = float(np.clip(iv, lo * 1.01, hi * 0.99))
                x0.append(math.log(vc))
                lb.append(math.log(lo))
                ub.append(math.log(hi))
            else:
                span = hi - lo
                vc = float(np.clip(iv, lo + 0.01 * span, hi - 0.01 * span))
                x0.append(vc)
                lb.append(lo)
                ub.append(hi)
            is_log.append(lg)

    def unpack(vec: np.ndarray) -> dict[str, float]:
        out_p: dict[str, float] = {}
        pos = 0
        for name, fval, _, _, _, lg in specs:
            if fval is not None:
                out_p[name] = float(fval)
            else:
                rv = float(vec[pos])
                pos += 1
                out_p[name] = math.exp(rv) if lg else rv
        if tie_m_min_to_maj:
            out_p["m_min_dos_over_me"] = out_p["m_maj_dos_over_me"]
        return out_p

    s_scale = max(float(np.std(s_exp)), 15.0)
    k_scale = max(float(np.std(kt_exp)), 0.08) if (has_kappa and kt_exp is not None) else 0.1

    def resid(vec: np.ndarray) -> np.ndarray:
        p = unpack(vec)
        ev = evaluate_bipolar_temperature_series(
            t_exp,
            majority_sign=maj_sign,
            n_dop_cm3=p["n_dop_1e19_cm3"] * 1e19,
            m_maj_dos=p["m_maj_dos_over_me"],
            m_min_dos=p["m_min_dos_over_me"],
            mu0_maj_300_cm2_vs=p["mu0_maj_300K_cm2_Vs"],
            b_min_over_maj=p["b_mu_min_over_maj"],
            eg0_ev=p["Eg0_eV"],
            beta_eg_ev_k=beta_eg_ev_k,
            acoustic_p=acoustic_p,
            scattering_r=scattering_r,
            mu_imp_maj_cm2_vs=p.get("mu_imp_maj_cm2_Vs"),
            allow_semimetal=semimetal_enabled,
        )
        r_parts = [
            (ev["Seebeck_uV_K"] - s_exp) / s_scale,
            (np.log(ev["Conductivity_S_m-1"]) - np.log(sig_exp)) / 0.12,
        ]
        if nh_exp is not None:
            r_parts.append((np.log(ev["nH_cm-3"]) - np.log(nh_exp)) / 0.10)
        if has_kappa and kt_exp is not None:
            kl_mod = p["kL_A_W_m"] / t_exp + p["kL_inf_W_mK"]
            kt_mod = kl_mod + ev["Total_Electronic_Thermal_Conductivity_W_m-1_K-1"]
            r_parts.append((kt_mod - kt_exp) / k_scale)
        return np.concatenate(r_parts)

    if free_names:
        de_res = differential_evolution(
            lambda v: float(np.sum(resid(v) ** 2)),
            bounds=list(zip(lb, ub)),
            seed=42,
            maxiter=28,
            popsize=7,
            tol=2e-3,
            polish=False,
        )
        opt = least_squares(resid, x0=de_res.x, bounds=(lb, ub), method="trf", ftol=1e-11, xtol=1e-11)
        p_fit = unpack(opt.x)
        phys_v = [math.exp(float(v)) if lg else float(v) for v, lg in zip(opt.x, is_log)]
        diag = compute_jacobian_diagnostics(opt.jac, opt.fun, free_names, phys_v, is_log_param=is_log)
    else:
        p_fit = unpack(np.asarray([]))
        diag = {}

    ev_pts = evaluate_bipolar_temperature_series(
        t_exp,
        majority_sign=maj_sign,
        n_dop_cm3=p_fit["n_dop_1e19_cm3"] * 1e19,
        m_maj_dos=p_fit["m_maj_dos_over_me"],
        m_min_dos=p_fit["m_min_dos_over_me"],
        mu0_maj_300_cm2_vs=p_fit["mu0_maj_300K_cm2_Vs"],
        b_min_over_maj=p_fit["b_mu_min_over_maj"],
        eg0_ev=p_fit["Eg0_eV"],
        beta_eg_ev_k=beta_eg_ev_k,
        acoustic_p=acoustic_p,
        scattering_r=scattering_r,
        mu_imp_maj_cm2_vs=p_fit.get("mu_imp_maj_cm2_Vs"),
        allow_semimetal=semimetal_enabled,
    )
    pts["Seebeck_model_uV_K"] = ev_pts["Seebeck_uV_K"]
    pts["Conductivity_model_S_cm-1"] = ev_pts["Conductivity_S_cm-1"]
    pts["nH_model_cm-3"] = ev_pts["nH_cm-3"]
    pts["Carrier_Thermal_Conductivity_W_m-1_K-1"] = ev_pts["Carrier_Thermal_Conductivity_W_m-1_K-1"]
    pts["Bipolar_Thermal_Conductivity_W_m-1_K-1"] = ev_pts["Bipolar_Thermal_Conductivity_W_m-1_K-1"]
    if has_kappa and kt_exp is not None:
        pts["Lattice_Thermal_Conductivity_true_W_m-1_K-1"] = (
            kt_exp - ev_pts["Total_Electronic_Thermal_Conductivity_W_m-1_K-1"]
        )

    t_grid = np.linspace(float(t_exp.min()) * 0.96, float(t_exp.max()) * 1.04, 240)
    ev_grd = evaluate_bipolar_temperature_series(
        t_grid,
        majority_sign=maj_sign,
        n_dop_cm3=p_fit["n_dop_1e19_cm3"] * 1e19,
        m_maj_dos=p_fit["m_maj_dos_over_me"],
        m_min_dos=p_fit["m_min_dos_over_me"],
        mu0_maj_300_cm2_vs=p_fit["mu0_maj_300K_cm2_Vs"],
        b_min_over_maj=p_fit["b_mu_min_over_maj"],
        eg0_ev=p_fit["Eg0_eV"],
        beta_eg_ev_k=beta_eg_ev_k,
        acoustic_p=acoustic_p,
        scattering_r=scattering_r,
        mu_imp_maj_cm2_vs=p_fit.get("mu_imp_maj_cm2_Vs"),
        allow_semimetal=semimetal_enabled,
    )
    curve_df = pd.DataFrame(
        {
            "Temperature_K": t_grid,
            "Seebeck_TwoBand_uV_K": ev_grd["Seebeck_uV_K"],
            "Seebeck_Extrinsic_Majority_uV_K": ev_grd["Seebeck_extrinsic_only_uV_K"],
            "Conductivity_Total_S_cm-1": ev_grd["Conductivity_S_cm-1"],
            "Conductivity_Majority_S_cm-1": ev_grd["Conductivity_maj_S_cm-1"],
            "Conductivity_Minority_S_cm-1": ev_grd["Conductivity_min_S_cm-1"],
            "nH_TwoBand_cm-3": ev_grd["nH_cm-3"],
            "kappa_e_W_m-1_K-1": ev_grd["Carrier_Thermal_Conductivity_W_m-1_K-1"],
            "kappa_bipolar_W_m-1_K-1": ev_grd["Bipolar_Thermal_Conductivity_W_m-1_K-1"],
        }
    )
    if has_kappa:
        kl_grd = p_fit["kL_A_W_m"] / t_grid + p_fit["kL_inf_W_mK"]
        curve_df["kappa_L_model_W_m-1_K-1"] = kl_grd
        curve_df["kappa_total_model_W_m-1_K-1"] = kl_grd + ev_grd["Total_Electronic_Thermal_Conductivity_W_m-1_K-1"]

    ev_300 = evaluate_bipolar_temperature_series(
        np.asarray([300.0]),
        majority_sign=maj_sign,
        n_dop_cm3=p_fit["n_dop_1e19_cm3"] * 1e19,
        m_maj_dos=p_fit["m_maj_dos_over_me"],
        m_min_dos=p_fit["m_min_dos_over_me"],
        mu0_maj_300_cm2_vs=p_fit["mu0_maj_300K_cm2_Vs"],
        b_min_over_maj=p_fit["b_mu_min_over_maj"],
        eg0_ev=p_fit["Eg0_eV"],
        beta_eg_ev_k=beta_eg_ev_k,
        acoustic_p=acoustic_p,
        scattering_r=scattering_r,
        mu_imp_maj_cm2_vs=p_fit.get("mu_imp_maj_cm2_Vs"),
        allow_semimetal=semimetal_enabled,
    )
    b_drift_300 = float(ev_300["Drift_Mobility_min_cm2_V-1_s-1"][0] / max(ev_300["Drift_Mobility_maj_cm2_V-1_s-1"][0], 1e-30))

    fit_summary: dict[str, Any] = {
        "mode": "bipolar",
        "majority_carrier": "p-type" if maj_sign > 0 else "n-type",
        "allow_semimetal": semimetal_enabled,
        "scattering_r": float(scattering_r),
        "goldsmid_sharp_Eg_eV": eg_goldsmid_sharp,
        "fitted_Eg0_eV": p_fit["Eg0_eV"],
        "Eg_300K_eV": float(ev_300["Eg_T_eV"][0]),
        "n_dop_cm-3": p_fit["n_dop_1e19_cm3"] * 1e19,
        "m_maj_dos_over_me": p_fit["m_maj_dos_over_me"],
        "m_min_dos_over_me": p_fit["m_min_dos_over_me"],
        "mu0_maj_300K_cm2_Vs": p_fit["mu0_maj_300K_cm2_Vs"],
        "mu_imp_maj_cm2_Vs": p_fit.get("mu_imp_maj_cm2_Vs"),
        "b_mu_min_over_maj": p_fit["b_mu_min_over_maj"],
        "weighted_mobility_ratio_A0_e_over_h": _electron_to_hole_weighted_ratio(
            maj_sign, p_fit["m_maj_dos_over_me"], p_fit["m_min_dos_over_me"], p_fit["b_mu_min_over_maj"]
        ),
        "weighted_mobility_ratio_A_drift_300K_e_over_h": _electron_to_hole_weighted_ratio(
            maj_sign, p_fit["m_maj_dos_over_me"], p_fit["m_min_dos_over_me"], b_drift_300
        ),
        "seebeck_rmse_uV_K": float(np.sqrt(np.mean((ev_pts["Seebeck_uV_K"] - s_exp) ** 2))),
        "diagnostics": diag,
    }
    return pts, curve_df, fit_summary


# ===========================================================================
# MODE 3: Semimetal / Compensated Two-Band Point-by-Point Inversion (`semimetal`)
#         (Exact Boltzmann & parallel conduction Eqs. S11-S17 of Mao et al. 2019)
# ===========================================================================
def invert_two_band_semimetal(
    df_raw: pd.DataFrame,
    *,
    m_e_dos: float | None = None,
    m_h_dos: float | None = None,
    n_dop_cm3: float = 0.0,
    fix_eg0: float | None = None,
    beta_eg_ev_k: float = 0.0,
    closure: str = "auto",
    scattering_r: float = -0.5,
    nh_unit: str = "cm^-3",
    sigma_unit: str = "auto",
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Non-parametric temperature-by-temperature e+h two-band decomposition.

    Conventions:
    - Band 1 (`m_e_dos` / `--fix-m1`): Conduction band DOS effective mass m*_d,e / m_e = N_e^(2/3) m*_b,e / m_e.
    - Band 2 (`m_h_dos` / `--fix-m2`): Valence band DOS effective mass m*_d,h / m_e = N_h^(2/3) m*_b,h / m_e.
    - `closure`:
      * `'hall-split'` (default when `fix_eg0 is None`): uses measured Hall concentration n_H(T) = 1/(e|R_H(T)|)
        with n_e(T) + n_h(T) = n_H(T) and charge balance n_e(T) - n_h(T) = N_dop (reducing to n_e = n_h = n_H/2
        for stoichiometric semimetals N_dop = 0, cf. Mao et al. Science 2019 Eqs. S11-S17), solving exact
        Fermi integrals for eta_e(T), eta_h(T) and band overlap E_g(T) = -(eta_e + eta_h) k_B T.
      * `'fixed-gap'` (default when `fix_eg0 is not None`): uses E_g(T) = E_g0 + beta_Eg * T and solves exact
        1D charge neutrality n_e(eta_e, T) - n_h(-eta_e - E_g(T)/(k_B T), T) = N_dop without assuming
        n_e + n_h = n_H.
    """
    if m_e_dos is None or m_h_dos is None or m_e_dos <= 0.0 or m_h_dos <= 0.0:
        raise MissingMaterialParametersError(
            "Semimetal / Hall-inversion mode requires both conduction and valence DOS effective masses:\n"
            "  1. Conduction-band DOS mass: --fix-m1 <m*_d,e / m_e>  (where m*_d = N_v^(2/3) * (m_xx*m_yy*m_zz)^(1/3))\n"
            "  2. Valence-band DOS mass:    --fix-m2 <m*_d,h / m_e>\n"
            "Example (Mg3.2Bi2, Table S1 of Mao et al. Science 2019):\n"
            "  python main.py two-band path/to/data.csv --mode semimetal --fix-m1 0.530 --fix-m2 0.276 --no-show"
        )

    resolved_closure = closure.strip().lower()
    if resolved_closure == "auto":
        resolved_closure = "fixed-gap" if fix_eg0 is not None else "hall-split"
    if resolved_closure not in {"hall-split", "fixed-gap"}:
        raise ValueError(f"Unknown semimetal closure {closure!r}; choose 'auto', 'hall-split', or 'fixed-gap'.")
    if resolved_closure == "fixed-gap" and fix_eg0 is None:
        raise MissingMaterialParametersError(
            "Semimetal '--semimetal-closure fixed-gap' requires '--fix-eg0 <eV>' (negative for semimetal band overlap, e.g. -0.10)."
        )

    c_t = find_column(df_raw, None, TEMPERATURE_CANDIDATES, required=True)
    c_s = find_column(df_raw, None, SEEBECK_CANDIDATES, required=True)
    c_kt = find_column(df_raw, None, KAPPA_TOT_CANDIDATES, required=False)

    pts = df_raw.copy()
    pts["Temperature_K"] = pd.to_numeric(pts[c_t], errors="coerce").astype(float)
    pts["Seebeck_uV_K"] = infer_seebeck_uv_k(pts[c_s])
    sig_sm = _extract_conductivity_s_m(pts, sigma_unit=sigma_unit, required=True)
    assert sig_sm is not None
    pts["Conductivity_exp_S_m-1"] = sig_sm
    pts["Conductivity_exp_S_cm-1"] = sig_sm * 0.01

    med_sign = 1 if float(pts["Seebeck_uV_K"].dropna().median()) >= 0.0 else -1
    nh_m3_ser, rh_m3_c_ser = _extract_hall_nh_and_rh(
        pts,
        nh_unit=nh_unit,
        fallback_sign=med_sign,
        required=(resolved_closure == "hall-split"),
    )
    has_hall = nh_m3_ser is not None and rh_m3_c_ser is not None
    if has_hall:
        assert nh_m3_ser is not None and rh_m3_c_ser is not None
        pts["nH_exp_m-3"] = nh_m3_ser
        pts["nH_exp_cm-3"] = nh_m3_ser * 1e-6
        pts["RH_exp_m3_C-1"] = rh_m3_c_ser
        pts["Hall_Mobility_exp_cm2_V-1_s-1"] = rh_m3_c_ser.abs() * sig_sm * 1e4

    has_kappa = c_kt is not None
    if has_kappa:
        pts["Thermal_Conductivity_exp_W_m-1_K-1"] = pd.to_numeric(pts[c_kt], errors="coerce").astype(float)

    req = ["Temperature_K", "Seebeck_uV_K", "Conductivity_exp_S_m-1"]
    if resolved_closure == "hall-split":
        req.append("nH_exp_m-3")
    pts = pts.replace([np.inf, -np.inf], np.nan).dropna(subset=req).sort_values("Temperature_K").reset_index(drop=True)
    if len(pts) < 2:
        raise ValueError(f"Semimetal inversion requires >= 2 valid temperature rows, got {len(pts)}")

    t_arr = pts["Temperature_K"].to_numpy(dtype=float)
    s_exp_uv = pts["Seebeck_uV_K"].to_numpy(dtype=float)
    s_exp_vk = s_exp_uv * 1e-6
    sig_exp_sm = pts["Conductivity_exp_S_m-1"].to_numpy(dtype=float)
    n_dop_m3 = float(n_dop_cm3) * 1e6

    if resolved_closure == "hall-split":
        nh_exp_m3 = pts["nH_exp_m-3"].to_numpy(dtype=float)
        ne_m3 = 0.5 * (nh_exp_m3 + n_dop_m3)
        nh_hole_m3 = 0.5 * (nh_exp_m3 - n_dop_m3)
        if np.any(ne_m3 <= 0.0) or np.any(nh_hole_m3 <= 0.0):
            raise ValueError(
                "In 'hall-split' closure, |N_dop| exceeds measured n_H(T) so minority density <= 0; "
                "use '--mode bipolar' or '--semimetal-closure fixed-gap' for strongly extrinsic samples."
            )
        eta_e = np.array(
            [
                solve_eta_from_carrier_density_parabolic(float(ne_v), temperature_k=float(tk), mstar_dos_ratio=float(m_e_dos))
                for ne_v, tk in zip(ne_m3, t_arr)
            ],
            dtype=float,
        )
        eta_h = np.array(
            [
                solve_eta_from_carrier_density_parabolic(float(nh_v), temperature_k=float(tk), mstar_dos_ratio=float(m_h_dos))
                for nh_v, tk in zip(nh_hole_m3, t_arr)
            ],
            dtype=float,
        )
        eg_t_ev = -(eta_e + eta_h) * (k * t_arr / e)
    else:
        assert fix_eg0 is not None
        eta_e, eta_h, eg_t_ev = solve_bipolar_neutrality_eta(
            t_arr,
            n_dop_m3=n_dop_m3,
            m_maj_dos=float(m_e_dos),
            m_min_dos=float(m_h_dos),
            eg0_ev=float(fix_eg0),
            beta_eg_ev_k=float(beta_eg_ev_k),
            allow_semimetal=True,
        )

    use_rh_factor = float(scattering_r) > -0.75
    st_e = parabolic_band_state_general_r(
        eta_e,
        temperature_k=t_arr,
        mstar_dos_ratio=float(m_e_dos),
        mu0_cm2_vs=1.0,
        scattering_r=float(scattering_r),
        carrier_sign=-1,
        use_hall_factor=use_rh_factor,
    )
    st_h = parabolic_band_state_general_r(
        eta_h,
        temperature_k=t_arr,
        mstar_dos_ratio=float(m_h_dos),
        mu0_cm2_vs=1.0,
        scattering_r=float(scattering_r),
        carrier_sign=+1,
        use_hall_factor=use_rh_factor,
    )

    ne_m3 = st_e["n_m-3"]
    nh_hole_m3 = st_h["n_m-3"]
    se_vk = st_e["Seebeck_V_K"]
    sh_vk = st_h["Seebeck_V_K"]
    denom_s = sh_vk - se_vk  # strictly > 0 since S_h > 0 and S_e < 0

    sig_e_sm = sig_exp_sm * (sh_vk - s_exp_vk) / np.maximum(denom_s, 1e-30)
    sig_h_sm = sig_exp_sm * (s_exp_vk - se_vk) / np.maximum(denom_s, 1e-30)

    mu_e_cm2_vs = (sig_e_sm / np.maximum(e * ne_m3, 1e-300)) * 1e4
    mu_h_cm2_vs = (sig_h_sm / np.maximum(e * nh_hole_m3, 1e-300)) * 1e4

    warnings: list[str] = []
    neg_e_mask = sig_e_sm <= 0.0
    neg_h_mask = sig_h_sm <= 0.0
    if np.any(neg_e_mask) or np.any(neg_h_mask):
        bad_t = t_arr[neg_e_mask | neg_h_mask]
        warnings.append(
            f"Unphysical non-positive partial mobility at {len(bad_t)} temperature(s) "
            f"(T in [{float(bad_t.min()):.0f}, {float(bad_t.max()):.0f}] K): experimental S(T) lies outside "
            f"[S_e(T), S_h(T)]. Check valley degeneracy N_v, DOS effective masses (m*_e, m*_h), or scattering exponent r."
        )

    with np.errstate(divide="ignore", invalid="ignore"):
        mu_e_over_h = np.where(mu_h_cm2_vs > 0.0, mu_e_cm2_vs / mu_h_cm2_vs, np.nan)
    mass_factor = (float(m_e_dos) / float(m_h_dos)) ** 1.5
    weighted_a = mu_e_over_h * mass_factor

    # Two-band Hall coefficient: (1) r_H = 1 convention (Eq. S17 of Mao et al.), and (2) exact Boltzmann r_H(eta)
    rh_calc_unit_factor = (
        nh_hole_m3 * ((mu_h_cm2_vs * 1e-4) ** 2) - ne_m3 * ((mu_e_cm2_vs * 1e-4) ** 2)
    ) / np.maximum(e * ((nh_hole_m3 * (mu_h_cm2_vs * 1e-4) + ne_m3 * (mu_e_cm2_vs * 1e-4)) ** 2), 1e-300)
    rh_calc_boltzmann = (
        st_h["Hall_Coefficient_m3_C-1"] * (sig_h_sm**2) + st_e["Hall_Coefficient_m3_C-1"] * (sig_e_sm**2)
    ) / np.maximum(sig_exp_sm**2, 1e-300)

    ke_w_mk = (st_e["Lorenz_WOhmK-2"] * np.maximum(sig_e_sm, 0.0) + st_h["Lorenz_WOhmK-2"] * np.maximum(sig_h_sm, 0.0)) * t_arr
    kbi_w_mk = (np.maximum(sig_e_sm, 0.0) * np.maximum(sig_h_sm, 0.0) / np.maximum(sig_exp_sm, 1e-30)) * ((se_vk - sh_vk) ** 2) * t_arr

    pts["eta_e"] = eta_e
    pts["eta_h"] = eta_h
    pts["Band_Gap_or_Overlap_eV"] = eg_t_ev
    pts["n_e_cm-3"] = ne_m3 * 1e-6
    pts["n_h_cm-3"] = nh_hole_m3 * 1e-6
    pts["Seebeck_e_uV_K"] = st_e["Seebeck_uV_K"]
    pts["Seebeck_h_uV_K"] = st_h["Seebeck_uV_K"]
    pts["Conductivity_e_S_cm-1"] = sig_e_sm * 0.01
    pts["Conductivity_h_S_cm-1"] = sig_h_sm * 0.01
    pts["Mobility_e_cm2_V-1_s-1"] = mu_e_cm2_vs
    pts["Mobility_h_cm2_V-1_s-1"] = mu_h_cm2_vs
    pts["Mobility_Ratio_e_over_h"] = mu_e_over_h
    pts["Weighted_Mobility_Ratio_A"] = weighted_a
    pts["RH_calc_rH1_m3_C-1"] = rh_calc_unit_factor
    pts["RH_calc_Boltzmann_m3_C-1"] = rh_calc_boltzmann
    if has_hall:
        rh_exp_arr = pts["RH_exp_m3_C-1"].to_numpy(dtype=float)
        pts["RH_ratio_calc_over_exp"] = rh_calc_unit_factor / rh_exp_arr
        pts["RH_ratio_Boltzmann_over_exp"] = rh_calc_boltzmann / rh_exp_arr
    pts["Carrier_Thermal_Conductivity_W_m-1_K-1"] = ke_w_mk
    pts["Bipolar_Thermal_Conductivity_W_m-1_K-1"] = kbi_w_mk
    if has_kappa:
        pts["Lattice_Thermal_Conductivity_true_W_m-1_K-1"] = (
            pts["Thermal_Conductivity_exp_W_m-1_K-1"] - ke_w_mk - kbi_w_mk
        )

    curve_df = pts.copy()

    # Summarize representative room-T (~300 K or closest point) values
    idx_ref = int(np.argmin(np.abs(t_arr - 300.0)))
    fit_summary: dict[str, Any] = {
        "mode": "semimetal",
        "closure": resolved_closure,
        "scattering_r": float(scattering_r),
        "m_e_dos_over_me": float(m_e_dos),
        "m_h_dos_over_me": float(m_h_dos),
        "n_dop_cm-3": float(n_dop_cm3),
        "reference_T_K": float(t_arr[idx_ref]),
        "Eg_at_ref_T_eV": float(eg_t_ev[idx_ref]),
        "Eg_mean_eV": float(np.nanmean(eg_t_ev)),
        "Se_at_ref_T_uV_K": float(st_e["Seebeck_uV_K"][idx_ref]),
        "Sh_at_ref_T_uV_K": float(st_h["Seebeck_uV_K"][idx_ref]),
        "mu_e_at_ref_T_cm2_Vs": float(mu_e_cm2_vs[idx_ref]),
        "mu_h_at_ref_T_cm2_Vs": float(mu_h_cm2_vs[idx_ref]),
        "mu_e_over_mu_h_at_ref_T": float(mu_e_over_h[idx_ref]) if np.isfinite(mu_e_over_h[idx_ref]) else None,
        "weighted_mobility_ratio_A_at_ref_T": float(weighted_a[idx_ref]) if np.isfinite(weighted_a[idx_ref]) else None,
        "RH_calc_over_exp_at_ref_T": (
            float(pts["RH_ratio_calc_over_exp"].iloc[idx_ref]) if "RH_ratio_calc_over_exp" in pts.columns else None
        ),
        "seebeck_rmse_uV_K": 0.0,
        "diagnostics": {
            "n_temperatures": int(len(pts)),
            "physical_partial_mobilities": bool(not (np.any(neg_e_mask) or np.any(neg_h_mask))),
            "identifiability_warnings": warnings,
        },
    }
    return pts, curve_df, fit_summary


# ===========================================================================
# MODE 4: Isothermal Bipolar Pisarenko & Weighted-Mobility Asymmetry (`isothermal-bipolar`)
#         (Exact Boltzmann Eqs. S1-S10 & Figs. S10-S12 of Mao et al. 2019)
# ===========================================================================
_ISO_BIPOLAR_ETA_GRID = np.linspace(-10.0, 24.0, 340)


def evaluate_isothermal_bipolar_grid(
    eta_maj_grid: np.ndarray,
    *,
    temperature_k: float,
    majority_sign: int,
    m_maj_dos: float,
    m_min_dos: float,
    eg_ev: float,
    mu0_maj_cm2_vs: float,
    b_min_over_maj: float,
    scattering_r: float = -0.5,
) -> dict[str, np.ndarray]:
    """Evaluate isothermal opposite-sign (e+h) two-band states across reduced majority Fermi energy."""
    eg_red = (float(eg_ev) * e) / (k * float(temperature_k))
    eta_min_grid = -np.asarray(eta_maj_grid, dtype=float) - eg_red
    mu0_min = float(mu0_maj_cm2_vs) * float(b_min_over_maj)

    st_maj = _eval_parabolic_or_acoustic_band(
        eta_maj_grid,
        temperature_k=temperature_k,
        mstar_dos_ratio=m_maj_dos,
        mu0_cm2_vs=mu0_maj_cm2_vs,
        carrier_sign=majority_sign,
        scattering_r=scattering_r,
    )
    st_min = _eval_parabolic_or_acoustic_band(
        eta_min_grid,
        temperature_k=temperature_k,
        mstar_dos_ratio=m_min_dos,
        mu0_cm2_vs=max(mu0_min, 1e-6),
        carrier_sign=-majority_sign,
        scattering_r=scattering_r,
    )
    comb = combine_two_bands(st_maj, st_min)
    comb["eta_maj"] = np.asarray(eta_maj_grid, dtype=float)
    comb["eta_min"] = eta_min_grid
    comb["n_maj_m-3"] = st_maj["n_m-3"]
    comb["n_min_m-3"] = st_min["n_m-3"]
    comb["Seebeck_maj_only_uV_K"] = st_maj["Seebeck_uV_K"]
    comb["Power_Factor_maj_only_uW_cm-1_K-2"] = st_maj["Power_Factor_uW_cm-1_K-2"]
    return comb


def predict_isothermal_bipolar_at_nh(
    nh_target_m3: np.ndarray,
    *,
    temperature_k: float,
    majority_sign: int,
    m_maj_dos: float,
    m_min_dos: float,
    eg_ev: float,
    mu0_maj_cm2_vs: float,
    b_min_over_maj: float,
    scattering_r: float = -0.5,
) -> dict[str, np.ndarray]:
    """Predict isothermal opposite-sign two-band observables at target apparent Hall concentration n_H
    within the majority-dominated Hall branch (sgn(R_H) == majority_sign).
    """
    grid = evaluate_isothermal_bipolar_grid(
        _ISO_BIPOLAR_ETA_GRID,
        temperature_k=temperature_k,
        majority_sign=majority_sign,
        m_maj_dos=m_maj_dos,
        m_min_dos=m_min_dos,
        eg_ev=eg_ev,
        mu0_maj_cm2_vs=mu0_maj_cm2_vs,
        b_min_over_maj=b_min_over_maj,
        scattering_r=scattering_r,
    )
    rh_sign_ok = (grid["Hall_Coefficient_m3_C-1"] * float(majority_sign)) > 0.0
    if np.sum(rh_sign_ok) >= 8:
        eta_sub = _ISO_BIPOLAR_ETA_GRID[rh_sign_ok]
        nh_sub = grid["nH_m-3"][rh_sign_ok]
        # Take the monotonic degenerate-to-extrinsic branch above the bipolar R_H=0 turnaround minimum
        idx_min = int(np.argmin(nh_sub))
        eta_branch = eta_sub[idx_min:]
        nh_branch = nh_sub[idx_min:]
        if len(eta_branch) < 4:
            eta_branch = eta_sub
            nh_branch = nh_sub
    else:
        eta_branch = _ISO_BIPOLAR_ETA_GRID
        nh_branch = grid["nH_m-3"]

    log_nh = np.log(np.maximum(nh_branch, 1e10))
    order = np.argsort(log_nh)
    eta_interp = np.interp(np.log(np.asarray(nh_target_m3, dtype=float)), log_nh[order], eta_branch[order])
    return evaluate_isothermal_bipolar_grid(
        eta_interp,
        temperature_k=temperature_k,
        majority_sign=majority_sign,
        m_maj_dos=m_maj_dos,
        m_min_dos=m_min_dos,
        eg_ev=eg_ev,
        mu0_maj_cm2_vs=mu0_maj_cm2_vs,
        b_min_over_maj=b_min_over_maj,
        scattering_r=scattering_r,
    )


def fit_two_band_isothermal_bipolar(
    df_raw: pd.DataFrame,
    *,
    temperature_k: float = 300.0,
    fix_m1: float | None = None,
    fix_m2: float | None = None,
    fix_eg0: float | None = None,
    fix_mu1: float | None = None,
    fix_b: float | None = None,
    scattering_r: float = -0.5,
    nh_unit: str = "cm^-3",
    sigma_unit: str = "auto",
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    c_s = find_column(df_raw, None, SEEBECK_CANDIDATES, required=True)
    c_mu = find_column(df_raw, None, MOBILITY_CANDIDATES, required=False)
    c_pf = find_column(df_raw, None, PF_CANDIDATES, required=False)

    pts = df_raw.copy()
    pts["Seebeck_uV_K"] = infer_seebeck_uv_k(pts[c_s])
    pts["Seebeck_abs_uV_K"] = pts["Seebeck_uV_K"].abs()
    maj_sign = 1 if float(pts["Seebeck_uV_K"].dropna().median()) >= 0.0 else -1

    nh_m3_ser, _ = _extract_hall_nh_and_rh(pts, nh_unit=nh_unit, fallback_sign=maj_sign, required=True)
    assert nh_m3_ser is not None
    pts["nH_m-3"] = nh_m3_ser
    pts["nH_cm-3"] = nh_m3_ser * 1e-6

    if c_mu is not None:
        pts["Hall_Mobility_exp_cm2_V-1_s-1"] = pd.to_numeric(pts[c_mu], errors="coerce").astype(float)
    sig_sm = _extract_conductivity_s_m(pts, sigma_unit=sigma_unit, required=False)
    if sig_sm is not None:
        pts["Conductivity_exp_S_m-1"] = sig_sm
        if "Hall_Mobility_exp_cm2_V-1_s-1" not in pts.columns:
            pts["Hall_Mobility_exp_cm2_V-1_s-1"] = (sig_sm / (pts["nH_m-3"] * e)) * 1e4
    if c_pf is not None:
        pts["Power_Factor_exp_uW_cm-1_K-2"] = infer_pf_uw_cm_k2(pts[c_pf], c_pf)
    elif "Conductivity_exp_S_m-1" in pts.columns:
        pts["Power_Factor_exp_uW_cm-1_K-2"] = ((pts["Seebeck_uV_K"] * 1e-6) ** 2) * pts["Conductivity_exp_S_m-1"] * 1e4

    pts = pts.replace([np.inf, -np.inf], np.nan).dropna(subset=["nH_m-3", "Seebeck_uV_K"])
    pts = pts[pts["nH_m-3"] > 0].sort_values("nH_cm-3").reset_index(drop=True)
    if len(pts) < 4:
        raise ValueError(f"Isothermal-bipolar fit needs >= 4 (nH, S) samples, got {len(pts)}")

    nh_m3 = pts["nH_m-3"].to_numpy(dtype=float)
    s_exp = pts["Seebeck_uV_K"].to_numpy(dtype=float)
    has_mobility = "Hall_Mobility_exp_cm2_V-1_s-1" in pts.columns
    mu_exp = pts["Hall_Mobility_exp_cm2_V-1_s-1"].to_numpy(dtype=float) if has_mobility else None

    # Anchor majority m*_1 from highest-nH points where minority carriers are exponentially suppressed
    n_high = max(2, len(pts) // 3)
    m1_hi_est = []
    for i in range(len(pts) - n_high, len(pts)):
        s_abs_i = max(abs(float(s_exp[i])), 5.0)
        ei = solve_eta_from_seebeck_skb(s_abs_i, alpha=0.0)
        mi, _, _ = point_mstar_from_eta_and_nh_skb(ei, float(nh_m3[i]), temperature_k, 0.0)
        m1_hi_est.append(mi)
    m1_init = float(np.clip(np.median(m1_hi_est), 0.05, 8.0))
    mu1_init = float(np.clip(np.nanmax(mu_exp) * 1.4, 2.0, 3e4)) if (has_mobility and mu_exp is not None) else 100.0
    effective_fix_mu1 = fix_mu1 if fix_mu1 is not None else (None if has_mobility else 100.0)

    tie_m2_to_m1 = fix_m2 is None
    specs: list[tuple[str, float | None, float, float, float, bool]] = [
        ("m_maj_dos_over_me", fix_m1, m1_init, 0.03, 12.0, True),
        ("m_min_dos_over_me", (-1.0 if tie_m2_to_m1 else fix_m2), m1_init, 0.03, 12.0, True),
        ("Eg_eV", fix_eg0, 0.06, -0.30, 0.60, False),
        ("b_mu_min_over_maj", fix_b, 0.30, 0.01, 30.0, True),
        ("mu0_maj_cm2_Vs", effective_fix_mu1, mu1_init, 0.2, 1e5, True),
    ]

    free_names, x0, lb, ub, is_log = [], [], [], [], []
    for name, fval, iv, lo, hi, lg in specs:
        if fval is None:
            free_names.append(name)
            if lg:
                vc = float(np.clip(iv, lo * 1.01, hi * 0.99))
                x0.append(math.log(vc))
                lb.append(math.log(lo))
                ub.append(math.log(hi))
            else:
                span = hi - lo
                vc = float(np.clip(iv, lo + 0.01 * span, hi - 0.01 * span))
                x0.append(vc)
                lb.append(lo)
                ub.append(hi)
            is_log.append(lg)

    def unpack(vec: np.ndarray) -> dict[str, float]:
        out_p: dict[str, float] = {}
        pos = 0
        for name, fval, _, _, _, lg in specs:
            if fval is not None:
                out_p[name] = float(fval)
            else:
                rv = float(vec[pos])
                pos += 1
                out_p[name] = math.exp(rv) if lg else rv
        if tie_m2_to_m1:
            out_p["m_min_dos_over_me"] = out_p["m_maj_dos_over_me"]
        return out_p

    s_scale = max(float(np.std(s_exp)), 12.0)

    def resid(vec: np.ndarray) -> np.ndarray:
        p = unpack(vec)
        pred = predict_isothermal_bipolar_at_nh(
            nh_m3,
            temperature_k=temperature_k,
            majority_sign=maj_sign,
            m_maj_dos=p["m_maj_dos_over_me"],
            m_min_dos=p["m_min_dos_over_me"],
            eg_ev=p["Eg_eV"],
            mu0_maj_cm2_vs=p["mu0_maj_cm2_Vs"],
            b_min_over_maj=p["b_mu_min_over_maj"],
            scattering_r=scattering_r,
        )
        r_list = [(pred["Seebeck_uV_K"] - s_exp) / s_scale]
        if has_mobility and mu_exp is not None:
            valid = np.isfinite(mu_exp) & (mu_exp > 0)
            r_list.append((np.log(pred["Hall_Mobility_cm2_V-1_s-1"][valid]) - np.log(mu_exp[valid])) / 0.16)
        return np.concatenate(r_list)

    if free_names:
        de_res = differential_evolution(
            lambda v: float(np.sum(resid(v) ** 2)),
            bounds=list(zip(lb, ub)),
            seed=42,
            maxiter=26,
            popsize=7,
            tol=2e-3,
            polish=False,
        )
        opt = least_squares(resid, x0=de_res.x, bounds=(lb, ub), method="trf", ftol=1e-11, xtol=1e-11)
        p_fit = unpack(opt.x)
        phys_v = [math.exp(float(v)) if lg else float(v) for v, lg in zip(opt.x, is_log)]
        diag = compute_jacobian_diagnostics(opt.jac, opt.fun, free_names, phys_v, is_log_param=is_log)
    else:
        p_fit = unpack(np.asarray([]))
        diag = {}

    if not has_mobility and fix_mu1 is None:
        diag.setdefault("identifiability_warnings", []).append(
            "Only (nH, Seebeck) were supplied without sigma/muH/PF; absolute mu0_maj cancels out in S(nH) and was locked to 100 cm^2/Vs while fitting mobility ratio b."
        )

    pred_pts = predict_isothermal_bipolar_at_nh(
        nh_m3,
        temperature_k=temperature_k,
        majority_sign=maj_sign,
        m_maj_dos=p_fit["m_maj_dos_over_me"],
        m_min_dos=p_fit["m_min_dos_over_me"],
        eg_ev=p_fit["Eg_eV"],
        mu0_maj_cm2_vs=p_fit["mu0_maj_cm2_Vs"],
        b_min_over_maj=p_fit["b_mu_min_over_maj"],
        scattering_r=scattering_r,
    )
    pts["Seebeck_model_uV_K"] = pred_pts["Seebeck_uV_K"]
    pts["Hall_Mobility_model_cm2_V-1_s-1"] = pred_pts["Hall_Mobility_cm2_V-1_s-1"]
    pts["Power_Factor_model_uW_cm-1_K-2"] = pred_pts["Power_Factor_uW_cm-1_K-2"]

    nh_lo = float(pts["nH_cm-3"].min()) * 0.55
    nh_hi = float(pts["nH_cm-3"].max()) * 1.85
    nh_grid_m3 = np.logspace(math.log10(nh_lo), math.log10(nh_hi), 220) * 1e6
    crv = predict_isothermal_bipolar_at_nh(
        nh_grid_m3,
        temperature_k=temperature_k,
        majority_sign=maj_sign,
        m_maj_dos=p_fit["m_maj_dos_over_me"],
        m_min_dos=p_fit["m_min_dos_over_me"],
        eg_ev=p_fit["Eg_eV"],
        mu0_maj_cm2_vs=p_fit["mu0_maj_cm2_Vs"],
        b_min_over_maj=p_fit["b_mu_min_over_maj"],
        scattering_r=scattering_r,
    )
    crv_maj_only = predict_isothermal_bipolar_at_nh(
        nh_grid_m3,
        temperature_k=temperature_k,
        majority_sign=maj_sign,
        m_maj_dos=p_fit["m_maj_dos_over_me"],
        m_min_dos=p_fit["m_min_dos_over_me"],
        eg_ev=4.0,
        mu0_maj_cm2_vs=p_fit["mu0_maj_cm2_Vs"],
        b_min_over_maj=p_fit["b_mu_min_over_maj"],
        scattering_r=scattering_r,
    )
    curve_df = pd.DataFrame(
        {
            "nH_cm-3": nh_grid_m3 * 1e-6,
            "Seebeck_TwoBand_uV_K": crv["Seebeck_uV_K"],
            "Seebeck_Majority_only_uV_K": crv_maj_only["Seebeck_uV_K"],
            "Power_Factor_TwoBand_uW_cm-1_K-2": crv["Power_Factor_uW_cm-1_K-2"],
            "Minority_Conductivity_Fraction": crv["Band2_Conductivity_Fraction"],
        }
    )

    a0_eh = _electron_to_hole_weighted_ratio(
        maj_sign, p_fit["m_maj_dos_over_me"], p_fit["m_min_dos_over_me"], p_fit["b_mu_min_over_maj"]
    )
    fit_summary = {
        "mode": "isothermal-bipolar",
        "Temperature_K": float(temperature_k),
        "majority_carrier": "p-type" if maj_sign > 0 else "n-type",
        "scattering_r": float(scattering_r),
        "m_maj_dos_over_me": p_fit["m_maj_dos_over_me"],
        "m_min_dos_over_me": p_fit["m_min_dos_over_me"],
        "Eg_eV": p_fit["Eg_eV"],
        "Eg_in_kBT": float((p_fit["Eg_eV"] * e) / (k * temperature_k)),
        "b_mu_min_over_maj": p_fit["b_mu_min_over_maj"],
        "weighted_mobility_ratio_A0_e_over_h": a0_eh,
        "mu0_maj_cm2_Vs": p_fit["mu0_maj_cm2_Vs"] if has_mobility or fix_mu1 is not None else None,
        "seebeck_rmse_uV_K": float(np.sqrt(np.mean((pred_pts["Seebeck_uV_K"] - s_exp) ** 2))),
        "diagnostics": diag,
    }
    return pts, curve_df, fit_summary


# ===========================================================================
# Rendering Two-Band Figures across all 4 physical modes
# ===========================================================================
def render_two_band_figures(
    pts: pd.DataFrame,
    curve_df: pd.DataFrame,
    fit_info: dict[str, Any],
    *,
    output_dir: Path,
    stem_prefix: str,
    formats: Sequence[str],
    color_set: str | None = None,
    show: bool = False,
) -> list[str]:
    apply_plot_style(mode="single")
    palette = get_colors(color_set, 5)
    mode_name = fit_info["mode"]

    if mode_name == "convergence":
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.4, 4.9))
        nh_exp = pts["nH_cm-3"].to_numpy(dtype=float)
        nh_grd = curve_df["nH_cm-3"].to_numpy(dtype=float)

        ax1.plot(nh_grd, curve_df["Seebeck_TwoBand_uV_K"], color=FIT_RED_COLOR, linewidth=DEFAULT_LINE_WIDTH * 1.2, label="Two-Band Total Fit", zorder=4.5)
        ax1.plot(nh_grd, curve_df["Seebeck_Band1_only_uV_K"], color=STAGE_NONRED_PALETTE[0], linestyle="--", linewidth=1.45, label=rf"Band 1 only ($m^*_1={fit_info['m1_dos_over_me']:.2f}m_e$)", zorder=3)
        ax1.plot(nh_grd, curve_df["Seebeck_Band2_only_uV_K"], color=STAGE_NONRED_PALETTE[1], linestyle=":", linewidth=1.45, label=rf"Band 2 only ($m^*_2={fit_info['m2_dos_over_me']:.2f}m_e$)", zorder=2.8)
        ax1.scatter(nh_exp, pts["Seebeck_abs_uV_K"], s=(DEFAULT_MARKER_SIZE * 0.95) ** 2, facecolor=EXP_MARKER_FACE, edgecolor=EXP_MARKER_EDGE, linewidths=1.05, alpha=0.90, label="Experimental", zorder=3.8)

        s_top = max(float(pts["Seebeck_abs_uV_K"].max()), float(curve_df["Seebeck_TwoBand_uV_K"].max()))
        ax1.set_xscale("log")
        ax1.set_ylim(0.0, s_top * 1.32)
        ax1.set_xlabel(r"$n_{\mathrm{H}}$ (cm$^{-3}$)")
        ax1.set_ylabel(r"$|S|$ ($\mu$V K$^{-1}$)")
        format_te_axis(ax1, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
        ax1.xaxis.set_major_locator(ticker.LogLocator(base=10.0))
        ax1.text(
            0.04,
            0.19,
            rf"$\Delta E = {fit_info['delta_E_eV']:.3f}$ eV ({fit_info['delta_E_in_kBT']:.1f} $k_{{\mathrm{{B}}}}T$)"
            + "\n"
            + rf"$b = \mu_{{0,1}}/\mu_{{0,2}} = {fit_info['b_mu1_over_mu2']:.1f}$",
            transform=ax1.transAxes,
            ha="left",
            va="top",
            fontsize=10.4,
            bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.9, "pad": 3.5},
        )
        place_legend_inside(
            ax1,
            loc="upper right",
            fontsize=10.0,
            frameon=True,
            facecolor="white",
            edgecolor="black",
            fancybox=False,
            ylim_locked=(True, False),
        )

        ax2.set_xscale("log")
        ax2.set_xlabel(r"$n_{\mathrm{H}}$ (cm$^{-3}$)")
        format_te_axis(ax2, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
        ax2.xaxis.set_major_locator(ticker.LogLocator(base=10.0))

        if "Power_Factor_exp_uW_cm-1_K-2" in pts.columns:
            ax2.plot(nh_grd, curve_df["Power_Factor_TwoBand_uW_cm-1_K-2"], color=FIT_RED_COLOR, linewidth=DEFAULT_LINE_WIDTH * 1.2, label="Two-Band $PF$ Fit", zorder=4.5)
            ax2.plot(nh_grd, curve_df["Power_Factor_Band1_only_uW_cm-1_K-2"], color=STAGE_NONRED_PALETTE[0], linestyle="--", linewidth=1.4, label="Band 1 only $PF$", zorder=3)
            ax2.scatter(nh_exp, pts["Power_Factor_exp_uW_cm-1_K-2"], s=(DEFAULT_MARKER_SIZE * 0.95) ** 2, facecolor=EXP_MARKER_FACE, edgecolor=EXP_MARKER_EDGE, linewidths=1.05, alpha=0.90, label="Experimental $PF$", zorder=3.8)
            pf_max = max(float(pts["Power_Factor_exp_uW_cm-1_K-2"].max()), float(curve_df["Power_Factor_TwoBand_uW_cm-1_K-2"].max()))
            ax2.set_ylim(0.0, pf_max * 1.34)
            ax2.set_ylabel(r"$PF$ ($\mu$W cm$^{-1}$ K$^{-2}$)")
            ax2_r = ax2.twinx()
            ax2_r.plot(nh_grd, curve_df["Band2_Conductivity_Fraction"] * 100.0, color="#00A087", linestyle="-.", linewidth=1.35, label="Heavy Band $\\sigma_2 / \\sigma$ (%)")
            ax2_r.set_ylim(0.0, 105.0)
            ax2_r.set_ylabel(r"Heavy-Band Share $\sigma_2 / \sigma$ (%)", color="#00A087")
            ax2_r.tick_params(axis="y", colors="#00A087", direction="in", labelsize=DEFAULT_TICK_LABEL_SIZE * 0.9)
            h1, l1 = ax2.get_legend_handles_labels()
            h2, l2 = ax2_r.get_legend_handles_labels()
            place_legend_inside(
                ax2,
                h1 + h2,
                l1 + l2,
                extra_axes=(ax2_r,),
                loc="upper left",
                fontsize=9.8,
                frameon=True,
                facecolor="white",
                edgecolor="black",
                fancybox=False,
                ylim_locked=(True, False),
                extra_ylim_locked=[(True, True)],
            )
        else:
            ax2.plot(nh_grd, curve_df["Band2_Conductivity_Fraction"] * 100.0, color="#00A087", linewidth=DEFAULT_LINE_WIDTH * 1.15, label=r"Heavy Band $\sigma_2 / \sigma$")
            ax2.plot(nh_grd, (1.0 - curve_df["Band2_Conductivity_Fraction"]) * 100.0, color=palette[1], linestyle="--", linewidth=1.45, label=r"Light Band $\sigma_1 / \sigma$")
            ax2.set_ylim(0.0, 108.0)
            ax2.set_ylabel("Conductivity Contribution (%)")
            place_legend_inside(
                ax2,
                loc="center right",
                fontsize=10.4,
                frameon=True,
                facecolor="white",
                edgecolor="black",
                fancybox=False,
                ylim_locked=(True, False),
                cap_ticks_at=100.0,
            )

        fig.tight_layout()
        return export_model_figure(fig, f"{stem_prefix}_two_band_convergence", output_dir=output_dir, formats=formats, show=show)

    if mode_name == "semimetal":
        fig, axes = plt.subplots(2, 2, figsize=(11.6, 8.8))
        t_exp = pts["Temperature_K"].to_numpy(dtype=float)

        # Panel (a): Partial & total Seebeck coefficients S_e, S_h, S_exp
        ax_s = axes[0, 0]
        ax_s.plot(t_exp, pts["Seebeck_e_uV_K"], color=FIT_RED_COLOR, marker="D", markersize=4.8, linewidth=DEFAULT_LINE_WIDTH * 1.05, label=r"Electron $S_e$", zorder=4.2)
        ax_s.plot(t_exp, pts["Seebeck_h_uV_K"], color="#00A087", marker="^", markersize=5.2, linewidth=DEFAULT_LINE_WIDTH * 1.05, label=r"Hole $S_h$", zorder=4.0)
        ax_s.scatter(t_exp, pts["Seebeck_uV_K"], s=(DEFAULT_MARKER_SIZE * 0.9) ** 2, facecolor=EXP_MARKER_FACE, edgecolor=EXP_MARKER_EDGE, linewidths=1.05, label=r"Measured Total $S$", zorder=4.5)
        ax_s.axhline(0.0, color="gray", linestyle=":", linewidth=0.9)
        s_vals = np.concatenate([pts["Seebeck_e_uV_K"].to_numpy(), pts["Seebeck_h_uV_K"].to_numpy(), pts["Seebeck_uV_K"].to_numpy()])
        s_span = max(float(np.nanmax(s_vals) - np.nanmin(s_vals)), 30.0)
        ax_s.set_ylim(float(np.nanmin(s_vals)) - 0.14 * s_span, float(np.nanmax(s_vals)) + 0.28 * s_span)
        ax_s.set_xlabel(r"$T$ (K)")
        ax_s.set_ylabel(r"$S$ ($\mu$V K$^{-1}$)")
        format_te_axis(ax_s, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.92)
        place_legend_inside(ax_s, loc="upper left", ncol=2, fontsize=9.2, frameon=True, facecolor="white", edgecolor="black", fancybox=False)

        # Panel (b): Partial drift mobilities mu_e, mu_h (+ apparent Hall mu_H if present)
        ax_m = axes[0, 1]
        ax_m.plot(t_exp, pts["Mobility_e_cm2_V-1_s-1"], color=FIT_RED_COLOR, marker="D", markersize=4.8, linewidth=DEFAULT_LINE_WIDTH * 1.05, label=r"Electron $\mu_e$", zorder=4.2)
        ax_m.plot(t_exp, pts["Mobility_h_cm2_V-1_s-1"], color="#00A087", marker="^", markersize=5.2, linewidth=DEFAULT_LINE_WIDTH * 1.05, label=r"Hole $\mu_h$", zorder=4.0)
        if "Hall_Mobility_exp_cm2_V-1_s-1" in pts.columns:
            ax_m.scatter(t_exp, pts["Hall_Mobility_exp_cm2_V-1_s-1"], s=(DEFAULT_MARKER_SIZE * 0.88) ** 2, facecolor=EXP_MARKER_FACE, edgecolor=EXP_MARKER_EDGE, linewidths=1.0, alpha=0.88, label=r"Apparent $\mu_{\mathrm{H}}$", zorder=3.8)
        ax_m.set_xlabel(r"$T$ (K)")
        ax_m.set_ylabel(r"$\mu$ (cm$^2$ V$^{-1}$ s$^{-1}$)")
        format_te_axis(ax_m, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.92)
        place_legend_inside(ax_m, loc="upper right", fontsize=9.4, frameon=True, facecolor="white", edgecolor="black", fancybox=False)

        # Panel (c): Weighted mobility ratio A & mobility ratio mu_e / mu_h
        ax_a = axes[1, 0]
        valid_a = np.isfinite(pts["Weighted_Mobility_Ratio_A"].to_numpy()) & (pts["Weighted_Mobility_Ratio_A"].to_numpy() > 0)
        if np.any(valid_a):
            ax_a.plot(t_exp[valid_a], pts["Weighted_Mobility_Ratio_A"].to_numpy()[valid_a], color=FIT_RED_COLOR, marker="o", markersize=5.0, linewidth=DEFAULT_LINE_WIDTH * 1.1, label=r"Weighted Ratio $A = (\mu_e/\mu_h)(m^*_{d,e}/m^*_{d,h})^{3/2}$")
            ax_a.plot(t_exp[valid_a], pts["Mobility_Ratio_e_over_h"].to_numpy()[valid_a], color=STAGE_NONRED_PALETTE[0], linestyle="--", marker="D", markersize=4.5, linewidth=1.45, label=r"Mobility Ratio $\mu_e / \mu_h$")
            if float(np.nanmax(pts["Weighted_Mobility_Ratio_A"].to_numpy()[valid_a]) / max(float(np.nanmin(pts["Mobility_Ratio_e_over_h"].to_numpy()[valid_a])), 0.1)) > 4.0:
                ax_a.set_yscale("log")
        ax_a.axhline(1.0, color="gray", linestyle=":", linewidth=0.9)
        ax_a.set_xlabel(r"$T$ (K)")
        ax_a.set_ylabel("Asymmetry Ratio")
        format_te_axis(ax_a, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.92)
        place_legend_inside(ax_a, loc="upper right", fontsize=9.0, frameon=True, facecolor="white", edgecolor="black", fancybox=False)

        # Panel (d): Band overlap / gap E_g(T) + Hall self-consistency R_{H,calc} / R_{H,exp}
        ax_g = axes[1, 1]
        eg_arr = pts["Band_Gap_or_Overlap_eV"].to_numpy(dtype=float)
        ax_g.plot(t_exp, eg_arr, color=FIT_RED_COLOR, marker="o", markersize=4.8, linewidth=DEFAULT_LINE_WIDTH * 1.1, label=r"$E_g(T)$ (<0: semimetal overlap)")
        ax_g.axhline(0.0, color="gray", linestyle=":", linewidth=0.9)
        eg_span = max(float(np.nanmax(eg_arr) - np.nanmin(eg_arr)), 0.06)
        ax_g.set_ylim(float(np.nanmin(eg_arr)) - 0.35 * eg_span, float(np.nanmax(eg_arr)) + 0.45 * eg_span)
        ax_g.set_xlabel(r"$T$ (K)")
        ax_g.set_ylabel(r"$E_g$ / Band Overlap (eV)")
        format_te_axis(ax_g, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.92)
        if "RH_ratio_calc_over_exp" in pts.columns:
            ax_gr = ax_g.twinx()
            ax_gr.plot(t_exp, pts["RH_ratio_calc_over_exp"], color="#3C5488", linestyle="--", linewidth=1.4, label=r"$R_{\mathrm{H,calc}} / R_{\mathrm{H,exp}}$")
            ax_gr.axhline(1.0, color="#3C5488", linestyle=":", linewidth=0.8, alpha=0.6)
            ax_gr.set_ylim(0.0, max(2.0, float(np.nanmax(pts["RH_ratio_calc_over_exp"])) * 1.25))
            ax_gr.set_ylabel(r"$R_{\mathrm{H,calc}} / R_{\mathrm{H,exp}}$", color="#3C5488")
            ax_gr.tick_params(axis="y", colors="#3C5488", direction="in", labelsize=DEFAULT_TICK_LABEL_SIZE * 0.88)
            h1, l1 = ax_g.get_legend_handles_labels()
            h2, l2 = ax_gr.get_legend_handles_labels()
            place_legend_inside(ax_g, h1 + h2, l1 + l2, extra_axes=(ax_gr,), loc="upper right", fontsize=8.8, frameon=True, facecolor="white", edgecolor="black", fancybox=False)
        else:
            place_legend_inside(ax_g, loc="upper right", fontsize=9.2, frameon=True, facecolor="white", edgecolor="black", fancybox=False)

        fig.tight_layout()
        return export_model_figure(fig, f"{stem_prefix}_two_band_semimetal", output_dir=output_dir, formats=formats, show=show)

    if mode_name == "isothermal-bipolar":
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.8, 4.9))
        nh_exp = pts["nH_cm-3"].to_numpy(dtype=float)
        nh_grd = curve_df["nH_cm-3"].to_numpy(dtype=float)

        ax1.plot(nh_grd, curve_df["Seebeck_TwoBand_uV_K"], color=FIT_RED_COLOR, linewidth=DEFAULT_LINE_WIDTH * 1.2, label="Isothermal Bipolar Fit", zorder=4.5)
        ax1.plot(nh_grd, curve_df["Seebeck_Majority_only_uV_K"], color=STAGE_NONRED_PALETTE[0], linestyle="--", linewidth=1.45, label="Majority Extrinsic SPB", zorder=3.0)
        ax1.scatter(nh_exp, pts["Seebeck_uV_K"], s=(DEFAULT_MARKER_SIZE * 0.95) ** 2, facecolor=EXP_MARKER_FACE, edgecolor=EXP_MARKER_EDGE, linewidths=1.05, alpha=0.90, label="Experimental", zorder=3.8)
        ax1.set_xscale("log")
        ax1.set_xlabel(r"$n_{\mathrm{H}}$ (cm$^{-3}$)")
        ax1.set_ylabel(r"$S$ ($\mu$V K$^{-1}$)")
        format_te_axis(ax1, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
        ax1.xaxis.set_major_locator(ticker.LogLocator(base=10.0))
        ax1.text(
            0.04,
            0.06 if fit_info["majority_carrier"] == "n-type" else 0.78,
            rf"$E_g = {fit_info['Eg_eV']:.3f}$ eV"
            + "\n"
            + rf"$A_0 = {fit_info['weighted_mobility_ratio_A0_e_over_h']:.2f}$",
            transform=ax1.transAxes,
            ha="left",
            va="bottom",
            fontsize=9.8,
            bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.92, "pad": 3.4},
        )
        place_legend_inside(ax1, loc="best", fontsize=9.6, frameon=True, facecolor="white", edgecolor="black", fancybox=False)

        # Panel (b): 2D Seebeck contour map S(A_0, n_e) at fixed (T, E_g) (cf. Mao et al. Figs. S10-S12)
        a_grid = np.logspace(-1.0, 1.3, 90)
        eta_e_map = np.linspace(-3.5, 10.0, 95)
        t_iso = float(fit_info["Temperature_K"])
        eg_iso = float(fit_info["Eg_eV"])
        eg_red_iso = (eg_iso * e) / (k * t_iso)
        m_e_map = fit_info["m_maj_dos_over_me"] if fit_info["majority_carrier"] == "n-type" else fit_info["m_min_dos_over_me"]
        r_iso = float(fit_info["scattering_r"])

        st_e_1d = _eval_parabolic_or_acoustic_band(eta_e_map, temperature_k=t_iso, mstar_dos_ratio=m_e_map, mu0_cm2_vs=1.0, carrier_sign=-1, scattering_r=r_iso)
        st_h_1d = _eval_parabolic_or_acoustic_band(-eta_e_map - eg_red_iso, temperature_k=t_iso, mstar_dos_ratio=m_e_map, mu0_cm2_vs=1.0, carrier_sign=+1, scattering_r=r_iso)
        ne_cm3_1d = st_e_1d["n_cm-3"]
        se_1d = st_e_1d["Seebeck_uV_K"][:, None]
        sh_1d = st_h_1d["Seebeck_uV_K"][:, None]
        # Exact ratio sigma_e / sigma_h = A_0 * (sigma_e(mu0=1, m*=1) / sigma_h(mu0=1, m*=1))
        sig_ratio_base = (st_e_1d["Conductivity_S_m-1"] / np.maximum(st_h_1d["Conductivity_S_m-1"], 1e-300))[:, None]
        sig_e_over_h = sig_ratio_base * a_grid[None, :]
        s_map = (sig_e_over_h * se_1d + sh_1d) / (sig_e_over_h + 1.0)

        cf = ax2.contourf(a_grid, ne_cm3_1d, s_map, levels=20, cmap=resolve_cmap("soft-br"))
        cbar = fig.colorbar(cf, ax=ax2, pad=0.02)
        cbar.set_label(r"$S$ ($\mu$V K$^{-1}$)", fontsize=10.0)
        a0_val = float(fit_info["weighted_mobility_ratio_A0_e_over_h"])
        if 0.1 <= a0_val <= 20.0:
            ax2.axvline(a0_val, color=FIT_RED_COLOR, linestyle="--", linewidth=1.6, label=rf"Fitted $A_0 = {a0_val:.2f}$")
            ax2.legend(loc="upper right", fontsize=9.2, frameon=True, facecolor="white", edgecolor="black", fancybox=False)
        ax2.set_xscale("log")
        ax2.set_yscale("log")
        ax2.set_ylim(max(float(ne_cm3_1d.min()), 2e18), min(float(ne_cm3_1d.max()), 1.5e20))
        ax2.set_xlabel(r"Electron-to-Hole Weighted Mobility Ratio $A_0$")
        ax2.set_ylabel(r"Electron Concentration $n_e$ (cm$^{-3}$)")
        format_te_axis(ax2, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.92)
        fig.tight_layout()
        return export_model_figure(fig, f"{stem_prefix}_two_band_isothermal_bipolar", output_dir=output_dir, formats=formats, show=show)

    # --- Bipolar 3-panel figure: S(T), sigma(T), kappa(T) decomposition ---
    has_kappa = "kappa_total_model_W_m-1_K-1" in curve_df.columns
    n_cols = 3 if has_kappa else 2
    fig, axes = plt.subplots(1, n_cols, figsize=(14.6 if has_kappa else 10.6, 4.7))
    t_exp = pts["Temperature_K"].to_numpy(dtype=float)
    t_grd = curve_df["Temperature_K"].to_numpy(dtype=float)

    ax_s = axes[0]
    ax_s.plot(t_grd, curve_df["Seebeck_TwoBand_uV_K"], color=FIT_RED_COLOR, linewidth=DEFAULT_LINE_WIDTH * 1.2, label="Bipolar Two-Band Fit", zorder=4.5)
    ax_s.plot(t_grd, curve_df["Seebeck_Extrinsic_Majority_uV_K"], color=STAGE_NONRED_PALETTE[0], linestyle="--", linewidth=1.4, label="Majority Extrinsic Only", zorder=3)
    ax_s.scatter(t_exp, pts["Seebeck_uV_K"], s=(DEFAULT_MARKER_SIZE * 0.9) ** 2, facecolor=EXP_MARKER_FACE, edgecolor=EXP_MARKER_EDGE, linewidths=1.05, alpha=0.90, label="Experimental", zorder=3.8)
    s_all = np.concatenate([pts["Seebeck_uV_K"].to_numpy(), curve_df["Seebeck_Extrinsic_Majority_uV_K"].to_numpy()])
    s_span = max(float(s_all.max() - s_all.min()), 20.0)
    ax_s.set_ylim(float(s_all.min()) - 0.14 * s_span, float(s_all.max()) + 0.34 * s_span)
    ax_s.set_xlabel(r"$T$ (K)")
    ax_s.set_ylabel(r"$S$ ($\mu$V K$^{-1}$)")
    format_te_axis(ax_s, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.92)
    ax_s.text(
        0.05,
        0.06,
        rf"$E_{{\mathrm{{g,0}}}} = {fit_info['fitted_Eg0_eV']:.3f}$ eV"
        + "\n"
        + rf"$A_0 = {fit_info['weighted_mobility_ratio_A0_e_over_h']:.2f}$ ($E_{{\mathrm{{g}}}}^{{\mathrm{{GS}}}} = {fit_info['goldsmid_sharp_Eg_eV']:.2f}$ eV)",
        transform=ax_s.transAxes,
        ha="left",
        va="bottom",
        fontsize=9.4,
        bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.92, "pad": 3.4},
    )
    place_legend_inside(ax_s, loc="best", fontsize=9.6, frameon=True, facecolor="white", edgecolor="black", fancybox=False)

    ax_c = axes[1]
    ax_c.plot(t_grd, curve_df["Conductivity_Total_S_cm-1"], color=FIT_RED_COLOR, linewidth=DEFAULT_LINE_WIDTH * 1.2, label="Total $\\sigma$ Fit", zorder=4.5)
    ax_c.plot(t_grd, curve_df["Conductivity_Majority_S_cm-1"], color=STAGE_NONRED_PALETTE[0], linestyle="--", linewidth=1.35, label="Majority $\\sigma_{\\mathrm{maj}}$", zorder=3)
    ax_c.plot(t_grd, curve_df["Conductivity_Minority_S_cm-1"], color="#00A087", linestyle="-.", linewidth=1.35, label="Minority $\\sigma_{\\mathrm{min}}$", zorder=3)
    ax_c.scatter(t_exp, pts["Conductivity_exp_S_cm-1"], s=(DEFAULT_MARKER_SIZE * 0.9) ** 2, facecolor=EXP_MARKER_FACE, edgecolor=EXP_MARKER_EDGE, linewidths=1.05, alpha=0.90, label="Experimental", zorder=3.8)
    sig_top = max(float(pts["Conductivity_exp_S_cm-1"].max()), float(curve_df["Conductivity_Total_S_cm-1"].max()))
    ax_c.set_ylim(0.0, sig_top * 1.34)
    ax_c.set_xlabel(r"$T$ (K)")
    ax_c.set_ylabel(r"$\sigma$ (S cm$^{-1}$)")
    format_te_axis(ax_c, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.92)
    place_legend_inside(ax_c, loc="upper right", fontsize=9.8, frameon=True, facecolor="white", edgecolor="black", fancybox=False, ylim_locked=(True, False))

    if has_kappa:
        ax_k = axes[2]
        ax_k.plot(t_grd, curve_df["kappa_total_model_W_m-1_K-1"], color=FIT_RED_COLOR, linewidth=DEFAULT_LINE_WIDTH * 1.2, label=r"Total $\kappa$ Fit", zorder=4.5)
        ax_k.plot(t_grd, curve_df["kappa_L_model_W_m-1_K-1"], color=STAGE_NONRED_PALETTE[0], linestyle="--", linewidth=1.4, label=r"Phonon $\kappa_{\mathrm{L}}$", zorder=3)
        ax_k.plot(t_grd, curve_df["kappa_bipolar_W_m-1_K-1"], color=STAGE_NONRED_PALETTE[2], linestyle="-.", linewidth=1.45, label=r"Bipolar $\kappa_{\mathrm{bi}}$", zorder=3.5)
        ax_k.fill_between(t_grd, 0.0, curve_df["kappa_bipolar_W_m-1_K-1"], color=STAGE_NONRED_PALETTE[2], alpha=0.16, zorder=1.8)
        ax_k.plot(t_grd, curve_df["kappa_e_W_m-1_K-1"], color="#00A087", linestyle=":", linewidth=1.35, label=r"Carrier $\kappa_{\mathrm{e}}$", zorder=2.8)
        ax_k.scatter(t_exp, pts["Thermal_Conductivity_exp_W_m-1_K-1"], s=(DEFAULT_MARKER_SIZE * 0.9) ** 2, facecolor=EXP_MARKER_FACE, edgecolor=EXP_MARKER_EDGE, linewidths=1.05, alpha=0.90, label=r"Exp. $\kappa_{\mathrm{tot}}$", zorder=3.8)
        k_top = max(float(pts["Thermal_Conductivity_exp_W_m-1_K-1"].max()), float(curve_df["kappa_total_model_W_m-1_K-1"].max()))
        ax_k.set_ylim(0.0, k_top * 1.34)
        ax_k.set_xlabel(r"$T$ (K)")
        ax_k.set_ylabel(r"$\kappa$ (W m$^{-1}$ K$^{-1}$)")
        format_te_axis(ax_k, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.92)
        place_legend_inside(ax_k, loc="upper right", fontsize=9.6, frameon=True, facecolor="white", edgecolor="black", fancybox=False, ylim_locked=(True, False))

    fig.tight_layout()
    return export_model_figure(fig, f"{stem_prefix}_two_band_bipolar", output_dir=output_dir, formats=formats, show=show)


def run_two_band_workflow(
    input_csv: str | os.PathLike[str],
    *,
    mode: str = "auto",
    output_dir: str | os.PathLike[str] | None = None,
    temperature_k: float = 300.0,
    band1_eg_ev: float | None = None,
    fix_m1: float | None = None,
    fix_m2: float | None = None,
    fix_delta_e: float | None = None,
    fix_mu1: float | None = None,
    fix_b: float | None = None,
    fix_eg0: float | None = None,
    fix_n_dop_cm3: float | None = None,
    fix_mu_imp: float | None = None,
    beta_eg_ev_k: float = 0.0,
    acoustic_p: float = 1.5,
    scattering_r: float = -0.5,
    allow_semimetal: bool = False,
    matthiessen: bool = False,
    fit_nh: bool = False,
    semimetal_closure: str = "auto",
    nh_unit: str = "cm^-3",
    sigma_unit: str = "auto",
    formats: Sequence[str] = ("svg",),
    color_set: str | None = None,
    rename: str | None = None,
    copy_to_data_dir: bool = True,
    show: bool = False,
) -> dict[str, Any]:
    df = read_tabular_data(input_csv)
    resolved_mode = mode.strip().lower()
    if resolved_mode == "auto":
        has_nh = (
            find_column(df, None, NH_CANDIDATES, required=False) is not None
            or find_column(df, None, HALL_COEFF_CANDIDATES, required=False) is not None
        )
        has_t = find_column(df, None, TEMPERATURE_CANDIDATES, required=False) is not None
        resolved_mode = "bipolar" if has_t else ("convergence" if has_nh else "convergence")

    if resolved_mode in {"convergence", "isothermal", "valence", "conduction", "pisarenko"}:
        pts, curve_df, fit_info = fit_two_band_convergence(
            df,
            temperature_k=temperature_k,
            band1_eg_ev=band1_eg_ev,
            fix_m1=fix_m1,
            fix_m2=fix_m2,
            fix_delta_e=fix_delta_e,
            fix_mu1=fix_mu1,
            fix_b=fix_b,
            nh_unit=nh_unit,
            sigma_unit=sigma_unit,
        )
    elif resolved_mode in {"bipolar", "temperature", "eh", "intrinsic"}:
        pts, curve_df, fit_info = fit_two_band_bipolar(
            df,
            fix_eg0=fix_eg0,
            fix_m_maj=fix_m1,
            fix_m_min=fix_m2,
            fix_n_dop_cm3=fix_n_dop_cm3,
            fix_b=fix_b,
            fix_mu_imp=fix_mu_imp,
            beta_eg_ev_k=beta_eg_ev_k,
            acoustic_p=acoustic_p,
            scattering_r=scattering_r,
            allow_semimetal=allow_semimetal,
            matthiessen=matthiessen,
            fit_nh=fit_nh,
            nh_unit=nh_unit,
            sigma_unit=sigma_unit,
        )
    elif resolved_mode in {"semimetal", "hall-inversion", "semimetal-invert", "inversion"}:
        pts, curve_df, fit_info = invert_two_band_semimetal(
            df,
            m_e_dos=fix_m1,
            m_h_dos=fix_m2,
            n_dop_cm3=float(fix_n_dop_cm3) if fix_n_dop_cm3 is not None else 0.0,
            fix_eg0=fix_eg0,
            beta_eg_ev_k=beta_eg_ev_k,
            closure=semimetal_closure,
            scattering_r=scattering_r,
            nh_unit=nh_unit,
            sigma_unit=sigma_unit,
        )
    elif resolved_mode in {"isothermal-bipolar", "bipolar-pisarenko", "asymmetry"}:
        pts, curve_df, fit_info = fit_two_band_isothermal_bipolar(
            df,
            temperature_k=temperature_k,
            fix_m1=fix_m1,
            fix_m2=fix_m2,
            fix_eg0=fix_eg0,
            fix_mu1=fix_mu1,
            fix_b=fix_b,
            scattering_r=scattering_r,
            nh_unit=nh_unit,
            sigma_unit=sigma_unit,
        )
    else:
        raise ValueError(f"Unknown two-band mode: {mode!r}")

    from te_analysis.paths import get_workspace

    out_path = Path(output_dir) if output_dir is not None else get_workspace().model_output_dir("two_band")
    out_path.mkdir(parents=True, exist_ok=True)
    stem = Path(input_csv).stem
    tag = fit_info["mode"].replace("-", "_")
    pts_csv = out_path / f"{stem}_two_band_{tag}_points.csv"
    crv_csv = out_path / f"{stem}_two_band_{tag}_curve.csv"
    pts.to_csv(pts_csv, index=False)
    curve_df.to_csv(crv_csv, index=False)

    with figure_output_naming(rename):
        fig_paths = render_two_band_figures(
            pts,
            curve_df,
            fit_info,
            output_dir=out_path,
            stem_prefix=stem,
            formats=formats,
            color_set=color_set,
            show=show,
        )

    copied = copy_figures_beside_input(fig_paths, input_csv) if copy_to_data_dir else []
    summary = {
        "model": f"Two-Band ({fit_info['mode']})",
        "input_csv": str(Path(input_csv).resolve()),
        "fit": fit_info,
        "outputs": {
            "points_csv": str(pts_csv),
            "curve_csv": str(crv_csv),
            "figures": fig_paths,
            "data_dir_figures": copied,
        },
    }
    sum_json = save_json_clean(summary, out_path / f"{stem}_two_band_{tag}_summary.json")
    summary["outputs"]["summary_json"] = str(sum_json)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Fit or decompose Two-Band thermoelectric models (`convergence`, `bipolar`, "
            "`semimetal`, or `isothermal-bipolar`) with collinearity diagnostics."
        )
    )
    p.add_argument("input_csv", help="Input CSV/TSV/XLSX (isothermal nH-S-sigma series or T-S-sigma/rho[-nH/RH-kappa] curve).")
    p.add_argument(
        "--mode",
        default="auto",
        choices=(
            "auto",
            "convergence",
            "isothermal",
            "bipolar",
            "temperature",
            "semimetal",
            "hall-inversion",
            "semimetal-invert",
            "isothermal-bipolar",
            "bipolar-pisarenko",
            "asymmetry",
        ),
        help=(
            "Two-band physical regime: 'convergence' (same-sign light+heavy vs nH), "
            "'bipolar' (e+h global T-fit across E_g >=< 0), 'semimetal' (point-by-point e+h Hall+S+sigma inversion vs T), "
            "or 'isothermal-bipolar' (e+h Pisarenko & weighted-mobility A map vs nH). Default: auto."
        ),
    )
    from te_analysis.paths import get_workspace

    p.add_argument(
        "-o",
        "--output-dir",
        default=str(get_workspace().model_output_dir("two_band")),
        help="Output folder.",
    )
    p.add_argument("-T", "--temperature", type=float, default=300.0, help="Isothermal temperature in K for convergence / isothermal-bipolar modes (default: 300).")
    p.add_argument("--band1-eg", type=float, default=None, help="Optional Kane bandgap E_g (eV) for light Band 1 in convergence mode.")
    p.add_argument("--fix-m1", type=float, default=None, help="Pin Band 1 DOS mass m*_1 / m_e (light band in convergence, majority in bipolar, electrons in semimetal).")
    p.add_argument("--fix-m2", type=float, default=None, help="Pin Band 2 DOS mass m*_2 / m_e (heavy band in convergence, minority in bipolar, holes in semimetal).")
    p.add_argument("--fix-delta-e", type=float, default=None, help="Pin band offset Delta E (eV) in convergence mode.")
    p.add_argument("--fix-mu1", type=float, default=None, help="Pin Band 1 / majority intrinsic mobility mu0_1 (cm^2/Vs).")
    p.add_argument("--fix-b", type=float, default=None, help="Pin mobility ratio b (mu1/mu2 in convergence; mu_min/mu_maj in bipolar / isothermal-bipolar).")
    p.add_argument("--fix-eg0", type=float, default=None, help="Pin 0 K (or isothermal) bandgap / band overlap E_g0 in eV (negative for semimetal overlap).")
    p.add_argument("--fix-ndop", type=float, default=None, help="Pin net extrinsic doping N_dop = n_maj - n_min (cm^-3; pass 0 for undoped semimetal n_e=n_h).")
    p.add_argument("--fix-mu-imp", type=float, default=None, help="Pin T-independent defect/impurity mobility limit mu_imp (cm^2/Vs) in bipolar Matthiessen mode.")
    p.add_argument("--beta-eg", type=float, default=0.0, help="Linear temperature coefficient dE_g/dT (eV/K) in bipolar / semimetal fixed-gap modes.")
    p.add_argument("--acoustic-p", type=float, default=1.5, help="Phonon mobility temperature exponent mu_ac ~ T^-p in bipolar mode (default: 1.5).")
    p.add_argument("--scattering-r", type=float, default=-0.5, help="Boltzmann energy-relaxation exponent r in tau(E) = tau_0 E^r (default: -0.5 for acoustic phonons; 0.0 for neutral defects).")
    p.add_argument("--allow-semimetal", action="store_true", help="Allow negative bandgap E_g0 < 0 (band-overlapping semimetal) in bipolar global fit.")
    p.add_argument("--matthiessen", action="store_true", help="Include T-independent defect scattering 1/mu0(T) = 1/mu_imp + (1/mu_300)*(T/300)^p in bipolar mode.")
    p.add_argument("--fit-nh", action="store_true", help="Jointly fit apparent Hall concentration n_H(T) when an nH/RH column is present in bipolar mode.")
    p.add_argument(
        "--semimetal-closure",
        default="auto",
        choices=("auto", "hall-split", "fixed-gap"),
        help="Carrier-density closure in semimetal mode: 'hall-split' (n_e+n_h=n_H,exp) or 'fixed-gap' (uses --fix-eg0).",
    )
    p.add_argument("--nh-unit", default="cm^-3", choices=("cm^-3", "m^-3"), help="Unit of nH column.")
    p.add_argument("--sigma-unit", default="auto", choices=("auto", "S/cm", "S/m"), help="Unit of electrical conductivity.")
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
    try:
        summary = run_two_band_workflow(
            args.input_csv,
            mode=args.mode,
            output_dir=args.output_dir,
            temperature_k=args.temperature,
            band1_eg_ev=args.band1_eg,
            fix_m1=args.fix_m1,
            fix_m2=args.fix_m2,
            fix_delta_e=args.fix_delta_e,
            fix_mu1=args.fix_mu1,
            fix_b=args.fix_b,
            fix_eg0=args.fix_eg0,
            fix_n_dop_cm3=args.fix_ndop,
            fix_mu_imp=args.fix_mu_imp,
            beta_eg_ev_k=args.beta_eg,
            acoustic_p=args.acoustic_p,
            scattering_r=args.scattering_r,
            allow_semimetal=args.allow_semimetal,
            matthiessen=args.matthiessen,
            fit_nh=args.fit_nh,
            semimetal_closure=args.semimetal_closure,
            nh_unit=args.nh_unit,
            sigma_unit=args.sigma_unit,
            formats=formats,
            color_set=args.color_set,
            rename=args.rename,
            copy_to_data_dir=not args.no_copy_to_data_dir,
            show=not args.no_show,
        )
    except MissingMaterialParametersError as exc:
        print(f"Missing required physical parameters:\n{exc}", file=sys.stderr)
        return 2

    fit = summary["fit"]
    mode_tag = fit["mode"]
    if mode_tag == "convergence":
        print(
            f"Two-Band (convergence) fit -> m*_1={fit['m1_dos_over_me']:.2f} m_e, m*_2={fit['m2_dos_over_me']:.2f} m_e, "
            f"Delta_E={fit['delta_E_eV']:.3f} eV, b={fit['b_mu1_over_mu2']:.2f}, RMSE(|S|)={fit['seebeck_rmse_uV_K']:.2f} uV/K"
        )
    elif mode_tag == "semimetal":
        mu_rat = fit["mu_e_over_mu_h_at_ref_T"]
        a_rat = fit["weighted_mobility_ratio_A_at_ref_T"]
        rat_str = f"mu_e/mu_h={mu_rat:.2f}, A={a_rat:.2f}" if (mu_rat is not None and a_rat is not None) else "unphysical mobility sign"
        print(
            f"Two-Band (semimetal:{fit['closure']}) @ {fit['reference_T_K']:.0f} K -> "
            f"E_g={fit['Eg_at_ref_T_eV']:+.3f} eV, S_e={fit['Se_at_ref_T_uV_K']:.1f} uV/K, S_h={fit['Sh_at_ref_T_uV_K']:+.1f} uV/K, "
            f"mu_e={fit['mu_e_at_ref_T_cm2_Vs']:.1f}, mu_h={fit['mu_h_at_ref_T_cm2_Vs']:.1f} cm^2/Vs ({rat_str})"
        )
    elif mode_tag == "isothermal-bipolar":
        print(
            f"Two-Band (isothermal-bipolar) fit -> E_g={fit['Eg_eV']:+.3f} eV, "
            f"b={fit['b_mu_min_over_maj']:.2f}, A_0={fit['weighted_mobility_ratio_A0_e_over_h']:.2f}, "
            f"RMSE(S)={fit['seebeck_rmse_uV_K']:.2f} uV/K"
        )
    else:
        print(
            f"Two-Band (bipolar) fit -> E_g0={fit['fitted_Eg0_eV']:+.3f} eV (GS={fit['goldsmid_sharp_Eg_eV']:.3f} eV), "
            f"N_dop={fit['n_dop_cm-3']:.2e} cm^-3, b={fit['b_mu_min_over_maj']:.2f}, "
            f"A_0={fit['weighted_mobility_ratio_A0_e_over_h']:.2f}, RMSE(S)={fit['seebeck_rmse_uV_K']:.2f} uV/K"
        )
    for w in fit.get("diagnostics", {}).get("identifiability_warnings", []):
        print(f"warning: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

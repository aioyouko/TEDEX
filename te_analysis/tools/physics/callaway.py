#!/usr/bin/env python3
"""Debye-Callaway & Cahill-minimum lattice thermal conductivity fitting and spectral/MFP analysis.

Supports multi-mechanism Matthiessen phonon scattering rates:
  - Umklapp (U):         tau_U^-1 = B * omega^2 * T * exp(-Theta_D / (3 T))
  - Grain Boundary (GB): tau_B^-1 = v_s / L_grain
  - Point Defect (PD):   tau_PD^-1 = A * omega^4   (with disorder Gamma if V_0 given)
  - Dislocations (D):    tau_D^-1 = D_strain * omega + D_core * omega^3  (parameterized by N_D)
  - Nanoprecipitates:    tau_NP^-1 = v_s * n_p / (1/sigma_s(omega) + 1/sigma_l)
  - Rattler / Resonant:  tau_R^-1 = C_R * omega^2 / ((omega_0^2 - omega^2)^2 + (gamma_R omega_0 omega)^2)

Also computes:
  - Optional full Callaway Normal-scattering correction (beta_N = tau_N^-1 / tau_U^-1)
  - Cahill-Watson-Pohl amorphous minimum thermal conductivity kappa_min(T)
  - Spectral thermal conductivity kappa_s(omega / omega_D) & cumulative kappa_cum(Lambda) vs MFP
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from numpy.polynomial.legendre import leggauss
from scipy.constants import hbar, k
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import ticker  # noqa: E402

from te_analysis.tools.physics.debye_calc import (  # noqa: E402
    MissingDebyeParametersError,
    debye_from_heat_capacity,
    debye_from_ultrasonic,
    format_missing_debye_prompt,
    interactive_prompt_debye_params,
)
from te_analysis.tools.physics.io_plot import (  # noqa: E402
    CONDUCTIVITY_CANDIDATES,
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_LINE_WIDTH,
    DEFAULT_MARKER_SIZE,
    DEFAULT_SUBPLOT_ASPECT,
    DEFAULT_SUBPLOT_HEIGHT,
    DEFAULT_TICK_LABEL_SIZE,
    EXP_MARKER_EDGE,
    EXP_MARKER_FACE,
    FIT_RED_COLOR,
    KAPPA_L_CANDIDATES,
    KAPPA_TOT_CANDIDATES,
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
    figure_size_for_subplot_aspect,
    find_column,
    format_te_axis,
    get_colors,
    infer_conductivity_s_m,
    infer_seebeck_uv_k,
    normalize_output_formats,
    place_legend_inside,
    read_tabular_data,
    save_json_clean,
)
from te_analysis.tools.physics.lorenz import (  # noqa: E402
    calculate_generalized_fermi_level,
    calculate_lorenz_number,
)

_GL_NODES, _GL_WEIGHTS = leggauss(96)
_U01 = 0.5 * (_GL_NODES + 1.0)
_W01 = 0.5 * _GL_WEIGHTS


def debye_heat_kernel(x: np.ndarray) -> np.ndarray:
    """Overflow-free evaluation of x^4 * exp(x) / (exp(x) - 1)^2 for x >= 0."""
    x_arr = np.asarray(x, dtype=float)
    small = x_arr < 1e-4
    safe_x = np.where(small, 1.0, x_arr)
    half_term = safe_x * safe_x * np.exp(-0.5 * safe_x) / (-np.expm1(-safe_x))
    return np.where(small, x_arr * x_arr * (1.0 - (x_arr * x_arr) / 12.0), half_term * half_term)


def cahill_heat_kernel(x: np.ndarray) -> np.ndarray:
    """Overflow-free evaluation of x^3 * exp(x) / (exp(x) - 1)^2 for Cahill kappa_min."""
    x_arr = np.asarray(x, dtype=float)
    small = x_arr < 1e-4
    safe_x = np.where(small, 1.0, x_arr)
    denom = -np.expm1(-safe_x)
    large_val = (safe_x**3) * np.exp(-safe_x) / (denom * denom)
    return np.where(small, x_arr * (1.0 - (x_arr * x_arr) / 12.0), large_val)


@dataclass
class CallawayMaterialParams:
    theta_d_k: float = 210.0
    sound_velocity_m_s: float = 2200.0
    atomic_volume_a3: float | None = None  # Angstrom^3 per atom; if None, inferred from Debye sphere
    gruneisen_gamma: float = 1.6
    np_density_contrast: float = 0.25  # |Delta rho / rho| for nanoprecipitate Rayleigh scattering
    rattler_damping: float = 0.0  # 0.0 -> standard Pohl undamped resonant dip; >0 -> Lorentzian damping
    normal_ratio_beta: float = 0.0  # tau_N^-1 / tau_U^-1 (0 -> standard Klemens-Callaway)
    umklapp_div: float = 3.0  # b_U in exp(-Theta_D / (b_U * T)); papers commonly use 2.0 or 3.0

    def resolved_atomic_volume_m3(self) -> float:
        if self.atomic_volume_a3 is not None and self.atomic_volume_a3 > 0:
            return float(self.atomic_volume_a3) * 1e-30
        # Exact Debye relation: omega_D = v_s * (6 pi^2 / V_0)^(1/3) = k_B Theta_D / hbar
        omega_d = k * self.theta_d_k / hbar
        return float(6.0 * (math.pi**2) * ((self.sound_velocity_m_s / omega_d) ** 3))


@dataclass
class CallawayScatteringParams:
    b_umklapp_1e18_s_k: float = 2.5  # B in 10^-18 s K^-1
    umklapp_exp_k: float | None = None  # Optional free C_U (K) in exp(-C_U / T); if None uses Theta_D / umklapp_div
    grain_size_nm: float = 2500.0  # L in nm
    a_pd_1e41_s3: float = 1.5  # A in 10^-41 s^3
    ep_e_1e3: float = 0.0  # Ziman electron-phonon / planar fault tau_EP^-1 = (ep_e_1e3 * 1e-3) * omega
    dislocation_density_1e11_cm2: float = 0.0  # N_D in 10^11 cm^-2 (= 10^15 m^-2)
    np_volume_fraction: float = 0.0  # f_v dimensionless (0..0.2)
    np_radius_nm: float = 4.0  # R_p in nm
    rattler_c_1e35_s3: float = 0.0  # C_R in 10^35 s^-3
    rattler_theta_e_k: float = 40.0  # Theta_E in K


def scattering_rates_components(
    omega: np.ndarray,
    temperature_k: np.ndarray | float,
    mat: CallawayMaterialParams,
    scat: CallawayScatteringParams,
) -> dict[str, np.ndarray]:
    """Compute individual scattering rates tau_i^-1(omega, T) [s^-1]."""
    temp = np.asarray(temperature_k, dtype=float)
    w2 = omega * omega
    w4 = w2 * w2

    # 1. Umklapp
    b_si = max(float(scat.b_umklapp_1e18_s_k), 1e-9) * 1e-18
    c_u = float(scat.umklapp_exp_k) if (scat.umklapp_exp_k is not None and scat.umklapp_exp_k > 0) else (
        mat.theta_d_k / max(float(mat.umklapp_div), 0.1)
    )
    rate_u = b_si * w2 * temp * np.exp(-c_u / np.maximum(temp, 0.5))

    # 2. Grain boundary
    l_m = max(float(scat.grain_size_nm), 0.2) * 1e-9
    rate_gb = np.full_like(omega, mat.sound_velocity_m_s / l_m, dtype=float)

    # 3. Point defect
    a_si = max(float(scat.a_pd_1e41_s3), 0.0) * 1e-41
    rate_pd = a_si * w4

    # 3b. Electron-phonon / planar stacking-fault (Ziman linear-omega acoustic scattering)
    c_ep = max(float(scat.ep_e_1e3), 0.0) * 1e-3
    rate_ep = c_ep * omega if c_ep > 0.0 else np.zeros_like(omega)

    # 4. Dislocation core + strain
    nd_m2 = max(float(scat.dislocation_density_1e11_cm2), 0.0) * 1e15
    if nd_m2 > 0.0:
        v0_m3 = mat.resolved_atomic_volume_m3()
        burgers = v0_m3 ** (1.0 / 3.0)
        rate_d_core = 0.55 * (v0_m3 ** (4.0 / 3.0)) / (mat.sound_velocity_m_s**2) * nd_m2 * (omega**3)
        rate_d_strain = 0.06 * (burgers**2) * (mat.gruneisen_gamma**2) * nd_m2 * omega
        rate_d = rate_d_core + rate_d_strain
    else:
        rate_d = np.zeros_like(omega)

    # 5. Nanoprecipitate Rayleigh-to-geometric crossover
    fv = max(float(scat.np_volume_fraction), 0.0)
    if fv > 0.0:
        rp_m = max(float(scat.np_radius_nm), 0.3) * 1e-9
        vol_p = (4.0 / 3.0) * math.pi * (rp_m**3)
        np_m3 = fv / vol_p
        sigma_l = 2.0 * math.pi * (rp_m**2)
        sigma_s = (4.0 / 9.0) * math.pi * (rp_m**2) * (mat.np_density_contrast**2) * ((omega * rp_m / mat.sound_velocity_m_s) ** 4)
        sigma_eff = 1.0 / (1.0 / np.maximum(sigma_s, 1e-60) + 1.0 / sigma_l)
        rate_np = mat.sound_velocity_m_s * np_m3 * sigma_eff
    else:
        rate_np = np.zeros_like(omega)

    # 6. Resonant / Rattler (C_R in 10^35 s^-3 -> tau_R^-1 ~ 10^10-10^12 s^-1 near omega_0)
    c_r = max(float(scat.rattler_c_1e35_s3), 0.0) * 1e35
    if c_r > 0.0:
        w0 = k * max(float(scat.rattler_theta_e_k), 1.0) / hbar
        damp = (mat.rattler_damping * w0 * omega) ** 2
        rate_r = c_r * w2 / np.maximum((w0 * w0 - w2) ** 2 + damp, 1e-30)
    else:
        rate_r = np.zeros_like(omega)

    return {
        "U": rate_u,
        "GB": rate_gb,
        "PD": rate_pd,
        "EP": rate_ep,
        "D": rate_d,
        "NP": rate_np,
        "R": rate_r,
    }


def callaway_kappa_l(
    temperatures_k: Sequence[float] | np.ndarray,
    mat: CallawayMaterialParams,
    scat: CallawayScatteringParams,
    *,
    active_mechanisms: Sequence[str] = ("U", "GB", "PD", "EP", "D", "NP", "R"),
) -> np.ndarray:
    """Evaluate Debye-Callaway lattice thermal conductivity kappa_L(T) [W m^-1 K^-1].

    Uses active thermal window truncation min(Theta_D / T, 46.0) since x^4 e^x / (e^x - 1)^2 < 1e-13
    for x > 46, preserving full 96-node precision down to cryogenic temperatures (0.5 K - 2000 K).
    """
    t_arr = np.atleast_1d(np.asarray(temperatures_k, dtype=float))
    x_eff_max = np.minimum(mat.theta_d_k / np.maximum(t_arr, 0.3), 46.0)[:, None]  # (N_T, 1)
    x = x_eff_max * _U01[None, :]  # (N_T, 96)
    omega = (k * t_arr[:, None] / hbar) * x

    comps = scattering_rates_components(omega, t_arr[:, None], mat, scat)
    total_rate = np.zeros_like(omega)
    for mech in active_mechanisms:
        if mech in comps:
            total_rate = total_rate + comps[mech]

    if mat.normal_ratio_beta > 0.0 and "U" in active_mechanisms:
        rate_n = mat.normal_ratio_beta * comps["U"]
        total_rate_c = total_rate + rate_n
    else:
        rate_n = None
        total_rate_c = total_rate

    tau_c = 1.0 / np.maximum(total_rate_c, 1e-30)
    kernel = debye_heat_kernel(x)
    prefactor = (k / (2.0 * (math.pi**2) * mat.sound_velocity_m_s)) * ((k * t_arr / hbar) ** 3)

    i1 = np.sum(tau_c * kernel * _W01[None, :], axis=1) * x_eff_max[:, 0]
    if rate_n is not None:
        ratio_cn = tau_c * rate_n
        i2 = np.sum(ratio_cn * kernel * _W01[None, :], axis=1) * x_eff_max[:, 0]
        i3 = np.sum(rate_n * (1.0 - ratio_cn) * kernel * _W01[None, :], axis=1) * x_eff_max[:, 0]
        corr = np.where(i3 > 1e-30, (i2 * i2) / np.maximum(i3, 1e-30), 0.0)
        return prefactor * (i1 + corr)
    return prefactor * i1


def cahill_minimum_kappa(
    temperatures_k: Sequence[float] | np.ndarray,
    mat: CallawayMaterialParams,
) -> np.ndarray:
    """Compute Cahill-Watson-Pohl amorphous minimum thermal conductivity kappa_min(T) [W m^-1 K^-1]."""
    t_arr = np.atleast_1d(np.asarray(temperatures_k, dtype=float))
    v0_m3 = mat.resolved_atomic_volume_m3()
    n_a = 1.0 / v0_m3
    # Using average sound velocity v_s across 3 acoustic branches (sum_i v_i = 3 v_s)
    theta_cut = mat.theta_d_k
    x_max = (theta_cut / np.maximum(t_arr, 0.5))[:, None]
    x = x_max * _U01[None, :]
    integ = np.sum(cahill_heat_kernel(x) * _W01[None, :], axis=1) * x_max[:, 0]
    pref = ((math.pi / 6.0) ** (1.0 / 3.0)) * k * (n_a ** (2.0 / 3.0)) * (3.0 * mat.sound_velocity_m_s)
    return pref * ((t_arr / theta_cut) ** 2) * integ


def spectral_and_mfp_profile(
    temperature_k: float,
    mat: CallawayMaterialParams,
    scat: CallawayScatteringParams,
    cumulative_stages: Sequence[tuple[str, Sequence[str]]],
    n_grid: int = 500,
    spectral_norm: str = "u",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compute spectral thermal conductivity kappa_s and cumulative kappa(MFP).

    - `spectral_norm="u"`: kappa_L = int_0^1 kappa_s d(omega / omega_D)
    - `spectral_norm="x"`: kappa_L = int_0^{Theta_D/T} kappa_s d(hbar*omega / k_B*T) (standard literature integrand)
    """
    u_base = np.linspace(1e-4, 1.0, n_grid)
    if scat.rattler_c_1e35_s3 > 0.0 and mat.theta_d_k > 0.0:
        u_res = float(scat.rattler_theta_e_k / mat.theta_d_k)
        if 1e-4 < u_res < 1.0:
            # Dense cluster right around u_res so undamped Pohl zero dip renders sharply
            u_local = u_res + np.linspace(-0.015, 0.015, 61)
            u_local = u_local[(u_local > 1e-4) & (u_local < 1.0)]
            u_grid = np.unique(np.concatenate([u_base, u_local, [u_res]]))
        else:
            u_grid = u_base
    else:
        u_grid = u_base

    x_max = mat.theta_d_k / float(temperature_k)
    x_grid = u_grid * x_max
    omega_d = k * mat.theta_d_k / hbar
    omega_grid = u_grid * omega_d
    prefactor_x = (k / (2.0 * (math.pi**2) * mat.sound_velocity_m_s)) * ((k * temperature_k / hbar) ** 3)
    prefactor = prefactor_x if str(spectral_norm).lower() == "x" else (prefactor_x * x_max)
    kernel = debye_heat_kernel(x_grid)

    comps = scattering_rates_components(omega_grid, float(temperature_k), mat, scat)
    spec_df = pd.DataFrame(
        {
            "omega_over_omegaD": u_grid,
            "energy_meV": (hbar * omega_grid) / 1.602176634e-22,
            "omega_THz": omega_grid * 1e-12,
            "frequency_THz": omega_grid / (2.0 * math.pi * 1e12),
        }
    )

    final_tau = None
    final_ks_u = None
    for stage_label, mechs in cumulative_stages:
        rate = np.zeros_like(omega_grid)
        for m in mechs:
            rate = rate + comps[m]
        tau = 1.0 / np.maximum(rate, 1e-30)
        ks = prefactor * tau * kernel
        col_safe = stage_label.replace(" ", "_").replace("+", "plus")
        spec_df[f"kappa_s_{col_safe}"] = ks
        final_tau = tau
        final_ks_u = (prefactor_x * x_max) * tau * kernel

    assert final_tau is not None and final_ks_u is not None
    mfp_nm = mat.sound_velocity_m_s * final_tau * 1e9
    spec_df["mfp_nm"] = mfp_nm

    # Sort by increasing MFP using exact nonuniform du quadrature weights
    du_weights = np.gradient(u_grid)
    dk_weights = np.maximum(final_ks_u * du_weights, 0.0)
    order = np.argsort(mfp_nm)
    mfp_sorted = mfp_nm[order]
    cum_kappa = np.cumsum(dk_weights[order])
    total_k = max(float(cum_kappa[-1]), 1e-30)
    cum_norm = cum_kappa / total_k

    mfp_50_nm = float(np.interp(0.5, cum_norm, mfp_sorted))
    mfp_10_nm = float(np.interp(0.1, cum_norm, mfp_sorted))
    mfp_90_nm = float(np.interp(0.9, cum_norm, mfp_sorted))

    spec_df["mfp_sorted_nm"] = mfp_sorted
    spec_df["kappa_cum_norm"] = cum_norm

    return spec_df, {
        "reference_temperature_K": float(temperature_k),
        "spectral_norm": str(spectral_norm).lower(),
        "mfp_10pct_nm": mfp_10_nm,
        "mfp_50pct_median_nm": mfp_50_nm,
        "mfp_90pct_nm": mfp_90_nm,
    }


# ---------------------------------------------------------------------------
# Fitting Engine
# ---------------------------------------------------------------------------
PARAMETER_SPECS: dict[str, tuple[str, float, float, float]] = {
    # mech_key -> (attr_name_in_CallawayScatteringParams, init, min, max) — all fitted in log-space
    "U": ("b_umklapp_1e18_s_k", 2.5, 1e-3, 1000.0),
    "CU": ("umklapp_exp_k", 50.0, 3.0, 800.0),
    "GB": ("grain_size_nm", 1500.0, 2.0, 5.0e6),
    "PD": ("a_pd_1e41_s3", 2.0, 1e-4, 5000.0),
    "EP": ("ep_e_1e3", 2.0, 1e-4, 5000.0),
    "D": ("dislocation_density_1e11_cm2", 1.0, 1e-3, 5000.0),
    "NP": ("np_volume_fraction", 0.015, 1e-5, 0.30),
    "R": ("rattler_c_1e35_s3", 1.0, 1e-4, 1e5),
    "TE": ("rattler_theta_e_k", 35.0, 5.0, 300.0),
}


def fit_callaway_model(
    temperatures_k: np.ndarray,
    kappa_l_exp: np.ndarray,
    mat: CallawayMaterialParams,
    base_scat: CallawayScatteringParams,
    *,
    fit_mechanisms: Sequence[str] = ("U", "PD"),
    active_mechanisms: Sequence[str] = ("U", "GB", "PD"),
    loss_scale: str = "auto",
) -> tuple[CallawayScatteringParams, dict[str, Any]]:
    """Fit requested Callaway scattering parameters in log-space via Trust-Region Reflective NLS."""
    t_arr = np.asarray(temperatures_k, dtype=float)
    y_arr = np.asarray(kappa_l_exp, dtype=float)

    fit_keys = [m for m in fit_mechanisms if m in PARAMETER_SPECS]
    if not fit_keys:
        pred = callaway_kappa_l(t_arr, mat, base_scat, active_mechanisms=active_mechanisms)
        res = pred - y_arr
        return base_scat, {
            "mode": "simulation_only",
            "rmse_W_mK": float(np.sqrt(np.mean(res**2))),
            "mae_W_mK": float(np.mean(np.abs(res))),
            "r2": float(1.0 - np.sum(res**2) / max(np.sum((y_arr - np.mean(y_arr)) ** 2), 1e-30)),
        }

    x0_log = []
    lb_log = []
    ub_log = []
    param_names = []
    for key in fit_keys:
        attr, default_init, lo, hi = PARAMETER_SPECS[key]
        raw_cur = getattr(base_scat, attr)
        cur_val = float(raw_cur) if raw_cur is not None else -1.0
        if key == "CU" and cur_val <= 0:
            cur_val = mat.theta_d_k / max(mat.umklapp_div, 0.5)
        init_val = cur_val if (cur_val > 0.0 and lo <= cur_val <= hi) else default_init
        x0_log.append(math.log(init_val))
        lb_log.append(math.log(lo))
        ub_log.append(math.log(hi))
        param_names.append(attr)

    def unpack(theta_log: np.ndarray) -> CallawayScatteringParams:
        trial = CallawayScatteringParams(**asdict(base_scat))
        for key, val_log in zip(fit_keys, theta_log):
            attr = PARAMETER_SPECS[key][0]
            setattr(trial, attr, float(math.exp(float(val_log))))
        return trial

    dynamic_range = float(y_arr.max() / max(float(y_arr.min()), 1e-6))
    resolved_loss = (
        ("log" if dynamic_range > 3.8 or float(t_arr.min()) < 120.0 else "sqrt")
        if loss_scale == "auto"
        else loss_scale
    )

    def residuals_fn(theta_log: np.ndarray) -> np.ndarray:
        trial = unpack(theta_log)
        pred = callaway_kappa_l(t_arr, mat, trial, active_mechanisms=active_mechanisms)
        if resolved_loss == "log":
            return np.log(np.maximum(pred, 1e-12) / np.maximum(y_arr, 1e-12))
        if resolved_loss == "linear":
            return pred - y_arr
        return (pred - y_arr) / np.maximum(np.sqrt(np.abs(y_arr)), 0.15)

    opt = least_squares(residuals_fn, x0=np.asarray(x0_log), bounds=(lb_log, ub_log), method="trf", ftol=1e-11, xtol=1e-11)
    fitted_scat = unpack(opt.x)
    pred = callaway_kappa_l(t_arr, mat, fitted_scat, active_mechanisms=active_mechanisms)
    raw_res = pred - y_arr
    ss_tot = float(np.sum((y_arr - np.mean(y_arr)) ** 2))

    phys_vals = [float(getattr(fitted_scat, name)) for name in param_names]
    diag = compute_jacobian_diagnostics(
        opt.jac,
        opt.fun,
        param_names,
        phys_vals,
        is_log_param=[True] * len(param_names),
    )

    v0_m3 = mat.resolved_atomic_volume_m3()
    disorder_gamma = (
        4.0 * math.pi * (mat.sound_velocity_m_s**3) * (fitted_scat.a_pd_1e41_s3 * 1e-41) / v0_m3
    )

    return fitted_scat, {
        "mode": "fit",
        "converged": bool(opt.success),
        "active_mechanisms": list(active_mechanisms),
        "fitted_mechanisms": fit_keys,
        "rmse_W_mK": float(np.sqrt(np.mean(raw_res**2))),
        "mae_W_mK": float(np.mean(np.abs(raw_res))),
        "r2": float(1.0 - float(np.sum(raw_res**2)) / max(ss_tot, 1e-30)),
        "derived_point_defect_Gamma": float(disorder_gamma),
        "resolved_atomic_volume_A3": float(v0_m3 * 1e30),
        "diagnostics": diag,
    }


# ---------------------------------------------------------------------------
# Data Loading & Publication Plotting
# ---------------------------------------------------------------------------
def _looks_numeric_header(columns: Sequence[Any]) -> bool:
    if len(columns) < 2:
        return False
    try:
        float(str(columns[0]).strip())
        float(str(columns[1]).strip())
        return True
    except ValueError:
        return False


def load_kappa_l_table(
    path: str | os.PathLike[str],
    *,
    temp_col: str | None = None,
    kl_col: str | None = None,
) -> pd.DataFrame:
    df = read_tabular_data(path)
    # Support raw 2-column headerless WebPlotDigitizer CSV/TXT files directly
    if temp_col is None and kl_col is None and _looks_numeric_header(list(df.columns)):
        first_row = pd.DataFrame([[float(df.columns[0]), float(df.columns[1])]], columns=["Temperature_K", "kappa_L"])
        rest = df.iloc[:, :2].copy()
        rest.columns = ["Temperature_K", "kappa_L"]
        df = pd.concat([first_row, rest], ignore_index=True)

    t_c = find_column(df, temp_col, TEMPERATURE_CANDIDATES, required=False)
    kl_c = find_column(df, kl_col, KAPPA_L_CANDIDATES, required=False)
    if t_c is None and kl_c is None and df.shape[1] == 2:
        t_c, kl_c = str(df.columns[0]), str(df.columns[1])
    elif t_c is None:
        t_c = find_column(df, temp_col, TEMPERATURE_CANDIDATES, required=True)

    out = df.copy()
    out["Temperature_K"] = pd.to_numeric(out[t_c], errors="coerce").astype(float)

    if kl_c is not None:
        out["Lattice_Thermal_Conductivity_W_m-1_K-1"] = pd.to_numeric(out[kl_c], errors="coerce").astype(float)
        out["kappa_L_source"] = kl_c
    else:
        kt_c = find_column(df, None, KAPPA_TOT_CANDIDATES, required=True)
        s_c = find_column(df, None, SEEBECK_CANDIDATES, required=False)
        sig_c = find_column(df, None, CONDUCTIVITY_CANDIDATES, required=False)
        kt_vals = pd.to_numeric(out[kt_c], errors="coerce").astype(float)
        if s_c is not None and sig_c is not None:
            s_v_k = infer_seebeck_uv_k(out[s_c]) * 1e-6
            sig_s_m = infer_conductivity_s_m(out[sig_c], sig_c)
            ke_vals = []
            for t_v, s_v, sg_v in zip(out["Temperature_K"], s_v_k, sig_s_m):
                if np.isfinite(t_v) and np.isfinite(s_v) and np.isfinite(sg_v) and abs(s_v) > 1e-7:
                    eta = calculate_generalized_fermi_level(abs(float(s_v)))
                    lor = calculate_lorenz_number(eta)
                    ke_vals.append(lor * float(sg_v) * float(t_v))
                else:
                    ke_vals.append(0.0)
            out["Lattice_Thermal_Conductivity_W_m-1_K-1"] = kt_vals - np.asarray(ke_vals, dtype=float)
            out["kappa_L_source"] = f"{kt_c} - SPB_kappa_e"
        else:
            out["Lattice_Thermal_Conductivity_W_m-1_K-1"] = kt_vals
            out["kappa_L_source"] = kt_c

    out = out.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["Temperature_K", "Lattice_Thermal_Conductivity_W_m-1_K-1"]
    )
    out = out[(out["Temperature_K"] > 0) & (out["Lattice_Thermal_Conductivity_W_m-1_K-1"] > 0)].sort_values("Temperature_K")
    if out.empty:
        raise ValueError("No valid positive (Temperature, kappa_L) points found in input file.")
    return out.reset_index(drop=True)


MECH_DISPLAY_TOKENS = {
    "U": "U",
    "GB": "B",
    "PD": "PD",
    "EP": "EP",
    "D": "D",
    "NP": "NP",
    "R": "RES",
}

MECH_ALIASES = {
    "U": "U",
    "CU": "CU",
    "B": "GB",
    "GB": "GB",
    "PD": "PD",
    "EP": "EP",
    "D": "D",
    "NP": "NP",
    "R": "R",
    "RES": "R",
    "TE": "TE",
}


def normalize_mech_list(mechs: Sequence[str]) -> list[str]:
    out: list[str] = []
    for raw in mechs:
        canon = MECH_ALIASES.get(str(raw).strip().upper())
        if canon is None:
            raise ValueError(f"Unknown Callaway mechanism {raw!r}; choose from U, B/GB, PD, EP, D, NP, R/RES.")
        if canon not in out:
            out.append(canon)
    return out


def build_cumulative_stages(
    active_mechanisms: Sequence[str],
    *,
    has_cryogenic_t: bool = False,  # kept for API compatibility; pure U is always included first
) -> list[tuple[str, list[str]]]:
    """Build cumulative stages using standard Callaway notation:
    `U`, `U + B`, `U + B + PD`, `U + B + PD + RES` (all evaluated at the SAME fitted parameters).
    """
    _ = has_cryogenic_t
    ordered = [m for m in ("U", "GB", "PD", "EP", "D", "NP", "R") if m in active_mechanisms]
    if not ordered:
        ordered = ["U"]

    stages: list[tuple[str, list[str]]] = []
    running: list[str] = []
    for m in ordered:
        running = [*running, m]
        stage_label = " + ".join(MECH_DISPLAY_TOKENS.get(k, k) for k in running)
        stages.append((stage_label, running))
    return stages


def compute_mechanism_contributions_table(
    eval_temps_k: Sequence[float],
    stages: Sequence[tuple[str, Sequence[str]]],
    mat: CallawayMaterialParams,
    scat: CallawayScatteringParams,
) -> pd.DataFrame:
    """Quantify incremental kappa_L reduction (W/mK and % of total drop) at each stage using the fitted parameters."""
    rows: list[dict[str, Any]] = []
    t_arr = np.asarray(eval_temps_k, dtype=float)
    stage_vals = [callaway_kappa_l(t_arr, mat, scat, active_mechanisms=mechs) for _, mechs in stages]
    base_k = stage_vals[0]
    final_k = stage_vals[-1]
    total_drop = np.maximum(base_k - final_k, 1e-12)

    for t_idx, tk in enumerate(t_arr):
        row: dict[str, Any] = {
            "Temperature_K": float(tk),
            "Pure_First_Stage": stages[0][0],
            f"kappa_L_{stages[0][0]}_W_mK": float(base_k[t_idx]),
            "kappa_L_total_fit_W_mK": float(final_k[t_idx]),
        }
        for s_idx in range(1, len(stages)):
            stage_name = stages[s_idx][0]
            added_tok = MECH_DISPLAY_TOKENS.get(stages[s_idx][1][-1], stages[s_idx][1][-1])
            k_curr = float(stage_vals[s_idx][t_idx])
            dk = float(stage_vals[s_idx - 1][t_idx] - k_curr)
            row[f"kappa_L_{stage_name}_W_mK"] = k_curr
            row[f"Delta_kappa_{added_tok}_W_mK"] = dk
            row[f"Share_of_Drop_from_U_{added_tok}_pct"] = 100.0 * dk / float(total_drop[t_idx])
        rows.append(row)
    return pd.DataFrame(rows)


MECH_SHORT_NAMES = {
    "U": "Umklapp (U)",
    "GB": "Boundary (B)",
    "PD": "Point Defect (PD)",
    "EP": "e–ph / Planar (EP)",
    "D": "Dislocation (D)",
    "NP": "Nanoprecipitate (NP)",
    "R": "Resonant (RES)",
}


REPORT_PARAM_META: dict[str, tuple[str, str, str, str]] = {
    "b_umklapp_1e18_s_k": ("Umklapp (`U`)", r"$\tau_{\mathrm{U}}^{-1} = B \omega^2 T e^{-\Theta_{\mathrm{D}}/(b_{\mathrm{U}}T)}$", "$B$", "$10^{-18}$ s K$^{-1}$"),
    "umklapp_exp_k": ("Umklapp Exp (`CU`)", r"$\exp(-C_{\mathrm{U}} / T)$", "$C_{\\mathrm{U}}$", "K"),
    "grain_size_nm": ("Boundary (`B`)", r"$\tau_{\mathrm{B}}^{-1} = v_{\mathrm{s}} / L$", "$L$", "nm"),
    "a_pd_1e41_s3": ("Point Defect (`PD`)", r"$\tau_{\mathrm{PD}}^{-1} = A \omega^4$", "$A$", "$10^{-41}$ s$^3$"),
    "ep_e_1e3": ("e–ph / Planar (`EP`)", r"$\tau_{\mathrm{EP}}^{-1} = E_{\mathrm{ep}} \omega$", "$E_{\\mathrm{ep}}$", "$10^{-3}$"),
    "dislocation_density_1e11_cm2": ("Dislocation (`D`)", r"$\tau_{\mathrm{D}}^{-1} = \tau_{\mathrm{DS}}^{-1}(\omega) + \tau_{\mathrm{DC}}^{-1}(\omega^3)$", "$N_{\\mathrm{D}}$", "$10^{11}$ cm$^{-2}$"),
    "np_volume_fraction": ("Nanoprecipitate (`NP`)", r"$\tau_{\mathrm{NP}}^{-1} = v_{\mathrm{s}} n_{\mathrm{p}} (\sigma_{\mathrm{s}}^{-1}+\sigma_{\mathrm{l}}^{-1})^{-1}$", "$f_{\\mathrm{v}}$", "dimensionless"),
    "rattler_c_1e35_s3": ("Resonant (`RES`)", r"$\tau_{\mathrm{RES}}^{-1} = C_{\mathrm{RES}}\omega^2 / [(\omega_0^2-\omega^2)^2 + (\gamma_{\mathrm{R}}\omega_0\omega)^2]$", "$C_{\\mathrm{RES}}$", "$10^{35}$ s$^{-3}$"),
    "rattler_theta_e_k": ("Resonant Temp (`TE`)", r"$\omega_0 = k_{\mathrm{B}}\Theta_{\mathrm{E}} / \hbar$", "$\\Theta_{\\mathrm{E}}$", "K"),
}


MECH_SHADE_COLORS = {
    "GB": "#4CB992",  # soft mint/emerald green for Boundary reduction
    "PD": "#9B8AC4",  # soft lavender/violet for Point-Defect reduction
    "R": "#F28B82",   # soft coral/rose for Resonant reduction
    "EP": "#5DA5DA",  # soft sky blue for e-ph / planar fault reduction
    "D": "#60BD68",   # soft sage green for Dislocation reduction
    "NP": "#F5B041",  # soft warm amber for Nanoprecipitate reduction
    "U": "#D99B26",   # warm gold
}


def compute_paper_unit_equivalents(
    mat: CallawayMaterialParams,
    scat: CallawayScatteringParams,
    fit_info: dict[str, Any],
) -> dict[str, Any]:
    """Compute common literature/table unit equivalents so reports compare directly against papers."""
    omega_d_thz = (k * mat.theta_d_k / hbar) * 1e-12
    nu_d_thz = omega_d_thz / (2.0 * math.pi)
    e_d_mev = (k * mat.theta_d_k) / 1.602176634e-22

    w_res_thz = (k * scat.rattler_theta_e_k / hbar) * 1e-12
    nu_res_thz = w_res_thz / (2.0 * math.pi)
    e_res_mev = (k * scat.rattler_theta_e_k) / 1.602176634e-22
    wavenumber_cm1 = scat.rattler_theta_e_k * 0.6950348

    return {
        "omega_D_THz_rad_s": float(omega_d_thz),
        "nu_D_THz": float(nu_d_thz),
        "hbar_omega_D_meV": float(e_d_mev),
        "grain_size_um": float(scat.grain_size_nm / 1000.0),
        "b_umklapp_1e17_s_K": float(scat.b_umklapp_1e18_s_k / 10.0),
        "rattler_C_1e36_s3": float(scat.rattler_c_1e35_s3 / 10.0),
        "omega_RES_THz_rad_s": float(w_res_thz),
        "nu_RES_THz": float(nu_res_thz),
        "hbar_omega_RES_meV": float(e_res_mev),
        "nu_RES_cm-1": float(wavenumber_cm1),
        "point_defect_Gamma": float(fit_info.get("derived_point_defect_Gamma", 0.0)),
    }


def _dual_unit_note(attr: str, val: float, eq: dict[str, Any]) -> str:
    if attr == "b_umklapp_1e18_s_k":
        return f"`{val / 10.0:.4g}` $\\times 10^{{-17}}$ s K$^{{-1}}$"
    if attr == "grain_size_nm":
        return f"`{val / 1000.0:.4g}` $\\mu$m"
    if attr == "a_pd_1e41_s3":
        return f"$\\Gamma =$ `{eq['point_defect_Gamma']:.4f}`"
    if attr == "rattler_c_1e35_s3":
        return f"**`{val / 10.0:.4g}`** $\\times 10^{{36}}$ s$^{{-3}}$"
    if attr == "rattler_theta_e_k":
        return (
            f"$\\omega_{{\\mathrm{{RES}}}}/\\nu_{{\\mathrm{{RES}}}} =$ "
            f"**`{eq['omega_RES_THz_rad_s']:.2f}` / `{eq['nu_RES_THz']:.3f}`** THz "
            f"(`{eq['hbar_omega_RES_meV']:.2f}` meV, `{eq['nu_RES_cm-1']:.1f}` cm$^{{-1}}$)"
        )
    if attr == "dislocation_density_1e11_cm2":
        return f"`{val * 1e15:.3g}` m$^{{-2}}$"
    if attr == "np_volume_fraction":
        return f"`{val * 100.0:.2f}` vol%"
    return "—"


def build_callaway_markdown_report(
    stem: str,
    points_df: pd.DataFrame,
    share_df: pd.DataFrame,
    contrib_df: pd.DataFrame,
    stages: Sequence[tuple[str, Sequence[str]]],
    active_mechanisms: Sequence[str],
    mat: CallawayMaterialParams,
    scat: CallawayScatteringParams,
    fit_info: dict[str, Any],
    mfp_info: dict[str, Any],
) -> str:
    """Generate a structured Markdown parameter & contribution report for a Callaway fit."""
    t_exp = points_df["Temperature_K"].to_numpy(dtype=float)
    kl_exp = points_df["Lattice_Thermal_Conductivity_W_m-1_K-1"].to_numpy(dtype=float)
    res_arr = points_df["kappa_L_residual_W_m-1_K-1"].to_numpy(dtype=float)
    mape = float(100.0 * np.mean(np.abs(res_arr) / np.maximum(kl_exp, 1e-9)))
    sse = float(np.sum(res_arr * res_arr))
    pearson_chi2 = float(np.sum((res_arr * res_arr) / np.maximum(kl_exp, 1e-9)))
    v0_a3 = float(fit_info.get("resolved_atomic_volume_A3", mat.resolved_atomic_volume_m3() * 1e30))
    cahill_300 = float(cahill_minimum_kappa([300.0], mat)[0])
    eq = compute_paper_unit_equivalents(mat, scat, fit_info)

    unc_map = fit_info.get("diagnostics", {}).get("parameter_uncertainties", {})
    fitted_set = {PARAMETER_SPECS[k][0] for k in fit_info.get("fitted_mechanisms", []) if k in PARAMETER_SPECS}

    active_attrs: list[str] = []
    if "U" in active_mechanisms:
        active_attrs.append("b_umklapp_1e18_s_k")
        if scat.umklapp_exp_k is not None:
            active_attrs.append("umklapp_exp_k")
    if "GB" in active_mechanisms:
        active_attrs.append("grain_size_nm")
    if "PD" in active_mechanisms:
        active_attrs.append("a_pd_1e41_s3")
    if "EP" in active_mechanisms:
        active_attrs.append("ep_e_1e3")
    if "D" in active_mechanisms:
        active_attrs.append("dislocation_density_1e11_cm2")
    if "NP" in active_mechanisms:
        active_attrs.append("np_volume_fraction")
    if "R" in active_mechanisms:
        active_attrs.extend(["rattler_c_1e35_s3", "rattler_theta_e_k"])

    lines = [
        f"# Debye–Callaway Lattice Thermal Conductivity Fit Report (`{stem}`)",
        "",
        "## 1. Lattice Constants & Goodness-of-Fit Summary",
        "",
        "| Quantity | Symbol | Value | Unit | Source / Literature Equivalents |",
        "| --- | :---: | :---: | :---: | --- |",
        f"| Debye temperature | $\\Theta_{{\\mathrm{{D}}}}$ | `{mat.theta_d_k:.2f}` | K | $\\omega_{{\\mathrm{{D}}}}/\\nu_{{\\mathrm{{D}}}} =$ `{eq['omega_D_THz_rad_s']:.2f}` / `{eq['nu_D_THz']:.2f}` THz (`{eq['hbar_omega_D_meV']:.2f}` meV) |",
        f"| Average sound velocity | $v_{{\\mathrm{{s}}}}$ | `{mat.sound_velocity_m_s:.1f}` | m s$^{{-1}}$ | Input / Anderson sound velocity |",
        f"| Average atomic volume | $V_0$ | `{v0_a3:.2f}` | $\\text{{\\AA}}^3$ | {'Explicit input' if mat.atomic_volume_a3 else 'Derived from Debye sphere'} |",
        f"| Grüneisen / Resonant damping | $\\gamma_{{\\mathrm{{G}}}}$ / $\\gamma_{{\\mathrm{{R}}}}$ | `{mat.gruneisen_gamma:.2f}` / `{mat.rattler_damping:.2g}` | — | Umklapp divisor $b_{{\\mathrm{{U}}}} = {mat.umklapp_div:g}$ |",
        f"| Amorphous limit at 300 K | $\\kappa_{{\\min}}(300\\text{{ K}})$ | `{cahill_300:.4f}` | W m$^{{-1}}$ K$^{{-1}}$ | Cahill–Watson–Pohl model |",
        f"| Experimental $T$ range | $T$ | `{float(t_exp.min()):.2f} – {float(t_exp.max()):.2f}` | K | `{len(points_df)}` experimental points |",
        f"| Goodness of fit | $R^2$ / RMSE | `{fit_info.get('r2', 1.0):.4f}` (`{fit_info.get('r2', 1.0)*100:.2f}%`) / `{fit_info.get('rmse_W_mK', 0.0):.4f}` | W m$^{{-1}}$ K$^{{-1}}$ | MAPE = `{mape:.2f}%`, SSE = `{sse:.5f}`, $\\chi^2_{{\\mathrm{{P}}}} =$ `{pearson_chi2:.5f}` |",
        f"| Median phonon MFP at {mfp_info['reference_temperature_K']:.0f} K | $\\Lambda_{{50\\%}}$ | `{mfp_info['mfp_50pct_median_nm']:.2f}` | nm | 10%–90% window: `{mfp_info['mfp_10pct_nm']:.2f} – {mfp_info['mfp_90pct_nm']:.2f}` nm |",
        "",
        "## 2. Scattering Parameters, Uncertainties & Dual-Unit Equivalents",
        "",
        "| Mechanism | Relaxation Rate $\\tau_i^{-1}(\\omega, T)$ | Param | Optimal Value | Std. Error (SE) | 95% CI Half-Width | Unit | Literature Dual-Unit Equivalent | Status |",
        "| --- | --- | :---: | :---: | :---: | :---: | :---: | --- | :---: |",
    ]

    for attr in active_attrs:
        mech_lbl, formula, sym, unit = REPORT_PARAM_META[attr]
        val = float(getattr(scat, attr))
        is_fit = attr in fitted_set and attr in unc_map
        if is_fit:
            u = unc_map[attr]
            se_str = f"`± {u['std_error']:.3g}` (`{u['relative_se_pct']:.1f}%`)"
            ci_str = f"`± {u['ci95_halfwidth']:.3g}`"
            st_str = "Fit"
        else:
            se_str = "—"
            ci_str = "—"
            st_str = "Fixed"
        dual_str = _dual_unit_note(attr, val, eq)
        lines.append(f"| {mech_lbl} | {formula} | {sym} | **`{val:.4g}`** | {se_str} | {ci_str} | {unit} | {dual_str} | {st_str} |")

    # Table 3: Stage-by-stage kappa_L at characteristic temperatures
    stage_names = [s[0] for s in stages]
    lines.extend([
        "",
        "## 3. Cumulative Stage Thermal Conductivity & Scattering Shares",
        "",
        "| $T$ (K) | " + " | ".join(f"$\\kappa_{{\\mathrm{{L}}}}$ (`{sn}`)" for sn in stage_names) + " | Order-Independent Scattering Share $S_m(T)$ |",
        "| :---: | " + " | ".join(":---:" for _ in stage_names) + " | --- |",
    ])
    t_sh_grid = share_df["Temperature_K"].to_numpy(dtype=float)
    ordered_m = [m for m in ("GB", "R", "EP", "D", "NP", "PD", "U") if m in active_mechanisms]
    for _, crow in contrib_df.iterrows():
        tk = float(crow["Temperature_K"])
        k_cells = []
        for idx_s, sn in enumerate(stage_names):
            col_k = f"kappa_L_{sn}_W_mK" if idx_s > 0 else f"kappa_L_{stages[0][0]}_W_mK"
            k_cells.append(f"`{float(crow[col_k]):.4f}`")
        share_parts = []
        for m in ordered_m:
            pct = float(np.interp(tk, t_sh_grid, share_df[f"Share_{m}_pct"].to_numpy(dtype=float)))
            share_parts.append(f"`{MECH_DISPLAY_TOKENS[m]}`: {pct:.1f}%")
        lines.append(f"| `{tk:.1f}` | " + " | ".join(k_cells) + " | " + ", ".join(share_parts) + " |")

    warnings = fit_info.get("diagnostics", {}).get("identifiability_warnings", [])
    if warnings:
        lines.extend(["", "## 4. Identifiability & Collinearity Diagnostics", ""])
        for w in warnings:
            lines.append(f"- {w}")

    return "\n".join(lines) + "\n"


def compute_fractional_scattering_shares(
    temperatures_k: np.ndarray,
    active_mechanisms: Sequence[str],
    mat: CallawayMaterialParams,
    scat: CallawayScatteringParams,
) -> pd.DataFrame:
    """Compute order-independent Matthiessen conductivity-weighted scattering shares S_m(T) [%]
    at every temperature T, satisfying sum_m S_m(T) = 100% identically.
    """
    t_arr = np.atleast_1d(np.asarray(temperatures_k, dtype=float))
    x_eff_max = np.minimum(mat.theta_d_k / np.maximum(t_arr, 0.3), 46.0)[:, None]
    x = x_eff_max * _U01[None, :]
    omega = (k * t_arr[:, None] / hbar) * x

    comps = scattering_rates_components(omega, t_arr[:, None], mat, scat)
    ordered = [m for m in ("GB", "R", "EP", "D", "NP", "PD", "U") if m in active_mechanisms]
    total_rate = np.zeros_like(omega)
    for m in ordered:
        total_rate = total_rate + comps[m]
    total_rate_safe = np.maximum(total_rate, 1e-30)

    # Spectral thermal conductivity weight K(x, T) = tau_c * x^4 e^x / (e^x - 1)^2
    k_weight = (1.0 / total_rate_safe) * debye_heat_kernel(x) * _W01[None, :]
    denom = np.maximum(np.sum(k_weight, axis=1), 1e-300)

    out = pd.DataFrame({"Temperature_K": t_arr})
    for m in ordered:
        frac_m = comps[m] / total_rate_safe
        share_pct = 100.0 * np.sum(frac_m * k_weight, axis=1) / denom
        out[f"Share_{m}_pct"] = share_pct
    return out


def render_callaway_figures(
    points_df: pd.DataFrame,
    curve_df: pd.DataFrame,
    spec_df: pd.DataFrame,
    share_df: pd.DataFrame,
    stages: Sequence[tuple[str, list[str]]],
    active_mechanisms: Sequence[str],
    mat: CallawayMaterialParams,
    scat: CallawayScatteringParams,
    fit_info: dict[str, Any],
    mfp_info: dict[str, Any],
    *,
    output_dir: Path,
    stem_prefix: str,
    formats: Sequence[str],
    color_set: str | None = None,
    subplot_aspect: str = DEFAULT_SUBPLOT_ASPECT,
    xscale: str = "auto",
    yscale: str = "auto",
    spectral_xaxis: str = "norm",
    show: bool = False,
) -> list[str]:
    apply_plot_style(mode="single")
    palette = get_colors(color_set, max(len(stages) + 3, 7))
    saved_paths: list[str] = []

    t_exp_arr = points_df["Temperature_K"].to_numpy(dtype=float)
    exp_vals = points_df["Lattice_Thermal_Conductivity_W_m-1_K-1"].to_numpy(dtype=float)
    t_min_exp = float(t_exp_arr.min())
    exp_max = float(exp_vals.max())
    exp_min = float(exp_vals.min())
    t_grid = curve_df["Temperature_K"].to_numpy(dtype=float)
    stage_cols = [f"kappa_{lbl.replace(' ', '_').replace('+', 'plus')}" for lbl, _ in stages]
    crv_vals = curve_df[stage_cols].to_numpy()
    crv_max = float(crv_vals.max())
    # Exclude pure-U cryogenic exponential divergence when computing bounded display ceiling
    bounded_cols = stage_cols[1:] if (len(stage_cols) > 1 and stages[0][1] == ["U"] and t_min_exp < 100.0) else stage_cols
    bounded_max = float(curve_df[bounded_cols].to_numpy().max())

    linestyles = ["--", "-.", ":", (0, (5, 2, 1, 2)), (0, (3, 1, 1, 1))]
    # Non-red colors for intermediate stages; vibrant crimson-red (#E64B35) exclusively for the final best-fit curve!
    nonred = list(STAGE_NONRED_PALETTE)
    stage_colors = [
        nonred[idx % len(nonred)] if idx < len(stages) - 1 else FIT_RED_COLOR
        for idx in range(len(stages))
    ]
    last_col = stage_cols[-1]
    y_total_fit = curve_df[last_col].to_numpy(dtype=float)
    y_cahill = curve_df["Cahill_kappa_min_W_m-1_K-1"].to_numpy(dtype=float)

    mape_pct = float(
        100.0
        * np.mean(
            np.abs(points_df["kappa_L_residual_W_m-1_K-1"].to_numpy(dtype=float))
            / np.maximum(exp_vals, 1e-9)
        )
    )
    extra_tag = (
        rf"$\Theta_{{\mathrm{{E}}}}={scat.rattler_theta_e_k:.1f}$ K, $\Gamma={fit_info.get('derived_point_defect_Gamma', 0.0):.2f}$"
        if ("R" in active_mechanisms and scat.rattler_c_1e35_s3 > 0)
        else rf"$\Gamma={fit_info.get('derived_point_defect_Gamma', 0.0):.3f}$, $L={scat.grain_size_nm / 1000.0:.2f}$ $\mu$m"
    )
    info_lines = [
        rf"$\Theta_{{\mathrm{{D}}}}={mat.theta_d_k:.0f}$ K, $v_{{\mathrm{{s}}}}={mat.sound_velocity_m_s:.0f}$ m s$^{{-1}}$, $R^2={fit_info.get('r2', 1.0):.3f}$",
        extra_tag + rf", MAPE $={mape_pct:.1f}\%$",
    ]

    # --- Figure 1: Cryogenic-to-High-T Dual View (Linear Cascade Zoom + Log-Log Full Cascade) ---
    if t_min_exp < 100.0 and xscale == "auto" and yscale == "auto":
        fig1, (ax_lin, ax_log) = plt.subplots(1, 2, figsize=(11.8, 5.0))

        # Panel (a): Linear scale showing ALL stages (U, U+B, U+B+PD, U+B+PD+RES) zoomed around experimental scale
        for idx, ((stage_lbl, _), col_name) in enumerate(zip(stages, stage_cols)):
            y_st = curve_df[col_name].to_numpy(dtype=float)
            is_last = idx == len(stages) - 1
            ax_lin.plot(
                t_grid,
                y_st,
                color=stage_colors[idx],
                linestyle="-" if is_last else linestyles[idx % len(linestyles)],
                linewidth=DEFAULT_LINE_WIDTH * (1.2 if is_last else 0.95),
                label=f"{stage_lbl} (Fit)" if is_last else stage_lbl,
                zorder=4.2 if is_last else 2.8,
            )
        ax_lin.plot(t_grid, y_cahill, color="#555555", linestyle=(0, (4, 3)), linewidth=1.35, label=r"Cahill $\kappa_{\min}$", zorder=2.2)
        ax_lin.scatter(
            t_exp_arr,
            exp_vals,
            s=(DEFAULT_MARKER_SIZE * 0.88) ** 2,
            facecolor=EXP_MARKER_FACE,
            edgecolor=EXP_MARKER_EDGE,
            linewidths=1.0,
            alpha=0.90,
            label=r"Experimental $\kappa_{\mathrm{L}}$",
            zorder=3.8,
        )
        # Set linear ceiling so high-T separation of U / U+B / U+B+PD / Fit is visible without squashing experimental peak
        lin_top = max(exp_max, float(y_total_fit.max())) * 2.65
        ax_lin.set_xlim(0.0, float(t_grid.max()) * 1.02)
        ax_lin.set_ylim(0.0, lin_top)
        ax_lin.set_xlabel(r"$T$ (K)")
        ax_lin.set_ylabel(r"$\kappa_{\mathrm{L}}$ (W m$^{-1}$ K$^{-1}$)")
        format_te_axis(ax_lin, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
        ax_lin.text(
            0.54,
            0.03,
            "\n".join(info_lines),
            transform=ax_lin.transAxes,
            ha="center",
            va="bottom",
            fontsize=9.1,
            bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.75, "alpha": 0.92, "pad": 2.8},
            zorder=6,
        )
        place_legend_inside(
            ax_lin,
            loc="upper right",
            fontsize=9.6,
            frameon=True,
            facecolor="white",
            edgecolor="black",
            fancybox=False,
            ylim_locked=(True, False),
        )

        # Panel (b): Log-Log Full-Range Cascade (U -> U+B -> U+B+PD -> U+B+PD+RES)
        for idx, ((stage_lbl, _), col_name) in enumerate(zip(stages, stage_cols)):
            y_st = curve_df[col_name].to_numpy(dtype=float)
            is_last = idx == len(stages) - 1
            ax_log.plot(
                t_grid,
                y_st,
                color=stage_colors[idx],
                linestyle="-" if is_last else linestyles[idx % len(linestyles)],
                linewidth=DEFAULT_LINE_WIDTH * (1.2 if is_last else 0.95),
                label=f"{stage_lbl} (Fit)" if is_last else stage_lbl,
                zorder=4.2 if is_last else 2.8,
            )
        ax_log.plot(t_grid, y_cahill, color="#555555", linestyle=(0, (4, 3)), linewidth=1.3, label=r"Cahill $\kappa_{\min}$", zorder=2)
        ax_log.scatter(
            t_exp_arr,
            exp_vals,
            s=(DEFAULT_MARKER_SIZE * 0.85) ** 2,
            facecolor=EXP_MARKER_FACE,
            edgecolor=EXP_MARKER_EDGE,
            linewidths=1.0,
            alpha=0.90,
            label=r"Experimental $\kappa_{\mathrm{L}}$",
            zorder=3.8,
        )
        ax_log.set_xscale("log")
        ax_log.set_yscale("log")
        y_lo = max(min(exp_min, float(y_cahill.min())) * 0.55, 1e-3)
        ax_log.set_ylim(y_lo, max(exp_max, bounded_max) * 20.0)
        ax_log.set_xlabel(r"$T$ (K)")
        ax_log.set_ylabel(r"$\kappa_{\mathrm{L}}$ (W m$^{-1}$ K$^{-1}$)")
        format_te_axis(ax_log, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
        ax_log.xaxis.set_major_formatter(ticker.ScalarFormatter())
        place_legend_inside(
            ax_log,
            loc="upper right",
            fontsize=9.6,
            frameon=True,
            facecolor="white",
            edgecolor="black",
            fancybox=False,
            ylim_locked=(True, False),
        )
        fig1.tight_layout()
        saved_paths.extend(export_model_figure(fig1, f"{stem_prefix}_callaway_fit", output_dir=output_dir, formats=formats, show=show))
    else:
        use_log_x = (t_min_exp < 100.0) if xscale == "auto" else (xscale == "log")
        use_log_y = (t_min_exp < 100.0) if yscale == "auto" else (yscale == "log")
        figsize = figure_size_for_subplot_aspect(subplot_aspect, subplot_height=DEFAULT_SUBPLOT_HEIGHT)
        fig1, ax1 = plt.subplots(figsize=figsize)

        for idx, (stage_lbl, _) in enumerate(stages):
            col_safe = stage_lbl.replace(" ", "_").replace("+", "plus")
            y_stage = curve_df[f"kappa_{col_safe}"].to_numpy(dtype=float)
            is_last = idx == len(stages) - 1
            ax1.plot(
                t_grid,
                y_stage,
                color=stage_colors[idx],
                linestyle="-" if is_last else linestyles[idx % len(linestyles)],
                linewidth=DEFAULT_LINE_WIDTH * (1.2 if is_last else 0.95),
                label=f"{stage_lbl} (Fit)" if is_last else stage_lbl,
                zorder=4.5 if is_last else 2.5,
            )
        ax1.plot(t_grid, y_cahill, color="#555555", linestyle=(0, (4, 3)), linewidth=1.35, label=r"Cahill $\kappa_{\min}$", zorder=2)
        ax1.scatter(
            t_exp_arr,
            exp_vals,
            s=(DEFAULT_MARKER_SIZE * 0.95) ** 2,
            facecolor=EXP_MARKER_FACE,
            edgecolor=EXP_MARKER_EDGE,
            linewidths=1.05,
            alpha=0.90,
            label=r"Experimental $\kappa_{\mathrm{L}}$",
            zorder=3.8,
        )
        if use_log_x:
            ax1.set_xscale("log")
            ax1.xaxis.set_major_formatter(ticker.ScalarFormatter())
        if use_log_y:
            ax1.set_yscale("log")
            y_lo = max(min(exp_min, float(y_cahill.min())) * 0.55, 1e-3)
            ax1.set_ylim(y_lo, max(exp_max, bounded_max) * 16.0)
        else:
            y_all_max = min(max(exp_max, bounded_max), exp_max * 2.8) if bounded_max > exp_max * 3.5 else max(exp_max, bounded_max)
            ax1.set_ylim(0.0, y_all_max * 1.32)
        ax1.set_xlabel(r"$T$ (K)")
        ax1.set_ylabel(r"$\kappa_{\mathrm{L}}$ (W m$^{-1}$ K$^{-1}$)")
        format_te_axis(ax1, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE)
        ax1.text(
            0.97,
            0.54,
            "\n".join(info_lines),
            transform=ax1.transAxes,
            ha="right",
            va="top",
            fontsize=10.2,
            bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.92, "pad": 3.5},
            zorder=6,
        )
        place_legend_inside(
            ax1,
            loc="upper right",
            fontsize=10.5,
            frameon=True,
            facecolor="white",
            edgecolor="black",
            fancybox=False,
            ylim_locked=(True, False),
        )
        fig1.tight_layout()
        saved_paths.extend(export_model_figure(fig1, f"{stem_prefix}_callaway_fit", output_dir=output_dir, formats=formats, show=show))

    # --- Figure 2: Individual Mechanism Contributions (Relaxation Rate tau_i^-1(omega) + 100% Share vs T) ---
    fig_c, (ax_rt, ax_sh) = plt.subplots(1, 2, figsize=(11.6, 4.95))
    t_ref = mfp_info["reference_temperature_K"]
    u_pos = np.geomspace(0.01, 1.0, 320)
    omega_d = k * mat.theta_d_k / hbar
    omega_pos = u_pos * omega_d
    rate_comps = scattering_rates_components(omega_pos, float(t_ref), mat, scat)

    ordered_mechs = [m for m in ("GB", "R", "EP", "D", "NP", "PD", "U") if m in active_mechanisms]
    mech_color_map = {m: STAGE_NONRED_PALETTE[idx % len(STAGE_NONRED_PALETTE)] for idx, m in enumerate(ordered_mechs)}

    tot_rate = np.zeros_like(omega_pos)
    positive_rates: list[np.ndarray] = []
    for idx, m in enumerate(ordered_mechs):
        r_m = rate_comps[m]
        tot_rate = tot_rate + r_m
        if np.any(r_m > 0):
            positive_rates.append(r_m[r_m > 0])
            ax_rt.plot(
                u_pos,
                np.maximum(r_m, 1e-30),
                color=mech_color_map[m],
                linestyle=linestyles[idx % len(linestyles)],
                linewidth=1.55,
                label=MECH_SHORT_NAMES.get(m, m),
                zorder=3,
            )
    ax_rt.plot(u_pos, tot_rate, color=FIT_RED_COLOR, linewidth=DEFAULT_LINE_WIDTH * 1.2, label=r"Total $\tau_{\mathrm{c}}^{-1}$", zorder=4.5)

    r_min_pos = min(float(arr.min()) for arr in positive_rates) if positive_rates else 1e7
    r_max_pos = float(tot_rate.max())
    ax_rt.set_xscale("log")
    ax_rt.set_yscale("log")
    ax_rt.set_xlim(float(u_pos.min()), 1.0)
    ax_rt.set_ylim(max(r_min_pos * 0.35, 1e5), r_max_pos * 12.0)
    ax_rt.set_xlabel(r"Reduced frequency $\omega / \omega_{\mathrm{D}}$")
    ax_rt.set_ylabel(r"Scattering rate $\tau_i^{-1}$ (s$^{-1}$)")
    format_te_axis(ax_rt, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
    ax_rt.text(
        0.96,
        0.06,
        f"$T = {t_ref:.0f}$ K",
        transform=ax_rt.transAxes,
        ha="right",
        va="bottom",
        fontsize=10.8,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 2.0},
    )
    place_legend_inside(
        ax_rt,
        loc="upper left",
        fontsize=9.8,
        frameon=True,
        facecolor="white",
        edgecolor="black",
        fancybox=False,
        ylim_locked=(True, False),
    )

    # Panel (b): 100% Stacked Area of Individual Mechanism Scattering Share S_m(T) vs T
    t_sh = share_df["Temperature_K"].to_numpy(dtype=float)
    y_stacks = [share_df[f"Share_{m}_pct"].to_numpy(dtype=float) for m in ordered_mechs]
    stack_colors = [mech_color_map[m] for m in ordered_mechs]
    stack_labels = [m for m in ordered_mechs]

    polys = ax_sh.stackplot(t_sh, *y_stacks, labels=[MECH_SHORT_NAMES.get(m, m) for m in stack_labels], colors=stack_colors, alpha=0.72, zorder=2)
    cum_base = np.zeros_like(t_sh)
    for y_s, c_s in zip(y_stacks, stack_colors):
        cum_base = cum_base + y_s
        ax_sh.plot(t_sh, cum_base, color=c_s, linewidth=1.0, zorder=3)
    ax_sh.axhline(100.0, color="#555555", linestyle="--", linewidth=0.85, zorder=3.5)

    if t_min_exp < 100.0:
        ax_sh.set_xscale("log")
        ax_sh.xaxis.set_major_formatter(ticker.ScalarFormatter())
    ax_sh.set_xlim(float(t_sh.min()), float(t_sh.max()))
    n_leg_cols = 2 if len(ordered_mechs) <= 4 else 3
    ax_sh.set_ylim(0.0, 124.0 if len(ordered_mechs) > 2 else 118.0)
    ax_sh.set_yticks([0, 20, 40, 60, 80, 100])
    ax_sh.set_xlabel(r"$T$ (K)")
    ax_sh.set_ylabel("Scattering Contribution (%)")
    format_te_axis(ax_sh, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
    place_legend_inside(
        ax_sh,
        loc="upper center",
        ncol=n_leg_cols,
        fontsize=9.4,
        frameon=True,
        facecolor="white",
        edgecolor="black",
        fancybox=False,
        ylim_locked=(True, False),
        cap_ticks_at=100.0,
    )
    fig_c.tight_layout()
    saved_paths.extend(
        export_model_figure(fig_c, f"{stem_prefix}_callaway_contributions", output_dir=output_dir, formats=formats, show=show)
    )

    # --- Figure 3: Stage-by-Stage Shaded Spectral kappa_s + Cumulative kappa_cum(MFP) ---
    fig2, (ax_sp, ax_mfp) = plt.subplots(1, 2, figsize=(11.6, 5.0))
    sp_axis_key = str(spectral_xaxis).strip().lower()
    sp_axis_map = {
        "norm": ("omega_over_omegaD", r"Reduced frequency $\omega / \omega_{\mathrm{D}}$"),
        "mev": ("energy_meV", r"Phonon energy $\hbar\omega$ (meV)"),
        "thz": ("omega_THz", r"Angular frequency $\omega$ (THz)"),
        "nu-thz": ("frequency_THz", r"Phonon frequency $\nu$ (THz)"),
    }
    sp_col, sp_xlabel = sp_axis_map.get(sp_axis_key, sp_axis_map["norm"])
    x_sp = spec_df[sp_col].to_numpy(dtype=float)

    prev_ks = None
    for idx, (stage_lbl, stage_mechs) in enumerate(stages):
        col_safe = stage_lbl.replace(" ", "_").replace("+", "plus")
        ks = spec_df[f"kappa_s_{col_safe}"].to_numpy(dtype=float)
        is_last = idx == len(stages) - 1
        c_line = stage_colors[idx]
        ax_sp.plot(
            x_sp,
            ks,
            color=c_line,
            linestyle="-" if is_last else linestyles[idx % len(linestyles)],
            linewidth=DEFAULT_LINE_WIDTH * (1.2 if is_last else 0.95),
            label=f"{stage_lbl} (Fit)" if is_last else stage_lbl,
            zorder=4.8 if is_last else 3.2,
        )
        if prev_ks is not None:
            added_mech = stage_mechs[-1]
            added_tok = MECH_DISPLAY_TOKENS.get(added_mech, added_mech)
            shade_c = MECH_SHADE_COLORS.get(added_mech, c_line)
            ax_sp.fill_between(
                x_sp,
                ks,
                prev_ks,
                facecolor=shade_c,
                alpha=0.28 if added_mech == "R" else 0.24,
                edgecolor="none",
                label=f"−{added_tok} scattering",
                zorder=2.0 + 0.1 * idx,
            )
        prev_ks = ks
    if prev_ks is not None:
        ax_sp.fill_between(x_sp, 0.0, prev_ks, facecolor=FIT_RED_COLOR, alpha=0.07, edgecolor="none", zorder=1.5)

    t_ref = mfp_info["reference_temperature_K"]
    ks_top = max(
        float(spec_df[f"kappa_s_{s_lbl.replace(' ', '_').replace('+', 'plus')}"].max())
        for s_lbl, _ in stages
    )
    ks_top = max(ks_top, 1e-6)
    ax_sp.set_xlim(0.0, float(x_sp.max()))
    ax_sp.set_ylim(0.0, ks_top * (1.42 if len(stages) >= 4 else 1.32))
    ax_sp.set_xlabel(sp_xlabel)
    ax_sp.set_ylabel(r"Spectral $\kappa_{\mathrm{s}}$ (W m$^{-1}$ K$^{-1}$)")
    format_te_axis(ax_sp, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
    ax_sp.text(
        0.03,
        0.95,
        f"$T = {t_ref:.0f}$ K",
        transform=ax_sp.transAxes,
        ha="left",
        va="top",
        fontsize=10.8,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 2.0},
    )
    place_legend_inside(
        ax_sp,
        loc="upper right",
        ncol=2 if len(stages) >= 3 else 1,
        fontsize=8.8,
        frameon=True,
        facecolor="white",
        edgecolor="black",
        fancybox=False,
        ylim_locked=(True, False),
    )

    mfp_s = spec_df["mfp_sorted_nm"].to_numpy(dtype=float)
    cum_n = spec_df["kappa_cum_norm"].to_numpy(dtype=float)
    mfp50 = mfp_info["mfp_50pct_median_nm"]
    ax_mfp.plot(mfp_s, cum_n, color=FIT_RED_COLOR, linewidth=DEFAULT_LINE_WIDTH * 1.15, label="Cumulative $\\kappa_{\\mathrm{L}}$")
    ax_mfp.axhline(0.5, color="#666666", linestyle="--", linewidth=1.0)
    ax_mfp.axvline(mfp50, color="#3C5488", linestyle="--", linewidth=1.15)
    ax_mfp.set_xscale("log")
    mfp_lo = max(float(np.interp(0.002, cum_n, mfp_s)) * 0.25, 1e-3)
    mfp_hi = max(float(np.interp(0.999, cum_n, mfp_s)) * 2.5, mfp50 * 15.0)
    if mfp_hi > mfp_lo * 1.5:
        ax_mfp.set_xlim(mfp_lo, mfp_hi)
    ax_mfp.set_ylim(0.0, 1.08)
    ax_mfp.set_xlabel(r"Phonon MFP $\Lambda$ (nm)")
    ax_mfp.set_ylabel(r"Normalized $\kappa_{\mathrm{cum}}(\Lambda) / \kappa_{\mathrm{L}}$")
    format_te_axis(ax_mfp, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
    ax_mfp.xaxis.set_major_locator(ticker.LogLocator(base=10.0))
    ax_mfp.text(
        0.05,
        0.93,
        rf"$\Lambda_{{50\%}} = {mfp50:.1f}$ nm" + "\n" + rf"$\Lambda_{{10\text{{–}}90\%}} = {mfp_info['mfp_10pct_nm']:.1f}\text{{–}}{mfp_info['mfp_90pct_nm']:.1f}$ nm",
        transform=ax_mfp.transAxes,
        ha="left",
        va="top",
        fontsize=10.8,
        bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.92, "pad": 3.8},
    )

    fig2.tight_layout()
    saved_paths.extend(
        export_model_figure(fig2, f"{stem_prefix}_callaway_spectral_mfp", output_dir=output_dir, formats=formats, show=show)
    )
    return saved_paths


def run_callaway_workflow(
    input_csv: str | os.PathLike[str],
    *,
    output_dir: str | os.PathLike[str] | None = None,
    mat: CallawayMaterialParams | None = None,
    scat: CallawayScatteringParams | None = None,
    active_mechanisms: Sequence[str] = ("U", "GB", "PD"),
    fit_mechanisms: Sequence[str] = ("U", "PD"),
    ref_temp_k: float = 300.0,
    loss_scale: str = "auto",
    xscale: str = "auto",
    yscale: str = "auto",
    spectral_xaxis: str = "norm",
    spectral_norm: str = "u",
    temp_col: str | None = None,
    kl_col: str | None = None,
    formats: Sequence[str] = ("svg",),
    color_set: str | None = None,
    subplot_aspect: str = DEFAULT_SUBPLOT_ASPECT,
    rename: str | None = None,
    copy_to_data_dir: bool = True,
    show: bool = False,
) -> dict[str, Any]:
    mat_cfg = mat or CallawayMaterialParams()
    scat_init = scat or CallawayScatteringParams()
    points_df = load_kappa_l_table(input_csv, temp_col=temp_col, kl_col=kl_col)

    t_exp = points_df["Temperature_K"].to_numpy(dtype=float)
    kl_exp = points_df["Lattice_Thermal_Conductivity_W_m-1_K-1"].to_numpy(dtype=float)

    fitted_scat, fit_info = fit_callaway_model(
        t_exp,
        kl_exp,
        mat_cfg,
        scat_init,
        fit_mechanisms=fit_mechanisms,
        active_mechanisms=active_mechanisms,
        loss_scale=loss_scale,
    )

    points_df["kappa_L_model_W_m-1_K-1"] = callaway_kappa_l(t_exp, mat_cfg, fitted_scat, active_mechanisms=active_mechanisms)
    points_df["kappa_L_residual_W_m-1_K-1"] = points_df["kappa_L_model_W_m-1_K-1"] - kl_exp

    has_cryo = float(t_exp.min()) < 100.0
    t_lo = max(1.0, float(t_exp.min()) * 0.85)
    t_hi = float(t_exp.max()) * 1.06
    t_grid = np.geomspace(t_lo, t_hi, 320) if has_cryo else np.linspace(t_lo, t_hi, 240)
    stages = build_cumulative_stages(active_mechanisms, has_cryogenic_t=has_cryo)

    curve_df = pd.DataFrame({"Temperature_K": t_grid})
    for stage_lbl, mechs in stages:
        col_safe = stage_lbl.replace(" ", "_").replace("+", "plus")
        curve_df[f"kappa_{col_safe}"] = callaway_kappa_l(t_grid, mat_cfg, fitted_scat, active_mechanisms=mechs)
    curve_df["Cahill_kappa_min_W_m-1_K-1"] = cahill_minimum_kappa(t_grid, mat_cfg)

    spec_df, mfp_info = spectral_and_mfp_profile(ref_temp_k, mat_cfg, fitted_scat, stages, spectral_norm=spectral_norm)
    share_df = compute_fractional_scattering_shares(t_grid, active_mechanisms, mat_cfg, fitted_scat)
    eval_set = {round(float(t_exp[int(np.argmax(kl_exp))]), 1), float(ref_temp_k), round(float(t_exp.max()), 1)}
    if has_cryo:
        eval_set.add(round(float(t_exp.min()), 1))
        if float(t_exp.min()) < 9.0 < float(t_exp.max()):
            eval_set.add(10.0)
    eval_ts = sorted(eval_set)
    contrib_df = compute_mechanism_contributions_table(eval_ts, stages, mat_cfg, fitted_scat)
    fit_info["paper_unit_equivalents"] = compute_paper_unit_equivalents(mat_cfg, fitted_scat, fit_info)

    from te_analysis.paths import get_workspace

    out_path = Path(output_dir) if output_dir is not None else get_workspace().model_output_dir("callaway")
    out_path.mkdir(parents=True, exist_ok=True)
    stem = Path(input_csv).stem

    points_csv = out_path / f"{stem}_callaway_points.csv"
    curve_csv = out_path / f"{stem}_callaway_curve.csv"
    spec_csv = out_path / f"{stem}_callaway_spectral.csv"
    contrib_csv = out_path / f"{stem}_callaway_contributions.csv"
    share_csv = out_path / f"{stem}_callaway_shares.csv"
    points_df.to_csv(points_csv, index=False)
    curve_df.to_csv(curve_csv, index=False)
    spec_df.to_csv(spec_csv, index=False)
    contrib_df.to_csv(contrib_csv, index=False)
    share_df.to_csv(share_csv, index=False)

    with figure_output_naming(rename):
        fig_paths = render_callaway_figures(
            points_df,
            curve_df,
            spec_df,
            share_df,
            stages,
            active_mechanisms,
            mat_cfg,
            fitted_scat,
            fit_info,
            mfp_info,
            output_dir=out_path,
            stem_prefix=stem,
            formats=formats,
            color_set=color_set,
            subplot_aspect=subplot_aspect,
            xscale=xscale,
            yscale=yscale,
            spectral_xaxis=spectral_xaxis,
            show=show,
        )

    copied = copy_figures_beside_input(fig_paths, input_csv) if copy_to_data_dir else []
    report_md_text = build_callaway_markdown_report(
        stem,
        points_df,
        share_df,
        contrib_df,
        stages,
        active_mechanisms,
        mat_cfg,
        fitted_scat,
        fit_info,
        mfp_info,
    )
    report_md_path = out_path / f"{stem}_callaway_report.md"
    report_md_path.write_text(report_md_text, encoding="utf-8")

    summary = {
        "model": "Debye-Callaway",
        "input_csv": str(Path(input_csv).resolve()),
        "material": asdict(mat_cfg),
        "fitted_scattering": asdict(fitted_scat),
        "fit_metrics": fit_info,
        "mechanism_contributions": contrib_df.to_dict(orient="records"),
        "spectral_mfp_summary": mfp_info,
        "outputs": {
            "points_csv": str(points_csv),
            "curve_csv": str(curve_csv),
            "spectral_csv": str(spec_csv),
            "contributions_csv": str(contrib_csv),
            "shares_csv": str(share_csv),
            "report_md": str(report_md_path),
            "figures": fig_paths,
            "data_dir_figures": copied,
        },
    }
    summary_json = save_json_clean(summary, out_path / f"{stem}_callaway_summary.json")
    summary["outputs"]["summary_json"] = str(summary_json)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Fit Debye-Callaway multi-mechanism lattice thermal conductivity & spectral MFP profiles."
    )
    from te_analysis.paths import get_workspace

    p.add_argument("input_csv", help="CSV/TSV/XLSX with Temperature and kappa_L (or 2-column headerless T, kappa_L).")
    p.add_argument("-o", "--output-dir", default=str(get_workspace().model_output_dir("callaway")), help="Output folder.")
    p.add_argument("--theta-d", type=float, default=None, help="Debye temperature Theta_D in K (if omitted, computed from --vl/--vt or --cp-* or prompted).")
    p.add_argument("--vs", type=float, default=None, help="Average sound velocity v_s in m/s (if omitted, computed from --vl/--vt or --cp-* or prompted).")
    p.add_argument("--vl", type=float, default=None, help="Longitudinal sound velocity v_l in m/s (Method 1 ultrasonic).")
    p.add_argument("--vt", type=float, default=None, help="Transverse sound velocity v_t in m/s (Method 1 ultrasonic).")
    p.add_argument("--cp-csv", default=None, help="Low-T Cp(T) file to derive Theta_D (Method 2 heat capacity).")
    p.add_argument("--cp-beta", type=float, default=None, help="Low-T Cp/T vs T^2 slope beta in mJ mol^-1 K^-4 (Method 2).")
    p.add_argument("--density-g-cm3", type=float, default=None, help="Sample density in g/cm^3 (for deriving V_0 / v_s).")
    p.add_argument("--molar-mass", type=float, default=None, help="Formula-unit molar mass in g/mol (for deriving V_0 / v_s).")
    p.add_argument("--atoms-per-fu", type=float, default=None, help="Atoms per formula unit N_at (for Method 1/2).")
    p.add_argument("--atomic-volume-a3", type=float, default=None, help="Average volume per atom V_0 in Angstrom^3.")
    p.add_argument("--gruneisen", type=float, default=None, help="Gruneisen parameter gamma_G (default: derived from vl/vt or 1.6).")
    p.add_argument("--umklapp-div", type=float, default=3.0, help="Denominator b_U in exp(-Theta_D / (b_U * T)) (default: 3.0; some papers use 2.0).")
    p.add_argument("--umklapp-exp-k", type=float, default=None, help="Explicit Umklapp exponential temperature C_U (K) in exp(-C_U / T).")
    p.add_argument("--normal-beta", type=float, default=0.0, help="Callaway Normal-to-Umklapp ratio beta_N = tau_N^-1 / tau_U^-1.")
    p.add_argument(
        "--mechanisms",
        nargs="+",
        choices=tuple(k for k in MECH_ALIASES if k not in ("CU", "TE")),
        default=["U", "GB", "PD"],
        help="Active phonon scattering mechanisms (e.g. --mechanisms U B PD RES; default: U GB PD).",
    )
    p.add_argument(
        "--fit",
        dest="fit_mechanisms",
        nargs="*",
        choices=tuple(MECH_ALIASES.keys()),
        default=None,
        help="Subset of parameters to optimize (TE optimizes Rattler Einstein temperature Theta_E).",
    )
    p.add_argument("--grain-size-nm", type=float, default=2500.0, help="Initial or fixed grain size L in nm (default: 2500).")
    p.add_argument("--b-umklapp", type=float, default=2.5, help="Initial/fixed Umklapp B in 10^-18 s K^-1.")
    p.add_argument("--a-pd", type=float, default=1.5, help="Initial/fixed point-defect A in 10^-41 s^3.")
    p.add_argument("--ep-c", type=float, default=2.0, help="Initial/fixed Ziman electron-phonon / planar fault E_ep in 10^-3.")
    p.add_argument("--nd", type=float, default=1.0, help="Initial/fixed dislocation density N_D in 10^11 cm^-2.")
    p.add_argument("--np-fv", type=float, default=0.01, help="Initial/fixed nanoprecipitate volume fraction f_v.")
    p.add_argument("--np-radius-nm", type=float, default=4.0, help="Nanoprecipitate radius R_p in nm (default: 4.0).")
    p.add_argument("--rattler-theta-e", type=float, default=32.0, help="Initial or fixed Rattler Einstein temperature Theta_E in K.")
    p.add_argument("--fix-rattler-theta-e", action="store_true", help="Keep --rattler-theta-e fixed instead of optimizing TE.")
    p.add_argument("--rattler-c", type=float, default=2.0, help="Initial/fixed rattler coupling C_R in 10^35 s^-3.")
    p.add_argument("--rattler-damping", type=float, default=0.0, help="Dimensionless resonant damping gamma_R (default: 0.0 for standard Pohl undamped zero dip; e.g. 0.08 for Lorentzian broadening).")
    p.add_argument("--ref-temp", type=float, default=300.0, help="Reference temperature (K) for spectral & cumulative MFP plot.")
    p.add_argument(
        "--spectral-xaxis",
        type=str.lower,
        default="norm",
        choices=("norm", "mev", "thz", "nu-thz"),
        help="Horizontal axis unit for spectral kappa_s plot: norm (omega/omega_D), mev (hbar*omega in meV), thz (angular omega in THz), or nu-thz (nu in THz).",
    )
    p.add_argument(
        "--spectral-norm",
        type=str.lower,
        default="u",
        choices=("u", "x"),
        help="Spectral kappa_s integrand convention: 'u' wrt omega/omega_D in [0,1]; 'x' wrt hbar*omega/(k_B*T) in [0, Theta_D/T] (matches literature Fig d scale).",
    )
    p.add_argument("--loss-scale", default="auto", choices=("auto", "log", "sqrt", "linear"), help="Residual weighting across dynamic range (default: auto -> log for cryogenic-to-high-T).")
    p.add_argument("--xscale", default="auto", choices=("auto", "linear", "log"), help="Temperature axis scale (default: auto -> log when T_min < 100 K).")
    p.add_argument("--yscale", default="auto", choices=("auto", "linear", "log"), help="kappa_L axis scale (default: auto -> log when T_min < 100 K).")
    p.add_argument("--temp-col", default=None, help="Explicit temperature column name.")
    p.add_argument("--kl-col", default=None, help="Explicit lattice thermal conductivity column name.")
    p.add_argument("--subplot-aspect", "--aspect", default=DEFAULT_SUBPLOT_ASPECT, help="Plot aspect ratio (default: 10:8).")
    p.add_argument("--formats", nargs="+", default=["svg"], help="Figure export formats (e.g. svg png pdf).")
    p.add_argument("--pdf", action="store_true", help="Also export vector PDF.")
    p.add_argument("--no-copy-to-data-dir", action="store_true", help="Do not copy figures beside input CSV.")
    p.add_argument("--no-show", action="store_true", help="Save figures without opening GUI window.")
    add_color_set_argument(p)
    add_rename_argument(p)
    return p


def _resolve_cli_debye_inputs(args: argparse.Namespace) -> tuple[float, float, float | None, float]:
    """Resolve (theta_d_k, vs_m_s, atomic_volume_a3, gruneisen) from direct flags, Method 1 (vl/vt),
    Method 2 (Cp), or interactive prompt / structured agent error.
    """
    v0 = args.atomic_volume_a3
    gam = args.gruneisen if args.gruneisen is not None else 1.6

    if args.theta_d is not None and args.vs is not None:
        return float(args.theta_d), float(args.vs), v0, gam

    if args.vl is not None and args.vt is not None:
        res = debye_from_ultrasonic(
            args.vl,
            args.vt,
            atomic_volume_a3=v0,
            density_g_cm3=args.density_g_cm3,
            molar_mass_g_mol=args.molar_mass,
            atoms_per_fu=args.atoms_per_fu,
        )
        print(
            f"[Debye-Calc Method 1: Ultrasonic] v_s = {res['vs_anderson_m_s']:.1f} m/s, "
            f"Theta_D = {res['Theta_D_K']:.1f} K, gamma_G = {res['gruneisen_gamma']:.2f}"
        )
        return (
            float(args.theta_d or res["Theta_D_K"]),
            float(args.vs or res["vs_anderson_m_s"]),
            v0 or res["atomic_volume_A3"],
            args.gruneisen if args.gruneisen is not None else res["gruneisen_gamma"],
        )

    if args.cp_csv is not None or args.cp_beta is not None:
        if args.atoms_per_fu is None:
            raise MissingDebyeParametersError("Deriving Theta_D from low-T Cp requires `--atoms-per-fu <N>`.")
        res = debye_from_heat_capacity(
            atoms_per_fu=args.atoms_per_fu,
            beta_mj_mol_k4=args.cp_beta,
            cp_csv=args.cp_csv,
            molar_mass_g_mol=args.molar_mass,
            atomic_volume_a3=v0,
            density_g_cm3=args.density_g_cm3,
        )
        vs_out = args.vs or res["vs_derived_m_s"]
        if vs_out is None:
            raise MissingDebyeParametersError(
                f"Derived Theta_D = {res['Theta_D_K']:.1f} K from Cp, but still need `--vs` or `--atomic-volume-a3` "
                "(or `--density-g-cm3` + `--molar-mass`) to determine sound velocity v_s."
            )
        print(f"[Debye-Calc Method 2: Low-T Cp] Theta_D = {res['Theta_D_K']:.1f} K, v_s = {vs_out:.1f} m/s")
        return float(args.theta_d or res["Theta_D_K"]), float(vs_out), v0 or res["atomic_volume_A3"], gam

    if sys.stdin.isatty():
        ans = interactive_prompt_debye_params()
        return (
            float(ans["theta_d_k"]),
            float(ans["vs_m_s"]),
            ans["atomic_volume_a3"] or v0,
            args.gruneisen if args.gruneisen is not None else float(ans["gruneisen"] or 1.6),
        )

    raise MissingDebyeParametersError(format_missing_debye_prompt())


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    formats = normalize_output_formats(args.formats, pdf=args.pdf)

    try:
        theta_d_k, vs_m_s, v0_a3, gamma_g = _resolve_cli_debye_inputs(args)
    except MissingDebyeParametersError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    active = normalize_mech_list(args.mechanisms)
    df_peek = load_kappa_l_table(args.input_csv, temp_col=args.temp_col, kl_col=args.kl_col)
    has_low_t = float(df_peek["Temperature_K"].min()) < 150.0
    if args.fit_mechanisms is not None:
        fit_mechs = [MECH_ALIASES[m.strip().upper()] for m in args.fit_mechanisms]
    else:
        fit_mechs = [m for m in active if (m != "GB" or has_low_t)]
        if "R" in active and has_low_t and not args.fix_rattler_theta_e and "TE" not in fit_mechs:
            fit_mechs.append("TE")

    mat = CallawayMaterialParams(
        theta_d_k=theta_d_k,
        sound_velocity_m_s=vs_m_s,
        atomic_volume_a3=v0_a3,
        gruneisen_gamma=gamma_g,
        rattler_damping=args.rattler_damping,
        normal_ratio_beta=args.normal_beta,
        umklapp_div=args.umklapp_div,
    )
    scat = CallawayScatteringParams(
        b_umklapp_1e18_s_k=args.b_umklapp,
        umklapp_exp_k=args.umklapp_exp_k,
        grain_size_nm=args.grain_size_nm,
        a_pd_1e41_s3=args.a_pd,
        ep_e_1e3=args.ep_c if "EP" in active else 0.0,
        dislocation_density_1e11_cm2=args.nd if "D" in active else 0.0,
        np_volume_fraction=args.np_fv if "NP" in active else 0.0,
        np_radius_nm=args.np_radius_nm,
        rattler_c_1e35_s3=args.rattler_c if "R" in active else 0.0,
        rattler_theta_e_k=args.rattler_theta_e,
    )

    summary = run_callaway_workflow(
        args.input_csv,
        output_dir=args.output_dir,
        mat=mat,
        scat=scat,
        active_mechanisms=active,
        fit_mechanisms=fit_mechs,
        ref_temp_k=args.ref_temp,
        loss_scale=args.loss_scale,
        xscale=args.xscale,
        yscale=args.yscale,
        spectral_xaxis=args.spectral_xaxis,
        spectral_norm=args.spectral_norm,
        temp_col=args.temp_col,
        kl_col=args.kl_col,
        formats=formats,
        color_set=args.color_set,
        subplot_aspect=args.subplot_aspect,
        rename=args.rename,
        copy_to_data_dir=not args.no_copy_to_data_dir,
        show=not args.no_show,
    )
    print(f"Callaway fit complete -> R^2 = {summary['fit_metrics']['r2']:.4f}, RMSE = {summary['fit_metrics']['rmse_W_mK']:.4f} W m^-1 K^-1")
    print(f"Median phonon MFP at {args.ref_temp:g} K: {summary['spectral_mfp_summary']['mfp_50pct_median_nm']:.1f} nm")
    for w in summary["fit_metrics"].get("diagnostics", {}).get("identifiability_warnings", []):
        print(f"warning: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

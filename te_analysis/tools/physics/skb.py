#!/usr/bin/env python3
"""Single Kane Band (SKB) non-parabolic transport fitting tool.

Accounts for finite bandgap non-parabolicity alpha = k_B T / E_g via two-parameter
generalized Fermi integrals ^n L_k^m(eta, alpha):
  - Fits global DOS effective mass m*_d / m_e (and optionally E_g) from Hall Pisarenko |S|(n_H)
  - Computes per-point m*_d / m_e, Hall factor r_H, and SKB Lorenz number L(eta, alpha)
  - Fits intrinsic mobility mu_0 and acoustic deformation potential Xi (eV) when PF / sigma / mu_H is given
  - Automatically overlays the parabolic SPB (alpha = 0) curve at the same m*_d to visualize non-parabolicity
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
from scipy.constants import e, hbar, k, m_e
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import ticker  # noqa: E402

from te_analysis.tools.physics.fermi import (  # noqa: E402
    single_band_state,
    solve_eta_from_nh_skb,
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
    MOBILITY_CANDIDATES,
    NH_CANDIDATES,
    PF_CANDIDATES,
    SEEBECK_CANDIDATES,
    STAGE_NONRED_PALETTE,
    ZT_CANDIDATES,
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
    normalize_output_formats,
    place_legend_inside,
    read_tabular_data,
    save_json_clean,
)


@dataclass
class SKBFitConfig:
    temperature_k: float = 300.0
    eg_ev: float = 0.28
    fit_eg: bool = False
    fixed_mstar: float | None = None
    valley_degeneracy: float = 1.0
    anisotropy_k: float = 1.0
    use_hall_factor: bool = True
    density_kg_m3: float | None = None
    sound_velocity_m_s: float | None = None
    kappa_lattice_w_mk: float | None = None
    nh_unit: str = "cm^-3"
    seebeck_unit: str = "auto"
    sigma_unit: str = "auto"
    pf_unit: str = "auto"
    curve_points: int = 240


def alpha_from_temp_and_eg(temperature_k: float, eg_ev: float) -> float:
    if eg_ev <= 0:
        raise ValueError(f"Bandgap E_g must be > 0 eV, got {eg_ev}")
    return float((k * float(temperature_k)) / (float(eg_ev) * e))


def inertial_and_band_mass_from_dos(
    mstar_dos_ratio: float,
    valley_degeneracy: float = 1.0,
    anisotropy_k: float = 1.0,
) -> tuple[float, float]:
    """Return (m*_I / m_e, m*_b / m_e) for N_v ellipsoidal valleys with K = m_par / m_perp."""
    nv = max(float(valley_degeneracy), 1e-6)
    kv = max(float(anisotropy_k), 1e-6)
    mb = float(mstar_dos_ratio) / (nv ** (2.0 / 3.0))
    mi = mb * (3.0 * (kv ** (2.0 / 3.0))) / (2.0 * kv + 1.0)
    return float(mi), float(mb)


def deformation_potential_from_skb_mu0_ev(
    mu0_cm2_vs: float,
    mstar_dos_ratio: float,
    temperature_k: float,
    density_kg_m3: float,
    sound_velocity_m_s: float,
    *,
    valley_degeneracy: float = 1.0,
    anisotropy_k: float = 1.0,
) -> tuple[float, float, float]:
    """Invert Bardeen-Shockley mu_0 = pi e hbar^4 rho v_l^2 / (sqrt(2) m*_I (m*_b k_B T)^(3/2) Xi^2) for Xi [eV]."""
    mi_ratio, mb_ratio = inertial_and_band_mass_from_dos(mstar_dos_ratio, valley_degeneracy, anisotropy_k)
    mu0_si = float(mu0_cm2_vs) * 1e-4
    num = e * math.pi * (hbar**4) * float(density_kg_m3) * (float(sound_velocity_m_s) ** 2)
    den_no_xi = math.sqrt(2.0) * (mi_ratio * m_e) * ((mb_ratio * m_e * k * float(temperature_k)) ** 1.5)
    xi_j = math.sqrt(num / max(den_no_xi * mu0_si, 1e-160))
    return float(xi_j / e), mi_ratio, mb_ratio


def point_mstar_from_eta_and_nh_skb(
    eta: float,
    nh_m3: float,
    temperature_k: float,
    alpha: float,
    *,
    anisotropy_k: float = 1.0,
    use_hall_factor: bool = True,
) -> tuple[float, float, float]:
    """Compute exact point-wise (m*_d / m_e, r_H, Lorenz_WOhmK-2) from experimental (n_H, |S|)."""
    st_unit = single_band_state(
        eta,
        temperature_k=temperature_k,
        mstar_dos_ratio=1.0,
        alpha=alpha,
        anisotropy_k=anisotropy_k,
        use_hall_factor=use_hall_factor,
    )
    nh_at_m1 = float(st_unit["nH_m-3"][0])
    # Since n_H proportional to (m*_d)^(3/2):
    mstar = (float(nh_m3) / max(nh_at_m1, 1e-30)) ** (2.0 / 3.0)
    return float(mstar), float(st_unit["Hall_factor_rH"][0]), float(st_unit["Lorenz_WOhmK-2"][0])


def load_skb_points(
    input_csv: str | os.PathLike[str],
    cfg: SKBFitConfig,
    *,
    nh_col: str | None = None,
    seebeck_col: str | None = None,
    mu_col: str | None = None,
    sigma_col: str | None = None,
    pf_col: str | None = None,
    zt_col: str | None = None,
) -> pd.DataFrame:
    df = read_tabular_data(input_csv)
    c_nh = find_column(df, nh_col, NH_CANDIDATES, required=True)
    c_s = find_column(df, seebeck_col, SEEBECK_CANDIDATES, required=True)
    c_mu = find_column(df, mu_col, MOBILITY_CANDIDATES, required=False)
    c_sig = find_column(df, sigma_col, CONDUCTIVITY_CANDIDATES, required=False)
    c_pf = find_column(df, pf_col, PF_CANDIDATES, required=False)
    c_zt = find_column(df, zt_col, ZT_CANDIDATES, required=False)

    out = df.copy()
    nh_raw = pd.to_numeric(out[c_nh], errors="coerce").astype(float)
    u_nh = cfg.nh_unit.strip().lower().replace(" ", "")
    if u_nh in {"m^-3", "m-3", "1/m3"}:
        out["nH_m-3"] = nh_raw
        out["nH_cm-3"] = nh_raw * 1e-6
    else:
        out["nH_cm-3"] = nh_raw
        out["nH_m-3"] = nh_raw * 1e6

    out["Seebeck_uV_K"] = infer_seebeck_uv_k(out[c_s], cfg.seebeck_unit)
    out["Seebeck_abs_uV_K"] = out["Seebeck_uV_K"].abs()

    if c_mu is not None:
        out["Hall_Mobility_exp_cm2_V-1_s-1"] = pd.to_numeric(out[c_mu], errors="coerce").astype(float)
    if c_sig is not None:
        sig_sm = infer_conductivity_s_m(out[c_sig], c_sig, cfg.sigma_unit)
        out["Conductivity_exp_S_m-1"] = sig_sm
        out["Conductivity_exp_S_cm-1"] = sig_sm * 0.01
        if "Hall_Mobility_exp_cm2_V-1_s-1" not in out.columns:
            out["Hall_Mobility_exp_cm2_V-1_s-1"] = (sig_sm / (out["nH_m-3"] * e)) * 1e4
    if c_pf is not None:
        pf_uw = infer_pf_uw_cm_k2(out[c_pf], c_pf, cfg.pf_unit)
        out["Power_Factor_exp_uW_cm-1_K-2"] = pf_uw
        out["Power_Factor_exp_W_m-1_K-2"] = pf_uw * 1e-4
        if "Hall_Mobility_exp_cm2_V-1_s-1" not in out.columns:
            s_vk = out["Seebeck_abs_uV_K"] * 1e-6
            sig_est = (pf_uw * 1e-4) / np.maximum(s_vk * s_vk, 1e-30)
            out["Hall_Mobility_exp_cm2_V-1_s-1"] = (sig_est / (out["nH_m-3"] * e)) * 1e4
    elif "Conductivity_exp_S_m-1" in out.columns:
        pf_si = ((out["Seebeck_abs_uV_K"] * 1e-6) ** 2) * out["Conductivity_exp_S_m-1"]
        out["Power_Factor_exp_W_m-1_K-2"] = pf_si
        out["Power_Factor_exp_uW_cm-1_K-2"] = pf_si * 1e4

    if c_zt is not None:
        out["ZT_exp"] = pd.to_numeric(out[c_zt], errors="coerce").astype(float)

    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=["nH_m-3", "Seebeck_abs_uV_K"])
    out = out[(out["nH_m-3"] > 0) & (out["Seebeck_abs_uV_K"] > 0)].sort_values("nH_cm-3").reset_index(drop=True)
    if out.empty:
        raise ValueError("No valid positive (nH, |S|) rows found in input CSV.")
    return out


def fit_skb_model(points_df: pd.DataFrame, cfg: SKBFitConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    nh_m3 = points_df["nH_m-3"].to_numpy(dtype=float)
    nh_cm3 = points_df["nH_cm-3"].to_numpy(dtype=float)
    s_exp = points_df["Seebeck_abs_uV_K"].to_numpy(dtype=float)
    has_mobility = "Hall_Mobility_exp_cm2_V-1_s-1" in points_df.columns
    mu_exp = points_df["Hall_Mobility_exp_cm2_V-1_s-1"].to_numpy(dtype=float) if has_mobility else None

    # Initial m*_d guess from median point-wise SKB mass
    alpha_init = alpha_from_temp_and_eg(cfg.temperature_k, cfg.eg_ev)
    m_pts_init = []
    for nh_i, s_i in zip(nh_m3, s_exp):
        eta_i = solve_eta_from_seebeck_skb(float(s_i), alpha=alpha_init)
        m_i, _, _ = point_mstar_from_eta_and_nh_skb(
            eta_i,
            float(nh_i),
            cfg.temperature_k,
            alpha_init,
            anisotropy_k=cfg.anisotropy_k,
            use_hall_factor=cfg.use_hall_factor,
        )
        m_pts_init.append(m_i)
    mstar_guess = float(np.median(m_pts_init))

    param_names: list[str] = []
    x0: list[float] = []
    lb: list[float] = []
    ub: list[float] = []
    if cfg.fixed_mstar is None:
        param_names.append("mstar_dos_over_me")
        x0.append(math.log(float(np.clip(mstar_guess, 0.02, 20.0))))
        lb.append(math.log(0.01))
        ub.append(math.log(30.0))
    if cfg.fit_eg:
        param_names.append("Eg_eV")
        x0.append(math.log(float(np.clip(cfg.eg_ev, 0.04, 3.0))))
        lb.append(math.log(0.03))
        ub.append(math.log(5.0))
    if has_mobility:
        # Estimate initial mu0 from first point
        st0 = single_band_state(
            0.0,
            temperature_k=cfg.temperature_k,
            mstar_dos_ratio=cfg.fixed_mstar or mstar_guess,
            mu0_cm2_vs=1.0,
            alpha=alpha_init,
            anisotropy_k=cfg.anisotropy_k,
            use_hall_factor=cfg.use_hall_factor,
        )
        mu0_guess = max(float(np.nanmedian(mu_exp)) / max(float(st0["Hall_Mobility_cm2_V-1_s-1"][0]), 0.1), 1.0)
        param_names.append("mu0_cm2_Vs")
        x0.append(math.log(float(np.clip(mu0_guess, 0.5, 5e4))))
        lb.append(math.log(0.05))
        ub.append(math.log(2e5))

    def unpack(vec: np.ndarray) -> tuple[float, float, float]:
        idx = 0
        ms = float(math.exp(float(vec[idx]))) if cfg.fixed_mstar is None else float(cfg.fixed_mstar)
        if cfg.fixed_mstar is None:
            idx += 1
        eg = float(math.exp(float(vec[idx]))) if cfg.fit_eg else float(cfg.eg_ev)
        if cfg.fit_eg:
            idx += 1
        mu0 = float(math.exp(float(vec[idx]))) if has_mobility else 100.0
        return ms, eg, mu0

    def predict_at_nh(nh_arr_m3: np.ndarray, ms: float, eg: float, mu0: float, *, parabolic_override: bool = False) -> dict[str, np.ndarray]:
        alp = 0.0 if parabolic_override else alpha_from_temp_and_eg(cfg.temperature_k, eg)
        etas = np.asarray(
            [
                solve_eta_from_nh_skb(
                    float(n_val),
                    temperature_k=cfg.temperature_k,
                    mstar_dos_ratio=ms,
                    alpha=alp,
                    anisotropy_k=cfg.anisotropy_k,
                    use_hall_factor=cfg.use_hall_factor,
                )
                for n_val in nh_arr_m3
            ],
            dtype=float,
        )
        return single_band_state(
            etas,
            temperature_k=cfg.temperature_k,
            mstar_dos_ratio=ms,
            mu0_cm2_vs=mu0,
            alpha=alp,
            anisotropy_k=cfg.anisotropy_k,
            use_hall_factor=cfg.use_hall_factor,
        )

    s_scale = max(float(np.std(s_exp)), 15.0)

    def resid(vec: np.ndarray) -> np.ndarray:
        ms, eg, mu0 = unpack(vec)
        st = predict_at_nh(nh_m3, ms, eg, mu0)
        r_s = (st["Seebeck_abs_uV_K"] - s_exp) / s_scale
        if has_mobility and mu_exp is not None:
            valid = np.isfinite(mu_exp) & (mu_exp > 0)
            r_mu = (np.log(st["Hall_Mobility_cm2_V-1_s-1"][valid]) - np.log(mu_exp[valid])) / 0.18
            return np.concatenate([r_s, r_mu])
        return r_s

    if param_names:
        opt = least_squares(resid, x0=np.asarray(x0), bounds=(lb, ub), method="trf", ftol=1e-11, xtol=1e-11)
        mstar_fit, eg_fit, mu0_fit = unpack(opt.x)
        phys_vals = [math.exp(float(v)) for v in opt.x]
        diag = compute_jacobian_diagnostics(opt.jac, opt.fun, param_names, phys_vals, is_log_param=[True] * len(param_names))
    else:
        mstar_fit, eg_fit, mu0_fit = float(cfg.fixed_mstar or mstar_guess), float(cfg.eg_ev), 100.0
        diag = {}

    alpha_fit = alpha_from_temp_and_eg(cfg.temperature_k, eg_fit)

    # Enrich experimental table with point-wise SKB values + fitted SKB model predictions
    pts = points_df.copy()
    eta_pts, m_pts, rh_pts, lor_pts = [], [], [], []
    for nh_i, s_i in zip(nh_m3, s_exp):
        ei = solve_eta_from_seebeck_skb(float(s_i), alpha=alpha_fit)
        mi, rhi, lori = point_mstar_from_eta_and_nh_skb(
            ei,
            float(nh_i),
            cfg.temperature_k,
            alpha_fit,
            anisotropy_k=cfg.anisotropy_k,
            use_hall_factor=cfg.use_hall_factor,
        )
        eta_pts.append(ei)
        m_pts.append(mi)
        rh_pts.append(rhi)
        lor_pts.append(lori * 1e8)
    pts["eta_from_Seebeck_SKB"] = eta_pts
    pts["mstar_over_me_point_SKB"] = m_pts
    pts["Hall_factor_rH_SKB"] = rh_pts
    pts["Lorenz_1e-8_WOhmK-2_SKB"] = lor_pts

    st_pts = predict_at_nh(nh_m3, mstar_fit, eg_fit, mu0_fit)
    pts["Seebeck_model_SKB_uV_K"] = st_pts["Seebeck_abs_uV_K"]
    pts["Hall_Mobility_model_SKB_cm2_V-1_s-1"] = st_pts["Hall_Mobility_cm2_V-1_s-1"]
    pts["Power_Factor_model_SKB_uW_cm-1_K-2"] = st_pts["Power_Factor_uW_cm-1_K-2"]
    if cfg.kappa_lattice_w_mk is not None and cfg.kappa_lattice_w_mk > 0:
        ktot_pts = cfg.kappa_lattice_w_mk + st_pts["Carrier_Thermal_Conductivity_W_m-1_K-1"]
        pts["ZT_model_SKB"] = st_pts["Power_Factor_W_m-1_K-2"] * cfg.temperature_k / ktot_pts

    # Fit reference parabolic SPB (alpha = 0) to the same dataset for direct apples-to-apples comparison
    def resid_spb(vec_spb: np.ndarray) -> np.ndarray:
        ms_p = float(math.exp(float(vec_spb[0])))
        mu_p = float(math.exp(float(vec_spb[1]))) if len(vec_spb) > 1 else mu0_fit
        st_p = predict_at_nh(nh_m3, ms_p, eg_fit, mu_p, parabolic_override=True)
        rs_p = (st_p["Seebeck_abs_uV_K"] - s_exp) / s_scale
        if has_mobility and mu_exp is not None:
            valid = np.isfinite(mu_exp) & (mu_exp > 0)
            rm_p = (np.log(st_p["Hall_Mobility_cm2_V-1_s-1"][valid]) - np.log(mu_exp[valid])) / 0.18
            return np.concatenate([rs_p, rm_p])
        return rs_p

    x0_spb = [math.log(mstar_fit)] + ([math.log(mu0_fit)] if has_mobility else [])
    lb_spb = [math.log(0.01)] + ([math.log(0.05)] if has_mobility else [])
    ub_spb = [math.log(30.0)] + ([math.log(2e5)] if has_mobility else [])
    opt_spb = least_squares(resid_spb, x0=np.asarray(x0_spb), bounds=(lb_spb, ub_spb), method="trf")
    mstar_spb_ref = float(math.exp(float(opt_spb.x[0])))
    mu0_spb_ref = float(math.exp(float(opt_spb.x[1]))) if has_mobility else mu0_fit

    # Smooth SKB + reference SPB curves across log-spaced nH grid
    nh_lo = float(nh_cm3.min()) * 0.55
    nh_hi = float(nh_cm3.max()) * 1.85
    nh_grid_cm3 = np.logspace(math.log10(nh_lo), math.log10(nh_hi), cfg.curve_points)
    nh_grid_m3 = nh_grid_cm3 * 1e6

    st_skb = predict_at_nh(nh_grid_m3, mstar_fit, eg_fit, mu0_fit, parabolic_override=False)
    st_spb = predict_at_nh(nh_grid_m3, mstar_spb_ref, eg_fit, mu0_spb_ref, parabolic_override=True)

    curve_df = pd.DataFrame(
        {
            "nH_cm-3": nh_grid_cm3,
            "eta_SKB": st_skb["eta"],
            "Seebeck_SKB_uV_K": st_skb["Seebeck_abs_uV_K"],
            "Seebeck_SPB_uV_K": st_spb["Seebeck_abs_uV_K"],
            "Lorenz_SKB_1e-8_WOhmK-2": st_skb["Lorenz_1e-8_WOhmK-2"],
            "Lorenz_SPB_1e-8_WOhmK-2": st_spb["Lorenz_1e-8_WOhmK-2"],
            "Hall_Mobility_SKB_cm2_V-1_s-1": st_skb["Hall_Mobility_cm2_V-1_s-1"],
            "Hall_Mobility_SPB_cm2_V-1_s-1": st_spb["Hall_Mobility_cm2_V-1_s-1"],
            "Power_Factor_SKB_uW_cm-1_K-2": st_skb["Power_Factor_uW_cm-1_K-2"],
            "Power_Factor_SPB_uW_cm-1_K-2": st_spb["Power_Factor_uW_cm-1_K-2"],
        }
    )
    if cfg.kappa_lattice_w_mk is not None and cfg.kappa_lattice_w_mk > 0:
        curve_df["ZT_SKB"] = (
            st_skb["Power_Factor_W_m-1_K-2"]
            * cfg.temperature_k
            / (cfg.kappa_lattice_w_mk + st_skb["Carrier_Thermal_Conductivity_W_m-1_K-1"])
        )
        curve_df["ZT_SPB"] = (
            st_spb["Power_Factor_W_m-1_K-2"]
            * cfg.temperature_k
            / (cfg.kappa_lattice_w_mk + st_spb["Carrier_Thermal_Conductivity_W_m-1_K-1"])
        )

    s_res = st_pts["Seebeck_abs_uV_K"] - s_exp
    xi_ev = None
    mi_ratio, mb_ratio = inertial_and_band_mass_from_dos(mstar_fit, cfg.valley_degeneracy, cfg.anisotropy_k)
    if has_mobility and cfg.density_kg_m3 and cfg.sound_velocity_m_s:
        xi_ev, mi_ratio, mb_ratio = deformation_potential_from_skb_mu0_ev(
            mu0_fit,
            mstar_fit,
            cfg.temperature_k,
            cfg.density_kg_m3,
            cfg.sound_velocity_m_s,
            valley_degeneracy=cfg.valley_degeneracy,
            anisotropy_k=cfg.anisotropy_k,
        )

    summary_fit = {
        "Temperature_K": float(cfg.temperature_k),
        "Eg_eV": eg_fit,
        "nonparabolicity_alpha": alpha_fit,
        "mstar_dos_over_me": mstar_fit,
        "spb_apparent_mstar_over_me": mstar_spb_ref,
        "mstar_band_over_me": mb_ratio,
        "mstar_inertial_over_me": mi_ratio,
        "mu0_cm2_Vs": mu0_fit if has_mobility else None,
        "deformation_potential_Xi_eV": xi_ev,
        "seebeck_rmse_uV_K": float(np.sqrt(np.mean(s_res**2))),
        "seebeck_mae_uV_K": float(np.mean(np.abs(s_res))),
        "diagnostics": diag,
    }
    return pts, curve_df, summary_fit


def render_skb_figures(
    pts: pd.DataFrame,
    curve_df: pd.DataFrame,
    fit_info: dict[str, Any],
    cfg: SKBFitConfig,
    *,
    output_dir: Path,
    stem_prefix: str,
    formats: Sequence[str],
    color_set: str | None = None,
    show: bool = False,
) -> list[str]:
    apply_plot_style(mode="single")
    palette = get_colors(color_set, 5)

    fig, (ax_s, ax_r) = plt.subplots(1, 2, figsize=(11.3, 4.85))
    nh_exp = pts["nH_cm-3"].to_numpy(dtype=float)
    nh_grd = curve_df["nH_cm-3"].to_numpy(dtype=float)

    # Panel (a): Pisarenko |S| vs nH (SKB vs SPB)
    ax_s.plot(
        nh_grd,
        curve_df["Seebeck_SKB_uV_K"].to_numpy(dtype=float),
        color=FIT_RED_COLOR,
        linewidth=DEFAULT_LINE_WIDTH * 1.2,
        label=rf"SKB Fit ($m^*_{{\mathrm{{d}}}}={fit_info['mstar_dos_over_me']:.2f}m_e, E_{{\mathrm{{g}}}}={fit_info['Eg_eV']:.2f}$ eV)",
        zorder=4.5,
    )
    ax_s.plot(
        nh_grd,
        curve_df["Seebeck_SPB_uV_K"].to_numpy(dtype=float),
        color=STAGE_NONRED_PALETTE[0],
        linestyle="--",
        linewidth=1.45,
        label=rf"Best SPB Fit ($\alpha=0, m^*_{{\mathrm{{app}}}}={fit_info['spb_apparent_mstar_over_me']:.2f}m_e$)",
        zorder=3,
    )
    ax_s.scatter(
        nh_exp,
        pts["Seebeck_abs_uV_K"].to_numpy(dtype=float),
        s=(DEFAULT_MARKER_SIZE * 0.95) ** 2,
        facecolor=EXP_MARKER_FACE,
        edgecolor=EXP_MARKER_EDGE,
        linewidths=1.05,
        alpha=0.90,
        label="Experimental",
        zorder=3.8,
    )

    s_max = max(float(pts["Seebeck_abs_uV_K"].max()), float(curve_df["Seebeck_SKB_uV_K"].max()))
    ax_s.set_xscale("log")
    ax_s.set_ylim(0.0, s_max * 1.28)
    ax_s.set_xlabel(r"$n_{\mathrm{H}}$ (cm$^{-3}$)")
    ax_s.set_ylabel(r"$|S|$ ($\mu$V K$^{-1}$)")
    format_te_axis(ax_s, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
    ax_s.xaxis.set_major_locator(ticker.LogLocator(base=10.0))
    ax_s.text(
        0.04,
        0.16,
        rf"$T = {cfg.temperature_k:.0f}$ K, $\alpha = k_{{\mathrm{{B}}}}T/E_{{\mathrm{{g}}}} = {fit_info['nonparabolicity_alpha']:.3f}$",
        transform=ax_s.transAxes,
        ha="left",
        va="top",
        fontsize=10.5,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 2.0},
    )
    place_legend_inside(
        ax_s,
        loc="upper right",
        fontsize=10.2,
        frameon=True,
        facecolor="white",
        edgecolor="black",
        fancybox=False,
        ylim_locked=(True, False),
    )

    # Panel (b): PF (if available) or Mobility (if available) or Lorenz suppression
    if "Power_Factor_exp_uW_cm-1_K-2" in pts.columns:
        ax_r.plot(
            nh_grd,
            curve_df["Power_Factor_SKB_uW_cm-1_K-2"].to_numpy(dtype=float),
            color=FIT_RED_COLOR,
            linewidth=DEFAULT_LINE_WIDTH * 1.2,
            label="SKB $PF$ Fit",
            zorder=4.5,
        )
        ax_r.plot(
            nh_grd,
            curve_df["Power_Factor_SPB_uW_cm-1_K-2"].to_numpy(dtype=float),
            color=STAGE_NONRED_PALETTE[0],
            linestyle="--",
            linewidth=1.45,
            label="SPB $PF$ ($\\alpha=0$)",
            zorder=3,
        )
        ax_r.scatter(
            nh_exp,
            pts["Power_Factor_exp_uW_cm-1_K-2"].to_numpy(dtype=float),
            s=(DEFAULT_MARKER_SIZE * 0.95) ** 2,
            facecolor=EXP_MARKER_FACE,
            edgecolor=EXP_MARKER_EDGE,
            linewidths=1.05,
            alpha=0.90,
            label="Experimental $PF$",
            zorder=3.8,
        )
        pf_top = max(
            float(pts["Power_Factor_exp_uW_cm-1_K-2"].max()),
            float(curve_df[["Power_Factor_SKB_uW_cm-1_K-2", "Power_Factor_SPB_uW_cm-1_K-2"]].to_numpy().max()),
        )
        ax_r.set_ylim(0.0, pf_top * 1.32)
        ax_r.set_ylabel(r"$PF$ ($\mu$W cm$^{-1}$ K$^{-2}$)")
    elif "Hall_Mobility_exp_cm2_V-1_s-1" in pts.columns:
        ax_r.plot(
            nh_grd,
            curve_df["Hall_Mobility_SKB_cm2_V-1_s-1"].to_numpy(dtype=float),
            color=FIT_RED_COLOR,
            linewidth=DEFAULT_LINE_WIDTH * 1.2,
            label="SKB $\\mu_{\\mathrm{H}}$ Fit",
            zorder=4.5,
        )
        ax_r.plot(
            nh_grd,
            curve_df["Hall_Mobility_SPB_cm2_V-1_s-1"].to_numpy(dtype=float),
            color=STAGE_NONRED_PALETTE[0],
            linestyle="--",
            linewidth=1.45,
            label="SPB $\\mu_{\\mathrm{H}}$ ($\\alpha=0$)",
            zorder=3,
        )
        ax_r.scatter(
            nh_exp,
            pts["Hall_Mobility_exp_cm2_V-1_s-1"].to_numpy(dtype=float),
            s=(DEFAULT_MARKER_SIZE * 0.95) ** 2,
            facecolor=EXP_MARKER_FACE,
            edgecolor=EXP_MARKER_EDGE,
            linewidths=1.05,
            alpha=0.90,
            label="Experimental $\\mu_{\\mathrm{H}}$",
            zorder=3.8,
        )
        mu_top = max(
            float(pts["Hall_Mobility_exp_cm2_V-1_s-1"].max()),
            float(curve_df["Hall_Mobility_SPB_cm2_V-1_s-1"].max()),
        )
        ax_r.set_ylim(0.0, mu_top * 1.30)
        ax_r.set_ylabel(r"$\mu_{\mathrm{H}}$ (cm$^2$ V$^{-1}$ s$^{-1}$)")
    else:
        ax_r.plot(
            nh_grd,
            curve_df["Lorenz_SKB_1e-8_WOhmK-2"].to_numpy(dtype=float),
            color=FIT_RED_COLOR,
            linewidth=DEFAULT_LINE_WIDTH * 1.2,
            label="SKB Lorenz $L$",
            zorder=4.5,
        )
        ax_r.plot(
            nh_grd,
            curve_df["Lorenz_SPB_1e-8_WOhmK-2"].to_numpy(dtype=float),
            color=STAGE_NONRED_PALETTE[0],
            linestyle="--",
            linewidth=1.45,
            label="SPB Lorenz $L$ ($\\alpha=0$)",
            zorder=3,
        )
        ax_r.scatter(
            nh_exp,
            pts["Lorenz_1e-8_WOhmK-2_SKB"].to_numpy(dtype=float),
            s=(DEFAULT_MARKER_SIZE * 0.95) ** 2,
            facecolor=EXP_MARKER_FACE,
            edgecolor=EXP_MARKER_EDGE,
            linewidths=1.05,
            alpha=0.90,
            label="Points (SKB $L$)",
            zorder=3.8,
        )
        ax_r.set_ylabel(r"$L$ ($10^{-8}$ W $\Omega$ K$^{-2}$)")
        ax_r.set_ylim(1.2, 2.65)

    ax_r.set_xscale("log")
    ax_r.set_xlabel(r"$n_{\mathrm{H}}$ (cm$^{-3}$)")
    format_te_axis(ax_r, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE * 0.95)
    ax_r.xaxis.set_major_locator(ticker.LogLocator(base=10.0))

    if fit_info["mu0_cm2_Vs"] is not None:
        lines_b = [rf"$\mu_0 = {fit_info['mu0_cm2_Vs']:.1f}$ cm$^2$ V$^{{-1}}$ s$^{{-1}}$"]
        if fit_info["deformation_potential_Xi_eV"] is not None:
            lines_b.append(rf"$\Xi = {fit_info['deformation_potential_Xi_eV']:.2f}$ eV")
        ax_r.text(
            0.04,
            0.94,
            "\n".join(lines_b),
            transform=ax_r.transAxes,
            ha="left",
            va="top",
            fontsize=10.6,
            bbox={"facecolor": "white", "edgecolor": "black", "linewidth": 0.8, "alpha": 0.92, "pad": 3.8},
        )
    place_legend_inside(
        ax_r,
        loc="upper right",
        fontsize=10.2,
        frameon=True,
        facecolor="white",
        edgecolor="black",
        fancybox=False,
        ylim_locked=(True, False),
    )

    fig.tight_layout()
    return export_model_figure(fig, f"{stem_prefix}_skb_fit", output_dir=output_dir, formats=formats, show=show)


def run_skb_workflow(
    input_csv: str | os.PathLike[str],
    *,
    output_dir: str | os.PathLike[str] | None = None,
    cfg: SKBFitConfig | None = None,
    formats: Sequence[str] = ("svg",),
    color_set: str | None = None,
    rename: str | None = None,
    copy_to_data_dir: bool = True,
    show: bool = False,
) -> dict[str, Any]:
    from te_analysis.paths import get_workspace

    skb_cfg = cfg or SKBFitConfig()
    pts_in = load_skb_points(input_csv, skb_cfg)
    pts, curve_df, fit_info = fit_skb_model(pts_in, skb_cfg)

    out_path = Path(output_dir) if output_dir is not None else get_workspace().model_output_dir("skb")
    out_path.mkdir(parents=True, exist_ok=True)
    stem = Path(input_csv).stem
    pts_csv = out_path / f"{stem}_skb_points.csv"
    crv_csv = out_path / f"{stem}_skb_curve.csv"
    pts.to_csv(pts_csv, index=False)
    curve_df.to_csv(crv_csv, index=False)

    with figure_output_naming(rename):
        fig_paths = render_skb_figures(
            pts,
            curve_df,
            fit_info,
            skb_cfg,
            output_dir=out_path,
            stem_prefix=stem,
            formats=formats,
            color_set=color_set,
            show=show,
        )

    copied = copy_figures_beside_input(fig_paths, input_csv) if copy_to_data_dir else []
    summary = {
        "model": "Single-Kane-Band (SKB)",
        "input_csv": str(Path(input_csv).resolve()),
        "config": asdict(skb_cfg),
        "fit": fit_info,
        "outputs": {
            "points_csv": str(pts_csv),
            "curve_csv": str(crv_csv),
            "figures": fig_paths,
            "data_dir_figures": copied,
        },
    }
    sum_json = save_json_clean(summary, out_path / f"{stem}_skb_summary.json")
    summary["outputs"]["summary_json"] = str(sum_json)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fit non-parabolic Single Kane Band (SKB) transport parameters.")
    from te_analysis.paths import get_workspace

    p.add_argument("input_csv", help="CSV/TSV/XLSX with Hall nH and Seebeck (plus optional mu_H, sigma, PF, zT).")
    p.add_argument("-o", "--output-dir", default=str(get_workspace().model_output_dir("skb")), help="Output folder.")
    p.add_argument("-T", "--temperature", type=float, default=300.0, help="Measurement temperature in K (default: 300).")
    p.add_argument("--eg", type=float, default=0.28, help="Bandgap E_g in eV (default: 0.28).")
    p.add_argument("--fit-eg", action="store_true", help="Jointly optimize E_g alongside m*_d (requires rich high-nH/mobility data).")
    p.add_argument("--fix-mstar", type=float, default=None, help="Fix DOS effective mass m*_d / m_e.")
    p.add_argument("--nv", type=float, default=1.0, help="Valley degeneracy N_v (default: 1.0).")
    p.add_argument("--anisotropy-k", type=float, default=1.0, help="Valley mass anisotropy K = m_par / m_perp (default: 1.0).")
    p.add_argument("--no-hall-factor", action="store_true", help="Set r_H = 1 instead of Kane acoustic Hall factor.")
    p.add_argument("--rho", type=float, default=None, help="Mass density in kg/m^3 (for deformation potential Xi).")
    p.add_argument("--vl", type=float, default=None, help="Longitudinal sound velocity in m/s (for deformation potential Xi).")
    p.add_argument("--kL", type=float, default=None, help="Lattice thermal conductivity in W m^-1 K^-1 for zT curve.")
    p.add_argument("--nh-unit", default="cm^-3", choices=("cm^-3", "m^-3"), help="Unit of Hall carrier concentration.")
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
    cfg = SKBFitConfig(
        temperature_k=args.temperature,
        eg_ev=args.eg,
        fit_eg=args.fit_eg,
        fixed_mstar=args.fix_mstar,
        valley_degeneracy=args.nv,
        anisotropy_k=args.anisotropy_k,
        use_hall_factor=not args.no_hall_factor,
        density_kg_m3=args.rho,
        sound_velocity_m_s=args.vl,
        kappa_lattice_w_mk=args.kL,
        nh_unit=args.nh_unit,
        sigma_unit=args.sigma_unit,
    )
    summary = run_skb_workflow(
        args.input_csv,
        output_dir=args.output_dir,
        cfg=cfg,
        formats=formats,
        color_set=args.color_set,
        rename=args.rename,
        copy_to_data_dir=not args.no_copy_to_data_dir,
        show=not args.no_show,
    )
    fit = summary["fit"]
    print(
        f"SKB fit complete -> m*_d = {fit['mstar_dos_over_me']:.3f} m_e, "
        f"E_g = {fit['Eg_eV']:.3f} eV (alpha = {fit['nonparabolicity_alpha']:.3f}), "
        f"RMSE(|S|) = {fit['seebeck_rmse_uV_K']:.2f} uV/K"
    )
    for w in fit.get("diagnostics", {}).get("identifiability_warnings", []):
        print(f"warning: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

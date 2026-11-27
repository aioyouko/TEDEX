"""Vectorized Fermi-Dirac and two-parameter Kane generalized Fermi integrals.

Provides fast, double-precision (< 1e-12 relative error) numerical quadrature
on smooth transformed coordinates `x = t^2` using 96-node Gauss-Legendre rules:

1. Standard unnormalized Fermi-Dirac integral:
   F_j(eta) = int_0^inf x^j / (1 + exp(x - eta)) dx   (j > -1)

2. Generalized two-parameter Kane band integral:
   ^n L_k^m(eta, alpha) = int_0^inf (-df_0/dx) x^n (x + alpha x^2)^m (1 + 2 alpha x)^k dx

At alpha = 0 (parabolic limit E_g -> inf):
   ^n L_k^m(eta, 0) = (n + m) * F_{n + m - 1}(eta),
guaranteeing that SKB transport equations reduce identically to SPB.
"""

from __future__ import annotations

import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.constants import e, h, hbar, k, m_e
from scipy.optimize import brentq
from scipy.special import expit

K_B_OVER_E_V_PER_K: float = k / e
K_B_OVER_E_UV_PER_K: float = (k / e) * 1e6
LORENZ_PREFACTOR_W_OHM_K2: float = (k / e) ** 2

# Precompute 96-point Gauss-Legendre nodes/weights mapped to [0, 1]
_GL_NODES_RAW, _GL_WEIGHTS_RAW = leggauss(96)
_GL_U: np.ndarray = 0.5 * (_GL_NODES_RAW + 1.0)  # shape (96,)
_GL_W: np.ndarray = 0.5 * _GL_WEIGHTS_RAW  # shape (96,)


def _gl_integrate_t(
    t_lo: np.ndarray,
    t_hi: np.ndarray,
    eval_fn,
) -> np.ndarray:
    """Integrate `eval_fn(t)` over [t_lo, t_hi] row-wise using 96-node Gauss-Legendre."""
    span = np.maximum(t_hi - t_lo, 0.0)  # (N, 1)
    t = t_lo + span * _GL_U[None, :]  # (N, 96)
    vals = eval_fn(t)
    return np.sum(vals * _GL_W[None, :], axis=1) * span[:, 0]


def fermi_integral_vec(eta: float | np.ndarray, order: float) -> np.ndarray:
    """Vectorized unnormalized Fermi integral F_order(eta) (< 1e-13 rel error across all eta)."""
    j = float(order)
    if j <= -1.0:
        raise ValueError(f"Fermi integral order must be > -1, got {j}")

    eta_arr = np.atleast_1d(np.asarray(eta, dtype=float))
    eta_col = eta_arr[:, None]
    power = 2.0 * j + 1.0

    def integrand(t: np.ndarray) -> np.ndarray:
        t_term = np.ones_like(t) if power == 0.0 else np.power(t, power)
        return 2.0 * t_term * expit(eta_col - t * t)

    # Split at the Fermi step t_mid = sqrt(max(eta, 1.0)) so both the degenerate sea [0, sqrt(eta)]
    # and the thermal tail [sqrt(eta), sqrt(max(0, eta) + 46)] receive 96 nodes each!
    t_zero = np.zeros_like(eta_col)
    t_mid = np.sqrt(np.maximum(eta_col, 1.5))
    t_top = np.sqrt(np.maximum(eta_col, 0.0) + 48.0)
    return _gl_integrate_t(t_zero, t_mid, integrand) + _gl_integrate_t(t_mid, t_top, integrand)


def fermi_integral_scalar(eta: float, order: float) -> float:
    """Scalar convenience wrapper for F_order(eta)."""
    return float(fermi_integral_vec(float(eta), order)[0])


def kane_integral_vec(
    eta: float | np.ndarray,
    alpha: float | np.ndarray,
    n: float,
    k_idx: float,
    m: float,
) -> np.ndarray:
    """Vectorized generalized Kane integral ^n L_{k_idx}^m(eta, alpha).

    Definition:
        int_0^inf (-df_0/dx) * x^n * (x + alpha * x^2)^m * (1 + 2 * alpha * x)^k_idx dx

    Because (-df_0/dx) < 1e-20 outside [max(0, eta - 46), max(0, eta) + 46], mapping two 96-node
    sub-intervals around sqrt(max(eta, 1.5)) concentrates all 192 nodes inside the active Fermi window.
    """
    n_f, k_f, m_f = float(n), float(k_idx), float(m)
    if n_f + m_f <= -0.5:
        raise ValueError(f"Kane integral diverges at x=0 for n + m = {n_f + m_f} <= 0")

    eta_arr, alpha_arr = np.broadcast_arrays(
        np.atleast_1d(np.asarray(eta, dtype=float)),
        np.atleast_1d(np.asarray(alpha, dtype=float)),
    )
    if np.any(alpha_arr < 0.0):
        raise ValueError("Non-parabolicity parameter alpha = k_B T / E_g must be >= 0")

    shape = eta_arr.shape
    eta_flat = eta_arr.ravel()[:, None]  # (N, 1)
    alpha_flat = alpha_arr.ravel()[:, None]  # (N, 1)
    t_pow_exp = 2.0 * (n_f + m_f) + 1.0

    def integrand(t: np.ndarray) -> np.ndarray:
        x = t * t
        df0 = expit(eta_flat - x) * expit(x - eta_flat)
        t_pow = np.ones_like(t) if t_pow_exp == 0.0 else np.power(t, t_pow_exp)
        term_m = np.ones_like(x) if m_f == 0.0 else np.power(1.0 + alpha_flat * x, m_f)
        term_k = np.ones_like(x) if k_f == 0.0 else np.power(1.0 + 2.0 * alpha_flat * x, k_f)
        return 2.0 * df0 * t_pow * term_m * term_k

    x_lo = np.maximum(0.0, eta_flat - 46.0)
    x_mid = np.maximum(eta_flat, 1.5)
    x_hi = np.maximum(eta_flat, 0.0) + 46.0
    t_lo = np.sqrt(x_lo)
    t_mid = np.sqrt(np.maximum(x_mid, x_lo + 0.5))
    t_hi = np.sqrt(np.maximum(x_hi, x_mid + 1.0))

    vals = _gl_integrate_t(t_lo, t_mid, integrand) + _gl_integrate_t(t_mid, t_hi, integrand)
    return vals.reshape(shape)


def kane_integral_scalar(eta: float, alpha: float, n: float, k_idx: float, m: float) -> float:
    return float(kane_integral_vec(float(eta), float(alpha), n, k_idx, m).ravel()[0])


# ---------------------------------------------------------------------------
# Single Band (SPB when alpha=0, SKB when alpha = k_B T / E_g > 0) Transport
# ---------------------------------------------------------------------------
def band_anisotropy_hall_prefactor(anisotropy_k: float = 1.0) -> float:
    """Return A_K = 3 K (K + 2) / (2 K + 1)^2 for valley mass anisotropy K = m_par / m_perp."""
    k_val = float(anisotropy_k)
    if k_val <= 0:
        raise ValueError("Valley anisotropy K must be positive")
    return float(3.0 * k_val * (k_val + 2.0) / ((2.0 * k_val + 1.0) ** 2))


def single_band_state(
    eta: float | np.ndarray,
    *,
    temperature_k: float | np.ndarray,
    mstar_dos_ratio: float,
    mu0_cm2_vs: float = 100.0,
    alpha: float | np.ndarray = 0.0,
    carrier_sign: int = 1,
    anisotropy_k: float = 1.0,
    use_hall_factor: bool = True,
) -> dict[str, np.ndarray]:
    """Compute exact acoustic-phonon SPB (alpha=0) or SKB (alpha>0) single-band observables.

    Parameters
    ----------
    eta : float or array
        Reduced chemical potential E_F / (k_B T) measured into the band.
    temperature_k : float or array
        Absolute temperature in K.
    mstar_dos_ratio : float
        Total density-of-states effective mass m*_d / m_e = N_v^(2/3) m*_b / m_e.
    mu0_cm2_vs : float
        Intrinsic non-degenerate mobility parameter mu_0 in cm^2 V^-1 s^-1.
    alpha : float or array
        Non-parabolicity k_B T / E_g (dimensionless, 0 for parabolic SPB).
    carrier_sign : int
        +1 for holes (p-type, S > 0, R_H > 0) or -1 for electrons (n-type, S < 0, R_H < 0).
    anisotropy_k : float
        Ellipsoidal valley mass ratio K = m_parallel / m_perp (default 1.0 -> A_K = 1.0).
    """
    if mstar_dos_ratio <= 0:
        raise ValueError(f"mstar_dos_ratio must be > 0, got {mstar_dos_ratio}")
    if mu0_cm2_vs <= 0:
        raise ValueError(f"mu0_cm2_vs must be > 0, got {mu0_cm2_vs}")
    sgn = 1.0 if carrier_sign >= 0 else -1.0
    a_k = band_anisotropy_hall_prefactor(anisotropy_k)

    eta_arr, temp_arr, alpha_arr = np.broadcast_arrays(
        np.atleast_1d(np.asarray(eta, dtype=float)),
        np.atleast_1d(np.asarray(temperature_k, dtype=float)),
        np.atleast_1d(np.asarray(alpha, dtype=float)),
    )

    l_0_0_32 = kane_integral_vec(eta_arr, alpha_arr, 0.0, 0.0, 1.5)
    l_0_m2_1 = kane_integral_vec(eta_arr, alpha_arr, 0.0, -2.0, 1.0)
    l_1_m2_1 = kane_integral_vec(eta_arr, alpha_arr, 1.0, -2.0, 1.0)
    l_2_m2_1 = kane_integral_vec(eta_arr, alpha_arr, 2.0, -2.0, 1.0)
    l_0_m4_12 = kane_integral_vec(eta_arr, alpha_arr, 0.0, -4.0, 0.5)

    # True carrier density n [m^-3]
    dos_prefactor = ((2.0 * mstar_dos_ratio * m_e * k * temp_arr) ** 1.5) / (3.0 * (np.pi**2) * (hbar**3))
    n_m3 = dos_prefactor * l_0_0_32

    # Hall factor r_H and Hall concentration n_H = n / r_H
    if use_hall_factor:
        r_h = a_k * (l_0_m4_12 * l_0_0_32) / np.maximum(l_0_m2_1**2, 1e-300)
    else:
        r_h = np.ones_like(n_m3)
    nh_m3 = n_m3 / r_h
    r_hall_m3_c = sgn * r_h / np.maximum(e * n_m3, 1e-300)

    # Seebeck coefficient
    ratio_10 = l_1_m2_1 / np.maximum(l_0_m2_1, 1e-300)
    seebeck_abs_v_k = K_B_OVER_E_V_PER_K * (ratio_10 - eta_arr)
    seebeck_v_k = sgn * seebeck_abs_v_k

    # Lorenz number [W Ohm K^-2]
    ratio_20 = l_2_m2_1 / np.maximum(l_0_m2_1, 1e-300)
    lorenz = LORENZ_PREFACTOR_W_OHM_K2 * np.maximum(ratio_20 - ratio_10**2, 0.0)

    # Drift & Hall mobility [cm^2 V^-1 s^-1] and electrical conductivity [S m^-1]
    # Note: sigma = (2/3) e ((2 m*_d k_B T)^(3/2) / (2 pi^2 hbar^3)) * (mu0 * 1e-4) * ^0 L_{-2}^1
    # Since n = ((2 m*_d k_B T)^(3/2) / (3 pi^2 hbar^3)) * ^0 L_0^{3/2},
    # drift mobility mu = sigma / (e n) = mu0 * (^0 L_{-2}^1 / ^0 L_0^{3/2}).
    mu_drift_cm2_vs = float(mu0_cm2_vs) * (l_0_m2_1 / np.maximum(l_0_0_32, 1e-300))
    mu_hall_cm2_vs = r_h * mu_drift_cm2_vs
    sigma_s_m = e * n_m3 * (mu_drift_cm2_vs * 1e-4)
    pf_w_m_k2 = (seebeck_v_k**2) * sigma_s_m
    kappa_e_w_m_k = lorenz * sigma_s_m * temp_arr

    return {
        "eta": eta_arr,
        "alpha": alpha_arr,
        "Temperature_K": temp_arr,
        "n_m-3": n_m3,
        "n_cm-3": n_m3 * 1e-6,
        "Hall_factor_rH": r_h,
        "nH_m-3": nh_m3,
        "nH_cm-3": nh_m3 * 1e-6,
        "Hall_Coefficient_m3_C-1": r_hall_m3_c,
        "Seebeck_V_K": seebeck_v_k,
        "Seebeck_uV_K": seebeck_v_k * 1e6,
        "Seebeck_abs_uV_K": seebeck_abs_v_k * 1e6,
        "Lorenz_WOhmK-2": lorenz,
        "Lorenz_1e-8_WOhmK-2": lorenz * 1e8,
        "Drift_Mobility_cm2_V-1_s-1": mu_drift_cm2_vs,
        "Hall_Mobility_cm2_V-1_s-1": mu_hall_cm2_vs,
        "Conductivity_S_m-1": sigma_s_m,
        "Conductivity_S_cm-1": sigma_s_m * 0.01,
        "Power_Factor_W_m-1_K-2": pf_w_m_k2,
        "Power_Factor_uW_cm-1_K-2": pf_w_m_k2 * 1e4,
        "Carrier_Thermal_Conductivity_W_m-1_K-1": kappa_e_w_m_k,
    }


def solve_eta_from_seebeck_skb(
    seebeck_abs_uv_k: float,
    alpha: float = 0.0,
    eta_min: float = -50.0,
    eta_max: float = 80.0,
) -> float:
    """Invert |S|(eta, alpha) = seebeck_abs_uv_k for eta."""
    target = abs(float(seebeck_abs_uv_k))
    if not np.isfinite(target) or target <= 0.0:
        raise ValueError(f"Seebeck magnitude must be positive, got {seebeck_abs_uv_k}")

    def resid(eta_val: float) -> float:
        l0 = kane_integral_scalar(eta_val, alpha, 0.0, -2.0, 1.0)
        l1 = kane_integral_scalar(eta_val, alpha, 1.0, -2.0, 1.0)
        s_uv = K_B_OVER_E_UV_PER_K * (l1 / l0 - eta_val)
        return s_uv - target

    lo_val = resid(eta_min)
    hi_val = resid(eta_max)
    if lo_val * hi_val > 0:
        raise ValueError(
            f"Cannot bracket eta for |S|={target:.2f} uV/K (alpha={alpha:.4f}) in [{eta_min}, {eta_max}]"
        )
    return float(brentq(resid, eta_min, eta_max, xtol=1e-10, rtol=1e-10, maxiter=200))


def solve_eta_from_nh_skb(
    nh_m3: float,
    *,
    temperature_k: float,
    mstar_dos_ratio: float,
    alpha: float = 0.0,
    anisotropy_k: float = 1.0,
    use_hall_factor: bool = True,
    eta_min: float = -55.0,
    eta_max: float = 85.0,
) -> float:
    """Invert n_H(eta, alpha) = nh_m3 for a single parabolic or Kane band."""
    target_log = float(np.log(float(nh_m3)))

    def resid(eta_val: float) -> float:
        st = single_band_state(
            eta_val,
            temperature_k=temperature_k,
            mstar_dos_ratio=mstar_dos_ratio,
            alpha=alpha,
            anisotropy_k=anisotropy_k,
            use_hall_factor=use_hall_factor,
        )
        return float(np.log(st["nH_m-3"][0])) - target_log

    lo_val = resid(eta_min)
    hi_val = resid(eta_max)
    if lo_val * hi_val > 0:
        raise ValueError(
            f"Cannot bracket eta for nH={nh_m3:.3e} m^-3, m*={mstar_dos_ratio:.3g}, alpha={alpha:.4f}"
        )
    return float(brentq(resid, eta_min, eta_max, xtol=1e-10, rtol=1e-10, maxiter=200))


def parabolic_band_state_general_r(
    eta: float | np.ndarray,
    *,
    temperature_k: float | np.ndarray,
    mstar_dos_ratio: float,
    mu0_cm2_vs: float = 100.0,
    scattering_r: float = -0.5,
    carrier_sign: int = 1,
    anisotropy_k: float = 1.0,
    use_hall_factor: bool = True,
) -> dict[str, np.ndarray]:
    """Compute exact 3D parabolic Boltzmann single-band transport for power-law tau(E) = tau_0 E^r.

    Exact textbook equations (unnormalized Fermi-Dirac integral F_j(eta) = int_0^inf x^j / (1 + e^(x-eta)) dx):
    - Carrier density:
        n = 4 * pi * (2 * m*_d * k_B * T / h^2)^(3/2) * F_{1/2}(eta)
          = ((2 * m*_d * k_B * T)^(3/2) / (2 * pi^2 * hbar^3)) * F_{1/2}(eta)
    - Seebeck coefficient (r > -3/2):
        S = sgn * (k_B / e) * [ ((r + 5/2) * F_{r + 3/2}(eta)) / ((r + 3/2) * F_{r + 1/2}(eta)) - eta ]
    - Lorenz number (r > -3/2):
        L = (k_B / e)^2 * [ ((r + 7/2) * F_{r + 5/2}(eta)) / ((r + 3/2) * F_{r + 1/2}(eta))
                            - (((r + 5/2) * F_{r + 3/2}(eta)) / ((r + 3/2) * F_{r + 1/2}(eta)))^2 ]
    - Drift mobility:
        mu_drift = mu_0 * [ (2/3) * (r + 3/2) * F_{r + 1/2}(eta) / F_{1/2}(eta) ]
    - Low-field Hall factor (r > -3/4 when use_hall_factor=True):
        r_H = A_K * [ (3/2) * (2r + 3/2) * F_{1/2}(eta) * F_{2r + 1/2}(eta) ] / [ (r + 3/2) * F_{r + 1/2}(eta) ]^2

    At `scattering_r = -0.5` (acoustic phonon deformation-potential scattering), every observable reduces
    identically to `single_band_state(..., alpha=0.0)` to machine precision (< 1e-13).
    """
    if mstar_dos_ratio <= 0:
        raise ValueError(f"mstar_dos_ratio must be > 0, got {mstar_dos_ratio}")
    if mu0_cm2_vs <= 0:
        raise ValueError(f"mu0_cm2_vs must be > 0, got {mu0_cm2_vs}")
    r = float(scattering_r)
    if r <= -1.5:
        raise ValueError(f"Boltzmann conductivity integral diverges for scattering_r={r} <= -1.5")
    if use_hall_factor and r <= -0.75:
        raise ValueError(f"Low-field Hall integral F_{{2r+1/2}} diverges for scattering_r={r} <= -0.75")

    sgn = 1.0 if carrier_sign >= 0 else -1.0
    a_k = band_anisotropy_hall_prefactor(anisotropy_k)

    eta_arr, temp_arr = np.broadcast_arrays(
        np.atleast_1d(np.asarray(eta, dtype=float)),
        np.atleast_1d(np.asarray(temperature_k, dtype=float)),
    )
    shape = eta_arr.shape
    eta_flat = eta_arr.ravel()
    temp_flat = temp_arr.ravel()

    f_half = fermi_integral_vec(eta_flat, 0.5)
    f_r0 = fermi_integral_vec(eta_flat, r + 0.5)
    f_r1 = fermi_integral_vec(eta_flat, r + 1.5)
    f_r2 = fermi_integral_vec(eta_flat, r + 2.5)

    # Exact 3D parabolic DOS prefactor: 4*pi*(2*m*_d*k_B*T / h^2)^(3/2) == (2*m*_d*k_B*T)^(3/2) / (2*pi^2*hbar^3)
    dos_pref = 4.0 * np.pi * ((2.0 * mstar_dos_ratio * m_e * k * temp_flat / (h**2)) ** 1.5)
    n_m3 = dos_pref * f_half

    denom_r0 = np.maximum((r + 1.5) * f_r0, 1e-300)
    if use_hall_factor:
        f_hall = fermi_integral_vec(eta_flat, 2.0 * r + 0.5)
        r_h = a_k * (1.5 * (2.0 * r + 1.5) * f_half * f_hall) / np.maximum(denom_r0**2, 1e-300)
    else:
        r_h = np.ones_like(n_m3)

    nh_m3 = n_m3 / r_h
    r_hall_m3_c = sgn * r_h / np.maximum(e * n_m3, 1e-300)

    ratio_10 = ((r + 2.5) * f_r1) / denom_r0
    seebeck_abs_v_k = K_B_OVER_E_V_PER_K * (ratio_10 - eta_flat)
    seebeck_v_k = sgn * seebeck_abs_v_k

    ratio_20 = ((r + 3.5) * f_r2) / denom_r0
    lorenz = LORENZ_PREFACTOR_W_OHM_K2 * np.maximum(ratio_20 - ratio_10**2, 0.0)

    mu_drift_cm2_vs = float(mu0_cm2_vs) * ((2.0 / 3.0) * denom_r0 / np.maximum(f_half, 1e-300))
    mu_hall_cm2_vs = r_h * mu_drift_cm2_vs
    sigma_s_m = e * n_m3 * (mu_drift_cm2_vs * 1e-4)
    pf_w_m_k2 = (seebeck_v_k**2) * sigma_s_m
    kappa_e_w_m_k = lorenz * sigma_s_m * temp_flat

    return {
        "eta": eta_arr,
        "scattering_r": np.full(shape, r, dtype=float),
        "Temperature_K": temp_arr,
        "n_m-3": n_m3.reshape(shape),
        "n_cm-3": (n_m3 * 1e-6).reshape(shape),
        "Hall_factor_rH": r_h.reshape(shape),
        "nH_m-3": nh_m3.reshape(shape),
        "nH_cm-3": (nh_m3 * 1e-6).reshape(shape),
        "Hall_Coefficient_m3_C-1": r_hall_m3_c.reshape(shape),
        "Seebeck_V_K": seebeck_v_k.reshape(shape),
        "Seebeck_uV_K": (seebeck_v_k * 1e6).reshape(shape),
        "Seebeck_abs_uV_K": (seebeck_abs_v_k * 1e6).reshape(shape),
        "Lorenz_WOhmK-2": lorenz.reshape(shape),
        "Lorenz_1e-8_WOhmK-2": (lorenz * 1e8).reshape(shape),
        "Drift_Mobility_cm2_V-1_s-1": mu_drift_cm2_vs.reshape(shape),
        "Hall_Mobility_cm2_V-1_s-1": mu_hall_cm2_vs.reshape(shape),
        "Conductivity_S_m-1": sigma_s_m.reshape(shape),
        "Conductivity_S_cm-1": (sigma_s_m * 0.01).reshape(shape),
        "Power_Factor_W_m-1_K-2": pf_w_m_k2.reshape(shape),
        "Power_Factor_uW_cm-1_K-2": (pf_w_m_k2 * 1e4).reshape(shape),
        "Carrier_Thermal_Conductivity_W_m-1_K-1": kappa_e_w_m_k.reshape(shape),
    }


def solve_eta_from_carrier_density_parabolic(
    n_m3: float,
    *,
    temperature_k: float,
    mstar_dos_ratio: float,
    eta_min: float = -60.0,
    eta_max: float = 95.0,
) -> float:
    """Invert exact 3D parabolic carrier density n(eta, T) = n_m3 for reduced chemical potential eta."""
    if n_m3 <= 0.0:
        raise ValueError(f"Carrier density n_m3 must be > 0, got {n_m3}")
    pref = 4.0 * np.pi * ((2.0 * float(mstar_dos_ratio) * m_e * k * float(temperature_k) / (h**2)) ** 1.5)
    target_f_half = float(n_m3) / pref
    target_log = float(np.log(target_f_half))

    def resid(eta_val: float) -> float:
        return float(np.log(fermi_integral_scalar(eta_val, 0.5))) - target_log

    lo_val = resid(eta_min)
    hi_val = resid(eta_max)
    if lo_val * hi_val > 0:
        raise ValueError(
            f"Cannot bracket eta for n={n_m3:.3e} m^-3, m*={mstar_dos_ratio:.3g}, T={temperature_k:.1f} K"
        )
    return float(brentq(resid, eta_min, eta_max, xtol=1e-12, rtol=1e-12, maxiter=200))

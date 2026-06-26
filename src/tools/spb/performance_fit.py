"""Fit SPB PF and zT curves from Hall nH, Seebeck, PF, and zT data."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.constants import e, hbar, k, m_e


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.spb.effective_mass_fit import (  # noqa: E402
    DEFAULT_NH_COLUMN_CANDIDATES,
    DEFAULT_SEEBECK_COLUMN_CANDIDATES,
    EffectiveMassFitConfig,
    SPB_FIT_STYLE_KEYS,
    _convert_nh_to_m3,
    _convert_seebeck_to_uv,
    _find_column,
    add_point_effective_mass_estimates,
    apply_plot_overrides,
    build_multi_property_plot_overrides,
    copy_figures_to_input_data_dir,
    curve_nh_bounds_from_points,
    eta_from_nh_and_mstar,
    fermi_integral,
    fit_global_effective_mass,
    first_present,
    group_color,
    group_label_from_params,
    group_marker,
    group_temperature,
    is_blank_value,
    optional_bool,
    optional_float,
    parse_output_formats,
    parsed_x_curve_xlim,
    read_group_params,
    resolve_group_by_for_cli,
    safe_path_fragment,
    filter_source_by_groups,
    selector_display_label,
    seebeck_abs_uv_from_eta,
    series_style,
)


PF_COLUMN_CANDIDATES = (
    "PF",
    "Power_Factor",
    "power_factor",
    "Power Factor",
    "PF_uW_cm-1_K-2",
    "Power_Factor_uW_cm-1_K-2",
)

ZT_COLUMN_CANDIDATES = (
    "ZT",
    "zT",
    "zt",
    "ZT_value",
)

PROPERTY_COLUMNS = {
    "pf": {
        "experimental": "Power_Factor_uW_cm-1_K-2",
        "model": "Power_Factor_model_uW_cm-1_K-2",
        "residual": "Power_Factor_residual_uW_cm-1_K-2",
        "output_stem": "pf_fit",
    },
    "zt": {
        "experimental": "ZT",
        "model": "ZT_model",
        "residual": "ZT_residual",
        "output_stem": "zt_fit",
    },
}


@dataclass
class MobilityModel:
    """Carrier-concentration dependent Hall mobility model."""

    model: str
    n_ref_cm3: float
    mu_ref_cm2_vs: float
    alpha: float = 0.0
    source: str = "fit"
    mu0_cm2_vs: float | None = None
    scattering_lambda: float = 0.0
    deformation_potential_eV: float | None = None
    density_kg_m3: float | None = None
    sound_velocity_m_s: float | None = None
    valley_degeneracy: float | None = None
    inertial_mass_over_me: float | None = None
    band_mass_over_me: float | None = None


@dataclass
class PerformanceFitConfig:
    """Configuration for SPB PF/zT performance fitting."""

    temperature: float = 300.0
    nh_unit: str = "cm^-3"
    seebeck_unit: str = "uV/K"
    pf_unit: str = "uW cm^-1 K^-2"
    nh_column: str | None = None
    seebeck_column: str | None = None
    pf_column: str | None = None
    zt_column: str | None = None
    use_hall_factor: bool = True
    eta_min: float = -60.0
    eta_max: float = 80.0
    mstar_min: float = 0.02
    mstar_max: float = 20.0
    mstar_over_me: float | None = None
    curve_points: int = 300
    curve_xlim: tuple[float | None, float | None] | None = None
    mobility_model: str = "spb_u0"
    mobility_u0_cm2_vs: float | None = None
    mobility_cm2_vs: float | None = None
    scattering_lambda: float = 0.0
    deformation_potential_eV: float | None = None
    density_kg_m3: float | None = None
    sound_velocity_m_s: float | None = None
    valley_degeneracy: float = 1.0
    kappa_lattice: str | float | None = None
    properties: tuple[str, ...] | None = None
    figure_formats: tuple[str, ...] = ("png", "pdf")


def normalize_unit(unit: str) -> str:
    return (
        str(unit)
        .strip()
        .lower()
        .replace("μ", "u")
        .replace("µ", "u")
        .replace("micro", "u")
        .replace(" ", "")
        .replace("_", "")
        .replace("/", "")
        .replace("**", "^")
    )


def convert_pf_to_uw_cm(values: pd.Series, unit: str) -> pd.Series:
    """Convert power factor to uW cm^-1 K^-2."""

    normalized = normalize_unit(unit)
    if normalized in {
        "uwcm^-1k^-2",
        "uwcm-1k-2",
        "uwcm^-1k^-2.",
        "uw/cm/k^2",
        "uwcm^-1/k^2",
        "uwcmk^2",
        "uwcmk-2",
    }:
        return values.astype(float)
    if normalized in {
        "wm^-1k^-2",
        "wm-1k-2",
        "wm^-1/k^2",
        "wmk^-2",
        "w/m/k^2",
        "wmk^2",
        "wmk-2",
    }:
        return values.astype(float) / 1e-4
    raise ValueError(f"Unsupported power-factor unit: {unit}")


def pf_uw_cm_to_si(values: pd.Series | np.ndarray | float) -> pd.Series | np.ndarray | float:
    """Convert uW cm^-1 K^-2 to W m^-1 K^-2."""

    return values * 1e-4


def optional_find_column(df: pd.DataFrame, preferred: str | None, candidates: tuple[str, ...]) -> str | None:
    try:
        return _find_column(df, preferred, candidates)
    except ValueError:
        if preferred:
            raise
        return None


def effective_mass_config(config: PerformanceFitConfig) -> EffectiveMassFitConfig:
    return EffectiveMassFitConfig(
        temperature=config.temperature,
        nh_unit=config.nh_unit,
        seebeck_unit=config.seebeck_unit,
        nh_column=config.nh_column,
        seebeck_column=config.seebeck_column,
        use_hall_factor=config.use_hall_factor,
        eta_min=config.eta_min,
        eta_max=config.eta_max,
        mstar_min=config.mstar_min,
        mstar_max=config.mstar_max,
        curve_points=config.curve_points,
        curve_xlim=config.curve_xlim,
        figure_formats=config.figure_formats,
    )


def prepare_performance_input_table(
    csv_path: str | os.PathLike,
    config: PerformanceFitConfig,
) -> tuple[pd.DataFrame, dict[str, str | None]]:
    """Load and normalize nH, Seebeck, PF, and zT columns."""

    df = pd.read_csv(csv_path)
    nh_column = _find_column(df, config.nh_column, DEFAULT_NH_COLUMN_CANDIDATES)
    seebeck_column = _find_column(df, config.seebeck_column, DEFAULT_SEEBECK_COLUMN_CANDIDATES)
    pf_column = optional_find_column(df, config.pf_column, PF_COLUMN_CANDIDATES)
    zt_column = optional_find_column(df, config.zt_column, ZT_COLUMN_CANDIDATES)

    result = df.copy()
    result["nH_cm-3"] = _convert_nh_to_m3(result[nh_column], config.nh_unit) / 1e6
    result["nH_m-3"] = _convert_nh_to_m3(result[nh_column], config.nh_unit)
    result["Seebeck_uV_K"] = _convert_seebeck_to_uv(result[seebeck_column], config.seebeck_unit)
    result["Seebeck_abs_uV_K"] = result["Seebeck_uV_K"].abs()
    result["Temperature_K"] = config.temperature

    if pf_column:
        result["Power_Factor_uW_cm-1_K-2"] = convert_pf_to_uw_cm(result[pf_column], config.pf_unit)
        result["Power_Factor_W_m-1_K-2"] = pf_uw_cm_to_si(result["Power_Factor_uW_cm-1_K-2"])
    if zt_column:
        result["ZT"] = pd.to_numeric(result[zt_column], errors="coerce")

    required = ["nH_m-3", "Seebeck_abs_uV_K"]
    result = result.replace([np.inf, -np.inf], np.nan).dropna(subset=required).reset_index(drop=True)
    result = result[(result["nH_m-3"] > 0) & (result["Seebeck_abs_uV_K"] > 0)].reset_index(drop=True)
    if result.empty:
        raise ValueError("No positive finite nH/Seebeck rows remain after cleaning")

    columns = {
        "nh": nh_column,
        "seebeck": seebeck_column,
        "pf": pf_column,
        "zt": zt_column,
    }
    return result, columns


def lorenz_number_from_eta(eta: float) -> float:
    """SPB Lorenz number in W Ohm K^-2 for the same acoustic model."""

    f0 = fermi_integral(eta, 0.0)
    f1 = fermi_integral(eta, 1.0)
    f2 = fermi_integral(eta, 2.0)
    return float((k**2 / e**2) * (3.0 * f0 * f2 - 4.0 * f1**2) / (f0**2))


def hall_mobility_factor_from_eta(eta: float, scattering_lambda: float = 0.0) -> float:
    """Return mu_H / mu0 from the SPB scattering mobility expression."""

    lam = float(scattering_lambda)
    if lam <= -0.25:
        raise ValueError("scattering lambda must be greater than -0.25 for the mu_H(mu0) formula.")
    numerator_order = 2.0 * lam - 0.5
    denominator_order = lam
    prefactor = (0.5 + 2.0 * lam) / (1.0 + lam)
    return float(prefactor * fermi_integral(eta, numerator_order) / fermi_integral(eta, denominator_order))


def band_mass_from_dos_mass(mstar_over_me: float, valley_degeneracy: float) -> float:
    """Convert DOS effective mass to single-valley band/inertial mass."""

    nv = float(valley_degeneracy)
    if nv <= 0:
        raise ValueError("valley degeneracy Nv must be positive")
    return float(mstar_over_me) / (nv ** (2.0 / 3.0))


def mu0_from_deformation_potential_cm2_vs(
    mstar_over_me: float,
    temperature: float,
    density_kg_m3: float,
    sound_velocity_m_s: float,
    deformation_potential_eV: float,
    valley_degeneracy: float = 1.0,
) -> tuple[float, float, float]:
    """Compute mu0 from the acoustic deformation-potential expression."""

    if density_kg_m3 <= 0:
        raise ValueError("density must be positive")
    if sound_velocity_m_s <= 0:
        raise ValueError("sound velocity must be positive")
    if deformation_potential_eV <= 0:
        raise ValueError("deformation potential Xi must be positive")

    band_mass_over_me = band_mass_from_dos_mass(mstar_over_me, valley_degeneracy)
    inertial_mass_over_me = band_mass_over_me
    band_mass_kg = band_mass_over_me * m_e
    inertial_mass_kg = inertial_mass_over_me * m_e
    xi_joule = deformation_potential_eV * e
    numerator = e * np.pi * hbar**4 * density_kg_m3 * sound_velocity_m_s**2
    denominator = np.sqrt(2.0 * inertial_mass_kg) * (band_mass_kg * k * temperature) ** 1.5 * xi_joule**2
    mu0_m2_vs = numerator / denominator
    return float(mu0_m2_vs * 1e4), float(inertial_mass_over_me), float(band_mass_over_me)


def deformation_potential_from_mu0_eV(
    mu0_cm2_vs: float,
    mstar_over_me: float,
    temperature: float,
    density_kg_m3: float,
    sound_velocity_m_s: float,
    valley_degeneracy: float = 1.0,
) -> tuple[float, float, float]:
    """Back-calculate Xi from a fitted mu0 and material parameters."""

    if mu0_cm2_vs <= 0:
        raise ValueError("mu0 must be positive")
    if density_kg_m3 <= 0:
        raise ValueError("density must be positive")
    if sound_velocity_m_s <= 0:
        raise ValueError("sound velocity must be positive")

    band_mass_over_me = band_mass_from_dos_mass(mstar_over_me, valley_degeneracy)
    inertial_mass_over_me = band_mass_over_me
    band_mass_kg = band_mass_over_me * m_e
    inertial_mass_kg = inertial_mass_over_me * m_e
    mu0_m2_vs = mu0_cm2_vs / 1e4
    numerator = e * np.pi * hbar**4 * density_kg_m3 * sound_velocity_m_s**2
    denominator_without_xi = np.sqrt(2.0 * inertial_mass_kg) * (band_mass_kg * k * temperature) ** 1.5
    xi_joule = np.sqrt(numerator / (denominator_without_xi * mu0_m2_vs))
    return float(xi_joule / e), float(inertial_mass_over_me), float(band_mass_over_me)


def add_theoretical_spb_at_points(
    points: pd.DataFrame,
    mstar_over_me: float,
    config: PerformanceFitConfig,
) -> pd.DataFrame:
    """Add theoretical S/L at measured nH and mobility estimates from PF/S_theory^2."""

    result = points.copy()
    em_config = effective_mass_config(config)

    eta_values = []
    seebeck_model_values = []
    lorenz_values = []
    for _, row in result.iterrows():
        eta = eta_from_nh_and_mstar(float(row["nH_m-3"]), mstar_over_me, em_config)
        eta_values.append(eta)
        seebeck_model_values.append(seebeck_abs_uv_from_eta(eta))
        lorenz_values.append(lorenz_number_from_eta(eta))

    result["eta_model_from_nH"] = eta_values
    result["Seebeck_model_abs_uV_K"] = seebeck_model_values
    result["Seebeck_model_residual_uV_K"] = result["Seebeck_model_abs_uV_K"] - result["Seebeck_abs_uV_K"]
    result["Lorenz_model_WOhmK-2"] = lorenz_values
    result["Lorenz_model_1e-8_WOhmK-2"] = result["Lorenz_model_WOhmK-2"] * 1e8

    if "Power_Factor_W_m-1_K-2" in result.columns:
        seebeck_model_v_k = result["Seebeck_model_abs_uV_K"] * 1e-6
        sigma = result["Power_Factor_W_m-1_K-2"] / (seebeck_model_v_k * seebeck_model_v_k)
        mu_cm2_vs = sigma / (result["nH_m-3"] * e) * 1e4
        result["Conductivity_fit_from_PF_Smodel_S_m-1"] = sigma
        result["Conductivity_fit_from_PF_Smodel_S_cm-1"] = sigma * 0.01
        result["Hall_Mobility_fit_from_PF_Smodel_cm2_V-1_s-1"] = mu_cm2_vs
        result["Carrier_Thermal_Conductivity_fit_from_PF_Smodel_W_m-1_K-1"] = (
            result["Lorenz_model_WOhmK-2"] * sigma * result["Temperature_K"]
        )
        if "ZT" in result.columns:
            kappa_total = result["Power_Factor_W_m-1_K-2"] * result["Temperature_K"] / result["ZT"]
            result["Thermal_Conductivity_from_ZT_W_m-1_K-1"] = kappa_total
            result["Lattice_Thermal_Conductivity_apparent_from_Smodel_W_m-1_K-1"] = (
                kappa_total - result["Carrier_Thermal_Conductivity_fit_from_PF_Smodel_W_m-1_K-1"]
            )

    return result


def fit_mu0_from_pf(working: pd.DataFrame, scattering_lambda: float) -> float:
    seebeck_model_v_k = working["Seebeck_model_abs_uV_K"].to_numpy(dtype=float) * 1e-6
    eta_values = working["eta_model_from_nH"].to_numpy(dtype=float)
    mobility_factors = np.asarray(
        [hall_mobility_factor_from_eta(eta, scattering_lambda) for eta in eta_values],
        dtype=float,
    )
    x = (
        seebeck_model_v_k
        * seebeck_model_v_k
        * working["nH_m-3"].to_numpy(dtype=float)
        * e
        * 1e-4
        * mobility_factors
    )
    y = working["Power_Factor_W_m-1_K-2"].to_numpy(dtype=float)
    return float(np.sum(x * y) / np.sum(x * x))


def fit_mobility_model(
    points: pd.DataFrame,
    config: PerformanceFitConfig,
    mstar_over_me: float,
) -> MobilityModel:
    """Fit or set a Hall mobility model in cm^2 V^-1 s^-1."""

    n_values = points["nH_cm-3"].to_numpy(dtype=float)
    n_ref = float(np.exp(np.mean(np.log(n_values))))

    if config.mobility_u0_cm2_vs is not None:
        if config.mobility_u0_cm2_vs <= 0:
            raise ValueError("--u0/--mu0 must be positive")
        hall_mobility_factor_from_eta(0.0, config.scattering_lambda)
        return MobilityModel(
            model="spb_u0",
            n_ref_cm3=n_ref,
            mu_ref_cm2_vs=float(config.mobility_u0_cm2_vs),
            source="fixed",
            mu0_cm2_vs=float(config.mobility_u0_cm2_vs),
            scattering_lambda=float(config.scattering_lambda),
        )

    if config.mobility_model == "deformation_potential" and config.deformation_potential_eV is not None:
        if config.density_kg_m3 is None or config.sound_velocity_m_s is None:
            raise ValueError("deformation-potential mobility needs --rho and --vl.")
        mu0, inertial_mass, band_mass = mu0_from_deformation_potential_cm2_vs(
            mstar_over_me,
            config.temperature,
            config.density_kg_m3,
            config.sound_velocity_m_s,
            config.deformation_potential_eV,
            config.valley_degeneracy,
        )
        return MobilityModel(
            model="deformation_potential",
            n_ref_cm3=n_ref,
            mu_ref_cm2_vs=mu0,
            source="fixed_xi",
            mu0_cm2_vs=mu0,
            scattering_lambda=float(config.scattering_lambda),
            deformation_potential_eV=float(config.deformation_potential_eV),
            density_kg_m3=float(config.density_kg_m3),
            sound_velocity_m_s=float(config.sound_velocity_m_s),
            valley_degeneracy=float(config.valley_degeneracy),
            inertial_mass_over_me=inertial_mass,
            band_mass_over_me=band_mass,
        )

    if config.mobility_cm2_vs is not None:
        if config.mobility_cm2_vs <= 0:
            raise ValueError("--mobility-cm2-vs must be positive")
        return MobilityModel(
            model="constant",
            n_ref_cm3=n_ref,
            mu_ref_cm2_vs=float(config.mobility_cm2_vs),
            source="fixed",
        )

    mobility_column = "Hall_Mobility_fit_from_PF_Smodel_cm2_V-1_s-1"
    if mobility_column not in points.columns:
        raise ValueError("PF data, --u0/--mu0, or --mobility-cm2-vs is required to estimate mobility.")

    required = [
        "nH_cm-3",
        mobility_column,
        "Power_Factor_W_m-1_K-2",
        "Seebeck_model_abs_uV_K",
        "nH_m-3",
        "eta_model_from_nH",
    ]
    working = points[required].replace([np.inf, -np.inf], np.nan).dropna()
    working = working[(working["nH_cm-3"] > 0) & (working[mobility_column] > 0)]
    if working.empty:
        raise ValueError("No positive finite mobility estimates are available from PF/S_theory^2.")

    n_fit = working["nH_cm-3"].to_numpy(dtype=float)
    mu_fit = working[mobility_column].to_numpy(dtype=float)
    n_ref = float(np.exp(np.mean(np.log(n_fit))))

    if config.mobility_model == "spb_u0":
        mu0 = fit_mu0_from_pf(working, config.scattering_lambda)
        return MobilityModel(
            model="spb_u0",
            n_ref_cm3=n_ref,
            mu_ref_cm2_vs=mu0,
            source="fit",
            mu0_cm2_vs=mu0,
            scattering_lambda=float(config.scattering_lambda),
        )

    if config.mobility_model == "deformation_potential":
        if config.density_kg_m3 is None or config.sound_velocity_m_s is None:
            raise ValueError("deformation-potential fitting needs --rho and --vl.")
        mu0 = fit_mu0_from_pf(working, config.scattering_lambda)
        xi_eV, inertial_mass, band_mass = deformation_potential_from_mu0_eV(
            mu0,
            mstar_over_me,
            config.temperature,
            config.density_kg_m3,
            config.sound_velocity_m_s,
            config.valley_degeneracy,
        )
        return MobilityModel(
            model="deformation_potential",
            n_ref_cm3=n_ref,
            mu_ref_cm2_vs=mu0,
            source="fit_xi",
            mu0_cm2_vs=mu0,
            scattering_lambda=float(config.scattering_lambda),
            deformation_potential_eV=xi_eV,
            density_kg_m3=float(config.density_kg_m3),
            sound_velocity_m_s=float(config.sound_velocity_m_s),
            valley_degeneracy=float(config.valley_degeneracy),
            inertial_mass_over_me=inertial_mass,
            band_mass_over_me=band_mass,
        )

    if config.mobility_model == "constant" or len(working) == 1:
        seebeck_model_v_k = working["Seebeck_model_abs_uV_K"].to_numpy(dtype=float) * 1e-6
        x = seebeck_model_v_k * seebeck_model_v_k * working["nH_m-3"].to_numpy(dtype=float) * e * 1e-4
        y = working["Power_Factor_W_m-1_K-2"].to_numpy(dtype=float)
        mu_ref = float(np.sum(x * y) / np.sum(x * x))
        return MobilityModel(
            model="constant",
            n_ref_cm3=n_ref,
            mu_ref_cm2_vs=mu_ref,
            source="fit",
        )

    x = np.log(n_fit / n_ref)
    y = np.log(mu_fit)
    alpha, log_mu_ref = np.polyfit(x, y, 1)
    return MobilityModel(
        model="power_law",
        n_ref_cm3=n_ref,
        mu_ref_cm2_vs=float(np.exp(log_mu_ref)),
        alpha=float(alpha),
        source="fit",
    )


def mobility_from_model(
    nh_cm3: float | np.ndarray,
    model: MobilityModel,
    eta: float | None = None,
) -> float | np.ndarray:
    if model.model in {"spb_u0", "deformation_potential"}:
        if eta is None:
            raise ValueError("eta is required for SPB mu0/deformation-potential mobility models.")
        mu0 = model.mu0_cm2_vs if model.mu0_cm2_vs is not None else model.mu_ref_cm2_vs
        return mu0 * hall_mobility_factor_from_eta(float(eta), model.scattering_lambda)
    if model.model == "constant":
        return np.ones_like(np.asarray(nh_cm3, dtype=float)) * model.mu_ref_cm2_vs
    return model.mu_ref_cm2_vs * (np.asarray(nh_cm3, dtype=float) / model.n_ref_cm3) ** model.alpha


def resolve_kappa_lattice(points: pd.DataFrame, requested: str | float | None) -> tuple[float | None, str]:
    """Resolve scalar lattice thermal conductivity for zT modeling."""

    if requested is None:
        return None, "none"
    if isinstance(requested, (int, float)):
        value = float(requested)
        if value <= 0:
            raise ValueError("Lattice thermal conductivity must be positive")
        return value, "specified"

    text = str(requested).strip().lower()
    if text in {"", "none", "null"}:
        return None, "none"
    if text == "auto":
        raise ValueError("Please specify --kL/--kappa-lattice as a numeric W m^-1 K^-1 value for zT modeling.")
    value = float(text)
    if value <= 0:
        raise ValueError("Lattice thermal conductivity must be positive")
    return value, "specified"


def fit_effective_mass_value(points: pd.DataFrame, config: PerformanceFitConfig) -> tuple[float, dict[str, Any]]:
    em_config = effective_mass_config(config)
    if config.mstar_over_me is not None:
        if config.mstar_over_me <= 0:
            raise ValueError("--m/--mstar must be positive")
        return float(config.mstar_over_me), {"mode": "fixed_mstar", "mstar_over_me": float(config.mstar_over_me)}

    fit = fit_global_effective_mass(points, em_config)
    return float(fit["mstar_over_me_fit"]), {
        "mode": "fit",
        "mstar_over_me_fit": fit["mstar_over_me_fit"],
        "seebeck_rmse_uV_K": fit["rmse_uV_K"],
        "seebeck_mae_uV_K": fit["mae_uV_K"],
        "seebeck_max_abs_error_uV_K": fit["max_abs_error_uV_K"],
    }


def predict_performance_row(
    nh_cm3: float,
    mstar_over_me: float,
    em_config: EffectiveMassFitConfig,
    mobility_model: MobilityModel,
    kappa_lattice: float | None,
) -> dict[str, float]:
    nh_m3 = float(nh_cm3) * 1e6
    eta = eta_from_nh_and_mstar(nh_m3, mstar_over_me, em_config)
    seebeck_abs_uv = seebeck_abs_uv_from_eta(eta)
    seebeck_v_k = seebeck_abs_uv * 1e-6
    lorenz = lorenz_number_from_eta(eta)
    mu_cm2_vs = float(mobility_from_model(nh_cm3, mobility_model, eta=eta))
    sigma = nh_m3 * e * mu_cm2_vs * 1e-4
    pf_si = seebeck_v_k * seebeck_v_k * sigma
    kappa_e = lorenz * sigma * em_config.temperature

    row = {
        "nH_cm-3": float(nh_cm3),
        "nH_m-3": nh_m3,
        "eta": eta,
        "Seebeck_abs_uV_K": seebeck_abs_uv,
        "Lorenz_Number_WOhmK-2": lorenz,
        "Lorenz_Number_1e-8_WOhmK-2": lorenz * 1e8,
        "Hall_Mobility_model_cm2_V-1_s-1": mu_cm2_vs,
        "Conductivity_model_S_m-1": sigma,
        "Conductivity_model_S_cm-1": sigma * 0.01,
        "Power_Factor_model_W_m-1_K-2": pf_si,
        "Power_Factor_model_uW_cm-1_K-2": pf_si / 1e-4,
        "Carrier_Thermal_Conductivity_model_W_m-1_K-1": kappa_e,
        "Temperature_K": em_config.temperature,
        "mstar_over_me": mstar_over_me,
    }
    if mobility_model.model in {"spb_u0", "deformation_potential"}:
        mu0 = mobility_model.mu0_cm2_vs if mobility_model.mu0_cm2_vs is not None else mobility_model.mu_ref_cm2_vs
        row["Mobility_u0_model_cm2_V-1_s-1"] = mu0
        row["Mobility_scattering_lambda"] = mobility_model.scattering_lambda
        row["Hall_Mobility_factor_from_mu0"] = hall_mobility_factor_from_eta(
            eta,
            mobility_model.scattering_lambda,
        )
        if mobility_model.deformation_potential_eV is not None:
            row["Deformation_Potential_eV"] = mobility_model.deformation_potential_eV
        if mobility_model.valley_degeneracy is not None:
            row["Valley_Degeneracy"] = mobility_model.valley_degeneracy
        if mobility_model.inertial_mass_over_me is not None:
            row["Inertial_Mass_over_me"] = mobility_model.inertial_mass_over_me
        if mobility_model.band_mass_over_me is not None:
            row["Band_Mass_over_me"] = mobility_model.band_mass_over_me
    if kappa_lattice is not None:
        kappa_total = kappa_lattice + kappa_e
        row["Lattice_Thermal_Conductivity_W_m-1_K-1"] = kappa_lattice
        row["Thermal_Conductivity_model_W_m-1_K-1"] = kappa_total
        row["ZT_model"] = pf_si * em_config.temperature / kappa_total
    return row


def build_performance_curve(
    points: pd.DataFrame,
    mstar_over_me: float,
    config: PerformanceFitConfig,
    mobility_model: MobilityModel,
    kappa_lattice: float | None,
) -> pd.DataFrame:
    em_config = effective_mass_config(config)
    nh_min, nh_max = curve_nh_bounds_from_points(points, config.curve_xlim)
    nh_grid = np.logspace(np.log10(nh_min), np.log10(nh_max), config.curve_points)
    rows = [
        predict_performance_row(nh_cm3, mstar_over_me, em_config, mobility_model, kappa_lattice)
        for nh_cm3 in nh_grid
    ]
    return pd.DataFrame(rows)


def add_model_predictions_at_points(
    points: pd.DataFrame,
    mstar_over_me: float,
    config: PerformanceFitConfig,
    mobility_model: MobilityModel,
    kappa_lattice: float | None,
) -> pd.DataFrame:
    em_config = effective_mass_config(config)
    rows = [
        predict_performance_row(nh_cm3, mstar_over_me, em_config, mobility_model, kappa_lattice)
        for nh_cm3 in points["nH_cm-3"].to_numpy(dtype=float)
    ]
    predictions = pd.DataFrame(rows).add_suffix("_at_point")
    predictions = predictions.rename(
        columns={
            "Power_Factor_model_uW_cm-1_K-2_at_point": "Power_Factor_model_uW_cm-1_K-2",
            "ZT_model_at_point": "ZT_model",
        }
    )
    result = pd.concat([points.reset_index(drop=True), predictions.reset_index(drop=True)], axis=1)
    if "Power_Factor_uW_cm-1_K-2" in result.columns:
        result["Power_Factor_residual_uW_cm-1_K-2"] = (
            result["Power_Factor_model_uW_cm-1_K-2"] - result["Power_Factor_uW_cm-1_K-2"]
        )
    if "ZT" in result.columns and "ZT_model" in result.columns:
        result["ZT_residual"] = result["ZT_model"] - result["ZT"]
    return result


def property_rmse(points: pd.DataFrame, property_key: str) -> dict[str, float]:
    columns = PROPERTY_COLUMNS[property_key]
    if columns["experimental"] not in points.columns or columns["model"] not in points.columns:
        return {}
    residual = pd.to_numeric(points[columns["model"]] - points[columns["experimental"]], errors="coerce").dropna()
    if residual.empty:
        return {}
    prefix = "pf" if property_key == "pf" else "zt"
    return {
        f"{prefix}_rmse": float(np.sqrt(np.mean(residual * residual))),
        f"{prefix}_mae": float(np.mean(np.abs(residual))),
        f"{prefix}_max_abs_error": float(np.max(np.abs(residual))),
    }


def infer_properties(points: pd.DataFrame, config: PerformanceFitConfig, kappa_lattice: float | None) -> tuple[str, ...]:
    if config.properties:
        return config.properties

    properties = []
    if "Power_Factor_uW_cm-1_K-2" in points.columns or config.mobility_cm2_vs is not None:
        properties.append("pf")
    if kappa_lattice is not None:
        properties.append("zt")
    return tuple(properties or ("pf",))


def default_performance_recipe(property_key: str) -> dict[str, Any]:
    labels = {
        "pf": {
            "name": "spb_power_factor_fit",
            "ylabel": "$PF$ (\u00b5W cm$^{-1}$ K$^{-2}$)",
            "property": "power_factor",
            "model_label": "SPB PF model",
            "data_label": "PF data",
        },
        "zt": {
            "name": "spb_zt_fit",
            "ylabel": "$zT$",
            "property": "zt",
            "model_label": "SPB zT model",
            "data_label": "zT data",
        },
    }[property_key]
    columns = PROPERTY_COLUMNS[property_key]
    return {
        "name": labels["name"],
        "plot": {
            "kind": "line",
            "x": {"column": "nH_cm-3", "label": r"$n_{\mathrm{H}}$ (cm$^{-3}$)"},
            "series": [
                {
                    "y": {"column": columns["model"], "label": labels["ylabel"]},
                    "property": labels["property"],
                    "group_value": labels["model_label"],
                    "marker": "None",
                    "linestyle": "-",
                    "line_width": 1.4,
                },
                {
                    "y": {"column": columns["experimental"], "label": labels["ylabel"]},
                    "property": labels["property"],
                    "group_value": labels["data_label"],
                    "color": "#e76f6f",
                    "marker": "o",
                    "marker_size": 5.5,
                    "alpha": 0.75,
                    "linestyle": "none",
                    "line_width": 0.0,
                },
            ],
            "xlabel": r"$n_{\mathrm{H}}$ (cm$^{-3}$)",
            "ylabel": labels["ylabel"],
            "xscale": "log",
            "x_log_ticks": "decade",
            "legend": "inside",
            "legend_loc": "best",
            "x_margin": 0.04,
            "y_margin": 0.08,
        },
    }


def load_performance_recipe(property_key: str) -> dict[str, Any]:
    recipe_path = ROOT / f"configs/plot_recipes/spb/{PROPERTY_COLUMNS[property_key]['output_stem']}.json"
    fallback = default_performance_recipe(property_key)
    try:
        with open(recipe_path, "r", encoding="utf-8") as handle:
            recipe = json.load(handle)
    except (OSError, json.JSONDecodeError):
        recipe = fallback

    merged = dict(fallback)
    merged["plot"] = {**fallback["plot"], **recipe.get("plot", {})}
    merged["name"] = recipe.get("name", fallback["name"])
    return merged


def build_property_normalized_table(
    points: pd.DataFrame,
    curve: pd.DataFrame,
    property_key: str,
    recipe: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    plot = recipe.get("plot", {})
    series_specs = plot.get("series") or default_performance_recipe(property_key)["plot"]["series"]
    curve_spec = series_specs[0] if len(series_specs) >= 1 and isinstance(series_specs[0], dict) else {}
    point_spec = series_specs[1] if len(series_specs) >= 2 and isinstance(series_specs[1], dict) else {}
    columns = PROPERTY_COLUMNS[property_key]

    y_selector = curve_spec.get("y", {})
    property_name = str(curve_spec.get("property") or property_key)
    property_label = selector_display_label(y_selector, plot.get("ylabel", property_name))

    frames = []
    curve_group_column = "series_id" if "series_id" in curve.columns else None
    curve_groups = list(curve.groupby(curve_group_column, sort=False)) if curve_group_column else [(None, curve)]
    point_group_column = "point_series_id" if "point_series_id" in points.columns else None
    point_groups = list(points.groupby(point_group_column, sort=False)) if point_group_column else [(None, points)]
    multi_group = len(curve_groups) > 1 or len(point_groups) > 1

    for curve_index, (_, curve_group) in enumerate(curve_groups):
        legend_label = curve_spec.get("legend_label", curve_spec.get("group_value", "SPB model"))
        if "legend_label" in curve_group.columns and not is_blank_value(curve_group["legend_label"].iloc[0]):
            legend_label = str(curve_group["legend_label"].iloc[0])
        curve_frame = pd.DataFrame(
            {
                "x": curve_group["nH_cm-3"].to_numpy(dtype=float),
                "x_category": curve_group["nH_cm-3"].astype(str).to_numpy(),
                "y": curve_group[columns["model"]].to_numpy(dtype=float),
                "property": property_name,
                "group": legend_label,
                "legend_label": legend_label,
                "label": "",
                "condition": "",
                "source": "performance_curve",
                "x_source_column": "nH_cm-3",
                "y_source_column": columns["model"],
                "series_order": curve_index * 2,
            }
        )
        for key in SPB_FIT_STYLE_KEYS:
            curve_frame[key] = series_style(curve_spec, key)
        if multi_group:
            curve_frame["color"] = group_color(curve_index)
        frames.append(curve_frame)

    if columns["experimental"] in points.columns:
        for point_index, (_, point_group) in enumerate(point_groups):
            legend_label = point_spec.get("legend_label", point_spec.get("group_value", "data"))
            if "legend_label" in point_group.columns and not is_blank_value(point_group["legend_label"].iloc[0]):
                legend_label = str(point_group["legend_label"].iloc[0])
            point_frame = pd.DataFrame(
                {
                    "x": point_group["nH_cm-3"].to_numpy(dtype=float),
                    "x_category": point_group["nH_cm-3"].astype(str).to_numpy(),
                    "y": point_group[columns["experimental"]].to_numpy(dtype=float),
                    "property": property_name,
                    "group": legend_label,
                    "legend_label": legend_label,
                    "label": "",
                    "condition": "",
                    "source": "performance_points",
                    "x_source_column": "nH_cm-3",
                    "y_source_column": columns["experimental"],
                    "series_order": point_index * 2 + 1,
                }
            )
            for key in SPB_FIT_STYLE_KEYS:
                point_frame[key] = series_style(point_spec, key)
            if multi_group:
                point_frame["color"] = group_color(point_index)
                point_frame["marker"] = group_marker(point_index)
            frames.append(point_frame)

    normalized = pd.concat(frames, ignore_index=True).dropna(subset=["x", "y"])
    metadata = {
        "x_label": selector_display_label(plot.get("x"), "nH_cm-3"),
        "property_labels": {property_name: property_label},
        "kind": plot.get("kind", "line"),
        "title": plot.get("title", recipe.get("name", "")),
        "categorical_x": False,
        "x_categories": [],
    }
    return normalized, metadata


def plot_property_fit(
    points: pd.DataFrame,
    curve: pd.DataFrame,
    property_key: str,
    output_dir: Path,
    formats: tuple[str, ...],
    show: bool = False,
    defer_show: bool = False,
    plot_overrides: dict | None = None,
) -> list[str]:
    cache_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "te_matplotlib_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))

    from src.tools.flexible_plot import plot_line_or_scatter
    from src.tools.plot import save_figure

    import matplotlib.pyplot as plt

    recipe = apply_plot_overrides(load_performance_recipe(property_key), plot_overrides)
    normalized, metadata = build_property_normalized_table(points, curve, property_key, recipe)
    fig, _ = plot_line_or_scatter(normalized, metadata, recipe)

    output_stem = PROPERTY_COLUMNS[property_key]["output_stem"]
    save_figure(fig, f"{output_stem}.png", save_dir=str(output_dir), formats=formats)
    keep_open_for_group_show = show and defer_show
    if show and not defer_show:
        plt.show()
    if not keep_open_for_group_show:
        plt.close(fig)
    return [str(output_dir / f"{output_stem}.{file_format}") for file_format in formats]


def plot_overrides_for_property(plot_overrides: dict | None, property_key: str) -> dict | None:
    if not plot_overrides:
        return None

    overrides = dict(plot_overrides)
    property_ylims = overrides.pop("property_ylims", {})
    if property_key in property_ylims:
        overrides["ylim"] = property_ylims[property_key]
    return overrides


def show_open_performance_figures() -> None:
    import matplotlib.pyplot as plt

    plt.show()
    plt.close("all")


def run_performance_fit(
    csv_path: str | os.PathLike,
    output_dir: str | os.PathLike,
    config: PerformanceFitConfig | None = None,
    show: bool = False,
    plot_overrides: dict | None = None,
) -> dict[str, Any]:
    config = config or PerformanceFitConfig()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    points, source_columns = prepare_performance_input_table(csv_path, config)
    points = add_point_effective_mass_estimates(points, effective_mass_config(config))

    mstar_over_me, mstar_summary = fit_effective_mass_value(points, config)
    points = add_theoretical_spb_at_points(points, mstar_over_me, config)
    mobility_model = fit_mobility_model(points, config, mstar_over_me)
    kappa_lattice, kappa_lattice_source = resolve_kappa_lattice(points, config.kappa_lattice)
    curve = build_performance_curve(points, mstar_over_me, config, mobility_model, kappa_lattice)
    points = add_model_predictions_at_points(points, mstar_over_me, config, mobility_model, kappa_lattice)

    properties = infer_properties(points, config, kappa_lattice)
    if "zt" in properties and "ZT_model" not in curve.columns:
        raise ValueError("zT modeling needs --kL/--kappa-lattice VALUE.")

    summary: dict[str, Any] = {
        "input_csv": str(csv_path),
        "temperature_K": config.temperature,
        "source_columns": source_columns,
        "config": asdict(config),
        "mstar": mstar_summary,
        "mobility_model": asdict(mobility_model),
        "kappa_lattice_W_m-1_K-1": kappa_lattice,
        "kappa_lattice_source": kappa_lattice_source,
        "properties": list(properties),
        "n_points": int(len(points)),
    }
    for property_key in properties:
        summary.update(property_rmse(points, property_key))

    points_path = output_dir / "performance_points.csv"
    curve_path = output_dir / "performance_curve.csv"
    summary_path = output_dir / "performance_summary.json"
    points.to_csv(points_path, index=False)
    curve.to_csv(curve_path, index=False)
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    plot_paths: dict[str, list[str]] = {}
    data_dir_plot_paths: dict[str, list[str]] = {}
    for property_key in properties:
        plot_paths[property_key] = plot_property_fit(
            points,
            curve,
            property_key,
            output_dir,
            config.figure_formats,
            show=show,
            defer_show=show,
            plot_overrides=plot_overrides_for_property(plot_overrides, property_key),
        )
        data_dir_plot_paths[property_key] = copy_figures_to_input_data_dir(
            plot_paths[property_key],
            csv_path,
        )

    if show:
        show_open_performance_figures()

    return {
        "summary": summary,
        "points_path": str(points_path),
        "curve_path": str(curve_path),
        "summary_path": str(summary_path),
        "plot_paths": plot_paths,
        "data_dir_plot_paths": data_dir_plot_paths,
    }


def optional_text(value: object) -> str | None:
    if is_blank_value(value):
        return None
    return str(value)


def performance_config_for_group(
    base_config: PerformanceFitConfig,
    group_df: pd.DataFrame,
    temperature_column: str | None,
    params_row: pd.Series | None,
) -> PerformanceFitConfig:
    config = PerformanceFitConfig(**asdict(base_config))
    config.temperature = group_temperature(group_df, base_config.temperature, temperature_column, params_row)

    config_mstar = optional_float(first_present(params_row, ("m", "mstar", "mstar_over_me", "effective_mass")))
    if config_mstar is not None:
        config.mstar_over_me = config_mstar

    config_u0 = optional_float(first_present(params_row, ("u0", "mu0", "mobility_u0_cm2_vs")))
    if config_u0 is not None:
        config.mobility_u0_cm2_vs = config_u0

    config_muh = optional_float(first_present(params_row, ("muH", "mobility_cm2_vs", "hall_mobility_cm2_vs")))
    if config_muh is not None:
        config.mobility_cm2_vs = config_muh

    config_kappa_lattice = first_present(params_row, ("kL", "kl", "kappa_lattice", "kappa_lattice_W_m-1_K-1"))
    if config_kappa_lattice is not None:
        config.kappa_lattice = config_kappa_lattice

    config_lambda = optional_float(first_present(params_row, ("lambda", "scattering_lambda")))
    if config_lambda is not None:
        config.scattering_lambda = config_lambda

    config_model = optional_text(first_present(params_row, ("mobility_model", "u_model")))
    if config_model is not None:
        config.mobility_model = config_model

    config_xi = optional_float(first_present(params_row, ("Xi", "deformation_potential_eV")))
    if config_xi is not None:
        config.deformation_potential_eV = config_xi

    config_rho = optional_float(first_present(params_row, ("rho", "density_kg_m3")))
    if config_rho is not None:
        config.density_kg_m3 = config_rho

    config_vl = optional_float(first_present(params_row, ("vl", "sound_velocity_m_s")))
    if config_vl is not None:
        config.sound_velocity_m_s = config_vl

    config_nv = optional_float(first_present(params_row, ("Nv", "valley_degeneracy")))
    if config_nv is not None:
        config.valley_degeneracy = config_nv

    use_hall_factor = optional_bool(first_present(params_row, ("use_hall_factor", "hall_factor")))
    if use_hall_factor is not None:
        config.use_hall_factor = use_hall_factor

    has_deformation_params = any(
        value is not None
        for value in (config.deformation_potential_eV, config.density_kg_m3, config.sound_velocity_m_s)
    ) or config.valley_degeneracy != 1.0
    if config.mobility_model == "spb_u0" and has_deformation_params:
        config.mobility_model = "deformation_potential"

    return config


def run_performance_fit_multi(
    csv_path: str | os.PathLike,
    output_dir: str | os.PathLike,
    group_by: str,
    config: PerformanceFitConfig | None = None,
    params_path: str | os.PathLike | None = None,
    temperature_column: str | None = None,
    only_groups: list[str] | tuple[str, ...] | None = None,
    show: bool = False,
    plot_overrides: dict | None = None,
) -> dict[str, Any]:
    """Run SPB performance fits for multiple groups and save combined outputs."""

    config = config or PerformanceFitConfig()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    source = pd.read_csv(csv_path)
    if group_by not in source.columns:
        raise ValueError(f"Group column not found: {group_by}")
    source = filter_source_by_groups(source, group_by, only_groups)

    params = read_group_params(params_path, group_by)
    group_results = []
    point_frames = []
    curve_frames = []
    properties_seen: list[str] = []

    groups_dir = output_dir / "groups"
    for group_index, (group_key, group_df) in enumerate(source.groupby(group_by, sort=False)):
        group_key = str(group_key)
        params_row = params.get(group_key)
        group_label = group_label_from_params(group_key, params_row)
        group_config = performance_config_for_group(config, group_df, temperature_column, params_row)

        group_dir = groups_dir / safe_path_fragment(group_key)
        group_dir.mkdir(parents=True, exist_ok=True)
        group_input_path = group_dir / "input.csv"
        group_df.to_csv(group_input_path, index=False)

        result = run_performance_fit(
            group_input_path,
            group_dir,
            group_config,
            show=False,
            plot_overrides=plot_overrides,
        )
        summary = result["summary"]
        for property_key in summary.get("properties", []):
            if property_key not in properties_seen:
                properties_seen.append(property_key)

        points = pd.read_csv(result["points_path"])
        curve = pd.read_csv(result["curve_path"])

        points[group_by] = group_key
        points["curve_id"] = group_key
        points["material"] = group_label
        points["point_series_id"] = f"{group_key}:data"
        points["legend_label"] = f"{group_label} data"
        points["series_order"] = group_index * 2 + 1

        curve[group_by] = group_key
        curve["curve_id"] = group_key
        curve["material"] = group_label
        curve["series_id"] = f"{group_key}:model"
        curve["legend_label"] = f"{group_label} model"
        curve["series_order"] = group_index * 2

        point_frames.append(points)
        curve_frames.append(curve)

        group_results.append(
            {
                group_by: group_key,
                "curve_id": group_key,
                "label": group_label,
                "temperature_K": group_config.temperature,
                "mstar_mode": summary["mstar"]["mode"],
                "mstar_over_me": summary["mstar"].get("mstar_over_me", summary["mstar"].get("mstar_over_me_fit")),
                "mobility_model": summary["mobility_model"].get("model"),
                "mu0_cm2_vs": summary["mobility_model"].get("mu0_cm2_vs"),
                "mu_ref_cm2_vs": summary["mobility_model"].get("mu_ref_cm2_vs"),
                "kappa_lattice_W_m-1_K-1": summary.get("kappa_lattice_W_m-1_K-1"),
                "properties": ",".join(summary.get("properties", [])),
                "n_points": summary["n_points"],
                "points_path": result["points_path"],
                "curve_path": result["curve_path"],
                "summary_path": result["summary_path"],
            }
        )

    combined_points = pd.concat(point_frames, ignore_index=True)
    combined_curve = pd.concat(curve_frames, ignore_index=True)
    summary = {
        "mode": "multi",
        "input_csv": str(csv_path),
        "group_by": group_by,
        "temperature_column": temperature_column,
        "params_csv": str(params_path) if params_path else None,
        "n_groups": len(group_results),
        "properties": properties_seen,
        "groups": group_results,
        "config": asdict(config),
    }

    points_path = output_dir / "performance_points.csv"
    curve_path = output_dir / "performance_curve.csv"
    summary_path = output_dir / "performance_summary.json"
    summary_by_group_path = output_dir / "performance_summary_by_group.csv"
    combined_points.to_csv(points_path, index=False)
    combined_curve.to_csv(curve_path, index=False)
    pd.DataFrame(group_results).to_csv(summary_by_group_path, index=False)
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    plot_paths: dict[str, list[str]] = {}
    data_dir_plot_paths: dict[str, list[str]] = {}
    combined_plot_overrides = dict(plot_overrides or {})
    combined_plot_overrides.setdefault("legend_font_size", 7.5)
    combined_plot_overrides.setdefault("legend", "outside")
    for property_key in properties_seen:
        plot_paths[property_key] = plot_property_fit(
            combined_points,
            combined_curve,
            property_key,
            output_dir,
            config.figure_formats,
            show=show,
            defer_show=show,
            plot_overrides=plot_overrides_for_property(combined_plot_overrides, property_key),
        )
        data_dir_plot_paths[property_key] = copy_figures_to_input_data_dir(
            plot_paths[property_key],
            csv_path,
        )

    if show:
        show_open_performance_figures()

    return {
        "summary": summary,
        "points_path": str(points_path),
        "curve_path": str(curve_path),
        "summary_path": str(summary_path),
        "summary_by_group_path": str(summary_by_group_path),
        "plot_paths": plot_paths,
        "data_dir_plot_paths": data_dir_plot_paths,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fit SPB power-factor and zT curves from nH, Seebeck, PF, and zT data.",
    )
    parser.add_argument("csv_path", help="Input CSV containing Hall nH, Seebeck, PF, and optionally zT columns.")
    parser.add_argument(
        "--output-dir",
        default="results/spb_fitting/performance_fit",
        help="Directory for output CSV/JSON/PNG files.",
    )
    parser.add_argument("--temperature", "--T", type=float, default=300.0, help="Measurement temperature in K.")
    parser.add_argument("--group-by", "--group", "-g", dest="group_by", help="Column defining independent fit groups, e.g. curve_id.")
    parser.add_argument("--only", nargs="+", help="Fit only selected group value(s). Defaults to curve_id when --group is omitted.")
    parser.add_argument("--params", help="Optional per-group parameter CSV keyed by --group-by or curve_id.")
    parser.add_argument("--T-column", "--temperature-column", dest="temperature_column", help="Column containing per-group temperature in K.")
    parser.add_argument("--x", "--nh-column", dest="nh_column", default=None, help="Hall concentration column name.")
    parser.add_argument("--y", "--seebeck-column", dest="seebeck_column", default=None, help="Seebeck column name.")
    parser.add_argument("--pf", "--pf-column", dest="pf_column", default=None, help="Power-factor column name.")
    parser.add_argument("--zt", "--zt-column", dest="zt_column", default=None, help="zT column name.")
    parser.add_argument("--nh-unit", default="cm^-3", help="Hall concentration unit: cm^-3 or m^-3.")
    parser.add_argument("--seebeck-unit", default="uV/K", help="Seebeck unit: uV/K or V/K.")
    parser.add_argument("--pf-unit", default="uW cm^-1 K^-2", help="PF unit: uW cm^-1 K^-2 or W m^-1 K^-2.")
    parser.add_argument(
        "--mstar",
        "--m",
        "--effective-mass",
        dest="mstar",
        type=float,
        default=None,
        help="Use a fixed m*/me instead of fitting nH-S.",
    )
    parser.add_argument(
        "--mobility-model",
        choices=("spb_u0", "constant", "power_law", "deformation_potential"),
        default="spb_u0",
        help="Mobility model fitted from PF/S_theory^2. Default: spb_u0.",
    )
    parser.add_argument(
        "--u0",
        "--mu0",
        dest="mobility_u0_cm2_vs",
        type=float,
        default=None,
        help="Use fixed SPB mobility prefactor mu0 in cm^2 V^-1 s^-1.",
    )
    parser.add_argument(
        "--mobility-cm2-vs",
        dest="mobility_cm2_vs",
        type=float,
        default=None,
        help="Use fixed Hall mobility in cm^2 V^-1 s^-1; this bypasses the mu0 eta-dependent formula.",
    )
    parser.add_argument(
        "--scattering-lambda",
        "--lambda",
        dest="scattering_lambda",
        type=float,
        default=0.0,
        help="Scattering exponent lambda in the mu_H(mu0, eta) formula. Default: 0.",
    )
    parser.add_argument(
        "--deformation-potential-eV",
        "--Xi",
        dest="deformation_potential_eV",
        type=float,
        default=None,
        help="Acoustic deformation potential Xi in eV. If omitted in deformation_potential mode, Xi is fitted.",
    )
    parser.add_argument(
        "--density-kg-m3",
        "--rho",
        dest="density_kg_m3",
        type=float,
        default=None,
        help="Mass density rho in kg m^-3 for deformation-potential mobility.",
    )
    parser.add_argument(
        "--sound-velocity-m-s",
        "--vl",
        dest="sound_velocity_m_s",
        type=float,
        default=None,
        help="Longitudinal sound velocity v_l in m s^-1 for deformation-potential mobility.",
    )
    parser.add_argument(
        "--valley-degeneracy",
        "--Nv",
        dest="valley_degeneracy",
        type=float,
        default=1.0,
        help="Valley degeneracy Nv used for m_D* = Nv^(2/3) m_b*. Default: 1.",
    )
    parser.add_argument(
        "--kappa-lattice",
        "--kL",
        "--kl",
        dest="kappa_lattice",
        default=None,
        help='Lattice thermal conductivity in W m^-1 K^-1 for zT modeling, e.g. 0.5. Use "none" to skip zT.',
    )
    parser.add_argument(
        "--properties",
        nargs="+",
        choices=("pf", "zt"),
        default=None,
        help="Which performance curves to plot. Default: infer from data.",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=("png", "pdf"),
        help="Figure formats to export. Default: png pdf.",
    )
    parser.add_argument(
        "--no-hall-factor",
        action="store_true",
        help="Use nH = n instead of nH = n/rH in the SPB nH-S effective-mass fit.",
    )
    parser.add_argument("--no-show", action="store_true", help="Save outputs without calling plt.show().")
    parser.add_argument("--xlim", nargs=2, metavar=("LOW", "HIGH"), help="Override x-axis limits; use auto for one side.")
    parser.add_argument(
        "--ylim",
        nargs="+",
        action="append",
        default=[],
        metavar="VALUE",
        help=(
            "Override y-axis limits. Use --ylim LOW HIGH for all plots, "
            "or repeat --ylim PROPERTY LOW HIGH, e.g. --ylim pf 0 15 --ylim zt 0 1.2."
        ),
    )
    parser.add_argument("--xscale", choices=("linear", "log", "symlog", "logit"), help="Override x-axis scale.")
    parser.add_argument("--yscale", choices=("linear", "log", "symlog", "logit"), help="Override y-axis scale.")
    parser.add_argument("--x-major", type=float, help="Set x major tick interval for linear axes.")
    parser.add_argument("--x-minor", type=float, help="Set x minor tick interval for linear axes.")
    parser.add_argument("--y-major", type=float, help="Set y major tick interval.")
    parser.add_argument("--y-minor", type=float, help="Set y minor tick interval.")
    parser.add_argument("--x-tick-format", choices=("auto", "plain", "scientific"), help="Override x tick label format.")
    parser.add_argument("--y-tick-format", choices=("auto", "plain", "scientific"), help="Override y tick label format.")
    parser.add_argument("--x-log-ticks", choices=("auto", "decade"), help="For log x axes, label only integer powers of 10 when set to decade.")
    parser.add_argument("--y-log-ticks", choices=("auto", "decade"), help="For log y axes, label only integer powers of 10 when set to decade.")
    parser.add_argument("--legend", choices=("inside", "outside", "none"), help="Override legend placement.")
    parser.add_argument("--legend-loc", help='Matplotlib legend location, e.g. "best", "upper right", "lower left".')
    parser.add_argument("--legend-font-size", type=float, help="Override legend font size.")
    parser.add_argument("--subplot-aspect", help='Override axes aspect ratio, e.g. "10:8" or "1:1".')
    parser.add_argument("--figsize", nargs=2, type=float, metavar=("WIDTH", "HEIGHT"), help="Override figure size in inches.")
    parser.add_argument("--title", help="Override plot title text.")
    parser.add_argument("--show-title", action="store_true", help="Show the plot title.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    mobility_model = args.mobility_model
    deformation_potential_args_given = any(
        value is not None
        for value in (
            args.deformation_potential_eV,
            args.density_kg_m3,
            args.sound_velocity_m_s,
        )
    ) or args.valley_degeneracy != 1.0
    if mobility_model == "spb_u0" and deformation_potential_args_given:
        mobility_model = "deformation_potential"

    config = PerformanceFitConfig(
        temperature=args.temperature,
        nh_unit=args.nh_unit,
        seebeck_unit=args.seebeck_unit,
        pf_unit=args.pf_unit,
        nh_column=args.nh_column,
        seebeck_column=args.seebeck_column,
        pf_column=args.pf_column,
        zt_column=args.zt_column,
        use_hall_factor=not args.no_hall_factor,
        mstar_over_me=args.mstar,
        curve_xlim=parsed_x_curve_xlim(args),
        mobility_model=mobility_model,
        mobility_u0_cm2_vs=args.mobility_u0_cm2_vs,
        mobility_cm2_vs=args.mobility_cm2_vs,
        scattering_lambda=args.scattering_lambda,
        deformation_potential_eV=args.deformation_potential_eV,
        density_kg_m3=args.density_kg_m3,
        sound_velocity_m_s=args.sound_velocity_m_s,
        valley_degeneracy=args.valley_degeneracy,
        kappa_lattice=args.kappa_lattice,
        properties=tuple(args.properties) if args.properties else None,
        figure_formats=parse_output_formats(args.formats),
    )
    group_by = resolve_group_by_for_cli(args.csv_path, args.group_by, args.params, args.only)
    if group_by:
        result = run_performance_fit_multi(
            args.csv_path,
            args.output_dir,
            group_by,
            config,
            params_path=args.params,
            temperature_column=args.temperature_column,
            only_groups=args.only,
            show=not args.no_show,
            plot_overrides=build_multi_property_plot_overrides(args, ("pf", "zt")),
        )
        summary = result["summary"]
        print("SPB performance multi-fit finished")
        print(f"groups: {summary['n_groups']}")
        print(f"Points: {result['points_path']}")
        print(f"Curve: {result['curve_path']}")
        print(f"Summary: {result['summary_path']}")
        print(f"Summary by group: {result['summary_by_group_path']}")
        for property_key, paths in result["plot_paths"].items():
            print(f"{property_key.upper()} plot: {', '.join(paths)}")
            data_dir_paths = result["data_dir_plot_paths"].get(property_key, [])
            print(f"{property_key.upper()} data folder plot: {', '.join(data_dir_paths)}")
        return 0

    result = run_performance_fit(
        args.csv_path,
        args.output_dir,
        config,
        show=not args.no_show,
        plot_overrides=build_multi_property_plot_overrides(args, ("pf", "zt")),
    )
    summary = result["summary"]

    print("SPB performance fit finished")
    if summary["mstar"]["mode"] == "fit":
        print(f"m*/me fit: {summary['mstar']['mstar_over_me_fit']:.4f}")
        print(f"Seebeck RMSE: {summary['mstar']['seebeck_rmse_uV_K']:.2f} uV/K")
    else:
        print(f"m*/me fixed: {summary['mstar']['mstar_over_me']:.4f}")
    mobility = summary["mobility_model"]
    if mobility["model"] == "spb_u0":
        print(
            "Mobility model: "
            f"mu_H(eta) from mu0 = {mobility['mu0_cm2_vs']:.3g} cm^2/V/s, "
            f"lambda = {mobility['scattering_lambda']:.3g} ({mobility['source']})"
        )
    elif mobility["model"] == "deformation_potential":
        print(
            "Mobility model: "
            f"deformation-potential mu0 = {mobility['mu0_cm2_vs']:.3g} cm^2/V/s, "
            f"Xi = {mobility['deformation_potential_eV']:.3g} eV, "
            f"lambda = {mobility['scattering_lambda']:.3g} ({mobility['source']})"
        )
    elif mobility["model"] == "power_law":
        print(
            "Mobility model: "
            f"mu_H = {mobility['mu_ref_cm2_vs']:.3g} "
            f"(nH/{mobility['n_ref_cm3']:.3g})^{mobility['alpha']:.3g} cm^2/V/s"
        )
    else:
        print(f"Mobility model: mu_H = {mobility['mu_ref_cm2_vs']:.3g} cm^2/V/s")
    if summary["kappa_lattice_W_m-1_K-1"] is not None:
        print(
            "Lattice thermal conductivity: "
            f"{summary['kappa_lattice_W_m-1_K-1']:.4g} W/m/K "
            f"({summary['kappa_lattice_source']})"
        )
    print(f"Points: {result['points_path']}")
    print(f"Curve: {result['curve_path']}")
    print(f"Summary: {result['summary_path']}")
    for property_key, paths in result["plot_paths"].items():
        print(f"{property_key.upper()} plot: {', '.join(paths)}")
        data_dir_paths = result["data_dir_plot_paths"].get(property_key, [])
        print(f"{property_key.upper()} data folder plot: {', '.join(data_dir_paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

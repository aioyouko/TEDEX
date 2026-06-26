"""Fit SPB density-of-states effective mass from Hall nH and Seebeck data."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.constants import e, h, k, m_e
from scipy.integrate import quad
from scipy.optimize import brentq, minimize_scalar
from scipy.special import expit


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_NH_COLUMN_CANDIDATES = (
    "nH",
    "Hall_Carrier_Concentration",
    "Hall_Carrier_Concentration_cm-3",
    "Carrier_Concentration",
    "carrier_concentration",
    "concentration",
)

DEFAULT_SEEBECK_COLUMN_CANDIDATES = (
    "Seebeck",
    "seebeck",
    "S",
    "S_uV_K",
    "Seebeck_uV_K",
)

K_B_OVER_E_UV_PER_K = k / e * 1e6


@dataclass
class EffectiveMassFitConfig:
    """Configuration for the first-pass Hall-Pisarenko effective mass fit."""

    temperature: float = 300.0
    nh_unit: str = "cm^-3"
    seebeck_unit: str = "uV/K"
    nh_column: str | None = None
    seebeck_column: str | None = None
    use_hall_factor: bool = True
    eta_min: float = -60.0
    eta_max: float = 80.0
    mstar_min: float = 0.02
    mstar_max: float = 20.0
    curve_points: int = 300
    curve_xlim: tuple[float | None, float | None] | None = None
    manual_mstar_values: tuple[float, ...] | None = None
    figure_formats: tuple[str, ...] = ("png", "pdf")


def _normalize_column_name(name: str) -> str:
    return (
        name.strip()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
        .lower()
    )


def _find_column(df: pd.DataFrame, preferred: str | None, candidates: tuple[str, ...]) -> str:
    if preferred:
        if preferred not in df.columns:
            raise ValueError(f"Column not found: {preferred}")
        return preferred

    normalized = {_normalize_column_name(column): column for column in df.columns}
    for candidate in candidates:
        match = normalized.get(_normalize_column_name(candidate))
        if match:
            return match

    raise ValueError(
        "Could not identify a required column. "
        f"Available columns: {list(df.columns)}; candidates: {list(candidates)}"
    )


def _convert_nh_to_m3(values: pd.Series, unit: str) -> pd.Series:
    normalized = unit.strip().lower().replace(" ", "")
    if normalized in {"cm^-3", "cm-3", "cm**-3", "1/cm3", "cm^-3."}:
        return values.astype(float) * 1e6
    if normalized in {"m^-3", "m-3", "m**-3", "1/m3"}:
        return values.astype(float)
    raise ValueError(f"Unsupported Hall concentration unit: {unit}")


def _convert_seebeck_to_uv(values: pd.Series, unit: str) -> pd.Series:
    normalized = unit.strip().lower().replace(" ", "")
    if normalized in {"uv/k", "uvk^-1", "microv/k", "microvolt/k"}:
        return values.astype(float)
    if normalized in {"v/k", "vk^-1", "volt/k"}:
        return values.astype(float) * 1e6
    raise ValueError(f"Unsupported Seebeck unit: {unit}")


def curve_nh_bounds_from_points(
    points: pd.DataFrame,
    curve_xlim: tuple[float | None, float | None] | list[float | None] | None = None,
) -> tuple[float, float]:
    nh_min = float(points["nH_cm-3"].min()) * 0.7
    nh_max = float(points["nH_cm-3"].max()) * 1.4

    if curve_xlim:
        low, high = curve_xlim
        if low is not None:
            low = float(low)
            if low > 0:
                nh_min = min(nh_min, low)
        if high is not None:
            high = float(high)
            if high > 0:
                nh_max = max(nh_max, high)

    if nh_min <= 0 or nh_max <= 0 or nh_min >= nh_max:
        raise ValueError(f"Invalid nH curve bounds: {nh_min}, {nh_max}")
    return nh_min, nh_max


@lru_cache(maxsize=20000)
def _fermi_integral_cached(order: float, eta_rounded: float) -> float:
    eta = float(eta_rounded)
    upper_x = max(80.0, eta + 80.0)
    upper_t = np.sqrt(upper_x)

    def integrand(t):
        return 2.0 * (t ** (2.0 * order + 1.0)) * expit(eta - t * t)

    result, _ = quad(integrand, 0.0, upper_t, epsabs=1e-10, epsrel=1e-10, limit=300)
    return float(result)


def fermi_integral(eta: float, order: float) -> float:
    """Unnormalized Fermi integral int x^order / (1 + exp(x - eta)) dx."""

    if order <= -1:
        raise ValueError("Fermi integral order must be greater than -1")
    return _fermi_integral_cached(float(order), round(float(eta), 11))


def seebeck_abs_uv_from_eta(eta: float) -> float:
    """Acoustic-phonon SPB Seebeck magnitude in uV/K for scattering exponent lambda=0."""

    f0 = fermi_integral(eta, 0.0)
    f1 = fermi_integral(eta, 1.0)
    return K_B_OVER_E_UV_PER_K * (2.0 * f1 / f0 - eta)


def eta_from_seebeck_abs_uv(seebeck_abs_uv: float, eta_min: float = -60.0, eta_max: float = 80.0) -> float:
    """Solve eta from Seebeck magnitude using the same lambda=0 SPB relation."""

    target = float(abs(seebeck_abs_uv))
    if not np.isfinite(target) or target <= 0:
        raise ValueError(f"Seebeck magnitude must be positive, got {seebeck_abs_uv}")

    def residual(eta):
        return seebeck_abs_uv_from_eta(eta) - target

    low_value = residual(eta_min)
    high_value = residual(eta_max)
    if low_value * high_value > 0:
        raise ValueError(
            f"Could not bracket eta for Seebeck={seebeck_abs_uv} uV/K "
            f"between {eta_min} and {eta_max}"
        )
    return float(brentq(residual, eta_min, eta_max, xtol=1e-10, rtol=1e-10, maxiter=200))


def hall_factor_acoustic(eta: float) -> float:
    """SPB Hall factor for acoustic-phonon scattering, lambda=0."""

    f_half = fermi_integral(eta, 0.5)
    f_minus_half = fermi_integral(eta, -0.5)
    f0 = fermi_integral(eta, 0.0)
    return 0.75 * f_half * f_minus_half / (f0 * f0)


def carrier_concentration_m3(eta: float, mstar_ratio: float, temperature: float) -> float:
    """True carrier concentration for a single parabolic band in m^-3."""

    if mstar_ratio <= 0:
        raise ValueError("mstar_ratio must be positive")
    prefactor = 4.0 * np.pi * (2.0 * mstar_ratio * m_e * k * temperature / h**2) ** 1.5
    return float(prefactor * fermi_integral(eta, 0.5))


def hall_concentration_m3(
    eta: float,
    mstar_ratio: float,
    temperature: float,
    use_hall_factor: bool = True,
) -> float:
    """Hall carrier concentration nH = n / rH in m^-3."""

    n_true = carrier_concentration_m3(eta, mstar_ratio, temperature)
    if not use_hall_factor:
        return n_true
    return n_true / hall_factor_acoustic(eta)


def mstar_from_eta_and_nh(
    eta: float,
    nh_m3: float,
    temperature: float,
    use_hall_factor: bool = True,
) -> float:
    """Direct point estimate of m*/me from experimental eta and nH."""

    hall_factor = hall_factor_acoustic(eta) if use_hall_factor else 1.0
    density_argument = nh_m3 * hall_factor / (4.0 * np.pi * fermi_integral(eta, 0.5))
    mstar_kg = h**2 / (2.0 * k * temperature) * density_argument ** (2.0 / 3.0)
    return float(mstar_kg / m_e)


def eta_from_nh_and_mstar(
    nh_m3: float,
    mstar_ratio: float,
    config: EffectiveMassFitConfig,
) -> float:
    """Solve eta from nH for a trial effective mass."""

    target_log = np.log(float(nh_m3))

    def residual(eta):
        model = hall_concentration_m3(
            eta,
            mstar_ratio,
            config.temperature,
            use_hall_factor=config.use_hall_factor,
        )
        return np.log(model) - target_log

    low_value = residual(config.eta_min)
    high_value = residual(config.eta_max)
    if low_value * high_value > 0:
        raise ValueError(
            f"Could not bracket eta for nH={nh_m3:.4e} m^-3 and m*={mstar_ratio:.4g}"
        )
    return float(brentq(residual, config.eta_min, config.eta_max, xtol=1e-10, rtol=1e-10, maxiter=200))


def prepare_spb_input_table(csv_path: str | os.PathLike, config: EffectiveMassFitConfig) -> pd.DataFrame:
    """Load a Hall-Pisarenko CSV and normalize nH/Seebeck units."""

    df = pd.read_csv(csv_path)
    nh_column = _find_column(df, config.nh_column, DEFAULT_NH_COLUMN_CANDIDATES)
    seebeck_column = _find_column(df, config.seebeck_column, DEFAULT_SEEBECK_COLUMN_CANDIDATES)

    result = df.copy()
    result["nH_cm-3"] = _convert_nh_to_m3(result[nh_column], config.nh_unit) / 1e6
    result["nH_m-3"] = _convert_nh_to_m3(result[nh_column], config.nh_unit)
    result["Seebeck_uV_K"] = _convert_seebeck_to_uv(result[seebeck_column], config.seebeck_unit)
    result["Seebeck_abs_uV_K"] = result["Seebeck_uV_K"].abs()
    result["Temperature_K"] = config.temperature

    required = ["nH_m-3", "Seebeck_abs_uV_K"]
    result = result.replace([np.inf, -np.inf], np.nan).dropna(subset=required).reset_index(drop=True)
    result = result[(result["nH_m-3"] > 0) & (result["Seebeck_abs_uV_K"] > 0)].reset_index(drop=True)
    if result.empty:
        raise ValueError("No positive finite nH/Seebeck rows remain after cleaning")

    return result


def add_point_effective_mass_estimates(
    points: pd.DataFrame,
    config: EffectiveMassFitConfig,
) -> pd.DataFrame:
    """Add eta, Hall factor, and per-point m*/me estimates from experimental Seebeck."""

    rows = []
    for _, row in points.iterrows():
        eta = eta_from_seebeck_abs_uv(
            row["Seebeck_abs_uV_K"],
            eta_min=config.eta_min,
            eta_max=config.eta_max,
        )
        r_h = hall_factor_acoustic(eta) if config.use_hall_factor else 1.0
        mstar = mstar_from_eta_and_nh(
            eta,
            row["nH_m-3"],
            config.temperature,
            use_hall_factor=config.use_hall_factor,
        )
        updated = row.to_dict()
        updated["eta_from_Seebeck"] = eta
        updated["Hall_factor_rH"] = r_h
        updated["mstar_over_me_point"] = mstar
        rows.append(updated)

    return pd.DataFrame(rows)


def fit_global_effective_mass(
    points: pd.DataFrame,
    config: EffectiveMassFitConfig,
) -> dict:
    """Fit one common m*/me by minimizing Seebeck residuals on a Pisarenko curve."""

    nh_values = points["nH_m-3"].to_numpy(dtype=float)
    seebeck_values = points["Seebeck_abs_uV_K"].to_numpy(dtype=float)

    def predict_for_mstar(mstar_ratio: float) -> np.ndarray:
        predicted = []
        for nh_m3 in nh_values:
            eta = eta_from_nh_and_mstar(nh_m3, mstar_ratio, config)
            predicted.append(seebeck_abs_uv_from_eta(eta))
        return np.asarray(predicted)

    def objective(log_mstar: float) -> float:
        mstar_ratio = float(np.exp(log_mstar))
        predicted = predict_for_mstar(mstar_ratio)
        residuals = predicted - seebeck_values
        return float(np.mean(residuals * residuals))

    result = minimize_scalar(
        objective,
        bounds=(np.log(config.mstar_min), np.log(config.mstar_max)),
        method="bounded",
        options={"xatol": 1e-8},
    )
    if not result.success:
        raise ValueError(f"Effective-mass fit failed: {result.message}")

    fitted_mstar = float(np.exp(result.x))
    predicted = predict_for_mstar(fitted_mstar)
    residuals = predicted - seebeck_values
    return {
        "mstar_over_me_fit": fitted_mstar,
        "rmse_uV_K": float(np.sqrt(np.mean(residuals * residuals))),
        "mae_uV_K": float(np.mean(np.abs(residuals))),
        "max_abs_error_uV_K": float(np.max(np.abs(residuals))),
        "model_seebeck_uV_K": predicted,
        "residual_uV_K": residuals,
    }


def build_pisarenko_curve(
    points: pd.DataFrame,
    mstar_ratio: float,
    config: EffectiveMassFitConfig,
) -> pd.DataFrame:
    """Build an nH-S curve for the fitted effective mass."""

    nh_min, nh_max = curve_nh_bounds_from_points(points, config.curve_xlim)
    nh_grid_cm3 = np.logspace(np.log10(nh_min), np.log10(nh_max), config.curve_points)

    rows = []
    for nh_cm3 in nh_grid_cm3:
        nh_m3 = nh_cm3 * 1e6
        eta = eta_from_nh_and_mstar(nh_m3, mstar_ratio, config)
        rows.append(
            {
                "nH_cm-3": nh_cm3,
                "nH_m-3": nh_m3,
                "eta": eta,
                "Seebeck_abs_uV_K": seebeck_abs_uv_from_eta(eta),
                "Hall_factor_rH": hall_factor_acoustic(eta) if config.use_hall_factor else 1.0,
                "mstar_over_me": mstar_ratio,
                "Temperature_K": config.temperature,
            }
        )

    return pd.DataFrame(rows)


def build_pisarenko_curves(
    points: pd.DataFrame,
    mstar_values: list[float] | tuple[float, ...],
    config: EffectiveMassFitConfig,
) -> pd.DataFrame:
    """Build one or more nH-S curves for requested effective masses."""

    curve_frames = []
    for mstar_ratio in mstar_values:
        curve = build_pisarenko_curve(points, mstar_ratio, config)
        curve["curve_label"] = f"m*/me = {mstar_ratio:.3g}"
        curve_frames.append(curve)

    return pd.concat(curve_frames, ignore_index=True)


SPB_FIT_RECIPE = ROOT / "configs/plot_recipes/spb/pisarenko_fit.json"
SPB_FIT_STYLE_KEYS = ("color", "marker", "linestyle", "line_width", "marker_size", "alpha")


def default_spb_fit_recipe() -> dict:
    """Return the flexible-plot compatible defaults for Hall-Pisarenko fits."""

    return {
        "name": "spb_pisarenko_fit",
        "plot": {
            "kind": "line",
            "x": {
                "column": "nH_cm-3",
                "label": r"$n_{\mathrm{H}}$ (cm$^{-3}$)",
            },
            "series": [
                {
                    "y": {
                        "column": "Seebeck_abs_uV_K",
                        "label": "$|S|$ (\u00b5V K$^{-1}$)",
                    },
                    "property": "seebeck",
                    "marker": "None",
                    "linestyle": "-",
                    "line_width": 1.4,
                },
                {
                    "y": {
                        "column": "Seebeck_abs_uV_K",
                        "label": "$|S|$ (\u00b5V K$^{-1}$)",
                    },
                    "property": "seebeck",
                    "group_value": "data",
                    "color": "#e76f6f",
                    "marker": "o",
                    "marker_size": 5.5,
                    "alpha": 0.75,
                    "linestyle": "none",
                    "line_width": 0.0,
                },
            ],
            "xlabel": r"$n_{\mathrm{H}}$ (cm$^{-3}$)",
            "ylabel": "$|S|$ (\u00b5V K$^{-1}$)",
            "xscale": "log",
            "x_log_ticks": "decade",
            "legend": "inside",
            "legend_loc": "best",
            "x_margin": 0.04,
            "y_margin": 0.08,
        },
    }


def load_spb_fit_recipe() -> dict:
    """Load the fitting plot recipe from configs/plot_recipes."""

    fallback = default_spb_fit_recipe()
    try:
        with open(SPB_FIT_RECIPE, "r", encoding="utf-8") as handle:
            recipe = json.load(handle)
    except (OSError, json.JSONDecodeError):
        recipe = fallback

    merged = dict(fallback)
    merged["plot"] = {**fallback["plot"], **recipe.get("plot", {})}
    merged["name"] = recipe.get("name", fallback["name"])
    return merged


def apply_plot_overrides(recipe: dict, overrides: dict | None) -> dict:
    """Apply command-line plot overrides to a loaded recipe."""

    if not overrides:
        return recipe

    updated = dict(recipe)
    updated["plot"] = {**recipe.get("plot", {}), **overrides}
    return updated


BLANK_STRINGS = {"", "none", "null", "nan", "na", "n/a", "-"}


def is_blank_value(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    return str(value).strip().lower() in BLANK_STRINGS


def optional_float(value: object) -> float | None:
    if is_blank_value(value):
        return None
    return float(value)


def optional_bool(value: object) -> bool | None:
    if is_blank_value(value):
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Could not parse boolean value: {value}")


def first_present(row: pd.Series | dict[str, Any] | None, names: tuple[str, ...]) -> object | None:
    if row is None:
        return None
    for name in names:
        if name in row and not is_blank_value(row[name]):
            return row[name]
    return None


def safe_path_fragment(value: object) -> str:
    text = str(value).strip() or "group"
    safe = []
    for char in text:
        if char.isalnum() or char in {"-", "_", "."}:
            safe.append(char)
        else:
            safe.append("_")
    return "".join(safe).strip("._") or "group"


def read_group_params(
    params_path: str | os.PathLike | None,
    group_column: str,
) -> dict[str, pd.Series]:
    if not params_path:
        return {}
    params = pd.read_csv(params_path)
    key_column = group_column if group_column in params.columns else "curve_id"
    if key_column not in params.columns:
        raise ValueError(
            f"Params file must contain '{group_column}' or 'curve_id'. "
            f"Available columns: {list(params.columns)}"
        )
    result = {}
    for _, row in params.iterrows():
        key = str(row[key_column])
        if key in result:
            raise ValueError(f"Duplicate params row for group: {key}")
        result[key] = row
    return result


def group_temperature(
    group_df: pd.DataFrame,
    default_temperature: float,
    temperature_column: str | None = None,
    params_row: pd.Series | None = None,
) -> float:
    param_temperature = optional_float(first_present(params_row, ("T", "temperature", "temperature_K")))
    if param_temperature is not None:
        return param_temperature

    if temperature_column:
        if temperature_column not in group_df.columns:
            raise ValueError(f"Temperature column not found: {temperature_column}")
        values = pd.to_numeric(group_df[temperature_column], errors="coerce").dropna().unique()
        if len(values) == 0:
            return float(default_temperature)
        if len(values) > 1:
            raise ValueError(f"Group has multiple temperatures in column '{temperature_column}': {values}")
        return float(values[0])

    return float(default_temperature)


def group_label_from_params(group_key: str, params_row: pd.Series | None = None) -> str:
    label = first_present(params_row, ("label", "legend_label", "material", "composition", "curve_label"))
    return str(label) if label is not None else str(group_key)


def group_style(index: int) -> tuple[str, str]:
    from src.tools.plot import get_style_cycles

    colors, markers = get_style_cycles()
    color = marker = None
    for _ in range(index + 1):
        color = next(colors)
        marker = next(markers)
    return str(color), str(marker)


def group_color(index: int) -> str:
    return group_style(index)[0]


def group_marker(index: int) -> str:
    return group_style(index)[1]


def resolve_group_by_for_cli(
    csv_path: str | os.PathLike,
    group_by: str | None,
    params_path: str | os.PathLike | None = None,
    only_groups: list[str] | tuple[str, ...] | None = None,
) -> str | None:
    if group_by:
        return group_by
    if params_path or only_groups:
        columns = set(pd.read_csv(csv_path, nrows=0).columns)
        if "curve_id" in columns:
            return "curve_id"
        raise ValueError("--only/--params needs --group/-g unless the input CSV contains a curve_id column.")
    return None


def filter_source_by_groups(
    source: pd.DataFrame,
    group_by: str,
    only_groups: list[str] | tuple[str, ...] | None,
) -> pd.DataFrame:
    if not only_groups:
        return source

    requested = {str(group) for group in only_groups}
    available = set(source[group_by].astype(str).unique())
    missing = sorted(requested - available)
    if missing:
        raise ValueError(
            f"Requested group(s) not found in '{group_by}': {missing}. "
            f"Available groups: {sorted(available)}"
        )
    return source[source[group_by].astype(str).isin(requested)].copy()


def selector_display_label(selector: object, default: str) -> str:
    if isinstance(selector, dict):
        return str(selector.get("label") or selector.get("title") or default)
    return default


def fit_curve_label(mstar_ratio: float, summary: dict) -> str:
    if summary["mode"] == "fit":
        return f"SPB fit m*/me = {mstar_ratio:.3f}"
    return f"m*/me = {mstar_ratio:.3g}"


def series_style(spec: dict, key: str) -> object:
    if key in spec:
        return spec[key]
    return ""


def build_spb_fit_normalized_table(
    points: pd.DataFrame,
    curve: pd.DataFrame,
    summary: dict,
    recipe: dict,
) -> tuple[pd.DataFrame, dict]:
    """Build the normalized table expected by flexible_plot plotters."""

    plot = recipe.get("plot", {})
    series_specs = plot.get("series") or default_spb_fit_recipe()["plot"]["series"]
    curve_spec = series_specs[0] if len(series_specs) >= 1 and isinstance(series_specs[0], dict) else {}
    point_spec = series_specs[1] if len(series_specs) >= 2 and isinstance(series_specs[1], dict) else {}
    y_selector = curve_spec.get("y", {})
    property_name = str(curve_spec.get("property") or "seebeck")
    property_label = selector_display_label(y_selector, plot.get("ylabel", "$|S|$ (\u00b5V K$^{-1}$)"))

    frames = []
    curve_group_column = "series_id" if "series_id" in curve.columns else "mstar_over_me"
    curve_groups = list(curve.groupby(curve_group_column, sort=False))
    point_group_column = "point_series_id" if "point_series_id" in points.columns else None
    point_group_count = points[point_group_column].nunique() if point_group_column else 1
    multi_group = len(curve_groups) > 1 or point_group_count > 1

    for curve_index, (_, curve_group) in enumerate(curve_groups):
        mstar_ratio = float(curve_group["mstar_over_me"].iloc[0])
        legend_label = (
            str(curve_group["legend_label"].iloc[0])
            if "legend_label" in curve_group.columns and not is_blank_value(curve_group["legend_label"].iloc[0])
            else fit_curve_label(mstar_ratio, summary)
        )
        frame = pd.DataFrame(
            {
                "x": curve_group["nH_cm-3"].to_numpy(dtype=float),
                "x_category": curve_group["nH_cm-3"].astype(str).to_numpy(),
                "y": curve_group["Seebeck_abs_uV_K"].to_numpy(dtype=float),
                "property": property_name,
                "group": legend_label,
                "legend_label": legend_label,
                "label": "",
                "condition": "",
                "source": "pisarenko_curve",
                "x_source_column": "nH_cm-3",
                "y_source_column": "Seebeck_abs_uV_K",
                "series_order": curve_index,
            }
        )
        for key in SPB_FIT_STYLE_KEYS:
            frame[key] = series_style(curve_spec, key)
        if multi_group:
            frame["color"] = group_color(curve_index)
        frames.append(frame)

    if point_group_column:
        point_groups = list(points.groupby(point_group_column, sort=False))
    else:
        point_groups = [(None, points)]

    for point_index, (_, point_group) in enumerate(point_groups):
        point_label = str(point_spec.get("legend_label") or point_spec.get("group_value") or "data")
        if "legend_label" in point_group.columns and not is_blank_value(point_group["legend_label"].iloc[0]):
            point_label = str(point_group["legend_label"].iloc[0])
        point_frame = pd.DataFrame(
            {
                "x": point_group["nH_cm-3"].to_numpy(dtype=float),
                "x_category": point_group["nH_cm-3"].astype(str).to_numpy(),
                "y": point_group["Seebeck_abs_uV_K"].to_numpy(dtype=float),
                "property": property_name,
                "group": point_label,
                "legend_label": point_label,
                "label": "",
                "condition": "",
                "source": "effective_mass_points",
                "x_source_column": "nH_cm-3",
                "y_source_column": "Seebeck_abs_uV_K",
                "series_order": len(frames),
            }
        )
        for key in SPB_FIT_STYLE_KEYS:
            point_frame[key] = series_style(point_spec, key)
        if multi_group:
            point_frame["color"] = group_color(point_index)
            point_frame["marker"] = group_marker(point_index)
        frames.append(point_frame)

    normalized = pd.concat(frames, ignore_index=True)
    metadata = {
        "x_label": selector_display_label(plot.get("x"), "nH_cm-3"),
        "property_labels": {property_name: property_label},
        "kind": plot.get("kind", "line"),
        "title": plot.get("title", recipe.get("name", "")),
        "categorical_x": False,
        "x_categories": [],
    }
    return normalized, metadata


def plot_pisarenko_fit(
    points: pd.DataFrame,
    curve: pd.DataFrame,
    summary: dict,
    save_path: str | os.PathLike,
    formats: tuple[str, ...] = ("png", "pdf"),
    show: bool = False,
    plot_overrides: dict | None = None,
) -> list[str]:
    """Save a publication-style Pisarenko plot using the project house style."""

    cache_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "te_matplotlib_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))

    from src.tools.flexible_plot import plot_line_or_scatter
    from src.tools.plot import save_figure

    import matplotlib.pyplot as plt

    recipe = apply_plot_overrides(load_spb_fit_recipe(), plot_overrides)
    normalized, metadata = build_spb_fit_normalized_table(points, curve, summary, recipe)
    fig, _ = plot_line_or_scatter(normalized, metadata, recipe)

    save_path = Path(save_path)
    save_figure(
        fig,
        save_path.name,
        save_dir=str(save_path.parent),
        formats=formats,
    )
    if show:
        plt.show()
    plt.close(fig)

    return [str(save_path.with_suffix(f".{file_format}")) for file_format in formats]


def copy_figures_to_input_data_dir(
    figure_paths: list[str | os.PathLike],
    csv_path: str | os.PathLike,
) -> list[str]:
    """Copy exported figure files next to the input CSV and return those paths."""

    data_dir = Path(csv_path).expanduser().resolve().parent
    data_dir.mkdir(parents=True, exist_ok=True)

    copied_paths = []
    for figure_path in figure_paths:
        source = Path(figure_path).expanduser()
        if not source.exists():
            continue
        target = data_dir / source.name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        copied_paths.append(str(target))
    return copied_paths


def run_effective_mass_fit(
    csv_path: str | os.PathLike,
    output_dir: str | os.PathLike,
    config: EffectiveMassFitConfig | None = None,
    show: bool = False,
    plot_overrides: dict | None = None,
) -> dict:
    """Run the full first-pass effective mass fit and save tables/plot."""

    config = config or EffectiveMassFitConfig()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    points = prepare_spb_input_table(csv_path, config)
    points = add_point_effective_mass_estimates(points, config)

    summary = {
        "input_csv": str(csv_path),
        "temperature_K": config.temperature,
        "use_hall_factor": config.use_hall_factor,
        "n_points": int(len(points)),
        "mstar_over_me_point_mean": float(points["mstar_over_me_point"].mean()),
        "mstar_over_me_point_median": float(points["mstar_over_me_point"].median()),
        "mstar_over_me_point_std": float(points["mstar_over_me_point"].std(ddof=1)),
        "config": asdict(config),
    }

    if config.manual_mstar_values:
        mstar_values = tuple(float(value) for value in config.manual_mstar_values)
        curve = build_pisarenko_curves(points, mstar_values, config)
        summary.update(
            {
                "mode": "manual_mstar",
                "manual_mstar_values": list(mstar_values),
            }
        )
    else:
        fit = fit_global_effective_mass(points, config)
        points["model_Seebeck_abs_uV_K"] = fit["model_seebeck_uV_K"]
        points["fit_residual_uV_K"] = fit["residual_uV_K"]
        curve = build_pisarenko_curves(points, (fit["mstar_over_me_fit"],), config)
        summary.update(
            {
                "mode": "fit",
                "mstar_over_me_fit": fit["mstar_over_me_fit"],
                "rmse_uV_K": fit["rmse_uV_K"],
                "mae_uV_K": fit["mae_uV_K"],
                "max_abs_error_uV_K": fit["max_abs_error_uV_K"],
            }
        )

    points_path = output_dir / "effective_mass_points.csv"
    curve_path = output_dir / "pisarenko_curve.csv"
    summary_path = output_dir / "fit_summary.json"
    plot_path = output_dir / "pisarenko_fit.png"

    points.to_csv(points_path, index=False)
    curve.to_csv(curve_path, index=False)
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    plot_paths = plot_pisarenko_fit(
        points,
        curve,
        summary,
        plot_path,
        formats=config.figure_formats,
        show=show,
        plot_overrides=plot_overrides,
    )
    data_dir_plot_paths = copy_figures_to_input_data_dir(plot_paths, csv_path)

    return {
        "summary": summary,
        "points_path": str(points_path),
        "curve_path": str(curve_path),
        "summary_path": str(summary_path),
        "plot_path": plot_paths[0],
        "plot_paths": plot_paths,
        "data_dir_plot_paths": data_dir_plot_paths,
    }


def effective_config_for_group(
    base_config: EffectiveMassFitConfig,
    group_df: pd.DataFrame,
    temperature_column: str | None,
    params_row: pd.Series | None,
) -> EffectiveMassFitConfig:
    config = EffectiveMassFitConfig(**asdict(base_config))
    config.temperature = group_temperature(group_df, base_config.temperature, temperature_column, params_row)

    group_mstar = optional_float(first_present(params_row, ("m", "mstar", "mstar_over_me", "effective_mass")))
    if group_mstar is not None:
        config.manual_mstar_values = (group_mstar,)

    use_hall_factor = optional_bool(first_present(params_row, ("use_hall_factor", "hall_factor")))
    if use_hall_factor is not None:
        config.use_hall_factor = use_hall_factor

    return config


def run_effective_mass_fit_multi(
    csv_path: str | os.PathLike,
    output_dir: str | os.PathLike,
    group_by: str,
    config: EffectiveMassFitConfig | None = None,
    params_path: str | os.PathLike | None = None,
    temperature_column: str | None = None,
    only_groups: list[str] | tuple[str, ...] | None = None,
    show: bool = False,
    plot_overrides: dict | None = None,
) -> dict:
    """Run effective-mass fits for multiple groups and save combined outputs."""

    config = config or EffectiveMassFitConfig()
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

    groups_dir = output_dir / "groups"
    for group_index, (group_key, group_df) in enumerate(source.groupby(group_by, sort=False)):
        group_key = str(group_key)
        params_row = params.get(group_key)
        group_label = group_label_from_params(group_key, params_row)
        group_config = effective_config_for_group(config, group_df, temperature_column, params_row)

        group_dir = groups_dir / safe_path_fragment(group_key)
        group_dir.mkdir(parents=True, exist_ok=True)
        group_input_path = group_dir / "input.csv"
        group_df.to_csv(group_input_path, index=False)

        result = run_effective_mass_fit(
            group_input_path,
            group_dir,
            group_config,
            show=False,
            plot_overrides=plot_overrides,
        )
        summary = result["summary"]
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
        if summary["mode"] == "fit":
            curve_label = f"{group_label} fit m*/me={summary['mstar_over_me_fit']:.3g}"
        else:
            values = ",".join(f"{value:.3g}" for value in summary.get("manual_mstar_values", []))
            curve_label = f"{group_label} m*/me={values}"
        curve["legend_label"] = curve_label
        curve["series_order"] = group_index * 2

        point_frames.append(points)
        curve_frames.append(curve)

        group_results.append(
            {
                group_by: group_key,
                "curve_id": group_key,
                "label": group_label,
                "temperature_K": group_config.temperature,
                "mode": summary["mode"],
                "mstar_over_me_fit": summary.get("mstar_over_me_fit"),
                "manual_mstar_values": ",".join(str(value) for value in summary.get("manual_mstar_values", [])),
                "rmse_uV_K": summary.get("rmse_uV_K"),
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
        "groups": group_results,
        "config": asdict(config),
    }

    points_path = output_dir / "effective_mass_points.csv"
    curve_path = output_dir / "pisarenko_curve.csv"
    summary_path = output_dir / "fit_summary.json"
    summary_by_group_path = output_dir / "fit_summary_by_group.csv"
    plot_path = output_dir / "pisarenko_fit.png"

    combined_points.to_csv(points_path, index=False)
    combined_curve.to_csv(curve_path, index=False)
    pd.DataFrame(group_results).to_csv(summary_by_group_path, index=False)
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    combined_plot_overrides = dict(plot_overrides or {})
    combined_plot_overrides.setdefault("legend_font_size", 7.5)
    combined_plot_overrides.setdefault("legend", "outside")
    plot_paths = plot_pisarenko_fit(
        combined_points,
        combined_curve,
        summary,
        plot_path,
        formats=config.figure_formats,
        show=show,
        plot_overrides=combined_plot_overrides,
    )
    data_dir_plot_paths = copy_figures_to_input_data_dir(plot_paths, csv_path)

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
        description="Fit SPB density-of-states effective mass from Hall nH and Seebeck data.",
    )
    parser.add_argument("csv_path", help="Input CSV containing Hall nH and Seebeck columns.")
    parser.add_argument(
        "--output-dir",
        default="results/spb_fitting/effective_mass_fit",
        help="Directory for output CSV/JSON/PNG files.",
    )
    parser.add_argument("--temperature", "--T", type=float, default=300.0, help="Measurement temperature in K.")
    parser.add_argument("--group-by", "--group", "-g", dest="group_by", help="Column defining independent fit groups, e.g. curve_id.")
    parser.add_argument("--only", nargs="+", help="Fit only selected group value(s). Defaults to curve_id when --group is omitted.")
    parser.add_argument("--params", help="Optional per-group parameter CSV keyed by --group-by or curve_id.")
    parser.add_argument("--T-column", "--temperature-column", dest="temperature_column", help="Column containing per-group temperature in K.")
    parser.add_argument("--nh-column", "--x", dest="nh_column", default=None, help="Hall concentration column name.")
    parser.add_argument("--seebeck-column", "--y", dest="seebeck_column", default=None, help="Seebeck column name.")
    parser.add_argument("--nh-unit", default="cm^-3", help="Hall concentration unit: cm^-3 or m^-3.")
    parser.add_argument("--seebeck-unit", default="uV/K", help="Seebeck unit: uV/K or V/K.")
    parser.add_argument(
        "--formats",
        nargs="+",
        default=("png", "pdf"),
        help="Figure formats to export. Default: png pdf.",
    )
    parser.add_argument(
        "--m",
        nargs="+",
        default=None,
        help=(
            "Manual m*/me values to plot instead of fitting, e.g. "
            "--m 1.3 1.4 1.5 or --m 1.3,1.4,1.5."
        ),
    )
    parser.add_argument(
        "--no-hall-factor",
        action="store_true",
        help="Use nH = n instead of nH = n/rH. Default includes acoustic-SPB Hall factor.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save outputs without calling plt.show().",
    )
    parser.add_argument("--xlim", nargs=2, metavar=("LOW", "HIGH"), help="Override x-axis limits; use auto for one side.")
    parser.add_argument("--ylim", nargs=2, metavar=("LOW", "HIGH"), help="Override y-axis limits; use auto for one side.")
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


def parse_manual_mstar_values(tokens: list[str] | None) -> tuple[float, ...] | None:
    if not tokens:
        return None

    values = []
    for token in tokens:
        for part in token.split(","):
            part = part.strip()
            if not part:
                continue
            value = float(part)
            if value <= 0:
                raise ValueError(f"Manual m*/me values must be positive, got {value}")
            values.append(value)

    if not values:
        return None
    return tuple(values)


def parse_output_formats(tokens: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not tokens:
        return ("png", "pdf")

    formats = []
    for token in tokens:
        for part in str(token).split(","):
            clean_format = part.strip().lstrip(".").lower()
            if clean_format and clean_format not in formats:
                formats.append(clean_format)

    return tuple(formats) or ("png", "pdf")


def parse_axis_limit(values: list[str] | tuple[str, ...] | None) -> list[float | None] | None:
    if not values:
        return None
    if len(values) != 2:
        raise ValueError("Axis limits must be exactly LOW HIGH.")

    parsed = []
    for value in values:
        clean_value = str(value).strip().lower()
        if clean_value in {"auto", "none", "null", ""}:
            parsed.append(None)
        else:
            parsed.append(float(value))

    if parsed[0] is None and parsed[1] is None:
        return None
    if parsed[0] is not None and parsed[1] is not None and parsed[0] >= parsed[1]:
        raise ValueError("Axis lower limit must be smaller than upper limit")
    return parsed


def parse_global_axis_limit_arg(
    values: list[str] | list[list[str]] | tuple[str, ...] | None,
    option_name: str = "--ylim",
) -> list[float | None] | None:
    if not values:
        return None
    first_value = values[0]
    if isinstance(first_value, (list, tuple)):
        positional_limits = [raw_limit for raw_limit in values if len(raw_limit) == 2]
        if not positional_limits:
            return None
        if len(positional_limits) > 1:
            raise ValueError(
                f"Repeated {option_name} LOW HIGH is ambiguous. "
                f"Use {option_name} PROPERTY LOW HIGH for per-property limits."
            )
        return parse_axis_limit(positional_limits[0])
    return parse_axis_limit(values)


def normalize_property_axis_limit_key(property_key: str, valid_properties: tuple[str, ...]) -> str:
    normalized = str(property_key).strip().lower().replace("-", "_")
    aliases = {
        "s": "seebeck",
        "seebeck": "seebeck",
        "pf": "pf",
        "power_factor": "pf",
        "powerfactor": "pf",
        "zt": "zt",
        "z_t": "zt",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in valid_properties:
        choices = ", ".join(valid_properties)
        raise ValueError(f"Unknown property for --ylim: {property_key}. Choose from: {choices}.")
    return normalized


def parse_property_axis_limits(
    raw_limits: list[str] | list[list[str]] | tuple[str, ...] | None,
    valid_properties: tuple[str, ...],
    option_name: str = "--ylim",
) -> dict[str, list[float | None]]:
    if not raw_limits:
        return {}
    if isinstance(raw_limits[0], str):
        return {}

    property_limits = {}
    for raw_limit in raw_limits:
        if len(raw_limit) == 2:
            continue
        if len(raw_limit) != 3:
            raise ValueError(
                f"{option_name} expects LOW HIGH or PROPERTY LOW HIGH. "
                f"Example: {option_name} pf 0 15 {option_name} zt 0 1.2."
            )
        property_key = normalize_property_axis_limit_key(raw_limit[0], valid_properties)
        limit_pair = parse_axis_limit(raw_limit[1:])
        if limit_pair is not None:
            property_limits[property_key] = limit_pair
    return property_limits


def build_plot_overrides(args: argparse.Namespace) -> dict:
    overrides = {}

    for attr in (
        "xscale",
        "yscale",
        "x_major",
        "x_minor",
        "y_major",
        "y_minor",
        "x_tick_format",
        "y_tick_format",
        "x_log_ticks",
        "y_log_ticks",
        "legend",
        "legend_loc",
        "legend_font_size",
        "subplot_aspect",
        "title",
    ):
        value = getattr(args, attr)
        if value is not None:
            overrides[attr] = value

    xlim = parse_axis_limit(args.xlim)
    ylim = parse_global_axis_limit_arg(args.ylim)
    if xlim is not None:
        overrides["xlim"] = xlim
    if ylim is not None:
        overrides["ylim"] = ylim
    if args.figsize is not None:
        overrides["figsize"] = [float(args.figsize[0]), float(args.figsize[1])]
    if args.show_title:
        overrides["show_title"] = True

    return overrides


def build_multi_property_plot_overrides(
    args: argparse.Namespace,
    valid_properties: tuple[str, ...],
) -> dict:
    overrides = build_plot_overrides(args)
    property_ylims = parse_property_axis_limits(args.ylim, valid_properties)
    if property_ylims:
        overrides["property_ylims"] = property_ylims
    return overrides


def parsed_x_curve_xlim(args: argparse.Namespace) -> tuple[float | None, float | None] | None:
    xlim = parse_axis_limit(args.xlim)
    if xlim is None:
        return None
    return (xlim[0], xlim[1])


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = EffectiveMassFitConfig(
        temperature=args.temperature,
        nh_unit=args.nh_unit,
        seebeck_unit=args.seebeck_unit,
        nh_column=args.nh_column,
        seebeck_column=args.seebeck_column,
        use_hall_factor=not args.no_hall_factor,
        curve_xlim=parsed_x_curve_xlim(args),
        manual_mstar_values=parse_manual_mstar_values(args.m),
        figure_formats=parse_output_formats(args.formats),
    )
    group_by = resolve_group_by_for_cli(args.csv_path, args.group_by, args.params, args.only)
    if group_by:
        result = run_effective_mass_fit_multi(
            args.csv_path,
            args.output_dir,
            group_by,
            config,
            params_path=args.params,
            temperature_column=args.temperature_column,
            only_groups=args.only,
            show=not args.no_show,
            plot_overrides=build_plot_overrides(args),
        )
        summary = result["summary"]
        print("SPB effective mass multi-fit finished")
        print(f"groups: {summary['n_groups']}")
        print(f"Points: {result['points_path']}")
        print(f"Curve: {result['curve_path']}")
        print(f"Summary: {result['summary_path']}")
        print(f"Summary by group: {result['summary_by_group_path']}")
        print(f"Plot: {', '.join(result['plot_paths'])}")
        print(f"Data folder plot: {', '.join(result['data_dir_plot_paths'])}")
        return 0

    result = run_effective_mass_fit(
        args.csv_path,
        args.output_dir,
        config,
        show=not args.no_show,
        plot_overrides=build_plot_overrides(args),
    )
    summary = result["summary"]

    if summary["mode"] == "fit":
        print("SPB effective mass fit finished")
        print(f"m*/me fit: {summary['mstar_over_me_fit']:.4f}")
        print(f"RMSE: {summary['rmse_uV_K']:.2f} uV/K")
    else:
        print("SPB effective mass manual curves finished")
        values = ", ".join(f"{value:.4g}" for value in summary["manual_mstar_values"])
        print(f"manual m*/me curves: {values}")
    print(f"Points: {result['points_path']}")
    print(f"Curve: {result['curve_path']}")
    print(f"Summary: {result['summary_path']}")
    print(f"Plot: {', '.join(result['plot_paths'])}")
    print(f"Data folder plot: {', '.join(result['data_dir_plot_paths'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fit SPB mobility prefactor from conductivity-Seebeck data."""

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
from scipy.constants import e


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.spb.effective_mass_fit import (  # noqa: E402
    DEFAULT_SEEBECK_COLUMN_CANDIDATES,
    SPB_FIT_STYLE_KEYS,
    _convert_seebeck_to_uv,
    _find_column,
    apply_plot_overrides,
    build_plot_overrides,
    copy_figures_to_input_data_dir,
    eta_from_seebeck_abs_uv,
    filter_source_by_groups,
    first_present,
    group_color,
    group_label_from_params,
    group_marker,
    group_temperature,
    hall_concentration_m3,
    is_blank_value,
    optional_bool,
    optional_float,
    parse_output_formats,
    parsed_x_curve_xlim,
    read_group_params,
    resolve_group_by_for_cli,
    safe_path_fragment,
    seebeck_abs_uv_from_eta,
    selector_display_label,
    series_style,
)
from src.tools.spb.performance_fit import (  # noqa: E402
    PF_COLUMN_CANDIDATES,
    ZT_COLUMN_CANDIDATES,
    MobilityModel,
    convert_pf_to_uw_cm,
    hall_mobility_factor_from_eta,
    lorenz_number_from_eta,
    normalize_unit,
    optional_find_column,
    pf_uw_cm_to_si,
    resolve_kappa_lattice,
)


CONDUCTIVITY_COLUMN_CANDIDATES = (
    "sigma",
    "Sigma",
    "conductivity",
    "Conductivity",
    "Electrical_Conductivity",
    "Electrical Conductivity",
    "EC",
    "sigma_S_cm-1",
    "sigma_S_cm^-1",
    "Conductivity_S_cm-1",
    "Conductivity_S_cm^-1",
    "sigma_S_m-1",
    "sigma_S_m^-1",
    "Conductivity_S_m-1",
    "Conductivity_S_m^-1",
)

PROPERTY_COLUMNS = {
    "seebeck": {
        "experimental": "Seebeck_abs_uV_K",
        "model": "Seebeck_model_abs_uV_K",
        "output_stem": "conductivity_seebeck_fit",
        "property": "seebeck",
        "ylabel": "$|S|$ (\u00b5V K$^{-1}$)",
        "model_label": "SPB S model",
        "data_label": "S data",
    },
    "pf": {
        "experimental": "Power_Factor_uW_cm-1_K-2",
        "model": "Power_Factor_model_uW_cm-1_K-2",
        "output_stem": "conductivity_pf_fit",
        "property": "power_factor",
        "ylabel": "$PF$ (\u00b5W cm$^{-1}$ K$^{-2}$)",
        "model_label": "SPB PF model",
        "data_label": "PF data",
    },
    "zt": {
        "experimental": "ZT",
        "model": "ZT_model",
        "output_stem": "conductivity_zt_fit",
        "property": "zt",
        "ylabel": "$zT$",
        "model_label": "SPB zT model",
        "data_label": "zT data",
    },
}


@dataclass
class ConductivityFitConfig:
    """Configuration for fitting SPB curves against conductivity as x."""

    temperature: float = 300.0
    conductivity_unit: str = "S/m"
    seebeck_unit: str = "uV/K"
    pf_unit: str = "uW cm^-1 K^-2"
    conductivity_column: str | None = None
    seebeck_column: str | None = None
    pf_column: str | None = None
    zt_column: str | None = None
    use_hall_factor: bool = True
    eta_min: float = -60.0
    eta_max: float = 80.0
    mstar_over_me: float = 1.0
    mobility_u0_cm2_vs: float | None = None
    scattering_lambda: float = 0.0
    kappa_lattice: str | float | None = None
    properties: tuple[str, ...] | None = None
    curve_points: int = 300
    curve_xlim: tuple[float | None, float | None] | None = None
    figure_formats: tuple[str, ...] = ("png", "pdf")


def convert_conductivity_to_s_m(values: pd.Series, unit: str) -> pd.Series:
    """Convert electrical conductivity to S m^-1."""

    normalized = normalize_unit(unit)
    if normalized in {
        "s/cm",
        "scm",
        "scm^-1",
        "scm-1",
        "s.cm^-1",
        "s.cm-1",
        "ohm^-1cm^-1",
        "ohm-1cm-1",
    }:
        return values.astype(float) * 100.0
    if normalized in {
        "s/m",
        "sm",
        "sm^-1",
        "sm-1",
        "s.m^-1",
        "s.m-1",
        "ohm^-1m^-1",
        "ohm-1m-1",
    }:
        return values.astype(float)
    raise ValueError(f"Unsupported conductivity unit: {unit}")


def prepare_conductivity_input_table(
    csv_path: str | os.PathLike,
    config: ConductivityFitConfig,
) -> tuple[pd.DataFrame, dict[str, str | None]]:
    """Load and normalize conductivity, Seebeck, PF, and zT columns."""

    df = pd.read_csv(csv_path)
    conductivity_column = _find_column(df, config.conductivity_column, CONDUCTIVITY_COLUMN_CANDIDATES)
    seebeck_column = _find_column(df, config.seebeck_column, DEFAULT_SEEBECK_COLUMN_CANDIDATES)
    pf_column = optional_find_column(df, config.pf_column, PF_COLUMN_CANDIDATES)
    zt_column = optional_find_column(df, config.zt_column, ZT_COLUMN_CANDIDATES)

    result = df.copy()
    result["Conductivity_S_m-1"] = convert_conductivity_to_s_m(result[conductivity_column], config.conductivity_unit)
    result["Conductivity_S_cm-1"] = result["Conductivity_S_m-1"] * 0.01
    result["Seebeck_uV_K"] = _convert_seebeck_to_uv(result[seebeck_column], config.seebeck_unit)
    result["Seebeck_abs_uV_K"] = result["Seebeck_uV_K"].abs()
    result["Temperature_K"] = config.temperature

    if pf_column:
        result["Power_Factor_uW_cm-1_K-2"] = convert_pf_to_uw_cm(result[pf_column], config.pf_unit)
        result["Power_Factor_W_m-1_K-2"] = pf_uw_cm_to_si(result["Power_Factor_uW_cm-1_K-2"])
    else:
        seebeck_v_k = result["Seebeck_abs_uV_K"] * 1e-6
        result["Power_Factor_W_m-1_K-2"] = seebeck_v_k * seebeck_v_k * result["Conductivity_S_m-1"]
        result["Power_Factor_uW_cm-1_K-2"] = result["Power_Factor_W_m-1_K-2"] / 1e-4
    if zt_column:
        result["ZT"] = pd.to_numeric(result[zt_column], errors="coerce")

    required = ["Conductivity_S_m-1", "Seebeck_abs_uV_K"]
    result = result.replace([np.inf, -np.inf], np.nan).dropna(subset=required).reset_index(drop=True)
    result = result[(result["Conductivity_S_m-1"] > 0) & (result["Seebeck_abs_uV_K"] > 0)].reset_index(drop=True)
    if result.empty:
        raise ValueError("No positive finite conductivity/Seebeck rows remain after cleaning")

    columns = {
        "conductivity": conductivity_column,
        "seebeck": seebeck_column,
        "pf": pf_column or "computed_from_conductivity_and_seebeck",
        "zt": zt_column,
    }
    return result, columns


def resolve_mstar_normalization(config: ConductivityFitConfig) -> float:
    if config.mstar_over_me <= 0:
        raise ValueError("--m/--mstar must be positive")
    return float(config.mstar_over_me)


def add_spb_coordinates_from_seebeck(
    points: pd.DataFrame,
    mstar_over_me: float,
    config: ConductivityFitConfig,
) -> pd.DataFrame:
    """Infer eta and the model Hall nH for each measured Seebeck value."""

    rows = []
    for _, row in points.iterrows():
        eta = eta_from_seebeck_abs_uv(
            row["Seebeck_abs_uV_K"],
            eta_min=config.eta_min,
            eta_max=config.eta_max,
        )
        nh_m3 = hall_concentration_m3(
            eta,
            mstar_over_me,
            config.temperature,
            use_hall_factor=config.use_hall_factor,
        )
        updated = row.to_dict()
        updated["eta_from_Seebeck"] = eta
        updated["nH_model_from_Seebeck_m-3"] = nh_m3
        updated["nH_model_from_Seebeck_cm-3"] = nh_m3 / 1e6
        updated["Hall_Mobility_factor_from_mu0"] = hall_mobility_factor_from_eta(
            eta,
            config.scattering_lambda,
        )
        rows.append(updated)
    return pd.DataFrame(rows)


def fit_mu0_from_conductivity(points: pd.DataFrame, config: ConductivityFitConfig) -> MobilityModel:
    """Fit mu0 from measured sigma after eta is fixed by measured Seebeck."""

    n_ref = float(np.exp(np.mean(np.log(points["nH_model_from_Seebeck_cm-3"].to_numpy(dtype=float)))))
    if config.mobility_u0_cm2_vs is not None:
        if config.mobility_u0_cm2_vs <= 0:
            raise ValueError("--u0/--mu0 must be positive")
        return MobilityModel(
            model="spb_u0",
            n_ref_cm3=n_ref,
            mu_ref_cm2_vs=float(config.mobility_u0_cm2_vs),
            source="fixed",
            mu0_cm2_vs=float(config.mobility_u0_cm2_vs),
            scattering_lambda=float(config.scattering_lambda),
        )

    x = (
        points["nH_model_from_Seebeck_m-3"].to_numpy(dtype=float)
        * e
        * 1e-4
        * points["Hall_Mobility_factor_from_mu0"].to_numpy(dtype=float)
    )
    y = points["Conductivity_S_m-1"].to_numpy(dtype=float)
    mu0 = float(np.sum(x * y) / np.sum(x * x))
    if not np.isfinite(mu0) or mu0 <= 0:
        raise ValueError("Could not fit a positive finite mu0 from conductivity-Seebeck data.")
    return MobilityModel(
        model="spb_u0",
        n_ref_cm3=n_ref,
        mu_ref_cm2_vs=mu0,
        source="fit",
        mu0_cm2_vs=mu0,
        scattering_lambda=float(config.scattering_lambda),
    )


def predict_row_from_eta(
    eta: float,
    mstar_over_me: float,
    config: ConductivityFitConfig,
    mobility_model: MobilityModel,
    kappa_lattice: float | None,
) -> dict[str, float]:
    nh_m3 = hall_concentration_m3(
        eta,
        mstar_over_me,
        config.temperature,
        use_hall_factor=config.use_hall_factor,
    )
    mobility_factor = hall_mobility_factor_from_eta(eta, mobility_model.scattering_lambda)
    mu0 = mobility_model.mu0_cm2_vs if mobility_model.mu0_cm2_vs is not None else mobility_model.mu_ref_cm2_vs
    mu_h = mu0 * mobility_factor
    sigma = nh_m3 * e * mu_h * 1e-4
    seebeck_abs_uv = seebeck_abs_uv_from_eta(eta)
    seebeck_v_k = seebeck_abs_uv * 1e-6
    pf_si = seebeck_v_k * seebeck_v_k * sigma
    lorenz = lorenz_number_from_eta(eta)
    kappa_e = lorenz * sigma * config.temperature

    row = {
        "eta": eta,
        "nH_model_cm-3": nh_m3 / 1e6,
        "nH_model_m-3": nh_m3,
        "Seebeck_model_abs_uV_K": seebeck_abs_uv,
        "Lorenz_Number_WOhmK-2": lorenz,
        "Lorenz_Number_1e-8_WOhmK-2": lorenz * 1e8,
        "Mobility_u0_model_cm2_V-1_s-1": mu0,
        "Hall_Mobility_factor_from_mu0": mobility_factor,
        "Hall_Mobility_model_cm2_V-1_s-1": mu_h,
        "Conductivity_model_S_m-1": sigma,
        "Conductivity_model_S_cm-1": sigma * 0.01,
        "Power_Factor_model_W_m-1_K-2": pf_si,
        "Power_Factor_model_uW_cm-1_K-2": pf_si / 1e-4,
        "Carrier_Thermal_Conductivity_model_W_m-1_K-1": kappa_e,
        "Temperature_K": config.temperature,
        "mstar_over_me": mstar_over_me,
        "Mobility_scattering_lambda": mobility_model.scattering_lambda,
    }
    if kappa_lattice is not None:
        kappa_total = kappa_lattice + kappa_e
        row["Lattice_Thermal_Conductivity_W_m-1_K-1"] = kappa_lattice
        row["Thermal_Conductivity_model_W_m-1_K-1"] = kappa_total
        row["ZT_model"] = pf_si * config.temperature / kappa_total
    return row


def add_model_predictions_at_points(
    points: pd.DataFrame,
    mstar_over_me: float,
    config: ConductivityFitConfig,
    mobility_model: MobilityModel,
    kappa_lattice: float | None,
) -> pd.DataFrame:
    rows = [
        predict_row_from_eta(float(eta), mstar_over_me, config, mobility_model, kappa_lattice)
        for eta in points["eta_from_Seebeck"].to_numpy(dtype=float)
    ]
    predictions = pd.DataFrame(rows)
    result = points.copy().reset_index(drop=True)
    for column in (
        "Conductivity_model_S_m-1",
        "Conductivity_model_S_cm-1",
        "Power_Factor_model_W_m-1_K-2",
        "Power_Factor_model_uW_cm-1_K-2",
        "Carrier_Thermal_Conductivity_model_W_m-1_K-1",
        "ZT_model",
    ):
        if column in predictions.columns:
            result[column] = predictions[column]
    result["Conductivity_residual_S_m-1"] = result["Conductivity_model_S_m-1"] - result["Conductivity_S_m-1"]
    result["Conductivity_residual_S_cm-1"] = result["Conductivity_model_S_cm-1"] - result["Conductivity_S_cm-1"]
    result["Power_Factor_residual_uW_cm-1_K-2"] = (
        result["Power_Factor_model_uW_cm-1_K-2"] - result["Power_Factor_uW_cm-1_K-2"]
    )
    if "ZT" in result.columns and "ZT_model" in result.columns:
        result["ZT_residual"] = result["ZT_model"] - result["ZT"]
    return result


def conductivity_curve_bounds(points: pd.DataFrame, config: ConductivityFitConfig) -> tuple[float, float]:
    sigma_min = float(points["Conductivity_S_cm-1"].min()) * 0.7
    sigma_max = float(points["Conductivity_S_cm-1"].max()) * 1.4
    if config.curve_xlim:
        low, high = config.curve_xlim
        if low is not None and float(low) > 0:
            sigma_min = min(sigma_min, float(low))
        if high is not None and float(high) > 0:
            sigma_max = max(sigma_max, float(high))
    if sigma_min <= 0 or sigma_max <= 0 or sigma_min >= sigma_max:
        raise ValueError(f"Invalid conductivity curve bounds: {sigma_min}, {sigma_max}")
    return sigma_min, sigma_max


def build_conductivity_curve(
    points: pd.DataFrame,
    mstar_over_me: float,
    config: ConductivityFitConfig,
    mobility_model: MobilityModel,
    kappa_lattice: float | None,
) -> pd.DataFrame:
    sigma_min, sigma_max = conductivity_curve_bounds(points, config)
    dense_count = max(config.curve_points * 4, 600)
    eta_values = np.linspace(config.eta_min, config.eta_max, dense_count)
    rows = [
        predict_row_from_eta(float(eta), mstar_over_me, config, mobility_model, kappa_lattice)
        for eta in eta_values
    ]
    dense = pd.DataFrame(rows).sort_values("Conductivity_model_S_cm-1").reset_index(drop=True)
    window = dense[
        (dense["Conductivity_model_S_cm-1"] >= sigma_min)
        & (dense["Conductivity_model_S_cm-1"] <= sigma_max)
    ]
    if len(window) < 4:
        window = dense
    if len(window) > config.curve_points:
        take = np.linspace(0, len(window) - 1, config.curve_points).round().astype(int)
        window = window.iloc[take]
    return window.reset_index(drop=True)


def infer_properties(points: pd.DataFrame, config: ConductivityFitConfig, kappa_lattice: float | None) -> tuple[str, ...]:
    if config.properties:
        return config.properties
    properties = ["seebeck", "pf"]
    if kappa_lattice is not None or "ZT" in points.columns:
        properties.append("zt")
    return tuple(properties)


def fit_quality(points: pd.DataFrame) -> dict[str, float]:
    residual = pd.to_numeric(points["Conductivity_residual_S_cm-1"], errors="coerce").dropna()
    if residual.empty:
        return {}
    return {
        "conductivity_rmse_S_cm-1": float(np.sqrt(np.mean(residual * residual))),
        "conductivity_mae_S_cm-1": float(np.mean(np.abs(residual))),
        "conductivity_max_abs_error_S_cm-1": float(np.max(np.abs(residual))),
    }


def model_legend_parameters(mobility_model: MobilityModel, kappa_lattice: float | None) -> str:
    """Format compact fitted/fixed parameters for plot legends."""

    mu0 = mobility_model.mu0_cm2_vs if mobility_model.mu0_cm2_vs is not None else mobility_model.mu_ref_cm2_vs
    parts = [f"u0={mu0:.3g} {mobility_model.source}"]
    if kappa_lattice is not None:
        parts.append(f"kL={kappa_lattice:.3g}")
    return ", ".join(parts)


def default_conductivity_recipe(property_key: str) -> dict[str, Any]:
    info = PROPERTY_COLUMNS[property_key]
    return {
        "name": f"spb_{info['output_stem']}",
        "plot": {
            "kind": "line",
            "x": {"column": "Conductivity_S_cm-1", "label": r"$\sigma$ (S cm$^{-1}$)"},
            "series": [
                {
                    "y": {"column": info["model"], "label": info["ylabel"]},
                    "property": info["property"],
                    "group_value": info["model_label"],
                    "marker": "None",
                    "linestyle": "-",
                    "line_width": 1.4,
                },
                {
                    "y": {"column": info["experimental"], "label": info["ylabel"]},
                    "property": info["property"],
                    "group_value": info["data_label"],
                    "color": "black",
                    "marker": "o",
                    "linestyle": "none",
                    "line_width": 0.0,
                },
            ],
            "xlabel": r"$\sigma$ (S cm$^{-1}$)",
            "ylabel": info["ylabel"],
            "xscale": "log",
            "x_log_ticks": "decade",
            "legend": "inside",
            "legend_loc": "best",
            "x_margin": 0.04,
            "y_margin": 0.08,
        },
    }


def load_conductivity_recipe(property_key: str) -> dict[str, Any]:
    recipe_path = ROOT / f"configs/plot_recipes/spb/{PROPERTY_COLUMNS[property_key]['output_stem']}.json"
    fallback = default_conductivity_recipe(property_key)
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
    series_specs = plot.get("series") or default_conductivity_recipe(property_key)["plot"]["series"]
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
        if "legend_parameters" in curve_group.columns and not is_blank_value(curve_group["legend_parameters"].iloc[0]):
            legend_label = f"{legend_label}\n{curve_group['legend_parameters'].iloc[0]}"
        curve_frame = pd.DataFrame(
            {
                "x": curve_group["Conductivity_model_S_cm-1"].to_numpy(dtype=float),
                "x_category": curve_group["Conductivity_model_S_cm-1"].astype(str).to_numpy(),
                "y": curve_group[columns["model"]].to_numpy(dtype=float),
                "property": property_name,
                "group": legend_label,
                "legend_label": legend_label,
                "label": "",
                "condition": "",
                "source": "conductivity_curve",
                "x_source_column": "Conductivity_model_S_cm-1",
                "y_source_column": columns["model"],
                "series_order": curve_index * 2,
            }
        )
        for key in SPB_FIT_STYLE_KEYS:
            curve_frame[key] = series_style(curve_spec, key)
        curve_frame["color"] = group_color(curve_index)
        frames.append(curve_frame)

    if columns["experimental"] in points.columns:
        for point_index, (_, point_group) in enumerate(point_groups):
            legend_label = point_spec.get("legend_label", point_spec.get("group_value", "data"))
            if "legend_label" in point_group.columns and not is_blank_value(point_group["legend_label"].iloc[0]):
                legend_label = str(point_group["legend_label"].iloc[0])
            point_frame = pd.DataFrame(
                {
                    "x": point_group["Conductivity_S_cm-1"].to_numpy(dtype=float),
                    "x_category": point_group["Conductivity_S_cm-1"].astype(str).to_numpy(),
                    "y": point_group[columns["experimental"]].to_numpy(dtype=float),
                    "property": property_name,
                    "group": legend_label,
                    "legend_label": legend_label,
                    "label": "",
                    "condition": "",
                    "source": "conductivity_points",
                    "x_source_column": "Conductivity_S_cm-1",
                    "y_source_column": columns["experimental"],
                    "series_order": point_index * 2 + 1,
                }
            )
            for key in SPB_FIT_STYLE_KEYS:
                point_frame[key] = series_style(point_spec, key)
            point_frame["color"] = group_color(point_index)
            point_frame["marker"] = group_marker(point_index)
            frames.append(point_frame)

    normalized = pd.concat(frames, ignore_index=True).dropna(subset=["x", "y"])
    metadata = {
        "x_label": selector_display_label(plot.get("x"), "Conductivity_S_cm-1"),
        "property_labels": {property_name: property_label},
        "kind": plot.get("kind", "line"),
        "title": plot.get("title", recipe.get("name", "")),
        "categorical_x": False,
        "x_categories": [],
    }
    return normalized, metadata


def plot_conductivity_property_fit(
    points: pd.DataFrame,
    curve: pd.DataFrame,
    property_key: str,
    output_dir: Path,
    formats: tuple[str, ...],
    show: bool = False,
    plot_overrides: dict | None = None,
) -> list[str]:
    cache_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "te_matplotlib_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))

    from src.tools.flexible_plot import plot_line_or_scatter
    from src.tools.plot import save_figure

    import matplotlib.pyplot as plt

    recipe = apply_plot_overrides(load_conductivity_recipe(property_key), plot_overrides)
    normalized, metadata = build_property_normalized_table(points, curve, property_key, recipe)
    fig, _ = plot_line_or_scatter(normalized, metadata, recipe)

    output_stem = PROPERTY_COLUMNS[property_key]["output_stem"]
    save_figure(fig, f"{output_stem}.png", save_dir=str(output_dir), formats=formats)
    if show:
        plt.show()
    plt.close(fig)
    return [str(output_dir / f"{output_stem}.{file_format}") for file_format in formats]


def run_conductivity_fit(
    csv_path: str | os.PathLike,
    output_dir: str | os.PathLike,
    config: ConductivityFitConfig | None = None,
    show: bool = False,
    plot_overrides: dict | None = None,
) -> dict[str, Any]:
    config = config or ConductivityFitConfig()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mstar_over_me = resolve_mstar_normalization(config)
    points, source_columns = prepare_conductivity_input_table(csv_path, config)
    points = add_spb_coordinates_from_seebeck(points, mstar_over_me, config)
    mobility_model = fit_mu0_from_conductivity(points, config)
    kappa_lattice, kappa_lattice_source = resolve_kappa_lattice(points, config.kappa_lattice)
    curve = build_conductivity_curve(points, mstar_over_me, config, mobility_model, kappa_lattice)
    curve["legend_parameters"] = model_legend_parameters(mobility_model, kappa_lattice)
    points = add_model_predictions_at_points(points, mstar_over_me, config, mobility_model, kappa_lattice)

    properties = infer_properties(points, config, kappa_lattice)
    if "zt" in properties and "ZT_model" not in curve.columns:
        raise ValueError("zT modeling needs --kL/--kappa-lattice VALUE.")

    summary: dict[str, Any] = {
        "input_csv": str(csv_path),
        "temperature_K": config.temperature,
        "source_columns": source_columns,
        "config": asdict(config),
        "mstar": {
            "mode": "normalization",
            "mstar_over_me": mstar_over_me,
            "note": "For conductivity-based fitting, fitted u0 is a weighted mobility prefactor that absorbs the chosen m* normalization.",
        },
        "mobility_model": asdict(mobility_model),
        "kappa_lattice_W_m-1_K-1": kappa_lattice,
        "kappa_lattice_source": kappa_lattice_source,
        "properties": list(properties),
        "n_points": int(len(points)),
    }
    summary.update(fit_quality(points))

    points_path = output_dir / "conductivity_points.csv"
    curve_path = output_dir / "conductivity_curve.csv"
    summary_path = output_dir / "conductivity_summary.json"
    points.to_csv(points_path, index=False)
    curve.to_csv(curve_path, index=False)
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    plot_paths: dict[str, list[str]] = {}
    data_dir_plot_paths: dict[str, list[str]] = {}
    for property_key in properties:
        plot_paths[property_key] = plot_conductivity_property_fit(
            points,
            curve,
            property_key,
            output_dir,
            config.figure_formats,
            show=show,
            plot_overrides=plot_overrides,
        )
        data_dir_plot_paths[property_key] = copy_figures_to_input_data_dir(
            plot_paths[property_key],
            csv_path,
        )

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


def conductivity_config_for_group(
    base_config: ConductivityFitConfig,
    group_df: pd.DataFrame,
    temperature_column: str | None,
    params_row: pd.Series | None,
) -> ConductivityFitConfig:
    config = ConductivityFitConfig(**asdict(base_config))
    config.temperature = group_temperature(group_df, base_config.temperature, temperature_column, params_row)

    config_mstar = optional_float(first_present(params_row, ("m", "mstar", "mstar_over_me", "effective_mass")))
    if config_mstar is not None:
        config.mstar_over_me = config_mstar

    config_u0 = optional_float(first_present(params_row, ("u0", "mu0", "mobility_u0_cm2_vs")))
    if config_u0 is not None:
        config.mobility_u0_cm2_vs = config_u0

    config_kappa_lattice = first_present(params_row, ("kL", "kl", "kappa_lattice", "kappa_lattice_W_m-1_K-1"))
    if config_kappa_lattice is not None:
        config.kappa_lattice = config_kappa_lattice

    config_lambda = optional_float(first_present(params_row, ("lambda", "scattering_lambda")))
    if config_lambda is not None:
        config.scattering_lambda = config_lambda

    use_hall_factor = optional_bool(first_present(params_row, ("use_hall_factor", "hall_factor")))
    if use_hall_factor is not None:
        config.use_hall_factor = use_hall_factor

    sigma_unit = optional_text(first_present(params_row, ("sigma_unit", "conductivity_unit")))
    if sigma_unit is not None:
        config.conductivity_unit = sigma_unit

    return config


def run_conductivity_fit_multi(
    csv_path: str | os.PathLike,
    output_dir: str | os.PathLike,
    group_by: str,
    config: ConductivityFitConfig | None = None,
    params_path: str | os.PathLike | None = None,
    temperature_column: str | None = None,
    only_groups: list[str] | tuple[str, ...] | None = None,
    show: bool = False,
    plot_overrides: dict | None = None,
) -> dict[str, Any]:
    """Run conductivity-based SPB fits for multiple groups."""

    config = config or ConductivityFitConfig()
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
        group_config = conductivity_config_for_group(config, group_df, temperature_column, params_row)

        group_dir = groups_dir / safe_path_fragment(group_key)
        group_dir.mkdir(parents=True, exist_ok=True)
        group_input_path = group_dir / "input.csv"
        group_df.to_csv(group_input_path, index=False)

        result = run_conductivity_fit(
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
        curve["legend_parameters"] = model_legend_parameters(
            MobilityModel(**summary["mobility_model"]),
            summary.get("kappa_lattice_W_m-1_K-1"),
        )
        curve["series_order"] = group_index * 2

        point_frames.append(points)
        curve_frames.append(curve)

        group_results.append(
            {
                group_by: group_key,
                "curve_id": group_key,
                "label": group_label,
                "temperature_K": group_config.temperature,
                "mstar_over_me": summary["mstar"]["mstar_over_me"],
                "mu0_cm2_vs": summary["mobility_model"].get("mu0_cm2_vs"),
                "u0_source": summary["mobility_model"].get("source"),
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

    points_path = output_dir / "conductivity_points.csv"
    curve_path = output_dir / "conductivity_curve.csv"
    summary_path = output_dir / "conductivity_summary.json"
    summary_by_group_path = output_dir / "conductivity_summary_by_group.csv"
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
        plot_paths[property_key] = plot_conductivity_property_fit(
            combined_points,
            combined_curve,
            property_key,
            output_dir,
            config.figure_formats,
            show=show,
            plot_overrides=combined_plot_overrides,
        )
        data_dir_plot_paths[property_key] = copy_figures_to_input_data_dir(
            plot_paths[property_key],
            csv_path,
        )

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
        description="Fit SPB u0 from conductivity-Seebeck data and plot S/PF/zT versus conductivity.",
    )
    parser.add_argument("csv_path", help="Input CSV containing conductivity and Seebeck columns.")
    parser.add_argument(
        "--output-dir",
        default="results/spb_fitting/conductivity_fit",
        help="Directory for output CSV/JSON/PNG files.",
    )
    parser.add_argument("--temperature", "--T", type=float, default=300.0, help="Measurement temperature in K.")
    parser.add_argument("--group-by", "--group", "-g", dest="group_by", help="Column defining independent fit groups, e.g. curve_id.")
    parser.add_argument("--only", nargs="+", help="Fit only selected group value(s). Defaults to curve_id when --group is omitted.")
    parser.add_argument("--params", help="Optional per-group parameter CSV keyed by --group-by or curve_id.")
    parser.add_argument("--T-column", "--temperature-column", dest="temperature_column", help="Column containing per-group temperature in K.")
    parser.add_argument("--x", "--sigma", "--conductivity-column", dest="conductivity_column", help="Electrical conductivity column name.")
    parser.add_argument("--y", "--seebeck-column", dest="seebeck_column", help="Seebeck column name.")
    parser.add_argument("--pf", "--pf-column", dest="pf_column", help="Optional power-factor column name.")
    parser.add_argument("--zt", "--zt-column", dest="zt_column", help="Optional zT column name.")
    parser.add_argument("--sigma-unit", "--conductivity-unit", dest="conductivity_unit", default="S/m", help="Conductivity unit: S/m or S/cm. Default: S/m.")
    parser.add_argument("--seebeck-unit", default="uV/K", help="Seebeck unit: uV/K or V/K.")
    parser.add_argument("--pf-unit", default="uW cm^-1 K^-2", help="PF unit: uW cm^-1 K^-2 or W m^-1 K^-2.")
    parser.add_argument(
        "--mstar",
        "--m",
        "--effective-mass",
        dest="mstar",
        type=float,
        default=1.0,
        help=(
            "Density-of-states effective-mass normalization m*/me used to report weighted u0. "
            "Default: 1.0."
        ),
    )
    parser.add_argument(
        "--u0",
        "--mu0",
        dest="mobility_u0_cm2_vs",
        type=float,
        default=None,
        help="Use fixed weighted SPB mobility prefactor mu0 in cm^2 V^-1 s^-1. If omitted, fit mu0 from S-sigma.",
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
        choices=("seebeck", "pf", "zt"),
        default=None,
        help="Which curves to plot. Default: seebeck pf, plus zt when --kL is provided.",
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
        help="Use nH = n instead of nH = n/rH in the SPB sigma model.",
    )
    parser.add_argument("--no-show", action="store_true", help="Save outputs without calling plt.show().")
    parser.add_argument("--xlim", nargs=2, metavar=("LOW", "HIGH"), help="Override x-axis limits in S/cm; use auto for one side.")
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


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = ConductivityFitConfig(
        temperature=args.temperature,
        conductivity_unit=args.conductivity_unit,
        seebeck_unit=args.seebeck_unit,
        pf_unit=args.pf_unit,
        conductivity_column=args.conductivity_column,
        seebeck_column=args.seebeck_column,
        pf_column=args.pf_column,
        zt_column=args.zt_column,
        use_hall_factor=not args.no_hall_factor,
        mstar_over_me=args.mstar,
        mobility_u0_cm2_vs=args.mobility_u0_cm2_vs,
        scattering_lambda=args.scattering_lambda,
        kappa_lattice=args.kappa_lattice,
        properties=tuple(args.properties) if args.properties else None,
        curve_xlim=parsed_x_curve_xlim(args),
        figure_formats=parse_output_formats(args.formats),
    )
    group_by = resolve_group_by_for_cli(args.csv_path, args.group_by, args.params, args.only)
    if group_by:
        result = run_conductivity_fit_multi(
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
        print("SPB conductivity multi-fit finished")
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

    result = run_conductivity_fit(
        args.csv_path,
        args.output_dir,
        config,
        show=not args.no_show,
        plot_overrides=build_plot_overrides(args),
    )
    summary = result["summary"]
    mobility = summary["mobility_model"]

    print("SPB conductivity fit finished")
    print(f"m*/me normalization: {summary['mstar']['mstar_over_me']:.4f}")
    print(
        "Mobility model: "
        f"weighted mu_H(eta) from mu0 = {mobility['mu0_cm2_vs']:.3g} cm^2/V/s, "
        f"lambda = {mobility['scattering_lambda']:.3g} ({mobility['source']})"
    )
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

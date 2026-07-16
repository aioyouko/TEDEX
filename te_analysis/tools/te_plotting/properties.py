"""TE property keys, column aliases, and dataframe standardization.

Split verbatim from scripts/plotting/plot_te.py; behavior unchanged.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from pathlib import Path

import pandas as pd

from te_analysis.tools.plot import TE_PLOT_SPECS
from te_analysis.tools.selectors import (
    normalize_sample_selector as normalize_selector,
    truncate_with_digest,
)


PROPERTY_KEY_ALIASES = {
    "rho": "resistivity",
    "s": "seebeck",
    "electrical_conductivity": "conductivity",
    "sigma": "conductivity",
    "sig": "conductivity",
    "cond": "conductivity",
    "tc": "thermal_conductivity",
    "thermal": "thermal_conductivity",
    "kappa": "thermal_conductivity",
    "kt": "thermal_conductivity",
    "ktot": "thermal_conductivity",
    "kappa_total": "thermal_conductivity",
    "kappa_tot": "thermal_conductivity",
    "total_kappa": "thermal_conductivity",
    "diff": "diffusivity",
    "alpha": "diffusivity",
    "ke": "carrier_thermal_conductivity",
    "k_e": "carrier_thermal_conductivity",
    "kappa_e": "carrier_thermal_conductivity",
    "carrier": "carrier_thermal_conductivity",
    "carrier_kappa": "carrier_thermal_conductivity",
    "electronic_kappa": "carrier_thermal_conductivity",
    "kl": "lattice_thermal_conductivity",
    "k_l": "lattice_thermal_conductivity",
    "kappa_l": "lattice_thermal_conductivity",
    "lattice": "lattice_thermal_conductivity",
    "kappa_lattice": "lattice_thermal_conductivity",
    "lattice_kappa": "lattice_thermal_conductivity",
    "lorenz": "lorenz_number",
    "eta": "generalized_fermi_level",
    "muw": "weighted_mobility",
    "mu_w": "weighted_mobility",
    "weighted_mu": "weighted_mobility",
    "b": "quality_factor",
    "qb": "quality_factor",
    "powerfactor": "power_factor",
    "pf": "power_factor",
}
PROPERTY_FLAG_ALIASES = {
    "resistivity": ("rho",),
    "seebeck": ("s",),
    "conductivity": ("sigma", "cond"),
    "thermal_conductivity": ("kappa", "kt", "ktot", "tc"),
    "diffusivity": ("diff", "alpha"),
    "carrier_thermal_conductivity": ("ke", "kappa-e"),
    "lattice_thermal_conductivity": ("kl", "kappa-l", "lattice"),
    "lorenz_number": ("lorenz",),
    "generalized_fermi_level": ("eta",),
    "weighted_mobility": ("muw", "mu-w"),
    "quality_factor": ("b",),
    "power_factor": ("pf",),
}


def valid_property_list():
    return ", ".join(TE_PLOT_SPECS.keys())


def normalize_property_key(raw_property, option_name="property"):
    property_key = str(raw_property).strip().lower().replace("-", "_")
    property_key = PROPERTY_KEY_ALIASES.get(property_key, property_key)

    if property_key not in TE_PLOT_SPECS:
        raise ValueError(
            f"{option_name} must be one of: {valid_property_list()}. "
            f"Got {raw_property!r}."
        )

    return property_key


def normalize_property_keys(property_keys, option_name="property"):
    if property_keys is None:
        return None

    selected_properties = []
    for raw_property in property_keys:
        property_key = normalize_property_key(raw_property, option_name)
        if property_key not in selected_properties:
            selected_properties.append(property_key)

    return selected_properties


def normalize_column_token(column_name):
    text = str(column_name).strip().lower()
    text = (
        text.replace("µ", "u")
        .replace("μ", "u")
        .replace("κ", "kappa")
        .replace("σ", "sigma")
        .replace("ρ", "rho")
    )
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def build_te_column_aliases():
    aliases = {
        "Temperature": [
            "temperature",
            "temp",
            "t",
            "temperaturek",
            "tk",
        ],
        "Resistivity": [
            "resistivity",
            "electrical resistivity",
            "rho",
        ],
        "Seebeck": [
            "seebeck",
            "seebeck coefficient",
            "s",
        ],
        "Conductivity": [
            "conductivity",
            "electrical conductivity",
            "sigma",
        ],
        "Thermal_Conductivity": [
            "thermal conductivity",
            "total thermal conductivity",
            "kappa",
            "kappa total",
            "kappa tot",
        ],
        "Diffusivity": [
            "diffusivity",
            "thermal diffusivity",
        ],
        "Carrier_Thermal_Conductivity": [
            "carrier thermal conductivity",
            "electronic thermal conductivity",
            "kappa e",
            "kappa electronic",
        ],
        "Lattice_Thermal_Conductivity": [
            "lattice thermal conductivity",
            "kappa l",
            "kappa lattice",
        ],
        "Lorenz_Number_1e-8_WOhmK-2": [
            "lorenz number",
            "lorenz",
            "l",
        ],
        "Generalized_Fermi_Level": [
            "generalized fermi level",
            "fermi level",
            "eta",
        ],
        "Weighted_Mobility_cm2_V-1_s-1": [
            "weighted mobility",
            "mu w",
            "muw",
        ],
        "Quality_Factor_B": [
            "quality factor",
            "quality factor b",
            "b",
        ],
        "ZT": [
            "zt",
            "z t",
        ],
        "Power_Factor": [
            "power factor",
            "powerfactor",
            "pf",
        ],
    }

    for property_key, spec in TE_PLOT_SPECS.items():
        canonical_column = spec["column"]
        aliases.setdefault(canonical_column, [])
        aliases[canonical_column].extend([canonical_column, property_key])

    alias_map = {}
    for canonical_column, raw_aliases in aliases.items():
        alias_map[normalize_column_token(canonical_column)] = canonical_column
        for raw_alias in raw_aliases:
            alias_map[normalize_column_token(raw_alias)] = canonical_column

    return alias_map


TE_COLUMN_ALIASES = build_te_column_aliases()


def standardize_te_dataframe_columns(df, csv_path=None):
    """
    Normalize copied/hand-curated TE CSVs to the processed-data column contract.

    Direct inter-batch folders are often assembled by copying selected CSVs into
    one place. In that workflow the first column is treated as temperature even
    when it is named "T", "Temp (K)", or similar.
    """
    if df.empty or len(df.columns) == 0:
        return df

    standardized = df.copy()
    first_column = standardized.columns[0]
    standardized["Temperature"] = pd.to_numeric(standardized[first_column], errors="coerce")

    for column in list(standardized.columns):
        canonical_column = TE_COLUMN_ALIASES.get(normalize_column_token(column))
        if not canonical_column or canonical_column == "Temperature":
            continue
        if canonical_column not in standardized.columns:
            standardized[canonical_column] = pd.to_numeric(standardized[column], errors="coerce")

    return standardized


def add_property_flag_arguments(parser):
    property_group = parser.add_argument_group("single-property shortcuts")

    for property_key, spec in TE_PLOT_SPECS.items():
        dashed_key = property_key.replace("_", "-")
        option_strings = [f"--{dashed_key}", f"-{dashed_key}"]
        if dashed_key != property_key:
            option_strings.extend([f"--{property_key}", f"-{property_key}"])
        seen_options = set(option_strings)
        for alias in PROPERTY_FLAG_ALIASES.get(property_key, ()):
            alias_variants = {
                alias,
                alias.replace("_", "-"),
                alias.replace("-", "_"),
            }
            for alias_variant in sorted(alias_variants):
                if not alias_variant:
                    continue
                for prefix in ("--", "-"):
                    option_string = f"{prefix}{alias_variant}"
                    if option_string not in seen_options:
                        option_strings.append(option_string)
                        seen_options.add(option_string)

        property_group.add_argument(
            *option_strings,
            dest=f"plot_property_{property_key}",
            action="store_true",
            help=f"Plot the {spec['title']} single-property figure.",
        )


def get_property_flag_selection(args):
    selected_properties = []

    for property_key in TE_PLOT_SPECS:
        if getattr(args, f"plot_property_{property_key}", False):
            selected_properties.append(property_key)

    return selected_properties


def get_requested_single_properties(args):
    selected_properties = normalize_property_keys(
        args.single_properties,
        "--single-properties/--properties",
    ) or []

    for property_key in get_property_flag_selection(args):
        if property_key not in selected_properties:
            selected_properties.append(property_key)

    return selected_properties or None



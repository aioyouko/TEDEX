import os
from glob import glob

import numpy as np
import pandas as pd
from scipy.constants import e, h, k, m_e
from scipy.integrate import quad
from scipy.optimize import root
from scipy.special import expit

WEIGHTED_MOBILITY_COLUMN = 'Weighted_Mobility_cm2_V-1_s-1'
QUALITY_FACTOR_COLUMN = 'Quality_Factor_B'


REQUIRED_COLUMNS = {
    'Temperature',
    'Seebeck',
    'Conductivity',
    'Thermal_Conductivity',
}

OUTPUT_COLUMNS = [
    'Generalized_Fermi_Level',
    'Lorenz_Number',
    'Lorenz_Number_1e-8_WOhmK-2',
    WEIGHTED_MOBILITY_COLUMN,
    'Carrier_Thermal_Conductivity',
    'Lattice_Thermal_Conductivity',
    QUALITY_FACTOR_COLUMN,
]


def fermi_integral(eta, order=0):
    """
    Calculate the Fermi integral used by the simple SPB Lorenz-number model.
    """
    eta = float(np.asarray(eta).ravel()[0])
    integrand = lambda x: (x ** order) * expit(eta - x)
    result, _ = quad(integrand, 0, np.inf)
    return result


def calculate_generalized_fermi_level(seebeck):
    """
    Calculate generalized Fermi level from Seebeck coefficient.

    Parameters
    ----------
    seebeck : float
        Seebeck coefficient in V/K. The magnitude is used because the current
        SPB relation is solving carrier degeneracy rather than carrier sign.
    """
    alpha = abs(seebeck)

    def equation(eta):
        f0 = fermi_integral(eta, order=0)
        f1 = fermi_integral(eta, order=1)
        return k / e * (2 * f1 / f0 - eta) - alpha

    solution = root(equation, x0=0)
    if not solution.success:
        raise ValueError(f"Root finding did not converge for Seebeck={seebeck}")

    return solution.x[0]


def calculate_lorenz_number(generalized_fermi_level):
    """
    Calculate Lorenz number in W Ohm K^-2.
    """
    eta = generalized_fermi_level
    f0 = fermi_integral(eta, order=0)
    f1 = fermi_integral(eta, order=1)
    f2 = fermi_integral(eta, order=2)

    return (k ** 2 / e ** 2) * (3 * f0 * f2 - 4 * f1 ** 2) / f0 ** 2


def calculate_weighted_mobility(conductivity, temperature, generalized_fermi_level):
    """
    Calculate SPB weighted mobility in cm^2 V^-1 s^-1.

    The expression follows the acoustic-phonon SPB relation:
    mu_w = 3 sigma / (8 pi e F_0(eta)) * (h^2 / (2 m_e k_B T))^(3/2).
    Input conductivity is S/m and temperature is K.
    """
    sigma = float(conductivity)
    temp = float(temperature)
    eta = float(generalized_fermi_level)

    if not np.isfinite(sigma) or sigma <= 0:
        return np.nan
    if not np.isfinite(temp) or temp <= 0:
        return np.nan

    f0 = fermi_integral(eta, order=0)
    if not np.isfinite(f0) or f0 <= 0:
        return np.nan

    mobility_m2_per_vs = (
        3
        * sigma
        / (8 * np.pi * e * f0)
        * (h ** 2 / (2 * m_e * k * temp)) ** 1.5
    )
    return mobility_m2_per_vs * 1e4


def calculate_quality_factor(weighted_mobility, lattice_thermal_conductivity):
    """
    Calculate quality factor B as weighted mobility divided by lattice kappa.
    """
    mobility = float(weighted_mobility)
    k_lattice = float(lattice_thermal_conductivity)

    if not np.isfinite(mobility):
        return np.nan
    if not np.isfinite(k_lattice) or k_lattice <= 0:
        return np.nan

    return mobility / k_lattice


def validate_transport_dataframe(df):
    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")


def add_lattice_thermal_conductivity(df):
    """
    Add SPB-derived transport columns.

    Input columns expected from processed TE data:
    - Temperature: K
    - Seebeck: V/K
    - Conductivity: S/m
    - Thermal_Conductivity: W/m/K

    Added SPB-derived columns include weighted mobility in cm^2 V^-1 s^-1
    and quality factor B = weighted mobility / lattice thermal conductivity.
    """
    validate_transport_dataframe(df)
    result_df = df.copy()

    fermi_levels = []
    lorenz_numbers = []
    weighted_mobilities = []

    for _, row in result_df.iterrows():
        seebeck = row['Seebeck']
        eta = calculate_generalized_fermi_level(seebeck)
        lorenz_number = calculate_lorenz_number(eta)
        weighted_mobility = calculate_weighted_mobility(
            row['Conductivity'],
            row['Temperature'],
            eta,
        )

        fermi_levels.append(eta)
        lorenz_numbers.append(lorenz_number)
        weighted_mobilities.append(weighted_mobility)

    result_df['Generalized_Fermi_Level'] = fermi_levels
    result_df['Lorenz_Number'] = lorenz_numbers
    result_df['Lorenz_Number_1e-8_WOhmK-2'] = result_df['Lorenz_Number'] * 1e8
    result_df[WEIGHTED_MOBILITY_COLUMN] = weighted_mobilities
    result_df['Carrier_Thermal_Conductivity'] = (
        result_df['Lorenz_Number']
        * result_df['Conductivity']
        * result_df['Temperature']
    )
    result_df['Lattice_Thermal_Conductivity'] = (
        result_df['Thermal_Conductivity']
        - result_df['Carrier_Thermal_Conductivity']
    )
    result_df[QUALITY_FACTOR_COLUMN] = [
        calculate_quality_factor(mobility, lattice_k)
        for mobility, lattice_k in zip(
            result_df[WEIGHTED_MOBILITY_COLUMN],
            result_df['Lattice_Thermal_Conductivity'],
        )
    ]

    return result_df


def get_processed_batch_dir(batch_id, processed_root='data/processed'):
    return os.path.join(processed_root, f'{batch_id}-processed')


def get_processed_csv_paths(batch_id, processed_root='data/processed'):
    processed_dir = get_processed_batch_dir(batch_id, processed_root=processed_root)
    return sorted(glob(os.path.join(processed_dir, '*.csv')))


def calculate_lattice_for_csv(csv_path, save=True):
    """
    Load one processed CSV, add SPB-derived columns, and optionally save it.
    """
    df = pd.read_csv(csv_path)
    updated_df = add_lattice_thermal_conductivity(df)

    if save:
        updated_df.to_csv(csv_path, index=False)
        print(f"✅ SPB-derived columns saved: {csv_path}")

    return updated_df


def calculate_lattice_for_batch(batch_id, processed_root='data/processed', save=True):
    """
    Add SPB-derived columns to every processed CSV in one batch folder.

    Returns
    -------
    dict
        sample_name -> updated dataframe
    """
    csv_paths = get_processed_csv_paths(batch_id, processed_root=processed_root)
    if not csv_paths:
        print(f"⚠️ no processed CSV files found for batch: {batch_id}")
        return {}

    updated_data = {}

    for csv_path in csv_paths:
        sample_name = os.path.splitext(os.path.basename(csv_path))[0]
        try:
            updated_data[sample_name] = calculate_lattice_for_csv(csv_path, save=save)
        except Exception as exc:
            print(f"❌ lattice calculation failed for {sample_name}: {exc}")

    return updated_data


def calculate_lattice_for_dataframes(processed_data):
    """
    Add SPB-derived columns to an in-memory sample_name -> dataframe dict.
    """
    updated_data = {}

    for sample_name, df in processed_data.items():
        try:
            updated_data[sample_name] = add_lattice_thermal_conductivity(df)
        except Exception as exc:
            print(f"❌ lattice calculation failed for {sample_name}: {exc}")
            updated_data[sample_name] = df

    return updated_data

import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def get_nearest_temperature_row(df, target_temperature):
    """
    Select the data row closest to target_temperature.

    Parameters
    ----------
    df : pandas.DataFrame
        Processed TE dataframe containing Temperature, Seebeck, Conductivity.
    target_temperature : float
        Target temperature in K.

    Returns
    -------
    pandas.Series
        Row closest to target_temperature.
    """
    required_columns = {'Temperature', 'Seebeck', 'Conductivity'}
    missing_columns = required_columns - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    idx = (df['Temperature'] - target_temperature).abs().idxmin()
    return df.loc[idx]


def collect_transport_points(processed_data, target_temperature):
    """
    Collect Seebeck and conductivity values near one temperature
    from multiple samples.

    Parameters
    ----------
    processed_data : dict
        Example: {"sample_A": dataframe_A, "sample_B": dataframe_B}
    target_temperature : float
        Target temperature in K.

    Returns
    -------
    pandas.DataFrame
        Table with one row per sample.
    """
    rows = []

    for sample_name, df in processed_data.items():
        row = get_nearest_temperature_row(df, target_temperature)

        rows.append(
            {
                'Sample': sample_name,
                'Temperature': row['Temperature'],
                'Seebeck': row['Seebeck'],
                'Conductivity': row['Conductivity'],
                'Power_Factor': row.get('Power_Factor', np.nan),
                'ZT': row.get('ZT', np.nan),
            }
        )

    return pd.DataFrame(rows)


def plot_conductivity_vs_seebeck(points_df, target_temperature, save_path=None):
    """
    Plot conductivity vs Seebeck at a selected temperature.

    This is not a full SPB fit. It is a comparison plot for seeing how
    samples move in the Seebeck-conductivity relationship.
    """
    required_columns = {'Sample', 'Seebeck', 'Conductivity'}
    missing_columns = required_columns - set(points_df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    fig, ax = plt.subplots(figsize=(6, 5))

    x = points_df['Seebeck'] * 1e6
    y = points_df['Conductivity']

    ax.scatter(x, y, s=70)

    for _, row in points_df.iterrows():
        ax.annotate(
            row['Sample'],
            (row['Seebeck'] * 1e6, row['Conductivity']),
            textcoords='offset points',
            xytext=(6, 4),
            fontsize=9,
        )

    ax.set_xlabel('Seebeck Coefficient (microV/K)')
    ax.set_ylabel('Electrical Conductivity (S/m)')
    ax.set_title(f'Conductivity vs Seebeck near {target_temperature:.0f} K')
    ax.grid(True, linestyle='--', alpha=0.4)

    if save_path:
        save_dir = os.path.dirname(save_path)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
        plt.savefig(save_path, dpi=300, bbox_inches='tight')

    return fig, ax

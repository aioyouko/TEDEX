import pandas as pd
import numpy as np
import os
import csv
from scipy.interpolate import interp1d

try:
    from src.tools.spb.lattice_cal import add_lattice_thermal_conductivity
    HAS_LATTICE_CALC = True
except ImportError:
    HAS_LATTICE_CALC = False


TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin1")


def _read_csv_with_fallback(file_path, **kwargs):
    errors = []
    for encoding in TEXT_ENCODINGS:
        try:
            return pd.read_csv(file_path, encoding=encoding, **kwargs)
        except UnicodeDecodeError as error:
            errors.append(f"{encoding}: {error}")

    raise UnicodeDecodeError(
        "text-fallback",
        b"",
        0,
        1,
        "; ".join(errors),
    )


def _read_text_with_fallback(file_path):
    errors = []
    with open(file_path, 'rb') as handle:
        data = handle.read()

    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError as error:
            errors.append(f"{encoding}: {error}")

    raise UnicodeDecodeError(
        "text-fallback",
        data,
        0,
        1,
        "; ".join(errors),
    )


def load_zem(file_path):
    """
    读取并清洗 ZEM 原始 txt 数据。
    """
    if not file_path or not os.path.exists(file_path):
        print(f"❌Cannot find ZEM file: {file_path}")
        return None

    try:
        # index [0, 1, 4, 5] refers to Temperature, Resistivity, Seebeck and Power_Factor for ZEM-3 output .txt
        target_cols = [0, 1, 4, 5]
        
        df = _read_csv_with_fallback(
            file_path, 
            sep='\t',       
            skiprows=2, 
            usecols=target_cols,
            header=None,
        )
        
        df.columns = ['Temperature', 'Resistivity', 'Seebeck', 'Power_Factor']
        
        # Temperature (K), Resistivity (Ohm m), Seebeck (V/K), Power_Factor (W/m/K2), Conductivity (S/m)
        df['Temperature'] =df['Temperature'] + 273.15
        df['Conductivity'] = 1 / df['Resistivity']
        
        print(f"✅Successfully exrract ZEM data from: {os.path.basename(file_path)}")
        return df

    except Exception as e:
        print(f"❌Fail to exrract ZEM data from: {os.path.basename(file_path)} ")
        return None

def _finalize_lfa_dataframe(df):
    df = df.iloc[:, :2].copy()
    df.columns = ['Temperature_LFA', 'Diffusivity']
    df['Temperature_LFA'] = pd.to_numeric(df['Temperature_LFA'], errors='coerce')
    df['Diffusivity'] = pd.to_numeric(df['Diffusivity'], errors='coerce')
    df = df.dropna(subset=['Temperature_LFA', 'Diffusivity']).reset_index(drop=True)

    if df.empty:
        raise ValueError("No numeric LFA temperature/diffusivity rows found")

    df['Temperature_LFA'] = df['Temperature_LFA'] + 273.15
    return df


def _load_lfa_mean_rows(file_path):
    text = _read_text_with_fallback(file_path)
    rows = []

    for row in csv.reader(text.splitlines()):
        if not row or row[0].strip() != '#Mean':
            continue
        if len(row) < 4:
            continue
        rows.append([row[1], row[3]])

    if not rows:
        raise ValueError("No #Mean rows found in instrument LFA export")

    return _finalize_lfa_dataframe(pd.DataFrame(rows))


def _has_lfa_mean_rows(file_path):
    with open(file_path, 'rb') as handle:
        return any(line.lstrip().startswith(b'#Mean,') for line in handle)


def load_lfa(file_path):
    """
    laod LFA data
    """
    if not file_path or not os.path.exists(file_path):
        print(f"❌Cannot find LFA file: {file_path}")
        return None

    errors = []

    if _has_lfa_mean_rows(file_path):
        try:
            # Netzsch/LFA report export: use the per-temperature #Mean rows.
            df = _load_lfa_mean_rows(file_path)

            print(f"✅Successfully extract LFA data: {os.path.basename(file_path)}")
            return df

        except Exception as e:
            errors.append(str(e))

    try:
        # Compact CSV format: two columns, temperature and diffusivity.
        df = _read_csv_with_fallback(file_path, usecols=[0, 1])
        df = _finalize_lfa_dataframe(df)
        
        print(f"✅Successfully extract LFA data: {os.path.basename(file_path)}")
        return df

    except Exception as e:
        errors.append(str(e))

    if not _has_lfa_mean_rows(file_path):
        try:
            # Fallback for instrument exports without a quick #Mean pre-detection.
            df = _load_lfa_mean_rows(file_path)

            print(f"✅Successfully extract LFA data: {os.path.basename(file_path)}")
            return df

        except Exception as e:
            errors.append(str(e))

    print(f"❌Failed to extract LFA data from: {file_path}. {'; '.join(errors)}")
    return None


def calculate_zt(zem_df, lfa_df, density, cp_value, calculate_lattice=True):
    """
    Combine cleaned ZEM/LFA data, calculate total thermal conductivity, ZT,
    and optional SPB-derived transport columns.
    """
    try:
        if zem_df is None or lfa_df is None:
            raise ValueError("ZEM and LFA dataframes are required")

        if density is None or cp_value is None:
            raise ValueError("density and cp_value are required")

        shared_len = min(len(zem_df), len(lfa_df))
        if shared_len == 0:
            raise ValueError("ZEM or LFA dataframe is empty")

        if len(zem_df) != len(lfa_df):
            print(f"⚠️ ZEM/LFA length mismatch; using first {shared_len} rows")

        aligned_diffusivity = lfa_df['Diffusivity'].values[:shared_len]
        full_df = zem_df.iloc[:shared_len].copy()

        full_df['Diffusivity'] = aligned_diffusivity

        full_df['Thermal_Conductivity'] = full_df['Diffusivity'] * density * cp_value

        full_df['ZT'] = (full_df['Power_Factor']) * full_df['Temperature'] / full_df['Thermal_Conductivity']

        if calculate_lattice:
            if HAS_LATTICE_CALC:
                try:
                    full_df = add_lattice_thermal_conductivity(full_df)
                    print("✅ SPB-derived transport columns calculated")
                except Exception as e:
                    print(f"⚠️ SPB-derived transport calculation skipped: {e}")
            else:
                print("⚠️ SPB-derived transport calculation skipped: module unavailable")

        print("✅ zT calculation finished")
        return full_df
        
    except Exception as e:
        print(f"❌ zT calculation failed: {e}")
        return zem_df

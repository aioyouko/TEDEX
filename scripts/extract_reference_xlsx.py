from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

try:
    from src.tools.spb.lattice_cal import (
        QUALITY_FACTOR_COLUMN,
        WEIGHTED_MOBILITY_COLUMN,
        calculate_generalized_fermi_level,
        calculate_lorenz_number,
        calculate_quality_factor,
        calculate_weighted_mobility,
    )

    HAS_SPB = True
except Exception:
    HAS_SPB = False
    WEIGHTED_MOBILITY_COLUMN = "Weighted_Mobility_cm2_V-1_s-1"
    QUALITY_FACTOR_COLUMN = "Quality_Factor_B"


STANDARD_COLUMNS = [
    "Temperature",
    "Resistivity",
    "Seebeck",
    "Power_Factor",
    "Conductivity",
    "Diffusivity",
    "Thermal_Conductivity",
    "ZT",
    "Generalized_Fermi_Level",
    "Lorenz_Number",
    "Lorenz_Number_1e-8_WOhmK-2",
    WEIGHTED_MOBILITY_COLUMN,
    "Carrier_Thermal_Conductivity",
    "Lattice_Thermal_Conductivity",
    QUALITY_FACTOR_COLUMN,
]

FEATURE_COLUMNS = [
    "sample_id",
    "reference_id",
    "Samples",
    "sample_name",
    "matrix_composition",
    "sample_composition",
    "optimization_type",
    "modifier_species",
    "modifier_element",
    "modifier_amount",
    "modifier_unit",
    "T_ZT_max(K)",
    "ZT_max",
    "T_S_max(K)",
    "S_max(V/K)",
    "T_C_max(K)",
    "C_max(S/m)",
    "T_K_min(K)",
    "K_min(W/(m*K))",
    "T_KL_min(K)",
    "KL_min(W/(m*K))",
    "T_Ke_max(K)",
    "Ke_max(W/(m*K))",
    "performance_file",
    "source_workbook",
    "notes",
]

HEADER_MAP = {
    "tk": ("Temperature", 1.0),
    "temperaturek": ("Temperature", 1.0),
    "temperature": ("Temperature", 1.0),
    "resistivitymohmcm": ("Resistivity", 1e-5),
    "resistivitymilliohmcm": ("Resistivity", 1e-5),
    "resistivityohmm": ("Resistivity", 1.0),
    "conductivityscm": ("Conductivity", 100.0),
    "conductivitysm": ("Conductivity", 1.0),
    "electricalconductivityscm": ("Conductivity", 100.0),
    "electricalconductivitysm": ("Conductivity", 1.0),
    "seebeckuvk": ("Seebeck", 1e-6),
    "seebeckvk": ("Seebeck", 1.0),
    "seebeckcoefficientuvk": ("Seebeck", 1e-6),
    "seebeckcoefficientvk": ("Seebeck", 1.0),
    "pfuwcmk2": ("Power_Factor", 1e-4),
    "powerfactoruwcmk2": ("Power_Factor", 1e-4),
    "powerfactorwmk2": ("Power_Factor", 1.0),
    "thermalconductivitywmk": ("Thermal_Conductivity", 1.0),
    "thermalconductivitywm1k1": ("Thermal_Conductivity", 1.0),
    "zt": ("ZT", 1.0),
}

METADATA_FIELDS = [
    "sample_id",
    "reference_id",
    "sample_name",
    "matrix_composition",
    "pristine_composition",
    "sample_composition",
    "optimization_type",
    "modifier_species",
    "modifier_element",
    "modifier_elements",
    "modifier_amount",
    "modifier_unit",
    "modifier_site",
    "phase_type",
    "synthesis_route",
    "annealing_condition",
    "performance_file",
    "performance_source",
    "source_workbook",
    "notes",
]


def resolve_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return WORKSPACE / path


def relative_path(path: str | Path) -> str:
    path = Path(path)
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve()))
    except ValueError:
        return str(path)


def clean_header(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).lower()
    text = text.replace("μ", "u")
    return re.sub(r"[^a-z0-9]+", "", text)


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip() == ""


def as_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    if math.isnan(number) or math.isinf(number):
        return np.nan
    return number


def is_amount_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", token.strip()))


def parse_amount(token: str) -> float | None:
    token = token.strip()
    if not token:
        return None
    if "." in token:
        return float(token)
    if not token.isdigit():
        return None
    if len(token) == 1:
        return int(token) / 10
    if len(token) == 2:
        return int(token) / 10
    return int(token) / 100


def formula_elements(formula: str) -> list[str]:
    seen = []
    for element in re.findall(r"[A-Z][a-z]?", formula):
        if element not in seen:
            seen.append(element)
    return seen


def split_modifier_part(part: str) -> tuple[str, float | None]:
    part = part.strip()
    leading = re.fullmatch(r"(\d+(?:\.\d+)?)([A-Z].*)", part)
    if leading:
        return leading.group(2), parse_amount(leading.group(1))

    trailing_decimal = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*?)(\d+\.\d+)", part)
    if trailing_decimal:
        return trailing_decimal.group(1), parse_amount(trailing_decimal.group(2))

    return part, None


def parse_modifiers(sample_name: str, matrix: str) -> list[dict[str, Any]]:
    remainder = sample_name
    if remainder == matrix:
        return []
    if remainder.startswith(f"{matrix}-"):
        remainder = remainder[len(matrix) + 1 :]

    parts = [part for part in remainder.split("-") if part]
    modifiers: list[dict[str, Any]] = []
    pending_species: str | None = None

    for part in parts:
        if is_amount_token(part) and pending_species:
            modifiers.append(
                {
                    "species": pending_species,
                    "amount": parse_amount(part),
                    "elements": formula_elements(pending_species),
                }
            )
            pending_species = None
            continue

        species, amount = split_modifier_part(part)
        if amount is None:
            if pending_species:
                modifiers.append(
                    {
                        "species": pending_species,
                        "amount": None,
                        "elements": formula_elements(pending_species),
                    }
                )
            pending_species = species
        else:
            if pending_species:
                modifiers.append(
                    {
                        "species": pending_species,
                        "amount": None,
                        "elements": formula_elements(pending_species),
                    }
                )
                pending_species = None
            modifiers.append(
                {
                    "species": species,
                    "amount": amount,
                    "elements": formula_elements(species),
                }
            )

    if pending_species:
        modifiers.append(
            {
                "species": pending_species,
                "amount": None,
                "elements": formula_elements(pending_species),
            }
        )

    return modifiers


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return slug or "sample"


def build_sample_metadata(
    sample_name: str,
    reference_id: str,
    matrix: str,
    performance_file: Path,
    workbook: Path,
) -> dict[str, Any]:
    modifiers = parse_modifiers(sample_name, matrix)
    modifier_elements: list[str] = []
    for modifier in modifiers:
        for element in modifier["elements"]:
            if element not in modifier_elements:
                modifier_elements.append(element)

    modifier_species = "; ".join(
        f"{modifier['amount']:g} {modifier['species']}"
        if modifier["amount"] is not None
        else modifier["species"]
        for modifier in modifiers
    )

    if not modifiers:
        optimization_type = "pristine"
    elif len(modifiers) == 1:
        optimization_type = "alloy"
    else:
        optimization_type = "composite"

    return {
        "sample_id": f"{reference_id}-{slugify(sample_name)}",
        "reference_id": reference_id,
        "sample_name": sample_name,
        "matrix_composition": matrix,
        "pristine_composition": matrix,
        "sample_composition": sample_name,
        "optimization_type": optimization_type,
        "modifier_species": modifier_species,
        "modifier_element": modifier_elements[0] if modifier_elements else "",
        "modifier_elements": modifier_elements,
        "modifier_amount": modifiers[0]["amount"] if len(modifiers) == 1 else None,
        "modifier_unit": "nominal_fraction_from_sample_name" if modifiers else "",
        "modifier_site": "",
        "phase_type": "",
        "synthesis_route": "",
        "annealing_condition": "",
        "performance_file": relative_path(performance_file),
        "performance_source": "reference_xlsx_table",
        "source_workbook": relative_path(workbook),
        "notes": "Parsed from sample name; verify composition metadata before publication use.",
    }


def row_has_temperature_header(row: pd.Series) -> bool:
    return any(clean_header(value) in {"tk", "temperature", "temperaturek"} for value in row)


def parse_header_row(row: pd.Series) -> list[tuple[int, str, float]]:
    mappings: list[tuple[int, str, float]] = []
    for col_idx, value in row.items():
        header_key = clean_header(value)
        if header_key in HEADER_MAP:
            target, scale = HEADER_MAP[header_key]
            mappings.append((int(col_idx), target, scale))
    return mappings


def parse_workbook_blocks(workbook: Path, sheet_name: str | None = None) -> list[tuple[str, pd.DataFrame]]:
    excel = pd.ExcelFile(workbook)
    selected_sheet = sheet_name or excel.sheet_names[0]
    raw = pd.read_excel(workbook, sheet_name=selected_sheet, header=None)

    blocks: list[tuple[str, pd.DataFrame]] = []
    i = 0
    while i < len(raw) - 1:
        first_cell = raw.iat[i, 0]
        if isinstance(first_cell, str) and first_cell.strip() and row_has_temperature_header(raw.iloc[i + 1]):
            sample_name = first_cell.strip()
            mappings = parse_header_row(raw.iloc[i + 1])
            data_rows: list[dict[str, float]] = []
            j = i + 2
            while j < len(raw):
                row = raw.iloc[j]
                if row.dropna(how="all").empty:
                    break
                if isinstance(row.iat[0], str) and row.iat[0].strip():
                    break

                parsed_row: dict[str, float] = {}
                for col_idx, target, scale in mappings:
                    value = as_float(row.iat[col_idx])
                    parsed_row[target] = value * scale if not np.isnan(value) else np.nan

                if not parsed_row or np.isnan(parsed_row.get("Temperature", np.nan)):
                    break
                data_rows.append(parsed_row)
                j += 1

            if data_rows:
                blocks.append((sample_name, pd.DataFrame(data_rows)))
            i = max(j, i + 1)
        else:
            i += 1

    return blocks


def add_derived_columns(df: pd.DataFrame, calculate_lattice: bool = True) -> pd.DataFrame:
    out = df.copy()
    for column in STANDARD_COLUMNS:
        if column not in out.columns:
            out[column] = np.nan

    invalid_k = out["Thermal_Conductivity"].notna() & (out["Thermal_Conductivity"] <= 0)
    out.loc[invalid_k, "Thermal_Conductivity"] = np.nan

    missing_conductivity = out["Conductivity"].isna() & out["Resistivity"].notna() & (out["Resistivity"] != 0)
    out.loc[missing_conductivity, "Conductivity"] = 1 / out.loc[missing_conductivity, "Resistivity"]

    missing_resistivity = out["Resistivity"].isna() & out["Conductivity"].notna() & (out["Conductivity"] != 0)
    out.loc[missing_resistivity, "Resistivity"] = 1 / out.loc[missing_resistivity, "Conductivity"]

    missing_pf = out["Power_Factor"].isna() & out["Seebeck"].notna() & out["Conductivity"].notna()
    out.loc[missing_pf, "Power_Factor"] = (
        out.loc[missing_pf, "Seebeck"] ** 2 * out.loc[missing_pf, "Conductivity"]
    )

    missing_zt = (
        out["ZT"].isna()
        & out["Power_Factor"].notna()
        & out["Temperature"].notna()
        & out["Thermal_Conductivity"].notna()
        & (out["Thermal_Conductivity"] != 0)
    )
    out.loc[missing_zt, "ZT"] = (
        out.loc[missing_zt, "Power_Factor"]
        * out.loc[missing_zt, "Temperature"]
        / out.loc[missing_zt, "Thermal_Conductivity"]
    )

    if calculate_lattice and HAS_SPB:
        for idx, row in out.iterrows():
            required = [
                row["Seebeck"],
                row["Conductivity"],
                row["Temperature"],
                row["Thermal_Conductivity"],
            ]
            if any(pd.isna(value) for value in required):
                continue
            try:
                eta = calculate_generalized_fermi_level(row["Seebeck"])
                lorenz = calculate_lorenz_number(eta)
                weighted_mobility = calculate_weighted_mobility(
                    row["Conductivity"],
                    row["Temperature"],
                    eta,
                )
                carrier_k = lorenz * row["Conductivity"] * row["Temperature"]
                lattice_k = row["Thermal_Conductivity"] - carrier_k
                out.at[idx, "Generalized_Fermi_Level"] = eta
                out.at[idx, "Lorenz_Number"] = lorenz
                out.at[idx, "Lorenz_Number_1e-8_WOhmK-2"] = lorenz * 1e8
                out.at[idx, WEIGHTED_MOBILITY_COLUMN] = weighted_mobility
                out.at[idx, "Carrier_Thermal_Conductivity"] = carrier_k
                out.at[idx, "Lattice_Thermal_Conductivity"] = lattice_k
                out.at[idx, QUALITY_FACTOR_COLUMN] = calculate_quality_factor(
                    weighted_mobility,
                    lattice_k,
                )
            except Exception:
                continue

    return out[STANDARD_COLUMNS]


def json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_clean(item) for item in value]
    if pd.isna(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def series_index(series: pd.Series, mode: str) -> Any:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    if mode == "absmax":
        return values.abs().idxmax()
    if mode == "max":
        return values.idxmax()
    if mode == "min":
        return values.idxmin()
    raise ValueError(f"Unknown mode: {mode}")


def rounded_temperature(df: pd.DataFrame, idx: Any) -> float | None:
    if idx is None:
        return None
    value = as_float(df.loc[idx, "Temperature"])
    if np.isnan(value):
        return None
    return round(value, 2)


def value_at(df: pd.DataFrame, idx: Any, column: str) -> float | None:
    if idx is None or column not in df.columns:
        return None
    value = as_float(df.loc[idx, column])
    if np.isnan(value):
        return None
    return value


def extract_features(sample_name: str, df: pd.DataFrame, metadata: dict[str, Any]) -> dict[str, Any]:
    idx_s = series_index(df["Seebeck"], "absmax")
    idx_c = series_index(df["Conductivity"], "max")
    idx_k = series_index(df["Thermal_Conductivity"], "min")
    idx_zt = series_index(df["ZT"], "max")
    idx_kl = series_index(df["Lattice_Thermal_Conductivity"], "min")
    idx_ke = series_index(df["Carrier_Thermal_Conductivity"], "max")

    features = {
        "Samples": sample_name,
        "T_S_max(K)": rounded_temperature(df, idx_s),
        "S_max(V/K)": value_at(df, idx_s, "Seebeck"),
        "T_C_max(K)": rounded_temperature(df, idx_c),
        "C_max(S/m)": value_at(df, idx_c, "Conductivity"),
        "T_K_min(K)": rounded_temperature(df, idx_k),
        "K_min(W/(m*K))": value_at(df, idx_k, "Thermal_Conductivity"),
        "T_ZT_max(K)": rounded_temperature(df, idx_zt),
        "ZT_max": value_at(df, idx_zt, "ZT"),
        "T_KL_min(K)": rounded_temperature(df, idx_kl),
        "KL_min(W/(m*K))": value_at(df, idx_kl, "Lattice_Thermal_Conductivity"),
        "T_Ke_max(K)": rounded_temperature(df, idx_ke),
        "Ke_max(W/(m*K))": value_at(df, idx_ke, "Carrier_Thermal_Conductivity"),
    }
    features.update({key: metadata.get(key) for key in METADATA_FIELDS if key in metadata})
    return json_clean(features)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(json_clean(payload), handle, indent=2, ensure_ascii=False)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def merge_reference_samples(samples_path: Path, generated_samples: list[dict[str, Any]]) -> None:
    existing = read_json(samples_path, [])
    if not isinstance(existing, list):
        existing = []

    by_id: dict[str, dict[str, Any]] = {
        item.get("sample_id"): item for item in existing if isinstance(item, dict) and item.get("sample_id")
    }

    for generated in generated_samples:
        current = by_id.get(generated["sample_id"], {}).copy()
        for key, value in generated.items():
            if value not in ("", None, []):
                current[key] = value
            elif key not in current:
                current[key] = value
        by_id[generated["sample_id"]] = current

    ordered = sorted(by_id.values(), key=lambda item: (item.get("reference_id", ""), item.get("sample_id", "")))
    write_json(samples_path, ordered)


def markdown_table(records: list[dict[str, Any]], columns: list[str]) -> str:
    def fmt(value: Any) -> str:
        if value is None or value == "":
            return ""
        if isinstance(value, float):
            return f"{value:.6g}"
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = []
    for record in records:
        rows.append("| " + " | ".join(fmt(record.get(column)) for column in columns) + " |")
    return "\n".join([header, separator, *rows])


def write_feature_exports(
    features_dir: Path,
    reference_id: str,
    workbook: Path,
    features_list: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, str]:
    features_dir.mkdir(parents=True, exist_ok=True)

    features_json = features_dir / "extracted_features.json"
    sample_features_json = features_dir / "sample_features.json"
    sample_features_csv = features_dir / "sample_features.csv"
    sample_features_md = features_dir / "sample_features.md"
    sample_features_txt = features_dir / "sample_features.txt"
    manifest_json = features_dir / "manifest.json"

    feature_payload = {
        "batch_name": reference_id,
        "reference_id": reference_id,
        "source_type": "reference_xlsx",
        "source_workbook": relative_path(workbook),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "samples_data": features_list,
    }

    write_json(features_json, feature_payload)
    write_json(sample_features_json, features_list)
    write_json(manifest_json, manifest)

    feature_frame = pd.DataFrame(features_list)
    csv_frame = feature_frame.copy()
    for column in csv_frame.columns:
        csv_frame[column] = csv_frame[column].map(
            lambda value: json.dumps(value, ensure_ascii=False)
            if isinstance(value, (list, dict))
            else value
        )
    csv_columns = [column for column in FEATURE_COLUMNS if column in csv_frame.columns]
    csv_columns.extend(column for column in csv_frame.columns if column not in csv_columns)
    csv_frame.to_csv(sample_features_csv, index=False, columns=csv_columns)

    summary_columns = [
        "sample_name",
        "optimization_type",
        "modifier_species",
        "modifier_amount",
        "T_ZT_max(K)",
        "ZT_max",
        "K_min(W/(m*K))",
        "KL_min(W/(m*K))",
    ]
    top = sorted(
        features_list,
        key=lambda item: item.get("ZT_max") if item.get("ZT_max") is not None else -math.inf,
        reverse=True,
    )[:8]

    md_lines = [
        f"# {reference_id} Reference Features",
        "",
        f"- Source workbook: `{relative_path(workbook)}`",
        f"- Samples extracted: {len(features_list)}",
        "- Units match processed lab CSV style: K, V/K, S/m, W/m/K, W/m/K2.",
        "",
        "## Top Samples By ZT",
        "",
        markdown_table(top, summary_columns),
        "",
        "## All Samples",
        "",
        markdown_table(features_list, summary_columns),
        "",
    ]
    sample_features_md.write_text("\n".join(md_lines), encoding="utf-8")

    txt_lines = [
        f"{reference_id} reference features",
        f"Source workbook: {relative_path(workbook)}",
        f"Samples extracted: {len(features_list)}",
        "",
        "Top samples by ZT:",
    ]
    for record in top:
        txt_lines.append(
            f"- {record.get('sample_name')}: ZT_max={record.get('ZT_max')} "
            f"at {record.get('T_ZT_max(K)')} K; modifier={record.get('modifier_species') or 'pristine'}"
        )
    sample_features_txt.write_text("\n".join(txt_lines) + "\n", encoding="utf-8")

    return {
        "features_json": relative_path(features_json),
        "sample_features_json": relative_path(sample_features_json),
        "sample_features_csv": relative_path(sample_features_csv),
        "sample_features_md": relative_path(sample_features_md),
        "sample_features_txt": relative_path(sample_features_txt),
        "manifest_json": relative_path(manifest_json),
    }


def extract_reference_workbook(args: argparse.Namespace) -> dict[str, Any]:
    workbook = resolve_path(args.workbook)
    if not workbook.exists():
        raise FileNotFoundError(f"Workbook not found: {workbook}")

    reference_id = args.reference_id or workbook.stem
    matrix = args.matrix_composition or args.material_family or reference_id
    processed_dir = resolve_path(args.processed_root) / reference_id
    features_dir = resolve_path(args.features_root) / reference_id
    samples_path = resolve_path(args.samples_json)

    blocks = parse_workbook_blocks(workbook, sheet_name=args.sheet)
    if not blocks:
        raise ValueError(f"No sample blocks found in {workbook}")

    processed_files = []
    features_list = []
    sample_records = []
    warnings = []

    if args.no_lattice:
        warnings.append("SPB/Lorenz/lattice calculation disabled by --no-lattice.")
    elif not HAS_SPB:
        warnings.append("SPB/Lorenz/lattice calculation unavailable; columns were left blank.")

    processed_dir.mkdir(parents=True, exist_ok=True)
    for sample_name, raw_df in blocks:
        slug = slugify(sample_name)
        csv_path = processed_dir / f"{slug}.csv"
        metadata = build_sample_metadata(sample_name, reference_id, matrix, csv_path, workbook)
        processed_df = add_derived_columns(raw_df, calculate_lattice=not args.no_lattice)
        processed_df.to_csv(csv_path, index=False)

        processed_files.append(relative_path(csv_path))
        sample_records.append(metadata)
        features_list.append(extract_features(sample_name, processed_df, metadata))

    merge_reference_samples(samples_path, sample_records)

    manifest = {
        "reference_id": reference_id,
        "source_workbook": relative_path(workbook),
        "sheet": args.sheet,
        "sample_count": len(blocks),
        "processed_dir": relative_path(processed_dir),
        "features_dir": relative_path(features_dir),
        "samples_json": relative_path(samples_path),
        "processed_files": processed_files,
        "standard_columns": STANDARD_COLUMNS,
        "unit_conversions": {
            "resistivity(mohm cm)": "Resistivity = value * 1e-5 Ohm m",
            "conductivity(S/cm)": "Conductivity = value * 100 S/m",
            "seebeck(uV/K)": "Seebeck = value * 1e-6 V/K",
            "PF(uW/cm K2)": "Power_Factor = value * 1e-4 W/m/K^2",
            "thermal conductivity(W/mk)": "Thermal_Conductivity kept as W/m/K",
            "ZT": "dimensionless",
        },
        "warnings": warnings,
    }
    export_paths = write_feature_exports(features_dir, reference_id, workbook, features_list, manifest)
    manifest["feature_exports"] = export_paths
    write_json(features_dir / "manifest.json", manifest)

    return {
        "reference_id": reference_id,
        "sample_count": len(blocks),
        "processed_dir": relative_path(processed_dir),
        "features_dir": relative_path(features_dir),
        "samples_json": relative_path(samples_path),
        "feature_exports": export_paths,
        "warnings": warnings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract stacked reference TE data from an Excel workbook into project-style CSV/JSON/MD/TXT files."
    )
    parser.add_argument("workbook", nargs="?", default="data/reference/GeSe.xlsx")
    parser.add_argument("--sheet", default=None, help="Worksheet name. Defaults to the first sheet.")
    parser.add_argument("--reference-id", default=None, help="Reference dataset id. Defaults to workbook stem.")
    parser.add_argument("--material-family", default=None, help="Material family/matrix fallback.")
    parser.add_argument("--matrix-composition", default=None, help="Matrix composition, e.g. GeSe.")
    parser.add_argument("--processed-root", default="data/reference/processed")
    parser.add_argument("--features-root", default="data/reference/features")
    parser.add_argument("--samples-json", default="data/reference/samples.json")
    parser.add_argument("--no-lattice", action="store_true", help="Skip SPB Lorenz and lattice thermal columns.")
    return parser.parse_args()


def main() -> None:
    summary = extract_reference_workbook(parse_args())
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

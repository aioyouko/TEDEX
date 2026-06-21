import json
import os
from pathlib import Path

_MPL_CACHE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "te_matplotlib_cache"
_MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(_MPL_CACHE_DIR))

import pandas as pd

from src.tools.file_utils import setup_batch_directories

try:
    from src.tools.te_data import calculate_zt, load_lfa, load_zem

    HAS_PARSER = True
except ImportError:
    HAS_PARSER = False
    print("TE data parser module is not available.")

try:
    from src.tools.plot import plot_combined_figure

    HAS_PLOTTER = True
except ImportError:
    HAS_PLOTTER = False
    print("TE plotting module is not available.")

try:
    from src.tools.SPB.lattice_cal import (
        OUTPUT_COLUMNS as SPB_OUTPUT_COLUMNS,
        QUALITY_FACTOR_COLUMN,
        WEIGHTED_MOBILITY_COLUMN,
        calculate_lattice_for_dataframes,
    )

    HAS_LATTICE_CALC = True
except ImportError:
    HAS_LATTICE_CALC = False
    SPB_OUTPUT_COLUMNS = []
    WEIGHTED_MOBILITY_COLUMN = "Weighted_Mobility_cm2_V-1_s-1"
    QUALITY_FACTOR_COLUMN = "Quality_Factor_B"
    print("Lattice thermal conductivity module is not available.")


MATERIAL_METADATA_FIELDS = [
    "sample_id",
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
    "notes",
]


def get_sample_records(sample_files: dict):
    """Return sample entries from one batch config, ignoring batch metadata."""
    return {
        sample_name: paths
        for sample_name, paths in sample_files.items()
        if isinstance(paths, dict) and paths.get("zem") and paths.get("lfa")
    }


def get_sample_metadata(sample_files: dict):
    """Merge batch-level material metadata into each sample metadata record."""
    batch_metadata = sample_files.get("batch_metadata", {})
    sample_metadata = {}

    for sample_name, paths in get_sample_records(sample_files).items():
        merged = {
            key: value
            for key, value in batch_metadata.items()
            if key in MATERIAL_METADATA_FIELDS
        }
        merged.update(
            {
                key: value
                for key, value in paths.items()
                if key in MATERIAL_METADATA_FIELDS
            }
        )
        sample_metadata[sample_name] = merged

    return sample_metadata


def infer_raw_sample_suffix(sample_id: str, batch_id: str):
    """Return A/B/C-style suffix from a full sample id when possible."""
    prefix = f"{batch_id}-"
    if sample_id and sample_id.startswith(prefix):
        return sample_id[len(prefix) :]
    return sample_id


def normalize_match_text(value):
    """Normalize user selectors and sample aliases for case-insensitive matching."""
    return str(value or "").strip().replace("Batch-", "CHY-", 1).lower()


def expand_selector_aliases(selector):
    """Return common aliases for a batch/sample selector."""
    raw = str(selector or "").strip()
    aliases = {raw, raw.replace("Batch-", "CHY-", 1)}
    if raw and raw[0].isdigit():
        aliases.add(f"CHY-{raw}")
    return {normalize_match_text(alias) for alias in aliases if alias}


def sample_matches_selector(batch_id: str, sample_name: str, sample_info: dict, selector: str):
    """Return True when a selector identifies one sample in a batch ledger."""
    sample_id = sample_info.get("sample_id", "")
    display_name = sample_info.get("sample_name", sample_name)
    raw_suffix = infer_raw_sample_suffix(sample_id, batch_id) if sample_id else sample_name
    sample_composition = sample_info.get("sample_composition", "")

    candidates = {
        sample_id,
        sample_name,
        display_name,
        raw_suffix,
        f"{batch_id}-{raw_suffix}",
        f"{batch_id}-{sample_name}",
        f"{batch_id}-{display_name}",
        f"{batch_id}/{sample_name}",
        f"{batch_id}:{sample_name}",
        f"{batch_id}/{display_name}",
        f"{batch_id}:{display_name}",
    }
    if sample_composition:
        candidates.update(
            {
                sample_composition,
                f"{batch_id}-{sample_composition}",
                f"{batch_id}/{sample_composition}",
                f"{batch_id}:{sample_composition}",
            }
        )

    normalized_candidates = {
        normalize_match_text(candidate) for candidate in candidates if candidate
    }
    return bool(normalized_candidates & expand_selector_aliases(selector))


def filter_sample_files(
    batch_id: str,
    sample_files: dict,
    sample_selectors=None,
    strict: bool = False,
):
    """Limit a batch ledger to the requested sample selectors."""
    selectors = [selector for selector in sample_selectors or [] if str(selector).strip()]
    if not selectors:
        return sample_files

    filtered = {"batch_metadata": sample_files.get("batch_metadata", {})}
    unmatched = []

    for selector in selectors:
        matches = []
        for sample_name, sample_info in sample_files.items():
            if sample_name == "batch_metadata" or not isinstance(sample_info, dict):
                continue
            if sample_matches_selector(batch_id, sample_name, sample_info, selector):
                matches.append((sample_name, sample_info))

        if not matches:
            unmatched.append(str(selector))
            continue

        for sample_name, sample_info in matches:
            filtered[sample_name] = sample_info

    if unmatched:
        message = (
            f"No sample matched in {batch_id}: {', '.join(unmatched)}. "
            "Try a full id such as CHY-1054-B, a suffix such as B, "
            "or a sample_name from data/lab/samples.json."
        )
        if strict:
            raise ValueError(message)
        print(f"Warning: {message}")

    selected_names = [name for name in filtered if name != "batch_metadata"]
    if selected_names:
        print(f"Selected samples for {batch_id}: {', '.join(selected_names)}")
    else:
        print(f"No samples selected for {batch_id}.")

    return filtered


def process_batch_raw_data(batch_id: str, sample_files: dict, processed_path: str):
    """
    Load raw ZEM/LFA files, calculate transport properties, and save one
    processed CSV per sample.
    """
    processed_data = {}
    processed_files = {}

    if not HAS_PARSER:
        print("Step 1 skipped: TE parser is not available.")
        return processed_data, processed_files

    print("Step 1: Process raw TE data.")

    for sample_name, paths in get_sample_records(sample_files).items():
        sample_id = paths.get("sample_id") or f"{batch_id}-{sample_name}"
        zem_path = paths.get("zem")
        lfa_path = paths.get("lfa")
        density_val = paths.get("density")
        cp_val = paths.get("cp_value", 0.3)

        if density_val is None or cp_val is None:
            print(
                f"Skipping {sample_name}: density or cp_value is missing. "
                "Fill these values in data/lab/lab_metadata.md or data/lab/samples.json."
            )
            continue

        zem_data = load_zem(zem_path)
        lfa_data = load_lfa(lfa_path)

        if zem_data is None or lfa_data is None:
            print(f"Skipping {sample_name}: raw ZEM or LFA data could not be loaded.")
            continue

        zt_data = calculate_zt(
            zem_data,
            lfa_data,
            density=density_val,
            cp_value=cp_val,
        )
        processed_data[sample_name] = zt_data

        save_path = os.path.join(processed_path, f"{sample_id}.csv")
        zt_data.to_csv(save_path, index=False)
        processed_files[sample_name] = save_path

        print(f"Saved processed data: {save_path}")
        print(f"Preview for {sample_id} ({sample_name}):")
        print(zt_data.head())
        print("-" * 50)

    return processed_data, processed_files


def run_spb_fitting(processed_data: dict, processed_files: dict = None):
    """
    Run the currently available SPB-derived transport-column calculation.
    """
    if not processed_data:
        print("Step 2 skipped: no processed data is available.")
        return {}

    if not HAS_LATTICE_CALC:
        print("Step 2 skipped: lattice thermal conductivity module is not available.")
        return {}

    has_spb_columns = all(
        set(SPB_OUTPUT_COLUMNS).issubset(df.columns)
        for df in processed_data.values()
    )

    if has_spb_columns:
        print("Step 2: SPB-derived columns already exist.")
    else:
        print("Step 2: Calculate SPB-derived transport columns.")
        updated_data = calculate_lattice_for_dataframes(processed_data)
        processed_data.clear()
        processed_data.update(updated_data)

    if processed_files:
        for sample_name, df in processed_data.items():
            save_path = processed_files.get(sample_name)
            if save_path:
                df.to_csv(save_path, index=False)
                print(f"Saved SPB-derived columns: {save_path}")

    spb_results = {}
    for sample_name, df in processed_data.items():
        if "Lorenz_Number_1e-8_WOhmK-2" not in df.columns:
            continue
        spb_results[sample_name] = {
            "Lorenz_Number_1e-8_WOhmK-2_mean": df[
                "Lorenz_Number_1e-8_WOhmK-2"
            ].mean(),
            "Carrier_Thermal_Conductivity_mean": df[
                "Carrier_Thermal_Conductivity"
            ].mean(),
            "Lattice_Thermal_Conductivity_min": df[
                "Lattice_Thermal_Conductivity"
            ].min(),
        }
        if WEIGHTED_MOBILITY_COLUMN in df.columns:
            spb_results[sample_name][f"{WEIGHTED_MOBILITY_COLUMN}_mean"] = df[
                WEIGHTED_MOBILITY_COLUMN
            ].mean()
        if QUALITY_FACTOR_COLUMN in df.columns:
            spb_results[sample_name][f"{QUALITY_FACTOR_COLUMN}_max"] = df[
                QUALITY_FACTOR_COLUMN
            ].max()

    return spb_results


def extract_sample_transport_features(
    sample_name: str,
    transport_df: pd.DataFrame,
    spb_result: dict = None,
    sample_metadata: dict = None,
):
    """
    Extract compact sample-level features from calculated transport data.
    """
    required_columns = {
        "Temperature",
        "Seebeck",
        "Conductivity",
        "Thermal_Conductivity",
        "ZT",
    }
    missing_columns = required_columns - set(transport_df.columns)
    if missing_columns:
        print(
            f"Feature extraction failed for {sample_name}: missing columns "
            f"{sorted(missing_columns)}."
        )
        return None

    col_t = "Temperature"
    col_s = "Seebeck"
    col_c = "Conductivity"
    col_k = "Thermal_Conductivity"
    col_zt = "ZT"

    idx_s_max = transport_df[col_s].abs().idxmax()
    idx_c_max = transport_df[col_c].idxmax()
    idx_k_min = transport_df[col_k].idxmin()
    idx_zt_max = transport_df[col_zt].idxmax()

    features = {
        "Samples": sample_name,
        "T_S_max(K)": round(transport_df.loc[idx_s_max, col_t], 2),
        "S_max(V/K)": transport_df.loc[idx_s_max, col_s],
        "T_C_max(K)": round(transport_df.loc[idx_c_max, col_t], 2),
        "C_max(S/m)": transport_df.loc[idx_c_max, col_c],
        "T_K_min(K)": round(transport_df.loc[idx_k_min, col_t], 2),
        "K_min(W/(m*K))": transport_df.loc[idx_k_min, col_k],
        "T_ZT_max(K)": round(transport_df.loc[idx_zt_max, col_t], 2),
        "ZT_max": transport_df.loc[idx_zt_max, col_zt],
    }

    if sample_metadata:
        features.update(
            {
                key: value
                for key, value in sample_metadata.items()
                if key in MATERIAL_METADATA_FIELDS and value not in ("", None, [])
            }
        )

    if "Lattice_Thermal_Conductivity" in transport_df.columns:
        col_kl = "Lattice_Thermal_Conductivity"
        idx_kl_min = transport_df[col_kl].idxmin()
        features.update(
            {
                "T_KL_min(K)": round(transport_df.loc[idx_kl_min, col_t], 2),
                "KL_min(W/(m*K))": transport_df.loc[idx_kl_min, col_kl],
            }
        )

    if "Carrier_Thermal_Conductivity" in transport_df.columns:
        col_ke = "Carrier_Thermal_Conductivity"
        idx_ke_max = transport_df[col_ke].idxmax()
        features.update(
            {
                "T_Ke_max(K)": round(transport_df.loc[idx_ke_max, col_t], 2),
                "Ke_max(W/(m*K))": transport_df.loc[idx_ke_max, col_ke],
            }
        )

    if WEIGHTED_MOBILITY_COLUMN in transport_df.columns:
        weighted_mobility = pd.to_numeric(
            transport_df[WEIGHTED_MOBILITY_COLUMN],
            errors="coerce",
        ).dropna()
        if not weighted_mobility.empty:
            idx_mu_max = weighted_mobility.idxmax()
            features.update(
                {
                    "T_weighted_mobility_max(K)": round(
                        transport_df.loc[idx_mu_max, col_t],
                        2,
                    ),
                    f"{WEIGHTED_MOBILITY_COLUMN}_max": transport_df.loc[
                        idx_mu_max,
                        WEIGHTED_MOBILITY_COLUMN,
                    ],
                }
            )

    if QUALITY_FACTOR_COLUMN in transport_df.columns:
        quality_factor = pd.to_numeric(
            transport_df[QUALITY_FACTOR_COLUMN],
            errors="coerce",
        ).dropna()
        if not quality_factor.empty:
            idx_b_max = quality_factor.idxmax()
            features.update(
                {
                    "T_quality_factor_max(K)": round(
                        transport_df.loc[idx_b_max, col_t],
                        2,
                    ),
                    f"{QUALITY_FACTOR_COLUMN}_max": transport_df.loc[
                        idx_b_max,
                        QUALITY_FACTOR_COLUMN,
                    ],
                }
            )

    if spb_result:
        features["SPB"] = spb_result

    return features


def extract_and_save_features(
    batch_id: str,
    processed_data: dict,
    spb_results: dict,
    processed_path: str,
    sample_metadata: dict = None,
    merge_existing: bool = False,
):
    """
    Build and save compact feature JSON from processed transport data.
    """
    features_list = []

    for sample_name, transport_df in processed_data.items():
        sample_features = extract_sample_transport_features(
            sample_name,
            transport_df,
            spb_results.get(sample_name, {}),
            (sample_metadata or {}).get(sample_name, {}),
        )
        if sample_features:
            features_list.append(sample_features)

    json_path = os.path.join(processed_path, "extracted_features.json")
    if merge_existing and os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as handle:
                existing_features = json.load(handle)
        except (json.JSONDecodeError, OSError):
            existing_features = {}

        merged_features = {}
        for record in existing_features.get("samples_data", []):
            key = record.get("sample_id") or record.get("Samples")
            if key:
                merged_features[key] = record

        for record in features_list:
            key = record.get("sample_id") or record.get("Samples")
            if key:
                merged_features[key] = record

        features_list = list(merged_features.values())

    features_dict = {
        "batch_name": batch_id,
        "samples_data": features_list,
    }

    if features_list:
        feature_df = pd.DataFrame(features_list)
        print("Step 3: Extracted batch feature summary.")
        print(feature_df.to_string(index=False))
    else:
        print("Step 3: No sample features were extracted.")

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(features_dict, handle, indent=4, ensure_ascii=False)

    print(f"Saved feature JSON: {json_path}")
    return features_dict


def get_plot_stem(batch_id: str, processed_files: dict, sample_selectors=None):
    """Choose a non-destructive plot stem for batch or selected-sample runs."""
    if not sample_selectors:
        return batch_id
    if len(processed_files) == 1:
        first_path = next(iter(processed_files.values()))
        return Path(first_path).stem
    return f"{batch_id}_selected"


def plot_batch_transport(batch_id: str, processed_files: dict, sample_selectors=None):
    """
    Plot the processed CSV files for the batch if plotting is available.
    """
    if not HAS_PLOTTER:
        print("Step 4 skipped: plotter is not available.")
        return None

    if not processed_files:
        print("Step 4 skipped: no processed files are available.")
        return None

    plot_stem = get_plot_stem(batch_id, processed_files, sample_selectors)
    plot_path = plot_combined_figure(
        list(processed_files.values()),
        save_name=f"{plot_stem}_summary.png",
        save_dir=os.path.join("outputs", "figures", "te", batch_id),
    )
    print(f"Saved batch transport plot: {plot_path}")
    return plot_path


def te_analysis(
    batch_id: str,
    sample_files: dict,
    sample_selectors=None,
    strict: bool = False,
):
    """
    Main batch workflow:
    1. Load raw data, calculate transport properties, and save processed CSVs.
    2. Run SPB-derived transport-column calculation when available.
    3. Extract compact features and save JSON.
    4. Plot processed transport properties.
    """
    print(f"Starting TE analysis for batch: {batch_id}")
    sample_files = filter_sample_files(
        batch_id,
        sample_files,
        sample_selectors=sample_selectors,
        strict=strict,
    )

    _, processed_path = setup_batch_directories(batch_id)

    processed_data, processed_files = process_batch_raw_data(
        batch_id,
        sample_files,
        processed_path,
    )
    spb_results = run_spb_fitting(processed_data, processed_files)
    sample_metadata = get_sample_metadata(sample_files)
    features_dict = extract_and_save_features(
        batch_id,
        processed_data,
        spb_results,
        processed_path,
        sample_metadata,
        merge_existing=bool(sample_selectors),
    )

    plot_batch_transport(batch_id, processed_files, sample_selectors=sample_selectors)

    print(f"Finished TE analysis for batch: {batch_id}")
    return {
        "processed_data": processed_data,
        "processed_files": processed_files,
        "spb_results": spb_results,
        "features": features_dict,
    }


def main():
    """Compatibility CLI; the full batch runner lives in run_analysis.py."""
    from run_analysis import execute_selected_batches, parse_args

    args = parse_args()
    execute_selected_batches(
        args.batches,
        sample_selectors=args.samples,
        analyze_all=args.all,
        sync_markdown=not args.no_markdown_sync,
        sync_raw=not args.no_raw_sync,
        refresh_markdown_after=not args.no_markdown_refresh,
        dry_run=args.dry_run,
        strict=args.strict,
    )


if __name__ == "__main__":
    main()

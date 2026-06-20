import json
import os

import pandas as pd

from src.tools.file_utils import setup_batch_directories

try:
    from src.tools.te_data import load_zem, load_lfa, calculate_zt
    HAS_PARSER = True
except ImportError:
    HAS_PARSER = False
    print('No modulus for TE calculation')

try:
    from src.tools.plot import plot_comprehensive_figure
    HAS_PLOTTER = True
except ImportError:
    HAS_PLOTTER = False

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
    WEIGHTED_MOBILITY_COLUMN = 'Weighted_Mobility_cm2_V-1_s-1'
    QUALITY_FACTOR_COLUMN = 'Quality_Factor_B'
    print('No modulus for lattice thermal conductivity calculation')

try:
    from src.agents.core_agent import analyze_materials_data
    HAS_AGENT = True
except ImportError:
    HAS_AGENT = False


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
    """Return only sample entries from a batch config, ignoring metadata."""
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
        merged.update({
            key: value
            for key, value in paths.items()
            if key in MATERIAL_METADATA_FIELDS
        })
        sample_metadata[sample_name] = merged

    return sample_metadata


def process_batch_raw_data(batch_id: str, sample_files: dict, processed_path: str):
    """
    Load raw ZEM/LFA files, calculate transport properties, and save one
    processed CSV per sample.
    """
    processed_data = {}
    processed_files = {}

    if not HAS_PARSER:
        print('skipping step1: TE parser is not available')
        return processed_data, processed_files

    print('step1. Data processing')

    for sample_name, paths in get_sample_records(sample_files).items():
        sample_id = paths.get("sample_id") or f"{batch_id}-{sample_name}"
        zem_path = paths.get('zem')
        lfa_path = paths.get('lfa')
        density_val = paths.get('density')
        cp_val = paths.get('cp_value', 0.3)

        if density_val is None or cp_val is None:
            print(
                f"⚠️ skip {sample_name}: density/cp_value missing. "
                "Fill these in data/lab/samples.json before calculation."
            )
            continue

        zem_data = load_zem(zem_path)
        lfa_data = load_lfa(lfa_path)

        if zem_data is None or lfa_data is None:
            print(f"⚠️ skip {sample_name}: raw ZEM or LFA data is missing")
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

        print(f"💾 已保存清洗后数据至: {save_path}")
        print(f"\n👀 {sample_id} ({sample_name}) 的数据预览:")
        print(zt_data.head())
        print("-" * 50)

    return processed_data, processed_files


def run_spb_fitting(processed_data: dict, processed_files: dict = None):
    """
    Run the currently available SPB-derived transport-column calculation.

    Future full SPB fitting results can be added to the returned dict:
    {
        "sample_name": {
            "carrier_concentration": ...,
            "effective_mass": ...,
            ...
        }
    }
    """
    if not processed_data:
        print('skipping step2: no processed data')
        return {}

    if not HAS_LATTICE_CALC:
        print('skipping step2: lattice thermal conductivity module is not available')
        return {}

    has_spb_columns = all(
        set(SPB_OUTPUT_COLUMNS).issubset(df.columns)
        for df in processed_data.values()
    )

    if has_spb_columns:
        print('step2. SPB-derived columns already available')
    else:
        print('step2. SPB-derived transport columns')
        updated_data = calculate_lattice_for_dataframes(processed_data)
        processed_data.clear()
        processed_data.update(updated_data)

    if processed_files:
        for sample_name, df in processed_data.items():
            save_path = processed_files.get(sample_name)
            if save_path:
                df.to_csv(save_path, index=False)
                print(f"💾 SPB-derived columns saved to: {save_path}")

    spb_results = {}
    for sample_name, df in processed_data.items():
        if 'Lorenz_Number_1e-8_WOhmK-2' not in df.columns:
            continue
        spb_results[sample_name] = {
            "Lorenz_Number_1e-8_WOhmK-2_mean": df['Lorenz_Number_1e-8_WOhmK-2'].mean(),
            "Carrier_Thermal_Conductivity_mean": df['Carrier_Thermal_Conductivity'].mean(),
            "Lattice_Thermal_Conductivity_min": df['Lattice_Thermal_Conductivity'].min(),
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
    Extract compact sample-level features from calculated transport data and
    optional SPB fitting results.
    """
    required_columns = {
        'Temperature',
        'Seebeck',
        'Conductivity',
        'Thermal_Conductivity',
        'ZT',
    }
    missing_columns = required_columns - set(transport_df.columns)
    if missing_columns:
        print(f"⚠️ 提取特征失败，{sample_name} 缺少列名: {sorted(missing_columns)}")
        return None

    col_T = 'Temperature'
    col_S = 'Seebeck'
    col_C = 'Conductivity'
    col_K = 'Thermal_Conductivity'
    col_ZT = 'ZT'

    idx_S_max = transport_df[col_S].abs().idxmax()
    idx_C_max = transport_df[col_C].idxmax()
    idx_K_min = transport_df[col_K].idxmin()
    idx_ZT_max = transport_df[col_ZT].idxmax()

    features = {
        "Samples": sample_name,
        "T_S_max(K)": round(transport_df.loc[idx_S_max, col_T], 2),
        "S_max(V/K)": transport_df.loc[idx_S_max, col_S],
        "T_C_max(K)": round(transport_df.loc[idx_C_max, col_T], 2),
        "C_max(S/m)": transport_df.loc[idx_C_max, col_C],
        "T_K_min(K)": round(transport_df.loc[idx_K_min, col_T], 2),
        "K_min(W/(m*K))": transport_df.loc[idx_K_min, col_K],
        "T_ZT_max(K)": round(transport_df.loc[idx_ZT_max, col_T], 2),
        "ZT_max": transport_df.loc[idx_ZT_max, col_ZT],
    }

    if sample_metadata:
        features.update({
            key: value
            for key, value in sample_metadata.items()
            if key in MATERIAL_METADATA_FIELDS and value not in ("", None, [])
        })

    if 'Lattice_Thermal_Conductivity' in transport_df.columns:
        col_KL = 'Lattice_Thermal_Conductivity'
        idx_KL_min = transport_df[col_KL].idxmin()
        features.update({
            "T_KL_min(K)": round(transport_df.loc[idx_KL_min, col_T], 2),
            "KL_min(W/(m*K))": transport_df.loc[idx_KL_min, col_KL],
        })

    if 'Carrier_Thermal_Conductivity' in transport_df.columns:
        col_Ke = 'Carrier_Thermal_Conductivity'
        idx_Ke_max = transport_df[col_Ke].idxmax()
        features.update({
            "T_Ke_max(K)": round(transport_df.loc[idx_Ke_max, col_T], 2),
            "Ke_max(W/(m*K))": transport_df.loc[idx_Ke_max, col_Ke],
        })

    if WEIGHTED_MOBILITY_COLUMN in transport_df.columns:
        weighted_mobility = pd.to_numeric(
            transport_df[WEIGHTED_MOBILITY_COLUMN],
            errors='coerce',
        ).dropna()
        if not weighted_mobility.empty:
            idx_mu_max = weighted_mobility.idxmax()
            features.update({
                "T_weighted_mobility_max(K)": round(
                    transport_df.loc[idx_mu_max, col_T],
                    2,
                ),
                f"{WEIGHTED_MOBILITY_COLUMN}_max": transport_df.loc[
                    idx_mu_max,
                    WEIGHTED_MOBILITY_COLUMN,
                ],
            })

    if QUALITY_FACTOR_COLUMN in transport_df.columns:
        quality_factor = pd.to_numeric(
            transport_df[QUALITY_FACTOR_COLUMN],
            errors='coerce',
        ).dropna()
        if not quality_factor.empty:
            idx_b_max = quality_factor.idxmax()
            features.update({
                "T_quality_factor_max(K)": round(
                    transport_df.loc[idx_b_max, col_T],
                    2,
                ),
                f"{QUALITY_FACTOR_COLUMN}_max": transport_df.loc[
                    idx_b_max,
                    QUALITY_FACTOR_COLUMN,
                ],
            })

    if spb_result:
        features["SPB"] = spb_result

    return features


def extract_and_save_features(
    batch_id: str,
    processed_data: dict,
    spb_results: dict,
    processed_path: str,
    sample_metadata: dict = None,
):
    """
    Build the feature JSON used by future agent analysis.
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

    features_dict = {
        "batch_name": batch_id,
        "samples_data": features_list,
    }

    if features_list:
        feature_df = pd.DataFrame(features_list)
        print("\n🏆 本批次特征数据提取完成 (用于 Agent 机理分析):")
        print(feature_df.to_string(index=False))

    json_path = os.path.join(processed_path, "extracted_features.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(features_dict, f, indent=4, ensure_ascii=False)

    print(f"✅ 核心特征数据已保存至: {json_path}")
    return features_dict


def plot_batch_transport(batch_id: str, processed_files: dict):
    """
    Plot the processed CSV files for the batch if plotting is available.
    """
    if not HAS_PLOTTER:
        print('skipping step3: plotter is not available')
        return None

    if not processed_files:
        print('skipping step3: no processed files')
        return None

    plot_path = plot_comprehensive_figure(
        list(processed_files.values()),
        save_name=f"{batch_id}_summary.png",
        save_dir=os.path.join("outputs", "figures", "te", batch_id),
    )
    print(f"📈 批次综合图已保存至: {plot_path}")
    return plot_path


def run_agent_analysis(features_dict: dict):
    """
    Run the agent analysis from already extracted features.
    """
    if not HAS_AGENT:
        print("⏭️ 跳过 Step 4 (缺少 Agent 模块)")
        return None

    if not features_dict.get("samples_data"):
        print("⏭️ 跳过 Step 4 (无可用特征数据)")
        return None

    print("➡️ Step 4: 召唤大模型进行机理分析...")
    agent_report = analyze_materials_data(features_dict)

    print("✅ Agent 分析完成并已生成报告。")
    print("\n================ Agent 结论 ================\n")
    print(agent_report)
    return agent_report


def te_analysis(batch_id: str, sample_files: dict):
    """
    Main batch workflow:
    1. Load raw data, calculate transport properties, save processed CSVs.
    2. Run SPB-derived transport-column calculation when available.
    3. Extract compact features and save JSON for agent analysis.
    4. Plot processed transport properties.
    5. Run agent analysis from extracted features.
    """
    print(f"Starting process: {batch_id}")

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
    )

    plot_batch_transport(batch_id, processed_files)
    run_agent_analysis(features_dict)

    print(f"🎉 批次 {batch_id} 处理完毕！")
    return {
        "processed_data": processed_data,
        "processed_files": processed_files,
        "spb_results": spb_results,
        "features": features_dict,
    }

#!/usr/bin/env python3
"""
Build Notion-ready payloads for NU sample and batch lab databases.

The script combines local lab metadata, raw-file paths, processed TE metrics,
and batch summary plot paths into CSV/JSON artifacts that can be uploaded or
used by a Notion sync step.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
SAMPLES_PATH = WORKSPACE / "data" / "lab" / "samples.json"
BATCHES_PATH = WORKSPACE / "data" / "lab" / "batches.json"
PROCESSED_DIR = WORKSPACE / "data" / "processed"
RAW_DIR = WORKSPACE / "data" / "raw"
PLOTS_DIR = WORKSPACE / "results" / "plots"
OUTPUT_DIR = WORKSPACE / "results" / "notion_sync"


SAMPLE_FIELDS = [
    "sample_id",
    "batch_id",
    "sample_name",
    "sample_composition",
    "pristine_composition",
    "matrix_composition",
    "material_family",
    "optimization_type",
    "modifier_species",
    "modifier_element",
    "modifier_elements",
    "modifier_amount",
    "modifier_unit",
    "modifier_site",
    "density_g_cm3",
    "cp_value",
    "phase_type",
    "synthesis_route",
    "annealing_condition",
    "processed_exists",
    "zem_path",
    "lfa_path",
    "xrd_paths",
    "processed_file",
    "temperature_near_300_K",
    "seebeck_300_uV_K",
    "conductivity_300_S_cm",
    "power_factor_300_uW_cm_K2",
    "thermal_conductivity_300_W_m_K",
    "zt_300",
    "seebeck_max_uV_K",
    "temperature_seebeck_max_K",
    "conductivity_max_S_cm",
    "temperature_conductivity_max_K",
    "power_factor_max_uW_cm_K2",
    "temperature_power_factor_max_K",
    "thermal_conductivity_min_W_m_K",
    "temperature_thermal_conductivity_min_K",
    "lattice_thermal_conductivity_min_W_m_K",
    "temperature_lattice_thermal_conductivity_min_K",
    "zt_max",
    "temperature_zt_max_K",
    "notes",
]


BATCH_FIELDS = [
    "batch_id",
    "project",
    "material_family",
    "matrix_composition",
    "pristine_composition",
    "sample_count",
    "processed_count",
    "zem_count",
    "lfa_count",
    "xrd_count",
    "best_sample_by_zt",
    "zt_max",
    "temperature_zt_max_K",
    "best_sample_by_power_factor",
    "power_factor_max_uW_cm_K2",
    "temperature_power_factor_max_K",
    "summary_plot_png",
    "summary_plot_pdf",
    "notes",
]


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def rel(path: Path | str | None) -> str:
    if not path:
        return ""
    path = Path(path)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(WORKSPACE).as_posix()
    except ValueError:
        return path.as_posix()


def round_value(value, digits=6):
    if value is None:
        return ""
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return value


def read_processed_rows(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def numeric(row, key):
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def nearest_temperature_row(rows, target=300.0):
    valid_rows = [row for row in rows if numeric(row, "Temperature") is not None]
    if not valid_rows:
        return None
    return min(valid_rows, key=lambda row: abs(numeric(row, "Temperature") - target))


def row_with_max(rows, key):
    valid_rows = [row for row in rows if numeric(row, key) is not None]
    if not valid_rows:
        return None
    return max(valid_rows, key=lambda row: numeric(row, key))


def row_with_min(rows, key):
    valid_rows = [row for row in rows if numeric(row, key) is not None]
    if not valid_rows:
        return None
    return min(valid_rows, key=lambda row: numeric(row, key))


def sample_xrd_paths(batch_id: str, sample_id: str) -> list[str]:
    xrd_dir = RAW_DIR / batch_id / "XRD"
    if not xrd_dir.exists():
        return []
    return sorted(rel(path) for path in xrd_dir.glob(f"{sample_id}*"))


def performance_metrics(processed_file: str) -> dict:
    rows = read_processed_rows(WORKSPACE / processed_file)
    metrics = {}

    near_300 = nearest_temperature_row(rows)
    if near_300:
        metrics.update(
            {
                "temperature_near_300_K": round_value(numeric(near_300, "Temperature"), 2),
                "seebeck_300_uV_K": round_value(numeric(near_300, "Seebeck") * 1e6, 3),
                "conductivity_300_S_cm": round_value(numeric(near_300, "Conductivity") / 100, 3),
                "power_factor_300_uW_cm_K2": round_value(
                    numeric(near_300, "Power_Factor") * 10000, 3
                ),
                "thermal_conductivity_300_W_m_K": round_value(
                    numeric(near_300, "Thermal_Conductivity"), 3
                ),
                "zt_300": round_value(numeric(near_300, "ZT"), 4),
            }
        )

    seebeck_row = row_with_max(rows, "Seebeck")
    if seebeck_row:
        metrics["seebeck_max_uV_K"] = round_value(numeric(seebeck_row, "Seebeck") * 1e6, 3)
        metrics["temperature_seebeck_max_K"] = round_value(numeric(seebeck_row, "Temperature"), 2)

    conductivity_row = row_with_max(rows, "Conductivity")
    if conductivity_row:
        metrics["conductivity_max_S_cm"] = round_value(
            numeric(conductivity_row, "Conductivity") / 100, 3
        )
        metrics["temperature_conductivity_max_K"] = round_value(
            numeric(conductivity_row, "Temperature"), 2
        )

    power_factor_row = row_with_max(rows, "Power_Factor")
    if power_factor_row:
        metrics["power_factor_max_uW_cm_K2"] = round_value(
            numeric(power_factor_row, "Power_Factor") * 10000, 3
        )
        metrics["temperature_power_factor_max_K"] = round_value(
            numeric(power_factor_row, "Temperature"), 2
        )

    thermal_row = row_with_min(rows, "Thermal_Conductivity")
    if thermal_row:
        metrics["thermal_conductivity_min_W_m_K"] = round_value(
            numeric(thermal_row, "Thermal_Conductivity"), 3
        )
        metrics["temperature_thermal_conductivity_min_K"] = round_value(
            numeric(thermal_row, "Temperature"), 2
        )

    lattice_row = row_with_min(rows, "Lattice_Thermal_Conductivity")
    if lattice_row:
        metrics["lattice_thermal_conductivity_min_W_m_K"] = round_value(
            numeric(lattice_row, "Lattice_Thermal_Conductivity"), 3
        )
        metrics["temperature_lattice_thermal_conductivity_min_K"] = round_value(
            numeric(lattice_row, "Temperature"), 2
        )

    zt_row = row_with_max(rows, "ZT")
    if zt_row:
        metrics["zt_max"] = round_value(numeric(zt_row, "ZT"), 4)
        metrics["temperature_zt_max_K"] = round_value(numeric(zt_row, "Temperature"), 2)

    return metrics


def string_list(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return value or ""


def build_sample_records(samples, batch_lookup):
    records = []
    for sample in samples:
        batch_id = sample.get("batch_id", "")
        batch = batch_lookup.get(batch_id, {})
        processed_file = sample.get("processed_file", "")
        record = {
            "sample_id": sample.get("sample_id", ""),
            "batch_id": batch_id,
            "sample_name": sample.get("sample_name", ""),
            "sample_composition": sample.get("sample_composition", ""),
            "pristine_composition": sample.get("pristine_composition", "")
            or batch.get("pristine_composition", ""),
            "matrix_composition": sample.get("matrix_composition", "")
            or batch.get("matrix_composition", ""),
            "material_family": batch.get("material_family", ""),
            "optimization_type": sample.get("optimization_type", ""),
            "modifier_species": sample.get("modifier_species", ""),
            "modifier_element": sample.get("modifier_element", ""),
            "modifier_elements": string_list(sample.get("modifier_elements")),
            "modifier_amount": sample.get("modifier_amount", ""),
            "modifier_unit": sample.get("modifier_unit", ""),
            "modifier_site": sample.get("modifier_site", ""),
            "density_g_cm3": sample.get("density", ""),
            "cp_value": sample.get("cp_value", ""),
            "phase_type": sample.get("phase_type", ""),
            "synthesis_route": sample.get("synthesis_route", ""),
            "annealing_condition": sample.get("annealing_condition", ""),
            "processed_exists": sample.get("processed_exists", False),
            "zem_path": sample.get("zem", ""),
            "lfa_path": sample.get("lfa", ""),
            "xrd_paths": "; ".join(sample_xrd_paths(batch_id, sample.get("sample_id", ""))),
            "processed_file": processed_file,
            "notes": sample.get("notes", ""),
        }
        if processed_file:
            record.update(performance_metrics(processed_file))
        records.append(record)
    return records


def plot_path(batch_id: str, suffix: str) -> str:
    path = PLOTS_DIR / batch_id / f"{batch_id}_summary.{suffix}"
    return rel(path) if path.exists() else ""


def build_batch_records(batches, sample_records):
    records = []
    samples_by_batch = {}
    for sample in sample_records:
        samples_by_batch.setdefault(sample["batch_id"], []).append(sample)

    for batch in batches:
        batch_id = batch.get("batch_id", "")
        samples = samples_by_batch.get(batch_id, [])
        best_zt = max(
            (sample for sample in samples if sample.get("zt_max") not in ("", None)),
            key=lambda sample: sample["zt_max"],
            default={},
        )
        best_pf = max(
            (sample for sample in samples if sample.get("power_factor_max_uW_cm_K2") not in ("", None)),
            key=lambda sample: sample["power_factor_max_uW_cm_K2"],
            default={},
        )
        records.append(
            {
                "batch_id": batch_id,
                "project": batch.get("project", ""),
                "material_family": batch.get("material_family", ""),
                "matrix_composition": batch.get("matrix_composition", ""),
                "pristine_composition": batch.get("pristine_composition", ""),
                "sample_count": len(samples),
                "processed_count": sum(1 for sample in samples if sample.get("processed_exists")),
                "zem_count": sum(1 for sample in samples if sample.get("zem_path")),
                "lfa_count": sum(1 for sample in samples if sample.get("lfa_path")),
                "xrd_count": sum(1 for sample in samples if sample.get("xrd_paths")),
                "best_sample_by_zt": best_zt.get("sample_id", ""),
                "zt_max": best_zt.get("zt_max", ""),
                "temperature_zt_max_K": best_zt.get("temperature_zt_max_K", ""),
                "best_sample_by_power_factor": best_pf.get("sample_id", ""),
                "power_factor_max_uW_cm_K2": best_pf.get("power_factor_max_uW_cm_K2", ""),
                "temperature_power_factor_max_K": best_pf.get("temperature_power_factor_max_K", ""),
                "summary_plot_png": plot_path(batch_id, "png"),
                "summary_plot_pdf": plot_path(batch_id, "pdf"),
                "notes": batch.get("notes", ""),
            }
        )
    return records


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    batches = load_json(BATCHES_PATH, [])
    samples = load_json(SAMPLES_PATH, [])
    batch_lookup = {batch.get("batch_id"): batch for batch in batches}

    sample_records = build_sample_records(samples, batch_lookup)
    batch_records = build_batch_records(batches, sample_records)

    write_csv(OUTPUT_DIR / "sample_list_nu_payload.csv", sample_records, SAMPLE_FIELDS)
    write_csv(OUTPUT_DIR / "batch_list_nu_payload.csv", batch_records, BATCH_FIELDS)

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target_databases": {
            "samples": "sample list NU",
            "batches": "batch list NU",
        },
        "sample_count": len(sample_records),
        "batch_count": len(batch_records),
        "files": {
            "sample_payload_csv": rel(OUTPUT_DIR / "sample_list_nu_payload.csv"),
            "batch_payload_csv": rel(OUTPUT_DIR / "batch_list_nu_payload.csv"),
            "sample_source_json": rel(SAMPLES_PATH),
            "batch_source_json": rel(BATCHES_PATH),
        },
    }
    with (OUTPUT_DIR / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=4, ensure_ascii=False)
        handle.write("\n")

    print(f"Wrote {len(sample_records)} sample records")
    print(f"Wrote {len(batch_records)} batch records")
    print(f"Output: {rel(OUTPUT_DIR)}")


if __name__ == "__main__":
    main()

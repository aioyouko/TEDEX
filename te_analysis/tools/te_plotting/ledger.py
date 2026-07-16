"""Lab and reference ledger loading (batches/samples JSON).

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


def load_lab_ledger(file_path="configs/lab_batches.json"):
    flat_ledger = load_flat_lab_ledger()
    reference_ledger = load_flat_reference_ledger()
    if flat_ledger or reference_ledger:
        merged = dict(flat_ledger)
        for reference_id, reference_samples in reference_ledger.items():
            if reference_id in merged:
                merged[f"REF-{reference_id}"] = reference_samples
            else:
                merged[reference_id] = reference_samples
        return merged

    return load_json(file_path, {})


def load_json(file_path, default):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"❌ JSON NOT FOUND: {file_path}")
        return default
    except json.JSONDecodeError:
        print(f"❌ JSON FORMAT WRONG: {file_path}")
        return default


def load_flat_lab_ledger(
    batches_path="data/lab/batches.json",
    samples_path="data/lab/samples.json",
):
    batches = load_json(batches_path, [])
    samples = load_json(samples_path, [])
    ledger = {}

    for batch in batches:
        batch_id = batch.get("batch_id")
        if not batch_id:
            continue
        ledger[batch_id] = {
            "batch_metadata": {
                "matrix_composition": batch.get("matrix_composition", ""),
                "pristine_composition": batch.get("pristine_composition", ""),
                "material_family": batch.get("material_family", ""),
                "notes": batch.get("notes", ""),
            }
        }

    for sample in samples:
        batch_id = sample.get("batch_id")
        if not batch_id:
            continue

        sample_id = sample.get("sample_id")
        sample_name = sample.get("sample_name") or sample_id
        if not sample_name:
            continue

        ledger.setdefault(batch_id, {"batch_metadata": {}})
        if (
            sample_name in ledger[batch_id]
            and ledger[batch_id][sample_name].get("sample_id") != sample_id
            and sample_id
        ):
            sample_name = sample_id

        ledger[batch_id][sample_name] = {
            key: value
            for key, value in sample.items()
            if key not in {"batch_id", "processed_exists"}
        }

    return ledger


def load_flat_reference_ledger(samples_path="data/reference/samples.json"):
    samples = load_json(samples_path, [])
    ledger = {}

    for sample in samples:
        reference_id = sample.get("reference_id")
        if not reference_id:
            continue

        sample_name = sample.get("sample_name") or sample.get("sample_id")
        if not sample_name:
            continue

        ledger.setdefault(
            reference_id,
            {
                "batch_metadata": {
                    "matrix_composition": sample.get("matrix_composition", ""),
                    "pristine_composition": sample.get("pristine_composition", ""),
                    "material_family": sample.get("material_family", ""),
                    "notes": sample.get("notes", ""),
                    "source_type": "reference",
                }
            },
        )

        sample_entry = {
            key: value
            for key, value in sample.items()
            if key not in {"processed_exists"}
        }
        if sample_entry.get("performance_file") and not sample_entry.get("processed_file"):
            sample_entry["processed_file"] = sample_entry["performance_file"]
        sample_entry["is_reference"] = True

        ledger[reference_id][sample_name] = sample_entry

    return ledger

ALL_LAB_BATCHES = load_lab_ledger()



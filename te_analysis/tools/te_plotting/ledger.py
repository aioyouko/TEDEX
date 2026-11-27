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

from te_analysis.paths import get_workspace
from te_analysis.tools.plot import TE_PLOT_SPECS
from te_analysis.tools.selectors import (
    normalize_sample_selector as normalize_selector,
    truncate_with_digest,
)


def load_lab_ledger(file_path=None):
    ws = get_workspace()
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

    fallback = Path(file_path) if file_path is not None else ws.legacy_lab_batches_json
    return load_json(fallback, {}, quiet_missing=True)


def load_json(file_path, default, quiet_missing=False):
    path = Path(file_path)
    if not path.exists():
        if not quiet_missing:
            print(f"❌ JSON NOT FOUND: {file_path}")
        return default
    try:
        with path.open('r', encoding='utf-8') as file:
            return json.load(file)
    except json.JSONDecodeError:
        print(f"❌ JSON FORMAT WRONG: {file_path}")
        return default


def load_flat_lab_ledger(
    batches_path=None,
    samples_path=None,
):
    ws = get_workspace()
    b_path = Path(batches_path) if batches_path is not None else ws.batches_json
    s_path = Path(samples_path) if samples_path is not None else ws.samples_json
    batches = load_json(b_path, [], quiet_missing=True)
    samples = load_json(s_path, [], quiet_missing=True)
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


def load_flat_reference_ledger(samples_path=None):
    ws = get_workspace()
    ref_path = Path(samples_path) if samples_path is not None else ws.reference_samples_json
    samples = load_json(ref_path, [], quiet_missing=True)
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



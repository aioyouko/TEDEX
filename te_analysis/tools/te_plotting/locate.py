"""Processed-data discovery: selectors, paths, labels, and data loading.

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
from te_analysis.tools.te_plotting.properties import standardize_te_dataframe_columns
from te_analysis.tools.te_plotting.ledger import ALL_LAB_BATCHES, load_flat_lab_ledger, load_flat_reference_ledger, load_json, load_lab_ledger


TE_FIGURE_DIR = Path("data") / "processed" / "figures"
TE_LABEL_FILE_STEMS = ("label", "labels", "legend", "legends")
TE_LABEL_FILE_SUFFIXES = ("", ".txt", ".csv", ".tsv", ".md")
def get_batch_plot_dir(batch_id):
    return str(Path(get_processed_dir(batch_id)) / "figures")


def get_single_plot_dir(batch_id):
    return os.path.join(get_batch_plot_dir(batch_id), f"single-{batch_id}")


def get_interbatch_comparison_id(target_batches):
    safe_names = []
    for target in target_batches:
        safe_names.append(safe_selector_name(target))
    return "_vs_".join(safe_names)


def get_interbatch_plot_dir(comparison_id):
    return str(TE_FIGURE_DIR / "inter-batch" / comparison_id)


def get_interbatch_single_plot_dir(comparison_id):
    return os.path.join(get_interbatch_plot_dir(comparison_id), f"single-{comparison_id}")


def is_te_label_file(path):
    path = Path(path)
    return (
        path.stem.lower() in TE_LABEL_FILE_STEMS
        and path.suffix.lower() in TE_LABEL_FILE_SUFFIXES
    )


def iter_te_data_csvs(directory):
    return sorted(path for path in Path(directory).glob("*.csv") if not is_te_label_file(path))


def find_te_label_file(csv_dir):
    directory = Path(csv_dir)
    for stem in TE_LABEL_FILE_STEMS:
        for suffix in TE_LABEL_FILE_SUFFIXES:
            candidate = directory / f"{stem}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def read_te_labels(path):
    path = Path(path)
    labels = []
    suffix = path.suffix.lower()

    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            for row in reader:
                if not row:
                    continue
                label = row[0].strip()
                if not label or label.startswith("#"):
                    continue
                labels.append(label)
        return labels

    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            label = line.strip()
            if not label or label.startswith("#"):
                continue
            labels.append(label)
    return labels


def load_te_label_overrides(csv_files):
    overrides = {}
    grouped_dirs = sorted({Path(path).parent for path in csv_files})

    for csv_dir in grouped_dirs:
        label_file = find_te_label_file(csv_dir)
        if label_file is None:
            continue

        labels = read_te_labels(label_file)
        directory_files = iter_te_data_csvs(csv_dir)
        if len(labels) != len(directory_files):
            print(
                f"warning: {label_file} has {len(labels)} labels for "
                f"{len(directory_files)} TE CSV files; applying labels by sorted file order."
            )

        for path, label in zip(directory_files, labels):
            overrides[path.resolve()] = label

    return overrides


def get_processed_csv_paths(batch_id):
    processed_dir = os.path.join("data", "processed", f"{batch_id}-processed")

    if not os.path.exists(processed_dir):
        print(f"⚠️ cannot find {processed_dir}, run_analysis.py before this step")
        return []

    processed_data = [str(path) for path in iter_te_data_csvs(processed_dir)]

    if not processed_data:
        print(f"⚠️ no .csv in {processed_dir}, skip")

    return processed_data


def get_processed_dir(batch_id):
    return os.path.join("data", "processed", f"{batch_id}-processed")



def safe_selector_name(selector, max_length=96):
    raw_selector = str(selector)
    selector = raw_selector.strip()
    selector = selector.replace(os.sep, "-").replace("/", "-").replace(":", "-").replace(" ", "_")
    selector = selector.replace("\\", "-")
    selector = selector.strip("-") or "selected_te"
    return truncate_with_digest(selector, max_length)


def selector_is_path_like(selector):
    selector = str(selector)
    return (
        selector.endswith(".csv")
        or os.sep in selector
        or "/" in selector
        or "\\" in selector
        or selector.startswith(".")
    )


def selector_is_definite_path(selector):
    selector = str(selector)
    return (
        selector.endswith(".csv")
        or selector.startswith(".")
        or selector.startswith("data/")
        or selector.startswith("data\\")
    )


def selector_is_whole_batch(selector):
    return normalize_selector(selector) in ALL_LAB_BATCHES


def selectors_need_combined_view(selectors):
    return any(not selector_is_whole_batch(selector) for selector in selectors)


def infer_raw_sample_suffix(sample_id, batch_id):
    prefix = f"{batch_id}-"
    if sample_id.startswith(prefix):
        return sample_id[len(prefix):]
    return sample_id


def get_candidate_processed_paths(batch_id, sample_name, sample_info):
    processed_dir = get_processed_dir(batch_id)
    sample_id = sample_info.get("sample_id", "")
    display_name = sample_info.get("sample_name", sample_name)
    raw_suffix = infer_raw_sample_suffix(sample_id, batch_id) if sample_id else sample_name
    legacy_name = sample_info.get("legacy_sample_name", "")

    stems = [
        sample_id,
        raw_suffix,
        sample_name,
        display_name,
        legacy_name,
    ]

    candidates = []
    for stem in stems:
        if stem:
            candidates.append(os.path.join(processed_dir, f"{stem}.csv"))

    processed_file = sample_info.get("processed_file")
    if processed_file:
        candidates.append(processed_file)
    performance_file = sample_info.get("performance_file")
    if performance_file:
        candidates.append(performance_file)

    unique_candidates = []
    for candidate in candidates:
        if candidate not in unique_candidates:
            unique_candidates.append(candidate)
    return unique_candidates


def get_processed_path_aliases(path_like):
    """
    Return possible filesystem paths for a direct processed CSV/dir selector.

    This accepts both the project layout, e.g.
    data/processed/CHY-1040-processed/Zn_dope_0.02.csv, and the shorter form
    data/processed/CHY-1040/Zn_dope_0.02.csv.
    """
    raw_path = Path(path_like)
    candidates = [raw_path]

    if raw_path.suffix == "":
        candidates.append(raw_path.with_suffix(".csv"))

    parts = list(raw_path.parts)
    for idx, part in enumerate(parts):
        if part == "processed" and idx + 1 < len(parts):
            batch_part = parts[idx + 1]
            if batch_part.startswith("CHY-") and not batch_part.endswith("-processed"):
                alias_parts = parts[:]
                alias_parts[idx + 1] = f"{batch_part}-processed"
                alias_path = Path(*alias_parts)
                candidates.append(alias_path)
                if alias_path.suffix == "":
                    candidates.append(alias_path.with_suffix(".csv"))

    unique_candidates = []
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique_candidates.append(candidate)
            seen.add(key)
    return unique_candidates


def resolve_processed_path_selector(selector):
    matches = []
    for candidate in get_processed_path_aliases(selector):
        if candidate.is_file() and candidate.suffix.lower() == ".csv" and not is_te_label_file(candidate):
            matches.append(candidate)
        elif candidate.is_dir():
            matches.extend(iter_te_data_csvs(candidate))

    unique_matches = []
    seen = set()
    for match in matches:
        key = str(match.resolve())
        if key not in seen:
            unique_matches.append(match)
            seen.add(key)
    return unique_matches


def read_te_dataframe(csv_path):
    return standardize_te_dataframe_columns(pd.read_csv(csv_path), csv_path=csv_path)


def infer_batch_from_processed_path(csv_path):
    for part in Path(csv_path).parts:
        if part.startswith("CHY-"):
            return part.replace("-processed", "")
    return ""


def resolve_processed_csv_path(batch_id, sample_name, sample_info):
    for candidate in get_candidate_processed_paths(batch_id, sample_name, sample_info):
        if os.path.exists(candidate):
            return candidate
    return None


def iter_batch_samples(batch_id):
    batch_files = ALL_LAB_BATCHES.get(batch_id, {})
    for sample_name, sample_info in batch_files.items():
        if sample_name == "batch_metadata" or not isinstance(sample_info, dict):
            continue
        yield sample_name, sample_info


def sample_matches_selector(batch_id, sample_name, sample_info, selector):
    sample_id = sample_info.get("sample_id", "")
    raw_suffix = infer_raw_sample_suffix(sample_id, batch_id) if sample_id else sample_name
    display_name = sample_info.get("sample_name", sample_name)
    legacy_name = sample_info.get("legacy_sample_name", "")
    sample_composition = sample_info.get("sample_composition", "")

    possible_selectors = {
        sample_id,
        f"{batch_id}-{raw_suffix}",
        f"{batch_id}-{sample_name}",
        f"{batch_id}-{display_name}",
        f"{batch_id}-{legacy_name}" if legacy_name else "",
        f"{batch_id}-{sample_composition}" if sample_composition else "",
        f"{batch_id}/{sample_name}",
        f"{batch_id}:{sample_name}",
        f"{batch_id}/{display_name}",
        f"{batch_id}:{display_name}",
        f"{batch_id}/{sample_composition}" if sample_composition else "",
        f"{batch_id}:{sample_composition}" if sample_composition else "",
        sample_name,
        display_name,
        legacy_name,
        sample_composition,
        raw_suffix,
    }

    return selector in possible_selectors


def resolve_sample_selectors(selectors):
    resolved_samples = []

    for raw_selector in selectors:
        selector = normalize_selector(raw_selector)

        if selector in ALL_LAB_BATCHES:
            for sample_name, sample_info in iter_batch_samples(selector):
                resolved_samples.append((selector, sample_name, sample_info))
            continue

        matched = False
        for batch_id in ALL_LAB_BATCHES:
            for sample_name, sample_info in iter_batch_samples(batch_id):
                if sample_matches_selector(batch_id, sample_name, sample_info, selector):
                    resolved_samples.append((batch_id, sample_name, sample_info))
                    matched = True

        if not matched:
            print(f"⚠️ cannot match selector: {raw_selector}")

    return resolved_samples


def get_sample_label(batch_id, csv_path, include_batch=False):
    csv_basename = os.path.basename(csv_path)
    csv_stem = os.path.splitext(csv_basename)[0]
    batch_files = ALL_LAB_BATCHES.get(batch_id, {})

    label = csv_stem
    for sample_name, sample_info in batch_files.items():
        if sample_name == "batch_metadata" or not isinstance(sample_info, dict):
            continue

        processed_file = sample_info.get("processed_file", "") or sample_info.get("performance_file", "")
        if os.path.basename(processed_file) == csv_basename or sample_name == csv_stem:
            label = sample_info.get("sample_name") or sample_name
            break

    if include_batch:
        return f"{batch_id}/{label}"
    return label


def get_path_sample_label(csv_path, include_batch=False):
    csv_path = Path(csv_path)
    batch_id = infer_batch_from_processed_path(csv_path)
    if batch_id:
        return get_sample_label(batch_id, str(csv_path), include_batch=include_batch)
    return csv_path.stem


def add_processed_csv(processed_data, csv_path, label):
    if label in processed_data:
        label = f"{label} ({Path(csv_path).stem})"
    processed_data[label] = read_te_dataframe(csv_path)


def property_has_plottable_data(processed_data, property_key):
    spec = TE_PLOT_SPECS[property_key]
    column = spec["column"]

    for df in processed_data.values():
        if "Temperature" not in df.columns or column not in df.columns:
            continue
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        temperatures = pd.to_numeric(df["Temperature"], errors="coerce").dropna()
        if not values.empty and not temperatures.empty:
            return True

    return False


def resolve_single_property_keys(processed_data, property_keys=None):
    selected_keys = list(property_keys) if property_keys is not None else list(TE_PLOT_SPECS)
    available_keys = []

    for property_key in selected_keys:
        if property_has_plottable_data(processed_data, property_key):
            available_keys.append(property_key)
        else:
            print(f"⚠️ skip {property_key}: no plottable column found in selected data")

    return available_keys


def get_selected_processed_data(selectors, include_batch=False):
    processed_data = {}

    for raw_selector in selectors:
        path_matches = resolve_processed_path_selector(raw_selector)
        if path_matches:
            label_overrides = load_te_label_overrides(path_matches)
            for csv_path in path_matches:
                plot_label = label_overrides.get(
                    csv_path.resolve(),
                    get_path_sample_label(csv_path, include_batch=include_batch),
                )
                add_processed_csv(processed_data, csv_path, plot_label)
            continue

        if selector_is_definite_path(raw_selector):
            tried = ", ".join(str(path) for path in get_processed_path_aliases(raw_selector))
            print(f"⚠️ missing processed csv path for {raw_selector}. Tried: {tried}")
            continue

        for batch_id, sample_name, sample_info in resolve_sample_selectors([raw_selector]):
            csv_path = resolve_processed_csv_path(batch_id, sample_name, sample_info)
            if not csv_path:
                candidates = ", ".join(get_candidate_processed_paths(batch_id, sample_name, sample_info))
                print(f"⚠️ missing processed csv for {batch_id}/{sample_name}. Tried: {candidates}")
                continue

            plot_label = sample_info.get("sample_name") or sample_name
            if include_batch:
                plot_label = f"{batch_id}/{plot_label}"

            if plot_label in processed_data:
                plot_label = f"{plot_label} ({sample_info.get('sample_id', sample_name)})"

            add_processed_csv(processed_data, csv_path, plot_label)

    return processed_data


def get_selected_processed_paths(selectors):
    selected_paths = []

    for raw_selector in selectors:
        path_matches = resolve_processed_path_selector(raw_selector)
        if path_matches:
            selected_paths.extend(path_matches)
            continue

        if selector_is_definite_path(raw_selector):
            continue

        for batch_id, sample_name, sample_info in resolve_sample_selectors([raw_selector]):
            csv_path = resolve_processed_csv_path(batch_id, sample_name, sample_info)
            if csv_path:
                selected_paths.append(Path(csv_path))

    unique_paths = []
    seen = set()
    for path in selected_paths:
        key = str(Path(path).resolve())
        if key not in seen:
            unique_paths.append(Path(path))
            seen.add(key)

    return unique_paths


def resolve_te_data_figure_dir(selectors, folder_name="figures", comparison_id=None):
    processed_paths = get_selected_processed_paths(selectors)
    source_dirs = sorted({path.parent.resolve() for path in processed_paths})
    if not source_dirs:
        return None
    if len(source_dirs) == 1:
        return source_dirs[0] / folder_name

    common_dir = Path(os.path.commonpath([str(path) for path in source_dirs]))
    if comparison_id:
        return common_dir / folder_name / safe_selector_name(comparison_id)
    return common_dir / folder_name


def selectors_are_direct_file_inputs(selectors):
    if not selectors:
        return False

    for selector in selectors:
        if resolve_processed_path_selector(selector):
            continue
        if selector_is_path_like(selector):
            continue
        return False
    return True


def resolve_te_source_output_dir(selectors):
    if not selectors_are_direct_file_inputs(selectors):
        return None

    processed_paths = get_selected_processed_paths(selectors)
    source_dirs = sorted({path.parent.resolve() for path in processed_paths})
    if len(source_dirs) == 1:
        return source_dirs[0]
    return None


def get_path_selection_comparison_id(selectors, source_output_dir=None):
    processed_paths = get_selected_processed_paths(selectors)
    if len(processed_paths) == 1:
        return safe_selector_name(processed_paths[0].stem)

    if source_output_dir is not None:
        return safe_selector_name(Path(source_output_dir).name)

    return get_interbatch_comparison_id(selectors)


def load_batch_processed_data(batch_id, include_batch=False):
    batch_id = normalize_selector(batch_id)

    return get_selected_processed_data([batch_id], include_batch=include_batch)


def load_interbatch_processed_data(target_batches):
    return get_selected_processed_data(target_batches, include_batch=True)



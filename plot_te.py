import os
import glob
import json
import argparse
from pathlib import Path

_MPL_CACHE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "te_agent_matplotlib"
_MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(_MPL_CACHE_DIR))

import pandas as pd
from src.tools.plot import (
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_MARKER_SIZE,
    DEFAULT_SUBPLOT_ASPECT,
    TE_PLOT_SPECS,
    normalize_output_formats,
    parse_aspect_ratio,
    plot_combined_figure,
    plot_single_property,
)


PLOT_MODE_CHOICES = ("combined", "single", "both")
AUTO_LIMIT_VALUES = {"auto", "none", "null"}
DEFAULT_PLOT_MODE = "single"
TE_FIGURE_DIR = Path("outputs") / "figures" / "te"


def valid_property_list():
    return ", ".join(TE_PLOT_SPECS.keys())


def normalize_property_key(raw_property, option_name="property"):
    property_key = str(raw_property).strip().lower().replace("-", "_")
    aliases = {
        "electrical_conductivity": "conductivity",
        "sigma": "conductivity",
        "powerfactor": "power_factor",
        "pf": "power_factor",
        "thermal": "thermal_conductivity",
        "kappa": "thermal_conductivity",
        "lattice": "lattice_thermal_conductivity",
        "kappa_l": "lattice_thermal_conductivity",
        "rho": "resistivity",
    }
    property_key = aliases.get(property_key, property_key)

    if property_key not in TE_PLOT_SPECS:
        raise ValueError(
            f"{option_name} must be one of: {valid_property_list()}. "
            f"Got {raw_property!r}."
        )

    return property_key


def normalize_property_keys(property_keys, option_name="property"):
    if property_keys is None:
        return None

    selected_properties = []
    for raw_property in property_keys:
        property_key = normalize_property_key(raw_property, option_name)
        if property_key not in selected_properties:
            selected_properties.append(property_key)

    return selected_properties


def add_property_flag_arguments(parser):
    property_group = parser.add_argument_group("single-property shortcuts")

    for property_key, spec in TE_PLOT_SPECS.items():
        dashed_key = property_key.replace("_", "-")
        option_strings = [f"--{dashed_key}", f"-{dashed_key}"]
        if dashed_key != property_key:
            option_strings.extend([f"--{property_key}", f"-{property_key}"])

        property_group.add_argument(
            *option_strings,
            dest=f"plot_property_{property_key}",
            action="store_true",
            help=f"Plot the {spec['title']} single-property figure.",
        )


def get_property_flag_selection(args):
    selected_properties = []

    for property_key in TE_PLOT_SPECS:
        if getattr(args, f"plot_property_{property_key}", False):
            selected_properties.append(property_key)

    return selected_properties


def get_requested_single_properties(args):
    selected_properties = normalize_property_keys(
        args.single_properties,
        "--single-properties/--properties",
    ) or []

    for property_key in get_property_flag_selection(args):
        if property_key not in selected_properties:
            selected_properties.append(property_key)

    return selected_properties or None


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


def get_batch_plot_dir(batch_id):
    return str(TE_FIGURE_DIR / batch_id)


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


def parse_limit_bound(raw_value, option_name):
    clean_value = str(raw_value).strip()
    if clean_value.lower() in AUTO_LIMIT_VALUES:
        return None

    try:
        return float(clean_value)
    except ValueError as exc:
        raise ValueError(
            f"{option_name} limit {raw_value!r} must be a number or one of "
            f"{', '.join(sorted(AUTO_LIMIT_VALUES))}"
        ) from exc


def normalize_axis_limit_pair(raw_pair, option_name):
    if raw_pair is None:
        return None

    low = parse_limit_bound(raw_pair[0], option_name)
    high = parse_limit_bound(raw_pair[1], option_name)

    if low is None and high is None:
        return None
    if low is not None and high is not None and low >= high:
        raise ValueError(f"{option_name} lower limit must be smaller than upper limit")

    return (low, high)


def parse_property_ylims(raw_ylims, selected_properties=None):
    ylims = {}
    selected_properties = selected_properties or []

    for raw_ylim in raw_ylims or []:
        if len(raw_ylim) == 2:
            if len(selected_properties) != 1:
                raise ValueError(
                    "--ylim LOW HIGH can only be used when exactly one single "
                    "property is selected. Use --ylim PROPERTY LOW HIGH for "
                    "combined or multi-property plots."
                )
            property_key = selected_properties[0]
            low, high = raw_ylim
        elif len(raw_ylim) == 3:
            property_key, low, high = raw_ylim
            property_key = normalize_property_key(property_key, "--ylim property")
        else:
            raise ValueError(
                "--ylim expects either LOW HIGH or PROPERTY LOW HIGH. "
                "Examples: --seebeck --ylim -300 300, or "
                "--ylim seebeck -300 300."
            )

        limit_pair = normalize_axis_limit_pair((low, high), f"--ylim {property_key}")
        if limit_pair is not None:
            ylims[property_key] = limit_pair

    return ylims


def get_processed_csv_paths(batch_id):
    processed_dir = os.path.join("data", "processed", f"{batch_id}-processed")

    if not os.path.exists(processed_dir):
        print(f"⚠️ cannot find {processed_dir}, run_analysis.py before this step")
        return []

    processed_data = sorted(glob.glob(os.path.join(processed_dir, "*.csv")))

    if not processed_data:
        print(f"⚠️ no .csv in {processed_dir}, skip")

    return processed_data


def get_processed_dir(batch_id):
    return os.path.join("data", "processed", f"{batch_id}-processed")


def normalize_selector(selector):
    selector = selector.strip()
    if selector.startswith("Batch-"):
        selector = selector.replace("Batch-", "CHY-", 1)
    if selector.isdigit():
        selector = f"CHY-{selector}"
    elif selector and selector[0].isdigit():
        selector = f"CHY-{selector}"
    return selector


def safe_selector_name(selector):
    selector = str(selector).strip()
    selector = selector.replace(os.sep, "-").replace("/", "-").replace(":", "-").replace(" ", "_")
    selector = selector.replace("\\", "-")
    return selector.strip("-") or "selected_te"


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
        if candidate.is_file() and candidate.suffix.lower() == ".csv":
            matches.append(candidate)
        elif candidate.is_dir():
            matches.extend(sorted(candidate.glob("*.csv")))

    unique_matches = []
    seen = set()
    for match in matches:
        key = str(match.resolve())
        if key not in seen:
            unique_matches.append(match)
            seen.add(key)
    return unique_matches


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
    processed_data[label] = pd.read_csv(csv_path)


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
            for csv_path in path_matches:
                plot_label = get_path_sample_label(csv_path, include_batch=include_batch)
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


def load_batch_processed_data(batch_id, include_batch=False):
    batch_id = normalize_selector(batch_id)

    return get_selected_processed_data([batch_id], include_batch=include_batch)


def load_interbatch_processed_data(target_batches):
    return get_selected_processed_data(target_batches, include_batch=True)


def plot_combined_batch(
    processed_data,
    batch_id,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    marker_size=DEFAULT_MARKER_SIZE,
    show=False,
):
    save_name = f"{batch_id}_summary.png"
    save_dir = get_batch_plot_dir(batch_id)

    return plot_combined_figure(
        processed_data=processed_data,
        save_name=save_name,
        save_dir=save_dir,
        formats=formats,
        xlim=xlim,
        ylims=ylims,
        subplot_aspect=subplot_aspect,
        marker_size=marker_size,
        show=show,
    )


def plot_single_batch_properties(
    processed_data,
    batch_id,
    property_keys=None,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    single_legend="none",
    marker_size=DEFAULT_MARKER_SIZE,
    legend_font_size=DEFAULT_LEGEND_FONT_SIZE,
    show=False,
):
    property_keys = resolve_single_property_keys(processed_data, property_keys)
    if not property_keys:
        print(f"⚠️ no single-property plots available for {batch_id}")
        return []

    save_dir = get_single_plot_dir(batch_id)
    plot_paths = []

    for property_key in property_keys:
        save_name = f"{batch_id}_{property_key}.png"
        plot_path = plot_single_property(
            processed_data=processed_data,
            property_key=property_key,
            save_name=save_name,
            save_dir=save_dir,
            formats=formats,
            xlim=xlim,
            ylim=ylims.get(property_key) if ylims else None,
            subplot_aspect=subplot_aspect,
            legend=single_legend,
            marker_size=marker_size,
            legend_font_size=legend_font_size,
            show=show,
        )
        plot_paths.append(plot_path)

    return plot_paths


def plot_combined_interbatch(
    processed_data,
    comparison_id,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    marker_size=DEFAULT_MARKER_SIZE,
    show=False,
):
    save_name = f"{comparison_id}_summary.png"
    save_dir = get_interbatch_plot_dir(comparison_id)

    return plot_combined_figure(
        processed_data=processed_data,
        save_name=save_name,
        save_dir=save_dir,
        formats=formats,
        xlim=xlim,
        ylims=ylims,
        subplot_aspect=subplot_aspect,
        marker_size=marker_size,
        show=show,
    )


def plot_single_interbatch_properties(
    processed_data,
    comparison_id,
    property_keys=None,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    single_legend="none",
    marker_size=DEFAULT_MARKER_SIZE,
    legend_font_size=DEFAULT_LEGEND_FONT_SIZE,
    show=False,
):
    property_keys = resolve_single_property_keys(processed_data, property_keys)
    if not property_keys:
        print(f"⚠️ no single-property plots available for {comparison_id}")
        return []

    save_dir = get_interbatch_single_plot_dir(comparison_id)
    plot_paths = []

    for property_key in property_keys:
        save_name = f"{comparison_id}_{property_key}.png"
        plot_path = plot_single_property(
            processed_data=processed_data,
            property_key=property_key,
            save_name=save_name,
            save_dir=save_dir,
            formats=formats,
            xlim=xlim,
            ylim=ylims.get(property_key) if ylims else None,
            subplot_aspect=subplot_aspect,
            legend=single_legend,
            marker_size=marker_size,
            legend_font_size=legend_font_size,
            show=show,
        )
        plot_paths.append(plot_path)

    return plot_paths


def execute_interbatch_comparison(
    target_batches,
    plot_mode=DEFAULT_PLOT_MODE,
    single_properties=None,
    comparison_id=None,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    single_legend="none",
    marker_size=DEFAULT_MARKER_SIZE,
    legend_font_size=DEFAULT_LEGEND_FONT_SIZE,
    show=False,
):
    if plot_mode not in PLOT_MODE_CHOICES:
        raise ValueError(f"plot_mode must be one of {PLOT_MODE_CHOICES}, got {plot_mode!r}")

    comparison_id = comparison_id or get_interbatch_comparison_id(target_batches)
    processed_data = load_interbatch_processed_data(target_batches)

    if not processed_data:
        print("⚠️ no processed data found for inter-batch comparison")
        return

    print(f"\n{'='*50}")
    print(f"TE selection: {comparison_id}")
    print(f"✅ total {len(processed_data)} samples, now plotting")

    try:
        if plot_mode in ("combined", "both"):
            plot_path = plot_combined_interbatch(
                processed_data,
                comparison_id,
                formats=formats,
                xlim=xlim,
                ylims=ylims,
                subplot_aspect=subplot_aspect,
                marker_size=marker_size,
                show=show,
            )
            print(f"🎉 inter-batch combined plot saved to: {plot_path}")

        if plot_mode in ("single", "both"):
            plot_paths = plot_single_interbatch_properties(
                processed_data,
                comparison_id,
                property_keys=single_properties,
                formats=formats,
                xlim=xlim,
                ylims=ylims,
                subplot_aspect=subplot_aspect,
                single_legend=single_legend,
                marker_size=marker_size,
                legend_font_size=legend_font_size,
                show=show,
            )
            print(f"🎉 inter-batch single-property plots saved to: {get_interbatch_single_plot_dir(comparison_id)}")
            print(f"   total single plots: {len(plot_paths)}")
    except Exception as e:
        print(f"❌ error for inter-batch comparison {comparison_id}: {e}")


def execute_plot_batches(
    target_batches,
    plot_mode=DEFAULT_PLOT_MODE,
    single_properties=None,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    single_legend="none",
    marker_size=DEFAULT_MARKER_SIZE,
    legend_font_size=DEFAULT_LEGEND_FONT_SIZE,
    show=False,
):
    if not ALL_LAB_BATCHES:
        return

    if plot_mode not in PLOT_MODE_CHOICES:
        raise ValueError(f"plot_mode must be one of {PLOT_MODE_CHOICES}, got {plot_mode!r}")
    
    for raw_batch_id in target_batches:
        batch_id = normalize_selector(raw_batch_id)
        if batch_id in ALL_LAB_BATCHES:
            print(f"\n{'='*50}")
            print(f"{'='*50}")
            
            processed_data = load_batch_processed_data(batch_id)
            
            if not processed_data:
                continue
                
            print(f"✅ total {len(processed_data)} samples, now plotting")
            
            try:
                if plot_mode in ("combined", "both"):
                    plot_path = plot_combined_batch(
                        processed_data,
                        batch_id,
                        formats=formats,
                        xlim=xlim,
                        ylims=ylims,
                        subplot_aspect=subplot_aspect,
                        marker_size=marker_size,
                        show=show,
                    )
                    print(f"🎉 combined plot saved to: {plot_path}")

                if plot_mode in ("single", "both"):
                    plot_paths = plot_single_batch_properties(
                        processed_data,
                        batch_id,
                        property_keys=single_properties,
                        formats=formats,
                        xlim=xlim,
                        ylims=ylims,
                        subplot_aspect=subplot_aspect,
                        single_legend=single_legend,
                        marker_size=marker_size,
                        legend_font_size=legend_font_size,
                        show=show,
                    )
                    print(f"🎉 single-property plots saved to: {get_single_plot_dir(batch_id)}")
                    print(f"   total single plots: {len(plot_paths)}")
            except Exception as e:
                print(f"❌ error for {batch_id}: {e}")
                
        else:
            print(f"⚠️ missing {batch_id} JSON")


def parse_args():
    parser = argparse.ArgumentParser(description="Plot processed TE batch data.")
    parser.add_argument(
        "batches",
        nargs="*",
        help=(
            "Batch/sample/path selectors. Examples: CHY-1046 for all samples, "
            "CHY-1040-A for one sample, CHY-1040-Zn_dope_0.02 for one named "
            "sample, CHY-1046/Na_dope for one named sample, or a direct CSV/dir "
            "such as data/processed/CHY-1040/Zn_dope_0.02.csv."
        ),
    )
    parser.add_argument(
        "--plot-mode",
        choices=PLOT_MODE_CHOICES,
        default=None,
        help=(
            "Choose combined summary, single-property plots, or both. "
            f"Default: {DEFAULT_PLOT_MODE}."
        ),
    )
    parser.add_argument(
        "--single-properties",
        "--properties",
        nargs="+",
        metavar="PROPERTY",
        default=None,
        dest="single_properties",
        help="Optional subset of properties for single-property plotting.",
    )
    add_property_flag_arguments(parser)
    parser.add_argument(
        "--inter-batch",
        action="store_true",
        help=(
            "Plot samples from all selected batches together in one comparison. "
            "This is automatic for multiple selectors or any sample/path selector."
        ),
    )
    parser.add_argument(
        "--comparison-id",
        default=None,
        help="Optional folder and filename prefix for --inter-batch output.",
    )
    parser.add_argument(
        "--xlim",
        nargs=2,
        default=None,
        metavar=("LOW", "HIGH"),
        help=(
            "Shared temperature axis limits for all TE plots. "
            "Use 'auto' for an open bound, for example: --xlim 300 auto."
        ),
    )
    parser.add_argument(
        "--ylim",
        nargs="+",
        action="append",
        default=[],
        metavar="VALUE",
        help=(
            "Y-axis limits. Use --ylim LOW HIGH when exactly one property is "
            "selected, or --ylim PROPERTY LOW HIGH. Repeat to set multiple "
            "properties, for example: --ylim zt 0 1.2 --ylim seebeck -300 300."
        ),
    )
    parser.add_argument(
        "--subplot-aspect",
        default=DEFAULT_SUBPLOT_ASPECT,
        help=(
            "Width:height ratio for each plot frame, e.g. 10:8 or 1:1. "
            "Applies to single plots and each panel in combined plots."
        ),
    )
    parser.add_argument(
        "--single-legend",
        choices=("none", "inside", "outside"),
        default="none",
        help="Legend placement for single-property plots. Default: none.",
    )
    parser.add_argument(
        "--legend",
        dest="single_legend",
        action="store_const",
        const="inside",
        help="Add an inside legend to selected single-property plots.",
    )
    parser.add_argument(
        "--legend-font-size",
        type=float,
        default=DEFAULT_LEGEND_FONT_SIZE,
        help=(
            "Legend font size in points for single-property legends. "
            f"Default: {DEFAULT_LEGEND_FONT_SIZE}."
        ),
    )
    parser.add_argument(
        "--marker-size",
        type=float,
        default=DEFAULT_MARKER_SIZE,
        help="Marker size in points for both combined and single-property plots.",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["svg"],
        help="Output formats, for example: --formats svg png pdf.",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Also save vector PDF output in addition to the selected formats.",
    )
    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument(
        "--show",
        dest="show",
        action="store_true",
        default=True,
        help="Display each generated figure with matplotlib after saving. Default.",
    )
    display_group.add_argument(
        "--no-show",
        dest="show",
        action="store_false",
        help="Save figures without opening a matplotlib preview window.",
    )
    args = parser.parse_args()

    try:
        args.single_properties = get_requested_single_properties(args)
        args.xlim = normalize_axis_limit_pair(args.xlim, "--xlim")
        args.ylim = parse_property_ylims(
            args.ylim,
            selected_properties=args.single_properties,
        )
        parse_aspect_ratio(args.subplot_aspect)
        if args.marker_size <= 0:
            raise ValueError("--marker-size must be positive")
        if args.legend_font_size <= 0:
            raise ValueError("--legend-font-size must be positive")
    except ValueError as exc:
        parser.error(str(exc))

    return args

if __name__ == "__main__":
    
    # Select whole batches or individual samples:
    # "CHY-1046" means all samples in CHY-1046.
    # "CHY-1040-A" means only sample A from CHY-1040.
    # "CHY-1046/Na_dope" or "CHY-1046:Na_dope" means one named sample.
    my_targets = ["CHY-1048"]
    inter_batch = False  # set True to compare all my_targets in one plot
    
    args = parse_args()
    target_batches = args.batches or my_targets
    selected_plot_mode = args.plot_mode or DEFAULT_PLOT_MODE
    selected_formats = normalize_output_formats(args.formats, pdf=args.pdf)
    selected_xlim = args.xlim
    selected_ylims = args.ylim
    selected_subplot_aspect = args.subplot_aspect
    selected_single_legend = args.single_legend
    selected_marker_size = args.marker_size
    selected_legend_font_size = args.legend_font_size
    selected_show = args.show

    selected_inter_batch = (
        args.inter_batch
        or (inter_batch and not args.batches)
        or (args.batches and len(target_batches) > 1)
        or selectors_need_combined_view(target_batches)
    )

    if selected_inter_batch:
        execute_interbatch_comparison(
            target_batches,
            plot_mode=selected_plot_mode,
            single_properties=args.single_properties,
            comparison_id=args.comparison_id,
            formats=selected_formats,
            xlim=selected_xlim,
            ylims=selected_ylims,
            subplot_aspect=selected_subplot_aspect,
            single_legend=selected_single_legend,
            marker_size=selected_marker_size,
            legend_font_size=selected_legend_font_size,
            show=selected_show,
        )
    else:
        execute_plot_batches(
            target_batches,
            plot_mode=selected_plot_mode,
            single_properties=args.single_properties,
            formats=selected_formats,
            xlim=selected_xlim,
            ylims=selected_ylims,
            subplot_aspect=selected_subplot_aspect,
            single_legend=selected_single_legend,
            marker_size=selected_marker_size,
            legend_font_size=selected_legend_font_size,
            show=selected_show,
        )

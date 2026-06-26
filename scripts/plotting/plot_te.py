import os
import json
import argparse
import sys
import re
import csv
import hashlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
from src.tools.file_utils import copy_saved_figure_outputs


PLOT_MODE_CHOICES = ("combined", "single", "both")
AUTO_LIMIT_VALUES = {"auto", "none", "null"}
DEFAULT_PLOT_MODE = "single"
TE_FIGURE_DIR = Path("data") / "processed" / "figures"
TE_LABEL_FILE_STEMS = ("label", "labels", "legend", "legends")
TE_LABEL_FILE_SUFFIXES = ("", ".txt", ".csv", ".tsv", ".md")
PROPERTY_KEY_ALIASES = {
    "rho": "resistivity",
    "s": "seebeck",
    "electrical_conductivity": "conductivity",
    "sigma": "conductivity",
    "sig": "conductivity",
    "cond": "conductivity",
    "tc": "thermal_conductivity",
    "thermal": "thermal_conductivity",
    "kappa": "thermal_conductivity",
    "kt": "thermal_conductivity",
    "ktot": "thermal_conductivity",
    "kappa_total": "thermal_conductivity",
    "kappa_tot": "thermal_conductivity",
    "total_kappa": "thermal_conductivity",
    "diff": "diffusivity",
    "alpha": "diffusivity",
    "ke": "carrier_thermal_conductivity",
    "k_e": "carrier_thermal_conductivity",
    "kappa_e": "carrier_thermal_conductivity",
    "carrier": "carrier_thermal_conductivity",
    "carrier_kappa": "carrier_thermal_conductivity",
    "electronic_kappa": "carrier_thermal_conductivity",
    "kl": "lattice_thermal_conductivity",
    "k_l": "lattice_thermal_conductivity",
    "kappa_l": "lattice_thermal_conductivity",
    "lattice": "lattice_thermal_conductivity",
    "kappa_lattice": "lattice_thermal_conductivity",
    "lattice_kappa": "lattice_thermal_conductivity",
    "lorenz": "lorenz_number",
    "eta": "generalized_fermi_level",
    "muw": "weighted_mobility",
    "mu_w": "weighted_mobility",
    "weighted_mu": "weighted_mobility",
    "b": "quality_factor",
    "qb": "quality_factor",
    "powerfactor": "power_factor",
    "pf": "power_factor",
}
PROPERTY_FLAG_ALIASES = {
    "resistivity": ("rho",),
    "seebeck": ("s",),
    "conductivity": ("sigma", "cond"),
    "thermal_conductivity": ("kappa", "kt", "ktot", "tc"),
    "diffusivity": ("diff", "alpha"),
    "carrier_thermal_conductivity": ("ke", "kappa-e"),
    "lattice_thermal_conductivity": ("kl", "kappa-l", "lattice"),
    "lorenz_number": ("lorenz",),
    "generalized_fermi_level": ("eta",),
    "weighted_mobility": ("muw", "mu-w"),
    "quality_factor": ("b",),
    "power_factor": ("pf",),
}


def valid_property_list():
    return ", ".join(TE_PLOT_SPECS.keys())


def normalize_property_key(raw_property, option_name="property"):
    property_key = str(raw_property).strip().lower().replace("-", "_")
    property_key = PROPERTY_KEY_ALIASES.get(property_key, property_key)

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


def normalize_column_token(column_name):
    text = str(column_name).strip().lower()
    text = (
        text.replace("µ", "u")
        .replace("μ", "u")
        .replace("κ", "kappa")
        .replace("σ", "sigma")
        .replace("ρ", "rho")
    )
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def build_te_column_aliases():
    aliases = {
        "Temperature": [
            "temperature",
            "temp",
            "t",
            "temperaturek",
            "tk",
        ],
        "Resistivity": [
            "resistivity",
            "electrical resistivity",
            "rho",
        ],
        "Seebeck": [
            "seebeck",
            "seebeck coefficient",
            "s",
        ],
        "Conductivity": [
            "conductivity",
            "electrical conductivity",
            "sigma",
        ],
        "Thermal_Conductivity": [
            "thermal conductivity",
            "total thermal conductivity",
            "kappa",
            "kappa total",
            "kappa tot",
        ],
        "Diffusivity": [
            "diffusivity",
            "thermal diffusivity",
        ],
        "Carrier_Thermal_Conductivity": [
            "carrier thermal conductivity",
            "electronic thermal conductivity",
            "kappa e",
            "kappa electronic",
        ],
        "Lattice_Thermal_Conductivity": [
            "lattice thermal conductivity",
            "kappa l",
            "kappa lattice",
        ],
        "Lorenz_Number_1e-8_WOhmK-2": [
            "lorenz number",
            "lorenz",
            "l",
        ],
        "Generalized_Fermi_Level": [
            "generalized fermi level",
            "fermi level",
            "eta",
        ],
        "Weighted_Mobility_cm2_V-1_s-1": [
            "weighted mobility",
            "mu w",
            "muw",
        ],
        "Quality_Factor_B": [
            "quality factor",
            "quality factor b",
            "b",
        ],
        "ZT": [
            "zt",
            "z t",
        ],
        "Power_Factor": [
            "power factor",
            "powerfactor",
            "pf",
        ],
    }

    for property_key, spec in TE_PLOT_SPECS.items():
        canonical_column = spec["column"]
        aliases.setdefault(canonical_column, [])
        aliases[canonical_column].extend([canonical_column, property_key])

    alias_map = {}
    for canonical_column, raw_aliases in aliases.items():
        alias_map[normalize_column_token(canonical_column)] = canonical_column
        for raw_alias in raw_aliases:
            alias_map[normalize_column_token(raw_alias)] = canonical_column

    return alias_map


TE_COLUMN_ALIASES = build_te_column_aliases()


def standardize_te_dataframe_columns(df, csv_path=None):
    """
    Normalize copied/hand-curated TE CSVs to the processed-data column contract.

    Direct inter-batch folders are often assembled by copying selected CSVs into
    one place. In that workflow the first column is treated as temperature even
    when it is named "T", "Temp (K)", or similar.
    """
    if df.empty or len(df.columns) == 0:
        return df

    standardized = df.copy()
    first_column = standardized.columns[0]
    standardized["Temperature"] = pd.to_numeric(standardized[first_column], errors="coerce")

    for column in list(standardized.columns):
        canonical_column = TE_COLUMN_ALIASES.get(normalize_column_token(column))
        if not canonical_column or canonical_column == "Temperature":
            continue
        if canonical_column not in standardized.columns:
            standardized[canonical_column] = pd.to_numeric(standardized[column], errors="coerce")

    return standardized


def add_property_flag_arguments(parser):
    property_group = parser.add_argument_group("single-property shortcuts")

    for property_key, spec in TE_PLOT_SPECS.items():
        dashed_key = property_key.replace("_", "-")
        option_strings = [f"--{dashed_key}", f"-{dashed_key}"]
        if dashed_key != property_key:
            option_strings.extend([f"--{property_key}", f"-{property_key}"])
        seen_options = set(option_strings)
        for alias in PROPERTY_FLAG_ALIASES.get(property_key, ()):
            alias_variants = {
                alias,
                alias.replace("_", "-"),
                alias.replace("-", "_"),
            }
            for alias_variant in sorted(alias_variants):
                if not alias_variant:
                    continue
                for prefix in ("--", "-"):
                    option_string = f"{prefix}{alias_variant}"
                    if option_string not in seen_options:
                        option_strings.append(option_string)
                        seen_options.add(option_string)

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


def normalize_selector(selector):
    selector = selector.strip()
    if selector.startswith("Batch-"):
        selector = selector.replace("Batch-", "CHY-", 1)
    if selector.isdigit():
        selector = f"CHY-{selector}"
    elif selector and selector[0].isdigit():
        selector = f"CHY-{selector}"
    short_sample_match = re.fullmatch(r"(CHY-\d+)([A-Za-z](?:-.+)?)", selector)
    if short_sample_match:
        batch_id, sample_suffix = short_sample_match.groups()
        selector = f"{batch_id}-{sample_suffix[:1].upper()}{sample_suffix[1:]}"
    return selector


def safe_selector_name(selector, max_length=96):
    raw_selector = str(selector)
    selector = raw_selector.strip()
    selector = selector.replace(os.sep, "-").replace("/", "-").replace(":", "-").replace(" ", "_")
    selector = selector.replace("\\", "-")
    selector = selector.strip("-") or "selected_te"
    if len(selector) <= max_length:
        return selector
    digest = hashlib.sha1(selector.encode("utf-8")).hexdigest()[:8]
    prefix_length = max(1, max_length - len(digest) - 1)
    return f"{selector[:prefix_length].rstrip('_.-')}_{digest}"


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


def plot_combined_batch(
    processed_data,
    batch_id,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    marker_size=DEFAULT_MARKER_SIZE,
    legend_columns=None,
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
        legend_columns=legend_columns,
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
    legend_columns=None,
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
            legend_columns=legend_columns,
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
    legend_columns=None,
    save_dir=None,
    show=False,
):
    save_name = f"{comparison_id}_summary.png"
    save_dir = save_dir or get_interbatch_plot_dir(comparison_id)

    return plot_combined_figure(
        processed_data=processed_data,
        save_name=save_name,
        save_dir=save_dir,
        formats=formats,
        xlim=xlim,
        ylims=ylims,
        subplot_aspect=subplot_aspect,
        marker_size=marker_size,
        legend_columns=legend_columns,
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
    legend_columns=None,
    save_dir=None,
    show=False,
):
    property_keys = resolve_single_property_keys(processed_data, property_keys)
    if not property_keys:
        print(f"⚠️ no single-property plots available for {comparison_id}")
        return []

    save_dir = save_dir or get_interbatch_single_plot_dir(comparison_id)
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
            legend_columns=legend_columns,
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
    legend_columns=None,
    data_figures=False,
    data_figures_dir="figures",
    output_dir=None,
    show=False,
):
    if plot_mode not in PLOT_MODE_CHOICES:
        raise ValueError(f"plot_mode must be one of {PLOT_MODE_CHOICES}, got {plot_mode!r}")

    comparison_id = comparison_id or get_interbatch_comparison_id(target_batches)
    processed_data = load_interbatch_processed_data(target_batches)
    output_dir = Path(output_dir) if output_dir is not None else None
    data_figure_dir = (
        resolve_te_data_figure_dir(target_batches, data_figures_dir, comparison_id)
        if data_figures
        else None
    )

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
                legend_columns=legend_columns,
                save_dir=output_dir,
                show=show,
            )
            print(f"🎉 inter-batch combined plot saved to: {plot_path}")
            if data_figure_dir is not None:
                copied_paths = copy_saved_figure_outputs(plot_path, data_figure_dir, formats=formats)
                if copied_paths:
                    print(f"   copied data figures to: {data_figure_dir}")

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
                legend_columns=legend_columns,
                save_dir=output_dir,
                show=show,
            )
            single_save_dir = output_dir or get_interbatch_single_plot_dir(comparison_id)
            print(f"🎉 inter-batch single-property plots saved to: {single_save_dir}")
            print(f"   total single plots: {len(plot_paths)}")
            if data_figure_dir is not None:
                copied_paths = copy_saved_figure_outputs(plot_paths, data_figure_dir, formats=formats)
                if copied_paths:
                    print(f"   copied data figures to: {data_figure_dir}")
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
    legend_columns=None,
    data_figures=False,
    data_figures_dir="figures",
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
            data_figure_dir = Path(get_processed_dir(batch_id)) / data_figures_dir if data_figures else None
            
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
                        legend_columns=legend_columns,
                        show=show,
                    )
                    print(f"🎉 combined plot saved to: {plot_path}")
                    if data_figure_dir is not None:
                        copied_paths = copy_saved_figure_outputs(plot_path, data_figure_dir, formats=formats)
                        if copied_paths:
                            print(f"   copied data figures to: {data_figure_dir}")

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
                        legend_columns=legend_columns,
                        show=show,
                    )
                    print(f"🎉 single-property plots saved to: {get_single_plot_dir(batch_id)}")
                    print(f"   total single plots: {len(plot_paths)}")
                    if data_figure_dir is not None:
                        copied_paths = copy_saved_figure_outputs(plot_paths, data_figure_dir, formats=formats)
                        if copied_paths:
                            print(f"   copied data figures to: {data_figure_dir}")
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
        "--legend-columns",
        "--legend-cols",
        "--legend-ncol",
        type=int,
        default=None,
        help=(
            "Number of legend columns for single-property and combined plots. "
            "Default: automatic."
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
        "--data-figures",
        "--save-near-data",
        action="store_true",
        help="Also copy saved figures into a figures folder beside the processed data.",
    )
    parser.add_argument(
        "--data-figures-dir",
        default="figures",
        help="Folder name for --data-figures copies. Default: figures.",
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
        if args.legend_columns is not None and args.legend_columns <= 0:
            raise ValueError("--legend-columns must be a positive integer")
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
    selected_legend_columns = args.legend_columns
    selected_show = args.show
    selected_data_figures = args.data_figures
    selected_data_figures_dir = args.data_figures_dir
    selected_comparison_id = args.comparison_id

    selected_inter_batch = (
        args.inter_batch
        or (inter_batch and not args.batches)
        or (args.batches and len(target_batches) > 1)
        or selectors_need_combined_view(target_batches)
    )
    selected_output_dir = None
    if selected_inter_batch:
        source_output_dir = resolve_te_source_output_dir(target_batches)
        if selected_comparison_id is None and source_output_dir is not None:
            selected_comparison_id = get_path_selection_comparison_id(
                target_batches,
                source_output_dir=source_output_dir,
            )
        if selected_comparison_id is None:
            selected_comparison_id = get_interbatch_comparison_id(target_batches)
        selected_output_dir = resolve_te_data_figure_dir(
            target_batches,
            selected_data_figures_dir,
            selected_comparison_id,
        )

    if selected_inter_batch:
        execute_interbatch_comparison(
            target_batches,
            plot_mode=selected_plot_mode,
            single_properties=args.single_properties,
            comparison_id=selected_comparison_id,
            formats=selected_formats,
            xlim=selected_xlim,
            ylims=selected_ylims,
            subplot_aspect=selected_subplot_aspect,
            single_legend=selected_single_legend,
            marker_size=selected_marker_size,
            legend_font_size=selected_legend_font_size,
            legend_columns=selected_legend_columns,
            data_figures=selected_data_figures,
            data_figures_dir=selected_data_figures_dir,
            output_dir=selected_output_dir,
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
            legend_columns=selected_legend_columns,
            data_figures=selected_data_figures,
            data_figures_dir=selected_data_figures_dir,
            show=selected_show,
        )

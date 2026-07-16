"""XRD pattern loading: .xy files, labels, file discovery, selectors.

Split verbatim from plot_xrd_data.py; behavior unchanged.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from itertools import cycle
from pathlib import Path
from typing import Iterable, Sequence

from te_analysis.tools.matplotlib_backend import configure_matplotlib_backend

configure_matplotlib_backend()

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from te_analysis.tools.selectors import (
    normalize_batch_id as normalize_batch_selector,
    truncate_with_digest,
)
from te_analysis.tools.plot import (
    DEFAULT_COLORS,
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_SUBPLOT_ASPECT,
    DEFAULT_SUBPLOT_HEIGHT,
    apply_plot_style,
    apply_subplot_aspect,
    figure_size_for_subplot_aspect,
    format_te_axis,
    save_figure,
)



DEFAULT_XRD_ROOT = Path("data/raw")
XRD_LABEL_FILE_STEMS = ("label", "labels", "legend", "legends")
XRD_LABEL_FILE_SUFFIXES = ("", ".txt", ".csv", ".tsv", ".md")
@dataclass(frozen=True)
class XRDPattern:
    label: str
    two_theta: np.ndarray
    intensity: np.ndarray
    source_path: Path
    batch_id: str = ""
    sample_id: str = ""
    sample_name: str = ""
    wavelength_angstrom: float | None = None
    label_from_file: bool = False


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default



def safe_filename(value: str, max_length: int = 96) -> str:
    raw_value = str(value)
    value = re.sub(r"[^\w.\-]+", "_", raw_value.strip())
    value = re.sub(r"_+", "_", value).strip("_") or "xrd_comparison"
    return truncate_with_digest(value, max_length)


def infer_batch_id_from_path(path: Path, xrd_root: Path = DEFAULT_XRD_ROOT) -> str:
    try:
        relative = path.resolve().relative_to(xrd_root.resolve())
    except ValueError:
        parts = path.parts
        return next((part for part in parts if re.match(r"CHY-\d+", part)), "")
    return relative.parts[0] if relative.parts else ""


def infer_sample_id_from_xrd_path(path: Path) -> str:
    stem = path.stem
    sample_match = re.match(r"^((?:CHY-)?\d{3,5}-[A-Za-z0-9]+)", stem, flags=re.IGNORECASE)
    if sample_match:
        return sample_match.group(1)
    stem = re.sub(r"[_\-]?(XRD|Theta[_\-]?2[_\-]?Theta|Theta[_\-]?2Theta)$", "", stem, flags=re.IGNORECASE)
    return stem


def load_sample_metadata(
    samples_path: str | os.PathLike[str] = "data/lab/samples.json",
    legacy_batches_path: str | os.PathLike[str] = "configs/lab_batches.json",
) -> dict[str, dict[str, str]]:
    """
    Return sample_id -> metadata for labeling XRD traces.

    The newer flat lab ledger is preferred, while the older batch JSON remains
    supported so this plotter follows the same labels used by the TE plots.
    """
    lookup: dict[str, dict[str, str]] = {}

    for sample in _read_json(Path(samples_path), []):
        sample_id = sample.get("sample_id")
        if not sample_id:
            continue
        lookup[sample_id] = {
            "batch_id": sample.get("batch_id", ""),
            "sample_name": sample.get("sample_name") or sample_id,
            "sample_composition": sample.get("sample_composition", ""),
        }

    legacy_batches = _read_json(Path(legacy_batches_path), {})
    for batch_id, batch_entry in legacy_batches.items():
        if not isinstance(batch_entry, dict):
            continue
        for sample_name, sample_info in batch_entry.items():
            if sample_name == "batch_metadata" or not isinstance(sample_info, dict):
                continue
            sample_id = sample_info.get("sample_id")
            if not sample_id or sample_id in lookup:
                continue
            lookup[sample_id] = {
                "batch_id": batch_id,
                "sample_name": sample_name,
                "sample_composition": sample_info.get("sample_composition", ""),
            }

    return lookup


def read_xrd_xy(path: str | os.PathLike[str]) -> tuple[np.ndarray, np.ndarray, float | None]:
    """
    Read a two-column XRD .xy file.

    Header lines are ignored. A line containing ``Wavelength = ...`` is captured
    when present, and numeric columns may be separated by spaces, commas, or tabs.
    """
    two_theta: list[float] = []
    intensity: list[float] = []
    wavelength = None

    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue

            wavelength_match = re.search(r"Wavelength\s*=\s*([0-9.]+)", stripped)
            if wavelength_match:
                wavelength = float(wavelength_match.group(1))
                continue

            parts = stripped.replace(",", " ").split()
            if len(parts) < 2:
                continue
            try:
                two_theta.append(float(parts[0]))
                intensity.append(float(parts[1]))
            except ValueError:
                continue

    if not two_theta:
        raise ValueError(f"No numeric XRD data found in {path}")

    order = np.argsort(two_theta)
    return np.asarray(two_theta)[order], np.asarray(intensity)[order], wavelength


def find_xrd_label_file(xrd_dir: str | os.PathLike[str]) -> Path | None:
    """
    Return the first label/legend file found in an XRD folder.

    Supported names are label, labels, legend, and legends, with optional
    .txt/.csv/.tsv/.md suffixes.
    """
    directory = Path(xrd_dir)
    for stem in XRD_LABEL_FILE_STEMS:
        for suffix in XRD_LABEL_FILE_SUFFIXES:
            candidate = directory / f"{stem}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def read_xrd_labels(path: str | os.PathLike[str]) -> list[str]:
    """
    Read one-column XRD legend labels from a text, CSV, or TSV file.

    Empty rows and rows whose first non-space character is # are ignored. CSV
    and TSV files use their first column; plain-text files use one label per
    line so Matplotlib mathtext strings such as $\\mathit{CuSbTe_2}$ are kept
    intact.
    """
    path = Path(path)
    labels: list[str] = []
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


def load_xrd_label_overrides(xrd_files: Sequence[Path]) -> dict[Path, str]:
    """
    Map XRD files to labels from label/legend files in the same folder.

    Labels are assigned in the same sorted order used for XRD file discovery.
    If the label count does not match the number of .xy files in that folder,
    available labels are still applied to the first files and a warning is
    printed.
    """
    overrides: dict[Path, str] = {}
    grouped_dirs = sorted({Path(path).parent for path in xrd_files})

    for xrd_dir in grouped_dirs:
        label_file = find_xrd_label_file(xrd_dir)
        if label_file is None:
            continue

        labels = read_xrd_labels(label_file)
        directory_files = sorted(xrd_dir.glob("*.xy"))
        if len(labels) != len(directory_files):
            print(
                f"warning: {label_file} has {len(labels)} labels for "
                f"{len(directory_files)} XRD files; applying labels by sorted file order."
            )

        for path, label in zip(directory_files, labels):
            overrides[path.resolve()] = label

    return overrides


def find_xrd_files_for_selector(
    selector: str,
    xrd_root: str | os.PathLike[str] = DEFAULT_XRD_ROOT,
) -> list[Path]:
    root = Path(xrd_root)
    selector = normalize_batch_selector(selector)
    selector_path = Path(selector)

    if selector_path.exists() and selector_path.is_file():
        return [selector_path]
    if selector_path.exists() and selector_path.is_dir():
        return sorted(selector_path.rglob("*.xy"))

    batch_xrd_dir = root / selector / "XRD"
    if batch_xrd_dir.exists():
        return sorted(batch_xrd_dir.glob("*.xy"))

    all_xrd_files = sorted(root.glob("*/XRD/*.xy"))
    metadata = load_sample_metadata()
    matches = []
    for path in all_xrd_files:
        batch_id = infer_batch_id_from_path(path, root)
        sample_id = infer_sample_id_from_xrd_path(path)
        sample_name = metadata.get(sample_id, {}).get("sample_name", "")
        identifiers = {
            batch_id,
            sample_id,
            sample_name,
            f"{batch_id}/{sample_id}",
            f"{batch_id}:{sample_id}",
            f"{batch_id}/{sample_name}",
            f"{batch_id}:{sample_name}",
            path.stem,
            path.name,
        }
        if selector in identifiers:
            matches.append(path)

    return matches


def collect_xrd_files(
    selectors: Sequence[str] | None = None,
    xrd_root: str | os.PathLike[str] = DEFAULT_XRD_ROOT,
) -> list[Path]:
    root = Path(xrd_root)
    selectors = list(selectors or [])

    if not selectors:
        files = sorted(root.glob("*/XRD/*.xy"))
    else:
        files = []
        for selector in selectors:
            selector_files = find_xrd_files_for_selector(selector, root)
            if not selector_files:
                print(f"warning: no .xy XRD file found for selector {selector!r}")
            files.extend(selector_files)

    unique_files: list[Path] = []
    seen = set()
    for path in files:
        key = str(path.resolve())
        if key not in seen:
            unique_files.append(path)
            seen.add(key)
    return unique_files


def _split_selector_terms(selectors: Sequence[str] | None) -> list[str]:
    terms: list[str] = []
    for selector in selectors or []:
        terms.extend(part.strip() for part in str(selector).split(",") if part.strip())
    return terms


def _pattern_identifier_values(pattern: XRDPattern) -> set[str]:
    suffix = ""
    if pattern.batch_id and pattern.sample_id.startswith(f"{pattern.batch_id}-"):
        suffix = pattern.sample_id[len(pattern.batch_id) + 1 :]
    elif "-" in pattern.sample_id:
        suffix = pattern.sample_id.rsplit("-", 1)[-1]

    values = {
        pattern.label,
        pattern.batch_id,
        pattern.sample_id,
        pattern.sample_name,
        suffix,
        pattern.source_path.stem,
        pattern.source_path.name,
        str(pattern.source_path),
    }
    return {value for value in values if value}


def pattern_matches_selector(pattern: XRDPattern, selector: str) -> bool:
    """
    Match a loaded XRD pattern against a compact sample selector.

    Exact identifiers and shell-style globs are always supported. For longer
    selectors, substring matching is also useful for composition labels such as
    ``CdSe_0.02``.
    """
    selector = normalize_batch_selector(selector.strip())
    if not selector:
        return False

    selector_lower = selector.lower()
    identifiers = _pattern_identifier_values(pattern)
    identifier_lowers = {value.lower() for value in identifiers}

    if selector_lower in identifier_lowers:
        return True

    if any(fnmatchcase(value.lower(), selector_lower) for value in identifiers):
        return True

    return len(selector_lower) >= 3 and any(selector_lower in value for value in identifier_lowers)


def filter_xrd_patterns(
    patterns: Sequence[XRDPattern],
    selectors: Sequence[str] | None = None,
) -> tuple[list[XRDPattern], list[str]]:
    terms = _split_selector_terms(selectors)
    if not terms:
        return list(patterns), []

    selected: list[XRDPattern] = []
    matched_terms: set[str] = set()
    for pattern in patterns:
        pattern_matches = [term for term in terms if pattern_matches_selector(pattern, term)]
        if pattern_matches:
            selected.append(pattern)
            matched_terms.update(pattern_matches)

    missing_terms = [term for term in terms if term not in matched_terms]
    return selected, missing_terms


def load_xrd_patterns(
    selectors: Sequence[str] | None = None,
    xrd_root: str | os.PathLike[str] = DEFAULT_XRD_ROOT,
    include_batch: bool | None = None,
) -> list[XRDPattern]:
    xrd_root = Path(xrd_root)
    xrd_files = collect_xrd_files(selectors, xrd_root)
    metadata = load_sample_metadata()
    label_overrides = load_xrd_label_overrides(xrd_files)

    batch_count = len({infer_batch_id_from_path(path, xrd_root) for path in xrd_files})
    if include_batch is None:
        include_batch = batch_count > 1

    patterns = []
    for path in xrd_files:
        two_theta, intensity, wavelength = read_xrd_xy(path)
        batch_id = infer_batch_id_from_path(path, xrd_root)
        sample_id = infer_sample_id_from_xrd_path(path)
        sample_meta = metadata.get(sample_id, {})
        sample_name = sample_meta.get("sample_name") or sample_id
        label_override = label_overrides.get(path.resolve())
        label = label_override or format_xrd_pattern_label(
            batch_id,
            sample_id,
            sample_name,
            include_batch=include_batch,
        )
        patterns.append(
            XRDPattern(
                label=label,
                two_theta=two_theta,
                intensity=intensity,
                source_path=path,
                batch_id=batch_id,
                sample_id=sample_id,
                sample_name=sample_name,
                wavelength_angstrom=wavelength,
                label_from_file=label_override is not None,
            )
        )

    return patterns


def format_xrd_pattern_label(
    batch_id: str,
    sample_id: str,
    sample_name: str = "",
    include_batch: bool | None = None,
) -> str:
    """
    Return a compact legend label using batch + sample id, e.g. CHY-1048-A.
    """
    if sample_id:
        if batch_id and not sample_id.startswith(f"{batch_id}-"):
            batch_number = batch_id.replace("CHY-", "", 1)
            if sample_id.startswith(f"{batch_number}-"):
                return f"{batch_id}-{sample_id[len(batch_number) + 1:]}"
            return f"{batch_id}-{sample_id}"
        return sample_id

    if sample_name:
        if batch_id and include_batch is not False:
            return f"{batch_id}-{sample_name}"
        return sample_name

    return batch_id or "xrd_pattern"


def right_xrd_pattern_label(pattern: XRDPattern) -> str:
    """
    Return the label used for right-side trace annotations.

    Label/legend files should drive right labels just like the external legend.
    Without a label file, the file stem is the most explicit fallback.
    """
    if pattern.label_from_file:
        return pattern.label
    return pattern.source_path.stem or pattern.label



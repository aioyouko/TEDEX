from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from itertools import cycle
from pathlib import Path
from typing import Iterable, Sequence

from src.tools.matplotlib_backend import configure_matplotlib_backend

configure_matplotlib_backend()

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    from src.tools.plot import (
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
except ImportError:  # pragma: no cover - lets this file run outside the repo package.
    DEFAULT_COLORS = [
        "#d62728",
        "#1f77b4",
        "#2ca02c",
        "#9467bd",
        "#ff7f0e",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#17becf",
    ]
    DEFAULT_LEGEND_FONT_SIZE = 7.5
    DEFAULT_SUBPLOT_ASPECT = "10:8"
    DEFAULT_SUBPLOT_HEIGHT = 2.65

    def apply_plot_style(font="arial", mode="single"):
        plt.rcParams.update(
            {
                "font.sans-serif": "Arial" if font == "arial" else "Times New Roman",
                "axes.linewidth": 1,
                "axes.labelsize": 14,
                "xtick.direction": "in",
                "ytick.direction": "in",
                "xtick.minor.visible": True,
                "ytick.minor.visible": True,
                "legend.frameon": False,
                "savefig.dpi": 300,
                "savefig.bbox": "tight",
            }
        )

    def format_te_axis(ax, show_grid=False, tick_labelsize=11):
        ax.minorticks_on()
        ax.tick_params(which="both", direction="in", top=False, right=False)
        ax.tick_params(which="major", width=1, length=6, labelsize=tick_labelsize)
        ax.tick_params(which="minor", width=1, length=4)
        ax.grid(show_grid, which="major", linestyle="--", linewidth=0.5, alpha=0.5)

    def save_figure(fig, save_name, save_dir="outputs/figures", formats=None, transparent=False):
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        formats = formats or [Path(save_name).suffix.lstrip(".") or "png"]
        base_name = Path(save_name).stem
        first_path = None
        for file_format in formats:
            path = Path(save_dir) / f"{base_name}.{file_format}"
            fig.savefig(path, dpi=300, bbox_inches="tight", transparent=transparent)
            first_path = first_path or str(path)
        return first_path

    def figure_size_for_subplot_aspect(aspect=DEFAULT_SUBPLOT_ASPECT, ncols=1, nrows=1, subplot_height=DEFAULT_SUBPLOT_HEIGHT):
        width, height = str(aspect).replace("x", ":").split(":", 1)
        return (subplot_height * float(width) / float(height) * ncols, subplot_height * nrows)

    def apply_subplot_aspect(ax, aspect=DEFAULT_SUBPLOT_ASPECT):
        width, height = str(aspect).replace("x", ":").split(":", 1)
        if hasattr(ax, "set_box_aspect"):
            ax.set_box_aspect(float(height) / float(width))


DEFAULT_XRD_ROOT = Path("data/raw")
DEFAULT_PDF_CARD_DIR = Path("data/pdf_card")
DEFAULT_PDF_STANDARD_DIR = DEFAULT_PDF_CARD_DIR / "plot_standards"
DEFAULT_XRD_SAVE_DIR = Path("outputs/figures/xrd")
DEFAULT_TWO_THETA_RANGE = (10.0, 80.0)
DEFAULT_XRD_LINE_WIDTH = 1.15
PDF_PEAK_PATTERN = re.compile(
    r"^\s*([0-9.]+)\s+([0-9.]+)\s+(\S+)\s+"
    r"\(\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\)"
)


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


@dataclass(frozen=True)
class PDFStandard:
    label: str
    peaks: pd.DataFrame
    source_path: Path


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def normalize_batch_selector(selector: str) -> str:
    selector = selector.strip()
    if selector.startswith("Batch-"):
        return selector.replace("Batch-", "CHY-", 1)
    if selector.isdigit() or (selector and selector[0].isdigit()):
        return f"CHY-{selector}"
    return selector


def safe_filename(value: str) -> str:
    value = re.sub(r"[^\w.\-]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "xrd_comparison"


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
        label = format_xrd_pattern_label(batch_id, sample_id, sample_name, include_batch=include_batch)
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


def _parse_intensity(value: str) -> float:
    value = str(value).strip()
    if not value:
        return math.nan
    if value.startswith("<"):
        try:
            return 0.5 * float(value[1:])
        except ValueError:
            return 0.5
    try:
        return float(value)
    except ValueError:
        return math.nan


def _parse_pdf_label(path: Path, lines: Sequence[str]) -> str:
    pdf_match = re.search(r"PDF#([^:\s]+)", lines[0] if lines else "")
    pdf_id = pdf_match.group(1).strip() if pdf_match else ""
    formula = ""
    for line in lines[1:5]:
        stripped = line.strip()
        if stripped and not stripped.startswith(("Radiation=", "Calibration=", "Ref:")):
            formula = stripped
    if formula and pdf_id:
        return f"{formula} PDF#{pdf_id}"
    return path.stem.replace("_", " ")


def read_pdf_card_text(path: str | os.PathLike[str]) -> PDFStandard:
    path = Path(path)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows = []

    for line in lines:
        match = PDF_PEAK_PATTERN.match(line)
        if not match:
            continue
        rows.append(
            {
                "two_theta_deg": float(match.group(1)),
                "d_angstrom": float(match.group(2)),
                "intensity": _parse_intensity(match.group(3)),
                "intensity_text": match.group(3),
                "h": int(match.group(4)),
                "k": int(match.group(5)),
                "l": int(match.group(6)),
            }
        )

    if not rows:
        raise ValueError(f"No PDF peak table found in {path}")

    return PDFStandard(
        label=_parse_pdf_label(path, lines),
        peaks=pd.DataFrame(rows),
        source_path=path,
    )


def read_pdf_peak_csv(path: str | os.PathLike[str]) -> PDFStandard:
    path = Path(path)
    df = pd.read_csv(path)
    column_lookup = {_normalize_column_name(column): column for column in df.columns}
    two_theta_column = _find_column(
        column_lookup,
        aliases=("two_theta_deg", "two_theta", "twotheta", "2theta", "2theta_deg", "2-theta", "2-theta_deg"),
    )
    intensity_column = _find_column(
        column_lookup,
        aliases=("intensity", "relative_intensity", "rel_intensity", "i", "i_rel", "height"),
    )

    if two_theta_column is None or intensity_column is None:
        raise ValueError(
            f"{path} must include 2-theta and intensity columns. "
            "Recommended columns: two_theta_deg,intensity,label"
        )

    peaks = pd.DataFrame(
        {
            "two_theta_deg": pd.to_numeric(df[two_theta_column], errors="coerce"),
            "intensity": df[intensity_column].map(_parse_intensity),
        }
    )

    for output_column, aliases in {
        "d_angstrom": ("d_angstrom", "d", "d_spacing", "d_spacing_angstrom"),
        "h": ("h",),
        "k": ("k",),
        "l": ("l",),
    }.items():
        source_column = _find_column(column_lookup, aliases)
        if source_column is not None:
            peaks[output_column] = pd.to_numeric(df[source_column], errors="coerce")

    peaks = peaks.dropna(subset=["two_theta_deg", "intensity"])
    if peaks.empty:
        raise ValueError(f"No usable PDF peaks found in {path}")

    label = _label_from_pdf_standard_csv(path, df)
    return PDFStandard(label=label, peaks=peaks, source_path=path)


def _normalize_column_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _find_column(column_lookup: dict[str, str], aliases: Sequence[str]) -> str | None:
    for alias in aliases:
        column = column_lookup.get(_normalize_column_name(alias))
        if column is not None:
            return column
    return None


def _label_from_pdf_standard_csv(path: Path, df: pd.DataFrame) -> str:
    label_column = _find_column(
        {_normalize_column_name(column): column for column in df.columns},
        aliases=("label", "standard_label", "pdf_label", "phase_label"),
    )
    if label_column is not None:
        labels = df[label_column].dropna().astype(str).str.strip()
        labels = labels[labels != ""]
        if not labels.empty:
            return labels.iloc[0]

    return path.stem.replace("_", " ").replace("PDF 97 023 8958", "PDF#97-023-8958")


def resolve_pdf_source_path(
    pdf_source: str | os.PathLike[str],
    pdf_card_dir: str | os.PathLike[str] = DEFAULT_PDF_CARD_DIR,
    standard_dir: str | os.PathLike[str] = DEFAULT_PDF_STANDARD_DIR,
) -> Path:
    """
    Resolve a PDF standard name, path, or extensionless basename.

    Examples that resolve:
    - data/pdf_card/plot_standards/CuInTe2_PDF_97_023_8958.csv
    - data/pdf_card/plot_standards/CuInTe2_PDF_97_023_8958
    - CuInTe2_PDF_97_023_8958
    """
    raw_path = Path(pdf_source)
    search_dirs = [Path(standard_dir), Path(pdf_card_dir), Path(pdf_card_dir) / "standard"]
    suffixes = ["", ".csv", ".txt"]
    candidates = []

    if raw_path.is_dir():
        candidates.extend(sorted(raw_path.glob("*.csv")))
        candidates.extend(sorted(raw_path.glob("*.txt")))
    else:
        for suffix in suffixes:
            candidates.append(raw_path if suffix == "" else raw_path.with_suffix(suffix))
        if not raw_path.is_absolute():
            for search_dir in search_dirs:
                for base in (raw_path, Path(raw_path.name)):
                    for suffix in suffixes:
                        path = search_dir / base
                        candidates.append(path if suffix == "" else path.with_suffix(suffix))

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    raise FileNotFoundError(f"Cannot find PDF standard for {pdf_source!r}")


def list_pdf_card_candidates(
    pdf_card_dir: str | os.PathLike[str] = DEFAULT_PDF_CARD_DIR,
    standard_dir: str | os.PathLike[str] = DEFAULT_PDF_STANDARD_DIR,
) -> list[Path]:
    pdf_card_dir = Path(pdf_card_dir)
    standard_dir = Path(standard_dir)
    candidates = (
        sorted(standard_dir.glob("*.csv"))
        + sorted(pdf_card_dir.glob("*.txt"))
        + sorted((pdf_card_dir / "standard").glob("*.csv"))
        + sorted((pdf_card_dir / "standard").glob("*.txt"))
    )

    unique_candidates: list[Path] = []
    seen = set()
    for path in candidates:
        key = str(path.resolve())
        if key not in seen and path.is_file():
            unique_candidates.append(path)
            seen.add(key)
    return unique_candidates


def resolve_pdf_standard(
    pdf_source: str | os.PathLike[str] | None = None,
    pdf_card_dir: str | os.PathLike[str] = DEFAULT_PDF_CARD_DIR,
    standard_dir: str | os.PathLike[str] = DEFAULT_PDF_STANDARD_DIR,
    preferred_phase: str = "CuInTe2",
) -> PDFStandard:
    if pdf_source:
        path = resolve_pdf_source_path(pdf_source, pdf_card_dir=pdf_card_dir, standard_dir=standard_dir)
    else:
        pdf_card_dir = Path(pdf_card_dir)
        standard_dir = Path(standard_dir)
        plot_csv_candidates = sorted(standard_dir.glob(f"*{preferred_phase}*.csv"))
        legacy_csv_candidates = sorted((pdf_card_dir / "standard").glob(f"*{preferred_phase}*_peaks.csv"))
        txt_candidates = sorted(pdf_card_dir.glob(f"*{preferred_phase}*.txt"))
        all_plot_csv = sorted(standard_dir.glob("*.csv"))
        all_legacy_csv = sorted((pdf_card_dir / "standard").glob("*_peaks.csv"))
        all_txt = sorted(pdf_card_dir.glob("*.txt"))
        candidates = (
            plot_csv_candidates
            + legacy_csv_candidates
            + txt_candidates
            + all_plot_csv
            + all_legacy_csv
            + all_txt
        )
        if not candidates:
            raise FileNotFoundError(f"No PDF standard found in {standard_dir} or {pdf_card_dir}")
        path = candidates[0]

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_pdf_peak_csv(path)
    return read_pdf_card_text(path)


def _clip_pattern(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    two_theta_range: tuple[float, float] | None,
) -> tuple[np.ndarray, np.ndarray]:
    if not two_theta_range:
        return two_theta, intensity
    low, high = two_theta_range
    mask = (two_theta >= low) & (two_theta <= high)
    if not np.any(mask):
        return two_theta, intensity
    return two_theta[mask], intensity[mask]


def prepare_intensity(
    intensity: np.ndarray,
    normalized: bool,
    baseline: str = "min",
) -> np.ndarray:
    values = intensity.astype(float).copy()
    if baseline == "min":
        values = values - np.nanmin(values)
    elif baseline == "none":
        pass
    else:
        raise ValueError("baseline must be 'min' or 'none'")

    if normalized:
        max_value = np.nanmax(np.abs(values))
        if max_value > 0:
            values = values / max_value
    return values


def _default_offset_step(prepared_intensities: Sequence[np.ndarray], normalized: bool, overlap: float) -> float:
    if normalized:
        return overlap
    max_range = max(float(np.nanmax(values) - np.nanmin(values)) for values in prepared_intensities)
    return max(max_range * overlap, 1.0)


def _clean_peaks(peaks: pd.DataFrame, two_theta_range: tuple[float, float] | None) -> pd.DataFrame:
    usable = peaks.copy()
    usable["intensity"] = pd.to_numeric(usable["intensity"], errors="coerce").fillna(0.0)
    usable = usable[usable["intensity"] > 0].sort_values("two_theta_deg")
    if two_theta_range:
        low, high = two_theta_range
        usable = usable[(usable["two_theta_deg"] >= low) & (usable["two_theta_deg"] <= high)]
    return usable


def plot_xrd_comparison(
    patterns: Sequence[XRDPattern],
    pdf_standard: PDFStandard | None = None,
    normalized: bool = False,
    save_name: str | None = None,
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    two_theta_range: tuple[float, float] | None = DEFAULT_TWO_THETA_RANGE,
    overlap: float = 1.05,
    offset_step: float | None = None,
    baseline: str = "min",
    standard_height_fraction: float = 0.42,
    standard_gap_fraction: float = 0.60,
    standard_min_height_fraction: float = 0.08,
    figsize: tuple[float, float] | None = None,
    subplot_aspect: str = DEFAULT_SUBPLOT_ASPECT,
    ylim: tuple[float | None, float | None] | None = None,
    colors: Sequence[str] | None = None,
    line_width: float = DEFAULT_XRD_LINE_WIDTH,
    tick_labelsize: float = 10,
    legend_font_size: float = DEFAULT_LEGEND_FONT_SIZE,
    legend_outside: bool = True,
    right_labels: bool = False,
    standard_color: str = "#d62728",
    transparent: bool = False,
    close: bool = True,
):
    """
    Plot stacked XRD patterns with an optional PDF-card stick reference.

    ``normalized=False`` keeps the raw count scale after optional baseline
    alignment; ``normalized=True`` scales each trace to its own maximum.
    """
    if not patterns:
        raise ValueError("No XRD patterns were provided")

    apply_plot_style(mode="single")
    prepared = []
    for pattern in patterns:
        clipped_x, clipped_y = _clip_pattern(pattern.two_theta, pattern.intensity, two_theta_range)
        prepared_y = prepare_intensity(clipped_y, normalized=normalized, baseline=baseline)
        prepared.append((pattern, clipped_x, prepared_y))

    prepared_intensities = [item[2] for item in prepared]
    offset_step = offset_step or _default_offset_step(prepared_intensities, normalized, overlap)
    standard_base = 0.0
    standard_height = standard_height_fraction * offset_step
    sample_base = (standard_height + standard_gap_fraction * offset_step) if pdf_standard else 0.0

    if figsize is None:
        figsize = figure_size_for_subplot_aspect(
            subplot_aspect,
            subplot_height=DEFAULT_SUBPLOT_HEIGHT,
        )
    fig, ax = plt.subplots(figsize=figsize)
    color_cycle = cycle(colors or DEFAULT_COLORS)
    handles = []
    labels = []

    for index, (pattern, x_values, y_values) in enumerate(prepared):
        offset = sample_base + index * offset_step
        color = next(color_cycle)
        (line,) = ax.plot(x_values, y_values + offset, color=color, linewidth=line_width, label=pattern.label)
        handles.append(line)
        labels.append(pattern.label)
        if right_labels and x_values.size:
            text_x = float(two_theta_range[1]) if two_theta_range else float(np.nanmax(x_values))
            label_y = offset + min(float(np.nanmax(y_values)) * 0.28, 0.75 * offset_step)
            ax.text(
                text_x - 0.6,
                label_y,
                pattern.sample_name or pattern.label,
                ha="right",
                va="center",
                fontsize=tick_labelsize,
                color="black",
            )

    if pdf_standard is not None:
        peaks = _clean_peaks(pdf_standard.peaks, two_theta_range)
        if not peaks.empty:
            max_pdf_intensity = peaks["intensity"].max()
            relative_intensity = peaks["intensity"] / max_pdf_intensity
            stick_heights = (
                standard_min_height_fraction * standard_height
                + relative_intensity * (1.0 - standard_min_height_fraction) * standard_height
            )
            ax.vlines(
                peaks["two_theta_deg"],
                standard_base,
                standard_base + stick_heights,
                color=standard_color,
                linewidth=line_width,
                label=pdf_standard.label,
            )
            handles.append(
                plt.Line2D([0], [0], color=standard_color, linewidth=max(line_width, 1.15), label=pdf_standard.label)
            )
            labels.append(pdf_standard.label)

    ax.set_xlabel(r"2$\mathit{Theta}$ (Degree)")
    ylabel = r"$\mathit{Intensity}$ (a.u.)" if normalized else r"$\mathit{Intensity}$ (counts)"
    ax.set_ylabel(ylabel)
    if two_theta_range:
        ax.set_xlim(*two_theta_range)
    ax.set_yticks([])
    format_te_axis(ax, show_grid=False, tick_labelsize=tick_labelsize)
    ax.tick_params(axis="x", which="both", direction="in", top=True, bottom=True, labelsize=tick_labelsize)
    ax.tick_params(axis="y", which="both", left=False, right=False, labelleft=False)

    bottom = 0.0 if pdf_standard else -0.05 * offset_step
    top = sample_base + (len(prepared) - 1) * offset_step + max(
        float(np.nanmax(values)) for values in prepared_intensities
    )
    ax.set_ylim(bottom, top + 0.25 * offset_step)
    if ylim is not None:
        ax.set_ylim(*ylim)
    apply_subplot_aspect(ax, subplot_aspect)

    if legend_outside and handles:
        fig.legend(
            handles,
            labels,
            loc="center left",
            bbox_to_anchor=(1.01, 0.5),
            fontsize=legend_font_size,
            frameon=False,
        )
        fig.tight_layout(rect=(0, 0, 0.82, 1))
    else:
        ax.legend(fontsize=legend_font_size, loc="best", frameon=False)
        fig.tight_layout()

    if save_name:
        plot_path = save_figure(
            fig,
            save_name,
            save_dir=save_dir,
            formats=list(formats) if formats else None,
            transparent=transparent,
        )
        if close:
            plt.close(fig)
        return plot_path

    return fig, ax


def plot_xrd_raw_and_normalized(
    patterns: Sequence[XRDPattern],
    pdf_standard: PDFStandard | None,
    comparison_id: str,
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    two_theta_range: tuple[float, float] | None = DEFAULT_TWO_THETA_RANGE,
    ylim: tuple[float | None, float | None] | None = None,
    overlap: float = 1.05,
    colors: Sequence[str] | None = None,
    line_width: float = DEFAULT_XRD_LINE_WIDTH,
    subplot_aspect: str = DEFAULT_SUBPLOT_ASPECT,
    tick_labelsize: float = 10,
    legend_font_size: float = DEFAULT_LEGEND_FONT_SIZE,
    legend_outside: bool = True,
    right_labels: bool = False,
    standard_color: str = "#d62728",
    close: bool = True,
) -> dict[str, str]:
    save_dir = Path(save_dir) / safe_filename(comparison_id)
    raw_path = plot_xrd_comparison(
        patterns,
        pdf_standard=pdf_standard,
        normalized=False,
        save_name=f"{safe_filename(comparison_id)}_XRD_not_normalized.png",
        save_dir=save_dir,
        formats=formats,
        two_theta_range=two_theta_range,
        ylim=ylim,
        overlap=overlap,
        colors=colors,
        line_width=line_width,
        subplot_aspect=subplot_aspect,
        tick_labelsize=tick_labelsize,
        legend_font_size=legend_font_size,
        legend_outside=legend_outside,
        right_labels=right_labels,
        standard_color=standard_color,
        close=close,
    )
    normalized_path = plot_xrd_comparison(
        patterns,
        pdf_standard=pdf_standard,
        normalized=True,
        save_name=f"{safe_filename(comparison_id)}_XRD_normalized.png",
        save_dir=save_dir,
        formats=formats,
        two_theta_range=two_theta_range,
        ylim=ylim,
        overlap=overlap,
        colors=colors,
        line_width=line_width,
        subplot_aspect=subplot_aspect,
        tick_labelsize=tick_labelsize,
        legend_font_size=legend_font_size,
        legend_outside=legend_outside,
        right_labels=right_labels,
        standard_color=standard_color,
        close=close,
    )
    return {"not_normalized": raw_path, "normalized": normalized_path}


def _normalized_modes_for_output_mode(output_mode: str) -> list[tuple[str, bool]]:
    if output_mode == "both":
        return [("not_normalized", False), ("normalized", True)]
    if output_mode == "normalized":
        return [("normalized", True)]
    if output_mode == "not_normalized":
        return [("not_normalized", False)]
    raise ValueError("output_mode must be 'both', 'normalized', or 'not_normalized'")


def plot_xrd_separate(
    patterns: Sequence[XRDPattern],
    pdf_standard: PDFStandard | None,
    comparison_id: str,
    output_mode: str = "both",
    save_dir: str | os.PathLike[str] = DEFAULT_XRD_SAVE_DIR,
    formats: Sequence[str] | None = None,
    two_theta_range: tuple[float, float] | None = DEFAULT_TWO_THETA_RANGE,
    ylim: tuple[float | None, float | None] | None = None,
    overlap: float = 1.05,
    colors: Sequence[str] | None = None,
    line_width: float = DEFAULT_XRD_LINE_WIDTH,
    subplot_aspect: str = DEFAULT_SUBPLOT_ASPECT,
    tick_labelsize: float = 10,
    legend_font_size: float = DEFAULT_LEGEND_FONT_SIZE,
    legend_outside: bool = True,
    right_labels: bool = False,
    standard_color: str = "#d62728",
    close: bool = True,
) -> dict[str, str]:
    save_dir = Path(save_dir) / safe_filename(comparison_id) / "separate"
    paths: dict[str, str] = {}

    for pattern in patterns:
        sample_key = safe_filename(pattern.sample_id or pattern.label)
        for suffix, normalized in _normalized_modes_for_output_mode(output_mode):
            plot_path = plot_xrd_comparison(
                [pattern],
                pdf_standard=pdf_standard,
                normalized=normalized,
                save_name=f"{sample_key}_XRD_{suffix}.png",
                save_dir=save_dir,
                formats=formats,
                two_theta_range=two_theta_range,
                ylim=ylim,
                overlap=overlap,
                colors=colors,
                line_width=line_width,
                subplot_aspect=subplot_aspect,
                tick_labelsize=tick_labelsize,
                legend_font_size=legend_font_size,
                legend_outside=legend_outside,
                right_labels=right_labels,
                standard_color=standard_color,
                close=close,
            )
            paths[f"{sample_key}_{suffix}"] = plot_path

    return paths


def comparison_id_from_patterns(patterns: Sequence[XRDPattern]) -> str:
    batches = []
    for pattern in patterns:
        name = pattern.batch_id or pattern.label
        if name not in batches:
            batches.append(name)
    if len(batches) == 1:
        return batches[0]
    return "_vs_".join(batches)


def summarize_patterns(patterns: Iterable[XRDPattern]) -> list[dict[str, str]]:
    return [
        {
            "label": pattern.label,
            "batch_id": pattern.batch_id,
            "sample_id": pattern.sample_id,
            "source_path": str(pattern.source_path),
        }
        for pattern in patterns
    ]

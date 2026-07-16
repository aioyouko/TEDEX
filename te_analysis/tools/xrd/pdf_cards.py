"""PDF reference card parsing and resolution.

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

from te_analysis.tools.xrd.io import _read_json, safe_filename


DEFAULT_PDF_CARD_DIR = Path("data/pdf_card")
DEFAULT_PDF_STANDARD_DIR = DEFAULT_PDF_CARD_DIR / "plot_standards"
PDF_PEAK_PATTERN = re.compile(
    r"^\s*([0-9.]+)\s+([0-9.]+)\s+(\S+)\s+"
    r"\(\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\)"
)


@dataclass(frozen=True)
class PDFStandard:
    label: str
    peaks: pd.DataFrame
    source_path: Path


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


def _clean_peaks(
    peaks: pd.DataFrame,
    two_theta_range: tuple[float | None, float | None] | None,
) -> pd.DataFrame:
    usable = peaks.copy()
    usable["intensity"] = pd.to_numeric(usable["intensity"], errors="coerce").fillna(0.0)
    usable = usable[usable["intensity"] > 0].sort_values("two_theta_deg")
    if two_theta_range:
        low, high = two_theta_range
        if low is not None:
            usable = usable[usable["two_theta_deg"] >= low]
        if high is not None:
            usable = usable[usable["two_theta_deg"] <= high]
    return usable


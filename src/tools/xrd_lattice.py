"""
Utilities for normalizing PDF cards and fitting XRD lattice parameters.

The fitting uses Bragg's law to convert measured 2-theta peak positions to
1/d^2, then solves symmetry-constrained reciprocal-lattice equations selected
from the space-group number or crystal-system label.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy.signal import find_peaks, peak_widths, savgol_filter


DEFAULT_WAVELENGTH_ANGSTROM = 1.5406


@dataclass
class PeakRecord:
    two_theta_deg: float
    d_angstrom: float
    intensity: float
    intensity_text: str
    h: int
    k: int
    l: int
    theta_deg: Optional[float] = None
    inv_2d: Optional[float] = None
    two_pi_over_d: Optional[float] = None


@dataclass
class ObservedPeak:
    two_theta_deg: float
    intensity: float
    corrected_intensity: float
    relative_intensity: float
    prominence: float
    fwhm_deg: Optional[float]
    index: int


def _float_or_none(value: str) -> Optional[float]:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_intensity(value: str) -> float:
    value = value.strip()
    if value.startswith("<"):
        parsed = _float_or_none(value[1:])
        return 0.5 * parsed if parsed is not None else 0.5
    parsed = _float_or_none(value)
    if parsed is None:
        return float("nan")
    return parsed


def crystal_system_from_space_group_number(space_group_number: Optional[int]) -> Optional[str]:
    if space_group_number is None:
        return None
    if 1 <= space_group_number <= 2:
        return "triclinic"
    if 3 <= space_group_number <= 15:
        return "monoclinic"
    if 16 <= space_group_number <= 74:
        return "orthorhombic"
    if 75 <= space_group_number <= 142:
        return "tetragonal"
    if 143 <= space_group_number <= 167:
        return "trigonal"
    if 168 <= space_group_number <= 194:
        return "hexagonal"
    if 195 <= space_group_number <= 230:
        return "cubic"
    return None


def _normalize_crystal_system(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = value.strip().lower()
    aliases = {
        "rhombohedral": "trigonal",
        "trigonal-r": "trigonal",
        "hex": "hexagonal",
        "tetra": "tetragonal",
        "ortho": "orthorhombic",
        "mono": "monoclinic",
        "tri": "triclinic",
    }
    return aliases.get(text, text)


def parse_pdf_card(card_path: os.PathLike[str] | str) -> Dict[str, Any]:
    """
    Parse a Jade-style PDF card text export into a normalized dictionary.
    """
    path = Path(card_path)
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line.rstrip() for line in raw_text.splitlines()]

    pdf_index = None
    quality_mark = None
    d_source = None
    intensity_source = None
    first_line_match = re.search(r"PDF#([^:]+):\s*(.*)$", lines[0] if lines else "")
    if first_line_match:
        pdf_index = first_line_match.group(1).strip()
        tokens = first_line_match.group(2)
        quality_mark = _search_key_value(tokens, "QM")
        d_source = _search_key_value(tokens, "d")
        intensity_source = _search_key_value(tokens, "I")

    radiation = None
    wavelength = None
    two_theta_range = None
    rir = None
    phase_name = ""
    formula = ""
    crystal_system = None
    space_group = None
    space_group_number = None
    z_value = None
    cell = {
        "a_angstrom": None,
        "b_angstrom": None,
        "c_angstrom": None,
        "alpha_deg": None,
        "beta_deg": None,
        "gamma_deg": None,
    }
    density_calculated = None
    density_measured = None
    molecular_weight = None
    volume = None
    references: List[str] = []
    notes: List[str] = []
    strong_lines = ""

    table_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 1 and stripped:
            phase_name = stripped
        elif i == 2 and stripped:
            formula = stripped

        if "Radiation=" in stripped:
            radiation = _search_key_value(stripped, "Radiation")
            wavelength = _float_or_none(_search_key_value(stripped, "Lambda") or "")

        if "2T=" in stripped:
            two_theta_range = _search_key_value(stripped, "2T")

        if "I/Ic(RIR)=" in stripped:
            rir = _float_or_none(_search_key_value(stripped, "I/Ic(RIR)") or "")

        if stripped.startswith("Ref:"):
            references.append(stripped[4:].strip())

        crystal_match = re.match(
            r"([^,]+),\s+(.+?)\s+\((\d+)\)\s+Z\s*=\s*([0-9.]+)",
            stripped,
        )
        if crystal_match:
            crystal_system = _normalize_crystal_system(crystal_match.group(1))
            space_group = crystal_match.group(2).strip()
            space_group_number = int(crystal_match.group(3))
            z_value = _float_or_none(crystal_match.group(4))

        cell_match = re.search(
            r"CELL:\s*([0-9.]+)\s*x\s*([0-9.]+)\s*x\s*([0-9.]+)\s*"
            r"<\s*([0-9.]+)\s*x\s*([0-9.]+)\s*x\s*([0-9.]+)\s*>",
            stripped,
        )
        if cell_match:
            cell = {
                "a_angstrom": float(cell_match.group(1)),
                "b_angstrom": float(cell_match.group(2)),
                "c_angstrom": float(cell_match.group(3)),
                "alpha_deg": float(cell_match.group(4)),
                "beta_deg": float(cell_match.group(5)),
                "gamma_deg": float(cell_match.group(6)),
            }

        if stripped.startswith("Density(c)="):
            density_calculated = _float_or_none(_search_key_value(stripped, "Density(c)") or "")
            density_measured = _float_or_none(_search_key_value(stripped, "Density(m)") or "")
            molecular_weight = _float_or_none(_search_key_value(stripped, "Mwt") or "")
            volume = _float_or_none(_search_key_value(stripped, "Vol") or "")

        if stripped.startswith("Strong Lines:"):
            strong_lines = stripped.split(":", 1)[1].strip()

        if stripped.startswith("NOTE:"):
            notes.append(stripped[5:].strip())
        elif notes and stripped and not stripped.startswith("2-Theta"):
            if table_start is None and not stripped.startswith("Ref:"):
                notes.append(stripped)

        if stripped.startswith("2-Theta"):
            table_start = i + 1
            break

    inferred_system = crystal_system_from_space_group_number(space_group_number)
    if inferred_system is not None:
        crystal_system = inferred_system

    peaks: List[PeakRecord] = []
    if table_start is not None:
        for line in lines[table_start:]:
            peak = _parse_pdf_peak_line(line)
            if peak is not None:
                peaks.append(peak)

    return {
        "schema_version": "xrd_pdf_card/v1",
        "source": {
            "path": str(path),
            "format": "jade_pdf_card_text",
        },
        "pdf_index": pdf_index,
        "phase": {
            "name": phase_name,
            "formula": formula,
        },
        "radiation": {
            "type": radiation,
            "wavelength_angstrom": wavelength or DEFAULT_WAVELENGTH_ANGSTROM,
        },
        "quality": {
            "quality_mark": quality_mark,
            "d_spacing_source": d_source,
            "intensity_source": intensity_source,
            "rir": rir,
            "two_theta_range_deg": two_theta_range,
        },
        "crystal": {
            "crystal_system": crystal_system,
            "space_group": space_group,
            "space_group_number": space_group_number,
            "z": z_value,
            "cell": cell,
            "density_calculated_g_cm3": density_calculated,
            "density_measured_g_cm3": density_measured,
            "molecular_weight": molecular_weight,
            "volume_angstrom3": volume,
        },
        "strong_lines": strong_lines,
        "references": references,
        "notes": notes,
        "peaks": [asdict(peak) for peak in peaks],
    }


def _search_key_value(text: str, key: str) -> Optional[str]:
    pattern = re.escape(key) + r"\s*=\s*([^;\t]+)"
    match = re.search(pattern, text)
    if not match:
        return None
    return match.group(1).strip()


def _parse_pdf_peak_line(line: str) -> Optional[PeakRecord]:
    pattern = re.compile(
        r"^\s*([0-9.]+)\s+([0-9.]+)\s+(\S+)\s+"
        r"\(\s*(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+)\)\s*"
        r"([0-9.]*)?\s*([0-9.]*)?\s*([0-9.]*)?"
    )
    match = pattern.match(line)
    if not match:
        return None
    return PeakRecord(
        two_theta_deg=float(match.group(1)),
        d_angstrom=float(match.group(2)),
        intensity=_parse_intensity(match.group(3)),
        intensity_text=match.group(3),
        h=int(match.group(4)),
        k=int(match.group(5)),
        l=int(match.group(6)),
        theta_deg=_float_or_none(match.group(7) or ""),
        inv_2d=_float_or_none(match.group(8) or ""),
        two_pi_over_d=_float_or_none(match.group(9) or ""),
    )


def write_standard_pdf_card(
    card: Dict[str, Any],
    output_json_path: os.PathLike[str] | str,
    output_peaks_csv_path: Optional[os.PathLike[str] | str] = None,
) -> None:
    json_path = Path(output_json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(card, indent=2), encoding="utf-8")

    if output_peaks_csv_path is not None:
        csv_path = Path(output_peaks_csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        peaks = card.get("peaks", [])
        fieldnames = [
            "two_theta_deg",
            "d_angstrom",
            "intensity",
            "intensity_text",
            "h",
            "k",
            "l",
            "theta_deg",
            "inv_2d",
            "two_pi_over_d",
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for peak in peaks:
                writer.writerow({field: peak.get(field) for field in fieldnames})


def load_xrd_xy(xrd_path: os.PathLike[str] | str) -> Tuple[np.ndarray, np.ndarray, Optional[float]]:
    x_values: List[float] = []
    y_values: List[float] = []
    wavelength = None

    with Path(xrd_path).open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            wavelength_match = re.search(r"Wavelength\s*=\s*([0-9.]+)", stripped)
            if wavelength_match:
                wavelength = float(wavelength_match.group(1))
                continue
            if "Theta" in stripped:
                continue
            parts = stripped.replace(",", " ").split()
            if len(parts) < 2:
                continue
            try:
                x_values.append(float(parts[0]))
                y_values.append(float(parts[1]))
            except ValueError:
                continue

    if not x_values:
        raise ValueError(f"No numeric XRD data found in {xrd_path}")

    return np.asarray(x_values), np.asarray(y_values), wavelength


def _odd_window(points: int, minimum: int = 5) -> int:
    points = max(points, minimum)
    return points if points % 2 else points + 1


def detect_xrd_peaks(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    prominence_fraction: float = 0.015,
    min_distance_deg: float = 0.12,
    smooth_window_deg: float = 0.30,
    baseline_window_deg: float = 8.0,
) -> List[ObservedPeak]:
    """
    Detect XRD peaks after Savitzky-Golay smoothing and broad baseline removal.
    """
    if two_theta.size != intensity.size:
        raise ValueError("two_theta and intensity arrays must have the same length")
    if two_theta.size < 7:
        raise ValueError("At least 7 XRD points are required for peak detection")

    step = float(np.median(np.diff(two_theta)))
    smooth_window = _odd_window(int(round(smooth_window_deg / step)), minimum=5)
    baseline_window = _odd_window(int(round(baseline_window_deg / step)), minimum=smooth_window + 2)
    smooth_window = min(smooth_window, _odd_window(two_theta.size - 2, minimum=5))
    baseline_window = min(baseline_window, _odd_window(two_theta.size - 2, minimum=smooth_window + 2))
    if smooth_window >= two_theta.size:
        smooth_window = _odd_window(two_theta.size - 2, minimum=5)
    if baseline_window >= two_theta.size:
        baseline_window = _odd_window(two_theta.size - 2, minimum=smooth_window + 2)

    smoothed = savgol_filter(intensity, smooth_window, 3)
    baseline = savgol_filter(intensity, baseline_window, 2)
    corrected = smoothed - baseline
    corrected = corrected - min(0.0, float(np.nanmin(corrected)))

    min_prominence = max(25.0, float(np.nanmax(corrected)) * prominence_fraction)
    min_distance_points = max(1, int(round(min_distance_deg / step)))
    peak_indices, properties = find_peaks(
        corrected,
        prominence=min_prominence,
        distance=min_distance_points,
    )
    widths = peak_widths(corrected, peak_indices, rel_height=0.5)[0] * step if peak_indices.size else []
    max_corrected = float(np.nanmax(corrected[peak_indices])) if peak_indices.size else 1.0

    observed: List[ObservedPeak] = []
    for n, peak_index in enumerate(peak_indices):
        refined_two_theta = _refine_peak_center(two_theta, corrected, int(peak_index))
        corrected_intensity = float(corrected[peak_index])
        relative = 100.0 * corrected_intensity / max_corrected if max_corrected else 0.0
        observed.append(
            ObservedPeak(
                two_theta_deg=refined_two_theta,
                intensity=float(intensity[peak_index]),
                corrected_intensity=corrected_intensity,
                relative_intensity=relative,
                prominence=float(properties["prominences"][n]),
                fwhm_deg=float(widths[n]) if len(widths) else None,
                index=int(peak_index),
            )
        )

    return sorted(observed, key=lambda peak: peak.two_theta_deg)


def _refine_peak_center(two_theta: np.ndarray, corrected: np.ndarray, peak_index: int) -> float:
    left = max(0, peak_index - 3)
    right = min(two_theta.size, peak_index + 4)
    if right - left < 5:
        return float(two_theta[peak_index])
    x = two_theta[left:right]
    y = corrected[left:right]
    try:
        coeff = np.polyfit(x, y, 2)
    except np.linalg.LinAlgError:
        return float(two_theta[peak_index])
    if coeff[0] >= 0:
        return float(two_theta[peak_index])
    center = -coeff[1] / (2 * coeff[0])
    if float(x[0]) <= center <= float(x[-1]):
        return float(center)
    return float(two_theta[peak_index])


def match_reference_peaks(
    reference_peaks: Sequence[Dict[str, Any]],
    observed_peaks: Sequence[ObservedPeak],
    tolerance_deg: float = 0.8,
    min_reference_intensity: float = 0.5,
    min_observed_relative_intensity: float = 0.5,
) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    usable_observed = [
        peak for peak in observed_peaks if peak.relative_intensity >= min_observed_relative_intensity
    ]

    for ref in reference_peaks:
        ref_intensity = ref.get("intensity")
        if ref_intensity is None or math.isnan(float(ref_intensity)):
            continue
        if float(ref_intensity) < min_reference_intensity:
            continue
        if not usable_observed:
            break

        ref_two_theta = float(ref["two_theta_deg"])
        best = min(usable_observed, key=lambda peak: abs(peak.two_theta_deg - ref_two_theta))
        delta = best.two_theta_deg - ref_two_theta
        if abs(delta) <= tolerance_deg:
            matches.append(
                {
                    "reference_two_theta_deg": ref_two_theta,
                    "observed_two_theta_deg": best.two_theta_deg,
                    "delta_two_theta_deg": delta,
                    "reference_d_angstrom": ref["d_angstrom"],
                    "reference_intensity": ref_intensity,
                    "reference_intensity_text": ref.get("intensity_text"),
                    "observed_intensity": best.intensity,
                    "observed_corrected_intensity": best.corrected_intensity,
                    "observed_relative_intensity": best.relative_intensity,
                    "observed_peak_index": best.index,
                    "h": int(ref["h"]),
                    "k": int(ref["k"]),
                    "l": int(ref["l"]),
                }
            )

    return sorted(matches, key=lambda item: item["reference_two_theta_deg"])


def bragg_d_spacing(two_theta_deg: float, wavelength_angstrom: float) -> float:
    theta_rad = math.radians(two_theta_deg / 2.0)
    sin_theta = math.sin(theta_rad)
    if sin_theta <= 0:
        raise ValueError(f"Invalid 2-theta value: {two_theta_deg}")
    return wavelength_angstrom / (2.0 * sin_theta)


def two_theta_from_d_spacing(d_angstrom: float, wavelength_angstrom: float) -> Optional[float]:
    argument = wavelength_angstrom / (2.0 * d_angstrom)
    if argument < -1.0 or argument > 1.0:
        return None
    return math.degrees(2.0 * math.asin(argument))


def fit_lattice_parameters(
    matches: Sequence[Dict[str, Any]],
    crystal_system: Optional[str],
    wavelength_angstrom: float,
) -> Dict[str, Any]:
    system = _normalize_crystal_system(crystal_system) or "triclinic"
    rows = []
    q_observed = []
    usable_matches = []
    for match in matches:
        h, k, l = int(match["h"]), int(match["k"]), int(match["l"])
        if h == 0 and k == 0 and l == 0:
            continue
        d_obs = bragg_d_spacing(float(match["observed_two_theta_deg"]), wavelength_angstrom)
        rows.append(_design_row(h, k, l, system))
        q_observed.append(1.0 / (d_obs * d_obs))
        usable = dict(match)
        usable["observed_d_angstrom"] = d_obs
        usable_matches.append(usable)

    if not rows:
        raise ValueError("No indexed reference peaks were matched to measured peaks")

    design = np.asarray(rows, dtype=float)
    y = np.asarray(q_observed, dtype=float)
    required_rank = _required_rank(system)
    if design.shape[0] < required_rank:
        raise ValueError(
            f"{system} fitting needs at least {required_rank} independent matched peaks; "
            f"found {design.shape[0]}"
        )

    params, residuals, rank, singular_values = np.linalg.lstsq(design, y, rcond=None)
    if rank < required_rank:
        raise ValueError(
            f"Matched peaks are not independent enough for {system} fitting "
            f"(rank {rank}, need {required_rank})"
        )

    q_fit = design @ params
    cell = _cell_from_fit_params(params, system)
    match_rows = []
    for match, q_fit_i, q_obs_i in zip(usable_matches, q_fit, y):
        d_fit = 1.0 / math.sqrt(q_fit_i) if q_fit_i > 0 else float("nan")
        two_theta_fit = (
            two_theta_from_d_spacing(d_fit, wavelength_angstrom) if math.isfinite(d_fit) else None
        )
        row = dict(match)
        row["fitted_d_angstrom"] = d_fit
        row["fitted_two_theta_deg"] = two_theta_fit
        row["residual_q_inv_angstrom2"] = q_obs_i - q_fit_i
        row["residual_two_theta_deg"] = (
            float(match["observed_two_theta_deg"]) - two_theta_fit
            if two_theta_fit is not None
            else None
        )
        match_rows.append(row)

    rms_two_theta = _rms(
        row["residual_two_theta_deg"]
        for row in match_rows
        if row["residual_two_theta_deg"] is not None
    )
    rms_q = _rms(row["residual_q_inv_angstrom2"] for row in match_rows)

    return {
        "fit_model": {
            "crystal_system": system,
            "parameterization": _parameterization_name(system),
            "wavelength_angstrom": wavelength_angstrom,
            "matched_peak_count": len(match_rows),
            "least_squares_rank": int(rank),
            "singular_values": [float(value) for value in singular_values],
            "rms_two_theta_deg": rms_two_theta,
            "rms_q_inv_angstrom2": rms_q,
        },
        "lattice_parameters": cell,
        "fit_parameters": [float(value) for value in params],
        "matched_peaks": match_rows,
    }


def _design_row(h: int, k: int, l: int, crystal_system: str) -> List[float]:
    if crystal_system == "cubic":
        return [h * h + k * k + l * l]
    if crystal_system == "tetragonal":
        return [h * h + k * k, l * l]
    if crystal_system in {"hexagonal", "trigonal"}:
        return [(4.0 / 3.0) * (h * h + h * k + k * k), l * l]
    if crystal_system == "orthorhombic":
        return [h * h, k * k, l * l]
    if crystal_system == "monoclinic":
        return [h * h, k * k, l * l, 2 * h * l]
    return [h * h, k * k, l * l, 2 * h * k, 2 * h * l, 2 * k * l]


def _required_rank(crystal_system: str) -> int:
    return {
        "cubic": 1,
        "tetragonal": 2,
        "hexagonal": 2,
        "trigonal": 2,
        "orthorhombic": 3,
        "monoclinic": 4,
        "triclinic": 6,
    }.get(crystal_system, 6)


def _parameterization_name(crystal_system: str) -> str:
    if crystal_system in {"cubic", "tetragonal", "hexagonal", "trigonal", "orthorhombic"}:
        return "direct reciprocal lengths"
    if crystal_system == "monoclinic":
        return "reciprocal metric tensor, unique axis b"
    return "full reciprocal metric tensor"


def _cell_from_fit_params(params: np.ndarray, crystal_system: str) -> Dict[str, float]:
    if crystal_system == "cubic":
        a = _positive_reciprocal_length(params[0], "a")
        return _cell_dict(a, a, a, 90.0, 90.0, 90.0)

    if crystal_system == "tetragonal":
        a = _positive_reciprocal_length(params[0], "a")
        c = _positive_reciprocal_length(params[1], "c")
        return _cell_dict(a, a, c, 90.0, 90.0, 90.0)

    if crystal_system in {"hexagonal", "trigonal"}:
        a = _positive_reciprocal_length(params[0], "a")
        c = _positive_reciprocal_length(params[1], "c")
        return _cell_dict(a, a, c, 90.0, 90.0, 120.0)

    if crystal_system == "orthorhombic":
        a = _positive_reciprocal_length(params[0], "a")
        b = _positive_reciprocal_length(params[1], "b")
        c = _positive_reciprocal_length(params[2], "c")
        return _cell_dict(a, b, c, 90.0, 90.0, 90.0)

    if crystal_system == "monoclinic":
        g_star = np.asarray(
            [
                [params[0], 0.0, params[3]],
                [0.0, params[1], 0.0],
                [params[3], 0.0, params[2]],
            ],
            dtype=float,
        )
        return _cell_from_reciprocal_metric(g_star)

    g_star = np.asarray(
        [
            [params[0], params[3], params[4]],
            [params[3], params[1], params[5]],
            [params[4], params[5], params[2]],
        ],
        dtype=float,
    )
    return _cell_from_reciprocal_metric(g_star)


def _positive_reciprocal_length(value: float, label: str) -> float:
    if value <= 0:
        raise ValueError(f"Fitted reciprocal length for {label} is not positive: {value}")
    return 1.0 / math.sqrt(value)


def _cell_from_reciprocal_metric(g_star: np.ndarray) -> Dict[str, float]:
    eigenvalues = np.linalg.eigvalsh(g_star)
    if np.any(eigenvalues <= 0):
        raise ValueError("Fitted reciprocal metric tensor is not positive definite")
    metric = np.linalg.inv(g_star)
    a = math.sqrt(metric[0, 0])
    b = math.sqrt(metric[1, 1])
    c = math.sqrt(metric[2, 2])
    gamma = _angle_from_cos(metric[0, 1] / (a * b))
    beta = _angle_from_cos(metric[0, 2] / (a * c))
    alpha = _angle_from_cos(metric[1, 2] / (b * c))
    return _cell_dict(a, b, c, alpha, beta, gamma)


def _angle_from_cos(value: float) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, value))))


def _cell_dict(
    a: float,
    b: float,
    c: float,
    alpha: float,
    beta: float,
    gamma: float,
) -> Dict[str, float]:
    return {
        "a_angstrom": float(a),
        "b_angstrom": float(b),
        "c_angstrom": float(c),
        "alpha_deg": float(alpha),
        "beta_deg": float(beta),
        "gamma_deg": float(gamma),
    }


def _rms(values: Iterable[float]) -> Optional[float]:
    numeric = np.asarray([float(value) for value in values], dtype=float)
    if numeric.size == 0:
        return None
    return float(math.sqrt(np.mean(numeric * numeric)))


def run_lattice_fit(
    pdf_card_path: os.PathLike[str] | str,
    xrd_path: os.PathLike[str] | str,
    output_dir: os.PathLike[str] | str,
    sample_name: Optional[str] = None,
    match_tolerance_deg: float = 0.8,
    min_reference_intensity: float = 2.0,
    peak_prominence_fraction: float = 0.015,
) -> Dict[str, Any]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    card = parse_pdf_card(pdf_card_path)
    sample = sample_name or Path(xrd_path).stem.replace("_XRD", "")
    pdf_label = (card.get("pdf_index") or "unknown").replace("#", "").replace("-", "_")
    phase_label = re.sub(r"[^A-Za-z0-9]+", "_", card["phase"]["formula"] or card["phase"]["name"]).strip("_")
    prefix = f"{sample}_{phase_label}_PDF_{pdf_label}"

    standard_json = output_path / f"{phase_label}_PDF_{pdf_label}_standard.json"
    standard_csv = output_path / f"{phase_label}_PDF_{pdf_label}_peaks.csv"
    write_standard_pdf_card(card, standard_json, standard_csv)

    two_theta, intensity, measured_wavelength = load_xrd_xy(xrd_path)
    wavelength = measured_wavelength or card["radiation"]["wavelength_angstrom"] or DEFAULT_WAVELENGTH_ANGSTROM
    observed_peaks = detect_xrd_peaks(
        two_theta,
        intensity,
        prominence_fraction=peak_prominence_fraction,
    )
    matches = match_reference_peaks(
        card["peaks"],
        observed_peaks,
        tolerance_deg=match_tolerance_deg,
        min_reference_intensity=min_reference_intensity,
    )
    fit = fit_lattice_parameters(
        matches,
        card["crystal"]["crystal_system"],
        wavelength,
    )

    result = {
        "schema_version": "xrd_lattice_fit/v1",
        "sample": {
            "name": sample,
            "xrd_path": str(xrd_path),
            "wavelength_angstrom": wavelength,
        },
        "reference_card": {
            "standard_json": str(standard_json),
            "standard_peaks_csv": str(standard_csv),
            "pdf_index": card.get("pdf_index"),
            "phase": card.get("phase"),
            "crystal": card.get("crystal"),
        },
        "peak_detection": {
            "peak_count": len(observed_peaks),
            "prominence_fraction": peak_prominence_fraction,
            "observed_peaks": [asdict(peak) for peak in observed_peaks],
        },
        "peak_matching": {
            "match_tolerance_deg": match_tolerance_deg,
            "min_reference_intensity": min_reference_intensity,
        },
        **fit,
    }

    result_json = output_path / f"{prefix}_lattice_fit.json"
    result_csv = output_path / f"{prefix}_matched_peaks.csv"
    observed_csv = output_path / f"{prefix}_observed_peaks.csv"
    result_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    _write_rows_csv(result_csv, result["matched_peaks"])
    _write_rows_csv(observed_csv, [asdict(peak) for peak in observed_peaks])

    result["output_files"] = {
        "standard_pdf_card_json": str(standard_json),
        "standard_pdf_card_peaks_csv": str(standard_csv),
        "lattice_fit_json": str(result_json),
        "matched_peaks_csv": str(result_csv),
        "observed_peaks_csv": str(observed_csv),
    }
    result_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _write_rows_csv(path: os.PathLike[str] | str, rows: Sequence[Dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize a PDF card and fit lattice parameters from an XRD .xy file."
    )
    parser.add_argument("--pdf-card", required=True, help="Path to the PDF card text export.")
    parser.add_argument("--xrd", required=True, help="Path to measured XRD .xy data.")
    parser.add_argument("--output-dir", default="results/xrd_lattice", help="Output directory.")
    parser.add_argument("--sample-name", default=None, help="Optional sample name.")
    parser.add_argument("--match-tolerance-deg", type=float, default=0.8)
    parser.add_argument("--min-reference-intensity", type=float, default=2.0)
    parser.add_argument("--peak-prominence-fraction", type=float, default=0.015)
    args = parser.parse_args(argv)

    result = run_lattice_fit(
        pdf_card_path=args.pdf_card,
        xrd_path=args.xrd,
        output_dir=args.output_dir,
        sample_name=args.sample_name,
        match_tolerance_deg=args.match_tolerance_deg,
        min_reference_intensity=args.min_reference_intensity,
        peak_prominence_fraction=args.peak_prominence_fraction,
    )
    cell = result["lattice_parameters"]
    print("Lattice parameters")
    print(f"  a = {cell['a_angstrom']:.5f} A")
    print(f"  b = {cell['b_angstrom']:.5f} A")
    print(f"  c = {cell['c_angstrom']:.5f} A")
    print(f"  alpha = {cell['alpha_deg']:.4f} deg")
    print(f"  beta  = {cell['beta_deg']:.4f} deg")
    print(f"  gamma = {cell['gamma_deg']:.4f} deg")
    print(f"Matched peaks: {result['fit_model']['matched_peak_count']}")
    print(f"RMS 2-theta residual: {result['fit_model']['rms_two_theta_deg']:.4f} deg")
    print("Output files")
    for label, path in result["output_files"].items():
        print(f"  {label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

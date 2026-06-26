#!/usr/bin/env python3
"""Create compact paper-style TE plot variants from processed lab CSV files.

Examples
--------
Point-line property versus composition:
    python scripts/plot_paper_style_te_variants.py \
        --samples CHY-1051 \
        --plot-type composition-line \
        --property zt \
        --temperature 700 \
        --x-element Ag \
        --x-label "Ag content x"

Dual-axis point-line plot versus composition:
    python scripts/plot_paper_style_te_variants.py \
        --samples CHY-1036-A CHY-1040-A CHY-1040-B CHY-1051 \
        --plot-type composition-dual \
        --temperature 300 \
        --left-property seebeck \
        --right-property conductivity \
        --x-element Ag

Compact 2x3 transport panel:
    python scripts/plot_paper_style_te_variants.py \
        --samples CHY-1051 \
        --plot-type summary-panels
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from itertools import cycle
from pathlib import Path
from typing import Any


def set_matplotlib_cache() -> None:
    cache_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "te_agent_matplotlib"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))


set_matplotlib_cache()

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import ticker


PROPERTY_ALIASES = {
    "s": "seebeck",
    "seebeck": "seebeck",
    "sigma": "conductivity",
    "electrical_conductivity": "conductivity",
    "conductivity": "conductivity",
    "pf": "power_factor",
    "power_factor": "power_factor",
    "kappa": "thermal_conductivity",
    "thermal_conductivity": "thermal_conductivity",
    "kappa_tot": "thermal_conductivity",
    "kappa_l": "lattice_thermal_conductivity",
    "lattice_thermal_conductivity": "lattice_thermal_conductivity",
    "zt": "zt",
}


FALLBACK_COLORS = [
    "#d62728",
    "#1f77b4",
    "#2ca02c",
    "#9467bd",
    "#ff7f0e",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
]

FALLBACK_MARKERS = ["o", "s", "D", "^", "v", "<", ">", "p", "h"]
PAPER_MAJOR_TICK_LENGTH = 4.0
PAPER_MINOR_TICK_LENGTH = 2.2

PAPER_YLABELS = {
    "seebeck": "$S$ (µV K$^{-1}$)",
    "conductivity": "$\\sigma$ (S cm$^{-1}$)",
    "power_factor": "$PF$ (µW cm$^{-1}$ K$^{-2}$)",
    "thermal_conductivity": "$\\kappa_{\\mathrm{tot}}$ (W m$^{-1}$ K$^{-1}$)",
    "lattice_thermal_conductivity": "$\\kappa_{\\mathrm{L}}$ (W m$^{-1}$ K$^{-1}$)",
    "zt": "$ZT$",
}

NORMALIZED_YLABELS = {
    "seebeck": r"Normalized $S$",
    "conductivity": r"Normalized $\sigma$",
    "power_factor": r"Normalized $PF$",
    "thermal_conductivity": r"Normalized $\kappa_{\mathrm{tot}}$",
    "lattice_thermal_conductivity": r"Normalized $\kappa_{\mathrm{L}}$",
    "zt": r"Normalized $ZT$",
}


def safe_output_stem(value: str, max_length: int = 96) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    stem = re.sub(r"_+", "_", stem).strip("_.-") or "plot"
    if len(stem) <= max_length:
        return stem
    digest = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:8]
    prefix_length = max(1, max_length - len(digest) - 1)
    return f"{stem[:prefix_length].rstrip('_.-')}_{digest}"


def apply_paper_labels(specs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    local_specs = {key: dict(value) for key, value in specs.items()}
    for key, ylabel in PAPER_YLABELS.items():
        if key in local_specs:
            local_specs[key]["ylabel"] = ylabel
    return local_specs


def import_project_plot_style(workspace: Path):
    sys.path.insert(0, str(workspace))
    try:
        from src.tools.plot import (  # type: ignore
            DEFAULT_COLORS,
            DEFAULT_MARKERS,
            TE_PLOT_SPECS,
            apply_plot_style,
            format_te_axis,
            save_figure,
        )

        return DEFAULT_COLORS, DEFAULT_MARKERS, apply_paper_labels(TE_PLOT_SPECS), apply_plot_style, format_te_axis, save_figure
    except Exception:
        specs = {
            "seebeck": {
                "column": "Seebeck",
                "scale": 1e6,
                "title": "Seebeck Coefficient",
                "ylabel": PAPER_YLABELS["seebeck"],
            },
            "conductivity": {
                "column": "Conductivity",
                "scale": 0.01,
                "title": "Electrical Conductivity",
                "ylabel": PAPER_YLABELS["conductivity"],
            },
            "thermal_conductivity": {
                "column": "Thermal_Conductivity",
                "scale": 1,
                "title": "Total Thermal Conductivity",
                "ylabel": PAPER_YLABELS["thermal_conductivity"],
            },
            "lattice_thermal_conductivity": {
                "column": "Lattice_Thermal_Conductivity",
                "scale": 1,
                "title": "Lattice Thermal Conductivity",
                "ylabel": PAPER_YLABELS["lattice_thermal_conductivity"],
            },
            "zt": {
                "column": "ZT",
                "scale": 1,
                "title": "Figure of Merit",
                "ylabel": r"$ZT$",
            },
            "power_factor": {
                "column": "Power_Factor",
                "scale": 1e4,
                "title": "Power Factor",
                "ylabel": PAPER_YLABELS["power_factor"],
            },
        }

        def apply_plot_style(font: str = "arial", mode: str = "single") -> None:
            del font, mode
            plt.rcParams.update(
                {
                    "font.sans-serif": "Arial",
                    "mathtext.fontset": "custom",
                    "axes.linewidth": 0.9,
                    "xtick.direction": "in",
                    "ytick.direction": "in",
                    "xtick.minor.visible": True,
                    "ytick.minor.visible": True,
                    "legend.frameon": False,
                    "savefig.dpi": 600,
                }
            )

        def format_te_axis(ax, show_grid: bool = False, tick_labelsize: int = 9) -> None:
            ax.minorticks_on()
            ax.tick_params(which="both", direction="in", top=False, right=False)
            ax.tick_params(which="major", width=0.9, length=4.5, labelsize=tick_labelsize)
            ax.tick_params(which="minor", width=0.8, length=2.5)
            ax.grid(show_grid, which="major", linestyle="--", linewidth=0.4, alpha=0.45)

        def save_figure(fig, save_name: str, save_dir: str = "figures", formats=None, transparent: bool = False):
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            normalized = formats or [Path(save_name).suffix.lstrip(".") or "png"]
            stem = Path(save_name).stem
            saved = []
            for fmt in normalized:
                path = Path(save_dir) / f"{stem}.{fmt}"
                fig.savefig(path, dpi=600, bbox_inches="tight", transparent=transparent)
                saved.append(str(path))
            return saved[0]

        return FALLBACK_COLORS, FALLBACK_MARKERS, specs, apply_plot_style, format_te_axis, save_figure


def normalize_selector(raw: str) -> str:
    selector = str(raw).strip()
    selector = selector.replace("Batch-", "CHY-", 1)
    selector = selector.upper()

    if re.fullmatch(r"\d{3,5}[A-Z]", selector):
        selector = f"CHY-{selector[:-1]}-{selector[-1]}"
    elif re.fullmatch(r"CHY-\d{3,5}[A-Z]", selector):
        selector = f"{selector[:-1]}-{selector[-1]}"
    elif selector.isdigit():
        selector = f"CHY-{selector}"

    return selector


def normalize_property(name: str) -> str:
    key = str(name).strip().lower().replace("-", "_")
    if key not in PROPERTY_ALIASES:
        valid = ", ".join(sorted(set(PROPERTY_ALIASES.values())))
        raise ValueError(f"Unknown property '{name}'. Valid property keys: {valid}")
    return PROPERTY_ALIASES[key]


def load_samples(workspace: Path) -> list[dict[str, Any]]:
    samples_path = workspace / "data" / "lab" / "samples.json"
    with samples_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def resolve_samples(selectors: list[str], workspace: Path, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_sample = {row["sample_id"].upper(): row for row in samples}
    by_batch: dict[str, list[dict[str, Any]]] = {}
    for row in samples:
        by_batch.setdefault(row.get("batch_id", "").upper(), []).append(row)

    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw_selector in selectors:
        raw_path = Path(raw_selector).expanduser()
        if raw_path.suffix.lower() == ".csv" and (raw_path.exists() or (workspace / raw_path).exists()):
            csv_path = raw_path if raw_path.is_absolute() else workspace / raw_path
            sample_id = csv_path.stem
            if str(csv_path.resolve()) not in seen:
                resolved.append(
                    {
                        "sample_id": sample_id,
                        "batch_id": csv_path.parent.name,
                        "sample_name": sample_id,
                        "sample_composition": "",
                        "processed_file": str(csv_path),
                    }
                )
                seen.add(str(csv_path.resolve()))
            continue

        selector = normalize_selector(raw_selector)
        if selector in by_sample:
            matches = [by_sample[selector]]
        elif selector in by_batch:
            matches = sorted(by_batch[selector], key=lambda row: row.get("sample_id", ""))
        else:
            raise ValueError(f"Cannot resolve sample selector: {raw_selector}")

        for row in matches:
            sample_id = row["sample_id"]
            if sample_id not in seen:
                resolved.append(row)
                seen.add(sample_id)

    return resolved


def csv_path_for(workspace: Path, meta: dict[str, Any]) -> Path:
    processed_file = meta.get("processed_file")
    if not processed_file:
        raise ValueError(f"Missing processed_file for {meta.get('sample_id')}")
    path = Path(processed_file).expanduser()
    return path if path.is_absolute() else workspace / path


def default_output_dir_for_rows(workspace: Path, rows: list[dict[str, Any]]) -> Path:
    data_dirs = sorted({csv_path_for(workspace, row).resolve().parent for row in rows})
    if not data_dirs:
        return workspace / "figures"
    common_dir = Path(os.path.commonpath([str(path) for path in data_dirs]))
    return common_dir / "figures"


def load_curve(workspace: Path, meta: dict[str, Any]) -> pd.DataFrame:
    path = csv_path_for(workspace, meta)
    df = pd.read_csv(path)
    if "Temperature" not in df.columns:
        raise ValueError(f"{path} is missing Temperature column")
    return df.sort_values("Temperature")


def property_value(row: pd.Series, property_key: str, specs: dict[str, dict[str, Any]]) -> float:
    spec = specs[property_key]
    column = spec["column"]
    if column not in row.index:
        raise ValueError(f"Missing column {column} for property {property_key}")
    return float(row[column]) * float(spec.get("scale", 1))


def compact_amount(value: Any, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    text = f"{number:.{digits}f}"
    return text.rstrip("0").rstrip(".")


def parse_element_amount(composition: str, element: str) -> float | None:
    if not composition:
        return None
    pattern = rf"(?<![A-Za-z]){re.escape(element)}(\d+(?:\.\d+)?)"
    match = re.search(pattern, composition)
    return float(match.group(1)) if match else None


def first_number(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def compact_composition(composition: str) -> str:
    pairs = dict(re.findall(r"([A-Z][a-z]?)(\d+(?:\.\d+)?)", composition or ""))
    if {"Cu", "Ag", "In", "Ga"}.issubset(pairs):
        return (
            f"Cu{compact_amount(pairs['Cu'], 2)} Ag{compact_amount(pairs['Ag'], 2)}\n"
            f"In{compact_amount(pairs['In'], 2)} Ga{compact_amount(pairs['Ga'], 2)}"
        )
    return composition[:28] if composition else ""


def label_for(meta: dict[str, Any], mode: str) -> str:
    sample_id = meta.get("sample_id", "")
    sample_name = meta.get("sample_name") or sample_id
    composition = meta.get("sample_composition", "")
    if mode == "sample_name":
        return str(sample_name).replace("_", " ")
    if mode == "composition":
        return compact_composition(str(composition)) or str(sample_id)
    if mode == "compact":
        compact = compact_composition(str(composition))
        return f"{sample_id}\n{compact}" if compact else str(sample_id)
    return str(sample_id)


def resolve_x_value(meta: dict[str, Any], index: int, args: argparse.Namespace) -> tuple[float, str]:
    sample_id = str(meta.get("sample_id", ""))
    composition = str(meta.get("sample_composition") or meta.get("pristine_composition") or "")

    if args.x_field == "sample_order":
        return float(index), label_for(meta, args.label_mode)

    if args.x_field != "auto":
        raw_value = meta.get(args.x_field)
        value = first_number(str(raw_value)) if raw_value is not None else None
        if value is not None:
            return value, compact_amount(value)

    if args.x_element:
        value = parse_element_amount(composition, args.x_element)
        if value is not None:
            return value, compact_amount(value)

    raw_modifier = meta.get("modifier_amount")
    if raw_modifier is not None:
        try:
            value = float(raw_modifier)
            return value, compact_amount(value)
        except (TypeError, ValueError):
            pass

    value = first_number(meta.get("sample_name"))
    if value is not None:
        return value, compact_amount(value)

    return float(index), label_for(meta, args.label_mode)


def collect_points(
    workspace: Path,
    rows: list[dict[str, Any]],
    properties: list[str],
    temperature: float,
    specs: dict[str, dict[str, Any]],
    args: argparse.Namespace,
) -> pd.DataFrame:
    records = []
    for index, meta in enumerate(rows):
        df = load_curve(workspace, meta)
        nearest_idx = (df["Temperature"] - temperature).abs().idxmin()
        point = df.loc[nearest_idx]
        x_value, x_label = resolve_x_value(meta, index, args)
        record: dict[str, Any] = {
            "sample_id": meta.get("sample_id", ""),
            "sample_name": meta.get("sample_name", ""),
            "composition": meta.get("sample_composition", ""),
            "processed_file": str(csv_path_for(workspace, meta)),
            "target_temperature_K": temperature,
            "nearest_temperature_K": float(point["Temperature"]),
            "x": x_value,
            "x_label": x_label,
        }
        for property_key in properties:
            record[property_key] = property_value(point, property_key, specs)
        records.append(record)

    data = pd.DataFrame(records)
    if args.x_field == "sample_order" and not args.x_element:
        return data
    return data.sort_values(["x", "sample_id"]).reset_index(drop=True)


def apply_paper_style(apply_plot_style, compact: bool = False) -> None:
    apply_plot_style(font="arial", mode="single")
    base_size = 10.0 if compact else 11.0
    plt.rcParams.update(
        {
            "font.size": base_size,
            "axes.titlesize": base_size,
            "axes.labelsize": base_size + 1,
            "xtick.labelsize": base_size - 1,
            "ytick.labelsize": base_size - 1,
            "legend.fontsize": base_size,
            "lines.linewidth": 1.15,
            "lines.markersize": 4.8 if compact else 5.5,
            "axes.linewidth": 0.9,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.dpi": 600,
            "savefig.bbox": "tight",
        }
    )


def format_axis(ax, format_te_axis, grid: bool, tick_labelsize: int = 9) -> None:
    format_te_axis(ax, show_grid=grid, tick_labelsize=tick_labelsize)
    ax.set_facecolor("white")
    ax.tick_params(which="both", pad=3)
    ax.tick_params(which="major", length=PAPER_MAJOR_TICK_LENGTH)
    ax.tick_params(which="minor", length=PAPER_MINOR_TICK_LENGTH)
    ax.xaxis.labelpad = 2
    ax.yaxis.labelpad = 2
    if not grid:
        ax.grid(False)
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)


def format_temperature_axis(ax, args: argparse.Namespace) -> None:
    if args.temperature_major_tick:
        ax.xaxis.set_major_locator(ticker.MultipleLocator(args.temperature_major_tick))
    if args.temperature_minor_tick:
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(args.temperature_minor_tick))


def cycle_style(colors: list[str], markers: list[str]):
    return cycle(colors or FALLBACK_COLORS), cycle(markers or FALLBACK_MARKERS)


def apply_x_axis(ax, data: pd.DataFrame, args: argparse.Namespace, numeric: bool = True) -> None:
    if numeric:
        ax.set_xlabel(args.x_label or inferred_x_label(args))
    else:
        ax.set_xticks(data["x"])
        ax.set_xticklabels(data["x_label"], fontsize=9, linespacing=1.15)
        ax.set_xlabel(args.x_label or "Sample and nominal composition")


def inferred_x_label(args: argparse.Namespace) -> str:
    if args.x_label:
        return args.x_label
    if args.x_element:
        return f"{args.x_element} content"
    if args.x_field not in ("auto", "sample_order"):
        return args.x_field.replace("_", " ")
    return "Nominal composition"


def add_panel_label(ax, label: str | None) -> None:
    if not label:
        return
    ax.text(
        0.02,
        0.98,
        label,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=11,
        fontweight="normal",
    )


def annotate_points(ax, x_values, y_values, labels, color: str, y_offset: int = 6) -> None:
    for x_value, y_value, label in zip(x_values, y_values, labels):
        ax.annotate(
            str(label),
            (x_value, y_value),
            xytext=(0, y_offset),
            textcoords="offset points",
            ha="center",
            fontsize=7,
            color=color,
            clip_on=False,
        )


def annotate_scatter_labels(ax, data: pd.DataFrame, x_key: str, y_key: str) -> None:
    offsets = [(4, 4), (4, -8), (-26, 4), (-26, -8), (8, 10), (-32, 10)]
    for index, (_, row) in enumerate(data.iterrows()):
        dx, dy = offsets[index % len(offsets)]
        ax.annotate(
            row["sample_id"],
            (row[x_key], row[y_key]),
            xytext=(dx, dy),
            textcoords="offset points",
            fontsize=7,
            clip_on=False,
        )


def save_outputs(fig, output_dir: Path, stem: str, formats: list[str], save_figure, transparent: bool) -> list[Path]:
    stem = safe_output_stem(stem)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_figure(fig, f"{stem}.png", save_dir=str(output_dir), formats=formats, transparent=transparent)
    plt.close(fig)
    return [output_dir / f"{stem}.{fmt}" for fmt in formats]


def plot_composition_line(
    data: pd.DataFrame,
    property_key: str,
    specs: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    style: dict[str, Any],
) -> tuple[Any, str]:
    apply_paper_style(style["apply_plot_style"])
    figsize = args.figsize or (3.6, 2.7)
    fig, ax = plt.subplots(figsize=figsize)
    colors, markers = cycle_style(style["colors"], style["markers"])
    color = next(colors)
    marker = next(markers)
    numeric_x = args.x_field != "sample_order"

    ax.plot(
        data["x"],
        data[property_key],
        color=color,
        marker=marker,
        markerfacecolor=color,
        markeredgecolor=color,
        label=specs[property_key]["title"],
    )
    if args.annotate:
        annotate_points(ax, data["x"], data[property_key], data["sample_id"], color)

    ax.set_ylabel(specs[property_key]["ylabel"])
    apply_x_axis(ax, data, args, numeric=numeric_x)
    ax.margins(x=0.08, y=0.14)
    format_axis(ax, style["format_te_axis"], args.grid)
    add_panel_label(ax, args.panel_label)
    if args.title:
        ax.set_title(args.title)
    fig.tight_layout()
    return fig, f"{args.stem or 'composition_line'}_{property_key}_{int(args.temperature)}K"


def plot_composition_dual(
    data: pd.DataFrame,
    left_key: str,
    right_key: str,
    specs: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    style: dict[str, Any],
) -> tuple[Any, str]:
    apply_paper_style(style["apply_plot_style"])
    figsize = args.figsize or (4.4, 3.0)
    fig, ax1 = plt.subplots(figsize=figsize)
    ax2 = ax1.twinx()
    left_color = style["colors"][0]
    right_color = style["colors"][1]
    numeric_x = args.x_field != "sample_order"

    line1 = ax1.plot(
        data["x"],
        data[left_key],
        color=left_color,
        marker="o",
        markerfacecolor=left_color,
        markeredgecolor=left_color,
        label=specs[left_key]["title"],
    )
    line2 = ax2.plot(
        data["x"],
        data[right_key],
        color=right_color,
        marker="s",
        markerfacecolor=right_color,
        markeredgecolor=right_color,
        label=specs[right_key]["title"],
    )

    if args.annotate:
        annotate_points(ax1, data["x"], data[left_key], data[left_key].round(2), left_color, 7)
        annotate_points(ax2, data["x"], data[right_key], data[right_key].round(2), right_color, -12)

    ax1.set_ylabel(specs[left_key]["ylabel"], color=left_color)
    ax2.set_ylabel(specs[right_key]["ylabel"], color=right_color)
    ax1.margins(x=0.08, y=0.12)
    ax2.margins(x=0.08, y=0.12)
    ax1.tick_params(axis="y", colors=left_color)
    ax2.tick_params(axis="y", colors=right_color)
    ax1.spines["left"].set_color(left_color)
    ax2.spines["right"].set_color(right_color)
    apply_x_axis(ax1, data, args, numeric=numeric_x)
    format_axis(ax1, style["format_te_axis"], args.grid)
    format_axis(ax2, style["format_te_axis"], args.grid)
    ax2.tick_params(which="both", right=True, labelright=True, left=False, labelleft=False)
    add_panel_label(ax1, args.panel_label)
    if args.title:
        ax1.set_title(args.title)
    ax1.legend(line1 + line2, [line.get_label() for line in line1 + line2], loc="best", frameon=False)
    fig.tight_layout()
    return fig, f"{args.stem or 'composition_dual'}_{left_key}_{right_key}_{int(args.temperature)}K"


def plot_temperature_overlay(
    rows: list[dict[str, Any]],
    property_key: str,
    specs: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    style: dict[str, Any],
    workspace: Path,
    normalized: bool = False,
) -> tuple[Any, str]:
    apply_paper_style(style["apply_plot_style"])
    figsize = args.figsize or (3.6, 2.7)
    fig, ax = plt.subplots(figsize=figsize)
    colors, markers = cycle_style(style["colors"], style["markers"])
    spec = specs[property_key]
    column = spec["column"]

    for meta in rows:
        df = load_curve(workspace, meta)
        if column not in df.columns:
            continue
        y = df[column].astype(float) * float(spec.get("scale", 1))
        ylabel = spec["ylabel"]
        if normalized:
            if args.normalize_by == "first":
                divisor = y.iloc[0]
            elif args.normalize_by == "target":
                idx = (df["Temperature"] - args.temperature).abs().idxmin()
                divisor = y.loc[idx]
            else:
                divisor = y.max()
            if divisor != 0:
                y = y / divisor
            ylabel = NORMALIZED_YLABELS.get(property_key, f"Normalized {spec['title']}")
        color = next(colors)
        marker = next(markers)
        ax.plot(
            df["Temperature"],
            y,
            color=color,
            marker=marker,
            markerfacecolor=color,
            markeredgecolor=color,
            label=label_for(meta, args.label_mode),
        )

    ax.set_xlabel(r"$T$ (K)")
    ax.set_ylabel(ylabel)
    format_axis(ax, style["format_te_axis"], args.grid)
    format_temperature_axis(ax, args)
    add_panel_label(ax, args.panel_label)
    if args.title:
        ax.set_title(args.title)
    ax.legend(loc="best", frameon=False, fontsize=10)
    fig.tight_layout()
    mode = "normalized_temperature" if normalized else "temperature_overlay"
    return fig, f"{args.stem or mode}_{property_key}"


def plot_temperature_dual(
    rows: list[dict[str, Any]],
    left_key: str,
    right_key: str,
    specs: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    style: dict[str, Any],
    workspace: Path,
) -> tuple[Any, str]:
    apply_paper_style(style["apply_plot_style"])
    figsize = args.figsize or (4.2, 2.9)
    fig, ax1 = plt.subplots(figsize=figsize)
    ax2 = ax1.twinx()
    colors, markers = cycle_style(style["colors"], style["markers"])
    left_spec = specs[left_key]
    right_spec = specs[right_key]

    for meta in rows:
        df = load_curve(workspace, meta)
        color = next(colors)
        marker = next(markers)
        label = label_for(meta, args.label_mode)
        ax1.plot(
            df["Temperature"],
            df[left_spec["column"]] * float(left_spec.get("scale", 1)),
            color=color,
            marker=marker,
            markerfacecolor=color,
            markeredgecolor=color,
            label=label,
        )
        ax2.plot(
            df["Temperature"],
            df[right_spec["column"]] * float(right_spec.get("scale", 1)),
            color=color,
            marker=marker,
            markerfacecolor="white",
            markeredgecolor=color,
            linestyle="--",
            label="_nolegend_",
        )

    ax1.set_xlabel(r"$T$ (K)")
    ax1.set_ylabel(left_spec["ylabel"], color=style["colors"][0])
    ax2.set_ylabel(right_spec["ylabel"], color=style["colors"][1])
    ax1.tick_params(axis="y", colors=style["colors"][0])
    ax2.tick_params(axis="y", colors=style["colors"][1])
    format_axis(ax1, style["format_te_axis"], args.grid)
    format_axis(ax2, style["format_te_axis"], args.grid)
    format_temperature_axis(ax1, args)
    format_temperature_axis(ax2, args)
    ax2.tick_params(which="both", right=True, labelright=True, left=False, labelleft=False)
    add_panel_label(ax1, args.panel_label)
    if args.title:
        ax1.set_title(args.title)
    handles1, labels1 = ax1.get_legend_handles_labels()
    if len(rows) > 2:
        fig.legend(
            handles1,
            labels1,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.965),
            ncol=min(len(labels1), 4),
            frameon=False,
            fontsize=9,
            borderaxespad=0.0,
            handlelength=1.5,
            columnspacing=1.1,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.915))
    else:
        ax1.legend(handles1, labels1, loc="best", frameon=False, fontsize=9)
        fig.tight_layout()
    return fig, f"{args.stem or 'temperature_dual'}_{left_key}_{right_key}"


def plot_tradeoff_scatter(
    data: pd.DataFrame,
    x_key: str,
    y_key: str,
    color_key: str | None,
    specs: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    style: dict[str, Any],
) -> tuple[Any, str]:
    apply_paper_style(style["apply_plot_style"])
    figsize = args.figsize or (3.4, 2.8)
    fig, ax = plt.subplots(figsize=figsize)

    if color_key:
        scatter = ax.scatter(
            data[x_key],
            data[y_key],
            c=data[color_key],
            cmap="viridis",
            s=34,
            edgecolors="black",
            linewidths=0.35,
            zorder=3,
        )
        cbar = fig.colorbar(scatter, ax=ax, pad=0.02)
        cbar.set_label(specs[color_key]["ylabel"])
        cbar.ax.tick_params(labelsize=9)
    else:
        colors, markers = cycle_style(style["colors"], style["markers"])
        for _, row in data.iterrows():
            color = next(colors)
            marker = next(markers)
            ax.scatter(
                row[x_key],
                row[y_key],
                color=color,
                marker=marker,
                s=38,
                edgecolors=color,
                linewidths=0.6,
                label=row["sample_id"],
                zorder=3,
            )

    if args.annotate:
        annotate_scatter_labels(ax, data, x_key, y_key)

    ax.set_xlabel(specs[x_key]["ylabel"])
    ax.set_ylabel(specs[y_key]["ylabel"])
    ax.margins(x=0.10, y=0.12)
    format_axis(ax, style["format_te_axis"], args.grid)
    add_panel_label(ax, args.panel_label)
    if args.title:
        ax.set_title(args.title)
    if not color_key and len(data) <= 8:
        ax.legend(loc="best", frameon=False, fontsize=9)
    fig.tight_layout()
    suffix = f"_{color_key}" if color_key else ""
    return fig, f"{args.stem or 'tradeoff_scatter'}_{x_key}_vs_{y_key}{suffix}_{int(args.temperature)}K"


def plot_summary_panels(
    rows: list[dict[str, Any]],
    properties: list[str],
    specs: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    style: dict[str, Any],
    workspace: Path,
) -> tuple[Any, str]:
    apply_paper_style(style["apply_plot_style"], compact=True)
    n = len(properties)
    if n <= 4:
        ncols = 2
    else:
        ncols = 3
    nrows = (n + ncols - 1) // ncols
    default_width = 8.8 if ncols == 3 else 6.1
    default_height = 2.65 * nrows
    figsize = args.figsize or (default_width, default_height)
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, squeeze=False)
    panel_labels = [f"({chr(97 + i)})" for i in range(n)]

    for index, property_key in enumerate(properties):
        ax = axes[index // ncols][index % ncols]
        spec = specs[property_key]
        colors, markers = cycle_style(style["colors"], style["markers"])
        for meta in rows:
            df = load_curve(workspace, meta)
            column = spec["column"]
            if column not in df.columns:
                continue
            color = next(colors)
            marker = next(markers)
            ax.plot(
                df["Temperature"],
                df[column] * float(spec.get("scale", 1)),
                color=color,
                marker=marker,
                markerfacecolor=color,
                markeredgecolor=color,
                label=label_for(meta, args.label_mode),
            )
        ax.set_xlabel(r"$T$ (K)")
        ax.set_ylabel(spec["ylabel"])
        format_axis(ax, style["format_te_axis"], args.grid, tick_labelsize=9)
        format_temperature_axis(ax, args)
        add_panel_label(ax, panel_labels[index] if args.panel_labels else None)

    for index in range(n, nrows * ncols):
        axes[index // ncols][index % ncols].axis("off")

    handles, labels = axes[0][0].get_legend_handles_labels()
    if handles:
        fig.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.965),
            ncol=min(len(labels), 4),
            frameon=False,
            fontsize=10,
            borderaxespad=0.0,
            handlelength=1.5,
            columnspacing=1.3,
        )
    if args.title:
        fig.suptitle(args.title, y=0.985, fontsize=11)
        top = 0.875
    else:
        top = 0.915 if handles else 0.96
    fig.subplots_adjust(
        left=0.075,
        right=0.985,
        bottom=0.095,
        top=top,
        wspace=0.34,
        hspace=0.36,
    )
    return fig, args.stem or "summary_panels"


def default_stem_prefix(args: argparse.Namespace, rows: list[dict[str, Any]]) -> str:
    selectors = "_".join(str(row.get("sample_id", "")).replace("-", "") for row in rows[:4])
    if len(rows) > 4:
        selectors += f"_plus{len(rows) - 4}"
    return f"{args.plot_type}_{selectors}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", default=".", help="Path to te_agent_workspace.")
    parser.add_argument("--samples", nargs="+", required=True, help="Sample IDs, batch IDs, or processed CSV paths.")
    parser.add_argument(
        "--plot-type",
        choices=[
            "composition-line",
            "composition-dual",
            "temperature-overlay",
            "normalized-temperature",
            "temperature-dual",
            "tradeoff-scatter",
            "summary-panels",
        ],
        required=True,
    )
    parser.add_argument("--temperature", type=float, default=300.0, help="Target temperature in K for composition/scatter plots.")
    parser.add_argument("--property", default="seebeck", help="Property for single-property plot types.")
    parser.add_argument("--properties", nargs="+", default=None, help="Properties for summary-panels.")
    parser.add_argument("--left-property", default="seebeck", help="Left y-axis property for dual-axis plots.")
    parser.add_argument("--right-property", default="conductivity", help="Right y-axis property for dual-axis plots.")
    parser.add_argument("--x-property", default="seebeck", help="X property for tradeoff-scatter.")
    parser.add_argument("--y-property", default="conductivity", help="Y property for tradeoff-scatter.")
    parser.add_argument("--color-property", default=None, help="Optional point color property for tradeoff-scatter.")
    parser.add_argument("--x-element", default=None, help="Element symbol to parse from composition, e.g. Ag, Cu, Sn.")
    parser.add_argument(
        "--x-field",
        default="auto",
        help="Metadata field for x value. Use sample_order for categorical/sample spacing.",
    )
    parser.add_argument("--x-label", default=None)
    parser.add_argument("--label-mode", choices=["sample_id", "sample_name", "composition", "compact"], default="sample_id")
    parser.add_argument("--normalize-by", choices=["max", "first", "target"], default="max")
    parser.add_argument("--temperature-major-tick", type=float, default=100.0, help="Major tick spacing for temperature x axes.")
    parser.add_argument("--temperature-minor-tick", type=float, default=50.0, help="Minor tick spacing for temperature x axes.")
    parser.add_argument("--figsize", nargs=2, type=float, default=None, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory. Default: a figures folder beside the processed input data.",
    )
    parser.add_argument("--stem", default=None)
    parser.add_argument("--formats", nargs="+", default=["svg"])
    parser.add_argument("--grid", action="store_true", help="Show light major grid lines.")
    parser.add_argument("--annotate", action="store_true", help="Annotate points.")
    parser.add_argument("--panel-label", default=None, help="Single panel label, e.g. '(a)'.")
    parser.add_argument("--panel-labels", action="store_true", default=False, help="Show panel labels for summary-panels.")
    parser.add_argument("--no-panel-labels", action="store_false", dest="panel_labels")
    parser.add_argument("--title", default=None)
    parser.add_argument("--transparent", action="store_true", help="Save with transparent figure background.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()

    colors, markers, specs, apply_plot_style, format_te_axis, save_figure = import_project_plot_style(workspace)
    style = {
        "colors": list(colors),
        "markers": list(markers),
        "apply_plot_style": apply_plot_style,
        "format_te_axis": format_te_axis,
    }

    rows = resolve_samples(args.samples, workspace, load_samples(workspace))
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser()
        if not output_dir.is_absolute():
            output_dir = workspace / output_dir
    else:
        output_dir = default_output_dir_for_rows(workspace, rows)
    if not args.stem:
        args.stem = default_stem_prefix(args, rows)
    args.stem = safe_output_stem(args.stem)
    output_dir.mkdir(parents=True, exist_ok=True)

    property_key = normalize_property(args.property)
    left_key = normalize_property(args.left_property)
    right_key = normalize_property(args.right_property)
    x_key = normalize_property(args.x_property)
    y_key = normalize_property(args.y_property)
    color_key = normalize_property(args.color_property) if args.color_property else None
    summary_properties = [normalize_property(item) for item in (args.properties or [
        "seebeck",
        "conductivity",
        "power_factor",
        "thermal_conductivity",
        "lattice_thermal_conductivity",
        "zt",
    ])]

    if args.plot_type == "composition-line":
        data = collect_points(workspace, rows, [property_key], args.temperature, specs, args)
        fig, stem = plot_composition_line(data, property_key, specs, args, style)
        stem = safe_output_stem(stem)
        data.to_csv(output_dir / f"{stem}.csv", index=False)
    elif args.plot_type == "composition-dual":
        data = collect_points(workspace, rows, [left_key, right_key], args.temperature, specs, args)
        fig, stem = plot_composition_dual(data, left_key, right_key, specs, args, style)
        stem = safe_output_stem(stem)
        data.to_csv(output_dir / f"{stem}.csv", index=False)
    elif args.plot_type == "temperature-overlay":
        fig, stem = plot_temperature_overlay(rows, property_key, specs, args, style, workspace, normalized=False)
    elif args.plot_type == "normalized-temperature":
        fig, stem = plot_temperature_overlay(rows, property_key, specs, args, style, workspace, normalized=True)
    elif args.plot_type == "temperature-dual":
        fig, stem = plot_temperature_dual(rows, left_key, right_key, specs, args, style, workspace)
    elif args.plot_type == "tradeoff-scatter":
        properties = [x_key, y_key] + ([color_key] if color_key else [])
        data = collect_points(workspace, rows, properties, args.temperature, specs, args)
        fig, stem = plot_tradeoff_scatter(data, x_key, y_key, color_key, specs, args, style)
        stem = safe_output_stem(stem)
        data.to_csv(output_dir / f"{stem}.csv", index=False)
    elif args.plot_type == "summary-panels":
        fig, stem = plot_summary_panels(rows, summary_properties, specs, args, style, workspace)
    else:
        raise ValueError(f"Unsupported plot type {args.plot_type}")

    paths = save_outputs(fig, output_dir, stem, args.formats, save_figure, args.transparent)
    for path in paths:
        print(f"figure: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

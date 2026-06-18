#!/usr/bin/env python3
"""Create house-style room-temperature Seebeck/conductivity comparison plots."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def set_matplotlib_cache() -> None:
    cache_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "te_agent_matplotlib"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))


set_matplotlib_cache()

import matplotlib.pyplot as plt
import pandas as pd


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


def load_samples(workspace: Path) -> list[dict]:
    samples_path = workspace / "data" / "lab" / "samples.json"
    with samples_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def resolve_samples(selectors: list[str], samples: list[dict]) -> list[dict]:
    by_sample = {row["sample_id"].upper(): row for row in samples}
    by_batch: dict[str, list[dict]] = {}
    for row in samples:
        by_batch.setdefault(row.get("batch_id", "").upper(), []).append(row)

    resolved: list[dict] = []
    seen: set[str] = set()

    for raw_selector in selectors:
        selector = normalize_selector(raw_selector)
        matches: list[dict] = []

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


def compact_amount(value: str | None, digits: int = 2) -> str:
    if value is None:
        return ""
    number = float(value)
    return f"{number:.{digits}f}"


def compact_composition(composition: str) -> str:
    pairs = dict(re.findall(r"([A-Z][a-z]?)(\d+(?:\.\d+)?)", composition or ""))
    if {"Cu", "Ag", "In", "Ga"}.issubset(pairs):
        line_1 = f"Cu{compact_amount(pairs['Cu'], 2)} Ag{compact_amount(pairs['Ag'], 2)}"
        in_amount = float(pairs["In"])
        ga_amount = float(pairs["Ga"])
        if abs(in_amount - ga_amount) < 1e-9:
            line_2 = f"In/Ga {in_amount:.3f}" if in_amount != 0.5 else "In/Ga 0.50"
        else:
            line_2 = f"In{compact_amount(pairs['In'], 3)} Ga{compact_amount(pairs['Ga'], 3)}"
        return f"{line_1}\n{line_2}"

    if composition:
        return composition[:32]
    return ""


def collect_points(workspace: Path, rows: list[dict], target_temperature: float) -> pd.DataFrame:
    records = []
    for meta in rows:
        processed_file = meta.get("processed_file")
        if not processed_file:
            raise ValueError(f"Missing processed_file for {meta.get('sample_id')}")

        raw_path = Path(processed_file).expanduser()
        csv_path = raw_path if raw_path.is_absolute() else workspace / raw_path
        try:
            display_processed_file = str(csv_path.relative_to(workspace))
        except ValueError:
            display_processed_file = str(csv_path)

        df = pd.read_csv(csv_path)
        required = {"Temperature", "Seebeck", "Conductivity"}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"{csv_path} missing columns: {', '.join(sorted(missing))}")

        idx = (df["Temperature"] - target_temperature).abs().idxmin()
        point = df.loc[idx]
        composition = meta.get("sample_composition", "")
        sample_id = meta["sample_id"]
        records.append(
            {
                "sample_id": sample_id,
                "sample_name": meta.get("sample_name", sample_id),
                "composition": composition,
                "x_label": f"{sample_id}\n{compact_composition(composition)}",
                "processed_file": display_processed_file,
                "temperature_K": float(point["Temperature"]),
                "seebeck_V_per_K": float(point["Seebeck"]),
                "seebeck_uV_per_K": float(point["Seebeck"] * 1e6),
                "conductivity_S_per_m": float(point["Conductivity"]),
                "conductivity_S_per_cm": float(point["Conductivity"] * 0.01),
            }
        )

    return pd.DataFrame(records)


def import_project_plot_style(workspace: Path):
    sys.path.insert(0, str(workspace))
    try:
        from src.tools.plot import DEFAULT_COLORS, apply_plot_style, format_te_axis, save_figure

        return DEFAULT_COLORS, apply_plot_style, format_te_axis, save_figure
    except Exception:
        default_colors = [
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

        def apply_plot_style(font: str = "arial", mode: str = "single") -> None:
            plt.rcParams.update(
                {
                    "font.sans-serif": "Arial" if font == "arial" else "Times New Roman",
                    "axes.linewidth": 1,
                    "xtick.direction": "in",
                    "ytick.direction": "in",
                    "xtick.minor.visible": True,
                    "ytick.minor.visible": True,
                    "legend.frameon": False,
                    "savefig.dpi": 300,
                }
            )

        def format_te_axis(ax, show_grid: bool = False, tick_labelsize: int = 11) -> None:
            ax.minorticks_on()
            ax.tick_params(which="both", direction="in", top=False, right=False)
            ax.tick_params(which="major", width=1, length=6, labelsize=tick_labelsize)
            ax.tick_params(which="minor", width=1, length=3)
            if show_grid:
                ax.grid(True, which="major", linestyle="--", linewidth=0.5, alpha=0.5)
            else:
                ax.grid(False)

        def save_figure(fig, save_name: str, save_dir: str, formats=None, transparent: bool = False):
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            formats = formats or ["png"]
            first = None
            stem = Path(save_name).stem
            for fmt in formats:
                path = Path(save_dir) / f"{stem}.{fmt}"
                fig.savefig(path, dpi=300, bbox_inches="tight", transparent=transparent)
                first = first or str(path)
            return first

        return default_colors, apply_plot_style, format_te_axis, save_figure


def make_plot(
    workspace: Path,
    data: pd.DataFrame,
    output_dir: Path,
    stem: str,
    formats: list[str],
    kind: str,
    target_temperature: float,
) -> list[Path]:
    colors, apply_plot_style, format_te_axis, save_figure = import_project_plot_style(workspace)
    apply_plot_style(font="arial", mode="single")

    seebeck_color = colors[0]
    conductivity_color = colors[1]
    x_positions = list(range(len(data)))

    width = max(7.0, 1.05 * len(data) + 2.2)
    fig, ax1 = plt.subplots(figsize=(width, 5.2))
    ax2 = ax1.twinx()

    if kind == "bar":
        bar_width = 0.36
        ax1.bar(
            [x - bar_width / 2 for x in x_positions],
            data["seebeck_uV_per_K"],
            width=bar_width,
            color=seebeck_color,
            alpha=0.85,
            label="Seebeck",
        )
        ax2.bar(
            [x + bar_width / 2 for x in x_positions],
            data["conductivity_S_per_cm"],
            width=bar_width,
            color=conductivity_color,
            alpha=0.85,
            label="Electrical conductivity",
        )
    else:
        ax1.plot(
            x_positions,
            data["seebeck_uV_per_K"],
            color=seebeck_color,
            marker="o",
            markerfacecolor=seebeck_color,
            markeredgecolor=seebeck_color,
            label="Seebeck",
        )
        ax2.plot(
            x_positions,
            data["conductivity_S_per_cm"],
            color=conductivity_color,
            marker="s",
            markerfacecolor=conductivity_color,
            markeredgecolor=conductivity_color,
            label="Electrical conductivity",
        )

    format_te_axis(ax1, show_grid=False, tick_labelsize=11)
    format_te_axis(ax2, show_grid=False, tick_labelsize=11)
    ax2.tick_params(which="both", right=True, labelright=True, left=False, labelleft=False)

    ax1.set_xticks(x_positions)
    ax1.set_xticklabels(data["x_label"], fontsize=9, linespacing=1.2)
    ax1.set_ylabel(r"$S$ ($\mu$V K$^{-1}$)", color=seebeck_color)
    ax2.set_ylabel(r"$\sigma$ (S cm$^{-1}$)", color=conductivity_color)
    ax1.tick_params(axis="y", colors=seebeck_color)
    ax2.tick_params(axis="y", colors=conductivity_color)
    ax1.spines["left"].set_color(seebeck_color)
    ax2.spines["right"].set_color(conductivity_color)
    ax1.set_xlabel("Nominal composition")
    fig.suptitle(f"Room-temperature transport near {target_temperature:.0f} K", y=0.995)

    for idx, row in data.iterrows():
        ax1.annotate(
            f"{row['seebeck_uV_per_K']:.0f}",
            (idx, row["seebeck_uV_per_K"]),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=seebeck_color,
        )
        ax2.annotate(
            f"{row['conductivity_S_per_cm']:.0f}",
            (idx, row["conductivity_S_per_cm"]),
            xytext=(0, -13),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=conductivity_color,
        )

    handles_1, labels_1 = ax1.get_legend_handles_labels()
    handles_2, labels_2 = ax2.get_legend_handles_labels()
    fig.legend(
        handles_1 + handles_2,
        labels_1 + labels_2,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.955),
        ncol=2,
        fontsize=9,
        frameon=False,
    )

    fig.tight_layout()
    fig.subplots_adjust(left=0.10, right=0.90, bottom=0.22, top=0.80)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_figure(fig, f"{stem}.png", save_dir=str(output_dir), formats=formats)
    plt.close(fig)

    return [output_dir / f"{stem}.{fmt}" for fmt in formats]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".", help="Path to the TE workflow root.")
    parser.add_argument("--samples", nargs="+", required=True, help="Sample or batch selectors.")
    parser.add_argument("--temperature", type=float, default=300.0, help="Target temperature in K.")
    parser.add_argument("--kind", choices=["line", "bar"], default="line", help="Plot form.")
    parser.add_argument("--output-dir", default="results/plots/room_temp_composition")
    parser.add_argument("--stem", default=None, help="Output filename stem.")
    parser.add_argument("--formats", nargs="+", default=["png", "pdf"], help="Output formats.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = workspace / output_dir

    samples = resolve_samples(args.samples, load_samples(workspace))
    data = collect_points(workspace, samples, args.temperature)

    safe_selectors = "_vs_".join(normalize_selector(item).replace("-", "") for item in args.samples)
    stem = args.stem or f"room_temp_{safe_selectors}_dual_axis"
    csv_path = output_dir / f"{stem}.csv"
    output_dir.mkdir(parents=True, exist_ok=True)
    data.to_csv(csv_path, index=False)

    figure_paths = make_plot(
        workspace=workspace,
        data=data,
        output_dir=output_dir,
        stem=stem,
        formats=args.formats,
        kind=args.kind,
        target_temperature=args.temperature,
    )

    print(data[["sample_id", "temperature_K", "seebeck_uV_per_K", "conductivity_S_per_cm", "composition"]].to_string(index=False))
    for path in figure_paths:
        print(f"figure: {path}")
    print(f"csv: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

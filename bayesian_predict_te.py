#!/usr/bin/env python3
"""Bayesian local surrogate predictions for processed TE lab data.

The script builds conservative one-dimensional Gaussian-process models for
comparable local composition series, such as one modifier amount on the same
matrix composition. It is intended for next-experiment planning, not as a
fully automated global optimizer.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_CACHE_ROOT = Path(tempfile.gettempdir()) / "codex_te_bayes_cache"
(_CACHE_ROOT / "matplotlib").mkdir(parents=True, exist_ok=True)
(_CACHE_ROOT / "xdg").mkdir(parents=True, exist_ok=True)
os.environ.setdefault(
    "MPLCONFIGDIR", str(_CACHE_ROOT / "matplotlib")
)
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_ROOT / "xdg"))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern


DEFAULT_TARGET = "ZT_max"
DEFAULT_OUTPUT_DIR = Path("results/bayesian_predictions")
DEFAULT_FIGURE_DIR = Path("outputs/figures/bayesian_predictions")
FORMULA_TOKEN_RE = re.compile(r"([A-Z][a-z]?)(\d*(?:\.\d+)?)")


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, tuple, dict)) and len(value) == 0:
        return True
    return False


def clean(value: Any) -> str:
    if is_empty(value):
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if not is_empty(item))
    return str(value).strip()


def merge_nonempty(base: dict[str, Any], feature: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in feature.items():
        if is_empty(value) and not is_empty(merged.get(key)):
            continue
        merged[key] = value
    return merged


def format_amount(value: float) -> str:
    if abs(value - round(value)) < 1e-10:
        return str(int(round(value)))
    return f"{value:.6g}"


def normalize_composition(value: Any) -> str:
    return re.sub(r"\s+", "", clean(value))


def markdown_cell(value: Any) -> str:
    return clean(value).replace("|", "\\|")


def parse_formula_tokens(formula: str) -> list[tuple[str, float]]:
    tokens: list[tuple[str, float]] = []
    for element, amount_text in FORMULA_TOKEN_RE.findall(formula):
        amount = float(amount_text) if amount_text else 1.0
        tokens.append((element, amount))
    return tokens


def reconstruct_formula(tokens: list[tuple[str, float]]) -> str:
    return "".join(f"{element}{format_amount(amount)}" for element, amount in tokens)


def site_elements(site: Any) -> list[str]:
    text = clean(site)
    return re.findall(r"[A-Z][a-z]?", text)


def infer_optimization_type(row: pd.Series) -> str:
    existing = clean(row.get("optimization_type"))
    if existing:
        return existing

    text = clean(row.get("Samples")) or clean(row.get("sample_name"))
    lower = text.lower()
    if "pristine" in lower:
        return "pristine"
    if "deficiency" in lower or "defficiency" in lower or "defficicency" in lower:
        return "deficiency"
    if "alloy" in lower:
        return "alloy"
    if "composite" in lower:
        return "composite"
    if "dope" in lower or "excess" in lower:
        return "dope"
    return ""


def infer_modifier_label_from_name(row: pd.Series) -> str:
    text = clean(row.get("sample_name")) or clean(row.get("Samples"))
    if not text or "-" not in text:
        return ""

    tail = text.split("-", 1)[1]
    tail = re.sub(r"^(?:0?\.\d+|\d+(?:\.\d+)?)", "", tail)
    tail = re.sub(r"[-_](?:0?\.\d+|0_\d+|\d{2,3}|\d+(?:\.\d+)?)$", "", tail)
    tail = tail.replace("-", "+").replace("_", "")
    tail = tail.strip("+ ")
    if re.search(r"[A-Z][a-z]?", tail):
        return tail
    return ""


def infer_modifier_label(row: pd.Series) -> str:
    named_modifier = infer_modifier_label_from_name(row)
    modifier_elements = row.get("modifier_elements")
    has_multiple_modifier_elements = (
        isinstance(modifier_elements, list) and len(modifier_elements) > 1
    )
    if named_modifier and (clean(row.get("reference_id")) or has_multiple_modifier_elements):
        return named_modifier

    for key in ("modifier_element", "modifier_species"):
        value = clean(row.get(key))
        if value:
            return value

    if named_modifier:
        return named_modifier

    text = clean(row.get("Samples")) or clean(row.get("sample_name"))
    if "pristine" in text.lower():
        return ""

    match = re.search(
        r"([A-Z][a-z]?(?:\s*&\s*[A-Z][a-z]?)?)_?\s*"
        r"(?:dope|def+ic+iency|deficiency|excess)",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return re.sub(r"\s+", "", match.group(1).replace("&", ""))

    text_without_leading_amount = re.sub(r"^\d+(?:\.\d+)?_", "", text)
    match = re.match(
        r"([A-Z][A-Za-z0-9]*?)(?:_\d|_alloy|_dope|\s|$)",
        text_without_leading_amount,
    )
    if match:
        return match.group(1)

    return ""


def infer_modifier_amount(row: pd.Series, modifier_label: str) -> float:
    existing = row.get("modifier_amount")
    try:
        if not is_empty(existing):
            return float(existing)
    except (TypeError, ValueError):
        pass

    text = clean(row.get("Samples")) or clean(row.get("sample_name"))
    if not text:
        return np.nan
    if "pristine" in text.lower():
        return 0.0

    if modifier_label:
        escaped = re.escape(modifier_label)
        patterns = [
            rf"{escaped}[^0-9]{{0,30}}(\d+(?:\.\d+)?)",
            rf"(\d+(?:\.\d+)?)_?{escaped}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return float(match.group(1))

    match = re.search(
        r"(?:dope|def+ic+iency|deficiency|excess|alloy|composite)"
        r"[^0-9]{0,20}(\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return float(match.group(1))

    match = re.match(r"(\d+(?:\.\d+)?)_", text)
    if match:
        return float(match.group(1))

    for match in re.finditer(r"(?<![A-Za-z])(\d+(?:\.\d+)?)", text):
        value = float(match.group(1))
        if value <= 1.0:
            return value

    return np.nan


def infer_matrix_from_substitution(row: pd.Series, modifier_label: str) -> str:
    formula = normalize_composition(row.get("sample_composition"))
    if not formula:
        return ""

    if "pristine" in (clean(row.get("Samples")) or clean(row.get("sample_name"))).lower():
        return formula

    modifier_elements = re.findall(r"[A-Z][a-z]?", modifier_label)
    hosts = site_elements(row.get("modifier_site"))
    tokens = parse_formula_tokens(formula)

    # Only infer a matrix for simple substitution cases. Composite additions,
    # multi-phase strings, and ambiguous labels stay with their explicit metadata.
    if not hosts or len(modifier_elements) != 1 or "+" in formula or "-" in formula:
        return ""

    modifier = modifier_elements[0]
    modifier_amount = 0.0
    output_tokens: list[tuple[str, float]] = []
    for element, amount in tokens:
        if element == modifier:
            modifier_amount += amount
        else:
            output_tokens.append((element, amount))

    if modifier_amount == 0:
        return ""

    host_increment = modifier_amount / len(hosts)
    adjusted_tokens: list[tuple[str, float]] = []
    seen_hosts: set[str] = set()
    for element, amount in output_tokens:
        if element in hosts:
            adjusted_tokens.append((element, amount + host_increment))
            seen_hosts.add(element)
        else:
            adjusted_tokens.append((element, amount))

    if len(seen_hosts) != len(hosts):
        return ""
    return reconstruct_formula(adjusted_tokens)


def initial_matrix_key(row: pd.Series, modifier_label: str) -> str:
    for key in ("matrix_composition", "pristine_composition"):
        value = normalize_composition(row.get(key))
        if value:
            return value

    inferred = infer_matrix_from_substitution(row, modifier_label)
    if inferred:
        return inferred

    return clean(row.get("batch_id"))


def finalize_table(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty:
        return table

    for column, default in {
        "batch_id": "",
        "reference_id": "",
        "modifier_site": "",
        "modifier_elements": "",
        "matrix_composition": "",
        "pristine_composition": "",
        "sample_composition": "",
        "optimization_type": "",
        "modifier_element": "",
        "modifier_species": "",
        "Samples": "",
        "sample_name": "",
    }.items():
        if column not in table.columns:
            table[column] = default

    table["optimization_type_clean"] = table.apply(infer_optimization_type, axis=1)
    table["modifier_label"] = table.apply(infer_modifier_label, axis=1)
    table["amount_num"] = [
        infer_modifier_amount(row, label)
        for (_, row), label in zip(table.iterrows(), table["modifier_label"])
    ]
    table["site_key"] = table["modifier_site"].map(clean)
    table["matrix_key"] = [
        initial_matrix_key(row, label)
        for (_, row), label in zip(table.iterrows(), table["modifier_label"])
    ]

    # Fill sparse metadata within a batch/reference series when one row has
    # enough information to identify the shared matrix.
    fallback = table["matrix_key"].eq(table["batch_id"].map(clean)) | table["matrix_key"].eq("")
    group_keys = [
        "batch_id",
        "reference_id",
        "optimization_type_clean",
        "modifier_label",
        "site_key",
    ]
    for _, group in table.groupby(group_keys, dropna=False):
        batch_ids = set(group["batch_id"].dropna().astype(str))
        known = sorted(
            {
                key
                for key in group["matrix_key"].dropna().astype(str)
                if key and key not in batch_ids
            }
        )
        if len(known) == 1:
            table.loc[group.index[fallback.loc[group.index]], "matrix_key"] = known[0]

    return table


def load_lab_table(root: Path) -> pd.DataFrame:
    metadata_path = root / "data/lab/samples.json"
    metadata = {
        row["sample_id"]: row for row in json.loads(metadata_path.read_text())
    }

    rows: list[dict[str, Any]] = []
    for feature_path in sorted(root.glob("data/processed/*-processed/extracted_features.json")):
        payload = json.loads(feature_path.read_text())
        for feature_row in payload.get("samples_data", []):
            sample_id = feature_row.get("sample_id")
            merged = merge_nonempty(metadata.get(sample_id, {}), feature_row)
            merged["feature_file"] = str(feature_path)
            merged["source_kind"] = "lab_data"
            rows.append(merged)

    return finalize_table(pd.DataFrame(rows))


def load_reference_table(root: Path, reference_id: str | None) -> pd.DataFrame:
    metadata_path = root / "data/reference/samples.json"
    metadata: dict[str, dict[str, Any]] = {}
    if metadata_path.exists():
        metadata = {
            row["sample_id"]: row for row in json.loads(metadata_path.read_text())
        }

    feature_paths: list[Path]
    if reference_id:
        feature_paths = [
            root / "data/reference/features" / reference_id / "extracted_features.json"
        ]
    else:
        feature_paths = sorted(root.glob("data/reference/features/*/extracted_features.json"))

    rows: list[dict[str, Any]] = []
    for feature_path in feature_paths:
        if not feature_path.exists():
            continue
        payload = json.loads(feature_path.read_text())
        for feature_row in payload.get("samples_data", []):
            sample_id = feature_row.get("sample_id")
            merged = merge_nonempty(metadata.get(sample_id, {}), feature_row)
            merged["feature_file"] = str(feature_path)
            merged["batch_id"] = clean(merged.get("batch_id")) or clean(
                merged.get("reference_id")
            )
            merged["source_kind"] = "own_reference_database"
            rows.append(merged)

    return finalize_table(pd.DataFrame(rows))


def load_source_table(
    root: Path,
    source: str,
    reference_id: str | None,
) -> pd.DataFrame:
    tables: list[pd.DataFrame] = []
    if source in {"lab", "all"}:
        tables.append(load_lab_table(root))
    if source in {"reference", "all"}:
        tables.append(load_reference_table(root, reference_id))

    tables = [table for table in tables if not table.empty]
    if not tables:
        return pd.DataFrame()
    return pd.concat(tables, ignore_index=True)


def build_composition_index(table: pd.DataFrame) -> dict[str, list[pd.Series]]:
    composition_index: dict[str, list[pd.Series]] = {}
    for _, row in table.iterrows():
        composition = normalize_composition(row.get("sample_composition"))
        if composition:
            composition_index.setdefault(composition, []).append(row)
    return composition_index


@dataclass
class LocalModelResult:
    series_id: str
    matrix: str
    optimization_type: str
    modifier: str
    site: str
    observations: pd.DataFrame
    grid: pd.DataFrame
    candidates: pd.DataFrame
    kernel: str
    current_best: float


def expected_improvement(
    mean: np.ndarray,
    std: np.ndarray,
    incumbent: float,
    minimize: bool,
) -> np.ndarray:
    if minimize:
        improvement = incumbent - mean
    else:
        improvement = mean - incumbent
    z = np.divide(improvement, std, out=np.zeros_like(improvement), where=std > 1e-12)
    return improvement * norm.cdf(z) + std * norm.pdf(z)


def fit_local_models(
    table: pd.DataFrame,
    target: str,
    minimize: bool,
    top_candidates_per_series: int,
) -> list[LocalModelResult]:
    composition_index = build_composition_index(table)
    results: list[LocalModelResult] = []
    group_keys = ["matrix_key", "optimization_type_clean", "modifier_label", "site_key"]

    for keys, group in table.groupby(group_keys, dropna=False):
        matrix, optimization_type, modifier, site = (str(item) for item in keys)
        if not modifier or optimization_type == "pristine":
            continue

        observed = group.dropna(subset=["amount_num", target]).copy()
        if len(observed) < 2:
            continue

        obs_rows = observed[
            ["sample_id", "Samples", "amount_num", target, "T_ZT_max(K)"]
        ].copy()
        obs_rows["is_baseline"] = False

        baseline_rows = composition_index.get(normalize_composition(matrix), [])
        existing_ids = set(obs_rows["sample_id"])
        for baseline in baseline_rows:
            if baseline.get("sample_id") in existing_ids or is_empty(baseline.get(target)):
                continue
            obs_rows = pd.concat(
                [
                    obs_rows,
                    pd.DataFrame(
                        [
                            {
                                "sample_id": f"{baseline.get('sample_id')} baseline",
                                "Samples": baseline.get("Samples", "baseline"),
                                "amount_num": 0.0,
                                target: float(baseline.get(target)),
                                "T_ZT_max(K)": baseline.get("T_ZT_max(K)"),
                                "is_baseline": True,
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )

        obs_rows = (
            obs_rows.dropna(subset=["amount_num", target])
            .drop_duplicates(subset=["amount_num"], keep="first")
            .sort_values("amount_num")
            .reset_index(drop=True)
        )
        if len(obs_rows) < 2 or obs_rows["amount_num"].nunique() < 2:
            continue

        x = obs_rows[["amount_num"]].to_numpy(dtype=float)
        y = obs_rows[target].to_numpy(dtype=float)
        unique_x = np.unique(x[:, 0])
        diffs = np.diff(unique_x)
        step = float(np.median(diffs)) if len(diffs) else 0.01
        if step <= 0:
            continue

        lower = max(0.0, float(unique_x.min() - step))
        upper = float(unique_x.max() + step)
        if unique_x.max() <= 0.1:
            upper = min(upper, float(unique_x.max() + max(step, 0.02)))

        grid_x = np.linspace(lower, upper, 401).reshape(-1, 1)
        length_lower = max(step * 0.5, 0.002)
        length_upper = max(step * 10.0, length_lower * 2.0)
        kernel = ConstantKernel(1.0, (0.1, 10.0)) * Matern(
            length_scale=max(step * 1.5, length_lower),
            length_scale_bounds=(length_lower, length_upper),
            nu=2.5,
        )
        model = GaussianProcessRegressor(
            kernel=kernel,
            normalize_y=True,
            alpha=0.02**2,
            n_restarts_optimizer=5,
            random_state=42,
        )
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=ConvergenceWarning)
            model.fit(x, y)

        mean, std = model.predict(grid_x, return_std=True)
        incumbent = float(np.nanmin(y) if minimize else np.nanmax(y))
        ei = expected_improvement(mean, std, incumbent=incumbent, minimize=minimize)
        ucb = mean - std if minimize else mean + std

        grid = pd.DataFrame(
            {
                "amount": grid_x[:, 0],
                "posterior_mean": mean,
                "posterior_std": std,
                "expected_improvement": ei,
                "ucb": ucb,
            }
        )

        min_distance = max(step / 10.0, 0.001)
        measured_amounts = list(unique_x)
        unmeasured = grid[
            ~grid["amount"].apply(
                lambda value: any(abs(value - measured) < min_distance for measured in measured_amounts)
            )
        ].copy()
        unmeasured = unmeasured.sort_values(
            ["ucb", "posterior_mean", "expected_improvement"],
            ascending=[minimize, minimize, False],
        )
        candidate_rows: list[pd.Series] = []
        candidate_spacing = max(step / 4.0, min_distance)
        for _, candidate in unmeasured.iterrows():
            if any(
                abs(float(candidate["amount"]) - float(chosen["amount"]))
                < candidate_spacing
                for chosen in candidate_rows
            ):
                continue
            candidate_rows.append(candidate)
            if len(candidate_rows) >= top_candidates_per_series:
                break
        candidates = (
            pd.DataFrame(candidate_rows)
            if candidate_rows
            else unmeasured.head(top_candidates_per_series).copy()
        )
        candidates.insert(0, "series_id", "")

        series_id = " | ".join(
            item for item in [matrix, optimization_type, modifier, site] if item
        )
        candidates["series_id"] = series_id
        candidates["matrix"] = matrix
        candidates["optimization_type"] = optimization_type
        candidates["modifier"] = modifier
        candidates["site"] = site
        candidates["n_observations"] = len(obs_rows)
        candidates["current_best"] = incumbent
        candidates["evidence_ids"] = "; ".join(obs_rows["sample_id"].astype(str))

        results.append(
            LocalModelResult(
                series_id=series_id,
                matrix=matrix,
                optimization_type=optimization_type,
                modifier=modifier,
                site=site,
                observations=obs_rows,
                grid=grid,
                candidates=candidates,
                kernel=str(model.kernel_),
                current_best=incumbent,
            )
        )

    return results


def render_markdown(
    table: pd.DataFrame,
    candidates: pd.DataFrame,
    models: list[LocalModelResult],
    target: str,
    minimize: bool,
    source_label: str,
    plot_path: Path,
    csv_path: Path,
    json_path: Path,
) -> str:
    direction = "minimize" if minimize else "maximize"
    created = datetime.now().isoformat(timespec="seconds")
    top_observed = table.dropna(subset=[target]).sort_values(target, ascending=minimize)
    best_observed = top_observed.iloc[0] if not top_observed.empty else None

    lines = [
        f"# Bayesian Prediction Report: {target}",
        "",
        f"- Created at: {created}",
        f"- Objective: {direction} `{target}`",
        f"- Observations used: {len(table.dropna(subset=[target]))}",
        f"- Local GP series fitted: {len(models)}",
        f"- Evidence source: {source_label}",
        "- Internet references: not used",
        "",
        "## Current Best Observations",
        "",
        "| Rank | Sample | Series label | Modifier amount | Target | T_ZT_max(K) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for rank, (_, row) in enumerate(top_observed.head(8).iterrows(), start=1):
        amount = row.get("amount_num")
        amount_text = "" if is_empty(amount) else f"{float(amount):.4g}"
        lines.append(
            f"| {rank} | {row.get('sample_id', '')} | {row.get('Samples', '')} | "
            f"{amount_text} | {float(row[target]):.4g} | {clean(row.get('T_ZT_max(K)'))} |"
        )

    lines.extend(
        [
            "",
            "## Ranked Bayesian Candidates",
            "",
        ]
    )

    if candidates.empty:
        lines.append(
            "No comparable local numeric series had enough points for a GP surrogate."
        )
    else:
        lines.extend(
            [
                "| Rank | Matrix / series | Amount | Mean | Std | UCB | EI | Evidence |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        sorted_candidates = candidates.sort_values(
            ["ucb", "posterior_mean", "expected_improvement"],
            ascending=[minimize, minimize, False],
        )
        for rank, (_, row) in enumerate(sorted_candidates.head(12).iterrows(), start=1):
            lines.append(
                f"| {rank} | {markdown_cell(row['series_id'])} | {row['amount']:.4g} | "
                f"{row['posterior_mean']:.4g} | {row['posterior_std']:.4g} | "
                f"{row['ucb']:.4g} | {row['expected_improvement']:.4g} | "
                f"{markdown_cell(row['evidence_ids'])} |"
            )

    lines.extend(["", "## Interpretation", ""])

    if best_observed is not None:
        best_amount = best_observed.get("amount_num")
        amount_text = "" if is_empty(best_amount) else f" at amount {float(best_amount):.4g}"
        lines.append(
            f"- Best observed point is `{best_observed.get('sample_id', '')}`"
            f"{amount_text}, with `{target}` = {float(best_observed[target]):.4g}."
        )

    if not candidates.empty:
        sorted_by_mean = candidates.sort_values(
            "posterior_mean", ascending=minimize
        ).iloc[0]
        sorted_by_ucb = candidates.sort_values("ucb", ascending=minimize).iloc[0]
        lines.append(
            f"- Highest posterior-mean candidate is `{markdown_cell(sorted_by_mean['series_id'])}` "
            f"at amount {sorted_by_mean['amount']:.4g}: mean {sorted_by_mean['posterior_mean']:.4g}, "
            f"std {sorted_by_mean['posterior_std']:.4g}."
        )
        lines.append(
            f"- Highest UCB candidate is `{markdown_cell(sorted_by_ucb['series_id'])}` "
            f"at amount {sorted_by_ucb['amount']:.4g}: UCB {sorted_by_ucb['ucb']:.4g}. "
            "This is the more exploration-weighted choice."
        )

    lines.extend(
        [
            "- Candidate points near dense measured data are safer interpolation choices; points just outside the measured range are exploration choices and need stronger validation.",
            "- Series with only two or three measured points are included, but their uncertainty should be treated as planning guidance rather than a reliable optimum.",
            "- Suggested validation for any top candidate: repeat ZT curve, Hall carrier concentration/mobility, XRD phase check, density verification, and composition/EDS when available.",
            "",
            "## Output Files",
            "",
            f"- Candidate table: `{csv_path}`",
            f"- Machine-readable payload: `{json_path}`",
            f"- GP plot: `{plot_path}`",
        ]
    )

    return "\n".join(lines) + "\n"


def plot_models(models: list[LocalModelResult], target: str, output_paths: list[Path], limit: int) -> None:
    if not models:
        return

    ranked = sorted(
        models,
        key=lambda model: model.candidates["ucb"].max()
        if not model.candidates.empty
        else -np.inf,
        reverse=True,
    )[:limit]

    cols = 2
    rows = math.ceil(len(ranked) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(12, max(4, rows * 3.6)), squeeze=False)

    for axis, model in zip(axes.flat, ranked):
        grid = model.grid
        observations = model.observations
        x = grid["amount"].to_numpy()
        mean = grid["posterior_mean"].to_numpy()
        std = grid["posterior_std"].to_numpy()
        axis.plot(x, mean, color="#2457a6", linewidth=2, label="posterior mean")
        axis.fill_between(
            x,
            mean - std,
            mean + std,
            color="#2457a6",
            alpha=0.18,
            label="mean +/- 1 std",
        )
        axis.scatter(
            observations["amount_num"],
            observations[target],
            color="#b3261e",
            s=40,
            zorder=3,
            label="measured",
        )
        axis.set_title(model.series_id, fontsize=9)
        axis.set_xlabel("modifier amount")
        axis.set_ylabel(target)
        axis.grid(alpha=0.25)

    for axis in axes.flat[len(ranked) :]:
        axis.axis("off")

    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    for output_path in output_paths:
        fig.savefig(output_path, dpi=220)
    plt.close(fig)


def write_outputs(
    root: Path,
    output_dir: Path,
    figure_dir: Path,
    table: pd.DataFrame,
    models: list[LocalModelResult],
    target: str,
    minimize: bool,
    top: int,
    run_label: str,
    source_label: str,
    pdf: bool = False,
) -> dict[str, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    resolved_dir = root / output_dir
    resolved_dir.mkdir(parents=True, exist_ok=True)
    resolved_figure_dir = root / figure_dir
    resolved_figure_dir.mkdir(parents=True, exist_ok=True)

    all_candidates = (
        pd.concat([model.candidates for model in models], ignore_index=True)
        if models
        else pd.DataFrame()
    )
    if not all_candidates.empty:
        all_candidates = all_candidates.sort_values(
            ["ucb", "posterior_mean", "expected_improvement"],
            ascending=[minimize, minimize, False],
        ).reset_index(drop=True)

    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_label).strip("_") or "all"
    csv_path = resolved_dir / f"bayesian_candidates_{safe_label}_{target}_{timestamp}.csv"
    json_path = resolved_dir / f"bayesian_prediction_{safe_label}_{target}_{timestamp}.json"
    md_path = resolved_dir / f"bayesian_prediction_{safe_label}_{target}_{timestamp}.md"
    plot_path = resolved_figure_dir / f"bayesian_local_gp_{safe_label}_{target}_{timestamp}.png"
    plot_paths = [plot_path]
    if pdf:
        plot_paths.append(plot_path.with_suffix(".pdf"))

    all_candidates.to_csv(csv_path, index=False)
    plot_models(models, target, plot_paths, limit=min(top, 8))

    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "target": target,
        "objective": "minimize" if minimize else "maximize",
        "n_lab_observations": int(len(table.dropna(subset=[target]))),
        "n_local_gp_series": len(models),
        "top_observed": table.dropna(subset=[target])
        .sort_values(target, ascending=minimize)
        .head(12)
        .replace({np.nan: None})
        .to_dict(orient="records"),
        "candidates": all_candidates.head(30)
        .replace({np.nan: None})
        .to_dict(orient="records"),
        "model_series": [
            {
                "series_id": model.series_id,
                "kernel": model.kernel,
                "current_best": model.current_best,
                "observations": model.observations.replace({np.nan: None}).to_dict(
                    orient="records"
                ),
            }
            for model in models
        ],
        "limitations": [
            "Local one-dimensional Gaussian-process surrogates only.",
            "No internet references used.",
            "Missing Hall, phase-fraction, and repeated-measurement uncertainty values limit confidence.",
            "The recommendation is for experiment planning, not fully autonomous Bayesian optimization.",
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md_path.write_text(
        render_markdown(
            table=table,
            candidates=all_candidates,
            models=models,
            target=target,
            minimize=minimize,
            source_label=source_label,
            plot_path=plot_path,
            csv_path=csv_path,
            json_path=json_path,
        ),
        encoding="utf-8",
    )

    outputs = {"csv": csv_path, "json": json_path, "markdown": md_path, "plot": plot_path}
    if pdf:
        outputs["plot_pdf"] = plot_path.with_suffix(".pdf")
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fit local Bayesian GP predictions for processed TE materials data."
    )
    parser.add_argument(
        "--source",
        choices=["lab", "reference", "all"],
        default="lab",
        help="Data source to model, default: lab",
    )
    parser.add_argument(
        "--reference-id",
        default=None,
        help="Reference dataset id under data/reference/features, e.g. GeSe.",
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        help=f"Target metric to model, default: {DEFAULT_TARGET}",
    )
    parser.add_argument(
        "--minimize",
        action="store_true",
        help="Use minimization acquisition instead of maximization.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Table/report output directory, default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--figure-dir",
        default=str(DEFAULT_FIGURE_DIR),
        help=f"Figure output directory, default: {DEFAULT_FIGURE_DIR}",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=12,
        help="Number of ranked candidates to print.",
    )
    parser.add_argument(
        "--top-candidates-per-series",
        type=int,
        default=5,
        help="Number of unmeasured candidate amounts retained per local series.",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Also save vector PDF output for the GP plot.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    table = load_source_table(root, source=args.source, reference_id=args.reference_id)
    if table.empty:
        raise SystemExit("No processed feature rows were found for the requested source.")
    if args.target not in table.columns:
        available = ", ".join(sorted(str(col) for col in table.columns))
        raise SystemExit(f"Target {args.target!r} not found. Available columns: {available}")

    models = fit_local_models(
        table=table,
        target=args.target,
        minimize=args.minimize,
        top_candidates_per_series=args.top_candidates_per_series,
    )
    outputs = write_outputs(
        root=root,
        output_dir=Path(args.output_dir),
        figure_dir=Path(args.figure_dir),
        table=table,
        models=models,
        target=args.target,
        minimize=args.minimize,
        top=args.top,
        run_label=args.reference_id or args.source,
        source_label=(
            f"{args.source}"
            + (f" reference_id={args.reference_id}" if args.reference_id else "")
            + "; local files only"
        ),
        pdf=args.pdf,
    )

    candidates = (
        pd.concat([model.candidates for model in models], ignore_index=True)
        if models
        else pd.DataFrame()
    )
    if not candidates.empty:
        candidates = candidates.sort_values(
            ["ucb", "posterior_mean", "expected_improvement"],
            ascending=[args.minimize, args.minimize, False],
        )
        display_cols = [
            "series_id",
            "amount",
            "posterior_mean",
            "posterior_std",
            "ucb",
            "expected_improvement",
            "n_observations",
        ]
        print(candidates[display_cols].head(args.top).to_string(index=False))

    print("\nOutputs:")
    for label, path in outputs.items():
        print(f"- {label}: {path}")


if __name__ == "__main__":
    main()

"""
Assess selected thermoelectric batches from existing extracted features.

Usage:
    python assess_selected_batches.py CHY-1040 CHY-1048
    python assess_selected_batches.py --all

The script is intentionally local and deterministic:
1. It reads lab data from data/processed/*/extracted_features.json.
2. It optionally enriches metrics from each processed sample CSV.
3. It searches the local reference tables already in this workspace.
4. It writes JSON, Markdown, and an AI-ready prompt to results/assessments/.

It does not browse the Internet. When you want web-backed assessment, ask Codex
to use the generated JSON/prompt and browse current literature.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError:  # pragma: no cover - pandas is already in requirements.txt
    pd = None


WORKSPACE = Path(__file__).resolve().parent
DEFAULT_SELECTED_BATCHES = ["CHY-1040", "CHY-1048"]
FEATURE_ROOT = WORKSPACE / "data" / "processed"
REFERENCE_TABLES = [
    WORKSPACE / "data" / "extracted_te_review" / "article_level_extraction_20.csv",
    WORKSPACE / "data" / "extracted_te_review" / "property_records_long_20.csv",
    WORKSPACE
    / "data"
    / "extracted_te_review"
    / "actamat_2023_119259_pilot"
    / "sample_metadata.csv",
    WORKSPACE
    / "data"
    / "extracted_te_review"
    / "actamat_2023_119259_pilot"
    / "temperature_property_long.csv",
]
REFERENCE_TABLES.extend(
    sorted((WORKSPACE / "data" / "reference" / "features").glob("**/sample_features.csv"))
)
LAB_SAMPLES_PATH = WORKSPACE / "data" / "lab" / "samples.json"


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def safe_float(value: Any) -> float | None:
    if value in ("", None, [], {}):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def as_list(value: Any) -> list[Any]:
    if value in ("", None):
        return []
    if isinstance(value, list):
        return value
    return [value]


def fmt(value: Any, digits: int = 4) -> str:
    number = safe_float(value)
    if number is None:
        return ""
    return f"{number:.{digits}g}"


def normalize_label(value: Any) -> str:
    if value in ("", None):
        return ""
    return str(value).strip()


def discover_batches() -> list[str]:
    batches = []
    for path in sorted(FEATURE_ROOT.glob("*-processed/extracted_features.json")):
        batches.append(path.parent.name.removesuffix("-processed"))
    return batches


def batch_feature_path(batch_id: str) -> Path:
    return FEATURE_ROOT / f"{batch_id}-processed" / "extracted_features.json"


def processed_folder(batch_id: str) -> Path:
    return FEATURE_ROOT / f"{batch_id}-processed"


def find_processed_csv(batch_id: str, sample: dict[str, Any]) -> Path | None:
    folder = processed_folder(batch_id)
    if not folder.exists():
        return None

    labels = [
        normalize_label(sample.get("sample_id")),
        normalize_label(sample.get("Samples")),
        normalize_label(sample.get("sample_name")),
    ]
    labels = [label for label in labels if label]
    for label in labels:
        candidate = folder / f"{label}.csv"
        if candidate.exists():
            return candidate

    normalized = {label.lower().replace(" ", "_") for label in labels}
    for path in folder.glob("*.csv"):
        if path.stem.lower().replace(" ", "_") in normalized:
            return path
    return None


def value_is_present(value: Any) -> bool:
    return value not in ("", None, [], {})


def load_lab_sample_index() -> dict[tuple[str, str], dict[str, Any]]:
    records = load_json(LAB_SAMPLES_PATH, default=[]) or []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        batch_id = normalize_label(record.get("batch_id"))
        if not batch_id:
            continue
        labels = [
            record.get("sample_id"),
            record.get("sample_name"),
            record.get("legacy_sample_name"),
        ]
        for label in labels:
            label = normalize_label(label)
            if label:
                index[(batch_id, label)] = record
    return index


def merge_lab_metadata(
    batch_id: str,
    feature_sample: dict[str, Any],
    lab_sample_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    labels = [
        feature_sample.get("sample_id"),
        feature_sample.get("Samples"),
        feature_sample.get("sample_name"),
    ]
    lab_record = None
    for label in labels:
        label = normalize_label(label)
        if label and (batch_id, label) in lab_sample_index:
            lab_record = lab_sample_index[(batch_id, label)]
            break

    if not lab_record:
        return feature_sample

    merged = dict(lab_record)
    for key, value in feature_sample.items():
        if value_is_present(value) or key not in merged:
            merged[key] = value
    return merged


def numeric_series(frame: Any, column: str) -> Any | None:
    if pd is None or column not in frame.columns:
        return None
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    if series.empty:
        return None
    return series


def read_processed_metrics(csv_path: Path | None) -> dict[str, Any]:
    if csv_path is None or pd is None:
        return {}

    try:
        frame = pd.read_csv(csv_path)
    except Exception:
        return {}

    metrics: dict[str, Any] = {
        "processed_csv": str(csv_path.relative_to(WORKSPACE)),
        "n_temperature_points": int(len(frame)),
    }

    temp = numeric_series(frame, "Temperature")
    zt = numeric_series(frame, "ZT")
    seebeck = numeric_series(frame, "Seebeck")
    conductivity = numeric_series(frame, "Conductivity")
    thermal = numeric_series(frame, "Thermal_Conductivity")
    lattice = numeric_series(frame, "Lattice_Thermal_Conductivity")
    carrier = numeric_series(frame, "Carrier_Thermal_Conductivity")
    power_factor = numeric_series(frame, "Power_Factor")

    if temp is not None:
        metrics["temperature_min_K"] = float(temp.min())
        metrics["temperature_max_K"] = float(temp.max())

    if zt is not None:
        idx = zt.idxmax()
        metrics["ZT_max_from_csv"] = float(zt.loc[idx])
        metrics["ZT_avg"] = float(zt.mean())
        if temp is not None and idx in temp.index:
            metrics["T_ZT_max_K_from_csv"] = float(temp.loc[idx])
        if conductivity is not None and idx in conductivity.index:
            metrics["conductivity_at_ZT_max"] = float(conductivity.loc[idx])
        if thermal is not None and idx in thermal.index:
            metrics["K_at_ZT_max"] = float(thermal.loc[idx])
        if lattice is not None and idx in lattice.index:
            metrics["KL_at_ZT_max"] = float(lattice.loc[idx])

    if seebeck is not None:
        metrics["S_abs_max_from_csv"] = float(seebeck.abs().max())
    if conductivity is not None:
        metrics["conductivity_max_from_csv"] = float(conductivity.max())
    if thermal is not None:
        metrics["K_min_from_csv"] = float(thermal.min())
    if lattice is not None:
        metrics["KL_min_from_csv"] = float(lattice.min())
    if carrier is not None:
        metrics["Ke_max_from_csv"] = float(carrier.max())

    if power_factor is not None:
        metrics["PF_max"] = float(power_factor.max())
    elif seebeck is not None and conductivity is not None:
        aligned = frame[["Seebeck", "Conductivity"]].apply(
            pd.to_numeric, errors="coerce"
        )
        proxy = (aligned["Seebeck"] ** 2) * aligned["Conductivity"]
        proxy = proxy.dropna()
        if not proxy.empty:
            metrics["PF_proxy_max"] = float(proxy.max())
            metrics["PF_proxy_note"] = "Calculated as S^2*sigma from CSV rows."

    return metrics


def sample_identifier(batch_id: str, sample: dict[str, Any]) -> str:
    label = (
        normalize_label(sample.get("sample_id"))
        or normalize_label(sample.get("Samples"))
        or normalize_label(sample.get("sample_name"))
        or "unknown"
    )
    if label.startswith(batch_id):
        return f"lab:{label}"
    return f"lab:{batch_id}:{label}"


def observation_from_sample(
    batch_id: str,
    sample: dict[str, Any],
    lab_sample_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    sample = merge_lab_metadata(batch_id, sample, lab_sample_index)
    csv_path = find_processed_csv(batch_id, sample)
    csv_metrics = read_processed_metrics(csv_path)

    s_max = safe_float(sample.get("S_max(V/K)"))
    metrics = {
        "ZT_max": safe_float(sample.get("ZT_max")),
        "T_ZT_max_K": safe_float(sample.get("T_ZT_max(K)")),
        "S_abs_max": abs(s_max) if s_max is not None else None,
        "conductivity_max": safe_float(sample.get("C_max(S/m)")),
        "K_min": safe_float(sample.get("K_min(W/(m*K))")),
        "KL_min": safe_float(sample.get("KL_min(W/(m*K))")),
        "Ke_max": safe_float(sample.get("Ke_max(W/(m*K))")),
    }
    metrics.update(csv_metrics)

    if metrics.get("ZT_max") is None:
        metrics["ZT_max"] = metrics.get("ZT_max_from_csv")
    if metrics.get("T_ZT_max_K") is None:
        metrics["T_ZT_max_K"] = metrics.get("T_ZT_max_K_from_csv")
    if metrics.get("K_min") is None:
        metrics["K_min"] = metrics.get("K_min_from_csv")
    if metrics.get("KL_min") is None:
        metrics["KL_min"] = metrics.get("KL_min_from_csv")

    sample_label = (
        normalize_label(sample.get("Samples"))
        or normalize_label(sample.get("sample_name"))
        or normalize_label(sample.get("sample_id"))
    )

    modifier_elements = as_list(sample.get("modifier_elements"))
    if not modifier_elements:
        modifier_elements = as_list(sample.get("modifier_element"))
    if not modifier_elements:
        modifier_elements = as_list(sample.get("modifier_species"))

    required_metadata = [
        "matrix_composition",
        "sample_composition",
        "optimization_type",
        "modifier_amount",
    ]
    missing_metadata = [
        key for key in required_metadata if sample.get(key) in ("", None, [], {})
    ]
    if csv_path is None:
        missing_metadata.append("processed_csv")

    quality_score = max(0.0, 1.0 - len(missing_metadata) / 6.0)

    return {
        "observation_id": sample_identifier(batch_id, sample),
        "source_type": "lab",
        "batch_id": batch_id,
        "sample_label": sample_label,
        "material": {
            "matrix_composition": sample.get("matrix_composition", ""),
            "pristine_composition": sample.get("pristine_composition", ""),
            "sample_composition": sample.get("sample_composition", ""),
            "phase_type": sample.get("phase_type", ""),
        },
        "intervention": {
            "optimization_type": sample.get("optimization_type", ""),
            "modifier_species": sample.get("modifier_species", ""),
            "modifier_element": sample.get("modifier_element", ""),
            "modifier_elements": modifier_elements,
            "modifier_amount": safe_float(sample.get("modifier_amount")),
            "modifier_unit": sample.get("modifier_unit", ""),
            "modifier_site": sample.get("modifier_site", ""),
        },
        "metrics": metrics,
        "quality": {
            "score": round(quality_score, 3),
            "missing_or_uncertain_fields": missing_metadata,
            "notes": sample.get("notes", ""),
        },
        "raw_feature_record": sample,
    }


def load_observations(batch_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    observations = []
    warnings = []
    lab_sample_index = load_lab_sample_index()
    for batch_id in batch_ids:
        path = batch_feature_path(batch_id)
        payload = load_json(path)
        if not payload:
            warnings.append(f"Missing extracted features for {batch_id}: {path}")
            continue
        for sample in payload.get("samples_data", []):
            observations.append(observation_from_sample(batch_id, sample, lab_sample_index))
    return observations, warnings


def add_rankings(observations: list[dict[str, Any]]) -> None:
    by_batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        by_batch[obs["batch_id"]].append(obs)

    for batch_obs in by_batch.values():
        ranked = sorted(
            batch_obs,
            key=lambda item: safe_float(item["metrics"].get("ZT_max")) or -math.inf,
            reverse=True,
        )
        best = safe_float(ranked[0]["metrics"].get("ZT_max")) if ranked else None
        for rank, obs in enumerate(ranked, start=1):
            zt = safe_float(obs["metrics"].get("ZT_max"))
            obs["rankings"] = {
                "rank_in_batch_by_ZT_max": rank,
                "delta_from_batch_best_ZT": None
                if zt is None or best is None
                else zt - best,
            }

    ranked_all = sorted(
        observations,
        key=lambda item: safe_float(item["metrics"].get("ZT_max")) or -math.inf,
        reverse=True,
    )
    for rank, obs in enumerate(ranked_all, start=1):
        obs.setdefault("rankings", {})["rank_in_selected_set_by_ZT_max"] = rank


def trend_key(obs: dict[str, Any]) -> tuple[Any, ...]:
    intervention = obs["intervention"]
    material = obs["material"]
    elements = tuple(sorted(str(x) for x in intervention.get("modifier_elements", [])))
    return (
        material.get("matrix_composition", ""),
        intervention.get("optimization_type", ""),
        elements,
    )


def monotonic_direction(values: list[float]) -> str:
    if len(values) < 2:
        return "insufficient"
    eps = 1e-12
    increasing = all(b >= a - eps for a, b in zip(values, values[1:]))
    decreasing = all(b <= a + eps for a, b in zip(values, values[1:]))
    if increasing and not decreasing:
        return "increasing"
    if decreasing and not increasing:
        return "decreasing"
    if increasing and decreasing:
        return "flat"
    return "mixed"


def compute_trends(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        amount = obs["intervention"].get("modifier_amount")
        zt = safe_float(obs["metrics"].get("ZT_max"))
        if amount is None or zt is None:
            continue
        grouped[trend_key(obs)].append(obs)

    trends = []
    for key, group in grouped.items():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda item: item["intervention"]["modifier_amount"])
        amounts = [item["intervention"]["modifier_amount"] for item in group]
        zts = [safe_float(item["metrics"].get("ZT_max")) for item in group]
        best = max(group, key=lambda item: safe_float(item["metrics"].get("ZT_max")) or -math.inf)
        direction = monotonic_direction([float(x) for x in zts if x is not None])
        modifier_slug = "-".join(str(part) for part in key[2]) or "none"

        trends.append(
            {
                "trend_id": ":".join(
                    [
                        "trend",
                        slugify(key[0]),
                        slugify(key[1]),
                        slugify(modifier_slug),
                    ]
                ),
                "matrix_composition": key[0],
                "optimization_type": key[1],
                "modifier_elements": list(key[2]),
                "amounts": amounts,
                "ZT_max_values": zts,
                "direction_by_ZT_max": direction,
                "best_observation_id": best["observation_id"],
                "best_amount": best["intervention"]["modifier_amount"],
                "best_ZT_max": safe_float(best["metrics"].get("ZT_max")),
                "evidence_ids": [item["observation_id"] for item in group],
            }
        )
    return trends


def slugify(value: Any) -> str:
    text = str(value or "unknown")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("_") or "unknown"


def suggestion_from_trend(trend: dict[str, Any]) -> dict[str, Any]:
    amounts = [safe_float(x) for x in trend["amounts"] if safe_float(x) is not None]
    best_amount = safe_float(trend["best_amount"])
    if not amounts or best_amount is None:
        target = "Collect more points before proposing a local composition search."
    else:
        sorted_amounts = sorted(amounts)
        step = min(
            [
                abs(b - a)
                for a, b in zip(sorted_amounts, sorted_amounts[1:])
                if abs(b - a) > 0
            ]
            or [max(abs(best_amount) * 0.5, 0.01)]
        )
        direction = trend["direction_by_ZT_max"]
        if direction == "decreasing":
            low = max(0.0, best_amount - step / 2)
            target = f"Refine below or near {fmt(best_amount)}: test {fmt(low)} to {fmt(best_amount)}."
        elif direction == "increasing":
            high = best_amount + step / 2
            target = f"Refine above or near {fmt(best_amount)}: test {fmt(best_amount)} to {fmt(high)}."
        elif direction == "mixed":
            low = max(0.0, best_amount - step / 2)
            high = best_amount + step / 2
            target = f"Local search around the apparent optimum: test {fmt(low)} to {fmt(high)}."
        else:
            target = f"Add replicate or midpoint samples around {fmt(best_amount)}."

    confidence = 0.45 + min(0.3, 0.05 * len(trend["evidence_ids"]))
    if trend["direction_by_ZT_max"] in {"increasing", "decreasing"}:
        confidence += 0.1

    return {
        "suggestion_id": "suggestion:" + trend["trend_id"].removeprefix("trend:"),
        "type": "local_composition_refinement",
        "proposal": target,
        "reasonable_reason": (
            f"Within this local series, ZT_max is {trend['direction_by_ZT_max']} "
            f"over amounts {trend['amounts']}; best current amount is "
            f"{fmt(trend['best_amount'])} with ZT_max {fmt(trend['best_ZT_max'])}."
        ),
        "evidence_source": "lab_data",
        "evidence_ids": trend["evidence_ids"],
        "confidence": round(min(confidence, 0.85), 2),
        "next_measurements": ["Hall carrier concentration", "phase purity/XRD", "repeat ZT curve"],
    }


def make_cross_intervention_suggestions(
    observations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    suggestions = []
    by_matrix: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        matrix = obs["material"].get("matrix_composition") or "unknown_matrix"
        by_matrix[matrix].append(obs)

    for matrix, group in by_matrix.items():
        valid = [obs for obs in group if safe_float(obs["metrics"].get("ZT_max")) is not None]
        if len(valid) < 3:
            continue
        best_zt = max(valid, key=lambda item: safe_float(item["metrics"].get("ZT_max")) or -math.inf)
        low_k_pool = [
            obs for obs in valid if safe_float(obs["metrics"].get("KL_min") or obs["metrics"].get("K_min")) is not None
        ]
        if not low_k_pool:
            continue
        low_k = min(
            low_k_pool,
            key=lambda item: safe_float(item["metrics"].get("KL_min") or item["metrics"].get("K_min")) or math.inf,
        )
        if best_zt["observation_id"] == low_k["observation_id"]:
            continue
        if best_zt["intervention"].get("optimization_type") == low_k["intervention"].get(
            "optimization_type"
        ):
            continue

        suggestions.append(
            {
                "suggestion_id": f"suggestion:combine:{matrix}",
                "type": "combination_screen",
                "proposal": (
                    "Consider a small factorial screen combining the best-ZT "
                    "intervention with the lowest-thermal-conductivity intervention."
                ),
                "reasonable_reason": (
                    f"For matrix {matrix}, {best_zt['sample_label']} has the best "
                    f"ZT_max ({fmt(best_zt['metrics'].get('ZT_max'))}), while "
                    f"{low_k['sample_label']} has lower K/KL "
                    f"({fmt(low_k['metrics'].get('KL_min') or low_k['metrics'].get('K_min'))}). "
                    "A limited combination screen can test whether electrical transport "
                    "and phonon scattering benefits can coexist."
                ),
                "evidence_source": "lab_data",
                "evidence_ids": [best_zt["observation_id"], low_k["observation_id"]],
                "confidence": 0.48,
                "next_measurements": [
                    "Hall carrier concentration",
                    "SEM/EDS for second phase",
                    "full temperature-dependent transport",
                ],
            }
        )
    return suggestions


def make_suggestions(
    observations: list[dict[str, Any]], trends: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    suggestions = [suggestion_from_trend(trend) for trend in trends]
    suggestions.extend(make_cross_intervention_suggestions(observations))
    return suggestions


def read_csv_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [{**row, "_source_file": str(path.relative_to(WORKSPACE))} for row in reader]


def reference_query_tokens(obs: dict[str, Any]) -> list[str]:
    pieces = [
        obs["material"].get("matrix_composition", ""),
        obs["material"].get("sample_composition", ""),
        obs["intervention"].get("optimization_type", ""),
        obs["intervention"].get("modifier_species", ""),
        obs["intervention"].get("modifier_element", ""),
    ]
    pieces.extend(str(x) for x in obs["intervention"].get("modifier_elements", []))
    text = " ".join(str(piece) for piece in pieces if piece)
    tokens = set(re.findall(r"[A-Z][a-z]?", text))
    tokens.update(
        word.lower()
        for word in re.findall(r"[A-Za-z]{4,}", text)
        if word.lower() not in {"with", "site", "unknown"}
    )
    return sorted(tokens)


def score_reference_record(record: dict[str, Any], tokens: list[str]) -> int:
    haystack = " ".join(str(value) for value in record.values()).lower()
    score = 0
    for token in tokens:
        token_lower = token.lower()
        if len(token_lower) <= 1:
            continue
        if token_lower in haystack:
            score += 1
    if "zt" in haystack:
        score += 1
    if "chalcopyrite" in haystack:
        score += 2
    return score


def find_local_reference_hits(
    observations: list[dict[str, Any]], max_hits: int = 8
) -> list[dict[str, Any]]:
    reference_records = []
    for path in REFERENCE_TABLES:
        reference_records.extend(read_csv_records(path))

    tokens = sorted(
        set(token for obs in observations for token in reference_query_tokens(obs))
    )
    scored = []
    for record in reference_records:
        score = score_reference_record(record, tokens)
        if score <= 0:
            continue
        scored.append((score, record))

    hits = []
    seen = set()
    for score, record in sorted(scored, key=lambda item: item[0], reverse=True):
        doi = record.get("doi", "")
        title = record.get("title", "")
        composition = record.get("composition") or record.get("sample_id") or ""
        key = (doi, title, composition, record.get("_source_file"))
        if key in seen:
            continue
        seen.add(key)
        hits.append(
            {
                "evidence_id": f"own_reference:{len(hits) + 1}",
                "source_type": "own_reference_database",
                "source_file": record.get("_source_file", ""),
                "doi": doi,
                "title": title,
                "composition_or_sample": composition,
                "matched_score": score,
                "brief": (
                    record.get("key_results")
                    or record.get("qualifier")
                    or record.get("note")
                    or record.get("property")
                    or ""
                ),
            }
        )
        if len(hits) >= max_hits:
            break
    return hits


def build_assessment(batch_ids: list[str]) -> dict[str, Any]:
    observations, warnings = load_observations(batch_ids)
    add_rankings(observations)
    trends = compute_trends(observations)
    suggestions = make_suggestions(observations, trends)
    local_reference_hits = find_local_reference_hits(observations)

    top_samples = sorted(
        observations,
        key=lambda obs: safe_float(obs["metrics"].get("ZT_max")) or -math.inf,
        reverse=True,
    )[:10]

    return {
        "assessment_metadata": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "selected_batches": batch_ids,
            "internet_reference_status": "not_used_by_local_script",
            "own_reference_database_status": "searched"
            if local_reference_hits
            else "searched_no_hits",
            "method": "deterministic_local_assessment",
        },
        "warnings": warnings,
        "observations": observations,
        "top_samples_by_ZT_max": [
            {
                "observation_id": obs["observation_id"],
                "batch_id": obs["batch_id"],
                "sample_label": obs["sample_label"],
                "ZT_max": obs["metrics"].get("ZT_max"),
                "T_ZT_max_K": obs["metrics"].get("T_ZT_max_K"),
                "K_min": obs["metrics"].get("K_min"),
                "KL_min": obs["metrics"].get("KL_min"),
                "optimization_type": obs["intervention"].get("optimization_type"),
                "modifier_elements": obs["intervention"].get("modifier_elements"),
                "modifier_amount": obs["intervention"].get("modifier_amount"),
            }
            for obs in top_samples
        ],
        "trends": trends,
        "optimization_suggestions": suggestions,
        "reference_evidence": {
            "own_reference_database": local_reference_hits,
            "internet": [],
        },
        "self_assessment": {
            "computer_assessment_confidence": confidence_from_data(observations, trends),
            "limitations": [
                "This script does not browse the Internet.",
                "Trend suggestions are heuristic unless enough points exist for a real BO model.",
                "Some old extracted_features.json files may lack metadata; rerun main.py after metadata updates.",
                "Hall/SPB conclusions are limited when carrier concentration and mobility are missing.",
            ],
            "bo_readiness": bo_readiness(observations, trends),
        },
    }


def confidence_from_data(
    observations: list[dict[str, Any]], trends: list[dict[str, Any]]
) -> float:
    if not observations:
        return 0.0
    completeness = sum(obs["quality"]["score"] for obs in observations) / len(observations)
    trend_bonus = min(0.2, len(trends) * 0.04)
    count_bonus = min(0.2, len(observations) * 0.015)
    return round(min(0.9, 0.25 + completeness * 0.35 + trend_bonus + count_bonus), 2)


def bo_readiness(
    observations: list[dict[str, Any]], trends: list[dict[str, Any]]
) -> dict[str, Any]:
    numeric_points = [
        obs
        for obs in observations
        if obs["intervention"].get("modifier_amount") is not None
        and safe_float(obs["metrics"].get("ZT_max")) is not None
    ]
    ready_groups = [
        trend for trend in trends if len(trend.get("evidence_ids", [])) >= 5
    ]
    return {
        "numeric_observations": len(numeric_points),
        "series_with_at_least_5_points": len(ready_groups),
        "status": "ready_for_basic_gp_bo"
        if ready_groups
        else "collect_more_points_for_reliable_bo",
        "recommendation": (
            "For reliable Bayesian optimization, target at least 5 points per "
            "single-variable series or 10-20 points for mixed composition/process spaces."
        ),
    }


def markdown_table(rows: list[list[Any]], headers: list[str]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_markdown(assessment: dict[str, Any]) -> str:
    meta = assessment["assessment_metadata"]
    lines = [
        f"# Selected Batch Assessment: {', '.join(meta['selected_batches'])}",
        "",
        f"- Created at: {meta['created_at']}",
        "- Lab data source: data/processed/*/extracted_features.json and processed CSV files",
        f"- Own reference database: {meta['own_reference_database_status']}",
        "- Internet references: not used by this local script",
        "",
    ]

    if assessment["warnings"]:
        lines.append("## Warnings")
        lines.extend(f"- {warning}" for warning in assessment["warnings"])
        lines.append("")

    lines.append("## Top Samples by ZT_max")
    top_rows = []
    for item in assessment["top_samples_by_ZT_max"]:
        top_rows.append(
            [
                item["batch_id"],
                item["sample_label"],
                fmt(item["ZT_max"]),
                fmt(item["T_ZT_max_K"]),
                fmt(item["K_min"]),
                fmt(item["KL_min"]),
                item.get("optimization_type") or "",
                ",".join(str(x) for x in item.get("modifier_elements") or []),
                fmt(item.get("modifier_amount")),
            ]
        )
    lines.append(
        markdown_table(
            top_rows,
            [
                "Batch",
                "Sample",
                "ZT_max",
                "T_ZTmax K",
                "K_min",
                "KL_min",
                "Type",
                "Modifier",
                "Amount",
            ],
        )
    )
    lines.append("")

    lines.append("## Trends")
    if assessment["trends"]:
        for trend in assessment["trends"]:
            lines.append(
                f"- {trend['optimization_type']} / {','.join(trend['modifier_elements'])}: "
                f"ZT trend is {trend['direction_by_ZT_max']} over amounts "
                f"{trend['amounts']}; best amount {fmt(trend['best_amount'])} "
                f"with ZT_max {fmt(trend['best_ZT_max'])}. "
                f"Evidence: {', '.join(trend['evidence_ids'])}"
            )
    else:
        lines.append("- No multi-point composition trends were available.")
    lines.append("")

    lines.append("## Optimization Suggestions")
    if assessment["optimization_suggestions"]:
        for suggestion in assessment["optimization_suggestions"]:
            lines.append(f"### {suggestion['suggestion_id']}")
            lines.append(f"- Proposal: {suggestion['proposal']}")
            lines.append(f"- Reason: {suggestion['reasonable_reason']}")
            lines.append(f"- Evidence source: {suggestion['evidence_source']}")
            lines.append(f"- Evidence IDs: {', '.join(suggestion['evidence_ids'])}")
            lines.append(f"- Confidence: {suggestion['confidence']}")
            lines.append(
                "- Next measurements: "
                + ", ".join(suggestion.get("next_measurements", []))
            )
            lines.append("")
    else:
        lines.append("- Not enough comparable observations for suggestions.")
        lines.append("")

    lines.append("## Reference Evidence")
    local_hits = assessment["reference_evidence"]["own_reference_database"]
    if local_hits:
        lines.append("Own reference database hits:")
        for hit in local_hits:
            label = hit.get("title") or hit.get("composition_or_sample") or hit.get("doi")
            lines.append(
                f"- {hit['evidence_id']} ({hit['source_file']}): {label}; "
                f"DOI: {hit.get('doi', '')}; note: {hit.get('brief', '')}"
            )
    else:
        lines.append("- No local reference hits found.")
    lines.append("- Internet reference hits: none; this script does not browse.")
    lines.append("")

    lines.append("## Self Assessment")
    self_assessment = assessment["self_assessment"]
    lines.append(
        f"- Computer assessment confidence: "
        f"{self_assessment['computer_assessment_confidence']}"
    )
    lines.append(
        f"- BO readiness: {self_assessment['bo_readiness']['status']} "
        f"({self_assessment['bo_readiness']['numeric_observations']} numeric observations)"
    )
    for limitation in self_assessment["limitations"]:
        lines.append(f"- Limitation: {limitation}")
    lines.append("")

    return "\n".join(lines)


def build_ai_prompt(assessment: dict[str, Any]) -> str:
    compact_payload = {
        "assessment_metadata": assessment["assessment_metadata"],
        "top_samples_by_ZT_max": assessment["top_samples_by_ZT_max"],
        "trends": assessment["trends"],
        "optimization_suggestions": assessment["optimization_suggestions"],
        "reference_evidence": assessment["reference_evidence"],
        "self_assessment": assessment["self_assessment"],
    }
    return (
        "You are an evidence-grounded thermoelectric materials assessment agent.\n\n"
        "Required user instruction: Give reasonable reasons for optimization "
        "suggestions; if you look into references on the Internet or in the "
        "user's own reference database, explicitly point that out.\n\n"
        "Separate conclusions into: (1) lab-data-supported conclusions, "
        "(2) own-reference-database-supported conclusions, "
        "(3) Internet-reference-supported conclusions, and "
        "(4) hypotheses/speculation.\n\n"
        "Do not invent references. If Internet evidence is absent, say that "
        "Internet references were not used. For each optimization suggestion, "
        "include evidence IDs, confidence, risk, and the next measurement that "
        "would validate or reject it.\n\n"
        "Assessment payload:\n"
        "```json\n"
        f"{json.dumps(compact_payload, indent=2, ensure_ascii=False)}\n"
        "```\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assess selected thermoelectric batches."
    )
    parser.add_argument(
        "batches",
        nargs="*",
        help="Batch IDs to assess, e.g. CHY-1040 CHY-1048.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Assess every batch with an extracted_features.json file.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(WORKSPACE / "results" / "assessments"),
        help="Directory for JSON, Markdown, and AI prompt outputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.all:
        batch_ids = discover_batches()
    elif args.batches:
        batch_ids = args.batches
    else:
        batch_ids = DEFAULT_SELECTED_BATCHES

    assessment = build_assessment(batch_ids)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = "assessment_" + "_".join(batch_ids) + f"_{timestamp}"
    output_dir = Path(args.output_dir)
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    prompt_path = output_dir / f"{stem}.prompt.md"

    write_json(json_path, assessment)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(assessment), encoding="utf-8")
    prompt_path.write_text(build_ai_prompt(assessment), encoding="utf-8")

    print(f"Assessment JSON: {json_path}")
    print(f"Markdown report: {markdown_path}")
    print(f"AI prompt: {prompt_path}")
    print(
        "BO readiness:",
        assessment["self_assessment"]["bo_readiness"]["status"],
    )


if __name__ == "__main__":
    main()

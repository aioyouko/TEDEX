"""Centralized workspace configuration and path resolution for TEDEX (Mode B ready).

Separates two distinct roots so the software/plugin layer and user data directory
never collide:
- ``ENGINE_ROOT``: Installed Python package / plugin repository root owning ``te_analysis/``,
  ``scripts/``, built-in ``data/demo/``, and template schemas.
- ``WORKSPACE_ROOT``: Active user project directory owning ``configs/workspace.json``,
  ``data/``, and ``outputs/`` (with zero Python or skill files required in the user directory).
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "tedex-workspace/v1"
ENGINE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_CONFIG_CANDIDATES = (
    Path("configs") / "workspace.json",
    Path(".tedex.json"),
    Path("workspace.json"),
)
GROUPING_MODES = ("by_batch", "by_system_batch", "by_project")

DEFAULT_WORKSPACE_DICT: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "project": {
        "name": "Thermoelectric Project",
        "grouping_mode": "by_batch",
        "batch_prefix": "",
        "raw_dir_pattern": "{batch_id}",
        "processed_dir_pattern": "{batch_id}",
        "figure_dir_pattern": "{domain}/{batch_id}",
        "default_batches": [],
    },
    "paths": {
        "raw": "data/raw",
        "processed": "data/processed",
        "metadata": "data/metadata",
        "references": "data/references/literature",
        "xrd_cards": "data/references/xrd_cards",
        "figures": "outputs/figures",
        "models": "outputs/models",
        "reports": "outputs/reports",
        "cache": "outputs/cache",
        "recipes": "configs/plot_recipes",
        "schemas": "configs/schemas",
    },
    "data_types": {
        "electrical_transport": {
            "instrument": "ZEM-3",
            "formats": [".txt", ".csv"],
            "conductivity_unit": "S/cm",
            "seebeck_unit": "uV/K",
            "temperature_unit": "K",
        },
        "thermal_transport": {
            "instrument": "LFA",
            "formats": [".csv", ".xlsx"],
            "diffusivity_unit": "mm^2/s",
        },
        "xrd": {
            "formats": [".xy", ".csv", ".txt"],
            "wavelength_angstrom": 1.5406,
            "radiation": "Cu-Ka",
        },
        "hall_and_cp": {
            "hall_nh_unit": "cm^-3",
            "cp_unit": "J/molK",
        },
    },
    "plotting": {
        "formats": ["svg"],
        "color_set": "npg",
        "copy_beside_data": True,
        "data_figures_subdir": "figures",
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def default_patterns_for_grouping(grouping_mode: str) -> dict[str, str]:
    mode = str(grouping_mode or "by_batch").strip().lower()
    if mode == "by_system_batch":
        return {
            "raw_dir_pattern": "{system}/{batch_id}",
            "processed_dir_pattern": "{system}/{batch_id}",
            "figure_dir_pattern": "{domain}/{system}/{batch_id}",
        }
    if mode == "by_project":
        return {
            "raw_dir_pattern": "{batch_id}",
            "processed_dir_pattern": "{batch_id}",
            "figure_dir_pattern": "{batch_id}",
        }
    return {
        "raw_dir_pattern": "{batch_id}",
        "processed_dir_pattern": "{batch_id}",
        "figure_dir_pattern": "{domain}/{batch_id}",
    }


def build_workspace_config_dict(
    *,
    project_name: str = "Thermoelectric Project",
    grouping_mode: str = "by_batch",
    batch_prefix: str = "",
    processed_dir_pattern: str | None = None,
    default_batches: list[str] | None = None,
    path_overrides: dict[str, str] | None = None,
    data_type_overrides: dict[str, Any] | None = None,
    plotting_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a complete ``workspace.json`` payload from user onboarding choices."""
    if grouping_mode not in GROUPING_MODES:
        raise ValueError(
            f"Unknown grouping_mode {grouping_mode!r}. Choose from {', '.join(GROUPING_MODES)}."
        )
    cfg = copy.deepcopy(DEFAULT_WORKSPACE_DICT)
    patterns = default_patterns_for_grouping(grouping_mode)
    if processed_dir_pattern:
        patterns["processed_dir_pattern"] = processed_dir_pattern

    cfg["project"].update(
        {
            "name": project_name.strip() or "Thermoelectric Project",
            "grouping_mode": grouping_mode,
            "batch_prefix": str(batch_prefix or "").strip().rstrip("-"),
            **patterns,
            "default_batches": list(default_batches or []),
        }
    )
    if path_overrides:
        for key, val in path_overrides.items():
            if val is not None and str(val).strip():
                cfg["paths"][key] = str(val).strip().replace("\\", "/")
    if data_type_overrides:
        cfg["data_types"] = _deep_merge(cfg["data_types"], data_type_overrides)
    if plotting_overrides:
        cfg["plotting"] = _deep_merge(cfg["plotting"], plotting_overrides)
    return cfg


def find_workspace_config(start_dir: Path | str | None = None) -> tuple[Path | None, Path]:
    """Locate ``configs/workspace.json`` (or ``.tedex.json``) and return ``(config_path, workspace_root)``."""
    env_cfg = os.environ.get("TE_WORKSPACE_CONFIG", "").strip()
    if env_cfg:
        cfg_path = Path(env_cfg).expanduser().resolve()
        if cfg_path.is_file():
            root = cfg_path.parent.parent if cfg_path.parent.name == "configs" else cfg_path.parent
            return cfg_path, root

    env_root = os.environ.get("TE_WORKSPACE_ROOT", "").strip()
    if env_root:
        base = Path(env_root).expanduser().resolve()
        for rel in WORKSPACE_CONFIG_CANDIDATES:
            candidate = base / rel
            if candidate.is_file():
                return candidate, base
        return None, base

    current = Path(start_dir).expanduser().resolve() if start_dir is not None else Path.cwd().resolve()
    if current.is_file():
        current = current.parent

    for directory in (current, *current.parents):
        for rel in WORKSPACE_CONFIG_CANDIDATES:
            candidate = directory / rel
            if candidate.is_file():
                return candidate, directory
    return None, current


@dataclass
class WorkspacePaths:
    """Resolved paths and conventions for an active user workspace."""

    root: Path
    config_path: Path | None
    raw_config: dict[str, Any] = field(default_factory=dict)
    is_initialized: bool = False

    @property
    def engine_root(self) -> Path:
        return ENGINE_ROOT

    # --- Project & Naming Conventions ---
    @property
    def project_section(self) -> dict[str, Any]:
        return self.raw_config.get("project", {})

    @property
    def project_name(self) -> str:
        return str(self.project_section.get("name") or self.root.name)

    @property
    def grouping_mode(self) -> str:
        mode = str(self.project_section.get("grouping_mode") or "by_batch").strip()
        return mode if mode in GROUPING_MODES else "by_batch"

    @property
    def batch_prefix(self) -> str:
        if "batch_prefix" in self.project_section:
            return str(self.project_section.get("batch_prefix") or "").strip().rstrip("-")
        return ""

    @property
    def default_batches(self) -> list[str]:
        configured = self.project_section.get("default_batches")
        if isinstance(configured, list) and configured:
            return [str(item) for item in configured if str(item).strip()]
        return []

    @property
    def processed_dir_pattern(self) -> str:
        return str(self.project_section.get("processed_dir_pattern") or "{batch_id}")

    @property
    def raw_dir_pattern(self) -> str:
        return str(self.project_section.get("raw_dir_pattern") or "{batch_id}")

    @property
    def figure_dir_pattern(self) -> str:
        return str(self.project_section.get("figure_dir_pattern") or "{domain}/{batch_id}")

    # --- Core Directory Resolution ---
    def resolve_configured_path(self, key: str, fallback_rel: str | None = None) -> Path:
        paths_cfg = self.raw_config.get("paths", {})
        raw_val = paths_cfg.get(key) or fallback_rel or DEFAULT_WORKSPACE_DICT["paths"].get(key, key)
        candidate = Path(str(raw_val)).expanduser()
        if candidate.is_absolute():
            return candidate
        return self.root / candidate

    @property
    def raw_dir(self) -> Path:
        return self.resolve_configured_path("raw", "data/raw")

    @property
    def processed_dir(self) -> Path:
        return self.resolve_configured_path("processed", "data/processed")

    @property
    def metadata_dir(self) -> Path:
        configured = self.resolve_configured_path("metadata", "data/metadata")
        if not self.is_initialized and not configured.exists():
            legacy_lab = self.root / "data" / "lab"
            if legacy_lab.exists():
                return legacy_lab
        return configured

    @property
    def batches_json(self) -> Path:
        return self.metadata_dir / "batches.json"

    @property
    def samples_json(self) -> Path:
        return self.metadata_dir / "samples.json"

    @property
    def lab_markdown(self) -> Path:
        return self.metadata_dir / "lab_metadata.md"

    @property
    def legacy_lab_batches_json(self) -> Path:
        return self.root / "configs" / "lab_batches.json"

    @property
    def references_dir(self) -> Path:
        configured = self.resolve_configured_path("references", "data/references/literature")
        if not self.is_initialized and not configured.exists():
            legacy_ref = self.root / "data" / "reference"
            if legacy_ref.exists():
                return legacy_ref
        return configured

    @property
    def reference_samples_json(self) -> Path:
        primary = self.references_dir / "samples.json"
        if primary.exists():
            return primary
        legacy = self.root / "data" / "reference" / "samples.json"
        if legacy.exists():
            return legacy
        return primary

    @property
    def xrd_cards_dir(self) -> Path:
        configured = self.resolve_configured_path("xrd_cards", "data/references/xrd_cards")
        if configured.exists():
            return configured
        legacy_local = self.root / "data" / "pdf_card"
        if legacy_local.exists():
            return legacy_local
        bundled_engine = ENGINE_ROOT / "data" / "pdf_card"
        if bundled_engine.exists() and not self.is_initialized:
            return bundled_engine
        return configured

    @property
    def xrd_standard_dir(self) -> Path:
        cards = self.xrd_cards_dir
        sub = cards / "plot_standards"
        if sub.is_dir():
            return sub
        if cards.is_dir():
            return cards
        # Fallback to bundled engine PDF standards when local workspace xrd_cards is empty
        engine_std = ENGINE_ROOT / "data" / "pdf_card" / "plot_standards"
        if engine_std.is_dir():
            return engine_std
        return cards

    @property
    def figures_dir(self) -> Path:
        return self.resolve_configured_path("figures", "outputs/figures")

    @property
    def models_dir(self) -> Path:
        return self.resolve_configured_path("models", "outputs/models")

    @property
    def reports_dir(self) -> Path:
        return self.resolve_configured_path("reports", "outputs/reports")

    @property
    def cache_dir(self) -> Path:
        return self.resolve_configured_path("cache", "outputs/cache")

    @property
    def recipes_dir(self) -> Path:
        configured = self.resolve_configured_path("recipes", "configs/plot_recipes")
        if not configured.exists():
            for alt_name in ("plot_recipes", "recipes"):
                legacy = self.root / "configs" / alt_name
                if legacy.exists():
                    return legacy
        return configured

    @property
    def schemas_dir(self) -> Path:
        return self.resolve_configured_path("schemas", "configs/schemas")

    @property
    def demo_dir(self) -> Path:
        local_demo = self.root / "data" / "demo"
        if local_demo.exists():
            return local_demo
        return ENGINE_ROOT / "data" / "demo"

    # --- Data Types & Plotting Defaults ---
    @property
    def data_types(self) -> dict[str, Any]:
        return self.raw_config.get("data_types", DEFAULT_WORKSPACE_DICT["data_types"])

    @property
    def xrd_wavelength_angstrom(self) -> float:
        try:
            return float(self.data_types.get("xrd", {}).get("wavelength_angstrom", 1.5406))
        except (TypeError, ValueError):
            return 1.5406

    @property
    def plotting_defaults(self) -> dict[str, Any]:
        return self.raw_config.get("plotting", DEFAULT_WORKSPACE_DICT["plotting"])

    @property
    def default_plot_formats(self) -> list[str]:
        fmts = self.plotting_defaults.get("formats", ["svg"])
        return [str(f).strip().lstrip(".") for f in fmts if str(f).strip()] or ["svg"]

    @property
    def default_color_set(self) -> str | None:
        val = self.plotting_defaults.get("color_set")
        return str(val).strip() if val else None

    @property
    def data_figures_subdir(self) -> str:
        return str(self.plotting_defaults.get("data_figures_subdir") or "figures")

    # --- Subfolder Pattern Helpers (Batch / System / Comparisons) ---
    def _split_system_and_batch(self, batch_id: str, system: str | None = None) -> tuple[str, str]:
        clean = str(batch_id).strip().strip("/\\")
        if "/" in clean or "\\" in clean:
            parts = clean.replace("\\", "/").split("/", 1)
            return parts[0], parts[1]
        if system:
            return str(system).strip(), clean
        return "", clean

    def _format_subpath(self, pattern: str, *, batch_id: str, system: str = "", domain: str = "") -> Path:
        sys_part, b_part = self._split_system_and_batch(batch_id, system)
        rendered = pattern.format(
            batch_id=b_part,
            system=sys_part or "general",
            project=b_part,
            domain=domain,
        )
        # Collapse leading/duplicate slashes if system or domain is omitted
        parts = [seg for seg in rendered.replace("\\", "/").split("/") if seg]
        if not sys_part and "{system}" in pattern and parts and parts[0] == "general":
            parts = parts[1:]
        return Path(*parts) if parts else Path(b_part)

    def raw_batch_dir(self, batch_id: str, system: str | None = None) -> Path:
        sys_part, b_part = self._split_system_and_batch(batch_id, system)
        primary = self.raw_dir / self._format_subpath(self.raw_dir_pattern, batch_id=b_part, system=sys_part)
        if primary.exists() or sys_part or self.grouping_mode != "by_system_batch":
            return primary
        # Auto-discover <raw>/<system>/<batch_id> when grouping_mode is by_system_batch
        if self.raw_dir.is_dir():
            for sys_dir in sorted(p for p in self.raw_dir.iterdir() if p.is_dir()):
                candidate = sys_dir / b_part
                if candidate.is_dir():
                    return candidate
        return primary

    def processed_batch_dir_candidates(self, batch_id: str, system: str | None = None) -> list[Path]:
        sys_part, b_part = self._split_system_and_batch(batch_id, system)
        primary = self.processed_dir / self._format_subpath(
            self.processed_dir_pattern, batch_id=b_part, system=sys_part
        )
        candidates = [primary]
        alt_clean = self.processed_dir / (Path(sys_part) / b_part if sys_part else Path(b_part))
        alt_legacy = self.processed_dir / (
            Path(sys_part) / f"{b_part}-processed" if sys_part else Path(f"{b_part}-processed")
        )
        for cand in (alt_clean, alt_legacy):
            if cand not in candidates:
                candidates.append(cand)
        if not sys_part and self.grouping_mode == "by_system_batch" and self.processed_dir.is_dir():
            for sys_dir in sorted(p for p in self.processed_dir.iterdir() if p.is_dir()):
                for sub_name in (b_part, f"{b_part}-processed"):
                    cand = sys_dir / sub_name
                    if cand.is_dir() and cand not in candidates:
                        candidates.insert(0, cand)
        return candidates

    def processed_batch_dir(self, batch_id: str, system: str | None = None, *, prefer_existing: bool = True) -> Path:
        candidates = self.processed_batch_dir_candidates(batch_id, system=system)
        if prefer_existing:
            for candidate in candidates:
                if candidate.exists():
                    return candidate
        return candidates[0]

    def processed_sample_csv(self, batch_id: str, sample_id: str, system: str | None = None) -> Path:
        return self.processed_batch_dir(batch_id, system=system) / f"{sample_id}.csv"

    def _infer_system_for_batch(self, batch_id: str) -> str:
        if self.grouping_mode != "by_system_batch":
            return ""
        for base in (self.processed_dir, self.raw_dir):
            if not base.is_dir():
                continue
            for sys_dir in sorted(p for p in base.iterdir() if p.is_dir()):
                if (sys_dir / batch_id).is_dir() or (sys_dir / f"{batch_id}-processed").is_dir():
                    return sys_dir.name
        return ""

    def te_batch_figure_dir(self, batch_id: str, system: str | None = None) -> Path:
        sys_part, b_part = self._split_system_and_batch(batch_id, system)
        if not sys_part:
            sys_part = self._infer_system_for_batch(b_part)
        pattern = self.figure_dir_pattern
        sub = self._format_subpath(pattern, batch_id=b_part, system=sys_part, domain="te")
        return self.figures_dir / sub

    def te_comparison_figure_dir(self, comparison_id: str) -> Path:
        # Preserve legacy inter-batch layout if explicitly configured without {domain}, else clean comparisons/
        if "{domain}" not in self.figure_dir_pattern:
            return self.figures_dir / "inter-batch" / comparison_id
        return self.figures_dir / "te" / "comparisons" / comparison_id

    def xrd_figure_dir(self, group_id: str | None = None) -> Path:
        base = self.figures_dir / "xrd" if "{domain}" in self.figure_dir_pattern else self.figures_dir / "xrd"
        return base / group_id if group_id else base

    def model_output_dir(self, model_name: str) -> Path:
        return self.models_dir / model_name

    def report_output_dir(self, category: str | None = None) -> Path:
        return self.reports_dir / category if category else self.reports_dir

    def relative_or_posix(self, path: Path | str) -> str:
        target = Path(path)
        if not target.is_absolute():
            return target.as_posix()
        try:
            return target.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return target.as_posix()

    def ensure_directories(self, *, include_optional: bool = True) -> list[Path]:
        """Create all configured workspace directories and return the created/verified paths."""
        targets = [
            self.raw_dir,
            self.processed_dir,
            self.metadata_dir,
            self.references_dir,
            self.xrd_cards_dir,
            self.figures_dir,
            self.models_dir,
            self.reports_dir,
            self.cache_dir,
        ]
        if include_optional:
            targets.extend([self.recipes_dir, self.schemas_dir])
        created: list[Path] = []
        for directory in targets:
            directory.mkdir(parents=True, exist_ok=True)
            created.append(directory)
        return created


_WORKSPACE_CACHE: dict[Path, WorkspacePaths] = {}


def load_workspace(workspace: Path | str | None = None, *, reload: bool = False) -> WorkspacePaths:
    """Load and return ``WorkspacePaths`` for ``workspace`` (or discovered active workspace)."""
    cfg_path, root = find_workspace_config(workspace)
    resolved_root = root.resolve()
    if not reload and resolved_root in _WORKSPACE_CACHE:
        return _WORKSPACE_CACHE[resolved_root]

    if cfg_path is not None and cfg_path.is_file():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in workspace config {cfg_path}: {exc}") from exc
        merged = _deep_merge(DEFAULT_WORKSPACE_DICT, loaded)
        ws = WorkspacePaths(
            root=resolved_root,
            config_path=cfg_path,
            raw_config=merged,
            is_initialized=True,
        )
    else:
        default_cfg = copy.deepcopy(DEFAULT_WORKSPACE_DICT)
        default_cfg["project"]["name"] = resolved_root.name
        # Preserve legacy processed folder suffix if uninitialized legacy data/lab exists
        if (resolved_root / "data" / "lab").exists():
            default_cfg["project"]["processed_dir_pattern"] = "{batch_id}-processed"
            default_cfg["project"]["figure_dir_pattern"] = "{batch_id}"
        ws = WorkspacePaths(
            root=resolved_root,
            config_path=resolved_root / "configs" / "workspace.json",
            raw_config=default_cfg,
            is_initialized=False,
        )

    _WORKSPACE_CACHE[resolved_root] = ws
    return ws


def get_workspace(workspace: Path | str | None = None) -> WorkspacePaths:
    """Return the active ``WorkspacePaths`` (cached per workspace root)."""
    return load_workspace(workspace=workspace, reload=False)


def clear_workspace_cache() -> None:
    """Clear cached ``WorkspacePaths`` instances (useful in tests and after ``init``)."""
    _WORKSPACE_CACHE.clear()


__all__ = [
    "DEFAULT_WORKSPACE_DICT",
    "ENGINE_ROOT",
    "GROUPING_MODES",
    "SCHEMA_VERSION",
    "WORKSPACE_CONFIG_CANDIDATES",
    "WorkspacePaths",
    "build_workspace_config_dict",
    "clear_workspace_cache",
    "default_patterns_for_grouping",
    "find_workspace_config",
    "get_workspace",
    "load_workspace",
]

#!/usr/bin/env python3
"""Initialize or inspect a clean Mode-B user data workspace for TEDEX.

Creates ``configs/workspace.json`` plus clean data/output directories and starter
metadata ledgers—without copying Python source code, agents, or skills into the
user's data folder.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from te_analysis.paths import (  # noqa: E402
    DEFAULT_WORKSPACE_DICT,
    ENGINE_ROOT,
    GROUPING_MODES,
    WorkspacePaths,
    build_workspace_config_dict,
    clear_workspace_cache,
    load_workspace,
)

RADIATION_WAVELENGTHS_ANGSTROM: dict[str, float] = {
    "cu-ka": 1.5406,
    "cuka": 1.5406,
    "cu": 1.5406,
    "mo-ka": 0.71073,
    "moka": 0.71073,
    "mo": 0.71073,
    "co-ka": 1.78897,
    "coka": 1.78897,
    "co": 1.78897,
    "ag-ka": 0.55941,
    "ag": 0.55941,
}

STARTER_LAB_MARKDOWN = """# Lab Metadata

Edit values in the tables below, then run `te sync markdown` (or `python main.py sync markdown`) to write edits back to JSON.

## Batches

_No batches recorded yet. Drop raw ZEM/LFA files under your configured `raw` folder and run `te sync metadata`._

## Samples

_No samples recorded yet._
"""


def _prompt_with_default(prompt_text: str, default: str) -> str:
    suffix = f" [{default}]" if default != "" else " [none]"
    raw = input(f"{prompt_text}{suffix}: ").strip()
    return raw if raw else default


def _resolve_wavelength(radiation: str, explicit_wavelength: float | None) -> float:
    if explicit_wavelength is not None:
        return float(explicit_wavelength)
    key = str(radiation or "Cu-Ka").strip().lower()
    return RADIATION_WAVELENGTHS_ANGSTROM.get(key, 1.5406)


def format_workspace_status(ws: WorkspacePaths) -> dict[str, Any]:
    return {
        "is_initialized": ws.is_initialized,
        "workspace_root": str(ws.root),
        "engine_root": str(ws.engine_root),
        "config_path": str(ws.config_path) if ws.config_path else None,
        "project": ws.raw_config.get("project", {}),
        "resolved_paths": {
            "raw": str(ws.raw_dir),
            "processed": str(ws.processed_dir),
            "metadata": str(ws.metadata_dir),
            "references": str(ws.references_dir),
            "xrd_cards": str(ws.xrd_cards_dir),
            "figures": str(ws.figures_dir),
            "models": str(ws.models_dir),
            "reports": str(ws.reports_dir),
            "cache": str(ws.cache_dir),
            "recipes": str(ws.recipes_dir),
            "schemas": str(ws.schemas_dir),
        },
        "data_types": ws.data_types,
        "plotting": ws.plotting_defaults,
    }


def print_onboarding_checklist(target_root: Path) -> None:
    print(f"Workspace at {target_root} is not initialized yet (missing configs/workspace.json).")
    print("\nConfirm the following items with the user before running `te init --yes ...`:")
    print("  1. Directory locations (press Enter / accept defaults or point to custom paths):")
    for key, val in DEFAULT_WORKSPACE_DICT["paths"].items():
        print(f"     - {key:<12}: {val}")
    print("  2. Subfolder grouping strategy (--grouping):")
    print("     - by_batch        : data/raw/<batch_id>/ -> outputs/figures/te/<batch_id>/")
    print("     - by_system_batch : data/raw/<system>/<batch_id>/ -> outputs/figures/te/<system>/<batch_id>/")
    print("     - by_project      : data/processed/<project>/ -> outputs/figures/<project>/")
    print("  3. Sample/batch prefix (--batch-prefix, e.g. 'TE', 'SNSE', or empty '' for free naming)")
    print("  4. Instrument & unit conventions:")
    print("     - Electrical / Thermal : ZEM-3 + LFA, PPMS, or pre-processed CSV (--elec-instrument, --thermal-instrument)")
    print("     - XRD radiation        : Cu-Ka (1.5406 A), Mo-Ka (0.71073 A), or custom --xrd-wavelength")
    print("     - Units & plot formats : --sigma-unit (S/cm or S/m), --formats (svg png pdf), --color-set (npg)")


def initialize_workspace(
    target_dir: Path | str,
    *,
    config_payload: dict[str, Any],
    force: bool = False,
    create_starter_ledgers: bool = True,
) -> WorkspacePaths:
    root = Path(target_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    cfg_path = root / "configs" / "workspace.json"

    if cfg_path.exists() and not force:
        raise FileExistsError(
            f"Workspace config already exists at {cfg_path}. Pass --force to overwrite."
        )

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(config_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    clear_workspace_cache()
    ws = load_workspace(root, reload=True)
    ws.ensure_directories(include_optional=True)

    # Keep cache directory ignored from Git
    cache_gitignore = ws.cache_dir / ".gitignore"
    if not cache_gitignore.exists():
        cache_gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")

    # Seed empty starter metadata files so `sync` and `analyze` work out of the box
    if create_starter_ledgers:
        if not ws.batches_json.exists():
            ws.batches_json.write_text("[]\n", encoding="utf-8")
        if not ws.samples_json.exists():
            ws.samples_json.write_text("[]\n", encoding="utf-8")
        if not ws.lab_markdown.exists():
            ws.lab_markdown.write_text(STARTER_LAB_MARKDOWN, encoding="utf-8")

    return ws


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Initialize or inspect a clean TEDEX user data workspace (configs/workspace.json)."
    )
    p.add_argument(
        "target_dir",
        nargs="?",
        default=".",
        help="Target user project folder to initialize or inspect (default: current directory).",
    )
    p.add_argument("--status", action="store_true", help="Print resolved workspace paths and conventions without modifying files.")
    p.add_argument(
        "--check",
        action="store_true",
        help="Exit with code 0 if initialized, or exit with code 2 and print the onboarding checklist if uninitialized.",
    )
    p.add_argument("--json", action="store_true", help="Emit status output as JSON (for AI agent onboarding).")
    p.add_argument("-y", "--yes", "--defaults", dest="yes", action="store_true", help="Non-interactive mode: accept defaults for any unprovided options.")
    p.add_argument("--force", action="store_true", help="Overwrite an existing configs/workspace.json.")

    # Project & Grouping
    p.add_argument("--name", default=None, help="Human-readable project name.")
    p.add_argument("--grouping", choices=GROUPING_MODES, default=None, help="Subfolder organization mode.")
    p.add_argument("--batch-prefix", default=None, help="Optional sample/batch ID prefix (e.g. TE, SNSE, or '' for none).")
    p.add_argument("--processed-pattern", default=None, help="Subfolder pattern inside processed/ (e.g. '{batch_id}' or '{batch_id}-processed').")
    p.add_argument("--default-batches", nargs="*", default=None, help="Optional default batch IDs.")

    # Custom Folder Locations
    p.add_argument("--raw-dir", default=None, help="Raw measurement folder (default: data/raw).")
    p.add_argument("--processed-dir", default=None, help="Processed CSV folder (default: data/processed).")
    p.add_argument("--metadata-dir", default=None, help="Sample/batch metadata folder (default: data/metadata).")
    p.add_argument("--references-dir", default=None, help="Literature benchmark data folder (default: data/references/literature).")
    p.add_argument("--xrd-cards-dir", default=None, help="XRD PDF standard cards folder (default: data/references/xrd_cards).")
    p.add_argument("--figures-dir", default=None, help="Exported figures root (default: outputs/figures).")
    p.add_argument("--models-dir", default=None, help="Physics & ML numeric fit outputs root (default: outputs/models).")
    p.add_argument("--reports-dir", default=None, help="Markdown reports & assessments root (default: outputs/reports).")
    p.add_argument("--cache-dir", default=None, help="Disposable cache & logs folder (default: outputs/cache).")
    p.add_argument("--recipes-dir", default=None, help="Reusable JSON plot recipes folder (default: configs/plot_recipes).")
    p.add_argument("--schemas-dir", default=None, help="Instrument column mapping schemas folder (default: configs/schemas).")

    # Instrument & Data Types
    p.add_argument("--elec-instrument", default=None, help="Electrical transport instrument (e.g. ZEM-3, PPMS, LSR, CSV).")
    p.add_argument("--sigma-unit", default=None, choices=("S/cm", "S/m", "mOhm*cm"), help="Preferred electrical conductivity unit.")
    p.add_argument("--temp-unit", default=None, choices=("K", "C"), help="Preferred temperature unit.")
    p.add_argument("--thermal-instrument", default=None, help="Thermal transport instrument (e.g. LFA, PPMS, Direct-kappa).")
    p.add_argument("--xrd-radiation", default=None, help="XRD anode/source label (e.g. Cu-Ka, Mo-Ka, Co-Ka, Synchrotron).")
    p.add_argument("--xrd-wavelength", type=float, default=None, help="XRD wavelength in Angstrom (default: 1.5406 for Cu-Ka).")
    p.add_argument("--cp-unit", default=None, choices=("J/molK", "mJ/molK", "J/gK"), help="Heat capacity unit.")

    # Plotting Preferences
    p.add_argument("--formats", nargs="+", default=None, help="Default figure export formats (e.g. svg png).")
    p.add_argument("--color-set", default=None, help="Default color palette (default: npg).")
    p.add_argument("--no-copy-beside-data", action="store_true", help="Disable copying figures into a sidecar figures/ folder beside data.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target_root = Path(args.target_dir).expanduser().resolve()

    if args.status or args.check:
        ws = load_workspace(target_root, reload=True)
        payload = format_workspace_status(ws)
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            state = "INITIALIZED" if ws.is_initialized else "UNINITIALIZED (using fallback defaults)"
            print(f"TEDEX Workspace Status: {state}")
            print(f"  Workspace root : {ws.root}")
            print(f"  Software root  : {ws.engine_root}")
            print(f"  Config file    : {ws.config_path}")
            print(f"  Grouping mode  : {ws.grouping_mode} (prefix={ws.batch_prefix or 'none'})")
            for k, v in payload["resolved_paths"].items():
                print(f"  - {k:<12} : {v}")
        if args.check and not ws.is_initialized:
            if not args.json:
                print()
                print_onboarding_checklist(target_root)
            return 2
        return 0

    interactive = sys.stdin.isatty() and not args.yes
    default_name = args.name or target_root.name or "Thermoelectric Project"
    grouping = args.grouping or "by_batch"
    prefix = args.batch_prefix if args.batch_prefix is not None else ""
    raw_dir = args.raw_dir or DEFAULT_WORKSPACE_DICT["paths"]["raw"]
    processed_dir = args.processed_dir or DEFAULT_WORKSPACE_DICT["paths"]["processed"]
    metadata_dir = args.metadata_dir or DEFAULT_WORKSPACE_DICT["paths"]["metadata"]
    xrd_cards_dir = args.xrd_cards_dir or DEFAULT_WORKSPACE_DICT["paths"]["xrd_cards"]
    figures_dir = args.figures_dir or DEFAULT_WORKSPACE_DICT["paths"]["figures"]
    radiation = args.xrd_radiation or "Cu-Ka"

    if interactive:
        print(f"=== Initializing TEDEX Data Workspace in {target_root} ===")
        default_name = _prompt_with_default("Project name", default_name)
        grouping_in = _prompt_with_default("Grouping mode (by_batch / by_system_batch / by_project)", grouping)
        if grouping_in in GROUPING_MODES:
            grouping = grouping_in
        prefix = _prompt_with_default("Sample/batch ID prefix (e.g. TE, SNSE, or leave blank)", prefix)
        raw_dir = _prompt_with_default("Raw data folder", raw_dir)
        processed_dir = _prompt_with_default("Processed data folder", processed_dir)
        metadata_dir = _prompt_with_default("Metadata ledger folder", metadata_dir)
        xrd_cards_dir = _prompt_with_default("XRD PDF standard cards folder", xrd_cards_dir)
        figures_dir = _prompt_with_default("Exported figures folder", figures_dir)
        radiation = _prompt_with_default("XRD radiation source (Cu-Ka / Mo-Ka / Co-Ka / Synchrotron)", radiation)

    wavelength = _resolve_wavelength(radiation, args.xrd_wavelength)

    path_overrides = {
        "raw": raw_dir,
        "processed": processed_dir,
        "metadata": metadata_dir,
        "references": args.references_dir,
        "xrd_cards": xrd_cards_dir,
        "figures": figures_dir,
        "models": args.models_dir,
        "reports": args.reports_dir,
        "cache": args.cache_dir,
        "recipes": args.recipes_dir,
        "schemas": args.schemas_dir,
    }

    data_type_overrides: dict[str, Any] = {
        "xrd": {
            "radiation": radiation,
            "wavelength_angstrom": wavelength,
        }
    }
    if args.elec_instrument or args.sigma_unit or args.temp_unit:
        elec: dict[str, Any] = {}
        if args.elec_instrument:
            elec["instrument"] = args.elec_instrument
        if args.sigma_unit:
            elec["conductivity_unit"] = args.sigma_unit
        if args.temp_unit:
            elec["temperature_unit"] = args.temp_unit
        data_type_overrides["electrical_transport"] = elec
    if args.thermal_instrument:
        data_type_overrides["thermal_transport"] = {"instrument": args.thermal_instrument}
    if args.cp_unit:
        data_type_overrides["hall_and_cp"] = {"cp_unit": args.cp_unit}

    plotting_overrides: dict[str, Any] = {}
    if args.formats:
        plotting_overrides["formats"] = [f.strip().lstrip(".") for f in args.formats if f.strip()]
    if args.color_set:
        plotting_overrides["color_set"] = args.color_set
    if args.no_copy_beside_data:
        plotting_overrides["copy_beside_data"] = False

    config_payload = build_workspace_config_dict(
        project_name=default_name,
        grouping_mode=grouping,
        batch_prefix=prefix,
        processed_dir_pattern=args.processed_pattern,
        default_batches=args.default_batches,
        path_overrides=path_overrides,
        data_type_overrides=data_type_overrides,
        plotting_overrides=plotting_overrides,
    )

    try:
        ws = initialize_workspace(target_root, config_payload=config_payload, force=args.force)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(format_workspace_status(ws), indent=2, ensure_ascii=False))
    else:
        print(f"Initialized TEDEX workspace: {ws.root}")
        print(f"Saved configuration        : {ws.config_path}")
        print(f"Grouping mode              : {ws.grouping_mode} (prefix={ws.batch_prefix or 'none'})")
        print(f"Software engine root       : {ENGINE_ROOT}")
        print("Created / verified folders :")
        for key, path_val in format_workspace_status(ws)["resolved_paths"].items():
            print(f"  - {key:<12}: {path_val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

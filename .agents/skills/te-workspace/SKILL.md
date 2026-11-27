---
name: te-workspace
description: >-
  Initialize, inspect, or reconfigure a clean user thermoelectric data workspace
  (configs/workspace.json) for TEDEX workflows. Use whenever entering a new project
  folder without configs/workspace.json, when `te init --check` exits with code 2, or
  when the user asks to configure data/output directories, batch/system subfolder naming,
  or instrument/unit conventions.
---

# TEDEX Workspace Initialization & Directory Configuration (`init`)

TEDEX separates the **software/plugin layer** (`te` / `tedex` CLI + `te_analysis` package + skills) from the **user's clean project directory** (which holds only `configs/workspace.json`, `data/`, and `outputs/`—zero Python scripts or skill files).

## 1. Check Initialization State First

Before running batch pipelines in an unfamiliar workspace, check whether `configs/workspace.json` exists:

```bash
te init --check --json
# (or inside the engine repository: python main.py init --check --json)
```

- **Exit code `0`**: Workspace is already initialized. Respect `resolved_paths`, `grouping_mode`, `batch_prefix`, and `data_types` from the JSON output.
- **Exit code `2`**: Workspace is uninitialized. Confirm the configuration choices below with the user before creating folders.

## 2. Ask the User to Confirm Locations & Data Types

Do **not** silently invent custom folder names or assume sample prefixes for a new user. Present the clean defaults concisely and ask what they want to keep or customize:

1. **Folder Locations (`paths`)** — keep defaults or point to existing/shared directories (relative or absolute paths are both supported):
   - `data/raw` — Raw measurement exports (ZEM, LFA, XRD, Hall, $C_p$)
   - `data/processed` — Cleaned & interpolated transport CSVs + `extracted_features.json`
   - `data/metadata` — Sample/batch ledgers (`lab_metadata.md`, `batches.json`, `samples.json`)
   - `data/references/literature` & `data/references/xrd_cards` — Literature benchmarks & XRD PDF cards (can point directly to a shared lab drive)
   - `outputs/figures`, `outputs/models`, `outputs/reports`, `outputs/cache` — Generated plots, numeric model fits, Markdown reports, and cache
   - `configs/plot_recipes` & `configs/schemas` — Reusable `sciplot` JSON recipes and column schemas
2. **Subfolder Grouping Strategy (`--grouping`)**:
   - `by_batch` *(default)*: `data/raw/<batch_id>/` $\rightarrow$ `outputs/figures/te/<batch_id>/`
   - `by_system_batch`: `data/raw/<system>/<batch_id>/` $\rightarrow$ `outputs/figures/te/<system>/<batch_id>/` (ideal for multi-system projects)
   - `by_project`: `data/processed/<project>/` $\rightarrow$ `outputs/figures/<project>/` (ideal for standalone modeling/plotting)
   - Optional **Batch Prefix (`--batch-prefix`)**: e.g. `SNSE`, `PBTE`, or `""` (free naming).
3. **Instrument & Data Conventions (`data_types` & `plotting`)**:
   - Electrical & thermal instruments (`ZEM-3` + `LFA`, `PPMS`, `LSR`, or pre-processed `CSV`)
   - XRD radiation & wavelength (default `Cu-Ka` = `1.5406 Å`; `Mo-Ka` = `0.71073 Å`; `Co-Ka` = `1.78897 Å`; `Ag-Ka` = `0.55941 Å`; or custom `--xrd-wavelength`)
   - Preferred units (`--sigma-unit S/cm|S/m`, `--temp-unit K|C`, `--cp-unit J/molK|mJ/molK|J/gK`) and figure formats (`--formats svg png`).

## 3. Lock In the Workspace Configuration

Once the user confirms, execute `te init --yes` with their chosen flags:

```bash
# Example A: Accept clean defaults with by_system_batch grouping
te init --yes --name "CuInTe2 Doping Study" --grouping by_system_batch

# Example B: Custom XRD card location and sample prefix
te init --yes \
  --name "SnSe High-T Transport" \
  --grouping by_batch \
  --batch-prefix "SNSE" \
  --xrd-cards-dir "D:/SharedLab/XRD_PDF_Cards" \
  --formats svg png
```

This writes `configs/workspace.json`, scaffolds the configured folders, creates starter `batches.json` / `samples.json` / `lab_metadata.md` files, and adds `outputs/cache/.gitignore`. All subsequent `te` / `python main.py` commands automatically read from `configs/workspace.json`.

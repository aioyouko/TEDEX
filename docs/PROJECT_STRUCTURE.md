# Project Structure

The root directory is intentionally reserved for the user-facing launcher:

```text
main.py
```

Everything else should land in one of these buckets:

| Folder | Purpose |
| --- | --- |
| `src/` | Importable source modules used by `main.py` and `scripts/`. |
| `scripts/analysis/` | Runnable analysis workflows such as TE processing, assessment, agent analysis, and Bayesian prediction. |
| `scripts/plotting/` | Runnable plotting entry scripts for TE, XRD, and flexible recipes. |
| `scripts/` | Supporting sync/export utilities and small shell helpers. |
| `data/raw/` | Original instrument exports and unmodified source data. |
| `data/processed/` | Cleaned CSVs and extracted features generated from raw data. |
| `data/lab/` | Batch/sample ledgers and lab metadata. |
| `data/reference/` | Literature/reference datasets, extracted text, PDF-card data, and reference features. |
| `configs/` | Plot recipes, batch templates, and schema/config JSON files. |
| `results/` | Standard outputs produced by the analysis scripts. |
| `outputs/` | Standalone artifacts, exported figures, decks, tables, logs, and one-off generated outputs. |
| `outputs/cache/` | Ignored local cache archive for `.pyc`, Jupyter checkpoints, and macOS metadata. |
| `notebooks/` | Scratch notebooks and exploratory work. |
| `docs/` | Human-facing instructions, command notes, and project documentation. |
| `skills/` | Local skill instructions used by Codex workflows. |
| `external/` | Third-party snapshots or archived external code. |

## Practical Rules

1. User-facing tools should be launched through `python main.py <command>`.
2. New reusable functions go in `src/tools/` or another `src/` package.
3. New experiment data goes in `data/raw/` first, then processed outputs go in
   `data/processed/`.
4. New generated plots from standard TE/XRD scripts should stay under
   `outputs/figures/te/` or `outputs/figures/xrd/`.
5. One-off figures or exports should go under `outputs/figures/`,
   `outputs/tables/`, or `outputs/logs/`.
6. Notebooks should be named for their purpose, not `Untitled.ipynb`.
7. Do not hardcode API keys in notebooks or scripts; use `.env`.

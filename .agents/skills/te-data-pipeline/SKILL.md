---
name: te-data-pipeline
description: >-
  Manage thermoelectric raw data batch processing (ZEM + LFA raw files via `analyze`),
  metadata ledger synchronization (`sync metadata`, `sync markdown`, `batches.json`,
  `samples.json`, `lab_metadata.md`), batch optimization assessment (`assess`), Bayesian
  property prediction (`bayes`), and sample densification/metadata verification. Use
  whenever working with raw ZEM/LFA measurement folders, sample metadata ledgers, batch
  performance comparisons, or Bayesian candidate screening.
---

# Thermoelectric Raw Data Pipeline, Metadata Sync & Batch Assessment

All data pipeline commands resolve directories (`paths.raw`, `paths.processed`, `paths.metadata`, `paths.reports`) dynamically from `configs/workspace.json` (`te_analysis/paths.py`).

## 1. Sample Metadata & Densification Verification Protocol

Whenever comparing transport performance across samples or batches:
1. **Inspect `lab_metadata.md` / `samples.json` First**: Look up each target sample's `density`, `cp_value`, `sample_composition`, `synthesis_route`, `annealing_condition`, and `notes` under `paths.metadata` before interpreting transport differences. (If working inside a laboratory repository with additional local rules in root `AGENTS.md`, follow those workspace-specific rules as well.)
2. **Account for Densification**: Treat sample density as a primary indicator of pressing densification and batch-to-batch variation. When comparing identical nominal compositions, explicitly discuss how density differences affect electrical conductivity ($\sigma$) and thermal conductivity ($\kappa$).
   - Quote **relative density (%)** only when a reliable theoretical crystal density is established.
   - Otherwise, compare measured densities ($\mathrm{g\ cm^{-3}}$) directly across identical nominal compositions without inventing a percentage.
3. **Verify Blank Fields**: Never treat blank metadata fields or legacy labels as confirmed experimental conditions; cross-check against raw files and user-confirmed details.

## 2. Raw ZEM + LFA Batch Processing (`analyze`)

Combines raw electrical transport (`<sample_id>_ZEM.txt`) and thermal diffusivity (`<sample_id>_LFA.csv` or `.xlsx`) files under `paths.raw` with sample `density` and `cp_value` from `paths.metadata`, computing $\sigma$, $S$, $PF$, $\kappa$, $zT$, SPB Lorenz number $L$, $\kappa_{\mathrm{e}}$, $\kappa_{\mathrm{L}}$, weighted mobility $\mu_W$, and quality factor $B$ into `paths.processed`:

```bash
# Analyze a single batch or specific samples within a batch
python main.py analyze <BATCH_ID>
python main.py analyze <BATCH_ID> --sample A B
python main.py analyze --all --dry-run
```

## 3. Metadata Ledger Synchronization (`sync`)

Keep `batches.json`, `samples.json`, and editable `lab_metadata.md` (under `paths.metadata`) synchronized:

```bash
# Scan raw/processed folders and update JSON + Markdown ledgers
python main.py sync metadata
python main.py sync metadata --dry-run

# Export JSON records to editable lab_metadata.md
python main.py sync markdown export

# Import manual edits from lab_metadata.md back into JSON
python main.py sync markdown import
python main.py sync markdown import --dry-run

# Optional Notion payload & Excel literature reference extraction
python main.py sync notion-payload --help
python main.py sync reference-xlsx --help
```

## 4. Batch Assessment, Bayesian Prediction & Agent Reports (`assess`, `bayes`, `agent`)

```bash
# Summarize batch optimization directions from extracted_features.json
python main.py assess <BATCH_ID>
python main.py assess --all

# Run Gaussian-process Bayesian TE candidate prediction
python main.py bayes --help

# Generate mechanistic AI report from extracted batch features
python main.py agent <BATCH_ID>
```

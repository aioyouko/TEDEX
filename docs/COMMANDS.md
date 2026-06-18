# Common Commands

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Metadata

Scan `data/raw` and create or update JSON and Markdown metadata:

```bash
python scripts/sync_lab_metadata.py
```

Export JSON to Markdown:

```bash
python scripts/sync_lab_markdown.py export
```

Import Markdown edits back to JSON:

```bash
python scripts/sync_lab_markdown.py
```

## Analysis

Run one batch:

```bash
python run_analysis.py CHY-1051
```

Run selected samples:

```bash
python run_analysis.py CHY-1051 --sample A B
python run_analysis.py CHY-1051-A CHY-1051-B
```

Preview selected targets without processing:

```bash
python run_analysis.py CHY-1051 --dry-run
```

## Plotting

Batch summary and single-property plots:

```bash
python plot_te.py CHY-1051 --plot-mode both --formats png pdf --no-show
```

Specific properties:

```bash
python plot_te.py CHY-1051 --properties seebeck conductivity power_factor zt --formats png pdf --no-show
```

Inter-batch comparison:

```bash
python plot_te.py CHY-1036 CHY-1040 CHY-1051 --inter-batch --plot-mode single --properties seebeck conductivity zt --formats png pdf --no-show
```

Direct processed CSV or folder:

```bash
python plot_te.py data/processed/CHY-1051-processed --plot-mode both --formats png pdf --no-show
python plot_te.py data/processed/CHY-1051-processed/CHY-1051-A.csv --seebeck --formats png pdf --no-show
```

Room-temperature dual-axis plot:

```bash
python scripts/plot_room_temp_dual_axis.py --samples CHY-1051 --temperature 300 --formats png pdf
```

Paper-style variants:

```bash
python scripts/plot_paper_style_te_variants.py --samples CHY-1051 --plot-type summary-panels --formats png pdf
```

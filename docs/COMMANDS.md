# Commands

Run commands from the release root:

```bash
cd te-analysis-plotting-v1.2.0
```

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

## Flexible Demo Plots

```bash
python flexible_plot.py --recipe configs/flexible_plot_demos/temperature_seebeck_line.json --formats png pdf --no-show
python flexible_plot.py --recipe configs/flexible_plot_demos/pbse_tec_qc_multi_files.json --formats png pdf --no-show
python flexible_plot.py --recipe configs/flexible_plot_demos/room_temp_dual_axis.json --formats png pdf --no-show
```

Direct CLI:

```bash
python flexible_plot.py data/demo/max_cooling_capacity/1.csv \
  --kind line \
  --x I \
  --y Q \
  --xlabel '$I$ (A)' \
  --ylabel '$Q_{\mathrm{c}}$ (W)' \
  --stem quick_qc_demo \
  --formats png pdf \
  --no-show
```

Installed entry:

```bash
te-flex-plot --recipe configs/flexible_plot_demos/temperature_seebeck_line.json --formats png pdf --no-show
```

## TE Analysis

Add private raw data and lab metadata locally, then use:

```bash
python scripts/sync_lab_metadata.py
python scripts/sync_lab_markdown.py export
python scripts/sync_lab_markdown.py
python run_analysis.py <BATCH_ID>
```

The release does not include private `data/raw`, `data/processed`, or `data/lab` content.

## TE Plotting

After adding processed CSV files locally:

```bash
python plot_te.py <BATCH_ID> --plot-mode both --formats png pdf --no-show
python plot_te.py data/processed/<BATCH_ID>-processed/<SAMPLE_ID>.csv --seebeck --formats png pdf --no-show
```

## XRD Plotting

After adding local XRD `.xy` files:

```bash
python plot_XRD.py <BATCH_ID> --mode both --formats png pdf
python plot_XRD.py data/raw/<BATCH_ID>/XRD --mode normalized --formats png pdf
```

## Assessment And Bayesian Helpers

These require local processed features/results:

```bash
python assess_selected_batches.py --help
python bayesian_predict_te.py --help
```

## Documentation

- `docs/FLEXIBLE_PLOTTING.md`
- `docs/PROJECT_STRUCTURE.md`

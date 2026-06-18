# TE Analysis and Plotting Workflow

Version: 1.0.0

This folder is a standalone release of the thermoelectric analysis and plotting workflow. It keeps the original project-style entry points:

- `run_analysis.py`: raw ZEM/LFA files to processed transport CSV, feature JSON, and summary plots.
- `plot_te.py`: batch, sample, inter-batch, and direct processed-CSV plotting.
- `scripts/plot_room_temp_dual_axis.py`: room-temperature Seebeck/conductivity comparison.
- `scripts/plot_paper_style_te_variants.py`: compact paper-style plot variants.
- `scripts/sync_lab_metadata.py` and `scripts/sync_lab_markdown.py`: lab metadata discovery and editing.

The release template intentionally does not include private raw data, processed data, or generated results. Those folders are present as empty placeholders.

## Quick Start

```bash
cd te-analysis-plotting-v1.0.0
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

You can also install only the requirements:

```bash
pip install -r requirements.txt
```

## Try The Demo

The demo uses small synthetic processed CSV files, so it only tests plotting.

```bash
cd examples/demo_project
python ../../plot_te.py CHY-DEMO --plot-mode both --formats png pdf --no-show
python ../../scripts/plot_room_temp_dual_axis.py --workspace . --samples CHY-DEMO --formats png pdf
```

Outputs are written under `examples/demo_project/results/plots/`.

If you installed with `pip install -e .`, the equivalent console commands are:

```bash
te-plot CHY-DEMO --plot-mode both --formats png pdf --no-show
te-room-temp-dual --workspace . --samples CHY-DEMO --formats png pdf
```

## Configure Your Own Data

Use this folder as the root of one TE workflow repository.

```text
data/
  raw/
    CHY-1051/
      CHY-1051-A_ZEM.txt
      CHY-1051-A_LFA.csv
  lab/
    batches.json
    samples.json
    lab_metadata.md
  processed/
results/
```

Raw file names should follow:

```text
<sample_id>_ZEM.txt
<sample_id>_LFA.csv
<sample_id>_LFA.txt
```

Then run:

```bash
python scripts/sync_lab_metadata.py
```

Edit `data/lab/lab_metadata.md` to fill density, heat capacity, sample composition, and notes. Import the edits:

```bash
python scripts/sync_lab_markdown.py
```

Run analysis:

```bash
python run_analysis.py CHY-1051
```

Create publication-style plots from processed CSV:

```bash
python plot_te.py CHY-1051 --plot-mode both --formats png pdf --no-show
python plot_te.py CHY-1051-A --seebeck --conductivity --formats png pdf --no-show
python plot_te.py CHY-1036 CHY-1040 CHY-1051 --inter-batch --plot-mode single --properties seebeck conductivity zt --formats png pdf --no-show
```

## Data Assumptions

The raw-data parser currently assumes:

- ZEM files are tab-delimited text with two header rows skipped.
- ZEM columns 0, 1, 4, and 5 map to temperature in Celsius, resistivity in ohm m, Seebeck in V/K, and power factor in W m^-1 K^-2.
- LFA files are either compact two-column CSV files or instrument exports containing `#Mean` rows.
- LFA temperature is in Celsius and diffusivity is used with density and heat capacity to compute thermal conductivity.
- Processed transport CSV files use temperature in K, conductivity in S/m, Seebeck in V/K, thermal conductivity in W m^-1 K^-1, and ZT as dimensionless.

See `docs/DATA_LAYOUT.md` and `docs/COMMANDS.md` for more detail.

## GitHub Notes

The `.gitignore` keeps `data/raw`, `data/processed`, and `results` out of version control by default. Commit code, docs, metadata templates, and lightweight examples; keep experimental data in a private location unless you explicitly want to publish it.

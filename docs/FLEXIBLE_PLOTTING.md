# Flexible Plotting

`flexible_plot.py` is for quick publication-style plots from loosely structured CSV/TXT/XLSX files. It is useful when a table is clean enough to plot but does not follow the processed TE transport schema used by `plot_te.py`.

Run commands from the release root:

```bash
cd te-analysis-plotting-v1.2.0
```

Default output folders:

```text
outputs/figures/flexible_cli/      # direct CLI mode
outputs/figures/flexible/          # reusable recipe mode
outputs/figures/flexible_demos/    # included demo recipes
```

## Direct CLI Mode

Basic line plot:

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

Multiple files on one plot:

```bash
python flexible_plot.py \
  --data data/demo/max_cooling_capacity/1.csv \
  --data data/demo/max_cooling_capacity/2.csv \
  --data data/demo/max_cooling_capacity/3.csv \
  --kind line \
  --x I \
  --y Q \
  --label "Condition 1" \
  --label "Condition 2" \
  --label "Condition 3" \
  --xlabel '$I$ (A)' \
  --ylabel '$Q_{\mathrm{c}}$ (W)' \
  --stem quick_qc_multi_file \
  --formats png pdf \
  --no-show
```

Dual-line plot with left and right y-axes:

```bash
python flexible_plot.py "data/demo/device power geenration/1.csv" \
  --kind dual_line \
  --x I \
  --y V \
  --y P \
  --label Voltage \
  --label Power \
  --xlabel '$I$ (mA)' \
  --ylabel "Voltage (mV)" \
  --right-ylabel "Power (mW)" \
  --legend outside \
  --stem quick_voltage_power \
  --formats png pdf \
  --no-show
```

Scatter plot:

```bash
python flexible_plot.py data/demo/composition_Hall/nu_muh.csv \
  --kind scatter \
  --x x \
  --y concentration \
  --xlabel "Content" \
  --ylabel '$n_{\mathrm{H}}$ ($10^{19}$ cm$^{-3}$)' \
  --stem quick_hall_scatter \
  --formats png pdf \
  --no-show
```

## Recipe Mode

Run one included demo recipe:

```bash
python flexible_plot.py --recipe configs/flexible_plot_demos/temperature_seebeck_line.json --formats png pdf --no-show
```

Run several demo recipes:

```bash
python flexible_plot.py \
  --recipe configs/flexible_plot_demos/temperature_seebeck_line.json \
  --recipe configs/flexible_plot_demos/pbse_tec_qc_multi_files.json \
  --recipe configs/flexible_plot_demos/room_temp_dual_axis.json \
  --formats png pdf \
  --no-show
```

Use a reusable recipe with a new data file and column overrides:

```bash
python flexible_plot.py data/demo/COP/1.csv \
  --recipe configs/plot_recipes/device/current_vs_cop.json \
  --x I \
  --y COP \
  --formats png pdf \
  --no-show
```

Installed entry point:

```bash
te-flex-plot --recipe configs/flexible_plot_demos/temperature_seebeck_line.json --formats png pdf --no-show
```

## Included Demo Recipes

| Recipe | Demonstrates |
| --- | --- |
| `configs/flexible_plot_demos/temperature_seebeck_line.json` | Single-file temperature line plot using `data/demo/temperature_vs_mobility/1.csv`. |
| `configs/flexible_plot_demos/temperature_multi_panel.json` | Multi-panel plot from two simple `x,y` temperature datasets. |
| `configs/flexible_plot_demos/composition_scatter.json` | Composition scatter plot from `data/demo/composition_Hall/nu_muh.csv`. |
| `configs/flexible_plot_demos/room_temp_dual_axis.json` | Dual-line Hall concentration and mobility plot. |
| `configs/flexible_plot_demos/pbse_tec_dtmax_txt.json` | Hot-side temperature versus maximum cooling temperature. |
| `configs/flexible_plot_demos/pbse_tec_qc_multi_files.json` | Multiple cooling-capacity CSV files combined into one plot. |
| `configs/flexible_plot_demos/pbse_tec_qc_excel_multicolumn.json` | Device voltage and power dual-line plot from one CSV. |

## Input Notes

Supported input files:

```text
.csv
.tsv
.txt
.dat
.xlsx
.xls
```

Each saved plot writes a normalized CSV by default. That file contains resolved columns as `x`, `y`, `property`, `group`, `legend_label`, `label`, `condition`, and `source`, which makes it easier to audit what the recipe actually plotted.

---
name: te-plotting
description: >-
  Generate publication-grade thermoelectric transport figures (`plot-te`) and 20+ general
  1D/2D/statistical scientific charts and JSON recipes (`sciplot`, legacy alias `flexible`)
  with universal overlays, inside-axes legend layout, color sets, and sequential figure
  renaming. Use whenever the user asks to plot TE properties (S, sigma, kappa, kappa_L, PF,
  zT), experimental/simulated CSVs, contour/phase maps, heatmaps, ternary diagrams,
  waterfall/stacked bars, parity plots, Arrhenius plots, radar charts, or multi-panel figures.
---

# Scientific & Thermoelectric Plotting Suite (`plot-te`, `sciplot`)

All plotting commands share consistent publication typography (`22 pt` axis labels, `18.5 pt` ticks, `15 pt` base legends auto-scaled inside the axes, `12 pt` markers, `1.65 pt` frame spines), smart Kelvin temperature tick snapping, keep legends **inside** the plot frame by default via `legend_layout` (automatically selecting clear inside locations, adjusting `ncol` and font size, and expanding axis headroom to avoid curve/bar collisions; never pass `--legend outside` unless requested), and support `--formats svg png pdf` (or `--pdf`), `--color-set`, `--rename "[1]"`, `--xlim`, `--ylim`, and `--no-show`.

## 1. Thermoelectric Transport Plotting (`plot-te`)

Plots $S$, $\sigma$, $\rho$, $\kappa$, $\kappa_{\mathrm{e}}$, $\kappa_{\mathrm{L}}$, $PF$, and $zT$ from batch IDs, sample selectors, processed CSV files, or folders (`--yscale {linear,log,symlog}` supported):

```bash
python main.py plot-te <BATCH_ID> --plot-mode combined --formats svg png --no-show
python main.py plot-te <BATCH_A> <BATCH_B> --properties s sigma pf kl zt --legend --no-show
python main.py plot-te data/processed/inter_batch_compare --zt --legend --color-set blue --no-show
```

## 2. General 1D / 2D / Statistical Scientific Plotting (`sciplot`)

Driven either by `--figure <KIND_OR_RECIPE>` with CLI column selectors (`-x`, `-y`, `-z`) or by a reusable JSON recipe (`--recipe configs/plot_recipes/...json`). *(Legacy CLI alias `flexible` / `flex` remains supported.)*

### Supported `--figure` Kinds
- **1D & Multi-Axis**: `line`, `scatter`, `line_scatter`, `bar`, `stacked_bar`, `waterfall` (`--waterfall-mode {delta,levels}`), `dual_axis`, `dual_line`, `multi_panel`, `broken_y` (`--y-break low_max,high_min`).
- **2D Maps & Compositional Spaces** (default colormap `soft-br`: soft blue for low values to soft coral-red for high values; reverse with `soft-rb`):
  - `heatmap` (`-x`, `-y`, `-z`, `--annotate-values`)
  - `contour` / `phase_map` (`-x`, `-y`, `-z`, `--levels 14`)
  - `ternary` (`--a-col`, `--b-col`, `--c-col`, `-z`, `--alabel`, `--blabel`, `--clabel`)
  - `bubble` (`-x`, `-y`, `-z`, `--size-col`)
- **Statistical, Regression & Diagnostics**:
  - `boxplot`, `violin`, `histogram`
  - `parity` ($y_{\mathrm{pred}}$ vs $y_{\mathrm{true}}$ with $R^2$, MAE, RMSE, and $\pm 10\%$ bands)
  - `arrhenius` ($\ln y$ vs $1000/T$ with automatic activation energy $E_{\mathrm{a}}$ extraction + top $T$ (K) axis)
  - `fit_residual` (2-row main fit + $\Delta y$ residual subpanel)
  - `radar` / `spider` (multi-metric normalized polygon comparison)

### Universal CLI Overlays (combinable with 1D/scatter kinds)
- Error bars / confidence bands: `--yerr <COL>`, `--yerr-pct <PCT>`, `--xerr <COL>`, `--error-mode {bars,band,both}`
- Reference lines & shaded regions: `--hline 1.0,"$zT=1$",#444444,--` / `--vline 673,"Transition"` / `--hspan` / `--vspan`
- Zoom inset: `--inset-xlim 550 750 --inset-ylim 1.1 1.6 --inset-bounds 0.52,0.14,0.42,0.38`
- Literature benchmark background styling & direct end-labels: `--benchmark-group "Literature"`, `--end-labels`

```bash
python main.py sciplot --figure contour data/phase_grid.csv -x Temp_K -y Doping_x -z zT --cmap soft-br --formats png svg --no-show
python main.py sciplot --figure ternary data/comp.csv --a-col Cu --b-col Ag --c-col Se -z zT --formats png svg --no-show
python main.py sciplot --figure parity data/ml_pred.csv -x zT_exp -y zT_pred --formats png svg --no-show
python main.py sciplot --recipe configs/plot_recipes/thermoelectric/temperature_vs_zt_benchmark.json --formats png svg --no-show
```

## 3. Palettes & Sequential Figure Renaming

- `--color-set`: `science` (default), `npg`, `classic`, `blue-orange`, `blue`, `teal`, `purple`, `orange`, `red`, `gray`, `legacy`.
- `--rename "[1]"`: Renames exported figures sequentially (`[1].svg`, `[2].svg`, ...) without altering underlying CSV/JSON filenames. Always quote bracketed names.

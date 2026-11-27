# Flexible Plot Recipe Index

The categorized recipes are the preferred names. Root-level recipe files are
reserved for standalone recipes that do not yet have a categorized equivalent.

## Color Sets

Recipes can set `plot.color_set` (for example `"blue"`). The automatic palette
is now `science`; use `legacy` for the original 24 colors. `--color-set` overrides
the recipe palette, while explicit series `color` / CLI `--color` values remain
higher priority. See [color galleries and examples](../../docs/COLOR_SETS.md).

## Device

- `device/current_vs_efficiency.json`: `$I$ (A)` vs `$\eta$ (%)`
- `device/current_vs_cop.json`: `$I$ (A)` vs `COP`
- `device/hot_side_temperature_vs_delta_tmax.json`: `$T_{\mathrm{H}}$ (K)` vs `$\Delta T_{\max}$ (K)`
- `device/current_vs_cooling_capacity_qc.json`: `$I$ (A)` vs `$Q_{\mathrm{c}}$ (W)`
- `device/current_vs_voltage_power_dual.json`: `$I$ (mA)` vs `Voltage (mV)` and `Power (mW)`

## SPB Fitting

- `spb/pisarenko_fit.json`: Hall-Pisarenko fitting curve plus measured `$|S|$` points
- `spb/pf_fit.json`: SPB power-factor model curve plus measured `$PF$` points
- `spb/zt_fit.json`: SPB `$zT$` model curve plus measured `$zT$` points
- `spb/carrier_concentration_vs_seebeck.json`: `$n_{\mathrm{H}}$` vs `$S$`
- `spb/carrier_concentration_vs_mobility.json`: `$n_{\mathrm{H}}$` vs `$\mu_{\mathrm{H}}$`
- `spb/carrier_concentration_vs_power_factor.json`: `$n_{\mathrm{H}}$` vs `$PF$`
- `spb/carrier_concentration_vs_zt.json`: `$n_{\mathrm{H}}$` vs `$zT$`

## Temperature Transport

- `temperature/temperature_vs_carrier_concentration.json`: `$T$` vs `$n_{\mathrm{H}}$`
- `temperature/temperature_vs_mobility.json`: `$T$` vs `$\mu_{\mathrm{H}}$`
- `temperature/temperature_vs_cp_over_t.json`: `$T$` vs `$C_p/T$`

## STA / Thermal Analysis

- `sta/temperature_vs_dta.json`: NETZSCH STA export temperature vs mass-normalized DTA. It locates the `##` header automatically and reads ANSI/Latin-1 degree and micro symbols.

For example, compare the second-heating curves from two samples:

```bash
python main.py sciplot \
  data/raw/TE-1070/STA/ExpDat_te-1070-a-3.csv \
  data/raw/TE-1070/STA/ExpDat_te-1070-d-3.csv \
  --recipe configs/plot_recipes/sta/temperature_vs_dta.json \
  --label TE-1070-A \
  --label TE-1070-D \
  --no-show
```

## Thermoelectric Properties

- `thermoelectric/temperature_vs_te_summary.json`: `$T$` vs standard 2x3 TE summary properties
- `thermoelectric/temperature_vs_<property>.json`: `$T$` vs one processed TE property using `python main.py plot-te` labels

## Lattice

- `lattice/composition_vs_lattice_parameter.json`: composition/content vs lattice parameter

## Bar & Waterfall Charts

- `bar/simple_bar.json`: categorical x vs one value column
- `bar/grouped_bar.json`: categorical x vs two or more side-by-side value columns
- `bar/stacked_bar.json`: vertical stacked bar chart with optional stack totals
- `bar/percent_stacked_bar.json`: 100%-normalized stacked contribution bar chart
- `bar/waterfall_steps.json`: step-by-step cumulative enhancement/reduction waterfall chart
- `thermoelectric/thermal_conductivity_breakdown_stacked.json`: stacked $\kappa_{\mathrm{L}} + \kappa_{\mathrm{e}}$ breakdown across compositions

## 2D Maps, Screening & Ternary

- `map/heatmap_xyz.json`: 2D categorical or numeric grid heatmap with cell values and colorbar
- `map/contour_phase_map.json`: 2D filled contour map (regular grid or scattered $(x, y, z)$ triangulation)
- `map/bubble_screening.json`: 4D screening scatter ($x$, $y$, colorbar $z$, bubble size)
- `map/ternary_composition.json`: equilateral ternary $(A, B, C)$ phase/property diagram

## Statistical & Parity

- `stats/boxplot_distribution.json`: boxplot + jittered individual points + mean marker
- `stats/violin_distribution.json`: KDE violin distribution + median/extrema + raw points
- `stats/grain_size_histogram.json`: 1D size histogram with lognormal/normal/KDE curve fit
- `stats/parity_pred_vs_exp.json`: predicted vs experimental 1:1 parity plot with $\pm\%$ cone and $R^2$/MAE/RMSE

## Benchmarks, Arrhenius & Special Layouts

- `thermoelectric/temperature_vs_zt_benchmark.json`: muted hollow-marker literature curves vs highlighted "This work" curve
- `thermoelectric/temperature_vs_zt_errorband.json`: $zT(T)$ with shaded uncertainty band (`--yerr` or `--yerr-pct`)
- `thermoelectric/temperature_vs_kappa_lattice_kmin.json`: $\kappa_{\mathrm{L}}(T)$ with horizontal $\kappa_{\min}$ reference guide
- `temperature/arrhenius_conductivity.json`: $1000/T$ vs $\sigma$ Arrhenius plot with top $T$ (K) axis and $E_{\mathrm{a}}$ linear fit
- `special/broken_axis_line.json`: split upper/lower y-axis plot with spine `//` break marks
- `special/fit_with_residual.json`: observed + calculated + peak components with bottom difference panel
- `special/radar_multi_metric.json`: multi-metric polar radar/spider chart
- `special/line_with_inset.json`: curve plot with magnified zoom-in inset box and connectors

## Dual Axis

- `dual_axis/composition_vs_carrier_mobility_dual.json`: composition/content vs `$n_{\mathrm{H}}$` and `$\mu_{\mathrm{H}}$`
- `dual_axis/temperature_vs_carrier_mobility_dual.json`: `$T$` vs `$n_{\mathrm{H}}$` and `$\mu_{\mathrm{H}}$`

## Example

```bash
python main.py sciplot data.csv \
  --recipe configs/plot_recipes/device/current_vs_cooling_capacity_qc.json \
  --x I_A \
  --y Qc_W
```

CLI options such as `--xlabel`, `--ylabel`, `--yscale`, `--ylim`,
`--right-ylabel`, and `--right-ylim` can override recipe defaults. Style
overrides are also available:

```bash
--xlim 300 800
--ylim 0 auto
--x-major 100 --x-minor 50
--y-major 1 --y-minor 0.5
--color '#d62728' --color '#1f77b4'
--marker o --marker s
--line-width 1.4
--marker-size 5
--subplot-aspect 10:8
--copy-to-data-dir
```

`--aspect` is a shorter alias for `--subplot-aspect`, including when overriding
a saved recipe.

For dual-axis recipes, use `--right-ylim`, `--right-yscale`,
`--right-y-major`, `--right-y-minor`, and `--right-y-tick-format` for the
right axis.

For bar recipes, use `plot.x_order` in JSON to set the category order. In
direct CLI mode, repeat `--y` and `--label` to make grouped bars.

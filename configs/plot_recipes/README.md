# Flexible Plot Recipe Index

The categorized recipes are the preferred names. Short recipe files in
`configs/plot_recipes/*.json` are kept as legacy aliases.

## Device

- `device/current_vs_efficiency.json`: `$I$ (A)` vs `$\eta$ (%)`
- `device/current_vs_cop.json`: `$I$ (A)` vs `COP`
- `device/hot_side_temperature_vs_delta_tmax.json`: `$T_{\mathrm{H}}$ (K)` vs `$\Delta T_{\max}$ (K)`
- `device/current_vs_cooling_capacity_qc.json`: `$I$ (A)` vs `$Q_{\mathrm{c}}$ (W)`
- `device/current_vs_voltage_power_dual.json`: `$I$ (A)` vs `Voltage (mV)` and `Power (mW)`

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

## Thermoelectric Properties

- `thermoeletric/temperature_vs_te_summary.json`: `$T$` vs standard 2x3 TE summary properties
- `thermoeletric/temperature_vs_<property>.json`: `$T$` vs one processed TE property using `plot_te.py` labels

## Lattice

- `lattice/composition_vs_lattice_parameter.json`: composition/content vs lattice parameter

## Bar Charts

- `bar/simple_bar.json`: categorical x vs one value column
- `bar/grouped_bar.json`: categorical x vs two or more side-by-side value columns

## Dual Axis

- `dual_axis/composition_vs_carrier_mobility_dual.json`: composition/content vs `$n_{\mathrm{H}}$` and `$\mu_{\mathrm{H}}$`
- `dual_axis/temperature_vs_carrier_mobility_dual.json`: `$T$` vs `$n_{\mathrm{H}}$` and `$\mu_{\mathrm{H}}$`

## Example

```bash
python flexible_plot.py data.csv \
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

For dual-axis recipes, use `--right-ylim`, `--right-yscale`,
`--right-y-major`, `--right-y-minor`, and `--right-y-tick-format` for the
right axis.

For bar recipes, use `plot.x_order` in JSON to set the category order. In
direct CLI mode, repeat `--y` and `--label` to make grouped bars.

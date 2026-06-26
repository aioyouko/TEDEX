# TE Property Recipes

Recipes in this folder target processed TE CSV files, such as
`data/processed/*-processed/*.csv`. The labels, columns, and scale factors
mirror `TE_PLOT_SPECS` in `src/tools/plot.py`.

The folder keeps the existing spelling `thermoeletric` from the requested path.
By default, each recipe saves the figure plus normalized CSV in a `figures`
folder beside the input data file.

## Usage

```bash
python src/tools/flexible_plot.py \
  --recipe configs/plot_recipes/thermoeletric/temperature_vs_te_summary.json \
  data/processed/CHY-1033-processed/CHY-1033-A.csv \
  --no-show
```

For a single property comparison across multiple samples:

```bash
python src/tools/flexible_plot.py \
  --recipe configs/plot_recipes/thermoeletric/temperature_vs_seebeck.json \
  data/processed/CHY-1033-processed/CHY-1033-A.csv \
  data/processed/CHY-1033-processed/CHY-1033-B.csv \
  --legend inside \
  --no-show
```

## Expected Processed Units

- `Temperature`: K
- `Resistivity`: Ohm m, scaled to mOhm cm
- `Seebeck`: V K^-1, scaled to uV K^-1
- `Conductivity`: S m^-1, scaled to S cm^-1
- `Power_Factor`: W m^-1 K^-2, scaled to uW cm^-1 K^-2
- `Thermal_Conductivity`, `Carrier_Thermal_Conductivity`,
  `Lattice_Thermal_Conductivity`: W m^-1 K^-1
- `Lorenz_Number_1e-8_WOhmK-2`: 10^-8 W Ohm K^-2

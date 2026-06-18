# Data Layout

## Required Folders

```text
data/raw/
data/lab/
data/processed/
results/
```

`data/lab/batches.json` and `data/lab/samples.json` are the machine-readable ledgers. `data/lab/lab_metadata.md` is the human-editable version.

## Raw Data Naming

Place raw files inside a batch folder:

```text
data/raw/CHY-1051/CHY-1051-A_ZEM.txt
data/raw/CHY-1051/CHY-1051-A_LFA.csv
```

The metadata sync script recognizes:

```text
<sample_id>_ZEM.txt
<sample_id>_LFA.csv
<sample_id>_LFA.txt
```

## Metadata Fields

Minimum sample fields for raw analysis:

- `sample_id`
- `batch_id`
- `zem`
- `lfa`
- `density`
- `cp_value`

Recommended fields for plotting and comparison:

- `sample_name`
- `sample_composition`
- `matrix_composition`
- `pristine_composition`
- `optimization_type`
- `modifier_element`
- `modifier_amount`
- `modifier_unit`
- `modifier_site`
- `notes`

## Processed CSV Columns

The plotting scripts expect:

- `Temperature`: K
- `Seebeck`: V/K
- `Conductivity`: S/m
- `Power_Factor`: W m^-1 K^-2
- `Thermal_Conductivity`: W m^-1 K^-1
- `ZT`: dimensionless

Optional SPB-derived columns:

- `Generalized_Fermi_Level`
- `Lorenz_Number`
- `Lorenz_Number_1e-8_WOhmK-2`
- `Carrier_Thermal_Conductivity`
- `Lattice_Thermal_Conductivity`
- `Weighted_Mobility_cm2_V-1_s-1`
- `Quality_Factor_B`

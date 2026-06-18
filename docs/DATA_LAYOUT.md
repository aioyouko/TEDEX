# Data Layout

## Required Folders

```text
data/raw/
data/lab/
data/pdf_card/plot_standards/
data/processed/
results/
```

`data/lab/batches.json` and `data/lab/samples.json` are the machine-readable ledgers. `data/lab/lab_metadata.md` is the human-editable version.

## Raw Data Naming

Place raw files inside a batch folder:

```text
data/raw/CHY-1051/CHY-1051-A_ZEM.txt
data/raw/CHY-1051/CHY-1051-A_LFA.csv
data/raw/CHY-1051/XRD/CHY-1051-A_XRD.xy
```

The metadata sync script recognizes:

```text
<sample_id>_ZEM.txt
<sample_id>_LFA.csv
<sample_id>_LFA.txt
XRD/<sample_id>_XRD.xy
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

## XRD Files

XRD pattern files are expected under:

```text
data/raw/<batch_id>/XRD/*.xy
```

The XRD reader accepts simple two-column text:

```text
2theta intensity
10.0 123
10.02 125
```

Header lines are ignored. If a header line contains `Wavelength = 1.5406`, that value is captured for metadata, but plotting does not require it.

## PDF-Card Standards For XRD Plotting

Place clean plotting standards under:

```text
data/pdf_card/plot_standards/
```

Recommended CSV columns:

```csv
label,two_theta_deg,intensity,d_angstrom,h,k,l
Demo cubic standard,28.4,100,3.14,1,1,1
```

Only `two_theta_deg` and `intensity` are required by the plotter.

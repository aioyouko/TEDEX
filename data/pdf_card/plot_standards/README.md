# Plotting PDF Standard Format

Use this folder for PDF-card peak data that are already cleaned for XRD plotting.
This avoids depending on JADE `.txt` exports, which can have inconsistent header
and table formatting.

Recommended file type: `.csv`

Required columns:

```csv
two_theta_deg,intensity
24.875,100
41.168,48.9
```

Optional columns:

```csv
label,d_angstrom,h,k,l
```

Column-name aliases are accepted:

- `two_theta`, `2theta`, `2-theta`, `2theta_deg`
- `relative_intensity`, `rel_intensity`, `i`, `height`

Best practice:

- Use relative intensity on a 0-100 scale.
- Keep only one header row. Do not add JADE text headers above the CSV table.
- Name files clearly, for example `CuInTe2_PDF_97_023_8958.csv`.

Example commands:

```bash
python main.py plot-xrd TE-1038 --pdf-card CuInTe2_PDF_97_023_8958
python main.py plot-xrd TE-1038 --pdf-card data/pdf_card/plot_standards/CuInTe2_PDF_97_023_8958.csv
python main.py plot-xrd TE-1038 --pdf-card CuInTe2_PDF_97_023_8958 --pdf-card Sb2Te3_PDF_97_067_0037
```

With two `--pdf-card` options, the first card is drawn below the measured XRD
traces and the second above them. The first starts at the x-axis; the second
uses a black baseline. The cards use red and blue defaults controlled by
`--standard-color` and `--top-standard-color`. Card names are hidden by default;
add `--pdf-labels` to write them directly in the plot. Maximum stick height
defaults to `1.0` of one XRD offset step. The default bottom-card gap is `0.25`
of one offset step; an enabled bottom label retains `0.60` clearance. Use
`--pdf-height-fraction` only for an explicit height override.

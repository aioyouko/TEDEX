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
python main.py plot-xrd CHY-1038 --pdf-card CuInTe2_PDF_97_023_8958
python main.py plot-xrd CHY-1038 --pdf-card data/pdf_card/plot_standards/CuInTe2_PDF_97_023_8958.csv
```

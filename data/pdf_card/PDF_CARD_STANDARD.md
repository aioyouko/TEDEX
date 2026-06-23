# PDF Card Standard

Recommended storage:

- `*_standard.json`: canonical reference-card record for programs.
- `*_peaks.csv`: flat peak table for checking in Excel, Origin, or pandas.
- original `.txt`: keep as the raw source.

The JSON schema is `xrd_pdf_card/v1`. It stores:

- `pdf_index`
- `phase.name` and `phase.formula`
- `radiation.type` and `radiation.wavelength_angstrom`
- `crystal.crystal_system`
- `crystal.space_group`
- `crystal.space_group_number`
- `crystal.cell.a_angstrom`, `b_angstrom`, `c_angstrom`
- `crystal.cell.alpha_deg`, `beta_deg`, `gamma_deg`
- `crystal.density_calculated_g_cm3`
- `crystal.density_measured_g_cm3`
- `crystal.volume_angstrom3`
- `peaks[]` with `two_theta_deg`, `d_angstrom`, `intensity`, and `h k l`

For fitting your own XRD data, use the JSON as the reference phase and match
measured peaks to the indexed `h k l` rows. The fitted output schema is
`xrd_lattice_fit/v1` and records the detected peaks, matched reference peaks,
fitting model, residuals, and final lattice parameters.

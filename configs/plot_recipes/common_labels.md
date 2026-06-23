# Common Plot Label Snippets

Use single quotes in zsh/bash for labels that contain `$...$`.
Do not use Python raw-string syntax such as `r"..."` on the command line.

For JSON recipes, escape backslashes as `\\`.

## Temperature Labels

CLI:

```bash
--xlabel '$T$ (K)'
--xlabel '$T_{\mathrm{H}}$ (K)'
--xlabel '$T_{\mathrm{C}}$ (K)'
--xlabel '$\Delta T$ (K)'
--ylabel '$T$ (K)'
--ylabel '$\Delta T$ (K)'
--ylabel '$\Delta T_{\max}$ (K)'
```

JSON:

```json
"xlabel": "$T$ (K)"
"xlabel": "$T_{\\mathrm{H}}$ (K)"
"xlabel": "$T_{\\mathrm{C}}$ (K)"
"xlabel": "$\\Delta T$ (K)"
"ylabel": "$T$ (K)"
"ylabel": "$\\Delta T$ (K)"
"ylabel": "$\\Delta T_{\\max}$ (K)"
```

## TE Transport Labels

CLI:

```bash
--ylabel '$S$ ($\mu$V K$^{-1}$)'
--ylabel '$\sigma$ (S cm$^{-1}$)'
--ylabel '$PF$ ($\mu$W cm$^{-1}$ K$^{-2}$)'
--ylabel '$zT$'
```

JSON:

```json
"ylabel": "$S$ ($\\mu$V K$^{-1}$)"
"ylabel": "$\\sigma$ (S cm$^{-1}$)"
"ylabel": "$PF$ ($\\mu$W cm$^{-1}$ K$^{-2}$)"
"ylabel": "$zT$"
```

## Thermal Conductivity Labels

CLI:

```bash
--ylabel '$\kappa_{\mathrm{tot}}$ (W m$^{-1}$ K$^{-1}$)'
--ylabel '$\kappa_{\mathrm{L}}$ (W m$^{-1}$ K$^{-1}$)'
--ylabel '$\kappa_{\mathrm{e}}$ (W m$^{-1}$ K$^{-1}$)'
--ylabel '$D$ (mm$^2$ s$^{-1}$)'
```

JSON:

```json
"ylabel": "$\\kappa_{\\mathrm{tot}}$ (W m$^{-1}$ K$^{-1}$)"
"ylabel": "$\\kappa_{\\mathrm{L}}$ (W m$^{-1}$ K$^{-1}$)"
"ylabel": "$\\kappa_{\\mathrm{e}}$ (W m$^{-1}$ K$^{-1}$)"
"ylabel": "$D$ (mm$^2$ s$^{-1}$)"
```

## Carrier Labels

CLI:

```bash
--ylabel '$n_{\mathrm{H}}$ (cm$^{-3}$)'
--ylabel '$n_{\mathrm{H}}$ ($10^{19}$ cm$^{-3}$)'
--ylabel '$p_{\mathrm{H}}$ (cm$^{-3}$)'
--ylabel '$\mu_{\mathrm{H}}$ (cm$^2$ V$^{-1}$ s$^{-1}$)'
--right-ylabel '$\mu_{\mathrm{H}}$ (cm$^2$ V$^{-1}$ s$^{-1}$)'
--ylabel '$R_{\mathrm{H}}$ (cm$^3$ C$^{-1}$)'
```

JSON:

```json
"ylabel": "$n_{\\mathrm{H}}$ (cm$^{-3}$)"
"ylabel": "$n_{\\mathrm{H}}$ ($10^{19}$ cm$^{-3}$)"
"ylabel": "$p_{\\mathrm{H}}$ (cm$^{-3}$)"
"ylabel": "$\\mu_{\\mathrm{H}}$ (cm$^2$ V$^{-1}$ s$^{-1}$)"
"right_ylabel": "$\\mu_{\\mathrm{H}}$ (cm$^2$ V$^{-1}$ s$^{-1}$)"
"ylabel": "$R_{\\mathrm{H}}$ (cm$^3$ C$^{-1}$)"
```

## Composition And Structure Labels

CLI:

```bash
--xlabel 'Content'
--xlabel 'Composition'
--xlabel '$x$'
--xlabel '$x$ ($10^{-3}$)'
--xlabel '2$\theta$ (degree)'
--ylabel 'Intensity (a.u.)'
--ylabel 'Lattice Parameter ($\AA$)'
--ylabel 'Lattice Constant ($\AA$)'
--ylabel '$a$ ($\AA$)'
--ylabel '$c$ ($\AA$)'
```

JSON:

```json
"xlabel": "Content"
"xlabel": "Composition"
"xlabel": "$x$"
"xlabel": "$x$ ($10^{-3}$)"
"xlabel": "2$\\theta$ (degree)"
"ylabel": "Intensity (a.u.)"
"ylabel": "Lattice Parameter ($\\AA$)"
"ylabel": "Lattice Constant ($\\AA$)"
"ylabel": "$a$ ($\\AA$)"
"ylabel": "$c$ ($\\AA$)"
```

## Device Labels

CLI:

```bash
--xlabel '$I$ (A)'
--ylabel 'Voltage (mV)'
--right-ylabel 'Power (mW)'
--ylabel '$Q_{\mathrm{c}}$ (W)'
--ylabel 'COP'
--ylabel '$\eta$ (%)'
--label '$\Delta T=0$ K' --label '$\Delta T=5$ K' --label '$\Delta T=10$ K'
--label 'Voltage' --label 'Power'
```

JSON:

```json
"xlabel": "$I$ (A)"
"ylabel": "Voltage (mV)"
"right_ylabel": "Power (mW)"
"ylabel": "$Q_{\\mathrm{c}}$ (W)"
"ylabel": "COP"
"ylabel": "$\\eta$ (%)"
"legend_label": "$\\Delta T=0$ K"
"legend_label": "$\\Delta T=5$ K"
"legend_label": "$\\Delta T=10$ K"
"legend_label": "Voltage"
"legend_label": "Power"
```

## Energy And Spectroscopy Labels

CLI:

```bash
--xlabel 'Energy (eV)'
--xlabel '$E-E_{\mathrm{F}}$ (eV)'
--ylabel '$\alpha/S$ (a.u.)'
--ylabel 'DOS (states eV$^{-1}$)'
--ylabel 'Absorbance (a.u.)'
```

JSON:

```json
"xlabel": "Energy (eV)"
"xlabel": "$E-E_{\\mathrm{F}}$ (eV)"
"ylabel": "$\\alpha/S$ (a.u.)"
"ylabel": "DOS (states eV$^{-1}$)"
"ylabel": "Absorbance (a.u.)"
```

## Generic Legend Labels

CLI:

```bash
--label 'Sample 1' --label 'Sample 2' --label 'Sample 3'
--label 'Reference' --label 'This work'
--label '$n_{\mathrm{H}}$' --label '$\mu_{\mathrm{H}}$'
--label '$S$' --label '$\sigma$' --label '$PF$'
```

JSON:

```json
"legend_label": "Sample 1"
"legend_label": "Sample 2"
"legend_label": "Sample 3"
"legend_label": "Reference"
"legend_label": "This work"
"legend_label": "$n_{\\mathrm{H}}$"
"legend_label": "$\\mu_{\\mathrm{H}}$"
"legend_label": "$S$"
"legend_label": "$\\sigma$"
"legend_label": "$PF$"
```

## Style Helpers

```bash
--legend inside --legend-loc 'best'
--legend inside --legend-loc 'upper right'
--legend none
```

```bash
--xscale log
--yscale log
--right-yscale log
--x-tick-format plain
--y-tick-format plain
--right-y-tick-format plain
--x-major 100
--x-minor 50
--y-major 1
--y-minor 0.5
--right-y-major 10
--right-y-minor 5
--ylim 1e18 1e21
--right-ylim 1 100
--copy-to-data-dir
```

```bash
--color '#d62728' --color '#1f77b4' --color '#2ca02c'
--marker o --marker s --marker D
```

## Complete Copy Examples

Carrier concentration and mobility:

```bash
python main.py flexible data/demo/concentration_mobility_double_axis.csv \
  --kind dual_line \
  --x x \
  --xlabel '$x$ ($10^{-3}$)' \
  --y 'concentration (18)' \
  --y mobility \
  --ylabel '$n_{\mathrm{H}}$ ($10^{19}$ cm$^{-3}$)' \
  --right-ylabel '$\mu_{\mathrm{H}}$ (cm$^2$ V$^{-1}$ s$^{-1}$)' \
  --yscale log \
  --y-tick-format plain
```

Three-group scatter:

```bash
python main.py flexible data/demo/flexible_sactter.csv \
  --kind scatter \
  --x x1 --y y1 \
  --x x2 --y y2 \
  --x x3 --y y3 \
  --xlabel 'Content' \
  --ylabel 'Lattice Parameter ($\AA$)' \
  --label 'Sample 1' --label 'Sample 2' --label 'Sample 3'
```

Device voltage and power:

```bash
python main.py flexible data.csv \
  --kind dual_line \
  --x I_A \
  --xlabel '$I$ (A)' \
  --y Voltage_mV \
  --y Power_mW \
  --ylabel 'Voltage (mV)' \
  --right-ylabel 'Power (mW)'
```

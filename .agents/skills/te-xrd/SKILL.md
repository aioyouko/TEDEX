---
name: te-xrd
description: >-
  Plot and analyze X-ray diffraction (XRD) data via `plot-xrd` and `xrd-lattice`: stacked
  and separate diffraction patterns, PDF reference stick cards, peak-shift zoom panels
  (`--zoom`), variable-temperature 2D heatmaps (`--vt-map`) and waterfall stacks
  (`--vt-stack`), Rietveld/Le Bail profile plots (`--rietveld`), pseudo-Voigt peak
  deconvolution (`--peak-fit`), Williamson-Hall size/strain regression (`--wh`), and
  unit-cell lattice parameter refinement (`xrd-lattice`). Use whenever working with XRD
  files (.xy, .txt, .dat, .csv, .asc, .ras), PDF standard cards, phase transitions, peak
  shifts, Rietveld profiles, or lattice constants.
---

# XRD Pattern Plotting, Profile Analysis & Lattice Refinement (`plot-xrd`, `xrd-lattice`)

Reads `.xy`, `.txt`, `.dat`, `.csv`, `.asc`, and `.ras` diffraction files, respects `xrd_cards_dir` and `wavelength_angstrom` from `configs/workspace.json`, and keeps legends inside the plot axes by default (`--no-show` recommended for headless runs).

## 1. Standard & Advanced XRD Plotting (`plot-xrd`)

### Pattern Selection & PDF Reference Cards
- Inspect folder order & bound `legend.txt` labels without plotting: `--list-files`
- Select subset by 1-based position: `--pick 124` (for positions $1\text{–}9$) or `--indices 2 10` (for $\ge 10$ files), or filter by name via `--select <SUBSTR>`
- Reference stick cards: `--list-pdf-cards`, `--pdf-card <CARD_NAME>`, `--top-pdf-card <CARD_NAME>`, repeated `--pdf-card <CARD1> --pdf-card <CARD2>`, or `--no-pdf-card`

### Layout Modes (`--layout` or Shortcut Flags)
- `stack` *(default)* / `separate`: Multi-sample stacked offset or individual panels (`--raw`, `--normalized`, `--both`).
- `--zoom <LOW> <HIGH>` (`--layout zoom`): Full-range stacked XRD paired with a synchronized zoomed peak-shift subpanel.
- `--vt-map` (`--layout vt-map`): 2D variable-temperature $(2\theta, T)$ intensity heatmap (`--transition-temp <K>`, `--temperatures <T1 T2 ...>`, default `soft-br` colormap).
- `--vt-stack` (`--layout vt-stack`): Temperature-ordered waterfall XRD colored along the soft blue-to-red thermal gradient (`--guide-2theta <DEG...>`).
- `--rietveld` (`--layout rietveld`): Publication Rietveld / Le Bail refinement plot ($Y_{\mathrm{obs}}$, $Y_{\mathrm{calc}}$, $Y_{\mathrm{obs}} - Y_{\mathrm{calc}}$ residual, Bragg ticks, optional `--formula`, `--cell-text`, `--zoom <LOW> <HIGH>`).
- `--peak-fit` (`--layout peak-fit`): Multi-peak pseudo-Voigt deconvolution within `--xlim <LOW> <HIGH>` resolving overlapping doublets + residual panel and exported peak table.
- `--wh` / `--williamson-hall`: Automatic peak extraction and $\beta\cos\theta$ vs $4\sin\theta$ linear regression yielding crystallite size $D$ (nm) and microstrain $\varepsilon$ (`--instr-fwhm <DEG>`).

```bash
python main.py plot-xrd <BATCH_OR_FOLDER> --no-show
python main.py plot-xrd <BATCH_OR_FOLDER> --pick 124 --zoom 26.6 28.4 --pdf-card CuInTe2_PDF_97_023_8958 --formats png svg --no-show
python main.py plot-xrd path/to/VT_XRD --vt-map --transition-temp 635 --formats png svg --no-show
python main.py plot-xrd path/to/VT_XRD --vt-stack --guide-2theta 27.55 45.40 --no-show
python main.py plot-xrd path/to/rietveld_profile.csv --rietveld --zoom 44.0 47.5 --formats png svg --no-show
python main.py plot-xrd path/to/sample.xy --peak-fit --xlim 44.2 46.8 --no-show
python main.py plot-xrd path/to/sample.xy --wh --pdf-card CuInTe2_PDF_97_023_8958 --instr-fwhm 0.05 --no-show
```

## 2. Unit-Cell Lattice Parameter Refinement (`xrd-lattice`)

Refines crystal-system-constrained unit-cell parameters $(a, b, c, \alpha, \beta, \gamma)$ and cell volume $V$ by matching experimental XRD peak positions ($2\theta$) against $hkl$ reflections from a reference PDF card:

```bash
python main.py xrd-lattice \
  --xrd path/to/sample.xy \
  --pdf-card "data/pdf_card/CuInTe2 PDF#97-023-8958.txt" \
  --output-dir outputs/models/xrd_lattice
```

Exports matched reflection tables (`*_matched_peaks.csv`) and refined lattice constants with RMS $2\theta$ residuals (`*_lattice_fit.json`).

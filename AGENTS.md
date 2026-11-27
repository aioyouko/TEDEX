# Thermoelectric Analysis Workspace — Agent Harness Instructions

This repository (`te-analysis-workspace` / TEDEX `1.5.1`) is an integrated CLI and Python harness for thermoelectric (TE) raw data processing, publication-grade scientific plotting, XRD structural analysis, and electronic/phonon physics modeling.

## 1. Core Harness Routing Rules

- **Use `python main.py` First**: Always execute built-in workspace tools via `python main.py <command> ... --no-show` (or `te <command> ...` when editable-installed) rather than writing ad-hoc `matplotlib` or `scipy` scripts from scratch. This guarantees house typography, color conventions (soft steel-blue experimental markers `#79ADD8` / `#264B73` + crimson-red best-fit curves `#E64B35`, `soft-br` blue-to-red 2D maps), structured CSV/JSON exports, dual-unit Markdown reports, and SVD Jacobian collinearity diagnostics.
- **Headless Execution**: Always pass `--no-show` when running plotting or fitting commands from an agent terminal so GUI windows do not block execution.
- **Inside-Axes Legend Convention**: Always keep legends **inside** the plot axes (`--legend` / `--legend inside`, which is the default across `plot-te`, `plot-xrd`, `sciplot`, `spb`, and physics models) rather than placing legends outside the frame. The built-in `legend_layout` engine automatically selects clear inside locations, adjusts `ncol` and font size, and expands axis headroom (`ylim` / `xlim`) to prevent data collisions; you can also tune `--ylim`, `--xlim`, `--legend-font-size`, or `--legend-columns` when needed. Never pass `--legend outside` or `--legend-outside` unless explicitly requested by the user.
- **Missing-Parameter Prompting (Exit Code `2`)**: Commands such as `callaway` and `debye-calc` exit with status code `2` and print a structured parameter checklist when required physical constants (such as Debye temperature $\Theta_{\mathrm{D}}$ and sound velocity $v_{\mathrm{s}}$) are omitted in non-interactive shells. **Never guess or fabricate unprovided material constants**—ask the user which parameter set they can provide:
  1. Direct Debye temperature `--theta-d <K>` and average sound velocity `--vs <m/s>`,
  2. Ultrasonic longitudinal/transverse velocities `--vl <m/s> --vt <m/s>` plus `--atomic-volume-a3` (or `--density-g-cm3`, `--molar-mass`, `--atoms-per-fu`), or
  3. Low-temperature heat capacity `--cp-csv <path>` (or `--cp-beta <mJ/molK^4>`) plus `--atoms-per-fu` and volume/density.
- **Collinearity Handling**: After running `callaway`, `skb`, or `two-band`, inspect the terminal warnings or `*_summary.json` (`identifiability_warnings` and `parameter_uncertainties`). When two parameters show $|r| \ge 0.90$, suggest fixing one from independent characterization (SEM grain size, optical $E_{\mathrm{g}}$, low-$T$ $C_p$, or DFT $m^*$) via `--fit` or `--fix-*` flags.

## 2. Command Quick Reference

| Domain | Command | Typical Use |
| --- | --- | --- |
| Workspace init / status | `python main.py init [--check\|--status\|--yes ...]` | Initialize `configs/workspace.json`, inspect resolved paths, or scaffold a clean Mode-B user folder |
| Raw ZEM/LFA pipeline | `python main.py analyze <BATCH_ID>` | Process raw ZEM + LFA data into `paths.processed` and extract features |
| TE property plots | `python main.py plot-te <SELECTOR> --no-show` | Plot $S$, $\sigma$, $\kappa$, $\kappa_{\mathrm{L}}$, $PF$, $zT$ across batches, samples, or CSVs |
| General scientific plots | `python main.py sciplot --figure <KIND_OR_RECIPE> <DATA> --no-show` | 20+ plot kinds (`heatmap`, `contour`, `ternary`, `bubble`, `waterfall`, `stacked_bar`, `parity`, `arrhenius`, `broken_y`, `fit_residual`, `radar`, etc.) + overlays (`flexible` alias kept) |
| XRD & refinement plots | `python main.py plot-xrd <SELECTOR> --no-show` | Stack, separate, `zoom`, `vt-map`, `vt-stack`, `rietveld`, `peak-fit`, `williamson-hall` |
| XRD lattice refinement | `python main.py xrd-lattice ...` | Fit unit-cell lattice parameters $(a, b, c, \alpha, \beta, \gamma)$ from indexed XRD peaks |
| SPB transport fitting | `python main.py spb <effective-mass\|conductivity\|performance> <CSV>` | Parabolic single-band Pisarenko, mobility, $PF$, and $zT$ modeling |
| Debye–Callaway $\kappa_{\mathrm{L}}$ | `python main.py callaway <CSV> --theta-d <K> --vs <m/s> --no-show` | Multi-source phonon scattering (`U`, `B`, `PD`, `EP`, `D`, `NP`, `RES`), spectral $\kappa_{\mathrm{s}}$, MFP, and Markdown report |
| Debye $\Theta_{\mathrm{D}}$ calculator | `python main.py debye-calc ...` | Compute $\Theta_{\mathrm{D}}$, $v_{\mathrm{s}}$, elastic moduli, and $\gamma_{\mathrm{G}}$ from $(v_l, v_t)$ or low-$T$ $C_p(T)$ |
| Debye–Einstein $C_p(T)$ | `python main.py debye-einstein <CSV> --atoms-per-fu <N> --no-show` | Low-$T$ heat capacity $C_p/T^3$ boson-peak & rattler mode fitting |
| Single Kane Band (SKB) | `python main.py skb <CSV> --eg <eV> --no-show` | Non-parabolic narrow-gap Pisarenko, $\mu_{\mathrm{H}}$, Lorenz number, and deformation potential $\Xi$ |
| Two-Band transport | `python main.py two-band <CSV> --mode <convergence\|bipolar> --no-show` | Isothermal light+heavy band convergence, semimetal Hall inversion, or variable-$T$ bipolar $\kappa_{\mathrm{bi}}$ |
| Metadata ledger sync | `python main.py sync <metadata\|markdown\|notion-payload\|reference-xlsx>` | Synchronize `lab_metadata.md` with `batches.json` and `samples.json` |
| Batch assessment / ML | `python main.py assess ...` / `python main.py bayes ...` | Batch optimization summaries and Bayesian TE property prediction |

Detailed runbooks are organized as 5 orthogonal workspace skills under `.agents/skills/` (and mirrored in the standalone Mode-B plugin under `plugin/tedex/skills/`):
- `.agents/skills/te-workspace/SKILL.md` — First-run workspace initialization (`configs/workspace.json`), custom directory mapping, subfolder grouping (`by_batch`, `by_system_batch`, `by_project`), and instrument/unit conventions (`te_analysis/paths.py`).
- `.agents/skills/te-data-pipeline/SKILL.md` — Raw ZEM/LFA batch processing (`analyze`), metadata ledger synchronization (`sync`), batch assessment (`assess`), and Bayesian prediction (`bayes`).
- `.agents/skills/te-plotting/SKILL.md` — Thermoelectric property plots (`plot-te`), 20+ general 1D/2D/statistical scientific charts and JSON recipes (`sciplot`), overlays, colormaps, and `--rename`.
- `.agents/skills/te-xrd/SKILL.md` — Standard & advanced XRD pattern plotting (`plot-xrd`: stack, zoom, VT phase maps, Rietveld, peak-fit, Williamson–Hall), PDF reference cards, and unit-cell lattice refinement (`xrd-lattice`).
- `.agents/skills/te-physics-models/SKILL.md` — Phonon & electronic band transport models (`debye-calc`, `callaway`, `debye-einstein`, `spb`, `skb`, `two-band`).

## 3. Sample Performance & Metadata Verification Rules

- Before comparing sample transport performance across a batch or doping series, query the workspace's configured metadata ledger (`lab_metadata.md` and `samples.json` under `paths.metadata` in `configs/workspace.json`) for each sample's `density`, `cp_value`, synthesis/annealing conditions, and notes. Treat sample density as a primary indicator of pressing densification and batch-to-batch variation.
- When comparing samples with the same nominal composition, cross-check their densities alongside transport properties and account for densification differences when discussing electrical conductivity ($\sigma$) and thermal conductivity ($\kappa$). Compute relative density (%) only when a reliable theoretical crystal density is established; when only measured density is available, perform relative comparisons among identical nominal compositions without quoting a relative density percentage.
- When composition or processing fields in `lab_metadata.md` are blank, cross-verify against raw measurement files (`paths.raw`) and user-confirmed information; never treat blank fields or legacy labels as confirmed experimental conditions.

# Changelog

## Unreleased

## 1.5.1 - 2026-11-27

- **`sciplot` Dual-Axis Right Y-Axis Fixes**:
  - Always apply `apply_axis_options()` to the right axis (`ax_right`) in `plot_dual_line` and `plot_dual_axis` so linear right axes automatically receive tick-aligned `compute_smart_linear_ylim()` bounds even when explicit `right_*` options are omitted.
  - Inherit `y_tick_format` and `y_log_ticks` onto `ax_right` in `right_y_axis_options()` when `right_y_tick_format` / `right_y_log_ticks` are not separately specified.
  - Refined `log_plain_formatter()` power-of-ten rounding and single-decade plain tick spacing (`1, 2, 5, 10`) to prevent tick label crowding at publication font sizes, with regression tests in `tests/test_inside_legend_layout.py`.
- **Showcase Gallery Updates (`showcase/`)**:
  - Unified Case 07 room-temperature Hall carrier concentration & mobility data (`hall_composition_rt.csv`, `03_hall_composition_dual_axis`) with the Case 07 variable-temperature Hall mobility series (`04_hall_vt_mobility`).
  - Refreshed Case 04 cryogenic Debye–Callaway cascade fit and spectral thermal conductivity / MFP figures (`paper_demo_kl_4_300K_callaway_fit`, `paper_demo_kl_4_300K_callaway_spectral_mfp`).

## 1.5.0 - 2026-11-26

- **Mode-B Software Plugin & Workspace Initialization (`init`)**:
  - Added `te_analysis/paths.py` and `configs/workspace_template.json` (`configs/workspace.json`) to decouple `ENGINE_ROOT` (installed `tedex` package & plugin) from `WORKSPACE_ROOT` (clean user data directories with zero `.py` or skill clutter).
  - Added `te init` / `python main.py init` (`workspace_init.py`) supporting `--check` (exit code `2` onboarding prompt), `--status --json`, custom directory mappings, `by_batch` / `by_system_batch` / `by_project` subfolder topologies, configurable `batch_prefix`, and XRD/transport unit conventions.
  - Packaged standalone Mode-B plugin under `plugin/tedex/` alongside 5 orthogonal skills (`te-workspace`, `te-data-pipeline`, `te-plotting`, `te-xrd`, `te-physics-models`).
- **Phonon & Electronic Band Transport Physics Suite**:
  - Added `callaway` multi-mechanism Debye–Callaway $\kappa_{\mathrm{L}}(T)$ fitting (`U`, `B`, `PD`, `EP`, `D`, `NP`, `RES`), spectral $\kappa_{\mathrm{s}}(\omega)$, cumulative phonon MFP, and dual-unit Markdown reports.
  - Added `debye-calc` ultrasonic $(v_l, v_t)$ and low-$T$ $C_p(T)$ Debye $\Theta_{\mathrm{D}}$ / $v_{\mathrm{s}}$ / elastic moduli calculator with exit-code `2` missing-parameter prompting.
  - Added `debye-einstein` low-temperature $C_p/T^3$ boson-peak & rattler mode fitting.
  - Added non-parabolic `skb` (Single Kane Band) and `two-band` (`convergence`, `bipolar`, and semimetal Hall inversion) models with SVD Jacobian collinearity diagnostics.
- **Expanded Scientific Plotting (`sciplot`) & Advanced XRD (`plot-xrd`)**:
  - Renamed general scientific plotter to `sciplot` (`flexible` kept as backward-compatible alias) with 20+ chart kinds (`heatmap`, `contour`, `ternary`, `bubble`, `waterfall`, `stacked_bar`, `broken_y`, `fit_residual`, `parity`, `arrhenius`, `radar`, `violin`, `boxplot`, `histogram`) and universal overlays.
  - Added advanced `plot-xrd` modes (`zoom`, `vt-map`, `vt-stack`, `rietveld`, `peak-fit`, `williamson-hall`) and sequential figure stem renaming (`--rename "[1]"`).
  - Added automatic inside-axes legend layout (`legend_layout.py`) with collision avoidance and dynamic axis headroom across `plot-te`, `sciplot`, `plot-xrd`, `spb`, and physics models.
- **Self-Contained `tedex` Package Consolidation**:
  - Moved pipeline (`te_analysis/pipeline/`) and metadata sync (`te_analysis/sync/`) modules inside `te_analysis/` so all `te` / `tedex` CLI commands work from standalone wheel installations while keeping `scripts/` shims backward-compatible.
  - Added `plot-te --yscale` (`linear`, `log`, `symlog`), shared `--color-set` palettes (default `npg` + sequential ramps, [docs/COLOR_SETS.md](docs/COLOR_SETS.md)), and two-card XRD comparison layouts.
  - Added MIT `LICENSE` and expanded `.gitignore` safeguards for private laboratory datasets.

## 1.4.1

- Fixed small bugs found after the v1.4.0 launcher and path cleanup.
- Refined plot and documentation formatting for a cleaner GitHub release.
- Rebuilt the public package with current source, scripts, configs, docs,
  public demo data, and PDF card examples.
- Cleaned release contents by excluding Python caches, macOS metadata,
  LaTeX build intermediates, local outputs, and private/raw data.

## 1.4.0

- Added `main.py` as the single root command launcher for analysis, plotting,
  SPB fitting, metadata sync, XRD lattice fitting, assessment, and prediction.
- Moved runnable analysis entry scripts into `scripts/analysis/`.
- Moved runnable plotting entry scripts into `scripts/plotting/`.
- Renamed XRD and SPB Python paths to lowercase:
  - `plot_XRD.py` -> `scripts/plotting/plot_xrd.py`
  - `src/tools/plot_XRD_data.py` -> `src/tools/plot_xrd_data.py`
  - `src/tools/SPB/` -> `src/tools/spb/`
- Removed the obsolete flexible plotting demo runner; flexible recipes now run
  through `python main.py flexible --recipe ...`.
- Updated README, command docs, project structure docs, and local workflow
  notes for the unified launcher.

## 1.3.0

- Added SPB effective-mass fitting from Hall carrier concentration and
  Seebeck data.
- Added SPB performance fitting for Seebeck, power factor, and zT curves from
  grouped `nH-S-PF-ZT` tables.
- Added conductivity-axis SPB fitting for data without measured Hall carrier
  concentration, including weighted `u0` fitting, fixed `u0`, `kL`, and
  legend parameter summaries.
- Added SPB plot recipes under `configs/plot_recipes/spb/`.
- Added public SPB demo inputs and gallery figures under
  `data/demo/spb_fitting/`.

## 1.2.1

- Added bar and grouped-bar support to `flexible_plot.py`.
- Added reusable bar chart recipes under `configs/plot_recipes/bar/`.
- Added thermoelectric property recipes under
  `configs/plot_recipes/thermoeletric/`.
- Added public demo figures and inputs for bar charts and TE property plots
  under `data/demo/`.
- Refreshed the GitHub README with v1.2.1 examples and gallery images.

## 1.2.0

- Rebuilt the GitHub package from the current workspace source tree.
- Included current root entry scripts, `src/agents`, `src/tools`, `scripts`,
  `myplotstyle`, docs, and public plotting recipes.
- Included only public demo data under `data/demo/`; private raw, processed,
  lab, reference, result, and output folders are empty placeholders.
- Added `te-flex-plot`, `te-assess-batches`, and `te-bayes-predict` console
  entry points.
- Added README gallery images copied from `data/demo/`.

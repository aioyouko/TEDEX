# Project Commands

Run commands from the workspace root:

```bash
cd ~/Documents/tedex
```

Most user-facing tools are launched through `main.py`:

| Task | Command |
| --- | --- |
| Workspace initialization | `python main.py init [--check\|--status\|--yes ...]` |
| TE raw-data analysis | `python main.py analyze ...` |
| TE plotting | `python main.py plot-te ...` |
| XRD plotting | `python main.py plot-xrd ...` |
| Scientific plotting (`sciplot`) | `python main.py sciplot ...` |
| SPB fitting | `python main.py spb <mode> ...` where `<mode>` is `effective-mass`, `conductivity`, or `performance` (use `band` for `skb` / `two-band`) |
| Physics modeling | `python main.py model <name> ...` (`callaway`, `debye-calc`, `debye-einstein`, `skb`, `two-band`) |
| Debye $\Theta_{\mathrm{D}}$ / $v_{\mathrm{s}}$ calculator | `python main.py debye-calc ...` |
| XRD lattice fitting | `python main.py xrd-lattice ...` |
| Lab metadata sync | `python main.py sync metadata ...` |
| Lab Markdown sync | `python main.py sync markdown ...` |
| Batch assessment | `python main.py assess ...` |
| Bayesian prediction | `python main.py bayes ...` |

Use `python main.py --help` or `python main.py <command> --help` to inspect
the current options.

## How the Launcher Works

The root `main.py` is intentionally a 10-line shim: the actual launcher lives
in `te_analysis/launcher.py` so the installed package owns it. Running
`python main.py <command>` dispatches to the matching entry script. If the
package is installed with `pip install -e .`, the same launcher is also
available as the `te` command (`te plot-te ...`, `te sciplot ...`).

Where the plotting implementation now lives (each split from a former
single-file module, with the old module names kept as import shims):

| Area | Package | Entry point |
| --- | --- | --- |
| TE property plots | `te_analysis/tools/te_plotting/` (properties, ledger, locate) | `te_analysis/tools/te_plotting/cli.py` via `python main.py plot-te` |
| Scientific recipe & chart plots (`sciplot`) | `te_analysis/tools/sciplot/` (util, normalize, style, render, output, cli) | `python main.py sciplot` |
| XRD plots | `te_analysis/tools/xrd/` (io, pdf_cards, render) | `te_analysis/tools/xrd/cli.py` via `python main.py plot-xrd` |

## Rename Exported Figures

All plotting and fitting entry points support `--rename`, including `plot-te`, `plot-xrd`, `sciplot`, `spb`, `callaway`, `debye-einstein`, `skb`, `two-band`, `demo paper-te`, automatic `analyze` plots, `bayes`, FTIR plotting scripts, and palette preview scripts. It overrides only the exported figure filename stem while keeping the target output directory, raw data, CSV/JSON tables, and report filenames unchanged.

```bash
# Single XRD figure saved as [1].svg; compatible with --pick
python main.py plot-xrd data/raw/TE-1038/XRD --pick 124 --rename "[1]" --no-show

# Two XRD figures: raw counts [1].svg, normalized [2].svg
python main.py plot-xrd data/raw/TE-1038/XRD --both --rename "[1].svg" --no-show

# Multiple TE figures numbered sequentially in rendering order: [5].svg, [6].svg, [7].svg
python main.py plot-te TE-1048 --seebeck --conductivity --zt --rename "[5]" --no-show

# Custom plain names are also supported; multiple figures become XRD.svg, XRD_2.svg, ...
python main.py plot-xrd TE-1038 --rename "XRD" --no-show

# Multiple formats of the same figure share the same index: [1].svg and [1].pdf
python main.py sciplot --recipe configs/plot_recipes/thermoelectric/temperature_vs_zt.json --rename "[1]" --formats svg pdf --no-show

python main.py spb effective-mass data/demo/spb_fitting/Ag2Se/Ag2Se_series.csv --rename "[1]" --no-show
```

Quote bracketed names such as `"[1]"` so the shell does not treat them as glob patterns. `--rename "[1]"` and `--rename "[1].svg"` specify the same stem: any optional image extension is stripped, and exported formats remain controlled by `--formats` or `--pdf`. Omitting `--rename` preserves default naming.

Numbering increments in actual rendering order across samples, properties, and recipes within one command; multi-format exports and sidecar copies of the same figure share the same index. Pass a filename stem only (no directory separators). `--comparison-id` and `--stem` retain their grouping, folder, and table naming roles.

## Plot Color Sets

`plot-te`, `plot-xrd`, `sciplot`, `spb`, and the physics fitting commands support `--color-set`. Automatic coloring defaults to `npg`; available presets are `science`, `classic`, `blue-orange`, `blue`, `teal`, `purple`, `orange`, `red`, `gray`, and `legacy`. The six monochromatic ramps generate dark-to-light gradients scaled to the series count. Explicit per-series `--color` flags in XRD or `sciplot` take precedence over `--color-set`.

See [COLOR_SETS.md](COLOR_SETS.md) for swatches, cross-batch examples, and recipe syntax.

```bash
python main.py plot-te TE-1048 --zt --legend --color-set blue --no-show
python main.py plot-xrd TE-1056-B --color-set purple --no-show
```

## Quick Plotting Recipes

The three most common plotting tasks:

```bash
# 1. Plot processed TE properties for a batch (or a direct CSV path)
python main.py plot-te TE-1048 --zt --no-show
python main.py plot-te path/to/sample.csv --seebeck --conductivity --zt --no-show

# 2. Plot XRD patterns (batch, sample, or a direct .xy file)
python main.py plot-xrd TE-1056-B --no-show
python main.py plot-xrd path/to/pattern.xy --no-pdf-card --no-show --output-dir out/

# 3. Render a flexible plot recipe
python main.py sciplot --recipe configs/plot_recipes/thermoelectric/temperature_vs_zt.json --no-show
```

## Running the Tests

The characterization test suite pins current behavior so refactors can be
verified:

```bash
pytest tests/              # with pytest installed
python tests/run_tests.py  # fallback runner, no pytest needed
```

The first run records missing golden baselines (reported as skips); rerun to
compare against them. SPB tests require scipy.

## Run TE Analysis

The selected-batch raw-data workflow is implemented in `te_analysis/pipeline/te_analysis_pipeline.py` and
called by `python main.py analyze`. This workflow processes raw ZEM/LFA data, calculates
transport properties, extracts feature JSON, and plots TE summaries. It does not
run any agent/LLM analysis.

Analyze one selected batch:

```bash
python main.py analyze TE-1048
```

Analyze multiple selected batches:

```bash
python main.py analyze TE-1038 TE-1040
```

Short numeric batch names are accepted:

```bash
python main.py analyze 1038 1040
```

Analyze every batch currently listed in `data/lab/batches.json`:

```bash
python main.py analyze --all
```

Preview which batches would run without modifying files:

```bash
python main.py analyze TE-1038 TE-1040 --dry-run
```

Skip Markdown import before analysis:

```bash
python main.py analyze TE-1038 --no-markdown-sync
```

Skip raw-folder metadata scan before and after analysis:

```bash
python main.py analyze TE-1038 --no-raw-sync
```

Skip refreshing `data/lab/lab_metadata.md` after analysis:

```bash
python main.py analyze TE-1038 --no-markdown-refresh
```

Fail if a requested batch is missing:

```bash
python main.py analyze TE-9999 --strict
```

Raw TE files should be arranged like:

```text
data/raw/TE-1048/TE-1048-A_ZEM.txt
data/raw/TE-1048/TE-1048-A_LFA.csv
```

Before analysis, fill `density` and `cp_value` for each sample in `data/lab/lab_metadata.md` or `data/lab/samples.json`.

## Plot TE Data

Default plot output is transparent-background SVG at 600 dpi. `python main.py plot-te` now defaults to
single-property output; it only writes combined summary figures when
`--plot-mode combined` or `--plot-mode both` is passed. The default plot frame
ratio is 10:8 for single-property plots and for each panel in combined figures.
Combined figures keep one legend above the panels; single-property figures omit
legends by default so the curves are not covered.

Enable zsh tab completion for `python main.py plot-te` options:

```bash
source scripts/plot_te_completion.zsh
plot_te --s<Tab>
```

After sourcing, use `plot_te` instead of `python main.py plot-te` when you want tab
completion. To enable it permanently, add the `source .../scripts/plot_te_completion.zsh`
line to `~/.zshrc`.

Plot one whole batch:

```bash
python main.py plot-te TE-1040
```

Also copy generated TE figures beside the processed data:

```bash
python main.py plot-te TE-1040 --data-figures
# copies to data/processed/TE-1040-processed/figures/
```

Plot multiple batches together:

```bash
python main.py plot-te TE-1038 TE-1040 --plot-mode combined
```

Plot one named sample/composition:

```bash
python main.py plot-te TE-1040-Zn_dope_0.02 --seebeck
```

Plot one direct processed CSV. The shorter folder alias is accepted:

```bash
python main.py plot-te data/processed/TE-1040/Zn_dope_0.02.csv --plot-mode combined
```

Plot every CSV in one processed directory:

```bash
python main.py plot-te data/processed/TE-1040 --plot-mode combined
```

For direct CSV or directory inputs, figures are saved back to the source folder
by default. The first CSV column is treated as temperature, so copied
inter-batch comparison folders can be plotted without renaming that column:

```bash
python main.py plot-te data/processed/inter_batch_compare --seebeck --legend --formats svg png
# saves data/processed/inter_batch_compare/inter_batch_compare_seebeck.svg
```

Custom legend labels can be placed in the same folder using `label`, `labels`,
`legend`, or `legends`, with optional `.txt`, `.csv`, `.tsv`, or `.md`
suffixes. Put one label per row; CSV/TSV files use the first column. Labels are
applied in sorted `.csv` filename order, excluding the label file itself.
This applies to batch IDs and individual sample selectors as well as direct
CSV/folder paths. For example, `plot-te TE-1074 --seebeck --legend` reads
`data/processed/TE-1074-processed/legend.txt` before using ledger sample names.
Selecting only some samples keeps their positions in the full folder order.
Custom labels are used as written, without an added batch prefix; missing
labels fall back to ledger names (or filenames when no ledger name exists).
`--legend` controls visibility; it does not choose the label source.

Generate combined and single-property figures:

```bash
python main.py plot-te TE-1040 --plot-mode both
```

Generate only one selected single-property figure. The one-dash shortcut is also
accepted for quick interactive use:

```bash
python main.py plot-te TE-1040 --seebeck
python main.py plot-te TE-1040 --s
python main.py plot-te TE-1040 -seebeck
```

Save PNG output instead of the default SVG:

```bash
python main.py plot-te TE-1040 --plot-mode combined --formats png
```

Save SVG plus vector PDF output:

```bash
python main.py plot-te TE-1040 --plot-mode combined --pdf
```

Generate only selected single-property figures:

```bash
python main.py plot-te TE-1040 --properties seebeck zt power_factor
python main.py plot-te TE-1040 --properties s sigma pf kl zt
```

Short aliases are accepted as standalone flags and inside `--properties`:
`--s` for Seebeck, `--sigma` or `--cond` for electrical conductivity,
`--kappa`/`--kt`/`--tc` for total thermal conductivity, `--kl` for lattice
thermal conductivity, `--ke` for carrier thermal conductivity, `--pf` for power
factor, `--rho` for resistivity, `--eta` for generalized Fermi level, `--muw`
for weighted mobility, and `--b` for quality factor.

Add a boxed inside legend to selected single-property plots:

```bash
python main.py plot-te TE-1040 --seebeck --legend
python main.py plot-te TE-1040 --properties seebeck zt --single-legend inside --legend-font-size 8
python main.py plot-te data/processed/inter_batch_compare --pf --legend --legend-columns 2
```

Use `--legend-columns N` when long inter-batch legends should wrap into
multiple columns. The aliases `--legend-cols` and `--legend-ncol` are also
accepted. This works for single-property legends and combined summary legends.

Set the y-axis scale for single-property plots and every combined subplot.
The default is `linear`; `--yscal` is an alias for `--yscale`:

```bash
python main.py plot-te TE-1040 --conductivity --yscal log --legend
python main.py plot-te TE-1040 --seebeck --yscal symlog --legend
python main.py plot-te TE-1040 --plot-mode combined --yscale symlog
```

`log` displays positive values only; use positive bounds with `--ylim`.
`symlog` displays negative values, zero, and positive values, with a linear
region near zero and logarithmic scaling farther away. The scale changes
axis spacing, while property units and plotted data stay the same.

Place the single-property legend outside the plot frame:

```bash
python main.py plot-te TE-1040 --plot-mode single --single-properties zt --single-legend outside
```

Change the per-panel plot frame ratio. `10:8` is the default; `1:1` makes each
combined subplot square:

```bash
python main.py plot-te TE-1040 --plot-mode combined --subplot-aspect 1:1
python main.py plot-te TE-1040 --plot-mode single --single-properties zt --subplot-aspect 10:8
```

`--aspect` is a shorter alias for `--subplot-aspect` in `plot-te`, `plot-xrd`,
`sciplot`, and all three `spb` fitting commands.

The shared default canvas height per panel is 5.30 inches, with width derived
from the selected aspect ratio: `10:8` gives 6.625 × 5.30 inches, and `10:12`
gives about 4.417 × 5.30 inches. These dimensions apply to previews and exports;
explicit `figsize` settings still take precedence where supported. Default axis
tick labels are 20 pt and axis titles (x/y labels) are 24 pt in both single-panel
and combined plots. Default markers are 10.0 pt and general plot lines are
2.3 pt. These sizes, axis frames, ticks, and layout spacing use the same 2x
scale as the canvas to preserve the original compact plot proportions. Explicit marker/line sizes in recipes or command-line options take
precedence. Legends default to 15 pt, with row spacing of 0.65 times the
font size and a handle height of 1.0 times the font size. Legends above the
plot reserve space based on their rendered height. `--legend-font-size`
continues to override the default where supported. XRD keeps its separate
`--line-width` setting and its 7.5 pt trace/PDF labels; an explicit XRD
`--legend-font-size` also sizes those labels. The 600 DPI export setting
remains unchanged. XRD's `--tick-labelsize` overrides its tick label size.

Change marker size for both combined and single-property plots. The default is
10.0 pt, so markers keep the same visual scale across plot modes:

```bash
python main.py plot-te TE-1040 --plot-mode both --marker-size 8
```

Use the saved selected-sample plotting script so repeated plots keep the same
sample list and y-axis limits:

```bash
./scripts/plot_selected_te.sh
```

The script currently plots `TE-1036-A`, `TE-1040-A`, `TE-1040-B`, and
`TE-1054-A`, with `power_factor` fixed to `0 15` and `conductivity` fixed to
`0 300`. Extra `python main.py plot-te` options can be appended:

```bash
./scripts/plot_selected_te.sh --ylim zt 0 1.2 --comparison-id selected_fixed_axes
```

Set the shared temperature range for all TE plots:

```bash
python main.py plot-te TE-1040 --seebeck --xlim 300 800
```

By default, `python main.py plot-te` shows a matplotlib preview window after saving, useful
when tuning axis limits:

```bash
python main.py plot-te TE-1040 --seebeck --xlim 300 800 --ylim -300 300
```

Disable preview windows for batch output:

```bash
python main.py plot-te TE-1040 --seebeck --no-show
```

Set y-axis limits for individual TE properties:

```bash
python main.py plot-te TE-1040 --seebeck --ylim -300 300
python main.py plot-te TE-1040 --plot-mode both --ylim zt 0 1.2 --ylim seebeck -300 300
```

Set a custom inter-batch output folder/name:

```bash
python main.py plot-te TE-1038 TE-1040 --comparison-id TE1038_vs_TE1040
```

Outputs go under:

```text
outputs/figures/te/<batch>/
outputs/figures/te/inter-batch/<comparison-id>/
```

## Flexible Plotting

Use `python main.py sciplot` for loosely structured CSV/TXT/XLSX files or reusable
JSON plotting recipes. Detailed examples live in
`docs/SCIPLOT.md`.

Run one demo recipe:

```bash
python main.py sciplot --recipe configs/sciplot_demos/temperature_seebeck_line.json --no-show
```

Direct CLI example:

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/literature_comparison_loose.csv \
  --kind scatter \
  --x "Ag fraction x" \
  --y "Best zT" \
  --xlabel "Ag fraction, $x$" \
  --ylabel "$ZT_{\\mathrm{max}}$" \
  --stem demo_scatter \
  --formats png pdf \
  --no-show
```

Grouped bar example:

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/composition_grouped_bar_summary.csv \
  --kind grouped_bar \
  --x "Composition" \
  --y "zT_500K" \
  --y "zT_700K" \
  --label "500 K" \
  --label "700 K" \
  --ylabel "$zT$" \
  --stem demo_grouped_bar \
  --formats png pdf \
  --no-show
```

## SPB Recipes: Flexible vs Fitting Commands

There are two SPB plotting paths, and they use the recipe files in
`configs/plot_recipes/spb/` differently:

- `python main.py sciplot ... --recipe <recipe.json>` runs a JSON recipe
  directly on a user-provided table. This is best for already-cleaned SPB
  summary tables.
- `python main.py spb <mode> ...` runs an SPB fitting workflow first, builds the
  model/point tables internally, then uses the SPB recipe only as the plot-style
  template. These commands do not shell out to `python main.py sciplot`; they
  call the same flexible plotter functions inside Python.

Direct flexible SPB recipes:

| Recipe | Direct command | Expected key columns | Plot |
|---|---|---|---|
| `configs/plot_recipes/spb/carrier_concentration_vs_seebeck.json` | `python main.py sciplot data.csv --recipe ...` | `n_H_cm-3`, `Seebeck_uV_K` | `$n_{\mathrm{H}}$` vs `$S$` |
| `configs/plot_recipes/spb/carrier_concentration_vs_mobility.json` | `python main.py sciplot data.csv --recipe ...` | `n_H_cm-3`, `mu_H_cm2_V-1_s-1` | `$n_{\mathrm{H}}$` vs `$\mu_{\mathrm{H}}$` |
| `configs/plot_recipes/spb/carrier_concentration_vs_power_factor.json` | `python main.py sciplot data.csv --recipe ...` | `n_H_cm-3`, `PF_uW_cm-1_K-2` | `$n_{\mathrm{H}}$` vs `$PF$` |
| `configs/plot_recipes/spb/carrier_concentration_vs_zt.json` | `python main.py sciplot data.csv --recipe ...` | `n_H_cm-3`, `zT` | `$n_{\mathrm{H}}$` vs `$zT$` |

Example:

```bash
python main.py sciplot data/demo/spb_fitting/Ag2Se/Ag2Se_series.csv \
  --recipe configs/plot_recipes/spb/carrier_concentration_vs_power_factor.json \
  --x nH \
  --y PF \
  --formats png pdf \
  --no-show
```

The SPB summary recipes set `output.copy_to_data_dir: true`, so successful runs
also copy the figure and normalized CSV beside the input data. If your table
uses different column names, override the recipe selectors:

```bash
python main.py sciplot data/demo/spb_fitting/Ag2Se/Ag2Se_series.csv \
  --recipe configs/plot_recipes/spb/carrier_concentration_vs_seebeck.json \
  --x nH \
  --y S \
  --no-show
```

SPB fitting command recipe mapping:

| Command | Script | Recipe(s) loaded for plots | Main outputs |
|---|---|---|---|
| `python main.py spb effective-mass ...` aliases: `mass`, `mstar`, `pisarenko` | `te_analysis/tools/spb/effective_mass_fit.py` | `configs/plot_recipes/spb/pisarenko_fit.json` | `effective_mass_points.csv`, `pisarenko_curve.csv`, `fit_summary.json`, `pisarenko_fit.*` |
| `python main.py spb performance ...` aliases: `fitting`, `fit`, `pf`, `zt` | `te_analysis/tools/spb/performance_fit.py` | `pf_fit.json` for `--properties pf`; `zt_fit.json` for `--properties zt` | `performance_points.csv`, `performance_curve.csv`, `performance_summary.json`, `pf_fit.*`, `zt_fit.*` |
| `python main.py spb conductivity ...` aliases: `sigma`, `mobility` | `te_analysis/tools/spb/conductivity_fit.py` | `conductivity_seebeck_fit.json`, `conductivity_pf_fit.json`, `conductivity_zt_fit.json` | `conductivity_points.csv`, `conductivity_curve.csv`, `conductivity_summary.json`, `conductivity_seebeck_fit.*`, `conductivity_pf_fit.*`, `conductivity_zt_fit.*` |

The fitting recipes are usually internal style templates. They expect columns
created by the fitting scripts, such as `nH_cm-3`,
`Seebeck_model_abs_uV_K`, `Power_Factor_model_uW_cm-1_K-2`,
`Conductivity_S_cm-1`, and `ZT_model`. You can run them with `sciplot`
manually only if your input table already has those model/data columns.
Grouped SPB runs also write a `*_summary_by_group.csv`. All SPB fitting
commands copy generated figures beside the input CSV in addition to writing
them under `--output-dir`.

Typical fitting commands:

```bash
python main.py spb effective-mass \
  data/demo/spb_fitting/Ag2Se/Ag2Se_series.csv \
  --group-by curve_id \
  --params data/demo/spb_fitting/Ag2Se/Ag2Se_params.csv \
  --formats png pdf \
  --no-show

python main.py spb performance \
  data/demo/spb_fitting/Ag2Se/Ag2Se_series.csv \
  --group-by curve_id \
  --params data/demo/spb_fitting/Ag2Se/Ag2Se_params.csv \
  --properties pf zt \
  --kL 0.5 \
  --formats png pdf \
  --no-show

python main.py spb conductivity \
  data/demo/spb_fitting/Cu2SSeTe/900K.csv \
  --sigma-unit S/cm \
  --properties seebeck pf zt \
  --kL 0.5 \
  --formats png pdf \
  --no-show
```

Plot styling in the `spb` commands comes from the loaded recipe, but common
plot options override it at runtime: `--xlim`, `--ylim`, `--xscale`,
`--yscale`, `--legend`, `--legend-loc`, `--legend-font-size`,
`--subplot-aspect`, `--figsize`, `--title`, and `--show-title`.
For SPB commands that write multiple plots, `--ylim LOW HIGH` applies the same
limits to all plots, while repeated property-specific limits target individual
plots:

```bash
python main.py spb performance input.csv \
  --properties pf zt \
  --ylim pf 0 15 \
  --ylim zt 0 1.2

python main.py spb conductivity input.csv \
  --properties seebeck pf zt \
  --ylim seebeck 0 300 \
  --ylim pf 0 15 \
  --ylim zt 0 1.2
```

## Advanced Electronic & Phonon Physics Fitting (`callaway`, `debye-calc`, `debye-einstein`, `skb`, `two-band`)

All physics tools are available both as top-level commands (`python main.py callaway ...`) and under the `model` / `physics` group (`python main.py model <name> ...`). Every fitting model exports `*_points.csv`, `*_curve.csv`, `*_summary.json` (with SVD Jacobian condition numbers, 95% parameter confidence intervals, and correlation matrices), and publication-grade figures (`#79ADD8`/`#264B73` experimental markers + `#E64B35` crimson-red best-fit curves).

```bash
# 0. Debye temperature & average sound velocity calculator (ultrasonic vl/vt or low-T Cp)
python main.py debye-calc --vl 2600 --vt 1450 --density-g-cm3 6.15 --molar-mass 433.0 --atoms-per-fu 4
python main.py debye-calc --cp-csv data/demo/physics_fitting/cp_rattler.csv --atoms-per-fu 4 --atomic-volume-a3 29.0

# 1. Debye-Callaway multi-source phonon scattering + stage-shaded spectral kappa_s + cumulative MFP
#    Supported mechanisms: U (Umklapp), B/GB (boundary), PD (point defect), EP (e-ph/planar), D (dislocation), NP (nanoprecipitate), RES/R (resonant rattler)
python main.py callaway data/demo/physics_fitting/paper_demo_kl_4_300K.csv \
  --theta-d 146 --vs 1445 --mechanisms U B PD RES \
  --spectral-xaxis meV --spectral-norm x --rattler-damping 0 --ref-temp 300 --no-show

# Run directly on a processed TE CSV (automatically subtracts electronic kappa_e via SPB Lorenz number)
python main.py callaway data/processed/TE-1048-processed/sample.csv --theta-d 210 --vs 2200 --no-show

# 2. Debye-Einstein low-T heat capacity Cp(T) & boson-peak (Cp/T^3 vs T) multi-oscillator fit
python main.py debye-einstein data/demo/physics_fitting/cp_rattler.csv \
  --atoms-per-fu 4 --n-einstein 2 --volume-a3-per-fu 116.0 --no-show

# 3. Non-parabolic Single Kane Band (SKB, alpha = k_B T / E_g) with parabolic SPB reference overlay
python main.py skb data/demo/physics_fitting/skb_narrow_gap.csv \
  -T 300 --eg 0.24 --nv 4 --rho 8150 --vl 3050 --kL 0.85 --no-show

# 4a. Two-Band Mode A: Isothermal light + heavy band convergence vs nH (use --fix-m1 / --fix-m2 / --fix-delta-e / --fix-b to break collinearity)
python main.py two-band data/demo/physics_fitting/two_band_convergence.csv \
  --mode convergence -T 300 --band1-eg 0.28 --no-show

# 4b. Two-Band Mode B: Variable-temperature bipolar excitation vs T (solves charge neutrality & extracts bipolar kappa_bi)
python main.py two-band data/demo/physics_fitting/two_band_bipolar.csv \
  --mode bipolar --no-show
```

## Plot XRD Data

Plot one XRD batch as a normalized stacked figure, without a PDF card by default:

```bash
python main.py plot-xrd TE-1038
```

Plot one XRD sample. Normalized output is the default, so `--mode normalized`
or `--normalized` is optional:

```bash
python main.py plot-xrd TE-1038-A
```

Plot raw-count/normal-intensity XRD instead of normalized intensity:

```bash
python main.py plot-xrd TE-1038 --raw
```

Save both raw-count and normalized XRD versions:

```bash
python main.py plot-xrd TE-1038 --both
```

Plot all XRD files in a direct folder:

```bash
python main.py plot-xrd data/raw/TE-1038/XRD
```

Select XRD files by 1-based index (ordered by sorted filename):

```bash
# List discovered files, 1-based indices, and resolved legend labels without plotting
python main.py plot-xrd data/raw/TE-1038/XRD --list-files

# Plot only files 1, 2, and 4, or files 2, 3, and 4
python main.py plot-xrd data/raw/TE-1038/XRD --pick 124
python main.py plot-xrd data/raw/TE-1038/XRD --pick 234

# Use space-separated --indices when selecting two-digit indices (e.g. 1, 2, and 10)
python main.py plot-xrd data/raw/TE-1038/XRD --indices 1 2 10
# Select only file 10
python main.py plot-xrd data/raw/TE-1038/XRD --indices 10
```

Omitting index flags plots all discovered files. In `--pick`, each digit is a single-digit index (`1–9`); in `--indices`, each space-separated integer is a full index (the two flags are mutually exclusive). Traces are always rendered in canonical sorted order and duplicate indices are deduplicated. Indices refer to the full loaded file list prior to `--select` filtering; inspect `--list-files` to confirm numbering across multiple folders.

Folder `legend` / `label` files remain aligned row-for-row with the full sorted `.xy` file list without manual editing: for example, `--pick 124` automatically picks rows 1, 2, and 4 for both standard legends and `--right-labels`. Index-filtered stacked figures append suffixes such as `_pick_1_2_4` unless `--comparison-id` is set explicitly. Compatible with `--both` and `--layout separate`.

Plot selected samples from one XRD folder:

```bash
python main.py plot-xrd data/raw/TE-1038/XRD --select A C
```

Use custom trace labels from a file in the same XRD folder. These labels are
used by both the legend and `--right-labels`. Supported filenames include
`label`, `labels`, `legend`, and `legends`, with optional `.txt`, `.csv`,
`.tsv`, or `.md` suffixes. Put one label per row; CSV/TSV files use the first
column. Labels are applied in sorted `.xy` filename order.

```text
# data/raw/TE-1038/XRD/legend
$\mathit{CuInTe_2}$
$\mathit{CuInTe_2}$ + 2% Sb
$\mathit{CuInTe_2}$ + 4% Sb
```

Plot each selected XRD file as a separate figure:

```bash
python main.py plot-xrd data/raw/TE-1038/XRD --select A C --layout separate
```

Save figures without opening the matplotlib viewer:

```bash
python main.py plot-xrd data/raw/TE-1038/XRD --no-show
```

Also copy generated XRD figures beside the source XRD data:

```bash
python main.py plot-xrd data/raw/TE-1038/XRD --data-figures --no-show
# copies to data/raw/TE-1038/XRD/figures/
```

Use `--data-figures-dir plots` if you prefer a folder named `plots`.

Use a clean PDF standard CSV by basename:

```bash
python main.py plot-xrd TE-1038 --pdf-card CuInTe2_PDF_97_023_8958
```

Plot two PDF cards by repeating `--pdf-card`. The first card is placed below
all measured XRD traces and the second is placed above them:

```bash
python main.py plot-xrd TE-1038 \
  --pdf-card CuInTe2_PDF_97_023_8958 \
  --pdf-card Sb2Te3_PDF_97_067_0037
```

The bottom PDF sticks start directly from the x-axis. The top PDF sticks use a
separate black baseline. Both stick fields are scaled taller than before
relative to a normalized XRD trace. PDF-card names are hidden by default; add
`--pdf-labels` to show them. When shown, the top name is placed above its sticks.
The default maximum stick-height fraction is `1.0`. The bottom card-to-first-
trace gap is `0.25` of one offset step, while the top separation remains `0.60`.
Use `--pdf-height-fraction` only when an explicit height override is needed.
The default card colors are red and blue; override them independently when needed:

```bash
python main.py plot-xrd TE-1038 \
  --pdf-card CuInTe2_PDF_97_023_8958 \
  --pdf-card Sb2Te3_PDF_97_067_0037 \
  --pdf-labels \
  --standard-color '#d62728' \
  --top-standard-color '#1f77b4'
```

List available PDF-card basenames:

```bash
python main.py plot-xrd --list-pdf-cards
```

Optional shell completion for `--pdf-card` basenames uses `argcomplete` with
the direct script path:

```bash
eval "$(register-python-argcomplete scripts/plotting/plot_xrd.py)"
scripts/plotting/plot_xrd.py data/raw/TE-1038/XRD --select <TAB>
scripts/plotting/plot_xrd.py TE-1038 --pdf-card <TAB>
```

Use a clean PDF standard CSV by path:

```bash
python main.py plot-xrd TE-1038 --pdf-card data/pdf_card/plot_standards/CuInTe2_PDF_97_023_8958.csv
```

Use an extensionless path. The script will search `data/pdf_card/plot_standards` by basename:

```bash
python main.py plot-xrd TE-1038 --pdf-card data/pdf_card/CuInTe2_PDF_97_023_8958
```

Explicitly plot without a PDF card:

```bash
python main.py plot-xrd TE-1038 --no-pdf-card
```

Change the 2Theta range:

```bash
python main.py plot-xrd TE-1038 --xlim 15 75
```

Clip the stacked intensity range:

```bash
python main.py plot-xrd TE-1038 --ylim 0 auto
```

Use the shared TE plot frame ratio and override trace styling:

```bash
python main.py plot-xrd TE-1038 \
  --subplot-aspect 10:8 \
  --color '#d62728' --color '#1f77b4' \
  --line-width 0.9
```

Use `--aspect 10:12 --fixed-aspect` for a taller XRD plot frame that keeps its
ratio when the window is resized:

```bash
python main.py plot-xrd TE-1038 --aspect 10:12 --fixed-aspect
```

By default, XRD figures omit the conventional legend and PDF-card names, showing
only right-side trace labels. Add `--pdf-labels` to show the PDF-card names. If
the XRD folder contains `label`,
`labels`, `legend`, or `legends` with optional `.txt`, `.csv`, `.tsv`, or `.md`
suffix, labels are applied in sorted `.xy` file order; otherwise the `.xy` file
stems are used. Use `--legend` to restore the conventional legend or
`--no-right-labels` to hide the trace annotations.

```bash
python main.py plot-xrd TE-1038 --legend --pdf-labels --no-right-labels
```

Save multiple output formats:

```bash
python main.py plot-xrd TE-1038 --formats svg png
```

Save PNG plus vector PDF output:

```bash
python main.py plot-xrd TE-1038 --pdf
```

### Advanced XRD Layouts: Fitting, Refinement, Zoom & Variable-Temperature

`python main.py plot-xrd` supports six specialized diffraction figure types via `--layout` / `--figure` or direct shortcut flags:

```bash
# 1. Full-range stacked XRD paired with a synchronized zoomed peak-shift subpanel (--zoom LOW HIGH)
python main.py plot-xrd TE-1038 --zoom 26.6 28.4 --pdf-card CuInTe2_PDF_97_023_8958 --no-show

# 2. In-situ variable-temperature XRD 2D contour/heatmap (--vt-map, default soft-br blue-to-red palette)
python main.py plot-xrd data/raw/TE-1048/VT_XRD --vt-map \
  --pdf-card CuInTe2_PDF_97_023_8958 --transition-temp 635 --no-show

# 3. Variable-temperature waterfall XRD colored along a blue-to-red thermal gradient (--vt-stack)
python main.py plot-xrd data/raw/TE-1048/VT_XRD --vt-stack \
  --guide-2theta 27.55 45.40 --pdf-card CuInTe2_PDF_97_023_8958 --no-show

# 4. Rietveld / Le Bail refinement profile + Bragg tick bars + difference residual + high-angle zoom inset (--rietveld)
python main.py plot-xrd results/rietveld_profile.csv --rietveld \
  --pdf-card CuInTe2_PDF_97_023_8958 --pdf-card ZnSe_PDF \
  --formula "$\mathrm{CuIn_{0.8}Ga_{0.2}Te_2}$" \
  --cell-text "$I\overline{4}2d$: $a=6.142$ Å, $c=12.298$ Å" \
  --zoom 44.0 47.5 --no-show

# 5. Multi-peak pseudo-Voigt deconvolution + residual subpanel (--peak-fit, exports fitted peak table)
python main.py plot-xrd TE-1038-A --peak-fit --xlim 44.2 46.8 --no-show

# 6. Williamson-Hall crystallite size D and microstrain epsilon linear regression (--williamson-hall / --wh)
python main.py plot-xrd TE-1038-A --wh --pdf-card CuInTe2_PDF_97_023_8958 --instr-fwhm 0.05 --no-show
```

## Fit XRD Lattice Parameters

Fit lattice parameters for one measured XRD `.xy` file using a PDF-card text export with indexed peaks:

```bash
python main.py xrd-lattice \
  --pdf-card "data/pdf_card/CuInTe2 PDF#97-023-8958.txt" \
  --xrd data/raw/TE-1038/XRD/TE-1038-A_XRD.xy \
  --sample-name TE-1038-A \
  --output-dir results/xrd_lattice
```

Try lattice fitting for every XRD `.xy` file in one raw batch folder:

```bash
batch_id=TE-1038
for xrd in data/raw/${batch_id}/XRD/*.xy; do
  sample=$(basename "$xrd" .xy)
  sample=${sample%_XRD}
  sample=${sample%_Theta_2-Theta}
  python main.py xrd-lattice \
    --pdf-card "data/pdf_card/CuInTe2 PDF#97-023-8958.txt" \
    --xrd "$xrd" \
    --sample-name "$sample" \
    --output-dir results/xrd_lattice
done
```

The fitting command reads numeric XRD `.xy` data, detects observed peaks, matches them to the indexed PDF-card peaks, and writes lattice-fit JSON plus matched/observed peak CSV files.

XRD files should be arranged like:

```text
data/raw/TE-1038/XRD/TE-1038-A_XRD.xy
```

Clean PDF standards for plotting should go in:

```text
data/pdf_card/plot_standards/
```

Recommended PDF standard CSV format:

```csv
label,two_theta_deg,intensity,d_angstrom,h,k,l
CuInTe2 PDF#97-023-8958,24.875,100.0,3.5766,1,1,2
CuInTe2 PDF#97-023-8958,41.168,48.9,2.1909,2,0,4
```

Required columns are only `two_theta_deg` and `intensity`.

Outputs go under:

```text
outputs/figures/xrd/<comparison-id>/
```

## Sync Lab JSON And Markdown

Scan raw data folders and update `data/lab/batches.json`, `data/lab/samples.json`, and `data/lab/lab_metadata.md`:

```bash
python main.py sync metadata
```

Preview raw-folder sync without writing:

```bash
python main.py sync metadata --dry-run
```

Scan raw folders without importing/exporting Markdown:

```bash
python main.py sync metadata --no-markdown-sync
```

Export JSON metadata to editable Markdown:

```bash
python main.py sync markdown export
```

Import Markdown edits back to JSON:

```bash
python main.py sync markdown
```

The explicit equivalent is:

```bash
python main.py sync markdown import
```

Preview Markdown import without writing:

```bash
python main.py sync markdown import --dry-run
```

The main metadata files are:

```text
data/lab/batches.json
data/lab/samples.json
data/lab/lab_metadata.md
```

Usual workflow:

```bash
python main.py sync metadata
python main.py sync markdown export
# edit data/lab/lab_metadata.md
python main.py sync markdown
python main.py analyze TE-1048
python main.py plot-te TE-1048 --seebeck
python main.py plot-xrd TE-1038
```

### Markdown Layout (v2)

`lab_metadata.md` groups records by batch: an Overview table first, then one
`## <batch_id>` section per batch containing the `### Batch` table followed by
its `### Sample` tables. File paths (`Raw:` / `Processed:` lines) are shown as
read-only info; edit paths in JSON or let `sync metadata` manage them.
Deleting a section from the Markdown no longer deletes the JSON record — the
import keeps it and prints a warning. Pass `--prune` to actually delete
records removed from the Markdown.

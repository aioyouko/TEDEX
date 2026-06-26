# Project Commands

Run commands from the workspace root:

```bash
cd "/Users/chenheyang/Library/CloudStorage/OneDrive-NorthwesternUniversity/02-Northwestern Lab/te_agent_workspace"
```

Most user-facing tools are launched through `main.py`:

| Task | Command |
| --- | --- |
| TE raw-data analysis | `python main.py analyze ...` |
| TE plotting | `python main.py plot-te ...` |
| XRD plotting | `python main.py plot-xrd ...` |
| Flexible plotting | `python main.py flexible ...` |
| SPB fitting | `python main.py spb <mode> ...` where `<mode>` is `effective-mass`, `conductivity`, or `performance` |
| XRD lattice fitting | `python main.py xrd-lattice ...` |
| Lab metadata sync | `python main.py sync metadata ...` |
| Lab Markdown sync | `python main.py sync markdown ...` |
| Batch assessment | `python main.py assess ...` |
| Bayesian prediction | `python main.py bayes ...` |

Use `python main.py --help` or `python main.py <command> --help` to inspect
the current options.

## Run TE Analysis

The selected-batch raw-data workflow is implemented in `scripts/analysis/te_analysis.py` and
called by `python main.py analyze`. This workflow processes raw ZEM/LFA data, calculates
transport properties, extracts feature JSON, and plots TE summaries. It does not
run any agent/LLM analysis.

Analyze one selected batch:

```bash
python main.py analyze CHY-1048
```

Analyze multiple selected batches:

```bash
python main.py analyze CHY-1038 CHY-1040
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
python main.py analyze CHY-1038 CHY-1040 --dry-run
```

Skip Markdown import before analysis:

```bash
python main.py analyze CHY-1038 --no-markdown-sync
```

Skip raw-folder metadata scan before and after analysis:

```bash
python main.py analyze CHY-1038 --no-raw-sync
```

Skip refreshing `data/lab/lab_metadata.md` after analysis:

```bash
python main.py analyze CHY-1038 --no-markdown-refresh
```

Fail if a requested batch is missing:

```bash
python main.py analyze CHY-9999 --strict
```

Raw TE files should be arranged like:

```text
data/raw/CHY-1048/CHY-1048-A_ZEM.txt
data/raw/CHY-1048/CHY-1048-A_LFA.csv
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
python main.py plot-te CHY-1040
```

Also copy generated TE figures beside the processed data:

```bash
python main.py plot-te CHY-1040 --data-figures
# copies to data/processed/CHY-1040-processed/figures/
```

Plot multiple batches together:

```bash
python main.py plot-te CHY-1038 CHY-1040 --plot-mode combined
```

Plot one named sample/composition:

```bash
python main.py plot-te CHY-1040-Zn_dope_0.02 --seebeck
```

Plot one direct processed CSV. The shorter folder alias is accepted:

```bash
python main.py plot-te data/processed/CHY-1040/Zn_dope_0.02.csv --plot-mode combined
```

Plot every CSV in one processed directory:

```bash
python main.py plot-te data/processed/CHY-1040 --plot-mode combined
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

Generate combined and single-property figures:

```bash
python main.py plot-te CHY-1040 --plot-mode both
```

Generate only one selected single-property figure. The one-dash shortcut is also
accepted for quick interactive use:

```bash
python main.py plot-te CHY-1040 --seebeck
python main.py plot-te CHY-1040 --s
python main.py plot-te CHY-1040 -seebeck
```

Save PNG output instead of the default SVG:

```bash
python main.py plot-te CHY-1040 --plot-mode combined --formats png
```

Save SVG plus vector PDF output:

```bash
python main.py plot-te CHY-1040 --plot-mode combined --pdf
```

Generate only selected single-property figures:

```bash
python main.py plot-te CHY-1040 --properties seebeck zt power_factor
python main.py plot-te CHY-1040 --properties s sigma pf kl zt
```

Short aliases are accepted as standalone flags and inside `--properties`:
`--s` for Seebeck, `--sigma` or `--cond` for electrical conductivity,
`--kappa`/`--kt`/`--tc` for total thermal conductivity, `--kl` for lattice
thermal conductivity, `--ke` for carrier thermal conductivity, `--pf` for power
factor, `--rho` for resistivity, `--eta` for generalized Fermi level, `--muw`
for weighted mobility, and `--b` for quality factor.

Add a boxed inside legend to selected single-property plots:

```bash
python main.py plot-te CHY-1040 --seebeck --legend
python main.py plot-te CHY-1040 --properties seebeck zt --single-legend inside --legend-font-size 8
python main.py plot-te data/processed/inter_batch_compare --pf --legend --legend-columns 2
```

Use `--legend-columns N` when long inter-batch legends should wrap into
multiple columns. The aliases `--legend-cols` and `--legend-ncol` are also
accepted. This works for single-property legends and combined summary legends.

Place the single-property legend outside the plot frame:

```bash
python main.py plot-te CHY-1040 --plot-mode single --single-properties zt --single-legend outside
```

Change the per-panel plot frame ratio. `10:8` is the default; `1:1` makes each
combined subplot square:

```bash
python main.py plot-te CHY-1040 --plot-mode combined --subplot-aspect 1:1
python main.py plot-te CHY-1040 --plot-mode single --single-properties zt --subplot-aspect 10:8
```

Change marker size for both combined and single-property plots. The default is
5.0 pt, so markers keep the same visual scale across plot modes:

```bash
python main.py plot-te CHY-1040 --plot-mode both --marker-size 4.5
```

Use the saved selected-sample plotting script so repeated plots keep the same
sample list and y-axis limits:

```bash
./scripts/plot_selected_te.sh
```

The script currently plots `CHY-1036-A`, `CHY-1040-A`, `CHY-1040-B`, and
`CHY-1054-A`, with `power_factor` fixed to `0 15` and `conductivity` fixed to
`0 300`. Extra `python main.py plot-te` options can be appended:

```bash
./scripts/plot_selected_te.sh --ylim zt 0 1.2 --comparison-id selected_fixed_axes
```

Set the shared temperature range for all TE plots:

```bash
python main.py plot-te CHY-1040 --seebeck --xlim 300 800
```

By default, `python main.py plot-te` shows a matplotlib preview window after saving, useful
when tuning axis limits:

```bash
python main.py plot-te CHY-1040 --seebeck --xlim 300 800 --ylim -300 300
```

Disable preview windows for batch output:

```bash
python main.py plot-te CHY-1040 --seebeck --no-show
```

Set y-axis limits for individual TE properties:

```bash
python main.py plot-te CHY-1040 --seebeck --ylim -300 300
python main.py plot-te CHY-1040 --plot-mode both --ylim zt 0 1.2 --ylim seebeck -300 300
```

Set a custom inter-batch output folder/name:

```bash
python main.py plot-te CHY-1038 CHY-1040 --comparison-id CHY1038_vs_CHY1040
```

Outputs go under:

```text
outputs/figures/te/<batch>/
outputs/figures/te/inter-batch/<comparison-id>/
```

## Flexible Plotting

Use `python main.py flexible` for loosely structured CSV/TXT/XLSX files or reusable
JSON plotting recipes. Detailed examples live in
`docs/FLEXIBLE_PLOTTING.md`.

Run one demo recipe:

```bash
python main.py flexible --recipe configs/flexible_plot_demos/temperature_seebeck_line.json --no-show
```

Direct CLI example:

```bash
python main.py flexible \
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
python main.py flexible \
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

- `python main.py flexible ... --recipe <recipe.json>` runs a JSON recipe
  directly on a user-provided table. This is best for already-cleaned SPB
  summary tables.
- `python main.py spb <mode> ...` runs an SPB fitting workflow first, builds the
  model/point tables internally, then uses the SPB recipe only as the plot-style
  template. These commands do not shell out to `python main.py flexible`; they
  call the same flexible plotter functions inside Python.

Direct flexible SPB recipes:

| Recipe | Direct command | Expected key columns | Plot |
|---|---|---|---|
| `configs/plot_recipes/spb/carrier_concentration_vs_seebeck.json` | `python main.py flexible data.csv --recipe ...` | `n_H_cm-3`, `Seebeck_uV_K` | `$n_{\mathrm{H}}$` vs `$S$` |
| `configs/plot_recipes/spb/carrier_concentration_vs_mobility.json` | `python main.py flexible data.csv --recipe ...` | `n_H_cm-3`, `mu_H_cm2_V-1_s-1` | `$n_{\mathrm{H}}$` vs `$\mu_{\mathrm{H}}$` |
| `configs/plot_recipes/spb/carrier_concentration_vs_power_factor.json` | `python main.py flexible data.csv --recipe ...` | `n_H_cm-3`, `PF_uW_cm-1_K-2` | `$n_{\mathrm{H}}$` vs `$PF$` |
| `configs/plot_recipes/spb/carrier_concentration_vs_zt.json` | `python main.py flexible data.csv --recipe ...` | `n_H_cm-3`, `zT` | `$n_{\mathrm{H}}$` vs `$zT$` |

Example:

```bash
python main.py flexible data/demo/spb_fitting/Ag2Se/Ag2Se_series.csv \
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
python main.py flexible data/demo/spb_fitting/Ag2Se/Ag2Se_series.csv \
  --recipe configs/plot_recipes/spb/carrier_concentration_vs_seebeck.json \
  --x nH \
  --y S \
  --no-show
```

SPB fitting command recipe mapping:

| Command | Script | Recipe(s) loaded for plots | Main outputs |
|---|---|---|---|
| `python main.py spb effective-mass ...` aliases: `mass`, `mstar`, `pisarenko` | `src/tools/spb/effective_mass_fit.py` | `configs/plot_recipes/spb/pisarenko_fit.json` | `effective_mass_points.csv`, `pisarenko_curve.csv`, `fit_summary.json`, `pisarenko_fit.*` |
| `python main.py spb performance ...` aliases: `fitting`, `fit`, `pf`, `zt` | `src/tools/spb/performance_fit.py` | `pf_fit.json` for `--properties pf`; `zt_fit.json` for `--properties zt` | `performance_points.csv`, `performance_curve.csv`, `performance_summary.json`, `pf_fit.*`, `zt_fit.*` |
| `python main.py spb conductivity ...` aliases: `sigma`, `mobility` | `src/tools/spb/conductivity_fit.py` | `conductivity_seebeck_fit.json`, `conductivity_pf_fit.json`, `conductivity_zt_fit.json` | `conductivity_points.csv`, `conductivity_curve.csv`, `conductivity_summary.json`, `conductivity_seebeck_fit.*`, `conductivity_pf_fit.*`, `conductivity_zt_fit.*` |

The fitting recipes are usually internal style templates. They expect columns
created by the fitting scripts, such as `nH_cm-3`,
`Seebeck_model_abs_uV_K`, `Power_Factor_model_uW_cm-1_K-2`,
`Conductivity_S_cm-1`, and `ZT_model`. You can run them with `flexible`
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

## Plot XRD Data

Plot one XRD batch as a normalized stacked figure, without a PDF card by default:

```bash
python main.py plot-xrd CHY-1038
```

Plot one XRD sample. Normalized output is the default, so `--mode normalized`
or `--normalized` is optional:

```bash
python main.py plot-xrd CHY-1038-A
```

Plot raw-count/normal-intensity XRD instead of normalized intensity:

```bash
python main.py plot-xrd CHY-1038 --raw
```

Save both raw-count and normalized XRD versions:

```bash
python main.py plot-xrd CHY-1038 --both
```

Plot all XRD files in a direct folder:

```bash
python main.py plot-xrd data/raw/CHY-1038/XRD
```

Plot selected samples from one XRD folder:

```bash
python main.py plot-xrd data/raw/CHY-1038/XRD --select A C
```

Use custom legend labels from a file in the same XRD folder. Supported filenames
include `label`, `labels`, `legend`, and `legends`, with optional `.txt`,
`.csv`, `.tsv`, or `.md` suffixes. Put one label per row; CSV/TSV files use the
first column. Labels are applied in sorted `.xy` filename order.

```text
# data/raw/CHY-1038/XRD/legend
$\mathit{CuInTe_2}$
$\mathit{CuInTe_2}$ + 2% Sb
$\mathit{CuInTe_2}$ + 4% Sb
```

Plot each selected XRD file as a separate figure:

```bash
python main.py plot-xrd data/raw/CHY-1038/XRD --select A C --layout separate
```

Save figures without opening the matplotlib viewer:

```bash
python main.py plot-xrd data/raw/CHY-1038/XRD --no-show
```

Also copy generated XRD figures beside the source XRD data:

```bash
python main.py plot-xrd data/raw/CHY-1038/XRD --data-figures --no-show
# copies to data/raw/CHY-1038/XRD/figures/
```

Use `--data-figures-dir plots` if you prefer a folder named `plots`.

Use a clean PDF standard CSV by basename:

```bash
python main.py plot-xrd CHY-1038 --pdf-card CuInTe2_PDF_97_023_8958
```

List available PDF-card basenames:

```bash
python main.py plot-xrd --list-pdf-cards
```

Optional shell completion for `--pdf-card` basenames uses `argcomplete` with
the direct script path:

```bash
eval "$(register-python-argcomplete scripts/plotting/plot_xrd.py)"
scripts/plotting/plot_xrd.py data/raw/CHY-1038/XRD --select <TAB>
scripts/plotting/plot_xrd.py CHY-1038 --pdf-card <TAB>
```

Use a clean PDF standard CSV by path:

```bash
python main.py plot-xrd CHY-1038 --pdf-card data/pdf_card/plot_standards/CuInTe2_PDF_97_023_8958.csv
```

Use an extensionless path. The script will search `data/pdf_card/plot_standards` by basename:

```bash
python main.py plot-xrd CHY-1038 --pdf-card data/pdf_card/CuInTe2_PDF_97_023_8958
```

Explicitly plot without a PDF card:

```bash
python main.py plot-xrd CHY-1038 --no-pdf-card
```

Change the 2Theta range:

```bash
python main.py plot-xrd CHY-1038 --xlim 15 75
```

Clip the stacked intensity range:

```bash
python main.py plot-xrd CHY-1038 --ylim 0 auto
```

Use the shared TE plot frame ratio and override trace styling:

```bash
python main.py plot-xrd CHY-1038 \
  --subplot-aspect 10:8 \
  --color '#d62728' --color '#1f77b4' \
  --line-width 1.15
```

Save multiple output formats:

```bash
python main.py plot-xrd CHY-1038 --formats svg png
```

Save PNG plus vector PDF output:

```bash
python main.py plot-xrd CHY-1038 --pdf
```

## Fit XRD Lattice Parameters

Fit lattice parameters for one measured XRD `.xy` file using a PDF-card text export with indexed peaks:

```bash
python main.py xrd-lattice \
  --pdf-card "data/pdf_card/CuInTe2 PDF#97-023-8958.txt" \
  --xrd data/raw/CHY-1038/XRD/CHY-1038-A_XRD.xy \
  --sample-name CHY-1038-A \
  --output-dir results/xrd_lattice
```

Try lattice fitting for every XRD `.xy` file in one raw batch folder:

```bash
batch_id=CHY-1038
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
data/raw/CHY-1038/XRD/CHY-1038-A_XRD.xy
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
python main.py analyze CHY-1048
python main.py plot-te CHY-1048 --seebeck
python main.py plot-xrd CHY-1038
```

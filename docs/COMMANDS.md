# Project Commands

Run commands from the workspace root, in the `teagent` conda environment:

```bash
cd ~/Documents/te-analysis-plotting
conda activate teagent
```

From a non-interactive shell (scripts, agents), use
`conda run --no-capture-output -n teagent python main.py ...` instead.

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

`analyze`, `plot-te`, `assess`, and `agent` have no default batch: name the
batches (or pass `--all` where supported), otherwise they stop with an error.

## Machine-Readable Runs (`--json`)

Put `--json` before the command to get one JSON object on stdout when it
finishes. The tool's own messages move to stderr, so stdout stays parseable:

```bash
python main.py --json assess CHY-1048
python main.py --json plot-te CHY-1048 --zt --no-show
```

```json
{
  "command": "assess",
  "args": ["CHY-1048"],
  "exit_code": 0,
  "ok": true,
  "outputs": [
    {"path": "results/assessments/assessment_CHY-1048_20261123_160501.json", "kind": "json", "exists": true}
  ]
}
```

`outputs` lists every file the command wrote, in write order, with paths
relative to the workspace root (absolute when outside it). `kind` is one of
`figure`, `table`, `json`, `markdown`, `text`, or `file`. This includes shared
metadata such as `data/lab/batches.json` when `analyze` rewrites it.

Tools report a file by calling `te_analysis.run_manifest.record_output(path)`
right after writing it. New tools should do the same.

## Working With the Role Agents (Claude Code)

In Claude Code, three subagents defined in `.claude/agents/` split the work:

| Agent | Handles | Writes |
| --- | --- | --- |
| `te-plotter` | `plot-te`, `plot-xrd`, `flexible` | figures (and new recipes when asked) |
| `te-analyst` | `analyze`, `spb`, `sync` | `data/lab/`, processed data, SPB outputs |
| `te-assessor` | `assess`, `bayes`, `agent` | `results/` reports |

Ask in plain language; Claude delegates by each agent's description, or name
one directly:

```text
Plot zT and Seebeck for CHY-1040 and CHY-1048 in one comparison, and the XRD stack for CHY-1056.
Use te-analyst to process CHY-1060 and CHY-1061.
Have te-assessor compare CHY-1040 and CHY-1048 and suggest the next composition.
```

The agents can work in parallel. The assessor runs `agent` (which sends data
to the Moonshot API) only when you ask for an LLM analysis.

### Running Commands in Parallel

Commands that change `data/lab/` (`analyze`, `sync metadata`, `sync markdown`,
`sync workbook`, `sync fill`) hold a lock while they read, change, and write
it, so parallel runs take turns instead of overwriting each other. A waiting
command prints `Waiting for another command to finish updating ...` and gives
up after 120 s (set `TE_LAB_LOCK_TIMEOUT` to change that). `analyze` holds the
lock only while it syncs metadata, not while it processes data, so analyses of
different batches overlap. Files are swapped in whole, so commands that only
read `data/lab/` (`plot-te`, `assess`) never see a half-written file.

Two limits: don't analyze the same batch twice at once, and the lock covers
one computer only. Running commands on two computers against the
OneDrive-synced folder at the same time can still produce conflict copies such
as `samples-<computer name>.json`.

## How the Launcher Works

The root `main.py` is intentionally a 10-line shim: the actual launcher lives
in `te_analysis/launcher.py` so the installed package owns it. Running
`python main.py <command>` dispatches to the matching entry script. If the
package is installed with `pip install -e .`, the same launcher is also
available as the `te` command (`te plot-te ...`, `te flexible ...`).

Where the plotting implementation now lives (each split from a former
single-file module, with the old module names kept as import shims):

| Area | Package | Entry point |
| --- | --- | --- |
| TE property plots | `te_analysis/tools/te_plotting/` (properties, ledger, locate) | `scripts/plotting/plot_te.py` via `python main.py plot-te` |
| Flexible recipe plots | `te_analysis/tools/flexible/` (util, normalize, style, render, output, cli) | `python main.py flexible` |
| XRD plots | `te_analysis/tools/xrd/` (io, pdf_cards, render) | `scripts/plotting/plot_xrd.py` via `python main.py plot-xrd` |

## Quick Plotting Recipes

The three most common plotting tasks:

```bash
# 1. Plot processed TE properties for a batch (or a direct CSV path)
python main.py plot-te CHY-1048 --zt --no-show
python main.py plot-te path/to/sample.csv --seebeck --conductivity --zt --no-show

# 2. Plot XRD patterns (batch, sample, or a direct .xy file)
python main.py plot-xrd CHY-1056-B --no-show
python main.py plot-xrd path/to/pattern.xy --no-pdf-card --no-show --output-dir out/

# 3. Render a flexible plot recipe
python main.py flexible --recipe configs/plot_recipes/thermoeletric/temperature_vs_zt.json --no-show
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

The selected-batch raw-data workflow is implemented in `scripts/analysis/te_analysis_pipeline.py` and
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

## Run Agent (LLM) Analysis

`python main.py agent` sends a processed batch's `extracted_features.json` to
the model and saves a Markdown mechanism analysis to
`results/reports/<batch>_Analysis.md`. It needs `MOONSHOT_API_KEY` in `.env`.

```bash
python main.py agent CHY-1040 CHY-1038
python main.py agent CHY-1040 --matrix Cu0.8Ag0.2In0.5Ga0.5Te2
python main.py agent data/processed/CHY-1048-processed/extracted_features.json
```

The matrix composition comes from `--matrix`, else `data/lab/batches.json`
(then `configs/lab_batches.json`), else the samples in the features file when
they all agree. A target without one fails instead of being analyzed blind.
The command exits non-zero if any target fails.

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
| `python main.py spb effective-mass ...` aliases: `mass`, `mstar`, `pisarenko` | `te_analysis/tools/spb/effective_mass_fit.py` | `configs/plot_recipes/spb/pisarenko_fit.json` | `effective_mass_points.csv`, `pisarenko_curve.csv`, `fit_summary.json`, `pisarenko_fit.*` |
| `python main.py spb performance ...` aliases: `fitting`, `fit`, `pf`, `zt` | `te_analysis/tools/spb/performance_fit.py` | `pf_fit.json` for `--properties pf`; `zt_fit.json` for `--properties zt` | `performance_points.csv`, `performance_curve.csv`, `performance_summary.json`, `pf_fit.*`, `zt_fit.*` |
| `python main.py spb conductivity ...` aliases: `sigma`, `mobility` | `te_analysis/tools/spb/conductivity_fit.py` | `conductivity_seebeck_fit.json`, `conductivity_pf_fit.json`, `conductivity_zt_fit.json` | `conductivity_points.csv`, `conductivity_curve.csv`, `conductivity_summary.json`, `conductivity_seebeck_fit.*`, `conductivity_pf_fit.*`, `conductivity_zt_fit.*` |

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

Use custom trace labels from a file in the same XRD folder. These labels are
used by both the legend and `--right-labels`. Supported filenames include
`label`, `labels`, `legend`, and `legends`, with optional `.txt`, `.csv`,
`.tsv`, or `.md` suffixes. Put one label per row; CSV/TSV files use the first
column. Labels are applied in sorted `.xy` filename order.

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

Plot two PDF cards by repeating `--pdf-card`. The first card is placed below
all measured XRD traces and the second is placed above them:

```bash
python main.py plot-xrd CHY-1038 \
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
python main.py plot-xrd CHY-1038 \
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
  --line-width 0.9
```

By default, XRD figures omit the conventional legend and PDF-card names, showing
only right-side trace labels. Add `--pdf-labels` to show the PDF-card names. If
the XRD folder contains `label`,
`labels`, `legend`, or `legends` with optional `.txt`, `.csv`, `.tsv`, or `.md`
suffix, labels are applied in sorted `.xy` file order; otherwise the `.xy` file
stems are used. Use `--legend` to restore the conventional legend or
`--no-right-labels` to hide the trace annotations.

```bash
python main.py plot-xrd CHY-1038 --legend --pdf-labels --no-right-labels
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

### Fill Cp and Composition From the Lab Workbook

`sync workbook` reads the batch's sheet in `NU Lab samples lists.xlsx` (looked
up in `data/lab/`, then the workspace root) and fills `cp_value` and
`sample_composition` for the samples already in the metadata:

```bash
python main.py sync workbook CHY-1090 --dry-run   # show the changes
python main.py sync workbook CHY-1090             # write them
```

The sheet must be named after the batch. For each `Sample ID` block the
composition is the cell below the sample ID in column A, and Cp is the value in
column G between 0.05 and 1.5 J/g/K (the other G values are the molar mass and
atoms per formula unit, in either order). Cp is checked against Dulong-Petit
(3R x atoms / molar mass) and written with 9 decimals. Sample IDs from other
batches on the sheet are skipped, and blocks with an empty sample-ID cell are
reported by row rather than guessed. Close the workbook in Excel first: Excel
locks it against reading.

### Set a Field in Sample Order (Density, Labels, ...)

`sync fill` writes one value per sample, in sample-ID order (A, B, C, ...):

```bash
python main.py sync fill CHY-1090 density 5.94 5.97 6.01 5.88 5.90 5.92
python main.py sync fill CHY-1090 density 5.94 6.01 --samples A C
python main.py sync fill CHY-1090 sample_name Ga0.8 Ag_alloy Se_alloy_0.025 --samples A B C
```

The number of values must match the number of samples. Both commands import
your Markdown edits first, then write `samples.json` and re-export
`lab_metadata.md`, changing only the fields they set. If a field already holds a
different value, nothing is written and the command exits 1 so you can check;
add `--overwrite` to replace it. A `sample_name` that is still the raw-scan
placeholder (the sample letter) counts as empty.

New-batch workflow:

```bash
python main.py sync metadata                       # after raw files are in data/raw/CHY-1090/
python main.py sync workbook CHY-1090              # Cp + composition
python main.py sync fill CHY-1090 density 5.94 5.97 6.01 5.88 5.90 5.92
python main.py analyze CHY-1090
```

### Markdown Layout (v2)

`lab_metadata.md` groups records by batch: an Overview table first, then one
`## <batch_id>` section per batch containing the `### Batch` table followed by
its `### Sample` tables. File paths (`Raw:` / `Processed:` lines) are shown as
read-only info; edit paths in JSON or let `sync metadata` manage them.
Deleting a section from the Markdown no longer deletes the JSON record — the
import keeps it and prints a warning. Pass `--prune` to actually delete
records removed from the Markdown.

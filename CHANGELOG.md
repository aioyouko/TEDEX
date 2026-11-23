# Changelog

## Unreleased

- Added `python main.py --json <command> ...`: prints one JSON object on
  stdout with the command, args, exit code, and every file the command wrote
  (`outputs`), and moves the tool's own messages to stderr. Tools report files
  through the new `te_analysis.run_manifest.record_output()`.
- `analyze`, `plot-te`, and `assess` no longer fall back to a hard-coded batch
  (`CHY-1048`, or `CHY-1040 CHY-1048` for `assess`) when none is given; they
  stop with an error instead. `analyze --sample B` without a batch is also an
  error now rather than silently using `CHY-1048`.
- `agent` now takes its targets from the command line (batch IDs or
  `extracted_features.json` paths) instead of two hard-coded batches, finds the
  matrix composition in the lab ledger (or `--matrix`), and exits non-zero when
  a target fails.
- `te_analysis.agents.core_agent` raises `AgentError` on a missing API key, a
  failed call, or an empty reply instead of returning the error text as if it
  were a report.
- The launcher sets `PYTHONIOENCODING=utf-8` for the tools it runs, so piped
  output on Windows no longer crashes on the status symbols.
- Tracked `AGENTS.md` (project rules for agents) and added `CLAUDE.md`, which
  imports it for Claude Code.

## 1.4.2 - 2026-07-16

- Added two-card XRD comparison plots: the first PDF card is placed below the
  measured traces and the second above them. XRD plots now default to right-side
  trace labels without a conventional legend or in-plot PDF-card names; the
  names can be enabled with `--pdf-labels`. Bottom sticks now start at the
  x-axis, top sticks use a black baseline with their
  label above the stick field, both stick fields default to `1.0` of one XRD
  offset step, the bottom card-to-first-trace gap is reduced to `0.25` offset
  step, and the two cards have independently configurable colors.
- Renamed the installable code to a single proper package: `src/` is now
  `te_analysis/`, and `myplotstyle/` moved to `te_analysis/plotstyle/`.
  Previously `pip install` shipped top-level packages named `src`, `scripts`,
  `myplotstyle`, and `main`, which collide with other projects.
- Moved the launcher into `te_analysis/launcher.py`; root `main.py` is now a
  thin shim, so `python main.py ...` works unchanged.
- Renamed `scripts/analysis/te_analysis.py` to
  `scripts/analysis/te_analysis_pipeline.py` to stop it shadowing the new
  package name.
- Updated console scripts: `te` and the three `te-spb-*` entries remain; the
  `te-plot-xrd`, `te-flex-plot`, `te-assess-batches`, `te-bayes-predict`,
  `te-sync-*`, and `te-paper-plots` shortcuts were removed (use the
  equivalent `te <command>` instead).
- Started tracking the project with git; private lab data folders are
  excluded via .gitignore.

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

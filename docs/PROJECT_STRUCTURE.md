# Project Structure

The root directory keeps `main.py` as the thin user-facing launcher shim, while all library logic and CLI entry points live inside the installable `te_analysis/` (`tedex`) package:

| Folder / File | Purpose |
| --- | --- |
| `main.py` | Root launcher shim delegating to `te_analysis.launcher:main`. |
| `te_analysis/` | Self-contained installable Python package (`tedex`). |
| `te_analysis/pipeline/` | Raw ZEM/LFA batch analysis (`analyze`), batch assessment (`assess`), Bayesian GP prediction (`bayes`), and mechanistic AI reports (`agent`). |
| `te_analysis/sync/` | Bidirectional `lab_metadata.md` <-> JSON ledger sync, Notion payload builder, and Excel reference extractor. |
| `te_analysis/tools/` | Core plotting & physics modules (`te_plotting/`, `sciplot/`, `xrd/`, `spb/`, `physics/`, `workspace_init.py`, `legend_layout.py`, `colors.py`, `figure_naming.py`). |
| `te_analysis/plotstyle/` | Publication typography and axis formatting helpers. |
| `te_analysis/paths.py` | Centralized workspace configuration & path resolver (`ENGINE_ROOT` vs `WORKSPACE_ROOT`). |
| `plugin/tedex/` | Standalone Mode-B software-layer plugin (`plugin.json`, generic `rules/AGENTS.md`, and 5 orthogonal skills). |
| `.agents/skills/` | Workspace-level 5 orthogonal skills (`te-workspace`, `te-data-pipeline`, `te-plotting`, `te-xrd`, `te-physics-models`). |
| `scripts/` | Backward-compatible CLI shims and standalone utility/example scripts. |
| `configs/` | `workspace_template.json`, reusable `plot_recipes/`, `sciplot_demos/`, and metadata schema templates. |
| `data/` | Public `demo/` and `pdf_card/` examples; user `raw/`, `processed/`, `metadata/` (`lab/`), and `references/` remain gitignored. |
| `outputs/` | Unified root for generated `figures/`, numeric `models/`, Markdown `reports/`, and disposable `cache/` (gitignored). |
| `docs/` | Command references (`COMMANDS.md`, `SCIPLOT.md`, `COLOR_SETS.md`, `RELEASING.md`). |
| `tests/` | Unit, golden-master, and Mode-B workspace integration tests (`pytest` or `python tests/run_tests.py`). |

## Practical Conventions

1. Execute tools through `python main.py <command> ... --no-show` (or `te <command> ... --no-show` after `pip install -e .`).
2. Keep all installable CLI targets inside `te_analysis/` so standard wheel installations (`pip install .`) work outside the source repository.
3. Resolve workspace directories through `te_analysis/paths.py` (`configs/workspace.json`) rather than hardcoding `data/` or `outputs/` paths.
4. Keep legends inside plot axes by default (`legend_layout.py`) unless `--legend outside` is explicitly requested.
5. Never commit API keys or private measurement files; keep `.env` and local `configs/workspace.json` gitignored.

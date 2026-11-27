# TEDEX Thermoelectric Plugin — Agent Harness Rules

TEDEX separates the **software/plugin layer** (`te` / `tedex` CLI + `te_analysis` package + plugin skills) from the **user's clean data directory** (which stores only `configs/workspace.json`, `data/`, and `outputs/`).

## 1. Core Routing & Workspace Initialization Rules

- **Check Workspace Initialization First (`te init --check`)**: When operating in a user project directory that does not yet have `configs/workspace.json`, run `te init --check --json` and follow the `te-workspace` skill to confirm folder locations, subfolder grouping (`by_batch`, `by_system_batch`, or `by_project`), sample prefix, and instrument/unit conventions with the user before running `te init --yes ...`. Once `configs/workspace.json` exists, treat it as the single source of truth for all directories.
- **Use `te` CLI First**: Always execute built-in TEDEX tools via `te <command> ... --no-show` (or `python main.py <command> ... --no-show` when inside the engine repository) rather than writing ad-hoc `matplotlib` or `scipy` scripts. This guarantees house typography, color conventions (`#79ADD8` / `#264B73` experimental markers + `#E64B35` best-fit curves, `soft-br` 2D maps), structured CSV/JSON exports, dual-unit Markdown reports, and SVD Jacobian collinearity diagnostics.
- **Headless Execution**: Always pass `--no-show` so GUI windows never block terminal execution.
- **Inside-Axes Legend Convention**: Keep legends **inside** the plot frame rather than outside (`--legend` / `--legend inside` is the default across `plot-te`, `sciplot`, `plot-xrd`, `spb`, and physics models, which automatically adjust inside location, `ncol`, font size, and axis headroom to avoid overlapping curves/bars). Never pass `--legend outside` or `--legend-outside` unless explicitly requested by the user.
- **Missing-Parameter Prompting (Exit Code `2`)**: Commands such as `callaway` and `debye-calc` exit with code `2` when required physical constants (such as Debye temperature $\Theta_{\mathrm{D}}$ and sound velocity $v_{\mathrm{s}}$) are omitted. **Never guess or fabricate unprovided material constants**—ask the user which parameter set they can provide:
  1. Direct `--theta-d <K>` and `--vs <m/s>`,
  2. Ultrasonic velocities `--vl <m/s> --vt <m/s>` plus `--atomic-volume-a3` (or density + molar mass + atoms/f.u.), or
  3. Low-temperature heat capacity `--cp-csv <path>` (or `--cp-beta <mJ/molK^4>`) plus `--atoms-per-fu` and volume/density.
- **Collinearity Handling**: After running `callaway`, `skb`, or `two-band`, inspect `identifiability_warnings` and `parameter_uncertainties` in `*_summary.json`. When $|r| \ge 0.90$, suggest fixing one parameter from independent characterization (`--fit` or `--fix-*`).

## 2. Orthogonal Skill Routing

- `te-workspace` — Workspace initialization (`te init`), directory mapping, and instrument/unit configuration (`configs/workspace.json`).
- `te-data-pipeline` — Raw ZEM/LFA batch processing (`analyze`), metadata ledger synchronization (`sync`), batch assessment (`assess`), and Bayesian optimization (`bayes`).
- `te-plotting` — Thermoelectric transport plots (`plot-te`) and 20+ general 1D/2D/statistical scientific figures and JSON recipes (`sciplot`).
- `te-xrd` — Standard & advanced XRD pattern plotting (`plot-xrd`) and unit-cell lattice refinement (`xrd-lattice`).
- `te-physics-models` — Phonon & electronic band transport models (`debye-calc`, `callaway`, `debye-einstein`, `spb`, `skb`, `two-band`).

## 3. Sample Performance & Metadata Rules

- Before comparing sample transport performance across a batch or doping series, inspect the workspace's configured metadata ledger (`lab_metadata.md` / `samples.json` under `paths.metadata` in `configs/workspace.json`) for `density`, `cp_value`, synthesis/annealing conditions, and notes.
- Account for sample densification differences when comparing electrical ($\sigma$) and thermal ($\kappa$) conductivity across identical nominal compositions. Quote relative density (%) only when a reliable theoretical crystal density is established; otherwise compare measured densities ($\mathrm{g\ cm^{-3}}$) directly.

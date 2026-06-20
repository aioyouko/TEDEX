# Project Structure

Version 1.2.0 is a public release rebuilt from the current workspace source while excluding private data and generated outputs.

```text
te-analysis-plotting-v1.2.0/
  run_analysis.py
  plot_te.py
  plot_XRD.py
  flexible_plot.py
  main.py
  assess_selected_batches.py
  bayesian_predict_te.py
  te_analysis.py
  src/
  scripts/
  myplotstyle/
  configs/
  data/
  docs/
  notebooks/
  results/
  outputs/
```

## Included Source

| Path | Purpose |
| --- | --- |
| `src/tools/` | TE data loading, plotting, XRD, flexible plotting, SPB helpers, and shared utilities. |
| `src/agents/` | Optional agent analysis helpers. They read API keys from environment variables or `.env`, which is not included. |
| `scripts/` | Metadata sync, plotting helpers, reference extraction, and demo utilities. |
| `myplotstyle/` | Plot styling helpers. |
| `configs/plot_recipes/` | Reusable flexible plotting recipes. |
| `configs/flexible_plot_demos/` | Recipes wired to included `data/demo/` files. |

## Included Data

Only public demo data are included:

```text
data/demo/
```

Private-data folders are present only as empty placeholders:

```text
data/raw/
data/processed/
data/lab/
data/reference/
data/pdf_card/
results/
outputs/
```

The release `.gitignore` keeps those private/generated folders out of version control while keeping `data/demo/` available.

## Not Included

- `.env` and API keys.
- Private lab metadata JSON/Markdown.
- Raw instrument exports.
- Processed sample CSVs outside `data/demo/`.
- Reference PDF/data libraries.
- Generated reports, plots, caches, and notebook checkpoints.
- Local `skills/` and `external/` folders.

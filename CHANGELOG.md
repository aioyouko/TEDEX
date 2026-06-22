# Changelog

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
- Included current root entry scripts, `src/agents`, `src/tools`, `scripts`, `myplotstyle`, docs, and public plotting recipes.
- Included only public demo data under `data/demo/`; private raw, processed, lab, reference, result, and output folders are empty placeholders.
- Added `te-flex-plot`, `te-assess-batches`, and `te-bayes-predict` console entry points.
- Added README gallery images copied from `data/demo/`.

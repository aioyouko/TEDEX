# Changelog

## 1.1.0

- Added XRD plotting to the release package via `plot_XRD.py` and `src/tools/plot_XRD_data.py`.
- Added stacked raw-count and normalized XRD plotting, selected-sample filtering, separate per-sample XRD plots, and optional PDF-card stick overlays.
- Added `te-plot-xrd` console entry point.
- Added XRD data layout documentation and synthetic demo XRD files.
- Lattice-parameter fitting is intentionally not included in this release.

## 1.0.0

- Packaged the TE raw-data analysis workflow into a standalone GitHub-ready folder.
- Included raw ZEM/LFA parsing, processed CSV generation, SPB-derived transport columns, feature extraction, and publication-style plotting.
- Added metadata sync tools for `data/lab/batches.json`, `data/lab/samples.json`, and editable `data/lab/lab_metadata.md`.
- Added room-temperature dual-axis and paper-style plotting helper scripts.
- Added empty project templates plus a small synthetic demo project.

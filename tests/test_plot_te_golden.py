"""End-to-end test for plot-te using a synthetic processed-style CSV.

plot-te accepts a direct CSV path selector and writes figures beside the
input, so this runs fully self-contained in a temp directory. It pins the
CLI contract: exit code, figure output location, and produced filenames.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from _helpers import run_cli

CSV_HEADER = "Temperature,Seebeck,Conductivity,Thermal_Conductivity,ZT"


def _write_synthetic_csv(directory: Path) -> Path:
    rows = [CSV_HEADER]
    for i, temperature in enumerate(range(300, 750, 50)):
        seebeck = 120e-6 + i * 8e-6
        conductivity = 90000 - i * 6000
        kappa = 1.4 - i * 0.05
        zt = seebeck * seebeck * conductivity * temperature / kappa
        rows.append(f"{temperature},{seebeck},{conductivity},{kappa},{zt}")
    path = directory / "demo_sample.csv"
    path.write_text("\n".join(rows) + "\n")
    return path


def test_plot_te_direct_csv_zt():
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = _write_synthetic_csv(Path(tmp))
        result = run_cli(["plot-te", str(csv_path), "--zt", "--no-show"])
        assert result.returncode == 0, (result.stderr or result.stdout)[-2000:]
        figures = sorted((Path(tmp) / "figures").rglob("*.svg"))
        assert figures, "no figure produced beside the input CSV"


def test_plot_te_direct_csv_multi_property():
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = _write_synthetic_csv(Path(tmp))
        result = run_cli(
            [
                "plot-te",
                str(csv_path),
                "--seebeck",
                "--conductivity",
                "--zt",
                "--no-show",
            ]
        )
        assert result.returncode == 0, (result.stderr or result.stdout)[-2000:]
        figures = sorted((Path(tmp) / "figures").rglob("*.svg"))
        assert len(figures) >= 3, f"expected >=3 figures, got {figures}"

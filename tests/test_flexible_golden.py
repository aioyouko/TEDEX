"""Golden-master tests for the flexible plotting pipeline.

Runs every public demo recipe end to end and compares the normalized CSV
against a stored baseline. Together the recipes cover line, scatter, bar,
grouped-bar, dual-axis, and multi-panel rendering plus CSV/TXT/XLSX and
multi-file inputs.

Missing baselines are captured on first run (test skips), so run the suite
once to record baselines before refactoring.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from _helpers import GOLDEN_DIR, REPO_ROOT, run_cli, skip

RECIPE_DIR = REPO_ROOT / "configs" / "flexible_plot_demos"

RECIPES = [
    "composition_grouped_bar",
    "composition_scatter",
    "pbse_tec_dtmax_txt",
    "pbse_tec_qc_excel_multicolumn",
    "pbse_tec_qc_multi_files",
    "room_temp_dual_axis",
    "temperature_multi_panel",
    "temperature_seebeck_line",
]


def _run_recipe(name: str):
    recipe = RECIPE_DIR / f"{name}.json"
    assert recipe.exists(), recipe
    with tempfile.TemporaryDirectory() as tmp:
        result = run_cli(
            [
                "flexible",
                "--recipe",
                str(recipe),
                "--output-dir",
                tmp,
                "--no-copy-to-data-dir",
                "--no-show",
            ]
        )
        assert result.returncode == 0, result.stderr[-2000:]

        produced = sorted(Path(tmp).glob("*_normalized.csv"))
        assert produced, f"no normalized CSV produced for {name}"
        assert sorted(Path(tmp).glob("*.png")), f"no PNG produced for {name}"

        content = produced[0].read_text()
        golden = GOLDEN_DIR / f"flexible_{name}_normalized.csv"
        if not golden.exists():
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy(produced[0], golden)
            skip(f"baseline captured: {golden.name} — rerun to compare")
        assert content == golden.read_text(), (
            f"{name}: normalized CSV differs from golden baseline"
        )


def test_flexible_composition_grouped_bar():
    _run_recipe("composition_grouped_bar")


def test_flexible_composition_scatter():
    _run_recipe("composition_scatter")


def test_flexible_pbse_tec_dtmax_txt():
    _run_recipe("pbse_tec_dtmax_txt")


def test_flexible_pbse_tec_qc_excel_multicolumn():
    _run_recipe("pbse_tec_qc_excel_multicolumn")


def test_flexible_pbse_tec_qc_multi_files():
    _run_recipe("pbse_tec_qc_multi_files")


def test_flexible_room_temp_dual_axis():
    _run_recipe("room_temp_dual_axis")


def test_flexible_temperature_multi_panel():
    _run_recipe("temperature_multi_panel")


def test_flexible_temperature_seebeck_line():
    _run_recipe("temperature_seebeck_line")

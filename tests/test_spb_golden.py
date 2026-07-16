"""Golden-master tests for the three SPB fitting workflows.

Each test runs the documented demo command with outputs redirected to a
temp directory, then compares every numeric value in the summary JSON
against a stored baseline (relative tolerance 1e-5).

Baselines are captured automatically on the first run (test is skipped),
so run the suite once BEFORE refactoring to record them. Requires scipy;
tests are skipped where scipy is unavailable.

Demo inputs are copied to the temp directory first because SPB commands
also write figures beside the input CSV — this keeps data/demo/ pristine.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from _helpers import GOLDEN_DIR, REPO_ROOT, assert_close, run_cli, skip

DEMO = REPO_ROOT / "data" / "demo" / "spb_fitting"

CASES = {
    "effective_mass": {
        "inputs": ["Ag2Se/Ag2Se_series.csv", "Ag2Se/Ag2Se_params.csv"],
        "args": lambda tmp: [
            "spb", "effective-mass", str(tmp / "Ag2Se_series.csv"),
            "--group-by", "curve_id",
            "--params", str(tmp / "Ag2Se_params.csv"),
            "--formats", "png",
            "--no-show", "--output-dir",
        ],
        "summary_glob": "**/*summary*.json",
    },
    "performance": {
        "inputs": ["Ag2Se/Ag2Se_series.csv", "Ag2Se/Ag2Se_params.csv"],
        "args": lambda tmp: [
            "spb", "performance", str(tmp / "Ag2Se_series.csv"),
            "--group-by", "curve_id",
            "--params", str(tmp / "Ag2Se_params.csv"),
            "--properties", "pf", "zt",
            "--kL", "0.5",
            "--formats", "png",
            "--no-show", "--output-dir",
        ],
        "summary_glob": "**/*summary*.json",
    },
    "conductivity": {
        "inputs": ["Cu2SSeTe/900K.csv"],
        "args": lambda tmp: [
            "spb", "conductivity", str(tmp / "900K.csv"),
            "--sigma-unit", "S/cm",
            "--properties", "seebeck", "pf", "zt",
            "--kL", "0.5",
            "--formats", "png",
            "--no-show", "--output-dir",
        ],
        "summary_glob": "**/*summary*.json",
    },
}


def _require_scipy():
    try:
        import scipy  # noqa: F401
    except ImportError:
        skip("scipy not installed in this environment")


def _run_case(name: str):
    _require_scipy()
    case = CASES[name]
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        for rel in case["inputs"]:
            shutil.copy(DEMO / rel, tmp / Path(rel).name)
        out_dir = tmp / "out"
        result = run_cli(case["args"](tmp) + [str(out_dir)])
        assert result.returncode == 0, (result.stderr or result.stdout)[-2000:]

        summaries = sorted(out_dir.glob(case["summary_glob"]))
        assert summaries, f"no summary JSON produced under {out_dir}"
        actual = {p.name: json.loads(p.read_text()) for p in summaries}

        golden_path = GOLDEN_DIR / f"spb_{name}_summary.json"
        if not golden_path.exists():
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            golden_path.write_text(json.dumps(actual, indent=1, sort_keys=True))
            skip(f"baseline captured: {golden_path.name} — rerun to compare")

        expected = json.loads(golden_path.read_text())
        assert_close(actual, expected, path=name)


def test_spb_effective_mass_fit():
    _run_case("effective_mass")


def test_spb_performance_fit():
    _run_case("performance")


def test_spb_conductivity_fit():
    _run_case("conductivity")

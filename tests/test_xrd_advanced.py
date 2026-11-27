"""End-to-end tests for advanced XRD figure types:
zoom-stack, vt-map, vt-stack, rietveld, peak-fit, and williamson-hall.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from _helpers import run_cli


def _make_vt_xy_folder(folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    x = np.linspace(15.0, 70.0, 1400)
    temps = [300, 400, 500, 600, 700]
    for tk in temps:
        shift = -0.0012 * (tk - 300.0)
        split = max(0.0, 0.36 * (1.0 - (tk - 300.0) / 340.0))
        y = 35.0 + 5.0 * np.sin(x * 0.1)
        for cen, amp, w in (
            (27.55 + shift, 1000.0, 0.14),
            (45.40 + shift - split / 2.0, 520.0, 0.16),
            (45.40 + shift + split / 2.0, 480.0, 0.16),
            (53.85 + shift, 340.0, 0.18),
        ):
            y = y + amp * np.exp(-0.5 * ((x - cen) / (w / 2.355)) ** 2)
        lines = [f"{xv:.4f} {yv:.2f}" for xv, yv in zip(x, y)]
        (folder / f"sample_{tk}K.xy").write_text("\n".join(lines) + "\n", encoding="utf-8")

    card = folder / "ref_card.csv"
    pd.DataFrame(
        {
            "label": ["CuInTe2"] * 4,
            "two_theta_deg": [27.55, 45.22, 45.58, 53.85],
            "intensity": [100, 55, 50, 35],
            "h": [1, 2, 2, 3],
            "k": [1, 0, 2, 1],
            "l": [2, 4, 0, 2],
        }
    ).to_csv(card, index=False)
    return folder, card


def test_xrd_vt_map_vt_stack_and_zoom():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        vt_dir, card = _make_vt_xy_folder(tmp_path / "vt_xrd")

        # 1. VT 2D Map
        out_map = tmp_path / "out_map"
        res_map = run_cli(
            [
                "plot-xrd",
                str(vt_dir),
                "--vt-map",
                "--pdf-card",
                str(card),
                "--transition-temp",
                "620",
                "--formats",
                "png",
                "--output-dir",
                str(out_map),
                "--no-show",
            ]
        )
        assert res_map.returncode == 0, res_map.stderr or res_map.stdout
        assert sorted(out_map.rglob("*_XRD_vt_map.png"))

        # 2. VT Gradient Stack
        out_stack = tmp_path / "out_vt_stack"
        res_stack = run_cli(
            [
                "plot-xrd",
                str(vt_dir),
                "--vt-stack",
                "--pdf-card",
                str(card),
                "--guide-2theta",
                "27.55",
                "45.40",
                "--formats",
                "png",
                "--output-dir",
                str(out_stack),
                "--no-show",
            ]
        )
        assert res_stack.returncode == 0, res_stack.stderr or res_stack.stdout
        assert sorted(out_stack.rglob("*_XRD_vt_stack.png"))

        # 3. Dual-panel Zoom Stack
        out_zoom = tmp_path / "out_zoom"
        res_zoom = run_cli(
            [
                "plot-xrd",
                str(vt_dir),
                "--zoom",
                "44.4",
                "46.4",
                "--pdf-card",
                str(card),
                "--formats",
                "png",
                "--output-dir",
                str(out_zoom),
                "--no-show",
            ]
        )
        assert res_zoom.returncode == 0, res_zoom.stderr or res_zoom.stdout
        assert sorted(out_zoom.rglob("*_XRD_zoom.png"))


def test_xrd_rietveld_peak_fit_and_williamson_hall():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        vt_dir, card = _make_vt_xy_folder(tmp_path / "fit_xrd")
        xy_300 = vt_dir / "sample_300K.xy"

        # 4. Pseudo-Voigt Peak Fit
        out_pf = tmp_path / "out_pf"
        res_pf = run_cli(
            [
                "plot-xrd",
                str(xy_300),
                "--peak-fit",
                "--xlim",
                "44.5",
                "46.3",
                "--formats",
                "png",
                "--output-dir",
                str(out_pf),
                "--no-show",
            ]
        )
        assert res_pf.returncode == 0, res_pf.stderr or res_pf.stdout
        assert sorted(out_pf.rglob("*_XRD_peak_fit.png"))
        assert sorted(out_pf.rglob("*_peaks.csv"))

        # 5. Williamson-Hall Fit
        out_wh = tmp_path / "out_wh"
        res_wh = run_cli(
            [
                "plot-xrd",
                str(xy_300),
                "--williamson-hall",
                "--pdf-card",
                str(card),
                "--instr-fwhm",
                "0.05",
                "--formats",
                "png",
                "--output-dir",
                str(out_wh),
                "--no-show",
            ]
        )
        assert res_wh.returncode == 0, res_wh.stderr or res_wh.stdout
        assert sorted(out_wh.rglob("*_XRD_williamson_hall.png"))

        # 6. Rietveld Refinement Plot
        x = np.linspace(15.0, 70.0, 1100)
        calc = 30.0 + 900.0 * np.exp(-0.5 * ((x - 27.55) / 0.08) ** 2) + 460.0 * np.exp(-0.5 * ((x - 45.4) / 0.10) ** 2)
        rng = np.random.default_rng(42)
        obs = calc + rng.normal(0.0, 8.5, size=len(x))
        prof_csv = tmp_path / "rietveld_profile.csv"
        pd.DataFrame({"2theta": x, "obs": obs, "calc": calc, "diff": obs - calc}).to_csv(prof_csv, index=False)

        out_riet = tmp_path / "out_riet"
        res_riet = run_cli(
            [
                "plot-xrd",
                str(prof_csv),
                "--rietveld",
                "--pdf-card",
                str(card),
                "--formula",
                "$\\mathrm{CuInTe_2}$",
                "--cell-text",
                "$a = 6.194$ Å, $c = 12.418$ Å",
                "--zoom",
                "44.2",
                "46.6",
                "--formats",
                "png",
                "--output-dir",
                str(out_riet),
                "--no-show",
            ]
        )
        assert res_riet.returncode == 0, res_riet.stderr or res_riet.stdout
        assert sorted(out_riet.rglob("*_XRD_rietveld.png"))

"""
Example: fit lattice parameters for CHY-1038-A using the CuInTe2 PDF card.

Run from the repository root:

    python src/tools/example_xrd_lattice_fit.py
"""

from __future__ import annotations

from pathlib import Path

try:
    from src.tools.xrd_lattice import run_lattice_fit
except ModuleNotFoundError:
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    from src.tools.xrd_lattice import run_lattice_fit


REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_CARD = REPO_ROOT / "data/pdf_card/CuInTe2 PDF#97-023-8958.txt"
XRD_FILE = REPO_ROOT / "data/raw/CHY-1038/XRD/CHY-1038-A_XRD.xy"
OUTPUT_DIR = REPO_ROOT / "results/xrd_lattice"


def main() -> int:
    result = run_lattice_fit(
        pdf_card_path=PDF_CARD,
        xrd_path=XRD_FILE,
        output_dir=OUTPUT_DIR,
        sample_name="CHY-1038-A",
        match_tolerance_deg=0.8,
        min_reference_intensity=2.0,
        peak_prominence_fraction=0.015,
    )

    cell = result["lattice_parameters"]
    print("CHY-1038-A lattice fit from CuInTe2 reference card")
    print(f"a     = {cell['a_angstrom']:.5f} A")
    print(f"b     = {cell['b_angstrom']:.5f} A")
    print(f"c     = {cell['c_angstrom']:.5f} A")
    print(f"alpha = {cell['alpha_deg']:.4f} deg")
    print(f"beta  = {cell['beta_deg']:.4f} deg")
    print(f"gamma = {cell['gamma_deg']:.4f} deg")
    print(f"matched peaks = {result['fit_model']['matched_peak_count']}")
    print(f"RMS 2-theta residual = {result['fit_model']['rms_two_theta_deg']:.4f} deg")
    print(f"JSON result = {result['output_files']['lattice_fit_json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

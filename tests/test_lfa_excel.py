"""Exercise Excel LFA ingestion and raw-file discovery without lab data writes."""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.sync_lab_metadata import discover_raw_samples
from te_analysis.tools.te_data import load_lfa


def test_xlsx_skips_exactly_one_row_and_matches_csv():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        excel_path = root / "sample_LFA.XLSX"
        # A numeric first row must still be ignored. Extra columns and sheets
        # must not affect the temperature/diffusivity values.
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            pd.DataFrame([
                [999, 999, "ignored first row"],
                [25, 1.2, 100],
                [100, 1.5, 200],
                [None, None, "blank"],
                ["note", "invalid", 300],
                [200, 1.8, 400],
            ]).to_excel(writer, index=False, header=False, sheet_name="LFA")
            pd.DataFrame([[800, 50]]).to_excel(
                writer, index=False, header=False, sheet_name="Other",
            )
        csv_path = root / "sample_LFA.csv"
        csv_path.write_text("Temperature,Diffusivity\n25,1.2\n100,1.5\n200,1.8\n")
        actual = load_lfa(excel_path)
        assert actual is not None
        np.testing.assert_allclose(actual["Temperature_LFA"], [298.15, 373.15, 473.15])
        np.testing.assert_allclose(actual["Diffusivity"], [1.2, 1.5, 1.8])
        pd.testing.assert_frame_equal(actual, load_lfa(csv_path))


def test_xlsx_without_numeric_pairs_is_rejected():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "empty_LFA.xlsx"
        pd.DataFrame([["Temperature", "Diffusivity"], ["note", None]]).to_excel(
            path, index=False, header=False,
        )
        assert load_lfa(path) is None


def test_instrument_csv_mean_rows_still_load():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sample_LFA.csv"
        path.write_text(
            "Instrument report\n#Mean,25,unused,1.2\n#Mean,100,unused,1.5\n"
        )
        actual = load_lfa(path)
        assert actual is not None
        np.testing.assert_allclose(actual["Temperature_LFA"], [298.15, 373.15])
        np.testing.assert_allclose(actual["Diffusivity"], [1.2, 1.5])


def test_discovery_accepts_lfa_excel_and_ignores_lock_files():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        batch = root / "TE-9999"
        batch.mkdir()
        for name in (
            "TE-9999-A_ZEM.txt", "TE-9999-A_LFA.XLSX",
            "TE-9999-B_LFA.csv", "TE-9999-C_ZEM.xlsx",
            "~$TE-9999-A_LFA.xlsx",
        ):
            (batch / name).touch()
        actual = discover_raw_samples(root)
        assert set(actual) == {"TE-9999-A", "TE-9999-B"}
        assert actual["TE-9999-A"]["lfa"] == (batch / "TE-9999-A_LFA.XLSX").as_posix()
        assert actual["TE-9999-A"]["zem"] == (batch / "TE-9999-A_ZEM.txt").as_posix()
        assert actual["TE-9999-B"]["lfa"] == (batch / "TE-9999-B_LFA.csv").as_posix()

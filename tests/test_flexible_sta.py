"""STA recipe coverage for NETZSCH-style ANSI CSV exports."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from _helpers import REPO_ROOT, run_cli


def write_netzsch_csv(path: Path, header: str, rows: list[str], metadata_rows: int) -> None:
    metadata = [f"#META {index}:,value" for index in range(metadata_rows)]
    text = "\r\n".join([*metadata, "", header, *rows, ""])
    path.write_bytes(text.encode("latin1"))


def test_sta_recipe_reads_ansi_dynamic_headers_and_dta_unit_variants():
    recipe = REPO_ROOT / "configs" / "plot_recipes" / "sta" / "temperature_vs_dta.json"
    assert recipe.exists(), recipe

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        first = tmp_path / "sample-a-heating.csv"
        second = tmp_path / "sample-d-heating.csv"
        output_dir = tmp_path / "figures"

        write_netzsch_csv(
            first,
            "##Temp./°C,DTA/(µV/mg)",
            ["400,0.2", "450,-0.5"],
            metadata_rows=3,
        )
        write_netzsch_csv(
            second,
            "##Temp./°C,Time/min,DTA/(uV/mg),Sensit./(uV/mW)",
            ["405,1,0.1,1", "455,2,-0.4,1"],
            metadata_rows=5,
        )

        result = run_cli(
            [
                "sciplot",
                str(first),
                str(second),
                "--recipe",
                str(recipe),
                "--output-dir",
                str(output_dir),
                "--formats",
                "png",
                "--no-copy-to-data-dir",
                "--no-show",
            ]
        )
        assert result.returncode == 0, result.stderr[-2000:]

        normalized_files = list(output_dir.glob("*_normalized.csv"))
        assert len(normalized_files) == 1
        normalized = pd.read_csv(normalized_files[0], keep_default_na=False)
        assert len(normalized) == 4
        assert set(normalized["source"]) == {first.name, second.name}
        assert set(normalized["property"]) == {"dta"}
        assert set(normalized["marker"]) == {"None"}
        assert list(output_dir.glob("*.png"))

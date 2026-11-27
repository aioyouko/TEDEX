"""Regression coverage for figure names shared by every plotting command.

Inputs and figure exports stay in temporary directories. No pytest fixtures
are required, so these also run with ``python tests/run_tests.py figure_rename``.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from _helpers import REPO_ROOT, run_cli, skip

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from te_analysis.tools.figure_naming import (
    add_rename_argument,
    figure_output_naming,
    next_figure_stem,
)
from te_analysis.tools.plot import save_figure, save_figure_outputs


def _assert_cli_ok(result):
    assert result.returncode == 0, (result.stderr + result.stdout)[-4000:]
    assert "Traceback" not in result.stderr


def _assert_exports(directory: Path, stems: list[str], formats: tuple[str, ...]):
    expected = {f"{stem}.{fmt}" for stem in stems for fmt in formats}
    actual = [path for path in directory.rglob("*") if path.suffix.lstrip(".") in formats]
    assert {path.name for path in actual} == expected, [str(path) for path in actual]
    assert len(actual) == len(expected), [str(path) for path in actual]
    assert all(path.stat().st_size > 100 for path in actual)
    return {path.name: path for path in actual}


def _assert_copies_match(originals, copies):
    assert originals.keys() == copies.keys()
    for name, original in originals.items():
        assert original.read_bytes() == copies[name].read_bytes(), name


def _write_xrd_inputs(directory: Path):
    directory.mkdir()
    for index in range(1, 4):
        (directory / f"scan-{index}.xy").write_text(
            f"10 {index}\n20 {10 + index}\n30 {2 * index}\n40 {index}\n",
            encoding="utf-8",
        )
    (directory / "legend.txt").write_text("LABEL_ONE\nLABEL_TWO\nLABEL_THREE\n", encoding="utf-8")


def _write_te_input(directory: Path) -> Path:
    directory.mkdir()
    path = directory / "synthetic_te.csv"
    path.write_text(
        "Temperature,Seebeck,Conductivity,Thermal_Conductivity,ZT\n"
        "300,0.00012,90000,1.4,0.278\n"
        "400,0.00014,80000,1.3,0.482\n"
        "500,0.00016,70000,1.2,0.747\n"
        "600,0.00018,60000,1.1,1.060\n",
        encoding="utf-8",
    )
    return path


def test_figure_rename_sequence_resets_and_restores_after_exception():
    assert next_figure_stem("original") == "original"
    with figure_output_naming("[1].svg"):
        assert next_figure_stem("first") == "[1]"
        try:
            with figure_output_naming("sample.pdf"):
                assert next_figure_stem("nested") == "sample"
                assert next_figure_stem("nested_again") == "sample_2"
                raise RuntimeError("exercise cleanup")
        except RuntimeError:
            pass
        assert next_figure_stem("second") == "[2]"
        with figure_output_naming(None):
            assert next_figure_stem("original_inner") == "original_inner"
        assert next_figure_stem("third") == "[3]"
    assert next_figure_stem("original_after") == "original_after"
    with figure_output_naming("[1]"):
        assert next_figure_stem("new_invocation") == "[1]"


def test_figure_rename_exports_share_stem_and_return_actual_paths():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fig, ax = plt.subplots(figsize=(2, 2))
        ax.plot([0, 1], [1, 2])
        try:
            with figure_output_naming("[1].svg"):
                first = save_figure_outputs(fig, "original.png", root, formats=["svg", "pdf"])
                second = save_figure_outputs(fig, "other.png", root, formats=["svg", "pdf"])
                legacy = save_figure(fig, "legacy.png", root, formats=["svg", "pdf"])
            assert [Path(path).name for path in first] == ["[1].svg", "[1].pdf"]
            assert [Path(path).name for path in second] == ["[2].svg", "[2].pdf"]
            assert Path(legacy).name == "[3].svg"
            _assert_exports(root, ["[1]", "[2]", "[3]"], ("svg", "pdf"))
            assert not list(root.glob("*.png"))
        finally:
            plt.close(fig)


def test_figure_rename_does_not_change_formats_or_default_names():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fig, ax = plt.subplots(figsize=(2, 2))
        ax.plot([0, 1], [1, 2])
        try:
            with figure_output_naming("sample.svg"):
                explicit = save_figure_outputs(fig, "old.png", root, formats=["pdf"])
                inferred = save_figure_outputs(fig, "old.pdf", root)
            assert [Path(path).name for path in explicit] == ["sample.pdf"]
            assert [Path(path).name for path in inferred] == ["sample_2.pdf"]
            unchanged = save_figure_outputs(fig, "original.svg", root, formats=["svg", "pdf"])
            assert [Path(path).name for path in unchanged] == ["original.svg", "original.pdf"]
            assert not (root / "sample.svg").exists()
            assert all(Path(path).exists() for path in explicit + inferred + unchanged)
        finally:
            plt.close(fig)


def test_figure_rename_rejects_paths_blank_names_and_control_characters():
    parser = argparse.ArgumentParser()
    add_rename_argument(parser)
    assert parser.parse_args([]).rename is None
    assert parser.parse_args(["--rename", "[1].svg"]).rename == "[1].svg"
    invalid_names = (
        "", " ", ".", "..", ".svg", "../figure.svg", "folder/figure",
        "folder\\figure", "bad\nname", "bad\tname", "bad\x00name", "figure\n",
    )
    for value in invalid_names:
        try:
            with figure_output_naming(value):
                pass
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid figure name accepted: {value!r}")
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                parser.parse_args(["--rename", value])
            except SystemExit as exc:
                assert exc.code == 2
            else:
                raise AssertionError(f"invalid CLI name accepted: {value!r}")
    assert next_figure_stem("unchanged") == "unchanged"


def test_figure_rename_is_exposed_by_all_plot_command_help():
    commands = (
        ["plot-te"], ["plot-xrd"], ["flexible"],
        ["spb", "effective-mass"], ["spb", "performance"], ["spb", "conductivity"],
        ["analyze"], ["bayes"], ["demo", "paper-te"],
    )
    for command in commands:
        result = run_cli([*command, "--help"])
        _assert_cli_ok(result)
        assert "--rename" in result.stdout, command
    for script in (
        "scripts/plotting/preview_color_sets.py",
        "scripts/analysis/fit_ftir_bandgap.py",
        "scripts/analysis/compare_ftir_bandgaps.py",
        "scripts/analysis/compare_ftir_gap_methods.py",
    ):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / script), "--help"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
        _assert_cli_ok(result)
        assert "--rename" in result.stdout, script


def test_figure_rename_xrd_both_modes_and_data_copies_keep_selected_legends():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = root / "patterns"
        _write_xrd_inputs(data)
        out = root / "exports"
        result = run_cli([
            "plot-xrd", str(data), "--pick", "13", "--both", "--legend",
            "--rename", "[1].svg", "--formats", "svg", "pdf",
            "--output-dir", str(out), "--data-figures", "--no-show",
        ])
        _assert_cli_ok(result)
        exports = _assert_exports(out, ["[1]", "[2]"], ("svg", "pdf"))
        copies = _assert_exports(data / "figures", ["[1]", "[2]"], ("svg", "pdf"))
        _assert_copies_match(exports, copies)
        for name in ("[1].svg", "[2].svg"):
            svg = exports[name].read_text(encoding="utf-8")
            assert "LABEL_ONE" in svg and "LABEL_THREE" in svg
            assert "LABEL_TWO" not in svg
        assert "[1].svg" in result.stdout and "[2].svg" in result.stdout


def test_figure_rename_xrd_separate_figures_share_one_sequence():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = root / "patterns"
        _write_xrd_inputs(data)
        out = root / "exports"
        result = run_cli([
            "plot-xrd", str(data), "--pick", "13", "--both", "--layout", "separate",
            "--rename", "[1]", "--formats", "svg", "--output-dir", str(out), "--no-show",
        ])
        _assert_cli_ok(result)
        exports = _assert_exports(out, ["[1]", "[2]", "[3]", "[4]"], ("svg",))
        for path in exports.values():
            svg = path.read_text(encoding="utf-8")
            assert "LABEL_TWO" not in svg
            assert sum(label in svg for label in ("LABEL_ONE", "LABEL_THREE")) == 1


def test_figure_rename_te_multi_property_and_data_copies():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = root / "data"
        source = _write_te_input(data)
        # Run the same plot-te entry point from a temporary working directory:
        # its central outputs/figures path is relative to the working directory.
        env = os.environ.copy()
        env["MPLBACKEND"] = "Agg"
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts/plotting/plot_te.py"), str(source),
             "--seebeck", "--conductivity", "--zt", "--rename", "sample.svg",
             "--formats", "svg", "pdf", "--no-show"],
            cwd=root, env=env, capture_output=True, text=True, timeout=120,
        )
        _assert_cli_ok(result)
        exports = _assert_exports(root / "outputs/figures", ["sample", "sample_2", "sample_3"], ("svg", "pdf"))
        copies = _assert_exports(data / "figures", ["sample", "sample_2", "sample_3"], ("svg", "pdf"))
        _assert_copies_match(exports, copies)
        assert not list(root.rglob("*.png"))


def test_figure_rename_flexible_multiple_recipes_paths_copies_and_csv_names():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = root / "data"
        data.mkdir()
        source = data / "series.csv"
        source.write_text("Temperature,Seebeck\n300,120\n400,145\n500,170\n", encoding="utf-8")
        out = root / "exports"
        recipes = []
        for index in (1, 2):
            recipe = {
                "name": f"recipe_{index}",
                "data": [{"path": str(source)}],
                "plot": {
                    "kind": "line", "x": {"column": "Temperature"},
                    "series": [{"column": "Seebeck", "property": "seebeck", "label": "Sample"}],
                },
                "output": {"stem": f"recipe_{index}", "normalized_csv": True},
            }
            path = root / f"recipe_{index}.json"
            path.write_text(json.dumps(recipe), encoding="utf-8")
            recipes.extend(["--recipe", str(path)])
        result = run_cli([
            "flexible", *recipes, "--output-dir", str(out), "--formats", "svg", "pdf",
            "--rename", "[1].svg", "--copy-to-data-dir", "--no-show",
        ])
        _assert_cli_ok(result)
        exports = _assert_exports(out, ["[1]", "[2]"], ("svg", "pdf"))
        copies = _assert_exports(data, ["[1]", "[2]"], ("svg", "pdf"))
        _assert_copies_match(exports, copies)
        decoder = json.JSONDecoder()
        reports = [decoder.raw_decode(result.stdout[match.start():])[0]
                   for match in re.finditer(r"(?m)^\{", result.stdout)]
        assert len(reports) == 2, result.stdout
        for index, report in enumerate(reports, 1):
            assert [Path(path).name for path in report["figures"]] == [f"[{index}].svg", f"[{index}].pdf"]
            assert all(Path(path).exists() for path in report["figures"] + report["data_dir_copies"])
            normalized = Path(report["normalized_csv"])
            assert normalized.name == f"recipe_{index}_normalized.csv"
            assert normalized.exists()
            assert (data / normalized.name).read_bytes() == normalized.read_bytes()
        assert {path.name for path in out.glob("*_normalized.csv")} == {
            "recipe_1_normalized.csv", "recipe_2_normalized.csv",
        }


def test_figure_rename_spb_effective_mass_returned_paths_and_data_copies():
    try:
        import scipy  # noqa: F401
    except ImportError:
        skip("scipy not installed in this environment")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = root / "data"
        data.mkdir()
        source = data / "series.csv"
        shutil.copy(REPO_ROOT / "data/demo/spb_fitting/Ag2Se/Ag2Se_series.csv", source)
        out = root / "exports"
        result = run_cli([
            "spb", "effective-mass", str(source), "--only", "Ag2Se", "--m", "1.2",
            "--formats", "svg", "pdf", "--rename", "[1].svg",
            "--output-dir", str(out), "--no-show",
        ])
        _assert_cli_ok(result)
        figures = sorted(out.rglob("*.svg"))
        assert figures
        stems = [f"[{index}]" for index in range(1, len(figures) + 1)]
        exports = _assert_exports(out, stems, ("svg", "pdf"))
        # Group plots stay with each generated group input; only the combined
        # plot is copied beside the original source CSV.
        combined = {name: path for name, path in exports.items() if path.parent == out}
        assert combined
        combined_stems = sorted({path.stem for path in combined.values()})
        copies = _assert_exports(data, combined_stems, ("svg", "pdf"))
        _assert_copies_match(combined, copies)
        assert list(out.rglob("fit_summary.json"))
        assert list(out.rglob("pisarenko_curve.csv"))
        assert all(name in result.stdout for name in combined)

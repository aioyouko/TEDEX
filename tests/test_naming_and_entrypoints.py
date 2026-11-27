"""Regression tests for TEDEX 1.5.0 module naming, CLI entrypoints, shims, and 5-skill layout."""

from __future__ import annotations

import json
import re
from pathlib import Path

from _helpers import REPO_ROOT, run_cli


def test_all_launcher_targets_live_inside_installable_te_analysis_package():
    from te_analysis import launcher

    pkg_root = (REPO_ROOT / "te_analysis").resolve()
    all_cmds = [
        *launcher.DIRECT_COMMANDS,
        *launcher.SPB_COMMANDS,
        *launcher.BAND_COMMANDS,
        *launcher.MODEL_COMMANDS,
        *launcher.SYNC_COMMANDS,
        *launcher.DEMO_COMMANDS,
    ]
    for cmd in all_cmds:
        target = cmd.target.resolve()
        assert target.is_file(), f"Missing launcher target for {cmd.name}: {target}"
        assert pkg_root in target.parents, (
            f"Command {cmd.name} points outside installable te_analysis/ package: {target}"
        )


def test_sciplot_and_lorenz_modules_preserve_backward_compatible_import_shims():
    import te_analysis.tools.flexible as legacy_flex
    import te_analysis.tools.sciplot as sciplot
    from te_analysis.tools.physics import lorenz
    from te_analysis.tools.spb import lattice_cal

    assert sciplot.main is legacy_flex.main
    assert sciplot.PLOTTERS is legacy_flex.PLOTTERS
    assert lorenz.calculate_lorenz_number is lattice_cal.calculate_lorenz_number
    assert lorenz.add_lattice_thermal_conductivity is lattice_cal.add_lattice_thermal_conductivity


def test_cli_groups_and_legacy_aliases_dispatch_cleanly():
    res_sci = run_cli(["sciplot", "--help"])
    assert res_sci.returncode == 0, res_sci.stderr

    res_flex = run_cli(["flexible", "--help"])
    assert res_flex.returncode == 0, res_flex.stderr

    res_spb = run_cli(["spb", "--help"])
    assert res_spb.returncode == 0
    assert "effective-mass" in res_spb.stdout
    assert "skb" not in res_spb.stdout  # Non-parabolic models moved out of spb help

    res_band = run_cli(["band", "--help"])
    assert res_band.returncode == 0
    assert "effective-mass" in res_band.stdout and "skb" in res_band.stdout and "two-band" in res_band.stdout

    # Legacy `spb skb --help` fallback remains functional
    res_legacy_spb_skb = run_cli(["spb", "skb", "--help"])
    assert res_legacy_spb_skb.returncode == 0


def test_five_orthogonal_skills_and_tedex_plugin_decoupling():
    expected_skills = {
        "te-workspace",
        "te-data-pipeline",
        "te-plotting",
        "te-xrd",
        "te-physics-models",
    }
    local_skills = {
        p.name for p in (REPO_ROOT / ".agents" / "skills").iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
    }
    plugin_skills = {
        p.name
        for p in (REPO_ROOT / "plugin" / "tedex" / "skills").iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file()
    }
    assert local_skills == expected_skills
    assert plugin_skills == expected_skills

    # Ensure generic plugin skills use CLI `te` without repository-private spreadsheet references
    for skill_name in expected_skills:
        txt = (REPO_ROOT / "plugin" / "tedex" / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
        assert "samples lists.xlsx" not in txt.lower(), (
            f"Lab-specific spreadsheet string leaked into generic plugin skill {skill_name}"
        )


def test_package_name_and_version_consistency():
    import te_analysis

    version_txt = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    plugin_meta = json.loads((REPO_ROOT / "plugin" / "tedex" / "plugin.json").read_text(encoding="utf-8"))
    pyproject_txt = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert version_txt == "1.5.0"
    assert te_analysis.__version__ == version_txt
    assert plugin_meta["name"] == "tedex"
    assert plugin_meta["version"] == version_txt
    assert re.search(r'^name\s*=\s*"tedex"', pyproject_txt, flags=re.MULTILINE)
    assert re.search(rf'^version\s*=\s*"{re.escape(version_txt)}"', pyproject_txt, flags=re.MULTILINE)

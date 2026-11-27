"""End-to-end tests for Mode-B clean user workspaces, workspace init, and te_analysis.paths."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from _helpers import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from te_analysis.paths import (  # noqa: E402
    ENGINE_ROOT,
    build_workspace_config_dict,
    clear_workspace_cache,
    load_workspace,
)
from te_analysis.tools.selectors import (  # noqa: E402
    normalize_batch_id,
    normalize_sample_selector,
    parse_batch_sample_selector,
)
from te_analysis.tools.workspace_init import initialize_workspace  # noqa: E402


def _run_launcher_in_dir(cwd: Path, args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"
    env.pop("TE_WORKSPACE_ROOT", None)
    env.pop("TE_WORKSPACE_CONFIG", None)
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_workspace_template_is_clean_and_valid():
    template_path = REPO_ROOT / "configs" / "workspace_template.json"
    assert template_path.is_file()
    payload = json.loads(template_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "tedex-workspace/v1"
    assert payload["project"]["batch_prefix"] == ""
    assert payload["paths"]["metadata"] == "data/metadata"
    assert payload["paths"]["figures"] == "outputs/figures"


def test_selectors_support_custom_and_empty_batch_prefixes():
    # Explicit custom prefix (e.g. SNSE)
    assert normalize_batch_id("102", batch_prefix="SNSE") == "SNSE-102"
    assert normalize_batch_id("Batch-102", batch_prefix="SNSE") == "SNSE-102"
    assert normalize_sample_selector("SNSE-102b", batch_prefix="SNSE") == "SNSE-102-B"
    assert parse_batch_sample_selector("102-A", batch_prefix="SNSE") == ("SNSE-102", "SNSE-102-A")

    # Free naming (empty prefix)
    assert normalize_batch_id("2026_Run1", batch_prefix="") == "2026_Run1"
    assert normalize_sample_selector("Sample_Alpha", batch_prefix="") == "Sample_Alpha"
    assert parse_batch_sample_selector("CuInTe2_Run1/SampleA", batch_prefix="") == (
        "CuInTe2_Run1",
        "CuInTe2_Run1/SampleA",
    )


def test_init_check_exits_2_when_uninitialized_and_0_after_init():
    with tempfile.TemporaryDirectory() as raw_tmp:
        user_dir = Path(raw_tmp) / "clean_project"
        user_dir.mkdir(parents=True)

        # Uninitialized folder -> exit code 2
        res_before = _run_launcher_in_dir(user_dir, ["init", "--check"])
        assert res_before.returncode == 2, res_before.stdout + res_before.stderr

        # Initialize with custom locations, system/batch grouping, and Mo-Ka XRD radiation
        res_init = _run_launcher_in_dir(
            user_dir,
            [
                "init",
                "--yes",
                "--name",
                "SnSe Phonon Study",
                "--grouping",
                "by_system_batch",
                "--batch-prefix",
                "SNSE",
                "--metadata-dir",
                "meta_ledger",
                "--figures-dir",
                "manuscript/figures",
                "--xrd-radiation",
                "Mo-Ka",
                "--formats",
                "svg",
                "png",
            ],
        )
        assert res_init.returncode == 0, res_init.stdout + res_init.stderr

        # Verify zero Python/skill clutter in user_dir
        assert list(user_dir.glob("*.py")) == []
        assert not (user_dir / ".agents").exists()
        assert (user_dir / "configs" / "workspace.json").is_file()
        assert (user_dir / "meta_ledger" / "lab_metadata.md").is_file()
        assert (user_dir / "outputs" / "cache" / ".gitignore").is_file()

        # Check status JSON
        res_status = _run_launcher_in_dir(user_dir, ["init", "--check", "--json"])
        assert res_status.returncode == 0
        payload = json.loads(res_status.stdout)
        assert payload["is_initialized"] is True
        assert payload["project"]["grouping_mode"] == "by_system_batch"
        assert payload["project"]["batch_prefix"] == "SNSE"
        assert abs(payload["data_types"]["xrd"]["wavelength_angstrom"] - 0.71073) < 1e-5


def test_mode_b_external_clean_workspace_sync_and_plot_pipeline():
    """Verify sync + plot-te work inside an external Mode-B directory with custom paths."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        user_dir = Path(raw_tmp) / "external_lab_project"
        cfg = build_workspace_config_dict(
            project_name="External CuInTe2 Project",
            grouping_mode="by_system_batch",
            batch_prefix="CIT",
            path_overrides={
                "metadata": "data/metadata",
                "figures": "paper_outputs/figures",
            },
        )
        ws = initialize_workspace(user_dir, config_payload=cfg)
        assert ws.engine_root == ENGINE_ROOT

        # Seed a two-level raw folder: data/raw/CuInTe2/CIT-01/CIT-01-A_{ZEM,LFA}
        raw_batch = ws.raw_dir / "CuInTe2" / "CIT-01"
        raw_batch.mkdir(parents=True, exist_ok=True)
        (raw_batch / "CIT-01-A_ZEM.txt").write_text("dummy zem\n", encoding="utf-8")
        (raw_batch / "CIT-01-A_LFA.csv").write_text("Temp,Diff\n300,0.65\n", encoding="utf-8")

        # Run `sync metadata` inside the external clean directory
        res_sync = _run_launcher_in_dir(user_dir, ["sync", "metadata"])
        assert res_sync.returncode == 0, res_sync.stdout + res_sync.stderr

        batches = json.loads((user_dir / "data" / "metadata" / "batches.json").read_text(encoding="utf-8"))
        samples = json.loads((user_dir / "data" / "metadata" / "samples.json").read_text(encoding="utf-8"))
        assert len(batches) == 1 and batches[0]["batch_id"] == "CIT-01"
        assert batches[0]["material_family"] == "CuInTe2"
        assert len(samples) == 1 and samples[0]["sample_id"] == "CIT-01-A"
        assert samples[0]["processed_file"] == "data/processed/CuInTe2/CIT-01/CIT-01-A.csv"

        # Seed processed CSV and run `plot-te CIT-01 --zt --no-show` from the clean user workspace
        proc_csv = user_dir / samples[0]["processed_file"]
        proc_csv.parent.mkdir(parents=True, exist_ok=True)
        proc_csv.write_text(
            "Temperature,Seebeck,Conductivity,Thermal_Conductivity,ZT\n"
            "300,150e-6,50000,1.2,0.28\n"
            "500,210e-6,42000,0.9,1.03\n"
            "700,255e-6,36000,0.7,2.34\n",
            encoding="utf-8",
        )

        res_plot = _run_launcher_in_dir(
            user_dir,
            ["plot-te", "CIT-01", "--zt", "--no-data-figures", "--no-show"],
        )
        assert res_plot.returncode == 0, res_plot.stdout + res_plot.stderr

        expected_fig_root = user_dir / "paper_outputs" / "figures" / "te" / "CuInTe2" / "CIT-01"
        produced_svgs = list(expected_fig_root.rglob("*.svg"))
        assert produced_svgs, f"Expected figure under {expected_fig_root}, got none"

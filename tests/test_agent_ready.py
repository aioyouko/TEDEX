"""Tests for the agent-facing contract of the launcher and tools.

Covers the `--json` run summary, the run manifest, commands refusing to guess
a batch, the `agent` command's argument handling, and core_agent raising
AgentError instead of returning error text. No test reaches a real model:
MOONSHOT_API_KEY is blanked and the OpenAI client is replaced by a fake.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from _helpers import REPO_ROOT, run_cli

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

API_KEY_ENV_VAR = "MOONSHOT_API_KEY"
SPB_DEMO = REPO_ROOT / "data" / "demo" / "spb_fitting"


@contextmanager
def env_var(name: str, value: str | None):
    saved = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = saved


# --- run manifest -----------------------------------------------------------


def test_record_output_without_manifest_does_nothing():
    from te_analysis.run_manifest import MANIFEST_ENV_VAR, record_output

    with env_var(MANIFEST_ENV_VAR, None), tempfile.TemporaryDirectory() as tmp:
        record_output(Path(tmp) / "figure.png")
        assert list(Path(tmp).iterdir()) == []


def test_manifest_round_trip_dedupes_and_relativizes():
    from te_analysis.run_manifest import MANIFEST_ENV_VAR, read_manifest, record_output

    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        manifest = tmp / "manifest.jsonl"
        figure = tmp / "plots" / "zt.png"
        figure.parent.mkdir()
        figure.write_text("png")
        with env_var(MANIFEST_ENV_VAR, str(manifest)):
            record_output(figure)
            record_output(tmp / "gone.csv")
            record_output(figure)  # written twice, reported once

        assert read_manifest(manifest, root=tmp) == [
            {"path": "plots/zt.png", "kind": "figure", "exists": True},
            {"path": "gone.csv", "kind": "table", "exists": False},
        ]


# --- launcher --json ----------------------------------------------------------


def test_json_run_reports_every_written_file():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        for name in ("Ag2Se_series.csv", "Ag2Se_params.csv"):
            shutil.copy(SPB_DEMO / "Ag2Se" / name, tmp / name)
        out_dir = tmp / "out"

        result = run_cli(
            [
                "--json", "spb", "effective-mass", str(tmp / "Ag2Se_series.csv"),
                "--group-by", "curve_id",
                "--params", str(tmp / "Ag2Se_params.csv"),
                "--formats", "png",
                "--no-show", "--output-dir", str(out_dir),
            ]
        )
        assert result.returncode == 0, result.stderr[-2000:]

        summary = json.loads(result.stdout)  # stdout must hold only the JSON object
        assert summary["command"] == "spb effective-mass"
        assert summary["ok"] is True and summary["exit_code"] == 0
        outputs = summary["outputs"]
        assert all(entry["exists"] for entry in outputs), outputs
        assert {"figure", "table", "json"} <= {entry["kind"] for entry in outputs}

        reported = {Path(entry["path"]).resolve() for entry in outputs}
        written = {path.resolve() for path in out_dir.rglob("*") if path.is_file()}
        assert written, "the fit wrote nothing"
        assert written <= reported, f"unreported files: {sorted(written - reported)}"


def test_json_run_reports_failure_as_json():
    result = run_cli(["--json", "assess"])
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    assert summary == {
        "command": "assess",
        "args": [],
        "exit_code": 2,
        "ok": False,
        "outputs": [],
    }
    assert "no batch selected" in result.stderr


def test_json_flag_without_command_is_an_error():
    result = run_cli(["--json"])
    assert result.returncode == 2


# --- no hidden default batch -------------------------------------------------


def test_analyze_requires_a_batch():
    result = run_cli(["analyze", "--dry-run"])
    assert result.returncode != 0
    assert "No batch selected" in result.stderr


def test_analyze_sample_without_batch_is_an_error():
    result = run_cli(["analyze", "--sample", "B", "--dry-run"])
    assert result.returncode != 0
    assert "does not name a batch" in result.stderr


def test_plot_te_requires_a_batch():
    result = run_cli(["plot-te", "--no-show"])
    assert result.returncode == 2
    assert "no batch selected" in result.stderr


def test_assess_requires_a_batch():
    result = run_cli(["assess"])
    assert result.returncode == 2
    assert "no batch selected" in result.stderr


# --- agent command --------------------------------------------------------------


def _write_features(directory: Path, batch_name: str) -> Path:
    folder = directory / f"{batch_name}-processed"
    folder.mkdir()
    path = folder / "extracted_features.json"
    path.write_text(
        json.dumps({"batch_name": batch_name, "samples_data": [{"Samples": "A", "ZT_max": 0.8}]}),
        encoding="utf-8",
    )
    return path


def test_agent_requires_a_target():
    result = run_cli(["agent"])
    assert result.returncode == 2


def test_agent_reports_missing_features():
    with env_var(API_KEY_ENV_VAR, ""):
        result = run_cli(["agent", "CHY-0000"])
    assert result.returncode == 1
    assert "no extracted features for CHY-0000" in result.stderr


def test_agent_refuses_to_run_without_a_matrix():
    with tempfile.TemporaryDirectory() as raw_tmp, env_var(API_KEY_ENV_VAR, ""):
        features = _write_features(Path(raw_tmp), "TEST-0001")
        result = run_cli(["agent", str(features), "--output-dir", str(Path(raw_tmp) / "reports")])
    assert result.returncode == 1
    assert "no matrix composition found for TEST-0001" in result.stderr


def test_agent_missing_api_key_fails_without_writing_a_report():
    with tempfile.TemporaryDirectory() as raw_tmp, env_var(API_KEY_ENV_VAR, ""):
        tmp = Path(raw_tmp)
        features = _write_features(tmp, "TEST-0001")
        reports = tmp / "reports"
        result = run_cli(
            ["agent", str(features), "--matrix", "Cu2Se", "--output-dir", str(reports)]
        )
        assert result.returncode == 1
        assert f"{API_KEY_ENV_VAR} is not set" in result.stderr
        assert not reports.exists() or not any(reports.iterdir())


# --- core_agent -------------------------------------------------------------------


def _fake_openai(behavior):
    """An OpenAI stand-in whose completion raises `behavior` or returns it as text."""

    def create(**_kwargs):
        if isinstance(behavior, Exception):
            raise behavior
        message = SimpleNamespace(content=behavior)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    return FakeOpenAI


def _expect_agent_error(call, fragment: str):
    from te_analysis.agents.core_agent import AgentError

    try:
        call()
    except AgentError as error:
        assert fragment in str(error), str(error)
    else:
        raise AssertionError(f"expected AgentError containing {fragment!r}")


def test_core_agent_raises_instead_of_returning_error_text():
    with env_var(API_KEY_ENV_VAR, ""):  # set before import so .env cannot fill it
        from te_analysis.agents import core_agent

        real_client = core_agent.OpenAI
        try:
            _expect_agent_error(lambda: core_agent.analyze_materials_data({}), "is not set")

            os.environ[API_KEY_ENV_VAR] = "test-key"
            core_agent.OpenAI = _fake_openai(RuntimeError("connection refused"))
            _expect_agent_error(lambda: core_agent.analyze_materials_data({}), "connection refused")

            core_agent.OpenAI = _fake_openai("   ")
            _expect_agent_error(lambda: core_agent.assess_materials_performance({}), "empty reply")

            core_agent.OpenAI = _fake_openai("## Report")
            assert core_agent.assess_materials_performance({}) == "## Report"
        finally:
            core_agent.OpenAI = real_client

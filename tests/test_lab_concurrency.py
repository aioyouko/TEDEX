"""Concurrent commands must not lose each other's lab-metadata edits.

Runs several `sync fill` processes at once against one synthetic data/lab,
holds the lab lock from another process to check that commands wait (or time
out with a clear message), and checks that a child process of the lock holder
goes straight through, as analyze's Markdown sync does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from _helpers import REPO_ROOT, run_cli

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BATCH = "CHY-9101"
SUFFIXES = "ABCDEF"


def write_metadata(directory: Path) -> list[str]:
    from scripts.sync_lab_markdown import render_markdown

    samples = [
        {"sample_id": f"{BATCH}-{s}", "batch_id": BATCH, "sample_name": s, "density": None, "cp_value": None, "notes": ""}
        for s in SUFFIXES
    ]
    batches = [{"batch_id": BATCH, "notes": ""}]
    (directory / "samples.json").write_text(json.dumps(samples, indent=4), encoding="utf-8")
    (directory / "batches.json").write_text(json.dumps(batches, indent=4), encoding="utf-8")
    (directory / "lab_metadata.md").write_text(render_markdown(batches, samples), encoding="utf-8")
    return [
        "--markdown", str(directory / "lab_metadata.md"),
        "--batches-json", str(directory / "batches.json"),
        "--samples-json", str(directory / "samples.json"),
    ]


def cli_env(**extra) -> dict:
    env = os.environ.copy()
    env.pop("TE_LAB_LOCK_HELD", None)
    env["MPLBACKEND"] = "Agg"
    env.update(extra)
    return env


def spawn(args: list[str], **env) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "main.py"), *args],
        cwd=REPO_ROOT,
        env=cli_env(**env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )


@contextmanager
def lock_held_by_other_process(lab_dir: Path, seconds: float):
    """Hold the lab lock from a separate process for up to `seconds`."""
    code = (
        "import sys, time; sys.path.insert(0, sys.argv[1]);"
        "from te_analysis.lab_store import lab_lock;"
        "lock = lab_lock(sys.argv[2]); lock.__enter__();"
        "print('locked', flush=True); time.sleep(float(sys.argv[3]))"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", code, str(REPO_ROOT), str(lab_dir), str(seconds)],
        env=cli_env(), stdout=subprocess.PIPE, encoding="utf-8",
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        yield holder
    finally:
        holder.kill()
        holder.wait()


def test_concurrent_fills_keep_every_edit():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        paths = write_metadata(tmp)
        jobs = []
        for index, suffix in enumerate(SUFFIXES):
            jobs.append(spawn(["sync", "fill", BATCH, "density", f"5.{90 + index}", "--samples", suffix, *paths]))
            jobs.append(spawn(["sync", "fill", BATCH, "sample_name", f"label_{suffix}", "--samples", suffix, *paths]))
        for job in jobs:
            _, stderr = job.communicate(timeout=300)
            assert job.returncode == 0, stderr[-1500:]

        records = {r["sample_id"]: r for r in json.loads((tmp / "samples.json").read_text(encoding="utf-8"))}
        for index, suffix in enumerate(SUFFIXES):
            record = records[f"{BATCH}-{suffix}"]
            assert record["density"] == float(f"5.{90 + index}"), record
            assert record["sample_name"] == f"label_{suffix}", record
        markdown = (tmp / "lab_metadata.md").read_text(encoding="utf-8")
        assert markdown.count("| density | 5.9") == len(SUFFIXES)
        assert not list(tmp.glob(".*.tmp")), "temporary files were left behind"


def test_command_times_out_while_another_holds_the_lock():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        paths = write_metadata(tmp)
        with lock_held_by_other_process(tmp, 60):
            job = spawn(["sync", "fill", BATCH, "density", "6.1", "--samples", "A", *paths], TE_LAB_LOCK_TIMEOUT="1")
            _, stderr = job.communicate(timeout=60)
        assert job.returncode == 2
        assert "another command has been updating" in stderr
        assert json.loads((tmp / "samples.json").read_text(encoding="utf-8"))[0]["density"] is None


def test_command_waits_for_the_lock_then_writes():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        paths = write_metadata(tmp)
        with lock_held_by_other_process(tmp, 3) as holder:
            started = time.monotonic()
            job = spawn(["sync", "fill", BATCH, "density", "6.2", "--samples", "A", *paths])
            holder.wait(timeout=30)  # releases the lock when it exits
            _, stderr = job.communicate(timeout=120)
        assert job.returncode == 0, stderr[-1500:]
        assert "Waiting for another command" in stderr
        assert time.monotonic() - started >= 1.0
        assert json.loads((tmp / "samples.json").read_text(encoding="utf-8"))[0]["density"] == 6.2


def test_child_of_the_lock_holder_does_not_wait():
    from te_analysis.lab_store import lab_lock

    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        paths = write_metadata(tmp)
        with lab_lock(tmp):  # like analyze holding the lock while it runs the Markdown sync
            result = run_cli(["sync", "fill", BATCH, "density", "6.3", "--samples", "B", *paths])
        assert result.returncode == 0, result.stderr[-1500:]
        assert "Waiting" not in result.stderr
        assert "TE_LAB_LOCK_HELD" not in os.environ


def test_atomic_write_replaces_and_cleans_up():
    from te_analysis.lab_store import atomic_write_text

    with tempfile.TemporaryDirectory() as raw_tmp:
        target = Path(raw_tmp) / "samples.json"
        target.write_text("old", encoding="utf-8")
        atomic_write_text(target, "new\n")
        assert target.read_text(encoding="utf-8") == "new\n"
        assert [p.name for p in Path(raw_tmp).iterdir()] == ["samples.json"]

"""Shared helpers for the characterization test suite.

Tests run with pytest (`pytest tests/`) or without it
(`python tests/run_tests.py`).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

try:  # pragma: no cover
    import pytest

    def skip(message: str):
        pytest.skip(message)

except ImportError:  # plain-python runner

    class SkipTest(Exception):
        pass

    def skip(message: str):
        raise SkipTest(message)


def run_cli(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """Run `python main.py <args>` from the repo root, headless."""
    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def load_script(relative_path: str, module_name: str):
    """Import a repo script file (scripts/ is not a package)."""
    path = REPO_ROOT / relative_path
    for extra in (REPO_ROOT, path.parent):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    import matplotlib

    matplotlib.use("Agg")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_close(actual, expected, path="", rel_tol=1e-5, abs_tol=1e-9):
    """Recursively compare JSON-like structures; floats within tolerance."""
    import math

    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual)}"
        assert set(actual) == set(expected), (
            f"{path}: keys differ: {sorted(set(actual) ^ set(expected))}"
        )
        for key in expected:
            assert_close(actual[key], expected[key], f"{path}.{key}", rel_tol, abs_tol)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), (
            f"{path}: list length {len(actual)} != {len(expected)}"
        )
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert_close(a, e, f"{path}[{i}]", rel_tol, abs_tol)
    elif isinstance(expected, bool) or expected is None:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"
    elif isinstance(expected, (int, float)):
        assert isinstance(actual, (int, float)), f"{path}: {actual!r} not numeric"
        assert math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol), (
            f"{path}: {actual!r} != {expected!r}"
        )
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"

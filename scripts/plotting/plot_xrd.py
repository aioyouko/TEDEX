#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""Backward-compatible CLI shim for ``te_analysis.tools.xrd.cli``."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from te_analysis.tools.xrd.cli import *  # noqa: F401,F403,E402
from te_analysis.tools.xrd.cli import main  # noqa: E402


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from None

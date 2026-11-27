#!/usr/bin/env python3
"""Backward-compatible shim for ``te_analysis.pipeline.run_analysis``."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from te_analysis.pipeline.run_analysis import *  # noqa: F401,F403,E402
from te_analysis.pipeline.run_analysis import main  # noqa: E402


if __name__ == "__main__":
    main()

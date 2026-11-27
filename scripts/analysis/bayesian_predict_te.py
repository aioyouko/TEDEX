#!/usr/bin/env python3
"""Backward-compatible shim for ``te_analysis.pipeline.bayesian_predict``."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from te_analysis.pipeline.bayesian_predict import *  # noqa: F401,F403,E402
from te_analysis.pipeline.bayesian_predict import main  # noqa: E402


if __name__ == "__main__":
    main()

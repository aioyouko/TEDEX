#!/usr/bin/env python3
"""Backward-compatible shim for ``te_analysis.sync.reference_xlsx``."""

import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from te_analysis.sync.reference_xlsx import *  # noqa: F401,F403,E402
from te_analysis.sync.reference_xlsx import main  # noqa: E402


if __name__ == "__main__":
    main()

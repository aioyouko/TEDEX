#!/usr/bin/env python3
"""Backward-compatible CLI shim for ``te_analysis.tools.te_plotting.paper_variants``."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from te_analysis.tools.te_plotting.paper_variants import *  # noqa: F401,F403,E402
from te_analysis.tools.te_plotting.paper_variants import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Command-line launcher shim for the sciplot scientific plotting tool."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from te_analysis.tools.sciplot import main


if __name__ == "__main__":
    raise SystemExit(main())

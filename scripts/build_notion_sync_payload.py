#!/usr/bin/env python3
"""Backward-compatible shim for ``te_analysis.sync.notion_payload``."""

import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from te_analysis.sync.notion_payload import *  # noqa: F401,F403,E402
from te_analysis.sync.notion_payload import main  # noqa: E402


if __name__ == "__main__":
    main()

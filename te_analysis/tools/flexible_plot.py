"""Backward-compatible shim; implementation lives in te_analysis.tools.flexible."""

from te_analysis.tools.flexible import *  # noqa: F401,F403
from te_analysis.tools.flexible import __all__  # noqa: F401
from te_analysis.tools.flexible.cli import main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())

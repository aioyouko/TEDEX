"""Thin root shim for the workspace launcher.

The real launcher lives in te_analysis/launcher.py so the installed package
owns it; this file only preserves the `python main.py ...` workflow.
"""

from te_analysis.launcher import main

if __name__ == "__main__":
    raise SystemExit(main())

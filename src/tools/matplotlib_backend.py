from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _has_qt_binding() -> bool:
    return any(
        importlib.util.find_spec(package_name) is not None
        for package_name in ("PyQt6", "PySide6", "PyQt5", "PySide2")
    )


def _is_interactive_terminal() -> bool:
    return bool(getattr(sys.stdout, "isatty", lambda: False)() or getattr(sys.stderr, "isatty", lambda: False)())


def configure_matplotlib_backend() -> None:
    """
    Configure a writable Matplotlib cache and prefer an interactive Qt backend.

    Set MPLBACKEND before importing matplotlib.pyplot if a specific backend is
    needed. Set TE_AGENT_MPL_BACKEND=default to keep Matplotlib's own default.
    """
    mpl_cache_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "te_agent_matplotlib"
    mpl_cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_cache_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(mpl_cache_dir))

    if os.environ.get("MPLBACKEND"):
        return

    requested_backend = os.environ.get("TE_AGENT_MPL_BACKEND", "").strip()
    if requested_backend:
        if requested_backend.lower() not in {"default", "auto", "none"}:
            os.environ["MPLBACKEND"] = requested_backend
        return

    if _is_interactive_terminal() and _has_qt_binding():
        os.environ["MPLBACKEND"] = "QtAgg"


def show_interactive_figures() -> None:
    import matplotlib.pyplot as plt

    plt.show()

#!/usr/bin/env python3
"""Minimal test runner for environments without pytest.

Usage: python tests/run_tests.py [name-filter]
With pytest installed, prefer: pytest tests/ -v
"""

from __future__ import annotations

import sys
import traceback
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    name_filter = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.path.insert(0, str(HERE))
    passed = skipped = failed = 0

    for test_file in sorted(HERE.glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(test_file.stem, test_file)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            print(f"IMPORT ERROR  {test_file.name}")
            traceback.print_exc()
            failed += 1
            continue

        for name in sorted(dir(module)):
            if not name.startswith("test_") or not callable(getattr(module, name)):
                continue
            if name_filter and name_filter not in f"{test_file.stem}.{name}":
                continue
            label = f"{test_file.stem}.{name}"
            try:
                getattr(module, name)()
            except BaseException as exc:  # pytest's Skipped is not an Exception subclass
                if isinstance(exc, KeyboardInterrupt):
                    raise
                if type(exc).__name__ in ("SkipTest", "Skipped"):
                    print(f"SKIP  {label}: {exc}")
                    skipped += 1
                else:
                    print(f"FAIL  {label}")
                    traceback.print_exc()
                    failed += 1
            else:
                print(f"PASS  {label}")
                passed += 1

    print(f"\n{passed} passed, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Machine-readable record of the files a command writes.

``python main.py --json <command> ...`` points the ``TE_RUN_MANIFEST``
environment variable at a temporary file before it runs the tool. Tools call
:func:`record_output` right after they write a file. The launcher then reads
the entries back and prints one JSON object on stdout, so an agent or a script
can find a command's outputs without parsing its console messages.

Without ``TE_RUN_MANIFEST`` set, :func:`record_output` does nothing, so normal
command-line use is unchanged. Child processes inherit the variable, so files
written by helper subprocesses (for example the lab-metadata sync that
``analyze`` runs) are recorded too.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

MANIFEST_ENV_VAR = "TE_RUN_MANIFEST"

_KIND_BY_SUFFIX = {
    ".png": "figure",
    ".pdf": "figure",
    ".svg": "figure",
    ".jpg": "figure",
    ".jpeg": "figure",
    ".tif": "figure",
    ".tiff": "figure",
    ".eps": "figure",
    ".csv": "table",
    ".tsv": "table",
    ".xlsx": "table",
    ".json": "json",
    ".md": "markdown",
    ".txt": "text",
}


def output_kind(path: str | os.PathLike[str]) -> str:
    """Classify an output file by its extension."""
    return _KIND_BY_SUFFIX.get(Path(path).suffix.lower(), "file")


def record_output(path: str | os.PathLike[str], kind: str | None = None) -> None:
    """Record that the running command wrote ``path``.

    Call it after the file is written. A failure to record is reported on
    stderr but never raised, so the tool's real work is not lost over it.
    """
    manifest = os.environ.get(MANIFEST_ENV_VAR)
    if not manifest:
        return
    entry = {"path": str(Path(path).resolve()), "kind": kind or output_kind(path)}
    try:
        with open(manifest, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"warning: could not record output {path}: {error}", file=sys.stderr)


def read_manifest(
    manifest_path: str | os.PathLike[str],
    root: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    """Return the recorded outputs in first-write order, one entry per file.

    Paths under ``root`` are reported relative to it, in POSIX form; other
    paths stay absolute. ``exists`` is False when a later step removed the file.
    """
    path = Path(manifest_path)
    if not path.exists():
        return []

    root_path = Path(root).resolve() if root is not None else None
    outputs: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        resolved = Path(entry["path"])
        display = resolved
        if root_path is not None:
            try:
                display = resolved.relative_to(root_path)
            except ValueError:
                pass
        outputs[str(resolved)] = {
            "path": display.as_posix(),
            "kind": entry.get("kind") or output_kind(resolved),
            "exists": resolved.exists(),
        }
    return list(outputs.values())

"""Optional figure filenames shared by plotting commands.

Keep naming scoped to one command so repeated programmatic calls do not share
their counters. Export formats and data-table filenames remain independent.
"""

from __future__ import annotations

import argparse
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


_IMAGE_SUFFIXES = {
    ".svg", ".svgz", ".png", ".pdf", ".jpg", ".jpeg", ".tif", ".tiff",
    ".eps", ".ps", ".webp", ".pgf", ".raw", ".rgba",
}


def normalize_figure_name(value: str) -> str:
    """Validate a filename (not a path) and remove an optional image suffix."""
    raw_name = str(value)
    if any(char in raw_name for char in ("/", "\\")) or any(
        ord(char) < 32 or ord(char) == 127 for char in raw_name
    ):
        raise ValueError("--rename accepts a filename only, without folders or control characters.")
    name = raw_name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("--rename needs a non-empty figure filename, e.g. '[1]'.")
    suffix = Path(name).suffix
    if suffix.lower() in _IMAGE_SUFFIXES:
        name = name[:-len(suffix)]
    if not name or name in {".", ".."} or name.lower() in _IMAGE_SUFFIXES:
        raise ValueError("--rename needs a filename before the extension.")
    return name


def _rename_argument(value: str) -> str:
    try:
        normalize_figure_name(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value


def add_rename_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--rename",
        metavar="NAME",
        type=_rename_argument,
        help=(
            "Rename exported figures, e.g. --rename '[1]' gives [1], [2], ...; "
            "--rename 'sample' gives sample, sample_2, ... in plotting order. "
            "An optional image extension is ignored; existing format options "
            "still control export formats. Quote brackets in the shell."
        ),
    )


@dataclass
class _FigureNames:
    stem: str
    count: int = 0

    def next_stem(self) -> str:
        index = self.count
        self.count += 1
        numbered = re.fullmatch(r"\[([0-9]+)\]", self.stem)
        if numbered:
            digits = numbered.group(1)
            number = str(int(digits) + index).zfill(len(digits))
            return f"[{number}]"
        return self.stem if index == 0 else f"{self.stem}_{index + 1}"


_figure_names: ContextVar[_FigureNames | None] = ContextVar("figure_names", default=None)


@contextmanager
def figure_output_naming(rename: str | None = None):
    """Name each saved figure once, sharing its name across export formats."""
    names = _FigureNames(normalize_figure_name(rename)) if rename is not None else None
    token = _figure_names.set(names)
    try:
        yield
    finally:
        _figure_names.reset(token)


def next_figure_stem(original_stem: str) -> str:
    names = _figure_names.get()
    return names.next_stem() if names is not None else original_stem

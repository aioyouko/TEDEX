"""Read sample compositions and Cp values from the lab samples workbook.

The workbook ("NU Lab samples lists.xlsx") has one sheet per batch, named by
the batch ID (e.g. ``CHY-1090``). Each sample is a block:

    row r    A: "Sample ID"        C: "weight (g)"  D: "elements"  E: "Mole ratio"
    row r+1  A: CHY-1090-A         C: total weight
    row r+2  A: composition        C-F: first element    G: molar mass (g/mol)
    row r+3                        C-F: next element     G: Cp (J/g/K)
    row r+4                        C-F: next element     G: atoms per formula unit
    ...                            one row per element (the count varies)

The number of element rows varies between batches, and older sheets order
column G as molar mass, atoms, Cp. So the reader keys on the sample-ID row,
takes the composition from column A below it, and tells the G values apart
by size: Cp is the one value between 0.05 and 1.5 J/g/K, molar mass is the
largest, and atoms per formula unit is the other. Cp is cross-checked against
Dulong-Petit (3R x atoms / molar mass) when both are present.

Blocks whose sample-ID cell is empty are reported by row, never guessed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_WORKBOOK_NAME = "NU Lab samples lists.xlsx"
SAMPLE_ID_RE = re.compile(r"^(CHY-\d+)-([A-Za-z0-9]+)$", re.IGNORECASE)
HEADER_TEXT = "sample id"
GAS_CONSTANT = 8.314462618  # J/(mol K)
CP_RANGE = (0.05, 1.5)  # J/(g K); outside this the cell is almost surely not Cp
DULONG_PETIT_TOLERANCE = 0.02


class WorkbookError(Exception):
    """The workbook or the batch sheet cannot be read."""


@dataclass
class WorkbookSample:
    sample_id: str
    row: int
    composition: str = ""
    cp_value: float | None = None
    molar_mass: float | None = None
    atoms_per_formula: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class WorkbookBatch:
    batch_id: str
    sheet: str
    samples: list[WorkbookSample]
    skipped: list[str]  # sample IDs on the sheet that belong to another batch
    unlabeled_rows: list[int] = field(default_factory=list)  # blocks with an empty sample-ID cell


def find_workbook(project_root: Path, explicit: str | os.PathLike[str] | None = None) -> Path:
    """Return the workbook path: the explicit one, else data/lab/, else the repo root."""
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise WorkbookError(f"workbook not found: {path}")
        return path
    for candidate in (project_root / "data" / "lab" / DEFAULT_WORKBOOK_NAME, project_root / DEFAULT_WORKBOOK_NAME):
        if candidate.is_file():
            return candidate
    raise WorkbookError(
        f"no {DEFAULT_WORKBOOK_NAME!r} in data/lab/ or the workspace root; pass --workbook PATH"
    )


def _number(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _is_block_start(cell_a) -> bool:
    text = _text(cell_a)
    return text.lower() == HEADER_TEXT or bool(SAMPLE_ID_RE.match(text))


def _sheet_for_batch(workbook, batch_id: str):
    wanted = batch_id.strip().lower()
    for name in workbook.sheetnames:
        if name.strip().lower() == wanted:
            return workbook[name]
    raise WorkbookError(f"no sheet named {batch_id!r} in the workbook")


def parse_rows(rows: list[tuple], batch_id: str) -> tuple[list[WorkbookSample], list[str], list[int]]:
    """Parse a batch sheet given as rows of (A, B, C, D, E, F, G, ...) values.

    Returns the batch's samples, the IDs of other batches' samples on the
    sheet, and the 1-based rows of blocks whose sample-ID cell is empty.
    """
    batch_key = batch_id.strip().upper()
    samples: list[WorkbookSample] = []
    skipped: list[str] = []
    unlabeled: list[int] = []

    for index, row in enumerate(rows):
        cell_a = _text(row[0] if row else None)
        if cell_a.lower() == HEADER_TEXT:
            following = rows[index + 1] if index + 1 < len(rows) else ()
            if not _text(following[0] if following else None):
                unlabeled.append(index + 2)
            continue
        match = SAMPLE_ID_RE.match(cell_a)
        if not match:
            continue
        sample_id = f"{match.group(1).upper()}-{match.group(2)}"
        if match.group(1).upper() != batch_key:
            skipped.append(sample_id)
            continue

        # The block runs until the next header or sample-ID row.
        block = []
        for following in rows[index + 1 :]:
            if following and _is_block_start(following[0]):
                break
            block.append(following)

        sample = WorkbookSample(sample_id=sample_id, row=index + 1)
        if block:
            composition = _text(block[0][0] if block[0] else None)
            if composition and not _is_block_start(composition):
                sample.composition = composition
        g_values = [
            number
            for block_row in block
            if len(block_row) > 6 and (number := _number(block_row[6])) is not None
        ]
        _assign_g_values(sample, g_values)
        if not sample.composition:
            sample.warnings.append("no composition below the sample ID")
        samples.append(sample)

    return samples, skipped, unlabeled


def _assign_g_values(sample: WorkbookSample, g_values: list[float]) -> None:
    low, high = CP_RANGE
    cp_candidates = [value for value in g_values if low <= value <= high]
    larger = sorted(value for value in g_values if value > high)
    if larger:
        sample.molar_mass = larger[-1]
    if len(larger) >= 2:
        sample.atoms_per_formula = larger[0]

    if len(cp_candidates) != 1:
        found = "no value" if not cp_candidates else f"{len(cp_candidates)} values"
        sample.warnings.append(f"{found} in column G between {low} and {high} J/g/K; Cp not read")
        return
    sample.cp_value = cp_candidates[0]
    if sample.molar_mass and sample.atoms_per_formula:
        expected = 3 * GAS_CONSTANT * sample.atoms_per_formula / sample.molar_mass
        if abs(sample.cp_value - expected) / expected > DULONG_PETIT_TOLERANCE:
            sample.warnings.append(
                f"Cp {sample.cp_value:.6g} differs from Dulong-Petit {expected:.6g} by more than "
                f"{DULONG_PETIT_TOLERANCE:.0%}; check the sheet"
            )


def read_batch(workbook_path: str | os.PathLike[str], batch_id: str) -> WorkbookBatch:
    """Read every sample block of ``batch_id`` from its sheet."""
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(workbook_path, data_only=True, read_only=True)
    except PermissionError as error:
        raise WorkbookError(
            f"cannot open {workbook_path}: another program (usually Excel) has it locked. "
            "Close it there and run again."
        ) from error
    try:
        sheet = _sheet_for_batch(workbook, batch_id)
        rows = [tuple(row) for row in sheet.iter_rows(values_only=True)]
        sheet_name = sheet.title
    finally:
        workbook.close()

    samples, skipped, unlabeled = parse_rows(rows, batch_id)
    if not samples:
        hint = (
            f"; {len(unlabeled)} block(s) have an empty sample-ID cell (rows "
            f"{', '.join(map(str, unlabeled))}): type the IDs into column A"
            if unlabeled
            else ""
        )
        raise WorkbookError(f"sheet {sheet_name!r} has no sample blocks for {batch_id}{hint}")
    return WorkbookBatch(batch_id, sheet_name, samples, skipped, unlabeled)

#!/usr/bin/env python3
"""Fill a batch's Cp values and compositions from the lab samples workbook.

Usage:
    python main.py sync workbook CHY-1090
    python main.py sync workbook CHY-1090 --dry-run
    python main.py sync workbook CHY-1090 --workbook "path/to/NU Lab samples lists.xlsx"

Reads the sheet named after the batch, takes each sample's composition
(column A under its sample ID) and Cp (column G), and writes them to
`sample_composition` and `cp_value` of the matching samples in
data/lab/samples.json and data/lab/lab_metadata.md.

Samples must already exist in the lab metadata: run `python main.py sync
metadata` after the raw files are in data/raw. A field that already holds a
different value is left alone, and nothing is written, unless --overwrite.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lab_records import (  # noqa: E402
    Change,
    RecordsError,
    add_path_arguments,
    batch_samples,
    finish,
    load_records,
    plan_change,
)
from te_analysis.lab_store import LabLockTimeout, lab_lock  # noqa: E402
from te_analysis.tools.lab_workbook import WorkbookError, find_workbook, read_batch  # noqa: E402
from te_analysis.tools.selectors import normalize_batch_id  # noqa: E402

CP_DECIMALS = 9  # matches the precision already used in lab_metadata.md


def decimals(value: float) -> int:
    text = repr(float(value))
    if "e" in text or "E" in text:
        return CP_DECIMALS
    return len(text.split(".")[1]) if "." in text else 0


def plan_cp(sample: dict, cp_value: float, overwrite: bool) -> Change:
    """Like plan_change, but a Cp typed with fewer decimals counts as a match."""
    new = round(cp_value, CP_DECIMALS)
    old = sample.get("cp_value")
    if (
        isinstance(old, (int, float))
        and not isinstance(old, bool)
        and old != new
        and decimals(old) < CP_DECIMALS
        and round(new, decimals(old)) == old
    ):
        return Change(sample.get("sample_id", ""), "cp_value", old, new, "rounded")
    return plan_change(sample, "cp_value", new, overwrite)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fill Cp values and compositions for one batch from the lab samples workbook."
    )
    parser.add_argument("batch", help="Batch ID, e.g. CHY-1090 or 1090.")
    parser.add_argument("--workbook", default=None, help="Workbook path (default: data/lab/, then the workspace root).")
    parser.add_argument(
        "--fields",
        nargs="+",
        choices=["cp_value", "sample_composition"],
        default=["cp_value", "sample_composition"],
        help="Fields to fill (default: both).",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace fields that already hold a different value.")
    parser.add_argument("--dry-run", action="store_true", help="Show the changes without writing anything.")
    add_path_arguments(parser)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    batch_id = normalize_batch_id(args.batch)

    try:
        workbook_path = find_workbook(PROJECT_ROOT, args.workbook)
        sheet = read_batch(workbook_path, batch_id)
        # Hold the lab lock from reading the records to writing them.
        with lab_lock(args.samples_json.parent):
            records = load_records(args.markdown, args.batches_json, args.samples_json)
            return fill_from_sheet(args, batch_id, workbook_path, sheet, records)
    except (WorkbookError, RecordsError, LabLockTimeout) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def fill_from_sheet(args, batch_id, workbook_path, sheet, records) -> int:
    print(f"Workbook: {workbook_path} (sheet {sheet.sheet!r})")
    if sheet.skipped:
        print(f"Skipped sample IDs from other batches: {', '.join(sheet.skipped)}")
    if sheet.unlabeled_rows:
        print(
            f"warning: {len(sheet.unlabeled_rows)} block(s) have an empty sample-ID cell (rows "
            f"{', '.join(map(str, sheet.unlabeled_rows))}); type the IDs into column A to import them",
            file=sys.stderr,
        )

    existing = {sample.get("sample_id"): sample for sample in batch_samples(records, batch_id)}
    if not existing:
        print(
            f"error: {batch_id} has no samples in the lab metadata yet. Put its raw files in "
            f"data/raw/{batch_id}/ and run `python main.py sync metadata` first.",
            file=sys.stderr,
        )
        return 2

    changes = []
    for entry in sheet.samples:
        for warning in entry.warnings:
            print(f"warning: {entry.sample_id} (row {entry.row}): {warning}", file=sys.stderr)
        sample = existing.get(entry.sample_id)
        if sample is None:
            continue
        if "cp_value" in args.fields and entry.cp_value is not None:
            changes.append(plan_cp(sample, entry.cp_value, args.overwrite))
        if "sample_composition" in args.fields and entry.composition:
            changes.append(plan_change(sample, "sample_composition", entry.composition, args.overwrite))

    in_sheet = {entry.sample_id for entry in sheet.samples}
    only_sheet = sorted(in_sheet - set(existing))
    only_metadata = sorted(set(existing) - in_sheet)
    if only_sheet:
        print(f"In the workbook but not the lab metadata (no raw files yet?): {', '.join(only_sheet)}")
    if only_metadata:
        print(f"In the lab metadata but not the workbook: {', '.join(only_metadata)}", file=sys.stderr)

    if not changes:
        print("Nothing to fill: no workbook values for this batch's samples.", file=sys.stderr)
        return 1
    return finish(records, changes, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

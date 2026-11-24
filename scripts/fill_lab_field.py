#!/usr/bin/env python3
"""Set one metadata field for a batch's samples, in sample order.

Usage:
    python main.py sync fill CHY-1090 density 5.94 5.97 6.01 5.88 5.90 5.92
    python main.py sync fill CHY-1090 sample_name Ga0.8 Ag_alloy Se_alloy_0.025 --samples A B C
    python main.py sync fill CHY-1090 density 5.94 5.97 --dry-run

Values go to the batch's samples in sample-ID order (A, B, C, ...), or to the
samples named with --samples. The number of values must match the number of
samples exactly; nothing is guessed. Values are parsed the way the Markdown
sync parses them (numbers for density and cp_value, lists for
modifier_elements). A field that already holds a different value is left
alone, and nothing is written, unless --overwrite.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lab_records import (  # noqa: E402
    EDITABLE_SAMPLE_FIELDS,
    RecordsError,
    add_path_arguments,
    batch_samples,
    finish,
    load_records,
    plan_change,
)
from scripts.sync_lab_markdown import parse_value  # noqa: E402
from te_analysis.lab_store import LabLockTimeout, lab_lock  # noqa: E402
from te_analysis.tools.selectors import normalize_batch_id  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set one metadata field for a batch's samples, in sample order (A, B, C, ...)."
    )
    parser.add_argument("batch", help="Batch ID, e.g. CHY-1090 or 1090.")
    parser.add_argument("field", choices=EDITABLE_SAMPLE_FIELDS, metavar="FIELD", help="Field to set, e.g. density, cp_value, sample_name.")
    parser.add_argument("values", nargs="+", help="One value per sample, in order.")
    parser.add_argument(
        "--samples",
        nargs="+",
        default=None,
        help="Samples to set, as suffixes (A B) or full IDs (CHY-1090-A). Default: all samples of the batch.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace values that differ from the current ones.")
    parser.add_argument("--dry-run", action="store_true", help="Show the changes without writing anything.")
    add_path_arguments(parser)
    return parser.parse_args(argv)


def select_samples(all_samples, batch_id, selectors):
    if not selectors:
        return all_samples
    by_id = {sample.get("sample_id"): sample for sample in all_samples}
    chosen = []
    for selector in selectors:
        sample_id = selector if selector.upper().startswith(batch_id.upper() + "-") else f"{batch_id}-{selector}"
        match = next((sid for sid in by_id if sid.upper() == sample_id.upper()), None)
        if match is None:
            raise RecordsError(f"{sample_id} is not a sample of {batch_id} (have: {', '.join(by_id)})")
        chosen.append(by_id[match])
    return chosen


def main(argv=None) -> int:
    args = parse_args(argv)
    batch_id = normalize_batch_id(args.batch)

    try:
        parsed = [parse_value(args.field, value) for value in args.values]
        # Hold the lab lock from reading the records to writing them.
        with lab_lock(args.samples_json.parent):
            records = load_records(args.markdown, args.batches_json, args.samples_json)
            samples = batch_samples(records, batch_id)
            if not samples:
                raise RecordsError(
                    f"{batch_id} has no samples in the lab metadata. Put its raw files in "
                    f"data/raw/{batch_id}/ and run `python main.py sync metadata` first."
                )
            targets = select_samples(samples, batch_id, args.samples)
            if len(parsed) != len(targets):
                names = ", ".join(sample.get("sample_id", "") for sample in targets)
                raise RecordsError(
                    f"got {len(parsed)} value(s) for {len(targets)} sample(s) ({names}); "
                    "give one value per sample, or name the samples with --samples"
                )
            changes = [plan_change(sample, args.field, value, args.overwrite) for sample, value in zip(targets, parsed)]
            return finish(records, changes, args.dry_run)
    except (RecordsError, ValueError, LabLockTimeout) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

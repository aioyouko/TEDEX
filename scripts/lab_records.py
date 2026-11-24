"""Load, change, and save lab metadata records without losing Markdown edits.

The JSON files (data/lab/batches.json, samples.json) are the record of truth
and data/lab/lab_metadata.md is the editable mirror. Every change goes
through the same cycle as `analyze`: import the Markdown into the records
first (so hand edits are kept), apply the change, write the JSON, and export
the Markdown again.

A field that already holds a different value is never overwritten unless
the caller asks for it, so a tool cannot silently replace curated data.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from te_analysis.lab_store import atomic_write_text  # noqa: E402
from te_analysis.run_manifest import record_output  # noqa: E402
from te_analysis.tools.selectors import normalize_batch_id  # noqa: E402

try:
    from scripts.sync_lab_markdown import (  # noqa: E402
        BATCH_FIELDS,
        SAMPLE_FIELDS,
        merge_records,
        parse_markdown,
        read_json,
        render_markdown,
        write_json,
    )
except ModuleNotFoundError:  # run from inside scripts/
    from sync_lab_markdown import (  # noqa: E402
        BATCH_FIELDS,
        SAMPLE_FIELDS,
        merge_records,
        parse_markdown,
        read_json,
        render_markdown,
        write_json,
    )

DEFAULT_MARKDOWN = PROJECT_ROOT / "data" / "lab" / "lab_metadata.md"
DEFAULT_BATCHES_JSON = PROJECT_ROOT / "data" / "lab" / "batches.json"
DEFAULT_SAMPLES_JSON = PROJECT_ROOT / "data" / "lab" / "samples.json"

# Managed by the raw-folder scan; tools must not set them.
STRUCTURAL_FIELDS = {"sample_id", "batch_id", "zem", "lfa", "processed_file", "processed_exists"}
EDITABLE_SAMPLE_FIELDS = [name for name in SAMPLE_FIELDS if name not in STRUCTURAL_FIELDS]


class RecordsError(Exception):
    """The lab metadata cannot be loaded or the change cannot be applied."""


@dataclass
class LabRecords:
    batches: list[dict[str, Any]]
    samples: list[dict[str, Any]]
    markdown: Path
    batches_json: Path
    samples_json: Path


@dataclass
class Change:
    sample_id: str
    field: str
    old: Any
    new: Any
    status: str  # "set", "unchanged", "rounded" (kept), "conflict", or "overwritten"


def add_path_arguments(parser) -> None:
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Lab metadata Markdown.")
    parser.add_argument("--batches-json", type=Path, default=DEFAULT_BATCHES_JSON, help="Batch records JSON.")
    parser.add_argument("--samples-json", type=Path, default=DEFAULT_SAMPLES_JSON, help="Sample records JSON.")


def load_records(markdown: Path, batches_json: Path, samples_json: Path) -> LabRecords:
    """Load the records, folding in any edits made in the Markdown."""
    batches = read_json(batches_json, [])
    samples = read_json(samples_json, [])
    if markdown.exists():
        try:
            parsed_batches, parsed_samples = parse_markdown(markdown, batches, samples)
        except ValueError as error:
            raise RecordsError(f"{markdown} could not be read: {error}") from error
        batches = merge_records(parsed_batches, batches, "batch_id", BATCH_FIELDS, True)
        samples = merge_records(parsed_samples, samples, "sample_id", SAMPLE_FIELDS, True)
    if not samples:
        raise RecordsError(f"no sample records in {samples_json} or {markdown}")
    return LabRecords(batches, samples, markdown, batches_json, samples_json)


def batch_samples(records: LabRecords, batch_id: str) -> list[dict[str, Any]]:
    """Return a batch's sample records in sample-ID order (A, B, C, ...)."""
    batch_id = normalize_batch_id(batch_id)
    return sorted(
        (sample for sample in records.samples if sample.get("batch_id") == batch_id),
        key=lambda sample: sample.get("sample_id", ""),
    )


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def is_placeholder(sample: dict[str, Any], field: str, value: Any) -> bool:
    """True for values the raw scan fills in as stand-ins, e.g. sample_name 'A'."""
    if field != "sample_name" or not isinstance(value, str):
        return False
    sample_id = sample.get("sample_id", "")
    batch_id = sample.get("batch_id", "")
    suffix = sample_id[len(batch_id) + 1 :] if sample_id.startswith(f"{batch_id}-") else sample_id
    return value in {suffix, sample_id}


def same_value(old: Any, new: Any) -> bool:
    if isinstance(old, (int, float)) and isinstance(new, (int, float)) and not isinstance(old, bool):
        return math.isclose(old, new, rel_tol=1e-9, abs_tol=1e-12)
    return old == new


def plan_change(sample: dict[str, Any], field: str, new: Any, overwrite: bool) -> Change:
    old = sample.get(field)
    if same_value(old, new):
        status = "unchanged"
    elif is_empty(old) or is_placeholder(sample, field, old):
        status = "set"
    else:
        status = "overwritten" if overwrite else "conflict"
    return Change(sample.get("sample_id", ""), field, old, new, status)


def apply_changes(records: LabRecords, changes: list[Change]) -> int:
    """Apply set/overwritten changes; return how many fields changed."""
    by_id = {sample.get("sample_id"): sample for sample in records.samples}
    applied = 0
    for change in changes:
        if change.status in {"set", "overwritten"}:
            by_id[change.sample_id][change.field] = change.new
            applied += 1
    return applied


def save_records(records: LabRecords) -> None:
    """Write the JSON records and export the Markdown mirror."""
    batches = sorted(records.batches, key=lambda item: item.get("batch_id", ""))
    samples = sorted(records.samples, key=lambda item: (item.get("batch_id", ""), item.get("sample_id", "")))
    write_json(records.batches_json, batches)
    write_json(records.samples_json, samples)
    atomic_write_text(records.markdown, render_markdown(batches, samples))
    record_output(records.markdown)


def show(value: Any) -> str:
    if is_empty(value):
        return "(empty)"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def print_changes(changes: list[Change]) -> None:
    width = max((len(change.sample_id) for change in changes), default=10)
    for change in changes:
        if change.status == "unchanged":
            detail = show(change.new)
        elif change.status == "rounded":
            detail = f"kept {show(change.old)} (= {show(change.new)} rounded)"
        else:
            detail = f"{show(change.old)} -> {show(change.new)}"
        print(f"  {change.sample_id:<{width}}  {change.field:<20} {change.status:<11} {detail}")


def finish(records: LabRecords, changes: list[Change], dry_run: bool) -> int:
    """Print the plan, then save it unless dry-run or any field conflicts.

    All or nothing: when a field already holds a different value and
    overwrite was not requested, nothing is written and the exit code is 1.
    """
    print_changes(changes)
    conflicts = [change for change in changes if change.status == "conflict"]
    pending = sum(change.status in {"set", "overwritten"} for change in changes)

    if conflicts:
        print(
            f"\n{len(conflicts)} field(s) already hold a different value. Nothing was written; "
            "check the values, then rerun with --overwrite to replace them.",
            file=sys.stderr,
        )
        return 1
    if dry_run:
        print(f"\nDry run: {pending} field(s) would change; nothing was written.")
    elif pending:
        apply_changes(records, changes)
        save_records(records)
        print(f"\nUpdated {pending} field(s) in {records.samples_json} and {records.markdown}.")
    else:
        print("\nNothing to change.")
    return 0

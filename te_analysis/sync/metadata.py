#!/usr/bin/env python3
"""
Scan data/raw/<batch_id>/ files and update flat lab metadata tables.

The sync is intentionally conservative:
- It creates missing batch/sample records from discovered ZEM/LFA files.
- It updates structural file paths and processed-file existence flags.
- It preserves manually curated chemistry fields already present in JSON.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[2]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from te_analysis.paths import get_workspace  # noqa: E402

try:
    from te_analysis.sync.markdown import (
        BATCH_FIELDS,
        SAMPLE_FIELDS,
        merge_records,
        parse_markdown,
        render_markdown,
    )
except ModuleNotFoundError:
    from sync_lab_markdown import (
        BATCH_FIELDS,
        SAMPLE_FIELDS,
        merge_records,
        parse_markdown,
        render_markdown,
    )


RAW_FILE_PATTERN = re.compile(
    r"^(?P<sample_id>.+)_(?P<kind>ZEM|LFA)\.(?P<ext>txt|csv|xlsx)$",
    re.IGNORECASE,
)


CHEMISTRY_DEFAULTS = {
    "density": None,
    "cp_value": None,
    "matrix_composition": "",
    "pristine_composition": "",
    "sample_composition": "",
    "optimization_type": "",
    "modifier_species": "",
    "modifier_element": "",
    "modifier_elements": [],
    "modifier_amount": None,
    "modifier_unit": "",
    "modifier_site": "",
    "phase_type": "",
    "synthesis_route": "",
    "annealing_condition": "",
    "notes": "",
}


def read_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=False)
        handle.write("\n")


def write_markdown(path, batches, samples):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(batches, samples), encoding="utf-8")


def load_json_with_markdown_edits(markdown_path, batches_path, samples_path):
    batches = read_json(batches_path, [])
    samples = read_json(samples_path, [])

    if not markdown_path.exists():
        return batches, samples, False

    parsed_batches, parsed_samples = parse_markdown(markdown_path, batches, samples)
    batches = merge_records(parsed_batches, batches, "batch_id", BATCH_FIELDS)
    samples = merge_records(parsed_samples, samples, "sample_id", SAMPLE_FIELDS)
    batches = sorted(batches, key=lambda record: record.get("batch_id", ""))
    samples = sorted(
        samples,
        key=lambda record: (record.get("batch_id", ""), record.get("sample_id", "")),
    )

    return batches, samples, True


def relative_path(path):
    return get_workspace().relative_or_posix(path)


def existing_by_key(records, key):
    return {record[key]: record for record in records if key in record}


def _scan_batch_folder(batch_dir: Path, batch_id: str, discovered: dict, material_family: str = "") -> None:
    for raw_file in sorted(path for path in batch_dir.iterdir() if path.is_file()):
        if raw_file.name.startswith("~$"):
            continue  # Excel lock files are not sample data.
        match = RAW_FILE_PATTERN.match(raw_file.name)
        if not match:
            continue

        sample_id = match.group("sample_id")
        kind = match.group("kind").lower()
        if match.group("ext").lower() == "xlsx" and kind != "lfa":
            continue
        sample = discovered.setdefault(
            sample_id,
            {
                "sample_id": sample_id,
                "batch_id": batch_id,
            },
        )
        if material_family and not sample.get("material_family"):
            sample["material_family"] = material_family
        sample[kind] = relative_path(raw_file)


def discover_raw_samples(raw_dir):
    discovered = {}
    ws = get_workspace()

    for entry_dir in sorted(path for path in Path(raw_dir).iterdir() if path.is_dir()):
        direct_before = len(discovered)
        _scan_batch_folder(entry_dir, entry_dir.name, discovered)
        if len(discovered) == direct_before and ws.grouping_mode == "by_system_batch":
            # Scan two-level <raw>/<system>/<batch_id>/ layout
            for sub_batch_dir in sorted(p for p in entry_dir.iterdir() if p.is_dir()):
                _scan_batch_folder(sub_batch_dir, sub_batch_dir.name, discovered, material_family=entry_dir.name)

    return discovered


def infer_sample_label(sample_id, batch_id):
    prefix = f"{batch_id}-"
    if sample_id.startswith(prefix):
        return sample_id[len(prefix):]
    return sample_id


def build_processed_path(batch_id, sample_id, system=""):
    ws = get_workspace()
    return ws.relative_or_posix(ws.processed_sample_csv(batch_id, sample_id, system=system or None))


def merge_batch_records(existing_batches, discovered_samples):
    batches_by_id = existing_by_key(existing_batches, "batch_id")

    for sample in discovered_samples.values():
        batch_id = sample["batch_id"]
        if batch_id not in batches_by_id:
            batches_by_id[batch_id] = {
                "batch_id": batch_id,
                "project": "",
                "matrix_composition": "",
                "pristine_composition": "",
                "material_family": sample.get("material_family", ""),
                "notes": "Auto-created from raw folder scan; fill manually.",
            }

    return sorted(batches_by_id.values(), key=lambda record: record["batch_id"])


def merge_sample_records(existing_samples, discovered_samples):
    samples_by_id = existing_by_key(existing_samples, "sample_id")

    for sample_id, discovered in discovered_samples.items():
        batch_id = discovered["batch_id"]
        existing = samples_by_id.get(sample_id, {})
        sample_name = existing.get("sample_name") or infer_sample_label(sample_id, batch_id)
        # Preserve a manually curated processed path; only default when unset.
        processed_file = existing.get("processed_file") or build_processed_path(
            batch_id, sample_id, system=discovered.get("material_family", "")
        )

        ws = get_workspace()
        proc_check = Path(processed_file)
        if not proc_check.is_absolute():
            proc_check = ws.root / proc_check

        merged = {
            "sample_id": sample_id,
            "batch_id": batch_id,
            "sample_name": sample_name,
            "zem": discovered.get("zem", existing.get("zem", "")),
            "lfa": discovered.get("lfa", existing.get("lfa", "")),
            "processed_file": processed_file,
            "processed_exists": proc_check.exists(),
        }

        for key, value in CHEMISTRY_DEFAULTS.items():
            merged[key] = existing.get(key, value)

        for key, value in existing.items():
            if key not in merged:
                merged[key] = value

        samples_by_id[sample_id] = merged

    return sorted(
        samples_by_id.values(),
        key=lambda record: (record.get("batch_id", ""), record.get("sample_id", "")),
    )


def main():
    ws = get_workspace()
    parser = argparse.ArgumentParser(
        description="Update metadata batches.json and samples.json from raw measurement folders."
    )
    parser.add_argument("--raw-dir", default=str(ws.raw_dir))
    parser.add_argument("--batches-json", default=str(ws.batches_json))
    parser.add_argument("--samples-json", default=str(ws.samples_json))
    parser.add_argument("--markdown", default=str(ws.lab_markdown))
    parser.add_argument(
        "--no-markdown-sync",
        action="store_true",
        help="Skip importing Markdown edits before the raw scan and exporting updated Markdown after JSON sync.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    batches_path = Path(args.batches_json)
    samples_path = Path(args.samples_json)
    markdown_path = Path(args.markdown)

    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw data folder does not exist: {raw_dir}")

    if args.no_markdown_sync:
        existing_batches = read_json(batches_path, [])
        existing_samples = read_json(samples_path, [])
    else:
        existing_batches, existing_samples, imported_markdown = load_json_with_markdown_edits(
            markdown_path,
            batches_path,
            samples_path,
        )
        if imported_markdown:
            print(f"Loaded Markdown edits from {markdown_path}")

    discovered_samples = discover_raw_samples(raw_dir)

    updated_batches = merge_batch_records(existing_batches, discovered_samples)
    updated_samples = merge_sample_records(existing_samples, discovered_samples)

    new_batches = len(updated_batches) - len(existing_batches)
    new_samples = len(updated_samples) - len(existing_samples)

    print(f"Discovered {len(discovered_samples)} samples from {raw_dir}")
    print(f"Batches: {len(existing_batches)} -> {len(updated_batches)} ({new_batches:+d})")
    print(f"Samples: {len(existing_samples)} -> {len(updated_samples)} ({new_samples:+d})")

    if args.dry_run:
        print("Dry run only; no files were changed.")
        if not args.no_markdown_sync:
            print(f"Markdown would be refreshed at {markdown_path}")
        return

    write_json(batches_path, updated_batches)
    write_json(samples_path, updated_samples)
    print(f"Updated {batches_path}")
    print(f"Updated {samples_path}")

    if not args.no_markdown_sync:
        write_markdown(markdown_path, updated_batches, updated_samples)
        print(f"Updated {markdown_path}")


if __name__ == "__main__":
    main()

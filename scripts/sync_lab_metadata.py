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
from pathlib import Path

try:
    from scripts.sync_lab_markdown import (
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
    r"^(?P<sample_id>.+)_(?P<kind>ZEM|LFA)\.(?P<ext>txt|csv)$",
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

    markdown_text = markdown_path.read_text(encoding="utf-8")
    has_records = "lab-sync:" in markdown_text or re.search(
        r"^###\s+(Batch|Sample)\s+",
        markdown_text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    if not has_records:
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
    return path.as_posix()


def existing_by_key(records, key):
    return {record[key]: record for record in records if key in record}


def discover_raw_samples(raw_dir):
    discovered = {}

    for batch_dir in sorted(path for path in raw_dir.iterdir() if path.is_dir()):
        batch_id = batch_dir.name

        for raw_file in sorted(path for path in batch_dir.iterdir() if path.is_file()):
            match = RAW_FILE_PATTERN.match(raw_file.name)
            if not match:
                continue

            sample_id = match.group("sample_id")
            kind = match.group("kind").lower()
            sample = discovered.setdefault(
                sample_id,
                {
                    "sample_id": sample_id,
                    "batch_id": batch_id,
                },
            )
            sample[kind] = relative_path(raw_file)

    return discovered


def infer_sample_label(sample_id, batch_id):
    prefix = f"{batch_id}-"
    if sample_id.startswith(prefix):
        return sample_id[len(prefix):]
    return sample_id


def build_processed_path(batch_id, sample_id):
    return f"data/processed/{batch_id}-processed/{sample_id}.csv"


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
                "material_family": "",
                "notes": "Auto-created from data/raw scan; fill manually.",
            }

    return sorted(batches_by_id.values(), key=lambda record: record["batch_id"])


def merge_sample_records(existing_samples, discovered_samples):
    samples_by_id = existing_by_key(existing_samples, "sample_id")

    for sample_id, discovered in discovered_samples.items():
        batch_id = discovered["batch_id"]
        existing = samples_by_id.get(sample_id, {})
        sample_name = existing.get("sample_name") or infer_sample_label(sample_id, batch_id)
        default_processed_file = build_processed_path(batch_id, sample_id)
        processed_file = default_processed_file

        merged = {
            "sample_id": sample_id,
            "batch_id": batch_id,
            "sample_name": sample_name,
            "zem": discovered.get("zem", existing.get("zem", "")),
            "lfa": discovered.get("lfa", existing.get("lfa", "")),
            "processed_file": processed_file,
            "processed_exists": Path(processed_file).exists(),
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
    parser = argparse.ArgumentParser(
        description="Update data/lab/batches.json and data/lab/samples.json from data/raw."
    )
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--batches-json", default="data/lab/batches.json")
    parser.add_argument("--samples-json", default="data/lab/samples.json")
    parser.add_argument("--markdown", default="data/lab/lab_metadata.md")
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

#!/usr/bin/env python3
"""
Export lab metadata JSON to editable Markdown and sync Markdown edits back to JSON.

Default workflow:
  1. python scripts/sync_lab_markdown.py export
  2. Edit data/lab/lab_metadata.md
  3. python scripts/sync_lab_markdown.py

The default command is import, so step 3 writes Markdown values back to JSON.
"""

import argparse
import json
import re
from pathlib import Path


BATCH_FIELDS = [
    "batch_id",
    "project",
    "matrix_composition",
    "pristine_composition",
    "material_family",
    "notes",
]

SAMPLE_FIELDS = [
    "sample_id",
    "batch_id",
    "sample_name",
    "zem",
    "lfa",
    "processed_file",
    "processed_exists",
    "density",
    "cp_value",
    "matrix_composition",
    "pristine_composition",
    "sample_composition",
    "optimization_type",
    "modifier_species",
    "modifier_element",
    "modifier_elements",
    "modifier_amount",
    "modifier_unit",
    "modifier_site",
    "phase_type",
    "synthesis_route",
    "annealing_condition",
    "notes",
]

FIELD_TYPES = {
    "density": "number",
    "cp_value": "number",
    "modifier_amount": "number_or_list",
    "modifier_elements": "list",
    "processed_exists": "bool",
}

MARKER_RE = re.compile(r"^<!--\s*lab-sync:(batch|sample)\s+(.+?)\s*-->\s*$")
HEADING_RE = re.compile(r"^###\s+(Batch|Sample)\s+(.+?)\s*$", re.IGNORECASE)
LIST_SEPARATOR_RE = re.compile(r"\s*(?:,|;|\x1f)\s*")


class MarkdownSyncError(ValueError):
    pass


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


def ordered_fields(records, preferred_fields):
    fields = list(preferred_fields)
    seen = set(fields)

    for record in records:
        for field in record:
            if field not in seen:
                fields.append(field)
                seen.add(field)

    return fields


def markdown_value(value):
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, list):
        text = ", ".join(str(item) for item in value)
    else:
        text = str(value)

    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def split_markdown_row(line):
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        raise MarkdownSyncError(f"Expected a Markdown table row, got: {line}")

    content = stripped[1:-1]
    cells = []
    current = []
    escaped = False

    for char in content:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)

    if escaped:
        current.append("\\")

    cells.append("".join(current).strip())
    return [cell.replace("<br>", "\n") for cell in cells]


def is_separator_row(line):
    try:
        cells = split_markdown_row(line)
    except MarkdownSyncError:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def parse_bool(field, text):
    normalized = text.strip().lower()
    if normalized in {"true", "yes", "y", "1"}:
        return True
    if normalized in {"false", "no", "n", "0", ""}:
        return False
    raise MarkdownSyncError(
        f"Field {field!r} expects a boolean value like true or false, got {text!r}"
    )


def parse_list(field, text):
    stripped = text.strip()
    if not stripped:
        return []

    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise MarkdownSyncError(
                f"Field {field!r} contains invalid JSON list syntax: {text!r}"
            ) from error
        if not isinstance(parsed, list):
            raise MarkdownSyncError(f"Field {field!r} must be a list.")
        return parsed

    return [item.strip() for item in LIST_SEPARATOR_RE.split(stripped) if item.strip()]


def parse_number(field, text):
    stripped = text.strip()
    if not stripped or stripped.lower() == "null":
        return None

    try:
        return float(stripped)
    except ValueError as error:
        raise MarkdownSyncError(
            f"Field {field!r} expects a number or blank value, got {text!r}"
        ) from error


def parse_number_or_list(field, text):
    stripped = text.strip()
    if not stripped or stripped.lower() == "null":
        return None

    if "\x1f" not in stripped and "," not in stripped and ";" not in stripped:
        return parse_number(field, stripped)

    values = []
    for item in LIST_SEPARATOR_RE.split(stripped):
        if not item:
            continue
        values.append(parse_number(field, item))
    return values or None


def parse_text(text):
    return text.replace("\x1f", ", ")


def parse_unknown(text, existing_value=None):
    stripped = text.strip()

    if isinstance(existing_value, bool):
        return parse_bool("unknown", stripped)
    if isinstance(existing_value, list):
        return parse_list("unknown", stripped)
    if isinstance(existing_value, (int, float)) or existing_value is None:
        lowered = stripped.lower()
        if lowered in {"", "null"}:
            return None
        if lowered in {"true", "false"}:
            return lowered == "true"
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return parse_text(text)

    return parse_text(text)


def parse_value(field, text, existing_value=None):
    field_type = FIELD_TYPES.get(field)

    if field_type == "bool":
        return parse_bool(field, text)
    if field_type == "list":
        return parse_list(field, text)
    if field_type == "number":
        return parse_number(field, text)
    if field_type == "number_or_list":
        return parse_number_or_list(field, text)

    if existing_value is not None and not isinstance(existing_value, str):
        return parse_unknown(text, existing_value)

    return parse_text(text)


def record_table(record, fields, preferred_fields):
    preferred = set(preferred_fields)
    lines = [
        "| Field | Value |",
        "| --- | --- |",
    ]

    for field in fields:
        if field not in record and field not in preferred:
            continue
        value = markdown_value(record.get(field, ""))
        lines.append(f"| {field} | {value} |")

    return "\n".join(lines)


def render_markdown(batches, samples):
    batch_fields = ordered_fields(batches, BATCH_FIELDS)
    sample_fields = ordered_fields(samples, SAMPLE_FIELDS)

    lines = [
        "# Lab Metadata",
        "",
        "Edit the values in the tables below, then run:",
        "",
        "```bash",
        "python scripts/sync_lab_markdown.py",
        "```",
        "",
        "Keep the `### Batch ...` / `### Sample ...` headings and `Field` names unchanged so the sync script can find each record.",
        "`lab-sync` comments are optional; some Markdown editors may hide or remove them.",
        "Blank numeric values become `null`; comma-separated list values become JSON arrays.",
        "",
        "## Batches",
        "",
    ]

    for batch in sorted(batches, key=lambda item: item.get("batch_id", "")):
        batch_id = batch.get("batch_id", "")
        lines.extend(
            [
                f"<!-- lab-sync:batch {batch_id} -->",
                f"### Batch {batch_id}",
                "",
                record_table(batch, batch_fields, BATCH_FIELDS),
                "",
            ]
        )

    lines.extend(["## Samples", ""])

    for sample in sorted(
        samples,
        key=lambda item: (item.get("batch_id", ""), item.get("sample_id", "")),
    ):
        sample_id = sample.get("sample_id", "")
        lines.extend(
            [
                f"<!-- lab-sync:sample {sample_id} -->",
                f"### Sample {sample_id}",
                "",
                record_table(sample, sample_fields, SAMPLE_FIELDS),
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def find_next_table(lines, start_index, marker_text, stop_on_heading=False):
    index = start_index

    while index < len(lines):
        line = lines[index]
        if MARKER_RE.match(line):
            break
        if stop_on_heading and HEADING_RE.match(line):
            break
        if line.strip().startswith("|"):
            table = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table.append(lines[index])
                index += 1
            return table
        index += 1

    raise MarkdownSyncError(f"Could not find a table after marker {marker_text!r}.")


def parse_record_table(table, marker_text, existing_record=None):
    if len(table) < 3:
        raise MarkdownSyncError(f"Table after marker {marker_text!r} is too short.")

    header = [cell.lower() for cell in split_markdown_row(table[0])]
    if header[:2] != ["field", "value"]:
        raise MarkdownSyncError(
            f"Table after marker {marker_text!r} must start with Field and Value columns."
        )
    if not is_separator_row(table[1]):
        raise MarkdownSyncError(
            f"Table after marker {marker_text!r} is missing the Markdown separator row."
        )

    record = {}
    existing_record = existing_record or {}

    for row in table[2:]:
        cells = split_markdown_row(row)
        if len(cells) < 2:
            continue

        field = cells[0].strip()
        value = cells[1]
        if not field:
            continue

        record[field] = parse_value(field, value, existing_record.get(field))

    return record


def existing_by_id(records, key):
    return {record.get(key): record for record in records if record.get(key)}


def parse_markdown(markdown_path, existing_batches, existing_samples):
    lines = markdown_path.read_text(encoding="utf-8").splitlines()
    existing_batches_by_id = existing_by_id(existing_batches, "batch_id")
    existing_samples_by_id = existing_by_id(existing_samples, "sample_id")
    batches = []
    samples = []

    for index, line in enumerate(lines):
        marker = MARKER_RE.match(line)
        heading = None
        if not marker:
            heading = HEADING_RE.match(line)
            if not heading or (index > 0 and MARKER_RE.match(lines[index - 1])):
                continue

        if marker:
            record_type, marker_id = marker.groups()
            stop_on_heading = False
        else:
            record_type, marker_id = heading.groups()
            record_type = record_type.lower()
            stop_on_heading = True

        marker_id = marker_id.strip()
        table = find_next_table(
            lines,
            index + 1,
            line,
            stop_on_heading=stop_on_heading,
        )

        if record_type == "batch":
            existing_record = existing_batches_by_id.get(marker_id, {})
            record = parse_record_table(table, line, existing_record)
            record.setdefault("batch_id", marker_id)
            batches.append(record)
        else:
            existing_record = existing_samples_by_id.get(marker_id, {})
            record = parse_record_table(table, line, existing_record)
            record.setdefault("sample_id", marker_id)
            samples.append(record)

    if not batches:
        raise MarkdownSyncError(f"No batch records found in {markdown_path}.")
    if not samples:
        raise MarkdownSyncError(f"No sample records found in {markdown_path}.")

    return batches, samples


def merge_records(parsed_records, existing_records, key, preferred_fields):
    existing = existing_by_id(existing_records, key)
    merged_records = []
    seen_ids = set()

    for parsed in parsed_records:
        record_id = parsed.get(key)
        if not record_id:
            raise MarkdownSyncError(f"Missing required field {key!r}.")
        if record_id in seen_ids:
            raise MarkdownSyncError(f"Duplicate {key}: {record_id}")
        seen_ids.add(record_id)

        prior = existing.get(record_id, {})
        fields = ordered_fields([parsed, prior], preferred_fields)
        merged = {}
        for field in fields:
            if field in parsed:
                merged[field] = parsed[field]
            elif field in prior:
                merged[field] = prior[field]
        merged_records.append(merged)

    return merged_records


def export_markdown(args):
    batches = read_json(args.batches_json, [])
    samples = read_json(args.samples_json, [])
    markdown = render_markdown(batches, samples)

    if args.dry_run:
        print(markdown)
        return

    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(markdown, encoding="utf-8")
    print(f"Exported {len(batches)} batches and {len(samples)} samples to {args.markdown}")


def import_markdown(args):
    existing_batches = read_json(args.batches_json, [])
    existing_samples = read_json(args.samples_json, [])
    if not args.markdown.exists():
        print(f"No Markdown metadata found at {args.markdown}; nothing to import.")
        return

    markdown_text = args.markdown.read_text(encoding="utf-8")
    has_records = "lab-sync:" in markdown_text or re.search(
        r"^###\s+(Batch|Sample)\s+",
        markdown_text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    if not has_records:
        print(f"No batch/sample records found in {args.markdown}; nothing to import.")
        return

    parsed_batches, parsed_samples = parse_markdown(
        args.markdown,
        existing_batches,
        existing_samples,
    )

    batches = merge_records(parsed_batches, existing_batches, "batch_id", BATCH_FIELDS)
    samples = merge_records(parsed_samples, existing_samples, "sample_id", SAMPLE_FIELDS)
    batches = sorted(batches, key=lambda item: item.get("batch_id", ""))
    samples = sorted(samples, key=lambda item: (item.get("batch_id", ""), item.get("sample_id", "")))

    if args.dry_run:
        print(f"Would update {args.batches_json} with {len(batches)} batches.")
        print(f"Would update {args.samples_json} with {len(samples)} samples.")
        return

    write_json(args.batches_json, batches)
    write_json(args.samples_json, samples)
    print(f"Updated {args.batches_json} from {args.markdown}")
    print(f"Updated {args.samples_json} from {args.markdown}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Sync editable lab metadata Markdown with JSON files."
    )
    parser.add_argument(
        "command",
        choices=["export", "import"],
        nargs="?",
        default="import",
        help="Use export to create Markdown from JSON, or import to write Markdown edits to JSON.",
    )
    parser.add_argument("--markdown", type=Path, default=Path("data/lab/lab_metadata.md"))
    parser.add_argument("--batches-json", type=Path, default=Path("data/lab/batches.json"))
    parser.add_argument("--samples-json", type=Path, default=Path("data/lab/samples.json"))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "export":
        export_markdown(args)
    else:
        import_markdown(args)


if __name__ == "__main__":
    main()

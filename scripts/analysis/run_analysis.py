import json
import logging
import os
import re
import subprocess
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_MPL_CACHE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "te_matplotlib_cache"
_MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(_MPL_CACHE_DIR))

from te_analysis import te_analysis
from scripts.sync_lab_metadata import (
    discover_raw_samples,
    merge_batch_records,
    merge_sample_records,
    read_json,
    write_json,
)


LAB_MARKDOWN_PATH = PROJECT_ROOT / "data" / "lab" / "lab_metadata.md"
LAB_MARKDOWN_SYNC_SCRIPT = PROJECT_ROOT / "scripts" / "sync_lab_markdown.py"
DEFAULT_TARGET_BATCHES = ["CHY-1048"]


def load_json(file_path, default):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"❌ JSON NOT FOUND: {file_path}")
        return default
    except json.JSONDecodeError:
        print(f"❌ JSON FORMAT WRONG: {file_path}")
        return default


def load_flat_lab_ledger(
    batches_path="data/lab/batches.json",
    samples_path="data/lab/samples.json",
):
    batches = load_json(batches_path, [])
    samples = load_json(samples_path, [])
    ledger = {}

    for batch in batches:
        batch_id = batch.get("batch_id")
        if not batch_id:
            continue
        ledger[batch_id] = {
            "batch_metadata": {
                "matrix_composition": batch.get("matrix_composition", ""),
                "pristine_composition": batch.get("pristine_composition", ""),
                "material_family": batch.get("material_family", ""),
                "notes": batch.get("notes", ""),
            }
        }

    for sample in samples:
        batch_id = sample.get("batch_id")
        if not batch_id:
            continue

        sample_id = sample.get("sample_id")
        sample_name = sample.get("sample_name") or sample_id
        if not sample_name:
            continue

        ledger.setdefault(batch_id, {"batch_metadata": {}})
        if (
            sample_name in ledger[batch_id]
            and ledger[batch_id][sample_name].get("sample_id") != sample_id
            and sample_id
        ):
            sample_name = sample_id

        ledger[batch_id][sample_name] = {
            key: value
            for key, value in sample.items()
            if key not in {"batch_id", "processed_file", "processed_exists", "legacy_sample_name"}
        }

    return ledger


def load_lab_ledger(file_path="configs/lab_batches.json"):
    flat_ledger = load_flat_lab_ledger()
    if flat_ledger:
        return flat_ledger

    return load_json(file_path, {})


ALL_LAB_BATCHES = {}


def sync_lab_metadata_from_markdown():
    if not LAB_MARKDOWN_PATH.exists():
        raise FileNotFoundError(
            f"Markdown metadata file not found: {LAB_MARKDOWN_PATH}. "
            "Run `python scripts/sync_lab_markdown.py export` first."
        )

    print("Syncing data/lab/lab_metadata.md -> data/lab/*.json...", flush=True)
    command = [
        sys.executable,
        str(LAB_MARKDOWN_SYNC_SCRIPT),
        "--markdown",
        str(LAB_MARKDOWN_PATH),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def normalize_batch_id(selector):
    selector = str(selector).strip()
    if selector.startswith("Batch-"):
        selector = selector.replace("Batch-", "CHY-", 1)
    if selector.isdigit() or (selector and selector[0].isdigit()):
        selector = f"CHY-{selector}"
    return selector


def parse_batch_sample_selector(selector):
    """
    Split selectors like CHY-1054-B, 1054-B, CHY-1054/B, or CHY-1054:B.

    Returns (batch_id, sample_selector). sample_selector is None for a whole
    batch selector such as CHY-1054.
    """
    raw = str(selector or "").strip()
    if not raw:
        return "", None

    normalized = raw.replace("Batch-", "CHY-", 1)
    match = re.match(r"^(?:CHY-)?(\d+)(?:[-/:](.+))?$", normalized)
    if not match:
        return normalize_batch_id(normalized), None

    batch_id = f"CHY-{match.group(1)}"
    sample_part = match.group(2)
    if not sample_part:
        return batch_id, None

    separator = "/" if "/" in normalized else ":" if ":" in normalized else "-"
    return batch_id, f"{batch_id}{separator}{sample_part}"


def parse_qualified_sample_selector(selector):
    """Return a scoped sample selector when the selector includes a batch id."""
    batch_id, sample_selector = parse_batch_sample_selector(selector)
    if sample_selector:
        return batch_id, sample_selector
    return "", str(selector or "").strip()


def add_unique(targets, value):
    if value and value not in targets:
        targets.append(value)


def build_batch_sample_selection(
    target_selectors=None,
    sample_selectors=None,
    analyze_all=False,
):
    """
    Build batch targets plus optional per-batch sample filters.

    Positional selectors can be whole batches or individual samples. Explicit
    --sample/--samples selectors are applied to the selected batches unless they
    already include a batch id.
    """
    batch_targets = []
    sample_targets_by_batch = {}

    for selector in target_selectors or []:
        batch_id, sample_selector = parse_batch_sample_selector(selector)
        add_unique(batch_targets, batch_id)
        if sample_selector:
            sample_targets_by_batch.setdefault(batch_id, []).append(sample_selector)

    unqualified_samples = []
    for selector in sample_selectors or []:
        batch_id, sample_selector = parse_qualified_sample_selector(selector)
        if batch_id:
            add_unique(batch_targets, batch_id)
            sample_targets_by_batch.setdefault(batch_id, []).append(sample_selector)
        else:
            unqualified_samples.append(sample_selector)

    if unqualified_samples:
        scoped_batches = batch_targets or ([] if analyze_all else list(DEFAULT_TARGET_BATCHES))
        for batch_id in scoped_batches:
            add_unique(batch_targets, batch_id)
            sample_targets_by_batch.setdefault(batch_id, []).extend(unqualified_samples)

    if not batch_targets and not analyze_all:
        batch_targets = list(DEFAULT_TARGET_BATCHES)

    return batch_targets, sample_targets_by_batch


def sync_lab_metadata_from_raw(target_batches=None):
    raw_dir = Path("data/raw")
    batches_path = Path("data/lab/batches.json")
    samples_path = Path("data/lab/samples.json")

    if not raw_dir.exists():
        return

    target_batch_ids = {normalize_batch_id(batch_id) for batch_id in target_batches or []}
    existing_batches = read_json(batches_path, [])
    existing_samples = read_json(samples_path, [])
    discovered_samples = discover_raw_samples(raw_dir)
    if target_batch_ids:
        discovered_samples = {
            sample_id: sample
            for sample_id, sample in discovered_samples.items()
            if sample.get("batch_id") in target_batch_ids
        }

    updated_batches = merge_batch_records(existing_batches, discovered_samples)
    updated_samples = merge_sample_records(existing_samples, discovered_samples)

    write_json(batches_path, updated_batches)
    write_json(samples_path, updated_samples)


def export_lab_metadata_to_markdown():
    print("Refreshing data/lab/lab_metadata.md from data/lab/*.json...", flush=True)
    command = [
        sys.executable,
        str(LAB_MARKDOWN_SYNC_SCRIPT),
        "export",
        "--markdown",
        str(LAB_MARKDOWN_PATH),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def resolve_target_batches(target_batches, analyze_all=False):
    if analyze_all:
        return sorted(ALL_LAB_BATCHES)
    if target_batches:
        return [normalize_batch_id(batch_id) for batch_id in target_batches]
    return list(DEFAULT_TARGET_BATCHES)


def execute_selected_batches(
    target_batches=None,
    sample_selectors=None,
    analyze_all=False,
    sync_markdown=True,
    sync_raw=True,
    refresh_markdown_after=True,
    dry_run=False,
    strict=False,
):
    global ALL_LAB_BATCHES

    os.chdir(PROJECT_ROOT)

    normalized_targets, sample_targets_by_batch = build_batch_sample_selection(
        target_batches,
        sample_selectors=sample_selectors,
        analyze_all=analyze_all,
    )
    if dry_run:
        sync_markdown = False
        sync_raw = False

    if sync_markdown:
        try:
            sync_lab_metadata_from_markdown()
        except FileNotFoundError as error:
            raise SystemExit(str(error)) from error
        except subprocess.CalledProcessError as error:
            raise SystemExit(
                "Markdown lab metadata sync failed. Fix data/lab/lab_metadata.md "
                "before running analysis."
            ) from error

    if sync_raw:
        print("Syncing selected raw folders -> data/lab/*.json...", flush=True)
        sync_lab_metadata_from_raw(normalized_targets if not analyze_all else None)

    ALL_LAB_BATCHES = load_lab_ledger()

    if not ALL_LAB_BATCHES:
        return

    selected_batches = resolve_target_batches(normalized_targets, analyze_all=analyze_all)
    if dry_run:
        print("Dry run only; selected batches:")
        for batch_id in selected_batches:
            status = "found" if batch_id in ALL_LAB_BATCHES else "missing"
            samples = sample_targets_by_batch.get(batch_id, [])
            sample_text = f"; samples: {', '.join(samples)}" if samples else ""
            print(f"  - {batch_id}: {status}{sample_text}")
        return

    for batch_id in selected_batches:
        if batch_id not in ALL_LAB_BATCHES:
            print(f"Syncing {batch_id} from data/raw...")
            sync_lab_metadata_from_raw([batch_id])
            ALL_LAB_BATCHES = load_lab_ledger()

        if batch_id in ALL_LAB_BATCHES:
            print(f"\n{'='*50}")
            print(f"▶️ Running Analysis for: {batch_id}")
            print(f"{'='*50}")
            
            batch_files = ALL_LAB_BATCHES[batch_id]
            te_analysis(
                batch_id,
                batch_files,
                sample_selectors=sample_targets_by_batch.get(batch_id),
                strict=strict,
            )
        else:
            message = f"⚠️ {batch_id} not found"
            if strict:
                raise SystemExit(message)
            logging.warning(message)

    if sync_raw:
        print("Refreshing processed_exists flags after analysis...", flush=True)
        sync_lab_metadata_from_raw(selected_batches)
        if sync_markdown and refresh_markdown_after:
            export_lab_metadata_to_markdown()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run TE raw-data analysis for selected lab batches."
    )
    parser.add_argument(
        "batches",
        nargs="*",
        help=(
            "Batch ids to analyze. Examples: CHY-1048, 1048, CHY-1038 CHY-1040. "
            f"If omitted, defaults to {' '.join(DEFAULT_TARGET_BATCHES)}."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Analyze every batch currently listed in data/lab/batches.json.",
    )
    parser.add_argument(
        "--sample",
        "--samples",
        dest="samples",
        nargs="+",
        default=[],
        help=(
            "Analyze only selected samples within the selected batch. Examples: "
            "--sample B, --samples B C, or --sample CHY-1054-B. Positional "
            "sample selectors such as CHY-1054-B also work."
        ),
    )
    parser.add_argument(
        "--no-markdown-sync",
        action="store_true",
        help="Do not import data/lab/lab_metadata.md before analysis.",
    )
    parser.add_argument(
        "--no-raw-sync",
        action="store_true",
        help="Do not scan data/raw before or after analysis.",
    )
    parser.add_argument(
        "--no-markdown-refresh",
        action="store_true",
        help="Do not export refreshed JSON metadata back to data/lab/lab_metadata.md after analysis.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show selected batches without running analysis.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with an error if any selected batch is missing.",
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    execute_selected_batches(
        args.batches,
        sample_selectors=args.samples,
        analyze_all=args.all,
        sync_markdown=not args.no_markdown_sync,
        sync_raw=not args.no_raw_sync,
        refresh_markdown_after=not args.no_markdown_refresh,
        dry_run=args.dry_run,
        strict=args.strict,
    )

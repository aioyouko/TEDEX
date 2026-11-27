import json
import logging
import os
import re
import subprocess
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

_MPL_CACHE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "te_matplotlib_cache"
_MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(_MPL_CACHE_DIR))

from te_analysis.paths import get_workspace
from te_analysis.pipeline.te_analysis_pipeline import te_analysis
from te_analysis.tools.figure_naming import add_rename_argument, figure_output_naming
from te_analysis.tools.selectors import (
    normalize_batch_id,
    parse_batch_sample_selector,
    parse_qualified_sample_selector,
)
from te_analysis.sync.metadata import (
    discover_raw_samples,
    merge_batch_records,
    merge_sample_records,
    read_json,
    write_json,
)


LAB_MARKDOWN_SYNC_SCRIPT = PROJECT_ROOT / "te_analysis" / "sync" / "markdown.py"
DEFAULT_TARGET_BATCHES = get_workspace().default_batches


def load_json(file_path, default, quiet_missing=False):
    path = Path(file_path)
    if not path.exists():
        if not quiet_missing:
            print(f"❌ JSON NOT FOUND: {file_path}")
        return default
    try:
        with path.open('r', encoding='utf-8') as file:
            return json.load(file)
    except json.JSONDecodeError:
        print(f"❌ JSON FORMAT WRONG: {file_path}")
        return default


def load_flat_lab_ledger(
    batches_path=None,
    samples_path=None,
):
    ws = get_workspace()
    b_path = Path(batches_path) if batches_path is not None else ws.batches_json
    s_path = Path(samples_path) if samples_path is not None else ws.samples_json
    batches = load_json(b_path, [], quiet_missing=True)
    samples = load_json(s_path, [], quiet_missing=True)
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


def load_lab_ledger(file_path=None):
    flat_ledger = load_flat_lab_ledger()
    if flat_ledger:
        return flat_ledger

    fallback = Path(file_path) if file_path is not None else get_workspace().legacy_lab_batches_json
    return load_json(fallback, {}, quiet_missing=True)


ALL_LAB_BATCHES = {}


def sync_lab_metadata_from_markdown():
    ws = get_workspace()
    md_path = ws.lab_markdown
    if not md_path.exists():
        raise FileNotFoundError(
            f"Markdown metadata file not found: {md_path}. "
            "Run `te init` or `te sync markdown export` first."
        )

    print(f"Syncing {ws.relative_or_posix(md_path)} -> {ws.relative_or_posix(ws.metadata_dir)}/*.json...", flush=True)
    command = [
        sys.executable,
        str(LAB_MARKDOWN_SYNC_SCRIPT),
        "--markdown",
        str(md_path),
        "--batches-json",
        str(ws.batches_json),
        "--samples-json",
        str(ws.samples_json),
    ]
    subprocess.run(command, cwd=ws.root, check=True)





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
    ws = get_workspace()
    raw_dir = ws.raw_dir
    batches_path = ws.batches_json
    samples_path = ws.samples_json

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
    ws = get_workspace()
    md_path = ws.lab_markdown
    print(f"Refreshing {ws.relative_or_posix(md_path)} from {ws.relative_or_posix(ws.metadata_dir)}/*.json...", flush=True)
    command = [
        sys.executable,
        str(LAB_MARKDOWN_SYNC_SCRIPT),
        "export",
        "--markdown",
        str(md_path),
        "--batches-json",
        str(ws.batches_json),
        "--samples-json",
        str(ws.samples_json),
    ]
    subprocess.run(command, cwd=ws.root, check=True)


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

    ws = get_workspace()
    os.chdir(ws.root)

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
            "Batch ids to analyze. Examples: TE-1048, 1048, TE-1038 TE-1040. "
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
            "--sample B, --samples B C, or --sample TE-1054-B. Positional "
            "sample selectors such as TE-1054-B also work."
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
    add_rename_argument(parser)
    return parser.parse_args()


def _run_cli(args):
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


def main():
    args = parse_args()
    with figure_output_naming(args.rename):
        return _run_cli(args)


if __name__ == "__main__":
    main()

"""Run the LLM mechanism analysis on batches that `analyze` has processed.

Usage:
    python main.py agent CHY-1040 CHY-1038
    python main.py agent CHY-1040 --matrix Cu0.8Ag0.2In0.5Ga0.5Te2
    python main.py agent data/processed/CHY-1048-processed/extracted_features.json

Each target is a batch ID or a path to an extracted_features.json file. The
base matrix composition comes from --matrix, else from the lab ledger
(data/lab/batches.json, then configs/lab_batches.json), else from the samples
in the features file when they all agree. A target with no matrix fails rather
than being analyzed without one.

Reports go to results/reports/<batch>_Analysis.md and are printed to stdout.
The command exits non-zero if any target fails.

Set MOONSHOT_API_KEY in your shell or .env file. Do not hardcode API keys here.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from te_analysis.agents.core_agent import AgentError, analyze_materials_data  # noqa: E402
from te_analysis.run_manifest import record_output  # noqa: E402
from te_analysis.tools.selectors import normalize_batch_id  # noqa: E402

PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed"
LAB_BATCHES_PATH = PROJECT_ROOT / "data" / "lab" / "batches.json"
LEGACY_BATCHES_PATH = PROJECT_ROOT / "configs" / "lab_batches.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "results" / "reports"


class TargetError(Exception):
    """A target could not be prepared for analysis."""


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_features_path(target: str) -> tuple[str, Path]:
    """Return (batch_id, features_path) for a batch ID or a features file path."""
    candidate = Path(target)
    if candidate.suffix.lower() == ".json" or candidate.is_file():
        if not candidate.is_file():
            raise TargetError(f"features file not found: {candidate}")
        folder = candidate.resolve().parent.name
        batch_id = folder[: -len("-processed")] if folder.endswith("-processed") else folder
        return batch_id, candidate

    batch_id = normalize_batch_id(target)
    path = PROCESSED_ROOT / f"{batch_id}-processed" / "extracted_features.json"
    if not path.is_file():
        raise TargetError(
            f"no extracted features for {batch_id} ({path.relative_to(PROJECT_ROOT).as_posix()}); "
            f"run `python main.py analyze {batch_id}` first"
        )
    return batch_id, path


def ledger_matrix(batch_id: str) -> str:
    for record in read_json(LAB_BATCHES_PATH, []) or []:
        if record.get("batch_id") == batch_id and record.get("matrix_composition"):
            return record["matrix_composition"]
    legacy = read_json(LEGACY_BATCHES_PATH, {}) or {}
    return (legacy.get(batch_id, {}).get("batch_metadata", {}) or {}).get("matrix_composition", "")


def samples_matrix(features: dict) -> str:
    matrices = {
        sample.get("matrix_composition")
        for sample in features.get("samples_data", [])
        if sample.get("matrix_composition")
    }
    return matrices.pop() if len(matrices) == 1 else ""


def analyze_target(target: str, matrix_override: str | None, report_dir: Path) -> Path:
    batch_id, features_path = resolve_features_path(target)
    features = read_json(features_path)
    if not isinstance(features, dict):
        raise TargetError(f"{features_path} does not hold a JSON object")
    batch_id = features.get("batch_name") or batch_id

    matrix = matrix_override or ledger_matrix(batch_id) or samples_matrix(features)
    if not matrix:
        raise TargetError(
            f"no matrix composition found for {batch_id}; pass --matrix or fill "
            "matrix_composition in data/lab/lab_metadata.md"
        )
    features["base_matrix_material"] = matrix

    print(f"\n{'=' * 50}\nAnalyzing {batch_id} | matrix: {matrix}\n{'=' * 50}", flush=True)
    report = analyze_materials_data(features)

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{batch_id}_Analysis.md"
    report_path.write_text(report, encoding="utf-8")
    record_output(report_path)

    print(f"\n================ {batch_id} mechanism analysis ================\n")
    print(report)
    print(f"\nReport saved: {report_path}\n")
    return report_path


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the LLM mechanism analysis on processed batches."
    )
    parser.add_argument(
        "targets",
        nargs="+",
        help="Batch IDs (e.g. CHY-1048) or paths to extracted_features.json files.",
    )
    parser.add_argument(
        "--matrix",
        default=None,
        help="Base matrix composition for every target, overriding the lab ledger.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory for the Markdown reports (default: results/reports).",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)

    failures = []
    for target in args.targets:
        try:
            analyze_target(target, args.matrix, args.output_dir)
        except (TargetError, AgentError) as error:
            print(f"error: {target}: {error}", file=sys.stderr)
            failures.append(target)

    if failures:
        print(f"{len(failures)} of {len(args.targets)} target(s) failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

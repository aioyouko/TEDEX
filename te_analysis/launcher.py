#!/usr/bin/env python3
"""Unified command launcher for the thermoelectric workspace."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from te_analysis.run_manifest import MANIFEST_ENV_VAR, read_manifest  # noqa: E402

JSON_FLAG = "--json"


@dataclass(frozen=True)
class Command:
    name: str
    target: Path
    description: str
    aliases: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


DIRECT_COMMANDS = (
    Command(
        name="analyze",
        target=PROJECT_ROOT / "scripts" / "analysis" / "run_analysis.py",
        description="Run raw ZEM/LFA processing, feature extraction, and TE analysis.",
        aliases=("analysis", "run"),
        examples=("python main.py analyze CHY-1048",),
    ),
    Command(
        name="plot-te",
        target=PROJECT_ROOT / "scripts" / "plotting" / "plot_te.py",
        description="Plot processed thermoelectric properties.",
        aliases=("te-plot", "teplot"),
        examples=("python main.py plot-te CHY-1048 --zt --no-show",),
    ),
    Command(
        name="plot-xrd",
        target=PROJECT_ROOT / "scripts" / "plotting" / "plot_xrd.py",
        description="Plot XRD patterns and optional PDF-card comparisons.",
        aliases=("xrd", "xrd-plot"),
        examples=("python main.py plot-xrd CHY-1056-B --no-show",),
    ),
    Command(
        name="flexible",
        target=PROJECT_ROOT / "scripts" / "plotting" / "flexible_plot.py",
        description="Render flexible plot recipes or direct flexible plots.",
        aliases=("flex",),
        examples=("python main.py flexible --recipe configs/plot_recipes/example.json",),
    ),
    Command(
        name="assess",
        target=PROJECT_ROOT / "scripts" / "analysis" / "assess_selected_batches.py",
        description="Assess selected batches and summarize optimization direction.",
        aliases=("assessment",),
        examples=("python main.py assess CHY-1048",),
    ),
    Command(
        name="bayes",
        target=PROJECT_ROOT / "scripts" / "analysis" / "bayesian_predict_te.py",
        description="Run Bayesian TE prediction workflows.",
        aliases=("bayesian", "predict"),
        examples=("python main.py bayes --help",),
    ),
    Command(
        name="agent",
        target=PROJECT_ROOT / "scripts" / "analysis" / "agent_analysis.py",
        description="Run agent-based analysis from extracted features.",
        aliases=("agent-analysis",),
        examples=(
            "python main.py agent CHY-1048",
            "python main.py agent data/processed/CHY-1048-processed/extracted_features.json",
        ),
    ),
    Command(
        name="xrd-lattice",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "xrd_lattice.py",
        description="Fit lattice parameters from XRD peak positions.",
        aliases=("lattice",),
        examples=("python main.py xrd-lattice --help",),
    ),
)


SPB_COMMANDS = (
    Command(
        name="effective-mass",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "spb" / "effective_mass_fit.py",
        description="Fit SPB density-of-states effective mass from nH-Seebeck data.",
        aliases=("mass", "mstar", "pisarenko"),
        examples=("python main.py spb effective-mass data/demo/spb_fitting/Ag2Se/input.csv",),
    ),
    Command(
        name="conductivity",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "spb" / "conductivity_fit.py",
        description="Fit SPB mobility from conductivity-Seebeck data.",
        aliases=("sigma", "mobility"),
        examples=("python main.py spb conductivity data/demo/spb_fitting/Cu2SSeTe/input.csv",),
    ),
    Command(
        name="performance",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "spb" / "performance_fit.py",
        description="Fit and plot SPB power-factor and zT performance curves.",
        aliases=("fitting", "fit", "pf", "zt"),
        examples=("python main.py spb fitting data/demo/spb_fitting/Ag2Se/input.csv",),
    ),
)


SYNC_COMMANDS = (
    Command(
        name="metadata",
        target=PROJECT_ROOT / "scripts" / "sync_lab_metadata.py",
        description="Sync lab JSON metadata from discovered raw/processed files.",
        aliases=("lab", "raw"),
        examples=("python main.py sync metadata --help",),
    ),
    Command(
        name="markdown",
        target=PROJECT_ROOT / "scripts" / "sync_lab_markdown.py",
        description="Import/export data/lab/lab_metadata.md and lab JSON files.",
        aliases=("md",),
        examples=("python main.py sync markdown export",),
    ),
    Command(
        name="workbook",
        target=PROJECT_ROOT / "scripts" / "sync_lab_workbook.py",
        description="Fill a batch's Cp values and compositions from the lab samples workbook.",
        aliases=("samples-workbook", "cp"),
        examples=("python main.py sync workbook CHY-1090 --dry-run",),
    ),
    Command(
        name="fill",
        target=PROJECT_ROOT / "scripts" / "fill_lab_field.py",
        description="Set one metadata field (e.g. density) for a batch's samples in order.",
        aliases=("set",),
        examples=("python main.py sync fill CHY-1090 density 5.94 5.97 6.01",),
    ),
    Command(
        name="notion-payload",
        target=PROJECT_ROOT / "scripts" / "build_notion_sync_payload.py",
        description="Build payloads for Notion/lab metadata synchronization.",
        aliases=("notion", "payload"),
        examples=("python main.py sync notion-payload --help",),
    ),
    Command(
        name="reference-xlsx",
        target=PROJECT_ROOT / "scripts" / "extract_reference_xlsx.py",
        description="Extract structured reference data from Excel workbooks.",
        aliases=("xlsx", "reference"),
        examples=("python main.py sync reference-xlsx --help",),
    ),
)


DEMO_COMMANDS = (
    Command(
        name="paper-te",
        target=PROJECT_ROOT / "scripts" / "plot_paper_style_te_variants.py",
        description="Generate paper-style TE plot variants.",
        aliases=("paper", "te"),
        examples=("python main.py demo paper-te --help",),
    ),
)


GROUPS = {
    "spb": ("SPB fitting tools", SPB_COMMANDS),
    "sync": ("Metadata and data synchronization tools", SYNC_COMMANDS),
    "demo": ("Gallery generators", DEMO_COMMANDS),
    "demos": ("Gallery generators", DEMO_COMMANDS),
}


def build_alias_map(commands: tuple[Command, ...]) -> dict[str, Command]:
    alias_map = {}
    for command in commands:
        for key in (command.name, *command.aliases):
            alias_map[key] = command
    return alias_map


DIRECT_ALIAS_MAP = build_alias_map(DIRECT_COMMANDS)


def add_project_to_pythonpath(env: dict[str, str]) -> None:
    current = env.get("PYTHONPATH")
    root = str(PROJECT_ROOT)
    env["PYTHONPATH"] = root if not current else root + os.pathsep + current


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    add_project_to_pythonpath(env)
    # Tools print non-ASCII status symbols. When stdout is a pipe (an agent,
    # a test, `| tee`), Windows would otherwise encode it with the legacy code
    # page and crash with UnicodeEncodeError.
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # Keep stdout and stderr in the order they were printed when both are
    # captured (agents, `conda run`), instead of stdout arriving last.
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def run_python(target: Path, args: list[str]) -> int:
    if not target.exists():
        print(f"Target script does not exist: {target}", file=sys.stderr)
        return 2

    result = subprocess.run(
        [sys.executable, str(target), *args],
        cwd=PROJECT_ROOT,
        env=child_env(),
    )
    return result.returncode


def stderr_fileno() -> int | None:
    try:
        sys.stderr.flush()
        return sys.stderr.fileno()
    except (AttributeError, OSError, ValueError):
        return None


def run_python_json(command_name: str, target: Path, args: list[str]) -> int:
    """Run a tool and print one JSON object describing the run on stdout.

    The tool's own console output goes to stderr, so stdout carries only the
    JSON object: the command, its arguments, the exit code, and every file the
    tool recorded through te_analysis.run_manifest.record_output.
    """
    handle, manifest_name = tempfile.mkstemp(prefix="te_run_", suffix=".jsonl")
    os.close(handle)
    manifest_path = Path(manifest_name)
    try:
        if target.exists():
            env = child_env()
            env[MANIFEST_ENV_VAR] = str(manifest_path)
            stdout_target = stderr_fileno()
            result = subprocess.run(
                [sys.executable, str(target), *args],
                cwd=PROJECT_ROOT,
                env=env,
                stdout=stdout_target if stdout_target is not None else subprocess.PIPE,
            )
            if stdout_target is None and result.stdout:
                sys.stderr.write(result.stdout.decode("utf-8", errors="replace"))
            exit_code = result.returncode
        else:
            print(f"Target script does not exist: {target}", file=sys.stderr)
            exit_code = 2

        summary = {
            "command": command_name,
            "args": args,
            "exit_code": exit_code,
            "ok": exit_code == 0,
            "outputs": read_manifest(manifest_path, root=PROJECT_ROOT),
        }
    finally:
        manifest_path.unlink(missing_ok=True)

    # ASCII-escaped so printing never fails on a non-UTF-8 console.
    print(json.dumps(summary, indent=2))
    return exit_code


def run_command(command_name: str, target: Path, args: list[str], json_mode: bool) -> int:
    if json_mode:
        return run_python_json(command_name, target, args)
    return run_python(target, args)


def command_rows(commands: tuple[Command, ...]) -> str:
    rows = []
    for command in commands:
        aliases = f" ({', '.join(command.aliases)})" if command.aliases else ""
        rows.append(f"{command.name:<16} {command.description}{aliases}")
    return "\n".join(rows)


def print_main_help() -> None:
    common = textwrap.indent(command_rows(DIRECT_COMMANDS), "  ")
    print(f"""Usage:
  python main.py [--json] <command> [args...]
  python main.py [--json] <group> <command> [args...]

  --json           Print one JSON object on stdout when the command finishes:
                   command, args, exit_code, ok, and the files it wrote
                   (outputs). The tool's own messages move to stderr.

Common commands:
{common}

Command groups:
  spb              SPB fitting tools: effective-mass, conductivity, performance
  sync             Metadata and data synchronization tools
  demo             Gallery generators

Examples:
  python main.py analyze CHY-1048
  python main.py plot-te CHY-1048 --zt --no-show
  python main.py plot-xrd CHY-1056-B --no-show
  python main.py flexible --recipe configs/plot_recipes/example.json
  python main.py spb fitting data/demo/spb_fitting/Ag2Se/input.csv
  python main.py sync markdown export
  python main.py --json assess CHY-1048

Use "python main.py <command> --help" for a tool's own options.
Use "python main.py <group> --help" to list commands in a group.""")


def print_group_help(group_name: str, title: str, commands: tuple[Command, ...]) -> None:
    examples = []
    for command in commands:
        examples.extend(command.examples[:1])
    example_text = "\n".join(f"  {example}" for example in examples)
    rows = textwrap.indent(command_rows(commands), "  ")

    print(f"""{title}

Usage:
  python main.py {group_name} <command> [args...]

Commands:
{rows}

Examples:
{example_text}""")


def print_unknown_command(command_name: str) -> None:
    print(f"Unknown command: {command_name}", file=sys.stderr)
    print("Run `python main.py --help` to see available commands.", file=sys.stderr)


def dispatch_group(group_name: str, args: list[str], json_mode: bool = False) -> int:
    title, commands = GROUPS[group_name]
    if not args or args[0] in {"-h", "--help", "help"}:
        print_group_help(group_name, title, commands)
        return 0

    alias_map = build_alias_map(commands)
    command_name = args[0]
    command = alias_map.get(command_name)
    if command is None:
        print(f"Unknown {group_name} command: {command_name}", file=sys.stderr)
        print_group_help(group_name, title, commands)
        return 2

    return run_command(f"{group_name} {command.name}", command.target, args[1:], json_mode)


def dispatch_help(args: list[str]) -> int:
    if not args:
        print_main_help()
        return 0

    command_name = args[0]
    if command_name in GROUPS:
        title, commands = GROUPS[command_name]
        print_group_help(command_name, title, commands)
        return 0

    command = DIRECT_ALIAS_MAP.get(command_name)
    if command is not None:
        return run_python(command.target, ["--help"])

    print_unknown_command(command_name)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    # --json belongs to the launcher only when it comes before the command;
    # after the command it is passed through to the tool untouched.
    json_mode = bool(args) and args[0] == JSON_FLAG
    if json_mode:
        args = args[1:]

    if not args or args[0] in {"-h", "--help"}:
        print_main_help()
        # A bare `--json` names no command to run.
        return 2 if json_mode and not args else 0

    if args[0] == "help":
        return dispatch_help(args[1:])

    command_name = args[0]
    if command_name in GROUPS:
        return dispatch_group(command_name, args[1:], json_mode)

    command = DIRECT_ALIAS_MAP.get(command_name)
    if command is None:
        print_unknown_command(command_name)
        return 2

    return run_command(command.name, command.target, args[1:], json_mode)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Unified command launcher for the thermoelectric workspace."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


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
        examples=("python main.py agent data/processed/CHY-1048-processed/extracted_features.json",),
    ),
    Command(
        name="xrd-lattice",
        target=PROJECT_ROOT / "src" / "tools" / "xrd_lattice.py",
        description="Fit lattice parameters from XRD peak positions.",
        aliases=("lattice",),
        examples=("python main.py xrd-lattice --help",),
    ),
)


SPB_COMMANDS = (
    Command(
        name="effective-mass",
        target=PROJECT_ROOT / "src" / "tools" / "spb" / "effective_mass_fit.py",
        description="Fit SPB density-of-states effective mass from nH-Seebeck data.",
        aliases=("mass", "mstar", "pisarenko"),
        examples=("python main.py spb effective-mass data/demo/spb_fitting/Ag2Se/input.csv",),
    ),
    Command(
        name="conductivity",
        target=PROJECT_ROOT / "src" / "tools" / "spb" / "conductivity_fit.py",
        description="Fit SPB mobility from conductivity-Seebeck data.",
        aliases=("sigma", "mobility"),
        examples=("python main.py spb conductivity data/demo/spb_fitting/Cu2SSeTe/input.csv",),
    ),
    Command(
        name="performance",
        target=PROJECT_ROOT / "src" / "tools" / "spb" / "performance_fit.py",
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


def run_python(target: Path, args: list[str]) -> int:
    if not target.exists():
        print(f"Target script does not exist: {target}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    add_project_to_pythonpath(env)
    result = subprocess.run(
        [sys.executable, str(target), *args],
        cwd=PROJECT_ROOT,
        env=env,
    )
    return result.returncode


def command_rows(commands: tuple[Command, ...]) -> str:
    rows = []
    for command in commands:
        aliases = f" ({', '.join(command.aliases)})" if command.aliases else ""
        rows.append(f"{command.name:<16} {command.description}{aliases}")
    return "\n".join(rows)


def print_main_help() -> None:
    common = textwrap.indent(command_rows(DIRECT_COMMANDS), "  ")
    print(f"""Usage:
  python main.py <command> [args...]
  python main.py <group> <command> [args...]

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


def dispatch_group(group_name: str, args: list[str]) -> int:
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

    return run_python(command.target, args[1:])


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

    if not args or args[0] in {"-h", "--help"}:
        print_main_help()
        return 0

    if args[0] == "help":
        return dispatch_help(args[1:])

    command_name = args[0]
    if command_name in GROUPS:
        return dispatch_group(command_name, args[1:])

    command = DIRECT_ALIAS_MAP.get(command_name)
    if command is None:
        print_unknown_command(command_name)
        return 2

    return run_python(command.target, args[1:])


if __name__ == "__main__":
    raise SystemExit(main())

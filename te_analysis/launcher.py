#!/usr/bin/env python3
"""Unified command launcher for the TEDEX thermoelectric workspace."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Command:
    name: str
    target: Path
    description: str
    aliases: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


DIRECT_COMMANDS = (
    Command(
        name="init",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "workspace_init.py",
        description="Initialize or inspect a clean user data workspace (configs/workspace.json).",
        aliases=("setup", "onboard", "workspace"),
        examples=("te init --check", "te init --yes --grouping by_system_batch"),
    ),
    Command(
        name="analyze",
        target=PROJECT_ROOT / "te_analysis" / "pipeline" / "run_analysis.py",
        description="Run raw ZEM/LFA processing, feature extraction, and TE analysis.",
        aliases=("analysis", "run"),
        examples=("python main.py analyze TE-1048",),
    ),
    Command(
        name="plot-te",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "te_plotting" / "cli.py",
        description="Plot processed thermoelectric properties.",
        aliases=("te-plot", "teplot"),
        examples=("python main.py plot-te TE-1048 --zt --no-show",),
    ),
    Command(
        name="plot-xrd",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "xrd" / "cli.py",
        description="Plot standard/VT/refinement XRD patterns and PDF-card comparisons.",
        aliases=("xrd", "xrd-plot"),
        examples=("python main.py plot-xrd TE-1056-B --no-show",),
    ),
    Command(
        name="sciplot",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "sciplot" / "cli.py",
        description="Render general 1D/2D/statistical scientific figures and JSON plot recipes.",
        aliases=("flexible", "flex", "plot-fig"),
        examples=(
            "python main.py sciplot --figure contour data/phase_grid.csv -x Temp_K -y Doping_x -z zT --no-show",
            "python main.py sciplot --recipe configs/plot_recipes/thermoelectric/temperature_vs_zt_benchmark.json --no-show",
        ),
    ),
    Command(
        name="assess",
        target=PROJECT_ROOT / "te_analysis" / "pipeline" / "assess_batches.py",
        description="Assess selected batches and summarize optimization direction.",
        aliases=("assessment",),
        examples=("python main.py assess TE-1048",),
    ),
    Command(
        name="bayes",
        target=PROJECT_ROOT / "te_analysis" / "pipeline" / "bayesian_predict.py",
        description="Run Bayesian TE prediction workflows.",
        aliases=("bayesian", "predict"),
        examples=("python main.py bayes --help",),
    ),
    Command(
        name="agent",
        target=PROJECT_ROOT / "te_analysis" / "pipeline" / "agent_analysis.py",
        description="Run agent-based analysis from extracted features.",
        aliases=("agent-analysis",),
        examples=("python main.py agent TE-1048",),
    ),
    Command(
        name="xrd-lattice",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "xrd_lattice.py",
        description="Fit unit-cell lattice parameters from indexed XRD peak positions.",
        aliases=("lattice",),
        examples=("python main.py xrd-lattice --help",),
    ),
    Command(
        name="callaway",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "callaway.py",
        description="Fit Debye-Callaway phonon scattering & spectral MFP models.",
        aliases=("phonon",),
        examples=("python main.py callaway data/demo/physics_fitting/callaway_cigt.csv --theta-d 202 --vs 2160 --no-show",),
    ),
    Command(
        name="debye-calc",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "debye_calc.py",
        description="Calculate Debye temperature Theta_D & v_s from ultrasonic (vl,vt) or low-T Cp.",
        aliases=("theta-d", "sound-velocity"),
        examples=("python main.py debye-calc --vl 3100 --vt 1750 --atomic-volume-a3 29.0",),
    ),
    Command(
        name="debye-einstein",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "debye_einstein.py",
        description="Fit low-T heat capacity Cp(T) with Debye + Einstein rattler modes.",
        aliases=("debye", "cp-fit"),
        examples=("python main.py debye-einstein data/demo/physics_fitting/cp_rattler.csv --no-show",),
    ),
    Command(
        name="skb",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "skb.py",
        description="Fit non-parabolic Single Kane Band (SKB) transport models.",
        aliases=("kane",),
        examples=("python main.py skb data/demo/physics_fitting/skb_narrow_gap.csv --eg 0.25 --no-show",),
    ),
    Command(
        name="two-band",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "two_band.py",
        description="Fit Two-Band convergence (nH) or bipolar (T) transport models.",
        aliases=("twoband", "2band"),
        examples=("python main.py two-band data/demo/physics_fitting/two_band_convergence.csv --no-show",),
    ),
)


SPB_COMMANDS = (
    Command(
        name="effective-mass",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "spb" / "effective_mass_fit.py",
        description="Fit SPB density-of-states effective mass from nH-Seebeck data.",
        aliases=("mass", "mstar", "pisarenko"),
        examples=("python main.py spb effective-mass data/demo/spb_fitting/Ag2Se/Ag2Se_series.csv --no-show",),
    ),
    Command(
        name="conductivity",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "spb" / "conductivity_fit.py",
        description="Fit SPB mobility from conductivity-Seebeck data.",
        aliases=("sigma", "mobility"),
        examples=("python main.py spb conductivity data/demo/spb_fitting/Cu2SSeTe/900K.csv --no-show",),
    ),
    Command(
        name="performance",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "spb" / "performance_fit.py",
        description="Fit and plot SPB power-factor and zT performance curves.",
        aliases=("fitting", "fit", "pf", "zt"),
        examples=("python main.py spb performance data/demo/spb_fitting/Ag2Se/Ag2Se_series.csv --no-show",),
    ),
)


BAND_EXTRA_COMMANDS = (
    Command(
        name="skb",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "skb.py",
        description="Fit non-parabolic Single Kane Band (SKB) transport curves.",
        aliases=("kane",),
        examples=("python main.py band skb data/demo/physics_fitting/skb_narrow_gap.csv --eg 0.25 --no-show",),
    ),
    Command(
        name="two-band",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "two_band.py",
        description="Fit Two-Band convergence or bipolar transport curves.",
        aliases=("twoband", "2band"),
        examples=("python main.py band two-band data/demo/physics_fitting/two_band_convergence.csv --no-show",),
    ),
)

BAND_COMMANDS = (*SPB_COMMANDS, *BAND_EXTRA_COMMANDS)


MODEL_COMMANDS = (
    Command(
        name="callaway",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "callaway.py",
        description="Fit Debye-Callaway lattice thermal conductivity & spectral MFP.",
        aliases=("phonon",),
        examples=("python main.py model callaway data/demo/physics_fitting/callaway_cigt.csv --theta-d 202 --vs 2160 --no-show",),
    ),
    Command(
        name="debye-calc",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "debye_calc.py",
        description="Calculate Debye Theta_D, v_s & Gruneisen gamma from (vl,vt) or low-T Cp.",
        aliases=("theta-d", "sound-velocity"),
        examples=("python main.py model debye-calc --vl 3100 --vt 1750 --atomic-volume-a3 29.0",),
    ),
    Command(
        name="debye-einstein",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "debye_einstein.py",
        description="Fit low-T Cp(T) Sommerfeld + Debye + Einstein rattler boson peaks.",
        aliases=("debye", "cp-fit"),
        examples=("python main.py model debye-einstein data/demo/physics_fitting/cp_rattler.csv --no-show",),
    ),
    Command(
        name="skb",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "skb.py",
        description="Fit non-parabolic Single Kane Band (SKB) effective mass, Xi & PF.",
        aliases=("kane",),
        examples=("python main.py model skb data/demo/physics_fitting/skb_narrow_gap.csv --eg 0.25 --no-show",),
    ),
    Command(
        name="two-band",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "physics" / "two_band.py",
        description="Fit Two-Band convergence (L+Sigma) or bipolar (e+h) transport.",
        aliases=("twoband", "2band"),
        examples=("python main.py model two-band data/demo/physics_fitting/two_band_convergence.csv --no-show",),
    ),
)


SYNC_COMMANDS = (
    Command(
        name="metadata",
        target=PROJECT_ROOT / "te_analysis" / "sync" / "metadata.py",
        description="Sync JSON metadata ledgers from discovered raw/processed files.",
        aliases=("lab", "raw"),
        examples=("python main.py sync metadata --help",),
    ),
    Command(
        name="markdown",
        target=PROJECT_ROOT / "te_analysis" / "sync" / "markdown.py",
        description="Import/export editable lab_metadata.md and JSON metadata ledgers.",
        aliases=("md",),
        examples=("python main.py sync markdown export",),
    ),
    Command(
        name="notion-payload",
        target=PROJECT_ROOT / "te_analysis" / "sync" / "notion_payload.py",
        description="Build payloads for Notion/lab metadata synchronization.",
        aliases=("notion", "payload"),
        examples=("python main.py sync notion-payload --help",),
    ),
    Command(
        name="reference-xlsx",
        target=PROJECT_ROOT / "te_analysis" / "sync" / "reference_xlsx.py",
        description="Extract structured reference data from Excel workbooks.",
        aliases=("xlsx", "reference"),
        examples=("python main.py sync reference-xlsx --help",),
    ),
)


DEMO_COMMANDS = (
    Command(
        name="paper-te",
        target=PROJECT_ROOT / "te_analysis" / "tools" / "te_plotting" / "paper_variants.py",
        description="Generate paper-style TE plot variants.",
        aliases=("paper", "te"),
        examples=("python main.py demo paper-te --help",),
    ),
)


GROUPS = {
    "spb": ("Single Parabolic Band (SPB) fitting tools", SPB_COMMANDS),
    "band": ("Electronic band transport fitting tools (SPB, SKB, Two-Band)", BAND_COMMANDS),
    "model": ("Electronic & phonon physics fitting models", MODEL_COMMANDS),
    "physics": ("Electronic & phonon physics fitting models", MODEL_COMMANDS),
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
LEGACY_SPB_FALLBACK_MAP = build_alias_map(BAND_EXTRA_COMMANDS)


def add_project_to_pythonpath(env: dict[str, str]) -> None:
    current = env.get("PYTHONPATH")
    root = str(PROJECT_ROOT)
    env["PYTHONPATH"] = root if not current else root + os.pathsep + current


def run_python(target: Path, args: list[str], workspace: Path | None = None) -> int:
    if not target.exists():
        print(f"Target script does not exist: {target}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    add_project_to_pythonpath(env)
    run_cwd = Path(workspace).expanduser().resolve() if workspace is not None else Path.cwd().resolve()
    if workspace is not None:
        env["TE_WORKSPACE_ROOT"] = str(run_cwd)
    else:
        env.setdefault("TE_WORKSPACE_ROOT", str(run_cwd))
    result = subprocess.run(
        [sys.executable, str(target), *args],
        cwd=run_cwd,
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
  spb              Single Parabolic Band (SPB) tools: effective-mass, conductivity, performance
  band             Electronic band models: effective-mass, conductivity, performance, skb, two-band
  model / physics  Phonon & electronic physics models: callaway, debye-calc, debye-einstein, skb, two-band
  sync             Metadata and data synchronization tools: metadata, markdown, notion-payload, reference-xlsx
  demo             Gallery generators

Examples:
  python main.py analyze TE-1048
  python main.py plot-te TE-1048 --zt --no-show
  python main.py plot-xrd TE-1056-B --no-show
  python main.py sciplot --figure contour data/phase_grid.csv -x Temp_K -y Doping_x -z zT --no-show
  python main.py spb performance data/demo/spb_fitting/Ag2Se/Ag2Se_series.csv --no-show
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


def dispatch_group(group_name: str, args: list[str], workspace: Path | None = None) -> int:
    title, commands = GROUPS[group_name]
    if not args or args[0] in {"-h", "--help", "help"}:
        print_group_help(group_name, title, commands)
        return 0

    alias_map = build_alias_map(commands)
    command_name = args[0]
    command = alias_map.get(command_name)
    if command is None and group_name == "spb":
        # Backward-compatible fallback for legacy `te spb skb` / `te spb two-band` invocations.
        command = LEGACY_SPB_FALLBACK_MAP.get(command_name)
    if command is None:
        print(f"Unknown {group_name} command: {command_name}", file=sys.stderr)
        print_group_help(group_name, title, commands)
        return 2

    return run_python(command.target, args[1:], workspace=workspace)


def dispatch_help(args: list[str], workspace: Path | None = None) -> int:
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
        return run_python(command.target, ["--help"], workspace=workspace)

    print_unknown_command(command_name)
    return 2


def _extract_workspace_option(args: list[str]) -> tuple[Path | None, list[str]]:
    workspace: Path | None = None
    cleaned: list[str] = []
    idx = 0
    while idx < len(args):
        token = args[idx]
        if token in {"-w", "--workspace"}:
            if idx + 1 >= len(args):
                raise ValueError(f"{token} requires a directory path")
            workspace = Path(args[idx + 1])
            idx += 2
            continue
        if token.startswith("--workspace="):
            workspace = Path(token.split("=", 1)[1])
            idx += 1
            continue
        cleaned.append(token)
        idx += 1
    return workspace, cleaned


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    try:
        workspace, args = _extract_workspace_option(raw_args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args or args[0] in {"-h", "--help"}:
        print_main_help()
        return 0

    if args[0] == "help":
        return dispatch_help(args[1:], workspace=workspace)

    command_name = args[0]
    if command_name in GROUPS:
        return dispatch_group(command_name, args[1:], workspace=workspace)

    command = DIRECT_ALIAS_MAP.get(command_name)
    if command is None:
        print_unknown_command(command_name)
        return 2

    return run_python(command.target, args[1:], workspace=workspace)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Debye temperature, sound velocity, elastic moduli, and Gruneisen parameter calculator.

Implements the two primary experimental methods for thermoelectric materials:
1. Ultrasonic Pulse-Echo / RUS sound velocities (`vl`, `vt`) + atomic density (`V0` or `rho` + `molar_mass` + `atoms_per_fu`)
   -> Anderson mean sound velocity v_s, Debye temperature Theta_D, acoustic Theta_a, elastic moduli (E, G, B),
      Poisson ratio nu, and Gruneisen parameter gamma_G.
2. Low-temperature PPMS heat capacity Cp(T) (`Cp / T = gamma + beta * T^2` or full Debye-Einstein fit)
   -> Sommerfeld gamma, phonon slope beta, Debye temperature Theta_D, and (if V0/rho given) sound velocity v_s.

Also provides a structured missing-parameter check (`ensure_debye_parameters`) so CLI / AI Agents
can either prompt interactively in a TTY or ask the user for the exact missing experimental observables.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from scipy.constants import N_A, R as GAS_R, h, hbar, k

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from te_analysis.tools.physics.io_plot import (  # noqa: E402
    CP_CANDIDATES,
    TEMPERATURE_CANDIDATES,
    find_column,
    read_tabular_data,
)


class MissingDebyeParametersError(ValueError):
    """Raised when neither (Theta_D, v_s) nor ultrasonic/Cp inputs are provided."""


def resolve_number_density_per_m3(
    *,
    atomic_volume_a3: float | None = None,
    density_g_cm3: float | None = None,
    molar_mass_g_mol: float | None = None,
    atoms_per_fu: float | None = None,
) -> tuple[float, float]:
    """Return (n_a [m^-3], V_0 [Angstrom^3/atom])."""
    if atomic_volume_a3 is not None and atomic_volume_a3 > 0:
        v0_a3 = float(atomic_volume_a3)
        return 1.0 / (v0_a3 * 1e-30), v0_a3
    if (
        density_g_cm3 is not None
        and density_g_cm3 > 0
        and molar_mass_g_mol is not None
        and molar_mass_g_mol > 0
        and atoms_per_fu is not None
        and atoms_per_fu > 0
    ):
        # rho [g/cm^3] * 1e6 [g/m^3] / M [g/mol] * N_A * atoms_per_fu
        n_a = (float(density_g_cm3) * 1e6 / float(molar_mass_g_mol)) * N_A * float(atoms_per_fu)
        v0_a3 = 1e30 / n_a
        return float(n_a), float(v0_a3)
    raise MissingDebyeParametersError(
        "Need either `--atomic-volume-a3` (V_0 in A^3/atom) OR (`--density-g-cm3`, `--molar-mass`, `--atoms-per-fu`) "
        "to convert between Debye temperature Theta_D and sound velocity v_s."
    )


def debye_from_ultrasonic(
    vl_m_s: float,
    vt_m_s: float,
    *,
    atomic_volume_a3: float | None = None,
    density_g_cm3: float | None = None,
    molar_mass_g_mol: float | None = None,
    atoms_per_fu: float | None = None,
    atoms_per_primitive_cell: float | None = None,
) -> dict[str, Any]:
    """Method 1: Compute Anderson v_s, Theta_D, Poisson ratio nu, moduli, and Gruneisen gamma_G from (v_l, v_t)."""
    vl = float(vl_m_s)
    vt = float(vt_m_s)
    if vl <= 0 or vt <= 0:
        raise ValueError("Longitudinal (vl) and transverse (vt) sound velocities must be positive.")
    if vl <= math.sqrt(4.0 / 3.0) * vt:
        raise ValueError(
            f"Unphysical sound velocities: v_l ({vl} m/s) must exceed sqrt(4/3) * v_t ({vt * math.sqrt(4/3):.1f} m/s)."
        )

    vs = (1.0 / 3.0 * (1.0 / (vl**3) + 2.0 / (vt**3))) ** (-1.0 / 3.0)
    ratio2 = (vt / vl) ** 2
    poisson_nu = (1.0 - 2.0 * ratio2) / (2.0 - 2.0 * ratio2)
    gruneisen = 1.5 * (1.0 + poisson_nu) / max(2.0 - 3.0 * poisson_nu, 1e-6)

    n_a, v0_a3 = resolve_number_density_per_m3(
        atomic_volume_a3=atomic_volume_a3,
        density_g_cm3=density_g_cm3,
        molar_mass_g_mol=molar_mass_g_mol,
        atoms_per_fu=atoms_per_fu,
    )
    theta_d = (h / k) * ((3.0 * n_a / (4.0 * math.pi)) ** (1.0 / 3.0)) * vs
    theta_a = (
        theta_d * (float(atoms_per_primitive_cell) ** (-1.0 / 3.0))
        if (atoms_per_primitive_cell and atoms_per_primitive_cell > 0)
        else None
    )

    result: dict[str, Any] = {
        "method": "ultrasonic_sound_velocity",
        "vl_m_s": vl,
        "vt_m_s": vt,
        "vs_anderson_m_s": float(vs),
        "Theta_D_K": float(theta_d),
        "Theta_acoustic_K": float(theta_a) if theta_a is not None else None,
        "atomic_volume_A3": float(v0_a3),
        "number_density_m-3": float(n_a),
        "poisson_ratio_nu": float(poisson_nu),
        "gruneisen_gamma": float(gruneisen),
    }
    if density_g_cm3 is not None and density_g_cm3 > 0:
        rho_kg = float(density_g_cm3) * 1000.0
        g_gpa = rho_kg * (vt**2) * 1e-9
        b_gpa = (rho_kg * (vl**2) * 1e-9) - (4.0 / 3.0) * g_gpa
        e_gpa = 2.0 * g_gpa * (1.0 + poisson_nu)
        result["shear_modulus_G_GPa"] = float(g_gpa)
        result["bulk_modulus_B_GPa"] = float(b_gpa)
        result["youngs_modulus_E_GPa"] = float(e_gpa)
    return result


def debye_from_heat_capacity(
    *,
    atoms_per_fu: float,
    beta_mj_mol_k4: float | None = None,
    cp_csv: str | Path | None = None,
    cp_unit: str = "J/molK",
    molar_mass_g_mol: float | None = None,
    t_fit_max_k: float = 10.0,
    atomic_volume_a3: float | None = None,
    density_g_cm3: float | None = None,
    atoms_per_primitive_cell: float | None = None,
) -> dict[str, Any]:
    """Method 2: Compute Theta_D (and v_s if density/volume provided) from low-T Cp/T = gamma + beta T^2."""
    if atoms_per_fu <= 0:
        raise ValueError("--atoms-per-fu must be positive")

    gamma_mj = None
    if beta_mj_mol_k4 is not None:
        beta_j = float(beta_mj_mol_k4) * 1e-3
    elif cp_csv is not None:
        df = read_tabular_data(cp_csv)
        tc = find_column(df, None, TEMPERATURE_CANDIDATES, required=True)
        cc = find_column(df, None, CP_CANDIDATES, required=True)
        t_vals = pd.to_numeric(df[tc], errors="coerce").to_numpy(dtype=float)
        c_vals = pd.to_numeric(df[cc], errors="coerce").to_numpy(dtype=float)
        u_clean = cp_unit.strip().lower().replace(" ", "").replace("-", "").replace("^", "")
        if u_clean in {"mj/molk", "mjmolk", "mjmol1k1"}:
            c_vals = c_vals * 1e-3
        elif u_clean in {"j/gk", "jgk", "jg1k1"}:
            if not molar_mass_g_mol or molar_mass_g_mol <= 0:
                raise ValueError("--cp-unit J/gK requires --molar-mass")
            c_vals = c_vals * float(molar_mass_g_mol)
        valid = np.isfinite(t_vals) & np.isfinite(c_vals) & (t_vals > 0.2) & (c_vals > 0)
        t_v, c_v = t_vals[valid], c_vals[valid]
        low = t_v <= float(t_fit_max_k)
        if np.sum(low) < 3:
            order = np.argsort(t_v)[: min(6, len(t_v))]
            t_sub, c_sub = t_v[order], c_v[order]
        else:
            t_sub, c_sub = t_v[low], c_v[low]
        slope_b, inter_g = np.polyfit(t_sub**2, c_sub / t_sub, 1)
        if slope_b <= 0:
            raise ValueError(f"Fitted Cp/T vs T^2 slope beta = {slope_b:.3e} <= 0; check low-T window (--cp-tmax).")
        beta_j = float(slope_b)
        gamma_mj = max(float(inter_g) * 1e3, 0.0)
    else:
        raise MissingDebyeParametersError("Provide either `--cp-beta` (mJ mol^-1 K^-4) or `--cp-csv` for Method 2.")

    theta_d = ((12.0 * (math.pi**4) * float(atoms_per_fu) * GAS_R) / (5.0 * beta_j)) ** (1.0 / 3.0)
    theta_a = (
        theta_d * (float(atoms_per_primitive_cell) ** (-1.0 / 3.0))
        if (atoms_per_primitive_cell and atoms_per_primitive_cell > 0)
        else None
    )

    vs = None
    v0_a3 = None
    try:
        n_a, v0_a3 = resolve_number_density_per_m3(
            atomic_volume_a3=atomic_volume_a3,
            density_g_cm3=density_g_cm3,
            molar_mass_g_mol=molar_mass_g_mol,
            atoms_per_fu=atoms_per_fu,
        )
        vs = float((k * theta_d) / (hbar * ((6.0 * (math.pi**2) * n_a) ** (1.0 / 3.0))))
    except MissingDebyeParametersError:
        pass

    return {
        "method": "low_T_heat_capacity",
        "atoms_per_fu": float(atoms_per_fu),
        "gamma_mJ_molK2": gamma_mj,
        "beta_mJ_molK4": float(beta_j * 1e3),
        "Theta_D_K": float(theta_d),
        "Theta_acoustic_K": float(theta_a) if theta_a is not None else None,
        "vs_derived_m_s": vs,
        "atomic_volume_A3": v0_a3,
    }


def format_missing_debye_prompt() -> str:
    return (
        "Missing Debye lattice parameters (`--theta-d` and `--vs`).\n"
        "Please provide ONE of the following three parameter sets (or ask the user):\n"
        "  [Option 1 - Direct]      `--theta-d <K> --vs <m/s>` (optional `--atomic-volume-a3 <A^3>`)\n"
        "  [Option 2 - Ultrasonic]  `--vl <m/s> --vt <m/s>` plus `--atomic-volume-a3 <A^3>` "
        "(or `--density-g-cm3 <g/cm3> --molar-mass <g/mol> --atoms-per-fu <N>`)\n"
        "  [Option 3 - Low-T Cp]    `--cp-csv <path>` (or `--cp-beta <mJ/molK^4>`) plus `--atoms-per-fu <N>` "
        "and `--atomic-volume-a3 <A^3>` (or density + molar mass)"
    )


def interactive_prompt_debye_params() -> dict[str, float | None]:
    """Interactive terminal questionnaire when a human runs CLI without Debye parameters."""
    print("\n[Callaway] 未检测到德拜温度 (--theta-d) 和声速 (--vs)。请选择参数输入方式：")
    print("  1) 直接输入 德拜温度 Theta_D (K) 与 平均声速 v_s (m/s)")
    print("  2) 超声声速法：输入 纵波声速 v_l (m/s)、横波声速 v_t (m/s) 及单原子体积/密度")
    print("  3) 低温比热法：输入 低温比热斜率 beta (mJ mol^-1 K^-4) 或 Cp 文件路径")
    choice = input("请选择 [1/2/3]: ").strip()

    if choice == "1":
        td = float(input("  Theta_D (K): ").strip())
        vs = float(input("  v_s (m/s): ").strip())
        v0_raw = input("  单原子平均体积 V_0 (A^3，可直接回车由德拜球自动推算): ").strip()
        return {"theta_d_k": td, "vs_m_s": vs, "atomic_volume_a3": float(v0_raw) if v0_raw else None, "gruneisen": None}

    if choice == "2":
        vl = float(input("  纵波声速 v_l (m/s): ").strip())
        vt = float(input("  横波声速 v_t (m/s): ").strip())
        v0_raw = input("  单原子体积 V_0 (A^3，若改用密度换算请直接回车): ").strip()
        if v0_raw:
            res = debye_from_ultrasonic(vl, vt, atomic_volume_a3=float(v0_raw))
        else:
            rho = float(input("  实测密度 rho (g/cm^3): ").strip())
            mm = float(input("  化学式摩尔质量 M (g/mol): ").strip())
            n_fu = float(input("  每化学式原子数 N_at: ").strip())
            res = debye_from_ultrasonic(vl, vt, density_g_cm3=rho, molar_mass_g_mol=mm, atoms_per_fu=n_fu)
        return {
            "theta_d_k": res["Theta_D_K"],
            "vs_m_s": res["vs_anderson_m_s"],
            "atomic_volume_a3": res["atomic_volume_A3"],
            "gruneisen": res["gruneisen_gamma"],
        }

    if choice == "3":
        n_fu = float(input("  每化学式原子数 N_at: ").strip())
        src = input("  输入低温比热 CSV 路径，或直接输入斜率 beta (mJ mol^-1 K^-4): ").strip()
        v0 = float(input("  单原子体积 V_0 (A^3): ").strip())
        if Path(src).is_file():
            res = debye_from_heat_capacity(atoms_per_fu=n_fu, cp_csv=src, atomic_volume_a3=v0)
        else:
            res = debye_from_heat_capacity(atoms_per_fu=n_fu, beta_mj_mol_k4=float(src), atomic_volume_a3=v0)
        return {
            "theta_d_k": res["Theta_D_K"],
            "vs_m_s": float(res["vs_derived_m_s"]),
            "atomic_volume_a3": res["atomic_volume_A3"],
            "gruneisen": None,
        }

    raise MissingDebyeParametersError(format_missing_debye_prompt())


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute Debye temperature Theta_D, sound velocity v_s, elastic moduli & Gruneisen gamma_G "
        "from (1) ultrasonic velocities (vl, vt) or (2) low-T heat capacity Cp(T)."
    )
    p.add_argument("--vl", type=float, default=None, help="Longitudinal sound velocity v_l in m/s (Method 1).")
    p.add_argument("--vt", type=float, default=None, help="Transverse/shear sound velocity v_t in m/s (Method 1).")
    p.add_argument("--cp-csv", default=None, help="Low-T Cp(T) CSV/TSV/XLSX file path (Method 2).")
    p.add_argument("--cp-beta", type=float, default=None, help="Low-T Cp/T vs T^2 slope beta in mJ mol^-1 K^-4 (Method 2).")
    p.add_argument("--cp-unit", default="J/molK", choices=("J/molK", "mJ/molK", "J/gK"), help="Unit of Cp in --cp-csv.")
    p.add_argument("--cp-tmax", type=float, default=10.0, help="Max T (K) for linear Cp/T vs T^2 fit (default: 10 K).")
    p.add_argument("--atomic-volume-a3", type=float, default=None, help="Average volume per atom V_0 in Angstrom^3.")
    p.add_argument("--density-g-cm3", "--rho-gcm3", dest="density_g_cm3", type=float, default=None, help="Sample density in g/cm^3.")
    p.add_argument("--molar-mass", type=float, default=None, help="Formula-unit molar mass in g/mol.")
    p.add_argument("--atoms-per-fu", type=float, default=None, help="Number of atoms per formula unit N_at.")
    p.add_argument("--atoms-per-prim", type=float, default=None, help="Atoms per primitive cell (to also report acoustic Theta_a).")
    p.add_argument("--interactive", action="store_true", help="Prompt interactively if required inputs are missing.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        if args.vl is not None and args.vt is not None:
            res = debye_from_ultrasonic(
                args.vl,
                args.vt,
                atomic_volume_a3=args.atomic_volume_a3,
                density_g_cm3=args.density_g_cm3,
                molar_mass_g_mol=args.molar_mass,
                atoms_per_fu=args.atoms_per_fu,
                atoms_per_primitive_cell=args.atoms_per_prim,
            )
        elif args.cp_csv is not None or args.cp_beta is not None:
            if args.atoms_per_fu is None:
                raise MissingDebyeParametersError("Method 2 (heat capacity) requires `--atoms-per-fu <N>`.")
            res = debye_from_heat_capacity(
                atoms_per_fu=args.atoms_per_fu,
                beta_mj_mol_k4=args.cp_beta,
                cp_csv=args.cp_csv,
                cp_unit=args.cp_unit,
                molar_mass_g_mol=args.molar_mass,
                t_fit_max_k=args.cp_tmax,
                atomic_volume_a3=args.atomic_volume_a3,
                density_g_cm3=args.density_g_cm3,
                atoms_per_primitive_cell=args.atoms_per_prim,
            )
        elif args.interactive or sys.stdin.isatty():
            res = interactive_prompt_debye_params()
        else:
            raise MissingDebyeParametersError(format_missing_debye_prompt())
    except MissingDebyeParametersError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

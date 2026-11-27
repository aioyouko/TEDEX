"""Physics & numerical accuracy tests for Callaway, Debye-Einstein, SKB, and Two-Band models."""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
import pandas as pd

from _helpers import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))

from te_analysis.tools.physics.callaway import (  # noqa: E402
    CallawayMaterialParams,
    CallawayScatteringParams,
    callaway_kappa_l,
    main as callaway_cli_main,
    run_callaway_workflow,
)
from te_analysis.tools.physics.debye_calc import (  # noqa: E402
    debye_from_heat_capacity,
    debye_from_ultrasonic,
)
from te_analysis.tools.physics.debye_einstein import (  # noqa: E402
    evaluate_debye_einstein_components,
    run_debye_einstein_workflow,
)
from te_analysis.tools.physics.fermi import (  # noqa: E402
    LORENZ_PREFACTOR_W_OHM_K2,
    fermi_integral_vec,
    parabolic_band_state_general_r,
    single_band_state,
)
from te_analysis.tools.physics.skb import SKBFitConfig, run_skb_workflow  # noqa: E402
from te_analysis.tools.physics.two_band import (  # noqa: E402
    evaluate_bipolar_temperature_series,
    main as two_band_cli_main,
    predict_convergence_at_nh,
    predict_isothermal_bipolar_at_nh,
    run_two_band_workflow,
    solve_bipolar_neutrality_eta,
)
from te_analysis.tools.spb.effective_mass_fit import (  # noqa: E402
    fermi_integral as spb_fermi_quad,
    hall_concentration_m3 as spb_hall_nh,
    hall_factor_acoustic as spb_rh,
    seebeck_abs_uv_from_eta as spb_seebeck,
)
from te_analysis.tools.spb.performance_fit import (  # noqa: E402
    hall_mobility_factor_from_eta as spb_mu_factor,
    lorenz_number_from_eta as spb_lorenz,
)


def test_fermi_quadrature_and_skb_parabolic_limit_match_spb():
    etas = np.array([-8.0, -2.5, 0.0, 1.8, 6.0, 18.0])
    for order in (-0.5, 0.0, 0.5, 1.0, 2.0):
        vec_vals = fermi_integral_vec(etas, order)
        ref_vals = np.array([spb_fermi_quad(float(e_val), order) for e_val in etas])
        rel_err = np.max(np.abs(vec_vals - ref_vals) / ref_vals)
        assert rel_err < 1e-11, f"F_{order} relative error too large: {rel_err}"

    # Verify SKB at alpha = 0 matches SPB identically across all transport observables
    st = single_band_state(etas, temperature_k=300.0, mstar_dos_ratio=1.25, mu0_cm2_vs=85.0, alpha=0.0)
    for idx, eta_v in enumerate(etas):
        assert math.isclose(st["Seebeck_abs_uV_K"][idx], spb_seebeck(float(eta_v)), rel_tol=1e-10)
        assert math.isclose(st["Hall_factor_rH"][idx], spb_rh(float(eta_v)), rel_tol=1e-10)
        assert math.isclose(st["nH_m-3"][idx], spb_hall_nh(float(eta_v), 1.25, 300.0), rel_tol=1e-10)
        assert math.isclose(st["Lorenz_WOhmK-2"][idx], spb_lorenz(float(eta_v)), rel_tol=1e-10)
        expected_mu_h = 85.0 * spb_mu_factor(float(eta_v), 0.0)
        assert math.isclose(st["Hall_Mobility_cm2_V-1_s-1"][idx], expected_mu_h, rel_tol=1e-10)


def test_callaway_and_debye_einstein_parameter_recovery():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 1. Synthetic Full-Range (3 K -> 800 K) Cryogenic-to-High-T Callaway dataset with 4 sources
        mat_true = CallawayMaterialParams(theta_d_k=210.0, sound_velocity_m_s=2200.0, atomic_volume_a3=28.5)
        scat_true = CallawayScatteringParams(
            b_umklapp_1e18_s_k=3.2,
            grain_size_nm=2500.0,
            a_pd_1e41_s3=2.6,
            dislocation_density_1e11_cm2=1.8,
        )
        t_grid = np.geomspace(3.0, 800.0, 30)
        kl_true = callaway_kappa_l(t_grid, mat_true, scat_true, active_mechanisms=("U", "GB", "PD", "D"))
        cal_csv = tmp_dir / "syn_callaway_full.csv"
        pd.DataFrame({"Temperature": t_grid, "kappa_L": kl_true}).to_csv(cal_csv, index=False)

        res_cal = run_callaway_workflow(
            cal_csv,
            output_dir=tmp_dir / "out_cal",
            mat=mat_true,
            active_mechanisms=("U", "GB", "PD", "D"),
            fit_mechanisms=("U", "GB", "PD", "D"),
            formats=("png",),
            copy_to_data_dir=False,
            show=False,
        )
        fs = res_cal["fitted_scattering"]
        assert math.isclose(fs["b_umklapp_1e18_s_k"], 3.2, rel_tol=0.03)
        assert math.isclose(fs["grain_size_nm"], 2500.0, rel_tol=0.04)
        assert math.isclose(fs["a_pd_1e41_s3"], 2.6, rel_tol=0.04)
        assert math.isclose(fs["dislocation_density_1e11_cm2"], 1.8, rel_tol=0.06)
        assert len(res_cal["mechanism_contributions"]) >= 2

        # Verify Debye calculator round-trip & missing-parameter non-TTY exit code 2
        u_res = debye_from_ultrasonic(2600.0, 1450.0, atomic_volume_a3=28.5)
        assert u_res["Theta_D_K"] > 100.0 and u_res["vs_anderson_m_s"] > 1000.0
        rc_missing = callaway_cli_main([str(cal_csv), "--no-show"])
        assert rc_missing == 2
        rc_ultra = callaway_cli_main(
            [
                str(cal_csv),
                "-o",
                str(tmp_dir / "out_ultra"),
                "--vl",
                "2600",
                "--vt",
                "1450",
                "--atomic-volume-a3",
                "28.5",
                "--mechanisms",
                "U",
                "B",
                "PD",
                "RES",
                "--rattler-damping",
                "0",
                "--spectral-xaxis",
                "meV",
                "--spectral-norm",
                "x",
                "--no-copy-to-data-dir",
                "--no-show",
            ]
        )
        assert rc_ultra == 0
        rep_md = (tmp_dir / "out_ultra" / "syn_callaway_full_callaway_report.md").read_text(encoding="utf-8")
        assert "\\omega_{\\mathrm{RES}}/\\nu_{\\mathrm{RES}}" in rep_md

        # 2. Synthetic Debye-Einstein dataset (1 rattler mode at 45 K)
        t_cp = np.geomspace(2.2, 120.0, 36)
        comps = evaluate_debye_einstein_components(
            t_cp,
            atoms_per_fu=4.0,
            gamma_mj_mol_k2=1.2,
            theta_d_k=230.0,
            w_debye=0.88,
            einstein_modes=[(45.0, 0.12)],
        )
        cp_csv = tmp_dir / "syn_cp.csv"
        pd.DataFrame({"T_K": t_cp, "Cp_J_molK": comps["total"]}).to_csv(cp_csv, index=False)

        res_de = run_debye_einstein_workflow(
            cp_csv,
            output_dir=tmp_dir / "out_de",
            atoms_per_fu=4.0,
            n_einstein=1,
            formats=("png",),
            copy_to_data_dir=False,
            show=False,
        )
        fit_de = res_de["fit"]
        assert math.isclose(fit_de["Theta_D_K"], 230.0, rel_tol=0.03)
        assert math.isclose(fit_de["einstein_modes"][0]["Theta_E_K"], 45.0, rel_tol=0.03)
        assert fit_de["r2_Cp_over_T3"] > 0.999


def test_skb_and_two_band_convergence_and_bipolar_recovery():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 1. SKB recovery on narrow-gap semiconductor (Eg = 0.22 eV, m*_d = 0.38 m_e, mu0 = 420)
        etas = np.linspace(-1.5, 5.0, 9)
        alpha_true = (1.380649e-23 * 300.0) / (0.22 * 1.602176634e-19)
        st_skb = single_band_state(etas, temperature_k=300.0, mstar_dos_ratio=0.38, mu0_cm2_vs=420.0, alpha=alpha_true)
        skb_csv = tmp_dir / "syn_skb.csv"
        pd.DataFrame(
            {
                "nH_cm-3": st_skb["nH_cm-3"],
                "Seebeck_uV_K": st_skb["Seebeck_abs_uV_K"],
                "muH": st_skb["Hall_Mobility_cm2_V-1_s-1"],
            }
        ).to_csv(skb_csv, index=False)

        res_skb = run_skb_workflow(
            skb_csv,
            output_dir=tmp_dir / "out_skb",
            cfg=SKBFitConfig(temperature_k=300.0, eg_ev=0.22, density_kg_m3=8100.0, sound_velocity_m_s=3000.0),
            formats=("png",),
            copy_to_data_dir=False,
            show=False,
        )
        assert math.isclose(res_skb["fit"]["mstar_dos_over_me"], 0.38, rel_tol=0.02)
        assert math.isclose(res_skb["fit"]["mu0_cm2_Vs"], 420.0, rel_tol=0.02)
        assert res_skb["fit"]["deformation_potential_Xi_eV"] is not None

        # 2. Two-Band Convergence recovery (with m1 pinned, verifying clean recovery of m2, Delta E, b, mu1)
        nh_series = np.logspace(18.5, 20.6, 12) * 1e6
        conv_true = predict_convergence_at_nh(
            nh_series,
            temperature_k=300.0,
            m1_dos=0.35,
            m2_dos=1.80,
            delta_e_ev=0.11,
            mu0_1_cm2_vs=320.0,
            b_mobility_ratio=6.0,
            carrier_sign=1,
        )
        conv_csv = tmp_dir / "syn_conv.csv"
        pd.DataFrame(
            {
                "nH": conv_true["nH_cm-3"],
                "Seebeck": conv_true["Seebeck_uV_K"],
                "Conductivity_S_cm-1": conv_true["Conductivity_S_cm-1"],
            }
        ).to_csv(conv_csv, index=False)

        res_conv = run_two_band_workflow(
            conv_csv,
            mode="convergence",
            output_dir=tmp_dir / "out_conv",
            temperature_k=300.0,
            fix_m1=0.35,
            formats=("png",),
            copy_to_data_dir=False,
            show=False,
        )
        fc = res_conv["fit"]
        assert fc["seebeck_rmse_uV_K"] < 1.5
        assert math.isclose(fc["delta_E_eV"], 0.11, abs_tol=0.025)

        # 3. Two-Band Bipolar temperature series recovery
        t_series = np.linspace(300.0, 780.0, 16)
        bip_true = evaluate_bipolar_temperature_series(
            t_series,
            majority_sign=1,
            n_dop_cm3=3.5e18,
            m_maj_dos=0.95,
            m_min_dos=0.95,
            mu0_maj_300_cm2_vs=95.0,
            b_min_over_maj=2.2,
            eg0_ev=0.32,
        )
        kl_true_b = 360.0 / t_series + 0.35
        bip_csv = tmp_dir / "syn_bipolar.csv"
        pd.DataFrame(
            {
                "Temperature": t_series,
                "Seebeck": bip_true["Seebeck_uV_K"],
                "Conductivity_S_cm-1": bip_true["Conductivity_S_cm-1"],
                "Thermal_Conductivity": kl_true_b + bip_true["Total_Electronic_Thermal_Conductivity_W_m-1_K-1"],
            }
        ).to_csv(bip_csv, index=False)

        res_bip = run_two_band_workflow(
            bip_csv,
            mode="bipolar",
            output_dir=tmp_dir / "out_bip",
            fix_m1=0.95,
            fix_m2=0.95,
            formats=("png",),
            copy_to_data_dir=False,
            show=False,
        )
        fb = res_bip["fit"]
        assert math.isclose(fb["fitted_Eg0_eV"], 0.32, rel_tol=0.08)
        assert fb["seebeck_rmse_uV_K"] < 2.0


def test_parabolic_general_r_boltzmann_limits_and_spb_identity():
    etas = np.array([-8.0, -2.5, 0.0, 1.8, 6.0, 18.0])
    st_skb0 = single_band_state(etas, temperature_k=300.0, mstar_dos_ratio=0.72, mu0_cm2_vs=140.0, alpha=0.0, carrier_sign=-1)
    st_gen = parabolic_band_state_general_r(
        etas, temperature_k=300.0, mstar_dos_ratio=0.72, mu0_cm2_vs=140.0, scattering_r=-0.5, carrier_sign=-1
    )
    for col in (
        "n_m-3",
        "nH_m-3",
        "Hall_factor_rH",
        "Hall_Coefficient_m3_C-1",
        "Seebeck_uV_K",
        "Lorenz_WOhmK-2",
        "Drift_Mobility_cm2_V-1_s-1",
        "Hall_Mobility_cm2_V-1_s-1",
        "Conductivity_S_m-1",
        "Carrier_Thermal_Conductivity_W_m-1_K-1",
    ):
        assert np.allclose(st_gen[col], st_skb0[col], rtol=1e-12, atol=0.0), f"Mismatch in {col}"

    # Verify analytical non-degenerate (eta = -16) and degenerate Sommerfeld (eta = +250) limits for multiple r
    for r_val in (-0.5, 0.0, 0.5, 1.5):
        nd = parabolic_band_state_general_r(-16.0, temperature_k=300.0, mstar_dos_ratio=1.0, scattering_r=r_val)
        deg = parabolic_band_state_general_r(250.0, temperature_k=300.0, mstar_dos_ratio=1.0, scattering_r=r_val)
        l_nd_factor = float(nd["Lorenz_WOhmK-2"][0]) / LORENZ_PREFACTOR_W_OHM_K2
        l_deg_factor = float(deg["Lorenz_WOhmK-2"][0]) / LORENZ_PREFACTOR_W_OHM_K2
        assert math.isclose(l_nd_factor, r_val + 2.5, rel_tol=2e-4)
        assert math.isclose(l_deg_factor, (math.pi**2) / 3.0, rel_tol=2e-3)
        assert math.isclose(float(deg["Hall_factor_rH"][0]), 1.0, rel_tol=2e-3)

    rh_ac_nd = float(parabolic_band_state_general_r(-16.0, temperature_k=300.0, mstar_dos_ratio=1.0, scattering_r=-0.5)["Hall_factor_rH"][0])
    rh_neu_nd = float(parabolic_band_state_general_r(-16.0, temperature_k=300.0, mstar_dos_ratio=1.0, scattering_r=0.0)["Hall_factor_rH"][0])
    assert math.isclose(rh_ac_nd, 3.0 * math.pi / 8.0, rel_tol=2e-4)
    assert math.isclose(rh_neu_nd, 1.0, rel_tol=2e-4)


def test_two_band_semimetal_and_isothermal_bipolar_and_negative_eg():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 1. Exact round-trip test for semimetal point-by-point inversion (both 'hall-split' and 'fixed-gap')
        t_arr = np.linspace(100.0, 350.0, 6)
        eta_e_true, eta_h_true, eg_true = solve_bipolar_neutrality_eta(
            t_arr,
            n_dop_m3=0.0,
            m_maj_dos=0.530,
            m_min_dos=0.276,
            eg0_ev=-0.095,
            beta_eg_ev_k=-5e-5,
            allow_semimetal=True,
        )
        st_e = parabolic_band_state_general_r(eta_e_true, temperature_k=t_arr, mstar_dos_ratio=0.530, mu0_cm2_vs=1.0, scattering_r=-0.5, carrier_sign=-1)
        st_h = parabolic_band_state_general_r(eta_h_true, temperature_k=t_arr, mstar_dos_ratio=0.276, mu0_cm2_vs=1.0, scattering_r=-0.5, carrier_sign=+1)
        mu_e_true = 420.0 * ((t_arr / 250.0) ** -0.9)
        mu_h_true = 125.0 * ((t_arr / 250.0) ** -0.8)
        sig_e_sm = 1.602176634e-19 * st_e["n_m-3"] * (mu_e_true * 1e-4)
        sig_h_sm = 1.602176634e-19 * st_h["n_m-3"] * (mu_h_true * 1e-4)
        sig_tot_sm = sig_e_sm + sig_h_sm
        s_tot_uv = (sig_e_sm * st_e["Seebeck_uV_K"] + sig_h_sm * st_h["Seebeck_uV_K"]) / sig_tot_sm
        n_sum_cm3 = (st_e["n_m-3"] + st_h["n_m-3"]) * 1e-6

        sm_csv = tmp_dir / "syn_semimetal.csv"
        pd.DataFrame(
            {
                "Temperature_K": t_arr,
                "Resistivity_uOhm_m": 1e6 / sig_tot_sm,
                "Seebeck_uV_K": s_tot_uv,
                "nH_cm-3": n_sum_cm3,
            }
        ).to_csv(sm_csv, index=False)

        # Missing --fix-m1 / --fix-m2 must exit with status code 2
        assert two_band_cli_main([str(sm_csv), "--mode", "semimetal", "--no-show"]) == 2

        res_sm_split = run_two_band_workflow(
            sm_csv,
            mode="semimetal",
            output_dir=tmp_dir / "out_sm_split",
            fix_m1=0.530,
            fix_m2=0.276,
            semimetal_closure="hall-split",
            formats=("png",),
            copy_to_data_dir=False,
            show=False,
        )
        pts_sm = pd.read_csv(res_sm_split["outputs"]["points_csv"])
        assert np.allclose(pts_sm["Band_Gap_or_Overlap_eV"].to_numpy(), eg_true, rtol=1e-7, atol=1e-9)
        assert np.allclose(pts_sm["Mobility_e_cm2_V-1_s-1"].to_numpy(), mu_e_true, rtol=1e-7)
        assert np.allclose(pts_sm["Mobility_h_cm2_V-1_s-1"].to_numpy(), mu_h_true, rtol=1e-7)
        expected_a = (mu_e_true / mu_h_true) * ((0.530 / 0.276) ** 1.5)
        assert np.allclose(pts_sm["Weighted_Mobility_Ratio_A"].to_numpy(), expected_a, rtol=1e-7)

        res_sm_fixed = run_two_band_workflow(
            sm_csv,
            mode="semimetal",
            output_dir=tmp_dir / "out_sm_fixed",
            fix_m1=0.530,
            fix_m2=0.276,
            fix_eg0=-0.095,
            beta_eg_ev_k=-5e-5,
            semimetal_closure="fixed-gap",
            formats=("png",),
            copy_to_data_dir=False,
            show=False,
        )
        pts_fx = pd.read_csv(res_sm_fixed["outputs"]["points_csv"])
        assert np.allclose(pts_fx["Mobility_e_cm2_V-1_s-1"].to_numpy(), mu_e_true, rtol=1e-7)

        # 2. Bipolar global fit with negative bandgap (--allow-semimetal), N_dop = 0, and Matthiessen mobility
        ev_neg = evaluate_bipolar_temperature_series(
            t_arr,
            majority_sign=-1,
            n_dop_cm3=0.0,
            m_maj_dos=0.530,
            m_min_dos=0.276,
            mu0_maj_300_cm2_vs=780.0,
            mu_imp_maj_cm2_vs=2600.0,
            b_min_over_maj=0.23,
            eg0_ev=-0.095,
            allow_semimetal=True,
        )
        neg_csv = tmp_dir / "syn_bipolar_semimetal.csv"
        pd.DataFrame(
            {
                "Temperature_K": t_arr,
                "Seebeck_uV_K": ev_neg["Seebeck_uV_K"],
                "Conductivity_S_cm-1": ev_neg["Conductivity_S_cm-1"],
                "nH_cm-3": ev_neg["nH_cm-3"],
            }
        ).to_csv(neg_csv, index=False)

        res_neg = run_two_band_workflow(
            neg_csv,
            mode="bipolar",
            output_dir=tmp_dir / "out_bip_neg",
            fix_m1=0.530,
            fix_m2=0.276,
            fix_n_dop_cm3=0.0,
            fix_b=0.23,
            allow_semimetal=True,
            matthiessen=True,
            fit_nh=True,
            formats=("png",),
            copy_to_data_dir=False,
            show=False,
        )
        assert math.isclose(res_neg["fit"]["fitted_Eg0_eV"], -0.095, abs_tol=0.004)
        assert res_neg["fit"]["seebeck_rmse_uV_K"] < 0.5

        # 3. Isothermal-bipolar Pisarenko & weighted-mobility A_0 recovery
        nh_iso = np.logspace(18.6, 20.2, 9) * 1e6
        iso_true = predict_isothermal_bipolar_at_nh(
            nh_iso,
            temperature_k=300.0,
            majority_sign=-1,
            m_maj_dos=0.55,
            m_min_dos=0.55,
            eg_ev=0.07,
            mu0_maj_cm2_vs=320.0,
            b_min_over_maj=0.20,
        )
        iso_csv = tmp_dir / "syn_iso_bipolar.csv"
        pd.DataFrame(
            {
                "nH_cm-3": iso_true["nH_cm-3"],
                "Seebeck_uV_K": iso_true["Seebeck_uV_K"],
                "Conductivity_S_cm-1": iso_true["Conductivity_S_cm-1"],
            }
        ).to_csv(iso_csv, index=False)

        res_iso = run_two_band_workflow(
            iso_csv,
            mode="isothermal-bipolar",
            output_dir=tmp_dir / "out_iso_bip",
            temperature_k=300.0,
            fix_m1=0.55,
            fix_m2=0.55,
            fix_eg0=0.07,
            formats=("png",),
            copy_to_data_dir=False,
            show=False,
        )
        assert math.isclose(res_iso["fit"]["weighted_mobility_ratio_A0_e_over_h"], 5.0, rel_tol=0.04)
        assert res_iso["fit"]["seebeck_rmse_uV_K"] < 1.0

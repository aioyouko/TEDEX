"""Thermoelectric transport & phonon physics modeling suite:
- `fermi`: Vectorized Fermi-Dirac F_j(eta) and two-parameter Kane ^n L_k^m(eta, alpha) integrals
- `callaway`: Debye-Callaway & Cahill-minimum lattice thermal conductivity + spectral/MFP analysis
- `debye_einstein`: Low-temperature Cp(T) Sommerfeld + Debye + multi-Einstein rattler boson-peak fit
- `skb`: Non-parabolic Single Kane Band (SKB) effective mass, mobility, deformation potential & zT fit
- `two_band`: Two-Band convergence (L+Sigma / split-valence) & bipolar (e+h) transport fitting with SVD diagnostics
"""

from te_analysis.tools.physics.callaway import (
    CallawayMaterialParams,
    CallawayScatteringParams,
    cahill_minimum_kappa,
    callaway_kappa_l,
    fit_callaway_model,
    run_callaway_workflow,
)
from te_analysis.tools.physics.debye_calc import (
    MissingDebyeParametersError,
    debye_from_heat_capacity,
    debye_from_ultrasonic,
)
from te_analysis.tools.physics.debye_einstein import (
    debye_molar_cv,
    einstein_molar_cv,
    fit_debye_einstein_model,
    run_debye_einstein_workflow,
)
from te_analysis.tools.physics.fermi import (
    fermi_integral_scalar,
    fermi_integral_vec,
    kane_integral_scalar,
    kane_integral_vec,
    single_band_state,
    solve_eta_from_nh_skb,
    solve_eta_from_seebeck_skb,
)
from te_analysis.tools.physics.skb import (
    SKBFitConfig,
    fit_skb_model,
    run_skb_workflow,
)
from te_analysis.tools.physics.two_band import (
    combine_two_bands,
    fit_two_band_bipolar,
    fit_two_band_convergence,
    run_two_band_workflow,
)

__all__ = [
    "CallawayMaterialParams",
    "CallawayScatteringParams",
    "SKBFitConfig",
    "cahill_minimum_kappa",
    "callaway_kappa_l",
    "combine_two_bands",
    "debye_molar_cv",
    "einstein_molar_cv",
    "fermi_integral_scalar",
    "fermi_integral_vec",
    "fit_callaway_model",
    "fit_debye_einstein_model",
    "fit_skb_model",
    "fit_two_band_bipolar",
    "fit_two_band_convergence",
    "kane_integral_scalar",
    "kane_integral_vec",
    "run_callaway_workflow",
    "run_debye_einstein_workflow",
    "run_skb_workflow",
    "run_two_band_workflow",
    "single_band_state",
    "solve_eta_from_nh_skb",
    "solve_eta_from_seebeck_skb",
]

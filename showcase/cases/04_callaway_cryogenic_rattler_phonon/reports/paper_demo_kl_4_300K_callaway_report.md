# Debye–Callaway Lattice Thermal Conductivity Fit Report (`paper_demo_kl_4_300K`)

## 1. Lattice Constants & Goodness-of-Fit Summary

| Quantity | Symbol | Value | Unit | Source / Literature Equivalents |
| --- | :---: | :---: | :---: | --- |
| Debye temperature | $\Theta_{\mathrm{D}}$ | `146.00` | K | $\omega_{\mathrm{D}}/\nu_{\mathrm{D}} =$ `19.11` / `3.04` THz (`12.58` meV) |
| Average sound velocity | $v_{\mathrm{s}}$ | `1445.0` | m s$^{-1}$ | Input / Anderson sound velocity |
| Average atomic volume | $V_0$ | `25.58` | $\text{\AA}^3$ | Derived from Debye sphere |
| Grüneisen / Resonant damping | $\gamma_{\mathrm{G}}$ / $\gamma_{\mathrm{R}}$ | `1.60` / `0` | — | Umklapp divisor $b_{\mathrm{U}} = 3$ |
| Amorphous limit at 300 K | $\kappa_{\min}(300\text{ K})$ | `0.2751` | W m$^{-1}$ K$^{-1}$ | Cahill–Watson–Pohl model |
| Experimental $T$ range | $T$ | `4.09 – 302.72` | K | `67` experimental points |
| Goodness of fit | $R^2$ / RMSE | `0.9918` (`99.18%`) / `0.0153` | W m$^{-1}$ K$^{-1}$ | MAPE = `3.53%`, SSE = `0.01560`, $\chi^2_{\mathrm{P}} =$ `0.03755` |
| Median phonon MFP at 300 K | $\Lambda_{50\%}$ | `0.68` | nm | 10%–90% window: `0.15 – 6.21` nm |

## 2. Scattering Parameters, Uncertainties & Dual-Unit Equivalents

| Mechanism | Relaxation Rate $\tau_i^{-1}(\omega, T)$ | Param | Optimal Value | Std. Error (SE) | 95% CI Half-Width | Unit | Literature Dual-Unit Equivalent | Status |
| --- | --- | :---: | :---: | :---: | :---: | :---: | --- | :---: |
| Umklapp (`U`) | $\tau_{\mathrm{U}}^{-1} = B \omega^2 T e^{-\Theta_{\mathrm{D}}/(b_{\mathrm{U}}T)}$ | $B$ | **`58.98`** | `± 1.7` (`2.9%`) | `± 3.41` | $10^{-18}$ s K$^{-1}$ | `5.898` $\times 10^{-17}$ s K$^{-1}$ | Fit |
| Boundary (`B`) | $\tau_{\mathrm{B}}^{-1} = v_{\mathrm{s}} / L$ | $L$ | **`171.6`** | `± 88.3` (`51.5%`) | `± 177` | nm | `0.1716` $\mu$m | Fit |
| Point Defect (`PD`) | $\tau_{\mathrm{PD}}^{-1} = A \omega^4$ | $A$ | **`6.793`** | `± 0.349` (`5.1%`) | `± 0.698` | $10^{-41}$ s$^3$ | $\Gamma =$ `0.1007` | Fit |
| Resonant (`RES`) | $\tau_{\mathrm{RES}}^{-1} = C_{\mathrm{RES}}\omega^2 / [(\omega_0^2-\omega^2)^2 + (\gamma_{\mathrm{R}}\omega_0\omega)^2]$ | $C_{\mathrm{RES}}$ | **`16.21`** | `± 1.46` (`9.0%`) | `± 2.91` | $10^{35}$ s$^{-3}$ | **`1.621`** $\times 10^{36}$ s$^{-3}$ | Fit |
| Resonant Temp (`TE`) | $\omega_0 = k_{\mathrm{B}}\Theta_{\mathrm{E}} / \hbar$ | $\Theta_{\mathrm{E}}$ | **`29.52`** | `± 1.65` (`5.6%`) | `± 3.31` | K | $\omega_{\mathrm{RES}}/\nu_{\mathrm{RES}} =$ **`3.87` / `0.615`** THz (`2.54` meV, `20.5` cm$^{-1}$) | Fit |

## 3. Cumulative Stage Thermal Conductivity & Scattering Shares

| $T$ (K) | $\kappa_{\mathrm{L}}$ (`U`) | $\kappa_{\mathrm{L}}$ (`U + B`) | $\kappa_{\mathrm{L}}$ (`U + B + PD`) | $\kappa_{\mathrm{L}}$ (`U + B + PD + RES`) | Order-Independent Scattering Share $S_m(T)$ |
| :---: | :---: | :---: | :---: | :---: | --- |
| `4.1` | `505146.1872` | `0.2310` | `0.1633` | `0.0343` | `B`: 38.7%, `RES`: 60.2%, `PD`: 1.1%, `U`: 0.0% |
| `10.0` | `459.1226` | `3.2652` | `0.7271` | `0.1143` | `B`: 17.1%, `RES`: 55.9%, `PD`: 27.0%, `U`: 0.0% |
| `48.4` | `7.1050` | `5.3313` | `1.2943` | `0.5876` | `B`: 4.3%, `RES`: 21.3%, `PD`: 62.9%, `U`: 11.5% |
| `300.0` | `0.6110` | `0.5741` | `0.3981` | `0.3088` | `B`: 2.5%, `RES`: 10.2%, `PD`: 29.6%, `U`: 57.7% |
| `302.7` | `0.6047` | `0.5685` | `0.3952` | `0.3070` | `B`: 2.5%, `RES`: 10.1%, `PD`: 29.5%, `U`: 57.9% |

## 4. Identifiability & Collinearity Diagnostics

- Strong parameter collinearity between grain_size_nm and rattler_theta_e_k (r = -0.929); consider fixing one from independent Hall/optical/DFT data.

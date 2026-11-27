---
name: te-physics-models
description: >-
  Run and interpret thermoelectric phonon and electronic transport physics models via
  `te` / `python main.py`: Debye-Callaway lattice thermal conductivity and spectral MFP
  (`callaway`), Debye temperature and sound velocity calculator (`debye-calc`),
  Debye-Einstein low-T heat capacity (`debye-einstein`), Single Parabolic Band (`spb`),
  non-parabolic Single Kane Band (`skb`), and Two-Band convergence, semimetal Hall
  inversion, or bipolar transport (`two-band`). Use whenever the user asks to fit or
  simulate kappa_L(T), phonon scattering contributions, Cp(T) boson peaks, Debye
  temperature, Pisarenko curves, effective mass, deformation potential, band convergence,
  or bipolar thermal conductivity.
---

# Thermoelectric Phonon & Band Transport Physics Suite

Always execute these models through `te <command> ... --no-show` (or `python main.py <command> ... --no-show`) rather than writing custom fitting scripts. All models share unified publication styling (`#79ADD8`/`#264B73` experimental markers, `#E64B35` best-fit curve, inside-axes legends), default output routing under `outputs/models/<model_name>` (`paths.models` in `configs/workspace.json`), and structured CSVs plus `*_summary.json` with SVD Jacobian condition numbers, 95% confidence intervals, and parameter correlation matrices.

## 1. Debye Temperature & Sound Velocity Calculator (`debye-calc`)

Computes average sound velocity $v_{\mathrm{s}}$, Debye temperature $\Theta_{\mathrm{D}}$, bulk/shear/Young's moduli, Poisson ratio $\nu$, and Grüneisen parameter $\gamma_{\mathrm{G}}$ from two standard experimental routes:

```bash
# Route A: Room-temperature ultrasonic pulse-echo velocities (v_l, v_t)
te debye-calc --vl 2600 --vt 1450 --density-g-cm3 6.15 --molar-mass 433.0 --atoms-per-fu 4
te debye-calc --vl 2600 --vt 1450 --atomic-volume-a3 25.6 -o outputs/models/debye_calc.json

# Route B: Cryogenic heat capacity Cp(T) linear fit (Cp/T = gamma + beta * T^2)
te debye-calc --cp-csv path/to/cp.csv --atoms-per-fu 4 --atomic-volume-a3 29.2
te debye-calc --cp-beta 0.85 --atoms-per-fu 4 --density-g-cm3 6.15 --molar-mass 433.0
```

## 2. Debye–Callaway Multi-Source Lattice Thermal Conductivity (`callaway`)

Fits cryogenic-to-high-temperature $\kappa_{\mathrm{L}}(T)$ (accepts named CSV/TSV/XLSX columns, 2-column headerless `T, kappa_L` files, or full TE tables from which electronic $\kappa_{\mathrm{e}}$ is automatically subtracted via SPB Lorenz number in `te_analysis/tools/physics/lorenz.py`).

### Supported Scattering Mechanisms (`--mechanisms`)
- `U`: Umklapp ($\tau_{\mathrm{U}}^{-1} = B \omega^2 T e^{-\Theta_{\mathrm{D}}/(b_{\mathrm{U}}T)}$)
- `B` (or `GB`): Grain/phase boundary ($\tau_{\mathrm{B}}^{-1} = v_{\mathrm{s}}/L$)
- `PD`: Point defects ($\tau_{\mathrm{PD}}^{-1} = A \omega^4$; derives disorder parameter $\Gamma$)
- `EP`: Electron–phonon / planar fault ($\tau_{\mathrm{EP}}^{-1} = E_{\mathrm{ep}}\omega$)
- `D`: Dislocation core ($\omega^3$) + strain field ($\omega$), parameterized by $N_{\mathrm{D}}$
- `NP`: Nanoprecipitates (Rayleigh $\omega^4$ to geometric crossover, `--np-radius-nm`)
- `RES` (or `R`): Local resonant / rattler mode ($\tau_{\mathrm{RES}}^{-1} = C_{\mathrm{RES}}\omega^2 / [(\omega_0^2-\omega^2)^2 + (\gamma_{\mathrm{R}}\omega_0\omega)^2]$; `TE` optimizes $\Theta_{\mathrm{E}}$)

```bash
# Full cryogenic-to-room-T fit with stage-by-stage shaded spectral kappa_s(hbar*omega) in meV
te callaway path/to/kl.csv -o outputs/models/callaway \
  --theta-d 146 --vs 1445 --mechanisms U B PD RES \
  --spectral-xaxis meV --spectral-norm x --rattler-damping 0 \
  --formats png svg --no-show

# Supply ultrasonic (vl, vt) directly instead of --theta-d / --vs
te callaway path/to/kl.csv --vl 2600 --vt 1450 --atomic-volume-a3 25.6 \
  --mechanisms U B PD --formats png svg --no-show

# Fix SEM grain size L = 80 nm to break low-T collinearity with resonant mode
te callaway path/to/kl.csv --theta-d 146 --vs 1445 \
  --mechanisms U B PD RES --grain-size-nm 80 --fit U PD RES TE --no-show
```

If neither `--theta-d`/`--vs`, `--vl`/`--vt`, nor `--cp-*` is supplied, `callaway` exits with code `2`. Ask the user which of the three parameter sets they can provide before re-running.

## 3. Debye–Einstein Low-Temperature Heat Capacity (`debye-einstein`)

Simultaneously fits Sommerfeld $\gamma T$, Debye acoustic lattice, and $1\text{–}3$ Einstein rattler modes in $C_p/T^3$ space to resolve boson peaks:

```bash
te debye-einstein path/to/cp_rattler.csv \
  --atoms-per-fu 4 --n-einstein 2 --volume-a3-per-fu 116.8 \
  --formats png svg --no-show
```

## 4. Electronic Band Models (`spb`, `skb`, `two-band`, or `band` Group)

Parabolic SPB models live under `spb`, while all parabolic + non-parabolic/multi-band models are also accessible under `band`:

```bash
# Parabolic SPB suite (`spb` or `band`)
te spb effective-mass path/to/pisarenko.csv --no-show
te spb conductivity path/to/sigma_seebeck.csv --no-show
te spb performance path/to/pisarenko.csv --no-show

# Non-parabolic Single Kane Band (SKB) — overlays SPB baseline for direct comparison
te skb path/to/skb_narrow_gap.csv \
  -T 300 --eg 0.25 --nv 4 --rho 8160 --vl 3050 --kL 0.9 --formats png svg --no-show

# Two-Band Mode A: Isothermal same-sign light + heavy band convergence (S and PF vs n_H)
te two-band path/to/two_band_convergence.csv \
  --mode convergence -T 300 --band1-eg 0.28 --fix-m1 0.36 --formats png svg --no-show

# Two-Band Mode B: Variable-temperature bipolar excitation & kappa_bi extraction
te two-band path/to/two_band_bipolar.csv \
  --mode bipolar --fix-m1 0.92 --fix-m2 0.75 --formats png svg --no-show

# Two-Band Mode C: Semimetal / compensated e+h point-by-point Hall+S+sigma inversion
te two-band path/to/two_band_semimetal.csv \
  --mode semimetal --fix-m1 0.530 --fix-m2 0.276 --formats png svg --no-show

# Two-Band Mode D: Isothermal opposite-sign e+h Pisarenko & weighted-mobility-ratio A_0 map
te two-band path/to/isothermal_bipolar.csv \
  --mode isothermal-bipolar -T 300 --fix-m1 0.53 --fix-m2 0.28 --fix-eg0 0.08 --formats png svg --no-show
```

Use `--fix-m1`, `--fix-m2`, `--fix-delta-e`, `--fix-b`, `--fix-eg0`, `--fix-ndop`, `--scattering-r`, `--allow-semimetal`, `--matthiessen`, or `--fit-nh` in `two-band` whenever DFT effective masses, optical/Arrhenius bandgaps, or Hall carrier densities are known. Note that `--mode semimetal` exits with code `2` if `--fix-m1` or `--fix-m2` is omitted.

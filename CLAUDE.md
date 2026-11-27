# Claude Code / Cowork Instructions

Please read and follow all workspace harness rules, CLI routing conventions, missing-parameter prompting protocols, and sample metadata/densification comparison rules defined in [AGENTS.md](./AGENTS.md).

## Key Reminders

1. **Prefer `python main.py <command> ... --no-show`** for all thermoelectric processing (`analyze`, `sync`), plotting (`plot-te`, `sciplot`, `plot-xrd`), XRD lattice refinement (`xrd-lattice`), and physics modeling (`spb`, `callaway`, `debye-calc`, `debye-einstein`, `skb`, `two-band`) instead of writing one-off plotting or fitting scripts.
2. **Consult the 5 Orthogonal Workspace Skills on Demand**:
   - `.agents/skills/te-workspace/SKILL.md` for `configs/workspace.json` initialization (`init`), folder mapping, and instrument/unit conventions.
   - `.agents/skills/te-data-pipeline/SKILL.md` for raw ZEM/LFA batch analysis (`analyze`), metadata ledger sync (`sync`), `assess`, and `bayes`.
   - `.agents/skills/te-plotting/SKILL.md` for `plot-te` options and `sciplot` 1D/2D/statistical plot kinds, recipes, overlays, palettes, and `--rename`.
   - `.agents/skills/te-xrd/SKILL.md` for `plot-xrd` stack/zoom/VT/Rietveld/peak-fit/Williamson–Hall layouts and `xrd-lattice` unit-cell fitting.
   - `.agents/skills/te-physics-models/SKILL.md` for Callaway, Debye–Einstein, Debye calculator, SPB, SKB, and Two-Band fitting flags and output tables.
3. **Ask When Required Physical Constants Are Missing**: If `callaway` or `debye-calc` exits with code `2`, ask the user for $(\Theta_{\mathrm{D}}, v_{\mathrm{s}})$, ultrasonic $(v_l, v_t)$, or low-$T$ $C_p(T)$ parameters rather than assuming defaults.

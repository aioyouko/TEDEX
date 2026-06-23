# zsh completion for the plot-te launcher.
#
# Usage:
#   source /path/to/te_agent_workspace/scripts/plot_te_completion.zsh
#   plot_te --s<Tab>
#
# Optional:
#   export PLOT_TE_WORKSPACE=/path/to/te_agent_workspace

_plot_te_completion_file="${${(%):-%N}:A}"
_plot_te_completion_dir="${_plot_te_completion_file:h}"
: "${PLOT_TE_WORKSPACE:=${_plot_te_completion_dir:h}}"

plot_te() {
  (cd "$PLOT_TE_WORKSPACE" && python main.py plot-te "$@")
}

_plot_te_plot_modes() {
  local -a modes
  modes=(
    'combined:combined summary figure'
    'single:single-property figures'
    'both:combined plus single-property figures'
  )
  _describe -t plot-modes 'plot mode' modes
}

_plot_te_properties() {
  local -a properties
  properties=(
    'resistivity:electrical resistivity'
    'seebeck:Seebeck coefficient'
    'conductivity:electrical conductivity'
    'thermal_conductivity:total thermal conductivity'
    'diffusivity:thermal diffusivity'
    'carrier_thermal_conductivity:carrier thermal conductivity'
    'lattice_thermal_conductivity:lattice thermal conductivity'
    'lorenz_number:Lorenz number'
    'generalized_fermi_level:generalized Fermi level'
    'weighted_mobility:weighted mobility'
    'quality_factor:quality factor'
    'zt:figure of merit'
    'power_factor:power factor'
  )
  _describe -t te-properties 'TE property' properties
}

_plot_te_formats() {
  local -a formats
  formats=(
    'svg:editable vector SVG'
    'png:raster preview PNG'
    'pdf:publication vector PDF'
  )
  _describe -t output-formats 'output format' formats
}

_plot_te_legends() {
  local -a legends
  legends=(
    'none:no legend'
    'inside:legend inside the plot frame'
    'outside:legend above the plot frame'
  )
  _describe -t legend-positions 'single-property legend' legends
}

_plot_te_selectors() {
  local -a batches csvs

  if [[ -d "$PLOT_TE_WORKSPACE/data/processed" ]]; then
    batches=("${(@f)$(command find "$PLOT_TE_WORKSPACE/data/processed" -maxdepth 1 -type d -name 'CHY-*-processed' -exec basename {} \; 2>/dev/null)}")
    batches=("${(@)batches%-processed}")
    (( ${#batches[@]} )) && compadd -a batches
  fi

  _files -g '*.csv(-.)'
}

_plot_te() {
  _arguments -C -s -S \
    '(-h --help)'{-h,--help}'[show help]' \
    '--plot-mode[choose combined, single, or both output]:plot mode:_plot_te_plot_modes' \
    '--single-properties[select single-property plots]:property:_plot_te_properties' \
    '--properties[select single-property plots]:property:_plot_te_properties' \
    '--resistivity[plot electrical resistivity]' \
    '--seebeck[plot Seebeck coefficient]' \
    '--conductivity[plot electrical conductivity]' \
    '--thermal-conductivity[plot total thermal conductivity]' \
    '--diffusivity[plot thermal diffusivity]' \
    '--carrier-thermal-conductivity[plot carrier thermal conductivity]' \
    '--lattice-thermal-conductivity[plot lattice thermal conductivity]' \
    '--lorenz-number[plot Lorenz number]' \
    '--generalized-fermi-level[plot generalized Fermi level]' \
    '--weighted-mobility[plot weighted mobility]' \
    '--quality-factor[plot quality factor]' \
    '--zt[plot ZT]' \
    '--power-factor[plot power factor]' \
    '--inter-batch[plot selected samples together]' \
    '--comparison-id[set output folder and filename prefix]:comparison id:' \
    '--xlim[set shared temperature axis limits]:low:' \
    '--ylim[set y-axis limits; use LOW HIGH or PROPERTY LOW HIGH]:value:' \
    '--subplot-aspect[set plot frame ratio, e.g. 10:8 or 1:1]:aspect ratio:' \
    '--single-legend[set single-property legend placement]:legend:_plot_te_legends' \
    '--legend[add an inside legend to selected single-property plots]' \
    '--legend-font-size[set single-property legend font size in points]:font size:' \
    '--marker-size[set marker size in points]:marker size:' \
    '--formats[set output format]:format:_plot_te_formats' \
    '--pdf[also save PDF output]' \
    '--show[show matplotlib preview window]' \
    '--no-show[save without opening a preview window]' \
    '*:batch/sample/path selector:_plot_te_selectors'
}

if ! whence -w compdef >/dev/null 2>&1; then
  autoload -Uz compinit
  compinit
fi

compdef _plot_te plot_te
compdef _plot_te plot-te

unset _plot_te_completion_file _plot_te_completion_dir

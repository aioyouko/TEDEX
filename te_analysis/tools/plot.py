import os
from pathlib import Path
from itertools import cycle
from math import gcd

from te_analysis.tools.matplotlib_backend import configure_matplotlib_backend, show_interactive_figures

configure_matplotlib_backend()

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import ticker

try:
    from te_analysis.plotstyle import axis_formatting, mpl_arial
except ImportError:
    axis_formatting = None
    mpl_arial = None


from te_analysis.tools.colors import DEFAULT_COLOR_SET, SEQUENTIAL_COLOR_SETS, get_colors
from te_analysis.tools.legend_layout import (
    axis_limit_locked,
    place_legend_inside,
    place_shared_legend_inside_panels,
)

DEFAULT_COLORS = get_colors()

DEFAULT_MARKERS = ['o', 's', 'D', '^', 'v', '<', '>', '*', 'p', 'P', 'X', 'h', 'H', '8', 'd']

# Balanced Origin / Science publication typography & bold frame weights for a ~6.6 x 5.3 in canvas.
DEFAULT_PLOT_SCALE = 2.0
PAPER_MAJOR_TICK_LENGTH = 7.5
PAPER_MINOR_TICK_LENGTH = 4.2
DEFAULT_AXIS_LINE_WIDTH = 1.65
DEFAULT_TICK_LINE_WIDTH = 1.65
DEFAULT_AXIS_LABEL_PAD = 6.0
DEFAULT_TICK_PAD = 5.5
DEFAULT_TEMPERATURE_MAJOR_TICK = 100
DEFAULT_TEMPERATURE_MINOR_TICK = 50
DEFAULT_SUBPLOT_ASPECT = "10:8"
DEFAULT_SUBPLOT_HEIGHT = 2.65 * DEFAULT_PLOT_SCALE  # Inches; width follows the selected aspect ratio.
DEFAULT_AXIS_LABEL_SIZE = 22.0
DEFAULT_TICK_LABEL_SIZE = 18.5
DEFAULT_FIGURE_DIR = "figures"
DEFAULT_TE_FIGURE_DIR = "outputs/figures"
DEFAULT_MARKER_SIZE = 12.0
DEFAULT_LINE_WIDTH = 2.3
DEFAULT_LEGEND_FONT_SIZE = 15.0
DEFAULT_LEGEND_LABEL_SPACING = 0.50
DEFAULT_LEGEND_HANDLE_HEIGHT = 1.0

TE_PLOT_SPECS = {
    'resistivity': {
        'column': 'Resistivity',
        'scale': 1e5,
        'title': 'Electrical Resistivity',
        'ylabel': r'$\rho$ (m$\Omega$ cm)',
    },
    'seebeck': {
        'column': 'Seebeck',
        'scale': 1e6,
        'title': 'Seebeck Coefficient',
        'ylabel': '$S$ (\u00b5V K$^{-1}$)',
    },
    'conductivity': {
        'column': 'Conductivity',
        'scale': 0.01,
        'title': 'Electrical Conductivity',
        'ylabel': r'$\sigma$ (S cm$^{-1}$)',
    },
    'thermal_conductivity': {
        'column': 'Thermal_Conductivity',
        'scale': 1,
        'title': 'Total Thermal Conductivity',
        'ylabel': r'$\kappa_{\mathrm{tot}}$ (W m$^{-1}$ K$^{-1}$)',
    },
    'diffusivity': {
        'column': 'Diffusivity',
        'scale': 1,
        'title': 'Thermal Diffusivity',
        'ylabel': 'Diffusivity',
    },
    'carrier_thermal_conductivity': {
        'column': 'Carrier_Thermal_Conductivity',
        'scale': 1,
        'title': 'Carrier Thermal Conductivity',
        'ylabel': r'$\kappa_{\mathrm{e}}$ (W m$^{-1}$ K$^{-1}$)',
        'allow_missing': True,
    },
    'lattice_thermal_conductivity': {
        'column': 'Lattice_Thermal_Conductivity',
        'scale': 1,
        'title': 'Lattice Thermal Conductivity',
        'ylabel': r'$\kappa_{\mathrm{L}}$ (W m$^{-1}$ K$^{-1}$)',
        'allow_missing': True,
    },
    'lorenz_number': {
        'column': 'Lorenz_Number_1e-8_WOhmK-2',
        'scale': 1,
        'title': 'Lorenz Number',
        'ylabel': r'$L$ ($10^{-8}$ W $\Omega$ K$^{-2}$)',
        'allow_missing': True,
    },
    'generalized_fermi_level': {
        'column': 'Generalized_Fermi_Level',
        'scale': 1,
        'title': 'Generalized Fermi Level',
        'ylabel': r'$\eta$',
        'allow_missing': True,
    },
    'weighted_mobility': {
        'column': 'Weighted_Mobility_cm2_V-1_s-1',
        'scale': 1,
        'title': 'Weighted Mobility',
        'ylabel': r'$\mu_{\mathrm{w}}$ (cm$^2$ V$^{-1}$ s$^{-1}$)',
        'allow_missing': True,
    },
    'quality_factor': {
        'column': 'Quality_Factor_B',
        'scale': 1,
        'title': 'Quality Factor',
        'ylabel': r'$B$',
        'allow_missing': True,
    },
    'zt': {
        'column': 'ZT',
        'scale': 1,
        'title': 'Figure of Merit',
        'ylabel': r'$ZT$',
    },
    'power_factor': {
        'column': 'Power_Factor',
        'scale': 1e4,
        'title': 'Power Factor',
        'ylabel': r'$PF$ ($\mathrm{\mu}$W cm$^{-1}$ K$^{-2}$)',
    },
}


def apply_plot_style(font='arial', mode='single'):
    """
    Apply one standard plot style for this project.

    Scale the original compact style with the larger default canvas so axis
    labels, markers, lines, and spacing retain their visual proportions.
    """
    font_name = 'Arial' if font == 'arial' else 'Times New Roman'
    math_fontset = 'custom' if font == 'arial' else 'stix'

    if mode == 'summary':
        font_size = 16.5
        title_size = 18.5
        marker_size = DEFAULT_MARKER_SIZE
        line_width = DEFAULT_LINE_WIDTH
    else:
        font_size = 17.5
        title_size = 19.5
        marker_size = DEFAULT_MARKER_SIZE
        line_width = DEFAULT_LINE_WIDTH

    plt.rcParams.update({
        'font.sans-serif': font_name,
        'mathtext.fontset': math_fontset,
        'lines.linewidth': line_width,
        'lines.markersize': marker_size,
        'lines.markeredgewidth': 1.4,
        'axes.linewidth': DEFAULT_AXIS_LINE_WIDTH,
        'axes.labelpad': DEFAULT_AXIS_LABEL_PAD,
        'axes.titlesize': title_size,
        'axes.labelsize': DEFAULT_AXIS_LABEL_SIZE,
        'xtick.labelsize': DEFAULT_TICK_LABEL_SIZE,
        'ytick.labelsize': DEFAULT_TICK_LABEL_SIZE,
        'xtick.direction': 'in',
        'xtick.major.width': DEFAULT_TICK_LINE_WIDTH,
        'xtick.minor.width': DEFAULT_TICK_LINE_WIDTH,
        'xtick.major.size': PAPER_MAJOR_TICK_LENGTH,
        'xtick.minor.size': PAPER_MINOR_TICK_LENGTH,
        'ytick.direction': 'in',
        'ytick.major.width': DEFAULT_TICK_LINE_WIDTH,
        'ytick.minor.width': DEFAULT_TICK_LINE_WIDTH,
        'ytick.major.size': PAPER_MAJOR_TICK_LENGTH,
        'ytick.minor.size': PAPER_MINOR_TICK_LENGTH,
        'xtick.minor.visible': True,
        'ytick.minor.visible': True,
        'font.size': font_size,
        'font.weight': 'normal',
        'legend.frameon': False,
        'legend.fontsize': DEFAULT_LEGEND_FONT_SIZE,
        'legend.title_fontsize': DEFAULT_LEGEND_FONT_SIZE,
        'legend.labelspacing': DEFAULT_LEGEND_LABEL_SPACING,
        'legend.handleheight': DEFAULT_LEGEND_HANDLE_HEIGHT,
        'savefig.dpi': 600,
        'savefig.bbox': 'tight',
    })


def get_style_cycles(color_set=None, count=None):
    """
    Return project color and marker cycles.

    The color and marker sequences advance together for easy visual scanning,
    but the marker sequence is offset after each full color pass. This keeps
    marker variation in the first palette cycle and delays repeated color-marker
    pairs for large multi-sample plots.
    """
    name = color_set or DEFAULT_COLOR_SET
    # Keep categorical cycle lengths stable so marker offsets retain their meaning.
    colors = get_colors(name, count if name in SEQUENTIAL_COLOR_SETS else None)
    if not colors:
        colors = get_colors(name, 1)
    markers = getattr(mpl_arial, 'marker_list_main', DEFAULT_MARKERS) if mpl_arial else DEFAULT_MARKERS

    color_count = len(colors)
    marker_count = len(markers)
    marker_shift = 1
    while gcd(color_count + marker_shift, marker_count) != 1:
        marker_shift += 1

    sequence_length = color_count * marker_count
    color_sequence = []
    marker_sequence = []

    for index in range(sequence_length):
        color_sequence.append(colors[index % color_count])
        marker_index = (index + marker_shift * (index // color_count)) % marker_count
        marker_sequence.append(markers[marker_index])

    return cycle(color_sequence), cycle(marker_sequence)


def normalize_output_formats(formats=None, pdf=False, default=('svg',)):
    """
    Normalize output format names and optionally append PDF output.
    """
    selected_formats = formats if formats else default
    normalized = []

    for file_format in selected_formats:
        clean_format = str(file_format).strip().lstrip('.').lower()
        if clean_format and clean_format not in normalized:
            normalized.append(clean_format)

    if pdf and 'pdf' not in normalized:
        normalized.append('pdf')

    return normalized or list(default)


def load_processed_csvs(processed_data):
    """
    Convert a list of processed CSV paths or a dict of dataframes into a
    standard sample_name -> dataframe mapping.
    """
    if isinstance(processed_data, dict):
        return processed_data

    data_by_sample = {}

    for data_item in processed_data:
        if not os.path.exists(data_item):
            print(f"⚠️ plot skipped missing file: {data_item}")
            continue

        sample_name = os.path.splitext(os.path.basename(data_item))[0]
        data_by_sample[sample_name] = pd.read_csv(data_item)

    return data_by_sample


def format_te_axis(ax, show_grid=False, tick_labelsize=DEFAULT_TICK_LABEL_SIZE):
    """
    Apply consistent axis formatting to one matplotlib axis.
    """
    if axis_formatting:
        axis_formatting.format_axes(
            ax,
            grid=show_grid,
            tick_labelsize=tick_labelsize,
        )
    else:
        ax.minorticks_on()
        ax.tick_params(which='both', direction='in', top=False, right=False)
        ax.tick_params(which='major', width=1, length=6, labelsize=tick_labelsize)
        ax.tick_params(which='minor', width=1, length=4)
        if show_grid:
            ax.grid(True, which='major', linestyle='--', linewidth=0.5, alpha=0.5)
        else:
            ax.grid(False)

    ax.tick_params(which='both', pad=DEFAULT_TICK_PAD, width=DEFAULT_TICK_LINE_WIDTH)
    ax.tick_params(which='major', length=PAPER_MAJOR_TICK_LENGTH)
    ax.tick_params(which='minor', length=PAPER_MINOR_TICK_LENGTH)
    ax.xaxis.labelpad = DEFAULT_AXIS_LABEL_PAD
    ax.yaxis.labelpad = DEFAULT_AXIS_LABEL_PAD
    for spine in ax.spines.values():
        spine.set_linewidth(DEFAULT_AXIS_LINE_WIDTH)


def _nice_step(raw_step: float) -> float:
    import math
    if not math.isfinite(raw_step) or raw_step <= 0.0:
        return 1.0
    exp = math.floor(math.log10(raw_step))
    base = 10.0 ** exp
    frac = raw_step / base
    if frac <= 1.0:
        mult = 1.0
    elif frac <= 2.0:
        mult = 2.0
    elif frac <= 2.5:
        mult = 2.5
    elif frac <= 5.0:
        mult = 5.0
    else:
        mult = 10.0
    return mult * base


def compute_smart_temperature_axis(
    t_values,
    explicit_xlim=None,
    major_tick=None,
    minor_tick=None,
):
    """Compute intelligent temperature major/minor tick spacing and snapped xlim bounds.

    Thermoelectric measurements routinely start near 300 K and end at X73 K
    (e.g. 573 K = 300 C, 673 K = 400 C, 773 K = 500 C, 873 K = 600 C). Default
    5% Matplotlib margins stop at 587 / 796 K and hide the 600 / 800 K tick.
    This helper snaps the upper bound to the next major tick when close (giving
    300, 400, 500, 600 K) while keeping a clean ~20% major-tick breathing pad
    when data starts or ends right on a major tick (e.g. 280 to 600 K).
    """
    import math
    import numpy as np

    arr = np.asarray(t_values, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        maj = major_tick if major_tick is not None else DEFAULT_TEMPERATURE_MAJOR_TICK
        mnr = minor_tick if minor_tick is not None else DEFAULT_TEMPERATURE_MINOR_TICK
        return explicit_xlim, maj, mnr

    t_min = float(np.min(arr))
    t_max = float(np.max(arr))
    span = t_max - t_min

    if span <= 1e-6:
        maj = major_tick if major_tick is not None else 50
        mnr = minor_tick if minor_tick is not None else 25
        lo_exp = explicit_xlim[0] if (explicit_xlim and len(explicit_xlim) == 2) else None
        hi_exp = explicit_xlim[1] if (explicit_xlim and len(explicit_xlim) == 2) else None
        return (lo_exp if lo_exp is not None else t_min - 25.0, hi_exp if hi_exp is not None else t_max + 25.0), maj, mnr

    if major_tick is None:
        if span <= 45.0:
            maj, auto_mnr = 10.0, 5.0
        elif span <= 115.0:
            maj, auto_mnr = 20.0, 10.0
        elif span <= 220.0:
            maj, auto_mnr = 50.0, 25.0
        elif span <= 720.0:
            maj, auto_mnr = 100.0, 50.0
        else:
            maj, auto_mnr = 200.0, 100.0
    else:
        maj = float(major_tick)
        auto_mnr = maj / 2.0
    mnr = float(minor_tick) if minor_tick is not None else auto_mnr

    lo_locked = explicit_xlim[0] if (explicit_xlim and len(explicit_xlim) == 2) else None
    hi_locked = explicit_xlim[1] if (explicit_xlim and len(explicit_xlim) == 2) else None

    if lo_locked is not None:
        x_lo = float(lo_locked)
    else:
        near_lo = round(t_min / maj) * maj
        prev_lo = math.floor(t_min / maj) * maj
        if 0.0 <= t_min <= 0.18 * maj:
            x_lo = 0.0
        elif abs(t_min - near_lo) <= 0.12 * maj:
            x_lo = near_lo - 0.20 * maj
        elif 0.08 * maj <= (t_min - prev_lo) <= 0.40 * maj:
            x_lo = prev_lo
        else:
            x_lo = math.floor((t_min - 0.06 * span) / mnr) * mnr

    if hi_locked is not None:
        x_hi = float(hi_locked)
    else:
        next_hi = math.ceil(t_max / maj) * maj
        gap_hi = next_hi - t_max
        if gap_hi < 0.08 * maj:
            x_hi = next_hi + 0.20 * maj
        elif gap_hi <= 0.45 * maj:
            x_hi = next_hi
        else:
            next_half = math.ceil(t_max / mnr) * mnr
            if (next_half - t_max) >= 0.12 * maj:
                x_hi = next_half
            else:
                x_hi = next_half + 0.20 * maj

    if x_lo >= x_hi:
        x_lo, x_hi = t_min - 0.08 * span, t_max + 0.08 * span
    return (x_lo, x_hi), maj, mnr


def compute_smart_linear_ylim(y_values, explicit_ylim=None, pad_frac: float = 0.12):
    """Compute generous, tick-aligned linear y-axis bounds when not user-locked.

    - Symmetric signed data (e.g. p/n Seebeck crossover around 0) snaps to clean
      symmetric bounds `(-B, +B)` such as `(-400, 400)`.
    - Non-negative data never drops below 0 and snaps to 0 when starting near 0.
    - All unlocked bounds receive ~12% breathing room snapped outward to clean
      half-step intervals so large markers never crowd the frame spines.
    """
    import math
    import numpy as np

    lo_locked = explicit_ylim[0] if (explicit_ylim and len(explicit_ylim) == 2) else None
    hi_locked = explicit_ylim[1] if (explicit_ylim and len(explicit_ylim) == 2) else None
    if lo_locked is not None and hi_locked is not None:
        return (float(lo_locked), float(hi_locked))

    arr = np.asarray(y_values, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return explicit_ylim

    y_min = float(np.min(arr))
    y_max = float(np.max(arr))
    span = y_max - y_min
    if span <= 1e-12:
        return explicit_ylim

    # Symmetric p/n crossover (e.g. Seebeck spanning -315 to +337 uV/K -> -400 to +400)
    if (
        lo_locked is None
        and hi_locked is None
        and y_min < 0.0 < y_max
        and 0.45 <= (abs(y_min) / max(abs(y_max), 1e-30)) <= 2.2
    ):
        max_abs = max(abs(y_min), abs(y_max)) * (1.0 + pad_frac)
        maj = _nice_step((2.0 * max_abs) / 4.2)
        sub = maj / 2.0
        bound = math.ceil((max_abs - 1e-12) / sub) * sub
        return (-bound, bound)

    padded_lo = y_min - pad_frac * span
    padded_hi = y_max + pad_frac * span
    maj = _nice_step((padded_hi - padded_lo) / 4.5)
    sub = maj / 2.0

    if lo_locked is not None:
        y_lo = float(lo_locked)
    elif y_min >= 0.0:
        if y_min <= 0.20 * y_max or padded_lo <= 0.0:
            y_lo = 0.0
        else:
            y_lo = max(0.0, math.floor((padded_lo + 1e-12) / sub) * sub)
    else:
        y_lo = math.floor((padded_lo + 1e-12) / sub) * sub

    if hi_locked is not None:
        y_hi = float(hi_locked)
    elif y_max <= 0.0 and y_min < 0.0:
        if abs(y_max) <= 0.20 * abs(y_min) or padded_hi >= 0.0:
            y_hi = 0.0
        else:
            y_hi = min(0.0, math.ceil((padded_hi - 1e-12) / sub) * sub)
    else:
        y_hi = math.ceil((padded_hi - 1e-12) / sub) * sub

    if y_lo >= y_hi:
        return explicit_ylim
    return (y_lo, y_hi)


def format_temperature_axis(
    ax,
    major_tick=DEFAULT_TEMPERATURE_MAJOR_TICK,
    minor_tick=DEFAULT_TEMPERATURE_MINOR_TICK,
):
    """
    Use fixed publication-style temperature tick spacing.
    """
    if major_tick:
        ax.xaxis.set_major_locator(ticker.MultipleLocator(major_tick))
    if minor_tick:
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(minor_tick))


def parse_aspect_ratio(aspect=DEFAULT_SUBPLOT_ASPECT):
    """
    Return width / height from values like "10:8", "1:1", 1.25, or (10, 8).
    """
    if aspect is None:
        aspect = DEFAULT_SUBPLOT_ASPECT

    if isinstance(aspect, (tuple, list)) and len(aspect) == 2:
        width, height = float(aspect[0]), float(aspect[1])
    else:
        raw = str(aspect).strip().lower().replace("x", ":").replace("/", ":")
        if ":" in raw:
            width_raw, height_raw = raw.split(":", 1)
            width, height = float(width_raw), float(height_raw)
        else:
            width, height = float(raw), 1.0

    if width <= 0 or height <= 0:
        raise ValueError("Aspect ratio values must be positive")

    return width / height


def figure_size_for_subplot_aspect(aspect=DEFAULT_SUBPLOT_ASPECT, ncols=1, nrows=1, subplot_height=DEFAULT_SUBPLOT_HEIGHT):
    ratio = parse_aspect_ratio(aspect)
    return (subplot_height * ratio * ncols, subplot_height * nrows)


def apply_subplot_aspect(ax, aspect=DEFAULT_SUBPLOT_ASPECT):
    """
    Fix the data axes box aspect as height / width.
    """
    ratio = parse_aspect_ratio(aspect)
    if hasattr(ax, "set_box_aspect"):
        ax.set_box_aspect(1 / ratio)


def apply_axis_limits(ax, xlim=None, ylim=None):
    """
    Apply optional axis limits to one matplotlib axis.
    """
    if xlim is not None:
        ax.set_xlim(*xlim)
    if ylim is not None:
        ax.set_ylim(*ylim)


def plot_property_vs_temperature(
    ax,
    processed_data,
    property_key,
    xlabel=r'$T$ (K)',
    show_legend=True,
    show_grid=False,
    tick_labelsize=DEFAULT_TICK_LABEL_SIZE,
    tick_pad=8,
    xlim=None,
    ylim=None,
    show_title=False,
    temperature_major_tick=DEFAULT_TEMPERATURE_MAJOR_TICK,
    temperature_minor_tick=DEFAULT_TEMPERATURE_MINOR_TICK,
    marker_size=None,
    color_set=None,
    yscale='linear',
):
    """
    Plot one TE property versus temperature for all samples.
    """
    data_by_sample = load_processed_csvs(processed_data)
    spec = TE_PLOT_SPECS[property_key]
    colors, markers = get_style_cycles(color_set, len(data_by_sample))

    plotted_any_data = False
    all_t_values = []
    all_y_values = []

    for sample_name, df in data_by_sample.items():
        color = next(colors)
        marker = next(markers)
        column = spec['column']
        if 'Temperature' not in df.columns or column not in df.columns:
            if not spec.get('allow_missing'):
                print(f"⚠️ skip {sample_name} for {property_key}: missing Temperature or {column}")
            continue

        plotted_any_data = True
        t_series = pd.to_numeric(df['Temperature'], errors='coerce')
        y_series = pd.to_numeric(df[column], errors='coerce') * spec['scale']
        valid_mask = t_series.notna() & y_series.notna()
        if valid_mask.any():
            all_t_values.append(t_series[valid_mask].to_numpy(dtype=float))
            all_y_values.append(y_series[valid_mask].to_numpy(dtype=float))
        plot_kwargs = {}
        if marker_size is not None:
            plot_kwargs["markersize"] = marker_size
        ax.plot(
            t_series,
            y_series,
            color=color,
            marker=marker,
            markerfacecolor=color,
            markeredgecolor=color,
            label=sample_name,
            **plot_kwargs,
        )

    if show_title:
        ax.set_title(spec['title'])
    ax.set_xlabel(xlabel)
    ax.set_ylabel(spec['ylabel'])
    format_te_axis(ax, show_grid=show_grid, tick_labelsize=tick_labelsize)

    resolved_xlim = xlim
    resolved_major = temperature_major_tick
    resolved_minor = temperature_minor_tick
    if all_t_values:
        import numpy as np
        auto_maj = None if temperature_major_tick == DEFAULT_TEMPERATURE_MAJOR_TICK else temperature_major_tick
        auto_mnr = None if temperature_minor_tick == DEFAULT_TEMPERATURE_MINOR_TICK else temperature_minor_tick
        resolved_xlim, resolved_major, resolved_minor = compute_smart_temperature_axis(
            np.concatenate(all_t_values),
            explicit_xlim=xlim,
            major_tick=auto_maj,
            minor_tick=auto_mnr,
        )
    format_temperature_axis(ax, major_tick=resolved_major, minor_tick=resolved_minor)

    # Set the scale after house formatting so nonlinear axes keep their native
    # tick locators, and before limits so log bounds use logarithmic rules.
    if yscale != 'linear' or ax.get_yscale() != yscale:
        ax.set_yscale(yscale)

    resolved_ylim = ylim
    if yscale == 'linear' and all_y_values:
        import numpy as np
        resolved_ylim = compute_smart_linear_ylim(np.concatenate(all_y_values), explicit_ylim=ylim)
    apply_axis_limits(ax, xlim=resolved_xlim, ylim=resolved_ylim)

    if not plotted_any_data:
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(True)

    if show_legend and data_by_sample:
        place_legend_inside(
            ax,
            fontsize=DEFAULT_LEGEND_FONT_SIZE,
            frameon=False,
            ylim_locked=axis_limit_locked(ylim),
            xlim_locked=axis_limit_locked(xlim),
        )

    return ax


def save_figure_outputs(fig, save_name, save_dir=DEFAULT_FIGURE_DIR, formats=None, transparent=None):
    """Save a figure and return every actual exported path.

    A command's optional rename context applies once per figure. All exported
    formats share that name. SVG keeps its default transparent background.
    """
    from te_analysis.tools.figure_naming import next_figure_stem

    if formats is None:
        ext = os.path.splitext(save_name)[1].lstrip('.')
        formats = [ext] if ext else ['svg']
    formats = normalize_output_formats(formats)
    base_name = next_figure_stem(os.path.splitext(save_name)[0])
    os.makedirs(save_dir, exist_ok=True)
    saved_paths = []

    for file_format in formats:
        plot_path = os.path.join(save_dir, f"{base_name}.{file_format}")
        format_transparent = file_format == 'svg' if transparent is None else transparent
        fig.savefig(plot_path, dpi=600, bbox_inches='tight', transparent=format_transparent)
        saved_paths.append(plot_path)

    return saved_paths


def save_figure(fig, save_name, save_dir=DEFAULT_FIGURE_DIR, formats=None, transparent=None):
    """Save a figure and return its first exported path (legacy API)."""
    return save_figure_outputs(
        fig, save_name, save_dir=save_dir, formats=formats, transparent=transparent,
    )[0]


def figure_top_below_legend(fig):
    """Return a layout top bound below the figure's top legends."""
    if not fig.legends:
        return 1.0
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bottom = min(
        legend.get_window_extent(renderer).transformed(fig.transFigure.inverted()).y0
        for legend in fig.legends
    )
    padding = (4.0 * DEFAULT_PLOT_SCALE / 72.0) / fig.get_figheight()
    return max(0.0, min(1.0, bottom - padding))


def plot_single_property(
    processed_data,
    property_key,
    save_name=None,
    save_dir=DEFAULT_TE_FIGURE_DIR,
    formats=None,
    figsize=None,
    transparent=None,
    xlim=None,
    ylim=None,
    style_mode='single',
    tick_labelsize=DEFAULT_TICK_LABEL_SIZE,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    legend='none',
    marker_size=DEFAULT_MARKER_SIZE,
    legend_font_size=None,
    legend_columns=None,
    show=False,
    color_set=None,
    yscale='linear',
):
    """
    Make a publication-style single-property plot using the summary style.
    """
    apply_plot_style(mode=style_mode)
    if figsize is None:
        figsize = figure_size_for_subplot_aspect(subplot_aspect, subplot_height=DEFAULT_SUBPLOT_HEIGHT)
    fig, ax = plt.subplots(figsize=figsize)
    plot_property_vs_temperature(
        ax,
        processed_data,
        property_key,
        show_legend=False,
        tick_labelsize=tick_labelsize,
        xlim=xlim,
        ylim=ylim,
        marker_size=marker_size,
        color_set=color_set,
        yscale=yscale,
    )
    apply_subplot_aspect(ax, subplot_aspect)
    handles, labels = ax.get_legend_handles_labels()
    resolved_fs = DEFAULT_LEGEND_FONT_SIZE if legend_font_size is None else float(legend_font_size)
    if legend == 'inside' and handles:
        place_legend_inside(
            ax,
            handles,
            labels,
            ncol=legend_columns,
            fontsize=resolved_fs,
            fontsize_locked=legend_font_size is not None,
            frameon=True,
            fancybox=False,
            shadow=False,
            framealpha=0.95,
            facecolor='white',
            edgecolor='black',
            ylim_locked=axis_limit_locked(ylim),
            xlim_locked=axis_limit_locked(xlim),
        )
        fig.tight_layout()
    elif legend == 'outside' and handles:
        legend_ncol = legend_columns or min(len(labels), 2)
        fig.legend(
            handles,
            labels,
            loc='upper center',
            bbox_to_anchor=(0.5, 0.98),
            ncol=legend_ncol,
            fontsize=resolved_fs,
            frameon=False,
            borderaxespad=0.0,
            handlelength=1.5,
            columnspacing=1.3,
        )
        fig.tight_layout(rect=(0, 0, 1, figure_top_below_legend(fig)))
    else:
        fig.tight_layout()

    if save_name:
        plot_path = save_figure(
            fig,
            save_name,
            save_dir=save_dir,
            formats=formats,
            transparent=transparent,
        )
        if show:
            show_interactive_figures()
        plt.close(fig)
        return plot_path

    if show:
        show_interactive_figures()

    return fig, ax


def plot_combined_figure(
    processed_data,
    save_name='summary.png',
    save_dir=DEFAULT_TE_FIGURE_DIR,
    formats=None,
    xlim=None,
    ylims=None,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    marker_size=DEFAULT_MARKER_SIZE,
    legend_columns=None,
    show=False,
    color_set=None,
    yscale='linear',
):
    """
    Plot the standard 2x3 TE summary figure.

    Parameters
    ----------
    processed_data : list or dict
        Either a list of processed CSV paths, or a sample_name -> dataframe dict.
    save_name : str
        Output filename. Existing callers can keep passing "batch_summary.png".
    save_dir : str
        Output directory.
    formats : list[str], optional
        Example: ["png", "svg"] for quick preview plus editable vector output.
    xlim : tuple[float | None, float | None], optional
        Shared temperature axis limits for every subplot.
    ylims : dict[str, tuple[float | None, float | None]], optional
        Per-property y-axis limits, keyed by TE_PLOT_SPECS property name.
    yscale : str, optional
        Shared y-axis scale: linear (default), log, or symlog.

    Returns
    -------
    str
        Path to the first saved figure.
    """
    apply_plot_style(mode='summary')
    data_by_sample = load_processed_csvs(processed_data)

    fig, axs = plt.subplots(
        2,
        3,
        figsize=figure_size_for_subplot_aspect(
            subplot_aspect,
            ncols=3,
            nrows=2,
            subplot_height=DEFAULT_SUBPLOT_HEIGHT,
        ),
    )
    property_layout = [
        ('seebeck', axs[0, 0]),
        ('conductivity', axs[0, 1]),
        ('power_factor', axs[0, 2]),
        ('thermal_conductivity', axs[1, 0]),
        ('lattice_thermal_conductivity', axs[1, 1]),
        ('zt', axs[1, 2]),
    ]

    for property_key, ax in property_layout:
        plot_property_vs_temperature(
            ax,
            data_by_sample,
            property_key,
            show_legend=False,
            show_grid=False,
            tick_labelsize=DEFAULT_TICK_LABEL_SIZE,
            xlim=xlim,
            ylim=ylims.get(property_key) if ylims else None,
            marker_size=marker_size,
            color_set=color_set,
            yscale=yscale,
        )
        apply_subplot_aspect(ax, subplot_aspect)

    handles, labels = axs[0, 0].get_legend_handles_labels()
    if handles:
        panel_locks = [
            axis_limit_locked(ylims.get(prop_key) if ylims else None)
            for prop_key, _ in property_layout
        ]
        place_shared_legend_inside_panels(
            [ax for _, ax in property_layout],
            handles,
            labels,
            fontsize=DEFAULT_LEGEND_FONT_SIZE,
            ncol=legend_columns,
            frameon=True,
            facecolor='white',
            edgecolor='black',
            framealpha=0.95,
            fancybox=False,
            ylim_locks_by_panel=panel_locks,
        )

    fig.subplots_adjust(
        left=0.085,
        right=0.985,
        bottom=0.105,
        top=min(0.915, figure_top_below_legend(fig)) if fig.legends else 0.96,
        wspace=0.38,
        hspace=0.38,
    )
    plot_path = save_figure(fig, save_name, save_dir=save_dir, formats=formats)
    if show:
        show_interactive_figures()
    plt.close(fig)

    return plot_path


plot_comprehensive_figure = plot_combined_figure

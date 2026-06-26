import os
from pathlib import Path
from itertools import cycle
from math import gcd

from src.tools.matplotlib_backend import configure_matplotlib_backend, show_interactive_figures

configure_matplotlib_backend()

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import ticker

try:
    from myplotstyle import axis_formatting, mpl_arial
except ImportError:
    axis_formatting = None
    mpl_arial = None


DEFAULT_COLORS = [
    '#d62728',
    '#1f77b4',
    '#2ca02c',
    '#9467bd',
    '#ff7f0e',
    '#8c564b',
    '#e377c2',
    '#7f7f7f',
    '#17becf',
    '#bcbd22',
    '#000000',
    '#393b79',
    '#637939',
    '#8c6d31',
    '#843c39',
    '#7b4173',
    '#3182bd',
    '#31a354',
    '#756bb1',
    '#e6550d',
    '#9c9ede',
    '#8ca252',
    '#bd9e39',
    '#ad494a',
]

DEFAULT_MARKERS = ['o', 's', 'D', '^', 'v', '<', '>', '*', 'p', 'P', 'X', 'h', 'H', '8', 'd']

PAPER_MAJOR_TICK_LENGTH = 4.0
PAPER_MINOR_TICK_LENGTH = 2.2
DEFAULT_TEMPERATURE_MAJOR_TICK = 100
DEFAULT_TEMPERATURE_MINOR_TICK = 50
DEFAULT_SUBPLOT_ASPECT = "10:8"
DEFAULT_SUBPLOT_HEIGHT = 2.65
DEFAULT_FIGURE_DIR = "figures"
DEFAULT_TE_FIGURE_DIR = "data/processed/figures"
DEFAULT_MARKER_SIZE = 5.0
DEFAULT_LEGEND_FONT_SIZE = 7.5

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
        'ylabel': r'$PF$ ($\mu$W cm$^{-1}$ K$^{-2}$)',
    },
}


def apply_plot_style(font='arial', mode='single'):
    """
    Apply one standard plot style for this project.

    The values mirror the old myplotstyle settings, but this function makes the
    style choice explicit instead of relying on hidden import side effects.
    """
    font_name = 'Arial' if font == 'arial' else 'Times New Roman'
    math_fontset = 'custom' if font == 'arial' else 'stix'

    if mode == 'summary':
        font_size = 10
        title_size = 10
        label_size = 11
        marker_size = DEFAULT_MARKER_SIZE
        line_width = 1.15
    else:
        font_size = 11
        title_size = 11
        label_size = 12
        marker_size = DEFAULT_MARKER_SIZE
        line_width = 1.15

    plt.rcParams.update({
        'font.sans-serif': font_name,
        'mathtext.fontset': math_fontset,
        'lines.linewidth': line_width,
        'lines.markersize': marker_size,
        'axes.linewidth': 0.9,
        'axes.labelpad': 2,
        'axes.titlesize': title_size,
        'axes.labelsize': label_size,
        'xtick.direction': 'in',
        'xtick.major.width': 1,
        'xtick.minor.width': 1,
        'xtick.major.size': PAPER_MAJOR_TICK_LENGTH,
        'xtick.minor.size': PAPER_MINOR_TICK_LENGTH,
        'ytick.direction': 'in',
        'ytick.major.width': 1,
        'ytick.minor.width': 1,
        'ytick.major.size': PAPER_MAJOR_TICK_LENGTH,
        'ytick.minor.size': PAPER_MINOR_TICK_LENGTH,
        'xtick.minor.visible': True,
        'ytick.minor.visible': True,
        'font.size': font_size,
        'font.weight': 'normal',
        'legend.frameon': False,
        'savefig.dpi': 600,
        'savefig.bbox': 'tight',
    })


def get_style_cycles():
    """
    Return project color and marker cycles.

    The color and marker sequences advance together for easy visual scanning,
    but the marker sequence is offset after each full color pass. This keeps
    marker variation in the first palette cycle and delays repeated color-marker
    pairs for large multi-sample plots.
    """
    if mpl_arial:
        colors = getattr(mpl_arial, 'color_list_main', DEFAULT_COLORS)
        markers = getattr(mpl_arial, 'marker_list_main', DEFAULT_MARKERS)
    else:
        colors = DEFAULT_COLORS
        markers = DEFAULT_MARKERS

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


def normalize_output_formats(formats=None, pdf=False, default=('png',)):
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


def format_te_axis(ax, show_grid=False, tick_labelsize=11):
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

    ax.tick_params(which='both', pad=3)
    ax.tick_params(which='major', length=PAPER_MAJOR_TICK_LENGTH)
    ax.tick_params(which='minor', length=PAPER_MINOR_TICK_LENGTH)
    ax.xaxis.labelpad = 2
    ax.yaxis.labelpad = 2
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)


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
    tick_labelsize=11,
    tick_pad=8,
    xlim=None,
    ylim=None,
    show_title=False,
    temperature_major_tick=DEFAULT_TEMPERATURE_MAJOR_TICK,
    temperature_minor_tick=DEFAULT_TEMPERATURE_MINOR_TICK,
    marker_size=None,
):
    """
    Plot one TE property versus temperature for all samples.
    """
    data_by_sample = load_processed_csvs(processed_data)
    spec = TE_PLOT_SPECS[property_key]
    colors, markers = get_style_cycles()

    plotted_any_data = False

    for sample_name, df in data_by_sample.items():
        column = spec['column']
        if 'Temperature' not in df.columns or column not in df.columns:
            if not spec.get('allow_missing'):
                print(f"⚠️ skip {sample_name} for {property_key}: missing Temperature or {column}")
            continue

        plotted_any_data = True
        color = next(colors)
        marker = next(markers)
        plot_kwargs = {}
        if marker_size is not None:
            plot_kwargs["markersize"] = marker_size
        ax.plot(
            df['Temperature'],
            df[column] * spec['scale'],
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
    format_temperature_axis(ax, major_tick=temperature_major_tick, minor_tick=temperature_minor_tick)
    apply_axis_limits(ax, xlim=xlim, ylim=ylim)

    if not plotted_any_data:
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(True)

    if show_legend and data_by_sample:
        ax.legend(fontsize=10, loc='best')

    return ax


def save_figure(fig, save_name, save_dir=DEFAULT_FIGURE_DIR, formats=None, transparent=None):
    """
    Save a figure and return the first saved path.

    SVG outputs default to a transparent background so they drop cleanly into
    slides and vector editors. Other formats keep Matplotlib's normal opaque
    background unless a caller explicitly passes transparent=True.
    """
    os.makedirs(save_dir, exist_ok=True)

    if formats is None:
        ext = os.path.splitext(save_name)[1].lstrip('.')
        formats = [ext] if ext else ['png']
    formats = normalize_output_formats(formats)

    base_name = os.path.splitext(save_name)[0]
    saved_paths = []

    for file_format in formats:
        plot_path = os.path.join(save_dir, f"{base_name}.{file_format}")
        format_transparent = file_format == 'svg' if transparent is None else transparent
        fig.savefig(plot_path, dpi=600, bbox_inches='tight', transparent=format_transparent)
        saved_paths.append(plot_path)

    return saved_paths[0]


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
    tick_labelsize=10,
    subplot_aspect=DEFAULT_SUBPLOT_ASPECT,
    legend='none',
    marker_size=DEFAULT_MARKER_SIZE,
    legend_font_size=DEFAULT_LEGEND_FONT_SIZE,
    legend_columns=None,
    show=False,
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
    )
    apply_subplot_aspect(ax, subplot_aspect)
    handles, labels = ax.get_legend_handles_labels()
    if legend == 'inside' and handles:
        legend_ncol = legend_columns or 1
        ax.legend(
            handles,
            labels,
            loc='best',
            ncol=legend_ncol,
            fontsize=legend_font_size,
            frameon=True,
            fancybox=False,
            shadow=True,
            framealpha=1.0,
            facecolor='white',
            edgecolor='black',
            borderpad=0.35,
            handlelength=1.5,
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
            fontsize=legend_font_size,
            frameon=False,
            borderaxespad=0.0,
            handlelength=1.5,
            columnspacing=1.3,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.90))
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
            tick_labelsize=9,
            xlim=xlim,
            ylim=ylims.get(property_key) if ylims else None,
            marker_size=marker_size,
        )
        apply_subplot_aspect(ax, subplot_aspect)

    handles, labels = axs[0, 0].get_legend_handles_labels()
    if handles:
        legend_ncol = legend_columns or min(len(labels), 4)
        fig.legend(
            handles,
            labels,
            loc='upper center',
            bbox_to_anchor=(0.5, 0.965),
            ncol=legend_ncol,
            fontsize=10,
            frameon=False,
            borderaxespad=0.0,
            handlelength=1.5,
            columnspacing=1.3,
        )

    fig.subplots_adjust(
        left=0.075,
        right=0.985,
        bottom=0.095,
        top=0.915 if handles else 0.96,
        wspace=0.34,
        hspace=0.36,
    )
    plot_path = save_figure(fig, save_name, save_dir=save_dir, formats=formats)
    if show:
        show_interactive_figures()
    plt.close(fig)

    return plot_path


plot_comprehensive_figure = plot_combined_figure

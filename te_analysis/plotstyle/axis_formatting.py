from matplotlib import ticker
import numpy as np

def format_axes(*axes,
                minor_ticks=True,
                grid=False,
                x_major=None, y_major=None,
                tick_direction='in',
                major_width=1, minor_width=1,
                major_size=6, minor_size=4,
                labelpad=8, tick_pad=8,
                tick_labelsize=12  # 
):
    for ax in axes:
        ax.tick_params(which='both', top=False, right=False, direction=tick_direction, pad=tick_pad)
        ax.tick_params(which='major', width=major_width, length=major_size)
        ax.tick_params(which='minor', width=minor_width, length=minor_size)
        ax.tick_params(labelsize=tick_labelsize)  # 

        if x_major:
            ax.xaxis.set_major_locator(ticker.MultipleLocator(x_major))
        if y_major:
            ax.yaxis.set_major_locator(ticker.MultipleLocator(y_major))

        if minor_ticks:
            if ax.get_xscale() == 'log':
                ax.xaxis.set_minor_locator(ticker.LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1, numticks=10))
            else:
                ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(2))

            if ax.get_yscale() == 'log':
                ax.yaxis.set_minor_locator(ticker.LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1, numticks=10))
            else:
                ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(2))

        ax.xaxis.labelpad = labelpad
        ax.yaxis.labelpad = labelpad

        if grid:
            ax.grid(True, which='major', linestyle='--', linewidth=0.5, alpha=0.5)

def format_legend(*axes, loc='best', fontsize=10, fancybox=False, edgecolor='black', shadow=True, ncol=1):
    for ax in axes:
        ax.legend(loc=loc,
                  fontsize=fontsize,
                  fancybox=fancybox,
                  edgecolor=edgecolor,
                  shadow=shadow,
                  ncol=ncol)
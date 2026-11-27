"""Shared categorical palettes and count-aware sequential palettes.

Sequential colors run dark to light in input order, never performance order.
See docs/COLOR_SETS.md for swatches, provenance, and CLI examples.
"""

from itertools import cycle, islice

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, to_hex, to_rgb

DEFAULT_COLOR_SET = "science"
DEFAULT_FIELD_CMAP = "soft-br"

CUSTOM_CMAP_STOPS = {
    "soft-rb": (
        "#F4978E",
        "#F9BFB5",
        "#FBE4DF",
        "#F6F7FA",
        "#DCECF8",
        "#A9D0EE",
        "#72A8D8",
    ),
    "soft-br": (
        "#72A8D8",
        "#A9D0EE",
        "#DCECF8",
        "#F6F7FA",
        "#FBE4DF",
        "#F9BFB5",
        "#F4978E",
    ),
    "soft-blue": (
        "#EEF5FB",
        "#CFE3F5",
        "#9EC5E8",
        "#6BA3D6",
        "#3F7BB6",
    ),
    "soft-red": (
        "#FDF0EE",
        "#FAD2CC",
        "#F5ACA3",
        "#EA8277",
        "#D45B52",
    ),
}


def resolve_cmap(cmap=None):
    """Resolve custom soft colormaps (default 'soft-br': light blue -> light red) or Matplotlib colormaps."""
    if cmap is None or cmap == "":
        name = DEFAULT_FIELD_CMAP
    elif isinstance(cmap, str):
        name = cmap.strip()
    else:
        return cmap

    key = name.lower().replace("_", "-")
    if key in CUSTOM_CMAP_STOPS:
        return LinearSegmentedColormap.from_list(key, CUSTOM_CMAP_STOPS[key], N=256)
    return plt.get_cmap(name)

COLOR_SETS = {
    "npg": ("#3C5488", "#E64B35", "#00A087", "#4DBBD5", "#7E6148", "#8491B4", "#B24773", "#D99B32"),
    "science": ("#3B4992", "#D43F3A", "#008B78", "#8F6BB0", "#E59F23", "#4C8DCB", "#B85B86", "#333333"),
    "classic": ("#343434", "#C6283D", "#3478BF", "#67A64B", "#9565A8", "#DC8C32", "#36A5AA", "#A97155"),
    "blue-orange": ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#333333", "#7A7A7A"),
    "blue": ("#173B65", "#245582", "#356E9B", "#4A84AE", "#6398BD"),
    "teal": ("#124E46", "#17685C", "#24816F", "#389582", "#55A492"),
    "purple": ("#492662", "#63417D", "#7A5894", "#906FAB", "#A184BA"),
    "orange": ("#76370D", "#914A13", "#AA601E", "#BB762D", "#C48C45"),
    "red": ("#741F35", "#93334A", "#AB4C60", "#BE6675", "#CA7D85"),
    "gray": ("#292F38", "#424A55", "#5B6572", "#737E8B", "#8B96A2"),
    "legacy": (
        "#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b",
        "#e377c2", "#7f7f7f", "#17becf", "#bcbd22", "#000000", "#393b79",
        "#637939", "#8c6d31", "#843c39", "#7b4173", "#3182bd", "#31a354",
        "#756bb1", "#e6550d", "#9c9ede", "#8ca252", "#bd9e39", "#ad494a",
    ),
}
SEQUENTIAL_COLOR_SETS = frozenset(("blue", "teal", "purple", "orange", "red", "gray"))


def get_colors(color_set=None, count=None):
    """Return a fresh palette, optionally sized to exactly ``count`` series.

    Categorical palettes cycle. Sequential palettes interpolate their anchors
    across the full range; a single series uses the darkest anchor. No alpha
    fading is used, so colors remain consistent on exported backgrounds.
    """
    name = DEFAULT_COLOR_SET if color_set is None else color_set
    if name not in COLOR_SETS:
        raise ValueError(f"Unknown color set {name!r}. Choose from: {', '.join(COLOR_SETS)}")
    anchors = COLOR_SETS[name]
    if count is None:
        return list(anchors)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("Color count must be a non-negative integer")
    if count <= 1 or name not in SEQUENTIAL_COLOR_SETS:
        return list(islice(cycle(anchors), count))
    colors = []
    for index in range(count):
        position = index * (len(anchors) - 1) / (count - 1)
        low = int(position)
        high = min(low + 1, len(anchors) - 1)
        fraction = position - low
        rgb = tuple(a + fraction * (b - a) for a, b in zip(to_rgb(anchors[low]), to_rgb(anchors[high])))
        colors.append(to_hex(rgb))
    return colors


def add_color_set_argument(parser, *, default=DEFAULT_COLOR_SET):
    """Use one CLI contract across plotting commands."""
    parser.add_argument(
        "--color-set", choices=tuple(COLOR_SETS), default=default,
        help="Whole-plot palette (default: science). Blue/teal/purple/orange/red/gray "
             "are dark-to-light gradients sized to the selected samples; legacy restores the old 24 colors.",
    )

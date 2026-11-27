"""Smart inside-axes legend placement engine.

Keeps legends inside the plot axes whenever possible by jointly evaluating:
1. Candidate inside-axes positions (corners and edge centers),
2. Multi-column compact layouts (`ncol`) and stepped font-size reduction, and
3. Minimal axis-limit headroom expansion (`ylim` / optional `xlim`) computed
   analytically in scale space (linear, log, or symlog) while respecting
   user-locked bounds and non-negative physical floors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import matplotlib.pyplot as plt
from matplotlib import patches as mpatches
from matplotlib import ticker
from matplotlib.collections import LineCollection, PathCollection, PolyCollection
from matplotlib.legend import Legend
import numpy as np


STANDARD_INSIDE_LOCS: tuple[str, ...] = (
    "upper right",
    "upper left",
    "lower right",
    "lower left",
    "upper center",
    "lower center",
    "center right",
    "center left",
)

_LOC_CODE_TO_NAME: dict[int, str] = {
    0: "best",
    1: "upper right",
    2: "upper left",
    3: "lower left",
    4: "lower right",
    5: "center right",
    6: "center left",
    7: "center right",
    8: "lower center",
    9: "upper center",
    10: "center",
}


def normalize_loc_name(loc: Any) -> str:
    if loc is None:
        return "best"
    if isinstance(loc, int):
        return _LOC_CODE_TO_NAME.get(loc, "best")
    text = str(loc).strip().lower()
    if text == "right":
        return "center right"
    return text or "best"


def axis_limit_locked(limit_pair: Any) -> tuple[bool, bool]:
    """Return `(low_locked, high_locked)` from an optional `(low, high)` limit tuple."""
    if limit_pair is None:
        return (False, False)
    if isinstance(limit_pair, (tuple, list)) and len(limit_pair) == 2:
        return (limit_pair[0] is not None, limit_pair[1] is not None)
    return (False, False)


@dataclass
class _AxisObstacles:
    ax: plt.Axes
    sx_lo: float
    sx_hi: float
    sy_lo: float
    sy_hi: float
    data_y_min: float | None
    data_y_max: float | None
    # Scale-space points: (N,) arrays
    sx: np.ndarray
    sy: np.ndarray
    rx: np.ndarray
    ry: np.ndarray
    weights: np.ndarray
    # Reference-guide points where one coordinate is fixed in Axes [0, 1] space
    hline_sy: np.ndarray
    vline_sx: np.ndarray


def _safe_scale_vals(axis_obj: Any, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(values, dtype=float)
    valid = np.isfinite(arr)
    if axis_obj.get_scale() == "log":
        valid &= arr > 0.0
    if not np.any(valid):
        return np.empty(0, dtype=float), valid
    transformed = np.asarray(axis_obj.get_transform().transform(arr[valid]), dtype=float)
    ok_t = np.isfinite(transformed)
    if not np.all(ok_t):
        idx = np.flatnonzero(valid)
        valid[idx[~ok_t]] = False
        transformed = transformed[ok_t]
    return transformed, valid


def _transform_xy(ax: plt.Axes, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x_arr = np.asarray(x, dtype=float).ravel()
    y_arr = np.asarray(y, dtype=float).ravel()
    valid = np.isfinite(x_arr) & np.isfinite(y_arr)
    if ax.get_xscale() == "log":
        valid &= x_arr > 0.0
    if ax.get_yscale() == "log":
        valid &= y_arr > 0.0
    if not np.any(valid):
        empty = np.empty(0, dtype=float)
        return empty, empty, empty, empty
    xv = x_arr[valid]
    yv = y_arr[valid]
    sx = np.asarray(ax.xaxis.get_transform().transform(xv), dtype=float)
    sy = np.asarray(ax.yaxis.get_transform().transform(yv), dtype=float)
    ok = np.isfinite(sx) & np.isfinite(sy)
    return sx[ok], sy[ok], xv[ok], yv[ok]


def _extract_obstacles(
    primary_ax: plt.Axes,
    axes_list: Sequence[plt.Axes],
    renderer: Any,
) -> tuple[list[_AxisObstacles], list[tuple[float, float, float, float, float]]]:
    fig = primary_ax.figure
    ax_win = primary_ax.get_window_extent(renderer)
    w_px = max(float(ax_win.width), 40.0)
    h_px = max(float(ax_win.height), 40.0)
    dpi = float(fig.dpi or 100.0)
    inv_primary_axes = primary_ax.transAxes.inverted()

    fixed_boxes: list[tuple[float, float, float, float, float]] = []
    for ins in getattr(primary_ax, "child_axes", ()):
        if not ins.get_visible():
            continue
        ib = ins.get_window_extent(renderer).transformed(inv_primary_axes)
        if ib.x1 > 0.01 and ib.x0 < 0.99 and ib.y1 > 0.01 and ib.y0 < 0.99:
            fixed_boxes.append((float(ib.x0), float(ib.y0), float(ib.x1), float(ib.y1), 5.0))

    per_axis: list[_AxisObstacles] = []
    for a in axes_list:
        x_lo, x_hi = a.get_xlim()
        y_lo, y_hi = a.get_ylim()
        sx_bounds = np.asarray(a.xaxis.get_transform().transform([x_lo, x_hi]), dtype=float)
        sy_bounds = np.asarray(a.yaxis.get_transform().transform([y_lo, y_hi]), dtype=float)
        sx_lo, sx_hi = float(sx_bounds[0]), float(sx_bounds[1])
        sy_lo, sy_hi = float(sy_bounds[0]), float(sy_bounds[1])
        if math.isclose(sx_lo, sx_hi):
            sx_hi = sx_lo + 1.0
        if math.isclose(sy_lo, sy_hi):
            sy_hi = sy_lo + 1.0

        sx_parts: list[np.ndarray] = []
        sy_parts: list[np.ndarray] = []
        rx_parts: list[np.ndarray] = []
        ry_parts: list[np.ndarray] = []
        w_parts: list[np.ndarray] = []
        raw_y_vals: list[np.ndarray] = []
        hlines_sy: list[float] = []
        vlines_sx: list[float] = []

        def _append_pts(sx_v: np.ndarray, sy_v: np.ndarray, r_px: float, weight: float, y_raw: np.ndarray | None = None) -> None:
            if sx_v.size == 0:
                return
            sx_parts.append(sx_v)
            sy_parts.append(sy_v)
            rx_parts.append(np.full(sx_v.shape, r_px / w_px, dtype=float))
            ry_parts.append(np.full(sy_v.shape, r_px / h_px, dtype=float))
            w_parts.append(np.full(sx_v.shape, weight, dtype=float))
            if y_raw is not None and y_raw.size:
                raw_y_vals.append(y_raw)

        # 1. Lines
        for line in a.lines:
            if not line.get_visible():
                continue
            tr = line.get_transform()
            xd = np.asarray(line.get_xdata(orig=False), dtype=float)
            yd = np.asarray(line.get_ydata(orig=False), dtype=float)
            if tr == a.transData:
                sx_v, sy_v, _, yv = _transform_xy(a, xd, yd)
                if sx_v.size == 0:
                    continue
                has_marker = line.get_marker() not in (None, "None", "none", "", " ")
                ms_pts = float(line.get_markersize() or 4.0) if has_marker else 2.0
                r_px = 0.55 * ms_pts * dpi / 72.0
                _append_pts(sx_v, sy_v, r_px, 1.0, yv)

                has_stroke = line.get_linestyle() not in (None, "None", "none", "", " ")
                if has_stroke and sx_v.size >= 2:
                    n_seg = sx_v.size - 1
                    per_seg = max(1, min(6, int(math.ceil(64.0 / n_seg))))
                    if per_seg > 1 or sx_v.size <= 40:
                        ts = np.linspace(0.0, 1.0, per_seg + 2)[1:-1]
                        if ts.size:
                            seg_x = (sx_v[:-1, None] * (1.0 - ts[None, :]) + sx_v[1:, None] * ts[None, :]).ravel()
                            seg_y = (sy_v[:-1, None] * (1.0 - ts[None, :]) + sy_v[1:, None] * ts[None, :]).ravel()
                            lw_px = 0.5 * float(line.get_linewidth() or 1.5) * dpi / 72.0
                            _append_pts(seg_x, seg_y, lw_px, 0.85)
            elif tr == a.get_yaxis_transform() and yd.size:
                sy_h, _ = _safe_scale_vals(a.yaxis, yd[:1])
                if sy_h.size:
                    hlines_sy.append(float(sy_h[0]))
            elif tr == a.get_xaxis_transform() and xd.size:
                sx_h, _ = _safe_scale_vals(a.xaxis, xd[:1])
                if sx_h.size:
                    vlines_sx.append(float(sx_h[0]))

        # 2. Collections (scatter, vlines/errorbar, fill_between/stackplot/violin)
        for coll in a.collections:
            if not coll.get_visible():
                continue
            alpha_raw = coll.get_alpha()
            alpha_val = 1.0 if alpha_raw is None else (float(np.mean(alpha_raw)) if np.ndim(alpha_raw) else float(alpha_raw))

            if isinstance(coll, PathCollection):
                offsets = np.asarray(coll.get_offsets(), dtype=float)
                if offsets.ndim == 2 and offsets.shape[0] > 0 and coll.get_offset_transform() == a.transData:
                    sx_v, sy_v, _, yv = _transform_xy(a, offsets[:, 0], offsets[:, 1])
                    if sx_v.size:
                        sizes = np.asarray(coll.get_sizes(), dtype=float)
                        mean_s = float(np.nanmedian(sizes)) if sizes.size else 36.0
                        r_px = 0.58 * math.sqrt(max(mean_s, 4.0)) * dpi / 72.0
                        _append_pts(sx_v, sy_v, r_px, 1.15, yv)
            elif isinstance(coll, LineCollection) and coll.get_transform() == a.transData:
                segs = coll.get_segments()
                if segs:
                    pts_list = []
                    for seg in segs:
                        if len(seg) >= 2:
                            pts_list.append(seg[0])
                            pts_list.append(0.5 * (seg[0] + seg[-1]))
                            pts_list.append(seg[-1])
                    if pts_list:
                        arr = np.asarray(pts_list, dtype=float)
                        sx_v, sy_v, _, yv = _transform_xy(a, arr[:, 0], arr[:, 1])
                        _append_pts(sx_v, sy_v, 2.0, 0.85, yv)
            elif isinstance(coll, PolyCollection) and coll.get_transform() == a.transData:
                poly_w = 0.16 if alpha_val <= 0.28 else 0.95
                for path in coll.get_paths():
                    verts = path.vertices
                    if verts is None or len(verts) < 3:
                        continue
                    stride = max(1, len(verts) // 80)
                    sub = verts[::stride]
                    sx_v, sy_v, _, yv = _transform_xy(a, sub[:, 0], sub[:, 1])
                    _append_pts(sx_v, sy_v, 1.5, poly_w, yv if poly_w > 0.3 else None)
                    if poly_w > 0.3 and sx_v.size >= 6:
                        half = sx_v.size // 2
                        mid_x = 0.5 * (sx_v[:half] + sx_v[-1 : -1 - half : -1])
                        mid_y = 0.5 * (sy_v[:half] + sy_v[-1 : -1 - half : -1])
                        _append_pts(mid_x, mid_y, 1.5, poly_w * 0.85)

        # 3. Patches (bars, histograms, boxplots)
        for patch in a.patches:
            if patch is a.patch or not patch.get_visible():
                continue
            alpha_p = patch.get_alpha()
            w_patch = 0.16 if (alpha_p is not None and float(alpha_p) <= 0.28) else 1.1
            data_tr = patch.get_data_transform() if hasattr(patch, "get_data_transform") else patch.get_transform()
            if isinstance(patch, mpatches.Rectangle) and data_tr == a.transData:
                x0, y0 = float(patch.get_x()), float(patch.get_y())
                x1 = x0 + float(patch.get_width())
                y1 = y0 + float(patch.get_height())
                if not (math.isfinite(x0) and math.isfinite(x1) and math.isfinite(y0) and math.isfinite(y1)):
                    continue
                gx = np.linspace(min(x0, x1), max(x0, x1), 7)
                gy = np.linspace(min(y0, y1), max(y0, y1), 9)
                xx, yy = np.meshgrid(gx, gy)
                sx_v, sy_v, _, yv = _transform_xy(a, xx.ravel(), yy.ravel())
                _append_pts(sx_v, sy_v, 2.0, w_patch, yv if w_patch > 0.3 else None)

        # 4. Texts and annotations
        for txt in a.texts:
            if not txt.get_visible() or not str(txt.get_text()).strip():
                continue
            wb = txt.get_window_extent(renderer)
            if wb.width <= 0.5 or wb.height <= 0.5:
                continue
            ab = wb.transformed(inv_primary_axes)
            if ab.x1 <= 0.01 or ab.x0 >= 0.99 or ab.y1 <= 0.01 or ab.y0 >= 0.99:
                continue
            tr = txt.get_transform()
            if tr == a.transAxes or tr == primary_ax.transAxes:
                fixed_boxes.append(
                    (
                        max(0.0, float(ab.x0)),
                        max(0.0, float(ab.y0)),
                        min(1.0, float(ab.x1)),
                        min(1.0, float(ab.y1)),
                        3.0,
                    )
                )
            else:
                # Data-anchored label: convert current Axes box corners into scale coordinates so it shifts with ylim
                ab_local = wb.transformed(a.transAxes.inverted())
                ux_pts = np.array([ab_local.x0, ab_local.x1, ab_local.x0, ab_local.x1, 0.5 * (ab_local.x0 + ab_local.x1)])
                uy_pts = np.array([ab_local.y0, ab_local.y0, ab_local.y1, ab_local.y1, 0.5 * (ab_local.y0 + ab_local.y1)])
                sx_t = sx_lo + ux_pts * (sx_hi - sx_lo)
                sy_t = sy_lo + uy_pts * (sy_hi - sy_lo)
                _append_pts(sx_t, sy_t, 2.5, 2.2)

        if sx_parts:
            sx_all = np.concatenate(sx_parts)
            sy_all = np.concatenate(sy_parts)
            rx_all = np.concatenate(rx_parts)
            ry_all = np.concatenate(ry_parts)
            w_all = np.concatenate(w_parts)
        else:
            sx_all = sy_all = rx_all = ry_all = w_all = np.empty(0, dtype=float)

        if raw_y_vals:
            y_concat = np.concatenate(raw_y_vals)
            data_y_min = float(np.nanmin(y_concat))
            data_y_max = float(np.nanmax(y_concat))
        else:
            data_y_min = data_y_max = None

        per_axis.append(
            _AxisObstacles(
                ax=a,
                sx_lo=sx_lo,
                sx_hi=sx_hi,
                sy_lo=sy_lo,
                sy_hi=sy_hi,
                data_y_min=data_y_min,
                data_y_max=data_y_max,
                sx=sx_all,
                sy=sy_all,
                rx=rx_all,
                ry=ry_all,
                weights=w_all,
                hline_sy=np.asarray(hlines_sy, dtype=float),
                vline_sx=np.asarray(vlines_sx, dtype=float),
            )
        )

    return per_axis, fixed_boxes


def _loc_rect(loc_name: str, w_ax: float, h_ax: float, pad_x: float = 0.022, pad_y: float = 0.024) -> tuple[float, float, float, float]:
    if "left" in loc_name:
        x0 = pad_x
    elif "right" in loc_name:
        x0 = 1.0 - pad_x - w_ax
    else:
        x0 = 0.5 * (1.0 - w_ax)
    x1 = x0 + w_ax

    if "upper" in loc_name:
        y1 = 1.0 - pad_y
        y0 = y1 - h_ax
    elif "lower" in loc_name:
        y0 = pad_y
        y1 = y0 + h_ax
    else:
        y0 = 0.5 * (1.0 - h_ax)
        y1 = y0 + h_ax
    return (x0, y0, x1, y1)


def _apply_expanded_sy_bounds(obs: _AxisObstacles, expand_bot: float, expand_top: float, lock: tuple[bool, bool]) -> tuple[float, float]:
    sy_lo, sy_hi = obs.sy_lo, obs.sy_hi
    span = sy_hi - sy_lo
    inverted = span < 0.0
    abs_span = abs(span)
    sgn = -1.0 if inverted else 1.0

    new_lo = sy_lo - sgn * (0.0 if lock[0] else expand_bot) * abs_span
    new_hi = sy_hi + sgn * (0.0 if lock[1] else expand_top) * abs_span

    # Do not push a non-negative linear axis below zero (or a non-positive axis above zero).
    if obs.ax.get_yscale() == "linear" and not inverted:
        if not lock[0] and expand_bot > 0.0 and obs.data_y_min is not None and obs.data_y_min >= -1e-12 and sy_lo >= -1e-12:
            new_lo = max(0.0, new_lo)
        if not lock[1] and expand_top > 0.0 and obs.data_y_max is not None and obs.data_y_max <= 1e-12 and sy_hi <= 1e-12:
            new_hi = min(0.0, new_hi)
    return new_lo, new_hi


def _compact_spacing_kwargs(scale_ratio: float, explicit_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Scale internal legend padding harmoniously when font size is reduced."""
    r = max(0.62, min(1.0, float(scale_ratio)))
    defaults = {
        "borderpad": round(0.34 * r, 3),
        "labelspacing": round(0.42 * r, 3),
        "handlelength": round(1.45 * (0.82 + 0.18 * r), 3),
        "handletextpad": round(0.50 * r, 3),
        "columnspacing": round(1.05 * r, 3),
        "borderaxespad": round(0.42 * r, 3),
    }
    for k, v in explicit_kwargs.items():
        if v is not None:
            defaults[k] = v
    return defaults


def _font_ladder(base_fs: float, min_fs: float, *, locked: bool, n_items: int) -> list[float]:
    floor = min(min_fs, 6.8 if n_items >= 8 else min_fs)
    floor = min(floor, base_fs)
    if locked:
        # Respect explicit user font size first; only include gentle fallbacks for physical overflow/locked-axis rescue.
        cands = [base_fs, max(floor, round(base_fs * 0.86, 2)), floor]
    else:
        ratios = (1.0, 0.90, 0.80, 0.72, 0.64, 0.56)
        cands = [max(floor, round(base_fs * r, 2)) for r in ratios]
    out: list[float] = []
    for val in cands:
        if all(abs(val - prev) > 0.25 for prev in out):
            out.append(val)
    return out


def _ncol_ladder(n_items: int, explicit_ncol: int | None, max_label_len: int) -> list[int]:
    if n_items <= 1:
        return [1]
    if explicit_ncol is not None:
        base = max(1, min(int(explicit_ncol), n_items))
        extra = min(n_items, base + 1)
        return [base] if extra == base else [base, extra]

    if n_items <= 3:
        cands = [1, n_items] if max_label_len <= 28 else [1, 2]
    elif n_items <= 6:
        cands = [1, 2, 3] if max_label_len <= 20 else [1, 2]
    else:
        cands = [2, 3, 1, min(n_items, 4)] if max_label_len <= 18 else [2, 1, 3]

    out: list[int] = []
    for c in cands:
        c_clamped = max(1, min(c, n_items))
        if c_clamped not in out:
            out.append(c_clamped)
    return out


def _place_polar_legend_inside(
    ax: plt.Axes,
    handles: Sequence[Any],
    labels: Sequence[str],
    *,
    fontsize: float,
    min_fontsize: float,
    ncol: int | None,
    title: str | None,
    style_kwargs: dict[str, Any],
    frame_linewidth: float | None,
) -> Legend:
    """Place a compact legend in the cleanest corner of a polar radar Axes bounding box."""
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    inv_ax = ax.transAxes.inverted()
    ax_win = ax.get_window_extent(renderer)
    w_px = max(float(ax_win.width), 40.0)
    h_px = max(float(ax_win.height), 40.0)

    spoke_boxes: list[tuple[float, float, float, float]] = []
    for tick_lbl in ax.get_xticklabels():
        if tick_lbl.get_visible() and str(tick_lbl.get_text()).strip():
            tb = tick_lbl.get_window_extent(renderer).transformed(inv_ax)
            spoke_boxes.append((float(tb.x0), float(tb.y0), float(tb.x1), float(tb.y1)))

    corners = [
        ("upper right", (1.02, 1.04)),
        ("upper left", (-0.02, 1.04)),
        ("lower right", (1.02, -0.02)),
        ("lower left", (-0.02, -0.02)),
    ]
    fs_start = min(float(fontsize), 10.5)
    fs_cands = _font_ladder(fs_start, min_fontsize, locked=False, n_items=len(labels))
    ncol_cands = [ncol] if ncol is not None else ([1, min(len(labels), 2)] if len(labels) > 1 else [1])

    best_cfg: tuple[float, float, int, str, tuple[float, float]] | None = None
    for fs in fs_cands:
        for nc in ncol_cands:
            spacing = _compact_spacing_kwargs(fs / max(fontsize, 1.0), {})
            probe = ax.legend(
                handles,
                labels,
                loc="upper right",
                ncol=nc,
                fontsize=fs,
                title=title,
                **style_kwargs,
                **spacing,
            )
            if title and probe.get_title().get_text():
                probe.get_title().set_fontsize(fs)
            lb = probe.get_window_extent(renderer)
            probe.remove()
            w_ax = float(lb.width) / w_px
            h_ax = float(lb.height) / h_px

            for loc_name, anchor in corners:
                ax_x0 = anchor[0] - w_ax if "right" in loc_name else anchor[0]
                ax_x1 = ax_x0 + w_ax
                ax_y1 = anchor[1] if "upper" in loc_name else anchor[1] + h_ax
                ax_y0 = ax_y1 - h_ax

                # Distance penalty to polar circle (center 0.5, 0.5, radius 0.5) + spoke label overlap
                cx = min(max(0.5, ax_x0), ax_x1)
                cy = min(max(0.5, ax_y0), ax_y1)
                dist_center = math.hypot(cx - 0.5, cy - 0.5)
                circle_overlap = max(0.0, 0.48 - dist_center)

                spoke_pen = 0.0
                for sx0, sy0, sx1, sy1 in spoke_boxes:
                    ix = max(0.0, min(ax_x1 + 0.01, sx1) - max(ax_x0 - 0.01, sx0))
                    iy = max(0.0, min(ax_y1 + 0.01, sy1) - max(ax_y0 - 0.01, sy0))
                    if ix > 0.0 and iy > 0.0:
                        spoke_pen += 500.0 * (1.0 + 20.0 * ix * iy)

                cost = 800.0 * circle_overlap + spoke_pen + 1.2 * ((fs_start - fs) / max(fs_start, 1.0)) ** 2
                if best_cfg is None or cost < best_cfg[0]:
                    best_cfg = (cost, fs, nc, loc_name, anchor)

    assert best_cfg is not None
    _, best_fs, best_nc, best_loc, best_anchor = best_cfg
    spacing = _compact_spacing_kwargs(best_fs / max(fontsize, 1.0), {})
    leg = ax.legend(
        handles,
        labels,
        loc=best_loc,
        bbox_to_anchor=best_anchor,
        ncol=best_nc,
        fontsize=best_fs,
        title=title,
        **style_kwargs,
        **spacing,
    )
    if title and leg.get_title().get_text():
        leg.get_title().set_fontsize(best_fs)
    if frame_linewidth is not None and style_kwargs.get("frameon", True):
        leg.get_frame().set_linewidth(frame_linewidth)
    return leg


def place_legend_inside(
    ax: plt.Axes,
    handles: Sequence[Any] | None = None,
    labels: Sequence[str] | None = None,
    *,
    extra_axes: Sequence[plt.Axes] = (),
    loc: Any = "best",
    loc_locked: bool = False,
    bbox_to_anchor: Any = None,
    fontsize: float = 15.0,
    fontsize_locked: bool = False,
    min_fontsize: float = 9.5,
    ncol: int | None = None,
    title: str | None = None,
    frameon: bool = True,
    facecolor: Any = "white",
    edgecolor: Any = "black",
    framealpha: float = 0.94,
    fancybox: bool = False,
    shadow: bool = False,
    frame_linewidth: float | None = 1.15,
    ylim_locked: tuple[bool, bool] = (False, False),
    extra_ylim_locked: Sequence[tuple[bool, bool]] | None = None,
    xlim_locked: tuple[bool, bool] = (True, True),
    allow_xlim_expand: bool = False,
    max_ylim_expand: float = 0.45,
    max_xlim_expand: float = 0.18,
    cap_ticks_at: float | None = None,
    max_box_height_frac: float = 0.58,
    spacing_overrides: dict[str, Any] | None = None,
) -> Legend | None:
    """Place a legend inside `ax`, adapting location, columns, font size, and axis headroom."""
    if handles is None or labels is None:
        h_auto, l_auto = ax.get_legend_handles_labels()
        handles = list(h_auto) if handles is None else list(handles)
        labels = [str(lbl) for lbl in (l_auto if labels is None else labels)]
    else:
        handles = list(handles)
        labels = [str(lbl) for lbl in labels]

    if not handles or not labels:
        return None

    style_kwargs: dict[str, Any] = {"frameon": bool(frameon)}
    if frameon:
        style_kwargs.update(
            {
                "facecolor": facecolor,
                "edgecolor": edgecolor,
                "framealpha": float(framealpha),
                "fancybox": bool(fancybox),
                "shadow": bool(shadow),
            }
        )

    if getattr(ax, "name", "") == "polar":
        return _place_polar_legend_inside(
            ax,
            handles,
            labels,
            fontsize=fontsize,
            min_fontsize=min_fontsize,
            ncol=ncol,
            title=title,
            style_kwargs=style_kwargs,
            frame_linewidth=frame_linewidth,
        )

    # If the caller supplied an explicit custom bbox_to_anchor, render directly (clamping inside [0, 1] if slightly >1).
    if bbox_to_anchor is not None:
        spacing = _compact_spacing_kwargs(1.0, spacing_overrides or {})
        leg = ax.legend(
            handles,
            labels,
            loc="upper right" if normalize_loc_name(loc) == "best" else loc,
            bbox_to_anchor=bbox_to_anchor,
            ncol=ncol or 1,
            fontsize=fontsize,
            title=title,
            **style_kwargs,
            **spacing,
        )
        if title and leg.get_title().get_text():
            leg.get_title().set_fontsize(fontsize)
        if frame_linewidth is not None and frameon:
            leg.get_frame().set_linewidth(frame_linewidth)
        return leg

    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    ax_win = ax.get_window_extent(renderer)
    w_px = max(float(ax_win.width), 40.0)
    h_px = max(float(ax_win.height), 40.0)

    all_axes = [ax, *list(extra_axes)]
    all_ylim_locks = [ylim_locked, *(list(extra_ylim_locked) if extra_ylim_locked is not None else [(False, False)] * len(extra_axes))]
    axis_obstacles, fixed_boxes = _extract_obstacles(ax, all_axes, renderer)

    norm_loc = normalize_loc_name(loc)
    if loc_locked and norm_loc != "best" and norm_loc in (*STANDARD_INSIDE_LOCS, "center"):
        loc_candidates = [norm_loc]
    else:
        loc_candidates = list(STANDARD_INSIDE_LOCS)
        if norm_loc in loc_candidates:
            loc_candidates.remove(norm_loc)
            loc_candidates.insert(0, norm_loc)

    max_lbl_len = max((max((len(line) for line in lbl.splitlines()), default=0) for lbl in labels), default=0)
    fs_candidates = _font_ladder(float(fontsize), float(min_fontsize), locked=fontsize_locked, n_items=len(labels))
    ncol_candidates = _ncol_ladder(len(labels), ncol, max_lbl_len)

    # Pre-measure exact legend box size (w_ax, h_ax) for each (fontsize, ncol) candidate
    measured_boxes: list[tuple[float, int, float, float, dict[str, Any]]] = []
    for fs in fs_candidates:
        ratio = fs / max(float(fontsize), 1.0)
        spacing = _compact_spacing_kwargs(ratio, spacing_overrides or {})
        for nc in ncol_candidates:
            probe = ax.legend(
                handles,
                labels,
                loc="upper right",
                ncol=nc,
                fontsize=fs,
                title=title,
                **style_kwargs,
                **spacing,
            )
            if title and probe.get_title().get_text():
                probe.get_title().set_fontsize(fs)
            ext = probe.get_window_extent(renderer)
            probe.remove()
            measured_boxes.append((fs, nc, float(ext.width) / w_px, float(ext.height) / h_px, spacing))

    clear_pad = 0.018
    x_locks = xlim_locked if allow_xlim_expand else (True, True)
    base_fs = float(fontsize)

    best_score = float("inf")
    best_choice: tuple[float, int, str, float, float, float, float, dict[str, Any]] | None = None

    for fs, nc, w_ax, h_ax, spacing in measured_boxes:
        fs_rel_drop = max(0.0, (base_fs - fs) / max(base_fs, 1.0))
        font_pen = (3.8 if fontsize_locked else 1.25) * (fs_rel_drop ** 2)
        ncol_pen = 0.018 * max(nc - 1, 0) if ncol is None else (1.5 * abs(nc - ncol))
        size_pen = (
            (4.0 * (h_ax - max_box_height_frac) ** 2 if h_ax > max_box_height_frac else 0.0)
            + (4.0 * (w_ax - 0.88) ** 2 if w_ax > 0.88 else 0.0)
        )

        for loc_idx, loc_name in enumerate(loc_candidates):
            bx0, by0, bx1, by1 = _loc_rect(loc_name, w_ax, h_ax)
            overflow = (
                max(0.0, 0.010 - bx0)
                + max(0.0, bx1 - 0.990)
                + max(0.0, 0.010 - by0)
                + max(0.0, by1 - 0.990)
            )
            overflow_pen = 6000.0 * (1.0 + 12.0 * overflow) if overflow > 0.0 else 0.0

            # Fixed Axes-coordinate box collisions (stats boxes, zoom insets) do not move with ylim/xlim
            fixed_pen = 0.0
            for fx0, fy0, fx1, fy1, fw in fixed_boxes:
                ix = max(0.0, min(bx1 + clear_pad, fx1) - max(bx0 - clear_pad, fx0))
                iy = max(0.0, min(by1 + clear_pad, fy1) - max(by0 - clear_pad, fy0))
                if ix > 0.0 and iy > 0.0:
                    fixed_pen += 2200.0 * fw * (1.0 + 25.0 * ix * iy)

            loc_pref_pen = (
                0.0
                if loc_name in ("upper right", "upper left", "lower right", "lower left")
                else (0.022 if loc_name in ("center right", "center left") else 0.035)
            )
            if norm_loc != "best" and loc_name == norm_loc:
                loc_pref_pen -= 0.020
            loc_pref_pen += 0.002 * loc_idx

            # Build candidate (expand_bot, expand_top, expand_left, expand_right) tuples
            exp_candidates: list[tuple[float, float, float, float]] = [(0.0, 0.0, 0.0, 0.0)]

            if "upper" in loc_name and max_ylim_expand > 0.0:
                any_unlocked_top = any(not lk[1] for lk in all_ylim_locks)
                if any_unlocked_top:
                    top_steps = {0.10, 0.20, 0.32, max_ylim_expand}
                    target_uy = by0 - clear_pad
                    if target_uy > 0.22:
                        req_tops: list[float] = []
                        for obs, lk in zip(axis_obstacles, all_ylim_locks):
                            if lk[1] or obs.sx.size == 0 or obs.sy_hi <= obs.sy_lo:
                                continue
                            ux_cur = (obs.sx - obs.sx_lo) / (obs.sx_hi - obs.sx_lo)
                            in_strip = (ux_cur + obs.rx >= bx0 - clear_pad) & (ux_cur - obs.rx <= bx1 + clear_pad)
                            if np.any(in_strip):
                                eff_target = np.maximum(target_uy - obs.ry[in_strip], 0.18)
                                needed_span = (obs.sy[in_strip] - obs.sy_lo) / eff_target
                                cur_span = obs.sy_hi - obs.sy_lo
                                req = float(np.max(needed_span / cur_span - 1.0)) + 0.015
                                if 0.0 < req <= max_ylim_expand:
                                    req_tops.append(req)
                        if req_tops:
                            top_steps.add(max(req_tops))
                    for et in sorted(t for t in top_steps if 0.0 < t <= max_ylim_expand + 1e-9):
                        exp_candidates.append((0.0, min(et, max_ylim_expand), 0.0, 0.0))

            if "lower" in loc_name and max_ylim_expand > 0.0:
                any_unlocked_bot = any(not lk[0] for lk in all_ylim_locks)
                if any_unlocked_bot:
                    bot_steps = {0.10, 0.22, 0.35, max_ylim_expand}
                    target_uy = by1 + clear_pad
                    if target_uy < 0.78:
                        req_bots: list[float] = []
                        for obs, lk in zip(axis_obstacles, all_ylim_locks):
                            if lk[0] or obs.sx.size == 0 or obs.sy_hi <= obs.sy_lo:
                                continue
                            if obs.ax.get_yscale() == "linear" and obs.data_y_min is not None and obs.data_y_min >= -1e-12 and obs.sy_lo <= 1e-12:
                                continue
                            ux_cur = (obs.sx - obs.sx_lo) / (obs.sx_hi - obs.sx_lo)
                            in_strip = (ux_cur + obs.rx >= bx0 - clear_pad) & (ux_cur - obs.rx <= bx1 + clear_pad)
                            if np.any(in_strip):
                                eff_target = np.minimum(target_uy + obs.ry[in_strip], 0.82)
                                sy_new_lo = (obs.sy[in_strip] - eff_target * obs.sy_hi) / (1.0 - eff_target)
                                cur_span = obs.sy_hi - obs.sy_lo
                                req = float(np.max((obs.sy_lo - sy_new_lo) / cur_span)) + 0.015
                                if 0.0 < req <= max_ylim_expand:
                                    req_bots.append(req)
                        if req_bots:
                            bot_steps.add(max(req_bots))
                    for eb in sorted(b for b in bot_steps if 0.0 < b <= max_ylim_expand + 1e-9):
                        exp_candidates.append((min(eb, max_ylim_expand), 0.0, 0.0, 0.0))

            if allow_xlim_expand and max_xlim_expand > 0.0:
                if "right" in loc_name and not x_locks[1]:
                    for er in (0.08, max_xlim_expand):
                        exp_candidates.append((0.0, 0.0, 0.0, er))
                elif "left" in loc_name and not x_locks[0]:
                    for el in (0.08, max_xlim_expand):
                        exp_candidates.append((0.0, 0.0, el, 0.0))

            for eb, et, el, er in exp_candidates:
                data_pen = 0.0
                actual_expand_sum = 0.0

                for obs, lk in zip(axis_obstacles, all_ylim_locks):
                    sy_lo_c, sy_hi_c = _apply_expanded_sy_bounds(obs, eb, et, lk)
                    y_span_orig = abs(obs.sy_hi - obs.sy_lo)
                    actual_y_exp = abs((sy_hi_c - sy_lo_c) - (obs.sy_hi - obs.sy_lo)) / max(y_span_orig, 1e-30)

                    sx_span_orig = obs.sx_hi - obs.sx_lo
                    sx_sgn = -1.0 if sx_span_orig < 0.0 else 1.0
                    sx_lo_c = obs.sx_lo - sx_sgn * (0.0 if x_locks[0] else el) * abs(sx_span_orig)
                    sx_hi_c = obs.sx_hi + sx_sgn * (0.0 if x_locks[1] else er) * abs(sx_span_orig)
                    actual_x_exp = (el if not x_locks[0] else 0.0) + (er if not x_locks[1] else 0.0)
                    actual_expand_sum = max(actual_expand_sum, actual_y_exp + 1.2 * actual_x_exp)

                    if obs.sx.size:
                        ux = (obs.sx - sx_lo_c) / (sx_hi_c - sx_lo_c)
                        uy = (obs.sy - sy_lo_c) / (sy_hi_c - sy_lo_c)
                        vis = (ux >= -0.02) & (ux <= 1.02) & (uy >= -0.02) & (uy <= 1.02)
                        if np.any(vis):
                            ux_v = ux[vis]
                            uy_v = uy[vis]
                            rx_v = obs.rx[vis]
                            ry_v = obs.ry[vis]
                            w_v = obs.weights[vis]

                            hard = (
                                (ux_v >= bx0 - rx_v)
                                & (ux_v <= bx1 + rx_v)
                                & (uy_v >= by0 - ry_v)
                                & (uy_v <= by1 + ry_v)
                            )
                            if np.any(hard):
                                data_pen += 1200.0 * float(np.sum(w_v[hard]))

                            halo = (
                                (~hard)
                                & (ux_v >= bx0 - clear_pad - rx_v)
                                & (ux_v <= bx1 + clear_pad + rx_v)
                                & (uy_v >= by0 - clear_pad - ry_v)
                                & (uy_v <= by1 + clear_pad + ry_v)
                            )
                            if np.any(halo):
                                data_pen += 45.0 * float(np.sum(w_v[halo]))

                    if obs.hline_sy.size:
                        uy_h = (obs.hline_sy - sy_lo_c) / (sy_hi_c - sy_lo_c)
                        hit_h = (uy_h >= by0 - 0.008) & (uy_h <= by1 + 0.008)
                        if np.any(hit_h):
                            data_pen += 90.0 * float(np.sum(hit_h))

                    if obs.vline_sx.size:
                        ux_v = (obs.vline_sx - sx_lo_c) / (sx_hi_c - sx_lo_c)
                        hit_v = (ux_v >= bx0 - 0.008) & (ux_v <= bx1 + 0.008)
                        if np.any(hit_v):
                            data_pen += 90.0 * float(np.sum(hit_v))

                expand_pen = 1.45 * (actual_expand_sum ** 2)
                total_score = overflow_pen + fixed_pen + data_pen + font_pen + expand_pen + size_pen + ncol_pen + loc_pref_pen
                if total_score < best_score:
                    best_score = total_score
                    best_choice = (fs, nc, loc_name, eb, et, el, er, spacing)

    assert best_choice is not None
    win_fs, win_nc, win_loc, win_eb, win_et, win_el, win_er, win_spacing = best_choice

    # Apply chosen axis expansions (if > 0)
    if win_eb > 0.0 or win_et > 0.0:
        for obs, lk in zip(axis_obstacles, all_ylim_locks):
            sy_lo_new, sy_hi_new = _apply_expanded_sy_bounds(obs, win_eb, win_et, lk)
            if not (math.isclose(sy_lo_new, obs.sy_lo) and math.isclose(sy_hi_new, obs.sy_hi)):
                inv_y = obs.ax.yaxis.get_transform().inverted()
                y_bounds = np.asarray(inv_y.transform([sy_lo_new, sy_hi_new]), dtype=float)
                if np.all(np.isfinite(y_bounds)):
                    obs.ax.set_ylim(float(y_bounds[0]), float(y_bounds[1]))

    if allow_xlim_expand and (win_el > 0.0 or win_er > 0.0):
        obs0 = axis_obstacles[0]
        sx_span = obs0.sx_hi - obs0.sx_lo
        sx_sgn = -1.0 if sx_span < 0.0 else 1.0
        sx_lo_new = obs0.sx_lo - sx_sgn * (0.0 if x_locks[0] else win_el) * abs(sx_span)
        sx_hi_new = obs0.sx_hi + sx_sgn * (0.0 if x_locks[1] else win_er) * abs(sx_span)
        inv_x = ax.xaxis.get_transform().inverted()
        x_bounds = np.asarray(inv_x.transform([sx_lo_new, sx_hi_new]), dtype=float)
        if np.all(np.isfinite(x_bounds)):
            for a in all_axes:
                a.set_xlim(float(x_bounds[0]), float(x_bounds[1]))

    if cap_ticks_at is not None and ax.get_yscale() == "linear":
        y_lo_now, y_hi_now = sorted(ax.get_ylim())
        if y_hi_now > cap_ticks_at + 1e-6:
            fig.canvas.draw()
            kept_ticks = [float(t) for t in ax.get_yticks() if y_lo_now - 1e-7 <= float(t) <= cap_ticks_at + 1e-7]
            if kept_ticks:
                ax.yaxis.set_major_locator(ticker.FixedLocator(kept_ticks))

    legend_obj = ax.legend(
        handles,
        labels,
        loc=win_loc,
        ncol=win_nc,
        fontsize=win_fs,
        title=title,
        **style_kwargs,
        **win_spacing,
    )
    if title and legend_obj.get_title().get_text():
        legend_obj.get_title().set_fontsize(win_fs)
    if frame_linewidth is not None and frameon:
        legend_obj.get_frame().set_linewidth(frame_linewidth)
    legend_obj.set_zorder(10.0)
    return legend_obj


def place_shared_legend_inside_panels(
    axes: Sequence[plt.Axes],
    handles: Sequence[Any],
    labels: Sequence[str],
    *,
    fontsize: float = 15.0,
    min_fontsize: float = 9.5,
    ncol: int | None = None,
    title: str | None = None,
    frameon: bool = True,
    facecolor: Any = "white",
    edgecolor: Any = "black",
    framealpha: float = 0.94,
    fancybox: bool = False,
    frame_linewidth: float | None = 1.15,
    ylim_locks_by_panel: Sequence[tuple[bool, bool]] | None = None,
    max_ylim_expand: float = 0.45,
) -> Legend | None:
    """Place a shared multi-panel legend inside a visible panel (preferring panel 0).

    Falls back to a figure-level top legend only in the extreme case where the
    legend has so many entries that it physically overflows a single panel even
    at minimum font size and multi-column layout.
    """
    visible_axes = [a for a in axes if a.get_visible() and a.axison]
    if not visible_axes or not handles or not labels:
        return None

    locks = (
        list(ylim_locks_by_panel)
        if ylim_locks_by_panel is not None
        else [(False, False)] * len(visible_axes)
    )

    target_ax = visible_axes[0]
    target_lock = locks[0] if locks else (False, False)
    leg = place_legend_inside(
        target_ax,
        handles,
        labels,
        fontsize=min(float(fontsize), 14.5),
        min_fontsize=min_fontsize,
        ncol=ncol,
        title=title,
        frameon=frameon,
        facecolor=facecolor,
        edgecolor=edgecolor,
        framealpha=framealpha,
        fancybox=fancybox,
        frame_linewidth=frame_linewidth,
        ylim_locked=target_lock,
        max_ylim_expand=max_ylim_expand,
    )
    if leg is None:
        return None

    # Verify the legend fits within the panel frame; only if an extreme sample count overflows, fall back.
    fig = target_ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    lb = leg.get_window_extent(renderer).transformed(target_ax.transAxes.inverted())
    if lb.width <= 0.98 and lb.height <= 0.78:
        return leg

    leg.remove()
    fallback_ncol = ncol or min(len(labels), 4)
    return fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.98),
        ncol=fallback_ncol,
        fontsize=max(min_fontsize, min(fontsize, 10.5)),
        frameon=False,
    )

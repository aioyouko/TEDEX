#!/usr/bin/env python3
"""Audit an OMNIC Kubelka–Munk spectrum, bridge CO2 residuals, and assess Tauc fits.

Interpolation is an estimate of the continuum, not measured gas subtraction.
Every reconstructed point is excluded from regression. Raw files are read only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/te-bandgap-mpl")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/te-bandgap-cache")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

from te_analysis.tools.plot import DEFAULT_COLORS, apply_plot_style
from te_analysis.tools.figure_naming import add_rename_argument, figure_output_naming, next_figure_stem

HC_EV_CM = 1.2398419843320026e-4
WINDOWS = [(630.0, 700.0, 20.0, "CO2_bend_candidate"),
           (2280.0, 2400.0, 40.0, "CO2_stretch_residual")]
FIT_WINDOWS = [(0.075, 0.120), (0.085, 0.130), (0.100, 0.150),
               (0.120, 0.160), (0.300, 0.380), (0.320, 0.420)]
SOURCES = {
    "CO2_frequencies": "https://cccbdb.nist.gov/exp2x.asp?casno=124389&charge=0",
    "OMNIC_format_reader": "https://github.com/spectrochempy/spectrochempy/blob/master/src/spectrochempy/core/readers/read_omnic.py",
    "Tauc_limitations": "https://doi.org/10.1002/adfm.202304523",
    "Tauc_baseline_analysis": "https://doi.org/10.1021/acscombsci.6b00053",
}


def spa_audit(path: Path, csv: np.ndarray) -> dict:
    """Read only native header, history and spectral payload; verify export identity."""
    raw = path.read_bytes()
    if not raw.startswith(b"Spectral Data File"):
        raise ValueError("Expected OMNIC SPA spectral file")
    records = {}
    for pos in range(304, len(raw) - 15, 16):
        key, offset, length = struct.unpack_from("<HII", raw, pos)
        if key == 0:
            break
        if offset + length > len(raw):
            raise ValueError("SPA block outside file")
        records.setdefault(key, []).append((offset, length))
    header, _ = records[2][0]
    count = struct.unpack_from("<I", raw, header + 4)[0]
    xcode, ycode = raw[header + 8], raw[header + 12]
    last_x, first_x = struct.unpack_from("<ff", raw, header + 16)
    if xcode != 1 or ycode != 20:
        raise ValueError(f"Expected wavenumber and Kubelka-Munk: codes {xcode}, {ycode}")
    offset, length = records[3][0]
    native = np.frombuffer(raw, dtype="<f4", count=count, offset=offset)[::-1]
    native_x = np.linspace(first_x, last_x, count)
    # The CSV contains an extra zero before the instrument's valid spectral range.
    valid_csv = csv[csv[:, 0] >= first_x - 1e-3]
    if len(valid_csv) != count:
        raise ValueError("CSV point count differs from native payload")
    dx = float(np.max(np.abs(valid_csv[:, 0] - native_x)))
    dy = float(np.max(np.abs(valid_csv[:, 1] - native)))
    if dx > 1e-3 or dy > 1e-4:
        raise ValueError("CSV and native SPA spectrum do not agree")
    history = ""
    if 27 in records:
        p, n = records[27][0]
        history = raw[p:p + n].decode("latin1").rstrip("\x00")
    return {"spa_file": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "native_points": int(count), "x_code": xcode, "y_code": ycode,
            "x_unit": "cm^-1", "signal": "Kubelka-Munk F(R)",
            "native_wavenumber_min": first_x, "native_wavenumber_max": last_x,
            "csv_max_wavenumber_difference": dx, "csv_max_signal_difference": dy,
            "resolution_cm^-1": 4.0, "resolution_evidence": "SPA history: Resolution: 4.000",
            "history": history, "payload_bytes": length}


def bridge_co2(x: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray, list]:
    # F(R) is nonlinear: reconstruct reflectance and bridge its apparent optical density.
    reflectance = 1 / (1 + f + np.sqrt(f * (f + 2)))
    apparent_od = -np.log(reflectance)
    clean = f.copy()
    flags = np.full(len(x), "measured", dtype=object)
    details = []
    for lo, hi, padding, name in WINDOWS:
        selected = (x >= lo) & (x <= hi)
        left = (x >= lo - padding) & (x < lo)
        right = (x > hi) & (x <= hi + padding)
        if min(left.sum(), right.sum()) < 5:
            raise ValueError("Not enough points to estimate local continuum")
        anchors_x = [np.median(x[left]), x[left][-1], x[right][0], np.median(x[right])]
        anchors_y = [np.median(apparent_od[left]), apparent_od[left][-1],
                     apparent_od[right][0], np.median(apparent_od[right])]
        rebuilt = PchipInterpolator(anchors_x, anchors_y)(x[selected])
        clean[selected] = np.cosh(rebuilt) - 1
        flags[selected] = name
        delta = clean[selected] - f[selected]
        details.append({"label": name, "min_cm^-1": lo, "max_cm^-1": hi,
                        "min_eV": lo * HC_EV_CM, "max_eV": hi * HC_EV_CM,
                        "n_reconstructed": int(selected.sum()),
                        "padding_cm^-1": padding,
                        "anchor_wavenumber": [float(v) for v in anchors_x],
                        "anchor_apparent_OD": [float(v) for v in anchors_y],
                        "F_corrected_minus_raw_min": float(delta.min()),
                        "F_corrected_minus_raw_max": float(delta.max())})
    measured = flags == "measured"
    if not np.array_equal(clean[measured], f[measured]):
        raise AssertionError("A measured point was altered")
    if not np.all(np.isfinite(clean)) or np.min(clean) <= 0:
        raise AssertionError("Nonphysical or nonfinite reconstructed signal")
    return clean, flags, details


def regress(energy, ordinate, valid, lo, hi) -> dict:
    selected = valid & (energy >= lo) & (energy <= hi)
    xx, yy = energy[selected], ordinate[selected]
    if len(xx) < 12:
        raise ValueError("Too few independent spectral samples")
    slope, intercept = np.polyfit(xx, yy, 1)
    residual = yy - (slope * xx + intercept)
    r2 = 1 - np.sum(residual ** 2) / np.sum((yy - yy.mean()) ** 2)
    return {"fit_low_eV": lo, "fit_high_eV": hi, "fit_n": int(selected.sum()),
            "slope": float(slope), "intercept": float(intercept),
            "apparent_intercept_eV": float(-intercept / slope), "R2": float(r2),
            "intercept_positive": bool(-intercept / slope > 0),
            "bandgap_validated": False}


def plot_style():
    apply_plot_style()
    plt.rcParams.update({"font.size": 12, "axes.labelsize": 15, "axes.titlesize": 15,
                         "xtick.labelsize": 12, "ytick.labelsize": 12,
                         "mathtext.rm": "Arial", "mathtext.it": "Arial:italic",
                         "mathtext.bf": "Arial:bold", "lines.linewidth": 1.3,
                         "axes.linewidth": 1.0, "xtick.major.width": 1.0,
                         "ytick.major.width": 1.0, "xtick.minor.width": .8,
                         "ytick.minor.width": .8, "xtick.major.size": 5,
                         "ytick.major.size": 5, "xtick.minor.size": 3,
                         "ytick.minor.size": 3, "pdf.fonttype": 42})


def finish_axis(ax):
    ax.minorticks_on()
    ax.tick_params(which="both", direction="in", top=True, right=True)
    ax.grid(False)


def save(fig, folder, stem):
    stem = next_figure_stem(stem)
    fig.savefig(folder / f"{stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(folder / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def make_figures(x, raw, clean, flags, fits, output, stem):
    plot_style()
    energy = x * HC_EV_CM
    direct, indirect = (clean * energy) ** 2, np.sqrt(clean * energy)
    usable = flags == "measured"
    colors = [DEFAULT_COLORS[i] for i in [0, 1, 3]]
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 9.2), layout="constrained")
    ax = axes[0, 0]
    ax.plot(energy, raw, color="0.62", lw=.9, label="Original F(R)")
    ax.plot(energy, clean, color=colors[1], lw=1, label="CO$_2$ continuum estimate")
    for lo, hi, _, _ in WINDOWS:
        ax.axvspan(lo * HC_EV_CM, hi * HC_EV_CM, color="0.9", zorder=-1)
    ax.set(xlabel="Photon energy (eV)", ylabel="$F(R)$",
           title=f"(a) {stem}: optical spectrum", xlim=(.045, .5),
           ylim=(0, 1.1 * max(raw.max(), clean.max())))
    ax.legend(frameon=False, fontsize=11, loc="lower right")
    ax.text(.03, .06, "Shaded: reconstructed points excluded from fits", transform=ax.transAxes, fontsize=10)
    ax = axes[0, 1]
    s = (x >= 2220) & (x <= 2450)
    ax.plot(x[s], raw[s], color="0.5", label="Original")
    ax.plot(x[s], clean[s], color=colors[1], label="Continuum estimate")
    ax.axvspan(2280, 2400, color="0.9", zorder=-1)
    ax.set(xlabel="Wavenumber (cm$^{-1}$)", ylabel="$F(R)$",
           title="(b) CO$_2$ residual near 2350 cm$^{-1}$", xlim=(2220, 2450))
    ax.legend(frameon=False, fontsize=11, loc="upper right")
    ax = axes[1, 0]
    s = energy <= .18
    curve = np.where(usable, direct, np.nan)
    ax.plot(energy[s], curve[s], color="0.35", label="Measured Tauc curve")
    for color, (lo, hi) in zip(colors, [FIT_WINDOWS[0], FIT_WINDOWS[2], FIT_WINDOWS[3]]):
        row = next(r for r in fits if r["transition"] == "direct_allowed" and r["fit_low_eV"] == lo and r["fit_high_eV"] == hi)
        intercept = row["apparent_intercept_eV"]
        line_x = np.linspace(max(intercept, 0), hi, 100)
        ax.plot(line_x, row["slope"] * line_x + row["intercept"], "--", color=color,
                label=f"{lo:.3f}-{hi:.3f} eV: intercept {intercept:.3f} eV")
    ax.set(xlabel="Photon energy (eV)", ylabel="$[F(R)E]^2$ (a.u.)",
           title="(c) Direct model: interval-sensitive intercept", xlim=(.04, .18),
           ylim=(0, 1.1 * direct[s].max()))
    ax.legend(frameon=False, fontsize=9.7, loc="upper left")
    ax = axes[1, 1]
    selected_indirect = [r for r in fits if r["transition"] == "indirect_allowed"
                         and (r["fit_low_eV"], r["fit_high_eV"]) in
                         [FIT_WINDOWS[0], FIT_WINDOWS[2], FIT_WINDOWS[3]]]
    indirect_xmin = min(-.055, min(r["apparent_intercept_eV"] for r in selected_indirect) - .015)
    ax.axvspan(indirect_xmin, energy[0], color="0.95", zorder=-1)
    curve = np.where(usable, indirect, np.nan)
    ax.plot(energy[s], curve[s], color="0.35", label="Measured Tauc curve")
    for color, (lo, hi) in zip(colors, [FIT_WINDOWS[0], FIT_WINDOWS[2], FIT_WINDOWS[3]]):
        row = next(r for r in fits if r["transition"] == "indirect_allowed" and r["fit_low_eV"] == lo and r["fit_high_eV"] == hi)
        intercept = row["apparent_intercept_eV"]
        line_x = np.linspace(intercept, hi, 100)
        ax.plot(line_x, row["slope"] * line_x + row["intercept"], "--", color=color,
                label=f"{lo:.3f}-{hi:.3f} eV: intercept {intercept:.3f} eV")
    ax.axvline(0, color="0.65", lw=.8)
    ax.set(xlabel="Photon energy (eV)", ylabel="$[F(R)E]^{1/2}$ (a.u.)",
           title="(d) Indirect model: negative intercepts", xlim=(indirect_xmin, .18),
           ylim=(0, 1.12 * indirect[s].max()))
    ax.legend(frameon=False, fontsize=9.7, loc="upper left")
    for ax in axes.flat:
        finish_axis(ax)
    save(fig, output, f"{stem}_bandgap_diagnostic")

    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.8), layout="constrained")
    for ax, (lo, hi, pad, name) in zip(axes, WINDOWS):
        view = (x >= lo - 2 * pad) & (x <= hi + 2 * pad)
        ax.plot(x[view], raw[view], color="0.5", label="Original")
        ax.plot(x[view], clean[view], color=colors[1], label="Continuum estimate")
        ax.axvspan(lo, hi, color="0.9", zorder=-1)
        ax.set(xlabel="Wavenumber (cm$^{-1}$)", ylabel="$F(R)$",
               title="Candidate bending band: cautiously masked" if lo < 1000 else "Stretching-band background residual")
        ax.legend(frameon=False, fontsize=11)
        finish_axis(ax)
    save(fig, output, f"{stem}_CO2_windows")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--spa", type=Path)
    parser.add_argument("--output", type=Path)
    add_rename_argument(parser)
    args = parser.parse_args()
    with figure_output_naming(args.rename):
        return _run_cli(args)


def _run_cli(args):
    source = args.input.resolve()
    spa = (args.spa or source.parent / "raw" / source.with_suffix(".SPA").name).resolve()
    output = (args.output or ROOT / "results" / "plots" / "bandgap" / source.stem).resolve()
    output.mkdir(parents=True, exist_ok=True)
    all_data = np.loadtxt(source, delimiter=",")
    metadata = spa_audit(spa, all_data)
    keep = all_data[:, 0] >= metadata["native_wavenumber_min"] - 1e-3
    data = all_data[keep]
    x, raw = data.T
    if not np.all(np.diff(x) > 0) or not np.all(np.isfinite(data)) or raw.min() <= 0:
        raise ValueError("Input must be ordered, finite, positive F(R)")
    clean, flags, corrections = bridge_co2(x, raw)
    energy = x * HC_EV_CM
    native_step = float(np.median(np.diff(x)))
    stride = int(np.ceil(metadata["resolution_cm^-1"] / native_step))
    subsampled = np.zeros(len(x), dtype=bool)
    subsampled[::stride] = True
    # Buffer the interpolation windows by 10 cm-1; no interpolated data enter fits.
    eligible = flags == "measured"
    for lo, hi, _, _ in WINDOWS:
        eligible &= ~((x >= lo - 10) & (x <= hi + 10))
    fit_valid = eligible & subsampled
    fits = []
    for transition, power in [("direct_allowed", 2.0), ("indirect_allowed", .5)]:
        for lo, hi in FIT_WINDOWS:
            row = regress(energy, (clean * energy) ** power, fit_valid, lo, hi)
            before = regress(energy, (raw * energy) ** power, fit_valid, lo, hi)
            row.update(transition=transition, exponent=power,
                       raw_apparent_intercept_eV=before["apparent_intercept_eV"],
                       intercept_change_due_to_CO2=row["apparent_intercept_eV"] - before["apparent_intercept_eV"])
            fits.append(row)
    reflectance = 1 / (1 + clean + np.sqrt(clean * (clean + 2)))
    spectrum = pd.DataFrame({"wavenumber_cm-1": x, "energy_eV": energy, "F_R_raw": raw,
                             "F_R_CO2_continuum_estimate": clean,
                             "F_R_corrected_minus_raw": clean - raw,
                             "inferred_reflectance_fraction": reflectance,
                             "point_status": flags,
                             "eligible_for_regression": eligible.astype(int),
                             "resolution_subsample": subsampled.astype(int),
                             "tauc_direct": (clean * energy) ** 2,
                             "tauc_indirect": np.sqrt(clean * energy)})
    stem = source.stem
    spectrum.to_csv(output / f"{stem}_processed.csv", index=False, float_format="%.10g")
    np.savetxt(output / f"{stem}_CO2_corrected.CSV", np.column_stack([x, clean]), delimiter=",", fmt="%.8e")
    pd.DataFrame(fits).to_csv(output / f"{stem}_exploratory_fits.csv", index=False, float_format="%.10g")
    low_direct = [r for r in fits if r["transition"] == "direct_allowed" and r["fit_high_eV"] <= .16]
    summary = {"sample": stem, "input": str(source),
               "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "metadata": metadata, "removed_export_rows": all_data[~keep].tolist(),
               "valid_points": len(x), "energy_range_eV": [float(energy.min()), float(energy.max())],
               "signal_range_F_R": [float(raw.min()), float(raw.max())],
               "inferred_raw_R_percent_range": [float(100 / (1 + raw.max() + np.sqrt(raw.max() * (raw.max() + 2)))),
                                                 float(100 / (1 + raw.min() + np.sqrt(raw.min() * (raw.min() + 2))))],
               "correction_method": "PCHIP continuum interpolation in -ln(R), R inferred from F(R); not a gas-reference subtraction",
               "CO2_windows": corrections, "fit_stride": stride,
               "fit_sample_spacing_cm^-1": stride * native_step,
               "interpolation_fit_buffer_cm^-1": 10,
               "fits": fits, "status": "no_reliable_unique_bandgap",
               "reported_bandgap_eV": None,
               "low_energy_direct_intercept_range_eV": [min(r["apparent_intercept_eV"] for r in low_direct), max(r["apparent_intercept_eV"] for r in low_direct)],
               "limitations": ["F(R) baseline remains large below the proposed edge; no independently known absorption baseline",
                               "Fit intercept changes with chosen energy interval",
                               "Indirect-allowed fits produce negative energy intercepts",
                               "Diffuse-reflectance geometry, optical thickness, and scattering dependence not verified",
                               "Atmospheric water-like residuals outside CO2 windows retained",
                               "CO2 bending-window attribution is tentative; masking may remove sample features"],
               "checks": {"unchanged_outside_CO2_windows": True,
                          "finite_positive_clean_spectrum": True,
                          "native_export_agreement": True,
                          "all_fits_exclude_interpolated_points": bool(np.all(flags[fit_valid] == "measured")),
                          "fit_CO2_effect_max_eV": max(abs(r["intercept_change_due_to_CO2"]) for r in fits)},
               "references": SOURCES}
    (output / f"{stem}_analysis.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"{stem} 红外光谱 CO2 处理与带隙评估", "",
             "结论：可以生成探索性 Tauc 拟合，但此数据不能可靠确定唯一的光学带隙。", "",
             "1. 数据审计",
             "原始 SPA 文件显示：Final format: Kubelka-Munk；纵轴为 F(R)，不是透过率或普通吸光度。",
             f"CSV 与 SPA 原始信号吻合，纵轴最大舍入差 {metadata['csv_max_signal_difference']:.2g}。",
             f"有效点 {len(x)} 个；波数 {x.min():.4f}–{x.max():.4f} cm^-1；能量 {energy.min():.5f}–{energy.max():.5f} eV。",
             "CSV 第一行 399.6813,0 不在原始 SPA 测量范围内，作为导出占位行剔除。",
             f"仪器分辨率 4 cm^-1；拟合每 {stride} 个原始点取一点，间隔约 {stride*native_step:.2f} cm^-1，避免过采样点数造成虚假精度。", "",
             "2. CO2 处理",
             "NIST 给出的 CO2 基频为约 2349 cm^-1（伸缩）与 667 cm^-1（弯曲）。",
             "主峰处是向下残留，提示背景与样品空气吸收不一致；归因尚需背景/气体参考确认。",
             "处理窗口：2280–2400 cm^-1，以及归属不确定的 630–700 cm^-1。",
             "先由 F(R) 反算 R=1/[1+F+sqrt(F(F+2))]，再在 -ln(R) 域用两侧连续背景做 PCHIP 插值，最后换回 F(R)。",
             "此操作是局部连续背景重建，不是用实测 CO2 参考定量扣除。弯曲窗口可能含样品信号，已明确标记。",
             "窗口外的数值完全保留；所有插值点及窗口外侧 10 cm^-1 缓冲区均不参与拟合；其余水汽样残留保留。", "",
             "3. Tauc 方法与探索性结果",
             "E(eV)=1.2398419843320026e-4 × 波数(cm^-1)。",
             "直接允许跃迁：y=[F(R)E]^2；间接允许跃迁：y=[F(R)E]^(1/2)。",
             "对指定区间做 y=mE+b 线性拟合，横轴截距=-b/m。该截距只有在物理模型和真实带边成立时才可解释为 Eg。",
             "没有任意减去常数背景，也没有用平滑曲线参与回归。", "",
             "模型                 区间/eV         横轴截距/eV     R^2     是否确认为带隙"]
    for row in fits:
        label = "直接允许" if row["transition"] == "direct_allowed" else "间接允许"
        lines.append(f"{label:<12} {row['fit_low_eV']:.3f}–{row['fit_high_eV']:.3f}       {row['apparent_intercept_eV']: .5f}       {row['R2']:.5f}   否")
    lines += ["", "高能区 0.300–0.420 eV 的拟合仅作敏感性/反例检查，该区间原始 F(R) 在下降，没有可确认的吸收起始，不能按最高 R^2 选成带隙。",
              "CO2 掩膜及缓冲区内的数据不参加回归，所以相同掩膜下原始谱/处理谱的外推截距一致。这表明去除 CO2 不能解决此谱的带边识别问题。", "",
              "4. 为什么不报唯一 Eg",
              "低能侧 F(R) 已明显大于零；整个测量范围没有可独立确定的弱吸收基线。直接模型有曲率，换区间就改变外推截距；间接模型出现负截距。",
              "不能凭 R^2 高选择跃迁类型，也不能凭负截距判定材料是金属或没有带隙。",
              "应确认材料/成分、粉末漫反射还是块体镜面反射，并检查参考、样品光学厚度与散射条件。",
              "若目标带隙接近或低于 0.05 eV，需要更低波数覆盖；若目标带隙高于 0.496 eV，需要近红外/可见光谱。",
              "建议在充分吹扫后重测匹配背景与样品，获取带边两侧的弱吸收区与上升区，再判断直接/间接模型。", "",
              "5. 输出说明",
              f"{stem}_CO2_corrected.CSV：两列、无表头，波数及重建 F(R)，可按原始文件方式导入；已去掉零占位行。",
              f"{stem}_processed.csv：包含原始值、处理值、能量、插值标记、回归资格、反算 R 与 Tauc 数据。",
              f"{stem}_exploratory_fits.csv：各区间探索性拟合，bandgap_validated 全为 False。",
              "诊断图提供 PNG 与矢量 PDF；analysis.json 保存参数与检查记录。", "", "参考资料："]
    lines += [f"{key}: {url}" for key, url in SOURCES.items()]
    (output / f"{stem}_report_zh.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    make_figures(x, raw, clean, flags, fits, output, stem)
    print(json.dumps({"output": str(output), "status": summary["status"],
                      "direct_intercept_range_eV": summary["low_energy_direct_intercept_range_eV"],
                      "fits": [{k: row[k] for k in ["transition", "fit_low_eV", "fit_high_eV", "apparent_intercept_eV", "R2"]} for row in fits],
                      "checks": summary["checks"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

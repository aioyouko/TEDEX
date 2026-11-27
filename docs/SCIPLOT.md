# Scientific Plotting (`sciplot`) Commands

这个文档专门记录 `python main.py sciplot` 的用法。它支持直接命令或可复用的 JSON 画图格式（`--recipe` / `--figure`），覆盖科研论文常用的全部图型：

- 基础曲线与柱图：`line`、`scatter`、`bar`、`grouped_bar`、`stacked_bar`、`percent_stacked_bar`、`waterfall`
- 双轴与多面板：`dual_axis`、`dual_line`、`multi_panel`、`broken_y`（断轴图）、`fit_residual`（拟合+残差双栏图）
- 二维场、多维筛选与相图：`heatmap`、`contour`（等高线/相图）、`bubble`（气泡图）、`ternary`（三元成分相图）
- 统计、动力学与综合对比：`boxplot`、`violin`、`histogram`（含正态/对数正态/KDE 拟合）、`parity`（预测 vs 实验对角图）、`arrhenius`（含顶部 $T$ 轴与 $E_{\mathrm{a}}$ 拟合）、`radar`（雷达图）、`benchmark`（文献对标高亮图）
- 通用科研叠加层：误差棒/误差阴影带（`--yerr` / `--yerr-pct` / `--error-mode`）、参考线与阴影带（`--hline` / `--vline` / `--hspan` / `--vspan`）、画中画局部放大（`--inset-xlim` / `--inset-ylim`）

其中 `--figure` 是智能快捷入口：既可以直接传图类型名（如 `--figure waterfall`、`--figure contour`、`--figure ternary`），也可以直接传 `configs/plot_recipes/` 下的格式模板名（如 `--figure contour_phase_map`、`--figure parity_pred_vs_exp`），数据来源与坐标轴参数写法完全保持一致：

```bash
python main.py sciplot --figure contour_phase_map your_data.csv --xlim 300 800 --zlim 0 1.6 --no-show
python main.py sciplot --figure waterfall your_steps.csv --x Step --y Value --ylim 0 1.8 --no-show
```

所有命令建议在项目主目录运行：

```bash
cd ~/Documents/tedex
```

默认输出位置：

```text
<输入数据共同目录>/figures/       # 默认
--output-dir <路径>                # 显式指定时
```

## Color Sets

使用 `--color-set npg` 选择默认多色方案，或用 `--color-set blue` / `teal` /
`purple` / `orange` / `red` / `gray` 比较同成分不同批次。`--color-set legacy` 恢复原有 24 色。
也可以在 recipe 的 `plot` 中保存 `"color_set": "blue"`；命令行设置优先于此字段。
现有 `--color` 和系列 `color` 仍可指定具体颜色，不会被色板覆盖。

完整色卡、全部方案及混合多个色系的示例见 [配色手册](COLOR_SETS.md)。

## Two Ways To Use It

`python main.py sciplot` 有两种模式：

1. 直接命令模式：适合临时画一张图，不想先写 JSON。
2. Recipe 配置模式：适合重复画同一种格式，或者想保存一套固定绘图参数。

## Direct CLI Mode

最基本命令结构：

```bash
python main.py sciplot \
  --data <数据文件> \
  --kind <图类型> \
  --x <x列名> \
  --y <y列名> \
  --xlabel "<x轴标签>" \
  --ylabel "<y轴标签>" \
  --output-dir outputs/figures/flexible_cli \
  --stem <输出文件名> \
  --formats png pdf \
  --no-show
```

`--no-show` 表示只保存图片，不弹出 matplotlib 窗口。建议批量画图或远程运行时都加上。

### Single Line Plot

从一个 CSV 画一条曲线：

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/messy_te_temperature_series.csv \
  --kind line \
  --x "Temp / K" \
  --y "S (uV/K)" \
  --xlabel "$T$ (K)" \
  --ylabel "$S$ ($\\mu$V K$^{-1}$)" \
  --label "Seebeck" \
  --stem demo_seebeck_line \
  --formats png pdf \
  --no-show
```

输出：

```text
outputs/figures/flexible_cli/demo_seebeck_line.png
outputs/figures/flexible_cli/demo_seebeck_line.pdf
outputs/figures/flexible_cli/demo_seebeck_line_normalized.csv
```

如果不想保存 normalized CSV：

```bash
python main.py sciplot ... --no-normalized-csv
```

### Multiple Y Columns From One File

同一个文件里画多条 y 曲线：

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/messy_te_temperature_series.csv \
  --kind line \
  --x "Temp / K" \
  --y "S (uV/K)" \
  --y "Power factor" \
  --label "Seebeck" \
  --label "Power factor" \
  --xlabel "$T$ (K)" \
  --ylabel "Value" \
  --stem demo_two_curves \
  --formats png pdf \
  --no-show
```

注意：多个 `--y` 最好配多个 `--label`，顺序一一对应。

### Multiple Files

多个文件画到同一张图。如果每个文件使用相同的 x/y 列名，只需要写一个 `--x` 和一个 `--y`：

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/pbse_tec_qc_split/dt0.csv \
  --data data/demo/flexible_plotting/pbse_tec_qc_split/dt10.csv \
  --kind line \
  --x I_A \
  --y Qc_W \
  --label "Delta T = 0 K" \
  --label "Delta T = 10 K" \
  --xlabel "Current (A)" \
  --ylabel "$Q_c$ (W)" \
  --stem demo_multi_file_qc \
  --formats png pdf \
  --no-show
```

### Scatter Plot

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/literature_comparison_loose.csv \
  --kind scatter \
  --x "Ag fraction x" \
  --y "Best zT" \
  --xlabel "Ag fraction, $x$" \
  --ylabel "$ZT_{\\mathrm{max}}$" \
  --stem demo_scatter \
  --formats png pdf \
  --no-show
```

### Bar And Grouped Bar Plot

普通柱状图可以直接用字符串列作分类 x 轴：

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/composition_grouped_bar_summary.csv \
  --kind bar \
  --x "Composition" \
  --y "zT_700K" \
  --xlabel "Composition" \
  --ylabel "$zT$" \
  --stem demo_bar \
  --formats png pdf \
  --no-show
```

分组柱状图只需要重复 `--y` 和 `--label`：

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/composition_grouped_bar_summary.csv \
  --kind grouped_bar \
  --x "Composition" \
  --y "zT_500K" \
  --y "zT_700K" \
  --label "500 K" \
  --label "700 K" \
  --xlabel "Composition" \
  --ylabel "$zT$" \
  --stem demo_grouped_bar \
  --formats png pdf \
  --no-show
```

### Dual-Line Plot

`dual_line` 适合两个 y 轴，例如 Hall carrier concentration 和 mobility：

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/messy_te_temperature_series.csv \
  --kind dual_line \
  --x "Temp / K" \
  --y "S (uV/K)" \
  --y "sigma [S cm-1]" \
  --label "Seebeck" \
  --label "Conductivity" \
  --xlabel "$T$ (K)" \
  --ylabel "$S$ ($\\mu$V K$^{-1}$)" \
  --right-ylabel "$\\sigma$ (S cm$^{-1}$)" \
  --stem demo_dual_line \
  --formats png pdf \
  --no-show
```

### Axis Limits, Log Scale, Ticks

常用坐标轴控制：

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/literature_comparison_loose.csv \
  --kind scatter \
  --x "Ag fraction x" \
  --y "Best zT" \
  --xlim 0 0.18 \
  --ylim 0.3 0.9 \
  --x-major 0.05 \
  --y-major 0.1 \
  --stem demo_scatter_limited \
  --formats png pdf \
  --no-show
```

对数坐标：

```bash
python main.py sciplot \
  --data your_data.csv \
  --kind line \
  --x T_K \
  --y n_H_cm-3 \
  --yscale log \
  --stem hall_n_log \
  --formats png pdf \
  --no-show
```

### Text Annotation

数据坐标标注：

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/literature_comparison_loose.csv \
  --kind scatter \
  --x "Ag fraction x" \
  --y "Best zT" \
  --text "0.08,0.83,best sample" \
  --stem demo_scatter_text \
  --formats png \
  --no-show
```

图框相对坐标标注，`0,0` 是左下，`1,1` 是右上：

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/literature_comparison_loose.csv \
  --kind scatter \
  --x "Ag fraction x" \
  --y "Best zT" \
  --text-axes "0.05,0.92,(a)" \
  --stem demo_panel_label \
  --formats png \
  --no-show
```

## Input File Notes

Supported input types:

```text
.csv
.txt
.tsv
.xlsx
```

Excel sheet can be supplied in either style:

```bash
python main.py sciplot --data "data.xlsx::Sheet1" ...
python main.py sciplot --data data.xlsx --sheet Sheet1 ...
```

For tab- or whitespace-separated text:

```bash
python main.py sciplot \
  --data data/demo/flexible_plotting/pbse_tec_dtmax_curve.txt \
  --sep "\\s+" \
  --x T_H_K \
  --y DeltaTmax_K \
  --stem dtmax_from_txt \
  --formats png pdf \
  --no-show
```

If the header is not on the first row:

```bash
python main.py sciplot \
  --data your_data.csv \
  --skiprows 2 \
  --header 0 \
  --x Temperature \
  --y Seebeck \
  --stem skipped_header_example \
  --no-show
```

For ANSI instrument exports, the encoding and a recognizable header prefix
can be supplied directly:

```bash
python main.py sciplot \
  --data instrument_export.csv \
  --encoding latin1 \
  --header-prefix "##" \
  --x "##Temp./°C" \
  --y "DTA/(µV/mg)" \
  --stem instrument_curve \
  --no-show
```

## Recipe Mode

Recipe 是 JSON 文件，适合长期复用。运行已有 recipe：

```bash
python main.py sciplot --recipe configs/sciplot_demos/temperature_seebeck_line.json --no-show
```

一次运行多个 recipe：

```bash
python main.py sciplot \
  --recipe configs/sciplot_demos/temperature_seebeck_line.json \
  --recipe configs/sciplot_demos/temperature_multi_panel.json \
  --recipe configs/sciplot_demos/room_temp_dual_axis.json \
  --no-show
```

常用 recipe 位置：

```text
configs/sciplot_demos/      # demo examples
configs/plot_recipes/             # reusable recipe templates
```

### Minimal Recipe Template

```json
{
  "name": "my flexible plot",
  "data": [
    {
      "path": "data/demo/flexible_plotting/messy_te_temperature_series.csv"
    }
  ],
  "plot": {
    "kind": "line",
    "x": {
      "column": "Temp / K",
      "label": "$T$ (K)"
    },
    "series": [
      {
        "y": {
          "column": "S (uV/K)",
          "label": "$S$ ($\\mu$V K$^{-1}$)"
        },
        "property": "seebeck",
        "group_value": "sample A",
        "legend_label": "sample A"
      }
    ],
    "xlabel": "$T$ (K)",
    "ylabel": "$S$ ($\\mu$V K$^{-1}$)",
    "legend": "inside",
    "legend_font_size": 8,
    "legend_frame": true
  },
  "output": {
    "dir": "outputs/figures/flexible",
    "stem": "my_flexible_plot",
    "formats": ["png", "pdf"],
    "normalized_csv": true
  }
}
```

Run it:

```bash
python main.py sciplot --recipe configs/plot_recipes/my_flexible_plot.json --no-show
```

### Recipe Keys You Usually Edit

| Key | Meaning |
| --- | --- |
| `data[].path` | Input CSV/TXT/XLSX path. |
| `source_defaults` | Reader options inherited by every input source, such as `encoding` and `header_startswith`. Per-source options override these defaults. |
| `plot.kind` | `line`, `scatter`, `bar`, `grouped_bar`, `multi_panel`, `dual_axis`, or `dual_line`. |
| `plot.x.column` | Exact x column name. |
| `plot.x.semantic` | Loose semantic lookup, such as `temperature`. |
| `plot.x_order` | Optional order for categorical x values in `bar` and `grouped_bar`. |
| `plot.group.column` | Column used to group curves or points. |
| `plot.series[]` | One or more y-series definitions. |
| `series[].y.column` | Exact y column name. |
| `series[].semantic` | Loose semantic lookup, such as `seebeck`, `conductivity`, `zt`. |
| `series[].property` | Internal property name used for style/color defaults. |
| `series[].scale` | Multiply y values before plotting. Useful for unit conversion. |
| `plot.bar_width` | Total width for one category in `bar` and `grouped_bar`. |
| `plot.bar_labels` | Whether to print values above bars. |
| `plot.legend` | Legend mode: `inside`, `outside`, or `none`. |
| `plot.legend_font_size` | Legend font size in points. |
| `plot.legend_frame` | Whether to draw the legend box. Defaults to `true`. |
| `plot.legend_edgecolor` | Legend box edge color. Defaults to `black`. |
| `plot.legend_facecolor` | Legend box background color. Defaults to `white`. |
| `plot.legend_frame_linewidth` | Legend box edge width. Defaults to `0.8`. |
| `output.dir` | Output folder. Use `outputs/figures/flexible...`. |
| `output.stem` | Output filename without extension. |
| `output.formats` | Example: `["png", "pdf"]` or `["svg"]`. |
| `output.normalized_csv` | Whether to save the normalized table next to the figure. |

## Existing Recipe Examples

| Recipe | What it does |
| --- | --- |
| `configs/sciplot_demos/temperature_seebeck_line.json` | Single Seebeck vs temperature line plot with loose column matching. |
| `configs/sciplot_demos/temperature_multi_panel.json` | Multi-panel TE transport figure from one messy table. |
| `configs/sciplot_demos/room_temp_dual_axis.json` | Room-temperature dual-axis plot with unit scaling. |
| `configs/sciplot_demos/composition_scatter.json` | Literature-style composition scatter plot. |
| `configs/sciplot_demos/composition_grouped_bar.json` | Composition-category grouped bar plot. |
| `configs/sciplot_demos/pbse_tec_dtmax_txt.json` | TXT input with DeltaTmax curve. |
| `configs/sciplot_demos/pbse_tec_qc_excel_multicolumn.json` | Excel input with multiple Qc curves. |
| `configs/sciplot_demos/pbse_tec_qc_multi_files.json` | Multiple files combined into one plot. |
| `configs/plot_recipes/bar/simple_bar.json` | Reusable single-series bar chart template. |
| `configs/plot_recipes/bar/grouped_bar.json` | Reusable grouped bar chart template. |
| `configs/plot_recipes/dual_axis/temperature_vs_carrier_mobility_dual.json` | Dual-line Hall carrier concentration and mobility template. |
| `configs/plot_recipes/sta/temperature_vs_dta.json` | NETZSCH STA/DTA export with ANSI encoding and automatic `##` header detection. |

### NETZSCH STA / DTA

The STA recipe reads the metadata-prefixed CSV exports directly; no cleaned
intermediate CSV is needed. To compare TE-1070 second-heating segments:

```bash
python main.py sciplot \
  data/raw/TE-1070/STA/ExpDat_te-1070-a-3.csv \
  data/raw/TE-1070/STA/ExpDat_te-1070-d-3.csv \
  --recipe configs/plot_recipes/sta/temperature_vs_dta.json \
  --label TE-1070-A \
  --label TE-1070-D \
  --no-show
```

For these NETZSCH files, the metadata value `EXO +1` means exothermic peaks
point upward, so an endothermic melting feature on a heating curve points
downward. File suffixes
`-1`, `-2`, `-3`, and `-4` correspond to first heating, first cooling, second
heating, and second cooling in this export set.

## Overriding A Recipe From CLI

You can use a recipe as a template and override some fields:

```bash
python main.py sciplot \
  --recipe configs/sciplot_demos/temperature_seebeck_line.json \
  --data data/demo/flexible_plotting/messy_te_temperature_series.csv \
  --stem quick_override_seebeck \
  --formats png \
  --no-show
```

Override x/y columns:

```bash
python main.py sciplot \
  --recipe configs/sciplot_demos/temperature_seebeck_line.json \
  --x "Temp / K" \
  --y "S (uV/K)" \
  --stem quick_override_columns \
  --no-show
```

## Extended Scientific Plot Examples (`--figure`)

```bash
# 1. 堆叠柱状图 / 百分比堆叠柱状图（如 κ_L + κ_e 构成）
python main.py sciplot --figure stacked_bar kappa_parts.csv \
  --x Sample --y kappa_L --y kappa_e --label "$\kappa_{\mathrm{L}}$" --label "$\kappa_{\mathrm{e}}$" \
  --ylabel "$\kappa$ (W m$^{-1}$ K$^{-1}$)" --no-show

# 2. 阶梯瀑布图（协同优化贡献拆解；支持 --waterfall-mode delta 或 levels）
python main.py sciplot --figure waterfall_steps steps.csv --ylim 0 1.6 --no-show

# 3. 二维等高线相图 / 热力图（支持规则网格或散乱 (x, y, z) 点自动三角剖分）
python main.py sciplot --figure contour phase_data.csv \
  --x T_K --y x_doping --z ZT --zlabel "$zT$" --xlim 300 800 --zlim 0.1 1.5 --no-show

# 4. 三元成分相图（散点或叠加强度等高线云图）
python main.py sciplot --figure ternary_composition ternary.csv \
  --a CuInTe2 --b CuGaTe2 --c ZnSe --z ZT --alabel "CuInTe$_2$" --blabel "CuGaTe$_2$" --clabel "ZnSe" --no-show

# 5. 四维材料筛选气泡图（x, y, 颜色=z, 面积=size）
python main.py sciplot --figure bubble screening.csv \
  --x kappa_L --y PF --z T_K --size ZT --zlabel "$T$ (K)" --no-show

# 6. 统计分布：箱线图 / 小提琴图 / 对数正态拟合粒径直方图
python main.py sciplot --figure boxplot hardness.csv --x Sample --y Hardness_GPa --no-show
python main.py sciplot --figure histogram grains.csv --x Diameter_nm --fit-dist lognormal --bins 16 --no-show

# 7. 机器学习/模型预测 Parity 对角图（含 ±10% 误差锥与 R²/MAE/RMSE）
python main.py sciplot --figure parity_pred_vs_exp predictions.csv --xlim 0 1.6 --no-show

# 8. Arrhenius 激活能拟合图（自动转换 1000/T、生成顶部 T(K) 轴并标注 E_a）
python main.py sciplot --figure arrhenius_conductivity transport.csv --fit-range 450 800 --no-show

# 9. 文献 Benchmark 对标图 + 误差阴影带 + 参考线 + 局部放大画中画 Inset
python main.py sciplot --figure benchmark lit_vs_ours.csv \
  --group Sample --x T_K --y ZT --highlight "This work" --end-labels --no-show

python main.py sciplot --figure line transport.csv \
  --group Sample --x T_K --y ZT --yerr-pct 8 --error-mode band \
  --hline "1.0,$zT=1$,#444444,--" --inset-xlim 650 800 --inset-ylim 0.9 1.5 --no-show

# 10. 断轴图、分峰拟合+残差双栏图、多指标归一化雷达图
python main.py sciplot --figure broken_y cond.csv --group Sample --x T_K --y sigma --ylim 0 320 --ylim-top 1100 1500 --no-show
python main.py sciplot --figure fit_with_residual peaks.csv --xlim 26 30 --no-show
python main.py sciplot --figure radar_multi_metric metrics.csv --no-show
```

## Troubleshooting

If a column cannot be found:

1. Open the data file and copy the column name exactly.
2. Put quotes around column names with spaces or symbols.
3. Try exact `column` in a recipe instead of semantic matching.

If units look wrong:

1. Check whether the data is in S/m or S/cm.
2. Use `series[].scale` in recipe mode for conversion.
3. Rename output stem after changing units so old figures are not confused with new ones.

If the figure is saved but looks blank:

1. Check that x and y columns are numeric.
2. Check `--xlim`, `--ylim`, and log-scale settings.
3. Open the normalized CSV saved next to the figure and inspect the plotted columns.

If labels with LaTeX fail:

1. Keep labels inside quotes.
2. Escape backslashes in JSON as `\\`.
3. In shell commands, use double backslashes for LaTeX commands, e.g. `$\\mu$`.

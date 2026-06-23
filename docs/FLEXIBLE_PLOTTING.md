# Flexible Plotting Commands

这个文档专门记录 `python main.py flexible` 的用法。它适合处理“列名不完全统一、临时整理的 CSV/TXT/XLSX 数据”，快速画 line、scatter、bar、grouped-bar、multi-panel、dual-axis、dual-line 图。

所有命令建议在项目主目录运行：

```bash
cd "/Users/chenheyang/Library/CloudStorage/OneDrive-NorthwesternUniversity/02-Northwestern Lab/te_agent_workspace"
```

默认输出位置：

```text
outputs/figures/flexible_cli/      # 直接命令模式
outputs/figures/flexible/          # 常用 recipe
```

## Two Ways To Use It

`python main.py flexible` 有两种模式：

1. 直接命令模式：适合临时画一张图，不想先写 JSON。
2. Recipe 配置模式：适合重复画同一种格式，或者想保存一套固定绘图参数。

## Direct CLI Mode

最基本命令结构：

```bash
python main.py flexible \
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
python main.py flexible \
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
python main.py flexible ... --no-normalized-csv
```

### Multiple Y Columns From One File

同一个文件里画多条 y 曲线：

```bash
python main.py flexible \
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
python main.py flexible \
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
python main.py flexible \
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
python main.py flexible \
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
python main.py flexible \
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
python main.py flexible \
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
python main.py flexible \
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
python main.py flexible \
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
python main.py flexible \
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
python main.py flexible \
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
python main.py flexible --data "data.xlsx::Sheet1" ...
python main.py flexible --data data.xlsx --sheet Sheet1 ...
```

For tab- or whitespace-separated text:

```bash
python main.py flexible \
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
python main.py flexible \
  --data your_data.csv \
  --skiprows 2 \
  --header 0 \
  --x Temperature \
  --y Seebeck \
  --stem skipped_header_example \
  --no-show
```

## Recipe Mode

Recipe 是 JSON 文件，适合长期复用。运行已有 recipe：

```bash
python main.py flexible --recipe configs/flexible_plot_demos/temperature_seebeck_line.json --no-show
```

一次运行多个 recipe：

```bash
python main.py flexible \
  --recipe configs/flexible_plot_demos/temperature_seebeck_line.json \
  --recipe configs/flexible_plot_demos/temperature_multi_panel.json \
  --recipe configs/flexible_plot_demos/room_temp_dual_axis.json \
  --no-show
```

常用 recipe 位置：

```text
configs/flexible_plot_demos/      # demo examples
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
python main.py flexible --recipe configs/plot_recipes/my_flexible_plot.json --no-show
```

### Recipe Keys You Usually Edit

| Key | Meaning |
| --- | --- |
| `data[].path` | Input CSV/TXT/XLSX path. |
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
| `configs/flexible_plot_demos/temperature_seebeck_line.json` | Single Seebeck vs temperature line plot with loose column matching. |
| `configs/flexible_plot_demos/temperature_multi_panel.json` | Multi-panel TE transport figure from one messy table. |
| `configs/flexible_plot_demos/room_temp_dual_axis.json` | Room-temperature dual-axis plot with unit scaling. |
| `configs/flexible_plot_demos/composition_scatter.json` | Literature-style composition scatter plot. |
| `configs/flexible_plot_demos/composition_grouped_bar.json` | Composition-category grouped bar plot. |
| `configs/flexible_plot_demos/pbse_tec_dtmax_txt.json` | TXT input with DeltaTmax curve. |
| `configs/flexible_plot_demos/pbse_tec_qc_excel_multicolumn.json` | Excel input with multiple Qc curves. |
| `configs/flexible_plot_demos/pbse_tec_qc_multi_files.json` | Multiple files combined into one plot. |
| `configs/plot_recipes/bar/simple_bar.json` | Reusable single-series bar chart template. |
| `configs/plot_recipes/bar/grouped_bar.json` | Reusable grouped bar chart template. |
| `configs/plot_recipes/dual_axis/temperature_vs_carrier_mobility_dual.json` | Dual-line Hall carrier concentration and mobility template. |

## Overriding A Recipe From CLI

You can use a recipe as a template and override some fields:

```bash
python main.py flexible \
  --recipe configs/flexible_plot_demos/temperature_seebeck_line.json \
  --data data/demo/flexible_plotting/messy_te_temperature_series.csv \
  --stem quick_override_seebeck \
  --formats png \
  --no-show
```

Override x/y columns:

```bash
python main.py flexible \
  --recipe configs/flexible_plot_demos/temperature_seebeck_line.json \
  --x "Temp / K" \
  --y "S (uV/K)" \
  --stem quick_override_columns \
  --no-show
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

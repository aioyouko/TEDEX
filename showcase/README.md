# TEDEX Agent Showcase Gallery (`showcase/`)

本目录独立收录并整理了 **TEDEX 1.5.0 AI Agent Harness** 的 **8 大代表性实战案例**（已彻底脱敏、剔除本地绝对路径与组内未发表私有数据），覆盖从经典体相热电变温输运、霍尔与单抛物带（SPB）分析、窄带隙/双带/笼状声子高级物理建模、原位变温 XRD 结构精修、20+ 种通用科研图库到热电发电/帕尔贴制冷器件表征的全链路，专供个人主页、课题组网站或项目文档展示直接调用。

## 目录结构与网页接入方式

- **`showcase_manifest.json`**：面向前端框架（Next.js / Astro / React / Vue）的结构化数据源。包含每个案例的中英文标题、自然语言 Prompt、调用的 Skills、Agent 亮点、CLI 命令、核心定量指标卡片以及 SVG/PNG/CSV/JSON 的相对路径，直接将该 `showcase/` 文件夹拷入网站 `public/showcase/` 即可渲染。
- **`preview.html`**：零依赖单文件静态网页预览（内嵌完整数据，支持双击直接在本地浏览器打开，无 CORS 跨域限制，也可直接复用其卡片排版与样式）。
- **`assets/tedex_evolution_roadmap.svg`**：TEDEX 架构演进与软件/数据解耦矢量图。
- **`cases/01..08_*/`**：每个案例相互独立，均包含 `case.md`、`data/`、高清矢量 `figures/`（全部采用图内自适应无碰撞图例布局 `.svg` + `.png`），以及对应的 `recipes/` 或 `summaries/` / `reports/`。

## 8 大 Agent 案例总览

| # | 案例目录 | 材料体系与主题 | 调用的 Skills | 代表产物 |
| :---: | --- | --- | --- | --- |
| `01` | [`01_pbse_nonparabolic_skb_vs_spb`](./cases/01_pbse_nonparabolic_skb_vs_spb/case.md) | **PbSe 窄带隙非抛物单 Kane 带（SKB）与单抛物带（SPB）多温区对比** (n-type PbSe (303–723 K)) | `te-physics-models`, `te-plotting` | 4 张矢量 SVG/PNG + 数据与报告 |
| `02` | [`02_mg3bi2_semimetal_bipolar_suite`](./cases/02_mg3bi2_semimetal_bipolar_suite/case.md) | **Mg3+δBi2-xSbx 半金属—窄带隙半导体跨相区双带输运反演与全局拟合** (Mg3.2Bi2-xSbxTex (x = 0, 0.3, 0.5; 100–350 K)) | `te-physics-models` | 4 张矢量 SVG/PNG + 数据与报告 |
| `03` | [`03_bi2sbte3_two_band_convergence`](./cases/03_bi2sbte3_two_band_convergence/case.md) | **p-Bi0.5Sb1.5Te3 双价带收敛与多模型（SPB / SKB / Two-Band）基准对比** (p-type Bi2-xSbxTe3 (x = 0.75, 300–500 K)) | `te-physics-models`, `te-plotting` | 5 张矢量 SVG/PNG + 数据与报告 |
| `04` | [`04_callaway_cryogenic_rattler_phonon`](./cases/04_callaway_cryogenic_rattler_phonon/case.md) | **4–300 K 晶格热导率 Debye–Callaway 局域共振散射与低温比热玻色峰解析** (Rattler Chalcogenide / Cage-like Thermoelectric (4–300 K)) | `te-physics-models` | 4 张矢量 SVG/PNG + 数据与报告 |
| `05` | [`05_xrd_structural_and_vt_suite`](./cases/05_xrd_structural_and_vt_suite/case.md) | **多模态结构表征：原位变温 XRD 相变热图、Rietveld 精修与微观应变解析** (Chalcopyrite CuIn1-xGaxTe2 – ZnSe (300–750 K)) | `te-xrd` | 6 张矢量 SVG/PNG + 数据与报告 |
| `06` | [`06_sciplot_20kind_scientific_gallery`](./cases/06_sciplot_20kind_scientific_gallery/case.md) | **sciplot 通用科研图表引擎：20+ 种多维相图、统计与机器学习诊断图库** (Cross-system thermoelectric screening, ML & device characterization) | `te-plotting` | 6 张矢量 SVG/PNG + 数据与报告 |
| `07` | [`07_classical_te_transport_and_spb_suite`](./cases/07_classical_te_transport_and_spb_suite/case.md) | **经典热电材料变温输运、霍尔表征与单抛物带（SPB）全流程解析** (p→n Chalcogenide Series, Cu2Se (300/750 K) & Cu2(S,Se,Te) (900 K)) | `te-plotting`, `te-physics-models` | 6 张矢量 SVG/PNG + 数据与报告 |
| `08` | [`08_te_device_power_and_peltier_cooling`](./cases/08_te_device_power_and_peltier_cooling/case.md) | **热电器件服役表征：发电器件（TEG）输出功率/效率与帕尔贴制冷（TEC）性能图谱** (Multi-ΔT TEG Power & Peltier TEC Cooling Modules) | `te-plotting` | 4 张矢量 SVG/PNG + 数据与配方 |

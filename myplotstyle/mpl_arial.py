import matplotlib.pyplot as plt

plt.rcParams.update({
    'font.sans-serif': 'Arial',
    'mathtext.fontset': 'custom',
    'lines.linewidth': 1,
    'lines.markersize': 5,
    'axes.linewidth': 1,
    'xtick.direction': 'in',
    'xtick.major.width': 1,
    'xtick.minor.width': 1,
    'xtick.major.size': 6,
    'xtick.minor.size': 4,
    'ytick.direction': 'in',
    'ytick.major.width': 1,
    'ytick.minor.width': 1,
    'ytick.major.size': 6,
    'ytick.minor.size': 4,
    'xtick.minor.visible': True,
    'ytick.minor.visible': True,
    'font.size': 16,
    'font.weight': 'normal',
    'axes.labelpad': 10
})

fonts = {
    'font1': {'size': 12, 'fontname': 'Arial'},
    'font2': {'size': 14, 'fontname': 'Arial'},
    'font3': {'size': 20},
    'font4': {'size': 30, 'font.weight': 'normal'},
}

color_list_main = [
    '#d62728',  # 红
    '#1f77b4',  # 蓝
    '#2ca02c',  # 绿
    '#9467bd',  # 紫
    '#ff7f0e',  # 橙
    '#8c564b',  # 棕
    '#e377c2',  # 粉
    '#7f7f7f',  # 灰
    '#17becf',  # 青
    '#bcbd22',  # 橄榄
    '#000000',  # 黑
    '#393b79',  # 深蓝紫
    '#637939',  # 深橄榄
    '#8c6d31',  # 金棕
    '#843c39',  # 深红棕
    '#7b4173',  # 梅紫
    '#3182bd',  # 中蓝
    '#31a354',  # 中绿
    '#756bb1',  # 中紫
    '#e6550d',  # 深橙
    '#9c9ede',  # 浅蓝紫
    '#8ca252',  # 浅橄榄
    '#bd9e39',  # 金色
    '#ad494a',  # 柔红
]

marker_list_main = [
    'o',  # 圆圈
    's',  # 方块
    'D',  # 菱形
    '^',  # 上三角
    'v',  # 下三角
    '<',  # 左三角
    '>',  # 右三角
    '*',  # 五角
    'p',  # 正五边形
    'P',  # 加号填充
    'X',  # X 填充
    'h',  # 六边形1
    'H',  # 六边形2
    '8',  # 八边形
    'd',  # 小菱形
]

color_list_compare = [
    '#a6bddb',  # 浅蓝
    '#fdbe85',  # 浅橙
    '#a1d99b',  # 浅绿
    '#fc9272',  # 浅红
    '#bcbddc',  # 浅紫
    '#d9d9d9',  # 浅灰
    '#fdd0a2',  # 米黄
    '#bdbdbd',  # 更浅灰
    '#9ecae1',  # 天蓝
    '#c7e9c0',  # 浅绿
    '#fdae6b',  # 杏橙
    '#dadaeb',  # 淡紫
    '#bcbddc',  # 紫灰
    '#c6dbef',  # 淡蓝
    '#e7ba52',  # 柔金
    '#e7969c',  # 柔红
    '#cedb9c',  # 柔橄榄
    '#de9ed6',  # 柔粉紫
    '#b5cf6b',  # 黄绿
    '#6baed6',  # 蓝
    '#74c476',  # 绿
    '#9e9ac8',  # 紫
    '#fdd0a2',  # 浅橙2
]

marker_list_compare = [
    'p',  # 正五边形
    '*',  # 五角
    '>',  # 右三角
    '<',  # 左三角
    'v',  # 下三角
    '^',  # 上三角
    'D',  # 菱形
    's',  # 方块
    'o',  # 圆圈
    'P',  # 加号填充
    'X',  # X 填充
    'h',  # 六边形1
    'H',  # 六边形2
    '8',  # 八边形
    'd',  # 小菱形

]

import matplotlib.pyplot as plt

plt.rcParams.update({
    'font.sans-serif': 'Times New Roman',
    'mathtext.fontset': 'stix',
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
    'font1': {'size': 12, 'fontname': 'Times New Roman'},
    'font2': {'size': 14, 'fontname': 'Times New Roman'},
    'font3': {'size': 20},
    'font4': {'size': 30, 'font.weight': 'normal'},
}

color_list = [
    '#2d5b8e', '#ec0000',  '#feba12', '#34bb66',
    '#5b5b8e', '#8e8e8e', '#ff5b5b', '#5b8ec5', '#c55b00',
    '#7f3c8d', '#11a579', '#3969ac', '#f2b701', '#e73f74',
    '#80ba5a', '#e68310', '#008695', '#cf1c90', '#f97b72',
    '#4b4b8f', '#a5aa99', '#984ea3', '#999933'
]

marker_list = [
    'o',   # 圆圈
    's',   # 方块
    'D',   # 菱形
    '^',   # 上三角
    'v',   # 下三角
    '<',   # 左三角
    '>',   # 右三角
    '*',   # 五角
    'p',   # 正五边形
    'P',   # 加号填充
    'X',   # X填充
    'h',   # 六边形1
    'H',   # 六边形2
    '8',   # 八边形
    'd',   # 小菱形
]

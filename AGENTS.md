## Imported Claude Cowork project instructions

## 样品性能比较

- 对比 CHY 样品性能时，先查询 `data/lab/lab_metadata.md` 中对应样品的 `density`、`cp_value`、制备/退火条件和备注。用户要求将密度作为判断压制致密程度和批次差异的依据。
- 同名义成分的比较应同时核对密度，讨论电导率和热导率差异时考虑致密程度的影响。有可靠理论密度时可计算相对密度；只有实测密度时做同成分间的相对比较，不直接给出致密度百分比。
- Markdown 中成分或工艺字段为空时，结合原始样品列表及用户已确认的信息核对；不将空白或旧标签当作已确认条件。

## Running the tools

- Launch tools through `python main.py <command>`; `python main.py --help` lists them.
- Always name the batches (or pass `--all`). `analyze`, `plot-te`, `assess`, and `agent` have no default batch and stop with an error when none is given.
- Put `--json` before the command (`python main.py --json assess CHY-1048`) to get one JSON object on stdout with the exit code and every file the command wrote. Read results from those paths instead of parsing console output.
- Don't run two `analyze` jobs at the same time: each one rewrites `data/lab/*.json` and `data/lab/lab_metadata.md`.

import os
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from te_analysis.agents.core_agent import analyze_materials_data
from te_analysis.paths import get_workspace

# Set MOONSHOT_API_KEY in your shell or .env file. Do not hardcode API keys here.

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def load_extracted_features(batch_id):
    """
    读取该批次之前提取好的数据特征。
    """
    ws = get_workspace()
    feature_path = ws.processed_batch_dir(batch_id) / "extracted_features.json"

    if feature_path.exists():
        with feature_path.open('r', encoding='utf-8') as f:
            return json.load(f)
    else:
        logging.warning(f"⚠️ 找不到 {batch_id} 的提取特征 ({feature_path})。")
        logging.warning("请确认 analyze 是否将特征数据保存为了 JSON 文件。")
        return None

def execute_agent_analysis(batch_configs):
    if not batch_configs:
        return

    print(f"\n🤖 Agent 分析任务启动，共准备分析 {len(batch_configs)} 个批次...\n")

    for batch_id, matrix_material in batch_configs.items():
        print(f"{'='*50}")
        print(f"▶️ 正在分析批次: {batch_id} | 🧬 基体材料: {matrix_material}")
        print(f"{'='*50}")

        # 1. 加载该批次的特征数据
        # 注意：如果你的 main.py 没有保存 JSON，你可能需要在这里调用 main.py 里的特征提取函数来实时生成 features
        features = load_extracted_features(batch_id)
        if not features:
            continue

        # 2. 🌟 核心操作：将“基体材料”直接注入到特征字典中！
        features["base_matrix_material"] = matrix_material

        # 3. 召唤 Agent 进行机理分析
        report = analyze_materials_data(features)

        # 4. 在控制台打印报告
        print(f"\n================ 【{batch_id}】机理分析报告 ================\n")
        print(report)

        # 5. 将报告持久化保存为 Markdown 文件，方便以后查阅
        report_dir = str(get_workspace().reports_dir)
        os.makedirs(report_dir, exist_ok=True)
        report_path = os.path.join(report_dir, f"{batch_id}_Analysis.md")
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n✅ 报告已生成并保存至: {report_path}\n")


def build_parser():
    import argparse

    p = argparse.ArgumentParser(description="Run AI agent mechanistic analysis on extracted batch features.")
    p.add_argument("batches", nargs="*", help="Batch IDs (e.g. TE-101) or extracted_features.json paths.")
    p.add_argument("--matrix", default="", help="Optional matrix material formula override.")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    ws = get_workspace()
    if not args.batches:
        targets = {b: args.matrix for b in ws.default_batches}
    else:
        targets = {}
        for item in args.batches:
            p = Path(item)
            if p.suffix.lower() == ".json" and p.exists():
                batch_id = p.parent.name.removesuffix("-processed")
                targets[batch_id] = args.matrix
            else:
                targets[item] = args.matrix
    execute_agent_analysis(targets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

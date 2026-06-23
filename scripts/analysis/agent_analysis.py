import os
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.core_agent import analyze_materials_data

# Set MOONSHOT_API_KEY in your shell or .env file. Do not hardcode API keys here.

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def load_extracted_features(batch_id):
    """
    读取该批次之前提取好的数据特征。
    假设你的 main.py 在清洗数据后，把浓缩的特征存成了 JSON。
    """
    feature_path = os.path.join("data", "processed", f"{batch_id}-processed", "extracted_features.json")
    
    if os.path.exists(feature_path):
        with open(feature_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        logging.warning(f"⚠️ 找不到 {batch_id} 的提取特征 ({feature_path})。")
        logging.warning("请确认 main.py 是否将特征数据保存为了 JSON 文件。")
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
        report_dir = os.path.join("results", "reports")
        os.makedirs(report_dir, exist_ok=True)
        report_path = os.path.join(report_dir, f"{batch_id}_Analysis.md")
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n✅ 报告已生成并保存至: {report_path}\n")

if __name__ == "__main__":
    
    # 🌟 在这里配置你想跑的 batch，以及它们对应的“基体材料”
    # 格式：{"batch名字": "基体材料名"}
    my_batches_to_analyze = {
        "CHY-1040": "Cu0.8Ag0.2In0.5Ga0.5Te2",   
        "CHY-1038": "Cu0.8Ag0.2In0.5Ga0.5Te2",
    }
    
    execute_agent_analysis(my_batches_to_analyze)

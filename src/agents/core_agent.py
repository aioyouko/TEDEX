# src/agents/core_agent.py
import os
import json
import logging
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

# 引入抽离出来的 Prompt
from src.agents.prompts import TE_EXPERT_SYSTEM_PROMPT, TE_ASSESSMENT_SYSTEM_PROMPT

def analyze_materials_data(extracted_features: dict) -> str:
    """
    调用大模型对提取的热电特征进行机理分析。
    """
    api_key = os.getenv("MOONSHOT_API_KEY")
    if not api_key:
        error_msg = "⚠️ 未找到 API Key。请在环境变量中设置 MOONSHOT_API_KEY。"
        logging.error(error_msg)
        return error_msg

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.moonshot.cn/v1")

    # 构造 User Prompt
    user_prompt = f"请分析以下批次的热电材料特征数据：\n\n{json.dumps(extracted_features, indent=2, ensure_ascii=False)}"

    logging.info("🧠 正在等待 Agent 深度思考...")
    try:
        response = client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=[
                # 直接在这里使用导入的变量
                {"role": "system", "content": TE_EXPERT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=1500
        )
        return response.choices[0].message.content
        
    except Exception as e:
        error_msg = f"❌ Agent 分析时发生错误: {str(e)}"
        logging.error(error_msg)
        return error_msg

# 测试运行块...


def assess_materials_performance(assessment_payload: dict) -> str:
    """
    Call the model for evidence-grounded self-assessment and next-step feedback.

    The payload is expected to come from assess_selected_batches.py. The local
    script performs deterministic scoring first; this function adds the AI
    interpretation layer.
    """
    api_key = os.getenv("MOONSHOT_API_KEY")
    if not api_key:
        error_msg = "⚠️ 未找到 API Key。请在环境变量中设置 MOONSHOT_API_KEY。"
        logging.error(error_msg)
        return error_msg

    client = OpenAI(api_key=api_key, base_url="https://api.moonshot.cn/v1")
    user_prompt = (
        "Please assess the selected thermoelectric batches from this payload. "
        "Keep evidence sources explicit.\n\n"
        f"{json.dumps(assessment_payload, indent=2, ensure_ascii=False)}"
    )

    logging.info("🧠 正在等待 Agent 进行证据化评估...")
    try:
        response = client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=[
                {"role": "system", "content": TE_ASSESSMENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1800,
        )
        return response.choices[0].message.content

    except Exception as e:
        error_msg = f"❌ Agent 评估时发生错误: {str(e)}"
        logging.error(error_msg)
        return error_msg

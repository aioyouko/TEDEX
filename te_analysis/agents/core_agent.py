"""LLM interpretation layer for thermoelectric analysis results.

Both entry points send a JSON payload to an OpenAI-compatible chat endpoint
(Moonshot) and return the model's Markdown reply. Every failure raises
AgentError, so a caller can always tell a failed call from a report.
"""

from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

from te_analysis.agents.prompts import TE_ASSESSMENT_SYSTEM_PROMPT, TE_EXPERT_SYSTEM_PROMPT

load_dotenv()

API_KEY_ENV_VAR = "MOONSHOT_API_KEY"
BASE_URL = "https://api.moonshot.cn/v1"
MODEL = "moonshot-v1-8k"
TEMPERATURE = 0.2


class AgentError(RuntimeError):
    """The model call did not produce a report."""


def _complete(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    api_key = os.getenv(API_KEY_ENV_VAR)
    if not api_key:
        raise AgentError(f"{API_KEY_ENV_VAR} is not set. Add it to .env or the environment.")

    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=TEMPERATURE,
            max_tokens=max_tokens,
        )
    except Exception as error:  # the SDK raises many error types; report them all the same way
        raise AgentError(f"Model call failed: {error}") from error

    content = response.choices[0].message.content if response.choices else None
    if not content or not content.strip():
        raise AgentError("Model returned an empty reply.")
    return content


def analyze_materials_data(extracted_features: dict) -> str:
    """Return a Markdown mechanism analysis of one batch's extracted features.

    The payload should carry ``base_matrix_material``; the system prompt asks
    the model to explain every trend against that matrix. Raises AgentError.
    """
    user_prompt = (
        "请分析以下批次的热电材料特征数据：\n\n"
        f"{json.dumps(extracted_features, indent=2, ensure_ascii=False)}"
    )
    logging.info("Waiting for the mechanism-analysis model reply...")
    return _complete(TE_EXPERT_SYSTEM_PROMPT, user_prompt, max_tokens=1500)


def assess_materials_performance(assessment_payload: dict) -> str:
    """Return an evidence-grounded assessment and next-step feedback.

    The payload is expected to come from assess_selected_batches.py, which
    does the deterministic scoring first; this adds the AI interpretation
    layer. Raises AgentError.
    """
    user_prompt = (
        "Please assess the selected thermoelectric batches from this payload. "
        "Keep evidence sources explicit.\n\n"
        f"{json.dumps(assessment_payload, indent=2, ensure_ascii=False)}"
    )
    logging.info("Waiting for the assessment model reply...")
    return _complete(TE_ASSESSMENT_SYSTEM_PROMPT, user_prompt, max_tokens=1800)

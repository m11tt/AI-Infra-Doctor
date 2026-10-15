"""LLM 客户端。

通过 OpenAI 兼容接口调用任意大模型服务，不绑定具体厂商。
所有支持 OpenAI 兼容协议的服务商（OpenAI / MiniMax / DeepSeek / 通义 / 本地推理框架等）
都可以只改环境变量来切换，业务代码一行都不用动。

配置全部来自环境变量，不写死在代码里：

    AI_API_KEY    模型服务的 API Key
    AI_BASE_URL   OpenAI 兼容接口地址，例如 https://example.com/v1
    AI_MODEL      模型名称

安全约定：
    - 代码里不出现任何 API Key
    - API Key 只从环境变量读取，不写进 Prompt
    - 错误信息只报告环境变量名和异常类型，绝不包含 API Key 的值

本模块只做"分析和建议"，不执行任何系统操作。
"""

import json
import logging
import os

import httpx

from ai.advisor import build_diagnosis_prompt

# 请求模型服务的超时时间（秒）。设上限避免调用方永久卡住。
DEFAULT_TIMEOUT = 30.0

# 模型返回结果必须包含的字段。
REQUIRED_FIELDS = ["summary", "root_cause", "risk", "recommendations"]

# 必须是字符串的字段。
TEXT_FIELDS = ["summary", "root_cause", "risk"]

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用或返回解析失败。

    用它替代裸异常，保证上层能区分"LLM 相关失败"和"程序 bug"。
    """


def _load_config() -> tuple:
    """读取并校验环境变量配置。

    返回:
        tuple: (api_key, base_url, model)，其中 base_url 已去掉末尾斜杠。
    """
    api_key = os.getenv("AI_API_KEY", "").strip()
    base_url = os.getenv("AI_BASE_URL", "").strip()
    model = os.getenv("AI_MODEL", "").strip()

    missing = []
    if not api_key:
        missing.append("AI_API_KEY")
    if not base_url:
        missing.append("AI_BASE_URL")
    if not model:
        missing.append("AI_MODEL")

    if missing:
        # 只报告缺失的变量名，不涉及任何变量的值。
        raise LLMError(
            "缺少必要的环境变量：" + ", ".join(missing) + "。请先配置后再调用 LLM。"
        )

    return api_key, base_url.rstrip("/"), model


def ask_llm(prompt: str) -> str:
    """把 Prompt 发给大模型，返回模型生成的文本。

    参数:
        prompt (str): 完整的 Prompt 文本。

    返回:
        str: 模型生成的原始文本（通常是 JSON 字符串）。

    异常:
        LLMError: 配置缺失、请求失败、返回异常或返回空内容时抛出。
    """
    api_key, base_url, model = _load_config()

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        # 要求服务端保证返回合法 JSON 对象。
        # OpenAI / DeepSeek 等主流兼容服务都支持该字段；不支持的服务
        # 通常直接忽略它，此时仍由 parse_ai_response 的围栏剥离兜底。
        "response_format": {"type": "json_object"},
    }

    try:
        response = httpx.post(
            url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise LLMError(
            f"模型服务返回错误状态码 {e.response.status_code}。"
        ) from e
    except httpx.HTTPError as e:
        # 只取异常类型名（如 ConnectError / ReadTimeout），不取异常文本，
        # 避免任何形式的信息泄漏。
        raise LLMError(f"请求模型服务失败：{type(e).__name__}。") from e

    try:
        data = response.json()
        text = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LLMError("模型返回的内容不是预期的 OpenAI 兼容格式。") from e

    if not isinstance(text, str) or not text.strip():
        raise LLMError("模型返回了空内容，视为调用失败。")

    return text


def _strip_code_fence(text: str) -> str:
    """剥掉模型常见的 markdown 代码块包裹。

    对话型模型即使被要求"只返回 JSON"，也经常输出成：

        ```json
        {"summary": "..."}
        ```

    这段围栏不是模型答案的一部分，但会让 json.loads 直接失败。
    这里把首尾的 ```json / ``` 围栏和空白去掉，
    只对"整段被围栏包住"的情况生效，不碰正文里合法的 JSON。
    """
    stripped = text.strip()

    # 必须成对出现：以 ``` 开头且以 ``` 结尾，才算被完整包裹。
    if not (stripped.startswith("```") and stripped.endswith("```")):
        return stripped

    # 去掉开头的 ``` 及其后可选的语言标记（json / JSON / 其他单词）。
    body = stripped[3:]
    newline = body.find("\n")
    if newline == -1:
        # 没有换行说明不是正常的围栏结构，原样返回交给后续解析报错。
        return stripped
    body = body[newline + 1:]

    # 去掉结尾的 ```。
    body = body.rstrip()
    if body.endswith("```"):
        body = body[:-3]

    return body.strip()


def parse_ai_response(response: str) -> dict:
    """把模型返回的 JSON 文本解析成结构化字典。

    本阶段只做基本 JSON 解析和字段检查，不做自动修复。

    参数:
        response (str): 模型返回的原始文本。

    返回:
        dict: 解析后的结果，包含 summary / root_cause / risk / recommendations。

    异常:
        LLMError: 内容为空、不是合法 JSON、顶层不是对象、缺少必要字段，
                  或字段类型不对时抛出。
    """
    if not isinstance(response, str) or not response.strip():
        raise LLMError("模型返回了空内容，无法解析。")

    # 先剥掉可能的 markdown 代码块围栏，再按纯 JSON 解析。
    cleaned = _strip_code_fence(response)

    try:
        data = json.loads(cleaned)
    except ValueError as e:
        raise LLMError("模型返回的内容不是合法 JSON。") from e

    if not isinstance(data, dict):
        raise LLMError("模型返回的 JSON 顶层不是对象。")

    for field in REQUIRED_FIELDS:
        if field not in data:
            raise LLMError(f"模型返回结果缺少必要字段：{field}")

    for field in TEXT_FIELDS:
        if not isinstance(data[field], str):
            raise LLMError(f"字段 {field} 必须是字符串。")

    if not isinstance(data["recommendations"], list):
        raise LLMError("字段 recommendations 必须是列表。")

    return data


def _fallback_result(error_message: str) -> dict:
    """构造降级结果。调用失败时用它保证项目不崩。"""
    return {
        "summary": "AI 诊断暂时不可用",
        "root_cause": "",
        "risk": "",
        "recommendations": [],
        "fallback": True,
        "error": error_message,
    }


def generate_ai_diagnosis(
    metrics: dict,
    anomalies: list,
    diagnoses: list,
    correlation_findings: list = None,
) -> dict:
    """AI 诊断完整流程：构造 Prompt → 调用 LLM → 解析结果。

    参数:
        metrics (dict):    系统指标
        anomalies (list):  检测到的异常
        diagnoses (list):  规则得出的基础诊断
        correlation_findings (list): 多指标关联发现。
                          可选，默认 None；只做透传，不在本层做任何判断。

    返回:
        dict: 成功时包含 summary / root_cause / risk / recommendations / fallback=False；
              失败时返回降级结果，fallback=True 且附带 error 说明。

    说明:
        调用失败会返回降级结果而不是抛出异常，但 fallback 字段会明确标记
        这次没有拿到真正的 AI 输出，调用方和用户都能看出来，不会伪装成功。
    """
    try:
        prompt = build_diagnosis_prompt(
            metrics, anomalies, diagnoses, correlation_findings
        )
        raw_text = ask_llm(prompt)
        result = parse_ai_response(raw_text)
    except LLMError as e:
        logger.warning("AI 诊断失败，已降级：%s", e)
        return _fallback_result(str(e))
    except Exception as e:
        # 兜底：任何意外错误都不让整个项目崩掉。
        # 同样只记录异常类型名，且通过 fallback=True 明确暴露"这不是真实 AI 结果"。
        logger.exception("AI 诊断出现未预期错误，已降级")
        return _fallback_result(f"未预期的错误：{type(e).__name__}")

    return {**result, "fallback": False}

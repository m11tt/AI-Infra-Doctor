"""LLM 客户端测试。

全部使用 mock，不访问互联网，也不需要任何真实 API Key。

两条安全网在文件级别兜底：
    - clean_env 清空 AI_* 环境变量，保证测试不依赖也不泄漏真实 Key
    - block_network 把 httpx.post 换成"一调用就失败"的哨兵，
      任何测试如果不小心发出真实网络请求会立刻暴露
需要模拟成功响应的测试，用 mock_ask 显式覆盖这个哨兵。
"""

import io
import json
import logging

import httpx
import pytest

from ai import client
from ai.client import (
    LLMError,
    ask_llm,
    generate_ai_diagnosis,
    parse_ai_response,
)

# 测试用的假配置。值是随便编的，不对应任何真实服务。
FAKE_KEY = "test-key-not-real"
FAKE_BASE_URL = "https://fake-llm.example.com/v1"
FAKE_MODEL = "fake-model"

VALID_RESPONSE = {
    "summary": "CPU 与内存同时接近满载",
    "root_cause": "训练任务并发过高导致资源争抢",
    "risk": "持续高负载可能导致任务失败或系统无响应",
    "recommendations": ["降低 batch size", "限制并发数"],
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """清空 AI_* 环境变量，测试绝不能依赖真实配置。"""
    for name in ["AI_API_KEY", "AI_BASE_URL", "AI_MODEL"]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """默认拦截一切网络请求。测试若需要响应请自行覆盖。"""

    def _forbidden(*args, **kwargs):
        raise AssertionError("测试不应访问互联网")

    monkeypatch.setattr(httpx, "post", _forbidden)


def set_config(monkeypatch, key=FAKE_KEY, base_url=FAKE_BASE_URL, model=FAKE_MODEL):
    """写入假的 AI_* 配置。"""
    if key is not None:
        monkeypatch.setenv("AI_API_KEY", key)
    if base_url is not None:
        monkeypatch.setenv("AI_BASE_URL", base_url)
    if model is not None:
        monkeypatch.setenv("AI_MODEL", model)


def mock_ask(monkeypatch, text):
    """把 httpx.post 替换成返回一个固定内容的假响应。"""
    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        captured["headers"] = headers
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": text}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", _fake_post)
    return captured


# ---------- 1. 缺少 API Key ----------


def test_missing_api_key_raises_clear_error(monkeypatch) -> None:
    """缺少 API Key 时应给出清晰的错误，而不是难懂的 traceback。"""
    set_config(monkeypatch)
    monkeypatch.delenv("AI_API_KEY", raising=False)

    with pytest.raises(LLMError) as exc:
        ask_llm("测试")

    message = str(exc.value)
    assert "AI_API_KEY" in message
    assert "缺少必要的环境变量" in message


def test_missing_all_config_lists_all_variable_names() -> None:
    """三个变量都缺失时应一次性全部报出。"""
    with pytest.raises(LLMError) as exc:
        ask_llm("测试")
    message = str(exc.value)
    assert "AI_API_KEY" in message
    assert "AI_BASE_URL" in message
    assert "AI_MODEL" in message


def test_error_message_never_contains_secret(monkeypatch) -> None:
    """配置缺失时的错误信息里不能出现任何密钥内容。"""
    set_config(monkeypatch)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    with pytest.raises(LLMError) as exc:
        ask_llm("测试")
    assert FAKE_KEY not in str(exc.value)


# ---------- 2. ask_llm 正常情况 ----------


def test_ask_llm_returns_model_text(monkeypatch) -> None:
    """正常情况下应返回模型生成的文本。"""
    set_config(monkeypatch)
    captured = mock_ask(monkeypatch, "这是模型返回的内容")

    result = ask_llm("你好")

    assert result == "这是模型返回的内容"
    assert captured["url"] == f"{FAKE_BASE_URL}/chat/completions"
    assert captured["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    assert captured["payload"]["model"] == FAKE_MODEL


def test_ask_llm_sends_prompt_as_user_message(monkeypatch) -> None:
    """Prompt 应作为 user 消息发送。"""
    set_config(monkeypatch)
    captured = mock_ask(monkeypatch, "ok")

    ask_llm("我的 Prompt 内容")

    messages = captured["payload"]["messages"]
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "我的 Prompt 内容"


def test_ask_llm_never_sends_api_key_in_prompt(monkeypatch) -> None:
    """API Key 只能出现在请求头，绝不能出现在 Prompt 正文里。"""
    set_config(monkeypatch)
    captured = mock_ask(monkeypatch, "ok")

    ask_llm("请分析系统状态")

    assert FAKE_KEY not in json.dumps(captured["payload"], ensure_ascii=False)
    assert FAKE_KEY in captured["headers"]["Authorization"]


def test_ask_llm_handles_base_url_with_trailing_slash(monkeypatch) -> None:
    """base_url 末尾多一个斜杠也不应产生双斜杠。"""
    set_config(monkeypatch, base_url=FAKE_BASE_URL + "/")
    captured = mock_ask(monkeypatch, "ok")

    ask_llm("测试")

    assert captured["url"] == f"{FAKE_BASE_URL}/chat/completions"


# ---------- 3. API 请求失败 ----------


def test_http_error_status_raises_llm_error(monkeypatch) -> None:
    """服务端返回错误状态码时应抛出 LLMError，并带上状态码。"""
    set_config(monkeypatch)

    def _fake_post(url, json=None, headers=None, timeout=None):
        return httpx.Response(401, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", _fake_post)

    with pytest.raises(LLMError) as exc:
        ask_llm("测试")
    assert "401" in str(exc.value)


def test_network_error_raises_llm_error(monkeypatch) -> None:
    """连不上服务时应抛出 LLMError，并给出异常类型。"""
    set_config(monkeypatch)

    def _fake_post(url, json=None, headers=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _fake_post)

    with pytest.raises(LLMError) as exc:
        ask_llm("测试")
    assert "ConnectError" in str(exc.value)


def test_network_error_message_hides_exception_text(monkeypatch) -> None:
    """网络异常的错误信息不应把原始异常文本直接抛出。"""
    set_config(monkeypatch)

    def _fake_post(url, json=None, headers=None, timeout=None):
        raise httpx.ConnectError("secret-host-internal-detail")

    monkeypatch.setattr(httpx, "post", _fake_post)

    with pytest.raises(LLMError) as exc:
        ask_llm("测试")
    assert "secret-host-internal-detail" not in str(exc.value)


# ---------- 4. 模型返回空字符串 ----------


def test_empty_content_raises_llm_error(monkeypatch) -> None:
    """模型返回空字符串应视为调用失败。"""
    set_config(monkeypatch)
    mock_ask(monkeypatch, "")

    with pytest.raises(LLMError) as exc:
        ask_llm("测试")
    assert "空内容" in str(exc.value)


def test_whitespace_content_raises_llm_error(monkeypatch) -> None:
    """模型只返回空白字符也应视为失败。"""
    set_config(monkeypatch)
    mock_ask(monkeypatch, "   \n  ")

    with pytest.raises(LLMError) as exc:
        ask_llm("测试")
    assert "空内容" in str(exc.value)


def test_unexpected_response_shape_raises_llm_error(monkeypatch) -> None:
    """返回结构不是 OpenAI 兼容格式时应抛出 LLMError。"""
    set_config(monkeypatch)

    def _fake_post(url, json=None, headers=None, timeout=None):
        return httpx.Response(
            200,
            json={"unexpected": "shape"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", _fake_post)

    with pytest.raises(LLMError) as exc:
        ask_llm("测试")
    assert "预期" in str(exc.value)


# ---------- 5~9. parse_ai_response ----------


def test_parse_valid_json_succeeds() -> None:
    """合法 JSON 应被正确解析。"""
    result = parse_ai_response(json.dumps(VALID_RESPONSE, ensure_ascii=False))

    assert result["summary"] == VALID_RESPONSE["summary"]
    assert result["recommendations"] == VALID_RESPONSE["recommendations"]


def test_parse_empty_string_raises() -> None:
    """空字符串应报错。"""
    with pytest.raises(LLMError):
        parse_ai_response("")


def test_parse_invalid_json_raises() -> None:
    """非法 JSON 应报错。"""
    with pytest.raises(LLMError) as exc:
        parse_ai_response("这不是 JSON")
    assert "合法 JSON" in str(exc.value)


def test_parse_non_dict_json_raises() -> None:
    """顶层是数组而不是对象时应报错。"""
    with pytest.raises(LLMError) as exc:
        parse_ai_response("[1, 2, 3]")
    assert "顶层" in str(exc.value)


def test_parse_missing_summary_raises() -> None:
    """缺少 summary 应报错。"""
    payload = dict(VALID_RESPONSE)
    del payload["summary"]

    with pytest.raises(LLMError) as exc:
        parse_ai_response(json.dumps(payload, ensure_ascii=False))
    assert "summary" in str(exc.value)


def test_parse_missing_root_cause_raises() -> None:
    """缺少 root_cause 应报错。"""
    payload = dict(VALID_RESPONSE)
    del payload["root_cause"]

    with pytest.raises(LLMError) as exc:
        parse_ai_response(json.dumps(payload, ensure_ascii=False))
    assert "root_cause" in str(exc.value)


def test_parse_missing_risk_raises() -> None:
    """缺少 risk 应报错。"""
    payload = dict(VALID_RESPONSE)
    del payload["risk"]

    with pytest.raises(LLMError) as exc:
        parse_ai_response(json.dumps(payload, ensure_ascii=False))
    assert "risk" in str(exc.value)


def test_parse_missing_recommendations_raises() -> None:
    """缺少 recommendations 应报错。"""
    payload = dict(VALID_RESPONSE)
    del payload["recommendations"]

    with pytest.raises(LLMError) as exc:
        parse_ai_response(json.dumps(payload, ensure_ascii=False))
    assert "recommendations" in str(exc.value)


def test_parse_recommendations_not_a_list_raises() -> None:
    """recommendations 不是列表时应报错。"""
    payload = dict(VALID_RESPONSE)
    payload["recommendations"] = "这是一个字符串"

    with pytest.raises(LLMError) as exc:
        parse_ai_response(json.dumps(payload, ensure_ascii=False))
    assert "列表" in str(exc.value)


def test_parse_non_string_summary_raises() -> None:
    """summary 不是字符串时应报错。"""
    payload = dict(VALID_RESPONSE)
    payload["summary"] = 123

    with pytest.raises(LLMError) as exc:
        parse_ai_response(json.dumps(payload, ensure_ascii=False))
    assert "summary" in str(exc.value)


# ---------- 10. generate_ai_diagnosis 正常流程 ----------


def sample_inputs() -> tuple:
    return (
        {
            "cpu_percent": 95.2,
            "memory_percent": 93.5,
            "disk_percent": 70.0,
            "network_sent_mb_per_sec": 1.2,
            "network_recv_mb_per_sec": 2.5,
        },
        [
            {
                "metric": "cpu_percent",
                "value": 95.2,
                "threshold": 90,
                "message": "CPU 使用率过高",
            }
        ],
        [{"type": "cpu", "message": "CPU 使用率过高，可能存在 CPU 计算负载较高"}],
    )


def test_generate_ai_diagnosis_happy_path(monkeypatch) -> None:
    """mock LLM 后应得到结构化诊断结果。"""
    set_config(monkeypatch)
    mock_ask(monkeypatch, json.dumps(VALID_RESPONSE, ensure_ascii=False))

    result = generate_ai_diagnosis(*sample_inputs())

    assert result["fallback"] is False
    assert result["summary"] == VALID_RESPONSE["summary"]
    assert result["root_cause"] == VALID_RESPONSE["root_cause"]
    assert result["risk"] == VALID_RESPONSE["risk"]
    assert result["recommendations"] == VALID_RESPONSE["recommendations"]
    assert "error" not in result


def test_generate_ai_diagnosis_sends_real_prompt(monkeypatch) -> None:
    """发出去的内容应该是 Stage 4A 构造的完整 Prompt。"""
    set_config(monkeypatch)
    captured = mock_ask(monkeypatch, json.dumps(VALID_RESPONSE, ensure_ascii=False))

    generate_ai_diagnosis(*sample_inputs())

    sent = captured["payload"]["messages"][0]["content"]
    assert "AI Infra 运维诊断助手" in sent
    assert "95.2" in sent
    assert "CPU 使用率过高" in sent


# ---------- 11. generate_ai_diagnosis 失败降级 ----------


def test_generate_ai_diagnosis_falls_back_when_no_key() -> None:
    """没有配置 API Key 时应返回降级结果，而不是抛异常。"""
    result = generate_ai_diagnosis(*sample_inputs())

    assert result["fallback"] is True
    assert result["summary"] == "AI 诊断暂时不可用"
    assert result["root_cause"] == ""
    assert result["risk"] == ""
    assert result["recommendations"] == []
    assert "AI_API_KEY" in result["error"]


def test_generate_ai_diagnosis_falls_back_on_request_failure(monkeypatch) -> None:
    """请求失败时应降级。"""
    set_config(monkeypatch)

    def _fake_post(url, json=None, headers=None, timeout=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", _fake_post)

    result = generate_ai_diagnosis(*sample_inputs())

    assert result["fallback"] is True
    assert "ConnectError" in result["error"]


def test_generate_ai_diagnosis_falls_back_on_bad_json(monkeypatch) -> None:
    """模型返回无法解析的内容时应降级。"""
    set_config(monkeypatch)
    mock_ask(monkeypatch, "这不是 JSON")

    result = generate_ai_diagnosis(*sample_inputs())

    assert result["fallback"] is True
    assert "合法 JSON" in result["error"]


def test_generate_ai_diagnosis_falls_back_on_missing_field(monkeypatch) -> None:
    """模型返回缺少必要字段时应降级。"""
    set_config(monkeypatch)
    mock_ask(monkeypatch, json.dumps({"summary": "只有 summary"}, ensure_ascii=False))

    result = generate_ai_diagnosis(*sample_inputs())

    assert result["fallback"] is True
    assert "root_cause" in result["error"]


def test_fallback_never_contains_api_key(monkeypatch) -> None:
    """降级结果里绝不能出现 API Key。"""
    set_config(monkeypatch)

    def _fake_post(url, json=None, headers=None, timeout=None):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", _fake_post)

    result = generate_ai_diagnosis(*sample_inputs())
    assert FAKE_KEY not in json.dumps(result, ensure_ascii=False)


# ---------- 12~13. 安全性与隔离 ----------


def test_client_module_has_no_hardcoded_key() -> None:
    """client.py 源码里不能出现任何看起来像密钥的字面量。"""
    source = open(client.__file__, encoding="utf-8").read()

    assert "sk-" not in source
    assert "AI_API_KEY=" not in source


def test_client_does_not_log_api_key(monkeypatch) -> None:
    """调用过程中 API Key 不应出现在任何日志输出里。"""
    set_config(monkeypatch)
    mock_ask(monkeypatch, "ok")

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    client.logger.addHandler(handler)
    try:
        ask_llm("测试")
    finally:
        client.logger.removeHandler(handler)

    assert FAKE_KEY not in stream.getvalue()


def test_client_does_not_use_shell_or_process() -> None:
    """禁止执行任何系统操作。"""
    source = open(client.__file__, encoding="utf-8").read()

    for forbidden in ["subprocess", "os.system", "shutil", "socket"]:
        assert forbidden not in source, f"client.py 不应使用 {forbidden}"


# ================================================================
# Stage 5C：关联发现透传到 advisor
# ================================================================


def sample_correlation_findings() -> list:
    return [
        {
            "type": "cpu_bottleneck",
            "severity": "high",
            "message": "可能存在 CPU 侧数据处理或任务调度瓶颈。",
        }
    ]


def test_generate_ai_diagnosis_legacy_call_unchanged(monkeypatch) -> None:
    """旧的三参数调用必须继续正常工作。"""
    set_config(monkeypatch)
    mock_ask(monkeypatch, json.dumps(VALID_RESPONSE, ensure_ascii=False))

    result = generate_ai_diagnosis(*sample_inputs())

    assert result["fallback"] is False
    assert result["summary"] == VALID_RESPONSE["summary"]


def test_generate_ai_diagnosis_passes_findings_to_prompt(monkeypatch) -> None:
    """关联发现应被带进发出去的 Prompt。"""
    set_config(monkeypatch)
    captured = mock_ask(monkeypatch, json.dumps(VALID_RESPONSE, ensure_ascii=False))

    generate_ai_diagnosis(*sample_inputs(), sample_correlation_findings())

    sent = captured["payload"]["messages"][0]["content"]
    assert "多指标关联发现" in sent
    assert "cpu_bottleneck" in sent
    assert "CPU 侧数据处理或任务调度瓶颈" in sent


def test_generate_ai_diagnosis_without_findings_omits_section(monkeypatch) -> None:
    """不传关联发现时，Prompt 里不应出现关联发现章节。"""
    set_config(monkeypatch)
    captured = mock_ask(monkeypatch, json.dumps(VALID_RESPONSE, ensure_ascii=False))

    generate_ai_diagnosis(*sample_inputs())

    sent = captured["payload"]["messages"][0]["content"]
    assert "cpu_bottleneck" not in sent


def test_generate_ai_diagnosis_fallback_unchanged_with_findings(monkeypatch) -> None:
    """传了关联发现时，LLM 失败仍按原样降级。"""
    set_config(monkeypatch)

    def _fake_post(url, json=None, headers=None, timeout=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", _fake_post)

    result = generate_ai_diagnosis(*sample_inputs(), sample_correlation_findings())

    assert result["fallback"] is True
    assert result["summary"] == "AI 诊断暂时不可用"
    assert result["recommendations"] == []
    assert "ConnectError" in result["error"]


def test_generate_ai_diagnosis_missing_key_fallback_unchanged() -> None:
    """没有配置 Key 时的降级行为不因新参数而改变。"""
    result = generate_ai_diagnosis(*sample_inputs(), sample_correlation_findings())

    assert result["fallback"] is True
    assert "AI_API_KEY" in result["error"]


# ---------- markdown 代码块包裹（真实模型高频输出） ----------


VALID_JSON = (
    '{"summary": "s", "root_cause": "r", "risk": "k", "recommendations": ["a"]}'
)


def test_parse_json_fence_is_stripped() -> None:
    """```json 围栏包裹的 JSON 应能正常解析。"""
    text = "```json\n" + VALID_JSON + "\n```"
    result = parse_ai_response(text)

    assert result["summary"] == "s"
    assert result["recommendations"] == ["a"]


def test_parse_bare_fence_is_stripped() -> None:
    """不带语言标记的 ``` 围栏也应能解析。"""
    text = "```\n" + VALID_JSON + "\n```"
    assert parse_ai_response(text)["summary"] == "s"


def test_parse_uppercase_json_fence_is_stripped() -> None:
    """语言标记大小写不敏感（```JSON）。"""
    text = "```JSON\n" + VALID_JSON + "\n```"
    assert parse_ai_response(text)["summary"] == "s"


def test_parse_fence_with_surrounding_whitespace() -> None:
    """围栏前后有多余空白和换行时仍应解析。"""
    text = "\n\n  ```json\n" + VALID_JSON + "\n```  \n\n"
    assert parse_ai_response(text)["summary"] == "s"


def test_plain_json_still_parses_after_strip_logic() -> None:
    """没有围栏的纯 JSON 必须保持不变，不能因剥离逻辑而破坏。"""
    assert parse_ai_response(VALID_JSON)["summary"] == "s"


def test_broken_json_inside_fence_still_raises() -> None:
    """围栏内内容不是合法 JSON 时仍应报错，不能静默放行。"""
    text = "```json\n{not json}\n```"
    with pytest.raises(LLMError):
        parse_ai_response(text)


def test_fence_only_does_not_crash() -> None:
    """只有围栏、没有内容时应报错而不是崩溃。"""
    with pytest.raises(LLMError):
        parse_ai_response("```json\n```")


def test_request_payload_asks_for_json_object() -> None:
    """请求体应声明 response_format=json_object，降低模型输出围栏的概率。"""
    import ai.client as client_module
    import inspect

    source = inspect.getsource(client_module.ask_llm)
    assert "response_format" in source
    assert "json_object" in source

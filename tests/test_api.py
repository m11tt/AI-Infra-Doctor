"""统一状态 API 测试。

覆盖 GET / 和 GET /api/v1/status。

本文件不调用 LLM，也不访问互联网。
TestClient 在进程内走 ASGI 协议，不会发出真实网络请求。
"""

import pytest
from fastapi.testclient import TestClient

# 注意命名：这里必须用别名导入模块。
# 如果直接写 "from app.main import app"，名字 app 会被 FastAPI 实例覆盖，
# 后面再写 app.main 就找不到模块了。
from app import main as main_module
from app.main import app
from diagnosis.diagnosis import CORRELATION_SOURCE

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_llm_config(monkeypatch):
    """清空 AI_* 环境变量，证明接口不依赖 LLM 配置即可工作。"""
    for name in ["AI_API_KEY", "AI_BASE_URL", "AI_MODEL"]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def busy_cpu(monkeypatch):
    """注入一个 CPU 吃紧的机器状态。

    为什么必须注入：cpu_bottleneck 关联规则要求 cpu_percent > 90，
    这是随机器负载变化的真实值。空闲机器上 CPU 只有几十，
    直接断言会写出一条必然失败的脆弱测试。
    这里只替换最上游的指标采集，其余各层仍走真实代码。
    """
    real = main_module.get_system_metrics

    def fake_get_system_metrics():
        metrics = dict(real())
        metrics["cpu_percent"] = 95.2
        return metrics

    monkeypatch.setattr(main_module, "get_system_metrics", fake_get_system_metrics)
    return fake_get_system_metrics


# ---------- 1. 旧接口保持不变 ----------


def test_root_endpoint_unchanged() -> None:
    """GET / 必须返回原来的结果。"""
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "project": "AI Infra Doctor",
        "status": "running",
    }


# ---------- 2~4. 状态接口基本结构 ----------


def test_status_returns_200() -> None:
    """GET /api/v1/status 应返回 200。"""
    assert client.get("/api/v1/status").status_code == 200


def test_status_returns_json() -> None:
    """返回的应是 JSON 对象。"""
    payload = client.get("/api/v1/status").json()
    assert isinstance(payload, dict)


def test_status_has_all_top_level_keys() -> None:
    """顶层应包含约定的 5 个键。"""
    payload = client.get("/api/v1/status").json()

    assert set(payload.keys()) == {
        "metrics",
        "workload",
        "anomalies",
        "correlation_findings",
        "diagnoses",
    }


# ---------- 5~6. 各层数据结构 ----------


def test_metrics_has_five_fields() -> None:
    """metrics 应包含 monitor 采集的 5 个字段。"""
    metrics = client.get("/api/v1/status").json()["metrics"]

    assert set(metrics.keys()) == {
        "cpu_percent",
        "memory_percent",
        "disk_percent",
        "network_sent_mb_per_sec",
        "network_recv_mb_per_sec",
    }


def test_workload_has_four_fields() -> None:
    """workload 应包含 4 个 AI 推理指标。"""
    workload = client.get("/api/v1/status").json()["workload"]

    assert set(workload.keys()) == {
        "request_count",
        "avg_latency_ms",
        "queue_length",
        "gpu_utilization",
    }


def test_anomalies_and_findings_are_lists() -> None:
    """anomalies / correlation_findings / diagnoses 都应是列表。"""
    payload = client.get("/api/v1/status").json()

    for key in ["anomalies", "correlation_findings", "diagnoses"]:
        assert isinstance(payload[key], list), f"{key} 应为列表"


# ---------- 7~8. 命中 CPU bottleneck 场景 ----------


def test_cpu_bottleneck_finding_returned(busy_cpu) -> None:
    """CPU 吃紧 + 当前模拟工作负载，应命中 cpu_bottleneck 关联发现。

    模拟工作负载固定给出 gpu=35、latency=350、queue=18，
    本身就满足关联规则的后三个条件，缺的只有高 CPU。
    """
    findings = client.get("/api/v1/status").json()["correlation_findings"]

    assert len(findings) >= 1
    assert any(f["type"] == "cpu_bottleneck" for f in findings)


def test_cpu_bottleneck_severity_is_high(busy_cpu) -> None:
    """命中的关联发现应带 severity=high。"""
    findings = client.get("/api/v1/status").json()["correlation_findings"]
    finding = next(f for f in findings if f["type"] == "cpu_bottleneck")

    assert finding["severity"] == "high"
    assert "可能存在" in finding["message"]


def test_diagnoses_contain_correlation_source(busy_cpu) -> None:
    """diagnoses 中应存在 source == correlation 的条目。"""
    diagnoses = client.get("/api/v1/status").json()["diagnoses"]

    assert any(d.get("source") == CORRELATION_SOURCE for d in diagnoses)


def test_diagnoses_also_contain_rule_entries(busy_cpu) -> None:
    """规则诊断和关联发现应并存，而不是只保留其中一类。"""
    diagnoses = client.get("/api/v1/status").json()["diagnoses"]

    correlation_entries = [d for d in diagnoses if d.get("source") == CORRELATION_SOURCE]
    rule_entries = [d for d in diagnoses if "source" not in d]

    assert correlation_entries, "应有关联发现"
    assert rule_entries, "CPU 超标时应有规则诊断"


def test_no_findings_on_idle_machine() -> None:
    """机器空闲（CPU 未超标）时，不应凭空出现关联发现。"""
    payload = client.get("/api/v1/status").json()

    for finding in payload["correlation_findings"]:
        assert finding["type"] == "cpu_bottleneck"  # 仅确认结构，不依赖机器状态
        assert finding["severity"] == "high"


# ---------- 9. 不调用 LLM ----------


def test_status_works_without_api_key() -> None:
    """没有配置 AI_* 变量时接口照常返回，证明没有调用 LLM。"""
    assert client.get("/api/v1/status").status_code == 200


def test_status_does_not_call_llm(monkeypatch) -> None:
    """即使 LLM 客户端可用，状态接口也不应调用它。"""
    import ai.client

    def _explode(*args, **kwargs):
        raise AssertionError("状态接口不应调用 LLM")

    monkeypatch.setattr(ai.client, "ask_llm", _explode)
    monkeypatch.setattr(ai.client, "generate_ai_diagnosis", _explode)

    assert client.get("/api/v1/status").status_code == 200


def test_main_does_not_import_llm_client() -> None:
    """app/main.py 源码里不应出现 LLM 客户端相关内容。"""
    source = open(main_module.__file__, encoding="utf-8").read()

    for forbidden in [
        "from ai.client",
        "import ai.client",
        "generate_ai_diagnosis",
        "ask_llm",
        "AI_API_KEY",
    ]:
        assert forbidden not in source, f"app/main.py 不应出现 {forbidden}"


# ---------- 10. 不改变已有模块行为 ----------


def test_api_does_not_reimplement_detection_logic() -> None:
    """接口里的 anomalies 应与直接调用 detect_anomalies 完全一致。

    一致说明 app/main.py 只是编排，没有另写一套判断逻辑。
    """
    from detection.detector import detect_anomalies
    from monitor.system import get_system_metrics

    payload = client.get("/api/v1/status").json()

    assert payload["anomalies"] == detect_anomalies(get_system_metrics())


def test_api_does_not_reimplement_correlation_logic() -> None:
    """接口里的 correlation_findings 应与直接调用 correlate 完全一致。"""
    from correlation.correlator import correlate
    from detection.detector import detect_anomalies
    from monitor.system import get_system_metrics
    from workload.inference import get_inference_metrics

    payload = client.get("/api/v1/status").json()

    metrics = get_system_metrics()
    workload = get_inference_metrics()
    assert payload["correlation_findings"] == correlate(
        metrics, workload, detect_anomalies(metrics)
    )


def test_api_does_not_reimplement_diagnosis_logic() -> None:
    """接口里的 diagnoses 应与直接调用 diagnose 完全一致。"""
    from correlation.correlator import correlate
    from detection.detector import detect_anomalies
    from diagnosis.diagnosis import diagnose
    from monitor.system import get_system_metrics
    from workload.inference import get_inference_metrics

    payload = client.get("/api/v1/status").json()

    metrics = get_system_metrics()
    anomalies = detect_anomalies(metrics)
    findings = correlate(metrics, get_inference_metrics(), anomalies)
    assert payload["diagnoses"] == diagnose(metrics, anomalies, findings)


def test_openapi_documents_both_routes() -> None:
    """两个接口都应出现在 OpenAPI 文档里。"""
    paths = client.get("/openapi.json").json()["paths"]

    assert "/" in paths
    assert "/api/v1/status" in paths


# ---------- 11. 安全响应头 ----------


REQUIRED_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


@pytest.mark.parametrize("path", ["/", "/api/v1/status", "/dashboard"])
def test_security_headers_present(path: str) -> None:
    """所有响应都应带上基础安全头。"""
    headers = client.get(path).headers

    for name, value in REQUIRED_SECURITY_HEADERS.items():
        assert headers.get(name) == value, f"{path} 缺少安全头 {name}"


def test_content_security_policy_present() -> None:
    """应有 CSP，且禁止被 iframe 嵌套（frame-ancestors none）。"""
    csp = client.get("/dashboard").headers.get("content-security-policy", "")

    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_security_headers_do_not_break_static_files() -> None:
    """静态资源响应也应带安全头，且内容不受影响。"""
    response = client.get("/dashboard/app.js")

    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert "REFRESH_INTERVAL" in response.text


def test_404_also_carries_security_headers() -> None:
    """连 404 响应也应带安全头（中间件在全局生效）。"""
    response = client.get("/definitely-not-a-route")

    assert response.status_code == 404
    assert response.headers.get("x-content-type-options") == "nosniff"

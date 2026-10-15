"""AI 诊断输入层测试。

覆盖 build_ai_context() 和 build_diagnosis_prompt()。
本文件不调用任何大模型，全部使用固定数据作为输入。
"""

import copy

import ai.advisor
from ai.advisor import build_ai_context, build_diagnosis_prompt

# advisor.py 不允许出现的第三方依赖。
# 这些都是具体的包名/厂商名，不会出现在 Prompt 正文里。
FORBIDDEN_TOKENS = [
    "openai",
    "anthropic",
    "deepseek",
    "minimax",
    "requests",
    "httpx",
    "api_key",
]

# advisor.py 不允许 import 的上游模块。
# 判据是"有没有 import 语句"，而不是"有没有提到这个名字"——
# docstring 里正常会说明数据来自哪些模块，按字面查会误报。
FORBIDDEN_IMPORTS = [
    "import monitor",
    "from monitor",
    "import detection",
    "from detection",
    "import diagnosis",
    "from diagnosis",
]


def sample_metrics() -> dict:
    return {
        "cpu_percent": 95.2,
        "memory_percent": 93.5,
        "disk_percent": 70.0,
        "network_sent_mb_per_sec": 1.2,
        "network_recv_mb_per_sec": 2.5,
    }


def sample_anomalies() -> list:
    return [
        {
            "metric": "cpu_percent",
            "value": 95.2,
            "threshold": 90,
            "message": "CPU 使用率过高",
        },
        {
            "metric": "memory_percent",
            "value": 93.5,
            "threshold": 90,
            "message": "内存使用率过高",
        },
    ]


def sample_diagnoses() -> list:
    return [
        {"type": "cpu", "message": "CPU 使用率过高，可能存在 CPU 计算负载较高"},
        {"type": "memory", "message": "内存使用率过高，可能存在内存资源紧张"},
        {
            "type": "system",
            "message": "CPU 和内存同时处于高负载状态，系统整体资源压力较大",
        },
    ]


# ---------- build_ai_context() ----------


def test_context_combines_three_parts() -> None:
    """应该正确组合 metrics + anomalies + diagnoses 三部分。"""
    context = build_ai_context(sample_metrics(), sample_anomalies(), sample_diagnoses())

    assert isinstance(context, dict)
    assert set(context.keys()) == {"metrics", "anomalies", "diagnoses"}
    assert context["metrics"]["cpu_percent"] == 95.2
    assert len(context["anomalies"]) == 2
    assert len(context["diagnoses"]) == 3


def test_context_does_not_modify_input_metrics() -> None:
    """调用后原始 metrics 不应被改变。"""
    metrics = sample_metrics()
    snapshot = copy.deepcopy(metrics)

    build_ai_context(metrics, sample_anomalies(), sample_diagnoses())

    assert metrics == snapshot


def test_context_does_not_modify_input_anomalies() -> None:
    """调用后原始 anomalies 不应被改变。"""
    anomalies = sample_anomalies()
    snapshot = copy.deepcopy(anomalies)

    build_ai_context(sample_metrics(), anomalies, sample_diagnoses())

    assert anomalies == snapshot


def test_context_does_not_modify_input_diagnoses() -> None:
    """调用后原始 diagnoses 不应被改变。"""
    diagnoses = sample_diagnoses()
    snapshot = copy.deepcopy(diagnoses)

    build_ai_context(sample_metrics(), sample_anomalies(), diagnoses)

    assert diagnoses == snapshot


def test_returned_context_is_independent_copy() -> None:
    """修改返回值不应影响原始数据。"""
    metrics = sample_metrics()
    context = build_ai_context(metrics, sample_anomalies(), sample_diagnoses())

    context["metrics"]["cpu_percent"] = 0
    context["anomalies"].clear()

    assert metrics["cpu_percent"] == 95.2
    assert len(sample_anomalies()) == 2


def test_context_handles_empty_inputs() -> None:
    """没有异常和诊断时也应正常返回结构。"""
    context = build_ai_context(sample_metrics(), [], [])

    assert context["anomalies"] == []
    assert context["diagnoses"] == []


# ---------- build_diagnosis_prompt() ----------


def test_prompt_returns_string() -> None:
    """Prompt 必须返回字符串。"""
    prompt = build_diagnosis_prompt(
        sample_metrics(), sample_anomalies(), sample_diagnoses()
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_prompt_contains_metrics() -> None:
    """Prompt 应包含 CPU、内存、磁盘和网络指标及其数值和单位。"""
    prompt = build_diagnosis_prompt(
        sample_metrics(), sample_anomalies(), sample_diagnoses()
    )

    assert "CPU" in prompt
    assert "Memory" in prompt
    assert "95.2" in prompt
    assert "93.5" in prompt
    assert "MB/s" in prompt


def test_prompt_contains_anomalies() -> None:
    """Prompt 应包含异常信息。"""
    prompt = build_diagnosis_prompt(
        sample_metrics(), sample_anomalies(), sample_diagnoses()
    )

    assert "cpu_percent" in prompt
    assert "CPU 使用率过高" in prompt
    assert "阈值 90" in prompt


def test_prompt_contains_diagnoses() -> None:
    """Prompt 应包含基础诊断信息。"""
    prompt = build_diagnosis_prompt(
        sample_metrics(), sample_anomalies(), sample_diagnoses()
    )

    assert "基础诊断结果" in prompt
    assert "system" in prompt
    assert "系统整体资源压力较大" in prompt


def test_prompt_contains_analysis_requirements() -> None:
    """Prompt 应要求模型做根因分析、风险评估和优化建议。"""
    prompt = build_diagnosis_prompt(
        sample_metrics(), sample_anomalies(), sample_diagnoses()
    )

    assert "root cause" in prompt
    assert "risk" in prompt
    assert "recommendations" in prompt


def test_prompt_declares_no_execution_permission() -> None:
    """Prompt 必须明确 AI 只能分析建议，不能执行系统操作。"""
    prompt = build_diagnosis_prompt(
        sample_metrics(), sample_anomalies(), sample_diagnoses()
    )

    assert "不能执行任何系统操作" in prompt
    assert "权限限制" in prompt


def test_prompt_declares_output_format() -> None:
    """Prompt 应要求模型按约定 JSON 结构返回。"""
    prompt = build_diagnosis_prompt(
        sample_metrics(), sample_anomalies(), sample_diagnoses()
    )

    for field in ["summary", "root_cause", "risk", "recommendations"]:
        assert field in prompt, f"输出格式缺少字段 {field}"
    assert "输出格式" in prompt


def test_prompt_handles_empty_anomalies_and_diagnoses() -> None:
    """没有异常和诊断时 Prompt 仍应正常生成，并写明未检测到异常。"""
    prompt = build_diagnosis_prompt(sample_metrics(), [], [])

    assert isinstance(prompt, str)
    assert "未检测到超过阈值的异常" in prompt
    assert "无基础诊断结果" in prompt


# ---------- 模块边界 ----------


def test_advisor_has_no_ai_sdk_or_http_client() -> None:
    """本阶段不引入任何大模型 SDK 或网络请求库。"""
    with open(ai.advisor.__file__, encoding="utf-8") as f:
        content = f.read().lower()
    for token in FORBIDDEN_TOKENS:
        assert token not in content, f"advisor.py 不应出现 {token}"


def test_advisor_does_not_import_upstream_modules() -> None:
    """ai 层只处理传入的数据，不应引入上游三个模块。"""
    with open(ai.advisor.__file__, encoding="utf-8") as f:
        content = f.read()
    for statement in FORBIDDEN_IMPORTS:
        assert statement not in content, f"advisor.py 不应出现 {statement}"


# ================================================================
# Stage 5C：接入多指标关联发现
# ================================================================


def sample_correlation_findings() -> list:
    return [
        {
            "type": "cpu_bottleneck",
            "severity": "high",
            "message": (
                "CPU 使用率较高，同时 GPU 利用率较低、推理延迟较高且请求队列较长，"
                "可能存在 CPU 侧数据处理或任务调度瓶颈。"
            ),
        }
    ]


# ---------- B. build_ai_context ----------


def test_context_legacy_three_arg_call_unchanged() -> None:
    """旧调用 build_ai_context(metrics, anomalies, diagnoses) 结构不变。"""
    context = build_ai_context(sample_metrics(), sample_anomalies(), sample_diagnoses())

    assert set(context.keys()) == {"metrics", "anomalies", "diagnoses"}


def test_context_with_none_findings_works() -> None:
    """correlation_findings=None 时正常生成，且不新增键。"""
    context = build_ai_context(
        sample_metrics(), sample_anomalies(), sample_diagnoses(), None
    )

    assert "correlation_findings" not in context
    assert len(context["diagnoses"]) == 3


def test_context_contains_correlation_findings() -> None:
    """传入关联发现后 context 中应存在该键和该内容。"""
    findings = sample_correlation_findings()
    context = build_ai_context(
        sample_metrics(), sample_anomalies(), sample_diagnoses(), findings
    )

    assert "correlation_findings" in context
    assert context["correlation_findings"] == findings


def test_context_with_empty_findings_has_empty_key() -> None:
    """显式传入空列表时，键存在但内容为空。"""
    context = build_ai_context(
        sample_metrics(), sample_anomalies(), sample_diagnoses(), []
    )

    assert context["correlation_findings"] == []


def test_context_findings_independent_from_input() -> None:
    """context 中的关联发现必须是独立副本，双向隔离。"""
    findings = sample_correlation_findings()
    context = build_ai_context(
        sample_metrics(), sample_anomalies(), sample_diagnoses(), findings
    )

    # 方向一：改原始列表，context 不应跟着变
    findings[0]["severity"] = "low"
    assert context["correlation_findings"][0]["severity"] == "high"
    assert context["correlation_findings"][0]["type"] == "cpu_bottleneck"

    # 方向二：改 context，原始列表不应跟着变
    context["correlation_findings"][0]["type"] = "tampered"
    assert findings[0]["type"] == "cpu_bottleneck"


def test_context_legacy_three_fields_still_independent() -> None:
    """原有三个字段的隔离行为不能因为加了新参数而退化。"""
    metrics = sample_metrics()
    context = build_ai_context(metrics, sample_anomalies(), sample_diagnoses(), [])

    context["metrics"]["cpu_percent"] = 0
    assert metrics["cpu_percent"] == 95.2


# ---------- C. Prompt ----------


def test_prompt_legacy_call_still_works() -> None:
    """旧调用 build_diagnosis_prompt(metrics, anomalies, diagnoses) 仍然正常。"""
    prompt = build_diagnosis_prompt(
        sample_metrics(), sample_anomalies(), sample_diagnoses()
    )

    assert isinstance(prompt, str)
    assert "AI Infra 运维诊断助手" in prompt


def test_prompt_contains_correlation_section() -> None:
    """有关联发现时 Prompt 应包含该章节。"""
    prompt = build_diagnosis_prompt(
        sample_metrics(),
        sample_anomalies(),
        sample_diagnoses(),
        sample_correlation_findings(),
    )

    assert "多指标关联发现" in prompt
    assert "cpu_bottleneck" in prompt
    assert "high" in prompt
    assert "可能存在 CPU 侧数据处理或任务调度瓶颈" in prompt


def test_prompt_states_findings_are_not_confirmed_root_cause() -> None:
    """Prompt 必须明确说明关联发现只是可能原因，不是已确认根因。"""
    prompt = build_diagnosis_prompt(
        sample_metrics(),
        sample_anomalies(),
        sample_diagnoses(),
        sample_correlation_findings(),
    )

    assert "不是已经确认的根因" in prompt


def test_prompt_caveat_present_even_without_findings() -> None:
    """即使没有关联发现，Prompt 里也保留"不是已确认根因"的提醒。"""
    prompt = build_diagnosis_prompt(sample_metrics(), sample_anomalies(), [])

    assert "多指标关联发现" in prompt
    assert "不是已经确认的根因" in prompt
    assert "未发现指标之间的异常关联" in prompt


def test_prompt_without_findings_still_complete() -> None:
    """没有关联发现时 Prompt 仍然完整可用。"""
    prompt = build_diagnosis_prompt(sample_metrics(), [], [])

    assert isinstance(prompt, str)
    assert "root cause" in prompt
    assert "recommendations" in prompt
    assert "不能执行任何系统操作" in prompt
    assert "未发现指标之间的异常关联" in prompt


def test_prompt_section_numbering_is_contiguous() -> None:
    """Prompt 章节编号应连续，不因新增章节而错乱。"""
    prompt = build_diagnosis_prompt(
        sample_metrics(),
        sample_anomalies(),
        sample_diagnoses(),
        sample_correlation_findings(),
    )

    for number, title in [
        ("一", "当前系统指标"),
        ("二", "检测到的异常"),
        ("三", "基础诊断结果"),
        ("四", "多指标关联发现"),
        ("五", "分析要求"),
        ("六", "权限限制"),
        ("七", "输出格式"),
    ]:
        assert f"## {number}、{title}" in prompt, f"缺少章节：{number}、{title}"


def test_advisor_does_not_call_correlate() -> None:
    """advisor 只组织上下文，不应该自己跑关联分析。"""
    source = open(ai.advisor.__file__, encoding="utf-8").read()

    for forbidden in ["correlate(", "from correlation", "import correlation"]:
        assert forbidden not in source, f"advisor.py 不应出现 {forbidden}"

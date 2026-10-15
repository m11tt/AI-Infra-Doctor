"""初步诊断测试。

覆盖 diagnose() 的三条诊断规则。
本文件全部使用固定字典和列表作为输入，不调用 monitor、不调用 psutil，
因为 diagnosis 只负责分析传入的数据。
"""

import copy

import diagnosis.diagnosis
from diagnosis.diagnosis import CORRELATION_SOURCE, diagnose

# diagnosis 不允许出现的第三方依赖和 API 调用痕迹。
# 这些都是具体名称，不会出现在中文说明文字里。
FORBIDDEN_TOKENS = [
    "psutil",
    "openai",
    "anthropic",
    "httpx",
    "urllib",
    "requests",
    "api_key",
    "dashscope",
    "zhipu",
    "chat.completions",
]


def make_metrics(cpu=50, memory=60, disk=70, sent=1.0, recv=2.0) -> dict:
    """构造一份测试用指标字典。"""
    return {
        "cpu_percent": cpu,
        "memory_percent": memory,
        "disk_percent": disk,
        "network_sent_mb_per_sec": sent,
        "network_recv_mb_per_sec": recv,
    }


def make_anomaly(metric: str, value: float = 95.0) -> dict:
    """构造一条与 detect_anomalies() 格式一致的异常记录。"""
    return {
        "metric": metric,
        "value": value,
        "threshold": 90,
        "message": f"{metric} 过高",
    }


# ---------- 测试 1：没有异常 ----------


def test_no_anomalies_returns_empty_list() -> None:
    """anomalies 为空时返回 []。"""
    assert diagnose(make_metrics(), []) == []


# ---------- 测试 2：只有 CPU 异常 ----------


def test_only_cpu_anomaly_returns_one_diagnosis() -> None:
    """只有 CPU 异常时，只给出 CPU 诊断。"""
    result = diagnose(make_metrics(cpu=95), [make_anomaly("cpu_percent")])

    assert len(result) == 1
    assert result[0] == {
        "type": "cpu",
        "message": "CPU 使用率过高，可能存在 CPU 计算负载较高",
    }


# ---------- 测试 3：只有内存异常 ----------


def test_only_memory_anomaly_returns_one_diagnosis() -> None:
    """只有内存异常时，只给出内存诊断。"""
    result = diagnose(make_metrics(memory=95), [make_anomaly("memory_percent")])

    assert len(result) == 1
    assert result[0] == {
        "type": "memory",
        "message": "内存使用率过高，可能存在内存资源紧张",
    }


# ---------- 测试 4：CPU + memory 同时异常 ----------


def test_cpu_and_memory_returns_three_diagnoses() -> None:
    """CPU 和内存同时异常时，返回 3 条诊断，含 1 条综合诊断。"""
    anomalies = [
        make_anomaly("cpu_percent"),
        make_anomaly("memory_percent"),
    ]
    result = diagnose(make_metrics(cpu=95, memory=93), anomalies)

    assert len(result) == 3
    assert [d["type"] for d in result] == ["cpu", "memory", "system"]
    assert result[2] == {
        "type": "system",
        "message": "CPU 和内存同时处于高负载状态，系统整体资源压力较大",
    }


# ---------- 测试 5：只有磁盘异常 ----------


def test_only_disk_anomaly_returns_disk_diagnosis() -> None:
    """只有磁盘异常时，应给出一条 disk 诊断，不能报而不诊。

    detection 会把磁盘纳入检测范围，diagnosis 就必须给出对应结论，
    否则会出现"资源异常列表有磁盘告警、诊断结果却为空"的矛盾。
    """
    result = diagnose(make_metrics(disk=95), [make_anomaly("disk_percent")])

    assert len(result) == 1
    assert result[0]["type"] == "disk"
    assert "磁盘" in result[0]["message"]


def test_disk_anomaly_does_not_trigger_combined_rule() -> None:
    """磁盘异常不应误触发 CPU + 内存的组合诊断。"""
    result = diagnose(make_metrics(disk=95), [make_anomaly("disk_percent")])

    assert all(d["type"] != "system" for d in result)


def test_all_three_metrics_return_four_diagnoses() -> None:
    """CPU / 内存 / 磁盘同时异常时，返回 3 条单项 + 1 条组合 = 4 条。"""
    anomalies = [
        make_anomaly("cpu_percent"),
        make_anomaly("memory_percent"),
        make_anomaly("disk_percent"),
    ]
    result = diagnose(make_metrics(cpu=95, memory=93, disk=95), anomalies)

    assert [d["type"] for d in result] == ["cpu", "memory", "disk", "system"]


# ---------- 测试 6：网络速率高但没有异常 ----------


def test_high_network_rate_with_no_anomalies_returns_empty_list() -> None:
    """网络速率极高但 anomalies 为空时，仍返回 []。"""
    metrics = make_metrics(sent=1000, recv=1000)
    assert diagnose(metrics, []) == []


# ---------- 模块边界 ----------


def test_diagnosis_does_not_use_psutil() -> None:
    """diagnosis 不应该自己采集系统数据，因此不能依赖 psutil。"""
    with open(diagnosis.diagnosis.__file__, encoding="utf-8") as f:
        content = f.read()
    assert "psutil" not in content, "diagnosis.py 不应引入 psutil"


def test_diagnosis_does_not_call_any_ai_api() -> None:
    """本阶段不调用大模型和任何外部 API。"""
    with open(diagnosis.diagnosis.__file__, encoding="utf-8") as f:
        content = f.read().lower()
    for token in FORBIDDEN_TOKENS:
        assert token not in content, f"diagnosis.py 不应出现 {token}"


def test_diagnosis_does_not_recollect_metrics() -> None:
    """diagnosis 只能分析传入的数据，不能自己去 monitor 取指标。

    判断依据是"有没有 import monitor"：
    只要没有引入 monitor 模块，就不可能调用 get_system_metrics。
    这里不能直接查 "get_system_metrics" 字样，因为 docstring 的参数说明里
    正常就会提到这个函数名，那样会误报。
    """
    with open(diagnosis.diagnosis.__file__, encoding="utf-8") as f:
        content = f.read()
    assert "import monitor" not in content, "diagnosis.py 不应引入 monitor"
    assert "from monitor" not in content, "diagnosis.py 不应引入 monitor"


# ---------- 输出格式 ----------


def test_each_diagnosis_has_type_and_message() -> None:
    """每条诊断应恰好包含 type 和 message 两个字段。"""
    result = diagnose(make_metrics(), [make_anomaly("cpu_percent")])

    assert len(result) == 1
    assert set(result[0].keys()) == {"type", "message"}


def test_result_does_not_mutate_global_rules() -> None:
    """返回值应是规则常量的副本，修改结果不应影响后续调用。"""
    result = diagnose(make_metrics(), [make_anomaly("cpu_percent")])
    result[0]["message"] = "被测试改坏了"

    again = diagnose(make_metrics(), [make_anomaly("cpu_percent")])
    assert again[0]["message"] == "CPU 使用率过高，可能存在 CPU 计算负载较高"


# ================================================================
# Stage 5C：接入多指标关联发现
# ================================================================


def make_cpu_bottleneck_finding() -> dict:
    """构造一条与 correlate() 输出格式一致的关联发现。"""
    return {
        "type": "cpu_bottleneck",
        "severity": "high",
        "message": (
            "CPU 使用率较高，同时 GPU 利用率较低、推理延迟较高且请求队列较长，"
            "可能存在 CPU 侧数据处理或任务调度瓶颈。"
        ),
    }


def test_legacy_two_arg_call_still_works() -> None:
    """旧调用方式 diagnose(metrics, anomalies) 仍然正常。"""
    result = diagnose(make_metrics(), [make_anomaly("cpu_percent")])

    assert len(result) == 1
    assert result[0]["type"] == "cpu"


def test_none_correlation_findings_behaves_like_before() -> None:
    """correlation_findings=None 时行为与旧版本一致。"""
    with_none = diagnose(make_metrics(), [make_anomaly("cpu_percent")], None)
    without = diagnose(make_metrics(), [make_anomaly("cpu_percent")])

    assert with_none == without
    assert with_none == [
        {"type": "cpu", "message": "CPU 使用率过高，可能存在 CPU 计算负载较高"}
    ]


def test_empty_correlation_findings_changes_nothing() -> None:
    """传入空列表时不应产生额外诊断。"""
    assert diagnose(make_metrics(), [], []) == []


def test_correlation_finding_appears_in_diagnoses() -> None:
    """传入关联发现后应出现在诊断结果里。"""
    findings = [make_cpu_bottleneck_finding()]
    result = diagnose(make_metrics(), [], findings)

    assert len(result) == 1
    assert result[0]["type"] == "cpu_bottleneck"
    assert result[0]["severity"] == "high"
    assert "可能存在" in result[0]["message"]


def test_correlation_finding_coexists_with_rule_diagnoses() -> None:
    """关联发现应与普通规则诊断并存，而不是替换它们。"""
    result = diagnose(
        make_metrics(), [make_anomaly("cpu_percent")], [make_cpu_bottleneck_finding()]
    )

    types = [entry["type"] for entry in result]
    assert types == ["cpu", "cpu_bottleneck"]


def test_rule_and_correlation_are_distinguishable() -> None:
    """两类结论必须能明确区分，不能混成一个概念。"""
    result = diagnose(
        make_metrics(), [make_anomaly("cpu_percent")], [make_cpu_bottleneck_finding()]
    )

    rule_entry = next(e for e in result if e["type"] == "cpu")
    corr_entry = next(e for e in result if e["type"] == "cpu_bottleneck")

    # 关联发现带 source 标记，普通规则诊断不带
    assert corr_entry["source"] == CORRELATION_SOURCE
    assert "source" not in rule_entry


def test_correlation_finding_alone_does_not_trigger_rule_rules() -> None:
    """关联发现不应被当成普通 anomaly 去触发 CPU/内存规则。"""
    # anomalies 为空但给了关联发现，结果里不应凭空出现 cpu / memory 规则诊断
    result = diagnose(make_metrics(), [], [make_cpu_bottleneck_finding()])

    assert [e["type"] for e in result] == ["cpu_bottleneck"]


def test_input_correlation_findings_not_modified() -> None:
    """传入的关联发现列表和其中的字典都不应被修改。"""
    finding = make_cpu_bottleneck_finding()
    findings = [finding]
    snapshot = copy.deepcopy(findings)

    diagnose(make_metrics(), [], findings)

    assert findings == snapshot
    assert "source" not in findings[0]


def test_result_correlation_entry_is_independent_copy() -> None:
    """修改结果里的关联发现不应影响下一次调用。"""
    findings = [make_cpu_bottleneck_finding()]
    first = diagnose(make_metrics(), [], findings)
    first[0]["severity"] = "low"

    again = diagnose(make_metrics(), [], [make_cpu_bottleneck_finding()])
    assert again[0]["severity"] == "high"


# ---------- 非法输入（防御式取值） ----------


def test_anomaly_missing_metric_field_does_not_raise() -> None:
    """异常项缺少 metric 字段时跳过，不抛 KeyError。"""
    assert diagnose({}, [{"value": 95, "threshold": 90, "message": "x"}]) == []


def test_non_dict_anomaly_item_does_not_raise() -> None:
    """异常项不是字典时跳过，不影响其他合法项。"""
    anomalies = ["bad", make_anomaly("cpu_percent")]
    result = diagnose({}, anomalies)

    assert [d["type"] for d in result] == ["cpu"]


def test_non_dict_correlation_finding_is_skipped() -> None:
    """关联发现列表里混入非字典元素时跳过，不抛异常。"""
    assert diagnose({}, [], ["bad", 123, None]) == []


def test_disk_rule_matches_detection_scope() -> None:
    """诊断规则表必须与 detection 检测的指标一一对应。

    这是防止"报了警却没有任何结论"的结构性约束：
    detection 检测哪些指标，diagnosis 就要有对应规则。
    """
    from detection.detector import CHECK_RULES
    from diagnosis.diagnosis import DIAGNOSIS_RULES

    detected_metrics = {name for name, _, _ in CHECK_RULES}
    assert detected_metrics <= set(DIAGNOSIS_RULES), (
        f"检测了但没诊断规则的指标：{detected_metrics - set(DIAGNOSIS_RULES)}"
    )

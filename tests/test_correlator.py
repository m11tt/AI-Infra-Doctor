"""多指标关联分析测试。

覆盖 correlate() 的 CPU 侧潜在瓶颈规则。
本文件不调用 monitor / workload / detection，
全部用固定字典作为输入，确保数据来源明确可控。
"""

import copy

import correlation.correlator
from correlation.correlator import correlate


def make_metrics(cpu=95.0) -> dict:
    return {
        "cpu_percent": cpu,
        "memory_percent": 60.0,
        "disk_percent": 70.0,
        "network_sent_mb_per_sec": 1.2,
        "network_recv_mb_per_sec": 2.5,
    }


def make_workload(gpu=35.0, latency=350.0, queue=18) -> dict:
    return {
        "request_count": 100,
        "avg_latency_ms": latency,
        "queue_length": queue,
        "gpu_utilization": gpu,
    }


def make_anomalies() -> list:
    return [
        {
            "metric": "cpu_percent",
            "value": 95.0,
            "threshold": 90,
            "message": "CPU 使用率过高",
        }
    ]


# ---------- 1. 条件全部满足 ----------


def test_all_conditions_met_returns_cpu_bottleneck() -> None:
    """四个条件同时满足时应产生一条 cpu_bottleneck 诊断。"""
    findings = correlate(
        make_metrics(cpu=95.0),
        make_workload(gpu=35.0, latency=350.0, queue=18),
        make_anomalies(),
    )

    assert len(findings) == 1
    assert findings[0] == {
        "type": "cpu_bottleneck",
        "severity": "high",
        "message": (
            "CPU 使用率较高，同时 GPU 利用率较低、推理延迟较高且请求队列较长，"
            "可能存在 CPU 侧数据处理或任务调度瓶颈。"
        ),
    }


# ---------- 2~5. 缺少任一条件都不应触发 ----------


def test_cpu_high_but_gpu_also_high_no_finding() -> None:
    """CPU 高但 GPU 也高，不构成 CPU 侧瓶颈。"""
    findings = correlate(
        make_metrics(cpu=95.0),
        make_workload(gpu=85.0, latency=350.0, queue=18),
        make_anomalies(),
    )
    assert findings == []


def test_cpu_high_but_latency_normal_no_finding() -> None:
    """CPU 高但延迟正常，不构成 CPU 侧瓶颈。"""
    findings = correlate(
        make_metrics(cpu=95.0),
        make_workload(gpu=35.0, latency=100.0, queue=18),
        make_anomalies(),
    )
    assert findings == []


def test_cpu_high_but_queue_normal_no_finding() -> None:
    """CPU 高但队列正常，不构成 CPU 侧瓶颈。"""
    findings = correlate(
        make_metrics(cpu=95.0),
        make_workload(gpu=35.0, latency=350.0, queue=3),
        make_anomalies(),
    )
    assert findings == []


def test_gpu_low_but_cpu_normal_no_finding() -> None:
    """GPU 低但 CPU 正常，不构成 CPU 侧瓶颈。"""
    findings = correlate(
        make_metrics(cpu=50.0),
        make_workload(gpu=35.0, latency=350.0, queue=18),
        [],
    )
    assert findings == []


# ---------- 6. 返回值类型 ----------


def test_always_returns_list() -> None:
    """无论命中与否，返回值都必须是 list。"""
    assert isinstance(
        correlate(make_metrics(), make_workload(), make_anomalies()), list
    )
    assert isinstance(
        correlate(make_metrics(cpu=20.0), make_workload(), []), list
    )


# ---------- 7~9. 不修改输入 ----------


def test_does_not_modify_input_metrics() -> None:
    """调用后原始 metrics 不应被改变。"""
    metrics = make_metrics()
    snapshot = copy.deepcopy(metrics)

    correlate(metrics, make_workload(), make_anomalies())

    assert metrics == snapshot


def test_does_not_modify_input_workload() -> None:
    """调用后原始 workload 不应被改变。"""
    workload = make_workload()
    snapshot = copy.deepcopy(workload)

    correlate(make_metrics(), workload, make_anomalies())

    assert workload == snapshot


def test_does_not_modify_input_anomalies() -> None:
    """调用后原始 anomalies 不应被改变。"""
    anomalies = make_anomalies()
    snapshot = copy.deepcopy(anomalies)

    correlate(make_metrics(), make_workload(), anomalies)

    assert anomalies == snapshot


# ---------- 10. 正常场景 ----------


def test_normal_scenario_returns_empty_list() -> None:
    """一切正常时返回空列表。"""
    assert correlate(
        make_metrics(cpu=50.0),
        make_workload(gpu=35.0, latency=120.0, queue=2),
        [],
    ) == []


# ---------- 边界：正好等于阈值不触发 ----------


def test_values_exactly_at_thresholds_do_not_trigger() -> None:
    """四个值正好等于阈值时不应触发（严格大于 / 严格小于）。"""
    findings = correlate(
        make_metrics(cpu=90),
        make_workload(gpu=50, latency=200, queue=10),
        make_anomalies(),
    )
    assert findings == []


def test_values_just_above_thresholds_do_trigger() -> None:
    """四个值刚越过阈值一点点就应该触发。"""
    findings = correlate(
        make_metrics(cpu=90.1),
        make_workload(gpu=49.9, latency=200.1, queue=11),
        make_anomalies(),
    )
    assert len(findings) == 1


# ---------- 措辞：不得断言根因 ----------


def test_message_does_not_claim_certainty() -> None:
    """结论只能是"可能"，不能断言根因。"""
    findings = correlate(make_metrics(), make_workload(), make_anomalies())
    message = findings[0]["message"]

    assert "可能存在" in message
    for forbidden in ["一定是", "根因就是", "确定是", "必然是"]:
        assert forbidden not in message, f"message 不应使用确定性措辞 {forbidden}"


# ---------- 返回值隔离 ----------


def test_result_is_independent_copy() -> None:
    """修改返回值不应影响模块常量。"""
    findings = correlate(make_metrics(), make_workload(), make_anomalies())
    findings[0]["severity"] = "low"

    again = correlate(make_metrics(), make_workload(), make_anomalies())
    assert again[0]["severity"] == "high"


# ---------- 数据缺失时不应崩溃 ----------


def test_missing_workload_fields_do_not_crash() -> None:
    """工作负载数据缺失时应返回空列表，而不是抛异常。"""
    assert correlate(make_metrics(), {}, []) == []


def test_missing_metrics_do_not_crash() -> None:
    """系统指标缺失时应返回空列表。"""
    assert correlate({}, make_workload(), []) == []


# ---------- 模块边界 ----------


def test_does_not_import_upstream_modules() -> None:
    """correlation 只分析传入的数据，不应自己采集或检测。"""
    import ast

    with open(correlation.correlator.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    # 本模块是纯规则判断，不 import 任何东西，包括不引入 LLM 客户端。
    assert imported == set(), f"correlator.py 不应 import 任何模块，实际: {imported}"


# ---------- 非法输入（防御式取值） ----------


def test_none_metrics_returns_empty_list() -> None:
    """metrics 为 None 时返回空列表，不抛 AttributeError。"""
    assert correlate(None, {}, []) == []


def test_none_workload_returns_empty_list() -> None:
    """workload 为 None 时返回空列表。"""
    assert correlate({}, None, []) == []


def test_non_dict_inputs_return_empty_list() -> None:
    """整体传入字符串等非字典类型时返回空列表。"""
    assert correlate("abc", "def", []) == []
    assert correlate([], [], []) == []


def test_non_numeric_values_do_not_raise() -> None:
    """指标值不是数值时规则不成立，不抛 TypeError。"""
    metrics = {"cpu_percent": "95"}
    workload = {"gpu_utilization": None, "avg_latency_ms": 350, "queue_length": 18}
    assert correlate(metrics, workload, []) == []


def test_cpu_bottleneck_still_works_after_guards() -> None:
    """加了类型守卫后，正常的命中场景必须保持不变。"""
    metrics = {"cpu_percent": 95}
    workload = {"gpu_utilization": 35.0, "avg_latency_ms": 350.0, "queue_length": 18}
    findings = correlate(metrics, workload, [])

    assert len(findings) == 1
    assert findings[0]["type"] == "cpu_bottleneck"

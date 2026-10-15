"""AI 推理工作负载指标测试。

覆盖 get_inference_metrics() 的返回结构和取值合理性。
"""

import ast

import workload.inference
from workload.inference import get_inference_metrics

# 四个字段及其期望类型
EXPECTED_FIELDS = {
    "request_count": int,
    "avg_latency_ms": float,
    "queue_length": int,
    "gpu_utilization": float,
}


# ---------- 基本结构 ----------


def test_returns_dict() -> None:
    """返回值必须是字典。"""
    assert isinstance(get_inference_metrics(), dict)


def test_contains_all_fields() -> None:
    """必须包含约定的 4 个字段。"""
    metrics = get_inference_metrics()
    for field in EXPECTED_FIELDS:
        assert field in metrics, f"返回值缺少字段: {field}"


def test_returns_exactly_four_fields() -> None:
    """返回值应恰好是约定的 4 个字段，不多不少。"""
    assert len(get_inference_metrics()) == 4


# ---------- 字段类型 ----------


def test_field_types_are_correct() -> None:
    """每个字段的类型都应符合约定。"""
    metrics = get_inference_metrics()
    for field, expected_type in EXPECTED_FIELDS.items():
        value = metrics[field]
        assert isinstance(value, expected_type), (
            f"{field} 应为 {expected_type.__name__}，实际是 {type(value).__name__}"
        )


# ---------- 取值合理性 ----------


def test_non_negative_fields() -> None:
    """请求数、延迟、队列长度都不应为负数。"""
    metrics = get_inference_metrics()
    for field in ["request_count", "avg_latency_ms", "queue_length"]:
        assert metrics[field] >= 0, f"{field} 不应为负数: {metrics[field]}"


def test_gpu_utilization_in_range() -> None:
    """GPU 使用率是百分比，应当在 0-100 之间。"""
    value = get_inference_metrics()["gpu_utilization"]
    assert 0 <= value <= 100, f"gpu_utilization 超出 0-100: {value}"


def test_values_match_mock_baseline() -> None:
    """本阶段应稳定返回约定的模拟数据。"""
    assert get_inference_metrics() == {
        "request_count": 100,
        "avg_latency_ms": 350.0,
        "queue_length": 18,
        "gpu_utilization": 35.0,
    }


# ---------- 返回值隔离 ----------


def test_result_is_independent_copy() -> None:
    """返回值应是常量副本，修改结果不应影响后续调用。"""
    result = get_inference_metrics()
    result["gpu_utilization"] = 999.0
    result["queue_length"] = -1

    assert get_inference_metrics()["gpu_utilization"] == 35.0
    assert get_inference_metrics()["queue_length"] == 18


def test_repeated_calls_are_independent() -> None:
    """多次调用返回的应是彼此独立的字典。"""
    first = get_inference_metrics()
    second = get_inference_metrics()

    first["request_count"] = 0
    assert second["request_count"] == 100


# ---------- 模块边界 ----------


def test_does_not_use_gpu_or_network_libraries() -> None:
    """本阶段不连接 GPU / CUDA / CANN，也不访问外部服务。

    这里用 ast 解析出所有 import，而不是搜索关键词：
    文档里写"本阶段不连接 GPU / CUDA"是正常的说明文字，
    按关键词搜会误报自己。inference.py 目前不需要 import 任何模块，
    所以这里直接断言 import 集合为空。
    """
    with open(workload.inference.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported == set(), f"本阶段不应 import 任何模块，实际: {imported}"

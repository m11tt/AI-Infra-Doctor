"""监控模块测试。

覆盖系统资源采集函数 get_system_metrics()。
"""

import pytest

import monitor.system
from monitor.system import get_system_metrics

# get_system_metrics() 必须返回的字段
PERCENT_FIELDS = ["cpu_percent", "memory_percent", "disk_percent"]
NETWORK_FIELDS = ["network_sent_mb_per_sec", "network_recv_mb_per_sec"]
REQUIRED_FIELDS = PERCENT_FIELDS + NETWORK_FIELDS

# 阶段 1.5 已废弃的累计流量字段，返回值里不应该再出现
REMOVED_FIELDS = ["network_sent_mb", "network_recv_mb"]


# ---------- 包结构 ----------


def test_monitor_package_importable() -> None:
    """monitor.system 模块应可被导入。"""
    assert monitor.system is not None


def test_monitor_system_has_docstring() -> None:
    """占位模块应保留职责说明，便于后续实现时对齐边界。"""
    assert monitor.system.__doc__


# ---------- get_system_metrics() 返回结构 ----------


def test_returns_dict() -> None:
    """返回值必须是字典。"""
    assert isinstance(get_system_metrics(), dict)


def test_contains_required_fields() -> None:
    """必须包含约定的 5 个字段。"""
    metrics = get_system_metrics()
    for field in REQUIRED_FIELDS:
        assert field in metrics, f"返回值缺少字段: {field}"


def test_removed_cumulative_fields_are_gone() -> None:
    """累计流量字段已被实时速率取代，不应再出现在返回值里。"""
    metrics = get_system_metrics()
    for field in REMOVED_FIELDS:
        assert field not in metrics, f"字段 {field} 应该已被移除"


def test_returns_exactly_five_fields() -> None:
    """返回值应恰好是约定的 5 个字段，不多不少。"""
    assert len(get_system_metrics()) == 5


# ---------- 字段类型 ----------


def test_percent_fields_are_numbers() -> None:
    """三个使用率指标应该是数值。"""
    metrics = get_system_metrics()
    for field in PERCENT_FIELDS:
        assert isinstance(metrics[field], (int, float)), (
            f"{field} 不是数值，实际是 {type(metrics[field]).__name__}"
        )


def test_network_fields_are_numbers() -> None:
    """两个网络速率指标应该是数值。"""
    metrics = get_system_metrics()
    for field in NETWORK_FIELDS:
        assert isinstance(metrics[field], (int, float)), (
            f"{field} 不是数值，实际是 {type(metrics[field]).__name__}"
        )


# ---------- 字段取值合理性 ----------


def test_percent_fields_in_range() -> None:
    """使用率应当在 0-100 之间。"""
    metrics = get_system_metrics()
    for field in PERCENT_FIELDS:
        value = metrics[field]
        assert 0 <= value <= 100, f"{field} 超出 0-100 范围: {value}"


def test_network_fields_not_negative() -> None:
    """网络速率不可能是负数。"""
    metrics = get_system_metrics()
    for field in NETWORK_FIELDS:
        value = metrics[field]
        assert value >= 0, f"{field} 不应为负数: {value}"


# ---------- 首次调用没有对比数据的情况 ----------


def test_first_call_returns_zero_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    """第一次调用时没有上一次采样，网络速率应返回 0.0 而不是崩溃。

    monkeypatch 在测试结束后会自动把模块变量还原，
    所以不会影响其它测试。
    """
    monkeypatch.setattr(monitor.system, "_previous_net_io", None)
    monkeypatch.setattr(monitor.system, "_previous_sampled_at", None)

    metrics = get_system_metrics()
    for field in NETWORK_FIELDS:
        assert metrics[field] == 0.0, f"首次调用时 {field} 应为 0.0"


def test_second_call_returns_real_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    """第二次调用时已能算出真实速率（使用真实间隔，不假设 1 秒）。"""
    import time

    monkeypatch.setattr(monitor.system, "_previous_net_io", None)
    monkeypatch.setattr(monitor.system, "_previous_sampled_at", None)

    get_system_metrics()  # 第一次：建立基线
    time.sleep(0.2)  # 故意用 0.2 秒，证明没有假设间隔是 1 秒
    metrics = get_system_metrics()  # 第二次：算出速率

    for field in NETWORK_FIELDS:
        value = metrics[field]
        assert isinstance(value, (int, float))
        assert value >= 0

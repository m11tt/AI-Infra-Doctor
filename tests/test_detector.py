"""基础异常检测测试。

覆盖 detect_anomalies() 的阈值判断规则。
本文件不依赖 monitor 和 psutil，全部使用固定字典作为输入，
因为 detect_anomalies() 只负责判断，不负责采集。
"""

import detection.detector
from detection.detector import detect_anomalies


def make_metrics(cpu=50, memory=60, disk=70, sent=1.0, recv=2.0) -> dict:
    """构造一份测试用指标字典，格式与 get_system_metrics() 保持一致。"""
    return {
        "cpu_percent": cpu,
        "memory_percent": memory,
        "disk_percent": disk,
        "network_sent_mb_per_sec": sent,
        "network_recv_mb_per_sec": recv,
    }


# ---------- 测试 1：全部正常 ----------


def test_all_normal_returns_empty_list() -> None:
    """CPU、内存、磁盘全部正常时不应产生任何异常。"""
    metrics = make_metrics(cpu=50, memory=60, disk=70)
    assert detect_anomalies(metrics) == []


# ---------- 测试 2：CPU 超标 ----------


def test_cpu_above_threshold_detected() -> None:
    """CPU > 90 时产生 1 条 CPU 异常。"""
    metrics = make_metrics(cpu=95.2)
    anomalies = detect_anomalies(metrics)

    assert len(anomalies) == 1
    assert anomalies[0] == {
        "metric": "cpu_percent",
        "value": 95.2,
        "threshold": 90,
        "message": "CPU 使用率过高",
    }


# ---------- 测试 3：内存超标 ----------


def test_memory_above_threshold_detected() -> None:
    """memory_percent > 90 时产生 1 条内存异常。"""
    metrics = make_metrics(memory=93.5)
    anomalies = detect_anomalies(metrics)

    assert len(anomalies) == 1
    assert anomalies[0] == {
        "metric": "memory_percent",
        "value": 93.5,
        "threshold": 90,
        "message": "内存使用率过高",
    }


# ---------- 测试 4：磁盘超标 ----------


def test_disk_above_threshold_detected() -> None:
    """disk_percent > 90 时产生 1 条磁盘异常。"""
    metrics = make_metrics(disk=96.0)
    anomalies = detect_anomalies(metrics)

    assert len(anomalies) == 1
    assert anomalies[0] == {
        "metric": "disk_percent",
        "value": 96.0,
        "threshold": 90,
        "message": "磁盘使用率过高",
    }


# ---------- 测试 5：三个指标同时超标 ----------


def test_all_three_above_threshold_returns_three_anomalies() -> None:
    """CPU、内存、磁盘同时超标时产生 3 条异常。"""
    metrics = make_metrics(cpu=95, memory=92, disk=97)
    anomalies = detect_anomalies(metrics)

    assert len(anomalies) == 3
    assert [a["metric"] for a in anomalies] == [
        "cpu_percent",
        "memory_percent",
        "disk_percent",
    ]


# ---------- 测试 6：正好等于阈值 ----------


def test_value_equal_to_threshold_is_normal() -> None:
    """正好等于 90 视为正常，只有超过 90 才算异常。"""
    metrics = make_metrics(cpu=90, memory=90, disk=90)
    assert detect_anomalies(metrics) == []


# ---------- 测试 7：网络速率不参与检测 ----------


def test_high_network_rate_produces_no_anomaly() -> None:
    """网络速率极高但其它指标正常时，仍不应产生任何异常。"""
    metrics = make_metrics(cpu=50, memory=60, disk=70, sent=1000, recv=1000)
    assert detect_anomalies(metrics) == []


def test_network_never_appears_in_anomalies() -> None:
    """即使网络速率爆表，异常列表里也不允许出现任何网络指标。"""
    metrics = make_metrics(cpu=99, memory=99, disk=99, sent=99999, recv=99999)
    anomalies = detect_anomalies(metrics)

    assert len(anomalies) == 3
    for anomaly in anomalies:
        assert not anomaly["metric"].startswith("network"), (
            f"本阶段不应检测网络，但出现了 {anomaly['metric']}"
        )


# ---------- 记录格式 ----------


def test_anomaly_has_exactly_four_fields() -> None:
    """每条异常记录应恰好包含 4 个约定字段。"""
    anomalies = detect_anomalies(make_metrics(cpu=95))

    assert len(anomalies) == 1
    assert set(anomalies[0].keys()) == {"metric", "value", "threshold", "message"}


def test_threshold_in_anomaly_is_ninety() -> None:
    """异常记录中记录的阈值应为 90。"""
    anomalies = detect_anomalies(make_metrics(cpu=95))
    assert anomalies[0]["threshold"] == 90


# ---------- 模块边界 ----------


def test_detector_does_not_import_psutil() -> None:
    """detector 只负责判断，不应该自己采集数据，因此不能依赖 psutil。"""
    source = detection.detector.__file__
    with open(source, encoding="utf-8") as f:
        content = f.read()
    assert "psutil" not in content, "detector.py 不应引入 psutil"


def test_thresholds_are_ninety() -> None:
    """三个固定阈值都应为 90。"""
    assert detection.detector.CPU_THRESHOLD == 90
    assert detection.detector.MEMORY_THRESHOLD == 90
    assert detection.detector.DISK_THRESHOLD == 90


# ---------- 缺失 / 非法输入（防御式取值） ----------


def test_missing_metric_does_not_raise() -> None:
    """指标缺失时跳过该项，而不是抛 KeyError 打断链路。"""
    assert detect_anomalies({"cpu_percent": 95}) == [
        {
            "metric": "cpu_percent",
            "value": 95,
            "threshold": 90,
            "message": "CPU 使用率过高",
        }
    ]


def test_none_metric_is_skipped() -> None:
    """指标为 None 时视为拿不到数据，不算异常。"""
    assert detect_anomalies({"cpu_percent": None, "memory_percent": 10}) == []


def test_string_metric_is_skipped() -> None:
    """指标是字符串时不参与比较，避免 TypeError。"""
    metrics = {"cpu_percent": "95", "memory_percent": 10, "disk_percent": 10}
    assert detect_anomalies(metrics) == []


def test_non_dict_input_does_not_raise() -> None:
    """整体传入 None / 字符串时返回空列表，不抛异常。"""
    assert detect_anomalies(None) == []
    assert detect_anomalies("not-a-dict") == []


def test_nan_is_not_an_anomaly() -> None:
    """NaN 与任何阈值比较都是 False，不应产生误报。"""
    assert detect_anomalies({"cpu_percent": float("nan")}) == []


def test_negative_value_is_not_an_anomaly() -> None:
    """负值不可能超过 90，不应产生误报。"""
    assert detect_anomalies({"cpu_percent": -5}) == []


def test_bool_is_not_treated_as_number() -> None:
    """True 在 Python 里等于 1，不应被当成数值指标。"""
    assert detect_anomalies({"cpu_percent": True}) == []

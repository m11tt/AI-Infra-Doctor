"""基础异常检测。

monitor 模块回答："现在系统是什么状态？"
detection 模块回答："这些指标有没有超过基础阈值？"

本阶段采用最简单的固定阈值检测：指标 > 阈值 判定为异常。
不做时间序列分析、z-score、动态阈值，也不做 AI 故障诊断。
"""

# 固定阈值。数值直接定义在本模块顶部，方便查看和调整。
CPU_THRESHOLD = 90
MEMORY_THRESHOLD = 90
DISK_THRESHOLD = 90

# 参与检测的指标列表，每一项是 (指标名, 阈值, 异常提示语)。
#
# 注意：network_sent_mb_per_sec 和 network_recv_mb_per_sec 故意不写在这里。
# 本阶段只监控网络速率，不判断网络是否异常 ——
# 什么样的网络速率算异常，取决于具体的 AI 工作负载和业务场景，
# 需要在后续阶段结合时间窗口和多指标关系再设计。
CHECK_RULES = [
    ("cpu_percent", CPU_THRESHOLD, "CPU 使用率过高"),
    ("memory_percent", MEMORY_THRESHOLD, "内存使用率过高"),
    ("disk_percent", DISK_THRESHOLD, "磁盘使用率过高"),
]


def detect_anomalies(metrics: dict) -> list:
    """检查指标是否超过固定阈值。

    参数:
        metrics (dict): monitor.system.get_system_metrics() 返回的指标字典。
                       需要包含 cpu_percent、memory_percent、disk_percent。

    返回:
        list: 异常列表。每条异常是一个字典，字段为
              metric(指标名) / value(实际值) / threshold(阈值) / message(提示语)。
              全部正常时返回空列表 []。

    数据缺失时的行为:
        某个指标缺失、为 None 或不是数值时，该指标直接跳过，不产生异常，
        也不会抛异常。检测层只对拿得到的数值下判断。

    示例:
        >>> detect_anomalies({"cpu_percent": 95.2, "memory_percent": 60.0,
        ...                   "disk_percent": 70.0,
        ...                   "network_sent_mb_per_sec": 1.2,
        ...                   "network_recv_mb_per_sec": 2.5})
        [{'metric': 'cpu_percent', 'value': 95.2, 'threshold': 90,
          'message': 'CPU 使用率过高'}]
    """
    anomalies = []

    # 遍历检测规则，逐个比对
    for metric_name, threshold, message in CHECK_RULES:
        # 防御式取值：指标缺失或类型不对时跳过这一项，而不是让整条链路崩掉。
        # 监控指标采集偶尔失败是常态，检测层应该容忍，由调用方决定怎么处理。
        value = metrics.get(metric_name) if isinstance(metrics, dict) else None

        # 只对真正的数值做比较。None、字符串等一律视为"拿不到数据"，不算异常。
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue

        # 注意是 > 不是 >=：正好等于 90 视为正常，超过 90 才算异常。
        if value > threshold:
            anomalies.append(
                {
                    "metric": metric_name,
                    "value": value,
                    "threshold": threshold,
                    "message": message,
                }
            )

    return anomalies

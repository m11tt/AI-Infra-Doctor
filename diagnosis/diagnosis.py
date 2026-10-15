"""多指标关联与初步诊断。

各模块的职责分工：

    monitor     现在系统是什么状态？
    detection   哪些指标超过了基础阈值？
    correlation 多项指标组合起来说明什么？
    diagnosis   根据这些异常，可能发生了什么？

本模块基于可解释规则给出初步诊断：只根据 anomalies 里已经确认的异常，
套用固定的诊断规则，得出"可能发生了什么"的判断。

Stage 5C 起额外接收 correlation_findings，把 correlation 层的关联发现
并入诊断结果。关联发现和普通规则诊断是两个不同概念：
    普通规则诊断   单个指标超阈值就能得出，如"CPU 使用率过高"
    关联发现       多项指标组合才成立，如"疑似 CPU 侧瓶颈"
因此关联发现在结果里会带上 source 标记，便于调用方区分。

本阶段不调用大模型，不请求任何外部 API，不重新采集系统数据。
"""

# 诊断规则：覆盖 CPU、内存、磁盘，以及 CPU + 内存的组合。
#
# 每条规则说明"当 anomalies 里出现某些指标时，应该得出什么判断"。
# 这里必须与 detection 的检测范围保持一致：detection 检测哪些指标，
# 这里就要给出对应的诊断结论，否则会出现"报了警却没有任何结论"的空档。
DIAGNOSIS_RULES = {
    "cpu_percent": {
        "type": "cpu",
        "message": "CPU 使用率过高，可能存在 CPU 计算负载较高",
    },
    "memory_percent": {
        "type": "memory",
        "message": "内存使用率过高，可能存在内存资源紧张",
    },
    "disk_percent": {
        "type": "disk",
        "message": "磁盘使用率过高，可能存在磁盘空间不足或写入压力较大",
    },
}

# 组合诊断规则：当 CPU 和内存同时异常时，额外给出一条综合判断。
COMBINED_RULE = {
    "metrics": ["cpu_percent", "memory_percent"],
    "type": "system",
    "message": "CPU 和内存同时处于高负载状态，系统整体资源压力较大",
}

# 关联发现在诊断结果中的来源标记。
# 调用方可以用它把"关联发现"和"普通规则诊断"区分开：
#   if entry.get("source") == CORRELATION_SOURCE: ...
# 普通规则诊断不带这个字段，输出格式与旧版本保持一致。
CORRELATION_SOURCE = "correlation"


def diagnose(
    metrics: dict,
    anomalies: list,
    correlation_findings: list = None,
) -> list:
    """根据系统指标、已检测出的异常和关联发现，给出初步诊断。

    参数:
        metrics (dict):    monitor.system.get_system_metrics() 返回的指标字典。
                          规则诊断只依赖 anomalies，因此该参数暂未使用；
                          保留它是为了让接口稳定。
        anomalies (list):  detection.detector.detect_anomalies() 返回的异常列表。
        correlation_findings (list): correlation.correlator.correlate() 返回的关联发现。
                          可选，默认 None 表示没有关联发现，此时行为与旧版本完全一致。

    返回:
        list: 诊断列表，分两类：
              - 普通规则诊断：字段为 type / message，由 anomalies 推导；
              - 关联发现：字段为 type / severity / message / source，
                其中 source 恒为 CORRELATION_SOURCE，便于与前者区分。
              没有任何内容时返回空列表 []。

    示例:
        >>> anomalies = [{"metric": "cpu_percent", "value": 95, "threshold": 90,
        ...               "message": "CPU 使用率过高"}]
        >>> diagnose({}, anomalies)
        [{'type': 'cpu', 'message': 'CPU 使用率过高，可能存在 CPU 计算负载较高'}]
        >>> diagnose({}, [], [{"type": "cpu_bottleneck", "severity": "high",
        ...                    "message": "可能存在 CPU 侧瓶颈"}])
        [{'type': 'cpu_bottleneck', 'severity': 'high',
          'message': '可能存在 CPU 侧瓶颈', 'source': 'correlation'}]
    """
    diagnoses = []

    # ---- 普通规则诊断：只根据 anomalies 推导 ----
    # 防御式取值：anomalies 未必是列表，单条异常也未必带 metric 字段。
    # 数据不合法时跳过该条，而不是让整条诊断链路崩掉。
    if anomalies:
        # 把异常列表里的指标名收集成一个集合，方便后面判断"某个指标是否异常"。
        # 例如 anomalies 中有 cpu_percent 时，detected 就是 {"cpu_percent"}。
        detected = {
            item["metric"]
            for item in anomalies
            if isinstance(item, dict) and "metric" in item
        }

        # 逐条套用单指标诊断规则：只要该指标出现在 detected 中就给出一条结论。
        # 规则表与检测范围一一对应，新增检测指标时在这里自动生效，无需改本函数。
        for metric_name, rule in DIAGNOSIS_RULES.items():
            if metric_name in detected:
                diagnoses.append(dict(rule))

        # 组合诊断规则：CPU 和内存同时异常时，额外给出综合判断。
        # 用 all() 判断组合规则要求的指标是否全部出现在 detected 中。
        if all(name in detected for name in COMBINED_RULE["metrics"]):
            diagnoses.append(
                {
                    "type": COMBINED_RULE["type"],
                    "message": COMBINED_RULE["message"],
                }
            )

    # ---- 关联发现：作为独立结论并入，不参与上面的规则判断 ----
    # 复制一份再加 source 标记，既不改调用方传入的原对象，也不改模块常量。
    # 元素非字典时跳过，避免非法输入中断链路。
    for finding in correlation_findings or []:
        if not isinstance(finding, dict):
            continue
        entry = dict(finding)
        entry["source"] = CORRELATION_SOURCE
        diagnoses.append(entry)

    return diagnoses

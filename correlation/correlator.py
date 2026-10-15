"""多指标关联分析。

把系统资源指标和 AI 推理工作负载指标放在一起，找指标之间的关联。

本阶段只实现一个场景：CPU 侧潜在瓶颈。

判断条件（全部同时满足才成立）：
    cpu_percent    > 90    机器 CPU 吃紧
    gpu_utilization < 50    但 GPU 却闲着
    avg_latency_ms  > 200   推理延迟却很高
    queue_length    > 10    而且请求还在堆积

这个组合说明瓶颈可能不在算力侧，而更可能在数据搬运、任务调度等
由 CPU 承担的工作上。

重要：这里给出的只是"可能"，不是已确认的根因。
本模块不调用 LLM，也不执行任何系统操作。
"""

# 关联判定的阈值。全部采用严格不等号：正好等于阈值不算命中。
CPU_PERCENT_HIGH = 90  # CPU 使用率高于此值
GPU_UTILIZATION_LOW = 50  # GPU 利用率低于此值
AVG_LATENCY_MS_HIGH = 200  # 平均延迟高于此值
QUEUE_LENGTH_HIGH = 10  # 队列长度高于此值

# 命中时返回的关联诊断对象。
CPU_BOTTLENECK_FINDING = {
    "type": "cpu_bottleneck",
    "severity": "high",
    "message": (
        "CPU 使用率较高，同时 GPU 利用率较低、推理延迟较高且请求队列较长，"
        "可能存在 CPU 侧数据处理或任务调度瓶颈。"
    ),
}


def correlate(metrics: dict, workload: dict, anomalies: list) -> list:
    """对系统资源指标和 AI 工作负载指标做关联分析。

    参数:
        metrics (dict):   monitor.get_system_metrics() 的结果，含 cpu_percent 等
        workload (dict):  workload.get_inference_metrics() 的结果，含
                          gpu_utilization / avg_latency_ms / queue_length
        anomalies (list): detection.detect_anomalies() 的结果。
                          当前这条规则直接用原始指标判断，不依赖它；
                          保留这个参数是为了后续规则复用检测结果。

    返回:
        list: 关联诊断列表。命中时返回一条，不命中返回空列表 []。

    数据缺失时的行为:
        任一指标缺失时，该规则不成立，返回空列表。
        传入的 metrics / workload 若为 None 或不是字典，同样直接返回空列表。
        关联分析只是增强信息，拿不到数据时宁可不给出结论，
        也不应该让整个链路中断。
    """
    # 防御式取值：入参可能整体为空或类型不对，先归一化成字典再取值。
    # 关联分析是"锦上添花"的一层，绝不能因为拿不到数据就把链路打断。
    if not isinstance(metrics, dict):
        metrics = {}
    if not isinstance(workload, dict):
        workload = {}

    cpu_percent = metrics.get("cpu_percent", 0)
    gpu_utilization = workload.get("gpu_utilization", 100)
    avg_latency_ms = workload.get("avg_latency_ms", 0)
    queue_length = workload.get("queue_length", 0)

    findings = []

    # 规则一：CPU 侧潜在瓶颈
    # 四个条件必须同时成立，缺一不可。
    # 先确认四个值都是数值：类型不对说明数据不可信，直接判定规则不成立，
    # 避免用 None / 字符串去比较而抛 TypeError。
    values = (cpu_percent, gpu_utilization, avg_latency_ms, queue_length)
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        if (
            cpu_percent > CPU_PERCENT_HIGH
            and gpu_utilization < GPU_UTILIZATION_LOW
            and avg_latency_ms > AVG_LATENCY_MS_HIGH
            and queue_length > QUEUE_LENGTH_HIGH
        ):
            # 返回副本，避免调用方改坏模块常量。
            findings.append(dict(CPU_BOTTLENECK_FINDING))

    return findings

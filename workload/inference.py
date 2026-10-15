"""AI 推理工作负载指标。

本阶段返回固定的模拟数据，用于打通链路和验证数据结构。

后续阶段会替换成真实采集：
    request_count      来自推理服务的请求计数
    avg_latency_ms     来自推理服务的延迟统计
    queue_length       来自推理服务的队列长度
    gpu_utilization    来自 GPU 利用率采集

本阶段不连接 GPU / CUDA / CANN，也不访问任何外部服务。
"""

# 模拟数据。集中定义在这里，方便将来整体替换成真实采集。
MOCK_INFERENCE_METRICS = {
    "request_count": 100,
    "avg_latency_ms": 350.0,
    "queue_length": 18,
    "gpu_utilization": 35.0,
}


def get_inference_metrics() -> dict:
    """获取 AI 推理工作负载指标。

    返回:
        dict: 包含以下 4 个字段的字典
            - request_count (int):    累计推理请求数
            - avg_latency_ms (float): 平均推理延迟，单位毫秒
            - queue_length (int):     等待处理的请求队列长度
            - gpu_utilization (float): GPU 使用率，0-100

    注意:
        当前返回的是模拟数据。返回值是常量的一份副本，
        调用方修改它不会影响后续调用。
    """
    return dict(MOCK_INFERENCE_METRICS)

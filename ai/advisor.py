"""AI 诊断输入构造。

本模块把上游三个阶段的结果（系统指标、异常、基础诊断）整理成两种产物：

    build_ai_context()       结构化上下文，给程序用
    build_diagnosis_prompt() 完整 Prompt 文本，给大模型用

本阶段只负责"把上下文准备好"，不调用任何大模型，也不发起任何网络请求。
真正的模型接入在下一个阶段（Stage 4B）完成。
"""

import copy

# 指标的展示顺序和单位。
# 顺序写死，保证每次生成的 Prompt 可读、可测试。
# 单位必须写清楚：大模型看到裸数字无法判断 95 是 95% 还是 95MB/s。
METRIC_LABELS = [
    ("cpu_percent", "CPU 使用率 (CPU Utilization)", "%"),
    ("memory_percent", "内存使用率 (Memory Utilization)", "%"),
    ("disk_percent", "磁盘使用率 (Disk Utilization)", "%"),
    ("network_sent_mb_per_sec", "网络发送速率 (Network Sent Rate)", "MB/s"),
    ("network_recv_mb_per_sec", "网络接收速率 (Network Recv Rate)", "MB/s"),
]

# 要求大模型返回的结构。明确指定格式，模型输出才能被程序稳定解析。
OUTPUT_FORMAT = """{
    "summary": "一句话概括当前系统状态",
    "root_cause": "可能的根本原因分析",
    "risk": "如果不处理可能存在的风险",
    "recommendations": [
        "优化建议 1",
        "优化建议 2",
        "优化建议 3"
    ]
}"""


def _format_metrics(metrics: dict) -> str:
    """把指标字典格式化成带单位的多行文本。"""
    lines = []
    for key, label, unit in METRIC_LABELS:
        value = metrics.get(key, "N/A")
        lines.append(f"- {label}: {value} {unit}")
    return "\n".join(lines)


def _format_anomalies(anomalies: list) -> str:
    """把异常列表格式化成多行文本。"""
    if not anomalies:
        return "- 未检测到超过阈值的异常"
    lines = []
    for item in anomalies:
        lines.append(
            f"- {item.get('metric')} = {item.get('value')} "
            f"(阈值 {item.get('threshold')}): {item.get('message')}"
        )
    return "\n".join(lines)


def _format_diagnoses(diagnoses: list) -> str:
    """把基础诊断列表格式化成多行文本。"""
    if not diagnoses:
        return "- 无基础诊断结果"
    lines = []
    for item in diagnoses:
        lines.append(f"- [{item.get('type')}] {item.get('message')}")
    return "\n".join(lines)


def _format_correlation_findings(findings: list) -> str:
    """把多指标关联发现格式化成多行文本。"""
    if not findings:
        return "未发现指标之间的异常关联。"
    lines = []
    for item in findings:
        lines.append(
            f"- 类型 [{item.get('type')}] / 严重程度 [{item.get('severity')}]："
            f"{item.get('message')}"
        )
    return "\n".join(lines)


# 关联发现章节的固定说明。
# 这段话每次都出现在 Prompt 里，用来提醒模型：关联发现只是线索，不是已确认的根因。
CORRELATION_CAVEAT = (
    "以下关联发现由系统基于当前可观测指标的多项组合推导得出，"
    "属于**可能的线索，而不是已经确认的根因**。\n"
    "请把它当作待验证的假设，并在分析中说明还需要哪些信息才能确认。"
)


def build_ai_context(
    metrics: dict,
    anomalies: list,
    diagnoses: list,
    correlation_findings: list = None,
) -> dict:
    """把上游数据打包成结构化 AI 上下文。

    参数:
        metrics (dict):    系统指标
        anomalies (list):  检测到的异常
        diagnoses (list):  规则得出的基础诊断
        correlation_findings (list): 多指标关联发现。
                          可选，默认 None 表示没有关联发现。

    返回:
        dict: 新字典。传入 correlation_findings 时包含四个键
              metrics / anomalies / diagnoses / correlation_findings；
              不传时只有前三个键——这样旧调用
              build_ai_context(metrics, anomalies, diagnoses)
              的返回结构完全不变。

    使用 copy.deepcopy 做深拷贝：返回的字典和传入的数据完全独立，
    调用方之后怎么修改返回值，都不会影响原始数据，反之亦然。
    """
    context = {
        "metrics": copy.deepcopy(metrics),
        "anomalies": copy.deepcopy(anomalies),
        "diagnoses": copy.deepcopy(diagnoses),
    }

    # 只有调用方明确传入时才加这个键，保证旧调用的结构一字不变。
    if correlation_findings is not None:
        context["correlation_findings"] = copy.deepcopy(correlation_findings)

    return context


def build_diagnosis_prompt(
    metrics: dict,
    anomalies: list,
    diagnoses: list,
    correlation_findings: list = None,
) -> str:
    """生成用于请求大模型诊断的完整 Prompt。

    Prompt 不只丢一句"CPU 很高"，而是带上完整的结构化上下文：
    系统指标 + 异常 + 基础诊断 + 多指标关联发现。
    模型在已有事实的基础上做进一步分析，比从零猜测要准确得多。

    参数:
        metrics (dict):    系统指标
        anomalies (list):  检测到的异常
        diagnoses (list):  规则得出的基础诊断
        correlation_findings (list): 多指标关联发现。可选，默认 None。

    返回:
        str: 完整的 Prompt 文本。
    """
    return f"""你是一名 AI Infra 运维诊断助手。

## 一、当前系统指标

{_format_metrics(metrics)}

## 二、检测到的异常

{_format_anomalies(anomalies)}

## 三、基础诊断结果

以下结论由系统的固定阈值规则得出，是已经确认的事实：

{_format_diagnoses(diagnoses)}

## 四、多指标关联发现

{CORRELATION_CAVEAT}

{_format_correlation_findings(correlation_findings)}

## 五、分析要求

请基于以上已经确认的事实，进行进一步分析：

1. 根因分析 (root cause)：结合各项指标的关联关系，判断最可能的根本原因。
2. 风险评估 (risk)：如果这些问题不处理，可能会带来什么后果。
3. 优化建议 (recommendations)：给出具体、可执行的优化建议。

## 六、权限限制

你只能进行分析和建议，**不能执行任何系统操作**。
不要建议或执行任何会改变系统状态的动作，例如终止进程、修改配置、
清理文件、重启服务或安装软件。所有操作都必须由人工判断后执行。

## 七、输出格式

请严格按照以下 JSON 结构返回，不要输出任何多余内容：

{OUTPUT_FORMAT}"""

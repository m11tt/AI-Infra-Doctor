"""系统资源采集。

基于 psutil 采集当前机器的基础系统资源信息。

本模块只负责"采集和计算监控指标"，不判断是否异常。
"是否异常"属于 detection 模块的职责，不要在这里写判断逻辑。
"""

import time

import psutil

# 字节换算成 MB 用的除数：1 MB = 1024 * 1024 字节
BYTES_PER_MB = 1024 * 1024

# 保存"上一次"的网络累计字节数和采样时刻。
# 模块级变量，让两次调用之间可以传递数据，无需数据库或缓存系统。
# 初始为 None，表示程序刚启动、还没有上一次采样。
_previous_net_io = None
_previous_sampled_at = None


def get_system_metrics() -> dict:
    """获取当前机器的基础系统资源指标。

    网络速率通过"两次采样的累计字节数之差 ÷ 真实时间间隔"计算得出。
    因为必须有上一次的数据做对比，第一次调用时两个网络速率返回 0.0，
    第二次及以后的调用才返回真实速率。

    返回:
        dict: 包含以下 5 个字段的字典
            - cpu_percent (float):           CPU 使用率，0-100
            - memory_percent (float):        内存使用率，0-100
            - disk_percent (float):          系统磁盘使用率，0-100
            - network_sent_mb_per_sec (float): 网络发送速率，单位 MB/s
            - network_recv_mb_per_sec (float): 网络接收速率，单位 MB/s
    """
    global _previous_net_io, _previous_sampled_at

    # ---- CPU ----
    # CPU 使用率。interval=0.1 表示先采样 0.1 秒再和上一次对比。
    # 不传 interval 的话，第一次调用只会返回 0.0（因为没有对比基准）。
    cpu_percent = psutil.cpu_percent(interval=0.1)

    # ---- 内存 ----
    # virtual_memory() 返回一个内存信息对象，
    # 里面的 percent 字段就是 0-100 的使用率。
    memory_percent = psutil.virtual_memory().percent

    # ---- 磁盘 ----
    # "/" 在 Windows 上表示系统盘，在 Linux/macOS 上表示根目录。
    disk_percent = psutil.disk_usage("/").percent

    # ---- 网络速率 ----
    # psutil.net_io_counters() 给的是"开机以来的累计字节数"，
    # 本身不表示当前负载，所以要用两次采样的差值除以时间间隔。
    net_io = psutil.net_io_counters()

    # 用 monotonic 而不是 time()：它表示单调递增的秒数，
    # 系统时钟被校准时不会跳变，算时间间隔更可靠。
    sampled_at = time.monotonic()

    if _previous_net_io is None:
        # 第一次调用，没有上一次数据可比，速率视为 0.0。
        network_sent_mb_per_sec = 0.0
        network_recv_mb_per_sec = 0.0
    else:
        # 真实的采样间隔（秒），不假设它正好等于 1 秒。
        elapsed = sampled_at - _previous_sampled_at

        # 字节差 ÷ 秒 = 字节/秒，再换算成 MB/s。
        sent_delta = net_io.bytes_sent - _previous_net_io.bytes_sent
        recv_delta = net_io.bytes_recv - _previous_net_io.bytes_recv
        network_sent_mb_per_sec = round(sent_delta / elapsed / BYTES_PER_MB, 2)
        network_recv_mb_per_sec = round(recv_delta / elapsed / BYTES_PER_MB, 2)

    # 把本次采样存下来，供下一次调用做对比。
    _previous_net_io = net_io
    _previous_sampled_at = sampled_at

    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "disk_percent": disk_percent,
        "network_sent_mb_per_sec": network_sent_mb_per_sec,
        "network_recv_mb_per_sec": network_recv_mb_per_sec,
    }

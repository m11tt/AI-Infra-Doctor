"""FastAPI 应用入口。

当前提供的只读接口：

    GET /                服务存活检查
    GET /api/v1/status   完整诊断链路的统一状态快照

以及一个静态页面：

    GET /dashboard       AI Infra Doctor 监控 Dashboard

/api/v1/status 本身不做任何判断，它只是按固定顺序把现有各层串起来，
让前端一次请求就能拿到全链路结果。
Dashboard 只负责展示，不实现任何监控或诊断逻辑。
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from correlation.correlator import correlate
from detection.detector import detect_anomalies
from diagnosis.diagnosis import diagnose
from monitor.system import get_system_metrics
from workload.inference import get_inference_metrics

app = FastAPI(
    title="AI Infra Doctor",
    description="面向 AI 工作负载的智能监控与故障诊断工具",
    version="0.1.0",
)

# 前端静态资源目录。用 __file__ 推算路径，不依赖启动时的工作目录。
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


# 统一下发的安全响应头。
#
# 为什么需要：Dashboard 是浏览器直接访问的页面，缺失这些头会留下
# 点击劫持（iframe 嵌套）和 MIME 嗅探的隐患。这里集中下发，避免
# 每个路由各写一遍。
#
# CSP 说明：页面用到的都是本站资源（本地 ECharts + 内联事件），
# 因此限制为 self；ECharts 需要 style 内联，所以 style-src 放开
# 'unsafe-inline'。没有引入任何第三方域名，不需要额外白名单。
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    ),
}


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """给所有响应补上安全头。"""
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@app.get("/")
async def read_root() -> dict[str, str]:
    """服务存活检查。"""
    return {
        "project": "AI Infra Doctor",
        "status": "running",
    }


@app.get("/api/v1/status")
def read_status() -> dict:
    """返回当前完整诊断链路的统一快照。

    调用链（严格按顺序，任何一层都不跳过）：

        1. get_system_metrics()                  系统资源指标
        2. get_inference_metrics()               AI 工作负载指标
        3. detect_anomalies(metrics)             普通资源异常
        4. correlate(metrics, workload, ...)     多指标关联发现
        5. diagnose(metrics, anomalies, ...)     综合诊断
        6. 返回统一 JSON

    这里刻意用同步的 def 而不是 async def：
    get_system_metrics() 里 CPU 采样会阻塞约 0.1 秒，
    FastAPI 会把同步路由放进线程池执行，这样不会卡住事件循环。
    """
    # 1. 系统资源指标
    metrics = get_system_metrics()

    # 2. AI 工作负载指标（当前为模拟数据）
    workload = get_inference_metrics()

    # 3. 普通资源异常检测
    anomalies = detect_anomalies(metrics)

    # 4. 多指标关联发现
    correlation_findings = correlate(metrics, workload, anomalies)

    # 5. 综合诊断（规则诊断 + 关联发现）
    diagnoses = diagnose(metrics, anomalies, correlation_findings)

    # 6. 统一返回
    return {
        "metrics": metrics,
        "workload": workload,
        "anomalies": anomalies,
        "correlation_findings": correlation_findings,
        "diagnoses": diagnoses,
    }


# ---------- 静态 Dashboard ----------
#
# 挂载顺序很重要：/dashboard 路由必须在 mount 之前注册，
# 否则 StaticFiles 会先接管这个路径。

# 静态资源（style.css / app.js），例如 /dashboard/style.css
app.mount("/dashboard", StaticFiles(directory=FRONTEND_DIR, html=True), name="dashboard")


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> FileResponse:
    """返回 Dashboard 页面。

    显式声明这条路由是为了直接返回 200。
    只靠 StaticFiles 的话，访问 /dashboard 可能先收到一个重定向。

    这不是 API，不进 OpenAPI 文档。
    """
    return FileResponse(FRONTEND_DIR / "index.html")

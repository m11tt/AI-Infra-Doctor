"""Dashboard 测试。

覆盖静态页面能否访问、页面内容是否包含关键信息、
以及前端没有引入构建工具链和自动刷新。

本文件不访问互联网：ECharts 是浏览器端 CDN 引入的，
测试只读取服务端返回的 HTML / CSS / JS 文本。
"""

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# 前端不允许出现的前端框架 / 构建工具痕迹。
# 这里用精确的 token，而不是裸露的关键词：
# 例如 CDN 地址里本来就含 "/npm/" 这个路径段，
# 裸查 "npm" 会误报。要查的是真正使用包管理器的痕迹。
FORBIDDEN_FRONTEND_TOKENS = [
    "react",
    "vue.js",
    "vue.min",
    "angular",
    "svelte",
    "webpack",
    "vite.config",
    "rollup",
    "parcel",
    "typescript",
    ".jsx",
    ".tsx",
    "package.json",
    "node_modules",
    "npm install",
    "npm run",
    "npm ci",
    "yarn ",
    "pnpm ",
    "babel",
]

# Stage 6C 起，setInterval 轮询是允许且期望的。
# 这里只列出仍然禁止的刷新手段：WebSocket、SSE、rAF 循环。
FORBIDDEN_REFRESH_TOKENS = [
    "WebSocket",
    "EventSource",
    "requestAnimationFrame",
]


def dashboard_html() -> str:
    return client.get("/dashboard").text


def dashboard_script() -> str:
    return client.get("/dashboard/app.js").text


def dashboard_all() -> str:
    """页面完整内容 = HTML + CSS + JS。

    fetch 调用写在 app.js 里，只看 HTML 会漏掉，
    所以三份文件合起来看才是"这个页面"。
    """
    return "\n".join(
        [
            client.get("/dashboard").text,
            client.get("/dashboard/style.css").text,
            client.get("/dashboard/app.js").text,
        ]
    )


# ---------- 1~3. 路由可达性 ----------


def test_root_still_works() -> None:
    """GET / 必须保持原样。"""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "project": "AI Infra Doctor",
        "status": "running",
    }


def test_status_api_still_works() -> None:
    """GET /api/v1/status 必须保持原样。"""
    response = client.get("/api/v1/status")
    assert response.status_code == 200

    payload = response.json()
    assert set(payload.keys()) == {
        "metrics",
        "workload",
        "anomalies",
        "correlation_findings",
        "diagnoses",
    }


def test_dashboard_returns_200() -> None:
    """GET /dashboard 应返回 200。"""
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


# ---------- 4. 页面标题 ----------


def test_dashboard_contains_project_title() -> None:
    """页面应包含 AI Infra Doctor。"""
    html = dashboard_html()
    assert "AI Infra Doctor" in html


def test_dashboard_contains_subtitle() -> None:
    """页面应包含副标题。"""
    assert "AI Workload Monitoring" in dashboard_html()


# ---------- 5. 页面会请求状态 API ----------


def test_dashboard_fetches_status_api() -> None:
    """页面脚本应请求 /api/v1/status。

    用正则而不是精确字符串：引号写成单引号或双引号都算对，
    写死一种引号会让测试在无意义的格式变动上失败。
    """
    script = dashboard_script()
    assert re.search(r"""fetch\(\s*["']/api/v1/status["']""", script)


# ---------- 6. 页面包含关键展示内容 ----------


def test_dashboard_shows_system_metrics() -> None:
    """页面应展示 CPU / 内存 / 磁盘 / 网络。"""
    content = dashboard_all()
    for keyword in ["CPU", "内存", "磁盘", "网络发送", "网络接收"]:
        assert keyword in content, f"页面缺少系统资源展示：{keyword}"


def test_dashboard_shows_workload_metrics() -> None:
    """页面应展示四个 AI 工作负载指标。"""
    content = dashboard_all()
    for keyword in ["Request Count", "Average Latency", "Queue Length", "GPU Utilization"]:
        assert keyword in content, f"页面缺少工作负载展示：{keyword}"


def test_dashboard_shows_anomaly_and_diagnosis_sections() -> None:
    """页面应包含异常、关联发现、诊断三个区域。"""
    html = dashboard_html()
    for keyword in ["Anomalies", "Correlation Findings", "Diagnosis"]:
        assert keyword in html, f"页面缺少区域：{keyword}"


def test_dashboard_has_all_empty_state_messages() -> None:
    """三种空状态文案都要有，对应 API 返回空列表时的表现。"""
    script = dashboard_script()
    for message in [
        "当前未检测到资源异常",
        "当前未发现明显的多指标关联问题",
        "当前系统运行正常，暂无诊断建议",
    ]:
        assert message in script, f"缺少空状态文案：{message}"


def test_dashboard_uses_echarts_for_charts() -> None:
    """页面应引入 ECharts 并用于绘图。"""
    content = dashboard_all()
    assert "echarts" in content
    assert "gauge" in content


# ---------- 7. 前端文件存在 ----------


@pytest.mark.parametrize(
    "filename", ["index.html", "style.css", "app.js"]
)
def test_frontend_files_exist(filename: str) -> None:
    """前端三个文件必须存在。"""
    path = FRONTEND_DIR / filename
    assert path.is_file(), f"缺少前端文件：{path}"
    assert path.stat().st_size > 0, f"前端文件为空：{path}"


@pytest.mark.parametrize(
    "route", ["/dashboard", "/dashboard/style.css", "/dashboard/app.js"]
)
def test_static_assets_served(route: str) -> None:
    """静态资源都应能被服务端返回。"""
    assert client.get(route).status_code == 200


# ---------- 8. 不引入前端框架 / 构建工具 ----------


def test_no_frontend_framework() -> None:
    """不得引入 React/Vue 等框架或构建工具链。"""
    content = dashboard_all().lower()
    for token in FORBIDDEN_FRONTEND_TOKENS:
        assert token not in content, f"前端不应出现 {token}"


def test_no_package_manager_config() -> None:
    """仓库里不应出现 package.json 这类 Node 生态文件。"""
    assert not (FRONTEND_DIR / "package.json").exists()


# ---------- 自动刷新（Stage 6C 才做，本阶段禁止）----------


def test_uses_interval_polling() -> None:
    """Stage 6C 起应使用定时轮询自动刷新。"""
    script = dashboard_script()

    assert "setInterval" in script
    assert "REFRESH_INTERVAL" in script


def test_refresh_interval_is_two_seconds() -> None:
    """刷新间隔应为 2000 毫秒。"""
    assert re.search(r"REFRESH_INTERVAL\s*=\s*2000\b", dashboard_script())


def test_initial_load_happens_before_polling() -> None:
    """打开页面应立即请求一次，然后再开始定时轮询。

    顺序很重要：先 refreshOnce() 再 setInterval()，
    否则用户要等满一个周期才能看到第一屏数据。
    """
    script = dashboard_script()

    body = script[script.index("function startAutoRefresh") :]
    immediate = body.index("refreshOnce();")
    polling = body.index("setInterval(")
    assert immediate < polling, "应先立即请求一次，再启动定时轮询"


def test_still_uses_fetch_not_websocket() -> None:
    """刷新必须走 fetch 轮询，不得引入 WebSocket 或 SSE。"""
    script = dashboard_script()

    assert 'fetch("/api/v1/status")' in script
    for forbidden in ["WebSocket", "EventSource", "new WebSocket"]:
        assert forbidden not in script, f"不应使用 {forbidden}"


def test_no_request_animation_frame_loop() -> None:
    """不应改用 requestAnimationFrame 驱动刷新。"""
    assert "requestAnimationFrame" not in dashboard_script()


def test_no_full_page_reload() -> None:
    """更新数据不应触发整页刷新。"""
    script = dashboard_script()

    for forbidden in ["location.reload", "location.href =", "document.location"]:
        assert forbidden not in script, f"不应整页刷新：{forbidden}"


def test_request_failure_keeps_previous_data() -> None:
    """请求失败时只提示，不清空已有数据。

    判据是 catch 分支里只调用状态提示函数，
    不能出现清空容器或重新 render 空数据的动作。
    """
    script = dashboard_script()
    body = script[script.index("function refreshOnce") :]
    body = body[: body.index("function startAutoRefresh")]

    assert ".catch(" in body, "refreshOnce 应有失败处理"
    assert "setHealthError" in body, "失败时应给出提示"

    for forbidden in ["textContent = \"\"", "buildCards", "render(", "innerHTML"]:
        assert forbidden not in body, f"失败分支不应清空数据：{forbidden}"


def test_error_message_says_data_is_kept() -> None:
    """失败提示应明确说明保留了上次数据。"""
    assert "保留上次数据" in dashboard_script()


def test_charts_are_created_once_not_every_poll() -> None:
    """图表实例只能创建一次，否则每次轮询都会泄漏一个实例和 resize 监听器。"""
    script = dashboard_script()

    assert script.count("echarts.init(") == 1, (
        "echarts.init 只应出现一次（创建实例），"
        "后续刷新应使用 setOption 更新数值"
    )
    assert "setOption" in script, "后续刷新应通过 setOption 更新图表"


def test_resize_listener_bound_once() -> None:
    """resize 监听只应绑定一次，避免越开越卡。"""
    script = dashboard_script()

    assert script.count('addEventListener("resize"') == 1
    assert "resizeBound" in script


def test_cards_are_updated_in_place() -> None:
    """数字卡片应复用 DOM，只改数值文本，避免每 2 秒闪烁。"""
    script = dashboard_script()

    assert "buildCards" in script
    assert "updateCards" in script
    assert "cardRefs" in script


# ---------- 前端不重写业务逻辑 ----------


def test_frontend_only_consumes_api_fields() -> None:
    """前端只消费 API 返回的字段，不自己造数据。

    这几个字段名都是后端接口契约，前端必须原样使用，
    一旦前端自己改名或自己计算，就说明逻辑被搬到前端了。
    """
    script = dashboard_script()
    for field in [
        "metrics",
        "workload",
        "anomalies",
        "correlation_findings",
        "diagnoses",
        "correlation",
    ]:
        assert field in script, f"前端未消费后端字段：{field}"


def test_dashboard_marks_correlation_source_distinctly() -> None:
    """前端应区分"关联发现"和"规则诊断"两种来源。"""
    script = dashboard_script()
    assert "关联发现" in script
    assert "规则诊断" in script


# ---------- 浏览器真实解析出来的资源地址必须可用 ----------


def test_all_page_resources_resolve_and_load() -> None:
    """按浏览器的规则解析页面里的 href/src，然后逐个请求，必须都是 200。

    这条测试专门防一个很容易漏的坑：
    页面地址是 /dashboard（没有尾斜杠），如果 HTML 里写相对的
    href="style.css"，浏览器会把它解析成 /style.css 而不是
    /dashboard/style.css，结果 CSS 和 JS 全部 404、页面一片空白。

    只测 /dashboard/style.css 是发现不了这个问题的，
    必须模拟浏览器的相对路径解析。
    """
    page_url = "http://testserver/dashboard"
    html = dashboard_html()

    refs = re.findall(r'(?:href|src)="([^"]+)"', html)
    # 排除外链（CDN 等），只验证本地资源
    local_refs = [r for r in refs if not r.startswith("http")]

    assert local_refs, "页面应至少引用一个本地资源"

    for ref in local_refs:
        resolved = urljoin(page_url, ref)
        path = urlparse(resolved).path

        response = client.get(path)
        assert response.status_code == 200, (
            f"页面引用的 {ref} 解析成 {path}，返回 {response.status_code}。"
            f"相对路径在 /dashboard 下会被解析错，建议改用绝对路径。"
        )


def test_echarts_is_not_a_blocking_script_tag() -> None:
    """ECharts 不能是阻塞式 <script>，否则 CDN 慢时整个页面都渲染不出来。

    echarts.min.js 约 1MB，如果同步写在 app.js 前面，
    浏览器会卡在下载上，后面的脚本根本不执行。
    """
    html = dashboard_html()

    for ref in re.findall(r'<script[^>]*src="([^"]+)"', html):
        assert not ref.startswith("http"), (
            f"页面里有同步外链脚本 {ref}，CDN 慢会导致整页阻塞。"
            f"应改为在 app.js 里动态加载。"
        )


def test_chart_fallback_is_cleared_when_charts_load() -> None:
    """图表库就绪后必须撤掉文字兜底。

    漏掉这一步有两个后果：兜底文字会压在仪表盘上，
    而且 .chart-fallback 的样式会把图表容器高度压扁。
    """
    script = dashboard_script()

    assert "chart-fallback" in script, "应存在图表文字兜底逻辑"
    assert "classList.remove" in script, (
        "图表就绪后应移除 chart-fallback 类，否则文字会叠在图表上"
    )


def test_chart_fallback_css_keeps_chart_height() -> None:
    """.chart-fallback 不应覆盖 .chart 的固定高度。"""
    css = client.get("/dashboard/style.css").text

    # 取出 .chart-fallback 规则块
    block = re.search(r"\.chart-fallback\s*\{([^}]*)\}", css)
    assert block, "未找到 .chart-fallback 样式"

    assert "height" not in block.group(1), (
        ".chart-fallback 不应设置 height，否则会把图表容器高度压扁"
    )


# ================================================================
# ECharts 本地化：断网也能显示
# ================================================================

VENDOR_DIR = FRONTEND_DIR / "vendor"
VENDOR_FILE = VENDOR_DIR / "echarts.min.js"
VENDOR_ROUTE = "/dashboard/vendor/echarts.min.js"


def test_local_echarts_file_exists() -> None:
    """本地 ECharts 文件必须存在且非空。"""
    assert VENDOR_FILE.is_file(), f"缺少本地 ECharts：{VENDOR_FILE}"
    assert VENDOR_FILE.stat().st_size > 500_000, (
        f"本地 ECharts 文件异常小（{VENDOR_FILE.stat().st_size} bytes），可能下载不完整"
    )


def test_local_echarts_is_really_echarts() -> None:
    """校验文件内容确实是 ECharts，而不是下载失败的错误页。"""
    text = VENDOR_FILE.read_text(encoding="utf-8", errors="replace")

    for marker in ["echarts", "zrender", "Apache"]:
        assert marker in text, f"本地文件缺少 {marker} 标识，可能不是 ECharts"


def test_local_echarts_served_over_http() -> None:
    """本地 ECharts 必须能通过 HTTP 访问。"""
    response = client.get(VENDOR_ROUTE)

    assert response.status_code == 200, f"{VENDOR_ROUTE} 返回 {response.status_code}"
    assert len(response.content) == VENDOR_FILE.stat().st_size
    assert "javascript" in response.headers["content-type"]


def test_no_cdn_dependency_in_frontend() -> None:
    """前端不得再依赖 CDN，断网也必须可用。

    检查范围是 HTML / CSS / app.js 三个文件，
    也就是"页面本身"，不包括 vendor 里的第三方库源码
    （第三方库内部可能带有自己的网址注释，那不是依赖）。
    """
    for name in ["index.html", "style.css", "app.js"]:
        content = (FRONTEND_DIR / name).read_text(encoding="utf-8")

        for host in ["cdn.jsdelivr", "unpkg.com", "cdnjs", "bootcdn", "npmmirror"]:
            assert host not in content, f"{name} 仍依赖外部 CDN：{host}"

        # 不应有任何指向外部站点的脚本/样式引用
        for ref in re.findall(r'(?:src|href)="(https?://[^"]+)"', content):
            assert False, f"{name} 引用了外部资源：{ref}"


def test_app_js_points_to_local_echarts() -> None:
    """app.js 必须从本地 vendor 路径加载 ECharts。"""
    script = dashboard_script()

    assert "/dashboard/vendor/echarts.min.js" in script
    assert "echarts.min.js" in script


def test_no_auto_refresh_still_holds() -> None:
    """刷新机制只用 setInterval 轮询，不得混入其它刷新手段。"""
    content = "\n".join(
        [
            dashboard_html(),
            dashboard_script(),
            client.get("/dashboard/style.css").text,
        ]
    )

    for token in FORBIDDEN_REFRESH_TOKENS:
        assert token not in content, f"不应出现 {token}"


# ---------- 前后端阈值一致性 ----------


def test_frontend_threshold_values_match_backend() -> None:
    """前端"异常级"阈值必须与后端 detection 的阈值一致。

    PERCENT_BAD 是"异常级"颜色，必须等于后端的检测阈值（90）；
    PERCENT_WARN 是介于之间的"偏高"提示色，只需小于异常级即可。
    """
    from detection.detector import CPU_THRESHOLD, DISK_THRESHOLD, MEMORY_THRESHOLD

    script = dashboard_script()
    bad = re.search(r"PERCENT_BAD\s*=\s*(\d+)", script)
    warn = re.search(r"PERCENT_WARN\s*=\s*(\d+)", script)

    assert bad is not None and warn is not None
    assert int(bad.group(1)) == CPU_THRESHOLD == MEMORY_THRESHOLD == DISK_THRESHOLD
    assert int(bad.group(1)) == 90
    # 提示级必须严格低于异常级，否则两档颜色会重叠。
    assert int(warn.group(1)) < int(bad.group(1))


def test_frontend_uses_strict_greater_than_for_bad_level() -> None:
    """前端标红必须用严格大于，与后端 value > 90 保持一致。

    如果写成 >= 90，指标正好 90.0 时会出现"卡片标红但异常列表为空"
    的自相矛盾，这里把它钉死。
    """
    script = dashboard_script()

    assert "value > PERCENT_BAD" in script
    assert "value >= PERCENT_BAD" not in script
    assert "value > PERCENT_WARN" in script
    assert "value >= PERCENT_WARN" not in script

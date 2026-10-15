// AI Infra Doctor Dashboard
//
// 职责很单纯：调用 GET /api/v1/status，把返回的 JSON 渲染到页面上。
// 这里不做任何监控、检测、关联或诊断判断——那些全部由后端各层负责。
//
// 页面打开后立即请求一次，之后每 2 秒轮询一次，只更新页面上的数据和图表，
// 不会整页刷新。
//
// ECharts 的加载策略：先渲染数字，再异步加载图表库。
// 因为 echarts.min.js 有 1MB 左右，如果用普通的 <script> 标签同步引入，
// 网络慢时浏览器会卡在下载上，后面的脚本根本不会执行，页面一片空白。
// 所以这里改成"数据先显示、图表后补齐"。

// ---------- 指标展示配置 ----------

const METRIC_CARDS = [
  { key: "cpu_percent", label: "CPU 使用率", unit: "%", max: 100 },
  { key: "memory_percent", label: "内存使用率", unit: "%", max: 100 },
  { key: "disk_percent", label: "磁盘使用率", unit: "%", max: 100 },
  { key: "network_sent_mb_per_sec", label: "网络发送速率", unit: "MB/s" },
  { key: "network_recv_mb_per_sec", label: "网络接收速率", unit: "MB/s" },
];

const WORKLOAD_CARDS = [
  { key: "request_count", label: "Request Count", unit: "" },
  { key: "avg_latency_ms", label: "Average Latency", unit: "ms" },
  { key: "queue_length", label: "Queue Length", unit: "" },
  { key: "gpu_utilization", label: "GPU Utilization", unit: "%", max: 100 },
];

// 后端 detection 的固定阈值，前端只用来给数字上色，不重新判断。
//
// 关键：这里的比较方式必须和后端 detection 严格一致——后端用
// `value > 90` 判定异常（正好等于 90 算正常），所以这里也必须是
// 严格大于。如果前端写成 `>= 90`，当指标恰好为 90.0 时会出现
// "卡片标红、但异常列表为空" 的自相矛盾现象。
const PERCENT_WARN = 70;
const PERCENT_BAD = 90;

// 自动刷新间隔（毫秒）。
const REFRESH_INTERVAL = 2000;

// ---------- 小工具 ----------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function levelOf(value, max) {
  if (typeof value !== "number" || !max) return "";
  // 与后端一致：严格大于阈值才算异常级别。
  if (value > PERCENT_BAD) return "bad";
  if (value > PERCENT_WARN) return "warn";
  return "ok";
}

function nowText() {
  const d = new Date();
  const pad = function (n) {
    return n < 10 ? "0" + n : String(n);
  };
  return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
}

// ---------- 数字卡片 ----------

// 卡片只创建一次，之后只改数字文本。
// 如果每次刷新都重建 DOM，数字会不停闪烁。
const cardRefs = {};

function buildCards(containerId, items, source) {
  const box = document.getElementById(containerId);
  box.textContent = "";

  cardRefs[containerId] = items.map(function (item) {
    const card = el("div", "card");
    card.appendChild(el("div", "label", item.label));

    const valueNode = el("div", "value");
    const num = el("span", "num", "0");
    valueNode.appendChild(num);
    if (item.unit) valueNode.appendChild(el("span", "unit", item.unit));

    card.appendChild(valueNode);
    box.appendChild(card);

    return { card: card, num: num, item: item };
  });

  updateCards(containerId, source);
}

function updateCards(containerId, source) {
  const refs = cardRefs[containerId] || [];
  refs.forEach(function (ref) {
    const value = source[ref.item.key];
    ref.num.textContent = value === undefined ? "N/A" : String(value);

    const level = levelOf(value, ref.item.max);
    ref.card.classList.remove("ok", "warn", "bad");
    if (level) ref.card.classList.add(level);
  });
}

// ---------- 图表 ----------

// ECharts 从项目本地静态资源加载，不再依赖 CDN。
//
// 为什么本地化：比赛现场网络不可控，CDN 一旦慢或不通，
// 图表就出不来。本地副本由 FastAPI 一起提供，断网也能正常显示。
const ECHARTS_SRC = "/dashboard/vendor/echarts.min.js";

// 等待 ECharts 的最长时间（毫秒），超时就走文字兜底。
const ECHARTS_TIMEOUT = 6000;

function showChartFallback(domId, title, value) {
  const box = document.getElementById(domId);
  box.classList.add("chart-fallback");
  box.textContent = title + "：" + (value === undefined ? "N/A" : value) + "%";
}

function gaugeOption(title, color, value) {
  return {
    series: [
      {
        type: "gauge",
        startAngle: 210,
        endAngle: -30,
        min: 0,
        max: 100,
        radius: "92%",
        progress: { show: true, width: 14 },
        axisLine: { lineStyle: { width: 14, color: [[1, "#2a3140"]] } },
        axisTick: { show: false },
        splitLine: { length: 12, lineStyle: { color: "#3a4252", width: 2 } },
        axisLabel: { color: "#8b949e", distance: 16, fontSize: 10 },
        pointer: { width: 4, length: "62%", itemStyle: { color: color } },
        anchor: { show: true, size: 10, itemStyle: { color: color } },
        title: { show: true, offsetCenter: [0, "32%"], color: "#8b949e", fontSize: 12 },
        detail: {
          valueAnimation: true,
          offsetCenter: [0, "2%"],
          fontSize: 30,
          fontWeight: "bold",
          color: color,
          formatter: "{value}%",
        },
        data: [{ value: typeof value === "number" ? value : 0, name: title }],
      },
    ],
  };
}

// 图表实例只创建一次，之后用 setOption 更新数值。
// 如果每 2 秒重新 init 一次，既会堆积图表实例，
// 也会不断累加 resize 监听器，页面越开越卡。
const charts = { cpu: null, gpu: null };
let resizeBound = false;

function ensureChart(key, domId, title, color, value) {
  if (typeof echarts === "undefined") {
    showChartFallback(domId, title, value);
    return;
  }

  if (!charts[key]) {
    const box = document.getElementById(domId);

    // 图表库就绪了，撤掉文字兜底。
    // 漏掉这一步会导致兜底文字压在仪表盘上，而且 .chart-fallback 的
    // 样式还会把容器高度压扁。
    box.classList.remove("chart-fallback");
    box.textContent = "";

    charts[key] = echarts.init(box);

    // resize 监听只绑一次。
    if (!resizeBound) {
      window.addEventListener("resize", function () {
        if (charts.cpu) charts.cpu.resize();
        if (charts.gpu) charts.gpu.resize();
      });
      resizeBound = true;
    }
  }

  charts[key].setOption(gaugeOption(title, color, value));
}

let echartsLoading = false;

function ensureEChartsLoaded() {
  if (typeof echarts !== "undefined" || echartsLoading) return;
  echartsLoading = true;

  const script = document.createElement("script");
  script.src = ECHARTS_SRC;

  const timeoutId = setTimeout(function () {
    echartsLoading = false;
  }, ECHARTS_TIMEOUT);

  script.onload = function () {
    clearTimeout(timeoutId);
    echartsLoading = false;
    syncCharts(lastMetrics, lastWorkload);
  };
  script.onerror = function () {
    clearTimeout(timeoutId);
    echartsLoading = false;
  };

  document.head.appendChild(script);
}

function syncCharts(metrics, workload) {
  if (!metrics || !workload) return;

  ensureChart("cpu", "cpu-chart", "CPU 使用率", "#4f9cf9", metrics.cpu_percent);
  ensureChart("gpu", "gpu-chart", "GPU Utilization", "#3fb950", workload.gpu_utilization);

  // 图表库还没到位就顺手拉一次，到位后 onload 会重画。
  ensureEChartsLoaded();
}

// ---------- 列表 ----------

function renderAnomalies(list) {
  const box = document.getElementById("anomalies-list");
  box.textContent = "";

  if (!list.length) {
    box.appendChild(el("div", "empty", "当前未检测到资源异常"));
    return;
  }

  list.forEach(function (item) {
    const node = el("div", "item");
    node.style.borderLeftColor = "var(--red)";

    const head = el("div", "item-head");
    head.appendChild(el("span", "metric", item.metric));
    head.appendChild(
      el(
        "span",
        "badge",
        "value " + item.value + " / 阈值 " + item.threshold,
      ),
    );
    node.appendChild(head);
    node.appendChild(el("div", "msg", item.message));
    box.appendChild(node);
  });
}

function renderFindings(list) {
  const box = document.getElementById("findings-list");
  box.textContent = "";

  if (!list.length) {
    box.appendChild(el("div", "empty", "当前未发现明显的多指标关联问题"));
    return;
  }

  list.forEach(function (item) {
    const node = el("div", "item");
    node.style.borderLeftColor = "var(--orange)";

    const head = el("div", "item-head");
    head.appendChild(el("span", "metric", item.type));
    if (item.severity) {
      head.appendChild(el("span", "badge sev-" + item.severity, item.severity));
    }
    node.appendChild(head);
    node.appendChild(el("div", "msg", item.message));
    box.appendChild(node);
  });
}

function renderDiagnoses(list) {
  const box = document.getElementById("diagnoses-list");
  box.textContent = "";

  if (!list.length) {
    box.appendChild(el("div", "empty", "当前系统运行正常，暂无诊断建议"));
    return;
  }

  list.forEach(function (item) {
    const node = el("div", "item");
    node.style.borderLeftColor = "var(--blue)";

    const head = el("div", "item-head");
    head.appendChild(el("span", "metric", item.type));
    // source 字段区分"关联发现"和"规则诊断"，这两个概念不能混为一谈
    if (item.source === "correlation") {
      head.appendChild(el("span", "badge src-correlation", "关联发现"));
    } else {
      head.appendChild(el("span", "badge", "规则诊断"));
    }
    node.appendChild(head);
    node.appendChild(el("div", "msg", item.message));
    box.appendChild(node);
  });
}

// 内容没变就不动 DOM，避免每 2 秒重建一次列表。
const listCache = {};

function renderList(key, containerId, list, renderFn) {
  const signature = JSON.stringify(list);
  if (listCache[key] === signature) return;
  listCache[key] = signature;
  renderFn(list);
}

// ---------- 状态提示 ----------

function setHealthOk(data) {
  const health = document.getElementById("health");
  const count = (data.anomalies || []).length + (data.correlation_findings || []).length;
  health.className = "health ok";
  health.textContent = "已连接 · " + count + " 项待关注 · " + nowText();
}

function setHealthError(error) {
  const health = document.getElementById("health");
  health.className = "health bad";
  health.textContent = "刷新失败（保留上次数据）：" + error.message;
}

// ---------- 主流程 ----------

let lastMetrics = null;
let lastWorkload = null;

function render(data) {
  const metrics = data.metrics || {};
  const workload = data.workload || {};
  lastMetrics = metrics;
  lastWorkload = workload;

  if (cardRefs["metrics-cards"]) {
    updateCards("metrics-cards", metrics);
  } else {
    buildCards("metrics-cards", METRIC_CARDS, metrics);
  }

  if (cardRefs["workload-cards"]) {
    updateCards("workload-cards", workload);
  } else {
    buildCards("workload-cards", WORKLOAD_CARDS, workload);
  }

  renderList("anomalies", "anomalies-list", data.anomalies || [], renderAnomalies);
  renderList("findings", "findings-list", data.correlation_findings || [], renderFindings);
  renderList("diagnoses", "diagnoses-list", data.diagnoses || [], renderDiagnoses);

  syncCharts(metrics, workload);
  setHealthOk(data);
}

// ---------- 定时轮询 ----------

function fetchStatus() {
  return fetch("/api/v1/status").then(function (response) {
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  });
}

// 单次刷新。成功就更新页面，失败只提示、不清空任何数据。
// 这里 catch 之后不再抛出，所以即使连续失败也不会堆积定时任务。
function refreshOnce() {
  return fetchStatus()
    .then(render)
    .catch(setHealthError);
}

function startAutoRefresh() {
  // 打开页面立即请求一次。
  refreshOnce();

  // 之后每 2 秒自动更新一次。
  setInterval(refreshOnce, REFRESH_INTERVAL);
}

startAutoRefresh();

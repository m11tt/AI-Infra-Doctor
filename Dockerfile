# AI Infra Doctor —— Docker 镜像
#
# 构建：
#   docker build -t ai-infra-doctor .
# 运行：
#   docker run --rm -p 8000:8000 ai-infra-doctor
# 然后浏览器打开 http://127.0.0.1:8000/dashboard
#
# 说明：
# - 基础镜像用 python:3.13-slim，与项目要求的 Python 3.13 一致。
# - psutil 需要编译环境，但如果官方 wheel 可用（Linux 上有 manylinux wheel），
#   可以直接安装，无需 gcc。因此这里不预装构建工具，保持镜像精简。
# - LLM 相关环境变量（AI_API_KEY / AI_BASE_URL / AI_MODEL）为可选项：
#   不提供时 ai/client.py 会自动降级，规则链路（监控/检测/关联/诊断）不受影响。

FROM python:3.13-slim

# 不在容器内写 .pyc，输出日志不缓冲（便于 docker logs 实时查看）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先只拷贝依赖清单，利用 Docker 层缓存：requirements 不变时不会重装依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 再拷贝其余源码（.dockerignore 已排除 .venv、tests、docs 等无关内容）
COPY . .

EXPOSE 8000

# 关键：host 必须是 0.0.0.0，否则容器外无法访问
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

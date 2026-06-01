FROM python:3.11-slim AS builder

WORKDIR /build
COPY scheduler/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt

FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    # 安装 Docker CLI（用于读取其他容器日志）
    apt-get install -y --no-install-recommends docker.io && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /install /usr/local
COPY shared/ /app/shared/
COPY scheduler/app/ /app/app/

EXPOSE 8006
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -sf http://localhost:8006/health | grep -q '"scheduler_running": true' || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]

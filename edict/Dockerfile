FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

ENV HOME=/app \
    HERMES_HOME=/app/.hermes \
    PATH="/app/.local/bin:${PATH}"

# 安装 Python 依赖与 Hermes Agent CLI。
# Hermes 源码由 docker-compose 的 additional_contexts 提供，避免官方
# installer 在 Docker 构建中重新 clone 并安装 Node/browser/ffmpeg 等额外工具。
COPY --from=hermes_agent . /tmp/hermes-agent
COPY edict/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt /tmp/hermes-agent

# 复制后端代码
COPY edict/backend/ /app/

# 复制 Alembic 配置
COPY edict/alembic.ini /app/alembic.ini
COPY edict/migration/ /app/migration/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

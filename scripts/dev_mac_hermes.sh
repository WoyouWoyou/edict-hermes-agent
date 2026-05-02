#!/usr/bin/env bash
# Edict + Hermes local development launcher for macOS.
#
# Usage:
#   ./scripts/dev_mac_hermes.sh
#
# Optional environment overrides:
#   OPENAI_API_KEY=... ./scripts/dev_mac_hermes.sh
#   HERMES_PROVIDER=openai HERMES_MODEL=openai/gpt-4o-mini ./scripts/dev_mac_hermes.sh
#   SKIP_FRONTEND=1 ./scripts/dev_mac_hermes.sh
#   SKIP_RUN_LOOP=1 ./scripts/dev_mac_hermes.sh
#   SKIP_DB_SETUP=1 ./scripts/dev_mac_hermes.sh

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/edict"
BACKEND_DIR="$APP_DIR/backend"
FRONTEND_DIR="$APP_DIR/frontend"
LOG_DIR="${EDICT_LOG_DIR:-/tmp/edict-hermes-dev}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
REFRESH_INTERVAL="${REFRESH_INTERVAL:-15}"
SCHEDULER_SCAN_INTERVAL="${SCHEDULER_SCAN_INTERVAL:-120}"

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-edict}"
POSTGRES_USER="${POSTGRES_USER:-edict}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-edict_secret_change_me}"
REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

HERMES_HOME="${HERMES_HOME:-$ROOT_DIR/.hermes}"
HERMES_PROJECT_DIR="${HERMES_PROJECT_DIR:-$ROOT_DIR}"
HERMES_SOURCE="${HERMES_SOURCE:-edict}"
HERMES_REPO="${HERMES_REPO:-$(cd "$ROOT_DIR/.." && pwd)/hermes-agent}"
HERMES_BIN="${HERMES_BIN:-hermes}"

SKIP_FRONTEND="${SKIP_FRONTEND:-0}"
SKIP_RUN_LOOP="${SKIP_RUN_LOOP:-0}"
SKIP_DB_SETUP="${SKIP_DB_SETUP:-0}"
AUTO_INSTALL_DEPS="${AUTO_INSTALL_DEPS:-1}"
AUTO_INSTALL_HERMES="${AUTO_INSTALL_HERMES:-1}"

PIDS=()
NAMES=()

color() {
  local code="$1"
  shift
  printf "\033[%sm%s\033[0m\n" "$code" "$*"
}

info() { color "0;34" "==> $*"; }
ok() { color "0;32" "OK  $*"; }
warn() { color "1;33" "!!  $*"; }
die() {
  color "0;31" "ERR $*"
  exit 1
}

cleanup() {
  local rc=$?
  if ((${#PIDS[@]})); then
    echo
    warn "正在关闭本地服务..."
    for pid in "${PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
  exit "$rc"
}
trap cleanup INT TERM EXIT

load_env_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    info "加载环境变量: $file"
    set -a
    # shellcheck disable=SC1090
    source "$file"
    set +a
  fi
}

usage() {
  cat <<EOF
Edict + Hermes macOS 本地一键启动

用法:
  ./scripts/dev_mac_hermes.sh

常用环境变量:
  OPENAI_API_KEY=...              LLM API key，可选；Hermes 已配置则不需要
  HERMES_PROVIDER=openai          可选；不设置则使用 Hermes 自己的配置
  HERMES_MODEL=openai/gpt-4o-mini 可选；不设置则使用 Hermes 自己的配置
  HERMES_BIN=/path/to/hermes      Hermes CLI 路径
  SKIP_FRONTEND=1                 不启动前端
  SKIP_RUN_LOOP=1                 不启动数据刷新循环
  SKIP_DB_SETUP=1                 不自动创建本地数据库
  BACKEND_PORT=8001               后端端口
  FRONTEND_PORT=5174              前端端口
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

require_command() {
  local cmd="$1"
  local hint="$2"
  command -v "$cmd" >/dev/null 2>&1 || die "找不到命令: $cmd。$hint"
}

maybe_brew_start() {
  local formula="$1"
  if command -v brew >/dev/null 2>&1 && brew list "$formula" >/dev/null 2>&1; then
    brew services start "$formula" >/dev/null 2>&1 || true
    return 0
  fi
  return 1
}

ensure_postgres() {
  if command -v pg_isready >/dev/null 2>&1 && pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" >/dev/null 2>&1; then
    ok "Postgres 已就绪"
    return 0
  fi

  info "尝试启动 Homebrew Postgres..."
  maybe_brew_start postgresql@16 || maybe_brew_start postgresql@15 || maybe_brew_start postgresql@14 || maybe_brew_start postgresql || true
  sleep 2

  if command -v pg_isready >/dev/null 2>&1 && pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" >/dev/null 2>&1; then
    ok "Postgres 已启动"
    return 0
  fi

  die "Postgres 未就绪。请先安装并启动: brew install postgresql@16 && brew services start postgresql@16"
}

ensure_redis() {
  if command -v redis-cli >/dev/null 2>&1 && redis-cli -u "$REDIS_URL" ping >/dev/null 2>&1; then
    ok "Redis 已就绪"
    return 0
  fi

  info "尝试启动 Homebrew Redis..."
  maybe_brew_start redis || true
  sleep 1

  if command -v redis-cli >/dev/null 2>&1 && redis-cli -u "$REDIS_URL" ping >/dev/null 2>&1; then
    ok "Redis 已启动"
    return 0
  fi

  die "Redis 未就绪。请先安装并启动: brew install redis && brew services start redis"
}

sql_escape() {
  printf "%s" "$1" | sed "s/'/''/g"
}

setup_database() {
  [[ "$SKIP_DB_SETUP" == "1" ]] && return 0
  require_command psql "请先安装 PostgreSQL 命令行工具。"

  info "准备本地数据库 $POSTGRES_DB / 用户 $POSTGRES_USER"
  createuser "$POSTGRES_USER" >/dev/null 2>&1 || true
  createdb "$POSTGRES_DB" -O "$POSTGRES_USER" >/dev/null 2>&1 || true

  local escaped_password
  escaped_password="$(sql_escape "$POSTGRES_PASSWORD")"
  psql postgres -v ON_ERROR_STOP=0 -c "ALTER USER \"$POSTGRES_USER\" WITH PASSWORD '$escaped_password';" >/dev/null 2>&1 || true
  psql postgres -v ON_ERROR_STOP=0 -c "GRANT ALL PRIVILEGES ON DATABASE \"$POSTGRES_DB\" TO \"$POSTGRES_USER\";" >/dev/null 2>&1 || true
  psql "$POSTGRES_DB" -v ON_ERROR_STOP=0 -c "GRANT ALL ON SCHEMA public TO \"$POSTGRES_USER\";" >/dev/null 2>&1 || true
  ok "数据库准备完成"
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  [[ "$AUTO_INSTALL_DEPS" == "1" ]] || die "找不到 uv。请安装: brew install uv"
  require_command brew "请先安装 Homebrew，或手动安装 uv。"
  info "安装 uv..."
  brew install uv
}

ensure_backend_env() {
  ensure_uv
  if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
    info "创建 Python 虚拟环境 (.venv, Python $PYTHON_VERSION)..."
    uv venv "$ROOT_DIR/.venv" --python "$PYTHON_VERSION"
  fi

  local python_bin="$ROOT_DIR/.venv/bin/python"
  local marker="$ROOT_DIR/.venv/.edict_backend_ready"
  if [[ ! -f "$marker" || "$APP_DIR/backend/requirements.txt" -nt "$marker" ]]; then
    info "安装后端依赖..."
    uv pip install --python "$python_bin" -r "$APP_DIR/backend/requirements.txt"
    touch "$marker"
  fi
  PYTHON_BIN="$python_bin"
  ok "后端 Python 环境已就绪"
}

ensure_hermes() {
  if command -v "$HERMES_BIN" >/dev/null 2>&1; then
    HERMES_BIN="$(command -v "$HERMES_BIN")"
    ok "Hermes CLI: $HERMES_BIN"
    return 0
  fi

  if [[ -x "$HERMES_REPO/.venv/bin/hermes" ]]; then
    HERMES_BIN="$HERMES_REPO/.venv/bin/hermes"
    ok "使用本地 Hermes: $HERMES_BIN"
    return 0
  fi

  if [[ "$AUTO_INSTALL_HERMES" == "1" && -f "$HERMES_REPO/pyproject.toml" ]]; then
    ensure_uv
    info "未检测到 hermes 命令，开始从本地 hermes-agent 仓库安装..."
    uv venv "$HERMES_REPO/.venv" --python "$PYTHON_VERSION"
    uv pip install --python "$HERMES_REPO/.venv/bin/python" -e "$HERMES_REPO"
    HERMES_BIN="$HERMES_REPO/.venv/bin/hermes"
    ok "本地 Hermes 安装完成: $HERMES_BIN"
    return 0
  fi

  die "找不到 Hermes CLI。可先执行: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
}

ensure_frontend_env() {
  [[ "$SKIP_FRONTEND" == "1" ]] && return 0
  require_command npm "请先安装 Node.js，例如: brew install node"
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    [[ "$AUTO_INSTALL_DEPS" == "1" ]] || die "前端依赖未安装。请运行: cd $FRONTEND_DIR && npm install"
    info "安装前端依赖..."
    (cd "$FRONTEND_DIR" && npm install)
  fi
  ok "前端依赖已就绪"
}

init_runtime_data() {
  mkdir -p "$ROOT_DIR/data" "$HERMES_HOME" "$LOG_DIR"
  for file in live_status.json agent_config.json model_change_log.json sync_status.json officials_stats.json; do
    [[ -f "$ROOT_DIR/data/$file" ]] || printf "{}\n" > "$ROOT_DIR/data/$file"
  done
  for file in pending_model_changes.json tasks_source.json tasks.json officials.json; do
    [[ -f "$ROOT_DIR/data/$file" ]] || printf "[]\n" > "$ROOT_DIR/data/$file"
  done
}

run_migrations() {
  info "执行数据库迁移..."
  (cd "$APP_DIR" && "$PYTHON_BIN" -m alembic upgrade head)
  ok "数据库迁移完成"
}

bootstrap_hermes_profiles() {
  info "同步 Hermes profiles..."
  "$PYTHON_BIN" "$ROOT_DIR/scripts/bootstrap_hermes_profiles.py" --hermes-bin "$HERMES_BIN" --hermes-home "$HERMES_HOME"
  "$PYTHON_BIN" "$ROOT_DIR/scripts/sync_agent_config.py"
  ok "Hermes profiles 已同步"
}

start_service() {
  local name="$1"
  local cwd="$2"
  shift 2
  local log="$LOG_DIR/$name.log"
  info "启动 $name，日志: $log"
  (cd "$cwd" && "$@") >"$log" 2>&1 &
  PIDS+=("$!")
  NAMES+=("$name")
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local tries="${3:-30}"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      ok "$label 已可访问: $url"
      return 0
    fi
    sleep 1
  done
  warn "$label 还没响应，请查看日志目录: $LOG_DIR"
}

load_env_file "$ROOT_DIR/.env"
load_env_file "$APP_DIR/.env"

export POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB}"
export REDIS_URL
export BACKEND_HOST BACKEND_PORT PORT="$BACKEND_PORT"
export HERMES_HOME HERMES_PROJECT_DIR HERMES_SOURCE HERMES_BIN
export VITE_API_URL="${VITE_API_URL:-http://127.0.0.1:$BACKEND_PORT}"

DISPLAY_HERMES_PROVIDER="${HERMES_PROVIDER:-使用 Hermes 配置}"
DISPLAY_HERMES_MODEL="${HERMES_MODEL:-使用 Hermes 配置}"

cat <<EOF

============================================================
 Edict + Hermes 本地开发启动器
============================================================
 项目目录:      $ROOT_DIR
 Hermes Home:  $HERMES_HOME
 Backend:      http://127.0.0.1:$BACKEND_PORT
 Frontend:     http://127.0.0.1:$FRONTEND_PORT
 Logs:         $LOG_DIR
 Provider:     $DISPLAY_HERMES_PROVIDER
 Model:        $DISPLAY_HERMES_MODEL
============================================================

EOF

init_runtime_data
ensure_postgres
ensure_redis
setup_database
ensure_backend_env
ensure_hermes
ensure_frontend_env
bootstrap_hermes_profiles
run_migrations

start_service backend "$BACKEND_DIR" "$PYTHON_BIN" -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload
wait_for_http "http://127.0.0.1:$BACKEND_PORT/health" "Backend"

start_service outbox-relay "$BACKEND_DIR" "$PYTHON_BIN" -m app.workers.outbox_relay
start_service dispatcher "$BACKEND_DIR" "$PYTHON_BIN" -m app.workers.dispatch_worker

if [[ "$SKIP_RUN_LOOP" != "1" ]]; then
  start_service run-loop "$ROOT_DIR" env EDICT_PYTHON="$PYTHON_BIN" EDICT_DASHBOARD_PORT="$BACKEND_PORT" bash "$ROOT_DIR/scripts/run_loop.sh" "$REFRESH_INTERVAL" "$SCHEDULER_SCAN_INTERVAL"
fi

if [[ "$SKIP_FRONTEND" != "1" ]]; then
  start_service frontend "$FRONTEND_DIR" env VITE_API_URL="$VITE_API_URL" npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
  wait_for_http "http://127.0.0.1:$FRONTEND_PORT" "Frontend"
fi

cat <<EOF

启动完成。

前端页面: http://127.0.0.1:$FRONTEND_PORT
后端健康检查: http://127.0.0.1:$BACKEND_PORT/health
日志目录: $LOG_DIR

按 Ctrl+C 停止所有本次启动的服务。

EOF

wait "${PIDS[@]}"

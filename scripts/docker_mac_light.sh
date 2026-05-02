#!/usr/bin/env bash
# Lightweight Docker launcher for Edict + Hermes on macOS.
#
# Usage:
#   ./scripts/docker_mac_light.sh          # foreground, Ctrl+C stops services
#   ./scripts/docker_mac_light.sh detached # background
#   ./scripts/docker_mac_light.sh down     # stop and remove containers
#   ./scripts/docker_mac_light.sh clean    # down + remove volumes

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT_DIR/edict"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-edict-hermes}"
ACTION="${1:-up}"
if (($# > 0)); then
  shift
fi

BASE_ARGS=(
  --project-name "$PROJECT_NAME"
  --project-directory "$COMPOSE_DIR"
  -f "$COMPOSE_DIR/docker-compose.yml"
  -f "$COMPOSE_DIR/docker-compose.mac-light.yml"
)

color() {
  local code="$1"
  shift
  printf "\033[%sm%s\033[0m\n" "$code" "$*"
}

info() { color "0;34" "==> $*"; }
warn() { color "1;33" "!!  $*"; }
die() {
  color "0;31" "ERR $*"
  exit 1
}

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
Edict + Hermes macOS 轻量 Docker 启动器

用法:
  ./scripts/docker_mac_light.sh
  ./scripts/docker_mac_light.sh detached
  ./scripts/docker_mac_light.sh logs
  ./scripts/docker_mac_light.sh ps
  ./scripts/docker_mac_light.sh hermes --version
  ./scripts/docker_mac_light.sh hermes setup
  ./scripts/docker_mac_light.sh down
  ./scripts/docker_mac_light.sh clean

说明:
  up/detached 会使用 docker-compose.mac-light.yml 覆盖默认配置：
  - 禁止容器随 Docker Desktop 自动重启
  - 后端关闭 --reload
  - 给服务设置较保守的 CPU / 内存上限

可选:
  OPENAI_API_KEY=... ./scripts/docker_mac_light.sh
  HERMES_PROVIDER=... HERMES_MODEL=... ./scripts/docker_mac_light.sh
EOF
}

if [[ "$ACTION" == "-h" || "$ACTION" == "--help" || "$ACTION" == "help" ]]; then
  usage
  exit 0
fi

command -v docker >/dev/null 2>&1 || die "找不到 docker。请先安装并打开 Docker Desktop。"
docker compose version >/dev/null 2>&1 || die "当前 docker 不支持 compose 插件。请更新 Docker Desktop。"

load_env_file "$ROOT_DIR/.env"
load_env_file "$COMPOSE_DIR/.env"

case "$ACTION" in
  up|start)
    info "启动 Edict + Hermes Docker 栈，前台运行，按 Ctrl+C 停止。"
    docker compose "${BASE_ARGS[@]}" up --build
    ;;
  detached|daemon|-d)
    info "后台启动 Edict + Hermes Docker 栈。"
    docker compose "${BASE_ARGS[@]}" up --build -d
    info "前端: http://127.0.0.1:3000"
    info "后端: http://127.0.0.1:8000/health"
    ;;
  logs)
    docker compose "${BASE_ARGS[@]}" logs "$@"
    ;;
  ps|status)
    docker compose "${BASE_ARGS[@]}" ps
    ;;
  hermes)
    docker compose "${BASE_ARGS[@]}" exec dispatcher hermes "$@"
    ;;
  stop)
    warn "停止容器，但保留容器和数据卷。"
    docker compose "${BASE_ARGS[@]}" stop
    ;;
  down)
    warn "停止并移除容器，保留数据库数据卷。"
    docker compose "${BASE_ARGS[@]}" down
    ;;
  clean)
    warn "停止并移除容器和数据卷，本地数据库数据会被清掉。"
    docker compose "${BASE_ARGS[@]}" down -v
    ;;
  *)
    usage
    exit 2
    ;;
esac

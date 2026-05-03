#!/usr/bin/env bash
# Lightweight local smoke test for Edict Hermes Agent.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="${EDICT_API_URL:-http://127.0.0.1:8000}"
WEB_URL="${EDICT_WEB_URL:-http://127.0.0.1:3000}"
PROFILE="${HERMES_TEST_PROFILE:-taizi}"
PROMPT="${HERMES_TEST_PROMPT:-只回复：Hermes OK}"

ok() { printf "\033[0;32m✓\033[0m %s\n" "$*"; }
info() { printf "\033[0;34m→\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!\033[0m %s\n" "$*"; }
fail() {
  printf "\033[0;31m✗\033[0m %s\n" "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || fail "缺少命令：$1"
}

curl_json() {
  local url="$1"
  curl -fsS --max-time 10 "$url"
}

info "检查基础命令"
need docker
need curl
ok "docker / curl 可用"

info "检查 Docker Compose 服务"
"$ROOT_DIR/scripts/docker_mac_light.sh" ps >/tmp/edict-hermes-smoke-ps.txt || fail "Docker 栈未运行。先执行 ./scripts/docker_mac_light.sh detached"
if ! grep -q "Up" /tmp/edict-hermes-smoke-ps.txt; then
  cat /tmp/edict-hermes-smoke-ps.txt
  fail "没有发现运行中的容器。先执行 ./scripts/docker_mac_light.sh detached"
fi
ok "Docker 栈正在运行"

info "检查后端健康状态"
curl_json "$API_URL/health" >/tmp/edict-hermes-smoke-health.json || fail "后端不可访问：$API_URL/health"
ok "后端健康接口可访问"

info "检查 dashboard API"
curl_json "$API_URL/api/live-status" >/tmp/edict-hermes-smoke-live.json || fail "live-status 不可访问"
curl_json "$API_URL/api/agents-status" >/tmp/edict-hermes-smoke-agents.json || fail "agents-status 不可访问"
curl_json "$API_URL/api/hermes-profile-status" >/tmp/edict-hermes-smoke-profiles.json || fail "hermes-profile-status 不可访问"
ok "核心 API 可访问"

info "检查前端页面"
curl -fsSI --max-time 10 "$WEB_URL" >/tmp/edict-hermes-smoke-web.txt || fail "前端不可访问：$WEB_URL"
ok "前端可访问：$WEB_URL"

info "执行 Hermes profile 轻量测试：$PROFILE"
if "$ROOT_DIR/scripts/docker_mac_light.sh" hermes --profile "$PROFILE" chat --quiet --source edict -q "$PROMPT" >/tmp/edict-hermes-smoke-hermes.txt; then
  ok "Hermes CLI 能调用 profile：$PROFILE"
else
  cat /tmp/edict-hermes-smoke-hermes.txt 2>/dev/null || true
  warn "Hermes CLI 调用失败。请检查 $PROFILE 的 config.yaml / .env / 模型密钥配置"
  exit 1
fi

printf "\n"
ok "Smoke test 通过"
printf "前端：%s\n后端：%s\n" "$WEB_URL" "$API_URL"

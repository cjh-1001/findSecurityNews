#!/usr/bin/env bash
# 飞书工作流：采集 → 推送
# 用法: scripts/run_feishu.sh [window] [extra args]
#   window: latest | day | morning | evening (默认 latest)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

WINDOW="${1:-latest}"
if [[ $# -gt 0 ]]; then
  shift
fi

NOW=$(date '+%Y-%m-%d %H:%M:%S')
LOG_FILE="$LOG_DIR/feishu.log"

log()  { echo "[$NOW] $1" | tee -a "$LOG_FILE"; }
warn() { echo "[$NOW] WARN: $1" | tee -a "$LOG_FILE" >&2; }
err()  { echo "[$NOW] ERROR: $1" | tee -a "$LOG_FILE" >&2; }

log "工作流开始 (window=$WINDOW)"

# ── 检查 RSSHub ──
if [[ "${ENABLE_RSSHUB:-false}" =~ ^(1|true|yes)$ ]]; then
  if curl -sf --max-time 5 http://127.0.0.1:1200/healthz >/dev/null 2>&1; then
    log "RSSHub 正常"
  else
    warn "RSSHub 未响应，微信源将跳过"
  fi
fi

# ── 构建参数 ──
ARGS=(
  run.py
  feishu-workflow
  --window "$WINDOW"
  --collect-limit "${COLLECT_LIMIT:-30}"
  --push-limit "${PUSH_LIMIT:-20}"
)

if [[ "${ENABLE_AI:-false}" =~ ^(1|true|yes)$ ]]; then
  log "AI 已启用"
  ARGS+=(--ai)
fi

ARGS+=("$@")

# ── 运行 ──
PYTHON="${PYTHON_BIN:-python3}"
export PYTHONUNBUFFERED=1
log "执行: $PYTHON ${ARGS[*]}"

if "$PYTHON" "${ARGS[@]}" 2>&1 | tee -a "$LOG_FILE"; then
  log "工作流完成"
else
  err "工作流失败 (exit=$?)"
  exit 1
fi

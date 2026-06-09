#!/usr/bin/env bash
# 飞书工作流：采集 / 推送 / 完整流程
# 用法: scripts/run_feishu.sh <mode> [window] [extra args]
#   mode: collect | push | workflow (默认 workflow)
#   window (push/workflow 模式): latest | day | morning | evening (默认 latest)
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

MODE="${1:-workflow}"
shift

if [[ "$MODE" =~ ^(push|workflow)$ ]]; then
  WINDOW="${1:-latest}"
  shift
elif [[ "$MODE" == "collect" ]]; then
  WINDOW="latest"  # collect 模式不需要窗口参数
else
  echo "未知模式: $MODE (可选: collect, push, workflow)" >&2
  exit 1
fi

NOW=$(date '+%Y-%m-%d %H:%M:%S')
LOG_FILE="$LOG_DIR/feishu.log"

append_output() {
  if [[ -t 1 ]]; then
    tee -a "$LOG_FILE"
  else
    cat
  fi
}

log()  { echo "[$NOW] $1" | append_output; }
warn() { echo "[$NOW] WARN: $1" | append_output >&2; }
err()  { echo "[$NOW] ERROR: $1" | append_output >&2; }

log "工作流开始 (mode=$MODE, window=$WINDOW)"

# ── 检查 RSSHub ──
if [[ "${ENABLE_RSSHUB:-false}" =~ ^(1|true|yes)$ ]]; then
  if curl -sf --max-time 5 http://127.0.0.1:1200/healthz >/dev/null 2>&1; then
    log "RSSHub 正常"
  else
    warn "RSSHub 未响应，微信源将跳过"
  fi
fi

PYTHON="${PYTHON_BIN:-python3}"
export PYTHONUNBUFFERED=1

AI_FLAG=()
if [[ "${ENABLE_AI:-false}" =~ ^(1|true|yes)$ ]]; then
  log "AI 已启用"
  AI_FLAG=(--ai)
fi

# ── 构建参数 ──
case "$MODE" in
  collect)
    ARGS=(
      run.py
      collect
      --limit "${COLLECT_LIMIT:-30}"
    )
    ARGS+=("${AI_FLAG[@]}" "$@")
    log "执行: $PYTHON ${ARGS[*]}"
    ;;
  push)
    ARGS=(
      run.py
      push-feishu
      --window "$WINDOW"
      --limit "${PUSH_LIMIT:-20}"
      --batch-size "${PUSH_BATCH_SIZE:-20}"
      --summary-limit "${PUSH_SUMMARY_LIMIT:-30}"
    )
    ARGS+=("$@")
    log "执行: $PYTHON ${ARGS[*]}"
    ;;
  workflow)
    ARGS=(
      run.py
      feishu-workflow
      --window "$WINDOW"
      --collect-limit "${COLLECT_LIMIT:-30}"
      --push-limit "${PUSH_LIMIT:-20}"
      --batch-size "${PUSH_BATCH_SIZE:-20}"
      --summary-limit "${PUSH_SUMMARY_LIMIT:-30}"
    )
    ARGS+=("${AI_FLAG[@]}" "$@")
    log "执行: $PYTHON ${ARGS[*]}"
    ;;
  *)
    err "未知模式: $MODE (可选: collect, push, workflow)"
    exit 1
    ;;
esac

# ── 运行 ──
if "$PYTHON" "${ARGS[@]}" 2>&1 | append_output; then
  log "工作流完成"
else
  err "工作流失败 (exit=$?)"
  exit 1
fi

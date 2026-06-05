#!/usr/bin/env bash
# 一键部署：拉代码 → 装依赖 → 启动服务 → 装 cron
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

log() { printf '[%(%Y-%m-%d %H:%M:%S)T] %s\n' -1 "$1"; }
fail() { printf '[%(%Y-%m-%d %H:%M:%S)T] ERROR: %s\n' -1 "$1" >&2; exit 1; }

log "开始部署 findSecurityNews"

# ── 1. 更新代码 ──
log "拉取最新代码"
git fetch origin main
if ! git merge --ff-only origin/main 2>/dev/null; then
  log "无法 fast-forward 合并，尝试 rebase"
  git pull --rebase origin main || fail "代码更新失败，请手动处理冲突"
fi

# ── 2. 确定 Python ──
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -f .venv/bin/python ]]; then
  PYTHON_BIN="$(pwd)/.venv/bin/python"
  log "使用虚拟环境: $PYTHON_BIN"
elif ! "$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,10)' 2>/dev/null; then
  log "Python < 3.10，尝试创建虚拟环境"
  python3.11 -m venv .venv 2>/dev/null || python3 -m venv .venv 2>/dev/null || fail "需要 Python >= 3.10"
  PYTHON_BIN="$(pwd)/.venv/bin/python"
fi

# ── 3. 装依赖 ──
log "安装 Python 依赖"
"$PYTHON_BIN" -m pip install -e . --quiet || fail "pip install 失败"

# ── 4. 初始化数据库 ──
log "初始化数据库"
"$PYTHON_BIN" run.py init-db || fail "数据库初始化失败"

# ── 5. 启动 RSSHub ──
if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
  log "启动 RSSHub"
  docker compose up -d rsshub || log "RSSHub 启动失败（如不需要微信源可忽略）"
else
  log "未检测到 Docker，跳过 RSSHub"
fi

# ── 6. 安装 cron ──
log "安装定时任务"
bash scripts/install_cron.sh 2>/dev/null || log "cron 安装失败（手动执行 scripts/install_cron.sh）"

CLEANUP_SCHEDULE="${CLEANUP_SCHEDULE:-weekly}"
bash scripts/install_cleanup_cron.sh "$CLEANUP_SCHEDULE" 2>/dev/null || log "清理 cron 安装失败"

# ── 7. 验证 ──
log "验证部署"
sleep 2
"$PYTHON_BIN" run.py list --limit 1 >/dev/null 2>&1 && log "数据库可用" || log "数据库无数据（首次部署正常）"

if docker compose ps rsshub 2>/dev/null | grep -q running; then
  log "RSSHub 运行中"
else
  log "RSSHub 未运行（微信源将不可用）"
fi

log "部署完成！"
echo ""
echo "  查看定时任务: crontab -l | grep findSecurityNews"
echo "  手动测试:     scripts/run_feishu.sh latest"
echo "  查看日志:     tail -f logs/feishu.log"
echo "  仪表盘:       ENABLE_DASHBOARD=true $PYTHON_BIN run.py dashboard"

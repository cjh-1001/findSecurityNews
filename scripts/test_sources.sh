#!/usr/bin/env bash
# 一键测试所有新闻源是否连通
# 用法: bash scripts/test_sources.sh [timeout_seconds]
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# 加载 .env 获取 PYTHON_BIN
if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

PYTHON="${PYTHON_BIN:-python3}"
TIMEOUT="${1:-30}"

# 检查 Python 版本
PY_VER=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "unknown")
echo "Python: $PYTHON ($PY_VER)"
echo ""

# 获取所有启用的源
SOURCES=$("$PYTHON" -c "
from find_security_news.config import load_sources
from pathlib import Path
for s in load_sources(Path('config/sources.toml')):
    print(s.name)
" 2>/dev/null)

if [[ -z "$SOURCES" ]]; then
  echo "ERROR: 无法加载源列表，请检查 Python 环境和 config/sources.toml"
  exit 1
fi

PASS=0
FAIL=0
FAILED_SOURCES=()

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
printf "  %-30s %s\n" "Source" "Status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for src in $SOURCES; do
  printf "  %-30s " "$src"
  if timeout "$TIMEOUT" "$PYTHON" run.py collect --source "$src" --limit 1 >/dev/null 2>&1; then
    echo "✓ OK"
    ((PASS++)) || true
  else
    EXIT_CODE=$?
    if [[ $EXIT_CODE -eq 124 ]]; then
      echo "✗ TIMEOUT (${TIMEOUT}s)"
    else
      echo "✗ FAILED"
    fi
    ((FAIL++)) || true
    FAILED_SOURCES+=("$src")
  fi
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  通过: $PASS  失败: $FAIL  总计: $((PASS + FAIL))"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 检查 RSSHub
if [[ "${ENABLE_RSSHUB:-false}" =~ ^(1|true|yes)$ ]]; then
  echo ""
  if curl -sf --max-time 3 http://127.0.0.1:1200/healthz >/dev/null 2>&1; then
    echo "  RSSHub: ✓ OK (wechat sources will work)"
  else
    echo "  RSSHub: ✗ 未响应 (微信源将跳过)"
  fi
fi

# 显示失败源的详细信息
if [[ $FAIL -gt 0 ]]; then
  echo ""
  echo "失败源详情（最近一次错误）："
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  for src in "${FAILED_SOURCES[@]}"; do
    echo ""
    echo "--- $src ---"
    "$PYTHON" run.py collect --source "$src" --limit 1 2>&1 | tail -5
  done
fi

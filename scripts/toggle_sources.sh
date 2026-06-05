#!/usr/bin/env bash
# 一键切换国外源 on/off
# 用法: scripts/toggle_sources.sh on|off
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

CONFIG="$PROJECT_DIR/config/sources.toml"

# 国外源列表
FOREIGN_SOURCES=(
  "security_affairs_security"
  "group_ib_blog"
  "securityonline_info"
  "malwarebytes_blog"
  "cyble_blog"
  "cybersecurity360_news"
  "krebs_on_security"
)

ACTION="${1:-}"

if [[ "$ACTION" == "on" ]]; then
  TARGET="true"
  REPLACE="false"
  echo "启用国外源..."
elif [[ "$ACTION" == "off" ]]; then
  TARGET="false"
  REPLACE="true"
  echo "禁用国外源..."
else
  echo "用法: $0 [on|off]" >&2
  echo "  on  — 启用国外源" >&2
  echo "  off — 禁用国外源" >&2
  exit 1
fi

cp "$CONFIG" "${CONFIG}.bak"

for name in "${FOREIGN_SOURCES[@]}"; do
  python3 -c "
import re, sys
c = open('$CONFIG').read()
pattern = rf'\[\[sources\]\]\nname = \"{name}\"(.*?)enabled = ){REPLACE}'
result, n = re.subn(pattern, rf'\1{TARGET}', c, flags=re.DOTALL)
if n > 0:
    open('$CONFIG','w').write(result)
    print(f'  {name} → {TARGET}')
else:
    print(f'  {name}: 未找到或已是目标状态')
"
done

echo ""
echo "备份: ${CONFIG}.bak"
echo "当前国外源状态:"
grep -A5 'security_affairs' "$CONFIG" | grep enabled

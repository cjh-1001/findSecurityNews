#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

TMP_CRON="$(mktemp)"
trap 'rm -f "$TMP_CRON"' EXIT

crontab -l 2>/dev/null | grep -v "findSecurityNews feishu" > "$TMP_CRON" || true

{
  echo "0 8 * * * cd \"$PROJECT_DIR\" && /usr/bin/env bash scripts/feishu_morning.sh >> \"$LOG_DIR/feishu.log\" 2>&1 # findSecurityNews feishu morning"
  echo "0 20 * * * cd \"$PROJECT_DIR\" && /usr/bin/env bash scripts/feishu_evening.sh >> \"$LOG_DIR/feishu.log\" 2>&1 # findSecurityNews feishu evening"
} >> "$TMP_CRON"

crontab "$TMP_CRON"
echo "Installed Feishu cron jobs:"
crontab -l | grep "findSecurityNews feishu"

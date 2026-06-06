#!/usr/bin/env bash
# 安装飞书推送定时任务
# 策略：采集和推送分离，采集提前 1 小时执行，确保 AI 分析有充足时间
#   早报: 7:00 采集 → 8:00 推送
#   晚报: 19:00 采集 → 20:00 推送
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

TMP_CRON="$(mktemp)"
trap 'rm -f "$TMP_CRON"' EXIT

# 移除旧版 cron 条目（兼容旧格式）
crontab -l 2>/dev/null | grep -v "findSecurityNews feishu" > "$TMP_CRON" || true

{
  # 早报：7:00 采集，8:00 推送
  echo "0 7 * * * cd \"$PROJECT_DIR\" && /usr/bin/env bash scripts/collect_articles.sh >> \"$LOG_DIR/feishu.log\" 2>&1 # findSecurityNews feishu collect morning"
  echo "0 8 * * * cd \"$PROJECT_DIR\" && /usr/bin/env bash scripts/feishu_morning.sh >> \"$LOG_DIR/feishu.log\" 2>&1 # findSecurityNews feishu push morning"

  # 晚报：19:00 采集，20:00 推送
  echo "0 19 * * * cd \"$PROJECT_DIR\" && /usr/bin/env bash scripts/collect_articles.sh >> \"$LOG_DIR/feishu.log\" 2>&1 # findSecurityNews feishu collect evening"
  echo "0 20 * * * cd \"$PROJECT_DIR\" && /usr/bin/env bash scripts/feishu_evening.sh >> \"$LOG_DIR/feishu.log\" 2>&1 # findSecurityNews feishu push evening"
} >> "$TMP_CRON"

crontab "$TMP_CRON"
echo "Installed Feishu cron jobs:"
crontab -l | grep "findSecurityNews feishu"

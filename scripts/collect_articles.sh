#!/usr/bin/env bash
# 采集文章 + AI 分析 (cron 在推送前 1 小时触发)
# 早报: 7:00 采集 → 8:00 推送
# 晚报: 19:00 采集 → 20:00 推送
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$PROJECT_DIR/scripts/run_feishu.sh" collect "$@"

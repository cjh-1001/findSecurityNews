#!/usr/bin/env bash
# 飞书晚报推送 (20:00 cron 触发)
# 采集由 collect_articles.sh 在 19:00 提前完成
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$PROJECT_DIR/scripts/run_feishu.sh" push evening "$@"

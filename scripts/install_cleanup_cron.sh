#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

SCHEDULE="${1:-${CLEANUP_SCHEDULE:-none}}"
case "$SCHEDULE" in
  weekly)
    CRON_EXPR="30 3 * * 0"
    ;;
  monthly)
    CRON_EXPR="30 3 1 * *"
    ;;
  none|"")
    CRON_EXPR=""
    ;;
  *)
    echo "Unsupported cleanup schedule: $SCHEDULE. Use weekly, monthly, or none." >&2
    exit 2
    ;;
esac

TMP_CRON="$(mktemp)"
trap 'rm -f "$TMP_CRON"' EXIT

crontab -l 2>/dev/null | grep -v "findSecurityNews cleanup" > "$TMP_CRON" || true

if [[ -n "$CRON_EXPR" ]]; then
  echo "$CRON_EXPR cd \"$PROJECT_DIR\" && /usr/bin/env bash scripts/run_cleanup.sh >> \"$LOG_DIR/cleanup.log\" 2>&1 # findSecurityNews cleanup $SCHEDULE" >> "$TMP_CRON"
fi

crontab "$TMP_CRON"
if [[ -n "$CRON_EXPR" ]]; then
  echo "Installed cleanup cron job:"
  crontab -l | grep "findSecurityNews cleanup"
else
  echo "Removed findSecurityNews cleanup cron jobs."
fi

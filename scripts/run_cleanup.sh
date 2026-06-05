#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

RETENTION_DAYS="${CLEANUP_RETENTION_DAYS:-30}"
if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || [[ "$RETENTION_DAYS" -lt 1 ]]; then
  echo "Invalid CLEANUP_RETENTION_DAYS: $RETENTION_DAYS" >&2
  exit 2
fi

BEFORE_DATE="$(date -u -d "$RETENTION_DAYS days ago" +%F)"
ARGS=(
  scripts/cleanup_data.py
  --before "$BEFORE_DATE"
  --yes
)

if [[ "${CLEANUP_VACUUM:-false}" =~ ^(1|true|yes)$ ]]; then
  ARGS+=(--vacuum)
fi

echo "Cleaning records before $BEFORE_DATE; retention=${RETENTION_DAYS}d; vacuum=${CLEANUP_VACUUM:-false}"
"${PYTHON_BIN:-python3}" "${ARGS[@]}"

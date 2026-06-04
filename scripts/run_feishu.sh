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

WINDOW="${1:-latest}"
if [[ $# -gt 0 ]]; then
  shift
fi

ARGS=(
  run.py
  feishu-workflow
  --window "$WINDOW"
  --collect-limit "${COLLECT_LIMIT:-30}"
  --push-limit "${PUSH_LIMIT:-20}"
)

if [[ "${ENABLE_AI:-false}" =~ ^(1|true|yes)$ ]]; then
  ARGS+=(--ai)
fi

ARGS+=("$@")

"${PYTHON_BIN:-python3}" "${ARGS[@]}"

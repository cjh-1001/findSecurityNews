#!/usr/bin/env bash
# Start RSSHub via Docker Compose
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "Starting RSSHub..."
docker compose up -d rsshub

# Wait for healthy
echo "Waiting for RSSHub to be ready..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:1200/healthz >/dev/null 2>&1; then
    echo "RSSHub is ready at http://127.0.0.1:1200"
    exit 0
  fi
  sleep 2
done

echo "ERROR: RSSHub did not become healthy after 60s." >&2
exit 1

#!/usr/bin/env bash
# Stop RSSHub via Docker Compose
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "Stopping RSSHub..."
docker compose stop rsshub
echo "RSSHub stopped."

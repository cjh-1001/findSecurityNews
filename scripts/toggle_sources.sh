#!/usr/bin/env bash
# 一键切换国外源 on/off
# 用法: scripts/toggle_sources.sh on|off
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

ACTION="${1:-}"

if [[ "$ACTION" != "on" && "$ACTION" != "off" ]]; then
  echo "用法: $0 [on|off]" >&2
  exit 1
fi

PYTHON="${PYTHON_BIN:-python3}"

"$PYTHON" - "$ACTION" "$PROJECT_DIR/config/sources.toml" <<'PYEOF'
import sys, re

action = sys.argv[1]    # on or off
config = sys.argv[2]

target = "true" if action == "on" else "false"
current = "false" if action == "on" else "true"

FOREIGN = [
    "security_affairs_security",
    "group_ib_blog",
    "securityonline_info",
    "malwarebytes_blog",
    "cyble_blog",
    "cybersecurity360_news",
    "krebs_on_security",
]

text = open(config).read()

for name in FOREIGN:
    # Match: [[sources]]\nname = "name"\n...whatever...\nenabled = current
    pattern = rf'(\[\[sources\]\]\nname = "{name}".*?enabled = ){current}'
    new_text, n = re.subn(pattern, rf'\1{target}', text, flags=re.DOTALL)
    if n > 0:
        text = new_text
        print(f"  {name} -> {target}")
    else:
        print(f"  {name}: already {target}")

open(config, "w").write(text)
print(f"\nDone. Foreign sources {'enabled' if action == 'on' else 'disabled'}.")
PYEOF

#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

ENV_FILE="$PROJECT_DIR/.env"
VENV_DIR="$PROJECT_DIR/.venv"
DEFAULT_PYTHON_BIN="$VENV_DIR/bin/python"

say() {
  printf '\n==> %s\n' "$1"
}

warn() {
  printf 'WARN: %s\n' "$1" >&2
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

python_is_compatible() {
  command_exists "$1" && "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {
  local candidate
  for candidate in python3.12 python3.11 python3.10 python3 python; do
    if python_is_compatible "$candidate"; then
      echo "$candidate"
      return 0
    fi
  done
  echo ""
}

run_as_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  elif command_exists sudo; then
    sudo "$@"
  else
    warn "This step requires root privileges. Re-run as root or install sudo."
    return 1
  fi
}

detect_package_manager() {
  if command_exists apt-get; then
    echo "apt"
  elif command_exists dnf; then
    echo "dnf"
  elif command_exists yum; then
    echo "yum"
  elif command_exists zypper; then
    echo "zypper"
  elif command_exists pacman; then
    echo "pacman"
  else
    echo ""
  fi
}

install_packages() {
  local package_manager="$1"
  shift
  case "$package_manager" in
    apt)
      run_as_root apt-get update
      run_as_root apt-get install -y "$@"
      ;;
    dnf|yum)
      # Only use core repos — skips broken third-party repos (EPEL etc.)
      if run_as_root "$package_manager" install -y --disablerepo="*" --enablerepo="BaseOS,AppStream,crb,powertools" "$@" 2>&1; then
        return 0
      fi
      # Fallback: allow all repos
      run_as_root "$package_manager" install -y "$@" 2>&1 || warn "Package install failed: $*"
      ;;
    zypper)
      run_as_root zypper --non-interactive install "$@"
      ;;
    pacman)
      run_as_root pacman -Sy --noconfirm "$@"
      ;;
    *)
      warn "Unsupported package manager. Install missing packages manually: $*"
      return 1
      ;;
  esac
}

# Try installing Python 3.10+ for old distros that ship older Python
install_python_for_dnf() {
  # Disable ALL repos, then enable only core ones — bypasses broken EPEL
  local core_repos="BaseOS,AppStream,crb,powertools"
  local candidates=("python3.11" "python3.12" "python3.10" "python3")
  for pkg in "${candidates[@]}"; do
    say "Trying: $pkg (core repos only)"
    if run_as_root dnf install -y --disablerepo="*" --enablerepo="$core_repos" "$pkg" 2>&1; then
      return 0
    fi
  done
  # If core repos fail, try without any repo filter
  for pkg in python3.11 python3.10; do
    say "Trying: $pkg (all repos)"
    if run_as_root dnf install -y "$pkg" 2>&1; then
      return 0
    fi
  done
  return 1
}

# Preemptively disable EPEL repos — their metalinks are often unreachable
fix_broken_repos() {
  if command_exists dnf; then
    say "Disabling EPEL repos (often unreachable)"
    for repo in epel epel-modular epel-testing epel-testing-modular; do
      run_as_root dnf config-manager --set-disabled "$repo" 2>/dev/null || true
    done
    # Also clear stale metadata cache to prevent dnf from trying to refresh EPEL
    run_as_root dnf clean metadata 2>/dev/null || true
  fi
}

ensure_system_dependencies() {
  local package_manager
  local python_bin
  package_manager="$(detect_package_manager)"
  fix_broken_repos
  python_bin="$(find_python)"

  if [[ -z "$python_bin" ]]; then
    say "Installing Python 3.10+"
    case "$package_manager" in
      apt) install_packages "$package_manager" python3 python3-pip python3-venv ;;
      dnf|yum) install_python_for_dnf ;;
      zypper) install_packages "$package_manager" python3 python3-pip ;;
      pacman) install_packages "$package_manager" python python-pip ;;
      *) install_packages "$package_manager" python3 python3-pip ;;
    esac
    python_bin="$(find_python)"
    if [[ -z "$python_bin" ]]; then
      warn "Python 3.10+ is still unavailable after automatic install."
      cat >&2 <<PYHELP

请手动安装 Python 3.10+：

  # CentOS/RHEL/OpenCloudOS 8
  dnf install -y python3.11 python3.11-pip

  # CentOS/RHEL/OpenCloudOS 9
  dnf install -y python3 python3-pip

  # Ubuntu/Debian
  apt-get install -y python3 python3-pip python3-venv

安装后重新运行本脚本。
PYHELP
      return 1
    fi
  fi

  if ! "$python_bin" -m pip --version >/dev/null 2>&1; then
    say "Installing pip"
    case "$package_manager" in
      apt) install_packages "$package_manager" python3-pip python3-venv ;;
      dnf|yum) install_packages "$package_manager" python3-pip python3.11-pip 2>/dev/null || true ;;
      zypper) install_packages "$package_manager" python3-pip ;;
      pacman) install_packages "$package_manager" python-pip ;;
      *) install_packages "$package_manager" python3-pip ;;
    esac
  fi

  if ! command_exists crontab; then
    say "Installing cron"
    case "$package_manager" in
      apt) install_packages "$package_manager" cron ;;
      dnf|yum) install_packages "$package_manager" cronie ;;
      zypper) install_packages "$package_manager" cron ;;
      pacman) install_packages "$package_manager" cronie ;;
      *) install_packages "$package_manager" cron ;;
    esac
  fi
}

start_cron_service() {
  if ! command_exists systemctl; then
    return 0
  fi

  local service
  for service in cron crond; do
    if systemctl list-unit-files "$service.service" >/dev/null 2>&1; then
      run_as_root systemctl enable --now "$service.service" >/dev/null 2>&1 || true
      return 0
    fi
  done
}

ensure_virtualenv() {
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    return 0
  fi

  local python_bin
  python_bin="$(find_python)"
  say "Creating virtual environment: $VENV_DIR"
  if ! "$python_bin" -m venv "$VENV_DIR"; then
    local package_manager
    package_manager="$(detect_package_manager)"
    if [[ "$package_manager" == "apt" ]]; then
      warn "Python venv support is missing. Installing python3-venv."
      install_packages "$package_manager" python3-venv
      "$python_bin" -m venv "$VENV_DIR"
    else
      echo "Failed to create virtual environment. Install Python venv support and re-run this script." >&2
      return 1
    fi
  fi
}

ensure_project_dirs() {
  mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/logs" "$PROJECT_DIR/outputs/daily" \
    "$PROJECT_DIR/outputs/archive" "$PROJECT_DIR/outputs/site"
}

get_existing() {
  local key="$1"
  if [[ -f "$ENV_FILE" ]]; then
    local value
    value="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)"
    value="${value#\'}"
    value="${value%\'}"
    value="${value#\"}"
    value="${value%\"}"
    printf '%s' "$value"
  fi
}

prompt_value() {
  local key="$1"
  local prompt="$2"
  local default="${3:-}"
  local secret="${4:-false}"
  local required="${5:-false}"
  local current
  current="$(get_existing "$key")"
  [[ -n "$current" ]] || current="$default"

  local suffix=""
  if [[ "$secret" == "true" && -n "$current" ]]; then
    suffix=" [configured]"
  elif [[ -n "$current" ]]; then
    suffix=" [$current]"
  fi

  local value=""
  while true; do
    if [[ "$secret" == "true" ]]; then
      read -r -s -p "$prompt$suffix: " value
      echo >&2
    else
      read -r -p "$prompt$suffix: " value
    fi
    if [[ -z "$value" ]]; then
      value="$current"
    fi
    if [[ "$required" != "true" || -n "$value" ]]; then
      printf '%s' "$value"
      return 0
    fi
    warn "$key is required."
  done
}

confirm() {
  local prompt="$1"
  local default="${2:-n}"
  local suffix="[y/N]"
  if [[ "$default" =~ ^[Yy]$ ]]; then
    suffix="[Y/n]"
  fi

  local value
  read -r -p "$prompt $suffix: " value
  if [[ -z "$value" ]]; then
    value="$default"
  fi
  [[ "$value" =~ ^[Yy](es)?$ ]]
}

write_env_line() {
  local key="$1"
  local value="$2"
  if [[ -n "$value" ]]; then
    printf "%s='%s'\n" "$key" "${value//\'/\'\\\'\'}" >> "$ENV_FILE"
  fi
}

configure_env() {
  say "Configuring runtime settings"

  local feishu_required="false"
  if confirm "Will this server push messages to Feishu?" "y"; then
    feishu_required="true"
  fi

  FEISHU_WEBHOOK="$(prompt_value FEISHU_WEBHOOK 'Feishu webhook' '' false "$feishu_required")"
  FEISHU_SECRET="$(prompt_value FEISHU_SECRET 'Feishu signing secret (optional)' '' true)"

  local existing_api_key
  existing_api_key="$(get_existing OPENAI_API_KEY)"
  local default_enable_ai="false"
  [[ -n "$existing_api_key" ]] && default_enable_ai="true"
  ENABLE_AI="$(prompt_value ENABLE_AI 'Enable AI for scheduled workflows? true/false' "$default_enable_ai")"

  AI_PROVIDER="$(prompt_value AI_PROVIDER 'AI provider' 'openai')"
  OPENAI_BASE_URL="$(prompt_value OPENAI_BASE_URL 'AI base URL (optional)' '')"
  OPENAI_API_KEY="$(prompt_value OPENAI_API_KEY 'AI API key (optional)' '' true)"
  OPENAI_MODEL="$(prompt_value OPENAI_MODEL 'AI model' 'gpt-4.1-mini')"
  AI_MAX_TOKENS="$(prompt_value AI_MAX_TOKENS 'AI max output tokens' '8192')"
  COLLECT_LIMIT="$(prompt_value COLLECT_LIMIT 'Collect limit per source' '30')"
  PUSH_LIMIT="$(prompt_value PUSH_LIMIT 'Push limit per workflow' '20')"
  if confirm "Install automatic database cleanup?" "y"; then
    CLEANUP_SCHEDULE="$(prompt_value CLEANUP_SCHEDULE 'Cleanup schedule: weekly/monthly' 'weekly')"
    while [[ "$CLEANUP_SCHEDULE" != "weekly" && "$CLEANUP_SCHEDULE" != "monthly" ]]; do
      warn "Cleanup schedule must be weekly or monthly."
      CLEANUP_SCHEDULE="$(prompt_value CLEANUP_SCHEDULE 'Cleanup schedule: weekly/monthly' 'weekly')"
    done
    CLEANUP_RETENTION_DAYS="$(prompt_value CLEANUP_RETENTION_DAYS 'Keep records for N days before cleanup' '30')"
    while ! [[ "$CLEANUP_RETENTION_DAYS" =~ ^[0-9]+$ ]] || [[ "$CLEANUP_RETENTION_DAYS" -lt 1 ]]; do
      warn "CLEANUP_RETENTION_DAYS must be a positive integer."
      CLEANUP_RETENTION_DAYS="$(prompt_value CLEANUP_RETENTION_DAYS 'Keep records for N days before cleanup' '30')"
    done
    CLEANUP_VACUUM="$(prompt_value CLEANUP_VACUUM 'Run SQLite VACUUM after cleanup? true/false' 'false')"
  else
    CLEANUP_SCHEDULE="none"
    CLEANUP_RETENTION_DAYS="$(prompt_value CLEANUP_RETENTION_DAYS 'Keep records for N days before manual cleanup' '30')"
    CLEANUP_VACUUM="$(prompt_value CLEANUP_VACUUM 'Run SQLite VACUUM after cleanup? true/false' 'false')"
  fi
  PYTHON_BIN="$(prompt_value PYTHON_BIN 'Python command' "$DEFAULT_PYTHON_BIN" false true)"
  ENABLE_DASHBOARD="$(prompt_value ENABLE_DASHBOARD 'Enable built-in web dashboard? true/false' 'false')"
  ENABLE_RSSHUB="$(prompt_value ENABLE_RSSHUB 'Enable RSSHub (for WeChat MP sources)? true/false' 'false')"

  umask 077
  : > "$ENV_FILE"
  write_env_line FEISHU_WEBHOOK "$FEISHU_WEBHOOK"
  write_env_line FEISHU_SECRET "$FEISHU_SECRET"
  write_env_line ENABLE_AI "$ENABLE_AI"
  write_env_line AI_PROVIDER "$AI_PROVIDER"
  write_env_line OPENAI_BASE_URL "$OPENAI_BASE_URL"
  write_env_line OPENAI_API_KEY "$OPENAI_API_KEY"
  write_env_line OPENAI_MODEL "$OPENAI_MODEL"
  write_env_line AI_MAX_TOKENS "$AI_MAX_TOKENS"
  write_env_line COLLECT_LIMIT "$COLLECT_LIMIT"
  write_env_line PUSH_LIMIT "$PUSH_LIMIT"
  write_env_line CLEANUP_SCHEDULE "$CLEANUP_SCHEDULE"
  write_env_line CLEANUP_RETENTION_DAYS "$CLEANUP_RETENTION_DAYS"
  write_env_line CLEANUP_VACUUM "$CLEANUP_VACUUM"
  write_env_line PYTHON_BIN "$PYTHON_BIN"
  write_env_line ENABLE_DASHBOARD "$ENABLE_DASHBOARD"
  write_env_line ENABLE_RSSHUB "$ENABLE_RSSHUB"

  echo "Wrote $ENV_FILE. Secrets are stored locally in plaintext."
}

install_python_dependencies() {
  say "Installing Python dependencies"
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -e .
}

initialize_database() {
  say "Initializing database"
  "$PYTHON_BIN" run.py init-db
}

install_schedules() {
  if confirm "Install cron jobs for 08:00 morning and 20:00 evening workflows?" "y"; then
    scripts/install_cron.sh
  else
    warn "Cron installation skipped. Run scripts/install_cron.sh later if needed."
  fi

  if [[ "${CLEANUP_SCHEDULE:-none}" == "none" ]]; then
    scripts/install_cleanup_cron.sh none
  else
    scripts/install_cleanup_cron.sh "$CLEANUP_SCHEDULE"
  fi
}

run_optional_tests() {
  say "Running local smoke test"
  "$PYTHON_BIN" run.py list --limit 1 >/dev/null

  if confirm "Run a live workflow test now? This will crawl sources and may push to Feishu." "n"; then
    scripts/run_feishu.sh latest
  fi
}

print_summary() {
  say "Deployment complete"
  cat <<EOF
Project: $PROJECT_DIR
Python:  $PYTHON_BIN
Env:     $ENV_FILE
Logs:    $PROJECT_DIR/logs/feishu.log

Useful commands:
  scripts/run_feishu.sh latest
  scripts/run_feishu.sh day
  scripts/run_feishu.sh morning
  scripts/run_feishu.sh evening
  scripts/run_cleanup.sh
  scripts/install_cleanup_cron.sh weekly
  scripts/install_cleanup_cron.sh monthly
  scripts/install_cleanup_cron.sh none
  crontab -l | grep findSecurityNews
  tail -f logs/feishu.log
  tail -f logs/cleanup.log

Dashboard:
  $PYTHON_BIN run.py dashboard --host 127.0.0.1 --port 8000
  (Set ENABLE_DASHBOARD=true in .env first if you want the web dashboard.)

RSSHub (WeChat MP sources):
  docker compose up -d     # start RSSHub
  docker compose down      # stop RSSHub
  docker compose ps        # check status
  http://127.0.0.1:1200    # local endpoint
  (Set ENABLE_RSSHUB=true in .env to check RSSHub health before each workflow run.)

If cron should follow Beijing time, set the server timezone:
  sudo timedatectl set-timezone Asia/Shanghai
EOF
}

main() {
  say "findSecurityNews interactive Linux deployment"
  ensure_system_dependencies
  start_cron_service
  ensure_virtualenv
  ensure_project_dirs
  chmod +x scripts/*.sh
  configure_env
  install_python_dependencies
  initialize_database
  install_schedules
  run_optional_tests
  print_summary
}

main "$@"

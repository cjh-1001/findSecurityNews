#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

ENV_FILE="$PROJECT_DIR/.env"
VENV_DIR="$PROJECT_DIR/.venv"

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

find_python() {
  if command_exists python3; then
    echo "python3"
  elif command_exists python && python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    echo "python"
  else
    echo ""
  fi
}

run_as_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  elif command_exists sudo; then
    sudo "$@"
  else
    echo "This step requires root privileges. Re-run as root or install sudo." >&2
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
    dnf)
      run_as_root dnf install -y "$@"
      ;;
    yum)
      run_as_root yum install -y "$@"
      ;;
    zypper)
      run_as_root zypper --non-interactive install "$@"
      ;;
    pacman)
      run_as_root pacman -Sy --noconfirm "$@"
      ;;
    *)
      echo "Unsupported package manager. Install missing packages manually: $*" >&2
      return 1
      ;;
  esac
}

ensure_system_dependencies() {
  local package_manager
  local python_bin
  package_manager="$(detect_package_manager)"
  python_bin="$(find_python)"

  if [[ -z "$python_bin" ]]; then
    echo "Python 3.10+ not found. Installing Python..."
    case "$package_manager" in
      apt) install_packages "$package_manager" python3 python3-pip python3-venv ;;
      dnf|yum) install_packages "$package_manager" python3 python3-pip ;;
      zypper) install_packages "$package_manager" python3 python3-pip ;;
      pacman) install_packages "$package_manager" python python-pip ;;
      *) install_packages "$package_manager" python3 python3-pip ;;
    esac
    python_bin="$(find_python)"
    if [[ -z "$python_bin" ]]; then
      echo "Python 3.10+ is still unavailable after installation." >&2
      return 1
    fi
  fi

  if ! "$python_bin" -m pip --version >/dev/null 2>&1; then
    echo "pip for $python_bin not found. Installing pip..."
    case "$package_manager" in
      apt) install_packages "$package_manager" python3-pip python3-venv ;;
      dnf|yum) install_packages "$package_manager" python3-pip ;;
      zypper) install_packages "$package_manager" python3-pip ;;
      pacman) install_packages "$package_manager" python-pip ;;
      *) install_packages "$package_manager" python3-pip ;;
    esac
  fi

  if ! command_exists crontab; then
    echo "crontab not found. Installing cron..."
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

  for service in cron crond; do
    if systemctl list-unit-files "$service.service" >/dev/null 2>&1; then
      run_as_root systemctl enable --now "$service.service" >/dev/null 2>&1 || true
      return 0
    fi
  done
}

ensure_virtualenv() {
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    local python_bin
    python_bin="$(find_python)"
    echo "Creating virtual environment: $VENV_DIR"
    if ! "$python_bin" -m venv "$VENV_DIR"; then
      local package_manager
      package_manager="$(detect_package_manager)"
      if [[ "$package_manager" == "apt" ]]; then
        echo "python3 venv support is missing. Installing python3-venv..."
        install_packages "$package_manager" python3-venv
        "$python_bin" -m venv "$VENV_DIR"
      else
        echo "Failed to create virtual environment. Install Python venv support and re-run this script." >&2
        return 1
      fi
    fi
  fi
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
  if [[ "$secret" == "true" ]]; then
    read -r -s -p "$prompt$suffix: " value
    echo >&2
  else
    read -r -p "$prompt$suffix: " value
  fi
  if [[ -n "$value" ]]; then
    printf '%s' "$value"
  else
    printf '%s' "$current"
  fi
}

write_env_line() {
  local key="$1"
  local value="$2"
  if [[ -n "$value" ]]; then
    printf "%s='%s'\n" "$key" "${value//\'/\'\\\'\'}" >> "$ENV_FILE"
  fi
}

ensure_system_dependencies
start_cron_service
ensure_virtualenv

DEFAULT_PYTHON_BIN="$VENV_DIR/bin/python"

FEISHU_WEBHOOK="$(prompt_value FEISHU_WEBHOOK 'Feishu webhook')"
FEISHU_SECRET="$(prompt_value FEISHU_SECRET 'Feishu signing secret (optional)' '' true)"
AI_PROVIDER="$(prompt_value AI_PROVIDER 'AI provider' 'openai')"
OPENAI_BASE_URL="$(prompt_value OPENAI_BASE_URL 'AI base URL (optional)' '')"
OPENAI_API_KEY="$(prompt_value OPENAI_API_KEY 'AI API key (optional)' '' true)"
OPENAI_MODEL="$(prompt_value OPENAI_MODEL 'AI model' 'gpt-4.1-mini')"
AI_MAX_TOKENS="$(prompt_value AI_MAX_TOKENS 'AI max output tokens' '4096')"
DEFAULT_ENABLE_AI="false"
[[ -n "$OPENAI_API_KEY" ]] && DEFAULT_ENABLE_AI="true"
ENABLE_AI="$(prompt_value ENABLE_AI 'Enable AI for scheduled pushes? true/false' "$DEFAULT_ENABLE_AI")"
COLLECT_LIMIT="$(prompt_value COLLECT_LIMIT 'Collect limit' '30')"
PUSH_LIMIT="$(prompt_value PUSH_LIMIT 'Push limit' '20')"
PYTHON_BIN="$(prompt_value PYTHON_BIN 'Python command' "$DEFAULT_PYTHON_BIN")"

umask 077
: > "$ENV_FILE"
write_env_line FEISHU_WEBHOOK "$FEISHU_WEBHOOK"
write_env_line FEISHU_SECRET "$FEISHU_SECRET"
write_env_line AI_PROVIDER "$AI_PROVIDER"
write_env_line OPENAI_BASE_URL "$OPENAI_BASE_URL"
write_env_line OPENAI_API_KEY "$OPENAI_API_KEY"
write_env_line OPENAI_MODEL "$OPENAI_MODEL"
write_env_line AI_MAX_TOKENS "$AI_MAX_TOKENS"
write_env_line ENABLE_AI "$ENABLE_AI"
write_env_line COLLECT_LIMIT "$COLLECT_LIMIT"
write_env_line PUSH_LIMIT "$PUSH_LIMIT"
write_env_line PYTHON_BIN "$PYTHON_BIN"

echo "Wrote .env with configured values. Secrets are stored locally in plaintext."

chmod +x scripts/*.sh

echo "Installing Python dependencies..."
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -e .

echo "Initializing database..."
"$PYTHON_BIN" run.py init-db

read -r -p "Install cron jobs for 08:00 and 20:00? y/N: " INSTALL_CRON
if [[ "$INSTALL_CRON" =~ ^[Yy](es)?$ ]]; then
  scripts/install_cron.sh
fi

echo "Setup complete."
echo "Test push: $PYTHON_BIN run.py push-feishu --limit 3"
echo "AI workflow: scripts/run_feishu.sh evening"

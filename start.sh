#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"

log() {
  printf '\n==> %s\n' "$1"
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

read_env_value() {
  local key_name="$1"

  if [ ! -f "$ENV_FILE" ]; then
    return
  fi

  local line
  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key_name}=" "$ENV_FILE" | tail -n 1 || true)"
  if [ -z "$line" ]; then
    return
  fi

  local value="${line#*=}"
  value="${value%$'\r'}"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "$value"
}

load_env_api_keys() {
  if [ -z "${OPENAI_API_KEY:-}" ]; then
    local openai_key
    openai_key="$(read_env_value OPENAI_API_KEY)"
    if [ -n "$openai_key" ]; then
      export OPENAI_API_KEY="$openai_key"
    fi
  fi

  if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    local anthropic_key
    anthropic_key="$(read_env_value ANTHROPIC_API_KEY)"
    if [ -n "$anthropic_key" ]; then
      export ANTHROPIC_API_KEY="$anthropic_key"
    fi
  fi
}

write_env_api_key() {
  local key_name="$1"
  local key="$2"
  local tmp_file

  tmp_file="$(mktemp)"
  if [ -f "$ENV_FILE" ]; then
    grep -v -E "^[[:space:]]*(export[[:space:]]+)?${key_name}=" "$ENV_FILE" >"$tmp_file" || true
  fi
  printf '%s=%s\n' "$key_name" "$key" >>"$tmp_file"
  mv "$tmp_file" "$ENV_FILE"
}

prompt_for_api_key() {
  if [ -n "${OPENAI_API_KEY:-}" ] || [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    return
  fi

  local provider
  read -r -p 'Choose a model provider (openai/anthropic): ' provider
  provider="$(printf '%s' "$provider" | tr '[:upper:]' '[:lower:]')"

  if [ "$provider" = "openai" ]; then
    read -r -s -p 'Enter your OpenAI API key: ' OPENAI_API_KEY
    printf '\n'

    if [ -z "$OPENAI_API_KEY" ]; then
      fail "OPENAI_API_KEY cannot be empty"
    fi

    export OPENAI_API_KEY
    write_env_api_key OPENAI_API_KEY "$OPENAI_API_KEY"
    log "Saved OPENAI_API_KEY to .env"
    return
  fi

  if [ "$provider" != "anthropic" ]; then
    fail "Provider must be openai or anthropic"
  fi

  read -r -s -p 'Enter your Anthropic API key: ' ANTHROPIC_API_KEY
  printf '\n'

  if [ -z "$ANTHROPIC_API_KEY" ]; then
    fail "ANTHROPIC_API_KEY cannot be empty"
  fi

  export ANTHROPIC_API_KEY
  write_env_api_key ANTHROPIC_API_KEY "$ANTHROPIC_API_KEY"
  log "Saved ANTHROPIC_API_KEY to .env"
}

main() {
  cd "$ROOT_DIR"

  require_command uv

  load_env_api_keys
  prompt_for_api_key

  log "Installing Python dependencies"
  uv sync

  if [ "${1:-}" = "--check" ]; then
    log "Running the agent against the scripted checks"
    uv run python scripts/check_agent.py
    return
  fi

  log "Starting terminal chat"
  uv run retail-support "$@"
}

main "$@"

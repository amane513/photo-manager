#!/usr/bin/env bash

set -euo pipefail

die() {
  printf 'エラー: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "必要なコマンドが見つからない: $1"
}

run() {
  if [[ "${DRY_RUN:-false}" == true ]]; then
    printf '+ '
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

load_host_config() {
  local config_path=$1
  [[ -r "$config_path" ]] || die "ホスト設定を読めない: $config_path"
  # shellcheck disable=SC1090
  source "$config_path"

  local required
  for required in \
    PRIMARY_STORAGE_UUID PRIMARY_STORAGE_FSTYPE ARCHIVE_MOUNT \
    ARCHIVE_OWNER ARCHIVE_GROUP SMB_SHARE_NAME SMB_VALID_USER; do
    [[ -n "${!required:-}" ]] || die "ホスト設定に $required がない"
  done
}

require_root() {
  [[ ${EUID} -eq 0 ]] || die 'sudoで実行すること'
}

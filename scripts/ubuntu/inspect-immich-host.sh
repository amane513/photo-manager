#!/usr/bin/env bash
# Immich導入の前提を変更せずに報告する。
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/../lib/common.sh"

CONFIG_PATH=
while (($#)); do
  case "$1" in
    --host-config) CONFIG_PATH=${2:?}; shift 2 ;;
    -h|--help) printf '使い方: inspect-immich-host.sh --host-config FILE\n'; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done
[[ -n "$CONFIG_PATH" ]] || die '--host-config を指定すること'
load_host_config "$CONFIG_PATH"
for name in IMMICH_ROOT IMMICH_LAN_BIND_ADDRESS IMMICH_PORT IMMICH_VERSION ARCHIVE_LIBRARY_ROOT; do
  [[ -n "${!name:-}" ]] || die "ホスト設定に $name がない"
done

printf 'OS:\n'; (grep -E '^(PRETTY_NAME)=' /etc/os-release || true)
printf 'アーキテクチャ: '; uname -m
printf 'メモリ:\n'; free -h
printf 'Immich SSD (%s):\n' "$IMMICH_ROOT"; df -hT "$(dirname "$IMMICH_ROOT")"
printf '主HDD:\n'; findmnt -no SOURCE,TARGET,FSTYPE,OPTIONS "$ARCHIVE_MOUNT"
printf 'ライブラリルート: '; readlink -f "$ARCHIVE_LIBRARY_ROOT"
[[ ! -L "$ARCHIVE_LIBRARY_ROOT" ]] || die 'ARCHIVE_LIBRARY_ROOTがシンボリックリンクである'
printf 'Docker:\n'; docker --version 2>&1 || true; docker compose version 2>&1 || true
printf 'NVIDIA:\n'; nvidia-smi 2>&1 || true
printf 'NVIDIA Container Toolkit:\n'; nvidia-container-cli --version 2>&1 || true
printf 'Docker NVIDIA runtime:\n'; docker info --format '{{json .Runtimes}}' 2>&1 || true
printf '既存コンテナ:\n'; docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' 2>&1 || true
if [[ -e "$IMMICH_ROOT" ]]; then
  printf '既存のImmichルート:\n'; find "$IMMICH_ROOT" -mindepth 1 -maxdepth 2 -printf '%y %p\n'
else
  printf 'Immichルートは未作成である。\n'
fi

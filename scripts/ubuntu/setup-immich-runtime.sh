#!/usr/bin/env bash
# DockerとNVIDIA Container Toolkitの不足を表示し、明示時だけ導入する。
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/../lib/common.sh"
DRY_RUN=false
INSTALL=false
while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --install-missing) INSTALL=true; shift ;;
    -h|--help) printf '使い方: sudo setup-immich-runtime.sh [--dry-run] [--install-missing]\n'; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done
require_root
missing=()
command -v docker >/dev/null || missing+=(docker)
docker compose version >/dev/null 2>&1 || missing+=(docker-compose-plugin)
command -v nvidia-smi >/dev/null || missing+=(nvidia-driver-545-or-newer)
command -v nvidia-ctk >/dev/null || missing+=(nvidia-container-toolkit)
if ((${#missing[@]} == 0)); then
  printf 'OK: Docker、Compose、NVIDIAドライバー、NVIDIA Container Toolkitを検出した。\n'
  exit 0
fi
printf '不足または未検出: %s\n' "${missing[*]}"
[[ "$INSTALL" == true ]] || die '--install-missing を指定しない限り変更しない'
die '不足ランタイムの導入は公式Docker/NVIDIAリポジトリ設定を伴う。既存Docker構成を確認してから、公式手順に従い個別に導入すること'

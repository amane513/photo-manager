#!/usr/bin/env bash
# Ubuntuのphoto-copy受信環境へExifToolとrsyncを導入する。

set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

DRY_RUN=false
while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) printf '使い方: sudo setup-copy-receiver.sh [--dry-run]\n'; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done

require_root
require_command apt-get
require_command dpkg-query

missing=()
for package in rsync libimage-exiftool-perl; do
  dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null | grep -Fxq installed || missing+=("$package")
done

if ((${#missing[@]})); then
  run apt-get update
  run apt-get install --yes "${missing[@]}"
else
  printf 'rsyncとExifToolは導入済み。更新は行わない。\n'
fi

printf '完了: 受信環境の依存コマンドを確認した。続けてverify-copy-receiver.shを実行すること。\n'

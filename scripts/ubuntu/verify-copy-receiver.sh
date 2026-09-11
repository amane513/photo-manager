#!/usr/bin/env bash
# Ubuntuのphoto-copy受信環境を変更せずに検査する。

set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

CONFIG_PATH=
while (($#)); do
  case "$1" in
    --host-config) CONFIG_PATH=${2:?}; shift 2 ;;
    -h|--help) printf '使い方: sudo verify-copy-receiver.sh --host-config FILE\n'; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done

[[ -n "$CONFIG_PATH" ]] || die '--host-config を指定すること'
load_host_config "$CONFIG_PATH"
require_root
require_command exiftool
require_command rsync
require_command findmnt

mountpoint -q "$ARCHIVE_MOUNT" || die "未マウント: $ARCHIVE_MOUNT"
actual_uuid=$(findmnt -n -o UUID --target "$ARCHIVE_MOUNT")
[[ "$actual_uuid" == "$PRIMARY_STORAGE_UUID" ]] || die "想定外のマウント元UUID: ${actual_uuid:-不明}"
sudo -u "$ARCHIVE_OWNER" test -w "$ARCHIVE_MOUNT" || die "保存アカウントが主HDDへ書き込めない: $ARCHIVE_OWNER"
rsync_version=$(rsync --version | sed -n '1s/^rsync  version \([0-9.]*\).*/\1/p')
[[ "$rsync_version" =~ ^3\.2\.[6-9]$|^3\.[3-9]\. ]] || die "rsync 3.2.6以上が必要: ${rsync_version:-不明}"
printf 'OK: 主HDD（UUID %s）、書込み権限、rsync %s、ExifTool %sを確認した。\n' \
  "$PRIMARY_STORAGE_UUID" "$rsync_version" "$(exiftool -ver)"

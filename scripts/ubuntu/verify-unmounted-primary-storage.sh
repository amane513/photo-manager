#!/usr/bin/env bash
# HDDを手動で安全にアンマウントした直後に実行し、SSDへの誤書込みを防げることを検査する。

set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

CONFIG_PATH=
while (($#)); do
  case "$1" in
    --host-config) CONFIG_PATH=${2:?}; shift 2 ;;
    -h|--help) printf '使い方: verify-unmounted-primary-storage.sh --host-config FILE\n'; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done
[[ -n "$CONFIG_PATH" ]] || die '--host-config を指定すること'
load_host_config "$CONFIG_PATH"
[[ -n "${ARCHIVE_LIBRARY_ROOT:-}" ]] || die "ホスト設定に ARCHIVE_LIBRARY_ROOT がない"
require_root

mountpoint -q "$ARCHIVE_MOUNT" && die "HDDがまだマウントされている。先に sudo umount $ARCHIVE_MOUNT を実行すること"
[[ $(stat -c '%U:%G' "$ARCHIVE_MOUNT") == root:root ]] || die 'アンマウント時のマウントポイントがroot所有ではない'
[[ $(stat -c '%a' "$ARCHIVE_MOUNT") == 755 ]] || die 'アンマウント時のマウントポイントの権限が0755ではない'
[[ -e "$ARCHIVE_LIBRARY_ROOT" ]] && die "未マウント時にライブラリルートが見えている。SSD側に誤って作られていないか確認すること: $ARCHIVE_LIBRARY_ROOT"
if sudo -u "$ARCHIVE_OWNER" touch "$ARCHIVE_MOUNT/.photo-manager-unmounted-write-test" 2>/dev/null; then
  rm -f "$ARCHIVE_MOUNT/.photo-manager-unmounted-write-test"
  die '未マウントのマウントポイントへ書き込めた。SSDへの誤書込みを防げていない'
fi
printf 'OK: 未マウント時、%s は %s による書込みを拒否し、ライブラリルートも存在しない。\n' "$ARCHIVE_MOUNT" "$ARCHIVE_OWNER"

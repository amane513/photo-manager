#!/usr/bin/env bash
# 主HDD上にライブラリルート（年フォルダの置き場）を作成する。

set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

DRY_RUN=false
CONFIG_PATH=

usage() {
  printf '使い方: sudo setup-library-root.sh --host-config FILE [--dry-run]\n'
}

while (($#)); do
  case "$1" in
    --host-config) CONFIG_PATH=${2:?}; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done

[[ -n "$CONFIG_PATH" ]] || die '--host-config を指定すること'
load_host_config "$CONFIG_PATH"
[[ -n "${ARCHIVE_LIBRARY_ROOT:-}" ]] || die "ホスト設定に ARCHIVE_LIBRARY_ROOT がない"
require_root
require_command findmnt

mountpoint -q "$ARCHIVE_MOUNT" || die "主HDDが未マウントである: $ARCHIVE_MOUNT"
case "$ARCHIVE_LIBRARY_ROOT" in
  "$ARCHIVE_MOUNT"/*) ;;
  *) die "ARCHIVE_LIBRARY_ROOTが$ARCHIVE_MOUNT配下にない: $ARCHIVE_LIBRARY_ROOT" ;;
esac

if [[ -e "$ARCHIVE_LIBRARY_ROOT" ]]; then
  [[ -d "$ARCHIVE_LIBRARY_ROOT" ]] || die "ライブラリルートがディレクトリではない: $ARCHIVE_LIBRARY_ROOT"
  actual_owner=$(stat -c '%U:%G' "$ARCHIVE_LIBRARY_ROOT")
  [[ "$actual_owner" == "$ARCHIVE_OWNER:$ARCHIVE_GROUP" ]] || die "既存のライブラリルートの所有者が想定と異なる: $actual_owner"
  actual_mode=$(stat -c '%a' "$ARCHIVE_LIBRARY_ROOT")
  [[ "$actual_mode" == 755 ]] || die "既存のライブラリルートの権限が0755ではない: $actual_mode"
  printf '既存のライブラリルートは設定済み: %s\n' "$ARCHIVE_LIBRARY_ROOT"
else
  run install -d -o "$ARCHIVE_OWNER" -g "$ARCHIVE_GROUP" -m 0755 "$ARCHIVE_LIBRARY_ROOT"
  printf '完了: ライブラリルートを作成した: %s\n' "$ARCHIVE_LIBRARY_ROOT"
fi

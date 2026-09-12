#!/usr/bin/env bash
# 主HDD・fstab・Sambaサービスの通常状態を検査する。

set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

CONFIG_PATH=
while (($#)); do
  case "$1" in
    --host-config) CONFIG_PATH=${2:?}; shift 2 ;;
    -h|--help) printf '使い方: verify-primary-storage.sh --host-config FILE\n'; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done
[[ -n "$CONFIG_PATH" ]] || die '--host-config を指定すること'
load_host_config "$CONFIG_PATH"
[[ -n "${ARCHIVE_LIBRARY_ROOT:-}" ]] || die "ホスト設定に ARCHIVE_LIBRARY_ROOT がない"
require_root
require_command findmnt
require_command systemctl
require_command testparm
require_command pdbedit

expected_device=$(blkid -U "$PRIMARY_STORAGE_UUID") || die "UUIDが見つからない: $PRIMARY_STORAGE_UUID"
mountpoint -q "$ARCHIVE_MOUNT" || die "未マウント: $ARCHIVE_MOUNT"
actual_device=$(findmnt -n -o SOURCE --target "$ARCHIVE_MOUNT")
[[ "$actual_device" == "$expected_device" ]] || die "想定外のマウント元: $actual_device"
[[ $(stat -c '%U:%G' "$ARCHIVE_MOUNT") == "$ARCHIVE_OWNER:$ARCHIVE_GROUP" ]] || die 'マウント先の所有者またはグループが違う'
[[ $(stat -c '%a' "$ARCHIVE_MOUNT") == 755 ]] || die 'マウント先の権限が0755ではない'
awk -v uuid="UUID=$PRIMARY_STORAGE_UUID" -v mount="$ARCHIVE_MOUNT" '$1 == uuid && $2 == mount { found=1 } END { exit !found }' /etc/fstab || die 'fstabに対象のUUIDマウント設定がない'
[[ -d "$ARCHIVE_LIBRARY_ROOT" ]] || die "ライブラリルートがない: $ARCHIVE_LIBRARY_ROOT"
[[ $(stat -c '%U:%G' "$ARCHIVE_LIBRARY_ROOT") == "$ARCHIVE_OWNER:$ARCHIVE_GROUP" ]] || die 'ライブラリルートの所有者またはグループが違う'
[[ $(stat -c '%a' "$ARCHIVE_LIBRARY_ROOT") == 755 ]] || die 'ライブラリルートの権限が0755ではない'
testparm -s >/dev/null
share_parameters=$(testparm -s --section-name="$SMB_SHARE_NAME")
printf '%s\n' "$share_parameters" | grep -Fq "path = $ARCHIVE_MOUNT" || die 'Samba共有のパスが違う'
printf '%s\n' "$share_parameters" | grep -Fq 'read only = No' || die 'Samba共有が書込み可能ではない'
printf '%s\n' "$share_parameters" | grep -Fq "valid users = $SMB_VALID_USER" || die 'Samba共有の利用者が違う'
pdbedit -L 2>/dev/null | cut -d: -f1 | grep -Fxq "$SMB_VALID_USER" || die 'Samba利用者が登録されていない'
systemctl is-active --quiet smbd || die 'smbdが起動していない'
printf 'OK: 主HDD、fstab、ライブラリルート、権限、Sambaサービスを確認した。共有名: %s、ライブラリルート: %s\n' "$SMB_SHARE_NAME" "$ARCHIVE_LIBRARY_ROOT"

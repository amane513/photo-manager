#!/usr/bin/env bash
# 主HDDのfstab、権限、Samba共有を安全に整備する。

set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

DRY_RUN=false
CONFIG_PATH=
ADOPT_EXISTING_SHARE=false

usage() {
  cat <<'EOF'
使い方: sudo setup-primary-storage.sh --host-config FILE [--dry-run] [--adopt-existing-share]

--adopt-existing-share は、同名の既存Samba共有をこのスクリプト管理の共有へ
明示的に置き換える初回移行時だけ指定する。設定ファイルは退避する。
EOF
}

while (($#)); do
  case "$1" in
    --host-config) CONFIG_PATH=${2:?}; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --adopt-existing-share) ADOPT_EXISTING_SHARE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done

[[ -n "$CONFIG_PATH" ]] || die '--host-config を指定すること'
load_host_config "$CONFIG_PATH"
require_root
require_command blkid
require_command findmnt
require_command mount
require_command testparm
require_command systemctl
require_command pdbedit

device=$(blkid -U "$PRIMARY_STORAGE_UUID") || die "UUIDが見つからない: $PRIMARY_STORAGE_UUID"
actual_type=$(blkid -s TYPE -o value "$device")
[[ "$actual_type" == "$PRIMARY_STORAGE_FSTYPE" ]] || die "ファイルシステムが違う: $actual_type（期待値: $PRIMARY_STORAGE_FSTYPE）"
id "$ARCHIVE_OWNER" >/dev/null || die "所有者ユーザーが存在しない: $ARCHIVE_OWNER"
getent group "$ARCHIVE_GROUP" >/dev/null || die "所有者グループが存在しない: $ARCHIVE_GROUP"
pdbedit -L 2>/dev/null | cut -d: -f1 | grep -Fxq "$SMB_VALID_USER" || die "Samba利用者が未登録: $SMB_VALID_USER。先に sudo smbpasswd -a $SMB_VALID_USER を対話的に実行すること"

fstab_line="UUID=$PRIMARY_STORAGE_UUID $ARCHIVE_MOUNT $PRIMARY_STORAGE_FSTYPE defaults,nofail,x-systemd.device-timeout=30 0 2"
if awk -v mount="$ARCHIVE_MOUNT" '$1 !~ /^#/ && $2 == mount { found=1 } END { exit !found }' /etc/fstab; then
  if ! awk -v uuid="UUID=$PRIMARY_STORAGE_UUID" -v mount="$ARCHIVE_MOUNT" '$1 == uuid && $2 == mount { found=1 } END { exit !found }' /etc/fstab; then
    die "/etc/fstab に $ARCHIVE_MOUNT の既存設定がある。無断で置き換えないため、内容を確認してから移行すること"
  fi
else
  run cp -a /etc/fstab "/etc/fstab.photo-manager.$(date +%Y%m%d%H%M%S).bak"
  if [[ "$DRY_RUN" == true ]]; then
    printf '+ fstabへ追加: %s\n' "$fstab_line"
  else
    printf '\n# photo-manager primary storage\n%s\n' "$fstab_line" >> /etc/fstab
  fi
fi

if mountpoint -q "$ARCHIVE_MOUNT"; then
  mounted_source=$(findmnt -n -o SOURCE --target "$ARCHIVE_MOUNT")
  [[ "$mounted_source" == "$device" ]] || die "$ARCHIVE_MOUNT は想定外のデバイスをマウントしている: $mounted_source"
else
  run install -d -o root -g root -m 0755 "$ARCHIVE_MOUNT"
  run mount "$ARCHIVE_MOUNT"
fi

run chown "$ARCHIVE_OWNER:$ARCHIVE_GROUP" "$ARCHIVE_MOUNT"
run chmod 0755 "$ARCHIVE_MOUNT"

smb_conf=/etc/samba/smb.conf
managed_begin="# BEGIN photo-manager $SMB_SHARE_NAME"
managed_end="# END photo-manager $SMB_SHARE_NAME"
managed_block=$(printf '%s\n[%s]\n    path = %s\n    browseable = yes\n    read only = no\n    valid users = %s\n    create mask = 0664\n    directory mask = 0775\n%s' "$managed_begin" "$SMB_SHARE_NAME" "$ARCHIVE_MOUNT" "$SMB_VALID_USER" "$managed_end")

if grep -Fqx "$managed_begin" "$smb_conf"; then
  existing_block=$(awk -v begin="$managed_begin" -v end="$managed_end" '
    $0 == begin { in_block=1 }
    in_block { print }
    $0 == end { exit }
  ' "$smb_conf")
  [[ "$existing_block" == "$managed_block" ]] || die "既存のスクリプト管理ブロックの内容が想定と異なる。無断更新を防ぐため、手動で確認すること"
  printf '既存のスクリプト管理共有 [%s] は設定済み。\n' "$SMB_SHARE_NAME"
elif grep -Eq "^\\[$SMB_SHARE_NAME\\][[:space:]]*$" "$smb_conf"; then
  [[ "$ADOPT_EXISTING_SHARE" == true ]] || die "同名の既存共有 $SMB_SHARE_NAME を検出した。内容を確認し、初回移行なら --adopt-existing-share を指定すること"
  run cp -a "$smb_conf" "$smb_conf.photo-manager.$(date +%Y%m%d%H%M%S).bak"
  if [[ "$DRY_RUN" == true ]]; then
    printf '+ 既存の [%s] 共有を管理ブロックへ置換\n' "$SMB_SHARE_NAME"
  else
    awk -v share="$SMB_SHARE_NAME" -v replacement="$managed_block" '
      BEGIN { in_share=0; replaced=0 }
      $0 == "[" share "]" { in_share=1; if (!replaced) { print replacement; replaced=1 }; next }
      in_share && /^\[/ { in_share=0 }
      !in_share { print }
      END { if (!replaced) exit 1 }
    ' "$smb_conf" > "$smb_conf.new"
    testparm -s "$smb_conf.new" >/dev/null
    mv "$smb_conf.new" "$smb_conf"
  fi
else
  run cp -a "$smb_conf" "$smb_conf.photo-manager.$(date +%Y%m%d%H%M%S).bak"
  if [[ "$DRY_RUN" == true ]]; then
    printf '+ smb.confへ共有を追加: [%s]\n' "$SMB_SHARE_NAME"
  else
    printf '\n%s\n' "$managed_block" >> "$smb_conf"
    testparm -s "$smb_conf" >/dev/null
  fi
fi

run systemctl enable --now smbd
printf '完了: %s を %s としてマウントし、SMB共有 %s を設定した。\n' "$device" "$ARCHIVE_MOUNT" "$SMB_SHARE_NAME"

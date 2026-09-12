#!/usr/bin/env bash
# CameraArchive共有のマウント状態、読み書き可否、LaunchAgentの登録を検査する。

set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

CONFIG_PATH=
while (($#)); do
  case "$1" in
    --host-config) CONFIG_PATH=${2:?}; shift 2 ;;
    -h|--help) printf '使い方: verify-smb-mount.sh --host-config FILE\n'; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done
[[ -n "$CONFIG_PATH" ]] || die '--host-config を指定すること'
load_host_config "$CONFIG_PATH"
[[ -n "${SMB_SERVER:-}" ]] || die "ホスト設定に SMB_SERVER がない"
require_command launchctl

mount_point="/Volumes/$SMB_SHARE_NAME"
mount | grep -Fq " on $mount_point (smbfs" || die "未マウント: $mount_point"

test_file="$mount_point/.photo-manager-smb-mount-test-$$"
if ! ( : > "$test_file" ) 2>/dev/null; then
  die "$mount_point への書き込みに失敗した"
fi
rm -f "$test_file"

plist_label="com.photo-manager.mount-${SMB_SHARE_NAME}"
plist_path="$HOME/Library/LaunchAgents/${plist_label}.plist"
[[ -f "$plist_path" ]] || die "LaunchAgentの設定ファイルがない: $plist_path"
launchctl print "gui/$(id -u)/$plist_label" >/dev/null 2>&1 || die "LaunchAgentが読み込まれていない: $plist_label"

printf 'OK: %s はマウント済みで読み書き可能。LaunchAgent %s が読み込まれている。\n' "$mount_point" "$plist_label"

#!/usr/bin/env bash
# Macログイン時にCameraArchive共有を自動マウントするLaunchAgentを設定する。
# キーチェーンへのパスワード保存は対象外とし、既存の登録を前提とする。

set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

DRY_RUN=false
CONFIG_PATH=

usage() {
  printf '使い方: setup-smb-mount.sh --host-config FILE [--dry-run]\n'
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
[[ -n "${SMB_SERVER:-}" ]] || die "ホスト設定に SMB_SERVER がない"
CONFIG_PATH_ABS=$(cd -- "$(dirname -- "$CONFIG_PATH")" && pwd)/$(basename -- "$CONFIG_PATH")
require_command security
require_command osascript
require_command launchctl

mount_script="$SCRIPT_DIR/mount-camera-archive.sh"
[[ -x "$mount_script" ]] || die "マウントスクリプトが見つからない: $mount_script"

security find-internet-password -a "$SMB_VALID_USER" -s "$SMB_SERVER" -r "smb " >/dev/null 2>&1 \
  || die "キーチェーンにSMB認証情報がない。先にFinderで smb://${SMB_VALID_USER}@${SMB_SERVER}/${SMB_SHARE_NAME} へ接続し、パスワードをキーチェーンへ保存すること"

plist_label="com.photo-manager.mount-${SMB_SHARE_NAME}"
plist_path="$HOME/Library/LaunchAgents/${plist_label}.plist"
log_path="$HOME/Library/Logs/photo-manager-mount-${SMB_SHARE_NAME}.log"
plist_content=$(cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>${plist_label}</string>
	<key>ProgramArguments</key>
	<array>
		<string>${mount_script}</string>
		<string>${CONFIG_PATH_ABS}</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>StandardOutPath</key>
	<string>${log_path}</string>
	<key>StandardErrorPath</key>
	<string>${log_path}</string>
</dict>
</plist>
PLIST
)

if [[ -f "$plist_path" ]]; then
  if diff -q <(printf '%s\n' "$plist_content") "$plist_path" >/dev/null 2>&1; then
    printf '既存のLaunchAgentは設定済み: %s\n' "$plist_path"
  else
    die "既存のLaunchAgentの内容が想定と異なる。無断更新を防ぐため、手動で確認すること: $plist_path"
  fi
else
  if [[ "$DRY_RUN" == true ]]; then
    printf '+ LaunchAgentを作成: %s\n' "$plist_path"
  else
    printf '%s\n' "$plist_content" > "$plist_path"
  fi
fi

if launchctl print "gui/$(id -u)/$plist_label" >/dev/null 2>&1; then
  printf 'LaunchAgentは読み込み済み: %s\n' "$plist_label"
else
  run launchctl bootstrap "gui/$(id -u)" "$plist_path"
fi

run "$mount_script" "$CONFIG_PATH_ABS"

printf '完了: ログイン時に /Volumes/%s を自動マウントするLaunchAgentを設定した。\n' "$SMB_SHARE_NAME"

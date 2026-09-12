#!/usr/bin/env bash
# CameraArchive共有がマウント済みでなければマウントする。LaunchAgentから呼ばれる。
# パスワードはキーチェーンに保存済みである前提で、対話プロンプトは出さない。

set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

CONFIG_PATH=${1:?"使い方: mount-camera-archive.sh HOST_CONFIG_FILE"}
load_host_config "$CONFIG_PATH"
[[ -n "${SMB_SERVER:-}" ]] || die "ホスト設定に SMB_SERVER がない"

mount_point="/Volumes/$SMB_SHARE_NAME"
if mount | grep -Fq " on $mount_point (smbfs"; then
  printf '既にマウント済み: %s\n' "$mount_point"
  exit 0
fi

/usr/bin/osascript -e "mount volume \"smb://${SMB_VALID_USER}@${SMB_SERVER}/${SMB_SHARE_NAME}\"" >/dev/null
printf 'マウントした: %s\n' "$mount_point"
